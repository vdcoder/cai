# Architecture

## Layout

```
src/cai/            the engine (standard library only)
  config.py         cai.json loading and validation
  adapters.py       the four comment styles: recognise and render directives
  parser.py         text -> [ordinary text | Directive] segments + diagnostics
  discovery.py      glob discovery, deterministic file order, UTF-8/BOM handling
  engine.py         lifecycle resolution (build_plan) and rendering (render_file)
  runner.py         snapshots, subprocess execution, timeout, output caps
  txn.py            workspace lock, roll-back journal, recovery
  manifest.py       optional incremental-scan manifest
  stats.py          statistics log and summary
  core.py           one invocation, end to end
  cli.py, report.py argument parsing and human-readable output
src/cai_bench/      the benchmark harness (separate package, see BENCHMARKS.md)
benchmarks/         challenges, CAI overlays, scan micro-benchmark
examples/demo/      reference project
tests/              functional regression suite (unittest)
```

## Data flow of one invocation

```
cai.json ─► discover ─► parse ─► build_plan ─► render (per checkpoint, final)
                                     │              │
                                diagnostics     snapshots ─► runner ─► results
                                     │              │
                                     └── any error: stop, exit 2
                                                    ▼
                                      txn.commit (journal, replace, unlink)
                                                    ▼
                                    report + stats + manifest
```

**Parser.** Line oriented and adapter driven. A file becomes a list of
segments; ordinary text segments are kept verbatim, so joining the raw
segments reproduces the input exactly. A file with no `#command` token at all
takes a fast path and is never split into lines. The parser never raises;
it returns diagnostics.

**Plan.** `build_plan` walks all directives in processing order and gives each
named block a *history*: a list of `(operation index, status, body)` states.
Nothing is mutated in place. The state of the workspace "as of operation p"
is therefore a pure function of the plan, which is what makes checkpoints
cheap and exact: `render_file(plan, file, p)` replays only history entries
before `p`. The final consolidated source is the same function with `p = ∞`.

**Execution.** For each pending run, the files that differ from disk at its
checkpoint are rendered and overlaid on a fresh copy of the workspace. The
runner is started there. All experiments finish before anything is committed.

**Commit.** See "Atomicity" below.

## Design decisions

These are the points where the specification left room; each is the simplest
behaviour that keeps the contract, and each is covered by tests.

1. **The source file is the only state.** Active `#defer`, `#test` and pending
   `#run` blocks live in the source as comments. `.cai/` holds only the lock,
   the journal, statistics, the optional manifest and the last report; deleting
   it loses no directive.
2. **Materialisation happens at the placeholder.** `#evolve` text is appended
   wherever the agent happens to be writing; the code lands where the
   `#defer` sits, with the placeholder's indentation.
3. **Whole-invocation validation.** Any invalid directive rejects the entire
   invocation. Partial consolidation would make source-order semantics
   depend on which errors happened to be present.
4. **Execute, then commit.** Experiments run on snapshots before the commit, so
   an interrupted invocation consumed nothing and can simply be repeated.
5. **Roll-back, not roll-forward, recovery.** An interrupted commit is undone,
   because its experiment results may never have reached the agent.
6. **Global names, path-ordered files.** One namespace keeps reports and
   `--test NAME` unambiguous. Cross-file order is a documented rule (path
   order), not a claim about chronology.
7. **Blank-line policy.** The one deliberate deviation from byte-for-byte
   preservation: when a removed directive sat between two blank lines (or a
   blank line and a file boundary), one blank line goes with it. Otherwise
   every consolidation would leave double gaps behind.
8. **Full scan by default.** Parsing is linear and fast (about 0.16 s for
   2,000 directive-free files of 200 lines). The manifest is opt-in.

## Resolved ambiguities worth a second look

The contract asked for these to be surfaced rather than decided silently.

| topic | chosen behaviour | alternative |
|---|---|---|
| Evolving an already-evolved `#defer` in the same invocation | Rejected with `E302`. The spec says a deferred block "remains available until evolved". | Allow repeated `#evolve` of the same name before consolidation (last one wins, runs in between see intermediate versions). This would serve "cheaper to change its mind" more directly and is a small change in `engine.build_plan`. |
| "Evolve a pending run" vs "reject evolution after the run's checkpoint" | Allowed only while no source-state change lies between the `#run` and the `#evolve`; otherwise `E304`. | Always reject, or always allow and re-point the run. |
| `--build` with pending runs | Runs stay in the source and execute later against the state at that time; `--discard-runs` removes them. | Refuse to build, or always discard. |
| Does `--test` write files? | Yes, it consolidates first (like `--build`), then tests the final state. | Test the consolidated view without writing. |
| Scope of names | Workspace-wide. | Per file. |

## Atomicity

Filesystems offer atomic replacement of one file, not of several. CAI
therefore makes multi-file consolidation *recoverable* rather than claiming it
is atomic:

1. Re-read every file about to change; abort if any differs from what was
   parsed (another writer was active).
2. Stage the original and the new content of each file under
   `.cai/txn/`, flushed to disk.
3. Write `journal.json` atomically (hashes of both versions per file).
4. `os.replace` each target.
5. Delete `journal.json`: the commit point.

A journal found at start-up means step 5 was not reached: each file that
holds the new content is restored from its staged original. A file matching
neither version was edited in between; CAI refuses to overwrite it, keeps the
staged originals and reports `E512`. A torn state can exist on disk only
between a crash and the next modifying `cai` invocation. `cai --check`
reports it (`W520`) without repairing, because it never writes.

A PID lock file (`.cai/lock`) enforces the single-writer assumption. On POSIX
a lock whose owner is dead is taken over with a warning.

## Testing

`python -m unittest discover -s tests -t .` runs everything in temporary
workspaces. Crash recovery is tested by hard-killing a real `cai` process at
named points of the commit (`CAI_FAULT_POINT`, a test-only hook in `txn.py`).
