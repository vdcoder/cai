"""Comment-style adapters.

An adapter knows how a directive is spelled inside one comment style. All
adapters are line oriented: a directive starts on a line whose first
non-blank text is the opener, and ends on a line holding only the terminator.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

COMMANDS = ("defer", "wait", "evolve", "drop", "run", "test")
NAMED = ("defer", "evolve", "drop", "run", "test")
_CMD = r"#(?P<command>" + "|".join(COMMANDS) + r")\b(?P<rest>.*)$"
_INDENT = r"^(?P<indent>[ \t]*)"


@dataclass(frozen=True)
class Adapter:
    style: str
    open_re: re.Pattern[str]
    end_re: re.Pattern[str]
    inline_end_re: re.Pattern[str]  # applied to the header remainder
    closer: str | None  # token that would close the host comment early
    head: str  # text placed before "#command" when rendering
    tail: str  # text placed after "#end" when rendering
    line_prefix: str  # prefix of every rendered body line

    def decode_body_line(self, line: str) -> str | None:
        """Return the logical body text of a raw line, or None if the line
        cannot belong to a directive in this style."""
        if not self.line_prefix:
            return line
        stripped = line.lstrip(" \t")
        if not stripped:
            return ""
        if not stripped.startswith("#"):
            return None
        stripped = stripped[1:]
        return stripped[1:] if stripped.startswith(" ") else stripped

    def render(self, command: str, name: str | None, body: list[str], indent: str, newline: str) -> str:
        """Spell a directive in this style (used when a #test or pending #run
        was evolved and must be written back)."""
        header = f"{indent}{self.head}#{command}" + (f" {name}" if name else "")
        lines = [header]
        for text in body:
            if self.line_prefix:
                lines.append(f"{indent}{self.line_prefix} {text}".rstrip() if text else f"{indent}{self.line_prefix}")
            else:
                lines.append(f"{indent}{text}" if text else "")
        lines.append(f"{indent}{self.line_prefix + ' ' if self.line_prefix else ''}#end{self.tail}")
        return newline.join(lines) + newline


def _adapter(style: str, opener: str, end_tail: str, closer: str | None,
             head: str, tail: str, line_prefix: str = "") -> Adapter:
    return Adapter(
        style=style,
        open_re=re.compile(_INDENT + opener + _CMD),
        end_re=re.compile(r"^[ \t]*" + (r"#[ \t]*" if line_prefix else "") + r"#end[ \t]*" + end_tail + r"[ \t]*$"),
        inline_end_re=re.compile(r"^(?P<text>(?:.*?[ \t])?)#end[ \t]*" + end_tail + r"[ \t]*$"),
        closer=closer,
        head=head,
        tail=tail,
        line_prefix=line_prefix,
    )


ADAPTERS: dict[str, Adapter] = {
    a.style: a
    for a in (
        _adapter("c_block", r"/\*+[ \t]*", r"\*+/", "*/", "/* ", " */"),
        _adapter("html_comment", r"<!--+[ \t]*", r"--+>", "-->", "<!-- ", " -->"),
        _adapter("python_comment", r"#[ \t]*", "", None, "# ", "", line_prefix="#"),
        _adapter("bare", "", "", None, "", ""),
    )
}
