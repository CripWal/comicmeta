import subprocess
import sys

from comicmeta.cli import build_parser


def test_parser_has_new_commands():
    parser = build_parser()
    choices = parser._subparsers._group_actions[0].choices
    for name in ("covers", "self-test", "update-check"):
        assert name in choices


def test_self_test_runs():
    import os
    env = {**os.environ, "PYTHONPATH": str(__import__("pathlib").Path(__file__).resolve().parents[1] / "src")}
    result = subprocess.run(
        [sys.executable, "-m", "comicmeta", "self-test"],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 0
    assert "RESULT PASS" in result.stdout
