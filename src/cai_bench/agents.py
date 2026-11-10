"""Agent adapters: the provider-neutral boundary between harness and agent.

``ReplayAgent`` is a deterministic scripted "agent" used to validate the
harness without any model or API. ``CommandAgent`` delegates a trial to an
external program supplied by the user. No vendor integration is bundled.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import cai
from cai.adapters import ADAPTERS

from .challenge import Challenge
from .conditions import Condition
from .trace import TraceError, empty_trace, load_trace


@dataclass
class TrialContext:
    challenge: Challenge
    condition: Condition
    workspace: Path
    prompt: str
    prompt_file: Path
    trace_file: Path
    timeout: float


class AgentError(Exception):
    """The agent could not complete the trial (not a grading failure)."""


class AgentTimeout(AgentError):
    pass


class Agent(Protocol):
    name: str
    synthetic: bool

    def describe(self) -> dict: ...

    def run(self, ctx: TrialContext) -> dict:
        """Work on ``ctx.workspace`` and return a trace dict."""


def _subst(argv: list[str], mapping: dict[str, str]) -> list[str]:
    out = []
    for arg in argv:
        for token, value in mapping.items():
            arg = arg.replace(token, value)
        out.append(arg)
    return out


def _cai_env() -> dict[str, str]:
    env = dict(os.environ)
    src = str(Path(cai.__file__).resolve().parents[1])
    env["PYTHONPATH"] = src + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    return env


class ReplayAgent:
    """Replays the scripted steps in a challenge's ``replay.json``.

    Step operations: ``turn``; ``write`` / ``append`` (``content`` or ``from``);
    ``replace`` (``old``, ``new``); ``directive`` (appends a CAI directive
    rendered in ``style``); ``shell`` (``argv``, ``as``: validation |
    experiment | test | other, ``expect``: pass | fail | any); ``cai``
    (``args``, ``expect_exit``).
    """

    name = "replay"
    synthetic = True

    def describe(self) -> dict:
        return {"adapter": self.name, "provider": None, "model": None, "model_version": None, "reasoning": None}

    def run(self, ctx: TrialContext) -> dict:
        ch = ctx.challenge
        if ch.replay is None:
            raise AgentError(f"challenge {ch.id} has no replay script")
        script = json.loads(ch.replay.read_text(encoding="utf-8"))
        steps = script.get(ctx.condition.key)
        if steps is None:
            raise AgentError(f"replay script of {ch.id} has no steps for condition {ctx.condition.key}")
        events: list[dict] = []
        for n, step in enumerate(steps):
            try:
                self._step(ctx, step, events)
            except (OSError, KeyError, ValueError) as exc:
                raise AgentError(f"replay step {n} ({step.get('op')}) failed: {exc!r}") from None
        return empty_trace(self.name, synthetic=True, events=events)

    def _text(self, ctx: TrialContext, step: dict) -> str:
        if "from" in step:
            return (ctx.challenge.root / step["from"]).read_text(encoding="utf-8")
        return step["content"]

    def _step(self, ctx: TrialContext, step: dict, events: list[dict]) -> None:
        op = step["op"]
        ws = ctx.workspace
        if op == "turn":
            events.append({"type": "turn"})
        elif op in ("write", "append", "replace", "directive"):
            path = ws / step["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            old = path.read_text(encoding="utf-8") if path.exists() else ""
            if op == "write":
                new = self._text(ctx, step)
            elif op == "append":
                new = old + self._text(ctx, step)
            elif op == "replace":
                if old.count(step["old"]) != 1:
                    raise ValueError(f"'old' text must occur exactly once in {step['path']}")
                new = old.replace(step["old"], step["new"])
            else:
                body = self._text(ctx, step).rstrip("\n").split("\n") if ("from" in step or "content" in step) else []
                new = old + ADAPTERS[step["style"]].render(step["command"], step.get("name"), body, "", "\n")
            path.write_text(new, encoding="utf-8")
            events.append({"type": "tool_call", "tool": "file_edit", "ok": True})
            events.append({"type": "edit", "path": step["path"], "source_changes": 1})
        elif op == "shell":
            argv = _subst(step["argv"], {"{python}": sys.executable})
            proc = subprocess.run(argv, cwd=ws, capture_output=True, timeout=ctx.timeout, env=_cai_env())
            ok = proc.returncode == 0
            self._expect(step.get("expect", "any"), ok, f"shell {argv}", proc.stderr)
            events.append({"type": "tool_call", "tool": "shell", "ok": ok})
            if step.get("as", "other") != "other":
                events.append({"type": step["as"], "ok": ok})
        elif op == "cai":
            if not ctx.condition.cai_enabled:
                raise ValueError("the cai tool is not available in this condition")
            argv = [sys.executable, "-m", "cai", "--json", *step["args"]]
            proc = subprocess.run(argv, cwd=ws, capture_output=True, timeout=ctx.timeout, env=_cai_env())
            want = step.get("expect_exit")
            if want is not None and proc.returncode != want:
                raise ValueError(f"cai {step['args']} exited {proc.returncode}, expected {want}: "
                                 f"{proc.stdout.decode(errors='replace')[-2000:]}")
            report = json.loads(proc.stdout)
            events.append({"type": "tool_call", "tool": "cai", "ok": proc.returncode == 0})
            if report.get("files_modified"):
                stats = report["stats"]
                events.append({"type": "edit", "path": ",".join(report["files_modified"]), "via": "cai",
                               "source_changes": max(1, stats["evolutions"] + stats["drops"])})
            if proc.returncode == 2:  # rejected by validation: the agent observed a failed check
                events.append({"type": "validation", "ok": False, "via": "cai"})
            for kind, key in (("experiment", "runs"), ("test", "tests")):
                for res in report.get(key, []):
                    if res["status"] != "skipped":
                        events.append({"type": kind, "ok": res["status"] == "passed", "via": "cai", "name": res["name"]})
        else:
            raise ValueError(f"unknown replay op '{op}'")

    @staticmethod
    def _expect(expect: str, ok: bool, what: str, stderr: bytes) -> None:
        if expect == "pass" and not ok or expect == "fail" and ok:
            raise ValueError(f"{what} was expected to {expect}; stderr: {stderr.decode(errors='replace')[-1500:]}")


class CommandAgent:
    """Runs an external agent command for each trial.

    The specification is a JSON file::

        {"adapter": "command",
         "argv": ["my-agent", "--prompt-file", "{prompt_file}", "--trace-out", "{trace_file}"],
         "provider": "...", "model": "...", "model_version": "...", "reasoning": "..."}

    The command is started with the trial workspace as working directory.
    Tokens ``{prompt_file}``, ``{workspace}``, ``{trace_file}``, ``{condition}``,
    ``{challenge}`` and ``{python}`` are substituted; the same values are
    exported as ``CAI_BENCH_*`` variables. If the command writes a trace to
    ``{trace_file}`` it is imported; otherwise every agent metric is recorded
    as unavailable.
    """

    synthetic = False

    def __init__(self, spec: dict) -> None:
        if not (isinstance(spec.get("argv"), list) and spec["argv"]):
            raise AgentError("agent spec requires a non-empty 'argv' array")
        self.spec = spec
        self.name = spec.get("name", "command")

    def describe(self) -> dict:
        return {"adapter": self.name, **{k: self.spec.get(k) for k in ("provider", "model", "model_version", "reasoning")}}

    def run(self, ctx: TrialContext) -> dict:
        mapping = {"{prompt_file}": str(ctx.prompt_file), "{workspace}": str(ctx.workspace),
                   "{trace_file}": str(ctx.trace_file), "{condition}": ctx.condition.key,
                   "{challenge}": ctx.challenge.id, "{python}": sys.executable}
        env = _cai_env() if ctx.condition.cai_enabled else dict(os.environ)
        env.update(CAI_BENCH_PROMPT_FILE=str(ctx.prompt_file), CAI_BENCH_WORKSPACE=str(ctx.workspace),
                   CAI_BENCH_TRACE_FILE=str(ctx.trace_file), CAI_BENCH_CONDITION=ctx.condition.key,
                   CAI_BENCH_CHALLENGE=ctx.challenge.id)
        try:
            proc = subprocess.run(_subst(self.spec["argv"], mapping), cwd=ctx.workspace, env=env,
                                  stdin=subprocess.DEVNULL, capture_output=True, timeout=ctx.timeout)
        except subprocess.TimeoutExpired:
            raise AgentTimeout(f"agent exceeded the trial limit of {ctx.timeout}s") from None
        except OSError as exc:
            raise AgentError(f"cannot launch agent: {exc}") from None
        if proc.returncode != 0:
            raise AgentError(f"agent exited with {proc.returncode}: {proc.stderr.decode(errors='replace')[-2000:]}")
        if ctx.trace_file.exists():
            try:
                trace = load_trace(ctx.trace_file)
            except TraceError as exc:
                raise AgentError(f"agent wrote an invalid trace: {exc}") from None
            for key, value in self.describe().items():
                trace["agent"].setdefault(key, value)
            return trace
        return empty_trace(synthetic=False, events=None, **self.describe())


def load_agent(spec: str) -> Agent:
    if spec == "replay":
        return ReplayAgent()
    try:
        data = json.loads(Path(spec).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AgentError(f"agent must be 'replay' or a JSON spec file: {exc}") from None
    if data.get("adapter") != "command":
        raise AgentError("agent spec: 'adapter' must be \"command\"")
    return CommandAgent(data)
