"""comicmeta logo — print the comicmeta wordmark."""

from __future__ import annotations

import argparse

from comicmeta._common import Palette, add_examples, color_enabled, render_wordmark


def add_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "logo",
        help="print the comicmeta wordmark",
        description=__doc__,
    )
    add_examples(parser, [
        "comicmeta logo",
    ])
    parser.set_defaults(handler=run)


def run(args: argparse.Namespace) -> None:
    from comicmeta import _config
    from comicmeta._common import set_theme
    try:
        set_theme(_config.get(_config.load(getattr(args, "source", None)), "appearance.theme"))
    except Exception:
        pass
    colors = Palette(color_enabled(args))
    print(render_wordmark(colors))
