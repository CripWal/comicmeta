"""Comic archive helpers: scanning, ComicInfo.xml generation, hashing."""

from __future__ import annotations

import hashlib
import json
import os
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from comicmeta._common import COMICINFO_FIELDS, REQUIRED_FIELDS, atomic_write, serialize_multi

ARCHIVE_SUFFIXES = {".cbz", ".cbr", ".cb7", ".cbt"}

_FIELD_ORDER = (
    "series", "series_sort", "localized_series", "number", "count", "volume",
    "year", "month", "day", "format", "title", "publisher", "imprint",
    "writer", "penciller", "inker", "colorist", "letterer", "cover_artist", "editor",
    "genre", "tags", "characters", "teams", "locations", "story_arc", "story_arc_number",
    "summary", "notes", "web", "age_rating",
)
_TAG_NAMES = {
    "series_sort": "SeriesSort", "localized_series": "LocalizedSeries",
    "cover_artist": "CoverArtist", "story_arc": "StoryArc", "story_arc_number": "StoryArcNumber",
    "age_rating": "AgeRating",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def archives(source: Path, exclude: set[str] | None = None) -> list[Path]:
    """Return comic archives under `source`, skipping internal/backup dirs.

    `exclude` is a set of directory names never to treat as library content,
    e.g. `{"comicmeta-backups"}` so backups written inside the library root are
    not scanned as library comics.
    """
    exclude = {name.casefold() for name in (exclude or set())}
    result = []
    for path in source.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in ARCHIVE_SUFFIXES:
            continue
        relative = path.relative_to(source)
        if any(part.casefold() in exclude for part in relative.parts[:-1]):
            continue
        result.append(path)
    return sorted(result)


def root_comicinfo(path: Path) -> bool:
    if path.suffix.lower() != ".cbz":
        return False
    try:
        with zipfile.ZipFile(path) as archive:
            return any(name.lower().lstrip("./") == "comicinfo.xml" for name in archive.namelist())
    except zipfile.BadZipFile:
        raise ValueError(f"archive is not a valid zip: {path}")


class ComicInfoCache:
    """Persistent cache of per-archive ComicInfo presence, keyed by size+mtime.

    Checking ComicInfo.xml requires opening each CBZ's central directory, which
    is slow on mounted/network volumes. Re-using the cache across runs makes
    `inspect` and `browse` listings fast. Entries are invalidated when a file's
    size or mtime changes.
    """

    _CACHE_VERSION = 1

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "comicmeta" / "comicinfo.json"
        self._entries: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if payload.get("version") != self._CACHE_VERSION:
            return
        self._entries = payload.get("entries", {})

    def _save(self) -> None:
        try:
            atomic_write(self._path, json.dumps(
                {"version": self._CACHE_VERSION, "entries": self._entries}, indent=2))
        except OSError:
            pass

    def get(self, path: Path) -> bool | None:
        """Return cached presence, or None if not cached/stale."""
        try:
            stat = path.stat()
            key = str(path)
            entry = self._entries.get(key)
            if entry and entry.get("size") == stat.st_size and entry.get("mtime") == stat.st_mtime_ns:
                return entry.get("present")
        except OSError:
            return None
        return None

    def set(self, path: Path, present: bool) -> None:
        try:
            stat = path.stat()
        except OSError:
            return
        self._entries[str(path)] = {
            "size": stat.st_size,
            "mtime": stat.st_mtime_ns,
            "present": present,
        }
        self._save()


def cached_root_comicinfo(path: Path, cache: ComicInfoCache | None = None) -> bool:
    """root_comicinfo with a persistent presence cache. Raises on bad zip."""
    if path.suffix.lower() != ".cbz":
        return False
    cache = cache or ComicInfoCache()
    cached = cache.get(path)
    if cached is not None:
        return cached
    present = root_comicinfo(path)
    cache.set(path, present)
    return present


def read_comicinfo(path: Path) -> dict | None:
    """Return the root ComicInfo fields of a CBZ as a casefolded dict, or None."""
    if path.suffix.lower() != ".cbz":
        return None
    try:
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                if name.lower().lstrip("./") == "comicinfo.xml":
                    root = ElementTree.fromstring(archive.read(name))
                    return {child.tag.casefold(): (child.text or "").strip() for child in root}
    except (zipfile.BadZipFile, KeyError, OSError, ElementTree.ParseError):
        return None
    return None


def audit_existing_metadata(path: Path, folder_year: str | None, filename_number: str | None) -> dict:
    """Audit a file's existing ComicInfo for completeness and consistency.

    Returns ``{"present", "complete", "issues"}`` where ``issues`` lists
    human-readable problems (missing required fields, volume/folder-year
    conflicts, number/filename conflicts). ``complete`` is True only when no
    issues were found. Files with complete, consistent metadata may be left
    alone; anything else should flow back through review.
    """
    fields = read_comicinfo(path) or {}
    if not fields:
        return {"present": False, "complete": False, "issues": ["no ComicInfo.xml"]}
    issues = []
    for field in REQUIRED_FIELDS:
        if not str(fields.get(field, "")).strip():
            issues.append(f"missing {field}")
    volume = str(fields.get("volume", "")).strip()
    if folder_year and volume and volume != folder_year:
        issues.append(f"volume {volume} != folder year {folder_year}")
    number = str(fields.get("number", "")).strip()
    if filename_number and number:
        def _as_int(value: str) -> int | None:
            try:
                return int(value.lstrip("0") or "0")
            except ValueError:
                return None
        if _as_int(number) is not None and _as_int(filename_number) is not None \
                and _as_int(number) != _as_int(filename_number):
            issues.append(f"number {number} != filename #{filename_number}")
    return {"present": True, "complete": not issues, "issues": issues}


def comicinfo_xml(metadata: dict) -> bytes:
    missing = [field for field in REQUIRED_FIELDS if not str(metadata.get(field, "")).strip()]
    if missing:
        raise ValueError(f"missing required reviewed fields: {', '.join(missing)}")
    root = ElementTree.Element("ComicInfo", {
        "xmlns:xsd": "http://www.w3.org/2001/XMLSchema",
        "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
    })
    for field in _FIELD_ORDER:
        value = metadata.get(field)
        if value is not None and str(value) != "":
            child = ElementTree.SubElement(root, _TAG_NAMES.get(field, field.title()))
            child.text = serialize_multi(value)
    return ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)
