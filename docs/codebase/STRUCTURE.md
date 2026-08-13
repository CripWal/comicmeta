# Codebase Structure

## Core Sections (Required)

### 1) Top-Level Map

| Path | Purpose | Evidence |
|------|---------|----------|
| `src/comicmeta/` | Application package and CLI implementation | `src/comicmeta/` |
| `src/comicmeta/_commands/` | Subcommand modules registered with argparse | `src/comicmeta/_commands/__init__.py` |
| `src/comicmeta/_executors/` | NAS execution implementations | `src/comicmeta/_executors/` |
| `tests/` | Automated unit/integration-style tests | `tests/` |
| `stress/` | Fuzz, chaos, and performance-oriented tests | `stress/` |
| `docs/wiki/` | User-facing wiki-ready pages | `docs/wiki/` |
| `docs/plans/`, `docs/design/` | Project design and planning documents | `docs/` |
| `tap/Formula/` | Homebrew formula | `tap/Formula/comicmeta.rb` |

### 2) Entry Points

- Main runtime entry: `src/comicmeta/cli.py:main`.
- Python module entry: `src/comicmeta/__main__.py`.
- Installed console entry: `comicmeta = comicmeta.cli:main` in `pyproject.toml`.
- Subcommands are registered by `src/comicmeta/_commands/__init__.py`.

### 3) Module Boundaries

| Boundary | What belongs here | What must not be here |
|----------|------------------|------------------------|
| `cli.py` | Parser, dashboard, interactive navigation, dispatch | Archive-format implementation details |
| `_commands/` | Command-specific parsing and execution | Cross-command CLI bootstrap |
| `_config.py` | Defaults, settings resolution, per-library state paths | Command-specific mutations |
| `_archive.py` | Archive discovery and ComicInfo handling | Dashboard rendering |
| `_executors/` | Remote command transport | Local review policy |
| `tests/` and `stress/` | Verification and failure reproduction | Production behavior |

### 4) Naming and Organization Rules

- Python modules use lowercase snake_case; internal helpers/modules use a leading underscore.
- Command modules are named after their CLI command, for example `health.py` and `organize.py`.
- The package uses a source layout under `src/`.
- No import alias convention or lint-enforced layout is configured. `[TODO]`

### 5) Evidence

- `pyproject.toml`
- `src/comicmeta/__main__.py`
- `src/comicmeta/cli.py`
- `src/comicmeta/_commands/__init__.py`
