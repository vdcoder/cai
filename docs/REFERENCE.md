# CAI reference

## 1. Configuration: `cai.json`

`cai` looks for `cai.json` in the directory given by `--root` (default: the
current directory) or at the path given by `--config`. That directory is the
*workspace root*.

```json
{
  "version": 1,
  "project": {
    "name": "cai_example",
    "include": [
      { "pattern": "src/**/*.cpp", "style": "c_block" },
      { "pattern": "src/**/*.py",  "style": "python_comment" },
      { "pattern": "docs/**/*.md", "style": "html_comment" },
      { "pattern": "notes/*.txt",  "style": "bare" }
    ],
    "exclude": ["src/vendor/*"]
  },
  "runner": {
    "run_command":  ["{python}", "tools/run_experiment.py"],
    "test_command": ["{python}", "tools/run_test.py"],
    "timeout_seconds": 30,
    "max_output_bytes": 65536
  },
  "snapshot": { "exclude": ["build/*", "*.o"] },
  "scan":     { "incremental": false },
  "stats":    { "enabled": true, "path": ".cai/stats.jsonl" },
  "state_dir": ".cai"
}
```

| key | meaning | default |
|---|---|---|
| `version` | must be `1` | required |
| `project.include[]` | glob `pattern` (relative, `**` allowed) and comment `style`. The first rule matching a file decides its style. Only matched files are ever read or modified. | required |
| `project.exclude[]` | `fnmatch` patterns on the relative POSIX path | `[]` |
| `runner.run_command` / `test_command` | argv list, never a shell string | none |
| `runner.timeout_seconds` | per experiment / test | `30` |
| `runner.max_output_bytes` | cap per output stream | `65536` |
| `snapshot.exclude[]` | extra paths left out of snapshots | `[]` |
| `scan.incremental` | use the content-hash manifest (section 8) | `false` |
| `stats.enabled`, `stats.path` | statistics log | `true`, `<state_dir>/stats.jsonl` |
| `state_dir` | lock, journal, manifest, statistics, last report | `.cai` |

Files under `state_dir` and `.git` are never treated as sources. Add the state
directory to your VCS ignore list.

## 2. Directive syntax

A directive occupies whole lines. The opener must be the first non-blank text
on its line; the terminator must be alone on its line.

| style | opener | body lines | terminator |
|---|---|---|---|
| `c_block` | `/* #cmd name` | verbatim | `#end */` |
| `html_comment` | `<!-- #cmd name` | verbatim | `#end -->` |
| `python_comment` | `# #cmd name` | `# text` (one `#` and at most one space are removed; blank lines allowed) | `# #end` |
| `bare` | `#cmd name` | verbatim | `#end` |

- Names match `[A-Za-z_][A-Za-z0-9_.-]*`. `#wait` takes no name.
- One-line form: `/* #drop old #end */`, `# #wait reconsider this #end`.
- Body indentation is relative: the whitespace prefix common to all non-blank
  body lines is removed. When a `#defer` is materialised, every body line gets
  the indentation of the placeholder's opener line and the line-ending style
  of the file that holds the placeholder.
- In `c_block` bodies, `*/` may appear (for example an `#evolve` body that
  contains comments). The directive ends only at a `#end */` line.
- Python triple-quoted strings are never treated as comments.

## 3. Directive semantics

| directive | effect | lifetime |
|---|---|---|
| `#defer name` | Named placeholder. Stays in the file, as a comment, until evolved or dropped. | until `#evolve` / `#drop` |
| `#wait` | Scratchpad. Removed at the next consolidation. Not printed unless `--show-waits`. | one invocation |
| `#evolve name` | Target `#defer`: the body replaces the placeholder as ordinary code *at the placeholder's position*; the name is consumed. Target `#test`: the body is replaced, name and position are kept, the test stays evolvable. Target pending `#run`: the body is replaced before execution (see 4.3). | one invocation |
| `#drop name` | Removes an active `#defer`, `#test` or pending `#run`. | one invocation |
| `#run name` | Experiment executed by `runner.run_command` against the source state at its position. Consumed (removed) by `cai --run`. | until executed or dropped |
| `#test name` | Regression test. Stays in its source file as a comment; executed by `cai --test`. | until dropped |

Names live in one workspace-wide namespace shared by `#defer`, `#test` and
`#run`. Two *active* blocks may not share a name (`E303`). After a block's
lifecycle ends (evolved defer, dropped block, executed run) its name may be
reused. `#evolve`/`#drop` of a name with no active block is an error: `E301`
if it never existed in this invocation, `E302` if it was already consumed
(the message says where).

CAI never edits code it did not place: changing an existing function remains
an ordinary edit by the agent.

## 4. Ordering and checkpoints

### 4.1 Processing order

Directives are processed in one deterministic sequence:

1. files in ascending order of their workspace-relative POSIX path, compared
   by Unicode code point (`docs/a.md` < `src/a.py` < `src/b.py`);
2. within a file, top to bottom.

