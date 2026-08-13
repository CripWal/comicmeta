import json
from argparse import Namespace
import io, contextlib

from comicmeta._commands.flags import collect, run


def _state(volume: dict | None = None, issues: dict | None = None) -> tuple:
    import tempfile
    from pathlib import Path
    directory = Path(tempfile.mkdtemp())
    if volume is not None:
        (directory / "vol.json").write_text(json.dumps({"selections": volume}))
    if issues is not None:
        (directory / "iss.json").write_text(json.dumps({"reviews": issues}))
    return directory, directory / "vol.json", directory / "iss.json"


def test_collect_flagged(tmp_path, monkeypatch):
    from comicmeta import _config
    directory, vol, iss = _state(
        volume={"Aquaman Vol. 5 (1994)": {"status": "flagged", "note": "wrong volume pinned"}},
        issues={"Marvel/X (2020)/X (2020) #001.cbz": {"status": "flagged", "note": "check date"}},
    )
    monkeypatch.setattr(_config, "get", lambda flat, key: {
        "paths.volume_state": str(vol),
        "paths.issue_state": str(iss),
    }.get(key))
    series, issues = collect({})
    assert len(series) == 1 and series[0]["query"] == "Aquaman Vol. 5 (1994)"
    assert series[0]["note"] == "wrong volume pinned"
    assert len(issues) == 1 and issues[0]["note"] == "check date"


def test_run_lists_flags(tmp_path, monkeypatch):
    from comicmeta import _config
    directory, vol, iss = _state(volume={"X (2020)": {"status": "flagged", "note": "n"}})
    monkeypatch.setattr(_config, "get", lambda flat, key: {
        "paths.volume_state": str(vol),
        "paths.issue_state": str(iss),
    }.get(key))
    out = io.StringIO()
    args = Namespace(source=tmp_path, no_color=True)
    with contextlib.redirect_stdout(out):
        run(args)
    assert "X (2020)" in out.getvalue()
    assert "SERIES (1)" in out.getvalue()


def test_run_no_flags(tmp_path, monkeypatch):
    from comicmeta import _config
    directory, vol, iss = _state(volume={}, issues={})
    monkeypatch.setattr(_config, "get", lambda flat, key: {
        "paths.volume_state": str(vol),
        "paths.issue_state": str(iss),
    }.get(key))
    out = io.StringIO()
    args = Namespace(source=tmp_path, no_color=True)
    with contextlib.redirect_stdout(out):
        run(args)
    assert "none" in out.getvalue()
