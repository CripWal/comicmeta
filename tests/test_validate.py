import zipfile

import pytest

from comicmeta._commands.validate import validate


def build_archive(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("001.jpg", b"page")
        archive.writestr(
            "ComicInfo.xml",
            b"<ComicInfo><Series>Hawkeye</Series><Number>1</Number><Volume>1994</Volume>"
            b"<Year>1994</Year><Format>Issue</Format></ComicInfo>",
        )


def fixture(tmp_path):
    relative = "Marvel/Hawkeye (1994)/Hawkeye (1994) #001.cbz"
    production = tmp_path / "production" / relative
    backup = tmp_path / "backup" / relative
    staged = tmp_path / "staging" / relative
    build_archive(production)
    build_archive(backup)
    build_archive(staged)
    from comicmeta import _archive
    original_hash = _archive.sha256(production)
    staged_hash = _archive.sha256(staged)
    mapping = {
        relative: {
            "series": "Hawkeye",
            "number": "1",
            "volume": "1994",
            "year": "1994",
            "format": "Issue",
        }
    }
    return tmp_path, relative, mapping, original_hash, staged_hash


def test_validate(tmp_path):
    root, relative, mapping, original_hash, staged_hash = fixture(tmp_path)
    results = validate(
        root / "staging",
        root / "production",
        root / "backup",
        mapping,
        {relative: {"path": relative, "source_sha256": original_hash}},
        {relative: {"path": relative, "after": staged_hash}},
    )
    assert results == [{"path": relative, "before": original_hash, "after": staged_hash}]


def test_validate_detects_production_change(tmp_path):
    root, relative, mapping, original_hash, staged_hash = fixture(tmp_path)
    (root / "production" / relative).write_bytes(b"changed")
    with pytest.raises(ValueError, match="production hash changed"):
        validate(
            root / "staging",
            root / "production",
            root / "backup",
            mapping,
            {relative: {"path": relative, "source_sha256": original_hash}},
            {relative: {"path": relative, "after": staged_hash}},
        )


def test_staging_write_and_validate_extended_metadata(tmp_path):
    from comicmeta import _archive
    from comicmeta._commands.stage import prepare
    from comicmeta._commands.write import execute
    import json

    relative = "Marvel/Hawkeye (1994)/Hawkeye (1994) #001.cbz"
    production = tmp_path / "production" / relative
    production.parent.mkdir(parents=True)
    with zipfile.ZipFile(production, "w") as archive:
        archive.writestr("001.jpg", b"page")
    mapping = {relative: {
        "series": "Hawkeye", "series_sort": "Hawkeye", "volume": "1994", "number": "1",
        "year": "1994", "format": "Issue", "writer": "A. Writer;B. Writer",
        "characters": "Hero;Sidekick", "summary": "A & B", "comicvine_issue_id": 42,
    }}
    staging = tmp_path / "staging"
    copy_items = prepare(tmp_path / "production", staging, mapping)
    original_hash = _archive.sha256(production)
    write_report = tmp_path / "write.json"
    mapping_path = tmp_path / "mapping.json"
    mapping_path.write_text(json.dumps(mapping))
    execute(staging, mapping_path, tmp_path / "backup", write_report, None)
    results = validate(
        staging, tmp_path / "production", tmp_path / "backup", mapping,
        {item["path"]: item for item in copy_items},
        {item["path"]: item for item in json.loads(write_report.read_text())["items"]},
    )
    assert results[0]["before"] == original_hash
    assert _archive.sha256(production) == original_hash
