"""Fail-closed schema parsing for persisted model documents."""

from __future__ import annotations

import pytest

from claude_kit.models import (
    ExecutionPolicy,
    FileRecord,
    GateDefinition,
    InitOptions,
    InstallRequest,
    ModelChoice,
    ModelChoiceKind,
    Runtime,
    UpgradeJournal,
    WorkerBinding,
    digest_gate_definitions,
)
from tests._helpers import make_selection


def _init_options_doc(payload):
    return {
        "claude_kit_version": "0.0.0-test",
        "selection": make_selection(payload).to_dict(),
        "files": [],
    }


def test_init_options_absent_schema_is_explicit_legacy_v1(payload):
    options = InitOptions.from_dict(_init_options_doc(payload))
    assert options.schema_version == 3
    assert options.runtimes == ["claude"]
    assert options.state_layout.root == ".claude"
    assert options.execution_policy is None


def test_init_options_rejects_future_and_malformed_schema(payload):
    document = _init_options_doc(payload)
    with pytest.raises(
        ValueError, match="unsupported future init-options schema_version 4"
    ):
        InitOptions.from_dict({**document, "schema_version": 4})
    with pytest.raises(ValueError, match="must be an integer"):
        InitOptions.from_dict({**document, "schema_version": "1"})


def _native_v2_init_options_doc(payload):
    return {
        **_init_options_doc(payload),
        "schema_version": 2,
        "runtimes": ["claude", "codex"],
        "state_layout": {
            "name": "neutral-v1",
            "root": ".ckit",
            "manifest": ".ckit/config/init-options.json",
            "stack_snapshot": ".ckit/config/stack-catalog.snapshot.yaml",
            "pipeline_snapshot": ".ckit/state/pipeline-snapshot.json",
            "journal": ".ckit/config/upgrade-in-progress.json",
            "continuity": ".ckit/CONTINUITY.md",
            "memory": ".ckit/agent-memory",
            "artifacts": ".ckit/artifacts",
            "state": ".ckit/state",
            "temporary": ".ckit/tmp",
        },
        "rendering_version": 1,
        "compatibility_catalog_versions": {"claude": 1, "codex": 1},
    }


def _execution_policy() -> ExecutionPolicy:
    return ExecutionPolicy(
        maker=WorkerBinding(
            provider="claude",
            model=ModelChoice(kind="tier", value="deep"),
        ),
        reviewer=WorkerBinding(
            provider="codex",
            model=ModelChoice(kind="exact", value="gpt-5.6-codex"),
        ),
    )


def test_init_options_v2_migrates_without_execution_policy(payload):
    document = _native_v2_init_options_doc(payload)
    document["execution"] = _execution_policy().to_dict()

    options = InitOptions.from_dict(document)

    assert options.schema_version == 3
    assert options.execution_policy is None


def test_model_choice_normalizes_and_round_trips_all_kinds():
    inherited = ModelChoice(kind="inherit")
    tier = ModelChoice(kind="tier", value="deep")
    exact = ModelChoice(kind="exact", value="  claude-opus-4-1  ")

    assert inherited.kind is ModelChoiceKind.INHERIT
    assert inherited.value is None
    assert tier.to_dict() == {"kind": "tier", "value": "deep"}
    assert exact.to_dict() == {"kind": "exact", "value": "claude-opus-4-1"}
    assert ModelChoice.from_dict(exact.to_dict()) == exact


@pytest.mark.parametrize(
    "choice, message",
    [
        ({"kind": "inherit", "value": "unexpected"}, "inherit"),
        ({"kind": "tier"}, "tier.*value"),
        ({"kind": "tier", "value": "huge"}, "model tier"),
        ({"kind": "exact", "value": ""}, "exact model"),
        ({"kind": "exact", "value": "--dangerous"}, "exact model"),
        ({"kind": "exact", "value": "x" * 129}, "exact model"),
        ({"kind": "inherit", "extra": True}, "unknown model choice"),
    ],
)
def test_model_choice_rejects_invalid_or_unknown_fields(choice, message):
    with pytest.raises(ValueError, match=message):
        ModelChoice.from_dict(choice)


def test_worker_binding_rejects_installation_mode_and_unknown_fields():
    with pytest.raises(ValueError, match="concrete provider"):
        WorkerBinding(provider="both", model=ModelChoice(kind="inherit"))
    with pytest.raises(ValueError, match="unknown worker binding"):
        WorkerBinding.from_dict(
            {"provider": "claude", "model": {"kind": "inherit"}, "tools": []}
        )


