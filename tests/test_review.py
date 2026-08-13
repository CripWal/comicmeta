import json

import pytest


def test_review_parser_defers_api_key_env_to_config():
    from comicmeta.cli import build_parser

    assert build_parser().parse_args(["review"]).api_key_env is None


def test_review_uses_configured_api_key_env(monkeypatch):
    from argparse import Namespace
    from comicmeta._commands.review import _try_api_key

    monkeypatch.setenv("CUSTOM_COMICVINE_KEY", "secret")
    args = Namespace(api_key_env=None, api_key_file=None)

    assert _try_api_key(args, {
        "api.key_env": "CUSTOM_COMICVINE_KEY",
        "api.key_file": "",
        "api.keychain": False,
    }) == "secret"


def test_review_uses_configured_keychain():
    from argparse import Namespace
    from unittest import mock
    from comicmeta._commands.review import _try_api_key

    with mock.patch("comicmeta._comicvine._keychain_read", return_value="secret"):
        assert _try_api_key(Namespace(api_key_env=None, api_key_file=None), {
            "api.key_env": "CUSTOM_COMICVINE_KEY",
            "api.key_file": "",
            "api.keychain": True,
        }) == "secret"



def test_issue_review_complete_requires_all_candidate_paths(tmp_path):
    from comicmeta._commands.review import _issue_review_complete
    state = tmp_path / "state.json"
    candidates = {"series": [
        {"matches": [
            {"path": "Aquaman (1994) #000.cbz", "archive_format": "cbz"},
            {"path": "Aquaman (1994) #001.cbz", "archive_format": "cbz"},
        ]},
    ]}
    # only one of two candidate paths reviewed
    state.write_text(json.dumps({"reviews": {
        "Aquaman (1994) #000.cbz": {"status": "auto-accepted"},
    }}))
    assert _issue_review_complete(state, candidates) is False
    # both candidate paths reviewed -> complete even with extra stale reviews
    state.write_text(json.dumps({"reviews": {
        "Aquaman (1994) #000.cbz": {"status": "auto-accepted"},
        "Aquaman (1994) #001.cbz": {"status": "auto-accepted"},
        "Hawkeye (1983) #001.cbz": {"status": "auto-accepted"},  # stale, no longer a candidate
    }}))
    assert _issue_review_complete(state, candidates) is True


def test_issue_candidates_stale_when_empty(tmp_path):
    from comicmeta._commands.review import _issue_candidates_stale
    state = tmp_path / "vol-state.json"
    state.write_text(json.dumps({"selections": {
        "X (2020)": {"status": "selected", "candidate_id": 1},
    }}))
    candidates = tmp_path / "issues.json"
    candidates.write_text(json.dumps({"series": []}))  # stale empty
    assert _issue_candidates_stale(state, candidates) is True


def test_issue_candidates_stale_when_missing(tmp_path):
    from comicmeta._commands.review import _issue_candidates_stale
    state = tmp_path / "vol-state.json"
    state.write_text(json.dumps({"selections": {}}))
    assert _issue_candidates_stale(state, tmp_path / "nope.json") is True


def test_issue_candidates_fresh_when_matches(tmp_path):
    from comicmeta._commands.review import _issue_candidates_stale
    state = tmp_path / "vol-state.json"
    state.write_text(json.dumps({"selections": {
        "X (2020)": {"status": "selected", "candidate_id": 1},
        "Y (2021)": {"status": "flagged"},
    }}))
    candidates = tmp_path / "issues.json"
    candidates.write_text(json.dumps({"series": [{"query": "X (2020)"}]}))
    assert _issue_candidates_stale(state, candidates) is False


