"""comicmeta stage — copy reviewed CBZ files into an empty staging root."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from comicmeta import _archive
from comicmeta._common import add_examples, load_json


def add_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "stage",
        help="copy reviewed CBZ files into an empty staging root",
        description=__doc__,
    )
    parser.add_argument("--source", "-s", required=True, type=Path, help="comic library root")
    parser.add_argument("--destination", "-d", required=True, type=Path, help="empty staging root to create")
    parser.add_argument("--mapping", "-m", required=True, type=Path, help="reviewed JSON mapping")
    parser.add_argument("--report", "-r", required=True, type=Path, help="JSON report path")
    add_examples(parser, [
        "comicmeta stage -s . -d /tmp/staging -m mapping.json -r stage.json",
    ])
    parser.set_defaults(handler=run)


def prepare(source: Path, destination: Path, mapping: dict) -> list[dict]:
    source = source.resolve()
    if not source.is_dir():
        raise ValueError(f"source does not exist: {source}")
    if destination.exists() and not destination.is_dir():
        raise ValueError(f"destination is not a directory: {destination}")
    if destination.is_dir() and any(destination.iterdir()):
        raise ValueError(f"destination is not empty: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    report = []
    for relative in sorted(mapping):
        relative_path = Path(relative)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError(f"unsafe mapping path: {relative}")
        original = (source / relative_path).resolve()
        if source not in original.parents or not original.is_file():
            raise ValueError(f"source file missing or unsafe: {relative}")
        if original.suffix.casefold() != ".cbz":
            raise ValueError(f"staging supports CBZ only: {relative}")
        staged = destination / relative_path
        if staged.exists():
            raise ValueError(f"staging collision: {staged}")
        staged.parent.mkdir(parents=True, exist_ok=True)
        _copy2_lenient(original, staged)
        before = _archive.sha256(original)
        after = _archive.sha256(staged)
        if before != after:
            raise ValueError(f"copy hash mismatch: {relative}")
        report.append({"path": relative, "source_sha256": before, "staged_sha256": after})
    return report


def _copy2_lenient(source: Path, destination: Path) -> None:
    """Copy a file, tolerating unpermitted metadata (e.g. chflags on some volumes).

    `shutil.copy2` copies file flags which macOS rejects when staging onto a
    temp volume. Copy content + best-effort stat; never fail the copy over
    metadata we cannot set.
    """
    shutil.copyfile(source, destination)
    try:
        shutil.copystat(source, destination, follow_symlinks=True)
    except (OSError, NotImplementedError):
        pass


def run(args: argparse.Namespace) -> None:
    mapping = load_json(args.mapping, "mapping")
    try:
        report = prepare(args.source, args.destination, mapping)
    except ValueError as error:
        raise SystemExit(str(error))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps({"items": report}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"▸ STAGE — {len(report)} reviewed CBZ file(s) staged (hashes verified)")
    print(f"STAGED files={len(report)} destination={args.destination} report={args.report}")
