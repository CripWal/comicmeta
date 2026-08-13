# Technology Stack

## Core Sections (Required)

### 1) Runtime Summary

| Area | Value | Evidence |
|------|-------|----------|
| Primary language | Python | `pyproject.toml`, `src/` |
| Runtime + version | Python >= 3.11 | `pyproject.toml` (`requires-python`) |
| Package manager | pip/setuptools; Homebrew packaging is also present | `pyproject.toml`, `tap/Formula/comicmeta.rb` |
| Module/build system | setuptools with `src` layout | `pyproject.toml` |

### 2) Production Frameworks and Dependencies

| Dependency | Version | Role in system | Evidence |
|------------|---------|----------------|----------|
| Python standard library | N/A | CLI, TOML, ZIP/CBZ, XML, HTTP, SSH/rsync process execution | `pyproject.toml`, `src/comicmeta/` |
| ComicVine API | HTTP service | Volume and issue metadata lookup | `src/comicmeta/_comicvine.py` |

### 3) Development Toolchain

| Tool | Purpose | Evidence |
|------|---------|----------|
| pytest | Automated tests | `pytest.ini`, `tests/` |
| Docker Compose | Headless/container execution | `docker-compose.yaml`, `Dockerfile` |
| Hypothesis | Fuzz/property-style tests | `stress/`, `tests/` |

### 4) Key Commands

```bash
pip install -e .
python -m pytest tests/ stress/
python -m build --sdist
```

No lint or format command is configured in the repository. `[TODO]` Add one
when a formatter/linter becomes part of the project contract.

### 5) Environment and Config

- Config sources: `comicmeta.toml`, user config under `~/.config/comicmeta/`, CLI flags, environment variables.
- Required environment variables: `COMICVINE_API_KEY` by default; an API key file or macOS Keychain can be configured instead.
- Runtime constraints: Python 3.11+; optional `timg` is used for macOS terminal cover previews.

### 6) Evidence

- `pyproject.toml`
- `pytest.ini`
- `Dockerfile`
- `docker-compose.yaml`
- `src/comicmeta/_config.py`
