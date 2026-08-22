"""Crash-released lease for one managed workflow coordinator.

The lock file is persistent; ownership is the kernel lock, never file age or a
PID written to disk.  This avoids PID-reuse and unlink/ABA races.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from claude_kit.secure_fs import ProjectFS
from claude_kit.state import detect_state_layout


class ManagedExecutionLeaseHeld(RuntimeError):
    """Raised when another live coordinator owns the managed run lease."""


def _lease_path(project_root: Path) -> Path:
    root = Path(project_root).resolve(strict=True)
    layout = detect_state_layout(root)
    relative = f"{layout.state}/managed-execution.lock"
    path = ProjectFS(root).path(relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def managed_execution_lease(
    project_root: Path, *, blocking: bool = False
) -> Iterator[None]:
    """Hold the project managed-execution lease until the context exits."""

    path = _lease_path(project_root)
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    try:
        os.fchmod(fd, 0o600)
        if os.name == "posix":
            import fcntl

            operation = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
            try:
                fcntl.flock(fd, operation)
            except BlockingIOError as exc:
                raise ManagedExecutionLeaseHeld(
                    "another managed workflow coordinator is still running"
                ) from exc
            try:
                yield
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
        else:  # pragma: no cover - exercised by Windows CI
            import msvcrt

            if os.fstat(fd).st_size == 0:
                os.write(fd, b"\0")
            os.lseek(fd, 0, os.SEEK_SET)
            mode = msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK  # type: ignore[attr-defined]
            try:
                msvcrt.locking(fd, mode, 1)  # type: ignore[attr-defined]
            except OSError as exc:
                raise ManagedExecutionLeaseHeld(
                    "another managed workflow coordinator is still running"
                ) from exc
            try:
                yield
            finally:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)  # type: ignore[attr-defined]
    finally:
        os.close(fd)


__all__ = ["ManagedExecutionLeaseHeld", "managed_execution_lease"]
