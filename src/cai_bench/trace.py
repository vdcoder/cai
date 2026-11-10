"""Provider-neutral agent trace format and the metrics derived from it.

A trace is a JSON object (see docs/BENCHMARKS.md):

    {"schema_version": 1,
     "synthetic": false,
     "agent": {"adapter": "...", "provider": "...", "model": "...",
               "model_version": "...", "reasoning": "..."},
     "usage": {"input_tokens": 0, "output_tokens": 0, "reasoning_tokens": null,
               "cache_read_tokens": null, "cache_write_tokens": null,
               "billable_tokens": null, "cost_usd": null},
     "events": [{"type": "turn"}, {"type": "tool_call", "tool": "shell", "ok": true},
                {"type": "edit", "path": "src/x.py", "source_changes": 1},
                {"type": "validation", "ok": false},
                {"type": "experiment", "ok": true}, {"type": "test", "ok": true}]}

``null`` (or an absent key) always means "not measured". It is never read as 0.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import SCHEMA_VERSION

USAGE_FIELDS = ("input_tokens", "output_tokens", "reasoning_tokens", "cache_read_tokens",
                "cache_write_tokens", "billable_tokens", "cost_usd")
EVENT_TYPES = ("turn", "tool_call", "edit", "validation", "experiment", "test")
CHECK_TYPES = ("validation", "experiment", "test")
EVENT_METRICS = ("agent_turns", "tool_calls", "failed_tool_calls", "edit_operations", "source_changes",
                 "corrective_cycles", "experiment_executions", "test_executions")


class TraceError(Exception):
    pass


def empty_trace(adapter: str, *, synthetic: bool, events: list | None = None, **agent: str | None) -> dict:
    info = {"adapter": adapter, "provider": None, "model": None, "model_version": None, "reasoning": None}
    info.update(agent)
    return {"schema_version": SCHEMA_VERSION, "synthetic": synthetic, "agent": info,
            "usage": {f: None for f in USAGE_FIELDS}, "events": events}


def validate(trace: object) -> dict:
    if not isinstance(trace, dict) or trace.get("schema_version") != SCHEMA_VERSION:
        raise TraceError(f"trace must be an object with schema_version {SCHEMA_VERSION}")
    if not isinstance(trace.get("synthetic"), bool):
        raise TraceError("trace.synthetic must be true or false")
    if not isinstance(trace.get("agent"), dict):
        raise TraceError("trace.agent must be an object")
    usage = trace.setdefault("usage", {})
    if not isinstance(usage, dict):
        raise TraceError("trace.usage must be an object")
    for key, value in usage.items():
        if key not in USAGE_FIELDS:
            raise TraceError(f"unknown usage field '{key}'")
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0):
            raise TraceError(f"usage.{key} must be a non-negative number or null")
    events = trace.get("events")
    if events is not None:
        if not isinstance(events, list):
            raise TraceError("trace.events must be an array or null")
        for i, ev in enumerate(events):
            if not isinstance(ev, dict) or ev.get("type") not in EVENT_TYPES:
                raise TraceError(f"events[{i}].type must be one of {EVENT_TYPES}")
            if ev["type"] in CHECK_TYPES + ("tool_call",) and not isinstance(ev.get("ok"), bool):
                raise TraceError(f"events[{i}] ({ev['type']}) requires a boolean 'ok'")
    return trace


def load_trace(path: Path) -> dict:
    try:
        return validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        raise TraceError(f"{path}: {exc}") from None


def corrective_cycles(events: list[dict]) -> int:
    """Number of completed corrective edit cycles.

    A cycle opens when the agent observes a failed check (a ``validation``,
    ``experiment`` or ``test`` event with ``ok`` false). It closes at the next
    check event that is preceded by at least one ``edit`` event made after the
    cycle opened, i.e. when a revised candidate is submitted for validation.
    A check that closes a cycle and fails opens the next one. The definition
    is identical for all conditions.
    """
    cycles = 0
    is_open = False
    edited = False
    for ev in events:
        kind = ev["type"]
        if kind == "edit" and is_open:
            edited = True
        elif kind in CHECK_TYPES:
            if is_open and edited:
                cycles += 1
                is_open = False
            if not ev["ok"]:
                is_open, edited = True, False
    return cycles


def derive_metrics(trace: dict) -> dict:
    """Flatten a trace into metric columns; unavailable values are ``None``."""
    usage = trace.get("usage") or {}
    out: dict = {f: usage.get(f) for f in USAGE_FIELDS}
    inp, outp = out["input_tokens"], out["output_tokens"]
    out["total_tokens"] = inp + outp if inp is not None and outp is not None else None
    events = trace.get("events")
    if events is None:
        out.update({m: None for m in EVENT_METRICS})
        return out
    count = lambda kind: sum(ev["type"] == kind for ev in events)  # noqa: E731
    out.update(
        agent_turns=count("turn"),
        tool_calls=count("tool_call"),
        failed_tool_calls=sum(ev["type"] == "tool_call" and not ev["ok"] for ev in events),
        edit_operations=count("edit"),
        source_changes=sum(int(ev.get("source_changes", 1)) for ev in events if ev["type"] == "edit"),
        corrective_cycles=corrective_cycles(events),
        experiment_executions=count("experiment"),
        test_executions=count("test"),
    )
    return out
