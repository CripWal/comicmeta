import sys
from pathlib import Path
from unittest import mock

import pytest

from comicmeta import _context, _executor
from comicmeta._context import DEFAULT_CONNECT_TIMEOUT
from comicmeta._executors import get_executor
from comicmeta._executors.docker import DockerExecutor
from comicmeta._executors.rsync import RsyncExecutor
from comicmeta.cli import _strip_context_flag, main

SRC = Path(__file__).resolve().parents[1] / "src"


@pytest.fixture
def mock_contexts_dir(tmp_path, monkeypatch):
    """Redirect contexts and active-context files into a temporary directory."""
    root = tmp_path / "comicmeta"
    root.mkdir()
    monkeypatch.setattr(_context, "contexts_dir", lambda: root / "contexts")
    monkeypatch.setattr(_context, "_active_path", lambda: root / "active_context")
    return root


@pytest.fixture
def nas_context():
    return {
        "name": "nas",
        "host": "nas.example.com",
        "ssh_user": "alice",
        "library_path": "/srv/comics",
        "exec": "rsync",
        "nas_src": "~/comicmeta",
        "image": "comicmeta:latest",
    }


# ─── _strip_context_flag ───


def test_strip_context_flag_long():
    assert _strip_context_flag(["--context", "nas", "inspect", "--quick"]) == [
        "inspect", "--quick"
    ]


def test_strip_context_flag_short():
    assert _strip_context_flag(["-c", "nas", "inspect"]) == ["inspect"]


def test_strip_context_flag_not_present():
    assert _strip_context_flag(["inspect", "--quick"]) == ["inspect", "--quick"]


def test_strip_context_flag_at_end():
    assert _strip_context_flag(["inspect", "--context", "nas"]) == ["inspect"]


# ─── _prepare_argv ───


def test_prepare_argv_replaces_source(nas_context):
    ex = RsyncExecutor(nas_context)
    result = ex._prepare_argv(["inspect", "--source", "/Volumes/media/comics", "--quick"])
    assert result == ["inspect", "--source", "/srv/comics", "--quick"]


def test_prepare_argv_appends_source_when_missing(nas_context):
    ex = RsyncExecutor(nas_context)
    result = ex._prepare_argv(["inspect", "--quick"])
    assert result == ["inspect", "--quick", "--source", "/srv/comics"]


def test_prepare_argv_replaces_short_source(nas_context):
    ex = RsyncExecutor(nas_context)
    result = ex._prepare_argv(["inspect", "-s", "/local", "--quick"])
    assert result == ["inspect", "-s", "/srv/comics", "--quick"]


def test_prepare_argv_injects_api_key_file_for_review(nas_context):
    ex = RsyncExecutor(nas_context)
    result = ex._prepare_argv(["review"])
    assert "--api-key-file" in result
    assert result[result.index("--api-key-file") + 1] == _context.DEFAULT_KEY_LOCATION


def test_prepare_argv_injects_api_key_file_for_discover(nas_context):
    ex = RsyncExecutor(nas_context)
    result = ex._prepare_argv(["discover", "--report", "r.json"])
    assert result[result.index("--api-key-file") + 1] == _context.DEFAULT_KEY_LOCATION


def test_prepare_argv_does_not_inject_key_for_health(nas_context):
    ex = RsyncExecutor(nas_context)
    result = ex._prepare_argv(["health"])
    assert "--api-key-file" not in result


def test_prepare_argv_respects_explicit_api_key_file(nas_context):
    ex = RsyncExecutor(nas_context)
    result = ex._prepare_argv(["review", "--api-key-file", "/data/key"])
    assert "--api-key-file" in result
    assert result[result.index("--api-key-file") + 1] == "/data/key"


def test_prepare_argv_skips_source_for_bare_dashboard(nas_context):
    ex = RsyncExecutor(nas_context)
    result = ex._prepare_argv([])
    assert result == []


