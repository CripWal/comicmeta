"""comicmeta backups — list and manage metadata/conversion backups.

Backups of original archives (pre-write copies and converted .cbr originals)
are stored under the configured backup directory. This command lists them and
optionally deletes them after you verify the written metadata.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from comicmeta import _config
from comicmeta._common import add_examples, die
from comicmeta._humanize import pretty_bytes


def add_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "backups",
        help="list and manage stored backups",
        description=__doc__,
    )
    parser.add_argument("--source", "-s", type=Path, help="comic library root (default: current directory)")
    parser.add_argument("--backup-dir", type=Path, help="backup directory (default: from settings)")
    parser.add_argument("--list", action="store_true", help="list backups (default)")
    parser.add_argument("--delete", action="store_true", help="delete all backups after listing")
    add_examples(parser, [
        "comicmeta backups",
        "comicmeta backups --delete",
    ])
    parser.set_defaults(handler=run)


def run(args: argparse.Namespace) -> None:
    from comicmeta._common import Palette, color_enabled
    colors = Palette(color_enabled(args))
    flat = _config.load(getattr(args, "source", None))
    backup_dir = args.backup_dir or Path(_config.get(flat, "paths.backup_dir"))
    if not backup_dir.is_dir():
        print(f"  No backups yet at: {colors.path(str(backup_dir))}")
        return

    backups = sorted(backup_dir.rglob("*")) if backup_dir.is_dir() else []
    files = [p for p in backups if p.is_file()]
    print(f"  Backups at: {colors.path(str(backup_dir))}")
    print()
    if not files:
        print("  ✓ No backup files found.")
        return

    total = 0
    for path in files:
        rel = path.relative_to(backup_dir)
        total += path.stat().st_size
        print(f"  {colors.muted(pretty_bytes(path.stat().st_size))}  {colors.path(rel)}")
    print()
    print(f"  BACKUPS files={len(files)} total={pretty_bytes(total)}")

    if args.delete:
        if not sys.stdin.isatty():
            die("backups --delete needs confirmation; run it interactively")
        from comicmeta._tui import confirm
        if confirm(f"  Delete {len(files)} backup files?", default=False):
            shutil.rmtree(backup_dir)
            print(f"  Deleted backup directory: {backup_dir}")
        else:
            print("  Delete cancelled.")
