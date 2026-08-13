# Troubleshooting

## The screen looks blank after opening Health or Organize

The command may have printed a long report and then redrawn the dashboard.
Run the command directly to keep the complete output visible:

```sh
comicmeta health --source /path/to/comics
comicmeta organize --source /path/to/comics
```

The dashboard now presents Organize's dry-run output before asking whether to
apply it.

## Pressing a footer key does nothing

Footer commands are screen-specific. Read the footer on the current screen;
`f` in Browse flags the selected item, while `f` in Review may mean a fresh
review. In settings, use arrow keys and Enter; `a` toggles Advanced and `q`
returns.

## Covers are grayscale, missing, or the gallery is empty

Check Settings → Cover previews. If the renderer is not installed, allow the
first-run `timg` installation or install it manually:

```sh
brew install timg
```

Gallery is available for a series, not as a general issue-level screen.
Numeric story pages are not alternate covers unless the archive contains a
clearly named cover candidate.

## NAS commands use the wrong folder

Confirm the active context and its library path:

```sh
comicmeta context ls
comicmeta context use nas
comicmeta --context nas status
```

You can run the command from any local directory. For a mounted share, pass an
absolute `--source` path instead of relying on the current directory.

## Theme or settings appear different in another directory

Appearance is global, but library state is intentionally scoped per library.
Confirm that the command is using the expected context or `--source` path.
Run `comicmeta settings` and check the file path shown at the bottom of the
panel.

## Health reports incomplete metadata

Incomplete means a required metadata field is missing; it does not necessarily
mean the archive is corrupt. Inspect the issue in Browse, then repair it
through the reviewed metadata workflow rather than editing CBZ files manually.
