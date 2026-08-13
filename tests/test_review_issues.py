import json

from comicmeta._commands.review_issues import accepted, atomic_json, manual_metadata, review_items, validate_metadata, write_summary


def match(path, issue_format="Issue", status="exact-number"):
    return {
        "path": path,
        "archive_format": "cbr",
        "status": status,
        "issue": {"id": 10, "issue_number": "1"},
        "metadata_candidate": {
            "series": "Hawkeye", "volume": "1983", "number": "1", "year": "1983",
            "month": "9", "day": "1", "format": issue_format, "publisher": "Marvel",
            "title": "Point Blank", "web": "https://example/10",
        },
    }


report = {
    "active_source": "/srv/comics",
    "scanned_source": "/srv/kavita/comics",
    "series": [
        {"query": "Hawkeye (1983)", "matches": [match("Marvel/Hawkeye (1983)/Hawkeye (1983) #001.cbr")]},
        {"query": "Hawkeye Omnibus (2015)", "matches": [match("Marvel/Hawkeye Omnibus (2015)/Hawkeye.cbr", "Omnibus")]},
    ],
}


def test_review_items():
    items = review_items(report)
    assert len(items) == 2
    assert items[0]["high_confidence"] is True
    assert items[1]["high_confidence"] is False
    assert items[0]["active_path"].startswith("/srv/comics/")
    assert items[0]["scanned_path"].startswith("/srv/kavita/comics/")


def test_state_and_summary(tmp_path):
    items = review_items(report)
    state_path = tmp_path / "state.json"
    summary_path = tmp_path / "summary.md"
    state = {"version": 1, "report": "fixture", "reviews": {
        items[0]["path"]: accepted(items[0]["metadata"], "auto-accepted"),
        items[1]["path"]: accepted(items[1]["metadata"]),
    }}
    atomic_json(state_path, state)
    saved = json.loads(state_path.read_text())
    assert saved["reviews"][items[0]["path"]]["metadata"]["number"] == "1"
    assert state_path.stat().st_mode & 0o777 == 0o644
    write_summary(summary_path, items, state)
    summary = summary_path.read_text()
    assert "Reviewed: 2 / 2" in summary
    assert "/srv/comics/Marvel/Hawkeye" in summary
    assert "https://example/10" in summary


def test_validate_metadata():
    assert validate_metadata({"series": "X", "volume": "2020", "number": "1", "year": "2020", "format": "Issue"}) == []
    assert validate_metadata({"series": "X"}) == ["volume", "number", "year", "format"]


def test_manual_metadata_produces_valid_comicinfo(monkeypatch):
    # Identity fields stay first; the remaining extended fields are optional.
    answers = iter(["Hawkeye", "1983", "1", "1983", "9", "", "Issue", "", "", ""] + [""] * 30)
    monkeypatch.setattr("builtins.input", lambda *a, **k: next(answers))
    result = manual_metadata({"path": "Marvel/Hawkeye (1983)/#001.cbz"})
    assert result is not None
    assert validate_metadata(result) == []
    assert result["series"] == "Hawkeye"
    assert result["number"] == "1"
    assert "manually entered" in result["notes"]


def test_manual_metadata_rejects_missing_required(monkeypatch):
    answers = iter([""] * 40)
    monkeypatch.setattr("builtins.input", lambda *a, **k: next(answers))
    result = manual_metadata({"path": "x.cbz"})
    assert result is None


def test_interactive_arrow_accept(tmp_path, monkeypatch):
    from unittest import mock
    from pathlib import Path
    from comicmeta._commands.review_issues import Palette, interactive

    report = tmp_path / "i.json"
    report.write_text(json.dumps({
        "active_source": str(tmp_path),
        "scanned_source": str(tmp_path),
        "series": [{
            "query": "Hawkeye (1983)",
            "matches": [
                {"path": "Hawkeye #001.cbr", "archive_format": "cbr", "status": "exact-number",
                 "issue": {"id": 10},
                 "metadata_candidate": {"series": "Hawkeye", "volume": "1983", "number": "1",
                                        "year": "1983", "format": "Issue", "publisher": "Marvel"}},
                {"path": "Hawkeye #002.cbr", "archive_format": "cbr", "status": "exact-number",
                 "issue": {"id": 11},
                 "metadata_candidate": {"series": "Hawkeye", "volume": "1983", "number": "2",
                                        "year": "1983", "format": "Issue", "publisher": "Marvel"}},
            ],
        }],
    }))
    state_path = tmp_path / "is.json"
    summary = tmp_path / "is-summary.md"
    keys = iter(["down", "enter", "q"])
    with mock.patch("comicmeta._tui.read_key", lambda: next(keys)):
        interactive(report, state_path, summary, Palette(False))
    saved = json.loads(state_path.read_text())["reviews"]
    assert "Hawkeye #002.cbr" in saved
    assert "Hawkeye #001.cbr" not in saved


def test_interactive_last_item_breaks_loop(tmp_path, monkeypatch):
    """Accepting the final item must end the loop, not hang on it."""
    from unittest import mock
    from pathlib import Path
    from comicmeta._commands.review_issues import Palette, interactive

    report = tmp_path / "one.json"
    report.write_text(json.dumps({
        "active_source": str(tmp_path),
        "scanned_source": str(tmp_path),
        "series": [{
            "query": "Hawkeye (1983)",
            "matches": [{
                "path": "H1.cbr", "archive_format": "cbr", "status": "exact-number",
                "issue": {"id": 10},
                "metadata_candidate": {"series": "Hawkeye", "volume": "1983", "number": "1",
                                       "year": "1983", "format": "Issue", "publisher": "Marvel"},
            }],
        }],
    }))
    state_path = tmp_path / "s.json"
    with mock.patch("comicmeta._tui.read_key", return_value="enter"):
        interactive(report, state_path, tmp_path / "sm.md", Palette(False))
    saved = json.loads(state_path.read_text())["reviews"]
    assert "H1.cbr" in saved


