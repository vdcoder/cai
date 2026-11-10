"""Lifecycle resolution and deterministic rendering.

``build_plan`` walks every directive in processing order (files sorted by
relative path, then top to bottom) and records, for each named block, the
history of its states. Rendering a file "as of" operation index *p* replays
only the directives before *p*; later directives are treated as absent. The
final consolidated source is the rendering as of the end of the sequence.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .adapters import ADAPTERS
from .diagnostics import ERROR, Diagnostic
from .parser import Directive, ParsedFile, dedent

ACTIVE, EVOLVED, DROPPED = "active", "evolved", "dropped"
END = 1 << 60  # "after every operation"


@dataclass
class State:
    op: int  # index of the operation that produced this state
    status: str
    body: list[str]
    changed: bool  # body differs from the block's declaration


@dataclass
class Block:
    kind: str  # defer | test | run
    name: str
    decl: Directive
    history: list[State] = field(default_factory=list)
    checkpoint: int = 0  # runs only: source-state version observed
    closed_by: Directive | None = None

    def state_at(self, p: int) -> State | None:
        found = None
        for st in self.history:
            if st.op >= p:
                break
            found = st
        return found

    @property
    def final(self) -> State:
        return self.history[-1]


@dataclass
class Plan:
    files: list[ParsedFile]
    ops: list[Directive] = field(default_factory=list)
    blocks: list[Block] = field(default_factory=list)
    by_decl: dict[int, Block] = field(default_factory=dict)  # id(Directive) -> Block
    diagnostics: list[Diagnostic] = field(default_factory=list)
    versions: int = 0  # number of source-state changes in the sequence
    counts: dict[str, int] = field(default_factory=dict)
    waits: list[Directive] = field(default_factory=list)

    def active(self, kind: str) -> list[Block]:
        return [b for b in self.blocks if b.kind == kind and b.final.status == ACTIVE]

    def op_index(self, block: Block) -> int:
        return block.history[0].op


def build_plan(files: list[ParsedFile]) -> Plan:
    plan = Plan(files=files)
    active: dict[str, Block] = {}
    closed: dict[str, Block] = {}
    counts = {c: 0 for c in ("defer", "wait", "evolve", "drop", "run", "test")}
    version = 0
    last_change: Directive | None = None

    def error(code: str, msg: str, d: Directive) -> None:
        plan.diagnostics.append(Diagnostic(ERROR, code, msg, d.file, d.line, d.command, d.name))

    def missing(d: Directive) -> None:
        old = closed.get(d.name or "")
        if old is not None and old.closed_by is not None:
            how = {"evolve": "evolved", "drop": "dropped"}[old.closed_by.command]
            error("E302", f"target '{d.name}' was already consumed: the #{old.kind} declared at "
                  f"{old.decl.where} was {how} at {old.closed_by.where}", d)
            return
        later = next((o for o in plan_all if o.name == d.name and o.command in ("defer", "test", "run")), None)
        hint = (f"; a #{later.command} {d.name} exists at {later.where}, which is later in processing "
                "order (files are processed in path order, then top to bottom)") if later else ""
        error("E301", f"no active block named '{d.name}'{hint}", d)

    plan_all = [d for pf in files for d in pf.directives]
    for idx, d in enumerate(plan_all):
        plan.ops.append(d)
        counts[d.command] += 1
        if d.command == "wait":
            plan.waits.append(d)
        elif d.command in ("defer", "test", "run"):
            other = active.get(d.name or "")
            if other is not None:
                error("E303", f"duplicate active identifier '{d.name}': a #{other.kind} with this name "
                      f"is still active (declared at {other.decl.where})", d)
                continue
            block = Block(d.command, d.name or "", d, [State(idx, ACTIVE, dedent(d.body), False)])
            if block.kind == "run":
                block.checkpoint = version
            else:
                version += 1
                last_change = d
            active[block.name] = block
            plan.blocks.append(block)
            plan.by_decl[id(d)] = block
        elif d.command == "evolve":
            block = active.get(d.name or "")
            if block is None:
                missing(d)
            elif block.kind == "run":
                if block.checkpoint != version:
                    assert last_change is not None
                    error("E304", f"cannot evolve pending #run '{d.name}' (declared at {block.decl.where}): "
                          f"the source state changed after its checkpoint (#{last_change.command} "
                          f"{last_change.name} at {last_change.where}); declare a new #run instead", d)
                else:
                    block.history.append(State(idx, ACTIVE, dedent(d.body), True))
            elif block.kind == "defer":
                block.history.append(State(idx, EVOLVED, dedent(d.body), True))
                block.closed_by = d
                closed[block.name] = active.pop(block.name)
                version += 1
                last_change = d
            else:  # test: body replaced, identity retained
                block.history.append(State(idx, ACTIVE, dedent(d.body), True))
                version += 1
                last_change = d
        elif d.command == "drop":
            block = active.get(d.name or "")
            if block is None:
                missing(d)
                continue
            block.history.append(State(idx, DROPPED, [], True))
            block.closed_by = d
            closed[block.name] = active.pop(block.name)
            if block.kind != "run":
                version += 1
                last_change = d
    plan.versions = version
    plan.counts = counts
    return plan


def _materialize(body: list[str], indent: str, newline: str, final_newline: bool) -> str:
    if not body:
        return ""
    text = newline.join(indent + line if line else "" for line in body)
    return text + (newline if final_newline else "")


def _render_directive(plan: Plan, pf: ParsedFile, d: Directive, p: int, keep_runs: bool) -> str:
    block = plan.by_decl.get(id(d))
    if block is None:  # wait / evolve / drop are always transient
        return ""
    st = block.state_at(p)
    if st is None or st.status == DROPPED:
        return ""
    ends_nl = d.raw.endswith("\n")
    if st.status == EVOLVED:
        return _materialize(st.body, d.indent, pf.newline, ends_nl)
    if block.kind == "run" and not keep_runs:
        return ""
    if not st.changed:
        return d.raw
    text = ADAPTERS[pf.style].render(d.command, d.name, st.body, d.indent, pf.newline)
    return text if ends_nl else text[: -len(pf.newline)]


def _ends_blank(text: str) -> bool:
    """True if ``text`` is empty or its last line is a blank line."""
    if not text:
        return True
    if not text.endswith("\n"):
        return False
    body = text[:-1]
    return body[body.rfind("\n") + 1:].strip(" \t\r") == ""


def render_file(plan: Plan, pf: ParsedFile, p: int = END, keep_runs: bool = False) -> str:
    """Render ``pf`` as of operation index ``p``.

    Ordinary text is copied verbatim with one exception: when a removed
    directive sat between two blank lines (or between a blank line and either
    end of the file) one of the blank lines is removed with it.
    """
    out = ""
    swallow = False
    for seg in pf.segments:
        if isinstance(seg, str):
            if swallow:
                first, sep, rest = seg.partition("\n")
                if first.strip(" \t\r") == "":
                    seg = rest if sep else ""
            swallow = False
            out += seg
            continue
        rendered = _render_directive(plan, pf, seg, p, keep_runs)
        if rendered:
            out += rendered
            swallow = False
        elif _ends_blank(out):
            swallow = True
    if swallow and out:
        body = out[:-1]
        out = body[: body.rfind("\n") + 1]
    return out
