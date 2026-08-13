import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from comicmeta.cli import build_parser

SRC = Path(__file__).resolve().parents[1] / "src"


def test_cover_tool_installer_detects_platform(monkeypatch):
    from comicmeta.cli import _cover_tool_installer
    monkeypatch.setattr("comicmeta.cli.shutil.which",
                        lambda t: "/usr/bin/brew" if t == "brew" else None)
    label, cmd = _cover_tool_installer()
    assert label == "timg with Homebrew"
    assert cmd == ["brew", "install", "timg"]
    monkeypatch.setattr("comicmeta.cli.shutil.which",
                        lambda t: "/usr/bin/apt-get" if t == "apt-get" else None)
    label, cmd = _cover_tool_installer()
    assert label == "chafa with apt"
    assert cmd == ["sudo", "apt-get", "install", "-y", "chafa"]
    monkeypatch.setattr("comicmeta.cli.shutil.which", lambda t: None)
    assert _cover_tool_installer() is None


def test_configure_cover_previews_enables_when_tool_present(monkeypatch, tmp_path):
    from unittest import mock
    from comicmeta.cli import _configure_cover_previews
    from comicmeta._common import Palette
    from comicmeta._commands import settings as settings_cmd
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr("comicmeta.cli.shutil.which",
                        lambda t: "/bin/timg" if t in ("timg", "chafa", "image") else None)
    config = tmp_path / "comicmeta" / "comicmeta.toml"
    assert _configure_cover_previews(Palette(False)) is True
    flat = settings_cmd.load_flat()
    assert flat["appearance.cover_previews"] is True


def test_configure_cover_previews_offers_apt_install(monkeypatch, tmp_path):
    from unittest import mock
    from comicmeta.cli import _configure_cover_previews
    from comicmeta._common import Palette
    from comicmeta._commands import settings as settings_cmd
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    present = {"apt-get": "/usr/bin/apt-get"}  # chafa absent until install
    monkeypatch.setattr("comicmeta.cli.shutil.which", lambda t: present.get(t))
    monkeypatch.setattr("comicmeta.cli.confirm", lambda *a, **k: True)
    monkeypatch.setattr("subprocess.run",
                        lambda cmd, **k: present.update({"chafa": "/usr/bin/chafa"}) or subprocess.CompletedProcess(cmd, 0))
    assert _configure_cover_previews(Palette(False)) is True
    flat = settings_cmd.load_flat()
    assert flat["appearance.cover_previews"] is True


def test_configure_cover_previews_stays_off_without_installer(monkeypatch, tmp_path, capsys):
    from comicmeta.cli import _configure_cover_previews
    from comicmeta._common import Palette
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr("comicmeta.cli.shutil.which", lambda t: None)
    monkeypatch.setattr("comicmeta._cover.pillow_preview_available", lambda: False)
    assert _configure_cover_previews(Palette(False)) is False
    out = capsys.readouterr().out
    assert "No cover renderer found" in out


def test_configure_cover_previews_enables_ascii_without_installer(monkeypatch, tmp_path):
    from comicmeta.cli import _configure_cover_previews
    from comicmeta._common import Palette
    from comicmeta._commands import settings as settings_cmd
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr("comicmeta.cli.shutil.which", lambda t: None)
    monkeypatch.setattr("comicmeta._cover.pillow_preview_available", lambda: True)
    assert _configure_cover_previews(Palette(False)) is True
    flat = settings_cmd.load_flat()
    assert flat["appearance.cover_previews"] is True


def test_configure_cover_previews_ascii_notice(monkeypatch, tmp_path, capsys):
    from comicmeta.cli import _configure_cover_previews
    from comicmeta._common import Palette
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr("comicmeta.cli.shutil.which", lambda t: None)
    monkeypatch.setattr("comicmeta._cover.pillow_preview_available", lambda: True)
    _configure_cover_previews(Palette(False))
    out = capsys.readouterr().out
    assert "enabled (Pillow true-color)" in out
    assert "install timg or chafa" in out


