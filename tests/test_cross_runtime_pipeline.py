"""End-to-end proof that Claude and Codex share one provider-neutral gate ledger."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional, Sequence

import pytest
import yaml

from claude_kit import catalog
from claude_kit import pipeline as pipeline_state
from claude_kit.dispatch import (
    DispatchHandle,
    DispatchMessage,
    DispatchRequest,
    DispatchResult,
    DispatchStatus,
    WaitMode,
    WaitResult,
)
from claude_kit.models import InitOptions, InstallRequest, Runtime, StateLayout
from claude_kit.runtime_scaffold import install_runtime, transition_runtime
from claude_kit.workflow_executor import (
    ManagedWorktreeResolver,
    WorkflowExecutionStatus,
    execute_bound_workflow,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    ).stdout.strip()


def _init_git_repo(repo: Path) -> str:
    """Create the real branch/commit identity required by schema-v2 lifecycle state."""

    repo.mkdir()
    _git(repo, "init", "-b", "cross-runtime-main")
    _git(repo, "config", "user.email", "cross-runtime@example.invalid")
    _git(repo, "config", "user.name", "Cross Runtime Test")
    (repo / "tracked.txt").write_text("pipeline identity\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-m", "establish pipeline identity")
    return _git(repo, "rev-parse", "HEAD")


def _headless_cli(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run the public CLI with closed stdin, as a CI job or agent shell would."""

    environment = os.environ.copy()
    source = str(REPO_ROOT / "src")
    existing = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        source if not existing else source + os.pathsep + existing
    )
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, "-m", "claude_kit", *args],
        cwd=repo,
        env=environment,
        stdin=subprocess.DEVNULL,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _runtime_metadata(repo: Path) -> tuple[InitOptions, dict[str, Any]]:
    layout = StateLayout.neutral()
    options = InitOptions.from_dict(
        json.loads((repo / layout.manifest).read_text(encoding="utf-8"))
    )
    stack_snapshot = yaml.safe_load(
        (repo / layout.stack_snapshot).read_text(encoding="utf-8")
    )
    assert isinstance(stack_snapshot, dict)
    return options, stack_snapshot


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _managed_evidence_document(evidence_id: str) -> dict[str, Any]:
    documents: dict[str, dict[str, Any]] = {
        "scope-record": {
            "mode": "D",
            "surfaces": ["repository"],
            "constraints": [],
            "risks": [],
        },
        "command-evidence": {
            "command": "pytest -q",
            "exit-status": 0,
            "output": "passed",
        },
        "review-verdict": {
            "status": "PASS",
            "reviewer": "cross-runtime-reviewer",
            "findings": [],
            "evidence": ["tests/test_cross_runtime_pipeline.py"],
        },
        "test-report": {
            "scope": ["cross-runtime managed execution"],
            "passed": 1,
            "failed": 0,
            "skipped": 0,
            "residual-risk": [],
        },
        "closeout-record": {
            "outcome": "prepared",
            "gates": [
                {
                    "id": "build-green",
                    "status": "passed",
                    "evidence": ["tests/test_cross_runtime_pipeline.py"],
                }
            ],
            "accepted-risks": [],
            "learnings": [],
        },
    }
    return documents[evidence_id]


