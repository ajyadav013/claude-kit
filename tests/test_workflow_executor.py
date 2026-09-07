from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence

import pytest

from claude_kit import catalog, pipeline
from claude_kit.canonical_agents import AgentSourceKind, find_canonical_agent
from claude_kit.components import Capability
from claude_kit.dispatch import (
    Dispatcher,
    DispatchHandle,
    DispatchMessage,
    DispatchRequest,
    DispatchResult,
    DispatchStatus,
    HumanStopRequest,
    WaitMode,
    WaitResult,
)
from claude_kit.models import FileRecord, InitOptions, StateLayout
from claude_kit.process_dispatch import (
    CodexProcessDispatcher,
    NativeRoleDefinition,
    ProcessOutcome,
    RoleUnavailableError,
    UnsupportedCapabilityError,
)
from claude_kit.projection import Provider
from claude_kit.workflow_executor import (
    ManagedWorktreeResolver,
    OwnedWorkspaceResolver,
    PipelineStageLedger,
    ProjectWorkspaceResolver,
    StageLedger,
    WorkflowExecutionStatus,
    WorkflowExecutor,
    _assert_clean_application_state,
    _DependencyStageEvidence,
    _mutable_runtime_context,
    _planning_packet_generation,
    _selection_digest,
    _verify_execution_binding,
)
from claude_kit.workflows import (
    AcceptedRiskPolicy,
    BoundWorkflow,
    EvidenceKind,
    EvidenceRequirement,
    ExhaustedAction,
    FindingsPolicy,
    GatePolicy,
    GateRequirement,
    ParallelGroup,
    ParallelLane,
    RetryBudget,
    RoleRoute,
    WorkflowDefinition,
    WorkflowGate,
    WorkflowMode,
    WorkflowStageDefinition,
    WorkflowValidationError,
)


def _stage(
    stage_id: str,
    route: str,
    evidence: str,
    *,
    depends_on: tuple[str, ...] = (),
    parallel_group: Optional[str] = None,
    gates: tuple[str, ...] = (),
    condition: str = "always",
) -> WorkflowStageDefinition:
    return WorkflowStageDefinition(
        stage_id,
        "implementation",
        route,
        depends_on,
        parallel_group,
        condition,
        gates,
        "default",
        (evidence,),
        frozenset({Capability.FILE_READ}),
    )


def _bound_workflow() -> BoundWorkflow:
    stages = (
        _stage("plan", "planning", "scope-record"),
        _stage(
            "left",
            "left-route",
            "left-report",
            depends_on=("plan",),
            parallel_group="delivery",
        ),
        _stage(
            "right",
            "right-route",
            "right-report",
            depends_on=("plan",),
            parallel_group="delivery",
        ),
        _stage(
            "review",
            "review-route",
            "review-verdict",
            depends_on=("left", "right"),
            gates=("quality",),
        ),
    )
    gate = WorkflowGate(
        "quality",
        "review",
        GateRequirement.REQUIRED,
        False,
        (),
        ("review-verdict",),
    )
    definition = WorkflowDefinition(
        schema_version=1,
        id="test",
        title="Test workflow",
        description="Small graph for deterministic executor tests.",
        roles={
            "planning": RoleRoute("planning", "planner", (), "Plan."),
            "left-route": RoleRoute("left-route", "left-worker", (), "Left."),
            "right-route": RoleRoute("right-route", "right-worker", (), "Right."),
            "review-route": RoleRoute("review-route", "reviewer", (), "Review."),
        },
        retry_budgets={
            "default": RetryBudget("default", 1, 0, 0, ExhaustedAction.ESCALATE_HUMAN)
        },
        evidence_requirements={
            "scope-record": EvidenceRequirement(
                "scope-record",
                EvidenceKind.ARTIFACT,
                "scope",
                ("mode", "surfaces", "constraints", "risks"),
                True,
            ),
            "left-report": EvidenceRequirement(
                "left-report", EvidenceKind.ARTIFACT, "left", ("path",), True
            ),
            "right-report": EvidenceRequirement(
                "right-report", EvidenceKind.ARTIFACT, "right", ("path",), True
            ),
            "review-verdict": EvidenceRequirement(
                "review-verdict",
                EvidenceKind.VERDICT,
                "review",
                ("status", "reviewer", "findings", "evidence"),
                True,
            ),
        },
        findings_policy=FindingsPolicy(
            ("critical", "high", "medium", "low", "cosmetic"),
            ("critical", "high", "medium"),
            ("critical", "high"),
            False,
            "reject",
            AcceptedRiskPolicy(("medium",), ("reason",)),
        ),
        ordered_gates=("quality",),
        gates={"quality": gate},
        stages=stages,
        parallel_groups={
            "delivery": ParallelGroup(
                "delivery",
                "plan",
                "review",
                "disjoint-only",
                (
                    ParallelLane("left", ("left",), "left files"),
                    ParallelLane("right", ("right",), "right files"),
                ),
            )
        },
        modes={
            "test-mode": WorkflowMode(
                "test-mode",
                "B",
                "Test mode.",
                ("test",),
                True,
                (),
                ("delivery",),
                GatePolicy.RESOLVED_PLAN,
                (),
                {},
                None,
            )
        },
    )
    return BoundWorkflow(definition, (gate,), ("review",), "digest")


def _evidence_document(evidence_id: str, *, mode: str) -> dict:
    documents: dict[str, dict] = {
        "scope-record": {
            "mode": mode,
            "surfaces": ["repository"],
            "constraints": [],
            "risks": [],
        },
        "fast-track-scope-record": {
            "mode": "D",
            "surfaces": ["one local implementation boundary"],
            "constraints": [],
            "risks": [],
            "risk-tier": "low",
            "localized-single-boundary": True,
            "unambiguous": True,
            "reversible": True,
            "sensitive-surface": False,
            "public-contract-surface": False,
            "irreversible-action": False,
            "external-effect": False,
        },
        "specification": {
            "outcome": "Requested behavior is implemented.",
            "acceptance-criteria": ["The requested behavior is verified."],
            "non-goals": [],
            "risks": [],
        },
        "architecture-plan": {
            "boundaries": ["project workspace"],
            "dependencies": [],
            "interfaces": [],
            "verification": ["focused tests"],
        },
        "story-breakdown": {
            "stories": [
                {
                    "story-id": "STORY-1",
                    "goal": "Deliver the requested behavior.",
                    "acceptance-criteria": ["The requested behavior is verified."],
                    "surfaces": ["project workspace"],
                    "risk": "standard",
                    "batchable": False,
                    "verification": ["Run focused tests."],
                }
            ],
            "dependencies": [{"story-id": "STORY-1", "blocked-by": []}],
            "parallelizable": ["STORY-1"],
            "sequencing": ["STORY-1"],
            "traceability": [
                {
                    "criterion": "The requested behavior is verified.",
                    "story-ids": ["STORY-1"],
                }
            ],
        },
        "review-verdict": {
            "status": "PASS",
            "reviewer": "test-reviewer",
            "findings": [],
            "evidence": ["tests/test_workflow_executor.py"],
        },
        "planning-review-verdict": {
            "status": "PASS",
            "reviewer": "test-planning-reviewer",
            "planning-generation": "b" * 64,
            "authority-domain": "architecture",
            "findings": [],
            "evidence": ["tests/test_workflow_executor.py"],
        },
        "planning-decision": {
            "status": "PASS",
            "reviewer": "em-reviewer",
            "planning-generation": "b" * 64,
            "panel-reviewers": ["test-planning-reviewer"],
            "findings": [],
            "decisions": [],
            "evidence": ["tests/test_workflow_executor.py"],
        },
        "command-evidence": {
            "command": "pytest -q",
            "exit-status": 0,
            "output": "passed",
        },
        "test-report": {
            "scope": ["focused tests"],
            "passed": 1,
            "failed": 0,
            "skipped": 0,
            "residual-risk": [],
        },
        "security-report": {
            "scanners": ["test-scanner"],
            "findings": [],
            "dispositions": [],
            "residual-risk": [],
        },
        "delivery-report": {
            "checks": ["pipeline"],
            "rollback": {"strategy": "revert"},
            "residual-risk": [],
        },
        "human-approval": {
            "approver": "test-owner",
            "scope": "test action",
            "decision": "approved",
            "timestamp": "2026-01-01T00:00:00Z",
        },
        "frozen-manifest": {
            "lanes": ["lane"],
            "boundaries": ["workspace"],
            "waves": ["wave"],
            "owners": ["owner"],
            "gates": ["gate"],
            "digest": "a" * 64,
        },
        "restore-point": {
            "scope": "workspace",
            "reference": "commit:abc",
            "verification": "verified",
        },
        "closeout-record": {
            "outcome": "completed",
            "gates": [
                {
                    "id": "gate",
                    "status": "passed",
                    "evidence": ["tests/test_workflow_executor.py"],
                }
            ],
            "accepted-risks": [],
            "learnings": [],
        },
    }
    return documents.get(evidence_id, {"path": f"artifacts/{evidence_id}.json"})


