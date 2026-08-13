import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"


def run_cli(*args, cwd=None, env=None):
    base = {**os.environ.copy(), "PYTHONPATH": str(SRC)}
    if env:
        base.update(env)
    return subprocess.run(
        [sys.executable, "-m", "comicmeta", *map(str, args)],
        capture_output=True,
        text=True,
        cwd=cwd,
        env=base,
    )


def make_library(tmp_path, n=2):
    """Create a fake library with n CBZ archives."""
    for i in range(1, n + 1):
        comic = tmp_path / "Marvel" / f"Series #{i:03}.cbz"
        comic.parent.mkdir(parents=True, exist_ok=True)
        comic.write_bytes(b"PK\x03\x04")
    return tmp_path


# ─── status ───


def test_status_renders_library_and_pipeline(tmp_path):
    lib = make_library(tmp_path)
    result = run_cli("status", "--source", str(lib))
    assert result.returncode == 0, result.stderr
    assert "STATUS" in result.stdout
    assert "Context" in result.stdout
    assert "Archives" in result.stdout
    assert "Pipeline" in result.stdout
    assert "Next:" in result.stdout


def test_status_json(tmp_path):
    lib = make_library(tmp_path)
    result = run_cli("status", "--json", "--source", str(lib))
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["library"] == str(lib.resolve())
    assert payload["archives"] == 2
    assert payload["context"] == "local"
    assert len(payload["pipeline"]) == 5


def test_status_missing_source_fails(tmp_path):
    result = run_cli("status", "--source", str(tmp_path / "nope"))
    assert result.returncode == 1
    assert "does not exist" in result.stderr


# ─── help ───


def test_help_command_shows_top_level():
    result = run_cli("help")
    assert result.returncode == 0
    assert "usage: comicmeta" in result.stdout


def test_help_command_shows_subcommand():
    result = run_cli("help", "write")
    assert result.returncode == 0
    assert "usage: comicmeta write" in result.stdout


def test_help_unknown_command_fails():
    result = run_cli("help", "nope")
    assert result.returncode == 1
    assert "unknown command" in result.stderr


# ─── completion ───


def test_completion_zsh():
    result = run_cli("completion", "zsh")
    assert result.returncode == 0
    assert "#compdef comicmeta" in result.stdout
    assert "review" in result.stdout
    assert "status" in result.stdout


def test_completion_bash():
    result = run_cli("completion", "bash")
    assert result.returncode == 0
    assert "_comicmeta_completions" in result.stdout
    assert "complete -F" in result.stdout
    assert "status" in result.stdout


# ─── color gating ───


def test_color_enabled_when_no_overrides(tmp_path, monkeypatch):
    from comicmeta._common import color_enabled
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("TERM", raising=False)
    class Tty:
        def isatty(self):
            return True
    assert color_enabled(stream=Tty()) is True


def test_color_disabled_with_no_color_env(tmp_path, monkeypatch):
    from comicmeta._common import color_enabled
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.delenv("TERM", raising=False)
    assert color_enabled() is False


def test_color_disabled_with_dumb_term(tmp_path, monkeypatch):
    from comicmeta._common import color_enabled
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "dumb")
    assert color_enabled() is False


def test_color_disabled_with_no_color_flag(tmp_path, monkeypatch):
    from comicmeta._common import color_enabled
    from types import SimpleNamespace
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("TERM", raising=False)
    args = SimpleNamespace(no_color=True)
    assert color_enabled(args) is False


# ─── --no-input flag ───


def test_parser_has_no_input_flag():
    from comicmeta.cli import build_parser
    parser = build_parser()
    args = parser.parse_args(["--no-input", "logo"])
    assert args.no_input is True


def test_require_tty_honors_no_input():
    from comicmeta._common import require_tty
    from comicmeta._tui import set_no_input
    set_no_input(True)
    try:
        with pytest.raises(SystemExit) as exc:
            require_tty("review", "comicmeta review --list")
        assert exc.value.code == 1
    finally:
        set_no_input(False)


