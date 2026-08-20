import io
from unittest import mock

from comicmeta import _spinner


def test_spinner_clears_on_exit():
    stream = io.StringIO()
    with mock.patch("sys.stderr", stream):
        with _spinner.Spinner("Working", stream=stream) as s:
            assert s._enabled is False  # StringIO is not a TTY
    # non-TTY path prints the final message as a plain line
    assert "Working" in stream.getvalue()


def test_spinner_non_tty_prints_final_line():
    stream = io.StringIO()
    with _spinner.Spinner("Doing work", stream=stream) as s:
        s.update("Halfway")
    assert "Halfway" in stream.getvalue()


def test_spinner_frames_present():
    assert "⠋" in _spinner.FRAMES["dots"]
    assert _spinner.FRAMES["line"] == ["-", "\\", "|", "/"]
    assert len(_spinner.FRAMES["dots8Bit"]) > 100


def test_spinner_tty_enabled():
    class FakeStream:
        def isatty(self):
            return True

        def write(self, text):
            return len(text)

        def flush(self):
            pass

    s = _spinner.Spinner("Work", stream=FakeStream())
    assert s._enabled is True
    # A TTY spinner starts a daemon thread on enter.
    with s:
        assert s._thread is not None
        assert s._thread.daemon is True
    # After exit, the thread is joined and stopped.
    assert s._stop.is_set()


def test_spinner_progress_bar_tty():
    class FakeStream:
        def isatty(self):
            return True

        def write(self, text):
            return len(text)

        def flush(self):
            pass

    s = _spinner.Spinner("Work", stream=FakeStream())
    with s:
        s.progress(2, 4)
    assert "%" in s.message
    assert "2/4" in s.message


def test_spinner_disabled_over_remote_pty_emits_plain_lines():
    # A remote `ssh -t` pty reports as a TTY, so animation would flood the
    # scrollback. COMICMETA_NO_ANIMATION (set by the NAS executor) must turn
    # off the in-place redraw and instead emit one plain line per update.
    class FakeStream:
        def isatty(self):
            return True

        def __init__(self):
            self.data = ""

        def write(self, text):
            self.data += text
            return len(text)

        def flush(self):
            pass

    stream = FakeStream()
    with mock.patch.dict("os.environ", {"COMICMETA_NO_ANIMATION": "1"}):
        s = _spinner.Spinner("Work", stream=stream)
        assert s._enabled is False
        with s:
            s.progress(2, 4, item="Marvel/a.cbz")
            s.progress(3, 4, item="Marvel/b.cbz")
            s.succeed("Wrote 4")
    out = stream.data
    assert "Wrote 2/4  Marvel/a.cbz" in out
    assert "Wrote 3/4  Marvel/b.cbz" in out
    assert "✓ Wrote 4" in out
    # No animated frames leaked.
    assert "\r" not in out



def test_spinner_succeed_non_tty_prints_checkmark():
    stream = io.StringIO()
    with _spinner.Spinner("Work", stream=stream) as s:
        s.progress(2, 4)
        s.succeed("Wrote 4")
    out = stream.getvalue()
    assert "✓ Wrote 4" in out
    # the intermediate progress message must NOT leak (succeed suppresses __exit__)
    assert "2/4" not in out


def test_clear_active_spinner_clears_line():
    class FakeStream:
        def __init__(self):
            self.data = ""

        def isatty(self):
            return True

        def write(self, text):
            self.data += text
            return len(text)

        def flush(self):
            pass

    stream = FakeStream()
    s = _spinner.Spinner("working", stream=stream)
    with s:
        assert _spinner._ACTIVE is s
        _spinner.clear_active_spinner()
    assert "\x1b[K" in stream.data
    assert _spinner._ACTIVE is None


def test_die_clears_spinner_without_active():
    from unittest import mock
    from comicmeta._common import die
    # die must not crash when no spinner is active (imports clear_active_spinner lazily)
    with mock.patch("comicmeta._spinner._ACTIVE", None):
        try:
            die("boom")
        except SystemExit:
            pass
    assert True


def test_spinner_progress_footer():
    class FakeStream:
        def isatty(self):
            return True

        def write(self, text):
            return len(text)

        def flush(self):
            pass

    s = _spinner.Spinner("", stream=FakeStream())
    s.progress(2, 3, item="Marvel/a.cbz")
    assert "2/3" in s.message
    assert "Marvel/a.cbz" in s.message