def test_prepare_argv_does_not_inject_source_for_non_source_commands(nas_context):
    ex = RsyncExecutor(nas_context)
    for command in ("setup", "review-volumes", "map"):
        assert ex._prepare_argv([command]) == [command]
    # fetch-issues takes no --source but still gets the API key file injected.
    result = ex._prepare_argv(["fetch-issues"])
    assert "--source" not in result
    assert result == ["fetch-issues", "--api-key-file", _context.DEFAULT_KEY_LOCATION]


def test_prepare_argv_injects_source_only_for_source_commands(nas_context):
    ex = RsyncExecutor(nas_context)
    result = ex._prepare_argv(["status"])
    assert result == ["status", "--source", nas_context["library_path"]]


# ─── _shell_cmd ───


def test_shell_cmd_quotes_regular_args():
    cmd = _executor.Executor._shell_cmd(["docker", "run", "--rm", "-v", "/path:/comics"])
    # /path:/comics contains no shell metacharacters, so shlex.quote leaves it bare
    assert cmd == "docker run --rm -v /path:/comics"


def test_shell_cmd_preserves_tilde():
    cmd = _executor.Executor._shell_cmd(["-v", "~/.config/comicmeta:/data/config"])
    assert cmd == "-v ~/.config/comicmeta:/data/config"


def test_shell_cmd_preserves_pythonpath_tilde():
    cmd = _executor.Executor._shell_cmd(["PYTHONPATH=~/comicmeta", "python3"])
    assert cmd == "PYTHONPATH=~/comicmeta python3"


# ─── Executor factory ───


def test_get_executor_rsync(nas_context):
    nas_context["exec"] = "rsync"
    ex = get_executor(nas_context)
    assert isinstance(ex, RsyncExecutor)


def test_get_executor_docker(nas_context):
    nas_context["exec"] = "docker"
    ex = get_executor(nas_context)
    assert isinstance(ex, DockerExecutor)


def test_get_executor_unknown(nas_context):
    nas_context["exec"] = "bad"
    with pytest.raises(ValueError):
        get_executor(nas_context)


# ─── RsyncExecutor command construction ───


def test_rsync_executor_run_command(nas_context, monkeypatch):
    ex = RsyncExecutor(nas_context)
    called = []
    monkeypatch.setattr(ex, "_run_ssh", lambda flags, parts: called.append((flags, parts)) or 0)
    ex.run(["inspect", "--quick"])
    assert len(called) == 1
    flags, parts = called[0]
    assert flags == []
    assert parts[0] == "PYTHONPATH=~/comicmeta"
    assert "python3" in parts
    assert "--source" in parts
    assert "/srv/comics" in parts


def test_rsync_executor_forces_local_context_remotely(nas_context, monkeypatch):
    ex = RsyncExecutor(nas_context)
    called = []
    monkeypatch.setattr(ex, "_run_ssh", lambda flags, parts: called.append((flags, parts)) or 0)
    ex.run(["status"])
    parts = called[0][1]
    assert "--context" in parts
    assert parts[parts.index("--context") + 1] == "local"


def test_sync_source_unreachable_returns_single_message(nas_context, monkeypatch):
    ex = RsyncExecutor(nas_context)
    calls = []

    def fake_run_ssh(flags, parts, report_unreachable=True):
        calls.append(report_unreachable)
        return 255

    monkeypatch.setattr(ex, "_run_ssh", fake_run_ssh)
    ok, message = ex.sync_source()
    assert ok is False
    assert "could not reach" in message
    assert "--context local" in message
    # The sync path owns the error report; _run_ssh must stay silent.
    assert calls == [False]


def test_rsync_executor_xdg_base_default(nas_context):
    # config_dir defaults to ~/.config/comicmeta → XDG base is its parent
    ex = RsyncExecutor(nas_context)
    assert ex._xdg_base() == "~/.config"


