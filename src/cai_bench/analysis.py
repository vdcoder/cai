"""Aggregation and reporting. Correctness and efficiency are kept apart."""
from __future__ import annotations

import csv
import json
import math
import random
import statistics
from pathlib import Path

EFFICIENCY = ("wall_seconds", "total_tokens", "billable_tokens", "cost_usd", "agent_turns", "tool_calls",
              "failed_tool_calls", "edit_operations", "source_changes", "corrective_cycles",
              "experiment_executions", "test_executions", "diff_lines_added", "diff_lines_removed")
MIN_N_FOR_CI = 5


def read_trials(out_dir: Path) -> list[dict]:
    with open(out_dir / "trials.jsonl", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if n == 0:
        return None
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4))


def bootstrap_ci(values: list[float], seed: int = 0, rounds: int = 2000) -> tuple[float, float] | None:
    """95% percentile bootstrap interval of the mean; None below MIN_N_FOR_CI."""
    if len(values) < MIN_N_FOR_CI:
        return None
    rng = random.Random(seed)
    means = sorted(statistics.fmean(rng.choices(values, k=len(values))) for _ in range(rounds))
    return (round(means[int(0.025 * rounds)], 4), round(means[int(0.975 * rounds) - 1], 4))


def describe(values: list[float]) -> dict:
    """Summary of the available values; ``n`` says how many were measured."""
    if not values:
        return {"n": 0, "mean": None, "median": None, "stdev": None, "ci95": None}
    return {
        "n": len(values),
        "mean": round(statistics.fmean(values), 4),
        "median": round(statistics.median(values), 4),
        "stdev": round(statistics.stdev(values), 4) if len(values) > 1 else None,
        "ci95": bootstrap_ci(values),
    }


def summarize_group(trials: list[dict]) -> dict:
    attempted = [t for t in trials if t["status"] != "skipped"]
    wins = [t for t in attempted if t.get("success")]
    failures: dict[str, int] = {}
    for t in trials:
        if t.get("failure_category"):
            failures[t["failure_category"]] = failures.get(t["failure_category"], 0) + 1
    rates = [t["pass_rate"] for t in attempted if t.get("pass_rate") is not None]

    def metric(rows: list[dict], key: str) -> dict:
        return describe([float(t[key]) for t in rows if t.get(key) is not None])

    return {
        "trials": len(trials),
        "attempted": len(attempted),
        "skipped": len(trials) - len(attempted),
        "successes": len(wins),
        "success_rate": round(len(wins) / len(attempted), 4) if attempted else None,
        "success_rate_ci95": wilson(len(wins), len(attempted)),
        "final_test_pass_rate": describe(rates),
        "failure_categories": failures,
        "synthetic_trials": sum(bool(t.get("synthetic")) for t in trials),
        # efficiency over every attempted trial, successful or not
        "all_attempts": {k: metric(attempted, k) for k in EFFICIENCY},
        # efficiency over successful trials only: subject to selection bias,
        # always read next to success_rate
        "successful_only": {k: metric(wins, k) for k in EFFICIENCY},
    }


def _paired_reduction(trials: list[dict], key: str, base: str, other: str) -> dict | None:
    """Relative reduction of the per-task mean of ``key``, over tasks where both
    conditions have measurements. Positive means ``other`` used less."""
    per_task: dict[str, dict[str, list[float]]] = {}
    for t in trials:
        if t["status"] != "skipped" and t.get(key) is not None and t["condition"] in (base, other):
            per_task.setdefault(t["challenge"], {}).setdefault(t["condition"], []).append(float(t[key]))
    pairs = [(statistics.fmean(v[base]), statistics.fmean(v[other]))
             for v in per_task.values() if base in v and other in v]
    total_base = sum(a for a, _ in pairs)
    if not pairs or total_base == 0:
        return None
    return {"tasks_compared": len(pairs), "baseline_mean": round(total_base / len(pairs), 4),
            "other_mean": round(sum(b for _, b in pairs) / len(pairs), 4),
            "relative_reduction": round(1 - sum(b for _, b in pairs) / total_base, 4)}


