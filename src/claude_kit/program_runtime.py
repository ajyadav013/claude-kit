"""Frozen, provider-neutral program manifests for program-scale execution.

This module deliberately stops at the planning trust boundary.  It loads and
validates a frozen Mode E manifest, but it does not dispatch workers, mutate a
pipeline ledger, create worktrees, or consume approvals.  Those effects belong
to the coordinator that integrates this contract with the workflow executor.

The manifest digest covers every field except the digest field itself.  JSON
and YAML therefore produce the same identity, and any edit after freezing is
detected before semantic validation or execution.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import stat
from collections import Counter
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Mapping, Optional, Sequence, TypeVar, Union, cast

import jsonschema
import yaml

PROGRAM_MANIFEST_SCHEMA_VERSION = 1
_MAX_MANIFEST_BYTES = 2 * 1024 * 1024
_MAX_SCHEMA_BYTES = 1024 * 1024


class ProgramManifestValidationError(ValueError):
    """Raised when a program manifest is unsafe, ambiguous, or inconsistent."""


class RiskTier(str, Enum):
    """Closed risk ordering used to sequence execution waves."""

    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    RESTRICTED = "restricted"


class BoundaryKind(str, Enum):
    """Whether an exact write boundary names one file or a complete subtree."""

    FILE = "file"
    TREE = "tree"


class ProgramWaveKind(str, Enum):
    """Closed lifecycle phases in a deterministic program plan."""

    AUDIT = "audit"
    EXECUTION = "execution"
    VERIFICATION = "verification"
    CLOSEOUT = "closeout"


class ProgramUnitKind(str, Enum):
    """Closed worker responsibilities inside program waves."""

    AUDIT = "audit"
    IMPLEMENTATION = "implementation"
    GATE_RUNNER = "gate-runner"
    KNOWLEDGE_CLOSEOUT = "knowledge-closeout"


class ProgramGateKind(str, Enum):
    """Whether a gate is local to the program or owned by the pipeline."""

    PROGRAM_WAVE = "program-wave"
    PIPELINE = "pipeline"


class BudgetExceedAction(str, Enum):
    """Fail-closed action when a wave exhausts any declared budget."""

    STOP_SPAWNING = "stop-spawning"
    CHECKPOINT_AND_ESCALATE = "checkpoint-and-escalate"


@dataclass(frozen=True)
class ProgramBoundary:
    """One canonical project-relative ownership boundary."""

    id: str
    kind: BoundaryKind
    path: PurePosixPath


@dataclass(frozen=True)
class ProgramLane:
    """One explicit lane and the boundaries and units assigned to it."""

    id: str
    boundary_ids: tuple[str, ...]
    unit_ids: tuple[str, ...]


@dataclass(frozen=True)
class ProgramBudget:
    """Hard, coordinator-enforced limits for one wave."""

    hard_spawn_cap: int
    max_attempts_per_unit: int
    max_turns_per_worker: int
    wall_clock_seconds: int
    token_ceiling: int
    on_exceed: BudgetExceedAction


@dataclass(frozen=True)
class ProgramInventoryReference:
    """Content-addressed dry-run inventory and its exact count contract."""

    artifact_id: str
    artifact_digest: str
    items_digest: str
    item_count: int
    expected_post_count: int


@dataclass(frozen=True)
class ProgramRestorePointReference:
    """Immutable git tag and content-addressed restore verification."""

    tag_ref: str
    commit: str
    verification_artifact_id: str
    verification_digest: str


@dataclass(frozen=True)
class ProgramApprovalReference:
    """Detached approval artifacts bound to one action, inventory, and restore point.

    This is a frozen reference only.  It does not attest that an approval broker
    has consumed the authorization or performed the external action.
    """

    request_artifact_id: str
    request_digest: str
    action_digest: str
    authorization_artifact_id: str
    authorization_digest: str
    inventory_artifact_digest: str
    restore_point_commit: str


@dataclass(frozen=True)
class ProgramWave:
    """One ordered audit, execution, verification, or closeout wave."""

    id: str
    order: int
    kind: ProgramWaveKind
    parallel: bool
    risk: RiskTier
    unit_ids: tuple[str, ...]
    gate_ids: tuple[str, ...]
    gate_wave_id: Optional[str]
    verifies_wave_id: Optional[str]
    budget: ProgramBudget


@dataclass(frozen=True)
class ProgramUnit:
    """One independently owned unit in the frozen plan."""

    id: str
    wave_id: str
    lane_id: str
    kind: ProgramUnitKind
    objective: str
    dependencies: tuple[str, ...]
    boundary_ids: tuple[str, ...]
    risk: RiskTier
    irreversible: bool
    inventory: Optional[ProgramInventoryReference]
    restore_point: Optional[ProgramRestorePointReference]
    approval: Optional[ProgramApprovalReference]
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class ProgramOwner:
    """Provider-neutral route that owns exactly one unit."""

    unit_id: str
    route: str


@dataclass(frozen=True)
class ProgramGate:
    """One ordered gate owned by a dedicated gate-runner unit."""

    id: str
    order: int
    kind: ProgramGateKind
    wave_id: str
    owner_unit_id: str
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class ProgramManifest:
    """Complete immutable program plan bound to workflow, gates, and selection."""

    schema_version: int
    program_id: str
    run_id: str
    objective: str
    source_commit: str
    workflow_definition_digest: str
    gate_definition_digest: str
    selection_digest: str
    revision: int
    parent_digest: Optional[str]
    frozen: bool
    pre_change_restore_point: ProgramRestorePointReference
    boundaries: tuple[ProgramBoundary, ...]
    lanes: tuple[ProgramLane, ...]
    waves: tuple[ProgramWave, ...]
    units: tuple[ProgramUnit, ...]
    owners: tuple[ProgramOwner, ...]
    gates: tuple[ProgramGate, ...]
    digest: str

    @property
    def pipeline_gate_ids(self) -> tuple[str, ...]:
        """Return pipeline-owned gates in their frozen execution order."""

        return tuple(
            gate.id for gate in self.gates if gate.kind is ProgramGateKind.PIPELINE
        )


@dataclass(frozen=True)
class ProgramManifestBinding:
    """Exact authoritative inputs a coordinator must persist with a manifest."""

    manifest_digest: str
    revision: int
    parent_digest: Optional[str]
    run_id: str
    source_commit: str
    workflow_definition_digest: str
    gate_definition_digest: str
    selection_digest: str
    pipeline_gate_ids: tuple[str, ...]


_RISK_ORDER = {
    RiskTier.NONE: 0,
    RiskTier.LOW: 1,
    RiskTier.MEDIUM: 2,
    RiskTier.HIGH: 3,
    RiskTier.RESTRICTED: 4,
}
_EnumT = TypeVar("_EnumT", bound=Enum)


class _DuplicateKeyError(ValueError):
    """Internal parser error promoted to ProgramManifestValidationError."""


class _UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys."""