def test_rsync_executor_xdg_base_custom(nas_context):
    nas_context["config_dir"] = "/srv/appdata/comicmeta/comicmeta"
    ex = RsyncExecutor(nas_context)
    assert ex._xdg_base() == "/srv/appdata/comicmeta"


def test_rsync_executor_passes_xdg_base(nas_context, monkeypatch):
    nas_context["config_dir"] = "/data/ns/cm/comicmeta"
    ex = RsyncExecutor(nas_context)
    called = []
    monkeypatch.setattr(ex, "_run_ssh", lambda flags, parts: called.append((flags, parts)) or 0)
    ex.run(["inspect", "--quick"])
    parts = called[0][1]
    assert "XDG_CONFIG_HOME=/data/ns/cm" in parts
    assert parts[0] == "PYTHONPATH=~/comicmeta"


def test_rsync_executor_interactive_uses_tty(nas_context, monkeypatch):
    ex = RsyncExecutor(nas_context)
    called = []
    monkeypatch.setattr(ex, "_run_ssh", lambda flags, parts: called.append((flags, parts)) or 0)
    ex.run_interactive(["browse"])
    assert called[0][0] == ["-t"]


# ─── DockerExecutor command construction ───


def test_docker_executor_run_command(nas_context, monkeypatch):
    nas_context["exec"] = "docker"
    ex = DockerExecutor(nas_context)
    called = []
    monkeypatch.setattr(ex, "_run_ssh", lambda flags, parts: called.append((flags, parts)) or 0)
    ex.run(["inspect", "--quick"])
    assert len(called) == 1
    flags, parts = called[0]
    assert flags == []
    assert "docker" in parts
    assert "run" in parts
    assert "--rm" in parts
    assert f"/srv/comics:/comics" in parts
    assert "~/.config/comicmeta:/data/config" in parts
    assert "comicmeta:latest" in parts
    assert parts[parts.index("--context") + 1] == "local"


def test_docker_executor_config_mount_custom(nas_context, monkeypatch):
    nas_context["exec"] = "docker"
    nas_context["config_dir"] = "/srv/appdata/comicmeta/comicmeta"
    ex = DockerExecutor(nas_context)
    called = []
    monkeypatch.setattr(ex, "_run_ssh", lambda flags, parts: called.append((flags, parts)) or 0)
    ex.run(["inspect", "--quick"])
    parts = called[0][1]
    assert "/srv/appdata/comicmeta/comicmeta:/data/config" in parts


def test_docker_executor_interactive_uses_it_and_tty(nas_context, monkeypatch):
    nas_context["exec"] = "docker"
    ex = DockerExecutor(nas_context)
    called = []
    monkeypatch.setattr(ex, "_run_ssh", lambda flags, parts: called.append((flags, parts)) or 0)
    ex.run_interactive(["browse"])
    flags, parts = called[0]
    assert flags == ["-t"]
    assert "-it" in parts


# ─── Integration: cli.py dispatches to executor for NAS context ───


def test_cli_dispatches_to_executor(mock_contexts_dir, monkeypatch, tmp_path, capsys):
    """When NAS context is active, cli main() dispatches to the executor."""
    root = mock_contexts_dir.parent
    monkeypatch.setenv("XDG_CONFIG_HOME", str(root))
    _context.save_context({
        "name": "nas",
        "host": "nas.example.com",
        "ssh_user": "alice",
        "library_path": "/srv/comics",
        "exec": "rsync",
    })
    _context.set_active_context("nas")
    # Mock _run_ssh so we don't actually try to ssh, but let the executor build the command
    dispatched = []

    def fake_run_ssh(self, flags, parts):
        dispatched.append(("run_ssh", flags, parts))
        return 0

    monkeypatch.setattr(
        "comicmeta._executor.Executor._run_ssh", fake_run_ssh
    )
    monkeypatch.setattr(
        "comicmeta._executors.rsync.RsyncExecutor.sync_source",
        lambda self: (True, "synced"),
    )
    # Run a headless command (inspect --quick)
    with pytest.raises(SystemExit) as exc:
        main(["--context", "nas", "inspect", "--quick", "--source", str(tmp_path)])
    assert exc.value.code == 0
    assert len(dispatched) == 1
    assert dispatched[0][0] == "run_ssh"
    # The remote command parts should include the remapped --source
    parts = dispatched[0][2]
    assert "python3" in parts
    assert "-m" in parts
    assert "comicmeta" in parts
    assert "--source" in parts
    assert "/srv/comics" in parts


