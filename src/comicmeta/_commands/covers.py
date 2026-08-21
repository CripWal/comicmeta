"""comicmeta covers — preview comic covers from the library, optionally as a grid."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

from comicmeta import _archive, _cover
from comicmeta._common import add_examples, die_missing_source


def add_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "covers",
        help="preview comic covers in the terminal (or as a grid)",
        description=__doc__,
    )
    parser.add_argument("--source", "-s", type=Path, help="comic library root (default: current directory)")
    parser.add_argument("--max", type=int, default=12, help="maximum covers to preview")
    parser.add_argument("--series", type=str, help="series folder name to gallery (grid of covers)")
    add_examples(parser, [
        "comicmeta covers",
        "comicmeta covers -s /path/to/comics --max 20",
        "comicmeta covers --series 'Aquaman (1994)'",
    ])
    parser.set_defaults(handler=run)


def _gallery(series_dir: Path, colors, source_root: Path | None = None) -> None:
    """Render all covers in a series as a grid (timg) or stacked stack (chafa/image)."""
    covers = []
    source_root = source_root or series_dir.parent
    if not _cover.previews_enabled(source_root):
        print("  Cover previews are disabled — enable `Cover previews` in settings.")
        return
    for path in sorted(series_dir.glob("*.cbz")):
        data = _cover._extract_cover(path, source_root=source_root)
        if data:
            covers.append((path, data))
    if not covers:
        print(f"  No covers found in {series_dir.name}")
        return
    timg = shutil.which("timg")
    chafa = shutil.which("chafa")
    terminal_image = shutil.which("image")
    with tempfile.TemporaryDirectory(prefix="comicmeta-gallery-") as directory:
        files = []
        for index, (path, (data, suffix)) in enumerate(covers):
            tmp = Path(directory) / f"{index:03d}{suffix}"
            tmp.write_bytes(data)
            files.append(tmp)
        if timg:
            cols = max(1, shutil.get_terminal_size((100, 24)).columns // 30)
            rows = max(1, shutil.get_terminal_size((100, 24)).lines // 30)
            subprocess.run([
                timg, f"--grid={cols}", "-g", f"{cols * 30}x{rows * 30}",
                *[str(f) for f in files],
            ])
        elif chafa:
            cols = max(1, shutil.get_terminal_size((100, 24)).columns // 2)
            rows = max(1, shutil.get_terminal_size((100, 24)).lines // len(files))
            for f in files:
                subprocess.run([chafa, "--format", "blocks", "--size", f"{cols}x{rows}", str(f)])
        elif terminal_image:
            # terminal-image-cli has no grid mode; render covers stacked.
            for f in files:
                subprocess.run([terminal_image, str(f)])
        else:
            print("  No color renderer found; using ASCII cover previews.")
            for path, (data, suffix) in covers:
                print(f"\n  {path.name}")
                print(_cover.preview_data(data, suffix))
    print(f"\n  {len(covers)} covers · {series_dir.name}")


def run(args: argparse.Namespace) -> None:
    from comicmeta import _config
    from comicmeta._common import die
    flat = _config.load(getattr(args, "source", None))
    source = args.source or Path(_config.get(flat, "paths.source"))
    if not source.is_dir():
        die_missing_source(source)
    print("▸ COVERS")
    print(f"  {source}")
    print()
    if not _cover.previews_enabled(source):
        print("  Cover previews are disabled — enable `Cover previews` in settings.")
        return
    if args.series:
        series_dir = source / args.series
        if not series_dir.is_dir():
            die(f"series folder not found: {args.series}")
        _gallery(series_dir, None, source)
        return
    if not _cover.supports_inline():
        has_tool = any(shutil.which(tool) for tool in ("timg", "image", "chafa"))
        if not has_tool:
            print("Note: covers will render as ASCII fallback — install timg, chafa, "
                  "or terminal-image-cli for true-color previews.")
    shown = 0
    for path in _archive.archives(source, exclude=_config.scan_excludes(flat)):
        if path.suffix.lower() != ".cbz":
            continue
        if shown >= args.max:
            break
        print(path.relative_to(source))
        cover = _cover.preview(path, source)
        if cover:
            print(cover)
        else:
            print("  [no image cover found]")
        print()
        shown += 1
    if shown == 0:
        print("  No CBZ archives found — check the source path or convert CBR files first.")
    print(f"COVERS shown={shown}")
