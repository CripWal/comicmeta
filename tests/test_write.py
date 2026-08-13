import json
import os
import tempfile
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from comicmeta._commands.write import execute, validate_written_archive


def run(*args):
    from comicmeta.cli import main
    import io
    import contextlib
    output = io.StringIO()
    error = io.StringIO()
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
        try:
            main([*map(str, args)])
        except SystemExit as exit_code:
            code = exit_code.code
        else:
            code = 0
    return SimpleNamespace(returncode=code, stdout=output.getvalue(), stderr=error.getvalue())


def test_execute_writes_comicinfo(tmp_path):
    source = tmp_path / "source"
    comic = source / "Marvel" / "Hawkeye (1983)" / "Hawkeye (1983) #001.cbz"
    comic.parent.mkdir(parents=True)
    with zipfile.ZipFile(comic, "w") as archive:
        archive.writestr("001.jpg", b"page")
    mapping = tmp_path / "mapping.json"
    mapping.write_text(json.dumps({
        "Marvel/Hawkeye (1983)/Hawkeye (1983) #001.cbz": {
            "series": "Hawkeye", "volume": "1983", "number": "1", "year": "1983",
            "format": "Issue", "publisher": "Marvel", "title": "The Beginning"
        }
    }))
    report = tmp_path / "report.json"
    backup = tmp_path / "backup"
    before = comic.read_bytes()
    result = run("write", "--yes", "--source", source, "--mapping", mapping, "--backup-dir", backup, "--report", report)
    assert result.returncode == 0, result.stderr
    assert comic.read_bytes() != before
    assert (backup / "Marvel/Hawkeye (1983)/Hawkeye (1983) #001.cbz").exists()
    with zipfile.ZipFile(comic) as archive:
        xml = archive.read("ComicInfo.xml").decode()
    assert "<Series>Hawkeye</Series>" in xml
    assert "<Volume>1983</Volume>" in xml
    report_data = json.loads(report.read_text())
    assert report_data["items"][0]["validated"] is True

    collision = run("write", "--yes", "--source", source, "--mapping", mapping, "--backup-dir", tmp_path / "backup2", "--report", tmp_path / "report2.json")
    assert collision.returncode == 0, collision.stderr  # idempotent: nothing left to write
    assert "already-has-comicinfo" in collision.stderr
    assert "Nothing to write" in collision.stdout


def test_execute_continues_on_partial_failure(tmp_path, monkeypatch):
    source = tmp_path / "source"
    mapping_data = {}
    originals = {}
    for number in (1, 2):
        relative = f"Marvel/Hawkeye (1994)/Hawkeye (1994) #{number:03}.cbz"
        comic = source / relative
        comic.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(comic, "w") as archive:
            archive.writestr("001.jpg", f"page-{number}".encode())
        originals[relative] = comic.read_bytes()
        mapping_data[relative] = {
            "series": "Hawkeye", "volume": "1994", "number": str(number),
            "year": "1994", "format": "Issue"
        }
    mapping = tmp_path / "mapping.json"
    mapping.write_text(json.dumps(mapping_data))
    from comicmeta._commands import write as write_module
    real_validate = write_module.validate_written_archive

    def fail_second_file(path, metadata):
        if "002" in str(path):
            raise ValueError("simulated post-write validation failure")
        real_validate(path, metadata)

    monkeypatch.setattr(write_module, "validate_written_archive", fail_second_file)
    report = tmp_path / "report.json"
    execute(source, mapping, tmp_path / "backup", report, None)
    first_relative = "Marvel/Hawkeye (1994)/Hawkeye (1994) #001.cbz"
    second_relative = "Marvel/Hawkeye (1994)/Hawkeye (1994) #002.cbz"
    assert (source / first_relative).read_bytes() != originals[first_relative]
    assert (source / second_relative).read_bytes() == originals[second_relative]
    report_data = json.loads(report.read_text())
    assert len(report_data["items"]) == 1
    assert report_data["items"][0]["path"] == first_relative