def test_configure_cover_previews_apt_failure_gives_root_hint(monkeypatch, tmp_path, capsys):
    from comicmeta.cli import _configure_cover_previews
    from comicmeta._common import Palette
    from comicmeta._commands import settings as settings_cmd
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    present = {"apt-get": "/usr/bin/apt-get"}  # chafa absent and install fails
    monkeypatch.setattr("comicmeta.cli.shutil.which", lambda t: present.get(t))
    monkeypatch.setattr("comicmeta.cli.confirm", lambda *a, **k: True)
    monkeypatch.setattr("comicmeta.cli._is_truenas", lambda: False)
    monkeypatch.setattr("comicmeta._cover.pillow_preview_available", lambda: True)
    monkeypatch.setattr("subprocess.run",
                        lambda cmd, **k: subprocess.CompletedProcess(cmd, 1))
    assert _configure_cover_previews(Palette(False)) is True  # pillow keeps previews on
    flat = settings_cmd.load_flat()
    assert flat["appearance.cover_previews"] is True
    out = capsys.readouterr().out
    assert "apt-get update && apt-get install -y chafa" in out


def test_configure_cover_previews_apt_failure_truenas_advice(monkeypatch, tmp_path, capsys):
    from comicmeta.cli import _configure_cover_previews
    from comicmeta._common import Palette
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    present = {"apt-get": "/usr/bin/apt-get"}
    monkeypatch.setattr("comicmeta.cli.shutil.which", lambda t: present.get(t))
    monkeypatch.setattr("comicmeta.cli.confirm", lambda *a, **k: True)
    monkeypatch.setattr("comicmeta.cli._is_truenas", lambda: True)
    monkeypatch.setattr("comicmeta._cover.pillow_preview_available", lambda: True)
    monkeypatch.setattr("subprocess.run",
                        lambda cmd, **k: subprocess.CompletedProcess(cmd, 1))
    _configure_cover_previews(Palette(False))
    out = capsys.readouterr().out
    assert "TrueNAS disables apt" in out
    assert "timg static binary" in out


def test_root_install_hint_strips_sudo_and_updates():
    from comicmeta.cli import _root_install_hint
    assert _root_install_hint(["sudo", "apt-get", "install", "-y", "chafa"]) == "apt-get update && apt-get install -y chafa"
    assert _root_install_hint(["brew", "install", "timg"]) == "brew install timg"


def run_cli(*args):
    env = {**os.environ.copy(), "PYTHONPATH": str(SRC)}
    # Isolate from the user's real config (its active context may be a NAS
    # context, which would route subprocess commands through the executor).
    env["XDG_CONFIG_HOME"] = tempfile.mkdtemp(prefix="comicmeta-test-")
    return subprocess.run(
        [sys.executable, "-m", "comicmeta", *map(str, args)],
        capture_output=True,
        text=True,
        env=env,
    )


def test_parser_has_all_commands():
    parser = build_parser()
    subcommands = parser._subparsers._group_actions[0].choices
    for expected in ("discover", "review-volumes", "fetch-issues", "review-issues", "map", "stage", "validate", "write"):
        assert expected in subcommands


def test_version():
    result = run_cli("--version")
    assert result.returncode == 0
    assert "comicmeta" in result.stdout


def test_help():
    result = run_cli("--help")
    assert result.returncode == 0
    for command in ("discover", "review-volumes", "fetch-issues", "review-issues", "map", "stage", "validate", "write"):
        assert command in result.stdout


def test_bare_invocation_shows_dashboard():
    result = run_cli()
    assert result.returncode == 0
    assert "comicmeta" in result.stdout
    assert "PIPELINE" in result.stdout
    assert "NEXT" in result.stdout
    assert "comicmeta discover" in result.stdout


