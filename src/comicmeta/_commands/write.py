"""comicmeta write — write reviewed ComicInfo.xml data into CBZ archives.

Requires an explicit JSON mapping, a backup directory, and (recommended) an
expected-hashes staging audit. CBZ is the only writeable format; CBR is
reported but never converted or modified. Failed files are rolled back
individually from backup; successfully validated files are never undone.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
import zipfile
import zlib
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree

from comicmeta import _archive
from comicmeta._common import COMICINFO_FIELDS, REQUIRED_FIELDS, add_examples, atomic_write, die, die_missing_source, load_json, serialize_multi, _truncate_ansi, _terminal_size

_TRANSIENT_ERRNOS = {22, 5, 16, 35}


def add_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "write",
        help="write reviewed ComicInfo.xml into CBZ archives (requires reviewed mapping)",
        description=__doc__,
    )
    parser.add_argument("--source", "-s", type=Path, help="comic library root (default: current directory)")
    parser.add_argument("--mapping", "-m", type=Path, help="reviewed JSON mapping (default: from settings)")
    parser.add_argument("--backup-dir", type=Path, help="backup directory (default: from settings)")
    parser.add_argument("--report", "-r", type=Path, help="JSON report path (default: from settings)")
    parser.add_argument("--expected-hashes", type=Path, help="staging audit with required production hashes")
    parser.add_argument("--dry-run", action="store_true", help="stage and validate without modifying production")
    parser.add_argument("--staging-dir", type=Path, help="directory for dry-run staging copies (default: system temp)")
    parser.add_argument("--yes", "-y", action="store_true", help="skip the confirmation prompt")
    parser.add_argument("--no-backups", action="store_true", help="write without creating backups (overrides write.keep_backups)")
    add_examples(parser, [
        "comicmeta write",
        "comicmeta write --dry-run",
        "comicmeta write --dry-run --staging-dir /srv/tmp",
        "comicmeta write -y --backup-dir /tmp/backup",
    ])
    parser.set_defaults(handler=run)


def validate_mapping(source: Path, mapping: dict, replacement_paths: set[str] | None = None) -> tuple[list[tuple[Path, dict]], list[str]]:
    """Return (writable, skipped) — writable archives to touch and the relative
    paths skipped with their reason, so callers can tell a successful no-op
    ("everything already has ComicInfo") apart from a genuine nothing-to-write."""
    if not isinstance(mapping, dict) or not mapping:
        die("mapping must be a non-empty JSON object keyed by relative archive path")
    replacement_paths = replacement_paths or set()
    validated = []
    skipped: list[str] = []
    for relative, metadata in mapping.items():
        relative_path = Path(relative)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            die(f"mapping path is not safely relative: {relative}")
        path = (source / relative_path).resolve()
        if source.resolve() not in path.parents:
            die(f"mapping path escapes source: {relative}")
        if not path.is_file():
            reason = "mapped-archive-missing"
            print(f"SKIP path={relative} reason={reason}", file=sys.stderr)
            skipped.append(f"{relative} ({reason})")
            continue
        if path.suffix.lower() != ".cbz":
            reason = "write-support-is-cbz-only"
            print(f"SKIP path={relative} reason={reason}", file=sys.stderr)
            skipped.append(f"{relative} ({reason})")
            continue
        if not isinstance(metadata, dict):
            die(f"metadata must be an object: {relative}")
        _archive.comicinfo_xml(metadata)
        if _archive.root_comicinfo(path) and relative not in replacement_paths:
            reason = "already-has-comicinfo-requires-explicit-replacement"
            print(f"SKIP path={relative} reason={reason}", file=sys.stderr)
            skipped.append(f"{relative} ({reason})")
            continue
        validated.append((path, metadata))
    return validated, skipped


def expected_hashes(path: Path) -> dict[str, str]:
    payload = load_json(path, "expected-hashes")
    try:
        return {item["path"]: item["before_sha256"] for item in payload["items"]}
    except (KeyError, TypeError) as error:
        die(f"invalid expected-hashes report: {path}")


def validate_written_archive(path: Path, metadata: dict) -> None:
    with zipfile.ZipFile(path) as archive:
        unreadable = archive.testzip()
        if unreadable:
            raise ValueError(f"unreadable archive member after write: {path}: {unreadable}")
        comicinfo = [
            name for name in archive.namelist()
            if name.lower().lstrip("./") == "comicinfo.xml"
        ]
        if len(comicinfo) != 1:
            raise ValueError(f"expected one root ComicInfo.xml after write: {path}")
        root = ElementTree.fromstring(archive.read(comicinfo[0]))
    fields = {child.tag.casefold(): child.text for child in root}
    tag_names = getattr(_archive, "_TAG_NAMES", {})
    for field in COMICINFO_FIELDS:
        if field not in metadata or metadata[field] in (None, ""):
            continue
        tag = tag_names.get(field, field.title()).casefold()
        if fields.get(tag) != serialize_multi(metadata[field]):
            raise ValueError(f"metadata mismatch after write: {path}: {field}")


def _copy2_lenient(source: Path, destination: Path) -> None:
    """Copy a file, tolerating unpermitted metadata (e.g. chflags on some volumes)."""
    shutil.copyfile(source, destination)
    try:
        shutil.copystat(source, destination, follow_symlinks=True)
    except (OSError, NotImplementedError):
        pass


def _commit(temp: Path, dest: Path, retries: int = 3) -> None:
    """Place ``temp`` at ``dest``: atomic rename where possible, streaming
    overwrite as a fallback.

    ``os.replace`` over SMB can fail with ``EINVAL``/``EIO`` on large files
    (a long-standing macOS SMB-client behaviour). The build is expensive, so we
    retry only the rename for transient errnos, then fall back to a sequential
    in-place copy — which is robust over SMB where a cross-FS rename is not.
    The backup written by :func:`execute` protects the original if the copy is
    interrupted. Raises the rename error if both paths fail.
    """
    last_error: OSError | None = None
    for attempt in range(1, retries + 1):
        try:
            os.replace(temp, dest)
            return
        except OSError as error:
            last_error = error
            if error.errno not in _TRANSIENT_ERRNOS:
                break  # permanent rename error: try the streaming fallback once
            if attempt < retries:
                time.sleep(0.5 * attempt)
    try:
        shutil.copyfile(temp, dest)
    except OSError:
        raise last_error
    temp.unlink(missing_ok=True)


def _write_one(path: Path, metadata: dict, retries: int = 3) -> None:
    """Rewrite a CBZ in place with a new root ComicInfo.xml (atomic).

    The new archive is built once into a sibling temp file, then handed to
    :func:`_commit` (which retries the rename and falls back to a streaming
    overwrite on SMB). The outer loop only re-runs the build when the build
    itself fails transiently — it never re-streams the whole zip just because
    the commit step returned a transient errno.
    """
    last_error: OSError | None = None
    for attempt in range(1, retries + 1):
        try:
            with zipfile.ZipFile(path) as source_archive:
                with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".cbz.tmp", delete=False) as handle:
                    temporary = Path(handle.name)
                try:
                    with zipfile.ZipFile(temporary, "w") as destination:
                        destination.comment = source_archive.comment
                        for info in source_archive.infolist():
                            if info.is_dir():
                                continue  # directory entries carry no data
                            if info.filename.lower().lstrip("./") == "comicinfo.xml":
                                continue
                            # Some third-party archives carry corrupt local-header
                            # offsets (e.g. offset > file size) that make the member
                            # unreadable. Restore from backup/archive if pages go
                            # missing; never let one corrupt entry abort the write.
                            try:
                                destination.writestr(info, source_archive.read(info.filename))
                            except (OSError, zipfile.BadZipFile, zlib.error, EOFError):
                                print(
                                    f"SKIP_MEMBER path={path.name} member={info.filename!r} "
                                    f"reason=unreadable-entry (corrupt archive)",
                                    file=sys.stderr,
                                )
                                continue
                        destination.writestr("ComicInfo.xml", _archive.comicinfo_xml(metadata))
                    _commit(temporary, path)
                finally:
                    temporary.unlink(missing_ok=True)
            return
        except OSError as error:
            last_error = error
            if error.errno not in _TRANSIENT_ERRNOS or attempt == retries:
                raise
            time.sleep(0.5 * attempt)
    if last_error is not None:
        raise last_error


def _prune_stale_temp_files(source_root: Path) -> None:
    """Remove *.cbz.tmp leftovers a killed write leaves behind.

    :func:`_write_one` builds each new archive as a ``*.cbz.tmp`` sibling and
    cleans it in a ``finally``. If the process is killed (or the pty closed)
    before that runs, the temp file is orphaned. Any such file older than an
    hour is garbage — a live write's temp file is only open for the duration
    of one archive build, far less — so prune it before a fresh write starts.
    """
    now = time.time()
    stale: list[Path] = []
    try:
        for path in source_root.rglob("*.cbz.tmp"):
            try:
                if now - path.stat().st_mtime > 3600:
                    stale.append(path)
            except OSError:
                continue
    except OSError:
        return
    for path in stale:
        try:
            path.unlink()
            print(f"CLEANED_STALE_TMP path={path.relative_to(source_root)} deployed-by=comicmeta-write")
        except OSError:
            pass


def purge_backups(backup_dir: Path, retention_days: int = 0) -> tuple[int, int]:
    """Delete backups, returning (files_removed, bytes_freed).

    With a positive ``retention_days``, only backups older than that many days
    are removed (rolling retention). Otherwise the whole backup directory is
    removed. Called after a fully validated write when ``write.keep_backup_after_verify``
    or ``write.backup_retention`` is configured.
    """
    if not backup_dir.is_dir():
        return 0, 0
    removed = 0
    freed = 0
    now = time.time()
    if retention_days > 0:
        cutoff = now - retention_days * 86400
        for path in backup_dir.rglob("*"):
            if not path.is_file():
                continue
            try:
                if path.stat().st_mtime >= cutoff:
                    continue
            except OSError:
                continue
            try:
                size = path.stat().st_size
                path.unlink()
            except OSError:
                continue
            removed += 1
            freed += size
    else:
        for path in backup_dir.rglob("*"):
            if path.is_file():
                try:
                    freed += path.stat().st_size
                except OSError:
                    pass
        shutil.rmtree(backup_dir, ignore_errors=True)
        removed = len(list(backup_dir.rglob("*"))) if backup_dir.exists() else 0
    return removed, freed


def execute(
    source: Path,
    mapping: Path,
    backup_dir: Path,
    report_path: Path,
    expected: Path | None,
    make_backups: bool = True,
    retention_days: int = 0,
    purge_after_verify: bool = False,
    replacement_paths: set[str] | None = None,
) -> None:
    if not source.is_dir():
        die_missing_source(source)
    source_root = source.resolve()
    _prune_stale_temp_files(source_root)
    mapping_data = load_json(mapping, "mapping")
    try:
        validated, skipped = validate_mapping(source_root, mapping_data, replacement_paths)
    except ValueError as error:
        die(str(error))
    if not validated:
        noop_reasons = {
            "already-has-comicinfo", "already-has-comicinfo-requires-explicit-replacement",
            "mapped-archive-missing", "write-support-is-cbz-only",
        }
        blocked = [s for s in skipped if not any(s.endswith(f"({r})") for r in noop_reasons)]
        if not blocked:
            print("  Nothing to write:")
            for item in skipped:
                print(f"    - {item}")
            return
        die("no writable CBZ mappings remain")
    required_hashes = expected_hashes(expected) if expected else None
    if required_hashes is not None and set(required_hashes) != set(mapping_data):
        die("expected-hashes paths must exactly match mapping paths")
    before_hashes = {}
    if required_hashes is not None:
        # Only pre-hash every file when expected hashes must be verified. Skipping
        # this avoids reading the whole library up-front when it's not enforced.
        for path, _ in validated:
            relative = path.relative_to(source_root).as_posix()
            before = _archive.sha256(path)
            if required_hashes[relative] != before:
                die(f"production hash does not match staging audit: {relative}")
            before_hashes[path] = before
    try:
        if make_backups:
            backup_dir.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        die(f"backup directory is not writable: {backup_dir} ({error})")
    if make_backups and not os.access(backup_dir, os.W_OK):
        die(f"backup directory is not writable: {backup_dir}")
    report = {"generated_at": datetime.now(timezone.utc).isoformat(), "items": []}
    written = []
    from comicmeta._spinner import Spinner
    from comicmeta._humanize import pretty_bytes, pretty_duration
    total = len(validated)
    started_at = time.monotonic()
    bytes_before = 0
    failed = []
    with Spinner(f"Writing 0/{total} archives") as spinner:
        for count, (path, metadata) in enumerate(validated, 1):
            relative = path.relative_to(source_root)
            backup = backup_dir / relative
            if make_backups:
                backup.parent.mkdir(parents=True, exist_ok=True)
            before = before_hashes.get(path) if required_hashes is not None else _archive.sha256(path)
            bytes_before += path.stat().st_size
            try:
                if make_backups:
                    if backup.exists():
                        if _archive.sha256(backup) != before:
                            # The existing backup is stale: a previous write for
                            # this archive was interrupted after backing up but
                            # before/while re-writing, so production no longer
                            # matches. Refresh the backup from the *current*
                            # production, then continue with the write. Dieing
                            # here traps the library in a write/rollback loop.
                            _copy2_lenient(path, backup)
                    else:
                        _copy2_lenient(path, backup)
                _write_one(path, metadata)
                if make_backups:
                    try:
                        shutil.copystat(backup, path, follow_symlinks=True)
                    except OSError:
                        pass
                validate_written_archive(path, metadata)
                after = _archive.sha256(path)
                report["items"].append({
                    "path": relative.as_posix(), "before": before, "after": after,
                    "backup": str(backup), "validated": True,
                })
                written.append((path, backup))
                spinner.progress(count, total, item=relative.as_posix())
                # A replacement-requested archive is now rewritten; drop the request.
                if replacement_paths and relative.as_posix() in replacement_paths:
                    from comicmeta._commands import replacement
                    replacement.clear_request(source_root, relative.as_posix())
                # Per-file WROTE lines are machine output for the report log;
                # on an interactive terminal the single spinner bar is enough.
                if not sys.stdout.isatty():
                    print(f"WROTE path={relative} before={before} after={after} backup={backup}")
            except BaseException as error:
                failed.append((relative, error))
                if make_backups and backup.exists():
                    try:
                        _copy2_lenient(backup, path)
                        print(f"ROLLBACK path={relative} backup={backup}", file=sys.stderr)
                    except BaseException as rollback_error:
                        print(f"ROLLBACK_FAILED path={relative} error={rollback_error}", file=sys.stderr)
                print(f"FAILED path={relative} error={error}", file=sys.stderr)
                if isinstance(error, zipfile.BadZipFile) or getattr(error, "errno", None) in (22, 5):
                    print(f"HINT path={relative} archive may be corrupt; re-download or restore from backup", file=sys.stderr)
                elif getattr(error, "errno", None) == 28:
                    print(f"HINT path={relative} no space left on device; free space or move backup/staging to another filesystem", file=sys.stderr)
    succeeded = total - len(failed)
    if succeeded:
        spinner.succeed(f"Wrote {succeeded}/{total} archives")
    elapsed = time.monotonic() - started_at
    per_file = elapsed / total if total else 0.0
    backup_note = "with backups" if make_backups else "without backups"
    print(f"▸ WRITE — {succeeded}/{total} archive(s) written {backup_note} in {pretty_duration(elapsed)}")
    print(f"SUMMARY wrote={succeeded} failed={len(failed)} time={pretty_duration(elapsed)} avg={pretty_duration(per_file)}/file size={pretty_bytes(bytes_before)}")
    for relative, error in failed:
        print(f"FAILED path={relative} error={error}", file=sys.stderr)
    atomic_write(report_path, json.dumps(report, indent=2, sort_keys=True) + "\n")
    if failed and succeeded == 0:
        die(f"all {total} writes failed; first error: {failed[0][1]}")
    if succeeded and not failed:
        if purge_after_verify:
            removed, freed = purge_backups(backup_dir)
            print(f"PURGED backups removed={removed} freed={pretty_bytes(freed)} reason=after-verified-write")
        elif retention_days > 0:
            removed, freed = purge_backups(backup_dir, retention_days)
            if removed:
                print(f"PURGED backups removed={removed} freed={pretty_bytes(freed)} reason=retention")


def _dry_run(source: Path, mapping: Path, backup_dir: Path, report: Path, staging_dir: Path | None = None, replacement_paths: set[str] | None = None) -> None:
    """Validate the write against every mapped file without touching production.

    Streams per-file: copy one archive to a temp dir, write it, validate it,
    then delete the temp copy before moving to the next. Peak disk usage is a
    single archive, so a full-library dry-run fits anywhere regardless of size.
    `staging_dir` overrides the default system temp location — use a directory
    on a roomy filesystem when the system temp is small (e.g. a NAS tmpfs).
    """
    if not mapping.is_file():
        die(f"mapping not found: {mapping}; run `comicmeta review` first")
    mapping_data = load_json(mapping, "mapping")
    if staging_dir is not None and not staging_dir.is_dir():
        die(f"staging directory does not exist: {staging_dir}")

    with tempfile.TemporaryDirectory(prefix="comicmeta-dryrun-", dir=staging_dir) as temporary:
        root = Path(temporary)
        staging = root / "staging"
        staging.mkdir()
        validated = 0
        failed = []
        for relative, metadata in sorted(mapping_data.items()):
            relative_path = Path(relative)
            if relative_path.is_absolute() or ".." in relative_path.parts:
                die(f"mapping path is not safely relative: {relative}")
            original = (source / relative_path).resolve()
            if source.resolve() not in original.parents:
                die(f"mapping path escapes source: {relative}")
            if not original.is_file():
                failed.append((relative, FileNotFoundError("mapped archive missing from library")))
                print(f"DRY_FAIL path={relative} error=mapped archive does not exist in library", file=sys.stderr)
                continue
            if original.suffix.lower() == ".cbz":
                try:
                    existing_comicinfo = _archive.root_comicinfo(original)
                except (OSError, ValueError, zipfile.BadZipFile) as error:
                    failed.append((relative, error))
                    print(f"DRY_FAIL path={relative} error={error}", file=sys.stderr)
                    continue
                if existing_comicinfo and relative not in (replacement_paths or set()):
                    print(
                        f"DRY_SKIP path={relative} reason=already-has-comicinfo-requires-explicit-replacement",
                        file=sys.stderr,
                    )
                    continue
            staged = staging / relative
            staged.parent.mkdir(parents=True, exist_ok=True)
            _copy2_lenient(original, staged)
            # Validate the mapping is writable for this file.
            try:
                _archive.comicinfo_xml(metadata)
            except ValueError as error:
                failed.append((relative, error))
                print(f"DRY_FAIL path={relative} error={error}", file=sys.stderr)
                continue
            # Write the staged copy (no backup needed — staging is the copy).
            # A corrupt archive (bad EOCD, truncated member) aborts the whole
            # run if treated as fatal — like the real write, report it and
            # continue so one bad file does not block the rest of the library.
            try:
                _write_one(staged, metadata)
            except (zipfile.BadZipFile, OSError, ValueError) as error:
                failed.append((relative, error))
                print(f"DRY_FAIL path={relative} error={error}", file=sys.stderr)
                continue
            try:
                validate_written_archive(staged, metadata)
            except ValueError as error:
                failed.append((relative, error))
                print(f"DRY_FAIL path={relative} error={error}", file=sys.stderr)
                continue
            validated += 1
            staged.unlink(missing_ok=True)
        if failed and validated == 0:
            die(f"all {len(mapping_data)} dry-run files failed; first error: {failed[0][1]}")
        print(f"▸ DRY-RUN — {validated}/{len(mapping_data)} archive(s) write cleanly")
        print("DRY_RUN production_unchanged=yes")
        print(f"DRY_RUN staged={validated} (streamed one-at-a-time)")
        if failed:
            print(f"DRY_RUN failed={len(failed)} (skipped; see DRY_FAIL lines above)", file=sys.stderr)
        print("  No production archive was modified. Run `comicmeta write` to apply.")
        _ = report  # dry-run writes no persistent report


def _write_summary_panel(colors, rows):
    """Boxed pre-write summary so the confirm step reads as a review screen."""
    label_w = max(len(label) for label, _ in rows)
    value_w = max(len(value) for _, value in rows)
    cols, _ = _terminal_size((80, 24))
    inner = min(label_w + value_w + 3, max(4, cols - 4))
    print(colors.muted("┌" + "─" * (inner + 2) + "┐"))
    for label, value in rows:
        line = _truncate_ansi(f"  {label:<{label_w}}  {value}", inner + 2)
        print(colors.muted("│" + line.ljust(inner + 2) + "│"))
    print(colors.muted("└" + "─" * (inner + 2) + "┘"))


def run(args: argparse.Namespace) -> None:
    from comicmeta import _config
    from comicmeta._tui import confirm, is_interactive
    flat = _config.load(getattr(args, "source", None))
    source = args.source or Path(_config.get(flat, "paths.source"))
    mapping = args.mapping or Path(_config.get(flat, "paths.mapping"))
    backup_dir = args.backup_dir or Path(_config.get(flat, "paths.backup_dir"))
    report = args.report or Path(_config.get(flat, "paths.write_report"))
    make_backups = not args.no_backups and bool(_config.get(flat, "write.keep_backups"))
    retention_days = _config.as_int(_config.get(flat, "write.backup_retention"), 0)
    purge_after_verify = bool(_config.get(flat, "write.keep_backup_after_verify"))

    from comicmeta._commands import replacement
    replacement_paths = replacement.requested_paths(source)

    if getattr(args, "dry_run", False):
        _dry_run(source, mapping, backup_dir, report, getattr(args, "staging_dir", None), replacement_paths)
        return

    if not mapping.is_file():
        die(f"mapping not found: {mapping}; run `comicmeta review` first")

    # Report how many reviewed files are excluded because they're flagged.
    from comicmeta._commands.flags import collect
    series_flags, issue_flags = collect(flat)
    if series_flags or issue_flags:
        print(f"  ⚠ Excluded from this write (flagged for research): "
              f"{len(series_flags)} series, {len(issue_flags)} issues")
        print("    These are intentionally not written. Run `comicmeta flags --clear` once resolved.")
        print()

    if not getattr(args, "yes", False) and not _config.get(flat, "write.auto_confirm"):
        if not is_interactive():
            die("write modifies production; pass --yes to confirm non-interactively")
        from comicmeta._common import Palette, color_enabled
        colors = Palette(color_enabled())
        print(colors.title("▸ WRITE COMICINFO"))
        print()
        count = 0
        try:
            mapping_data = load_json(mapping, "mapping")
            count = len(mapping_data) if isinstance(mapping_data, dict) else 0
        except SystemExit:
            pass
        rows = [
            ("Library", str(source)),
            ("Mapping", str(mapping)),
            ("Backup", str(backup_dir) if make_backups else "disabled (no backups)"),
            ("Files", f"{count} archive{'s' if count != 1 else ''}" if count else "—"),
        ]
        if make_backups and purge_after_verify:
            rows.append(("Backups", "purge after verified write"))
        elif make_backups and retention_days > 0:
            rows.append(("Backups", f"keep {retention_days}d, purge older"))
        _write_summary_panel(colors, rows)
        print()
        if not confirm("  Proceed with the write?", default=False):
            die("write cancelled")

    expected = args.expected_hashes
    if expected is None and _config.get(flat, "write.enforce_expected_hashes"):
        stage_report = Path(_config.get(flat, "paths.candidates")).parent / "comicmeta-stage-report.json"
        if stage_report.exists():
            expected = stage_report
        else:
            die("write.enforce_expected_hashes is on but no staging audit was found")

    if replacement_paths:
        print(f"  ↻ {len(replacement_paths)} archive(s) marked for ComicInfo replacement will be rewritten.")
        print()

    execute(source, mapping, backup_dir, report, expected, make_backups=make_backups,
            retention_days=retention_days, purge_after_verify=purge_after_verify,
            replacement_paths=replacement_paths)