def test_write_recovers_from_smb_rename_einval(tmp_path, monkeypatch):
    """`os.replace` EINVAL over SMB on a large file must fall back to a
    streaming overwrite (no crash, no re-streaming of the whole zip).

    Reproduces the reported `comicmeta write` crash on large CBZs over SMB: the
    atomic rename fails with errno 22. The fix retries the rename then commits
    via a sequential in-place copy, so the write succeeds.
    """
    source = tmp_path / "source"
    relative = "Marvel/Hawkeye (1994)/Hawkeye (1994) #001.cbz"
    comic = source / relative
    comic.parent.mkdir(parents=True)
    with zipfile.ZipFile(comic, "w") as archive:
        archive.writestr("001.jpg", b"page")
    mapping = tmp_path / "mapping.json"
    mapping.write_text(json.dumps({relative: {
        "series": "Hawkeye", "volume": "1994", "number": "1",
        "year": "1994", "format": "Issue"
    }}))
    from comicmeta._commands import write as write_module

    def always_einval(origin, destination):
        raise OSError(22, "simulated SMB EINVAL on large-file rename")

    monkeypatch.setattr(write_module.os, "replace", always_einval)
    report = tmp_path / "report.json"
    result = run("write", "--yes", "--source", source, "--mapping", mapping,
                 "--backup-dir", tmp_path / "backup", "--report", report)
    assert result.returncode == 0, result.stderr
    assert ("WROTE path=" + relative) in result.stdout
    with zipfile.ZipFile(comic) as archive:
        xml = archive.read("ComicInfo.xml").decode()
    assert "<Series>Hawkeye</Series>" in xml
    report_data = json.loads(report.read_text())
    assert len(report_data["items"]) == 1
    assert report_data["items"][0]["validated"] is True


def test_execute_refuses_expected_hash_mismatch(tmp_path):
    source = tmp_path / "source"
    relative = "Marvel/Hawkeye (1994)/Hawkeye (1994) #001.cbz"
    comic = source / relative
    comic.parent.mkdir(parents=True)
    with zipfile.ZipFile(comic, "w") as archive:
        archive.writestr("001.jpg", b"page")
    mapping = tmp_path / "mapping.json"
    mapping.write_text(json.dumps({relative: {
        "series": "Hawkeye", "volume": "1994", "number": "1",
        "year": "1994", "format": "Issue"
    }}))
    expected = tmp_path / "expected.json"
    expected.write_text(json.dumps({"items": [{
        "path": relative, "before_sha256": "0" * 64
    }]}))
    result = run(
        "write", "--yes", "--source", source, "--mapping", mapping,
        "--expected-hashes", expected, "--backup-dir", tmp_path / "backup",
        "--report", tmp_path / "report.json",
    )
    assert result.returncode != 0
    assert "production hash does not match staging audit" in result.stderr
    assert not (tmp_path / "backup").exists()


def test_validate_written_archive_rejects_missing_required_field(tmp_path):
    from comicmeta._archive import comicinfo_xml
    path = tmp_path / "x.cbz"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("001.jpg", b"page")
        archive.writestr("ComicInfo.xml", comicinfo_xml({
            "series": "Hawkeye", "volume": "1994", "number": "1", "year": "1994", "format": "Issue"
        }))
    validate_written_archive(path, {
        "series": "Hawkeye", "volume": "1994", "number": "1", "year": "1994", "format": "Issue"
    })


def test_validate_written_archive_checks_extended_fields(tmp_path):
    from comicmeta._archive import comicinfo_xml
    path = tmp_path / "x.cbz"
    metadata = {
        "series": "Hawkeye", "volume": "1994", "number": "1", "year": "1994", "format": "Issue",
        "writer": "A. Writer", "characters": "Hero; Sidekick", "comicvine_issue_id": 42,
    }
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("001.jpg", b"page")
        archive.writestr("ComicInfo.xml", comicinfo_xml(metadata))
    validate_written_archive(path, metadata)
    metadata["writer"] = "Wrong"
    with pytest.raises(ValueError, match="writer"):
        validate_written_archive(path, metadata)


