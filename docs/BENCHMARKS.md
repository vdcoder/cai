# Benchmark harness

The harness answers one question honestly: *does CAI change how well a coding
agent performs?* It measures; it does not assume the answer.

> **Current evidence: none.** Only deterministic replay scripts have been run
> through the harness. They validate the machinery and say nothing about
> language-model agents. Do not quote any number from a `synthetic` report as
> a performance result.

## Conditions

| key | name | agent may use |
|---|---|---|
| A | standard editing | normal editing, search/replace, shell |
| B | standard editing + scratchpad comments | A, plus temporary planning comments it must remove |
| C | CAI-assisted editing | A, plus the six directives and the `cai` tool (not obligatory) |

B exists to separate the effect of "a place to think in the file" from the
effect of the CAI engine. The three prompts share the task text and rules and
differ only in the workflow section (`cai_bench/conditions.py`); the SHA-256
of each prompt is stored with every trial. In condition C the workspace
additionally receives a CAI overlay (`cai.json` and a runner script).

## Two kinds of evidence

| | synthetic harness validation | agent benchmark |
|---|---|---|
| produced by | `ReplayAgent` (scripted steps in `replay.json`) | a real agent via `CommandAgent` or the manual workflow |
| `synthetic` field | `true` | `false` |
| report banner | `SYNTHETIC HARNESS VALIDATION` | `Agent trials` |
| can show | that isolation, grading, metrics and reports work | differences between conditions |

A report containing both kinds is labelled `MIXED DATA`. Separately, the
*engine* is verified by the unit tests in `tests/`; those are not benchmarks
of any kind.

## Commands

```bash
cai-bench list
```

```bash
cai-bench validate --out /tmp/cai-bench-validate
```

```bash
cai-bench run --agent my_agent.json --reps 5 --seed 1 --out benchmarks/results/run-001
```

```bash
cai-bench report benchmarks/results/run-001
```

`validate` replays every challenge once per condition and fails if any replay
does not pass its grader. `run` executes challenges × conditions × repetitions
in a seeded random order. Each results directory contains `run.json` (seed,
order, agent, environment), `trials.jsonl`, `trials.csv`, `summary.json`,
`summary.csv` and `report.md`.

## Challenge manifest

`benchmarks/challenges/<id>/challenge.json`:

```json
{
  "schema_version": 1,
  "id": "py-bug-repair",
  "title": "Repair a binary search",
  "category": "bug_repair",
  "description": "Task text shown to the agent.",
  "fixture": "fixture",
  "cai_overlay": "../../overlays/python",
  "setup": [["{python}", "-c", "pass"]],
  "permitted_tools": ["file_edit", "search", "shell"],
  "limits": { "trial_timeout_seconds": 900, "grade_timeout_seconds": 60 },
  "grader": { "dir": "grader", "command": ["{python}", "grade.py"] },
  "success_criteria": "Human-readable statement of what the grader checks.",
  "requires": ["g++"],
  "replay": "replay.json"
}
```

- `fixture/` is the starting repository. `grader/` is never copied into the
  agent's workspace and must not be inside the fixture.
- `setup` commands run in the fresh workspace before the agent starts.
- `requires` lists executables; if one is missing the trial is recorded as
  `skipped`, not failed.
- **Grader protocol:** after the agent stops, the workspace is copied to a new
  directory, the grader directory to another, and `grader.command` runs in the
  grader copy with `CAI_BENCH_WORKSPACE` pointing at the workspace copy. Exit
  status 0 is success. A line
  `CAI_BENCH_RESULT {"tests_passed": 3, "tests_total": 4, "runtime_ms": 12.5}`
  on stdout adds the final pass rate and a runtime measurement.

The initial suite:

| id | category |
|---|---|
| `py-small-function` | small function implementation |
| `py-refactor-report` | multi-function refactoring |
| `py-bug-repair` | bug repair |
| `py-missing-target` | missing-target recovery |
| `py-optimize-pairs` | iterative algorithm optimisation (reports runtime) |
| `py-write-tests` | unit-test creation (mutation-checked) |
| `cpp-ring-buffer` | C++ implementation (needs `g++`) |
| `py-lru-cache` | Python implementation |
| `py-multifile-currency` | multi-file change |
| `py-parse-duration` | repeated failed experiments, then correction |

## Isolation and controls

- Every trial starts from a fresh copy of the fixture; the copy's digest is
  checked against the fixture, and the fixture's digest is re-checked before
  each trial, so a trial cannot alter what later trials start from.
- Workspaces are separate temporary directories and are deleted afterwards
  (`--keep-workspaces` retains them). Grading uses yet another copy.
- Trial order is shuffled with `--seed`; `--reps` repeats every cell.
- Recorded per run: agent adapter, provider, model, model version, reasoning
  configuration (as declared in the agent spec), platform, CPU count, Python
  and CAI versions. Recorded per trial: prompt hash, time limit, permitted
  tools.
- **Not enforced by the harness:** tool permissions inside the agent, hardware
  load, network conditions and provider-side model changes. Keep them constant
  yourself, interleave conditions (the random order does this) and record the
  date.

## Trace format

Agents report what they did in a provider-neutral JSON trace:

