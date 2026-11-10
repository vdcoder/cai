"""The three experimental conditions and their agent instructions."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class Condition:
    key: str  # A | B | C
    label: str
    cai_enabled: bool
    instructions: str


COMMON = """\
Work only inside the current workspace directory. When you are finished, the
workspace must contain the final source code; nothing else is submitted.
A separate, hidden grader evaluates the result after you stop.
"""

A = Condition("A", "standard editing", False, """\
Use your normal workflow: file editing, search/replace, shell execution and
debugging. Do not use CAI directives and do not invoke the `cai` tool.
""")

B = Condition("B", "standard editing + scratchpad comments", False, """\
Use your normal workflow: file editing, search/replace, shell execution and
debugging. You may additionally write temporary comments in source files to
plan or reconsider your approach. Remove such scratch comments before you
finish. Do not use CAI directives and do not invoke the `cai` tool.
""")

C = Condition("C", "CAI-assisted editing", True, """\
Your normal workflow (file editing, search/replace, shell) remains available.
In addition this workspace is configured for CAI (see cai.json). You may append
CAI directives to the configured source files, each written as a comment in
the file's comment style and terminated by `#end`:

  #defer <name>   named placeholder for code you will write later
  #wait           unnamed scratchpad; removed on consolidation
  #evolve <name>  replace a #defer placeholder with real code (it is written
                  at the placeholder's position), or replace the body of a
                  #test or of a not-yet-executed #run
  #drop <name>    remove an active #defer, #test or pending #run
  #run <name>     temporary experiment; sees the source as of its position
  #test <name>    persistent regression test kept in the source file

Then invoke `cai --run` (consolidate and execute experiments, results are
reported together), `cai --test` (consolidate and execute tests), or
`cai --build` (consolidate only). `cai --check` validates without writing.
You are not required to use CAI for every change. Before you finish, run
`cai --build --discard-runs` so that no transient directives remain.
""")

CONDITIONS = {c.key: c for c in (A, B, C)}


def build_prompt(description: str, condition: Condition) -> str:
    return f"# Task\n\n{description.strip()}\n\n# Rules\n\n{COMMON}\n# Workflow\n\n{condition.instructions}"


def prompt_digest(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()
