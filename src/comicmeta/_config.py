"""Settings loading and resolution for comicmeta.

Settings live in a TOML file (`comicmeta.toml`) searched in the library
directory, then the user config directory (`~/.config/comicmeta`). Resolution
precedence is: CLI flags > environment variables > settings file > built-in
defaults. All keys are dotted names like `api.request_delay`.
"""

from __future__ import annotations

import os
import sys
import tomllib
from pathlib import Path

from comicmeta._common import die

SETTINGS_FILENAME = "comicmeta.toml"

DEFAULTS: dict = {
    "paths": {
        "source": ".",
        "candidates": "comicvine-candidates.json",
        "volume_state": "comicvine-review-state.json",
        "volume_summary": "comicvine-review.md",
        "policy": "comic-metadata-review-policy.json",
        "issue_candidates": "comicvine-issue-candidates.json",
        "issue_state": "comicvine-issue-review-state.json",
        "issue_summary": "comicvine-issue-review.md",
        "cover_state": "comicmeta-cover-preferences.json",
        "mapping": "comic-metadata-reviewed-mapping.json",
        "kavita_export": "comicmeta-kavita-export.json",
        "replacement_state": "comicmeta-replacement-requests.json",
        "backup_dir": "comicmeta-backups/latest",
        "write_report": "comicmeta-write-report.json",
    },
    "api": {
        "key_env": "COMICVINE_API_KEY",
        "key_file": "",
        "keychain": False,
        "request_delay": 0.25,
        "timeout": 30,
        "user_agent": "comicmeta",
        "candidate_limit": 10,
        "concurrency": 5,
    },
    "review": {
        "active_source": "",
        "blocked_queries": {},
        "high_confidence_score": 90,
        "high_confidence_margin": 15,
        "continue_to_write": True,
    },
    "write": {
        "enforce_expected_hashes": False,
        "auto_confirm": False,
        "keep_backups": True,
        "backup_retention": 0,
        "keep_backup_after_verify": False,
        "backup_configured": False,
    },
    "appearance": {
        "color": True,
        "dashboard": True,
        "check_for_updates": False,
        "theme": "classic",
        "cover_previews": True,
        "cover_previews_configured": False,
    },
}

FLAT_DEFAULTS = {
    f"{section}.{key}": value
    for section, values in DEFAULTS.items()
    for key, value in values.items()
}

# Display metadata for the interactive settings menu: friendly label, kind,
# and secret flag. Keys absent from this table are still shown with a
# humanized key name and string-kind editing.
SETTINGS_META = {
    "paths.source": ("Library root", "path"),
    "paths.candidates": ("Candidate report", "path"),
    "paths.volume_state": ("Volume review state", "path"),
    "paths.volume_summary": ("Volume review summary", "path"),
    "paths.policy": ("Review policy file", "path"),
    "paths.issue_candidates": ("Issue candidates report", "path"),
    "paths.issue_state": ("Issue review state", "path"),
    "paths.issue_summary": ("Issue review summary", "path"),
    "paths.cover_state": ("Cover preferences", "path"),
    "paths.mapping": ("Writer mapping file", "path"),
    "paths.kavita_export": ("Kavita sync export", "path"),
    "paths.replacement_state": ("Replacement request state", "path"),
    "paths.backup_dir": ("Write backup directory", "path"),
    "paths.write_report": ("Write report file", "path"),
    "api.key_env": ("API key environment variable", "str"),
    "api.key_file": ("API key file", "secret-path"),
    "api.keychain": ("Read API key from macOS Keychain", "bool"),
    "api.request_delay": ("Seconds between API calls", "float"),
    "api.timeout": ("API request timeout", "int"),
    "api.user_agent": ("API user agent", "str"),
    "api.candidate_limit": ("Candidates per query", "int"),
    "api.concurrency": ("Parallel API requests", "int"),
    "review.active_source": ("Active library root", "path"),
    "review.blocked_queries": ("Blocked queries", "dict"),
    "review.high_confidence_score": ("High-confidence score", "int"),
    "review.high_confidence_margin": ("High-confidence margin", "int"),
    "review.continue_to_write": ("Continue to write after review", "bool"),
    "write.enforce_expected_hashes": ("Enforce expected hashes", "bool"),
    "write.auto_confirm": ("Auto-confirm write", "bool"),
    "write.keep_backups": ("Keep write backups", "bool"),
    "write.backup_retention": ("Backup retention (days)", "int"),
    "write.keep_backup_after_verify": ("Purge backups after verified write", "bool"),
    "write.backup_configured": ("Backup location configured", "bool"),
    "appearance.color": ("Enable colors", "bool"),
    "appearance.dashboard": ("Interactive dashboard", "bool"),
    "appearance.check_for_updates": ("Check for updates", "bool"),
    "appearance.theme": ("Color theme", "str"),
    "appearance.cover_previews": ("Cover previews", "bool"),
    "appearance.cover_previews_configured": ("Cover previews configured", "bool"),
}

