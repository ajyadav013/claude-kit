"""Security and lifecycle tests for origin-bound managed external-action approval."""

from __future__ import annotations

import base64
import copy
import json
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import jsonschema
import pytest

from claude_kit.managed_approval import (
    AUTHORIZATION_DOMAIN,
    PULL_REQUEST_CREATE,
    REQUEST_DOMAIN,
    ApprovalConflictError,
    ApprovalDriftError,
    ApprovalExpiredError,
    ApprovalPolicyError,
    ApprovalSignatureError,
    ApprovalState,
    ApprovalStateError,
    ApprovalValidationError,
    ArtifactBinding,
    BrokerExecutionPermit,
    ExternalActionBroker,
    ManagedApprovalCoordinator,
    ManagedApprovalRecord,
    ManagedApprovalRequest,
    ManagedApprovalScope,
    ManagedAuthorizationEnvelope,
    ManagedWorkspaceBinding,
    PullRequestBrokerPreflight,
    PullRequestCreateAction,
    PullRequestReceipt,
    RepositoryBinding,
    SignerPolicyDecision,
    TypedActionReceipt,
    TypedBrokerPreflight,
    TypedExternalAction,
    WorkspaceCheckpointBinding,
    action_from_dict,
    approval_marker,
    canonical_json_bytes,
    consumption_permit,
    domain_separated_bytes,
    validate_broker_preflight,
    validate_external_policy_source,
    verify_authorization,
)

ROOT = Path(__file__).parents[1]
SCHEMA_PATH = ROOT / "schemas" / "managed-approval.schema.json"
NOW = datetime(2026, 8, 21, 10, 0, tzinfo=timezone.utc)
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64
DIGEST_D = "d" * 64
COMMIT_A = "1" * 40
COMMIT_B = "2" * 40
SIGNATURE = base64.urlsafe_b64encode(b"s" * 64).decode("ascii").rstrip("=")


def _scope() -> ManagedApprovalScope:
    return ManagedApprovalScope(
        run_id="run-001",
        stop_id="stop-001",
        workflow_id="sdlc",
        workflow_schema_version=1,
        workflow_definition_digest=DIGEST_A,
        gate_definition_digest=DIGEST_B,
        stage_id="pull-request",
        stage_attempt=2,
        dispatch_id="dispatch-002",
        dispatch_attempt=1,
        provider="codex",
        route="pr-raiser",
        role="pr-raiser",
        repository=RepositoryBinding(
            repository="github.com/acme/widgets",
            branch="ckit/run-001",
            commit=COMMIT_A,
        ),
        workspace=ManagedWorkspaceBinding(
            owner="ckit",
            worker_id="integration",
            target_path="../.ckit-worktrees/run-001/integration",
            base_commit=COMMIT_A,
            provider_control_surface_digest=DIGEST_C,
            checkpoint=WorkspaceCheckpointBinding(
                head_commit=COMMIT_A,
                tracked_digest=DIGEST_A,
                untracked_digest=DIGEST_B,
                content_digest=DIGEST_D,
            ),
        ),
    )


def _action() -> PullRequestCreateAction:
    return PullRequestCreateAction(
        repository="github.com/acme/widgets",
        base_ref="main",
        head_ref="ckit/run-001",
        head_commit=COMMIT_A,
        title="Ship the reviewed change",
        body="Evidence is attached.",
        artifacts=(ArtifactBinding("evidence/report.json", DIGEST_A),),
    )


def _request() -> ManagedApprovalRequest:
    return ManagedApprovalRequest(
        request_id="approval-request-001",
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=30),
        scope=_scope(),
        action=_action(),
    )


def _envelope(
    request: Optional[ManagedApprovalRequest] = None,
    **changes: object,
) -> ManagedAuthorizationEnvelope:
    bound = request or _request()
    values: dict[str, object] = {
        "authorization_id": "authorization-001",
        "request_id": bound.request_id,
        "request_digest": bound.digest(),
        "policy_id": "protected-reviewers",
        "policy_digest": DIGEST_D,
        "signer_id": "reviewer-001",
        "key_id": "key-001",
        "algorithm": "ed25519",
        "issued_at": NOW + timedelta(minutes=1),
        "expires_at": NOW + timedelta(minutes=20),
        "signature": SIGNATURE,
    }
    values.update(changes)
    return ManagedAuthorizationEnvelope(**values)  # type: ignore[arg-type]


