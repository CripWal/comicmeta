"""Shared constants and helpers used across comicmeta subcommands."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REQUIRED_FIELDS = ("series", "volume", "number", "year", "format")
COMICINFO_FIELDS = (
    "series", "series_sort", "localized_series", "number", "count", "volume",
    "year", "month", "day", "format", "title", "publisher", "imprint",
    "writer", "penciller", "inker", "colorist", "letterer", "cover_artist", "editor",
    "genre", "tags", "characters", "teams", "locations", "story_arc", "story_arc_number",
    "summary", "notes", "web", "age_rating",
)
PROVENANCE_FIELDS = (
    "comicvine_issue_id", "comicvine_volume_id", "comicvine_url",
    "cover_url", "cover_width", "cover_height",
)
ALLOWED_FIELDS = COMICINFO_FIELDS + PROVENANCE_FIELDS


_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    """Return ``text`` with ANSI SGR escape sequences removed."""
    return _ANSI_ESCAPE.sub("", text)


def _truncate_ansi(text: str, width: int) -> str:
    """Truncate a (possibly ANSI-colored) line to ``width`` visible columns.

    ANSI escape sequences are preserved but don't count toward the width; when
    the visible text is longer than ``width`` it is cut and an ellipsis appended
    inside the last color span, so the border never overflows on narrow terms.
    """
    if len(_strip_ansi(text)) <= width:
        return text
    if width <= 0:
        return ""
    result: list[str] = []
    visible = 0
    ellipsis = "…"
    for char in text:
        if char == "\x1b":
            result.append(char)
            continue
        if visible >= width - len(ellipsis):
            if visible < width:
                result.append(ellipsis)
                visible = width
            continue
        result.append(char)
        visible += 1
    return "".join(result)


def _terminal_size(fallback=(80, 24)) -> tuple[int, int]:
    """Return (columns, rows), tolerating os.terminal_size and test mocks."""
    size = shutil.get_terminal_size(fallback)
    try:
        return size.columns, size.lines
    except AttributeError:
        return size[0], size[1]


def serialize_multi(value: object) -> str:
    """Serialize ComicInfo multi-value fields with the schema delimiter."""
    if isinstance(value, (list, tuple, set)):
        return ";".join(str(item).strip() for item in value if str(item).strip())
    return str(value).strip() if value is not None else ""


def die(message: str) -> "NoReturn":
    try:
        from comicmeta._spinner import clear_active_spinner
        clear_active_spinner()
    except ImportError:
        pass
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_json(path: Path, label: str = "file") -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"{label} not found: {path}")
    except json.JSONDecodeError as error:
        raise SystemExit(f"Invalid JSON {path}: {error}")


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        temporary = Path(handle.name)
    try:
        try:
            os.replace(temporary, path)
        except OSError as error:
            if error.errno not in (22, 5, 16, 35):
                raise
            shutil.copyfile(temporary, path)
            temporary.unlink(missing_ok=True)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    path.chmod(0o644)


def atomic_json(path: Path, value: dict) -> None:
    value["updated_at"] = datetime.now(timezone.utc).isoformat()
    atomic_write(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def color_enabled(args=None, *, stream=None) -> bool:
    """Whether ANSI color should be used.

    Disabled when: stdout is not a TTY, NO_COLOR is set (non-empty), TERM is
    ``dumb``, or the command's ``--no-color`` flag was passed.
    """
    import os
    import sys
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("TERM") == "dumb":
        return False
    if getattr(args, "no_color", False):
        return False
    if stream is None:
        stream = sys.stdout
    return stream.isatty()


DEFAULT_THEME = "classic"

# Comic-themed palettes. Each slot maps to an ANSI SGR sequence body used by
# Palette (e.g. "31" red or "38;5;196" 256-color bright red). Keep slot roles
# stable (title/good/warn/muted/path) so a theme swap never breaks semantics.
THEMES = {
    "classic": {"title": "36", "good": "32", "warn": "33", "muted": "2", "path": "35"},
    "marvel": {"title": "38;5;196", "good": "38;5;118", "warn": "38;5;220", "muted": "2", "path": "38;5;75"},
    "dc": {"title": "38;5;39", "good": "38;5;155", "warn": "38;5;208", "muted": "2", "path": "38;5;81"},
    "noir": {"title": "1;37", "good": "38;5;250", "warn": "38;5;245", "muted": "2", "path": "38;5;244"},
    "technicolor": {"title": "38;5;207", "good": "38;5;82", "warn": "38;5;226", "muted": "2", "path": "38;5;51"},
    "beige": {"title": "38;5;180", "good": "38;5;107", "warn": "38;5;179", "muted": "2", "path": "38;5;137"},
    "bookshelf": {"title": "38;5;94", "good": "38;5;148", "warn": "38;5;172", "muted": "2", "path": "38;5;61"},
}

# True-color RGB accent per theme for the logo fill. The wordmark is rendered
# as a vertical (top-down) gradient in that single hue: light tint at the top
# deepening to the base accent at the bottom, so the fill matches the theme
# rather than sweeping a rainbow across the letters.
_LOGO_BASE = {
    "classic": (0, 160, 200),
    "marvel": (230, 40, 60),
    "dc": (20, 110, 240),
    "noir": (200, 200, 200),
    "technicolor": (200, 40, 160),
    "beige": (190, 150, 90),
    "bookshelf": (160, 100, 40),
}

_ACTIVE_THEME = DEFAULT_THEME


def set_theme(name: str) -> None:
    """Set the process-wide palette theme by name (falls back to classic)."""
    global _ACTIVE_THEME
    _ACTIVE_THEME = name if name in THEMES else DEFAULT_THEME


def active_theme() -> str:
    return _ACTIVE_THEME


class Palette:
    """Shared ANSI styling. Semantic slots only: one accent + neutrals.

    Colors come from the active theme (classic by default; marvel, dc, noir,
    technicolor, beige, bookshelf are built in). Red is reserved for failure,
    never decoration.
    """

    def __init__(self, enabled: bool, theme: str | None = None) -> None:
        self.enabled = enabled
        self.colors = THEMES.get(theme or _ACTIVE_THEME, THEMES[DEFAULT_THEME])

    def paint(self, code: str, value: object) -> str:
        text = str(value)
        return f"\033[{code}m{text}\033[0m" if self.enabled else text

    def title(self, value: object) -> str:
        return self.paint(self.colors["title"], value)

    def bold(self, value: object) -> str:
        return self.paint("1", value)

    def good(self, value: object) -> str:
        return self.paint(self.colors["good"], value)

    def warn(self, value: object) -> str:
        return self.paint(self.colors["warn"], value)

    def muted(self, value: object) -> str:
        return self.paint(self.colors["muted"], value)

    def path(self, value: object) -> str:
        return self.paint(self.colors["path"], value)

    def reverse(self, value: object) -> str:
        return self.paint("7", value)


WORDMARK = r"""▞▀▖       ▗    ▙▗▌   ▐     
▌  ▞▀▖▛▚▀▖▄ ▞▀▖▌▘▌▞▀▖▜▀ ▝▀▖
▌ ▖▌ ▌▌▐ ▌▐ ▌ ▖▌ ▌▛▀ ▐ ▖▞▀▌
▝▀ ▝▀ ▘▝ ▘▀▘▝▀ ▘ ▘▝▀▘ ▀ ▝▀▘"""

PIPELINE = [
    ("1 discover", "Query ComicVine · writes candidates.json"),
    ("2 review-volumes", "Choose the right volume for each series"),
    ("3 fetch-issues", "Pull issue-level data for selected volumes"),
    ("4 review-issues", "Approve ComicInfo fields per file"),
    ("5 map", "Emit a CBZ-only writer mapping"),
    ("6 stage", "Copy reviewed CBZ files into an empty staging root"),
    ("7 validate", "Check staged writes against production hashes"),
    ("8 write", "Insert ComicInfo.xml · reviewed mapping + backup only"),
]

PIPELINE_CHAIN = " → ".join((
    "discover", "review-volumes", "fetch-issues", "review-issues",
    "map", "stage", "validate", "write",
))


def render_wordmark(colors: "Palette") -> str:
    """The comicmeta wordmark as a filled theme-colored gradient.

    Each character is painted with the theme's accent hue, interpolated
    vertically (top-down): a light tint at the top row deepening to the full
    accent at the bottom. Falls back to plain text when colors are off.
    """
    if not colors.enabled:
        return WORDMARK
    base = _LOGO_BASE.get(_ACTIVE_THEME, _LOGO_BASE[DEFAULT_THEME])
    rows = WORDMARK.splitlines()
    height = max(1, len(rows))

    def shade(rix: int) -> tuple[int, int, int]:
        # t=0 top (mix 40% white) → t=1 bottom (full accent).
        t = rix / max(1, height - 1)
        return tuple(round(base[i] + (255 - base[i]) * 0.4 * (1 - t)) for i in range(3))

    lines = []
    for rix, row in enumerate(rows):
        out = []
        r, g, b = shade(rix)
        for char in row:
            if char == " ":
                out.append(char)
            else:
                out.append(f"\033[38;2;{r};{g};{b}m{char}\033[0m")
        lines.append("".join(out))
    return "\n".join(lines)


def progress_bar(done: int, total: int, width: int = 20) -> str:
    """Solid-bar progress: `█` filled, `·` empty. No dithered glyphs."""
    if total <= 0:
        ratio = 0.0
    else:
        ratio = min(1.0, max(0.0, done / total))
    filled = round(width * ratio)
    return "█" * filled + "·" * (width - filled)


def add_examples(parser, lines: list[str]) -> None:
    """Attach `examples` epilog lines to a subcommand's argparse parser."""
    examples = "\n".join(f"  {line}" for line in lines)
    parser.epilog = f"examples:\n{examples}"
    if parser.formatter_class in (argparse.HelpFormatter, None):
        parser.formatter_class = argparse.RawDescriptionHelpFormatter


def require_tty(command: str, alternate: str) -> None:
    """Refuse interactive input when stdin is not a terminal, with a door."""
    from comicmeta._tui import is_no_input
    if is_no_input() or not sys.stdin.isatty():
        die(
            f"{command} needs an interactive terminal; "
            f"use `{alternate}` to run non-interactively"
        )
