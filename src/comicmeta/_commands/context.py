"""comicmeta context — manage NAS contexts.

Create, switch between, list, edit, and remove NAS contexts. The local context
is implicit and always available.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from comicmeta import _context
from comicmeta._context import Context
from comicmeta._common import Palette, add_examples, color_enabled, die
from comicmeta._tui import prompt_edit


def add_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "context",
        help="manage NAS contexts",
        description="Manage NAS contexts for remote execution.",
    )
    ctx_subparsers = parser.add_subparsers(dest="ctx_command", metavar="COMMAND")

    add_p = ctx_subparsers.add_parser("add", help="add a new NAS context")
    add_p.add_argument("name", nargs="?", help="context name")
    add_p.add_argument("--host", help="NAS hostname or IP")
    add_p.add_argument("--ssh-user", help="SSH username")
    add_p.add_argument("--ssh-port", type=int, default=22, help="SSH port (default: 22)")
    add_p.add_argument("--identity-file", help="SSH identity file (default: ~/.ssh keys)")
    add_p.add_argument("--connect-timeout", type=int, default=10, help="SSH connect timeout in seconds (default: 10)")
    add_p.add_argument("--library-path", help="library path on the NAS")
    add_p.add_argument(
        "--exec", choices=["docker", "rsync"], default="rsync",
        help="execution method",
    )
    add_p.add_argument(
        "--image", default="comicmeta:latest", help="Docker image name",
    )
    add_p.add_argument(
        "--nas-src", default="~/comicmeta",
        help="source directory on NAS for rsync",
    )
    add_p.add_argument(
        "--config-dir", default="~/.config/comicmeta",
        help="config directory on NAS holding comicmeta config + API key",
    )
    add_p.add_argument(
        "--key-location", default="~/.config/comicmeta/comicvine.key",
        help="path on the NAS where the ComicVine API key is stored",
    )
    add_p.set_defaults(handler=_add)

    use_p = ctx_subparsers.add_parser("use", help="set the active context")
    use_p.add_argument("name", help="context name or 'local'")
    use_p.set_defaults(handler=_use)

    ls_p = ctx_subparsers.add_parser("ls", help="list contexts")
    ls_p.add_argument("--json", action="store_true", help="output as JSON (machine-readable)")
    ls_p.set_defaults(handler=_ls)

    edit_p = ctx_subparsers.add_parser("edit", help="edit a context")
    edit_p.add_argument("name", help="context name")
    edit_p.add_argument("--host", help="NAS hostname or IP")
    edit_p.add_argument("--ssh-user", help="SSH username")
    edit_p.add_argument("--ssh-port", type=int, help="SSH port")
    edit_p.add_argument("--identity-file", help="SSH identity file")
    edit_p.add_argument("--connect-timeout", type=int, help="SSH connect timeout in seconds")
    edit_p.add_argument("--library-path", help="library path on the NAS")
    edit_p.add_argument(
        "--exec", choices=["docker", "rsync"], help="execution method",
    )
    edit_p.add_argument("--image", help="Docker image name")
    edit_p.add_argument("--nas-src", help="source directory on NAS for rsync")
    edit_p.add_argument("--config-dir", help="config directory on NAS holding comicmeta config + API key")
    edit_p.add_argument("--key-location", help="path on the NAS where the ComicVine API key is stored")
    edit_p.add_argument(
        "--sync", action="store_true",
        help="re-sync the comicmeta source to the NAS (rsync contexts)",
    )
    edit_p.set_defaults(handler=_edit)

    rm_p = ctx_subparsers.add_parser("remove", help="remove a context")
    rm_p.add_argument("name", help="context name")
    rm_p.set_defaults(handler=_remove)

    add_examples(parser, [
        "comicmeta context add nas --host nas.example.com --ssh-user alice --library-path /srv/comics",
        "comicmeta context use nas",
        "comicmeta context ls",
        "comicmeta context edit nas --host nas.example.com",
        "comicmeta context edit nas --sync  # re-sync source after editing",
        "comicmeta context remove nas",
    ])
    parser.set_defaults(handler=run)


def run(args: argparse.Namespace) -> None:
    if not getattr(args, "ctx_command", None):
        die("usage: comicmeta context {add,use,ls,edit,remove}")
    args.handler(args)


def _step(colors: Palette, current: int, total: int, label: str) -> None:
    """Print a step header with a dashed rule."""
    width = shutil.get_terminal_size((60, 24)).columns
    rule = "─" * max(10, width - 4)
    print(f"\n  {colors.title(f'Step {current} of {total}')}  {colors.bold(label)}")
    print(f"  {colors.muted(rule)}")


def _prompt_non_empty(colors: Palette, label: str) -> str:
    """Prompt until a non-empty value is given."""
    while True:
        value = prompt_edit(f"  {label}: ")
        if value is None:
            print(colors.warn("  (cancelled)"))
            raise SystemExit(1)
        stripped = value.strip()
        if stripped:
            return stripped
        print(colors.warn("  Required — please enter a value."))


def _interactive_add(name: str | None) -> Context:
    colors = Palette(color_enabled())
    print(colors.title("▸ ADD NAS CONTEXT"))
    print(colors.muted("  Connect to a NAS and run comicmeta commands remotely."))

    _step(colors, 1, 5, "Name")
    if not name:
        name = _prompt_non_empty(colors, "Context name")

    _step(colors, 2, 5, "Host")
    host = _prompt_non_empty(colors, "NAS hostname or IP")

    _step(colors, 3, 5, "SSH user")
    ssh_user = _prompt_non_empty(colors, "SSH username")

    _step(colors, 4, 5, "Library path")
    library_path = _prompt_non_empty(colors, "Library path on NAS")

    _step(colors, 5, 5, "Execution method")
    print(f"  [1] {colors.bold('Docker')}    — build container on the NAS (requires docker group)")
    print(f"  [2] {colors.bold('rsync-source')} — copy source + use NAS Python (recommended)")
    choice = input("  Enter 1 or 2 [2]: ").strip() or "2"
    exec_method = "docker" if choice == "1" else "rsync"

    ctx = Context(
        name=name,
        host=host,
        ssh_user=ssh_user,
        library_path=library_path,
        exec=exec_method,
    )
    ctx.apply_nas_defaults()
    # Optional SSH connection settings (advanced).
    ssh_port = prompt_edit("  SSH port [22]: ", current="22")
    if ssh_port and ssh_port.strip() and ssh_port.strip() != "22":
        ctx.ssh_port = int(ssh_port.strip())
    identity_file = prompt_edit("  SSH identity file (blank to use default keys): ")
    if identity_file and identity_file.strip():
        ctx.identity_file = identity_file.strip()
    connect_timeout = prompt_edit("  SSH connect timeout in seconds [10]: ", current="10")
    if connect_timeout and connect_timeout.strip() and connect_timeout.strip() != "10":
        ctx.connect_timeout = int(connect_timeout.strip())

    # Connection test
    print(f"\n  {colors.muted('─' * 40)}")
    print(f"  {colors.title('Connection test')}  {ssh_user}@{host}")
    ok, message = _context.test_connection(ctx)
    if ok:
        print(f"  {colors.good('✓ Connected.')} {message}")
    else:
        print(f"  {colors.warn('✗ Connection failed.')}")
        print(f"  {colors.warn(message)}")
        print(f"\n  {colors.muted('Fix the issue, then run:')}")
        print(f"    {colors.muted(f'comicmeta context edit {name}')}  {colors.muted('to update host/user, then rerun context add.')}")
        raise SystemExit(1)

    # API key
    print(f"\n  {colors.muted('─' * 40)}")
    print(f"  {colors.title('ComicVine API key')}  (stored on NAS, not locally)")
    existing = [c for c in _context.list_contexts() if c.name != name]
    api_key = None
    if existing:
        print(f"  {colors.muted('Other contexts: ' + ', '.join(c.name for c in existing))}")
        reuse = input("  Copy the key from an existing context? [y/N]: ").strip().lower()
        if reuse in ("y", "yes"):
            api_key = _copy_api_key_from(existing, colors)
        if not api_key:
            api_key = prompt_edit("  API key: ", secret=True)
    else:
        api_key = prompt_edit("  API key: ", secret=True)
    if api_key and api_key.strip():
        ctx._api_key = api_key.strip()  # ephemeral, written to NAS config then dropped

    # Exec-specific setup
    print(f"\n  {colors.muted('─' * 40)}")
    if exec_method == "rsync":
        print(f"  {colors.title('Syncing source')}  to {ctx.nas_src} on NAS …")
        from comicmeta._executors import get_executor
        executor = get_executor(ctx)
        ok, message = executor.sync_source()
        if ok:
            print(f"  {colors.good('✓')} {message}")
        else:
            print(f"  {colors.warn('✗ Sync failed.')}")
            print(f"  {colors.warn(message)}")
            print(f"\n  {colors.muted('You can retry later with:')}")
            print(f"    {colors.muted(f'comicmeta context edit {name} --exec rsync')}")
            # Don't abort; the context is still valid, just missing source
    else:
        print(f"  {colors.title('Building Docker image')}  {ctx.image} on NAS …")
        from comicmeta._executors import get_executor
        executor = get_executor(ctx)
        ok, message = executor.build_image()
        if ok:
            print(f"  {colors.good('✓')} {message}")
        else:
            print(f"  {colors.warn('✗ Build failed.')}")
            print(f"  {colors.warn(message)}")
            print(f"\n  {colors.muted('You can switch to rsync-source with:')}")
            print(f"    {colors.muted(f'comicmeta context edit {name} --exec rsync')}")

    # Summary
    print(f"\n  {colors.muted('─' * 40)}")
    print(f"  {colors.bold('Summary')}")
    print(f"    name:      {colors.title(name)}")
    print(f"    host:      {host}")
    print(f"    user:      {ssh_user}")
    print(f"    library:   {library_path}")
    print(f"    exec:      {exec_method}")
    print(f"  {colors.muted('─' * 40)}")

    return ctx


def _copy_api_key_from(existing: list, colors: Palette) -> str | None:
    """Let the user pick an existing context and return its NAS-stored API key.

    Reads the key from the chosen context's NAS (`key_location`) so it can be
    reused on a new NAS without retyping it. Returns None if no key is found.
    """
    for i, ctx in enumerate(existing, 1):
        print(f"    [{i}] {colors.bold(ctx.name)}  ({ctx.ssh_user}@{ctx.host})")
    choice = input("  Pick a context to copy its key from: ").strip()
    try:
        source = existing[int(choice) - 1]
    except (ValueError, IndexError):
        print(colors.warn("  Invalid choice; enter the key manually."))
        return None
    print(f"  Reading key from '{source.name}' …")
    import subprocess
    import shlex
    key_path = str(source.key_location or "~/.config/comicmeta/comicvine.key")
    token = key_path if key_path.startswith("~/") else shlex.quote(key_path)
    remote = f"cat {token}"
    cmd = ["ssh"] + source.ssh_flags() + [source.ssh_target(), remote]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    except Exception as exc:
        print(colors.warn(f"  Could not reach '{source.name}': {exc}"))
        return None
    if result.returncode != 0 or not result.stdout.strip():
        print(colors.warn(f"  No key found on '{source.name}' at {key_path}"))
        return None
    return result.stdout.strip()


def _write_api_key_to_nas(ctx: Context, api_key: str) -> tuple[bool, str]:
    """Write the API key to the NAS comicmeta config via SSH, using ctx.key_location."""
    import subprocess
    import shlex
    key_path = ctx.key_location or "~/.config/comicmeta/comicvine.key"

    def remote_token(value: str) -> str:
        # Leave `~/` unquoted so the remote shell expands `~`; quote the rest.
        if value.startswith("~/"):
            return value
        return shlex.quote(value)

    key_dir = str(key_path).rsplit("/", 1)[0] or "~/.config/comicmeta"
    remote = (
        f"mkdir -p {remote_token(key_dir)} "
        f"&& echo {shlex.quote(api_key)} > {remote_token(str(key_path))} "
        f"&& chmod 600 {remote_token(str(key_path))}"
    )
    cmd = ["ssh"] + ctx.ssh_flags() + [ctx.ssh_target(), remote]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    except Exception as exc:
        return False, str(exc)
    if result.returncode != 0:
        return False, result.stderr.strip() or f"exit {result.returncode}"
    return True, f"API key saved to {key_path} on NAS"


def _add(args: argparse.Namespace) -> None:
    colors = Palette(color_enabled())
    name = args.name
    if not name or not args.host:
        ctx = _interactive_add(name)
    else:
        ctx = Context(
            name=name,
            host=args.host,
            ssh_user=args.ssh_user or "",
            ssh_port=args.ssh_port,
            identity_file=args.identity_file or "",
            connect_timeout=args.connect_timeout,
            library_path=args.library_path or "",
            exec=args.exec,
            image=args.image,
            nas_src=args.nas_src,
            config_dir=args.config_dir,
            key_location=args.key_location,
        )
        ctx.apply_nas_defaults()
    _context.save_context(ctx)

    # If we have an ephemeral API key, write it to the NAS
    ephemeral_key = ctx._api_key or None
    if ephemeral_key:
        ok, msg = _write_api_key_to_nas(ctx, ephemeral_key)
        if ok:
            print(f"  {colors.good('✓')} {msg}")
        else:
            print(f"  {colors.warn('✗ API key setup failed:')} {msg}")

    print(f"\n  {colors.good('✓')} Context '{ctx.name}' created.")

    # Offer to set as active
    if sys.stdin.isatty():
        response = input(f"  Set as active context? [Y/n]: ").strip().lower()
    else:
        response = "y"
    if response in ("", "y", "yes"):
        _context.set_active_context(ctx.name)
        print(f"  {colors.good('✓')} Active context is now '{ctx.name}'.")
    else:
        print(f"  {colors.muted('Context created but not active. Switch later with:')}")
        cmd = "comicmeta context use " + ctx.name
        print(f"    {colors.muted(cmd)}")


def _use(args: argparse.Namespace) -> None:
    _context.set_active_context(args.name)
    print(f"Active context is now '{args.name}'.")


def _ls(args: argparse.Namespace) -> None:
    contexts = _context.list_contexts()
    active = _context.active_context()
    active_name = active.name
    if getattr(args, "json", False):
        import json
        payload = {
            "active": active_name,
            "contexts": [c.to_dict() for c in contexts],
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    if not contexts:
        print(f"Active: {active_name}")
        print("No contexts configured.")
        return
    print(f"Active: {active_name}")
    for ctx in contexts:
        marker = "▸ " if ctx.name == active_name else "  "
        print(
            f"{marker}{ctx.name}  {ctx.host}  "
            f"{ctx.library_path}  ({ctx.exec})"
        )


def _edit(args: argparse.Namespace) -> None:
    ctx = _context.load_context(args.name)
    if ctx is None:
        die(f"context not found: {args.name}")
    for key in ("host", "ssh_user", "ssh_port", "identity_file", "connect_timeout", "library_path", "exec", "image", "nas_src", "config_dir", "key_location"):
        val = getattr(args, key.replace("-", "_"))
        if val is not None:
            setattr(ctx, key, val)
    ctx.apply_nas_defaults()
    _context.save_context(ctx)
    print(f"Context '{args.name}' updated.")
    if getattr(args, "sync", False):
        from comicmeta._executors import get_executor
        executor = get_executor(ctx)
        ok, message = executor.sync_source()
        if ok:
            print(f"  {Palette(color_enabled()).good('✓')} {message}")
        else:
            print(f"  {Palette(color_enabled()).warn('✗ Sync failed:')}")
            print(f"  {Palette(color_enabled()).warn(message)}")


def _remove(args: argparse.Namespace) -> None:
    existed = _context.remove_context(args.name)
    if existed:
        print(f"Context '{args.name}' removed.")
    else:
        print(f"Context '{args.name}' not found.")
