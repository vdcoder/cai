# CAI Core v1 — progress

Resume point for work interrupted by context or usage limits.

## Completed
- **M1 Parser and configuration** — `cai.json` loading, file discovery, four
  comment adapters, line-oriented directive parser, structured diagnostics.
- **M2 Source transformation** — lifecycle resolution (`engine.py`), rendering,
  `--check` / `--build`, preservation and idempotence tests.

- **M3 Ordered execution** — `#run`, per-experiment snapshots at source-order
  checkpoints, runner protocol (`runner.py`), consolidated report.
- **M4 Persistent tests** — `#test` evolution/drop, `--test [NAME...]`.
- **M5 Safety and telemetry** — lock + roll-back journal (`txn.py`), optional
  incremental manifest (`manifest.py`), `.cai/stats.jsonl` (`stats.py`).

## Next step
- M6 Benchmark infrastructure (`src/cai_bench`, `benchmarks/challenges`).

## Known limitations
- See `docs/LIMITATIONS.md` (written in M7).