def test_cli_auto_syncs_rsync_context_before_dispatch(mock_contexts_dir, monkeypatch, tmp_path):
    root = mock_contexts_dir.parent
    monkeypatch.setenv("XDG_CONFIG_HOME", str(root))
    _context.save_context({
        "name": "nas",
        "host": "h",
        "ssh_user": "u",
        "library_path": "/p",
        "exec": "rsync",
    })
    _context.set_active_context("nas")
    events = []
    monkeypatch.setattr(
        "comicmeta._executors.rsync.RsyncExecutor.sync_source",
        lambda self: events.append("sync") or (True, "synced"),
    )
    monkeypatch.setattr(
        "comicmeta._executors.rsync.RsyncExecutor.run",
        lambda self, argv: events.append(("run", argv)) or 0,
    )

    with pytest.raises(SystemExit) as exc:
        main(["--context", "nas", "health", "--source", str(tmp_path)])

    assert exc.value.code == 0
    assert events[0] == "sync"
    assert events[1][0] == "run"


def test_cli_stops_when_rsync_context_sync_fails(mock_contexts_dir, monkeypatch, tmp_path, capsys):
    root = mock_contexts_dir.parent
    monkeypatch.setenv("XDG_CONFIG_HOME", str(root))
    _context.save_context({
        "name": "nas",
        "host": "h",
        "ssh_user": "u",
        "library_path": "/p",
        "exec": "rsync",
    })
    _context.set_active_context("nas")
    monkeypatch.setattr(
        "comicmeta._executors.rsync.RsyncExecutor.sync_source",
        lambda self: (False, "NAS unavailable"),
    )

    with pytest.raises(SystemExit) as exc:
        main(["--context", "nas", "organize", "--execute", "--source", str(tmp_path)])

    assert exc.value.code == 1
    assert "NAS unavailable" in capsys.readouterr().err


def test_existing_local_source_overrides_active_nas(mock_contexts_dir, monkeypatch, tmp_path):
    root = mock_contexts_dir.parent
    monkeypatch.setenv("XDG_CONFIG_HOME", str(root))
    _context.save_context({
        "name": "nas",
        "host": "h",
        "ssh_user": "u",
        "library_path": "/p",
        "exec": "rsync",
    })
    _context.set_active_context("nas")
    monkeypatch.setattr(
        "comicmeta._executors.rsync.RsyncExecutor.run",
        lambda self, argv: pytest.fail("local source was incorrectly sent to NAS"),
    )

    main(["organize", "--source", str(tmp_path)])


def test_comic_filled_current_directory_overrides_active_nas(mock_contexts_dir, monkeypatch, tmp_path):
    import zipfile

    root = mock_contexts_dir.parent
    monkeypatch.setenv("XDG_CONFIG_HOME", str(root))
    _context.save_context({
        "name": "nas",
        "host": "h",
        "ssh_user": "u",
        "library_path": "/p",
        "exec": "rsync",
    })
    _context.set_active_context("nas")
    with zipfile.ZipFile(tmp_path / "local.cbz", "w") as archive:
        archive.writestr("001.jpg", b"page")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "comicmeta._executors.rsync.RsyncExecutor.run",
        lambda self, argv: pytest.fail("comic-filled current directory was sent to NAS"),
    )

    main(["organize"])


