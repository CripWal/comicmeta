<p align="center">
  <img src="docs/showcase/browse-cover.svg" alt="comicmeta — browse your library, review against ComicVine, write ComicInfo.xml safely" style="max-width: 720px; width: 100%; height: auto;">
</p>

A comic archive without `ComicInfo.xml` is just a folder of images. Your reader — Kavita, Jellyfin, Komga — can't tell one issue from the next, and filling that metadata in by hand, series after series, is the kind of chore a terminal should swallow whole.

comicmeta is a **review-first ComicVine metadata pipeline** for comic archives. It scans your library, matches every file against ComicVine, walks you through the review, and writes `ComicInfo.xml` into each CBZ — with backups, and only the files you approve. Everything before `write` is read-only.

Pure Python stdlib, zero production dependencies. Python 3.11+.

## Get started

1. **Install**

   ```sh
   pip install comicmeta
   ```

   or via Homebrew:

   ```sh
   brew tap CripWal/comicmeta
   brew install comicmeta
   ```

2. **Open your terminal** in your comic folder:

   ```sh
   cd /path/to/comics
   comicmeta
   ```

   The dashboard opens with the pipeline ready. Arrow around, jump straight to a step, or open Settings — and for a quick read of the library without the TUI:

   ```sh
   comicmeta health --source /path/to/comics
   comicmeta organize --source /path/to/comics --dry-run
   ```

## Browse the library

Expand the tree down to your files, open an issue, and see its cover, metadata, and summary. Flag anything that needs research, choose a named alternate cover, or open the series gallery — all read-only.

<p align="center">
  <img src="docs/showcase/browse.svg" alt="comicmeta's browse view: the library tree and issue card" style="max-width: 720px; width: 100%; height: auto;">
</p>

## Review against ComicVine

comicmeta queries ComicVine for every series, scores the candidates, and lets you accept, skip, or flag each one. State persists between runs, so a big library can be reviewed across sessions.

<p align="center">
  <img src="docs/showcase/review.svg" alt="comicmeta's volume review: scroll ComicVine candidates and accept" style="max-width: 720px; width: 100%; height: auto;">
</p>

## Convert, write, done

CBR archives can't carry `ComicInfo.xml`, so comicmeta offers to convert them to CBZ before reviewing. Once the review is complete, `write` inserts ComicInfo into only the approved files — after a verified backup.

<p align="center">
  <img src="docs/showcase/review-convert.svg" alt="comicmeta's review flow: CBR warning, convert picker, volume review" style="max-width: 720px; width: 100%; height: auto;">
</p>

## Everything, lightly

The whole app in one glance — each of these is a real command, and each has a
dedicated page in the [wiki](#the-wiki) when you want to go deep.

| Do this | Command | What it does |
|---|---|---|
| Browse | `browse` | Read-only tree of the library, covers, flags, series gallery |
| Check up | `health` | Scan for corrupt archives and missing metadata |
| Name things | `organize` | Rename files/folders to `Series (Year) #NNN`; dry-run by default |
| Convert | `convert` | CBR → CBZ when a reader won't touch CBR |
| Review | `review-volumes` / `review-issues` | Match files against ComicVine, accept/skip/flag |
| Write | `write` | Insert `ComicInfo.xml` into approved CBZs, with backups |
| Research | `flags` / `missing` | Track flagged series and ComicVine issues not in your library |
| Configure | `settings` / `context` | TOML settings; local vs NAS context |

## The wiki

[wiki]: https://github.com/CripWal/comicmeta/wiki

The README is the headline; the [wiki][wiki] is the full story. It covers
install and first-run ([Getting Started][wiki:gs]), the review-to-write flow
([Review and Write][wiki:rw]), renaming and health ([Health and Organize][wiki:ho]),
libraries on a NAS ([Library Contexts][wiki:lc]), covers ([Browse and
Covers][wiki:bc]), settings, troubleshooting, and the 1.0 release notes.

[wiki:gs]: https://github.com/CripWal/comicmeta/wiki/Getting-Started
[wiki:rw]: https://github.com/CripWal/comicmeta/wiki/Review-and-Write
[wiki:ho]: https://github.com/CripWal/comicmeta/wiki/Health-and-Organize
[wiki:lc]: https://github.com/CripWal/comicmeta/wiki/Library-Contexts
[wiki:bc]: https://github.com/CripWal/comicmeta/wiki/Browse-and-Covers

## Safe by design

| Promise | How |
|---|---|
| Nothing changes before you approve it | Every step up to `write` is read-only |
| `write` never surprises you | Requires an explicit reviewed mapping and creates a verified backup per file |
| CBZ only | CBR is reported or converted — never modified in place |
| Failures stay small | A failed file rolls back from its backup; the batch continues |

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

## Where it runs

Local drive, external share, or NAS — the same commands either way.

### Mac vs NAS

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
| Write and organize | On the library's host | Mutates files and folders; use the configured context or run locally on the mounted drive |

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

## Commands

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

Other commands:

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
```

Global flags: `--context NAME` (run against a NAS context), `--debug` (show a
full traceback on unexpected errors), `--no-input` (never prompt; fail instead).

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

For full-color cover previews, comicmeta offers to install the optional `timg`
renderer on first run. No software is installed on the library drive. Browse
supports flagging, named alternate-cover selection, and a series gallery.

### Exit codes

`0` success; non-zero on failure. The `write` command refuses path traversal,
existing ComicInfo.xml, missing required identity fields, backup
collisions, and unsupported archive writes. A failure at file N rolls back
**only** file N from its verified backup; successfully written files earlier in
the run are kept, the failed file is logged, and the batch continues. Re-running
`comicmeta write` skips files that already have ComicInfo.

## Privacy

comicmeta talks to [ComicVine](https://comicvine.gamespot.com) only when you
run a discovery/fetch command, using your own API key — which stays on your
machine, never in logs. Nothing is uploaded from your library; metadata flows
into your CBZ files and stays there. The repo is open source (MIT), so there is
nothing to hide behind.

## Development

The user guide is available in the [GitHub wiki-ready pages](docs/wiki/).
The evidence-backed contributor map is in [docs/codebase/](docs/codebase/).

```sh
pip install -e .
python -m pytest tests/ stress/
python -m build --sdist
```

GitHub Actions runs the test suite on Python 3.11 through 3.14 for pushes and
pull requests. Tagging a `v*` release publishes to PyPI via trusted publishing.

Run `python -m comicmeta --help` for the full command list.

## License

MIT
