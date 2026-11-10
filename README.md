# CAI

**CAI makes it cheaper for an AI coding agent to change its mind while writing software.**

An agent writes source files front to back. When it realises, halfway down a
file, that an earlier decision was wrong, the usual remedy is another round of
search-and-replace tool calls. CAI offers a second option: keep writing.
The agent appends small *directives* inside ordinary comments — a placeholder,
a second thought, a replacement, an experiment, a test — and the `cai` tool
deterministically consolidates them into clean source code.

CAI is a companion for existing languages. It is not a programming language,
compiler, IDE, coding agent or inference engine, and it never rewrites code it
did not place itself.

> **Status: v0.1 prototype.** The engine and harness are covered by 109 automated tests. Whether
> CAI makes agents faster, cheaper or more accurate is **unmeasured**: the
> benchmark harness exists, but no controlled agent trials have been run yet.
> See [Benchmarks](#benchmarks).

## The six directives

Every directive starts with `#command` and ends with `#end`, inside the comment
style configured for the file.

```c
/* #defer process_data            named placeholder for code to be written later
Validate the buffer, then process the data.
#end */

/* #wait                          scratchpad; removed on consolidation
The current approach may allocate unnecessarily.
#end */

/* #evolve process_data           replaces the placeholder with real code,
void process_data(void* buffer) { at the placeholder's position
    if (!buffer) return;
}
#end */

/* #drop obsolete_experiment      removes an active named block
#end */

/* #run allocation_probe          temporary experiment; sees the source as of
print("allocation probe")         its own position; consumed when executed
#end */

/* #test empty_buffer             persistent regression test; stays in the file
assert process_data(None) is None
#end */
```

| style | file kinds | spelling |
|---|---|---|
| `c_block` | C, C++, JavaScript, CSS, … | `/* #cmd name` … `#end */` |
| `python_comment` | Python, shell, YAML, … | `# #cmd name`, `# body`, `# #end` |
| `html_comment` | HTML, Markdown | `<!-- #cmd name` … `#end -->` |
| `bare` | explicitly configured text files | `#cmd name` … `#end` |

## Install

Python 3.11 or newer; no third-party dependencies.

```bash
pip install -e .
```

```bash
python -m unittest discover -s tests -t .
```

## Five-minute demonstration

```bash
cp -r examples/demo /tmp/cai-demo && cd /tmp/cai-demo
```

```bash
cai --check
```

```bash
cai --run --test
```

`src/metrics.py` starts with two placeholders, a scratchpad note, an evolution,
a drop, three experiments and one test, all appended top to bottom. One
invocation consolidates the three files and reports:

```
[run] before: passed  exit=0  33.4ms  checkpoint=6  (src/metrics.py:23)
    median defined: False
[run] after: passed  exit=0  33.0ms  checkpoint=8  (src/metrics.py:47)
    median defined: True
    median([5, 1, 4, 2]) -> 3.0
[run] empty_input: failed  exit=1  32.9ms  checkpoint=8  (src/metrics.py:53)
    ValueError: median of an empty sequence
runs: 2/3 passed
[test] mean_and_median: passed  exit=0  32.7ms  (src/metrics.py:58)
```

`before` and `after` ran in the same batch yet observed different source
states, because each experiment runs against a snapshot of the source *as of
its position*. The deliberately failing `empty_input` shows the failure policy:
the experiment failed (exit status 1), the consolidation was still committed.
Afterwards the files are plain source; only the `#test` block remains.
[examples/demo/README.md](examples/demo/README.md) has the full walkthrough.

## Commands

| command | effect | writes source files? |
|---|---|---|
| `cai --check` | validate every directive | never (writes nothing at all) |
| `cai --build` | consolidate; pending `#run` blocks stay in place, unexecuted | yes |
| `cai --run` | consolidate and execute all pending `#run` blocks | yes |
| `cai --test [NAME…]` | consolidate and execute `#test` blocks | yes (only if directives were pending) |
| `cai --stats` | summarise `.cai/stats.jsonl` | no |

`--run` and `--test` can be combined. Add `--json` for machine-readable output.
Exit status: `0` ok · `1` consolidated, but an experiment or test did not pass ·
`2` invalid directives, nothing changed · `3` configuration or usage error ·
`4` lock, commit or recovery problem · `130` interrupted.

If any directive is invalid the whole invocation is rejected and no file is
touched. Multi-file changes are committed through a roll-back journal, so a
crash never leaves a mixture of old and new files behind.

## Documentation

- [docs/REFERENCE.md](docs/REFERENCE.md) — `cai.json`, directive semantics, ordering rules, CLI, failure policy, runner protocol, diagnostics, statistics
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — modules, pipeline, design decisions and open questions
- [docs/LIMITATIONS.md](docs/LIMITATIONS.md) — unsupported cases and known sharp edges
- [docs/BENCHMARKS.md](docs/BENCHMARKS.md) — the A/B/C agent benchmark harness and how to run real trials
- [PROGRESS.md](PROGRESS.md) — milestone log and next steps

## Benchmarks

`cai-bench` compares three conditions on ten local challenges: (A) standard
editing, (B) standard editing plus scratchpad comments, (C) CAI-assisted
editing. It isolates every trial, grades with hidden graders, records traces in
a provider-neutral format and reports correctness separately from efficiency.

```bash
cai-bench validate --out /tmp/cai-bench-validate
```

That command replays deterministic scripts through the harness. It proves the
harness works and **nothing else**: a scripted replay is not an agent, and its
reports are labelled `SYNTHETIC HARNESS VALIDATION`. No language-model trials
have been run, so this repository makes no claim that CAI improves agent
performance. [docs/BENCHMARKS.md](docs/BENCHMARKS.md) describes how to collect
real evidence.

## Safety

`#run` and `#test` bodies are executed as code by the runner you configure.
A subprocess with a timeout and an output cap is not a sandbox. Only run CAI on
content you would be willing to execute, or inside a separately secured
environment.

## License

MIT — see [LICENSE](LICENSE).
