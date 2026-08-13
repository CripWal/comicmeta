# Codebase Concerns

## Core Sections (Required)

### 1) Top Risks (Prioritized)

| Severity | Concern | Evidence | Impact | Suggested action |
|----------|---------|----------|--------|-----------------|
| High | `cli.py` coordinates many interactive flows and is high churn | scan high-churn section; `src/comicmeta/cli.py` | UI regressions can affect multiple screens | Add focused interaction tests before further refactors |
| Medium | CI does not yet enforce formatting or coverage | `.github/workflows/ci.yml`, `pytest.ini` | Style and untested paths can still merge | Add checks after choosing a formatter and coverage baseline |
| Medium | Remote NAS behavior depends on SSH/rsync/Docker environment | `_executor.py`, `_executors/` | Local tests may not catch host-specific failures | Maintain a documented NAS smoke test |
| Medium | Optional terminal renderer availability varies | `_cover.py`, `cli.py` | Cover views may degrade or appear unavailable | Keep fallback messaging and test renderer detection |

### 2) Technical Debt

| Debt item | Why it exists | Where | Risk if ignored | Suggested fix |
|-----------|---------------|-------|----------------|---------------|
| No formatter/linter gate | Repository currently relies on tests and local style | scan lint section | Style drift and harder reviews | `[ASK USER]` choose ruff/format policy |
| No coverage threshold | Coverage is not enforced | `pytest.ini`, scan testing section | Untested CLI paths may regress | Add targeted coverage reporting after baseline measurement |
| Internal state and user-facing docs can drift | Behavior spans CLI, commands, config, and wiki | `README.md`, `docs/wiki/`, `src/comicmeta/` | Users follow stale commands | Update docs with each visible workflow change |

### 3) Security Concerns

| Risk | OWASP category (if applicable) | Evidence | Current mitigation | Gap |
|------|--------------------------------|----------|--------------------|-----|
| Archive mutation is high impact | N/A | `_commands/write.py` | Reviewed mapping, backups, validation, CBZ-only writes | Real NAS write smoke test remains environment-dependent |
| Remote command construction must remain safely quoted | N/A | `_executor.py` | `shlex.quote` and explicit argv preparation | Add more adversarial context/argument tests |
| API key exposure through config or logs | N/A | `_comicvine.py`, `_config.py` | Env/file/Keychain options and no intentional logging | `[TODO]` document file permissions and rotation guidance |

### 4) Performance and Scaling Concerns

| Concern | Evidence | Current symptom | Scaling risk | Suggested improvement |
|---------|----------|-----------------|--------------|----------------------|
| Archive scans open many files | `_archive.py`, health/inspect commands | Cost grows with library size | Slow SMB/NAS scans | Keep cache/deep-scan distinction and benchmark representative libraries |
| Batch ComicVine requests are bounded but external | `_comicvine.py` | Network latency dominates discovery | API limits or throttling | Preserve request delay/concurrency controls |

### 5) Fragile/High-Churn Areas

| Area | Why fragile | Churn signal | Safe change strategy |
|------|-------------|--------------|----------------------|
| `src/comicmeta/cli.py` | Dashboard, settings, themes, and dispatch share one module | 41 changes in scan history | Make one screen change at a time and run CLI tests |
| `src/comicmeta/_commands/write.py` | Data mutation and recovery behavior | 27 changes | Preserve backup/hash tests and add regression cases |
| `src/comicmeta/_config.py` | Global appearance and per-library state resolution | 12 changes | Test source/context combinations explicitly |

### 6) `[ASK USER]` Questions

1. [ASK USER] Should a coverage threshold be part of the 1.0 release gate?
2. [ASK USER] Should real NAS smoke tests run in CI, or remain a documented manual release check?

### 7) Evidence

- `docs/codebase/.codebase-scan.txt`
- `src/comicmeta/cli.py`
- `src/comicmeta/_config.py`
- `src/comicmeta/_commands/write.py`
- `src/comicmeta/_executor.py`
- `pytest.ini`
