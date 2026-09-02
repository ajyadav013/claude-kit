"""Authoritative maker-checker feedback-loop tests."""

from __future__ import annotations

import json
import shlex
import subprocess
from contextlib import ExitStack
from pathlib import Path
from typing import Callable, Optional, Sequence

import pytest

from claude_kit import maker_checker as maker_checker_module
from claude_kit import pipeline, schemas
from claude_kit.components import Capability
from claude_kit.dispatch import (
    DispatchHandle,
    DispatchMessage,
    DispatchRequest,
    DispatchResult,
    DispatchStatus,
    ExecutionSlot,
    WaitMode,
    WaitResult,
)
from claude_kit.maker_checker import (
    DeliverableKind,
    MakerCheckerError,
    MakerCheckerStatus,
    confirm_maker_checker_dispatch_terminated,
    load_frozen_maker_checker_run,
    run_maker_checker,
    validate_maker_checker_snapshot,
)
from claude_kit.models import (
    ExecutionPolicy,
    ModelChoice,
    ModelChoiceKind,
    Runtime,
    WorkerBinding,
)
from claude_kit.process_dispatch import CodexAppServerBackend
from tests._helpers import install

ResponseFactory = Callable[[DispatchRequest], str]


class ScriptedDispatcher:
    """Queued dispatcher fake that returns one nested response per spawn."""

    queued_spawn = True

    def __init__(
        self,
        responses: Sequence[ResponseFactory],
        *,
        providers: Optional[dict[ExecutionSlot, str]] = None,
        time_out_at: Optional[int] = None,
    ) -> None:
        self.responses = list(responses)
        self.providers = providers or {
            ExecutionSlot.MAKER: "claude",
            ExecutionSlot.REVIEWER: "codex",
        }
        self.time_out_at = time_out_at
        self.requests: list[DispatchRequest] = []
        self.handles: list[DispatchHandle] = []
        self.cancelled: list[DispatchHandle] = []
        self.retry_calls: list[DispatchHandle] = []

    def spawn(self, request: DispatchRequest) -> DispatchHandle:
        index = len(self.requests)
        assert index < len(self.responses)
        assert request.execution_slot is not None
        self.requests.append(request)
        handle = DispatchHandle(
            f"dispatch-{index + 1}",
            request.route,
            provider=self.providers[request.execution_slot],
            required_capabilities=(Capability.FILE_READ, Capability.SEARCH),
            attested_capabilities=(Capability.FILE_READ, Capability.SEARCH),
            execution_slot=request.execution_slot,
            requested_model=request.requested_model,
        )
        self.handles.append(handle)
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
        handle = tuple(handles)[0]
        if self.time_out_at == len(self.requests):
            return WaitResult((), (handle,), True)
        return WaitResult((handle,), (), False)

    def collect(self, handles: Sequence[DispatchHandle]) -> tuple[DispatchResult, ...]:
        results: list[DispatchResult] = []
        for handle in handles:
            index = self.handles.index(handle)
            output = self.responses[index](self.requests[index])
            results.append(
                DispatchResult(handle, DispatchStatus.SUCCEEDED, output=output)
            )
        return tuple(results)

    def retry(self, handle: DispatchHandle, reason: str) -> DispatchHandle:
        del reason
        self.retry_calls.append(handle)
        raise AssertionError("semantic reviewer FAIL must not use transport retry")

    def cancel(self, handle: DispatchHandle, reason: str) -> None:
        assert reason
        self.cancelled.append(handle)


class SimulatedCoordinatorCrash(BaseException):
    """Test-only process death that bypasses coordinator exception handling."""


class CrashBeforeReviewerDispatcher(ScriptedDispatcher):
    def spawn(self, request: DispatchRequest) -> DispatchHandle:
        if request.execution_slot is ExecutionSlot.REVIEWER:
            raise SimulatedCoordinatorCrash
        return super().spawn(request)


class WrongRouteDispatcher(ScriptedDispatcher):
    def spawn(self, request: DispatchRequest) -> DispatchHandle:
        handle = super().spawn(request)
        return DispatchHandle(
            handle.id,
            "maker-checker-reviewer",
            provider=handle.provider,
            required_capabilities=handle.required_capabilities,
            attested_capabilities=handle.attested_capabilities,
            execution_slot=handle.execution_slot,
            requested_model=handle.requested_model,
        )


class CancelFailureDispatcher(ScriptedDispatcher):
    def cancel(self, handle: DispatchHandle, reason: str) -> None:
        del handle, reason
        raise RuntimeError("injected cancellation failure")


class RetryReservationFailureDispatcher(ScriptedDispatcher):
    def collect(self, handles: Sequence[DispatchHandle]) -> tuple[DispatchResult, ...]:
        handle = tuple(handles)[0]
        return (
            DispatchResult(
                handle,
                DispatchStatus.FAILED,
                error="injected transient transport failure",
            ),
        )

    def retry(self, handle: DispatchHandle, reason: str) -> DispatchHandle:
        assert reason
        self.retry_calls.append(handle)
        raise RuntimeError("retry reservation failed before a worker existed")


class TerminalCollectFailureDispatcher(ScriptedDispatcher):
    def collect(self, handles: Sequence[DispatchHandle]) -> tuple[DispatchResult, ...]:
        assert tuple(handles)
        raise RuntimeError("terminal response decoding failed")

    def cancel(self, handle: DispatchHandle, reason: str) -> None:
        raise AssertionError(
            f"terminal handle {handle.id} must not be cancelled after wait: {reason}"
        )


class CrashOnThirdSpawnDispatcher(ScriptedDispatcher):
    def spawn(self, request: DispatchRequest) -> DispatchHandle:
        if len(self.requests) == 2:
            raise SimulatedCoordinatorCrash
        return super().spawn(request)


class CrashAtSlotDispatcher(ScriptedDispatcher):
    def __init__(
        self, slot: ExecutionSlot, responses: Sequence[ResponseFactory]
    ) -> None:
        super().__init__(responses)
        self.slot = slot

    def spawn(self, request: DispatchRequest) -> DispatchHandle:
        if request.execution_slot is self.slot:
            raise SimulatedCoordinatorCrash
        return super().spawn(request)


def _policy(*, revisions: int = 2) -> ExecutionPolicy:
    return ExecutionPolicy(
        maker=WorkerBinding(
            Runtime.CLAUDE,
            ModelChoice(ModelChoiceKind.EXACT, "claude-maker-model"),
        ),
        reviewer=WorkerBinding(
            Runtime.CODEX,
            ModelChoice(ModelChoiceKind.INHERIT),
        ),
        max_revisions=revisions,
    )


def _maker(
    content: str,
    *,
    kind: str = "document",
    dispositions: Optional[list[dict[str, object]]] = None,
) -> ResponseFactory:
    def response(_request: DispatchRequest) -> str:
        return json.dumps(
            {
                "schema_version": 1,
                "artifact": {"kind": kind, "content": content},
                "summary": "Produced the requested artifact.",
                "finding_dispositions": dispositions or [],
            }
        )

    return response


def _review(
    verdict: str,
    *,
    findings: Optional[list[dict[str, object]]] = None,
    stale_artifact_digest: bool = False,
    residual_risks: Optional[list[str]] = None,
) -> ResponseFactory:
    def response(request: DispatchRequest) -> str:
        context = json.loads(request.context)
        criteria = [
            {
                "criterion_id": item["id"],
                "status": verdict,
                "evidence": [f"artifact://{item['id']}"],
            }
            for item in context["contract"]["acceptance_criteria"]
        ]
        return json.dumps(
            {
                "schema_version": 1,
                "verdict": verdict,
                "contract_digest": context["contract"]["digest"],
                "artifact_digest": (
                    "0" * 64 if stale_artifact_digest else context["artifact"]["digest"]
                ),
                "criteria": criteria,
                "findings": findings or [],
                "residual_risks": residual_risks or [],
            }
        )

    return response


def _finding() -> dict[str, object]:
    return {
        "finding_id": "F-001",
        "severity": "medium",
        "message": "The error state is missing.",
        "evidence": ["artifact://criterion-1"],
    }


def _assert_failed_attempt_preserves_output(
    root: Path,
    *,
    expected_output: str,
    expected_slot: ExecutionSlot,
) -> dict[str, object]:
    snapshot = json.loads(
        (root / ".ckit/state/pipeline-snapshot.json").read_text(encoding="utf-8")
    )
    attempt = snapshot["maker_checker"]["attempts"][-1]
    assert attempt["status"] == "failed"
    assert attempt["execution_slot"] == expected_slot.value
    assert isinstance(attempt["output_path"], str)
    assert isinstance(attempt["output_sha256"], str)
    output_path = root / attempt["output_path"]
    assert output_path.read_text(encoding="utf-8") == expected_output
    assert output_path.stat().st_mode & 0o777 == 0o600
    assert attempt["output_sha256"] == maker_checker_module._bytes_digest(
        output_path.read_bytes()
    )
    coherent, messages = validate_maker_checker_snapshot(root, snapshot)
    assert coherent, "\n".join(messages)
    with ExitStack() as stack:
        assert schemas.validate_doc(snapshot, "pipeline-snapshot", stack) == []
    return snapshot


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "Test User"],
        check=True,
    )
    (path / ".ckit").mkdir(exist_ok=True)
    (path / "app.py").write_text("answer = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "app.py"], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-qm", "base"], check=True)


