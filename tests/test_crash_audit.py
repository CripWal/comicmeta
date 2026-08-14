"""Regression tests for confirmed crash bugs (C1/C2/C3, H2/H3, M1/M2/M3)."""

import io
import contextlib
import json
import sys
from pathlib import Path
from unittest import mock

import pytest

from comicmeta._common import Palette


# ─── C1: review_volumes publisher may be a bare string ───

def string_publisher_report():
    return {
        "source": "/srv/comics",
        "items": [{
            "query": "Batman (2017)",
            "path": "Batman #001.cbr",
            "format": "cbr",
            "status": "review-required",
            "issue_number_from_filename": "001",
            "candidates": [{
                "id": 104042, "name": "Batman", "start_year": "2017",
                "publisher": "DC Comics", "count_of_issues": 1,
                "site_detail_url": "https://cv.example/104042",
            }],
        }],
    }


def test_c1_grouped_items_string_publisher():
    from comicmeta._commands.review_volumes import grouped_items
    groups = grouped_items(string_publisher_report())
    assert groups[0]["recommendation"]["id"] == 104042
    assert groups[0]["recommendation"]["score"] >= 0


def test_c1_selection_for_string_publisher():
    from comicmeta._commands.review_volumes import selection_for
    selection = selection_for({
        "id": 1, "name": "Batman", "start_year": "2017", "publisher": "DC Comics",
    })
    assert selection["publisher"] == "DC Comics"


def test_c1_render_group_string_publisher():
    from comicmeta._commands.review_volumes import grouped_items, render_group
    groups = grouped_items(string_publisher_report())
    state = {"selections": {}}
    with contextlib.redirect_stdout(io.StringIO()):
        render_group(groups[0], 0, groups, string_publisher_report(), state, {}, Palette(False), show_all=False)


# ─── C2: browse empty library must not IndexError ───

def test_c2_browse_empty_library_no_index_error(tmp_path):
    from comicmeta._commands import browse as B
    root = B._build_tree(tmp_path, set())
    assert len(B._visible_nodes(root)) == 1
    with mock.patch.object(B, "read_key", return_value="enter"):
        with mock.patch.object(B, "_render_tree", lambda *a, **k: None):
            with contextlib.redirect_stdout(io.StringIO()):
                code = B._browse(root, tmp_path, None, Palette(False))
    assert code == 0


# ─── C3: ComicVine non-numeric total must not crash ───

def test_c3_fetch_volume_issues_non_numeric_total():
    from comicmeta import _comicvine
    payload = {
        "error": "OK",
        "number_of_total_results": "not-a-number",
        "results": [{"id": 1, "issue_number": "1"}, {"id": 2, "issue_number": "2"}],
    }
    with mock.patch("comicmeta._comicvine._api_request", return_value=payload):
        issues = _comicvine.fetch_volume_issues("key", 123, 0.0)
    assert len(issues) == 2


# ─── H2: surrogate-escape paths + non-UTF8 prints ───

def test_h2_state_dir_surrogate_path():
    from comicmeta import _config
    weird = Path(b"/tmp/comicmeta-\xff".decode("utf-8", "surrogateescape"))
    result = _config.state_dir(weird)
    assert isinstance(result, Path)


def test_h2_configure_stream_errors_sets_backslashreplace():
    from comicmeta import cli
    out = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
    err = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
    with mock.patch.object(sys, "stdout", out), mock.patch.object(sys, "stderr", err):
        cli._configure_stream_errors()
    assert out.errors == "backslashreplace"
    assert err.errors == "backslashreplace"
    weird = Path(b"x-\xff".decode("utf-8", "surrogateescape"))
    out.write(str(weird))
    err.write(str(weird))


def test_h2_configure_stream_errors_guard_no_reconfigure():
    from comicmeta import cli

    class NoReconfigure:
        def reconfigure(self, **kwargs):
            raise AttributeError("no reconfigure")

    with mock.patch.object(sys, "stdout", NoReconfigure()), mock.patch.object(sys, "stderr", NoReconfigure()):
        cli._configure_stream_errors()


# ─── H3: dry-run unsafe mapping keys must die cleanly ───

