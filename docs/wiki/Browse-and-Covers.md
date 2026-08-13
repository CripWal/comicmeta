# Browse, Covers, Flags, and Gallery

Browse is the visual library surface. It is a file tree by default and does
not modify CBZ archives just by viewing them.

## Browse flow

```sh
comicmeta browse --source /path/to/comics
```

Use the arrow keys to move through folders and files. Press Enter to open a
series or inspect an issue. The footer shows the commands available on the
current screen.

At the issue level:

| Key | Action |
|---|---|
| `↑` / `↓` | Previous or next issue |
| `←` / `b` | Back |
| `e` | Edit metadata |
| `f` | Flag or unflag the issue |
| `a` | Choose a named alternate cover |
| `g` | Open the series cover gallery |
| `q` | Back/quit the current view |

Flags are research markers. They do not write ComicInfo metadata.

## Cover previews

Cover previews are optional. On macOS, the first-run setup can install `timg`
with Homebrew. Settings remembers the choice globally:

```text
Settings → Cover previews
```

If previews are disabled or no renderer is available, browse remains usable as
a text interface and tells you how to enable previews.

## Gallery

Gallery is a series-level view. It shows the covers available across that
series and is not a replacement for the issue file browser.

## Alternate covers

The alternate-cover action only offers explicitly named cover candidates, such
as files containing `cover`, `front`, `variant`, `alternate`, or `alt` in the
name. Ordinary story pages are not presented as alternate covers.

Selecting a cover changes comicmeta's local cover-selection state. It does not
rewrite the CBZ archive or alter the image files.
