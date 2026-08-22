"""Origin-bound authorization for managed external actions.

This module is deliberately independent from the pipeline snapshot and native worker
adapters.  It defines the trust-boundary contract that those layers can integrate:

* an immutable, canonical request binds the complete managed execution origin and one
  typed action;
* a detached asymmetric signature is accepted only through a host-injected verifier and
  a signer policy whose source is outside the managed project;
* every transition compares the caller's exact current scope/action with the signed
  request; and
* a compare-and-swap store moves a request through the one-shot lifecycle
  ``pending -> authorized -> consuming -> consumed|indeterminate``.

The module intentionally contains no private-key handling, shared-secret/HMAC approval,
generic command action, credential transport, or external-effect implementation.  A
coordinator may hand a :class:`BrokerExecutionPermit` to a typed broker only *after* the
``consuming`` state has been durably committed.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path, PureWindowsPath
from typing import Any, Mapping, Optional, Protocol, runtime_checkable
from urllib.parse import urlsplit

REQUEST_DOMAIN = "claude-kit.managed-approval.request.v1"
ACTION_DOMAIN = "claude-kit.managed-approval.action.v1"
AUTHORIZATION_DOMAIN = "claude-kit.managed-approval.authorization.v1"
ENVELOPE_DOMAIN = "claude-kit.managed-approval.envelope.v1"
CONSUMPTION_DOMAIN = "claude-kit.managed-approval.consumption.v1"
PREFLIGHT_DOMAIN = "claude-kit.managed-approval.broker-preflight.v1"
APPROVAL_SCHEMA_VERSION = 1
BROKER_PREFLIGHT_MAX_AGE_SECONDS = 60

PULL_REQUEST_CREATE = "repository.pull-request.create"
APPROVAL_MARKER_PREFIX = "ckit-managed-approval:"

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_BASE64URL_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_CANONICAL_TIMESTAMP_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z$"
)
_GIT_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/@+-]*$")
_REPOSITORY_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
_ARTIFACT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")
_ASYMMETRIC_ALGORITHMS = frozenset(
    {
        "ed25519",
        "ecdsa-p256-sha256",
        "rsa-pss-sha256",
        "ssh-ed25519",
    }
)


class ManagedApprovalError(ValueError):
    """Base class for fail-closed managed-approval failures."""


class ApprovalValidationError(ManagedApprovalError):
    """An approval document or typed action is malformed."""


class ApprovalDriftError(ManagedApprovalError):
    """The current execution origin or action differs from the signed request."""


class ApprovalExpiredError(ManagedApprovalError):
    """The request or authorization is not currently valid."""


class ApprovalPolicyError(ManagedApprovalError):
    """The external signer policy does not authorize the envelope."""


class ApprovalSignatureError(ManagedApprovalError):
    """The detached asymmetric signature could not be verified."""


class ApprovalStateError(ManagedApprovalError):
    """A requested lifecycle transition is not legal from the current state."""


class ApprovalConflictError(ManagedApprovalError):
    """A compare-and-swap failed because another coordinator changed the record."""


class ApprovalNotFoundError(ManagedApprovalError):
    """The requested approval record does not exist."""


def _required_text(value: object, field_name: str, *, max_bytes: int = 4096) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ApprovalValidationError(f"{field_name} must be a non-empty string")
    if value != value.strip():
        raise ApprovalValidationError(
            f"{field_name} must not contain leading or trailing whitespace"
        )
    text = value
    if len(text.encode("utf-8")) > max_bytes:
        raise ApprovalValidationError(f"{field_name} exceeds {max_bytes} UTF-8 bytes")
    if any(ord(character) < 32 for character in text):
        raise ApprovalValidationError(
            f"{field_name} must not contain control characters"
        )
    return text


def _identifier(value: object, field_name: str) -> str:
    text = _required_text(value, field_name, max_bytes=256)
    if not _IDENTIFIER_RE.fullmatch(text) or ".." in text:
        raise ApprovalValidationError(
            f"{field_name} must use letters, digits, dots, underscores, or hyphens"
        )
    return text


def _digest(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise ApprovalValidationError(
            f"{field_name} must be 64 lowercase hexadecimal characters"
        )
    return value


def _commit(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not _COMMIT_RE.fullmatch(value):
        raise ApprovalValidationError(
            f"{field_name} must be a 40- or 64-character commit id"
        )
    return value


def _positive_integer(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ApprovalValidationError(f"{field_name} must be a positive integer")
    return value


def _utc_datetime(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ApprovalValidationError(f"{field_name} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _timestamp_text(value: datetime) -> str:
    normalized = _utc_datetime(value, "timestamp")
    return normalized.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_timestamp(value: object, field_name: str) -> datetime:
    if not isinstance(value, str) or not _CANONICAL_TIMESTAMP_RE.fullmatch(value):
        raise ApprovalValidationError(
            f"{field_name} must be a canonical UTC RFC 3339 timestamp"
        )
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ApprovalValidationError(
            f"{field_name} must be a canonical UTC RFC 3339 timestamp"
        ) from exc
    normalized = _utc_datetime(parsed, field_name)
    if _timestamp_text(normalized) != value:
        raise ApprovalValidationError(
            f"{field_name} must be a canonical UTC RFC 3339 timestamp"
        )
    return normalized


def _validate_json_value(value: object, path: str = "$") -> None:
    """Reject non-portable JSON values before canonicalization.

    Floats are excluded deliberately: NaN/Infinity and cross-language number rendering
    must never affect an authorization signature.
    """

    if value is None or isinstance(value, (str, bool)):
        return
    if isinstance(value, int):
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_value(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ApprovalValidationError(
                    f"{path} contains a non-string object key"
                )
            _validate_json_value(item, f"{path}.{key}")
        return
    raise ApprovalValidationError(
        f"{path} contains unsupported JSON value {type(value).__name__}"
    )


def canonical_json_bytes(document: Mapping[str, Any]) -> bytes:
    """Return the package's canonical UTF-8 JSON representation.

    Documents produced by this module use only strings, booleans, integers, null,
    arrays, and string-keyed objects. Object keys are sorted; insignificant whitespace
    and ASCII escaping are disabled. This is intentionally narrower than arbitrary JSON.
    """

    materialized = dict(document)
    _validate_json_value(materialized)
    return json.dumps(
        materialized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def domain_separated_bytes(domain: str, document: Mapping[str, Any]) -> bytes:
    """Length-frame one canonical document under an unambiguous signing domain."""

    try:
        domain_bytes = _required_text(domain, "domain", max_bytes=256).encode("ascii")
    except UnicodeEncodeError as exc:
        raise ApprovalValidationError(
            "domain must contain ASCII characters only"
        ) from exc
    payload = canonical_json_bytes(document)
    return (
        b"CKIT-MANAGED-APPROVAL\0"
        + len(domain_bytes).to_bytes(4, "big")
        + domain_bytes
        + len(payload).to_bytes(8, "big")
        + payload
    )


def _document_digest(domain: str, document: Mapping[str, Any]) -> str:
    return hashlib.sha256(domain_separated_bytes(domain, document)).hexdigest()


def _exact_keys(
    document: Mapping[str, Any],
    *,
    required: set[str],
    optional: Optional[set[str]] = None,
) -> None:
    optional = optional or set()
    missing = required - set(document)
    extra = set(document) - required - optional
    if missing:
        raise ApprovalValidationError(
            "document is missing fields: " + ", ".join(sorted(missing))
        )
    if extra:
        raise ApprovalValidationError(
            "document has unknown fields: " + ", ".join(sorted(extra))
        )


def _mapping(value: object, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ApprovalValidationError(f"{field_name} must be an object")
    if any(not isinstance(key, str) for key in value):
        raise ApprovalValidationError(f"{field_name} must have string keys")
    return value


def _relative_target_path(value: object) -> str:
    text = _required_text(value, "workspace.target_path", max_bytes=4096)
    if (
        Path(text).is_absolute()
        or PureWindowsPath(text).is_absolute()
        or _WINDOWS_DRIVE_RE.match(text)
        or "\\" in text
    ):
        raise ApprovalValidationError(
            "workspace.target_path must be a relative POSIX path"
        )
    return text


def _git_ref(value: object, field_name: str) -> str:
    text = _required_text(value, field_name, max_bytes=1024)
    forbidden = (
        not _GIT_REF_RE.fullmatch(text)
        or text.endswith(("/", ".", ".lock"))
        or ".." in text
        or "@{" in text
        or "//" in text
    )
    if forbidden:
        raise ApprovalValidationError(
            f"{field_name} must be a safe, fully specified git ref"
        )
    return text


def _repository_id(value: object, field_name: str) -> str:
    text = _required_text(value, field_name, max_bytes=1024)
    if not _REPOSITORY_ID_RE.fullmatch(text) or any(
        part in {"", ".", ".."} for part in text.split("/")
    ):
        raise ApprovalValidationError(
            f"{field_name} must be a canonical credential-free repository id"
        )
    return text


def _artifact_id(value: object) -> str:
    text = _required_text(value, "artifact_id", max_bytes=1024)
    if (
        not _ARTIFACT_ID_RE.fullmatch(text)
        or Path(text).is_absolute()
        or PureWindowsPath(text).is_absolute()
        or _WINDOWS_DRIVE_RE.match(text)
        or any(part in {"", ".", ".."} for part in text.split("/"))
    ):
        raise ApprovalValidationError(
            "artifact_id must be a contained relative POSIX logical path"
        )
    return text


@dataclass(frozen=True)
class WorkspaceCheckpointBinding:
    """Exact content identity of the managed workspace at authorization time."""

    head_commit: str
    tracked_digest: str
    untracked_digest: str
    content_digest: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ApprovalValidationError(
                "workspace checkpoint schema_version must be 1"
            )
        object.__setattr__(
            self, "head_commit", _commit(self.head_commit, "checkpoint.head_commit")
        )
        for field_name in ("tracked_digest", "untracked_digest", "content_digest"):
            object.__setattr__(
                self,
                field_name,
                _digest(getattr(self, field_name), f"checkpoint.{field_name}"),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "head_commit": self.head_commit,
            "tracked_digest": self.tracked_digest,
            "untracked_digest": self.untracked_digest,
            "content_digest": self.content_digest,
        }

    @classmethod
    def from_dict(cls, document: Mapping[str, Any]) -> WorkspaceCheckpointBinding:
        raw = _mapping(document, "checkpoint")
        _exact_keys(
            raw,
            required={
                "schema_version",
                "head_commit",
                "tracked_digest",
                "untracked_digest",
                "content_digest",
            },
        )
        return cls(
            schema_version=raw["schema_version"],
            head_commit=raw["head_commit"],
            tracked_digest=raw["tracked_digest"],
            untracked_digest=raw["untracked_digest"],
            content_digest=raw["content_digest"],
        )


@dataclass(frozen=True)
class ManagedWorkspaceBinding:
    """Ownership and control-surface binding for one run-owned workspace."""

    owner: str
    worker_id: str
    target_path: str
    base_commit: str
    provider_control_surface_digest: str
    checkpoint: WorkspaceCheckpointBinding

    def __post_init__(self) -> None:
        object.__setattr__(self, "owner", _identifier(self.owner, "workspace.owner"))
        object.__setattr__(
            self, "worker_id", _identifier(self.worker_id, "workspace.worker_id")
        )
        object.__setattr__(self, "target_path", _relative_target_path(self.target_path))
        object.__setattr__(
            self, "base_commit", _commit(self.base_commit, "workspace.base_commit")
        )
        object.__setattr__(
            self,
            "provider_control_surface_digest",
            _digest(
                self.provider_control_surface_digest,
                "workspace.provider_control_surface_digest",
            ),
        )
        if not isinstance(self.checkpoint, WorkspaceCheckpointBinding):
            raise ApprovalValidationError("workspace.checkpoint has the wrong type")

    def to_dict(self) -> dict[str, Any]:
        return {
            "owner": self.owner,
            "worker_id": self.worker_id,
            "target_path": self.target_path,
            "base_commit": self.base_commit,
            "provider_control_surface_digest": self.provider_control_surface_digest,
            "checkpoint": self.checkpoint.to_dict(),
        }

    @classmethod
    def from_dict(cls, document: Mapping[str, Any]) -> ManagedWorkspaceBinding:
        raw = _mapping(document, "workspace")
        _exact_keys(
            raw,
            required={
                "owner",
                "worker_id",
                "target_path",
                "base_commit",
                "provider_control_surface_digest",
                "checkpoint",
            },
        )
        return cls(
            owner=raw["owner"],
            worker_id=raw["worker_id"],
            target_path=raw["target_path"],
            base_commit=raw["base_commit"],
            provider_control_surface_digest=raw["provider_control_surface_digest"],
            checkpoint=WorkspaceCheckpointBinding.from_dict(
                _mapping(raw["checkpoint"], "workspace.checkpoint")
            ),
        )


@dataclass(frozen=True)
class RepositoryBinding:
    """Repository identity at the human-stop origin."""

    repository: str
    branch: str
    commit: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "repository",
            _repository_id(self.repository, "repository.repository"),
        )
        object.__setattr__(self, "branch", _git_ref(self.branch, "repository.branch"))
        object.__setattr__(self, "commit", _commit(self.commit, "repository.commit"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "repository": self.repository,
            "branch": self.branch,
            "commit": self.commit,
        }

    @classmethod
    def from_dict(cls, document: Mapping[str, Any]) -> RepositoryBinding:
        raw = _mapping(document, "repository")
        _exact_keys(raw, required={"repository", "branch", "commit"})
        return cls(
            repository=raw["repository"], branch=raw["branch"], commit=raw["commit"]
        )


@dataclass(frozen=True)
class ManagedApprovalScope:
    """Complete managed origin that an authorization cannot escape."""

    run_id: str
    stop_id: str
    workflow_id: str
    workflow_schema_version: int
    workflow_definition_digest: str
    gate_definition_digest: str
    stage_id: str
    stage_attempt: int
    dispatch_id: str
    dispatch_attempt: int
    provider: str
    route: str
    role: str
    repository: RepositoryBinding
    workspace: ManagedWorkspaceBinding

    def __post_init__(self) -> None:
        for field_name in (
            "run_id",
            "stop_id",
            "workflow_id",
            "stage_id",
            "dispatch_id",
            "provider",
            "route",
            "role",
        ):
            object.__setattr__(
                self, field_name, _identifier(getattr(self, field_name), field_name)
            )
        object.__setattr__(
            self,
            "workflow_schema_version",
            _positive_integer(self.workflow_schema_version, "workflow_schema_version"),
        )
        object.__setattr__(
            self,
            "stage_attempt",
            _positive_integer(self.stage_attempt, "stage_attempt"),
        )
        object.__setattr__(
            self,
            "dispatch_attempt",
            _positive_integer(self.dispatch_attempt, "dispatch_attempt"),
        )
        for field_name in ("workflow_definition_digest", "gate_definition_digest"):
            object.__setattr__(
                self, field_name, _digest(getattr(self, field_name), field_name)
            )
        if not isinstance(self.repository, RepositoryBinding):
            raise ApprovalValidationError("repository has the wrong type")
        if not isinstance(self.workspace, ManagedWorkspaceBinding):
            raise ApprovalValidationError("workspace has the wrong type")

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "stop_id": self.stop_id,
            "workflow_id": self.workflow_id,
            "workflow_schema_version": self.workflow_schema_version,
            "workflow_definition_digest": self.workflow_definition_digest,
            "gate_definition_digest": self.gate_definition_digest,
            "stage_id": self.stage_id,
            "stage_attempt": self.stage_attempt,
            "dispatch_id": self.dispatch_id,
            "dispatch_attempt": self.dispatch_attempt,
            "provider": self.provider,
            "route": self.route,
            "role": self.role,
            "repository": self.repository.to_dict(),
            "workspace": self.workspace.to_dict(),
        }

    @classmethod
    def from_dict(cls, document: Mapping[str, Any]) -> ManagedApprovalScope:
        raw = _mapping(document, "scope")
        required = {
            "run_id",
            "stop_id",
            "workflow_id",
            "workflow_schema_version",
            "workflow_definition_digest",
            "gate_definition_digest",
            "stage_id",
            "stage_attempt",
            "dispatch_id",
            "dispatch_attempt",
            "provider",
            "route",
            "role",
            "repository",
            "workspace",
        }
        _exact_keys(raw, required=required)
        return cls(
            run_id=raw["run_id"],
            stop_id=raw["stop_id"],
            workflow_id=raw["workflow_id"],
            workflow_schema_version=raw["workflow_schema_version"],
            workflow_definition_digest=raw["workflow_definition_digest"],
            gate_definition_digest=raw["gate_definition_digest"],
            stage_id=raw["stage_id"],
            stage_attempt=raw["stage_attempt"],
            dispatch_id=raw["dispatch_id"],
            dispatch_attempt=raw["dispatch_attempt"],
            provider=raw["provider"],
            route=raw["route"],
            role=raw["role"],
            repository=RepositoryBinding.from_dict(
                _mapping(raw["repository"], "scope.repository")
            ),
            workspace=ManagedWorkspaceBinding.from_dict(
                _mapping(raw["workspace"], "scope.workspace")
            ),
        )


@dataclass(frozen=True)
class ArtifactBinding:
    """One reviewed artifact whose bytes are included by digest."""

    artifact_id: str
    sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifact_id", _artifact_id(self.artifact_id))
        object.__setattr__(self, "sha256", _digest(self.sha256, "artifact.sha256"))

    def to_dict(self) -> dict[str, str]:
        return {"artifact_id": self.artifact_id, "sha256": self.sha256}

    @classmethod
    def from_dict(cls, document: Mapping[str, Any]) -> ArtifactBinding:
        raw = _mapping(document, "artifact")
        _exact_keys(raw, required={"artifact_id", "sha256"})
        return cls(artifact_id=raw["artifact_id"], sha256=raw["sha256"])


@runtime_checkable
class TypedExternalAction(Protocol):
    """An explicitly typed, canonical external action (never a generic command)."""

    @property
    def kind(self) -> str:
        """Stable semantic action discriminator."""
        ...

    def to_dict(self) -> dict[str, Any]:
        """Canonical JSON-compatible action document."""
        ...

    def digest(self) -> str:
        """Domain-separated digest of the complete action."""
        ...


@dataclass(frozen=True)
class PullRequestCreateAction:
    """The first supported typed closeout action.

    A broker may create exactly one pull request. It does not receive a shell command,
    process arguments, credentials, or an open-ended operation name.
    """

    repository: str
    base_ref: str
    head_ref: str
    head_commit: str
    title: str
    body: str
    draft: bool = False
    artifacts: tuple[ArtifactBinding, ...] = ()
    kind: str = PULL_REQUEST_CREATE

    def __post_init__(self) -> None:
        if self.kind != PULL_REQUEST_CREATE:
            raise ApprovalValidationError(
                f"unsupported external action kind {self.kind!r}"
            )
        object.__setattr__(
            self,
            "repository",
            _repository_id(self.repository, "action.repository"),
        )
        object.__setattr__(self, "base_ref", _git_ref(self.base_ref, "action.base_ref"))
        object.__setattr__(self, "head_ref", _git_ref(self.head_ref, "action.head_ref"))
        object.__setattr__(
            self, "head_commit", _commit(self.head_commit, "action.head_commit")
        )
        object.__setattr__(
            self, "title", _required_text(self.title, "action.title", max_bytes=1024)
        )
        if not isinstance(self.body, str) or len(self.body.encode("utf-8")) > 131_072:
            raise ApprovalValidationError(
                "action.body must be a string of at most 131072 UTF-8 bytes"
            )
        if not isinstance(self.draft, bool):
            raise ApprovalValidationError("action.draft must be a boolean")
        if isinstance(self.artifacts, (str, bytes)):
            raise ApprovalValidationError("action.artifacts must be a sequence")
        artifacts = tuple(self.artifacts)
        if any(not isinstance(item, ArtifactBinding) for item in artifacts):
            raise ApprovalValidationError(
                "action.artifacts must contain ArtifactBinding values"
            )
        artifact_ids = [item.artifact_id for item in artifacts]
        if artifact_ids != sorted(artifact_ids) or len(set(artifact_ids)) != len(
            artifact_ids
        ):
            raise ApprovalValidationError(
                "action.artifacts must be unique and sorted by artifact_id"
            )
        object.__setattr__(self, "artifacts", artifacts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "repository": self.repository,
            "base_ref": self.base_ref,
            "head_ref": self.head_ref,
            "head_commit": self.head_commit,
            "title": self.title,
            "body": self.body,
            "draft": self.draft,
            "artifacts": {item.artifact_id: item.sha256 for item in self.artifacts},
        }

    def digest(self) -> str:
        return _document_digest(ACTION_DOMAIN, self.to_dict())

    @classmethod
    def from_dict(cls, document: Mapping[str, Any]) -> PullRequestCreateAction:
        raw = _mapping(document, "action")
        _exact_keys(
            raw,
            required={
                "kind",
                "repository",
                "base_ref",
                "head_ref",
                "head_commit",
                "title",
                "body",
                "draft",
                "artifacts",
            },
        )
        artifacts = raw["artifacts"]
        if not isinstance(artifacts, Mapping) or any(
            not isinstance(key, str) for key in artifacts
        ):
            raise ApprovalValidationError("action.artifacts must be an object")
        return cls(
            kind=raw["kind"],
            repository=raw["repository"],
            base_ref=raw["base_ref"],
            head_ref=raw["head_ref"],
            head_commit=raw["head_commit"],
            title=raw["title"],
            body=raw["body"],
            draft=raw["draft"],
            artifacts=tuple(
                ArtifactBinding(artifact_id=artifact_id, sha256=artifacts[artifact_id])
                for artifact_id in sorted(artifacts)
            ),
        )


ExternalAction = PullRequestCreateAction


def action_from_dict(document: Mapping[str, Any]) -> ExternalAction:
    kind = document.get("kind")
    if kind != PULL_REQUEST_CREATE:
        raise ApprovalValidationError(f"unsupported external action kind {kind!r}")
    return PullRequestCreateAction.from_dict(document)


@dataclass(frozen=True)
class ManagedApprovalRequest:
    """Canonical origin-bound request presented to an external authorizer."""

    request_id: str
    created_at: datetime
    expires_at: datetime
    scope: ManagedApprovalScope
    action: ExternalAction
    schema_version: int = APPROVAL_SCHEMA_VERSION
    domain: str = REQUEST_DOMAIN

    def __post_init__(self) -> None:
        if (
            self.schema_version != APPROVAL_SCHEMA_VERSION
            or self.domain != REQUEST_DOMAIN
        ):
            raise ApprovalValidationError(
                "unsupported managed approval request version/domain"
            )
        object.__setattr__(
            self, "request_id", _identifier(self.request_id, "request_id")
        )
        object.__setattr__(
            self, "created_at", _utc_datetime(self.created_at, "created_at")
        )
        object.__setattr__(
            self, "expires_at", _utc_datetime(self.expires_at, "expires_at")
        )
        if self.expires_at <= self.created_at:
            raise ApprovalValidationError("request expires_at must be after created_at")
        if not isinstance(self.scope, ManagedApprovalScope):
            raise ApprovalValidationError("request.scope has the wrong type")
        if not isinstance(self.action, PullRequestCreateAction):
            raise ApprovalValidationError(
                "request.action must be a supported typed action"
            )
        if self.action.repository != self.scope.repository.repository:
            raise ApprovalValidationError(
                "action repository differs from the bound repository"
            )
        if self.action.head_commit != self.scope.workspace.checkpoint.head_commit:
            raise ApprovalValidationError(
                "action head commit differs from the bound workspace checkpoint"
            )
        if self.action.head_ref != self.scope.repository.branch:
            raise ApprovalValidationError(
                "action head ref differs from the bound source branch"
            )
        if self.action.head_commit != self.scope.repository.commit:
            raise ApprovalValidationError(
                "action head commit differs from the bound source commit"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "created_at": _timestamp_text(self.created_at),
            "expires_at": _timestamp_text(self.expires_at),
            "scope": self.scope.to_dict(),
            "action": self.action.to_dict(),
            "action_digest": self.action.digest(),
        }

    def signing_bytes(self) -> bytes:
        return domain_separated_bytes(REQUEST_DOMAIN, self.to_dict())

    def digest(self) -> str:
        return hashlib.sha256(self.signing_bytes()).hexdigest()

    @classmethod
    def from_dict(cls, document: Mapping[str, Any]) -> ManagedApprovalRequest:
        raw = _mapping(document, "request")
        _exact_keys(
            raw,
            required={
                "domain",
                "schema_version",
                "request_id",
                "created_at",
                "expires_at",
                "scope",
                "action",
                "action_digest",
            },
        )
        action = action_from_dict(_mapping(raw["action"], "request.action"))
        supplied_digest = _digest(raw["action_digest"], "request.action_digest")
        if supplied_digest != action.digest():
            raise ApprovalValidationError(
                "request.action_digest does not match the action"
            )
        return cls(
            domain=raw["domain"],
            schema_version=raw["schema_version"],
            request_id=raw["request_id"],
            created_at=_parse_timestamp(raw["created_at"], "request.created_at"),
            expires_at=_parse_timestamp(raw["expires_at"], "request.expires_at"),
            scope=ManagedApprovalScope.from_dict(
                _mapping(raw["scope"], "request.scope")
            ),
            action=action,
        )


class ApprovalDecision(str, Enum):
    APPROVED = "approved"


@dataclass(frozen=True)
class ManagedAuthorizationEnvelope:
    """Detached human/authority authorization; ``signature`` is not part of signed claims."""

    authorization_id: str
    request_id: str
    request_digest: str
    policy_id: str
    policy_digest: str
    signer_id: str
    key_id: str
    algorithm: str
    issued_at: datetime
    expires_at: datetime
    signature: str
    decision: ApprovalDecision = ApprovalDecision.APPROVED
    schema_version: int = APPROVAL_SCHEMA_VERSION
    domain: str = AUTHORIZATION_DOMAIN

    def __post_init__(self) -> None:
        if (
            self.schema_version != APPROVAL_SCHEMA_VERSION
            or self.domain != AUTHORIZATION_DOMAIN
        ):
            raise ApprovalValidationError(
                "unsupported authorization envelope version/domain"
            )
        if self.decision is not ApprovalDecision.APPROVED:
            try:
                object.__setattr__(self, "decision", ApprovalDecision(self.decision))
            except (TypeError, ValueError) as exc:
                raise ApprovalValidationError(
                    "authorization decision must be approved"
                ) from exc
        for field_name in (
            "authorization_id",
            "request_id",
            "policy_id",
            "signer_id",
            "key_id",
        ):
            object.__setattr__(
                self, field_name, _identifier(getattr(self, field_name), field_name)
            )
        object.__setattr__(
            self, "request_digest", _digest(self.request_digest, "request_digest")
        )
        object.__setattr__(
            self, "policy_digest", _digest(self.policy_digest, "policy_digest")
        )
        algorithm = _identifier(self.algorithm, "algorithm").lower()
        if algorithm not in _ASYMMETRIC_ALGORITHMS:
            raise ApprovalValidationError(
                "algorithm must identify a supported asymmetric signature scheme"
            )
        object.__setattr__(self, "algorithm", algorithm)
        object.__setattr__(
            self, "issued_at", _utc_datetime(self.issued_at, "issued_at")
        )
        object.__setattr__(
            self, "expires_at", _utc_datetime(self.expires_at, "expires_at")
        )
        if self.expires_at <= self.issued_at:
            raise ApprovalValidationError(
                "authorization expires_at must be after issued_at"
            )
        _decode_signature(self.signature)

    def signed_claims(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "schema_version": self.schema_version,
            "authorization_id": self.authorization_id,
            "decision": self.decision.value,
            "request_id": self.request_id,
            "request_digest": self.request_digest,
            "policy_id": self.policy_id,
            "policy_digest": self.policy_digest,
            "signer_id": self.signer_id,
            "key_id": self.key_id,
            "algorithm": self.algorithm,
            "issued_at": _timestamp_text(self.issued_at),
            "expires_at": _timestamp_text(self.expires_at),
        }

    def signing_bytes(self) -> bytes:
        return domain_separated_bytes(AUTHORIZATION_DOMAIN, self.signed_claims())

    def signature_bytes(self) -> bytes:
        return _decode_signature(self.signature)

    def to_dict(self) -> dict[str, Any]:
        return {**self.signed_claims(), "signature": self.signature}

    def digest(self) -> str:
        return _document_digest(ENVELOPE_DOMAIN, self.to_dict())

    @classmethod
    def from_dict(cls, document: Mapping[str, Any]) -> ManagedAuthorizationEnvelope:
        raw = _mapping(document, "authorization")
        _exact_keys(
            raw,
            required={
                "domain",
                "schema_version",
                "authorization_id",
                "decision",
                "request_id",
                "request_digest",
                "policy_id",
                "policy_digest",
                "signer_id",
                "key_id",
                "algorithm",
                "issued_at",
                "expires_at",
                "signature",
            },
        )
        try:
            decision = ApprovalDecision(raw["decision"])
        except (TypeError, ValueError) as exc:
            raise ApprovalValidationError(
                "authorization decision must be approved"
            ) from exc
        return cls(
            domain=raw["domain"],
            schema_version=raw["schema_version"],
            authorization_id=raw["authorization_id"],
            decision=decision,
            request_id=raw["request_id"],
            request_digest=raw["request_digest"],
            policy_id=raw["policy_id"],
            policy_digest=raw["policy_digest"],
            signer_id=raw["signer_id"],
            key_id=raw["key_id"],
            algorithm=raw["algorithm"],
            issued_at=_parse_timestamp(raw["issued_at"], "authorization.issued_at"),
            expires_at=_parse_timestamp(raw["expires_at"], "authorization.expires_at"),
            signature=raw["signature"],
        )


def _decode_signature(value: object) -> bytes:
    if not isinstance(value, str) or not _BASE64URL_RE.fullmatch(value) or "=" in value:
        raise ApprovalValidationError("signature must be unpadded base64url")
    try:
        decoded = base64.b64decode(
            value + "=" * (-len(value) % 4), altchars=b"-_", validate=True
        )
    except (binascii.Error, ValueError) as exc:
        raise ApprovalValidationError(
            "signature must be valid unpadded base64url"
        ) from exc
    if not 32 <= len(decoded) <= 2048:
        raise ApprovalValidationError(
            "signature byte length is outside the supported range"
        )
    if base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=") != value:
        raise ApprovalValidationError(
            "signature is not in canonical unpadded base64url form"
        )
    return decoded


@dataclass(frozen=True)
class SignerPolicyDecision:
    """Result returned by a trusted, host-owned signer policy."""

    allowed: bool
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.allowed, bool):
            raise ApprovalValidationError("policy decision allowed must be a boolean")
        object.__setattr__(
            self, "reason", _required_text(self.reason, "policy decision reason")
        )


@runtime_checkable
class ExternalSignerPolicy(Protocol):
    """Trusted policy loaded by the coordinator outside the managed project.

    The implementation may use a protected CI environment, an OS-managed policy file,
    or a remote authorization service. Its private signing authority must never be made
    available to a managed worker.
    """

    @property
    def policy_id(self) -> str: ...

    @property
    def policy_digest(self) -> str: ...

    @property
    def source_path(self) -> Path: ...

    def evaluate(
        self,
        request: ManagedApprovalRequest,
        envelope: ManagedAuthorizationEnvelope,
    ) -> SignerPolicyDecision:
        """Authorize this signer/key/action/scope under the current external policy."""
        ...


@runtime_checkable
class AsymmetricSignatureVerifier(Protocol):
    """Host-injected public-key verifier. No secret-key API exists in this module."""

    def verify(
        self,
        *,
        algorithm: str,
        key_id: str,
        message: bytes,
        signature: bytes,
    ) -> bool:
        """Return true only when the detached asymmetric signature is valid."""
        ...


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def validate_external_policy_source(source_path: Path, project_root: Path) -> Path:
    """Resolve and validate a host policy source outside the project trust boundary.

    Both the lexical and resolved paths are checked. Thus a project-local symlink to an
    external file and an external symlink back into the project are both rejected. Group-
    or world-writable policy files are rejected because another local principal could
    replace the trusted signer set. This check is necessary but not sufficient when a
    managed worker shares the coordinator's OS account: that host must additionally deny
    the worker write access to the external path (or use a protected remote policy).
    """

    source = Path(source_path)
    project = Path(project_root)
    if not source.is_absolute():
        raise ApprovalPolicyError("signer policy source must be an absolute path")
    try:
        project_lexical = Path(os.path.abspath(project))
        source_lexical = Path(os.path.abspath(source))
        project_resolved = project.resolve(strict=True)
        source_resolved = source.resolve(strict=True)
    except OSError as exc:
        raise ApprovalPolicyError(
            f"cannot resolve signer policy boundary: {exc}"
        ) from exc
    if _is_within(source_lexical, project_lexical) or _is_within(
        source_resolved, project_resolved
    ):
        raise ApprovalPolicyError(
            "signer policy source must be outside the managed project"
        )
    try:
        source_stat = source_resolved.stat()
    except OSError as exc:
        raise ApprovalPolicyError(
            f"cannot inspect signer policy source: {exc}"
        ) from exc
    if not stat.S_ISREG(source_stat.st_mode):
        raise ApprovalPolicyError("signer policy source must be a regular file")
    if source_stat.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise ApprovalPolicyError(
            "signer policy source must not be group- or world-writable"
        )
    return source_resolved


@dataclass(frozen=True)
class VerifiedAuthorization:
    request_digest: str
    authorization_digest: str
    policy_id: str
    policy_digest: str
    signer_id: str
    key_id: str


def _first_difference(
    expected: object, actual: object, path: str = "$"
) -> Optional[str]:
    if type(expected) is not type(actual):
        return path
    if isinstance(expected, dict):
        if not isinstance(actual, dict) or set(expected) != set(actual):
            return path
        for key in sorted(expected):
            difference = _first_difference(
                expected[key],
                actual[key],
                f"{path}.{key}",
            )
            if difference:
                return difference
        return None
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(expected) != len(actual):
            return path
        for index, item in enumerate(expected):
            difference = _first_difference(item, actual[index], f"{path}[{index}]")
            if difference:
                return difference
        return None
    return None if expected == actual else path


def validate_exact_binding(
    request: ManagedApprovalRequest,
    *,
    current_scope: ManagedApprovalScope,
    current_action: TypedExternalAction,
) -> None:
    """Fail when any origin, workspace, workflow, provider, or action field drifted."""

    if not isinstance(current_scope, ManagedApprovalScope):
        raise ApprovalDriftError("current scope has the wrong type")
    scope_difference = _first_difference(
        request.scope.to_dict(), current_scope.to_dict()
    )
    if scope_difference:
        raise ApprovalDriftError(
            f"managed approval scope drifted at {scope_difference}"
        )
    if not isinstance(current_action, PullRequestCreateAction):
        raise ApprovalDriftError("current action is not the signed typed action")
    action_difference = _first_difference(
        request.action.to_dict(), current_action.to_dict()
    )
    if action_difference:
        raise ApprovalDriftError(
            f"managed approval action drifted at {action_difference}"
        )
    if request.action.digest() != current_action.digest():
        raise ApprovalDriftError("managed approval action digest drifted")


def verify_authorization(
    request: ManagedApprovalRequest,
    envelope: ManagedAuthorizationEnvelope,
    *,
    current_scope: ManagedApprovalScope,
    current_action: TypedExternalAction,
    policy: ExternalSignerPolicy,
    verifier: AsymmetricSignatureVerifier,
    project_root: Path,
    now: datetime,
) -> VerifiedAuthorization:
    """Verify one detached authorization against current state and external trust."""

    current_time = _utc_datetime(now, "now")
    validate_exact_binding(
        request, current_scope=current_scope, current_action=current_action
    )
    if current_time < request.created_at or current_time >= request.expires_at:
        raise ApprovalExpiredError("managed approval request is not currently valid")
    if (
        envelope.request_id != request.request_id
        or envelope.request_digest != request.digest()
    ):
        raise ApprovalSignatureError("authorization is bound to a different request")
    if envelope.issued_at < request.created_at or envelope.issued_at > current_time:
        raise ApprovalExpiredError(
            "authorization issuance time is outside the request lifetime"
        )
    if envelope.expires_at > request.expires_at or current_time >= envelope.expires_at:
        raise ApprovalExpiredError("authorization is expired or outlives its request")

    validate_external_policy_source(Path(policy.source_path), Path(project_root))
    policy_id = _identifier(policy.policy_id, "policy.policy_id")
    policy_digest = _digest(policy.policy_digest, "policy.policy_digest")
    if envelope.policy_id != policy_id or envelope.policy_digest != policy_digest:
        raise ApprovalPolicyError(
            "authorization names a different signer policy revision"
        )
    try:
        decision = policy.evaluate(request, envelope)
    except Exception as exc:
        raise ApprovalPolicyError("external signer policy evaluation failed") from exc
    if not isinstance(decision, SignerPolicyDecision) or not decision.allowed:
        reason = (
            decision.reason
            if isinstance(decision, SignerPolicyDecision)
            else "invalid result"
        )
        raise ApprovalPolicyError(
            f"external signer policy denied authorization: {reason}"
        )
    try:
        valid_signature = verifier.verify(
            algorithm=envelope.algorithm,
            key_id=envelope.key_id,
            message=envelope.signing_bytes(),
            signature=envelope.signature_bytes(),
        )
    except Exception as exc:
        raise ApprovalSignatureError(
            "asymmetric signature verifier failed closed"
        ) from exc
    if valid_signature is not True:
        raise ApprovalSignatureError("detached asymmetric signature is invalid")
    return VerifiedAuthorization(
        request_digest=request.digest(),
        authorization_digest=envelope.digest(),
        policy_id=policy_id,
        policy_digest=policy_digest,
        signer_id=envelope.signer_id,
        key_id=envelope.key_id,
    )


class ApprovalState(str, Enum):
    PENDING = "pending"
    AUTHORIZED = "authorized"
    CONSUMING = "consuming"
    CONSUMED = "consumed"
    INDETERMINATE = "indeterminate"


@dataclass(frozen=True)
class ConsumptionRecord:
    """Durable consume-before-call boundary and deterministic idempotency key."""

    authorization_digest: str
    idempotency_key: str
    started_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "authorization_digest",
            _digest(self.authorization_digest, "authorization_digest"),
        )
        object.__setattr__(
            self, "idempotency_key", _digest(self.idempotency_key, "idempotency_key")
        )
        object.__setattr__(
            self, "started_at", _utc_datetime(self.started_at, "started_at")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authorization_digest": self.authorization_digest,
            "idempotency_key": self.idempotency_key,
            "started_at": _timestamp_text(self.started_at),
        }

    @classmethod
    def from_dict(cls, document: Mapping[str, Any]) -> ConsumptionRecord:
        raw = _mapping(document, "consumption")
        _exact_keys(
            raw, required={"authorization_digest", "idempotency_key", "started_at"}
        )
        return cls(
            authorization_digest=raw["authorization_digest"],
            idempotency_key=raw["idempotency_key"],
            started_at=_parse_timestamp(raw["started_at"], "consumption.started_at"),
        )


@runtime_checkable
class TypedActionReceipt(Protocol):
    @property
    def kind(self) -> str: ...

    @property
    def request_digest(self) -> str: ...

    @property
    def action_digest(self) -> str: ...

    @property
    def idempotency_key(self) -> str: ...

    def to_dict(self) -> dict[str, Any]: ...


@dataclass(frozen=True)
class PullRequestReceipt:
    """Reconciliable receipt for the typed pull-request creation action."""

    request_digest: str
    action_digest: str
    idempotency_key: str
    repository: str
    base_ref: str
    head_ref: str
    head_commit: str
    external_id: str
    url: str
    marker: str
    observed_at: datetime
    kind: str = PULL_REQUEST_CREATE

    def __post_init__(self) -> None:
        if self.kind != PULL_REQUEST_CREATE:
            raise ApprovalValidationError("receipt kind is not supported")
        for field_name in ("request_digest", "action_digest", "idempotency_key"):
            object.__setattr__(
                self, field_name, _digest(getattr(self, field_name), field_name)
            )
        object.__setattr__(
            self,
            "repository",
            _repository_id(self.repository, "receipt.repository"),
        )
        object.__setattr__(
            self, "base_ref", _git_ref(self.base_ref, "receipt.base_ref")
        )
        object.__setattr__(
            self, "head_ref", _git_ref(self.head_ref, "receipt.head_ref")
        )
        object.__setattr__(
            self, "head_commit", _commit(self.head_commit, "receipt.head_commit")
        )
        object.__setattr__(
            self,
            "external_id",
            _required_text(self.external_id, "receipt.external_id", max_bytes=1024),
        )
        url = _required_text(self.url, "receipt.url", max_bytes=4096)
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or any(character.isspace() for character in url)
        ):
            raise ApprovalValidationError(
                "receipt.url must be a credential-free HTTPS URL"
            )
        object.__setattr__(self, "url", url)
        object.__setattr__(
            self, "marker", _required_text(self.marker, "receipt.marker", max_bytes=256)
        )
        object.__setattr__(
            self, "observed_at", _utc_datetime(self.observed_at, "observed_at")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "request_digest": self.request_digest,
            "action_digest": self.action_digest,
            "idempotency_key": self.idempotency_key,
            "repository": self.repository,
            "base_ref": self.base_ref,
            "head_ref": self.head_ref,
            "head_commit": self.head_commit,
            "external_id": self.external_id,
            "url": self.url,
            "marker": self.marker,
            "observed_at": _timestamp_text(self.observed_at),
        }

    @classmethod
    def from_dict(cls, document: Mapping[str, Any]) -> PullRequestReceipt:
        raw = _mapping(document, "receipt")
        _exact_keys(
            raw,
            required={
                "kind",
                "request_digest",
                "action_digest",
                "idempotency_key",
                "repository",
                "base_ref",
                "head_ref",
                "head_commit",
                "external_id",
                "url",
                "marker",
                "observed_at",
            },
        )
        return cls(
            kind=raw["kind"],
            request_digest=raw["request_digest"],
            action_digest=raw["action_digest"],
            idempotency_key=raw["idempotency_key"],
            repository=raw["repository"],
            base_ref=raw["base_ref"],
            head_ref=raw["head_ref"],
            head_commit=raw["head_commit"],
            external_id=raw["external_id"],
            url=raw["url"],
            marker=raw["marker"],
            observed_at=_parse_timestamp(raw["observed_at"], "receipt.observed_at"),
        )


ExternalReceipt = PullRequestReceipt


def approval_marker(request_digest: str) -> str:
    return APPROVAL_MARKER_PREFIX + _digest(request_digest, "request_digest")


def _idempotency_key(request_digest: str, authorization_digest: str) -> str:
    document = {
        "request_digest": _digest(request_digest, "request_digest"),
        "authorization_digest": _digest(authorization_digest, "authorization_digest"),
    }
    return _document_digest(CONSUMPTION_DOMAIN, document)


@dataclass(frozen=True)
class BrokerExecutionPermit:
    """Non-secret capability handed to a typed broker after consume-before-call CAS."""

    request_id: str
    request_digest: str
    authorization_digest: str
    idempotency_key: str
    marker: str
    consumption_started_at: datetime
    scope: ManagedApprovalScope
    action: ExternalAction

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "request_id", _identifier(self.request_id, "request_id")
        )
        object.__setattr__(
            self, "request_digest", _digest(self.request_digest, "request_digest")
        )
        object.__setattr__(
            self,
            "authorization_digest",
            _digest(self.authorization_digest, "authorization_digest"),
        )
        object.__setattr__(
            self,
            "idempotency_key",
            _digest(self.idempotency_key, "idempotency_key"),
        )
        if self.idempotency_key != _idempotency_key(
            self.request_digest, self.authorization_digest
        ):
            raise ApprovalValidationError(
                "broker permit idempotency key is not canonical"
            )
        if self.marker != approval_marker(self.request_digest):
            raise ApprovalValidationError("broker permit marker is not canonical")
        object.__setattr__(
            self,
            "consumption_started_at",
            _utc_datetime(self.consumption_started_at, "consumption_started_at"),
        )
        if not isinstance(self.scope, ManagedApprovalScope):
            raise ApprovalValidationError("broker permit scope has the wrong type")
        if not isinstance(self.action, PullRequestCreateAction):
            raise ApprovalValidationError("broker permit action has the wrong type")


@runtime_checkable
class TypedBrokerPreflight(Protocol):
    """Read-only external observation required immediately before execution."""

    @property
    def kind(self) -> str: ...

    @property
    def request_digest(self) -> str: ...

    @property
    def action_digest(self) -> str: ...

    @property
    def idempotency_key(self) -> str: ...

    def to_dict(self) -> dict[str, Any]: ...


@dataclass(frozen=True)
class PullRequestBrokerPreflight:
    """Broker-observed remote branch state before pull-request creation."""

    request_digest: str
    action_digest: str
    idempotency_key: str
    repository: str
    base_ref: str
    head_ref: str
    expected_head_commit: str
    observed_head_commit: str
    marker: str
    checked_at: datetime
    kind: str = PULL_REQUEST_CREATE

    def __post_init__(self) -> None:
        if self.kind != PULL_REQUEST_CREATE:
            raise ApprovalValidationError("broker preflight kind is not supported")
        for field_name in ("request_digest", "action_digest", "idempotency_key"):
            object.__setattr__(
                self, field_name, _digest(getattr(self, field_name), field_name)
            )
        object.__setattr__(
            self,
            "repository",
            _repository_id(self.repository, "broker preflight repository"),
        )
        object.__setattr__(
            self, "base_ref", _git_ref(self.base_ref, "broker preflight base_ref")
        )
        object.__setattr__(
            self, "head_ref", _git_ref(self.head_ref, "broker preflight head_ref")
        )
        object.__setattr__(
            self,
            "expected_head_commit",
            _commit(self.expected_head_commit, "broker preflight expected_head_commit"),
        )
        object.__setattr__(
            self,
            "observed_head_commit",
            _commit(self.observed_head_commit, "broker preflight observed_head_commit"),
        )
        object.__setattr__(
            self,
            "marker",
            _required_text(self.marker, "broker preflight marker", max_bytes=256),
        )
        object.__setattr__(
            self,
            "checked_at",
            _utc_datetime(self.checked_at, "broker preflight checked_at"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "request_digest": self.request_digest,
            "action_digest": self.action_digest,
            "idempotency_key": self.idempotency_key,
            "repository": self.repository,
            "base_ref": self.base_ref,
            "head_ref": self.head_ref,
            "expected_head_commit": self.expected_head_commit,
            "observed_head_commit": self.observed_head_commit,
            "marker": self.marker,
            "checked_at": _timestamp_text(self.checked_at),
        }

    def digest(self) -> str:
        return _document_digest(PREFLIGHT_DOMAIN, self.to_dict())


def validate_broker_preflight(
    permit: BrokerExecutionPermit,
    preflight: TypedBrokerPreflight,
    *,
    now: datetime,
    max_age: timedelta = timedelta(seconds=BROKER_PREFLIGHT_MAX_AGE_SECONDS),
) -> PullRequestBrokerPreflight:
    """Validate a fresh, exact remote-head observation before broker execution."""

    if not isinstance(preflight, PullRequestBrokerPreflight):
        raise ApprovalValidationError("broker returned an unsupported preflight type")
    if not isinstance(max_age, timedelta) or max_age <= timedelta(0):
        raise ApprovalValidationError("broker preflight max_age must be positive")
    action = permit.action
    checks = {
        "kind": (preflight.kind, action.kind),
        "request_digest": (preflight.request_digest, permit.request_digest),
        "action_digest": (preflight.action_digest, action.digest()),
        "idempotency_key": (preflight.idempotency_key, permit.idempotency_key),
        "repository": (preflight.repository, action.repository),
        "base_ref": (preflight.base_ref, action.base_ref),
        "head_ref": (preflight.head_ref, action.head_ref),
        "expected_head_commit": (
            preflight.expected_head_commit,
            action.head_commit,
        ),
        "observed_head_commit": (
            preflight.observed_head_commit,
            action.head_commit,
        ),
        "marker": (preflight.marker, permit.marker),
    }
    for field_name, (actual, expected) in checks.items():
        if actual != expected:
            raise ApprovalDriftError(
                f"broker preflight {field_name} differs from the consumed action"
            )
    current_time = _utc_datetime(now, "now")
    if (
        preflight.checked_at < permit.consumption_started_at
        or preflight.checked_at > current_time
        or current_time - preflight.checked_at > max_age
    ):
        raise ApprovalExpiredError(
            "broker preflight is stale or outside the consumption interval"
        )
    return preflight


@runtime_checkable
class ExternalActionBroker(Protocol):
    """Coordinator-owned typed action boundary.

    Implementations must keep external credentials out of managed worker processes. They
    must reconcile by ``idempotency_key``/``marker`` after a crash and return a typed
    receipt. Arbitrary command execution is outside this protocol.
    """

    @property
    def action_kind(self) -> str: ...

    def preflight(self, permit: BrokerExecutionPermit) -> TypedBrokerPreflight: ...

    def execute(
        self,
        permit: BrokerExecutionPermit,
        preflight: TypedBrokerPreflight,
    ) -> TypedActionReceipt: ...

    def reconcile(
        self, permit: BrokerExecutionPermit
    ) -> Optional[TypedActionReceipt]: ...


@dataclass(frozen=True)
class ManagedApprovalRecord:
    """Persistable one-shot approval lifecycle record."""

    request: ManagedApprovalRequest
    request_digest: str
    state: ApprovalState = ApprovalState.PENDING
    revision: int = 0
    authorization: Optional[ManagedAuthorizationEnvelope] = None
    authorization_digest: Optional[str] = None
    authorized_at: Optional[datetime] = None
    consumption: Optional[ConsumptionRecord] = None
    receipt: Optional[ExternalReceipt] = None
    indeterminate_reason: Optional[str] = None
    terminal_at: Optional[datetime] = None
    schema_version: int = APPROVAL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != APPROVAL_SCHEMA_VERSION:
            raise ApprovalValidationError("approval record schema_version must be 1")
        if not isinstance(self.request, ManagedApprovalRequest):
            raise ApprovalValidationError("record.request has the wrong type")
        object.__setattr__(
            self, "request_digest", _digest(self.request_digest, "request_digest")
        )
        if self.request_digest != self.request.digest():
            raise ApprovalValidationError(
                "record.request_digest does not match request"
            )
        if not isinstance(self.state, ApprovalState):
            try:
                object.__setattr__(self, "state", ApprovalState(self.state))
            except (TypeError, ValueError) as exc:
                raise ApprovalValidationError(
                    "approval record has an unsupported state"
                ) from exc
        if (
            not isinstance(self.revision, int)
            or isinstance(self.revision, bool)
            or self.revision < 0
        ):
            raise ApprovalValidationError(
                "record.revision must be a non-negative integer"
            )
        expected_revision = {
            ApprovalState.PENDING: 0,
            ApprovalState.AUTHORIZED: 1,
            ApprovalState.CONSUMING: 2,
            ApprovalState.CONSUMED: 3,
            ApprovalState.INDETERMINATE: 3,
        }[self.state]
        if self.revision != expected_revision:
            raise ApprovalValidationError(
                f"state {self.state.value!r} requires revision {expected_revision}"
            )
        self._validate_state_fields()

    @classmethod
    def pending(cls, request: ManagedApprovalRequest) -> ManagedApprovalRecord:
        return cls(request=request, request_digest=request.digest())

    def _validate_state_fields(self) -> None:
        authorization_fields = (
            self.authorization,
            self.authorization_digest,
            self.authorized_at,
        )
        terminal_fields = (self.receipt, self.indeterminate_reason, self.terminal_at)
        if self.state is ApprovalState.PENDING:
            if any(
                value is not None
                for value in authorization_fields
                + (self.consumption,)
                + terminal_fields
            ):
                raise ApprovalValidationError(
                    "pending record contains later lifecycle fields"
                )
            return
        if (
            self.authorization is None
            or self.authorization_digest is None
            or self.authorized_at is None
        ):
            raise ApprovalValidationError(
                "authorized record is missing authorization fields"
            )
        if (
            self.authorization.request_id != self.request.request_id
            or self.authorization.request_digest != self.request_digest
        ):
            raise ApprovalValidationError(
                "record authorization is bound to a different request"
            )
        if self.authorization_digest != self.authorization.digest():
            raise ApprovalValidationError(
                "record.authorization_digest does not match envelope"
            )
        authorized_at = _utc_datetime(self.authorized_at, "authorized_at")
        object.__setattr__(self, "authorized_at", authorized_at)
        if authorized_at < self.authorization.issued_at:
            raise ApprovalValidationError(
                "authorized_at precedes authorization issuance"
            )
        if (
            authorized_at >= self.authorization.expires_at
            or authorized_at >= self.request.expires_at
        ):
            raise ApprovalValidationError(
                "authorized_at is outside the authorization lifetime"
            )
        if self.state is ApprovalState.AUTHORIZED:
            if self.consumption is not None or any(
                value is not None for value in terminal_fields
            ):
                raise ApprovalValidationError(
                    "authorized record contains consume/terminal fields"
                )
            return
        if self.consumption is None:
            raise ApprovalValidationError(
                "consuming/terminal record is missing consumption"
            )
        if self.consumption.authorization_digest != self.authorization_digest:
            raise ApprovalValidationError(
                "consumption is bound to a different authorization"
            )
        if self.consumption.started_at < authorized_at:
            raise ApprovalValidationError("consumption started before authorization")
        expected_key = _idempotency_key(self.request_digest, self.authorization_digest)
        if self.consumption.idempotency_key != expected_key:
            raise ApprovalValidationError(
                "consumption idempotency key is not canonical"
            )
        if self.state is ApprovalState.CONSUMING:
            if any(value is not None for value in terminal_fields):
                raise ApprovalValidationError(
                    "consuming record contains terminal fields"
                )
            return
        if self.terminal_at is None:
            raise ApprovalValidationError("terminal record is missing terminal_at")
        terminal_at = _utc_datetime(self.terminal_at, "terminal_at")
        object.__setattr__(self, "terminal_at", terminal_at)
        if terminal_at < self.consumption.started_at:
            raise ApprovalValidationError("terminal_at precedes consumption")
        if self.state is ApprovalState.CONSUMED:
            if self.receipt is None or self.indeterminate_reason is not None:
                raise ApprovalValidationError("consumed record requires only a receipt")
            _validate_receipt(self, self.receipt, terminal_at)
            return
        if self.receipt is not None or self.indeterminate_reason is None:
            raise ApprovalValidationError("indeterminate record requires only a reason")
        object.__setattr__(
            self,
            "indeterminate_reason",
            _required_text(self.indeterminate_reason, "indeterminate_reason"),
        )

    def to_dict(self) -> dict[str, Any]:
        document: dict[str, Any] = {
            "schema_version": self.schema_version,
            "revision": self.revision,
            "state": self.state.value,
            "request": self.request.to_dict(),
            "request_digest": self.request_digest,
        }
        if self.authorization is not None:
            document["authorization"] = self.authorization.to_dict()
            document["authorization_digest"] = self.authorization_digest
            assert self.authorized_at is not None
            document["authorized_at"] = _timestamp_text(self.authorized_at)
        if self.consumption is not None:
            document["consumption"] = self.consumption.to_dict()
        if self.receipt is not None:
            document["receipt"] = self.receipt.to_dict()
        if self.indeterminate_reason is not None:
            document["indeterminate_reason"] = self.indeterminate_reason
        if self.terminal_at is not None:
            document["terminal_at"] = _timestamp_text(self.terminal_at)
        return document

    @classmethod
    def from_dict(cls, document: Mapping[str, Any]) -> ManagedApprovalRecord:
        raw = _mapping(document, "approval record")
        _exact_keys(
            raw,
            required={
                "schema_version",
                "revision",
                "state",
                "request",
                "request_digest",
            },
            optional={
                "authorization",
                "authorization_digest",
                "authorized_at",
                "consumption",
                "receipt",
                "indeterminate_reason",
                "terminal_at",
            },
        )
        optional_fields = {
            "authorization",
            "authorization_digest",
            "authorized_at",
            "consumption",
            "receipt",
            "indeterminate_reason",
            "terminal_at",
        }
        null_fields = sorted(
            field_name
            for field_name in optional_fields
            if field_name in raw and raw[field_name] is None
        )
        if null_fields:
            raise ApprovalValidationError(
                "approval record fields must be omitted rather than null: "
                + ", ".join(null_fields)
            )
        try:
            state_value = ApprovalState(raw["state"])
        except (TypeError, ValueError) as exc:
            raise ApprovalValidationError(
                "approval record has an unsupported state"
            ) from exc
        authorization_raw = raw.get("authorization")
        consumption_raw = raw.get("consumption")
        receipt_raw = raw.get("receipt")
        return cls(
            schema_version=raw["schema_version"],
            revision=raw["revision"],
            state=state_value,
            request=ManagedApprovalRequest.from_dict(
                _mapping(raw["request"], "record.request")
            ),
            request_digest=raw["request_digest"],
            authorization=(
                ManagedAuthorizationEnvelope.from_dict(
                    _mapping(authorization_raw, "record.authorization")
                )
                if authorization_raw is not None
                else None
            ),
            authorization_digest=raw.get("authorization_digest"),
            authorized_at=(
                _parse_timestamp(raw["authorized_at"], "record.authorized_at")
                if "authorized_at" in raw
                else None
            ),
            consumption=(
                ConsumptionRecord.from_dict(
                    _mapping(consumption_raw, "record.consumption")
                )
                if consumption_raw is not None
                else None
            ),
            receipt=(
                PullRequestReceipt.from_dict(_mapping(receipt_raw, "record.receipt"))
                if receipt_raw is not None
                else None
            ),
            indeterminate_reason=raw.get("indeterminate_reason"),
            terminal_at=(
                _parse_timestamp(raw["terminal_at"], "record.terminal_at")
                if "terminal_at" in raw
                else None
            ),
        )


def _validate_receipt(
    record: ManagedApprovalRecord, receipt: ExternalReceipt, completed_at: datetime
) -> None:
    if not isinstance(receipt, PullRequestReceipt):
        raise ApprovalValidationError("broker returned an unsupported receipt type")
    assert record.consumption is not None
    action = record.request.action
    checks = {
        "kind": (receipt.kind, action.kind),
        "request_digest": (receipt.request_digest, record.request_digest),
        "action_digest": (receipt.action_digest, action.digest()),
        "idempotency_key": (
            receipt.idempotency_key,
            record.consumption.idempotency_key,
        ),
        "repository": (receipt.repository, action.repository),
        "base_ref": (receipt.base_ref, action.base_ref),
        "head_ref": (receipt.head_ref, action.head_ref),
        "head_commit": (receipt.head_commit, action.head_commit),
        "source_branch": (
            receipt.head_ref,
            record.request.scope.repository.branch,
        ),
        "source_commit": (
            receipt.head_commit,
            record.request.scope.repository.commit,
        ),
        "workspace_head_commit": (
            receipt.head_commit,
            record.request.scope.workspace.checkpoint.head_commit,
        ),
        "marker": (receipt.marker, approval_marker(record.request_digest)),
    }
    for field_name, (actual, expected) in checks.items():
        if actual != expected:
            raise ApprovalValidationError(
                f"receipt {field_name} differs from the consumed action"
            )
    if (
        receipt.observed_at < record.consumption.started_at
        or receipt.observed_at > completed_at
    ):
        raise ApprovalValidationError(
            "receipt observation time is outside the consumption interval"
        )


def consumption_permit(record: ManagedApprovalRecord) -> BrokerExecutionPermit:
    """Reconstruct the non-secret broker permit for crash reconciliation."""

    if record.state is not ApprovalState.CONSUMING or record.consumption is None:
        raise ApprovalStateError("a broker permit exists only for a consuming approval")
    assert record.authorization_digest is not None
    return BrokerExecutionPermit(
        request_id=record.request.request_id,
        request_digest=record.request_digest,
        authorization_digest=record.authorization_digest,
        idempotency_key=record.consumption.idempotency_key,
        marker=approval_marker(record.request_digest),
        consumption_started_at=record.consumption.started_at,
        scope=record.request.scope,
        action=record.request.action,
    )


@runtime_checkable
class ManagedApprovalStore(Protocol):
    """Durable storage boundary; integration must reject snapshot rollback as well as CAS races."""

    def get(self, request_id: str) -> Optional[ManagedApprovalRecord]: ...

    def compare_and_swap(
        self,
        request_id: str,
        expected_revision: int,
        replacement: ManagedApprovalRecord,
    ) -> bool:
        """Atomically replace only the exact request/revision and return whether it won."""
        ...


class ManagedApprovalCoordinator:
    """One-shot lifecycle transitions over an injected durable CAS store."""

    def __init__(self, store: ManagedApprovalStore) -> None:
        self._store = store

    def _current(
        self, request_id: str, expected_revision: int
    ) -> ManagedApprovalRecord:
        record = self._store.get(_identifier(request_id, "request_id"))
        if record is None:
            raise ApprovalNotFoundError(
                f"managed approval {request_id!r} was not found"
            )
        if record.revision != expected_revision:
            raise ApprovalConflictError(
                f"managed approval revision is {record.revision}, expected {expected_revision}"
            )
        return record

    def _commit(
        self,
        previous: ManagedApprovalRecord,
        replacement: ManagedApprovalRecord,
    ) -> ManagedApprovalRecord:
        if replacement.request_digest != previous.request_digest:
            raise ApprovalStateError(
                "approval transition changed the immutable request"
            )
        if not self._store.compare_and_swap(
            previous.request.request_id, previous.revision, replacement
        ):
            raise ApprovalConflictError(
                "managed approval compare-and-swap lost a concurrent race"
            )
        return replacement

    def authorize(
        self,
        request_id: str,
        *,
        expected_revision: int,
        envelope: ManagedAuthorizationEnvelope,
        current_scope: ManagedApprovalScope,
        current_action: TypedExternalAction,
        policy: ExternalSignerPolicy,
        verifier: AsymmetricSignatureVerifier,
        project_root: Path,
        now: datetime,
    ) -> ManagedApprovalRecord:
        current = self._current(request_id, expected_revision)
        if current.state is not ApprovalState.PENDING:
            raise ApprovalStateError(
                "authorization can be attached only once to a pending request"
            )
        verified = verify_authorization(
            current.request,
            envelope,
            current_scope=current_scope,
            current_action=current_action,
            policy=policy,
            verifier=verifier,
            project_root=project_root,
            now=now,
        )
        replacement = replace(
            current,
            state=ApprovalState.AUTHORIZED,
            revision=1,
            authorization=envelope,
            authorization_digest=verified.authorization_digest,
            authorized_at=_utc_datetime(now, "now"),
        )
        return self._commit(current, replacement)

    def begin_consumption(
        self,
        request_id: str,
        *,
        expected_revision: int,
        current_scope: ManagedApprovalScope,
        current_action: TypedExternalAction,
        policy: ExternalSignerPolicy,
        verifier: AsymmetricSignatureVerifier,
        project_root: Path,
        now: datetime,
    ) -> tuple[ManagedApprovalRecord, BrokerExecutionPermit]:
        """Durably consume authorization before any broker preflight/external call."""

        current = self._current(request_id, expected_revision)
        if (
            current.state is not ApprovalState.AUTHORIZED
            or current.authorization is None
        ):
            raise ApprovalStateError("only an authorized request can begin consumption")
        verify_authorization(
            current.request,
            current.authorization,
            current_scope=current_scope,
            current_action=current_action,
            policy=policy,
            verifier=verifier,
            project_root=project_root,
            now=now,
        )
        assert current.authorization_digest is not None
        consumption = ConsumptionRecord(
            authorization_digest=current.authorization_digest,
            idempotency_key=_idempotency_key(
                current.request_digest, current.authorization_digest
            ),
            started_at=_utc_datetime(now, "now"),
        )
        replacement = replace(
            current,
            state=ApprovalState.CONSUMING,
            revision=2,
            consumption=consumption,
        )
        committed = self._commit(current, replacement)
        return committed, consumption_permit(committed)

    def record_consumed(
        self,
        request_id: str,
        *,
        expected_revision: int,
        receipt: TypedActionReceipt,
        completed_at: datetime,
    ) -> ManagedApprovalRecord:
        """Finalize a typed receipt after execution or deterministic reconciliation."""

        current = self._current(request_id, expected_revision)
        if current.state is not ApprovalState.CONSUMING:
            raise ApprovalStateError("only a consuming request can be finalized")
        if not isinstance(receipt, PullRequestReceipt):
            raise ApprovalValidationError("broker returned an unsupported receipt type")
        terminal = _utc_datetime(completed_at, "completed_at")
        _validate_receipt(current, receipt, terminal)
        replacement = replace(
            current,
            state=ApprovalState.CONSUMED,
            revision=3,
            receipt=receipt,
            terminal_at=terminal,
        )
        return self._commit(current, replacement)

    def record_indeterminate(
        self,
        request_id: str,
        *,
        expected_revision: int,
        reason: str,
        recorded_at: datetime,
    ) -> ManagedApprovalRecord:
        """Fail closed when remote outcome cannot be reconciled unambiguously."""

        current = self._current(request_id, expected_revision)
        if current.state is not ApprovalState.CONSUMING:
            raise ApprovalStateError(
                "only a consuming request can become indeterminate"
            )
        terminal = _utc_datetime(recorded_at, "recorded_at")
        if current.consumption is None or terminal < current.consumption.started_at:
            raise ApprovalValidationError("recorded_at precedes consumption")
        replacement = replace(
            current,
            state=ApprovalState.INDETERMINATE,
            revision=3,
            indeterminate_reason=_required_text(reason, "indeterminate reason"),
            terminal_at=terminal,
        )
        return self._commit(current, replacement)
