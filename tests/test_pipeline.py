"""pipeline: validate/status/close-gate/abort operate on the snapshot state files, no SDLC run."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import threading
import time
from contextlib import ExitStack, contextmanager
from itertools import product
from pathlib import Path

import pytest
import yaml

from claude_kit import catalog, pipeline, schemas
from claude_kit.models import InstallRequest, Runtime
from claude_kit.runtime_scaffold import install_runtime
from claude_kit.secure_fs import ProjectFS
from claude_kit.state import detect_state_layout
from claude_kit.worktrees import WorktreeManager
from tests._helpers import install


def _init_git_repo(target: Path) -> str:
    """Give lifecycle tests a real branch/commit identity without committing the payload."""
    subprocess.run(
        ["git", "init", "-b", "audit-main"], cwd=target, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.email", "audit@example.invalid"],
        cwd=target,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Pipeline Audit"], cwd=target, check=True
    )
    marker = target / ".pipeline-audit-root"
    marker.write_text("root\n", encoding="utf-8")
    # Managed worktrees are created from HEAD and must contain the complete immutable
    # provider projection. Mutable pipeline state is written only after this fixture commit.
    subprocess.run(["git", "add", "-A"], cwd=target, check=True)
    subprocess.run(
        ["git", "commit", "-m", "test root"],
        cwd=target,
        check=True,
        capture_output=True,
    )
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=target,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _install_with_gate_metadata(payload: Path, target: Path, **overrides):
    """Install and ensure the intended post-hardening snapshot shape during TDD."""
    plan = install(payload, target, **overrides)
    path = target / ".claude" / "config" / "stack-catalog.snapshot.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["gate_definitions"] = {
        gate: definition.to_dict() for gate, definition in plan.gate_definitions.items()
    }
    data["gate_definition_digest"] = plan.gate_definition_digest
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return plan


def _record_findings(target: Path, **overrides) -> Path:
    counts = _findings(**overrides)
    evidence = target / "findings-report.json"
    evidence.write_text(json.dumps(counts, sort_keys=True), encoding="utf-8")
    ok, msgs = pipeline.record_findings(target, evidence=evidence, **counts)
    assert ok, "\n".join(msgs)
    return evidence


def _start_v2(
    payload: Path,
    target: Path,
    *,
    record_clean: bool = True,
    mode: str = "B",
    **overrides,
):
    _install_with_gate_metadata(payload, target, **overrides)
    commit = _init_git_repo(target)
    ok, msgs = pipeline.start(target, task="test run", mode=mode)
    assert ok, "\n".join(msgs)
    if record_clean:
        _record_findings(target)
    return commit


def _managed_workspace(target: Path) -> tuple[dict[str, str], WorktreeManager]:
    snapshot, error = pipeline.snapshot_document(target)
    assert error is None and snapshot is not None
    manager = WorktreeManager(target)
    record = manager.create(str(snapshot["run_id"]), "managed-workflow")
    return (
        {
            "worker_id": record.worker_id,
            "target_path": record.target_path,
            "base_commit": record.base_commit,
        },
        manager,
    )


def _bind_managed_run(target: Path, *, mode: str = "B") -> tuple[dict, WorktreeManager]:
    workflow = pipeline._current_workflow_definition()
    snapshot = _read_snap(target)
    gates = tuple(snapshot["ordered_gates"])
    _stages, _dependencies, _requirements, _routes, owners = (
        pipeline._managed_active_graph(target, mode, gates)
    )
    workspace, manager = _managed_workspace(target)
    managed, error = pipeline.bind_managed_execution(
        target,
        workflow_id=workflow.id,
        workflow_schema_version=workflow.schema_version,
        workflow_definition_digest=pipeline._current_workflow_identity()[2],
        mode=mode,
        ordered_gates=gates,
        gate_definition_digest=snapshot["gate_definition_digest"],
        gate_owner_stages=owners,
        workspace=workspace,
    )
    assert error is None and managed is not None
    return managed, manager


def _managed_evidence_document(evidence_id: str, *, mode: str = "B") -> dict:
    documents = {
        "scope-record": {
            "mode": mode,
            "surfaces": ["repository"],
            "constraints": [],
            "risks": [],
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
        "review-verdict": {
            "status": "PASS",
            "reviewer": "test-reviewer",
            "findings": [],
            "evidence": ["tests/test_pipeline.py"],
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
                    "evidence": ["tests/test_pipeline.py"],
                }
            ],
            "accepted-risks": [],
            "learnings": [],
        },
    }
    return documents.get(evidence_id, {"path": f"artifacts/{evidence_id}.json"})


def _managed_stage_result(
    target: Path,
    snapshot: dict,
    *,
    stage: str,
    dispatch_id: str,
    attempt: int,
    evidence_documents: dict[str, dict] | None = None,
    require_pass: bool = True,
) -> tuple[str, tuple[str, ...], tuple[dict, ...]]:
    managed = snapshot["managed_execution"]
    evidence_ids = tuple(managed["active_stage_evidence"][stage])
    output = json.dumps(
        {
            "evidence": {
                evidence_id: (
                    evidence_documents[evidence_id]
                    if evidence_documents is not None
                    and evidence_id in evidence_documents
                    else _managed_evidence_document(
                        evidence_id, mode=str(managed["mode"])
                    )
                )
                for evidence_id in evidence_ids
            }
        },
        sort_keys=True,
    )
    records, error = pipeline.materialize_managed_stage_evidence(
        target,
        stage=stage,
        dispatch_id=dispatch_id,
        dispatch_attempt=attempt,
        output=output,
        require_pass=require_pass,
    )
    assert error is None and records is not None
    references = tuple(f"artifact://{evidence_id}" for evidence_id in evidence_ids)
    return output, references, records


def _write_managed_terminal_artifact(
    target: Path,
    snapshot: dict,
    *,
    stage: str,
    dispatch_id: str,
    dispatch_attempt: int,
    status: str,
    output: str | None,
    error: str | None,
    evidence: tuple[str, ...],
    evidence_records: tuple[dict, ...],
    workspace_checkpoint: dict,
) -> tuple[str, str]:
    current, current_error = pipeline.snapshot_document(target)
    assert current_error is None and current is not None
    record = next(
        item
        for item in current["stage_history"]
        if item["stage"] == stage
        and item["dispatch_id"] == dispatch_id
        and item["dispatch_attempt"] == dispatch_attempt
        and item["status"] == "running"
    )
    document = {
        "schema_version": 1,
        "run_id": snapshot["run_id"],
        "stage": stage,
        "ledger_attempt": record["attempt"],
        "provider": record["provider"],
        "route": record["role"],
        "dispatch_id": dispatch_id,
        "dispatch_attempt": dispatch_attempt,
        "status": status,
        "output": output,
        "error": error,
        "evidence": list(evidence),
        "evidence_records": list(evidence_records),
        "workspace_checkpoint": workspace_checkpoint,
    }
    template = pipeline._managed_dispatch_artifact_relative(
        str(snapshot["run_id"]),
        stage,
        int(record["attempt"]),
        "{sha256}",
        layout=detect_state_layout(target),
    )
    return pipeline._write_private_content_addressed_json(
        ProjectFS(target), template, document
    )


def _finish_managed_stage(
    target: Path,
    manager: WorktreeManager,
    *,
    stage: str,
    provider: str = "claude",
    evidence_documents: dict[str, dict] | None = None,
) -> None:
    snapshot = _read_snap(target)
    managed = snapshot["managed_execution"]
    completed = {
        record["stage"]
        for record in snapshot.get("stage_history", [])
        if record.get("status") == "succeeded"
    }
    skipped = {record["stage"] for record in snapshot.get("skipped_stage_history", [])}
    active = set(managed["active_stages"])
    for dependency in managed["active_stage_dependencies"][stage]:
        if dependency in active and dependency not in completed | skipped:
            _finish_managed_stage(target, manager, stage=dependency, provider=provider)
    snapshot = _read_snap(target)
    dispatch_id = f"{provider}-{stage}"
    managed = snapshot["managed_execution"]
    role = managed["active_stage_routes"][stage]["role"]
    capabilities = tuple(managed["active_stage_requirements"][stage])
    claimed, messages = pipeline.claim_stage(
        target,
        stage=stage,
        role=role,
        provider=provider,
        dispatch_id=dispatch_id,
        attempt=1,
        required_capabilities=capabilities,
        attested_capabilities=capabilities,
    )
    assert claimed, "\n".join(messages)
    output, references, evidence_records = _managed_stage_result(
        target,
        snapshot,
        stage=stage,
        dispatch_id=dispatch_id,
        attempt=1,
        evidence_documents=evidence_documents,
    )
    checkpoint = manager.checkpoint(str(snapshot["run_id"]), "managed-workflow")
    relative, artifact_sha = _write_managed_terminal_artifact(
        target,
        snapshot,
        stage=stage,
        dispatch_id=dispatch_id,
        dispatch_attempt=1,
        status="succeeded",
        output=output,
        error=None,
        evidence=references,
        evidence_records=evidence_records,
        workspace_checkpoint=checkpoint.to_dict(),
    )
    finished, messages = pipeline.finish_stage(
        target,
        stage=stage,
        dispatch_id=dispatch_id,
        attempt=1,
        status="succeeded",
        output_sha256=hashlib.sha256(output.encode()).hexdigest(),
        output_path=relative,
        output_artifact_sha256=artifact_sha,
        workspace_checkpoint=checkpoint.to_dict(),
        evidence=references,
        evidence_records=evidence_records,
    )
    assert finished, "\n".join(messages)


def _findings(**overrides):
    findings = {"critical": 0, "high": 0, "medium": 0, "low": 0, "cosmetic": 0}
    findings.update(overrides)
    return findings


def test_portable_human_stop_blocks_resume_and_gate_mutations_until_approved(
    payload: Path, tmp_path: Path
) -> None:
    _start_v2(payload, tmp_path)
    ok, messages = pipeline.pause_for_human(
        tmp_path,
        reason="external-side-effect",
        message="Publishing would affect an external registry.",
        requested_action="Approve or reject publishing this exact artifact.",
    )
    assert ok, "\n".join(messages)
    snapshot, error = pipeline.snapshot_document(tmp_path)
    assert error is None and snapshot is not None
    stop = snapshot["human_stops"][0]
    assert stop["status"] == "pending"

    assert not pipeline.resume(tmp_path)[0]
    assert "paused for human input" in pipeline.resume(tmp_path)[1][0]
    blocked, blocked_messages = pipeline.record_findings(
        tmp_path,
        evidence=tmp_path / "findings-report.json",
        **_findings(),
    )
    assert not blocked
    assert "resolve the pause" in blocked_messages[0]
    first_gate = snapshot["ordered_gates"][0]
    gate_evidence = tmp_path / "gate.md"
    gate_evidence.write_text("not yet approved\n", encoding="utf-8")
    assert not pipeline.close_gate(tmp_path, first_gate, gate_evidence)[0]

    approval = tmp_path / "human-approval.json"
    approval.write_text(
        json.dumps({"approver": "owner", "decision": "approved"}),
        encoding="utf-8",
    )
    resolved, resolved_messages = pipeline.resolve_human_stop(
        tmp_path,
        stop["stop_id"],
        decision="approved",
        resolved_by="project-owner",
        note="Approved only for the recorded artifact and destination.",
        evidence=approval,
    )
    assert resolved, "\n".join(resolved_messages)
    assert pipeline.resume(tmp_path)[0]
    valid, messages = pipeline.validate(tmp_path, strict=True)
    assert valid, "\n".join(messages)

    updated, error = pipeline.snapshot_document(tmp_path)
    assert error is None and updated is not None
    record = updated["human_stops"][0]
    assert record["status"] == "approved"
    assert record["evidence_path"] == approval.name
    assert (
        record["evidence_sha256"] == hashlib.sha256(approval.read_bytes()).hexdigest()
    )


def test_managed_human_stop_cannot_be_self_approved_without_one_shot_scope(
    payload: Path, tmp_path: Path
) -> None:
    _start_v2(payload, tmp_path)
    workflow = pipeline._current_workflow_definition()
    snapshot = _read_snap(tmp_path)
    gates = tuple(snapshot["ordered_gates"])
    workspace, _manager = _managed_workspace(tmp_path)
    managed, error = pipeline.bind_managed_execution(
        tmp_path,
        workflow_id=workflow.id,
        workflow_schema_version=workflow.schema_version,
        workflow_definition_digest=pipeline._current_workflow_identity()[2],
        mode="B",
        ordered_gates=gates,
        gate_definition_digest=snapshot["gate_definition_digest"],
        gate_owner_stages={gate: workflow.gates[gate].stage for gate in gates},
        workspace=workspace,
    )
    assert error is None and managed is not None
    _record_findings(tmp_path)
    paused, messages = pipeline.pause_for_human(
        tmp_path,
        reason="external-side-effect",
        message="The selected native role cannot safely publish this artifact.",
        requested_action="Approve publishing the exact staged artifact.",
    )
    assert paused, "\n".join(messages)
    current, error = pipeline.snapshot_document(tmp_path)
    assert error is None and current is not None
    stop_id = current["human_stops"][0]["stop_id"]
    asserted_approval = tmp_path / "self-asserted-managed-approval.json"
    asserted_approval.write_text(
        json.dumps(
            {
                "resolver": "same-host-agent",
                "claim": "project-local evidence should be enough",
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    approved, messages = pipeline.resolve_human_stop(
        tmp_path,
        stop_id,
        decision="approved",
        resolved_by="same-host-agent",
        note="Approve and continue.",
        evidence=asserted_approval,
    )
    assert not approved
    # A same-account HMAC file or a caller-selected terminal stage is not an authorization:
    # a future implementation needs an external/asymmetric verifier plus an origin-bound,
    # one-shot handoff that only the exact retry can consume.
    rendered = "\n".join(messages)
    assert "one exact originating stage" in rendered
    assert "outside the managed worker trust boundary" in rendered
    unchanged, error = pipeline.snapshot_document(tmp_path)
    assert error is None and unchanged is not None
    assert unchanged["human_stops"][0]["status"] == "pending"

    rejected, messages = pipeline.resolve_human_stop(
        tmp_path,
        stop_id,
        decision="rejected",
        resolved_by="project-owner",
        note="Do not publish; return to a non-mutating plan.",
        evidence=asserted_approval,
    )
    assert rejected, "\n".join(messages)
    final, error = pipeline.snapshot_document(tmp_path)
    assert error is None and final is not None
    assert final["human_stops"][0]["status"] == "rejected"
    assert "re-plan" in final["next"]
    valid, messages = pipeline.validate(tmp_path, strict=True)
    assert valid, "\n".join(messages)


@pytest.mark.parametrize("reason", sorted(pipeline.HUMAN_STOP_REASONS))
def test_every_required_human_stop_reason_is_persistable(
    payload: Path, tmp_path: Path, reason: str
) -> None:
    _start_v2(payload, tmp_path, record_clean=False)
    assert pipeline.pause_for_human(
        tmp_path,
        reason=reason,
        message=f"stop for {reason}",
        requested_action="provide a bounded decision",
    )[0]
    snapshot, error = pipeline.snapshot_document(tmp_path)
    assert error is None and snapshot is not None
    assert snapshot["human_stops"][0]["reason"] == reason
    assert pipeline.abort(tmp_path)[0], "abort must remain available while paused"


def test_human_stop_reject_and_evidence_tamper_are_auditable(
    payload: Path, tmp_path: Path
) -> None:
    _start_v2(payload, tmp_path, record_clean=False)
    assert pipeline.pause_for_human(
        tmp_path,
        reason="scope-expansion",
        message="The requested change exceeds approved scope.",
        requested_action="Approve expansion or require re-planning.",
    )[0]
    snapshot, _ = pipeline.snapshot_document(tmp_path)
    assert snapshot is not None
    stop_id = snapshot["human_stops"][0]["stop_id"]
    assert pipeline.resolve_human_stop(
        tmp_path,
        stop_id,
        decision="rejected",
        resolved_by="owner",
        note="Keep the original boundary.",
    )[0]
    resumed, messages = pipeline.resume(tmp_path)
    assert resumed, "\n".join(messages)
    updated, _ = pipeline.snapshot_document(tmp_path)
    assert updated is not None
    assert "re-plan after rejected" in updated["next"]

    assert pipeline.pause_for_human(
        tmp_path,
        reason="irreversible-operation",
        message="A destructive migration is proposed.",
        requested_action="Approve only after recovery evidence is verified.",
    )[0]
    pending, _ = pipeline.snapshot_document(tmp_path)
    assert pending is not None
    approval = tmp_path / "restore-point.txt"
    approval.write_text("verified restore point\n", encoding="utf-8")
    assert pipeline.resolve_human_stop(
        tmp_path,
        pending["human_stops"][-1]["stop_id"],
        decision="approved",
        resolved_by="owner",
        note="Recovery reference verified.",
        evidence=approval,
    )[0]
    approval.write_text("tampered\n", encoding="utf-8")
    ok, validation = pipeline.validate(tmp_path, strict=True)
    assert not ok
    assert any("human-stop evidence hash mismatch" in line for line in validation)


def test_pipeline_resume_and_abort_share_run_owned_worktree_lifecycle(
    payload: Path, tmp_path: Path
) -> None:
    from claude_kit.worktrees import WorktreeManager, WorktreeStatus

    _start_v2(payload, tmp_path, record_clean=False)
    snapshot, error = pipeline.snapshot_document(tmp_path)
    assert error is None and snapshot is not None
    run_id = snapshot["run_id"]
    manager = WorktreeManager(tmp_path)
    record = manager.create(run_id, "implementation")

    resumed, messages = pipeline.resume(tmp_path)
    assert resumed, "\n".join(messages)
    assert any("verified 1 run-owned worktree" in line for line in messages)

    aborted, messages = pipeline.abort(tmp_path)
    assert aborted, "\n".join(messages)
    assert any("preserved 1 run-owned worktree" in line for line in messages)
    preserved = manager.records(run_id)[0]
    assert preserved.status is WorktreeStatus.ABORTED
    assert (tmp_path / record.target_path).resolve().is_dir()
    manager.cleanup(run_id, "implementation")


def _write_snapshot(target, **fields):
    if fields.get("schema_version") == 2:
        if not (target / ".git").is_dir():
            _init_git_repo(target)
        identity = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=target,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=target,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        gates = pipeline.installed_gates(target)
        anchor = fields.get("last_gate_passed")
        anchor_index = gates.index(anchor) if anchor in gates else -1
        starting_gate = (
            gates[anchor_index + 1]
            if gates and anchor_index + 1 < len(gates)
            else (gates[-1] if gates else "unknown")
        )
        fields.setdefault("run_id", "00000000-0000-4000-8000-000000000001")
        fields.setdefault("repository_root", str(target.resolve()))
        fields.setdefault("branch", branch)
        fields.setdefault("starting_commit", identity)
        fields.setdefault("current_commit", identity)
        fields.setdefault("kit_version", "test")
        fields.setdefault("claude_code_version", None)
        fields.setdefault("ordered_gates", gates)
        fields.setdefault(
            "gate_definition_digest",
            pipeline.installed_gate_definition_digest(target),
        )
        fields.setdefault("start_type", "adopted")
        fields.setdefault(
            "adoption",
            {
                "starting_gate": starting_gate,
                "historical_gates": gates[: anchor_index + 1],
                "reason": "test fixture explicitly adopts pre-ledger work",
                "adopted_by": "pytest",
            },
        )
        fields.setdefault("created_at", "2026-08-20T00:00:00+00:00")
        fields.setdefault("status", "active")
        fields.setdefault("gate_evidence", {})
        fields.setdefault("accepted_risks", [])
        fields.setdefault("gate_history", [])
        counts = fields.get("open_findings")
        if (
            "findings_evidence" not in fields
            and isinstance(counts, dict)
            and set(counts) == pipeline.FINDING_KEYS
            and all(
                isinstance(value, int) and not isinstance(value, bool) and value >= 0
                for value in counts.values()
            )
        ):
            evidence = target / "findings-fixture.json"
            evidence.write_text(json.dumps(counts, sort_keys=True), encoding="utf-8")
            evidence_sha = hashlib.sha256(evidence.read_bytes()).hexdigest()
            fields["findings_evidence"] = {
                "counts": dict(counts),
                "evidence_path": evidence.name,
                "evidence_sha256": evidence_sha,
                "finding_set_digest": pipeline._finding_set_digest(
                    counts,
                    evidence_sha256=evidence_sha,
                    repository_commit=identity,
                ),
                "repository_commit": identity,
                "recorded_at": "2026-08-20T00:00:00+00:00",
            }
    snap = target / ".claude" / "state" / "pipeline-snapshot.json"
    snap.parent.mkdir(parents=True, exist_ok=True)
    snap.write_text(json.dumps(fields), encoding="utf-8")
    return snap


def _coherent():
    return dict(
        schema_version=2,
        task="demo run",
        profile="standard",
        scope="team",
        mode="B",
        stage="build-green",
        lanes={"backend": "in-progress", "frontend": "passed"},
        last_gate_passed="code-review",
        open_findings=_findings(),
        next="run tests",
    )


def _legacy_coherent():
    snap = _coherent()
    snap.pop("schema_version")
    snap["schema"] = 1
    return snap


def test_validate_absent_snapshot_is_ok(tmp_path, payload):
    install(payload, tmp_path)
    ok, msgs = pipeline.validate(tmp_path)
    assert ok
    assert any("no run in progress" in m for m in msgs)


def test_validate_coherent_snapshot(tmp_path, payload):
    install(payload, tmp_path)
    _write_snapshot(tmp_path, **_coherent())
    ok, msgs = pipeline.validate(tmp_path)
    assert ok, "\n".join(msgs)
    assert any("coherent" in m for m in msgs)


def test_validate_rejects_bad_enums(tmp_path, payload):
    install(payload, tmp_path)
    bad = _coherent()
    bad.update(profile="bogus", scope="nope", mode="Z", lanes={"x": "weird"})
    _write_snapshot(tmp_path, **bad)
    ok, msgs = pipeline.validate(tmp_path)
    assert not ok
    joined = "\n".join(msgs)
    assert "profile 'bogus'" in joined
    assert "scope 'nope'" in joined
    assert "mode 'Z'" in joined
    assert "invalid state 'weird'" in joined


def test_validate_rejects_unknown_gate(tmp_path, payload):
    install(payload, tmp_path)  # standard profile defines a known gate set
    snap = _legacy_coherent()
    snap["last_gate_passed"] = "totally-made-up"
    _write_snapshot(tmp_path, **snap)
    ok, msgs = pipeline.validate(tmp_path)
    assert not ok
    assert any("last_gate_passed 'totally-made-up'" in m for m in msgs)


def test_validate_rejects_noninteger_findings(tmp_path, payload):
    install(payload, tmp_path)
    snap = _coherent()
    snap["open_findings"] = _findings(high="lots")
    _write_snapshot(tmp_path, **snap)
    ok, msgs = pipeline.validate(tmp_path)
    assert not ok
    assert any("must be a non-negative integer" in m for m in msgs)


@pytest.mark.parametrize(
    ("findings", "message"),
    [
        ({"critical": 0, "high": 0, "medium": 0, "low": 0}, "missing severities"),
        (_findings(high=-1), "non-negative integer"),
        (_findings(high=True), "non-negative integer"),
    ],
)
def test_validate_v2_findings_are_complete_nonnegative_integer_counts(
    tmp_path, payload, findings, message
):
    install(payload, tmp_path)
    snap = _coherent()
    snap["open_findings"] = findings
    _write_snapshot(tmp_path, **snap)
    ok, msgs = pipeline.validate(tmp_path)
    assert not ok
    assert any(message in item for item in msgs), msgs


@pytest.mark.parametrize("field", ["profile", "scope", "mode", "gate_history"])
def test_validate_requires_runtime_fields_required_by_the_v2_schema(
    tmp_path, payload, field
):
    install(payload, tmp_path)
    _write_snapshot(tmp_path, **_coherent())
    document = _read_snap(tmp_path)
    document.pop(field)
    (tmp_path / pipeline.SNAPSHOT_REL).write_text(
        json.dumps(document), encoding="utf-8"
    )

    ok, messages = pipeline.validate(tmp_path, strict=True)

    assert not ok
    assert any(field in message for message in messages), messages


def test_validate_rejects_unparseable_snapshot(tmp_path, payload):
    install(payload, tmp_path)
    snap = tmp_path / ".claude" / "state" / "pipeline-snapshot.json"
    snap.parent.mkdir(parents=True, exist_ok=True)
    snap.write_text("{ not json", encoding="utf-8")
    ok, msgs = pipeline.validate(tmp_path)
    assert not ok
    assert any("invalid JSON" in m for m in msgs)


def test_status_renders_fields(tmp_path, payload):
    install(payload, tmp_path)
    _write_snapshot(tmp_path, **_coherent())
    ok, msgs = pipeline.status(tmp_path)
    assert ok
    blob = "\n".join(msgs)
    assert (
        "demo run" in blob
        and "stage:   build-green" in blob
        and "backend: in-progress" in blob
    )


def test_close_gate_records_evidence_and_gate(tmp_path, payload):
    install(payload, tmp_path)
    _write_snapshot(tmp_path, **_coherent())
    evidence = tmp_path / "coverage.txt"
    evidence.write_text("100%", encoding="utf-8")
    ok, msgs = pipeline.close_gate(tmp_path, "build-green", evidence)
    assert ok, "\n".join(msgs)
    snap = json.loads(
        (tmp_path / ".claude" / "state" / "pipeline-snapshot.json").read_text(
            encoding="utf-8"
        )
    )
    assert snap["last_gate_passed"] == "build-green"
    assert snap["gate_evidence"]["build-green"].endswith("coverage.txt")


def test_close_gate_requires_existing_evidence(tmp_path, payload):
    install(payload, tmp_path)
    _write_snapshot(tmp_path, **_coherent())
    ok, msgs = pipeline.close_gate(tmp_path, "build-green", tmp_path / "missing.txt")
    assert not ok
    assert any("evidence file not found" in m for m in msgs)


def test_close_gate_rejects_unknown_gate(tmp_path, payload):
    install(payload, tmp_path)
    evidence = tmp_path / "e.txt"
    evidence.write_text("x", encoding="utf-8")
    ok, msgs = pipeline.close_gate(tmp_path, "not-a-gate", evidence)
    assert not ok
    assert any("is not a gate of this profile" in m for m in msgs)


def test_close_gate_never_implicitly_seeds_snapshot(tmp_path, payload):
    install(payload, tmp_path)  # writes the install snapshot (profile=standard)
    evidence = tmp_path / "e.txt"
    evidence.write_text("x", encoding="utf-8")
    assert not (tmp_path / ".claude" / "state" / "pipeline-snapshot.json").is_file()
    ok, msgs = pipeline.close_gate(tmp_path, "code-review", evidence)
    assert not ok
    assert any("start or adopt" in message for message in msgs)
    assert not (tmp_path / ".claude" / "state" / "pipeline-snapshot.json").exists()


def test_abort_marks_run_aborted(tmp_path, payload):
    install(payload, tmp_path)
    _write_snapshot(tmp_path, **_coherent())
    ok, msgs = pipeline.abort(tmp_path)
    assert ok
    snap = json.loads(
        (tmp_path / ".claude" / "state" / "pipeline-snapshot.json").read_text(
            encoding="utf-8"
        )
    )
    assert snap["stage"] == "aborted"


def test_abort_without_snapshot_is_noop(tmp_path, payload):
    install(payload, tmp_path)
    ok, msgs = pipeline.abort(tmp_path)
    assert ok
    assert any("nothing to abort" in m for m in msgs)


def test_validate_rejects_nondict_lanes_and_findings(tmp_path, payload):
    install(payload, tmp_path)
    snap = _coherent()
    snap["lanes"] = ["backend", "frontend"]  # should be an object
    snap["open_findings"] = [1, 2]  # should be an object
    _write_snapshot(tmp_path, **snap)
    ok, msgs = pipeline.validate(tmp_path)
    assert not ok
    joined = "\n".join(msgs)
    assert "lanes must be an object" in joined
    assert "open_findings must be an object" in joined


def test_validate_rejects_nonobject_snapshot_root(tmp_path, payload):
    install(payload, tmp_path)
    snap = tmp_path / ".claude" / "state" / "pipeline-snapshot.json"
    snap.parent.mkdir(parents=True, exist_ok=True)
    snap.write_text('["not", "an", "object"]', encoding="utf-8")
    ok, msgs = pipeline.validate(tmp_path)
    assert not ok
    assert any("not a JSON object" in m for m in msgs)


def test_close_gate_refuses_blocking_findings(tmp_path, payload):
    install(payload, tmp_path)
    snap = _coherent()
    snap["open_findings"] = _findings(critical=1, medium=2)
    _write_snapshot(tmp_path, **snap)
    evidence = tmp_path / "e.txt"
    evidence.write_text("x", encoding="utf-8")
    ok, msgs = pipeline.close_gate(tmp_path, "code-review", evidence)
    assert not ok
    joined = "\n".join(msgs)
    assert "cannot close" in joined and "critical=1" in joined and "medium=2" in joined
    # the gate must NOT have been recorded
    written = json.loads(
        (tmp_path / ".claude" / "state" / "pipeline-snapshot.json").read_text(
            encoding="utf-8"
        )
    )
    assert (
        written.get("last_gate_passed") == "code-review"
    )  # the pre-existing value, unchanged
    assert "build-green" not in (written.get("gate_evidence") or {})


def test_close_gate_allows_low_findings(tmp_path, payload):
    install(payload, tmp_path)
    snap = _coherent()
    snap["open_findings"] = _findings(low=5)
    _write_snapshot(tmp_path, **snap)
    evidence = tmp_path / "e.txt"
    evidence.write_text("x", encoding="utf-8")
    ok, msgs = pipeline.close_gate(tmp_path, "build-green", evidence)
    assert ok, "\n".join(msgs)  # low findings do not block


def test_close_gate_force_cannot_waive_high_even_without_reason(tmp_path, payload):
    install(payload, tmp_path)
    snap = _coherent()
    snap["open_findings"] = _findings(high=3)
    _write_snapshot(tmp_path, **snap)
    evidence = tmp_path / "e.txt"
    evidence.write_text("x", encoding="utf-8")
    ok, msgs = pipeline.close_gate(tmp_path, "build-green", evidence, force=True)
    assert not ok
    assert any("High" in m and "never waivable" in m for m in msgs)


def test_close_gate_force_with_reason_still_cannot_waive_high(tmp_path, payload):
    install(payload, tmp_path)
    snap = _coherent()
    snap["open_findings"] = _findings(high=3)
    _write_snapshot(tmp_path, **snap)
    evidence = tmp_path / "e.txt"
    evidence.write_text("x", encoding="utf-8")
    ok, msgs = pipeline.close_gate(
        tmp_path,
        "build-green",
        evidence,
        force=True,
        override_reason="hotfix: blocked finding tracked in TICKET-1",
    )
    assert not ok
    assert any("High" in m and "never waivable" in m for m in msgs)
    written = json.loads(
        (tmp_path / ".claude" / "state" / "pipeline-snapshot.json").read_text(
            encoding="utf-8"
        )
    )
    assert written["last_gate_passed"] == "code-review"
    assert "gate_overrides" not in written


def test_validate_fails_when_evidence_file_gone(tmp_path, payload):
    install(payload, tmp_path)
    snap = _coherent()
    snap["gate_evidence"] = {"code-review": str(tmp_path / "deleted-evidence.txt")}
    _write_snapshot(tmp_path, **snap)
    ok, msgs = pipeline.validate(tmp_path)
    assert not ok
    assert any("evidence file is missing" in m for m in msgs)


def test_validate_passes_when_evidence_file_present(tmp_path, payload):
    install(payload, tmp_path)
    evidence = tmp_path / "review.md"
    evidence.write_text("approved", encoding="utf-8")
    snap = _coherent()
    snap["gate_evidence"] = {"code-review": str(evidence)}
    _write_snapshot(tmp_path, **snap)
    ok, msgs = pipeline.validate(tmp_path)
    assert ok, "\n".join(msgs)


def test_validate_surfaces_forced_gate(tmp_path, payload):
    install(payload, tmp_path)
    evidence = tmp_path / "review.md"
    evidence.write_text("approved", encoding="utf-8")
    snap = _coherent()
    snap["gate_evidence"] = {"code-review": str(evidence)}
    snap["gate_overrides"] = {"code-review": "bypassed for hotfix"}
    _write_snapshot(tmp_path, **snap)
    ok, msgs = pipeline.validate(tmp_path)
    assert ok, "\n".join(msgs)
    assert any("force-closed" in m for m in msgs)


def test_close_gate_fails_closed_when_install_snapshot_missing(tmp_path):
    # No install() → no .claude/config/stack-catalog.snapshot.yaml to confirm the gate against.
    (tmp_path / ".claude" / "state").mkdir(parents=True, exist_ok=True)
    evidence = tmp_path / "e.txt"
    evidence.write_text("x", encoding="utf-8")
    ok, msgs = pipeline.close_gate(tmp_path, "some-gate", evidence)
    assert not ok
    assert any("not a gate of this profile" in m for m in msgs)


# --- Mode E (wave/program runs) ---------------------------------------------------------------


def test_validate_accepts_mode_e_snapshot(tmp_path, payload):
    install(payload, tmp_path)
    snap = _coherent()
    snap["mode"] = "E"
    snap["lanes"] = {"wave-0-audit": "passed", "wave-1-mechanical": "in-progress"}
    _write_snapshot(tmp_path, **snap)
    ok, msgs = pipeline.validate(tmp_path)
    assert ok, "\n".join(msgs)


def test_status_renders_mode_e(tmp_path, payload):
    install(payload, tmp_path)
    snap = _coherent()
    snap["mode"] = "E"
    _write_snapshot(tmp_path, **snap)
    ok, msgs = pipeline.status(tmp_path)
    assert ok
    assert any("mode: E" in m for m in msgs)


def test_modes_drift_guard_against_continuity_rule(payload):
    """The mode enum lives in pipeline.MODES; rules/continuity.md documents it. Keep them equal."""
    import re

    doc = (payload / "rules" / "continuity.md").read_text(encoding="utf-8")
    match = re.search(r'"mode":\s*"([A-Z\s|]+)"', doc)
    assert match, "rules/continuity.md no longer documents the mode enum"
    documented = {tok.strip() for tok in match.group(1).split("|")}
    assert documented == set(pipeline.MODES), (
        f"mode enum drift: rules/continuity.md documents {sorted(documented)}, "
        f"pipeline.MODES is {sorted(pipeline.MODES)}"
    )


# --- Gate ledger: order enforcement -----------------------------------------------------------
# Standard-profile execution order: spec-complete, em-approved, code-review, build-green,
# contract-clear (MR2), test-coverage, security-clear (pinned in test_catalog.py's
# test_gates_resolve_in_execution_order). _coherent() anchors at code-review → next is build-green.


def _read_snap(target):
    return json.loads(
        (target / ".claude" / "state" / "pipeline-snapshot.json").read_text(
            encoding="utf-8"
        )
    )


def test_close_gate_rejects_out_of_order(tmp_path, payload):
    install(payload, tmp_path)
    _write_snapshot(tmp_path, **_coherent())
    evidence = tmp_path / "e.txt"
    evidence.write_text("x", encoding="utf-8")
    ok, msgs = pipeline.close_gate(tmp_path, "security-clear", evidence)
    assert not ok
    joined = "\n".join(msgs)
    assert "out of order" in joined and "'build-green'" in joined
    assert _read_snap(tmp_path)["last_gate_passed"] == "code-review"  # unchanged


def test_close_gate_rejects_regression_behind_position(tmp_path, payload):
    install(payload, tmp_path)
    _write_snapshot(tmp_path, **_coherent())
    evidence = tmp_path / "e.txt"
    evidence.write_text("x", encoding="utf-8")
    ok, msgs = pipeline.close_gate(tmp_path, "spec-complete", evidence)
    assert not ok
    assert any("recorded or superseded" in m for m in msgs)


def test_close_gate_force_never_overrides_order(tmp_path, payload):
    install(payload, tmp_path)
    _write_snapshot(tmp_path, **_coherent())
    evidence = tmp_path / "e.txt"
    evidence.write_text("x", encoding="utf-8")
    ok, msgs = pipeline.close_gate(
        tmp_path,
        "security-clear",
        evidence,
        force=True,
        override_reason="hotfix lane: security scan ran ahead of build",
    )
    assert not ok
    assert any("cannot record a normal gate transition" in message for message in msgs)
    snap = _read_snap(tmp_path)
    assert snap["gate_history"] == []


def test_close_gate_cannot_bootstrap_at_an_arbitrary_gate(tmp_path, payload):
    install(payload, tmp_path)
    evidence = tmp_path / "e.txt"
    evidence.write_text("x", encoding="utf-8")
    ok, msgs = pipeline.close_gate(tmp_path, "build-green", evidence)
    assert not ok
    assert any("start or adopt" in m for m in msgs)
    assert not (tmp_path / ".claude/state/pipeline-snapshot.json").exists()


def test_close_gate_appends_ledger_entry_with_hash(tmp_path, payload):
    import hashlib

    install(payload, tmp_path)
    _write_snapshot(tmp_path, **_coherent())
    evidence = tmp_path / "coverage.txt"
    evidence.write_text("94% lines", encoding="utf-8")
    ok, msgs = pipeline.close_gate(tmp_path, "build-green", evidence)
    assert ok, "\n".join(msgs)
    entry = _read_snap(tmp_path)["gate_history"][-1]
    assert entry["gate"] == "build-green"
    assert entry["status"] == "passed"
    assert entry["verification"] == "agent"
    assert entry["evidence_sha256"] == hashlib.sha256(b"94% lines").hexdigest()
    assert entry["recorded_at"]  # UTC ISO timestamp present


# --- Gate ledger: skip-gate --------------------------------------------------------------------


def test_not_applicable_requires_reason(tmp_path, payload):
    install(payload, tmp_path)
    _write_snapshot(tmp_path, **_coherent())
    ev = tmp_path / "condition.txt"
    ev.write_text("no API", encoding="utf-8")
    ok, msgs = pipeline.not_applicable(
        tmp_path,
        "contract-clear",
        condition="no-api-contract-surface",
        reason="  ",
        evidence=ev,
    )
    assert not ok
    assert any("reason" in m for m in msgs)


def test_not_applicable_records_and_advances_position(tmp_path, payload):
    install(payload, tmp_path)
    _write_snapshot(tmp_path, **_coherent())
    ev = tmp_path / "e.txt"
    ev.write_text("x", encoding="utf-8")
    assert pipeline.close_gate(tmp_path, "build-green", ev)[0]
    ok, msgs = pipeline.not_applicable(
        tmp_path,
        "contract-clear",
        condition="no-api-contract-surface",
        reason="no public API contract",
        evidence=ev,
    )
    assert ok, "\n".join(msgs)
    entry = _read_snap(tmp_path)["gate_history"][-1]
    assert entry["status"] == "not-applicable"
    assert entry["condition_evidence_sha256"]
    ok, msgs = pipeline.close_gate(tmp_path, "test-coverage", ev)
    assert ok, "\n".join(msgs)


def test_not_applicable_rejects_out_of_order(tmp_path, payload):
    install(payload, tmp_path)
    _write_snapshot(tmp_path, **_coherent())
    ev = tmp_path / "condition.txt"
    ev.write_text("no API", encoding="utf-8")
    ok, msgs = pipeline.not_applicable(
        tmp_path,
        "contract-clear",
        condition="no-api-contract-surface",
        reason="not applicable",
        evidence=ev,
    )
    assert not ok
    assert any("out of order" in m for m in msgs)


# --- Gate ledger: validate re-verifies every entry ----------------------------------------------


def test_validate_fails_on_evidence_hash_mismatch(tmp_path, payload):
    install(payload, tmp_path)
    _write_snapshot(tmp_path, **_coherent())
    evidence = tmp_path / "review.md"
    evidence.write_text("approved", encoding="utf-8")
    ok, msgs = pipeline.close_gate(tmp_path, "build-green", evidence)
    assert ok, "\n".join(msgs)
    evidence.write_text("approved (edited after the gate closed)", encoding="utf-8")
    ok, msgs = pipeline.validate(tmp_path)
    assert not ok
    assert any("hash mismatch" in m for m in msgs)


def test_validate_fails_on_disordered_history(tmp_path, payload):
    install(payload, tmp_path)
    evidence = tmp_path / "e.txt"
    evidence.write_text("x", encoding="utf-8")
    snap = _coherent()
    snap["gate_history"] = [
        {"gate": "build-green", "status": "passed", "evidence_path": str(evidence)},
        {"gate": "code-review", "status": "passed", "evidence_path": str(evidence)},
    ]
    _write_snapshot(tmp_path, **snap)
    ok, msgs = pipeline.validate(tmp_path)
    assert not ok
    assert any("out of the installed gate order" in m for m in msgs)


def test_validate_checks_historical_entries_not_just_latest(tmp_path, payload):
    install(payload, tmp_path)
    evidence = tmp_path / "e.txt"
    evidence.write_text("x", encoding="utf-8")
    snap = _coherent()
    snap["gate_history"] = [
        {
            "gate": "code-review",
            "status": "passed",
            "evidence_path": str(tmp_path / "gone.txt"),  # historical evidence deleted
        },
        {"gate": "build-green", "status": "passed", "evidence_path": str(evidence)},
    ]
    snap["last_gate_passed"] = "build-green"
    _write_snapshot(tmp_path, **snap)
    ok, msgs = pipeline.validate(tmp_path)
    assert not ok
    assert any("gate_history[0]" in m and "missing" in m for m in msgs)


# --- Strict mode fails closed --------------------------------------------------------------------


def test_close_gate_strict_fails_without_install_snapshot(tmp_path):
    (tmp_path / ".claude" / "state").mkdir(parents=True, exist_ok=True)
    evidence = tmp_path / "e.txt"
    evidence.write_text("x", encoding="utf-8")
    ok, msgs = pipeline.close_gate(tmp_path, "some-gate", evidence, strict=True)
    assert not ok
    assert any("not a gate of this profile" in m for m in msgs)


def test_validate_strict_fails_without_install_snapshot(tmp_path):
    _write_snapshot(tmp_path, **_legacy_coherent())
    ok, msgs = pipeline.validate(tmp_path, strict=True)
    assert not ok
    assert any("--strict" in m for m in msgs)


# --- Atomic writes + locking ---------------------------------------------------------------------


def test_leftover_tmp_file_is_ignored(tmp_path, payload):
    install(payload, tmp_path)
    _write_snapshot(tmp_path, **_coherent())
    state = tmp_path / ".claude" / "state"
    (state / "pipeline-snapshot.json.tmp12345").write_text(
        "{ crashed", encoding="utf-8"
    )
    ok, msgs = pipeline.validate(tmp_path)
    assert ok, "\n".join(
        msgs
    )  # a crashed writer's temp file never corrupts the snapshot


def test_stale_lock_fails_cleanly(tmp_path, payload, monkeypatch):
    monkeypatch.setattr(pipeline, "_LOCK_TIMEOUT_S", 0.2)
    install(payload, tmp_path)
    _write_snapshot(tmp_path, **_coherent())
    state = tmp_path / ".claude" / "state"
    (state / "pipeline-snapshot.json.lock").write_text("", encoding="utf-8")
    evidence = tmp_path / "e.txt"
    evidence.write_text("x", encoding="utf-8")
    ok, msgs = pipeline.close_gate(tmp_path, "build-green", evidence)
    assert not ok
    assert any("could not lock" in m for m in msgs)
    assert _read_snap(tmp_path)["last_gate_passed"] == "code-review"  # nothing written


# --- adversarial-review regressions (0.76.0 pre-merge hardening) ----------------------------


def test_force_rerecord_is_not_a_valid_v2_transition(tmp_path, payload):
    install(payload, tmp_path)
    _write_snapshot(tmp_path, **_coherent())
    ev = tmp_path / "e.txt"
    ev.write_text("x", encoding="utf-8")
    assert pipeline.close_gate(tmp_path, "build-green", ev)[0]
    ok, msgs = pipeline.close_gate(
        tmp_path,
        "build-green",
        ev,
        force=True,
        override_reason="re-ran the build after a flaky failure",
    )
    assert not ok
    assert any("cannot record a normal gate transition" in message for message in msgs)
    ok, msgs = pipeline.validate(tmp_path)
    assert ok, "\n".join(msgs)
    assert len(_read_snap(tmp_path)["gate_history"]) == 1


def test_force_rerecord_without_reason_fails_on_order_path(tmp_path, payload):
    """--force without --override-reason is refused on the order path too (not only findings)."""
    install(payload, tmp_path)
    _write_snapshot(tmp_path, **_coherent())
    ev = tmp_path / "e.txt"
    ev.write_text("x", encoding="utf-8")
    assert pipeline.close_gate(tmp_path, "build-green", ev)[0]
    ok, msgs = pipeline.close_gate(tmp_path, "build-green", ev, force=True)
    assert not ok
    assert any("cannot record a normal gate transition" in m for m in msgs)


def test_position_never_rewinds_because_forced_backfill_is_refused(tmp_path, payload):
    install(payload, tmp_path)
    _write_snapshot(tmp_path, **_coherent())  # position: code-review
    ev = tmp_path / "e.txt"
    ev.write_text("x", encoding="utf-8")
    assert pipeline.close_gate(tmp_path, "build-green", ev)[0]
    ok, msgs = pipeline.close_gate(
        tmp_path,
        "spec-complete",
        ev,
        force=True,
        override_reason="backfilling the spec record for audit completeness",
    )
    assert not ok
    assert _read_snap(tmp_path)["last_gate_passed"] == "build-green"
    # Next legal gate is still contract-clear — the refused backfill changed no state.
    ok, msgs = pipeline.close_gate(tmp_path, "test-coverage", ev)
    assert not ok and any("contract-clear" in m for m in msgs)
    assert pipeline.close_gate(tmp_path, "contract-clear", ev)[0]


def test_close_and_skip_refuse_on_aborted_run(tmp_path, payload):
    """Abort is terminal for the ledger — no gate may be recorded onto an aborted run."""
    install(payload, tmp_path)
    _write_snapshot(tmp_path, **_coherent())
    assert pipeline.abort(tmp_path)[0]
    ev = tmp_path / "e.txt"
    ev.write_text("x", encoding="utf-8")
    ok, msgs = pipeline.close_gate(tmp_path, "build-green", ev)
    assert not ok and any("aborted" in m for m in msgs)
    ok, msgs = pipeline.not_applicable(
        tmp_path,
        "contract-clear",
        condition="no-api-contract-surface",
        reason="does not apply",
        evidence=ev,
    )
    assert not ok and any("aborted" in m for m in msgs)


def test_relative_evidence_resolves_against_project_root_not_cwd(
    tmp_path, payload, monkeypatch
):
    """A relative --evidence path means project-relative — the caller's CWD is irrelevant,
    and the stored path stays project-relative so the ledger is portable."""
    install(payload, tmp_path)
    _write_snapshot(tmp_path, **_coherent())
    (tmp_path / "artifacts").mkdir()
    (tmp_path / "artifacts" / "build.log").write_text("ok", encoding="utf-8")
    elsewhere = tmp_path / "unrelated-cwd"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    ok, msgs = pipeline.close_gate(tmp_path, "build-green", "artifacts/build.log")
    assert ok, "\n".join(msgs)
    entry = _read_snap(tmp_path)["gate_history"][-1]
    assert entry["evidence_path"] == "artifacts/build.log"
    ok, msgs = pipeline.validate(tmp_path)  # still from the foreign CWD
    assert ok, "\n".join(msgs)


def test_v2_repository_identity_refuses_a_relocated_checkout(tmp_path, payload):
    proj = tmp_path / "proj"
    proj.mkdir()
    install(payload, proj)
    _write_snapshot(proj, **_coherent())
    (proj / "cov.txt").write_text("100%", encoding="utf-8")
    assert pipeline.close_gate(proj, "build-green", proj / "cov.txt")[0]
    moved = tmp_path / "renamed-checkout"
    proj.rename(moved)
    ok, msgs = pipeline.validate(moved)
    assert not ok
    assert any("different repository root" in message for message in msgs)


def test_evidence_outside_project_recorded_absolute_with_warning(tmp_path, payload):
    """Out-of-tree evidence still closes the gate, but the non-portability is said out loud."""
    install(payload, tmp_path)
    _write_snapshot(tmp_path, **_coherent())
    outside = tmp_path.parent / f"{tmp_path.name}-outside-evidence.txt"
    outside.write_text("x", encoding="utf-8")
    ok, msgs = pipeline.close_gate(tmp_path, "build-green", outside)
    assert ok, "\n".join(msgs)
    assert any("outside the project" in m for m in msgs)
    entry = _read_snap(tmp_path)["gate_history"][-1]
    assert Path(entry["evidence_path"]).is_absolute()


def test_concurrent_closes_one_wins_one_refused(tmp_path, payload):
    """The lock spans the whole read-modify-write: two racers on the same gate cannot both
    win, and the loser gets a clean refusal instead of silently overwriting the winner."""
    install(payload, tmp_path)
    _write_snapshot(tmp_path, **_coherent())
    ev = tmp_path / "e.txt"
    ev.write_text("x", encoding="utf-8")
    results = []
    barrier = threading.Barrier(2)

    def racer():
        barrier.wait()
        results.append(pipeline.close_gate(tmp_path, "build-green", ev))

    threads = [threading.Thread(target=racer) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wins = [msgs for ok, msgs in results if ok]
    losses = [msgs for ok, msgs in results if not ok]
    assert len(wins) == 1 and len(losses) == 1, results
    assert any("recorded or superseded" in m for m in losses[0])
    assert (
        len(_read_snap(tmp_path)["gate_history"]) == 1
    )  # no lost update, no double entry


def test_validate_warns_on_foreign_profile_history_entry(tmp_path, payload):
    """A history gate from another profile's set is reviewable drift, not corruption — the
    snapshot may have been recorded before a profile change."""
    install(payload, tmp_path)  # standard: pipeline-green is enterprise-only
    snap = _legacy_coherent()
    snap["gate_history"] = [
        {
            "gate": "pipeline-green",
            "status": "passed",
            "evidence_path": "e.txt",
            "evidence_sha256": None,
            "verification": "agent",
            "recorded_at": "2026-08-01T00:00:00+00:00",
            "override": None,
        }
    ]
    _write_snapshot(tmp_path, **snap)
    (tmp_path / "e.txt").write_text("x", encoding="utf-8")
    ok, msgs = pipeline.validate(tmp_path)
    assert ok, "\n".join(msgs)
    assert any("not a gate of the installed profile" in m for m in msgs)


def test_old_lock_is_not_stolen_from_a_potential_long_running_writer(
    tmp_path, payload, monkeypatch
):
    """Age alone is not ownership proof; even an old lock fails closed."""
    install(payload, tmp_path)
    _write_snapshot(tmp_path, **_coherent())
    monkeypatch.setattr(pipeline, "_LOCK_TIMEOUT_S", 0.02)
    lock = tmp_path / ".claude" / "state" / "pipeline-snapshot.json.lock"
    lock.write_text("99999", encoding="utf-8")
    old = time.time() - 120  # well past _LOCK_STALE_S
    os.utime(lock, (old, old))
    ev = tmp_path / "e.txt"
    ev.write_text("x", encoding="utf-8")
    ok, msgs = pipeline.close_gate(tmp_path, "build-green", ev)
    assert not ok
    assert any("verify that no writer owns" in m for m in msgs)
    assert lock.read_text(encoding="utf-8") == "99999"


# --- Unreadable install snapshot: lenient by default, fail-closed under --strict ----------------
# The gate list comes from the install snapshot. When it cannot be read, the validator must say so
# rather than silently reporting "coherent" against an empty gate set — that is the difference
# between "order was checked and held" and "order could not be checked at all".


def _install_snapshot(target):
    return target / ".claude" / "config" / "stack-catalog.snapshot.yaml"


def test_validate_warns_when_install_snapshot_is_unparseable(tmp_path, payload):
    install(payload, tmp_path)
    _install_snapshot(tmp_path).write_text("gates: [a, b\n", encoding="utf-8")
    _write_snapshot(tmp_path, **_legacy_coherent())
    ok, msgs = pipeline.validate(tmp_path)
    assert ok, "\n".join(msgs)
    assert any(m.startswith("WARN") and "invalid YAML" in m for m in msgs)


def test_validate_strict_fails_on_unparseable_install_snapshot(tmp_path, payload):
    install(payload, tmp_path)
    _install_snapshot(tmp_path).write_text("gates: [a, b\n", encoding="utf-8")
    _write_snapshot(tmp_path, **_legacy_coherent())
    ok, msgs = pipeline.validate(tmp_path, strict=True)
    assert not ok
    assert any("invalid YAML" in m and "--strict" in m for m in msgs)


def test_validate_warns_when_install_snapshot_is_not_a_mapping(tmp_path, payload):
    """A YAML document that parses but isn't a mapping has no gate list to offer."""
    install(payload, tmp_path)
    _install_snapshot(tmp_path).write_text("- gates\n- selection\n", encoding="utf-8")
    _write_snapshot(tmp_path, **_legacy_coherent())
    ok, msgs = pipeline.validate(tmp_path)
    assert ok, "\n".join(msgs)
    assert any("not a YAML mapping" in m for m in msgs)


