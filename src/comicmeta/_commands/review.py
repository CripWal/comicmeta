"""comicmeta review — run the full read-only review pipeline in one command.

Scans the library directory (default: current directory), discovers ComicVine
candidates, interactively reviews volumes and issues, and emits the CBZ writer
mapping. Every phase is read-only with respect to comic archives. Phases resume
from saved state, so you can step away and return.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from comicmeta._common import color_enabled, Palette, add_examples, die, die_missing_source, load_json, require_tty
from comicmeta._tui import confirm, is_interactive
from comicmeta._commands import discover, fetch_issues, mapping, review_issues, review_volumes


def add_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "review",
        help="scan, discover, and review volumes + issues (read-only)",
        description=__doc__,
    )
    parser.add_argument("--source", "-s", type=Path, default=None, help="comic library root (default: auto-detected)")
    parser.add_argument("--api-key-file", type=Path, help="file containing the ComicVine key")
    parser.add_argument("--api-key-env", default=None, help="environment variable containing the API key")
    parser.add_argument("--no-color", action="store_true", help="disable ANSI colors")
    parser.add_argument("--list", action="store_true", help="print current pipeline state and exit")
    parser.add_argument("--fresh", action="store_true",
                        help="discard prior review state and re-review the whole library from scratch")
    parser.add_argument("--reopen", action="store_true",
                        help="re-open the interactive review even when it looks complete, so you can fix skipped or mis-selected volumes")
    add_examples(parser, [
        "comicmeta review",
        "comicmeta review -s /path/to/comics",
        "comicmeta review --list",
        "comicmeta review --fresh",
        "comicmeta review --reopen",
    ])
    parser.set_defaults(handler=run)


def _defaults(flat: dict | None = None) -> dict:
    from comicmeta import _config
    flat = flat or _config.load(None)
    get = lambda key: _config.get(flat, key)
    return {
        "candidates": Path(get("paths.candidates")),
        "volume_state": Path(get("paths.volume_state")),
        "volume_summary": Path(get("paths.volume_summary")),
        "policy": Path(get("paths.policy")),
        "issue_candidates": Path(get("paths.issue_candidates")),
        "issue_state": Path(get("paths.issue_state")),
        "issue_summary": Path(get("paths.issue_summary")),
        "mapping": Path(get("paths.mapping")),
        "kavita_export": Path(get("paths.kavita_export")),
    }


def _review_required_queries(candidates: dict) -> set[str]:
    """Distinct queries that still need volume review (one selection per query)."""
    return {item.get("query") for item in candidates.get("items", []) if item.get("status") == "review-required"}


def _volume_review_complete(state_path: Path, candidates: dict) -> bool:
    """True only when every required query has a real selection.

    A selection with status ``skipped`` does NOT count: it means the volume is
    held for later, so the review stays open (dashboard can re-open it) while
    the already-approved volumes above remain writable.
    """
    if not state_path.exists():
        return False
    state = load_json(state_path, "volume state")
    completed = {
        query for query, selection in state.get("selections", {}).items()
        if selection.get("status") not in {"skipped", "flagged"}
    }
    return _review_required_queries(candidates) <= completed


def _issue_review_complete(state_path: Path, candidates: dict) -> bool:
    if not state_path.exists():
        return False
    state = load_json(state_path, "issue state")
    reviewed = set(state.get("reviews", {}))
    candidate_paths = {
        match["path"]
        for series in candidates.get("series", [])
        if isinstance(series, dict)
        for match in series.get("matches", [])
        if isinstance(match, dict) and match.get("path") is not None
    }
    return bool(candidate_paths) and candidate_paths <= reviewed


def _policy(flat: dict, paths: dict) -> dict:
    from comicmeta import _config
    policy = load_json(paths["policy"], "policy") if paths["policy"].exists() else {}
    active_source = _config.get(flat, "review.active_source") or policy.get("active_source")
    blocked = _config.get(flat, "review.blocked_queries") or {}
    if isinstance(blocked, dict):
        blocked = {**policy.get("blocked_queries", {}), **blocked}
    if active_source:
        policy["active_source"] = active_source
    if blocked:
        policy["blocked_queries"] = blocked
    return policy


def _api_key(args, flat: dict) -> str:
    from comicmeta import _config, _comicvine
    if args.api_key_env is None:
        args.api_key_env = _config.get(flat, "api.key_env")
    if args.api_key_file is None and _config.get(flat, "api.key_file"):
        args.api_key_file = Path(os.path.expanduser(_config.get(flat, "api.key_file")))
    return _comicvine.api_key_from(args, flat)


def _try_api_key(args, flat: dict) -> str | None:
    """Return the API key if available, else None (no error)."""
    import os
    from comicmeta import _config
    env = args.api_key_env or _config.get(flat, "api.key_env")
    key = os.environ.get(env)
    if not key and args.api_key_file and args.api_key_file.is_file():
        key = args.api_key_file.read_text(encoding="utf-8").strip()
    if not key and _config.get(flat, "api.key_file"):
        path = Path(os.path.expanduser(_config.get(flat, "api.key_file")))
        if path.is_file():
            key = path.read_text(encoding="utf-8").strip()
    if not key and _config.get(flat, "api.keychain"):
        from comicmeta._comicvine import _keychain_read
        key = _keychain_read()
    return key or None


def _status_line(paths: dict) -> None:
    print("  comicmeta review — pipeline state")
    state_dir = paths["candidates"].parent
    print(f"  State dir: {state_dir}")
    for label, path in (
        ("1  discover", paths["candidates"]),
        ("2  volumes ", paths["volume_state"]),
        ("3  issues  ", paths["issue_candidates"]),
        ("4  issue rv", paths["issue_state"]),
        ("5  mapping ", paths["mapping"]),
    ):
        exists = "✓" if path.exists() else "·"
        print(f"   {exists} {label}  {path.name}")
    held = _held_queries(paths)
    if held:
        print(f"   ~ held      {len(held)} volume(s) skipped, still re-openable:")
        for query in sorted(held):
            print(f"     · {query[:60]}")


def _held_queries(paths: dict) -> set[str]:
    """Queries whose volume review was skipped or flagged (held, not done)."""
    state_path = paths["volume_state"]
    if not state_path.is_file():
        return set()
    state = load_json(state_path, "volume state")
    return {
        query for query, selection in state.get("selections", {}).items()
        if selection.get("status") in {"skipped", "flagged"}
    }


def _issue_candidates_stale(state_path: Path, issue_candidates: Path) -> bool:
    """True when issue candidates are missing or don't cover the selected volumes."""
    if not issue_candidates.is_file():
        return True
    try:
        report = load_json(issue_candidates, "issue candidates")
    except SystemExit:
        return True
    fetched = {series.get("query") for series in report.get("series", [])}
    selected = set()
    if state_path.is_file():
        state = load_json(state_path, "volume state")
        for query, selection in state.get("selections", {}).items():
            if selection.get("status") in {"selected", "auto-selected"}:
                selected.add(query)
    if selected and not fetched:
        return True
    return selected != fetched


