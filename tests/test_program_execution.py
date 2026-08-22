from __future__ import annotations

import hashlib
import json
import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping, Optional, Sequence

import pytest

from claude_kit import catalog, pipeline, program_execution
from claude_kit.components import (
    Capability,
    NestedDelegationPolicy,
    PermissionClass,
)
from claude_kit.dispatch import (
    DispatchHandle,
    DispatchMessage,
    DispatchRequest,
    DispatchResult,
    DispatchStatus,
    WaitMode,
    WaitResult,
)
from claude_kit.models import InstallRequest, Runtime
from claude_kit.process_dispatch import (
    ClaudeProcessDispatcher,
    NativeRoleDefinition,
    ProcessOutcome,
    UnsupportedCapabilityError,
)
from claude_kit.program_execution import (
    ProgramBoundaryContainmentAttestation,
    _changed_paths,
    _persist_terminal_result,
    _physical_boundary_problem,
    _select_role,
    _stable_workspace_capture,
    _workspace_snapshot,
    program_artifact_path,
)
from claude_kit.program_runtime import load_program_manifest, seal_program_manifest
from claude_kit.projection import Provider
from claude_kit.runtime_scaffold import install_runtime
from claude_kit.workflow_executor import (
    ManagedWorktreeResolver,
    WorkflowExecutionStatus,
    execute_bound_workflow,
)
from claude_kit.workflows import (
    WorkflowValidationError,
    bind_workflow,
    load_workflow,
    workflow_definition_digest,
)
from tests.test_program_runtime import _manifest_document


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    ).stdout.strip()


