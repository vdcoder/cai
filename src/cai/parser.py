"""Directive parser: splits a source text into ordinary text and directives.

Ordinary text is kept verbatim, so ``"".join(raw segments)`` always equals the
input. Parsing never raises; problems are returned as diagnostics.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .adapters import NAMED, Adapter
from .diagnostics import ERROR, Diagnostic

_LINE_RE = re.compile(r"[^\n]*\n|[^\n]+")
_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.\-]*")


@dataclass
class Directive:
    command: str
    name: str | None
    body: list[str]  # logical lines: comment prefix removed, no line endings
    file: str
    line: int  # 1-based line of the opener
    end_line: int
    indent: str
    style: str
    raw: str  # exact original text, including line endings

    @property
    def where(self) -> str:
        return f"{self.file}:{self.line}"


@dataclass
class ParsedFile:
    rel: str
    style: str
    newline: str
    segments: list[str | Directive] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)

    @property
    def directives(self) -> list[Directive]:
        return [s for s in self.segments if isinstance(s, Directive)]


def _eol_stripped(line: str) -> str:
    if line.endswith("\r\n"):
        return line[:-2]
    if line.endswith("\n"):
        return line[:-1]
    return line


def dedent(lines: list[str]) -> list[str]:
    """Remove the whitespace prefix common to all non-blank lines."""
    prefix: str | None = None
    for text in lines:
        if not text.strip():
            continue
        lead = text[: len(text) - len(text.lstrip(" \t"))]
        if prefix is None:
            prefix = lead
        else:
            n = 0
            while n < min(len(prefix), len(lead)) and prefix[n] == lead[n]:
                n += 1
            prefix = prefix[:n]
    cut = len(prefix or "")
    return [text[cut:] if text.strip() else "" for text in lines]


def parse_text(text: str, rel: str, adapter: Adapter) -> ParsedFile:
    lines = _LINE_RE.findall(text)
    newline = "\r\n" if lines and lines[0].endswith("\r\n") else "\n"
    pf = ParsedFile(rel=rel, style=adapter.style, newline=newline)
    buf: list[str] = []

    def error(code: str, msg: str, line: int, command: str | None = None, name: str | None = None) -> None:
        pf.diagnostics.append(Diagnostic(ERROR, code, msg, rel, line, command, name))

    i, n = 0, len(lines)
    while i < n:
        content = _eol_stripped(lines[i])
        m = adapter.open_re.match(content)
        if not m:
            if adapter.end_re.match(content):
                error("E203", "stray #end without an open directive", i + 1, "end")
            buf.append(lines[i])
            i += 1
            continue

        command, rest, indent = m["command"], m["rest"], m["indent"]
        inline = adapter.inline_end_re.match(rest)
        body: list[str] = []
        end = i
        problem: tuple[str, str, int] | None = None
        if inline:
            header = inline["text"]
        elif adapter.closer and adapter.closer in rest:
            header = ""
            problem = ("E201", f"comment is closed before #end (expected '#end{adapter.tail}')", i + 1)
        else:
            header = rest
            j = i + 1
            while j < n:
                inner = _eol_stripped(lines[j])
                if adapter.end_re.match(inner):
                    break
                if adapter.open_re.match(inner):
                    problem = ("E202", f"nested or overlapping directive: #{command} opened at line {i + 1} "
                               "is not terminated before this directive starts", j + 1)
                    break
                decoded = adapter.decode_body_line(inner)
                if decoded is None:
                    problem = ("E201", f"unterminated #{command}: line {j + 1} is not a comment line "
                               "and no '# #end' was found before it", i + 1)
                    break
                body.append(decoded)
                j += 1
            else:
                problem = ("E201", f"unterminated #{command}: reached end of file without #end", i + 1)
            end = j

        name: str | None = None
        if problem is None:
            header = header.strip()
            if command in NAMED:
                nm = _NAME_RE.match(header)
                extra = header[nm.end():] if nm else header
                if not nm or (extra and not extra[0].isspace()):
                    problem = ("E204", f"#{command} requires a name matching [A-Za-z_][A-Za-z0-9_.-]* "
                               f"(got {header!r})", i + 1)
                else:
                    name = nm.group(0)
                    extra = extra.strip()
                    if extra and inline:
                        body = [extra]
                    elif extra:
                        problem = ("E204", f"unexpected text after the name of #{command} {name}: {extra!r} "
                                   "(the body starts on the next line)", i + 1)
            elif header:
                body.insert(0, header)

        if problem is not None:
            error(problem[0], problem[1], problem[2], command, name)
            # A well-terminated block with a bad header is skipped as a whole
            # so that its #end is not reported a second time.
            skip = end + 1 if problem[0] == "E204" else i + 1
            buf.extend(lines[i:skip])
            i = skip
            continue

        if buf:
            pf.segments.append("".join(buf))
            buf = []
        pf.segments.append(Directive(
            command=command, name=name, body=body, file=rel, line=i + 1, end_line=end + 1,
            indent=indent, style=adapter.style, raw="".join(lines[i:end + 1]),
        ))
        i = end + 1
    if buf:
        pf.segments.append("".join(buf))
    return pf
