import json
import os
import zipfile
from pathlib import Path

import pytest

from comicmeta import _config
from comicmeta._commands import replacement


def test_toggle_adds_and_removes_request(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "source"
    source.mkdir()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    assert replacement.is_requested("a.cbz", source) is False
    assert replacement.toggle(source, "a.cbz") is True
    assert replacement.is_requested("a.cbz", source) is True
    assert replacement.requested_paths(source) == {"a.cbz"}
    assert replacement.toggle(source, "a.cbz") is False
    assert replacement.is_requested("a.cbz", source) is False


def test_clear_request_removes_entry(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "source"
    source.mkdir()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    replacement.toggle(source, "a.cbz")
    replacement.clear_request(source, "a.cbz")
    assert replacement.requested_paths(source) == set()


def test_rescan_marks_replacement_as_review_required(tmp_path, monkeypatch):
    """rescan (used by `comicmeta review`) forces replacement files through review."""
    from comicmeta._commands.discover import rescan
    source = tmp_path / "source"
    cbz = source / "Series (2020)" / "Series (2020) #001.cbz"
    cbz.parent.mkdir(parents=True)
    with zipfile.ZipFile(cbz, "w") as archive:
        archive.writestr("ComicInfo.xml", """<ComicInfo>
  <Series>Wrong</Series>
  <Volume>2020</Volume>
  <Number>1</Number>
  <Year>2020</Year>
  <Format>Issue</Format>
</ComicInfo>""")
        archive.writestr("001.jpg", b"page")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    replacement.toggle(source, "Series (2020)/Series (2020) #001.cbz")
    report = tmp_path / "candidates.json"

    from unittest import mock
    fake_search = mock.Mock(return_value=[])
    with mock.patch("comicmeta._comicvine.search_volumes_batch", fake_search):
        result = rescan(source, report, api_key="fake-key", limit=1, exclude=set())
    item = next(i for i in result["items"] if i["path"].endswith("#001.cbz"))
    assert item["status"] == "review-required"
    assert item.get("replacement_requested") is True

def test_validate_mapping_allows_replacement(tmp_path):
    from comicmeta._commands.write import validate_mapping
    source = tmp_path / "source"
    target = source / "a.cbz"
    target.parent.mkdir(parents=True)
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr("ComicInfo.xml", "<ComicInfo></ComicInfo>")
        archive.writestr("001.jpg", b"page")
    mapping = {"a.cbz": {"series": "X", "volume": "1", "number": "1", "year": "2020", "format": "Issue"}}
    validated, skipped = validate_mapping(source, mapping)
    assert validated == []  # existing ComicInfo skips by default
    validated, skipped = validate_mapping(source, mapping, replacement_paths={"a.cbz"})
    assert len(validated) == 1  # replacement request lifts the guard


def test_discover_marks_replacement_as_review_required(tmp_path, monkeypatch):
    from comicmeta._commands.discover import discover
    source = tmp_path / "source"
    cbz = source / "Series (2020)" / "Series (2020) #001.cbz"
    cbz.parent.mkdir(parents=True)
    with zipfile.ZipFile(cbz, "w") as archive:
        archive.writestr("ComicInfo.xml", """<ComicInfo>
  <Series>Wrong</Series>
  <Volume>2020</Volume>
  <Number>1</Number>
  <Year>2020</Year>
  <Format>Issue</Format>
</ComicInfo>""")
        archive.writestr("001.jpg", b"page")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    flat = _config.load(source)
    _config.set_key(flat, "paths.candidates", str(tmp_path / "candidates.json"))
    replacement.toggle(source, "Series (2020)/Series (2020) #001.cbz")

    result = discover(
        source,
        tmp_path / "candidates.json",
        api_key="fake-key",
        limit=1,
        exclude=set(),
    )
    item = next(i for i in result["items"] if i["path"].endswith("#001.cbz"))
    assert item["status"] == "review-required"
    assert item.get("replacement_requested") is True
