"""Provider-neutral, run-owned git worktree isolation.

Hosts may supply native isolation.  This manager is the deterministic fallback: every worktree has
an owner record in the shared state plane, an exact bounded sibling path, and conservative cleanup.
Failed or dirty workers are preserved unless a caller explicitly authorizes discarding them.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from claude_kit.secure_fs import ProjectFS
from claude_kit.state import detect_state_layout

WORKTREE_REGISTRY_SCHEMA = 1
_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,79}$")
_MAX_CHECKPOINT_PATHS = 100_000
_MAX_CHECKPOINT_BYTES = 2 * 1024 * 1024 * 1024
_CHECKPOINT_HASH_TIMEOUT_SECONDS = 30


class WorktreeError(RuntimeError):
    """A worktree lifecycle action failed a safety or ownership invariant."""


class WorktreeStatus(str, Enum):
    ACTIVE = "active"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ABORTED = "aborted"
    REMOVED = "removed"


@dataclass(frozen=True)
class WorkspaceCheckpoint:
    """Content-addressed identity of one exact managed workspace state."""

    head_commit: str
    tracked_digest: str
    untracked_digest: str
    content_digest: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise WorktreeError("unsupported workspace checkpoint schema")
        if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", self.head_commit):
            raise WorktreeError("workspace checkpoint HEAD must be a commit id")
        for field_name in ("tracked_digest", "untracked_digest", "content_digest"):
            if not re.fullmatch(r"[0-9a-f]{64}", getattr(self, field_name)):
                raise WorktreeError(
                    f"workspace checkpoint {field_name} must be lowercase sha256"
                )

    @classmethod
    def from_dict(cls, document: dict[str, Any]) -> WorkspaceCheckpoint:
        try:
            return cls(
                head_commit=str(document["head_commit"]),
                tracked_digest=str(document["tracked_digest"]),
                untracked_digest=str(document["untracked_digest"]),
                content_digest=str(document["content_digest"]),
                schema_version=int(document.get("schema_version", 0)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise WorktreeError(f"invalid workspace checkpoint: {exc}") from exc

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WorktreeRecord:
    run_id: str
    worker_id: str
    target_path: str
    base_ref: str
    base_commit: str
    gitdir_path: str
    status: WorktreeStatus
    created_at: str
    updated_at: str
    owner: str = "ckit"
    failure_reason: str | None = None
    removed_at: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorktreeRecord:
        try:
            record = cls(
                run_id=str(data["run_id"]),
                worker_id=str(data["worker_id"]),
                target_path=str(data["target_path"]),
                base_ref=str(data["base_ref"]),
                base_commit=str(data["base_commit"]),
                gitdir_path=str(data.get("gitdir_path", "")),
                status=WorktreeStatus(str(data["status"])),
                created_at=str(data["created_at"]),
                updated_at=str(data["updated_at"]),
                owner=str(data.get("owner", "")),
                failure_reason=(
                    str(data["failure_reason"])
                    if data.get("failure_reason") is not None
                    else None
                ),
                removed_at=(
                    str(data["removed_at"])
                    if data.get("removed_at") is not None
                    else None
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise WorktreeError(f"invalid worktree ownership record: {exc}") from exc
        _validate_id(record.run_id, "run_id")
        _validate_id(record.worker_id, "worker_id")
        if record.owner != "ckit":
            raise WorktreeError("worktree owner must be ckit")
        if (
            Path(record.target_path).is_absolute()
            or ".." not in Path(record.target_path).parts
        ):
            raise WorktreeError(
                "worktree target_path must be a portable sibling-relative path"
            )
        if record.gitdir_path and (
            Path(record.gitdir_path).is_absolute()
            or ".." in Path(record.gitdir_path).parts
        ):
            raise WorktreeError("worktree gitdir_path must be repository-relative")
        return record

    def to_dict(self) -> dict[str, Any]:
        document = asdict(self)
        document["status"] = self.status.value
        return document


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _validate_id(value: str, field: str) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value) or ".." in value:
        raise WorktreeError(
            f"{field} must use 1-80 letters, digits, dots, underscores, or hyphens"
        )
    return value


def _run_git(
    root: Path, *args: str, check: bool = True
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            check=check,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise WorktreeError(f"git {' '.join(args)} failed: {exc}") from exc


def _run_git_bytes(root: Path, *args: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            check=True,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise WorktreeError(f"git {' '.join(args)} failed: {exc}") from exc
    return result.stdout


def _framed(digest: Any, value: bytes) -> None:
    digest.update(len(value).to_bytes(8, "big"))
    digest.update(value)


def _is_reparse_point(info: os.stat_result) -> bool:
    attributes = getattr(info, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(attributes & reparse_flag)


def _real_directory(path: Path, *, allow_missing: bool = False) -> None:
    """Reject symlink/reparse redirection at a managed path boundary."""

    try:
        info = path.lstat()
    except FileNotFoundError:
        if allow_missing:
            return
        raise WorktreeError(f"managed worktree directory is missing: {path}") from None
    if stat.S_ISLNK(info.st_mode) or _is_reparse_point(info):
        raise WorktreeError(f"managed worktree path is a link/reparse point: {path}")
    if not stat.S_ISDIR(info.st_mode):
        raise WorktreeError(f"managed worktree path is not a directory: {path}")


def _regular_marker(path: Path) -> str:
    try:
        info = path.lstat()
    except FileNotFoundError:
        raise WorktreeError(
            f"owned worktree has no git marker: {path.parent}"
        ) from None
    if (
        not stat.S_ISREG(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or _is_reparse_point(info)
    ):
        raise WorktreeError(f"owned worktree has no valid git marker: {path.parent}")
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise WorktreeError(f"cannot read owned worktree git marker: {exc}") from exc


def _git_content_identities(root: Path, paths: list[bytes]) -> dict[bytes, bytes]:
    """Hash regular files in one bounded Git-native pass without writing objects."""

    if not paths:
        return {}
    if any(b"\n" in path or b"\r" in path for path in paths):
        raise WorktreeError(
            "managed workspace paths containing newlines cannot be checkpointed safely"
        )
    stdin = b"".join(b"./" + path + b"\n" for path in paths)
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "hash-object",
                "--no-filters",
                "--stdin-paths",
            ],
            input=stdin,
            check=True,
            capture_output=True,
            timeout=_CHECKPOINT_HASH_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise WorktreeError(f"cannot hash managed workspace contents: {exc}") from exc
    identities = result.stdout.splitlines()
    if len(identities) != len(paths) or any(
        not re.fullmatch(rb"[0-9a-f]{40}|[0-9a-f]{64}", identity)
        for identity in identities
    ):
        raise WorktreeError("git returned malformed workspace content identities")
    return dict(zip(paths, identities))


def _workspace_file_records(root: Path, raw_paths: list[bytes]) -> list[bytes]:
    """Return ordered records using one content-hash subprocess for regular files."""

    metadata: dict[bytes, tuple[bytes, bytes | None]] = {}
    regular_paths: list[bytes] = []
    total_bytes = 0
    for raw_path in raw_paths:
        if not raw_path or raw_path.startswith(b"/") or b".." in raw_path.split(b"/"):
            raise WorktreeError("git returned an unsafe workspace path")
        relative = Path(os.fsdecode(raw_path))
        candidate = root / relative
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            metadata[raw_path] = (b"missing", hashlib.sha256(b"").digest())
            continue
        if stat.S_ISLNK(info.st_mode):
            metadata[raw_path] = (b"symlink", os.fsencode(os.readlink(candidate)))
            continue
        if not stat.S_ISREG(info.st_mode):
            raise WorktreeError(
                f"workspace contains unsupported non-regular path: {relative}"
            )
        total_bytes += info.st_size
        if total_bytes > _MAX_CHECKPOINT_BYTES:
            raise WorktreeError(
                "managed workspace regular-file content exceeds the 2 GiB "
                "checkpoint safety limit"
            )
        kind = b"file-executable" if info.st_mode & stat.S_IXUSR else b"file"
        metadata[raw_path] = (kind, None)
        regular_paths.append(raw_path)

    identities = _git_content_identities(root, regular_paths)
    records: list[bytes] = []
    for raw_path in raw_paths:
        kind, inline_identity = metadata[raw_path]
        identity = identities[raw_path] if inline_identity is None else inline_identity
        record = hashlib.sha256()
        _framed(record, raw_path)
        _framed(record, kind)
        _framed(record, identity)
        records.append(record.digest())
    return records


def _workspace_checkpoint_once(
    root: Path, *, git_marker_digest: str
) -> WorkspaceCheckpoint:
    head_commit = (
        _run_git(root, "rev-parse", "--verify", "HEAD^{commit}").stdout.strip().lower()
    )
    tracked_entries = _run_git_bytes(root, "ls-files", "--stage", "-z").split(b"\0")
    tracked_paths: list[bytes] = []
    index_metadata: dict[bytes, bytes] = {}
    for entry in tracked_entries:
        if not entry:
            continue
        try:
            metadata, raw_path = entry.split(b"\t", 1)
            _mode, _object_id, stage = metadata.split(b" ", 2)
        except ValueError as exc:
            raise WorktreeError("git returned malformed tracked-file metadata") from exc
        if stage != b"0":
            raise WorktreeError("managed workspace has unresolved index conflicts")
        tracked_paths.append(raw_path)
        index_metadata[raw_path] = metadata
    if len(tracked_paths) != len(set(tracked_paths)):
        raise WorktreeError("managed workspace index contains duplicate paths")

    tracked_paths.sort()
    tracked = hashlib.sha256()
    for raw_path, record in zip(
        tracked_paths, _workspace_file_records(root, tracked_paths), strict=True
    ):
        # A checkpoint binds both the worktree bytes and the exact index entry.
        # Without the stage/mode/object id, a worker could stage an out-of-boundary
        # payload and restore the visible file before the coordinator checks it.
        _framed(tracked, index_metadata[raw_path])
        _framed(tracked, record)

    untracked_paths = [
        raw_path
        for raw_path in _run_git_bytes(
            root, "ls-files", "--others", "--exclude-standard", "-z"
        ).split(b"\0")
        if raw_path
    ]
    ignored_paths = [
        raw_path
        for raw_path in _run_git_bytes(
            root,
            "ls-files",
            "--others",
            "--ignored",
            "--exclude-standard",
            "-z",
        ).split(b"\0")
        if raw_path
    ]
    untracked_paths.extend(ignored_paths)
    if len(tracked_paths) + len(untracked_paths) > _MAX_CHECKPOINT_PATHS:
        raise WorktreeError(
            "managed workspace has more than 100000 tracked/untracked/ignored files; "
            "reduce generated inputs before checkpointing"
        )
    if len(untracked_paths) != len(set(untracked_paths)):
        raise WorktreeError("managed workspace contains duplicate untracked paths")
    untracked_paths.sort()
    untracked = hashlib.sha256()
    for record in _workspace_file_records(root, untracked_paths):
        _framed(untracked, record)

    tracked_digest = tracked.hexdigest()
    untracked_digest = untracked.hexdigest()
    content_document = {
        "head_commit": head_commit,
        "tracked_digest": tracked_digest,
        "untracked_digest": untracked_digest,
        "git_marker_digest": git_marker_digest,
    }
    content_digest = hashlib.sha256(
        json.dumps(content_document, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    return WorkspaceCheckpoint(
        head_commit,
        tracked_digest,
        untracked_digest,
        content_digest,
    )


class WorktreeManager:
    """Manage exact run/worker worktrees and their shared-state ownership ledger."""

    def __init__(self, project_root: str | Path) -> None:
        self.fs = ProjectFS(Path(project_root).expanduser())
        self.root = self.fs.root
        reported = Path(
            _run_git(self.root, "rev-parse", "--show-toplevel").stdout.strip()
        )
        if reported.resolve() != self.root:
            raise WorktreeError(
                f"target must be the git repository root (git reports {reported})"
            )
        layout = detect_state_layout(self.root)
        self.registry_rel = f"{layout.state}/worktrees.json"
        self.container = self.root.parent / f".{self.root.name}.ckit-worktrees"

    def _target(self, run_id: str, worker_id: str) -> Path:
        _validate_id(run_id, "run_id")
        _validate_id(worker_id, "worker_id")
        target = self.container / run_id / worker_id
        if target.parent.parent != self.container:
            raise WorktreeError("worktree target escapes the managed container")
        return target

    def _assert_target_boundary(
        self, target: Path, *, allow_missing_target: bool
    ) -> None:
        """Refuse redirectable managed container, run, and worker components."""

        _real_directory(self.root.parent)
        _real_directory(self.container, allow_missing=allow_missing_target)
        _real_directory(target.parent, allow_missing=allow_missing_target)
        _real_directory(target, allow_missing=allow_missing_target)

    def _common_git_dir(self) -> Path:
        raw = _run_git(self.root, "rev-parse", "--git-common-dir").stdout.strip()
        common = Path(raw)
        if not common.is_absolute():
            common = self.root / common
        try:
            resolved = common.resolve(strict=True)
        except OSError as exc:
            raise WorktreeError(
                f"cannot resolve repository common gitdir: {exc}"
            ) from exc
        _real_directory(resolved)
        return resolved

    def _bound_git_marker(
        self, target: Path, record: WorktreeRecord | None
    ) -> tuple[bytes, str]:
        text = _regular_marker(target / ".git")
        if not text.endswith("\n") or text.count("\n") != 1:
            raise WorktreeError(f"owned worktree has malformed git marker: {target}")
        prefix = "gitdir: "
        if not text.startswith(prefix):
            raise WorktreeError(f"owned worktree has no valid git marker: {target}")
        raw = text[len(prefix) : -1]
        marker_path = Path(raw)
        if not marker_path.is_absolute():
            raise WorktreeError("owned worktree git marker must use a canonical path")
        try:
            canonical = marker_path.resolve(strict=True)
        except OSError as exc:
            raise WorktreeError(
                f"owned worktree gitdir cannot be resolved: {exc}"
            ) from exc
        if raw != str(canonical):
            raise WorktreeError("owned worktree git marker is not canonical")
        common = self._common_git_dir()
        try:
            common_relative = canonical.relative_to(common)
        except ValueError as exc:
            raise WorktreeError(
                "owned worktree gitdir is outside the repository"
            ) from exc
        if len(common_relative.parts) != 2 or common_relative.parts[0] != "worktrees":
            raise WorktreeError(
                "owned worktree gitdir is not a registered worktree admin dir"
            )
        _real_directory(canonical)
        stored = common_relative.as_posix()
        if record is not None:
            if not record.gitdir_path:
                raise WorktreeError(
                    "worktree ownership record lacks exact gitdir binding"
                )
            if record.gitdir_path != stored:
                raise WorktreeError(
                    "owned worktree gitdir does not match its ownership record"
                )
        return text.encode("utf-8"), stored

    def _portable_target(self, target: Path) -> str:
        return Path(os.path.relpath(target, self.root)).as_posix()

    def _read_records(self) -> list[WorktreeRecord]:
        if not self.fs.is_file(self.registry_rel):
            return []
        try:
            document = json.loads(self.fs.read_text(self.registry_rel))
        except (json.JSONDecodeError, OSError, UnicodeError) as exc:
            raise WorktreeError(f"cannot read worktree registry: {exc}") from exc
        if not isinstance(document, dict) or document.get("schema_version") != 1:
            raise WorktreeError("unsupported or malformed worktree registry")
        records = document.get("records")
        if not isinstance(records, list) or any(
            not isinstance(item, dict) for item in records
        ):
            raise WorktreeError("worktree registry records must be an array of objects")
        loaded = [WorktreeRecord.from_dict(item) for item in records]
        keys = [(record.run_id, record.worker_id) for record in loaded]
        if len(keys) != len(set(keys)):
            raise WorktreeError(
                "worktree registry contains duplicate run/worker ownership"
            )
        for record in loaded:
            expected = self._portable_target(
                self._target(record.run_id, record.worker_id)
            )
            if record.target_path != expected:
                raise WorktreeError(
                    f"worktree ownership path mismatch for {record.run_id}/{record.worker_id}"
                )
        return loaded

    def _write_records(self, records: list[WorktreeRecord]) -> None:
        document = {
            "schema_version": WORKTREE_REGISTRY_SCHEMA,
            "records": [record.to_dict() for record in records],
        }
        self.fs.write_text(
            self.registry_rel,
            json.dumps(document, indent=2, sort_keys=True) + "\n",
            mode=0o600,
        )

    def records(self, run_id: str | None = None) -> tuple[WorktreeRecord, ...]:
        records = self._read_records()
        if run_id is not None:
            _validate_id(run_id, "run_id")
            records = [record for record in records if record.run_id == run_id]
        return tuple(records)

    def create(
        self, run_id: str, worker_id: str, *, base_ref: str = "HEAD"
    ) -> WorktreeRecord:
        target = self._target(run_id, worker_id)
        if (
            not isinstance(base_ref, str)
            or not base_ref.strip()
            or base_ref.startswith("-")
        ):
            raise WorktreeError("base_ref must be a non-option git revision")
        with self.fs.mutation_lease(exclusive=True):
            self._assert_target_boundary(target, allow_missing_target=True)
            records = self._read_records()
            if any(
                record.run_id == run_id and record.worker_id == worker_id
                for record in records
            ):
                raise WorktreeError(
                    f"worktree owner already exists: {run_id}/{worker_id}"
                )
            if target.exists() or target.is_symlink():
                raise WorktreeError(f"managed worktree target already exists: {target}")
            base_commit = _run_git(
                self.root, "rev-parse", "--verify", f"{base_ref}^{{commit}}"
            ).stdout.strip()
            target.parent.mkdir(parents=True, exist_ok=True)
            self._assert_target_boundary(target, allow_missing_target=True)
            _run_git(self.root, "worktree", "add", "--detach", str(target), base_commit)
            self._assert_target_boundary(target, allow_missing_target=False)
            _, gitdir_path = self._bound_git_marker(target, None)
            now = _utc_now()
            record = WorktreeRecord(
                run_id=run_id,
                worker_id=worker_id,
                target_path=self._portable_target(target),
                base_ref=base_ref,
                base_commit=base_commit,
                gitdir_path=gitdir_path,
                status=WorktreeStatus.ACTIVE,
                created_at=now,
                updated_at=now,
            )
            try:
                self._write_records([*records, record])
            except BaseException:
                _run_git(
                    self.root,
                    "worktree",
                    "remove",
                    "--force",
                    str(target),
                    check=False,
                )
                raise
            return record

    def _replace(self, replacement: WorktreeRecord) -> None:
        records = self._read_records()
        matches = [
            index
            for index, record in enumerate(records)
            if (record.run_id, record.worker_id)
            == (replacement.run_id, replacement.worker_id)
        ]
        if len(matches) != 1:
            raise WorktreeError(
                f"worktree owner not found: {replacement.run_id}/{replacement.worker_id}"
            )
        records[matches[0]] = replacement
        self._write_records(records)

    def mark(
        self,
        run_id: str,
        worker_id: str,
        status: WorktreeStatus | str,
        *,
        failure_reason: str | None = None,
    ) -> WorktreeRecord:
        new_status = WorktreeStatus(status)
        if new_status not in {
            WorktreeStatus.SUCCEEDED,
            WorktreeStatus.FAILED,
            WorktreeStatus.ABORTED,
        }:
            raise WorktreeError("mark status must be succeeded, failed, or aborted")
        with self.fs.mutation_lease(exclusive=True):
            record = self._owned(run_id, worker_id)
            if record.status is not WorktreeStatus.ACTIVE:
                raise WorktreeError(
                    f"cannot mark worktree in status {record.status.value}"
                )
            if new_status is WorktreeStatus.FAILED and not (
                isinstance(failure_reason, str) and failure_reason.strip()
            ):
                raise WorktreeError("failed worktree requires a failure reason")
            replacement = WorktreeRecord(
                **{
                    **record.to_dict(),
                    "status": new_status,
                    "updated_at": _utc_now(),
                    "failure_reason": failure_reason.strip()
                    if failure_reason
                    else None,
                }
            )
            self._replace(replacement)
            return replacement

    def _owned(self, run_id: str, worker_id: str) -> WorktreeRecord:
        matches = [
            record
            for record in self._read_records()
            if record.run_id == run_id and record.worker_id == worker_id
        ]
        if len(matches) != 1:
            raise WorktreeError(f"worktree owner not found: {run_id}/{worker_id}")
        return matches[0]

    def _registered_paths(self) -> set[Path]:
        output = _run_git(self.root, "worktree", "list", "--porcelain").stdout
        return {
            Path(line.removeprefix("worktree ")).resolve()
            for line in output.splitlines()
            if line.startswith("worktree ")
        }

    def verify(self, run_id: str, worker_id: str) -> WorktreeRecord:
        record = self._owned(run_id, worker_id)
        if record.status is WorktreeStatus.REMOVED:
            return record
        target = self._target(run_id, worker_id)
        self._assert_target_boundary(target, allow_missing_target=False)
        resolved_target = target.resolve(strict=True)
        if resolved_target not in self._registered_paths():
            raise WorktreeError(f"owned worktree is not registered with git: {target}")
        self._bound_git_marker(target, record)
        return record

    def checkpoint(self, run_id: str, worker_id: str) -> WorkspaceCheckpoint:
        """Return a stable exact content identity for one registered worktree."""

        record = self.verify(run_id, worker_id)
        if record.status is WorktreeStatus.REMOVED:
            raise WorktreeError("cannot checkpoint a removed managed worktree")
        target = self._target(run_id, worker_id)
        marker, _ = self._bound_git_marker(target, record)
        marker_digest = hashlib.sha256(marker).hexdigest()
        first = _workspace_checkpoint_once(target, git_marker_digest=marker_digest)
        self.verify(run_id, worker_id)
        marker, _ = self._bound_git_marker(target, record)
        second = _workspace_checkpoint_once(
            target, git_marker_digest=hashlib.sha256(marker).hexdigest()
        )
        self.verify(run_id, worker_id)
        if first != second:
            raise WorktreeError(
                "managed workspace changed while its content checkpoint was captured"
            )
        return first

    def cleanup(
        self,
        run_id: str,
        worker_id: str,
        *,
        discard_changes: bool = False,
        discard_failed: bool = False,
    ) -> WorktreeRecord:
        with self.fs.mutation_lease(exclusive=True):
            record = self.verify(run_id, worker_id)
            if record.status is WorktreeStatus.REMOVED:
                return record
            if record.status is WorktreeStatus.FAILED and not discard_failed:
                raise WorktreeError(
                    "failed worker artifacts are preserved; pass discard_failed explicitly"
                )
            target = self._target(run_id, worker_id)
            dirty = bool(
                _run_git(
                    target,
                    "status",
                    "--porcelain=v1",
                    "--untracked-files=all",
                    "--ignored=matching",
                ).stdout.strip()
            )
            current_head = _run_git(
                target, "rev-parse", "--verify", "HEAD^{commit}"
            ).stdout.strip()
            committed_changes = current_head != record.base_commit
            if (dirty or committed_changes) and not discard_changes:
                kind = (
                    "committed or uncommitted" if committed_changes else "uncommitted"
                )
                raise WorktreeError(
                    f"worktree has {kind} artifacts; pass discard_changes explicitly"
                )
            args = ["worktree", "remove"]
            if discard_changes:
                args.append("--force")
            args.append(str(target))
            _run_git(self.root, *args)
            now = _utc_now()
            replacement = WorktreeRecord(
                **{
                    **record.to_dict(),
                    "status": WorktreeStatus.REMOVED,
                    "updated_at": now,
                    "removed_at": now,
                }
            )
            self._replace(replacement)
            return replacement

    def abort_run(self, run_id: str) -> tuple[WorktreeRecord, ...]:
        """Mark active workers aborted while preserving every worktree for diagnosis/resume."""

        _validate_id(run_id, "run_id")
        with self.fs.mutation_lease(exclusive=True):
            records = self._read_records()
            now = _utc_now()
            updated: list[WorktreeRecord] = []
            for record in records:
                if record.run_id == run_id and record.status is WorktreeStatus.ACTIVE:
                    record = WorktreeRecord(
                        **{
                            **record.to_dict(),
                            "status": WorktreeStatus.ABORTED,
                            "updated_at": now,
                        }
                    )
                updated.append(record)
            self._write_records(updated)
            return tuple(record for record in updated if record.run_id == run_id)

    def resume_run(self, run_id: str) -> tuple[WorktreeRecord, ...]:
        """Verify that every preserved non-removed worker still has exact ownership."""

        records = self.records(run_id)
        for record in records:
            if record.status is not WorktreeStatus.REMOVED:
                self.verify(record.run_id, record.worker_id)
        return records


__all__ = [
    "WORKTREE_REGISTRY_SCHEMA",
    "WorktreeError",
    "WorktreeManager",
    "WorktreeRecord",
    "WorktreeStatus",
    "WorkspaceCheckpoint",
]