```json
{
  "schema_version": 1,
  "synthetic": false,
  "agent": {"adapter": "my-wrapper", "provider": "…", "model": "…",
            "model_version": "…", "reasoning": "…"},
  "usage": {"input_tokens": 12000, "output_tokens": 900, "reasoning_tokens": null,
            "cache_read_tokens": null, "cache_write_tokens": null,
            "billable_tokens": null, "cost_usd": null},
  "events": [
    {"type": "turn"},
    {"type": "tool_call", "tool": "shell", "ok": true},
    {"type": "edit", "path": "src/x.py", "source_changes": 1},
    {"type": "validation", "ok": false},
    {"type": "experiment", "ok": true},
    {"type": "test", "ok": true}
  ]
}
```

`null` or a missing usage field means *not measured*. If `events` is `null`,
every event-derived metric is unavailable. Unavailable values are stored as
`null` (empty CSV cells), excluded from means, and reported with the number
of trials that did measure them. They are never counted as zero.

Derived metrics:

| metric | definition |
|---|---|
| `agent_turns` | `turn` events |
| `tool_calls`, `failed_tool_calls` | `tool_call` events, and those with `ok: false` |
| `edit_operations` | `edit` events (tool invocations that changed source) |
| `source_changes` | sum of `source_changes` over `edit` events (default 1 each). For a CAI consolidation the replay adapter reports the number of evolutions and drops applied, so one `cai` call is not equated with one edit, nor inflated |
| `corrective_cycles` | see below |
| `experiment_executions`, `test_executions` | `experiment` / `test` events |
| `total_tokens` | `input_tokens + output_tokens`, only if both are present |
| `diff_lines_added/removed`, `diff_files_changed` | computed by the harness from fixture vs final workspace, independent of the trace |
| `wall_seconds` | measured by the harness around the agent call |
| `success`, `pass_rate`, `runtime_ms` | from the grader |

**Corrective edit cycle.** A cycle opens when the agent observes a failed
check: a `validation`, `experiment` or `test` event with `ok: false`. It
closes at the next check event that follows at least one `edit` made after
the cycle opened, that is, when a revised candidate is submitted for
validation. A closing check that fails opens the next cycle. Re-running a
check without editing does not count. The rule is identical for all
conditions; a `cai` invocation rejected for invalid directives counts as a
failed `validation`.

## Running real agent trials

No vendor integration ships with CAI, and none is simulated. Two supported
routes:

**1. External command (`CommandAgent`).** Write a wrapper around your agent
and describe it in a JSON spec:

```json
{
  "adapter": "command",
  "name": "my-agent",
  "argv": ["my-agent-wrapper", "--prompt-file", "{prompt_file}", "--trace-out", "{trace_file}"],
  "provider": "…", "model": "…", "model_version": "…", "reasoning": "…"
}
```

The command starts in the trial workspace with `CAI_BENCH_PROMPT_FILE`,
`CAI_BENCH_WORKSPACE`, `CAI_BENCH_TRACE_FILE`, `CAI_BENCH_CONDITION` and
`CAI_BENCH_CHALLENGE` set; in condition C the `cai` module is importable
(`python -m cai`). The wrapper must restrict the agent to the workspace, stop
when the agent is done, and should write a trace. Without a trace the trial is
still graded and timed, with all agent metrics unavailable. A non-zero exit is
recorded as `agent_error`, exceeding the time limit as `timeout`.

Headless agent CLIs that print usage and turn counts in a machine-readable
form can be wrapped this way; converting their output to the trace format is
the wrapper's job. No such wrapper is included because none has been tested
here, and a subscription to a chat product does not imply API or headless
access.

**2. Manual or externally orchestrated trials.**

```bash
cai-bench prepare py-bug-repair C --out /tmp/trials/bug-C-1
```

Give `/tmp/trials/bug-C-1/prompt.md` to the agent with
`/tmp/trials/bug-C-1/workspace` as its working directory. When it has
finished:

```bash
cai-bench grade /tmp/trials/bug-C-1 --trace trace.json --wall-seconds 184 --results benchmarks/results/manual-001
```

```bash
cai-bench report benchmarks/results/manual-001
```

`--trace` and `--wall-seconds` are optional; whatever was not captured stays
unavailable.

## Reading the report

- **Correctness first.** Success rate per condition with a Wilson 95%
  interval, mean final test pass rate, failure categories.
- **Efficiency twice.** Once over all attempted trials and once over
  successful trials only. The second view is biased towards any condition that
  fails the hard tasks; it is labelled as such and must be read next to the
  success rates. A condition that uses fewer tokens but succeeds less often is
  not an improvement.
- **Reductions versus A** are per-task means compared only over tasks where
  both conditions have measurements, across all attempted trials. They are
  descriptive ratios without a significance test.
- **Variance.** Standard deviations, plus bootstrap 95% intervals of the mean
  when at least five measurements exist. With fewer, no interval is shown.

Before making any claim: use at least 20–30 realistic tasks, several
repetitions per cell, a fixed model version, and report all three conditions
including failures.

## Adding a challenge

Create `benchmarks/challenges/<id>/` with `challenge.json`, `fixture/`,
`grader/` and, to keep `cai-bench validate` meaningful, a `replay.json` with
step lists for `A`, `B` and `C` (operations are documented in
`cai_bench/agents.py`). Check that the grader fails on the untouched fixture;
`tests/test_bench.py` enforces this for the bundled suite.
