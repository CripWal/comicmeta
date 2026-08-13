"""comicmeta settings — view and edit the comicmeta.toml configuration."""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from comicmeta import _config
from comicmeta._common import add_examples, die


def add_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "settings",
        help="view or edit comicmeta.toml configuration",
        description=__doc__,
    )
    parser.add_argument("--source", type=Path, help="library root to resolve settings for")
    parser.add_argument("--config", type=Path, help="explicit settings file path")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--init", action="store_true", help="scaffold a comicmeta.toml in the current directory")
    action.add_argument("--set", metavar="KEY=VALUE", help="set a setting (e.g. api.request_delay=0.5)")
    action.add_argument("--describe", metavar="KEY", help="explain what a setting does (e.g. api.request_delay)")
    add_examples(parser, [
        "comicmeta settings",
        "comicmeta settings --init",
        "comicmeta settings --set api.request_delay=0.5",
        "comicmeta settings --describe api.key_file",
    ])
    parser.set_defaults(handler=run)


def _toml_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        if not value:
            return "{}"
        parts = ", ".join(f"{key!r} = {_toml_value(item)}" for key, item in value.items())
        return "{ " + parts + " }"
    return repr(str(value))


def _toml_for(flat: dict) -> str:
    lines = ["# comicmeta configuration", ""]
    for section, values in _config.DEFAULTS.items():
        lines.append(f"[{section}]")
        for key in values:
            full = f"{section}.{key}"
            description = _config.SETTINGS_DESCRIPTIONS.get(full)
            if description:
                lines.append(f"# {description}")
            value = flat.get(f"{section}.{key}", values[key])
            lines.append(f"{key} = {_toml_value(value)}")
        lines.append("")
    return "\n".join(lines)


def _write_toml(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        temporary = Path(handle.name)
    temporary.replace(path)


def _init(args: argparse.Namespace) -> None:
    target = args.config or Path.cwd() / _config.SETTINGS_FILENAME
    if target.exists():
        die(f"settings already exist: {target}")
    # Initialize from defaults plus any existing config file that is readable.
    flat = dict(_config.FLAT_DEFAULTS)
    existing = args.config if args.config and args.config.is_file() else _config.find_settings(args.source)
    if existing is not None and existing != target:
        flat.update(_config.load(args.source, existing))
    _write_toml(target, _toml_for(flat))
    print(f"WROTE settings={target}")


def _set(args: argparse.Namespace) -> None:
    if "=" not in args.set:
        die("--set expects KEY=VALUE, e.g. api.request_delay=0.5")
    key, value = args.set.split("=", 1)
    target = args.config or (find_in_cwd() or Path.cwd() / _config.SETTINGS_FILENAME)
    # Load from the target if it exists, otherwise defaults.
    flat = dict(_config.FLAT_DEFAULTS)
    if target.is_file():
        flat.update(_config.load(None, target))
    _config.set_key(flat, key, value)
    _write_toml(target, _toml_for(flat))
    print(f"SET {key}={value!r} settings={target}")


def find_in_cwd() -> Path | None:
    path = Path.cwd() / _config.SETTINGS_FILENAME
    return path if path.is_file() else None


def settings_target() -> Path:
    user = _config.user_settings_path()
    return find_in_cwd() or (user if user.is_file() else Path.cwd() / _config.SETTINGS_FILENAME)


def load_flat() -> dict:
    """Resolved flat settings merged from the target file over defaults."""
    target = settings_target()
    flat = dict(_config.FLAT_DEFAULTS)
    if target.is_file():
        flat.update(_config.load(None, target))
    return flat


def write_flat(flat: dict, target: Path | None = None) -> Path:
    target = target or settings_target()
    _write_toml(target, _toml_for(flat))
    return target


def set_key_silent(key: str, value, target: Path | None = None) -> None:
    """Validate and write a single key without printing."""
    target = target or settings_target()
    flat = dict(_config.FLAT_DEFAULTS)
    if target.is_file():
        flat.update(_config.load(None, target))
    if isinstance(value, dict):
        import json as _json
        _config.set_key(flat, key, _json.dumps(value))
    else:
        _config.set_key(flat, key, str(value))
    write_flat(flat, target)


def _describe(key: str) -> None:
    if key not in _config.FLAT_DEFAULTS:
        die(
            f"unknown setting: {key}; valid keys:\n  " +
            "\n  ".join(sorted(_config.FLAT_DEFAULTS))
        )
    label, kind = _config.SETTINGS_META.get(key, (key, "str"))
    print(f"{key}")
    print(f"  {label}")
    print(f"  {_config.SETTINGS_DESCRIPTIONS.get(key, '(no description)')}")
    default = _config.FLAT_DEFAULTS[key]
    print(f"  default: {default!r}")


def run(args: argparse.Namespace) -> None:
    if args.init:
        _init(args)
        return
    if args.set:
        _set(args)
        return
    if args.describe:
        _describe(args.describe)
        return
    flat = _config.load(args.source, args.config)
    print(_config.render(flat))
    settings_path = args.config or _config.find_settings(args.source)
    if settings_path:
        print(f"\n# file: {settings_path}")
    else:
        print("\n# no settings file; using built-in defaults")
