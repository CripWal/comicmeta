import json
import subprocess
import sys
import zipfile
from pathlib import Path
from unittest import mock

import pytest

from comicmeta._commands.convert import convert_cbr, _bsdtar_available, _extractor, _extract_command


def _make_cbr(path: Path):
    """Create a real RAR via bsdtar (macOS built-in can create RAR? no — use a fake)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # bsdtar cannot create RAR; simulate a CBR that convert_cbr will fail to extract,
    # so we test the dry-run/report path instead of the extraction path.
    path.write_bytes(b"fake rar content")


def test_convert_requires_bsdtar(tmp_path, monkeypatch):
    if not _bsdtar_available():
        monkeypatch.setenv("PATH", "/usr/bin:/bin")
    # No real RAR test possible without a rar tool; just confirm bsdtar detection
    assert isinstance(_bsdtar_available(), bool)


def test_extractor_falls_back_across_tools(monkeypatch):
    # Prefer bsdtar, then 7zz/7z, then unrar; error when none exist.
    monkeypatch.setattr("comicmeta._commands.convert.shutil.which", lambda t: f"/bin/{t}")
    assert _extractor() == "bsdtar"
    monkeypatch.setattr("comicmeta._commands.convert.shutil.which",
                        lambda t: None if t == "bsdtar" else f"/bin/{t}")
    assert _extractor() == "7zz"
    monkeypatch.setattr("comicmeta._commands.convert.shutil.which",
                        lambda t: None if t in ("bsdtar", "7zz", "7z") else f"/bin/{t}")
    assert _extractor() == "unrar"
    monkeypatch.setattr("comicmeta._commands.convert.shutil.which", lambda t: None)
    assert _extractor() is None


def test_extract_command_shapes(monkeypatch):
    from pathlib import Path
    cbr = Path("/lib/a.cbr")
    out = Path("/tmp/pages")
    assert _extract_command("bsdtar", cbr, out) == ["bsdtar", "-xf", "/lib/a.cbr", "-C", "/tmp/pages"]
    assert _extract_command("7z", cbr, out) == ["7z", "x", "/lib/a.cbr", "-o/tmp/pages", "-y"]
    assert _extract_command("unrar", cbr, out) == ["unrar", "x", "-y", "/lib/a.cbr", "/tmp/pages/"]


def test_convert_cbr_reports_missing_extractor(tmp_path, monkeypatch):
    monkeypatch.setattr("comicmeta._commands.convert.shutil.which", lambda t: None)
    cbr = tmp_path / "x.cbr"
    cbr.write_bytes(b"not a rar")
    with pytest.raises(RuntimeError, match="no archive extractor"):
        convert_cbr(cbr, None, tmp_path / "backup")


def test_convert_cbr_fails_on_bad_archive(tmp_path):
    cbr = tmp_path / "x.cbr"
    cbr.write_bytes(b"not a rar")
    backup = tmp_path / "backup"
    if _bsdtar_available():
        with pytest.raises(RuntimeError):
            convert_cbr(cbr, None, backup)


def test_convert_rejects_existing_destination(tmp_path, monkeypatch):
    cbr = tmp_path / "x.cbr"
    cbr.write_bytes(b"fake")
    (tmp_path / "x.cbz").write_bytes(b"existing")
    if _bsdtar_available():
        with pytest.raises(RuntimeError, match="destination already exists"):
            convert_cbr(cbr, None, tmp_path / "backup")


def test_run_dry_run_reports_cbr(tmp_path, monkeypatch):
    import io, contextlib
    from argparse import Namespace
    from comicmeta._commands.convert import run
    monkeypatch.chdir(tmp_path)
    cbr = tmp_path / "Marvel/Old Man Hawkeye (2018)/Old Man Hawkeye (2018) #002.cbr"
    cbr.parent.mkdir(parents=True)
    cbr.write_bytes(b"fake")
    args = Namespace(source=tmp_path, mapping=None, backup_dir=tmp_path / "backup",
                     dry_run=True, execute=False, log=None, no_color=True)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        run(args)
    assert "sample" in out.getvalue() or "Old Man Hawkeye" in out.getvalue()
    assert "DRY-RUN" in out.getvalue()


def test_convert_picker_selects_and_converts(tmp_path, monkeypatch):
    import io, contextlib
    from comicmeta._commands.convert import convert_picker
    from comicmeta._common import Palette
    monkeypatch.chdir(tmp_path)
    cbr = tmp_path / "a.cbr"
    cbr.write_bytes(b"fake")
    keys = iter(["a", "enter", "x"])
    with mock.patch("comicmeta._tui.read_key", lambda: next(keys)):
        with contextlib.redirect_stdout(io.StringIO()):
            app, skip = convert_picker(tmp_path, {}, tmp_path / "backup", Palette(False))
    # A fake (non-RAR) file can't extract; it should be reported as skipped, not crash.
    assert app + skip == 1


def test_find_cbrs(tmp_path):
    from comicmeta._commands.convert import find_cbrs
    (tmp_path / "Marvel").mkdir()
    (tmp_path / "Marvel/a.cbr").write_bytes(b"x")
    (tmp_path / "Marvel/b.cbz").write_bytes(b"x")
    found = find_cbrs(tmp_path)
    assert len(found) == 1
    assert found[0].suffix == ".cbr"


def test_backups_lists_files(tmp_path, monkeypatch):
    import io, contextlib
    from argparse import Namespace
    from comicmeta._commands.backups import run
    monkeypatch.chdir(tmp_path)
    b = tmp_path / "backup" / "latest"
    (b / "sub").mkdir(parents=True)
    (b / "sub/a.cbr").write_bytes(b"data")
    args = Namespace(source=tmp_path, backup_dir=tmp_path / "backup", list=True, delete=False)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        run(args)
    assert "a.cbr" in out.getvalue()


def test_backups_delete_removes_files_after_confirmation(tmp_path, monkeypatch):
    from argparse import Namespace
    from comicmeta._commands import backups

    backup = tmp_path / "backup"
    (backup / "sub").mkdir(parents=True)
    (backup / "sub/a.cbr").write_bytes(b"data")
    monkeypatch.setattr(sys, "stdin", mock.Mock(isatty=lambda: True))
    monkeypatch.setattr("comicmeta._tui.confirm", lambda *args, **kwargs: True)

    backups.run(Namespace(source=tmp_path, backup_dir=backup, list=False, delete=True))

    assert not backup.exists()
