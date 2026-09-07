"""Tests for the provider-neutral SDLC workflow contract."""

from __future__ import annotations

import shutil
from dataclasses import replace
from pathlib import Path
from typing import Callable

import pytest
import yaml

from claude_kit import catalog
from claude_kit.components import Capability
from claude_kit.models import digest_gate_definitions
from claude_kit.workflows import (
    ExternalActionKind,
    GatePolicy,
    StageExecutionKind,
    WorkflowValidationError,
    bind_workflow,
    load_workflow,
)
from tests._helpers import make_selection


def _mutated_payload(
    payload: Path,
    tmp_path: Path,
    mutate: Callable[[dict], None],
) -> Path:
    root = tmp_path / "payload"
    workflow_dir = root / "catalog" / "workflows"
    schema_dir = root / "schemas"
    workflow_dir.mkdir(parents=True)
    schema_dir.mkdir(parents=True)
    shutil.copy2(payload / "schemas" / "workflow.schema.json", schema_dir)
    document = yaml.safe_load(
        (payload / "catalog" / "workflows" / "sdlc.yaml").read_text(encoding="utf-8")
    )
    mutate(document)
    (workflow_dir / "sdlc.yaml").write_text(
        yaml.safe_dump(document, sort_keys=False), encoding="utf-8"
    )
    return root


def test_real_workflow_loads_with_all_orchestration_dimensions(payload: Path) -> None:
    workflow = load_workflow(payload)

    assert workflow.id == "sdlc"
    assert {mode.code for mode in workflow.modes.values()} == {"A", "B", "C", "D", "E"}
    assert workflow.modes["fast-track"].gate_policy is GatePolicy.SUBSET
    assert workflow.modes["fast-track"].gates == ("code-review", "build-green")
    assert workflow.modes["fast-track"].triggers == (
        "localized-single-boundary",
        "low-risk",
        "reversible",
        "no-sensitive-or-public-contract-surface",
    )
    assert workflow.modes["fast-track"].stages[0] == "fast-track-classify"
    assert "classify" not in workflow.modes["fast-track"].stages
    assert workflow.modes["fast-track"].stages[-2:] == (
        "fast-pull-request-prepare",
        "fast-pull-request",
    )
    fast_classify = workflow.stage_by_id["fast-track-classify"]
    assert fast_classify.route == "classification"
    assert fast_classify.evidence == ("fast-track-scope-record",)
    assert workflow.stage_by_id["fast-implementation"].depends_on == (
        "fast-track-classify",
    )
    assert workflow.evidence_requirements["scope-record"].required_fields == (
        "mode",
        "surfaces",
        "constraints",
        "risks",
    )
    assert workflow.modes["program"].program is not None
    program = workflow.modes["program"].program
    assert program.files_over == 20
    assert program.independent_lanes_over == 2
    assert program.irreversible_always
    assert [wave.order for wave in program.waves] == list(range(len(program.waves)))
    assert {
        "planning-review-panel",
        "implementation-lanes",
        "testing-lanes",
        "security-scanners",
    } == set(workflow.parallel_groups)
    assert workflow.retry_budgets["implementation"].max_defect_cycles == 2
    assert workflow.retry_budgets["planning"].max_feedback_iterations == 1
    assert workflow.retry_budgets["review"].max_feedback_iterations == 2
    assert workflow.findings_policy.blocking_severities == (
        "critical",
        "high",
        "medium",
    )
    assert workflow.findings_policy.accepted_risk.allowed_severities == ("medium",)
    assert not workflow.findings_policy.critical_high_waivable
    for stage_id, prepare_id in (
        ("pull-request", "pull-request-prepare"),
        ("fast-pull-request", "fast-pull-request-prepare"),
    ):
        stage = workflow.stage_by_id[stage_id]
        assert stage.execution_kind is StageExecutionKind.TYPED_EXTERNAL_ACTION
        assert stage.action_kind is ExternalActionKind.CREATE_PULL_REQUEST
        assert stage.depends_on == (prepare_id,)
        assert stage.required_capabilities == frozenset({Capability.EXTERNAL_MUTATION})
        prepare = workflow.stage_by_id[prepare_id]
        assert prepare.execution_kind is StageExecutionKind.NATIVE_ROLE
        assert prepare.action_kind is None
        assert prepare.route == "pull-request-prepare"


