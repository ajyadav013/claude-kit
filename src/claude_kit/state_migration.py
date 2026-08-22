"""Transactional migration from Claude-hosted state to the neutral control plane.

The compatibility window is deliberately non-destructive: mutable kit state is
copied from ``.claude`` to ``.ckit`` and the legacy bytes remain available for
older releases and diagnostics.  Once the neutral manifest exists it is the
single authority; Claude's native discovery payload remains under ``.claude``.

Migration has two validation passes.  A read-only pass reports ordinary
destination conflicts without touching the project.  The same inventory is
rebuilt while :class:`~claude_kit.secure_fs.ProjectTransaction` holds the
project mutation lease, closing the check/use race and providing crash-safe
rollback across both state roots.
"""

from __future__ import annotations

import json
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from claude_kit.models import (
    INIT_OPTIONS_SCHEMA,
    FileRecord,
    InitOptions,
    StateLayout,
)
from claude_kit.secure_fs import (
    ProjectFS,
    ProjectTransaction,
    UnsafePathError,
    recover_interrupted_transaction,
)

_LEGACY = StateLayout.legacy_claude()
_NEUTRAL = StateLayout.neutral()

# ``config`` is copied as a tree so unknown, user-maintained state is retained.
# The upgrade journal is transient transaction machinery, never migrated as
# durable state.  The other roots are the complete mutable StateLayout surface.
_TREE_MAPPINGS = (
    (f"{_LEGACY.root}/config", f"{_NEUTRAL.root}/config"),
    (_LEGACY.memory, _NEUTRAL.memory),
    (_LEGACY.artifacts, _NEUTRAL.artifacts),
    (_LEGACY.state, _NEUTRAL.state),
    (_LEGACY.temporary, _NEUTRAL.temporary),
)
_FILE_MAPPINGS = ((_LEGACY.continuity, _NEUTRAL.continuity),)
_TRANSIENT_SOURCES = frozenset({_LEGACY.journal})

# Protect only mutable Claude paths, not the potentially large native discovery
# tree.  The neutral root contains the journal and every migration destination.
_TRANSACTION_PATHS = (
    _NEUTRAL.root,
    f"{_LEGACY.root}/config",
    _LEGACY.continuity,
    _LEGACY.memory,
    _LEGACY.artifacts,
    _LEGACY.state,
    _LEGACY.temporary,
)


class StateMigrationError(RuntimeError):
    """Base error for a legacy-state migration that made no committed change."""


class StateMigrationConflictError(StateMigrationError):
    """Raised when neutral state already contains incompatible bytes or types."""

    def __init__(self, conflicts: tuple[str, ...]) -> None:
        self.conflicts = conflicts
        super().__init__(
            "legacy state migration conflicts with existing neutral state: "
            + ", ".join(conflicts)
        )


@dataclass(frozen=True)
class StateMigrationResult:
    """Outcome of one explicit migration attempt."""

    migrated: bool
    recovered: bool = False
    already_neutral: bool = False
    copied_paths: tuple[str, ...] = ()
    created_directories: tuple[str, ...] = ()


@dataclass(frozen=True)
class _FileEntry:
    source: str
    destination: str
    content: bytes
    mode: int


@dataclass(frozen=True)
class _MigrationPlan:
    source_present: bool
    files: tuple[_FileEntry, ...]
    directories: tuple[str, ...]
    pending_files: tuple[_FileEntry, ...]
    pending_directories: tuple[str, ...]

    @property
    def has_changes(self) -> bool:
        return bool(self.pending_files or self.pending_directories)


def _mapped_state_path(path: str) -> str:
    """Map one tracked legacy-state path while leaving Claude payload paths intact."""

    if path in _TRANSIENT_SOURCES:
        return path
    for source, destination in (*_TREE_MAPPINGS, *_FILE_MAPPINGS):
        if path == source:
            return destination
        prefix = source + "/"
        if path.startswith(prefix):
            return destination + path[len(source) :]
    return path


