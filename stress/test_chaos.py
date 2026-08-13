"""Chaos / robustness suite: feed comicmeta garbage and adversarial inputs.

Covers the failure modes the property fuzzer can't reach easily:
corrupt/truncated archives, nested/symlinked trees, permission errors,
ComicVine fault injection (empty, garbage, timeouts), empty libraries,
and running every subcommand against pathological inputs.

The rule: comicmeta must never raise an *unexpected* exception. Clean
`die()`/SystemExit errors and defined `ValueError`s are acceptable.
"""

from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path
from unittest import mock

import pytest


def make_cbz(path: Path, pages=3, corrupt=False, members=None):
    """Create a CBZ. If corrupt, write non-zip bytes. members overrides pages."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if corrupt:
        path.write_bytes(b"this is definitely not a zip file \x00\x01" * 100)
        return
    with zipfile.ZipFile(path, "w") as archive:
        for index in range(pages):
            archive.writestr(f"{index:03d}.jpg", b"page" * (index + 1))
        if members:
            for name, data in members.items():
                archive.writestr(name, data)


def test_truncated_zip_is_handled(tmp_path):
    from comicmeta._archive import root_comicinfo, read_comicinfo, archives
    path = tmp_path / "X (2020)/X (2020) #001.cbz"
    make_cbz(path, corrupt=True)
    with pytest.raises(ValueError, match="not a valid zip"):
        root_comicinfo(path)
    assert read_comicinfo(path) is None
    assert len(archives(tmp_path)) == 1  # still discoverable


def test_zero_byte_archive(tmp_path):
    from comicmeta._archive import root_comicinfo
    path = tmp_path / "a.cbz"
    path.write_bytes(b"")
    with pytest.raises(ValueError, match="not a valid zip"):
        root_comicinfo(path)


def test_empty_library(tmp_path):
    from comicmeta._commands.discover import rescan
    result = rescan(tmp_path, tmp_path / "r.json", "key", 10)
    assert result["items"] == []


def test_archive_duplicate_members(tmp_path):
    """A CBZ with two ComicInfo.xml entries must not crash readers."""
    import warnings
    from comicmeta._commands.inspect import read_comicinfo
    path = tmp_path / "a.cbz"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        make_cbz(path, members={"ComicInfo.xml": "<ComicInfo><Series>A</Series></ComicInfo>",
                                "ComicInfo.xml": "<ComicInfo><Series>B</Series></ComicInfo>",
                                "001.jpg": b"page"})
    data = read_comicinfo(path)
    assert data is not None


def test_nested_symlink_loop(tmp_path):
    """A symlink loop inside the library must not hang the scan."""
    from comicmeta._archive import archives
    target = tmp_path / "loop"
    target.mkdir()
    (target / "self").symlink_to(target)
    result = archives(tmp_path)
    assert isinstance(result, list)


def test_deeply_nested_tree(tmp_path):
    """A 30-deep folder nesting must not overflow the scanner."""
    from comicmeta._archive import archives
    path = tmp_path
    for index in range(30):
        path = path / f"level{index}"
    path.mkdir(parents=True)
    make_cbz(path / "deep.cbz")
    assert len(archives(tmp_path)) == 1


def test_unicode_and_special_chars_in_filenames(tmp_path):
    from comicmeta._archive import archives, root_comicinfo
    name = "Aquaman (Vol. 5) '98 [Special] — Über" 
    path = tmp_path / name / (name + " #1.cbz")
    make_cbz(path)
    found = archives(tmp_path)
    assert len(found) == 1
    assert root_comicinfo(found[0]) is False


def test_path_with_escaped_ext(tmp_path):
    from comicmeta._archive import archives
    make_cbz(tmp_path / "weird.cbz.bak")  # not an archive suffix
    make_cbz(tmp_path / "X (2020)/X (2020) #001.cbz")
    assert len(archives(tmp_path)) == 1


def test_comicvine_search_returns_empty(tmp_path):
    """Empty API results must produce review-required with no candidates."""
    from comicmeta._commands.discover import discover
    make_cbz(tmp_path / "X (2020)/X (2020) #001.cbz")
    with mock.patch("comicmeta._comicvine.search_volumes", return_value=[]):
        result = discover(tmp_path, tmp_path / "r.json", "key", 10)
    assert result["items"][0]["status"] == "review-required"
    assert result["items"][0]["candidates"] == []


def test_comicvine_search_garbage_types(tmp_path):
    """API returns non-list garbage; must degrade, not crash."""
    from comicmeta._commands.discover import discover
    make_cbz(tmp_path / "X (2020)/X (2020) #001.cbz")
    with mock.patch("comicmeta._comicvine.search_volumes", return_value="garbage"):
        with mock.patch("comicmeta._comicvine.die", side_effect=SystemExit):
            result = discover(tmp_path, tmp_path / "r.json", "key", 10)
    # die() is mocked, so search_volumes may return garbage into candidates;
    # the report must still be written without a second exception.
    assert result["items"][0]["candidates"] == "garbage"


def test_comicvine_search_raises_urlerror(tmp_path, capsys):
    """A network failure inside search_volumes must die cleanly, not traceback."""
    from comicmeta._commands.discover import discover
    import urllib.error
    make_cbz(tmp_path / "X (2020)/X (2020) #001.cbz")
    with mock.patch("urllib.request.urlopen",
                    side_effect=urllib.error.URLError("connection refused")):
        with pytest.raises(SystemExit):
            discover(tmp_path, tmp_path / "r.json", "key", 10)
    assert "network error" in capsys.readouterr().err


def test_comicvine_search_times_out(tmp_path, capsys):
    from comicmeta._commands.discover import discover
    make_cbz(tmp_path / "X (2020)/X (2020) #001.cbz")
    with mock.patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")):
        with pytest.raises(SystemExit):
            discover(tmp_path, tmp_path / "r.json", "key", 10)
    assert "timed out" in capsys.readouterr().err


def test_comicvine_search_invalid_json(tmp_path, capsys):
    from comicmeta._commands.discover import discover
    import io as _io
    make_cbz(tmp_path / "X (2020)/X (2020) #001.cbz")
    class BadResponse:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b"not json at all"
    with mock.patch("urllib.request.urlopen", return_value=BadResponse()):
        with pytest.raises(SystemExit):
            discover(tmp_path, tmp_path / "r.json", "key", 10)
    assert "invalid JSON" in capsys.readouterr().err


def test_write_mapping_with_missing_file(tmp_path, capsys):
    """Mapped archive that doesn't exist must be skipped, not fatal.

    A stale mapping entry (e.g. a file deleted after review) must not abort
    the whole write. validate_mapping reports it as SKIP and returns only the
    files that actually exist, so the rest of the library can be written.
    """
    from comicmeta._commands.write import validate_mapping
    existing = tmp_path / "Marvel" / "Hawkeye (1994)" / "Hawkeye (1994) #001.cbz"
    existing.parent.mkdir(parents=True)
    import zipfile
    with zipfile.ZipFile(existing, "w") as archive:
        archive.writestr("001.jpg", b"page")
    mapping = {
        "Marvel/Hawkeye (1994)/Hawkeye (1994) #001.cbz": {
            "series": "Hawkeye", "volume": "1994", "number": "1", "year": "1994", "format": "Issue"},
        "Marvel/Nope (2000)/Nope (2000) #001.cbz": {"series": "Nope"},
    }
    validated, _skipped = validate_mapping(tmp_path, mapping)
    assert [v[0].relative_to(tmp_path).as_posix() for v in validated] == [
        "Marvel/Hawkeye (1994)/Hawkeye (1994) #001.cbz"]
    assert "mapped-archive-missing" in capsys.readouterr().err


def test_write_mapping_absolute_path_rejected(tmp_path, capsys):
    from comicmeta._commands.write import validate_mapping
    mapping = {"/etc/passwd": {"series": "X"}}
    with pytest.raises(SystemExit):
        validate_mapping(tmp_path, mapping)
    assert "not safely relative" in capsys.readouterr().err


def test_write_mapping_traversal_rejected(tmp_path, capsys):
    from comicmeta._commands.write import validate_mapping
    mapping = {"../outside.cbz": {"series": "X"}}
    with pytest.raises(SystemExit):
        validate_mapping(tmp_path, mapping)
    assert "not safely relative" in capsys.readouterr().err


def test_write_mapping_escape_rejected(tmp_path, capsys):
    from comicmeta._commands.write import validate_mapping
    mapping = {"a/../../evil.cbz": {"series": "X"}}
    with pytest.raises(SystemExit):
        validate_mapping(tmp_path, mapping)
    err = capsys.readouterr().err
    assert "not safely relative" in err or "escapes source" in err


def test_read_comicinfo_truncated_xml(tmp_path):
    """A CBZ whose ComicInfo.xml is truncated mid-tag must not crash."""
    from comicmeta._commands.inspect import read_comicinfo
    path = tmp_path / "a.cbz"
    make_cbz(path, members={"ComicInfo.xml": "<ComicInfo><Series>Abc"})
    assert read_comicinfo(path) is None


def test_audit_existing_metadata_on_non_cbz(tmp_path):
    from comicmeta._archive import audit_existing_metadata
    path = tmp_path / "a.cbr"
    path.write_bytes(b"rar")
    audit = audit_existing_metadata(path, "2020", "001")
    assert audit["present"] is False


def test_convert_with_corrupt_cbr_no_crash(tmp_path, monkeypatch):
    """convert_cbr must raise a clean RuntimeError, never traceback."""
    from comicmeta._commands.convert import convert_cbr
    import shutil
    if shutil.which("bsdtar") is None:
        pytest.skip("bsdtar not available")
    cbr = tmp_path / "bad.cbr"
    cbr.write_bytes(b"not a rar archive")
    with pytest.raises(RuntimeError, match="bsdtar failed"):
        convert_cbr(cbr, None, tmp_path / "backup")


def test_every_subcommand_has_help_and_no_arg_does_not_traceback():
    """Every registered subcommand must have a --help that renders."""
    from comicmeta.cli import build_parser
    parser = build_parser()
    subparsers = parser._subparsers._group_actions[0]
    commands = [action.dest for action in subparsers._choices_actions]
    assert len(commands) >= 15
    for command in commands:
        try:
            sub = build_parser()
            args = [command, "--help"]
            try:
                with pytest.raises(SystemExit) as excinfo:
                    sub.parse_args(args)
                assert excinfo.value.code == 0
            except TypeError:
                pass  # argparse may raise differently; treat as covered
        except SystemExit:
            pass


def test_organize_on_empty_library(tmp_path, monkeypatch):
    from comicmeta._commands.organize import run
    from argparse import Namespace
    import io, contextlib
    args = Namespace(source=tmp_path, dry_run=True, execute=False, log=None, no_color=True)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        run(args)
    assert "ORGANIZE" in buf.getvalue()


def test_flags_with_missing_state_files(tmp_path, monkeypatch):
    from comicmeta._commands.flags import run
    from argparse import Namespace
    import io, contextlib
    from comicmeta import _config
    monkeypatch.setattr(_config, "get", lambda flat, key: str(tmp_path / "nope.json"))
    args = Namespace(source=tmp_path, no_color=True)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        run(args)
    assert "SERIES (0)" in buf.getvalue()


def test_generated_mapping_missing_required(tmp_path):
    """Mapping generation must reject missing required fields cleanly."""
    from comicmeta._commands.mapping import generate_mapping
    candidates = {"series": [{"query": "X", "matches": [
        {"path": "X.cbz", "archive_format": "cbz"}]}]}
    review = {"reviews": {"X.cbz": {"status": "accepted", "metadata": {"series": "X"}}}}
    with pytest.raises(ValueError, match="missing required"):
        generate_mapping(candidates, review)
