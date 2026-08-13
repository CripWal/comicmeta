"""Rsync-source executor — runs comicmeta via the NAS's system Python.

No Docker required. The comicmeta source files must be present on the NAS at
the configured ``nas_src`` path (default ``~/comicmeta``). Interactive commands
use ``ssh -t`` so the TTY is forwarded to the NAS.
"""

from __future__ import annotations

import os
import subprocess
import sys

from comicmeta._executor import Executor


class RsyncExecutor(Executor):
    def run(self, argv: list[str]) -> int:
        remote_argv = self._prepare_argv(argv)
        remote_parts = [
            f"PYTHONPATH={self.context.nas_src}",
            f"XDG_CONFIG_HOME={self._xdg_base()}",
            "python3", "-m", "comicmeta",
            # Run directly on the NAS; never re-dispatch through whatever the
            # NAS's own active context happens to be.
            "--context", "local",
        ] + remote_argv
        return self._run_ssh([], remote_parts)

    def run_interactive(self, argv: list[str]) -> int:
        remote_argv = self._prepare_argv(argv)
        remote_parts = [
            f"PYTHONPATH={self.context.nas_src}",
            f"XDG_CONFIG_HOME={self._xdg_base()}",
            "python3", "-m", "comicmeta",
            "--context", "local",
        ] + remote_argv
        return self._run_ssh(["-t"], remote_parts)

    def _xdg_base(self) -> str:
        """XDG base dir whose `comicmeta/` subdir is the config root.

        comicmeta appends `/comicmeta` to XDG_CONFIG_HOME, so the config root
        (`~/.config/comicmeta`) maps to XDG base `~/.config`.
        """
        config_dir = self.context.config_dir or "~/.config/comicmeta"
        return os.path.dirname(config_dir) or "~/.config"

    def sync_source(self) -> tuple[bool, str]:
        """Rsync the local comicmeta package to a `comicmeta/` subdir of nas_src."""
        import importlib
        import os

        mod = importlib.import_module("comicmeta")
        src = mod.__path__[0]  # .../src/comicmeta
        # The run() PYTHONPATH points at nas_src (the parent); the package
        # lands in a `comicmeta/` subdirectory there.
        base = self.context.nas_src or "~/comicmeta"
        # rsync only creates the final target dir, not its parents, so make
        # sure nas_src exists first (it may not on a brand-new NAS).
        if self._run_ssh([], ["mkdir", "-p", base]) != 0:
            return False, f"could not create {base} on {self._ssh_target()}"
        target = f"{self._ssh_target()}:{base}/comicmeta/"
        cmd = [
            "rsync", "-az", "--delete",
            "-e", "ssh",
            src + "/", target,
        ]
        ok, msg = self._run_rsync(cmd, 60)
        if not ok:
            return False, msg
        return True, f"synced {src} → {target}"
