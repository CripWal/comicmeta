"""comicmeta update-check — check whether a newer version is available.

The package is not yet published to PyPI, so this checks PyPI and reports
'not published' when no release exists. Designed to become an update-notifier
style hint once a release is published.
"""

from __future__ import annotations

import argparse
import json
import urllib.request

import comicmeta
from comicmeta._common import add_examples


def add_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "update-check",
        help="check whether a newer comicmeta version is available",
        description=__doc__,
    )
    parser.add_argument("--timeout", type=int, default=5, help="network timeout in seconds")
    add_examples(parser, [
        "comicmeta update-check",
    ])
    parser.set_defaults(handler=run)

def latest_version(timeout: int = 5) -> str | None:
    """Query PyPI for the latest version. Returns None if not published/unreachable."""
    request = urllib.request.Request(
        "https://pypi.org/pypi/comicmeta/json",
        headers={"User-Agent": f"comicmeta/{comicmeta.__version__}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except Exception:
        return None
    return payload.get("info", {}).get("version")


def run(args: argparse.Namespace) -> None:
    latest = latest_version(args.timeout)
    current = comicmeta.__version__
    if latest is None:
        print(f"UPDATE_CHECK unknown (package not published or unreachable); current={current}")
        return
    if latest == current:
        print(f"UPDATE_CHECK up-to-date version={current}")
    else:
        print(f"UPDATE_CHECK available current={current} latest={latest}")
        print("  Run `brew upgrade comicmeta` to update.")
