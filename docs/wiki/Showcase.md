# Showcase

Animated terminal recordings of the comicmeta UI. They are **SVG with CSS
animations** — open in any browser to play; no video, no JS, selectable text.

Open each in its own tab to watch it move:

## Dashboard — arrow-key navigation

<img src="https://raw.githubusercontent.com/CripWal/comicmeta/main/docs/showcase/menu.svg" alt="Dashboard navigation" width="680">

## Browse — expand the library tree and open an issue card

<img src="https://raw.githubusercontent.com/CripWal/comicmeta/main/docs/showcase/browse.svg" alt="Browse the library tree" width="680">

## Browse an issue — cover art preview

<img src="https://raw.githubusercontent.com/CripWal/comicmeta/main/docs/showcase/browse-cover.svg" alt="Browse with cover art" width="680">

## Volume review — scroll ComicVine candidates and accept

<img src="https://raw.githubusercontent.com/CripWal/comicmeta/main/docs/showcase/review.svg" alt="Volume review" width="680">

## Review flow — CBR warning, convert picker, volume review

<img src="https://raw.githubusercontent.com/CripWal/comicmeta/main/docs/showcase/review-convert.svg" alt="Review with convert picker" width="680">

## Settings panel

<img src="https://raw.githubusercontent.com/CripWal/comicmeta/main/docs/showcase/settings.svg" alt="Settings panel" width="680">

## How these were made

1. **Record** an interactive session with [`termsvg`](https://github.com/MrMarble/termsvg)
   (asciicast v2 format), driven through a tmux pane so the TUI receives a real TTY:

   ```sh
   termsvg rec menu.cast -c "sh -c 'cd <library> && comicmeta'"
   # then drive the UI with tmux send-keys
   ```

2. **Render** the cast with a [termframe fork](https://github.com/CripWal/termframe)
   (branch `feat/cast-animation`) that replays recordings and reuses termframe's
   macOS-window + everblush styling:

   ```sh
   termframe --cast menu.cast -o menu.svg \
     --window-style macos --theme everblush --title "comicmeta" \
     --max-idle 2500
   ```

   Options: `--frame-interval MS` (snapshot granularity), `--max-idle MS`
   (how long each screen holds before advancing).

3. **Embed** on GitHub with a normal Markdown image tag — animated SVGs play
   when loaded as `<img>`, so `![menu](docs/showcase/menu.svg)` just works in
   the README and (via raw GitHub URLs) the wiki.

The static screens (`docs/showcase/dashboard.svg`, `health.svg`, …) come from
stock termframe: `termframe --window-style macos --theme everblush --title "comicmeta" -- comicmeta health`.
