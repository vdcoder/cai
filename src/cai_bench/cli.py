"""``cai-bench`` command line."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .agents import AgentError, load_agent
from .analysis import write_reports
from .challenge import ManifestError, load_challenge, load_suite, tree_digest
from .conditions import CONDITIONS, build_prompt
from .trace import TraceError, empty_trace, load_trace
from .trial import finish_record, new_record, prepare_workspace, run_matrix

DEFAULT_SUITE = "benchmarks/challenges"


def _suite(args) -> list:
    only = None if args.challenges in (None, "all") else args.challenges.split(",")
    return load_suite(Path(args.suite), only)


def cmd_list(args) -> int:
    for ch in _suite(args):
        missing = ch.missing_requirements()
        note = f"  [missing: {', '.join(missing)}]" if missing else ""
        print(f"{ch.id:28} {ch.category:28} {ch.title}{note}")
    return 0


def cmd_run(args) -> int:
    suite = _suite(args)
    agent = load_agent(args.agent)
    conditions = args.conditions.split(",")
    for key in conditions:
        if key not in CONDITIONS:
            raise ManifestError(f"unknown condition '{key}' (use A, B, C)")
    out = Path(args.out or f"benchmarks/results/{time.strftime('%Y%m%d-%H%M%S')}-{agent.name}")

    def progress(rec: dict) -> None:
        outcome = "pass" if rec.get("success") else rec["status"] if rec["status"] != "completed" else "FAIL"
        print(f"  {rec['trial_id']:48} {outcome}", file=sys.stderr)

    run_matrix(suite, conditions, agent, out, repetitions=args.reps, seed=args.seed,
               keep_workspaces=args.keep_workspaces, progress=progress)
    summary = write_reports(out)
    print(f"evidence: {summary['evidence']}")
    print(summary["notice"])
    for cond, g in summary["aggregate"].items():
        print(f"condition {cond}: {g['successes']}/{g['attempted']} succeeded, {g['skipped']} skipped")
    print(f"results: {out}/report.md, summary.json, summary.csv, trials.csv, trials.jsonl")
    return 0


def cmd_validate(args) -> int:
    """Self-check of the harness with the deterministic replay agent."""
    args.agent, args.reps, args.keep_workspaces = "replay", 1, False
    code = cmd_run(args)
    out = Path(args.out)
    bad = [json.loads(line) for line in (out / "trials.jsonl").read_text().splitlines()]
    bad = [t for t in bad if t["status"] != "skipped" and not t.get("success")]
    for t in bad:
        print(f"REPLAY FAILED {t['trial_id']}: {t.get('error') or t.get('grader_output')}", file=sys.stderr)
    return code or (1 if bad else 0)


def cmd_prepare(args) -> int:
    ch = load_challenge(Path(args.suite) / args.challenge)
    cond = CONDITIONS[args.condition]
    out = Path(args.out)
    out.mkdir(parents=True)
    digest = prepare_workspace(ch, cond, out / "workspace")
    prompt = build_prompt(ch.description, cond)
    (out / "prompt.md").write_text(prompt, encoding="utf-8")
    record = new_record(ch, cond, {"adapter": "manual"}, False, trial_id=out.name, fixture_digest=digest,
                        suite=str(Path(args.suite).resolve()), prepared_epoch=time.time())
    (out / "trial.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(f"workspace: {out / 'workspace'}\nprompt:    {out / 'prompt.md'}\n"
          f"When the agent has finished: cai-bench grade {out} [--trace TRACE.json] --results DIR")
    return 0


def cmd_grade(args) -> int:
    trial_dir = Path(args.trial_dir)
    record = json.loads((trial_dir / "trial.json").read_text(encoding="utf-8"))
    ch = load_challenge(Path(record.pop("suite")) / record["challenge"])
    if tree_digest(ch.fixture) != record["fixture_digest"]:
        raise ManifestError("the challenge fixture changed since this trial was prepared")
    cond = CONDITIONS[record["condition"]]
    started = record.pop("prepared_epoch")
    if args.trace:
        trace = load_trace(Path(args.trace))
    else:  # nothing was captured: every agent metric is unavailable
        trace = empty_trace("manual", synthetic=False, events=None)
    record["wall_seconds"] = args.wall_seconds  # only if the operator measured it
    record["prepared_to_graded_seconds"] = round(time.time() - started, 1)
    finish_record(record, ch, cond, trial_dir / "workspace", trace)
    results = Path(args.results)
    results.mkdir(parents=True, exist_ok=True)
    with open(results / "trials.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")
    print(f"{record['challenge']} [{record['condition']}]: {'success' if record['success'] else 'FAILED'}")
    print(f"recorded in {results / 'trials.jsonl'}; run: cai-bench report {results}")
    return 0


def cmd_report(args) -> int:
    summary = write_reports(Path(args.results))
    print(summary["notice"])
    print(f"wrote {args.results}/report.md, summary.json, summary.csv, trials.csv")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="cai-bench", description="Benchmark harness for CAI-assisted agent workflows.")
    p.add_argument("--suite", default=DEFAULT_SUITE, help=f"challenge directory (default: {DEFAULT_SUITE})")
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("list", help="list challenges")
    s.add_argument("--challenges", default="all")
    s.set_defaults(fn=cmd_list)
    for name, fn, text in (("run", cmd_run, "run trials with an agent adapter"),
                           ("validate", cmd_validate, "run every replay script once (synthetic harness check)")):
        s = sub.add_parser(name, help=text)
        s.add_argument("--challenges", default="all", help="comma-separated ids (default: all)")
        s.add_argument("--conditions", default="A,B,C")
        s.add_argument("--seed", type=int, default=0, help="seed of the randomized trial order")
        s.add_argument("--out", required=(name == "validate"), help="results directory (must be new)")
        if name == "run":
            s.add_argument("--agent", required=True, help="'replay' or path to a command-agent JSON spec")
            s.add_argument("--reps", type=int, default=1, help="repetitions per challenge and condition")
            s.add_argument("--keep-workspaces", action="store_true")
        s.set_defaults(fn=fn)
    s = sub.add_parser("prepare", help="create a clean workspace and prompt for a manual/external trial")
    s.add_argument("challenge")
    s.add_argument("condition", choices=sorted(CONDITIONS))
    s.add_argument("--out", required=True)
    s.set_defaults(fn=cmd_prepare)
    s = sub.add_parser("grade", help="grade a prepared trial and import its trace")
    s.add_argument("trial_dir")
    s.add_argument("--trace", help="trace JSON in the documented format")
    s.add_argument("--wall-seconds", type=float, default=None, help="measured agent working time, if known")
    s.add_argument("--results", required=True, help="results directory to append to")
    s.set_defaults(fn=cmd_grade)
    s = sub.add_parser("report", help="(re)generate CSV/JSON/Markdown reports for a results directory")
    s.add_argument("results")
    s.set_defaults(fn=cmd_report)
    args = p.parse_args(argv)
    try:
        return args.fn(args)
    except (ManifestError, AgentError, TraceError, FileExistsError, FileNotFoundError, RuntimeError) as exc:
        print(f"cai-bench: error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
