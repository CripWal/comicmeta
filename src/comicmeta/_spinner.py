"""Animated spinners for long-running operations.

Frame sets are the authentic `cli-spinners` collection (MIT, sindresorhus).
Spinners render on stderr so stdout stays clean for machine output. They only
animate when stderr is a TTY; piped/non-interactive output stays plain and a
final status line is printed instead.
"""

from __future__ import annotations

import os
import sys
import threading
import time

FRAMES = {
    "dots": ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"],
    "dots2": ["⣾", "⣽", "⣻", "⢿", "⡿", "⣟", "⣯", "⣷"],
    "dots8Bit": [
        "⠀", "⠁", "⠂", "⠃", "⠄", "⠅", "⠆", "⠇", "⡀", "⡁", "⡂", "⡃", "⡄", "⡅", "⡆", "⡇",
        "⠈", "⠉", "⠊", "⠋", "⠌", "⠍", "⠎", "⠏", "⡈", "⡉", "⡊", "⡋", "⡌", "⡍", "⡎", "⡏",
        "⠐", "⠑", "⠒", "⠓", "⠔", "⠕", "⠖", "⠗", "⡐", "⡑", "⡒", "⡓", "⡔", "⡕", "⡖", "⡗",
        "⠘", "⠙", "⠚", "⠛", "⠜", "⠝", "⠞", "⠟", "⡘", "⡙", "⡚", "⡛", "⡜", "⡝", "⡞", "⡟",
        "⠠", "⠡", "⠢", "⠣", "⠤", "⠥", "⠦", "⠧", "⡠", "⡡", "⡢", "⡣", "⡤", "⡥", "⡦", "⡧",
        "⠨", "⠩", "⠪", "⠫", "⠬", "⠭", "⠮", "⠯", "⡨", "⡩", "⡪", "⡫", "⡬", "⡭", "⡮", "⡯",
        "⠰", "⠱", "⠲", "⠳", "⠴", "⠵", "⠶", "⠷", "⡰", "⡱", "⡲", "⡳", "⡴", "⡵", "⡶", "⡷",
        "⠸", "⠹", "⠺", "⠻", "⠼", "⠽", "⠾", "⠿", "⡸", "⡹", "⡺", "⡻", "⡼", "⡽", "⡾", "⡿",
        "⢀", "⢁", "⢂", "⢃", "⢄", "⢅", "⢆", "⢇", "⣀", "⣁", "⣂", "⣃", "⣄", "⣅", "⣆", "⣇",
        "⢈", "⢉", "⢊", "⢋", "⢌", "⢍", "⢎", "⢏", "⣈", "⣉", "⣊", "⣋", "⣌", "⣍", "⣎", "⣏",
        "⢐", "⢑", "⢒", "⢓", "⢔", "⢕", "⢖", "⢗", "⣐", "⣑", "⣒", "⣓", "⣔", "⣕", "⣖", "⣗",
        "⢘", "⢙", "⢚", "⢛", "⢜", "⢝", "⢞", "⢟", "⣘", "⣙", "⣚", "⣛", "⣜", "⣝", "⣞", "⣟",
        "⢠", "⢡", "⢢", "⢣", "⢤", "⢥", "⢦", "⢧", "⣠", "⣡", "⣢", "⣣", "⣤", "⣥", "⣦", "⣧",
        "⢨", "⢩", "⢪", "⢫", "⢬", "⢭", "⢮", "⢯", "⣨", "⣩", "⣪", "⣫", "⣬", "⣭", "⣮", "⣯",
        "⢰", "⢱", "⢲", "⢳", "⢴", "⢵", "⢶", "⢷", "⣰", "⣱", "⣲", "⣳", "⣴", "⣵", "⣶", "⣷",
        "⢸", "⢹", "⢺", "⢻", "⢼", "⢽", "⢾", "⢿", "⣸", "⣹", "⣺", "⣻", "⣼", "⣽", "⣾", "⣿",
    ],
    "line": ["-", "\\", "|", "/"],
    "bounce": ["⠁", "⠂", "⠄", "⠂"],
    "aesthetic": ["▰▱▱▱▱▱▱", "▰▰▱▱▱▱▱", "▰▰▰▱▱▱▱", "▰▰▰▰▱▱▱", "▰▰▰▰▰▱▱", "▰▰▰▰▰▰▱", "▰▰▰▰▰▰▰", "▰▱▱▱▱▱▱"],
    "bouncingBar": ["[    ]", "[=   ]", "[==  ]", "[=== ]", "[====]", "[ ===]", "[  ==]", "[   =]", "[    ]"],
}

_DEFAULT_INTERVAL = 0.1

# The most recently started spinner that is still running. `die()` clears it
# before printing an error so the message isn't glued to a spinner frame.
_ACTIVE: "Spinner | None" = None


def _animation_allowed(stream) -> bool:
    """Whether in-place spinner animation should run for `stream`.

    Animation needs a real interactive terminal. It is suppressed when the
    stream is not a TTY, or when `COMICMETA_NO_ANIMATION` is set. The latter is
    exported by the NAS executors when a command runs over `ssh -t`: the remote
    pty reports as a TTY, but in-place `\r\x1b[K` redraws get captured as a
    scrollback flood rather than overwriting one line.
    """
    if not stream.isatty():
        return False
    return not os.environ.get("COMICMETA_NO_ANIMATION")