def _construct_unique_mapping(
    loader: _UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False
) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in result
        except TypeError as exc:
            raise _DuplicateKeyError("mapping keys must be scalar values") from exc
        if duplicate:
            raise _DuplicateKeyError(f"duplicate key {key!r}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _construct_unique_json(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError(f"duplicate key {key!r}")
        result[key] = value
    return result


def _copy_json_value(value: Any, location: str = "manifest") -> Any:
    """Return a detached JSON value while rejecting lossy or ambiguous inputs."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ProgramManifestValidationError(
                f"{location} contains a non-finite number"
            )
        return value
    if isinstance(value, Mapping):
        copied: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ProgramManifestValidationError(
                    f"{location} contains a non-string mapping key"
                )
            copied[key] = _copy_json_value(item, f"{location}.{key}")
        return copied
    if isinstance(value, (list, tuple)):
        return [
            _copy_json_value(item, f"{location}[{index}]")
            for index, item in enumerate(value)
        ]
    raise ProgramManifestValidationError(
        f"{location} contains unsupported value type {type(value).__name__}"
    )


def program_manifest_digest(document: Mapping[str, Any]) -> str:
    """Return the SHA-256 identity of a manifest, excluding its digest field."""

    copied = _copy_json_value(document)
    if not isinstance(
        copied, dict
    ):  # Defensive for non-standard Mapping implementations.
        raise ProgramManifestValidationError("program manifest must be a mapping")
    copied.pop("digest", None)
    encoded = json.dumps(
        copied,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def seal_program_manifest(document: Mapping[str, Any]) -> dict[str, Any]:
    """Return a detached copy with a freshly calculated manifest digest."""

    copied = _copy_json_value(document)
    if not isinstance(copied, dict):
        raise ProgramManifestValidationError("program manifest must be a mapping")
    copied.pop("digest", None)
    copied["digest"] = program_manifest_digest(copied)
    return copied


def _read_regular_utf8(path: Path, *, maximum: int, label: str) -> str:
    """Read a stable, non-symlink regular file without following a final link."""

    try:
        before = path.lstat()
    except OSError as exc:
        raise ProgramManifestValidationError(
            f"cannot read {label} {path}: {exc}"
        ) from exc
    if not stat.S_ISREG(before.st_mode):
        raise ProgramManifestValidationError(f"{label} must be a regular file: {path}")
    if before.st_size > maximum:
        raise ProgramManifestValidationError(
            f"{label} exceeds the {maximum}-byte size limit: {path}"
        )

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ProgramManifestValidationError(
            f"cannot open {label} {path}: {exc}"
        ) from exc
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise ProgramManifestValidationError(
                f"{label} must be a regular file: {path}"
            )
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise ProgramManifestValidationError(
                f"{label} changed while opening: {path}"
            )
        chunks: list[bytes] = []
        consumed = 0
        while consumed <= maximum:
            chunk = os.read(descriptor, min(64 * 1024, maximum + 1 - consumed))
            if not chunk:
                break
            chunks.append(chunk)
            consumed += len(chunk)
        if consumed > maximum:
            raise ProgramManifestValidationError(
                f"{label} exceeds the {maximum}-byte size limit: {path}"
            )
        raw = b"".join(chunks)
    finally:
        os.close(descriptor)
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProgramManifestValidationError(f"{label} must be UTF-8: {path}") from exc


def _load_json(text: str, *, label: str) -> Any:
    try:
        return json.loads(text, object_pairs_hook=_construct_unique_json)
    except _DuplicateKeyError as exc:
        raise ProgramManifestValidationError(f"{label} has a {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ProgramManifestValidationError(f"{label} is invalid JSON: {exc}") from exc
    except RecursionError as exc:
        raise ProgramManifestValidationError(f"{label} is nested too deeply") from exc


def _load_manifest_document(path: Path) -> Mapping[str, Any]:
    text = _read_regular_utf8(
        path, maximum=_MAX_MANIFEST_BYTES, label="program manifest"
    )
    suffix = path.suffix.lower()
    if suffix == ".json":
        data = _load_json(text, label="program manifest")
    elif suffix in {".yaml", ".yml"}:
        try:
            if any(
                isinstance(event, yaml.events.AliasEvent) for event in yaml.parse(text)
            ):
                raise ProgramManifestValidationError(
                    "program manifest must not contain YAML aliases"
                )
            data = yaml.load(text, Loader=_UniqueKeyLoader)
        except _DuplicateKeyError as exc:
            raise ProgramManifestValidationError(
                f"program manifest has a {exc}"
            ) from exc
        except yaml.YAMLError as exc:
            raise ProgramManifestValidationError(
                f"program manifest is invalid YAML: {exc}"
            ) from exc
        except RecursionError as exc:
            raise ProgramManifestValidationError(
                "program manifest is nested too deeply"
            ) from exc
    else:
        raise ProgramManifestValidationError(
            "program manifest must use a .json, .yaml, or .yml suffix"
        )
    if not isinstance(data, Mapping):
        raise ProgramManifestValidationError("program manifest must be a mapping")
    return cast(Mapping[str, Any], data)


def _load_schema(path: Path) -> Mapping[str, Any]:
    text = _read_regular_utf8(path, maximum=_MAX_SCHEMA_BYTES, label="program schema")
    data = _load_json(text, label="program schema")
    if not isinstance(data, Mapping):
        raise ProgramManifestValidationError("program schema must be a mapping")
    schema = cast(Mapping[str, Any], data)
    try:
        jsonschema.Draft202012Validator.check_schema(schema)
    except jsonschema.SchemaError as exc:
        raise ProgramManifestValidationError(
            f"program schema is invalid: {exc}"
        ) from exc
    return schema


def _schema_location(error: jsonschema.ValidationError) -> str:
    parts = [str(part) for part in error.absolute_path]
    return ".".join(parts) if parts else "<root>"


def _validate_schema(document: Mapping[str, Any], schema: Mapping[str, Any]) -> None:
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(
        validator.iter_errors(document),
        key=lambda error: (
            tuple(str(part) for part in error.absolute_path),
            error.message,
        ),
    )
    if errors:
        error = errors[0]
        raise ProgramManifestValidationError(
            "program manifest schema validation failed at "
            f"{_schema_location(error)}: {error.message}"
        )


def _enum_value(enum_type: type[_EnumT], value: Any, location: str) -> _EnumT:
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise ProgramManifestValidationError(
            f"{location} has unsupported value {value!r}"
        ) from exc


def _as_mapping(value: Any, location: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProgramManifestValidationError(f"{location} must be a mapping")
    return cast(Mapping[str, Any], value)


def _as_sequence(value: Any, location: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ProgramManifestValidationError(f"{location} must be an array")
    return cast(Sequence[Any], value)


def _as_string_tuple(value: Any, location: str) -> tuple[str, ...]:
    items = _as_sequence(value, location)
    if any(not isinstance(item, str) for item in items):
        raise ProgramManifestValidationError(f"{location} must contain only strings")
    return tuple(cast(Sequence[str], items))


def _as_string(value: Any, location: str) -> str:
    if not isinstance(value, str):
        raise ProgramManifestValidationError(f"{location} must be a string")
    return value


def _as_integer(value: Any, location: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProgramManifestValidationError(f"{location} must be an integer")
    return value


def _as_boolean(value: Any, location: str) -> bool:
    if not isinstance(value, bool):
        raise ProgramManifestValidationError(f"{location} must be a boolean")
    return value


def _optional_string(value: Any, location: str) -> Optional[str]:
    if value is None:
        return None
    return _as_string(value, location)


def _boundary_path(value: Any, location: str) -> PurePosixPath:
    raw = _as_string(value, location)
    path = PurePosixPath(raw)
    if (
        raw != path.as_posix()
        or raw != raw.strip()
        or path.is_absolute()
        or PureWindowsPath(raw).drive
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ProgramManifestValidationError(
            f"{location} must be a canonical project-relative path"
        )
    return path


def _git_tag_ref(value: Any, location: str) -> str:
    raw = _as_string(value, location)
    prefix = "refs/tags/"
    suffix = raw.removeprefix(prefix)
    parts = suffix.split("/")
    if (
        not raw.startswith(prefix)
        or not suffix
        or len(raw) > 264
        or raw != raw.strip()
        or any(character.isspace() or ord(character) < 32 for character in raw)
        or any(character in "~^:?*[" for character in raw)
        or any(token in raw for token in ("..", "//", "@{", "\\"))
        or raw.endswith(("/", "."))
        or any(
            part in {"", ".", ".."}
            or part.startswith(".")
            or part.endswith((".", ".lock"))
            for part in parts
        )
    ):
        raise ProgramManifestValidationError(
            f"{location} must be a canonical full refs/tags/ git reference"
        )
    return raw


def _parse_budget(value: Any, location: str) -> ProgramBudget:
    data = _as_mapping(value, location)
    return ProgramBudget(
        hard_spawn_cap=_as_integer(
            data["hard_spawn_cap"], f"{location}.hard_spawn_cap"
        ),
        max_attempts_per_unit=_as_integer(
            data["max_attempts_per_unit"], f"{location}.max_attempts_per_unit"
        ),
        max_turns_per_worker=_as_integer(
            data["max_turns_per_worker"], f"{location}.max_turns_per_worker"
        ),
        wall_clock_seconds=_as_integer(
            data["wall_clock_seconds"], f"{location}.wall_clock_seconds"
        ),
        token_ceiling=_as_integer(data["token_ceiling"], f"{location}.token_ceiling"),
        on_exceed=_enum_value(
            BudgetExceedAction, data["on_exceed"], f"{location}.on_exceed"
        ),
    )


def _parse_inventory_reference(value: Any, location: str) -> ProgramInventoryReference:
    data = _as_mapping(value, location)
    return ProgramInventoryReference(
        artifact_id=_as_string(data["artifact_id"], f"{location}.artifact_id"),
        artifact_digest=_as_string(
            data["artifact_digest"], f"{location}.artifact_digest"
        ),
        items_digest=_as_string(data["items_digest"], f"{location}.items_digest"),
        item_count=_as_integer(data["item_count"], f"{location}.item_count"),
        expected_post_count=_as_integer(
            data["expected_post_count"], f"{location}.expected_post_count"
        ),
    )


def _parse_restore_point_reference(
    value: Any, location: str
) -> ProgramRestorePointReference:
    data = _as_mapping(value, location)
    return ProgramRestorePointReference(
        tag_ref=_git_tag_ref(data["tag_ref"], f"{location}.tag_ref"),
        commit=_as_string(data["commit"], f"{location}.commit"),
        verification_artifact_id=_as_string(
            data["verification_artifact_id"],
            f"{location}.verification_artifact_id",
        ),
        verification_digest=_as_string(
            data["verification_digest"], f"{location}.verification_digest"
        ),
    )


def _parse_approval_reference(value: Any, location: str) -> ProgramApprovalReference:
    data = _as_mapping(value, location)
    return ProgramApprovalReference(
        request_artifact_id=_as_string(
            data["request_artifact_id"], f"{location}.request_artifact_id"
        ),
        request_digest=_as_string(data["request_digest"], f"{location}.request_digest"),
        action_digest=_as_string(data["action_digest"], f"{location}.action_digest"),
        authorization_artifact_id=_as_string(
            data["authorization_artifact_id"],
            f"{location}.authorization_artifact_id",
        ),
        authorization_digest=_as_string(
            data["authorization_digest"], f"{location}.authorization_digest"
        ),
        inventory_artifact_digest=_as_string(
            data["inventory_artifact_digest"],
            f"{location}.inventory_artifact_digest",
        ),
        restore_point_commit=_as_string(
            data["restore_point_commit"], f"{location}.restore_point_commit"
        ),
    )


def _optional_inventory_reference(
    value: Any, location: str
) -> Optional[ProgramInventoryReference]:
    if value is None:
        return None
    return _parse_inventory_reference(value, location)


def _optional_restore_point_reference(
    value: Any, location: str
) -> Optional[ProgramRestorePointReference]:
    if value is None:
        return None
    return _parse_restore_point_reference(value, location)


def _optional_approval_reference(
    value: Any, location: str
) -> Optional[ProgramApprovalReference]:
    if value is None:
        return None
    return _parse_approval_reference(value, location)


def _parse_manifest(document: Mapping[str, Any]) -> ProgramManifest:
    boundaries: list[ProgramBoundary] = []
    for index, value in enumerate(_as_sequence(document["boundaries"], "boundaries")):
        location = f"boundaries[{index}]"
        data = _as_mapping(value, location)
        boundaries.append(
            ProgramBoundary(
                id=_as_string(data["id"], f"{location}.id"),
                kind=_enum_value(BoundaryKind, data["kind"], f"{location}.kind"),
                path=_boundary_path(data["path"], f"{location}.path"),
            )
        )

    lanes: list[ProgramLane] = []
    for index, value in enumerate(_as_sequence(document["lanes"], "lanes")):
        location = f"lanes[{index}]"
        data = _as_mapping(value, location)
        lanes.append(
            ProgramLane(
                id=_as_string(data["id"], f"{location}.id"),
                boundary_ids=_as_string_tuple(
                    data["boundary_ids"], f"{location}.boundary_ids"
                ),
                unit_ids=_as_string_tuple(data["unit_ids"], f"{location}.unit_ids"),
            )
        )

    waves: list[ProgramWave] = []
    for index, value in enumerate(_as_sequence(document["waves"], "waves")):
        location = f"waves[{index}]"
        data = _as_mapping(value, location)
        waves.append(
            ProgramWave(
                id=_as_string(data["id"], f"{location}.id"),
                order=_as_integer(data["order"], f"{location}.order"),
                kind=_enum_value(ProgramWaveKind, data["kind"], f"{location}.kind"),
                parallel=_as_boolean(data["parallel"], f"{location}.parallel"),
                risk=_enum_value(RiskTier, data["risk"], f"{location}.risk"),
                unit_ids=_as_string_tuple(data["unit_ids"], f"{location}.unit_ids"),
                gate_ids=_as_string_tuple(data["gate_ids"], f"{location}.gate_ids"),
                gate_wave_id=_optional_string(
                    data["gate_wave_id"], f"{location}.gate_wave_id"
                ),
                verifies_wave_id=_optional_string(
                    data["verifies_wave_id"], f"{location}.verifies_wave_id"
                ),
                budget=_parse_budget(data["budget"], f"{location}.budget"),
            )
        )

    units: list[ProgramUnit] = []
    for index, value in enumerate(_as_sequence(document["units"], "units")):
        location = f"units[{index}]"
        data = _as_mapping(value, location)
        units.append(
            ProgramUnit(
                id=_as_string(data["id"], f"{location}.id"),
                wave_id=_as_string(data["wave_id"], f"{location}.wave_id"),
                lane_id=_as_string(data["lane_id"], f"{location}.lane_id"),
                kind=_enum_value(ProgramUnitKind, data["kind"], f"{location}.kind"),
                objective=_as_string(data["objective"], f"{location}.objective"),
                dependencies=_as_string_tuple(
                    data["dependencies"], f"{location}.dependencies"
                ),
                boundary_ids=_as_string_tuple(
                    data["boundary_ids"], f"{location}.boundary_ids"
                ),
                risk=_enum_value(RiskTier, data["risk"], f"{location}.risk"),
                irreversible=_as_boolean(
                    data["irreversible"], f"{location}.irreversible"
                ),
                inventory=_optional_inventory_reference(
                    data["inventory"], f"{location}.inventory"
                ),
                restore_point=_optional_restore_point_reference(
                    data["restore_point"], f"{location}.restore_point"
                ),
                approval=_optional_approval_reference(
                    data["approval"], f"{location}.approval"
                ),
                evidence=_as_string_tuple(data["evidence"], f"{location}.evidence"),
            )
        )

    owners: list[ProgramOwner] = []
    for index, value in enumerate(_as_sequence(document["owners"], "owners")):
        location = f"owners[{index}]"
        data = _as_mapping(value, location)
        owners.append(
            ProgramOwner(
                unit_id=_as_string(data["unit_id"], f"{location}.unit_id"),
                route=_as_string(data["route"], f"{location}.route"),
            )
        )

    gates: list[ProgramGate] = []
    for index, value in enumerate(_as_sequence(document["gates"], "gates")):
        location = f"gates[{index}]"
        data = _as_mapping(value, location)
        gates.append(
            ProgramGate(
                id=_as_string(data["id"], f"{location}.id"),
                order=_as_integer(data["order"], f"{location}.order"),
                kind=_enum_value(ProgramGateKind, data["kind"], f"{location}.kind"),
                wave_id=_as_string(data["wave_id"], f"{location}.wave_id"),
                owner_unit_id=_as_string(
                    data["owner_unit_id"], f"{location}.owner_unit_id"
                ),
                evidence=_as_string_tuple(data["evidence"], f"{location}.evidence"),
            )
        )

    return ProgramManifest(
        schema_version=_as_integer(document["schema_version"], "schema_version"),
        program_id=_as_string(document["program_id"], "program_id"),
        run_id=_as_string(document["run_id"], "run_id"),
        objective=_as_string(document["objective"], "objective"),
        source_commit=_as_string(document["source_commit"], "source_commit"),
        workflow_definition_digest=_as_string(
            document["workflow_definition_digest"], "workflow_definition_digest"
        ),
        gate_definition_digest=_as_string(
            document["gate_definition_digest"], "gate_definition_digest"
        ),
        selection_digest=_as_string(document["selection_digest"], "selection_digest"),
        revision=_as_integer(document["revision"], "revision"),
        parent_digest=_optional_string(document["parent_digest"], "parent_digest"),
        frozen=_as_boolean(document["frozen"], "frozen"),
        pre_change_restore_point=_parse_restore_point_reference(
            document["pre_change_restore_point"], "pre_change_restore_point"
        ),
        boundaries=tuple(boundaries),
        lanes=tuple(lanes),
        waves=tuple(waves),
        units=tuple(units),
        owners=tuple(owners),
        gates=tuple(gates),
        digest=_as_string(document["digest"], "digest"),
    )


def _require_unique(values: Sequence[str], label: str) -> None:
    if len(values) != len(set(values)):
        raise ProgramManifestValidationError(f"{label} ids must be unique")


def _is_canonical_boundary(boundary: ProgramBoundary) -> bool:
    rendered = boundary.path.as_posix()
    parts = boundary.path.parts
    return (
        bool(rendered)
        and not boundary.path.is_absolute()
        and not PureWindowsPath(rendered).drive
        and rendered not in {".", ".."}
        and rendered == rendered.strip()
        and not rendered.endswith("/")
        and "\\" not in rendered
        and all(part not in {"", ".", ".."} for part in parts)
    )


def _boundaries_overlap(left: ProgramBoundary, right: ProgramBoundary) -> bool:
    left_parts = left.path.parts
    right_parts = right.path.parts
    shorter = min(len(left_parts), len(right_parts))
    return left_parts[:shorter] == right_parts[:shorter]


def _validate_identifiers_and_order(manifest: ProgramManifest) -> None:
    _require_unique(tuple(boundary.id for boundary in manifest.boundaries), "boundary")
    _require_unique(tuple(lane.id for lane in manifest.lanes), "lane")
    _require_unique(tuple(wave.id for wave in manifest.waves), "wave")
    _require_unique(tuple(unit.id for unit in manifest.units), "unit")
    _require_unique(tuple(owner.unit_id for owner in manifest.owners), "owner unit")
    _require_unique(tuple(gate.id for gate in manifest.gates), "gate")

    if tuple(wave.order for wave in manifest.waves) != tuple(
        range(len(manifest.waves))
    ):
        raise ProgramManifestValidationError(
            "wave order must be contiguous and match manifest declaration order"
        )
    if tuple(gate.order for gate in manifest.gates) != tuple(
        range(len(manifest.gates))
    ):
        raise ProgramManifestValidationError(
            "gate order must be contiguous and match manifest declaration order"
        )
    if manifest.revision == 1 and manifest.parent_digest is not None:
        raise ProgramManifestValidationError(
            "revision 1 must not declare a parent digest"
        )
    if manifest.revision > 1 and manifest.parent_digest is None:
        raise ProgramManifestValidationError(
            "revisions after 1 must declare a parent digest"
        )


def _validate_boundaries(manifest: ProgramManifest) -> None:
    boundary_by_id = {boundary.id: boundary for boundary in manifest.boundaries}
    assignments: Counter[str] = Counter()
    for lane in manifest.lanes:
        for boundary_id in lane.boundary_ids:
            if boundary_id not in boundary_by_id:
                raise ProgramManifestValidationError(
                    f"lane {lane.id!r} references unknown boundary {boundary_id!r}"
                )
            assignments[boundary_id] += 1
    if assignments != Counter({boundary.id: 1 for boundary in manifest.boundaries}):
        raise ProgramManifestValidationError(
            "every exact boundary must be assigned to exactly one lane"
        )

    for boundary in manifest.boundaries:
        if not _is_canonical_boundary(boundary):
            raise ProgramManifestValidationError(
                f"boundary {boundary.id!r} must be a canonical project-relative path"
            )
    for index, left in enumerate(manifest.boundaries):
        for right in manifest.boundaries[index + 1 :]:
            if _boundaries_overlap(left, right):
                raise ProgramManifestValidationError(
                    "program has overlapping boundaries: "
                    f"{left.id!r} ({left.path}) and {right.id!r} ({right.path})"
                )


def _validate_assignments_and_dependencies(manifest: ProgramManifest) -> None:
    wave_by_id = {wave.id: wave for wave in manifest.waves}
    lane_by_id = {lane.id: lane for lane in manifest.lanes}
    boundary_ids = {boundary.id for boundary in manifest.boundaries}
    unit_by_id = {unit.id: unit for unit in manifest.units}
    unit_position = {unit.id: index for index, unit in enumerate(manifest.units)}

    wave_assignments = Counter(
        unit_id for wave in manifest.waves for unit_id in wave.unit_ids
    )
    lane_assignments = Counter(
        unit_id for lane in manifest.lanes for unit_id in lane.unit_ids
    )
    expected_assignments = Counter({unit.id: 1 for unit in manifest.units})
    if wave_assignments != expected_assignments:
        raise ProgramManifestValidationError(
            "every unit must appear exactly once in wave unit_ids"
        )
    if lane_assignments != expected_assignments:
        raise ProgramManifestValidationError(
            "every unit must appear exactly once in lane unit_ids"
        )

    declared_unit_order = tuple(unit.id for unit in manifest.units)
    wave_unit_order = tuple(
        unit_id for wave in manifest.waves for unit_id in wave.unit_ids
    )
    if wave_unit_order != declared_unit_order:
        raise ProgramManifestValidationError(
            "unit declaration order must match deterministic wave order"
        )
    for declared_lane in manifest.lanes:
        expected_lane_order = tuple(
            unit.id for unit in manifest.units if unit.lane_id == declared_lane.id
        )
        if declared_lane.unit_ids != expected_lane_order:
            raise ProgramManifestValidationError(
                f"lane {declared_lane.id!r} unit_ids do not match deterministic unit order"
            )

    for unit in manifest.units:
        wave = wave_by_id.get(unit.wave_id)
        if wave is None:
            raise ProgramManifestValidationError(
                f"unit {unit.id!r} references unknown wave {unit.wave_id!r}"
            )
        lane = lane_by_id.get(unit.lane_id)
        if lane is None:
            raise ProgramManifestValidationError(
                f"unit {unit.id!r} references unknown lane {unit.lane_id!r}"
            )
        if unit.id not in wave.unit_ids:
            raise ProgramManifestValidationError(
                f"unit {unit.id!r} is not declared by its wave {wave.id!r}"
            )
        if unit.id not in lane.unit_ids:
            raise ProgramManifestValidationError(
                f"unit {unit.id!r} is not declared by its lane {lane.id!r}"
            )
        if not set(unit.boundary_ids).issubset(lane.boundary_ids):
            raise ProgramManifestValidationError(
                f"unit {unit.id!r} crosses its lane's exact boundaries"
            )
        unknown_boundaries = set(unit.boundary_ids) - boundary_ids
        if unknown_boundaries:
            raise ProgramManifestValidationError(
                f"unit {unit.id!r} references unknown boundaries "
                f"{sorted(unknown_boundaries)!r}"
            )

        dependency_positions: list[int] = []
        for dependency_id in unit.dependencies:
            dependency = unit_by_id.get(dependency_id)
            if dependency is None:
                raise ProgramManifestValidationError(
                    f"unit {unit.id!r} references unknown dependency {dependency_id!r}"
                )
            dependency_wave = wave_by_id[dependency.wave_id]
            if dependency_wave.order >= wave.order:
                raise ProgramManifestValidationError(
                    f"unit {unit.id!r} dependencies must come from earlier waves"
                )
            dependency_positions.append(unit_position[dependency_id])
        if dependency_positions != sorted(dependency_positions):
            raise ProgramManifestValidationError(
                f"unit {unit.id!r} dependencies must follow deterministic unit order"
            )

    owner_order = tuple(owner.unit_id for owner in manifest.owners)
    if owner_order != declared_unit_order:
        raise ProgramManifestValidationError(
            "owners must cover units exactly once in deterministic unit order"
        )


def _validate_wave_structure(manifest: ProgramManifest) -> None:
    unit_by_id = {unit.id: unit for unit in manifest.units}
    boundary_by_id = {boundary.id: boundary for boundary in manifest.boundaries}
    expected_kinds = {
        ProgramWaveKind.AUDIT: ProgramUnitKind.AUDIT,
        ProgramWaveKind.EXECUTION: ProgramUnitKind.IMPLEMENTATION,
        ProgramWaveKind.VERIFICATION: ProgramUnitKind.GATE_RUNNER,
        ProgramWaveKind.CLOSEOUT: ProgramUnitKind.KNOWLEDGE_CLOSEOUT,
    }

    if manifest.waves[0].kind is not ProgramWaveKind.AUDIT:
        raise ProgramManifestValidationError("wave 0 must be the read-only audit wave")
    if not manifest.waves[0].parallel:
        raise ProgramManifestValidationError("wave 0 audits must be parallel")
    if sum(wave.kind is ProgramWaveKind.AUDIT for wave in manifest.waves) != 1:
        raise ProgramManifestValidationError("program must have exactly one audit wave")
    if manifest.waves[-1].kind is not ProgramWaveKind.CLOSEOUT:
        raise ProgramManifestValidationError("final wave must be knowledge closeout")
    if sum(wave.kind is ProgramWaveKind.CLOSEOUT for wave in manifest.waves) != 1:
        raise ProgramManifestValidationError(
            "program must have exactly one closeout wave"
        )
    if manifest.waves[-1].parallel:
        raise ProgramManifestValidationError("knowledge closeout must not be parallel")
    if len(manifest.waves[-1].unit_ids) != 1:
        raise ProgramManifestValidationError(
            "knowledge closeout must have exactly one dedicated unit"
        )

    for index, wave in enumerate(manifest.waves):
        units = tuple(unit_by_id[unit_id] for unit_id in wave.unit_ids)
        if wave.budget.hard_spawn_cap < len(units):
            raise ProgramManifestValidationError(
                f"wave {wave.id!r} spawn cap cannot launch every declared unit"
            )
        expected_kind = expected_kinds[wave.kind]
        if any(unit.kind is not expected_kind for unit in units):
            raise ProgramManifestValidationError(
                f"wave {wave.id!r} may contain only {expected_kind.value} units"
            )
        for unit in units:
            if unit.kind is ProgramUnitKind.GATE_RUNNER and unit.boundary_ids:
                raise ProgramManifestValidationError(
                    f"gate-runner {unit.id!r} cannot own write boundaries"
                )
            if unit.kind is not ProgramUnitKind.GATE_RUNNER and not unit.boundary_ids:
                raise ProgramManifestValidationError(
                    f"unit {unit.id!r} must declare an exact boundary"
                )
        if wave.kind is ProgramWaveKind.AUDIT and any(
            unit.dependencies for unit in units
        ):
            raise ProgramManifestValidationError(
                "audit units must not have dependencies"
            )

        if wave.kind in {ProgramWaveKind.AUDIT, ProgramWaveKind.EXECUTION}:
            if index + 1 >= len(manifest.waves):
                raise ProgramManifestValidationError(
                    f"{wave.kind.value} wave {wave.id!r} has no immediate verification wave"
                )
            verification = manifest.waves[index + 1]
            if (
                verification.kind is not ProgramWaveKind.VERIFICATION
                or wave.gate_wave_id != verification.id
                or verification.verifies_wave_id != wave.id
            ):
                raise ProgramManifestValidationError(
                    f"{wave.kind.value} wave {wave.id!r} must bind its immediate "
                    "verification wave"
                )
            if wave.verifies_wave_id is not None or wave.gate_ids:
                raise ProgramManifestValidationError(
                    f"{wave.kind.value} wave {wave.id!r} cannot verify or own gates"
                )
            if wave.kind is ProgramWaveKind.EXECUTION:
                if (
                    index == 0
                    or manifest.waves[index - 1].kind
                    is not ProgramWaveKind.VERIFICATION
                ):
                    raise ProgramManifestValidationError(
                        f"execution wave {wave.id!r} must follow a completed "
                        "verification gate"
                    )
                preceding_gate_units = set(manifest.waves[index - 1].unit_ids)
                if any(
                    not preceding_gate_units.issubset(unit.dependencies)
                    for unit in units
                ):
                    raise ProgramManifestValidationError(
                        f"every unit in execution wave {wave.id!r} must depend on "
                        "all preceding verification gate-runners"
                    )
        elif wave.kind is ProgramWaveKind.VERIFICATION:
            if index == 0 or manifest.waves[index - 1].kind not in {
                ProgramWaveKind.AUDIT,
                ProgramWaveKind.EXECUTION,
            }:
                raise ProgramManifestValidationError(
                    f"verification wave {wave.id!r} must immediately follow "
                    "an audit or execution wave"
                )
            verified = manifest.waves[index - 1]
            if (
                wave.verifies_wave_id != verified.id
                or verified.gate_wave_id != wave.id
                or wave.gate_wave_id is not None
                or not wave.gate_ids
            ):
                raise ProgramManifestValidationError(
                    f"verification wave {wave.id!r} must own at least one gate "
                    "and bind the immediately preceding work wave"
                )
        elif (
            wave.gate_wave_id is not None
            or wave.verifies_wave_id is not None
            or wave.gate_ids
        ):
            raise ProgramManifestValidationError(
                f"{wave.kind.value} wave {wave.id!r} cannot own gate-wave links"
            )

        if wave.parallel:
            for unit_index, left in enumerate(units):
                for right in units[unit_index + 1 :]:
                    for left_boundary_id in left.boundary_ids:
                        for right_boundary_id in right.boundary_ids:
                            if _boundaries_overlap(
                                boundary_by_id[left_boundary_id],
                                boundary_by_id[right_boundary_id],
                            ):
                                raise ProgramManifestValidationError(
                                    "parallel wave has overlapping boundaries: "
                                    f"{left.id!r} and {right.id!r}"
                                )

    closeout = unit_by_id[manifest.waves[-1].unit_ids[0]]
    for boundary_id in closeout.boundary_ids:
        boundary = boundary_by_id[boundary_id]
        if not boundary.path.parts or boundary.path.parts[0] != "docs":
            raise ProgramManifestValidationError(
                "knowledge closeout boundaries must remain under docs/; application, "
                "configuration, and control-plane paths require a later verification gate"
            )
    preceding_units = set(manifest.waves[-2].unit_ids)
    if not preceding_units.issubset(closeout.dependencies):
        raise ProgramManifestValidationError(
            "knowledge closeout must depend on all units in the final verification wave"
        )


def _validate_risk_and_safeguards(manifest: ProgramManifest) -> None:
    unit_by_id = {unit.id: unit for unit in manifest.units}
    wave_by_id = {wave.id: wave for wave in manifest.waves}
    execution_waves = tuple(
        wave for wave in manifest.waves if wave.kind is ProgramWaveKind.EXECUTION
    )
    if not execution_waves:
        raise ProgramManifestValidationError("program must contain an execution wave")
    if manifest.pre_change_restore_point.commit != manifest.source_commit:
        raise ProgramManifestValidationError(
            "the pre-change restore point must bind the manifest source commit"
        )

    artifact_digests = {
        manifest.pre_change_restore_point.verification_artifact_id: manifest.pre_change_restore_point.verification_digest
    }

    def bind_artifact(artifact_id: str, digest: str) -> None:
        existing = artifact_digests.setdefault(artifact_id, digest)
        if not hmac.compare_digest(existing, digest):
            raise ProgramManifestValidationError(
                f"artifact {artifact_id!r} is bound to conflicting content digests"
            )

    for wave in manifest.waves:
        units = tuple(unit_by_id[unit_id] for unit_id in wave.unit_ids)
        expected_risk = max((unit.risk for unit in units), key=_RISK_ORDER.__getitem__)
        if wave.risk is not expected_risk:
            raise ProgramManifestValidationError(
                f"wave risk must equal the maximum unit risk for wave {wave.id!r}"
            )

    execution_risks = [_RISK_ORDER[wave.risk] for wave in execution_waves]
    if execution_risks != sorted(execution_risks):
        raise ProgramManifestValidationError(
            "execution wave risk order must be non-decreasing"
        )

    final_execution_id = execution_waves[-1].id
    for unit in manifest.units:
        safeguard_evidence: set[str] = set()
        if unit.inventory is not None:
            bind_artifact(unit.inventory.artifact_id, unit.inventory.artifact_digest)
            safeguard_evidence.add(unit.inventory.artifact_id)
        if unit.restore_point is not None:
            bind_artifact(
                unit.restore_point.verification_artifact_id,
                unit.restore_point.verification_digest,
            )
            safeguard_evidence.add(unit.restore_point.verification_artifact_id)
        if unit.approval is not None:
            bind_artifact(
                unit.approval.request_artifact_id, unit.approval.request_digest
            )
            bind_artifact(
                unit.approval.authorization_artifact_id,
                unit.approval.authorization_digest,
            )
            safeguard_evidence.update(
                (
                    unit.approval.request_artifact_id,
                    unit.approval.authorization_artifact_id,
                )
            )
            if unit.inventory is None or unit.restore_point is None:
                raise ProgramManifestValidationError(
                    f"unit {unit.id!r} approval must bind an inventory and restore point"
                )
            if not hmac.compare_digest(
                unit.approval.inventory_artifact_digest,
                unit.inventory.artifact_digest,
            ):
                raise ProgramManifestValidationError(
                    f"unit {unit.id!r} approval does not bind its exact inventory"
                )
            if not hmac.compare_digest(
                unit.approval.restore_point_commit,
                unit.restore_point.commit,
            ):
                raise ProgramManifestValidationError(
                    f"unit {unit.id!r} approval does not bind its exact restore point"
                )
            if (
                unit.approval.request_artifact_id
                == unit.approval.authorization_artifact_id
            ):
                raise ProgramManifestValidationError(
                    f"unit {unit.id!r} approval request and authorization artifacts "
                    "must be distinct"
                )
        if not safeguard_evidence.issubset(unit.evidence):
            raise ProgramManifestValidationError(
                f"unit {unit.id!r} must declare every safeguard artifact as evidence"
            )

        if not unit.irreversible:
            continue
        if unit.kind is not ProgramUnitKind.IMPLEMENTATION:
            raise ProgramManifestValidationError(
                f"irreversible unit {unit.id!r} must be an implementation unit"
            )
        if unit.risk is not RiskTier.RESTRICTED or any(
            reference is None
            for reference in (unit.inventory, unit.restore_point, unit.approval)
        ):
            raise ProgramManifestValidationError(
                "irreversible units require restricted risk plus exact "
                "content-addressed inventory, restore point, and approval bindings"
            )
        if unit.wave_id != final_execution_id:
            raise ProgramManifestValidationError(
                "irreversible units must be confined to the final execution wave"
            )

    for wave in manifest.waves:
        if wave.kind is ProgramWaveKind.VERIFICATION:
            verified = wave_by_id[cast(str, wave.verifies_wave_id)]
            if wave.risk is not verified.risk:
                raise ProgramManifestValidationError(
                    f"verification wave {wave.id!r} must retain work-wave risk"
                )


def _validate_gates(manifest: ProgramManifest) -> None:
    wave_by_id = {wave.id: wave for wave in manifest.waves}
    unit_by_id = {unit.id: unit for unit in manifest.units}
    gate_by_id = {gate.id: gate for gate in manifest.gates}

    gate_wave_orders: list[int] = []
    for gate in manifest.gates:
        wave = wave_by_id.get(gate.wave_id)
        owner = unit_by_id.get(gate.owner_unit_id)
        if wave is None:
            raise ProgramManifestValidationError(
                f"gate {gate.id!r} references unknown wave {gate.wave_id!r}"
            )
        if wave.kind is not ProgramWaveKind.VERIFICATION:
            raise ProgramManifestValidationError(
                f"gate {gate.id!r} must belong to a verification wave"
            )
        if (
            owner is None
            or owner.kind is not ProgramUnitKind.GATE_RUNNER
            or owner.wave_id != wave.id
            or owner.id not in wave.unit_ids
        ):
            raise ProgramManifestValidationError(
                f"gate {gate.id!r} must be owned by a gate-runner in its wave"
            )
        if not set(gate.evidence).issubset(owner.evidence):
            raise ProgramManifestValidationError(
                f"gate-runner {owner.id!r} does not declare all gate evidence"
            )
        work_wave = wave_by_id[cast(str, wave.verifies_wave_id)]
        if not set(work_wave.unit_ids).issubset(owner.dependencies):
            raise ProgramManifestValidationError(
                f"gate-runner {owner.id!r} must depend on all units in work wave "
                f"{work_wave.id!r}"
            )
        gate_wave_orders.append(wave.order)
    if gate_wave_orders != sorted(gate_wave_orders):
        raise ProgramManifestValidationError(
            "gate order must follow deterministic verification wave order"
        )

    for wave in manifest.waves:
        expected_gate_ids = tuple(
            gate.id for gate in manifest.gates if gate.wave_id == wave.id
        )
        if wave.gate_ids != expected_gate_ids:
            raise ProgramManifestValidationError(
                f"wave {wave.id!r} gate_ids do not match ordered gate ownership"
            )
        if wave.kind is ProgramWaveKind.VERIFICATION:
            if not any(
                gate_by_id[gate_id].kind is ProgramGateKind.PROGRAM_WAVE
                for gate_id in wave.gate_ids
            ):
                raise ProgramManifestValidationError(
                    f"verification wave {wave.id!r} requires a program-wave gate"
                )
            owner_ids = {gate_by_id[gate_id].owner_unit_id for gate_id in wave.gate_ids}
            if owner_ids != set(wave.unit_ids):
                raise ProgramManifestValidationError(
                    f"every gate-runner in wave {wave.id!r} must own a gate"
                )
            owner_order = tuple(
                dict.fromkeys(
                    gate_by_id[gate_id].owner_unit_id for gate_id in wave.gate_ids
                )
            )
            if owner_order != wave.unit_ids:
                raise ProgramManifestValidationError(
                    f"verification wave {wave.id!r} gate owners must follow its "
                    "deterministic unit order"
                )

    audit_wave = manifest.waves[0]
    audit_verification = wave_by_id[cast(str, audit_wave.gate_wave_id)]
    audit_evidence = {
        evidence
        for gate_id in audit_verification.gate_ids
        if gate_by_id[gate_id].kind is ProgramGateKind.PROGRAM_WAVE
        for evidence in gate_by_id[gate_id].evidence
    }
    required_audit_evidence = {
        "frozen-manifest",
        manifest.pre_change_restore_point.verification_artifact_id,
    }
    if not required_audit_evidence.issubset(audit_evidence):
        raise ProgramManifestValidationError(
            "the Wave 0 program gate must verify the frozen manifest and concrete "
            "pre-change restore point before execution"
        )


def _validate_program_manifest(manifest: ProgramManifest) -> None:
    _validate_identifiers_and_order(manifest)
    _validate_boundaries(manifest)
    _validate_assignments_and_dependencies(manifest)
    _validate_wave_structure(manifest)
    _validate_risk_and_safeguards(manifest)
    _validate_gates(manifest)


def load_program_manifest(
    path: Union[str, Path], *, schema_path: Union[str, Path]
) -> ProgramManifest:
    """Load, verify, type, and semantically validate a frozen manifest."""

    document = _load_manifest_document(Path(path))
    schema = _load_schema(Path(schema_path))
    _validate_schema(document, schema)

    declared_digest = document.get("digest")
    expected_digest = program_manifest_digest(document)
    if not isinstance(declared_digest, str) or not hmac.compare_digest(
        declared_digest, expected_digest
    ):
        raise ProgramManifestValidationError(
            "program manifest digest does not match its frozen content"
        )

    manifest = _parse_manifest(document)
    _validate_program_manifest(manifest)
    return manifest


def validate_program_manifest_for_gates(
    manifest: ProgramManifest, ordered_gates: Sequence[str]
) -> tuple[str, ...]:
    """Bind a manifest to the pipeline's exact active gate order.

    Program-only gates remain authoritative within verification waves; only
    ``pipeline`` gates participate in this external binding.
    """

    if (
        isinstance(ordered_gates, (str, bytes))
        or not isinstance(ordered_gates, Sequence)
        or any(not isinstance(gate, str) for gate in ordered_gates)
    ):
        raise ProgramManifestValidationError(
            "pipeline gate order must be a sequence of gate identifiers"
        )
    supplied = tuple(ordered_gates)
    if supplied != manifest.pipeline_gate_ids:
        raise ProgramManifestValidationError(
            "pipeline gate order does not exactly match the frozen program manifest"
        )
    return supplied


def validate_program_manifest_binding(
    manifest: ProgramManifest,
    *,
    run_id: str,
    source_commit: str,
    workflow_definition_digest: str,
    gate_definition_digest: str,
    selection_digest: str,
    ordered_gates: Sequence[str],
    expected_revision: int,
    previous_manifest_digest: Optional[str],
) -> ProgramManifestBinding:
    """Validate all authoritative run inputs and return their persistence record.

    The caller must persist the returned binding atomically with its run ledger;
    this pure function intentionally performs no I/O and does not make Mode E
    executable by itself.
    """

    supplied_values = {
        "run id": run_id,
        "source commit": source_commit,
        "workflow definition digest": workflow_definition_digest,
        "gate definition digest": gate_definition_digest,
        "selection digest": selection_digest,
    }
    manifest_values = {
        "run id": manifest.run_id,
        "source commit": manifest.source_commit,
        "workflow definition digest": manifest.workflow_definition_digest,
        "gate definition digest": manifest.gate_definition_digest,
        "selection digest": manifest.selection_digest,
    }
    for label, supplied in supplied_values.items():
        if not isinstance(supplied, str) or not hmac.compare_digest(
            supplied, manifest_values[label]
        ):
            raise ProgramManifestValidationError(
                f"authoritative {label} does not match the frozen program manifest"
            )

    if (
        isinstance(expected_revision, bool)
        or not isinstance(expected_revision, int)
        or expected_revision != manifest.revision
    ):
        raise ProgramManifestValidationError(
            "authoritative revision does not match the frozen program manifest"
        )
    if manifest.revision == 1:
        if previous_manifest_digest is not None:
            raise ProgramManifestValidationError(
                "revision 1 cannot bind a previous program manifest"
            )
    elif (
        not isinstance(previous_manifest_digest, str)
        or manifest.parent_digest is None
        or not hmac.compare_digest(previous_manifest_digest, manifest.parent_digest)
    ):
        raise ProgramManifestValidationError(
            "previous program manifest digest does not match the frozen revision parent"
        )

    pipeline_gate_ids = validate_program_manifest_for_gates(manifest, ordered_gates)
    return ProgramManifestBinding(
        manifest_digest=manifest.digest,
        revision=manifest.revision,
        parent_digest=manifest.parent_digest,
        run_id=manifest.run_id,
        source_commit=manifest.source_commit,
        workflow_definition_digest=manifest.workflow_definition_digest,
        gate_definition_digest=manifest.gate_definition_digest,
        selection_digest=manifest.selection_digest,
        pipeline_gate_ids=pipeline_gate_ids,
    )


__all__ = [
    "BoundaryKind",
    "BudgetExceedAction",
    "PROGRAM_MANIFEST_SCHEMA_VERSION",
    "ProgramBoundary",
    "ProgramBudget",
    "ProgramApprovalReference",
    "ProgramGate",
    "ProgramGateKind",
    "ProgramInventoryReference",
    "ProgramLane",
    "ProgramManifest",
    "ProgramManifestBinding",
    "ProgramManifestValidationError",
    "ProgramOwner",
    "ProgramRestorePointReference",
    "ProgramUnit",
    "ProgramUnitKind",
    "ProgramWave",
    "ProgramWaveKind",
    "RiskTier",
    "load_program_manifest",
    "program_manifest_digest",
    "seal_program_manifest",
    "validate_program_manifest_binding",
    "validate_program_manifest_for_gates",
]