@dataclass
class _Policy:
    source_path: Path
    allowed: bool = True
    policy_id: str = "protected-reviewers"
    policy_digest: str = DIGEST_D
    evaluations: int = 0

    def evaluate(
        self,
        request: ManagedApprovalRequest,
        envelope: ManagedAuthorizationEnvelope,
    ) -> SignerPolicyDecision:
        self.evaluations += 1
        assert envelope.request_id == request.request_id
        return SignerPolicyDecision(self.allowed, "reviewer and target are allowed")


@dataclass
class _Verifier:
    valid: bool = True
    calls: int = 0
    message: bytes = b""

    def verify(
        self,
        *,
        algorithm: str,
        key_id: str,
        message: bytes,
        signature: bytes,
    ) -> bool:
        self.calls += 1
        self.message = message
        assert algorithm == "ed25519"
        assert key_id == "key-001"
        assert signature == b"s" * 64
        return self.valid


class _Store:
    def __init__(self, record: ManagedApprovalRecord) -> None:
        self.record = record
        self.fail_next_cas = False

    def get(self, request_id: str) -> Optional[ManagedApprovalRecord]:
        return self.record if self.record.request.request_id == request_id else None

    def compare_and_swap(
        self,
        request_id: str,
        expected_revision: int,
        replacement: ManagedApprovalRecord,
    ) -> bool:
        if self.fail_next_cas:
            self.fail_next_cas = False
            return False
        if (
            request_id != self.record.request.request_id
            or expected_revision != self.record.revision
        ):
            return False
        self.record = replacement
        return True


def _trust_boundary(tmp_path: Path) -> tuple[Path, _Policy, _Verifier]:
    project = tmp_path / "project"
    project.mkdir()
    policy_path = tmp_path / "host-policy" / "trusted-signers.json"
    policy_path.parent.mkdir()
    policy_path.write_text('{"policy":"test"}\n', encoding="utf-8")
    policy_path.chmod(0o600)
    return project, _Policy(policy_path), _Verifier()


def _authorize(
    coordinator: ManagedApprovalCoordinator,
    request: ManagedApprovalRequest,
    project: Path,
    policy: _Policy,
    verifier: _Verifier,
) -> ManagedApprovalRecord:
    return coordinator.authorize(
        request.request_id,
        expected_revision=0,
        envelope=_envelope(request),
        current_scope=request.scope,
        current_action=request.action,
        policy=policy,
        verifier=verifier,
        project_root=project,
        now=NOW + timedelta(minutes=2),
    )


def _begin(
    coordinator: ManagedApprovalCoordinator,
    request: ManagedApprovalRequest,
    project: Path,
    policy: _Policy,
    verifier: _Verifier,
) -> tuple[ManagedApprovalRecord, BrokerExecutionPermit]:
    return coordinator.begin_consumption(
        request.request_id,
        expected_revision=1,
        current_scope=request.scope,
        current_action=request.action,
        policy=policy,
        verifier=verifier,
        project_root=project,
        now=NOW + timedelta(minutes=3),
    )


def _receipt(
    record: ManagedApprovalRecord,
    permit: BrokerExecutionPermit,
    **changes: object,
) -> PullRequestReceipt:
    action = record.request.action
    values: dict[str, object] = {
        "request_digest": record.request_digest,
        "action_digest": action.digest(),
        "idempotency_key": permit.idempotency_key,
        "repository": action.repository,
        "base_ref": action.base_ref,
        "head_ref": action.head_ref,
        "head_commit": action.head_commit,
        "external_id": "42",
        "url": "https://github.com/acme/widgets/pull/42",
        "marker": permit.marker,
        "observed_at": NOW + timedelta(minutes=4),
    }
    values.update(changes)
    return PullRequestReceipt(**values)  # type: ignore[arg-type]


def _preflight(
    permit: BrokerExecutionPermit,
    **changes: object,
) -> PullRequestBrokerPreflight:
    action = permit.action
    values: dict[str, object] = {
        "request_digest": permit.request_digest,
        "action_digest": action.digest(),
        "idempotency_key": permit.idempotency_key,
        "repository": action.repository,
        "base_ref": action.base_ref,
        "head_ref": action.head_ref,
        "expected_head_commit": action.head_commit,
        "observed_head_commit": action.head_commit,
        "marker": permit.marker,
        "checked_at": NOW + timedelta(minutes=3, seconds=30),
    }
    values.update(changes)
    return PullRequestBrokerPreflight(**values)  # type: ignore[arg-type]


