# Limitations and unsupported cases

## Parsing

- **Line-oriented recognition.** A directive is recognised only when its
  opener is the first non-blank text on a line and its terminator is alone on
  a line. `int x; /* #wait ... #end */` on one code line is ordinary text.
- **Look-alikes at the start of a line inside multi-line strings.** CAI does
  not tokenise host languages. A line inside a multi-line string literal (or
  inside an unrelated block comment) that itself begins with `/* #run …`,
  `# #defer …` and so on is treated as a directive. Directive-like text in the
  middle of a line is safe.
- **No escape mechanism** for the case above.
- **Python docstrings / triple-quoted strings** are never directive
  containers.
- **One style per file.** Mixed-language files (for example `<script>` inside
  HTML) get the single configured style.
- **`bare` style has no comment protection.** A line `#end` or `#run x` in a
  bare-style file is a directive. Configure it only for files you control.
- **UTF-8 only.** Other encodings are reported (`E502`) and never modified. A
  UTF-8 BOM is preserved.
- **Line endings.** LF and CRLF are preserved; materialised code uses the
  style of the file's first line. Bare-CR (classic Mac) files are unsupported.
- **Names are ASCII identifiers** (`[A-Za-z_][A-Za-z0-9_.-]*`).
- **Cascading diagnostics.** A nested or unterminated directive can produce a
  follow-up `E203` for its orphaned `#end`. Fix the first error first.

## Semantics

- **A placeholder is a comment.** A `#defer` that is the *only* body of a
  Python block (`def f():` followed by just the placeholder) is a syntax error
  until it is evolved, and experiments checkpointed before the evolution will
  fail to import the file. Defer the whole definition, or keep a statement
  next to the placeholder.
- **Ordinary text is timeless.** Checkpoints order directive effects only.
  Code typed normally anywhere in a file is visible to every experiment.
- **Cross-file order is path order**, which may differ from the order in which
  an agent wrote the files. An `#evolve` must sort after its target.
- **No re-evolution of a materialised `#defer`.** Once evolved, the code is
  ordinary source; change it with a normal edit. (See ARCHITECTURE.md,
  "Resolved ambiguities".)
- **"Already consumed" is only known within one invocation.** After a
  consolidation is committed, an `#evolve` of an old name reports `E301`
  (no such block), not `E302`.
- **A run left pending by `--build` loses its original checkpoint.**
- **Blank-line policy** removes one neighbouring blank line together with a
  removed directive (the only non-verbatim change to ordinary text).
- **Indentation is applied mechanically.** The placeholder's indentation is
  prefixed to every non-blank body line; CAI does not check that the result is
  valid in the host language.
- **Consolidated code may not compile.** CAI transforms text; it does not
  build your project.

## Execution

- **Not a sandbox.** Bodies run with your privileges. Timeouts and output
  caps limit accidents, not attacks.
- **Snapshots copy the workspace** once per experiment (minus the default and
  configured exclusions). Large trees or large build outputs make `--run`
  slow; use `snapshot.exclude`. There is no copy-on-write or snapshot reuse.
- **Sequential execution.** No parallel experiments in v1.
- **Tests share one snapshot** and are trusted not to modify sources.
- **Snapshot paths are temporary**, so build caches keyed on absolute paths do
  not carry over between experiments.
- **Timeout kill** terminates the process group on POSIX and uses
  `taskkill /T` on Windows; processes that detach themselves can survive.

## Safety and platform

- **Single writer.** Concurrent CAI invocations are rejected by a lock;
  concurrent *edits by other tools* are detected only for files CAI is about
  to modify, and only at commit time.
- **Stale locks on Windows** are not detected automatically (delete
  `.cai/lock` after a crash); on POSIX they are.
- **Recovery is roll-back.** A crash between the file replacements and the
  commit point undoes the consolidation; experiments of that invocation will
  run again.
- **Durability depends on the filesystem** honouring `fsync` and atomic
  `rename`. Network filesystems may not.
- **Windows and macOS** are supported by design (no POSIX-only code paths
  without a fallback) but the test suite has so far been run on Linux only.
- **Symlinked files** resolving outside the workspace are ignored.

## Benchmarks

- **No agent has been benchmarked.** All committed evidence is synthetic
  harness validation.
- **No bundled vendor integration.** Real trials need an external command or
  the manual prepare/grade workflow (BENCHMARKS.md).
- **Ten small challenges** are enough to exercise the harness, not to
  characterise agent performance.
