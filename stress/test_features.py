"""Stress tests for the 0.5.40 feature batch: parallel fetching, auto-detect,
streaming dry-run, health, missing report, flag clearing, and progress ETA."""

from __future__ import annotations

import json
import time
import zipfile
from pathlib import Path
from unittest import mock

import pytest

from comicmeta import _archive, _comicvine


def make_cbz(path: Path, pages=3):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        for index in range(pages):
            archive.writestr(f"{index:03d}.jpg", b"page" * (index + 1))


def test_search_volumes_batch_concurrency_and_order():
    """Batch must preserve query order and run queries concurrently (rate-safe)."""
    queries = ["a", "b", "c", "d"]
    seen = {"order": []}
    delay = 0.02

    def fake_search(key, query, limit, **kwargs):
        time.sleep(delay)
        seen["order"].append(query)
        return [{"id": len(seen["order"]), "name": query}]

    with mock.patch("comicmeta._comicvine.search_volumes", fake_search):
        results = _comicvine.search_volumes_batch("k", queries, 10, request_delay=delay, concurrency=4)
    assert [r["query"] for r in results] == queries  # order preserved
    assert all(r["candidates"] for r in results)


def test_search_volumes_batch_empty():
    results = _comicvine.search_volumes_batch("k", [], 10)
    assert results == []


def test_search_volumes_batch_single():
    with mock.patch("comicmeta._comicvine.search_volumes", return_value=[{"id": 1}]):
        results = _comicvine.search_volumes_batch("k", ["only"], 10)
    assert results[0]["query"] == "only"
    assert results[0]["candidates"] == [{"id": 1}]


def test_search_volumes_batch_concurrency_one():
    """concurrency=1 must behave exactly like serial, no deadlock."""
    queries = [f"q{i}" for i in range(3)]
    hits = {"n": 0}
    lock = __import__("threading").Lock()

    def fake(key, query, limit, **kwargs):
        with lock:
            hits["n"] += 1
        return [{"id": hits["n"]}]

    with mock.patch("comicmeta._comicvine.search_volumes", fake):
        results = _comicvine.search_volumes_batch("k", queries, 10, request_delay=0.01, concurrency=1)
    assert len(results) == 3


def test_rescan_uses_batch(tmp_path, monkeypatch):
    from comicmeta._commands import discover
    make_cbz(tmp_path / "X (2020)/X (2020) #001.cbz")
    make_cbz(tmp_path / "Y (2021)/Y (2021) #001.cbz")
    called = {"batch": False}
    def fake_batch(key, queries, limit, **kwargs):
        called["batch"] = True
        return [{"query": q, "candidates": [{"id": i}]} for i, q in enumerate(queries)]
    with mock.patch("comicmeta._comicvine.search_volumes_batch", fake_batch):
        result = discover.rescan(tmp_path, tmp_path / "r.json", "key", 10,
                                 request_delay=0.01, concurrency=3)
    assert called["batch"] is True
    assert result["queried"] == 2
    assert all(item["candidates"] for item in result["items"])


def test_detect_source_walks_up(tmp_path, monkeypatch):
    from comicmeta import _config
    library = tmp_path / "comics"
    (library / "DC").mkdir(parents=True)
    (library / "Marvel").mkdir()
    deep = library / "DC" / "Hawkeye (2017)"
    deep.mkdir()
    monkeypatch.chdir(deep)
    assert _config.detect_source() == library


def test_detect_source_none_in_isolated_dir(tmp_path, monkeypatch):
    from comicmeta import _config
    isolated = tmp_path / "nowhere"
    isolated.mkdir()
    monkeypatch.chdir(isolated)
    assert _config.detect_source() is None


def test_dry_run_streams_and_unlinks(tmp_path):
    """Streaming dry-run leaves zero staging files behind (frees disk)."""
    from comicmeta._commands.write import _dry_run
    for i in range(3):
        make_cbz(tmp_path / "X (2020)/X (2020) #{:03d}.cbz".format(i + 1))
    mapping = tmp_path / "m.json"
    mapping.write_text(json.dumps({
        f"X (2020)/X (2020) #{i+1:03d}.cbz": {"series": "X", "volume": "2020",
            "number": str(i + 1), "year": "2020", "format": "Issue"} for i in range(3)
    }))
    _dry_run(tmp_path, mapping, tmp_path / "backup", tmp_path / "report.json")
    # temp staging is deleted by TemporaryDirectory; production untouched
    remaining = [p for p in tmp_path.rglob("*.cbz")]
    assert len(remaining) == 3  # originals intact