def test_static_dashboard_title_uses_theme(monkeypatch, capsys):
    from comicmeta import cli

    monkeypatch.setattr(cli._config, "load", lambda *_: {})
    monkeypatch.setattr(cli._config, "get", lambda _flat, key: "marvel" if key == "appearance.theme" else None)
    monkeypatch.setattr(cli, "color_enabled", lambda: True)
    cli.dashboard()
    assert "\033[38;5;196mcomicmeta — review-then-write" in capsys.readouterr().out


def test_settings_viewport_keeps_selected_row_visible():
    from comicmeta.cli import _settings_viewport

    body = [("row", f"row {index}") for index in range(20)]
    visible = _settings_viewport(body, selected=10, terminal_rows=24)
    assert len(visible) == 14
    assert visible[0][1] == "  ↑ more settings"
    assert visible[-1][1] == "  ↓ more settings"
    assert ("row", "row 14") in visible


def test_help_grouped_and_ordered():
    result = run_cli("--help")
    assert "Read-only review pipeline" in result.stdout
    assert "Staging + execution" in result.stdout
    assert "health" in result.stdout
    assert "Run in order:" in result.stdout
    review = ["discover", "review-volumes", "fetch-issues", "review-issues", "map"]
    exec_ = ["stage", "validate", "write"]
    assert result.stdout.index(review[0]) < result.stdout.index(exec_[0])


def test_noninteractive_review_fails_cleanly(tmp_path):
    report = tmp_path / "issue-candidates.json"
    report.write_text('{"active_source": "/x", "scanned_source": "/x", "series": []}')
    result = run_cli("review-issues", "--report", report)
    assert result.returncode == 1
    assert "interactive terminal" in result.stderr
    assert "Traceback" not in result.stderr


def test_interactive_dashboard_quits_cleanly():
    from unittest import mock
    from comicmeta.cli import interactive_dashboard, build_parser
    parser = build_parser()
    with mock.patch("builtins.input", side_effect=["q"]):
        assert interactive_dashboard(parser) == 0


def test_interactive_dashboard_opens_step():
    from unittest import mock
    from comicmeta.cli import interactive_dashboard, build_parser
    parser = build_parser()
    # select step 2, then back (Enter), then quit
    with mock.patch("builtins.input", side_effect=["2", "", "q"]):
        assert interactive_dashboard(parser) == 0


def test_step_help_shows_real_usage():
    from comicmeta.cli import build_parser, _subparsers
    parser = build_parser()
    sub = _subparsers(parser).choices["review-volumes"]
    help_text = sub.format_help()
    assert "usage: comicmeta review-volumes" in help_text
    assert "--report REPORT" in help_text
    assert "discover report JSON" in help_text


def test_dashboard_has_six_steps():
    from comicmeta.cli import DASHBOARD_STEPS
    names = [name for name, _ in DASHBOARD_STEPS]
    assert names == ["review", "write", "convert", "browse", "organize", "health"]


def test_dashboard_arrow_navigation():
    from unittest import mock
    from comicmeta.cli import interactive_dashboard, build_parser
    parser = build_parser()
    keys = iter(["down", "q"])
    with mock.patch("comicmeta.cli.read_key", lambda: next(keys)):
        assert interactive_dashboard(parser) == 0


def test_dashboard_ctrl_c_and_ctrl_d_quit():
    from unittest import mock
    from comicmeta.cli import interactive_dashboard, build_parser
    parser = build_parser()
    for key in ("ctrl-c", "ctrl-d"):
        with mock.patch("comicmeta.cli.read_key", return_value=key):
            assert interactive_dashboard(parser) == 0


def test_dashboard_opens_settings():
    from unittest import mock
    from comicmeta.cli import interactive_dashboard, build_parser
    parser = build_parser()
    # press s to open settings, then back to dashboard, then quit
    keys = iter(["s", "b", "q"])
    with mock.patch("comicmeta.cli.read_key", lambda: next(keys)):
        with mock.patch("comicmeta.cli._settings_screen", return_value=1):
            assert interactive_dashboard(parser) == 0


