"""comicmeta validate — validate staged ComicInfo writes without changing archives."""

from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from comicmeta import _archive
from comicmeta._common import COMICINFO_FIELDS, REQUIRED_FIELDS, add_examples, die, load_json, serialize_multi


def add_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "validate",
        help="validate staged ComicInfo writes against production state",
        description=__doc__,
    )
    parser.add_argument("--source", "-s", required=True, type=Path, help="staging root")
    parser.add_argument("--production", "-p", required=True, type=Path, help="production comic library root")
    parser.add_argument("--backup-dir", required=True, type=Path, help="backup directory")
    parser.add_argument("--mapping", "-m", required=True, type=Path, help="reviewed JSON mapping")
    parser.add_argument("--copy-report", required=True, type=Path, help="stage report JSON")
    parser.add_argument("--write-report", required=True, type=Path, help="write report JSON")
    add_examples(parser, [
        "comicmeta validate -s /tmp/staging -p . -m mapping.json --copy-report stage.json --write-report write.json",
    ])
    parser.set_defaults(handler=run)


def indexed_report(path: Path) -> dict[str, dict]:
    report = load_json(path, "report")
    return {item["path"]: item for item in report["items"]}


def validate(
    source: Path,
    production: Path,
    backup_dir: Path,
    mapping: dict,
    copy_report: dict[str, dict],
    write_report: dict[str, dict],
) -> list[dict]:
    results = []
    for relative, metadata in sorted(mapping.items()):
        staged = source / relative
        backup = backup_dir / relative
        active = production / relative
        if relative not in copy_report or relative not in write_report:
            raise ValueError(f"missing report entry: {relative}")
        with zipfile.ZipFile(staged) as archive:
            unreadable = archive.testzip()
            comicinfo = [
                name for name in archive.namelist()
                if name.lower().lstrip("./") == "comicinfo.xml"
            ]
            if unreadable:
                raise ValueError(f"unreadable archive member: {relative}: {unreadable}")
            if len(comicinfo) != 1:
                raise ValueError(f"expected one root ComicInfo.xml: {relative}")
            root = ElementTree.fromstring(archive.read(comicinfo[0]))
        fields = {child.tag.casefold(): child.text for child in root}
        tag_names = getattr(_archive, "_TAG_NAMES", {})
        for field in COMICINFO_FIELDS:
            if field not in metadata or metadata[field] in (None, ""):
                continue
            tag = tag_names.get(field, field.title()).casefold()
            if fields.get(tag) != serialize_multi(metadata[field]):
                raise ValueError(f"metadata mismatch: {relative}: {field}")
        original_hash = copy_report[relative]["source_sha256"]
        staged_hash = _archive.sha256(staged)
        if _archive.sha256(backup) != original_hash:
            raise ValueError(f"backup hash mismatch: {relative}")
        if _archive.sha256(active) != original_hash:
            raise ValueError(f"production hash changed: {relative}")
        if staged_hash != write_report[relative]["after"]:
            raise ValueError(f"staged hash mismatch: {relative}")
        results.append({"path": relative, "before": original_hash, "after": staged_hash})
    return results


def run(args: argparse.Namespace) -> None:
    mapping = load_json(args.mapping, "mapping")
    try:
        results = validate(
            args.source,
            args.production,
            args.backup_dir,
            mapping,
            indexed_report(args.copy_report),
            indexed_report(args.write_report),
        )
    except (KeyError, OSError, ValueError, zipfile.BadZipFile) as error:
        raise SystemExit(str(error))
    for item in results:
        print(f"VALID path={item['path']} before={item['before']} after={item['after']}")
    print(f"▸ VALIDATE — {len(results)} staged archive(s) match production and backup")
    print(f"STAGING_METADATA=OK files={len(results)} production_unchanged=yes")
