import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from comicmeta import _config

SRC = Path(__file__).resolve().parents[1] / "src"


def run_cli(*args, cwd=None):
    env = {**os.environ.copy(), "PYTHONPATH": str(SRC)}
    # Isolate from the user's real config (its active context may be a NAS
    # context, which would route subprocess commands through the executor).
    env["XDG_CONFIG_HOME"] = tempfile.mkdtemp(prefix="comicmeta-test-")
    return subprocess.run(
        [sys.executable, "-m", "comicmeta", *map(str, args)],
        capture_output=True, text=True, env=env, cwd=cwd,
    )


def test_defaults():
    # Explicit source avoids auto-detection, keeping the bare '.' default.
    flat = _config.load(source=Path("."))
    assert flat["paths.source"] == "."
    assert flat["api.request_delay"] == 0.25
    assert flat["write.keep_backups"] is True
    assert flat["write.backup_retention"] == 0
    assert flat["write.keep_backup_after_verify"] is False
    assert flat["write.backup_configured"] is False
    assert flat["review.high_confidence_score"] == 90
    assert flat["write.auto_confirm"] is False


def test_load_merges_file_over_defaults(tmp_path, monkeypatch):
    settings = tmp_path / "comicmeta.toml"
    settings.write_text('[api]\nrequest_delay = 0.7\n[write]\nauto_confirm = true\n')
    monkeypatch.chdir(tmp_path)
    flat = _config.load()
    assert flat["api.request_delay"] == 0.7
    assert flat["write.auto_confirm"] is True
    # Auto-detection finds the library dir that owns the settings file.
    assert flat["paths.source"] == str(tmp_path)


