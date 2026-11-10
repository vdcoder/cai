"""Trial execution: clean workspace, agent run, hidden grading, one record."""
from __future__ import annotations

import difflib
import json
import os
import platform
import random
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import cai

from .agents import Agent, AgentError, AgentTimeout, TrialContext
from .challenge import Challenge, tree_digest
from .conditions import CONDITIONS, Condition, build_prompt, prompt_digest
from .trace import derive_metrics, validate

RESULT_MARK = "CAI_BENCH_RESULT "
IGNORED_DIRS = {".cai", "__pycache__", ".git"}


def environment() -> dict:
    return {
        "platform": platform.platform(), "machine": platform.machine(), "cpu_count": os.cpu_count(),
        "python": sys.version.split()[0], "cai_version": cai.__version__,
    }


def prepare_workspace(ch: Challenge, cond: Condition, dest: Path) -> str:
    """Create a pristine workspace for one trial; returns the fixture digest."""
    digest = tree_digest(ch.fixture)
    shutil.copytree(ch.fixture, dest)
    if tree_digest(dest) != digest:
        raise RuntimeError(f"workspace copy of {ch.id} does not match its fixture")
    if cond.cai_enabled and ch.cai_overlay is not None:
        shutil.copytree(ch.cai_overlay, dest, dirs_exist_ok=True)
    for argv in ch.setup:
        argv = [a.replace("{python}", sys.executable) for a in argv]
        subprocess.run(argv, cwd=dest, check=True, capture_output=True, timeout=ch.trial_timeout)
    return digest


def _source_files(root: Path) -> dict[str, str]:
    out = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and not IGNORED_DIRS & set(path.relative_to(root).parts):
            try:
                out[path.relative_to(root).as_posix()] = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
    return out


def diff_stats(ch: Challenge, cond: Condition, workspace: Path) -> dict:
    """Objective size of the final change, independent of how it was made."""
    base = _source_files(ch.fixture)
    if cond.cai_enabled and ch.cai_overlay is not None:
        base.update(_source_files(ch.cai_overlay))
    final = _source_files(workspace)
    added = removed = files = 0
    for rel in sorted(set(base) | set(final)):
        a, b = base.get(rel, "").splitlines(), final.get(rel, "").splitlines()
        if a == b:
            continue
        files += 1
        for line in difflib.ndiff(a, b):
            added += line.startswith("+ ")
            removed += line.startswith("- ")
    return {"diff_files_changed": files, "diff_lines_added": added, "diff_lines_removed": removed}


def grade(ch: Challenge, workspace: Path) -> dict:
    """Run the hidden grader against a copy of the final workspace."""
    out = {"grader_exit_code": None, "success": False, "tests_passed": None, "tests_total": None,
           "pass_rate": None, "runtime_ms": None, "grader_output": ""}
    with tempfile.TemporaryDirectory(prefix="cai-grade-") as tmp:
        subject = Path(tmp) / "workspace"
        grader = Path(tmp) / "grader"
        shutil.copytree(workspace, subject, ignore=shutil.ignore_patterns(*IGNORED_DIRS))
        shutil.copytree(ch.grader_dir, grader)
        argv = [a.replace("{python}", sys.executable).replace("{workspace}", str(subject)) for a in ch.grader_command]
        env = dict(os.environ, CAI_BENCH_WORKSPACE=str(subject))
        try:
            proc = subprocess.run(argv, cwd=grader, env=env, capture_output=True, timeout=ch.grade_timeout)
        except subprocess.TimeoutExpired:
            out["grader_output"] = "grader timed out"
            return out
        except OSError as exc:
            out["grader_output"] = f"cannot launch grader: {exc}"
            return out
    text = proc.stdout.decode(errors="replace")
    out["grader_exit_code"] = proc.returncode
    out["success"] = proc.returncode == 0
    out["grader_output"] = (text + proc.stderr.decode(errors="replace"))[-4000:]
    for line in text.splitlines():
        if line.startswith(RESULT_MARK):
            try:
                extra = json.loads(line[len(RESULT_MARK):])
            except ValueError:
                continue
            for key in ("tests_passed", "tests_total", "runtime_ms"):
                if isinstance(extra.get(key), (int, float)):
                    out[key] = extra[key]
    if out["tests_total"]:
        out["pass_rate"] = round(out["tests_passed"] / out["tests_total"], 4) if out["tests_passed"] is not None else None
    return out


def finish_record(record: dict, ch: Challenge, cond: Condition, workspace: Path, trace: dict) -> dict:
    """Grade a finished workspace and merge trace metrics into ``record``."""
    validate(trace)
    record["synthetic"] = trace["synthetic"]
    record.update({f"agent_{k}": v for k, v in trace["agent"].items()})
    record.update(derive_metrics(trace))
    record.update(diff_stats(ch, cond, workspace))
    record.update(grade(ch, workspace))
    record["status"] = "completed"
    record["failure_category"] = None if record["success"] else "grader_failed"
    return record


