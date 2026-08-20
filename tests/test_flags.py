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


def test_collect_includes_replacement_requests(tmp_path, monkeypatch):
    from comicmeta import _config
    directory, vol, iss = _state()
    repl = directory / "repl.json"
    repl.write_text(json.dumps({"requests": {
        "Marvel/Y (2020)/Y (2020) #001.cbz": {"note": "tagged in browse"},
    }}))
    monkeypatch.setattr(_config, "get", lambda flat, key: {
        "paths.volume_state": str(vol),
        "paths.issue_state": str(iss),
        "paths.replacement_state": str(repl),
    }.get(key))
    series, issues = collect({})
    assert len(issues) == 1 and issues[0]["replacement"] is True
    assert issues[0]["path"] == "Marvel/Y (2020)/Y (2020) #001.cbz"


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


def test_clear_all_removes_everything(tmp_path, monkeypatch):
    import json as _json
    from comicmeta import _config
    directory, vol, iss = _state(
        volume={"Aquaman Vol. 5 (1994)": {"status": "flagged", "note": "wrong volume"}},
        issues={"Marvel/X (2020)/X (2020) #001.cbz": {"status": "flagged", "note": "check date"}},
    )
    repl = directory / "repl.json"
    repl.write_text(_json.dumps({"requests": {
        "Marvel/Y (2020)/Y (2020) #001.cbz": {"note": "tagged in browse"},
    }}))
    monkeypatch.setattr(_config, "get", lambda flat, key: {
        "paths.volume_state": str(vol),
        "paths.issue_state": str(iss),
        "paths.replacement_state": str(repl),
    }.get(key))

    out = io.StringIO()
    args = Namespace(source=tmp_path, no_color=True, clear_all=True, clear=False, yes=True)
    with contextlib.redirect_stdout(out):
        run(args)

    assert "Cleared 3 flag(s)" in out.getvalue()
    assert _json.loads(vol.read_text())["selections"] == {}
    assert _json.loads(iss.read_text())["reviews"] == {}
    assert _json.loads(repl.read_text())["requests"] == {}
    # collect now reports nothing
    series, issues = collect({})
    assert series == [] and issues == []


def test_clear_all_nothing_flagged(tmp_path, monkeypatch):
    from comicmeta import _config
    directory, vol, iss = _state(volume={}, issues={})
    monkeypatch.setattr(_config, "get", lambda flat, key: {
        "paths.volume_state": str(vol),
        "paths.issue_state": str(iss),
    }.get(key))
    out = io.StringIO()
    args = Namespace(source=tmp_path, no_color=True, clear_all=True, clear=False, yes=True)
    with contextlib.redirect_stdout(out):
        run(args)
    assert "Nothing flagged" in out.getvalue()

