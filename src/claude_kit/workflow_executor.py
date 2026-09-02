"""Provider-neutral execution of a bound SDLC stage graph.

The executor knows stages, dependencies, declared fork/join groups, retry
budgets, evidence references, gates, and portable human stops. Provider wire
details remain behind :class:`claude_kit.dispatch.Dispatcher`; durable stage and
gate state remains behind ``StageLedger``.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
from contextlib import ExitStack
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Callable, Mapping, Optional, Protocol, Sequence, runtime_checkable

import yaml

from claude_kit import catalog, pipeline, scaffold
from claude_kit.components import Capability, SymbolicRef
from claude_kit.dispatch import (
    Dispatcher,
    DispatchHandle,
    DispatchRequest,
    DispatchResult,
    DispatchStatus,
    HumanStopReason,
    HumanStopRequest,
    WaitMode,
)
from claude_kit.execution_lease import (
    ManagedExecutionLeaseHeld,
    managed_execution_lease,
)
from claude_kit.models import InitOptions, ResolvedPlan
from claude_kit.process_dispatch import (
    ClaudeProcessDispatcher,
    CodexProcessDispatcher,
    DispatchAdapterError,
    FilesystemNativeRoleLoader,
    RoleUnavailableError,
    UnsupportedCapabilityError,
)
from claude_kit.projection import Provider
from claude_kit.secure_fs import ProjectFS
from claude_kit.state import detect_state_layout
from claude_kit.workflow_evidence import (
    EvidenceValidationError,
    normalized_findings,
    parse_evidence_envelope,
    stage_instruction,
)
from claude_kit.workflows import (
    BoundWorkflow,
    StageExecutionKind,
    WorkflowMode,
    WorkflowStageDefinition,
    WorkflowValidationError,
    workflow_definition_digest,
)
from claude_kit.worktrees import WorktreeManager, WorktreeStatus

_MAX_DEPENDENCY_HANDOFF_BYTES = 524_288
_MAX_STAGE_ARTIFACT_BYTES = 8 * 1024 * 1024
_MAX_MUTABLE_CONTEXT_BYTES = 131_072
_MAX_MUTABLE_CONTEXT_FILES = 256


class WorkflowExecutionStatus(str, Enum):
    """Terminal/checkpoint outcomes from one bounded executor invocation."""

    SUCCEEDED = "succeeded"
    WAITING_GATE = "waiting-gate"
    HUMAN_STOP = "human-stop"
    FAILED = "failed"


@dataclass(frozen=True)
class StageArtifactRef:
    """Public, metadata-only reference to one private dispatch artifact."""

    path: str
    sha256: str
    truncated: bool
    category: str


@dataclass(frozen=True)
class StageExecution:
    """One stage attempt observed during this invocation."""

    stage: str
    role: str
    handle: DispatchHandle
    status: DispatchStatus
    evidence: tuple[SymbolicRef, ...] = ()
    error: Optional[str] = None
    artifact: Optional[StageArtifactRef] = None


@dataclass(frozen=True)
class WorkflowExecutionResult:
    """Portable result of running until completion or a mandatory checkpoint."""

    status: WorkflowExecutionStatus
    completed_stages: tuple[str, ...]
    skipped_stages: tuple[str, ...]
    attempts: tuple[StageExecution, ...]
    pending_gates: tuple[str, ...] = ()
    human_stop: Optional[HumanStopRequest] = None
    messages: tuple[str, ...] = ()


@dataclass(frozen=True)
class _AttemptDisposition:
    """Internal retry classification after a terminal worker result is durable."""

    error: Optional[str]
    retryable: bool


@runtime_checkable
class StageLedger(Protocol):
    """Authoritative persistence seam used before and after every host process."""

    def completed_stage_ids(self) -> frozenset[str]:
        """Return stages already completed in this shared run."""
        ...

    def skipped_stage_ids(self) -> frozenset[str]:
        """Return stages durably attested as skipped by a frozen false condition."""
        ...

    def resolved_gate_ids(self) -> frozenset[str]:
        """Return gates already resolved in this shared run."""
        ...

    def condition_decisions(self) -> Mapping[str, bool]:
        """Return stable workflow decisions already frozen for this run."""
        ...

    def bind_condition_decisions(
        self, decisions: Mapping[str, bool]
    ) -> Mapping[str, bool]:
        """Freeze decisions once, or verify the supplied set is identical."""
        ...

    def dependency_context(self, stage: WorkflowStageDefinition) -> str:
        """Return verified, bounded root-owned artifacts from direct dependencies."""
        ...

    def attest_skip(
        self,
        stage: WorkflowStageDefinition,
        dependency_states: Mapping[str, str],
    ) -> None:
        """Persist one canonical false-condition skip after dependencies settle."""
        ...

    def claim(self, stage: WorkflowStageDefinition, handle: DispatchHandle) -> None:
        """Atomically reserve a stage attempt before its prompt is submitted."""
        ...

    def finish(
        self, stage: WorkflowStageDefinition, result: DispatchResult
    ) -> Optional[StageArtifactRef]:
        """Atomically finish the exact claimed attempt and return private artifact metadata."""
        ...

    def attest_completion(self, active_stages: Sequence[str]) -> None:
        """Persist that the complete selected graph has terminally settled."""
        ...

    def pause(self, stop: HumanStopRequest) -> None:
        """Persist a mandatory human stop."""
        ...


@runtime_checkable
class OwnedWorkspaceResolver(Protocol):
    """Resolve the bounded workspace owned by a stage attempt."""

    def resolve(self, stage: WorkflowStageDefinition, role: str) -> Path:
        """Return a project workspace or a separately registered owned worktree."""
        ...


class ProjectWorkspaceResolver:
    """Default resolver for stages that do not require a separate worktree."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = Path(project_root).resolve(strict=True)

    def resolve(self, stage: WorkflowStageDefinition, role: str) -> Path:
        del stage, role
        return self.project_root


