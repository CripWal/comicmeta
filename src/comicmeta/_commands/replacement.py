"""comicmeta replacement — archives marked in browse for ComicInfo replacement.

Browse can tag any archive whose existing ComicInfo (e.g. written by a download
tool) is wrong. The tag persists in a replacement-request state file; `discover`
forces those files through review, and `write` replaces their ComicInfo instead
of skipping them (the normal `already-has-comicinfo` guard is lifted). Requests
are cleared automatically after a successful write.
"""

from __future__ import annotations

from pathlib import Path

from comicmeta import _config
from comicmeta._common import atomic_json, load_json

STATE_VERSION = 1


def _state_path(source: Path | None = None) -> Path:
    flat = _config.load(source)
    return Path(_config.get(flat, "paths.replacement_state"))


def load_requests(source: Path | None = None) -> dict:
    """Return {relative_path: request} from the replacement state file."""
    path = _state_path(source)
    if not path.is_file():
        return {}
    state = load_json(path, "replacement state")
    return state.get("requests", {}) if isinstance(state, dict) else {}


def requested_paths(source: Path | None = None) -> set[str]:
    """Return the set of relative paths marked for replacement."""
    return set(load_requests(source))


def is_requested(relative: str, source: Path | None = None) -> bool:
    return relative in requested_paths(source)


def toggle(source: Path, relative: str) -> bool:
    """Toggle the replacement request for one relative path; return the new state."""
    path = _state_path(source)
    state = load_json(path, "replacement state") if path.is_file() else {"version": STATE_VERSION, "requests": {}}
    if not isinstance(state, dict):
        state = {"version": STATE_VERSION, "requests": {}}
    requests = state.setdefault("requests", {})
    if relative in requests:
        del requests[relative]
        requested = False
    else:
        requests[relative] = {"status": "replacement-requested", "note": "tagged in browse"}
        requested = True
    atomic_json(path, state)
    return requested


def clear_request(source: Path, relative: str) -> None:
    """Remove a replacement request after its metadata has been written."""
    path = _state_path(source)
    if not path.is_file():
        return
    state = load_json(path, "replacement state")
    requests = state.get("requests", {}) if isinstance(state, dict) else {}
    if relative in requests:
        del requests[relative]
        atomic_json(path, state)
