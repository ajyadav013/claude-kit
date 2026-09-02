"""Provider-neutral dispatch contracts for workflow orchestration.

This module defines semantics only.  Runtime adapters map the six lifecycle
operations to whatever worker API a host exposes; workflow and catalog code do
not import host tool identifiers or event shapes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Protocol, Sequence, runtime_checkable

from claude_kit.components import Capability, SymbolicRef

_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")
_MAX_PUBLIC_STOP_BYTES = 4_096
_MAX_MESSAGE_BYTES = 65_536
_REQUESTED_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,127}$")
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)(\b[A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|CREDENTIAL|API[_-]?KEY|PRIVATE[_-]?KEY)"
    r"[A-Z0-9_]*\b\s*[:=]\s*)([^\s,;]+)"
)
_SECRET_VALUE_RE = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|AKIA[0-9A-Z]{16}|"
    r"sk_(?:live_)?[0-9A-Za-z]{16,}|xox[baprs]-[0-9A-Za-z-]{10,}|"
    r"gh[psuor]_[0-9A-Za-z]{20,}|(?i:Bearer\s+)[0-9A-Za-z._~+/=-]{12,}"
)
_URL_CREDENTIAL_RE = re.compile(r"(://[^\s/:@]+:)[^\s/@]+(@)")


def public_human_stop_text(value: object, *, fallback: str) -> str:
    """Redact and bound host-authored text before public persistence or output."""

    text = str(value).strip()
    text = _SECRET_ASSIGNMENT_RE.sub(r"\1[REDACTED]", text)
    text = _SECRET_VALUE_RE.sub("[REDACTED]", text)
    text = _URL_CREDENTIAL_RE.sub(r"\1[REDACTED]\2", text)
    encoded = text.encode("utf-8")
    if len(encoded) > _MAX_PUBLIC_STOP_BYTES:
        suffix = b"...[truncated]"
        encoded = encoded[: _MAX_PUBLIC_STOP_BYTES - len(suffix)] + suffix
        text = encoded.decode("utf-8", errors="ignore")
    return text or fallback


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _identifier(value: object, field_name: str) -> str:
    text = _required_text(value, field_name)
    if not _ID_RE.fullmatch(text) or ".." in text:
        raise ValueError(
            f"{field_name} must use letters, digits, dots, underscores, or hyphens"
        )
    return text


def _references(
    values: Sequence[SymbolicRef], field_name: str
) -> tuple[SymbolicRef, ...]:
    if isinstance(values, (str, bytes)):
        raise ValueError(f"{field_name} must be a sequence of symbolic references")
    refs = tuple(SymbolicRef.coerce(value) for value in values)
    if len(set(refs)) != len(refs):
        raise ValueError(f"{field_name} must not contain duplicates")
    return refs


class DispatchStatus(str, Enum):
    """Portable worker lifecycle states."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def terminal(self) -> bool:
        """Whether no more output is expected from this attempt."""
        return self in {
            DispatchStatus.SUCCEEDED,
            DispatchStatus.FAILED,
            DispatchStatus.CANCELLED,
        }


class MessageKind(str, Enum):
    """Intent of a message sent to an active worker."""

    CONTEXT = "context"
    INSTRUCTION = "instruction"
    STATUS = "status"
    CORRECTION = "correction"


class WaitMode(str, Enum):
    """Completion condition for a bounded wait."""

    ALL = "all"
    FIRST_COMPLETED = "first-completed"


class ExecutionSlot(str, Enum):
    """Semantic participant selected by a provider-neutral coordinator."""

    MAKER = "maker"
    REVIEWER = "reviewer"


class HumanStopReason(str, Enum):
    """Portable reasons a worker may require a human decision."""

    MISSING_REQUIREMENTS = "missing-requirements"
    SCOPE_EXPANSION = "scope-expansion"
    IRREVERSIBLE_OPERATION = "irreversible-operation"
    EXTERNAL_SIDE_EFFECT = "external-side-effect"
    RETRY_BUDGET_EXHAUSTED = "retry-budget-exhausted"
    CONFLICTING_EVIDENCE = "conflicting-evidence"
    UNSUPPORTED_REQUIRED_CAPABILITY = "unsupported-required-capability"