def test_public_maker_checker_entrypoints_reject_a_symlinked_project_root(
    tmp_path: Path,
) -> None:
    real = tmp_path / "real-project"
    real.mkdir()
    (real / ".ckit").mkdir()
    alias = tmp_path / "project-alias"
    alias.symlink_to(real, target_is_directory=True)

    valid, messages = validate_maker_checker_snapshot(alias)
    assert not valid
    assert any("link" in message for message in messages)
    with pytest.raises(MakerCheckerError, match="link"):
        run_maker_checker(
            alias,
            task="Draft a design.",
            kind="design",
            policy=_policy(),
            dispatcher=ScriptedDispatcher([]),
        )
    with pytest.raises(MakerCheckerError, match="link"):
        load_frozen_maker_checker_run(alias)
    with pytest.raises(MakerCheckerError, match="link"):
        maker_checker_module.abort_maker_checker_run(alias)
    with pytest.raises(MakerCheckerError, match="link"):
        confirm_maker_checker_dispatch_terminated(
            alias,
            run_id="mc-alias",
            attempt_id="attempt-1",
            route="maker-checker-maker",
            dispatch_id="dispatch-1",
            dispatch_attempt=1,
            evidence="terminated",
        )


def test_first_pass_specification_uses_bound_slots_and_persists_evidence(
    tmp_path: Path,
) -> None:
    (tmp_path / ".ckit").mkdir()
    dispatcher = ScriptedDispatcher(
        [_maker("# Login specification\n"), _review("PASS")]
    )

    result = run_maker_checker(
        tmp_path,
        task="Write a login specification.",
        kind=DeliverableKind.SPECIFICATION,
        policy=_policy(),
        dispatcher=dispatcher,
        run_id="mc-first-pass",
    )

    assert result.status is MakerCheckerStatus.PASSED
    assert result.iterations == 1
    assert result.artifact_path is not None
    assert (
        (tmp_path / result.artifact_path)
        .read_text(encoding="utf-8")
        .startswith("# Login")
    )
    assert [request.execution_slot for request in dispatcher.requests] == [
        ExecutionSlot.MAKER,
        ExecutionSlot.REVIEWER,
    ]
    assert dispatcher.requests[0].route == "maker-checker-maker"
    assert dispatcher.requests[1].route == "maker-checker-reviewer"
    assert dispatcher.requests[0].requested_model == "claude-maker-model"
    assert dispatcher.requests[1].requested_model is None
    assert dispatcher.requests[1].workspace == str(tmp_path.resolve())
    record = json.loads(
        (
            tmp_path / ".ckit/artifacts/maker-checker/runs/mc-first-pass/result.json"
        ).read_text(encoding="utf-8")
    )
    assert record["status"] == "passed"
    assert record["artifact_digest"] == result.artifact_digest
    snapshot_path = tmp_path / ".ckit/state/pipeline-snapshot.json"
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert snapshot["snapshot_kind"] == "maker-checker"
    assert snapshot["maker_checker"]["bindings"]["maker"]["provider"] == "claude"
    assert snapshot["maker_checker"]["bindings"]["reviewer"]["provider"] == "codex"
    assert validate_maker_checker_snapshot(tmp_path, snapshot)[0]
    assert pipeline.validate(tmp_path)[0]
    strict_ok, strict_messages = pipeline.validate(tmp_path, strict=True)
    assert not strict_ok
    assert any("install snapshot" in message for message in strict_messages)
    assert any(
        "maker-checker snapshot is coherent" in message for message in strict_messages
    )
    with ExitStack() as stack:
        assert schemas.validate_doc(snapshot, "pipeline-snapshot", stack) == []


def test_reviewer_fail_creates_new_maker_and_fresh_reviewer_attempt(
    tmp_path: Path,
) -> None:
    (tmp_path / ".ckit").mkdir()
    dispatcher = ScriptedDispatcher(
        [
            _maker("first"),
            _review("FAIL", findings=[_finding()]),
            _maker(
                "second",
                dispositions=[
                    {
                        "finding_id": "F-001",
                        "disposition": "fixed",
                        "evidence": ["artifact://criterion-1"],
                        "note": "Added the missing error state.",
                    }
                ],
            ),
            _review("PASS"),
        ]
    )

    result = run_maker_checker(
        tmp_path,
        task="Design a robust login flow.",
        kind="design",
        policy=_policy(),
        dispatcher=dispatcher,
        run_id="mc-revise",
    )

    assert result.status is MakerCheckerStatus.PASSED
    assert result.iterations == 2
    assert len({handle.id for handle in dispatcher.handles}) == 4
    assert [request.execution_slot for request in dispatcher.requests] == [
        ExecutionSlot.MAKER,
        ExecutionSlot.REVIEWER,
        ExecutionSlot.MAKER,
        ExecutionSlot.REVIEWER,
    ]
    assert not dispatcher.retry_calls
    revision_context = json.loads(dispatcher.requests[2].context)
    assert revision_context["findings"][0]["finding_id"] == "F-001"


@pytest.mark.parametrize(
    ("disposition", "expected_reason"),
    [
        ("disputed", "conflicting-evidence"),
        ("human-required", "missing-requirements"),
    ],
)
def test_unresolved_maker_disposition_preserves_private_response_evidence(
    tmp_path: Path,
    disposition: str,
    expected_reason: str,
) -> None:
    (tmp_path / ".ckit").mkdir()
    raw_response = json.dumps(
        {
            "schema_version": 1,
            "artifact": {"kind": "document", "content": "revised"},
            "summary": "The finding needs a person.",
            "finding_dispositions": [
                {
                    "finding_id": "F-001",
                    "disposition": disposition,
                    "evidence": ["artifact://criterion-1"],
                    "note": "Preserve this evidence for the operator.",
                }
            ],
        }
    )
    dispatcher = ScriptedDispatcher(
        [
            _maker("draft"),
            _review("FAIL", findings=[_finding()]),
            lambda _request: raw_response,
        ]
    )

    result = run_maker_checker(
        tmp_path,
        task="Draft a reviewable design.",
        kind="design",
        policy=_policy(),
        dispatcher=dispatcher,
        run_id=f"mc-{disposition}",
    )

    assert result.status is MakerCheckerStatus.HUMAN_STOP
    assert result.human_stop is not None
    assert result.human_stop.reason.value == expected_reason
    _assert_failed_attempt_preserves_output(
        tmp_path,
        expected_output=raw_response,
        expected_slot=ExecutionSlot.MAKER,
    )


@pytest.mark.parametrize("slot", [ExecutionSlot.MAKER, ExecutionSlot.REVIEWER])
def test_malformed_nested_output_is_preserved_for_operator_inspection(
    tmp_path: Path,
    slot: ExecutionSlot,
) -> None:
    (tmp_path / ".ckit").mkdir()
    malformed = '{"schema_version":'
    responses: list[ResponseFactory] = [lambda _request: malformed]
    if slot is ExecutionSlot.REVIEWER:
        responses.insert(0, _maker("draft"))

    result = run_maker_checker(
        tmp_path,
        task="Draft a reviewable design.",
        kind="design",
        policy=_policy(),
        dispatcher=ScriptedDispatcher(responses),
        run_id=f"mc-malformed-{slot.value}",
    )

    assert result.status is MakerCheckerStatus.HUMAN_STOP
    assert result.human_stop is not None
    assert result.human_stop.reason.value == "conflicting-evidence"
    _assert_failed_attempt_preserves_output(
        tmp_path,
        expected_output=malformed,
        expected_slot=slot,
    )


