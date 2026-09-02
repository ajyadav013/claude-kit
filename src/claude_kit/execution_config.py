"""Transactional access to project-scoped maker/reviewer defaults."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from claude_kit import __version__
from claude_kit.models import ExecutionPolicy, InitOptions, StateLayout
from claude_kit.secure_fs import ProjectFS, ProjectTransaction, UnsafePathError


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
        _document, options = _load_document(ProjectFS(Path(target).expanduser()))
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
    normalized = options.to_dict()
    normalized["execution"] = policy.to_dict() if policy is not None else None
    merged = {**document, **normalized}
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
        protected_paths=(StateLayout.neutral().root,),
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
