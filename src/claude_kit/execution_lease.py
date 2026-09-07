"""Crash-released lease for one managed workflow coordinator.

The provider-neutral lock file is persistent at the project root, outside every
rollback surface; ownership is the kernel lock, never file age or a PID written
to disk. Its exact marker is opened relative to a verified root descriptor.
This avoids PID-reuse, lifecycle rollback, path-redirection, and unlink/ABA
races introduced by putting the inode inside ``.ckit``.
"""

from __future__ import annotations

import os
import stat
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from claude_kit.models import StateLayout
from claude_kit.secure_fs import ProjectFS, UnsafePathError
from claude_kit.state import detect_state_layout

_LEASE_FILENAME = ".claude-kit-managed-execution.lock"
_LEASE_MAGIC = b"claude-kit-managed-execution-lock:v1\n"


class ManagedExecutionLeaseHeld(RuntimeError):
    """Raised when another live coordinator owns the managed run lease."""


def _after_lease_open(_root_fd: int, _lease_fd: int) -> None:
    """Test seam before the opened lock is rebound to its root entry."""


def _before_lease_create(_root_fd: int) -> None:
    """Test seam immediately before atomic root-entry creation/open."""


def _after_lease_create(_root_fd: int, _lease_fd: int) -> None:
    """Test seam after first publication but before initialization."""


def _open_lease_file(project_root: Path, *, blocking: bool) -> tuple[int, int]:
    """Open, initialize, and lock the stable root-level lease inode."""

    # Preserve the caller's lexical path. Resolving first would silently follow
    # a symlinked project root before ProjectFS has a chance to reject it.
    fs = ProjectFS(Path(project_root).expanduser())
    fs._require_secure_mutation("managed execution lease acquisition")
    root_fd = fs._open_verified_root_fd()
    common_flags = os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        common_flags |= os.O_CLOEXEC
    lease_fd = -1
    try:
        _before_lease_create(root_fd)
        try:
            lease_fd = os.open(
                _LEASE_FILENAME,
                os.O_RDWR | os.O_CREAT | os.O_EXCL | common_flags,
                0o600,
                dir_fd=root_fd,
            )
            os.fchmod(lease_fd, 0o600)
            _after_lease_create(root_fd, lease_fd)
        except FileExistsError:
            existing_flags = os.O_RDWR | common_flags
            if hasattr(os, "O_NONBLOCK"):
                existing_flags |= os.O_NONBLOCK
            lease_fd = os.open(
                _LEASE_FILENAME,
                existing_flags,
                dir_fd=root_fd,
            )

        opened = os.fstat(lease_fd)
        named = os.stat(_LEASE_FILENAME, dir_fd=root_fd, follow_symlinks=False)
        if not stat.S_ISREG(opened.st_mode):
            raise UnsafePathError("managed execution lock is not a regular file")
        if opened.st_nlink != 1:
            raise UnsafePathError(
                "managed execution lock must have exactly one filesystem link"
            )
        if (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino):
            raise UnsafePathError(
                "managed execution lock changed while it was being opened"
            )
        if stat.S_IMODE(opened.st_mode) != 0o600:
            raise UnsafePathError(
                "managed execution lock has unexpected permissions; refusing to alter it"
            )

        # Own the kernel lease before examining or repairing initialization.
        # If the creating process dies at any byte boundary, its crash releases
        # flock and the next owner can finish only an exact prefix of our
        # reserved marker. Arbitrary contents remain untouched and rejected.
        if os.name == "posix":
            import fcntl

            operation = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
            try:
                fcntl.flock(lease_fd, operation)
            except BlockingIOError as exc:
                raise ManagedExecutionLeaseHeld(
                    "another managed workflow coordinator is still running"
                ) from exc

        _after_lease_open(root_fd, lease_fd)
        opened = os.fstat(lease_fd)
        named = os.stat(_LEASE_FILENAME, dir_fd=root_fd, follow_symlinks=False)
        if (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino):
            raise UnsafePathError(
                "managed execution lock changed while it was being opened"
            )
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or stat.S_IMODE(opened.st_mode) != 0o600
        ):
            raise UnsafePathError(
                "managed execution lock metadata changed during acquisition"
            )
        os.lseek(lease_fd, 0, os.SEEK_SET)
        content = os.read(lease_fd, len(_LEASE_MAGIC) + 1)
        if content != _LEASE_MAGIC and _LEASE_MAGIC.startswith(content):
            os.ftruncate(lease_fd, 0)
            os.lseek(lease_fd, 0, os.SEEK_SET)
            view = memoryview(_LEASE_MAGIC)
            while view:
                written = os.write(lease_fd, view)
                if written <= 0:  # pragma: no cover - defensive OS contract
                    raise OSError(
                        "managed execution lock marker write made no progress"
                    )
                view = view[written:]
            os.fsync(lease_fd)
            content = _LEASE_MAGIC
        if content != _LEASE_MAGIC:
            raise UnsafePathError(
                "managed execution lock has unknown content; refusing to commandeer it"
            )
        final = os.fstat(lease_fd)
        current = os.stat(
            _LEASE_FILENAME,
            dir_fd=root_fd,
            follow_symlinks=False,
        )
        if (
            (final.st_dev, final.st_ino) != (current.st_dev, current.st_ino)
            or not stat.S_ISREG(final.st_mode)
            or final.st_nlink != 1
            or stat.S_IMODE(final.st_mode) != 0o600
            or final.st_size != len(_LEASE_MAGIC)
        ):
            raise UnsafePathError(
                "managed execution lock changed during marker verification"
            )
        return root_fd, lease_fd
    except BaseException:
        # Never unlink a published lock on initialization failure: another
        # opener may already hold a descriptor to this inode. Exact marker
        # prefixes are recoverable by a later kernel-lock owner.
        if lease_fd >= 0:
            os.close(lease_fd)
        os.close(root_fd)
        raise


