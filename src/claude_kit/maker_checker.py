"""Evidence-bound maker/reviewer execution over native Claude and Codex hosts.

The coordinator owns contracts, artifacts, deterministic checks, iteration budgets,
and all persistence. Native workers are passive: makers return documents or unified
diffs through a constrained output channel, and every reviewer is a fresh read-only
dispatch over the exact current artifact digest.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
import uuid
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, Optional, Sequence, cast

from claude_kit import scaffold
from claude_kit.components import Capability, ModelTier
from claude_kit.dispatch import (
    Dispatcher,
    DispatchHandle,
    DispatchRequest,
    DispatchStatus,
    ExecutionSlot,
    HumanStopReason,
    HumanStopRequest,
    WaitMode,
    public_human_stop_text,
)
from claude_kit.execution_config import ExecutionConfigError, load_execution_policy
from claude_kit.execution_lease import (
    ManagedExecutionLeaseHeld,
    managed_execution_lease,
)
from claude_kit.models import (
    ExecutionPolicy,
    ModelChoice,
    ModelChoiceKind,
    Runtime,
    WorkerBinding,
)
from claude_kit.process_dispatch import (
    ClaudeProcessDispatcher,
    CodexProcessDispatcher,
    cleanup_codex_dispatch_credentials,
)
from claude_kit.provider_compatibility import load_agent_projection_compatibility
from claude_kit.routed_dispatch import RoutedDispatcher
from claude_kit.secure_fs import ProjectFS, UnsafePathError
from claude_kit.state import detect_state_layout
from claude_kit.worktrees import (
    WorkspaceCheckpoint,
    WorktreeError,
    WorktreeManager,
    WorktreeRecord,
    WorktreeStatus,
)

MAKER_CHECKER_SCHEMA_VERSION = 1
MAKER_ROUTE = "maker-checker-maker"
REVIEWER_ROUTE = "maker-checker-reviewer"
_MAX_TASK_BYTES = 65_536
_MAX_NESTED_OUTPUT_BYTES = 786_432
_MAX_ARTIFACT_BYTES = 524_288
_MAX_SUMMARY_BYTES = 8_192
_MAX_FINDINGS = 128
_MAX_TEXT_FIELD_BYTES = 16_384
_TRANSPORT_RETRIES = 1
_PIPELINE_SCHEMA_VERSION = 2
_SNAPSHOT_KIND = "maker-checker"
_STRICT_BLOCKING_SUBSET_POLICY = "strict-blocking-finding-subset"
_BLOCKING_SEVERITY_RANK = {"medium": 1, "high": 2, "critical": 3}
_SNAPSHOT_STAGES = frozenset(
    {"setup", "maker", "apply", "reviewer", "completed", "human-stop"}
)
_ATTEMPT_STATUSES = frozenset({"running", "succeeded", "failed", "interrupted"})
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_REQUESTED_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,127}$")
_FILTER_DRIVER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_CODE_HINT_RE = re.compile(
    r"\b(?:implement|code|coding|fix|bug|refactor|function|class|endpoint|api|test|"
    r"component|application|app|feature)\b",
    re.IGNORECASE,
)
_SPEC_HINT_RE = re.compile(
    r"\b(?:spec|specification|requirements?|acceptance criteria|prd)\b",
    re.IGNORECASE,
)
_DESIGN_HINT_RE = re.compile(
    r"\b(?:design|architecture|architectural|wireframe|mockup|user flow|system design)\b",
    re.IGNORECASE,
)
_PROTECTED_CODE_PATHS = frozenset(
    {
        "AGENTS.md",
        "CLAUDE.md",
        ".gitattributes",
        ".gitignore",
        ".claude-kit-managed-execution.lock",
        ".mcp.json",
        ".gitmodules",
    }
)
_PROTECTED_CODE_ROOTS = frozenset({".agents", ".ckit", ".claude", ".codex", ".git"})


class DeliverableKind(str, Enum):
    """Supported maker artifact contracts."""

    AUTO = "auto"
    CODE = "code"
    DESIGN = "design"
    SPECIFICATION = "specification"


class MakerCheckerStatus(str, Enum):
    """Terminal result of one bounded maker-checker invocation."""

    PASSED = "passed"
    HUMAN_STOP = "human-stop"
    FAILED = "failed"


class MakerCheckerError(RuntimeError):
    """The configured run cannot be constructed safely."""


class _ContractViolation(MakerCheckerError):
    """A native worker returned output outside the frozen contract."""


class _PatchSafetyError(MakerCheckerError):
    """A maker patch crossed the constrained code-artifact channel."""


class _CoordinatorStop(Exception):
    def __init__(self, stop: HumanStopRequest) -> None:
        super().__init__(stop.message)
        self.stop = stop


def _existing_project_fs(project_root: str | Path) -> ProjectFS:
    """Bind an existing lexical project root without following a root symlink."""

    fs = ProjectFS(Path(project_root).expanduser())
    if not fs.root.exists():
        raise FileNotFoundError(fs.root)
    return fs


@dataclass(frozen=True)
class ResolvedWorkerBinding:
    """Frozen provider/model binding used by one run."""

    provider: str
    configured_model: Mapping[str, str]
    requested_model: Optional[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "configured_model": dict(self.configured_model),
            "requested_model": self.requested_model,
        }


@dataclass(frozen=True)
class MakerCheckerResult:
    """Public terminal summary; artifact content remains in the owned project paths."""

    status: MakerCheckerStatus
    run_id: str
    kind: DeliverableKind
    iterations: int
    policy_digest: str
    binding_digest: str
    contract_digest: Optional[str]
    artifact_path: Optional[str] = None
    artifact_digest: Optional[str] = None
    workspace: Optional[str] = None
    residual_risks: tuple[str, ...] = ()
    human_stop: Optional[HumanStopRequest] = None

    def to_dict(self) -> dict[str, object]:
        """Return a stable JSON-ready public record."""

        document: dict[str, object] = {
            "schema_version": MAKER_CHECKER_SCHEMA_VERSION,
            "status": self.status.value,
            "run_id": self.run_id,
            "kind": self.kind.value,
            "iterations": self.iterations,
            "policy_digest": self.policy_digest,
            "binding_digest": self.binding_digest,
            "contract_digest": self.contract_digest,
            "artifact_path": self.artifact_path,
            "artifact_digest": self.artifact_digest,
            "workspace": self.workspace,
            "residual_risks": list(self.residual_risks),
        }
        if self.human_stop is not None:
            document["human_stop"] = {
                "reason": self.human_stop.reason.value,
                "message": self.human_stop.message,
                "requested_action": self.human_stop.requested_action,
            }
        return document


@dataclass(frozen=True)
class FrozenMakerCheckerRun:
    """Read-only preflight view used to announce a resumable frozen run."""

    run_id: str
    task: str
    kind: DeliverableKind
    stage: str
    iteration: int
    max_revisions: int
    maker: ResolvedWorkerBinding
    reviewer: ResolvedWorkerBinding


@dataclass(frozen=True)
class _Artifact:
    kind: str
    content: str
    digest: str
    path: str


@dataclass(frozen=True)
class _ReviewerVerdict:
    verdict: str
    findings: tuple[dict[str, object], ...]
    residual_risks: tuple[str, ...]
    document: dict[str, object]


def _canonical_json(document: object) -> str:
    return json.dumps(
        document,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _digest(document: object) -> str:
    return hashlib.sha256(_canonical_json(document).encode("utf-8")).hexdigest()


def _content_digest(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _bytes_digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def is_maker_checker_snapshot(document: object) -> bool:
    """Return whether a shared pipeline snapshot belongs to this coordinator."""

    return (
        isinstance(document, dict) and document.get("snapshot_kind") == _SNAPSHOT_KIND
    )


def _read_json_artifact(
    fs: ProjectFS,
    relative: str,
    *,
    maximum_bytes: int = _MAX_NESTED_OUTPUT_BYTES,
) -> tuple[dict[str, object], str]:
    if not isinstance(relative, str) or not relative:
        raise MakerCheckerError("maker-checker evidence path is missing")
    content = fs.read_bytes(relative)
    if len(content) > maximum_bytes:
        raise MakerCheckerError("maker-checker evidence exceeds its bounded size")
    try:
        document = json.loads(content.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise MakerCheckerError(
            f"maker-checker evidence {relative!r} is not valid JSON"
        ) from exc
    if not isinstance(document, dict):
        raise MakerCheckerError(
            f"maker-checker evidence {relative!r} is not a JSON object"
        )
    return cast(dict[str, object], document), _bytes_digest(content)


def _read_text_artifact(
    fs: ProjectFS,
    relative: str,
    *,
    maximum_bytes: int = _MAX_ARTIFACT_BYTES,
) -> tuple[str, str]:
    if not isinstance(relative, str) or not relative:
        raise MakerCheckerError("maker-checker artifact path is missing")
    content = fs.read_bytes(relative)
    if len(content) > maximum_bytes:
        raise MakerCheckerError("maker-checker artifact exceeds its bounded size")
    try:
        text = content.decode("utf-8")
    except UnicodeError as exc:
        raise MakerCheckerError(
            f"maker-checker artifact {relative!r} is not UTF-8 text"
        ) from exc
    return text, _bytes_digest(content)


def _binding_from_document(document: object) -> ResolvedWorkerBinding:
    if not isinstance(document, dict) or set(document) != {
        "provider",
        "configured_model",
        "requested_model",
    }:
        raise MakerCheckerError("frozen maker-checker binding is malformed")
    provider = document.get("provider")
    if provider not in {Runtime.CLAUDE.value, Runtime.CODEX.value}:
        raise MakerCheckerError("frozen maker-checker provider is unsupported")
    configured = document.get("configured_model")
    if not isinstance(configured, dict):
        raise MakerCheckerError("frozen maker-checker model choice is malformed")
    try:
        ModelChoice.from_dict(cast(dict[str, Any], configured))
    except ValueError as exc:
        raise MakerCheckerError(
            f"frozen maker-checker model choice is invalid: {exc}"
        ) from exc
    requested = document.get("requested_model")
    if requested is not None and (
        not isinstance(requested, str) or not _REQUESTED_MODEL_RE.fullmatch(requested)
    ):
        raise MakerCheckerError("frozen maker-checker requested model is malformed")
    return ResolvedWorkerBinding(
        provider=str(provider),
        configured_model=cast(dict[str, str], configured),
        requested_model=cast(Optional[str], requested),
    )


def _frozen_bindings(
    maker_checker: Mapping[str, object],
) -> dict[ExecutionSlot, ResolvedWorkerBinding]:
    raw = maker_checker.get("bindings")
    if not isinstance(raw, dict) or set(raw) != {"maker", "reviewer"}:
        raise MakerCheckerError("frozen maker-checker bindings are malformed")
    return {
        ExecutionSlot.MAKER: _binding_from_document(raw["maker"]),
        ExecutionSlot.REVIEWER: _binding_from_document(raw["reviewer"]),
    }


def _snapshot_run_rel(root: Path, run_id: str) -> str:
    return f"{detect_state_layout(root).artifacts}/maker-checker/runs/{run_id}"


def _evidence_path_problem(relative: object, *, run_rel: str) -> Optional[str]:
    if not isinstance(relative, str) or not relative:
        return "maker-checker evidence path is missing"
    path = PurePosixPath(relative)
    prefix = PurePosixPath(run_rel)
    if path.is_absolute() or ".." in path.parts or path == prefix:
        return "maker-checker evidence path is unsafe"
    try:
        path.relative_to(prefix)
    except ValueError:
        return "maker-checker evidence escaped its run-owned artifact namespace"
    return None


def _read_evidence_hash(
    fs: ProjectFS,
    relative: object,
    *,
    run_rel: str,
    maximum_bytes: int = _MAX_NESTED_OUTPUT_BYTES,
) -> tuple[Optional[bytes], Optional[str]]:
    problem = _evidence_path_problem(relative, run_rel=run_rel)
    if problem:
        return None, problem
    assert isinstance(relative, str)
    try:
        content = fs.read_bytes(relative)
    except (FileNotFoundError, OSError, UnsafePathError) as exc:
        return None, f"maker-checker evidence {relative!r} is unavailable: {exc}"
    if len(content) > maximum_bytes:
        return None, f"maker-checker evidence {relative!r} exceeds its bounded size"
    return content, None


def _workspace_binding(record: WorktreeRecord) -> dict[str, str]:
    return {
        "worker_id": record.worker_id,
        "target_path": record.target_path,
        "base_commit": record.base_commit,
    }


def _snapshot_validation_problem(
    root: Path,
    snapshot: Mapping[str, object],
    *,
    verify_current_policy: bool,
    historical_terminal: bool,
    compatibility_root: Optional[Path],
) -> Optional[str]:
    """Return the first integrity problem in a maker-checker snapshot."""

    if snapshot.get("schema_version") != _PIPELINE_SCHEMA_VERSION:
        return "maker-checker snapshot has an unsupported pipeline schema_version"
    if snapshot.get("snapshot_kind") != _SNAPSHOT_KIND:
        return "pipeline snapshot is not a maker-checker run"
    run_id = snapshot.get("run_id")
    if (
        not isinstance(run_id, str)
        or not _IDENTIFIER_RE.fullmatch(run_id)
        or ".." in run_id
    ):
        return "maker-checker snapshot has an unsafe run_id"
    if snapshot.get("repository_root") != str(root):
        return "maker-checker snapshot belongs to a different project root"
    status_value = snapshot.get("status")
    if status_value not in {"active", "completed", "aborted"}:
        return "maker-checker snapshot has an invalid status"
    stage = snapshot.get("stage")
    if stage not in _SNAPSHOT_STAGES:
        return "maker-checker snapshot has an invalid stage"
    if historical_terminal and status_value not in {"completed", "aborted"}:
        return "historical maker-checker validation requires a terminal run"
    if status_value == "active" and stage not in {
        "setup",
        "maker",
        "apply",
        "reviewer",
    }:
        return "active maker-checker snapshot has a terminal stage"
    if status_value == "completed" and stage != "completed":
        return "completed maker-checker snapshot does not have stage 'completed'"
    if status_value == "aborted" and stage != "human-stop":
        return "aborted maker-checker snapshot does not have stage 'human-stop'"
    if not isinstance(snapshot.get("task"), str) or not str(snapshot["task"]).strip():
        return "maker-checker snapshot has no task"
    if len(str(snapshot["task"]).encode("utf-8")) > _MAX_TASK_BYTES:
        return "maker-checker snapshot task exceeds its bounded size"
    try:
        selected_kind = DeliverableKind(str(snapshot.get("kind")))
    except ValueError:
        return "maker-checker snapshot has an invalid deliverable kind"
    if selected_kind is DeliverableKind.AUTO:
        return "maker-checker snapshot cannot freeze the auto deliverable kind"
    revision = snapshot.get("state_revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        return "maker-checker snapshot state_revision is invalid"

    raw_state = snapshot.get("maker_checker")
    if not isinstance(raw_state, dict):
        return "maker-checker snapshot has no maker_checker binding"
    state = cast(dict[str, object], raw_state)
    if state.get("schema_version") != MAKER_CHECKER_SCHEMA_VERSION:
        return "maker_checker binding has an unsupported schema_version"
    for field in ("policy_digest", "binding_digest"):
        if not isinstance(state.get(field), str) or not _SHA256_RE.fullmatch(
            cast(str, state.get(field))
        ):
            return f"maker_checker {field} is malformed"
    raw_policy = state.get("policy")
    if not isinstance(raw_policy, dict):
        return "frozen maker-checker policy is malformed"
    try:
        frozen_policy = ExecutionPolicy.from_dict(cast(dict[str, Any], raw_policy))
    except ValueError as exc:
        return f"frozen maker-checker policy is invalid: {exc}"
    if _digest(frozen_policy.to_dict()) != state.get("policy_digest"):
        return "frozen maker-checker policy digest mismatch"
    try:
        bindings = _frozen_bindings(state)
    except MakerCheckerError as exc:
        return str(exc)
    binding_document = {
        slot.value: binding.to_dict() for slot, binding in bindings.items()
    }
    if _digest(binding_document) != state.get("binding_digest"):
        return "frozen maker-checker binding digest mismatch"
    for slot, configured_binding in (
        (ExecutionSlot.MAKER, frozen_policy.maker),
        (ExecutionSlot.REVIEWER, frozen_policy.reviewer),
    ):
        frozen_binding = bindings[slot]
        if (
            frozen_binding.provider != configured_binding.provider.value
            or frozen_binding.configured_model != configured_binding.model.to_dict()
        ):
            return "frozen maker-checker binding differs from its policy"
        if configured_binding.model.kind is ModelChoiceKind.INHERIT:
            expected_requested: Optional[str] = None
        elif configured_binding.model.kind is ModelChoiceKind.EXACT:
            expected_requested = str(configured_binding.model.value)
        else:
            # Some native hosts intentionally map semantic tiers to their own
            # default model, represented by a frozen null requested_model.
            expected_requested = frozen_binding.requested_model
        if frozen_binding.requested_model != expected_requested:
            return "frozen maker-checker requested model differs from its policy"
    del compatibility_root
    max_revisions = state.get("max_revisions")
    if (
        not isinstance(max_revisions, int)
        or isinstance(max_revisions, bool)
        or not 0 <= max_revisions <= 3
    ):
        return "maker_checker max_revisions is invalid"
    if max_revisions != frozen_policy.max_revisions:
        return "frozen maker-checker revision budget differs from its policy"
    iteration = state.get("iteration")
    if (
        not isinstance(iteration, int)
        or isinstance(iteration, bool)
        or not 1 <= iteration <= max_revisions + 1
    ):
        return "maker_checker iteration is outside its frozen budget"

    del verify_current_policy

    run_rel = _snapshot_run_rel(root, run_id)
    fs = ProjectFS(root)
    contract_digest = state.get("contract_digest")
    contract_path = state.get("contract_path")
    contract_file_sha256 = state.get("contract_file_sha256")
    frozen_contract: Optional[dict[str, object]] = None
    pre_setup_abort = (
        status_value == "aborted"
        and contract_digest is None
        and contract_path is None
        and contract_file_sha256 is None
    )
    if stage == "setup" or pre_setup_abort:
        if any(
            value is not None
            for value in (contract_digest, contract_path, contract_file_sha256)
        ):
            return (
                "setup-stage maker-checker snapshot already contains a partial contract"
            )
    else:
        if not isinstance(contract_digest, str) or not _SHA256_RE.fullmatch(
            contract_digest
        ):
            return "maker_checker contract_digest is malformed"
        problem = _evidence_path_problem(contract_path, run_rel=run_rel)
        if problem:
            return problem
        assert isinstance(contract_path, str)
        try:
            contract_record, actual_file_sha = _read_json_artifact(fs, contract_path)
        except (MakerCheckerError, FileNotFoundError, OSError, UnsafePathError) as exc:
            return f"cannot verify frozen maker-checker contract: {exc}"
        if actual_file_sha != contract_file_sha256:
            return "frozen maker-checker contract file hash mismatch"
        if contract_record.get("run_id") != run_id:
            return "frozen maker-checker contract belongs to a different run"
        if contract_record.get("policy_digest") != state.get("policy_digest"):
            return "frozen maker-checker contract policy digest mismatch"
        if contract_record.get("binding_digest") != state.get("binding_digest"):
            return "frozen maker-checker contract binding digest mismatch"
        if contract_record.get("bindings") != state.get("bindings"):
            return "frozen maker-checker contract bindings changed"
        if contract_record.get("max_revisions") != max_revisions:
            return "frozen maker-checker contract revision budget changed"
        raw_contract = contract_record.get("contract")
        if not isinstance(raw_contract, dict):
            return "frozen maker-checker contract document is malformed"
        contract_without_digest = dict(raw_contract)
        recorded_digest = contract_without_digest.pop("digest", None)
        if (
            recorded_digest != contract_digest
            or _digest(contract_without_digest) != contract_digest
        ):
            return "frozen maker-checker contract digest mismatch"
        if raw_contract.get("objective") != snapshot.get("task"):
            return "frozen maker-checker objective differs from its snapshot"
        if raw_contract.get("kind") != selected_kind.value:
            return "frozen maker-checker deliverable kind differs from its snapshot"
        convergence_policy = raw_contract.get("convergence_policy")
        if (
            "convergence_policy" in raw_contract
            and convergence_policy != _STRICT_BLOCKING_SUBSET_POLICY
        ):
            return "frozen maker-checker convergence policy is unsupported"
        frozen_contract = cast(dict[str, object], raw_contract)

    raw_attempts = state.get("attempts")
    if not isinstance(raw_attempts, list) or any(
        not isinstance(item, dict) for item in raw_attempts
    ):
        return "maker_checker attempt ledger is malformed"
    predecessor: Optional[str] = None
    running = 0
    for sequence, raw_attempt in enumerate(raw_attempts, start=1):
        attempt = cast(dict[str, object], raw_attempt)
        attempt_id = attempt.get("attempt_id")
        if (
            not isinstance(attempt_id, str)
            or not _IDENTIFIER_RE.fullmatch(attempt_id)
            or ".." in attempt_id
        ):
            return "maker_checker attempt id is malformed"
        if (
            attempt.get("sequence") != sequence
            or attempt.get("predecessor_attempt") != predecessor
        ):
            return "maker_checker attempt predecessor chain is not contiguous"
        predecessor = attempt_id
        slot_value = attempt.get("execution_slot")
        if slot_value not in {ExecutionSlot.MAKER.value, ExecutionSlot.REVIEWER.value}:
            return "maker_checker attempt execution slot is invalid"
        slot = ExecutionSlot(str(slot_value))
        expected_binding = bindings[slot]
        expected_route = MAKER_ROUTE if slot is ExecutionSlot.MAKER else REVIEWER_ROUTE
        if (
            attempt.get("route") != expected_route
            or attempt.get("provider") != expected_binding.provider
            or attempt.get("requested_model") != expected_binding.requested_model
            or attempt.get("contract_digest") != contract_digest
        ):
            return "maker_checker attempt differs from its frozen route or binding"
        attempt_iteration = attempt.get("iteration")
        if (
            not isinstance(attempt_iteration, int)
            or isinstance(attempt_iteration, bool)
            or not 1 <= attempt_iteration <= max_revisions + 1
        ):
            return "maker_checker attempt iteration is invalid"
        attempt_status = attempt.get("status")
        if attempt_status not in _ATTEMPT_STATUSES:
            return "maker_checker attempt status is invalid"
        if attempt_status == "running":
            running += 1
        output_path = attempt.get("output_path")
        output_sha = attempt.get("output_sha256")
        if (output_path is None) != (output_sha is None):
            return "maker_checker attempt output evidence is incomplete"
        if output_path is not None:
            if attempt_status not in {"succeeded", "failed"}:
                return (
                    "only succeeded or failed maker_checker attempts may contain "
                    "output evidence"
                )
            content, problem = _read_evidence_hash(fs, output_path, run_rel=run_rel)
            if problem:
                return problem
            assert content is not None
            if _bytes_digest(content) != output_sha:
                return "maker_checker attempt output hash mismatch"
        elif attempt_status == "succeeded":
            return "successful maker_checker attempt has no output evidence"
        proof_path = attempt.get("termination_proof_path")
        proof_sha = attempt.get("termination_proof_sha256")
        proof_dispatch_id = attempt.get("termination_dispatch_id")
        proof_dispatch_attempt = attempt.get("termination_dispatch_attempt")
        if (
            len(
                {
                    proof_path is None,
                    proof_sha is None,
                    proof_dispatch_id is None,
                    proof_dispatch_attempt is None,
                }
            )
            != 1
        ):
            return "maker_checker attempt termination proof is incomplete"
        if proof_path is not None:
            if attempt_status != "interrupted":
                return "only an interrupted maker_checker attempt may cite termination proof"
            proof_bytes, problem = _read_evidence_hash(fs, proof_path, run_rel=run_rel)
            if problem:
                return problem
            assert proof_bytes is not None
            if _bytes_digest(proof_bytes) != proof_sha:
                return "maker_checker attempt termination proof hash mismatch"
            try:
                proof = json.loads(proof_bytes.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError) as exc:
                return f"maker_checker attempt termination proof is invalid: {exc}"
            if (
                not isinstance(proof, dict)
                or set(proof)
                != {
                    "schema_version",
                    "run_id",
                    "attempt_id",
                    "route",
                    "dispatch_id",
                    "dispatch_attempt",
                    "confirmation",
                    "evidence",
                    "confirmed_at",
                }
                or proof.get("schema_version") != MAKER_CHECKER_SCHEMA_VERSION
                or proof.get("run_id") != run_id
                or proof.get("attempt_id") != attempt_id
                or proof.get("route") != expected_route
                or proof.get("dispatch_id") != proof_dispatch_id
                or proof.get("dispatch_attempt") != proof_dispatch_attempt
                or proof.get("confirmation") != "operator-confirmed-terminated"
                or not isinstance(proof.get("evidence"), str)
                or not str(proof.get("evidence")).strip()
                or len(str(proof.get("evidence")).encode("utf-8"))
                > _MAX_TEXT_FIELD_BYTES
                or not isinstance(proof.get("confirmed_at"), str)
            ):
                return "maker_checker attempt termination proof is malformed"
    last_attempt = raw_attempts[-1] if raw_attempts else None
    if running > 1 or (
        running
        and (
            not isinstance(last_attempt, dict)
            or last_attempt.get("status") != "running"
        )
    ):
        return "maker_checker attempt ledger has an invalid running attempt"
    if status_value != "active" and running:
        return "terminal maker-checker snapshot retains a running attempt"
    unsafe_dispatch = state.get("unsafe_dispatch")
    if unsafe_dispatch is not None:
        if (
            not isinstance(unsafe_dispatch, dict)
            or set(unsafe_dispatch)
            != {
                "attempt_id",
                "route",
                "dispatch_id",
                "dispatch_attempt",
                "reason",
            }
            or status_value != "active"
            or not isinstance(last_attempt, dict)
            or last_attempt.get("status") != "running"
            or unsafe_dispatch.get("attempt_id") != last_attempt.get("attempt_id")
            or unsafe_dispatch.get("route") != last_attempt.get("route")
            or not isinstance(unsafe_dispatch.get("dispatch_id"), str)
            or not _IDENTIFIER_RE.fullmatch(str(unsafe_dispatch.get("dispatch_id")))
            or not isinstance(unsafe_dispatch.get("dispatch_attempt"), int)
            or isinstance(unsafe_dispatch.get("dispatch_attempt"), bool)
            or int(cast(int, unsafe_dispatch.get("dispatch_attempt"))) < 1
            or not isinstance(unsafe_dispatch.get("reason"), str)
            or not str(unsafe_dispatch.get("reason")).strip()
            or len(str(unsafe_dispatch.get("reason")).encode("utf-8"))
            > _MAX_TEXT_FIELD_BYTES
        ):
            return "maker_checker unsafe dispatch ownership record is malformed"

    raw_records = state.get("iteration_records")
    if not isinstance(raw_records, list) or any(
        not isinstance(item, dict) for item in raw_records
    ):
        return "maker_checker iteration ledger is malformed"
    parsed_reviews: list[_ReviewerVerdict] = []
    previous_finding_ids: frozenset[str] = frozenset()
    code_patches: list[str] = []
    code_artifacts: list[str] = []
    for expected_iteration, raw_record in enumerate(raw_records, start=1):
        record = cast(dict[str, object], raw_record)
        if record.get("iteration") != expected_iteration:
            return "maker_checker iteration ledger is not contiguous"
        if record.get("contract_digest") != contract_digest:
            return "maker_checker iteration contract digest mismatch"
        evidence: dict[str, bytes] = {}
        for path_field, digest_field, maximum in (
            ("maker_response_path", "maker_response_sha256", _MAX_NESTED_OUTPUT_BYTES),
            ("artifact_path", "artifact_digest", _MAX_ARTIFACT_BYTES),
            ("checks_path", "checks_sha256", _MAX_NESTED_OUTPUT_BYTES),
        ):
            content, problem = _read_evidence_hash(
                fs, record.get(path_field), run_rel=run_rel, maximum_bytes=maximum
            )
            if problem:
                return problem
            assert content is not None
            if _bytes_digest(content) != record.get(digest_field):
                return f"maker_checker iteration {expected_iteration} {path_field} hash mismatch"
            evidence[path_field] = content

        maker_attempts = [
            cast(dict[str, object], attempt)
            for attempt in raw_attempts
            if cast(dict[str, object], attempt).get("iteration") == expected_iteration
            and cast(dict[str, object], attempt).get("execution_slot")
            == ExecutionSlot.MAKER.value
            and cast(dict[str, object], attempt).get("status") == "succeeded"
        ]
        if len(maker_attempts) != 1:
            return "maker_checker iteration has no unique successful maker attempt"
        if maker_attempts[0].get("output_path") != record.get(
            "maker_response_path"
        ) or maker_attempts[0].get("output_sha256") != record.get(
            "maker_response_sha256"
        ):
            return "maker_checker maker attempt output differs from iteration evidence"
        prior_artifact_digest = (
            cast(dict[str, object], raw_records[expected_iteration - 2]).get(
                "artifact_digest"
            )
            if expected_iteration > 1
            else None
        )
        if maker_attempts[0].get("artifact_digest") != prior_artifact_digest:
            return "maker_checker maker attempt prior artifact binding mismatch"
        try:
            maker_artifact, _summary, _dispositions = _parse_maker_output(
                evidence["maker_response_path"].decode("utf-8"),
                kind=selected_kind,
                expected_finding_ids=previous_finding_ids,
            )
        except (UnicodeError, _ContractViolation) as exc:
            return f"maker_checker maker response is invalid: {exc}"
        try:
            artifact_text = evidence["artifact_path"].decode("utf-8")
        except UnicodeError as exc:
            return f"maker_checker artifact is not UTF-8: {exc}"
        if selected_kind is not DeliverableKind.CODE:
            if maker_artifact.get("content") != artifact_text:
                return "maker_checker document differs from its maker response"
        else:
            try:
                maker_paths = set(_inspect_patch(str(maker_artifact["content"]))[0])
                artifact_paths = set(_inspect_patch(artifact_text)[0])
            except _PatchSafetyError as exc:
                return f"maker_checker code evidence is invalid: {exc}"
            if not maker_paths or not maker_paths.issubset(artifact_paths):
                return "maker_checker incremental patch is not bound to its artifact"
            code_patches.append(str(maker_artifact["content"]))
            code_artifacts.append(artifact_text)

        try:
            checks = json.loads(evidence["checks_path"].decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            return f"maker_checker deterministic checks are invalid: {exc}"
        expected_check_ids = (
            ["artifact-nonempty", "git-diff-check"]
            if selected_kind is DeliverableKind.CODE
            else ["artifact-nonempty"]
        )
        if (
            not isinstance(checks, list)
            or [item.get("id") for item in checks if isinstance(item, dict)]
            != expected_check_ids
            or any(not isinstance(item, dict) for item in checks)
            or any(item.get("status") != "PASS" for item in checks)
            or cast(dict[str, object], checks[0]).get("evidence")
            != f"sha256:{record.get('artifact_digest')}"
        ):
            return "maker_checker deterministic checks are not exact passing evidence"
        if selected_kind is DeliverableKind.CODE:
            code_check = cast(dict[str, object], checks[1])
            if set(code_check) != {
                "id",
                "status",
                "command",
                "output",
            } or code_check.get("command") != ["git", "diff", "--check", "HEAD", "--"]:
                return "maker_checker code check evidence is malformed"
        elif set(cast(dict[str, object], checks[0])) != {
            "id",
            "status",
            "evidence",
        }:
            return "maker_checker document check evidence is malformed"
        verdict = record.get("verdict")
        if verdict is None:
            unreviewed_abort = status_value == "aborted" and stage == "human-stop"
            if expected_iteration != len(raw_records) or not (
                stage == "reviewer" or unreviewed_abort
            ):
                return "only the active reviewer iteration may lack a verdict"
            if (
                record.get("review_response_path") is not None
                or record.get("review_response_sha256") is not None
            ):
                return "unreviewed maker_checker iteration contains review evidence"
            if record.get("finding_ids") != [] or record.get("findings") != []:
                return "unreviewed maker_checker iteration contains findings"
        elif verdict in {"PASS", "FAIL"}:
            content, problem = _read_evidence_hash(
                fs, record.get("review_response_path"), run_rel=run_rel
            )
            if problem:
                return problem
            assert content is not None
            if _bytes_digest(content) != record.get("review_response_sha256"):
                return "maker_checker review response hash mismatch"
            if frozen_contract is None:
                return "reviewed maker_checker iteration has no frozen contract"
            try:
                parsed_review = _parse_review_output(
                    content.decode("utf-8"),
                    contract=frozen_contract,
                    artifact_digest=str(record.get("artifact_digest")),
                )
            except (UnicodeError, _ContractViolation) as exc:
                return f"maker_checker review response is invalid: {exc}"
            parsed_findings = list(parsed_review.findings)
            if parsed_review.verdict != verdict:
                return "maker_checker iteration verdict differs from review evidence"
            if record.get("findings") != parsed_findings:
                return "maker_checker iteration findings differ from review evidence"
            if record.get("finding_ids") != [
                finding["finding_id"] for finding in parsed_findings
            ]:
                return "maker_checker iteration finding ids differ from review evidence"
            reviewer_attempts = [
                cast(dict[str, object], attempt)
                for attempt in raw_attempts
                if cast(dict[str, object], attempt).get("iteration")
                == expected_iteration
                and cast(dict[str, object], attempt).get("execution_slot")
                == ExecutionSlot.REVIEWER.value
                and cast(dict[str, object], attempt).get("status") == "succeeded"
            ]
            if (
                len(reviewer_attempts) != 1
                or reviewer_attempts[0].get("artifact_digest")
                != record.get("artifact_digest")
                or reviewer_attempts[0].get("output_path")
                != record.get("review_response_path")
                or reviewer_attempts[0].get("output_sha256")
                != record.get("review_response_sha256")
            ):
                return "maker_checker reviewer attempt differs from iteration evidence"
            prior_review = parsed_reviews[-1] if parsed_reviews else None
            parsed_reviews.append(parsed_review)
            previous_finding_ids = frozenset(
                str(finding["finding_id"]) for finding in parsed_findings
            )
            if (
                verdict == "FAIL"
                and expected_iteration > 1
                and prior_review is not None
                and _strict_blocking_subset_enabled(frozen_contract)
                and not _has_strict_blocking_finding_progress(
                    prior_review.findings, parsed_review.findings
                )
            ):
                continued = (
                    expected_iteration < len(raw_records)
                    or iteration > expected_iteration
                )
                if continued:
                    return (
                        "maker_checker iteration ledger continued after a no-progress "
                        "reviewer verdict"
                    )
                raw_stop = snapshot.get("human_stop")
                if (
                    status_value != "aborted"
                    or stage != "human-stop"
                    or not isinstance(raw_stop, dict)
                    or raw_stop.get("reason")
                    != HumanStopReason.CONFLICTING_EVIDENCE.value
                ):
                    return (
                        "maker_checker no-progress reviewer verdict must terminate "
                        "with conflicting-evidence"
                    )
            if expected_iteration < len(raw_records) and verdict != "FAIL":
                return "maker_checker only FAIL may precede another iteration"
            if verdict == "PASS" and (
                status_value != "completed" or expected_iteration != len(raw_records)
            ):
                return "maker_checker reviewer PASS is not terminal"
        else:
            return "maker_checker iteration verdict is invalid"
    if len(raw_records) > max_revisions + 1:
        return "maker_checker iteration ledger exceeded its frozen budget"
    if code_patches:
        raw_workspace_binding = state.get("workspace")
        if not isinstance(raw_workspace_binding, dict) or not isinstance(
            raw_workspace_binding.get("base_commit"), str
        ):
            return "maker_checker code iteration has no frozen base commit"
        try:
            reconstructed = _reconstruct_code_artifacts(
                root,
                base_commit=str(raw_workspace_binding["base_commit"]),
                patches=code_patches,
            )
        except _PatchSafetyError as exc:
            return f"cannot reconstruct maker_checker code evidence: {exc}"
        if reconstructed != code_artifacts:
            return "maker_checker cumulative code artifacts differ from maker evidence"
    bound_success_outputs = {
        (
            ExecutionSlot.MAKER.value,
            record.get("iteration"),
            record.get("maker_response_path"),
            record.get("maker_response_sha256"),
        )
        for record in cast(list[dict[str, object]], raw_records)
    } | {
        (
            ExecutionSlot.REVIEWER.value,
            record.get("iteration"),
            record.get("review_response_path"),
            record.get("review_response_sha256"),
        )
        for record in cast(list[dict[str, object]], raw_records)
        if record.get("verdict") is not None
    }
    for attempt in cast(list[dict[str, object]], raw_attempts):
        if (
            attempt.get("status") == "succeeded"
            and (
                attempt.get("execution_slot"),
                attempt.get("iteration"),
                attempt.get("output_path"),
                attempt.get("output_sha256"),
            )
            not in bound_success_outputs
        ):
            return "successful maker_checker attempt has no bound iteration evidence"
    expected_record_counts = {
        "setup": {0},
        "maker": {iteration - 1},
        "apply": {iteration - 1},
        "reviewer": {iteration},
        "completed": {iteration},
        "human-stop": {iteration - 1, iteration},
    }
    if len(raw_records) not in expected_record_counts[stage]:
        return "maker_checker stage/iteration record cardinality is inconsistent"

    pending_apply = state.get("pending_apply")
    if stage == "apply":
        if selected_kind is not DeliverableKind.CODE or not isinstance(
            pending_apply, dict
        ):
            return "maker-checker apply stage has no code apply intent"
        expected_pending_fields = {
            "attempt_id",
            "maker_response_path",
            "maker_response_sha256",
            "patch_path",
            "patch_sha256",
            "expected_artifact_digest",
            "allowed_paths",
        }
        if set(pending_apply) != expected_pending_fields:
            return "maker-checker apply intent is malformed"
        pending_content: dict[str, bytes] = {}
        for path_field, digest_field in (
            ("maker_response_path", "maker_response_sha256"),
            ("patch_path", "patch_sha256"),
        ):
            content, problem = _read_evidence_hash(
                fs, pending_apply.get(path_field), run_rel=run_rel
            )
            if problem:
                return problem
            assert content is not None
            if _bytes_digest(content) != pending_apply.get(digest_field):
                return f"maker-checker apply intent {path_field} hash mismatch"
            pending_content[path_field] = content
        try:
            pending_maker, _summary, _dispositions = _parse_maker_output(
                pending_content["maker_response_path"].decode("utf-8"),
                kind=selected_kind,
                expected_finding_ids=previous_finding_ids,
            )
            pending_patch = pending_content["patch_path"].decode("utf-8")
        except (UnicodeError, _ContractViolation) as exc:
            return f"maker-checker apply intent maker response is invalid: {exc}"
        if pending_maker.get("content") != pending_patch:
            return "maker-checker apply patch differs from its maker response"
        if not isinstance(
            pending_apply.get("expected_artifact_digest"), str
        ) or not _SHA256_RE.fullmatch(
            cast(str, pending_apply.get("expected_artifact_digest"))
        ):
            return "maker-checker apply intent expected artifact digest is malformed"
        allowed_paths = pending_apply.get("allowed_paths")
        if (
            not isinstance(allowed_paths, list)
            or not allowed_paths
            or len(allowed_paths) != len(set(allowed_paths))
            or any(not isinstance(item, str) for item in allowed_paths)
        ):
            return "maker-checker apply intent path set is malformed"
        if (
            not raw_attempts
            or not isinstance(raw_attempts[-1], dict)
            or raw_attempts[-1].get("attempt_id") != pending_apply.get("attempt_id")
            or raw_attempts[-1].get("execution_slot") != ExecutionSlot.MAKER.value
            or raw_attempts[-1].get("status") != "running"
            or raw_attempts[-1].get("artifact_digest")
            != (
                cast(dict[str, object], raw_records[-1]).get("artifact_digest")
                if raw_records
                else None
            )
        ):
            return "maker-checker apply intent has no matching active maker attempt"
    elif pending_apply is not None:
        return "maker-checker apply intent exists outside the apply stage"

    raw_artifact = state.get("artifact")
    if raw_artifact is not None:
        if not isinstance(raw_artifact, dict) or set(raw_artifact) != {
            "kind",
            "path",
            "digest",
        }:
            return "maker_checker current artifact record is malformed"
        artifact_path = raw_artifact.get("path")
        content, problem = _read_evidence_hash(
            fs, artifact_path, run_rel=run_rel, maximum_bytes=_MAX_ARTIFACT_BYTES
        )
        if problem:
            return problem
        assert content is not None
        if _bytes_digest(content) != raw_artifact.get("digest"):
            return "maker_checker current artifact digest mismatch"
        expected_artifact_kind = (
            "unified-diff" if selected_kind is DeliverableKind.CODE else "document"
        )
        if raw_artifact.get("kind") != expected_artifact_kind:
            return "maker_checker current artifact kind is invalid"
        if raw_records:
            latest_record = cast(dict[str, object], raw_records[-1])
            if raw_artifact.get("path") != latest_record.get(
                "artifact_path"
            ) or raw_artifact.get("digest") != latest_record.get("artifact_digest"):
                return "maker_checker current artifact differs from latest iteration"
    elif stage in {"reviewer", "completed"}:
        return "maker-checker reviewer/terminal stage has no current artifact"

    raw_findings = state.get("findings")
    if not isinstance(raw_findings, list) or any(
        not isinstance(item, dict) for item in raw_findings
    ):
        return "maker_checker current findings are malformed"
    last_record = raw_records[-1] if raw_records else None
    last_fail_findings = (
        last_record.get("findings")
        if isinstance(last_record, dict) and last_record.get("verdict") == "FAIL"
        else None
    )
    if stage == "maker" and iteration > 1:
        if (
            not isinstance(last_fail_findings, list)
            or raw_findings != last_fail_findings
        ):
            return "maker_checker revision findings differ from reviewer evidence"
    elif stage == "human-stop" and raw_findings:
        if (
            not isinstance(last_fail_findings, list)
            or raw_findings != last_fail_findings
        ):
            return "maker_checker human-stop findings differ from reviewer evidence"
    elif raw_findings:
        return "maker_checker findings are inconsistent with the current stage"

    workspace = state.get("workspace")
    checkpoint = state.get("workspace_checkpoint")
    verified_record: Optional[WorktreeRecord] = None
    if selected_kind is DeliverableKind.CODE:
        if (
            (stage == "setup" or pre_setup_abort)
            and workspace is None
            and checkpoint is None
        ):
            # Validation/status/preflight are read-only.  A coordinator may
            # have durably recorded a CREATING intent before the setup-stage
            # snapshot was able to bind it; report that recovery requirement
            # without letting WorktreeManager.verify finish the mutation.
            try:
                unbound_records = WorktreeManager(root).records(run_id)
            except (OSError, ValueError, WorktreeError) as exc:
                return f"cannot inspect maker-checker worktree ownership: {exc}"
            if unbound_records:
                return (
                    "maker-checker worktree creation is incomplete; resume or abort "
                    "the run under the managed lease"
                )
        elif not isinstance(workspace, dict) or not isinstance(checkpoint, dict):
            return "code maker-checker snapshot has no owned workspace checkpoint"
        else:
            try:
                manager = WorktreeManager(root)
                worker_id = str(workspace.get("worker_id"))
                verified_record = manager.verify(run_id, worker_id)
                if _workspace_binding(verified_record) != workspace:
                    return "maker-checker worktree differs from its frozen ownership binding"
                expected_statuses = (
                    {WorktreeStatus.ACTIVE}
                    if status_value == "active"
                    else {
                        WorktreeStatus.ACTIVE,
                        WorktreeStatus.SUCCEEDED,
                        WorktreeStatus.FAILED,
                        WorktreeStatus.ABORTED,
                        WorktreeStatus.REMOVED,
                    }
                )
                if verified_record.status not in expected_statuses:
                    return "maker-checker worktree lifecycle status is inconsistent"
                frozen_checkpoint = WorkspaceCheckpoint.from_dict(
                    cast(dict[str, Any], checkpoint)
                )
                current_checkpoint = (
                    frozen_checkpoint
                    if verified_record.status is WorktreeStatus.REMOVED
                    else manager.checkpoint(run_id, worker_id)
                )
                if current_checkpoint != frozen_checkpoint:
                    if stage != "apply" or not isinstance(pending_apply, dict):
                        return (
                            "maker-checker worktree content changed after its last "
                            "frozen checkpoint"
                        )
                    try:
                        current_diff, _checks, _paths = _capture_code_artifact(
                            (root / verified_record.target_path).resolve(strict=True),
                            allowed_paths=set(
                                cast(list[str], pending_apply["allowed_paths"])
                            ),
                        )
                    except (OSError, ValueError, _PatchSafetyError) as exc:
                        return f"cannot reconcile maker-checker apply intent: {exc}"
                    if _content_digest(current_diff) != pending_apply.get(
                        "expected_artifact_digest"
                    ):
                        return (
                            "maker-checker worktree differs from both its pre-apply "
                            "checkpoint and expected post-apply artifact"
                        )
            except (OSError, ValueError, WorktreeError) as exc:
                return f"cannot verify maker-checker worktree ownership: {exc}"
    elif workspace is not None or checkpoint is not None:
        return "document maker-checker snapshot must not bind a code worktree"

    if status_value == "completed":
        if not isinstance(snapshot.get("completed_at"), str):
            return "completed maker-checker snapshot has no completion timestamp"
        last_record = raw_records[-1] if raw_records else None
        if not isinstance(last_record, dict) or last_record.get("verdict") != "PASS":
            return "completed maker-checker snapshot has no terminal reviewer PASS"
    if status_value == "aborted":
        raw_stop = snapshot.get("human_stop")
        if not isinstance(raw_stop, dict):
            return "aborted maker-checker snapshot has no typed human stop"
        if raw_stop.get("reason") not in {reason.value for reason in HumanStopReason}:
            return "maker-checker human-stop reason is invalid"
        if not isinstance(snapshot.get("aborted_at"), str):
            return "aborted maker-checker snapshot has no abort timestamp"
    result_path = snapshot.get("result_path")
    result_sha256 = snapshot.get("result_sha256")
    if status_value == "active":
        if result_path is not None or result_sha256 is not None:
            return "active maker-checker snapshot contains terminal result evidence"
    else:
        problem = _evidence_path_problem(result_path, run_rel=run_rel)
        if problem:
            return problem
        assert isinstance(result_path, str)
        try:
            result_record, result_file_sha = _read_json_artifact(fs, result_path)
        except (MakerCheckerError, FileNotFoundError, OSError, UnsafePathError) as exc:
            return f"cannot verify maker-checker terminal result: {exc}"
        if result_file_sha != result_sha256:
            return "maker-checker terminal result file hash mismatch"
        expected_result_status = (
            "passed" if status_value == "completed" else "human-stop"
        )
        expected_result_fields = {
            "schema_version",
            "status",
            "run_id",
            "kind",
            "iterations",
            "policy_digest",
            "binding_digest",
            "contract_digest",
            "artifact_path",
            "artifact_digest",
            "workspace",
            "residual_risks",
            "iteration_records",
        }
        if status_value == "aborted":
            expected_result_fields.add("human_stop")
        if set(result_record) != expected_result_fields:
            return "maker-checker terminal result fields are malformed"
        for field, expected in (
            ("schema_version", MAKER_CHECKER_SCHEMA_VERSION),
            ("run_id", run_id),
            ("status", expected_result_status),
            ("kind", selected_kind.value),
            ("iterations", iteration),
            ("policy_digest", state.get("policy_digest")),
            ("binding_digest", state.get("binding_digest")),
            ("contract_digest", contract_digest),
        ):
            if result_record.get(field) != expected:
                return f"maker-checker terminal result {field} binding mismatch"
        if isinstance(raw_artifact, dict):
            if result_record.get("artifact_path") != raw_artifact.get(
                "path"
            ) or result_record.get("artifact_digest") != raw_artifact.get("digest"):
                return "maker-checker terminal result artifact binding mismatch"
        elif (
            result_record.get("artifact_path") is not None
            or result_record.get("artifact_digest") is not None
        ):
            return "maker-checker terminal result contains an unbound artifact"
        if result_record.get("iteration_records") != raw_records:
            return "maker-checker terminal result iteration evidence mismatch"
        residual_risks = result_record.get("residual_risks")
        if not isinstance(residual_risks, list) or any(
            not isinstance(item, str) for item in residual_risks
        ):
            return "maker-checker terminal result residual risks are malformed"
        if status_value == "completed":
            if (
                not parsed_reviews
                or parsed_reviews[-1].verdict != "PASS"
                or list(parsed_reviews[-1].residual_risks) != residual_risks
            ):
                return "maker-checker terminal residual risks differ from reviewer evidence"
        elif residual_risks:
            return "aborted maker-checker result contains unbound residual risks"
        if isinstance(workspace, dict):
            raw_target = root / str(workspace["target_path"])
            expected_workspace = (
                os.path.abspath(os.fspath(raw_target))
                if selected_kind is DeliverableKind.CODE
                and verified_record is not None
                and verified_record.status is WorktreeStatus.REMOVED
                else str(raw_target.resolve(strict=True))
            )
        else:
            expected_workspace = str(root)
        if result_record.get("workspace") != expected_workspace:
            return "maker-checker terminal result workspace binding mismatch"
        if status_value == "aborted" and result_record.get(
            "human_stop"
        ) != snapshot.get("human_stop"):
            return "maker-checker terminal result human-stop binding mismatch"
        if status_value == "completed" and result_record.get("human_stop") is not None:
            return "completed maker-checker result contains a human stop"
    from claude_kit import pipeline as pipeline_state

    archive_problems = pipeline_state._run_archive_problems(
        root, snapshot.get("run_archives", [])
    )
    if archive_problems:
        return archive_problems[0]
    return None


def validate_maker_checker_snapshot(
    project_root: str | Path,
    snapshot: Optional[Mapping[str, object]] = None,
    *,
    verify_current_policy: bool = False,
    historical_terminal: bool = False,
    compatibility_root: Optional[Path] = None,
) -> tuple[bool, list[str]]:
    """Validate a maker-checker variant stored in the shared pipeline snapshot."""

    problem: Optional[str]
    try:
        root = _existing_project_fs(project_root).root
        if snapshot is None:
            from claude_kit import pipeline as pipeline_state

            loaded, error = pipeline_state._load_snapshot(root)
            if error:
                return False, [f"FAIL  {error}"]
            if loaded is None:
                return False, ["FAIL  no maker-checker pipeline snapshot exists"]
            snapshot = loaded
        assert snapshot is not None
        from claude_kit import schemas

        with ExitStack() as stack:
            schema_errors = schemas.validate_doc(
                dict(snapshot), "pipeline-snapshot", stack
            )
        if schema_errors:
            problem = "maker-checker snapshot schema invalid: " + schema_errors[0]
        else:
            problem = _snapshot_validation_problem(
                root,
                snapshot,
                verify_current_policy=verify_current_policy,
                historical_terminal=historical_terminal,
                compatibility_root=compatibility_root,
            )
    except (ModuleNotFoundError, OSError, ValueError, UnsafePathError) as exc:
        problem = f"unsafe maker-checker snapshot: {exc}"
    if problem:
        return False, [f"FAIL  {problem}"]
    rendered_snapshot = cast(Mapping[str, object], snapshot)
    return True, [
        "OK    maker-checker snapshot is coherent "
        f"(stage: {rendered_snapshot.get('stage', '?')})"
    ]


@dataclass
class _RunLedger:
    root: Path
    fs: ProjectFS
    document: dict[str, object]

    @property
    def state(self) -> dict[str, object]:
        raw = self.document["maker_checker"]
        assert isinstance(raw, dict)
        return cast(dict[str, object], raw)

    def replace(self, document: dict[str, object]) -> None:
        """Compare-and-swap one exact revision under the shared pipeline lock."""

        from claude_kit import pipeline as pipeline_state

        current_revision = self.document.get("state_revision")
        if not isinstance(current_revision, int):
            raise MakerCheckerError("maker-checker state revision is malformed")
        candidate = deepcopy(document)
        candidate["state_revision"] = current_revision + 1
        candidate["updated_at"] = _utc_now()
        path = self.fs.path(detect_state_layout(self.root).pipeline_snapshot)
        try:
            with pipeline_state._pipeline_write_lock(self.fs, path):
                current, error = pipeline_state._load_snapshot(self.root)
                if error:
                    raise MakerCheckerError(error)
                if (
                    not is_maker_checker_snapshot(current)
                    or not isinstance(current, dict)
                    or current.get("run_id") != self.document.get("run_id")
                    or current.get("state_revision") != current_revision
                ):
                    raise MakerCheckerError(
                        "shared pipeline snapshot changed concurrently; refusing to overwrite it"
                    )
                self.fs.write_text(
                    detect_state_layout(self.root).pipeline_snapshot,
                    json.dumps(candidate, ensure_ascii=False, indent=2, sort_keys=True)
                    + "\n",
                    mode=0o600,
                )
        except TimeoutError as exc:
            raise MakerCheckerError(str(exc)) from exc
        self.document = candidate

    def update(self, **changes: object) -> None:
        candidate = deepcopy(self.document)
        candidate.update(changes)
        self.replace(candidate)

    def update_state(self, **changes: object) -> None:
        candidate = deepcopy(self.document)
        raw_state = candidate["maker_checker"]
        assert isinstance(raw_state, dict)
        raw_state.update(changes)
        self.replace(candidate)

    def begin_attempt(
        self,
        *,
        slot: ExecutionSlot,
        binding: ResolvedWorkerBinding,
        iteration: int,
        artifact_digest: Optional[str],
    ) -> str:
        candidate = deepcopy(self.document)
        raw_state = candidate["maker_checker"]
        assert isinstance(raw_state, dict)
        attempts = raw_state["attempts"]
        assert isinstance(attempts, list)
        predecessor = attempts[-1].get("attempt_id") if attempts else None
        attempt_id = f"attempt-{len(attempts) + 1:04d}-{uuid.uuid4().hex[:12]}"
        attempts.append(
            {
                "attempt_id": attempt_id,
                "sequence": len(attempts) + 1,
                "predecessor_attempt": predecessor,
                "iteration": iteration,
                "execution_slot": slot.value,
                "route": MAKER_ROUTE if slot is ExecutionSlot.MAKER else REVIEWER_ROUTE,
                "provider": binding.provider,
                "requested_model": binding.requested_model,
                "contract_digest": raw_state["contract_digest"],
                "artifact_digest": artifact_digest,
                "status": "running",
                "started_at": _utc_now(),
                "ended_at": None,
                "output_path": None,
                "output_sha256": None,
                "termination_proof_path": None,
                "termination_proof_sha256": None,
                "termination_dispatch_id": None,
                "termination_dispatch_attempt": None,
            }
        )
        self.replace(candidate)
        return attempt_id

    def finish_attempt(
        self,
        attempt_id: str,
        *,
        status: str,
        output_path: Optional[str] = None,
        output_sha256: Optional[str] = None,
    ) -> None:
        if status not in _ATTEMPT_STATUSES - {"running"}:
            raise MakerCheckerError("invalid terminal maker-checker attempt status")
        candidate = deepcopy(self.document)
        raw_state = candidate["maker_checker"]
        assert isinstance(raw_state, dict)
        attempts = raw_state["attempts"]
        assert isinstance(attempts, list)
        matches = [item for item in attempts if item.get("attempt_id") == attempt_id]
        if len(matches) != 1 or matches[0].get("status") != "running":
            raise MakerCheckerError("maker-checker attempt ownership changed")
        attempt = matches[0]
        attempt["status"] = status
        attempt["ended_at"] = _utc_now()
        attempt["output_path"] = output_path
        attempt["output_sha256"] = output_sha256
        self.replace(candidate)

    def interrupt_stale_attempt(self) -> None:
        attempts = self.state.get("attempts")
        if not isinstance(attempts, list) or not attempts:
            return
        last = attempts[-1]
        if not isinstance(last, dict) or last.get("status") != "running":
            return
        self.finish_attempt(str(last.get("attempt_id")), status="interrupted")

    def record_unsafe_dispatch(
        self,
        attempt_id: str,
        *,
        route: str,
        dispatch_id: str,
        dispatch_attempt: int,
        reason: str,
    ) -> None:
        """Persist unconfirmed native ownership without claiming a terminal stop."""

        candidate = deepcopy(self.document)
        raw_state = candidate["maker_checker"]
        assert isinstance(raw_state, dict)
        attempts = raw_state.get("attempts")
        if (
            not isinstance(attempts, list)
            or not attempts
            or not isinstance(attempts[-1], dict)
            or attempts[-1].get("attempt_id") != attempt_id
            or attempts[-1].get("status") != "running"
        ):
            raise MakerCheckerError("unsafe dispatch has no matching running attempt")
        raw_state["unsafe_dispatch"] = {
            "attempt_id": attempt_id,
            "route": route,
            "dispatch_id": dispatch_id,
            "dispatch_attempt": dispatch_attempt,
            "reason": public_human_stop_text(
                reason, fallback="native dispatch termination is unconfirmed"
            ),
        }
        candidate["next"] = (
            "confirm or terminate the preserved native dispatch before resuming"
        )
        self.replace(candidate)

    def clear_unsafe_dispatch(
        self, attempt_id: str, *, dispatch_id: str, dispatch_attempt: int
    ) -> None:
        """Clear an ownership intent only after native termination is attested."""

        candidate = deepcopy(self.document)
        raw_state = candidate["maker_checker"]
        assert isinstance(raw_state, dict)
        unsafe = raw_state.get("unsafe_dispatch")
        if (
            not isinstance(unsafe, dict)
            or unsafe.get("attempt_id") != attempt_id
            or unsafe.get("dispatch_id") != dispatch_id
            or unsafe.get("dispatch_attempt") != dispatch_attempt
        ):
            raise MakerCheckerError(
                "native dispatch ownership marker changed before termination"
            )
        raw_state["unsafe_dispatch"] = None
        self.replace(candidate)


def _initial_snapshot(
    root: Path,
    *,
    run_id: str,
    task: str,
    kind: DeliverableKind,
    policy: Mapping[str, object],
    policy_digest: str,
    binding_digest: str,
    bindings: Mapping[str, object],
    max_revisions: int,
) -> dict[str, object]:
    now = _utc_now()
    return {
        "schema_version": _PIPELINE_SCHEMA_VERSION,
        "snapshot_kind": _SNAPSHOT_KIND,
        "run_id": run_id,
        "repository_root": str(root),
        "status": "active",
        "task": task,
        "kind": kind.value,
        "stage": "setup",
        "next": "freeze the contract and owned workspace",
        "created_at": now,
        "updated_at": now,
        "state_revision": 1,
        "maker_checker": {
            "schema_version": MAKER_CHECKER_SCHEMA_VERSION,
            "policy": dict(policy),
            "policy_digest": policy_digest,
            "binding_digest": binding_digest,
            "contract_digest": None,
            "contract_path": None,
            "contract_file_sha256": None,
            "bindings": dict(bindings),
            "max_revisions": max_revisions,
            "iteration": 1,
            "attempts": [],
            "iteration_records": [],
            "findings": [],
            "artifact": None,
            "pending_apply": None,
            "unsafe_dispatch": None,
            "workspace": None,
            "workspace_checkpoint": None,
        },
    }


def _create_ledger(root: Path, document: dict[str, object]) -> _RunLedger:
    """Claim the single snapshot location, archiving only a valid terminal run."""

    from claude_kit import pipeline as pipeline_state

    fs = ProjectFS(root)
    layout = detect_state_layout(root)
    path = fs.path(layout.pipeline_snapshot)
    try:
        with pipeline_state._pipeline_write_lock(fs, path):
            existing, error = pipeline_state._load_snapshot(root)
            if error:
                raise MakerCheckerError(error)
            if existing is not None:
                status_value = existing.get("status")
                if status_value not in {"completed", "aborted"}:
                    raise MakerCheckerError(
                        "an active shared pipeline snapshot already exists; resume or abort it"
                    )
                if is_maker_checker_snapshot(existing):
                    valid, messages = validate_maker_checker_snapshot(
                        root, existing, historical_terminal=True
                    )
                else:
                    valid, messages = pipeline_state.validate(
                        root, strict=True, _historical_terminal=True
                    )
                if not valid:
                    raise MakerCheckerError(
                        "existing terminal pipeline snapshot is invalid and cannot be archived: "
                        + "; ".join(messages)
                    )
                document["run_archives"] = pipeline_state._archive_terminal_snapshot(
                    existing
                )
            run_rel = _snapshot_run_rel(root, str(document["run_id"]))
            run_path = fs.path(run_rel)
            if run_path.exists() or run_path.is_symlink():
                raise MakerCheckerError(
                    f"maker-checker run artifact tree already exists for {document['run_id']!r}; "
                    "use validated resume instead of reusing a run id"
                )
            fs.write_text(
                layout.pipeline_snapshot,
                json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True)
                + "\n",
                mode=0o600,
            )
    except TimeoutError as exc:
        raise MakerCheckerError(str(exc)) from exc
    return _RunLedger(root, fs, document)


def _resume_ledger(
    root: Path,
    run_id: Optional[str],
    *,
    compatibility_root: Optional[Path],
    interrupt_stale: bool = True,
    allow_unbound_setup_worktree: bool = False,
) -> _RunLedger:
    from claude_kit import pipeline as pipeline_state

    fs = ProjectFS(root)
    document, error = pipeline_state._load_snapshot(root)
    if error:
        raise MakerCheckerError(error)
    if not is_maker_checker_snapshot(document):
        raise MakerCheckerError(
            "the shared pipeline snapshot is not a maker-checker run"
        )
    assert isinstance(document, dict)
    if document.get("status") != "active":
        raise MakerCheckerError(
            f"maker-checker run {document.get('run_id')!r} is terminal"
        )
    if run_id is not None and document.get("run_id") != _safe_run_id(run_id):
        raise MakerCheckerError(
            f"active maker-checker run is {document.get('run_id')!r}, not {run_id!r}"
        )
    valid, messages = validate_maker_checker_snapshot(
        root,
        document,
        compatibility_root=compatibility_root,
    )
    if not valid:
        recoverable_setup = (
            allow_unbound_setup_worktree
            and document.get("stage") == "setup"
            and messages
            == [
                "FAIL  maker-checker worktree creation is incomplete; resume or "
                "abort the run under the managed lease"
            ]
        )
        if not recoverable_setup:
            raise MakerCheckerError(
                "cannot resume maker-checker: " + "; ".join(messages)
            )
    ledger = _RunLedger(root, fs, cast(dict[str, object], document))
    if ledger.state.get("unsafe_dispatch") is not None:
        raise MakerCheckerError(
            "cannot resume maker-checker while native dispatch termination is unconfirmed"
        )
    if interrupt_stale and ledger.document.get("stage") != "apply":
        ledger.interrupt_stale_attempt()
    return ledger


def _bounded_text(
    value: object,
    field: str,
    *,
    maximum_bytes: int = _MAX_TEXT_FIELD_BYTES,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _ContractViolation(f"{field} must be a non-empty string")
    text = value.strip()
    if len(text.encode("utf-8")) > maximum_bytes:
        raise _ContractViolation(f"{field} exceeds its bounded size")
    return text


def _bounded_content(value: object, field: str) -> str:
    """Validate artifact payload size without changing its exact digestable bytes."""

    if not isinstance(value, str) or not value.strip():
        raise _ContractViolation(f"{field} must be a non-empty string")
    if len(value.encode("utf-8")) > _MAX_ARTIFACT_BYTES:
        raise _ContractViolation(f"{field} exceeds its bounded size")
    return value


def _exact_keys(document: Mapping[str, object], expected: set[str], field: str) -> None:
    actual = set(document)
    if actual != expected:
        missing = ", ".join(sorted(expected - actual)) or "none"
        extra = ", ".join(sorted(actual - expected)) or "none"
        raise _ContractViolation(
            f"{field} fields differ from the contract (missing={missing}; extra={extra})"
        )


def _json_object(output: Optional[str], field: str) -> dict[str, object]:
    if output is None:
        raise _ContractViolation(f"{field} output is missing")
    if len(output.encode("utf-8")) > _MAX_NESTED_OUTPUT_BYTES:
        raise _ContractViolation(f"{field} output exceeds its bounded size")
    try:
        document = json.loads(output)
    except json.JSONDecodeError as exc:
        raise _ContractViolation(f"{field} output is not valid JSON") from exc
    if not isinstance(document, dict):
        raise _ContractViolation(f"{field} output must be a JSON object")
    return document


def _string_list(
    value: object,
    field: str,
    *,
    allow_empty: bool,
) -> tuple[str, ...]:
    if not isinstance(value, list) or (not value and not allow_empty):
        qualifier = "a" if allow_empty else "a non-empty"
        raise _ContractViolation(f"{field} must be {qualifier} string array")
    if len(value) > _MAX_FINDINGS:
        raise _ContractViolation(f"{field} has too many entries")
    return tuple(
        _bounded_text(item, f"{field} item", maximum_bytes=_MAX_TEXT_FIELD_BYTES)
        for item in value
    )


def _resolve_kind(task: str, raw_kind: DeliverableKind | str) -> DeliverableKind:
    try:
        kind = (
            raw_kind
            if isinstance(raw_kind, DeliverableKind)
            else DeliverableKind(raw_kind)
        )
    except (TypeError, ValueError) as exc:
        allowed = ", ".join(item.value for item in DeliverableKind)
        raise MakerCheckerError(f"kind must be one of: {allowed}") from exc
    if kind is not DeliverableKind.AUTO:
        return kind
    matches = [
        candidate
        for candidate, pattern in (
            (DeliverableKind.CODE, _CODE_HINT_RE),
            (DeliverableKind.DESIGN, _DESIGN_HINT_RE),
            (DeliverableKind.SPECIFICATION, _SPEC_HINT_RE),
        )
        if pattern.search(task)
    ]
    if len(matches) == 1:
        return matches[0]
    raise MakerCheckerError(
        "auto could not select one unambiguous deliverable contract; rerun with "
        "--kind code, --kind design, or --kind specification"
    )


def _resolved_binding(
    binding: WorkerBinding,
    *,
    compatibility_root: Optional[Path],
) -> ResolvedWorkerBinding:
    choice = binding.model
    requested_model: Optional[str]
    if choice.kind is ModelChoiceKind.INHERIT:
        requested_model = None
    elif choice.kind is ModelChoiceKind.EXACT:
        requested_model = str(choice.value)
    else:
        tier = ModelTier(str(choice.value))
        if compatibility_root is not None:
            compatibility = load_agent_projection_compatibility(
                compatibility_root,
                binding.provider.value,  # type: ignore[arg-type]
            )
            requested_model = compatibility.model_tiers[tier]
        else:
            with ExitStack() as resources:
                payload = scaffold.payload_dir(resources)
                compatibility = load_agent_projection_compatibility(
                    payload,
                    binding.provider.value,  # type: ignore[arg-type]
                )
                requested_model = compatibility.model_tiers[tier]
    return ResolvedWorkerBinding(
        provider=binding.provider.value,
        configured_model=binding.model.to_dict(),
        requested_model=requested_model,
    )


def resolve_execution_bindings(
    policy: ExecutionPolicy,
    *,
    compatibility_root: Optional[Path] = None,
) -> dict[ExecutionSlot, ResolvedWorkerBinding]:
    """Resolve semantic model tiers at dispatch time and freeze both slots."""

    if not isinstance(policy, ExecutionPolicy):
        raise MakerCheckerError("maker-checker policy must be an ExecutionPolicy")
    return {
        ExecutionSlot.MAKER: _resolved_binding(
            policy.maker, compatibility_root=compatibility_root
        ),
        ExecutionSlot.REVIEWER: _resolved_binding(
            policy.reviewer, compatibility_root=compatibility_root
        ),
    }


def build_routed_dispatcher(
    project_root: Path,
    bindings: Mapping[ExecutionSlot, ResolvedWorkerBinding],
    *,
    allowed_workspaces: Sequence[Path] = (),
) -> RoutedDispatcher:
    """Create only the concrete native adapters named by the frozen bindings."""

    adapters: dict[str, Dispatcher] = {}
    for binding in bindings.values():
        if binding.provider not in adapters:
            if binding.provider == Runtime.CLAUDE.value:
                adapters[binding.provider] = ClaudeProcessDispatcher(
                    project_root,
                    allowed_workspaces=allowed_workspaces,
                )
            elif binding.provider == Runtime.CODEX.value:
                adapters[binding.provider] = CodexProcessDispatcher(
                    project_root,
                    allowed_workspaces=allowed_workspaces,
                )
            else:  # pragma: no cover - WorkerBinding already closes this set
                raise MakerCheckerError(
                    f"unsupported maker-checker provider: {binding.provider}"
                )
    return RoutedDispatcher(
        {slot: adapters[binding.provider] for slot, binding in bindings.items()}
    )


def _acceptance_criteria(kind: DeliverableKind) -> list[dict[str, str]]:
    kind_expectation = {
        DeliverableKind.CODE: (
            "The scoped diff implements the stated task without changing managed control-plane "
            "or external-effect surfaces."
        ),
        DeliverableKind.DESIGN: (
            "The design addresses the stated user or system goal, important states, constraints, "
            "and feasibility."
        ),
        DeliverableKind.SPECIFICATION: (
            "The specification is complete, internally consistent, scoped, and testable."
        ),
    }[kind]
    return [
        {
            "id": "criterion-1",
            "text": "The artifact satisfies the exact requested objective.",
        },
        {"id": "criterion-2", "text": kind_expectation},
        {
            "id": "criterion-3",
            "text": "All deterministic checks supplied by the coordinator are green.",
        },
    ]


def _contract(
    task: str,
    kind: DeliverableKind,
    *,
    artifact_location: str,
) -> dict[str, object]:
    core: dict[str, object] = {
        "schema_version": MAKER_CHECKER_SCHEMA_VERSION,
        "objective": task,
        "kind": kind.value,
        "acceptance_criteria": _acceptance_criteria(kind),
        "non_goals": [
            "No merge, publication, deployment, purchase, deletion, or external effect is authorized.",
            "No maker or reviewer may edit the shared .ckit control plane.",
        ],
        "allowed_read_scope": [
            "project repository excluding protected secret-bearing paths"
        ],
        "allowed_write_scope": (
            ["validated unified diff in a run-owned worktree"]
            if kind is DeliverableKind.CODE
            else [artifact_location]
        ),
        "artifact_location": artifact_location,
        "convergence_policy": _STRICT_BLOCKING_SUBSET_POLICY,
        "deterministic_checks": (
            ["artifact-nonempty", "git-diff-check"]
            if kind is DeliverableKind.CODE
            else ["artifact-nonempty"]
        ),
    }
    return {**core, "digest": _digest(core)}


def _safe_run_id(value: Optional[str]) -> str:
    run_id = value or f"mc-{uuid.uuid4().hex[:20]}"
    if not _IDENTIFIER_RE.fullmatch(run_id) or ".." in run_id:
        raise MakerCheckerError(
            "run_id must use 1-128 letters, digits, dots, underscores, or hyphens"
        )
    return run_id


def _persist_json(fs: ProjectFS, relative: str, document: object) -> None:
    with fs.mutation_lease():
        fs.write_text(
            relative,
            json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            mode=0o600,
        )


def _persist_text(fs: ProjectFS, relative: str, content: str) -> None:
    with fs.mutation_lease():
        fs.write_text(relative, content, mode=0o600)


def _persist_worker_output(fs: ProjectFS, relative: str, output: str) -> str:
    """Persist one exact bounded nested response before semantic validation."""

    if len(output.encode("utf-8")) > _MAX_NESTED_OUTPUT_BYTES:
        raise _ContractViolation("worker output exceeds its bounded size")
    _persist_text(fs, relative, output)
    return _bytes_digest(fs.read_bytes(relative))


def _parse_dispositions(
    value: object,
    *,
    expected_finding_ids: frozenset[str],
) -> tuple[dict[str, object], ...]:
    if not isinstance(value, list) or len(value) > _MAX_FINDINGS:
        raise _ContractViolation("maker finding_dispositions must be a bounded array")
    parsed: list[dict[str, object]] = []
    for index, raw in enumerate(value):
        if not isinstance(raw, dict):
            raise _ContractViolation(
                f"maker finding_dispositions[{index}] must be an object"
            )
        _exact_keys(
            raw,
            {"finding_id", "disposition", "evidence", "note"},
            f"maker finding_dispositions[{index}]",
        )
        finding_id = _bounded_text(raw["finding_id"], "maker finding_id")
        if not _IDENTIFIER_RE.fullmatch(finding_id):
            raise _ContractViolation("maker finding_id is not a safe identifier")
        disposition = _bounded_text(raw["disposition"], "maker disposition")
        if disposition not in {"fixed", "disputed", "human-required"}:
            raise _ContractViolation("maker disposition is unsupported")
        evidence = _string_list(
            raw["evidence"], "maker disposition evidence", allow_empty=False
        )
        note = _bounded_text(raw["note"], "maker disposition note")
        parsed.append(
            {
                "finding_id": finding_id,
                "disposition": disposition,
                "evidence": list(evidence),
                "note": note,
            }
        )
    ids = [str(item["finding_id"]) for item in parsed]
    if len(ids) != len(set(ids)):
        raise _ContractViolation("maker finding dispositions contain duplicate ids")
    if frozenset(ids) != expected_finding_ids:
        raise _ContractViolation(
            "maker finding dispositions do not cover the prior reviewer finding set exactly"
        )
    return tuple(parsed)


def _parse_maker_output(
    output: Optional[str],
    *,
    kind: DeliverableKind,
    expected_finding_ids: frozenset[str],
) -> tuple[dict[str, object], str, tuple[dict[str, object], ...]]:
    document = _json_object(output, "maker")
    _exact_keys(
        document,
        {"schema_version", "artifact", "summary", "finding_dispositions"},
        "maker output",
    )
    if document["schema_version"] != MAKER_CHECKER_SCHEMA_VERSION:
        raise _ContractViolation("maker output has an unsupported schema_version")
    summary = _bounded_text(
        document["summary"], "maker summary", maximum_bytes=_MAX_SUMMARY_BYTES
    )
    raw_artifact = document["artifact"]
    if not isinstance(raw_artifact, dict):
        raise _ContractViolation("maker artifact must be an object")
    _exact_keys(raw_artifact, {"kind", "content"}, "maker artifact")
    expected_kind = "unified-diff" if kind is DeliverableKind.CODE else "document"
    if raw_artifact["kind"] != expected_kind:
        raise _ContractViolation(
            f"maker artifact kind must be {expected_kind!r} for {kind.value}"
        )
    content = _bounded_content(raw_artifact["content"], "maker artifact content")
    dispositions = _parse_dispositions(
        document["finding_dispositions"],
        expected_finding_ids=expected_finding_ids,
    )
    return ({"kind": expected_kind, "content": content}, summary, dispositions)


def _parse_findings(value: object) -> tuple[dict[str, object], ...]:
    if not isinstance(value, list) or len(value) > _MAX_FINDINGS:
        raise _ContractViolation("reviewer findings must be a bounded array")
    findings: list[dict[str, object]] = []
    for index, raw in enumerate(value):
        if not isinstance(raw, dict):
            raise _ContractViolation(f"reviewer findings[{index}] must be an object")
        _exact_keys(
            raw,
            {"finding_id", "severity", "message", "evidence"},
            f"reviewer findings[{index}]",
        )
        finding_id = _bounded_text(raw["finding_id"], "reviewer finding_id")
        if not _IDENTIFIER_RE.fullmatch(finding_id):
            raise _ContractViolation("reviewer finding_id is not a safe identifier")
        severity = _bounded_text(raw["severity"], "reviewer finding severity")
        if severity not in {"critical", "high", "medium", "low", "info"}:
            raise _ContractViolation("reviewer finding severity is unsupported")
        findings.append(
            {
                "finding_id": finding_id,
                "severity": severity,
                "message": _bounded_text(raw["message"], "reviewer finding message"),
                "evidence": list(
                    _string_list(
                        raw["evidence"],
                        "reviewer finding evidence",
                        allow_empty=False,
                    )
                ),
            }
        )
    ids = [str(item["finding_id"]) for item in findings]
    if len(ids) != len(set(ids)):
        raise _ContractViolation("reviewer findings contain duplicate ids")
    return tuple(findings)


def _strict_blocking_subset_enabled(contract: Mapping[str, object]) -> bool:
    return contract.get("convergence_policy") == _STRICT_BLOCKING_SUBSET_POLICY


def _blocking_findings_by_id(
    findings: Sequence[Mapping[str, object]],
) -> dict[str, str]:
    return {
        str(finding["finding_id"]): str(finding["severity"])
        for finding in findings
        if finding.get("severity") in _BLOCKING_SEVERITY_RANK
    }


def _has_strict_blocking_finding_progress(
    prior_findings: Sequence[Mapping[str, object]],
    current_findings: Sequence[Mapping[str, object]],
) -> bool:
    """Return whether one revised FAIL strictly reduced its frozen blockers."""

    prior = _blocking_findings_by_id(prior_findings)
    current = _blocking_findings_by_id(current_findings)
    if not current.keys() < prior.keys():
        return False
    return all(
        _BLOCKING_SEVERITY_RANK[current[finding_id]]
        <= _BLOCKING_SEVERITY_RANK[prior[finding_id]]
        for finding_id in current
    )


def _compact_finding_registry(
    findings: Sequence[Mapping[str, object]],
) -> list[dict[str, str]]:
    return [
        {
            "finding_id": str(finding["finding_id"]),
            "severity": str(finding["severity"]),
            "message": str(finding["message"]),
        }
        for finding in findings
    ]


def _parse_review_output(
    output: Optional[str],
    *,
    contract: Mapping[str, object],
    artifact_digest: str,
) -> _ReviewerVerdict:
    document = _json_object(output, "reviewer")
    _exact_keys(
        document,
        {
            "schema_version",
            "verdict",
            "contract_digest",
            "artifact_digest",
            "criteria",
            "findings",
            "residual_risks",
        },
        "reviewer output",
    )
    if document["schema_version"] != MAKER_CHECKER_SCHEMA_VERSION:
        raise _ContractViolation("reviewer output has an unsupported schema_version")
    if document["contract_digest"] != contract["digest"]:
        raise _ContractViolation("reviewer returned a stale contract digest")
    if document["artifact_digest"] != artifact_digest:
        raise _ContractViolation("reviewer returned a stale artifact digest")
    verdict = _bounded_text(document["verdict"], "reviewer verdict")
    if verdict not in {"PASS", "FAIL"}:
        raise _ContractViolation("reviewer verdict must be PASS or FAIL")

    raw_criteria = document["criteria"]
    if not isinstance(raw_criteria, list):
        raise _ContractViolation("reviewer criteria must be an array")
    contract_criteria = cast(
        Sequence[Mapping[str, object]], contract["acceptance_criteria"]
    )
    expected = {str(item["id"]) for item in contract_criteria}
    criteria_status: dict[str, str] = {}
    for index, raw in enumerate(raw_criteria):
        if not isinstance(raw, dict):
            raise _ContractViolation(f"reviewer criteria[{index}] must be an object")
        _exact_keys(
            raw,
            {"criterion_id", "status", "evidence"},
            f"reviewer criteria[{index}]",
        )
        criterion_id = _bounded_text(raw["criterion_id"], "reviewer criterion_id")
        status_value = _bounded_text(raw["status"], "reviewer criterion status")
        if status_value not in {"PASS", "FAIL"}:
            raise _ContractViolation("reviewer criterion status must be PASS or FAIL")
        _string_list(raw["evidence"], "reviewer criterion evidence", allow_empty=False)
        if criterion_id in criteria_status:
            raise _ContractViolation("reviewer returned duplicate criterion coverage")
        criteria_status[criterion_id] = status_value
    if set(criteria_status) != expected:
        raise _ContractViolation(
            "reviewer criteria do not cover the frozen acceptance criteria exactly"
        )
    findings = _parse_findings(document["findings"])
    blocking = tuple(
        finding
        for finding in findings
        if finding["severity"] in {"critical", "high", "medium"}
    )
    failed_criteria = tuple(
        criterion_id
        for criterion_id, status_value in criteria_status.items()
        if status_value == "FAIL"
    )
    if verdict == "PASS" and (blocking or failed_criteria):
        raise _ContractViolation(
            "reviewer PASS is illegal with blocking findings or failed criteria"
        )
    if verdict == "FAIL" and (not findings or not failed_criteria):
        raise _ContractViolation(
            "reviewer FAIL requires cited findings and at least one failed criterion"
        )
    if verdict == "FAIL" and _strict_blocking_subset_enabled(contract) and not blocking:
        raise _ContractViolation(
            "reviewer FAIL under strict convergence requires a blocking finding"
        )
    raw_risks = _string_list(
        document["residual_risks"], "reviewer residual_risks", allow_empty=True
    )
    # The complete provider response remains mode-0600 evidence. Only bounded,
    # redacted summaries cross the public result/CLI boundary. Preserve every
    # non-blocking PASS finding there so a reviewer concern cannot disappear.
    risks = tuple(
        dict.fromkeys(
            public_human_stop_text(risk, fallback="reviewer reported a residual risk")
            for risk in (
                *raw_risks,
                *(
                    f"{finding['finding_id']} [{finding['severity']}]: "
                    f"{finding['message']}"
                    for finding in findings
                    if finding["severity"] in {"low", "info"}
                ),
            )
        )
    )
    return _ReviewerVerdict(verdict, findings, risks, document)


def _safe_patch_path(raw: str) -> str:
    if (
        not raw
        or raw.startswith(("/", "-"))
        or "\\" in raw
        or len(raw.encode("utf-8")) > 4_096
    ):
        raise _PatchSafetyError("patch contains an unsafe path")
    path = PurePosixPath(raw)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise _PatchSafetyError("patch path escapes its owned worktree")
    protected_files = {item.casefold() for item in _PROTECTED_CODE_PATHS}
    protected_roots = {item.casefold() for item in _PROTECTED_CODE_ROOTS}
    folded_parts = {part.casefold() for part in path.parts}
    if folded_parts & (protected_files | protected_roots):
        raise _PatchSafetyError(f"patch targets protected managed path {raw!r}")
    return raw


def _inspect_patch(patch: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if not patch.endswith("\n"):
        raise _PatchSafetyError("unified diff must end with a newline")
    forbidden_prefixes = (
        "GIT binary patch",
        "Binary files ",
        "rename from ",
        "rename to ",
        "copy from ",
        "copy to ",
        "similarity index ",
        "dissimilarity index ",
        "old mode ",
        "new mode ",
        "deleted file mode ",
    )
    paths: list[str] = []
    new_paths: list[str] = []
    current_path: Optional[str] = None
    old_header: Optional[str] = None
    new_header: Optional[str] = None
    in_hunk = False

    def finish_section() -> None:
        if current_path is None:
            return
        if old_header is None or new_header is None:
            raise _PatchSafetyError(
                "every patch section requires exact ---/+++ headers"
            )
        if new_header != f"b/{current_path}":
            raise _PatchSafetyError("patch +++ header differs from its diff --git path")
        if old_header == "/dev/null":
            new_paths.append(current_path)
        elif old_header != f"a/{current_path}":
            raise _PatchSafetyError("patch --- header differs from its diff --git path")

    for line in patch.splitlines():
        if line.startswith(forbidden_prefixes):
            raise _PatchSafetyError(
                "patch contains binary, rename, deletion, or mode-change metadata"
            )
        if line.startswith("new file mode ") and line != "new file mode 100644":
            raise _PatchSafetyError("new files must be regular non-executable files")
        if line.startswith("diff --git "):
            finish_section()
            parts = line.split(" ")
            if (
                len(parts) != 4
                or not parts[2].startswith("a/")
                or not parts[3].startswith("b/")
            ):
                raise _PatchSafetyError(
                    "patch paths must be unquoted, space-free git paths"
                )
            left = _safe_patch_path(parts[2][2:])
            right = _safe_patch_path(parts[3][2:])
            if left != right:
                raise _PatchSafetyError("patch rename/copy paths are forbidden")
            paths.append(left)
            current_path = left
            old_header = None
            new_header = None
            in_hunk = False
        elif current_path is not None and line.startswith("@@"):
            if old_header is None or new_header is None:
                raise _PatchSafetyError("patch hunk precedes its exact path headers")
            in_hunk = True
        elif current_path is not None and not in_hunk and line.startswith("--- "):
            if old_header is not None:
                raise _PatchSafetyError("patch section contains duplicate --- headers")
            value = line[4:]
            if value == "/dev/null":
                old_header = value
            elif value == f"a/{current_path}":
                _safe_patch_path(value[2:])
                old_header = value
            else:
                raise _PatchSafetyError(
                    "patch --- header must be canonical, unquoted, and match diff --git"
                )
        elif current_path is not None and not in_hunk and line.startswith("+++ "):
            if new_header is not None:
                raise _PatchSafetyError("patch section contains duplicate +++ headers")
            value = line[4:]
            if value.startswith("/dev/null"):
                raise _PatchSafetyError(
                    "patch file deletion requires an explicit human decision"
                )
            if value != f"b/{current_path}":
                raise _PatchSafetyError(
                    "patch +++ header must be canonical, unquoted, and match diff --git"
                )
            _safe_patch_path(value[2:])
            new_header = value
    finish_section()
    if not paths or len(paths) != len(set(paths)):
        raise _PatchSafetyError("patch must contain unique same-path git diff sections")
    return tuple(paths), tuple(new_paths)


def _run_git(
    workspace: Path,
    args: Sequence[str],
    *,
    input_text: Optional[str] = None,
) -> subprocess.CompletedProcess[str]:
    environment = {
        name: value
        for name, value in os.environ.items()
        if not name.upper().startswith("GIT_")
    }
    try:
        with tempfile.TemporaryDirectory(prefix="ckit-empty-hooks-") as hooks:
            return subprocess.run(
                [
                    "git",
                    "--no-pager",
                    "-C",
                    str(workspace),
                    "-c",
                    "core.fsmonitor=false",
                    "-c",
                    f"core.hooksPath={hooks}",
                    *args,
                ],
                input=input_text,
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
                env=environment,
            )
    except (OSError, subprocess.SubprocessError) as exc:
        raise _PatchSafetyError(f"cannot verify the constrained patch: {exc}") from exc


def _run_git_with_env(
    workspace: Path,
    args: Sequence[str],
    *,
    environment: Mapping[str, str],
    input_text: Optional[str] = None,
) -> subprocess.CompletedProcess[str]:
    run_environment = {
        name: value
        for name, value in environment.items()
        if not name.upper().startswith("GIT_")
    }
    if "GIT_INDEX_FILE" in environment:
        run_environment["GIT_INDEX_FILE"] = environment["GIT_INDEX_FILE"]
    try:
        with tempfile.TemporaryDirectory(prefix="ckit-empty-hooks-") as hooks:
            return subprocess.run(
                [
                    "git",
                    "--no-pager",
                    "-C",
                    str(workspace),
                    "-c",
                    "core.fsmonitor=false",
                    "-c",
                    f"core.hooksPath={hooks}",
                    *args,
                ],
                input=input_text,
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
                env=run_environment,
            )
    except (OSError, subprocess.SubprocessError) as exc:
        raise _PatchSafetyError(f"cannot verify the constrained patch: {exc}") from exc


def _filter_neutral_git_args(
    workspace: Path,
    paths: Sequence[str],
    command: Sequence[str],
) -> tuple[str, ...]:
    """Disable repository-defined content filters for exact patch target paths."""

    attributes = _run_git(
        workspace,
        ("-c", "core.fsmonitor=false", "check-attr", "-z", "--stdin", "filter"),
        input_text="".join(f"{path}\0" for path in paths),
    )
    if attributes.returncode != 0:
        raise _PatchSafetyError("git could not inspect patch content-filter attributes")
    fields = [field for field in attributes.stdout.split("\0") if field]
    if len(fields) % 3:
        raise _PatchSafetyError("git returned malformed content-filter attributes")
    drivers: set[str] = set()
    seen_paths: list[str] = []
    for index in range(0, len(fields), 3):
        path, attribute, value = fields[index : index + 3]
        if attribute != "filter":
            raise _PatchSafetyError("git returned unexpected patch attributes")
        seen_paths.append(path)
        if value not in {"unspecified", "unset"}:
            if not _FILTER_DRIVER_RE.fullmatch(value):
                raise _PatchSafetyError(
                    "patch uses an unsafe content-filter driver name"
                )
            drivers.add(value)
    if seen_paths != list(paths):
        raise _PatchSafetyError(
            "git patch attribute paths differ from canonical headers"
        )
    args: list[str] = ["-c", "core.fsmonitor=false"]
    for driver in sorted(drivers):
        args.extend(
            (
                "-c",
                f"filter.{driver}.clean=",
                "-c",
                f"filter.{driver}.smudge=",
                "-c",
                f"filter.{driver}.process=",
                "-c",
                f"filter.{driver}.required=false",
            )
        )
    args.extend(command)
    return tuple(args)


def _assert_patch_target_ancestors(workspace: Path, paths: Sequence[str]) -> None:
    """Reject redirectable or gitlink ancestors before any patch can mutate them."""

    ancestors: set[str] = set()
    for relative in paths:
        cursor = workspace
        parts = PurePosixPath(relative).parts
        for index, part in enumerate(parts[:-1], start=1):
            cursor /= part
            ancestor = PurePosixPath(*parts[:index]).as_posix()
            ancestors.add(ancestor)
            if cursor.exists() or cursor.is_symlink():
                info = cursor.lstat()
                if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                    raise _PatchSafetyError(
                        f"patch target has a redirectable or non-directory ancestor: {ancestor!r}"
                    )
    indexed_boundaries = ancestors | set(paths)
    indexed = _run_git(
        workspace,
        ("ls-files", "--stage", "-z", "--", *sorted(indexed_boundaries)),
    )
    if indexed.returncode != 0:
        raise _PatchSafetyError("git could not verify patch target ancestors")
    for record in indexed.stdout.split("\0"):
        if not record:
            continue
        try:
            metadata, relative = record.split("\t", 1)
            mode = metadata.split(" ", 1)[0]
        except ValueError as exc:
            raise _PatchSafetyError(
                "git returned malformed patch ancestor evidence"
            ) from exc
        if relative in indexed_boundaries and mode in {"120000", "160000"}:
            kind = "symlink" if mode == "120000" else "gitlink"
            if relative in paths:
                raise _PatchSafetyError(f"patch target is indexed {kind} {relative!r}")
            raise _PatchSafetyError(
                f"patch target is nested below indexed {kind} {relative!r}"
            )


def _assert_new_paths_visible(workspace: Path, new_paths: Sequence[str]) -> None:
    """Reject ignored additions before apply so no invisible file can be left behind."""

    if not new_paths:
        return
    ignored = _run_git(
        workspace,
        ("check-ignore", "--no-index", "--stdin", "-z"),
        input_text="".join(f"{path}\0" for path in new_paths),
    )
    if ignored.returncode not in {0, 1}:
        raise _PatchSafetyError("git could not verify new patch path visibility")
    if ignored.stdout:
        rendered = ", ".join(path for path in ignored.stdout.split("\0") if path)
        raise _PatchSafetyError(
            "patch would create ignored path outside cumulative diff evidence: "
            + rendered
        )


def _assert_no_untracked_or_ignored_paths(workspace: Path) -> None:
    """Require every owned-worktree path to be represented by the git index."""

    unexpected: list[str] = []
    for args in (
        ("ls-files", "--others", "--exclude-standard", "-z"),
        ("ls-files", "--others", "--ignored", "--exclude-standard", "-z"),
    ):
        result = _run_git(workspace, args)
        if result.returncode != 0:
            raise _PatchSafetyError(
                "git could not verify owned-worktree path visibility"
            )
        unexpected.extend(path for path in result.stdout.split("\0") if path)
    if unexpected:
        raise _PatchSafetyError(
            "owned worktree contains untracked or ignored paths outside durable "
            "patch evidence: " + ", ".join(sorted(set(unexpected)))
        )


def _head_tree_entries(workspace: Path) -> dict[str, tuple[str, str]]:
    result = _run_git(workspace, ("ls-tree", "-r", "-z", "--full-tree", "HEAD"))
    if result.returncode != 0:
        raise _PatchSafetyError("git could not verify the HEAD tree")
    entries: dict[str, tuple[str, str]] = {}
    for record in result.stdout.split("\0"):
        if not record:
            continue
        try:
            metadata, path = record.split("\t", 1)
            mode, _kind, object_id = metadata.split(" ", 2)
        except ValueError as exc:
            raise _PatchSafetyError(
                "git returned malformed HEAD tree evidence"
            ) from exc
        if path in entries:
            raise _PatchSafetyError("git returned duplicate HEAD tree paths")
        entries[path] = (mode, object_id)
    return entries


def _assert_canonical_patch_index(
    workspace: Path, *, intended_new_paths: Sequence[str]
) -> None:
    """Bind recovery to a clean HEAD index plus intentional-add entries only."""

    head_entries = _head_tree_entries(workspace)
    current = _run_git(workspace, ("ls-files", "--stage", "-z"))
    flags = _run_git(workspace, ("ls-files", "-v", "-z"))
    empty_blob = _run_git(
        workspace, ("hash-object", "-t", "blob", "--stdin"), input_text=""
    )
    if any(result.returncode != 0 for result in (current, flags, empty_blob)):
        raise _PatchSafetyError("git could not verify the owned-worktree index")
    empty_oid = empty_blob.stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", empty_oid):
        raise _PatchSafetyError("git returned an invalid empty-blob identity")

    expected = {
        path: (mode, object_id, "0") for path, (mode, object_id) in head_entries.items()
    }

    for path in intended_new_paths:
        if path in expected:
            raise _PatchSafetyError(
                f"new-file patch path already exists in HEAD: {path!r}"
            )
        expected[path] = ("100644", empty_oid, "0")

    observed: dict[str, tuple[str, str, str]] = {}
    for record in current.stdout.split("\0"):
        if not record:
            continue
        try:
            metadata, path = record.split("\t", 1)
            mode, object_id, stage = metadata.split(" ", 2)
        except ValueError as exc:
            raise _PatchSafetyError("git returned malformed index evidence") from exc
        if path in observed:
            raise _PatchSafetyError("git returned duplicate index paths")
        observed[path] = (mode, object_id, stage)
    if observed != expected:
        raise _PatchSafetyError(
            "owned-worktree index differs from clean HEAD plus intentional additions"
        )
    flagged_paths: set[str] = set()
    for record in flags.stdout.split("\0"):
        if not record:
            continue
        if not record.startswith("H "):
            raise _PatchSafetyError(
                "owned-worktree index contains non-canonical visibility flags"
            )
        flagged_paths.add(record[2:])
    if flagged_paths != set(observed):
        raise _PatchSafetyError("git returned inconsistent index visibility evidence")


def _worktree_object_ids(
    workspace: Path,
    *,
    head_entries: Mapping[str, tuple[str, str]],
    new_paths: set[str],
) -> dict[str, str]:
    """Hash exact visible bytes without consulting repository filter commands."""

    regular_paths: list[str] = []
    object_ids: dict[str, str] = {}
    for relative in sorted(set(head_entries) | new_paths):
        if "\n" in relative or "\r" in relative:
            raise _PatchSafetyError(
                "workspace paths containing newlines are unsupported"
            )
        expected_mode, expected_object_id = head_entries.get(relative, ("100644", ""))
        if expected_mode == "160000":
            if relative in new_paths:
                raise _PatchSafetyError(
                    f"new patch path cannot be an indexed gitlink: {relative!r}"
                )
            # Preserve the immutable HEAD gitlink entry without opening an
            # initialized submodule checkout or requiring one to exist.
            object_ids[relative] = expected_object_id
            continue
        candidate = workspace / relative
        try:
            info = candidate.lstat()
        except FileNotFoundError as exc:
            raise _PatchSafetyError(
                f"owned-worktree path is missing: {relative!r}"
            ) from exc
        if expected_mode == "120000":
            if not stat.S_ISLNK(info.st_mode):
                raise _PatchSafetyError(
                    f"owned-worktree symlink changed type: {relative!r}"
                )
            hashed = _run_git(
                workspace,
                ("hash-object", "--stdin"),
                input_text=os.readlink(candidate),
            )
            if hashed.returncode != 0:
                raise _PatchSafetyError("git could not hash a tracked symlink")
            object_ids[relative] = hashed.stdout.strip()
            continue
        if expected_mode not in {"100644", "100755"}:
            raise _PatchSafetyError(
                f"owned-worktree index contains unsupported mode {expected_mode!r}"
            )
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise _PatchSafetyError(
                f"owned-worktree path is not a regular file: {relative!r}"
            )
        executable = bool(info.st_mode & stat.S_IXUSR)
        if executable != (expected_mode == "100755"):
            raise _PatchSafetyError(
                f"owned-worktree file mode changed outside patch evidence: {relative!r}"
            )
        regular_paths.append(relative)

    if regular_paths:
        hashed = _run_git(
            workspace,
            ("hash-object", "--no-filters", "--stdin-paths"),
            input_text="".join(f"./{path}\n" for path in regular_paths),
        )
        identities = hashed.stdout.splitlines()
        if hashed.returncode != 0 or len(identities) != len(regular_paths):
            raise _PatchSafetyError(
                "git could not hash owned-worktree files without filters"
            )
        object_ids.update(dict(zip(regular_paths, identities)))
    if any(
        not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", object_id)
        for object_id in object_ids.values()
    ):
        raise _PatchSafetyError("git returned malformed worktree object identities")
    return object_ids


def _persist_worktree_object(
    workspace: Path, *, path: str, mode: str, expected_object_id: str
) -> None:
    """Write one already-authorized visible object and attest its identity."""

    if mode == "160000":
        return
    if mode == "120000":
        hashed = _run_git(
            workspace,
            ("hash-object", "-w", "--stdin"),
            input_text=os.readlink(workspace / path),
        )
        identities = [hashed.stdout.strip()]
    else:
        hashed = _run_git(
            workspace,
            ("hash-object", "-w", "--no-filters", "--stdin-paths"),
            input_text=f"./{path}\n",
        )
        identities = hashed.stdout.splitlines()
    if (
        hashed.returncode != 0
        or identities != [expected_object_id]
        or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", expected_object_id)
    ):
        raise _PatchSafetyError(
            "git could not persist an authorized artifact object without filters"
        )


def _populate_no_filter_index(
    workspace: Path,
    *,
    environment: Mapping[str, str],
    allowed_paths: set[str],
) -> None:
    """Build HEAD plus exact allowed visible bytes without clean/smudge filters."""

    _assert_no_untracked_or_ignored_paths(workspace)
    head_entries = _head_tree_entries(workspace)
    new_paths = allowed_paths - set(head_entries)
    _assert_canonical_patch_index(workspace, intended_new_paths=sorted(new_paths))
    object_ids = _worktree_object_ids(
        workspace,
        head_entries=head_entries,
        new_paths=new_paths,
    )
    changed_outside_scope = sorted(
        path
        for path, (_mode, head_object_id) in head_entries.items()
        if path not in allowed_paths and object_ids[path] != head_object_id
    )
    if changed_outside_scope:
        raise _PatchSafetyError(
            "owned worktree changed outside the frozen maker path set: "
            + ", ".join(changed_outside_scope)
        )
    initialized = _run_git_with_env(
        workspace, ("read-tree", "HEAD"), environment=environment
    )
    if initialized.returncode != 0:
        raise _PatchSafetyError("cannot construct an isolated artifact index")
    for path in sorted(allowed_paths):
        mode = head_entries.get(path, ("100644", ""))[0]
        if object_ids[path] != head_entries.get(path, (mode, ""))[1]:
            _persist_worktree_object(
                workspace,
                path=path,
                mode=mode,
                expected_object_id=object_ids[path],
            )
        updated = _run_git_with_env(
            workspace,
            ("update-index", "--add", "--cacheinfo", mode, object_ids[path], path),
            environment=environment,
        )
        if updated.returncode != 0:
            raise _PatchSafetyError(
                "cannot bind visible artifact bytes in the isolated index"
            )


def _assert_clean_owned_worktree(workspace: Path) -> None:
    """Verify a recovered pre-binding worktree equals HEAD without filters."""

    _assert_no_untracked_or_ignored_paths(workspace)
    head_entries = _head_tree_entries(workspace)
    _assert_canonical_patch_index(workspace, intended_new_paths=())
    object_ids = _worktree_object_ids(
        workspace,
        head_entries=head_entries,
        new_paths=set(),
    )
    changed = sorted(
        path
        for path, (_mode, head_object_id) in head_entries.items()
        if object_ids[path] != head_object_id
    )
    if changed:
        raise _PatchSafetyError(
            "recovered setup worktree differs from clean HEAD: " + ", ".join(changed)
        )


def _capture_code_artifact(
    workspace: Path,
    *,
    allowed_paths: set[str],
) -> tuple[str, tuple[dict[str, object], ...], set[str]]:
    if not allowed_paths:
        raise _PatchSafetyError("code artifact path set is empty")
    descriptor, index_name = tempfile.mkstemp(prefix="ckit-maker-checker-index-")
    os.close(descriptor)
    index_path = Path(index_name)
    index_path.unlink()
    environment = {**os.environ, "GIT_INDEX_FILE": str(index_path)}
    try:
        _populate_no_filter_index(
            workspace,
            environment=environment,
            allowed_paths=allowed_paths,
        )
        diff_result = _run_git_with_env(
            workspace,
            (
                "diff",
                "--cached",
                "--no-ext-diff",
                "--no-textconv",
                "--no-renames",
                "--full-index",
                "HEAD",
                "--",
            ),
            environment=environment,
        )
        check_result = _run_git_with_env(
            workspace,
            (
                "diff",
                "--cached",
                "--no-ext-diff",
                "--no-textconv",
                "--check",
                "HEAD",
                "--",
            ),
            environment=environment,
        )
    finally:
        index_path.unlink(missing_ok=True)
        index_path.with_name(index_path.name + ".lock").unlink(missing_ok=True)
    if diff_result.returncode != 0:
        raise _PatchSafetyError("cannot capture the resulting owned-worktree diff")
    diff = diff_result.stdout
    if not diff.strip() or len(diff.encode("utf-8")) > _MAX_ARTIFACT_BYTES:
        raise _PatchSafetyError("resulting code artifact is empty or exceeds its bound")
    actual_paths, _new_paths = _inspect_patch(diff)
    if set(actual_paths) != allowed_paths:
        raise _PatchSafetyError(
            "owned worktree differs from the exact frozen maker path set"
        )
    frozen_paths = set(actual_paths)
    for relative in actual_paths:
        info = (workspace / relative).lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise _PatchSafetyError(
                f"resulting code artifact contains a non-regular path: {relative!r}"
            )
    checks: tuple[dict[str, object], ...] = (
        {
            "id": "artifact-nonempty",
            "status": "PASS",
            "evidence": f"sha256:{_content_digest(diff)}",
        },
        {
            "id": "git-diff-check",
            "status": "PASS" if check_result.returncode == 0 else "FAIL",
            "command": ["git", "diff", "--check", "HEAD", "--"],
            "output": check_result.stdout[-8_192:] + check_result.stderr[-8_192:],
        },
    )
    if check_result.returncode != 0:
        raise _PatchSafetyError("git diff --check rejected the resulting code artifact")
    return diff, checks, frozen_paths


def _expected_cumulative_diff(
    workspace: Path,
    patch: str,
    *,
    allowed_paths: set[str],
) -> tuple[str, set[str]]:
    """Compute the exact post-apply HEAD diff without changing the owned worktree."""

    paths, new_paths = _inspect_patch(patch)
    _assert_patch_target_ancestors(workspace, paths)
    _assert_new_paths_visible(workspace, new_paths)
    if allowed_paths and not set(paths).issubset(allowed_paths):
        expanded = sorted(set(paths) - allowed_paths)
        raise _PatchSafetyError(
            "code revision expands the frozen initial path set: " + ", ".join(expanded)
        )
    frozen_paths = allowed_paths or set(paths)
    descriptor, index_name = tempfile.mkstemp(prefix="ckit-maker-checker-index-")
    os.close(descriptor)
    index_path = Path(index_name)
    index_path.unlink()
    environment = {**os.environ, "GIT_INDEX_FILE": str(index_path)}
    try:
        _populate_no_filter_index(
            workspace,
            environment=environment,
            allowed_paths=allowed_paths,
        )
        applied = _run_git_with_env(
            workspace,
            _filter_neutral_git_args(
                workspace,
                paths,
                ("apply", "--cached", "--whitespace=error-all"),
            ),
            environment=environment,
            input_text=patch,
        )
        if applied.returncode != 0:
            raise _PatchSafetyError(
                "maker output is not an applicable clean incremental diff"
            )
        expected = _run_git_with_env(
            workspace,
            (
                "diff",
                "--cached",
                "--no-ext-diff",
                "--no-textconv",
                "--no-renames",
                "--full-index",
                "HEAD",
                "--",
            ),
            environment=environment,
        )
        checked = _run_git_with_env(
            workspace,
            (
                "diff",
                "--cached",
                "--no-ext-diff",
                "--no-textconv",
                "--check",
                "HEAD",
                "--",
            ),
            environment=environment,
        )
        if expected.returncode != 0 or checked.returncode != 0:
            raise _PatchSafetyError(
                "expected code artifact failed deterministic diff checks"
            )
        if (
            not expected.stdout.strip()
            or len(expected.stdout.encode("utf-8")) > _MAX_ARTIFACT_BYTES
        ):
            raise _PatchSafetyError(
                "expected code artifact is empty or exceeds its bound"
            )
        actual_paths, _ = _inspect_patch(expected.stdout)
        if not set(actual_paths).issubset(frozen_paths):
            raise _PatchSafetyError(
                "expected code artifact expanded the frozen path set"
            )
        return expected.stdout, frozen_paths
    finally:
        index_path.unlink(missing_ok=True)
        index_path.with_name(index_path.name + ".lock").unlink(missing_ok=True)


def _reconstruct_code_artifacts(
    repository: Path,
    *,
    base_commit: str,
    patches: Sequence[str],
) -> list[str]:
    """Rebuild each cumulative diff from immutable maker responses only."""

    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", base_commit):
        raise _PatchSafetyError("frozen code base commit is malformed")
    descriptor, index_name = tempfile.mkstemp(prefix="ckit-maker-checker-verify-")
    os.close(descriptor)
    index_path = Path(index_name)
    index_path.unlink()
    environment = {**os.environ, "GIT_INDEX_FILE": str(index_path)}
    reconstructed: list[str] = []
    try:
        initialized = _run_git_with_env(
            repository, ("read-tree", base_commit), environment=environment
        )
        if initialized.returncode != 0:
            raise _PatchSafetyError("cannot initialize frozen code evidence index")
        for patch in patches:
            paths, _new_paths = _inspect_patch(patch)
            applied = _run_git_with_env(
                repository,
                _filter_neutral_git_args(
                    repository,
                    paths,
                    ("apply", "--cached", "--whitespace=error-all"),
                ),
                environment=environment,
                input_text=patch,
            )
            if applied.returncode != 0:
                raise _PatchSafetyError(
                    "persisted maker patch is not incremental against prior evidence"
                )
            diff = _run_git_with_env(
                repository,
                (
                    "diff",
                    "--cached",
                    "--no-ext-diff",
                    "--no-textconv",
                    "--no-renames",
                    "--full-index",
                    base_commit,
                    "--",
                ),
                environment=environment,
            )
            checked = _run_git_with_env(
                repository,
                (
                    "diff",
                    "--cached",
                    "--no-ext-diff",
                    "--no-textconv",
                    "--check",
                    base_commit,
                    "--",
                ),
                environment=environment,
            )
            if (
                diff.returncode != 0
                or checked.returncode != 0
                or not diff.stdout.strip()
            ):
                raise _PatchSafetyError(
                    "persisted cumulative code evidence failed deterministic checks"
                )
            _inspect_patch(diff.stdout)
            reconstructed.append(diff.stdout)
    finally:
        index_path.unlink(missing_ok=True)
        index_path.with_name(index_path.name + ".lock").unlink(missing_ok=True)
    return reconstructed


def _apply_patch(
    workspace: Path,
    patch: str,
    *,
    allowed_paths: set[str],
) -> tuple[str, tuple[dict[str, object], ...], set[str]]:
    paths, new_paths = _inspect_patch(patch)
    _assert_patch_target_ancestors(workspace, paths)
    _assert_new_paths_visible(workspace, new_paths)
    if allowed_paths and not set(paths).issubset(allowed_paths):
        expanded = sorted(set(paths) - allowed_paths)
        raise _PatchSafetyError(
            "code revision expands the frozen initial path set: " + ", ".join(expanded)
        )
    numstat = _run_git(workspace, ("apply", "--numstat", "-z"), input_text=patch)
    if numstat.returncode != 0:
        raise _PatchSafetyError("git could not corroborate maker patch paths")
    reported_paths: list[str] = []
    for raw_record in numstat.stdout.split("\0"):
        if not raw_record:
            continue
        columns = raw_record.split("\t", 2)
        if len(columns) != 3:
            raise _PatchSafetyError("git returned malformed patch path evidence")
        reported_paths.append(_safe_patch_path(columns[2]))
    if reported_paths != list(paths):
        raise _PatchSafetyError(
            "git patch path evidence differs from canonical headers"
        )
    for relative in paths:
        candidate = workspace / relative
        if candidate.exists() or candidate.is_symlink():
            info = candidate.lstat()
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                raise _PatchSafetyError(
                    f"patch target must be a regular file: {relative!r}"
                )
    checked = _run_git(
        workspace,
        _filter_neutral_git_args(
            workspace,
            paths,
            ("apply", "--check", "--whitespace=error-all"),
        ),
        input_text=patch,
    )
    if checked.returncode != 0:
        raise _PatchSafetyError("maker output is not an applicable clean unified diff")
    applied = _run_git(
        workspace,
        _filter_neutral_git_args(
            workspace,
            paths,
            ("apply", "--intent-to-add", "--whitespace=error-all"),
        ),
        input_text=patch,
    )
    if applied.returncode != 0:
        raise _PatchSafetyError("validated patch changed before it could be applied")
    return _capture_code_artifact(workspace, allowed_paths=allowed_paths or set(paths))


def _document_checks(content: str) -> tuple[dict[str, object], ...]:
    return (
        {
            "id": "artifact-nonempty",
            "status": "PASS",
            "evidence": f"sha256:{_content_digest(content)}",
        },
    )


def _worker_context(
    contract: Mapping[str, object],
    *,
    iteration: int,
    prior_artifact: Optional[_Artifact],
    findings: Sequence[Mapping[str, object]],
) -> str:
    return _canonical_json(
        {
            "schema_version": MAKER_CHECKER_SCHEMA_VERSION,
            "contract": dict(contract),
            "iteration": iteration,
            "prior_artifact": (
                None
                if prior_artifact is None
                else {
                    "kind": prior_artifact.kind,
                    "content": prior_artifact.content,
                    "digest": prior_artifact.digest,
                    "path": prior_artifact.path,
                }
            ),
            "findings": list(findings),
            "output_contract": {
                "schema_version": 1,
                "artifact": {"kind": "document|unified-diff", "content": "string"},
                "summary": "string",
                "finding_dispositions": [
                    {
                        "finding_id": "string",
                        "disposition": "fixed|disputed|human-required",
                        "evidence": ["string"],
                        "note": "string",
                    }
                ],
            },
        }
    )


def _reviewer_context(
    contract: Mapping[str, object],
    artifact: _Artifact,
    checks: Sequence[Mapping[str, object]],
    *,
    prior_findings: Optional[Sequence[Mapping[str, object]]] = None,
) -> str:
    context: dict[str, object] = {
        "schema_version": MAKER_CHECKER_SCHEMA_VERSION,
        "contract": dict(contract),
        "artifact": {
            "kind": artifact.kind,
            "content": artifact.content,
            "digest": artifact.digest,
            "path": artifact.path,
        },
        "deterministic_checks": list(checks),
        "output_contract": {
            "schema_version": 1,
            "verdict": "PASS|FAIL",
            "contract_digest": contract["digest"],
            "artifact_digest": artifact.digest,
            "criteria": [
                {
                    "criterion_id": "string",
                    "status": "PASS|FAIL",
                    "evidence": ["string"],
                }
            ],
            "findings": [
                {
                    "finding_id": "string",
                    "severity": "critical|high|medium|low|info",
                    "message": "string",
                    "evidence": ["string"],
                }
            ],
            "residual_risks": ["string"],
        },
    }
    if prior_findings is not None:
        context["prior_finding_registry"] = _compact_finding_registry(prior_findings)
    return _canonical_json(context)


def _dispatch_ownership_callbacks(
    ledger: _RunLedger,
    *,
    attempt_id: str,
    route: str,
) -> tuple[Callable[[str, int, str], None], Callable[[str, int], None]]:
    """Bind native correlation receipts to one logical ledger attempt."""

    def record(dispatch_id: str, dispatch_attempt: int, reason: str) -> None:
        ledger.record_unsafe_dispatch(
            attempt_id,
            route=route,
            dispatch_id=dispatch_id,
            dispatch_attempt=dispatch_attempt,
            reason=reason,
        )

    def clear(dispatch_id: str, dispatch_attempt: int) -> None:
        ledger.clear_unsafe_dispatch(
            attempt_id,
            dispatch_id=dispatch_id,
            dispatch_attempt=dispatch_attempt,
        )

    return record, clear


def _dispatch_output(
    dispatcher: Dispatcher,
    request: DispatchRequest,
    *,
    expected_binding: ResolvedWorkerBinding,
    timeout_seconds: float,
    on_unconfirmed_ownership: Callable[[str, int, str], None],
    on_confirmed_termination: Callable[[str, int], None],
) -> str:
    if getattr(dispatcher, "queued_spawn", False) is not True:
        raise _CoordinatorStop(
            HumanStopRequest(
                HumanStopReason.UNSUPPORTED_REQUIRED_CAPABILITY,
                "native dispatch does not attest queue-before-wait ownership",
                "upgrade the provider adapter before starting a managed maker-checker run",
            )
        )
    try:
        handle = dispatcher.spawn(request)
    except Exception as exc:
        raise _CoordinatorStop(
            HumanStopRequest(
                HumanStopReason.UNSUPPORTED_REQUIRED_CAPABILITY,
                public_human_stop_text(
                    exc, fallback="the configured native worker is unavailable"
                ),
                "run maker-checker probe, repair the configured host/model/role, and retry",
            )
        ) from exc

    def verify_handle(candidate: DispatchHandle) -> None:
        if (
            candidate.route != request.route
            or tuple(candidate.required_capabilities)
            != tuple(request.required_capabilities)
            or candidate.execution_slot is not request.execution_slot
            or candidate.provider != expected_binding.provider
            or candidate.requested_model != expected_binding.requested_model
        ):
            raise _CoordinatorStop(
                HumanStopRequest(
                    HumanStopReason.CONFLICTING_EVIDENCE,
                    "native dispatch identity differs from the frozen maker-checker binding",
                    "inspect the provider adapter and restart with an attested binding",
                )
            )
        required = {Capability.FILE_READ, Capability.SEARCH}
        if set(candidate.attested_capabilities) != required:
            raise _CoordinatorStop(
                HumanStopRequest(
                    HumanStopReason.UNSUPPORTED_REQUIRED_CAPABILITY,
                    "native dispatch did not attest the required passive read/search boundary",
                    "upgrade or reconfigure to a host that can attest the required capabilities",
                )
            )

    def mark_uncertain_or_cancel(candidate: DispatchHandle, reason: str) -> None:
        try:
            on_unconfirmed_ownership(candidate.id, candidate.attempt, reason)
        except Exception as marker_error:
            # Queue-before-wait guarantees the initial handle has not started.
            # Still cancel its in-memory reservation before surfacing the failed
            # durable claim.
            try:
                dispatcher.cancel(candidate, reason)
            except Exception:
                pass
            raise MakerCheckerError(
                "native dispatch ownership could not be durably recorded; the "
                "maker-checker attempt remains active"
            ) from marker_error

    def cancel_or_leave_active(candidate: DispatchHandle, reason: str) -> None:
        intent_error: Optional[Exception] = None
        try:
            # Persist cancellation-pending before touching the native handle. A
            # killed coordinator can therefore never turn a failed cancellation
            # into an apparently stale/retryable attempt.
            on_unconfirmed_ownership(
                candidate.id, candidate.attempt, "cancellation pending: " + reason
            )
        except Exception as exc:
            intent_error = exc
        try:
            dispatcher.cancel(candidate, reason)
        except Exception as exc:
            raise MakerCheckerError(
                "native dispatch cancellation could not be confirmed; the active "
                "maker-checker snapshot is preserved for operator recovery"
            ) from (intent_error or exc)
        try:
            on_confirmed_termination(candidate.id, candidate.attempt)
        except Exception as exc:
            raise MakerCheckerError(
                "native dispatch was cancelled but its durable ownership marker "
                "could not be cleared"
            ) from exc

    try:
        verify_handle(handle)
    except _CoordinatorStop:
        cancel_or_leave_active(handle, "maker-checker dispatch attestation failed")
        raise
    mark_uncertain_or_cancel(
        handle, "native dispatch is queued and may become active during wait"
    )
    retries = 0
    while True:
        try:
            snapshot = dispatcher.wait(
                (handle,), WaitMode.ALL, timeout_seconds=timeout_seconds
            )
        except KeyboardInterrupt as exc:
            cancel_or_leave_active(handle, "maker-checker coordinator interrupted")
            raise _CoordinatorStop(
                HumanStopRequest(
                    HumanStopReason.RETRY_BUDGET_EXHAUSTED,
                    "maker-checker was interrupted and its active worker was cancelled",
                    "inspect preserved evidence and explicitly start a new run",
                )
            ) from exc
        except Exception as exc:
            cancel_or_leave_active(handle, "maker-checker wait failed")
            raise _CoordinatorStop(
                HumanStopRequest(
                    HumanStopReason.RETRY_BUDGET_EXHAUSTED,
                    public_human_stop_text(exc, fallback="native worker wait failed"),
                    "inspect the native host and explicitly retry the run",
                )
            ) from exc
        if snapshot.timed_out or snapshot.pending:
            cancel_or_leave_active(handle, "maker-checker hard wait timeout")
            raise _CoordinatorStop(
                HumanStopRequest(
                    HumanStopReason.RETRY_BUDGET_EXHAUSTED,
                    "native worker exceeded the bounded maker-checker wait",
                    "inspect the cancelled host attempt and explicitly retry",
                )
            )
        try:
            results = dispatcher.collect((handle,))
        except Exception as exc:
            # ``wait`` returned this exact handle as terminal. Collection can
            # still fail to decode transport evidence, but cancellation is no
            # longer meaningful and must not create a false unsafe marker.
            try:
                on_confirmed_termination(handle.id, handle.attempt)
            except Exception as marker_error:
                raise MakerCheckerError(
                    "native dispatch completed but its durable ownership marker "
                    "could not be cleared"
                ) from marker_error
            raise _CoordinatorStop(
                HumanStopRequest(
                    HumanStopReason.CONFLICTING_EVIDENCE,
                    public_human_stop_text(
                        exc, fallback="native worker result could not be collected"
                    ),
                    "inspect the provider adapter and preserved host capture",
                )
            ) from exc
        if len(results) != 1 or results[0].handle != handle:
            if (
                results
                and results[0].handle != handle
                and not results[0].status.terminal
            ):
                cancel_or_leave_active(
                    results[0].handle,
                    "maker-checker unexpected result identity",
                )
            try:
                on_confirmed_termination(handle.id, handle.attempt)
            except Exception as marker_error:
                raise MakerCheckerError(
                    "native dispatch completed but its durable ownership marker "
                    "could not be cleared"
                ) from marker_error
            raise _CoordinatorStop(
                HumanStopRequest(
                    HumanStopReason.CONFLICTING_EVIDENCE,
                    "native dispatcher returned a result for a different attempt",
                    "inspect the provider adapter and restart the run",
                )
            )
        result = results[0]
        try:
            on_confirmed_termination(handle.id, handle.attempt)
        except Exception as exc:
            raise MakerCheckerError(
                "native dispatch completed but its durable ownership marker could "
                "not be cleared"
            ) from exc
        if result.status is DispatchStatus.SUCCEEDED:
            if result.output is None:
                raise _CoordinatorStop(
                    HumanStopRequest(
                        HumanStopReason.CONFLICTING_EVIDENCE,
                        "native worker succeeded without bounded output",
                        "inspect the preserved host capture and restart the run",
                    )
                )
            return result.output
        if result.human_stop is not None:
            raise _CoordinatorStop(result.human_stop)
        if result.status is DispatchStatus.FAILED and retries < _TRANSPORT_RETRIES:
            retries += 1
            try:
                retry_handle = dispatcher.retry(
                    handle, "bounded native transport failure"
                )
            except Exception as exc:
                raise _CoordinatorStop(
                    HumanStopRequest(
                        HumanStopReason.RETRY_BUDGET_EXHAUSTED,
                        public_human_stop_text(
                            exc, fallback="native transport retry could not be reserved"
                        ),
                        "inspect the provider adapter and explicitly resume or restart",
                    )
                ) from exc
            if (
                retry_handle.id != result.handle.id
                or retry_handle.attempt != result.handle.attempt + 1
            ):
                cancel_or_leave_active(
                    retry_handle, "maker-checker retry identity changed"
                )
                raise _CoordinatorStop(
                    HumanStopRequest(
                        HumanStopReason.CONFLICTING_EVIDENCE,
                        "native retry identity differs from its durable ownership intent",
                        "inspect the provider adapter and restart the run",
                    )
                )
            try:
                verify_handle(retry_handle)
            except _CoordinatorStop:
                cancel_or_leave_active(
                    retry_handle, "maker-checker retry attestation failed"
                )
                raise
            mark_uncertain_or_cancel(
                retry_handle,
                "native transport retry is queued and may become active during wait",
            )
            handle = retry_handle
            continue
        raise _CoordinatorStop(
            HumanStopRequest(
                HumanStopReason.RETRY_BUDGET_EXHAUSTED,
                public_human_stop_text(
                    result.error,
                    fallback="native worker failed without usable evidence",
                ),
                "inspect the private host capture, repair the endpoint, and explicitly retry",
            )
        )


def _stop_result(
    *,
    run_id: str,
    kind: DeliverableKind,
    iterations: int,
    policy_digest: str,
    binding_digest: str,
    contract_digest: Optional[str],
    artifact: Optional[_Artifact],
    workspace: Optional[Path],
    stop: HumanStopRequest,
) -> MakerCheckerResult:
    return MakerCheckerResult(
        MakerCheckerStatus.HUMAN_STOP,
        run_id,
        kind,
        iterations,
        policy_digest,
        binding_digest,
        contract_digest,
        artifact_path=artifact.path if artifact else None,
        artifact_digest=artifact.digest if artifact else None,
        workspace=str(workspace) if workspace else None,
        human_stop=stop,
    )


def _mark_failed(manager: Optional[WorktreeManager], run_id: str, reason: str) -> None:
    if manager is None:
        return
    try:
        records = manager.records(run_id)
        if records and records[0].status is WorktreeStatus.ACTIVE:
            manager.mark(
                run_id,
                "maker-checker",
                WorktreeStatus.FAILED,
                failure_reason=public_human_stop_text(
                    reason, fallback="maker-checker stopped"
                ),
                _managed_lease_held=True,
                _project_lease_held=True,
            )
    except (OSError, ValueError, WorktreeError):
        pass


def _contract_from_ledger(ledger: _RunLedger) -> dict[str, object]:
    path = ledger.state.get("contract_path")
    if not isinstance(path, str):
        raise MakerCheckerError("frozen maker-checker contract path is missing")
    document, _sha = _read_json_artifact(ledger.fs, path)
    contract = document.get("contract")
    if not isinstance(contract, dict):
        raise MakerCheckerError("frozen maker-checker contract is malformed")
    return cast(dict[str, object], contract)


def _artifact_from_ledger(ledger: _RunLedger) -> Optional[_Artifact]:
    raw = ledger.state.get("artifact")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise MakerCheckerError("frozen maker-checker artifact record is malformed")
    path = raw.get("path")
    if not isinstance(path, str):
        raise MakerCheckerError("frozen maker-checker artifact path is missing")
    content, digest = _read_text_artifact(ledger.fs, path)
    if digest != raw.get("digest"):
        raise MakerCheckerError("frozen maker-checker artifact digest mismatch")
    return _Artifact(str(raw.get("kind")), content, digest, path)


def _checks_from_ledger(ledger: _RunLedger) -> tuple[dict[str, object], ...]:
    records = ledger.state.get("iteration_records")
    if (
        not isinstance(records, list)
        or not records
        or not isinstance(records[-1], dict)
    ):
        raise MakerCheckerError("active reviewer has no deterministic check record")
    path = records[-1].get("checks_path")
    if not isinstance(path, str):
        raise MakerCheckerError("active reviewer check evidence path is missing")
    raw = ledger.fs.read_bytes(path)
    if len(raw) > _MAX_NESTED_OUTPUT_BYTES:
        raise MakerCheckerError("deterministic check evidence exceeds its bounded size")
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise MakerCheckerError("deterministic check evidence is invalid JSON") from exc
    if not isinstance(document, list) or any(
        not isinstance(item, dict) for item in document
    ):
        raise MakerCheckerError("deterministic check evidence is malformed")
    return tuple(cast(list[dict[str, object]], document))


def _ensure_setup(
    ledger: _RunLedger,
    *,
    kind: DeliverableKind,
    task: str,
    manager: Optional[WorktreeManager],
) -> tuple[Path, Optional[WorktreeManager]]:
    """Idempotently finish the pre-dispatch contract/workspace binding."""

    if ledger.document.get("stage") != "setup":
        raw_workspace = ledger.state.get("workspace")
        if kind is DeliverableKind.CODE:
            if manager is None or not isinstance(raw_workspace, dict):
                raise MakerCheckerError(
                    "code maker-checker workspace binding is missing"
                )
            record = manager.verify(
                str(ledger.document["run_id"]), str(raw_workspace["worker_id"])
            )
            return (ledger.root / record.target_path).resolve(strict=True), manager
        return ledger.root, manager

    workspace = ledger.root
    workspace_record: Optional[WorktreeRecord] = None
    checkpoint: Optional[WorkspaceCheckpoint] = None
    if kind is DeliverableKind.CODE:
        manager = manager or WorktreeManager(ledger.root)
        records = manager.records(str(ledger.document["run_id"]))
        if not records:
            workspace_record = manager.create(
                str(ledger.document["run_id"]),
                "maker-checker",
                _managed_lease_held=True,
                _project_lease_held=True,
            )
        elif len(records) == 1 and records[0].worker_id == "maker-checker":
            workspace_record = (
                manager.create(
                    str(ledger.document["run_id"]),
                    "maker-checker",
                    base_ref=records[0].base_ref,
                    _managed_lease_held=True,
                    _project_lease_held=True,
                )
                if records[0].status is WorktreeStatus.CREATING
                else manager.verify(str(ledger.document["run_id"]), "maker-checker")
            )
            if workspace_record.status is not WorktreeStatus.ACTIVE:
                raise MakerCheckerError("setup worktree is no longer active")
        else:
            raise MakerCheckerError("setup found ambiguous run-owned worktree state")
        workspace = (ledger.root / workspace_record.target_path).resolve(strict=True)
        _assert_clean_owned_worktree(workspace)
        checkpoint = manager.checkpoint(
            str(ledger.document["run_id"]), workspace_record.worker_id
        )

    run_rel = _snapshot_run_rel(ledger.root, str(ledger.document["run_id"]))
    artifact_location = (
        workspace_record.target_path
        if workspace_record is not None
        else f"{run_rel}/{kind.value}.md"
    )
    contract = _contract(task, kind, artifact_location=artifact_location)
    contract_path = f"{run_rel}/contract.json"
    contract_record = {
        "schema_version": MAKER_CHECKER_SCHEMA_VERSION,
        "run_id": ledger.document["run_id"],
        "policy_digest": ledger.state["policy_digest"],
        "binding_digest": ledger.state["binding_digest"],
        "bindings": ledger.state["bindings"],
        "max_revisions": ledger.state["max_revisions"],
        "contract": contract,
    }
    _persist_json(ledger.fs, contract_path, contract_record)
    contract_bytes = ledger.fs.read_bytes(contract_path)
    candidate = deepcopy(ledger.document)
    candidate["stage"] = "maker"
    candidate["next"] = "dispatch maker iteration 1"
    raw_state = candidate["maker_checker"]
    assert isinstance(raw_state, dict)
    raw_state.update(
        {
            "contract_digest": contract["digest"],
            "contract_path": contract_path,
            "contract_file_sha256": _bytes_digest(contract_bytes),
            "workspace": (
                _workspace_binding(workspace_record)
                if workspace_record is not None
                else None
            ),
            "workspace_checkpoint": checkpoint.to_dict() if checkpoint else None,
        }
    )
    ledger.replace(candidate)
    return workspace, manager


def _finish_attempt_in_document(
    document: dict[str, object],
    attempt_id: str,
    *,
    status: str,
    output_path: Optional[str],
    output_sha256: Optional[str],
) -> None:
    raw_state = document.get("maker_checker")
    if not isinstance(raw_state, dict):
        raise MakerCheckerError("maker-checker state is malformed")
    attempts = raw_state.get("attempts")
    if not isinstance(attempts, list):
        raise MakerCheckerError("maker-checker attempt ledger is malformed")
    matches = [
        item
        for item in attempts
        if isinstance(item, dict) and item.get("attempt_id") == attempt_id
    ]
    if len(matches) != 1 or matches[0].get("status") != "running":
        raise MakerCheckerError("maker-checker attempt ownership changed")
    attempt = matches[0]
    attempt["status"] = status
    attempt["ended_at"] = _utc_now()
    attempt["output_path"] = output_path
    attempt["output_sha256"] = output_sha256


def _complete_apply_intent(
    ledger: _RunLedger,
    *,
    workspace: Path,
    manager: WorktreeManager,
) -> _Artifact:
    """Apply or reconcile one durable incremental patch intent exactly once."""

    pending = ledger.state.get("pending_apply")
    if not isinstance(pending, dict):
        raise MakerCheckerError("maker-checker apply intent is missing")
    patch_path = pending.get("patch_path")
    if not isinstance(patch_path, str):
        raise MakerCheckerError("maker-checker apply patch path is missing")
    patch, patch_sha = _read_text_artifact(ledger.fs, patch_path)
    if patch_sha != pending.get("patch_sha256"):
        raise MakerCheckerError("maker-checker apply patch digest mismatch")
    allowed_paths = pending.get("allowed_paths")
    if not isinstance(allowed_paths, list) or any(
        not isinstance(item, str) for item in allowed_paths
    ):
        raise MakerCheckerError("maker-checker apply path set is malformed")
    frozen_paths = set(cast(list[str], allowed_paths))
    raw_checkpoint = ledger.state.get("workspace_checkpoint")
    if not isinstance(raw_checkpoint, dict):
        raise MakerCheckerError(
            "maker-checker pre-apply workspace checkpoint is missing"
        )
    pre_checkpoint = WorkspaceCheckpoint.from_dict(cast(dict[str, Any], raw_checkpoint))
    current_checkpoint = manager.checkpoint(
        str(ledger.document["run_id"]), "maker-checker"
    )
    if current_checkpoint == pre_checkpoint:
        content, checks, actual_paths = _apply_patch(
            workspace, patch, allowed_paths=frozen_paths
        )
    else:
        content, checks, actual_paths = _capture_code_artifact(
            workspace, allowed_paths=frozen_paths
        )
    expected_digest = pending.get("expected_artifact_digest")
    if _content_digest(content) != expected_digest:
        raise _PatchSafetyError(
            "owned worktree differs from the durable expected post-apply artifact"
        )
    if actual_paths != frozen_paths:
        raise _PatchSafetyError(
            "applied code artifact differs from its frozen path set"
        )
    iteration = ledger.state.get("iteration")
    if not isinstance(iteration, int) or isinstance(iteration, bool):
        raise MakerCheckerError("maker-checker iteration is malformed")
    attempt_id = str(pending.get("attempt_id"))
    iteration_rel = (
        f"{_snapshot_run_rel(ledger.root, str(ledger.document['run_id']))}/"
        f"iterations/{iteration:03d}"
    )
    artifact_path = f"{iteration_rel}/artifact-{attempt_id}.patch"
    checks_path = f"{iteration_rel}/checks-{attempt_id}.json"
    _persist_text(ledger.fs, artifact_path, content)
    _persist_json(ledger.fs, checks_path, list(checks))
    current = _Artifact(
        "unified-diff", content, _content_digest(content), artifact_path
    )
    records = deepcopy(ledger.state.get("iteration_records"))
    if not isinstance(records, list):
        raise MakerCheckerError("maker-checker iteration ledger is malformed")
    records.append(
        {
            "iteration": iteration,
            "contract_digest": ledger.state["contract_digest"],
            "maker_response_path": pending["maker_response_path"],
            "maker_response_sha256": pending["maker_response_sha256"],
            "artifact_path": current.path,
            "artifact_digest": current.digest,
            "checks_path": checks_path,
            "checks_sha256": _bytes_digest(ledger.fs.read_bytes(checks_path)),
            "verdict": None,
            "finding_ids": [],
            "findings": [],
            "review_response_path": None,
            "review_response_sha256": None,
        }
    )
    candidate = deepcopy(ledger.document)
    _finish_attempt_in_document(
        candidate,
        attempt_id,
        status="succeeded",
        output_path=str(pending["maker_response_path"]),
        output_sha256=str(pending["maker_response_sha256"]),
    )
    state = candidate["maker_checker"]
    assert isinstance(state, dict)
    state.update(
        {
            "artifact": {
                "kind": current.kind,
                "path": current.path,
                "digest": current.digest,
            },
            "pending_apply": None,
            "findings": [],
            "iteration_records": records,
            "workspace_checkpoint": manager.checkpoint(
                str(ledger.document["run_id"]), "maker-checker"
            ).to_dict(),
        }
    )
    candidate["stage"] = "reviewer"
    candidate["next"] = f"review artifact iteration {iteration}"
    ledger.replace(candidate)
    return current


def _terminal_stop_with_ledger(
    ledger: _RunLedger,
    *,
    kind: DeliverableKind,
    artifact: Optional[_Artifact],
    workspace: Optional[Path],
    stop: HumanStopRequest,
    manager: Optional[WorktreeManager],
    attempt_output_path: Optional[str] = None,
    attempt_output_sha256: Optional[str] = None,
    attempt_status: str = "failed",
    mark_worktree_failed: bool = True,
) -> MakerCheckerResult:
    if (attempt_output_path is None) != (attempt_output_sha256 is None):
        raise MakerCheckerError("terminal attempt output evidence is incomplete")
    state = ledger.state
    raw_iteration = state.get("iteration", 1)
    if not isinstance(raw_iteration, int) or isinstance(raw_iteration, bool):
        raise MakerCheckerError("maker-checker iteration is malformed")
    iterations = raw_iteration
    result = _stop_result(
        run_id=str(ledger.document["run_id"]),
        kind=kind,
        iterations=iterations,
        policy_digest=str(state["policy_digest"]),
        binding_digest=str(state["binding_digest"]),
        contract_digest=(
            str(state["contract_digest"])
            if isinstance(state.get("contract_digest"), str)
            else None
        ),
        artifact=artifact,
        workspace=workspace,
        stop=stop,
    )
    run_rel = _snapshot_run_rel(ledger.root, result.run_id)
    result_path = f"{run_rel}/result.json"
    records = state.get("iteration_records")
    _persist_json(
        ledger.fs,
        result_path,
        {
            **result.to_dict(),
            "iteration_records": records if isinstance(records, list) else [],
        },
    )
    candidate = deepcopy(ledger.document)
    candidate_state = candidate["maker_checker"]
    assert isinstance(candidate_state, dict)
    attempts = candidate_state.get("attempts")
    if isinstance(attempts, list) and attempts:
        last = attempts[-1]
        if isinstance(last, dict) and last.get("status") == "running":
            _finish_attempt_in_document(
                candidate,
                str(last.get("attempt_id")),
                status=attempt_status,
                output_path=attempt_output_path,
                output_sha256=attempt_output_sha256,
            )
    candidate_state["pending_apply"] = None
    if manager is not None:
        candidate_state["workspace_checkpoint"] = manager.checkpoint(
            result.run_id, "maker-checker"
        ).to_dict()
    candidate.update(
        {
            "status": "aborted",
            "stage": "human-stop",
            "next": stop.requested_action,
            "aborted_at": _utc_now(),
            "human_stop": {
                "reason": stop.reason.value,
                "message": stop.message,
                "requested_action": stop.requested_action,
            },
            "result_path": result_path,
            "result_sha256": _bytes_digest(ledger.fs.read_bytes(result_path)),
        }
    )
    ledger.replace(candidate)
    if mark_worktree_failed:
        _mark_failed(manager, result.run_id, stop.message)
    return result


def abort_maker_checker_run(
    project_root: str | Path,
    *,
    run_id: Optional[str] = None,
    _managed_lease_held: bool = False,
) -> MakerCheckerResult:
    """Abort one active run with coherent result evidence and worktree state.

    The private lease flag exists only for :mod:`claude_kit.pipeline`, whose public
    ``abort`` entry point already owns the shared managed-execution lease.
    """

    try:
        lifecycle_fs = _existing_project_fs(project_root)
        root = lifecycle_fs.root
    except (OSError, ValueError, UnsafePathError) as exc:
        raise MakerCheckerError(f"unsafe maker-checker project root: {exc}") from exc

    def abort_under_lease() -> MakerCheckerResult:
        ledger = _resume_ledger(
            root,
            run_id,
            compatibility_root=None,
            interrupt_stale=False,
            allow_unbound_setup_worktree=True,
        )
        selected_kind = DeliverableKind(str(ledger.document["kind"]))
        artifact = _artifact_from_ledger(ledger)
        manager: Optional[WorktreeManager] = None
        checkpoint_manager: Optional[WorktreeManager] = None
        workspace: Optional[Path] = root
        if selected_kind is DeliverableKind.CODE:
            manager = WorktreeManager(root)
            raw_workspace = ledger.state.get("workspace")
            records = manager.records(str(ledger.document["run_id"]))
            if isinstance(raw_workspace, dict):
                record = manager.verify(
                    str(ledger.document["run_id"]), str(raw_workspace.get("worker_id"))
                )
                workspace = (root / record.target_path).resolve(strict=True)
                checkpoint_manager = manager
            elif ledger.document.get("stage") == "setup":
                if len(records) > 1 or (
                    records and records[0].worker_id != "maker-checker"
                ):
                    raise MakerCheckerError(
                        "setup found ambiguous run-owned worktree state"
                    )
                if records and records[0].status is WorktreeStatus.CREATING:
                    pending_target = root / records[0].target_path
                    if pending_target.exists() or pending_target.is_symlink():
                        manager.create(
                            str(ledger.document["run_id"]),
                            records[0].worker_id,
                            base_ref=records[0].base_ref,
                            _managed_lease_held=True,
                            _project_lease_held=True,
                        )
                    else:
                        manager.abort_run(
                            str(ledger.document["run_id"]),
                            _managed_lease_held=True,
                            _project_lease_held=True,
                        )
                    records = manager.records(str(ledger.document["run_id"]))
                discovered = (
                    records[0]
                    if records and records[0].status is not WorktreeStatus.REMOVED
                    else None
                )
                workspace = (
                    (root / discovered.target_path).resolve(strict=True)
                    if discovered is not None
                    else root
                )
                if discovered is not None:
                    discovered = manager.verify(
                        str(ledger.document["run_id"]), discovered.worker_id
                    )
                    discovered_checkpoint = manager.checkpoint(
                        str(ledger.document["run_id"]), discovered.worker_id
                    )
                    # Fold the pre-binding setup record into the same terminal CAS.
                    ledger.state["workspace"] = _workspace_binding(discovered)
                    ledger.state["workspace_checkpoint"] = (
                        discovered_checkpoint.to_dict()
                    )
                    checkpoint_manager = manager
            else:
                raise MakerCheckerError(
                    "active code maker-checker workspace binding is missing"
                )
            if ledger.document.get("stage") == "apply":
                pending = ledger.state.get("pending_apply")
                raw_checkpoint = ledger.state.get("workspace_checkpoint")
                if not isinstance(pending, dict) or not isinstance(
                    raw_checkpoint, dict
                ):
                    raise MakerCheckerError("maker-checker apply intent is malformed")
                assert manager is not None and workspace is not None
                before = WorkspaceCheckpoint.from_dict(
                    cast(dict[str, Any], raw_checkpoint)
                )
                current = manager.checkpoint(
                    str(ledger.document["run_id"]), "maker-checker"
                )
                if current != before:
                    artifact = _complete_apply_intent(
                        ledger,
                        workspace=workspace,
                        manager=manager,
                    )
                    checkpoint_manager = manager

        stop = HumanStopRequest(
            HumanStopReason.OPERATOR_ABORTED,
            "maker-checker run was explicitly aborted by its operator",
            "start a new maker-checker run if work should continue",
        )
        result = _terminal_stop_with_ledger(
            ledger,
            kind=selected_kind,
            artifact=artifact,
            workspace=workspace,
            stop=stop,
            manager=checkpoint_manager,
            attempt_status="interrupted",
            mark_worktree_failed=False,
        )
        if manager is not None:
            manager.abort_run(
                result.run_id,
                _managed_lease_held=True,
                _project_lease_held=True,
            )
        return result

    if _managed_lease_held:
        try:
            with lifecycle_fs.mutation_lease():
                return abort_under_lease()
        except (UnsafePathError, WorktreeError) as exc:
            raise MakerCheckerError(f"maker-checker abort failed: {exc}") from exc
    try:
        with managed_execution_lease(root), lifecycle_fs.mutation_lease():
            return abort_under_lease()
    except (ManagedExecutionLeaseHeld, UnsafePathError, WorktreeError) as exc:
        raise MakerCheckerError(f"maker-checker abort failed: {exc}") from exc


def confirm_maker_checker_dispatch_terminated(
    project_root: str | Path,
    *,
    run_id: str,
    attempt_id: str,
    route: str,
    dispatch_id: str,
    dispatch_attempt: int,
    evidence: str,
) -> str:
    """Record explicit operator evidence that one uncertain native attempt ended.

    This is the only supported recovery from ``unsafe_dispatch``. The caller must
    identify the exact frozen run, attempt, and route and provide a bounded
    human-auditable termination reference (for example, a host job status or PID
    observation). The confirmation is persisted and hash-bound before resume or
    abort may proceed.
    """

    try:
        lifecycle_fs = _existing_project_fs(project_root)
        root = lifecycle_fs.root
        frozen_run_id = _safe_run_id(run_id)
    except (OSError, ValueError, UnsafePathError) as exc:
        raise MakerCheckerError(f"unsafe maker-checker project root: {exc}") from exc
    if (
        not isinstance(attempt_id, str)
        or not _IDENTIFIER_RE.fullmatch(attempt_id)
        or ".." in attempt_id
    ):
        raise MakerCheckerError("termination confirmation attempt_id is malformed")
    if route not in {MAKER_ROUTE, REVIEWER_ROUTE}:
        raise MakerCheckerError("termination confirmation route is invalid")
    if not isinstance(dispatch_id, str) or not _IDENTIFIER_RE.fullmatch(dispatch_id):
        raise MakerCheckerError("termination confirmation dispatch_id is malformed")
    if (
        not isinstance(dispatch_attempt, int)
        or isinstance(dispatch_attempt, bool)
        or dispatch_attempt < 1
    ):
        raise MakerCheckerError("termination confirmation dispatch_attempt is invalid")
    if not isinstance(evidence, str) or not evidence.strip():
        raise MakerCheckerError("termination confirmation evidence is required")
    evidence = evidence.strip()
    if len(evidence.encode("utf-8")) > _MAX_TEXT_FIELD_BYTES:
        raise MakerCheckerError("termination confirmation evidence exceeds its bound")

    try:
        with managed_execution_lease(root), lifecycle_fs.mutation_lease():
            from claude_kit import pipeline as pipeline_state

            document, error = pipeline_state._load_snapshot(root)
            if error:
                raise MakerCheckerError(error)
            if not is_maker_checker_snapshot(document) or not isinstance(
                document, dict
            ):
                raise MakerCheckerError(
                    "the shared pipeline snapshot is not a maker-checker run"
                )
            if document.get("status") != "active":
                raise MakerCheckerError(
                    "termination confirmation requires an active run"
                )
            if document.get("run_id") != frozen_run_id:
                raise MakerCheckerError(
                    "termination confirmation run differs from the active run"
                )
            valid, messages = validate_maker_checker_snapshot(root, document)
            if not valid:
                raise MakerCheckerError(
                    "cannot reconcile maker-checker dispatch: " + "; ".join(messages)
                )
            ledger = _RunLedger(root, ProjectFS(root), document)
            unsafe = ledger.state.get("unsafe_dispatch")
            attempts = ledger.state.get("attempts")
            if (
                not isinstance(unsafe, dict)
                or unsafe.get("attempt_id") != attempt_id
                or unsafe.get("route") != route
                or unsafe.get("dispatch_id") != dispatch_id
                or unsafe.get("dispatch_attempt") != dispatch_attempt
                or not isinstance(attempts, list)
                or not attempts
                or not isinstance(attempts[-1], dict)
                or attempts[-1].get("attempt_id") != attempt_id
                or attempts[-1].get("route") != route
                or attempts[-1].get("status") != "running"
            ):
                raise MakerCheckerError(
                    "termination confirmation does not match the uncertain dispatch"
                )
            if attempts[-1].get("provider") == "codex":
                try:
                    cleanup_codex_dispatch_credentials(dispatch_id, dispatch_attempt)
                except (OSError, ValueError, RuntimeError) as exc:
                    raise MakerCheckerError(
                        "cannot confirm termination until the exact Codex credential "
                        "isolation has been removed"
                    ) from exc
            confirmed_at = _utc_now()
            proof_path = (
                f"{_snapshot_run_rel(root, frozen_run_id)}/termination-proofs/"
                f"{attempt_id}.json"
            )
            proof = {
                "schema_version": MAKER_CHECKER_SCHEMA_VERSION,
                "run_id": frozen_run_id,
                "attempt_id": attempt_id,
                "route": route,
                "dispatch_id": dispatch_id,
                "dispatch_attempt": dispatch_attempt,
                "confirmation": "operator-confirmed-terminated",
                "evidence": evidence,
                "confirmed_at": confirmed_at,
            }
            _persist_json(ledger.fs, proof_path, proof)
            candidate = deepcopy(ledger.document)
            _finish_attempt_in_document(
                candidate,
                attempt_id,
                status="interrupted",
                output_path=None,
                output_sha256=None,
            )
            candidate_state = candidate["maker_checker"]
            assert isinstance(candidate_state, dict)
            candidate_attempts = candidate_state["attempts"]
            assert isinstance(candidate_attempts, list)
            candidate_attempt = candidate_attempts[-1]
            assert isinstance(candidate_attempt, dict)
            candidate_attempt["termination_proof_path"] = proof_path
            candidate_attempt["termination_proof_sha256"] = _bytes_digest(
                ledger.fs.read_bytes(proof_path)
            )
            candidate_attempt["termination_dispatch_id"] = dispatch_id
            candidate_attempt["termination_dispatch_attempt"] = dispatch_attempt
            candidate_state["unsafe_dispatch"] = None
            candidate["next"] = (
                "resume or abort after operator-confirmed native termination"
            )
            ledger.replace(candidate)
            return proof_path
    except (ManagedExecutionLeaseHeld, UnsafePathError) as exc:
        raise MakerCheckerError(str(exc)) from exc


def load_frozen_maker_checker_run(
    project_root: str | Path,
    run_id: Optional[str] = None,
) -> FrozenMakerCheckerRun:
    """Read and validate an active frozen run without mutating resume state."""

    try:
        root = _existing_project_fs(project_root).root
    except (OSError, ValueError, UnsafePathError) as exc:
        raise MakerCheckerError(f"unsafe maker-checker project root: {exc}") from exc
    from claude_kit import pipeline as pipeline_state

    document, error = pipeline_state._load_snapshot(root)
    if error:
        raise MakerCheckerError(error)
    if not is_maker_checker_snapshot(document) or not isinstance(document, dict):
        raise MakerCheckerError(
            "the shared pipeline snapshot is not a maker-checker run"
        )
    if document.get("status") != "active":
        raise MakerCheckerError(
            f"maker-checker run {document.get('run_id')!r} is terminal"
        )
    if run_id is not None and document.get("run_id") != _safe_run_id(run_id):
        raise MakerCheckerError(
            f"active maker-checker run is {document.get('run_id')!r}, not {run_id!r}"
        )
    valid, messages = validate_maker_checker_snapshot(root, document)
    if not valid:
        raise MakerCheckerError("cannot resume maker-checker: " + "; ".join(messages))
    state = document.get("maker_checker")
    assert isinstance(state, dict)
    bindings = _frozen_bindings(state)
    iteration = state.get("iteration")
    max_revisions = state.get("max_revisions")
    if not isinstance(iteration, int) or not isinstance(max_revisions, int):
        raise MakerCheckerError("frozen maker-checker budget is malformed")
    return FrozenMakerCheckerRun(
        run_id=str(document["run_id"]),
        task=str(document["task"]),
        kind=DeliverableKind(str(document["kind"])),
        stage=str(document["stage"]),
        iteration=iteration,
        max_revisions=max_revisions,
        maker=bindings[ExecutionSlot.MAKER],
        reviewer=bindings[ExecutionSlot.REVIEWER],
    )


def run_maker_checker(
    project_root: str | Path,
    *,
    task: Optional[str] = None,
    kind: DeliverableKind | str = DeliverableKind.AUTO,
    policy: Optional[ExecutionPolicy] = None,
    dispatcher: Optional[Dispatcher] = None,
    compatibility_root: Optional[Path] = None,
    run_id: Optional[str] = None,
    resume_run_id: Optional[str] = None,
    timeout_seconds: float = 900.0,
    worktree_manager: Optional[WorktreeManager] = None,
    on_frozen: Optional[Callable[[FrozenMakerCheckerRun], None]] = None,
) -> MakerCheckerResult:
    """Run one explicit, bounded maker→reviewer feedback cycle.

    Args:
        project_root: Runtime-aware initialized project root.
        task: Exact user objective sent to both bound providers. May be omitted only
            while resuming, in which case the frozen objective is used.
        kind: Explicit artifact contract or conservative ``auto`` inference.
        policy: Optional preloaded policy; otherwise read from shared ``.ckit`` state.
        dispatcher: Injectable six-operation dispatcher used by tests/custom hosts.
        compatibility_root: Optional catalog root for semantic-tier resolution.
        run_id: Optional stable identifier, primarily for deterministic tests/resume tooling.
        resume_run_id: Resume the matching active maker-checker snapshot instead of
            creating a new run. The frozen task, contract, pair, and budget are reused.
        timeout_seconds: Hard wait for each native attempt.
        worktree_manager: Injectable worktree manager for code artifacts.
        on_frozen: Optional announcement callback invoked under the managed lease,
            after the exact run/pair is durably frozen and before setup or dispatch.

    Returns:
        A terminal PASS or typed human-stop record. Reviewer prose is never returned as
        the deliverable.

    Raises:
        MakerCheckerError: If inputs or persisted configuration cannot form a safe run.
    """

    if run_id is not None and resume_run_id is not None:
        raise MakerCheckerError("run_id and resume_run_id cannot be used together")
    if resume_run_id is None:
        if not isinstance(task, str) or not task.strip():
            raise MakerCheckerError("maker-checker task must be a non-empty string")
        task = task.strip()
        if len(task.encode("utf-8")) > _MAX_TASK_BYTES:
            raise MakerCheckerError(
                "maker-checker task exceeds the 64 KiB safety limit"
            )
    elif task is not None:
        if not isinstance(task, str) or not task.strip():
            raise MakerCheckerError("maker-checker task must be a non-empty string")
        task = task.strip()
        if len(task.encode("utf-8")) > _MAX_TASK_BYTES:
            raise MakerCheckerError(
                "maker-checker task exceeds the 64 KiB safety limit"
            )
    if timeout_seconds <= 0:
        raise MakerCheckerError("maker-checker timeout_seconds must be positive")
    try:
        fs = _existing_project_fs(project_root)
        root = fs.root
    except (OSError, ValueError, UnsafePathError) as exc:
        raise MakerCheckerError(f"unsafe maker-checker project root: {exc}") from exc
    manager: Optional[WorktreeManager] = None
    workspace: Optional[Path] = None
    ledger: Optional[_RunLedger] = None
    try:
        with managed_execution_lease(root), fs.mutation_lease():
            if resume_run_id is not None:
                ledger = _resume_ledger(
                    root,
                    resume_run_id,
                    compatibility_root=compatibility_root,
                    allow_unbound_setup_worktree=True,
                )
                frozen_run_id = str(ledger.document["run_id"])
                frozen_task = str(ledger.document["task"])
                if task is not None and task != frozen_task:
                    raise MakerCheckerError(
                        "resume task differs from the frozen maker-checker objective"
                    )
                selected_kind = DeliverableKind(str(ledger.document["kind"]))
                try:
                    requested_kind = (
                        kind
                        if isinstance(kind, DeliverableKind)
                        else DeliverableKind(kind)
                    )
                except (TypeError, ValueError) as exc:
                    raise MakerCheckerError(
                        "resume deliverable kind is invalid"
                    ) from exc
                if requested_kind not in {DeliverableKind.AUTO, selected_kind}:
                    raise MakerCheckerError(
                        "resume deliverable kind differs from the frozen contract"
                    )
                bindings = _frozen_bindings(ledger.state)
                selected_policy = None
                task = frozen_task
            else:
                assert task is not None
                selected_kind = _resolve_kind(task, kind)
                selected_policy = policy or load_execution_policy(root)
                if selected_policy is None:
                    raise MakerCheckerError(
                        "maker-checker is not configured; run "
                        "`ckit maker-checker configure PROJECT`"
                    )
                frozen_run_id = _safe_run_id(run_id)
                bindings = resolve_execution_bindings(
                    selected_policy, compatibility_root=compatibility_root
                )
                policy_digest = _digest(selected_policy.to_dict())
                binding_document = {
                    slot.value: binding.to_dict() for slot, binding in bindings.items()
                }
                binding_digest = _digest(binding_document)
                ledger = _create_ledger(
                    root,
                    _initial_snapshot(
                        root,
                        run_id=frozen_run_id,
                        task=task,
                        kind=selected_kind,
                        policy=selected_policy.to_dict(),
                        policy_digest=policy_digest,
                        binding_digest=binding_digest,
                        bindings=binding_document,
                        max_revisions=selected_policy.max_revisions,
                    ),
                )

            assert ledger is not None and task is not None
            if on_frozen is not None:
                on_frozen(
                    FrozenMakerCheckerRun(
                        run_id=frozen_run_id,
                        task=task,
                        kind=selected_kind,
                        stage=str(ledger.document["stage"]),
                        iteration=cast(int, ledger.state["iteration"]),
                        max_revisions=cast(int, ledger.state["max_revisions"]),
                        maker=bindings[ExecutionSlot.MAKER],
                        reviewer=bindings[ExecutionSlot.REVIEWER],
                    )
                )
            manager = (
                worktree_manager or WorktreeManager(root)
                if selected_kind is DeliverableKind.CODE
                else None
            )
            workspace, manager = _ensure_setup(
                ledger,
                kind=selected_kind,
                task=task,
                manager=manager,
            )
            contract = _contract_from_ledger(ledger)
            contract_digest = str(ledger.state["contract_digest"])
            run_rel = _snapshot_run_rel(root, frozen_run_id)
            document_artifact_rel = f"{run_rel}/{selected_kind.value}.md"
            active_dispatcher = dispatcher or build_routed_dispatcher(
                root,
                bindings,
                allowed_workspaces=(workspace,) if workspace != root else (),
            )
            artifact = _artifact_from_ledger(ledger)
            terminal_attempt_output_path: Optional[str] = None
            terminal_attempt_output_sha256: Optional[str] = None
            try:
                while ledger.document["status"] == "active":
                    raw_iteration = ledger.state["iteration"]
                    if not isinstance(raw_iteration, int) or isinstance(
                        raw_iteration, bool
                    ):
                        raise MakerCheckerError("maker-checker iteration is malformed")
                    iteration = raw_iteration
                    raw_findings = ledger.state.get("findings")
                    findings = tuple(
                        cast(list[dict[str, object]], raw_findings)
                        if isinstance(raw_findings, list)
                        else []
                    )
                    if ledger.document["stage"] == "apply":
                        if manager is None:
                            raise MakerCheckerError(
                                "maker-checker apply stage has no worktree manager"
                            )
                        pending_apply = ledger.state.get("pending_apply")
                        if isinstance(pending_apply, dict):
                            pending_response_path = pending_apply.get(
                                "maker_response_path"
                            )
                            pending_response_sha = pending_apply.get(
                                "maker_response_sha256"
                            )
                            if isinstance(pending_response_path, str) and isinstance(
                                pending_response_sha, str
                            ):
                                terminal_attempt_output_path = pending_response_path
                                terminal_attempt_output_sha256 = pending_response_sha
                        artifact = _complete_apply_intent(
                            ledger,
                            workspace=workspace,
                            manager=manager,
                        )
                        terminal_attempt_output_path = None
                        terminal_attempt_output_sha256 = None
                        continue
                    if ledger.document["stage"] == "maker":
                        maker_binding = bindings[ExecutionSlot.MAKER]
                        attempt_id = ledger.begin_attempt(
                            slot=ExecutionSlot.MAKER,
                            binding=maker_binding,
                            iteration=iteration,
                            artifact_digest=artifact.digest if artifact else None,
                        )
                        terminal_attempt_output_path = None
                        terminal_attempt_output_sha256 = None
                        maker_request = DispatchRequest(
                            MAKER_ROUTE,
                            (
                                "Produce the exact maker nested JSON output for this frozen "
                                "contract. For a code revision, emit an incremental unified diff "
                                "against the current owned worktree; the coordinator retains the "
                                "cumulative HEAD diff as the reviewed artifact. Do not write files, "
                                "run commands, delegate, or return hidden reasoning."
                            ),
                            lane="maker-checker",
                            retry_budget="maker-checker-transport",
                            context=_worker_context(
                                contract,
                                iteration=iteration,
                                prior_artifact=artifact,
                                findings=findings,
                            ),
                            required_capabilities=(
                                Capability.FILE_READ,
                                Capability.SEARCH,
                            ),
                            workspace=str(workspace),
                            execution_slot=ExecutionSlot.MAKER,
                            requested_model=maker_binding.requested_model,
                        )
                        record_unsafe, clear_unsafe = _dispatch_ownership_callbacks(
                            ledger,
                            attempt_id=attempt_id,
                            route=MAKER_ROUTE,
                        )
                        maker_output = _dispatch_output(
                            active_dispatcher,
                            maker_request,
                            expected_binding=maker_binding,
                            timeout_seconds=timeout_seconds,
                            on_unconfirmed_ownership=record_unsafe,
                            on_confirmed_termination=clear_unsafe,
                        )
                        iteration_rel = f"{run_rel}/iterations/{iteration:03d}"
                        maker_response_path = (
                            f"{iteration_rel}/maker-response-{attempt_id}.json"
                        )
                        maker_response_sha = _persist_worker_output(
                            fs, maker_response_path, maker_output
                        )
                        terminal_attempt_output_path = maker_response_path
                        terminal_attempt_output_sha256 = maker_response_sha
                        parsed_artifact, _maker_summary, dispositions = (
                            _parse_maker_output(
                                maker_output,
                                kind=selected_kind,
                                expected_finding_ids=frozenset(
                                    str(finding["finding_id"]) for finding in findings
                                ),
                            )
                        )
                        disputed = [
                            item
                            for item in dispositions
                            if item["disposition"] == "disputed"
                        ]
                        human_required = [
                            item
                            for item in dispositions
                            if item["disposition"] == "human-required"
                        ]
                        if disputed or human_required:
                            reason = (
                                HumanStopReason.MISSING_REQUIREMENTS
                                if human_required
                                else HumanStopReason.CONFLICTING_EVIDENCE
                            )
                            raise _CoordinatorStop(
                                HumanStopRequest(
                                    reason,
                                    "maker could not resolve every reviewer finding within "
                                    "the frozen contract",
                                    "decide the disputed or human-required finding before a new run",
                                )
                            )
                        prior_paths = (
                            set(_inspect_patch(artifact.content)[0])
                            if selected_kind is DeliverableKind.CODE
                            and artifact is not None
                            else set()
                        )
                        if selected_kind is DeliverableKind.CODE:
                            assert manager is not None
                            raw_patch = str(parsed_artifact["content"])
                            expected_content, frozen_paths = _expected_cumulative_diff(
                                workspace,
                                raw_patch,
                                allowed_paths=prior_paths,
                            )
                            expected_digest = _content_digest(expected_content)
                            if (
                                artifact is not None
                                and expected_digest == artifact.digest
                            ):
                                raise _CoordinatorStop(
                                    HumanStopRequest(
                                        HumanStopReason.CONFLICTING_EVIDENCE,
                                        "maker returned an unchanged artifact after reviewer FAIL",
                                        "resolve the findings or explicitly change the frozen task contract",
                                    )
                                )
                            patch_path = f"{iteration_rel}/maker-{attempt_id}.patch"
                            _persist_text(fs, patch_path, raw_patch)
                            candidate = deepcopy(ledger.document)
                            candidate["stage"] = "apply"
                            candidate["next"] = (
                                f"apply durable maker patch for iteration {iteration}"
                            )
                            state = candidate["maker_checker"]
                            assert isinstance(state, dict)
                            state["findings"] = []
                            state["pending_apply"] = {
                                "attempt_id": attempt_id,
                                "maker_response_path": maker_response_path,
                                "maker_response_sha256": maker_response_sha,
                                "patch_path": patch_path,
                                "patch_sha256": _bytes_digest(
                                    fs.read_bytes(patch_path)
                                ),
                                "expected_artifact_digest": expected_digest,
                                "allowed_paths": sorted(frozen_paths),
                            }
                            ledger.replace(candidate)
                            artifact = _complete_apply_intent(
                                ledger,
                                workspace=workspace,
                                manager=manager,
                            )
                            terminal_attempt_output_path = None
                            terminal_attempt_output_sha256 = None
                            continue

                        content = str(parsed_artifact["content"])
                        checks = _document_checks(content)
                        artifact_path = f"{iteration_rel}/artifact-{attempt_id}.md"
                        _persist_text(fs, artifact_path, content)
                        current = _Artifact(
                            "document",
                            content,
                            _content_digest(content),
                            artifact_path,
                        )
                        if artifact is not None and current.digest == artifact.digest:
                            raise _CoordinatorStop(
                                HumanStopRequest(
                                    HumanStopReason.CONFLICTING_EVIDENCE,
                                    "maker returned an unchanged artifact after reviewer FAIL",
                                    "resolve the findings or explicitly change the frozen task contract",
                                )
                            )
                        checks_path = f"{iteration_rel}/checks-{attempt_id}.json"
                        _persist_json(fs, checks_path, list(checks))
                        records = deepcopy(ledger.state["iteration_records"])
                        assert isinstance(records, list)
                        records.append(
                            {
                                "iteration": iteration,
                                "contract_digest": ledger.state["contract_digest"],
                                "maker_response_path": maker_response_path,
                                "maker_response_sha256": maker_response_sha,
                                "artifact_path": current.path,
                                "artifact_digest": current.digest,
                                "checks_path": checks_path,
                                "checks_sha256": _bytes_digest(
                                    fs.read_bytes(checks_path)
                                ),
                                "verdict": None,
                                "finding_ids": [],
                                "findings": [],
                                "review_response_path": None,
                                "review_response_sha256": None,
                            }
                        )
                        candidate = deepcopy(ledger.document)
                        _finish_attempt_in_document(
                            candidate,
                            attempt_id,
                            status="succeeded",
                            output_path=maker_response_path,
                            output_sha256=maker_response_sha,
                        )
                        state = candidate["maker_checker"]
                        assert isinstance(state, dict)
                        state.update(
                            {
                                "artifact": {
                                    "kind": current.kind,
                                    "path": current.path,
                                    "digest": current.digest,
                                },
                                "findings": [],
                                "iteration_records": records,
                            }
                        )
                        candidate["stage"] = "reviewer"
                        candidate["next"] = f"review artifact iteration {iteration}"
                        ledger.replace(candidate)
                        artifact = current
                        terminal_attempt_output_path = None
                        terminal_attempt_output_sha256 = None
                        continue

                    if ledger.document["stage"] != "reviewer":
                        raise MakerCheckerError(
                            f"unsupported active maker-checker stage {ledger.document['stage']!r}"
                        )
                    assert artifact is not None
                    checks = _checks_from_ledger(ledger)
                    prior_findings_for_reviewer: Optional[
                        Sequence[Mapping[str, object]]
                    ] = None
                    if iteration > 1 and _strict_blocking_subset_enabled(contract):
                        raw_records_for_context = ledger.state.get("iteration_records")
                        if (
                            not isinstance(raw_records_for_context, list)
                            or len(raw_records_for_context) < 2
                            or not isinstance(raw_records_for_context[-2], dict)
                            or not isinstance(
                                raw_records_for_context[-2].get("findings"), list
                            )
                        ):
                            raise MakerCheckerError(
                                "revised reviewer has no prior finding registry"
                            )
                        prior_findings_for_reviewer = cast(
                            list[dict[str, object]],
                            raw_records_for_context[-2]["findings"],
                        )
                    reviewer_binding = bindings[ExecutionSlot.REVIEWER]
                    attempt_id = ledger.begin_attempt(
                        slot=ExecutionSlot.REVIEWER,
                        binding=reviewer_binding,
                        iteration=iteration,
                        artifact_digest=artifact.digest,
                    )
                    terminal_attempt_output_path = None
                    terminal_attempt_output_sha256 = None
                    reviewer_request = DispatchRequest(
                        REVIEWER_ROUTE,
                        (
                            "Independently review the exact artifact digest and return the exact "
                            "reviewer nested JSON output. Do not edit, run commands, delegate, or "
                            "approve any external effect."
                        ),
                        lane="maker-checker",
                        retry_budget="maker-checker-transport",
                        context=_reviewer_context(
                            contract,
                            artifact,
                            checks,
                            prior_findings=prior_findings_for_reviewer,
                        ),
                        required_capabilities=(Capability.FILE_READ, Capability.SEARCH),
                        workspace=str(workspace),
                        execution_slot=ExecutionSlot.REVIEWER,
                        requested_model=reviewer_binding.requested_model,
                    )
                    record_unsafe, clear_unsafe = _dispatch_ownership_callbacks(
                        ledger,
                        attempt_id=attempt_id,
                        route=REVIEWER_ROUTE,
                    )
                    reviewer_output = _dispatch_output(
                        active_dispatcher,
                        reviewer_request,
                        expected_binding=reviewer_binding,
                        timeout_seconds=timeout_seconds,
                        on_unconfirmed_ownership=record_unsafe,
                        on_confirmed_termination=clear_unsafe,
                    )
                    iteration_rel = f"{run_rel}/iterations/{iteration:03d}"
                    review_response_path = (
                        f"{iteration_rel}/review-response-{attempt_id}.json"
                    )
                    review_response_sha = _persist_worker_output(
                        fs, review_response_path, reviewer_output
                    )
                    terminal_attempt_output_path = review_response_path
                    terminal_attempt_output_sha256 = review_response_sha
                    verdict = _parse_review_output(
                        reviewer_output,
                        contract=contract,
                        artifact_digest=artifact.digest,
                    )
                    records = deepcopy(ledger.state["iteration_records"])
                    assert isinstance(records, list) and isinstance(records[-1], dict)
                    records[-1].update(
                        {
                            "verdict": verdict.verdict,
                            "finding_ids": [
                                finding["finding_id"] for finding in verdict.findings
                            ],
                            "findings": list(verdict.findings),
                            "review_response_path": review_response_path,
                            "review_response_sha256": review_response_sha,
                        }
                    )
                    if verdict.verdict == "PASS":
                        if selected_kind is not DeliverableKind.CODE:
                            _persist_text(fs, document_artifact_rel, artifact.content)
                            artifact = _Artifact(
                                artifact.kind,
                                artifact.content,
                                artifact.digest,
                                document_artifact_rel,
                            )
                            records[-1]["artifact_path"] = artifact.path
                        result = MakerCheckerResult(
                            MakerCheckerStatus.PASSED,
                            frozen_run_id,
                            selected_kind,
                            iteration,
                            str(ledger.state["policy_digest"]),
                            str(ledger.state["binding_digest"]),
                            contract_digest,
                            artifact_path=artifact.path,
                            artifact_digest=artifact.digest,
                            workspace=str(workspace),
                            residual_risks=verdict.residual_risks,
                        )
                        result_path = f"{run_rel}/result.json"
                        _persist_json(
                            fs,
                            result_path,
                            {**result.to_dict(), "iteration_records": records},
                        )
                        candidate = deepcopy(ledger.document)
                        _finish_attempt_in_document(
                            candidate,
                            attempt_id,
                            status="succeeded",
                            output_path=review_response_path,
                            output_sha256=review_response_sha,
                        )
                        state = candidate["maker_checker"]
                        assert isinstance(state, dict)
                        state.update(
                            {
                                "artifact": {
                                    "kind": artifact.kind,
                                    "path": artifact.path,
                                    "digest": artifact.digest,
                                },
                                "findings": [],
                                "iteration_records": records,
                            }
                        )
                        candidate.update(
                            {
                                "status": "completed",
                                "stage": "completed",
                                "next": "(maker-checker run completed)",
                                "completed_at": _utc_now(),
                                "result_path": result_path,
                                "result_sha256": _bytes_digest(
                                    fs.read_bytes(result_path)
                                ),
                            }
                        )
                        ledger.replace(candidate)
                        if manager is not None:
                            manager.mark(
                                frozen_run_id,
                                "maker-checker",
                                WorktreeStatus.SUCCEEDED,
                                _managed_lease_held=True,
                                _project_lease_held=True,
                            )
                        return result

                    if iteration > 1 and _strict_blocking_subset_enabled(contract):
                        prior_record = records[-2]
                        if not isinstance(prior_record, dict) or not isinstance(
                            prior_record.get("findings"), list
                        ):
                            raise MakerCheckerError(
                                "revised reviewer has no prior finding evidence"
                            )
                        prior_findings = cast(
                            list[dict[str, object]], prior_record["findings"]
                        )
                        if not _has_strict_blocking_finding_progress(
                            prior_findings, verdict.findings
                        ):
                            stop = HumanStopRequest(
                                HumanStopReason.CONFLICTING_EVIDENCE,
                                "revised artifact did not strictly reduce the blocking "
                                "reviewer finding set",
                                "inspect the preserved reviewer evidence and adjudicate "
                                "the blockers before starting a new run",
                            )
                            ledger.state.update(
                                {
                                    "findings": list(verdict.findings),
                                    "iteration_records": records,
                                }
                            )
                            return _terminal_stop_with_ledger(
                                ledger,
                                kind=selected_kind,
                                artifact=artifact,
                                workspace=workspace,
                                stop=stop,
                                manager=manager,
                                attempt_output_path=review_response_path,
                                attempt_output_sha256=review_response_sha,
                                attempt_status="succeeded",
                            )

                    raw_max_revisions = ledger.state["max_revisions"]
                    if not isinstance(raw_max_revisions, int) or isinstance(
                        raw_max_revisions, bool
                    ):
                        raise MakerCheckerError(
                            "maker-checker revision budget is malformed"
                        )
                    max_revisions = raw_max_revisions
                    if iteration > max_revisions:
                        stop = HumanStopRequest(
                            HumanStopReason.RETRY_BUDGET_EXHAUSTED,
                            "reviewer findings remain after the configured revision budget",
                            "inspect the preserved findings and explicitly start a revised run",
                        )
                        result = _stop_result(
                            run_id=frozen_run_id,
                            kind=selected_kind,
                            iterations=iteration,
                            policy_digest=str(ledger.state["policy_digest"]),
                            binding_digest=str(ledger.state["binding_digest"]),
                            contract_digest=contract_digest,
                            artifact=artifact,
                            workspace=workspace,
                            stop=stop,
                        )
                        result_path = f"{run_rel}/result.json"
                        _persist_json(
                            fs,
                            result_path,
                            {**result.to_dict(), "iteration_records": records},
                        )
                        candidate = deepcopy(ledger.document)
                        _finish_attempt_in_document(
                            candidate,
                            attempt_id,
                            status="succeeded",
                            output_path=review_response_path,
                            output_sha256=review_response_sha,
                        )
                        state = candidate["maker_checker"]
                        assert isinstance(state, dict)
                        state.update(
                            {
                                "findings": list(verdict.findings),
                                "iteration_records": records,
                            }
                        )
                        candidate.update(
                            {
                                "status": "aborted",
                                "stage": "human-stop",
                                "next": stop.requested_action,
                                "aborted_at": _utc_now(),
                                "human_stop": {
                                    "reason": stop.reason.value,
                                    "message": stop.message,
                                    "requested_action": stop.requested_action,
                                },
                                "result_path": result_path,
                                "result_sha256": _bytes_digest(
                                    fs.read_bytes(result_path)
                                ),
                            }
                        )
                        ledger.replace(candidate)
                        _mark_failed(manager, frozen_run_id, stop.message)
                        return result
                    candidate = deepcopy(ledger.document)
                    _finish_attempt_in_document(
                        candidate,
                        attempt_id,
                        status="succeeded",
                        output_path=review_response_path,
                        output_sha256=review_response_sha,
                    )
                    state = candidate["maker_checker"]
                    assert isinstance(state, dict)
                    state.update(
                        {
                            "findings": list(verdict.findings),
                            "iteration_records": records,
                            "iteration": iteration + 1,
                        }
                    )
                    candidate["stage"] = "maker"
                    candidate["next"] = f"revise artifact for iteration {iteration + 1}"
                    ledger.replace(candidate)
                raise MakerCheckerError(
                    "maker-checker active loop ended without a terminal result"
                )
            except _PatchSafetyError as exc:
                return _terminal_stop_with_ledger(
                    ledger,
                    kind=selected_kind,
                    artifact=artifact,
                    workspace=workspace,
                    stop=HumanStopRequest(
                        HumanStopReason.SCOPE_EXPANSION,
                        public_human_stop_text(
                            exc,
                            fallback="maker patch crossed its frozen write boundary",
                        ),
                        "inspect the preserved patch and authorize a narrower safe task",
                    ),
                    manager=manager,
                    attempt_output_path=terminal_attempt_output_path,
                    attempt_output_sha256=terminal_attempt_output_sha256,
                )
            except _ContractViolation as exc:
                return _terminal_stop_with_ledger(
                    ledger,
                    kind=selected_kind,
                    artifact=artifact,
                    workspace=workspace,
                    stop=HumanStopRequest(
                        HumanStopReason.CONFLICTING_EVIDENCE,
                        public_human_stop_text(
                            exc, fallback="worker output violated the frozen contract"
                        ),
                        "inspect the preserved output and retry with a conforming native model",
                    ),
                    manager=manager,
                    attempt_output_path=terminal_attempt_output_path,
                    attempt_output_sha256=terminal_attempt_output_sha256,
                )
            except _CoordinatorStop as halted:
                return _terminal_stop_with_ledger(
                    ledger,
                    kind=selected_kind,
                    artifact=artifact,
                    workspace=workspace,
                    stop=halted.stop,
                    manager=manager,
                    attempt_output_path=terminal_attempt_output_path,
                    attempt_output_sha256=terminal_attempt_output_sha256,
                )
    except ManagedExecutionLeaseHeld as exc:
        raise MakerCheckerError(str(exc)) from exc
    except ExecutionConfigError as exc:
        raise MakerCheckerError(str(exc)) from exc
    except (OSError, ValueError, WorktreeError, UnsafePathError) as exc:
        raise MakerCheckerError(f"maker-checker runtime setup failed: {exc}") from exc


__all__ = [
    "DeliverableKind",
    "FrozenMakerCheckerRun",
    "MAKER_CHECKER_SCHEMA_VERSION",
    "MakerCheckerError",
    "MakerCheckerResult",
    "MakerCheckerStatus",
    "ResolvedWorkerBinding",
    "abort_maker_checker_run",
    "build_routed_dispatcher",
    "confirm_maker_checker_dispatch_terminated",
    "is_maker_checker_snapshot",
    "load_frozen_maker_checker_run",
    "resolve_execution_bindings",
    "run_maker_checker",
    "validate_maker_checker_snapshot",
]