def test_no_input_flag_blocks_interactive(tmp_path):
    """A command that needs a TTY fails cleanly when --no-input is passed."""
    report = tmp_path / "issue-candidates.json"
    report.write_text('{"active_source": "/x", "scanned_source": "/x", "series": []}')
    result = run_cli("--no-input", "review-issues", "--report", str(report))
    assert result.returncode == 1
    assert "needs an interactive terminal" in result.stderr
    assert "Traceback" not in result.stderr


# ─── settings panel render ───


def _render_panel(rows, selected=1, show_advanced=False, width=100, search=""):
    """Render the settings panel with a fixed terminal width, returning output."""
    import io
    import contextlib
    import types
    from unittest import mock
    from comicmeta._common import Palette
    from comicmeta.cli import _render_settings_menu
    ts = types.SimpleNamespace(columns=width, lines=80)
    buf = io.StringIO()
    with mock.patch("comicmeta.cli._clear_screen", lambda: None):
        with mock.patch("comicmeta.cli.shutil.get_terminal_size", lambda *a, **k: ts):
            with contextlib.redirect_stdout(buf):
                _render_settings_menu(Palette(False), rows, selected, None, show_advanced, search)
    return buf.getvalue()


def test_settings_panel_has_frame(monkeypatch, capsys):
    """The interactive settings menu renders a bordered panel."""
    from comicmeta._commands import settings as settings_cmd
    from comicmeta.cli import _build_rows
    flat = settings_cmd.load_flat()
    rows = _build_rows(flat)
    out = _render_panel(rows)
    assert out.lstrip().startswith("┌─")
    assert "└" in out
    assert "comicmeta settings" in out
    assert "APPEARANCE" in out
    assert "CONNECTIONS" in out
    assert "ADVANCED" in out
    assert "[↑/↓] move" in out


def test_settings_panel_centered(monkeypatch, capsys):
    """On a wide terminal the panel is centered (leading indentation)."""
    from comicmeta._commands import settings as settings_cmd
    from comicmeta.cli import _build_rows
    flat = settings_cmd.load_flat()
    rows = _build_rows(flat)
    out = _render_panel(rows, width=200)
    first = next(line for line in out.splitlines() if line.lstrip().startswith("┌"))
    indent = len(first) - len(first.lstrip())
    assert indent > 0


def test_settings_panel_hides_advanced_by_default(monkeypatch, capsys):
    """Internal state-file paths are hidden by default, shown with [a]."""
    from comicmeta._commands import settings as settings_cmd
    from comicmeta.cli import _build_rows
    flat = settings_cmd.load_flat()
    basic = _build_rows(flat, show_advanced=False)
    advanced = _build_rows(flat, show_advanced=True)
    basic_keys = {r["key"] for r in basic if r["type"] == "setting"}
    advanced_keys = {r["key"] for r in advanced if r["type"] == "setting"}
    assert "paths.candidates" not in basic_keys
    assert "paths.candidates" in advanced_keys
    assert "api.request_delay" not in basic_keys


def test_settings_panel_masks_secrets(monkeypatch, capsys):
    from comicmeta._commands import settings as settings_cmd
    from comicmeta.cli import _build_rows
    flat = settings_cmd.load_flat()
    flat["api.key_file"] = "/tmp/secret.key"
    rows = _build_rows(flat, show_advanced=True)
    out = _render_panel(rows)
    assert "••••••••" in out
    assert "/tmp/secret.key" not in out


def test_settings_panel_shows_context_summary(tmp_path, monkeypatch):
    """Connections start as compact summaries and expand on demand."""
    from comicmeta._commands import settings as settings_cmd
    from comicmeta.cli import _build_rows
    from comicmeta import _context
    root = tmp_path / "cfg"
    root.mkdir()
    monkeypatch.setattr(_context, "contexts_dir", lambda: root / "contexts")
    monkeypatch.setattr(_context, "_active_path", lambda: root / "active_context")
    _context.save_context({
        "name": "nas", "host": "h", "ssh_user": "u",
        "ssh_port": 2222, "library_path": "/p", "exec": "rsync",
    })
    _context.set_active_context("nas")
    flat = settings_cmd.load_flat()
    rows = _build_rows(flat)
    out = _render_panel(rows)
    assert "CONNECTIONS" in out
    assert "nas" in out
    assert "SSH port" not in out

    rows = _build_rows(flat, expanded_contexts={"nas"})
    out = _render_panel(rows)
    assert "SSH port" in out
    assert "2222" in out