class FakeDispatcher:
    queued_spawn = True

    def __init__(self) -> None:
        self.counter = 0
        self.requests: dict[DispatchHandle, DispatchRequest] = {}
        self.wait_batches: list[tuple[str, ...]] = []
        self.cancelled: set[DispatchHandle] = set()
        self.fail_once: set[str] = set()
        self.fail_always: set[str] = set()
        self.unsupported: set[str] = set()
        self.available_roles: Optional[set[str]] = None
        self.wait_errors: set[str] = set()
        self.interrupt_wait: set[str] = set()
        self.retry_errors: set[str] = set()

    def spawn(self, request: DispatchRequest) -> DispatchHandle:
        if Capability.EXTERNAL_MUTATION in request.required_capabilities:
            raise UnsupportedCapabilityError(
                request.route, (Capability.EXTERNAL_MUTATION,)
            )
        if (
            self.available_roles is not None
            and request.route not in self.available_roles
        ):
            raise RoleUnavailableError(f"native role is not installed: {request.route}")
        if request.route in self.unsupported:
            raise UnsupportedCapabilityError(request.route, (Capability.FILE_READ,))
        self.counter += 1
        handle = DispatchHandle(
            f"dispatch-{self.counter}",
            request.route,
            provider="codex",
            required_capabilities=(Capability.FILE_READ,),
            attested_capabilities=(Capability.FILE_READ,),
        )
        self.requests[handle] = request
        return handle

    def message(self, handle: DispatchHandle, message: DispatchMessage) -> None:
        del handle, message

    def wait(
        self,
        handles: Sequence[DispatchHandle],
        mode: WaitMode = WaitMode.ALL,
        timeout_seconds: Optional[float] = None,
    ) -> WaitResult:
        del mode, timeout_seconds
        self.wait_batches.append(tuple(handle.route for handle in handles))
        if any(handle.route in self.interrupt_wait for handle in handles):
            raise KeyboardInterrupt
        if any(handle.route in self.wait_errors for handle in handles):
            raise RuntimeError("injected wait/backend failure")
        return WaitResult(tuple(handles), (), False)

    def collect(self, handles: Sequence[DispatchHandle]) -> tuple[DispatchResult, ...]:
        results = []
        for handle in handles:
            request = self.requests[handle]
            if handle in self.cancelled:
                results.append(
                    DispatchResult(
                        handle, DispatchStatus.CANCELLED, error="batch cancelled"
                    )
                )
            elif handle.route in self.fail_always or (
                handle.route in self.fail_once and handle.attempt == 1
            ):
                results.append(
                    DispatchResult(handle, DispatchStatus.FAILED, error="transient")
                )
            else:
                documents = {}
                mode = next(
                    (
                        code
                        for code in ("A", "B", "C", "D", "E")
                        if f"Managed execution mode: {code}." in request.context
                    ),
                    "B",
                )
                for reference in request.evidence:
                    evidence_id = reference.uri.removeprefix("artifact://")
                    documents[evidence_id] = _evidence_document(evidence_id, mode=mode)
                marker = "Coordinator-authenticated planning binding."
                if marker in request.context:
                    binding_text = request.context.split(marker, 1)[1]
                    binding_line = next(
                        line
                        for line in binding_text.splitlines()
                        if line.startswith("{")
                    )
                    binding = json.loads(binding_line)
                    if "planning-review-verdict" in documents:
                        verdict = documents["planning-review-verdict"]
                        verdict["reviewer"] = binding["reviewer"]
                        verdict["planning-generation"] = binding["planning-generation"]
                        verdict["authority-domain"] = binding["authority-domain"]
                    if "planning-decision" in documents:
                        decision = documents["planning-decision"]
                        decision["reviewer"] = binding["reviewer"]
                        decision["planning-generation"] = binding["planning-generation"]
                        decision["panel-reviewers"] = binding["panel-reviewers"]
                        final_findings = []
                        seen_semantic_keys = set()
                        for finding in binding.get("panel-finding-register", []):
                            semantic_key = (
                                finding["authority-domain"],
                                finding["criterion"],
                                tuple(finding["evidence"]),
                            )
                            if semantic_key in seen_semantic_keys:
                                continue
                            seen_semantic_keys.add(semantic_key)
                            final_finding = dict(finding)
                            final_findings.append(final_finding)
                        decision["findings"] = final_findings
                        if any(
                            finding["severity"].strip().lower()
                            in {"critical", "high", "medium"}
                            and finding["disposition"]
                            in {"open", "disputed", "human-required"}
                            for finding in final_findings
                        ):
                            decision["status"] = "FAIL"
                results.append(
                    DispatchResult(
                        handle,
                        DispatchStatus.SUCCEEDED,
                        output=json.dumps({"evidence": documents}, sort_keys=True),
                        evidence=request.evidence,
                    )
                )
        return tuple(results)

    def retry(self, handle: DispatchHandle, reason: str) -> DispatchHandle:
        assert reason
        if handle.route in self.retry_errors:
            raise RuntimeError("injected retry launch failure")
        retried = DispatchHandle(
            handle.id,
            handle.route,
            handle.attempt + 1,
            provider=handle.provider,
            required_capabilities=handle.required_capabilities,
            attested_capabilities=handle.attested_capabilities,
        )
        self.requests[retried] = self.requests[handle]
        return retried

    def cancel(self, handle: DispatchHandle, reason: str) -> None:
        assert reason
        self.cancelled.add(handle)


class PlanningMutationDispatcher(FakeDispatcher):
    def __init__(
        self, mutations: Mapping[str, Callable[[dict[str, object]], None]]
    ) -> None:
        super().__init__()
        self.mutations = dict(mutations)

    def collect(self, handles: Sequence[DispatchHandle]) -> tuple[DispatchResult, ...]:
        results = list(super().collect(handles))
        for index, result in enumerate(results):
            request = self.requests[result.handle]
            stage_id = request.objective.removeprefix("Stage ").split(":", 1)[0]
            mutation = self.mutations.get(stage_id)
            if mutation is None or result.status is not DispatchStatus.SUCCEEDED:
                continue
            envelope = json.loads(result.output or "{}")
            mutation(envelope)
            results[index] = DispatchResult(
                result.handle,
                result.status,
                output=json.dumps(envelope, sort_keys=True),
                evidence=result.evidence,
            )
        return tuple(results)


def _planning_blocker() -> dict[str, object]:
    return {
        "finding-id": "BACKEND-PLAN-001",
        "severity": "High",
        "disposition": "open",
        "authority-domain": "backend",
        "criterion": "The transaction boundary must be explicit.",
        "evidence": ["specs/plan.md:12"],
        "requested-correction": "Define the transaction boundary.",
        "owner": "technical-architect",
    }


@dataclass
class MemoryLedger:
    completed: set[str]
    resolved: set[str]

    def __init__(self) -> None:
        self.completed = set()
        self.advisory_completed: set[str] = set()
        self.skipped: set[str] = set()
        self.resolved = set()
        self.claimed: list[tuple[str, DispatchHandle]] = []
        self.running: set[str] = set()
        self.finished: list[tuple[str, DispatchStatus]] = []
        self.paused: list[HumanStopRequest] = []
        self.conditions: dict[str, bool] = {}
        self.conditions_bound = False
        self.dependency_contexts: list[tuple[str, tuple[str, ...]]] = []
        self.completions: list[tuple[str, ...]] = []
        self.stage_results: dict[str, DispatchResult] = {}

    def completed_stage_ids(self) -> frozenset[str]:
        return frozenset(self.completed | self.advisory_completed)

    def skipped_stage_ids(self) -> frozenset[str]:
        return frozenset(self.skipped)

    def resolved_gate_ids(self) -> frozenset[str]:
        return frozenset(self.resolved)

    def condition_decisions(self) -> dict[str, bool]:
        return dict(self.conditions)

    def bind_condition_decisions(
        self, decisions: Mapping[str, bool]
    ) -> dict[str, bool]:
        if self.conditions_bound and self.conditions != decisions:
            raise RuntimeError("workflow condition decisions differ from frozen values")
        self.conditions = dict(decisions)
        self.conditions_bound = True
        return dict(self.conditions)

    def dependency_context(self, stage: WorkflowStageDefinition) -> str:
        self.dependency_contexts.append((stage.id, stage.depends_on))
        rendered = []
        for dependency in stage.depends_on:
            if dependency in self.skipped:
                rendered.append(f"Dependency stage {dependency!r} was skipped.")
                continue
            result = self.stage_results.get(dependency)
            if result is None:
                rendered.append(f"Dependency stage {dependency!r} is inactive.")
                continue
            rendered.append(
                f"Dependency stage {dependency!r}; status={result.status.value}:\n"
                + (result.output or "(no textual output)")
            )
        return "\n".join(rendered)

    def dependency_evidence(
        self, stage: WorkflowStageDefinition
    ) -> tuple[_DependencyStageEvidence, ...]:
        evidence: list[_DependencyStageEvidence] = []
        for dependency in stage.depends_on:
            if dependency in self.skipped:
                evidence.append(
                    _DependencyStageEvidence(
                        dependency,
                        "skipped",
                        None,
                        None,
                        None,
                        skip_condition="test-condition",
                        skip_attestation_sha256="a" * 64,
                    )
                )
                continue
            result = self.stage_results.get(dependency)
            if result is None:
                raise AssertionError(f"missing dependency result for {dependency}")
            envelope = json.loads(result.output or "{}")
            documents = envelope.get("evidence", {})
            digests = tuple(
                (
                    evidence_id,
                    hashlib.sha256(
                        (
                            json.dumps(
                                document,
                                ensure_ascii=False,
                                allow_nan=False,
                                separators=(",", ":"),
                                sort_keys=True,
                            )
                            + "\n"
                        ).encode("utf-8")
                    ).hexdigest(),
                )
                for evidence_id, document in sorted(documents.items())
            )
            evidence.append(
                _DependencyStageEvidence(
                    dependency,
                    (
                        "advisory-fail"
                        if dependency in self.advisory_completed
                        else "succeeded"
                    ),
                    result.handle.route,
                    result.output,
                    hashlib.sha256((result.output or "").encode("utf-8")).hexdigest(),
                    digests,
                )
            )
        return tuple(evidence)

    def attest_skip(
        self,
        stage: WorkflowStageDefinition,
        dependency_states: Mapping[str, str],
    ) -> None:
        assert set(dependency_states) == set(stage.depends_on)
        self.skipped.add(stage.id)

    def claim(self, stage: WorkflowStageDefinition, handle: DispatchHandle) -> None:
        if stage.id in self.completed:
            raise AssertionError("completed stage was claimed again")
        if stage.id in self.running:
            raise AssertionError("stage already has a running claim")
        self.claimed.append((stage.id, handle))
        self.running.add(stage.id)

    def finish(self, stage: WorkflowStageDefinition, result: DispatchResult) -> None:
        self.finished.append((stage.id, result.status))
        self.running.discard(stage.id)
        self.stage_results[stage.id] = result
        if result.status is DispatchStatus.SUCCEEDED:
            self.completed.add(stage.id)
        elif result.error == pipeline.MANAGED_ADVISORY_PLANNING_FAILURE:
            self.advisory_completed.add(stage.id)

    def attest_completion(self, active_stages: Sequence[str]) -> None:
        self.completions.append(tuple(active_stages))

    def pause(self, stop) -> None:
        self.paused.append(stop)


class _OneRoleLoader:
    def __init__(self, role: NativeRoleDefinition) -> None:
        self.role = role

    def load(self, provider: Provider, role: str) -> NativeRoleDefinition:
        assert provider is Provider.CODEX
        assert role == self.role.id
        return self.role


