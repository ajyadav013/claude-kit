"""Strict loading and plan binding for provider-neutral workflow catalogs.

The workflow catalog owns orchestration semantics (routing, joins, retries,
evidence and mode policy).  The existing catalog resolver continues to own
selection.  :func:`bind_workflow` is the narrow seam between them: it filters a
workflow's total gate order to a supplied :class:`~claude_kit.models.ResolvedPlan`
and fails closed if policy or the frozen definition digest has drifted.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Optional, Type, TypeVar

import jsonschema
import yaml

from claude_kit.components import Capability
from claude_kit.models import GateDefinition, ResolvedPlan, digest_gate_definitions

WORKFLOW_SCHEMA_VERSION = 1
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_EnumT = TypeVar("_EnumT", bound=Enum)


class WorkflowValidationError(ValueError):
    """Raised when workflow structure, references, or plan policy are invalid."""


def _canonical_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: _canonical_value(getattr(value, item.name))
            for item in fields(value)
        }
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (set, frozenset)):
        rendered = [_canonical_value(item) for item in value]
        return sorted(rendered, key=lambda item: json.dumps(item, sort_keys=True))
    if isinstance(value, (tuple, list)):
        return [_canonical_value(item) for item in value]
    return value


def workflow_definition_digest(workflow: WorkflowDefinition) -> str:
    """Hash every structured role, route, condition, gate, and retry definition."""
    encoded = json.dumps(
        _canonical_value(workflow),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class GateRequirement(str, Enum):
    """Whether a gate is unconditional or may close as not applicable."""

    REQUIRED = "required"
    CONDITIONAL = "conditional"


class ExhaustedAction(str, Enum):
    """Portable action taken when a retry budget is exhausted."""

    ESCALATE_HUMAN = "escalate-human"
    CANCEL_LANE = "cancel-lane"
    CHECKPOINT_AND_ESCALATE = "checkpoint-and-escalate"


class GatePolicy(str, Enum):
    """How a workflow mode obtains its gate membership."""

    RESOLVED_PLAN = "resolved-plan"
    SUBSET = "subset"


class EvidenceKind(str, Enum):
    """Closed portable evidence categories."""

    ARTIFACT = "artifact"
    COMMAND_OUTPUT = "command-output"
    VERDICT = "verdict"
    FINDINGS_REPORT = "findings-report"
    MANIFEST = "manifest"
    APPROVAL = "approval"
    RESTORE_POINT = "restore-point"


class StageExecutionKind(str, Enum):
    """How a workflow stage is executed by the authoritative coordinator."""

    NATIVE_ROLE = "native-role"
    TYPED_EXTERNAL_ACTION = "typed-external-action"


class ExternalActionKind(str, Enum):
    """Closed coordinator-owned external actions supported by workflow data."""

    CREATE_PULL_REQUEST = "repository.pull-request.create"


@dataclass(frozen=True)
class RoleRoute:
    """A logical role route with ordered fallbacks."""

    id: str
    primary: str
    fallbacks: tuple[str, ...]
    responsibility: str


@dataclass(frozen=True)
class RetryBudget:
    """Bounded retries and feedback cycles for a stage category."""

    id: str
    max_transient_retries: int
    max_feedback_iterations: int
    max_defect_cycles: int
    on_exhausted: ExhaustedAction


@dataclass(frozen=True)
class EvidenceRequirement:
    """Required shape and containment policy for one evidence record."""

    id: str
    kind: EvidenceKind
    description: str
    required_fields: tuple[str, ...]
    project_contained: bool


@dataclass(frozen=True)
class AcceptedRiskPolicy:
    """Severities and fields permitted for a structured accepted risk."""

    allowed_severities: tuple[str, ...]
    required_fields: tuple[str, ...]


@dataclass(frozen=True)
class FindingsPolicy:
    """Portable policy for blocking, waiving, and citing findings."""

    severity_order: tuple[str, ...]
    blocking_severities: tuple[str, ...]
    pass_requires_zero: tuple[str, ...]
    critical_high_waivable: bool
    uncited_finding: str
    accepted_risk: AcceptedRiskPolicy


@dataclass(frozen=True)
class WorkflowGate:
    """One quality gate and the stage/evidence that closes it."""

    id: str
    stage: str
    requirement: GateRequirement
    skippable: bool
    skip_conditions: tuple[str, ...]
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class WorkflowStageDefinition:
    """A routed unit of workflow work."""

    id: str
    phase: str
    route: str
    depends_on: tuple[str, ...]
    parallel_group: Optional[str]
    condition: str
    gates: tuple[str, ...]
    retry_budget: str
    evidence: tuple[str, ...]
    required_capabilities: frozenset[Capability] = frozenset()
    execution_kind: StageExecutionKind = StageExecutionKind.NATIVE_ROLE
    action_kind: Optional[ExternalActionKind] = None


@dataclass(frozen=True)
class ParallelLane:
    """One disjoint lane inside a fork/join group."""

    id: str
    stages: tuple[str, ...]
    boundary: str


@dataclass(frozen=True)
class ParallelGroup:
    """Fork/join semantics for independently dispatchable lanes."""

    id: str
    fork_after: str
    join_before: str
    concurrency: str
    lanes: tuple[ParallelLane, ...]


@dataclass(frozen=True)
class ProgramWave:
    """One ordered wave in program-scale mode."""

    id: str
    order: int
    kind: str
    parallel: bool
    risk_ordered: bool
    repeatable: bool
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class ProgramMode:
    """Activation thresholds and safeguards for wave execution."""

    files_over: int
    independent_lanes_over: int
    irreversible_always: bool
    manifest_required: bool
    freeze_before_execution: bool
    disjoint_boundaries_required: bool
    human_approval_for_irreversible: bool
    restore_point_for_irreversible: bool
    waves: tuple[ProgramWave, ...]


@dataclass(frozen=True)
class WorkflowMode:
    """A named execution shape selected from the same stage graph."""

    id: str
    code: str
    description: str
    triggers: tuple[str, ...]
    all_stages: bool
    stages: tuple[str, ...]
    parallel_groups: tuple[str, ...]
    gate_policy: GatePolicy
    gates: tuple[str, ...]
    gate_stages: Mapping[str, str]
    program: Optional[ProgramMode]


@dataclass(frozen=True)
class WorkflowDefinition:
    """Complete provider-neutral workflow contract."""

    schema_version: int
    id: str
    title: str
    description: str
    roles: Mapping[str, RoleRoute]
    retry_budgets: Mapping[str, RetryBudget]
    evidence_requirements: Mapping[str, EvidenceRequirement]
    findings_policy: FindingsPolicy
    ordered_gates: tuple[str, ...]
    gates: Mapping[str, WorkflowGate]
    stages: tuple[WorkflowStageDefinition, ...]
    parallel_groups: Mapping[str, ParallelGroup]
    modes: Mapping[str, WorkflowMode]

    @property
    def stage_by_id(self) -> dict[str, WorkflowStageDefinition]:
        """Return an id-indexed copy of the stage graph."""
        return {stage.id: stage for stage in self.stages}


@dataclass(frozen=True)
class BoundWorkflow:
    """A workflow whose gate membership is frozen to one resolved plan."""

    definition: WorkflowDefinition
    active_gates: tuple[WorkflowGate, ...]
    gate_stage_ids: tuple[str, ...]
    gate_definition_digest: str

    @property
    def active_gate_ids(self) -> tuple[str, ...]:
        """Gate ids in the exact order supplied by the resolved plan."""
        return tuple(gate.id for gate in self.active_gates)

    def gate_ids_for_mode(self, mode_id_or_code: str) -> tuple[str, ...]:
        """Return the frozen gate order projected through one mode policy."""
        matches = [
            mode
            for mode in self.definition.modes.values()
            if mode.id == mode_id_or_code or mode.code == mode_id_or_code
        ]
        if len(matches) != 1:
            raise WorkflowValidationError(
                f"workflow mode must name exactly one id or code: {mode_id_or_code!r}"
            )
        mode = matches[0]
        if mode.gate_policy is GatePolicy.RESOLVED_PLAN:
            return self.active_gate_ids
        requested = set(mode.gates)
        selected = tuple(gate for gate in self.active_gate_ids if gate in requested)
        if set(selected) != requested:
            missing = ", ".join(sorted(requested - set(selected)))
            raise WorkflowValidationError(
                f"workflow mode {mode.id!r} requires gates absent from the plan: {missing}"
            )
        return selected

    def gate_definition_digest_for_mode(self, mode_id_or_code: str) -> str:
        """Digest the exact ordered gate policy active in one execution mode."""
        gate_ids = self.gate_ids_for_mode(mode_id_or_code)
        gates = {gate.id: gate for gate in self.active_gates}
        definitions = {
            gate_id: GateDefinition(
                requirement=gates[gate_id].requirement.value,
                skippable=gates[gate_id].skippable,
                skip_conditions=list(gates[gate_id].skip_conditions),
            )
            for gate_id in gate_ids
        }
        return digest_gate_definitions(list(gate_ids), definitions)

    def gate_owner_stages_for_mode(self, mode_id_or_code: str) -> Mapping[str, str]:
        """Return the named stage authorized to own each mode-projected gate."""
        matches = [
            mode
            for mode in self.definition.modes.values()
            if mode.id == mode_id_or_code or mode.code == mode_id_or_code
        ]
        if len(matches) != 1:
            raise WorkflowValidationError(
                f"workflow mode must name exactly one id or code: {mode_id_or_code!r}"
            )
        mode = matches[0]
        gate_ids = self.gate_ids_for_mode(mode.id)
        if mode.gate_policy is GatePolicy.SUBSET:
            return {gate_id: mode.gate_stages[gate_id] for gate_id in gate_ids}
        return {gate_id: self.definition.gates[gate_id].stage for gate_id in gate_ids}

    def stages_for_mode(
        self, mode_id_or_code: str
    ) -> tuple[WorkflowStageDefinition, ...]:
        """Return the ordered stage projection for one declared execution mode.

        A stage whose only gate assignments are outside the resolved plan is not
        active. Dependencies on an omitted stage are treated as already outside
        this projection by the executor, never as evidence that the stage passed.
        """
        matches = [
            mode
            for mode in self.definition.modes.values()
            if mode.id == mode_id_or_code or mode.code == mode_id_or_code
        ]
        if len(matches) != 1:
            raise WorkflowValidationError(
                f"workflow mode must name exactly one id or code: {mode_id_or_code!r}"
            )
        mode = matches[0]
        selected = (
            {stage.id for stage in self.definition.stages}
            if mode.all_stages
            else set(mode.stages)
        )
        active_gates = set(self.active_gate_ids)
        return tuple(
            stage
            for stage in self.definition.stages
            if stage.id in selected
            and (not stage.gates or bool(set(stage.gates) & active_gates))
        )


class _UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys."""


