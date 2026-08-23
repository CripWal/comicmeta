# Changelog

All notable changes to this project are documented in this file.

## [1.4.0] - 2026-08-23

### Added
- `organize` files loose comics into new series folders instead of renaming root containers: a comic sitting directly in `Marvel/`, `dc/`, or any top-level folder without a `(Year)` now moves into `<container>/Series (Year)/` with a canonical filename. Containers (and the library root itself) are never renamed.
- `organize` collapses umbrella + volume double-wrappers when series/year can be inferred: `Marvel/Hawkeye/Volume 01 (1994)/` → `Marvel/Hawkeye (1994)/`, pruning the emptied wrapper folders afterward.
- Numberless comics (no `#NNN`) now rename to clean `Series (Year).ext` — stripping web-scrape junk like `GetComics.INFO` — both when moving and in place inside canonical folders. Collections (Omnibus/TPB/HC/deluxe) keep their distinguishing names.

### Fixed
- `organize` no longer proposes renaming publisher/root containers or the library root itself.
- Series-name inference no longer splits compound names (`X-Men`, `Spider-Man`) while still normalizing one-sided hyphens (`Daredevil- The` → `Daredevil - The`).

## [1.3.0] - 2026-08-20

### Added
- `comicmeta flags --clear-all` (with `--yes` to skip the prompt) to non-interactively clear every flag — series selections, issue reviews, and pending ComicInfo-replacement requests — so items can re-enter the write pool. The dashboard's `x` key triggers this, making it usable over NAS/SSH without a key-driven TUI.
- `comicmeta mapping --source/-s` to specify the comic library root.

### Fixed
- `mapping` no longer mislabels already-reviewed volumes as `archive-format=unknown`: when a volume is skipped by fetch-issues (its format is absent from the fresh candidates report), the format is now recovered from the on-disk archive. Reviews whose archive is gone are still skipped.
- NAS executors run remote commands over `ssh -t`; the remote pty reported as a TTY, so spinners animated in place and flooded the scrollback with `\r\x1b[K` redraws. Animation is now suppressed for remote processes (`COMICMETA_NO_ANIMATION`), emitting one plain progress line per update instead.
- `flags --clear-all` clears replacement requests in addition to series/issue flags.

## [1.2.0] - 2026-08-14

### Fixed
- Repo-wide bug audit: 30+ fixes across rendering, input, state, and crash paths.
