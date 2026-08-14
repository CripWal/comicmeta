

def test_load_resolves_state_paths_with_configured_source(tmp_path, monkeypatch):
    """_config.load(None) must resolve state paths via the configured paths.source."""
    from comicmeta import _config
    (tmp_path / "comicmeta.toml").write_text(
        "[paths]\nsource = 'LIBRARY'\ncandidates = 'candidates.json'\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(_config, "state_dir", lambda source: tmp_path / "state")
    flat = _config.load(None)
    assert flat["paths.source"] == "LIBRARY"
    assert flat["paths.candidates"].endswith("state/candidates.json")


def test_global_appearance_overrides_library_theme(tmp_path, monkeypatch):
    from comicmeta import _config
    source = tmp_path / "library"
    source.mkdir()
    (source / "comicmeta.toml").write_text("[appearance]\ntheme = 'classic'\n")
    xdg = tmp_path / "config"
    global_settings = xdg / "comicmeta" / "comicmeta.toml"
    global_settings.parent.mkdir(parents=True)
    global_settings.write_text("[appearance]\ntheme = 'marvel'\n")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))

    assert _config.load(source)["appearance.theme"] == "marvel"


def test_as_int_returns_default_for_bad_types():
    from comicmeta import _config
    assert _config.as_int("lots", 10) == 10
    assert _config.as_int(None, 10) == 10
    assert _config.as_int("10", 10) == 10
    assert _config.as_int(5, 10) == 5
    assert _config.as_int(True, 10) == 1


def test_as_float_returns_default_for_bad_types():
    from comicmeta import _config
    assert _config.as_float("forever", 0.25) == 0.25
    assert _config.as_float(None, 0.25) == 0.25
    assert _config.as_float("0.5", 0.25) == 0.5


def test_hand_edited_bad_types_do_not_crash_discover(tmp_path, monkeypatch):
    from argparse import Namespace

    from comicmeta import _comicvine
    from comicmeta._commands import discover as discover_module

    source = tmp_path / "library"
    source.mkdir()
    (source / "comicmeta.toml").write_text(
        "[api]\n"
        "candidate_limit = 'lots'\n"
        "timeout = 'forever'\n"
        "request_delay = 'slow'\n"
        "concurrency = 'many'\n"
    )
    monkeypatch.setattr(_comicvine, "api_key_from", lambda *a, **k: "fake-key")
    result = {"items": [], "reused": 0, "queried": 0, "added": [], "removed": [], "needs_api_key": []}
    monkeypatch.setattr(discover_module, "rescan", lambda *a, **k: dict(result))
    report = tmp_path / "state" / "report.json"
    args = Namespace(source=source, report=report, limit=None, api_key_env=None, api_key_file=None)
    discover_module.run(args)


def test_hand_edited_bad_backup_retention_does_not_crash_write(tmp_path):
    import pytest
    from argparse import Namespace

    from comicmeta._commands import write as write_module

    source = tmp_path / "library"
    source.mkdir()
    (source / "comicmeta.toml").write_text("[write]\nbackup_retention = 'forever'\n")
    mapping = tmp_path / "mapping.json"
    mapping.write_text("{}")
    args = Namespace(source=source, mapping=mapping, backup_dir=None, report=tmp_path / "report.json",
                     no_backups=False, dry_run=False, yes=False, staging_dir=None, expected_hashes=None)
    with pytest.raises(SystemExit):
        write_module.run(args)


def test_hand_edited_bad_types_do_not_crash_review(tmp_path, monkeypatch):
    import pytest
    from argparse import Namespace

    from comicmeta._commands import discover as discover_module
    from comicmeta._commands import review as review_module

    source = tmp_path / "library"
    source.mkdir()
    (source / "comicmeta.toml").write_text(
        "[api]\n"
        "candidate_limit = 'lots'\n"
        "request_delay = 'slow'\n"
        "concurrency = 'many'\n"
        "[review]\n"
        "high_confidence_score = 'high'\n"
        "high_confidence_margin = 'wide'\n"
    )
    result = {"items": [], "reused": 0, "queried": 0, "added": [], "removed": [], "needs_api_key": []}
    monkeypatch.setattr(discover_module, "rescan", lambda *a, **k: dict(result))
    args = Namespace(source=source, list=False, fresh=False, reopen=False,
                     api_key_env=None, api_key_file=None, no_color=True)
    with pytest.raises(SystemExit):
        review_module.run(args)