class _NoContainmentBackend:
    descendant_containment = False

    def __init__(self, outcome: ProcessOutcome) -> None:
        self.outcome = outcome
        self.started: list[dict[str, object]] = []

    def start(
        self, argv: Sequence[str], *, cwd: Path, env: Mapping[str, str]
    ) -> object:
        self.started.append(
            {"argv": tuple(argv), "cwd": cwd, "env": dict(env), "prompt": None}
        )
        return len(self.started) - 1

    def submit(self, process: object, prompt: str) -> None:
        assert isinstance(process, int)
        self.started[process]["prompt"] = prompt

    def poll(self, process: object) -> ProcessOutcome:
        del process
        return self.outcome

    def terminate(self, process: object) -> ProcessOutcome:
        del process
        return ProcessOutcome(-15, stderr="terminated")


def test_actual_canonical_codex_read_only_gate_owner_reaches_python_checkpoint(
    tmp_path: Path, payload: Path
):
    subprocess.run(("git", "init", "-q", str(tmp_path)), check=True)
    specification = tmp_path / "specs/feature_spec.md"
    specification.parent.mkdir()
    specification.write_text(
        "# Feature spec\n\nR1: Return a bounded health response.\n",
        encoding="utf-8",
    )
    subprocess.run(("git", "add", "specs/feature_spec.md"), cwd=tmp_path, check=True)
    canonical = find_canonical_agent(
        payload,
        "em-reviewer",
        kind=AgentSourceKind.CORE,
    ).spec
    role = NativeRoleDefinition(
        id=canonical.id,
        description=canonical.description,
        instructions=canonical.instructions,
        permission=canonical.permission,
        capabilities=canonical.capabilities,
        write_scope=canonical.write_scope,
        isolation=canonical.isolation,
        nested_delegation=canonical.nested_delegation,
        model_tier=canonical.model_tier,
    )
    gate = WorkflowGate(
        "em-approved",
        "planning-merge",
        GateRequirement.REQUIRED,
        False,
        (),
        ("review-verdict",),
    )
    stage = WorkflowStageDefinition(
        "planning-merge",
        "planning",
        "management-review",
        (),
        None,
        "always",
        ("em-approved",),
        "default",
        ("review-verdict",),
        canonical.capabilities,
    )
    base = _bound_workflow().definition
    definition = replace(
        base,
        id="codex-read-only-gate-owner",
        title="Codex read-only gate owner",
        roles={
            "management-review": RoleRoute(
                "management-review",
                "em-reviewer",
                (),
                "Review the frozen specification.",
            )
        },
        evidence_requirements={
            "review-verdict": EvidenceRequirement(
                "review-verdict",
                EvidenceKind.VERDICT,
                "Review verdict",
                ("status", "reviewer", "findings", "evidence"),
                True,
            )
        },
        ordered_gates=("em-approved",),
        gates={"em-approved": gate},
        stages=(stage,),
        parallel_groups={},
        modes={
            "read-only": WorkflowMode(
                "read-only",
                "B",
                "Exercise one passive native gate owner.",
                ("test",),
                True,
                (),
                (),
                GatePolicy.RESOLVED_PLAN,
                (),
                {},
                None,
            )
        },
    )
    workflow = BoundWorkflow(
        definition,
        (gate,),
        ("planning-merge",),
        "codex-read-only-gate-digest",
    )
    backend = _NoContainmentBackend(
        ProcessOutcome(
            0,
            json.dumps(
                {
                    "status": "succeeded",
                    "output": json.dumps(
                        {
                            "evidence": {
                                "review-verdict": {
                                    "status": "PASS",
                                    "reviewer": "em-reviewer",
                                    "findings": [],
                                    "evidence": ["specs/feature_spec.md"],
                                }
                            }
                        },
                        sort_keys=True,
                    ),
                    "evidence": ["artifact://review-verdict"],
                }
            ),
        )
    )
    dispatcher = CodexProcessDispatcher(
        tmp_path,
        backend=backend,
        role_loader=_OneRoleLoader(role),
        lockdown_probe=lambda *_: True,
    )
    ledger = MemoryLedger()

    result = WorkflowExecutor(
        workflow,
        dispatcher,
        ledger,
        mode="B",
        objective="Review the feature specification.",
        workspace_resolver=ProjectWorkspaceResolver(tmp_path),
        wait_timeout_seconds=1,
    ).run()

    assert result.status is WorkflowExecutionStatus.WAITING_GATE
    assert result.pending_gates == ("em-approved",)
    assert result.completed_stages == ("planning-merge",)
    assert len(result.attempts) == 1
    assert result.attempts[0].role == "em-reviewer"
    assert result.attempts[0].handle.provider == "codex"
    argv = backend.started[0]["argv"]
    assert isinstance(argv, tuple)
    disabled = {
        argv[index + 1] for index, value in enumerate(argv[:-1]) if value == "--disable"
    }
    assert {"shell_tool", "hooks", "plugins", "multi_agent"}.issubset(disabled)
    prompt = str(backend.started[0]["prompt"])
    assert "You are **Agent 3: EM Reviewer**" in prompt
    assert '"path":"specs/feature_spec.md"' in prompt
    assert "Coordinator-captured bounded source projection" in prompt
    assert ledger.completed == {"planning-merge"}


def test_executor_routes_dependencies_parallel_join_and_gate_checkpoint():
    dispatcher = FakeDispatcher()
    ledger = MemoryLedger()
    executor = WorkflowExecutor(
        _bound_workflow(),
        dispatcher,
        ledger,
        mode="B",
        objective="Deliver the bounded change.",
    )

    result = executor.run()

    assert result.status is WorkflowExecutionStatus.WAITING_GATE
    assert result.pending_gates == ("quality",)
    assert dispatcher.wait_batches == [
        ("planner",),
        ("left-worker", "right-worker"),
        ("reviewer",),
    ]
    assert ledger.completed == {"plan", "left", "right", "review"}

    ledger.resolved.add("quality")
    resumed = WorkflowExecutor(
        _bound_workflow(),
        dispatcher,
        ledger,
        mode="test-mode",
        objective="Deliver the bounded change.",
    ).run()
    assert resumed.status is WorkflowExecutionStatus.SUCCEEDED


def test_executor_injects_hash_verified_authoritative_mutable_context(
    tmp_path, payload
):
    selection = catalog.defaults(payload)
    options = InitOptions(
        "test",
        selection,
        [],
        runtimes=["codex"],
        state_layout=StateLayout.neutral(),
        rendering_version=2,
        compatibility_catalog_versions={"codex": 1},
    )
    continuity = tmp_path / options.state_layout.continuity
    memory = tmp_path / options.state_layout.memory / "patterns" / "memory.md"
    continuity.parent.mkdir(parents=True)
    memory.parent.mkdir(parents=True)
    continuity.write_text("current checkpoint\n", encoding="utf-8")
    memory.write_text("current learning\n", encoding="utf-8")
    dispatcher = FakeDispatcher()
    ledger = MemoryLedger()

    result = WorkflowExecutor(
        _bound_workflow(),
        dispatcher,
        ledger,
        mode="B",
        objective="Deliver the bounded change.",
        runtime_context_provider=lambda: _mutable_runtime_context(tmp_path, options),
    ).run()

    assert result.status is WorkflowExecutionStatus.WAITING_GATE
    contexts = [request.context for request in dispatcher.requests.values()]
    assert contexts
    assert all("Authoritative mutable context snapshot" in item for item in contexts)
    assert all(
        "current checkpoint" in item and "current learning" in item for item in contexts
    )
    expected = hashlib.sha256(continuity.read_bytes()).hexdigest()
    assert all(expected in item for item in contexts)
    assert all(len(item.encode("utf-8")) <= 131_072 for item in contexts)
    assert len(dispatcher.wait_batches) == 3, "completed stages must not be rerun"


def test_parallel_join_compiles_lane_terminals_into_verified_handoffs():
    workflow = _bound_workflow()
    definition = replace(
        workflow.definition,
        stages=tuple(
            replace(stage, depends_on=("plan",)) if stage.id == "review" else stage
            for stage in workflow.definition.stages
        ),
    )
    bound = BoundWorkflow(
        definition,
        workflow.active_gates,
        workflow.gate_stage_ids,
        workflow.gate_definition_digest,
    )
    ledger = MemoryLedger()

    result = WorkflowExecutor(
        bound, FakeDispatcher(), ledger, mode="B", objective="Deliver."
    ).run()

    assert result.status is WorkflowExecutionStatus.WAITING_GATE
    assert ("review", ("plan", "left", "right")) in ledger.dependency_contexts


