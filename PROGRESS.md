# CAI Core v1 — progress

Resume point for work interrupted by context or usage limits.

## Completed milestones
- **M1 Parser and configuration** — `cai.json`, discovery, four comment
  adapters, line-oriented parser, structured diagnostics.
- **M2 Source transformation** — lifecycle resolution and rendering
  (`engine.py`), `--check` / `--build`, preservation and idempotence.
- **M3 Ordered execution** — `#run`, per-experiment snapshots at source-order
  checkpoints, runner protocol, consolidated report.
- **M4 Persistent tests** — `#test` evolution/drop, `--test [NAME...]`.
- **M5 Safety and telemetry** — lock + roll-back journal, optional incremental
  manifest, `.cai/stats.jsonl`, `--stats`.
- **M6 Benchmark infrastructure** — `cai_bench` (conditions A/B/C, manifests,
  trace format, replay and command agents, isolation, analysis, reports) and
  ten challenges.
- **M7 Documentation and release check** — README, docs/, examples/demo,
  scan micro-benchmark, editable install verified.

## Verified state
- `python -m unittest discover -s tests -t .` → 109 tests pass (Linux, Python 3.13).
- `cai-bench validate` → 30/30 synthetic replay trials pass their graders.
- `pip install -e .` provides working `cai` and `cai-bench` commands.

## Not done / not claimed
- No language-model agent has been benchmarked. There is no evidence yet that
  CAI improves agent speed, cost or accuracy.
- Not yet run on Windows or macOS.
- No packaged release (PyPI) and no CI configuration.

## Open decisions for the project owner
See docs/ARCHITECTURE.md, "Resolved ambiguities worth a second look". The most
consequential: whether a `#defer` may be evolved more than once within one
invocation (currently rejected with E302).

## Next steps
1. Decide the open questions above.
2. Write and test a wrapper for one real agent (trace conversion), then run
   A/B/C trials with repetitions.
3. Grow the suite to 20-30 realistic tasks.
4. CI on Linux, macOS and Windows.
