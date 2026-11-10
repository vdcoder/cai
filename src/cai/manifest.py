"""Optional content-hash manifest for incremental scans.

A file may be skipped only when it was recorded as directive-free and its size
and mtime are unchanged. Files containing directives are always re-parsed, and
the manifest is rewritten only after a successful invocation, so an
interrupted run can never cause pending directives to be skipped. The default
(``scan.incremental`` false) is a full scan that ignores the manifest.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

RACY_NS = 2_000_000_000  # files modified this recently are never marked clean


def load(state: Path) -> dict[str, dict]:
    try:
        data = json.loads((state / "manifest.json").read_text(encoding="utf-8"))
        return data["files"] if data.get("version") == 1 else {}
    except (OSError, ValueError, KeyError, AttributeError):
        return {}


def is_clean(entry: dict | None, st: os.stat_result) -> bool:
    return bool(entry and entry.get("directive_free")
                and entry.get("size") == st.st_size and entry.get("mtime_ns") == st.st_mtime_ns)


def save(state: Path, previous: dict[str, dict], scanned: dict[str, tuple[Path, str, bool]],
         discovered: set[str]) -> None:
    """``scanned`` maps rel -> (path, sha256 of final content, directive_free)."""
    files = {rel: e for rel, e in previous.items() if rel in discovered}
    now = time.time_ns()
    for rel, (path, digest, directive_free) in scanned.items():
        try:
            st = path.stat()
        except OSError:
            files.pop(rel, None)
            continue
        files[rel] = {"size": st.st_size, "mtime_ns": st.st_mtime_ns, "sha256": digest,
                      "directive_free": directive_free and now - st.st_mtime_ns > RACY_NS}
    state.mkdir(parents=True, exist_ok=True)
    tmp = state / "manifest.json.tmp"
    tmp.write_text(json.dumps({"version": 1, "files": files}, indent=1), encoding="utf-8")
    os.replace(tmp, state / "manifest.json")