def test_terminal_result_semantics_are_verified_after_hash_rebinding(
    tmp_path: Path,
) -> None:
    (tmp_path / ".ckit").mkdir()
    result = run_maker_checker(
        tmp_path,
        task="Draft a durable design.",
        kind="design",
        policy=_policy(),
        dispatcher=ScriptedDispatcher([_maker("design"), _review("PASS")]),
        run_id="mc-result-binding",
    )
    assert result.status is MakerCheckerStatus.PASSED
    snapshot_path = tmp_path / ".ckit/state/pipeline-snapshot.json"
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    result_path = tmp_path / snapshot["result_path"]
    result_record = json.loads(result_path.read_text(encoding="utf-8"))
    result_record["iterations"] = 99
    result_path.write_text(
        json.dumps(result_record, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    snapshot["result_sha256"] = maker_checker_module._bytes_digest(
        result_path.read_bytes()
    )
    snapshot_path.write_text(json.dumps(snapshot) + "\n", encoding="utf-8")

    coherent, messages = validate_maker_checker_snapshot(tmp_path, snapshot)
    assert not coherent
    assert any("iterations binding mismatch" in message for message in messages)


@pytest.mark.parametrize("manifest", [None, "{not-json"])
def test_fresh_run_translates_missing_or_corrupt_manifest_to_public_error(
    tmp_path: Path, manifest: str | None
) -> None:
    (tmp_path / ".ckit/config").mkdir(parents=True)
    if manifest is not None:
        (tmp_path / ".ckit/config/init-options.json").write_text(
            manifest, encoding="utf-8"
        )
    with pytest.raises(
        MakerCheckerError,
        match="runtime-aware install|init-options manifest is corrupt",
    ):
        run_maker_checker(
            tmp_path,
            task="Draft a design.",
            kind="design",
            dispatcher=ScriptedDispatcher([]),
            run_id="mc-config-error",
        )


def test_unchanged_revision_is_a_human_stop_without_second_review(
    tmp_path: Path,
) -> None:
    (tmp_path / ".ckit").mkdir()
    dispatcher = ScriptedDispatcher(
        [
            _maker("same"),
            _review("FAIL", findings=[_finding()]),
            _maker(
                "same",
                dispositions=[
                    {
                        "finding_id": "F-001",
                        "disposition": "fixed",
                        "evidence": ["artifact://criterion-1"],
                        "note": "Claimed fixed.",
                    }
                ],
            ),
        ]
    )

    result = run_maker_checker(
        tmp_path,
        task="Draft a specification.",
        kind="specification",
        policy=_policy(),
        dispatcher=dispatcher,
        run_id="mc-unchanged",
    )

    assert result.status is MakerCheckerStatus.HUMAN_STOP
    assert result.human_stop is not None
    assert result.human_stop.reason.value == "conflicting-evidence"
    assert len(dispatcher.requests) == 3


def test_exhausted_revision_budget_never_turns_fail_into_pass(tmp_path: Path) -> None:
    (tmp_path / ".ckit").mkdir()
    dispatcher = ScriptedDispatcher(
        [_maker("draft"), _review("FAIL", findings=[_finding()])]
    )

    result = run_maker_checker(
        tmp_path,
        task="Draft a design.",
        kind="design",
        policy=_policy(revisions=0),
        dispatcher=dispatcher,
        run_id="mc-exhausted",
    )

    assert result.status is MakerCheckerStatus.HUMAN_STOP
    assert result.human_stop is not None
    assert result.human_stop.reason.value == "retry-budget-exhausted"
    assert result.iterations == 1


def test_stale_reviewer_digest_fails_closed(tmp_path: Path) -> None:
    (tmp_path / ".ckit").mkdir()
    dispatcher = ScriptedDispatcher(
        [_maker("draft"), _review("PASS", stale_artifact_digest=True)]
    )

    result = run_maker_checker(
        tmp_path,
        task="Draft a design.",
        kind="design",
        policy=_policy(),
        dispatcher=dispatcher,
        run_id="mc-stale",
    )

    assert result.status is MakerCheckerStatus.HUMAN_STOP
    assert result.human_stop is not None
    assert result.human_stop.reason.value == "conflicting-evidence"


def test_wait_timeout_cancels_the_owned_dispatch(tmp_path: Path) -> None:
    (tmp_path / ".ckit").mkdir()
    dispatcher = ScriptedDispatcher([_maker("never used")], time_out_at=1)

    result = run_maker_checker(
        tmp_path,
        task="Draft a design.",
        kind="design",
        policy=_policy(),
        dispatcher=dispatcher,
        run_id="mc-timeout",
        timeout_seconds=0.01,
    )

    assert result.status is MakerCheckerStatus.HUMAN_STOP
    assert result.human_stop is not None
    assert result.human_stop.reason.value == "retry-budget-exhausted"
    assert len(dispatcher.cancelled) == 1
    assert dispatcher.cancelled[0].id == dispatcher.handles[0].id
    assert dispatcher.cancelled[0].route == "maker-checker-maker"


def test_code_patch_is_applied_only_in_a_preserved_owned_worktree(
    tmp_path: Path,
) -> None:
    _init_git_repo(tmp_path)
    patch = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1 +1 @@
-answer = 1
+answer = 42
"""
    dispatcher = ScriptedDispatcher(
        [_maker(patch, kind="unified-diff"), _review("PASS")]
    )

    result = run_maker_checker(
        tmp_path,
        task="Change the answer to 42.",
        kind="code",
        policy=_policy(),
        dispatcher=dispatcher,
        run_id="mc-code",
    )

    assert result.status is MakerCheckerStatus.PASSED
    assert result.workspace is not None
    workspace = Path(result.workspace)
    assert workspace != tmp_path.resolve()
    assert (workspace / "app.py").read_text(encoding="utf-8") == "answer = 42\n"
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "answer = 1\n"
    assert dispatcher.requests[0].workspace == str(workspace)
    assert dispatcher.requests[1].workspace == str(workspace)


def test_code_patch_can_add_a_visible_intent_to_add_file(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    patch = """diff --git a/feature.py b/feature.py
new file mode 100644
--- /dev/null
+++ b/feature.py
@@ -0,0 +1 @@
+enabled = True
"""
    result = run_maker_checker(
        tmp_path,
        task="Add a visible feature module.",
        kind="code",
        policy=_policy(),
        dispatcher=ScriptedDispatcher(
            [_maker(patch, kind="unified-diff"), _review("PASS")]
        ),
        run_id="mc-visible-add",
    )

    assert result.status is MakerCheckerStatus.PASSED
    workspace = Path(result.workspace or "")
    assert (workspace / "feature.py").read_text(encoding="utf-8") == "enabled = True\n"
    assert (
        subprocess.run(
            [
                "git",
                "-C",
                str(workspace),
                "ls-files",
                "--error-unmatch",
                "feature.py",
            ],
            check=False,
            capture_output=True,
        ).returncode
        == 0
    )


def test_code_artifact_planning_never_executes_repository_clean_filter(
    tmp_path: Path,
) -> None:
    _init_git_repo(tmp_path)
    marker = tmp_path.parent / f"{tmp_path.name}-clean-filter-ran"
    filter_script = tmp_path.parent / f"{tmp_path.name}-clean-filter.sh"
    filter_script.write_text(
        '#!/bin/sh\ntouch "$1"\ncat\n',
        encoding="utf-8",
    )
    filter_script.chmod(0o700)
    filter_command = f"{shlex.quote(str(filter_script))} {shlex.quote(str(marker))}"
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "filter.audit.clean", filter_command],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "filter.audit.smudge", "cat"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "filter.audit.required", "true"],
        check=True,
    )
    (tmp_path / ".gitattributes").write_text("*.py filter=audit\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", ".gitattributes"], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-qm", "add clean filter"], check=True
    )
    marker.unlink(missing_ok=True)
    patch = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1 +1 @@
-answer = 1
+answer = 2
"""

    result = run_maker_checker(
        tmp_path,
        task="Change the answer without invoking repository filters.",
        kind="code",
        policy=_policy(),
        dispatcher=ScriptedDispatcher(
            [_maker(patch, kind="unified-diff"), _review("PASS")]
        ),
        run_id="mc-no-clean-filter",
    )

    assert result.status is MakerCheckerStatus.PASSED
    assert not marker.exists()


def test_code_patch_cannot_modify_managed_control_plane(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    patch = """diff --git a/.ckit/config.json b/.ckit/config.json
new file mode 100644
--- /dev/null
+++ b/.ckit/config.json
@@ -0,0 +1 @@
+unsafe
"""
    dispatcher = ScriptedDispatcher([_maker(patch, kind="unified-diff")])

    result = run_maker_checker(
        tmp_path,
        task="Change managed configuration.",
        kind="code",
        policy=_policy(),
        dispatcher=dispatcher,
        run_id="mc-protected",
    )

    assert result.status is MakerCheckerStatus.HUMAN_STOP
    assert result.human_stop is not None
    assert result.human_stop.reason.value == "scope-expansion"
    assert len(dispatcher.requests) == 1


def test_resume_reuses_frozen_reviewer_stage_without_replaying_maker(
    tmp_path: Path,
) -> None:
    (tmp_path / ".ckit").mkdir()
    crashing = CrashBeforeReviewerDispatcher([_maker("durable draft")])

    with pytest.raises(SimulatedCoordinatorCrash):
        run_maker_checker(
            tmp_path,
            task="Draft a durable design.",
            kind="design",
            policy=_policy(),
            dispatcher=crashing,
            run_id="mc-resume",
        )

    active = json.loads(
        (tmp_path / ".ckit/state/pipeline-snapshot.json").read_text(encoding="utf-8")
    )
    assert active["status"] == "active"
    assert active["stage"] == "reviewer"
    assert active["maker_checker"]["attempts"][-1]["status"] == "running"
    before_preflight = (tmp_path / ".ckit/state/pipeline-snapshot.json").read_bytes()
    frozen = load_frozen_maker_checker_run(tmp_path, "mc-resume")
    assert frozen.run_id == "mc-resume"
    assert frozen.kind is DeliverableKind.DESIGN
    assert frozen.max_revisions == 2
    assert frozen.maker.requested_model == "claude-maker-model"
    assert frozen.reviewer.provider == "codex"
    assert (
        tmp_path / ".ckit/state/pipeline-snapshot.json"
    ).read_bytes() == before_preflight

    resumed = ScriptedDispatcher([_review("PASS")])
    result = run_maker_checker(
        tmp_path,
        task=None,
        kind="auto",
        policy=_policy(),
        dispatcher=resumed,
        resume_run_id="mc-resume",
    )

    assert result.status is MakerCheckerStatus.PASSED
    assert [request.execution_slot for request in resumed.requests] == [
        ExecutionSlot.REVIEWER
    ]
    terminal = json.loads(
        (tmp_path / ".ckit/state/pipeline-snapshot.json").read_text(encoding="utf-8")
    )
    attempts = terminal["maker_checker"]["attempts"]
    assert [item["status"] for item in attempts] == [
        "succeeded",
        "interrupted",
        "succeeded",
    ]
    assert attempts[-1]["predecessor_attempt"] == attempts[-2]["attempt_id"]
    coherent, validation_messages = validate_maker_checker_snapshot(tmp_path, terminal)
    assert coherent, "\n".join(validation_messages)


def test_resume_rejects_artifact_policy_and_worktree_drift(tmp_path: Path) -> None:
    (tmp_path / ".ckit").mkdir()
    crashing = CrashBeforeReviewerDispatcher([_maker("durable draft")])
    with pytest.raises(SimulatedCoordinatorCrash):
        run_maker_checker(
            tmp_path,
            task="Draft a durable design.",
            kind="design",
            policy=_policy(),
            dispatcher=crashing,
            run_id="mc-drift",
        )
    active_snapshot = json.loads(
        (tmp_path / ".ckit/state/pipeline-snapshot.json").read_text(encoding="utf-8")
    )
    artifact = tmp_path / active_snapshot["maker_checker"]["artifact"]["path"]
    artifact.write_text("tampered", encoding="utf-8")
    with pytest.raises(
        MakerCheckerError, match="artifact digest mismatch|hash mismatch"
    ):
        run_maker_checker(
            tmp_path,
            policy=_policy(),
            dispatcher=ScriptedDispatcher([]),
            resume_run_id="mc-drift",
        )

    other_root = tmp_path / "code"
    other_root.mkdir()
    _init_git_repo(other_root)
    patch = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1 +1 @@
-answer = 1
+answer = 2
"""
    crashing_code = CrashBeforeReviewerDispatcher([_maker(patch, kind="unified-diff")])
    with pytest.raises(SimulatedCoordinatorCrash):
        run_maker_checker(
            other_root,
            task="Change the answer.",
            kind="code",
            policy=_policy(),
            dispatcher=crashing_code,
            run_id="mc-worktree-drift",
        )
    state = json.loads(
        (other_root / ".ckit/state/pipeline-snapshot.json").read_text(encoding="utf-8")
    )
    workspace = (
        other_root / state["maker_checker"]["workspace"]["target_path"]
    ).resolve()
    (workspace / "app.py").write_text("answer = 3\n", encoding="utf-8")
    with pytest.raises(MakerCheckerError, match="worktree content changed"):
        run_maker_checker(
            other_root,
            policy=_policy(),
            dispatcher=ScriptedDispatcher([]),
            resume_run_id="mc-worktree-drift",
        )


def test_resume_rejects_frozen_task_kind_and_reused_id_but_ignores_new_defaults(
    tmp_path: Path,
) -> None:
    (tmp_path / ".ckit").mkdir()
    crashing = CrashBeforeReviewerDispatcher([_maker("draft")])
    with pytest.raises(SimulatedCoordinatorCrash):
        run_maker_checker(
            tmp_path,
            task="Draft a design.",
            kind="design",
            policy=_policy(),
            dispatcher=crashing,
            run_id="mc-frozen",
        )
    with pytest.raises(MakerCheckerError, match="task differs"):
        run_maker_checker(
            tmp_path,
            task="Different task.",
            policy=_policy(),
            dispatcher=ScriptedDispatcher([]),
            resume_run_id="mc-frozen",
        )
    with pytest.raises(MakerCheckerError, match="kind differs"):
        run_maker_checker(
            tmp_path,
            task="Draft a design.",
            kind="specification",
            policy=_policy(),
            dispatcher=ScriptedDispatcher([]),
            resume_run_id="mc-frozen",
        )
    resumed = run_maker_checker(
        tmp_path,
        policy=_policy(revisions=0),
        dispatcher=ScriptedDispatcher([_review("PASS")]),
        resume_run_id="mc-frozen",
    )
    assert resumed.status is MakerCheckerStatus.PASSED
    with pytest.raises(MakerCheckerError, match="artifact tree already exists"):
        run_maker_checker(
            tmp_path,
            task="Draft another design.",
            kind="design",
            policy=_policy(),
            dispatcher=ScriptedDispatcher([]),
            run_id="mc-frozen",
        )


def test_resume_rejects_revision_budget_drift_from_frozen_policy(
    tmp_path: Path,
) -> None:
    (tmp_path / ".ckit").mkdir()
    with pytest.raises(SimulatedCoordinatorCrash):
        run_maker_checker(
            tmp_path,
            task="Draft a durable design.",
            kind="design",
            policy=_policy(revisions=1),
            dispatcher=CrashAtSlotDispatcher(ExecutionSlot.MAKER, []),
            run_id="mc-budget-drift",
        )
    snapshot_path = tmp_path / ".ckit/state/pipeline-snapshot.json"
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    snapshot["maker_checker"]["max_revisions"] = 2
    snapshot_path.write_text(json.dumps(snapshot) + "\n", encoding="utf-8")

    coherent, messages = validate_maker_checker_snapshot(tmp_path, snapshot)
    assert not coherent
    assert any("revision budget differs" in message for message in messages)
    with pytest.raises(MakerCheckerError, match="revision budget differs"):
        run_maker_checker(
            tmp_path,
            dispatcher=ScriptedDispatcher([]),
            resume_run_id="mc-budget-drift",
        )


def test_codex_tier_null_binding_is_frozen_and_resumes(tmp_path: Path) -> None:
    (tmp_path / ".ckit").mkdir()
    policy = ExecutionPolicy(
        maker=WorkerBinding(
            Runtime.CLAUDE,
            ModelChoice(ModelChoiceKind.EXACT, "claude-maker-model"),
        ),
        reviewer=WorkerBinding(
            Runtime.CODEX,
            ModelChoice(ModelChoiceKind.TIER, "balanced"),
        ),
        max_revisions=1,
    )
    with pytest.raises(SimulatedCoordinatorCrash):
        run_maker_checker(
            tmp_path,
            task="Draft a tier-bound design.",
            kind="design",
            policy=policy,
            dispatcher=CrashBeforeReviewerDispatcher([_maker("draft")]),
            run_id="mc-codex-tier-default",
        )
    snapshot = json.loads(
        (tmp_path / ".ckit/state/pipeline-snapshot.json").read_text(encoding="utf-8")
    )
    assert snapshot["maker_checker"]["bindings"]["reviewer"]["requested_model"] is None
    assert validate_maker_checker_snapshot(tmp_path, snapshot)[0]
    frozen = load_frozen_maker_checker_run(tmp_path, "mc-codex-tier-default")
    assert frozen.reviewer.requested_model is None

    result = run_maker_checker(
        tmp_path,
        dispatcher=ScriptedDispatcher([_review("PASS")]),
        resume_run_id="mc-codex-tier-default",
    )
    assert result.status is MakerCheckerStatus.PASSED


@pytest.mark.parametrize("mutation", ["missing-next", "extra-key"])
def test_resume_rejects_snapshot_schema_drift(tmp_path: Path, mutation: str) -> None:
    (tmp_path / ".ckit").mkdir()
    with pytest.raises(SimulatedCoordinatorCrash):
        run_maker_checker(
            tmp_path,
            task="Draft a schema-bound design.",
            kind="design",
            policy=_policy(),
            dispatcher=CrashAtSlotDispatcher(ExecutionSlot.MAKER, []),
            run_id="mc-schema-drift",
        )
    snapshot_path = tmp_path / ".ckit/state/pipeline-snapshot.json"
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    if mutation == "missing-next":
        del snapshot["next"]
    else:
        snapshot["unexpected"] = True
    snapshot_path.write_text(json.dumps(snapshot) + "\n", encoding="utf-8")

    coherent, messages = validate_maker_checker_snapshot(tmp_path, snapshot)
    assert not coherent
    assert any("schema invalid" in message for message in messages)
    with pytest.raises(MakerCheckerError, match="schema invalid"):
        run_maker_checker(
            tmp_path,
            dispatcher=ScriptedDispatcher([]),
            resume_run_id="mc-schema-drift",
        )


def test_dispatch_handle_wrong_route_fails_closed(tmp_path: Path) -> None:
    (tmp_path / ".ckit").mkdir()
    dispatcher = WrongRouteDispatcher([_maker("unused")])
    result = run_maker_checker(
        tmp_path,
        task="Draft a design.",
        kind="design",
        policy=_policy(),
        dispatcher=dispatcher,
        run_id="mc-wrong-route",
    )
    assert result.status is MakerCheckerStatus.HUMAN_STOP
    assert result.human_stop is not None
    assert result.human_stop.reason.value == "conflicting-evidence"
    assert len(dispatcher.cancelled) == 1
    assert dispatcher.cancelled[0].id == dispatcher.handles[0].id
    assert dispatcher.cancelled[0].route == "maker-checker-reviewer"


def test_retry_reservation_failure_leaves_no_phantom_dispatch_owner(
    tmp_path: Path,
) -> None:
    (tmp_path / ".ckit").mkdir()
    dispatcher = RetryReservationFailureDispatcher([_maker("unused")])

    result = run_maker_checker(
        tmp_path,
        task="Draft a design with a failing transport.",
        kind="design",
        policy=_policy(),
        dispatcher=dispatcher,
        run_id="mc-retry-reservation-failure",
    )

    assert result.status is MakerCheckerStatus.HUMAN_STOP
    assert result.human_stop is not None
    assert result.human_stop.reason.value == "retry-budget-exhausted"
    assert len(dispatcher.retry_calls) == 1
    snapshot = json.loads(
        (tmp_path / ".ckit/state/pipeline-snapshot.json").read_text(encoding="utf-8")
    )
    assert snapshot["maker_checker"]["unsafe_dispatch"] is None
    assert validate_maker_checker_snapshot(tmp_path, snapshot)[0]


def test_terminal_collect_failure_clears_owner_without_duplicate_cancel(
    tmp_path: Path,
) -> None:
    (tmp_path / ".ckit").mkdir()
    dispatcher = TerminalCollectFailureDispatcher([_maker("unused")])

    result = run_maker_checker(
        tmp_path,
        task="Draft a design with malformed terminal transport evidence.",
        kind="design",
        policy=_policy(),
        dispatcher=dispatcher,
        run_id="mc-terminal-collect-failure",
    )

    assert result.status is MakerCheckerStatus.HUMAN_STOP
    assert result.human_stop is not None
    assert result.human_stop.reason.value == "conflicting-evidence"
    snapshot = json.loads(
        (tmp_path / ".ckit/state/pipeline-snapshot.json").read_text(encoding="utf-8")
    )
    assert snapshot["maker_checker"]["unsafe_dispatch"] is None
    assert validate_maker_checker_snapshot(tmp_path, snapshot)[0]


def test_pass_findings_remain_public_as_redacted_residual_risks(
    tmp_path: Path,
) -> None:
    (tmp_path / ".ckit").mkdir()
    raw_secret = "secret-value-123456789"
    pem_body = "PUBLIC_PEM_BODY_MUST_NOT_LEAK_4f2a"
    low = {
        "finding_id": "F-LOW",
        "severity": "low",
        "message": f"Keep API_TOKEN={raw_secret} out of examples.",
        "evidence": ["artifact://criterion-1"],
    }
    result = run_maker_checker(
        tmp_path,
        task="Draft a safely reported design.",
        kind="design",
        policy=_policy(),
        dispatcher=ScriptedDispatcher(
            [
                _maker("# Safe design\n"),
                _review(
                    "PASS",
                    findings=[low],
                    residual_risks=[
                        f"Authorization: Bearer {raw_secret}",
                        f"https://user:{raw_secret}@example.invalid/path",
                        "-----BEGIN PRIVATE KEY-----\n"
                        + pem_body
                        + "\n-----END PRIVATE KEY-----",
                    ],
                ),
            ]
        ),
        run_id="mc-redacted-risks",
    )

    assert result.status is MakerCheckerStatus.PASSED
    assert len(result.residual_risks) == 4
    public = json.dumps(result.to_dict())
    assert raw_secret not in public
    assert pem_body not in public
    assert "END PRIVATE KEY" not in public
    assert "[REDACTED]" in public
    assert "F-LOW [low]" in public
    snapshot = json.loads(
        (tmp_path / ".ckit/state/pipeline-snapshot.json").read_text(encoding="utf-8")
    )
    response_path = snapshot["maker_checker"]["iteration_records"][0][
        "review_response_path"
    ]
    assert raw_secret in (tmp_path / response_path).read_text(encoding="utf-8")
    result_path = tmp_path / snapshot["result_path"]
    result_text = result_path.read_text(encoding="utf-8")
    assert pem_body not in result_text
    assert "END PRIVATE KEY" not in result_text
    assert validate_maker_checker_snapshot(tmp_path, snapshot)[0]


def test_unconfirmed_cancellation_requires_exact_operator_reconciliation(
    tmp_path: Path,
) -> None:
    (tmp_path / ".ckit").mkdir()
    dispatcher = CancelFailureDispatcher([_maker("never collected")], time_out_at=1)
    with pytest.raises(MakerCheckerError, match="cancellation could not be confirmed"):
        run_maker_checker(
            tmp_path,
            task="Draft a recoverable design.",
            kind="design",
            policy=_policy(),
            dispatcher=dispatcher,
            run_id="mc-unsafe-cancel",
            timeout_seconds=0.01,
        )

    snapshot_path = tmp_path / ".ckit/state/pipeline-snapshot.json"
    active = json.loads(snapshot_path.read_text(encoding="utf-8"))
    unsafe = active["maker_checker"]["unsafe_dispatch"]
    assert active["status"] == "active"
    assert validate_maker_checker_snapshot(tmp_path, active)[0]
    status_ok, status_messages = pipeline.status(tmp_path)
    assert status_ok
    rendered_status = "\n".join(status_messages)
    assert unsafe["dispatch_id"] in rendered_status
    assert str(unsafe["dispatch_attempt"]) in rendered_status
    ledger = maker_checker_module._RunLedger(
        tmp_path, maker_checker_module.ProjectFS(tmp_path), active
    )
    with pytest.raises(MakerCheckerError, match="ownership marker changed"):
        ledger.clear_unsafe_dispatch(
            unsafe["attempt_id"],
            dispatch_id=unsafe["dispatch_id"],
            dispatch_attempt=unsafe["dispatch_attempt"] + 1,
        )
    unchanged = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert unchanged["maker_checker"]["unsafe_dispatch"] == unsafe
    with pytest.raises(MakerCheckerError, match="termination is unconfirmed"):
        run_maker_checker(
            tmp_path,
            dispatcher=ScriptedDispatcher([]),
            resume_run_id="mc-unsafe-cancel",
        )
    aborted, messages = pipeline.abort(tmp_path)
    assert not aborted
    assert any("termination is unconfirmed" in message for message in messages)
    with pytest.raises(MakerCheckerError, match="does not match"):
        confirm_maker_checker_dispatch_terminated(
            tmp_path,
            run_id="mc-unsafe-cancel",
            attempt_id=unsafe["attempt_id"],
            route="maker-checker-reviewer",
            dispatch_id=unsafe["dispatch_id"],
            dispatch_attempt=unsafe["dispatch_attempt"],
            evidence="host job lookup reports terminal",
        )

    proof_path = confirm_maker_checker_dispatch_terminated(
        tmp_path,
        run_id="mc-unsafe-cancel",
        attempt_id=unsafe["attempt_id"],
        route=unsafe["route"],
        dispatch_id=unsafe["dispatch_id"],
        dispatch_attempt=unsafe["dispatch_attempt"],
        evidence="host job dispatch-1 was inspected and reports terminated",
    )
    assert (tmp_path / proof_path).is_file()
    reconciled = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert reconciled["maker_checker"]["unsafe_dispatch"] is None
    assert reconciled["maker_checker"]["attempts"][-1]["status"] == "interrupted"
    assert validate_maker_checker_snapshot(tmp_path, reconciled)[0]

    aborted, messages = pipeline.abort(tmp_path)
    assert aborted, "\n".join(messages)
    terminal = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert validate_maker_checker_snapshot(tmp_path, terminal)[0]


def test_codex_termination_confirmation_removes_crash_left_credential_replica(
    tmp_path: Path,
) -> None:
    (tmp_path / ".ckit").mkdir()
    dispatcher = CancelFailureDispatcher(
        [_maker("draft"), _review("PASS")], time_out_at=2
    )
    with pytest.raises(MakerCheckerError, match="cancellation could not be confirmed"):
        run_maker_checker(
            tmp_path,
            task="Draft a design with a recoverable Codex review.",
            kind="design",
            policy=_policy(),
            dispatcher=dispatcher,
            run_id="mc-codex-credential-recovery",
            timeout_seconds=0.01,
        )

    snapshot_path = tmp_path / ".ckit/state/pipeline-snapshot.json"
    active = json.loads(snapshot_path.read_text(encoding="utf-8"))
    unsafe = active["maker_checker"]["unsafe_dispatch"]
    assert active["maker_checker"]["attempts"][-1]["provider"] == "codex"
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    auth_path = codex_home / "auth.json"
    auth_path.write_text(
        '{"tokens":{"access_token":"private-test-token"}}\n', encoding="utf-8"
    )
    auth_path.chmod(0o600)
    isolation = CodexAppServerBackend._isolated_environment(
        {
            "HOME": str(tmp_path),
            "CODEX_HOME": str(codex_home),
            "CKIT_NATIVE_DISPATCH_ID": unsafe["dispatch_id"],
            "CKIT_NATIVE_DISPATCH_ATTEMPT": str(unsafe["dispatch_attempt"]),
        },
        copy_auth=True,
    )
    assert (isolation.root / "auth.json").is_file()

    confirm_maker_checker_dispatch_terminated(
        tmp_path,
        run_id="mc-codex-credential-recovery",
        attempt_id=unsafe["attempt_id"],
        route=unsafe["route"],
        dispatch_id=unsafe["dispatch_id"],
        dispatch_attempt=unsafe["dispatch_attempt"],
        evidence="the exact Codex process and descendants are terminated",
    )

    assert not isolation.root.exists()
    reconciled = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert reconciled["maker_checker"]["unsafe_dispatch"] is None
    assert validate_maker_checker_snapshot(tmp_path, reconciled)[0]


def test_reviewer_findings_are_bound_to_hash_verified_response_before_resume(
    tmp_path: Path,
) -> None:
    (tmp_path / ".ckit").mkdir()
    with pytest.raises(SimulatedCoordinatorCrash):
        run_maker_checker(
            tmp_path,
            task="Draft a review-bound design.",
            kind="design",
            policy=_policy(),
            dispatcher=CrashOnThirdSpawnDispatcher(
                [_maker("first"), _review("FAIL", findings=[_finding()])]
            ),
            run_id="mc-finding-binding",
        )
    snapshot_path = tmp_path / ".ckit/state/pipeline-snapshot.json"
    active = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert active["stage"] == "maker"
    assert validate_maker_checker_snapshot(tmp_path, active)[0]

    record = active["maker_checker"]["iteration_records"][0]
    review_path = tmp_path / record["review_response_path"]
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["findings"][0]["message"] = "coherently rehashed but different finding"
    review_path.write_text(
        json.dumps(review, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    rebound = maker_checker_module._bytes_digest(review_path.read_bytes())
    record["review_response_sha256"] = rebound
    reviewer_attempt = next(
        attempt
        for attempt in active["maker_checker"]["attempts"]
        if attempt["execution_slot"] == "reviewer"
    )
    reviewer_attempt["output_sha256"] = rebound
    snapshot_path.write_text(json.dumps(active) + "\n", encoding="utf-8")

    coherent, messages = validate_maker_checker_snapshot(tmp_path, active)
    assert not coherent
    assert any("findings differ" in message for message in messages)
    with pytest.raises(MakerCheckerError, match="findings differ"):
        run_maker_checker(
            tmp_path,
            dispatcher=ScriptedDispatcher([]),
            resume_run_id="mc-finding-binding",
        )


def test_code_revision_is_incremental_and_cannot_expand_initial_path_set(
    tmp_path: Path,
) -> None:
    _init_git_repo(tmp_path)
    first = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1 +1 @@
-answer = 1
+answer = 2
"""
    expanded = """diff --git a/extra.py b/extra.py
new file mode 100644
--- /dev/null
+++ b/extra.py
@@ -0,0 +1 @@
+unsafe_scope_growth = True
"""
    dispatcher = ScriptedDispatcher(
        [
            _maker(first, kind="unified-diff"),
            _review("FAIL", findings=[_finding()]),
            _maker(
                expanded,
                kind="unified-diff",
                dispositions=[
                    {
                        "finding_id": "F-001",
                        "disposition": "fixed",
                        "evidence": ["artifact://criterion-1"],
                        "note": "Attempted another file.",
                    }
                ],
            ),
        ]
    )
    result = run_maker_checker(
        tmp_path,
        task="Change the answer safely.",
        kind="code",
        policy=_policy(),
        dispatcher=dispatcher,
        run_id="mc-path-freeze",
    )
    assert result.status is MakerCheckerStatus.HUMAN_STOP
    assert result.human_stop is not None
    assert result.human_stop.reason.value == "scope-expansion"
    assert "incremental unified diff" in dispatcher.requests[2].objective
    assert not (Path(result.workspace or "") / "extra.py").exists()


def test_every_durable_transition_persists_a_coherent_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".ckit").mkdir()
    original = maker_checker_module._RunLedger.replace

    def checked_replace(
        ledger: maker_checker_module._RunLedger, document: dict[str, object]
    ) -> None:
        original(ledger, document)
        coherent, messages = validate_maker_checker_snapshot(
            ledger.root, ledger.document
        )
        assert coherent, "\n".join(messages)

    monkeypatch.setattr(maker_checker_module._RunLedger, "replace", checked_replace)
    result = run_maker_checker(
        tmp_path,
        task="Draft an atomic design.",
        kind="design",
        policy=_policy(),
        dispatcher=ScriptedDispatcher([_maker("atomic"), _review("PASS")]),
        run_id="mc-atomic",
    )
    assert result.status is MakerCheckerStatus.PASSED


def test_resume_reconciles_a_patch_applied_before_its_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init_git_repo(tmp_path)
    patch = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1 +1 @@
-answer = 1
+answer = 2
"""
    original = maker_checker_module._RunLedger.replace
    crashed = False

    def crash_before_apply_checkpoint(
        ledger: maker_checker_module._RunLedger, document: dict[str, object]
    ) -> None:
        nonlocal crashed
        if (
            not crashed
            and ledger.document.get("stage") == "apply"
            and document.get("stage") == "reviewer"
        ):
            crashed = True
            raise SimulatedCoordinatorCrash
        original(ledger, document)

    monkeypatch.setattr(
        maker_checker_module._RunLedger, "replace", crash_before_apply_checkpoint
    )
    with pytest.raises(SimulatedCoordinatorCrash):
        run_maker_checker(
            tmp_path,
            task="Change the answer.",
            kind="code",
            policy=_policy(),
            dispatcher=ScriptedDispatcher([_maker(patch, kind="unified-diff")]),
            run_id="mc-apply-crash",
        )
    snapshot = json.loads(
        (tmp_path / ".ckit/state/pipeline-snapshot.json").read_text(encoding="utf-8")
    )
    assert snapshot["stage"] == "apply"
    workspace = Path(snapshot["maker_checker"]["workspace"]["target_path"])
    workspace = (tmp_path / workspace).resolve()
    assert (workspace / "app.py").read_text(encoding="utf-8") == "answer = 2\n"
    assert validate_maker_checker_snapshot(tmp_path, snapshot)[0]

    resumed_dispatcher = ScriptedDispatcher([_review("PASS")])
    result = run_maker_checker(
        tmp_path,
        dispatcher=resumed_dispatcher,
        resume_run_id="mc-apply-crash",
    )
    assert result.status is MakerCheckerStatus.PASSED
    assert [request.execution_slot for request in resumed_dispatcher.requests] == [
        ExecutionSlot.REVIEWER
    ]


@pytest.mark.parametrize("stage", ["setup", "maker", "apply", "reviewer"])
def test_pipeline_abort_is_coherent_at_every_active_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
) -> None:
    if stage == "apply":
        _init_git_repo(tmp_path)
        patch = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1 +1 @@
-answer = 1
+answer = 2
"""

        def crash_apply(*_args: object, **_kwargs: object) -> None:
            raise SimulatedCoordinatorCrash

        monkeypatch.setattr(maker_checker_module, "_complete_apply_intent", crash_apply)
        invocation = {
            "task": "Change the answer.",
            "kind": "code",
            "dispatcher": ScriptedDispatcher([_maker(patch, kind="unified-diff")]),
        }
    else:
        (tmp_path / ".ckit").mkdir()
        if stage == "setup":

            def crash_setup(*_args: object, **_kwargs: object) -> None:
                raise SimulatedCoordinatorCrash

            monkeypatch.setattr(maker_checker_module, "_ensure_setup", crash_setup)
            dispatcher: ScriptedDispatcher = ScriptedDispatcher([])
        elif stage == "maker":
            dispatcher = CrashAtSlotDispatcher(ExecutionSlot.MAKER, [])
        else:
            dispatcher = CrashAtSlotDispatcher(
                ExecutionSlot.REVIEWER, [_maker("draft")]
            )
        invocation = {
            "task": "Draft an abortable design.",
            "kind": "design",
            "dispatcher": dispatcher,
        }

    with pytest.raises(SimulatedCoordinatorCrash):
        run_maker_checker(
            tmp_path,
            policy=_policy(),
            run_id=f"mc-abort-{stage}",
            **invocation,
        )
    active = json.loads(
        (tmp_path / ".ckit/state/pipeline-snapshot.json").read_text(encoding="utf-8")
    )
    assert active["stage"] == stage
    monkeypatch.undo()

    aborted, messages = pipeline.abort(tmp_path)
    assert aborted, "\n".join(messages)
    terminal = json.loads(
        (tmp_path / ".ckit/state/pipeline-snapshot.json").read_text(encoding="utf-8")
    )
    assert terminal["status"] == "aborted"
    assert terminal["stage"] == "human-stop"
    assert terminal["human_stop"]["reason"] == "operator-aborted"
    assert terminal["maker_checker"]["pending_apply"] is None
    assert not any(
        attempt["status"] == "running"
        for attempt in terminal["maker_checker"]["attempts"]
    )
    assert (tmp_path / terminal["result_path"]).is_file()
    coherent, validation_messages = validate_maker_checker_snapshot(tmp_path, terminal)
    assert coherent, "\n".join(validation_messages)
    with ExitStack() as stack:
        assert schemas.validate_doc(terminal, "pipeline-snapshot", stack) == []
    if stage == "apply":
        workspace = (
            tmp_path / terminal["maker_checker"]["workspace"]["target_path"]
        ).resolve()
        assert (workspace / "app.py").read_text(encoding="utf-8") == "answer = 1\n"


def test_abort_binds_a_worktree_created_before_setup_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init_git_repo(tmp_path)
    original = maker_checker_module._RunLedger.replace

    def crash_after_worktree_create(
        ledger: maker_checker_module._RunLedger, document: dict[str, object]
    ) -> None:
        if ledger.document.get("stage") == "setup" and document.get("stage") == "maker":
            raise SimulatedCoordinatorCrash
        original(ledger, document)

    monkeypatch.setattr(
        maker_checker_module._RunLedger, "replace", crash_after_worktree_create
    )
    with pytest.raises(SimulatedCoordinatorCrash):
        run_maker_checker(
            tmp_path,
            task="Change the answer.",
            kind="code",
            policy=_policy(),
            dispatcher=ScriptedDispatcher([]),
            run_id="mc-setup-worktree-abort",
        )
    monkeypatch.setattr(maker_checker_module._RunLedger, "replace", original)

    aborted, messages = pipeline.abort(tmp_path)
    assert aborted, "\n".join(messages)
    terminal = json.loads(
        (tmp_path / ".ckit/state/pipeline-snapshot.json").read_text(encoding="utf-8")
    )
    assert terminal["maker_checker"]["workspace"] is not None
    assert validate_maker_checker_snapshot(tmp_path, terminal)[0]


def test_abort_normalizes_a_post_ledger_worktree_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init_git_repo(tmp_path)
    with pytest.raises(SimulatedCoordinatorCrash):
        run_maker_checker(
            tmp_path,
            task="Change the answer.",
            kind="code",
            policy=_policy(),
            dispatcher=CrashAtSlotDispatcher(ExecutionSlot.MAKER, []),
            run_id="mc-abort-worktree-failure",
        )

    def fail_after_terminal_ledger(
        _manager: object,
        _run_id: str,
        **_kwargs: object,
    ) -> object:
        raise maker_checker_module.WorktreeError("registry transition failed")

    monkeypatch.setattr(
        maker_checker_module.WorktreeManager,
        "abort_run",
        fail_after_terminal_ledger,
    )
    with pytest.raises(
        MakerCheckerError,
        match="maker-checker abort failed: registry transition failed",
    ):
        maker_checker_module.abort_maker_checker_run(
            tmp_path,
            run_id="mc-abort-worktree-failure",
        )

    terminal = json.loads(
        (tmp_path / ".ckit/state/pipeline-snapshot.json").read_text(encoding="utf-8")
    )
    assert terminal["status"] == "aborted"
    assert terminal["human_stop"]["reason"] == "operator-aborted"


def test_read_only_lifecycle_never_reconciles_a_creating_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init_git_repo(tmp_path)
    manager = maker_checker_module.WorktreeManager(tmp_path)

    def crash_before_add(*_args: object, **_kwargs: object) -> None:
        raise SimulatedCoordinatorCrash

    original = maker_checker_module.WorktreeManager._finish_creating
    monkeypatch.setattr(
        maker_checker_module.WorktreeManager,
        "_finish_creating",
        crash_before_add,
    )
    with pytest.raises(SimulatedCoordinatorCrash):
        run_maker_checker(
            tmp_path,
            task="Change the answer.",
            kind="code",
            policy=_policy(),
            dispatcher=ScriptedDispatcher([]),
            run_id="mc-creating-read-only",
            worktree_manager=manager,
        )
    monkeypatch.setattr(
        maker_checker_module.WorktreeManager, "_finish_creating", original
    )
    registry = tmp_path / manager.registry_rel
    before = registry.read_bytes()
    intent = manager.records("mc-creating-read-only")[0]
    target = tmp_path / intent.target_path
    assert intent.status is maker_checker_module.WorktreeStatus.CREATING
    assert not target.exists()

    valid, messages = validate_maker_checker_snapshot(tmp_path)
    assert not valid
    assert any("creation is incomplete" in message for message in messages)
    status_ok, _status_messages = pipeline.status(tmp_path)
    assert status_ok
    with pytest.raises(MakerCheckerError, match="creation is incomplete"):
        load_frozen_maker_checker_run(tmp_path, "mc-creating-read-only")
    assert registry.read_bytes() == before
    assert not target.exists()


def test_aborted_result_rejects_rehashed_unbound_residual_risk(tmp_path: Path) -> None:
    (tmp_path / ".ckit").mkdir()
    result = run_maker_checker(
        tmp_path,
        task="Draft a bounded design.",
        kind="design",
        policy=_policy(),
        dispatcher=ScriptedDispatcher([_maker("unused")], time_out_at=1),
        run_id="mc-aborted-risk-tamper",
        timeout_seconds=0.01,
    )
    assert result.status is MakerCheckerStatus.HUMAN_STOP
    snapshot_path = tmp_path / ".ckit/state/pipeline-snapshot.json"
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    result_path = tmp_path / snapshot["result_path"]
    result_record = json.loads(result_path.read_text(encoding="utf-8"))
    result_record["residual_risks"] = ["unbound risk"]
    result_path.write_text(json.dumps(result_record) + "\n", encoding="utf-8")
    snapshot["result_sha256"] = maker_checker_module._bytes_digest(
        result_path.read_bytes()
    )
    snapshot_path.write_text(json.dumps(snapshot) + "\n", encoding="utf-8")

    valid, messages = validate_maker_checker_snapshot(tmp_path, snapshot)
    assert not valid
    assert any("unbound residual risks" in message for message in messages)


def test_setup_resume_rejects_changes_in_a_prebinding_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init_git_repo(tmp_path)
    original = maker_checker_module._RunLedger.replace

    def crash_after_worktree_create(
        ledger: maker_checker_module._RunLedger, document: dict[str, object]
    ) -> None:
        if ledger.document.get("stage") == "setup" and document.get("stage") == "maker":
            raise SimulatedCoordinatorCrash
        original(ledger, document)

    monkeypatch.setattr(
        maker_checker_module._RunLedger, "replace", crash_after_worktree_create
    )
    with pytest.raises(SimulatedCoordinatorCrash):
        run_maker_checker(
            tmp_path,
            task="Change the answer.",
            kind="code",
            policy=_policy(),
            dispatcher=ScriptedDispatcher([]),
            run_id="mc-dirty-setup-worktree",
        )
    record = maker_checker_module.WorktreeManager(tmp_path).records(
        "mc-dirty-setup-worktree"
    )[0]
    workspace = (tmp_path / record.target_path).resolve()
    (workspace / "app.py").write_text("tampered = True\n", encoding="utf-8")
    monkeypatch.setattr(maker_checker_module._RunLedger, "replace", original)

    with pytest.raises(MakerCheckerError, match="differs from clean HEAD"):
        run_maker_checker(
            tmp_path,
            dispatcher=ScriptedDispatcher([]),
            resume_run_id="mc-dirty-setup-worktree",
        )


@pytest.mark.parametrize(
    ("patch", "forbidden_path"),
    [
        (
            """diff --git a/safe.txt b/safe.txt
index d97c5ea..e69de29 100644
--- \"a/.codex/config.toml\"
+++ /dev/null\t2026-01-01
@@ -1 +0,0 @@
-secret
""",
            ".codex/config.toml",
        ),
        (
            """diff --git a/.CODEX/config.toml b/.CODEX/config.toml
new file mode 100644
--- /dev/null
+++ b/.CODEX/config.toml
@@ -0,0 +1 @@
+unsafe
""",
            ".CODEX/config.toml",
        ),
        (
            """diff --git a/docs/AGENTS.md b/docs/AGENTS.md
new file mode 100644
--- /dev/null
+++ b/docs/AGENTS.md
@@ -0,0 +1 @@
+unsafe instruction
""",
            "docs/AGENTS.md",
        ),
        (
            """diff --git a/.claude-kit-managed-execution.lock b/.claude-kit-managed-execution.lock
new file mode 100644
--- /dev/null
+++ b/.claude-kit-managed-execution.lock
@@ -0,0 +1 @@
+attacker-controlled-lock
""",
            ".claude-kit-managed-execution.lock",
        ),
    ],
)
def test_adversarial_patch_headers_and_nested_control_paths_fail_closed(
    tmp_path: Path, patch: str, forbidden_path: str
) -> None:
    _init_git_repo(tmp_path)
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".codex/config.toml").write_text("secret\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", ".codex/config.toml"], check=True
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-qm", "control file"], check=True
    )
    result = run_maker_checker(
        tmp_path,
        task="Apply a constrained patch.",
        kind="code",
        policy=_policy(),
        dispatcher=ScriptedDispatcher([_maker(patch, kind="unified-diff")]),
        run_id="mc-adversarial-" + forbidden_path.replace("/", "-").replace(".", "x"),
    )
    assert result.status is MakerCheckerStatus.HUMAN_STOP
    assert result.human_stop is not None
    assert result.human_stop.reason.value == "scope-expansion"
    workspace = Path(result.workspace or "")
    assert (workspace / ".codex/config.toml").read_text(encoding="utf-8") == "secret\n"
    if forbidden_path.casefold() != ".codex/config.toml":
        assert not (workspace / forbidden_path).exists()


