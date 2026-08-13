"""comicmeta health — scan the library for corrupt archives and metadata issues.

Walks every archive, verifies it opens cleanly, checks ComicInfo.xml presence
and required fields, and reports a summary. Read-only; never modifies archives.
Fast by default (presence check via cache); `--deep` opens every archive fully.
"""

from __future__ import annotations

import argparse
import os
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from comicmeta import _archive, _config
from comicmeta._common import color_enabled, REQUIRED_FIELDS, Palette, add_examples, die


def add_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "health",
        help="scan the library for corrupt archives and metadata problems",
        description=__doc__,
    )
    parser.add_argument("--source", "-s", type=Path, help="comic library root (default: current directory)")
    parser.add_argument("--deep", action="store_true", help="fully verify every archive member (slower)")
    parser.add_argument("--no-color", action="store_true", help="disable ANSI colors")
    add_examples(parser, [
        "comicmeta health",
        "comicmeta health --deep",
    ])
    parser.set_defaults(handler=run)


def _verify_non_zip(path: Path) -> tuple[bool, bool]:
    """Return (verified_ok, verifier_available) for a .cbr/.cb7 archive.

    RAR and 7z archives cannot be opened as ZIP. When a reader (rarfile /
    py7zr) is installed the archive is checked in its own format; when no
    reader is available the file is reported as unverified instead of being
    mislabelled corrupt.
    """
    suffix = path.suffix.lower()
    try:
        if suffix == ".cbr":
            import rarfile
        elif suffix == ".cb7":
            import py7zr
        else:
            return True, False
    except ImportError:
        return False, False
    try:
        if suffix == ".cbr":
            with rarfile.RarFile(path):
                pass
        else:
            with py7zr.SevenZipFile(path):
                pass
        return True, True
    except Exception:
        return False, True


def scan(source: Path, deep: bool = False, exclude: set[str] | None = None) -> dict:
    """Return health summary: corrupt, missing-metadata, incomplete-metadata."""
    result = {"total": 0, "corrupt": [], "no_metadata": [], "incomplete": [], "errors": [], "unverified": []}
    for path in _archive.archives(source, exclude=exclude):
        result["total"] += 1
        suffix = path.suffix.lower()
        if suffix not in (".cbz", ".cbt"):
            ok, verifier = _verify_non_zip(path)
            if ok:
                continue
            if verifier:
                result["corrupt"].append(str(path.relative_to(source)))
            else:
                result["unverified"].append(str(path.relative_to(source)))
            continue
        try:
            with zipfile.ZipFile(path) as archive:
                if deep:
                    bad = archive.testzip()
                    if bad:
                        result["corrupt"].append(str(path.relative_to(source)))
                        continue
                has_ci = any(n.lower().lstrip("./") == "comicinfo.xml" for n in archive.namelist())
        except (zipfile.BadZipFile, OSError):
            result["corrupt"].append(str(path.relative_to(source)))
            continue
        if not has_ci:
            result["no_metadata"].append(str(path.relative_to(source)))
            continue
        if suffix == ".cbz":
            try:
                with zipfile.ZipFile(path) as archive:
                    for name in archive.namelist():
                        if name.lower().lstrip("./") == "comicinfo.xml":
                            root = ElementTree.fromstring(archive.read(name))
                            fields = {child.tag.casefold(): (child.text or "").strip() for child in root}
                            break
                missing = [f for f in REQUIRED_FIELDS if not fields.get(f)]
                if missing:
                    result["incomplete"].append(f"{path.relative_to(source)}: missing {', '.join(missing)}")
            except (zipfile.BadZipFile, OSError, ElementTree.ParseError):
                result["errors"].append(str(path.relative_to(source)))
    return result


def run(args: argparse.Namespace) -> None:
    colors = Palette(color_enabled(args))
    flat = _config.load(getattr(args, "source", None))
    source = args.source or Path(_config.get(flat, "paths.source"))
    if not source.is_dir():
        die(f"source does not exist: {source}")

    print(colors.title("▸ HEALTH"))
    print(colors.muted(f"  {source}"))
    print()
    from comicmeta._spinner import Spinner
    with Spinner("Scanning library") as spinner:
        result = scan(source, args.deep, _config.scan_excludes(flat))
        spinner.update("Scan complete")

    def _section(label, items):
        if not items:
            return
        print(f"\n  {colors.warn(label)} ({len(items)}):")
        for item in items[:20]:
            print(f"      {colors.path(item)}")
        if len(items) > 20:
            print(colors.muted(f"      … and {len(items) - 20} more"))

    total = result["total"]
    ok = total > 0 and all(not result[key] for key in ("corrupt", "no_metadata", "incomplete", "errors"))
    if ok and not result["unverified"]:
        _all_clear_banner(colors, total)
    elif total == 0:
        print(colors.muted("— no archives found"))
    else:
        print(colors.warn("✗ issues found"))
    summary = f"  total={total} corrupt={len(result['corrupt'])} "
    summary += f"no-metadata={len(result['no_metadata'])} incomplete={len(result['incomplete'])}"
    if result["unverified"]:
        summary += f" unverified={len(result['unverified'])}"
    print(summary)
    for label, key in (("CORRUPT", "corrupt"), ("NO METADATA", "no_metadata"),
                       ("INCOMPLETE", "incomplete"), ("ERROR", "errors")):
        _section(label, result[key])
    if result["unverified"]:
        print(f"\n  {colors.muted('NOT VERIFIED')} ({len(result['unverified'])}):")
        for item in result["unverified"][:20]:
            print(f"      {colors.path(item)}")
        if len(result["unverified"]) > 20:
            print(colors.muted(f"      … and {len(result['unverified']) - 20} more"))
        print(colors.muted("  RAR/7z archives — install rarfile/py7zr to verify them."))


def _all_clear_banner(colors, total: int) -> None:
    """Boxed ALL-CLEAR banner shown when health has nothing to report."""
    line1 = f"  ✓  ALL CLEAR — {total} archive{'s' if total != 1 else ''} checked"
    line2 = "     no corrupt · no missing metadata"
    inner = max(len(line1), len(line2))
    print(colors.good("┌" + "─" * (inner + 2) + "┐"))
    print(colors.good("│" + line1.ljust(inner + 2) + "│"))
    print(colors.good("│" + line2.ljust(inner + 2) + "│"))
    print(colors.good("└" + "─" * (inner + 2) + "┘"))