This is a rule, not a reconstruction of history: CAI does not know when text
was written and does not consult timestamps. A directive may only target a
block that is *earlier* in this order (or already present from an earlier
invocation). An `#evolve` placed in a file that sorts before its target is
reported as `E301` with a hint naming the later declaration.

### 4.2 Checkpoints

Each `#run` observes the source *as if consolidation had happened using only
the directives before it* in processing order. Later directives are treated as
absent; ordinary (non-directive) text is always present, wherever it is.

Every experiment gets its own private snapshot directory in the system
temporary directory: a copy of the workspace (without `state_dir`, `.git`,
`__pycache__`, `node_modules`, virtualenvs, tool caches and
`snapshot.exclude`) in which the configured files have their checkpoint
content. Experiments cannot affect each other or the workspace. Experiments
execute sequentially, in processing order, after the whole plan has been
validated; batching never changes what an experiment observes.

The reported `checkpoint` number is the count of source-state changes
(`#defer`/`#test` declarations, `#evolve`, `#drop` of a defer or test) that
precede the run. Runs with the same number saw the same source state.

### 4.3 Evolving a pending run

A `#run` body can be replaced by a later `#evolve` only while the source state
is unchanged since the run's checkpoint, that is, no state-changing directive
lies between them. Otherwise the operation is rejected (`E304`): the run was
scheduled against an older state, and silently re-pointing it would rewrite
history. Declare a new `#run` instead.

### 4.4 Tests

`cai --test` executes active tests against one snapshot of the *final*
consolidated state of the invocation, in processing order of their
declarations. `cai --test NAME…` selects tests; an unknown name is `E305`.
Tests share that snapshot and should not modify sources.

### 4.5 `--build` and pending runs

`cai --build` (and `cai --test` without `--run`) consolidates everything else
and leaves `#run` blocks in the source, unexecuted and reported under
`pending.runs`. A run left pending is executed by a later `cai --run` against
the source state *at that later time*; its original checkpoint is not
preserved. `--discard-runs` removes pending runs instead.

## 5. Command line

```
cai (--check | --build | --run | --test [NAME ...] | --stats)
    [--json] [--root DIR | --config FILE] [--discard-runs] [--show-waits]
    [--keep-snapshots] [--full-scan] [--no-stats]
```

| mode | consolidates | executes | may modify sources |
|---|---|---|---|
| `--check` | no (reports `would_modify`) | nothing | never; also writes no state, statistics or lock |
| `--build` | yes | nothing | yes |
| `--run` | yes | pending runs | yes |
| `--test` | yes | selected tests | yes |
| `--run --test` | yes | runs, then tests | yes |
| `--stats` | no | nothing | never |

Source files are modified only by `--build`, `--run` and `--test`, only when
every directive in the workspace is valid, only files matched by
`project.include`, and only files whose consolidated content differs from
what is on disk. Untouched files keep their bytes and modification time.

Exit status:

| code | meaning |
|---|---|
| 0 | success |
| 1 | consolidation committed; at least one experiment or test did not pass |
| 2 | invalid directives or unknown test name; nothing was executed or changed |
| 3 | configuration or usage error (including a missing runner command) |
| 4 | workspace locked, commit aborted, or recovery needs manual attention |
| 130 | interrupted (Ctrl-C); sources are in their pre-invocation state |

The JSON report (`--json`, also stored in `<state_dir>/last_report.json`)
contains `ok`, `exit_code`, `mode`, `diagnostics[]`, `directives{}`,
`files_modified[]`, `would_modify[]`, `pending{defers,tests,runs}`, `runs[]`,
`tests[]`, `checkpoints`, `timing_ms{}` and `stats{}`.

## 6. Pipeline and failure policy

1. discover configured files → 2. parse and validate → 3. build the operation
sequence → 4. resolve lifecycles → 5. fix checkpoints → 6. compute the
consolidated state → 7. execute experiments and tests on snapshots →
8. diagnostics and telemetry → 9. commit.

Experiments run *before* the commit, on snapshots, so their results are in
hand before any source file changes.

| situation | behaviour |
|---|---|
| Parser failure, missing target, duplicate name, any `E2xx`/`E3xx` | Exit 2. No file modified, nothing executed. Requested runs are reported with status `skipped`. All diagnostics of the invocation are reported together. |
| Experiment or test exits non-zero | Status `failed`. Consolidation is committed, the run is consumed, exit 1. |
| Code at a checkpoint does not compile / import | Same as above: the runner fails, the report carries its output. The consolidated source is written as-is; repair it with ordinary edits or further directives. |
| Timeout | The process group is killed; status `timeout`; treated like a failure. |
| Runner cannot be started | Status `launch_error`; treated like a failure. |
| Runner command not configured but needed | Exit 3 before anything runs or changes. |
| Ctrl-C / SIGINT | Running experiment is killed, lock released, exit 130. Sources unchanged unless the commit had begun, in which case it is rolled back. |
| Crash or kill during commit | Journal remains; the next modifying invocation rolls every file back (`W522`), then proceeds normally. |
| A source file changes on disk during the invocation | Commit aborted before any write (`E511`), exit 4. Re-run. |
| Repeated invocation | Consolidation is idempotent: a second run finds nothing to do. Consumed runs do not execute again; tests can be run any number of times. |

