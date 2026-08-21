"""comicmeta inspect — read and edit existing ComicInfo.xml metadata.

Lists archives in the library, shows what metadata each already contains, and
lets you re-review or edit that metadata. Editing rewrites the CBZ in place with
a backup, using the same safety rules as `comicmeta write`.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from comicmeta import _archive, _config
from comicmeta._common import color_enabled, REQUIRED_FIELDS, add_examples, die, die_missing_source
from comicmeta._humanize import pretty_bytes

EDIT_FIELDS = ("series", "volume", "number", "year", "month", "day", "format", "title", "publisher", "web")


def add_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "inspect",
        help="read and edit existing ComicInfo.xml metadata",
        description=__doc__,
    )
    parser.add_argument("--source", "-s", type=Path, help="comic library root (default: current directory)")
    parser.add_argument("--path", "-p", type=Path, help="a specific archive to inspect (instead of listing all)")
    parser.add_argument("--backup-dir", type=Path, help="backup directory for edits (default: from settings)")
    parser.add_argument("--quick", "-q", action="store_true", help="list presence only, without reading each archive's metadata (faster)")
    parser.add_argument("--no-color", action="store_true", help="disable ANSI colors")
    add_examples(parser, [
        "comicmeta inspect",
        "comicmeta inspect -p 'Marvel/Hawkeye (1983)/Hawkeye (1983) #001.cbz'",
    ])
    parser.set_defaults(handler=run)


def read_comicinfo(path: Path) -> dict | None:
    """Return the root ComicInfo fields of a CBZ, or None if absent/unreadable."""
    if path.suffix.lower() != ".cbz":
        return None
    try:
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                if name.lower().lstrip("./") == "comicinfo.xml":
                    root = ElementTree.fromstring(archive.read(name))
                    return {child.tag.casefold(): (child.text or "") for child in root}
    except (zipfile.BadZipFile, KeyError, OSError, ElementTree.ParseError):
        return None
    return None


def read_comicinfo_xml(path: Path) -> str | None:
    """Return the raw root ComicInfo.xml text of a CBZ, or None if absent."""
    if path.suffix.lower() != ".cbz":
        return None
    try:
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                if name.lower().lstrip("./") == "comicinfo.xml":
                    return archive.read(name).decode("utf-8", errors="replace")
    except (zipfile.BadZipFile, KeyError, OSError):
        return None
    return None


def write_comicinfo(path: Path, metadata: dict) -> None:
    """Replace a CBZ's root ComicInfo.xml in place (creates it if missing)."""
    with zipfile.ZipFile(path) as source_archive:
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".cbz.tmp", delete=False) as handle:
            temporary = Path(handle.name)
        try:
            with zipfile.ZipFile(temporary, "w") as destination:
                destination.comment = source_archive.comment
                for info in source_archive.infolist():
                    if info.filename.lower().lstrip("./") == "comicinfo.xml":
                        continue  # drop the old one; write reviewed below
                    destination.writestr(info, source_archive.read(info.filename))
                destination.writestr("ComicInfo.xml", _archive.comicinfo_xml(metadata))
            import os
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def _prompt_edit(metadata: dict) -> dict | None:
    """Interactively edit metadata fields, returning the result or None on cancel."""
    from comicmeta._tui import prompt_edit
    edited = dict(metadata)
    print("  Enter keeps value. '-' clears optional. Leave blank to keep.")
    for field in EDIT_FIELDS:
        current = edited.get(field, "")
        value = prompt_edit(f"  {field} [{current}]: ", current=str(current))
        if value is None:
            return None
        if value == "-":
            edited.pop(field, None)
        elif value != current:
            edited[field] = value
    missing = [f for f in REQUIRED_FIELDS if not str(edited.get(f, "")).strip()]
    if missing:
        print(f"  Not saved. Missing required fields: {', '.join(missing)}")
        return None
    return edited


def _render(colors, relative: str, metadata: dict | None, size: int, path: Path) -> None:
    from comicmeta._common import color_enabled, Palette
    if metadata is None:
        print(f"  {colors.warn('(no ComicInfo.xml)')}  {colors.muted(pretty_bytes(size))}  {colors.path(relative)}")
        return
    print(f"  {colors.good('✓ ComicInfo')}  {colors.muted(pretty_bytes(size))}  {colors.path(relative)}")
    for field in ("series", "volume", "number", "year", "format", "title", "publisher"):
        if metadata.get(field):
            print(f"      {field:<10} {metadata[field]}")


def inspect_one(path: Path, source_root: Path, backup_dir: Path | None, colors) -> int:
    """Inspect and optionally edit a single archive. Returns 0 on clean exit."""
    from comicmeta._common import color_enabled, Palette
    from comicmeta._tui import read_key
    if not path.is_file():
        die(f"archive does not exist: {path}")
    metadata = read_comicinfo(path)
    print(f"  Inspecting: {colors.path(path)}")
    from comicmeta._commands.flags import flag_for
    series_note, issue_note = flag_for(path.resolve(), source_root)
    if series_note or issue_note:
        print(colors.warn("  ✦ FLAGGED FOR RESEARCH"))
        if series_note:
            print(colors.warn(f"      series: {series_note}"))
        if issue_note:
            print(colors.warn(f"      issue:  {issue_note}"))
    print()
    _render(colors, path.as_posix(), metadata, path.stat().st_size, path)
    print()
    print(colors.muted("  [e] edit metadata · [v] view full XML · [q] quit"))
    key = read_key()
    if key in {"q", "ctrl-c", "ctrl-d"}:
        return 0
    if key == "v":
        raw = read_comicinfo_xml(path)
        if raw:
            print(raw)
        else:
            print("  (no ComicInfo.xml present)")
        read_key()
        return 0
    if key == "e":
        edited = _prompt_edit(metadata or {})
        if edited is None:
            return 0
        if path.suffix.lower() != ".cbz":
            die(f"editing metadata is CBZ-only: {path}")
        if backup_dir is None:
            flat = _config.load(source_root)
            backup_dir = Path(_config.get(flat, "paths.backup_dir"))
        relative = path.relative_to(source_root)
        backup = backup_dir / relative
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, backup)
        write_comicinfo(path, edited)
        print(f"  Edited metadata for {path} (backup: {backup})")
        read_key()
        return 0
    return 0


def run(args: argparse.Namespace) -> None:
    from comicmeta._common import color_enabled, Palette
    colors = Palette(color_enabled(args))
    flat = _config.load(getattr(args, "source", None))
    source = args.source or Path(_config.get(flat, "paths.source"))
    if not source.is_dir():
        die_missing_source(source)
    backup_dir = args.backup_dir or Path(_config.get(flat, "paths.backup_dir"))

    if args.path:
        path = args.path if args.path.is_absolute() else (source / args.path)
        inspect_one(path.resolve(), source.resolve(), backup_dir, colors)
        return

    print(f"  Metadata in {source}:")
    print()
    cache = _archive.ComicInfoCache()
    for path in _archive.archives(source, exclude=_config.scan_excludes(flat)):
        if path.suffix.lower() != ".cbz":
            continue
        relative = path.relative_to(source)
        if args.quick:
            present = _archive.cached_root_comicinfo(path, cache)
            metadata = {"series": ""} if present else None
            _render(colors, relative.as_posix(), metadata, path.stat().st_size, path)
        else:
            metadata = read_comicinfo(path)
            _render(colors, relative.as_posix(), metadata, path.stat().st_size, path)
    print()
    print(colors.muted("  To edit one, run: comicmeta inspect -p 'RELATIVE/PATH.cbz'"))
