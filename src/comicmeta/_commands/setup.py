"""comicmeta setup — configure optional cover previews on the active context."""

from __future__ import annotations

import argparse


def add_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "setup",
        help="configure optional cover previews (installs timg or chafa as needed)",
        description=__doc__,
    )
    parser.set_defaults(handler=run)


def run(args: argparse.Namespace) -> None:
    from comicmeta._common import Palette, color_enabled
    from comicmeta.cli import _configure_cover_previews
    _configure_cover_previews(Palette(color_enabled()))
