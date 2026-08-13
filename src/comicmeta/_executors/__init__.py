"""Executor factory for NAS contexts."""

from __future__ import annotations

from comicmeta._executor import Executor
from comicmeta._executors.docker import DockerExecutor
from comicmeta._executors.rsync import RsyncExecutor


_EXECUTOR_CLASSES = {
    "docker": DockerExecutor,
    "rsync": RsyncExecutor,
}


def get_executor(context) -> Executor:
    """Return the appropriate executor for a context."""
    from comicmeta._context import Context
    context = Context.from_mapping(context)
    exec_method = context.exec or "rsync"
    cls = _EXECUTOR_CLASSES.get(exec_method)
    if cls is None:
        raise ValueError(f"unknown exec method: {exec_method}")
    return cls(context)