def test_cli_dispatches_interactive_with_tty(mock_contexts_dir, monkeypatch, tmp_path, capsys):
    """Interactive commands on a TTY use run_interactive."""
    root = mock_contexts_dir.parent
    monkeypatch.setenv("XDG_CONFIG_HOME", str(root))
    _context.save_context({
        "name": "nas",
        "host": "h",
        "ssh_user": "u",
        "library_path": "/p",
        "exec": "rsync",
    })
    _context.set_active_context("nas")
    dispatched = []

    def fake_run(self, argv):
        dispatched.append(("run", argv))
        return 0

    def fake_run_interactive(self, argv):
        dispatched.append(("run_interactive", argv))
        return 0

    monkeypatch.setattr(
        "comicmeta._executors.rsync.RsyncExecutor.run", fake_run
    )
    monkeypatch.setattr(
        "comicmeta._executors.rsync.RsyncExecutor.run_interactive", fake_run_interactive
    )
    monkeypatch.setattr(
        "comicmeta._executors.rsync.RsyncExecutor.sync_source",
        lambda self: (True, "synced"),
    )
    # Pretend stdin is a TTY
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    with pytest.raises(SystemExit) as exc:
        main(["--context", "nas", "browse", "--source", str(tmp_path)])
    assert exc.value.code == 0
    assert len(dispatched) == 1
    assert dispatched[0][0] == "run_interactive"


def test_cli_dispatches_write_interactive_with_tty(mock_contexts_dir, monkeypatch, tmp_path):
    """`write` needs a TTY so its remote confirmation prompt can render from
    the dashboard; it must dispatch via run_interactive (ssh -t), not run."""
    root = mock_contexts_dir.parent
    monkeypatch.setenv("XDG_CONFIG_HOME", str(root))
    _context.save_context({
        "name": "nas",
        "host": "h",
        "ssh_user": "u",
        "library_path": "/p",
        "exec": "rsync",
    })
    _context.set_active_context("nas")
    dispatched = []

    def fake_run(self, argv):
        dispatched.append(("run", argv))
        return 0

    def fake_run_interactive(self, argv):
        dispatched.append(("run_interactive", argv))
        return 0

    monkeypatch.setattr(
        "comicmeta._executors.rsync.RsyncExecutor.run", fake_run
    )
    monkeypatch.setattr(
        "comicmeta._executors.rsync.RsyncExecutor.run_interactive", fake_run_interactive
    )
    monkeypatch.setattr(
        "comicmeta._executors.rsync.RsyncExecutor.sync_source",
        lambda self: (True, "synced"),
    )
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    with pytest.raises(SystemExit) as exc:
        main(["--context", "nas", "write", "--source", str(tmp_path)])
    assert exc.value.code == 0
    assert len(dispatched) == 1
    assert dispatched[0][0] == "run_interactive"
    assert "write" in dispatched[0][1]


def test_cli_bare_invocation_runs_dashboard_locally(mock_contexts_dir, monkeypatch):
    """`comicmeta -c nas` (no subcommand) opens the dashboard here, targeting
    the chosen context; it must NOT dispatch the TUI to the NAS."""
    root = mock_contexts_dir.parent
    monkeypatch.setenv("XDG_CONFIG_HOME", str(root))
    _context.save_context({
        "name": "nas",
        "host": "h",
        "ssh_user": "u",
        "library_path": "/p",
        "exec": "rsync",
    })
    _context.set_active_context("nas")
    dispatched = []

    def fake_run(self, argv):
        dispatched.append(("run", argv))
        return 0

    def fake_run_interactive(self, argv):
        dispatched.append(("run_interactive", argv))
        return 0

    monkeypatch.setattr(
        "comicmeta._executors.rsync.RsyncExecutor.run", fake_run
    )
    monkeypatch.setattr(
        "comicmeta._executors.rsync.RsyncExecutor.run_interactive", fake_run_interactive
    )
    monkeypatch.setattr(
        "comicmeta._executors.rsync.RsyncExecutor.sync_source",
        lambda self: (True, "synced"),
    )
    calls = []
    monkeypatch.setattr(
        "comicmeta.cli.interactive_dashboard",
        lambda parser, initial_context=None: calls.append(initial_context) or 0,
    )
    monkeypatch.setattr("comicmeta.cli.is_interactive", lambda: True)
    with pytest.raises(SystemExit) as exc:
        main(["--context", "nas"])
    assert exc.value.code == 0
    assert dispatched == []
    assert calls == ["nas"]


