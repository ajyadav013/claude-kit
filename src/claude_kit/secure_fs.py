"""Project-root-bound filesystem mutations and recoverable install transactions.

Every path accepted by :class:`ProjectFS` is a project-relative POSIX path.  The
implementation rejects platform-specific absolute paths and refuses to traverse
symbolic links, Windows reparse points, or junctions.  Mutating methods repeat the
check immediately before changing the filesystem and atomic file writes replace a
temporary file in the destination directory.

``ProjectTransaction`` provides the stronger, multi-file guarantee needed by
install, merge, and upgrade.  It snapshots only claude-kit's mutation surface,
writes a schema-versioned recovery journal, rolls ordinary exceptions back, and
leaves the recovery data in place when the process is interrupted by a
``BaseException`` such as ``KeyboardInterrupt``.  A later invocation can then call
``recover_interrupted_transaction`` before doing any new work.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import sys
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Callable, Literal

TRANSACTION_SCHEMA = 2
"""Schema of the rollback-capable install/merge/upgrade journal."""

JOURNAL_PATH = ".claude/config/upgrade-in-progress.json"
_TRANSACTION_PREFIX = ".claude-kit-txn-"
_TRANSACTION_MARKER = "transaction.json"
_REPARSE_POINT = 0x400
_BACKUP_PREFIXES = (".claude-kit.bak-", ".claude.bak-")

_PROTECTED_PATHS = (
    ".claude",
    "CLAUDE.md",
    "CLAUDE.md.claude-kit",
    "AGENTS.md",
    "AGENTS.md.claude-kit",
    "README.claude-sdlc.md",
    "README.claude-sdlc.md.claude-kit",
    ".mcp.json",
    ".mcp.json.claude-kit",
    ".mcp.lock.json",
    ".gitignore",
)


class UnsafePathError(OSError):
    """A requested project mutation could escape through an unsafe path."""


def normalize_relative_path(raw: str | os.PathLike[str]) -> str:
    """Return a canonical project-relative POSIX path or raise.

    Validation is deliberately cross-platform even on POSIX.  A value such as
    ``C:\\outside`` must not become a harmless-looking filename on the development
    machine and an absolute path when the same configuration is used on Windows.
    Backslashes and colons are therefore refused in all components.
    """

    value = os.fspath(raw)
    if not isinstance(value, str):
        raise UnsafePathError("unsafe project path: expected text")
    if not value or value == "." or "\x00" in value:
        raise UnsafePathError(
            f"unsafe project path {value!r}: use a non-empty relative path"
        )
    windows = PureWindowsPath(value)
    if windows.drive or windows.root or windows.is_absolute():
        raise UnsafePathError(
            f"unsafe project path {value!r}: absolute, drive, UNC, and device paths are refused"
        )
    if "\\" in value:
        raise UnsafePathError(
            f"unsafe project path {value!r}: backslashes are refused; use '/' separators"
        )
    posix = PurePosixPath(value)
    if posix.is_absolute() or value.startswith("/"):
        raise UnsafePathError(
            f"unsafe project path {value!r}: absolute paths are refused"
        )
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise UnsafePathError(
            f"unsafe project path {value!r}: empty, '.' and '..' components are refused"
        )
    if any(":" in part for part in parts):
        raise UnsafePathError(
            f"unsafe project path {value!r}: ':' is refused in project path components"
        )
    return posix.as_posix()


def _is_link_or_reparse(path: Path, info: os.stat_result | None = None) -> bool:
    """Return whether ``path`` is a symlink, junction, or Windows reparse point."""

    try:
        current = info if info is not None else path.lstat()
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(current.st_mode):
        return True
    if int(getattr(current, "st_file_attributes", 0)) & _REPARSE_POINT:
        return True
    is_junction = getattr(path, "is_junction", None)
    if is_junction is not None:
        try:
            return bool(is_junction())
        except OSError:
            return True
    return False


def _unsafe(path: Path, reason: str) -> UnsafePathError:
    mac_hint = ""
    if (
        sys.platform == "darwin"
        and len(path.parts) > 1
        and path.parts[1]
        in {
            "tmp",
            "var",
        }
    ):
        mac_hint = (
            "; macOS aliases /tmp and /var through symlinks, so use the corresponding "
            "link-free /private/tmp or /private/var path"
        )
    return UnsafePathError(
        f"refusing unsafe project path {path}: {reason}{mac_hint}; remove the link/reparse point "
        "or choose a regular path inside the project and retry"
    )


def _assert_source_tree_safe(source: Path) -> None:
    """Fail closed when an external copy source contains a link or special file."""

    try:
        info = source.lstat()
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"copy source does not exist: {source}") from exc
    if _is_link_or_reparse(source, info):
        raise _unsafe(source, "copy source is a symlink, junction, or reparse point")
    if source.is_file():
        if not stat.S_ISREG(info.st_mode):
            raise _unsafe(source, "copy source is not a regular file")
        return
    if not source.is_dir():
        raise _unsafe(source, "copy source is not a regular directory")
    for current, dirs, files in os.walk(source, followlinks=False):
        base = Path(current)
        for name in [*dirs, *files]:
            child = base / name
            child_info = child.lstat()
            if _is_link_or_reparse(child, child_info):
                raise _unsafe(
                    child, "copy source contains a symlink, junction, or reparse point"
                )
            if not (
                stat.S_ISDIR(child_info.st_mode) or stat.S_ISREG(child_info.st_mode)
            ):
                raise _unsafe(child, "copy source contains a special filesystem entry")


class ProjectFS:
    """Filesystem capability restricted to one untrusted project root.

    POSIX mutation is anchored with ``dir_fd`` and ``O_NOFOLLOW``. Platforms
    without the complete primitive set retain safe read-only inspection but fail
    closed for mutation; native Windows callers are directed to WSL/POSIX.
    """

    def __init__(self, root: str | os.PathLike[str]) -> None:
        entered = Path(root).expanduser()
        self.root = Path(os.path.abspath(os.fspath(entered)))
        if self.root.parent == self.root:
            raise UnsafePathError(
                "refusing to use a filesystem root as the project root"
            )
        self._root_identity: tuple[int, int] | None = None
        self._lease_local = threading.local()
        self._assert_root()

    def _require_secure_mutation(self, operation: str) -> None:
        if not (self._supports_descriptor_walk() and self._supports_dir_fd_replace()):
            raise UnsafePathError(
                f"refusing {operation} in {self.root}: this platform lacks the "
                "descriptor-anchored filesystem primitives required for secure project "
                "mutation; use WSL or run claude-kit on a supported POSIX filesystem"
            )

    def mutation_lease(self, *, exclusive: bool = False) -> ProjectMutationLease:
        """Return a process-crash-safe project mutation lease.

        Lifecycle transactions take an exclusive lease. Short-lived runtime writers
        (pipeline/tickets/export) take the default shared lease before any subordinate
        lock, so an acknowledged write cannot be erased by transaction rollback.
        Acquisition is non-blocking and never reclaims locks by age.
        """

        return ProjectMutationLease(self, exclusive=exclusive)

    def _assert_root(self) -> None:
        if self._supports_descriptor_walk():
            identity = self._walk_root_descriptors(create=False)
            if identity is None:
                return
            if self._root_identity is None:
                self._root_identity = identity
            elif identity != self._root_identity:
                raise _unsafe(
                    self.root, "the project root was replaced during this operation"
                )
            return

        self._assert_root_ancestry()
        try:
            info = self.root.lstat()
        except FileNotFoundError:
            return
        if _is_link_or_reparse(self.root, info):
            raise _unsafe(
                self.root, "the project root is a symlink, junction, or reparse point"
            )
        if not stat.S_ISDIR(info.st_mode):
            raise _unsafe(self.root, "the project root is not a directory")
        identity = (info.st_dev, info.st_ino)
        if self._root_identity is None:
            self._root_identity = identity
        elif identity != self._root_identity:
            raise _unsafe(
                self.root, "the project root was replaced during this operation"
            )

    def _assert_root_ancestry(self) -> None:
        """Fail closed on lexical link/reparse ancestors (non-dir-fd platforms)."""

        current = self.root
        while True:
            try:
                info = current.lstat()
            except FileNotFoundError:
                info = None
            if info is not None and _is_link_or_reparse(current, info):
                raise _unsafe(
                    current,
                    "project-root ancestry contains a symlink, junction, or reparse point",
                )
            if (
                info is not None
                and current != self.root
                and not stat.S_ISDIR(info.st_mode)
            ):
                raise _unsafe(current, "project-root ancestry contains a non-directory")
            parent = current.parent
            if parent == current:
                return
            current = parent

    @staticmethod
    def _supports_descriptor_walk() -> bool:
        return (
            os.name == "posix"
            and os.open in os.supports_dir_fd
            and os.mkdir in os.supports_dir_fd
            and hasattr(os, "O_DIRECTORY")
            and hasattr(os, "O_NOFOLLOW")
        )

    def _before_root_create(self, anchor: Path, missing: tuple[str, ...]) -> None:
        """Test seam after opening the safe creation anchor."""

    def _open_root_descriptor(self, *, create: bool) -> int | None:
        """Open ``root`` by walking from ``/`` without following any component.

        Returning the final descriptor is important: reopening ``self.root`` as one
        lexical path would allow an attacker to swap an ancestor after validation.
        Callers own the returned descriptor.
        """

        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        current_fd = os.open(os.path.sep, flags)
        current_path = Path(os.path.sep)
        components = self.root.parts[1:]
        hook_called = False
        try:
            for index, part in enumerate(components):
                try:
                    next_fd = os.open(part, flags, dir_fd=current_fd)
                except FileNotFoundError:
                    if not create:
                        return None
                    if not hook_called:
                        self._before_root_create(
                            current_path, tuple(components[index:])
                        )
                        hook_called = True
                    try:
                        os.mkdir(part, dir_fd=current_fd)
                    except FileExistsError:
                        pass
                    try:
                        next_fd = os.open(part, flags, dir_fd=current_fd)
                    except OSError as exc:
                        raise _unsafe(
                            current_path / part,
                            f"new project-root component is not a link-free directory ({exc})",
                        ) from exc
                except OSError as exc:
                    raise _unsafe(
                        current_path / part,
                        f"project-root component is not a link-free directory ({exc})",
                    ) from exc
                os.close(current_fd)
                current_fd = next_fd
                current_path /= part
            result = current_fd
            current_fd = -1
            return result
        finally:
            if current_fd >= 0:
                os.close(current_fd)

    def _walk_root_descriptors(self, *, create: bool) -> tuple[int, int] | None:
        """Walk the absolute root from ``/`` and return its stable identity."""

        root_fd = self._open_root_descriptor(create=create)
        if root_fd is None:
            return None
        try:
            info = os.fstat(root_fd)
            return info.st_dev, info.st_ino
        finally:
            os.close(root_fd)

    def _open_verified_root_fd(self) -> int:
        """Return a link-free root capability matching the pinned identity."""

        root_fd = self._open_root_descriptor(create=False)
        if root_fd is None:
            raise _unsafe(self.root, "the project root disappeared")
        try:
            info = os.fstat(root_fd)
            identity = (info.st_dev, info.st_ino)
            if self._root_identity != identity:
                raise _unsafe(
                    self.root, "the project root changed before filesystem mutation"
                )
            return root_fd
        except BaseException:
            os.close(root_fd)
            raise

    def ensure_root(self) -> Path:
        """Create the project root if necessary, then verify its identity."""

        self._assert_root()
        if self._root_identity is None:
            self._require_secure_mutation("project-root creation")
            if self._supports_descriptor_walk():
                identity = self._walk_root_descriptors(create=True)
                if (
                    identity is None
                ):  # pragma: no cover - create=True returns an identity
                    raise _unsafe(self.root, "project root could not be created")
                self._root_identity = identity
            else:
                self._assert_root_ancestry()
                anchor = self.root.parent
                while not anchor.exists():
                    anchor = anchor.parent
                anchor_info = anchor.lstat()
                anchor_identity = (anchor_info.st_dev, anchor_info.st_ino)
                self._before_root_create(
                    anchor, tuple(self.root.relative_to(anchor).parts)
                )
                current_anchor = anchor.lstat()
                if (current_anchor.st_dev, current_anchor.st_ino) != anchor_identity:
                    raise _unsafe(anchor, "project-root creation anchor changed")
                self.root.mkdir(parents=True, exist_ok=False)
        self._assert_root()
        return self.root

    def relpath(self, path: str | os.PathLike[str]) -> str:
        """Convert a lexical path below ``root`` to the canonical relative form."""

        candidate = Path(path)
        if candidate.is_absolute():
            try:
                candidate = candidate.relative_to(self.root)
            except ValueError as exc:
                raise UnsafePathError(
                    f"refusing path outside project root {self.root}: {candidate}"
                ) from exc
        return normalize_relative_path(candidate.as_posix())

    def _parts(self, rel: str | os.PathLike[str]) -> tuple[str, ...]:
        return tuple(PurePosixPath(normalize_relative_path(rel)).parts)

    def _check(self, rel: str | os.PathLike[str], *, include_leaf: bool = True) -> Path:
        """Verify all existing path components without following them."""

        self._assert_root()
        parts = self._parts(rel)
        current = self.root
        checked = parts if include_leaf else parts[:-1]
        for index, part in enumerate(checked):
            current = current / part
            try:
                info = current.lstat()
            except FileNotFoundError:
                break
            except OSError as exc:
                raise _unsafe(
                    current, f"could not inspect path component ({exc})"
                ) from exc
            if _is_link_or_reparse(current, info):
                raise _unsafe(
                    current, "component is a symlink, junction, or reparse point"
                )
            if index < len(parts) - 1 and not stat.S_ISDIR(info.st_mode):
                raise _unsafe(
                    current, "non-directory component appears in path ancestry"
                )
        return self.root.joinpath(*parts)

    def path(self, rel: str | os.PathLike[str]) -> Path:
        """Return the checked absolute path for a relative project path."""

        return self._check(rel)

    def assert_safe(self, rel: str | os.PathLike[str]) -> Path:
        """Check ancestry and leaf for links/reparse points."""

        return self._check(rel)

    def assert_tree_safe(self, rel: str | os.PathLike[str]) -> Path:
        """Check a directory tree without following links."""

        path = self._check(rel)
        if not path.exists():
            return path
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode):
            return path
        for current, dirs, files in os.walk(path, followlinks=False):
            base = Path(current)
            for name in [*dirs, *files]:
                child = base / name
                child_info = child.lstat()
                if _is_link_or_reparse(child, child_info):
                    raise _unsafe(
                        child, "tree contains a symlink, junction, or reparse point"
                    )
                if not (
                    stat.S_ISDIR(child_info.st_mode) or stat.S_ISREG(child_info.st_mode)
                ):
                    raise _unsafe(child, "tree contains a special filesystem entry")
        return path

    def exists(self, rel: str | os.PathLike[str]) -> bool:
        return self._check(rel).exists()

    def is_file(self, rel: str | os.PathLike[str]) -> bool:
        return self._check(rel).is_file()

    def is_dir(self, rel: str | os.PathLike[str]) -> bool:
        return self._check(rel).is_dir()

    def read_bytes(self, rel: str | os.PathLike[str]) -> bytes:
        canonical = normalize_relative_path(rel)
        path = self._check(canonical)
        if not path.is_file():
            raise FileNotFoundError(path)
        self._check(canonical)
        if self._supports_dir_fd_replace():
            parent_fd = self._open_parent_fd(canonical)
            file_fd: int | None = None
            try:
                file_fd = os.open(
                    PurePosixPath(canonical).name,
                    os.O_RDONLY | os.O_NOFOLLOW,
                    dir_fd=parent_fd,
                )
                info = os.fstat(file_fd)
                if not stat.S_ISREG(info.st_mode):
                    raise _unsafe(path, "read source is not a regular file")
                with os.fdopen(file_fd, "rb") as handle:
                    file_fd = None
                    return handle.read()
            finally:
                if file_fd is not None:
                    os.close(file_fd)
                os.close(parent_fd)
        return path.read_bytes()

    def read_text(self, rel: str | os.PathLike[str], *, encoding: str = "utf-8") -> str:
        return self.read_bytes(rel).decode(encoding)

    def stat(self, rel: str | os.PathLike[str]) -> os.stat_result:
        """Return link-free metadata after validating project containment."""

        canonical = normalize_relative_path(rel)
        path = self._check(canonical)
        self._check(canonical)
        if self._supports_dir_fd_replace():
            parent_fd = self._open_parent_fd(canonical)
            try:
                info = os.stat(
                    PurePosixPath(canonical).name,
                    dir_fd=parent_fd,
                    follow_symlinks=False,
                )
                if stat.S_ISLNK(info.st_mode):
                    raise _unsafe(path, "metadata target changed to a symbolic link")
                return info
            finally:
                os.close(parent_fd)
        return path.lstat()

    def mkdir(self, rel: str | os.PathLike[str], *, parents: bool = True) -> Path:
        """Create a safe project directory and return its absolute path."""

        self._require_secure_mutation("directory creation")
        self.ensure_root()
        parts = self._parts(rel)
        if self._supports_dir_fd_replace() and os.mkdir in os.supports_dir_fd:
            return self._mkdir_dir_fd(parts, parents=parents)
        if not parents:
            parent_rel = "/".join(parts[:-1])
            if parent_rel:
                parent = self._check(parent_rel)
                if not parent.is_dir():
                    raise FileNotFoundError(parent)
            path = self._check("/".join(parts))
            self._check("/".join(parts), include_leaf=False)
            path.mkdir(exist_ok=True)
            return self._check("/".join(parts))

        current_parts: list[str] = []
        for part in parts:
            current_parts.append(part)
            current_rel = "/".join(current_parts)
            path = self._check(current_rel)
            if path.exists():
                if not path.is_dir():
                    raise _unsafe(
                        path, "directory creation encountered a non-directory"
                    )
                continue
            self._check(current_rel, include_leaf=False)
            try:
                path.mkdir()
            except FileExistsError:
                pass
            checked = self._check(current_rel)
            if not checked.is_dir():
                raise _unsafe(checked, "new directory was replaced by an unsafe entry")
        return self.root.joinpath(*parts)

    def _mkdir_dir_fd(self, parts: tuple[str, ...], *, parents: bool) -> Path:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        current_fd = self._open_verified_root_fd()
        try:
            for index, part in enumerate(parts):
                try:
                    next_fd = os.open(part, flags, dir_fd=current_fd)
                except FileNotFoundError:
                    if not parents and index != len(parts) - 1:
                        raise
                    os.mkdir(part, dir_fd=current_fd)
                    next_fd = os.open(part, flags, dir_fd=current_fd)
                except OSError as exc:
                    unsafe_part = self.root.joinpath(*parts[: index + 1])
                    raise _unsafe(
                        unsafe_part,
                        f"directory component is not a link-free directory ({exc})",
                    ) from exc
                os.close(current_fd)
                current_fd = next_fd
        finally:
            os.close(current_fd)
        return self._check("/".join(parts))

    def write_bytes(
        self,
        rel: str | os.PathLike[str],
        data: bytes,
        *,
        mode: int | None = None,
    ) -> Path:
        """Atomically replace one regular file inside the project."""

        self._require_secure_mutation("atomic file write")
        canonical = normalize_relative_path(rel)
        parent_rel = PurePosixPath(canonical).parent.as_posix()
        if parent_rel != ".":
            self.mkdir(parent_rel)
        else:
            self.ensure_root()
        path = self._check(canonical)
        if path.exists() and not path.is_file():
            raise _unsafe(path, "atomic write destination is not a regular file")
        if mode is None:
            try:
                mode = stat.S_IMODE(path.lstat().st_mode)
            except FileNotFoundError:
                mode = 0o666
        parent = self._check(canonical, include_leaf=False).parent
        # Recheck both ancestry and leaf immediately before creating/replacing.
        self._check(canonical)
        if self._supports_dir_fd_replace():
            return self._write_bytes_dir_fd(canonical, data, mode)

        parent_identity = self._directory_identity(parent)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=parent)
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                if hasattr(os, "fchmod"):
                    os.fchmod(handle.fileno(), mode)
                else:  # pragma: no cover - Windows fallback
                    os.chmod(tmp, mode)
            self._before_replace(canonical, path)
            self._check(canonical)
            if self._directory_identity(parent) != parent_identity:
                raise _unsafe(
                    parent, "destination directory changed before atomic replace"
                )
            os.replace(tmp, path)
        except BaseException:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        return self._check(canonical)

    @staticmethod
    def _supports_dir_fd_replace() -> bool:
        return (
            os.name == "posix"
            and os.open in os.supports_dir_fd
            and os.rename in os.supports_dir_fd
            and hasattr(os, "O_DIRECTORY")
            and hasattr(os, "O_NOFOLLOW")
        )

    @staticmethod
    def _directory_identity(path: Path) -> tuple[int, int]:
        info = path.lstat()
        return info.st_dev, info.st_ino

    def _before_replace(self, rel: str, path: Path) -> None:
        """Test seam immediately before the final file replacement."""

    def _before_remove_tree(self, rel: str, path: Path) -> None:
        """Test seam after the removal target is descriptor-anchored."""

    def _before_move(self, source_rel: str, destination_rel: str) -> None:
        """Test seam after the source leaf is descriptor-pinned."""

    def _before_chmod(self, rel: str, path: Path) -> None:
        """Test seam after link-count inspection and before opening the leaf."""

    def _open_parent_fd(self, canonical: str) -> int:
        """Open the destination parent one component at a time, never following links."""

        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        current_fd = self._open_verified_root_fd()
        try:
            for part in PurePosixPath(canonical).parts[:-1]:
                next_fd = os.open(part, flags, dir_fd=current_fd)
                os.close(current_fd)
                current_fd = next_fd
            return current_fd
        except BaseException:
            os.close(current_fd)
            raise

    def _write_bytes_dir_fd(self, canonical: str, data: bytes, mode: int) -> Path:
        """POSIX atomic write anchored by directory descriptors."""

        leaf = PurePosixPath(canonical).name
        parent_fd = self._open_parent_fd(canonical)
        tmp_leaf = f".{leaf}.{uuid.uuid4().hex}"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        file_fd: int | None = None
        try:
            file_fd = os.open(tmp_leaf, flags, mode, dir_fd=parent_fd)
            with os.fdopen(file_fd, "wb") as handle:
                file_fd = None
                handle.write(data)
                handle.flush()
                os.fchmod(handle.fileno(), mode)
            self._before_replace(canonical, self.root / canonical)
            # The open descriptor remains anchored to the verified project tree
            # even if an attacker swaps a lexical parent after validation.
            os.rename(
                tmp_leaf,
                leaf,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
            )
        except BaseException:
            if file_fd is not None:
                os.close(file_fd)
            try:
                os.unlink(tmp_leaf, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
            raise
        finally:
            os.close(parent_fd)
        return self._check(canonical)

    def write_text(
        self,
        rel: str | os.PathLike[str],
        text: str,
        *,
        encoding: str = "utf-8",
        mode: int | None = None,
    ) -> Path:
        return self.write_bytes(rel, text.encode(encoding), mode=mode)

    def create_exclusive(
        self,
        rel: str | os.PathLike[str],
        data: bytes = b"",
        *,
        mode: int = 0o600,
    ) -> None:
        """Create a regular file with ``O_EXCL`` without following links.

        Runtime lock implementations should use this primitive, inspect stale
        locks with :meth:`stat`, and remove them with :meth:`unlink`.
        """

        self._require_secure_mutation("exclusive file creation")
        canonical = normalize_relative_path(rel)
        parent_rel = PurePosixPath(canonical).parent.as_posix()
        if parent_rel != ".":
            self.mkdir(parent_rel)
        else:
            self.ensure_root()
        path = self._check(canonical)
        if path.exists():
            raise FileExistsError(path)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        if self._supports_dir_fd_replace():
            parent_fd = self._open_parent_fd(canonical)
            leaf = PurePosixPath(canonical).name
            created = False
            try:
                fd = os.open(leaf, flags, mode, dir_fd=parent_fd)
                created = True
                with os.fdopen(fd, "wb") as handle:
                    handle.write(data)
                    handle.flush()
            except BaseException:
                if created:
                    try:
                        os.unlink(leaf, dir_fd=parent_fd)
                    except FileNotFoundError:
                        pass
                raise
            finally:
                os.close(parent_fd)
            self._check(canonical)
            return

        parent = path.parent
        identity = self._directory_identity(parent)
        self._check(canonical)
        fd = os.open(path, flags, mode)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
        except BaseException:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        if self._directory_identity(parent) != identity:
            raise _unsafe(parent, "lock destination directory changed during creation")
        self._check(canonical)

    def copy_file(
        self, source: str | os.PathLike[str], rel: str | os.PathLike[str]
    ) -> Path:
        """Copy a verified regular source file to a safe project destination."""

        src = Path(source)
        try:
            source_rel = src.relative_to(self.root).as_posix()
        except ValueError:
            source_rel = None
        if source_rel is not None:
            source_mode = stat.S_IMODE(self.stat(source_rel).st_mode)
            return self.write_bytes(rel, self.read_bytes(source_rel), mode=source_mode)
        _assert_source_tree_safe(src)
        source_mode = stat.S_IMODE(src.lstat().st_mode)
        return self.write_bytes(rel, src.read_bytes(), mode=source_mode)

    def copy_tree(
        self,
        source: str | os.PathLike[str],
        rel: str | os.PathLike[str],
        *,
        ignore: Callable[[Path], bool] | None = None,
    ) -> Path:
        """Recursively copy a link-free source tree to a non-existing destination.

        ``ignore`` receives each source-relative path. It is intended for callers
        that copy packaged payloads, where installer-created bytecode/cache files
        are not product content. Transaction and rollback callers omit it and
        therefore retain exact-tree semantics.
        """

        src = Path(source)
        _assert_source_tree_safe(src)
        canonical = normalize_relative_path(rel)
        dest = self._check(canonical)
        if dest.exists():
            raise FileExistsError(dest)
        self.mkdir(canonical)
        for current, dirs, files in os.walk(src, followlinks=False):
            current_path = Path(current)
            current_rel = current_path.relative_to(src)
            dest_rel = PurePosixPath(canonical, current_rel.as_posix())
            dirs[:] = [
                dirname
                for dirname in sorted(dirs)
                if ignore is None or not ignore(current_rel / dirname)
            ]
            for dirname in dirs:
                child = PurePosixPath(dest_rel, dirname).as_posix()
                self.mkdir(child)
            for filename in sorted(files):
                source_rel = current_rel / filename
                if ignore is not None and ignore(source_rel):
                    continue
                source_file = current_path / filename
                child = PurePosixPath(dest_rel, filename).as_posix()
                self.copy_file(source_file, child)
        return self._check(canonical)

    def unlink(self, rel: str | os.PathLike[str], *, missing_ok: bool = False) -> None:
        self._require_secure_mutation("file deletion")
        canonical = normalize_relative_path(rel)
        path = self._check(canonical)
        self._check(canonical)
        if self._supports_dir_fd_replace() and os.unlink in os.supports_dir_fd:
            parent_fd = self._open_parent_fd(canonical)
            try:
                os.unlink(PurePosixPath(canonical).name, dir_fd=parent_fd)
            except FileNotFoundError:
                if not missing_ok:
                    raise
            finally:
                os.close(parent_fd)
            return
        try:
            path.unlink()
        except FileNotFoundError:
            if not missing_ok:
                raise

    def remove_tree(
        self, rel: str | os.PathLike[str], *, missing_ok: bool = False
    ) -> None:
        self._require_secure_mutation("recursive deletion")
        canonical = normalize_relative_path(rel)
        path = self.assert_tree_safe(canonical)
        if not path.exists():
            if missing_ok:
                return
            raise FileNotFoundError(path)
        if not path.is_dir():
            raise _unsafe(path, "recursive removal target is not a directory")
        self.assert_tree_safe(canonical)
        if self._supports_descriptor_removal():
            self._remove_tree_dir_fd(canonical)
            # Detect an ancestry swap even though descriptor anchoring ensured
            # the deletion could not escape into the replacement tree.
            self._check(canonical)
            return
        shutil.rmtree(path)

    @staticmethod
    def _supports_descriptor_removal() -> bool:
        return (
            ProjectFS._supports_dir_fd_replace()
            and os.listdir in os.supports_fd
            and os.stat in os.supports_dir_fd
            and os.unlink in os.supports_dir_fd
            and os.rmdir in os.supports_dir_fd
        )

    def _remove_tree_dir_fd(self, canonical: str) -> None:
        """Recursively delete a tree through verified directory capabilities."""

        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        parent_fd = self._open_parent_fd(canonical)
        leaf = PurePosixPath(canonical).name
        target_fd: int | None = None
        try:
            target_fd = os.open(leaf, flags, dir_fd=parent_fd)
            target_info = os.fstat(target_fd)
            self._before_remove_tree(canonical, self.root / canonical)
            self._empty_directory_fd(
                target_fd, self.root / canonical, allow_links=False
            )
            current = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
            if (current.st_dev, current.st_ino) != (
                target_info.st_dev,
                target_info.st_ino,
            ):
                raise _unsafe(
                    self.root / canonical,
                    "recursive removal target changed during deletion",
                )
            os.rmdir(leaf, dir_fd=parent_fd)
        finally:
            if target_fd is not None:
                os.close(target_fd)
            os.close(parent_fd)

    def _empty_directory_fd(
        self, directory_fd: int, display: Path, *, allow_links: bool
    ) -> None:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        for name in sorted(os.listdir(directory_fd)):
            try:
                info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            except FileNotFoundError:
                continue
            child_display = display / name
            if _is_link_or_reparse(child_display, info):
                if allow_links:
                    os.unlink(name, dir_fd=directory_fd)
                    continue
                raise _unsafe(
                    child_display,
                    "tree changed to contain a symlink, junction, or reparse point",
                )
            if stat.S_ISDIR(info.st_mode):
                child_fd: int | None = None
                try:
                    child_fd = os.open(name, flags, dir_fd=directory_fd)
                    opened = os.fstat(child_fd)
                    if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                        raise _unsafe(
                            child_display,
                            "directory changed while recursive removal opened it",
                        )
                    self._empty_directory_fd(
                        child_fd, child_display, allow_links=allow_links
                    )
                    current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                    if (current.st_dev, current.st_ino) != (
                        opened.st_dev,
                        opened.st_ino,
                    ):
                        raise _unsafe(
                            child_display,
                            "directory changed during recursive removal",
                        )
                    os.rmdir(name, dir_fd=directory_fd)
                finally:
                    if child_fd is not None:
                        os.close(child_fd)
            elif stat.S_ISREG(info.st_mode):
                os.unlink(name, dir_fd=directory_fd)
            elif allow_links:
                os.unlink(name, dir_fd=directory_fd)
            else:
                raise _unsafe(
                    child_display,
                    "tree changed to contain a special filesystem entry",
                )

    def remove_entry_nofollow(
        self, rel: str | os.PathLike[str], *, missing_ok: bool = False
    ) -> None:
        """Remove one rollback target without following an unsafe leaf.

        This is reserved for restoring a fully preflighted transaction snapshot:
        ancestry remains descriptor-verified, while a raced leaf link is unlinked
        rather than traversed.
        """

        self._require_secure_mutation("rollback entry removal")
        canonical = normalize_relative_path(rel)
        self._check(canonical, include_leaf=False)
        parent_fd = self._open_parent_fd(canonical)
        leaf = PurePosixPath(canonical).name
        try:
            try:
                info = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                if missing_ok:
                    return
                raise
            if stat.S_ISDIR(info.st_mode):
                flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                child_fd = os.open(leaf, flags, dir_fd=parent_fd)
                try:
                    opened = os.fstat(child_fd)
                    if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                        raise _unsafe(
                            self.root / canonical,
                            "rollback target changed while it was opened",
                        )
                    self._empty_directory_fd(
                        child_fd,
                        self.root / canonical,
                        allow_links=True,
                    )
                    current = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
                    if (current.st_dev, current.st_ino) != (
                        opened.st_dev,
                        opened.st_ino,
                    ):
                        raise _unsafe(
                            self.root / canonical,
                            "rollback target changed during removal",
                        )
                    os.rmdir(leaf, dir_fd=parent_fd)
                finally:
                    os.close(child_fd)
            else:
                os.unlink(leaf, dir_fd=parent_fd)
        finally:
            os.close(parent_fd)

    def move(
        self,
        source_rel: str | os.PathLike[str],
        destination_rel: str | os.PathLike[str],
    ) -> Path:
        """Atomically move one safe project entry to another project path."""

        self._require_secure_mutation("project entry move")
        source = normalize_relative_path(source_rel)
        destination = normalize_relative_path(destination_rel)
        src = self.assert_tree_safe(source)
        if not src.exists():
            raise FileNotFoundError(src)
        parent = PurePosixPath(destination).parent.as_posix()
        if parent != ".":
            self.mkdir(parent)
        dest = self._check(destination)
        if dest.exists():
            raise FileExistsError(dest)
        self.assert_tree_safe(source)
        self._check(destination)
        if self._supports_dir_fd_replace():
            source_parent_fd = self._open_parent_fd(source)
            destination_parent_fd = self._open_parent_fd(destination)
            source_fd: int | None = None
            try:
                source_leaf = PurePosixPath(source).name
                source_info = os.stat(
                    source_leaf,
                    dir_fd=source_parent_fd,
                    follow_symlinks=False,
                )
                flags = os.O_RDONLY | os.O_NOFOLLOW
                if stat.S_ISDIR(source_info.st_mode):
                    flags |= os.O_DIRECTORY
                elif not stat.S_ISREG(source_info.st_mode):
                    raise _unsafe(src, "move source is not a regular file or directory")
                source_fd = os.open(source_leaf, flags, dir_fd=source_parent_fd)
                pinned = os.fstat(source_fd)
                if (pinned.st_dev, pinned.st_ino) != (
                    source_info.st_dev,
                    source_info.st_ino,
                ):
                    raise _unsafe(src, "move source changed while it was pinned")
                self._before_move(source, destination)
                os.rename(
                    source_leaf,
                    PurePosixPath(destination).name,
                    src_dir_fd=source_parent_fd,
                    dst_dir_fd=destination_parent_fd,
                )
                moved = os.stat(
                    PurePosixPath(destination).name,
                    dir_fd=destination_parent_fd,
                    follow_symlinks=False,
                )
                if (moved.st_dev, moved.st_ino) != (
                    pinned.st_dev,
                    pinned.st_ino,
                ):
                    # A raced source leaf may have been renamed into the live
                    # destination. Remove it through the verified parent so
                    # rollback never has to traverse an unsafe leaf.
                    self.remove_entry_nofollow(destination, missing_ok=True)
                    raise _unsafe(
                        dest, "move source changed immediately before promotion"
                    )
            finally:
                if source_fd is not None:
                    os.close(source_fd)
                os.close(source_parent_fd)
                os.close(destination_parent_fd)
            return self._check(destination)
        os.replace(src, dest)
        return self._check(destination)

    def chmod(self, rel: str | os.PathLike[str], mode: int) -> None:
        self._require_secure_mutation("file mode change")
        canonical = normalize_relative_path(rel)
        path = self._check(canonical)
        if self._supports_dir_fd_replace() and hasattr(os, "fchmod"):
            parent_fd = self._open_parent_fd(canonical)
            file_fd: int | None = None
            try:
                leaf = PurePosixPath(canonical).name
                before = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
                if not stat.S_ISREG(before.st_mode):
                    raise _unsafe(path, "file mode target is not a regular file")
                if before.st_nlink != 1:
                    raise _unsafe(
                        path,
                        "file mode target has multiple hard links and could affect another path",
                    )
                self._before_chmod(canonical, path)
                file_fd = os.open(
                    leaf,
                    os.O_RDONLY | os.O_NOFOLLOW,
                    dir_fd=parent_fd,
                )
                opened = os.fstat(file_fd)
                if (opened.st_dev, opened.st_ino) != (
                    before.st_dev,
                    before.st_ino,
                ) or opened.st_nlink != 1:
                    raise _unsafe(
                        path,
                        "file mode target changed or gained a hard link before mutation",
                    )
                os.fchmod(file_fd, mode)
            finally:
                if file_fd is not None:
                    os.close(file_fd)
                os.close(parent_fd)
            return
        if not path.is_file():
            raise FileNotFoundError(path)
        self._check(canonical)
        try:
            os.chmod(path, mode, follow_symlinks=False)
        except (NotImplementedError, TypeError):  # pragma: no cover - Windows fallback
            self._check(canonical)
            os.chmod(path, mode)


class ProjectMutationLease:
    """Handle-tied advisory lease on a project's verified root directory."""

    def __init__(self, fs: ProjectFS, *, exclusive: bool) -> None:
        self.fs = fs
        self.exclusive = exclusive
        self._entered = False

    def __enter__(self) -> ProjectMutationLease:
        if self._entered:
            raise RuntimeError("project mutation lease already entered")
        self.fs._require_secure_mutation("project mutation lease acquisition")
        self.fs.ensure_root()
        depth = int(getattr(self.fs._lease_local, "depth", 0))
        held_exclusive = bool(getattr(self.fs._lease_local, "exclusive", False))
        if depth:
            if self.exclusive and not held_exclusive:
                raise UnsafePathError(
                    "cannot upgrade a shared project mutation lease to exclusive"
                )
            self.fs._lease_local.depth = depth + 1
            self._entered = True
            return self

        try:
            import fcntl
        except ImportError as exc:  # pragma: no cover - fail-closed Windows policy
            raise UnsafePathError(
                "project mutation leases require POSIX flock support"
            ) from exc
        root_fd = self.fs._open_verified_root_fd()
        operation = fcntl.LOCK_EX if self.exclusive else fcntl.LOCK_SH
        try:
            fcntl.flock(root_fd, operation | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(root_fd)
            raise UnsafePathError(
                f"project mutation is busy for {self.fs.root}; another claude-kit "
                "transaction is active, so retry after it finishes"
            ) from exc
        except BaseException:
            os.close(root_fd)
            raise
        self.fs._lease_local.depth = 1
        self.fs._lease_local.exclusive = self.exclusive
        self.fs._lease_local.fd = root_fd
        self._entered = True
        return self

    def __exit__(self, _exc_type: Any, _exc: Any, _tb: Any) -> Literal[False]:
        if not self._entered:
            return False
        depth = int(getattr(self.fs._lease_local, "depth", 0))
        if depth > 1:
            self.fs._lease_local.depth = depth - 1
        else:
            root_fd = int(self.fs._lease_local.fd)
            try:
                import fcntl

                fcntl.flock(root_fd, fcntl.LOCK_UN)
            finally:
                os.close(root_fd)
                for name in ("depth", "exclusive", "fd"):
                    try:
                        delattr(self.fs._lease_local, name)
                    except AttributeError:
                        pass
        self._entered = False
        return False


class ProjectTransaction:
    """Rollback transaction for claude-kit's bounded project mutation surface."""

    def __init__(
        self,
        fs: ProjectFS,
        *,
        operation: str,
        from_version: str = "(untracked)",
        to_version: str = "",
        actions: list[dict[str, str]] | None = None,
    ) -> None:
        if operation not in {"install", "force", "merge", "upgrade"}:
            raise ValueError(f"unsupported project transaction operation: {operation}")
        self.fs = fs
        self.operation = operation
        self.from_version = from_version
        self.to_version = to_version
        self.actions = list(actions or [])
        self.transaction_rel = f"{_TRANSACTION_PREFIX}{uuid.uuid4().hex}"
        self._started = False
        self._lease: ProjectMutationLease | None = None
        self._root_existed = fs.root.exists()

    def _release_lease(self) -> None:
        if self._lease is not None:
            lease = self._lease
            self._lease = None
            lease.__exit__(None, None, None)

    def _document(self, states: dict[str, str], backups: list[str]) -> dict[str, Any]:
        return {
            "schema_version": TRANSACTION_SCHEMA,
            "from_version": self.from_version,
            "to_version": self.to_version,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "actions": self.actions,
            "transaction_kind": self.operation,
            "phase": "applying",
            "transaction_dir": self.transaction_rel,
            "root_existed": self._root_existed,
            "protected": states,
            "existing_backups": backups,
        }

    def begin(self) -> None:
        if self._started:
            raise RuntimeError("project transaction already started")
        self._root_existed = self.fs.root.exists()
        self.fs.ensure_root()
        self._lease = self.fs.mutation_lease(exclusive=True)
        self._lease.__enter__()
        document: dict[str, Any] | None = None
        try:
            recovered = _recover_interrupted_transaction_locked(
                self.fs, preserve_root=True
            )
            if recovered is not None and not bool(recovered.get("root_existed", True)):
                # The empty root is only the held lock anchor; rollback of this
                # rerun must retain the original fresh-install semantics.
                self._root_existed = False
                if self.operation == "merge":
                    self.operation = "install"
            backups: list[str] = []
            for entry in self.fs.root.iterdir():
                if not entry.name.startswith(_BACKUP_PREFIXES):
                    continue
                rel = normalize_relative_path(entry.name)
                checked = self.fs.assert_tree_safe(rel)
                if checked.is_dir():
                    backups.append(entry.name)
            backups.sort()
            states: dict[str, str] = {}
            self.fs.mkdir(f"{self.transaction_rel}/rollback")
            for rel in _PROTECTED_PATHS:
                path = self.fs.assert_tree_safe(rel)
                if not path.exists():
                    states[rel] = "missing"
                    continue
                backup_rel = f"{self.transaction_rel}/rollback/{rel}"
                if path.is_dir():
                    states[rel] = "directory"
                    self.fs.copy_tree(path, backup_rel)
                elif path.is_file():
                    states[rel] = "file"
                    self.fs.copy_file(path, backup_rel)
                else:
                    raise _unsafe(
                        path, "transaction cannot snapshot a special filesystem entry"
                    )
            document = self._document(states, backups)
            encoded = json.dumps(document, indent=2) + "\n"
            self.fs.write_text(f"{self.transaction_rel}/{_TRANSACTION_MARKER}", encoded)
            # Journal last: its presence promises that the rollback snapshot is complete.
            self.fs.write_text(JOURNAL_PATH, encoded)
        except Exception:
            try:
                if document is not None:
                    # Snapshot completion is the setup transaction's own commit
                    # boundary. If publishing the marker/journal fails, restore from
                    # that in-memory document just like a live-mutation rollback.
                    _restore_document(self.fs, document, require_marker=False)
                else:
                    self.fs.remove_tree(self.transaction_rel, missing_ok=True)
                    if not self._root_existed:
                        try:
                            self.fs.root.rmdir()
                            self.fs._root_identity = None
                        except OSError:
                            pass
            finally:
                self._release_lease()
            raise
        self._started = True

    def commit(self) -> None:
        if not self._started:
            return
        document = self._read_document()
        document["phase"] = "committed"
        encoded = json.dumps(document, indent=2) + "\n"
        # The durable commit point is the top-level marker.  Recovery consults it
        # even while an older ``applying`` copy remains in .claude/config.
        try:
            self.fs.write_text(f"{self.transaction_rel}/{_TRANSACTION_MARKER}", encoded)
        except Exception:
            self.rollback()
            raise
        try:
            if self.fs.is_file(JOURNAL_PATH):
                self.fs.write_text(JOURNAL_PATH, encoded)
            self.fs.unlink(JOURNAL_PATH, missing_ok=True)
            self.fs.remove_tree(self.transaction_rel, missing_ok=True)
        finally:
            self._started = False
            self._release_lease()

    def rollback(self) -> None:
        if not self._started:
            return
        try:
            _restore_document(self.fs, self._read_document())
        finally:
            self._started = False
            self._release_lease()

    def _read_document(self) -> dict[str, Any]:
        return json.loads(
            self.fs.read_text(f"{self.transaction_rel}/{_TRANSACTION_MARKER}")
        )

    def __enter__(self) -> ProjectTransaction:
        self.begin()
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, _exc: BaseException | None, _tb: Any
    ) -> Literal[False]:
        if exc_type is None:
            self.commit()
        elif issubclass(exc_type, Exception):
            self.rollback()
        # KeyboardInterrupt/SystemExit model abrupt process interruption: retain
        # journal + rollback data for the next invocation.
        else:
            self._started = False
            self._release_lease()
        return False