def test_large_dependency_output_uses_bounded_authenticated_prefix(tmp_path):
    output = "é" * 350_000
    artifact_document = {"stage": "implementation", "output": output}
    artifact = json.dumps(artifact_document, ensure_ascii=False).encode("utf-8")
    relative = ".ckit/artifacts/dispatch/implementation.json"
    artifact_path = tmp_path / relative
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_bytes(artifact)
    snapshot_path = tmp_path / ".ckit/state/pipeline-snapshot.json"
    snapshot_path.parent.mkdir(parents=True)
    snapshot_path.write_text(
        json.dumps(
            {
                "stage_history": [
                    {
                        "stage": "implementation",
                        "status": "succeeded",
                        "output_path": relative,
                        "output_artifact_sha256": hashlib.sha256(artifact).hexdigest(),
                        "output_sha256": hashlib.sha256(output.encode()).hexdigest(),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    stage = WorkflowStageDefinition(
        id="review",
        phase="review",
        route="code-review",
        depends_on=("implementation",),
        parallel_group=None,
        condition="always",
        gates=(),
        retry_budget="default",
        evidence=(),
    )

    context = PipelineStageLedger(tmp_path).dependency_context(stage)

    assert len(context.encode("utf-8")) <= 524_288
    assert "dependency output prefix truncated" in context
    assert hashlib.sha256(artifact).hexdigest() in context


def test_executor_checkpoints_an_intentionally_skipped_gate_owner_after_dependencies():
    workflow = _bound_workflow()
    definition = replace(
        workflow.definition,
        stages=tuple(
            replace(stage, condition="review-required")
            if stage.id == "review"
            else stage
            for stage in workflow.definition.stages
        ),
    )
    bound = BoundWorkflow(
        definition,
        workflow.active_gates,
        workflow.gate_stage_ids,
        workflow.gate_definition_digest,
    )
    dispatcher = FakeDispatcher()
    ledger = MemoryLedger()

    result = WorkflowExecutor(
        bound,
        dispatcher,
        ledger,
        mode="B",
        objective="Deliver.",
        conditions={"review-required": False},
    ).run()

    assert result.status is WorkflowExecutionStatus.WAITING_GATE
    assert result.pending_gates == ("quality",)
    assert "review" in result.skipped_stages
    assert ledger.completed == {"plan", "left", "right"}
    assert all(handle.route != "reviewer" for handle in dispatcher.requests)


def test_executor_retries_within_budget_and_preserves_attempts():
    dispatcher = FakeDispatcher()
    dispatcher.fail_once.add("planner")
    ledger = MemoryLedger()

    result = WorkflowExecutor(
        _bound_workflow(),
        dispatcher,
        ledger,
        mode="B",
        objective="Deliver.",
    ).run()

    assert result.status is WorkflowExecutionStatus.WAITING_GATE
    plan_attempts = [attempt for attempt in result.attempts if attempt.stage == "plan"]
    assert [attempt.handle.attempt for attempt in plan_attempts] == [1, 2]
    assert [attempt.status for attempt in plan_attempts] == [
        DispatchStatus.FAILED,
        DispatchStatus.SUCCEEDED,
    ]


def test_executor_rejects_eager_dispatcher_before_spawn():
    class EagerDispatcher(FakeDispatcher):
        queued_spawn = False

        def __init__(self) -> None:
            super().__init__()
            self.spawn_calls = 0

        def spawn(self, request: DispatchRequest) -> DispatchHandle:
            self.spawn_calls += 1
            return super().spawn(request)

    dispatcher = EagerDispatcher()
    ledger = MemoryLedger()

    result = WorkflowExecutor(
        _bound_workflow(), dispatcher, ledger, mode="B", objective="Deliver."
    ).run()

    assert result.status is WorkflowExecutionStatus.HUMAN_STOP
    assert result.human_stop is not None
    assert result.human_stop.reason.value == "unsupported-required-capability"
    assert dispatcher.spawn_calls == 0
    assert ledger.claimed == []


def test_retry_requires_fresh_queued_spawn_attestation():
    class FlippingDispatcher(FakeDispatcher):
        def __init__(self) -> None:
            super().__init__()
            self.retry_calls = 0
            self.fail_once.add("planner")

        def collect(
            self, handles: Sequence[DispatchHandle]
        ) -> tuple[DispatchResult, ...]:
            results = super().collect(handles)
            if any(result.status is DispatchStatus.FAILED for result in results):
                self.queued_spawn = False
            return results

        def retry(self, handle: DispatchHandle, reason: str) -> DispatchHandle:
            self.retry_calls += 1
            return super().retry(handle, reason)

    dispatcher = FlippingDispatcher()
    result = WorkflowExecutor(
        _bound_workflow(), dispatcher, MemoryLedger(), mode="B", objective="Deliver."
    ).run()

    assert result.status is WorkflowExecutionStatus.HUMAN_STOP
    assert result.human_stop is not None
    assert result.human_stop.reason.value == "unsupported-required-capability"
    assert dispatcher.retry_calls == 0


def test_executor_never_completes_a_succeeded_dispatch_with_failing_typed_evidence():
    class FailingVerdictDispatcher(FakeDispatcher):
        def collect(
            self, handles: Sequence[DispatchHandle]
        ) -> tuple[DispatchResult, ...]:
            results = list(super().collect(handles))
            for index, result in enumerate(results):
                if (
                    result.handle.route == "reviewer"
                    and result.status is DispatchStatus.SUCCEEDED
                ):
                    envelope = json.loads(result.output or "{}")
                    envelope["evidence"]["review-verdict"]["status"] = "FAIL"
                    envelope["evidence"]["review-verdict"]["findings"] = [
                        {
                            "id": "CRIT-1",
                            "severity": "critical",
                            "disposition": "open",
                            "evidence": ["tests/test_workflow_executor.py"],
                        }
                    ]
                    results[index] = DispatchResult(
                        result.handle,
                        DispatchStatus.SUCCEEDED,
                        output=json.dumps(envelope, sort_keys=True),
                        evidence=result.evidence,
                    )
            return tuple(results)

    ledger = MemoryLedger()
    result = WorkflowExecutor(
        _bound_workflow(),
        FailingVerdictDispatcher(),
        ledger,
        mode="B",
        objective="Deliver.",
    ).run()

    assert result.status is WorkflowExecutionStatus.HUMAN_STOP
    assert "review" not in ledger.completed
    review_attempts = [
        attempt for attempt in result.attempts if attempt.stage == "review"
    ]
    assert review_attempts
    assert len(review_attempts) == 1
    assert all(attempt.status is DispatchStatus.FAILED for attempt in review_attempts)
    assert all("not PASS" in (attempt.error or "") for attempt in review_attempts)
    assert result.human_stop is not None
    assert result.human_stop.reason.value == "conflicting-evidence"


def _planning_test_context(payload: Path):
    from claude_kit.workflows import bind_workflow, load_workflow

    selection = catalog.defaults(payload)
    selection.profile = "standard"
    plan = catalog.resolve(payload, selection)
    bound = bind_workflow(load_workflow(payload), plan)
    derived = {
        "always",
        "full-sdlc-or-program",
        "fast-track-selected",
        "program-mode-selected",
        "security-gate-active",
        "acceptance-gate-active",
        "all-active-gates-closed",
        "fast-track-gates-closed",
        "all-waves-and-gates-closed",
    }
    included_panel_conditions = {
        "frontend-surface-present",
        "backend-surface-present",
        "risk-or-uncertainty-present",
    }
    conditions = {
        stage.condition: stage.condition in included_panel_conditions
        for stage in bound.stages_for_mode("B")
        if stage.condition not in derived
    }
    return plan, bound, conditions


def _run_through_spec_gate(
    payload: Path,
    dispatcher: FakeDispatcher,
    ledger: MemoryLedger,
):
    plan, bound, conditions = _planning_test_context(payload)
    dispatcher.available_roles = set(plan.agents) | set(plan.overlay_agents)
    first = WorkflowExecutor(
        bound,
        dispatcher,
        ledger,
        mode="B",
        objective="Deliver the bounded plan.",
        conditions=conditions,
    ).run()
    assert first.status is WorkflowExecutionStatus.WAITING_GATE
    assert first.pending_gates == ("spec-complete",)
    ledger.resolved.add("spec-complete")
    second = WorkflowExecutor(
        bound,
        dispatcher,
        ledger,
        mode="B",
        objective="Deliver the bounded plan.",
    ).run()
    return second, bound


def test_planning_panel_blocker_settles_once_and_stops_at_em(payload: Path):
    def fail_backend(envelope: dict[str, object]) -> None:
        evidence = envelope["evidence"]
        assert isinstance(evidence, dict)
        verdict = evidence["planning-review-verdict"]
        assert isinstance(verdict, dict)
        verdict["status"] = "FAIL"
        verdict["findings"] = [_planning_blocker()]

    dispatcher = PlanningMutationDispatcher({"backend-review": fail_backend})
    ledger = MemoryLedger()

    result, _bound = _run_through_spec_gate(payload, dispatcher, ledger)

    assert result.status is WorkflowExecutionStatus.HUMAN_STOP
    assert result.human_stop is not None
    assert result.human_stop.reason.value == "conflicting-evidence"
    assert "backend-review" in result.completed_stages
    assert "backend-review" in ledger.advisory_completed
    assert ledger.finished.count(("backend-review", DispatchStatus.FAILED)) == 1
    assert "planning-merge" not in ledger.completed
    merge_handle = next(
        handle
        for handle, request in dispatcher.requests.items()
        if request.objective.startswith("Stage planning-merge:")
    )
    merge_request = dispatcher.requests[merge_handle]
    for stage_id in (
        "frontend-review",
        "backend-review",
        "architecture-review",
        "plan-critique",
    ):
        panel_output = ledger.stage_results[stage_id].output
        assert panel_output is not None
        assert merge_request.context.count(panel_output) == 1
    merge_output = ledger.stage_results["planning-merge"].output
    merge_envelope = json.loads(merge_output or "{}")
    decision = merge_envelope["evidence"]["planning-decision"]
    assert decision["panel-reviewers"] == [
        "senior-frontend-reviewer",
        "senior-backend-reviewer",
        "technical-architect",
        "devils-advocate",
    ]
    assert decision["findings"] == [
        {**_planning_blocker(), "severity": "high", "disposition": "open"}
    ]
    assert decision["status"] == "FAIL"
    planning_output = ledger.stage_results["planning-gate"].output
    planning_envelope = json.loads(planning_output or "{}")
    packet_digests = tuple(
        (
            evidence_id,
            hashlib.sha256(
                (
                    json.dumps(
                        document,
                        ensure_ascii=False,
                        allow_nan=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    )
                    + "\n"
                ).encode("utf-8")
            ).hexdigest(),
        )
        for evidence_id, document in sorted(planning_envelope["evidence"].items())
    )
    expected_generation = _planning_packet_generation(
        _DependencyStageEvidence(
            "planning-gate",
            "succeeded",
            "orchestrator",
            planning_output,
            hashlib.sha256((planning_output or "").encode("utf-8")).hexdigest(),
            packet_digests,
        )
    )
    for stage_id in (
        "frontend-review",
        "backend-review",
        "architecture-review",
        "plan-critique",
    ):
        panel_envelope = json.loads(ledger.stage_results[stage_id].output or "{}")
        assert (
            panel_envelope["evidence"]["planning-review-verdict"]["planning-generation"]
            == expected_generation
        )
    assert decision["planning-generation"] == expected_generation


@pytest.mark.parametrize(
    "inherited_disposition", ["open", "disputed", "human-required"]
)
def test_same_generation_em_cannot_launder_inherited_unresolved_finding(
    payload: Path, inherited_disposition: str
):
    def panel_blocker(envelope: dict[str, object]) -> None:
        evidence = envelope["evidence"]
        assert isinstance(evidence, dict)
        verdict = evidence["planning-review-verdict"]
        assert isinstance(verdict, dict)
        finding = _planning_blocker()
        finding["disposition"] = inherited_disposition
        verdict["status"] = "FAIL"
        verdict["findings"] = [finding]

    def launder_at_merge(envelope: dict[str, object]) -> None:
        evidence = envelope["evidence"]
        assert isinstance(evidence, dict)
        decision = evidence["planning-decision"]
        assert isinstance(decision, dict)
        findings = decision["findings"]
        assert isinstance(findings, list) and len(findings) == 1
        finding = findings[0]
        assert isinstance(finding, dict)
        finding["disposition"] = "fixed"
        decision["status"] = "PASS"

    dispatcher = PlanningMutationDispatcher(
        {"backend-review": panel_blocker, "planning-merge": launder_at_merge}
    )

    result, _bound = _run_through_spec_gate(payload, dispatcher, MemoryLedger())

    assert result.status is WorkflowExecutionStatus.HUMAN_STOP
    merge_attempt = next(
        attempt for attempt in result.attempts if attempt.stage == "planning-merge"
    )
    assert (
        "same-generation planning decision cannot close or downgrade an inherited "
        "unresolved panel finding"
    ) in (merge_attempt.error or "")


def test_planning_generation_hashes_complete_typed_packet_and_each_component():
    base = _DependencyStageEvidence(
        "planning-gate",
        "succeeded",
        "orchestrator",
        "{}",
        "f" * 64,
        (
            ("architecture-plan", "a" * 64),
            ("review-verdict", "b" * 64),
            ("specification", "c" * 64),
        ),
    )
    changed_specification = replace(
        base,
        evidence_sha256=(
            ("architecture-plan", "a" * 64),
            ("review-verdict", "b" * 64),
            ("specification", "d" * 64),
        ),
    )
    changed_architecture = replace(
        base,
        evidence_sha256=(
            ("architecture-plan", "e" * 64),
            ("review-verdict", "b" * 64),
            ("specification", "c" * 64),
        ),
    )

    generations = {
        _planning_packet_generation(base),
        _planning_packet_generation(changed_specification),
        _planning_packet_generation(changed_architecture),
    }

    assert len(generations) == 3


@pytest.mark.parametrize(
    ("stage_id", "field", "spoofed", "message"),
    [
        (
            "backend-review",
            "planning-generation",
            "0" * 64,
            "different frozen generation",
        ),
        (
            "backend-review",
            "reviewer",
            "invented-reviewer",
            "reviewer differs from its frozen assignment",
        ),
        (
            "backend-review",
            "authority-domain",
            "product",
            "authority domain differs from its stage",
        ),
        (
            "planning-merge",
            "panel-reviewers",
            ["invented-reviewer"],
            "reviewer panel differs from the complete applicable panel",
        ),
    ],
)
def test_planning_bindings_reject_spoofed_digest_reviewer_and_panel(
    payload: Path,
    stage_id: str,
    field: str,
    spoofed: object,
    message: str,
):
    evidence_id = (
        "planning-decision"
        if stage_id == "planning-merge"
        else "planning-review-verdict"
    )

    def spoof(envelope: dict[str, object]) -> None:
        evidence = envelope["evidence"]
        assert isinstance(evidence, dict)
        document = evidence[evidence_id]
        assert isinstance(document, dict)
        document[field] = spoofed

    dispatcher = PlanningMutationDispatcher({stage_id: spoof})
    ledger = MemoryLedger()

    result, _bound = _run_through_spec_gate(payload, dispatcher, ledger)

    assert result.status is WorkflowExecutionStatus.HUMAN_STOP
    assert result.human_stop is not None
    assert result.human_stop.reason.value == "conflicting-evidence"
    matching = [attempt for attempt in result.attempts if attempt.stage == stage_id]
    assert len(matching) == 1
    assert message in (matching[0].error or "")
    if stage_id != "planning-merge":
        assert "planning-merge" not in ledger.stage_results


def test_planning_decision_cannot_replace_frozen_architecture_plan(payload: Path):
    def replace_architecture_plan(envelope: dict[str, object]) -> None:
        evidence = envelope["evidence"]
        assert isinstance(evidence, dict)
        architecture = evidence["architecture-plan"]
        assert isinstance(architecture, dict)
        architecture["boundaries"] = ["unreviewed replacement boundary"]

    dispatcher = PlanningMutationDispatcher(
        {"planning-merge": replace_architecture_plan}
    )
    ledger = MemoryLedger()

    result, _bound = _run_through_spec_gate(payload, dispatcher, ledger)

    assert result.status is WorkflowExecutionStatus.HUMAN_STOP
    assert result.human_stop is not None
    assert result.human_stop.reason.value == "conflicting-evidence"
    merge_attempt = next(
        attempt for attempt in result.attempts if attempt.stage == "planning-merge"
    )
    assert "architecture-plan differs from the frozen reviewed plan" in (
        merge_attempt.error or ""
    )
    assert "planning-merge" not in ledger.completed


def test_story_planning_cannot_replace_em_approved_architecture_plan(payload: Path):
    def replace_architecture_plan(envelope: dict[str, object]) -> None:
        evidence = envelope["evidence"]
        assert isinstance(evidence, dict)
        architecture = evidence["architecture-plan"]
        assert isinstance(architecture, dict)
        architecture["interfaces"] = ["unreviewed story-planner interface"]

    dispatcher = PlanningMutationDispatcher(
        {"story-planning": replace_architecture_plan}
    )
    ledger = MemoryLedger()
    planning_result, bound = _run_through_spec_gate(payload, dispatcher, ledger)
    assert planning_result.status is WorkflowExecutionStatus.WAITING_GATE
    assert planning_result.pending_gates == ("em-approved",)
    ledger.resolved.add("em-approved")

    result = WorkflowExecutor(
        bound,
        dispatcher,
        ledger,
        mode="B",
        objective="Deliver the bounded plan.",
    ).run()

    assert result.status is WorkflowExecutionStatus.HUMAN_STOP
    story_attempt = next(
        attempt for attempt in result.attempts if attempt.stage == "story-planning"
    )
    assert "story decomposition replaced the EM-approved architecture-plan" in (
        story_attempt.error or ""
    )
    assert "story-planning" not in ledger.completed


def test_planning_decision_requires_complete_deduplicated_panel_register(
    payload: Path,
):
    def fail_backend(envelope: dict[str, object]) -> None:
        evidence = envelope["evidence"]
        assert isinstance(evidence, dict)
        verdict = evidence["planning-review-verdict"]
        assert isinstance(verdict, dict)
        verdict["status"] = "FAIL"
        verdict["findings"] = [_planning_blocker()]

    def omit_register(envelope: dict[str, object]) -> None:
        evidence = envelope["evidence"]
        assert isinstance(evidence, dict)
        decision = evidence["planning-decision"]
        assert isinstance(decision, dict)
        decision["findings"] = []
        decision["status"] = "PASS"

    dispatcher = PlanningMutationDispatcher(
        {"backend-review": fail_backend, "planning-merge": omit_register}
    )
    result, _bound = _run_through_spec_gate(payload, dispatcher, MemoryLedger())

    assert result.status is WorkflowExecutionStatus.HUMAN_STOP
    merge_attempt = next(
        attempt for attempt in result.attempts if attempt.stage == "planning-merge"
    )
    assert "does not disposition every unique panel finding" in (
        merge_attempt.error or ""
    )


def test_planning_decision_deduplicates_panel_ids_by_semantic_key(payload: Path):
    def duplicate_semantic_finding(
        finding_id: str,
    ) -> Callable[[dict[str, object]], None]:
        def mutate(envelope: dict[str, object]) -> None:
            evidence = envelope["evidence"]
            assert isinstance(evidence, dict)
            verdict = evidence["planning-review-verdict"]
            assert isinstance(verdict, dict)
            finding = _planning_blocker()
            finding["finding-id"] = finding_id
            finding["severity"] = "Low"
            finding["disposition"] = "advisory"
            verdict["findings"] = [finding]

        return mutate

    dispatcher = PlanningMutationDispatcher(
        {
            "frontend-review": duplicate_semantic_finding("FRONTEND-PLAN-001"),
            "backend-review": duplicate_semantic_finding("BACKEND-PLAN-001"),
        }
    )
    ledger = MemoryLedger()

    result, _bound = _run_through_spec_gate(payload, dispatcher, ledger)

    assert result.status is WorkflowExecutionStatus.WAITING_GATE
    merge_envelope = json.loads(ledger.stage_results["planning-merge"].output or "{}")
    final_findings = merge_envelope["evidence"]["planning-decision"]["findings"]
    assert len(final_findings) == 1
    assert final_findings[0]["finding-id"] in {
        "FRONTEND-PLAN-001",
        "BACKEND-PLAN-001",
    }


def test_planning_decision_requires_ledger_for_conflicting_panel_positions(
    payload: Path,
):
    def conflicting_position(
        finding_id: str, correction: str, owner: str
    ) -> Callable[[dict[str, object]], None]:
        def mutate(envelope: dict[str, object]) -> None:
            evidence = envelope["evidence"]
            assert isinstance(evidence, dict)
            verdict = evidence["planning-review-verdict"]
            assert isinstance(verdict, dict)
            finding = _planning_blocker()
            finding["finding-id"] = finding_id
            finding["severity"] = "Low"
            finding["disposition"] = "advisory"
            finding["requested-correction"] = correction
            finding["owner"] = owner
            verdict["findings"] = [finding]

        return mutate

    dispatcher = PlanningMutationDispatcher(
        {
            "frontend-review": conflicting_position(
                "FRONTEND-PLAN-001", "Use a client-owned transaction.", "frontend"
            ),
            "backend-review": conflicting_position(
                "BACKEND-PLAN-001", "Use a service-owned transaction.", "backend"
            ),
        }
    )

    result, _bound = _run_through_spec_gate(payload, dispatcher, MemoryLedger())

    assert result.status is WorkflowExecutionStatus.HUMAN_STOP
    merge_attempt = next(
        attempt for attempt in result.attempts if attempt.stage == "planning-merge"
    )
    assert "must record the selected and rejected alternatives" in (
        merge_attempt.error or ""
    )


def test_planning_decision_accepts_cosmetic_severity_alias(payload: Path):
    def cosmetic_finding(envelope: dict[str, object]) -> None:
        evidence = envelope["evidence"]
        assert isinstance(evidence, dict)
        verdict = evidence["planning-review-verdict"]
        assert isinstance(verdict, dict)
        finding = _planning_blocker()
        finding["severity"] = "Cosmetic"
        finding["disposition"] = "advisory"
        verdict["findings"] = [finding]

    dispatcher = PlanningMutationDispatcher({"backend-review": cosmetic_finding})
    ledger = MemoryLedger()

    result, _bound = _run_through_spec_gate(payload, dispatcher, ledger)

    assert result.status is WorkflowExecutionStatus.WAITING_GATE
    panel_envelope = json.loads(ledger.stage_results["backend-review"].output or "{}")
    panel_findings = panel_envelope["evidence"]["planning-review-verdict"]["findings"]
    assert panel_findings[0]["severity"] == "Cosmetic"
    merge_envelope = json.loads(ledger.stage_results["planning-merge"].output or "{}")
    final_findings = merge_envelope["evidence"]["planning-decision"]["findings"]
    assert len(final_findings) == 1
    assert final_findings[0]["severity"] == "info"


def test_planning_decision_cannot_introduce_new_blocking_semantic_key(payload: Path):
    def invent_blocker(envelope: dict[str, object]) -> None:
        evidence = envelope["evidence"]
        assert isinstance(evidence, dict)
        decision = evidence["planning-decision"]
        assert isinstance(decision, dict)
        blocker = _planning_blocker()
        blocker["finding-id"] = "EM-NEW-001"
        blocker["criterion"] = "A new unreviewed criterion."
        decision["status"] = "FAIL"
        decision["findings"] = [blocker]

    dispatcher = PlanningMutationDispatcher({"planning-merge": invent_blocker})
    result, _bound = _run_through_spec_gate(payload, dispatcher, MemoryLedger())

    assert result.status is WorkflowExecutionStatus.HUMAN_STOP
    merge_attempt = next(
        attempt for attempt in result.attempts if attempt.stage == "planning-merge"
    )
    assert "introduces a new blocking semantic key" in (merge_attempt.error or "")


def test_advisory_panel_fail_is_not_rerun_when_em_dispatch_resumes(payload: Path):
    def fail_backend(envelope: dict[str, object]) -> None:
        evidence = envelope["evidence"]
        assert isinstance(evidence, dict)
        verdict = evidence["planning-review-verdict"]
        assert isinstance(verdict, dict)
        verdict["status"] = "FAIL"
        verdict["findings"] = [_planning_blocker()]

    plan, bound, conditions = _planning_test_context(payload)
    dispatcher = PlanningMutationDispatcher({"backend-review": fail_backend})
    all_roles = set(plan.agents) | set(plan.overlay_agents)
    dispatcher.available_roles = all_roles
    ledger = MemoryLedger()
    first = WorkflowExecutor(
        bound,
        dispatcher,
        ledger,
        mode="B",
        objective="Deliver the bounded plan.",
        conditions=conditions,
    ).run()
    assert first.pending_gates == ("spec-complete",)
    ledger.resolved.add("spec-complete")
    management_route = bound.definition.roles["management-review"]
    dispatcher.available_roles = all_roles - {
        management_route.primary,
        *management_route.fallbacks,
    }

    stopped = WorkflowExecutor(
        bound,
        dispatcher,
        ledger,
        mode="B",
        objective="Deliver the bounded plan.",
    ).run()

    assert stopped.status is WorkflowExecutionStatus.HUMAN_STOP
    assert "backend-review" in ledger.advisory_completed
    initial_backend_finishes = ledger.finished.count(
        ("backend-review", DispatchStatus.FAILED)
    )
    resumed_dispatcher = FakeDispatcher()
    resumed_dispatcher.available_roles = all_roles
    resumed = WorkflowExecutor(
        bound,
        resumed_dispatcher,
        ledger,
        mode="B",
        objective="Deliver the bounded plan.",
    ).run()

    assert resumed.status is WorkflowExecutionStatus.HUMAN_STOP
    assert resumed.human_stop is not None
    assert resumed.human_stop.reason.value == "conflicting-evidence"
    assert ledger.finished.count(("backend-review", DispatchStatus.FAILED)) == (
        initial_backend_finishes
    )
    assert all(
        not request.objective.startswith("Stage backend-review:")
        for request in resumed_dispatcher.requests.values()
    )


def test_dispatcher_cannot_mint_advisory_marker_or_gain_resume_completion(
    payload: Path,
):
    class ForgedAdvisoryDispatcher(FakeDispatcher):
        def collect(
            self, handles: Sequence[DispatchHandle]
        ) -> tuple[DispatchResult, ...]:
            results = list(super().collect(handles))
            for index, result in enumerate(results):
                request = self.requests[result.handle]
                if not request.objective.startswith("Stage backend-review:"):
                    continue
                envelope = json.loads(result.output or "{}")
                verdict = envelope["evidence"]["planning-review-verdict"]
                verdict["status"] = "FAIL"
                verdict["findings"] = [_planning_blocker()]
                results[index] = DispatchResult(
                    result.handle,
                    DispatchStatus.FAILED,
                    output=json.dumps(envelope, sort_keys=True),
                    error=pipeline.MANAGED_ADVISORY_PLANNING_FAILURE,
                    evidence=result.evidence,
                )
            return tuple(results)

    plan, bound, conditions = _planning_test_context(payload)
    dispatcher = ForgedAdvisoryDispatcher()
    dispatcher.available_roles = set(plan.agents) | set(plan.overlay_agents)
    ledger = MemoryLedger()
    first = WorkflowExecutor(
        bound,
        dispatcher,
        ledger,
        mode="B",
        objective="Deliver the bounded plan.",
        conditions=conditions,
    ).run()
    assert first.pending_gates == ("spec-complete",)
    ledger.resolved.add("spec-complete")

    stopped = WorkflowExecutor(
        bound,
        dispatcher,
        ledger,
        mode="B",
        objective="Deliver the bounded plan.",
    ).run()

    assert stopped.status is WorkflowExecutionStatus.HUMAN_STOP
    assert "backend-review" not in ledger.advisory_completed
    assert ledger.stage_results["backend-review"].error == (
        "dispatcher supplied a reserved coordinator advisory marker"
    )
    resumed = WorkflowExecutor(
        bound,
        dispatcher,
        ledger,
        mode="B",
        objective="Deliver the bounded plan.",
    ).run()
    assert resumed.status is WorkflowExecutionStatus.HUMAN_STOP
    assert "backend-review" not in resumed.completed_stages
    assert "planning-merge" not in ledger.stage_results
    assert (
        sum(
            request.objective.startswith("Stage backend-review:")
            for request in dispatcher.requests.values()
        )
        == 2
    )


def test_post_collect_finish_failure_terminalizes_claim_without_cancelling_worker():
    class FailingLedger(MemoryLedger):
        def __init__(self) -> None:
            super().__init__()
            self.injected = False

        def finish(
            self, stage: WorkflowStageDefinition, result: DispatchResult
        ) -> None:
            if not self.injected and result.status is DispatchStatus.SUCCEEDED:
                self.injected = True
                raise RuntimeError("injected post-collect persistence failure")
            super().finish(stage, result)

    dispatcher = FakeDispatcher()
    ledger = FailingLedger()
    result = WorkflowExecutor(
        _bound_workflow(), dispatcher, ledger, mode="B", objective="Deliver."
    ).run()

    assert result.status is WorkflowExecutionStatus.HUMAN_STOP
    assert result.human_stop is not None
    assert result.human_stop.reason.value == "conflicting-evidence"
    assert ledger.running == set()
    assert ledger.finished == [("plan", DispatchStatus.CANCELLED)]
    assert dispatcher.cancelled == set()


def test_post_collect_failure_terminalizes_entire_collected_parallel_batch():
    class ParallelFailingLedger(MemoryLedger):
        def __init__(self) -> None:
            super().__init__()
            self.injected = False

        def finish(
            self, stage: WorkflowStageDefinition, result: DispatchResult
        ) -> None:
            if stage.id == "left" and not self.injected:
                self.injected = True
                raise RuntimeError("injected parallel persistence failure")
            super().finish(stage, result)

    ledger = ParallelFailingLedger()
    result = WorkflowExecutor(
        _bound_workflow(), FakeDispatcher(), ledger, mode="B", objective="Deliver."
    ).run()

    assert result.status is WorkflowExecutionStatus.HUMAN_STOP
    assert ledger.running == set()
    assert ("left", DispatchStatus.CANCELLED) in ledger.finished
    assert ("right", DispatchStatus.SUCCEEDED) in ledger.finished


def test_post_collect_interrupt_terminalizes_entire_collected_parallel_batch():
    class InterruptingLedger(MemoryLedger):
        def __init__(self) -> None:
            super().__init__()
            self.injected = False

        def finish(
            self, stage: WorkflowStageDefinition, result: DispatchResult
        ) -> None:
            if (
                stage.id == "left"
                and result.status is DispatchStatus.SUCCEEDED
                and not self.injected
            ):
                self.injected = True
                raise KeyboardInterrupt
            super().finish(stage, result)

    ledger = InterruptingLedger()
    with pytest.raises(KeyboardInterrupt):
        WorkflowExecutor(
            _bound_workflow(), FakeDispatcher(), ledger, mode="B", objective="Deliver."
        ).run()

    assert ledger.running == set()
    assert ("left", DispatchStatus.CANCELLED) in ledger.finished
    assert ("right", DispatchStatus.CANCELLED) in ledger.finished


def test_post_collect_failure_on_retry_terminalizes_retry_claim():
    class RetryFailingLedger(MemoryLedger):
        def finish(
            self, stage: WorkflowStageDefinition, result: DispatchResult
        ) -> None:
            if (
                stage.id == "plan"
                and result.handle.attempt == 2
                and (result.status is DispatchStatus.SUCCEEDED)
            ):
                raise RuntimeError("injected retry persistence failure")
            super().finish(stage, result)

    dispatcher = FakeDispatcher()
    dispatcher.fail_once.add("planner")
    ledger = RetryFailingLedger()
    result = WorkflowExecutor(
        _bound_workflow(), dispatcher, ledger, mode="B", objective="Deliver."
    ).run()

    assert result.status is WorkflowExecutionStatus.HUMAN_STOP
    assert ledger.running == set()
    assert ("plan", DispatchStatus.FAILED) in ledger.finished
    assert ("plan", DispatchStatus.CANCELLED) in ledger.finished


def test_parallel_preflight_failure_cancels_every_claimed_process():
    dispatcher = FakeDispatcher()
    dispatcher.unsupported.add("right-worker")
    ledger = MemoryLedger()

    result = WorkflowExecutor(
        _bound_workflow(),
        dispatcher,
        ledger,
        mode="B",
        objective="Deliver.",
    ).run()

    assert result.status is WorkflowExecutionStatus.HUMAN_STOP
    assert result.human_stop is not None
    assert result.human_stop.reason.value == "unsupported-required-capability"
    left_handle = next(handle for stage, handle in ledger.claimed if stage == "left")
    assert left_handle in dispatcher.cancelled
    assert ("left", DispatchStatus.CANCELLED) in ledger.finished


def test_capability_failure_never_downgrades_to_route_fallback():
    workflow = _bound_workflow()
    routes = dict(workflow.definition.roles)
    routes["planning"] = replace(routes["planning"], fallbacks=("reviewer",))
    bound = BoundWorkflow(
        replace(workflow.definition, roles=routes),
        workflow.active_gates,
        workflow.gate_stage_ids,
        workflow.gate_definition_digest,
    )
    dispatcher = FakeDispatcher()
    dispatcher.unsupported.add("planner")

    result = WorkflowExecutor(
        bound, dispatcher, MemoryLedger(), mode="B", objective="Deliver."
    ).run()

    assert result.status is WorkflowExecutionStatus.HUMAN_STOP
    assert result.human_stop is not None
    assert result.human_stop.reason.value == "unsupported-required-capability"
    assert all(handle.route != "reviewer" for handle in dispatcher.requests)


def test_parallel_exhaustion_persists_successful_sibling_before_returning():
    dispatcher = FakeDispatcher()
    dispatcher.fail_always.add("left-worker")
    ledger = MemoryLedger()

    result = WorkflowExecutor(
        _bound_workflow(),
        dispatcher,
        ledger,
        mode="B",
        objective="Deliver.",
    ).run()

    assert result.status is WorkflowExecutionStatus.HUMAN_STOP
    assert "right" in ledger.completed
    assert [route for batch in dispatcher.wait_batches for route in batch].count(
        "right-worker"
    ) == 1
    assert ("right", DispatchStatus.SUCCEEDED) in ledger.finished


def test_wait_backend_failure_terminalizes_claim_and_persists_human_stop():
    dispatcher = FakeDispatcher()
    dispatcher.wait_errors.add("planner")
    ledger = MemoryLedger()

    result = WorkflowExecutor(
        _bound_workflow(), dispatcher, ledger, mode="B", objective="Deliver."
    ).run()

    assert result.status is WorkflowExecutionStatus.HUMAN_STOP
    assert result.human_stop is not None
    assert result.human_stop.reason.value == "conflicting-evidence"
    assert ("plan", DispatchStatus.CANCELLED) in ledger.finished
    assert ledger.paused


def test_keyboard_interrupt_terminalizes_claim_then_reraises_and_can_resume():
    dispatcher = FakeDispatcher()
    dispatcher.interrupt_wait.add("planner")
    ledger = MemoryLedger()

    with pytest.raises(KeyboardInterrupt):
        WorkflowExecutor(
            _bound_workflow(), dispatcher, ledger, mode="B", objective="Deliver."
        ).run()

    assert ledger.running == set()
    assert ledger.finished == [("plan", DispatchStatus.CANCELLED)]
    resumed = WorkflowExecutor(
        _bound_workflow(), FakeDispatcher(), ledger, mode="B", objective="Deliver."
    ).run()
    assert resumed.status is WorkflowExecutionStatus.WAITING_GATE


def test_retry_launch_failure_preserves_failed_attempt_and_stops():
    dispatcher = FakeDispatcher()
    dispatcher.fail_always.add("planner")
    dispatcher.retry_errors.add("planner")
    ledger = MemoryLedger()

    result = WorkflowExecutor(
        _bound_workflow(), dispatcher, ledger, mode="B", objective="Deliver."
    ).run()

    assert result.status is WorkflowExecutionStatus.HUMAN_STOP
    assert result.human_stop is not None
    assert result.human_stop.reason.value == "retry-budget-exhausted"
    assert ledger.finished == [("plan", DispatchStatus.FAILED)]


def test_false_condition_is_frozen_and_cannot_execute_after_resume():
    workflow = _bound_workflow()
    left = workflow.definition.stage_by_id["left"]
    conditional_left = WorkflowStageDefinition(
        left.id,
        left.phase,
        left.route,
        left.depends_on,
        left.parallel_group,
        "left-surface-present",
        left.gates,
        left.retry_budget,
        left.evidence,
        left.required_capabilities,
    )
    definition = WorkflowDefinition(
        workflow.definition.schema_version,
        workflow.definition.id,
        workflow.definition.title,
        workflow.definition.description,
        workflow.definition.roles,
        workflow.definition.retry_budgets,
        workflow.definition.evidence_requirements,
        workflow.definition.findings_policy,
        workflow.definition.ordered_gates,
        workflow.definition.gates,
        tuple(
            conditional_left if stage.id == "left" else stage
            for stage in workflow.definition.stages
        ),
        workflow.definition.parallel_groups,
        workflow.definition.modes,
    )
    bound = BoundWorkflow(
        definition,
        workflow.active_gates,
        workflow.gate_stage_ids,
        workflow.gate_definition_digest,
    )
    ledger = MemoryLedger()
    first_dispatcher = FakeDispatcher()

    first = WorkflowExecutor(
        bound,
        first_dispatcher,
        ledger,
        mode="B",
        objective="Deliver.",
        conditions={"left-surface-present": False},
    ).run()
    assert first.status is WorkflowExecutionStatus.WAITING_GATE
    assert "left" in first.skipped_stages
    assert all(handle.route != "left-worker" for handle in first_dispatcher.requests)

    second_dispatcher = FakeDispatcher()
    resumed = WorkflowExecutor(
        bound,
        second_dispatcher,
        ledger,
        mode="B",
        objective="Deliver.",
    ).run()
    assert resumed.status is WorkflowExecutionStatus.WAITING_GATE
    assert all(handle.route != "left-worker" for handle in second_dispatcher.requests)

    conflicting = WorkflowExecutor(
        bound,
        FakeDispatcher(),
        ledger,
        mode="B",
        objective="Deliver.",
        conditions={"left-surface-present": True},
    ).run()
    assert conflicting.status is WorkflowExecutionStatus.HUMAN_STOP
    assert conflicting.human_stop is not None
    assert conflicting.human_stop.reason.value == "conflicting-evidence"


def test_unknown_condition_stops_before_spawning_and_owned_workspace_is_injected(
    tmp_path,
):
    workflow = _bound_workflow()
    first = workflow.definition.stages[0]
    conditional = WorkflowStageDefinition(
        first.id,
        first.phase,
        first.route,
        first.depends_on,
        first.parallel_group,
        "needs-decision",
        first.gates,
        first.retry_budget,
        first.evidence,
        first.required_capabilities,
    )
    definition = WorkflowDefinition(
        workflow.definition.schema_version,
        workflow.definition.id,
        workflow.definition.title,
        workflow.definition.description,
        workflow.definition.roles,
        workflow.definition.retry_budgets,
        workflow.definition.evidence_requirements,
        workflow.definition.findings_policy,
        workflow.definition.ordered_gates,
        workflow.definition.gates,
        (conditional,) + workflow.definition.stages[1:],
        workflow.definition.parallel_groups,
        workflow.definition.modes,
    )
    bound = BoundWorkflow(
        definition,
        workflow.active_gates,
        workflow.gate_stage_ids,
        workflow.gate_definition_digest,
    )
    dispatcher = FakeDispatcher()
    ledger = MemoryLedger()

    stopped = WorkflowExecutor(
        bound, dispatcher, ledger, mode="B", objective="Deliver."
    ).run()
    assert stopped.status is WorkflowExecutionStatus.HUMAN_STOP
    assert dispatcher.requests == {}

    owned = tmp_path / "owned-worktree"
    owned.mkdir()

    class Resolver:
        def resolve(self, stage: WorkflowStageDefinition, role: str) -> Path:
            del stage, role
            return owned

    resumed = WorkflowExecutor(
        bound,
        dispatcher,
        MemoryLedger(),
        mode="B",
        objective="Deliver.",
        conditions={"needs-decision": True},
        workspace_resolver=Resolver(),
    ).run()
    assert resumed.status is WorkflowExecutionStatus.WAITING_GATE
    assert all(
        request.workspace == str(owned) for request in dispatcher.requests.values()
    )


def test_executor_protocols_remain_provider_neutral():
    assert isinstance(FakeDispatcher(), Dispatcher)
    assert isinstance(MemoryLedger(), StageLedger)
    assert not isinstance(object(), OwnedWorkspaceResolver)


def test_managed_resolver_reuses_one_run_owned_integration_worktree(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "workflow@example.invalid"],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Workflow Test"], cwd=repo, check=True
    )
    (repo / "tracked.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True)
    resolver = ManagedWorktreeResolver(repo, "run-1")
    stages = _bound_workflow().definition.stages

    first = resolver.resolve(stages[0], "planner")
    second = resolver.resolve(stages[1], "left-worker")

    assert first == second
    assert first != repo.resolve()
    assert resolver.serializes_disjoint_writes
    records = resolver.manager.records("run-1")
    assert len(records) == 1
    assert records[0].worker_id == "managed-workflow"


def test_managed_execution_rejects_dirty_application_state(tmp_path, payload):
    repo = tmp_path / "dirty-repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "workflow@example.invalid"],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Workflow Test"], cwd=repo, check=True
    )
    tracked = repo / "app.txt"
    tracked.write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "app.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True)
    tracked.write_text("uncommitted application edit\n", encoding="utf-8")
    selection = catalog.defaults(payload)
    options = InitOptions(
        "test",
        selection,
        [],
        runtimes=["codex"],
        state_layout=StateLayout.neutral(),
        rendering_version=2,
        compatibility_catalog_versions={"codex": 1},
    )

    with pytest.raises(WorkflowValidationError, match="worktree from HEAD"):
        _assert_clean_application_state(repo, options)


def test_managed_execution_requires_provider_config_in_head_but_allows_shared_state(
    tmp_path, payload
):
    repo = tmp_path / "provider-config-repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "workflow@example.invalid"],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Workflow Test"], cwd=repo, check=True
    )
    (repo / "app.txt").write_text("base\n", encoding="utf-8")
    (repo / ".gitignore").write_text(".codex/\n", encoding="utf-8")
    subprocess.run(["git", "add", "app.txt", ".gitignore"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True)

    provider_path = ".codex/agents/developer.toml"
    provider_file = repo / provider_path
    provider_file.parent.mkdir(parents=True)
    provider_file.write_text('name = "developer"\n', encoding="utf-8")
    selection = catalog.defaults(payload)
    options = InitOptions(
        "test",
        selection,
        [
            FileRecord(
                provider_path,
                "0" * 64,
                "kit",
                provider="codex",
                component_id="agent://developer",
            )
        ],
        runtimes=["codex"],
        state_layout=StateLayout.neutral(),
        rendering_version=2,
        compatibility_catalog_versions={"codex": 1},
    )

    with pytest.raises(WorkflowValidationError, match="provider configuration"):
        _assert_clean_application_state(repo, options)

    subprocess.run(["git", "add", "-f", provider_path], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "install provider config"], cwd=repo, check=True
    )
    state_file = repo / options.state_layout.pipeline_snapshot
    state_file.parent.mkdir(parents=True)
    state_file.write_text("{}\n", encoding="utf-8")

    _assert_clean_application_state(repo, options)

    immutable_path = ".ckit/rules/mandatory-workflow.md"
    immutable_file = repo / immutable_path
    immutable_file.parent.mkdir(parents=True, exist_ok=True)
    immutable_file.write_text("managed instructions\n", encoding="utf-8")
    options.files.append(
        FileRecord(
            immutable_path,
            hashlib.sha256(immutable_file.read_bytes()).hexdigest(),
            "kit",
            provider="shared",
            component_id="rule://mandatory-workflow",
        )
    )
    with pytest.raises(WorkflowValidationError, match="provider configuration"):
        _assert_clean_application_state(repo, options)

    subprocess.run(["git", "add", immutable_path], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "commit shared provider context"],
        cwd=repo,
        check=True,
    )
    _assert_clean_application_state(repo, options)
    immutable_file.write_text("dirty managed instructions\n", encoding="utf-8")
    with pytest.raises(WorkflowValidationError, match="Dirty"):
        _assert_clean_application_state(repo, options)


