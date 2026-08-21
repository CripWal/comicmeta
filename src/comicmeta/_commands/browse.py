"""comicmeta browse — navigate the library as an interactive file tree.

Shows the library as an expandable tree of folders and comic archives. Use
arrow keys to move, Enter to expand a folder or open an issue card, and Left
to collapse. Selecting an archive opens a CLI metadata card (Kavita-style):
↑/↓ pages between sibling issues in the folder, ←/b returns to the tree, and
e edits the metadata.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from comicmeta import _archive, _config
from comicmeta._common import color_enabled, Palette, add_examples, die, die_missing_source, _truncate_ansi, _terminal_size
from comicmeta._tui import read_key


def add_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "browse",
        help="navigate the library as an interactive file tree",
        description=__doc__,
    )
    parser.add_argument("--source", "-s", type=Path, help="comic library root (default: current directory)")
    parser.add_argument("--backup-dir", type=Path, help="backup directory for metadata edits")
    parser.add_argument("--no-color", action="store_true", help="disable ANSI colors")
    add_examples(parser, [
        "comicmeta browse",
        "comicmeta browse -s /path/to/comics",
    ])
    parser.set_defaults(handler=run)


class Node:
    def __init__(self, name: str, path: Path, is_dir: bool) -> None:
        self.name = name
        self.path = path
        self.is_dir = is_dir
        self.children: list[Node] = []
        self.expanded = False
        self.has_comicinfo: bool | None = None
        self.flagged = False
        self.replacement = False
        self._comicinfo_checked = False

    def label(self) -> str:
        if self.is_dir:
            return f"{self.name}/"
        return self.name

    def comicinfo(self) -> bool | None:
        """Return whether this archive has ComicInfo.xml (cached after first call)."""
        if self._comicinfo_checked:
            return self.has_comicinfo
        self._comicinfo_checked = True
        if self.path.suffix.lower() != ".cbz":
            self.has_comicinfo = None
            return None
        from comicmeta import _archive
        self.has_comicinfo = _archive.cached_root_comicinfo(self.path)
        return self.has_comicinfo


def _flagged_series(source: Path) -> set[str]:
    """Folder-name (query) keys of flagged series from the volume review state."""
    from comicmeta import _config
    from comicmeta._common import color_enabled, load_json
    flat = _config.load(source)
    state_path = Path(_config.get(flat, "paths.volume_state"))
    flagged = set()
    if state_path.is_file():
        state = load_json(state_path, "volume state")
        for query, selection in state.get("selections", {}).items():
            if selection.get("status") == "flagged":
                flagged.add(query)
    return flagged


def _build_tree(source: Path, exclude: set[str]) -> Node:
    root = Node(source.name or str(source), source, True)
    flagged_series = _flagged_series(source)
    replacements = _replacement_requests(source)
    entries: dict[Path, Node] = {source: root}
    for path in sorted(source.rglob("*"), key=lambda p: (p.is_file(), str(p).casefold())):
        if exclude and any(part in exclude for part in path.relative_to(source).parts):
            continue
        if path.is_dir():
            node = Node(path.name, path, True)
            node.flagged = path.name in flagged_series
            entries[path] = node
            parent = entries.get(path.parent)
            if parent:
                parent.children.append(node)
        elif path.is_file() and path.suffix.lower() in _archive.ARCHIVE_SUFFIXES:
            node = Node(path.name, path, False)
            node.replacement = str(path.relative_to(source)) in replacements
            entries[path] = node
            parent = entries.get(path.parent)
            if parent:
                parent.children.append(node)
    return root


def _visible_nodes(root: Node) -> list[tuple[Node, int]]:
    """Return (node, depth) pairs for visible nodes, depth 0 = root."""
    out: list[tuple[Node, int]] = []
    stack: list[tuple[Node, int]] = [(root, 0)]
    while stack:
        node, depth = stack.pop()
        out.append((node, depth))
        if node.is_dir and (node is root or node.expanded):
            for child in reversed(node.children):
                stack.append((child, depth + 1))
    return out


def _render_tree(root: Node, selected: int, colors: Palette) -> None:
    nodes = _visible_nodes(root)
    if sys.stdout.isatty():
        print("\033[2J\033[H", end="")
    terminal_cols, terminal_rows = _terminal_size((80, 24))
    print(colors.title("▸ LIBRARY"))
    from comicmeta._commands.flags import status_line
    flags = status_line(colors, root.path)
    if flags:
        print(flags)
    print(_truncate_ansi(colors.muted(f"  {root.path}"), terminal_cols))
    print(_truncate_ansi(colors.muted("  ✓ ComicInfo · · missing · ? not CBZ · ✦ flagged · ↻ replace"), terminal_cols))
    print()
    limit = max(5, terminal_rows - 8)
    if len(nodes) <= limit:
        start, end = 0, len(nodes)
    else:
        start = max(0, min(selected - limit // 2, len(nodes) - limit))
        end = start + limit
    if start > 1:
        print(colors.muted(f"    … {start - 1} more"))
    for index, (node, depth) in enumerate(nodes[start:end], start):
        if node is root:
            continue
        marker = "▸" if index == selected else " "
        indent = "  " * depth
        if node.is_dir:
            fold = "▾" if node.expanded else "▸"
            flag = "✦ " if node.flagged else ""
            line = f"    {marker} {indent}{fold} {flag}{colors.bold(node.label())}"
        else:
            ci = node.comicinfo()
            mark = "✓" if ci else ("·" if ci is False else "?")
            flag = "✦ " if node.flagged else ""
            repl = "↻ " if node.replacement else ""
            line = f"    {marker} {indent}  {flag}{repl}{mark} {colors.path(node.label())}"
        if index == selected:
            print(colors.title(line) if node.is_dir else colors.bold(line))
        else:
            print(line)
    if end < len(nodes):
        print(colors.muted(f"    … {len(nodes) - end} more"))
    print()
    print(_truncate_ansi(colors.muted("  [↑/↓] move · [→/Enter] open · [←] collapse/up · [f] flag · [r] replace ComicInfo · [q] quit"), terminal_cols))
def _toggle_replacement(path: Path, source_root: Path) -> bool:
    """Toggle the ComicInfo-replacement request for one archive; return new state."""
    from comicmeta._commands import replacement
    relative = str(path.relative_to(source_root))
    return replacement.toggle(source_root, relative)


def _replacement_requests(source_root: Path) -> set[str]:
    from comicmeta._commands import replacement
    return replacement.requested_paths(source_root)


def _toggle_flag(path: Path, source_root: Path) -> bool:
    """Toggle a series or issue research flag; return the new state."""
    from comicmeta._common import atomic_json, load_json

    flat = _config.load(source_root)
    if path.is_dir():
        state_path = Path(_config.get(flat, "paths.volume_state"))
        state = load_json(state_path, "volume state") if state_path.is_file() else {"selections": {}}
        selections = state.setdefault("selections", {})
        key = path.name
    else:
        state_path = Path(_config.get(flat, "paths.issue_state"))
        state = load_json(state_path, "issue state") if state_path.is_file() else {"reviews": {}}
        selections = state.setdefault("reviews", {})
        key = str(path.relative_to(source_root))
    if selections.get(key, {}).get("status") == "flagged":
        del selections[key]
        flagged = False
    else:
        selections[key] = {"status": "flagged", "note": "flagged from browse"}
        flagged = True
    atomic_json(state_path, state)
    return flagged


def _browse(root: Node, source_root: Path, backup_dir: Path | None, colors: Palette) -> int:
    from comicmeta._tui import enter_alt_screen, leave_alt_screen
    enter_alt_screen()
    try:
        selected = 1  # start just below root
        while True:
            nodes = _visible_nodes(root)
            if selected >= len(nodes):
                selected = len(nodes) - 1
            if selected < 1:
                selected = 1
            selected = min(selected, len(nodes) - 1)
            if len(nodes) <= 1:
                _render_tree(root, selected, colors)
                print(colors.warn("  No comics or folders found in this library."))
                read_key()
                return 0
            _render_tree(root, selected, colors)
            key = read_key()
            if key in {"q", "ctrl-c", "ctrl-d"}:
                return 0
            node, _depth = nodes[selected]
            if key == "up":
                selected = max(1, selected - 1)
            elif key == "down":
                selected = min(len(nodes) - 1, selected + 1)
            elif key in {"right", "enter"}:
                if node.is_dir:
                    node.expanded = not node.expanded
                else:
                    _open_issue_card(node.path, source_root, backup_dir, colors)
            elif key == "left":
                if node.is_dir and node.expanded:
                    node.expanded = False
                else:
                    # jump to parent folder
                    parent_path = node.path.parent
                    for i, (candidate, _d) in enumerate(nodes):
                        if candidate.path == parent_path:
                            selected = i
                            break
            elif key == "f":
                node.flagged = _toggle_flag(node.path, source_root)
            elif key == "r":
                node.replacement = _toggle_replacement(node.path, source_root)
        return 0
    finally:
        leave_alt_screen()


def _sibling_archives(path: Path) -> list[Path]:
    """Archives in the same folder as `path`, sorted, including `path`."""
    return sorted(
        child for child in path.parent.iterdir()
        if child.is_file() and child.suffix.lower() in _archive.ARCHIVE_SUFFIXES
    )


def _render_issue_card(path: Path, index: int, siblings: list[Path], source_root: Path, colors: Palette) -> None:
    from comicmeta._humanize import pretty_bytes
    from comicmeta._commands.inspect import read_comicinfo

    if sys.stdout.isatty():
        print("\033[2J\033[H", end="")
    relative = path.relative_to(source_root)
    metadata = read_comicinfo(path) if path.suffix.lower() == ".cbz" else None
    term_cols, term_rows = _terminal_size((100, 24))
    width = min(100, term_cols)
    budget = max(6, term_rows - 8)
    lines: list[str] = []

    lines.append(colors.title("▸ COMIC"))
    lines.append(_truncate_ansi(colors.muted(f"  {relative.parent}"), width))
    lines.append(colors.muted(f"  {index + 1}/{len(siblings)}"))

    from comicmeta._commands.flags import flag_for
    series_note, issue_note = flag_for(path.resolve(), source_root)
    if series_note or issue_note:
        lines.append("")
        lines.append(colors.warn("  ✦ FLAGGED FOR RESEARCH"))
        if series_note:
            lines.append(colors.warn(f"      series: {series_note}"))
        if issue_note:
            lines.append(colors.warn(f"      issue:  {issue_note}"))
    from comicmeta._commands import replacement as replacement_cmd
    if replacement_cmd.is_requested(str(relative), source_root):
        lines.append("")
        lines.append(colors.warn("  ↻ MARKED FOR COMICINFO REPLACEMENT"))
        lines.append(colors.muted("      Will be re-reviewed against ComicVine and rewritten on `write`."))

    title = metadata.get("series") if metadata else path.stem
    subtitle = ""
    if metadata and metadata.get("number"):
        subtitle = f"Issue #{metadata['number']}"
        if metadata.get("title"):
            subtitle += f" — {metadata['title']}"
    lines.append("")
    lines.append(colors.bold(f"  {title}"))
    if subtitle:
        lines.append(f"  {subtitle}")

    cover = None
    try:
        if path.suffix.lower() == ".cbz" and path.is_file():
            from comicmeta import _cover
            cover = _cover.preview(path, source_root)
    except Exception:
        cover = None
    if cover and len(lines) + len(cover.splitlines()) + 2 <= budget:
        lines.append("")
        lines.extend(cover.splitlines())
        lines.append("")

    if metadata:
        date = "-".join(
            part for part in (
                str(metadata.get("year") or ""),
                str(metadata.get("month") or "").zfill(2) if metadata.get("month") else "",
                str(metadata.get("day") or "").zfill(2) if metadata.get("day") else "",
            ) if part
        ) or "—"
        volume = metadata.get("volume") or "—"
        fmt = metadata.get("format") or "—"
        lines.append("")
        lines.append(f"  {colors.bold('BASIC METADATA')}")
        for row in (
            ("Volume", volume),
            ("Issue", metadata.get("number") or "—"),
            ("Date", date),
            ("Format", fmt),
            ("Publisher", metadata.get("publisher") or "—"),
            ("SeriesGroup", metadata.get("series_group") or "—"),
            ("StoryArc", metadata.get("story_arc") or "—"),
        ):
            lines.append(f"    {row[0]:<14}{row[1]}")
        lines.append("")
        lines.append(f"  {colors.bold('FILE')}")
        lines.append(f"    Path              {colors.path(str(relative))}")
        lines.append(f"    Pages             {_page_count(path) or '—'}")
        lines.append(f"    Size              {pretty_bytes(path.stat().st_size)}")
        lines.append(f"    ComicInfo         {colors.good('present')}")
        summary = metadata.get("summary")
        if summary:
            lines.append("")
            lines.append(f"  {colors.bold('SUMMARY')}")
            import textwrap
            for wrapped in textwrap.wrap(summary, max(10, width - 4))[:6]:
                lines.append(f"    {wrapped}")
        web = metadata.get("web")
        if web:
            lines.append("")
            lines.append(colors.muted(web))
    else:
        lines.append("")
        lines.append(f"  {colors.warn('(no ComicInfo.xml present)')}")
        lines.append(f"    Path              {colors.path(str(relative))}")
        lines.append(f"    Pages             {_page_count(path) or '—'}")
        lines.append(f"    Size              {pretty_bytes(path.stat().st_size)}")

    footer = [""]
    footer.append(_truncate_ansi(colors.muted("  [↑/↓] prev/next issue · [←/b] back · [e] edit · [f] flag/unflag"), width))
    footer.append(_truncate_ansi(colors.muted("  [r] replace ComicInfo · [a] choose cover · [g] gallery · [q] back"), width))
    if len(lines) + len(footer) > term_rows:
        lines = lines[:term_rows - len(footer)]
    lines = [_truncate_ansi(line, width) for line in lines]
    print("\n".join(lines + footer))


def _page_count(path: Path) -> int | None:
    try:
        import zipfile
        with zipfile.ZipFile(path) as archive:
            return sum(
                1 for name in archive.namelist()
                if name.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".gif"))
            )
    except Exception:
        return None


def _edit_from_card(path: Path, source_root: Path, backup_dir: Path | None, colors: Palette) -> None:
    from comicmeta._commands.inspect import _prompt_edit, read_comicinfo, write_comicinfo
    if path.suffix.lower() != ".cbz":
        print(colors.warn("  Editing metadata is CBZ-only."))
        read_key()
        return
    metadata = read_comicinfo(path) or {}
    edited = _prompt_edit(metadata)
    if edited is None:
        return
    if backup_dir is None:
        flat = _config.load(source_root)
        backup_dir = Path(_config.get(flat, "paths.backup_dir"))
    relative = path.relative_to(source_root)
    backup = backup_dir / relative
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, backup)
    write_comicinfo(path, edited)
    print(f"  Edited metadata for {path} (backup: {backup})")
    read_key()


def _open_issue_card(selected_path: Path, source_root: Path, backup_dir: Path | None, colors: Palette) -> None:
    siblings = _sibling_archives(selected_path)
    if selected_path not in siblings:
        siblings = [selected_path] + siblings
    index = siblings.index(selected_path)
    while True:
        _render_issue_card(siblings[index], index, siblings, source_root, colors)
        key = read_key()
        if key in {"q", "ctrl-c", "ctrl-d"}:
            return
        if key in {"left", "b"}:
            return
        if key == "up":
            index = (index - 1) % len(siblings)
        elif key == "down":
            index = (index + 1) % len(siblings)
        elif key == "e":
            _edit_from_card(siblings[index], source_root, backup_dir, colors)
        elif key == "f":
            _toggle_flag(siblings[index], source_root)
        elif key == "r":
            _toggle_replacement(siblings[index], source_root)
        elif key == "a":
            _choose_cover(siblings[index], source_root, colors)
        elif key == "g":
            # The gallery must pause before the issue card redraws over it.
            from comicmeta._commands.covers import _gallery
            _gallery(siblings[index].parent, colors, source_root)
            print(colors.muted("  [Enter] return to comic"))
            read_key()


def _choose_cover(path: Path, source_root: Path, colors: Palette) -> None:
    """Choose which image member a specific issue displays as its cover."""
    from comicmeta import _cover
    if not _cover.previews_enabled(source_root):
        print(colors.muted("  Cover previews are disabled — enable `Cover previews` in settings."))
        read_key()
        return
    entries = _cover.cover_candidates(path)
    if len(entries) < 2:
        print(colors.muted("  No explicitly named alternate cover art was found in this CBZ."))
        read_key()
        return
    current = _cover.preferred_entry(path, source_root)
    index = next((i for i, (name, _data, _suffix) in enumerate(entries) if name == current), 0)
    while True:
        if sys.stdout.isatty():
            print("\033[2J\033[H", end="")
        print(colors.title("▸ SELECT COVER"))
        print(colors.muted(f"  {path.name} · {index + 1}/{len(entries)}"))
        print()
        name, data, suffix = entries[index]
        preview = _cover.preview_data(data, suffix)
        if preview:
            print(preview)
            print()
        for position, (entry, _entry_data, _entry_suffix) in enumerate(entries):
            marker = "▸" if position == index else " "
            chosen = "  (selected)" if entry == current else ""
            print(f"  {marker} {position + 1:>3}  {entry}{chosen}")
        print()
        print(colors.muted("  [↑/↓] choose · [Enter] use this cover · [←/q] cancel"))
        key = read_key()
        if key in {"left", "q", "ctrl-c", "ctrl-d"}:
            return
        if key == "up":
            index = (index - 1) % len(entries)
        elif key == "down":
            index = (index + 1) % len(entries)
        elif key == "enter":
            _cover.select_entry(path, source_root, entries[index][0])
            print(colors.good(f"  ✓ Cover set to {entries[index][0]}"))
            read_key()
            return


def run(args: argparse.Namespace) -> None:
    import os
    colors = Palette(color_enabled(args))
    flat = _config.load(getattr(args, "source", None))
    source = (args.source or Path(_config.get(flat, "paths.source"))).resolve()
    if not source.is_dir():
        die_missing_source(source)
    if not sys.stdin.isatty():
        die("browse needs an interactive terminal")
    backup_dir = args.backup_dir or Path(_config.get(flat, "paths.backup_dir"))
    root = _build_tree(source, _config.scan_excludes(flat))
    _browse(root, source, backup_dir, colors)
