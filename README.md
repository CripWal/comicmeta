# comicmeta

A CLI for the controlled ComicVine metadata pipeline for comic archives. Review
matches, then write `ComicInfo.xml` into your CBZ files — the metadata format
Kavita, Jellyfin, and Komga read for library organization.

Every step **before** `write` is read-only. `write` requires an explicit
reviewed mapping and creates verified backups. CBZ is the only writeable
format; CBR is reported but never modified. The interactive experience is
designed for macOS Terminal, with local, external-drive, and NAS libraries
using the same commands.

Pure Python stdlib — zero production runtime dependencies. Works on Python 3.11+.

## Install

```sh
pip install comicmeta
```

Or via Homebrew:

```sh
brew tap CripWal/comicmeta
brew install comicmeta
```

Or Docker (for NAS / headless batch operations — see [Docker](#docker)):

```sh
docker build -t comicmeta .
```

## Quick start

```sh
cd /path/to/comics
comicmeta
```

Running `comicmeta` with no arguments opens an interactive dashboard
navigable with arrow keys. It guides you through health, browse, review,
organize, and write. For a direct safe preview:

```sh
comicmeta health --source /path/to/comics
comicmeta organize --source /path/to/comics --dry-run
```

Organize offers an explicit apply step after showing its proposed changes.
`Ctrl-C` quits cleanly.

## Interactive walkthrough

Animated SVG recordings of the terminal UI (open in a browser to play —
CSS animations, no video):

### Dashboard — arrow-key navigation
<img src="docs/showcase/menu.svg" alt="Dashboard navigation" width="640">

### Browse — expand the library tree and open an issue card
<img src="docs/showcase/browse.svg" alt="Browse the library tree" width="640">

### Browse an issue — cover art preview
<img src="docs/showcase/browse-cover.svg" alt="Browse with cover art" width="640">

### Volume review — scroll ComicVine candidates and accept
<img src="docs/showcase/review.svg" alt="Volume review" width="640">

### Review flow — CBR warning, convert picker, volume review
<img src="docs/showcase/review-convert.svg" alt="Review with convert picker" width="640">

### Settings panel
<img src="docs/showcase/settings.svg" alt="Settings panel" width="640">

## The pipeline

Review-then-write. The read-only phases produce a reviewed mapping; one
mutating phase writes `ComicInfo.xml` into CBZ archives.

```
discover          → comicvine-candidates.json
review-volumes    → comicvine-review-state.json + review.md
fetch-issues      → comicvine-issue-candidates.json
review-issues     → comicvine-issue-review-state.json + issue-review.md
map               → comic-metadata-reviewed-mapping.json
                    + comicmeta-kavita-export.json
──────────────────────────────────────────────────────────────────
write             → ComicInfo.xml inside CBZs + write-report.json
```

Each phase is resumable — state persists between runs. Re-running `discover`
skips files that already have complete metadata. `write` refuses to replace any
existing ComicInfo.xml automatically; those files require a separately
approved replacement flow.

## Mac vs NAS

If your comic library lives on a local drive (external HDD/SSD, internal
storage), run comicmeta directly — it's fast.

If your library lives on a NAS (TrueNAS, unRAID, Synology), create a context
once and select it from the dashboard or with `--context`. You can launch
comicmeta from any working directory; the selected context supplies the
correct remote library path:

```sh
comicmeta context add nas --host nas.example.local --ssh-user comics \
  --library-path /path/on/nas/comics
comicmeta context use nas
comicmeta --context nas health
comicmeta --context nas organize
```

For a mounted share or external drive, use its path directly. The path does
not need to be the directory where the command is launched:

```sh
comicmeta health --source /Volumes/media/comics
cd /Volumes/T7-Storage/comics
comicmeta organize
```

For large libraries accessed over SMB, running I/O-heavy commands on the NAS
or through an `rsync` context avoids network latency and unreliable large-file
renames:

| Command | Where | Why |
|---------|-------|-----|
| Metadata review and mapping | Either | Uses JSON state and reports; run it wherever your working state is available |
| Archive inspection, health, and discovery | Near the library | Reads CBZ/CBR archives, so local or NAS execution avoids unnecessary network traffic |
| Write and organize | On the library’s host | Mutates files and folders; use the configured context or run locally on the mounted drive |

Contexts replace the need for a hand-maintained NAS wrapper: they store the
remote host, library path, and state path in ComicMeta and work regardless of
the directory from which you launch the command.

### Docker

For NAS users who prefer a container over SSH:

```sh
# docker-compose.yaml is included in the repo
docker compose run --rm comicmeta inspect --quick --source /comics

# Or stand-alone:
docker run --rm -v /path/to/comics:/comics -v comicmeta-data:/data \
  comicmeta discover --source /comics

# Write (with API key):
COMICVINE_API_KEY=... docker compose run --rm comicmeta \
  write --yes --source /comics \
  --mapping /data/config/libraries/<hash>/comic-metadata-reviewed-mapping.json \
  --backup-dir /data/backups \
  --report /data/config/libraries/<hash>/write-report.json
```

The Docker container runs **headless batch commands only** (discover, inspect,
write, health, etc.). Interactive review stays on your workstation against
synced state files.

## Full command reference

```sh
# Query ComicVine and write a candidate report (read-only)
COMICVINE_API_KEY=... comicmeta discover --source /path/to/comics --report candidates.json

# Interactively review volume candidates (read-only)
comicmeta review-volumes --report candidates.json --state review-state.json \
  --summary review.md

# Fetch issue-level ComicVine data for selected volumes (read-only)
COMICVINE_API_KEY=... comicmeta fetch-issues --selections review-state.json \
  --report issue-candidates.json

# Interactively review issue-level candidates (read-only)
comicmeta review-issues --report issue-candidates.json \
  --state issue-review-state.json --summary issue-review.md

# Generate a CBZ-only writer mapping from completed review state
comicmeta map --candidates issue-candidates.json --review issue-review-state.json \
  --output reviewed-mapping.json

# Copy reviewed CBZ files into an empty staging root (read-only)
comicmeta stage --source /path/to/comics --destination /tmp/staging \
  --mapping reviewed-mapping.json --report stage-report.json

# Validate staged ComicInfo writes against production state (read-only)
comicmeta validate --source /tmp/staging --production /path/to/comics \
  --backup-dir /tmp/backup --mapping reviewed-mapping.json \
  --copy-report stage-report.json --write-report write-report.json

# Write reviewed ComicInfo.xml into production CBZ archives
comicmeta write --source /path/to/comics --mapping reviewed-mapping.json \
  --expected-hashes stage-report.json --backup-dir /tmp/backup \
  --report write-report.json
```

### Other commands

```sh
comicmeta status [--json]      # one-glance view of context, library, pipeline state
comicmeta inspect [--quick]   # list library + per-file ComicInfo status
comicmeta browse               # interactive tree view with covers + flags
comicmeta health [--deep]      # scan for corrupt archives, missing metadata
comicmeta convert              # CBR → CBZ via bsdtar (needs bsdtar on PATH)
comicmeta organize              # preview and report safe organization changes
comicmeta organize --execute    # apply folder/file normalization to Series (Year) #NNN
comicmeta flags                # list/clear research-flagged series + issues
comicmeta missing              # report ComicVine issues absent from your library
comicmeta backups [--delete]   # list/clean stored write backups
comicmeta self-test            # smoke-test the environment + config
comicmeta settings [--init]    # show/scaffold/edit comicmeta.toml
comicmeta help [command]       # show help for a command (alias for --help)
comicmeta completion zsh|bash  # generate a shell completion script

For full-color cover previews in macOS Terminal, comicmeta offers to install
the optional `timg` renderer with Homebrew on first run. No software is
installed on the library drive. Cover previews can be enabled or disabled
later from Settings. Browse supports flagging/unflagging from the issue view,
named alternate-cover selection, and a gallery for a series.
```

Global flags: `--context NAME` (run against a NAS context), `--debug` (show a
full traceback on unexpected errors), `--no-input` (never prompt; fail instead).

The dashboard runs `organize` as a dry-run first, then offers an explicit apply
step. It can infer missing starting years and series names from numbered archive
filenames, including collected editions named like `01 (of 5) (1993)`.
For rsync NAS contexts, the current comicmeta source is synchronized
automatically before remote commands run; `context edit NAME --sync` remains
available for an explicit manual sync.
`comicmeta status` answers "where am I?" — the active context, library size, and
which pipeline phases have data, with a suggested next command. Errors link to
the GitHub issue tracker so bugs are easy to report.

## Settings

Configuration lives in `comicmeta.toml` in the library directory (or
`~/.config/comicmeta/comicmeta.toml`). Precedence: CLI flags > environment
variables > settings file > built-in defaults.

```sh
comicmeta settings            # show resolved settings
comicmeta settings --init     # scaffold comicmeta.toml in the current directory
comicmeta settings --set api.request_delay=0.5
comicmeta settings --set review.high_confidence_score=80
```

| Section | Keys |
|---------|------|
| `paths` | `source`, `candidates`, `volume_state`, `volume_summary`, `policy`, `issue_candidates`, `issue_state`, `issue_summary`, `mapping`, `kavita_export`, `backup_dir`, `write_report` |
| `api` | `key_env`, `key_file`, `request_delay`, `timeout`, `user_agent`, `candidate_limit` |
| `review` | `active_source`, `blocked_queries`, `high_confidence_score`, `high_confidence_margin`, `continue_to_write` |
| `write` | `enforce_expected_hashes`, `auto_confirm` |
| `appearance` | `color`, `dashboard`, `theme`, `cover_previews` |

The ComicVine API key is read from an environment variable (default
`COMICVINE_API_KEY`) or a file path (`api.key_file` in settings). The key is
never persisted by comicmeta or written to logs.

Running `comicmeta settings` opens a centered interactive panel. Appearance
controls and compact connection summaries are shown first; press `[a]` for API,
paths, review, and write-safety settings. Press `Enter` on a connection to open
its SSH settings. The selected row is preserved while searching, expanding
connections, and changing settings:

| Context field | Default | Meaning |
|---------------|---------|---------|
| `host` | — | NAS hostname or IP |
| `ssh_user` | — | SSH username |
| `ssh_port` | `22` | SSH port |
| `identity_file` | (default keys) | SSH identity/private-key path |
| `connect_timeout` | `10` | SSH connect timeout (seconds) |
| `library_path` | — | comic library path on the NAS |
| `exec` | `rsync` | `rsync` (source + NAS Python) or `docker` |

Set them per-context: `comicmeta context edit nas --ssh-port 2222 --identity-file ~/.ssh/id_ed25519`.

### Exit codes

`0` success; non-zero on failure. The `write` command refuses path traversal,
existing ComicInfo.xml, missing required identity fields, backup
collisions, and unsupported archive writes. A failure at file N rolls back
**only** file N from its verified backup; successfully written files earlier in
the run are kept, the failed file is logged, and the batch continues. Re-running
`comicmeta write` skips files that already have ComicInfo.

## Development

The user guide is available in the [GitHub wiki-ready pages](docs/wiki/).
The evidence-backed contributor map is in [docs/codebase/](docs/codebase/).

```sh
pip install -e .
python -m pytest tests/ stress/
python -m build --sdist
```

GitHub Actions runs the test suite on Python 3.11 through 3.14 for pushes and
pull requests.

Run `python -m comicmeta --help` for the full command list.

## License

MIT