class _SuccessfulDispatcher:
    """Credential-free native-adapter seam with provider-accurate handles."""

    queued_spawn = True

    def __init__(self, provider: str) -> None:
        self.provider = provider
        self.counter = 0
        self.requests: dict[DispatchHandle, DispatchRequest] = {}

    def spawn(self, request: DispatchRequest) -> DispatchHandle:
        self.counter += 1
        handle = DispatchHandle(
            f"{self.provider}-{self.counter}",
            request.route,
            provider=self.provider,
            required_capabilities=request.required_capabilities,
            attested_capabilities=request.required_capabilities,
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
        return WaitResult(tuple(handles), (), False)

    def collect(self, handles: Sequence[DispatchHandle]) -> tuple[DispatchResult, ...]:
        results = []
        for handle in handles:
            request = self.requests[handle]
            documents = {}
            for reference in request.evidence:
                evidence_id = reference.uri.removeprefix("artifact://")
                if evidence_id == "closeout-record":
                    marker = (
                        "Authoritative closeout ledger (repeat gates and "
                        "accepted-risks exactly in closeout-record): "
                    )
                    assert marker in request.context
                    authoritative = json.loads(
                        request.context.split(marker, 1)[1].splitlines()[0]
                    )
                    documents[evidence_id] = {
                        "outcome": "prepared",
                        **authoritative,
                        "learnings": [],
                    }
                else:
                    documents[evidence_id] = _managed_evidence_document(evidence_id)
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
        retried = DispatchHandle(
            handle.id,
            handle.route,
            attempt=handle.attempt + 1,
            provider=handle.provider,
            required_capabilities=handle.required_capabilities,
            attested_capabilities=handle.attested_capabilities,
        )
        self.requests[retried] = self.requests[handle]
        return retried

    def cancel(self, handle: DispatchHandle, reason: str) -> None:
        del handle
        assert reason


def _record_clean_findings(target: Path) -> None:
    evidence = target / "evidence" / "managed-findings.json"
    evidence.parent.mkdir(exist_ok=True)
    evidence.write_text(
        json.dumps(
            {"critical": 0, "high": 0, "medium": 0, "low": 0, "cosmetic": 0},
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    ok, messages = pipeline_state.record_findings(
        target,
        critical=0,
        high=0,
        medium=0,
        low=0,
        cosmetic=0,
        evidence=evidence,
    )
    assert ok, "\n".join(messages)


def _close_managed_gate(target: Path, gate: str, provider: str) -> None:
    evidence = target / "evidence" / f"managed-{gate}.txt"
    evidence.write_text(f"verified after {provider} owner stage\n", encoding="utf-8")
    ok, messages = pipeline_state.close_gate(
        target,
        gate,
        evidence,
        strict=True,
    )
    assert ok, "\n".join(messages)


@pytest.mark.parametrize(
    ("initial_provider", "resuming_provider"),
    [("claude", "codex"), ("codex", "claude")],
)
def test_managed_executor_resumes_across_providers_without_replaying_stages(
    payload: Path,
    tmp_path: Path,
    initial_provider: str,
    resuming_provider: str,
) -> None:
    """Exercise the real factory/ledger while keeping host credentials out of tests."""

    target = tmp_path / f"managed-{initial_provider}-to-{resuming_provider}"
    _init_git_repo(target)
    selection = catalog.defaults(payload)
    selection.profile = "lean"
    selection.detect_commands = False
    plan = catalog.resolve(payload, selection)
    install_runtime(
        payload,
        target,
        plan,
        InstallRequest(selection=selection, runtime=Runtime.BOTH),
    )
    _git(target, "add", "-A")
    _git(target, "commit", "-m", "commit dual-provider execution controls")
    started, messages = pipeline_state.start(
        target,
        task="Cross-provider managed execution",
        mode="D",
    )
    assert started, "\n".join(messages)

    snapshot, error = pipeline_state.snapshot_document(target)
    assert error is None and snapshot is not None
    resolver = ManagedWorktreeResolver(target, str(snapshot["run_id"]))
    first_dispatcher = _SuccessfulDispatcher(initial_provider)
    first = execute_bound_workflow(
        target,
        provider=initial_provider,
        objective="Cross-provider managed execution",
        mode="D",
        conditions={},
        payload_root=payload,
        dispatcher=first_dispatcher,
        workspace_resolver=resolver,
    )

    assert first.status is WorkflowExecutionStatus.WAITING_GATE
    assert first.pending_gates == ("code-review",)
    assert {attempt.stage for attempt in first.attempts} == {
        "classify",
        "fast-implementation",
        "fast-review",
    }
    assert {attempt.handle.provider for attempt in first.attempts} == {initial_provider}
    _record_clean_findings(target)
    _close_managed_gate(target, "code-review", initial_provider)

    second_dispatcher = _SuccessfulDispatcher(resuming_provider)
    second = execute_bound_workflow(
        target,
        provider=resuming_provider,
        objective="Cross-provider managed execution",
        mode="D",
        conditions={},
        payload_root=payload,
        dispatcher=second_dispatcher,
        workspace_resolver=resolver,
    )

    assert second.status is WorkflowExecutionStatus.WAITING_GATE
    assert second.pending_gates == ("build-green",)
    assert [attempt.stage for attempt in second.attempts] == ["fast-verify"]
    assert second.attempts[0].handle.provider == resuming_provider
    _close_managed_gate(target, "build-green", resuming_provider)

    final = execute_bound_workflow(
        target,
        provider=resuming_provider,
        objective="Cross-provider managed execution",
        mode="D",
        conditions={},
        payload_root=payload,
        dispatcher=second_dispatcher,
        workspace_resolver=resolver,
    )
    assert final.status is WorkflowExecutionStatus.HUMAN_STOP
    assert final.human_stop is not None
    assert final.human_stop.reason.value == "external-side-effect"
    assert [attempt.stage for attempt in final.attempts] == [
        "fast-pull-request-prepare"
    ]
    completed, messages = pipeline_state.complete(target)
    assert not completed
    assert "external-side-effect" in "\n".join(messages)

    snapshot, error = pipeline_state.snapshot_document(target)
    assert error is None and snapshot is not None
    stage_history = snapshot["stage_history"]
    assert [record["stage"] for record in stage_history] == [
        "classify",
        "fast-implementation",
        "fast-review",
        "fast-verify",
        "fast-pull-request-prepare",
    ]
    assert [record["provider"] for record in stage_history] == [
        initial_provider,
        initial_provider,
        initial_provider,
        resuming_provider,
        resuming_provider,
    ]
    assert snapshot["status"] == "active"
    assert snapshot["human_stops"][-1]["reason"] == "external-side-effect"
    assert snapshot["managed_execution"]["ordered_gates"] == [
        "code-review",
        "build-green",
    ]
    assert len(snapshot["managed_execution"]["workflow_definition_digest"]) == 64


@pytest.mark.parametrize(
    ("initial_runtime", "resuming_runtime"),
    [("claude", "codex"), ("codex", "claude")],
)
def test_pipeline_crosses_runtime_metadata_without_splitting_ledger(
    payload: Path,
    tmp_path: Path,
    initial_runtime: str,
    resuming_runtime: str,
) -> None:
    """Start/advance on one host, transition metadata, then resume/advance on the other."""

    target = tmp_path / f"{initial_runtime}-to-{resuming_runtime}"
    commit = _init_git_repo(target)
    selection = catalog.defaults(payload)
    selection.profile = "lean"
    selection.detect_commands = False
    plan = catalog.resolve(payload, selection)
    assert plan.gates == ["code-review", "build-green"]

    install_runtime(
        payload,
        target,
        plan,
        InstallRequest(selection=selection, runtime=Runtime.parse(initial_runtime)),
    )
    initial_options, initial_stack = _runtime_metadata(target)
    assert initial_options.runtime is Runtime.parse(initial_runtime)
    assert initial_stack["runtimes"] == [initial_runtime]
    assert initial_stack["gate_definition_digest"] == plan.gate_definition_digest

    # Every lifecycle command below has stdin closed. There is no host prompt or TTY fallback.
    _headless_cli(
        target,
        "pipeline",
        "start",
        "--task",
        f"{initial_runtime}-to-{resuming_runtime} interoperability",
        "--mode",
        "B",
        ".",
    )
    claimed, claim_messages = pipeline_state.claim_stage(
        target,
        stage="classify",
        role="orchestrator",
        provider=initial_runtime,
        dispatch_id=f"{initial_runtime}-classify",
        attempt=1,
        required_capabilities=("filesystem.read", "workflow.ledger"),
        attested_capabilities=("filesystem.read", "workflow.ledger"),
    )
    assert claimed, "\n".join(claim_messages)
    finished, finish_messages = pipeline_state.finish_stage(
        target,
        stage="classify",
        dispatch_id=f"{initial_runtime}-classify",
        attempt=1,
        status="succeeded",
        output_sha256="c" * 64,
        evidence=("artifact://scope-record",),
    )
    assert finished, "\n".join(finish_messages)
    frozen_conditions, condition_error = (
        pipeline_state.bind_workflow_condition_decisions(
            target,
            {
                "backend-surface-present": True,
                "frontend-surface-present": False,
            },
        )
    )
    assert condition_error is None
    assert frozen_conditions is not None
    evidence_dir = target / "evidence"
    evidence_dir.mkdir()
    findings = evidence_dir / "findings.json"
    findings.write_text(
        json.dumps(
            {"critical": 0, "high": 0, "medium": 0, "low": 0, "cosmetic": 0},
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    _headless_cli(
        target,
        "pipeline",
        "record-findings",
        "--critical",
        "0",
        "--high",
        "0",
        "--medium",
        "0",
        "--low",
        "0",
        "--cosmetic",
        "0",
        "--evidence",
        "evidence/findings.json",
        ".",
    )
    first_evidence = evidence_dir / f"{plan.gates[0]}.txt"
    first_evidence.write_text(f"verified by {initial_runtime}\n", encoding="utf-8")
    _headless_cli(
        target,
        "pipeline",
        "close-gate",
        plan.gates[0],
        "--evidence",
        f"evidence/{first_evidence.name}",
        "--strict",
        ".",
    )

    layout = StateLayout.neutral()
    ledger = target / layout.pipeline_snapshot
    before_transition_bytes = ledger.read_bytes()
    before_transition = json.loads(before_transition_bytes)
    assert before_transition["repository_root"] == str(target.resolve())
    assert before_transition["starting_commit"] == commit
    assert before_transition["current_commit"] == commit
    assert before_transition["gate_definition_digest"] == plan.gate_definition_digest
    assert before_transition["stage_history"][0]["provider"] == initial_runtime
    assert before_transition["stage_history"][0]["status"] == "succeeded"
    assert before_transition["ordered_gates"] == plan.gates
    assert [entry["gate"] for entry in before_transition["gate_history"]] == [
        plan.gates[0]
    ]
    assert before_transition["gate_history"][0]["evidence_sha256"] == _sha256(
        first_evidence
    )

    transition_runtime(
        payload,
        target,
        plan,
        InstallRequest(selection=selection, runtime=Runtime.parse(resuming_runtime)),
        confirm_removal=True,
    )
    resumed_options, resumed_stack = _runtime_metadata(target)
    assert resumed_options.runtime is Runtime.parse(resuming_runtime)
    assert resumed_stack["runtimes"] == [resuming_runtime]
    assert resumed_stack["gate_definition_digest"] == plan.gate_definition_digest
    assert (target / ".claude").is_dir() is (resuming_runtime == "claude")
    assert (target / ".codex").is_dir() is (resuming_runtime == "codex")
    assert ledger.read_bytes() == before_transition_bytes

    resumed_conditions, condition_error = pipeline_state.workflow_condition_decisions(
        target
    )
    assert condition_error is None and resumed_conditions == frozen_conditions
    changed_conditions, condition_error = (
        pipeline_state.bind_workflow_condition_decisions(
            target,
            {
                "backend-surface-present": True,
                "frontend-surface-present": True,
            },
        )
    )
    assert changed_conditions is None
    assert condition_error is not None and "differ" in condition_error
    assert ledger.read_bytes() == before_transition_bytes

    rerun, rerun_messages = pipeline_state.claim_stage(
        target,
        stage="classify",
        role="orchestrator",
        provider=resuming_runtime,
        dispatch_id=f"{resuming_runtime}-classify",
        attempt=1,
        required_capabilities=("filesystem.read",),
        attested_capabilities=("filesystem.read",),
    )
    assert not rerun
    assert "cannot run twice" in rerun_messages[0]
    assert ledger.read_bytes() == before_transition_bytes

    resumed = _headless_cli(target, "pipeline", "resume", ".")
    assert "resumed" in resumed.stdout
    assert ledger.read_bytes() == before_transition_bytes
    status = _headless_cli(target, "pipeline", "status", "--json", ".")
    status_document = json.loads(status.stdout)
    assert status_document["ok"] is True
    assert status_document["snapshot"] == before_transition
    validation = _headless_cli(
        target, "pipeline", "validate", "--strict", "--json", "."
    )
    assert json.loads(validation.stdout)["snapshot"] == before_transition

    second_evidence = evidence_dir / f"{plan.gates[1]}.txt"
    second_evidence.write_text(f"verified by {resuming_runtime}\n", encoding="utf-8")
    _headless_cli(
        target,
        "pipeline",
        "close-gate",
        plan.gates[1],
        "--evidence",
        f"evidence/{second_evidence.name}",
        "--strict",
        ".",
    )
    after_resume = json.loads(ledger.read_text(encoding="utf-8"))
    assert after_resume["run_id"] == before_transition["run_id"]
    assert (
        after_resume["gate_definition_digest"]
        == before_transition["gate_definition_digest"]
    )
    assert after_resume["findings_evidence"] == before_transition["findings_evidence"]
    assert after_resume["gate_history"][0] == before_transition["gate_history"][0]
    assert [entry["gate"] for entry in after_resume["gate_history"]] == plan.gates
    assert [entry["evidence_sha256"] for entry in after_resume["gate_history"]] == [
        _sha256(first_evidence),
        _sha256(second_evidence),
    ]
    assert after_resume["gate_evidence"] == {
        plan.gates[0]: f"evidence/{first_evidence.name}",
        plan.gates[1]: f"evidence/{second_evidence.name}",
    }

    ledgers = sorted(
        path.relative_to(target).as_posix()
        for path in target.rglob("pipeline-snapshot.json")
    )
    assert ledgers == [layout.pipeline_snapshot]
    assert not (target / ".claude/state/pipeline-snapshot.json").exists()
    assert not (target / ".codex/state/pipeline-snapshot.json").exists()