def test_close_gate_refuses_unreadable_install_snapshot_under_strict(tmp_path, payload):
    install(payload, tmp_path)
    _install_snapshot(tmp_path).write_text("gates: [a, b\n", encoding="utf-8")
    ev = tmp_path / "e.txt"
    ev.write_text("x", encoding="utf-8")
    ok, msgs = pipeline.close_gate(tmp_path, "build-green", ev, strict=True)
    assert not ok
    assert any("install snapshot is invalid YAML" in m for m in msgs)
    assert not (tmp_path / ".claude" / "state" / "pipeline-snapshot.json").exists()


def test_close_gate_fails_closed_on_unreadable_install_snapshot(tmp_path, payload):
    install(payload, tmp_path)
    _install_snapshot(tmp_path).write_text("gates: [a, b\n", encoding="utf-8")
    ev = tmp_path / "e.txt"
    ev.write_text("x", encoding="utf-8")
    ok, msgs = pipeline.close_gate(tmp_path, "build-green", ev)
    assert not ok
    assert any("install snapshot is invalid YAML" in m for m in msgs)
    assert not (tmp_path / ".claude/state/pipeline-snapshot.json").exists()


# --- Snapshot field validation: each malformed field is reported, not ignored -------------------


def test_validate_warns_on_unexpected_schema(tmp_path, payload):
    install(payload, tmp_path)
    snap = _legacy_coherent()
    snap["schema"] = 2
    _write_snapshot(tmp_path, **snap)
    ok, msgs = pipeline.validate(tmp_path)
    assert ok, "\n".join(msgs)
    assert any("unsupported future pipeline snapshot schema" in m for m in msgs)