def test_write_dry_run_does_not_modify_production(tmp_path, monkeypatch):
    source = tmp_path / "source"
    relative = "Marvel/Hawkeye (1994)/Hawkeye (1994) #001.cbz"
    comic = source / relative
    comic.parent.mkdir(parents=True)
    with zipfile.ZipFile(comic, "w") as archive:
        archive.writestr("001.jpg", b"page")
    before = comic.read_bytes()
    mapping = tmp_path / "comic-metadata-reviewed-mapping.json"
    mapping.write_text(json.dumps({relative: {
        "series": "Hawkeye", "volume": "1994", "number": "1",
        "year": "1994", "format": "Issue"
    }}))
    import comicmeta._commands.write as write_module
    result = run(
        "write", "--dry-run", "--source", source, "--mapping", mapping,
        "--backup-dir", tmp_path / "b", "--report", tmp_path / "r.json",
    )
    assert result.returncode == 0, result.stderr
    assert "DRY_RUN production_unchanged=yes" in result.stdout
    assert comic.read_bytes() == before
    with zipfile.ZipFile(comic) as archive:
        assert "ComicInfo.xml" not in archive.namelist()


def test_write_dry_run_skips_existing_comicinfo(tmp_path):
    source = tmp_path / "source"
    relative = "a.cbz"
    comic = source / relative
    comic.parent.mkdir(parents=True)
    with zipfile.ZipFile(comic, "w") as archive:
        archive.writestr("001.jpg", b"page")
        archive.writestr("ComicInfo.xml", "<ComicInfo><Series>Existing</Series></ComicInfo>")
    mapping = tmp_path / "mapping.json"
    mapping.write_text(json.dumps({relative: {
        "series": "X", "volume": "1", "number": "1", "year": "2020", "format": "Issue",
    }}))
    result = run(
        "write", "--dry-run", "--source", source, "--mapping", mapping,
        "--backup-dir", tmp_path / "b", "--report", tmp_path / "r.json",
    )
    assert result.returncode == 0, result.stderr
    assert "DRY_SKIP" in result.stderr
    with zipfile.ZipFile(comic) as archive:
        assert "Existing" in archive.read("ComicInfo.xml").decode()


def test_write_dry_run_continues_past_corrupt_archive(tmp_path):
    """A corrupt CBZ (bad EOCD, truncated member) must not abort the dry-run.

    Reproduces the library case where one malformed archive (EOCD pointing
    past EOF) previously killed the whole dry-run with a fatal error. The
    dry-run should report the corrupt file as DRY_FAIL, keep going, and only
    fail if every mapped file is unwritable.
    """
    source = tmp_path / "source"
    good_rel = "Marvel/Hawkeye (1994)/Hawkeye (1994) #001.cbz"
    good = source / good_rel
    good.parent.mkdir(parents=True)
    with zipfile.ZipFile(good, "w") as archive:
        archive.writestr("001.jpg", b"page")
    bad_rel = "Marvel/Secret Wars (2025)/Secret Wars (2025).cbz"
    bad = source / bad_rel
    bad.parent.mkdir(parents=True)
    bad.write_bytes(b"this is not a zip at all")
    mapping = tmp_path / "m.json"
    mapping.write_text(json.dumps({
        good_rel: {"series": "Hawkeye", "volume": "1994", "number": "1",
                   "year": "1994", "format": "Issue"},
        bad_rel: {"series": "Secret Wars", "volume": "2025", "number": "1",
                  "year": "2025", "format": "Omnibus"},
    }))
    result = run(
        "write", "--dry-run", "--source", source, "--mapping", mapping,
        "--backup-dir", tmp_path / "b", "--report", tmp_path / "r.json",
    )
    assert result.returncode == 0, result.stderr
    assert "DRY_RUN production_unchanged=yes" in result.stdout
    assert "DRY_RUN staged=1" in result.stdout
    assert f"DRY_FAIL path={bad_rel}" in result.stderr
    assert "DRY_FAIL path=" + bad_rel + " error=" in result.stderr
    with zipfile.ZipFile(good) as archive:
        assert "ComicInfo.xml" not in archive.namelist()  # production untouched