class ManagedWorktreeResolver:
    """Create/reuse one run-owned integration worktree for every stage."""

    WORKER_ID = "managed-workflow"

    def __init__(
        self,
        project_root: Path,
        run_id: str,
        *,
        manager: Optional[WorktreeManager] = None,
        _managed_lease_held: bool = False,
    ) -> None:
        self.project_root = Path(project_root).resolve(strict=True)
        self.run_id = run_id
        self.manager = manager or WorktreeManager(self.project_root)
        self._managed_lease_held = _managed_lease_held

    @property
    def allowed_roots(self) -> tuple[Path, ...]:
        return (self.manager.container,)

    def _with_managed_lease(self) -> ManagedWorktreeResolver:
        """Return a resolver authorized by the caller's managed lease.

        ``execute_bound_workflow`` accepts a caller-supplied resolver so one
        provider can resume work created by another.  The public resolver must
        remain safe to use outside that call, so do not mutate its lease flag in
        place; share only its already-bound manager with an invocation-local
        resolver.
        """

        if self._managed_lease_held:
            return self
        return ManagedWorktreeResolver(
            self.project_root,
            self.run_id,
            manager=self.manager,
            _managed_lease_held=True,
        )

    def ensure_workspace(self) -> Path:
        """Create once, then verify and reuse across gate pauses and resumes."""
        matches = [
            record
            for record in self.manager.records(self.run_id)
            if record.worker_id == self.WORKER_ID
        ]
        if matches:
            record = matches[0]
            if record.status is WorktreeStatus.REMOVED:
                raise WorkflowValidationError(
                    f"owned worktree {self.run_id}/{self.WORKER_ID} was already removed"
                )
            record = (
                self.manager.create(
                    self.run_id,
                    self.WORKER_ID,
                    base_ref=record.base_ref,
                    _managed_lease_held=self._managed_lease_held,
                )
                if record.status is WorktreeStatus.CREATING
                else self.manager.verify(self.run_id, self.WORKER_ID)
            )
        else:
            record = self.manager.create(
                self.run_id,
                self.WORKER_ID,
                _managed_lease_held=self._managed_lease_held,
            )
        try:
            source_head = subprocess.run(
                ["git", "-C", str(self.project_root), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError) as exc:
            raise WorkflowValidationError(
                f"cannot verify managed source HEAD: {exc}"
            ) from exc
        if source_head != record.base_commit:
            raise WorkflowValidationError(
                "source checkout HEAD changed after the managed worktree was created; "
                "abort/restart the run so provider configuration and application inputs "
                "cannot diverge"
            )
        workspace = (self.project_root / record.target_path).resolve(strict=True)
        if workspace == self.project_root:
            raise WorkflowValidationError(
                "managed worktree resolved to the project root"
            )
        return workspace

    def resolve(self, stage: WorkflowStageDefinition, role: str) -> Path:
        del stage, role
        return self.ensure_workspace()

    def binding(self) -> dict[str, str]:
        """Return the portable identity frozen into the managed run contract."""

        self.ensure_workspace()
        record = self.manager.verify(self.run_id, self.WORKER_ID)
        return {
            "worker_id": record.worker_id,
            "target_path": record.target_path,
            "base_commit": record.base_commit,
        }

    def checkpoint(self) -> dict[str, object]:
        """Return the stable, exact content identity of the integration tree."""

        self.ensure_workspace()
        return self.manager.checkpoint(self.run_id, self.WORKER_ID).to_dict()

    @property
    def serializes_disjoint_writes(self) -> bool:
        """One integration tree trades parallel writes for coherent visibility."""
        return True


class PipelineStageLedger:
    """Stage ledger backed by the shared provider-neutral pipeline snapshot."""

    def __init__(
        self,
        project_root: Path,
        workspace_resolver: Optional[ManagedWorktreeResolver] = None,
    ) -> None:
        self.project_root = Path(project_root).resolve(strict=True)
        self.workspace_resolver = workspace_resolver

    @staticmethod
    def _require(ok: bool, messages: Sequence[str]) -> None:
        if not ok:
            raise WorkflowValidationError("; ".join(messages))

    def completed_stage_ids(self) -> frozenset[str]:
        completed, error = pipeline.completed_stage_ids(self.project_root)
        if error:
            raise WorkflowValidationError(error)
        return frozenset(completed)

    def skipped_stage_ids(self) -> frozenset[str]:
        skipped, error = pipeline.skipped_stage_ids(self.project_root)
        if error:
            raise WorkflowValidationError(error)
        return frozenset(skipped)

    def resolved_gate_ids(self) -> frozenset[str]:
        document, error = pipeline.snapshot_document(self.project_root)
        if error:
            raise WorkflowValidationError(error)
        if not isinstance(document, dict):
            return frozenset()
        resolved = {
            str(entry.get("gate"))
            for entry in document.get("gate_history", [])
            if isinstance(entry, dict)
            and entry.get("status") in {"passed", "not-applicable", "accepted-risk"}
        }
        return frozenset(resolved)

    def condition_decisions(self) -> Mapping[str, bool]:
        decisions, error = pipeline.workflow_condition_decisions(self.project_root)
        if error:
            raise WorkflowValidationError(error)
        return decisions

    def bind_condition_decisions(
        self, decisions: Mapping[str, bool]
    ) -> Mapping[str, bool]:
        frozen, error = pipeline.bind_workflow_condition_decisions(
            self.project_root, decisions
        )
        if error or frozen is None:
            raise WorkflowValidationError(
                error or "condition decisions were not frozen"
            )
        return frozen

    def dependency_context(self, stage: WorkflowStageDefinition) -> str:
        needs_closeout = "closeout-record" in stage.evidence
        if not stage.depends_on and not needs_closeout:
            return ""
        document, error = pipeline.snapshot_document(self.project_root)
        if error or not isinstance(document, dict):
            raise WorkflowValidationError(
                error or "dependency handoff requires an active pipeline snapshot"
            )
        history = document.get("stage_history")
        if not isinstance(history, list):
            raise WorkflowValidationError("dependency stage ledger is malformed")
        fs = ProjectFS(self.project_root)
        layout = detect_state_layout(self.project_root)
        rendered: list[str] = []
        total = 0
        for dependency in stage.depends_on:
            matches = [
                record
                for record in history
                if isinstance(record, dict)
                and record.get("stage") == dependency
                and record.get("status") == "succeeded"
            ]
            if not matches:
                skipped, skipped_error = pipeline.skipped_stage_attestation(
                    self.project_root, dependency
                )
                if skipped_error:
                    raise WorkflowValidationError(skipped_error)
                if skipped is None:
                    raise WorkflowValidationError(
                        f"dependency {dependency!r} is neither successful nor "
                        "durably skipped"
                    )
                block = (
                    f"Dependency stage {dependency!r} was durably skipped; "
                    f"condition={skipped['condition']!r}; decision=false; "
                    f"attestation_sha256={skipped['attestation_sha256']}."
                )
                total += len(block.encode("utf-8"))
                if total > _MAX_DEPENDENCY_HANDOFF_BYTES:
                    raise WorkflowValidationError(
                        "dependency skip attestations exceed the 512 KiB prompt safety limit"
                    )
                rendered.append(block)
                continue
            if len(matches) != 1:
                raise WorkflowValidationError(
                    f"dependency {dependency!r} has multiple successful stage artifacts"
                )
            record = matches[0]
            output_path = record.get("output_path")
            artifact_sha = record.get("output_artifact_sha256")
            if (
                not isinstance(output_path, str)
                or not output_path.startswith(layout.artifacts + "/dispatch/")
                or not isinstance(artifact_sha, str)
            ):
                raise WorkflowValidationError(
                    f"dependency {dependency!r} has no root-owned output artifact"
                )
            try:
                artifact, actual_sha, _artifact_size = (
                    pipeline._read_managed_file_bounded(  # noqa: SLF001
                        fs,
                        output_path,
                        maximum_bytes=_MAX_STAGE_ARTIFACT_BYTES,
                    )
                )
            except (FileNotFoundError, OSError, ValueError) as exc:
                raise WorkflowValidationError(
                    f"dependency {dependency!r} output artifact is unavailable: {exc}"
                ) from exc
            if actual_sha != artifact_sha:
                raise WorkflowValidationError(
                    f"dependency {dependency!r} output artifact hash mismatch"
                )
            try:
                artifact_document = json.loads(artifact)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise WorkflowValidationError(
                    f"dependency {dependency!r} output artifact is malformed"
                ) from exc
            if not isinstance(artifact_document, dict) or (
                artifact_document.get("stage") != dependency
            ):
                raise WorkflowValidationError(
                    f"dependency {dependency!r} output artifact identity mismatch"
                )
            output = artifact_document.get("output")
            output_sha = record.get("output_sha256")
            if output is not None and (
                not isinstance(output, str)
                or hashlib.sha256(output.encode("utf-8")).hexdigest() != output_sha
            ):
                raise WorkflowValidationError(
                    f"dependency {dependency!r} output content hash mismatch"
                )
            header = (
                f"Dependency stage {dependency!r}; root artifact {output_path}; "
                f"artifact_sha256={artifact_sha}; output_sha256={output_sha}:\n"
            )
            output_text = output if isinstance(output, str) else "(no textual output)"
            remaining = (
                _MAX_DEPENDENCY_HANDOFF_BYTES - total - len(header.encode("utf-8"))
            )
            if remaining <= 0:
                raise WorkflowValidationError(
                    "dependency metadata exceeds the 512 KiB prompt safety limit"
                )
            output_bytes = output_text.encode("utf-8")
            if len(output_bytes) > remaining:
                marker = (
                    "\n[dependency output prefix truncated; use the authenticated "
                    f"root artifact {output_path} for the full record]"
                ).encode("utf-8")
                prefix_limit = max(0, remaining - len(marker))
                safe_prefix = output_bytes[:prefix_limit].decode(
                    "utf-8", errors="ignore"
                )
                output_bytes = safe_prefix.encode("utf-8") + marker
            block = header + output_bytes.decode("utf-8")
            total += len(block.encode("utf-8"))
            rendered.append(block)
        if needs_closeout:
            gates, risks, closeout_problem = pipeline._managed_closeout_projection(  # noqa: SLF001
                fs, document
            )
            if closeout_problem:
                raise WorkflowValidationError(closeout_problem)
            closeout = json.dumps(
                {"gates": gates, "accepted-risks": risks},
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            block = (
                "Authoritative closeout ledger (repeat gates and accepted-risks "
                f"exactly in closeout-record): {closeout}"
            )
            total += len(block.encode("utf-8"))
            if total > _MAX_DEPENDENCY_HANDOFF_BYTES:
                raise WorkflowValidationError(
                    "closeout ledger exceeds the 512 KiB prompt safety limit"
                )
            rendered.append(block)
        return "\n".join(rendered)

    def attest_skip(
        self,
        stage: WorkflowStageDefinition,
        dependency_states: Mapping[str, str],
    ) -> None:
        workspace_checkpoint = (
            self.workspace_resolver.checkpoint()
            if self.workspace_resolver is not None
            else None
        )
        ok, messages = pipeline.attest_skipped_stage(
            self.project_root,
            stage=stage.id,
            condition=stage.condition,
            dependencies=stage.depends_on,
            dependency_states=dependency_states,
            workspace_checkpoint=workspace_checkpoint,
        )
        self._require(ok, messages)

    def claim(self, stage: WorkflowStageDefinition, handle: DispatchHandle) -> None:
        ok, messages = pipeline.claim_stage(
            self.project_root,
            stage=stage.id,
            role=handle.route,
            provider=handle.provider or "unknown",
            dispatch_id=handle.id,
            attempt=handle.attempt,
            required_capabilities=tuple(
                capability.value for capability in handle.required_capabilities
            ),
            attested_capabilities=tuple(
                capability.value for capability in handle.attested_capabilities
            ),
        )
        self._require(ok, messages)

    def finish(
        self, stage: WorkflowStageDefinition, result: DispatchResult
    ) -> Optional[StageArtifactRef]:
        output_sha256 = (
            hashlib.sha256(result.output.encode("utf-8")).hexdigest()
            if result.output is not None
            else None
        )
        layout = detect_state_layout(self.project_root)
        document, snapshot_error = pipeline.snapshot_document(self.project_root)
        if snapshot_error:
            raise WorkflowValidationError(snapshot_error)
        managed = (
            isinstance(document, dict) and document.get("managed_execution") is not None
        )
        run_id: str | None = None
        ledger_attempt: int | None = None
        if managed:
            assert isinstance(document, dict)
            run_id = document.get("run_id")
            history = document.get("stage_history")
            matches = (
                [
                    record
                    for record in history
                    if isinstance(record, dict)
                    and record.get("stage") == stage.id
                    and record.get("dispatch_id") == result.handle.id
                    and record.get("dispatch_attempt") == result.handle.attempt
                    and record.get("status") == "running"
                ]
                if isinstance(history, list)
                else []
            )
            if (
                not isinstance(run_id, str)
                or len(matches) != 1
                or not isinstance(matches[0].get("attempt"), int)
            ):
                raise WorkflowValidationError(
                    "managed terminal artifact has no exact running ledger attempt"
                )
            ledger_attempt = int(matches[0]["attempt"])
        workspace_checkpoint = (
            self.workspace_resolver.checkpoint()
            if self.workspace_resolver is not None
            else None
        )
        evidence_records: tuple[dict[str, object], ...] = ()
        if managed and result.status in {
            DispatchStatus.SUCCEEDED,
            DispatchStatus.FAILED,
        }:
            materialized, materialize_error = (
                pipeline.materialize_managed_stage_evidence(
                    self.project_root,
                    stage=stage.id,
                    dispatch_id=result.handle.id,
                    dispatch_attempt=result.handle.attempt,
                    output=result.output,
                    require_pass=result.status is DispatchStatus.SUCCEEDED,
                )
            )
            if materialize_error or materialized is None:
                if result.status is DispatchStatus.SUCCEEDED:
                    raise WorkflowValidationError(
                        materialize_error
                        or "managed stage evidence was not materialized"
                    )
            else:
                evidence_records = tuple(materialized)
        artifact_document = {
            "schema_version": 1,
            "run_id": run_id,
            "stage": stage.id,
            "ledger_attempt": ledger_attempt,
            "provider": result.handle.provider,
            "route": result.handle.route,
            "dispatch_id": result.handle.id,
            "dispatch_attempt": result.handle.attempt,
            "status": result.status.value,
            "output": result.output,
            "error": result.error,
            "evidence": [reference.uri for reference in result.evidence],
            "evidence_records": list(evidence_records),
            "workspace_checkpoint": workspace_checkpoint,
        }
        fs = ProjectFS(self.project_root)
        if managed:
            if run_id is None or ledger_attempt is None:  # pragma: no cover - guarded
                raise WorkflowValidationError("managed artifact identity was lost")
            template = pipeline._managed_dispatch_artifact_relative(  # noqa: SLF001
                run_id,
                stage.id,
                ledger_attempt,
                "{sha256}",
                layout=layout,
            )
            output_path, artifact_sha256 = (
                pipeline._write_private_content_addressed_json(  # noqa: SLF001
                    fs,
                    template,
                    artifact_document,
                )
            )
        else:
            token = hashlib.sha256(
                f"{result.handle.id}:{result.handle.attempt}".encode("utf-8")
            ).hexdigest()[:16]
            output_path = f"{layout.artifacts}/dispatch/{stage.id}-{token}.json"
            artifact = (
                json.dumps(
                    artifact_document,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            ).encode("utf-8")
            fs.write_bytes(output_path, artifact, mode=0o600)
            artifact_sha256 = hashlib.sha256(artifact).hexdigest()
        ok, messages = pipeline.finish_stage(
            self.project_root,
            stage=stage.id,
            dispatch_id=result.handle.id,
            attempt=result.handle.attempt,
            status=result.status.value,
            output_sha256=output_sha256,
            output_path=output_path,
            output_artifact_sha256=artifact_sha256,
            workspace_checkpoint=workspace_checkpoint,
            evidence=tuple(reference.uri for reference in result.evidence),
            evidence_records=evidence_records,
            error=result.error,
        )
        self._require(ok, messages)
        return StageArtifactRef(
            path=output_path,
            sha256=artifact_sha256,
            truncated=bool(
                result.error and "captured prefix truncated" in result.error
            ),
            category=result.status.value,
        )

    def attest_completion(self, active_stages: Sequence[str]) -> None:
        workspace_checkpoint = (
            self.workspace_resolver.checkpoint()
            if self.workspace_resolver is not None
            else None
        )
        ok, messages = pipeline.attest_managed_workflow_completion(
            self.project_root,
            active_stages=tuple(active_stages),
            workspace_checkpoint=workspace_checkpoint,
        )
        self._require(ok, messages)

    def pause(self, stop: HumanStopRequest) -> None:
        ok, messages = pipeline.pause_for_human(
            self.project_root,
            reason=stop.reason.value,
            message=stop.message,
            requested_action=stop.requested_action,
        )
        self._require(ok, messages)


class WorkflowExecutor:
    """Run one bound workflow deterministically through a ``Dispatcher``."""

    _DYNAMIC_CONDITIONS = frozenset(
        {
            "all-active-gates-closed",
            "fast-track-gates-closed",
            "all-waves-and-gates-closed",
        }
    )

    def __init__(
        self,
        workflow: BoundWorkflow,
        dispatcher: Dispatcher,
        ledger: StageLedger,
        *,
        mode: str,
        objective: str,
        context: str = "",
        runtime_context_provider: Optional[Callable[[], str]] = None,
        required_capability_overrides: Optional[
            Mapping[str, Sequence[Capability]]
        ] = None,
        role_overrides: Optional[Mapping[str, str]] = None,
        conditions: Optional[Mapping[str, bool]] = None,
        workspace_resolver: Optional[OwnedWorkspaceResolver] = None,
        wait_timeout_seconds: float = 900.0,
    ) -> None:
        if not objective.strip():
            raise ValueError("workflow objective must be non-empty")
        if wait_timeout_seconds <= 0:
            raise ValueError("wait_timeout_seconds must be positive")
        self.workflow = workflow
        self.dispatcher = dispatcher
        self.ledger = ledger
        self.mode = self._mode(mode)
        self.active_gate_ids = self.workflow.gate_ids_for_mode(self.mode.id)
        self.active_gate_digest = self.workflow.gate_definition_digest_for_mode(
            self.mode.id
        )
        self.gate_owner_stages = self.workflow.gate_owner_stages_for_mode(self.mode.id)
        selected_stages = self.workflow.stages_for_mode(self.mode.id)
        selected_ids = {stage.id for stage in selected_stages}
        implicit: dict[str, list[str]] = {stage.id: [] for stage in selected_stages}
        for group in self.workflow.definition.parallel_groups.values():
            if group.join_before not in selected_ids:
                continue
            for lane in group.lanes:
                active_lane = tuple(
                    item for item in lane.stages if item in selected_ids
                )
                if active_lane:
                    implicit[group.join_before].append(active_lane[-1])
        self.stages = tuple(
            replace(
                stage,
                depends_on=tuple(
                    dict.fromkeys(stage.depends_on + tuple(implicit[stage.id]))
                ),
            )
            for stage in selected_stages
        )
        self.objective = objective.strip()
        self.context = context
        self.runtime_context_provider = runtime_context_provider
        raw_overrides = dict(required_capability_overrides or {})
        unknown_override_stages = set(raw_overrides) - selected_ids
        if unknown_override_stages:
            raise WorkflowValidationError(
                "required capability overrides name inactive stages: "
                + ", ".join(sorted(unknown_override_stages))
            )
        self.required_capability_overrides = {
            stage_id: tuple(
                sorted(
                    (
                        value if isinstance(value, Capability) else Capability(value)
                        for value in values
                    ),
                    key=lambda item: item.value,
                )
            )
            for stage_id, values in raw_overrides.items()
        }
        raw_role_overrides = dict(role_overrides or {})
        unknown_role_stages = set(raw_role_overrides) - selected_ids
        if unknown_role_stages:
            raise WorkflowValidationError(
                "role overrides name inactive stages: "
                + ", ".join(sorted(unknown_role_stages))
            )
        if any(
            not isinstance(role, str) or not role.strip()
            for role in raw_role_overrides.values()
        ):
            raise WorkflowValidationError("role overrides must be non-empty role ids")
        self.role_overrides = raw_role_overrides
        self.conditions = dict(conditions or {})
        self.workspace_resolver = workspace_resolver
        self.wait_timeout_seconds = wait_timeout_seconds

    def _mode(self, value: str) -> WorkflowMode:
        matches = [
            mode
            for mode in self.workflow.definition.modes.values()
            if mode.id == value or mode.code == value
        ]
        if len(matches) != 1:
            raise WorkflowValidationError(
                f"workflow mode must name exactly one id or code: {value!r}"
            )
        return matches[0]

    def _condition(
        self, condition: str, resolved_gates: frozenset[str]
    ) -> Optional[bool]:
        if condition == "always":
            return True
        if condition == "full-sdlc-or-program":
            return self.mode.code in {"A", "B", "C", "E"}
        if condition == "fast-track-selected":
            return self.mode.code == "D"
        if condition == "program-mode-selected":
            return self.mode.code == "E"
        if condition == "security-gate-active":
            return "security-clear" in self.active_gate_ids
        if condition == "acceptance-gate-active":
            return "acceptance" in self.active_gate_ids
        if condition == "all-active-gates-closed":
            return set(self.active_gate_ids).issubset(resolved_gates)
        if condition == "fast-track-gates-closed":
            return set(self.mode.gates).issubset(resolved_gates)
        if condition == "all-waves-and-gates-closed" and self.mode.code != "E":
            return False
        return self.conditions.get(condition)

    def _pending_owned_gate(
        self,
        stage_by_id: Mapping[str, WorkflowStageDefinition],
        completed: set[str],
        skipped: set[str],
        resolved_gates: frozenset[str],
    ) -> tuple[str, ...]:
        """Return the next owner-settled gate in the frozen active order.

        A mode may replace the canonical gate owner (fast-track does this for
        both of its gates), so stage-local ``gates`` metadata is not
        authoritative here.  Only the first unresolved gate can be surfaced;
        this preserves a checkpoint between successive owning stages even if
        later owners were completed by the same resumable execution graph.
        """
        for gate_id in self.active_gate_ids:
            if gate_id in resolved_gates:
                continue
            owner_id = self.gate_owner_stages[gate_id]
            if owner_id in completed:
                return (gate_id,)
            if owner_id in skipped:
                owner = stage_by_id[owner_id]
                dependencies_settled = all(
                    dependency not in stage_by_id
                    or dependency in completed
                    or dependency in skipped
                    for dependency in owner.depends_on
                )
                if dependencies_settled:
                    return (gate_id,)
            # Gate order is authoritative: never expose a later gate before
            # the first unresolved gate's owner has settled.
            return ()
        return ()

    def _bind_stable_conditions(
        self,
        stages: Sequence[WorkflowStageDefinition],
        resolved_gates: frozenset[str],
    ) -> Mapping[str, bool]:
        persisted = dict(self.ledger.condition_decisions())
        stage_conditions = {
            stage.condition for stage in stages if stage.condition != "always"
        }
        unknown_inputs = set(self.conditions) - stage_conditions
        if unknown_inputs:
            names = ", ".join(sorted(unknown_inputs))
            raise WorkflowValidationError(
                f"condition input does not belong to the selected stage graph: {names}"
            )
        stable = tuple(
            dict.fromkeys(
                stage.condition
                for stage in stages
                if stage.condition != "always"
                and stage.condition not in self._DYNAMIC_CONDITIONS
            )
        )
        decisions: dict[str, bool] = {}
        for condition in stable:
            decision = self._condition(condition, resolved_gates)
            if decision is None and condition in persisted:
                decision = persisted[condition]
            if decision is None:
                raise WorkflowValidationError(
                    f"condition {condition!r} has no explicit decision"
                )
            decisions[condition] = decision
        if self.mode.code != "E" and "all-waves-and-gates-closed" in stage_conditions:
            decisions["all-waves-and-gates-closed"] = False
        frozen = dict(self.ledger.bind_condition_decisions(decisions))
        if frozen != decisions:
            raise WorkflowValidationError(
                "shared ledger returned different workflow condition decisions"
            )
        return frozen

    def _stop(
        self,
        reason: HumanStopReason,
        message: str,
        requested_action: str,
        *,
        completed: Sequence[str],
        skipped: Sequence[str],
        attempts: Sequence[StageExecution],
    ) -> WorkflowExecutionResult:
        stop = HumanStopRequest(reason, message, requested_action)
        self.ledger.pause(stop)
        return WorkflowExecutionResult(
            WorkflowExecutionStatus.HUMAN_STOP,
            tuple(completed),
            tuple(skipped),
            tuple(attempts),
            human_stop=stop,
            messages=(message,),
        )

    def _request(self, stage: WorkflowStageDefinition, role: str) -> DispatchRequest:
        workspace = (
            self.workspace_resolver.resolve(stage, role)
            if self.workspace_resolver is not None
            else None
        )
        lane = stage.parallel_group or "control"
        dependency_context = self.ledger.dependency_context(stage)
        evidence_context = (
            f"Managed execution mode: {self.mode.code}.\n"
            + stage_instruction(
                expected_ids=stage.evidence,
                requirements=self.workflow.definition.evidence_requirements,
            )
        )
        runtime_context = (
            self.runtime_context_provider()
            if self.runtime_context_provider is not None
            else ""
        )
        context = "\n\n".join(
            part
            for part in (
                self.context,
                runtime_context,
                dependency_context,
                evidence_context,
            )
            if part.strip()
        )
        return DispatchRequest(
            route=role,
            objective=f"Stage {stage.id}: {self.objective}",
            lane=lane,
            dependencies=tuple(
                SymbolicRef.parse(f"stage://{dependency}")
                for dependency in stage.depends_on
            ),
            evidence=tuple(
                SymbolicRef.parse(f"artifact://{evidence}")
                for evidence in stage.evidence
            ),
            retry_budget=stage.retry_budget,
            context=context,
            required_capabilities=self.required_capability_overrides.get(
                stage.id, tuple(stage.required_capabilities)
            ),
            workspace=str(workspace) if workspace is not None else None,
        )

    def _attest_ready_skips(
        self,
        *,
        stage_by_id: Mapping[str, WorkflowStageDefinition],
        candidates: set[str],
        completed: set[str],
        skipped: set[str],
    ) -> None:
        """Persist every false conditional whose effective dependencies settled."""

        progress = True
        while progress:
            progress = False
            for stage in self.stages:
                if stage.id not in candidates:
                    continue
                states: dict[str, str] = {}
                unsettled = False
                for dependency in stage.depends_on:
                    if dependency not in stage_by_id:
                        states[dependency] = "inactive"
                    elif dependency in completed:
                        states[dependency] = "succeeded"
                    elif dependency in skipped:
                        states[dependency] = "skipped"
                    else:
                        unsettled = True
                        break
                if unsettled:
                    continue
                self.ledger.attest_skip(stage, states)
                skipped.add(stage.id)
                candidates.remove(stage.id)
                progress = True

    def _spawn(self, stage: WorkflowStageDefinition) -> DispatchHandle:
        route = self.workflow.definition.roles[stage.route]
        unavailable: list[str] = []
        frozen_role = self.role_overrides.get(stage.id)
        candidates = (
            (frozen_role,)
            if frozen_role is not None
            else (route.primary,) + route.fallbacks
        )
        for role in candidates:
            try:
                return self.dispatcher.spawn(self._request(stage, role))
            except UnsupportedCapabilityError as exc:
                # Capability failure is not role unavailability. Falling back
                # would silently weaken the stage's permission/effect contract
                # (notably external-effect closeout routes).
                raise exc
            except RoleUnavailableError as exc:
                unavailable.append(str(exc))
        raise RoleUnavailableError(
            f"route {stage.route!r} has no installed native role: "
            + "; ".join(unavailable)
        )

    def _claim(self, stage: WorkflowStageDefinition, handle: DispatchHandle) -> None:
        try:
            self.ledger.claim(stage, handle)
        except BaseException:
            try:
                self.dispatcher.cancel(handle, "stage ledger claim failed")
            except BaseException:
                pass
            raise

    def _await(self, handles: Sequence[DispatchHandle]) -> tuple[DispatchResult, ...]:
        waited = self.dispatcher.wait(
            handles,
            WaitMode.ALL,
            timeout_seconds=self.wait_timeout_seconds,
        )
        if waited.timed_out:
            for handle in waited.pending:
                self.dispatcher.cancel(handle, "workflow wait timeout")
        results = self.dispatcher.collect(handles)
        if len(results) != len(handles) or tuple(
            result.handle for result in results
        ) != tuple(handles):
            raise DispatchAdapterError(
                "dispatcher returned results for a different attempt set"
            )
        return results

    def _cancel_launched(
        self,
        launched: Sequence[tuple[WorkflowStageDefinition, DispatchHandle]],
        attempts: list[StageExecution],
        reason: str,
    ) -> tuple[str, ...]:
        """Best-effort terminalize every claimed process and persist each outcome."""
        closure_errors: list[str] = []
        for stage, handle in launched:
            cancel_error: Optional[BaseException] = None
            try:
                self.dispatcher.cancel(handle, reason)
            except BaseException as exc:
                cancel_error = exc
            try:
                result = self.dispatcher.collect((handle,))[0]
                artifact = self.ledger.finish(stage, result)
                attempts.append(
                    StageExecution(
                        stage.id,
                        handle.route,
                        handle,
                        result.status,
                        result.evidence,
                        result.error,
                        artifact,
                    )
                )
            except BaseException as exc:
                detail = f"stage {stage.id!r} could not be terminalized: {exc}"
                if cancel_error is not None:
                    detail += f" (cancel also failed: {cancel_error})"
                closure_errors.append(detail)
        return tuple(closure_errors)

    def _dispatch_error_stop(
        self,
        exc: Exception,
        launched: Sequence[tuple[WorkflowStageDefinition, DispatchHandle]],
        attempts: list[StageExecution],
        *,
        completed: Sequence[str],
        skipped: Sequence[str],
        phase: str,
    ) -> WorkflowExecutionResult:
        closure_errors = self._cancel_launched(
            launched, attempts, f"{phase} failed: {exc}"
        )
        message = f"{phase} failed: {exc}"
        if closure_errors:
            message += "; " + "; ".join(closure_errors)
        return self._stop(
            HumanStopReason.CONFLICTING_EVIDENCE,
            message,
            "inspect the shared running-attempt ledger and recover or abort explicitly",
            completed=completed,
            skipped=skipped,
            attempts=attempts,
        )

    def _terminalize_collected_results(
        self,
        collected: Sequence[tuple[WorkflowStageDefinition, DispatchResult]],
        attempts: list[StageExecution],
        reason: str,
    ) -> None:
        """Best-effort ledger closure after collected-result persistence is interrupted.

        The native workers represented by these results are already terminal, so
        this deliberately does not call ``dispatcher.cancel``.  A cancellation
        record is only a conservative ledger disposition for a result that the
        coordinator could not acknowledge durably.
        """

        for stage, result in collected:
            fallback = DispatchResult(
                result.handle,
                DispatchStatus.CANCELLED,
                error=reason,
            )
            try:
                artifact = self.ledger.finish(stage, fallback)
                attempts.append(
                    StageExecution(
                        stage.id,
                        fallback.handle.route,
                        fallback.handle,
                        fallback.status,
                        fallback.evidence,
                        fallback.error,
                        artifact,
                    )
                )
            except BaseException:
                pass

    def _finish_attempt(
        self,
        stage: WorkflowStageDefinition,
        result: DispatchResult,
        attempts: list[StageExecution],
    ) -> _AttemptDisposition:
        expected = {SymbolicRef.parse(f"artifact://{item}") for item in stage.evidence}
        returned = set(result.evidence)
        missing = expected - returned
        unexpected = returned - expected
        duplicates = len(returned) != len(result.evidence)
        effective = result
        evidence_error: str | None = None
        typed_observation = False
        pass_problem: str | None = None
        try:
            payloads = parse_evidence_envelope(
                result.output,
                expected_ids=stage.evidence,
                requirements=self.workflow.definition.evidence_requirements,
                findings_policy=self.workflow.definition.findings_policy,
                mode=self.mode.code,
                require_pass=False,
            )
            normalized_findings(payloads)
            typed_observation = True
            try:
                parse_evidence_envelope(
                    result.output,
                    expected_ids=stage.evidence,
                    requirements=self.workflow.definition.evidence_requirements,
                    findings_policy=self.workflow.definition.findings_policy,
                    mode=self.mode.code,
                    require_pass=True,
                )
            except EvidenceValidationError as exc:
                pass_problem = str(exc)
        except EvidenceValidationError as exc:
            if result.status is DispatchStatus.SUCCEEDED:
                evidence_error = f"invalid structured stage evidence: {exc}"

        if result.status is DispatchStatus.SUCCEEDED and (
            missing or unexpected or duplicates
        ):
            details: list[str] = []
            if missing:
                details.append(
                    "missing "
                    + ", ".join(sorted(reference.uri for reference in missing))
                )
            if unexpected:
                details.append(
                    "unexpected "
                    + ", ".join(sorted(reference.uri for reference in unexpected))
                )
            if duplicates:
                details.append("duplicate references")
            reference_problem = "required evidence references differ: " + "; ".join(
                details
            )
            evidence_error = "; ".join(
                part for part in (evidence_error, reference_problem) if part
            )
        if result.status is DispatchStatus.SUCCEEDED and pass_problem:
            evidence_error = "; ".join(
                part
                for part in (
                    evidence_error,
                    f"structured stage evidence is non-PASS: {pass_problem}",
                )
                if part
            )
        if result.status is DispatchStatus.SUCCEEDED and evidence_error:
            effective = DispatchResult(
                result.handle,
                DispatchStatus.FAILED,
                output=result.output,
                error=evidence_error,
                evidence=result.evidence,
            )
        terminal_error = effective.error
        if effective.status is DispatchStatus.CANCELLED:
            terminal_error = terminal_error or "dispatch was cancelled"
        elif effective.status is DispatchStatus.FAILED:
            terminal_error = terminal_error or "dispatch failed"

        try:
            artifact = self.ledger.finish(stage, effective)
        except Exception as exc:
            fallback_error = (
                f"coordinator could not persist the collected terminal result: {exc}"
            )
            fallback = DispatchResult(
                effective.handle,
                DispatchStatus.CANCELLED,
                error=fallback_error,
            )
            try:
                artifact = self.ledger.finish(stage, fallback)
            except Exception as fallback_exc:
                return _AttemptDisposition(
                    f"{fallback_error}; cancellation persistence also failed: "
                    f"{fallback_exc}",
                    False,
                )
            attempts.append(
                StageExecution(
                    stage.id,
                    fallback.handle.route,
                    fallback.handle,
                    fallback.status,
                    fallback.evidence,
                    fallback.error,
                    artifact,
                )
            )
            return _AttemptDisposition(fallback_error, False)
        except BaseException:
            fallback = DispatchResult(
                effective.handle,
                DispatchStatus.CANCELLED,
                error="coordinator interrupted while persisting a collected result",
            )
            try:
                artifact = self.ledger.finish(stage, fallback)
                attempts.append(
                    StageExecution(
                        stage.id,
                        fallback.handle.route,
                        fallback.handle,
                        fallback.status,
                        fallback.evidence,
                        fallback.error,
                        artifact,
                    )
                )
            except BaseException:
                pass
            raise
        attempts.append(
            StageExecution(
                stage.id,
                effective.handle.route,
                effective.handle,
                effective.status,
                effective.evidence,
                effective.error,
                artifact,
            )
        )
        if effective.status is DispatchStatus.SUCCEEDED:
            return _AttemptDisposition(None, False)
        if effective.status is DispatchStatus.CANCELLED:
            return _AttemptDisposition(terminal_error, False)
        # A structurally valid evidence envelope is an authoritative semantic
        # observation, never a transient transport failure.  Without an
        # explicit resolution record, a retry cannot erase it by omission.
        return _AttemptDisposition(terminal_error, not typed_observation)

    def run(self) -> WorkflowExecutionResult:
        """Run until all stages finish, a gate is pending, or a human must decide."""
        if self.mode.code == "E":
            return self._stop(
                HumanStopReason.UNSUPPORTED_REQUIRED_CAPABILITY,
                "Mode E requires the authoritative program-manifest execution entry point",
                "invoke the managed workflow with an explicit --program-manifest path",
                completed=(),
                skipped=(),
                attempts=(),
            )
        stages = self.stages
        stage_by_id = {stage.id: stage for stage in stages}
        completed = set(self.ledger.completed_stage_ids())
        resolved_gates = self.ledger.resolved_gate_ids()
        skipped = set(self.ledger.skipped_stage_ids())
        attempts: list[StageExecution] = []

        try:
            stable_decisions = self._bind_stable_conditions(stages, resolved_gates)
        except Exception as exc:
            reason = (
                HumanStopReason.MISSING_REQUIREMENTS
                if "no explicit decision" in str(exc)
                else HumanStopReason.CONFLICTING_EVIDENCE
            )
            return self._stop(
                reason,
                str(exc),
                "supply every required condition once, without changing frozen decisions",
                completed=sorted(completed),
                skipped=sorted(skipped),
                attempts=attempts,
            )

        skip_candidates: set[str] = set()
        for stage in stages:
            if (
                stage.condition in stable_decisions
                and not stable_decisions[stage.condition]
            ):
                skip_candidates.add(stage.id)
            if (
                stage.condition == "all-waves-and-gates-closed"
                and self.mode.code != "E"
            ):
                skip_candidates.add(stage.id)

        unexpected_skips = skipped - skip_candidates
        if unexpected_skips:
            return self._stop(
                HumanStopReason.CONFLICTING_EVIDENCE,
                "durable skipped stages differ from the frozen false conditions: "
                + ", ".join(sorted(unexpected_skips)),
                "inspect the managed skip attestations before resuming",
                completed=sorted(completed),
                skipped=sorted(skipped),
                attempts=attempts,
            )
        skip_candidates -= skipped
        try:
            self._attest_ready_skips(
                stage_by_id=stage_by_id,
                candidates=skip_candidates,
                completed=completed,
                skipped=skipped,
            )
        except Exception as exc:
            return self._stop(
                HumanStopReason.CONFLICTING_EVIDENCE,
                f"cannot persist conditional-stage skip: {exc}",
                "inspect the frozen condition and dependency ledger",
                completed=sorted(completed),
                skipped=sorted(skipped),
                attempts=attempts,
            )

        pending = {
            stage.id: stage
            for stage in stages
            if stage.id not in completed and stage.id not in skipped
        }
        enabled_groups = set(self.mode.parallel_groups)

        while pending:
            unresolved_from_completed = self._pending_owned_gate(
                stage_by_id,
                completed,
                skipped,
                resolved_gates,
            )
            if unresolved_from_completed:
                return WorkflowExecutionResult(
                    WorkflowExecutionStatus.WAITING_GATE,
                    tuple(sorted(completed)),
                    tuple(sorted(skipped)),
                    tuple(attempts),
                    pending_gates=unresolved_from_completed,
                    messages=(
                        "resolve the pending gate ledger entries before continuing",
                    ),
                )

            ready = [
                stage
                for stage in stages
                if stage.id in pending
                and all(
                    dependency not in stage_by_id
                    or dependency in completed
                    or dependency in skipped
                    for dependency in stage.depends_on
                )
            ]
            if not ready:
                return self._stop(
                    HumanStopReason.CONFLICTING_EVIDENCE,
                    "workflow has pending stages but no dependency-ready stage",
                    "inspect the bound stage graph and shared stage history",
                    completed=sorted(completed),
                    skipped=sorted(skipped),
                    attempts=attempts,
                )

            first = ready[0]
            if first.parallel_group in enabled_groups:
                group = self.workflow.definition.parallel_groups[
                    str(first.parallel_group)
                ]
                serialize = (
                    bool(
                        getattr(
                            self.workspace_resolver,
                            "serializes_disjoint_writes",
                            False,
                        )
                    )
                    and group.concurrency == "disjoint-only"
                )
                batch = (
                    [first]
                    if serialize
                    else [
                        stage
                        for stage in ready
                        if stage.parallel_group == first.parallel_group
                    ]
                )
            else:
                batch = [first]

            typed_actions = [
                stage
                for stage in batch
                if stage.execution_kind is StageExecutionKind.TYPED_EXTERNAL_ACTION
            ]
            if typed_actions:
                stage = typed_actions[0]
                action = (
                    stage.action_kind.value
                    if stage.action_kind is not None
                    else "unknown"
                )
                return self._stop(
                    HumanStopReason.EXTERNAL_SIDE_EFFECT,
                    f"typed external action {action!r} for stage {stage.id!r} "
                    "requires a scoped broker and cannot be dispatched to a native role",
                    "generic pause approval cannot resume this action; use the typed "
                    "external-action broker bound to this exact stage attempt",
                    completed=sorted(completed),
                    skipped=sorted(skipped),
                    attempts=attempts,
                )

            for stage in batch:
                if stage.condition not in self._DYNAMIC_CONDITIONS:
                    continue
                dynamic_decision = self._condition(stage.condition, resolved_gates)
                if dynamic_decision:
                    continue
                if stage.condition in {
                    "all-active-gates-closed",
                    "fast-track-gates-closed",
                }:
                    relevant = (
                        self.mode.gates
                        if stage.condition == "fast-track-gates-closed"
                        else self.active_gate_ids
                    )
                    gates = tuple(
                        gate for gate in relevant if gate not in resolved_gates
                    )
                    return WorkflowExecutionResult(
                        WorkflowExecutionStatus.WAITING_GATE,
                        tuple(sorted(completed)),
                        tuple(sorted(skipped)),
                        tuple(attempts),
                        pending_gates=gates,
                        messages=(f"stage {stage.id!r} waits for its frozen gate set",),
                    )
                return self._stop(
                    HumanStopReason.MISSING_REQUIREMENTS,
                    f"stage {stage.id!r} condition {stage.condition!r} is not satisfied",
                    f"satisfy and explicitly attest condition {stage.condition!r}",
                    completed=sorted(completed),
                    skipped=sorted(skipped),
                    attempts=attempts,
                )

            if getattr(self.dispatcher, "queued_spawn", False) is not True:
                return self._stop(
                    HumanStopReason.UNSUPPORTED_REQUIRED_CAPABILITY,
                    "managed dispatch requires an authenticated queued-spawn "
                    "adapter so the ledger claim is durable before execution",
                    "use a dispatcher that explicitly attests queued_spawn=True",
                    completed=sorted(completed),
                    skipped=sorted(skipped),
                    attempts=attempts,
                )

            launched: list[tuple[WorkflowStageDefinition, DispatchHandle]] = []
            for stage in batch:
                try:
                    handle = self._spawn(stage)
                    self._claim(stage, handle)
                    launched.append((stage, handle))
                except UnsupportedCapabilityError as exc:
                    closure_errors = self._cancel_launched(
                        launched, attempts, "parallel batch capability preflight failed"
                    )
                    message = str(exc)
                    if closure_errors:
                        message += "; " + "; ".join(closure_errors)
                    return self._stop(
                        HumanStopReason.UNSUPPORTED_REQUIRED_CAPABILITY,
                        message,
                        "install/configure a capable provider role or change the approved route",
                        completed=sorted(completed),
                        skipped=sorted(skipped),
                        attempts=attempts,
                    )
                except Exception as exc:
                    closure_errors = self._cancel_launched(
                        launched,
                        attempts,
                        "parallel batch role/ledger preflight failed",
                    )
                    message = str(exc)
                    if closure_errors:
                        message += "; " + "; ".join(closure_errors)
                    return self._stop(
                        HumanStopReason.MISSING_REQUIREMENTS,
                        message,
                        "install the required native role or approve a valid fallback",
                        completed=sorted(completed),
                        skipped=sorted(skipped),
                        attempts=attempts,
                    )
                except BaseException:
                    self._cancel_launched(
                        launched,
                        attempts,
                        "parallel batch interrupted during launch",
                    )
                    raise

            try:
                results = self._await([handle for _stage, handle in launched])
            except Exception as exc:
                return self._dispatch_error_stop(
                    exc,
                    launched,
                    attempts,
                    completed=sorted(completed),
                    skipped=sorted(skipped),
                    phase="initial batch wait/collect",
                )
            except BaseException:
                self._cancel_launched(
                    launched,
                    attempts,
                    "coordinator interrupted during batch wait/collect",
                )
                raise
            human_result = next(
                (result for result in results if result.human_stop is not None), None
            )
            collected = [
                (stage, result) for (stage, _handle), result in zip(launched, results)
            ]
            if human_result is not None:
                for index, (stage, result) in enumerate(collected):
                    try:
                        disposition = self._finish_attempt(stage, result, attempts)
                    except BaseException:
                        self._terminalize_collected_results(
                            collected[index:],
                            attempts,
                            "coordinator interrupted while persisting collected results",
                        )
                        raise
                    if disposition.error is None:
                        completed.add(stage.id)
                        pending.pop(stage.id, None)
                stop = human_result.human_stop
                if stop is None:  # pragma: no cover - guarded by the search above
                    raise WorkflowValidationError("human-stop result lost its request")
                self.ledger.pause(stop)
                return WorkflowExecutionResult(
                    WorkflowExecutionStatus.HUMAN_STOP,
                    tuple(sorted(completed)),
                    tuple(sorted(skipped)),
                    tuple(attempts),
                    human_stop=stop,
                    messages=(stop.message,),
                )
            initial_dispositions: dict[str, _AttemptDisposition] = {}
            initial_results: dict[str, DispatchResult] = {}
            for index, (stage, result) in enumerate(collected):
                try:
                    disposition = self._finish_attempt(stage, result, attempts)
                except BaseException:
                    self._terminalize_collected_results(
                        collected[index:],
                        attempts,
                        "coordinator interrupted while persisting collected results",
                    )
                    raise
                initial_dispositions[stage.id] = disposition
                initial_results[stage.id] = result
                if disposition.error is None:
                    completed.add(stage.id)
                    pending.pop(stage.id, None)

            # Every initial result above is durable before any retry can stop
            # this invocation. A successful sibling therefore cannot be rerun
            # merely because an earlier result exhausts its retry budget.
            for stage, _handle in launched:
                disposition = initial_dispositions[stage.id]
                error = disposition.error
                current = initial_results[stage.id]
                if error is None:
                    continue
                if not disposition.retryable:
                    return self._stop(
                        HumanStopReason.CONFLICTING_EVIDENCE,
                        f"stage {stage.id!r} produced authoritative non-retryable "
                        f"evidence: {error}",
                        "inspect the preserved evidence and explicitly abort or re-plan; "
                        "a clean retry cannot resolve it by omission",
                        completed=sorted(completed),
                        skipped=sorted(skipped),
                        attempts=attempts,
                    )
                budget = self.workflow.definition.retry_budgets[stage.retry_budget]
                while (
                    error is not None
                    and current.handle.attempt <= budget.max_transient_retries
                ):
                    if getattr(self.dispatcher, "queued_spawn", False) is not True:
                        return self._stop(
                            HumanStopReason.UNSUPPORTED_REQUIRED_CAPABILITY,
                            "managed retry requires an authenticated queued-spawn "
                            "adapter before reserving another attempt",
                            "restore an explicitly attested queued dispatcher or abort",
                            completed=sorted(completed),
                            skipped=sorted(skipped),
                            attempts=attempts,
                        )
                    try:
                        retried = self.dispatcher.retry(current.handle, error)
                    except Exception as exc:
                        return self._stop(
                            HumanStopReason.RETRY_BUDGET_EXHAUSTED,
                            f"stage {stage.id!r} retry launch failed: {exc}",
                            "inspect the preserved failed attempt and re-plan or abort",
                            completed=sorted(completed),
                            skipped=sorted(skipped),
                            attempts=attempts,
                        )
                    except BaseException:
                        raise
                    try:
                        self._claim(stage, retried)
                    except Exception as exc:
                        return self._stop(
                            HumanStopReason.CONFLICTING_EVIDENCE,
                            f"stage {stage.id!r} retry claim failed: {exc}",
                            "inspect the shared stage ledger before any further retry",
                            completed=sorted(completed),
                            skipped=sorted(skipped),
                            attempts=attempts,
                        )
                    except BaseException:
                        self._cancel_launched(
                            ((stage, retried),),
                            attempts,
                            "coordinator interrupted during retry claim",
                        )
                        raise
                    try:
                        current = self._await((retried,))[0]
                    except Exception as exc:
                        return self._dispatch_error_stop(
                            exc,
                            ((stage, retried),),
                            attempts,
                            completed=sorted(completed),
                            skipped=sorted(skipped),
                            phase=f"stage {stage.id!r} retry wait/collect",
                        )
                    except BaseException:
                        self._cancel_launched(
                            ((stage, retried),),
                            attempts,
                            "coordinator interrupted during retry wait/collect",
                        )
                        raise
                    if current.human_stop is not None:
                        self._finish_attempt(stage, current, attempts)
                        self.ledger.pause(current.human_stop)
                        return WorkflowExecutionResult(
                            WorkflowExecutionStatus.HUMAN_STOP,
                            tuple(sorted(completed)),
                            tuple(sorted(skipped)),
                            tuple(attempts),
                            human_stop=current.human_stop,
                            messages=(current.human_stop.message,),
                        )
                    try:
                        disposition = self._finish_attempt(stage, current, attempts)
                    except BaseException:
                        self._terminalize_collected_results(
                            ((stage, current),),
                            attempts,
                            "coordinator interrupted while persisting a retry result",
                        )
                        raise
                    error = disposition.error
                    if error is not None and not disposition.retryable:
                        return self._stop(
                            HumanStopReason.CONFLICTING_EVIDENCE,
                            f"stage {stage.id!r} produced authoritative non-retryable "
                            f"evidence: {error}",
                            "inspect the preserved evidence and explicitly abort or "
                            "re-plan; a clean retry cannot resolve it by omission",
                            completed=sorted(completed),
                            skipped=sorted(skipped),
                            attempts=attempts,
                        )

                if error is not None:
                    return self._stop(
                        HumanStopReason.RETRY_BUDGET_EXHAUSTED,
                        f"stage {stage.id!r} exhausted retries: {error}",
                        "inspect preserved output and decide whether to re-plan or abort",
                        completed=sorted(completed),
                        skipped=sorted(skipped),
                        attempts=attempts,
                    )
                completed.add(stage.id)
                pending.pop(stage.id, None)

            resolved_gates = self.ledger.resolved_gate_ids()
            try:
                self._attest_ready_skips(
                    stage_by_id=stage_by_id,
                    candidates=skip_candidates,
                    completed=completed,
                    skipped=skipped,
                )
                for skipped_stage in skipped:
                    pending.pop(skipped_stage, None)
            except Exception as exc:
                return self._stop(
                    HumanStopReason.CONFLICTING_EVIDENCE,
                    f"cannot persist conditional-stage skip: {exc}",
                    "inspect the frozen condition and dependency ledger",
                    completed=sorted(completed),
                    skipped=sorted(skipped),
                    attempts=attempts,
                )

        unresolved_final = self._pending_owned_gate(
            stage_by_id,
            completed,
            skipped,
            resolved_gates,
        )
        if unresolved_final:
            return WorkflowExecutionResult(
                WorkflowExecutionStatus.WAITING_GATE,
                tuple(sorted(completed)),
                tuple(sorted(skipped)),
                tuple(attempts),
                pending_gates=unresolved_final,
                messages=("resolve the pending gate ledger entries before completion",),
            )
        unresolved_without_owner = tuple(
            gate for gate in self.active_gate_ids if gate not in resolved_gates
        )
        if unresolved_without_owner:
            return self._stop(
                HumanStopReason.CONFLICTING_EVIDENCE,
                "workflow finished without settling the owning stage for gate(s): "
                + ", ".join(unresolved_without_owner),
                "inspect the bound gate-owner mapping and shared stage history",
                completed=sorted(completed),
                skipped=sorted(skipped),
                attempts=attempts,
            )
        self.ledger.attest_completion(tuple(stage.id for stage in stages))
        return WorkflowExecutionResult(
            WorkflowExecutionStatus.SUCCEEDED,
            tuple(sorted(completed)),
            tuple(sorted(skipped)),
            tuple(attempts),
        )


def _selection_digest(selection: Mapping[str, object]) -> str:
    encoded = json.dumps(
        selection,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _assert_clean_application_state(root: Path, options: InitOptions) -> None:
    """Require every worktree-visible input to be committed into ``HEAD``.

    The managed integration worktree is created from ``HEAD``.  Exempting
    freshly scaffolded provider files would silently launch a host without its
    installed project instructions.  Only the enumerated mutable ledger,
    artifact, memory, continuity, journal, and temporary paths are excluded;
    provider-owned rules/templates and immutable shared stack context below the
    same control root must be committed and visible in the worker worktree.
    """
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "status",
                "--porcelain=v1",
                "-z",
                "--untracked-files=all",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )
        tracked_result = subprocess.run(
            ["git", "-C", str(root), "ls-tree", "-r", "--name-only", "-z", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise WorkflowValidationError(
            f"cannot verify clean application state: {exc}"
        ) from exc
    layout = options.state_layout

    def mutable_state_path(path: str) -> bool:
        exact = {layout.continuity, layout.journal}
        prefixes = {
            layout.state,
            layout.memory,
            layout.artifacts,
            layout.temporary,
        }
        return path in exact or any(
            path == prefix or path.startswith(prefix + "/") for prefix in prefixes
        )

    tracked = set(tracked_result.stdout.split("\0"))
    required_provider_files = {
        record.path for record in options.files if not mutable_state_path(record.path)
    }
    missing_from_head = sorted(required_provider_files - tracked)
    if missing_from_head:
        rendered = ", ".join(missing_from_head[:10])
        raise WorkflowValidationError(
            "managed execution creates its integration worktree from HEAD; installed "
            "provider configuration is not committed: " + rendered
        )
    dirty_inputs: list[str] = []
    for entry in result.stdout.split("\0"):
        if len(entry) < 4:
            continue
        path = entry[3:]
        if mutable_state_path(path):
            continue
        dirty_inputs.append(path)
    if dirty_inputs:
        rendered = ", ".join(sorted(set(dirty_inputs))[:10])
        raise WorkflowValidationError(
            "managed execution creates its integration worktree from HEAD; commit or "
            "stash application and installed provider configuration first. Dirty: "
            + rendered
        )


def _mutable_runtime_context(root: Path, options: InitOptions) -> str:
    """Render bounded current continuity/memory from the authoritative source root.

    The managed worktree is intentionally created from immutable ``HEAD``. Mutable
    learning state remains root-owned, so native workers receive a hash-identified
    prompt snapshot instead of reading or writing a stale second copy in the sibling.
    """

    fs = ProjectFS(root)
    layout = options.state_layout
    candidates: set[str] = set()
    if fs.is_file(layout.continuity):
        candidates.add(layout.continuity)
    memory_root = fs.path(layout.memory)
    if memory_root.exists():
        try:
            memory_info = memory_root.lstat()
        except OSError as exc:
            raise WorkflowValidationError(
                f"cannot inspect authoritative agent memory: {exc}"
            ) from exc
        if stat.S_ISLNK(memory_info.st_mode) or not stat.S_ISDIR(memory_info.st_mode):
            raise WorkflowValidationError(
                "authoritative agent-memory root must be a real directory"
            )
        for current, directories, files in os.walk(memory_root, followlinks=False):
            current_path = Path(current)
            for name in [*directories, *files]:
                candidate = current_path / name
                try:
                    info = candidate.lstat()
                except OSError as exc:
                    raise WorkflowValidationError(
                        f"cannot inspect mutable context path {candidate}: {exc}"
                    ) from exc
                if stat.S_ISLNK(info.st_mode):
                    raise WorkflowValidationError(
                        f"mutable context path must not be a symlink: {candidate}"
                    )
                if name in files:
                    if not stat.S_ISREG(info.st_mode):
                        raise WorkflowValidationError(
                            f"mutable context path is not a regular file: {candidate}"
                        )
                    candidates.add(candidate.relative_to(root).as_posix())
    if len(candidates) > _MAX_MUTABLE_CONTEXT_FILES:
        raise WorkflowValidationError(
            "authoritative continuity/memory exceeds the 256-file prompt safety limit"
        )
    if not candidates:
        return ""

    preamble = (
        "Authoritative mutable context snapshot (source-root, read-only for this worker). "
        "Do not use the sibling worktree's continuity/memory as a second ledger.\n"
    )
    rendered = bytearray(preamble.encode("utf-8"))
    for relative in sorted(candidates):
        try:
            content = fs.read_bytes(relative)
        except (OSError, ValueError) as exc:
            raise WorkflowValidationError(
                f"cannot read authoritative mutable context {relative}: {exc}"
            ) from exc
        header = (
            f"\n--- {relative} sha256={hashlib.sha256(content).hexdigest()} ---\n"
        ).encode("utf-8")
        remaining = _MAX_MUTABLE_CONTEXT_BYTES - len(rendered) - len(header)
        if remaining <= 0:
            rendered.extend(b"\n[additional mutable context omitted by byte limit]")
            break
        rendered.extend(header)
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            rendered.extend(b"[binary content omitted; digest above is authoritative]")
            continue
        encoded = text.encode("utf-8")
        if len(encoded) > remaining:
            marker = b"\n[file content prefix truncated by byte limit]"
            prefix = encoded[: max(0, remaining - len(marker))].decode(
                "utf-8", errors="ignore"
            )
            rendered.extend(prefix.encode("utf-8"))
            rendered.extend(marker)
            break
        rendered.extend(encoded)
    return bytes(rendered[:_MAX_MUTABLE_CONTEXT_BYTES]).decode("utf-8", errors="ignore")


def _verify_execution_binding(
    *,
    options: InitOptions,
    plan: ResolvedPlan,
    bound: BoundWorkflow,
    install_document: Mapping[str, object],
    run_document: Mapping[str, object],
    mode: str,
    objective: str,
) -> None:
    """Fail closed unless install, plan, workflow, and active ledger are identical."""
    selection = options.selection.to_dict()
    if install_document.get("selection") != selection:
        raise WorkflowValidationError(
            "installed stack snapshot selection differs from the runtime manifest"
        )
    expected_selection_digest = _selection_digest(selection)
    if run_document.get("selection_digest") != expected_selection_digest:
        raise WorkflowValidationError(
            "active pipeline selection digest differs from the installed selection"
        )
    if install_document.get("runtimes") != list(options.runtimes):
        raise WorkflowValidationError(
            "installed stack snapshot runtimes differ from the runtime manifest"
        )
    expected_gates = list(plan.gates)
    if install_document.get("gates") != expected_gates:
        raise WorkflowValidationError(
            "installed stack snapshot gates differ from the resolved plan"
        )
    if install_document.get("gate_definition_digest") != plan.gate_definition_digest:
        raise WorkflowValidationError(
            "installed stack snapshot gate digest differs from the resolved plan"
        )
    if list(bound.active_gate_ids) != expected_gates or (
        bound.gate_definition_digest != plan.gate_definition_digest
    ):
        raise WorkflowValidationError(
            "bound workflow gate policy differs from the resolved plan"
        )
    mode_gates = list(bound.gate_ids_for_mode(mode))
    mode_gate_digest = bound.gate_definition_digest_for_mode(mode)
    if run_document.get("ordered_gates") != mode_gates or (
        run_document.get("gate_definition_digest") != mode_gate_digest
    ):
        raise WorkflowValidationError(
            "active pipeline gate policy differs from the bound workflow"
        )
    if run_document.get("status") != "active":
        raise WorkflowValidationError(
            "structured workflow requires an active pipeline run"
        )
    if run_document.get("task") != objective.strip():
        raise WorkflowValidationError(
            "requested workflow objective differs from the active pipeline task"
        )
    if run_document.get("profile") != options.selection.profile or (
        run_document.get("scope") != options.selection.scope
    ):
        raise WorkflowValidationError(
            "active pipeline profile/scope differs from the installed selection"
        )
    matching_modes = [
        item
        for item in bound.definition.modes.values()
        if item.id == mode or item.code == mode
    ]
    if len(matching_modes) != 1 or run_document.get("mode") != matching_modes[0].code:
        raise WorkflowValidationError(
            "requested workflow mode differs from the active pipeline mode"
        )


def _execute_bound_workflow_under_lease(
    project_root: Path,
    *,
    provider: str | Provider,
    objective: str,
    mode: str,
    conditions: Mapping[str, bool],
    context: str = "",
    payload_root: Optional[Path] = None,
    dispatcher: Optional[Dispatcher] = None,
    ledger: Optional[StageLedger] = None,
    workspace_resolver: Optional[OwnedWorkspaceResolver] = None,
    program_manifest_path: Optional[Path] = None,
    wait_timeout_seconds: float = 900.0,
) -> WorkflowExecutionResult:
    """Load the installed selection and execute its canonical bound workflow.

    ``conditions`` is intentionally required: surface/risk decisions cannot be
    guessed by a lifecycle command. Derived mode/gate conditions are handled by
    the executor; every other selected condition must have an explicit boolean.
    """
    root = Path(project_root).resolve(strict=True)
    concrete = Provider.parse(provider)
    layout = detect_state_layout(root)
    manifest_path = root / layout.manifest
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        options = InitOptions.from_dict(manifest)
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise WorkflowValidationError(
            f"cannot load installed runtime manifest {manifest_path}: {exc}"
        ) from exc
    if concrete.value not in options.runtimes:
        raise WorkflowValidationError(
            f"provider {concrete.value!r} is not installed ({options.runtimes})"
        )

    with ExitStack() as resources:
        payload = (
            Path(payload_root)
            if payload_root is not None
            else scaffold.payload_dir(resources)
        )
        plan = catalog.resolve(payload, options.selection)
        from claude_kit.workflows import bind_workflow, load_workflow

        bound = bind_workflow(load_workflow(payload), plan)

    stack_path = root / layout.stack_snapshot
    try:
        install_document = yaml.safe_load(stack_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise WorkflowValidationError(
            f"cannot load installed stack snapshot {stack_path}: {exc}"
        ) from exc
    if not isinstance(install_document, dict):
        raise WorkflowValidationError(
            f"installed stack snapshot {stack_path} is not a mapping"
        )
    run_document, run_error = pipeline.snapshot_document(root)
    if run_error or run_document is None:
        raise WorkflowValidationError(
            run_error or "structured workflow requires an explicit active pipeline run"
        )
    _verify_execution_binding(
        options=options,
        plan=plan,
        bound=bound,
        install_document=install_document,
        run_document=run_document,
        mode=mode,
        objective=objective,
    )
    matching_mode = next(
        item
        for item in bound.definition.modes.values()
        if item.id == mode or item.code == mode
    )
    selected_resolver = workspace_resolver
    role_loader: Optional[FilesystemNativeRoleLoader] = None
    if selected_resolver is None:
        _assert_clean_application_state(root, options)
        run_id = run_document.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            raise WorkflowValidationError("active pipeline has no run-owned identity")
        role_loader = FilesystemNativeRoleLoader(root)
        selected_resolver = ManagedWorktreeResolver(
            root,
            run_id,
            _managed_lease_held=True,
        )
        selected_resolver.ensure_workspace()
    elif isinstance(selected_resolver, ManagedWorktreeResolver):
        # The public entry point owns the managed-execution lease for this
        # entire call. Propagate that authority to caller-supplied resolvers
        # without leaving them able to bypass the lease after this invocation.
        selected_resolver = selected_resolver._with_managed_lease()
    if not isinstance(selected_resolver, ManagedWorktreeResolver):
        raise WorkflowValidationError(
            "managed execution requires the run-owned checkpointing worktree resolver"
        )

    if matching_mode.code == "E":
        if program_manifest_path is None:
            raise WorkflowValidationError(
                "Mode E requires an explicit --program-manifest path"
            )
        if ledger is not None:
            raise WorkflowValidationError(
                "Mode E uses only the authoritative program pipeline ledger"
            )
        selected_dispatcher = dispatcher
        native_loader = role_loader or FilesystemNativeRoleLoader(root)
        if selected_dispatcher is None:
            selected_dispatcher = (
                ClaudeProcessDispatcher(
                    root,
                    role_loader=native_loader,
                    allowed_workspaces=selected_resolver.allowed_roots,
                )
                if concrete is Provider.CLAUDE
                else CodexProcessDispatcher(
                    root,
                    role_loader=native_loader,
                    allowed_workspaces=selected_resolver.allowed_roots,
                )
            )
        from claude_kit.program_execution import execute_program_manifest

        result = execute_program_manifest(
            root,
            provider=concrete,
            objective=objective,
            bound_workflow=bound,
            manifest_path=program_manifest_path,
            dispatcher=selected_dispatcher,
            workspace_resolver=selected_resolver,
            role_loader=native_loader,
            context=context,
            runtime_context=_mutable_runtime_context(root, options),
            wait_timeout_seconds=wait_timeout_seconds,
        )
        records = [
            record
            for record in selected_resolver.manager.records(selected_resolver.run_id)
            if record.worker_id == selected_resolver.WORKER_ID
        ]
        if records and records[0].status is WorktreeStatus.ACTIVE:
            if result.status is WorkflowExecutionStatus.SUCCEEDED:
                selected_resolver.manager.mark(
                    selected_resolver.run_id,
                    selected_resolver.WORKER_ID,
                    WorktreeStatus.SUCCEEDED,
                    _managed_lease_held=True,
                )
            # A failed Mode E attempt remains retryable only after the frozen
            # pre-checkpoint is restored. Keep the worktree active so recovery
            # remains governed by the program ledger's checkpoint-chain check.
        return result
    if program_manifest_path is not None:
        raise WorkflowValidationError("--program-manifest is accepted only for Mode E")

    managed, managed_error = pipeline.bind_managed_execution(
        root,
        workflow_id=bound.definition.id,
        workflow_schema_version=bound.definition.schema_version,
        workflow_definition_digest=workflow_definition_digest(bound.definition),
        mode=matching_mode.code,
        ordered_gates=bound.gate_ids_for_mode(matching_mode.id),
        gate_definition_digest=bound.gate_definition_digest_for_mode(matching_mode.id),
        gate_owner_stages=bound.gate_owner_stages_for_mode(matching_mode.id),
        workspace=selected_resolver.binding(),
    )
    if managed_error or managed is None:
        raise WorkflowValidationError(
            managed_error or "managed workflow contract was not frozen"
        )

    selected_dispatcher = dispatcher
    if selected_dispatcher is None:
        if not isinstance(selected_resolver, ManagedWorktreeResolver):
            raise WorkflowValidationError(
                "a custom workspace resolver requires an explicitly configured dispatcher"
            )
        native_loader = role_loader or FilesystemNativeRoleLoader(root)
        selected_dispatcher = (
            ClaudeProcessDispatcher(
                root,
                role_loader=native_loader,
                allowed_workspaces=selected_resolver.allowed_roots,
            )
            if concrete is Provider.CLAUDE
            else CodexProcessDispatcher(
                root,
                role_loader=native_loader,
                allowed_workspaces=selected_resolver.allowed_roots,
            )
        )
    selected_ledger = ledger or PipelineStageLedger(root, selected_resolver)
    raw_requirements = managed.get("active_stage_requirements")
    if not isinstance(raw_requirements, dict):
        raise WorkflowValidationError(
            "managed workflow has no frozen stage capability requirements"
        )
    try:
        required_overrides = {
            str(stage): tuple(Capability(str(value)) for value in values)
            for stage, values in raw_requirements.items()
            if isinstance(values, list)
        }
    except ValueError as exc:
        raise WorkflowValidationError(
            f"managed workflow has an unknown capability requirement: {exc}"
        ) from exc
    if set(required_overrides) != set(raw_requirements):
        raise WorkflowValidationError(
            "managed workflow stage capability requirements are malformed"
        )
    raw_routes = managed.get("active_stage_routes")
    if not isinstance(raw_routes, dict):
        raise WorkflowValidationError("managed workflow has no frozen stage routes")
    role_overrides = {
        str(stage): str(route["role"])
        for stage, route in raw_routes.items()
        if isinstance(route, dict)
        and isinstance(route.get("role"), str)
        and route["role"]
    }
    native_route_ids = {
        str(stage)
        for stage, route in raw_routes.items()
        if isinstance(route, dict)
        and route.get("execution_kind", "native-role") == "native-role"
    }
    if set(role_overrides) != native_route_ids:
        raise WorkflowValidationError("managed workflow stage routes are malformed")
    result = WorkflowExecutor(
        bound,
        selected_dispatcher,
        selected_ledger,
        mode=mode,
        objective=objective,
        context=context,
        runtime_context_provider=lambda: _mutable_runtime_context(root, options),
        required_capability_overrides=required_overrides,
        role_overrides=role_overrides,
        conditions=conditions,
        workspace_resolver=selected_resolver,
        wait_timeout_seconds=wait_timeout_seconds,
    ).run()
    if isinstance(selected_resolver, ManagedWorktreeResolver):
        records = [
            record
            for record in selected_resolver.manager.records(selected_resolver.run_id)
            if record.worker_id == selected_resolver.WORKER_ID
        ]
        if records and records[0].status is WorktreeStatus.ACTIVE:
            if result.status is WorkflowExecutionStatus.SUCCEEDED:
                selected_resolver.manager.mark(
                    selected_resolver.run_id,
                    selected_resolver.WORKER_ID,
                    WorktreeStatus.SUCCEEDED,
                    _managed_lease_held=True,
                )
            elif result.status is WorkflowExecutionStatus.FAILED:
                selected_resolver.manager.mark(
                    selected_resolver.run_id,
                    selected_resolver.WORKER_ID,
                    WorktreeStatus.FAILED,
                    failure_reason="; ".join(result.messages) or "workflow failed",
                    _managed_lease_held=True,
                )
    return result


def execute_bound_workflow(
    project_root: Path,
    *,
    provider: str | Provider,
    objective: str,
    mode: str,
    conditions: Mapping[str, bool],
    context: str = "",
    payload_root: Optional[Path] = None,
    dispatcher: Optional[Dispatcher] = None,
    ledger: Optional[StageLedger] = None,
    workspace_resolver: Optional[OwnedWorkspaceResolver] = None,
    program_manifest_path: Optional[Path] = None,
    wait_timeout_seconds: float = 900.0,
) -> WorkflowExecutionResult:
    """Execute one managed invocation while holding the crash-released run lease."""

    root = Path(project_root).resolve(strict=True)
    try:
        with managed_execution_lease(root):
            return _execute_bound_workflow_under_lease(
                root,
                provider=provider,
                objective=objective,
                mode=mode,
                conditions=conditions,
                context=context,
                payload_root=payload_root,
                dispatcher=dispatcher,
                ledger=ledger,
                workspace_resolver=workspace_resolver,
                program_manifest_path=program_manifest_path,
                wait_timeout_seconds=wait_timeout_seconds,
            )
    except ManagedExecutionLeaseHeld as exc:
        raise WorkflowValidationError(str(exc)) from exc


__all__ = [
    "ManagedWorktreeResolver",
    "OwnedWorkspaceResolver",
    "PipelineStageLedger",
    "ProjectWorkspaceResolver",
    "StageArtifactRef",
    "StageExecution",
    "StageLedger",
    "WorkflowExecutionResult",
    "WorkflowExecutionStatus",
    "WorkflowExecutor",
    "execute_bound_workflow",
]
