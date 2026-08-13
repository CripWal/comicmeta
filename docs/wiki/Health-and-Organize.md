# Health and Organize

## Health

Health checks archives and metadata without modifying the library:

```sh
comicmeta health --source /path/to/comics
```

The report distinguishes:

- Corrupt archives.
- Archives without metadata.
- Incomplete metadata.
- Structural issues that require a naming or folder decision.

An incomplete record is not automatically a corrupt file. For example, a CBZ
can be readable while still missing a format field in `ComicInfo.xml`.

## Organize

Organize has two stages:

```sh
comicmeta organize --source /path/to/comics
comicmeta organize --source /path/to/comics --execute
```

The first command is a dry run. It reports proposed folder and filename
normalization. In the interactive dashboard, the same dry run is shown first;
press `e` only after reviewing the proposal to apply it.

## Naming target

The standard target is a series folder with its starting year, followed by
normalized issue names. A common shape is:

```text
Publisher/Series Name (Starting Year)/Series Name (Starting Year) #001.cbz
```

Collection formats use a volume suffix instead of an issue number:

```text
Publisher/Daredevil Omnibus (2017)/Daredevil Omnibus (2017) Vol. 01.cbz
```

Collected editions without a volume number remain manual-review items.

Organize should never overwrite an existing destination. Review collisions and
manual-review items before applying anything.
