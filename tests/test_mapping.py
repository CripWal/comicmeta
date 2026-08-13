import argparse
import pytest

from comicmeta._commands.mapping import generate_mapping, run

cbz = "Marvel/Hawkeye (1994)/Hawkeye (1994) #001.cbz"
cbr = "Marvel/Hawkeye (1983)/Hawkeye (1983) #001.cbr"
candidates = {"series": [{"matches": [
    {"path": cbz, "archive_format": "cbz"},
    {"path": cbr, "archive_format": "cbr"},
]}]}
metadata = {
    "series": "Hawkeye", "volume": "1994", "number": "1", "year": "1994",
    "format": "Issue", "publisher": "Marvel", "comicvine_issue_id": 10,
    "format_reason": "fixture",
}
review = {"reviews": {
    cbz: {"status": "accepted", "metadata": metadata},
    cbr: {"status": "accepted", "metadata": {**metadata, "volume": "1983", "year": "1983"}},
}}


def test_generate_mapping_cbz_only():
    mapping, skipped = generate_mapping(candidates, review)
    assert list(mapping) == [cbz]
    assert mapping[cbz]["series"] == "Hawkeye"
    assert mapping[cbz]["comicvine_issue_id"] == 10
    assert "format_reason" not in mapping[cbz]
    assert skipped == [f"{cbr}: archive-format=cbr"]


def test_mapping_writes_future_kavita_export(tmp_path):
    from comicmeta._commands.mapping import kavita_export
    payload = kavita_export({cbz: metadata})
    assert payload["items"][0]["external_ids"] == {"comicvine_issue_id": 10}
    assert payload["items"][0]["metadata"]["series"] == "Hawkeye"


def test_generate_mapping_missing_required():
    with pytest.raises(ValueError, match="missing required fields"):
        generate_mapping(candidates, {"reviews": {cbz: {"status": "accepted", "metadata": {"series": "Hawkeye"}}}})


def test_generate_mapping_accepts_manual():
    manual_review = {"reviews": {
        cbz: {"status": "manual", "metadata": metadata},
    }}
    mapping, skipped = generate_mapping(candidates, manual_review)
    assert list(mapping) == [cbz]


def test_run_tolerates_stale_reviews(tmp_path):
    """Regression: rebuilt candidates (Aquaman replaced old Hawkeye queries) left
    old review entries in state; the exact count check must not fail."""
    issue_candidates = tmp_path / "aquaman-issues.json"
    issue_candidates.write_text('{"series": [{"matches": [{"path": "DC/Aquaman (1994)/Aquaman (1994) #000.cbz", "archive_format": "cbz"}]}]}')
    issue_state = tmp_path / "aquaman-state.json"
    issue_state.write_text('{"reviews": {'
        '"DC/Aquaman (1994)/Aquaman (1994) #000.cbz": {"status": "auto-accepted", "metadata": %s},'
        '"Marvel/Hawkeye (1983)/Hawkeye (1983) #001.cbz": {"status": "auto-accepted", "metadata": %s}'
        '}}' % (__import__("json").dumps(metadata), __import__("json").dumps(metadata)))
    out = tmp_path / "mapping.json"
    run(argparse.Namespace(candidates=issue_candidates, review=issue_state, output=out))
    mapping = __import__("json").loads(out.read_text())
    assert "DC/Aquaman (1994)/Aquaman (1994) #000.cbz" in mapping
    assert "Hawkeye" not in "".join(mapping)  # stale reviews not re-mapped


def test_run_partial_review_writes_reviewed_subset(tmp_path, capsys):
    """A partially-reviewed library must still map what is reviewed, warning
    about the deferred candidates instead of failing the whole write."""
    issue_candidates = tmp_path / "issues.json"
    issue_candidates.write_text('{"series": [{"matches": ['
        '{"path": "DC/Aquaman (1994)/Aquaman (1994) #000.cbz", "archive_format": "cbz"},'
        '{"path": "Marvel/Avengers Omnibus/Avengers Omnibus.cbz", "archive_format": "cbz"}'
        ']}]}')
    issue_state = tmp_path / "state.json"
    issue_state.write_text('{"reviews": {'
        '"DC/Aquaman (1994)/Aquaman (1994) #000.cbz": {"status": "auto-accepted", "metadata": %s}'
        '}}' % __import__("json").dumps(metadata))
    out = tmp_path / "mapping.json"
    run(argparse.Namespace(candidates=issue_candidates, review=issue_state, output=out))
    mapping = __import__("json").loads(out.read_text())
    assert list(mapping) == ["DC/Aquaman (1994)/Aquaman (1994) #000.cbz"]
    captured = capsys.readouterr()
    assert "PARTIAL mapping" in captured.err
    assert "Avengers Omnibus" in captured.err