@pytest.mark.parametrize("max_revisions", [-1, 4, True])
def test_execution_policy_bounds_revisions(max_revisions):
    with pytest.raises(ValueError, match="max_revisions"):
        ExecutionPolicy(
            maker=WorkerBinding("claude", ModelChoice("inherit")),
            reviewer=WorkerBinding("claude", ModelChoice("inherit")),
            max_revisions=max_revisions,
        )


def test_execution_policy_allows_the_same_binding_and_round_trips():
    binding = WorkerBinding("claude", ModelChoice("tier", "balanced"))
    policy = ExecutionPolicy(maker=binding, reviewer=binding)

    assert ExecutionPolicy.from_dict(policy.to_dict()) == policy
    assert policy.max_revisions == 2


def test_install_request_rejects_execution_provider_outside_runtime(payload):
    selection = make_selection(payload)
    with pytest.raises(ValueError, match="reviewer provider 'codex' is not installed"):
        InstallRequest(selection, Runtime.CLAUDE, _execution_policy())


def test_init_options_v3_round_trips_execution_and_validates_provider_set(payload):
    document = _native_v2_init_options_doc(payload)
    document["schema_version"] = 3
    document["execution"] = _execution_policy().to_dict()

    options = InitOptions.from_dict(document)

    assert options.execution_policy == _execution_policy()
    assert options.to_dict()["execution"] == _execution_policy().to_dict()

    document["runtimes"] = ["claude"]
    document["compatibility_catalog_versions"] = {"claude": 1}
    with pytest.raises(ValueError, match="reviewer provider 'codex' is not installed"):
        InitOptions.from_dict(document)


@pytest.mark.parametrize(
    "document, message",
    [
        ([], "root must be an object"),
        ({"selection": [], "files": []}, "selection must be an object"),
        ({"selection": {}, "files": {}}, "files must be an array"),
    ],
)
def test_init_options_rejects_wrong_container_shapes(document, message):
    with pytest.raises(ValueError, match=message):
        InitOptions.from_dict(document)


@pytest.mark.parametrize(
    "kwargs, message",
    [
        (
            {"path": "CLAUDE.md", "sha256": "not-a-digest", "owner": "kit"},
            "sha256",
        ),
        (
            {"path": "CLAUDE.md", "sha256": "0" * 64, "owner": "unknown"},
            "owner",
        ),
    ],
)
def test_file_records_reject_malformed_integrity_and_ownership(kwargs, message):
    with pytest.raises(ValueError, match=message):
        FileRecord(**kwargs)


def test_upgrade_journal_absent_schema_is_explicit_legacy_v1():
    journal = UpgradeJournal.from_dict(
        {
            "from_version": "0.1.0",
            "to_version": "0.2.0",
            "started_at": "2026-01-01T00:00:00+00:00",
            "actions": [],
        }
    )
    assert journal.schema_version == 1


def test_upgrade_journal_rejects_secure_transaction_and_future_schemas():
    base = {
        "from_version": "0.1.0",
        "to_version": "0.2.0",
        "started_at": "2026-01-01T00:00:00+00:00",
        "actions": [],
    }
    with pytest.raises(
        ValueError, match="unsupported future upgrade journal schema_version 2"
    ):
        UpgradeJournal.from_dict({**base, "schema_version": 2})
    with pytest.raises(
        ValueError, match="unsupported future upgrade journal schema_version 999"
    ):
        UpgradeJournal.from_dict({**base, "schema_version": 999})


@pytest.mark.parametrize(
    "bad, message",
    [
        (
            {
                "requirement": "conditional",
                "skippable": True,
                "skip_conditions": "no-surface",
            },
            "list of strings",
        ),
        (
            {
                "requirement": "required",
                "skippable": "false",
                "skip_conditions": [],
            },
            "must be a boolean",
        ),
    ],
)
def test_gate_definition_from_dict_rejects_wrong_container_types(bad, message):
    with pytest.raises(ValueError, match=message):
        GateDefinition.from_dict(bad)


def test_gate_definition_digest_requires_an_exact_unique_definition_set():
    required = GateDefinition("required", False, [])
    with pytest.raises(ValueError, match="missing definitions: build-green"):
        digest_gate_definitions(
            ["code-review", "build-green"], {"code-review": required}
        )
    with pytest.raises(ValueError, match="extra definitions: build-green"):
        digest_gate_definitions(
            ["code-review"], {"code-review": required, "build-green": required}
        )
    with pytest.raises(ValueError, match="contains duplicates"):
        digest_gate_definitions(
            ["code-review", "code-review"], {"code-review": required}
        )
