# Stress & Speed Testing

This directory contains adversarial and performance tests for comicmeta.

## Stress tests

```bash
# Property-based fuzzing (Hypothesis): pure parsing helpers under random input
PYTHONPATH=src python3 -m pytest stress/test_fuzz.py

# Chaos/robustness: corrupt archives, symlink loops, deep nesting, fault injection
PYTHONPATH=src python3 -m pytest stress/test_chaos.py

# Everything (existing tests + stress)
PYTHONPATH=src python3 -m pytest tests/ stress/
```

### What they cover

`test_fuzz.py` (Hypothesis, property-based):
- issue-number parsing, title/folder extraction, canonical number normalization
- humanize (`pretty_bytes`, `pretty_duration`) with arbitrary types
- `metadata_candidate`, `date_parts`, `inferred_format`, `plain_text`
- progress-bar bounds, JSON round-trips, ComicInfo audit with random fields

`test_chaos.py` (deterministic adversarial inputs):
- truncated/zero-byte/corrupt zips, duplicate zip members, truncated XML
- symlink loops, 30-deep nesting, unicode/`'`/`—`/`[]` filenames
- ComicVine fault injection: empty results, garbage, URLError, timeout, bad JSON
- path-traversal mapping attacks (absolute, `..`, escape)
- empty libraries, missing state files, missing required fields

### Bugs the stress suite already caught
- `progress_bar()` overflowed / raised `MemoryError` on huge `done` values
  (fixed: clamped ratio to `[0, 1]`)
- `metadata_candidate()` raised `KeyError` on a malformed selection
  (fixed: use `.get()` with defaults)
- `search_volumes`/`fetch_*` propagated `URLError`/`TimeoutError`/bad JSON as
  raw tracebacks instead of clean errors
  (fixed: `_api_request()` wraps network errors into `die()`)

## Speed tests

```bash
# Wall-clock timing of every subcommand (default 3 iterations, reports min)
python3 stress/perf.py --source /path/to/comics

# Profile one command under pyinstrument, write perf-<name>.html
python3 stress/perf.py --source /path/to/comics --profile review
```

### Known timings (macOS, 142-file library on a mounted volume)

| Command                    | Cold   | Warm (cached) |
|----------------------------|--------|---------------|
| review --list              | 0.1s   | 0.1s          |
| flags                      | 0.2s   | 0.1s          |
| browse (tree build)        | 0.2s   | 0.08s         |
| convert dry-run            | 0.4s   | 0.4s          |
| discover (reuse, no API)   | 31s    | 2.6s          |
| inspect (full listing)     | 19.5s  | 8.5s          |
| inspect --quick            | ~11s   | ~0.3s         |
| write (5 small files)      | 11ms   | 11ms          |

### What dominates

- **`discover` / `review` reuse path**: was re-opening every CBZ's central
  directory to check for `ComicInfo.xml`. A persistent presence cache
  (`~/.cache/comicmeta/comicinfo.json`, keyed by size+mtime) cuts cold→warm
  from ~31s to ~2.6s. The cache is used by `discover.rescan`, `inspect --quick`,
  and `browse` tree markers.
- **Fresh discovery** (new files) is ~34s because ComicVine rate-limits to
  0.25s per query and queries run serially. Reuse means subsequent runs only
  query files whose size/mtime/identity changed.
- **`inspect` full listing** opens every archive to read metadata; that's I/O
  bound on mounted volumes. `inspect --quick` lists presence without reading
  metadata and is fast when warm.
- **`write`** is fast (11ms/5 files) — it streams the zip, never decompresses.

### Fixed overhead

Python interpreter startup is ~4s per invocation (measured via pyinstrument:
`inspect --quick` does only 0.28s of real work; the rest is process spawn +
imports). This is the floor for any single CLI call and is not worth optimizing
away.
