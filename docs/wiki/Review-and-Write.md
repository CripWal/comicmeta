# Review and Write

comicmeta uses a review-then-write pipeline:

```text
discover → review-volumes → fetch-issues → review-issues → map
                                                          ↓
                                                        write
```

The review phases produce state and reports. `map` creates the explicit
reviewed mapping consumed by `write`.

## Typical command sequence

```sh
comicmeta discover --source /path/to/comics --report candidates.json
comicmeta review-volumes --report candidates.json --state volume-review.json \
  --summary volume-review.md
comicmeta fetch-issues --selections volume-review.json --report issue-candidates.json
comicmeta review-issues --report issue-candidates.json --state issue-review.json \
  --summary issue-review.md
comicmeta map --candidates issue-candidates.json --review issue-review.json \
  --output reviewed-mapping.json --kavita-export comicmeta-kavita-export.json
comicmeta stage --source /path/to/comics --destination /tmp/comicmeta-staging \
  --mapping reviewed-mapping.json --report stage-report.json
comicmeta validate --source /tmp/comicmeta-staging --production /path/to/comics \
  --backup-dir /tmp/comicmeta-backups --mapping reviewed-mapping.json \
  --copy-report stage-report.json --write-report write-report.json
comicmeta write --source /path/to/comics --mapping reviewed-mapping.json \
  --expected-hashes stage-report.json --backup-dir /tmp/comicmeta-backups \
  --report write-report.json
```

The interactive dashboard wraps the same workflow and keeps the intermediate
steps visible, so normal users do not need to assemble the pipeline by hand.

For a quick preview without staging, use `comicmeta write --dry-run` with the
reviewed mapping. The full staged sequence above is the production safety path.

## Write safety

`write`:

- Accepts CBZ archives only.
- Requires reviewed mapping data.
- Creates verified backups before mutation.
- Refuses path traversal and unsafe destinations.
- Refuses to replace any existing root `ComicInfo.xml` **unless the archive was
  explicitly marked for replacement in browse** (`[r]`). Marked archives go
  through review again and are rewritten on the next `write`.
- Preserves successfully written files if a later file fails.

### Replacing existing metadata

Download tools (e.g. Kapowarr) can embed ComicInfo that is incomplete or wrong.
To re-review and replace such a file:

1. In `comicmeta browse`, move to the archive and press `r` — it shows a `↻`
   marker and is added to the replacement-request state.
2. Run `comicmeta review` — the marked file is forced through review again even
   though its existing ComicInfo audits as complete.
3. Run `comicmeta write` — the guard against overwriting existing ComicInfo is
   lifted for marked files, and each request clears automatically after a
   successful write.

Replacement-requested files are listed by `comicmeta flags` alongside research
flags, so you can see what is pending before a batch write.

### Backup lifecycle

On the first interactive launch, comicmeta asks where backups should live:
a mounted volume (NAS or external drive), a custom path, the default state-dir
location, or no backups. That choice is recorded once; the location is always
re-editable from the settings panel (STORAGE → Backup location).

Backups are per-library, stored under `paths.backup_dir`
(`~/.config/comicmeta/libraries/<hash>/comicmeta-backups/latest/` by default).
`comicmeta backups` lists them and `comicmeta backups --purge` deletes them after
showing the space to be freed.

Three `[write]` settings control how much space backups consume:

| Setting | Default | Effect |
|---|---|---|
| `write.keep_backups` | `true` | When `false`, `write` touches archives with no safety copy. `--no-backups` on the CLI does the same for one run. |
| `write.backup_retention` | `0` | Keep backups this many days, then auto-delete older ones on the next successful write. `0` keeps them forever. |
| `write.keep_backup_after_verify` | `false` | Auto-purge a library's entire backup directory after a fully validated write completes. |

Choosing "no backups" is risky: converting a `.cbr` moves the original into the
backup directory, so without one an interrupted conversion can leave no
recoverable original.

`--purge` (or `--delete`) requires an interactive confirmation; in non-interactive
use pass nothing — the commands refuse to run without a TTY so backups are never
destroyed by a script.

## ComicVine fields and ComicInfo mapping

Discovery and issue fetching retain ComicVine issue/volume IDs, canonical URLs,
titles, publisher, description/deck, release dates, cover image metadata,
person credits, characters, teams, locations, story arcs, tags, and genres.
Reviewed issue metadata maps to these ComicInfo fields:

| Reviewed data | ComicInfo.xml |
|---|---|
| Series, series sort, localized series | `Series`, `SeriesSort`, `LocalizedSeries` |
| Volume, number, count, year/month/day, format | `Volume`, `Number`, `Count`, `Year`, `Month`, `Day`, `Format` |
| Title, publisher, imprint | `Title`, `Publisher`, `Imprint` |
| Writer, penciller, inker, colorist, letterer, cover artist, editor | `Writer`, `Penciller`, `Inker`, `Colorist`, `Letterer`, `CoverArtist`, `Editor` |
| Genres, tags, characters, teams, locations | `Genre`, `Tags`, `Characters`, `Teams`, `Locations` |
| Story arcs and number | `StoryArc`, `StoryArcNumber` |
| Summary, notes, ComicVine URL | `Summary`, `Notes`, `Web` |
| Age rating | `AgeRating` only when explicitly entered and reviewed |

Multi-value fields use the ComicInfo semicolon delimiter. HTML is stripped from
ComicVine descriptions before review. XML escaping is handled by the archive
writer.

The reviewed mapping preserves `comicvine_issue_id`, `comicvine_volume_id`, and
`comicvine_url`. `comicmeta-kavita-export.json` is a separate reviewed payload
for a future Kavita API synchronization step. Embedded ComicInfo metadata does
not populate Kavita's AniList, MAL, MangaBaka, Hardcover, Metron, or ComicVine
database IDs, and comicmeta fabricates none of those IDs.

After an approved production write, trigger a manual Kavita library rescan so
Kavita reprocesses the changed embedded ComicInfo metadata.

Use `comicmeta backups` to inspect stored backups. Do not delete backups until
the resulting library has been checked in the reader application.