def _migrated_manifest(content: bytes) -> bytes:
    """Upgrade manifest metadata while retaining the user's selection and checksums."""

    try:
        document = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StateMigrationError(
            f"legacy init-options manifest is unreadable: {exc}"
        ) from exc
    if not isinstance(document, dict):
        raise StateMigrationError("legacy init-options manifest must be a JSON object")
    try:
        options = InitOptions.from_dict(document)
    except (TypeError, ValueError) as exc:
        raise StateMigrationError(
            f"legacy init-options manifest is invalid: {exc}"
        ) from exc

    migrated_records: list[dict[str, str]] = []
    for record in options.files:
        destination = _mapped_state_path(record.path)
        provider = "shared" if destination != record.path else record.provider
        component_id = record.component_id
        if component_id == f"legacy-file://{record.path}":
            component_id = f"legacy-file://{destination}"
        migrated_records.append(
            FileRecord(
                path=destination,
                sha256=record.sha256,
                owner=record.owner,
                provider=provider,
                component_id=component_id,
            ).to_dict()
        )

    # Preserve unknown top-level metadata and the user's selection verbatim. Only
    # the runtime-neutral schema seam and canonicalized file records are replaced.
    migrated = dict(document)
    migrated.update(
        {
            "schema_version": INIT_OPTIONS_SCHEMA,
            "files": migrated_records,
            "runtimes": list(options.runtimes),
            "state_layout": _NEUTRAL.to_dict(),
            "rendering_version": options.rendering_version,
            "compatibility_catalog_versions": dict(
                options.compatibility_catalog_versions
            ),
        }
    )
    try:
        InitOptions.from_dict(migrated)
    except (TypeError, ValueError) as exc:  # pragma: no cover - defensive invariant
        raise StateMigrationError(
            f"migrated init-options manifest would be invalid: {exc}"
        ) from exc
    return (json.dumps(migrated, indent=2) + "\n").encode("utf-8")


def _add_directory_with_parents(directories: set[str], directory: str) -> None:
    current = PurePosixPath(directory)
    while current.as_posix() not in {".", ""}:
        directories.add(current.as_posix())
        current = current.parent


def _add_file_parents(directories: set[str], destination: str) -> None:
    _add_directory_with_parents(
        directories, PurePosixPath(destination).parent.as_posix()
    )


def _file_entry(fs: ProjectFS, source: str, destination: str) -> _FileEntry:
    content = fs.read_bytes(source)
    if source == _LEGACY.manifest:
        content = _migrated_manifest(content)
    mode = stat.S_IMODE(fs.stat(source).st_mode)
    return _FileEntry(
        source=source,
        destination=destination,
        content=content,
        mode=mode,
    )


def _collect_source(
    fs: ProjectFS,
) -> tuple[bool, tuple[_FileEntry, ...], tuple[str, ...]]:
    files: list[_FileEntry] = []
    directories: set[str] = set()
    source_present = False

    for source_root, destination_root in _TREE_MAPPINGS:
        source = fs.assert_tree_safe(source_root)
        if not source.exists():
            continue
        source_present = True
        if not source.is_dir():
            raise UnsafePathError(
                f"legacy state source must be a directory: {source_root}"
            )
        _add_directory_with_parents(directories, destination_root)
        for path in sorted(source.rglob("*")):
            source_rel = path.relative_to(fs.root).as_posix()
            if source_rel in _TRANSIENT_SOURCES:
                continue
            checked = fs.assert_tree_safe(source_rel)
            destination = _mapped_state_path(source_rel)
            if checked.is_dir():
                _add_directory_with_parents(directories, destination)
            elif checked.is_file():
                _add_file_parents(directories, destination)
                files.append(_file_entry(fs, source_rel, destination))
            else:  # ``assert_tree_safe`` already rejects special entries.
                raise UnsafePathError(
                    f"legacy state source must be a regular file or directory: {source_rel}"
                )

    for source_rel, destination in _FILE_MAPPINGS:
        source = fs.assert_tree_safe(source_rel)
        if not source.exists():
            continue
        source_present = True
        if not source.is_file():
            raise UnsafePathError(f"legacy state source must be a file: {source_rel}")
        _add_file_parents(directories, destination)
        files.append(_file_entry(fs, source_rel, destination))

    files.sort(
        key=lambda entry: (entry.destination == _NEUTRAL.manifest, entry.destination)
    )
    ordered_directories = tuple(
        sorted(directories, key=lambda rel: (len(PurePosixPath(rel).parts), rel))
    )
    return source_present, tuple(files), ordered_directories