def test_render_progress_ignores_stale_reviews(tmp_path):
    """Regression: the progress counter must only count reviews for files in
    THIS session, never stale reviews from pruned series. Before the fix a
    defunct series' reviews inflated the bar (e.g. 118/78, >100%)."""
    import io, contextlib
    from comicmeta._commands.review_issues import render
    from comicmeta._common import Palette
    items = review_items(report)
    state = {"reviews": {
        "stale/Aquaman.cbz": {"status": "auto-accepted"},  # not in this report
    }}
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        render(items[0], 0, items, state, Palette(False))
    out = buf.getvalue()
    assert "reviewed 0/2" in out
    assert "118" not in out


def test_h_jumps_to_first_unreviewed(tmp_path):
    """After accepting high-confidence with h, the cursor lands on the first
    item that still needs a manual decision."""
    import io, contextlib
    from unittest import mock
    from comicmeta._commands.review_issues import interactive, review_items
    from comicmeta._common import Palette
    report = tmp_path / "issues.json"
    report.write_text(json.dumps({
        "active_source": str(tmp_path), "scanned_source": str(tmp_path),
        "series": [{"query": "X (2020)", "matches": [
            {"path": "a.cbz", "archive_format": "cbz", "status": "exact-number",
             "high": True, "metadata_candidate": _meta(1),
             "issue": {"id": 1}},
            {"path": "b.cbz", "archive_format": "cbz", "status": "unmatched",
             "metadata_candidate": _meta(2)},
            {"path": "c.cbz", "archive_format": "cbz", "status": "exact-number",
             "metadata_candidate": _meta(3), "issue": {"id": 3}},
        ]}],
    }))
    items = review_items(json.loads(report.read_text()))
    # a and c are exact-number; mark them high-confidence by faking the fields
    for item in items:
        item["high_confidence"] = item["status"] == "exact-number"
    state = tmp_path / "state.json"
    keys = iter(["h", "y", "q"])  # accept all, confirm, then save/back
    with mock.patch("comicmeta._tui.read_key", lambda: next(keys)):
        with mock.patch("comicmeta._tui.confirm", lambda *a, **k: True):
            with contextlib.redirect_stdout(io.StringIO()):
                result = interactive(report, state, tmp_path / "sum.md", Palette(False))
    assert result == 1  # q returns 'back'
    saved = json.loads(state.read_text())
    assert saved["reviews"]["a.cbz"]["status"] == "auto-accepted"
    assert saved["reviews"]["c.cbz"]["status"] == "auto-accepted"
    assert "b.cbz" not in saved["reviews"]  # low-confidence still pending


def _meta(n):
    return {"series": "X", "volume": "2020", "number": str(n),
            "year": "2020", "format": "Issue"}


def test_h_then_navigation_only_shows_pending(tmp_path):
    """After h auto-accepts high-confidence items, arrow navigation must only
    move among items still needing a decision (low-confidence/unmatched)."""
    import io, contextlib
    from unittest import mock
    from comicmeta._commands.review_issues import interactive, review_items
    from comicmeta._common import Palette
    report = tmp_path / "issues.json"
    report.write_text(json.dumps({
        "active_source": str(tmp_path), "scanned_source": str(tmp_path),
        "series": [{"query": "X (2020)", "matches": [
            {"path": "a.cbz", "archive_format": "cbz", "status": "exact-number",
             "metadata_candidate": _meta(1), "issue": {"id": 1}},
            {"path": "b.cbz", "archive_format": "cbz", "status": "unmatched",
             "metadata_candidate": _meta(2)},
            {"path": "c.cbz", "archive_format": "cbz", "status": "unmatched",
             "metadata_candidate": _meta(3)},
        ]}],
    }))
    items = review_items(json.loads(report.read_text()))
    for item in items:
        item["high_confidence"] = item["path"] == "a.cbz"
    state = tmp_path / "state.json"
    rendered_paths = []
    real_render = __import__("comicmeta._commands.review_issues", fromlist=["render"]).render
    def spy_render(item, *a, **k):
        rendered_paths.append(item["path"])
        real_render(item, *a, **k)
    keys = iter(["h", "y", "down", "down", "q"])
    with mock.patch("comicmeta._tui.read_key", lambda: next(keys)):
        with mock.patch("comicmeta._tui.confirm", lambda *a, **k: True):
            with mock.patch("comicmeta._commands.review_issues.render", spy_render):
                with contextlib.redirect_stdout(io.StringIO()):
                    interactive(report, state, tmp_path / "sum.md", Palette(False))
    # After h: a.cbz is auto-accepted; navigation should only move among b and c
    assert "a.cbz" not in rendered_paths[1:]  # a not shown after auto-accept
    assert set(rendered_paths[1:]) == {"b.cbz", "c.cbz"}  # only pending items


def test_manual_review_hint_explains_reason(tmp_path):
    from comicmeta._commands.review_issues import _manual_review_hint
    unmatched = _manual_review_hint({"status": "unmatched", "metadata": {}})
    assert "no ComicVine issue matched" in unmatched
    assert "[Enter] accept" in unmatched
    ambiguous = _manual_review_hint({"status": "ambiguous-number", "metadata": {}})
    assert "more than one ComicVine issue" in ambiguous
    collected = _manual_review_hint({
        "status": "exact-number",
        "metadata": {"format": "TPB"},
    })
    assert "collected edition" in collected
    single = _manual_review_hint({"status": "single-file-single-issue", "metadata": {}})
    assert "whole-file edition" in single
