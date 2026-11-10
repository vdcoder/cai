"""One CAI invocation: scan, plan, execute, commit, report."""
from __future__ import annotations

import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import __version__
from .config import Config
from .diagnostics import Diagnostic, has_errors
from .discovery import SourceFile, discover, load
from .engine import Plan, build_plan, render_file

EXIT_OK, EXIT_FAILED, EXIT_INVALID, EXIT_CONFIG, EXIT_IO, EXIT_INTERRUPTED = 0, 1, 2, 3, 4, 130


@dataclass
class Options:
    check: bool = False
    run: bool = False
    test: bool = False
    build: bool = False
    test_names: list[str] = field(default_factory=list)
    discard_runs: bool = False
    show_waits: bool = False
    keep_snapshots: bool = False

    @property
    def mode(self) -> str:
        if self.check:
            return "check"
        return "+".join(m for m in ("run", "test") if getattr(self, m)) or "build"


@dataclass
class Scan:
    sources: list[SourceFile] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    files_scanned: int = 0
    files_skipped: int = 0
    bytes_read: int = 0


def scan(cfg: Config) -> Scan:
    result = Scan()
    for rel, path, style in discover(cfg):
        result.files_scanned += 1
        src, diags = load(rel, path, style)
        result.diagnostics.extend(diags)
        if src is not None:
            result.sources.append(src)
            result.bytes_read += len(src.data)
    return result


def write_atomic(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` through a flushed temporary sibling."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".cai-tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _block_info(plan: Plan, kind: str) -> list[dict]:
    return [{"name": b.name, "file": b.decl.file, "line": b.decl.line} for b in plan.active(kind)]


def invoke(cfg: Config, opts: Options) -> tuple[int, dict]:
    """Run one invocation and return (exit_code, report)."""
    t0 = time.perf_counter()
    report: dict = {"cai_version": __version__, "mode": opts.mode, "ok": False, "exit_code": EXIT_OK}
    scanned = scan(cfg)
    t_parse = time.perf_counter()
    plan = build_plan([s.parsed for s in scanned.sources])
    diags = scanned.diagnostics + plan.diagnostics
    keep_runs = not opts.run and not opts.discard_runs
    changes: dict[str, tuple[SourceFile, bytes]] = {}
    if not has_errors(diags):
        for src in scanned.sources:
            new = src.encode(render_file(plan, src.parsed, keep_runs=keep_runs))
            if new != src.data:
                changes[src.rel] = (src, new)
    t_transform = time.perf_counter()

    report["diagnostics"] = [d.to_dict() for d in diags]
    report["directives"] = dict(plan.counts)
    report["pending"] = {"defers": _block_info(plan, "defer"), "tests": _block_info(plan, "test"),
                         "runs": _block_info(plan, "run") if keep_runs else []}
    if opts.show_waits:
        report["waits"] = [{"file": w.file, "line": w.line, "text": "\n".join(w.body)} for w in plan.waits]
    report["files_modified"] = []
    report["would_modify"] = sorted(changes)
    code = EXIT_OK
    if has_errors(diags):
        code = EXIT_INVALID
    elif not opts.check:
        for rel in sorted(changes):
            src, new = changes[rel]
            write_atomic(src.path, new)
        report["files_modified"] = sorted(changes)
    report["timing_ms"] = {
        "parse": round((t_parse - t0) * 1000, 3),
        "transform": round((t_transform - t_parse) * 1000, 3),
        "total": round((time.perf_counter() - t0) * 1000, 3),
    }
    report["exit_code"] = code
    report["ok"] = code == EXIT_OK
    return code, report
