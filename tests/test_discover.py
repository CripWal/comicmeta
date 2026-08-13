import json
import zipfile
from pathlib import Path
from unittest import mock

from comicmeta._commands.discover import _same_identity, rescan


def make_cbz(root: Path, relative: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("001.jpg", b"page")


def fake_search(api_key, query, limit, timeout=30, user_agent=None):
    return [{
        "id": 3225, "name": query, "start_year": "1983", "count_of_issues": 4,
        "publisher": {"name": "Marvel"}, "site_detail_url": "https://cv.example/3225",
    }]


def test_rescan_queries_all_on_first_run(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    make_cbz(tmp_path, "Marvel/Hawkeye (1983)/Hawkeye (1983) #001.cbz")
    make_cbz(tmp_path, "Marvel/Hawkeye (1983)/Hawkeye (1983) #002.cbz")
    with mock.patch("comicmeta._comicvine.search_volumes", fake_search):
        result = rescan(tmp_path, tmp_path / "candidates.json", "KEY", 10)
    assert result["reused"] == 0
    assert result["queried"] == 2
    assert len(result["added"]) == 2


def test_rescan_reuses_unchanged_without_key(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    make_cbz(tmp_path, "Marvel/Hawkeye (1983)/Hawkeye (1983) #001.cbz")
    with mock.patch("comicmeta._comicvine.search_volumes", fake_search):
        rescan(tmp_path, tmp_path / "candidates.json", "KEY", 10)
    with mock.patch("comicmeta._comicvine.search_volumes") as search:
        result = rescan(tmp_path, tmp_path / "candidates.json", None, 10)
    assert result["reused"] == 1
    assert result["queried"] == 0
    assert result["needs_api_key"] == []
    search.assert_not_called()


def test_rescan_flags_new_file_without_key(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    make_cbz(tmp_path, "Marvel/Hawkeye (1983)/Hawkeye (1983) #001.cbz")
    with mock.patch("comicmeta._comicvine.search_volumes", fake_search):
        rescan(tmp_path, tmp_path / "candidates.json", "KEY", 10)
    make_cbz(tmp_path, "Marvel/Hawkeye (1983)/Hawkeye (1983) #003.cbz")
    result = rescan(tmp_path, tmp_path / "candidates.json", None, 10)
    assert result["reused"] == 1
    assert result["needs_api_key"] == ["Marvel/Hawkeye (1983)/Hawkeye (1983) #003.cbz"]


def test_rescan_queries_only_new_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    make_cbz(tmp_path, "Marvel/Hawkeye (1983)/Hawkeye (1983) #001.cbz")
    make_cbz(tmp_path, "Marvel/Hawkeye (1983)/Hawkeye (1983) #002.cbz")
    with mock.patch("comicmeta._comicvine.search_volumes", fake_search):
        rescan(tmp_path, tmp_path / "candidates.json", "KEY", 10)
    make_cbz(tmp_path, "Marvel/Hawkeye (1983)/Hawkeye (1983) #003.cbz")
    with mock.patch("comicmeta._comicvine.search_volumes") as search:
        search.side_effect = fake_search
        result = rescan(tmp_path, tmp_path / "candidates.json", "KEY", 10)
    assert result["reused"] == 2
    assert result["queried"] == 1
    assert result["added"] == ["Marvel/Hawkeye (1983)/Hawkeye (1983) #003.cbz"]
    assert search.call_count == 1


def test_rescan_drops_removed_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    make_cbz(tmp_path, "Marvel/Hawkeye (1983)/Hawkeye (1983) #001.cbz")
    with mock.patch("comicmeta._comicvine.search_volumes", fake_search):
        rescan(tmp_path, tmp_path / "candidates.json", "KEY", 10)
    (tmp_path / "Marvel/Hawkeye (1983)/Hawkeye (1983) #001.cbz").unlink()
    result = rescan(tmp_path, tmp_path / "candidates.json", "KEY", 10)
    assert result["removed"] == ["Marvel/Hawkeye (1983)/Hawkeye (1983) #001.cbz"]
    assert result["items"] == []


def test_same_identity():
    current = {"format": "cbz", "query": "Hawkeye (1983)", "issue_number_from_filename": "001", "has_comicinfo": False}
    assert _same_identity(current, dict(current)) is True
    changed = dict(current)
    changed["query"] = "Hawkeye"
    assert _same_identity(current, changed) is False


def test_rescan_preserves_cached_candidates_without_key(tmp_path, monkeypatch):
    """A keyless run must not degrade previously-queried candidates."""
    monkeypatch.chdir(tmp_path)
    make_cbz(tmp_path, "Marvel/Hawkeye (1983)/Hawkeye (1983) #001.cbz")
    report = tmp_path / "candidates.json"
    report.write_text(json.dumps({"items": [{
        "path": "Marvel/Hawkeye (1983)/Hawkeye (1983) #001.cbz",
        "format": "cbz", "has_comicinfo": False, "query": "Hawkeye (1983)",
        "issue_number_from_filename": "001",
        "candidates": [{"id": 3225}], "status": "review-required",
    }]}))
    result = rescan(tmp_path, report, None, 10)
    assert result["reused"] == 1
    assert result["needs_api_key"] == []
    written = json.loads(report.read_text())
    assert written["items"][0]["status"] == "review-required"
    assert written["items"][0]["candidates"] == [{"id": 3225}]


def test_audit_item_marks_incomplete_existing(tmp_path):
    from comicmeta._commands.discover import audit_item
    cbz = tmp_path / "X (2020)" / "X (2020) #001.cbz"
    cbz.parent.mkdir(parents=True)
    with zipfile.ZipFile(cbz, "w") as archive:
        archive.writestr("001.jpg", b"page")
        archive.writestr("ComicInfo.xml", "<ComicInfo><Series>X</Series></ComicInfo>")
    item = {"query": "X (2020)", "issue_number_from_filename": "001", "has_comicinfo": True}
    audit_item(cbz, item)
    assert item["status"] == "review-required"
    assert any("volume" in issue for issue in item["existing_issues"])


def test_audit_item_skips_complete_existing(tmp_path):
    from comicmeta._commands.discover import audit_item
    cbz = tmp_path / "X (2020)" / "X (2020) #001.cbz"
    cbz.parent.mkdir(parents=True)
    xml = ("<ComicInfo><Series>X</Series><Volume>2020</Volume><Number>1</Number>"
           "<Year>2020</Year><Format>Issue</Format></ComicInfo>")
    with zipfile.ZipFile(cbz, "w") as archive:
        archive.writestr("001.jpg", b"page")
        archive.writestr("ComicInfo.xml", xml)
    item = {"query": "X (2020)", "issue_number_from_filename": "001", "has_comicinfo": True}
    audit_item(cbz, item)
    assert item["status"] == "skipped-existing-comicinfo"
    assert item["existing_comicinfo"]["complete"] is True


def test_audit_flags_volume_year_conflict(tmp_path):
    from comicmeta._commands.discover import audit_item
    cbz = tmp_path / "X (2020)" / "X (2020) #001.cbz"
    cbz.parent.mkdir(parents=True)
    xml = ("<ComicInfo><Series>X</Series><Volume>1999</Volume><Number>1</Number>"
           "<Year>2020</Year><Format>Issue</Format></ComicInfo>")
    with zipfile.ZipFile(cbz, "w") as archive:
        archive.writestr("001.jpg", b"page")
        archive.writestr("ComicInfo.xml", xml)
    item = {"query": "X (2020)", "issue_number_from_filename": "001", "has_comicinfo": True}
    audit_item(cbz, item)
    assert item["status"] == "review-required"
    assert any("volume 1999" in issue for issue in item["existing_issues"])


def test_issue_number_v5_style():
    from comicmeta._commands.discover import issue_number
    assert issue_number(Path("Aquaman v5 000 (1994).cbz")) == "000"
    assert issue_number(Path("Aquaman v5 075 (2000).cbz")) == "075"
    assert issue_number(Path("Aquaman 057 (1999).cbz")) == "057"


def test_issue_number_hash_style_still_works():
    from comicmeta._commands.discover import issue_number
    assert issue_number(Path("Hawkeye (1983) #001.cbz")) == "001"
    assert issue_number(Path("Old Man Hawkeye (2018) #011.cbz")) == "011"


def test_issue_number_of_n_run_style():
    from comicmeta._commands.discover import issue_number
    assert issue_number(Path("Daredevil 01 (of 5) (1993) (Digital) (Zone-Empire).cbz")) == "01"
    assert issue_number(Path("Daredevil 05 (of 5) (1994) (Digital) (Zone-Empire).cbz")) == "05"
    assert issue_number(Path("Daredevil 06 (of 06) (2002) (digital) (Minutemen-PhD).cbz")) == "06"


def test_issue_number_omits_volume_tags():
    from comicmeta._commands.discover import issue_number
    # TPB volumes like `Daredevil Omnibus v01 (2017)` are collections, not issues.
    assert issue_number(Path("Daredevil Omnibus v01 (2017) (Digital-Empire).cbz")) is None


def test_title_for_query_prefers_series_folder():
    from comicmeta._commands.discover import title_for_query
    assert title_for_query(Path("DC/Batman (1940)/Batman (1940) #001.cbz")) == "Batman (1940)"
    assert title_for_query(Path("DC/Hawkeye (1983)/Hawkeye (1983) #001.cbz")) == "Hawkeye (1983)"
    assert title_for_query(Path("DC/Superman (1987)/Superman (1987) #002.cbz")) == "Superman (1987)"


def test_title_for_query_loose_file_uses_filename():
    from comicmeta._commands.discover import title_for_query
    # Loose files in a publisher/collection root must not search for the
    # folder name ("DC") — that returns unrelated series. The cleaned filename
    # is the series title instead.
    assert title_for_query(Path(
        "DC/Batman - The Dark Knight Returns 01 (of 04) (1986) "
        "(digital) (Minutemen-InnerDemons).cbr"
    )) == "Batman - The Dark Knight Returns (1986)"
    assert title_for_query(Path(
        "loose/Captain America 001 (1968) (digital) (Empire).cbz"
    )) == "Captain America (1968)"


def test_canonical_issue_number_special_values():
    from comicmeta._comicvine import canonical_issue_number
    assert canonical_issue_number("0") == "0"
    assert canonical_issue_number("000") == "0"
    assert canonical_issue_number("1000000") == "1000000"
    assert canonical_issue_number("075") == "75"