def _schema_validator() -> jsonschema.Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(
        schema, format_checker=jsonschema.FormatChecker()
    )


def test_canonical_documents_are_stable_and_domain_separated() -> None:
    assert canonical_json_bytes({"z": 2, "a": "é"}) == b'{"a":"\xc3\xa9","z":2}'
    request = _request()
    restored = ManagedApprovalRequest.from_dict(request.to_dict())
    assert restored == request
    assert restored.digest() == request.digest()
    assert request.signing_bytes() == domain_separated_bytes(
        REQUEST_DOMAIN, request.to_dict()
    )
    assert (
        domain_separated_bytes("different-domain", request.to_dict())
        != request.signing_bytes()
    )
    with pytest.raises(ApprovalValidationError, match="unsupported JSON value float"):
        canonical_json_bytes({"unsafe": 1.5})
    envelope = _envelope(request)
    assert (
        replace(envelope, signer_id="reviewer-002").signing_bytes()
        != envelope.signing_bytes()
    )


def test_action_is_typed_and_generic_shell_is_not_a_parseable_action() -> None:
    action = _action()
    assert isinstance(action, TypedExternalAction)
    assert action_from_dict(action.to_dict()) == action
    with pytest.raises(
        ApprovalValidationError, match="unsupported external action kind"
    ):
        action_from_dict({"kind": "shell", "command": "gh pr create"})
    with pytest.raises(ApprovalValidationError, match="asymmetric"):
        _envelope(algorithm="hmac-sha256")


def test_request_binds_pull_request_head_to_source_branch_and_workspace_commit() -> (
    None
):
    scope = _scope()
    action = _action()
    with pytest.raises(ApprovalValidationError, match="source branch"):
        ManagedApprovalRequest(
            request_id="wrong-source-branch",
            created_at=NOW,
            expires_at=NOW + timedelta(minutes=30),
            scope=scope,
            action=replace(action, head_ref="other/branch"),
        )
    with pytest.raises(ApprovalValidationError, match="workspace checkpoint"):
        ManagedApprovalRequest(
            request_id="wrong-workspace-commit",
            created_at=NOW,
            expires_at=NOW + timedelta(minutes=30),
            scope=scope,
            action=replace(action, head_commit=COMMIT_B),
        )
    with pytest.raises(ApprovalValidationError, match="source commit"):
        ManagedApprovalRequest(
            request_id="wrong-source-commit",
            created_at=NOW,
            expires_at=NOW + timedelta(minutes=30),
            scope=replace(
                scope,
                repository=replace(scope.repository, commit=COMMIT_B),
            ),
            action=action,
        )


def test_artifact_bindings_are_canonical_sorted_unique_map() -> None:
    first = ArtifactBinding("evidence/a.json", DIGEST_A)
    second = ArtifactBinding("evidence/b.json", DIGEST_B)
    action = replace(_action(), artifacts=(first, second))
    assert list(action.to_dict()["artifacts"]) == [
        "evidence/a.json",
        "evidence/b.json",
    ]
    assert action_from_dict(action.to_dict()) == action
    with pytest.raises(ApprovalValidationError, match="unique and sorted"):
        replace(_action(), artifacts=(second, first))
    with pytest.raises(ApprovalValidationError, match="unique and sorted"):
        replace(_action(), artifacts=(first, first))
    legacy_array = action.to_dict()
    legacy_array["artifacts"] = [first.to_dict()]
    with pytest.raises(ApprovalValidationError, match="must be an object"):
        action_from_dict(legacy_array)