def _read_json_object(fs: ProjectFS, rel: str) -> dict[str, Any]:
    try:
        document = json.loads(fs.read_text(rel))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise UnsafePathError(
            f"cannot recover interrupted claude-kit transaction: {rel} is corrupt ({exc})"
        ) from exc
    if not isinstance(document, dict):
        raise UnsafePathError(
            f"cannot recover interrupted claude-kit transaction: {rel} must contain a JSON object"
        )
    return document


def _is_legacy_upgrade_document(document: dict[str, Any]) -> bool:
    """Return whether this is the old convergence-only schema-1 marker."""

    schema = document.get("schema_version", 1)
    return (
        schema == 1
        and "transaction_dir" not in document
        and "transaction_kind" not in document
        and "protected" not in document
    )


def _load_recovery_document(fs: ProjectFS) -> dict[str, Any] | None:
    legacy: dict[str, Any] | None = None
    if fs.is_file(JOURNAL_PATH):
        primary = _read_json_object(fs, JOURNAL_PATH)
        schema = primary.get("schema_version", 1)
        if schema == TRANSACTION_SCHEMA:
            # A crash can happen after the top marker reaches ``committed`` but
            # before the live journal is updated/removed.  The commit marker is
            # authoritative, so never roll that successful operation back.
            transaction_rel = normalize_relative_path(
                str(primary.get("transaction_dir", ""))
            )
            marker_rel = f"{transaction_rel}/{_TRANSACTION_MARKER}"
            if fs.is_file(marker_rel):
                marker = _read_json_object(fs, marker_rel)
                if marker.get("schema_version") != TRANSACTION_SCHEMA:
                    raise UnsafePathError(
                        "cannot recover interrupted claude-kit transaction: "
                        "transaction marker uses an unsupported schema"
                    )
                if marker.get("transaction_dir") != transaction_rel:
                    raise UnsafePathError(
                        "cannot recover interrupted claude-kit transaction: "
                        "journal and transaction marker disagree"
                    )
                if marker.get("phase") == "committed":
                    return marker
                if primary.get("phase") == "committed":
                    raise UnsafePathError(
                        "cannot recover interrupted claude-kit transaction: "
                        "journal is committed but transaction marker is not"
                    )
            elif primary.get("phase") == "committed":
                raise UnsafePathError(
                    "cannot recover interrupted claude-kit transaction: "
                    "committed journal has no transaction marker"
                )
            return primary
        if _is_legacy_upgrade_document(primary):
            legacy = primary
        else:
            raise UnsafePathError(
                "cannot recover interrupted claude-kit transaction: unsupported journal schema "
                f"{schema!r}; expected legacy schema 1 or transaction schema "
                f"{TRANSACTION_SCHEMA}"
            )
    # Rollback may have removed .claude (and therefore the primary journal)
    # before an interruption.  The top-level duplicate makes recovery resumable.
    if not fs.root.exists():
        return None
    for candidate in sorted(fs.root.iterdir()):
        if not candidate.name.startswith(_TRANSACTION_PREFIX):
            continue
        candidate = fs.assert_tree_safe(normalize_relative_path(candidate.name))
        rel = f"{candidate.name}/{_TRANSACTION_MARKER}"
        if fs.is_file(rel):
            candidate_document = _read_json_object(fs, rel)
            if candidate_document.get("schema_version") != TRANSACTION_SCHEMA:
                raise UnsafePathError(
                    "cannot recover interrupted claude-kit transaction: unsupported marker schema "
                    f"{candidate_document.get('schema_version')!r}"
                )
            return candidate_document
    return legacy