def test_run_completes_with_no_cbrs_and_no_issue_candidates(tmp_path, monkeypatch):
    """Regression: continue-to-write confirm must not raise UnboundLocalError
    when there are no CBR files (the local `from comicmeta._tui import confirm`
    shadowed the module import, leaving `confirm` unbound on that path)."""
    import io, contextlib, argparse
    from pathlib import Path
    from unittest import mock
    from comicmeta._commands import review as R
    from comicmeta import _config as config_mod

    # empty tmp_path means find_cbrs() -> [] naturally; no convert mock needed
    (tmp_path / "candidates.json").write_text('{"items": []}')
    (tmp_path / "issues.json").write_text('{"series": []}')
    args = argparse.Namespace(source=tmp_path, api_key_file=None, api_key_env=None, list=False, no_color=True)
    mocks = [
        mock.patch.object(R.discover, "rescan", return_value={
            "needs_api_key": False, "reused": 0, "queried": 0, "removed": [], "added": [], "items": []}),
        mock.patch.object(R, "_volume_review_complete", return_value=True),
        mock.patch.object(R, "_issue_candidates_stale", return_value=False),
        mock.patch.object(R.review_issues, "review_items", return_value=[]),
        mock.patch.object(R.mapping, "run", lambda a: None),
        mock.patch.object(config_mod, "get", lambda flat, key: {
            "api.candidate_limit": "10",
            "api.key_env": "COMICVINE_API_KEY",
            "api.request_delay": "0.25",
            "api.concurrency": "2",
            "review.high_confidence_score": "90",
            "review.high_confidence_margin": "15",
            "review.continue_to_write": "1",
            "paths.backup_dir": str(tmp_path / "backups"),
            "paths.candidates": str(tmp_path / "candidates.json"),
            "paths.volume_state": str(tmp_path / "vol.json"),
            "paths.volume_summary": str(tmp_path / "vol.md"),
            "paths.policy": str(tmp_path / "policy.json"),
            "paths.issue_candidates": str(tmp_path / "issues.json"),
            "paths.issue_state": str(tmp_path / "iss.json"),
            "paths.issue_summary": str(tmp_path / "iss.md"),
            "paths.mapping": str(tmp_path / "mapping.json"),
            "write.auto_confirm": "0",
        }.get(key, "")),
        mock.patch.object(R, "is_interactive", return_value=True),
        mock.patch.object(R, "confirm", return_value=False),
    ]
    for m in mocks:
        m.start()
    try:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            R.run(args)
    finally:
        for m in reversed(mocks):
            m.stop()
    assert "Review complete" in buf.getvalue()


def _run_mocks(tmp_path, **overrides):
    import argparse
    from unittest import mock
    from comicmeta._commands import review as R
    from comicmeta import _config as config_mod

    args = argparse.Namespace(source=tmp_path, api_key_file=None, api_key_env=None, list=False, no_color=True, fresh=False, reopen=False)
    for key, value in overrides.items():
        setattr(args, key, value)
    config_get = {
        "api.candidate_limit": "10",
        "api.key_env": "COMICVINE_API_KEY",
        "api.request_delay": "0.25",
        "api.concurrency": "2",
        "review.high_confidence_score": "90",
        "review.high_confidence_margin": "15",
        "review.continue_to_write": "0",
        "paths.backup_dir": str(tmp_path / "backups"),
        "paths.candidates": str(tmp_path / "candidates.json"),
        "paths.volume_state": str(tmp_path / "vol.json"),
        "paths.volume_summary": str(tmp_path / "vol.md"),
        "paths.policy": str(tmp_path / "policy.json"),
        "paths.issue_candidates": str(tmp_path / "issues.json"),
        "paths.issue_state": str(tmp_path / "iss.json"),
        "paths.issue_summary": str(tmp_path / "iss.md"),
        "paths.mapping": str(tmp_path / "mapping.json"),
        "write.auto_confirm": "0",
    }
    return R, args, config_get, config_mod


def test_run_reopen_enters_interactive_even_when_complete(tmp_path):
    """--reopen must re-enter the volume review even when the review is complete,
    so skipped mis-selected volumes can be fixed without a destructive --fresh."""
    import io, contextlib
    from unittest import mock
    from pathlib import Path
    from comicmeta._common import die

    (tmp_path / "candidates.json").write_text('{"items": []}')
    (tmp_path / "issues.json").write_text('{"series": []}')
    R, args, config, config_mod = _run_mocks(tmp_path, reopen=True)
    calls = {"interactive": 0}
    def fake_interactive(*a, **kw):
        calls["interactive"] += 1
    mocks = [
        mock.patch.object(R.discover, "rescan", return_value={
            "needs_api_key": False, "reused": 0, "queried": 0, "removed": [], "added": [], "items": []}),
        mock.patch.object(R, "_volume_review_complete", return_value=True),  # would skip normally
        mock.patch.object(R, "require_tty", lambda cmd, alt: None),
        mock.patch.object(R.review_volumes, "interactive", fake_interactive),
        mock.patch.object(R, "_issue_candidates_stale", return_value=False),
        mock.patch.object(R.review_issues, "review_items", return_value=[]),
        mock.patch.object(R.mapping, "run", lambda a: None),
        mock.patch.object(config_mod, "get", lambda flat, key: config.get(key, "")),
        mock.patch.object(R, "is_interactive", return_value=False),
    ]
    for m in mocks:
        m.start()
    try:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            R.run(args)
    finally:
        for m in reversed(mocks):
            m.stop()
    assert calls["interactive"] == 1
    assert "(re-opened)" in buf.getvalue()