def test_execution_binding_rejects_changed_selection_gate_mode_or_objective(payload):
    selection = catalog.defaults(payload)
    selection.profile = "lean"
    plan = catalog.resolve(payload, selection)
    from claude_kit.workflows import bind_workflow, load_workflow

    bound = bind_workflow(load_workflow(payload), plan)
    options = InitOptions(
        "test",
        selection,
        [],
        runtimes=["codex"],
        state_layout=StateLayout.neutral(),
        rendering_version=2,
        compatibility_catalog_versions={"codex": 1},
    )
    install = {
        "selection": selection.to_dict(),
        "runtimes": ["codex"],
        "gates": plan.gates,
        "gate_definition_digest": plan.gate_definition_digest,
    }
    run = {
        "selection_digest": _selection_digest(selection.to_dict()),
        "ordered_gates": plan.gates,
        "gate_definition_digest": plan.gate_definition_digest,
        "status": "active",
        "task": "Deliver.",
        "profile": selection.profile,
        "scope": selection.scope,
        "mode": "B",
    }
    arguments = {
        "options": options,
        "plan": plan,
        "bound": bound,
        "install_document": install,
        "run_document": run,
        "mode": "B",
        "objective": "Deliver.",
    }

    _verify_execution_binding(**arguments)
    for field, value in (
        ("selection_digest", "0" * 64),
        ("gate_definition_digest", "0" * 64),
        ("mode", "A"),
        ("task", "Different objective"),
    ):
        changed = {**run, field: value}
        with pytest.raises(WorkflowValidationError):
            _verify_execution_binding(**{**arguments, "run_document": changed})


