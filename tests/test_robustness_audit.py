import json

import pytest
from unittest import mock

from comicmeta import _common, _context, _tui


def test_atomic_write_creates_parent_dirs_and_parses(tmp_path):
    path = tmp_path / "nested" / "deeper" / "state.json"
    _common.atomic_write(path, json.dumps({"items": [{"ok": True}]}))
    assert json.loads(path.read_text(encoding="utf-8"))["items"][0]["ok"] is True


def test_atomic_write_replaces_existing_content(tmp_path):
    path = tmp_path / "state.json"
    _common.atomic_write(path, "one")
    _common.atomic_write(path, "two")
    assert path.read_text(encoding="utf-8") == "two"


def test_atomic_json_keeps_updated_at_and_parses(tmp_path):
    path = tmp_path / "state.json"
    _common.atomic_json(path, {"selections": {}})
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert "updated_at" in saved
    assert saved["selections"] == {}


def test_atomic_write_falls_back_on_transient_rename_error(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    original_replace = _common.os.replace
    calls = []

    def flaky_replace(source, destination):
        calls.append(destination)
        if len(calls) == 1:
            raise OSError(22, "simulated SMB EINVAL on large-file rename")
        return original_replace(source, destination)

    monkeypatch.setattr(_common.os, "replace", flaky_replace)
    _common.atomic_write(path, "payload")
    assert path.read_text(encoding="utf-8") == "payload"
    assert len(calls) == 1


def test_context_save_and_active_marker_are_atomic(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    ctx = _context.Context(
        name="nas", host="10.0.0.1", ssh_user="pi", library_path="/comics"
    )
    _context.save_context(ctx)
    path = _context._context_path("nas")
    assert "host = '10.0.0.1'" in path.read_text(encoding="utf-8")
    _context.set_active_context("nas")
    assert _context._active_path().read_text(encoding="utf-8").strip() == "nas"


def test_confirm_returns_default_when_no_input():
    _tui.set_no_input(True)
    try:
        with mock.patch("comicmeta._tui.read_key", side_effect=AssertionError("must not read")):
            assert _tui.confirm("Proceed?", default=False) is False
            assert _tui.confirm("Proceed?", default=True) is True
            assert _tui.prompt_edit("k: ", current="old") is None
            assert _tui.prompt_hidden("secret: ") is None
    finally:
        _tui.set_no_input(False)


def test_confirm_still_interactive_without_no_input(capsys):
    _tui.set_no_input(False)
    try:
        with mock.patch("comicmeta._tui.read_key", return_value="y"):
            assert _tui.confirm("Do it?", default=False) is True
    finally:
        _tui.set_no_input(False)
