"""comicmeta fetch-issues — fetch issue-level ComicVine data for selected volumes."""

from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from comicmeta import _comicvine
from comicmeta._common import add_examples, load_json


def add_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "fetch-issues",
        help="fetch ComicVine issues for reviewed volume selections (read-only)",
        description=__doc__,
    )
    parser.add_argument("--candidates", "-c", type=Path, help="discover report JSON (default: from settings)")
    parser.add_argument("--selections", type=Path, help="reviewed volume selections JSON (default: from settings)")
    parser.add_argument("--policy", type=Path, help="review policy JSON (default: from settings)")
    parser.add_argument("--report", "-r", type=Path, help="issue candidates JSON (default: from settings)")
    parser.add_argument("--api-key-file", type=Path, help="file containing the ComicVine key")
    parser.add_argument("--api-key-env", default=None, help="environment variable containing the API key")
    parser.add_argument("--request-delay", type=float, default=None, help="seconds between ComicVine API calls")
    add_examples(parser, [
        "comicmeta fetch-issues",
        "comicmeta fetch-issues --selections s.json -r issues.json",
    ])
    parser.set_defaults(handler=run)


def build_report(candidates: dict, selections: dict, policy: dict, fetcher) -> dict:
    items_by_query: dict[str, list[dict]] = defaultdict(list)
    for item in candidates.get("items", []):
        items_by_query[item.get("query")].append(item)

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scanned_source": candidates.get("source"),
        "active_source": policy.get("active_source") or candidates.get("source"),
        "series": [],
    }
    skipped = 0
    for query, selection in sorted(selections.get("selections", {}).items()):
        if selection.get("status") not in {"selected", "auto-selected"}:
            continue
        local_items = [item for item in items_by_query.get(query, []) if item.get("status") == "review-required"]
        if not local_items:
            # The volume is selected but no longer has review-required files
            # (already fetched/reviewed, or the scan changed). Nothing to fetch
            # for it — skip instead of aborting the whole report.
            skipped += 1
            continue
        issues = fetcher(selection["candidate_id"])
        matches = _comicvine.match_files(query, local_items, issues, selection)
        result["series"].append({
            "query": query,
            "selection": selection,
            "issue_count_returned": len(issues),
            "matches": matches,
            "unmatched_api_issues": [
                {"id": issue.get("id"), "number": issue.get("issue_number"), "name": issue.get("name")}
                for issue in issues
                if issue.get("id") not in {
                    match.get("issue", {}).get("id") for match in matches if match.get("issue")
                }
            ],
        })
    result["skipped_queries"] = skipped
    return result


def run(args: argparse.Namespace) -> None:
    from comicmeta import _config
    flat = _config.load(None)
    candidates = args.candidates or Path(_config.get(flat, "paths.candidates"))
    selections = args.selections or Path(_config.get(flat, "paths.volume_state"))
    policy_path = args.policy or Path(_config.get(flat, "paths.policy"))
    report = args.report or Path(_config.get(flat, "paths.issue_candidates"))
    request_delay = args.request_delay if args.request_delay is not None else float(_config.get(flat, "api.request_delay"))
    timeout = int(_config.get(flat, "api.timeout"))
    user_agent = _config.get(flat, "api.user_agent")
    if args.api_key_env is None:
        args.api_key_env = _config.get(flat, "api.key_env")
    if args.api_key_file is None and _config.get(flat, "api.key_file"):
        args.api_key_file = Path(os.path.expanduser(_config.get(flat, "api.key_file")))
    api_key = _comicvine.api_key_from(args, flat)
    policy = load_json(policy_path, "policy") if policy_path.exists() else {}
    from comicmeta._spinner import Spinner
    with Spinner("Fetching issue-level candidates from ComicVine") as spinner:
        report_data = build_report(
            load_json(candidates, "candidates"),
            load_json(selections, "selections"),
            policy,
            lambda volume_id: _comicvine.fetch_volume_issues(api_key, volume_id, request_delay, timeout=timeout, user_agent=user_agent),
        )
        spinner.update("Fetch complete")
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(report_data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    status_counts: dict[str, int] = defaultdict(int)
    for series in report_data["series"]:
        for match in series["matches"]:
            status_counts[match["status"]] += 1
    skipped = report_data.get("skipped_queries", 0)
    summary = " ".join(f"{key}={value}" for key, value in sorted(status_counts.items()))
    if skipped:
        summary = f"skipped={skipped} " + summary
    print(f"ISSUE REPORT series={len(report_data['series'])} {summary} report={report}")
