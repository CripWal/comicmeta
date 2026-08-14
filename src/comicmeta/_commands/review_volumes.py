"""comicmeta review-volumes — interactively review ComicVine volume candidates."""

from __future__ import annotations

import argparse
import difflib
import os
import re
import sys
import unicodedata
import webbrowser
from collections import defaultdict
from pathlib import Path

from comicmeta._common import color_enabled, Palette, add_examples, atomic_json, die, load_json, progress_bar, require_tty, _truncate_ansi, _terminal_size

SPECIAL_TERMS = ("omnibus", "deluxe edition", "annual", "collection", "hardcover")


def add_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "review-volumes",
        help="interactively review ComicVine volume candidates (read-only)",
        description=__doc__,
    )
    parser.add_argument("--report", type=Path, default=Path("comicvine-candidates.json"), help="discover report JSON")
    parser.add_argument("--state", type=Path, default=Path("comicvine-review-state.json"), help="resumable review state JSON")
    parser.add_argument("--summary", type=Path, default=Path("comicvine-review.md"), help="readable review summary")
    parser.add_argument("--policy", type=Path, default=Path("comic-metadata-review-policy.json"), help="review policy JSON")
    parser.add_argument("--list", action="store_true", help="print scored recommendations and exit")
    parser.add_argument("--no-color", action="store_true", help="disable ANSI colors")
    add_examples(parser, [
        "comicmeta review-volumes",
        "comicmeta review-volumes --list",
        "comicmeta review-volumes --report candidates.json --state s.json",
    ])
    parser.set_defaults(handler=run)


def normalized(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).casefold()
    value = value.replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def query_identity(query: str) -> tuple[str, str | None]:
    match = re.search(r"\((\d{4})\)\s*$", query)
    year = match.group(1) if match else None
    title = query[:match.start()].strip() if match else query.strip()
    return title, year


def _publisher_name(candidate: dict) -> str:
    publisher = candidate.get("publisher")
    name = publisher.get("name") if isinstance(publisher, dict) else publisher
    return str(name or "")


def publisher_for(paths: list[str]) -> str | None:
    roots = {Path(path).parts[0].casefold() for path in paths if Path(path).parts}
    if "marvel" in roots:
        return "Marvel"
    if "dc" in roots:
        return "DC"
    return None


def issue_numbers(items: list[dict]) -> list[float]:
    numbers = []
    for item in items:
        value = item.get("issue_number_from_filename")
        try:
            numbers.append(float(value))
        except (TypeError, ValueError):
            continue
    return numbers


def score_candidate(group: dict, candidate: dict) -> tuple[int, list[str]]:
    expected_title, expected_year = query_identity(group["query"])
    candidate_name = candidate.get("name") or ""
    title_ratio = difflib.SequenceMatcher(None, normalized(expected_title), normalized(candidate_name)).ratio()
    score = round(title_ratio * 50)
    reasons = [f"title {round(title_ratio * 100)}%"]

    candidate_year = str(candidate.get("start_year") or "")
    if expected_year and candidate_year == expected_year:
        score += 30
        reasons.append("year exact")
    elif expected_year and candidate_year:
        score -= 20
        reasons.append(f"year differs ({candidate_year})")

    expected_publisher = publisher_for(group["paths"])
    publisher = _publisher_name(candidate)
    if expected_publisher and normalized(publisher) == normalized(expected_publisher):
        score += 10
        reasons.append("publisher exact")

    local_numbers = issue_numbers(group["items"])
    count = candidate.get("count_of_issues")
    if local_numbers and isinstance(count, int):
        if max(local_numbers) <= count:
            score += 5
            reasons.append("issue range fits")
        else:
            score -= 15
            reasons.append("issue range exceeds volume")

    expected_norm = normalized(expected_title)
    candidate_norm = normalized(candidate_name)
    expected_terms = {term for term in SPECIAL_TERMS if normalized(term) in expected_norm}
    candidate_terms = {term for term in SPECIAL_TERMS if normalized(term) in candidate_norm}
    if expected_terms == candidate_terms and expected_terms:
        score += 5
        reasons.append("edition terms exact")
    elif expected_terms != candidate_terms:
        score -= 20
        reasons.append("edition terms differ")

    return max(0, min(100, score)), reasons


