"""Transactional access to project-scoped maker/reviewer defaults."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from claude_kit import __version__
from claude_kit.models import ExecutionPolicy, InitOptions, StateLayout
from claude_kit.secure_fs import (
    ProjectFS,
    ProjectTransaction,
    UnsafePathError,
    inspect_interrupted_transaction,
    recover_interrupted_transaction,
)


class ExecutionConfigError(RuntimeError):
    """A maker/reviewer policy cannot be read or changed safely."""


def _load_document(fs: ProjectFS) -> tuple[dict[str, Any], InitOptions]:
    manifest = StateLayout.neutral().manifest
    if not fs.is_file(manifest):
        raise ExecutionConfigError(
            "maker-checker configuration requires a runtime-aware install with "
            "neutral .ckit state"
        )
    try:
        document = json.loads(fs.read_text(manifest))
        if not isinstance(document, dict):
            raise ValueError("document root must be an object")
        options = InitOptions.from_dict(document)
    except (json.JSONDecodeError, OSError, TypeError, UnicodeError, ValueError) as exc:
        raise ExecutionConfigError(
            f"native init-options manifest is corrupt: {exc}"
        ) from exc
    if options.state_layout != StateLayout.neutral():
        raise ExecutionConfigError(
            "maker-checker configuration requires a runtime-aware install with "
            "neutral .ckit state"
        )
    return document, options


def load_execution_policy(target: str | Path) -> ExecutionPolicy | None:
    """Return the configured project policy without mutating the installation."""

    try:
        fs = ProjectFS(Path(target).expanduser())
        if not fs.root.exists():
            _document, options = _load_document(fs)
            return options.execution_policy
        # A shared lease makes the manifest and lifecycle marker one coherent
        # read. Read-only configuration inspection never performs recovery.
        with fs.mutation_lease(exclusive=False):
            if inspect_interrupted_transaction(fs) is not None:
                raise ExecutionConfigError(
                    "cannot read maker-checker configuration while an interrupted "
                    "project transaction requires recovery"
                )
            _document, options = _load_document(fs)
    except (OSError, UnsafePathError) as exc:
        raise ExecutionConfigError(
            f"cannot read maker-checker configuration: {exc}"
        ) from exc
    return options.execution_policy


def _write_policy(
    fs: ProjectFS,
    document: dict[str, Any],
    options: InitOptions,
    policy: ExecutionPolicy | None,
) -> None:
    """Rewrite only the shared manifest while preserving unknown current keys."""

    if policy is not None:
        policy.validate_providers(options.runtimes)
    # This command owns only the execution binding. Keep every other byte-level
    # structure represented by the parsed document, including forward-compatible
    # keys inside known containers such as ``selection`` and ``state_layout``.
    merged = {
        **document,
        "execution": policy.to_dict() if policy is not None else None,
    }
    # Validate the exact bytes before a rollback-capable mutation begins.
    InitOptions.from_dict(merged)
    encoded = json.dumps(merged, indent=2) + "\n"
    manifest = StateLayout.neutral().manifest
    with ProjectTransaction(
        fs,
        operation="upgrade",
        from_version=options.claude_kit_version,
        to_version=__version__,
        actions=[{"rel": manifest, "kind": "update", "owner": "kit"}],
        # Configuration owns only this directory. Snapshotting all of .ckit
        # would let a later config rollback erase pipeline evidence appended by
        # a concurrently active, already-frozen managed run.
        protected_paths=(f"{StateLayout.neutral().root}/config",),
        journal_path=StateLayout.neutral().journal,
    ):
        fs.write_text(manifest, encoded)
        # Do not commit a document that the runtime itself cannot reload.
        InitOptions.from_dict(json.loads(fs.read_text(manifest)))


def configure_execution_policy(
    target: str | Path, policy: ExecutionPolicy
) -> ExecutionPolicy:
    """Atomically set defaults used by future maker-checker runs."""

    if not isinstance(policy, ExecutionPolicy):
        raise ValueError("policy must be an ExecutionPolicy")
    try:
        fs = ProjectFS(Path(target).expanduser())
        # Runtime transitions and upgrades mutate the same manifest. Hold one
        # project-wide lease from the authoritative read through verification so
        # configuration cannot restore a stale runtime or file inventory.
        with fs.mutation_lease(exclusive=True):
            recover_interrupted_transaction(fs, preserve_root=True)
            if inspect_interrupted_transaction(fs) is not None:
                raise ExecutionConfigError(
                    "cannot configure maker-checker while an unsupported project "
                    "transaction requires lifecycle recovery"
                )
            document, options = _load_document(fs)
            _write_policy(fs, document, options, policy)
    except ExecutionConfigError:
        raise
    except (OSError, UnsafePathError, TypeError, ValueError) as exc:
        raise ExecutionConfigError(f"cannot configure maker-checker: {exc}") from exc
    return policy


def disable_execution_policy(target: str | Path) -> bool:
    """Atomically disable the pair, returning whether a policy changed."""

    try:
        fs = ProjectFS(Path(target).expanduser())
        with fs.mutation_lease(exclusive=True):
            recover_interrupted_transaction(fs, preserve_root=True)
            if inspect_interrupted_transaction(fs) is not None:
                raise ExecutionConfigError(
                    "cannot disable maker-checker while an unsupported project "
                    "transaction requires lifecycle recovery"
                )
            document, options = _load_document(fs)
            if options.execution_policy is None:
                return False
            _write_policy(fs, document, options, None)
    except ExecutionConfigError:
        raise
    except (OSError, UnsafePathError, TypeError, ValueError) as exc:
        raise ExecutionConfigError(f"cannot disable maker-checker: {exc}") from exc
    return True


__all__ = [
    "ExecutionConfigError",
    "configure_execution_policy",
    "disable_execution_policy",
    "load_execution_policy",
]