def test_validate_accepts_minimal_snapshot_but_flags_thin_resume_context(
    tmp_path, payload
):
    """No lanes, no findings, no gate — legal, but the resume context is called out as weak."""
    install(payload, tmp_path)
    _write_snapshot(tmp_path, schema=1, profile="standard")
    ok, msgs = pipeline.validate(tmp_path)
    assert ok, "\n".join(msgs)
    for field in ("task", "stage", "next"):
        assert any(f"no {field!r}" in m for m in msgs), field


def test_validate_recognizes_cosmetic_finding_severity(tmp_path, payload):
    install(payload, tmp_path)
    snap = _coherent()
    snap["open_findings"] = _findings(cosmetic=2)
    _write_snapshot(tmp_path, **snap)
    ok, msgs = pipeline.validate(tmp_path)
    assert ok, "\n".join(msgs)
    assert not any("unknown severity 'cosmetic'" in m for m in msgs)


def test_validate_rejects_nondict_gate_overrides(tmp_path, payload):
    install(payload, tmp_path)
    snap = _coherent()
    snap["gate_overrides"] = ["code-review"]
    _write_snapshot(tmp_path, **snap)
    ok, msgs = pipeline.validate(tmp_path)
    assert not ok
    assert any("gate_overrides must be an object" in m for m in msgs)


def test_validate_warns_when_last_gate_has_no_recorded_evidence_path(tmp_path, payload):
    """A partial gate_evidence map that omits the passed gate is a gap worth surfacing."""
    install(payload, tmp_path)
    snap = _coherent()
    snap["gate_evidence"] = {"spec-complete": "docs/spec.md"}
    _write_snapshot(tmp_path, **snap)
    ok, msgs = pipeline.validate(tmp_path)
    assert ok, "\n".join(msgs)
    assert any("has no recorded gate_evidence path" in m for m in msgs)


# --- Ledger entry validation --------------------------------------------------------------------


def test_validate_rejects_nonlist_gate_history(tmp_path, payload):
    install(payload, tmp_path)
    snap = _coherent()
    snap["gate_history"] = {"code-review": "passed"}
    _write_snapshot(tmp_path, **snap)
    ok, msgs = pipeline.validate(tmp_path)
    assert not ok
    assert any("gate_history must be an array" in m for m in msgs)


def test_validate_rejects_non_object_ledger_entries(tmp_path, payload):
    install(payload, tmp_path)
    snap = _coherent()
    snap["gate_history"] = ["code-review"]
    _write_snapshot(tmp_path, **snap)
    ok, msgs = pipeline.validate(tmp_path)
    assert not ok
    assert any("contains non-object entries" in m for m in msgs)


def test_validate_rejects_ledger_entry_without_a_gate_name(tmp_path, payload):
    install(payload, tmp_path)
    snap = _coherent()
    snap["gate_history"] = [{"status": "passed", "evidence_path": "e.txt"}]
    _write_snapshot(tmp_path, **snap)
    ok, msgs = pipeline.validate(tmp_path)
    assert not ok
    assert any("has no gate name" in m for m in msgs)


def test_validate_rejects_ledger_entry_with_unknown_status(tmp_path, payload):
    install(payload, tmp_path)
    ev = tmp_path / "e.txt"
    ev.write_text("x", encoding="utf-8")
    snap = _coherent()
    snap["gate_history"] = [
        {"gate": "code-review", "status": "probably", "evidence_path": "e.txt"}
    ]
    _write_snapshot(tmp_path, **snap)
    ok, msgs = pipeline.validate(tmp_path)
    assert not ok
    assert any("status 'probably' is not one of" in m for m in msgs)


def test_validate_warns_on_unknown_verification_level(tmp_path, payload):
    """An unrecognised verification level must not be read as a stronger claim than it is."""
    install(payload, tmp_path)
    ev = tmp_path / "e.txt"
    ev.write_text("x", encoding="utf-8")
    snap = _legacy_coherent()
    snap["last_gate_passed"] = None
    snap["gate_history"] = [
        {
            "gate": "code-review",
            "status": "passed",
            "evidence_path": "e.txt",
            "verification": "vibes",
        }
    ]
    _write_snapshot(tmp_path, **snap)
    ok, msgs = pipeline.validate(tmp_path)
    assert ok, "\n".join(msgs)
    assert any("verification 'vibes' is not one of" in m for m in msgs)


def test_validate_rejects_passed_ledger_entry_without_evidence(tmp_path, payload):
    install(payload, tmp_path)
    snap = _coherent()
    snap["gate_history"] = [{"gate": "code-review", "status": "passed"}]
    _write_snapshot(tmp_path, **snap)
    ok, msgs = pipeline.validate(tmp_path)
    assert not ok
    assert any("has no evidence_path" in m for m in msgs)


def test_validate_warns_on_skip_without_a_reason_and_accepts_one_with(
    tmp_path, payload
):
    """A skip carries no evidence, so its reason is the only record of why the gate was bypassed."""
    install(payload, tmp_path)
    snap = _legacy_coherent()
    snap["last_gate_passed"] = "spec-complete"
    snap["gate_history"] = [
        {"gate": "spec-complete", "status": "skipped"},
        {"gate": "em-approved", "status": "skipped", "reason": "solo project, no EM"},
    ]
    _write_snapshot(tmp_path, **snap)
    ok, msgs = pipeline.validate(tmp_path)
    assert ok, "\n".join(msgs)
    assert any("skipped without a reason" in m for m in msgs)
    assert sum("skipped without a reason" in m for m in msgs) == 1


def test_validate_checks_ledger_entries_without_an_installed_gate_list(tmp_path):
    """With no install snapshot there is no order to check, but entries are still verified."""
    ev = tmp_path / "e.txt"
    ev.write_text("x", encoding="utf-8")
    _write_snapshot(
        tmp_path,
        schema=1,
        task="t",
        stage="build",
        next="n",
        gate_history=[
            {"gate": "code-review", "status": "passed", "evidence_path": "e.txt"}
        ],
    )
    ok, msgs = pipeline.validate(tmp_path)
    assert ok, "\n".join(msgs)
    assert any("no evidence_sha256" in m for m in msgs)


# --- status() rendering ---------------------------------------------------------------------


def test_status_fails_on_unparseable_snapshot(tmp_path, payload):
    install(payload, tmp_path)
    snap_path = tmp_path / ".claude" / "state" / "pipeline-snapshot.json"
    snap_path.parent.mkdir(parents=True, exist_ok=True)
    snap_path.write_text("{not json", encoding="utf-8")
    ok, msgs = pipeline.status(tmp_path)
    assert not ok
    assert any("invalid JSON" in m for m in msgs)


def test_status_renders_ledger_detail_and_omits_empty_sections(tmp_path, payload):
    """Each optional ledger annotation appears only when present; empty sections stay silent."""
    install(payload, tmp_path)
    _write_snapshot(
        tmp_path,
        schema=1,
        task="demo",
        stage="build",
        next="run tests",
        gate_history=[
            {"gate": "spec-complete", "status": "passed"},
            {"gate": "em-approved", "status": "passed", "verification": "agent"},
            {"gate": "code-review", "status": "overridden", "override": "hotfix"},
            {"gate": "build-green", "status": "skipped", "reason": "no build step"},
        ],
    )
    ok, msgs = pipeline.status(tmp_path)
    assert ok
    joined = "\n".join(msgs)
    assert "gate history:" in joined
    assert "- spec-complete: passed" in joined
    assert "verification=agent" in joined
    assert "override='hotfix'" in joined
    assert "reason='no build step'" in joined
    assert "lanes:" not in joined
    assert "open findings:" not in joined


# --- Read-modify-write failure paths ------------------------------------------------------------


def _corrupt_snapshot(target):
    path = target / ".claude" / "state" / "pipeline-snapshot.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    return path


def test_close_gate_refuses_to_overwrite_an_unparseable_snapshot(tmp_path, payload):
    """A corrupt snapshot must be reported, never silently replaced with a fresh one."""
    install(payload, tmp_path)
    path = _corrupt_snapshot(tmp_path)
    ev = tmp_path / "e.txt"
    ev.write_text("x", encoding="utf-8")
    ok, msgs = pipeline.close_gate(tmp_path, "spec-complete", ev)
    assert not ok
    assert any("invalid JSON" in m for m in msgs)
    assert path.read_text(encoding="utf-8") == "{not json"


def test_skip_gate_refuses_to_overwrite_an_unparseable_snapshot(tmp_path, payload):
    install(payload, tmp_path)
    path = _corrupt_snapshot(tmp_path)
    ev = tmp_path / "e.txt"
    ev.write_text("x", encoding="utf-8")
    ok, msgs = pipeline.skip_gate(
        tmp_path,
        "contract-clear",
        "not applicable",
        condition="no-api-contract-surface",
        evidence=ev,
    )
    assert not ok
    assert any("invalid JSON" in m for m in msgs)
    assert path.read_text(encoding="utf-8") == "{not json"


def test_abort_refuses_to_overwrite_an_unparseable_snapshot(tmp_path, payload):
    install(payload, tmp_path)
    path = _corrupt_snapshot(tmp_path)
    ok, msgs = pipeline.abort(tmp_path)
    assert not ok
    assert any("invalid JSON" in m for m in msgs)
    assert path.read_text(encoding="utf-8") == "{not json"


def test_abort_is_a_noop_when_the_snapshot_vanishes_mid_operation(
    tmp_path, payload, monkeypatch
):
    """Models the race where another process deletes the snapshot between the check and the read."""
    install(payload, tmp_path)
    _write_snapshot(tmp_path, **_coherent())
    monkeypatch.setattr(pipeline, "_load_snapshot", lambda target: (None, None))
    ok, msgs = pipeline.abort(tmp_path)
    assert ok
    assert any("nothing to abort" in m for m in msgs)


def test_refused_force_preserves_existing_override_metadata(tmp_path, payload):
    install(payload, tmp_path)
    snap = _coherent()
    snap["gate_overrides"] = {"spec-complete": "adopted mid-flight"}
    _write_snapshot(tmp_path, **snap)
    ev = tmp_path / "e.txt"
    ev.write_text("x", encoding="utf-8")
    ok, msgs = pipeline.close_gate(
        tmp_path,
        "security-clear",
        ev,
        force=True,
        override_reason="scanner ran ahead of build in the hotfix lane",
    )
    assert not ok
    overrides = _read_snap(tmp_path)["gate_overrides"]
    assert overrides["spec-complete"] == "adopted mid-flight"
    assert "security-clear" not in overrides


# --- skip_gate guard rails ------------------------------------------------------------------


def test_skip_gate_refuses_without_install_snapshot_under_strict(tmp_path):
    (tmp_path / ".claude" / "state").mkdir(parents=True, exist_ok=True)
    ok, msgs = pipeline.skip_gate(tmp_path, "build-green", "no build step", strict=True)
    assert not ok
    assert any("legacy skip-gate is no longer" in m for m in msgs)


def test_skip_gate_rejects_a_gate_outside_the_profile(tmp_path, payload):
    install(payload, tmp_path)
    ev = tmp_path / "e.txt"
    ev.write_text("x", encoding="utf-8")
    ok, msgs = pipeline.skip_gate(
        tmp_path,
        "not-a-gate",
        "does not apply",
        condition="nothing-here",
        evidence=ev,
    )
    assert not ok
    assert any("is not a gate of this profile" in m for m in msgs)


def test_not_applicable_refuses_to_repair_a_non_list_gate_history(tmp_path, payload):
    install(payload, tmp_path)
    snap = _coherent()
    snap["gate_history"] = "not-a-list"
    _write_snapshot(tmp_path, **snap)
    ev = tmp_path / "e.txt"
    ev.write_text("x", encoding="utf-8")
    ok, msgs = pipeline.not_applicable(
        tmp_path,
        "contract-clear",
        condition="no-api-contract-surface",
        reason="no API",
        evidence=ev,
    )
    assert not ok
    assert any("gate_history must be an array" in message for message in msgs)
    assert _read_snap(tmp_path)["gate_history"] == "not-a-list"


# --- Lock contention ---------------------------------------------------------------------------


def _hold_lock(target):
    lock = (
        target / ".claude" / "state" / "pipeline-snapshot.json.lock"
    )  # fresh mtime → live holder
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("99999", encoding="utf-8")
    return lock


def test_skip_gate_reports_lock_contention(tmp_path, payload, monkeypatch):
    install(payload, tmp_path)
    _write_snapshot(tmp_path, **_coherent())
    ev = tmp_path / "e.txt"
    ev.write_text("x", encoding="utf-8")
    assert pipeline.close_gate(tmp_path, "build-green", ev)[0]
    monkeypatch.setattr(pipeline, "_LOCK_TIMEOUT_S", 0.15)
    _hold_lock(tmp_path)
    ok, msgs = pipeline.not_applicable(
        tmp_path,
        "contract-clear",
        condition="no-api-contract-surface",
        reason="no API",
        evidence=ev,
    )
    assert not ok
    assert any("could not lock" in m for m in msgs)


def test_abort_reports_lock_contention(tmp_path, payload, monkeypatch):
    install(payload, tmp_path)
    _write_snapshot(tmp_path, **_coherent())
    monkeypatch.setattr(pipeline, "_LOCK_TIMEOUT_S", 0.15)
    _hold_lock(tmp_path)
    ok, msgs = pipeline.abort(tmp_path)
    assert not ok
    assert any("could not lock" in m for m in msgs)
    assert _read_snap(tmp_path)["stage"] == "build-green"  # unchanged


def test_two_lock_contenders_never_reclaim_an_old_lock_or_trigger_aba(
    tmp_path, monkeypatch
):
    """Two would-be reclaimers both fail closed and leave the exact lock untouched."""
    state = tmp_path / ".claude" / "state"
    state.mkdir(parents=True)
    snap = state / "pipeline-snapshot.json"
    snap.write_text("{}", encoding="utf-8")
    lock = snap.with_name(snap.name + ".lock")
    lock.write_text("99999", encoding="utf-8")
    old = time.time() - (pipeline._LOCK_STALE_S + 60)
    os.utime(lock, (old, old))
    monkeypatch.setattr(pipeline, "_LOCK_TIMEOUT_S", 0)
    fs = pipeline.ProjectFS(tmp_path)
    for _contender in range(2):
        with pytest.raises(TimeoutError, match="verify that no writer owns"):
            with pipeline._snapshot_lock(snap, project_fs=fs):
                pass
        assert lock.read_text(encoding="utf-8") == "99999"


def test_snapshot_lock_retries_when_the_holder_releases_mid_check(
    tmp_path, monkeypatch
):
    """A normally released lock is retried without any age-based unlink."""
    state = tmp_path / ".claude" / "state"
    state.mkdir(parents=True)
    snap = state / "pipeline-snapshot.json"
    snap.write_text("{}", encoding="utf-8")
    lock = snap.with_name(snap.name + ".lock")
    lock.write_text("99999", encoding="utf-8")
    released = []

    def release_during_wait(_seconds):
        if not released:
            released.append(True)
            lock.unlink(missing_ok=True)

    monkeypatch.setattr(time, "sleep", release_during_wait)
    with pipeline._snapshot_lock(snap, project_fs=pipeline.ProjectFS(tmp_path)):
        pass
    assert released, "the contention retry path was never exercised"
    assert not lock.exists()


def test_pipeline_write_waits_out_project_transaction_lease_without_deadlock(
    tmp_path, payload
):
    """An install rollback window excludes runtime RMW; retry succeeds after release."""
    _start_v2(payload, tmp_path, profile="lean")
    evidence = tmp_path / "e.txt"
    evidence.write_text("verified", encoding="utf-8")
    transaction_fs = pipeline.ProjectFS(tmp_path)
    original = _read_snap(tmp_path)

    with transaction_fs.mutation_lease(exclusive=True):
        ok, msgs = pipeline.close_gate(tmp_path, "code-review", evidence)
        assert not ok
        assert any("project mutation is busy" in item for item in msgs), msgs
        assert _read_snap(tmp_path) == original

    ok, msgs = pipeline.close_gate(tmp_path, "code-review", evidence)
    assert ok, "\n".join(msgs)
    assert _read_snap(tmp_path)["last_gate_resolved"] == "code-review"


