"""comicmeta map — generate CBZ writer mapping from completed issue review state."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from comicmeta._common import ALLOWED_FIELDS, REQUIRED_FIELDS, add_examples, load_json


def add_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "map",
        help="generate CBZ-only writer mapping from issue review state",
        description=__doc__,
    )
    parser.add_argument("--candidates", "-c", type=Path, default=Path("comicvine-issue-candidates.json"), help="issue candidates JSON")
    parser.add_argument("--review", "-r", type=Path, default=Path("comicvine-issue-review-state.json"), help="completed issue review state JSON")
    parser.add_argument("--output", "-o", type=Path, default=Path("comic-metadata-reviewed-mapping.json"), help="writer mapping JSON")
    parser.add_argument("--kavita-export", type=Path, help="future Kavita API synchronization export JSON")
    add_examples(parser, [
        "comicmeta map",
        "comicmeta map -c issues.json -r state.json -o mapping.json",
    ])
    parser.set_defaults(handler=run)


def generate_mapping(candidates: dict, review: dict) -> tuple[dict, list[str]]:
    formats = {
        match["path"]: match.get("archive_format", "").casefold()
        for series in candidates.get("series", [])
        for match in series.get("matches", [])
    }
    mapping = {}
    skipped = []
    for path, result in sorted(review.get("reviews", {}).items()):
        if result.get("status") not in {"accepted", "auto-accepted", "edited", "manual"}:
            skipped.append(f"{path}: status={result.get('status', 'unknown')}")
            continue
        if formats.get(path) != "cbz":
            skipped.append(f"{path}: archive-format={formats.get(path, 'unknown')}")
            continue
        metadata = result.get("metadata") or {}
        missing = [field for field in REQUIRED_FIELDS if not str(metadata.get(field, "")).strip()]
        if missing:
            raise ValueError(f"{path}: missing required fields: {', '.join(missing)}")
        mapping[path] = {
            field: metadata[field]
            for field in ALLOWED_FIELDS
            if field in metadata and metadata[field] not in (None, "")
        }
    return mapping, skipped


def kavita_export(mapping: dict, source: str | None = None) -> dict:
    """Build a reviewed external-ID payload; no non-ComicVine IDs are invented."""
    return {
        "version": 1,
        "source": source,
        "provider_ids": {"comicvine": "reviewed", "kavita": "not-populated"},
        "items": [
            {
                "path": path,
                "metadata": metadata,
                "external_ids": {
                    key: metadata[key]
                    for key in ("comicvine_issue_id", "comicvine_volume_id")
                    if metadata.get(key) not in (None, "")
                },
                "kavita_external_ids": {},
            }
            for path, metadata in sorted(mapping.items())
        ],
    }


def run(args: argparse.Namespace) -> None:
    candidates = load_json(args.candidates, "candidates")
    review = load_json(args.review, "review")
    reviewed = review.get("reviews", {})
    candidate_paths = {match["path"] for series in candidates.get("series", []) for match in series.get("matches", [])}
    missing = [path for path in sorted(candidate_paths) if path not in reviewed]
    if missing:
        # Partial review is usable: build the mapping from what IS reviewed and
        # say plainly what is deferred, rather than blocking every write.
        print(
            f"PARTIAL mapping: {len(candidate_paths) - len(missing)}/{len(candidate_paths)} reviewed;",
            f"{len(missing)} candidate(s) still pending [`comicmeta review` to finish]:",
            file=sys.stderr,
        )
        for path in missing:
            print(f"  - {path}", file=sys.stderr)
    try:
        mapping, skipped = generate_mapping(candidates, review)
    except ValueError as error:
        raise SystemExit(str(error))
    if not mapping:
        raise SystemExit("No reviewed CBZ mappings found")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(mapping, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    export_path = getattr(args, "kavita_export", None) or args.output.with_name("comicmeta-kavita-export.json")
    export_path.parent.mkdir(parents=True, exist_ok=True)
    export_path.write_text(
        json.dumps(kavita_export(mapping, candidates.get("active_source") or candidates.get("scanned_source")), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"▸ MAP — {len(mapping)} CBZ archive(s) carry reviewed metadata")
    print(f"MAPPING cbz={len(mapping)} skipped={len(skipped)} output={args.output}")
    print(f"KAVITA_EXPORT={export_path}")
    for reason in skipped:
        print(f"SKIP {reason}")
