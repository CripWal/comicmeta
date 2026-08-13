"""Cover preview helpers: extract and render comic covers in the terminal.

Rendering priority: iTerm2/Kitty/WezTerm inline-image escapes when available,
then the `timg` or `terminal-image-cli` true-color ANSI tools (these work in
plain terminals like Apple's Terminal.app), then a Pillow ASCII fallback.
Never reads more than the first image in a CBZ.
"""

from __future__ import annotations

import base64
import io
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

# The first page image is usually named 0000/0001 or similar; take the first
# image entry regardless of name.
_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif"}
_COVER_WORDS = ("cover", "front", "variant", "alternate", "alternate-cover", "alt")


def previews_enabled(source_root: Path | None = None) -> bool:
    if source_root is None:
        return True
    from comicmeta import _config
    return bool(_config.get(_config.load(source_root), "appearance.cover_previews"))


def _preference_path(source_root: Path) -> Path:
    from comicmeta import _config
    flat = _config.load(source_root)
    return Path(_config.get(flat, "paths.cover_state"))


def image_entries(path: Path) -> list[tuple[str, bytes, str]]:
    """Return image members as (member name, bytes, suffix), in page order."""
    if path.suffix.lower() != ".cbz":
        return []
    try:
        with zipfile.ZipFile(path) as archive:
            images = sorted(
                (info for info in archive.infolist()
                 if Path(info.filename).suffix.lower() in _IMAGE_SUFFIXES),
                key=lambda info: info.filename,
            )
            return [(info.filename, archive.read(info), Path(info.filename).suffix.lower()) for info in images]
    except (zipfile.BadZipFile, KeyError, OSError):
        return []


def cover_candidates(path: Path) -> list[tuple[str, bytes, str]]:
    """Return the first page plus explicitly named cover/variant images.

    CBZs do not identify alternate art semantically. Numeric page images are
    story pages, so they are intentionally excluded from this selector.
    """
    entries = image_entries(path)
    if not entries:
        return []
    named = [entry for entry in entries if any(word in Path(entry[0]).stem.casefold() for word in _COVER_WORDS)]
    result = [entries[0]]
    result.extend(entry for entry in named if entry[0] != entries[0][0])
    return result
def preferred_entry(path: Path, source_root: Path | None) -> str | None:
    if source_root is None:
        return None
    from comicmeta._common import load_json
    state_path = _preference_path(source_root)
    if not state_path.is_file():
        return None
    state = load_json(state_path, "cover preferences")
    saved = state.get("covers", {}).get(str(path.relative_to(source_root)))
    if not saved:
        return None
    stat = path.stat()
    if saved.get("size") != stat.st_size or saved.get("modified") != stat.st_mtime_ns:
        return None
    return saved.get("entry")


def select_entry(path: Path, source_root: Path, entry: str) -> None:
    from comicmeta._common import atomic_json, load_json
    state_path = _preference_path(source_root)
    state = load_json(state_path, "cover preferences") if state_path.is_file() else {"covers": {}}
    entries = {name for name, _data, _suffix in image_entries(path)}
    if entry not in entries:
        raise ValueError(f"cover page not found in archive: {entry}")
    state.setdefault("covers", {})[str(path.relative_to(source_root))] = {
        "entry": entry,
        "size": path.stat().st_size,
        "modified": path.stat().st_mtime_ns,
    }
    atomic_json(state_path, state)


def _extract_cover(path: Path, max_bytes: int = 2 * 1024 * 1024,
                   source_root: Path | None = None) -> tuple[bytes, str] | None:
    """Return (image_bytes, suffix) for the first image in a CBZ archive."""
    if path.suffix.lower() != ".cbz":
        return None
    try:
        preferred = preferred_entry(path, source_root)
        with zipfile.ZipFile(path) as archive:
            images = sorted(
                (info for info in archive.infolist()
                 if Path(info.filename).suffix.lower() in _IMAGE_SUFFIXES),
                key=lambda info: info.filename,
            )
            if not images:
                return None
            image = next((info for info in images if info.filename == preferred), images[0])
            data = archive.read(image)
            return data, Path(image.filename).suffix.lower()
    except (zipfile.BadZipFile, KeyError, OSError):
        return None


def supports_inline() -> bool:
    term = os.environ.get("TERM_PROGRAM", "")
    return "iTerm" in term or "kitty" in term or "WezTerm" in term


def pillow_preview_available() -> bool:
    """True when Pillow can render covers (true-color or ASCII fallback)."""
    import importlib.util
    return importlib.util.find_spec("PIL") is not None


def render_inline(data: bytes, suffix: str, height: int = 8) -> str:
    """Return the escape sequence to display an image inline in the terminal."""
    mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "gif": "gif", "webp": "webp", "avif": "avif"}.get(suffix.lstrip("."), "png")
    encoded = base64.b64encode(data).decode("ascii")
    return f"\x1b]1337;File=inline=1;height={height};name=cover.{mime};type=image/{mime}:{encoded}\x07"