def _open_compatibility_lease(fs: ProjectFS, relative: str, *, blocking: bool) -> int:
    """Lock one pre-root-anchor inode used by released claude-kit versions."""
    parent_rel = str(Path(relative).parent).replace(os.sep, "/")
    fs.mkdir(parent_rel)
    parent_fd = fs._open_parent_fd(relative)
    fd = -1
    flags = os.O_RDWR | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK
    try:
        try:
            fd = os.open(
                Path(relative).name,
                flags | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=parent_fd,
            )
            os.fchmod(fd, 0o600)
        except FileExistsError:
            fd = os.open(Path(relative).name, flags, dir_fd=parent_fd)
        opened = os.fstat(fd)
        named = os.stat(
            Path(relative).name,
            dir_fd=parent_fd,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or stat.S_IMODE(opened.st_mode) != 0o600
            or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
        ):
            raise UnsafePathError(
                "legacy managed execution lock is not one safe mode-0600 regular file"
            )
        if os.name == "posix":
            import fcntl

            operation = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
            try:
                fcntl.flock(fd, operation)
            except BlockingIOError as exc:
                raise ManagedExecutionLeaseHeld(
                    "a managed workflow coordinator from this or an earlier "
                    "claude-kit release is still running"
                ) from exc
        final = os.fstat(fd)
        current = os.stat(
            Path(relative).name,
            dir_fd=parent_fd,
            follow_symlinks=False,
        )
        if (
            (final.st_dev, final.st_ino) != (current.st_dev, current.st_ino)
            or not stat.S_ISREG(final.st_mode)
            or final.st_nlink != 1
            or stat.S_IMODE(final.st_mode) != 0o600
        ):
            raise UnsafePathError(
                "legacy managed execution lock changed during acquisition"
            )
        result = fd
        fd = -1
        return result
    finally:
        if fd >= 0:
            os.close(fd)
        os.close(parent_fd)


def _compatibility_lease_paths(fs: ProjectFS) -> tuple[str, ...]:
    """Return the active old path plus any stranded alternate old inode."""

    active = detect_state_layout(fs)
    neutral = f"{StateLayout.neutral().state}/managed-execution.lock"
    legacy = f"{StateLayout.legacy_claude().state}/managed-execution.lock"
    selected = {f"{active.state}/managed-execution.lock"}
    if active == StateLayout.legacy_claude():
        # A successful state migration makes the neutral manifest authoritative
        # while this lease is still held. Older releases then discover the
        # neutral path, so bind that prospective path before migration begins.
        selected.add(neutral)
    # Rollback can temporarily hide the marker that selects a layout while its
    # earlier-release lock inode remains. Lock either pre-existing alternate as
    # well, in deterministic order, to keep old and current coordinators apart.
    for relative in (neutral, legacy):
        if fs.is_file(relative):
            selected.add(relative)
    return tuple(path for path in (neutral, legacy) if path in selected)


@contextmanager
def managed_execution_lease(
    project_root: Path, *, blocking: bool = False
) -> Iterator[None]:
    """Hold the project managed-execution lease until the context exits."""

    root_fd, fd = _open_lease_file(project_root, blocking=blocking)
    compatibility_fds: list[int] = []
    windows_locked = False
    try:
        compatibility_fs = ProjectFS(Path(project_root).expanduser())
        for relative in _compatibility_lease_paths(compatibility_fs):
            compatibility_fds.append(
                _open_compatibility_lease(
                    compatibility_fs,
                    relative,
                    blocking=blocking,
                )
            )
        if os.name == "posix":
            current = os.stat(
                _LEASE_FILENAME,
                dir_fd=root_fd,
                follow_symlinks=False,
            )
            opened = os.fstat(fd)
            if (opened.st_dev, opened.st_ino) != (
                current.st_dev,
                current.st_ino,
            ):
                raise UnsafePathError(
                    "managed execution lock changed during acquisition"
                )
            yield
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
            windows_locked = True
            yield
    finally:
        # Release in strict reverse acquisition order. In particular, keep the
        # root anchor held until every old-path compatibility lock is released,
        # so a new client cannot observe a false old-version contention window.
        for compatibility_fd in reversed(compatibility_fds):
            if os.name == "posix":
                import fcntl

                fcntl.flock(compatibility_fd, fcntl.LOCK_UN)
            os.close(compatibility_fd)
        try:
            if os.name == "posix":
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_UN)
            elif windows_locked:  # pragma: no cover - exercised by Windows CI
                import msvcrt

                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)  # type: ignore[attr-defined]
        finally:
            os.close(fd)
            os.close(root_fd)


__all__ = ["ManagedExecutionLeaseHeld", "managed_execution_lease"]