def test_planning_review_panel_is_one_bounded_read_only_fanout(
    payload: Path,
) -> None:
    workflow = load_workflow(payload)
    stage_by_id = workflow.stage_by_id
    panel = workflow.parallel_groups["planning-review-panel"]
    reviewer_stage_ids = (
        "frontend-review",
        "backend-review",
        "architecture-review",
        "plan-critique",
    )

    assert panel.fork_after == "planning-gate"
    assert panel.join_before == "planning-merge"
    assert panel.concurrency == "read-only-fanout"
    assert all(len(lane.stages) == 1 for lane in panel.lanes)
    assert (
        tuple(stage_id for lane in panel.lanes for stage_id in lane.stages)
        == reviewer_stage_ids
    )

    for stage_id in reviewer_stage_ids:
        stage = stage_by_id[stage_id]
        assert stage.phase == "planning"
        assert stage.depends_on == ("planning-gate",)
        assert stage.parallel_group == panel.id
        assert stage.evidence == ("planning-review-verdict",)

    removed_serial_stage_ids = {
        "frontend-architecture",
        "frontend-management-review",
        "backend-architecture",
        "backend-management-review",
    }
    assert removed_serial_stage_ids.isdisjoint(stage_by_id)

    planning_management_stages = tuple(
        stage.id
        for stage in workflow.stages
        if stage.phase == "planning" and stage.route == "management-review"
    )
    assert planning_management_stages == ("planning-merge",)
    planning_merge = stage_by_id["planning-merge"]
    assert planning_merge.evidence == ("architecture-plan", "planning-decision")
    assert workflow.gates["em-approved"].evidence == (
        "architecture-plan",
        "planning-decision",
    )
    assert "planning-gate" in planning_merge.depends_on
    assert stage_by_id["story-planning"].evidence == (
        "architecture-plan",
        "story-breakdown",
    )
    effective_merge_dependencies = set(planning_merge.depends_on)
    effective_merge_dependencies.update(lane.stages[-1] for lane in panel.lanes)
    assert effective_merge_dependencies == {"planning-gate"} | set(reviewer_stage_ids)

    enabled_mode_codes = {
        mode.code
        for mode in workflow.modes.values()
        if panel.id in mode.parallel_groups
    }
    assert enabled_mode_codes == {"A", "B", "C"}
    program_mode = workflow.modes["program"]
    assert program_mode.parallel_groups == ()
    assert "program manifest" in program_mode.description


def test_planning_devils_advocate_is_never_dispatched_twice(payload: Path) -> None:
    quality_gates = (
        payload / "canonical" / "rules" / "core" / "quality-gates.md"
    ).read_text(encoding="utf-8")
    sdlc = (payload / "canonical" / "skills" / "core" / "sdlc.md").read_text(
        encoding="utf-8"
    )
    devils_advocate = (
        payload / "canonical" / "agents" / "core" / "devils-advocate.md"
    ).read_text(encoding="utf-8")

    assert "Do not dispatch a second post-unanimity adversarial pass" in quality_gates
    assert "planning panel's conditional Devil's Advocate" in sdlc
    assert "never dispatch it again after the panel" in sdlc
    assert "never run a second adversarial" in devils_advocate


def test_full_stack_planning_topology_has_at_most_six_batches_after_classify(
    payload: Path,
) -> None:
    workflow = load_workflow(payload)
    full_stack = next(mode for mode in workflow.modes.values() if mode.code == "B")
    selected_stage_ids = (
        set(workflow.stage_by_id) if full_stack.all_stages else set(full_stack.stages)
    )
    planning_stage_ids = {
        stage.id
        for stage in workflow.stages
        if stage.id in selected_stage_ids and stage.phase == "planning"
    }
    implicit_dependencies: dict[str, set[str]] = {}
    for group_id in full_stack.parallel_groups:
        group = workflow.parallel_groups[group_id]
        implicit_dependencies.setdefault(group.join_before, set()).update(
            lane.stages[-1] for lane in group.lanes
        )

    batch_by_stage: dict[str, int] = {"classify": 0}
    visiting: set[str] = set()

    def batch_for(stage_id: str) -> int:
        if stage_id in batch_by_stage:
            return batch_by_stage[stage_id]
        assert stage_id in planning_stage_ids
        assert stage_id not in visiting
        visiting.add(stage_id)
        stage = workflow.stage_by_id[stage_id]
        dependencies = set(stage.depends_on)
        dependencies.update(implicit_dependencies.get(stage_id, set()))
        assert dependencies.issubset(planning_stage_ids | {"classify"})
        batch = 1 + max((batch_for(item) for item in dependencies), default=0)
        visiting.remove(stage_id)
        batch_by_stage[stage_id] = batch
        return batch

    planning_batches = max(batch_for(stage_id) for stage_id in planning_stage_ids)

    assert planning_batches <= 6, batch_by_stage


