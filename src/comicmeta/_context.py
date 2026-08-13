"""Context management for comicmeta — local default + opt-in NAS contexts.

Contexts are stored as individual TOML files under
`~/.config/comicmeta/contexts/<name>.toml`. The active context is tracked in
`~/.config/comicmeta/active_context` (plain text, just the name). The local
context is implicit and never stored on disk.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from pathlib import Path

from comicmeta._common import die

CONTEXTS_DIR_NAME = "contexts"
ACTIVE_FILE = "active_context"
LOCAL_CONTEXT_NAME = "local"

DEFAULT_EXEC = "rsync"
DEFAULT_IMAGE = "comicmeta:latest"
DEFAULT_NAS_SRC = "~/comicmeta"
DEFAULT_CONFIG_DIR = "~/.config/comicmeta"
DEFAULT_SSH_PORT = 22
DEFAULT_CONNECT_TIMEOUT = 10
DEFAULT_KEY_LOCATION = "~/.config/comicmeta/comicvine.key"

_VALID_EXEC = {"docker", "rsync"}

# Context fields shown in the settings panel, in order, with (label, kind, description).
# The description is the single source of truth — the settings panel reads from here
# rather than re-spelling prose inline (avoids Shotgun Surgery on field additions).
CONTEXT_FIELDS = (
    ("host", "Host", "str", "NAS hostname or IP address."),
    ("ssh_user", "SSH user", "str", "SSH username used to connect to the NAS."),
    ("ssh_port", "SSH port", "int", "SSH port (default 22)."),
    ("identity_file", "SSH identity file", "path", "Path to an SSH private key, if not the default."),
    ("connect_timeout", "SSH connect timeout (s)", "int", "Seconds to wait for the SSH connection to establish."),
    ("library_path", "Library path", "path", "Comic library path on the NAS."),
    ("key_location", "API key location", "path", "Where the ComicVine API key is stored on the NAS."),
    ("exec", "Execution method", "str", "How comicmeta runs on the NAS: rsync (source + NAS Python) or docker."),
    ("image", "Docker image", "str", "Docker image name to run, when exec is docker."),
    ("nas_src", "Source dir on NAS", "path", "Directory on the NAS where the comicmeta source is synced."),
    ("config_dir", "Config dir on NAS", "path", "Directory on the NAS holding comicmeta config + API key (default ~/.config/comicmeta)."),
)


def _field_names() -> set[str]:
    return {f.name for f in fields(Context)}


@dataclass
class Context(Mapping):
    """A comicmeta execution context — local default or opt-in NAS profile.

    Typed wrapper that replaces the loose ``dict`` plumbing: defaults live
    in one place (here), callers use attribute access (``ctx.host``), and the
    ``Mapping`` protocol keeps dict-style call sites (tests, legacy paths)
    working via ``ctx["host"]`` / ``ctx.get("ssh_port", 22)`` / ``{**ctx}``.
    """

    name: str = LOCAL_CONTEXT_NAME
    host: str = ""
    ssh_user: str = ""
    ssh_port: int = DEFAULT_SSH_PORT
    identity_file: str = ""
    connect_timeout: int = DEFAULT_CONNECT_TIMEOUT
    library_path: str = ""
    key_location: str = DEFAULT_KEY_LOCATION
    exec: str = ""
    image: str = ""
    nas_src: str = ""
    config_dir: str = ""
    # Ephemeral: carried from `context add` to the NAS-key write, never serialized.
    _api_key: str = field(default="", repr=False, compare=False)

    @classmethod
    def from_mapping(cls, data) -> "Context":
        """Build a Context from any Mapping (dict, Context, tomllib output)."""
        if isinstance(data, cls):
            return data
        names = _field_names()
        kwargs = {k: v for k, v in dict(data).items() if k in names}
        return cls(**kwargs)

    def to_dict(self) -> dict:
        """Serializable view (excludes the ephemeral _api_key)."""
        return {f.name: getattr(self, f.name) for f in fields(self) if f.name != "_api_key"}

    # ── SSH helpers (single source of truth for target + flags) ───────────────
    def apply_nas_defaults(self) -> "Context":
        """Fill NAS-context defaults that the dataclass leaves empty.

        Dataclass defaults are ``""`` so the implicit local context stays
        clean; any real NAS context must be run through this (or
        ``load_context``) so rsync/docker executors see real paths.
        """
        if not self.image:
            self.image = DEFAULT_IMAGE
        if not self.nas_src:
            self.nas_src = DEFAULT_NAS_SRC
        if not self.config_dir:
            self.config_dir = DEFAULT_CONFIG_DIR
        if not self.key_location:
            self.key_location = DEFAULT_KEY_LOCATION
        return self

    def ssh_target(self) -> str:
        return f"{self.ssh_user}@{self.host}"

    def ssh_flags(self) -> list[str]:
        flags: list[str] = []
        if self.ssh_port and int(self.ssh_port) != DEFAULT_SSH_PORT:
            flags += ["-p", str(self.ssh_port)]
        if self.identity_file:
            flags += ["-i", self.identity_file]
        return flags

    # ── Mapping protocol (back-compat for dict-style callers) ────────────────
    def __getitem__(self, key):
        try:
            return object.__getattribute__(self, key)
        except AttributeError:
            raise KeyError(key)

    def __iter__(self):
        return iter(self.to_dict())

    def __len__(self):
        return len(self.to_dict())

    def keys(self):
        return self.to_dict().keys()


class ContextError(Exception):
    """Raised for invalid context operations."""


def contexts_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "comicmeta" / CONTEXTS_DIR_NAME


def _context_path(name: str) -> Path:
    return contexts_dir() / f"{name}.toml"


def _active_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "comicmeta" / ACTIVE_FILE


def list_contexts() -> list[Context]:
    """Return all stored contexts, sorted by name."""
    directory = contexts_dir()
    if not directory.is_dir():
        return []
    contexts = []
    for path in sorted(directory.glob("*.toml")):
        name = path.stem
        ctx = load_context(name)
        if ctx is not None:
            contexts.append(ctx)
    return contexts


def load_context(name: str) -> Context | None:
    """Load a context by name, or None if it does not exist."""
    if name == LOCAL_CONTEXT_NAME:
        return _local_context()
    path = _context_path(name)
    if not path.is_file():
        return None
    try:
        with path.open("rb") as handle:
            import tomllib

            raw = tomllib.load(handle)
    except Exception as error:
        die(f"invalid context file {path}: {error}")
    raw.setdefault("name", name)
    ctx = Context.from_mapping(raw)
    # NAS-context defaults that aren't dataclass defaults (local context keeps "").
    ctx.apply_nas_defaults()
    return ctx


def _local_context() -> Context:
    return Context()


def active_context() -> Context:
    """Return the currently active context (local if none set or invalid)."""
    path = _active_path()
    if path.is_file():
        name = path.read_text(encoding="utf-8").strip()
        if name and name != LOCAL_CONTEXT_NAME:
            ctx = load_context(name)
            if ctx is not None:
                return ctx
    return _local_context()


def set_active_context(name: str) -> None:
    """Set the active context name. 'local' clears the active file."""
    if name == LOCAL_CONTEXT_NAME:
        _active_path().unlink(missing_ok=True)
        return
    if load_context(name) is None:
        die(f"context not found: {name}")
    path = _active_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(name + "\n", encoding="utf-8")


def save_context(ctx) -> None:
    """Write a context to disk. Overwrites if it exists. Accepts dict or Context."""
    ctx = Context.from_mapping(ctx)
    if not ctx.name:
        die("context name is required")
    if ctx.name == LOCAL_CONTEXT_NAME:
        die(f"'{LOCAL_CONTEXT_NAME}' is a reserved context name")
    _validate_context(ctx)
    path = _context_path(ctx.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_toml_for(ctx), encoding="utf-8")


def remove_context(name: str) -> bool:
    """Remove a context. Returns True if it existed. Clears active if it was active."""
    if name == LOCAL_CONTEXT_NAME:
        die(f"cannot remove the '{LOCAL_CONTEXT_NAME}' context")
    path = _context_path(name)
    existed = path.is_file()
    if existed:
        path.unlink()
    active = _active_path()
    if active.is_file() and active.read_text(encoding="utf-8").strip() == name:
        active.unlink(missing_ok=True)
    return existed


def test_connection(ctx, timeout: int | None = None) -> tuple[bool, str]:
    """Test SSH connectivity to the NAS and verify the exec method works.

    Returns (ok, message). For rsync, checks python3 is available.
    For docker, checks docker daemon is reachable. `timeout` overrides the
    context's connect_timeout (e.g. a short probe for the dashboard indicator).
    """
    import subprocess
    ctx = Context.from_mapping(ctx)
    timeout = ctx.connect_timeout if timeout is None else timeout
    ssh_cmd = ["ssh"] + ctx.ssh_flags() + [ctx.ssh_target()]
    if ctx.exec == "docker":
        ssh_cmd += ["docker --version"]
    else:
        ssh_cmd += ["python3 --version"]
    try:
        result = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return False, "ssh not found; is it installed?"
    except subprocess.TimeoutExpired:
        return False, f"connection timed out ({timeout}s)"
    except Exception as exc:
        return False, f"connection failed: {exc}"
    if result.returncode != 0:
        stderr = result.stderr.strip()
        if "Permission denied" in stderr:
            return False, "SSH permission denied; check your key with ssh-copy-id"
        if "docker" in stderr.lower() and "permission" in stderr.lower():
            return False, "Docker socket permission denied; user is not in docker group"
        if ctx.exec == "docker" and ("not found" in stderr or "No such file" in stderr):
            return False, "docker not found on NAS; choose rsync-source instead"
        return False, stderr or f"exit code {result.returncode}"
    stdout = result.stdout.strip()
    return True, stdout


def _validate_context(ctx: Context) -> None:
    for key in ("host", "ssh_user", "library_path"):
        if not getattr(ctx, key):
            die(f"context field '{key}' is required")
    if not ctx.exec:
        ctx.exec = DEFAULT_EXEC  # empty → default rsync (local context keeps "" since it's never validated)
    if ctx.exec not in _VALID_EXEC:
        die(f"context exec must be 'docker' or 'rsync', got: {ctx.exec}")
    try:
        port = int(ctx.ssh_port)
    except (TypeError, ValueError):
        die(f"context ssh_port must be an integer, got: {ctx.ssh_port!r}")
    if not 1 <= port <= 65535:
        die(f"context ssh_port must be between 1 and 65535, got: {port}")
    try:
        timeout = int(ctx.connect_timeout)
    except (TypeError, ValueError):
        die(f"context connect_timeout must be an integer, got: {ctx.connect_timeout!r}")
    if timeout <= 0:
        die(f"context connect_timeout must be positive, got: {timeout}")


def _toml_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return repr(str(value))


def _toml_for(ctx: Context) -> str:
    lines = ["# comicmeta context", ""]
    for f in fields(ctx):
        if f.name == "_api_key":
            continue
        value = getattr(ctx, f.name)
        if value not in (None, ""):
            lines.append(f"{f.name} = {_toml_value(value)}")
    return "\n".join(lines) + "\n"
