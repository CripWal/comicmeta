from unittest import mock

from comicmeta import _tui


def test_alt_screen_enter_leave_is_idempotent():
    import io
    _tui._alt_screen = False
    buf = io.StringIO()
    with mock.patch("comicmeta._tui.is_interactive", return_value=True):
        with mock.patch("sys.stdout", buf):
            _tui.enter_alt_screen()
            _tui.enter_alt_screen()  # nested enter: no second escape
            _tui.leave_alt_screen()
            _tui.leave_alt_screen()  # leave after leave: no second escape
    assert buf.getvalue().count("\x1b[?1049h") == 1
    assert buf.getvalue().count("\x1b[?1049l") == 1
    assert _tui._alt_screen is False


def test_prompt_edit_noninteractive_returns_input():
    with mock.patch("comicmeta._tui.is_interactive", return_value=False):
        with mock.patch("builtins.input", return_value="COMICVINE_API_KEY"):
            assert _tui.prompt_edit("k: ", current="OLD") == "COMICVINE_API_KEY"


def test_prompt_edit_noninteractive_keeps_current_on_empty():
    with mock.patch("comicmeta._tui.is_interactive", return_value=False):
        with mock.patch("builtins.input", return_value=""):
            assert _tui.prompt_edit("k: ", current="OLD") == "OLD"


def test_prompt_edit_noninteractive_eof_returns_none():
    with mock.patch("comicmeta._tui.is_interactive", return_value=False):
        with mock.patch("builtins.input", side_effect=EOFError):
            assert _tui.prompt_edit("k: ", current="OLD") is None


def test_prompt_edit_key_sequence():
    """Simulate: type 'a', backspace, type 'bc', Enter -> 'bc'."""
    keys = iter([b"a", b"\x7f", b"b", b"c", b"\r"])
    with mock.patch("comicmeta._tui.is_interactive", return_value=True):
        with mock.patch("comicmeta._tui._HAS_TERMIOS", True):
            with mock.patch("sys.stdin.fileno", return_value=0):
                with mock.patch("comicmeta._tui.os.read", lambda *a: next(keys)):
                    with mock.patch("comicmeta._tui.termios"):
                        with mock.patch("comicmeta._tui.tty"):
                            result = _tui.prompt_edit("k: ", current="")
    assert result == "bc"


def test_prompt_edit_cancel_on_ctrl_c():
    keys = iter([b"x", b"\x03"])
    with mock.patch("comicmeta._tui.is_interactive", return_value=True):
        with mock.patch("comicmeta._tui._HAS_TERMIOS", True):
            with mock.patch("sys.stdin.fileno", return_value=0):
                with mock.patch("comicmeta._tui.os.read", lambda *a: next(keys)):
                    with mock.patch("comicmeta._tui.termios"):
                        with mock.patch("comicmeta._tui.tty"):
                            result = _tui.prompt_edit("k: ", current="")
    assert result is None


def test_prompt_edit_prefill_and_arrows():
    """Prefill 'abc', move left twice, type 'X', Enter -> 'aXbc'."""
    keys = iter([b"\x1b", b"[", b"D", b"\x1b", b"[", b"D", b"X", b"\r"])
    with mock.patch("comicmeta._tui.is_interactive", return_value=True):
        with mock.patch("comicmeta._tui._HAS_TERMIOS", True):
            with mock.patch("sys.stdin.fileno", return_value=0):
                with mock.patch("comicmeta._tui.os.read", lambda *a: next(keys)):
                    with mock.patch("comicmeta._tui.select.select", return_value=([object()], [], [])):
                        with mock.patch("comicmeta._tui.termios"):
                            with mock.patch("comicmeta._tui.tty"):
                                result = _tui.prompt_edit("k: ", current="abc")
    assert result == "aXbc"


def test_prompt_edit_lone_esc_ignored():
    """A lone ESC must be ignored and must not swallow the next typed char."""
    keys = iter([b"\x1b", b"X", b"\r"])
    with mock.patch("comicmeta._tui.is_interactive", return_value=True):
        with mock.patch("comicmeta._tui._HAS_TERMIOS", True):
            with mock.patch("sys.stdin.fileno", return_value=0):
                with mock.patch("comicmeta._tui.os.read", lambda *a: next(keys)):
                    # lone ESC: select says nothing ready
                    with mock.patch("comicmeta._tui.select.select", return_value=([], [], [])):
                        with mock.patch("comicmeta._tui.termios"):
                            with mock.patch("comicmeta._tui.tty"):
                                result = _tui.prompt_edit("k: ", current="abc")
    assert result == "abcX"


def test_prompt_edit_multi_byte_escape_no_leak():
    """A Ctrl+Arrow sequence (ESC [ 1 ; 5 D) must not leak bytes into the value."""
    keys = iter([b"\x1b", b"[", b"1", b";", b"5", b"D", b"X", b"\r"])
    with mock.patch("comicmeta._tui.is_interactive", return_value=True):
        with mock.patch("comicmeta._tui._HAS_TERMIOS", True):
            with mock.patch("sys.stdin.fileno", return_value=0):
                with mock.patch("comicmeta._tui.os.read", lambda *a: next(keys)):
                    with mock.patch("comicmeta._tui.select.select", return_value=([object()], [], [])):
                        with mock.patch("comicmeta._tui.termios"):
                            with mock.patch("comicmeta._tui.tty"):
                                result = _tui.prompt_edit("k: ", current="abc")
    # ESC[1;5D = Ctrl+left arrow: move cursor left once, no leak; then type X.
    assert result == "abXc"


def test_prompt_edit_esc_then_printable_not_swallowed():
    """ESC followed by a printable char must not swallow or insert the char."""
    keys = iter([b"\x1b", b"Z", b"X", b"\r"])
    with mock.patch("comicmeta._tui.is_interactive", return_value=True):
        with mock.patch("comicmeta._tui._HAS_TERMIOS", True):
            with mock.patch("sys.stdin.fileno", return_value=0):
                with mock.patch("comicmeta._tui.os.read", lambda *a: next(keys)):
                    # select is ready for the ESC + lead byte, then nothing follows.
                    with mock.patch("comicmeta._tui.select.select", side_effect=[
                        ([object()], [], []),
                        ([], [], []),
                    ]):
                        with mock.patch("comicmeta._tui.termios"):
                            with mock.patch("comicmeta._tui.tty"):
                                result = _tui.prompt_edit("k: ", current="")
    # ESC + Z: ESC handler reads 'Z' as the post-ESC byte, sees it's not '[',
    # drains nothing more; then X is typed normally.
    assert result == "X"
