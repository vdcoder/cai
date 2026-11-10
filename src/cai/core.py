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
from .engine import END, Block, Plan, build_plan, render_file
from .runner import PASSED, ExecResult, SnapshotArea, execute, make_snapshot, skipped

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


def _snapshot_contents(plan: Plan, sources: list[SourceFile], p: int) -> dict[str, bytes]:
    """Managed files whose content at operation index ``p`` differs from disk."""
    out = {}
    for src in sources:
        data = src.encode(render_file(plan, src.parsed, p))
        if data != src.data:
            out[src.rel] = data
    return out


def _execute_blocks(cfg: Config, plan: Plan, sources: list[SourceFile], area: SnapshotArea,
                    blocks: list[Block], kind: str) -> list[ExecResult]:
    command = cfg.run_command if kind == "run" else cfg.test_command
    assert command is not None
    results = []
    shared: Path | None = None
    for block in blocks:
        d = block.decl
        snapshot, job = area.new(f"{kind}-{block.name}")
        if kind == "run":  # one private snapshot per experiment, taken at its checkpoint
            make_snapshot(cfg, _snapshot_contents(plan, sources, plan.op_index(block)), snapshot)
        else:  # tests share one snapshot of the final consolidated state
            if shared is None:
                make_snapshot(cfg, _snapshot_contents(plan, sources, END), snapshot)
                shared = snapshot
            snapshot = shared
        body = "\n".join(block.final.body) + "\n"
        results.append(execute(
            cfg, command, kind=kind, name=block.name, body=body, snapshot=snapshot, job_dir=job,
            file=d.file, line=d.line, style=d.style, checkpoint=block.checkpoint if kind == "run" else None,
        ))
    return results


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

    report["directives"] = dict(plan.counts)
    report["pending"] = {"defers": _block_info(plan, "defer"), "tests": _block_info(plan, "test"),
                         "runs": _block_info(plan, "run") if keep_runs else []}
    if opts.show_waits:
        report["waits"] = [{"file": w.file, "line": w.line, "text": "\n".join(w.body)} for w in plan.waits]
    report["files_modified"] = []
    report["would_modify"] = sorted(changes)
    code = EXIT_OK
    runs = plan.active("run") if opts.run else []
    tests = plan.active("test") if opts.test else []
    unknown = sorted(set(opts.test_names) - {b.name for b in tests}) if opts.test else []
    if opts.test_names:
        tests = [b for b in tests if b.name in opts.test_names]
    for name in unknown:
        diags.append(Diagnostic("error", "E305", f"no active #test named '{name}'", name=name, directive="test"))
    for kind, blocks, command in (("run", runs, cfg.run_command), ("test", tests, cfg.test_command)):
        if blocks and command is None and not has_errors(diags):
            diags.append(Diagnostic("error", "E101", f"runner.{kind}_command is not configured but "
                                    f"{len(blocks)} #{kind} block(s) must be executed"))
            code = EXIT_CONFIG
    report["diagnostics"] = [d.to_dict() for d in diags]
    run_results: list[ExecResult] = []
    test_results: list[ExecResult] = []
    t_runner = 0.0
    if has_errors(diags):
        code = code or EXIT_INVALID
        if opts.run:
            run_results = [skipped(b.name, "run", b.decl.file, b.decl.line,
                                   "skipped: the invocation was rejected by validation errors", b.checkpoint)
                           for b in plan.blocks if b.kind == "run"]
    elif not opts.check:
        area = SnapshotArea(keep=opts.keep_snapshots)
        t_exec = time.perf_counter()
        try:
            run_results = _execute_blocks(cfg, plan, scanned.sources, area, runs, "run")
            test_results = _execute_blocks(cfg, plan, scanned.sources, area, tests, "test")
        finally:
            area.close()
        t_runner = time.perf_counter() - t_exec
        if opts.keep_snapshots:
            report["snapshot_dir"] = str(area.base)
        for rel in sorted(changes):
            src, new = changes[rel]
            write_atomic(src.path, new)
        report["files_modified"] = sorted(changes)
        if any(r.status != PASSED for r in run_results + test_results):
            code = EXIT_FAILED
    if opts.run:
        report["runs"] = [r.to_dict() for r in run_results]
        report["checkpoints"] = len({b.checkpoint for b in runs})
    if opts.test:
        report["tests"] = [r.to_dict() for r in test_results]
    report["timing_ms"] = {
        "parse": round((t_parse - t0) * 1000, 3),
        "transform": round((t_transform - t_parse) * 1000, 3),
        "runner": round(t_runner * 1000, 3),
        "total": round((time.perf_counter() - t0) * 1000, 3),
    }
    report["exit_code"] = code
    report["ok"] = code == EXIT_OK
    return code, report
