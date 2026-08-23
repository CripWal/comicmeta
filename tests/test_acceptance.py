import base64
import os
import subprocess
import sys
import zipfile


_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "YAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)


def _cbz(path, comicinfo=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("0001.png", _PNG)
        if comicinfo is not None:
            archive.writestr("ComicInfo.xml", comicinfo)


def _run(root, command):
    env = os.environ.copy()
    env["NO_COLOR"] = "1"
    return subprocess.run(
        [sys.executable, "-m", "comicmeta", "--context", "local", *command, "--source", str(root)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_real_user_flow_health_preview_apply(tmp_path):
    _cbz(
        tmp_path / "DC/Aquaman (1994)/Aquaman (1998-11) 1000000 (digital).cbz",
        "<ComicInfo><Series>Aquaman</Series><Volume>1994</Volume>"
        "<Number>1000000</Number><Year>1994</Year></ComicInfo>",
    )
    _cbz(tmp_path / "Marvel/Daredevil - Omnibus/Daredevil Omnibus v01 (2017).cbz")
    _cbz(
        tmp_path / "Marvel/Daredevil - The Man Without Fear 01-05 (1993-1994) "
        "GetComics.INFO/Daredevil- The Man Without Fear 01 (of 5) (1993).cbz"
    )

    health = _run(tmp_path, ["health", "--no-color"])
    assert health.returncode == 0
    assert "issues found" in health.stdout
    assert "incomplete=1" in health.stdout

    preview = _run(tmp_path, ["organize", "--dry-run", "--no-color"])
    assert preview.returncode == 0
    assert "PLAN folders=2 files=3 moves=0 manual=0" in preview.stdout

    applied = _run(tmp_path, ["organize", "--execute", "--no-color"])
    assert applied.returncode == 0
    assert (tmp_path / "Marvel/Daredevil Omnibus (2017)/Daredevil Omnibus (2017) Vol. 01.cbz").is_file()
    assert (tmp_path / "DC/Aquaman (1994)/Aquaman (1994) #1000000.cbz").is_file()
    assert (
        tmp_path / "Marvel/Daredevil - The Man Without Fear (1993)/"
        "Daredevil - The Man Without Fear (1993) #001.cbz"
    ).is_file()