def test_volume_review_complete_uses_queries_not_items(tmp_path):
    """One selection per query group must count as complete even when the
    query covers many files (e.g. a 76-issue run)."""
    from comicmeta._commands.review import _volume_review_complete
    candidates = {"items": [
        {"status": "review-required", "query": "Aquaman Vol. 5 (1994)"},
        {"status": "review-required", "query": "Aquaman Vol. 5 (1994)"},
        {"status": "review-required", "query": "Aquaman Vol. 5 (1994)"},
        {"status": "review-required", "query": "Hawkeye (2017)"},
        {"status": "skipped-existing-comicinfo", "query": "Hawkeye (1994)"},
    ]}
    state = tmp_path / "vol.json"
    state.write_text(json.dumps({"selections": {
        "Aquaman Vol. 5 (1994)": {"status": "selected", "candidate_id": 5230},
        "Hawkeye (2017)": {"status": "selected", "candidate_id": 96661},
    }}))
    assert _volume_review_complete(state, candidates) is True
    # missing a required query -> not complete
    state.write_text(json.dumps({"selections": {
        "Aquaman Vol. 5 (1994)": {"status": "selected"},
    }}))
    assert _volume_review_complete(state, candidates) is False
    # a skipped volume stays held (re-openable) even though every query has an answer
    state.write_text(json.dumps({"selections": {
        "Aquaman Vol. 5 (1994)": {"status": "selected", "candidate_id": 5230},
        "Hawkeye (2017)": {"status": "skipped"},
    }}))
    assert _volume_review_complete(state, candidates) is False


def test_fresh_flag_clears_state(tmp_path, monkeypatch):
    """review --fresh must delete prior state files after confirmation."""
    import io, contextlib, argparse
    from pathlib import Path
    from unittest import mock
    from comicmeta._commands import review as R
    from comicmeta import _config as config_mod

    for name in ("comicvine-candidates.json", "comicvine-review-state.json",
                 "comicvine-issue-candidates.json", "comicvine-issue-review-state.json",
                 "comic-metadata-reviewed-mapping.json"):
        (tmp_path / name).write_text("{}")

    def fake_get(flat, key):
        names = {
            "paths.candidates": "comicvine-candidates.json",
            "paths.volume_state": "comicvine-review-state.json",
            "paths.volume_summary": "comicvine-review.md",
            "paths.policy": "comic-metadata-review-policy.json",
            "paths.issue_candidates": "comicvine-issue-candidates.json",
            "paths.issue_state": "comicvine-issue-review-state.json",
                "paths.issue_summary": "comicvine-issue-review.md",
                "paths.mapping": "comic-metadata-reviewed-mapping.json",
                "paths.kavita_export": "comicmeta-kavita-export.json",
        }
        if key in names:
            return str(tmp_path / names[key])
        return {"api.candidate_limit": "10", "api.key_env": "K",
                "api.request_delay": "0.25", "api.concurrency": "2"}.get(key, "")

    def fake_rescan(source, report, *a, **k):
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text('{"items": []}')
        return {"needs_api_key": False, "reused": 0, "queried": 0, "removed": [], "added": [], "items": []}

    args = argparse.Namespace(source=tmp_path, api_key_file=None, api_key_env=None,
                              list=False, fresh=True, no_color=True)
    mocks = [
        mock.patch.object(R.discover, "rescan", fake_rescan),
        mock.patch.object(R, "confirm", return_value=True),
        mock.patch.object(R, "die", side_effect=SystemExit),
        mock.patch.object(config_mod, "get", fake_get),
    ]
    for m in mocks:
        m.start()
    try:
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                R.run(args)
        except SystemExit:
            pass  # fresh review continues into interactive volume review; that's fine
    finally:
        for m in reversed(mocks):
            m.stop()
    remaining = [n for n in ("comicvine-candidates.json", "comicvine-review-state.json",
                             "comicvine-issue-candidates.json", "comicvine-issue-review-state.json",
                             "comic-metadata-reviewed-mapping.json") if (tmp_path / n).exists()]
    # candidates is regenerated by the fresh rescan; the rest must stay cleared
    assert remaining == ["comicvine-candidates.json"]


def test_fresh_flag_cancel_keeps_state(tmp_path, monkeypatch):
    import io, contextlib, argparse
    from pathlib import Path
    from unittest import mock
    from comicmeta._commands import review as R
    from comicmeta import _config as config_mod

    (tmp_path / "comicvine-candidates.json").write_text("{}")

    def fake_get(flat, key):
        if key.startswith("paths."):
            return str(tmp_path / key.split(".")[-1])
        return {"api.candidate_limit": "10", "api.key_env": "K",
                "api.request_delay": "0.25", "api.concurrency": "2"}.get(key, "")

    args = argparse.Namespace(source=tmp_path, api_key_file=None, api_key_env=None,
                              list=False, fresh=True, no_color=True)
    mocks = [
        mock.patch.object(R, "confirm", return_value=False),
        mock.patch.object(R, "die", side_effect=SystemExit),
        mock.patch.object(config_mod, "get", fake_get),
    ]
    for m in mocks:
        m.start()
    try:
        with pytest.raises(SystemExit):
            with contextlib.redirect_stdout(io.StringIO()):
                R.run(args)
    finally:
        for m in reversed(mocks):
            m.stop()
    assert (tmp_path / "comicvine-candidates.json").exists()  # kept