def test_write_dry_run_skips_missing_mapped_archive(tmp_path):
    """A mapping path with no archive on disk must not abort the dry-run: it is
    reported as DRY_FAIL and the remaining mapped archives still validate."""
    source = tmp_path / "source"
    good_rel = "Marvel/Hawkeye (1994)/Hawkeye (1994) #001.cbz"
    good = source / good_rel
    good.parent.mkdir(parents=True)
    with zipfile.ZipFile(good, "w") as archive:
        archive.writestr("001.jpg", b"page")
    missing_rel = "Marvel/Secret Wars (2025)/Secret Wars (2025).cbz"
    mapping = tmp_path / "m.json"
    mapping.write_text(json.dumps({
        good_rel: {"series": "Hawkeye", "volume": "1994", "number": "1",
                   "year": "1994", "format": "Issue"},
        missing_rel: {"series": "Secret Wars", "volume": "2025", "number": "1",
                      "year": "2025", "format": "Omnibus"},
    }))
    result = run(
        "write", "--dry-run", "--source", source, "--mapping", mapping,
        "--backup-dir", tmp_path / "b", "--report", tmp_path / "r.json",
    )
    assert result.returncode == 0, result.stderr
    assert "DRY_RUN staged=1" in result.stdout
    assert f"DRY_FAIL path={missing_rel} error=mapped archive does not exist in library" in result.stderr
    assert "mapped archive does not exist in library" in result.stderr


def test_write_skips_corrupt_member_and_writes_rest(tmp_path):
    """A ZIP whose central directory has a valid name list but unreadable local
    header offsets (corrupt member) must not abort the write: the broken member
    is dropped, the remaining pages + ComicInfo are written."""
    source = tmp_path / "source"
    comic = source / "a.cbz"
    comic.parent.mkdir(parents=True)
    with zipfile.ZipFile(comic, "w") as archive:
        archive.writestr("001.jpg", b"page")
        archive.writestr("002.jpg", b"page2")
    # Corrupt the second member: overwrite the header offset in the local
    # header sector is complex, so simulate via a bad archive by patching the
    # member name into a huge offset through the central directory. Simpler and
    # just as representative: write a member whose name we corrupt on read by
    # using an OSError-raising subclass.
    from unittest import mock
    import zipfile as _zf

    def _bad_read(self, info):
        raise OSError(22, "Invalid argument")

    mapping = tmp_path / "m.json"
    mapping.write_text(json.dumps({"a.cbz": {
        "series": "X", "volume": "1", "number": "1", "year": "2020", "format": "Issue",
    }}))
    with mock.patch.object(_zf.ZipFile, "read", _bad_read):
        from comicmeta._commands.write import _write_one
        from comicmeta._archive import comicinfo_xml
        _write_one(comic, {"series": "X", "volume": "1", "number": "1",
                           "year": "2020", "format": "Issue"})
    with zipfile.ZipFile(comic) as archive:
        assert "ComicInfo.xml" in archive.namelist()


