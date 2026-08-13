"""Docker executor — runs comicmeta in a container on the NAS.

Requires Docker daemon on the NAS and the SSH user to be in the docker group
(or have sudo access to docker). Builds the image from source on first use if
it is not already present.
"""

from __future__ import annotations

import subprocess
import sys

from comicmeta._executor import Executor


class DockerExecutor(Executor):
    def _config_mount(self) -> str:
        """Mount source for the container's /data/config directory."""
        config_dir = self.context.config_dir or "~/.config/comicmeta"
        return f"{config_dir}:/data/config"

    def run(self, argv: list[str]) -> int:
        remote_argv = self._prepare_argv(argv)
        remote_parts = [
            "docker", "run", "--rm",
            "-v", f"{self.context.library_path}:/comics",
            "-v", self._config_mount(),
            "-v", "~/.cache/comicmeta:/data/cache",
            self.context.image,
            "--context", "local",
        ] + remote_argv
        return self._run_ssh([], remote_parts)

    def run_interactive(self, argv: list[str]) -> int:
        remote_argv = self._prepare_argv(argv)
        remote_parts = [
            "docker", "run", "--rm", "-it",
            "-v", f"{self.context.library_path}:/comics",
            "-v", self._config_mount(),
            "-v", "~/.cache/comicmeta:/data/cache",
            self.context.image,
            "--context", "local",
        ] + remote_argv
        return self._run_ssh(["-t"], remote_parts)

    def build_image(self) -> tuple[bool, str]:
        """Rsync the repo root to the NAS and build the Docker image there."""
        import importlib
        import os
        import shlex

        mod = importlib.import_module("comicmeta")
        # The package dir is .../src/comicmeta; repo root is its grandparent
        repo_root = os.path.dirname(os.path.dirname(mod.__path__[0]))
        nas_build_dir = "~/comicmeta-docker"
        target = f"{self._ssh_target()}:{nas_build_dir}/"
        # Rsync repo root to NAS
        sync_cmd = [
            "rsync", "-az", "--delete",
            "-e", "ssh",
            "--exclude", ".git",
            "--exclude", "__pycache__",
            "--exclude", "*.pyc",
            repo_root + "/", target,
        ]
        ok, msg = self._run_rsync(sync_cmd, 120)
        if not ok:
            return False, msg
        # Build on the NAS
        image = self.context.image
        build_cmd = [
            "ssh", self._ssh_target(),
            f"cd {nas_build_dir} && docker build -t {image} .",
        ]
        try:
            result = subprocess.run(build_cmd, capture_output=True, text=True, timeout=300)
        except subprocess.TimeoutExpired:
            return False, "docker build timed out after 300s"
        except Exception as exc:
            return False, f"docker build failed: {exc}"
        if result.returncode != 0:
            stderr = result.stderr.strip()
            if "permission denied" in stderr.lower() and "docker" in stderr.lower():
                return False, "Docker socket permission denied; user is not in docker group. Switch to rsync-source with: comicmeta context edit <name> --exec rsync"
            return False, stderr or f"docker build exit {result.returncode}"
        return True, f"built {image} on NAS"
