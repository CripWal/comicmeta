from unittest import mock

from comicmeta import _tui


def test_confirm_shows_prompt_and_accepts_y(capsys):
    with mock.patch("comicmeta._tui.read_key", return_value="y"):
        result = _tui.confirm("Do it?", default=False)
    captured = capsys.readouterr()
    assert "[y/N]" in captured.out
    assert "Do it?" in captured.out
    assert result is True


def test_confirm_default_true_on_enter(capsys):
    with mock.patch("comicmeta._tui.read_key", return_value="enter"):
        assert _tui.confirm("Go?", default=True) is True


def test_confirm_rejects_n(capsys):
    with mock.patch("comicmeta._tui.read_key", return_value="n"):
        assert _tui.confirm("Go?", default=False) is False


def test_confirm_prints_trailing_newline(capsys):
    with mock.patch("comicmeta._tui.read_key", return_value="y"):
        _tui.confirm("Go?", default=False)
    assert "\n" in capsys.readouterr().out
