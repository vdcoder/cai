"""Workspace lock, journaled multi-file commit, and crash recovery.

Protocol (roll-back journal):

1. Every file to be modified is re-read and compared with the bytes that were
   parsed; a mismatch aborts before anything is touched.
2. Original and new contents are staged under ``<state>/txn/`` and flushed.
3. ``journal.json`` is written atomically. From here on a crash is recoverable.
4. Each target is replaced with ``os.replace``.
5. ``journal.json`` is deleted. This single unlink is the commit point.

If a journal exists when an invocation starts, the previous one did not reach
step 5 and every file it replaced is restored from its staged original. A
file that matches neither the original nor the new content was edited by
someone else; it is left alone and reported.
"""
from __future__ import annotations

import errno
import hashlib
import json
import os
import shutil
from pathlib import Path

FAULT_ENV = "CAI_FAULT_POINT"  # test hook: hard-exit at a named point


class TxnError(Exception):
    """The commit or recovery could not be completed safely."""


class LockError(TxnError):
    pass


def _fault(point: str) -> None:
    if os.environ.get(FAULT_ENV) == point:
        os._exit(97)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_synced(path: Path, data: bytes) -> None:
    with open(path, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())


def _sync_dir(path: Path) -> None:
    if os.name != "posix":
        return
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _replace(staged: Path, target: Path) -> None:
    try:
        shutil.copymode(target, staged)
    except OSError:
        pass
    try:
        os.replace(staged, target)
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
        sibling = target.with_name(target.name + ".cai-tmp")
        shutil.copy2(staged, sibling)
        os.replace(sibling, target)
    _sync_dir(target.parent)


class Lock:
    """Single-writer guard: ``<state>/lock`` holds the owner's PID."""

    def __init__(self, state: Path) -> None:
        self.path = state / "lock"
        self.held = False
        self.stole_stale = False

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for attempt in (0, 1):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                pid = self._owner()
                if attempt == 0 and pid is not None and os.name == "posix" and not _alive(pid):
                    self.path.unlink(missing_ok=True)
                    self.stole_stale = True
                    continue
                raise LockError(
                    f"another cai invocation appears to be using this workspace (pid {pid}); "
                    f"if that process is gone, delete {self.path}") from None
            with os.fdopen(fd, "w") as fh:
                fh.write(str(os.getpid()))
            self.held = True
            return

    def _owner(self) -> int | None:
        try:
            return int(self.path.read_text().strip())
        except (OSError, ValueError):
            return None

    def release(self) -> None:
        if self.held:
            self.path.unlink(missing_ok=True)
            self.held = False


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def recover(root: Path, state: Path) -> list[str]:
    """Roll back an interrupted commit. Returns the restored relative paths."""
    txn = state / "txn"
    journal = txn / "journal.json"
    if not txn.exists():
        return []
    if not journal.exists():  # crashed while staging or while cleaning up: sources are consistent
        shutil.rmtree(txn, ignore_errors=True)
        return []
    try:
        entries = json.loads(journal.read_text(encoding="utf-8"))["files"]
    except (OSError, ValueError, KeyError) as exc:
        raise TxnError(f"unreadable transaction journal {journal}: {exc}; originals are in {txn / 'orig'}") from None
    restored, conflicts = [], []
    for entry in entries:
        target = root / entry["rel"]
        try:
            current = _sha(target.read_bytes())
        except FileNotFoundError:
            current = None
        if current == entry["orig_sha256"]:
            continue
        if current is not None and current != entry["new_sha256"]:
            conflicts.append(entry["rel"])
            continue
        backup = txn / "orig" / entry["id"]
        tmp = txn / ("restore-" + entry["id"])
        shutil.copyfile(backup, tmp)
        shutil.copymode(backup, tmp)
        _replace(tmp, target)
        restored.append(entry["rel"])
    if conflicts:
        raise TxnError(
            "an interrupted cai transaction cannot be rolled back automatically because these files were "
            f"changed afterwards: {', '.join(conflicts)}. Pre-transaction copies are in {txn / 'orig'} "
            f"(see {journal}); resolve manually, then delete {txn}")
    journal.unlink()
    shutil.rmtree(txn, ignore_errors=True)
    return restored


def commit(root: Path, state: Path, changes: list[tuple[str, bytes, bytes]]) -> int:
    """Apply ``(rel, original_bytes, new_bytes)`` changes all-or-nothing.

    Returns the number of bytes written to source files.
    """
    if not changes:
        return 0
    for rel, orig, _ in changes:
        try:
            on_disk = (root / rel).read_bytes()
        except OSError as exc:
            raise TxnError(f"{rel}: cannot re-read before commit: {exc}") from None
        if on_disk != orig:
            raise TxnError(f"{rel}: file was modified by another writer during this invocation; "
                           "nothing was changed, re-run cai")
    txn = state / "txn"
    if txn.exists():
        raise TxnError(f"stale transaction directory {txn}")
    (txn / "orig").mkdir(parents=True)
    (txn / "new").mkdir()
    entries = []
    try:
        for i, (rel, orig, new) in enumerate(changes):
            ident = f"{i:05d}"
            _write_synced(txn / "orig" / ident, orig)
            shutil.copymode(root / rel, txn / "orig" / ident)
            _write_synced(txn / "new" / ident, new)
            entries.append({"id": ident, "rel": rel, "orig_sha256": _sha(orig), "new_sha256": _sha(new)})
        _write_synced(txn / "journal.tmp", json.dumps({"version": 1, "files": entries}, indent=1).encode())
        os.replace(txn / "journal.tmp", txn / "journal.json")
        _sync_dir(txn)
    except OSError as exc:
        shutil.rmtree(txn, ignore_errors=True)
        raise TxnError(f"cannot stage transaction: {exc}") from None
    try:
        for n, entry in enumerate(entries):
            _fault(f"before_replace:{n}")
            _replace(txn / "new" / entry["id"], root / entry["rel"])
        _fault("before_commit")
        (txn / "journal.json").unlink()
    except BaseException as exc:
        try:
            recover(root, state)
        except Exception:  # leave the journal for the next invocation
            pass
        if isinstance(exc, OSError):
            raise TxnError(f"commit failed and was rolled back: {exc}") from None
        raise
    _fault("after_commit")
    shutil.rmtree(txn, ignore_errors=True)
    return sum(len(new) for _, _, new in changes)
