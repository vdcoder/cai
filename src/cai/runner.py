"""Snapshots and subprocess execution of #run experiments and #test blocks.

Runner protocol (see docs/RUNNER_PROTOCOL.md): the configured argv list is
started without a shell, with the snapshot directory as working directory,
the directive body on standard input and metadata in ``CAI_*`` environment
variables. Directive text is never interpolated into a command line.
"""
from __future__ import annotations

import fnmatch
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from .config import Config

PASSED, FAILED, TIMEOUT, LAUNCH_ERROR, SKIPPED = "passed", "failed", "timeout", "launch_error", "skipped"
DEFAULT_SNAPSHOT_EXCLUDES = frozenset({
    ".git", ".hg", ".svn", "__pycache__", "node_modules", ".venv", "venv",
    ".mypy_cache", ".pytest_cache", ".tox",
})


@dataclass
class ExecResult:
    name: str
    kind: str  # run | test
    status: str
    exit_code: int | None
    duration_ms: float
    stdout: str
    stderr: str
    checkpoint: int | None
    file: str
    line: int
    stdout_truncated: bool = False
    stderr_truncated: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def skipped(name: str, kind: str, file: str, line: int, reason: str, checkpoint: int | None = None) -> ExecResult:
    return ExecResult(name, kind, SKIPPED, None, 0.0, "", reason, checkpoint, file, line)


def make_snapshot(cfg: Config, contents: dict[str, bytes], dest: Path) -> None:
    """Copy the workspace to ``dest`` and overlay the given managed-file contents."""
    root = cfg.root
    state_top = Path(cfg.state_dir).parts[0]

    def ignore(directory: str, names: list[str]) -> set[str]:
        rel_dir = Path(directory).resolve().relative_to(root).as_posix()
        skip = set()
        for name in names:
            rel = name if rel_dir == "." else f"{rel_dir}/{name}"
            if (name in DEFAULT_SNAPSHOT_EXCLUDES or rel == state_top
                    or any(fnmatch.fnmatch(rel, pat) for pat in cfg.snapshot_exclude)):
                skip.add(name)
        return skip

    shutil.copytree(root, dest, symlinks=True, ignore=ignore)
    for rel, data in contents.items():
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


class _Capture(threading.Thread):
    """Drain a pipe, keeping at most ``limit`` bytes."""

    def __init__(self, pipe, limit: int) -> None:
        super().__init__(daemon=True)
        self.pipe, self.limit = pipe, limit
        self.data = bytearray()
        self.truncated = False
        self.start()

    def run(self) -> None:
        try:
            while chunk := self.pipe.read(65536):
                room = self.limit - len(self.data)
                if len(chunk) > room:
                    self.truncated = True
                self.data += chunk[: max(room, 0)]
        except (OSError, ValueError):
            pass

    def text(self) -> str:
        return bytes(self.data).decode("utf-8", errors="replace")


def _kill(proc: subprocess.Popen) -> None:
    try:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, check=False)
            proc.kill()
    except (OSError, ProcessLookupError):
        pass


def execute(cfg: Config, command: list[str], *, kind: str, name: str, body: str, snapshot: Path,
            job_dir: Path, file: str, line: int, style: str, checkpoint: int | None) -> ExecResult:
    job_dir.mkdir(parents=True, exist_ok=True)
    body_file = job_dir / "body.txt"
    meta_file = job_dir / "meta.json"
    body_file.write_bytes(body.encode("utf-8"))
    meta = {
        "kind": kind, "name": name, "source_file": file, "source_line": line, "style": style,
        "checkpoint": checkpoint, "snapshot_dir": str(snapshot), "workspace": str(cfg.root),
        "body_file": str(body_file), "timeout_seconds": cfg.timeout_seconds, "project": cfg.name,
    }
    meta_file.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    subst = {"{python}": sys.executable, "{name}": name, "{kind}": kind, "{body_file}": str(body_file),
             "{meta_file}": str(meta_file), "{snapshot}": str(snapshot), "{workspace}": str(cfg.root)}
    argv = []
    for arg in command:
        for token, value in subst.items():
            arg = arg.replace(token, value)
        argv.append(arg)
    env = dict(os.environ)
    env.update({
        "CAI_KIND": kind, "CAI_NAME": name, "CAI_SOURCE_FILE": file, "CAI_SOURCE_LINE": str(line),
        "CAI_STYLE": style, "CAI_CHECKPOINT": "" if checkpoint is None else str(checkpoint),
        "CAI_SNAPSHOT_DIR": str(snapshot), "CAI_WORKSPACE": str(cfg.root), "CAI_BODY_FILE": str(body_file),
        "CAI_META_FILE": str(meta_file), "CAI_TIMEOUT_SECONDS": str(cfg.timeout_seconds),
    })

    def result(status: str, code: int | None, out: str = "", err: str = "", t_out=False, t_err=False) -> ExecResult:
        return ExecResult(name, kind, status, code, round((time.perf_counter() - start) * 1000, 3),
                          out, err, checkpoint, file, line, t_out, t_err)

    start = time.perf_counter()
    try:
        proc = subprocess.Popen(
            argv, cwd=snapshot, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, start_new_session=(os.name == "posix"),
        )
    except (OSError, ValueError) as exc:
        return result(LAUNCH_ERROR, None, err=f"failed to launch {argv[0]!r}: {exc}")
    out, err = _Capture(proc.stdout, cfg.max_output_bytes), _Capture(proc.stderr, cfg.max_output_bytes)

    def feed() -> None:
        try:
            proc.stdin.write(body.encode("utf-8"))
            proc.stdin.close()
        except (OSError, ValueError):
            pass

    feeder = threading.Thread(target=feed, daemon=True)
    feeder.start()
    timed_out = False
    try:
        proc.wait(timeout=cfg.timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill(proc)
        proc.wait()
    except BaseException:
        _kill(proc)
        raise
    for t in (out, err, feeder):
        t.join(timeout=5)
    if timed_out:
        return result(TIMEOUT, None, out.text(), err.text(), out.truncated, err.truncated)
    status = PASSED if proc.returncode == 0 else FAILED
    return result(status, proc.returncode, out.text(), err.text(), out.truncated, err.truncated)


class SnapshotArea:
    """Temporary directory holding the snapshots and job files of one invocation."""

    def __init__(self, keep: bool = False) -> None:
        self.base = Path(tempfile.mkdtemp(prefix="cai-snap-"))
        self.keep = keep
        self._n = 0

    def new(self, label: str) -> tuple[Path, Path]:
        self._n += 1
        slot = self.base / f"{self._n:03d}-{label}"
        slot.mkdir()
        return slot / "snapshot", slot / "job"

    def close(self) -> None:
        if not self.keep:
            shutil.rmtree(self.base, ignore_errors=True)