def test_ignored_new_file_is_rejected_before_worktree_mutation(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    (tmp_path / ".gitignore").write_text("ignored.py\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", ".gitignore"], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-qm", "ignore generated file"],
        check=True,
    )
    patch = """diff --git a/ignored.py b/ignored.py
new file mode 100644
--- /dev/null
+++ b/ignored.py
@@ -0,0 +1 @@
+invisible = True
"""
    result = run_maker_checker(
        tmp_path,
        task="Add a visible file.",
        kind="code",
        policy=_policy(),
        dispatcher=ScriptedDispatcher([_maker(patch, kind="unified-diff")]),
        run_id="mc-ignored-add",
    )
    assert result.status is MakerCheckerStatus.HUMAN_STOP
    assert not (Path(result.workspace or "") / "ignored.py").exists()


def test_patch_cannot_hide_an_addition_by_changing_gitignore(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    (tmp_path / ".gitignore").write_text("existing.log\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", ".gitignore"], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-qm", "baseline ignore"],
        check=True,
    )
    patch = """diff --git a/.gitignore b/.gitignore
--- a/.gitignore
+++ b/.gitignore
@@ -1 +1,2 @@
 existing.log
+hidden.py
diff --git a/hidden.py b/hidden.py
new file mode 100644
--- /dev/null
+++ b/hidden.py
@@ -0,0 +1 @@
+hidden = True
"""
    result = run_maker_checker(
        tmp_path,
        task="Add an auditable source file.",
        kind="code",
        policy=_policy(),
        dispatcher=ScriptedDispatcher([_maker(patch, kind="unified-diff")]),
        run_id="mc-ignore-race",
    )
    assert result.status is MakerCheckerStatus.HUMAN_STOP
    workspace = Path(result.workspace or "")
    assert (workspace / ".gitignore").read_text(encoding="utf-8") == "existing.log\n"
    assert not (workspace / "hidden.py").exists()