def _construct_unique_mapping(
    loader: _UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False
) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            exists = key in mapping
        except TypeError as exc:
            raise WorkflowValidationError(
                "workflow mapping key must be scalar"
            ) from exc
        if exists:
            raise WorkflowValidationError(f"duplicate workflow key: {key!r}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _enum(value: str, enum_type: Type[_EnumT], path: str) -> _EnumT:
    try:
        return enum_type(value)
    except ValueError as exc:
        allowed = ", ".join(str(item.value) for item in enum_type)
        raise WorkflowValidationError(f"{path} must be one of: {allowed}") from exc


def _load_yaml(path: Path) -> Any:
    try:
        return yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
    except OSError as exc:
        raise WorkflowValidationError(
            f"cannot read workflow catalog {path}: {exc}"
        ) from exc
    except yaml.YAMLError as exc:
        raise WorkflowValidationError(
            f"invalid workflow YAML at {path}: {exc}"
        ) from exc


def _load_schema(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkflowValidationError(
            f"cannot load workflow schema {path}: {exc}"
        ) from exc
    if not isinstance(raw, dict):
        raise WorkflowValidationError("workflow schema root must be an object")
    return raw


def _validate_schema(document: Any, schema: dict[str, Any]) -> None:
    validator_type = jsonschema.validators.validator_for(schema)
    try:
        validator_type.check_schema(schema)
    except jsonschema.SchemaError as exc:
        raise WorkflowValidationError(
            f"invalid workflow schema: {exc.message}"
        ) from exc
    validator = validator_type(schema)
    errors = sorted(validator.iter_errors(document), key=lambda item: list(item.path))
    if not errors:
        return
    rendered = []
    for error in errors:
        location = "/".join(str(part) for part in error.path) or "(root)"
        rendered.append(f"{location}: {error.message}")
    raise WorkflowValidationError(
        "workflow schema validation failed: " + "; ".join(rendered)
    )


def _role_routes(raw: Mapping[str, Any]) -> dict[str, RoleRoute]:
    out: dict[str, RoleRoute] = {}
    for role_id, value in raw.items():
        item = value
        out[role_id] = RoleRoute(
            id=role_id,
            primary=str(item["primary"]),
            fallbacks=tuple(str(value) for value in item["fallbacks"]),
            responsibility=str(item["responsibility"]),
        )
    return out


def _retry_budgets(raw: Mapping[str, Any]) -> dict[str, RetryBudget]:
    out: dict[str, RetryBudget] = {}
    for budget_id, value in raw.items():
        item = value
        out[budget_id] = RetryBudget(
            id=budget_id,
            max_transient_retries=int(item["max_transient_retries"]),
            max_feedback_iterations=int(item["max_feedback_iterations"]),
            max_defect_cycles=int(item["max_defect_cycles"]),
            on_exhausted=_enum(
                str(item["on_exhausted"]), ExhaustedAction, f"retry_budgets/{budget_id}"
            ),
        )
    return out


def _evidence_requirements(raw: Mapping[str, Any]) -> dict[str, EvidenceRequirement]:
    out: dict[str, EvidenceRequirement] = {}
    for evidence_id, value in raw.items():
        item = value
        out[evidence_id] = EvidenceRequirement(
            id=evidence_id,
            kind=_enum(
                str(item["kind"]), EvidenceKind, f"evidence_requirements/{evidence_id}"
            ),
            description=str(item["description"]),
            required_fields=tuple(str(field) for field in item["required_fields"]),
            project_contained=bool(item["project_contained"]),
        )
    return out


def _findings_policy(raw: Mapping[str, Any]) -> FindingsPolicy:
    accepted = raw["accepted_risk"]
    return FindingsPolicy(
        severity_order=tuple(str(value) for value in raw["severity_order"]),
        blocking_severities=tuple(str(value) for value in raw["blocking_severities"]),
        pass_requires_zero=tuple(str(value) for value in raw["pass_requires_zero"]),
        critical_high_waivable=bool(raw["critical_high_waivable"]),
        uncited_finding=str(raw["uncited_finding"]),
        accepted_risk=AcceptedRiskPolicy(
            allowed_severities=tuple(
                str(value) for value in accepted["allowed_severities"]
            ),
            required_fields=tuple(str(value) for value in accepted["required_fields"]),
        ),
    )


def _gates(raw: Mapping[str, Any]) -> dict[str, WorkflowGate]:
    out: dict[str, WorkflowGate] = {}
    for gate_id, value in raw.items():
        item = value
        out[gate_id] = WorkflowGate(
            id=gate_id,
            stage=str(item["stage"]),
            requirement=_enum(
                str(item["requirement"]), GateRequirement, f"gates/{gate_id}"
            ),
            skippable=bool(item["skippable"]),
            skip_conditions=tuple(str(value) for value in item["skip_conditions"]),
            evidence=tuple(str(value) for value in item["evidence"]),
        )
    return out


def _stages(raw: list[Any]) -> tuple[WorkflowStageDefinition, ...]:
    return tuple(
        WorkflowStageDefinition(
            id=str(item["id"]),
            phase=str(item["phase"]),
            route=str(item["route"]),
            depends_on=tuple(str(value) for value in item["depends_on"]),
            parallel_group=(
                str(item["parallel_group"])
                if item["parallel_group"] is not None
                else None
            ),
            condition=str(item["condition"]),
            gates=tuple(str(value) for value in item["gates"]),
            retry_budget=str(item["retry_budget"]),
            evidence=tuple(str(value) for value in item["evidence"]),
            required_capabilities=frozenset(
                Capability(str(value))
                for value in item.get("required_capabilities", [])
            ),
            execution_kind=_enum(
                str(item.get("execution_kind", StageExecutionKind.NATIVE_ROLE.value)),
                StageExecutionKind,
                f"stages/{item['id']}/execution_kind",
            ),
            action_kind=(
                _enum(
                    str(item["action_kind"]),
                    ExternalActionKind,
                    f"stages/{item['id']}/action_kind",
                )
                if item.get("action_kind") is not None
                else None
            ),
        )
        for item in raw
    )


def _parallel_groups(raw: Mapping[str, Any]) -> dict[str, ParallelGroup]:
    out: dict[str, ParallelGroup] = {}
    for group_id, value in raw.items():
        item = value
        lanes = tuple(
            ParallelLane(
                id=str(lane["id"]),
                stages=tuple(str(stage) for stage in lane["stages"]),
                boundary=str(lane["boundary"]),
            )
            for lane in item["lanes"]
        )
        out[group_id] = ParallelGroup(
            id=group_id,
            fork_after=str(item["fork_after"]),
            join_before=str(item["join_before"]),
            concurrency=str(item["concurrency"]),
            lanes=lanes,
        )
    return out


def _program_mode(raw: Mapping[str, Any]) -> ProgramMode:
    activation = raw["activation"]
    waves = tuple(
        ProgramWave(
            id=str(wave["id"]),
            order=int(wave["order"]),
            kind=str(wave["kind"]),
            parallel=bool(wave["parallel"]),
            risk_ordered=bool(wave["risk_ordered"]),
            repeatable=bool(wave["repeatable"]),
            evidence=tuple(str(value) for value in wave["evidence"]),
        )
        for wave in raw["waves"]
    )
    return ProgramMode(
        files_over=int(activation["files_over"]),
        independent_lanes_over=int(activation["independent_lanes_over"]),
        irreversible_always=bool(activation["irreversible_always"]),
        manifest_required=bool(raw["manifest_required"]),
        freeze_before_execution=bool(raw["freeze_before_execution"]),
        disjoint_boundaries_required=bool(raw["disjoint_boundaries_required"]),
        human_approval_for_irreversible=bool(raw["human_approval_for_irreversible"]),
        restore_point_for_irreversible=bool(raw["restore_point_for_irreversible"]),
        waves=waves,
    )


def _modes(raw: Mapping[str, Any]) -> dict[str, WorkflowMode]:
    out: dict[str, WorkflowMode] = {}
    for mode_id, value in raw.items():
        item = value
        stage_value = item["stages"]
        all_stages = stage_value == "all"
        stages = () if all_stages else tuple(str(stage) for stage in stage_value)
        program_raw = item.get("program")
        out[mode_id] = WorkflowMode(
            id=mode_id,
            code=str(item["code"]),
            description=str(item["description"]),
            triggers=tuple(str(value) for value in item["triggers"]),
            all_stages=all_stages,
            stages=stages,
            parallel_groups=tuple(str(value) for value in item["parallel_groups"]),
            gate_policy=_enum(str(item["gate_policy"]), GatePolicy, f"modes/{mode_id}"),
            gates=tuple(str(value) for value in item["gates"]),
            gate_stages={
                str(gate_id): str(stage_id)
                for gate_id, stage_id in item.get("gate_stages", {}).items()
            },
            program=_program_mode(program_raw) if program_raw is not None else None,
        )
    return out


def _validate_references(workflow: WorkflowDefinition) -> None:
    stage_by_id = workflow.stage_by_id
    if len(stage_by_id) != len(workflow.stages):
        raise WorkflowValidationError("workflow stage ids must be unique")

    gate_ids = set(workflow.gates)
    if set(workflow.ordered_gates) != gate_ids:
        raise WorkflowValidationError(
            "ordered_gates must contain every workflow gate exactly once"
        )

    assigned_gates: dict[str, str] = {}
    for stage in workflow.stages:
        if stage.route not in workflow.roles:
            raise WorkflowValidationError(
                f"stage {stage.id!r} references unknown role route {stage.route!r}"
            )
        if stage.retry_budget not in workflow.retry_budgets:
            raise WorkflowValidationError(
                f"stage {stage.id!r} references unknown retry budget {stage.retry_budget!r}"
            )
        _require_refs(
            stage.evidence, workflow.evidence_requirements, f"stage {stage.id} evidence"
        )
        for dependency in stage.depends_on:
            if dependency not in stage_by_id:
                raise WorkflowValidationError(
                    f"stage {stage.id!r} references unknown dependency {dependency!r}"
                )
            if dependency == stage.id:
                raise WorkflowValidationError(
                    f"stage {stage.id!r} cannot depend on itself"
                )
        for gate_id in stage.gates:
            if gate_id not in gate_ids:
                raise WorkflowValidationError(
                    f"stage {stage.id!r} references unknown gate {gate_id!r}"
                )
            if gate_id in assigned_gates:
                raise WorkflowValidationError(
                    f"gate {gate_id!r} is assigned to multiple stages"
                )
            assigned_gates[gate_id] = stage.id

        if stage.execution_kind is StageExecutionKind.NATIVE_ROLE:
            if stage.action_kind is not None:
                raise WorkflowValidationError(
                    f"native-role stage {stage.id!r} cannot declare an action kind"
                )
        else:
            if stage.action_kind is None:
                raise WorkflowValidationError(
                    f"typed external-action stage {stage.id!r} must declare an action kind"
                )
            if stage.phase != "closeout":
                raise WorkflowValidationError(
                    f"typed external-action stage {stage.id!r} must be in closeout"
                )
            if stage.parallel_group is not None or stage.gates:
                raise WorkflowValidationError(
                    f"typed external-action stage {stage.id!r} cannot own a lane or gate"
                )
            if stage.required_capabilities != frozenset({Capability.EXTERNAL_MUTATION}):
                raise WorkflowValidationError(
                    f"typed external-action stage {stage.id!r} must require exactly external.mutation"
                )
            if stage.action_kind is ExternalActionKind.CREATE_PULL_REQUEST:
                expected_prepare = f"{stage.id}-prepare"
                if stage.route != "pull-request":
                    raise WorkflowValidationError(
                        f"typed PR stage {stage.id!r} must use the pull-request route"
                    )
                if stage.depends_on != (expected_prepare,):
                    raise WorkflowValidationError(
                        f"typed PR stage {stage.id!r} must depend only on {expected_prepare!r}"
                    )
                if stage.evidence != ("closeout-record",):
                    raise WorkflowValidationError(
                        f"typed PR stage {stage.id!r} must require exactly closeout-record evidence"
                    )

    if set(assigned_gates) != gate_ids:
        missing = ", ".join(sorted(gate_ids - set(assigned_gates)))
        raise WorkflowValidationError(f"workflow gates missing from stages: {missing}")

    downstream: dict[str, list[str]] = {stage.id: [] for stage in workflow.stages}
    for candidate in workflow.stages:
        for dependency in candidate.depends_on:
            downstream[dependency].append(candidate.id)
    for stage in workflow.stages:
        if stage.execution_kind is not StageExecutionKind.TYPED_EXTERNAL_ACTION:
            continue
        if downstream[stage.id]:
            dependents = ", ".join(sorted(downstream[stage.id]))
            raise WorkflowValidationError(
                f"typed external-action stage {stage.id!r} must be terminal; "
                f"downstream stages: {dependents}"
            )
        if stage.action_kind is ExternalActionKind.CREATE_PULL_REQUEST:
            prepare = stage_by_id[stage.depends_on[0]]
            if (
                prepare.execution_kind is not StageExecutionKind.NATIVE_ROLE
                or prepare.phase != "closeout"
                or prepare.route != "pull-request-prepare"
                or prepare.condition != stage.condition
                or prepare.evidence != ("closeout-record",)
            ):
                raise WorkflowValidationError(
                    f"typed PR stage {stage.id!r} requires a matching native "
                    "pull-request-prepare stage"
                )

    for gate_id, gate in workflow.gates.items():
        if gate.stage not in stage_by_id:
            raise WorkflowValidationError(
                f"gate {gate_id!r} references unknown stage {gate.stage!r}"
            )
        if assigned_gates[gate_id] != gate.stage:
            raise WorkflowValidationError(
                f"gate {gate_id!r} stage does not match its stage assignment"
            )
        expected_skippable = gate.requirement is GateRequirement.CONDITIONAL
        if gate.skippable != expected_skippable:
            raise WorkflowValidationError(
                f"gate {gate_id!r} skippable must match conditional requirement"
            )
        if expected_skippable != bool(gate.skip_conditions):
            raise WorkflowValidationError(
                f"gate {gate_id!r} skip conditions must exist only for conditional gates"
            )
        _require_refs(
            gate.evidence, workflow.evidence_requirements, f"gate {gate_id} evidence"
        )

    _validate_acyclic(workflow.stages)
    _validate_parallel_groups(workflow)
    _validate_modes(workflow)
    _validate_findings_policy(workflow.findings_policy)


def _require_refs(
    values: tuple[str, ...], choices: Mapping[str, Any], label: str
) -> None:
    missing = sorted(set(values) - set(choices))
    if missing:
        raise WorkflowValidationError(
            f"{label} references unknown ids: {', '.join(missing)}"
        )


def _validate_acyclic(stages: tuple[WorkflowStageDefinition, ...]) -> None:
    dependencies = {stage.id: stage.depends_on for stage in stages}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(stage_id: str) -> None:
        if stage_id in visiting:
            raise WorkflowValidationError(
                f"workflow dependency cycle contains {stage_id!r}"
            )
        if stage_id in visited:
            return
        visiting.add(stage_id)
        for dependency in dependencies[stage_id]:
            visit(dependency)
        visiting.remove(stage_id)
        visited.add(stage_id)

    for stage_id in dependencies:
        visit(stage_id)


def _validate_parallel_groups(workflow: WorkflowDefinition) -> None:
    stage_by_id = workflow.stage_by_id
    grouped_stages: dict[str, str] = {}
    for group_id, group in workflow.parallel_groups.items():
        for boundary_name, stage_id in (
            ("fork_after", group.fork_after),
            ("join_before", group.join_before),
        ):
            if stage_id not in stage_by_id:
                raise WorkflowValidationError(
                    f"parallel group {group_id!r} {boundary_name} references unknown stage {stage_id!r}"
                )
        lane_ids = [lane.id for lane in group.lanes]
        if len(set(lane_ids)) != len(lane_ids):
            raise WorkflowValidationError(
                f"parallel group {group_id!r} lane ids must be unique"
            )
        for lane in group.lanes:
            for stage_id in lane.stages:
                if stage_id not in stage_by_id:
                    raise WorkflowValidationError(
                        f"parallel lane {lane.id!r} references unknown stage {stage_id!r}"
                    )
                stage = stage_by_id[stage_id]
                if stage.parallel_group != group_id:
                    raise WorkflowValidationError(
                        f"stage {stage_id!r} does not name parallel group {group_id!r}"
                    )
                if stage_id in grouped_stages:
                    raise WorkflowValidationError(
                        f"stage {stage_id!r} appears in multiple parallel lanes"
                    )
                grouped_stages[stage_id] = group_id

    for stage in workflow.stages:
        if stage.parallel_group is None:
            continue
        if stage.parallel_group not in workflow.parallel_groups:
            raise WorkflowValidationError(
                f"stage {stage.id!r} references unknown parallel group {stage.parallel_group!r}"
            )
        if stage.id not in grouped_stages:
            raise WorkflowValidationError(
                f"stage {stage.id!r} is not assigned to a lane in {stage.parallel_group!r}"
            )


def _validate_modes(workflow: WorkflowDefinition) -> None:
    stage_ids = set(workflow.stage_by_id)
    gate_ids = set(workflow.gates)
    group_ids = set(workflow.parallel_groups)
    codes = [mode.code for mode in workflow.modes.values()]
    if set(codes) != {"A", "B", "C", "D", "E"} or len(codes) != 5:
        raise WorkflowValidationError(
            "workflow modes must define codes A through E exactly once"
        )

    for mode in workflow.modes.values():
        if not mode.all_stages:
            _require_refs(mode.stages, workflow.stage_by_id, f"mode {mode.id} stages")
        _require_refs(
            mode.parallel_groups, workflow.parallel_groups, f"mode {mode.id} groups"
        )
        _require_refs(mode.gates, workflow.gates, f"mode {mode.id} gates")
        if mode.gate_policy is GatePolicy.RESOLVED_PLAN and mode.gates:
            raise WorkflowValidationError(
                f"mode {mode.id!r} uses resolved-plan gates and must not list a subset"
            )
        if mode.gate_policy is GatePolicy.RESOLVED_PLAN and mode.gate_stages:
            raise WorkflowValidationError(
                f"mode {mode.id!r} uses resolved-plan gates and cannot override owners"
            )
        if mode.gate_policy is GatePolicy.SUBSET and not mode.gates:
            raise WorkflowValidationError(
                f"mode {mode.id!r} uses subset gates and must list them"
            )
        if mode.gate_policy is GatePolicy.SUBSET:
            if set(mode.gate_stages) != set(mode.gates):
                raise WorkflowValidationError(
                    f"mode {mode.id!r} must assign one owner stage to every subset gate"
                )
            selected_stages = stage_ids if mode.all_stages else set(mode.stages)
            if not set(mode.gate_stages.values()).issubset(selected_stages):
                raise WorkflowValidationError(
                    f"mode {mode.id!r} gate owner stages must belong to the mode"
                )
        if mode.code == "E" and mode.program is None:
            raise WorkflowValidationError(
                "program mode E must define program safeguards"
            )
        if mode.code != "E" and mode.program is not None:
            raise WorkflowValidationError(
                f"only program mode E may define program safeguards ({mode.id!r})"
            )
        if not set(mode.stages).issubset(stage_ids):
            raise WorkflowValidationError(f"mode {mode.id!r} contains unknown stages")
        if not set(mode.gates).issubset(gate_ids):
            raise WorkflowValidationError(f"mode {mode.id!r} contains unknown gates")
        if not set(mode.parallel_groups).issubset(group_ids):
            raise WorkflowValidationError(f"mode {mode.id!r} contains unknown groups")
        if mode.program is not None:
            _validate_program(mode.program, workflow.evidence_requirements)


def _validate_program(
    program: ProgramMode, evidence_requirements: Mapping[str, EvidenceRequirement]
) -> None:
    ids = [wave.id for wave in program.waves]
    orders = [wave.order for wave in program.waves]
    if len(set(ids)) != len(ids):
        raise WorkflowValidationError("program wave ids must be unique")
    if orders != list(range(len(orders))):
        raise WorkflowValidationError(
            "program wave order must be contiguous and start at zero"
        )
    for wave in program.waves:
        _require_refs(
            wave.evidence, evidence_requirements, f"program wave {wave.id} evidence"
        )


def _validate_findings_policy(policy: FindingsPolicy) -> None:
    severity_set = set(policy.severity_order)
    if not set(policy.blocking_severities).issubset(severity_set):
        raise WorkflowValidationError(
            "blocking severities must appear in severity_order"
        )
    if not set(policy.pass_requires_zero).issubset(policy.blocking_severities):
        raise WorkflowValidationError(
            "pass_requires_zero must be a subset of blocking severities"
        )
    if not set(policy.accepted_risk.allowed_severities).issubset(
        policy.blocking_severities
    ):
        raise WorkflowValidationError(
            "accepted-risk severities must be a subset of blocking severities"
        )
    if policy.critical_high_waivable:
        raise WorkflowValidationError(
            "critical and high findings must never be waivable"
        )
    if {"critical", "high"} & set(policy.accepted_risk.allowed_severities):
        raise WorkflowValidationError(
            "critical and high findings cannot be accepted risks"
        )


def _build_workflow(document: Mapping[str, Any]) -> WorkflowDefinition:
    workflow = WorkflowDefinition(
        schema_version=int(document["schema_version"]),
        id=str(document["id"]),
        title=str(document["title"]),
        description=str(document["description"]),
        roles=_role_routes(document["roles"]),
        retry_budgets=_retry_budgets(document["retry_budgets"]),
        evidence_requirements=_evidence_requirements(document["evidence_requirements"]),
        findings_policy=_findings_policy(document["findings_policy"]),
        ordered_gates=tuple(str(value) for value in document["ordered_gates"]),
        gates=_gates(document["gates"]),
        stages=_stages(document["stages"]),
        parallel_groups=_parallel_groups(document["parallel_groups"]),
        modes=_modes(document["modes"]),
    )
    _validate_references(workflow)
    return workflow


def load_workflow(payload_root: Path, workflow_id: str = "sdlc") -> WorkflowDefinition:
    """Load, schema-check, and semantically validate one workflow catalog.

    ``payload_root`` is explicit so the same function works in a source checkout,
    a bundled wheel, and isolated tests without consulting process-global paths.
    """
    if (
        not isinstance(workflow_id, str)
        or not _ID_RE.fullmatch(workflow_id)
        or ".." in workflow_id
    ):
        raise WorkflowValidationError(
            "workflow id must be a contained lowercase identifier"
        )
    root = Path(payload_root)
    workflow_path = root / "catalog" / "workflows" / f"{workflow_id}.yaml"
    schema_path = root / "schemas" / "workflow.schema.json"
    document = _load_yaml(workflow_path)
    schema = _load_schema(schema_path)
    _validate_schema(document, schema)
    if not isinstance(document, dict):
        raise WorkflowValidationError("workflow catalog root must be an object")
    workflow = _build_workflow(document)
    if workflow.schema_version != WORKFLOW_SCHEMA_VERSION:
        raise WorkflowValidationError(
            f"unsupported workflow schema version {workflow.schema_version}"
        )
    if workflow.id != workflow_id:
        raise WorkflowValidationError(
            f"workflow document id {workflow.id!r} does not match filename {workflow_id!r}"
        )
    return workflow


def bind_workflow(workflow: WorkflowDefinition, plan: ResolvedPlan) -> BoundWorkflow:
    """Bind gate membership/order to ``plan`` without changing its gate policy.

    The resolved plan remains authoritative.  Binding proves three invariants:
    every selected gate is known, its position is the workflow's canonical total
    order, and its requirement metadata reproduces the plan's frozen digest.
    """
    unknown = sorted(set(plan.gates) - set(workflow.gates))
    if unknown:
        raise WorkflowValidationError(
            "resolved plan references gates absent from workflow: " + ", ".join(unknown)
        )
    expected_order = tuple(
        gate_id for gate_id in workflow.ordered_gates if gate_id in set(plan.gates)
    )
    supplied_order = tuple(plan.gates)
    if supplied_order != expected_order:
        raise WorkflowValidationError(
            "resolved plan gate order differs from the workflow canonical order"
        )
    if set(plan.gate_definitions) != set(plan.gates):
        raise WorkflowValidationError(
            "resolved plan gate definitions do not match selected gate membership"
        )

    installed_roles = set(plan.agents) | set(plan.overlay_agents)
    unavailable_routes: list[str] = []
    for route_id, route in workflow.roles.items():
        candidates = (route.primary,) + route.fallbacks
        if not installed_roles.intersection(candidates):
            unavailable_routes.append(f"{route_id} ({', '.join(candidates)})")
    if unavailable_routes:
        raise WorkflowValidationError(
            "resolved plan installs no native role for workflow routes: "
            + "; ".join(unavailable_routes)
        )

    for gate_id in plan.gates:
        gate = workflow.gates[gate_id]
        definition = plan.gate_definitions[gate_id]
        if definition.requirement != gate.requirement.value:
            raise WorkflowValidationError(
                f"resolved plan requirement for gate {gate_id!r} differs from workflow"
            )
        if definition.skippable != gate.skippable:
            raise WorkflowValidationError(
                f"resolved plan skippable policy for gate {gate_id!r} differs from workflow"
            )
        if tuple(definition.skip_conditions) != gate.skip_conditions:
            raise WorkflowValidationError(
                f"resolved plan skip conditions for gate {gate_id!r} differ from workflow"
            )

    recomputed = digest_gate_definitions(plan.gates, plan.gate_definitions)
    if recomputed != plan.gate_definition_digest:
        raise WorkflowValidationError(
            "resolved plan gate-definition digest does not match its frozen policy"
        )
    active = tuple(workflow.gates[gate_id] for gate_id in plan.gates)
    return BoundWorkflow(
        definition=workflow,
        active_gates=active,
        gate_stage_ids=tuple(gate.stage for gate in active),
        gate_definition_digest=plan.gate_definition_digest,
    )