@pytest.mark.parametrize("mode", ["A", "B", "C", "D"])
def test_real_modes_a_through_d_reach_gate_checkpoints_and_terminate(payload, mode):
    from claude_kit.workflows import bind_workflow, load_workflow

    selection = catalog.defaults(payload)
    selection.profile = "standard"
    plan = catalog.resolve(payload, selection)
    bound = bind_workflow(load_workflow(payload), plan)
    dispatcher = FakeDispatcher()
    dispatcher.available_roles = set(plan.agents) | set(plan.overlay_agents)
    ledger = MemoryLedger()
    derived = {
        "always",
        "full-sdlc-or-program",
        "fast-track-selected",
        "program-mode-selected",
        "security-gate-active",
        "acceptance-gate-active",
        "all-active-gates-closed",
        "fast-track-gates-closed",
        "all-waves-and-gates-closed",
    }
    conditions = {
        stage.condition: False
        for stage in bound.stages_for_mode(mode)
        if stage.condition not in derived
    }
    checkpoints: list[tuple[str, ...]] = []

    for _ in range(30):
        result = WorkflowExecutor(
            bound,
            dispatcher,
            ledger,
            mode=mode,
            objective="Deliver.",
            conditions=conditions,
        ).run()
        if result.status is WorkflowExecutionStatus.WAITING_GATE:
            assert result.pending_gates
            checkpoints.append(result.pending_gates)
            ledger.resolved.update(result.pending_gates)
            continue
        assert result.status is WorkflowExecutionStatus.HUMAN_STOP
        assert result.human_stop is not None
        assert result.human_stop.reason.value == "external-side-effect"
        assert result.human_stop.requested_action.startswith(
            "generic pause approval cannot resume"
        )
        break
    else:
        pytest.fail(f"mode {mode} did not terminate")

    assert checkpoints
    expected_gates = bound.gate_ids_for_mode(mode)
    assert ledger.resolved == set(expected_gates)
    assert "fast-pull-request" not in ledger.completed
    assert "pull-request" not in ledger.completed
    assert all(
        not request.objective.startswith(
            ("Stage pull-request:", "Stage fast-pull-request:")
        )
        for request in dispatcher.requests.values()
    )