Run / test result:

```json
{"name": "allocation_probe", "kind": "run", "status": "passed", "exit_code": 0,
 "duration_ms": 18.4, "stdout": "...", "stderr": "...", "checkpoint": 3,
 "file": "src/a.py", "line": 12, "stdout_truncated": false, "stderr_truncated": false}
```

`status` is `passed` (exit 0), `failed` (non-zero exit), `timeout`,
`launch_error` or `skipped`. `passed` means the process exited successfully,
not that the experiment proved its hypothesis.

## 7. Runner protocol

For every experiment or test, CAI starts the configured argv list **without a
shell**:

| channel | content |
|---|---|
| working directory | the snapshot directory (a full copy of the workspace at the checkpoint, including your runner scripts) |
| standard input | the directive body, UTF-8, dedented, with a trailing newline |
| `CAI_KIND` | `run` or `test` |
| `CAI_NAME` | block name |
| `CAI_SOURCE_FILE`, `CAI_SOURCE_LINE` | where the block is declared |
| `CAI_STYLE` | comment style of that file |
| `CAI_CHECKPOINT` | checkpoint number (empty for tests) |
| `CAI_SNAPSHOT_DIR` | absolute snapshot path |
| `CAI_WORKSPACE` | absolute path of the real workspace (treat as read-only) |
| `CAI_BODY_FILE` | file containing the body |
| `CAI_META_FILE` | JSON file with all of the above |
| `CAI_TIMEOUT_SECONDS` | configured timeout |

Inside argv elements these tokens are substituted: `{python}` (the interpreter
running CAI), `{name}`, `{kind}`, `{body_file}`, `{meta_file}`, `{snapshot}`,
`{workspace}`. Directive text is never placed on a command line.

The runner decides what a body means: Python to `exec`, a C++ translation
unit to compile and run (see `benchmarks/overlays/cpp/tools/cai_cpp_runner.py`),
a shell-free command description, and so on. Exit status 0 means "passed".
stdout and stderr are captured up to `max_output_bytes` each.

## 8. Change detection

By default every invocation reads and parses every configured file. With
`scan.incremental: true`, CAI keeps `<state_dir>/manifest.json` (size,
mtime, SHA-256, directive-free flag per file) and skips a file only if it was
recorded as directive-free **and** its size and mtime are unchanged. Files
that contain directives are always re-parsed; files modified within two
seconds of the manifest write are never marked clean; the manifest is written
only after a successful invocation. `--full-scan` ignores it. There is no
`.cai_heartbeat` file: the measurements below did not justify one.

Measured with `python benchmarks/scan_bench.py` (Linux x86-64, 4 cores,
Python 3.13, warm file cache, already-consolidated tree, median of 7):

| tree | full scan | incremental |
|---|---|---|
| 2,000 files × 200 lines | 156 ms | 73 ms |
| 2,000 files × 2,000 lines | 948 ms | 75 ms |

## 9. Diagnostics

Every diagnostic has `severity`, `code`, `message`, `file`, `line`,
`directive` and `name`, printed as
`src/a.c:2: error E301 [#evolve ghost]: no active block named 'ghost'`.

| code | meaning |
|---|---|
| E100 | `cai.json` missing or invalid |
| E101 | runner command needed but not configured |
| E201 | unterminated directive, or comment closed before `#end` |
| E202 | nested or overlapping directive |
| E203 | stray `#end` |
| E204 | missing or invalid name, or text after the name |
| E301 | no active block with that name |
| E302 | target already consumed (evolved or dropped earlier) |
| E303 | duplicate active identifier |
| E304 | `#evolve` of a pending run after its checkpoint |
| E305 | `--test NAME`: no such active test |
| E501 / E502 | file unreadable / not valid UTF-8 |
| E510 | workspace locked by another invocation |
| E511 | commit aborted (external modification or I/O error); rolled back |
| E512 | interrupted transaction cannot be rolled back automatically |
| W520 | `--check` noticed a pending interrupted transaction |
| W521 | stale lock of a dead process removed |
| W522 | interrupted transaction rolled back |
| W530 | report or statistics could not be stored |

## 10. Statistics

Every modifying invocation appends one JSON object to the statistics file:
`timestamp`, `mode`, `exit_code`, `files_scanned`, `files_skipped`,
`directives{defer,wait,evolve,drop,run,test}`, `evolutions`, `drops`,
`experiments`, `experiment_failures`, `persistent_tests`, `tests_executed`,
`test_failures`, `transformation_errors`, `parse_ms`, `transform_ms`,
`runner_ms`, `total_ms`, `bytes_read`, `bytes_written`, `files_modified`,
`checkpoints`, `recovery_operations`. `cai --stats [--json]` totals them.
These are operational counters. CAI records no token counts and derives no
"savings" figures.
