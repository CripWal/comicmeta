import io
import contextlib
import os
import zipfile
from pathlib import Path
from unittest import mock

from comicmeta._commands import browse as B
from comicmeta._common import Palette


def make_cbz(path: Path, has_ci=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("001.jpg", b"page")
        if has_ci:
            archive.writestr("ComicInfo.xml", "<ComicInfo><Series>X</Series></ComicInfo>")


def test_build_tree(tmp_path):
    make_cbz(tmp_path / "DC/Absolute Flash (2025)/Absolute Flash (2025) #001.cbz", True)
    make_cbz(tmp_path / "Marvel/Hawkeye (1983)/Hawkeye (1983) #001.cbr")
    root = B._build_tree(tmp_path, {"comicmeta-backups"})
    publishers = {c.name for c in root.children}
    assert publishers == {"DC", "Marvel"}


def test_visible_nodes_expand(tmp_path):
    make_cbz(tmp_path / "DC/Absolute Flash (2025)/Absolute Flash (2025) #001.cbz")
    root = B._build_tree(tmp_path, set())
    dc = root.children[0]
    dc.expanded = True
    dc.children[0].expanded = True
    vis = B._visible_nodes(root)
    assert any(not node.is_dir for node, _depth in vis)  # a file becomes visible


def test_browse_navigates_and_opens(tmp_path):
    make_cbz(tmp_path / "Marvel/Hawkeye (1983)/Hawkeye (1983) #001.cbr")
    root = B._build_tree(tmp_path, set())
    keys = iter(["down", "down", "right", "down", "right", "down", "enter", "q"])
    opened = []
    with mock.patch("comicmeta._commands.browse.read_key", lambda: next(keys)):
        with mock.patch("comicmeta._commands.browse._open_issue_card",
                        side_effect=lambda path, *a, **k: opened.append(path.name)):
            with contextlib.redirect_stdout(io.StringIO()):
                B._browse(root, tmp_path, None, Palette(False))
    assert opened and opened[0].endswith(".cbr")


def test_render_issue_card_shows_metadata(tmp_path):
    make_cbz(tmp_path / "DC/Aquaman Vol. 5 Annual (1995)/Aquaman Annual 001 (1995).cbz", True)
    from comicmeta._commands.browse import _sibling_archives, _render_issue_card
    target = tmp_path / "DC/Aquaman Vol. 5 Annual (1995)/Aquaman Annual 001 (1995).cbz"
    siblings = _sibling_archives(target)
    assert len(siblings) == 1
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        _render_issue_card(target, 0, siblings, tmp_path, Palette(False))
    out = buf.getvalue()
    assert "COMIC" in out
    assert "Aquaman Vol. 5 Annual" in out
    assert "No ComicInfo" not in out or "ComicInfo" in out


def test_sibling_archives_sorted_and_pages(tmp_path):
    from comicmeta._commands.browse import _sibling_archives
    make_cbz(tmp_path / "Marvel/Hawkeye (2017)/Hawkeye (2017) #001.cbz")
    make_cbz(tmp_path / "Marvel/Hawkeye (2017)/Hawkeye (2017) #002.cbz")
    make_cbz(tmp_path / "Marvel/Hawkeye (2017)/Hawkeye (2017) #003.cbr")
    folder = tmp_path / "Marvel/Hawkeye (2017)"
    siblings = _sibling_archives(folder / "Hawkeye (2017) #002.cbz")
    assert [s.name for s in siblings] == [
        "Hawkeye (2017) #001.cbz",
        "Hawkeye (2017) #002.cbz",
        "Hawkeye (2017) #003.cbr",
    ]


def test_render_tree_has_footer(tmp_path):
    make_cbz(tmp_path / "Marvel/Hawkeye (1983)/Hawkeye (1983) #001.cbz")
    root = B._build_tree(tmp_path, set())
    buf = io.StringIO()
    with mock.patch("shutil.get_terminal_size", return_value=os.terminal_size((160, 40))):
        with contextlib.redirect_stdout(buf):
            B._render_tree(root, 0, Palette(False))
    out = buf.getvalue()
    assert "[↑/↓] move" in out
    assert "[→/Enter] open" in out
    assert "[q] quit" in out


def test_browse_toggle_issue_flag(tmp_path, monkeypatch):
    from comicmeta import _config
    target = tmp_path / "Marvel/Hawkeye (2017)/Hawkeye (2017) #001.cbz"
    make_cbz(target)
    state = tmp_path / "issue-state.json"
    monkeypatch.setattr(_config, "get", lambda flat, key: str(state) if key == "paths.issue_state" else "unused")
    assert B._toggle_flag(target, tmp_path) is True
    assert B._toggle_flag(target, tmp_path) is False
    assert '"reviews": {}' in state.read_text()


def test_browse_gallery_waits_before_redraw(tmp_path, monkeypatch):
    target = tmp_path / "Marvel/Hawkeye (2017)/Hawkeye (2017) #001.cbz"
    make_cbz(target)
    keys = iter(["g", "enter", "q"])
    gallery = []
    monkeypatch.setattr(B, "_render_issue_card", lambda *args: None)
    monkeypatch.setattr(B, "read_key", lambda: next(keys))
    monkeypatch.setattr("comicmeta._commands.covers._gallery", lambda path, *args: gallery.append(path))
    B._open_issue_card(target, tmp_path, None, Palette(False))
    assert gallery == [target.parent]