def inspect_interrupted_transaction(fs: ProjectFS) -> dict[str, Any] | None:
    """Read the authoritative lifecycle marker without mutating the project.

    Doctor/status callers should use this instead of assuming the nested journal
    still exists: backup-mode installation deliberately moves ``.claude`` while
    the top-level duplicate remains authoritative. Unsafe/corrupt/future markers
    raise :class:`UnsafePathError` and are never followed or recovered here.
    """

    if not fs.root.exists():
        return None
    document = _load_recovery_document(fs)
    if document is not None and document.get("schema_version") == TRANSACTION_SCHEMA:
        _validate_document(document)
    return document


def _validate_document(
    document: dict[str, Any],
) -> tuple[str, dict[str, str], set[str]]:
    if document.get("schema_version") != TRANSACTION_SCHEMA:
        raise UnsafePathError(
            "cannot recover interrupted claude-kit transaction: unsupported journal schema "
            f"{document.get('schema_version')!r}; expected {TRANSACTION_SCHEMA}"
        )
    transaction_rel = normalize_relative_path(str(document.get("transaction_dir", "")))
    if not transaction_rel.startswith(_TRANSACTION_PREFIX) or "/" in transaction_rel:
        raise UnsafePathError(
            f"cannot recover interrupted transaction from unexpected directory {transaction_rel!r}"
        )
    raw_states = document.get("protected")
    if not isinstance(raw_states, dict) or set(raw_states) != set(_PROTECTED_PATHS):
        raise UnsafePathError(
            "cannot recover interrupted transaction: invalid protected-path map"
        )
    states: dict[str, str] = {}
    for rel, value in raw_states.items():
        normalize_relative_path(str(rel))
        if rel not in _PROTECTED_PATHS or value not in {"missing", "file", "directory"}:
            raise UnsafePathError(
                "cannot recover interrupted transaction: invalid protected state"
            )
        states[str(rel)] = str(value)
    raw_backups = document.get("existing_backups", [])
    if not isinstance(raw_backups, list):
        raise UnsafePathError(
            "cannot recover interrupted transaction: invalid backup list"
        )
    backups = {normalize_relative_path(str(item)) for item in raw_backups}
    if any(not item.startswith(_BACKUP_PREFIXES) or "/" in item for item in backups):
        raise UnsafePathError(
            "cannot recover interrupted transaction: invalid backup directory"
        )
    if document.get("phase") not in {"applying", "committed"}:
        raise UnsafePathError(
            "cannot recover interrupted transaction: invalid transaction phase"
        )
    return transaction_rel, states, backups