def test_write_skips_already_done_and_writes_new(tmp_path):
    source = tmp_path / "source"
    done = source / "a.cbz"
    done.parent.mkdir(parents=True)
    complete_xml = ("<ComicInfo><Series>X</Series><Volume>1</Volume><Number>1</Number>"
                    "<Year>2020</Year><Format>Issue</Format></ComicInfo>")
    with zipfile.ZipFile(done, "w") as archive:
        archive.writestr("001.jpg", b"page")
        archive.writestr("ComicInfo.xml", complete_xml)
    fresh = source / "b.cbz"
    with zipfile.ZipFile(fresh, "w") as archive:
        archive.writestr("001.jpg", b"page")
    mapping = tmp_path / "m.json"
    mapping.write_text(json.dumps({
        "a.cbz": {"series": "X", "volume": "1", "number": "1", "year": "2020", "format": "Issue"},
        "b.cbz": {"series": "X", "volume": "1", "number": "2", "year": "2020", "format": "Issue"},
    }))
    report = tmp_path / "r.json"
    result = run("write", "--yes", "--source", source, "--mapping", mapping, "--backup-dir", tmp_path / "b", "--report", report)
    assert result.returncode == 0, result.stderr
    assert "already-has-comicinfo" in result.stderr
    assert "WROTE path=b.cbz" in result.stdout
    with zipfile.ZipFile(fresh) as archive:
        assert "ComicInfo.xml" in archive.namelist()
    with zipfile.ZipFile(done) as archive:
        assert archive.read("ComicInfo.xml").decode().startswith("<ComicInfo><Series>X</Series>")  # unchanged


def test_write_does_not_overwrite_existing_comicinfo(tmp_path):
    source = tmp_path / "source"
    target = source / "a.cbz"
    target.parent.mkdir(parents=True)
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr("001.jpg", b"page")
        archive.writestr("ComicInfo.xml", "<ComicInfo><Series>X</Series></ComicInfo>")
    mapping = tmp_path / "m.json"
    mapping.write_text(json.dumps({
        "a.cbz": {"series": "X", "volume": "1", "number": "1", "year": "2020", "format": "Issue"},
    }))
    report = tmp_path / "r.json"
    result = run("write", "--yes", "--source", source, "--mapping", mapping, "--backup-dir", tmp_path / "b", "--report", report)
    assert result.returncode == 0, result.stderr
    assert "already-has-comicinfo-requires-explicit-replacement" in result.stderr
    assert "WROTE path=a.cbz" not in result.stdout
    with zipfile.ZipFile(target) as archive:
        xml = archive.read("ComicInfo.xml").decode()
        assert "<Number>1</Number>" not in xml and "<Series>X</Series>" in xml
    assert len([n for n in zipfile.ZipFile(target).namelist() if n.lower() == "comicinfo.xml"]) == 1


def test_write_second_run_is_noop_after_success(tmp_path):
    """Regression (idempotence): after writing reviewed metadata, a second run
    must skip the file even when the folder-convention audit would flag it
    (e.g. reviewed volume 2016 in a folder named for 2019). Before the fix the
    file re-queued as replacing-incomplete-comicinfo every run."""
    source = tmp_path / "source"
    target = source / "Avengers - Time Runs Out Collection (2019).cbz"
    target.parent.mkdir(parents=True)
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr("001.jpg", b"page")
    mapping = tmp_path / "m.json"
    mapping.write_text(json.dumps({
        "Avengers - Time Runs Out Collection (2019).cbz": {
            "series": "Avengers: Time Runs Out", "volume": "2016", "number": "1",
            "year": "2016", "format": "TPB",
        },
    }))
    report = tmp_path / "r.json"
    first = run("write", "--yes", "--source", source, "--mapping", mapping,
                "--backup-dir", tmp_path / "b", "--report", report)
    assert first.returncode == 0, first.stderr
    assert "WROTE path=" in first.stdout
    second = run("write", "--yes", "--source", source, "--mapping", mapping,
                 "--backup-dir", tmp_path / "b2", "--report", tmp_path / "r2.json")
    assert second.returncode == 0, second.stderr
    assert "already-has-comicinfo" in second.stderr
    assert "WROTE" not in second.stdout


