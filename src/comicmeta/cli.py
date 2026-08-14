"""comicmeta command-line interface.

Single tool for the controlled ComicVine metadata pipeline. Discovery and
review are read-only. Execution requires an explicit reviewed JSON mapping and
a backup directory. CBZ is the only writeable format; CBR is reported but never
converted or modified.

Run bare `comicmeta` in your comic library directory: it scans the directory,
shows a two-step dashboard (review → write), and you navigate it with the
arrow keys.
"""

from __future__ import annotations

import argparse
import difflib
import shutil
import sys
import time
from pathlib import Path

import comicmeta
from comicmeta import _commands, _config, _context
from comicmeta import _archive
from comicmeta._comicvine import verify_api_key
from comicmeta._common import PIPELINE, PIPELINE_CHAIN, Palette, color_enabled, render_wordmark, _strip_ansi, _truncate_ansi
from comicmeta._tui import confirm, flush_input, is_interactive, read_key

ISSUES_URL = "https://github.com/CripWal/comicmeta/issues"

REVIEW_COMMANDS = ("review", "discover", "review-volumes", "fetch-issues", "review-issues", "map")
EXEC_COMMANDS = ("stage", "validate", "write", "status", "settings", "covers", "health", "self-test", "setup", "update-check", "logo", "inspect", "organize", "browse", "context", "help", "completion")
INSPECT_COMMANDS = ("browse", "inspect", "flags", "backups")
SOURCE_COMMANDS = {
    "review", "discover", "review-volumes", "fetch-issues", "review-issues",
    "map", "stage", "validate", "write", "convert", "covers", "health",
    "organize", "browse", "inspect", "missing", "backups", "status", "self-test",
}


class _ComicMetaArgumentParser(argparse.ArgumentParser):
    """ArgumentParser that suggests close matches for mistyped subcommands."""

    def error(self, message: str) -> "NoReturn":
        if self._subparsers is not None:
            choices = list(self._subparsers._group_actions[0].choices)
            import re
            match = re.search(r"invalid choice: '([^']+)'", message)
            if match and match.group(1) not in choices:
                matches = difflib.get_close_matches(match.group(1), choices, n=1, cutoff=0.6)
                if matches:
                    message = (
                        f"{message}\n"
                        f"Did you mean: {matches[0]}?\n"
                        f"See `comicmeta {matches[0]} --help` for usage."
                    )
        super().error(message)

DASHBOARD_STEPS = [
    (
        "review",
        [
            "Scan this directory, discover ComicVine candidates, review",
            "volumes and issues, and emit the reviewed mapping. (read-only)",
        ],
    ),
    (
        "write",
        [
            "Back up and insert ComicInfo.xml into the reviewed CBZ files.",
            "(mutating)",
        ],
    ),
    (
        "convert",
        [
            "Convert .cbr archives to .cbz so metadata can be written.",
            "Shows a picker; originals are kept in comicmeta-backups.",
        ],
    ),
    (
        "browse",
        [
            "Navigate the library as an expandable file tree; Enter inspects",
            "a file's existing ComicInfo.xml metadata. (read-only unless edited)",
        ],
    ),
    (
        "organize",
        [
            "Audit and propose strict-Comic organization (AGENTS.md rules).",
            "(dry-run by default)",
        ],
    ),
    (
        "health",
        [
            "Scan the library for corrupt archives and metadata problems.",
            "(read-only)",
        ],
    ),
]


class _PipelineHelpFormatter(argparse.RawDescriptionHelpFormatter):
    """Group subcommands by pipeline phase and add the run order as an epilog."""

    def _format_subparsers(self, action: argparse._SubParsersAction) -> str:
        width = max(len(name) for name in (*REVIEW_COMMANDS, *EXEC_COMMANDS, *INSPECT_COMMANDS))
        help_by_name = {pseudo.dest: pseudo.help for pseudo in action._choices_actions}
        lines: list[str] = []
        for header, names in (
            ("Read-only review pipeline", REVIEW_COMMANDS),
            ("Staging + execution", EXEC_COMMANDS),
            ("Inspection", INSPECT_COMMANDS),
        ):
            lines.append(f"{header}:")
            for name in names:
                lines.append(f"  {name:<{width + 2}}{help_by_name.get(name, '')}")
            lines.append("")
        return "\n".join(lines)

    def _format_action(self, action: argparse.Action) -> str:
        if isinstance(action, argparse._SubParsersAction):
            return self._format_subparsers(action)
        return super()._format_action(action)

    def format_help(self) -> str:
        text = super().format_help()
        return text.replace("positional arguments:\n", "")


