import io
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from comicmeta import _context
from comicmeta.cli import build_parser, main

SRC = Path(__file__).resolve().parents[1] / "src"


@pytest.fixture
def mock_contexts_dir(tmp_path, monkeypatch):
    """Redirect contexts and active-context files into a temporary directory."""
    root = tmp_path / "comicmeta"
    root.mkdir()
    monkeypatch.setattr(_context, "contexts_dir", lambda: root / "contexts")
    monkeypatch.setattr(
        _context, "_active_path", lambda: root / "active_context"
    )
    return root


def run_cli(*args, xdg_config_home=None):
    """Run comicmeta CLI in a subprocess with optional XDG_CONFIG_HOME override."""
    env = {**os.environ.copy(), "PYTHONPATH": str(SRC)}
    if xdg_config_home is not None:
        env["XDG_CONFIG_HOME"] = str(xdg_config_home)
    return subprocess.run(
        [sys.executable, "-m", "comicmeta", *map(str, args)],
        capture_output=True,
        text=True,
        env=env,
    )


# ─── Core storage tests ───


def test_local_context_is_implicit(mock_contexts_dir):
    assert _context.load_context("local") == _context._local_context()
    assert _context.active_context()["name"] == "local"


def test_save_and_load_roundtrip(mock_contexts_dir):
    ctx = {
        "name": "nas",
        "host": "nas.example.com",
        "ssh_user": "alice",
        "library_path": "/srv/comics",
        "exec": "rsync",
        "image": "comicmeta:latest",
        "nas_src": "~/comicmeta",
    }
    _context.save_context(ctx)
    loaded = _context.load_context("nas")
    expected = {
        **_context._local_context(),
        **ctx,
        "config_dir": _context.DEFAULT_CONFIG_DIR,  # NAS-context default applied on load
    }
    # Context is a Mapping; compare via dict() since Context==dict is False by design.
    assert dict(loaded) == expected


def test_apply_nas_defaults_fills_blank_paths(mock_contexts_dir):
    """A bare NAS Context gets real nas_src/config_dir/key_location defaults."""
    from comicmeta._context import Context
    ctx = Context(name="lan", host="h", ssh_user="u", library_path="/p", exec="rsync")
    ctx.apply_nas_defaults()
    assert ctx.nas_src == _context.DEFAULT_NAS_SRC
    assert ctx.config_dir == _context.DEFAULT_CONFIG_DIR
    assert ctx.key_location == _context.DEFAULT_KEY_LOCATION
    assert ctx.image == _context.DEFAULT_IMAGE


def test_apply_nas_defaults_preserves_set_values(mock_contexts_dir):
    """apply_nas_defaults never overwrites explicitly configured paths."""
    from comicmeta._context import Context
    ctx = Context(
        name="lan", host="h", ssh_user="u", library_path="/p", exec="rsync",
        nas_src="/data/comicmeta", config_dir="/data/.config/comicmeta",
        key_location="/data/.config/comicmeta/comicvine.key",
    )
    ctx.apply_nas_defaults()
    assert ctx.nas_src == "/data/comicmeta"
    assert ctx.config_dir == "/data/.config/comicmeta"
    assert ctx.key_location == "/data/.config/comicmeta/comicvine.key"


def test_list_contexts_sorted(mock_contexts_dir):
    for name in ("beta", "alpha", "gamma"):
        _context.save_context({
            "name": name,
            "host": "h",
            "ssh_user": "u",
            "library_path": "/p",
        })
    names = [c["name"] for c in _context.list_contexts()]
    assert names == ["alpha", "beta", "gamma"]


def test_set_active_context(mock_contexts_dir):
    _context.save_context({
        "name": "nas",
        "host": "h",
        "ssh_user": "u",
        "library_path": "/p",
    })
    _context.set_active_context("nas")
    assert _context.active_context()["name"] == "nas"


def test_set_active_context_to_local_clears_file(mock_contexts_dir):
    _context.save_context({
        "name": "nas",
        "host": "h",
        "ssh_user": "u",
        "library_path": "/p",
    })
    _context.set_active_context("nas")
    _context.set_active_context("local")
    assert _context.active_context()["name"] == "local"
    assert not _context._active_path().exists()


def test_remove_context_deletes_file_and_clears_active(mock_contexts_dir):
    _context.save_context({
        "name": "nas",
        "host": "h",
        "ssh_user": "u",
        "library_path": "/p",
    })
    _context.set_active_context("nas")
    assert _context.remove_context("nas") is True
    assert _context.load_context("nas") is None
    assert _context.active_context()["name"] == "local"


def test_remove_context_returns_false_when_missing(mock_contexts_dir):
    assert _context.remove_context("missing") is False


def test_cannot_remove_local_context(mock_contexts_dir):
    with pytest.raises(SystemExit):
        _context.remove_context("local")


def test_cannot_save_local_context_name(mock_contexts_dir):
    with pytest.raises(SystemExit):
        _context.save_context({
            "name": "local",
            "host": "h",
            "ssh_user": "u",
            "library_path": "/p",
        })


def test_validation_missing_host(mock_contexts_dir):
    with pytest.raises(SystemExit):
        _context.save_context({
            "name": "nas",
            "host": "",
            "ssh_user": "u",
            "library_path": "/p",
        })


def test_validation_bad_exec(mock_contexts_dir):
    with pytest.raises(SystemExit):
        _context.save_context({
            "name": "nas",
            "host": "h",
            "ssh_user": "u",
            "library_path": "/p",
            "exec": "bad",
        })


def test_toml_roundtrip_defaults(mock_contexts_dir):
    ctx = {
        "name": "nas",
        "host": "nas.example.com",
        "ssh_user": "alice",
        "library_path": "/srv/comics",
    }
    _context.save_context(ctx)
    loaded = _context.load_context("nas")
    assert loaded["exec"] == "rsync"
    assert loaded["image"] == "comicmeta:latest"
    assert loaded["nas_src"] == "~/comicmeta"