def new_record(ch: Challenge, cond: Condition, agent_info: dict, synthetic: bool, **extra) -> dict:
    record = {
        "challenge": ch.id, "category": ch.category, "condition": cond.key, "condition_label": cond.label,
        "status": "pending", "success": None, "failure_category": None, "synthetic": synthetic,
        "wall_seconds": None, "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "prompt_sha256": prompt_digest(build_prompt(ch.description, cond)),
        "trial_timeout_seconds": ch.trial_timeout, "permitted_tools": ",".join(ch.permitted_tools),
    }
    record.update({f"agent_{k}": v for k, v in agent_info.items()})
    record.update(extra)
    return record


def run_trial(ch: Challenge, cond: Condition, agent: Agent, work_root: Path, trial_id: str, **extra) -> dict:
    record = new_record(ch, cond, agent.describe(), agent.synthetic, trial_id=trial_id, **extra)
    missing = ch.missing_requirements()
    if missing:
        record.update(status="skipped", failure_category="missing_requirement:" + ",".join(missing))
        return record
    trial_dir = work_root / trial_id
    workspace = trial_dir / "workspace"
    trial_dir.mkdir(parents=True)
    try:
        record["fixture_digest"] = prepare_workspace(ch, cond, workspace)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        record.update(status="setup_error", failure_category="setup_error", error=str(exc)[-2000:])
        return record
    prompt = build_prompt(ch.description, cond)
    prompt_file = trial_dir / "prompt.md"
    prompt_file.write_text(prompt, encoding="utf-8")
    ctx = TrialContext(ch, cond, workspace, prompt, prompt_file, trial_dir / "trace.json", ch.trial_timeout)
    start = time.perf_counter()
    try:
        trace = agent.run(ctx)
    except AgentTimeout as exc:
        record.update(status="timeout", success=False, failure_category="timeout", error=str(exc),
                      wall_seconds=round(time.perf_counter() - start, 3))
        return record
    except (AgentError, subprocess.TimeoutExpired) as exc:
        record.update(status="agent_error", success=False, failure_category="agent_error", error=str(exc)[-2000:],
                      wall_seconds=round(time.perf_counter() - start, 3))
        return record
    record["wall_seconds"] = round(time.perf_counter() - start, 3)
    (trial_dir / "trace.json").write_text(json.dumps(trace, indent=1), encoding="utf-8")
    return finish_record(record, ch, cond, workspace, trace)


def run_matrix(suite: list[Challenge], conditions: list[str], agent: Agent, out_dir: Path, *,
               repetitions: int, seed: int, keep_workspaces: bool = False, progress=None) -> list[dict]:
    """Run every (challenge, condition, repetition) once, in seeded random order."""
    out_dir.mkdir(parents=True, exist_ok=True)
    if (out_dir / "trials.jsonl").exists():
        raise FileExistsError(f"{out_dir} already contains results; use a new --out directory")
    digests = {ch.id: tree_digest(ch.fixture) for ch in suite}
    plan = [(ch, key, rep) for ch in suite for key in conditions for rep in range(1, repetitions + 1)]
    random.Random(seed).shuffle(plan)
    meta = {
        "run_id": out_dir.name, "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seed": seed, "repetitions": repetitions, "conditions": conditions, "challenges": [c.id for c in suite],
        "agent": agent.describe(), "synthetic": agent.synthetic, "environment": environment(),
        "order": [f"{ch.id}/{key}/{rep}" for ch, key, rep in plan],
    }
    (out_dir / "run.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    work_root = Path(tempfile.mkdtemp(prefix="cai-bench-")) if not keep_workspaces else out_dir / "work"
    records = []
    try:
        with open(out_dir / "trials.jsonl", "a", encoding="utf-8") as fh:
            for index, (ch, key, rep) in enumerate(plan):
                if tree_digest(ch.fixture) != digests[ch.id]:
                    raise RuntimeError(f"fixture of {ch.id} changed during the run; results would be contaminated")
                record = run_trial(ch, CONDITIONS[key], agent, work_root, f"{index:04d}-{ch.id}-{key}-r{rep}",
                                   run_id=out_dir.name, repetition=rep, order_index=index)
                fh.write(json.dumps(record, sort_keys=True) + "\n")
                fh.flush()
                records.append(record)
                if progress:
                    progress(record)
    finally:
        if not keep_workspaces:
            shutil.rmtree(work_root, ignore_errors=True)
    return records
