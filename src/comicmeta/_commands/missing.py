"""comicmeta missing — report ComicVine issues not present in the library.

Reads the issue-candidates report (written by `comicmeta review` / `fetch-issues`)
and lists, per series, the ComicVine issues that have no matching local file.
Requires the report to exist; run `comicmeta review` (or `fetch-issues`) first.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from comicmeta import _config
from comicmeta._common import color_enabled, Palette, add_examples, die, load_json


def add_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "missing",
        help="list ComicVine issues not present in the library",
        description=__doc__,
    )
    parser.add_argument("--source", "-s", type=Path, help="comic library root (default: current directory)")
    parser.add_argument("--no-color", action="store_true", help="disable ANSI colors")
    add_examples(parser, [
        "comicmeta missing",
        "comicmeta missing -s /path/to/comics",
    ])
    parser.set_defaults(handler=run)


def run(args: argparse.Namespace) -> None:
    colors = Palette(color_enabled(args))
    flat = _config.load(getattr(args, "source", None))
    report_path = Path(_config.get(flat, "paths.issue_candidates"))
    if not report_path.is_file():
        die("issue candidates report not found; run `comicmeta review` or `comicmeta fetch-issues` first")

    report = load_json(report_path, "issue candidates")
    print("  comicmeta missing — ComicVine issues not in the library")
    print()
    total = 0
    any_gaps = False
    for series in report.get("series", []):
        unmatched = series.get("unmatched_api_issues", [])
        if not unmatched:
            continue
        any_gaps = True
        total += len(unmatched)
        print(f"  {colors.bold(series['query'])} ({len(unmatched)} missing)")
        for issue in unmatched[:15]:
            number = issue.get("number") or "?"
            name = issue.get("name") or ""
            print(f"      #{number}  {colors.muted(name)}")
        if len(unmatched) > 15:
            print(colors.muted(f"      … and {len(unmatched) - 15} more"))
        print()
    if not any_gaps:
        print(colors.good("  ✓ No missing issues found — library is complete."))
    else:
        print(f"  MISSING total={total} — use `comicmeta fetch-issues` to refresh this report.")
