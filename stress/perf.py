"""Speed-test harness: time every comicmeta subcommand against a library.

Usage:
    python stress/perf.py [--source /path/to/comics] [--iterations 3] [--profile review]

Times each major read-only command (discover, organize, inspect, flags, review
--list) and, with --execute-safe, the mutating ones. Uses pyinstrument when
available for per-line flame graphs; always reports wall-clock timing.

Flags:
    --source PATH      library root (default: current directory)
    --iterations N     runs per command (default 3, reports min)
    --profile NAME     run just that command under pyinstrument and write HTML
"""

from __future__ import annotations

import argparse
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

COMMANDS = [
    ("review --list", ["review", "--list"], True),
    ("discover", ["discover"], True),
    ("organize", ["organize"], True),
    ("inspect", ["inspect"], True),
    ("flags", ["flags"], True),
    ("browse (tree build only)", ["browse"], False),  # interactive; time startup
]


def _time_one(comicmeta: str, args: list[str], cwd: Path, source: str) -> float:
    full = [comicmeta, *[a if a != "@SOURCE" else source for a in args]]
    started = time.monotonic()
    subprocess.run(
        full, cwd=cwd,
        capture_output=True, text=True, timeout=180,
    )
    return time.monotonic() - started


def run_timing(comicmeta: str, source: Path, iterations: int) -> None:
    print(f"comicmeta speed test — library: {source}")
    print(f"binary: {comicmeta}")
    print()
    results: list[tuple[str, float, list[float]]] = []
    for label, args, _ in COMMANDS:
        times = []
        for _ in range(iterations):
            try:
                times.append(_time_one(comicmeta, args, source, str(source)))
            except subprocess.TimeoutExpired:
                times.append(float("inf"))
        best = min(times)
        results.append((label, best, times))
        print(f"  {label:<28} min={best:6.2f}s  runs={[f'{t:.2f}' for t in times]}")

    print()
    print("  Slowest first:")
    for label, best, _ in sorted(results, key=lambda item: -item[1]):
        print(f"    {label:<28} {best:6.2f}s")


def profile_command(comicmeta: str, name: str, source: Path) -> None:
    """Profile a single command under pyinstrument, write an HTML report."""
    try:
        import pyinstrument
    except ImportError:
        print("pyinstrument not installed; pip3 install pyinstrument")
        sys.exit(1)
    target = next((args for label, args, _ in COMMANDS if label.split()[0] == name), None)
    if target is None:
        print(f"unknown command: {name}")
        sys.exit(1)
    full = [comicmeta, *[a if a != "@SOURCE" else str(source) for a in target]]
    profiler = pyinstrument.Profiler()
    profiler.start()
    subprocess.run(full, cwd=source, capture_output=True, text=True, timeout=300)
    profiler.stop()
    report = profiler.output_html()
    out = ROOT / f"perf-{name}.html"
    out.write_text(report)
    print(f"profile written: {out}")
    print(profiler.output_text(unicode=True, color=False)[:3000])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path.cwd())
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--profile", type=str, default=None)
    args = parser.parse_args()

    comicmeta = shutil_which("comicmeta")
    if comicmeta is None:
        comicmeta = str(ROOT / "dist" / "bin" / "comicmeta")

    if args.profile:
        profile_command(comicmeta, args.profile, args.source)
    else:
        run_timing(comicmeta, args.source, args.iterations)


def shutil_which(name: str) -> str | None:
    import shutil
    return shutil.which(name)


if __name__ == "__main__":
    main()
