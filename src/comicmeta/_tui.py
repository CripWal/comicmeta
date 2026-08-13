"""Terminal UI helpers: raw arrow-key input and single-key prompts.

Uses termios cbreak mode on POSIX. Falls back to plain `input()` reads when a
TTY is unavailable (piped/non-interactive), where arrow navigation is skipped
and the caller should use its prompt path instead.
"""

from __future__ import annotations

import atexit
import select
import sys

try:
    import termios
    import tty

    _HAS_TERMIOS = True
except ImportError:  # pragma: no cover - non-POSIX
    _HAS_TERMIOS = False

_no_input = False


def set_no_input(enabled: bool) -> None:
    """Enable/disable --no-input: refuse prompts instead of blocking on them."""
    global _no_input
    _no_input = enabled


def is_no_input() -> bool:
    return _no_input


def is_interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


_alt_screen = False


def enter_alt_screen() -> None:
    """Switch to the alternate screen buffer so the terminal can't scroll back
    into the app (scroll-lock). No-op on non-TTY. Registers a single atexit
    hook so the main screen is restored even on early exit."""
    global _alt_screen
    if not is_interactive() or _alt_screen:
        return
    _alt_screen = True
    sys.stdout.write("\033[?1049h\033[H")
    sys.stdout.flush()
    atexit.register(leave_alt_screen)


def leave_alt_screen() -> None:
    """Restore the main screen buffer and scrollback.

    Idempotent: nested enter/leave cycles (dashboard plus an interactive
    subcommand) each leave exactly one ``\\x1b[?1049l``, and the atexit hook
    never double-fires behind an explicit leave.
    """
    global _alt_screen
    if not is_interactive() or not _alt_screen:
        return
    _alt_screen = False
    sys.stdout.write("\033[?1049l")
    sys.stdout.flush()


def erase_lines(n: int = 1) -> None:
    """Erase the current line plus the `n` lines above it, ending on the first
    erased line.

    Used to dismiss an acknowledgment line before leaving the alt screen so a
    stale prompt like ``[Enter] return to dashboard`` does not survive the
    exit. No-op when the terminal is not interactive.
    """
    if not is_interactive():
        return
    sys.stdout.write("\r" + "\x1b[1A\x1b[2K" * n)
    sys.stdout.flush()


def _read_arrow_key(fd: int) -> str:
    """Read one key under cbreak mode, decoding arrow escape sequences."""
    sequence = sys.stdin.read(1)
    if sequence == "":
        return "ctrl-d"  # EOF / Ctrl-D
    if sequence != "\x1b":
        return sequence
    if sys.stdin.read(1) != "[":
        return "esc"
    code = sys.stdin.read(1)
    return {
        "A": "up",
        "B": "down",
        "C": "right",
        "D": "left",
    }.get(code, "esc")


def read_key() -> str:
    """Read one keypress. Returns a normalized name for special keys."""
    if not is_interactive() or not _HAS_TERMIOS:
        try:
            key = input().strip().casefold()
        except EOFError:
            return "ctrl-d"
        except KeyboardInterrupt:
            return "ctrl-c"
        return key
    fd = sys.stdin.fileno()
    previous = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        try:
            key = _read_arrow_key(fd)
        except KeyboardInterrupt:
            key = "\x03"
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, previous)
    if key in {"\r", "\n"}:
        return "enter"
    if key == "\x03":
        return "ctrl-c"
    if key == "\x04":
        return "ctrl-d"
    return key


def confirm(prompt: str, default: bool = False) -> bool:
    """Yes/no prompt with arrow-key or y/n input."""
    suffix = "[Y/n]" if default else "[y/N]"
    print(f"{prompt} {suffix} ", end="", flush=True)
    answer = read_key()
    print()
    if answer == "enter":
        return default
    return answer.casefold() in {"y", "yes"}


