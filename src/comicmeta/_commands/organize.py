"""comicmeta organize — audit and normalize strict-Comic library organization.

Implements the Kavita strict-Comic rules from comics/AGENTS.md: no loose files
at a publisher root, series folders named `Series Name (Starting Volume Year)`,
three-digit issue padding, no character/franchise umbrella wrappers, and no
`Volume 01` wrapper folders.

`--execute` normalizes series folders and issue filenames to the standard:

    Series Name (Starting Volume Year)/Series Name (Starting Volume Year) #NNN.ext

Volume-wrapper noise (``Vol. 5``, ``Volume 2``, ``v3``) is stripped from folder
and filename series names, and issue numbers are three-digit padded. Collected
editions without a parseable issue number are left unchanged. All moves are
plain, non-overwriting renames and every operation is logged.

Root containers — the library root itself and any top-level folder whose name
lacks a ``(Year)`` (e.g. ``Marvel/``, ``dc/``, ``Image/``) — are never renamed.
Comics sitting loose inside one are filed into a new series subfolder instead:
``Marvel/Foo (2014) #1.cbz`` → ``Marvel/Foo (2014)/Foo (2014) #001.cbz``.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from pathlib import Path

from comicmeta import _archive, _config
from comicmeta._common import color_enabled, Palette, add_examples, die, die_missing_source

PUBLISHER_ROOTS = {"DC", "Marvel"}
_YEAR_RE = re.compile(r"\((\d{4})\)\s*$")
_VOLUME_TAG_RE = re.compile(r"\b(?:Vol\.?|Volume|vol\.?|v)\s*\d+\b", re.IGNORECASE)
_COLLECTION_RE = re.compile(
    r"\b(?:omnibus|tpb|trade paperback|hardcover|deluxe edition|absolute edition|"
    r"compendium|complete collection)\b",
    re.IGNORECASE,
)
_COLLECTION_VOLUME_RE = re.compile(r"\b(?:vol\.?|volume|v)\s*([0-9]+(?:\.[0-9]+)?)\b", re.IGNORECASE)


def add_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "organize",
        help="audit and normalize strict-Comic library organization (dry-run default)",
        description=__doc__,
    )
    parser.add_argument("--source", "-s", type=Path, help="comic library root (default: current directory)")
    parser.add_argument("--dry-run", action="store_true", help="report proposed changes without applying (default)")
    parser.add_argument("--execute", action="store_true", help="apply safe renames (folders + filenames to standard)")
    parser.add_argument("--log", type=Path, help="write a log of completed/skipped operations")
    parser.add_argument("--no-color", action="store_true", help="disable ANSI colors")
    add_examples(parser, [
        "comicmeta organize",
        "comicmeta organize --dry-run",
        "comicmeta organize --execute --log organize.log",
    ])
    parser.set_defaults(handler=run)


def _archives(source: Path) -> list[Path]:
    flat = _config.load(source)
    return _archive.archives(source, exclude=_config.scan_excludes(flat))


def _split_folder(folder_name: str) -> tuple[str | None, str | None]:
    """Return (series_name, year) from a folder like 'Aquaman Vol. 5 (1994)'."""
    match = _YEAR_RE.search(folder_name)
    if not match:
        return None, None
    year = match.group(1)
    series = folder_name[: match.start()].strip()
    return series or None, year


def _clean_series(series: str) -> str | None:
    """Strip volume-wrapper and scene tags from a series name, or None if empty."""
    cleaned = _VOLUME_TAG_RE.sub("", series)
    cleaned = re.sub(r"\s*\((?:Digital|Zone-Empire|BlackManta-Empire|Son of Ultron-Empire|Shadowcat-Empire|Shan-Empire)\)\s*", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*GetComics\.INFO\s*$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().rstrip(" -")
    return cleaned or None


def _collection_volume(stem: str) -> str | None:
    match = _COLLECTION_VOLUME_RE.search(stem)
    return match.group(1) if match else None


def _is_collection(series: str, stem: str) -> bool:
    return bool(_COLLECTION_RE.search(f"{series} {stem}"))


def _canonical_folder_name(folder_name: str) -> str | None:
    """Return the standard folder name, or None when already standard."""
    series, year = _split_folder(folder_name)
    if not series or not year:
        return None
    cleaned = _clean_series(series)
    if not cleaned or cleaned == series:
        return None
    return f"{cleaned} ({year})"


def _file_number(stem: str) -> str | None:
    """Extract an issue number from a filename stem, or None if none found."""
    match = re.search(r"#\s*([0-9]+(?:\.[0-9]+)?)", stem)
    if match:
        return match.group(1)
    match = re.search(r"\b([0-9]+(?:\.[0-9]+)?)\s*\(of\s*[0-9]+\)", stem, re.IGNORECASE)
    if match:
        return match.group(1)
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*\(\d{4}(?:-\d{2})?\)(?:\s*\([^)]*\))*\s*$", stem)
    if match:
        return match.group(1)
    match = re.search(r"\(\d{4}(?:-\d{2})?\)\s+([0-9]+(?:\.[0-9]+)?)(?:\s*\([^)]*\))*\s*$", stem)
    if match:
        return match.group(1)
    return None


def _infer_folder_parts(paths: list[Path]) -> tuple[str, str] | None:
    """Infer (series, year) from a numbered archive when the folder is noisy."""
    for path in paths:
        stem = path.stem
        year_match = re.search(r"\((\d{4})\)", stem)
        if not year_match:
            continue
        prefix = stem[:year_match.start()].strip(" -_")
        prefix = re.sub(r"\s+v(?:ol(?:ume)?\.?)\s*\d+(?:\.\d+)?$", "", prefix, flags=re.IGNORECASE)
        prefix = re.sub(r"\s+[0-9]+(?:\.[0-9]+)?\s*\(of\s*[0-9]+\)$", "", prefix, flags=re.IGNORECASE)
        prefix = re.sub(r"\s+#?[0-9]+(?:\.[0-9]+)?$", "", prefix)
        series = _clean_series(prefix)
        if series:
            # Pad hyphens that are missing a space on one side
            # ("Daredevil- The", "Daredevil -The") without splitting true
            # compounds like "X-Men" or "Spider-Man".
            series = re.sub(r"(\S)-\s+", r"\1 - ", series)
            series = re.sub(r"\s+-(\S)", r" - \1", series)
            return series, year_match.group(1)
    return None


def _canonical_file_name(stem: str, ext: str, series: str, year: str) -> str | None:
    """Standard issue or collection filename, or None when unparseable."""
    if _is_collection(series, stem):
        volume = _collection_volume(stem)
        if volume is None:
            return None
        if "." not in volume:
            volume = f"{int(volume):02d}"
        return f"{series} ({year}) Vol. {volume}{ext}"
    number = _file_number(stem)
    if number is None:
        return None  # collected edition / non-numbered; leave unchanged
    if "." in number:
        padded = number  # preserve non-integer numbers (0.5, 1.5)
    else:
        padded = f"{int(number):03d}"
    return f"{series} ({year}) #{padded}{ext}"


def _is_container(source: Path, folder: Path) -> bool:
    """True for the library root or any top-level folder without a ``(Year)``.

    Containers (``Marvel/``, ``dc/``, ``Image/``, …) hold series folders; they
    are never renamed and loose archives inside them are filed into a new
    series subfolder instead.
    """
    if folder == source:
        return True
    return folder.parent == source and not _YEAR_RE.search(folder.name)


def _container_label(container: Path, source: Path) -> str:
    if container == source:
        return "library root"
    if container.name.lower() in {p.lower() for p in PUBLISHER_ROOTS}:
        return f"publisher root `{container.name}`"
    return f"container root `{container.name}`"


def _folder_issues(source: Path, path: Path, folder_parts: tuple[str, str] | None = None) -> list[str]:
    """Return non-naming violations for the file's parent folder."""
    issues = []
    folder = path.parent
    rel_folder = folder.relative_to(source)
    parts = rel_folder.parts
    # Root containers and umbrella wrappers are handled by the move planners;
    # nothing manual here.
    if folder == source or (len(parts) <= 1 and not _YEAR_RE.search(folder.name)):
        return issues
    # Folder must end with `(Year)`.
    if folder_parts is None and not _YEAR_RE.search(folder.name):
        issues.append(f"series folder lacks `(Starting Year)`: {folder.name}")
    return issues