@pytest.mark.parametrize("profile", ["lean", "standard", "enterprise"])
@pytest.mark.parametrize(
    ("scope", "strictness"),
    [("team", "standard"), ("organization", "regulated")],
)
def test_binding_preserves_resolved_gate_order_membership_and_digest(
    payload: Path, profile: str, scope: str, strictness: str
) -> None:
    workflow = load_workflow(payload)
    plan = catalog.resolve(
        payload,
        make_selection(
            payload,
            profile=profile,
            scope=scope,
            review_strictness=strictness,
        ),
    )

    bound = bind_workflow(workflow, plan)

    assert bound.active_gate_ids == tuple(plan.gates)
    assert bound.gate_definition_digest == plan.gate_definition_digest
    assert bound.gate_definition_digest == digest_gate_definitions(
        plan.gates, plan.gate_definitions
    )
    assert bound.gate_stage_ids == tuple(
        workflow.gates[gate_id].stage for gate_id in plan.gates
    )


def test_workflow_total_gate_order_covers_the_canonical_catalog(payload: Path) -> None:
    workflow = load_workflow(payload)
    profiles = yaml.safe_load((payload / "catalog" / "profiles.yaml").read_text())

    assert set(workflow.gates) == set(profiles["gate_definitions"])
    for gate_id, raw in profiles["gate_definitions"].items():
        gate = workflow.gates[gate_id]
        assert gate.requirement.value == raw["requirement"]
        assert gate.skippable is raw["skippable"]
        assert gate.skip_conditions == tuple(raw["skip_conditions"])


def test_schema_rejects_unknown_fields(payload: Path, tmp_path: Path) -> None:
    root = _mutated_payload(
        payload,
        tmp_path,
        lambda document: document.update({"provider_override": {}}),
    )

    with pytest.raises(WorkflowValidationError, match="provider_override"):
        load_workflow(root)


def test_schema_rejects_future_versions(payload: Path, tmp_path: Path) -> None:
    root = _mutated_payload(
        payload,
        tmp_path,
        lambda document: document.update({"schema_version": 2}),
    )

    with pytest.raises(WorkflowValidationError, match="schema_version"):
        load_workflow(root)


def test_stage_required_capabilities_are_typed_and_unknown_values_fail_schema(
    payload: Path, tmp_path: Path
) -> None:
    root = _mutated_payload(
        payload,
        tmp_path,
        lambda document: document["stages"][0].update(
            {"required_capabilities": ["filesystem.read", "workflow.ledger"]}
        ),
    )
    workflow = load_workflow(root)
    assert workflow.stages[0].required_capabilities == frozenset(
        {Capability.FILE_READ, Capability.TASK_LEDGER}
    )

    invalid = _mutated_payload(
        payload,
        tmp_path / "invalid",
        lambda document: document["stages"][0].update(
            {"required_capabilities": ["provider.magic"]}
        ),
    )
    with pytest.raises(WorkflowValidationError, match="provider.magic"):
        load_workflow(invalid)


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"action_kind": None}, "must declare an action kind"),
        ({"phase": "implementation"}, "must be in closeout"),
        ({"route": "general-delivery"}, "must use the pull-request route"),
        ({"depends_on": ["security-aggregate"]}, "must depend only on"),
        ({"evidence": ["review-verdict"]}, "must require exactly closeout-record"),
        (
            {"required_capabilities": ["filesystem.read", "external.mutation"]},
            "must require exactly external.mutation",
        ),
    ],
)
def test_typed_external_action_stage_fails_closed_on_contract_drift(
    payload: Path,
    tmp_path: Path,
    updates: dict,
    message: str,
) -> None:
    def mutate(document: dict) -> None:
        stage = next(
            item for item in document["stages"] if item["id"] == "pull-request"
        )
        stage.update(updates)

    root = _mutated_payload(payload, tmp_path, mutate)

    with pytest.raises(WorkflowValidationError, match=message):
        load_workflow(root)


