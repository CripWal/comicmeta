"""comicmeta discover — query ComicVine and write candidates."""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from comicmeta import _archive, _comicvine
from comicmeta._common import add_examples, atomic_write, die


def add_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "discover",
        help="query ComicVine and write candidate report (read-only)",
        description=__doc__,
    )
    parser.add_argument("--source", "-s", type=Path, help="comic library root (default: current directory)")
    parser.add_argument("--report", "-r", type=Path, help="JSON report path (default: from settings)")
    parser.add_argument("--api-key-file", type=Path, help="file containing the ComicVine key")
    parser.add_argument("--api-key-env", default=None, help="environment variable containing the API key")
    parser.add_argument("--limit", type=int, default=None, help="ComicVine candidates per archive")
    add_examples(parser, [
        "comicmeta discover",
        "comicmeta discover -s /path/to/comics -r candidates.json",
    ])
    parser.set_defaults(handler=run)


def title_for_query(path: Path) -> str:
    """Pick the series title to search ComicVine for.

    Prefers the containing folder when it names the series (e.g.
    ``DC/Batman (1940)/Batman (1940) #001.cbz`` → ``Batman (1940)``). When a
    file sits loose in a collection/publisher root (e.g. ``DC/<file>.cbr``),
    the folder name is not the series, so a cleaned-up filename is used
    instead — otherwise ComicVine is searched for the folder name ("DC") and
    returns unrelated series.
    """
    folder = path.parent.name.strip()
    stem = path.stem.strip()
    if folder and _folder_names_series(folder, stem):
        return folder
    return _series_query_from_filename(stem)


def _folder_names_series(folder: str, stem: str) -> bool:
    """True when the folder name looks like the series the file belongs to.

    A series folder's name normally appears in its file names; a publisher or
    collection root ("DC", "Marvel") does not.
    """
    return folder.casefold() in stem.casefold()


