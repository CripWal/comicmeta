from unittest import mock

from comicmeta import _comicvine


def test_verify_api_key_ok():
    payload = b'{"error": "OK", "results": []}'
    with mock.patch("urllib.request.urlopen", return_value=mock.Mock(**{
        "__enter__": mock.Mock(return_value=mock.Mock(read=lambda: payload)),
        "__exit__": mock.Mock(return_value=False),
    })):
        ok, message = _comicvine.verify_api_key("valid_key")
    assert ok is True
    assert "accepted" in message


def test_verify_api_key_invalid():
    payload = b'{"error": "Invalid API Key", "results": []}'
    with mock.patch("urllib.request.urlopen", return_value=mock.Mock(**{
        "__enter__": mock.Mock(return_value=mock.Mock(read=lambda: payload)),
        "__exit__": mock.Mock(return_value=False),
    })):
        ok, message = _comicvine.verify_api_key("bad_key")
    assert ok is False
    assert "rejected" in message


def test_verify_api_key_network_error():
    import urllib.error
    error = urllib.error.URLError("connection refused")
    with mock.patch("urllib.request.urlopen", side_effect=error):
        ok, message = _comicvine.verify_api_key("key")
    assert ok is False
    assert "network error" in message


# ─── Keychain tests ───


def test_keychain_read_on_mac():
    from unittest import mock
    with mock.patch("sys.platform", "darwin"):
        with mock.patch("subprocess.run", return_value=mock.Mock(returncode=0, stdout="secret_key\n")) as run:
            result = _comicvine._keychain_read()
    assert result == "secret_key"
    cmd = run.call_args[0][0]
    assert cmd[0] == "security"
    assert "comicmeta" in cmd


def test_keychain_read_not_mac():
    from unittest import mock
    with mock.patch("sys.platform", "linux"):
        result = _comicvine._keychain_read()
    assert result is None


def test_keychain_read_command_fails():
    from unittest import mock
    with mock.patch("sys.platform", "darwin"):
        with mock.patch("subprocess.run", return_value=mock.Mock(returncode=1, stdout="", stderr="not found")):
            result = _comicvine._keychain_read()
    assert result is None


def test_keychain_read_timeout():
    import subprocess
    from unittest import mock
    with mock.patch("sys.platform", "darwin"):
        with mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 5)):
            result = _comicvine._keychain_read()
    assert result is None


def test_api_key_from_prefers_env_over_keychain():
    from unittest import mock
    import os
    with mock.patch.dict(os.environ, {"COMICVINE_API_KEY": "from_env"}):
        with mock.patch("comicmeta._comicvine._keychain_read", return_value="from_keychain"):
            key = _comicvine.api_key_from(mock.Mock(api_key_env=None, api_key_file=None), {"api.keychain": True})
    assert key == "from_env"


def test_api_key_from_uses_keychain_when_env_missing():
    from unittest import mock
    import os
    env = os.environ.copy()
    env.pop("COMICVINE_API_KEY", None)
    with mock.patch.dict(os.environ, env, clear=True):
        with mock.patch("comicmeta._comicvine._keychain_read", return_value="from_keychain"):
            key = _comicvine.api_key_from(mock.Mock(api_key_env=None, api_key_file=None), {"api.keychain": True})
    assert key == "from_keychain"


def test_api_key_from_falls_through_keychain_to_key_file():
    from unittest import mock
    import tempfile
    import os
    env = os.environ.copy()
    env.pop("COMICVINE_API_KEY", None)
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".key") as f:
        f.write("from_file\n")
        path = f.name
    try:
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch("comicmeta._comicvine._keychain_read", return_value=None):
                key = _comicvine.api_key_from(
                    mock.Mock(api_key_env=None, api_key_file=None),
                    {"api.keychain": True, "api.key_file": path}
                )
        assert key == "from_file"
    finally:
        os.unlink(path)


def test_api_key_from_keychain_disabled():
    from unittest import mock
    import os
    import pytest
    import io
    import sys
    import contextlib
    env = os.environ.copy()
    env.pop("COMICVINE_API_KEY", None)
    stderr_buf = io.StringIO()
    with mock.patch.dict(os.environ, env, clear=True):
        with mock.patch("comicmeta._comicvine._keychain_read", return_value="from_keychain"):
            with contextlib.redirect_stderr(stderr_buf):
                with pytest.raises(SystemExit) as exc:
                    _comicvine.api_key_from(mock.Mock(api_key_env=None, api_key_file=None), {"api.keychain": False})
    assert exc.value.code == 1
    assert "keychain" in stderr_buf.getvalue().lower()


