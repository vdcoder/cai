# CAI Core v1 — progress

Resume point for work interrupted by context or usage limits.

## Completed
- **M1 Parser and configuration** — `cai.json` loading, file discovery, four
  comment adapters, line-oriented directive parser, structured diagnostics.
- **M2 Source transformation** — lifecycle resolution (`engine.py`), rendering,
  `--check` / `--build`, preservation and idempotence tests.

## Next step
- M3 Ordered execution (`#run`, checkpoints, runner protocol).

## Known limitations
- See `docs/LIMITATIONS.md` (written in M7).
