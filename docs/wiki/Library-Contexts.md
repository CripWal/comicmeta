# Library Contexts

comicmeta supports three practical library locations:

1. A local folder on the Mac.
2. A mounted external drive or SMB share, such as `/Volumes/Comics/comics`.
3. A configured NAS context accessed over SSH.

## Local or mounted libraries

Pass the library explicitly when needed:

```sh
comicmeta health --source /Volumes/Comics/comics
comicmeta organize --source /Volumes/Comics/comics
```

You can also `cd` into a library and use the short form:

```sh
cd /Volumes/Comics/comics
comicmeta organize
```

The result should be the same regardless of the current working directory
when `--source` is provided.

## Add a NAS context

```sh
comicmeta context add nas \
  --host nas.example.local \
  --ssh-user comics \
  --library-path /path/on/nas/comics

comicmeta context use nas
```

After that, launch comicmeta from anywhere:

```sh
comicmeta
comicmeta --context nas health
comicmeta --context nas organize
```

The context owns the remote host, user, library path, SSH settings, and
execution mode. It should not depend on the directory from which the command
was launched.

## NAS execution modes

The `rsync` mode synchronizes the source and state needed for remote work. A
Docker mode is available for headless batch operations. Use the interactive
Mac dashboard for browsing and review when that is more convenient.

For large libraries, running archive-heavy work on or near the NAS avoids SMB
latency and unreliable large-file renames. The important safety rule remains
the same: inspect first, back up before writing, and apply organization changes
explicitly.

## Settings scope

Appearance preferences such as theme and cover previews are global to the Mac.
Library state such as review data and flags remains associated with the
selected library. This prevents flags from one unrelated library appearing in
another library.