def test_dashboard_convert_offers_execute_confirmation():
    from unittest import mock
    from comicmeta.cli import interactive_dashboard, build_parser
    parser = build_parser()
    calls = []

    def fake_run_subcommand(argv):
        calls.append(list(argv))
        return 0

    # jump to convert (3), run it (enter), confirm execute (e),
    # return to dashboard (enter), quit (q)
    keys = iter(["3", "enter", "e", "enter", "q"])
    with mock.patch("comicmeta.cli.read_key", lambda: next(keys)):
        with mock.patch("comicmeta.cli._run_subcommand", side_effect=fake_run_subcommand):
            assert interactive_dashboard(parser) == 0
    assert calls == [["convert"], ["convert", "--execute"]]


def test_dashboard_convert_skip_execute_keeps_dry_run():
    from unittest import mock
    from comicmeta.cli import interactive_dashboard, build_parser
    parser = build_parser()
    calls = []

    def fake_run_subcommand(argv):
        calls.append(list(argv))
        return 0

    # decline execution (n): dry-run only, no --execute
    keys = iter(["3", "enter", "n", "enter", "q"])
    with mock.patch("comicmeta.cli.read_key", lambda: next(keys)):
        with mock.patch("comicmeta.cli._run_subcommand", side_effect=fake_run_subcommand):
            assert interactive_dashboard(parser) == 0
    assert calls == [["convert"]]


def test_run_subcommand_clears_screens_around_alt_screen_leave(monkeypatch):
    """Running a step must wipe the dashboard and the stale main buffer so old
    shell history never leaks into step output."""
    import comicmeta.cli as cli

    calls = []
    monkeypatch.setattr(cli, "_DASHBOARD_CONTEXT", None)
    monkeypatch.setattr(cli, "_clear_screen", lambda: calls.append("clear"))
    monkeypatch.setattr("comicmeta._tui.leave_alt_screen", lambda: calls.append("leave"))
    monkeypatch.setattr(cli, "main", lambda argv: calls.append(("main", argv)))
    assert cli._run_subcommand(["review"]) == 0
    assert calls == ["clear", "leave", "clear", ("main", ["review"])]


def test_dashboard_help_page_has_footer(capsys):
    from unittest import mock
    from comicmeta.cli import interactive_dashboard, build_parser
    parser = build_parser()
    with mock.patch("builtins.input", side_effect=["h", "x", "q"]):
        assert interactive_dashboard(parser) == 0
    out = capsys.readouterr().out
    assert "back to the dashboard" in out


def test_dashboard_review_prompt_shows_when_held(capsys):
    from unittest import mock
    from comicmeta.cli import interactive_dashboard, build_parser
    parser = build_parser()
    with mock.patch("comicmeta.cli._review_held_count", return_value=2):
        with mock.patch("comicmeta.cli._run_subcommand", return_value=0):
            with mock.patch("builtins.input", side_effect=["1", "enter", "x", "enter", "q"]):
                assert interactive_dashboard(parser) == 0
    out = capsys.readouterr().out
    assert "re-open review (fix 2 held volumes)" in out
    assert "any other key returns to the dashboard" in out


def test_dashboard_review_skips_prompt_when_complete(capsys):
    from unittest import mock
    from comicmeta.cli import interactive_dashboard, build_parser
    parser = build_parser()
    with mock.patch("comicmeta.cli._review_held_count", return_value=0):
        with mock.patch("comicmeta.cli._run_subcommand", return_value=0):
            with mock.patch("builtins.input", side_effect=["1", "enter", "enter", "q"]):
                assert interactive_dashboard(parser) == 0
    out = capsys.readouterr().out
    assert "re-open review (fix" not in out
    assert "any other key returns to the dashboard" not in out


def test_review_command_list_shows_pipeline():
    import subprocess
    result = subprocess.run(
        [sys.executable, "-m", "comicmeta", "review", "--list"],
        capture_output=True, text=True, cwd=SRC.parent,
        env={**os.environ.copy(), "PYTHONPATH": str(SRC), "XDG_CONFIG_HOME": tempfile.mkdtemp(prefix="comicmeta-test-")},
    )
    assert result.returncode == 0
    assert "pipeline state" in result.stdout
    for step in ("discover", "volumes", "mapping"):
        assert step in result.stdout


