# Getting Started

## Install

On macOS, install with Homebrew:

```sh
brew tap CripWal/comicmeta
brew install comicmeta
```

Or install the Python package:

```sh
pip install comicmeta
```

comicmeta requires Python 3.11 or newer and has no required runtime
dependencies.

## First launch

Run:

```sh
comicmeta
```

The dashboard lets you choose Review, Write, Browse, Organize, or Health.
Press `c` to choose a local/NAS context, `s` for settings, `h` for help, and
`q` to quit.

On the first interactive launch, comicmeta asks whether to install `timg` for
color cover previews. This is optional and installs only on the Mac running
comicmeta. Choosing no does not block browsing or metadata work. You can
change the choice later in Settings.

## ComicVine access

Set the API key in the environment or configure a key file:

```sh
export COMICVINE_API_KEY="your-key"
comicmeta review
```

The key is not written to logs or review reports.

## First safe scan

```sh
comicmeta health --source /path/to/comics
comicmeta browse --source /path/to/comics
comicmeta organize --source /path/to/comics
```

Use the absolute path for a mounted volume. The directory where you launch
comicmeta does not have to be the library directory.