def build_parser() -> argparse.ArgumentParser:
    parser = _ComicMetaArgumentParser(
        prog="comicmeta",
        description=__doc__,
        formatter_class=_PipelineHelpFormatter,
        epilog=f"Run in order: {PIPELINE_CHAIN}\n\nReport issues: {ISSUES_URL}",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {comicmeta.__version__}")
    parser.add_argument("--context", "-c", help="run against a named context (default: active context)")
    parser.add_argument("--debug", action="store_true", help="show full traceback on unexpected errors")
    parser.add_argument("--no-input", action="store_true", help="never prompt; fail if a prompt would be required")
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")
    _commands.register(subparsers)
    return parser


def _subparsers(parser: argparse.ArgumentParser) -> argparse._SubParsersAction:
    return parser._subparsers._group_actions[0]


def dashboard() -> int:
    """Static first-launch screen for non-interactive (piped) use."""
    from comicmeta._common import set_theme
    try:
        set_theme(_config.get(_config.load(None), "appearance.theme"))
    except Exception:
        pass
    colors = Palette(color_enabled())
    print(render_wordmark(colors))
    print()
    print(colors.title("comicmeta — review-then-write ComicVine metadata for your comic library"))
    print("(every step before `write` is read-only)")
    print()
    print("  PIPELINE")
    for name, description in PIPELINE:
        marker = "▸" if name.startswith("1 ") else " "
        print(f"    {marker} {name:<15} {description}")
    print()
    print("  NEXT")
    print("    comicmeta discover --source /path/to/comics --report candidates.json")
    print()
    print("  See `comicmeta <command> --help` for each step.")
    return 0


def _clear_screen() -> None:
    if sys.stdout.isatty():
        print("\033[2J\033[H", end="", flush=True)


def _display_width(text: str) -> int:
    """Visible width of a rendered line, ignoring ANSI SGR escape codes."""
    return len(_strip_ansi(text))


def _center(text: str, width: int) -> str:
    """Horizontally center a rendered line in `width` columns."""
    length = _display_width(text)
    if length >= width:
        return text
    pad = (width - length) // 2
    return " " * pad + text


def _menu_status_line() -> str | None:
    """One-line library snapshot shown above the pipeline, or None."""
    from comicmeta import _config
    from comicmeta._commands.flags import counts
    flat = _config.load(None)
    series, issues = counts(flat)
    parts = []
    mapping = Path(_config.get(flat, "paths.mapping"))
    if series or issues:
        parts.append(f"{issues} issues · {series} series")
    parts.append("mapping ready" if mapping.is_file() else "no mapping yet")
    return " · ".join(parts)


def _render_menu(colors: Palette, selected: int, conn=None, ctx=None) -> None:
    _clear_screen()
    width = shutil.get_terminal_size((100, 24)).columns
    center = lambda text: _center(text, width)
    rows = []
    for w in render_wordmark(colors).splitlines():
        rows.append(center(w))
    rows.append("")
    rows.append(center(colors.title("comicmeta — review-then-write ComicVine metadata")))
    rows.append(center(colors.muted("(every step before `write` is read-only)")))
    rows.append("")
    status = _menu_status_line()
    selected_command = DASHBOARD_STEPS[selected][0]
    local_target = (
        _DASHBOARD_CONTEXT is None
        and _local_source_is_available(argparse.Namespace(command=selected_command, source=None))
    )
    effective_ctx = _target_context()
    light = colors.good("● local") if local_target or effective_ctx.get("name") == _context.LOCAL_CONTEXT_NAME else _connection_light(colors, conn, effective_ctx)
    parts = [p for p in (light, status) if p]
    if parts:
        rows.append(center(colors.muted("  ".join(parts))))
    rows.append("")
    rows.append(center(colors.bold("PIPELINE")))
    block = []
    for index, (name, lines) in enumerate(DASHBOARD_STEPS):
        marker = "▸" if index == selected else " "
        if index == selected:
            block.append(f"  {marker} {colors.bold(colors.title(name))}")
            block.extend(f"      {line}" for line in lines)
        else:
            block.append(f"  {marker} {colors.bold(name)}")
            block.extend(f"      {colors.muted(line)}" for line in lines)
        block.append("")
    block_width = max((_display_width(line) for line in block), default=0)
    pad_step = max(0, (width - block_width) // 2)
    rows.extend((" " * pad_step + line) for line in block)
    hint = "[↑/↓] move · [1-6] jump · [Enter] run · [c] context · [s] settings · [h] help · [q] quit"
    rows.append(center(colors.muted(hint)))
    target_name = "local" if local_target else effective_ctx.get("name")
    rows.append(center(colors.muted(f"  target: {target_name}  ")))
    action = {
        "review": "[Enter] run review · [f] fresh review",
        "write": "[Enter] write metadata (with backups)",
        "convert": "[Enter] convert .cbr → .cbz",
        "browse": "[Enter] browse library tree",
        "organize": "[Enter] audit organization (dry-run)",
        "health": "[Enter] run health check",
    }.get(DASHBOARD_STEPS[selected][0])
    if action:
        rows.append(center(colors.bold(action)))
    # Fit every rendered line to the terminal width so nothing wraps on narrow
    # terminals (wordmark, long descriptions, and the hint all truncate).
    width = shutil.get_terminal_size((100, 24)).columns
    rows = [_truncate_ansi(row, width) for row in rows]
    print("\n".join(rows))


def _value_display(flat: dict, key: str) -> tuple[str, bool]:
    """Return (display string, is_secret_value). Secrets mask when set."""
    kind = _config.SETTINGS_META.get(key, ("", "str"))[1]
    value = flat.get(key)
    if kind == "bool":
        return "yes" if value else "no", False
    if kind == "dict":
        if not value:
            return "none", False
        if isinstance(value, dict):
            return f"{len(value)} blocked", False
        return str(value), False
    if value in (None, ""):
        return "(not set)", False
    if kind == "secret-path":
        return "••••••••", True
    return str(value), False


def _context_value_display(row: dict) -> str:
    """Display value for a context-setting row."""
    value = row["context"].get(row["context_field"])
    if value in (None, ""):
        return "(not set)"
    if row.get("kind") == "int":
        return str(value)
    return str(value)


def _selected_description(rows: list, selected: int) -> str | None:
    """Description for the currently selected setting/context row, or None."""
    if not (0 <= selected < len(rows)):
        return None
    row = rows[selected]
    if row["type"] == "setting":
        return _config.SETTINGS_DESCRIPTIONS.get(row["key"])
    if row["type"] == "context-add":
        return "Add a NAS context so comicmeta commands run on a remote library over SSH."
    if row["type"] == "context-summary":
        return "Open this connection to edit its host, library path, and execution settings."
    if row["type"] == "advanced-toggle":
        return "Open API, paths, review, and write-safety settings."
    if row["type"] == "context-setting":
        field = row.get("context_field")
        # Single source of truth: descriptions live in _context.CONTEXT_FIELDS,
        # not re-spelled here (avoids Shotgun Surgery when a field is added).
        for fname, _label, _kind, desc in _context.CONTEXT_FIELDS:
            if fname == field:
                return desc
    return None


def _settings_viewport(body: list, selected: int, terminal_rows: int) -> list:
    """Keep the selected setting visible on short terminals."""
    limit = max(5, terminal_rows - 10)
    if len(body) <= limit:
        return body
    start = max(0, min(selected - limit // 2, len(body) - limit))
    end = start + limit
    visible = body[start:end]
    if start:
        visible[0] = ("row", "  ↑ more settings")
    if end < len(body):
        visible[-1] = ("row", "  ↓ more settings")
    return visible


def _render_settings_menu(colors: Palette, rows: list, selected: int, settings_path, show_advanced: bool = False, search: str = "") -> None:
    """Render settings as an opencode-command-palette-style panel.

    Title at top-left, a search field, right-aligned values, a full-width
    reverse-video highlight bar on the selected row, and a description line
    for the selected setting.
    """
    _clear_screen()
    value_width = 34  # column where the right-aligned value begins
    label_rows: list[tuple[str, str, bool]] = []  # (label, value, is_selected)
    header_rows: list[str] = []  # section titles, drawn between label rows
    rendered: list[str] = []
    for index, row in enumerate(rows):
        if row["type"] == "header":
            rendered.append(("header", colors.muted(colors.bold(row["title"]))))
            continue
        if row["type"] == "context-header":
            rendered.append(("header", colors.muted(colors.bold(row["title"]))))
            continue
        if row["type"] == "context-summary":
            context = row["context"]
            value = f"{context.get('host') or 'not configured'} · {context.get('library_path') or 'no library path'}"
        elif row["type"] == "advanced-toggle":
            value = "API · paths · review · write"
        elif row["type"] == "action":
            value = "run"
        elif row["type"] == "context-setting":
            value = _context_value_display(row)
        elif row["type"] == "context-add":
            value = "add"
        else:
            value, secret = _value_display(row["flat"], row["key"])
            if secret and value != "(not set)":
                value = "••••••••"
        display_value = value if value not in (None, "") else "(not set)"
        label = row["label"]
        is_selected = index == selected
        rendered.append(("setting", label, display_value, is_selected))
    # Build inner lines: settings are right-aligned; headers are plain.
    body: list[str] = []
    selected_body_index = 0
    for item in rendered:
        if item[0] == "header":
            if body:
                body.append("")
            body.append(item[1])
            continue
        _, label, display_value, is_selected = item
        if is_selected:
            selected_body_index = len(body)
        if is_selected:
            key = colors.bold(colors.title(label))
            val = colors.title(display_value)
            cursor = colors.title("❯ ")
        else:
            key = label
            val = colors.muted(display_value)
            cursor = "  "
        padding = max(0, value_width - len(_strip_ansi(key)))
        line = f"{cursor}{key}{' ' * padding}  {val}"
        body.append(("sel", line) if is_selected else ("row", line))
    # Footer: file path, then blank, then hints.
    if settings_path:
        body.append(("row", ""))
        body.append(("row", colors.muted(f"file: {settings_path}")))
    else:
        body.append(("row", ""))
        body.append(("row", colors.muted("no settings file; using built-in defaults")))
    terminal_size = shutil.get_terminal_size((80, 24))
    visible_body = _settings_viewport(body, selected_body_index, terminal_size.lines)
    # Measure content width from the widest plain line.
    widths = []
    for item in visible_body:
        if isinstance(item, str):
            widths.append(len(_strip_ansi(item)))
        else:
            widths.append(len(_strip_ansi(item[1])))
    # Never build a panel wider than the terminal; content is truncated to fit.
    max_inner = max(12, terminal_size.columns - 2)
    inner_width = min(max(widths, default=40) + 4, max_inner)
    # Search line at the top.
    search_line = "❯ " + search + "▍"
    # Assemble the panel.
    lines = ["┌" + "─" * inner_width + "┐"]
    title_line = _truncate_ansi(colors.title(" comicmeta settings "), inner_width)
    lines.append("│" + title_line + " " * max(0, inner_width - len(_strip_ansi(title_line))) + "│")
    lines.append("│" + " " * inner_width + "│")
    lines.append("│ " + _truncate_ansi(search_line, inner_width - 1) + " " * max(0, inner_width - len(_strip_ansi(search_line)) - 1) + "│")
    lines.append("├" + "─" * inner_width + "┤")
    for item in visible_body:
        if isinstance(item, str):
            lines.append("│" + _truncate_ansi(item, inner_width) + " " * max(0, inner_width - len(_strip_ansi(item))) + "│")
            continue
        kind, text = item
        if kind == "header":
            lines.append("│" + _truncate_ansi(text, inner_width) + " " * max(0, inner_width - len(_strip_ansi(text))) + "│")
            continue
        if kind == "row":
            lines.append("│ " + _truncate_ansi(text, inner_width - 1) + " " * max(0, inner_width - len(_strip_ansi(text)) - 1) + "│")
        else:  # selected: full-width reverse-video bar
            fitted = _truncate_ansi(text, inner_width - 1)
            padded = " " + fitted + " " * max(0, inner_width - len(_strip_ansi(fitted)) - 1)
            lines.append("│" + colors.reverse(padded) + "│")
    # Description line for the selected row, above the closing border.
    description = _selected_description(rows, selected)
    if description:
        lines.append("├" + "─" * inner_width + "┤")
        desc = colors.muted("  " + description)
        lines.append("│" + _truncate_ansi(desc, inner_width) + " " * max(0, inner_width - len(_strip_ansi(desc))) + "│")
    lines.append("└" + "─" * inner_width + "┘")
    lines.append("")
    # Center the whole panel horizontally on the terminal.
    terminal_width = terminal_size.columns
    pad_left = max(0, (terminal_width - (inner_width + 2)) // 2)
    advanced_hint = "  [a] hide advanced" if show_advanced else "  [a] advanced"
    search_hint = "  type to search · ⌫ clear"
    hint = colors.muted(f"{search_hint} · {advanced_hint} · [↑/↓] move · [Enter] open/edit · [q] back")
    lines.append(_truncate_ansi(hint, terminal_width - pad_left))
    if pad_left:
        lines = [" " * pad_left + line for line in lines]
    print("\n".join(lines))


def _build_rows(flat: dict, show_advanced: bool = False, expanded_contexts: set[str] | None = None) -> list:
    if not show_advanced:
        rows = [{"type": "header", "title": "APPEARANCE"}]
        for key in _config.DEFAULTS["appearance"]:
            full = f"appearance.{key}"
            if full in _config.ADVANCED_KEYS:
                continue
            label, _ = _config.SETTINGS_META.get(full, (key.replace("_", " "), "str"))
            rows.append({"type": "setting", "key": full, "label": label, "flat": flat})
        rows.append({"type": "header", "title": "CONNECTIONS"})
        from comicmeta import _context
        contexts = _context.list_contexts()
        active_name = _context.active_context().name
        expanded_contexts = expanded_contexts or set()
        for ctx in contexts:
            name = ctx.name
            marker = "❯" if name == active_name else "·"
            rows.append({
                "type": "context-summary", "key": f"{name}.context", "label": f"{marker} {name}",
                "context": ctx, "flat": flat,
            })
            if name in expanded_contexts:
                rows.append({"type": "context-header", "title": f"{name} details", "context": ctx, "flat": flat})
                for field, label, kind, _desc in _context.CONTEXT_FIELDS:
                    rows.append({
                        "type": "context-setting", "key": f"{name}.{field}", "label": label,
                        "kind": kind, "context": ctx, "context_field": field, "flat": flat,
                    })
        rows.append({"type": "context-add", "key": "context.add", "label": "＋ Add connection…", "flat": flat})
        rows.append({"type": "header", "title": "STORAGE"})
        rows.append({"type": "setting", "key": "paths.backup_dir", "label": "Backup location", "flat": flat})
        rows.append({"type": "action", "key": "storage.purge", "label": "Purge backups…", "flat": flat})
        rows.append({"type": "header", "title": "ADVANCED"})
        rows.append({"type": "advanced-toggle", "key": "settings.advanced", "label": "Show advanced settings…", "flat": flat})
        return rows
    rows = []
    for section in _config.SECTION_ORDER:
        section_rows = []
        for key in _config.DEFAULTS[section]:
            full = f"{section}.{key}"
            if not show_advanced and full in _config.ADVANCED_KEYS:
                continue
            label, _ = _config.SETTINGS_META.get(full, (key.replace("_", " "), "str"))
            section_rows.append({"type": "setting", "key": full, "label": label, "flat": flat})
        if section_rows:
            rows.append({"type": "header", "title": _config.SECTION_TITLES[section]})
            rows.extend(section_rows)
    # NAS contexts section: existing contexts' editable fields, then an add action.
    from comicmeta import _context
    contexts = _context.list_contexts()
    rows.append({"type": "header", "title": "NAS CONTEXTS"})
    active_name = _context.active_context().name
    for ctx in contexts:
        name = ctx.name
        marker = "❯" if name == active_name else "·"
        rows.append({"type": "context-header", "title": f"{marker} {name}", "context": ctx, "flat": flat})
        for field, label, kind, _desc in _context.CONTEXT_FIELDS:
            rows.append({
                "type": "context-setting",
                "key": f"{name}.{field}",
                "label": label,
                "kind": kind,
                "context": ctx,
                "context_field": field,
                "flat": flat,
            })
    rows.append({
        "type": "context-add",
        "key": "context.add",
        "label": "＋ Add NAS context…",
        "flat": flat,
    })
    rows.append({"type": "header", "title": "STORAGE"})
    rows.append({"type": "action", "key": "storage.purge", "label": "Purge backups…", "flat": flat})
    return rows


def _edit_value(colors: Palette, row: dict) -> bool:
    """Edit one setting. Returns True if changed and saved."""
    from comicmeta._commands import settings as settings_cmd
    from comicmeta._tui import prompt_edit
    key = row["key"]
    kind = _config.SETTINGS_META.get(key, ("", "str"))[1]
    flat = row["flat"]
    current = flat.get(key)

    if kind == "bool":
        new = not bool(current)
        if key == "appearance.cover_previews" and new and not _configure_cover_previews(colors, prompt=False):
            return False
        settings_cmd.set_key_silent(key, new)
        if key == "appearance.cover_previews":
            settings_cmd.set_key_silent("appearance.cover_previews_configured", True)
        return True

    if kind == "dict":
        return _edit_blocked(colors, key, current)

    if kind == "secret-path":
        print(colors.muted("  Enter the API key (input is hidden):"))
        value = prompt_edit("  API key: ", secret=True)
        if value is None or not value.strip():
            print(colors.warn("  No API key entered; unchanged."))
            return False
        # Persist the key to the configured key file, not the toml.
        target = Path(_config.get(flat, "api.key_file")) if _config.get(flat, "api.key_file") else Path.cwd() / "comicvine.key"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(value.strip() + "\n", encoding="utf-8")
        try:
            target.chmod(0o600)
        except OSError:
            pass
        settings_cmd.set_key_silent("api.key_file", str(target))
        ok, message = verify_api_key(
            value.strip(),
            timeout=_config.as_int(_config.get(flat, "api.timeout"), 30),
            user_agent=_config.get(flat, "api.user_agent"),
        )
        if ok:
            print(colors.good(f"  ✓ API key verified — {message}"))
            print(colors.muted(f"  API key saved to {target}"))
        else:
            print(colors.warn(f"  ✗ API key failed verification: {message}"))
            print(colors.muted(f"  Saved anyway to {target} (you can fix it later)."))
        return True

    if key == "appearance.theme":
        return _pick_theme(colors, current)

    prompt = f"  {row['label']}: "
    value = prompt_edit(prompt, current=str(current) if current not in (None, "") else "")
    if value is None:
        print()
        return False
    settings_cmd.set_key_silent(key, value)
    return True


def _pick_theme(colors: Palette, current) -> bool:
    """Cycle through built-in themes with a live-preview side-by-side swatch."""
    from comicmeta._common import THEMES
    from comicmeta._commands import settings as settings_cmd
    from comicmeta._tui import read_key

    names = list(THEMES)
    index = names.index(str(current)) if str(current or "classic") in names else 0
    while True:
        _clear_screen()
        heading = colors.title("▸ COLOR THEME")
        print(heading)
        print(colors.muted("  Comic-flavored palettes. ←/→ to preview, Enter to apply, q to cancel."))
        print()
        for number, name in enumerate(names):
            palette = Palette(True, theme=name)
            marker = "❯" if number == index else " "
            label = f" {marker} {name:<12}"
            swatch_parts = [
                palette.title("Title"),
                palette.good("Good"),
                palette.warn("Warn"),
                palette.path("Path"),
                palette.muted("Muted"),
            ]
            print(f"    {label}  {''.join(swatch_parts)}")
        print()
        print(colors.muted("  [↑/↓/←/→] move · [Enter] apply · [q] back"))
        key = read_key()
        if key in {"up", "left"}:
            index = (index - 1) % len(names)
            continue
        if key in {"down", "right"}:
            index = (index + 1) % len(names)
            continue
        if key in {"enter", "\r"}:
            settings_cmd.set_key_silent("appearance.theme", names[index])
            return True
        if key in {"q", "ctrl-c", "ctrl-d", "b"}:
            return False


def _edit_blocked(colors: Palette, key: str, current) -> bool:
    """Add/remove blocked queries."""
    from comicmeta._commands import settings as settings_cmd
    from comicmeta._tui import read_key
    blocked = dict(current) if isinstance(current, dict) else {}
    while True:
        _clear_screen()
        print(colors.title("▸ BLOCKED QUERIES"))
        print(colors.muted("  Queries excluded from selection during review"))
        print()
        if not blocked:
            print(colors.muted("  (none)"))
        for index, (query, reason) in enumerate(sorted(blocked.items()), 1):
            print(f"  {index}. {colors.bold(query)}")
            print(f"      {colors.muted(reason)}")
        print()
        print(colors.muted("  [a] add · [d] delete · [b] back · [q] quit"))
        choice = read_key()
        if choice in {"ctrl-c", "ctrl-d", "q"}:
            return False
        if choice == "b" or choice == "enter":
            settings_cmd.set_key_silent(key, blocked)
            return True
        if choice == "a":
            query = input("  Query (folder name): ").strip()
            if not query:
                continue
            reason = input("  Reason (optional): ").strip()
            blocked[query] = reason or "blocked by user"
            continue
        if choice == "d":
            index = input("  Number to delete: ").strip()
            if index.isdigit():
                names = sorted(blocked)
                if 1 <= int(index) <= len(names):
                    blocked.pop(names[int(index) - 1], None)
            continue
    return False


def _edit_context_value(colors: Palette, row: dict) -> bool:
    """Edit one context field. Returns True if changed and saved."""
    from comicmeta import _context
    from comicmeta._tui import prompt_edit
    ctx = dict(row["context"])
    field = row["context_field"]
    current = ctx.get(field, "")
    prompt = f"  {row['label']} [{current}]: " if current not in (None, "") else f"  {row['label']}: "
    value = prompt_edit(prompt, current=str(current) if current not in (None, "") else "")
    if value is None:
        print()
        return False
    value = value.strip()
    if row.get("kind") == "int":
        try:
            ctx[field] = int(value) if value else ctx.get(field)
        except ValueError:
            print(colors.warn("  Expected a number; unchanged."))
            return False
    else:
        ctx[field] = value
    _context.save_context(ctx)
    return True


def _filter_rows(rows: list, search: str) -> list:
    """Filter setting/context rows by search text; keep matching sections."""
    query = search.strip().casefold()
    if not query:
        return rows
    result: list = []
    for row in rows:
        if row["type"] in ("header", "context-header"):
            continue
        haystack = (row.get("label", "") + " " + row.get("key", "")).casefold()
        if query in haystack:
            result.append(row)
    if result:
        result.insert(0, {"type": "header", "title": "MATCHES"})
    return result


def _run_context_add(colors: Palette) -> None:
    """Launch the guided NAS context wizard from the settings panel.

    Leaves the alt screen (so the wizard renders in normal scrollback), runs the
    existing interactive `context add` flow, then re-enters the alt screen. The
    wizard already prompts for host/user/library/exec, tests the connection,
    and optionally syncs the source or builds the image.
    """
    from comicmeta._commands import context as context_cmd
    from comicmeta._tui import enter_alt_screen, leave_alt_screen
    _clear_screen()
    leave_alt_screen()
    _clear_screen()
    try:
        ns = argparse.Namespace(
            name=None, host=None, ssh_user=None, ssh_port=22,
            identity_file=None, connect_timeout=10, library_path=None,
            exec="rsync", image="comicmeta:latest", nas_src="~/comicmeta",
            config_dir="~/.config/comicmeta", key_location=None,
        )
        context_cmd._add(ns)
    except SystemExit:
        # Cancelled or connection failed — stay in the settings panel, don't
        # tear down the whole session. The wizard already printed the message.
        pass
    finally:
        enter_alt_screen()


def _run_purge_backups(colors: Palette) -> bool:
    """Purge this library's backups from the settings panel.

    Leaves the alt screen so the size preview and confirmation render in
    normal scrollback, then re-enters. Returns True if the backup directory
    existed and was removed, so the settings panel can mark itself dirty.
    """
    import argparse as _argparse
    from comicmeta import _config
    from comicmeta._commands import backups as backups_cmd
    from comicmeta._tui import enter_alt_screen, leave_alt_screen
    flat = _config.load(None)
    backup_dir = Path(_config.get(flat, "paths.backup_dir"))
    existed = backup_dir.is_dir()
    _clear_screen()
    leave_alt_screen()
    _clear_screen()
    try:
        ns = _argparse.Namespace(source=None, backup_dir=None, list=False, delete=False, purge=True)
        backups_cmd.run(ns)
    except SystemExit:
        pass
    finally:
        enter_alt_screen()
    return existed and not backup_dir.exists()


def _settings_screen(parser: argparse.ArgumentParser, colors: Palette) -> int:
    """Interactive settings menu: navigate, search, edit, init, or return."""
    from comicmeta import _config
    from comicmeta._commands import settings as settings_cmd
    from comicmeta._tui import read_key

    show_advanced = False
    expanded_contexts: set[str] = set()
    search = ""
    dirty = False  # a setting/context was edited during this visit
    selected_key = None

    def leave(changed: bool) -> int:
        """Return to the dashboard, confirming first when changes were made."""
        if changed and not confirm("  Settings were changed. Leave settings?", default=True):
            return None
        return 1

    while True:
        flat = settings_cmd.load_flat()
        from comicmeta._common import set_theme
        set_theme(_config.get(flat, "appearance.theme"))
        colors = Palette(color_enabled(), theme=_config.get(flat, "appearance.theme"))
        rows = _filter_rows(_build_rows(flat, show_advanced, expanded_contexts), search)
        selectable = [i for i, r in enumerate(rows) if r["type"] in ("setting", "context-summary", "context-setting", "context-add", "advanced-toggle", "action")]
        selected = next(
            (i for i in selectable if rows[i].get("key") == selected_key),
            selectable[0] if selectable else 0,
        )
        settings_path = _config.find_settings(None)

        def remember_selection() -> None:
            nonlocal selected_key
            if rows and 0 <= selected < len(rows):
                selected_key = rows[selected].get("key")

        while True:
            _render_settings_menu(colors, rows, selected, settings_path, show_advanced, search)
            key = read_key()
            if key in {"ctrl-c", "ctrl-d"}:
                return 0
            if key in {"q", "b"} or key == "enter" and rows and rows[selected]["type"] == "header":
                result = leave(dirty)
                if result is not None:
                    return result
                continue
            if key == "a":
                remember_selection()
                show_advanced = not show_advanced
                break
            if key in ("\x7f", "\b", "backspace"):
                search = search[:-1]
                remember_selection()
                break
            if key == "/":
                search = ""
                remember_selection()
                break
            if len(key) == 1 and key.isprintable():
                search += key
                remember_selection()
                break
            if key == "up":
                idx = selectable.index(selected) if selected in selectable else 0
                if idx > 0:
                    selected = selectable[idx - 1]
                continue
            if key == "down":
                idx = selectable.index(selected) if selected in selectable else -1
                if idx < len(selectable) - 1:
                    selected = selectable[idx + 1]
                continue
            if key == "enter":
                if rows and rows[selected]["type"] == "setting":
                    if _edit_value(colors, rows[selected]):
                        dirty = True
                    remember_selection()
                    break
                if rows and rows[selected]["type"] == "context-summary":
                    name = rows[selected]["context"].name
                    if name in expanded_contexts:
                        expanded_contexts.remove(name)
                    else:
                        expanded_contexts.add(name)
                    remember_selection()
                    break
                if rows and rows[selected]["type"] == "context-setting":
                    if _edit_context_value(colors, rows[selected]):
                        dirty = True
                    remember_selection()
                    break
                if rows and rows[selected]["type"] == "context-add":
                    _run_context_add(colors)
                    dirty = True
                    remember_selection()
                    break
                if rows and rows[selected]["type"] == "action":
                    if _run_purge_backups(colors):
                        dirty = True
                    remember_selection()
                    break
                if rows and rows[selected]["type"] == "advanced-toggle":
                    remember_selection()
                    show_advanced = True
                    break
                result = leave(dirty)
                if result is not None:
                    return result
                continue
    return 0


def _init_namespace():
    import argparse
    return argparse.Namespace(init=True, set=None, source=None, config=None)


def _cover_tool_installer() -> tuple[str, list[str]] | None:
    """Return (label, install command) for a cover-renderer, or None.

    Chooses the platform's package manager so the optional-install flow works
    on both macOS (brew → timg) and Debian/Ubuntu (apt → chafa).
    """
    if shutil.which("brew"):
        return "timg with Homebrew", ["brew", "install", "timg"]
    if shutil.which("apt-get"):
        return "chafa with apt", ["sudo", "apt-get", "install", "-y", "chafa"]
    return None


def _root_install_hint(cmd: list[str]) -> str:
    """User-facing command to install the renderer as root.

    apt needs a package update and drops the `sudo` prefix (the failure mode is
    usually a user without sudo rights); brew does not need root.
    """
    if cmd and cmd[0] == "sudo":
        return "apt-get update && " + " ".join(cmd[1:])
    return " ".join(cmd)


def _is_truenas() -> bool:
    """Best-effort TrueNAS detection: apt is disabled there, so root-install
    advice must not point at the host package manager."""
    try:
        return "truenas" in Path("/etc/version").read_text(encoding="utf-8", errors="ignore").casefold()
    except OSError:
        return False


def _detect_mounted_volumes() -> list[Path]:
    """Return currently-mounted volume mount points to offer as backup targets.

    macOS lists external/NAS mounts under /Volumes; Linux puts removable and
    network mounts under /media and /mnt. Only real directories are returned;
    the root filesystem and the user's home are excluded as non-volumes.
    """
    candidates: list[Path] = []
    for base in ("/Volumes", "/media", "/mnt", "/run/media"):
        root = Path(base)
        try:
            if not root.is_dir():
                continue
            for entry in sorted(root.iterdir()):
                if entry.is_dir():
                    candidates.append(entry)
        except OSError:
            continue
    home = Path.home().resolve()
    return [p for p in candidates if p.resolve() != home]


def _configure_cover_previews(colors: Palette, prompt: bool = True) -> bool:
    """Enable cover previews, offering to install a renderer if none exists.

    Pillow alone gives true-color covers (ANSI half-blocks), so previews work
    as soon as either an external color renderer (timg/chafa/terminal-image-cli)
    OR Pillow is available. The external tools only add higher quality; a failed
    optional install never disables previews when Pillow is present.
    """
    from comicmeta import _cover
    from comicmeta._commands import settings as settings_cmd
    target = _config.find_settings(None) or _config.user_settings_path()
    tools = ("timg", "image", "chafa")
    external_ok = any(shutil.which(tool) for tool in tools)
    pillow_ok = _cover.pillow_preview_available()
    enabled = external_ok or pillow_ok
    installer = _cover_tool_installer()
    if not external_ok:
        if installer is None:
            if not pillow_ok:
                print(colors.warn("  No cover renderer found (install timg, chafa, or terminal-image-cli). Cover previews will stay off."))
        else:
            note = " (Pillow true-color already works)" if pillow_ok else ""
            if confirm(f"  Install {installer[0]} for higher-quality covers?{note}", default=True):
                import subprocess
                result = subprocess.run(installer[1])
                external_ok = result.returncode == 0 and any(shutil.which(tool) for tool in tools)
                if not external_ok:
                    print(colors.warn(f"  {installer[0]} installation failed."))
                    if _is_truenas() and installer[1][:1] == ["sudo"]:
                        print(colors.muted("    TrueNAS disables apt on the host; Pillow previews already work."))
                        print(colors.muted("    For best quality, drop the timg static binary into ~/bin instead."))
                    else:
                        print(colors.muted("    For higher quality, run this with root privileges (e.g. the TrueNAS web shell or SSH as an admin):"))
                        print(colors.muted(f"      {_root_install_hint(installer[1])}"))
                    if not pillow_ok:
                        print(colors.muted("    No fallback renderer is available, so previews will stay off."))
        enabled = external_ok or pillow_ok
    if enabled and pillow_ok and not external_ok:
        print(colors.muted("  Cover previews are enabled (Pillow true-color)."))
        print(colors.muted("    No install needed — Pillow renders covers over SSH."))
        print(colors.muted("    For higher quality, install timg or chafa."))
    settings_cmd.set_key_silent("appearance.cover_previews", enabled, target=target)
    settings_cmd.set_key_silent("appearance.cover_previews_configured", True, target=target)
    return enabled


def _first_run_cover_setup(colors: Palette) -> None:
    flat = _config.load(None)
    if _config.get(flat, "appearance.cover_previews_configured") or not is_interactive():
        return
    # When the dashboard targets a NAS context, covers render on the NAS, so the
    # setup (and any tool install) must run there — not on this machine.
    if _DASHBOARD_CONTEXT not in (None, _context.LOCAL_CONTEXT_NAME):
        _run_subcommand(["setup"])
        return
    print(colors.title("comicmeta first-run setup"))
    print(colors.muted("  Cover previews are optional and only require software on this Mac."))
    _configure_cover_previews(colors)
    print()


def _first_run_backup_setup(colors: Palette) -> None:
    """Ask once where backups should live, on the first interactive launch."""
    from comicmeta._commands import settings as settings_cmd
    flat = _config.load(None)
    if _config.get(flat, "write.backup_configured") or not is_interactive():
        return
    if _DASHBOARD_CONTEXT not in (None, _context.LOCAL_CONTEXT_NAME):
        return  # NAS backups resolve on the NAS; configured there in settings
    _pick_backup_location(colors)
    settings_cmd.set_key_silent("write.backup_configured", "true")


def _pick_backup_location(colors: Palette) -> None:
    """Pick where backups should live: default, mounted volume, custom, or none.

    Offers the default state-dir location, any currently-mounted volumes (NAS
    or external drives), a custom path, or explicitly no backups. Records the
    choice into settings so it only runs once.
    """
    from comicmeta._commands import settings as settings_cmd
    flat = _config.load(None)
    default_dir = Path(_config.get(flat, "paths.backup_dir"))
    volumes = _detect_mounted_volumes()
    options: list[tuple[str, str, str | None]] = []  # (key, label, value)
    options.append(("default", f"Default location", str(default_dir)))
    for volume in volumes:
        target = volume / "comicmeta-backups"
        options.append((str(volume), f"{volume.name} (mounted volume)", str(target)))
    options.append(("custom", "Custom path…", None))
    options.append(("none", "No backups (risky)", None))
    if not volumes:
        # No volumes to choose from — keep the picker short.
        options = [
            ("default", "Default location", str(default_dir)),
            ("custom", "Custom path…", None),
            ("none", "No backups (risky)", None),
        ]

    selected = 0
    while True:
        _clear_screen()
        print(colors.title("▸ BACKUP LOCATION"))
        print(colors.muted("  Where should comicmeta keep the original archives it backs up"))
        print(colors.muted("  before writing metadata? A bad write never destroys an original."))
        print()
        for index, (key, label, value) in enumerate(options):
            marker = "❯" if index == selected else " "
            line = f"  {marker} {label}"
            if key == "none":
                line += colors.warn("  ⚠ no safety copy")
            elif value:
                line += f"  {colors.muted(value)}"
            if index == selected:
                print(colors.bold(line))
            else:
                print(line)
        print()
        print(colors.muted("  [↑/↓] move · [Enter] choose · [q] skip (use default)"))
        key = read_key()
        if key in {"q", "ctrl-c", "ctrl-d"}:
            break
        if key == "up":
            selected = max(0, selected - 1)
            continue
        if key == "down":
            selected = min(len(options) - 1, selected + 1)
            continue
        if key != "enter":
            continue
        kind, label, value = options[selected]
        target = settings_cmd.settings_target()
        if kind == "default":
            pass  # keep the resolved default location
        elif kind == "custom":
            from comicmeta._tui import prompt_edit
            print()
            value = prompt_edit("  Backup path: ", current=str(default_dir))
            if not value or not value.strip():
                print(colors.muted("  Cancelled; keeping default location."))
                break
            settings_cmd.set_key_silent("paths.backup_dir", value.strip(), target=target)
        elif kind == "none":
            print()
            print(colors.warn("  No backups: `write` will touch archives with no safety copy."))
            print(colors.warn("  Converting a .cbr moves the original into the backup directory —"))
            print(colors.warn("  without one, errors can leave you with no recoverable original."))
            if confirm("  Disable backups anyway?", default=False):
                settings_cmd.set_key_silent("write.keep_backups", "false", target=target)
        else:
            # A mounted volume: back up next to the library on the NAS/external drive.
            settings_cmd.set_key_silent("paths.backup_dir", str(Path(value)), target=target)
        break


def _review_held_count() -> int:
    """Volumes still held for later (skipped/flagged) in the current review.

    0 means the volume review is fully complete, so the dashboard skips the
    fresh/reopen prompt and just shows the plain footer.
    """
    import json
    flat = _config.load(None)
    state_path = Path(_config.get(flat, "paths.volume_state"))
    if not state_path.is_file():
        return 0
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return 0
    return sum(
        1 for selection in state.get("selections", {}).values()
        if selection.get("status") in {"skipped", "flagged"}
    )


def interactive_dashboard(parser: argparse.ArgumentParser, initial_context: str | None = None) -> int:
    global _DASHBOARD_CONTEXT
    _DASHBOARD_CONTEXT = initial_context
    colors = Palette(color_enabled())
    selected = 0
    update_hint = ""
    _first_run_cover_setup(colors)
    _first_run_backup_setup(colors)
    try:
        if _config.get(_config.load(None), "appearance.check_for_updates"):
            from comicmeta._commands.update_check import latest_version
            latest = latest_version()
            if latest and latest != comicmeta.__version__:
                update_hint = f"  Update available: {comicmeta.__version__} → {latest} (brew upgrade comicmeta)"
    except Exception:
        update_hint = ""
    from comicmeta._tui import enter_alt_screen, leave_alt_screen
    enter_alt_screen()
    try:
        while True:
            ctx = _target_context()
            conn = _connection_state(ctx)
            _render_menu(colors, selected, conn, ctx)
            if update_hint:
                print(colors.warn(update_hint))
            key = read_key()
            if key in {"ctrl-c", "ctrl-d", "q"}:
                return 0
            if key == "c":
                _cycle_target_context()
                continue
            if key == "up":
                selected = (selected - 1) % len(DASHBOARD_STEPS)
                continue
            if key == "down":
                selected = (selected + 1) % len(DASHBOARD_STEPS)
                continue
            if key == "s":
                if _settings_screen(parser, colors) == 0:
                    return 0
                continue
            if key == "h":
                print(parser.format_help())
                print()
                print(colors.muted("  [any key] back to the dashboard"))
                read_key()
                continue
            if key == "enter":
                name = DASHBOARD_STEPS[selected][0]
                ack_n = 0  # dashboard ack lines printed since the last subcommand

                def ack(line: str = "") -> None:
                    nonlocal ack_n
                    ack_n += 1
                    print(line)

                if name == "convert":
                    code = _run_subcommand(["convert"])
                    ack_n = 0
                    if code == 0:
                        flush_input()
                        ack()
                        ack(colors.bold("  [e] execute these conversions · any other key keeps dry-run only"))
                        if read_key() in {"e", "E"}:
                            _run_subcommand(["convert", "--execute"])
                            ack_n = 0
                elif name == "review":
                    # Run the (resumable) review first so the user sees the current
                    # library + review. Only offer fresh/reopen when the review
                    # still has held (skipped/flagged) volumes that need attention;
                    # a fully complete review falls through to the plain footer.
                    _run_subcommand(["review"])
                    ack_n = 0
                    held = _review_held_count()
                    if held:
                        flush_input()
                        ack()
                        ack(colors.warn(f"  [r] re-open review (fix {held} held volume{'s' if held != 1 else ''})"))
                        ack(colors.warn("  [f] fresh review (discard + re-review everything)"))
                        ack(colors.muted("  any other key returns to the dashboard"))
                        reopen = read_key()
                        if reopen in {"r", "R"}:
                            _run_subcommand(["review", "--reopen"])
                            ack_n = 0
                        elif reopen in {"f", "F"}:
                            _run_subcommand(["review", "--fresh"])
                            ack_n = 0
                elif name == "organize":
                    code = _run_subcommand(["organize"])
                    ack_n = 0
                    if code == 0:
                        flush_input()
                        ack()
                        ack(colors.bold("  [e] apply these organization changes · any other key keeps dry-run only"))
                        if read_key() in {"e", "E"}:
                            _run_subcommand(["organize", "--execute"])
                            ack_n = 0
                else:
                    _run_subcommand([name])
                    ack_n = 0
                # Keep the step's output visible before the menu redraws.
                flush_input()
                ack()
                ack(colors.muted("  [Enter] or [q] back to dashboard · [Ctrl+D] quit"))
                if read_key() in {"ctrl-c", "ctrl-d"}:
                    from comicmeta._tui import erase_lines
                    erase_lines(ack_n)  # dismiss the dashboard ack block, keep step output
                    return 0
                enter_alt_screen()
                continue
            if key in {str(n) for n in range(1, len(DASHBOARD_STEPS) + 1)}:
                selected = int(key) - 1
                continue
    finally:
        leave_alt_screen()
    return 0


def _run_subcommand(argv: list[str]) -> int:
    """Run a comicmeta subcommand from inside the dashboard.

    `main()` raises SystemExit when the NAS executor dispatches (and on
    `die()`), which would otherwise tear down the whole dashboard. Leave the
    alt screen while the command runs so its output remains visible until the
    user acknowledges it; the dashboard re-enters the alt screen afterward.

    The dashboard may target a context other than the active one (via the
    `c` toggle), which is passed through as `--context NAME`.
    """
    from comicmeta._tui import leave_alt_screen
    palette = Palette(color_enabled())
    # Remember the real command for error reporting before we prepend --context.
    command = next((a for a in argv if not a.startswith("-")), "")
    if _DASHBOARD_CONTEXT is not None:
        argv = ["--context", _DASHBOARD_CONTEXT, *argv]
    # Wipe the dashboard (alt buffer) and then the stale main buffer before
    # running the step, so old shell history never leaks into step output.
    _clear_screen()
    leave_alt_screen()
    _clear_screen()
    code = 0
    try:
        main(argv)
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
    if code != 0:
        print()
        print(palette.warn(f"  ⚠ `{command or 'step'}` finished with errors (exit {code})."))
        print(palette.muted("    Check the output above; the dashboard menu will not have been updated."))
    return code


_CONNECTION_TTL = 30.0  # seconds between NAS connectivity probes on the dashboard
_connection_cache: dict[str, object] = {"at": 0.0, "state": None}

_DASHBOARD_CONTEXT: str | None = None  # dashboard target override (None = active context)


def _target_context() -> object:
    """Return the dashboard's selected context (override or active)."""
    if _DASHBOARD_CONTEXT is not None:
        return _context.load_context(_DASHBOARD_CONTEXT) or _context.active_context()
    return _context.active_context()


def _cycle_target_context() -> None:
    """Select local first, then cycle through saved contexts."""
    global _DASHBOARD_CONTEXT
    names = [_context.LOCAL_CONTEXT_NAME] + [c.name for c in _context.list_contexts()]
    if _DASHBOARD_CONTEXT is None:
        active = _context.active_context().name
        _DASHBOARD_CONTEXT = (
            _context.LOCAL_CONTEXT_NAME
            if active != _context.LOCAL_CONTEXT_NAME
            else names[1] if len(names) > 1 else _context.LOCAL_CONTEXT_NAME
        )
        _connection_cache["at"] = 0.0
        return
    current = _DASHBOARD_CONTEXT
    try:
        index = names.index(current)
    except ValueError:
        index = names.index(_context.LOCAL_CONTEXT_NAME) if names else -1
    index = (index + 1) % len(names) if names else 0
    _DASHBOARD_CONTEXT = names[index]
    _connection_cache["at"] = 0.0


def _connection_state(ctx) -> tuple[bool, str] | None:
    """Probe the active context's connectivity for the dashboard indicator.

    Returns (connected, note) for a NAS context, or None for the local
    context. Uses a short timeout so the dashboard never hangs on an
    unreachable host. The result is cached for a few seconds so navigating
    the dashboard doesn't re-probe SSH on every keypress.
    """
    if ctx is None or ctx.get("name") == _context.LOCAL_CONTEXT_NAME:
        _connection_cache["state"] = None
        return None
    if time.monotonic() - _connection_cache["at"] < _CONNECTION_TTL:
        return _connection_cache["state"]
    try:
        ok, message = _context.test_connection(ctx, timeout=4)
        state = ok, message
    except Exception:
        state = False, "probe failed"
    _connection_cache["at"] = time.monotonic()
    _connection_cache["state"] = state
    return state


def _connection_light(colors: Palette, state, ctx: dict | None = None) -> str:
    """Render the dashboard connection indicator: ● green = up, ○ dim = down."""
    if state is None:
        return ""
    ok, note = state
    dot = colors.good("●") if ok else colors.muted("○")
    name = (ctx or _context.active_context()).get("name")
    return f"{dot} {name}" if ok else f"{dot} {name} unavailable · press [c] for local"


def _configure_stream_errors() -> None:
    """Make prints survive filenames with undecodable bytes (SMB/NAS)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> None:
    _configure_stream_errors()
    parser = build_parser()
    argv = sys.argv[1:] if argv is None else argv
    from comicmeta._common import set_theme
    try:
        set_theme(_config.get(_config.load(None), "appearance.theme"))
    except Exception:
        pass
    if not argv:
        if is_interactive():
            raise SystemExit(interactive_dashboard(parser))
        raise SystemExit(dashboard())
    args = parser.parse_args(argv)
    from comicmeta._tui import set_no_input
    set_no_input(bool(getattr(args, "no_input", False)))
    # Resolve active context
    ctx_name = getattr(args, "context", None)
    if ctx_name:
        ctx = _context.load_context(ctx_name)
        if ctx is None:
            from comicmeta._common import die
            die(f"context not found: {ctx_name}")
    elif _local_source_is_available(args):
        ctx = _context.load_context(_context.LOCAL_CONTEXT_NAME)
    else:
        ctx = _context.active_context()
    # A bare invocation (`comicmeta -c LAN`) opens the dashboard here on this
    # machine, targeting the chosen context; each step then runs over SSH from
    # the dashboard. Don't dispatch the TUI itself to the NAS.
    if getattr(args, "handler", None) is None:
        if ctx_name:
            _DASHBOARD_CONTEXT = ctx_name
        raise SystemExit(interactive_dashboard(parser, ctx_name) if is_interactive() else dashboard())
    # Dispatch to NAS executor when a NAS context is active
    if (
        ctx.get("name") != _context.LOCAL_CONTEXT_NAME
        and getattr(args, "command", None) not in {"context"}
    ):
        from comicmeta._executors import get_executor
        executor = get_executor(ctx)
        sync_source = getattr(executor, "sync_source", None)
        if sync_source is not None:
            print(f"Syncing comicmeta source to context {ctx.get('name')}…", file=sys.stderr)
            synced, message = sync_source()
            if not synced:
                print(f"ERROR: could not sync comicmeta source: {message}", file=sys.stderr)
                raise SystemExit(1)
        remote_argv = _strip_context_flag(argv)
        # Determine if the command needs an interactive TTY
        interactive_commands = {
            "review", "review-volumes", "review-issues", "browse", "inspect",
            "write", "convert", "setup",
        }
        command_name = getattr(args, "command", "") or ""
        if command_name in interactive_commands and sys.stdin.isatty():
            raise SystemExit(executor.run_interactive(remote_argv))
        raise SystemExit(executor.run(remote_argv))
    try:
        args.handler(args)
    except KeyboardInterrupt:
        print()
        raise SystemExit(0)
    except Exception as error:
        _report_unexpected_error(error, bool(getattr(args, "debug", False)))
        raise SystemExit(1)


def _local_source_is_available(args: argparse.Namespace) -> bool:
    """Prefer a local comic source unless the user explicitly chose a context."""
    if getattr(args, "command", "") not in SOURCE_COMMANDS:
        return False
    source = getattr(args, "source", None)
    if source is not None:
        return Path(source).is_dir()
    # Ignore backup dirs when deciding "are we inside a library?": a cwd whose
    # only archives live under comicmeta-backups (e.g. an SSH home dir) is not
    # a library to operate on. `comicmeta-backups` is always excluded, even when
    # the configured backup_dir resolves to an absolute state-dir path.
    exclude = _config.scan_excludes(_config.load(None))
    exclude.add("comicmeta-backups")
    return bool(_archive.archives(Path.cwd(), exclude=exclude))


def _report_unexpected_error(error: Exception, debug: bool) -> None:
    """Human-friendly report for unexpected errors, with an opt-in traceback."""
    if debug:
        import traceback
        traceback.print_exc()
        return
    print(f"ERROR: unexpected error: {error}", file=sys.stderr)
    print(file=sys.stderr)
    print(
        "  This looks like a bug in comicmeta, not something you did wrong.",
        file=sys.stderr,
    )
    print(
        f"  Please report it with the command you ran:\n    {ISSUES_URL}",
        file=sys.stderr,
    )
    print(
        "  Re-run the command with `--debug` to include a full traceback.",
        file=sys.stderr,
    )


def _strip_context_flag(argv: list[str]) -> list[str]:
    """Remove --context NAME or -c NAME from argv so the remote does not re-parse it."""
    result: list[str] = []
    skip_next = False
    for arg in argv:
        if skip_next:
            skip_next = False
            continue
        if arg in ("--context", "-c"):
            skip_next = True
            continue
        result.append(arg)
    return result


if __name__ == "__main__":
    main(sys.argv[1:])
