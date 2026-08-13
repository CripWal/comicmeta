import pytest
from pathlib import Path

from comicmeta._commands.stage import prepare


def test_prepare(tmp_path):
    source = tmp_path / "source"
    relative = Path("Marvel/Hawkeye (1994)/Hawkeye (1994) #001.cbz")
    original = source / relative
    original.parent.mkdir(parents=True)
    original.write_bytes(b"fixture")
    punctuation_relative = Path("Marvel/O'Brien [Edition] (2025)/O'Brien #001.cbz")
    punctuation_original = source / punctuation_relative
    punctuation_original.parent.mkdir(parents=True)
    punctuation_original.write_bytes(b"punctuation fixture")
    destination = tmp_path / "staging"
    mapping = {relative.as_posix(): {}, punctuation_relative.as_posix(): {}}
    report = prepare(source, destination, mapping)
    assert len(report) == 2
    assert (destination / relative).read_bytes() == b"fixture"
    assert (destination / punctuation_relative).read_bytes() == b"punctuation fixture"
    assert original.read_bytes() == b"fixture"
    assert punctuation_original.read_bytes() == b"punctuation fixture"
    with pytest.raises(ValueError, match="destination is not empty"):
        prepare(source, destination, mapping)


def test_prepare_rejects_file_destination(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.cbz").write_bytes(b"x")
    dest = tmp_path / "dest"
    dest.touch()
    with pytest.raises(ValueError, match="not a directory"):
        prepare(source, dest, {"a.cbz": {}})


def test_stage_copy2_lenient_on_chflags_error(tmp_path, monkeypatch):
    """copy2 must not fail when the volume rejects file-flag copies (macOS chflags)."""
    import shutil
    from comicmeta._commands.stage import prepare
    src = tmp_path / "source"
    cbz = src / "X (2020)/X (2020) #001.cbz"
    cbz.parent.mkdir(parents=True)
    cbz.write_bytes(b"archive-bytes")
    mapping = {"X (2020)/X (2020) #001.cbz": {"series": "X"}}
    dest = tmp_path / "staging"

    real_copystat = shutil.copystat
    def failing_copystat(*args, **kwargs):
        raise PermissionError("Operation not permitted")
    monkeypatch.setattr("comicmeta._commands.stage.shutil.copystat", failing_copystat)
    report = prepare(src, dest, mapping)
    assert len(report) == 1
    # content copied despite metadata failure
    assert (dest / "X (2020)/X (2020) #001.cbz").read_bytes() == b"archive-bytes"