def prompt_hidden(prompt: str) -> str:
    """Read a line of input with echo disabled (for secrets)."""
    print(prompt, end="", flush=True)
    if not is_interactive() or not _HAS_TERMIOS:
        value = input()
        print()
        return value
    fd = sys.stdin.fileno()
    previous = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        new = termios.tcgetattr(fd)
        new[3] = new[3] & ~termios.ECHO  # type: ignore[index]
        termios.tcsetattr(fd, termios.TCSADRAIN, new)
        chars = []
        while True:
            char = sys.stdin.read(1)
            if char == "" or char == "\x04":  # EOF / Ctrl-D
                break
            if char == "\r" or char == "\n":
                break
            if char == "\x7f" or char == "\b":  # backspace
                if chars:
                    chars.pop()
                continue
            if char == "\x03":  # Ctrl-C
                print()
                raise KeyboardInterrupt
            chars.append(char)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, previous)
    print()
    return "".join(chars)


def _redraw_line(prompt: str, value: list[str], cursor: int, secret: bool) -> None:
    """Redraw the current input line in place, restoring the cursor position."""
    visible = "".join("•" if secret else ch for ch in value)
    # \r start of line, \x1b[K clear to end, reprint, then move cursor left.
    tail = f"\r{prompt}{visible}\x1b[K"
    back = f"\x1b[{len(visible) - cursor}D"
    print(tail + back, end="", flush=True)


def _escape_action() -> str:
    """Read and fully consume one ESC sequence, returning 'left'/'right'/''.

    A lone ESC or an incomplete/multi-byte sequence is consumed without ever
    returning bytes that could leak into the edited value. Uses non-blocking
    reads so a bare ESC never blocks waiting for more input.
    """
    if not select.select([sys.stdin], [], [], 0.05)[0]:
        return ""  # lone ESC: nothing follows
    if sys.stdin.read(1) != "[":
        # ESC followed by a printable char (e.g. alt+key) — drain nothing, ignore.
        return ""
    # CSI sequence: consume parameter bytes and any intermediates until a final byte.
    while True:
        if not select.select([sys.stdin], [], [], 0.05)[0]:
            return ""  # incomplete sequence: drop it
        code = sys.stdin.read(1)
        if code in ("", "\x03", "\x04"):
            return ""
        if code == "D":
            return "left"
        if code == "C":
            return "right"
        if code in "ABCD":
            return ""  # up/down/home/end etc: recognized, no cursor action
        if code == "~":
            return ""  # function-key terminator: ignore
        # parameter byte (digit, ';', '?', etc.) — keep consuming
        if code in "0123456789;?<>=!":
            continue
        return ""  # any other byte: terminate and ignore


def prompt_edit(prompt: str, current: str = "", secret: bool = False) -> str | None:
    """Line editor with arrow-key cursor movement and in-place editing.

    Prefills `current`. Left/right arrows move the cursor, backspace deletes,
    typing inserts at the cursor, Enter confirms. Returns the edited string, or
    None on cancel (Ctrl-C/Ctrl-D/EOF). When `secret` is True, characters echo
    as `•`.
    """
    if not is_interactive() or not _HAS_TERMIOS:
        print(prompt, end="", flush=True)
        try:
            line = input()
        except (EOFError, KeyboardInterrupt):
            print()
            return None
        print()
        return line if line.strip() else current

    value = list(current)
    cursor = len(value)
    print(prompt, end="", flush=True)
    _redraw_line(prompt, value, cursor, secret)
    fd = sys.stdin.fileno()
    previous = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        while True:
            char = sys.stdin.read(1)
            if char in ("", "\x04"):  # EOF / Ctrl-D
                print()
                return None
            if char == "\x03":  # Ctrl-C
                print()
                return None
            if char in ("\r", "\n"):  # Enter
                print()
                return "".join(value)
            if char in ("\x7f", "\b"):  # backspace
                if cursor > 0:
                    del value[cursor - 1]
                    cursor -= 1
                    _redraw_line(prompt, value, cursor, secret)
                continue
            if char == "\x1b":  # escape sequence (arrow keys / lone ESC)
                action = _escape_action()
                if action == "left":
                    cursor = max(0, cursor - 1)
                    _redraw_line(prompt, value, cursor, secret)
                elif action == "right":
                    cursor = min(len(value), cursor + 1)
                    _redraw_line(prompt, value, cursor, secret)
                # lone ESC and unrecognized sequences: ignore, never insert bytes
                continue
            if char >= " ":  # printable character: insert at cursor
                value.insert(cursor, char)
                cursor += 1
                _redraw_line(prompt, value, cursor, secret)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, previous)
