import json
import tempfile

from comicmeta._commands.review_volumes import (
    atomic_json,
    grouped_items,
    selection_for,
    write_summary,
)


def candidate(identifier, name, year, count=4, publisher="Marvel"):
    return {
        "id": identifier,
        "name": name,
        "start_year": str(year),
        "count_of_issues": count,
        "publisher": {"name": publisher},
        "site_detail_url": f"https://comicvine.example/{identifier}",
    }


report = {
    "source": "/srv/comics",
    "items": [
        {
            "query": "Hawkeye (1983)",
            "path": "Marvel/Hawkeye (1983)/Hawkeye (1983) #001.cbr",
            "format": "cbr",
            "status": "review-required",
            "issue_number_from_filename": "001",
            "candidates": [
                candidate(96661, "Hawkeye", 2017, 16),
                candidate(3225, "Hawkeye", 1983, 4),
            ],
        },
        {
            "query": "Hawkeye (1983)",
            "path": "Marvel/Hawkeye (1983)/Hawkeye (1983) #004.cbr",
            "format": "cbr",
            "status": "review-required",
            "issue_number_from_filename": "004",
            "candidates": [candidate(3225, "Hawkeye", 1983, 4)],
        },
    ],
}


def test_grouped_items_recommendation():
    groups = grouped_items(report)
    assert len(groups) == 1
    group = groups[0]
    assert group["recommendation"]["id"] == 3225
    assert group["high_confidence"] is True
    assert group["paths"] == [
        "Marvel/Hawkeye (1983)/Hawkeye (1983) #001.cbr",
        "Marvel/Hawkeye (1983)/Hawkeye (1983) #004.cbr",
    ]
    assert group["recommendation"]["score"] > group["candidates"][1]["score"]


def test_atomic_json_and_summary(tmp_path):
    groups = grouped_items(report)
    group = groups[0]
    state_path = tmp_path / "state.json"
    summary_path = tmp_path / "summary.md"
    state = {"version": 1, "report": "fixture.json", "selections": {
        group["query"]: selection_for(group["recommendation"])
    }}
    atomic_json(state_path, state)
    saved = json.loads(state_path.read_text())
    assert saved["selections"]["Hawkeye (1983)"]["candidate_id"] == 3225
    write_summary(summary_path, report, groups, state, {"active_source": "/srv/comics"})
    summary = summary_path.read_text()
    assert "Active: `/srv/comics/Marvel/Hawkeye (1983)/Hawkeye (1983) #001.cbr`" in summary
    assert "Scanned copy: `/srv/comics/Marvel/Hawkeye (1983)/Hawkeye (1983) #001.cbr`" not in summary
    assert "https://comicvine.example/3225" in summary


def test_blocked_query():
    blocked = grouped_items(report, {"blocked_queries": {"Hawkeye (1983)": "fixture block"}})[0]
    assert blocked["high_confidence"] is False
    assert blocked["blocked_reason"] == "fixture block"


def test_interactive_arrow_selection(tmp_path, monkeypatch):
    from unittest import mock
    from pathlib import Path
    from comicmeta._commands.review_volumes import Palette, interactive

    report = tmp_path / "c.json"
    report.write_text(json.dumps({
        "source": str(tmp_path),
        "items": [
            {"query": "Batman (2017)", "path": "Batman #001.cbr", "format": "cbr",
             "status": "review-required", "issue_number_from_filename": "001",
             "candidates": [{"id": 104042, "name": "Batman", "start_year": "2017",
                             "count_of_issues": 1, "publisher": {"name": "DC Comics"},
                             "site_detail_url": "https://cv.example/104042"}]},
            {"query": "Hawkeye (1983)", "path": "Hawkeye #001.cbr", "format": "cbr",
             "status": "review-required", "issue_number_from_filename": "001",
             "candidates": [
                 {"id": 3225, "name": "Hawkeye", "start_year": "1983", "count_of_issues": 4,
                  "publisher": {"name": "Marvel"}, "site_detail_url": "https://cv.example/3225"},
                 {"id": 96661, "name": "Hawkeye", "start_year": "2017", "count_of_issues": 16,
                  "publisher": {"name": "Marvel"}, "site_detail_url": "https://cv.example/96661"},
             ]},
        ],
    }))
    state_path = tmp_path / "s.json"
    summary = tmp_path / "summary.md"
    keys = iter(["enter", "right", "down", "enter", "q"])
    with mock.patch("comicmeta._tui.read_key", lambda: next(keys)):
        interactive(report, state_path, summary, {}, Palette(False))
    saved = json.loads(state_path.read_text())["selections"]
    assert saved["Batman (2017)"]["candidate_id"] == 104042
    assert saved["Hawkeye (1983)"]["candidate_id"] == 96661