def test_help_shows_examples():
    from comicmeta.cli import build_parser, _subparsers
    parser = build_parser()
    for name in ("write", "review", "discover", "map", "stage", "validate", "settings", "covers", "self-test", "update-check"):
        sub = _subparsers(parser).choices[name]
        help_text = sub.format_help()
        assert "examples:" in help_text, name


def test_short_flags_present():
    from comicmeta.cli import build_parser, _subparsers
    parser = build_parser()
    write_help = _subparsers(parser).choices["write"].format_help()
    assert "-y" in write_help
    assert "-s" in write_help
    assert "-r" in write_help


def test_logo_command():
    import subprocess
    result = subprocess.run(
        [sys.executable, "-m", "comicmeta", "logo"],
        capture_output=True, text=True,
        env={**os.environ.copy(), "PYTHONPATH": str(SRC), "XDG_CONFIG_HOME": tempfile.mkdtemp(prefix="comicmeta-test-")},
    )
    assert result.returncode == 0
    assert "▞▀▖" in result.stdout


def test_new_commands_registered():
    from comicmeta.cli import build_parser
    choices = build_parser()._subparsers._group_actions[0].choices
    for name in ("logo", "inspect", "organize"):
        assert name in choices


def test_dashboard_no_fresh_prompt_without_prior_review_state(tmp_path, monkeypatch, capsys):
    """After a first review run the [f]/[r] prompt must not appear — review
    itself creates the state files, so checking after the run would always
    match."""
    import io, contextlib
    from unittest import mock
    from comicmeta.cli import interactive_dashboard, build_parser
    from comicmeta import _config
    monkeypatch.chdir(tmp_path)
    # Point state paths at tmp_path so a missing volume state means nothing is held.
    state = {
        "paths.candidates": str(tmp_path / "comicvine-candidates.json"),
        "paths.volume_state": str(tmp_path / "comicvine-review-state.json"),
        "paths.issue_candidates": str(tmp_path / "comicvine-issue-candidates.json"),
        "paths.issue_state": str(tmp_path / "comicvine-issue-review-state.json"),
        "paths.mapping": str(tmp_path / "comic-metadata-reviewed-mapping.json"),
    }
    monkeypatch.setattr(_config, "load", lambda *a, **k: state)
    parser = build_parser()
    keys = iter(["enter", "x", "q"])  # run review on step 0, then back, then quit
    buf = io.StringIO()
    with mock.patch("comicmeta.cli.read_key", lambda: next(keys)):
        with mock.patch("comicmeta.cli._run_subcommand") as subcmd:
            subcmd.return_value = 0
            with contextlib.redirect_stdout(buf):
                interactive_dashboard(parser)
    out = buf.getvalue()
    assert "fresh review (discard" not in out
    assert "re-open review" not in out


def test_dashboard_shows_fresh_prompt_with_held_volumes(tmp_path, monkeypatch, capsys):
    """When the volume review still has held (skipped/flagged) volumes, running
    review offers fresh/reopen."""
    import io, contextlib
    from unittest import mock
    from comicmeta.cli import interactive_dashboard, build_parser
    from comicmeta import _config
    monkeypatch.chdir(tmp_path)
    state = {
        "paths.candidates": str(tmp_path / "comicvine-candidates.json"),
        "paths.volume_state": str(tmp_path / "comicvine-review-state.json"),
        "paths.issue_candidates": str(tmp_path / "comicvine-issue-candidates.json"),
        "paths.issue_state": str(tmp_path / "comicvine-issue-review-state.json"),
        "paths.mapping": str(tmp_path / "comic-metadata-reviewed-mapping.json"),
    }
    (tmp_path / "comicvine-candidates.json").write_text("{}")
    (tmp_path / "comicvine-review-state.json").write_text(
        '{"selections": {"DC": {"status": "skipped"}}}'
    )
    monkeypatch.setattr(_config, "load", lambda *a, **k: state)
    parser = build_parser()
    keys = iter(["enter", "f", "x", "q"])  # run review, hit [f] fresh, back, quit
    buf = io.StringIO()
    with mock.patch("comicmeta.cli.read_key", lambda: next(keys)):
        with mock.patch("comicmeta.cli._run_subcommand") as subcmd:
            subcmd.return_value = 0
            with contextlib.redirect_stdout(buf):
                interactive_dashboard(parser)
    out = buf.getvalue()
    assert "fresh review (discard" in out
    assert "re-open review" in out