def test_rejected_out_of_scope_bytes_are_not_written_to_git_object_store(
    tmp_path: Path,
) -> None:
    _init_git_repo(tmp_path)
    secret_path = tmp_path / "private.txt"
    secret_path.write_text("baseline\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "private.txt"], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-qm", "private baseline"],
        check=True,
    )
    secret_path.write_text("REJECTED_SECRET_OBJECT_53af\n", encoding="utf-8")
    object_id = subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "hash-object",
            "--no-filters",
            "private.txt",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    patch = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1 +1 @@
-answer = 1
+answer = 2
"""

    with pytest.raises(
        maker_checker_module._PatchSafetyError,
        match="outside the frozen maker path set",
    ):
        maker_checker_module._expected_cumulative_diff(
            tmp_path, patch, allowed_paths={"app.py"}
        )

    missing = subprocess.run(
        ["git", "-C", str(tmp_path), "cat-file", "-e", object_id],
        check=False,
        capture_output=True,
    )
    assert missing.returncode != 0


def test_patch_git_commands_ignore_caller_repository_redirection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init_git_repo(tmp_path)
    redirected_git = tmp_path.parent / f"{tmp_path.name}-redirected-git"
    redirected_worktree = tmp_path.parent / f"{tmp_path.name}-redirected-worktree"
    redirected_git.mkdir()
    redirected_worktree.mkdir()
    hostile_index = tmp_path.parent / f"{tmp_path.name}-redirected-index"
    monkeypatch.setenv("GIT_DIR", str(redirected_git))
    monkeypatch.setenv("GIT_WORK_TREE", str(redirected_worktree))
    monkeypatch.setenv("GIT_INDEX_FILE", str(hostile_index))
    patch = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1 +1 @@
-answer = 1
+answer = 2
"""

    expected, paths = maker_checker_module._expected_cumulative_diff(
        tmp_path, patch, allowed_paths=set()
    )

    assert "answer = 2" in expected
    assert paths == {"app.py"}
    assert not hostile_index.exists()
    assert list(redirected_git.iterdir()) == []
    assert list(redirected_worktree.iterdir()) == []