# ─── CLI tests ───


def test_cli_context_add_flags(mock_contexts_dir):
    root = mock_contexts_dir.parent
    result = run_cli(
        "context", "add", "nas",
        "--host", "nas.example.com",
        "--ssh-user", "alice",
        "--library-path", "/srv/comics",
        "--exec", "rsync",
        xdg_config_home=root,
    )
    assert result.returncode == 0, result.stderr
    assert "Context 'nas' created" in result.stdout
    ctx = _context.load_context("nas")
    assert ctx is not None
    assert ctx["host"] == "nas.example.com"


def test_cli_context_ls(mock_contexts_dir):
    root = mock_contexts_dir.parent
    _context.save_context({
        "name": "nas",
        "host": "h",
        "ssh_user": "u",
        "library_path": "/p",
    })
    _context.set_active_context("nas")
    result = run_cli("context", "ls", xdg_config_home=root)
    assert result.returncode == 0, result.stderr
    assert "Active: nas" in result.stdout
    assert "▸ nas" in result.stdout


def test_cli_context_ls_json(mock_contexts_dir):
    import json
    root = mock_contexts_dir.parent
    _context.save_context({
        "name": "nas",
        "host": "h",
        "ssh_user": "u",
        "library_path": "/p",
    })
    _context.set_active_context("nas")
    result = run_cli("context", "ls", "--json", xdg_config_home=root)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["active"] == "nas"
    assert payload["contexts"][0]["name"] == "nas"
    assert payload["contexts"][0]["host"] == "h"


def test_cli_context_use(mock_contexts_dir):
    root = mock_contexts_dir.parent
    _context.save_context({
        "name": "nas",
        "host": "h",
        "ssh_user": "u",
        "library_path": "/p",
    })
    result = run_cli("context", "use", "nas", xdg_config_home=root)
    assert result.returncode == 0, result.stderr
    assert _context.active_context()["name"] == "nas"


def test_cli_context_edit(mock_contexts_dir):
    root = mock_contexts_dir.parent
    _context.save_context({
        "name": "nas",
        "host": "old",
        "ssh_user": "u",
        "library_path": "/p",
    })
    result = run_cli("context", "edit", "nas", "--host", "new", xdg_config_home=root)
    assert result.returncode == 0, result.stderr
    assert _context.load_context("nas")["host"] == "new"


def test_cli_context_remove(mock_contexts_dir):
    root = mock_contexts_dir.parent
    _context.save_context({
        "name": "nas",
        "host": "h",
        "ssh_user": "u",
        "library_path": "/p",
    })
    result = run_cli("context", "remove", "nas", xdg_config_home=root)
    assert result.returncode == 0, result.stderr
    assert _context.load_context("nas") is None


def test_cli_context_not_found(mock_contexts_dir):
    root = mock_contexts_dir.parent
    result = run_cli("context", "use", "missing", xdg_config_home=root)
    assert result.returncode == 1
    assert "context not found" in result.stderr


# ─── --context flag tests ───


def test_context_flag_missing_context(mock_contexts_dir):
    root = mock_contexts_dir.parent
    result = run_cli("--context", "missing", "inspect", "--quick", xdg_config_home=root)
    assert result.returncode == 1
    assert "context not found: missing" in result.stderr


def test_context_commands_work_when_nas_active(mock_contexts_dir):
    """Context subcommands themselves should not be blocked by active NAS context."""
    root = mock_contexts_dir.parent
    _context.save_context({
        "name": "nas",
        "host": "h",
        "ssh_user": "u",
        "library_path": "/p",
    })
    _context.set_active_context("nas")
    result = run_cli("context", "ls", xdg_config_home=root)
    assert result.returncode == 0, result.stderr
    assert "Active: nas" in result.stdout


def test_local_context_no_warning(mock_contexts_dir, tmp_path):
    """Local default context should not trigger any NAS warning."""
    root = mock_contexts_dir.parent
    # Create a fake library so inspect doesn't die on missing source
    (tmp_path / "Marvel").mkdir()
    result = run_cli("inspect", "--quick", "--source", str(tmp_path), xdg_config_home=root)
    # inspect --quick on empty dir returns 0
    assert result.returncode == 0, result.stderr
    assert "NAS context" not in result.stderr


def test_context_add_interactive_prompts(mock_contexts_dir, monkeypatch, capsys):
    """Interactive context add prompts for fields when not provided via flags."""
    root = mock_contexts_dir.parent
    monkeypatch.setenv("XDG_CONFIG_HOME", str(root))
    call_count = 0
    responses = iter([
        "nas", "nas.example.com", "alice", "/srv/comics",
        "22", "", "10", "my-api-key",
    ])

    def fake_prompt(prompt_text, current="", secret=False):
        nonlocal call_count
        call_count += 1
        return next(responses)

    monkeypatch.setattr("comicmeta._commands.context.prompt_edit", fake_prompt)
    monkeypatch.setattr("builtins.input", lambda _: "2")
    # Mock connection test and API key write to avoid real SSH
    monkeypatch.setattr(_context, "test_connection", lambda ctx: (True, "Python 3.11.9"))
    monkeypatch.setattr(
        "comicmeta._commands.context._write_api_key_to_nas",
        lambda ctx, key: (True, "saved")
    )
    main(["context", "add"])
    captured = capsys.readouterr()
    assert "Context 'nas' created" in captured.out
    assert call_count == 8
    ctx = _context.load_context("nas")
    assert ctx is not None
    assert ctx["host"] == "nas.example.com"
    assert ctx["exec"] == "rsync"