def _documents_match_marker(document: dict[str, Any], marker: dict[str, Any]) -> bool:
    keys = (
        "schema_version",
        "transaction_dir",
        "transaction_kind",
        "root_existed",
        "protected",
        "existing_backups",
        "from_version",
        "to_version",
        "actions",
    )
    return all(document.get(key) == marker.get(key) for key in keys)


def _preflight_restore(
    fs: ProjectFS,
    document: dict[str, Any],
    *,
    require_marker: bool,
) -> tuple[str, dict[str, str], set[str], list[str]]:
    """Validate the complete rollback set before the first destructive action."""

    transaction_rel, states, existing_backups = _validate_document(document)
    transaction = fs.assert_tree_safe(transaction_rel)
    if not transaction.is_dir():
        raise UnsafePathError(
            "cannot recover interrupted transaction: rollback directory is missing"
        )
    rollback_rel = f"{transaction_rel}/rollback"
    rollback = fs.assert_tree_safe(rollback_rel)
    if not rollback.is_dir():
        raise UnsafePathError(
            "cannot recover interrupted transaction: rollback snapshot is missing"
        )

    marker_rel = f"{transaction_rel}/{_TRANSACTION_MARKER}"
    if require_marker:
        marker_path = fs.assert_safe(marker_rel)
        if not marker_path.is_file():
            raise UnsafePathError(
                "cannot recover interrupted transaction: transaction marker is missing"
            )
        marker = _read_json_object(fs, marker_rel)
        if not _documents_match_marker(document, marker):
            raise UnsafePathError(
                "cannot recover interrupted transaction: journal and transaction marker disagree"
            )

    # Live leaves may themselves be the result of the interrupted race. Validate
    # their parents now; restoration removes each leaf through a verified parent
    # descriptor without following it.
    for rel in states:
        fs._check(rel, include_leaf=False)

    # Check every declared snapshot and its exact type before deleting live data.
    for rel, state_name in states.items():
        if state_name == "missing":
            continue
        backup_rel = f"{rollback_rel}/{rel}"
        backup = (
            fs.assert_tree_safe(backup_rel)
            if state_name == "directory"
            else fs.assert_safe(backup_rel)
        )
        if state_name == "directory" and not backup.is_dir():
            raise UnsafePathError(
                f"cannot recover interrupted transaction: directory backup missing for {rel}"
            )
        if state_name == "file":
            try:
                info = backup.lstat()
            except FileNotFoundError as exc:
                raise UnsafePathError(
                    f"cannot recover interrupted transaction: file backup missing for {rel}"
                ) from exc
            if not stat.S_ISREG(info.st_mode):
                raise UnsafePathError(
                    f"cannot recover interrupted transaction: invalid file backup for {rel}"
                )

    for rel in existing_backups:
        backup = fs.assert_tree_safe(rel)
        if not backup.is_dir():
            raise UnsafePathError(
                f"cannot recover interrupted transaction: existing backup {rel} changed"
            )

    current_backups: list[str] = []
    for path in sorted(fs.root.iterdir()):
        if not path.name.startswith(_BACKUP_PREFIXES):
            continue
        rel = normalize_relative_path(path.name)
        if rel in existing_backups:
            checked = fs.assert_tree_safe(rel)
            if not checked.is_dir():
                raise UnsafePathError(
                    f"cannot recover interrupted transaction: backup path {rel} is not a directory"
                )
        else:
            fs._check(rel, include_leaf=False)
        current_backups.append(rel)
    return transaction_rel, states, existing_backups, current_backups


