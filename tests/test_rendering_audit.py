"""Regression tests for terminal-width rendering fixes.

Each fixed screen is rendered at several narrow terminal widths and every
output line is asserted to fit within the terminal columns, following the
pattern from tests/test_settings.py.
"""

import contextlib
import io
import re
import shutil
import zipfile
from types import SimpleNamespace
from unittest import mock

import pytest

from comicmeta._common import Palette

WIDTHS = (40, 60, 80, 100)


def _run(call, cols, rows=24):
    fake = SimpleNamespace(columns=cols, lines=rows)
    original = shutil.get_terminal_size
    shutil.get_terminal_size = lambda f: fake
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            call()
    finally:
        shutil.get_terminal_size = original
    return buf.getvalue()


def _strip(text):
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def _assert_fits(out, cols):
    for line in out.split("\n"):
        assert len(_strip(line)) <= cols, f"overflow at {cols} cols: {line!r}"


def _make_cbz(path, summary=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    xml = (
        "<ComicInfo><Series>Test Series</Series><Volume>2020</Volume>"
        "<Number>1</Number><Year>2020</Year><Format>Issue</Format>"
        f"<Summary>{summary}</Summary><Web>https://example.com/issue/1</Web></ComicInfo>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("ComicInfo.xml", xml)
        archive.writestr("001.jpg", b"cover")


@pytest.mark.parametrize("cols", WIDTHS)
def test_browse_tree_fits_narrow_terminal(tmp_path, cols):
    from comicmeta._commands.browse import _build_tree, _render_tree
    for folder in (f"S{i:02d}" for i in range(20)):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / f"{folder}.cbr").write_bytes(b"x")
    root = _build_tree(tmp_path, set())
    out = _run(lambda: _render_tree(root, 10, Palette(False)), cols)
    _assert_fits(out, cols)
    assert "[↑/↓] move" in out
    assert "more" in out


@pytest.mark.parametrize("cols", WIDTHS)
def test_issue_card_fits_narrow_terminal(tmp_path, cols):
    from comicmeta._commands.browse import _render_issue_card, _sibling_archives
    target = tmp_path / "Series" / "Series #001.cbz"
    _make_cbz(target, summary="A very long summary line " * 6)
    siblings = _sibling_archives(target)
    out = _run(lambda: _render_issue_card(target, 0, siblings, tmp_path, Palette(False)), cols)
    _assert_fits(out, cols)
    assert "prev/next issue" in out


def test_issue_card_gates_cover_on_short_terminal(tmp_path):
    from comicmeta._commands.browse import _render_issue_card, _sibling_archives
    target = tmp_path / "Series" / "Series #001.cbz"
    _make_cbz(target)
    siblings = _sibling_archives(target)
    with mock.patch("comicmeta._cover.preview", return_value="\n".join(["#" * 40] * 14)):
        out = _run(lambda: _render_issue_card(target, 0, siblings, tmp_path, Palette(False)), 80, rows=24)
    assert "Test Series" in out
    assert "BASIC METADATA" in out
    assert len(out.rstrip("\n").split("\n")) <= 24


def _volume_group(path_count=20, candidate_count=9):
    candidates = [
        {
            "id": 100 + i,
            "name": f"Series {i}",
            "start_year": "2000",
            "publisher": {"name": "Marvel"},
            "count_of_issues": 100 + i,
            "site_detail_url": "https://comicvine.gamespot.com/aquaman/4050-5230/",
            "score": 100 - i,
            "score_reasons": ["title 100%"],
        }
        for i in range(candidate_count)
    ]
    return {
        "query": "Series (2000)",
        "items": [],
        "paths": [f"S{i}.cbr" for i in range(path_count)],
        "formats": ["CBR"],
        "blocked_reason": None,
        "candidates": candidates,
        "recommendation": candidates[0],
        "high_confidence": True,
    }


@pytest.mark.parametrize("cols", WIDTHS)
def test_volume_review_fits_narrow_terminal(cols):
    from comicmeta._commands.review_volumes import render_group
    group = _volume_group()
    out = _run(
        lambda: render_group(
            group, 0, [group], {"source": "/srv/comics"}, {"selections": {}},
            {"active_source": "/srv/comics"}, Palette(False), True, 4, (0, 0),
        ),
        cols,
    )
    _assert_fits(out, cols)
    assert "Recommended:" in out
    assert "[↑/↓] choose candidate" in out


def _issue_report():
    return {
        "active_source": "/srv/comics",
        "scanned_source": "/srv/kavita/comics",
        "series": [{
            "query": "Hawkeye (1983)",
            "matches": [{
                "path": "Hwk.cbr",
                "archive_format": "cbr",
                "status": "exact-number",
                "issue": {"id": 10, "issue_number": "1"},
                "metadata_candidate": {
                    "series": "Hawkeye", "volume": "1983", "number": "1", "year": "1983",
                    "month": "9", "day": "1", "format": "Issue", "publisher": "Marvel",
                    "title": "Point Blank", "web": "https://example.com/10",
                    "summary": "A very long summary " * 8,
                },
            }],
        }],
    }


@pytest.mark.parametrize("cols", WIDTHS)
def test_issue_review_fits_narrow_terminal(cols):
    from comicmeta._commands.review_issues import render, review_items
    items = review_items(_issue_report())
    out = _run(lambda: render(items[0], 0, items, {"reviews": {}}, Palette(False)), cols)
    _assert_fits(out, cols)
    assert "COMICVINE ISSUE REVIEW" in out


@pytest.mark.parametrize("cols", WIDTHS)
def test_write_summary_fits_narrow_terminal(cols):
    from comicmeta._commands.write import _write_summary_panel
    rows = [
        ("Library", "/srv/comics/library"),
        ("Mapping", "/srv/comics/mapping.json"),
        ("Backup", "keep 30d, purge older"),
        ("Files", "124 archives"),
    ]
    out = _run(lambda: _write_summary_panel(Palette(False), rows), cols)
    _assert_fits(out, cols)


@pytest.mark.parametrize("cols", WIDTHS)
def test_all_clear_banner_fits_narrow_terminal(cols):
    from comicmeta._commands.health import _all_clear_banner
    out = _run(lambda: _all_clear_banner(Palette(False), 1234), cols)
    _assert_fits(out, cols)


@pytest.mark.parametrize("cols", WIDTHS)
def test_convert_summary_fits_narrow_terminal(cols):
    from comicmeta._commands.convert import _convert_summary
    out = _run(lambda: _convert_summary(Palette(False), 12, 9, 3), cols)
    _assert_fits(out, cols)


@pytest.mark.parametrize("cols", (20, 40, 60, 80, 100))
def test_context_step_header_fits_narrow_terminal(cols):
    from comicmeta._commands.context import _step
    out = _run(lambda: _step(Palette(False), 1, 5, "Execution method"), cols)
    _assert_fits(out, cols)


@pytest.mark.parametrize("cols", WIDTHS)
def test_settings_menu_fits_narrow_terminal(tmp_path, cols):
    from comicmeta.cli import _render_settings_menu, _build_rows
    from comicmeta._commands.settings import load_flat
    out = _run(lambda: _render_settings_menu(Palette(False), _build_rows(load_flat(), show_advanced=True), 0, None), cols)
    _assert_fits(out, cols)


@pytest.mark.parametrize("cols", WIDTHS)
def test_convert_picker_fits_narrow_terminal(tmp_path, cols):
    from comicmeta._commands.convert import convert_picker
    for name in ("A.cbr", "B.cbr", "C.cbr", "D.cbr"):
        (tmp_path / name).write_bytes(b"fake")
    keys = iter(["q"])
    with mock.patch("comicmeta._tui.read_key", lambda: next(keys)):
        out = _run(lambda: convert_picker(tmp_path, {}, tmp_path / "backup", Palette(False)), cols)
    _assert_fits(out, cols)
    assert "CONVERT CBR → CBZ" in out