def test_not_applicable_appends_to_an_existing_ledger(tmp_path, payload):
    install(payload, tmp_path)
    _write_snapshot(tmp_path, **_coherent())
    ev = tmp_path / "e.txt"
    ev.write_text("x", encoding="utf-8")
    assert pipeline.close_gate(tmp_path, "build-green", ev)[0]
    ok, msgs = pipeline.not_applicable(
        tmp_path,
        "contract-clear",
        condition="no-api-contract-surface",
        reason="single-service change, no contract to verify",
        evidence=ev,
    )
    assert ok, "\n".join(msgs)
    history = _read_snap(tmp_path)["gate_history"]
    assert [(e["gate"], e["status"]) for e in history] == [
        ("build-green", "passed"),
        ("contract-clear", "not-applicable"),
    ]


# --- schema-v2 explicit lifecycle ---------------------------------------------------------------


def test_close_and_not_applicable_require_an_explicit_run(tmp_path, payload):
    _install_with_gate_metadata(payload, tmp_path)
    ev = tmp_path / "evidence.txt"
    ev.write_text("verified", encoding="utf-8")

    ok, msgs = pipeline.close_gate(tmp_path, "spec-complete", ev)
    assert not ok and any("start or adopt" in m for m in msgs)
    ok, msgs = pipeline.not_applicable(
        tmp_path,
        "contract-clear",
        condition="no-api-contract-surface",
        reason="no public API",
        evidence=ev,
    )
    assert not ok and any("start or adopt" in m for m in msgs)


def test_start_creates_complete_v2_identity_at_first_gate(tmp_path, payload):
    commit = _start_v2(payload, tmp_path)
    snap = _read_snap(tmp_path)

    assert snap["schema_version"] == 2
    assert snap["run_id"]
    assert snap["repository_root"] == str(tmp_path.resolve())
    assert snap["branch"] == "audit-main"
    assert snap["starting_commit"] == commit == snap["current_commit"]
    assert snap["start_type"] == "fresh"
    assert snap["status"] == "active"
    assert snap["stage"] == "spec-complete"
    assert snap["ordered_gates"][0] == "spec-complete"
    assert len(snap["gate_definition_digest"]) == 64
    assert len(snap["selection_digest"]) == 64
    assert snap["selection_digest"] == pipeline.installed_selection_digest(tmp_path)
    assert snap["findings_evidence"]["counts"] == _findings()
    assert snap["stage_history"] == []


def test_fast_track_start_freezes_only_its_ordered_gate_subset(tmp_path, payload):
    plan = _install_with_gate_metadata(payload, tmp_path, profile="standard")
    _init_git_repo(tmp_path)

    ok, messages = pipeline.start(tmp_path, task="fast change", mode="D")

    assert ok, "\n".join(messages)
    snapshot = _read_snap(tmp_path)
    assert snapshot["ordered_gates"] == ["code-review", "build-green"]
    assert snapshot["ordered_gates"] != plan.gates
    assert snapshot["gate_definition_digest"] == (
        pipeline.installed_gate_definition_digest_for_mode(tmp_path, "D")
    )
    valid, messages = pipeline.validate(tmp_path, strict=True)
    assert valid, "\n".join(messages)


def test_stage_ledger_claims_before_execution_and_never_reruns_completed_stage(
    tmp_path, payload
):
    _start_v2(payload, tmp_path)

    unsupported, messages = pipeline.claim_stage(
        tmp_path,
        stage="implementation",
        role="developer",
        provider="codex",
        dispatch_id="dispatch-unsupported",
        attempt=1,
        required_capabilities=("filesystem.write",),
        attested_capabilities=("filesystem.read",),
    )
    assert not unsupported
    assert "unsupported required capabilities" in messages[0]
    assert _read_snap(tmp_path)["stage_history"] == []

    claimed, messages = pipeline.claim_stage(
        tmp_path,
        stage="implementation",
        role="developer",
        provider="claude",
        dispatch_id="dispatch-1",
        attempt=1,
        required_capabilities=("filesystem.read", "filesystem.write"),
        attested_capabilities=("filesystem.read", "filesystem.write", "shell"),
    )
    assert claimed, "\n".join(messages)
    duplicate, messages = pipeline.claim_stage(
        tmp_path,
        stage="implementation",
        role="developer",
        provider="codex",
        dispatch_id="dispatch-2",
        attempt=1,
        required_capabilities=("filesystem.read",),
        attested_capabilities=("filesystem.read",),
    )
    assert not duplicate and "running attempt" in messages[0]

    finished, messages = pipeline.finish_stage(
        tmp_path,
        stage="implementation",
        dispatch_id="dispatch-1",
        attempt=1,
        status="succeeded",
        output_sha256="a" * 64,
        evidence=("artifact://implementation-report",),
    )
    assert finished, "\n".join(messages)
    completed, error = pipeline.completed_stage_ids(tmp_path)
    assert error is None and completed == {"implementation"}

    rerun, messages = pipeline.claim_stage(
        tmp_path,
        stage="implementation",
        role="developer",
        provider="codex",
        dispatch_id="dispatch-3",
        attempt=1,
        required_capabilities=("filesystem.read",),
        attested_capabilities=("filesystem.read",),
    )
    assert not rerun and "cannot run twice" in messages[0]
    ok, messages = pipeline.validate(tmp_path, strict=True)
    assert ok, "\n".join(messages)


def test_existing_schema_v2_snapshot_without_stage_history_defaults_safely(
    tmp_path, payload
):
    _start_v2(payload, tmp_path)
    path = tmp_path / ".claude/state/pipeline-snapshot.json"
    snapshot = _read_snap(tmp_path)
    snapshot.pop("stage_history")
    path.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")

    ok, messages = pipeline.validate(tmp_path, strict=True)
    assert ok, "\n".join(messages)
    completed, error = pipeline.completed_stage_ids(tmp_path)
    assert error is None and completed == set()
    claimed, messages = pipeline.claim_stage(
        tmp_path,
        stage="review",
        role="reviewer",
        provider="codex",
        dispatch_id="dispatch-new",
        attempt=1,
        required_capabilities=("filesystem.read",),
        attested_capabilities=("filesystem.read",),
    )
    assert claimed, "\n".join(messages)
    assert len(_read_snap(tmp_path)["stage_history"]) == 1


def test_workflow_condition_decisions_freeze_before_cross_host_resume(
    tmp_path, payload
):
    _start_v2(payload, tmp_path)

    frozen, error = pipeline.bind_workflow_condition_decisions(
        tmp_path,
        {"frontend-surface-present": False, "backend-surface-present": True},
    )
    assert error is None
    assert frozen == {
        "backend-surface-present": True,
        "frontend-surface-present": False,
    }
    resumed, error = pipeline.workflow_condition_decisions(tmp_path)
    assert error is None and resumed == frozen
    before = _read_snap(tmp_path)

    rejected, error = pipeline.bind_workflow_condition_decisions(
        tmp_path,
        {"frontend-surface-present": True, "backend-surface-present": True},
    )
    assert rejected is None
    assert error is not None and "differ" in error
    assert _read_snap(tmp_path) == before
    ok, messages = pipeline.validate(tmp_path, strict=True)
    assert ok, "\n".join(messages)


def test_managed_gate_requires_successful_named_owner_stage(tmp_path, payload):
    _start_v2(payload, tmp_path)
    workflow = pipeline._current_workflow_definition()
    snapshot = _read_snap(tmp_path)
    gates = tuple(snapshot["ordered_gates"])
    owners = {gate: workflow.gates[gate].stage for gate in gates}
    workspace, manager = _managed_workspace(tmp_path)
    managed, error = pipeline.bind_managed_execution(
        tmp_path,
        workflow_id=workflow.id,
        workflow_schema_version=workflow.schema_version,
        workflow_definition_digest=pipeline._current_workflow_identity()[2],
        mode="B",
        ordered_gates=gates,
        gate_definition_digest=snapshot["gate_definition_digest"],
        gate_owner_stages=owners,
        workspace=workspace,
    )
    assert error is None and managed is not None
    evidence = tmp_path / "managed-gate.txt"
    evidence.write_text("named owner verified\n", encoding="utf-8")

    closed, messages = pipeline.close_gate(tmp_path, gates[0], evidence)
    assert not closed and "owner stage" in messages[0]

    _finish_managed_stage(tmp_path, manager, stage=owners[gates[0]], provider="claude")
    mismatch = tmp_path / "mismatched-findings.json"
    mismatch.write_text('{"medium": 1}\n', encoding="utf-8")
    recorded, mismatch_messages = pipeline.record_findings(
        tmp_path,
        critical=0,
        high=0,
        medium=1,
        low=0,
        cosmetic=0,
        evidence=mismatch,
    )
    assert not recorded
    assert "differ from canonical owner-stage evidence" in "\n".join(mismatch_messages)
    _record_findings(tmp_path)
    closed, messages = pipeline.close_gate(tmp_path, gates[0], evidence)
    assert closed, "\n".join(messages)
    entry = _read_snap(tmp_path)["gate_history"][0]
    bundle = tmp_path / entry["evidence_path"]
    assert bundle != evidence
    assert bundle.stat().st_mode & 0o777 == 0o600
    assert json.loads(bundle.read_text(encoding="utf-8"))["kind"] == (
        "managed-workflow-gate-evidence"
    )
    evidence.write_text("mutable caller input changed\n", encoding="utf-8")
    assert pipeline.validate(tmp_path, strict=True)[0]
    bundle.write_text("{}\n", encoding="utf-8")
    valid, validation_messages = pipeline.validate(tmp_path, strict=True)
    assert not valid
    assert "bundle" in "\n".join(validation_messages)


def test_schema_requires_typed_evidence_authority_on_active_managed_run(
    tmp_path, payload
):
    _start_v2(payload, tmp_path, record_clean=False)
    workflow = pipeline._current_workflow_definition()
    snapshot = _read_snap(tmp_path)
    gates = tuple(snapshot["ordered_gates"])
    workspace, _manager = _managed_workspace(tmp_path)
    managed, error = pipeline.bind_managed_execution(
        tmp_path,
        workflow_id=workflow.id,
        workflow_schema_version=workflow.schema_version,
        workflow_definition_digest=pipeline._current_workflow_identity()[2],
        mode="B",
        ordered_gates=gates,
        gate_definition_digest=snapshot["gate_definition_digest"],
        gate_owner_stages={gate: workflow.gates[gate].stage for gate in gates},
        workspace=workspace,
    )
    assert error is None and managed is not None
    active = _read_snap(tmp_path)
    with ExitStack() as stack:
        assert schemas.validate_doc(active, "pipeline-snapshot", stack) == []
        for field in (
            "evidence_contract_version",
            "active_stage_evidence",
            "gate_evidence",
            "evidence_requirements",
            "findings_policy",
        ):
            malformed = json.loads(json.dumps(active))
            malformed["managed_execution"].pop(field)
            errors = schemas.validate_doc(malformed, "pipeline-snapshot", stack)
            assert errors, field
        missing_binding = json.loads(json.dumps(active))
        missing_binding.pop("execution_binding")
        assert schemas.validate_doc(missing_binding, "pipeline-snapshot", stack)
        missing_contract = json.loads(json.dumps(active))
        missing_contract.pop("managed_execution")
        assert schemas.validate_doc(missing_contract, "pipeline-snapshot", stack)

    snapshot_path = tmp_path / ".claude/state/pipeline-snapshot.json"
    snapshot_path.write_text(
        json.dumps(missing_contract, indent=2) + "\n", encoding="utf-8"
    )
    valid, validation_messages = pipeline.validate(tmp_path, strict=True)
    assert not valid
    assert "without its execution contract" in "\n".join(validation_messages)
    first_stage = managed["active_stages"][0]
    route = managed["active_stage_routes"][first_stage]
    capabilities = tuple(managed["active_stage_requirements"][first_stage])
    claimed, claim_messages = pipeline.claim_stage(
        tmp_path,
        stage=first_stage,
        role=route["role"],
        provider="claude",
        dispatch_id="downgraded-untyped-claim",
        attempt=1,
        required_capabilities=capabilities,
        attested_capabilities=capabilities,
    )
    assert not claimed
    assert "without its execution contract" in "\n".join(claim_messages)


def test_managed_bind_rechecks_workspace_and_controls_under_the_write_lock(
    tmp_path, payload, monkeypatch
):
    _start_v2(payload, tmp_path, record_clean=False)
    workflow = pipeline._current_workflow_definition()
    snapshot = _read_snap(tmp_path)
    gates = tuple(snapshot["ordered_gates"])
    workspace, _manager = _managed_workspace(tmp_path)
    workspace_root = (tmp_path / workspace["target_path"]).resolve(strict=True)
    control = workspace_root / "CLAUDE.md"
    original = control.read_text(encoding="utf-8")
    real_lock = pipeline._pipeline_write_lock
    mutated = False

    @contextmanager
    def mutating_lock(fs, path, *, msgs=None):
        nonlocal mutated
        if not mutated:
            control.write_text(
                original + "\nmutated before authoritative lock\n", encoding="utf-8"
            )
            mutated = True
        with real_lock(fs, path, msgs=msgs):
            yield

    monkeypatch.setattr(pipeline, "_pipeline_write_lock", mutating_lock)
    managed, error = pipeline.bind_managed_execution(
        tmp_path,
        workflow_id=workflow.id,
        workflow_schema_version=workflow.schema_version,
        workflow_definition_digest=pipeline._current_workflow_identity()[2],
        mode="B",
        ordered_gates=gates,
        gate_definition_digest=snapshot["gate_definition_digest"],
        gate_owner_stages={gate: workflow.gates[gate].stage for gate in gates},
        workspace=workspace,
    )

    assert mutated
    assert managed is None
    assert error is not None and "changed during" in error
    assert _read_snap(tmp_path).get("managed_execution") is None


def test_managed_bind_rechecks_source_head_under_the_write_lock(
    tmp_path, payload, monkeypatch
):
    _start_v2(payload, tmp_path, record_clean=False)
    workflow = pipeline._current_workflow_definition()
    snapshot = _read_snap(tmp_path)
    gates = tuple(snapshot["ordered_gates"])
    workspace, _manager = _managed_workspace(tmp_path)
    real_lock = pipeline._pipeline_write_lock
    advanced = False

    @contextmanager
    def advancing_lock(fs, path, *, msgs=None):
        nonlocal advanced
        if not advanced:
            marker = tmp_path / "source-advanced-before-bind.txt"
            marker.write_text("new source commit\n", encoding="utf-8")
            subprocess.run(["git", "add", marker.name], cwd=tmp_path, check=True)
            subprocess.run(
                ["git", "commit", "-m", "advance source during bind"],
                cwd=tmp_path,
                check=True,
                capture_output=True,
            )
            advanced = True
        with real_lock(fs, path, msgs=msgs):
            yield

    monkeypatch.setattr(pipeline, "_pipeline_write_lock", advancing_lock)
    managed, error = pipeline.bind_managed_execution(
        tmp_path,
        workflow_id=workflow.id,
        workflow_schema_version=workflow.schema_version,
        workflow_definition_digest=pipeline._current_workflow_identity()[2],
        mode="B",
        ordered_gates=gates,
        gate_definition_digest=snapshot["gate_definition_digest"],
        gate_owner_stages={gate: workflow.gates[gate].stage for gate in gates},
        workspace=workspace,
    )

    assert advanced
    assert managed is None
    assert error is not None and "source checkout HEAD changed during" in error
    assert _read_snap(tmp_path).get("managed_execution") is None


def test_managed_gate_findings_cover_exact_transitive_dependency_observations(
    tmp_path, payload
):
    _start_v2(payload, tmp_path, record_clean=False)
    _managed, manager = _bind_managed_run(tmp_path)
    snapshot = _read_snap(tmp_path)
    checkpoint = manager.checkpoint(str(snapshot["run_id"]), "managed-workflow")

    medium_report = _managed_evidence_document("security-report")
    medium_report["findings"] = [
        {
            "id": "MED-SCAN-1",
            "severity": "medium",
            "disposition": "open",
            "evidence": ["tests/test_pipeline.py"],
        }
    ]
    medium_report["dispositions"] = [
        {
            "finding-id": "MED-SCAN-1",
            "disposition": "open",
            "evidence": ["tests/test_pipeline.py"],
        }
    ]

    def observation(
        stage: str,
        *,
        document: dict[str, dict] | None = None,
        artifact_sha: str,
        status: str = "succeeded",
    ) -> dict:
        dispatch_id = f"claude-{stage}"
        output, _references, records = _managed_stage_result(
            tmp_path,
            snapshot,
            stage=stage,
            dispatch_id=dispatch_id,
            attempt=1,
            evidence_documents=document,
            require_pass=status == "succeeded",
        )
        return {
            "stage": stage,
            "role": "test-role",
            "provider": "claude",
            "dispatch_id": dispatch_id,
            "dispatch_attempt": 1,
            "attempt": 1,
            "status": status,
            "started_at": "2026-01-01T00:00:00+00:00",
            "finished_at": "2026-01-01T00:00:01+00:00",
            "output_sha256": hashlib.sha256(output.encode()).hexdigest(),
            "output_artifact_sha256": artifact_sha,
            "workspace_checkpoint": checkpoint.to_dict(),
            "evidence_records": list(records),
        }

    synthetic = json.loads(json.dumps(snapshot))
    synthetic["stage_history"] = [
        observation(
            "secret-scan",
            document={"security-report": medium_report},
            artifact_sha="a" * 64,
        ),
        observation(
            "dependency-scan",
            document={"security-report": medium_report},
            artifact_sha="b" * 64,
        ),
        observation("security-aggregate", artifact_sha="c" * 64),
        {
            "stage": "pull-request-prepare",
            "status": "succeeded",
            "evidence_records": [{"outside-closure": True}],
        },
    ]
    owner, findings, counts, contributors, projection_digest = (
        pipeline._managed_gate_finding_projection(
            ProjectFS(tmp_path), synthetic, "security-clear"
        )
    )

    assert owner is not None and owner["stage"] == "security-aggregate"
    assert counts == _findings(medium=1)
    assert [item["finding_id"] for item in findings] == ["MED-SCAN-1"]
    assert {item["stage"] for item in contributors} == {
        "secret-scan",
        "dependency-scan",
        "security-aggregate",
    }
    assert isinstance(projection_digest, str) and len(projection_digest) == 64
    findings_bundle, findings_error = pipeline._managed_findings_bundle(
        ProjectFS(tmp_path), synthetic, gate="security-clear", persist=False
    )
    gate_bundle, gate_error = pipeline._managed_gate_bundle(
        ProjectFS(tmp_path), synthetic, gate="security-clear", persist=False
    )
    assert findings_error is None and findings_bundle is not None
    assert gate_error is None and gate_bundle is not None
    assert findings_bundle["document"]["evidence_set_digest"] == projection_digest
    assert gate_bundle["document"]["finding_evidence_set_digest"] == projection_digest

    failed_report = json.loads(json.dumps(medium_report))
    failed_report["findings"][0].update(
        {"id": "CRIT-FAILED-SCAN", "severity": "critical"}
    )
    failed_report["dispositions"][0]["finding-id"] = "CRIT-FAILED-SCAN"
    failed_projection = json.loads(json.dumps(synthetic))
    failed_projection["stage_history"] = [
        record
        for record in failed_projection["stage_history"]
        if record["stage"] != "dependency-scan"
    ]
    failed_projection["stage_history"].append(
        observation(
            "dependency-scan",
            document={"security-report": failed_report},
            artifact_sha="f" * 64,
            status="failed",
        )
    )
    _owner, failed_findings, failed_counts, failed_contributors, failed_digest = (
        pipeline._managed_gate_finding_projection(
            ProjectFS(tmp_path), failed_projection, "security-clear"
        )
    )
    assert isinstance(failed_digest, str) and len(failed_digest) == 64
    assert failed_counts == _findings(critical=1, medium=1)
    assert {item["finding_id"] for item in failed_findings} == {
        "CRIT-FAILED-SCAN",
        "MED-SCAN-1",
    }
    assert any(
        item["stage"] == "dependency-scan" and item["status"] == "failed"
        for item in failed_contributors
    )

    conflicting_report = json.loads(json.dumps(medium_report))
    conflicting_report["findings"][0]["evidence"] = ["different-evidence.txt"]
    conflicting_report["dispositions"][0]["evidence"] = ["different-evidence.txt"]
    synthetic["stage_history"].append(
        observation(
            "policy-review",
            document={"security-report": conflicting_report},
            artifact_sha="d" * 64,
        )
    )
    conflict_owner, _conflict_findings, _counts, _contributors, conflict = (
        pipeline._managed_gate_finding_projection(
            ProjectFS(tmp_path), synthetic, "security-clear"
        )
    )
    assert conflict_owner is None
    assert conflict is not None and "conflicting evidence identities" in conflict


def test_managed_closeout_requires_the_exact_gate_and_risk_ledgers(tmp_path, payload):
    _start_v2(payload, tmp_path, record_clean=False, mode="D")
    _managed, manager = _bind_managed_run(tmp_path, mode="D")
    gate_evidence = tmp_path / "managed-closeout-gate.txt"
    gate_evidence.write_text("owner evidence verified\n", encoding="utf-8")

    _finish_managed_stage(tmp_path, manager, stage="fast-review")
    _record_findings(tmp_path)
    closed, messages = pipeline.close_gate(
        tmp_path, "code-review", gate_evidence, strict=True
    )
    assert closed, "\n".join(messages)
    _finish_managed_stage(tmp_path, manager, stage="fast-verify")
    _record_findings(tmp_path)
    closed, messages = pipeline.close_gate(
        tmp_path, "build-green", gate_evidence, strict=True
    )
    assert closed, "\n".join(messages)

    snapshot = _read_snap(tmp_path)
    gates, risks, problem = pipeline._managed_closeout_projection(
        ProjectFS(tmp_path), snapshot
    )
    assert problem is None and gates is not None and risks == []
    exact = {
        "outcome": "prepared",
        "gates": gates,
        "accepted-risks": risks,
        "learnings": [],
    }

    def materialize(document: dict, attempt: int):
        return pipeline.materialize_managed_stage_evidence(
            tmp_path,
            stage="fast-pull-request-prepare",
            dispatch_id="claude-closeout",
            dispatch_attempt=attempt,
            output=json.dumps(
                {"evidence": {"closeout-record": document}}, sort_keys=True
            ),
        )

    records, error = materialize(exact, 1)
    assert error is None and records is not None

    extra_resolution = json.loads(json.dumps(snapshot))
    extra_resolution["gate_history"].append(
        {
            "gate": "invented-gate",
            "status": "passed",
            "evidence_path": "made-up",
            "evidence_sha256": "c" * 64,
        }
    )
    _gates, _risks, projection_error = pipeline._managed_closeout_projection(
        ProjectFS(tmp_path), extra_resolution
    )
    assert projection_error is not None and "exact ordered gate set" in projection_error

    forged_bundle = json.loads(json.dumps(snapshot))
    forged_bundle["gate_history"][0]["evidence_path"] = "../../forged.json"
    forged_bundle["gate_history"][0]["evidence_sha256"] = "d" * 64
    _gates, _risks, projection_error = pipeline._managed_closeout_projection(
        ProjectFS(tmp_path), forged_bundle
    )
    assert (
        projection_error is not None
        and "exact owner evidence bundle" in projection_error
    )

    wrong_status_key = json.loads(json.dumps(snapshot))
    first_resolution = wrong_status_key["gate_history"][0]
    first_resolution["condition_evidence_path"] = first_resolution.pop("evidence_path")
    first_resolution["condition_evidence_sha256"] = first_resolution.pop(
        "evidence_sha256"
    )
    _gates, _risks, projection_error = pipeline._managed_closeout_projection(
        ProjectFS(tmp_path), wrong_status_key
    )
    assert (
        projection_error is not None and "not-applicable evidence" in projection_error
    )

    invented = json.loads(json.dumps(exact))
    invented["gates"][0]["id"] = "invented-gate"
    missing = json.loads(json.dumps(exact))
    missing["gates"].pop()
    extra = json.loads(json.dumps(exact))
    extra["gates"].append(
        {
            "id": "invented-gate",
            "status": "passed",
            "evidence": [{"path": "made-up", "sha256": "a" * 64}],
        }
    )
    invented_risk = json.loads(json.dumps(exact))
    invented_risk["accepted-risks"] = [
        {
            "risk-id": "invented-risk",
            "affected-gate": "build-green",
            "finding-id": "MED-INVENTED",
            "reason": "invented",
            "accepter": "test-owner",
            "owner": "test-owner",
            "ticket": "TEST-1",
            "revisit-trigger": "before release",
            "evidence": [{"path": "made-up", "sha256": "b" * 64}],
        }
    ]
    for attempt, malformed in enumerate(
        (invented, missing, extra, invented_risk), start=2
    ):
        malformed_records, malformed_error = materialize(malformed, attempt)
        assert malformed_records is None
        assert malformed_error is not None
        assert "differs" in malformed_error