def summarize(trials: list[dict], run_meta: dict | None = None) -> dict:
    conditions = sorted({t["condition"] for t in trials})
    challenges = sorted({t["challenge"] for t in trials})
    synthetic = [t for t in trials if t.get("synthetic")]
    kind = "synthetic" if len(synthetic) == len(trials) else "mixed" if synthetic else "agent"
    summary = {
        "run": run_meta or {},
        "evidence": kind,
        "notice": {
            "synthetic": "SYNTHETIC HARNESS VALIDATION. These trials were produced by a deterministic scripted "
                         "replay, not by a language model. They show that the harness works; they say nothing "
                         "about agent performance with or without CAI.",
            "mixed": "MIXED DATA. Some trials are synthetic replays; they must be excluded before drawing any "
                     "conclusion about agent performance.",
            "agent": "Agent trials. Check sample sizes and confidence intervals before comparing conditions.",
        }[kind],
        "aggregate": {c: summarize_group([t for t in trials if t["condition"] == c]) for c in conditions},
        "per_task": {ch: {c: summarize_group([t for t in trials if t["challenge"] == ch and t["condition"] == c])
                          for c in conditions} for ch in challenges},
        "comparisons_vs_A": {},
    }
    for other in conditions:
        if other == "A" or "A" not in conditions:
            continue
        summary["comparisons_vs_A"][other] = {
            key: _paired_reduction(trials, key, "A", other)
            for key in ("tool_calls", "total_tokens", "wall_seconds", "corrective_cycles")}
    return summary


def _fmt(value: object) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.3g}" if abs(value) < 1000 else f"{value:.0f}"
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_fmt(v) for v in value) + "]"
    return str(value)


def _stat(d: dict) -> str:
    return "n/a (0 measured)" if not d["n"] else f"{_fmt(d['mean'])} / {_fmt(d['median'])} (n={d['n']})"