def test_cli_context_commands_skip_executor(mock_contexts_dir, monkeypatch, capsys):
    """Context subcommands should not trigger executor dispatch."""
    root = mock_contexts_dir.parent
    monkeypatch.setenv("XDG_CONFIG_HOME", str(root))
    _context.save_context({
        "name": "nas",
        "host": "h",
        "ssh_user": "u",
        "library_path": "/p",
        "exec": "rsync",
    })
    _context.set_active_context("nas")
    dispatched = []

    def fake_run(self, argv):
        dispatched.append(("run", argv))
        return 0

    monkeypatch.setattr(
        "comicmeta._executors.rsync.RsyncExecutor.run", fake_run
    )
    # context ls should work locally, not via executor
    main(["context", "ls"])
    assert len(dispatched) == 0


# ─── SSH connection settings ───


def test_ssh_flags_empty_by_default(nas_context):
    ex = RsyncExecutor(nas_context)
    assert ex._ssh_flags() == ["-o", f"ConnectTimeout={DEFAULT_CONNECT_TIMEOUT}"]


def test_ssh_flags_include_port_and_identity(nas_context):
    nas_context["ssh_port"] = 2222
    nas_context["identity_file"] = "~/.ssh/id_ed25519"
    ex = RsyncExecutor(nas_context)
    assert ex._ssh_flags() == [
        "-p", "2222", "-i", "~/.ssh/id_ed25519",
        "-o", f"ConnectTimeout={DEFAULT_CONNECT_TIMEOUT}",
    ]


def test_ssh_flags_skip_default_port(nas_context):
    nas_context["ssh_port"] = 22
    nas_context["identity_file"] = ""
    ex = RsyncExecutor(nas_context)
    assert ex._ssh_flags() == ["-o", f"ConnectTimeout={DEFAULT_CONNECT_TIMEOUT}"]


def test_ssh_flags_honor_connect_timeout(nas_context):
    nas_context["connect_timeout"] = 3
    ex = RsyncExecutor(nas_context)
    assert ex._ssh_flags() == ["-o", "ConnectTimeout=3"]


def test_ssh_flags_fall_back_on_bad_connect_timeout(nas_context):
    nas_context["connect_timeout"] = "soon"
    ex = RsyncExecutor(nas_context)
    assert ex._ssh_flags() == ["-o", f"ConnectTimeout={DEFAULT_CONNECT_TIMEOUT}"]


def test_run_ssh_uses_context_flags(nas_context, monkeypatch):
    nas_context["ssh_port"] = 2222
    nas_context["identity_file"] = "/keys/id_rsa"
    ex = RsyncExecutor(nas_context)
    cmd = []
    monkeypatch.setattr("subprocess.run", lambda c, **kw: cmd.append(c) or __import__("subprocess").CompletedProcess(c, 0))
    ex._run_ssh([], ["python3", "--version"])
    assert cmd[0][0] == "ssh"
    assert "-p" in cmd[0]
    assert "2222" in cmd[0]
    assert "-i" in cmd[0]
    assert "/keys/id_rsa" in cmd[0]
    assert "alice@nas.example.com" in cmd[0]


def test_run_ssh_explains_connection_failure(nas_context, monkeypatch, capsys):
    ex = RsyncExecutor(nas_context)
    monkeypatch.setattr(
        "subprocess.run",
        lambda c, **kw: __import__("subprocess").CompletedProcess(c, 255),
    )

    assert ex._run_ssh([], ["python3", "--version"]) == 255
    assert "switch to `--context local`" in capsys.readouterr().err
