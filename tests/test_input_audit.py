import io
import json
import contextlib
from unittest import mock

from comicmeta import _tui


def _patch_tty():
    stack = contextlib.ExitStack()
    stack.enter_context(mock.patch("comicmeta._tui.is_interactive", return_value=True))
    stack.enter_context(mock.patch("comicmeta._tui._HAS_TERMIOS", True))
    stack.enter_context(mock.patch("sys.stdin.fileno", return_value=0))
    stack.enter_context(mock.patch("comicmeta._tui.termios"))
    stack.enter_context(mock.patch("comicmeta._tui.tty"))
    return stack


def test_prompt_edit_ctrl_c_keyboard_interrupt_cancels():
    with mock.patch("comicmeta._tui.os.read", side_effect=KeyboardInterrupt):
        with _patch_tty() as patches:
            assert _tui.prompt_edit("k: ", current="abc") is None


def test_prompt_hidden_ctrl_c_keyboard_interrupt_returns_none():
    with mock.patch("sys.stdin.read", side_effect=KeyboardInterrupt):
        with _patch_tty():
            assert _tui.prompt_hidden("pw: ") is None


def test_prompt_hidden_returns_entered_secret():
    keys = iter(["s", "e", "c", "\r"])
    with mock.patch("sys.stdin.read", lambda *a: next(keys)):
        with _patch_tty():
            assert _tui.prompt_hidden("pw: ") == "sec"


def test_review_volumes_interactive_leaves_alt_screen(tmp_path):
    from comicmeta._commands.review_volumes import Palette, interactive

    report = tmp_path / "c.json"
    report.write_text(json.dumps({
        "source": str(tmp_path),
        "items": [{
            "query": "Batman (2017)", "path": "Batman #001.cbr", "format": "cbr",
            "status": "review-required", "issue_number_from_filename": "001",
            "candidates": [{"id": 104042, "name": "Batman", "start_year": "2017",
                            "count_of_issues": 1, "publisher": {"name": "DC Comics"},
                            "site_detail_url": "https://cv.example/104042"}],
        }],
    }))
    buf = io.StringIO()
    _tui._alt_screen = False
    with mock.patch("comicmeta._tui.is_interactive", return_value=True):
        with mock.patch("comicmeta._tui.read_key", side_effect=["enter", "q"]):
            with mock.patch("sys.stdout", buf):
                interactive(report, tmp_path / "s.json", tmp_path / "sm.md", {}, Palette(False))
    assert _tui._alt_screen is False
    assert "\x1b[?1049h" in buf.getvalue()
    assert "\x1b[?1049l" in buf.getvalue()


def test_review_volumes_empty_leaves_alt_screen(tmp_path):
    from comicmeta._commands.review_volumes import Palette, interactive

    report = tmp_path / "c.json"
    report.write_text(json.dumps({"source": str(tmp_path), "items": []}))
    buf = io.StringIO()
    _tui._alt_screen = False
    with mock.patch("comicmeta._tui.is_interactive", return_value=True):
        with mock.patch("comicmeta._tui.read_key", return_value="q"):
            with mock.patch("sys.stdout", buf):
                interactive(report, tmp_path / "s.json", tmp_path / "sm.md", {}, Palette(False))
    assert _tui._alt_screen is False
    assert "\x1b[?1049l" in buf.getvalue()


def test_review_issues_die_leaves_alt_screen(tmp_path):
    from comicmeta._commands.review_issues import Palette, interactive

    report = tmp_path / "i.json"
    report.write_text(json.dumps({
        "active_source": str(tmp_path), "scanned_source": str(tmp_path), "series": [],
    }))
    buf = io.StringIO()
    _tui._alt_screen = False
    with mock.patch("comicmeta._tui.is_interactive", return_value=True):
        with mock.patch("sys.stdout", buf):
            with contextlib.redirect_stderr(io.StringIO()):
                try:
                    interactive(report, tmp_path / "s.json", tmp_path / "sm.md", Palette(False))
                except SystemExit:
                    pass
    assert _tui._alt_screen is False
    assert "\x1b[?1049l" in buf.getvalue()