# ─── setting descriptions ───


def test_every_setting_has_description():
    """Every config key has a one-line description for the settings panel."""
    from comicmeta import _config
    for section, keys in _config.DEFAULTS.items():
        for key in keys:
            full = f"{section}.{key}"
            assert full in _config.SETTINGS_DESCRIPTIONS, f"missing description for {full}"
            assert len(_config.SETTINGS_DESCRIPTIONS[full]) > 10


def test_render_includes_descriptions(capsys):
    from comicmeta import _config
    text = _config.render(dict(_config.FLAT_DEFAULTS))
    assert "# Library root" in text
    assert "# Seconds to wait between ComicVine API calls" in text


def test_settings_panel_shows_selected_description(monkeypatch, capsys):
    """The panel shows the selected setting's description near the bottom."""
    from comicmeta._commands import settings as settings_cmd
    from comicmeta.cli import _build_rows
    from comicmeta import _config
    flat = settings_cmd.load_flat()
    rows = _build_rows(flat, show_advanced=True)
    out = _render_panel(rows, selected=1)
    assert "cover" in out.lower()


def test_settings_describe_command():
    from comicmeta._commands.settings import _describe
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        _describe("api.key_file")
    out = buf.getvalue()
    assert "api.key_file" in out
    assert "API key file" in out
    assert "File containing the API key" in out
    assert "default:" in out


def test_settings_describe_unknown_fails():
    from comicmeta._commands.settings import _describe
    import pytest
    with pytest.raises(SystemExit) as exc:
        _describe("nope")
    assert exc.value.code == 1


def test_settings_panel_has_search_field(monkeypatch, capsys):
    """The panel shows a search line with the current query and cursor."""
    from comicmeta._commands import settings as settings_cmd
    from comicmeta.cli import _build_rows
    flat = settings_cmd.load_flat()
    rows = _build_rows(flat)
    out = _render_panel(rows, search="key")
    assert "❯ key▍" in out
    assert "type to search" in out


def test_filter_rows_filters_by_label(monkeypatch, capsys):
    """Search filters settings to matching rows under a single MATCHES header."""
    from comicmeta._commands import settings as settings_cmd
    from comicmeta.cli import _build_rows, _filter_rows
    flat = settings_cmd.load_flat()
    rows = _build_rows(flat, show_advanced=True)
    filtered = _filter_rows(rows, "timeout")
    labels = [r["label"] for r in filtered if r["type"] == "setting"]
    assert "API request timeout" in labels
    assert "API key environment variable" not in labels
    headers = [r for r in filtered if r["type"] == "header"]
    assert len(headers) == 1
    assert headers[0]["title"] == "MATCHES"


def test_filter_rows_empty_search_returns_all(monkeypatch, capsys):
    from comicmeta._commands import settings as settings_cmd
    from comicmeta.cli import _build_rows, _filter_rows
    flat = settings_cmd.load_flat()
    rows = _build_rows(flat)
    assert _filter_rows(rows, "") == rows


def test_settings_panel_selected_row_reverse_video(monkeypatch, capsys):
    """The selected row is rendered as a full-width reverse-video bar."""
    import types
    from unittest import mock
    import io
    import contextlib
    from comicmeta._common import Palette
    from comicmeta.cli import _render_settings_menu, _build_rows
    from comicmeta._commands import settings as settings_cmd
    ts = types.SimpleNamespace(columns=100, lines=24)
    flat = settings_cmd.load_flat()
    rows = _build_rows(flat, show_advanced=True)
    buf = io.StringIO()
    with mock.patch("comicmeta.cli._clear_screen", lambda: None):
        with mock.patch("comicmeta.cli.shutil.get_terminal_size", lambda *a, **k: ts):
            with contextlib.redirect_stdout(buf):
                _render_settings_menu(Palette(True), rows, 1, None, False, "")
    out = buf.getvalue()
    selected_line = next(line for line in out.splitlines() if "API key environment" in line)
    assert "\x1b[7m" in selected_line
    assert "\x1b[36m❯ \x1b[0m" in selected_line