def test_managed_terminal_artifacts_are_immutable_and_namespaced_per_run(
    tmp_path, payload
):
    _start_v2(payload, tmp_path, record_clean=False)
    _managed, first_manager = _bind_managed_run(tmp_path)
    _finish_managed_stage(tmp_path, first_manager, stage="classify")
    first_snapshot = _read_snap(tmp_path)
    first_record = next(
        item
        for item in first_snapshot["stage_history"]
        if item["stage"] == "classify" and item["status"] == "succeeded"
    )
    first_path = str(first_record["output_path"])
    first_bytes = (tmp_path / first_path).read_bytes()
    assert (
        f"/dispatch/runs/{first_snapshot['run_id']}/classify/1/terminal-" in first_path
    )

    aborted, messages = pipeline.abort(tmp_path)
    assert aborted, "\n".join(messages)
    aborted_snapshot = _read_snap(tmp_path)
    typed_evidence_path = first_record["evidence_records"][0]["artifact_path"]
    typed_evidence = tmp_path / typed_evidence_path
    typed_evidence_bytes = typed_evidence.read_bytes()
    downgraded_terminal = json.loads(json.dumps(aborted_snapshot))
    downgraded_terminal["managed_execution"].pop("evidence_contract_version")
    typed_evidence.write_bytes(b"{}")
    snapshot_path = tmp_path / ".claude/state/pipeline-snapshot.json"
    snapshot_path.write_text(
        json.dumps(downgraded_terminal, indent=2) + "\n", encoding="utf-8"
    )
    valid, validation_messages = pipeline.validate(tmp_path, strict=True)
    assert not valid
    assert "typed managed evidence contract version" in "\n".join(validation_messages)
    with ExitStack() as stack:
        assert schemas.validate_doc(downgraded_terminal, "pipeline-snapshot", stack)
    typed_evidence.write_bytes(typed_evidence_bytes)
    typed_evidence.chmod(0o600)
    snapshot_path.write_text(
        json.dumps(aborted_snapshot, indent=2) + "\n", encoding="utf-8"
    )
    started, messages = pipeline.start(tmp_path, task="second managed run", mode="B")
    assert started, "\n".join(messages)
    _managed, second_manager = _bind_managed_run(tmp_path)
    _finish_managed_stage(tmp_path, second_manager, stage="classify")
    second_snapshot = _read_snap(tmp_path)
    second_record = next(
        item
        for item in second_snapshot["stage_history"]
        if item["stage"] == "classify" and item["status"] == "succeeded"
    )
    second_path = str(second_record["output_path"])

    assert first_snapshot["run_id"] != second_snapshot["run_id"]
    assert first_path != second_path
    assert (tmp_path / first_path).read_bytes() == first_bytes
    assert (tmp_path / second_path).is_file()
    assert (
        f"/dispatch/runs/{second_snapshot['run_id']}/classify/1/terminal-"
        in second_path
    )
    cross_run_record = dict(second_record)
    cross_run_record["output_path"] = first_path
    cross_run_record["output_artifact_sha256"] = first_record["output_artifact_sha256"]
    problem = pipeline._managed_terminal_artifact_problem(
        tmp_path, second_snapshot, cross_run_record
    )
    assert problem is not None and "another run" in problem
    assert pipeline.validate(tmp_path, strict=True)[0]

    first_artifact = tmp_path / first_path
    for mutation in ("tampered", "missing", "wrong-mode"):
        if mutation == "tampered":
            first_artifact.write_bytes(b"{}")
        elif mutation == "missing":
            first_artifact.unlink()
        else:
            first_artifact.chmod(0o644)
        valid, messages = pipeline.validate(tmp_path, strict=True)
        assert not valid
        assert any(
            "run_archives[0]" in message and "terminal artifact" in message
            for message in messages
        )
        first_artifact.write_bytes(first_bytes)
        first_artifact.chmod(0o600)
        assert pipeline.validate(tmp_path, strict=True)[0]


def test_archived_typed_managed_artifacts_remain_live_verified(tmp_path, payload):
    _start_v2(payload, tmp_path, record_clean=False)
    managed, manager = _bind_managed_run(tmp_path)
    snapshot = _read_snap(tmp_path)
    gates = tuple(snapshot["ordered_gates"])
    definitions = pipeline.installed_gate_definitions(tmp_path)
    conditional_gate = next(
        gate for gate in gates if definitions[gate].requirement == "conditional"
    )
    preceding = gates[: gates.index(conditional_gate)]
    owners = managed["gate_owner_stages"]
    frozen, freeze_error = pipeline.bind_workflow_condition_decisions(
        tmp_path, {"api-contract-surface-present": False}
    )
    assert freeze_error is None and frozen is not None
    _record_findings(tmp_path)
    evidence = tmp_path / "archive-gate-evidence.txt"
    evidence.write_text("verified\n", encoding="utf-8")

    completed_owners: set[str] = set()
    for gate in preceding:
        owner = owners[gate]
        if owner not in completed_owners:
            _finish_managed_stage(tmp_path, manager, stage=owner)
            completed_owners.add(owner)
        closed, messages = pipeline.close_gate(tmp_path, gate, evidence)
        assert closed, "\n".join(messages)

    current = _read_snap(tmp_path)
    conditional_owner = owners[conditional_gate]
    dependencies = tuple(
        current["managed_execution"]["active_stage_dependencies"][conditional_owner]
    )
    checkpoint = manager.checkpoint(str(current["run_id"]), "managed-workflow")
    attested, messages = pipeline.attest_skipped_stage(
        tmp_path,
        stage=conditional_owner,
        condition="api-contract-surface-present",
        dependencies=dependencies,
        dependency_states={dependency: "succeeded" for dependency in dependencies},
        workspace_checkpoint=checkpoint.to_dict(),
    )
    assert attested, "\n".join(messages)
    skipped, messages = pipeline.not_applicable(
        tmp_path,
        conditional_gate,
        condition="no-api-contract-surface",
        reason="the frozen API surface decision is false",
        evidence=evidence,
    )
    assert skipped, "\n".join(messages)

    first_run = _read_snap(tmp_path)
    successful_record = next(
        record
        for record in first_run["stage_history"]
        if record.get("status") == "succeeded"
    )
    ordinary_gate = next(
        entry for entry in first_run["gate_history"] if entry["status"] == "passed"
    )
    not_applicable_gate = next(
        entry
        for entry in first_run["gate_history"]
        if entry["status"] == "not-applicable"
    )
    artifact_paths = {
        "terminal": successful_record["output_path"],
        "stage evidence": successful_record["evidence_records"][0]["artifact_path"],
        "findings bundle": first_run["findings_evidence"]["evidence_path"],
        "gate bundle": ordinary_gate["evidence_path"],
        "not-applicable bundle": not_applicable_gate["condition_evidence_path"],
    }

    aborted, messages = pipeline.abort(tmp_path)
    assert aborted, "\n".join(messages)
    started, messages = pipeline.start(tmp_path, task="archive verifier", mode="B")
    assert started, "\n".join(messages)
    _bind_managed_run(tmp_path)
    assert pipeline.validate(tmp_path, strict=True)[0]

    for artifact_name, relative in artifact_paths.items():
        artifact = tmp_path / relative
        original = artifact.read_bytes()
        original_mode = artifact.stat().st_mode & 0o777
        for mutation in ("tampered", "missing", "wrong-mode"):
            if mutation == "tampered":
                artifact.write_bytes(b"{}")
            elif mutation == "missing":
                artifact.unlink()
            else:
                artifact.chmod(0o644)
            valid, validation_messages = pipeline.validate(tmp_path, strict=True)
            assert not valid, f"{artifact_name} {mutation} was accepted"
            assert any("run_archives[0]" in message for message in validation_messages)
            artifact.write_bytes(original)
            artifact.chmod(original_mode)
            assert pipeline.validate(tmp_path, strict=True)[0]

    downgraded_archive = _read_snap(tmp_path)
    archived_snapshot = downgraded_archive["run_archives"][0]["snapshot"]
    archived_snapshot["managed_execution"].pop("evidence_contract_version")
    downgraded_archive["run_archives"][0]["snapshot_sha256"] = (
        pipeline._document_sha256(archived_snapshot)
    )
    snapshot_path = tmp_path / ".claude/state/pipeline-snapshot.json"
    snapshot_path.write_text(
        json.dumps(downgraded_archive, indent=2) + "\n", encoding="utf-8"
    )
    valid, validation_messages = pipeline.validate(tmp_path, strict=True)
    assert not valid
    assert any(
        "run_archives[0]" in message
        and "typed managed evidence contract version" in message
        for message in validation_messages
    )
    with ExitStack() as stack:
        assert schemas.validate_doc(downgraded_archive, "pipeline-snapshot", stack)


def test_failed_typed_findings_are_persisted_and_block_a_clean_retry(tmp_path, payload):
    _start_v2(payload, tmp_path, record_clean=False, mode="D")
    managed, manager = _bind_managed_run(tmp_path, mode="D")
    _finish_managed_stage(tmp_path, manager, stage="fast-implementation")
    stage = "fast-review"
    dispatch_id = "claude-fast-review-failing"
    route = managed["active_stage_routes"][stage]
    capabilities = tuple(managed["active_stage_requirements"][stage])
    claimed, messages = pipeline.claim_stage(
        tmp_path,
        stage=stage,
        role=route["role"],
        provider="claude",
        dispatch_id=dispatch_id,
        attempt=1,
        required_capabilities=capabilities,
        attested_capabilities=capabilities,
    )
    assert claimed, "\n".join(messages)

    verdict = _managed_evidence_document("review-verdict")
    verdict["status"] = "FAIL"
    verdict["findings"] = [
        {
            "id": "CRIT-FAILED-1",
            "severity": "critical",
            "disposition": "open",
            "evidence": ["tests/test_pipeline.py"],
        }
    ]
    output = json.dumps({"evidence": {"review-verdict": verdict}}, sort_keys=True)
    records, error = pipeline.materialize_managed_stage_evidence(
        tmp_path,
        stage=stage,
        dispatch_id=dispatch_id,
        dispatch_attempt=1,
        output=output,
        require_pass=False,
    )
    assert error is None and records is not None
    snapshot = _read_snap(tmp_path)
    checkpoint = manager.checkpoint(str(snapshot["run_id"]), "managed-workflow")
    references = ("artifact://review-verdict",)
    relative, artifact_sha = _write_managed_terminal_artifact(
        tmp_path,
        snapshot,
        stage=stage,
        dispatch_id=dispatch_id,
        dispatch_attempt=1,
        status="failed",
        output=output,
        error="review verdict status is not PASS",
        evidence=references,
        evidence_records=records,
        workspace_checkpoint=checkpoint.to_dict(),
    )
    finished, messages = pipeline.finish_stage(
        tmp_path,
        stage=stage,
        dispatch_id=dispatch_id,
        attempt=1,
        status="failed",
        output_sha256=hashlib.sha256(output.encode()).hexdigest(),
        output_path=relative,
        output_artifact_sha256=artifact_sha,
        workspace_checkpoint=checkpoint.to_dict(),
        evidence=references,
        evidence_records=records,
        error="review verdict status is not PASS",
    )
    assert finished, "\n".join(messages)

    failed_record = next(
        item
        for item in _read_snap(tmp_path)["stage_history"]
        if item["stage"] == stage and item["status"] == "failed"
    )
    assert failed_record["finding_counts"] == _findings(critical=1)
    assert [item["finding_id"] for item in failed_record["findings"]] == [
        "CRIT-FAILED-1"
    ]
    assert failed_record["evidence_records"] == list(records)

    retried, retry_messages = pipeline.claim_stage(
        tmp_path,
        stage=stage,
        role=route["role"],
        provider="claude",
        dispatch_id="claude-fast-review-clean-retry",
        attempt=2,
        required_capabilities=capabilities,
        attested_capabilities=capabilities,
    )
    assert not retried
    assert "unresolved authoritative typed evidence" in "\n".join(retry_messages)
    valid, validation_messages = pipeline.validate(tmp_path, strict=True)
    assert valid, "\n".join(validation_messages)


def test_managed_risk_acceptance_requires_exact_medium_finding_identity(
    tmp_path, payload
):
    _start_v2(payload, tmp_path)
    workflow = pipeline._current_workflow_definition()
    snapshot = _read_snap(tmp_path)
    gates = tuple(snapshot["ordered_gates"])
    owners = {gate: workflow.gates[gate].stage for gate in gates}
    workspace, manager = _managed_workspace(tmp_path)
    managed, error = pipeline.bind_managed_execution(
        tmp_path,
        workflow_id=workflow.id,
        workflow_schema_version=workflow.schema_version,
        workflow_definition_digest=pipeline._current_workflow_identity()[2],
        mode="B",
        ordered_gates=gates,
        gate_definition_digest=snapshot["gate_definition_digest"],
        gate_owner_stages=owners,
        workspace=workspace,
    )
    assert error is None and managed is not None
    verdict = _managed_evidence_document("review-verdict")
    verdict["findings"] = [
        {
            "id": "MED-EXACT-1",
            "severity": "medium",
            "disposition": "open",
            "evidence": ["src/example.py:10"],
        }
    ]
    _finish_managed_stage(
        tmp_path,
        manager,
        stage=owners[gates[0]],
        evidence_documents={"review-verdict": verdict},
    )
    findings_input = tmp_path / "managed-medium-findings.json"
    findings_input.write_text('{"medium": 1}\n', encoding="utf-8")
    recorded, messages = pipeline.record_findings(
        tmp_path,
        critical=0,
        high=0,
        medium=1,
        low=0,
        cosmetic=0,
        evidence=findings_input,
    )
    assert recorded, "\n".join(messages)
    acceptance = tmp_path / "risk-acceptance.md"
    acceptance.write_text(
        "Owner accepts this exact Medium finding.\n", encoding="utf-8"
    )
    common = {
        "reason": "bounded residual risk",
        "accepted_by": "test-owner",
        "owner": "test-owner",
        "ticket": "TICKET-1",
        "revisit": "before release",
        "evidence": acceptance,
    }
    accepted, messages = pipeline.accept_risk(
        tmp_path, gates[0], finding_id="MED-FORGED", **common
    )
    assert not accepted
    assert "not an exact current Medium finding id" in "\n".join(messages)
    accepted, messages = pipeline.accept_risk(
        tmp_path, gates[0], finding_id="MED-EXACT-1", **common
    )
    assert accepted, "\n".join(messages)
    entry = _read_snap(tmp_path)["gate_history"][0]
    assert entry["status"] == "accepted-risk"
    assert entry["owner_stage"] == owners[gates[0]]
    assert pipeline.validate(tmp_path, strict=True)[0]
    accepted_snapshot = _read_snap(tmp_path)
    closeout_snapshot = json.loads(json.dumps(accepted_snapshot))
    closeout_snapshot["ordered_gates"] = [gates[0]]
    projected_gates, projected_risks, projection_problem = (
        pipeline._managed_closeout_projection(ProjectFS(tmp_path), closeout_snapshot)
    )
    assert projection_problem is None and projected_gates is not None
    assert projected_risks is not None and len(projected_risks) == 1
    source_risk = accepted_snapshot["accepted_risks"][0]
    projected_risk = projected_risks[0]
    assert projected_risk["risk-id"] == source_risk["risk_id"]
    assert projected_risk["compensating-control"] == source_risk["compensating_control"]
    assert projected_risk["timestamp"] == source_risk["timestamp"]
    assert projected_risk["repository-commit"] == source_risk["repository_commit"]
    assert projected_risk["finding-set-digest"] == source_risk["finding_set_digest"]
    assert projected_risk["finding-fingerprint"] == source_risk["finding_fingerprint"]
    assert (
        projected_risk["gate-definition-digest"]
        == source_risk["gate_definition_digest"]
    )
    assert (
        projected_risk["workspace-content-digest"]
        == source_risk["workspace_content_digest"]
    )
    risk_artifact = tmp_path / source_risk["evidence_path"]
    assert (
        f"/evidence/runs/{accepted_snapshot['run_id']}/risks/{gates[0]}/"
        in source_risk["evidence_path"]
    )
    assert risk_artifact.stat().st_mode & 0o777 == 0o600
    risk_bytes = risk_artifact.read_bytes()
    acceptance.write_text("mutable caller evidence changed\n", encoding="utf-8")
    assert pipeline.validate(tmp_path, strict=True)[0]

    aborted, messages = pipeline.abort(tmp_path)
    assert aborted, "\n".join(messages)
    started, messages = pipeline.start(tmp_path, task="risk archive verifier", mode="B")
    assert started, "\n".join(messages)
    _bind_managed_run(tmp_path)
    for mutation in ("tampered", "missing", "wrong-mode"):
        if mutation == "tampered":
            risk_artifact.write_bytes(b"{}")
        elif mutation == "missing":
            risk_artifact.unlink()
        else:
            risk_artifact.chmod(0o644)
        valid, validation_messages = pipeline.validate(tmp_path, strict=True)
        assert not valid
        assert any(
            "run_archives[0]" in message and "accepted-risk evidence" in message
            for message in validation_messages
        )
        risk_artifact.write_bytes(risk_bytes)
        risk_artifact.chmod(0o600)
        assert pipeline.validate(tmp_path, strict=True)[0]


def test_managed_evidence_rejects_oversized_tamper_before_unbounded_read(
    tmp_path, payload, monkeypatch
):
    _start_v2(payload, tmp_path)
    workflow = pipeline._current_workflow_definition()
    snapshot = _read_snap(tmp_path)
    gates = tuple(snapshot["ordered_gates"])
    owners = {gate: workflow.gates[gate].stage for gate in gates}
    workspace, manager = _managed_workspace(tmp_path)
    managed, error = pipeline.bind_managed_execution(
        tmp_path,
        workflow_id=workflow.id,
        workflow_schema_version=workflow.schema_version,
        workflow_definition_digest=pipeline._current_workflow_identity()[2],
        mode="B",
        ordered_gates=gates,
        gate_definition_digest=snapshot["gate_definition_digest"],
        gate_owner_stages=owners,
        workspace=workspace,
    )
    assert error is None and managed is not None
    _finish_managed_stage(tmp_path, manager, stage=owners[gates[0]])
    snapshot = _read_snap(tmp_path)
    record = next(
        item
        for item in snapshot["stage_history"]
        if item["stage"] == owners[gates[0]] and item["status"] == "succeeded"
    )
    evidence_path = record["evidence_records"][0]["artifact_path"]
    with (tmp_path / evidence_path).open("r+b") as handle:
        handle.truncate(32 * 1024 * 1024)

    original_read_bytes = ProjectFS.read_bytes

    def guarded_read_bytes(self, relative):
        if self.relpath(relative) == evidence_path:
            raise AssertionError("oversized evidence reached unbounded read_bytes")
        return original_read_bytes(self, relative)

    monkeypatch.setattr(ProjectFS, "read_bytes", guarded_read_bytes)
    valid, messages = pipeline.validate(tmp_path, strict=True)
    assert not valid
    assert "safety limit" in "\n".join(messages)


def test_managed_not_applicable_rejects_successful_owner_and_true_predicate(
    tmp_path, payload
):
    _start_v2(payload, tmp_path)
    workflow = pipeline._current_workflow_definition()
    snapshot = _read_snap(tmp_path)
    gates = tuple(snapshot["ordered_gates"])
    definitions = pipeline.installed_gate_definitions(tmp_path)
    conditional_gate = next(
        gate for gate in gates if definitions[gate].requirement == "conditional"
    )
    preceding = gates[: gates.index(conditional_gate)]
    owners = {gate: workflow.gates[gate].stage for gate in gates}
    workspace, manager = _managed_workspace(tmp_path)
    managed, error = pipeline.bind_managed_execution(
        tmp_path,
        workflow_id=workflow.id,
        workflow_schema_version=workflow.schema_version,
        workflow_definition_digest=pipeline._current_workflow_identity()[2],
        mode="B",
        ordered_gates=gates,
        gate_definition_digest=snapshot["gate_definition_digest"],
        gate_owner_stages=owners,
        workspace=workspace,
    )
    assert error is None and managed is not None

    for owner in dict.fromkeys(owners[gate] for gate in preceding):
        _finish_managed_stage(tmp_path, manager, stage=owner)
    _record_findings(tmp_path)
    evidence = tmp_path / "managed-gate.txt"
    evidence.write_text("named owner verified\n", encoding="utf-8")
    for gate in preceding:
        closed, close_messages = pipeline.close_gate(tmp_path, gate, evidence)
        assert closed, "\n".join(close_messages)

    condition = definitions[conditional_gate].skip_conditions[0]
    skipped, skip_messages = pipeline.not_applicable(
        tmp_path,
        conditional_gate,
        condition=condition,
        reason="canonical condition is evidenced",
        evidence=evidence,
    )
    assert not skipped
    assert "owner stage" in "\n".join(skip_messages)

    frozen, freeze_error = pipeline.bind_workflow_condition_decisions(
        tmp_path, {"api-contract-surface-present": True}
    )
    assert freeze_error is None and frozen is not None
    _finish_managed_stage(tmp_path, manager, stage=owners[conditional_gate])
    _record_findings(tmp_path)
    skipped, skip_messages = pipeline.not_applicable(
        tmp_path,
        conditional_gate,
        condition=condition,
        reason="canonical condition is evidenced",
        evidence=evidence,
    )
    assert not skipped
    assert "requires frozen 'api-contract-surface-present'=false" in "\n".join(
        skip_messages
    )
    assert pipeline.validate(tmp_path, strict=True)[0]

    # Reproduce a pre-fix contradictory ledger: a successful positive-predicate
    # owner must not become N/A merely because the frozen decision is flipped.
    contradictory = _read_snap(tmp_path)
    contradictory["condition_decisions"]["api-contract-surface-present"] = False
    snapshot_path = tmp_path / ".claude/state/pipeline-snapshot.json"
    snapshot_path.write_text(
        json.dumps(contradictory, indent=2) + "\n", encoding="utf-8"
    )
    skipped, skip_messages = pipeline.not_applicable(
        tmp_path,
        conditional_gate,
        condition=condition,
        reason="canonical condition is evidenced",
        evidence=evidence,
    )
    assert not skipped
    assert "owner stage" in "\n".join(skip_messages) and "succeeded" in "\n".join(
        skip_messages
    )
    valid, validation_messages = pipeline.validate(tmp_path, strict=True)
    assert not valid
    assert "frozen condition" in "\n".join(validation_messages)