def test_settings_init_and_roundtrip(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = run_cli("settings", "--init")
    assert result.returncode == 0
    assert (tmp_path / "comicmeta.toml").exists()
    flat = _config.load()
    assert flat["api.request_delay"] == 0.25


def test_settings_set_and_persist(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    run_cli("settings", "--init")
    result = run_cli("settings", "--set", "api.request_delay=0.5")
    assert result.returncode == 0
    flat = _config.load()
    assert flat["api.request_delay"] == 0.5


def test_settings_set_rejects_unknown(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = run_cli("settings", "--set", "api.bogus=1")
    assert result.returncode == 1
    assert "unknown setting" in result.stderr


def test_settings_show_lists_sections(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = run_cli("settings")
    assert result.returncode == 0
    for section in ("[paths]", "[api]", "[review]", "[write]"):
        assert section in result.stdout


def test_settings_show_resolves_library_file(tmp_path, monkeypatch):
    settings = tmp_path / "comicmeta.toml"
    settings.write_text("[review]\nhigh_confidence_score = 80\n")
    monkeypatch.chdir(tmp_path)
    result = run_cli("settings")
    assert result.returncode == 0
    assert "high_confidence_score = 80" in result.stdout
    assert "comicmeta.toml" in result.stdout


def test_build_rows_groups_by_section(tmp_path, monkeypatch):
    from comicmeta.cli import _build_rows
    from comicmeta._commands.settings import load_flat
    monkeypatch.chdir(tmp_path)
    rows = _build_rows(load_flat())
    headers = [r["title"] for r in rows if r["type"] == "header"]
    assert headers == ["APPEARANCE", "CONNECTIONS", "STORAGE", "ADVANCED"]
    settings = [r["key"] for r in rows if r["type"] == "setting"]
    assert "appearance.theme" in settings
    assert not any(key.startswith(("api.", "write.")) for key in settings)
    assert any(r["type"] == "advanced-toggle" for r in rows)


def test_build_rows_offers_add_context_when_none(tmp_path, monkeypatch):
    """With no NAS contexts, the settings panel still offers an add action."""
    from comicmeta.cli import _build_rows
    from comicmeta._commands.settings import load_flat
    monkeypatch.chdir(tmp_path)
    rows = _build_rows(load_flat(), expanded_contexts={"nas"})
    adds = [r for r in rows if r["type"] == "context-add"]
    assert len(adds) == 1


def test_build_rows_offers_backup_storage_actions(tmp_path, monkeypatch):
    """The STORAGE section offers an editable backup location and a purge action."""
    from comicmeta.cli import _build_rows
    from comicmeta._commands.settings import load_flat
    monkeypatch.chdir(tmp_path)
    rows = _build_rows(load_flat())
    assert any(r["type"] == "setting" and r["key"] == "paths.backup_dir" for r in rows)
    assert any(r["type"] == "action" and r["key"] == "storage.purge" for r in rows)


def test_settings_panel_fits_narrow_terminal(tmp_path, monkeypatch):
    """The settings panel must never draw lines wider than the terminal."""
    import io
    import contextlib
    import shutil
    from types import SimpleNamespace
    from comicmeta import _common
    from comicmeta.cli import _render_settings_menu, _build_rows
    from comicmeta._commands.settings import load_flat
    monkeypatch.chdir(tmp_path)

    def strip_ansi(text):
        import re
        return re.sub(r"\x1b\[[0-9;]*m", "", text)

    for cols in (40, 50, 60, 80, 100, 120):
        fake = SimpleNamespace(columns=cols, lines=24)
        original = shutil.get_terminal_size
        shutil.get_terminal_size = lambda f: fake
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                _render_settings_menu(_common.Palette(False), _build_rows(load_flat(), show_advanced=True), 0, None)
        finally:
            shutil.get_terminal_size = original
        for line in buf.getvalue().split("\n"):
            assert len(strip_ansi(line)) <= cols, f"overflow at {cols} cols: {line!r}"


def test_settings_panel_width_stable_while_scrolling(tmp_path, monkeypatch):
    """The panel width must not change as the selection scrolls through rows.

    Regression: the width was computed from the *visible* window, so rows with
    long values (e.g. absolute state paths) resized the panel every frame.
    """
    import io
    import contextlib
    import shutil
    import re
    from types import SimpleNamespace
    from comicmeta import _common
    from comicmeta.cli import _render_settings_menu, _build_rows
    from comicmeta._commands.settings import load_flat
    monkeypatch.chdir(tmp_path)

    def strip_ansi(text):
        return re.sub(r"\x1b\[[0-9;]*m", "", text)

    def top_width(selected):
        fake = SimpleNamespace(columns=140, lines=24)
        original = shutil.get_terminal_size
        shutil.get_terminal_size = lambda f: fake
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                _render_settings_menu(_common.Palette(False), _build_rows(load_flat(), show_advanced=True), selected, None)
        finally:
            shutil.get_terminal_size = original
        return len(strip_ansi(buf.getvalue().split("\n")[0]))

    rows = _build_rows(load_flat(), show_advanced=True)
    widths = {top_width(i) for i in range(0, len(rows))}
    assert len(widths) == 1, f"panel width changed while scrolling: {widths}"


def test_dashboard_fits_narrow_terminal(tmp_path, monkeypatch):
    """The dashboard menu must never draw lines wider than the terminal."""
    import io
    import contextlib
    import shutil
    from types import SimpleNamespace
    from comicmeta import _common
    from comicmeta.cli import _render_menu
    monkeypatch.chdir(tmp_path)

    def strip_ansi(text):
        import re
        return re.sub(r"\x1b\[[0-9;]*m", "", text)

    for cols in (40, 60, 80, 100, 120):
        fake = SimpleNamespace(columns=cols, lines=24)
        original = shutil.get_terminal_size
        shutil.get_terminal_size = lambda f: fake
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                _render_menu(_common.Palette(False), 0, None, None)
        finally:
            shutil.get_terminal_size = original
        for line in buf.getvalue().split("\n"):
            assert len(strip_ansi(line)) <= cols, f"overflow at {cols} cols: {line!r}"


def test_detect_mounted_volumes_excludes_home(tmp_path, monkeypatch):
    """Mounted-volume detection never returns the user's home directory."""
    from comicmeta.cli import _detect_mounted_volumes
    volumes = _detect_mounted_volumes()
    home = Path.home().resolve()
    assert all(v.resolve() != home for v in volumes)
    assert all(v.is_dir() for v in volumes)


def test_backup_setup_skips_when_configured(tmp_path, monkeypatch):
    """First-run backup setup returns immediately once configured."""
    from comicmeta import _config as config
    from comicmeta._commands import settings as settings_cmd
    from comicmeta.cli import _first_run_backup_setup
    settings_cmd.set_key_silent("write.backup_configured", "true", target=tmp_path / "comicmeta.toml")
    called = {"picker": False}
    original_picker = None
    from comicmeta import cli
    original_picker = cli._pick_backup_location
    def fake_picker(colors):
        called["picker"] = True
    cli._pick_backup_location = fake_picker
    try:
        _first_run_backup_setup(None)
    finally:
        cli._pick_backup_location = original_picker
    assert not called["picker"]


def test_build_rows_renders_context_fields_and_add(tmp_path, monkeypatch):
    """A configured context shows its editable fields plus the add action."""
    from comicmeta import _context
    from comicmeta.cli import _build_rows
    from comicmeta._commands.settings import load_flat
    monkeypatch.chdir(tmp_path)
    _context.save_context({
        "name": "nas", "host": "h", "ssh_user": "u", "library_path": "/p",
    })
    rows = _build_rows(load_flat(), show_advanced=True)
    fields = [r for r in rows if r["type"] == "context-setting"]
    assert any(r["context_field"] == "host" for r in fields)
    assert any(r["type"] == "context-add" for r in rows)


def test_edit_bool_toggles_and_persists(tmp_path, monkeypatch):
    from comicmeta.cli import _build_rows, _edit_value, Palette
    from comicmeta._commands.settings import load_flat
    monkeypatch.chdir(tmp_path)
    settings = tmp_path / "comicmeta.toml"
    settings.write_text("[write]\nauto_confirm = true\n")
    rows = _build_rows(load_flat(), show_advanced=True)
    row = next(r for r in rows if r["type"] == "setting" and r["key"] == "write.auto_confirm")
    row["flat"] = load_flat()
    _edit_value(Palette(False), row)
    assert load_flat()["write.auto_confirm"] is False


def test_api_key_hidden_and_masked(tmp_path, monkeypatch):
    from unittest import mock
    from comicmeta.cli import _build_rows, _edit_value, Palette
    from comicmeta._commands.settings import load_flat
    monkeypatch.chdir(tmp_path)
    rows = _build_rows(load_flat(), show_advanced=True)
    row = next(r for r in rows if r["type"] == "setting" and r["key"] == "api.key_file")
    row["flat"] = load_flat()
    with mock.patch("comicmeta._tui.prompt_edit", return_value="sk_secret_12345"):
        with mock.patch("comicmeta.cli.verify_api_key", return_value=(True, "ok")):
            _edit_value(Palette(False), row)
    key_file = tmp_path / "comicvine.key"
    assert key_file.exists()
    assert key_file.read_text().strip() == "sk_secret_12345"
    assert key_file.stat().st_mode & 0o777 == 0o600
    assert str(key_file) == load_flat()["api.key_file"]


def test_api_key_rejected_still_saved(tmp_path, monkeypatch):
    from unittest import mock
    from comicmeta.cli import _build_rows, _edit_value, Palette
    from comicmeta._commands.settings import load_flat
    monkeypatch.chdir(tmp_path)
    rows = _build_rows(load_flat(), show_advanced=True)
    row = next(r for r in rows if r["type"] == "setting" and r["key"] == "api.key_file")
    row["flat"] = load_flat()
    with mock.patch("comicmeta._tui.prompt_edit", return_value="bad_key"):
        with mock.patch("comicmeta.cli.verify_api_key", return_value=(False, "invalid API key")):
            _edit_value(Palette(False), row)
    key_file = tmp_path / "comicvine.key"
    assert key_file.exists()
    assert key_file.read_text().strip() == "bad_key"


def test_api_key_empty_cancels(tmp_path, monkeypatch):
    from unittest import mock
    from comicmeta.cli import _build_rows, _edit_value, Palette
    from comicmeta._commands.settings import load_flat
    monkeypatch.chdir(tmp_path)
    rows = _build_rows(load_flat(), show_advanced=True)
    row = next(r for r in rows if r["type"] == "setting" and r["key"] == "api.key_file")
    row["flat"] = load_flat()
    with mock.patch("comicmeta._tui.prompt_edit", return_value="  "):
        changed = _edit_value(Palette(False), row)
    assert changed is False
    assert not (tmp_path / "comicvine.key").exists()


def test_blocked_queries_add(tmp_path, monkeypatch):
    from unittest import mock
    from comicmeta.cli import _build_rows, _edit_value, Palette
    from comicmeta._commands.settings import load_flat
    monkeypatch.chdir(tmp_path)
    settings = tmp_path / "comicmeta.toml"
    settings.write_text('[review]\nblocked_queries = { "Secret Wars (2025)" = "malformed" }\n')
    rows = _build_rows(load_flat(), show_advanced=True)
    row = next(r for r in rows if r["type"] == "setting" and r["key"] == "review.blocked_queries")
    row["flat"] = load_flat()
    inputs = iter(["Bad Batch (2024)", "corrupt"])
    keys = iter(["a", "b"])
    with mock.patch("builtins.input", lambda *a: next(inputs)):
        with mock.patch("comicmeta._tui.read_key", lambda: next(keys)):
            _edit_value(Palette(False), row)
    blocked = load_flat()["review.blocked_queries"]
    assert "Bad Batch (2024)" in blocked


def test_set_key_parses_dict_default():
    from comicmeta import _config
    flat = dict(_config.FLAT_DEFAULTS)
    _config.set_key(flat, "review.blocked_queries", '{"Secret Wars (2025)": "malformed"}')
    assert isinstance(flat["review.blocked_queries"], dict)
    assert flat["review.blocked_queries"]["Secret Wars (2025)"] == "malformed"


def test_set_key_rejects_invalid_json_for_dict():
    from comicmeta import _config
    import pytest
    flat = dict(_config.FLAT_DEFAULTS)
    with pytest.raises(SystemExit):
        _config.set_key(flat, "review.blocked_queries", "not json")


def test_state_files_resolve_to_config_dir(tmp_path, monkeypatch):
    from comicmeta import _config
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    src = tmp_path / "library"
    src.mkdir()
    flat = _config.load(src)
    assert flat["paths.candidates"].startswith(str(tmp_path / "cfg" / "comicmeta"))
    assert "libraries" in flat["paths.candidates"]
    assert str(src) not in flat["paths.candidates"]
    assert not Path(flat["paths.candidates"]).is_absolute() is False  # it IS absolute
    assert Path(flat["paths.candidates"]).is_absolute()
