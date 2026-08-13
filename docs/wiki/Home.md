# comicmeta Wiki

comicmeta is a review-first ComicVine metadata tool for CBZ comic libraries.
It helps you inspect, review, organize, and write `ComicInfo.xml` safely for
Kavita, Jellyfin, Komga, and similar readers.

## Start here

- [Getting Started](Getting-Started.md)
- [Local drives, external drives, and NAS contexts](Library-Contexts.md)
- [Browse, covers, flags, and gallery](Browse-and-Covers.md)
- [Health and Organize](Health-and-Organize.md)
- [Review and Write](Review-and-Write.md)
- [Settings and appearance](Settings.md)
- [Showcase — animated walkthroughs](Showcase.md)
- [Troubleshooting](Troubleshooting.md)
- [1.0 release checklist](Release-1.0.md)

## Core rules

- Everything before `write` is read-only.
- `write` only changes CBZ archives and creates backups.
- CBR files are reported or converted; they are never modified in place.
- Organize previews changes before applying them.
- Cover selection changes local state; CBZ files remain untouched.
- Local, external-drive, and NAS libraries use the same user flow.

## The recommended flow

```text
open comicmeta
    ↓
choose a local drive or NAS context
    ↓
health → browse → review → organize
    ↓
inspect the proposed changes
    ↓
write only after the review is complete
```

The interactive dashboard exposes the common actions. Every command also has
a non-interactive form for scripts and batch work.

This is a safe recommendation, not a mandatory sequence. Browse whenever you
want to inspect the library; review and organize both show previews before
anything is written.