def test_apply_recovery_rejects_an_injected_ignored_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init_git_repo(tmp_path)
    (tmp_path / ".gitignore").write_text("*.cache\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", ".gitignore"], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-qm", "ignore cache"], check=True
    )
    patch = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1 +1 @@
-answer = 1
+answer = 2
"""
    original = maker_checker_module._RunLedger.replace

    def crash_before_apply_checkpoint(
        ledger: maker_checker_module._RunLedger, document: dict[str, object]
    ) -> None:
        if (
            ledger.document.get("stage") == "apply"
            and document.get("stage") == "reviewer"
        ):
            raise SimulatedCoordinatorCrash
        original(ledger, document)

    monkeypatch.setattr(
        maker_checker_module._RunLedger, "replace", crash_before_apply_checkpoint
    )
    with pytest.raises(SimulatedCoordinatorCrash):
        run_maker_checker(
            tmp_path,
            task="Change the answer.",
            kind="code",
            policy=_policy(),
            dispatcher=ScriptedDispatcher([_maker(patch, kind="unified-diff")]),
            run_id="mc-apply-ignored-drift",
        )
    snapshot = json.loads(
        (tmp_path / ".ckit/state/pipeline-snapshot.json").read_text(encoding="utf-8")
    )
    workspace = (
        tmp_path / snapshot["maker_checker"]["workspace"]["target_path"]
    ).resolve()
    (workspace / "injected.cache").write_text("hidden\n", encoding="utf-8")
    monkeypatch.setattr(maker_checker_module._RunLedger, "replace", original)

    coherent, messages = validate_maker_checker_snapshot(tmp_path, snapshot)
    assert not coherent
    assert any("untracked or ignored" in message for message in messages)
    with pytest.raises(MakerCheckerError, match="untracked or ignored"):
        run_maker_checker(
            tmp_path,
            dispatcher=ScriptedDispatcher([]),
            resume_run_id="mc-apply-ignored-drift",
        )


def test_apply_recovery_rejects_hidden_index_tampering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init_git_repo(tmp_path)
    patch = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1 +1 @@
-answer = 1
+answer = 2
"""
    original = maker_checker_module._RunLedger.replace

    def crash_before_apply_checkpoint(
        ledger: maker_checker_module._RunLedger, document: dict[str, object]
    ) -> None:
        if (
            ledger.document.get("stage") == "apply"
            and document.get("stage") == "reviewer"
        ):
            raise SimulatedCoordinatorCrash
        original(ledger, document)

    monkeypatch.setattr(
        maker_checker_module._RunLedger, "replace", crash_before_apply_checkpoint
    )
    with pytest.raises(SimulatedCoordinatorCrash):
        run_maker_checker(
            tmp_path,
            task="Change the answer.",
            kind="code",
            policy=_policy(),
            dispatcher=ScriptedDispatcher([_maker(patch, kind="unified-diff")]),
            run_id="mc-apply-index-drift",
        )
    snapshot = json.loads(
        (tmp_path / ".ckit/state/pipeline-snapshot.json").read_text(encoding="utf-8")
    )
    workspace = (
        tmp_path / snapshot["maker_checker"]["workspace"]["target_path"]
    ).resolve()
    (workspace / "app.py").write_text("malicious = True\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(workspace), "add", "app.py"], check=True)
    (workspace / "app.py").write_text("answer = 2\n", encoding="utf-8")
    monkeypatch.setattr(maker_checker_module._RunLedger, "replace", original)

    coherent, messages = validate_maker_checker_snapshot(tmp_path, snapshot)
    assert not coherent
    assert any("index differs" in message for message in messages)
    with pytest.raises(MakerCheckerError, match="index differs"):
        run_maker_checker(
            tmp_path,
            dispatcher=ScriptedDispatcher([]),
            resume_run_id="mc-apply-index-drift",
        )


@pytest.mark.parametrize("initialize_submodule", [False, True])
def test_patch_below_gitlink_is_rejected_before_mutation(
    tmp_path: Path, initialize_submodule: bool
) -> None:
    submodule = tmp_path.parent / f"{tmp_path.name}-dependency"
    submodule.mkdir()
    subprocess.run(["git", "init", "-q", str(submodule)], check=True)
    subprocess.run(
        ["git", "-C", str(submodule), "config", "user.email", "test@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(submodule), "config", "user.name", "Test User"],
        check=True,
    )
    (submodule / "base.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(submodule), "add", "base.txt"], check=True)
    subprocess.run(["git", "-C", str(submodule), "commit", "-qm", "base"], check=True)
    _init_git_repo(tmp_path)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "-c",
            "protocol.file.allow=always",
            "submodule",
            "add",
            "-q",
            str(submodule),
            "vendor/dependency",
        ],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-qam", "add submodule"], check=True
    )
    patch = """diff --git a/vendor/dependency/new.py b/vendor/dependency/new.py
new file mode 100644
--- /dev/null
+++ b/vendor/dependency/new.py
@@ -0,0 +1 @@
+unsafe = True
"""
    if not initialize_submodule:
        subprocess.run(
            [
                "git",
                "-C",
                str(tmp_path),
                "submodule",
                "--quiet",
                "deinit",
                "-f",
                "--",
                "vendor/dependency",
            ],
            check=True,
        )
    with pytest.raises(maker_checker_module._PatchSafetyError, match="indexed gitlink"):
        maker_checker_module._apply_patch(tmp_path, patch, allowed_paths=set())
    assert not (tmp_path / "vendor/dependency/new.py").exists()


@pytest.mark.parametrize("initialize_submodule", [False, True])
def test_unchanged_gitlink_allows_unrelated_code_run(
    tmp_path: Path, initialize_submodule: bool
) -> None:
    submodule = tmp_path.parent / f"{tmp_path.name}-unchanged-dependency"
    submodule.mkdir()
    subprocess.run(["git", "init", "-q", str(submodule)], check=True)
    subprocess.run(
        ["git", "-C", str(submodule), "config", "user.email", "test@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(submodule), "config", "user.name", "Test User"],
        check=True,
    )
    (submodule / "base.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(submodule), "add", "base.txt"], check=True)
    subprocess.run(["git", "-C", str(submodule), "commit", "-qm", "base"], check=True)
    _init_git_repo(tmp_path)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "-c",
            "protocol.file.allow=always",
            "submodule",
            "add",
            "-q",
            str(submodule),
            "vendor/dependency",
        ],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-qam", "add submodule"], check=True
    )
    if not initialize_submodule:
        subprocess.run(
            [
                "git",
                "-C",
                str(tmp_path),
                "submodule",
                "--quiet",
                "deinit",
                "-f",
                "--",
                "vendor/dependency",
            ],
            check=True,
        )
    patch = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1 +1 @@
-answer = 1
+answer = 2
"""

    result = run_maker_checker(
        tmp_path,
        task="Change only the application answer.",
        kind="code",
        policy=_policy(),
        dispatcher=ScriptedDispatcher(
            [_maker(patch, kind="unified-diff"), _review("PASS")]
        ),
        run_id=f"mc-unchanged-gitlink-{initialize_submodule}",
    )

    assert result.status is MakerCheckerStatus.PASSED
    workspace = Path(result.workspace or "")
    assert (workspace / "app.py").read_text(encoding="utf-8") == "answer = 2\n"
    gitlink = subprocess.run(
        ["git", "-C", str(workspace), "ls-files", "--stage", "vendor/dependency"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert gitlink.startswith("160000 ")


def test_terminal_code_snapshot_remains_archivable_after_owned_worktree_cleanup(
    tmp_path: Path,
) -> None:
    _init_git_repo(tmp_path)
    patch = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1 +1 @@
-answer = 1
+answer = 2
"""
    result = run_maker_checker(
        tmp_path,
        task="Change the answer in an owned worktree.",
        kind="code",
        policy=_policy(),
        dispatcher=ScriptedDispatcher(
            [_maker(patch, kind="unified-diff"), _review("PASS")]
        ),
        run_id="mc-cleaned-terminal",
    )
    assert result.status is MakerCheckerStatus.PASSED
    manager = maker_checker_module.WorktreeManager(tmp_path)
    removed = manager.cleanup(
        "mc-cleaned-terminal", "maker-checker", discard_changes=True
    )
    assert removed.status is maker_checker_module.WorktreeStatus.REMOVED
    terminal_path = tmp_path / ".ckit/state/pipeline-snapshot.json"
    terminal = json.loads(terminal_path.read_text(encoding="utf-8"))
    coherent, messages = validate_maker_checker_snapshot(tmp_path, terminal)
    assert coherent, "\n".join(messages)

    successor = run_maker_checker(
        tmp_path,
        task="Draft a successor design.",
        kind="design",
        policy=_policy(),
        dispatcher=ScriptedDispatcher([_maker("successor"), _review("PASS")]),
        run_id="mc-after-cleanup",
    )
    assert successor.status is MakerCheckerStatus.PASSED
    current = json.loads(terminal_path.read_text(encoding="utf-8"))
    assert current["run_archives"][-1]["snapshot"]["run_id"] == "mc-cleaned-terminal"
    assert pipeline.validate(tmp_path)[0]


def test_cross_kind_archives_are_nonrecursive_and_live_verified(
    tmp_path: Path, payload: Path
) -> None:
    install(payload, tmp_path)
    _init_git_repo(tmp_path)
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-qm", "installed projection"],
        check=True,
    )

    started, messages = pipeline.start(tmp_path, task="generic predecessor")
    assert started, "\n".join(messages)
    aborted, messages = pipeline.abort(tmp_path)
    assert aborted, "\n".join(messages)
    generic_terminal = json.loads(
        (tmp_path / ".claude/state/pipeline-snapshot.json").read_text(encoding="utf-8")
    )

    maker_result = run_maker_checker(
        tmp_path,
        task="Draft a cross-kind design.",
        kind="design",
        policy=_policy(),
        dispatcher=ScriptedDispatcher([_maker("design"), _review("PASS")]),
        run_id="mc-cross-kind",
    )
    assert maker_result.status is MakerCheckerStatus.PASSED
    maker_terminal = json.loads(
        (tmp_path / ".claude/state/pipeline-snapshot.json").read_text(encoding="utf-8")
    )
    assert maker_terminal["run_archives"][0]["snapshot"] == generic_terminal
    assert pipeline.validate(tmp_path, strict=True)[0]

    started, messages = pipeline.start(tmp_path, task="generic successor")
    assert started, "\n".join(messages)
    current = json.loads(
        (tmp_path / ".claude/state/pipeline-snapshot.json").read_text(encoding="utf-8")
    )
    assert [
        archive["snapshot"].get("snapshot_kind") for archive in current["run_archives"]
    ] == [None, "maker-checker"]
    assert all(
        "run_archives" not in archive["snapshot"] for archive in current["run_archives"]
    )
    assert pipeline.validate(tmp_path, strict=True)[0]
    with ExitStack() as stack:
        assert schemas.validate_doc(current, "pipeline-snapshot", stack) == []

    maker_archive = current["run_archives"][1]["snapshot"]
    result_path = tmp_path / maker_archive["result_path"]
    original_result = result_path.read_bytes()
    result_path.write_text("{}\n", encoding="utf-8")
    coherent, validation_messages = pipeline.validate(tmp_path, strict=True)
    assert not coherent
    assert any(
        "run_archives[1]" in message and "terminal result" in message
        for message in validation_messages
    )
    result_path.write_bytes(original_result)
    assert pipeline.validate(tmp_path, strict=True)[0]