def _series_query_from_filename(stem: str) -> str:
    """Reduce a release-group filename to a ComicVine-searchable series title.

    ``Batman - The Dark Knight Returns 01 (of 04) (1986) (digital)
    (Minutemen-InnerDemons)`` → ``Batman - The Dark Knight Returns (1986)``.
    The four-digit year is kept because it helps ComicVine disambiguate.
    """
    text = stem
    # `#001` and `NNN (of M)` issue markers
    text = re.sub(r"#\s*[\d.]+", "", text)
    text = re.sub(r"\b\d+(?:\.\d+)?\s*\(\s*of\s*\d+\s*\)", "", text)
    # Any other parenthesized qualifier that isn't a four-digit year
    text = re.sub(r"\((?![\s]*(?:19|20)\d{2}[\s]*\))[^()]*\)", "", text)
    # Standalone issue number directly before the year group
    text = re.sub(r"\s+\d+(?:\.\d+)?(?=\s*\((?:19|20)\d{2}\))", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text.strip(" -_.") or stem


def issue_number(path: Path) -> str | None:
    """Extract the issue number from a filename.

    Supports `#NNN` (`Hawkeye (1983) #001.cbz`), `vN NNN` (`Aquaman v5 000
    (1994).cbz`), bare `NNN (Year)` at the end (`Aquaman 057 (1999).cbz`),
    and issue-first run labels (`Daredevil 01 (of 5) (1993) ... .cbz`).
    Special numbers such as `#0` and `#1000000` are preserved.
    """
    match = re.search(r"#\s*([0-9]+(?:\.[0-9]+)?)", path.stem)
    if match:
        return match.group(1)
    # Issue-first labels: `TITLE NNN (of M) (Year) ...` — grab the number that
    # sits immediately before `(of N)` (the issue in an x-of-y run).
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*\(\s*of\s*[0-9]+\s*\)", path.stem)
    if match:
        return match.group(1)
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*\(\d{4}\)\s*$", path.stem)
    if match:
        return match.group(1)
    return None


def folder_year(folder: str) -> str | None:
    match = re.search(r"\((\d{4})\)\s*$", folder.strip())
    return match.group(1) if match else None


def audit_item(path: Path, item: dict) -> None:
    """Audit existing ComicInfo. If incomplete/conflicting, mark for review."""
    from comicmeta import _archive
    audit = _archive.audit_existing_metadata(
        path,
        folder_year=folder_year(item.get("query") or ""),
        filename_number=item.get("issue_number_from_filename"),
    )
    item["existing_comicinfo"] = audit
    if audit["complete"]:
        item["status"] = "skipped-existing-comicinfo"
    else:
        item["status"] = "review-required"
        item["existing_issues"] = audit["issues"]


def discover(source: Path, report: Path, api_key: str, limit: int, timeout: int = 30, user_agent: str | None = None, exclude: set[str] | None = None, request_delay: float = 0.25, concurrency: int = 5) -> dict:
    result = {"generated_at": datetime.now(timezone.utc).isoformat(), "source": str(source), "items": []}
    items = []
    queries = set()
    for path in _archive.archives(source, exclude=exclude):
        relative = path.relative_to(source).as_posix()
        item = {
            "path": relative,
            "format": path.suffix.lower().lstrip("."),
            "has_comicinfo": _archive.root_comicinfo(path) if path.suffix.lower() == ".cbz" else None,
            "query": title_for_query(path),
            "issue_number_from_filename": issue_number(path),
            "candidates": [],
        }
        if item["has_comicinfo"]:
            audit_item(path, item)
            # An archive explicitly marked for replacement (e.g. download-tool
            # metadata that is wrong) must go through review again even when its
            # existing ComicInfo audits as complete.
            from comicmeta._commands import replacement
            if replacement.is_requested(relative, source):
                item["status"] = "review-required"
                item["replacement_requested"] = True
        else:
            item["status"] = "review-required"
            queries.add(item["query"])
        items.append(item)
    if queries:
        searched = _comicvine.search_volumes_batch(
            api_key, sorted(queries), limit,
            timeout=timeout, user_agent=user_agent,
            request_delay=request_delay, concurrency=concurrency,
        )
        by_query = {entry["query"]: entry["candidates"] for entry in searched}
        for item in items:
            if item["status"] == "review-required" and item["query"] in by_query:
                item["candidates"] = by_query[item["query"]]
    result["items"] = items
    atomic_write(report, json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def _cached_items(report: Path) -> dict[str, dict]:
    """Load prior candidates keyed by relative path, tolerating a missing file."""
    if not report.is_file():
        return {}
    try:
        payload = json.loads(report.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return {item["path"]: item for item in payload.get("items", [])}


def _same_identity(current: dict, cached: dict) -> bool:
    """True when a file's local identity is unchanged so candidates can be reused."""
    for field in ("format", "query", "issue_number_from_filename", "has_comicinfo"):
        if current.get(field) != cached.get(field):
            return False
    return True


def rescan(source: Path, report: Path, api_key: str | None, limit: int, timeout: int = 30, user_agent: str | None = None, exclude: set[str] | None = None, request_delay: float = 0.25, concurrency: int = 5) -> dict:
    """Scan the library, reusing cached candidates for unchanged files.

    Always walks the directory (so new files are found and removed files
    dropped), but only queries ComicVine for files whose local identity
    changed or is new. Fresh queries run concurrently (bounded by
    `concurrency`) while respecting `request_delay` spacing. `api_key` may be
    None: if a file needs a fresh query and no key is available, it is marked
    `needs-api-key` instead of dying. `exclude` skips directory names such as
    the backup root.
    """
    cached = _cached_items(report)
    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": str(source),
        "items": [],
        "reused": 0,
        "queried": 0,
        "added": [],
        "removed": [],
        "needs_api_key": [],
    }
    seen: set[str] = set()
    from comicmeta._archive import ComicInfoCache, cached_root_comicinfo
    cache = ComicInfoCache()
    items: list[dict] = []
    queries_to_search: set[str] = set()
    for path in _archive.archives(source, exclude=exclude):
        relative = path.relative_to(source).as_posix()
        seen.add(relative)
        item = {
            "path": relative,
            "format": path.suffix.lower().lstrip("."),
            "has_comicinfo": cached_root_comicinfo(path, cache) if path.suffix.lower() == ".cbz" else None,
            "query": title_for_query(path),
            "issue_number_from_filename": issue_number(path),
            "candidates": [],
        }
        if item["has_comicinfo"]:
            audit_item(path, item)
            # An archive explicitly marked for replacement (e.g. download-tool
            # metadata that is wrong) must go through review again even when its
            # existing ComicInfo audits as complete.
            from comicmeta._commands import replacement
            if replacement.is_requested(relative, source):
                item["status"] = "review-required"
                item["replacement_requested"] = True
        else:
            item["status"] = "review-required"
        if item["status"] == "review-required":
            prior = cached.get(relative)
            prior_usable = prior is not None and _same_identity(item, prior) and prior.get("status") == "review-required"
            if prior_usable:
                item["candidates"] = prior.get("candidates", [])
                result["reused"] += 1
            elif api_key:
                queries_to_search.add(item["query"])
            elif prior is not None and prior.get("candidates"):
                # Keep previously queried candidates; don't degrade the cache.
                item["candidates"] = prior["candidates"]
                result["reused"] += 1
            else:
                item["status"] = "needs-api-key"
                result["needs_api_key"].append(relative)
        items.append(item)

    # Batch-search queries that need fresh candidates, concurrently.
    if api_key and queries_to_search:
        searched = _comicvine.search_volumes_batch(
            api_key, sorted(queries_to_search), limit,
            timeout=timeout, user_agent=user_agent,
            request_delay=request_delay, concurrency=concurrency,
        )
        by_query = {entry["query"]: entry["candidates"] for entry in searched}
        for item in items:
            if item["status"] == "review-required" and item["query"] in by_query and not item["candidates"]:
                item["candidates"] = by_query[item["query"]]
                result["queried"] += 1
                result["added"].append(item["path"])
    result["items"] = items
    result["removed"] = sorted(set(cached) - seen)
    atomic_write(report, json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def run(args: argparse.Namespace) -> None:
    from comicmeta import _config
    flat = _config.load(getattr(args, "source", None))
    source = args.source or Path(_config.get(flat, "paths.source"))
    report = args.report or Path(_config.get(flat, "paths.candidates"))
    limit = args.limit if args.limit is not None else _config.as_int(_config.get(flat, "api.candidate_limit"), 10)
    timeout = _config.as_int(_config.get(flat, "api.timeout"), 30)
    user_agent = _config.get(flat, "api.user_agent")
    if args.api_key_env is None:
        args.api_key_env = _config.get(flat, "api.key_env")
    if args.api_key_file is None and _config.get(flat, "api.key_file"):
        args.api_key_file = Path(os.path.expanduser(_config.get(flat, "api.key_file")))
    if not source.is_dir():
        die(f"source does not exist: {source}")
    api_key = _comicvine.api_key_from(args, flat)
    request_delay = _config.as_float(_config.get(flat, "api.request_delay"), 0.25)
    concurrency = _config.as_int(_config.get(flat, "api.concurrency"), 5)
    from comicmeta._spinner import Spinner
    with Spinner(f"Scanning {source} and querying ComicVine") as spinner:
        result = rescan(source, report, api_key, limit, timeout=timeout, user_agent=user_agent, exclude=_config.scan_excludes(flat), request_delay=request_delay, concurrency=concurrency)
        spinner.update("Scan complete")
    print(f"DISCOVERY report={report} items={len(result['items'])} reused={result['reused']} queried={result['queried']}")
