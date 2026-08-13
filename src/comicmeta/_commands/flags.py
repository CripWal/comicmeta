"""comicmeta flags — list series/issues flagged for further research.

Flags are set with `[!]` during volume or issue review and persist in the
review state files. Flagged items are excluded from the write mapping, so they
are never written until the flag is cleared.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from comicmeta import _config
from comicmeta._common import color_enabled, Palette, add_examples, load_json


def add_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "flags",
        help="list series/issues flagged for research, or clear flags",
        description=__doc__,
    )
    parser.add_argument("--source", "-s", type=Path, help="comic library root (default: current directory)")
    parser.add_argument("--clear", action="store_true", help="interactively unflag items as they're resolved")
    parser.add_argument("--no-color", action="store_true", help="disable ANSI colors")
    add_examples(parser, [
        "comicmeta flags",
        "comicmeta flags --clear",
        "comicmeta flags -s /path/to/comics",
    ])
    parser.set_defaults(handler=run)


def collect(flat: dict) -> tuple[list[dict], list[dict]]:
    """Return (series_flags, issue_flags) from the review state files."""
    get = lambda key: _config.get(flat, key)
    volume_state = Path(get("paths.volume_state"))
    issue_state = Path(get("paths.issue_state"))

    series_flags = []
    if volume_state.is_file():
        state = load_json(volume_state, "volume state")
        for query, selection in sorted(state.get("selections", {}).items()):
            if selection.get("status") == "flagged":
                series_flags.append({
                    "query": query,
                    "note": selection.get("note") or "further research required",
                    "paths": [],
                })

    issue_flags = []
    if issue_state.is_file():
        state = load_json(issue_state, "issue state")
        for path, review in sorted(state.get("reviews", {}).items()):
            if review.get("status") == "flagged":
                issue_flags.append({
                    "path": path,
                    "note": review.get("note") or "further research required",
                })
    return series_flags, issue_flags


def counts(flat: dict) -> tuple[int, int]:
    """Return (series_flags, issue_flags) counts without building detail lists."""
    series, issues = collect(flat)
    return len(series), len(issues)


def flag_for(path: Path, source: Path | None = None) -> tuple[str | None, str | None]:
    """Return (series_flag_note, issue_flag_note) for an archive path.

    `path` is the archive's absolute path; `source` is the library root used to
    derive the relative issue path. Notes are None when not flagged.
    """
    from comicmeta import _config
    flat = _config.load(source)
    get = lambda key: _config.get(flat, key)
    series_note = issue_note = None
    volume_state = Path(get("paths.volume_state"))
    if volume_state.is_file():
        state = load_json(volume_state, "volume state")
        for query, selection in state.get("selections", {}).items():
            if selection.get("status") == "flagged" and query == path.parent.name:
                series_note = selection.get("note") or "further research required"
                break
    issue_state = Path(get("paths.issue_state"))
    if issue_state.is_file():
        state = load_json(issue_state, "issue state")
        rel = str(path.relative_to(source)) if source else str(path)
        review = state.get("reviews", {}).get(rel)
        if review and review.get("status") == "flagged":
            issue_note = review.get("note") or "further research required"
    return series_note, issue_note


def status_line(colors, source: Path | None = None) -> str | None:
    """A compact status-bar line for flagged items (iconographic), or None.

    `⚑` counts flagged issues, `✦` counts flagged series — two separate states.
    """
    from comicmeta import _config
    series, issues = counts(_config.load(source))
    if not series and not issues:
        return None
    parts = []
    if issues:
        parts.append(f"{issues}⚑")
    if series:
        parts.append(f"{series}✦")
    badge = " ".join(parts) if parts else "0"
    return f"  {colors.warn(f'ComicMeta {badge} · run: comicmeta flags')}"


def run(args: argparse.Namespace) -> None:
    colors = Palette(color_enabled(args))
    if getattr(args, "clear", False):
        clear_flags(args, colors)
        return
    flat = _config.load(getattr(args, "source", None))
    series_flags, issue_flags = collect(flat)

    print("  comicmeta flags — items flagged for further research")
    print()
    print(f"  SERIES ({len(series_flags)})")
    if not series_flags:
        print("    none")
    for flag in series_flags:
        print(f"    {colors.warn('⚑')} {flag['query']}")
        print(f"        {flag['note']}")
    print()
    print(f"  ISSUES ({len(issue_flags)})")
    if not issue_flags:
        print("    none")
    for flag in issue_flags:
        print(f"    {colors.warn('⚑')} {flag['path']}")
        print(f"        {flag['note']}")
    print()
    print(colors.muted("  To clear flags once resolved, run: comicmeta flags --clear"))


def clear_flags(args: argparse.Namespace, colors) -> None:
    """Interactively unflag series/issues so they can re-enter the write pool."""
    from comicmeta._common import color_enabled, atomic_json
    from comicmeta._tui import confirm, enter_alt_screen, read_key
    enter_alt_screen()
    flat = _config.load(getattr(args, "source", None))
    get = lambda key: _config.get(flat, key)
    volume_state = Path(get("paths.volume_state"))
    issue_state = Path(get("paths.issue_state"))

    series_flags, issue_flags = collect(flat)
    if not series_flags and not issue_flags:
        print("  Nothing flagged. Nothing to clear.")
        return

    cleared = 0
    if series_flags:
        print(f"  SERIES ({len(series_flags)}) — [↑/↓] select · [Enter] clear · [q] skip all")
        if volume_state.is_file():
            state = load_json(volume_state, "volume state")
        else:
            state = {"selections": {}}
        index = 0
        while series_flags:
            flag = series_flags[index]
            print(f"    {colors.warn('▸')} {flag['query']}")
            print(f"        {flag['note']}")
            key = read_key()
            if key in {"q", "ctrl-c", "ctrl-d"}:
                break
            if key == "enter":
                query = flag["query"]
                if query in state.get("selections", {}):
                    del state["selections"][query]
                    atomic_json(volume_state, state)
                series_flags.pop(index)
                cleared += 1
                index = min(index, len(series_flags) - 1) if series_flags else 0
            elif key == "up":
                index = max(0, index - 1)
            elif key == "down":
                index = min(len(series_flags) - 1, index + 1)

    if issue_flags:
        print(f"  ISSUES ({len(issue_flags)}) — [↑/↓] select · [Enter] clear · [q] quit")
        if issue_state.is_file():
            state = load_json(issue_state, "issue state")
        else:
            state = {"reviews": {}}
        index = 0
        while issue_flags:
            flag = issue_flags[index]
            print(f"    {colors.warn('▸')} {flag['path']}")
            print(f"        {flag['note']}")
            key = read_key()
            if key in {"q", "ctrl-c", "ctrl-d"}:
                break
            if key == "enter":
                path = flag["path"]
                if path in state.get("reviews", {}):
                    del state["reviews"][path]
                    atomic_json(issue_state, state)
                issue_flags.pop(index)
                cleared += 1
                index = min(index, len(issue_flags) - 1) if issue_flags else 0
            elif key == "up":
                index = max(0, index - 1)
            elif key == "down":
                index = min(len(issue_flags) - 1, index + 1)

    print()
    print(f"  Cleared {cleared} flag(s). Run `comicmeta review` again to re-review them.")
    print(colors.muted("  Note: cleared series/issues are no longer excluded from write."))
