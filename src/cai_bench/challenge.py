"""Challenge manifest format (``challenge.json``)."""
from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from . import SCHEMA_VERSION

CATEGORIES = (
    "small_function", "multi_function_refactor", "bug_repair", "missing_target_recovery",
    "iterative_optimization", "unit_test_creation", "cpp_implementation", "python_implementation",
    "multi_file_change", "repeated_failed_experiments", "other",
)


class ManifestError(Exception):
    pass


@dataclass
class Challenge:
    id: str
    title: str
    category: str
    description: str
    root: Path
    fixture: Path
    grader_dir: Path
    grader_command: list[str]
    success_criteria: str
    cai_overlay: Path | None = None
    setup: list[list[str]] = field(default_factory=list)
    permitted_tools: list[str] = field(default_factory=list)
    trial_timeout: float = 900.0
    grade_timeout: float = 120.0
    requires: list[str] = field(default_factory=list)
    replay: Path | None = None

    def missing_requirements(self) -> list[str]:
        return [tool for tool in self.requires if shutil.which(tool) is None]


def _argv(value: object, where: str) -> list[str]:
    if not (isinstance(value, list) and value and all(isinstance(a, str) for a in value)):
        raise ManifestError(f"{where} must be a non-empty array of strings")
    return list(value)


def load_challenge(directory: Path) -> Challenge:
    path = directory / "challenge.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ManifestError(f"{path}: {exc}") from None

    def need(key: str, kind: type) -> object:
        if not isinstance(data.get(key), kind):
            raise ManifestError(f"{path}: '{key}' is required and must be {kind.__name__}")
        return data[key]

    if data.get("schema_version") != SCHEMA_VERSION:
        raise ManifestError(f"{path}: schema_version must be {SCHEMA_VERSION}")
    cid = need("id", str)
    if cid != directory.name:
        raise ManifestError(f"{path}: id '{cid}' must equal the directory name")
    category = need("category", str)
    if category not in CATEGORIES:
        raise ManifestError(f"{path}: unknown category '{category}'")
    grader = need("grader", dict)
    limits = data.get("limits", {})
    ch = Challenge(
        id=cid, title=need("title", str), category=category, description=need("description", str),
        root=directory, fixture=directory / data.get("fixture", "fixture"),
        grader_dir=directory / grader.get("dir", "grader"),
        grader_command=_argv(grader.get("command"), f"{path}: grader.command"),
        success_criteria=need("success_criteria", str),
        cai_overlay=(directory / data["cai_overlay"]).resolve() if data.get("cai_overlay") else None,
        setup=[_argv(s, f"{path}: setup[]") for s in data.get("setup", [])],
        permitted_tools=list(data.get("permitted_tools", ["file_edit", "search", "shell"])),
        trial_timeout=float(limits.get("trial_timeout_seconds", 900)),
        grade_timeout=float(limits.get("grade_timeout_seconds", 120)),
        requires=list(data.get("requires", [])),
        replay=directory / data["replay"] if data.get("replay") else None,
    )
    for label, p in (("fixture", ch.fixture), ("grader.dir", ch.grader_dir), ("cai_overlay", ch.cai_overlay)):
        if p is not None and not p.is_dir():
            raise ManifestError(f"{path}: {label} directory not found: {p}")
    if ch.fixture.resolve() in ch.grader_dir.resolve().parents or ch.grader_dir.resolve() in (
            ch.fixture.resolve(), *ch.fixture.resolve().parents):
        raise ManifestError(f"{path}: the grader must not live inside the fixture (it has to stay hidden)")
    return ch


def load_suite(directory: Path, only: list[str] | None = None) -> list[Challenge]:
    found = sorted(p.parent for p in directory.glob("*/challenge.json"))
    suite = [load_challenge(p) for p in found if not only or p.name in only]
    missing = set(only or []) - {c.id for c in suite}
    if missing:
        raise ManifestError(f"unknown challenge(s): {', '.join(sorted(missing))}")
    return suite


def tree_digest(directory: Path) -> str:
    """Stable hash of every file path and content below ``directory``."""
    h = hashlib.sha256()
    for path in sorted(p for p in directory.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
        h.update(path.relative_to(directory).as_posix().encode() + b"\0")
        h.update(hashlib.sha256(path.read_bytes()).digest())
    return h.hexdigest()
