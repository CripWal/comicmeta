from comicmeta._humanize import pretty_bytes, pretty_duration


def test_duration():
    assert pretty_duration(0.5) == "500ms"
    assert pretty_duration(2.5) == "2.5s"
    assert pretty_duration(75) == "1m"
    assert pretty_duration(3700) == "1h"


def test_bytes():
    assert pretty_bytes(500) == "500 B"
    assert pretty_bytes(2048) == "2.0 KiB"
    assert pretty_bytes(5 * 1024 * 1024) == "5.0 MiB"
    assert pretty_bytes(3 * 1024 * 1024 * 1024) == "3.0 GiB"


def test_none():
    assert pretty_duration(None) == "—"
    assert pretty_bytes(None) == "—"
