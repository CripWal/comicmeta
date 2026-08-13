import zipfile
from pathlib import Path

from comicmeta import _cover


def test_pillow_ansi_cover_renders_true_color_blocks():
    import io
    try:
        from PIL import Image
    except ImportError:
        return
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (255, 0, 0)).save(buf, format="PNG")
    out = _cover.pillow_ansi_cover(buf.getvalue(), ".png", width=4, max_lines=4)
    assert out is not None
    assert "▀" in out
    assert "\x1b[38;2;255;0;0m" in out  # true-color foreground
    assert "\x1b[0m" in out


def test_pillow_ansi_cover_preserves_aspect_when_height_capped():
    """A tall cover that exceeds max_lines must shrink in width too, so the
    preview is uniformly scaled instead of squished."""
    import io
    try:
        from PIL import Image
    except ImportError:
        return
    buf = io.BytesIO()
    Image.new("RGB", (300, 600), (10, 10, 10)).save(buf, format="PNG")
    out = _cover.pillow_ansi_cover(buf.getvalue(), ".png", width=36, max_lines=22)
    rows = out.splitlines()
    cells = rows[0].count("▀")
    assert len(rows) == 22  # capped at max_lines
    assert cells < 30  # width shrank so the aspect stays uniform


def test_pillow_ansi_cover_returns_none_without_pillow():
    from unittest import mock
    with mock.patch.dict("sys.modules", {"PIL": None}):
        assert _cover.pillow_ansi_cover(b"not-an-image", ".png") is None


def test_extract_cover(tmp_path):
    cbz = tmp_path / "c.cbz"
    with zipfile.ZipFile(cbz, "w") as archive:
        archive.writestr("0001.jpg", b"fake")
        archive.writestr("0002.jpg", b"fake2")
    data, suffix = _cover._extract_cover(cbz)
    assert data == b"fake"
    assert suffix == ".jpg"


def test_extract_cover_non_cbz(tmp_path):
    assert _cover._extract_cover(tmp_path / "x.cbr") is None


def test_extract_cover_missing_image(tmp_path):
    cbz = tmp_path / "c.cbz"
    with zipfile.ZipFile(cbz, "w") as archive:
        archive.writestr("0001.txt", b"no image")
    assert _cover._extract_cover(cbz) is None


def test_extract_cover_keeps_large_image_bytes(tmp_path):
    cbz = tmp_path / "large.cbz"
    data = b"x" * (2 * 1024 * 1024 + 1)
    with zipfile.ZipFile(cbz, "w") as archive:
        archive.writestr("0001.jpg", data)

    extracted, _ = _cover._extract_cover(cbz)

    assert extracted == data


def test_render_inline_is_escape_sequence():
    out = _cover.render_inline(b"fake", ".png")
    assert out.startswith("\x1b]1337;File=inline=1")
    assert "base64" not in out  # already encoded inline
    assert "type=image/png" in out


def test_ascii_cover_without_pillow():
    out = _cover.ascii_cover(b"fake", ".jpg")
    assert "install Pillow" in out or "unavailable" in out


def test_ascii_cover_preserves_portrait_aspect(tmp_path):
    """A portrait cover must not be crushed into a landscape strip."""
    from PIL import Image
    import io
    cover = tmp_path / "p.png"
    Image.new("RGB", (200, 300), "white").save(cover)
    out = _cover.ascii_cover(cover.read_bytes(), ".png", width=24)
    lines = out.splitlines()
    height = len(lines)
    assert height > 12  # portrait cover: taller than the old width//2 landscape strip
    assert height <= 48  # and capped so it never floods the terminal


def test_external_preview_none_without_tools(tmp_path, monkeypatch):
    from comicmeta._cover import external_preview
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert external_preview(b"fake", ".jpg") is None


def test_external_preview_uses_timg(tmp_path, monkeypatch):
    from comicmeta import _cover
    cover = tmp_path / "cover.jpg"
    cover.write_bytes(b"imgdata")
    calls = {}
    def fake_run(cmd, **kwargs):
        calls["cmd"] = cmd
        class R: returncode = 0; stdout = "\x1b[?25lAB\x1b[?25h"
        return R()
    monkeypatch.setattr("shutil.which", lambda name: "timg" if name == "timg" else None)
    monkeypatch.setattr("subprocess.run", fake_run)
    out = _cover.external_preview(b"imgdata", ".jpg", width=30, height=20)
    assert out == "AB"  # cursor-hide/show stripped
    assert "30x20" in calls["cmd"]


def test_external_preview_forces_color_for_terminal_image(tmp_path, monkeypatch):
    calls = {}

    def fake_run(cmd, **kwargs):
        calls.update(kwargs)
        class R: returncode = 0; stdout = "color"
        return R()

    monkeypatch.setattr("shutil.which", lambda name: "image" if name == "image" else None)
    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setenv("NO_COLOR", "1")

    assert _cover.external_preview(b"imgdata", ".jpg") == "color"
    assert calls["env"]["FORCE_COLOR"] == "1"
    assert "NO_COLOR" not in calls["env"]


def test_alternate_cover_preference_is_external_and_reversible(tmp_path, monkeypatch):
    from comicmeta import _config
    cbz = tmp_path / "Marvel/Hawkeye (2017)/Hawkeye #001.cbz"
    cbz.parent.mkdir(parents=True)
    with zipfile.ZipFile(cbz, "w") as archive:
        archive.writestr("0001.jpg", b"first")
        archive.writestr("0002.jpg", b"second")
    preferences = tmp_path / "cover-preferences.json"
    monkeypatch.setattr(_config, "get", lambda flat, key: str(preferences) if key == "paths.cover_state" else None)

    _cover.select_entry(cbz, tmp_path, "0002.jpg")
    assert _cover._extract_cover(cbz, source_root=tmp_path) == (b"second", ".jpg")
    assert cbz.read_bytes()

    _cover.select_entry(cbz, tmp_path, "0001.jpg")
    assert _cover._extract_cover(cbz, source_root=tmp_path) == (b"first", ".jpg")


def test_cover_candidates_do_not_treat_story_pages_as_alternates(tmp_path):
    cbz = tmp_path / "issue.cbz"
    with zipfile.ZipFile(cbz, "w") as archive:
        archive.writestr("0001.jpg", b"first")
        archive.writestr("0002.jpg", b"story")
        archive.writestr("variant-cover.jpg", b"variant")

    assert [entry[0] for entry in _cover.cover_candidates(cbz)] == ["0001.jpg", "variant-cover.jpg"]


def test_preview_prefers_terminal_renderer_over_inline(tmp_path, monkeypatch):
    cbz = tmp_path / "c.cbz"
    with zipfile.ZipFile(cbz, "w") as archive:
        archive.writestr("0001.jpg", b"fake")
    monkeypatch.setattr(_cover, "supports_inline", lambda: True)
    monkeypatch.setattr(_cover, "external_preview", lambda *args: "terminal image")
    monkeypatch.setattr(_cover, "render_inline", lambda *args: "inline image")

    assert _cover.preview(cbz) == "terminal image"
