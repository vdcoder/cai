"""Discovery and loading of the configured source files."""
from __future__ import annotations

import fnmatch
import hashlib
from dataclasses import dataclass
from pathlib import Path

from .adapters import ADAPTERS
from .config import Config
from .diagnostics import ERROR, Diagnostic
from .parser import ParsedFile, parse_text

BOM = "﻿"


@dataclass
class SourceFile:
    rel: str  # POSIX path relative to the workspace root
    path: Path
    style: str
    data: bytes
    sha256: str
    bom: bool
    parsed: ParsedFile

    def encode(self, text: str) -> bytes:
        return ((BOM if self.bom else "") + text).encode("utf-8")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def discover(cfg: Config) -> list[tuple[str, Path, str]]:
    """Return (rel, path, style) for every configured file, sorted by ``rel``.

    The first include rule that matches a file decides its adapter. The sort
    key is the POSIX relative path compared by Unicode code point; this is the
    cross-file processing order.
    """
    root = cfg.root
    state = Path(cfg.state_dir).parts
    found: dict[str, tuple[Path, str]] = {}
    for rule in cfg.include:
        for path in root.glob(rule.pattern):
            if not path.is_file():
                continue
            try:
                relp = path.resolve().relative_to(root)
            except ValueError:
                continue  # symlink escaping the workspace
            if relp.parts[: len(state)] == state or ".git" in relp.parts:
                continue
            rel = relp.as_posix()
            if any(fnmatch.fnmatch(rel, pat) for pat in cfg.exclude):
                continue
            found.setdefault(rel, (root / relp, rule.style))
    return [(rel, *found[rel]) for rel in sorted(found)]


def load(rel: str, path: Path, style: str) -> tuple[SourceFile | None, list[Diagnostic]]:
    try:
        data = path.read_bytes()
    except OSError as exc:
        return None, [Diagnostic(ERROR, "E501", f"cannot read file: {exc}", rel)]
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        return None, [Diagnostic(ERROR, "E502", f"file is not valid UTF-8: {exc}", rel)]
    bom = text.startswith(BOM)
    parsed = parse_text(text[1:] if bom else text, rel, ADAPTERS[style])
    return SourceFile(rel, path, style, data, sha256(data), bom, parsed), list(parsed.diagnostics)
