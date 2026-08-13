import io

from comicmeta._spinner import Checklist


def test_checklist_non_tty_prints_checkmarks():
    stream = io.StringIO()
    cl = Checklist(stream=stream)
    cl.start("Scan")
    cl.succeed("Scan", "2 files")
    cl.start("Map")
    cl.succeed("Map", "complete")
    out = stream.getvalue()
    assert "✓ Scan — 2 files" in out
    assert "✓ Map — complete" in out
    assert len(cl._completed) == 2


def test_checklist_phases_completed():
    stream = io.StringIO()
    cl = Checklist(stream=stream)
    for name in ("Scan", "Volumes", "Issues", "Map"):
        cl.start(name)
        cl.succeed(name)
    assert [c[0] for c in cl._completed] == ["Scan", "Volumes", "Issues", "Map"]
