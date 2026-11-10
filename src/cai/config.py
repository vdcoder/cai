"""Loading and validation of ``cai.json``."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .adapters import ADAPTERS

CONFIG_NAME = "cai.json"


class ConfigError(Exception):
    """The configuration file is missing or invalid."""


@dataclass(frozen=True)
class IncludeRule:
    pattern: str
    style: str


@dataclass
class Config:
    root: Path
    name: str = "project"
    include: list[IncludeRule] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    run_command: list[str] | None = None
    test_command: list[str] | None = None
    timeout_seconds: float = 30.0
    max_output_bytes: int = 65536
    snapshot_exclude: list[str] = field(default_factory=list)
    state_dir: str = ".cai"
    stats_enabled: bool = True
    stats_path: str | None = None  # default: <state_dir>/stats.jsonl
    incremental: bool = False

    @property
    def state_path(self) -> Path:
        return self.root / self.state_dir

    @property
    def stats_file(self) -> Path:
        return self.root / (self.stats_path or f"{self.state_dir}/stats.jsonl")


def _expect(cond: bool, msg: str) -> None:
    if not cond:
        raise ConfigError(msg)


def _command(section: dict, key: str) -> list[str] | None:
    value = section.get(key)
    if value is None:
        return None
    _expect(
        isinstance(value, list) and value and all(isinstance(a, str) for a in value),
        f"runner.{key} must be a non-empty array of strings (an argv list, never a shell string)",
    )
    return list(value)


def _str_list(value: object, where: str) -> list[str]:
    _expect(isinstance(value, list) and all(isinstance(a, str) for a in value),
            f"{where} must be an array of strings")
    return list(value)  # type: ignore[arg-type]


def load_config(path: Path) -> Config:
    """Load ``cai.json``. ``path`` may be the file or the directory containing it."""
    path = Path(path)
    if path.is_dir():
        path = path / CONFIG_NAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"configuration file not found: {path}") from None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from None
    _expect(isinstance(data, dict), "cai.json must contain a JSON object")
    _expect(data.get("version") == 1, 'cai.json: "version" must be 1')

    project = data.get("project", {})
    _expect(isinstance(project, dict), '"project" must be an object')
    includes: list[IncludeRule] = []
    raw_inc = project.get("include", [])
    _expect(isinstance(raw_inc, list) and raw_inc, '"project.include" must be a non-empty array')
    for i, entry in enumerate(raw_inc):
        _expect(isinstance(entry, dict), f"project.include[{i}] must be an object")
        pattern, style = entry.get("pattern"), entry.get("style")
        _expect(isinstance(pattern, str) and pattern, f"project.include[{i}].pattern must be a string")
        _expect(not Path(pattern).is_absolute() and ".." not in Path(pattern).parts,
                f"project.include[{i}].pattern must stay inside the workspace")
        _expect(style in ADAPTERS,
                f"project.include[{i}].style must be one of {sorted(ADAPTERS)} (got {style!r})")
        includes.append(IncludeRule(pattern, style))

    runner = data.get("runner", {})
    _expect(isinstance(runner, dict), '"runner" must be an object')
    timeout = runner.get("timeout_seconds", 30)
    _expect(isinstance(timeout, (int, float)) and not isinstance(timeout, bool) and timeout > 0,
            "runner.timeout_seconds must be a positive number")
    max_out = runner.get("max_output_bytes", 65536)
    _expect(isinstance(max_out, int) and not isinstance(max_out, bool) and max_out > 0,
            "runner.max_output_bytes must be a positive integer")

    snapshot = data.get("snapshot", {})
    stats = data.get("stats", {})
    scan = data.get("scan", {})
    for label, section in (("snapshot", snapshot), ("stats", stats), ("scan", scan)):
        _expect(isinstance(section, dict), f'"{label}" must be an object')
    state_dir = data.get("state_dir", ".cai")
    _expect(isinstance(state_dir, str) and state_dir and not Path(state_dir).is_absolute(),
            '"state_dir" must be a relative path')

    return Config(
        root=path.parent.resolve(),
        name=str(project.get("name", path.parent.name)),
        include=includes,
        exclude=_str_list(project.get("exclude", []), "project.exclude"),
        run_command=_command(runner, "run_command"),
        test_command=_command(runner, "test_command"),
        timeout_seconds=float(timeout),
        max_output_bytes=max_out,
        snapshot_exclude=_str_list(snapshot.get("exclude", []), "snapshot.exclude"),
        state_dir=state_dir,
        stats_enabled=bool(stats.get("enabled", True)),
        stats_path=stats.get("path"),
        incremental=bool(scan.get("incremental", False)),
    )
