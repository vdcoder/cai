"""Micro-benchmark: full scan versus incremental (manifest) scan.

Usage: python benchmarks/scan_bench.py [FILES] [LINES_PER_FILE]

Creates a throw-away workspace, then times `cai --build` on an already
consolidated tree (the steady state an agent hits on most invocations).
Timings are wall-clock medians of in-process invocations on this machine.
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cai.config import load_config  # noqa: E402
from cai.core import Options, invoke  # noqa: E402


def build(root: Path, files: int, lines: int, incremental: bool) -> None:
    (root / "cai.json").write_text(json.dumps({
        "version": 1, "project": {"include": [{"pattern": "src/**/*.py", "style": "python_comment"}]},
        "scan": {"incremental": incremental}, "stats": {"enabled": False}}))
    body = "".join(f"value_{i} = {i}  # ordinary line\n" for i in range(lines))
    old = time.time() - 3600
    for n in range(files):
        path = root / "src" / f"pkg{n % 20:02d}" / f"mod{n:05d}.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
        os.utime(path, (old, old))


def measure(files: int, lines: int, incremental: bool, repeats: int = 7) -> tuple[float, int, int]:
    with tempfile.TemporaryDirectory(prefix="cai-scan-") as tmp:
        root = Path(tmp)
        build(root, files, lines, incremental)
        cfg = load_config(root)
        invoke(cfg, Options(build=True))  # warm-up; writes the manifest when incremental
        times = []
        for _ in range(repeats):
            start = time.perf_counter()
            _, report = invoke(cfg, Options(build=True))
            times.append((time.perf_counter() - start) * 1000)
        return statistics.median(times), report["stats"]["files_scanned"], report["stats"]["files_skipped"]


def main() -> None:
    files = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
    lines = int(sys.argv[2]) if len(sys.argv) > 2 else 200
    print(f"{files} files x {lines} lines, no pending directives, median of 7 invocations")
    for label, incremental in (("full scan", False), ("incremental", True)):
        ms, scanned, skipped = measure(files, lines, incremental)
        print(f"  {label:12} {ms:9.1f} ms   parsed={scanned} skipped={skipped}")


if __name__ == "__main__":
    main()
