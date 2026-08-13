"""Test isolation: subprocess-run commands use an empty config dir.

`cli.main()` routes any command through the NAS executor when the active
context is a NAS context. Tests that spawn `python3 -m comicmeta` subprocesses
inherit the user's real `~/.config/comicmeta`, whose active context may be a
NAS context — pointing each subprocess at an empty config dir keeps them
local. In-process tests that deliberately exercise contexts own their own
`XDG_CONFIG_HOME`/monkeypatching.
"""

import pytest


@pytest.fixture(autouse=True)
def _isolate_config_home(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    yield