@pytest.mark.parametrize("mode", ["A", "B", "C"])
def test_lean_full_modes_stop_before_dispatching_incompatible_panel(
    payload: Path, mode: str
):
    from claude_kit.workflows import bind_workflow, load_workflow

    selection = catalog.defaults(payload)
    selection.profile = "lean"
    plan = catalog.resolve(payload, selection)
    bound = bind_workflow(load_workflow(payload), plan)
    dispatcher = FakeDispatcher()
    dispatcher.available_roles = set(plan.agents) | set(plan.overlay_agents)

    result = WorkflowExecutor(
        bound,
        dispatcher,
        MemoryLedger(),
        mode=mode,
        profile="lean",
        objective="Deliver.",
    ).run()

    assert result.status is WorkflowExecutionStatus.HUMAN_STOP
    assert result.human_stop is not None
    assert result.human_stop.reason.value == "unsupported-required-capability"
    assert "distinct planning-panel reviewers" in result.human_stop.message
    assert dispatcher.requests == {}


def test_lean_mode_d_remains_executable(payload: Path):
    from claude_kit.workflows import bind_workflow, load_workflow

    selection = catalog.defaults(payload)
    selection.profile = "lean"
    plan = catalog.resolve(payload, selection)
    bound = bind_workflow(load_workflow(payload), plan)
    dispatcher = FakeDispatcher()
    dispatcher.available_roles = set(plan.agents) | set(plan.overlay_agents)
    conditions = {
        stage.condition: False
        for stage in bound.stages_for_mode("D")
        if stage.condition
        not in {"always", "fast-track-selected", "fast-track-gates-closed"}
    }

    result = WorkflowExecutor(
        bound,
        dispatcher,
        MemoryLedger(),
        mode="D",
        profile="lean",
        objective="Deliver.",
        conditions=conditions,
    ).run()

    assert result.status is WorkflowExecutionStatus.WAITING_GATE
    assert result.pending_gates == ("code-review",)