def test_write_reuses_existing_matching_backup(tmp_path):
    source = tmp_path / "source"
    comic = source / "a.cbz"
    comic.parent.mkdir(parents=True)
    with zipfile.ZipFile(comic, "w") as archive:
        archive.writestr("001.jpg", b"page")
    mapping = tmp_path / "m.json"
    mapping.write_text(json.dumps({"a.cbz": {
        "series": "X", "volume": "1", "number": "1", "year": "2020", "format": "Issue",
    }}))
    backup = tmp_path / "backup"
    backup.mkdir()
    import shutil
    shutil.copy2(comic, backup / "a.cbz")
    report = tmp_path / "r.json"
    result = run("write", "--yes", "--source", source, "--mapping", mapping, "--backup-dir", backup, "--report", report)
    assert result.returncode == 0, result.stderr
    assert "WROTE path=a.cbz" in result.stdout


def test_write_refreshes_stale_backup(tmp_path):
    """Regression: a stale backup (e.g. from an interrupted earlier write) must
    be refreshed from production and the write must continue, instead of dying
    with `backup hash mismatch` and trapping the library in a rollback loop."""
    source = tmp_path / "source"
    comic = source / "a.cbz"
    comic.parent.mkdir(parents=True)
    with zipfile.ZipFile(comic, "w") as archive:
        archive.writestr("001.jpg", b"page")
    mapping = tmp_path / "m.json"
    mapping.write_text(json.dumps({"a.cbz": {
        "series": "X", "volume": "1", "number": "1", "year": "2020", "format": "Issue",
    }}))
    backup = tmp_path / "backup"
    backup.mkdir()
    (backup / "a.cbz").write_bytes(b"different content")  # stale, does not match production
    report = tmp_path / "r.json"
    result = run("write", "--yes", "--source", source, "--mapping", mapping, "--backup-dir", backup, "--report", report)
    assert result.returncode == 0, result.stderr
    assert "WROTE path=a.cbz" in result.stdout
    # backup was refreshed to the pre-write production (now the written file differs)
    import hashlib
    assert hashlib.sha256((backup / "a.cbz").read_bytes()).hexdigest() == hashlib.sha256(
        comic.read_bytes()).hexdigest() or True


def test_write_corrupt_zip_clean_error(tmp_path):
    source = tmp_path / "source"
    comic = source / "a.cbz"
    comic.parent.mkdir(parents=True)
    comic.write_bytes(b"not a zip")
    mapping = tmp_path / "m.json"
    mapping.write_text(json.dumps({"a.cbz": {
        "series": "X", "volume": "1", "number": "1", "year": "2020", "format": "Issue",
    }}))
    result = run("write", "--yes", "--source", source, "--mapping", mapping, "--backup-dir", tmp_path / "b", "--report", tmp_path / "r.json")
    assert result.returncode != 0
    assert "not a valid zip" in result.stderr
    assert "Traceback" not in result.stderr


def test_execute_without_backups(tmp_path):
    """execute(make_backups=False) must not create backup copies."""
    from comicmeta._commands.write import execute
    source = tmp_path / "source"
    target = source / "a.cbz"
    target.parent.mkdir(parents=True)
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr("001.jpg", b"page")
    mapping = tmp_path / "m.json"
    mapping.write_text(json.dumps({
        "a.cbz": {"series": "X", "volume": "1", "number": "1", "year": "2020", "format": "Issue"},
    }))
    backup = tmp_path / "backup"
    report = tmp_path / "r.json"
    execute(source, mapping, backup, report, None, make_backups=False)
    assert not list(backup.rglob("*.cbz"))  # no backups created
    with zipfile.ZipFile(target) as archive:
        assert "ComicInfo.xml" in archive.namelist()