def test_dashboard_runs_step_and_pauses(tmp_path, monkeypatch):
    import io, contextlib
    from unittest import mock
    from comicmeta.cli import interactive_dashboard, build_parser
    monkeypatch.chdir(tmp_path)
    parser = build_parser()
    keys = iter(["down", "down", "down", "enter", "x", "q"])  # navigate to browse (step 4)
    buf = io.StringIO()
    ran = []
    with mock.patch("comicmeta.cli.read_key", lambda: next(keys)):
        # Browse needs a TTY; mock the subcommand dispatch so it records what
        # would run instead of actually running it (and would return to menu).
        with mock.patch("comicmeta.cli._run_subcommand") as subcmd:
            def fake_subcommand(argv):
                ran.append(argv)
                print(f"  (would run: {' '.join(argv)})")
            subcmd.side_effect = fake_subcommand
            with contextlib.redirect_stdout(buf):
                assert interactive_dashboard(parser) == 0
    out = buf.getvalue()
    assert ["browse"] in ran
    assert "back to dashboard" in out


@pytest.fixture
def mock_contexts_dir(tmp_path, monkeypatch):
    """Redirect contexts and active-context files into a temporary directory."""
    from comicmeta import _context
    root = tmp_path / "comicmeta"
    root.mkdir()
    monkeypatch.setattr(_context, "contexts_dir", lambda: root / "contexts")
    monkeypatch.setattr(_context, "_active_path", lambda: root / "active_context")
    return root


def test_dashboard_shows_active_context(mock_contexts_dir, monkeypatch):
    from comicmeta.cli import _connection_light
    from comicmeta import _context
    from comicmeta._common import Palette
    root = mock_contexts_dir.parent
    monkeypatch.setenv("XDG_CONFIG_HOME", str(root))
    _context.save_context({
        "name": "nas",
        "host": "h",
        "ssh_user": "u",
        "library_path": "/p",
    })
    _context.set_active_context("nas")
    line = _connection_light(Palette(False), (True, "ok"))
    assert "nas" in line


def test_dashboard_explains_unavailable_context_recovery():
    from comicmeta.cli import _connection_light
    from comicmeta._common import Palette

    line = _connection_light(Palette(False), (False, "unreachable"), {"name": "nas"})

    assert "unavailable" in line
    assert "[c]" in line


def test_dashboard_context_toggle_cycles_to_local(mock_contexts_dir, monkeypatch):
    from comicmeta import cli, _context
    root = mock_contexts_dir.parent
    monkeypatch.setenv("XDG_CONFIG_HOME", str(root))
    _context.save_context({
        "name": "nas",
        "host": "h",
        "ssh_user": "u",
        "library_path": "/p",
    })
    _context.set_active_context("nas")
    cli._DASHBOARD_CONTEXT = None
    assert cli._target_context().get("name") == "nas"
    cli._cycle_target_context()
    assert cli._target_context().get("name") == "local"
    cli._cycle_target_context()
    assert cli._target_context().get("name") == "nas"