def _write_program_artifact(repo: Path, artifact_id: str, document: Any) -> str:
    data = (
        json.dumps(
            document,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    path = program_artifact_path(repo, artifact_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def _prepare_program_repo(
    payload: Path, tmp_path: Path
) -> tuple[Path, Path, ManagedWorktreeResolver]:
    repo = tmp_path / "program-repo"
    repo.mkdir()
    _git(repo, "init", "-b", "program-main")
    _git(repo, "config", "user.email", "program@example.invalid")
    _git(repo, "config", "user.name", "Program Test")
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", "seed.txt")
    _git(repo, "commit", "-m", "seed")

    selection = catalog.defaults(payload)
    selection.profile = "lean"
    selection.detect_commands = False
    plan = catalog.resolve(payload, selection)
    install_runtime(
        payload,
        repo,
        plan,
        InstallRequest(selection=selection, runtime=Runtime.BOTH),
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "install both runtimes")
    source_commit = _git(repo, "rev-parse", "HEAD")
    ok, messages = pipeline.start(
        repo,
        task="Make the runtime projection portable.",
        mode="E",
    )
    assert ok, "\n".join(messages)
    run, error = pipeline.snapshot_document(repo)
    assert error is None and run is not None

    document = _manifest_document()
    document.update(
        {
            "run_id": run["run_id"],
            "source_commit": source_commit,
            "workflow_definition_digest": workflow_definition_digest(
                load_workflow(payload)
            ),
            "gate_definition_digest": run["gate_definition_digest"],
            "selection_digest": run["selection_digest"],
        }
    )
    assert tuple(plan.gates) == ("code-review", "build-green")

    prechange = document["pre_change_restore_point"]
    _git(repo, "tag", prechange["tag_ref"].removeprefix("refs/tags/"), source_commit)
    prechange["commit"] = source_commit
    prechange["verification_digest"] = _write_program_artifact(
        repo,
        prechange["verification_artifact_id"],
        {"tag_ref": prechange["tag_ref"], "commit": source_commit},
    )

    migration = next(unit for unit in document["units"] if unit["id"] == "migrate-data")
    inventory = migration["inventory"]
    items = [{"id": f"item-{index}"} for index in range(3)]
    items_digest = hashlib.sha256(
        json.dumps(
            items,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    inventory.update(
        {
            "items_digest": items_digest,
            "item_count": len(items),
            "expected_post_count": len(items),
        }
    )
    inventory["artifact_digest"] = _write_program_artifact(
        repo,
        inventory["artifact_id"],
        {
            "items": items,
            "item_count": len(items),
            "expected_post_count": len(items),
        },
    )

    restore = migration["restore_point"]
    _git(repo, "tag", restore["tag_ref"].removeprefix("refs/tags/"), source_commit)
    restore["commit"] = source_commit
    restore["verification_digest"] = _write_program_artifact(
        repo,
        restore["verification_artifact_id"],
        {"tag_ref": restore["tag_ref"], "commit": source_commit},
    )
    approval = migration["approval"]
    approval["request_digest"] = _write_program_artifact(
        repo,
        approval["request_artifact_id"],
        {"action": "migration", "scope": "three-items"},
    )
    approval["authorization_digest"] = _write_program_artifact(
        repo,
        approval["authorization_artifact_id"],
        {"decision": "approved", "scope": "three-items"},
    )
    approval["inventory_artifact_digest"] = inventory["artifact_digest"]
    approval["restore_point_commit"] = source_commit

    manifest_path = repo / "program.json"
    manifest_path.write_text(
        json.dumps(seal_program_manifest(document), indent=2) + "\n",
        encoding="utf-8",
    )
    resolver = ManagedWorktreeResolver(repo, str(run["run_id"]))
    resolver.ensure_workspace()
    return repo, manifest_path, resolver


def _evidence_document(artifact_id: str) -> dict[str, Any]:
    if artifact_id == "scope-record":
        return {
            "mode": "E",
            "surfaces": ["program-test-surface"],
            "constraints": [],
            "risks": [],
        }
    if artifact_id == "command-evidence":
        return {"command": "true", "exit-status": 0, "output": "verified"}
    if artifact_id == "review-verdict":
        return {
            "status": "PASS",
            "reviewer": "program-reviewer",
            "findings": [],
            "evidence": ["tests/test_program_execution.py"],
        }
    if artifact_id == "test-report":
        return {
            "scope": ["program-runtime"],
            "passed": 1,
            "failed": 0,
            "skipped": 0,
            "residual-risk": [],
        }
    if artifact_id == "security-report":
        return {
            "scanners": ["program-security-check"],
            "findings": [],
            "dispositions": [],
            "residual-risk": [],
        }
    raise AssertionError(f"unexpected ordinary evidence {artifact_id!r}")


def test_terminal_results_are_run_manifest_namespaced_and_cross_run_rejected(
    tmp_path: Path,
) -> None:
    (tmp_path / ".ckit").mkdir()
    handle = DispatchHandle("claude-1", "classification", provider="claude")
    result = DispatchResult(
        handle,
        DispatchStatus.SUCCEEDED,
        output="same terminal output",
    )
    first_run = "run-one"
    second_run = "run-two"
    first_manifest = "1" * 64
    second_manifest = "2" * 64

    first_path, first_digest = _persist_terminal_result(
        tmp_path,
        run_id=first_run,
        manifest_digest=first_manifest,
        unit_id="audit-api",
        attempt=1,
        result=result,
    )
    second_path, _second_digest = _persist_terminal_result(
        tmp_path,
        run_id=second_run,
        manifest_digest=second_manifest,
        unit_id="audit-api",
        attempt=1,
        result=result,
    )

    assert first_path != second_path
    assert first_path == (
        ".ckit/artifacts/program/runs/run-one/"
        f"{first_manifest}/audit-api/1/terminal-{first_digest}.json"
    )
    record = {
        "unit_id": "audit-api",
        "attempt": 1,
        "dispatch_id": "claude-1",
        "provider": "claude",
        "route": "classification",
        "status": "succeeded",
        "evidence": [],
        "output_sha256": hashlib.sha256(b"same terminal output").hexdigest(),
        "output_path": first_path,
        "output_artifact_sha256": first_digest,
        "error": None,
    }
    assert (
        pipeline._program_terminal_artifact_problem(
            tmp_path,
            {"run_id": first_run},
            {"binding": {"manifest_digest": first_manifest}},
            record,
        )
        is None
    )
    assert "another run or manifest" in str(
        pipeline._program_terminal_artifact_problem(
            tmp_path,
            {"run_id": second_run},
            {"binding": {"manifest_digest": second_manifest}},
            record,
        )
    )
    with pytest.raises(WorkflowValidationError, match="bounded artifact limit"):
        _persist_terminal_result(
            tmp_path,
            run_id="run-oversized",
            manifest_digest="3" * 64,
            unit_id="audit-api",
            attempt=1,
            result=DispatchResult(
                handle,
                DispatchStatus.FAILED,
                output="x" * (4 * 1024 * 1024),
                error="oversized injected-adapter result",
            ),
        )


class _ContainedDispatcher:
    queued_spawn = True

    def __init__(self, provider: str, *, fail_unit_once: str | None = None) -> None:
        self.provider = provider
        self.fail_unit_once = fail_unit_once
        self.failed = False
        self.counter = 0
        self.requests: dict[DispatchHandle, DispatchRequest] = {}
        self.cancelled: list[str] = []

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

    def attest_program_boundary_containment(
        self,
        request: DispatchRequest,
        handle: DispatchHandle,
        *,
        unit_id: str,
        workspace_target: str,
        boundary_digest: str,
        pre_workspace_checkpoint_digest: str,
        policy: str,
    ) -> ProgramBoundaryContainmentAttestation:
        assert request is self.requests[handle]
        return ProgramBoundaryContainmentAttestation.issue(
            issuer="test-contained-dispatcher",
            provider=self.provider,
            route=handle.route,
            dispatch_id=handle.id,
            unit_id=unit_id,
            workspace_target=workspace_target,
            boundary_digest=boundary_digest,
            pre_workspace_checkpoint_digest=pre_workspace_checkpoint_digest,
            policy=policy,
        )

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
        results: list[DispatchResult] = []
        for handle in handles:
            request = self.requests[handle]
            if (
                self.fail_unit_once is not None
                and self.fail_unit_once in request.objective
                and not self.failed
            ):
                self.failed = True
                results.append(
                    DispatchResult(
                        handle,
                        DispatchStatus.FAILED,
                        error="injected contained worker failure",
                    )
                )
                continue
            ordinary = {
                reference.uri.removeprefix("artifact://"): _evidence_document(
                    reference.uri.removeprefix("artifact://")
                )
                for reference in request.evidence
                if reference.uri.removeprefix("artifact://")
                in {
                    "scope-record",
                    "command-evidence",
                    "review-verdict",
                    "test-report",
                    "security-report",
                }
            }
            results.append(
                DispatchResult(
                    handle,
                    DispatchStatus.SUCCEEDED,
                    output=json.dumps({"evidence": ordinary}, separators=(",", ":")),
                    evidence=request.evidence,
                )
            )
        return tuple(results)

    def retry(self, handle: DispatchHandle, reason: str) -> DispatchHandle:
        raise AssertionError(f"coordinator retry is not used: {handle.id}: {reason}")

    def cancel(self, handle: DispatchHandle, reason: str) -> None:
        self.cancelled.append(f"{handle.id}:{reason}")


class _ReadOnlyRoleLoader:
    def load(self, provider: Any, role: str) -> NativeRoleDefinition:
        del provider
        return NativeRoleDefinition(
            role,
            "Read-only program auditor.",
            "Inspect the exact requested scope and return typed evidence.",
            PermissionClass.READ_ONLY,
            frozenset({Capability.FILE_READ, Capability.SEARCH, Capability.MESSAGE}),
            native_tools=("Read", "Glob", "Grep", "SendMessage"),
        )


class _SingleRoleLoader:
    def __init__(self, role: NativeRoleDefinition) -> None:
        self.role = role

    def load(self, provider: Any, role: str) -> NativeRoleDefinition:
        del provider
        assert role == self.role.id
        return self.role


@pytest.mark.parametrize(
    "extra",
    (
        Capability.SHELL,
        Capability.BROWSER,
        Capability.MCP,
        Capability.DELEGATE,
        Capability.TASK_LEDGER,
    ),
)
def test_mode_e_role_selection_rejects_excess_native_authority(
    extra: Capability,
) -> None:
    role = NativeRoleDefinition(
        "excess-role",
        "Excess role.",
        "Must not be selected for a read-only Mode E unit.",
        PermissionClass.READ_ONLY,
        frozenset({Capability.FILE_READ, Capability.SEARCH, extra}),
        nested_delegation=(
            NestedDelegationPolicy.ALLOWED
            if extra is Capability.DELEGATE
            else NestedDelegationPolicy.FORBIDDEN
        ),
    )

    with pytest.raises(UnsupportedCapabilityError):
        _select_role(
            provider=Provider.CLAUDE,
            candidates=(role.id,),
            required_capabilities=(Capability.FILE_READ, Capability.SEARCH),
            loader=_SingleRoleLoader(role),
        )


class _HostBackend:
    descendant_containment = True

    def __init__(self, outcomes: Sequence[ProcessOutcome]) -> None:
        self.outcomes = list(outcomes)
        self.started: list[dict[str, Any]] = []

    def start(
        self, argv: Sequence[str], *, cwd: Path, env: Mapping[str, str]
    ) -> object:
        token = len(self.started)
        self.started.append(
            {"argv": tuple(argv), "cwd": cwd, "env": dict(env), "prompt": None}
        )
        return token

    def submit(self, process: object, prompt: str) -> None:
        self.started[int(process)]["prompt"] = prompt

    def poll(self, process: object) -> ProcessOutcome:
        return self.outcomes[int(process)]

    def terminate(self, process: object) -> ProcessOutcome:
        return self.outcomes[int(process)]


def _scope_host_outcome(surface: str) -> ProcessOutcome:
    inner = json.dumps(
        {
            "evidence": {
                "scope-record": {
                    **_evidence_document("scope-record"),
                    "surfaces": [surface],
                }
            }
        },
        separators=(",", ":"),
    )
    return ProcessOutcome(
        0,
        json.dumps(
            {
                "status": "succeeded",
                "output": inner,
                "evidence": ["artifact://scope-record"],
            }
        ),
    )


def test_real_process_dispatcher_inner_evidence_envelope_reaches_audit_ledger(
    payload: Path, tmp_path: Path
) -> None:
    repo, manifest_path, resolver = _prepare_program_repo(payload, tmp_path)
    backend = _HostBackend(
        (_scope_host_outcome("src/api"), _scope_host_outcome("src/ui"))
    )
    dispatcher = ClaudeProcessDispatcher(
        repo,
        backend=backend,
        role_loader=_ReadOnlyRoleLoader(),
        allowed_workspaces=resolver.allowed_roots,
        environment={},
    )

    result = execute_bound_workflow(
        repo,
        provider="claude",
        objective="Make the runtime projection portable.",
        mode="E",
        conditions={},
        payload_root=payload,
        dispatcher=dispatcher,
        workspace_resolver=resolver,
        program_manifest_path=manifest_path,
    )

    assert result.status is WorkflowExecutionStatus.HUMAN_STOP
    assert result.human_stop is not None
    assert result.human_stop.reason.value == "unsupported-required-capability"
    assert [attempt.stage for attempt in result.attempts] == ["audit-api", "audit-ui"]
    assert len(backend.started) == 2
    assert all(
        "Set the host result's output string to a JSON-serialized inner document"
        in str(item["prompt"])
        for item in backend.started
    )
    run, error = pipeline.snapshot_document(repo)
    assert error is None and run is not None
    program = run["program_execution"]
    assert program["completed_units"] == ["audit-api", "audit-ui"]
    scope_records = [
        record
        for record in program["safeguard_verifications"]
        if record["artifact_id"] == "scope-record"
    ]
    assert len(scope_records) == 2
    assert all(
        record["details"]["validation_profile"] == "scope-record"
        for record in scope_records
    )


@pytest.mark.parametrize(
    ("initial_provider", "resuming_provider"),
    (("claude", "codex"), ("codex", "claude")),
)
def test_contained_program_resume_crosses_provider_without_replay(
    payload: Path,
    tmp_path: Path,
    initial_provider: str,
    resuming_provider: str,
) -> None:
    repo, manifest_path, resolver = _prepare_program_repo(payload, tmp_path)
    initial = _ContainedDispatcher(initial_provider, fail_unit_once="implement-api")
    first = execute_bound_workflow(
        repo,
        provider=initial_provider,
        objective="Make the runtime projection portable.",
        mode="E",
        conditions={},
        payload_root=payload,
        dispatcher=initial,
        workspace_resolver=resolver,
        program_manifest_path=manifest_path,
    )
    assert first.status is WorkflowExecutionStatus.FAILED
    assert [attempt.stage for attempt in first.attempts] == [
        "audit-api",
        "audit-ui",
        "gate-audit",
        "implement-api",
    ]

    resumed = _ContainedDispatcher(resuming_provider)
    second = execute_bound_workflow(
        repo,
        provider=resuming_provider,
        objective="Make the runtime projection portable.",
        mode="E",
        conditions={},
        payload_root=payload,
        dispatcher=resumed,
        workspace_resolver=resolver,
        program_manifest_path=manifest_path,
    )
    assert second.status is WorkflowExecutionStatus.WAITING_GATE
    assert second.pending_gates == ("code-review",)
    assert [attempt.stage for attempt in second.attempts] == [
        "implement-api",
        "implement-ui",
        "gate-low",
    ]
    run, error = pipeline.snapshot_document(repo)
    assert error is None and run is not None
    program = run["program_execution"]
    attempts = program["unit_attempts"]
    assert [item["provider"] for item in attempts[:4]] == [initial_provider] * 4
    assert [item["provider"] for item in attempts[4:]] == [resuming_provider] * 3
    assert [
        item["unit_id"] for item in attempts if item["status"] == "succeeded"
    ].count("audit-api") == 1
    assert [
        item["unit_id"] for item in attempts if item["status"] == "succeeded"
    ].count("gate-audit") == 1
    artifact_prefix = (
        f".ckit/artifacts/program/runs/{run['run_id']}/"
        f"{program['binding']['manifest_digest']}/"
    )
    assert all(
        item["output_path"].startswith(
            f"{artifact_prefix}{item['unit_id']}/{item['attempt']}/terminal-"
        )
        for item in attempts
    )


def test_workspace_snapshot_names_index_only_out_of_boundary_change(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "index-workspace"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "index@example.invalid")
    _git(repo, "config", "user.name", "Index Test")
    outside = repo / "outside.txt"
    outside.write_text("base\n", encoding="utf-8")
    _git(repo, "add", "outside.txt")
    _git(repo, "commit", "-m", "base")
    before, _digest = _workspace_snapshot(repo)

    outside.write_text("staged payload\n", encoding="utf-8")
    _git(repo, "add", "outside.txt")
    outside.write_text("base\n", encoding="utf-8")
    after, _digest = _workspace_snapshot(repo)

    assert _changed_paths(
        before,
        after,
        before_head=_git(repo, "rev-parse", "HEAD"),
        after_head=_git(repo, "rev-parse", "HEAD"),
    ) == ("outside.txt",)


def test_stable_workspace_capture_rejects_mutation_between_inventory_and_checkpoint(
    payload: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repo, _manifest_path, resolver = _prepare_program_repo(payload, tmp_path)
    workspace = resolver.ensure_workspace()
    original_checkpoint = resolver.checkpoint
    calls = 0

    def mutating_checkpoint() -> Mapping[str, Any]:
        nonlocal calls
        calls += 1
        if calls == 1:
            (workspace / "between-captures.txt").write_text(
                "mutated\n", encoding="utf-8"
            )
        return original_checkpoint()

    monkeypatch.setattr(resolver, "checkpoint", mutating_checkpoint)

    with pytest.raises(WorkflowValidationError, match="changed during"):
        _stable_workspace_capture(workspace, resolver, label="adversarial test capture")


def test_post_collect_fault_terminalizes_claimed_attempt(
    payload: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, manifest_path, resolver = _prepare_program_repo(payload, tmp_path)
    dispatcher = _ContainedDispatcher("claude")
    original_persist = program_execution._persist_terminal_result
    calls = 0

    def fail_once(*args: Any, **kwargs: Any) -> tuple[str, str]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("injected post-collect persistence fault")
        return original_persist(*args, **kwargs)

    monkeypatch.setattr(program_execution, "_persist_terminal_result", fail_once)

    with pytest.raises(OSError, match="injected post-collect"):
        execute_bound_workflow(
            repo,
            provider="claude",
            objective="Make the runtime projection portable.",
            mode="E",
            conditions={},
            payload_root=payload,
            dispatcher=dispatcher,
            workspace_resolver=resolver,
            program_manifest_path=manifest_path,
        )

    run, error = pipeline.snapshot_document(repo)
    assert error is None and run is not None
    attempts = run["program_execution"]["unit_attempts"]
    assert len(attempts) == 1
    assert attempts[0]["status"] == "cancelled"
    assert all(item["status"] != "running" for item in attempts)


def test_stale_program_reconciliation_is_content_addressed_to_its_run(
    payload: Path, tmp_path: Path
) -> None:
    repo, manifest_path, resolver = _prepare_program_repo(payload, tmp_path)
    selection = catalog.defaults(payload)
    selection.profile = "lean"
    selection.detect_commands = False
    bound = bind_workflow(load_workflow(payload), catalog.resolve(payload, selection))
    manifest = load_program_manifest(
        manifest_path, schema_path=payload / "schemas/program-manifest.schema.json"
    )
    program_execution._bind(
        repo,
        manifest=manifest,
        manifest_relative="program.json",
        bound_workflow=bound,
        workspace_resolver=resolver,
    )
    run, error = pipeline.snapshot_document(repo)
    assert error is None and run is not None
    program = run["program_execution"]
    unit = program["units"]["audit-api"]
    checkpoint = resolver.checkpoint()
    claimed, messages = pipeline.claim_program_unit(
        repo,
        unit_id="audit-api",
        provider="claude",
        route=unit["route_candidates"][0],
        dispatch_id="stale-audit-api",
        attempt=1,
        required_capabilities=tuple(unit["required_capabilities"]),
        attested_capabilities=tuple(unit["required_capabilities"]),
        pre_workspace_checkpoint=checkpoint,
        prompt_token_upper_bound=1,
    )
    assert claimed, "\n".join(messages)

    operator_evidence = repo / "operator-stale-evidence.json"
    operator_evidence.write_text(
        json.dumps({"operator": "release-owner", "observation": "host lost"}),
        encoding="utf-8",
    )
    reconciled, messages = pipeline.reconcile_stale_program_attempt(
        repo,
        unit_id="audit-api",
        dispatch_id="stale-audit-api",
        reconciled_by="release-owner",
        evidence=operator_evidence,
    )
    assert reconciled, "\n".join(messages)
    updated, error = pipeline.snapshot_document(repo)
    assert error is None and updated is not None
    updated_program = updated["program_execution"]
    record = updated_program["unit_attempts"][0]
    artifact_sha = record["output_artifact_sha256"]
    assert record["output_path"] == (
        f".ckit/artifacts/program/runs/{updated['run_id']}/"
        f"{updated_program['binding']['manifest_digest']}/audit-api/1/"
        f"reconciliation-{artifact_sha}.json"
    )
    assert pipeline._program_execution_problem(repo, updated) is None
    assert "another run or manifest" in str(
        pipeline._program_terminal_artifact_problem(
            repo,
            {**updated, "run_id": "another-run"},
            updated_program,
            record,
        )
    )


def test_bind_revalidates_manifest_file_while_holding_pipeline_lock(
    payload: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, manifest_path, resolver = _prepare_program_repo(payload, tmp_path)
    dispatcher = _ContainedDispatcher("claude")
    original_lock = pipeline._pipeline_write_lock
    original_manifest = manifest_path.read_text(encoding="utf-8")
    mutated = False

    @contextmanager
    def mutating_lock(
        fs: Any, path: Path, *, msgs: list[str] | None = None
    ) -> Iterator[None]:
        nonlocal mutated
        with original_lock(fs, path, msgs=msgs):
            if not mutated:
                mutated = True
                manifest_path.write_text(original_manifest + "\n", encoding="utf-8")
            yield

    monkeypatch.setattr(pipeline, "_pipeline_write_lock", mutating_lock)

    with pytest.raises(
        WorkflowValidationError, match="changed during authoritative bind"
    ):
        execute_bound_workflow(
            repo,
            provider="claude",
            objective="Make the runtime projection portable.",
            mode="E",
            conditions={},
            payload_root=payload,
            dispatcher=dispatcher,
            workspace_resolver=resolver,
            program_manifest_path=manifest_path,
        )

    run, error = pipeline.snapshot_document(repo)
    assert error is None and run is not None
    assert run.get("program_execution") is None


def test_physical_boundary_preflight_rejects_symlink_to_outside(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside\n", encoding="utf-8")
    allowed = workspace / "allowed"
    allowed.mkdir()
    (allowed / "redirect").symlink_to(outside)

    problem = _physical_boundary_problem(
        workspace, ({"id": "allowed", "kind": "tree", "path": "allowed"},)
    )

    assert problem is not None
    assert "symlink" in problem


@pytest.mark.parametrize(
    "document",
    (
        {
            "mode": "E",
            "surfaces": "artifact://scope-record",
            "constraints": "artifact://scope-record",
            "risks": "artifact://scope-record",
        },
        {
            "mode": "E",
            "surfaces": ["artifact://scope-record"],
            "constraints": [],
            "risks": [],
        },
    ),
)
def test_scope_evidence_rejects_symbolic_wrappers(document: dict[str, Any]) -> None:
    requirement = {
        "validation_profile": "scope-record",
        "kind": "artifact",
        "required_fields": ["mode", "surfaces", "constraints", "risks"],
        "project_contained": True,
    }
    content = json.dumps(document).encode("utf-8")
    assert pipeline._program_evidence_document_problem(content, requirement) is not None


@pytest.mark.parametrize(
    ("profile", "kind", "document", "required_fields"),
    (
        (
            "scope-record",
            "artifact",
            {"mode": "E", "surfaces": [1], "constraints": [], "risks": []},
            ["mode", "surfaces", "constraints", "risks"],
        ),
        (
            "review-verdict",
            "verdict",
            {
                "status": "PASS",
                "reviewer": "reviewer",
                "findings": [],
                "evidence": [True],
            },
            ["status", "reviewer", "findings", "evidence"],
        ),
        (
            "test-report",
            "findings-report",
            {
                "scope": True,
                "passed": 1,
                "failed": 0,
                "skipped": 0,
                "residual-risk": False,
            },
            ["scope", "passed", "failed", "skipped", "residual-risk"],
        ),
        (
            "security-report",
            "findings-report",
            {
                "scanners": ["scanner"],
                "findings": [
                    {
                        "id": "f1",
                        "severity": "low",
                        "summary": "finding",
                        "disposition": "fixed",
                        "evidence": [1],
                    }
                ],
                "dispositions": [
                    {
                        "finding-id": "f1",
                        "disposition": True,
                        "evidence": [1],
                    }
                ],
                "residual-risk": [],
            },
            ["scanners", "findings", "dispositions", "residual-risk"],
        ),
    ),
)
def test_evidence_profiles_reject_scalar_container_stand_ins(
    profile: str,
    kind: str,
    document: dict[str, Any],
    required_fields: list[str],
) -> None:
    requirement = {
        "validation_profile": profile,
        "kind": kind,
        "required_fields": required_fields,
        "project_contained": True,
    }
    content = json.dumps(document).encode("utf-8")

    assert pipeline._program_evidence_document_problem(content, requirement) is not None


@pytest.mark.parametrize(
    "invalid_field", ("finding-evidence", "decision", "decision-evidence")
)
def test_security_profile_rejects_boolean_or_numeric_citation_stand_ins(
    invalid_field: str,
) -> None:
    finding_evidence: list[Any] = ["scan-output"]
    decision: Any = "fixed"
    decision_evidence: list[Any] = ["fix-verification"]
    if invalid_field == "finding-evidence":
        finding_evidence = [1]
    elif invalid_field == "decision":
        decision = True
    else:
        decision_evidence = [False]
    document = {
        "scanners": ["scanner"],
        "findings": [
            {
                "id": "f1",
                "severity": "low",
                "summary": "finding",
                "disposition": "fixed",
                "evidence": finding_evidence,
            }
        ],
        "dispositions": [
            {
                "finding-id": "f1",
                "disposition": decision,
                "evidence": decision_evidence,
            }
        ],
        "residual-risk": [],
    }
    requirement = {
        "validation_profile": "security-report",
        "kind": "findings-report",
        "required_fields": ["scanners", "findings", "dispositions", "residual-risk"],
        "project_contained": True,
    }

    assert (
        pipeline._program_evidence_document_problem(
            json.dumps(document).encode("utf-8"), requirement
        )
        is not None
    )


def test_zero_test_report_cannot_pass() -> None:
    requirement = {
        "validation_profile": "test-report",
        "kind": "findings-report",
        "required_fields": ["scope", "passed", "failed", "skipped", "residual-risk"],
        "project_contained": True,
    }
    content = json.dumps(
        {
            "scope": ["unit"],
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "residual-risk": [],
        }
    ).encode("utf-8")
    assert "at least one executed test" in str(
        pipeline._program_evidence_document_problem(content, requirement)
    )


@pytest.mark.parametrize(
    "dispositions",
    (
        [],
        [
            {"finding-id": "f1", "disposition": "fixed", "evidence": ["scan"]},
            {"finding-id": "f1", "disposition": "fixed", "evidence": ["scan"]},
        ],
        [{"finding-id": "unknown", "disposition": "fixed", "evidence": ["scan"]}],
    ),
)
def test_security_findings_require_exact_disposition_coverage(
    dispositions: list[dict[str, Any]],
) -> None:
    requirement = {
        "validation_profile": "security-report",
        "kind": "findings-report",
        "required_fields": ["scanners", "findings", "dispositions", "residual-risk"],
        "project_contained": True,
    }
    content = json.dumps(
        {
            "scanners": ["scanner"],
            "findings": [
                {
                    "id": "f1",
                    "severity": "low",
                    "summary": "finding",
                    "disposition": "fixed",
                    "evidence": ["scan-output"],
                }
            ],
            "dispositions": dispositions,
            "residual-risk": [],
        }
    ).encode("utf-8")
    assert pipeline._program_evidence_document_problem(content, requirement) is not None


def test_closeout_cannot_self_assert_a_fake_gate() -> None:
    contract = {
        "ordered_program_gates": ["real-gate"],
        "gate_checkpoints": [
            {
                "gate_id": "real-gate",
                "verification_records": [
                    {"artifact_id": "test-report", "artifact_sha256": "a" * 64}
                ],
            }
        ],
        "gates": {"real-gate": {"kind": "program-wave"}},
    }
    run = {"gate_history": [], "accepted_risks": []}
    content = json.dumps(
        {
            "outcome": "done",
            "gates": [
                {
                    "id": "fake-gate",
                    "status": "passed",
                    "evidence": [{"artifact_id": "made-up", "sha256": "b" * 64}],
                }
            ],
            "accepted-risks": [],
            "learnings": [],
        }
    ).encode("utf-8")

    assert (
        pipeline._program_closeout_document_problem(content, run, contract)
        == "program closeout gate ledger differs from authoritative checkpoints"
    )


def test_packaged_manifest_loader_is_used_by_coordinator_fixture(
    payload: Path, tmp_path: Path
) -> None:
    repo, manifest_path, _resolver = _prepare_program_repo(payload, tmp_path)
    manifest = load_program_manifest(
        manifest_path, schema_path=payload / "schemas/program-manifest.schema.json"
    )
    assert manifest.workflow_definition_digest == workflow_definition_digest(
        load_workflow(payload)
    )
    assert repo in manifest_path.parents