def test_native_stage_cannot_smuggle_an_external_action_kind(
    payload: Path, tmp_path: Path
) -> None:
    def mutate(document: dict) -> None:
        stage = next(item for item in document["stages"] if item["id"] == "classify")
        stage["action_kind"] = "repository.pull-request.create"

    root = _mutated_payload(payload, tmp_path, mutate)

    with pytest.raises(WorkflowValidationError, match="cannot declare an action kind"):
        load_workflow(root)


def test_typed_external_action_must_be_terminal(payload: Path, tmp_path: Path) -> None:
    def mutate(document: dict) -> None:
        stage = next(item for item in document["stages"] if item["id"] == "classify")
        stage["depends_on"] = ["pull-request"]

    root = _mutated_payload(payload, tmp_path, mutate)

    with pytest.raises(WorkflowValidationError, match="must be terminal"):
        load_workflow(root)


def test_typed_pr_action_requires_matching_native_prepare(
    payload: Path, tmp_path: Path
) -> None:
    def mutate(document: dict) -> None:
        prepare = next(
            item for item in document["stages"] if item["id"] == "pull-request-prepare"
        )
        prepare["condition"] = "always"

    root = _mutated_payload(payload, tmp_path, mutate)

    with pytest.raises(WorkflowValidationError, match="matching native"):
        load_workflow(root)


def test_semantics_reject_dependency_cycles(payload: Path, tmp_path: Path) -> None:
    def mutate(document: dict) -> None:
        document["stages"][0]["depends_on"] = ["specification"]

    root = _mutated_payload(payload, tmp_path, mutate)

    with pytest.raises(WorkflowValidationError, match="dependency cycle"):
        load_workflow(root)


def test_semantics_reject_unknown_role_routes(payload: Path, tmp_path: Path) -> None:
    def mutate(document: dict) -> None:
        document["stages"][0]["route"] = "missing-route"

    root = _mutated_payload(payload, tmp_path, mutate)

    with pytest.raises(WorkflowValidationError, match="unknown role route"):
        load_workflow(root)


def test_loader_rejects_duplicate_yaml_keys(payload: Path, tmp_path: Path) -> None:
    root = tmp_path / "payload"
    workflow_dir = root / "catalog" / "workflows"
    schema_dir = root / "schemas"
    workflow_dir.mkdir(parents=True)
    schema_dir.mkdir(parents=True)
    shutil.copy2(payload / "schemas" / "workflow.schema.json", schema_dir)
    original = (payload / "catalog" / "workflows" / "sdlc.yaml").read_text(
        encoding="utf-8"
    )
    (workflow_dir / "sdlc.yaml").write_text(
        original.replace(
            "schema_version: 1", "schema_version: 1\nschema_version: 1", 1
        ),
        encoding="utf-8",
    )

    with pytest.raises(WorkflowValidationError, match="duplicate workflow key"):
        load_workflow(root)


def test_binding_rejects_gate_order_or_digest_drift(payload: Path) -> None:
    workflow = load_workflow(payload)
    plan = catalog.resolve(payload, make_selection(payload, profile="standard"))
    reordered = replace(plan, gates=list(reversed(plan.gates)))
    bad_digest = replace(plan, gate_definition_digest="0" * 64)

    with pytest.raises(WorkflowValidationError, match="gate order"):
        bind_workflow(workflow, reordered)
    with pytest.raises(WorkflowValidationError, match="digest"):
        bind_workflow(workflow, bad_digest)


def test_lean_full_mode_has_an_installed_native_role_for_every_route(
    payload: Path,
) -> None:
    workflow = load_workflow(payload)
    plan = catalog.resolve(payload, make_selection(payload, profile="lean"))

    bound = bind_workflow(workflow, plan)
    installed = set(plan.agents) | set(plan.overlay_agents)

    assert bound.stages_for_mode("B")
    for stage in bound.stages_for_mode("B"):
        route = workflow.roles[stage.route]
        assert installed.intersection((route.primary,) + route.fallbacks), stage.id


def test_binding_rejects_a_plan_without_any_available_route(payload: Path) -> None:
    workflow = load_workflow(payload)
    plan = catalog.resolve(payload, make_selection(payload, profile="lean"))
    unavailable = replace(plan, agents=[], overlay_agents=[])

    with pytest.raises(WorkflowValidationError, match="no native role"):
        bind_workflow(workflow, unavailable)


def test_workflow_id_cannot_escape_payload(payload: Path) -> None:
    with pytest.raises(WorkflowValidationError, match="contained"):
        load_workflow(payload, "../profiles")