def test_dry_run_missing_mapped_file(tmp_path, capsys):
    from comicmeta._commands.write import _dry_run
    mapping = tmp_path / "m.json"
    mapping.write_text(json.dumps({"Nope (2000)/Nope (2000) #001.cbz": {"series": "X"}}))
    with pytest.raises(SystemExit):
        _dry_run(tmp_path, mapping, tmp_path / "b", tmp_path / "r")
    assert "does not exist" in capsys.readouterr().err


def test_health_scan_counts(tmp_path):
    from comicmeta._commands.health import scan
    make_cbz(tmp_path / "X (2020)/X (2020) #001.cbz")  # no metadata
    bad = tmp_path / "bad.cbz"
    bad.write_bytes(b"not a zip")
    result = scan(tmp_path)
    assert result["total"] == 2
    assert len(result["corrupt"]) == 1
    assert len(result["no_metadata"]) == 1


def test_health_deep_detects_corrupt_member(tmp_path):
    from comicmeta._commands.health import scan
    # write a CBZ then corrupt a byte so testzip fails
    path = tmp_path / "X (2020)/X (2020) #001.cbz"
    make_cbz(path)
    data = bytearray(path.read_bytes())
    data[len(data) // 2] ^= 0xFF
    path.write_bytes(bytes(data))
    result = scan(tmp_path, deep=True)
    assert len(result["corrupt"]) == 1


def test_missing_report_requires_candidates(tmp_path, monkeypatch, capsys):
    from comicmeta._commands.missing import run
    from argparse import Namespace
    import io, contextlib
    from comicmeta import _config
    monkeypatch.setattr(_config, "get", lambda flat, key: str(tmp_path / "nope.json"))
    with pytest.raises(SystemExit):
        with contextlib.redirect_stdout(io.StringIO()):
            run(Namespace(source=tmp_path, no_color=True))
    assert "issue candidates report not found" in capsys.readouterr().err


def test_missing_reports_gaps(tmp_path, monkeypatch):
    from comicmeta._commands.missing import run
    from argparse import Namespace
    import io, contextlib
    from comicmeta import _config
    report = tmp_path / "issues.json"
    report.write_text(json.dumps({"series": [{"query": "X (2020)", "unmatched_api_issues": [
        {"number": "5", "name": "Issue 5"}]}]}))
    monkeypatch.setattr(_config, "get", lambda flat, key: str(report) if key == "paths.issue_candidates" else "")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        run(Namespace(source=tmp_path, no_color=True))
    assert "X (2020) (1 missing)" in buf.getvalue()
    assert "#5" in buf.getvalue()


def test_clear_flags_removes_entries(tmp_path, monkeypatch):
    from comicmeta._commands.flags import clear_flags
    from comicmeta._common import Palette
    from argparse import Namespace
    import io, contextlib
    from comicmeta import _config
    vol = tmp_path / "vol.json"
    iss = tmp_path / "iss.json"
    vol.write_text(json.dumps({"selections": {"X (2020)": {"status": "flagged"}}}))
    iss.write_text(json.dumps({"reviews": {"Y.cbz": {"status": "flagged"}}}))
    monkeypatch.setattr(_config, "get", lambda flat, key: {
        "paths.volume_state": str(vol), "paths.issue_state": str(iss)}.get(key, ""))
    keys = iter(["enter", "enter"])
    with mock.patch("comicmeta._tui.read_key", lambda: next(keys)):
        with contextlib.redirect_stdout(io.StringIO()):
            clear_flags(Namespace(source=tmp_path, no_color=True), Palette(False))
    assert json.loads(vol.read_text())["selections"] == {}
    assert json.loads(iss.read_text())["reviews"] == {}


def test_progress_eta_format():
    from comicmeta._spinner import Spinner
    assert Spinner._fmt_eta(5) == "5s"
    assert Spinner._fmt_eta(75) == "1m15s"
    assert Spinner._fmt_eta(3725) == "1h02m"