def test_match_files_volume_tag_to_collection_issue():
    """`Title v01 (Year)` matches a ComicVine issue named 'Volume 1'."""
    items = [
        {"path": "Daredevil - Omnibus/Daredevil Omnibus v01 (2017) (Digital-Empire).cbz",
         "format": "cbz", "issue_number_from_filename": None, "status": "review-required", "existing_issues": None},
        {"path": "Daredevil - Omnibus/Daredevil Omnibus v02 (2023) (Digital-Empire).cbz",
         "format": "cbz", "issue_number_from_filename": None, "status": "review-required", "existing_issues": None},
    ]
    issues = [
        {"id": 1, "name": "Volume 1", "issue_number": "1", "cover_date": "2017-05-10"},
        {"id": 2, "name": "Volume 2", "issue_number": "2", "cover_date": "2023-08-20"},
    ]
    selection = {"candidate_id": 98730, "name": "Daredevil Omnibus", "start_year": "2017", "publisher": "Marvel"}
    matches = _comicvine.match_files("Daredevil - Omnibus", items, issues, selection)
    assert [m["status"] for m in matches] == ["exact-volume", "exact-volume"]
    assert [m["candidate_issue_ids"] for m in matches] == [[1], [2]]
    assert matches[0]["metadata_candidate"]["number"] == "1"
    assert matches[0]["metadata_candidate"]["series"] == "Daredevil Omnibus"
    assert matches[1]["metadata_candidate"]["number"] == "2"


def test_match_files_volume_tag_does_not_false_positive():
    """A vNN tag without a matching 'Volume N' issue stays unmatched."""
    items = [
        {"path": "Series/X v01 (2020).cbz", "format": "cbz",
         "issue_number_from_filename": None, "status": "review-required", "existing_issues": None},
        {"path": "Series/X v03 (2021).cbz", "format": "cbz",
         "issue_number_from_filename": None, "status": "review-required", "existing_issues": None},
    ]
    issues = [{"id": 1, "name": "Volume 1", "issue_number": "1", "cover_date": "2020-01-01"}]
    selection = {"candidate_id": 1, "name": "X", "start_year": "2020", "publisher": "Y"}
    matches = _comicvine.match_files("Series", items, issues, selection)
    # v01 matches "Volume 1"; v03 has no "Volume 3" so it stays unmatched.
    assert matches[0]["status"] == "exact-volume"
    assert matches[1]["status"] == "unmatched"
    assert "metadata_candidate" not in matches[1]


def test_metadata_candidate_maps_credits_lists_and_provenance():
    issue = {
        "id": 42,
        "name": "The Beginning & Beyond",
        "issue_number": "1",
        "cover_date": "2020-03-04",
        "site_detail_url": "https://comicvine.gamespot.com/x/4050-42/",
        "deck": "<p>A <b>great</b> start.</p>",
        "person_credits": [
            {"name": "A. Writer", "role": "Writer"},
            {"name": "B. Artist", "role": "Penciller/Artist"},
            {"name": "C. Inker", "role": "Inker"},
            {"name": "D. Cover", "role": "Cover Artist"},
        ],
        "character_credits": [{"name": "Hero"}],
        "team_credits": [{"name": "The Team"}],
        "location_credits": [{"name": "New York"}],
        "story_arc_credits": [{"name": "First Arc"}],
        "tags": [{"name": "Legacy"}],
        "genres": [{"name": "Superhero"}],
        "image": {"original_url": "https://img.example/cover.jpg", "width": 100, "height": 150},
    }
    selection = {
        "candidate_id": 987,
        "name": "Example",
        "start_year": "2020",
        "publisher": "Marvel",
        "count_of_issues": 12,
    }
    metadata = _comicvine.metadata_candidate(selection, "Example (2020)", "Marvel/Example (2020)/x.cbz", issue)
    assert metadata["writer"] == "A. Writer"
    assert metadata["penciller"] == "B. Artist"
    assert metadata["cover_artist"] == "D. Cover"
    assert metadata["characters"] == "Hero"
    assert metadata["genre"] == "Superhero"
    assert metadata["summary"] == "A great start."
    assert metadata["cover_url"].endswith("cover.jpg")
    assert metadata["comicvine_issue_id"] == 42
    assert metadata["comicvine_volume_id"] == 987


def test_metadata_candidate_omits_missing_optional_fields():
    metadata = _comicvine.metadata_candidate(
        {"candidate_id": 1, "name": "X", "start_year": "2020", "publisher": "DC"},
        "X (2020)", "DC/X (2020)/X #1.cbz",
        {"id": 2, "issue_number": "1", "cover_date": "2020-00-00", "name": "X"},
    )
    assert "writer" not in metadata
    assert "summary" not in metadata
    assert "month" not in metadata
