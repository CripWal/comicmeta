import zipfile
from pathlib import Path

from comicmeta._commands.inspect import read_comicinfo, write_comicinfo


def test_read_comicinfo(tmp_path):
    cbz = tmp_path / "a.cbz"
    with zipfile.ZipFile(cbz, "w") as archive:
        archive.writestr("001.jpg", b"page")
        archive.writestr("ComicInfo.xml",
                         "<ComicInfo><Series>Hawkeye</Series><Volume>1983</Volume>"
                         "<Number>1</Number><Year>1983</Year><Format>Issue</Format></ComicInfo>")
    data = read_comicinfo(cbz)
    assert data["series"] == "Hawkeye"
    assert data["number"] == "1"


def test_read_comicinfo_missing(tmp_path):
    cbz = tmp_path / "a.cbz"
    with zipfile.ZipFile(cbz, "w") as archive:
        archive.writestr("001.jpg", b"page")
    assert read_comicinfo(cbz) is None


def test_read_comicinfo_bad_zip(tmp_path):
    bad = tmp_path / "b.cbz"
    bad.write_bytes(b"not a zip")
    assert read_comicinfo(bad) is None


def test_write_comicinfo_creates(tmp_path):
    cbz = tmp_path / "a.cbz"
    with zipfile.ZipFile(cbz, "w") as archive:
        archive.writestr("001.jpg", b"page")
    write_comicinfo(cbz, {"series": "Hawkeye", "volume": "1983", "number": "1",
                          "year": "1983", "format": "Issue"})
    data = read_comicinfo(cbz)
    assert data["series"] == "Hawkeye"
    assert data["number"] == "1"


def test_read_comicinfo_xml_raw(tmp_path):
    cbz = tmp_path / "a.cbz"
    xml = "<ComicInfo><Series>Hawkeye</Series></ComicInfo>"
    with zipfile.ZipFile(cbz, "w") as archive:
        archive.writestr("001.jpg", b"page")
        archive.writestr("ComicInfo.xml", xml)
    from comicmeta._commands.inspect import read_comicinfo_xml
    assert read_comicinfo_xml(cbz) == xml


def test_read_comicinfo_xml_missing(tmp_path):
    cbz = tmp_path / "a.cbz"
    with zipfile.ZipFile(cbz, "w") as archive:
        archive.writestr("001.jpg", b"page")
    from comicmeta._commands.inspect import read_comicinfo_xml
    assert read_comicinfo_xml(cbz) is None


def test_view_partial_metadata_no_crash(tmp_path, monkeypatch):
    import io, contextlib
    from unittest import mock
    from pathlib import Path
    from comicmeta._commands.inspect import inspect_one
    from comicmeta._common import Palette
    cbz = tmp_path / "partial.cbz"
    with zipfile.ZipFile(cbz, "w") as archive:
        archive.writestr("001.jpg", b"page")
        archive.writestr("ComicInfo.xml", "<ComicInfo><Series>Hawkeye</Series></ComicInfo>")
    keys = iter(["v", "x"])
    buf = io.StringIO()
    with mock.patch("comicmeta._tui.read_key", lambda: next(keys)):
        with contextlib.redirect_stdout(buf):
            inspect_one(cbz.resolve(), tmp_path, tmp_path / "b", Palette(False))
    assert "<ComicInfo><Series>Hawkeye</Series></ComicInfo>" in buf.getvalue()