class Checklist:
    """A listr-style task list that renders a spinner per phase, then a ✓.

    Each phase starts as a spinner line; calling `.succeed(name, detail)` turns
    it into a permanent checkmark line and moves the cursor to the next phase.
    Non-TTY output prints plain `✓ name` lines as they complete.
    """

    def __init__(self, stream=None) -> None:
        self.stream = stream or sys.stderr
        self._enabled = _animation_allowed(self.stream)
        self._active: Spinner | None = None
        self._completed: list[tuple[str, str]] = []
        self._lines_written = 0

    def start(self, name: str) -> "Checklist":
        """Begin a new phase, rendering an animated spinner for it."""
        self._finish_active()
        self._active = Spinner(name, stream=self.stream)
        if self._enabled:
            self._active.__enter__()
        return self

    def update(self, message: str) -> None:
        if self._active is not None:
            self._active.update(message)

    def succeed(self, name: str, detail: str = "") -> None:
        """Complete the current phase with a permanent checkmark line."""
        self._completed.append((name, detail))
        self._finish_active()
        line = f"✓ {name}"
        if detail:
            line += f" — {detail}"
        self.stream.write(line + "\n")
        self.stream.flush()
        self._lines_written += 1

    def _finish_active(self) -> None:
        if self._active is not None:
            if self._enabled:
                self._active.__exit__(None, None, None)
            self._active = None
            if self._enabled:
                self.stream.write("\n")
                self.stream.flush()

    def finish(self) -> None:
        """End the checklist, leaving all completed lines on screen."""
        self._finish_active()


class Spinner:
    """An animated stderr spinner that stops and clears cleanly.

    Usage::

        with Spinner("Writing archives") as s:
            for path in paths:
                s.update(f"Wrote {path.name}")
                do_work(path)
    """

    def __init__(self, message: str = "", style: str = "dots", stream=None) -> None:
        self.message = message
        self.frames = FRAMES.get(style, FRAMES["dots"])
        self.stream = stream or sys.stderr
        self._enabled = _animation_allowed(self.stream)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._frame = 0
        self._succeeded = False
        self._started_at: float | None = None

    def _render(self) -> None:
        frame = self.frames[self._frame % len(self.frames)]
        text = f"{frame} {self.message}"
        self.stream.write(f"\r\x1b[K{text}")
        self.stream.flush()
        self._frame += 1

    def _run(self) -> None:
        while not self._stop.is_set():
            self._render()
            self._stop.wait(_DEFAULT_INTERVAL)

    def update(self, message: str) -> None:
        """Change the trailing message without resetting the animation."""
        self.message = message
        if self._enabled:
            self._render()

    def progress(self, done: int, total: int, width: int = 16, item: str = "", eta: bool = True) -> None:
        """Render a progress bar with a persistent x/y footer.

        `done`/`total` drive the bar and `x/y`; `item` names the file currently
        being processed. Non-TTY output keeps the count as a plain line. When
        `eta` is True, an estimated-time-remaining is appended based on elapsed
        time per completed item.
        """
        pct = round(100 * done / total) if total else 100
        filled = width if total == 0 else round(width * done / total)
        bar = "█" * filled + "·" * (width - filled)
        if self._enabled:
            label = f"{bar} {pct:3d}%  {done}/{total}"
            if eta and done > 0 and done < total and self._started_at is not None:
                elapsed = max(0.0, time.monotonic() - self._started_at)
                per_item = elapsed / done
                remaining = int(per_item * (total - done))
                label += f"  {self._fmt_eta(remaining)}"
            self.message = f"{label}  {item}" if item else label
            self._render()
        else:
            # No animation. For piped output this stays silent (the final
            # status line is printed on succeed/exit). But when a NAS executor
            # runs us over `ssh -t` it exports COMICMETA_NO_ANIMATION, because
            # in-place `\r\x1b[K` redraws would flood the scrollback; there we
            # emit one plain line per update so progress stays visible.
            self.message = f"Wrote {done}/{total}" + (f"  {item}" if item else "")
            if os.environ.get("COMICMETA_NO_ANIMATION"):
                self.stream.write(self.message + "\n")
                self.stream.flush()

    @staticmethod
    def _fmt_eta(seconds: int) -> str:
        if seconds >= 3600:
            return f"{seconds // 3600}h{seconds % 3600 // 60:02d}m"
        if seconds >= 60:
            return f"{seconds // 60}m{seconds % 60:02d}s"
        return f"{seconds}s"

    def succeed(self, message: str = "") -> None:
        """Flash a checkmark and clear the line, leaving a permanent ✓ line."""
        self._succeeded = True
        if self._enabled:
            self._stop.set()
            if self._thread:
                self._thread.join(timeout=0.5)
            text = message or self.message
            self.stream.write(f"\r\x1b[K✓ {text}\n")
            self.stream.flush()
        else:
            self.stream.write(f"✓ {message or self.message}\n")
            self.stream.flush()

    def __enter__(self) -> "Spinner":
        global _ACTIVE
        _ACTIVE = self
        self._started_at = time.monotonic()
        if self._enabled:
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        global _ACTIVE
        if _ACTIVE is self:
            _ACTIVE = None
        if self._enabled:
            self._stop.set()
            if self._thread:
                self._thread.join(timeout=0.5)
            self.stream.write(f"\r\x1b[K")
            self.stream.flush()
        elif not self._succeeded:
            self.stream.write(f"{self.message}\n")
            self.stream.flush()


def clear_active_spinner() -> None:
    """Clear the active spinner line (e.g. before printing an error)."""
    spinner = _ACTIVE
    if spinner is not None and spinner._enabled:
        spinner._stop.set()
        if spinner._thread:
            spinner._thread.join(timeout=0.2)
        spinner.stream.write(f"\r\x1b[K")
        spinner.stream.flush()
