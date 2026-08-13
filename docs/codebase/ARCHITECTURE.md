# Architecture

## Core Sections (Required)

### 1) Architectural Style

- Primary style: command-oriented layered CLI with shared utility modules and adapter-based remote execution.
- Why: `cli.py` owns parsing/dashboard dispatch, `_commands/` owns command behavior, `_config.py` owns settings/state resolution, and `_executors/` adapts NAS transport.
- Primary constraints: read-only review before write; CBZ-only mutation; library state must be isolated by resolved source path.

### 2) System Flow

```text
comicmeta.cli:main -> argparse command -> _config.load -> command module
    -> archive/API/context work -> report/state/output
```

1. `main` builds the parser and resolves the selected context.
2. Interactive no-command execution enters `interactive_dashboard`; direct commands use their registered handler.
3. Commands load defaults and settings through `_config.load`.
4. Archive commands use `_archive` for CBZ discovery and ComicInfo inspection.
5. Review commands call `_comicvine` and persist state; write commands consume reviewed mappings and backups.
6. NAS commands are translated by an `Executor` implementation and run over SSH/Docker/rsync.

### 3) Layer/Module Responsibilities

| Layer or module | Owns | Must not own | Evidence |
|-----------------|------|--------------|----------|
| CLI/dashboard | User navigation and dispatch | Archive mutation policy | `src/comicmeta/cli.py` |
| Command modules | Individual command behavior | Global parser bootstrap | `src/comicmeta/_commands/` |
| Shared core | Config, archive, API, palette, TUI helpers | Screen-specific command flows | `src/comicmeta/_config.py`, `_archive.py`, `_comicvine.py`, `_common.py` |
| Executor adapters | Remote argv/source translation and transport | Local metadata policy | `src/comicmeta/_executor.py`, `src/comicmeta/_executors/` |

### 4) Reused Patterns

| Pattern | Where found | Why it exists |
|---------|-------------|---------------|
| Command registration | `_commands/__init__.py` | Centralizes argparse subcommands |
| Abstract executor adapter | `_executor.py` and `_executors/` | Allows remote execution strategies |
| Flat dotted settings | `_config.py` | Gives CLI/config/environment values one lookup model |
| Per-library hashed state | `_config.py` | Prevents state collisions between libraries |
| Shared palette/TUI helpers | `_common.py`, `_tui.py` | Keeps terminal interaction consistent |

### 5) Known Architectural Risks

- `cli.py` coordinates parser, dashboard, settings, and interactive flows; its size and churn make changes easy to regress.
- Remote command correctness depends on consistent source/context translation between the CLI and executors.
- GitHub Actions now runs the test matrix on pushes and pull requests; local execution remains useful for fast feedback.

### 6) Evidence

- `src/comicmeta/cli.py`
- `src/comicmeta/_commands/__init__.py`
- `src/comicmeta/_config.py`
- `src/comicmeta/_executor.py`
- `.github/workflows/ci.yml`