# One-line description per setting, shown in `comicmeta settings` output and
# in the interactive panel's help line.
SETTINGS_DESCRIPTIONS = {
    "paths.source": "Library root — the comic directory comicmeta scans.",
    "paths.candidates": "Discover output: ComicVine volume candidates.",
    "paths.volume_state": "Resumable volume review state (which volumes you chose).",
    "paths.volume_summary": "Volume review summary written as Markdown.",
    "paths.policy": "Review policy file (active source + blocked queries).",
    "paths.issue_candidates": "Issue-level candidates fetched for selected volumes.",
    "paths.issue_state": "Resumable issue review state (approved metadata fields).",
    "paths.issue_summary": "Issue review summary written as Markdown.",
    "paths.cover_state": "Selected named cover artwork per archive; CBZ files remain untouched.",
    "paths.mapping": "Reviewed writer mapping — the input to `write`.",
    "paths.kavita_export": "Reviewed ComicVine export reserved for a future Kavita API sync.",
    "paths.replacement_state": "Archives marked in browse for ComicInfo replacement on the next review+write.",
    "paths.backup_dir": "Where `write` stores per-file backups before rewriting.",
    "paths.write_report": "`write` output report (per-file success/failure).",
    "api.key_env": "Environment variable that holds the ComicVine API key.",
    "api.key_file": "File containing the API key (used when the env var is unset).",
    "api.keychain": "Read the API key from the macOS Keychain (between env and key_file).",
    "api.request_delay": "Seconds to wait between ComicVine API calls (rate limiting).",
    "api.timeout": "ComicVine API request timeout, in seconds.",
    "api.user_agent": "User-Agent header sent to the ComicVine API.",
    "api.candidate_limit": "Max candidates returned per volume search query.",
    "api.concurrency": "Parallel API requests during batch fetching.",
    "review.active_source": "Library root used to resolve relative paths during review.",
    "review.blocked_queries": "Queries excluded from review: folder name → reason.",
    "review.high_confidence_score": "Score at/above which a candidate auto-accepts.",
    "review.high_confidence_margin": "Required score gap for auto-acceptance.",
    "review.continue_to_write": "Ask to continue to `write` after review finishes.",
    "write.enforce_expected_hashes": "Require a staging audit (expected hashes) before writing.",
    "write.auto_confirm": "Skip the `write` confirmation prompt.",
    "write.keep_backups": "Keep per-file backups before rewriting. When off, `write` touches archives with no safety copy.",
    "write.backup_retention": "Keep backups for this many days, then auto-delete older ones. 0 keeps them forever.",
    "write.keep_backup_after_verify": "Auto-purge a library's backups after a fully validated write completes.",
    "write.backup_configured": "Internal marker that first-run backup setup has been completed.",
    "appearance.color": "Enable ANSI colors in terminal output.",
    "appearance.dashboard": "Show the interactive dashboard when run with no command.",
    "appearance.check_for_updates": "Check PyPI for a newer version on startup.",
    "appearance.theme": "Palette name: classic, marvel, dc, noir, technicolor, beige, or bookshelf.",
    "appearance.cover_previews": "Render comic cover images in browse, review, and series galleries.",
    "appearance.cover_previews_configured": "Internal first-run marker for the cover preview choice.",
}

# Keys hidden behind the `[a]` advanced toggle in the settings panel.
# These are internal state-file locations and tuning knobs most users never set.
ADVANCED_KEYS = {
    "paths.candidates", "paths.volume_state", "paths.volume_summary",
    "paths.policy", "paths.issue_candidates", "paths.issue_state",
    "paths.issue_summary", "paths.mapping", "paths.kavita_export", "paths.backup_dir",
    "paths.replacement_state",
    "paths.write_report",
    "appearance.cover_previews_configured",
    "write.backup_configured",
}

# Order sections for display in the interactive menu.
SECTION_ORDER = ["api", "paths", "review", "write", "appearance"]
SECTION_TITLES = {
    "api": "API",
    "paths": "PATHS",
    "review": "REVIEW",
    "write": "WRITE",
    "appearance": "APPEARANCE",
}


def user_settings_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "comicmeta" / SETTINGS_FILENAME


def state_dir(source: Path | None = None) -> Path:
    """Per-library state directory under the user config dir.

    All state files (candidates, review state, mapping, reports, backups) live
    here, keyed by the resolved library path, so the library folder itself stays
    clean. Uses a stable hash of the absolute source path.
    """
    import hashlib
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    root = Path(base) / "comicmeta"
    if source is None:
        return root / "libraries" / "default"
    resolved = source if source.is_absolute() else source.resolve()
    digest = hashlib.sha256(str(resolved).encode()).hexdigest()[:12]
    return root / "libraries" / digest