def test_interactive_last_group_breaks_loop(tmp_path, monkeypatch):
    """Selecting the final group must end the loop, not hang on it."""
    from unittest import mock
    from pathlib import Path
    from comicmeta._commands.review_volumes import Palette, interactive

    report = tmp_path / "one.json"
    report.write_text(json.dumps({
        "source": str(tmp_path),
        "items": [{
            "query": "Batman (2017)", "path": "Batman #001.cbr", "format": "cbr",
            "status": "review-required", "issue_number_from_filename": "001",
            "candidates": [{"id": 104042, "name": "Batman", "start_year": "2017",
                            "count_of_issues": 1, "publisher": {"name": "DC Comics"},
                            "site_detail_url": "https://cv.example/104042"}],
        }],
    }))
    state_path = tmp_path / "s.json"
    with mock.patch("comicmeta._tui.read_key", return_value="enter"):
        interactive(report, state_path, tmp_path / "sm.md", {}, Palette(False))
    saved = json.loads(state_path.read_text())["selections"]
    assert "Batman (2017)" in saved


def test_write_args_sets_yes_to_avoid_double_confirm():
    from pathlib import Path
    from comicmeta import _config
    from comicmeta._commands.review import _defaults, _write_args
    from argparse import Namespace
    args = Namespace(source=Path("."), api_key_env=None, api_key_file=None, no_color=False, list=False)
    flat = _config.load(None)
    wa = _write_args(args, _defaults(flat), flat)
    assert getattr(wa, "yes", False) is True


def test_flag_volume_persists(tmp_path, monkeypatch):
    import io, contextlib
    from unittest import mock
    from comicmeta._commands.review_volumes import interactive, grouped_items
    from comicmeta._common import Palette
    report_path = tmp_path / "candidates.json"
    state_path = tmp_path / "state.json"
    summary_path = tmp_path / "summary.md"
    report_path.write_text(json.dumps({
        "source": str(tmp_path),
        "items": [{
            "path": "X (2020)/X (2020) #001.cbz",
            "format": "cbz",
            "has_comicinfo": False,
            "query": "X (2020)",
            "issue_number_from_filename": "001",
            "status": "review-required",
            "candidates": [{"id": 1, "name": "X", "start_year": 2020, "count_of_issues": 5}],
        }],
    }))
    keys = iter(["!", "q"])
    with mock.patch("comicmeta._tui.read_key", lambda: next(keys)):
        with mock.patch("comicmeta._tui.prompt_edit", lambda *a, **k: "verify volume year"):
            with contextlib.redirect_stdout(io.StringIO()):
                interactive(report_path, state_path, summary_path, {}, Palette(False))
    state = json.loads(state_path.read_text())
    sel = state["selections"]["X (2020)"]
    assert sel["status"] == "flagged"
    assert sel["note"] == "verify volume year"


def test_pin_volume_fetches_and_selects(tmp_path, monkeypatch):
    import io, contextlib
    from unittest import mock
    from comicmeta._commands.review_volumes import interactive
    from comicmeta._common import Palette
    report_path = tmp_path / "candidates.json"
    state_path = tmp_path / "state.json"
    summary_path = tmp_path / "summary.md"
    report_path.write_text(json.dumps({
        "source": str(tmp_path),
        "items": [{
            "path": "X (2020)/X (2020) #001.cbz",
            "format": "cbz",
            "has_comicinfo": False,
            "query": "X (2020)",
            "issue_number_from_filename": "001",
            "status": "review-required",
            "candidates": [{"id": 99, "name": "Wrong", "start_year": 1990, "count_of_issues": 2}],
        }],
    }))
    fake_volume = {"id": 5230, "name": "Aquaman", "start_year": 1994,
                   "publisher": {"name": "DC Comics"}, "count_of_issues": 77,
                   "site_detail_url": "https://comicvine.gamespot.com/aquaman/4050-5230/"}
    keys = iter(["p", "enter", "q"])
    with mock.patch("comicmeta._tui.read_key", lambda: next(keys)):
        with mock.patch("comicmeta._commands.review_volumes.prompt_volume_id", lambda: 5230):
            with mock.patch("comicmeta._comicvine.fetch_volume", lambda *a, **k: fake_volume):
                with mock.patch("comicmeta._commands.review_volumes.api_key", lambda: "fake"):
                    with contextlib.redirect_stdout(io.StringIO()):
                        interactive(report_path, state_path, summary_path, {}, Palette(False))
    state = json.loads(state_path.read_text())
    sel = state["selections"]["X (2020)"]
    assert sel["candidate_id"] == 5230
    assert sel["name"] == "Aquaman"
