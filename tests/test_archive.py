import zipfile
from pathlib import Path

from comicmeta import _archive


def make_cbz(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("001.jpg", b"page")


def test_archives_excludes_backup_dir(tmp_path):
    comic = tmp_path / "Marvel/Hawkeye (1983)/Hawkeye (1983) #001.cbz"
    make_cbz(comic)
    backup = tmp_path / "comicmeta-backups/latest/Marvel/Hawkeye (1983)/Hawkeye (1983) #001.cbz"
    make_cbz(backup)
    found = _archive.archives(tmp_path, exclude={"comicmeta-backups"})
    assert [p.relative_to(tmp_path).as_posix() for p in found] == [
        "Marvel/Hawkeye (1983)/Hawkeye (1983) #001.cbz"
    ]


def test_archives_no_exclude_includes_all(tmp_path):
    make_cbz(tmp_path / "a.cbz")
    make_cbz(tmp_path / "backup/b.cbz")
    assert len(_archive.archives(tmp_path)) == 2


def test_comicinfo_xml_serializes_lists_and_escapes_text():
    xml = _archive.comicinfo_xml({
        "series": "A & B", "volume": "2020", "number": "1", "year": "2020", "format": "Issue",
        "writer": ["A <Writer>", "B"], "characters": "Hero; Sidekick", "summary": "<unsafe> & text",
        "comicvine_issue_id": 42,
    }).decode()
    assert "A &amp; B" in xml
    assert "A &lt;Writer&gt;;B" in xml
    assert "Hero; Sidekick" in xml
    assert "comicvine_issue_id" not in xml
