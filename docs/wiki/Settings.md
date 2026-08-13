# Settings and Appearance

Open Settings from the dashboard with `s` or run:

```sh
comicmeta settings
```

The primary screen is intentionally small:

```text
APPEARANCE
CONNECTIONS
ADVANCED
```

## Primary settings

Appearance includes:

- Color output.
- Dashboard visibility.
- Theme.
- Cover previews.

The title, wordmark, status indicators, and settings panel use the selected
theme. Theme preferences are global to the Mac, so changing directories or
switching library contexts does not reset the appearance.

Connections begin as compact summaries. Press Enter on one to expand and edit
its host, library path, SSH user, port, identity file, timeout, or execution
mode. Press Enter on `Add connection…` to start the guided setup.

## Advanced settings

Press `a` to show API, paths, review, and write-safety settings. This keeps
internal state paths and sensitive controls out of the normal user flow.

Search filters the visible settings. The selected row is preserved when the
list is rebuilt after searching, expanding a connection, toggling Advanced, or
editing a value.

## Configuration files

Library configuration may live in `comicmeta.toml`. Global appearance defaults
are stored in the user configuration directory. State files are keyed to the
library so separate libraries do not share review state or flags by accident.

For command-line configuration:

```sh
comicmeta settings --init
comicmeta settings --set api.request_delay=0.5
comicmeta settings --set review.high_confidence_score=80
```
