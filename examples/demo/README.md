# CAI demo project

`src/metrics.py`, `src/buffer.cpp` and `docs/notes.md` are in their
*un-consolidated* state: they contain every kind of directive. Because CAI
rewrites files in place, work on a copy so the demo stays repeatable:

```bash
cp -r examples/demo /tmp/cai-demo && cd /tmp/cai-demo
cai --check                # validate only; writes nothing
cai --run --test           # consolidate, run 3 experiments at 3 checkpoints, run the test
cat src/metrics.py         # clean source; only the #test block remains
cai --test                 # tests stay runnable; nothing is modified
cai --stats
```

Expected experiment results (one batch, two different source states):

| run | checkpoint | status | output |
|---|---|---|---|
| `before` | 6 | passed | `median defined: False` |
| `after` | 8 | passed | `median defined: True`, `median([5, 1, 4, 2]) -> 3.0` |
| `empty_input` | 8 | failed (exit 1) | `ValueError: median of an empty sequence` |

`empty_input` fails on purpose: the experiment's process exits non-zero, CAI
reports it and exits with status 1, and the consolidation is still committed.
A failed experiment is not a failed transformation.

A checkpoint number is the count of source-state changes (`#defer`/`#test`
declarations, `#evolve`, `#drop`) that precede the run in processing order:
`docs/notes.md`, then `src/buffer.cpp`, then `src/metrics.py`. `before` and
`after` are separated by one `#evolve` and one `#drop`.