def grouped_items(report: dict, policy: dict | None = None, score_threshold: int = 90, score_margin: int = 15) -> list[dict]:
    policy = policy or {}
    blocked = policy.get("blocked_queries", {})
    grouped: dict[str, list[dict]] = defaultdict(list)
    for item in report.get("items", []):
        if item.get("status") == "review-required":
            grouped[item["query"]].append(item)

    result = []
    for query, items in sorted(grouped.items()):
        candidates: dict[int, dict] = {}
        for item in items:
            for candidate in item.get("candidates", []):
                if candidate.get("id") is None:
                    continue
                candidates.setdefault(candidate["id"], candidate)
        group = {
            "query": query,
            "items": items,
            "paths": [item["path"] for item in items],
            "formats": sorted({item["format"].upper() for item in items}),
            "blocked_reason": blocked.get(query),
        }
        scored = []
        for candidate in candidates.values():
            score, reasons = score_candidate(group, candidate)
            scored.append({**candidate, "score": score, "score_reasons": reasons})
        scored.sort(key=lambda value: (-value["score"], value.get("name") or "", value.get("id") or 0))
        group["candidates"] = scored
        group["recommendation"] = scored[0] if scored else None
        runner_up = scored[1]["score"] if len(scored) > 1 else 0
        group["high_confidence"] = bool(
            scored and not group["blocked_reason"] and scored[0]["score"] >= score_threshold
            and scored[0]["score"] - runner_up >= score_margin
        )
        result.append(group)
    return result


def load_state(path: Path, report_path: Path) -> dict:
    if path.exists():
        state = load_json(path)
        state.setdefault("selections", {})
        return state
    return {"version": 1, "report": str(report_path), "selections": {}}


def selection_for(candidate: dict, status: str = "selected") -> dict:
    return {
        "status": status,
        "candidate_id": candidate["id"],
        "comicvine_volume_id": candidate["id"],
        "name": candidate.get("name"),
        "start_year": candidate.get("start_year"),
        "publisher": _publisher_name(candidate),
        "count_of_issues": candidate.get("count_of_issues"),
        "site_detail_url": candidate.get("site_detail_url"),
        "comicvine_url": candidate.get("site_detail_url"),
        "score": candidate.get("score"),
    }


def write_summary(path: Path, report: dict, groups: list[dict], state: dict, policy: dict | None = None) -> None:
    policy = policy or {}
    source = Path(report.get("source") or "")
    active_source = Path(policy.get("active_source") or source)
    lines = [
        "# ComicVine Metadata Review", "", f"Scanned source: `{source}`",
        f"Active library root: `{active_source}`", "",
    ]
    for group in groups:
        choice = state["selections"].get(group["query"])
        status = "blocked" if group.get("blocked_reason") else (choice.get("status") if choice else "pending")
        lines.extend([f"## {group['query']}", "", f"Status: **{status}**", ""])
        if group.get("blocked_reason"):
            lines.extend([f"Blocked reason: {group['blocked_reason']}", ""])
        if choice and choice.get("candidate_id"):
            label = f"{choice.get('name')} ({choice.get('start_year')}) — ComicVine {choice['candidate_id']}"
            url = choice.get("site_detail_url")
            lines.append(f"Selection: [{label}]({url})" if url else f"Selection: {label}")
            lines.append("")
        lines.append("Files:")
        lines.append("")
        for relative in group["paths"]:
            lines.append(f"- Active: `{active_source / relative}`")
            if active_source != source:
                lines.append(f"  - Scanned copy: `{source / relative}`")
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def clear_screen() -> None:
    if sys.stdout.isatty():
        print("\033[2J\033[H", end="")