def test_h3_dry_run_unsafe_absolute_key_dies_cleanly(tmp_path):
    from comicmeta._commands.write import _dry_run
    source = tmp_path / "source"
    source.mkdir()
    mapping = tmp_path / "m.json"
    mapping.write_text(json.dumps({"/etc/passwd": {"series": "X"}}))
    with pytest.raises(SystemExit):
        _dry_run(source, mapping, tmp_path / "backup", tmp_path / "r.json")


def test_h3_dry_run_parent_traversal_key_dies_cleanly(tmp_path):
    from comicmeta._commands.write import _dry_run
    source = tmp_path / "source"
    source.mkdir()
    mapping = tmp_path / "m.json"
    mapping.write_text(json.dumps({"../escape.cbz": {"series": "X"}}))
    with pytest.raises(SystemExit):
        _dry_run(source, mapping, tmp_path / "backup", tmp_path / "r.json")


# ─── M1: candidates without an id must be skipped ───

def test_m1_grouped_items_skips_candidate_without_id():
    from comicmeta._commands.review_volumes import grouped_items
    report = {
        "source": "/srv/comics",
        "items": [{
            "query": "X (2020)", "path": "X (2020)/X #001.cbr", "format": "cbr",
            "status": "review-required", "issue_number_from_filename": "001",
            "candidates": [{"name": "No Id", "start_year": "2020"}],
        }],
    }
    groups = grouped_items(report)
    assert groups[0]["candidates"] == []
    assert groups[0]["recommendation"] is None


# ─── M2: non-string summary must not crash render ───

def test_m2_render_non_string_summary(tmp_path):
    from comicmeta._commands.review_issues import render
    item = {
        "query": "X (2020)",
        "path": "X (2020)/X #001.cbz",
        "active_path": str(tmp_path / "X #001.cbz"),
        "scanned_path": str(tmp_path / "X #001.cbz"),
        "high_confidence": False,
        "status": "unmatched",
        "metadata": {"series": "X", "summary": 12345},
    }
    with contextlib.redirect_stdout(io.StringIO()):
        render(item, 0, [item], {"reviews": {}}, Palette(False))


# ─── M3: missing keys on JSON-derived dicts ───

def test_m3_review_items_tolerates_missing_keys():
    from comicmeta._commands.review_issues import review_items
    report = {
        "series": [
            {"matches": [{"path": None, "status": "unmatched"}]},
            "not-a-dict",
            {"query": "Q", "matches": [{"path": "Q/Q #1.cbz", "status": "exact-number"}]},
        ],
    }
    items = review_items(report)
    assert len(items) == 2


def test_m3_generate_mapping_tolerates_missing_path():
    from comicmeta._commands.mapping import generate_mapping
    candidates = {"series": [
        {"matches": [{"archive_format": "CBZ"}]},
        "not-a-dict",
    ]}
    mapping, skipped = generate_mapping(candidates, {"reviews": {}})
    assert mapping == {}


def test_m3_issue_review_complete_tolerates_malformed(tmp_path):
    from comicmeta._commands.review import _issue_review_complete
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"reviews": {}}))
    candidates = {"series": ["not-a-dict", {"matches": [{"status": "unmatched"}]}]}
    assert _issue_review_complete(state_path, candidates) is False


def test_m3_fetch_issues_skips_selection_without_candidate_id():
    from comicmeta._commands.fetch_issues import build_report

    def assert_never_fetch():
        raise AssertionError("fetcher must not run without a candidate_id")

    candidates = {"items": [{"query": "Q", "status": "review-required"}]}
    selections = {"selections": {"Q": {"status": "selected"}}}
    report = build_report(candidates, selections, {}, assert_never_fetch)
    assert report["series"] == []
    assert report["skipped_queries"] == 1


def test_m3_status_counts_tolerates_non_dict_series(tmp_path, monkeypatch):
    from comicmeta import _config
    from comicmeta._commands.status import _counts, _defaults
    monkeypatch.chdir(tmp_path)
    flat = _config.load(None)
    paths = _defaults(flat)
    paths["issue_candidates"].parent.mkdir(parents=True, exist_ok=True)
    paths["issue_candidates"].write_text(json.dumps({"series": ["not-a-dict", {"matches": []}]}))
    counts = _counts(paths)
    assert counts["issues"] == 0
