"""Structured diagnostics shared by every CAI stage."""
from __future__ import annotations

from dataclasses import asdict, dataclass

ERROR = "error"
WARNING = "warning"


@dataclass(frozen=True)
class Diagnostic:
    severity: str
    code: str
    message: str
    file: str | None = None
    line: int | None = None
    directive: str | None = None
    name: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    def format(self) -> str:
        where = self.file or "<workspace>"
        if self.line is not None:
            where += f":{self.line}"
        what = ""
        if self.directive:
            what = f" [#{self.directive}" + (f" {self.name}" if self.name else "") + "]"
        return f"{where}: {self.severity} {self.code}{what}: {self.message}"


def has_errors(diags: list[Diagnostic]) -> bool:
    return any(d.severity == ERROR for d in diags)