def test_successful_authorization_is_consumed_once_and_records_exact_receipt(
    tmp_path: Path,
) -> None:
    request = _request()
    store = _Store(ManagedApprovalRecord.pending(request))
    coordinator = ManagedApprovalCoordinator(store)
    project, policy, verifier = _trust_boundary(tmp_path)

    pending = store.record
    authorized = _authorize(coordinator, request, project, policy, verifier)
    assert pending.state is ApprovalState.PENDING
    assert authorized.state is ApprovalState.AUTHORIZED
    assert authorized.revision == 1
    assert verifier.calls == 1
    assert AUTHORIZATION_DOMAIN.encode("ascii") in verifier.message

    consuming, permit = _begin(coordinator, request, project, policy, verifier)
    assert consuming.state is ApprovalState.CONSUMING
    assert consuming.revision == 2
    assert policy.evaluations == 2
    assert permit.marker == approval_marker(request.digest())
    assert not hasattr(permit, "signature")
    assert not hasattr(permit, "authorization")

    receipt = _receipt(consuming, permit)
    consumed = coordinator.record_consumed(
        request.request_id,
        expected_revision=2,
        receipt=receipt,
        completed_at=NOW + timedelta(minutes=5),
    )
    assert consumed.state is ApprovalState.CONSUMED
    assert consumed.revision == 3
    assert consumed.receipt == receipt
    assert ManagedApprovalRecord.from_dict(consumed.to_dict()) == consumed
    _schema_validator().validate(consumed.to_dict())

    with pytest.raises(ApprovalStateError, match="only a consuming"):
        coordinator.record_consumed(
            request.request_id,
            expected_revision=3,
            receipt=receipt,
            completed_at=NOW + timedelta(minutes=6),
        )


def test_consume_before_call_state_is_durable_and_reconstructs_same_permit(
    tmp_path: Path,
) -> None:
    request = _request()
    store = _Store(ManagedApprovalRecord.pending(request))
    coordinator = ManagedApprovalCoordinator(store)
    project, policy, verifier = _trust_boundary(tmp_path)
    _authorize(coordinator, request, project, policy, verifier)
    consuming, permit = _begin(coordinator, request, project, policy, verifier)

    # Simulate coordinator death after CAS but before an external call. Recovery does not
    # reset to authorized and receives the exact deterministic reconciliation identity.
    recovered = ManagedApprovalRecord.from_dict(consuming.to_dict())
    assert consumption_permit(recovered) == permit
    with pytest.raises(ApprovalStateError, match="only an authorized"):
        coordinator.begin_consumption(
            request.request_id,
            expected_revision=2,
            current_scope=request.scope,
            current_action=request.action,
            policy=policy,
            verifier=verifier,
            project_root=project,
            now=NOW + timedelta(minutes=4),
        )


def test_broker_preflight_requires_fresh_exact_remote_source_head(
    tmp_path: Path,
) -> None:
    request = _request()
    store = _Store(ManagedApprovalRecord.pending(request))
    coordinator = ManagedApprovalCoordinator(store)
    project, policy, verifier = _trust_boundary(tmp_path)
    _authorize(coordinator, request, project, policy, verifier)
    _, permit = _begin(coordinator, request, project, policy, verifier)

    preflight = _preflight(permit)
    assert (
        validate_broker_preflight(
            permit,
            preflight,
            now=NOW + timedelta(minutes=3, seconds=45),
        )
        is preflight
    )
    assert preflight.digest() != request.action.digest()

    for drifted in (
        replace(preflight, head_ref="other/branch"),
        replace(preflight, observed_head_commit=COMMIT_B),
        replace(preflight, repository="github.com/acme/other"),
        replace(preflight, request_digest=DIGEST_A),
    ):
        with pytest.raises(ApprovalDriftError, match="broker preflight"):
            validate_broker_preflight(
                permit,
                drifted,
                now=NOW + timedelta(minutes=3, seconds=45),
            )

    with pytest.raises(ApprovalExpiredError, match="stale"):
        validate_broker_preflight(
            permit,
            preflight,
            now=NOW + timedelta(minutes=5),
        )
    with pytest.raises(ApprovalExpiredError, match="consumption interval"):
        validate_broker_preflight(
            permit,
            replace(
                preflight,
                checked_at=permit.consumption_started_at - timedelta(seconds=1),
            ),
            now=NOW + timedelta(minutes=3, seconds=45),
        )


def test_ambiguous_external_outcome_is_terminal_and_cannot_be_replayed(
    tmp_path: Path,
) -> None:
    request = _request()
    store = _Store(ManagedApprovalRecord.pending(request))
    coordinator = ManagedApprovalCoordinator(store)
    project, policy, verifier = _trust_boundary(tmp_path)
    _authorize(coordinator, request, project, policy, verifier)
    _begin(coordinator, request, project, policy, verifier)

    indeterminate = coordinator.record_indeterminate(
        request.request_id,
        expected_revision=2,
        reason="multiple remote resources matched the idempotency marker",
        recorded_at=NOW + timedelta(minutes=5),
    )
    assert indeterminate.state is ApprovalState.INDETERMINATE
    _schema_validator().validate(indeterminate.to_dict())
    with pytest.raises(ApprovalStateError, match="only a consuming"):
        coordinator.record_indeterminate(
            request.request_id,
            expected_revision=3,
            reason="retry",
            recorded_at=NOW + timedelta(minutes=6),
        )