def test_clear_flags_empty_leaves_alt_screen(tmp_path, monkeypatch):
    from argparse import Namespace
    from comicmeta import _config
    from comicmeta._commands.flags import clear_flags
    from comicmeta._common import Palette

    monkeypatch.setattr(_config, "get", lambda flat, key: None)
    buf = io.StringIO()
    _tui._alt_screen = False
    args = Namespace(source=tmp_path, no_color=True)
    with mock.patch("comicmeta._tui.is_interactive", return_value=True):
        with mock.patch("sys.stdout", buf):
            clear_flags(args, Palette(False))
    assert _tui._alt_screen is False
    assert "\x1b[?1049l" in buf.getvalue()


def test_flush_input_calls_tcflush():
    with mock.patch("comicmeta._tui.is_interactive", return_value=True):
        with mock.patch("comicmeta._tui._HAS_TERMIOS", True):
            with mock.patch("comicmeta._tui.termios") as tios:
                with mock.patch("sys.stdin", new=mock.MagicMock()) as stdin:
                    _tui.flush_input()
    tios.tcflush.assert_called_once_with(stdin, tios.TCIFLUSH)


def test_flush_input_noop_when_not_interactive():
    with mock.patch("comicmeta._tui.is_interactive", return_value=False):
        with mock.patch("comicmeta._tui.termios") as tios:
            _tui.flush_input()
    tios.tcflush.assert_not_called()


def test_display_width_counts_wide_and_combining():
    assert _tui._display_width("abc") == 3
    assert _tui._display_width("漫画") == 4
    assert _tui._display_width("e\u0301") == 1
    assert _tui._display_width("😀") == 2
    assert _tui._char_width("A") == 1
    assert _tui._char_width("\u0301") == 0


def test_redraw_line_cursor_math_uses_display_width():
    buf = io.StringIO()
    with mock.patch("sys.stdout", buf):
        _tui._redraw_line("k: ", list("漫画"), cursor=1, secret=False)
    out = buf.getvalue()
    assert out.startswith("\rk: 漫画\x1b[K")
    assert "\x1b[2D" in out


def test_read_arrow_key_application_cursor_mode():
    keys = iter([b"\x1b", b"O", b"B"])
    with mock.patch("comicmeta._tui.select.select", return_value=([object()], [], [])):
        with mock.patch("comicmeta._tui.os.read", lambda *a: next(keys)):
            assert _tui._read_arrow_key(0) == "down"


def test_read_arrow_key_lone_esc_does_not_block():
    keys = iter([b"\x1b"])
    # byte 1 (ESC) ready; the post-ESC prefix read times out (not ready)
    with mock.patch("comicmeta._tui.select.select", side_effect=[
        ([object()], [], []),
        ([], [], []),
    ]):
        with mock.patch("comicmeta._tui.os.read", lambda *a: next(keys)):
            assert _tui._read_arrow_key(0) == "esc"


def test_prompt_edit_ss3_function_key_does_not_leak():
    keys = iter([b"\x1b", b"O", b"P", b"X", b"\r"])
    with mock.patch("comicmeta._tui.os.read", lambda *a: next(keys)):
        with mock.patch("comicmeta._tui.select.select", side_effect=[
            ([object()], [], []),  # ESC: lead byte available
            ([object()], [], []),  # ESC O: function-key byte available
            ([], [], []),          # nothing follows: drain stops
        ]):
            with _patch_tty():
                result = _tui.prompt_edit("k: ", current="")
    assert result == "X"


def test_prompt_edit_app_mode_arrows():
    keys = iter([b"\x1b", b"O", b"D", b"X", b"\r"])
    with mock.patch("comicmeta._tui.os.read", lambda *a: next(keys)):
        with mock.patch("comicmeta._tui.select.select", return_value=([object()], [], [])):
            with _patch_tty():
                result = _tui.prompt_edit("k: ", current="abc")
    assert result == "abXc"