@dataclass(frozen=True)
class HumanStopRequest:
    """A provider-neutral request to pause orchestration for a person."""

    reason: HumanStopReason
    message: str
    requested_action: str

    def __post_init__(self) -> None:
        if not isinstance(self.reason, HumanStopReason):
            try:
                object.__setattr__(self, "reason", HumanStopReason(self.reason))
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "reason must be a supported human-stop reason"
                ) from exc
        object.__setattr__(self, "message", _required_text(self.message, "message"))
        object.__setattr__(
            self,
            "requested_action",
            _required_text(self.requested_action, "requested_action"),
        )


def _capabilities(values: Sequence[Capability]) -> tuple[Capability, ...]:
    if isinstance(values, (str, bytes)):
        raise ValueError("capabilities must be a sequence")
    try:
        normalized = tuple(
            value if isinstance(value, Capability) else Capability(value)
            for value in values
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("capabilities contain an unsupported value") from exc
    if len(set(normalized)) != len(normalized):
        raise ValueError("capabilities must not contain duplicates")
    return tuple(sorted(normalized, key=lambda item: item.value))


def _execution_slot(value: object) -> Optional[ExecutionSlot]:
    if value is None:
        return None
    try:
        return value if isinstance(value, ExecutionSlot) else ExecutionSlot(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("execution_slot must be maker or reviewer when set") from exc


def _requested_model(value: object) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str) or not _REQUESTED_MODEL_RE.fullmatch(value):
        raise ValueError(
            "requested_model must be 1-128 ASCII letters, digits, or ._:/@+- "
            "and must start with a letter or digit"
        )
    return value


@dataclass(frozen=True)
class DispatchRequest:
    """Portable request for one independently owned unit of work."""

    route: str
    objective: str
    lane: str = "control"
    dependencies: tuple[SymbolicRef, ...] = ()
    evidence: tuple[SymbolicRef, ...] = ()
    retry_budget: str = "orchestration"
    context: str = ""
    required_capabilities: tuple[Capability, ...] = ()
    workspace: Optional[str] = None
    execution_slot: Optional[ExecutionSlot] = None
    requested_model: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "route", _identifier(self.route, "route"))
        object.__setattr__(
            self, "objective", _required_text(self.objective, "objective")
        )
        object.__setattr__(self, "lane", _identifier(self.lane, "lane"))
        object.__setattr__(
            self,
            "dependencies",
            _references(self.dependencies, "dependencies"),
        )
        object.__setattr__(self, "evidence", _references(self.evidence, "evidence"))
        object.__setattr__(
            self,
            "retry_budget",
            _identifier(self.retry_budget, "retry_budget"),
        )
        if not isinstance(self.context, str):
            raise ValueError("context must be a string")
        object.__setattr__(
            self,
            "required_capabilities",
            _capabilities(self.required_capabilities),
        )
        if self.workspace is not None:
            object.__setattr__(
                self, "workspace", _required_text(self.workspace, "workspace")
            )
        object.__setattr__(self, "execution_slot", _execution_slot(self.execution_slot))
        object.__setattr__(
            self, "requested_model", _requested_model(self.requested_model)
        )


@dataclass(frozen=True)
class DispatchHandle:
    """Stable identity for one dispatch attempt."""

    id: str
    route: str
    attempt: int = 1
    provider: Optional[str] = None
    required_capabilities: tuple[Capability, ...] = ()
    attested_capabilities: tuple[Capability, ...] = ()
    execution_slot: Optional[ExecutionSlot] = None
    requested_model: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _identifier(self.id, "dispatch id"))
        object.__setattr__(self, "route", _identifier(self.route, "route"))
        if (
            not isinstance(self.attempt, int)
            or isinstance(self.attempt, bool)
            or self.attempt < 1
        ):
            raise ValueError("attempt must be a positive integer")
        if self.provider is not None:
            object.__setattr__(self, "provider", _identifier(self.provider, "provider"))
        required = _capabilities(self.required_capabilities)
        attested = _capabilities(self.attested_capabilities)
        if not set(required).issubset(attested):
            missing = ", ".join(
                capability.value for capability in set(required) - set(attested)
            )
            raise ValueError(
                "required capabilities must be attested; missing: " + missing
            )
        object.__setattr__(self, "required_capabilities", required)
        object.__setattr__(self, "attested_capabilities", attested)
        object.__setattr__(self, "execution_slot", _execution_slot(self.execution_slot))
        object.__setattr__(
            self, "requested_model", _requested_model(self.requested_model)
        )