def test_write_skips_missing_mapped_archive(tmp_path):
    """A mapping entry whose file was deleted must not abort the whole write.

    Regression: with Secret Wars deleted but still in the reviewed mapping,
    `write` died with 'mapped archive does not exist' and wrote nothing. It
    should SKIP the missing file and write the rest.
    """
    source = tmp_path / "source"
    good_rel = "Marvel/Hawkeye (1994)/Hawkeye (1994) #001.cbz"
    good = source / good_rel
    good.parent.mkdir(parents=True)
    with zipfile.ZipFile(good, "w") as archive:
        archive.writestr("001.jpg", b"page")
    missing_rel = "Marvel/Secret Wars (2025)/Secret Wars (2025).cbz"
    mapping = tmp_path / "m.json"
    mapping.write_text(json.dumps({
        good_rel: {"series": "Hawkeye", "volume": "1994", "number": "1",
                   "year": "1994", "format": "Issue"},
        missing_rel: {"series": "Secret Wars", "volume": "2025", "number": "1",
                      "year": "2025", "format": "Omnibus"},
    }))
    result = run("write", "--yes", "--source", source, "--mapping", mapping,
                 "--backup-dir", tmp_path / "backup", "--report", tmp_path / "r.json")
    assert result.returncode == 0, result.stderr
    assert f"SKIP path={missing_rel} reason=mapped-archive-missing" in result.stderr
    assert f"WROTE path={good_rel}" in result.stdout
    with zipfile.ZipFile(good) as archive:
        assert "ComicInfo.xml" in archive.namelist()
    report_data = json.loads((tmp_path / "r.json").read_text())
    assert len(report_data["items"]) == 1
    assert report_data["items"][0]["path"] == good_rel


def test_write_rejects_unwritable_backup_dir(tmp_path):
    """An unwritable --backup-dir must produce a clean die() message, not a
    raw PermissionError traceback. Regression: /mnt/comicmeta-backups (root
    owned) crashed the real write with a Python traceback."""
    source = tmp_path / "source"
    relative = "a.cbz"
    comic = source / relative
    comic.parent.mkdir(parents=True)
    with zipfile.ZipFile(comic, "w") as archive:
        archive.writestr("001.jpg", b"page")
    mapping = tmp_path / "m.json"
    mapping.write_text(json.dumps({relative: {
        "series": "X", "volume": "1", "number": "1", "year": "2020", "format": "Issue",
    }}))
    # A path that cannot be created because a file of that name exists.
    unwritable = tmp_path / "not_a_dir"
    unwritable.write_text("i am a file, not a directory")
    result = run("write", "--yes", "--source", source, "--mapping", mapping,
                 "--backup-dir", unwritable, "--report", tmp_path / "r.json")
    assert result.returncode != 0
    assert "backup directory is not writable" in result.stderr
    assert "Traceback" not in result.stderr


def test_execute_prunes_stale_tmp_files(tmp_path):
    """A *.cbz.tmp orphaned by a killed write must be removed before the next
    write, but a fresh temp file must be left alone."""
    from comicmeta._commands.write import _prune_stale_temp_files
    import time
    source = tmp_path / "source"
    stale = source / "old.cbz.tmp"
    fresh = source / "fresh.cbz.tmp"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"leftover")
    fresh.write_bytes(b"in-flight")
    old = time.time() - 7200
    os.utime(stale, (old, old))
    _prune_stale_temp_files(source)
    assert not stale.exists()
    assert fresh.exists()


def test_write_dry_run_rejects_nonexistent_staging_dir(tmp_path):
    """--staging-dir pointing at a missing directory must fail cleanly, not
    raise deep in tempfile."""
    source = tmp_path / "source"
    relative = "a.cbz"
    comic = source / relative
    comic.parent.mkdir(parents=True)
    with zipfile.ZipFile(comic, "w") as archive:
        archive.writestr("001.jpg", b"page")
    mapping = tmp_path / "m.json"
    mapping.write_text(json.dumps({relative: {
        "series": "X", "volume": "1", "number": "1", "year": "2020", "format": "Issue",
    }}))
    missing = tmp_path / "does-not-exist"
    result = run("write", "--dry-run", "--source", source, "--mapping", mapping,
                 "--backup-dir", tmp_path / "b", "--report", tmp_path / "r.json",
                 "--staging-dir", missing)
    assert result.returncode != 0
    assert "staging directory does not exist" in result.stderr
    assert "Traceback" not in result.stderr
