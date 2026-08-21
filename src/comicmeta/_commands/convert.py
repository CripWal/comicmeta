"""comicmeta convert — convert CBR (RAR) archives to CBZ (ZIP).

RAR has no standard-library writer on macOS, so in-place CBR metadata is not
feasible. This command instead converts a CBR to CBZ: extract with the built-in
`bsdtar`, insert (or preserve) ComicInfo.xml, re-pack as ZIP, and rename
`.cbr` → `.cbz`. The original `.cbr` is moved to a backup, never deleted.

Per comics/AGENTS.md, converting `.cbr` to `.cbz` requires explicit approval.
Dry-run is the default; `--execute` applies the conversion.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from comicmeta import _archive, _config
from comicmeta._common import color_enabled, REQUIRED_FIELDS, add_examples, die, die_missing_source, _truncate_ansi, _terminal_size

ARCHIVE_SUFFIXES = {".cbr", ".cb7", ".cbt", ".cbz"}


def add_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "convert",
        help="convert CBR archives to CBZ with ComicInfo.xml (requires --execute)",
        description=__doc__,
    )
    parser.add_argument("--source", "-s", type=Path, help="comic library root (default: current directory)")
    parser.add_argument("--mapping", "-m", type=Path, help="reviewed JSON mapping to apply during conversion")
    parser.add_argument("--backup-dir", type=Path, help="backup directory for originals (default: from settings)")
    parser.add_argument("--dry-run", action="store_true", help="report what would convert without applying (default)")
    parser.add_argument("--execute", action="store_true", help="apply the conversions (explicit approval required)")
    parser.add_argument("--log", type=Path, help="write a log of completed/skipped operations")
    parser.add_argument("--no-color", action="store_true", help="disable ANSI colors")
    add_examples(parser, [
        "comicmeta convert",                       # dry-run: list CBRs that would convert
        "comicmeta convert --execute",             # convert with approval
        "comicmeta convert --mapping mapping.json --execute",
    ])
    parser.set_defaults(handler=run)


def _bsdtar_available() -> bool:
    return shutil.which("bsdtar") is not None


def _extractor() -> str | None:
    """First available archive extractor (bsdtar, 7z, or unrar)."""
    for tool in ("bsdtar", "7zz", "7z", "unrar"):
        if shutil.which(tool):
            return tool
    return None


def _extract_command(tool: str, cbr: Path, extracted: Path) -> list[str]:
    if tool == "bsdtar":
        return ["bsdtar", "-xf", str(cbr), "-C", str(extracted)]
    if tool.startswith("7z"):
        # 7z's -o flag takes the output dir with no separator: -o/path
        return [tool, "x", str(cbr), f"-o{extracted}", "-y"]
    return ["unrar", "x", "-y", str(cbr), str(extracted) + "/"]


def convert_cbr(cbr: Path, metadata: dict | None, backup_dir: Path) -> Path:
    """Convert one CBR to CBZ. Returns the new CBZ path. Raises on failure."""
    tool = _extractor()
    if tool is None:
        raise RuntimeError("no archive extractor found (need bsdtar, 7z, or unrar)")
    cbz = cbr.with_suffix(".cbz")
    if cbz.exists():
        raise RuntimeError(f"destination already exists: {cbz}")
    with tempfile.TemporaryDirectory(prefix="comicmeta-convert-") as temporary:
        root = Path(temporary)
        extracted = root / "pages"
        extracted.mkdir()
        result = subprocess.run(
            _extract_command(tool, cbr, extracted),
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"{tool} failed on {cbr}: {result.stderr.strip()[:200]}")
        with zipfile.ZipFile(cbz, "w") as destination:
            destination.comment = b"converted by comicmeta"
            for page in sorted(extracted.rglob("*")):
                if page.is_file():
                    destination.write(page, page.relative_to(extracted).as_posix())
            if metadata:
                destination.writestr("ComicInfo.xml", _archive.comicinfo_xml(metadata))
    return cbz


def find_cbrs(source: Path) -> list[Path]:
    flat = _config.load(source)
    return [
        p for p in _archive.archives(source, exclude=_config.scan_excludes(flat))
        if p.suffix.lower() in {".cbr", ".cb7", ".cbt"}
    ]


def convert_list(cbrs: list[Path], source: Path, mapping: dict, backup_dir: Path,
                 apply: bool, log: Path | None, colors) -> tuple[int, int]:
    """Convert the given CBRs. Returns (applied, skipped)."""
    from comicmeta._spinner import Spinner
    from comicmeta._humanize import pretty_bytes
    log_lines = []
    applied = skipped = 0
    failures: list[str] = []
    if apply:
        spinner = Spinner(f"Converting 0/{len(cbrs)}")
        spinner.__enter__()
    try:
        for index, cbr in enumerate(cbrs, 1):
            relative = cbr.relative_to(source)
            size = pretty_bytes(cbr.stat().st_size).rjust(9)
            metadata = mapping.get(relative.as_posix()) if mapping else None
            new_path = cbr.with_suffix(".cbz")
            if metadata:
                missing = [f for f in REQUIRED_FIELDS if not str(metadata.get(f, "")).strip()]
                if missing:
                    if apply:
                        spinner.progress(index, len(cbrs), item=f"{relative}  (missing metadata)")
                    else:
                        print(f"  {colors.path(str(relative))}  {colors.muted(size)}")
                        print(f"      {colors.warn('⚠ metadata missing required fields; skipping')}")
                    skipped += 1
                    continue
            if new_path.exists():
                if apply:
                    spinner.progress(index, len(cbrs), item=f"{relative}  (destination exists)")
                else:
                    print(f"  {colors.path(str(relative))}  {colors.muted(size)}")
                    print(f"      {colors.warn('SKIP (destination exists)')} → {new_path.name}")
                skipped += 1
                continue
            if apply:
                try:
                    converted = convert_cbr(cbr, metadata, backup_dir)
                    backup = backup_dir / relative
                    backup = backup.with_suffix(".cbr")
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(cbr), str(backup))
                    shutil.move(str(converted), str(new_path))
                    log_lines.append(f"{relative}\t{new_path}\tconverted")
                    applied += 1
                except Exception as error:
                    failures.append(f"{relative}: {error}")
                    skipped += 1
                spinner.progress(index, len(cbrs), item=relative.as_posix())
            else:
                print(f"  {colors.path(str(relative))}  {colors.muted(size)}")
                print(f"      → {colors.path(new_path.name)}" + ("  (ComicInfo.xml added)" if metadata else "  (no metadata)"))
                log_lines.append(f"{relative}\t{new_path}\tproposed")
    finally:
        if apply:
            spinner.progress(applied, len(cbrs))
            spinner.succeed(f"Converted {applied}/{len(cbrs)}")
            spinner.__exit__(None, None, None)
    for failure in failures:
        print(f"  {colors.warn(f'FAILED: {failure}')}")
    if log:
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(log_lines) + "\n")
    return applied, skipped


def convert_picker(source: Path, mapping: dict, backup_dir: Path, colors, prompt: str = "Select CBRs to convert") -> tuple[int, int]:
    """Interactive CBR picker: arrow keys to move, space to toggle, Enter to convert.

    Returns (converted, skipped). Designed for use from the dashboard and the
    review flow so a user can approve CBR → CBZ conversion before reviewing.
    """
    from comicmeta._tui import read_key

    cbrs = find_cbrs(source)
    if not cbrs:
        print("  ✓ No CBR archives found.")
        return 0, 0

    selected = 0
    toggled: set[int] = set()
    from comicmeta._humanize import pretty_bytes
    sizes = [cbr.stat().st_size for cbr in cbrs]
    if sys.stdout.isatty():
        print("\033[2J\033[H", end="", flush=True)
    while True:
        if sys.stdout.isatty():
            print("\033[2J\033[H", end="", flush=True)
        print(colors.title("▸ CONVERT CBR → CBZ"))
        term_cols, term_rows = _terminal_size((80, 24))
        print(_truncate_ansi(colors.muted(prompt), term_cols))
        print(_truncate_ansi(colors.muted("  Converting moves the original .cbr to comicmeta-backups/latest/"), term_cols))
        print()
        window = max(5, term_rows - 10)
        start = min(max(0, selected - window // 2), max(0, len(cbrs) - window))
        end = min(len(cbrs), start + window)
        if start:
            print(colors.muted(f"    … {start} more"))
        for index in range(start, end):
            cbr = cbrs[index]
            rel = cbr.relative_to(source)
            marker = "▸" if index == selected else " "
            check = "[x]" if index in toggled else "[ ]"
            size = colors.muted(pretty_bytes(sizes[index]).rjust(9))
            line = f"    {marker} {check} {colors.path(rel)}  {size}"
            if index == selected:
                print(colors.bold(line))
            else:
                print(line)
        if end < len(cbrs):
            print(colors.muted(f"    … {len(cbrs) - end} more"))
        print()
        picked = toggled if toggled else {selected}
        picked_size = sum(sizes[i] for i in picked)
        summary = f"  {len(picked)} of {len(cbrs)} selected · {pretty_bytes(picked_size)}"
        if not toggled:
            summary += "  (selected row; space to add more)"
        print(colors.bold(_truncate_ansi(summary, term_cols)))
        print()
        print(_truncate_ansi(colors.muted("  [↑/↓] move · [space] toggle · [a] all · [Enter] convert · [q] quit"), term_cols))
        key = read_key()
        if key in {"q", "ctrl-c", "ctrl-d"}:
            return 0, 0
        if key == "up":
            selected = max(0, selected - 1)
        elif key == "down":
            selected = min(len(cbrs) - 1, selected + 1)
        elif key == " ":
            if selected in toggled:
                toggled.remove(selected)
            else:
                toggled.add(selected)
        elif key == "a":
            if len(toggled) == len(cbrs):
                toggled.clear()
            else:
                toggled = set(range(len(cbrs)))
        elif key == "enter":
            chosen = [cbrs[i] for i in sorted(toggled)] if toggled else [cbrs[selected]]
            if not chosen:
                return 0, 0
            applied, skipped = convert_list(chosen, source, mapping, backup_dir, True, None, colors)
            print()
            print(f"  CONVERTED={applied} skipped={skipped}")
            if backup_dir:
                print(f"  Backups: {colors.path(str(backup_dir / 'latest'))}")
            print(colors.muted("  Press any key to continue…"))
            read_key()
            return applied, skipped
    return 0, 0


def _convert_summary(colors, found: int, applied: int, skipped: int) -> None:
    """Boxed summary line for the convert page."""
    rows = [
        ("found", str(found)),
        ("converted", str(applied)),
        ("skipped", str(skipped)),
    ]
    label_w = max(len(label) for label, _ in rows)
    cols, _ = _terminal_size((80, 24))
    inner = min(label_w + 3 + 6, max(4, cols - 4))
    print(colors.muted("┌" + "─" * (inner + 2) + "┐"))
    for label, value in rows:
        line = _truncate_ansi(f"  {label:<{label_w}}  {value}", inner + 2)
        print(colors.muted("│" + line.ljust(inner + 2) + "│"))
    print(colors.muted("└" + "─" * (inner + 2) + "┘"))


def run(args: argparse.Namespace) -> None:
    import os
    from comicmeta._common import color_enabled, Palette
    colors = Palette(color_enabled(args))
    flat = _config.load(getattr(args, "source", None))
    source = args.source or Path(_config.get(flat, "paths.source"))
    if not source.is_dir():
        die_missing_source(source)

    mapping = {}
    if args.mapping:
        if not args.mapping.is_file():
            die(f"mapping not found: {args.mapping}")
        mapping = json.loads(args.mapping.read_text(encoding="utf-8"))

    apply = args.execute
    dry = not apply

    backup_dir = args.backup_dir or Path(_config.get(flat, "paths.backup_dir"))
    cbrs = find_cbrs(source)

    print(colors.title("▸ CONVERT CBR → CBZ"))
    badge = colors.muted("(DRY-RUN)") if dry else colors.good("(EXECUTE)")
    print(f"  {badge}  {source}")
    print()
    if not cbrs:
        print("  ✓ No CBR archives found.")
        return

    applied, skipped = convert_list(cbrs, source, mapping, backup_dir, apply, args.log, colors)
    print()
    _convert_summary(colors, len(cbrs), applied, skipped)
    if dry:
        print("  Run with --execute to apply (converts .cbr → .cbz; original moved to backup).")
