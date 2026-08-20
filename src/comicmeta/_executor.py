"""Abstract executor interface for NAS context command dispatch.

Executors translate local comicmeta commands into remote commands over SSH,
using either Docker or rsync-source as the execution method on the NAS.
"""

from __future__ import annotations

import abc
import os
import shlex
import subprocess
import sys

# Commands that accept `--source` and therefore get the NAS library path
# injected by `_prepare_argv`. Commands not listed here (setup, review-volumes,
# map, …) take the library from context/state files and would reject --source.
_SOURCE_COMMANDS = {
    "backups", "browse", "convert", "covers", "discover", "flags", "health",
    "inspect", "missing", "organize", "review", "self-test", "settings",
    "stage", "status", "validate", "write",
}


class Executor(abc.ABC):
    """Base class for NAS command executors."""

    def __init__(self, context) -> None:
        from comicmeta._context import Context
        self.context = Context.from_mapping(context)

    @abc.abstractmethod
    def run(self, argv: list[str]) -> int:
        """Run a headless command on the NAS. Return exit code."""

    @abc.abstractmethod
    def run_interactive(self, argv: list[str]) -> int:
        """Run an interactive command on the NAS. Return exit code."""

    def _ssh_target(self) -> str:
        return self.context.ssh_target()

    def _ssh_flags(self) -> list[str]:
        """Extra ssh flags from context: custom port and identity file."""
        return self.context.ssh_flags()

    def _prepare_argv(self, argv: list[str]) -> list[str]:
        """Replace local --source with the NAS library path, or append it.

        Also points commands that read an API key at the context's
        `key_location` on the NAS, so a stored key is actually used.
        """
        result: list[str] = []
        skip_next = False
        # Only inject --source for commands that accept it: a bare invocation
        # (`comicmeta -c nas`) opens the dashboard (no --source), and commands
        # like setup/review-volumes would reject it as an unrecognized argument.
        command = next((a for a in argv if not a.startswith("-")), "")
        inject_source = command in _SOURCE_COMMANDS
        for i, arg in enumerate(argv):
            if skip_next:
                skip_next = False
                continue
            if inject_source and arg in ("--source", "-s") and i + 1 < len(argv):
                skip_next = True
                result.extend([arg, self.context.library_path])
            else:
                result.append(arg)
        if inject_source and not any(r in ("--source", "-s") for r in result):
            result.extend(["--source", self.context.library_path])
        if (
            self.context.key_location
            and command in ("discover", "review", "fetch-issues")
            and "--api-key-file" not in result
        ):
            result.extend(["--api-key-file", self.context.key_location])
        return result

    @staticmethod
    def _shell_cmd(parts: list[str]) -> str:
        """Join command parts for remote shell execution.

        Tokens starting with ``~/`` or ``PYTHONPATH=~/`` are left unquoted so
        the remote shell expands ``~`` to the user's home directory. All other
        tokens are shlex-quoted.
        """
        tokens = []
        for part in parts:
            if (
                part.startswith("~/")
                or part.startswith("PYTHONPATH=~/")
                or part.startswith("XDG_CONFIG_HOME=~/")
            ):
                tokens.append(part)
            else:
                tokens.append(shlex.quote(part))
        return " ".join(tokens)

    def _run_ssh(self, ssh_flags: list[str], remote_parts: list[str]) -> int:
        """Run an SSH command locally, streaming stdout/stderr."""
        cmd = ["ssh"] + self._ssh_flags() + ssh_flags + [self._ssh_target(), self._shell_cmd(remote_parts)]
        # `ssh -t` allocates a pty, so the remote command's stderr reports as a
        # TTY and comicmeta would animate its spinners in place. Those `\r\x1b[K`
        # redraws get captured as a scrollback flood over SSH, so suppress
        # animation for the remote process.
        env = os.environ.copy()
        if "-t" in ssh_flags:
            env["COMICMETA_NO_ANIMATION"] = "1"
        try:
            result = subprocess.run(cmd, env=env)
        except FileNotFoundError:
            print("ERROR: ssh not found; is it installed?", file=sys.stderr)
            return 1
        except OSError as exc:
            print(f"ERROR: failed to run ssh: {exc}", file=sys.stderr)
            return 1
        if result.returncode == 255:
            print(
                f"ERROR: could not reach NAS context {self.context.name!r} "
                f"({self._ssh_target()}); check SSH access or switch to `--context local`.",
                file=sys.stderr,
            )
        return result.returncode

    @staticmethod
    def _run_rsync(cmd: list[str], timeout: int) -> tuple[bool, str]:
        """Run an rsync command and map failures to (ok, message).

        Shared envelope for both executors' source-sync / image-build steps
        so the FileNotFoundError/TimeoutExpired/Exception cascade lives once.
        """
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except FileNotFoundError:
            return False, "rsync not found; is it installed?"
        except subprocess.TimeoutExpired:
            return False, f"rsync timed out after {timeout}s"
        except Exception as exc:
            return False, f"rsync failed: {exc}"
        if result.returncode != 0:
            return False, result.stderr.strip() or f"rsync exit {result.returncode}"
        return True, ""