def pillow_ansi_cover(data: bytes, suffix: str, width: int = 36, max_lines: int = 22) -> str | None:
    """Render a true-color half-block cover using Pillow alone.

    Each terminal cell carries two pixels (top = foreground, bottom = background
    of a ▀ block), so a 48-column cover shows ~96px of height. Emits 24-bit ANSI
    colors and needs no external tool — works over SSH on any true-color
    terminal. Returns None when Pillow is unavailable or the image can't be read.
    """
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        image = Image.open(io.BytesIO(data))
        image = image.convert("RGB")
        lines = max(1, round(width * image.height / image.width * 0.5))
        if lines > max_lines:
            # Cap the height and shrink the width to match, so the cover is
            # never squished into the max height (uniform scaling).
            lines = max_lines
            width = max(1, round(max_lines * image.width / image.height * 2))
        px_height = max(2, lines * 2)
        image = image.resize((width, px_height))
    except Exception:
        return None
    pixels = image.load()
    rendered = []
    for y in range(lines):
        row = []
        for x in range(width):
            top = pixels[x, y * 2]
            bottom = pixels[x, y * 2 + 1] if y * 2 + 1 < px_height else top
            row.append(f"\x1b[38;2;{top[0]};{top[1]};{top[2]}m"
                       f"\x1b[48;2;{bottom[0]};{bottom[1]};{bottom[2]}m▀")
        row.append("\x1b[0m")
        rendered.append("".join(row))
    return "\n".join(rendered)


def ascii_cover(data: bytes, suffix: str, width: int = 24, max_height: int = 48) -> str:
    """A tiny ASCII placeholder when the terminal cannot show inline images.

    Preserves the cover's aspect ratio: terminal cells are roughly twice as tall
    as they are wide, so a portrait cover (e.g. 1988x3056) renders as a tall,
    readable grid instead of a crushed landscape strip.
    """
    try:
        from PIL import Image
    except ImportError:
        return "  [cover — install Pillow or use iTerm2/Kitty for inline previews]"
    try:
        image = Image.open(io.BytesIO(data))
        image = image.convert("L")
        height = max(1, round(width * image.height / image.width * 0.5))
        height = min(height, max_height)
        image = image.resize((width, height))
    except Exception:
        return "  [cover unavailable]"
    chars = " .:-=+*#%@"
    lines = []
    for y in range(image.height):
        row = ""
        for x in range(image.width):
            pixel = image.getpixel((x, y))
            row += chars[min(len(chars) - 1, pixel * (len(chars) - 1) // 255)]
        lines.append(row)
    return "\n".join(lines)


def external_preview(data: bytes, suffix: str, width: int = 48, height: int = 24) -> str | None:
    """Render a true-color cover via timg, terminal-image-cli, or chafa.

    These tools emit 24-bit ANSI half-blocks that work in Apple's native
    Terminal.app (no inline-image protocol needed).

    * `timg` takes `-g WxH` (character geometry) and its default output is
      true-color; `-pS` would switch it to Sixel, so it is deliberately unused.
    * `terminal-image-cli` installs a binary named `image` (not
      `terminal-image`). It has no size flags — it auto-detects the terminal
      width — so the request size is ignored for that tool.
    * `chafa` takes `--size WxH` and is the weakest fallback (half-block or
      symbol rendering depending on terminal).
    """
    tool: tuple[str, list[str]] | None = None
    timg = shutil.which("timg")
    terminal_image = shutil.which("image")
    chafa = shutil.which("chafa")
    if timg:
        tool = (timg, ["-g", f"{width}x{height}"])
    elif terminal_image:
        tool = (terminal_image, [])
    elif chafa:
        tool = (chafa, ["--format", "blocks", "--size", f"{width}x{height}"])
    if tool is None:
        return None
    command, flags = tool
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
            handle.write(data)
            temporary = handle.name
        try:
            environment = None
            if terminal_image:
                environment = os.environ.copy()
                environment["FORCE_COLOR"] = "1"
                environment.pop("NO_COLOR", None)
            result = subprocess.run(
                [command, *flags, temporary],
                capture_output=True, text=True, timeout=20, env=environment,
            )
        finally:
            Path(temporary).unlink(missing_ok=True)
    except (subprocess.SubprocessError, OSError):
        return None
    if result.returncode != 0 or not result.stdout:
        return None
    output = result.stdout.rstrip("\n")
    # timg wraps the image in cursor-hide/show; strip those so the card layout
    # does not hide the cursor for the rest of the interactive session.
    output = output.replace("\x1b[?25l", "").replace("\x1b[?25h", "")
    return output.rstrip("\n")


def preview_data(data: bytes, suffix: str) -> str:
    """Render image bytes using the best available terminal renderer."""
    external = external_preview(data, suffix)
    if external:
        return external
    if supports_inline():
        return render_inline(data, suffix)
    ansi = pillow_ansi_cover(data, suffix)
    if ansi:
        return ansi
    return ascii_cover(data, suffix)


def preview(path: Path, source_root: Path | None = None) -> str:
    """Render a cover preview for a CBZ, or an empty string if none available."""
    if not previews_enabled(source_root):
        return ""
    cover = _extract_cover(path, source_root=source_root)
    if cover is None:
        return ""
    return preview_data(*cover)