def test_dashboard_target_context_threads_into_subcommand(mock_contexts_dir, monkeypatch):
    import comicmeta.cli as cli
    from comicmeta import _context
    root = mock_contexts_dir.parent
    monkeypatch.setenv("XDG_CONFIG_HOME", str(root))
    _context.save_context({
        "name": "nas",
        "host": "h",
        "ssh_user": "u",
        "library_path": "/p",
    })
    _context.set_active_context("nas")
    cli._DASHBOARD_CONTEXT = None
    captured = []
    original = cli.main

    def fake_main(argv):
        captured.append(argv)
        return 0

    cli.main = fake_main
    try:
        cli._run_subcommand(["health"])
        # At the active context (NAS), no --context is injected by default.
        assert captured == [["health"]]
        captured.clear()
        cli._cycle_target_context()  # → local
        cli._run_subcommand(["health"])
        assert captured[0][:2] == ["--context", "local"]
    finally:
        cli.main = original
        cli._DASHBOARD_CONTEXT = None


def test_dashboard_no_context_when_local(mock_contexts_dir, monkeypatch):
    from comicmeta.cli import _menu_status_line
    from comicmeta import _context
    root = mock_contexts_dir.parent
    monkeypatch.setenv("XDG_CONFIG_HOME", str(root))
    line = _menu_status_line()
    assert "context:" not in line


# ─── CLI design improvements ───


def _parse_error_message(parser, argv):
    """Return the stderr emitted when parsing argv raises SystemExit."""
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        with pytest.raises(SystemExit):
            parser.parse_args(argv)
    return buf.getvalue()


def test_mistyped_command_suggests_correction():
    from comicmeta.cli import build_parser
    parser = build_parser()
    message = _parse_error_message(parser, ["reviwe"])
    assert "invalid choice: 'reviwe'" in message
    assert "Did you mean: review?" in message


def test_mistyped_command_suggestion_uses_help():
    from comicmeta.cli import build_parser
    parser = build_parser()
    message = _parse_error_message(parser, ["wrtie"])
    assert "Did you mean: write?" in message
    assert "comicmeta write --help" in message


def test_help_shows_issues_url():
    from comicmeta.cli import build_parser, ISSUES_URL
    parser = build_parser()
    help_text = parser.format_help()
    assert ISSUES_URL in help_text


def test_parser_has_debug_flag():
    from comicmeta.cli import build_parser
    parser = build_parser()
    args = parser.parse_args(["--debug", "logo"])
    assert args.debug is True


def test_unexpected_error_reports_bug_friendly(capsys):
    from unittest import mock
    import contextlib
    from comicmeta.cli import main, ISSUES_URL
    with mock.patch("comicmeta._commands.logo.run", side_effect=RuntimeError("kaboom")):
        with pytest.raises(SystemExit) as exc:
            main(["logo"])
    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "unexpected error: kaboom" in captured.err
    assert "not something you did wrong" in captured.err
    assert ISSUES_URL in captured.err
    assert "--debug" in captured.err


def test_unexpected_error_debug_shows_traceback(capsys):
    from unittest import mock
    from comicmeta.cli import main
    with mock.patch("comicmeta._commands.logo.run", side_effect=RuntimeError("kaboom")):
        with pytest.raises(SystemExit) as exc:
            main(["--debug", "logo"])
    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "RuntimeError: kaboom" in captured.err
    assert "Traceback" in captured.err


def test_run_subcommand_warns_on_nonzero_exit(capsys):
    """Regression: a failing subcommand from the dashboard (e.g. mapping
    blocked by unreviewed candidates) must surface a warning instead of
    silently returning to the menu."""
    from unittest import mock
    from comicmeta.cli import _run_subcommand
    with mock.patch("comicmeta.cli.main", side_effect=SystemExit(2)):
        code = _run_subcommand(["review"])
    assert code == 2
    captured = capsys.readouterr()
    assert "finished with errors (exit 2)" in captured.out
    assert "dashboard menu will not have been updated" in captured.out


def test_run_subcommand_silent_on_success(capsys):
    from unittest import mock
    from comicmeta.cli import _run_subcommand
    with mock.patch("comicmeta.cli.main", return_value=None):
        code = _run_subcommand(["review"])
    assert code == 0
    captured = capsys.readouterr()
    assert "finished with errors" not in captured.out