@dataclass(frozen=True)
class DispatchMessage:
    """A typed message queued before start or delivered to an active dispatch."""

    kind: MessageKind
    content: str
    correlation_id: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, MessageKind):
            try:
                object.__setattr__(self, "kind", MessageKind(self.kind))
            except (TypeError, ValueError) as exc:
                raise ValueError("kind must be a supported message kind") from exc
        content = _required_text(self.content, "content")
        if len(content.encode("utf-8")) > _MAX_MESSAGE_BYTES:
            raise ValueError(
                f"content must not exceed {_MAX_MESSAGE_BYTES} UTF-8 bytes"
            )
        object.__setattr__(self, "content", content)
        if self.correlation_id is not None:
            object.__setattr__(
                self,
                "correlation_id",
                _identifier(self.correlation_id, "correlation_id"),
            )


@dataclass(frozen=True)
class DispatchResult:
    """Terminal output and evidence from one dispatch attempt."""

    handle: DispatchHandle
    status: DispatchStatus
    output: Optional[str] = None
    error: Optional[str] = None
    evidence: tuple[SymbolicRef, ...] = ()
    human_stop: Optional[HumanStopRequest] = None

    def __post_init__(self) -> None:
        if not isinstance(self.handle, DispatchHandle):
            raise ValueError("handle must be a DispatchHandle")
        if not isinstance(self.status, DispatchStatus):
            try:
                object.__setattr__(self, "status", DispatchStatus(self.status))
            except (TypeError, ValueError) as exc:
                raise ValueError("status must be a supported dispatch status") from exc
        if not self.status.terminal:
            raise ValueError("a dispatch result must have a terminal status")
        if self.output is not None:
            object.__setattr__(self, "output", _required_text(self.output, "output"))
        if self.error is not None:
            object.__setattr__(self, "error", _required_text(self.error, "error"))
        if self.status is DispatchStatus.SUCCEEDED and self.error is not None:
            raise ValueError("a successful result cannot contain an error")
        if self.status is DispatchStatus.FAILED and self.error is None:
            raise ValueError("a failed result must contain an error")
        if self.human_stop is not None:
            if not isinstance(self.human_stop, HumanStopRequest):
                raise ValueError("human_stop must be a HumanStopRequest")
            if self.status is not DispatchStatus.FAILED:
                raise ValueError(
                    "a human stop must be represented as a failed dispatch"
                )
        object.__setattr__(self, "evidence", _references(self.evidence, "evidence"))


@dataclass(frozen=True)
class WaitResult:
    """Snapshot returned by a bounded wait."""

    completed: tuple[DispatchHandle, ...]
    pending: tuple[DispatchHandle, ...]
    timed_out: bool

    def __post_init__(self) -> None:
        if any(not isinstance(handle, DispatchHandle) for handle in self.completed):
            raise ValueError("completed must contain only dispatch handles")
        if any(not isinstance(handle, DispatchHandle) for handle in self.pending):
            raise ValueError("pending must contain only dispatch handles")
        if len(set(self.completed)) != len(self.completed):
            raise ValueError("completed must not contain duplicates")
        if len(set(self.pending)) != len(self.pending):
            raise ValueError("pending must not contain duplicates")
        overlap = set(self.completed) & set(self.pending)
        if overlap:
            raise ValueError("completed and pending dispatches must be disjoint")
        if not isinstance(self.timed_out, bool):
            raise ValueError("timed_out must be a boolean")


@runtime_checkable
class Dispatcher(Protocol):
    """Host adapter boundary used by a workflow executor.

    Implementations may maintain native session identifiers internally, but the
    observable contract remains portable and contains no host-specific types.
    """

    def spawn(self, request: DispatchRequest) -> DispatchHandle:
        """Start one dispatch attempt."""
        ...

    def message(self, handle: DispatchHandle, message: DispatchMessage) -> None:
        """Queue context before start or deliver it through an active session."""
        ...

    def wait(
        self,
        handles: Sequence[DispatchHandle],
        mode: WaitMode = WaitMode.ALL,
        timeout_seconds: Optional[float] = None,
    ) -> WaitResult:
        """Wait until the requested completion condition or timeout."""
        ...

    def collect(self, handles: Sequence[DispatchHandle]) -> tuple[DispatchResult, ...]:
        """Collect terminal results for the supplied dispatches."""
        ...

    def retry(self, handle: DispatchHandle, reason: str) -> DispatchHandle:
        """Start the next bounded attempt for a failed dispatch."""
        ...

    def cancel(self, handle: DispatchHandle, reason: str) -> None:
        """Cancel an active dispatch and preserve its terminal status."""
        ...
