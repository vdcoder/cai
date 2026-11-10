"""Operational statistics: one JSON record per invocation, kept outside the sources."""
from __future__ import annotations

import json
from pathlib import Path

SUM_FIELDS = (
    "files_scanned", "files_skipped", "evolutions", "drops", "experiments", "experiment_failures",
    "tests_executed", "test_failures", "transformation_errors", "bytes_read", "bytes_written",
    "files_modified", "checkpoints", "recovery_operations",
    "parse_ms", "transform_ms", "runner_ms", "total_ms",
)


def append(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")


def read(path: Path) -> list[dict]:
    records = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    records.append(json.loads(line))
                except ValueError:
                    continue  # a torn final line after a crash is ignored
    except FileNotFoundError:
        pass
    return records


def summarize(path: Path) -> dict:
    records = read(path)
    totals: dict = {f: 0 for f in SUM_FIELDS}
    directives: dict[str, int] = {}
    modes: dict[str, int] = {}
    for rec in records:
        for f in SUM_FIELDS:
            totals[f] += rec.get(f, 0)
        for cmd, n in rec.get("directives", {}).items():
            directives[cmd] = directives.get(cmd, 0) + n
        modes[rec.get("mode", "?")] = modes.get(rec.get("mode", "?"), 0) + 1
    for f in SUM_FIELDS:
        if f.endswith("_ms"):
            totals[f] = round(totals[f], 3)
    return {"stats_file": str(path), "invocations": len(records), "by_mode": modes,
            "directives": directives, "totals": totals, "last": records[-1] if records else None}


def format_summary(summary: dict) -> str:
    lines = [f"statistics: {summary['stats_file']}", f"invocations: {summary['invocations']}"]
    if summary["by_mode"]:
        lines.append("by mode: " + ", ".join(f"{m}={n}" for m, n in sorted(summary["by_mode"].items())))
    if summary["directives"]:
        lines.append("directives parsed: " + ", ".join(f"#{c}={n}" for c, n in sorted(summary["directives"].items())))
    for key, value in summary["totals"].items():
        lines.append(f"  {key:24} {value}")
    return "\n".join(lines) + "\n"