def test_receipt_target_mismatch_fails_closed_then_can_be_marked_indeterminate(
    tmp_path: Path,
) -> None:
    request = _request()
    store = _Store(ManagedApprovalRecord.pending(request))
    coordinator = ManagedApprovalCoordinator(store)
    project, policy, verifier = _trust_boundary(tmp_path)
    _authorize(coordinator, request, project, policy, verifier)
    consuming, permit = _begin(coordinator, request, project, policy, verifier)

    wrong_receipt = _receipt(consuming, permit, repository="github.com/attacker/repo")
    with pytest.raises(ApprovalValidationError, match="receipt repository differs"):
        coordinator.record_consumed(
            request.request_id,
            expected_revision=2,
            receipt=wrong_receipt,
            completed_at=NOW + timedelta(minutes=5),
        )
    assert store.record.state is ApprovalState.CONSUMING
    coordinator.record_indeterminate(
        request.request_id,
        expected_revision=2,
        reason="remote receipt target did not match",
        recorded_at=NOW + timedelta(minutes=5),
    )


@pytest.mark.parametrize(
    ("changes", "field_name"),
    [
        ({"head_ref": "other/branch"}, "head_ref"),
        ({"head_commit": COMMIT_B}, "head_commit"),
        ({"base_ref": "release"}, "base_ref"),
    ],
)
def test_receipt_is_bound_to_exact_signed_branch_and_commit(
    tmp_path: Path,
    changes: dict[str, object],
    field_name: str,
) -> None:
    request = _request()
    store = _Store(ManagedApprovalRecord.pending(request))
    coordinator = ManagedApprovalCoordinator(store)
    project, policy, verifier = _trust_boundary(tmp_path)
    _authorize(coordinator, request, project, policy, verifier)
    consuming, permit = _begin(coordinator, request, project, policy, verifier)
    with pytest.raises(
        ApprovalValidationError,
        match=f"receipt {field_name} differs",
    ):
        coordinator.record_consumed(
            request.request_id,
            expected_revision=2,
            receipt=_receipt(consuming, permit, **changes),
            completed_at=NOW + timedelta(minutes=5),
        )
    assert store.record.state is ApprovalState.CONSUMING


def test_every_origin_binding_and_workspace_checkpoint_field_is_exact(
    tmp_path: Path,
) -> None:
    request = _request()
    project, policy, verifier = _trust_boundary(tmp_path)
    envelope = _envelope(request)
    scope = request.scope
    drifts = [
        replace(scope, run_id="run-002"),
        replace(scope, stop_id="stop-002"),
        replace(scope, workflow_id="other-workflow"),
        replace(scope, workflow_definition_digest=DIGEST_B),
        replace(scope, gate_definition_digest=DIGEST_A),
        replace(scope, stage_id="other-stage"),
        replace(scope, stage_attempt=3),
        replace(scope, dispatch_id="dispatch-003"),
        replace(scope, dispatch_attempt=2),
        replace(scope, provider="claude"),
        replace(scope, route="other-route"),
        replace(scope, role="other-role"),
        replace(scope, repository=replace(scope.repository, commit=COMMIT_B)),
        replace(scope, workspace=replace(scope.workspace, worker_id="other-worker")),
        replace(
            scope,
            workspace=replace(
                scope.workspace,
                checkpoint=replace(scope.workspace.checkpoint, content_digest=DIGEST_A),
            ),
        ),
        replace(
            scope,
            workspace=replace(
                scope.workspace, provider_control_surface_digest=DIGEST_D
            ),
        ),
    ]
    for drifted_scope in drifts:
        with pytest.raises(ApprovalDriftError, match="scope drifted"):
            verify_authorization(
                request,
                envelope,
                current_scope=drifted_scope,
                current_action=request.action,
                policy=policy,
                verifier=verifier,
                project_root=project,
                now=NOW + timedelta(minutes=2),
            )
    assert verifier.calls == 0, "drift must fail before asymmetric verification"


