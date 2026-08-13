# Reddit posts for comicmeta

Posts tailored per subreddit. All are self-posts; disclose ownership. No piracy references anywhere.

## r/comicrackusers

**Title:** `A CLI that writes ComicInfo.xml into your CBZ archives — ComicRack-adjacent, matches on ComicVine`

> ComicRack users know the pain: you spend an evening hand-fixing metadata, then the next batch of files is a mess again. I built a small CLI called **comicmeta** that takes a lot of that off your plate.
>
> It's a controlled ComicVine metadata pipeline for comic archives:
> - **Scans** your library (CBZ/CBR), **reviews** matches against ComicVine before writing anything
> - **Writes** `ComicInfo.xml` into each CBZ — the same metadata format ComicRack reads and writes
> - Every step before `write` is read-only; `write` requires an explicit reviewed mapping and creates verified backups
> - `CBR` is reported but never modified
> - Pure Python stdlib, zero runtime dependencies; `pip install comicmeta`, Homebrew, or Docker for NAS/headless batch
>
> The workflow is deliberately manual: you review each match, then commit. No blind auto-fill.
>
> *(Disclosure: this is my project.)* If you manage a library in ComicRack, I'd genuinely like to hear whether this fits your workflow — especially the review-then-write flow.

## r/comicbooks

**Title:** `Managing a 10k-file digital comics library is miserable — I built a tool to fix metadata, thought you'd want to know it exists`

> If you keep a digital collection of comics you own, you've hit the wall where your reader can't sort anything because the archives have no metadata. I built a CLI called **comicmeta** to deal with exactly that.
>
> - **Scans** your library (CBZ/CBR), **reviews** matches against ComicVine's licensed API before writing anything
> - **Writes** `ComicInfo.xml` into each CBZ — the format Kavita, Komga, Jellyfin, and ComicRack read for organization
> - Everything before `write` is read-only; `write` needs an explicit reviewed mapping and makes verified backups
> - `CBR` files are reported, never modified
> - `pip install comicmeta`, Homebrew, or Docker; pure Python, no runtime dependencies
>
> It's meant for people who own the comics and want their library to organize itself. It doesn't touch where files come from — only the metadata that's already in files you own.
>
> *(Disclosure: this is my project.)* Feedback welcome, especially from folks with big libraries.

## r/KavitaManga

**Title:** `Kavita reads ComicInfo.xml — so here's a CLI that writes it into your CBZ files (reviewed against ComicVine)`

> Kavita's metadata comes from `ComicInfo.xml`, but most archives don't have one — which is why a fresh library can come in as a wall of unsorted files. I built a small CLI called **comicmeta** that fixes that gap.
>
> - **Scans** your library (CBZ/CBR), **reviews** matches against ComicVine before writing anything
> - **Writes** `ComicInfo.xml` into each CBZ — what Kavita reads for series, volume, issue, covers, and ordering
> - Every step before `write` is read-only; `write` requires an explicit reviewed mapping and creates verified backups
> - `CBR` reported, never modified
> - Pure Python stdlib, zero runtime deps — `pip install comicmeta`, Homebrew, or Docker (works great on a NAS for batch jobs)
>
> No auto-fill guesswork: you approve each match, then it writes. Since this directly targets Kavita's metadata format, I figured it was worth sharing here.
>
> *(Disclosure: this is my project.)* Would love to hear from Kavita users on how the reviewed workflow fits or misses.

## r/Komga (requires mod approval — sub is restricted)

**Title:** `Tooling for the metadata gap: a CLI that writes ComicInfo.xml into CBZ so Komga sorts your library properly`

> Komga's whole model runs on ComicInfo.xml, but most archives ship without it — which is why a fresh library often comes in as one giant unsorted pile. I built a small CLI called **comicmeta** to close that gap.
>
> - **Scans** your library (CBZ/CBR) and **reviews** matches against ComicVine before writing anything
> - **Writes** `ComicInfo.xml` into each CBZ — the exact metadata Komga reads for series/volume/issue ordering
> - Every step before `write` is **read-only**; `write` requires an explicit reviewed mapping and creates verified backups
> - `CBR` is reported, never modified
> - Pure Python stdlib, zero runtime deps: `pip install comicmeta`, Homebrew, or Docker for NAS batch jobs
>
> The design is review-first, not auto-fill — you approve each match, then it writes. Since this targets Komga's metadata format directly, it felt worth sharing here.
>
> *(Disclosure: my project.)* Feedback from Komga users is exactly what I'm after.

## r/jellyfin

**Title:** `If you run a comics library in Jellyfin, this metadata tool might save you an evening`

> Jellyfin reads ComicInfo.xml for comic libraries, but most CBZ files arrive without it — so your comics collection ends up as a wall of unsorted files while your movies get pretty posters. I built a small CLI (**comicmeta**) that handles the metadata part.
>
> - **Scans** your library (CBZ/CBR), **reviews** matches against ComicVine before writing
> - **Writes** `ComicInfo.xml` into each CBZ — what Jellyfin reads for series/issue/cover ordering
> - Everything before `write` is read-only; `write` needs an explicit reviewed mapping and makes backups
> - `CBR` files are reported, never touched
> - `pip install comicmeta`, Homebrew, or Docker; pure Python, no runtime deps
>
> It's deliberately a review-then-write workflow rather than blind auto-fill — the point is that *you* confirm each match before it commits. If you've fought your Jellyfin comic library's sorting, I'd be curious whether this approach fits.

## Not posting there

| Subreddit | Verdict | Why |
|---|---|---|
| r/selfhosted | Hold | New-project megathread only if <3mo old (first public commit); must be production-ready with docs |
| r/koreader | No | No rules posted, but KOReader doesn't consume ComicInfo.xml — reads off-topic |
| r/DataHoarder | No | Rule 6 bans "look what I built" posts and unapproved advertising |
| r/toolstalk / r/SideProject / r/Python | Low priority | Viable but low traffic or strict self-promo; revisit later |
