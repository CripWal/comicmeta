"""Subcommand registration for the comicmeta CLI."""

from __future__ import annotations

import argparse

from comicmeta._commands import (
    backups,
    browse,
    completion,
    convert,
    context,
    covers,
    discover,
    fetch_issues,
    flags,
    health,
    help,
    inspect,
    logo,
    mapping,
    missing,
    organize,
    review,
    review_issues,
    review_volumes,
    self_test,
    setup,
    settings,
    stage,
    status,
    update_check,
    validate,
    write,
)


def register(subparsers: argparse._SubParsersAction) -> None:
    for module in (
        review,
        discover,
        review_volumes,
        fetch_issues,
        review_issues,
        mapping,
        stage,
        validate,
        write,
        status,
        settings,
        covers,
        self_test,
        setup,
        update_check,
        logo,
        inspect,
        organize,
        browse,
        convert,
        backups,
        flags,
        health,
        missing,
        context,
        help,
        completion,
    ):
        module.add_parser(subparsers)
