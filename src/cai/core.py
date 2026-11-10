"""One CAI invocation: scan, plan, execute, commit, report."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import __version__, manifest, stats, txn
from .config import Config
from .diagnostics import ERROR, WARNING, Diagnostic, has_errors
from .discovery import SourceFile, discover, load, sha256
from .engine import END, Block, Plan, build_plan, render_file
from .runner import PASSED, SKIPPED, ExecResult, SnapshotArea, execute, make_snapshot, skipped

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
    full_scan: bool = False
    no_stats: bool = False

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
    manifest: dict = field(default_factory=dict)
    discovered: set = field(default_factory=set)


def scan(cfg: Config, use_manifest: bool = False) -> Scan:
    result = Scan()
    known = manifest.load(cfg.state_path) if use_manifest else {}
    result.manifest = known
    for rel, path, style in discover(cfg):
        result.discovered.add(rel)
        if known:
            try:
                if manifest.is_clean(known.get(rel), path.stat()):
                    result.files_skipped += 1
                    continue
            except OSError:
                pass
        result.files_scanned += 1
        src, diags = load(rel, path, style)
        result.diagnostics.extend(diags)
        if src is not None:
            result.sources.append(src)
            result.bytes_read += len(src.data)
    return result


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
    results = []
    shared: Path | None = None
    for block in blocks:
        assert command is not None
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
    lock = txn.Lock(cfg.state_path)
    recovered: list[str] = []
    early: list[Diagnostic] = []
    if opts.check:
        if (cfg.state_path / "txn" / "journal.json").exists():
            early.append(Diagnostic(WARNING, "W520", "an interrupted cai transaction is pending; it will be "
                                    "rolled back by the next --build/--run/--test"))
    else:
        try:
            lock.acquire()
            recovered = txn.recover(cfg.root, cfg.state_path)
        except txn.TxnError as exc:
            lock.release()
            code = "E510" if isinstance(exc, txn.LockError) else "E512"
            report.update(diagnostics=[Diagnostic(ERROR, code, str(exc)).to_dict()], exit_code=EXIT_IO)
            return EXIT_IO, report
        if lock.stole_stale:
            early.append(Diagnostic(WARNING, "W521", "removed a stale lock left by a dead cai process"))
        if recovered:
            early.append(Diagnostic(WARNING, "W522", "rolled back an interrupted cai transaction; restored: "
                                    + ", ".join(recovered)))
    try:
        return _invoke_locked(cfg, opts, report, early, recovered, t0)
    finally:
        lock.release()


def _invoke_locked(cfg: Config, opts: Options, report: dict, early: list[Diagnostic],
                   recovered: list[str], t0: float) -> tuple[int, dict]:
    # 1-2. discover, parse
    scanned = scan(cfg, cfg.incremental and not opts.full_scan)
    t_parse = time.perf_counter()
    # 3-6. operation sequence, lifecycles, checkpoints, consolidated state
    plan = build_plan([s.parsed for s in scanned.sources])
    diags = early + scanned.diagnostics + plan.diagnostics
    keep_runs = not opts.run and not opts.discard_runs
    changes: dict[str, tuple[SourceFile, bytes]] = {}
    if not has_errors(diags):
        for src in scanned.sources:
            new = src.encode(render_file(plan, src.parsed, keep_runs=keep_runs))
            if new != src.data:
                changes[src.rel] = (src, new)
    t_transform = time.perf_counter()

    code = EXIT_OK
    runs = plan.active("run") if opts.run else []
    tests = plan.active("test") if opts.test else []
    if opts.test_names:
        for name in sorted(set(opts.test_names) - {b.name for b in tests}):
            diags.append(Diagnostic(ERROR, "E305", f"no active #test named '{name}'", directive="test", name=name))
        tests = [b for b in tests if b.name in opts.test_names]
    if not has_errors(diags):
        for kind, blocks, command in (("run", runs, cfg.run_command), ("test", tests, cfg.test_command)):
            if blocks and command is None:
                diags.append(Diagnostic(ERROR, "E101", f"runner.{kind}_command is not configured but "
                                        f"{len(blocks)} #{kind} block(s) must be executed"))
                code = EXIT_CONFIG

    run_results: list[ExecResult] = []
    test_results: list[ExecResult] = []
    files_modified: list[str] = []
    bytes_written = 0
    t_runner = 0.0
    if has_errors(diags):
        code = code or EXIT_INVALID
        if opts.run:
            run_results = [skipped(b.name, "run", b.decl.file, b.decl.line,
                                   "skipped: the invocation was rejected by validation errors", b.checkpoint)
                           for b in plan.blocks if b.kind == "run"]
        tests = []
    elif not opts.check:
        # 7. execute against immutable snapshots; the workspace is still untouched
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
        # 9. commit
        try:
            bytes_written = txn.commit(cfg.root, cfg.state_path,
                                       [(rel, changes[rel][0].data, changes[rel][1]) for rel in sorted(changes)])
            files_modified = sorted(changes)
        except txn.TxnError as exc:
            diags.append(Diagnostic(ERROR, "E511", str(exc)))
            code = EXIT_IO
        if code == EXIT_OK and any(r.status != PASSED for r in run_results + test_results):
            code = EXIT_FAILED
        if code != EXIT_IO and cfg.incremental:
            final = {s.rel: (s.path, sha256(changes[s.rel][1] if s.rel in changes else s.data),
                             not s.parsed.directives) for s in scanned.sources}
            manifest.save(cfg.state_path, scanned.manifest, final, scanned.discovered)

    # 8. diagnostics and telemetry
    timing = {
        "parse": round((t_parse - t0) * 1000, 3),
        "transform": round((t_transform - t_parse) * 1000, 3),
        "runner": round(t_runner * 1000, 3),
        "total": round((time.perf_counter() - t0) * 1000, 3),
    }
    report.update(
        ok=code == EXIT_OK,
        exit_code=code,
        diagnostics=[d.to_dict() for d in diags],
        directives=dict(plan.counts),
        files_modified=files_modified,
        would_modify=sorted(changes),
        pending={"defers": _block_info(plan, "defer"), "tests": _block_info(plan, "test"),
                 "runs": _block_info(plan, "run") if keep_runs else []},
    )
    if opts.show_waits:
        report["waits"] = [{"file": w.file, "line": w.line, "text": "\n".join(w.body)} for w in plan.waits]
    if opts.run:
        report["runs"] = [r.to_dict() for r in run_results]
        report["checkpoints"] = len({b.checkpoint for b in runs})
    if opts.test:
        report["tests"] = [r.to_dict() for r in test_results]
    report["timing_ms"] = timing
    report["stats"] = record = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "cai_version": __version__,
        "mode": opts.mode,
        "exit_code": code,
        "files_scanned": scanned.files_scanned,
        "files_skipped": scanned.files_skipped,
        "directives": dict(plan.counts),
        "evolutions": plan.counts["evolve"],
        "drops": plan.counts["drop"],
        "experiments": sum(r.status != SKIPPED for r in run_results),
        "experiment_failures": sum(r.status not in (PASSED, SKIPPED) for r in run_results),
        "persistent_tests": len(plan.active("test")),
        "tests_executed": len(test_results),
        "test_failures": sum(r.status != PASSED for r in test_results),
        "transformation_errors": sum(d.severity == ERROR for d in diags),
        "parse_ms": timing["parse"],
        "transform_ms": timing["transform"],
        "runner_ms": timing["runner"],
        "total_ms": timing["total"],
        "bytes_read": scanned.bytes_read,
        "bytes_written": bytes_written,
        "files_modified": len(files_modified),
        "checkpoints": report.get("checkpoints", 0),
        "recovery_operations": len(recovered),
    }
    if not opts.check:  # --check leaves the disk untouched, statistics included
        try:
            cfg.state_path.mkdir(parents=True, exist_ok=True)
            (cfg.state_path / "last_report.json").write_text(
                json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
            if cfg.stats_enabled and not opts.no_stats:
                stats.append(cfg.stats_file, record)
        except OSError as exc:
            report["diagnostics"].append(
                Diagnostic(WARNING, "W530", f"could not store report/statistics: {exc}").to_dict())
    return code, report
