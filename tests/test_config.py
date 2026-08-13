

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