def _build_plan(fs: ProjectFS) -> _MigrationPlan:
    source_present, files, directories = _collect_source(fs)
    if fs.exists(_NEUTRAL.root):
        fs.assert_tree_safe(_NEUTRAL.root)

    conflicts: list[str] = []
    pending_directories: list[str] = []
    blocked_directories: list[str] = []
    for destination in directories:
        if any(
            destination.startswith(blocked + "/") for blocked in blocked_directories
        ):
            continue
        if not fs.exists(destination):
            pending_directories.append(destination)
            continue
        if not fs.is_dir(destination):
            conflicts.append(destination)
            blocked_directories.append(destination)

    pending_files: list[_FileEntry] = []
    for entry in files:
        if any(
            entry.destination.startswith(blocked + "/")
            for blocked in blocked_directories
        ):
            continue
        if not fs.exists(entry.destination):
            pending_files.append(entry)
            continue
        if not fs.is_file(entry.destination):
            conflicts.append(entry.destination)
            continue
        if fs.read_bytes(entry.destination) != entry.content:
            conflicts.append(entry.destination)

    if conflicts:
        raise StateMigrationConflictError(tuple(sorted(set(conflicts))))
    return _MigrationPlan(
        source_present=source_present,
        files=files,
        directories=directories,
        pending_files=tuple(pending_files),
        pending_directories=tuple(pending_directories),
    )


def _neutral_manifest_is_current(fs: ProjectFS) -> bool:
    if not fs.is_file(_NEUTRAL.manifest):
        return False
    try:
        document = json.loads(fs.read_text(_NEUTRAL.manifest))
        if not isinstance(document, dict):
            return False
        return InitOptions.from_dict(document).state_layout == _NEUTRAL
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        return False


def _before_copy(_fs: ProjectFS, _source: str, _destination: str) -> None:
    """Test seam immediately before one migration file is materialized."""


def _apply_plan(
    fs: ProjectFS, plan: _MigrationPlan
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    created_directories: list[str] = []
    copied: list[str] = []
    for destination in plan.pending_directories:
        if fs.exists(destination):
            if not fs.is_dir(destination):
                raise StateMigrationConflictError((destination,))
            continue
        fs.mkdir(destination)
        created_directories.append(destination)

    for entry in plan.pending_files:
        current = fs.read_bytes(entry.source)
        if entry.source == _LEGACY.manifest:
            current = _migrated_manifest(current)
        if current != entry.content:
            raise StateMigrationError(
                f"legacy state changed while migration was applying: {entry.source}"
            )
        _before_copy(fs, entry.source, entry.destination)
        if fs.exists(entry.destination):
            if (
                fs.is_file(entry.destination)
                and fs.read_bytes(entry.destination) == entry.content
            ):
                continue
            raise StateMigrationConflictError((entry.destination,))
        fs.write_bytes(entry.destination, entry.content, mode=entry.mode)
        if fs.read_bytes(entry.destination) != entry.content:
            raise StateMigrationError(
                f"neutral state verification failed after copying {entry.destination}"
            )
        copied.append(entry.destination)
    return tuple(copied), tuple(created_directories)


def migrate_legacy_state(target: str | Path) -> StateMigrationResult:
    """Copy legacy mutable state into ``.ckit`` transactionally and convergently.

    A valid neutral manifest is the durable completion marker.  Re-running after
    success therefore never compares or overwrites newer neutral user edits.
    Ordinary conflicts are discovered by a read-only pass before transaction
    setup, so the project is byte-for-byte unchanged when this function refuses
    a partial or independently-created destination.
    """

    fs = ProjectFS(Path(target).expanduser())
    recovered = recover_interrupted_transaction(fs, preserve_root=True)
    if not fs.root.exists():
        return StateMigrationResult(migrated=False, recovered=recovered)
    if _neutral_manifest_is_current(fs):
        return StateMigrationResult(
            migrated=False,
            recovered=recovered,
            already_neutral=True,
        )

    preliminary = _build_plan(fs)
    if not preliminary.source_present or not preliminary.has_changes:
        return StateMigrationResult(migrated=False, recovered=recovered)

    actions = [
        {"rel": entry.destination, "kind": "state-migrate", "owner": "shared"}
        for entry in preliminary.pending_files
    ]
    with ProjectTransaction(
        fs,
        operation="upgrade",
        actions=actions,
        protected_paths=_TRANSACTION_PATHS,
        journal_path=_NEUTRAL.journal,
    ):
        # Recompute after the transaction acquired its exclusive mutation lease.
        # The journal is an allowed extra destination and is never copied.
        plan = _build_plan(fs)
        if not plan.source_present:
            raise StateMigrationError(
                "legacy state disappeared while migration was acquiring its lock"
            )
        copied, created = _apply_plan(fs, plan)

    return StateMigrationResult(
        migrated=bool(copied or created),
        recovered=recovered,
        copied_paths=copied,
        created_directories=created,
    )


__all__ = [
    "StateMigrationConflictError",
    "StateMigrationError",
    "StateMigrationResult",
    "migrate_legacy_state",
]
