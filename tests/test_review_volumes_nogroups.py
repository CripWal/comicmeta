"""Feedback loop for the review-volumes empty-groups crash (diagnosing-bugs)."""
import io
import json
import contextlib
from pathlib import Path
from unittest import mock

from comicmeta._commands.review_volumes import Palette, interactive


def test_interactive_no_groups_returns_cleanly(tmp_path):
    """Empty review report must return, not die with exit 1.

    This is the exact symptom reported by the user: `comicmeta -c nas review`
    on a library where every archive either has complete ComicInfo or nothing
    is tagged for replacement → review-volumes died with
    "no review-required groups found" → exit 1 → SSH session closed.
    """
    report = tmp_path / "c.json"
    report.write_text(json.dumps({"source": str(tmp_path), "items": []}))
    state = tmp_path / "s.json"
    summary = tmp_path / "sm.md"
    out = io.StringIO()
    with mock.patch("comicmeta._tui.read_key"):
        with contextlib.redirect_stdout(out):
            # interactive() must not raise SystemExit; that would kill the
            # dashboard's subcommand and close the NAS SSH session.
            interactive(report, state, summary, {}, Palette(False))
    assert "Nothing to review" in out.getvalue()