def run(args: argparse.Namespace) -> None:
    colors = Palette(color_enabled(args))
    flat = _config.load(getattr(args, "source", None))
    source = args.source or Path(_config.get(flat, "paths.source"))
    if not source.is_dir():
        die_missing_source(source)

    apply = args.execute
    dry = not apply

    print(f"  Organize {source} ({'EXECUTE' if apply else 'DRY-RUN'})")
    print()

    archives = _archives(source)

    by_folder: dict[Path, list[Path]] = {}
    for path in archives:
        by_folder.setdefault(path.parent, []).append(path)

    container_files: dict[Path, list[Path]] = {}
    for folder in by_folder:
        if _is_container(source, folder):
            container_files[folder] = by_folder[folder]

    # Canonical folder names keyed by the existing folder path. Root
    # containers are excluded: they are never renamed — their loose files get
    # planned into new series subfolders instead (see `series_moves` below).
    folder_parts: dict[Path, tuple[str, str] | None] = {}
    folders: dict[Path, str | None] = {}
    for folder, paths in by_folder.items():
        if folder in container_files:
            continue
        series, year = _split_folder(folder.name)
        parts = (series, year) if series and year else _infer_folder_parts(paths)
        folder_parts[folder] = parts
        folders[folder] = (
            f"{_clean_series(parts[0]) or parts[0]} ({parts[1]})" if parts else None
        )

    # 1) Folder renames: Series Vol. N (Year) -> Series (Year).
    folder_moves: list[tuple[Path, Path]] = []
    for folder, canonical in folders.items():
        if canonical and canonical != folder.name:
            folder_moves.append((folder, folder.with_name(canonical)))

    # 2) File renames to `Series (Year) #NNN.ext` within their current folder.
    #    Folder renames (step 1's output) move the whole directory afterward, so
    #    file renames never cross folders and both stay valid in any order.
    #    Files inside root containers are excluded — they move into new series
    #    subfolders via `series_moves` below.
    file_renames: list[tuple[Path, Path]] = []
    for path in archives:
        folder = path.parent
        if folder in container_files:
            continue
        parts = folder_parts[folder]
        if not parts:
            continue
        series, year = parts
        cleaned = _clean_series(series)
        if not cleaned:
            continue
        target_name = _canonical_file_name(path.stem, path.suffix, cleaned, year)
        if target_name is None and not _is_collection(cleaned, path.stem):
            # Numberless one-shot in an otherwise-canonical folder: scrub
            # junk tags by renaming to the bare `Series (Year)` standard.
            target_name = f"{cleaned} ({year}){path.suffix}"
        if target_name and target_name != path.name:
            file_renames.append((path, path.with_name(target_name)))

    # 3) Root containers: file loose comics into new series subfolders.
    #    `Marvel/Foo (2014) #1.cbz` → `Marvel/Foo (2014)/Foo (2014) #001.cbz`.
    #    Numberless one-shots get a clean `Series (Year).ext` name; collections
    #    without a volume number keep their filename.
    series_moves: list[tuple[Path, Path]] = []
    manual_container: list[tuple[Path, str]] = []
    moved_sources: list[Path] = []

    def _target_name(path: Path, series: str, year: str) -> str:
        canonical = _canonical_file_name(path.stem, path.suffix, series, year)
        if canonical:
            return canonical
        if _is_collection(series, path.stem):
            return path.name
        return f"{series} ({year}){path.suffix}"

    for container in sorted(container_files, key=lambda p: p.parts):
        grouped: dict[tuple[str, str], list[Path]] = {}
        for path in container_files[container]:
            parts = _infer_folder_parts([path])
            cleaned = _clean_series(parts[0]) if parts else None
            if not cleaned:
                label = _container_label(container, source)
                manual_container.append((
                    path.relative_to(source),
                    f"loose file at {label}; couldn't infer a series folder from the filename",
                ))
                continue
            grouped.setdefault((cleaned, parts[1]), []).append(path)
        for (series, year), paths in sorted(grouped.items()):
            dest_dir = container / f"{series} ({year})"
            for path in paths:
                dest = dest_dir / _target_name(path, series, year)
                if dest != path:
                    series_moves.append((path, dest))

    # 4) Umbrella collapse: `Marvel/Hawkeye/Volume 01 (1994)/file.cbz` is two
    #    wrappers deep. When the series/year can be inferred, move files to
    #    `<publisher>/Series (Year)/` and prune the emptied wrapper folders.
    for folder in sorted(by_folder, key=lambda p: p.parts):
        rel_parts = folder.relative_to(source).parts
        if len(rel_parts) < 3 or folder in container_files:
            continue
        grouped = {}
        for path in by_folder[folder]:
            parts = _infer_folder_parts([path])
            cleaned = _clean_series(parts[0]) if parts else None
            if not cleaned:
                manual_container.append((
                    path.relative_to(source),
                    f"umbrella wrapper '{'/'.join(rel_parts[:-1])}'; "
                    "couldn't infer series/year — collapse manually",
                ))
                continue
            grouped.setdefault((cleaned, parts[1]), []).append(path)
        for (series, year), paths in sorted(grouped.items()):
            dest_dir = source / rel_parts[0] / f"{series} ({year})"
            for path in paths:
                dest = dest_dir / _target_name(path, series, year)
                if dest != path:
                    series_moves.append((path, dest))

    structural = []
    for path in archives:
        folder = path.parent
        if folder in container_files:
            continue
        rel_parts = folder.relative_to(source).parts
        if len(rel_parts) >= 3:
            continue  # umbrella collapse planner owns these
        for issue in _folder_issues(source, path, folder_parts[folder]):
            structural.append((path.relative_to(source), issue))
    structural.extend(manual_container)

    log_lines = []
    applied = skipped = 0

    print(f"  PLAN folders={len(folder_moves)} files={len(file_renames)} "
          f"moves={len(series_moves)} manual={len(structural)}")
    print()

    if structural:
        print(f"  {colors.warn('⚠ Structural (manual review required):')}")
        for rel, reason in structural:
            print(f"      {colors.path(str(rel))}")
            print(f"        {reason}")
            log_lines.append(f"{rel}\t{reason}\tmanual")
        print()

    if series_moves:
        print(f"  {colors.bold('Proposed new series folders (move out of wrapper):')}")
        for path, target in series_moves:
            if target.exists():
                print(f"      {colors.warn('SKIP (dest exists)')} {_display(source, path)} → {_display(source, target)}")
                skipped += 1
                continue
            print(f"      {_display(source, path)} → {colors.path(_display(source, target))}")
            if apply:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(path), str(target))
                moved_sources.append(path.parent)
                log_lines.append(f"{path}\t{target}\tmoved")
                applied += 1
            else:
                log_lines.append(f"{path}\t{target}\tmove-proposed")
        print()

    pruned = 0
    if apply and moved_sources:
        pruned = _prune_empty_wrappers(source, set(moved_sources))
        for folder in sorted(set(moved_sources)):
            log_lines.append(f"{folder}\t\twrapper-pruned-if-empty")

    if file_renames:
        print(f"  {colors.bold('Proposed file renames (standard naming):')}")
        for path, target in file_renames:
            if target.exists():
                print(f"      {colors.warn('SKIP (dest exists)')} {path.name} → {target.name}")
                skipped += 1
                continue
            print(f"      {path.name} → {colors.path(target.name)}")
            if apply:
                shutil.move(str(path), str(target))
                log_lines.append(f"{path}\t{target}\trenamed")
                applied += 1
            else:
                log_lines.append(f"{path}\t{target}\tproposed")
        print()

    if folder_moves:
        print(f"  {colors.bold('Proposed folder renames:')}")
        for folder, target in folder_moves:
            if target.exists():
                print(f"      {colors.warn('SKIP (dest exists)')} {folder.name} → {target.name}")
                skipped += 1
                continue
            print(f"      {folder.name}/ → {colors.path(target.name)}/")
            if apply:
                shutil.move(str(folder), str(target))
                log_lines.append(f"{folder}\t{target}\tfolder-renamed")
                applied += 1
            else:
                log_lines.append(f"{folder}\t{target}\tfolder-proposed")
        print()

    if log_lines:
        _log_write(args.log, log_lines)

    print(f"  ORGANIZE folders={len(folder_moves)} files={len(file_renames)} "
          f"moves={len(series_moves)} manual={len(structural)} applied={applied} skipped={skipped}"
          + (f" pruned={pruned}" if apply else ""))
    if dry:
        if folder_moves or file_renames or series_moves:
            print("  Run with --execute to apply the planned renames.")
        else:
            print("  No safe changes found.")


def _prune_empty_wrappers(source: Path, moved_from: set[Path]) -> int:
    """Remove wrapper folders left empty by moves; never above depth 2."""
    removed = 0
    for start in sorted(moved_from, key=lambda p: -len(p.parts)):
        folder = start
        while folder != source and source in folder.parents and folder.is_dir():
            if len(folder.relative_to(source).parts) < 2 or any(folder.iterdir()):
                break
            folder.rmdir()
            removed += 1
            folder = folder.parent
    return removed


def _display(source: Path, path: Path) -> str:
    """Library-relative display path, falling back to the full path."""
    try:
        return str(path.relative_to(source))
    except ValueError:
        return str(path)


def _log_write(log: Path | None, lines: list[str]) -> None:
    if log:
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