def test_managed_skipped_owner_can_only_close_matching_not_applicable_gate(
    tmp_path, payload
):
    _start_v2(payload, tmp_path)
    workflow = pipeline._current_workflow_definition()
    snapshot = _read_snap(tmp_path)
    gates = tuple(snapshot["ordered_gates"])
    conditional_gate = "contract-clear"
    owners = {gate: workflow.gates[gate].stage for gate in gates}
    workspace, manager = _managed_workspace(tmp_path)
    managed, error = pipeline.bind_managed_execution(
        tmp_path,
        workflow_id=workflow.id,
        workflow_schema_version=workflow.schema_version,
        workflow_definition_digest=pipeline._current_workflow_identity()[2],
        mode="B",
        ordered_gates=gates,
        gate_definition_digest=snapshot["gate_definition_digest"],
        gate_owner_stages=owners,
        workspace=workspace,
    )
    assert error is None and managed is not None
    frozen, error = pipeline.bind_workflow_condition_decisions(
        tmp_path, {"api-contract-surface-present": False}
    )
    assert error is None and frozen is not None
    conditional_owner = owners[conditional_gate]
    owner_route = managed["active_stage_routes"][conditional_owner]
    owner_capabilities = tuple(managed["active_stage_requirements"][conditional_owner])
    claimed, claim_messages = pipeline.claim_stage(
        tmp_path,
        stage=conditional_owner,
        role=owner_route["role"],
        provider="claude",
        dispatch_id="contradictory-owner",
        attempt=1,
        required_capabilities=owner_capabilities,
        attested_capabilities=owner_capabilities,
    )
    assert not claimed
    assert "frozen condition" in "\n".join(claim_messages)
    _record_findings(tmp_path)
    evidence = tmp_path / "managed-gate.txt"
    evidence.write_text("verified\n", encoding="utf-8")

    completed_owners: set[str] = set()
    for gate in gates[: gates.index(conditional_gate)]:
        owner = owners[gate]
        if owner not in completed_owners:
            _finish_managed_stage(tmp_path, manager, stage=owner)
            completed_owners.add(owner)
        closed, messages = pipeline.close_gate(tmp_path, gate, evidence)
        assert closed, "\n".join(messages)

    run = _read_snap(tmp_path)
    dependencies = tuple(
        run["managed_execution"]["active_stage_dependencies"][owners[conditional_gate]]
    )
    checkpoint = manager.checkpoint(str(run["run_id"]), "managed-workflow")
    attested, messages = pipeline.attest_skipped_stage(
        tmp_path,
        stage=owners[conditional_gate],
        condition="api-contract-surface-present",
        dependencies=dependencies,
        dependency_states={dependency: "succeeded" for dependency in dependencies},
        workspace_checkpoint=checkpoint.to_dict(),
    )
    assert attested, "\n".join(messages)
    passed, messages = pipeline.close_gate(tmp_path, conditional_gate, evidence)
    assert not passed and "successful owner" in "\n".join(messages)
    skipped, messages = pipeline.not_applicable(
        tmp_path,
        conditional_gate,
        condition="no-api-contract-surface",
        reason="the frozen API surface decision is false",
        evidence=evidence,
    )
    assert skipped, "\n".join(messages)
    entry = _read_snap(tmp_path)["gate_history"][-1]
    bundle = tmp_path / entry["condition_evidence_path"]
    bundle_document = json.loads(bundle.read_text(encoding="utf-8"))
    assert bundle_document["owner"]["kind"] == "skipped"
    assert (
        entry["owner_skip_attestation_sha256"]
        == (bundle_document["owner"]["attestation_sha256"])
    )
    assert pipeline.skipped_stage_ids(tmp_path)[0] == {owners[conditional_gate]}
    from claude_kit.workflow_executor import PipelineStageLedger

    join_stage = workflow.stage_by_id["api-tests"]
    join_stage = type(join_stage)(
        join_stage.id,
        join_stage.phase,
        join_stage.route,
        (owners[conditional_gate],),
        join_stage.parallel_group,
        join_stage.condition,
        join_stage.gates,
        join_stage.retry_budget,
        join_stage.evidence,
        join_stage.required_capabilities,
    )
    handoff = PipelineStageLedger(tmp_path).dependency_context(join_stage)
    assert "durably skipped" in handoff
    assert "api-contract-surface-present" in handoff
    assert pipeline.validate(tmp_path, strict=True)[0]


def test_managed_workflow_route_or_condition_digest_drift_blocks_resume(
    tmp_path, payload, monkeypatch
):
    _start_v2(payload, tmp_path)
    workflow = pipeline._current_workflow_definition()
    snapshot = _read_snap(tmp_path)
    gates = tuple(snapshot["ordered_gates"])
    identity = pipeline._current_workflow_identity()
    workspace, _manager = _managed_workspace(tmp_path)
    managed, error = pipeline.bind_managed_execution(
        tmp_path,
        workflow_id=identity[0],
        workflow_schema_version=identity[1],
        workflow_definition_digest=identity[2],
        mode="B",
        ordered_gates=gates,
        gate_definition_digest=snapshot["gate_definition_digest"],
        gate_owner_stages={gate: workflow.gates[gate].stage for gate in gates},
        workspace=workspace,
    )
    assert error is None and managed is not None
    monkeypatch.setattr(
        pipeline,
        "_current_workflow_identity",
        lambda: (identity[0], identity[1], "0" * 64),
    )

    claimed, messages = pipeline.claim_stage(
        tmp_path,
        stage="classify",
        role="orchestrator",
        provider="codex",
        dispatch_id="drifted-workflow",
        attempt=1,
        required_capabilities=("filesystem.read",),
        attested_capabilities=("filesystem.read",),
    )
    assert not claimed
    assert "workflow definition digest changed" in messages[0]


def test_managed_binding_derives_gate_owners_and_claim_contract_atomically(
    tmp_path, payload
):
    _start_v2(payload, tmp_path)
    workflow = pipeline._current_workflow_definition()
    snapshot = _read_snap(tmp_path)
    gates = tuple(snapshot["ordered_gates"])
    owners = {gate: workflow.gates[gate].stage for gate in gates}
    workspace, manager = _managed_workspace(tmp_path)

    forged_owners = dict(owners)
    forged_owners[gates[-1]] = "classify"
    rejected, error = pipeline.bind_managed_execution(
        tmp_path,
        workflow_id=workflow.id,
        workflow_schema_version=workflow.schema_version,
        workflow_definition_digest=pipeline._current_workflow_identity()[2],
        mode="B",
        ordered_gates=gates,
        gate_definition_digest=snapshot["gate_definition_digest"],
        gate_owner_stages=forged_owners,
        workspace=workspace,
    )
    assert rejected is None
    assert error is not None and "canonical mode policy" in error

    managed, error = pipeline.bind_managed_execution(
        tmp_path,
        workflow_id=workflow.id,
        workflow_schema_version=workflow.schema_version,
        workflow_definition_digest=pipeline._current_workflow_identity()[2],
        mode="B",
        ordered_gates=gates,
        gate_definition_digest=snapshot["gate_definition_digest"],
        gate_owner_stages=owners,
        workspace=workspace,
    )
    assert error is None and managed is not None
    shell_roles = [
        capabilities
        for capabilities in managed["active_stage_requirements"].values()
        if "shell" in capabilities
    ]
    assert shell_roles
    assert all(
        "process.descendant_containment" in capabilities for capabilities in shell_roles
    )
    classify_caps = tuple(managed["active_stage_requirements"]["classify"])
    classify_role = managed["active_stage_routes"]["classify"]["role"]

    for mutation, expected in (
        ({"role": "developer"}, "frozen canonical role"),
        ({"required_capabilities": ()}, "capabilities differ"),
        ({"provider": "codex"}, "frozen managed provider set"),
    ):
        values = {
            "stage": "classify",
            "role": classify_role,
            "provider": "claude",
            "dispatch_id": "forged-classify",
            "attempt": 1,
            "required_capabilities": classify_caps,
            "attested_capabilities": classify_caps,
        }
        values.update(mutation)
        claimed, messages = pipeline.claim_stage(tmp_path, **values)
        assert not claimed
        assert expected in "\n".join(messages)

    specification_caps = tuple(managed["active_stage_requirements"]["specification"])
    claimed, messages = pipeline.claim_stage(
        tmp_path,
        stage="specification",
        role=managed["active_stage_routes"]["specification"]["role"],
        provider="claude",
        dispatch_id="early-specification",
        attempt=1,
        required_capabilities=specification_caps,
        attested_capabilities=specification_caps,
    )
    assert not claimed
    assert "dependency 'classify'" in "\n".join(messages)

    _finish_managed_stage(tmp_path, manager, stage="classify", provider="claude")
    claimed, messages = pipeline.claim_stage(
        tmp_path,
        stage="specification",
        role=managed["active_stage_routes"]["specification"]["role"],
        provider="claude",
        dispatch_id="ready-specification",
        attempt=1,
        required_capabilities=specification_caps,
        attested_capabilities=specification_caps,
    )
    assert claimed, "\n".join(messages)


def test_managed_provider_projection_drift_blocks_next_claim(tmp_path, payload):
    _start_v2(payload, tmp_path)
    workflow = pipeline._current_workflow_definition()
    snapshot = _read_snap(tmp_path)
    gates = tuple(snapshot["ordered_gates"])
    workspace, _manager = _managed_workspace(tmp_path)
    managed, error = pipeline.bind_managed_execution(
        tmp_path,
        workflow_id=workflow.id,
        workflow_schema_version=workflow.schema_version,
        workflow_definition_digest=pipeline._current_workflow_identity()[2],
        mode="B",
        ordered_gates=gates,
        gate_definition_digest=snapshot["gate_definition_digest"],
        gate_owner_stages={gate: workflow.gates[gate].stage for gate in gates},
        workspace=workspace,
    )
    assert error is None and managed is not None
    manifest = json.loads(
        (tmp_path / ".claude/config/init-options.json").read_text(encoding="utf-8")
    )
    provider_file = next(
        item["path"] for item in manifest["files"] if item["provider"] == "claude"
    )
    path = tmp_path / provider_file
    path.write_bytes(path.read_bytes() + b"\nprovider projection drift\n")

    claimed, messages = pipeline.claim_stage(
        tmp_path,
        stage="classify",
        role=managed["active_stage_routes"]["classify"]["role"],
        provider="claude",
        dispatch_id="projection-drift",
        attempt=1,
        required_capabilities=tuple(managed["active_stage_requirements"]["classify"]),
        attested_capabilities=tuple(managed["active_stage_requirements"]["classify"]),
    )
    assert not claimed
    assert "provider projection changed" in "\n".join(messages)


def test_managed_worker_controls_are_frozen_but_mutable_context_is_not(
    tmp_path, payload
):
    selection = catalog.defaults(payload)
    selection.detect_commands = False
    plan = catalog.resolve(payload, selection)
    install_runtime(
        payload,
        tmp_path,
        plan,
        InstallRequest(selection=selection, runtime=Runtime.CLAUDE),
    )
    _init_git_repo(tmp_path)
    started, messages = pipeline.start(tmp_path, task="test run", mode="B")
    assert started, "\n".join(messages)
    _record_findings(tmp_path)
    workflow = pipeline._current_workflow_definition()
    snapshot, snapshot_error = pipeline.snapshot_document(tmp_path)
    assert snapshot_error is None and snapshot is not None
    gates = tuple(snapshot["ordered_gates"])
    workspace, _manager = _managed_workspace(tmp_path)
    managed, error = pipeline.bind_managed_execution(
        tmp_path,
        workflow_id=workflow.id,
        workflow_schema_version=workflow.schema_version,
        workflow_definition_digest=pipeline._current_workflow_identity()[2],
        mode="B",
        ordered_gates=gates,
        gate_definition_digest=snapshot["gate_definition_digest"],
        gate_owner_stages={gate: workflow.gates[gate].stage for gate in gates},
        workspace=workspace,
    )
    assert error is None and managed is not None
    layout = detect_state_layout(tmp_path)
    manifest = json.loads((tmp_path / layout.manifest).read_text(encoding="utf-8"))
    provider_path = next(
        item["path"] for item in manifest["files"] if item["provider"] == "claude"
    )
    worker_path = tmp_path / workspace["target_path"] / provider_path
    original = worker_path.read_bytes()
    worker_path.write_bytes(original + b"\nworker control rewrite\n")
    role = managed["active_stage_routes"]["classify"]["role"]
    capabilities = tuple(managed["active_stage_requirements"]["classify"])

    claimed, messages = pipeline.claim_stage(
        tmp_path,
        stage="classify",
        role=role,
        provider="claude",
        dispatch_id="worker-control-drift",
        attempt=1,
        required_capabilities=capabilities,
        attested_capabilities=capabilities,
    )
    assert not claimed
    assert "workspace provider control surface changed" in "\n".join(messages)

    worker_path.write_bytes(original)
    artifact_template_path = next(
        item["path"]
        for item in manifest["files"]
        if item["owner"] == "kit" and "/artifacts/templates/" in item["path"]
    )
    worker_template = tmp_path / workspace["target_path"] / artifact_template_path
    original_template = worker_template.read_bytes()
    worker_template.write_bytes(original_template + b"\nrewritten template\n")
    claimed, messages = pipeline.claim_stage(
        tmp_path,
        stage="classify",
        role=role,
        provider="claude",
        dispatch_id="artifact-template-drift",
        attempt=1,
        required_capabilities=capabilities,
        attested_capabilities=capabilities,
    )
    assert not claimed
    assert "workspace provider control surface changed" in "\n".join(messages)
    worker_template.write_bytes(original_template)

    mutable_path = next(
        item["path"]
        for item in manifest["files"]
        if item["path"].endswith("CONTINUITY.md") or "/agent-memory/" in item["path"]
    )
    source_mutable = tmp_path / mutable_path
    source_mutable.write_bytes(source_mutable.read_bytes() + b"\ncurrent context\n")
    claimed, messages = pipeline.claim_stage(
        tmp_path,
        stage="classify",
        role=role,
        provider="claude",
        dispatch_id="mutable-context-update",
        attempt=1,
        required_capabilities=capabilities,
        attested_capabilities=capabilities,
    )
    assert claimed, "\n".join(messages)


def test_failed_managed_attempt_requires_exact_pre_tree_restore_before_retry(
    tmp_path, payload
):
    _start_v2(payload, tmp_path)
    workflow = pipeline._current_workflow_definition()
    snapshot = _read_snap(tmp_path)
    gates = tuple(snapshot["ordered_gates"])
    workspace, manager = _managed_workspace(tmp_path)
    managed, error = pipeline.bind_managed_execution(
        tmp_path,
        workflow_id=workflow.id,
        workflow_schema_version=workflow.schema_version,
        workflow_definition_digest=pipeline._current_workflow_identity()[2],
        mode="B",
        ordered_gates=gates,
        gate_definition_digest=snapshot["gate_definition_digest"],
        gate_owner_stages={gate: workflow.gates[gate].stage for gate in gates},
        workspace=workspace,
    )
    assert error is None and managed is not None
    role = managed["active_stage_routes"]["classify"]["role"]
    capabilities = tuple(managed["active_stage_requirements"]["classify"])
    claim = {
        "stage": "classify",
        "role": role,
        "provider": "claude",
        "required_capabilities": capabilities,
        "attested_capabilities": capabilities,
    }
    claimed, messages = pipeline.claim_stage(
        tmp_path, dispatch_id="classify-failed", attempt=1, **claim
    )
    assert claimed, "\n".join(messages)

    worker = (tmp_path / workspace["target_path"]).resolve()
    escaped = worker / "out-of-scope.txt"
    escaped.write_text("must be remediated\n", encoding="utf-8")
    checkpoint = manager.checkpoint(str(snapshot["run_id"]), "managed-workflow")
    relative, artifact_sha = _write_managed_terminal_artifact(
        tmp_path,
        snapshot,
        stage="classify",
        dispatch_id="classify-failed",
        dispatch_attempt=1,
        status="failed",
        output=None,
        error="scope violation",
        evidence=(),
        evidence_records=(),
        workspace_checkpoint=checkpoint.to_dict(),
    )
    finished, messages = pipeline.finish_stage(
        tmp_path,
        stage="classify",
        dispatch_id="classify-failed",
        attempt=1,
        status="failed",
        output_path=relative,
        output_artifact_sha256=artifact_sha,
        workspace_checkpoint=checkpoint.to_dict(),
        error="scope violation",
    )
    assert finished, "\n".join(messages)

    retried, messages = pipeline.claim_stage(
        tmp_path, dispatch_id="classify-retry", attempt=2, **claim
    )
    assert not retried
    assert "restore its exact pre-attempt checkpoint" in "\n".join(messages)
    escaped.unlink()
    retried, messages = pipeline.claim_stage(
        tmp_path, dispatch_id="classify-retry", attempt=2, **claim
    )
    assert retried, "\n".join(messages)


