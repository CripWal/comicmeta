"""comicmeta self-test — smoke-test the environment and configuration."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import comicmeta
from comicmeta import _config
from comicmeta._common import add_examples


def add_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "self-test",
        help="check the environment and configuration",
        description=__doc__,
    )
    parser.add_argument("--source", "-s", type=Path, help="library root to check against")
    add_examples(parser, [
        "comicmeta self-test",
        "comicmeta self-test -s /path/to/comics",
    ])
    parser.set_defaults(handler=run)


def run(args: argparse.Namespace) -> None:
    checks = []
    ok = True

    print("▸ SELF-TEST")
    print()

    checks.append(("python", f"{sys.version.split()[0]} (need >= 3.11)", sys.version_info >= (3, 11)))
    checks.append(("comicmeta", comicmeta.__version__, True))

    try:
        import termios  # noqa: F401
        checks.append(("termios", "available (arrow keys + hidden input)", True))
    except ImportError:
        checks.append(("termios", "unavailable (arrow keys disabled)", False))

    try:
        import tomllib  # noqa: F401
        checks.append(("tomllib", "available (TOML settings)", True))
    except ImportError:
        checks.append(("tomllib", "unavailable (TOML settings broken)", False))

    settings_path = _config.find_settings(args.source)
    checks.append(("settings", str(settings_path) if settings_path else "none (built-in defaults)", True))
    if settings_path:
        try:
            _config.load(args.source, settings_path)
            checks.append(("settings parse", "valid TOML", True))
        except SystemExit:
            checks.append(("settings parse", "invalid TOML", False))

    for name, detail, passed in checks:
        mark = "✓" if passed else "✗"
        print(f"{mark} {name}: {detail}")
        ok = ok and passed

    print(f"\nRESULT {'PASS' if ok else 'FAIL'}")
    raise SystemExit(0 if ok else 1)
