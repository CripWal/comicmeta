"""comicmeta help — show help for a command (git-style `help subcommand`)."""

from __future__ import annotations

import argparse

from comicmeta._common import add_examples, die


def add_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "help",
        help="show help for a command (alias for COMMAND --help)",
        description=__doc__,
    )
    parser.add_argument("command", nargs="?", help="command name to show help for")
    add_examples(parser, [
        "comicmeta help",
        "comicmeta help write",
        "comicmeta help context",
    ])
    parser.set_defaults(handler=run)


def run(args: argparse.Namespace) -> None:
    from comicmeta.cli import build_parser
    parser = build_parser()
    if args.command is None:
        parser.print_help()
        return
    subparsers = parser._subparsers._group_actions[0]
    if args.command not in subparsers.choices:
        die(f"unknown command: {args.command}; run `comicmeta help` to list commands")
    subparsers.choices[args.command].print_help()
