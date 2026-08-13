# Coding Conventions

## Core Sections (Required)

### 1) Naming Rules

| Item | Rule | Example | Evidence |
|------|------|---------|----------|
| Files | lowercase snake_case; command names match CLI names | `review_issues.py`, `health.py` | `src/comicmeta/` |
| Functions/methods | lowercase snake_case; private helpers begin `_` | `_config.load`, `_archive.archives` | `src/comicmeta/` |
| Types/interfaces | PascalCase | `Executor`, `Palette` | `src/comicmeta/_executor.py`, `_common.py` |
| Constants/env vars | uppercase snake_case | `DEFAULTS`, `COMICVINE_API_KEY` | `src/comicmeta/_config.py`, `_comicvine.py` |

### 2) Formatting and Linting

- Formatter: `[TODO]` no formatter configuration detected.
- Linter: `[TODO]` no linter configuration detected.
- Most relevant enforced rules: Python type hints and standard-library style are used, but no automated formatter/linter gate is configured.
- Run commands: `python3 -m pytest -q`; package build command is `python -m build --sdist`.

### 3) Import and Module Conventions

- Imports are grouped as standard library, package imports, and local modules in representative files.
- Internal modules use explicit imports from `comicmeta` or `comicmeta._...`.
- No barrel-export policy is configured; subcommands are explicitly imported and registered in `_commands/__init__.py`.

### 4) Error and Logging Conventions

- User-facing command failures generally use shared `die(...)` handling for clean messages and exit codes.
- External failures are converted into readable messages in `_comicvine.py` and `_executor.py`.
- Secrets are read from environment, key file, or macOS Keychain; API keys are not intentionally logged.

### 5) Testing Conventions

- Tests live under `tests/` and use `test_*.py` names.
- Mocks and temporary directories isolate filesystem, subprocess, network, and TUI behavior.
- Coverage expectation: `[TODO]` no enforced threshold detected.

### 6) Evidence

- `src/comicmeta/_common.py`
- `src/comicmeta/_commands/__init__.py`
- `src/comicmeta/_comicvine.py`
- `tests/test_cli.py`
- `pytest.ini`
