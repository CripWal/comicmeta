import io
import zipfile
from argparse import Namespace
from contextlib import redirect_stdout

from comicmeta._commands.health import run, scan


def test_health_does_not_call_missing_metadata_healthy(tmp_path):
    archive = tmp_path / "missing.cbz"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("001.jpg", b"page")

    output = io.StringIO()
    with redirect_stdout(output):
        run(Namespace(source=tmp_path, deep=False, no_color=True))

    assert "✗ issues found" in output.getvalue()
    assert "✓ healthy" not in output.getvalue()


def test_health_reports_incomplete_metadata(tmp_path):
    archive = tmp_path / "incomplete.cbz"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("ComicInfo.xml", "<ComicInfo><Series>Only Series</Series></ComicInfo>")

    result = scan(tmp_path)

    assert result["incomplete"] == ["incomplete.cbz: missing volume, number, year, format"]


def test_health_does_not_call_empty_library_healthy(tmp_path):
    output = io.StringIO()
    with redirect_stdout(output):
        run(Namespace(source=tmp_path, deep=False, no_color=True))

    assert "no archives found" in output.getvalue()
    assert "✓ healthy" not in output.getvalue()


def test_health_verified_cbr_is_not_corrupt(tmp_path):
    from unittest import mock
    import contextlib
    archive = tmp_path / "valid.cbr"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("001.jpg", b"page")
    fake_rarfile = mock.Mock()
    fake_rarfile.RarFile = contextlib.nullcontext
    with mock.patch.dict("sys.modules", {"rarfile": fake_rarfile}):
        result = scan(tmp_path)
    assert result["total"] == 1
    assert result["corrupt"] == []
    assert result["unverified"] == []


def test_health_cbr_without_reader_is_unverified_not_corrupt(tmp_path):
    from unittest import mock
    archive = tmp_path / "valid.cbr"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("001.jpg", b"page")
    with mock.patch.dict("sys.modules", {"rarfile": None}):
        result = scan(tmp_path)
    assert result["corrupt"] == []
    assert result["unverified"] == ["valid.cbr"]


def test_health_broken_cbr_with_reader_is_corrupt(tmp_path):
    from unittest import mock
    archive = tmp_path / "broken.cbr"
    archive.write_bytes(b"not a real rar")

    def bad_rar(_path):
        raise Exception("bad archive")

    fake_rarfile = mock.Mock()
    fake_rarfile.RarFile = bad_rar
    with mock.patch.dict("sys.modules", {"rarfile": fake_rarfile}):
        result = scan(tmp_path)
    assert result["corrupt"] == ["broken.cbr"]


def test_health_corrupt_archive_exits_nonzero(tmp_path):
    import pytest
    archive = tmp_path / "broken.cbz"
    archive.write_bytes(b"not a real zip")

    output = io.StringIO()
    with redirect_stdout(output), pytest.raises(SystemExit) as excinfo:
        run(Namespace(source=tmp_path, deep=False, no_color=True))

    assert excinfo.value.code == 1
    assert "✗ issues found" in output.getvalue()


def test_health_clean_library_exits_zero(tmp_path):
    archive = tmp_path / "good.cbz"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("ComicInfo.xml", "<ComicInfo><Series>S</Series><Number>1</Number><Volume>1</Volume><Year>2020</Year><Format>Issue</Format></ComicInfo>")
        handle.writestr("001.jpg", b"page")

    output = io.StringIO()
    with redirect_stdout(output):
        run(Namespace(source=tmp_path, deep=False, no_color=True))

    assert "ALL CLEAR" in output.getvalue()


def test_health_json_reports_scan_result(tmp_path):
    import json as _json
    import pytest
    archive = tmp_path / "broken.cbz"
    archive.write_bytes(b"not a real zip")

    output = io.StringIO()
    with redirect_stdout(output), pytest.raises(SystemExit) as excinfo:
        run(Namespace(source=tmp_path, deep=False, json=True, no_color=True))

    payload = _json.loads(output.getvalue())
    assert payload["source"] == str(tmp_path)
    assert payload["total"] == 1
    assert payload["corrupt"] == ["broken.cbz"]
    assert excinfo.value.code == 1


def test_health_json_clean_exits_zero(tmp_path):
    import json as _json
    import pytest

    output = io.StringIO()
    with redirect_stdout(output), pytest.raises(SystemExit) as excinfo:
        run(Namespace(source=tmp_path, deep=False, json=True, no_color=True))

    payload = _json.loads(output.getvalue())
    assert payload["total"] == 0
    assert excinfo.value.code == 0