def markdown(summary: dict) -> str:
    run = summary["run"]
    lines = ["# CAI benchmark report", "", f"> **{summary['notice']}**", ""]
    if run:
        agent = run.get("agent", {})
        lines += [f"- run: `{run.get('run_id')}` created {run.get('created_at')}",
                  f"- agent adapter: `{agent.get('adapter')}`, model: {_fmt(agent.get('model'))} "
                  f"(version {_fmt(agent.get('model_version'))}, reasoning {_fmt(agent.get('reasoning'))})",
                  f"- repetitions per cell: {run.get('repetitions')}, order seed: {run.get('seed')}",
                  f"- environment: {json.dumps(run.get('environment', {}))}", ""]
    lines += ["## Correctness (all attempted trials)", "",
              "| condition | attempted | skipped | successes | success rate | 95% CI (Wilson) | mean final test pass rate | failures |",
              "|---|---|---|---|---|---|---|---|"]
    for cond, g in summary["aggregate"].items():
        lines.append(f"| {cond} | {g['attempted']} | {g['skipped']} | {g['successes']} | {_fmt(g['success_rate'])} | "
                     f"{_fmt(g['success_rate_ci95'])} | {_fmt(g['final_test_pass_rate']['mean'])} | "
                     f"{json.dumps(g['failure_categories']) if g['failure_categories'] else '-'} |")
    for title, key, note in (
        ("Efficiency over all attempted trials", "all_attempts",
         "Mean / median (n = trials where the metric was measured). `n/a` means the metric was not "
         "available; it is never treated as zero."),
        ("Efficiency over successful trials only", "successful_only",
         "Restricted to trials that passed grading. This view suffers from success-only selection bias: "
         "a condition that fails the hard tasks looks cheaper here. Read it together with the success rates above."),
    ):
        lines += ["", f"## {title}", "", note, "",
                  "| condition | wall s | total tokens | tool calls | edit ops | source changes | corrective cycles (median) | experiments | tests |",
                  "|---|---|---|---|---|---|---|---|---|"]
        for cond, g in summary["aggregate"].items():
            m = g[key]
            lines.append(f"| {cond} | {_stat(m['wall_seconds'])} | {_stat(m['total_tokens'])} | {_stat(m['tool_calls'])} | "
                         f"{_stat(m['edit_operations'])} | {_stat(m['source_changes'])} | "
                         f"{_fmt(m['corrective_cycles']['median'])} (n={m['corrective_cycles']['n']}) | "
                         f"{_stat(m['experiment_executions'])} | {_stat(m['test_executions'])} |")
        lines += ["", "Variance: " + "; ".join(
            f"{cond} wall stdev {_fmt(g[key]['wall_seconds']['stdev'])}, 95% CI of mean {_fmt(g[key]['wall_seconds']['ci95'])}"
            for cond, g in summary["aggregate"].items())
            + f". Intervals need at least {MIN_N_FOR_CI} measurements."]
    if summary["comparisons_vs_A"]:
        lines += ["", "## Relative reduction versus condition A", "",
                  "Per-task means, compared only over tasks where both conditions were measured; all attempted "
                  "trials are included regardless of success. Positive = fewer than A. This is a descriptive "
                  "ratio, not a significance test.", "",
                  "| condition | tool calls | total tokens | wall seconds | corrective cycles |", "|---|---|---|---|---|"]
        for cond, comp in summary["comparisons_vs_A"].items():
            cells = [("n/a" if comp[k] is None else f"{comp[k]['relative_reduction']:+.1%} ({comp[k]['tasks_compared']} tasks)")
                     for k in ("tool_calls", "total_tokens", "wall_seconds", "corrective_cycles")]
            lines.append(f"| {cond} | " + " | ".join(cells) + " |")
    lines += ["", "## Per task", "", "| task | condition | attempted | success rate | wall s (mean/median) | tool calls | corrective cycles (median) |",
              "|---|---|---|---|---|---|---|"]
    for task, conds in summary["per_task"].items():
        for cond, g in conds.items():
            m = g["all_attempts"]
            lines.append(f"| {task} | {cond} | {g['attempted']} | {_fmt(g['success_rate'])} | {_stat(m['wall_seconds'])} | "
                         f"{_stat(m['tool_calls'])} | {_fmt(m['corrective_cycles']['median'])} |")
    return "\n".join(lines) + "\n"


def write_reports(out_dir: Path) -> dict:
    trials = read_trials(out_dir)
    run_meta = json.loads((out_dir / "run.json").read_text(encoding="utf-8")) if (out_dir / "run.json").exists() else None
    summary = summarize(trials, run_meta)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (out_dir / "report.md").write_text(markdown(summary), encoding="utf-8")
    skip = {"grader_output", "error"}
    columns = sorted({k for t in trials for k in t} - skip)
    with open(out_dir / "trials.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for t in trials:  # None is written as an empty cell: "unavailable", not 0
            writer.writerow({k: ("" if t.get(k) is None else t.get(k)) for k in columns})
    with open(out_dir / "summary.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["scope", "condition", "evidence", "attempted", "successes", "success_rate", "population",
                         "metric", "n_measured", "mean", "median", "stdev"])
        scopes = [("aggregate", summary["aggregate"])] + list(summary["per_task"].items())
        for scope, conds in scopes:
            for cond, g in conds.items():
                for population in ("all_attempts", "successful_only"):
                    for metric_name, d in g[population].items():
                        writer.writerow([scope, cond, summary["evidence"], g["attempted"], g["successes"],
                                         "" if g["success_rate"] is None else g["success_rate"], population, metric_name,
                                         d["n"], *("" if d[k] is None else d[k] for k in ("mean", "median", "stdev"))])
    return summary
