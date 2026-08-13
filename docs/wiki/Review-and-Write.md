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
- Refuses to replace any existing root `ComicInfo.xml`; replacement is a separate
  future operation requiring explicit approval.
- Preserves successfully written files if a later file fails.

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
