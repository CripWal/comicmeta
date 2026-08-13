# Testing Patterns

## Core Sections (Required)

### 1) Test Stack and Commands

- Primary test framework: pytest, configured by `pytest.ini`.
- Assertion/mocking tools: pytest assertions, `unittest.mock`, temporary paths, subprocess tests, and Hypothesis in stress/property tests.
- Commands:

```bash
python3 -m pytest -q
python3 -m pytest tests/test_cli.py tests/test_settings.py -q
python3 -m pytest tests/ stress/
python3 -m pytest --cov  # [TODO] coverage plugin/config is not enforced
```

### 2) Test Layout

- Unit and command tests are in `tests/test_*.py`.
- Stress and fuzz-oriented tests are in `stress/`.
- Shared setup is in `tests/conftest.py`.

### 3) Test Scope Matrix

| Scope | Covered? | Typical target | Notes |
|-------|----------|----------------|-------|
| Unit | Yes | config, archive, API helpers, command logic | `tests/` |
| Integration | Partial | CLI subprocesses, filesystem, executor argv | `tests/test_cli.py`, `tests/test_executor.py` |
| E2E | Partial | Acceptance/user-flow scenarios | `tests/test_acceptance.py` |

### 4) Mocking and Isolation Strategy

- Temporary directories isolate settings, libraries, state, and archive writes.
- `unittest.mock` isolates network calls, subprocesses, prompts, and terminal input.
- CLI subprocess tests set `PYTHONPATH` and temporary config roots to avoid user state.
- Common failure mode: interactive behavior can diverge from direct command behavior if TUI input/output paths are not tested together.

### 5) Coverage and Quality Signals

- Coverage tool + threshold: `[TODO]` no coverage configuration or threshold detected.
- Current reported coverage: `[TODO]` not measured in the repository scan.
- Known gaps: real NAS/SSH execution and terminal renderer availability require environment-specific smoke tests.

### 6) Evidence

- `pytest.ini`
- `tests/conftest.py`
- `tests/test_acceptance.py`
- `tests/test_cli.py`
- `tests/test_executor.py`
- `stress/test_fuzz.py`
- `.github/workflows/ci.yml`