def render_group(group: dict, index: int, groups: list[dict], report: dict, state: dict, policy: dict, colors: Palette, show_all: bool, selected_candidate: int = 0, flag_count: tuple[int, int] = (0, 0)) -> None:
    clear_screen()
    completed = len(state["selections"])
    source = Path(report.get("source") or "")
    active_source = Path(policy.get("active_source") or source)
    term_cols, term_rows = _terminal_size((80, 24))
    print(colors.title(f"▸ COMICVINE METADATA REVIEW"))
    flags_series, flags_issues = flag_count
    if flags_series or flags_issues:
        parts = []
        if flags_issues:
            parts.append(f"{flags_issues}⚑")
        if flags_series:
            parts.append(f"{flags_series}✦")
        badge = " ".join(parts) if parts else "0"
        print(colors.warn(f"  ComicMeta {badge} · run: comicmeta flags"))
    print(colors.bold(f"  {group['query']} [{index + 1}/{len(groups)}]"))
    meta = f"reviewed {completed}/{len(groups)} · {', '.join(group['formats'])} · {len(group['paths'])} file"
    if len(group["paths"]) > 1:
        meta += "s"
    print(_truncate_ansi(f"  {progress_bar(completed, len(groups))}  {colors.muted(meta)}", term_cols))
    if group.get("blocked_reason"):
        print(colors.warn(f"  ⚠ BLOCKED: {group['blocked_reason']}"))
    current = state["selections"].get(group["query"])
    if current:
        if current.get("status") == "flagged":
            print(colors.warn(f"  ⚠ FLAGGED: {current.get('note') or 'further research required'}"))
        else:
            print(colors.good(f"  ✓ Saved: {current.get('status')} — {current.get('name') or 'no candidate'}"))
    print()
    available = max(1, term_rows - 18)
    candidate_count = min(9, len(group["candidates"]), max(1, ((available * 2) // 3) // 3))
    path_cap = max(1, (available - candidate_count * 3) // 2)
    print(colors.bold("  FILE PATHS"))
    visible = group["paths"][:path_cap] if show_all else group["paths"][:min(6, path_cap)]
    for relative in visible:
        print(f"    {'Active':<11} {colors.path(active_source / relative)}")
        if active_source != source:
            print(f"    {'Scanned':<11} {colors.muted(source / relative)}")
    if len(group["paths"]) > len(visible):
        print(colors.muted(f"    … {len(group['paths']) - len(visible)} more; press f to show all"))
    print()
    print(colors.bold("  CANDIDATES"))
    if not group["candidates"]:
        print(colors.warn("    No candidates returned"))
    cand_start = min(max(0, selected_candidate - candidate_count // 2), max(0, len(group["candidates"]) - candidate_count))
    cand_end = min(len(group["candidates"]), cand_start + candidate_count)
    if cand_start:
        print(colors.muted(f"    … {cand_start} more"))
    for number in range(cand_start, cand_end):
        candidate = group["candidates"][number]
        is_selected = number == selected_candidate
        marker = "✦" if candidate is group["recommendation"] else ("▸" if is_selected else " ")
        confidence = colors.good(f"{candidate['score']}% high confidence") if candidate["score"] >= 90 else colors.warn(f"{candidate['score']}% review")
        publisher = _publisher_name(candidate) or "Unknown publisher"
        if is_selected:
            print(_truncate_ansi(f"    {marker} {number + 1}  {colors.bold(candidate.get('name') or 'Untitled')} ({candidate.get('start_year') or '?'})", term_cols))
            print(_truncate_ansi(f"         ID {candidate.get('id') or '?'} · {publisher} · {candidate.get('count_of_issues') or '?'} issues · {confidence}", term_cols))
            print(_truncate_ansi(f"         {candidate.get('site_detail_url') or 'No link'}", term_cols))
        else:
            print(_truncate_ansi(f"    {marker} {number + 1}  {colors.muted(candidate.get('name') or 'Untitled')} ({candidate.get('start_year') or '?'})", term_cols))
            print(_truncate_ansi(f"         ID {candidate.get('id') or '?'} · {publisher} · {candidate.get('count_of_issues') or '?'} issues · {confidence}", term_cols))
            print(_truncate_ansi(f"         {candidate.get('site_detail_url') or 'No link'}", term_cols))
    if cand_end < len(group["candidates"]):
        print(colors.muted(f"    … {len(group['candidates']) - cand_end} more"))
    print()
    recommendation = group.get("recommendation")
    if group.get("blocked_reason"):
        print(colors.warn("  Recommendation disabled by review policy"))
    elif recommendation:
        label = "high confidence" if group["high_confidence"] else "review recommended"
        print(_truncate_ansi(f"  Recommended: {recommendation.get('name')} — {label}", term_cols))
    print()
    print(_truncate_ansi(colors.muted("  [↑/↓] choose candidate · [Enter] select · [a] accept · [o] open · [s] skip"), term_cols))
    print(_truncate_ansi(colors.muted("  [←/→] prev/next series · [n] next · [p] pin volume ID/URL · [!] flag for research"), term_cols))
    print(_truncate_ansi(colors.muted("  [h] accept all · [f] show all paths · [q] back"), term_cols))


def list_groups(groups: list[dict], colors: Palette, report: dict, policy: dict) -> None:
    source = Path(report.get("source") or "")
    active_source = Path(policy.get("active_source") or source)
    for group in groups:
        recommendation = group.get("recommendation")
        if recommendation:
            confidence = "BLOCKED" if group.get("blocked_reason") else ("AUTO" if group["high_confidence"] else "REVIEW")
            print(f"{colors.bold(group['query'])}: {recommendation['name']} ({recommendation.get('start_year')}) "
                  f"ID={recommendation['id']} score={recommendation['score']} {confidence}")
        else:
            print(f"{colors.bold(group['query'])}: no candidates")
        for path in group["paths"]:
            print(f"  {'Active':<11} {colors.path(active_source / path)}")
            if active_source != source:
                print(f"  {'Scanned':<11} {colors.muted(source / path)}")


def _advance(index: int, total: int) -> tuple[int, bool]:
    """Advance to the next item; returns (new_index, all_done)."""
    if index + 1 >= total:
        return index, True
    return index + 1, False


def api_key() -> str:
    from comicmeta import _config, _comicvine
    flat = _config.load(None)
    args = type("A", (), {"api_key_env": None, "api_key_file": None})()
    return _comicvine.api_key_from(args, flat)


def prompt_volume_id() -> int | None:
    """Prompt for a ComicVine volume ID (bare number or site_detail_url). Returns int or None on cancel.

    Understands ComicVine URL shapes:
      https://comicvine.gamespot.com/aquaman/4050-5230/   -> volume  5230
      https://comicvine.gamespot.com/aquaman/4050-5230/5030/ -> volume 5230
      4050                                                 -> volume 4050
    ComicVine writes resource IDs as ``<kind>-<id>`` (e.g. ``4050-5230``), so
    the last number in the URL is the volume ID.
    """
    from comicmeta._tui import prompt_edit
    text = prompt_edit("  Pin ComicVine volume ID or URL: ")
    if not text:
        return None
    numbers = [part for part in re.split(r"[^\d]+", text.strip()) if part]
    if not numbers:
        return None
    return int(numbers[-1])


def interactive(report_path: Path, state_path: Path, summary_path: Path, policy: dict, colors: Palette, score_threshold: int = 90, score_margin: int = 15) -> None:
    from comicmeta._tui import confirm, enter_alt_screen, leave_alt_screen, read_key
    enter_alt_screen()
    try:
        report = load_json(report_path, "report")
        groups = grouped_items(report, policy, score_threshold, score_margin)
        if not groups:
            print("  ✓ Nothing to review — every archive either has complete ComicInfo")
            print("    or is marked for replacement.")
            return
        state = load_state(state_path, report_path)
        from comicmeta._commands.flags import counts
        from comicmeta import _config as config_mod
        active_source = Path(policy.get("active_source") or report.get("source") or "")
        flag_count = counts(config_mod.load(active_source))
        index = 0
        show_all = False
        selected_candidate = 0
        while True:
            group = groups[index]
            render_group(group, index, groups, report, state, policy, colors, show_all, selected_candidate, flag_count)
            key = read_key()
            if key in {"q", "ctrl-c", "ctrl-d"}:
                break
            if key == "f":
                show_all = not show_all
                continue
            if key == "!":
                from comicmeta._tui import prompt_edit
                note = prompt_edit("  Flag note (for research): ")
                state["selections"][group["query"]] = {
                    "status": "flagged",
                    "note": note or "flagged for further research",
                }
                atomic_json(state_path, state)
                index, done = _advance(index, len(groups))
                show_all = False
                selected_candidate = 0
                if done:
                    break
                continue
            if key == "p":
                from comicmeta import _config
                from comicmeta._comicvine import fetch_volume
                volume_id = prompt_volume_id()
                if volume_id:
                    try:
                        volume = fetch_volume(api_key(), volume_id)
                    except Exception as error:
                        print(colors.warn(f"  ✗ Could not fetch volume {volume_id}: {error}"))
                        read_key()
                        continue
                    pinned = {
                        "id": volume["id"],
                        "name": volume.get("name"),
                        "start_year": volume.get("start_year"),
                        "publisher": volume.get("publisher"),
                        "count_of_issues": volume.get("count_of_issues"),
                        "site_detail_url": volume.get("site_detail_url"),
                        "score": 100,
                        "pinned": True,
                    }
                    group["candidates"].insert(0, pinned)
                    group["recommendation"] = pinned
                    group["high_confidence"] = True
                    selected_candidate = 0
                    continue
            if key == "o":
                current = state["selections"].get(group["query"])
                url = current.get("site_detail_url") if current else None
                url = url or (group["recommendation"] or {}).get("site_detail_url")
                if url:
                    webbrowser.open(url)
                continue
            if key in {"up"}:
                selected_candidate = max(0, selected_candidate - 1)
                continue
            if key in {"down"}:
                selected_candidate = min(len(group["candidates"]) - 1, selected_candidate + 1)
                continue
            if key == "left":
                index = max(0, index - 1)
                show_all = False
                selected_candidate = 0
                continue
            if key == "right":
                index = min(len(groups) - 1, index + 1)
                show_all = False
                selected_candidate = 0
                continue
            if key == "enter" and not group.get("blocked_reason") and group["candidates"]:
                state["selections"][group["query"]] = selection_for(group["candidates"][selected_candidate])
                atomic_json(state_path, state)
                index, done = _advance(index, len(groups))
                show_all = False
                selected_candidate = 0
                if done:
                    break
                continue
            if key == "a" and group["recommendation"] and not group.get("blocked_reason"):
                state["selections"][group["query"]] = selection_for(group["recommendation"])
                atomic_json(state_path, state)
                index, done = _advance(index, len(groups))
                show_all = False
                selected_candidate = 0
                if done:
                    break
                continue
            if key.isdigit() and not group.get("blocked_reason") and 1 <= int(key) <= min(9, len(group["candidates"])):
                state["selections"][group["query"]] = selection_for(group["candidates"][int(key) - 1])
                atomic_json(state_path, state)
                index, done = _advance(index, len(groups))
                show_all = False
                selected_candidate = 0
                if done:
                    break
                continue
            if key == "s":
                state["selections"][group["query"]] = {"status": "skipped"}
                atomic_json(state_path, state)
                index, done = _advance(index, len(groups))
                show_all = False
                selected_candidate = 0
                if done:
                    break
                continue
            if key == "h":
                pending = [g for g in groups if g["high_confidence"] and g["query"] not in state["selections"]]
                if pending and confirm(f"Accept {len(pending)} high-confidence recommendations?", default=False):
                    for candidate_group in pending:
                        state["selections"][candidate_group["query"]] = selection_for(
                            candidate_group["recommendation"], "auto-selected"
                        )
                    atomic_json(state_path, state)
                continue
            if key in {"n", ""}:
                index = min(len(groups) - 1, index + 1)
                show_all = False
                selected_candidate = 0

        atomic_json(state_path, state)
        write_summary(summary_path, report, groups, state, policy)
        print(f"Saved state: {state_path}")
        print(f"Review summary: {summary_path}")

    finally:
        leave_alt_screen()


def run(args: argparse.Namespace) -> None:
    colors = Palette(color_enabled(args))
    report = load_json(args.report, "report")
    policy = load_json(args.policy, "policy") if args.policy.exists() else {}
    groups = grouped_items(report, policy)
    if args.list:
        list_groups(groups, colors, report, policy)
        return
    require_tty("review-volumes", "comicmeta review-volumes --list")
    interactive(args.report, args.state, args.summary, policy, colors)
