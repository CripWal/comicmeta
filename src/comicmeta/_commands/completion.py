"""comicmeta completion — generate shell completion scripts (zsh/bash)."""

from __future__ import annotations

import argparse
import shutil

from comicmeta._common import add_examples, die


def add_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "completion",
        help="generate a shell completion script (zsh or bash)",
        description=__doc__,
    )
    parser.add_argument("shell", nargs="?", choices=["zsh", "bash"], help="target shell")
    add_examples(parser, [
        "comicmeta completion zsh > ~/.zfunc/_comicmeta",
        "comicmeta completion bash > /etc/bash_completion.d/comicmeta",
    ])
    parser.set_defaults(handler=run)


def _commands() -> list[str]:
    from comicmeta.cli import build_parser
    parser = build_parser()
    return sorted(parser._subparsers._group_actions[0].choices)


def _flags(command: str) -> list[str]:
    from comicmeta.cli import build_parser
    parser = build_parser()
    choices = parser._subparsers._group_actions[0].choices
    if command not in choices:
        return []
    sub = choices[command]
    flags = []
    for action in sub._actions:
        for opt in action.option_strings:
            flags.append(opt)
    return flags


def _zsh() -> str:
    cmds = _commands()
    cmd_list = " ".join(cmds)
    lines = [
        "#compdef comicmeta",
        f"_comicmeta() {{",
        f"  local -a commands",
        f"  commands=({cmd_list})",
        f"  if (( CURRENT == 2 )); then",
        f"    _describe 'command' commands",
        f"  else",
        f"    local cmd=$words[2]",
        f"    local -a flags",
        f"    case $cmd in",
    ]
    for cmd in cmds:
        flags = _flags(cmd)
        if flags:
            flag_list = " ".join(f"'{f}'" for f in flags)
            lines.append(f"      {cmd}) flags=({flag_list}) ;;")
    lines += [
        "      *) return 0 ;;",
        "    esac",
        "    _arguments '*:option:->flags'",
        "    _describe 'flag' flags",
        "  fi",
        "}",
        "_comicmeta \"$@\"",
    ]
    return "\n".join(lines) + "\n"


def _bash() -> str:
    cmds = _commands()
    cmd_list = " ".join(cmds)
    lines = [
        f"_comicmeta_completions() {{",
        f"  local cur=\"${{COMP_WORDS[COMP_CWORD]}}\"",
        f"  if [ \"$COMP_CWORD\" -eq 1 ]; then",
        f"    COMPREPLY=( $(compgen -W \"{cmd_list}\" -- \"$cur\") )",
        f"  else",
        f"    local cmd=\"${{COMP_WORDS[1]}}\"",
        f"    local flags",
        f"    case \"$cmd\" in",
    ]
    for cmd in cmds:
        flags = _flags(cmd)
        if flags:
            flag_list = " ".join(flags)
            lines.append(f"      {cmd}) flags=\"{flag_list}\" ;;")
    lines += [
        "      *) return 0 ;;",
        "    esac",
        "    COMPREPLY=( $(compgen -W \"$flags\" -- \"$cur\") )",
        "  fi",
        "}",
        "complete -F _comicmeta_completions comicmeta",
    ]
    return "\n".join(lines) + "\n"


def run(args: argparse.Namespace) -> None:
    shell = args.shell or ("zsh" if shutil.which("zsh") else "bash")
    if shell == "zsh":
        print(_zsh(), end="")
    else:
        print(_bash(), end="")
