from comicmeta import _comicvine
from comicmeta._commands.fetch_issues import build_report
from pathlib import Path


def test_canonical_issue_number():
    assert _comicvine.canonical_issue_number("001") == "1"
    assert _comicvine.canonical_issue_number("1.50") == "1.5"
    assert _comicvine.canonical_issue_number("-1") == "-1"
    assert _comicvine.canonical_issue_number("AU") == "au"


selection = {
    "candidate_id": 3225,
    "name": "Hawkeye",
    "publisher": "Marvel",
    "start_year": "1983",
    "status": "selected",
}
items = [
    {"path": "Marvel/Hawkeye (1983)/Hawkeye (1983) #001.cbr", "format": "cbr", "issue_number_from_filename": "001"},
    {"path": "Marvel/Hawkeye (1983)/Hawkeye (1983) #002.cbr", "format": "cbr", "issue_number_from_filename": "002"},
]
issues = [
    {"id": 10, "issue_number": "1", "name": "Point Blank", "cover_date": "1983-09-01", "site_detail_url": "https://example/10"},
    {"id": 11, "issue_number": "2", "name": "Questions", "cover_date": "1983-10-01", "site_detail_url": "https://example/11"},
]


def test_match_files_exact_number():
    matches = _comicvine.match_files("Hawkeye (1983)", items, issues, selection)
    assert [match["status"] for match in matches] == ["exact-number", "exact-number"]
    assert matches[0]["metadata_candidate"]["series"] == "Hawkeye"
    assert matches[0]["metadata_candidate"]["volume"] == "1983"
    assert matches[0]["metadata_candidate"]["number"] == "1"
    assert matches[0]["metadata_candidate"]["year"] == "1983"
    assert matches[0]["metadata_candidate"]["month"] == "9"
    assert matches[0]["metadata_candidate"]["format"] == "Issue"


def test_match_files_single_file():
    single = _comicvine.match_files(
        "Batman: Year One: The Deluxe Edition (2017)",
        [{"path": "DC/Batman (2017)/Batman HC.cbr", "format": "cbr", "issue_number_from_filename": None}],
        [{"id": 20, "issue_number": "1", "name": None, "cover_date": "2017-01-01"}],
        {**selection, "candidate_id": 104042, "name": "Batman: Year One: The Deluxe Edition", "publisher": "DC Comics", "start_year": "2017"},
    )
    assert single[0]["status"] == "single-file-single-issue"
    assert single[0]["metadata_candidate"]["format"] == "Hardcover"


def test_build_report():
    candidates = {
        "source": "/srv/kavita/comics",
        "items": [{**item, "query": "Hawkeye (1983)", "status": "review-required"} for item in items],
    }
    selections = {"selections": {"Hawkeye (1983)": selection}}
    report = build_report(candidates, selections, {"active_source": "/srv/comics"}, lambda _: issues)
    assert report["active_source"] == "/srv/comics"
    assert len(report["series"]) == 1
    assert report["series"][0]["unmatched_api_issues"] == []


def assert_never_fetch():
    raise AssertionError("fetcher must not run for a query with no review-required files")


def test_build_report_skips_selected_query_without_review_required_files(capsys):
    """A selected volume whose local files are no longer review-required (already
    fetched or the scan changed) must not abort the whole fetch report."""
    candidates = {
        "source": "/srv/kavita/comics",
        "items": [{**item, "query": "Hawkeye (1983)", "status": "selected"} for item in items],
    }
    selections = {"selections": {"Hawkeye (1983)": selection}}
    report = build_report(
        candidates, selections, {"active_source": "/srv/comics"}, lambda _: assert_never_fetch()
    )
    assert report["series"] == []
    assert report["skipped_queries"] == 1
    # The old per-volume SKIP_QUERY line was noisy console noise; skipping is
    # now reported as a count in the report and one summary line, not a flood.
    assert "SKIP_QUERY" not in capsys.readouterr().err
