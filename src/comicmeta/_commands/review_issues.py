"""comicmeta review-issues — interactively review issue-level ComicInfo candidates."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import textwrap
import webbrowser
from pathlib import Path

from comicmeta._common import color_enabled, REQUIRED_FIELDS, Palette, add_examples, atomic_json, die, load_json, progress_bar, require_tty

EDIT_FIELDS = (
    "series", "volume", "number", "year", "month", "day", "format", "title", "publisher", "web",
    "series_sort", "localized_series", "count", "imprint",
    "writer", "penciller", "inker", "colorist", "letterer", "cover_artist", "editor",
    "genre", "tags", "characters", "teams", "locations", "story_arc", "story_arc_number",
    "summary", "notes", "age_rating", "comicvine_issue_id", "comicvine_volume_id", "comicvine_url",
)
EDIT_LABELS = {
    "series_sort": "Series sort", "localized_series": "Localized series", "cover_artist": "Cover artist",
    "story_arc": "Story arc", "story_arc_number": "Story arc number", "age_rating": "Age rating",
    "comicvine_issue_id": "ComicVine issue ID", "comicvine_volume_id": "ComicVine volume ID",
    "comicvine_url": "ComicVine URL",
}


def add_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "review-issues",
        help="interactively review issue-level ComicInfo candidates (read-only)",
        description=__doc__,
    )
    parser.add_argument("--report", type=Path, default=Path("comicvine-issue-candidates.json"), help="issue candidates JSON")
    parser.add_argument("--state", type=Path, default=Path("comicvine-issue-review-state.json"), help="resumable review state JSON")
    parser.add_argument("--summary", type=Path, default=Path("comicvine-issue-review.md"), help="readable review summary")
    parser.add_argument("--list", action="store_true", help="print candidate status and paths, then exit")
    parser.add_argument("--no-color", action="store_true", help="disable ANSI colors")
    add_examples(parser, [
        "comicmeta review-issues",
        "comicmeta review-issues --list",
        "comicmeta review-issues --report issues.json --state s.json",
    ])
    parser.set_defaults(handler=run)


def review_items(report: dict) -> list[dict]:
    active_source = Path(report.get("active_source") or "")
    scanned_source = Path(report.get("scanned_source") or "")
    result = []
    for series in report.get("series", []):
        for match in series.get("matches", []):
            metadata = match.get("metadata_candidate")
            required = metadata and all(str(metadata.get(field, "")).strip() for field in REQUIRED_FIELDS)
            high_confidence = bool(
                match.get("status") == "exact-number" and metadata
                and metadata.get("format") == "Issue" and required
            )
            result.append({
                "query": series["query"],
                "path": match["path"],
                "archive_format": match.get("archive_format"),
                "status": match["status"],
                "metadata": metadata,
                "issue": match.get("issue"),
                "active_path": str(active_source / match["path"]),
                "scanned_path": str(scanned_source / match["path"]),
                "high_confidence": high_confidence,
                "existing_issues": match.get("existing_issues"),
            })
    return result


def load_state(path: Path, report: Path) -> dict:
    if path.exists():
        state = load_json(path, "state")
        state.setdefault("reviews", {})
        return state
    return {"version": 1, "report": str(report), "reviews": {}}


def accepted(metadata: dict, status: str = "accepted") -> dict:
    return {"status": status, "metadata": dict(metadata)}


def validate_metadata(metadata: dict) -> list[str]:
    return [field for field in REQUIRED_FIELDS if not str(metadata.get(field, "")).strip()]


def edit_metadata(metadata: dict) -> dict:
    edited = dict(metadata)
    print("Enter keeps value. '-' clears optional value.")
    for field in EDIT_FIELDS:
        current = edited.get(field, "")
        label = EDIT_LABELS.get(field, field.replace("_", " ").title())
        value = input(f"{label} [{current}]: ").strip()
        if not value:
            continue
        if value == "-":
            edited.pop(field, None)
        else:
            edited[field] = value
    missing = validate_metadata(edited)
    if missing:
        print(f"Not saved. Missing required fields: {', '.join(missing)}")
        return metadata
    return edited


def manual_metadata(item: dict) -> dict | None:
    """Prompt for ComicInfo fields by hand when ComicVine has no match."""
    print("No ComicVine candidate. Enter the ComicInfo fields manually.")
    print("Required: Series, Volume, Number, Year, Format.")
    print("Enter '-' to clear an optional value; blank keeps nothing.")
    edited: dict[str, str] = {}
    for field in EDIT_FIELDS:
        label = EDIT_LABELS.get(field, field.replace("_", " ").title())
        value = input(f"  {label}: ").strip()
        if not value:
            continue
        if value == "-":
            edited.pop(field, None)
        else:
            edited[field] = value
    missing = validate_metadata(edited)
    if missing:
        print(f"Not saved. Missing required fields: {', '.join(missing)}")
        return None
    edited.setdefault("notes", f"manually entered for {item['path']}")
    return edited


def clear_screen() -> None:
    if sys.stdout.isatty():
        print("\033[2J\033[H", end="")


def render(item: dict, index: int, items: list[dict], state: dict, colors: Palette, flag_count: tuple[int, int] = (0, 0)) -> None:
    clear_screen()
    # Only count reviews for files in THIS review session. The state may hold
    # stale entries for series that are no longer candidates (they were pruned
    # after their files were reviewed/written), so len(state["reviews"]) alone
    # would inflate the bar past 100%.
    done = sum(1 for candidate in items if candidate["path"] in state["reviews"])
    width = min(100, shutil.get_terminal_size((100, 24)).columns)
    print(colors.title("▸ COMICVINE ISSUE REVIEW"))
    flags_series, flags_issues = flag_count
    if flags_series or flags_issues:
        parts = []
        if flags_issues:
            parts.append(f"{flags_issues}⚑")
        if flags_series:
            parts.append(f"{flags_series}✦")
        badge = " ".join(parts) if parts else "0"
        print(colors.warn(f"  ComicMeta {badge} · run: comicmeta flags"))
    print(colors.bold(f"  {item['query']} [{index + 1}/{len(items)}]"))
    print(f"  {progress_bar(done, len(items))}  {colors.muted(f'reviewed {done}/{len(items)}')}")
    saved = state["reviews"].get(item["path"])
    if saved:
        print(colors.good(f"  ✓ Saved: {saved['status']}"))
    print()
    print(colors.bold("  FILE"))
    print(f"    {'Active':<11} {colors.path(item['active_path'])}")
    if item["scanned_path"] != item["active_path"]:
        print(f"    {'Scanned':<11} {colors.muted(item['scanned_path'])}")
    print(f"    {'Format':<11} {(item.get('archive_format') or '?').upper()} · {item['status']} match")
    existing_issues = item.get("existing_issues")
    if existing_issues:
        print(colors.warn(f"    ⚠ existing ComicInfo needs review: {'; '.join(existing_issues)}"))
    try:
        from comicmeta import _cover
        cover_path = Path(item["active_path"])
        if cover_path.suffix.lower() == ".cbz" and cover_path.is_file():
            cover = _cover.preview(cover_path)
            if cover:
                print()
                print(cover)
    except Exception:
        pass
    print()
    metadata = (saved or {}).get("metadata") or item.get("metadata")
    print(colors.bold("  COMICINFO CANDIDATE"))
    if not metadata:
        print(colors.warn("    No issue metadata candidate"))
    else:
        date = "-".join(
            part for part in (
                str(metadata.get("year") or ""),
                str(metadata.get("month") or "").zfill(2) if metadata.get("month") else "",
                str(metadata.get("day") or "").zfill(2) if metadata.get("day") else "",
            ) if part
        ) or "?"
        for field in (
            "series", "series_sort", "localized_series", "volume", "number", "count",
            "year", "month", "day", "format", "title", "publisher", "imprint",
            "writer", "penciller", "inker", "colorist", "letterer", "cover_artist", "editor",
            "genre", "tags", "characters", "teams", "locations", "story_arc", "story_arc_number",
            "age_rating", "comicvine_issue_id", "comicvine_volume_id", "comicvine_url",
        ):
            value = metadata.get(field)
            if value in (None, ""):
                continue
            label = EDIT_LABELS.get(field, field.replace("_", " ").title())
            print(f"    {label:<20} {value}")
        print(f"    {'Date':<11} {date}")
        print(f"    {'Web':<20} {metadata.get('web', '(none)')}")
        summary = metadata.get("summary")
        if summary:
            print("    Summary")
            for line in textwrap.wrap(summary, max(30, width - 8))[:3]:
                print(f"      {line}")
        if metadata.get("notes"):
            print(f"    {'Notes':<20} {metadata['notes']}")
    print()
    if item["high_confidence"]:
        print(colors.good("  ✓ High confidence: exact number, ordinary issue, required fields present"))
    else:
        print(colors.warn(_manual_review_hint(item)))
    print()
    print(colors.muted("  [↑/↓] prev/next file · [Enter] accept · [e] edit · [m] manual"))
    print(colors.muted("  [o] open · [s] skip · [!] flag for research · [h] accept all · [q] save & quit"))


def _manual_review_hint(item: dict) -> str:
    """Human-readable reason a candidate needs manual review, with the next step.

    The old single line ("collected edition, inferred format, or non-exact
    match") listed jargon with no guidance; this explains the specific reason
    and what to do next.
    """
    status = item.get("status", "unmatched")
    fmt = str((item.get("metadata") or {}).get("format", ""))
    collected = fmt.casefold() not in {"issue", ""}
    if status == "unmatched":
        reason = "no ComicVine issue matched the filename — this may be a special, a one-shot, or a collection"
    elif status == "ambiguous-number":
        reason = "more than one ComicVine issue shares this number — check the cover to pick the right one"
    elif status == "exact-volume":
        reason = "the collection volume tag matched a ComicVine Volume issue — confirm the cover data before accepting"
    elif status == "exact-number" and collected:
        reason = "an exact-number match, but a collected edition (TPB/omnibus) so the cover data should be confirmed before accepting"
    elif status == "single-file-single-issue":
        reason = "one candidate for a whole-file edition — confirm the title/volume/format are right before accepting"
    else:
        reason = "the format was inferred rather than confirmed — check that 'Issue' vs TPB/omnibus is right"
    return (f"  ⚠ Manual review — {reason}."
            f"\n    [Enter] accept · [m] enter your own · [o] open ComicVine first")


def write_summary(path: Path, items: list[dict], state: dict) -> None:
    counts = {"accepted": 0, "auto-accepted": 0, "edited": 0, "manual": 0, "skipped": 0, "pending": 0}
    for item in items:
        review = state["reviews"].get(item["path"])
        counts[review["status"] if review else "pending"] += 1
    lines = [
        "# ComicVine Issue Metadata Review", "",
        f"Reviewed: {len(items) - counts['pending']} / {len(items)}", "",
        "- " + "\n- ".join(f"{key}: {value}" for key, value in counts.items()), "",
    ]
    for item in items:
        review = state["reviews"].get(item["path"])
        status = review["status"] if review else "pending"
        metadata = (review or {}).get("metadata") or item.get("metadata") or {}
        lines.extend([
            f"## {item['path']}", "", f"Status: **{status}**", "",
            f"Active path: `{item['active_path']}`", "",
        ])
        if item["scanned_path"] != item["active_path"]:
            lines.extend([f"Scanned copy: `{item['scanned_path']}`", ""])
        if metadata:
            for field in EDIT_FIELDS:
                if field == "summary":
                    continue
                value = metadata.get(field)
                if value not in (None, ""):
                    label = EDIT_LABELS.get(field, field.replace("_", " ").title())
                    lines.append(f"- {label}: `{value}`")
            lines.append("")
            if metadata.get("summary"):
                lines.extend(["Summary:", "", str(metadata["summary"]), ""])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def list_items(items: list[dict]) -> None:
    for item in items:
        level = "AUTO" if item["high_confidence"] else "REVIEW"
        metadata = item.get("metadata") or {}
        print(f"{level}\t{item['status']}\t{metadata.get('format', '-')}\t{item['active_path']}")


def _advance(index: int, total: int) -> tuple[int, bool]:
    """Advance to the next item; returns (new_index, all_done)."""
    if index + 1 >= total:
        return index, True
    return index + 1, False


def interactive(report_path: Path, state_path: Path, summary_path: Path, colors: Palette) -> None:
    from comicmeta._tui import confirm, enter_alt_screen, read_key
    enter_alt_screen()
    report = load_json(report_path, "report")
    items = review_items(report)
    if not items:
        die("no issue candidates found")
    state = load_state(state_path, report_path)
    from comicmeta._commands.flags import counts
    from comicmeta import _config as config_mod
    flag_count = counts(config_mod.load(Path(report.get("active_source") or "")))

    def pending_items() -> list[int]:
        """Indices of items still needing a decision (not in review state)."""
        return [i for i, candidate in enumerate(items) if candidate["path"] not in state["reviews"]]

    pending = pending_items()
    index_in_pending = 0 if pending else 0
    while True:
        if not pending:
            break  # all items reviewed
        index = pending[index_in_pending]
        item = items[index]
        render(item, index, items, state, colors, flag_count)
        key = read_key()
        if key in {"q", "ctrl-c", "ctrl-d"}:
            # Save and go back to the caller; do not auto-continue to write.
            atomic_json(state_path, state)
            write_summary(summary_path, items, state)
            print(f"Saved state: {state_path}")
            print(f"Review summary: {summary_path}")
            return 1  # back / quit early
        if key == "o":
            review = state["reviews"].get(item["path"])
            metadata = (review or {}).get("metadata") or item.get("metadata") or {}
            if metadata.get("web"):
                webbrowser.open(metadata["web"])
            continue
        if key in {"enter", "a"} and item.get("metadata"):
            current = state["reviews"].get(item["path"])
            metadata = (current or {}).get("metadata") or item["metadata"]
            state["reviews"][item["path"]] = accepted(metadata)
            atomic_json(state_path, state)
            pending = pending_items()
            index_in_pending = min(index_in_pending, len(pending) - 1) if pending else 0
            continue
        if key == "e" and item.get("metadata"):
            current = state["reviews"].get(item["path"])
            before = (current or {}).get("metadata") or item["metadata"]
            edited = edit_metadata(before)
            state["reviews"][item["path"]] = accepted(edited, "edited")
            atomic_json(state_path, state)
            continue
        if key == "m":
            manual = manual_metadata(item)
            if manual is not None:
                state["reviews"][item["path"]] = accepted(manual, "manual")
                atomic_json(state_path, state)
                pending = pending_items()
                index_in_pending = min(index_in_pending, len(pending) - 1) if pending else 0
            continue
        if key == "!":
            from comicmeta._tui import prompt_edit
            note = prompt_edit("  Flag note (for research): ")
            state["reviews"][item["path"]] = {
                "status": "flagged",
                "note": note or "flagged for further research",
            }
            atomic_json(state_path, state)
            pending = pending_items()
            index_in_pending = min(index_in_pending, len(pending) - 1) if pending else 0
            continue
        if key == "s":
            state["reviews"][item["path"]] = {"status": "skipped"}
            atomic_json(state_path, state)
            pending = pending_items()
            index_in_pending = min(index_in_pending, len(pending) - 1) if pending else 0
            continue
        if key == "h":
            high = [candidate for candidate in items if candidate["high_confidence"] and candidate["path"] not in state["reviews"]]
            if high and confirm(f"Accept {len(high)} high-confidence issue candidates?", default=False):
                for candidate in high:
                    state["reviews"][candidate["path"]] = accepted(candidate["metadata"], "auto-accepted")
                atomic_json(state_path, state)
            # The remaining pending list is now only low-confidence / unmatched
            # items; stay on the current one (or the first pending if current
            # got auto-accepted).
            pending = pending_items()
            if not pending:
                break
            if item["path"] not in state["reviews"]:
                index_in_pending = pending.index(index)
            else:
                index_in_pending = 0
            continue
        if key in {"up", "p"}:
            index_in_pending = max(0, index_in_pending - 1)
            continue
        if key in {"down", "n", ""}:
            index_in_pending = min(len(pending) - 1, index_in_pending + 1)
    atomic_json(state_path, state)
    write_summary(summary_path, items, state)
    print(f"Saved state: {state_path}")
    print(f"Review summary: {summary_path}")
    return 0  # completed


def run(args: argparse.Namespace) -> None:
    colors = Palette(color_enabled(args))
    report = load_json(args.report, "report")
    items = review_items(report)
    if args.list:
        list_items(items)
        return
    require_tty("review-issues", "comicmeta review-issues --list")
    interactive(args.report, args.state, args.summary, colors)