@pytest.mark.parametrize(
    "drifted_action",
    [
        replace(_action(), repository="github.com/acme/other"),
        replace(_action(), base_ref="release"),
        replace(_action(), head_ref="other/head"),
        replace(_action(), title="Different title"),
        replace(_action(), body="Different body"),
        replace(_action(), draft=True),
        replace(
            _action(), artifacts=(ArtifactBinding("evidence/report.json", DIGEST_B),)
        ),
    ],
)
def test_every_action_field_is_bound(
    tmp_path: Path, drifted_action: PullRequestCreateAction
) -> None:
    request = _request()
    project, policy, verifier = _trust_boundary(tmp_path)
    with pytest.raises(ApprovalDriftError, match="action drifted"):
        verify_authorization(
            request,
            _envelope(request),
            current_scope=request.scope,
            current_action=drifted_action,
            policy=policy,
            verifier=verifier,
            project_root=project,
            now=NOW + timedelta(minutes=2),
        )
    assert verifier.calls == 0


def test_envelope_cannot_be_replayed_for_another_request(tmp_path: Path) -> None:
    request = _request()
    other = replace(request, request_id="approval-request-002")
    project, policy, verifier = _trust_boundary(tmp_path)
    with pytest.raises(ApprovalSignatureError, match="different request"):
        verify_authorization(
            other,
            _envelope(request),
            current_scope=other.scope,
            current_action=other.action,
            policy=policy,
            verifier=verifier,
            project_root=project,
            now=NOW + timedelta(minutes=2),
        )
    assert verifier.calls == 0


def test_expired_or_future_authorization_fails_before_signature_verification(
    tmp_path: Path,
) -> None:
    request = _request()
    project, policy, verifier = _trust_boundary(tmp_path)
    with pytest.raises(ApprovalExpiredError, match="issuance time"):
        verify_authorization(
            request,
            _envelope(request, issued_at=NOW + timedelta(minutes=5)),
            current_scope=request.scope,
            current_action=request.action,
            policy=policy,
            verifier=verifier,
            project_root=project,
            now=NOW + timedelta(minutes=2),
        )
    with pytest.raises(ApprovalExpiredError, match="expired"):
        verify_authorization(
            request,
            _envelope(request, expires_at=NOW + timedelta(minutes=3)),
            current_scope=request.scope,
            current_action=request.action,
            policy=policy,
            verifier=verifier,
            project_root=project,
            now=NOW + timedelta(minutes=4),
        )
    assert verifier.calls == 0


def test_authorization_expiring_between_authorize_and_consume_cannot_execute(
    tmp_path: Path,
) -> None:
    request = _request()
    store = _Store(ManagedApprovalRecord.pending(request))
    coordinator = ManagedApprovalCoordinator(store)
    project, policy, verifier = _trust_boundary(tmp_path)
    short = _envelope(request, expires_at=NOW + timedelta(minutes=3))
    coordinator.authorize(
        request.request_id,
        expected_revision=0,
        envelope=short,
        current_scope=request.scope,
        current_action=request.action,
        policy=policy,
        verifier=verifier,
        project_root=project,
        now=NOW + timedelta(minutes=2),
    )
    with pytest.raises(ApprovalExpiredError, match="expired"):
        coordinator.begin_consumption(
            request.request_id,
            expected_revision=1,
            current_scope=request.scope,
            current_action=request.action,
            policy=policy,
            verifier=verifier,
            project_root=project,
            now=NOW + timedelta(minutes=4),
        )
    assert store.record.state is ApprovalState.AUTHORIZED


def test_wrong_policy_denial_and_invalid_signature_all_fail_closed(
    tmp_path: Path,
) -> None:
    request = _request()
    project, policy, verifier = _trust_boundary(tmp_path)
    with pytest.raises(ApprovalPolicyError, match="different signer policy"):
        verify_authorization(
            request,
            _envelope(request, policy_digest=DIGEST_A),
            current_scope=request.scope,
            current_action=request.action,
            policy=policy,
            verifier=verifier,
            project_root=project,
            now=NOW + timedelta(minutes=2),
        )
    policy.allowed = False
    with pytest.raises(ApprovalPolicyError, match="denied"):
        verify_authorization(
            request,
            _envelope(request),
            current_scope=request.scope,
            current_action=request.action,
            policy=policy,
            verifier=verifier,
            project_root=project,
            now=NOW + timedelta(minutes=2),
        )
    policy.allowed = True
    verifier.valid = False
    with pytest.raises(ApprovalSignatureError, match="invalid"):
        verify_authorization(
            request,
            _envelope(request),
            current_scope=request.scope,
            current_action=request.action,
            policy=policy,
            verifier=verifier,
            project_root=project,
            now=NOW + timedelta(minutes=2),
        )


