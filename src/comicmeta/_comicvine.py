"""ComicVine API access shared by discovery and issue enrichment."""

from __future__ import annotations

import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

from comicmeta._common import die, serialize_multi

ISSUE_FIELDS = (
    "id,name,issue_number,cover_date,store_date,volume,site_detail_url,"
    "deck,description,person_credits,character_credits,team_credits,"
    "location_credits,story_arc_credits,tags,genres,image"
)
USER_AGENT = "comicmeta/0.1"
ROLE_FIELDS = {
    "writer": "writer", "writers": "writer",
    "penciller": "penciller", "penciller/artist": "penciller", "penciler": "penciller",
    "inker": "inker", "colorist": "colorist", "colourist": "colorist",
    "letterer": "letterer", "cover artist": "cover_artist", "coverartist": "cover_artist",
    "editor": "editor",
}


def _keychain_read() -> str | None:
    """Read the ComicVine API key from the macOS Keychain via the `security` CLI.

    Returns the key string on success, None on failure (not macOS, key not found,
    keychain locked, etc.). Uses a 5-second timeout to avoid hangs.
    """
    import subprocess
    import sys
    if sys.platform != "darwin":
        return None
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-a", "comicmeta", "-s", "comicmeta", "-w"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def api_key_from(args, flat: dict | None = None) -> str:
    import os
    from comicmeta import _config
    flat = flat or {}
    env = getattr(args, "api_key_env", None) or _config.get(flat, "api.key_env") or "COMICVINE_API_KEY"
    key = os.environ.get(env)
    key_file = getattr(args, "api_key_file", None)
    if not key and not key_file and flat:
        configured = _config.get(flat, "api.key_file")
        if configured:
            key_file = Path(os.path.expanduser(configured))
    # Try keychain after env, before key_file
    if not key and _config.get(flat, "api.keychain"):
        key = _keychain_read()
    if not key and key_file:
        key = Path(os.path.expanduser(str(key_file))).read_text(encoding="utf-8").strip()
    if not key:
        die(f"{env} is not set; set api.key_env, api.key_file, or api.keychain in comicmeta.toml")
    return key


def search_volumes(api_key: str, query: str, limit: int, timeout: int = 30, user_agent: str | None = None) -> list[dict]:
    params = urllib.parse.urlencode({
        "api_key": api_key,
        "format": "json",
        "resources": "volume",
        "query": query,
        "field_list": "id,name,start_year,publisher,count_of_issues,site_detail_url,description,deck,image",
        "limit": str(limit),
    })
    request = urllib.request.Request(
        f"https://comicvine.gamespot.com/api/search/?{params}",
        headers={"User-Agent": user_agent or USER_AGENT},
    )
    payload = _api_request(request, timeout, label="volume search")
    if payload.get("error") != "OK":
        die(f"ComicVine API error: {payload.get('error', 'unknown error')}")
    return payload.get("results", [])


def search_volumes_batch(api_key: str, queries: list[str], limit: int, timeout: int = 30,
                         user_agent: str | None = None, request_delay: float = 0.25,
                         concurrency: int = 5) -> list[dict]:
    """Query several volume searches with a bounded thread pool.

    Keeps `request_delay` spacing (rate-limit safe) while overlapping the
    network latency across up to `concurrency` workers. Returns one dict per
    query: ``{"query": q, "candidates": [...]}`` in input order.
    """
    import threading
    from concurrent.futures import ThreadPoolExecutor

    results: dict[str, list[dict]] = {}
    lock = threading.Lock()
    next_start = time.monotonic()

    def worker(query: str) -> None:
        nonlocal next_start
        with lock:
            wait = max(0.0, next_start - time.monotonic())
            next_start = max(next_start + request_delay, time.monotonic() + request_delay)
        if wait:
            time.sleep(wait)
        candidates = search_volumes(api_key, query, limit, timeout=timeout, user_agent=user_agent)
        with lock:
            results[query] = candidates

    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        list(pool.map(worker, queries))
    return [{"query": query, "candidates": results.get(query, [])} for query in queries]


def _api_request(request: urllib.request.Request, timeout: int, label: str) -> dict:
    """Run a ComicVine request, converting network errors to a clean message."""
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.URLError as error:
        reason = getattr(error, "reason", error)
        die(f"ComicVine {label} failed: network error: {reason}")
    except TimeoutError:
        die(f"ComicVine {label} timed out after {timeout}s")
    except (json.JSONDecodeError, ValueError) as error:
        die(f"ComicVine {label} returned invalid JSON: {error}")
    except OSError as error:
        die(f"ComicVine {label} failed: {error}")


def fetch_volume(api_key: str, volume_id: int, timeout: int = 30, user_agent: str | None = None) -> dict:
    """Fetch a single ComicVine volume by its numeric ID."""
    params = urllib.parse.urlencode({
        "api_key": api_key,
        "format": "json",
        "field_list": "id,name,start_year,publisher,count_of_issues,site_detail_url",
    })
    request = urllib.request.Request(
        f"https://comicvine.gamespot.com/api/volume/4050-{volume_id}/?{params}",
        headers={"User-Agent": user_agent or USER_AGENT},
    )
    payload = _api_request(request, timeout, label=f"volume {volume_id}")
    if payload.get("error") != "OK":
        die(f"ComicVine API error for volume {volume_id}: {payload.get('error', 'unknown error')}")
    return payload.get("results", {})