# State-file path keys that resolve under the per-library state dir.
# `paths.source` and `paths.policy` stay as the user configured them.
_STATE_KEYS = {
    "paths.candidates", "paths.volume_state", "paths.volume_summary",
    "paths.issue_candidates", "paths.issue_state", "paths.issue_summary",
    "paths.cover_state", "paths.mapping", "paths.kavita_export", "paths.backup_dir",
    "paths.replacement_state", "paths.write_report",
}


def find_settings(source: Path | None = None) -> Path | None:
    """Return the first existing settings file: library dir, then cwd, then user config."""
    candidates = []
    if source is not None:
        candidates.append((source if source.is_dir() else source.parent) / SETTINGS_FILENAME)
    candidates.append(Path.cwd() / SETTINGS_FILENAME)
    candidates.append(user_settings_path())
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def detect_source() -> Path | None:
    """Walk up from CWD to find a library: a comicmeta.toml or DC/ + Marvel/ pair.

    Returns the nearest ancestor that looks like a comic library, or None.
    """
    current = Path.cwd()
    for directory in (current, *current.parents):
        if (directory / SETTINGS_FILENAME).is_file():
            return directory
        if (directory / "DC").is_dir() and (directory / "Marvel").is_dir():
            return directory
    return None


def load_file(path: Path) -> dict:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except tomllib.TOMLDecodeError as error:
        die(f"invalid settings {path}: {error}")


def load(source: Path | None = None, path: Path | None = None) -> dict:
    """Load settings as a flat dotted-key dict with defaults applied.

    State-file paths resolve under the per-library state dir
    (`~/.config/comicmeta/libraries/<hash>/`) so the library folder stays clean,
    unless a user overrides them with an absolute path.
    """
    flat = dict(FLAT_DEFAULTS)
    settings_path = path or find_settings(source)
    if settings_path is not None:
        raw = load_file(settings_path)
        for section, values in raw.items():
            if not isinstance(values, dict):
                continue
            for key, value in values.items():
                flat[f"{section}.{key}"] = value
    user_path = user_settings_path()
    if user_path.is_file() and user_path != settings_path:
        global_raw = load_file(user_path)
        for key, value in global_raw.get("appearance", {}).items():
            flat[f"appearance.{key}"] = value
    # Auto-detect the library when no explicit source and no user-configured
    # source (i.e. still the bare '.' default).
    if source is None and str(flat.get("paths.source", "")).strip() in ("", "."):
        detected = detect_source()
        if detected is not None:
            flat["paths.source"] = str(detected)

    # Resolve state files into the per-library state dir when still relative.
    if source is not None or flat.get("paths.source"):
        effective = source if source is not None else Path(flat.get("paths.source"))
        state = state_dir(effective)
        for key in _STATE_KEYS:
            value = flat.get(key)
            if isinstance(value, str) and value and not Path(value).is_absolute():
                flat[key] = str(state / value)
    return flat


def get(flat: dict, key: str):
    return flat.get(key, FLAT_DEFAULTS.get(key))


def scan_excludes(flat: dict) -> set[str]:
    """Directory names under the library root to skip when scanning comics."""
    excludes: set[str] = set()
    backup = get(flat, "paths.backup_dir")
    if backup:
        path = Path(str(backup))
        # Only exclude when the backup lives inside the library root (relative).
        if not path.is_absolute():
            top = path.parts[0]
            if top:
                excludes.add(top)
    return excludes


def set_key(flat: dict, key: str, value: str) -> None:
    """Parse and assign a dotted key value, validating against defaults."""
    if key not in FLAT_DEFAULTS:
        die(
            f"unknown setting: {key}; valid keys:\n  " +
            "\n  ".join(sorted(FLAT_DEFAULTS))
        )
    expected = FLAT_DEFAULTS[key]
    if isinstance(expected, bool):
        parsed = value.casefold() in {"true", "1", "yes", "on"}
    elif isinstance(expected, (int, float)):
        try:
            parsed = type(expected)(value)
        except ValueError:
            die(f"setting {key} expects a number, got: {value}")
    elif isinstance(expected, dict):
        try:
            import json as _json
            parsed = _json.loads(value)
        except _json.JSONDecodeError:
            die(f"setting {key} expects a JSON object, got: {value}")
        if not isinstance(parsed, dict):
            die(f"setting {key} expects a JSON object, got: {value}")
    else:
        parsed = value
    flat[key] = parsed


def render(flat: dict) -> str:
    """Render resolved settings grouped by section, with a description comment."""
    lines = ["# resolved comicmeta settings"]
    for section in DEFAULTS:
        lines.append(f"\n[{section}]")
        for key in DEFAULTS[section]:
            full = f"{section}.{key}"
            description = SETTINGS_DESCRIPTIONS.get(full)
            if description:
                lines.append(f"# {description}")
            value = flat[f"{section}.{key}"]
            lines.append(f"{key} = {value!r}")
    return "\n".join(lines)
