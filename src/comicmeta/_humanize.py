"""Human-readable durations and sizes (pretty-ms / pretty-bytes style)."""

from __future__ import annotations

_DURATION_UNITS = (
    (1.0, "s"),
    (60.0, "m"),
    (3600.0, "h"),
    (86400.0, "d"),
)


def pretty_duration(seconds: float) -> str:
    """Format a duration in seconds as a compact human string."""
    if seconds is None:
        return "—"
    if seconds < 1.0:
        return f"{seconds * 1000:.0f}ms"
    if seconds < 60.0:
        return f"{seconds:.1f}s"
    if seconds < 3600.0:
        return f"{seconds / 60.0:.0f}m"
    if seconds < 86400.0:
        return f"{seconds / 3600.0:.0f}h"
    return f"{seconds / 86400.0:.0f}d"


def pretty_bytes(size: int) -> str:
    """Format a byte count as a compact human string (binary units)."""
    if size is None:
        return "—"
    if size < 1024:
        return f"{size} B"
    value = float(size)
    for unit in ("KiB", "MiB", "GiB", "TiB"):
        value /= 1024.0
        if value < 1024:
            if value < 10:
                return f"{value:.1f} {unit}"
            return f"{value:.0f} {unit}"
    return f"{value:.0f} PiB"
