"""Shared helpers: temporary workspaces and in-process CLI invocation."""
from __future__ import annotations

import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

RUNNER = '''\
import os, sys
body = sys.stdin.read()
sys.path.insert(0, os.path.join(os.getcwd(), "src"))
exec(compile(body, os.environ["CAI_NAME"], "exec"), {"__name__": "__cai__"})
'''

DEFAULT_INCLUDE = [
    {"pattern": "src/**/*.py", "style": "python_comment"},
    {"pattern": "src/**/*.c", "style": "c_block"},
    {"pattern": "docs/**/*.md", "style": "html_comment"},
    {"pattern": "notes/**/*.txt", "style": "bare"},
]


class WorkspaceCase(unittest.TestCase):
    """Creates an isolated temporary workspace per test."""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="cai-test-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.config()
        self.write("tools/runner.py", RUNNER)

    def config(self, **overrides) -> None:
        data = {
            "version": 1,
            "project": {"name": "t", "include": DEFAULT_INCLUDE},
            "runner": {
                "run_command": ["{python}", "tools/runner.py"],
                "test_command": ["{python}", "tools/runner.py"],
                "timeout_seconds": 20,
            },
        }
        for key, value in overrides.items():
            if isinstance(value, dict) and isinstance(data.get(key), dict):
                data[key].update(value)
            else:
                data[key] = value
        (self.root / "cai.json").write_text(json.dumps(data), encoding="utf-8")

    def write(self, rel: str, text: str | bytes) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))
        return path

    def read(self, rel: str) -> str:
        return (self.root / rel).read_bytes().decode("utf-8")

    def cai(self, *args: str) -> tuple[int, dict]:
        """Run the CLI in-process with --json; return (exit_code, report)."""
        from cai.cli import main

        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = main(["--root", str(self.root), "--json", *args])
        text = out.getvalue()
        return code, (json.loads(text) if text.strip() else {})

    def codes(self, report: dict) -> list[str]:
        return [d["code"] for d in report.get("diagnostics", [])]


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