def test_policy_source_must_be_external_regular_and_not_mutable(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    inside = project / "policy.json"
    inside.write_text("{}", encoding="utf-8")
    with pytest.raises(ApprovalPolicyError, match="outside"):
        validate_external_policy_source(inside, project)
    with pytest.raises(ApprovalPolicyError, match="absolute"):
        validate_external_policy_source(Path("policy.json"), project)

    external = tmp_path / "external-policy.json"
    external.write_text("{}", encoding="utf-8")
    external.chmod(0o666)
    with pytest.raises(ApprovalPolicyError, match="group- or world-writable"):
        validate_external_policy_source(external, project)

    external.chmod(0o600)
    project_link = project / "external-policy-link.json"
    project_link.symlink_to(external)
    with pytest.raises(ApprovalPolicyError, match="outside"):
        validate_external_policy_source(project_link, project)

    external_link = tmp_path / "inside-policy-link.json"
    external_link.symlink_to(inside)
    with pytest.raises(ApprovalPolicyError, match="outside"):
        validate_external_policy_source(external_link, project)


def test_cas_conflict_leaves_record_pending_and_stale_revisions_are_rejected(
    tmp_path: Path,
) -> None:
    request = _request()
    store = _Store(ManagedApprovalRecord.pending(request))
    store.fail_next_cas = True
    coordinator = ManagedApprovalCoordinator(store)
    project, policy, verifier = _trust_boundary(tmp_path)
    with pytest.raises(ApprovalConflictError, match="concurrent race"):
        _authorize(coordinator, request, project, policy, verifier)
    assert store.record.state is ApprovalState.PENDING
    _authorize(coordinator, request, project, policy, verifier)
    with pytest.raises(ApprovalConflictError, match="expected 0"):
        coordinator.authorize(
            request.request_id,
            expected_revision=0,
            envelope=_envelope(request),
            current_scope=request.scope,
            current_action=request.action,
            policy=policy,
            verifier=verifier,
            project_root=project,
            now=NOW + timedelta(minutes=2),
        )


def test_schema_accepts_every_state_and_rejects_state_or_action_confusion(
    tmp_path: Path,
) -> None:
    validator = _schema_validator()
    request = _request()
    pending = ManagedApprovalRecord.pending(request)
    validator.validate(pending.to_dict())

    store = _Store(pending)
    coordinator = ManagedApprovalCoordinator(store)
    project, policy, verifier = _trust_boundary(tmp_path)
    authorized = _authorize(coordinator, request, project, policy, verifier)
    validator.validate(authorized.to_dict())
    consuming, permit = _begin(coordinator, request, project, policy, verifier)
    validator.validate(consuming.to_dict())
    consumed = coordinator.record_consumed(
        request.request_id,
        expected_revision=2,
        receipt=_receipt(consuming, permit),
        completed_at=NOW + timedelta(minutes=5),
    )
    validator.validate(consumed.to_dict())

    wrong_revision = {**consumed.to_dict(), "revision": 2}
    assert list(validator.iter_errors(wrong_revision))
    generic_action = consumed.to_dict()
    generic_action["request"]["action"] = {"kind": "shell", "command": "gh pr create"}
    assert list(validator.iter_errors(generic_action))
    unknown_field = {**pending.to_dict(), "self_approved": True}
    assert list(validator.iter_errors(unknown_field))
    null_lifecycle_field = {**pending.to_dict(), "authorization": None}
    assert list(validator.iter_errors(null_lifecycle_field))
    with pytest.raises(ApprovalValidationError, match="omitted rather than null"):
        ManagedApprovalRecord.from_dict(null_lifecycle_field)


def test_runtime_records_and_schema_documents_conform_bidirectionally(
    tmp_path: Path,
) -> None:
    validator = _schema_validator()
    request = _request()
    pending = ManagedApprovalRecord.pending(request)
    store = _Store(pending)
    coordinator = ManagedApprovalCoordinator(store)
    project, policy, verifier = _trust_boundary(tmp_path)
    authorized = _authorize(coordinator, request, project, policy, verifier)
    consuming, permit = _begin(coordinator, request, project, policy, verifier)
    consumed = coordinator.record_consumed(
        request.request_id,
        expected_revision=2,
        receipt=_receipt(consuming, permit),
        completed_at=NOW + timedelta(minutes=5),
    )
    indeterminate = replace(
        consuming,
        state=ApprovalState.INDETERMINATE,
        revision=3,
        indeterminate_reason="remote outcome could not be reconciled",
        terminal_at=NOW + timedelta(minutes=5),
    )

    for record in (pending, authorized, consuming, consumed, indeterminate):
        document = record.to_dict()
        validator.validate(document)
        restored = ManagedApprovalRecord.from_dict(document)
        assert restored == record
        assert restored.to_dict() == document


def test_schema_and_runtime_reject_the_same_lexically_unsafe_documents() -> None:
    validator = _schema_validator()
    valid = ManagedApprovalRecord.pending(_request()).to_dict()

    def mutated(*path_and_value: object) -> dict[str, object]:
        *path, value = path_and_value
        document: dict[str, object] = copy.deepcopy(valid)
        target: object = document
        for key in path[:-1]:
            assert isinstance(target, dict)
            target = target[key]
        assert isinstance(target, dict)
        target[path[-1]] = value
        return document

    unsafe_documents = [
        mutated("request", "scope", "workspace", "target_path", "/tmp/worktree"),
        mutated("request", "scope", "workspace", "target_path", "C:worktree"),
        mutated(
            "request",
            "scope",
            "workspace",
            "target_path",
            "..\\worktree",
        ),
        mutated(
            "request",
            "scope",
            "workspace",
            "target_path",
            "..\tworktree",
        ),
        mutated("request", "created_at", "2026-08-21T10:00:00Z"),
        mutated("request", "created_at", "2026-08-21T10:00:00.000000+00:00"),
        mutated(
            "request",
            "scope",
            "repository",
            "repository",
            "https://github.com/acme/widgets",
        ),
        mutated(
            "request",
            "scope",
            "repository",
            "repository",
            "github.com/acme//widgets",
        ),
        mutated("request", "scope", "repository", "branch", "bad..branch"),
        mutated("request", "action", "base_ref", "-unsafe"),
        mutated("request", "action", "title", " padded title "),
        mutated(
            "request",
            "action",
            "artifacts",
            {"../outside.json": DIGEST_A},
        ),
        mutated(
            "request",
            "action",
            "artifacts",
            [{"artifact_id": "evidence/report.json", "sha256": DIGEST_A}],
        ),
    ]
    for document in unsafe_documents:
        assert list(validator.iter_errors(document)), document
        with pytest.raises(ApprovalValidationError):
            ManagedApprovalRecord.from_dict(document)


def test_persisted_authorization_must_bind_the_same_immutable_request() -> None:
    request = _request()
    other_request = replace(request, request_id="approval-request-002")
    other_envelope = _envelope(other_request)
    with pytest.raises(ApprovalValidationError, match="different request"):
        ManagedApprovalRecord(
            request=request,
            request_digest=request.digest(),
            state=ApprovalState.AUTHORIZED,
            revision=1,
            authorization=other_envelope,
            authorization_digest=other_envelope.digest(),
            authorized_at=NOW + timedelta(minutes=2),
        )


def test_protocols_expose_typed_action_receipt_and_broker_without_execution() -> None:
    @dataclass
    class _Broker:
        action_kind: str = PULL_REQUEST_CREATE

        def preflight(self, permit: BrokerExecutionPermit) -> TypedBrokerPreflight:
            raise AssertionError("not invoked by approval coordinator")

        def execute(
            self,
            permit: BrokerExecutionPermit,
            preflight: TypedBrokerPreflight,
        ) -> TypedActionReceipt:
            raise AssertionError("no external call in the approval core")

        def reconcile(
            self, permit: BrokerExecutionPermit
        ) -> Optional[TypedActionReceipt]:
            return None

    assert isinstance(_Broker(), ExternalActionBroker)
    assert isinstance(_action(), TypedExternalAction)
