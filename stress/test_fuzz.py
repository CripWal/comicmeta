"""Property-based fuzzing for comicmeta core parsing helpers.

Runs Hypothesis against pure functions (issue-number parsing, canonical
number normalization, humanize, metadata_candidate) with adversarial inputs:
empty strings, huge numbers, unicode, control characters, malformed dates,
missing fields, weird types. Invariants must hold for every input; nothing may
raise an unexpected exception.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from comicmeta import _humanize
from comicmeta._archive import audit_existing_metadata, read_comicinfo, root_comicinfo
from comicmeta._commands.discover import folder_year, issue_number, title_for_query
from comicmeta._comicvine import canonical_issue_number, date_parts, inferred_format, plain_text


@settings(max_examples=500, deadline=None)
@given(st.text(max_size=100))
def test_issue_number_never_crashes(name):
    result = issue_number(Path(name + ".cbz"))
    if result is not None:
        assert isinstance(result, str)


@settings(max_examples=500, deadline=None)
@given(st.text(max_size=100))
def test_title_for_query_never_crashes(name):
    result = title_for_query(Path(name) / "file.cbz")
    assert isinstance(result, str)


@settings(max_examples=500, deadline=None)
@given(st.text(max_size=100))
def test_folder_year_extracts_4digit_or_none(folder):
    year = folder_year(folder)
    if year is not None:
        assert len(year) == 4 and year.isdigit()


@settings(max_examples=500, deadline=None)
@given(st.one_of(st.none(), st.integers(), st.floats(), st.text(), st.booleans()))
def test_canonical_issue_number_is_stable(value):
    result = canonical_issue_number(value)
    assert result is None or isinstance(result, str)


@settings(max_examples=500, deadline=None)
@given(st.one_of(st.none(), st.integers(), st.floats(), st.text(max_size=100), st.booleans()))
def test_plain_text_never_crashes(value):
    result = plain_text(value)
    assert result is None or isinstance(result, str)


@settings(max_examples=500, deadline=None)
@given(st.dictionaries(st.text(max_size=30), st.one_of(st.none(), st.integers(), st.text(max_size=100))))
def test_date_parts_never_crashes(issue):
    result = date_parts(issue)
    assert isinstance(result, dict)


@settings(max_examples=500, deadline=None)
@given(st.text(max_size=100), st.text(max_size=100))
def test_inferred_format_never_crashes(query, path):
    fmt, kind = inferred_format(query, path)
    assert isinstance(fmt, str) and isinstance(kind, str)


@settings(max_examples=500, deadline=None)
@given(st.one_of(st.none(), st.integers(), st.floats(), st.text(), st.booleans(), st.lists(st.integers())))
def test_pretty_bytes_never_crashes(value):
    try:
        result = _humanize.pretty_bytes(value)  # type: ignore[arg-type]
        assert isinstance(result, str)
    except (TypeError, ValueError, OverflowError):
        pass  # non-numeric input is allowed to fail cleanly


@settings(max_examples=500, deadline=None)
@given(st.one_of(st.none(), st.integers(), st.floats(), st.text()))
def test_pretty_duration_never_crashes(value):
    try:
        result = _humanize.pretty_duration(value)  # type: ignore[arg-type]
        assert isinstance(result, str)
    except (TypeError, ValueError, OverflowError):
        pass


@settings(max_examples=200, deadline=None)
@given(
    st.text(min_size=0, max_size=80),
    st.one_of(st.none(), st.text(max_size=20)),
    st.one_of(st.none(), st.text(max_size=20)),
)
def test_metadata_candidate_never_crashes(query, number, title):
    from comicmeta._comicvine import metadata_candidate
    selection = {"candidate_id": 123, "name": "X"}
    issue = {
        "id": 1,
        "name": title,
        "issue_number": number,
        "cover_date": "2020-01-01",
        "store_date": None,
        "site_detail_url": "http://example.com",
    }
    result = metadata_candidate(selection, query, "Marvel/X (2020)/X (2020) #001.cbz", issue)
    assert isinstance(result, dict)


@settings(max_examples=200, deadline=None)
@given(st.lists(st.integers(min_value=0), max_size=50), st.integers(min_value=1, max_value=50))
def test_progress_bar_bounds(done_values, total):
    from comicmeta._common import progress_bar
    for done in done_values:
        bar = progress_bar(done, total)
        assert isinstance(bar, str)


@settings(max_examples=200, deadline=None)
@given(
    st.dictionaries(
        st.text(max_size=40),
        st.one_of(st.none(), st.text(max_size=40), st.integers()),
    )
)
def test_audit_existing_metadata_never_crashes(fields):
    """Write arbitrary metadata into a CBZ and audit it — must not raise."""
    import tempfile
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "X (2020) /X (2020) #001.cbz".replace(" ", "_")
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("001.jpg", b"page")
            archive.writestr("ComicInfo.xml", "<ComicInfo>" + "".join(
                f"<{k}>{v}</{k}>" for k, v in fields.items()
            ) + "</ComicInfo>")
        audit = audit_existing_metadata(path, "2020", "001")
        assert isinstance(audit, dict)
        assert "complete" in audit and "issues" in audit


@settings(max_examples=200, deadline=None)
@given(st.lists(st.text(max_size=50), max_size=30))
def test_load_json_and_atomic_json_roundtrip(data):
    """atomic_json writes a file that load_json can always read back."""
    import tempfile
    from comicmeta._common import atomic_json, load_json
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "state.json"
        value = {"items": data}
        atomic_json(path, value)
        loaded = load_json(path)
        assert loaded == value