def test_operator_can_reconcile_only_unchanged_side_effect_free_stale_attempt(
    tmp_path, payload
):
    selection = catalog.defaults(payload)
    selection.profile = "lean"
    selection.detect_commands = False
    plan = catalog.resolve(payload, selection)
    install_runtime(
        payload,
        tmp_path,
        plan,
        InstallRequest(selection=selection, runtime=Runtime.BOTH),
    )
    _init_git_repo(tmp_path)
    started, messages = pipeline.start(tmp_path, task="test run", mode="B")
    assert started, "\n".join(messages)
    _record_findings(tmp_path)
    workflow = pipeline._current_workflow_definition()
    snapshot, snapshot_error = pipeline.snapshot_document(tmp_path)
    assert snapshot_error is None and snapshot is not None
    gates = tuple(snapshot["ordered_gates"])
    workspace, manager = _managed_workspace(tmp_path)
    managed, error = pipeline.bind_managed_execution(
        tmp_path,
        workflow_id=workflow.id,
        workflow_schema_version=workflow.schema_version,
        workflow_definition_digest=pipeline._current_workflow_identity()[2],
        mode="B",
        ordered_gates=gates,
        gate_definition_digest=snapshot["gate_definition_digest"],
        gate_owner_stages={gate: workflow.gates[gate].stage for gate in gates},
        workspace=workspace,
    )
    assert error is None and managed is not None
    _record_findings(tmp_path)
    role = managed["active_stage_routes"]["classify"]["role"]
    capabilities = tuple(managed["active_stage_requirements"]["classify"])
    assert "shell" not in capabilities
    assert "filesystem.write" not in capabilities
    claimed, messages = pipeline.claim_stage(
        tmp_path,
        stage="classify",
        role=role,
        provider="codex",
        dispatch_id="unrecoverable-codex-classifier",
        attempt=1,
        required_capabilities=capabilities,
        attested_capabilities=capabilities,
    )
    assert claimed, "\n".join(messages)

    operator_evidence = tmp_path / "operator-recovery.json"
    operator_evidence.write_text(
        json.dumps(
            {
                "operator": "release-owner",
                "observation": "coordinator terminated before collecting the classifier",
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    reconciled, messages = pipeline.reconcile_stale_stage_attempt(
        tmp_path,
        stage="classify",
        dispatch_id="unrecoverable-codex-classifier",
        reconciled_by="release-owner",
        evidence=operator_evidence,
    )
    assert not reconciled
    assert "unsupported for this provider" in "\n".join(messages)

    checkpoint = manager.checkpoint(str(snapshot["run_id"]), "managed-workflow")
    cancelled_error = "coordinator retained control and cancelled the Codex process"
    codex_cancelled_relative, codex_cancelled_sha = _write_managed_terminal_artifact(
        tmp_path,
        snapshot,
        stage="classify",
        dispatch_id="unrecoverable-codex-classifier",
        dispatch_attempt=1,
        status="cancelled",
        output=None,
        error=cancelled_error,
        evidence=(),
        evidence_records=(),
        workspace_checkpoint=checkpoint.to_dict(),
    )
    finished, messages = pipeline.finish_stage(
        tmp_path,
        stage="classify",
        dispatch_id="unrecoverable-codex-classifier",
        attempt=1,
        status="cancelled",
        output_path=codex_cancelled_relative,
        output_artifact_sha256=codex_cancelled_sha,
        workspace_checkpoint=checkpoint.to_dict(),
        error=cancelled_error,
    )
    assert finished, "\n".join(messages)

    claimed, messages = pipeline.claim_stage(
        tmp_path,
        stage="classify",
        role=role,
        provider="claude",
        dispatch_id="crashed-classifier",
        attempt=2,
        required_capabilities=capabilities,
        attested_capabilities=capabilities,
    )
    assert claimed, "\n".join(messages)
    workspace_root = (tmp_path / workspace["target_path"]).resolve(strict=True)
    drift = workspace_root / "post-crash-drift.txt"
    drift.write_text("untrusted change after coordinator crash\n", encoding="utf-8")
    reconciled, messages = pipeline.reconcile_stale_stage_attempt(
        tmp_path,
        stage="classify",
        dispatch_id="crashed-classifier",
        reconciled_by="release-owner",
        evidence=operator_evidence,
    )
    assert not reconciled
    assert "workspace changed" in "\n".join(messages)
    drift.unlink()
    reconciled, messages = pipeline.reconcile_stale_stage_attempt(
        tmp_path,
        stage="classify",
        dispatch_id="crashed-classifier",
        reconciled_by="release-owner",
        evidence=operator_evidence,
    )
    assert reconciled, "\n".join(messages)
    updated, snapshot_error = pipeline.snapshot_document(tmp_path)
    assert snapshot_error is None and updated is not None
    record = next(
        item
        for item in updated["stage_history"]
        if item["dispatch_id"] == "crashed-classifier"
    )
    assert record["status"] == "cancelled"
    assert record["workspace_checkpoint"] == record["workspace_checkpoint_before"]
    assert record["reconciliation"]["reconciled_by"] == "release-owner"
    stored_evidence = tmp_path / record["reconciliation"]["evidence_path"]
    assert stored_evidence.is_file()
    assert (
        hashlib.sha256(stored_evidence.read_bytes()).hexdigest()
        == record["reconciliation"]["evidence_sha256"]
    )
    valid, messages = pipeline.validate(tmp_path, strict=True)
    assert valid, "\n".join(messages)
    with ExitStack() as stack:
        assert schemas.validate_doc(updated, "pipeline-snapshot", stack) == []

    retried, messages = pipeline.claim_stage(
        tmp_path,
        stage="classify",
        role=role,
        provider="codex",
        dispatch_id="classifier-retry",
        attempt=3,
        required_capabilities=capabilities,
        attested_capabilities=capabilities,
    )
    assert retried, "\n".join(messages)
    checkpoint = manager.checkpoint(str(snapshot["run_id"]), "managed-workflow")
    current, current_error = pipeline.snapshot_document(tmp_path)
    assert current_error is None and current is not None
    output, references, evidence_records = _managed_stage_result(
        tmp_path,
        current,
        stage="classify",
        dispatch_id="classifier-retry",
        attempt=3,
    )
    relative, artifact_sha = _write_managed_terminal_artifact(
        tmp_path,
        current,
        stage="classify",
        dispatch_id="classifier-retry",
        dispatch_attempt=3,
        status="succeeded",
        output=output,
        error=None,
        evidence=references,
        evidence_records=evidence_records,
        workspace_checkpoint=checkpoint.to_dict(),
    )
    finished, messages = pipeline.finish_stage(
        tmp_path,
        stage="classify",
        dispatch_id="classifier-retry",
        attempt=3,
        status="succeeded",
        output_sha256=hashlib.sha256(output.encode()).hexdigest(),
        output_path=relative,
        output_artifact_sha256=artifact_sha,
        workspace_checkpoint=checkpoint.to_dict(),
        evidence=references,
        evidence_records=evidence_records,
    )
    assert finished, "\n".join(messages)

    specification_role = managed["active_stage_routes"]["specification"]["role"]
    specification_caps = tuple(managed["active_stage_requirements"]["specification"])
    assert "shell" in specification_caps
    claimed, messages = pipeline.claim_stage(
        tmp_path,
        stage="specification",
        role=specification_role,
        provider="claude",
        dispatch_id="crashed-shell-stage",
        attempt=1,
        required_capabilities=specification_caps,
        attested_capabilities=specification_caps,
    )
    assert claimed, "\n".join(messages)
    reconciled, messages = pipeline.reconcile_stale_stage_attempt(
        tmp_path,
        stage="specification",
        dispatch_id="crashed-shell-stage",
        reconciled_by="release-owner",
        evidence=operator_evidence,
    )
    assert not reconciled
    assert "may have side effects" in "\n".join(messages)


def test_existing_schema_v2_without_execution_binding_fields_remains_readable(
    tmp_path, payload
):
    _start_v2(payload, tmp_path)
    path = tmp_path / ".claude/state/pipeline-snapshot.json"
    snapshot = _read_snap(tmp_path)
    snapshot.pop("selection_digest")
    snapshot.pop("stage_history")
    path.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")

    ok, messages = pipeline.validate(tmp_path, strict=True)

    assert ok, "\n".join(messages)
    assert pipeline.workflow_condition_decisions(tmp_path) == ({}, None)


def test_start_rereads_gate_policy_after_acquiring_project_lease(
    tmp_path, payload, monkeypatch
):
    _install_with_gate_metadata(payload, tmp_path, profile="lean")
    _init_git_repo(tmp_path)
    install_snapshot = _install_snapshot(tmp_path)
    original_write_lock = pipeline._pipeline_write_lock
    interleaved = []

    @contextmanager
    def policy_transaction_before_lease(fs, path, *, msgs=None):
        if not interleaved:
            interleaved.append(True)
            data = yaml.safe_load(install_snapshot.read_text(encoding="utf-8"))
            data["gates"] = list(reversed(data["gates"]))
            definitions = {
                gate: pipeline.GateDefinition.from_dict(data["gate_definitions"][gate])
                for gate in data["gates"]
            }
            data["gate_definition_digest"] = pipeline.digest_gate_definitions(
                data["gates"], definitions
            )
            install_snapshot.write_text(
                yaml.safe_dump(data, sort_keys=False), encoding="utf-8"
            )
        with original_write_lock(fs, path, msgs=msgs):
            yield

    monkeypatch.setattr(
        pipeline, "_pipeline_write_lock", policy_transaction_before_lease
    )

    ok, messages = pipeline.start(tmp_path, task="policy race")
    snapshot = _read_snap(tmp_path)

    assert ok, "\n".join(messages)
    assert interleaved
    assert snapshot["ordered_gates"] == ["build-green", "code-review"]
    assert snapshot["stage"] == "build-green"
    assert snapshot[
        "gate_definition_digest"
    ] == pipeline.installed_gate_definition_digest(tmp_path)
    assert pipeline.validate(tmp_path, strict=True)[0]


def test_start_placeholder_counts_are_visibly_unrecorded(tmp_path, payload):
    _start_v2(payload, tmp_path, record_clean=False)

    ok, messages = pipeline.status(tmp_path)
    snapshot = _read_snap(tmp_path)

    assert ok
    assert snapshot["open_findings"] == _findings()
    assert snapshot["findings_evidence"] is None
    assert any(
        "UNRECORDED" in message and "record-findings" in message for message in messages
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("critical", -1),
        ("high", True),
        ("medium", 1.5),
        ("low", "0"),
    ],
)
def test_record_findings_requires_exact_nonnegative_integer_counts(
    tmp_path, payload, field, value
):
    _start_v2(payload, tmp_path, record_clean=False)
    evidence = tmp_path / "findings.json"
    evidence.write_text("{}", encoding="utf-8")
    counts = _findings()
    counts[field] = value

    ok, messages = pipeline.record_findings(
        tmp_path,
        evidence=evidence,
        **counts,
    )

    assert not ok
    assert any("non-negative integer" in message for message in messages)
    assert _read_snap(tmp_path)["findings_evidence"] is None


def test_record_findings_refuses_no_run_terminal_and_external_evidence(
    tmp_path, payload
):
    _install_with_gate_metadata(payload, tmp_path)
    _init_git_repo(tmp_path)
    evidence = tmp_path / "findings.json"
    evidence.write_text("{}", encoding="utf-8")
    args = {**_findings(), "evidence": evidence}

    ok, messages = pipeline.record_findings(tmp_path, **args)
    assert not ok and any("start or adopt" in message for message in messages)

    assert pipeline.start(tmp_path, task="record findings guards")[0]
    outside = tmp_path.parent / f"{tmp_path.name}-findings.json"
    outside.write_text("{}", encoding="utf-8")
    ok, messages = pipeline.record_findings(tmp_path, **_findings(), evidence=outside)
    assert not ok and any("contained inside" in message for message in messages)

    assert pipeline.abort(tmp_path)[0]
    ok, messages = pipeline.record_findings(tmp_path, **args)
    assert not ok and any("terminal" in message for message in messages)


def test_record_findings_hash_drift_blocks_transition_until_rerecorded(
    tmp_path, payload
):
    _start_v2(payload, tmp_path, record_clean=False, profile="lean")
    report = _record_findings(tmp_path)
    gate_evidence = tmp_path / "gate.txt"
    gate_evidence.write_text("reviewed", encoding="utf-8")
    report.write_text('{"critical": 1}', encoding="utf-8")

    ok, messages = pipeline.close_gate(tmp_path, "code-review", gate_evidence)
    assert not ok and any(
        "findings evidence hash mismatch" in message for message in messages
    )

    _record_findings(tmp_path)
    ok, messages = pipeline.close_gate(tmp_path, "code-review", gate_evidence)
    assert ok, "\n".join(messages)


def test_fresh_run_cannot_begin_at_a_later_gate(tmp_path, payload):
    _start_v2(payload, tmp_path)
    ev = tmp_path / "review.txt"
    ev.write_text("approved", encoding="utf-8")
    ok, msgs = pipeline.close_gate(tmp_path, "code-review", ev)
    assert not ok
    assert any("next gate is 'spec-complete'" in m for m in msgs)


def test_adopt_records_historical_gates_reason_and_identity(tmp_path, payload):
    _install_with_gate_metadata(payload, tmp_path)
    _init_git_repo(tmp_path)
    ok, msgs = pipeline.adopt(
        tmp_path,
        task="adopt existing work",
        gate="code-review",
        reason="planning and EM review predated the ledger",
        adopted_by="release-manager",
        mode="B",
    )
    assert ok, "\n".join(msgs)
    snap = _read_snap(tmp_path)
    assert snap["start_type"] == "adopted"
    assert snap["stage"] == "code-review"
    assert snap["adoption"] == {
        "starting_gate": "code-review",
        "historical_gates": ["spec-complete", "em-approved"],
        "reason": "planning and EM review predated the ledger",
        "adopted_by": "release-manager",
    }
    assert any("ADOPTED" in m for m in pipeline.status(tmp_path)[1])


def test_adopt_requires_reason_and_identity(tmp_path, payload):
    _install_with_gate_metadata(payload, tmp_path)
    _init_git_repo(tmp_path)
    ok, msgs = pipeline.adopt(
        tmp_path,
        task="adopt",
        gate="code-review",
        reason=" ",
        adopted_by="release-manager",
    )
    assert not ok and any("reason" in m for m in msgs)
    ok, msgs = pipeline.adopt(
        tmp_path,
        task="adopt",
        gate="code-review",
        reason="already reviewed",
        adopted_by=" ",
    )
    assert not ok and any("identity" in m for m in msgs)


def test_future_schema_fails_strict_and_mutation(tmp_path, payload):
    _install_with_gate_metadata(payload, tmp_path)
    _write_snapshot(
        tmp_path,
        schema_version=999,
        task="future",
        stage="spec-complete",
        next="unknown",
    )
    ok, msgs = pipeline.validate(tmp_path, strict=True)
    assert not ok and any("unsupported future" in m for m in msgs)
    ev = tmp_path / "e.txt"
    ev.write_text("x", encoding="utf-8")
    ok, msgs = pipeline.close_gate(tmp_path, "spec-complete", ev)
    assert not ok and any("unsupported future" in m for m in msgs)


@pytest.mark.parametrize("version", [True, "1", 999])
def test_install_snapshot_unknown_or_malformed_schema_fails_lifecycle(
    tmp_path, payload, version
):
    _install_with_gate_metadata(payload, tmp_path)
    _init_git_repo(tmp_path)
    install_snapshot = _install_snapshot(tmp_path)
    data = yaml.safe_load(install_snapshot.read_text(encoding="utf-8"))
    data["schema_version"] = version
    install_snapshot.write_text(yaml.safe_dump(data), encoding="utf-8")

    ok, msgs = pipeline.start(tmp_path, task="must fail closed")

    assert not ok
    expected = "must be an integer" if version is True or version == "1" else "future"
    assert any(expected in item for item in msgs), msgs
    assert not (tmp_path / ".claude/state/pipeline-snapshot.json").exists()


def test_tampered_gate_policy_with_stale_persisted_digest_fails_closed(
    tmp_path, payload
):
    _start_v2(payload, tmp_path)
    install_snapshot = _install_snapshot(tmp_path)
    data = yaml.safe_load(install_snapshot.read_text(encoding="utf-8"))
    original_digest = data["gate_definition_digest"]
    data["gate_definitions"]["spec-complete"] = {
        "requirement": "conditional",
        "skippable": True,
        "skip_conditions": ["tampered-condition"],
    }
    data["gate_definition_digest"] = original_digest
    install_snapshot.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    evidence = tmp_path / "tampered.txt"
    evidence.write_text("not applicable", encoding="utf-8")

    ok, msgs = pipeline.not_applicable(
        tmp_path,
        "spec-complete",
        condition="tampered-condition",
        reason="must not trust stale digest",
        evidence=evidence,
    )

    assert not ok
    assert any("gate definition digest changed" in item for item in msgs), msgs
    valid, validation_msgs = pipeline.validate(tmp_path, strict=True)
    assert not valid
    assert any("semantically inconsistent" in item for item in validation_msgs)
    assert _read_snap(tmp_path)["gate_history"] == []


def test_legacy_v1_is_readable_but_requires_explicit_adoption_to_mutate(
    tmp_path, payload
):
    _install_with_gate_metadata(payload, tmp_path)
    _write_snapshot(
        tmp_path,
        schema=1,
        task="old run",
        stage="build",
        next="review",
        gate_history=[
            {
                "gate": "spec-complete",
                "status": "overridden",
                "evidence_path": "old.txt",
                "override": "legacy waiver",
            },
            {
                "gate": "em-approved",
                "status": "skipped",
                "reason": "legacy skip",
            },
        ],
    )
    (tmp_path / "old.txt").write_text("legacy", encoding="utf-8")
    ok, msgs = pipeline.validate(tmp_path)
    assert ok, "\n".join(msgs)
    joined = "\n".join(msgs)
    assert "legacy schema v1" in joined
    assert "legacy overridden" in joined
    assert "lacks structured condition evidence" in joined
    ev = tmp_path / "e.txt"
    ev.write_text("x", encoding="utf-8")
    ok, msgs = pipeline.close_gate(tmp_path, "code-review", ev)
    assert not ok and any("adopt" in m for m in msgs)


# --- accepted Medium risk; Critical and High are never waivable --------------------------------


def test_critical_and_high_cannot_be_forced(tmp_path, payload):
    for severity in ("critical", "high"):
        target = tmp_path / severity
        _start_v2(payload, target)
        _record_findings(target, **{severity: 1})
        ev = target / "e.txt"
        ev.write_text("x", encoding="utf-8")
        ok, msgs = pipeline.close_gate(
            target,
            "spec-complete",
            ev,
            force=True,
            override_reason="must never work",
        )
        assert not ok
        assert any(severity in m and "never" in m for m in msgs)


def test_medium_cannot_pass_normally_and_accept_risk_is_distinct(tmp_path, payload):
    commit = _start_v2(payload, tmp_path)
    _record_findings(tmp_path, medium=1, low=2, cosmetic=3)
    ev = tmp_path / "finding.md"
    ev.write_text("MED-7: retry latency remains high", encoding="utf-8")

    ok, msgs = pipeline.close_gate(tmp_path, "spec-complete", ev)
    assert not ok and any("medium=1" in m for m in msgs)
    ok, msgs = pipeline.accept_risk(
        tmp_path,
        "spec-complete",
        finding_id="MED-7",
        reason="bounded launch window",
        accepted_by="release-manager",
        owner="platform-team",
        ticket="ISSUE-77",
        revisit="before public launch",
        evidence=ev,
        compensating_control="alert at p95 > 500ms",
    )
    assert ok, "\n".join(msgs)
    snap = _read_snap(tmp_path)
    entry = snap["gate_history"][-1]
    risk = snap["accepted_risks"][-1]
    assert entry["status"] == "accepted-risk"
    assert "last_gate_passed" not in snap
    assert snap["last_gate_resolved"] == "spec-complete"
    assert risk["finding_id"] == "MED-7"
    assert risk["repository_commit"] == commit
    assert risk["affected_gate"] == "spec-complete"
    assert risk["ticket"] == "ISSUE-77"
    assert risk["compensating_control"]
    assert risk["finding_set_digest"] == snap["findings_evidence"]["finding_set_digest"]
    assert snap["findings_evidence"]["evidence_path"] == "findings-report.json"
    assert any("ACCEPTED RISK" in m for m in pipeline.status(tmp_path)[1])
    assert any("ACCEPTED RISK" in m for m in pipeline.validate(tmp_path)[1])


def test_accept_risk_requires_every_structured_field(tmp_path, payload):
    _start_v2(payload, tmp_path)
    _record_findings(tmp_path, medium=1)
    ev = tmp_path / "finding.md"
    ev.write_text("MED-1", encoding="utf-8")
    required = {
        "finding_id": "MED-1",
        "reason": "accepted",
        "accepted_by": "release-manager",
        "owner": "platform",
        "ticket": "ISSUE-1",
        "revisit": "2026-12-01",
    }
    for field in required:
        values = dict(required)
        values[field] = " "
        ok, msgs = pipeline.accept_risk(
            tmp_path, "spec-complete", evidence=ev, **values
        )
        assert not ok, field
        assert any(field.replace("_", " ") in m for m in msgs), (field, msgs)


def test_accept_risk_refuses_critical_or_high_findings(tmp_path, payload):
    _start_v2(payload, tmp_path)
    _record_findings(tmp_path, high=1, medium=1)
    ev = tmp_path / "finding.md"
    ev.write_text("MED-1", encoding="utf-8")
    ok, msgs = pipeline.accept_risk(
        tmp_path,
        "spec-complete",
        finding_id="MED-1",
        reason="accepted",
        accepted_by="release-manager",
        owner="platform",
        ticket="ISSUE-1",
        revisit="next release",
        evidence=ev,
    )
    assert not ok and any("high" in m and "never" in m for m in msgs)


def test_accepted_risk_invalid_after_commit_or_evidence_change(tmp_path, payload):
    _start_v2(payload, tmp_path)
    _record_findings(tmp_path, medium=1)
    ev = tmp_path / "finding.md"
    ev.write_text("MED-1 original", encoding="utf-8")
    assert pipeline.accept_risk(
        tmp_path,
        "spec-complete",
        finding_id="MED-1",
        reason="accepted",
        accepted_by="release-manager",
        owner="platform",
        ticket="ISSUE-1",
        revisit="next release",
        evidence=ev,
    )[0]
    ev.write_text("MED-1 changed", encoding="utf-8")
    ok, msgs = pipeline.validate(tmp_path)
    assert not ok and any("accepted-risk evidence hash mismatch" in m for m in msgs)

    # Restore the evidence, then move HEAD: the same acceptance may not follow a new commit.
    ev.write_text("MED-1 original", encoding="utf-8")
    (tmp_path / ".pipeline-audit-root").write_text("changed\n", encoding="utf-8")
    subprocess.run(["git", "add", ".pipeline-audit-root"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-m", "move head"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    ok, msgs = pipeline.validate(tmp_path)
    assert not ok and any("accepted risk belongs to commit" in m for m in msgs)


# --- structured not-applicable -----------------------------------------------------------------


def test_required_gates_cannot_be_marked_not_applicable(tmp_path, payload):
    _start_v2(payload, tmp_path)
    ev = tmp_path / "scope.txt"
    ev.write_text("docs only", encoding="utf-8")
    ok, msgs = pipeline.not_applicable(
        tmp_path,
        "spec-complete",
        condition="docs-only",
        reason="docs only",
        evidence=ev,
    )
    assert not ok and any("required" in m and "cannot" in m for m in msgs)


def test_configured_conditional_gate_can_be_not_applicable(tmp_path, payload):
    _start_v2(payload, tmp_path)
    ev = tmp_path / "e.txt"
    ev.write_text("verified", encoding="utf-8")
    for gate in ("spec-complete", "em-approved", "code-review", "build-green"):
        assert pipeline.close_gate(tmp_path, gate, ev)[0]
    condition_evidence = tmp_path / "contract-surface.txt"
    condition_evidence.write_text("no OpenAPI or public routes", encoding="utf-8")
    ok, msgs = pipeline.not_applicable(
        tmp_path,
        "contract-clear",
        condition="no-api-contract-surface",
        reason="repository has no API contract surface",
        evidence=condition_evidence,
    )
    assert ok, "\n".join(msgs)
    entry = _read_snap(tmp_path)["gate_history"][-1]
    assert entry["status"] == "not-applicable"
    assert entry["condition"] == "no-api-contract-surface"
    assert entry["condition_evidence_sha256"]
    assert entry["repository_commit"]


@pytest.mark.parametrize("severity", ["critical", "high", "medium"])
def test_not_applicable_cannot_bypass_blocking_findings(tmp_path, payload, severity):
    _start_v2(payload, tmp_path)
    evidence = tmp_path / "e.txt"
    evidence.write_text("verified", encoding="utf-8")
    for gate in ("spec-complete", "em-approved", "code-review", "build-green"):
        assert pipeline.close_gate(tmp_path, gate, evidence)[0]
    _record_findings(tmp_path, **{severity: 1})

    ok, msgs = pipeline.not_applicable(
        tmp_path,
        "contract-clear",
        condition="no-api-contract-surface",
        reason="repository has no API contract surface",
        evidence=evidence,
    )

    assert not ok
    assert any(
        "blocking findings remain" in item and f"{severity}=1" in item for item in msgs
    )
    assert _read_snap(tmp_path)["stage"] == "contract-clear"


def test_not_applicable_rejects_unknown_condition_and_missing_inputs(tmp_path, payload):
    _start_v2(payload, tmp_path)
    ev = tmp_path / "e.txt"
    ev.write_text("verified", encoding="utf-8")
    ok, msgs = pipeline.not_applicable(
        tmp_path,
        "contract-clear",
        condition="made-up",
        reason="not applicable",
        evidence=ev,
    )
    assert not ok and any("unknown condition" in m for m in msgs)
    ok, msgs = pipeline.not_applicable(
        tmp_path,
        "contract-clear",
        condition="no-api-contract-surface",
        reason=" ",
        evidence=ev,
    )
    assert not ok and any("reason" in m for m in msgs)
    ok, msgs = pipeline.not_applicable(
        tmp_path,
        "contract-clear",
        condition="no-api-contract-surface",
        reason="not applicable",
        evidence=tmp_path / "missing.txt",
    )
    assert not ok and any("evidence file not found" in m for m in msgs)


def test_not_applicable_still_enforces_order(tmp_path, payload):
    _start_v2(payload, tmp_path)
    ev = tmp_path / "e.txt"
    ev.write_text("verified", encoding="utf-8")
    ok, msgs = pipeline.not_applicable(
        tmp_path,
        "contract-clear",
        condition="no-api-contract-surface",
        reason="not applicable",
        evidence=ev,
    )
    assert not ok and any("next gate is 'spec-complete'" in m for m in msgs)


# --- lifecycle terminal states -----------------------------------------------------------------


def test_complete_requires_every_gate_and_terminal_runs_cannot_continue(
    tmp_path, payload
):
    _start_v2(payload, tmp_path, profile="lean")
    ok, msgs = pipeline.complete(tmp_path)
    assert not ok and any("unresolved gates" in m for m in msgs)
    ev = tmp_path / "e.txt"
    ev.write_text("verified", encoding="utf-8")
    assert pipeline.close_gate(tmp_path, "code-review", ev)[0]
    assert pipeline.close_gate(tmp_path, "build-green", ev)[0]
    assert pipeline.complete(tmp_path)[0]
    snap = _read_snap(tmp_path)
    assert snap["status"] == "completed" and snap["stage"] == "completed"
    ok, msgs = pipeline.close_gate(tmp_path, "build-green", ev)
    assert not ok and any("completed" in m for m in msgs)


def test_terminal_run_is_archived_before_the_next_run_starts(tmp_path, payload):
    _start_v2(payload, tmp_path, profile="lean")
    evidence = tmp_path / "gate.txt"
    evidence.write_text("verified", encoding="utf-8")
    assert pipeline.close_gate(tmp_path, "code-review", evidence)[0]
    assert pipeline.close_gate(tmp_path, "build-green", evidence)[0]
    assert pipeline.complete(tmp_path)[0]
    completed = _read_snap(tmp_path)
    (tmp_path / ".pipeline-audit-root").write_text(
        "unrelated post-completion commit\n", encoding="utf-8"
    )
    subprocess.run(["git", "add", ".pipeline-audit-root"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-m", "post-completion work"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "switch", "-c", "terminal-next"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    install_snapshot = _install_snapshot(tmp_path)
    install_data = yaml.safe_load(install_snapshot.read_text(encoding="utf-8"))
    install_data["selection"]["profile"] = "standard"
    install_data["gates"] = list(reversed(install_data["gates"]))
    new_definitions = {
        gate: pipeline.GateDefinition.from_dict(install_data["gate_definitions"][gate])
        for gate in install_data["gates"]
    }
    install_data["gate_definition_digest"] = pipeline.digest_gate_definitions(
        install_data["gates"], new_definitions
    )
    install_snapshot.write_text(
        yaml.safe_dump(install_data, sort_keys=False), encoding="utf-8"
    )

    ok, messages = pipeline.start(tmp_path, task="second run")
    assert ok, "\n".join(messages)
    assert any("archived terminal pipeline run" in message for message in messages)
    second = _read_snap(tmp_path)
    assert second["run_id"] != completed["run_id"]
    assert second["branch"] == "terminal-next"
    assert second["profile"] == "standard"
    assert second["ordered_gates"] == ["build-green", "code-review"]
    assert second["stage"] == "build-green"
    assert len(second["run_archives"]) == 1
    first_archive = second["run_archives"][0]
    assert first_archive["snapshot"] == completed
    assert first_archive["snapshot_sha256"] == pipeline._document_sha256(completed)
    assert pipeline.validate(tmp_path, strict=True)[0]

    _record_findings(tmp_path)
    (tmp_path / ".pipeline-audit-root").write_text(
        "commit after findings before abort\n", encoding="utf-8"
    )
    subprocess.run(["git", "add", ".pipeline-audit-root"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-m", "abandoned work"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    assert pipeline.abort(tmp_path)[0]
    aborted = _read_snap(tmp_path)
    assert pipeline.validate(tmp_path, strict=True)[0]
    ok, messages = pipeline.start(tmp_path, task="third run")
    assert ok, "\n".join(messages)
    third = _read_snap(tmp_path)
    assert len(third["run_archives"]) == 2
    assert third["run_archives"][1]["snapshot"] == {
        key: value for key, value in aborted.items() if key != "run_archives"
    }
    assert all(
        "run_archives" not in archive["snapshot"] for archive in third["run_archives"]
    )
    assert pipeline.validate(tmp_path, strict=True)[0]


def test_validate_enforces_terminal_state_and_exact_final_summary(tmp_path, payload):
    _start_v2(payload, tmp_path, profile="lean")
    evidence = tmp_path / "gate.txt"
    evidence.write_text("verified", encoding="utf-8")
    assert pipeline.close_gate(tmp_path, "code-review", evidence)[0]
    assert pipeline.close_gate(tmp_path, "build-green", evidence)[0]
    assert pipeline.complete(tmp_path)[0]
    valid = _read_snap(tmp_path)

    mutations = []
    wrong_stage = json.loads(json.dumps(valid))
    wrong_stage["stage"] = "code-review"
    mutations.append((wrong_stage, "stage 'completed'"))
    no_timestamp = json.loads(json.dumps(valid))
    no_timestamp.pop("completed_at")
    mutations.append((no_timestamp, "completed_at"))
    unresolved = json.loads(json.dumps(valid))
    unresolved["gate_history"].pop()
    mutations.append((unresolved, "unresolved gates"))
    fabricated_summary = json.loads(json.dumps(valid))
    fabricated_summary["final_summary"]["run_id"] = "fabricated"
    mutations.append((fabricated_summary, "deterministic terminal evidence projection"))

    snapshot_path = tmp_path / pipeline.SNAPSHOT_REL
    for document, expected in mutations:
        snapshot_path.write_text(json.dumps(document), encoding="utf-8")
        ok, messages = pipeline.validate(tmp_path, strict=True)
        assert not ok
        assert any(expected in message for message in messages), messages

    active_with_terminal_fields = json.loads(json.dumps(valid))
    active_with_terminal_fields["status"] = "active"
    active_with_terminal_fields["stage"] = "ready-to-complete"
    snapshot_path.write_text(json.dumps(active_with_terminal_fields), encoding="utf-8")
    ok, messages = pipeline.validate(tmp_path, strict=True)
    assert not ok
    assert any("must not retain terminal field" in message for message in messages)

    aborted_without_timestamp = json.loads(json.dumps(valid))
    aborted_without_timestamp["status"] = "aborted"
    aborted_without_timestamp["stage"] = "aborted"
    aborted_without_timestamp.pop("completed_at")
    aborted_without_timestamp.pop("final_summary")
    snapshot_path.write_text(json.dumps(aborted_without_timestamp), encoding="utf-8")
    ok, messages = pipeline.validate(tmp_path, strict=True)
    assert not ok
    assert any("aborted_at" in message for message in messages)


@pytest.mark.parametrize("severity", ["critical", "high"])
def test_complete_rejects_never_waivable_findings_added_after_last_gate(
    tmp_path, payload, severity
):
    _start_v2(payload, tmp_path, profile="lean")
    evidence = tmp_path / "e.txt"
    evidence.write_text("verified", encoding="utf-8")
    assert pipeline.close_gate(tmp_path, "code-review", evidence)[0]
    assert pipeline.close_gate(tmp_path, "build-green", evidence)[0]
    _record_findings(tmp_path, **{severity: 1})

    ok, msgs = pipeline.complete(tmp_path)

    assert not ok
    assert any(f"{severity}=1" in item and "never waivable" in item for item in msgs)
    assert _read_snap(tmp_path)["status"] == "active"


def test_complete_rejects_unaccepted_medium_added_after_last_gate(tmp_path, payload):
    _start_v2(payload, tmp_path, profile="lean")
    evidence = tmp_path / "e.txt"
    evidence.write_text("verified", encoding="utf-8")
    assert pipeline.close_gate(tmp_path, "code-review", evidence)[0]
    assert pipeline.close_gate(tmp_path, "build-green", evidence)[0]
    _record_findings(tmp_path, medium=1)

    ok, msgs = pipeline.complete(tmp_path)

    assert not ok
    assert any("exact current findings" in item for item in msgs)
    assert _read_snap(tmp_path)["status"] == "active"


def test_resume_surfaces_adoption_and_refuses_terminal_runs(tmp_path, payload):
    _start_v2(payload, tmp_path, profile="lean")
    assert pipeline.resume(tmp_path)[0]
    assert pipeline.abort(tmp_path)[0]
    ok, msgs = pipeline.resume(tmp_path)
    assert not ok and any("aborted" in m for m in msgs)


def test_adopt_transactionally_migrates_and_preserves_a_legacy_v1_snapshot(
    tmp_path, payload
):
    _install_with_gate_metadata(payload, tmp_path)
    legacy = _legacy_coherent()
    legacy["gate_history"] = [
        {
            "gate": "code-review",
            "status": "overridden",
            "evidence_path": "legacy-review.txt",
            "override": "pre-v2 waiver",
        }
    ]
    (tmp_path / "legacy-review.txt").write_text("legacy", encoding="utf-8")
    _write_snapshot(tmp_path, **legacy)
    _init_git_repo(tmp_path)

    ok, msgs = pipeline.adopt(
        tmp_path,
        task="migrate legacy run",
        gate="build-green",
        reason="explicitly migrate pre-v2 work",
        adopted_by="release-manager",
    )
    assert ok, "\n".join(msgs)
    migrated = _read_snap(tmp_path)
    assert migrated["schema_version"] == 2
    assert migrated["start_type"] == "adopted"
    assert migrated["legacy_migration"]["legacy_snapshot"] == legacy
    assert len(migrated["legacy_migration"]["legacy_snapshot_sha256"]) == 64


def test_accepted_risk_binds_gate_finding_identity_and_count(tmp_path, payload):
    _start_v2(payload, tmp_path)
    _record_findings(tmp_path, medium=1)
    evidence = tmp_path / "finding.md"
    evidence.write_text("MED-1", encoding="utf-8")
    kwargs = {
        "finding_id": "MED-1",
        "reason": "bounded",
        "accepted_by": "release-manager",
        "owner": "platform",
        "ticket": "ISSUE-1",
        "revisit": "next release",
        "evidence": evidence,
    }
    assert pipeline.accept_risk(tmp_path, "spec-complete", **kwargs)[0]
    original = _read_snap(tmp_path)

    tampered = json.loads(json.dumps(original))
    tampered["accepted_risks"][0]["affected_gate"] = "em-approved"
    _write_snapshot(tmp_path, **tampered)
    ok, msgs = pipeline.validate(tmp_path)
    assert not ok and any("identity/gate binding" in m for m in msgs)

    tampered = json.loads(json.dumps(original))
    tampered["accepted_risks"][0]["finding_id"] = "MED-OTHER"
    _write_snapshot(tmp_path, **tampered)
    ok, msgs = pipeline.validate(tmp_path)
    assert not ok and any("identity/gate binding" in m for m in msgs)

    tampered = json.loads(json.dumps(original))
    tampered["open_findings"]["medium"] = 2
    _write_snapshot(tmp_path, **tampered)
    ok, msgs = pipeline.validate(tmp_path)
    assert not ok and any("finding count changed" in m for m in msgs)


def test_validate_rejects_boolean_accepted_risk_finding_count(tmp_path, payload):
    _start_v2(payload, tmp_path)
    _record_findings(tmp_path, medium=1)
    evidence = tmp_path / "finding.md"
    evidence.write_text("MED-BOOL", encoding="utf-8")
    assert pipeline.accept_risk(
        tmp_path,
        "spec-complete",
        finding_id="MED-BOOL",
        reason="bounded",
        accepted_by="release-manager",
        owner="platform",
        ticket="ISSUE-BOOL",
        revisit="next release",
        evidence=evidence,
    )[0]
    document = _read_snap(tmp_path)
    risk = document["accepted_risks"][0]
    risk["medium_finding_count"] = True
    fingerprint = pipeline._risk_fingerprint(
        finding_id=risk["finding_id"],
        affected_gate=risk["affected_gate"],
        evidence_sha256=risk["evidence_sha256"],
        medium_finding_count=True,
        finding_set_digest=risk["finding_set_digest"],
        gate_definition_digest=risk["gate_definition_digest"],
        repository_commit=risk["repository_commit"],
    )
    risk["risk_id"] = fingerprint
    risk["finding_fingerprint"] = fingerprint
    document["gate_history"][0]["accepted_risk_ids"] = [fingerprint]
    (tmp_path / pipeline.SNAPSHOT_REL).write_text(
        json.dumps(document), encoding="utf-8"
    )

    ok, messages = pipeline.validate(tmp_path, strict=True)

    assert not ok
    assert any("positive integer" in message for message in messages), messages


def test_accept_risk_refresh_rebinds_commit_evidence_identity_and_count(
    tmp_path, payload
):
    _start_v2(payload, tmp_path)
    _record_findings(tmp_path, medium=1)
    evidence = tmp_path / "finding.md"
    evidence.write_text("MED-1 original", encoding="utf-8")

    def accept(finding_id, evidence_path=evidence, **extra):
        return pipeline.accept_risk(
            tmp_path,
            "spec-complete",
            finding_id=finding_id,
            reason="fresh human re-attestation",
            accepted_by="release-manager",
            owner="platform",
            ticket="ISSUE-1",
            revisit="next release",
            evidence=evidence_path,
            **extra,
        )

    assert accept("MED-1")[0]
    evidence.write_text("MED-RENAMED current", encoding="utf-8")
    (tmp_path / ".pipeline-audit-root").write_text("new commit\n", encoding="utf-8")
    subprocess.run(["git", "add", ".pipeline-audit-root"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-m", "move head"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    assert not pipeline.validate(tmp_path)[0]
    _record_findings(tmp_path, medium=1)
    ok, msgs = accept("MED-RENAMED", refresh=True, supersedes_finding_id="MED-1")
    assert ok, "\n".join(msgs)
    assert pipeline.validate(tmp_path)[0]
    refreshed = _read_snap(tmp_path)
    assert refreshed["accepted_risks"][0]["finding_id"] == "MED-RENAMED"
    assert refreshed["accepted_risk_history"][0]["finding_id"] == "MED-1"

    _record_findings(tmp_path, medium=2)
    evidence2 = tmp_path / "finding-2.md"
    evidence2.write_text("MED-2", encoding="utf-8")
    assert accept("MED-2", evidence_path=evidence2, refresh=True)[0]
    assert accept("MED-RENAMED", refresh=True)[0]
    assert pipeline.validate(tmp_path)[0]


def test_accept_risk_refresh_retires_stale_set_when_finding_count_decreases(
    tmp_path, payload
):
    _start_v2(payload, tmp_path)
    _record_findings(tmp_path, medium=2)
    evidence_a = tmp_path / "finding-a.md"
    evidence_b = tmp_path / "finding-b.md"
    evidence_a.write_text("MED-A", encoding="utf-8")
    evidence_b.write_text("MED-B", encoding="utf-8")

    def attest(finding_id, evidence, **extra):
        return pipeline.accept_risk(
            tmp_path,
            "spec-complete",
            finding_id=finding_id,
            reason="fresh human re-attestation",
            accepted_by="release-manager",
            owner="platform",
            ticket=f"ISSUE-{finding_id}",
            revisit="next release",
            evidence=evidence,
            **extra,
        )

    assert attest("MED-A", evidence_a)[0]
    assert attest("MED-B", evidence_b)[0]
    _record_findings(tmp_path, medium=1)
    assert not pipeline.validate(tmp_path)[0]

    ok, msgs = attest("MED-A", evidence_a, refresh=True)

    assert ok, "\n".join(msgs)
    assert pipeline.validate(tmp_path)[0]
    refreshed = _read_snap(tmp_path)
    assert [risk["finding_id"] for risk in refreshed["accepted_risks"]] == ["MED-A"]
    assert {risk["finding_id"] for risk in refreshed["accepted_risk_history"]} == {
        "MED-A",
        "MED-B",
    }
    assert all(
        "Medium finding count changed" in risk["superseded_reason"]
        for risk in refreshed["accepted_risk_history"]
    )


def test_accept_risk_refresh_clears_active_acceptance_when_finding_is_fixed(
    tmp_path, payload
):
    _start_v2(payload, tmp_path)
    _record_findings(tmp_path, medium=1)
    evidence = tmp_path / "finding.md"
    evidence.write_text("MED-1", encoding="utf-8")
    fields = {
        "finding_id": "MED-1",
        "reason": "verified fixed",
        "accepted_by": "release-manager",
        "owner": "platform",
        "ticket": "ISSUE-1",
        "revisit": "closed after verification",
        "evidence": evidence,
    }
    assert pipeline.accept_risk(tmp_path, "spec-complete", **fields)[0]
    _record_findings(tmp_path, medium=0)
    assert not pipeline.validate(tmp_path)[0]
    evidence.write_text("MED-1 fixed and re-tested", encoding="utf-8")

    ok, msgs = pipeline.accept_risk(tmp_path, "spec-complete", refresh=True, **fields)

    assert ok, "\n".join(msgs)
    assert pipeline.validate(tmp_path)[0]
    cleared = _read_snap(tmp_path)
    assert cleared["accepted_risks"] == []
    assert cleared["accepted_risk_history"][0]["finding_id"] == "MED-1"
    gate_entry = cleared["gate_history"][0]
    assert gate_entry["status"] == "accepted-risk"
    assert gate_entry["accepted_risk_ids"] == []
    assert gate_entry["risk_clearance"]["evidence_sha256"]


def test_accept_risk_refresh_can_repair_stale_acceptances_across_gates(
    tmp_path, payload
):
    _start_v2(payload, tmp_path)
    _record_findings(tmp_path, medium=1)
    evidence = tmp_path / "finding.md"
    evidence.write_text("MED-CROSS", encoding="utf-8")

    def attest(gate, **extra):
        return pipeline.accept_risk(
            tmp_path,
            gate,
            finding_id="MED-CROSS",
            reason="fresh human re-attestation",
            accepted_by="release-manager",
            owner="platform",
            ticket="ISSUE-CROSS",
            revisit="next release",
            evidence=evidence,
            **extra,
        )

    assert attest("spec-complete")[0]
    assert attest("em-approved")[0]
    (tmp_path / ".pipeline-audit-root").write_text("new commit\n", encoding="utf-8")
    subprocess.run(["git", "add", ".pipeline-audit-root"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-m", "move head across gates"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    assert not pipeline.validate(tmp_path)[0]
    _record_findings(tmp_path, medium=1)

    assert attest("spec-complete", refresh=True)[0]
    assert not pipeline.validate(tmp_path)[0]
    ok, msgs = attest("em-approved", refresh=True)

    assert ok, "\n".join(msgs)
    assert pipeline.validate(tmp_path)[0]
    refreshed = _read_snap(tmp_path)
    assert len(refreshed["accepted_risk_history"]) == 2
    assert {risk["affected_gate"] for risk in refreshed["accepted_risks"]} == {
        "spec-complete",
        "em-approved",
    }


def test_pipeline_state_machine_transition_sequences(tmp_path, payload):
    """A deterministic model sequence covers every public transition and terminality."""
    aborted = tmp_path / "aborted"
    _install_with_gate_metadata(payload, aborted, profile="lean")
    _init_git_repo(aborted)
    evidence = aborted / "e.txt"
    evidence.write_text("verified", encoding="utf-8")

    def record_clean(target):
        _record_findings(target)
        return True, []

    abort_sequence = [
        (
            "pass-before-start",
            lambda: pipeline.close_gate(aborted, "code-review", evidence),
            False,
        ),
        ("start", lambda: pipeline.start(aborted, task="state model"), True),
        ("record-findings", lambda: record_clean(aborted), True),
        ("duplicate-start", lambda: pipeline.start(aborted, task="duplicate"), False),
        (
            "adopt-over-active",
            lambda: pipeline.adopt(
                aborted,
                task="invalid",
                gate="build-green",
                reason="already active",
                adopted_by="tester",
            ),
            False,
        ),
        (
            "out-of-order-pass",
            lambda: pipeline.close_gate(aborted, "build-green", evidence),
            False,
        ),
        ("pass", lambda: pipeline.close_gate(aborted, "code-review", evidence), True),
        ("premature-complete", lambda: pipeline.complete(aborted), False),
        ("abort", lambda: pipeline.abort(aborted), True),
        ("resume-aborted", lambda: pipeline.resume(aborted), False),
        (
            "pass-after-abort",
            lambda: pipeline.close_gate(aborted, "build-green", evidence),
            False,
        ),
        ("complete-after-abort", lambda: pipeline.complete(aborted), False),
    ]
    for name, transition, expected in abort_sequence:
        assert transition()[0] is expected, name

    completed = tmp_path / "completed"
    _install_with_gate_metadata(payload, completed)
    _init_git_repo(completed)
    evidence = completed / "e.txt"
    evidence.write_text("verified", encoding="utf-8")
    assert pipeline.adopt(
        completed,
        task="adopted state model",
        gate="contract-clear",
        reason="earlier required gates predate v2",
        adopted_by="release-manager",
    )[0]
    _record_findings(completed)
    assert pipeline.not_applicable(
        completed,
        "contract-clear",
        condition="no-api-contract-surface",
        reason="no public API",
        evidence=evidence,
    )[0]
    _record_findings(completed, medium=1)

    def risk(gate):
        return pipeline.accept_risk(
            completed,
            gate,
            finding_id="MED-STATE",
            reason="bounded",
            accepted_by="release-manager",
            owner="platform",
            ticket="ISSUE-STATE",
            revisit="next release",
            evidence=evidence,
        )

    complete_sequence = [
        ("accepted-risk-test", lambda: risk("test-coverage"), True),
        ("accepted-risk-security", lambda: risk("security-clear"), True),
        ("complete", lambda: pipeline.complete(completed), True),
        ("abort-completed", lambda: pipeline.abort(completed), False),
        ("resume-completed", lambda: pipeline.resume(completed), False),
    ]
    for name, transition, expected in complete_sequence:
        assert transition()[0] is expected, name
    final = _read_snap(completed)
    assert final["final_summary"]["accepted_risks"] == final["accepted_risks"]
    assert [gate["status"] for gate in final["final_summary"]["gates"]] == [
        "historical-adoption",
        "historical-adoption",
        "historical-adoption",
        "historical-adoption",
        "not-applicable",
        "accepted-risk",
        "accepted-risk",
    ]


def test_exhaustive_bounded_transition_model_preserves_security_invariants():
    """Exhaust every length-5 lifecycle sequence against a small explicit reference model.

    The scenario test above drives the real filesystem/API transitions. This generated companion
    covers invalid orderings and terminal attempts exhaustively without an optional Hypothesis
    dependency, while checking the two security invariants after every transition.
    """
    actions = (
        "start",
        "adopt",
        "record-findings",
        "close",
        "not-applicable",
        "accept-risk",
        "abort",
        "complete",
    )
    finding_profiles = (
        _findings(),
        _findings(critical=1),
        _findings(high=1),
        _findings(medium=1),
    )
    gate_requirements = ("required", "conditional")

    for findings, sequence in product(finding_profiles, product(actions, repeat=5)):
        state = "none"
        next_gate = 0
        resolutions = []
        medium_covered = False
        findings_recorded = False
        terminal_reached = False

        for action in sequence:
            before = (
                state,
                next_gate,
                tuple(resolutions),
                medium_covered,
                findings_recorded,
            )
            accepted = False
            blockers = sum(findings[name] for name in ("critical", "high", "medium"))
            if action == "start" and state == "none":
                state = "active"
                next_gate = 0
                findings_recorded = False
                accepted = True
            elif action == "adopt" and state == "none":
                state = "active"
                next_gate = 1
                findings_recorded = False
                accepted = True
            elif action == "record-findings" and state == "active":
                findings_recorded = True
                medium_covered = False
                accepted = True
            elif (
                action == "close"
                and state == "active"
                and findings_recorded
                and next_gate < 2
                and blockers == 0
            ):
                resolutions.append((next_gate, "passed"))
                next_gate += 1
                accepted = True
            elif (
                action == "not-applicable"
                and state == "active"
                and findings_recorded
                and next_gate < 2
                and gate_requirements[next_gate] == "conditional"
                and blockers == 0
            ):
                resolutions.append((next_gate, "not-applicable"))
                next_gate += 1
                accepted = True
            elif (
                action == "accept-risk"
                and state == "active"
                and findings_recorded
                and next_gate < 2
                and findings["critical"] == findings["high"] == 0
                and findings["medium"] > 0
            ):
                resolutions.append((next_gate, "accepted-risk"))
                next_gate += 1
                medium_covered = True
                accepted = True
            elif action == "abort" and state == "active":
                state = "aborted"
                accepted = True
            elif (
                action == "complete"
                and state == "active"
                and findings_recorded
                and next_gate == 2
                and findings["critical"] == findings["high"] == 0
                and (findings["medium"] == 0 or medium_covered)
            ):
                state = "completed"
                accepted = True

            if terminal_reached:
                assert not accepted, (findings, sequence, action)
            if not accepted:
                assert before == (
                    state,
                    next_gate,
                    tuple(resolutions),
                    medium_covered,
                    findings_recorded,
                )
            terminal_reached = terminal_reached or state in {"completed", "aborted"}
            for gate_index, resolution in resolutions:
                if resolution == "passed":
                    assert blockers == 0
                elif resolution == "not-applicable":
                    assert gate_requirements[gate_index] == "conditional"
                    assert blockers == 0
                elif resolution == "accepted-risk":
                    assert findings["critical"] == findings["high"] == 0
                    assert findings["medium"] > 0


def test_headless_iteration_fails_closed_without_descendant_containment(
    tmp_path, payload
):
    _start_v2(payload, tmp_path, profile="lean")
    before = _read_snap(tmp_path)

    token, coordinator, messages = pipeline.begin_headless_iteration(tmp_path)

    assert token is None and coordinator is None
    assert "descendant-process containment" in "\n".join(messages)
    assert _read_snap(tmp_path) == before


def test_every_lifecycle_operation_refuses_symlinked_pipeline_state(tmp_path, payload):
    _install_with_gate_metadata(payload, tmp_path)
    _init_git_repo(tmp_path)
    state = tmp_path / ".claude" / "state"
    state.rename(tmp_path / "saved-state")
    outside = tmp_path / "outside-state"
    outside.mkdir()
    try:
        state.symlink_to(outside, target_is_directory=True)
    except OSError as exc:  # pragma: no cover - Windows without symlink privilege
        pytest.skip(f"symlinks unavailable: {exc}")
    evidence = tmp_path / "e.txt"
    evidence.write_text("verified", encoding="utf-8")
    operations = {
        "start": lambda: pipeline.start(tmp_path, task="unsafe"),
        "adopt": lambda: pipeline.adopt(
            tmp_path,
            task="unsafe",
            gate="code-review",
            reason="unsafe",
            adopted_by="tester",
        ),
        "record-findings": lambda: pipeline.record_findings(
            tmp_path, **_findings(), evidence=evidence
        ),
        "close": lambda: pipeline.close_gate(tmp_path, "spec-complete", evidence),
        "not-applicable": lambda: pipeline.not_applicable(
            tmp_path,
            "contract-clear",
            condition="no-api-contract-surface",
            reason="no API",
            evidence=evidence,
        ),
        "accept-risk": lambda: pipeline.accept_risk(
            tmp_path,
            "spec-complete",
            finding_id="MED-1",
            reason="unsafe",
            accepted_by="tester",
            owner="tester",
            ticket="ISSUE-1",
            revisit="next release",
            evidence=evidence,
        ),
        "resume": lambda: pipeline.resume(tmp_path),
        "complete": lambda: pipeline.complete(tmp_path),
        "abort": lambda: pipeline.abort(tmp_path),
        "validate": lambda: pipeline.validate(tmp_path),
        "status": lambda: pipeline.status(tmp_path),
    }
    for name, operation in operations.items():
        ok, msgs = operation()
        assert not ok, name
        assert any("unsafe" in message or "symlink" in message for message in msgs), (
            name,
            msgs,
        )
    assert list(outside.iterdir()) == []


def test_pipeline_api_refuses_a_symlinked_project_root(tmp_path, payload):
    target = tmp_path / "real-project"
    _install_with_gate_metadata(payload, target, profile="lean")
    _init_git_repo(target)
    alias = tmp_path / "project-alias"
    try:
        alias.symlink_to(target, target_is_directory=True)
    except OSError as exc:  # pragma: no cover - Windows without symlink privilege
        pytest.skip(f"symlinks unavailable: {exc}")

    ok, msgs = pipeline.start(alias, task="must refuse linked root")

    assert not ok
    assert any("unsafe" in item and "link/reparse" in item for item in msgs), msgs
    assert not (target / ".claude/state/pipeline-snapshot.json").exists()

    evidence = target / "findings.json"
    evidence.write_text("{}", encoding="utf-8")
    ok, msgs = pipeline.record_findings(alias, **_findings(), evidence=evidence)
    assert not ok
    assert any("unsafe" in item and "link/reparse" in item for item in msgs), msgs