def run(args: argparse.Namespace) -> None:
    from comicmeta import _config
    colors = Palette(color_enabled(args))
    flat = _config.load(args.source)
    paths = _defaults(flat)
    source = (args.source or Path(_config.get(flat, "paths.source"))).resolve()

    if not source.is_dir():
        die_missing_source(source)

    if args.list:
        _status_line(paths)
        return

    if getattr(args, "fresh", False):
        existing = [path for path in paths.values() if path.exists()]
        if existing:
            print(colors.warn(f"  ⚠ FRESH REVIEW: this discards your current review and starts over."))
            print(colors.warn(f"    It will re-scan and re-query ComicVine for the whole library, and"))
            print(colors.warn(f"    every volume and issue will need to be reviewed again."))
            print()
            print(f"    Existing state to be removed:")
            for path in existing:
                print(f"      - {path.name}")
            print()
            if not confirm("  Discard current review and start fresh?", default=False):
                die("fresh review cancelled")
            for path in existing:
                path.unlink(missing_ok=True)
            print(f"  Cleared {len(existing)} state file(s). Starting fresh.")
        else:
            print("  No prior review state found; starting fresh.")

    # Phase 1: rescan the library (reuses cached candidates for unchanged files)
    api_key = _try_api_key(args, flat)
    limit = _config.as_int(_config.get(flat, "api.candidate_limit"), 10)
    from comicmeta._spinner import Spinner
    with Spinner(f"Scanning {source}") as spinner:
        result = discover.rescan(source, paths["candidates"], api_key, limit=limit, exclude=_config.scan_excludes(flat),
                                 request_delay=_config.as_float(_config.get(flat, "api.request_delay"), 0.25),
                                 concurrency=_config.as_int(_config.get(flat, "api.concurrency"), 5))
        spinner.update("Scan complete")
    if result["needs_api_key"]:
        die(
            f"new files need ComicVine discovery but no API key is set; "
            f"export {_config.get(flat, 'api.key_env')} or set api.key_file in comicmeta.toml"
        )
    print(f"  Scan: {result['reused']} unchanged, {result['queried']} new, {len(result['removed'])} removed")
    if result["added"]:
        for relative in result["added"]:
            print(f"  + {relative}")
    if result["removed"]:
        for relative in result["removed"]:
            print(f"  - {relative}")

    # Phase 1b: CBR disclaimer + optional conversion (metadata can only be written to CBZ)
    from comicmeta._commands.convert import convert_picker, find_cbrs
    cbrs = find_cbrs(source)
    if cbrs:
        print()
        print(colors.warn(f"  ⚠ {len(cbrs)} .cbr file(s) found. Review covers both formats, but"))
        print(colors.warn("    metadata can only be written to .cbz. Convert .cbr → .cbz to write metadata."))
        print(colors.muted(f"    Backups will be kept at: {Path(_config.get(flat, 'paths.backup_dir'))}"))
        if is_interactive():
            if confirm("  Convert .cbr files now?", default=False):
                backup_dir = Path(_config.get(flat, "paths.backup_dir"))
                convert_picker(source, {}, backup_dir, colors,
                               prompt="Select .cbr files to convert before reviewing")
                # Rescan so converted CBZs are picked up as candidates.
                print(f"▸ Re-scanning after conversion")
                result = discover.rescan(source, paths["candidates"], api_key, limit=limit, exclude=_config.scan_excludes(flat),
                                         request_delay=_config.as_float(_config.get(flat, "api.request_delay"), 0.25),
                                         concurrency=_config.as_int(_config.get(flat, "api.concurrency"), 5))
                print(f"  Scan: {result['reused']} unchanged, {result['queried']} new, {len(result['removed'])} removed")
        else:
            print(colors.muted("  Run `comicmeta convert` (or `comicmeta convert --execute`) to convert them."))
        print()

    candidates = load_json(paths["candidates"], "candidates")

    # Phase 2: review volumes (interactive, resumable)
    reopen = getattr(args, "reopen", False)
    if reopen or not _volume_review_complete(paths["volume_state"], candidates):
        require_tty("review-volumes", "comicmeta review --list")
        print("▸ Reviewing volumes (re-opened)" if reopen else "▸ Reviewing volumes")
        policy_data = _policy(flat, paths)
        review_volumes.interactive(
            paths["candidates"], paths["volume_state"], paths["volume_summary"],
            policy_data,
            colors,
            score_threshold=_config.as_int(_config.get(flat, "review.high_confidence_score"), 90),
            score_margin=_config.as_int(_config.get(flat, "review.high_confidence_margin"), 15),
        )
    else:
        print("▸ Volumes already reviewed")

    # Phase 3: fetch issues
    if _issue_candidates_stale(paths["volume_state"], paths["issue_candidates"]):
        print("▸ Fetching issues")
        _api_key(args, flat)
        fetch_issues.run(_fetch_args(args, paths))
    else:
        print("▸ Issues already fetched")

    issue_candidates = load_json(paths["issue_candidates"], "issue candidates")

    # Phase 4: review issues (interactive, resumable)
    issue_items = review_issues.review_items(issue_candidates)
    if not issue_items:
        print("▸ No issue candidates to review")
    elif not _issue_review_complete(paths["issue_state"], issue_candidates):
        require_tty("review-issues", "comicmeta review --list")
        print("▸ Reviewing issues")
        status = review_issues.interactive(
            paths["issue_candidates"], paths["issue_state"], paths["issue_summary"], colors
        )
        if status == 1:
            print("Review saved. Run `comicmeta review` again to continue, or `comicmeta write` when ready.")
            return
    else:
        print("▸ Issues already reviewed")

    # Phase 5: generate mapping
    print("▸ Generating mapping")
    mapping.run(_map_args(args, paths))

    print("Review complete. The reviewed mapping is ready for `comicmeta write`.")
    if _issue_review_complete(paths["issue_state"], issue_candidates):
        print(colors.muted("  All candidates reviewed — a full write is ready."))
    else:
        print(colors.warn("  ⚠ Some candidates are still unreviewed; `write` will only touch the reviewed subset."))
    continue_to_write = _config.get(flat, "review.continue_to_write")
    if is_interactive() and continue_to_write and confirm("  Continue to write now?", default=True):
        from comicmeta._commands.write import run as write_run
        write_run(_write_args(args, paths, flat))
    elif not is_interactive():
        print("  Run `comicmeta write` when ready (or `comicmeta write --dry-run` to preview).")


def _fetch_args(args: argparse.Namespace, paths: dict) -> argparse.Namespace:
    return argparse.Namespace(
        candidates=paths["candidates"],
        selections=paths["volume_state"],
        policy=paths["policy"],
        report=paths["issue_candidates"],
        api_key_file=args.api_key_file,
        api_key_env=args.api_key_env,
        request_delay=None,
    )


def _map_args(args: argparse.Namespace, paths: dict) -> argparse.Namespace:
    return argparse.Namespace(
        candidates=paths["issue_candidates"],
        review=paths["issue_state"],
        output=paths["mapping"],
        kavita_export=paths.get("kavita_export"),
        source=args.source,
    )


def _write_args(args: argparse.Namespace, paths: dict, flat: dict) -> argparse.Namespace:
    from comicmeta import _config
    return argparse.Namespace(
        source=args.source,
        mapping=paths["mapping"],
        backup_dir=Path(_config.get(flat, "paths.backup_dir")),
        report=Path(_config.get(flat, "paths.write_report")),
        expected_hashes=None,
        no_backups=False,
        dry_run=False,
        yes=True,  # review already confirmed "continue to write"; don't re-prompt
    )
