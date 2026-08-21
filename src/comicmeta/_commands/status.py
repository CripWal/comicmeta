"""comicmeta status — one-glance view of context, library, and pipeline state.

Answers "where am I?" at a glance: active context, library location and size,
and which pipeline phases have data. Read-only. Use `--json` for scripts.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from comicmeta import _archive, _config, _context
from comicmeta._common import Palette, add_examples, color_enabled, die, die_missing_source, load_json

PIPELINE_STEPS = (
    ("discover", "candidates"),
    ("review-volumes", "volume_state"),
    ("fetch-issues", "issue_candidates"),
    ("review-issues", "issue_state"),
    ("map", "mapping"),
)

NEXT_STEP = {
    "discover": "comicmeta review-volumes",
    "review-volumes": "comicmeta fetch-issues",
    "fetch-issues": "comicmeta review-issues",
    "review-issues": "comicmeta map",
    "map": "comicmeta write --dry-run",
}


def add_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "status",
        help="show context, library, and pipeline state (read-only)",
        description=__doc__,
    )
    parser.add_argument("--source", "-s", type=Path, help="comic library root (default: from settings)")
    parser.add_argument("--json", action="store_true", help="output as JSON (machine-readable)")
    parser.add_argument("--no-color", action="store_true", help="disable ANSI colors")
    add_examples(parser, [
        "comicmeta status",
        "comicmeta status --json",
        "comicmeta status -s /path/to/comics",
    ])
    parser.set_defaults(handler=run)


def _defaults(flat: dict) -> dict:
    get = lambda key: _config.get(flat, key)
    return {key: Path(get(f"paths.{key}")) for key in (
        "candidates", "volume_state", "volume_summary", "policy",
        "issue_candidates", "issue_state", "issue_summary", "mapping",
    )}


def _phase_state(paths: dict) -> list[dict]:
    """Return per-phase state: name, done (file exists), file name."""
    phases = []
    for step, key in PIPELINE_STEPS:
        path = paths[key]
        phases.append({
            "step": step,
            "done": path.is_file(),
            "file": path.name,
        })
    return phases


def _counts(paths: dict) -> dict:
    """Counts where cheaply available from state files."""
    counts = {"archives": None, "candidates": None, "volumes": None, "issues": None, "mapping": None}
    candidates = paths["candidates"]
    if candidates.is_file():
        try:
            payload = load_json(candidates, "candidates")
            counts["candidates"] = len(payload.get("items", []))
        except SystemExit:
            counts["candidates"] = None
    volume_state = paths["volume_state"]
    if volume_state.is_file():
        try:
            payload = load_json(volume_state, "volume state")
            counts["volumes"] = len(payload.get("selections", {}))
        except SystemExit:
            counts["volumes"] = None
    issue_candidates = paths["issue_candidates"]
    if issue_candidates.is_file():
        try:
            payload = load_json(issue_candidates, "issue candidates")
            counts["issues"] = sum(
                len(s.get("matches", [])) for s in payload.get("series", []) if isinstance(s, dict)
            )
        except SystemExit:
            counts["issues"] = None
    if paths["mapping"].is_file():
        try:
            payload = load_json(paths["mapping"], "mapping")
            counts["mapping"] = len(payload)
        except SystemExit:
            counts["mapping"] = None
    return counts


def _next_action(phases: list[dict], write_ready: bool) -> str | None:
    if write_ready:
        return "comicmeta write --dry-run"
    for phase in phases:
        if not phase["done"]:
            return NEXT_STEP.get(phase["step"])
    return None


def _render(flat: dict, source: Path, counts: dict, phases: list[dict], context, write_ready: bool) -> None:
    colors = Palette(color_enabled())
    print(colors.title("▸ STATUS"))
    print()
    print(f"  {colors.bold('Context')}   {context.name}")
    print(f"  {colors.bold('Library')}   {source}")
    if counts["archives"] is not None:
        print(f"  {colors.bold('Archives')}  {counts['archives']}")
    print()
    print(colors.bold("  Pipeline"))
    for phase in phases:
        marker = "✓" if phase["done"] else "·"
        mark_color = colors.good(marker) if phase["done"] else colors.muted(marker)
        print(f"    {mark_color} {phase['step']:<16} {colors.muted(phase['file'])}")
    print()
    print(f"  {colors.bold('Counts')}")
    printed_any = False
    if counts["candidates"] is not None:
        print(f"    candidates   {counts['candidates']}")
        printed_any = True
    if counts["volumes"] is not None:
        print(f"    volumes      {counts['volumes']}")
        printed_any = True
    if counts["issues"] is not None:
        print(f"    issues       {counts['issues']}")
        printed_any = True
    if counts["mapping"] is not None:
        print(f"    mapping      {counts['mapping']}")
        printed_any = True
    if not printed_any:
        print(f"    {colors.muted('(no pipeline data yet — run `comicmeta review`)')}")
    print()
    next_action = _next_action(phases, write_ready)
    if next_action:
        print(f"  {colors.title('Next:')} {next_action}")


def run(args: argparse.Namespace) -> None:
    flat = _config.load(args.source)
    source = (args.source or Path(_config.get(flat, "paths.source"))).resolve()
    if not source.is_dir():
        die_missing_source(source)
    paths = _defaults(flat)
    ctx = _context.load_context(getattr(args, "context", None) or _context.LOCAL_CONTEXT_NAME) if getattr(args, "context", None) else _context.active_context()
    counts = _counts(paths)
    counts["archives"] = len(_archive.archives(source, exclude=_config.scan_excludes(flat)))
    phases = _phase_state(paths)
    write_ready = paths["mapping"].is_file()

    if args.json:
        print(json.dumps({
            "context": ctx.get("name", "local"),
            "library": str(source),
            "archives": counts["archives"],
            "counts": {k: v for k, v in counts.items() if k != "archives"},
            "pipeline": phases,
            "next": _next_action(phases, write_ready),
        }, indent=2, sort_keys=True))
        return
    _render(flat, source, counts, phases, ctx, write_ready)