def test_fast_track_checkpoints_after_each_mode_specific_gate_owner(payload):
    from claude_kit.workflows import bind_workflow, load_workflow

    selection = catalog.defaults(payload)
    selection.profile = "standard"
    plan = catalog.resolve(payload, selection)
    bound = bind_workflow(load_workflow(payload), plan)
    dispatcher = FakeDispatcher()
    dispatcher.available_roles = set(plan.agents) | set(plan.overlay_agents)
    ledger = MemoryLedger()
    conditions = {
        stage.condition: False
        for stage in bound.stages_for_mode("D")
        if stage.condition
        not in {
            "always",
            "fast-track-selected",
            "fast-track-gates-closed",
        }
    }

    first = WorkflowExecutor(
        bound,
        dispatcher,
        ledger,
        mode="D",
        objective="Deliver.",
        conditions=conditions,
    ).run()
    assert first.status is WorkflowExecutionStatus.WAITING_GATE
    assert first.pending_gates == ("code-review",)
    assert "fast-review" in ledger.completed
    assert "fast-verify" not in ledger.completed

    ledger.resolved.add("code-review")
    second = WorkflowExecutor(
        bound,
        dispatcher,
        ledger,
        mode="D",
        objective="Deliver.",
    ).run()
    assert second.status is WorkflowExecutionStatus.WAITING_GATE
    assert second.pending_gates == ("build-green",)
    assert "fast-verify" in ledger.completed
    assert "fast-pull-request" not in ledger.completed

    ledger.resolved.add("build-green")
    final = WorkflowExecutor(
        bound,
        dispatcher,
        ledger,
        mode="D",
        objective="Deliver.",
    ).run()
    assert final.status is WorkflowExecutionStatus.HUMAN_STOP
    assert final.human_stop is not None
    assert final.human_stop.reason.value == "external-side-effect"
    assert final.human_stop.requested_action.startswith(
        "generic pause approval cannot resume"
    )
    assert "fast-pull-request" not in ledger.completed
    assert all(
        not request.objective.startswith("Stage fast-pull-request:")
        for request in dispatcher.requests.values()
    )


def test_program_mode_fails_closed_without_explicit_wave_completion(payload):
    from claude_kit.workflows import bind_workflow, load_workflow

    selection = catalog.defaults(payload)
    selection.profile = "standard"
    plan = catalog.resolve(payload, selection)
    bound = bind_workflow(load_workflow(payload), plan)
    dispatcher = FakeDispatcher()
    dispatcher.available_roles = set(plan.agents) | set(plan.overlay_agents)
    ledger = MemoryLedger()
    derived = {
        "always",
        "full-sdlc-or-program",
        "fast-track-selected",
        "program-mode-selected",
        "security-gate-active",
        "acceptance-gate-active",
        "all-active-gates-closed",
        "fast-track-gates-closed",
        "all-waves-and-gates-closed",
    }
    conditions = {
        stage.condition: False
        for stage in bound.stages_for_mode("E")
        if stage.condition not in derived
    }

    result = WorkflowExecutor(
        bound,
        dispatcher,
        ledger,
        mode="E",
        objective="Program delivery.",
        conditions=conditions,
    ).run()

    assert result.status is WorkflowExecutionStatus.HUMAN_STOP
    assert result.human_stop is not None
    assert "authoritative program-manifest execution entry point" in (
        result.human_stop.message
    )
    assert dispatcher.requests == {}
    assert ledger.claimed == []
