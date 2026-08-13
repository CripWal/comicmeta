# External Integrations

## Core Sections (Required)

### 1) Integration Inventory

| System | Type (API/DB/Queue/etc) | Purpose | Auth model | Criticality | Evidence |
|--------|--------------------------|---------|------------|-------------|----------|
| ComicVine | HTTP API | Volume search, volume fetch, issue fetch, key verification | API key from env/file/macOS Keychain | High for discovery/review | `src/comicmeta/_comicvine.py` |
| SSH | Transport | Run commands against configured NAS contexts | SSH user, port, identity file | High for remote workflows | `src/comicmeta/_executor.py`, `_context.py` |
| rsync | File synchronization | Sync source/state for rsync NAS executor | SSH transport | Medium/High for rsync mode | `src/comicmeta/_executor.py`, `src/comicmeta/_executors/rsync.py` |
| Docker | Runtime/container | Headless NAS execution mode | Host Docker access | Medium | `Dockerfile`, `docker-compose.yaml`, `_executors/docker.py` |
| macOS `security` CLI | Local credential store | Optional API key lookup | macOS Keychain | Low/Medium | `src/comicmeta/_comicvine.py` |

### 2) Data Stores

| Store | Role | Access layer | Key risk | Evidence |
|-------|------|--------------|----------|----------|
| CBZ ZIP archives | Comic files and optional `ComicInfo.xml` | `_archive.py`, command modules | Write mutation/data loss | `src/comicmeta/_archive.py`, `_commands/write.py` |
| TOML settings | User and library configuration | `_config.py` | Wrong source/context selection | `src/comicmeta/_config.py` |
| JSON/Markdown state files | Resumable review, mapping, reports, cover selection | `_config.py`, command modules | State collision or stale state | `src/comicmeta/_config.py` |

### 3) Secrets and Credentials Handling

- Credential sources: environment variable, configured key file, optional macOS Keychain.
- Hardcoding checks: no required API key is hardcoded; source contains the public ComicVine endpoint and default user agent.
- Rotation/lifecycle: `[TODO]` no automated key rotation mechanism is defined.

### 4) Reliability and Failure Behavior

- ComicVine requests use timeouts and convert URL, timeout, JSON, and OS errors to clean failures (`_comicvine.py`).
- Batch volume requests use bounded concurrency and request spacing (`_comicvine.py`).
- SSH and rsync failures map to readable status messages (`_executor.py`).
- Circuit breaker: none detected.

### 5) Observability for Integrations

- Human-readable command output reports progress and per-file outcomes.
- Structured metrics/tracing: none detected.
- Missing visibility: `[TODO]` add machine-readable remote execution diagnostics if operational monitoring becomes necessary.

### 6) Evidence

- `src/comicmeta/_comicvine.py`
- `src/comicmeta/_executor.py`
- `src/comicmeta/_executors/rsync.py`
- `src/comicmeta/_executors/docker.py`
- `src/comicmeta/_config.py`