def verify_api_key(api_key: str, timeout: int = 15, user_agent: str | None = None) -> tuple[bool, str]:
    """Verify a ComicVine API key with a minimal request. Never reads secrets."""
    params = urllib.parse.urlencode({
        "api_key": api_key,
        "format": "json",
        "resources": "volume",
        "query": "batman",
        "field_list": "id",
        "limit": "1",
    })
    request = urllib.request.Request(
        f"https://comicvine.gamespot.com/api/search/?{params}",
        headers={"User-Agent": user_agent or USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except urllib.error.URLError as error:
        return False, f"network error: {error.reason}"
    except TimeoutError:
        return False, f"network error: timed out after {timeout}s"
    except (json.JSONDecodeError, ValueError, OSError) as error:
        return False, f"network error: {error}"
    error = payload.get("error")
    if error == "OK":
        return True, "ComicVine accepted the key"
    if error == "Invalid API Key":
        return False, "ComicVine rejected the key (invalid API key)"
    return False, f"ComicVine error: {error}"


def fetch_volume_issues(api_key: str, volume_id: int, request_delay: float, timeout: int = 30, user_agent: str | None = None) -> list[dict]:
    issues = []
    offset = 0
    while True:
        parameters = urllib.parse.urlencode({
            "api_key": api_key,
            "format": "json",
            "filter": f"volume:{volume_id}",
            "field_list": ISSUE_FIELDS,
            "limit": "100",
            "offset": str(offset),
            "sort": "issue_number:asc",
        })
        request = urllib.request.Request(
            f"https://comicvine.gamespot.com/api/issues/?{parameters}",
            headers={"User-Agent": user_agent or USER_AGENT},
        )
        payload = _api_request(request, timeout, label=f"issues for volume {volume_id}")
        if payload.get("error") != "OK":
            die(f"ComicVine API error for volume {volume_id}: {payload.get('error', 'unknown error')}")
        batch = payload.get("results", [])
        issues.extend(batch)
        offset += len(batch)
        try:
            total = int(payload.get("number_of_total_results"))
        except (TypeError, ValueError):
            total = len(issues)
        if not batch or offset >= total:
            break
        time.sleep(max(0, request_delay))
    return issues


def canonical_issue_number(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip().casefold()
    if not text:
        return None
    match = re.fullmatch(r"([+-]?)(\d+)(?:\.(\d+))?", text)
    if not match:
        return re.sub(r"\s+", "", text)
    sign, whole, decimal = match.groups()
    whole = str(int(whole))
    if decimal:
        decimal = decimal.rstrip("0")
    return f"{sign}{whole}{'.' + decimal if decimal else ''}"


def plain_text(value: object) -> str | None:
    if not value:
        return None
    text = re.sub(r"<[^>]+>", " ", html.unescape(str(value)))
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def _credit_names(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    names = []
    for item in value:
        name = item.get("name") if isinstance(item, dict) else item
        if name and str(name).strip():
            names.append(str(name).strip())
    return names


def _role_names(credits: object) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    if not isinstance(credits, list):
        return result
    for credit in credits:
        if not isinstance(credit, dict):
            continue
        name = str(credit.get("name") or "").strip()
        roles = str(credit.get("role") or "").casefold()
        if not name:
            continue
        for raw_role in re.split(r"[,;/]+|\band\b", roles):
            field = ROLE_FIELDS.get(" ".join(raw_role.split()))
            if field and name not in result[field]:
                result[field].append(name)
    return result


def _image_metadata(issue: dict) -> dict:
    image = issue.get("image")
    if not isinstance(image, dict):
        return {}
    result = {}
    for source, target in (("original_url", "cover_url"), ("width", "cover_width"), ("height", "cover_height")):
        if image.get(source) not in (None, ""):
            result[target] = image[source]
    return result


def date_parts(issue: dict) -> dict:
    raw = str(issue.get("cover_date") or issue.get("store_date") or "")
    if not raw or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        return {}
    year, month, day = raw.split("-")
    result = {"year": year}
    if month != "00":
        result["month"] = str(int(month))
    if day != "00":
        result["day"] = str(int(day))
    return result


def inferred_format(query: str, path: str) -> tuple[str, str]:
    combined = f"{query} {Path(path).stem}".casefold()
    if "omnibus" in combined:
        return "Omnibus", "name contains Omnibus"
    if "annual" in combined:
        return "Annual", "name contains Annual"
    if "deluxe edition" in combined or re.search(r"(?:^|[\s_-])hc(?:$|[\s_.-])", combined):
        return "Hardcover", "name indicates hardcover/deluxe edition"
    if "collection" in combined:
        return "TPB", "name contains Collection"
    return "Issue", "ordinary numbered issue candidate"


def metadata_candidate(selection: dict, query: str, path: str, issue: dict) -> dict:
    issue_format, format_reason = inferred_format(query, path)
    description = plain_text(issue.get("deck")) or plain_text(issue.get("description"))
    volume = str(selection.get("start_year") or "")
    roles = _role_names(issue.get("person_credits"))
    publisher = selection.get("publisher")
    if isinstance(publisher, dict):
        publisher = publisher.get("name")
    issue_volume = issue.get("volume") if isinstance(issue.get("volume"), dict) else {}
    issue_publisher = issue_volume.get("publisher")
    if isinstance(issue_publisher, dict):
        issue_publisher = issue_publisher.get("name")
    tags = _credit_names(issue.get("tags"))
    genres = _credit_names(issue.get("genres"))
    result = {
        "series": selection.get("name") or "",
        "series_sort": selection.get("name") or "",
        "volume": volume,
        "number": str(issue.get("issue_number") or ""),
        "count": selection.get("count_of_issues"),
        "format": issue_format,
        "format_reason": format_reason,
        "publisher": publisher or issue_publisher,
        "title": issue.get("name"),
        "writer": serialize_multi(roles.get("writer")),
        "penciller": serialize_multi(roles.get("penciller")),
        "inker": serialize_multi(roles.get("inker")),
        "colorist": serialize_multi(roles.get("colorist")),
        "letterer": serialize_multi(roles.get("letterer")),
        "cover_artist": serialize_multi(roles.get("cover_artist")),
        "editor": serialize_multi(roles.get("editor")),
        "genre": serialize_multi(genres),
        "tags": serialize_multi(tags),
        "characters": serialize_multi(_credit_names(issue.get("character_credits"))),
        "teams": serialize_multi(_credit_names(issue.get("team_credits"))),
        "locations": serialize_multi(_credit_names(issue.get("location_credits"))),
        "story_arc": serialize_multi(_credit_names(issue.get("story_arc_credits"))),
        "summary": description,
        "web": issue.get("site_detail_url") or selection.get("comicvine_url") or selection.get("site_detail_url"),
        "notes": f"ComicVine issue {issue.get('id')}; volume {selection.get('candidate_id')}",
        "comicvine_issue_id": issue.get("id"),
        "comicvine_volume_id": selection.get("comicvine_volume_id") or selection.get("candidate_id"),
        "comicvine_url": issue.get("site_detail_url") or selection.get("comicvine_url") or selection.get("site_detail_url"),
    }
    result.update(_image_metadata(issue))
    result.update(date_parts(issue))
    return {key: value for key, value in result.items() if value not in (None, "")}


def match_files(query: str, items: list[dict], issues: list[dict], selection: dict) -> list[dict]:
    by_number: dict[str, list[dict]] = defaultdict(list)
    for issue in issues:
        number = canonical_issue_number(issue.get("issue_number"))
        if number:
            by_number[number].append(issue)

    # Collections/omnibuses are filed as `Title vNN (Year)` with no issue
    # number, but ComicVine models them as issues named "Volume N". Match
    # the vNN tag to that "Volume N" issue when present.
    by_volume_name: dict[str, list[dict]] = defaultdict(list)
    for issue in issues:
        name = str(issue.get("name") or "")
        volume_match = re.search(r"volume\s+([0-9]+(?:\.[0-9]+)?)", name, re.IGNORECASE)
        if volume_match:
            by_volume_name[canonical_issue_number(volume_match.group(1))].append(issue)

    matches = []
    for item in items:
        parsed = canonical_issue_number(item.get("issue_number_from_filename"))
        candidates = by_number.get(parsed, []) if parsed else []
        status = "unmatched"
        issue = None
        if len(candidates) == 1:
            status = "exact-number"
            issue = candidates[0]
        elif len(candidates) > 1:
            status = "ambiguous-number"
        elif not parsed and len(items) == 1 and len(issues) == 1:
            status = "single-file-single-issue"
            issue = issues[0]
        elif not parsed:
            # Collection volume tag fallback: `Title v01 (Year)` -> "Volume 1".
            tag = re.search(r"\bv([0-9]+(?:\.[0-9]+)?)\b", Path(item["path"]).stem, re.IGNORECASE)
            if tag:
                volume = canonical_issue_number(tag.group(1))
                tagged = by_volume_name.get(volume, [])
                if len(tagged) == 1:
                    status = "exact-volume"
                    issue = tagged[0]
                elif len(tagged) > 1:
                    status = "ambiguous-number"

        candidate_issue_ids = [candidate.get("id") for candidate in candidates]
        if issue and not candidate_issue_ids:
            candidate_issue_ids = [issue.get("id")]
        entry = {
            "path": item["path"],
            "archive_format": item["format"],
            "filename_issue_number": item.get("issue_number_from_filename"),
            "status": status,
            "candidate_issue_ids": candidate_issue_ids,
            "existing_issues": item.get("existing_issues"),
        }
        if issue:
            entry["issue"] = dict(issue)
            entry["metadata_candidate"] = metadata_candidate(selection, query, item["path"], issue)
        matches.append(entry)
    return matches