def _restore_document(
    fs: ProjectFS,
    document: dict[str, Any],
    *,
    require_marker: bool = True,
    preserve_root: bool = False,
) -> None:
    transaction_rel, states, existing_backups, current_backups = _preflight_restore(
        fs, document, require_marker=require_marker
    )
    for rel, state_name in states.items():
        fs.remove_entry_nofollow(rel, missing_ok=True)
        if state_name == "directory":
            fs.copy_tree(fs.path(f"{transaction_rel}/rollback/{rel}"), rel)
        elif state_name == "file":
            fs.copy_file(fs.path(f"{transaction_rel}/rollback/{rel}"), rel)

    # Rescue/upgrade backups created during the aborted transaction are part of
    # the mutation and must not survive rollback.  Older backups are untouched.
    for rel in current_backups:
        if rel in existing_backups:
            continue
        fs.remove_entry_nofollow(rel, missing_ok=True)
    fs.remove_tree(transaction_rel, missing_ok=True)
    # Replacing .claude removed the transaction's live journal.  If the original
    # tree contained a legacy journal, the snapshot deliberately restored it.
    if not preserve_root and not bool(document.get("root_existed", True)):
        try:
            fs.root.rmdir()
            fs._root_identity = None
        except OSError:
            pass


def _recover_interrupted_transaction_locked(
    fs: ProjectFS, *, preserve_root: bool
) -> dict[str, Any] | None:
    """Recover while the caller holds the exclusive project mutation lease."""

    try:
        document = _load_recovery_document(fs)
    except FileNotFoundError:
        return None
    if document is None or _is_legacy_upgrade_document(document):
        return None
    if document.get("schema_version") != TRANSACTION_SCHEMA:
        raise UnsafePathError(
            "cannot recover interrupted claude-kit transaction: unsupported journal schema "
            f"{document.get('schema_version')!r}"
        )
    if document.get("phase") == "committed":
        transaction_rel, _states, _backups = _validate_document(document)
        if fs.exists(transaction_rel):
            fs.assert_tree_safe(transaction_rel)
        if fs.exists(JOURNAL_PATH):
            fs.unlink(JOURNAL_PATH)
        fs.remove_tree(transaction_rel, missing_ok=True)
        return document
    _restore_document(fs, document, preserve_root=preserve_root)
    return document


def recover_interrupted_transaction(
    fs: ProjectFS, *, preserve_root: bool = False
) -> bool:
    """Restore an interrupted rollback-capable transaction, if one exists.

    Legacy schema-1 upgrade markers are intentionally left to the upgrader's
    existing convergent path.  Only a schema-2 journal promises a rollback
    snapshot and is therefore eligible for automatic restoration.
    """

    if not fs.root.exists():
        return False
    # A caller that already holds this ProjectFS lease will continue operating after
    # recovery.  Its flock is attached to the current root inode, so deleting that
    # inode would let another process recreate and lock the pathname concurrently.
    # Preserve the root automatically for every nested recovery even if a caller
    # omitted the explicit flag.
    nested_lease = int(getattr(fs._lease_local, "depth", 0)) > 0
    with fs.mutation_lease(exclusive=True):
        return (
            _recover_interrupted_transaction_locked(
                fs, preserve_root=preserve_root or nested_lease
            )
            is not None
        )
