"""Typed, provider-neutral program manifest contract tests."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any, Callable

import pytest
import yaml

from claude_kit.program_runtime import (
    BoundaryKind,
    ProgramApprovalReference,
    ProgramInventoryReference,
    ProgramManifest,
    ProgramManifestBinding,
    ProgramManifestValidationError,
    ProgramRestorePointReference,
    ProgramUnitKind,
    ProgramWaveKind,
    RiskTier,
    load_program_manifest,
    program_manifest_digest,
    seal_program_manifest,
    validate_program_manifest_binding,
    validate_program_manifest_for_gates,
)


def _budget(spawn_cap: int) -> dict[str, object]:
    return {
        "hard_spawn_cap": spawn_cap,
        "max_attempts_per_unit": 2,
        "max_turns_per_worker": 20,
        "wall_clock_seconds": 1800,
        "token_ceiling": 100_000,
        "on_exceed": "checkpoint-and-escalate",
    }


def _manifest_document() -> dict[str, Any]:
    document: dict[str, Any] = {
        "schema_version": 1,
        "program_id": "runtime-portability",
        "run_id": "run-001",
        "objective": "Make the runtime projection portable.",
        "source_commit": "1" * 40,
        "workflow_definition_digest": "2" * 64,
        "gate_definition_digest": "3" * 64,
        "selection_digest": "4" * 64,
        "revision": 1,
        "parent_digest": None,
        "frozen": True,
        "pre_change_restore_point": {
            "tag_ref": "refs/tags/runtime-portability-pre-change",
            "commit": "1" * 40,
            "verification_artifact_id": "prechange-restore-verification",
            "verification_digest": "c" * 64,
        },
        "boundaries": [
            {"id": "api", "kind": "tree", "path": "src/api"},
            {"id": "ui", "kind": "tree", "path": "src/ui"},
            {"id": "migration", "kind": "tree", "path": "migrations"},
            {"id": "knowledge", "kind": "tree", "path": "docs/runbooks"},
        ],
        "lanes": [
            {
                "id": "backend",
                "boundary_ids": ["api", "migration"],
                "unit_ids": ["audit-api", "implement-api", "migrate-data"],
            },
            {
                "id": "frontend",
                "boundary_ids": ["ui"],
                "unit_ids": ["audit-ui", "implement-ui"],
            },
            {
                "id": "control",
                "boundary_ids": [],
                "unit_ids": ["gate-audit", "gate-low", "gate-restricted"],
            },
            {
                "id": "knowledge",
                "boundary_ids": ["knowledge"],
                "unit_ids": ["knowledge-closeout"],
            },
        ],
        "waves": [
            {
                "id": "audit",
                "order": 0,
                "kind": "audit",
                "parallel": True,
                "risk": "none",
                "unit_ids": ["audit-api", "audit-ui"],
                "gate_ids": [],
                "gate_wave_id": "verification-audit",
                "verifies_wave_id": None,
                "budget": _budget(2),
            },
            {
                "id": "verification-audit",
                "order": 1,
                "kind": "verification",
                "parallel": False,
                "risk": "none",
                "unit_ids": ["gate-audit"],
                "gate_ids": ["wave-0-audit-complete"],
                "gate_wave_id": None,
                "verifies_wave_id": "audit",
                "budget": _budget(1),
            },
            {
                "id": "execution-low",
                "order": 2,
                "kind": "execution",
                "parallel": True,
                "risk": "low",
                "unit_ids": ["implement-api", "implement-ui"],
                "gate_ids": [],
                "gate_wave_id": "verification-low",
                "verifies_wave_id": None,
                "budget": _budget(4),
            },
            {
                "id": "verification-low",
                "order": 3,
                "kind": "verification",
                "parallel": False,
                "risk": "low",
                "unit_ids": ["gate-low"],
                "gate_ids": ["wave-2-regression", "code-review"],
                "gate_wave_id": None,
                "verifies_wave_id": "execution-low",
                "budget": _budget(2),
            },
            {
                "id": "execution-restricted",
                "order": 4,
                "kind": "execution",
                "parallel": False,
                "risk": "restricted",
                "unit_ids": ["migrate-data"],
                "gate_ids": [],
                "gate_wave_id": "verification-restricted",
                "verifies_wave_id": None,
                "budget": _budget(2),
            },
            {
                "id": "verification-restricted",
                "order": 5,
                "kind": "verification",
                "parallel": False,
                "risk": "restricted",
                "unit_ids": ["gate-restricted"],
                "gate_ids": ["wave-4-safety", "build-green"],
                "gate_wave_id": None,
                "verifies_wave_id": "execution-restricted",
                "budget": _budget(2),
            },
            {
                "id": "knowledge-closeout",
                "order": 6,
                "kind": "closeout",
                "parallel": False,
                "risk": "low",
                "unit_ids": ["knowledge-closeout"],
                "gate_ids": [],
                "gate_wave_id": None,
                "verifies_wave_id": None,
                "budget": _budget(1),
            },
        ],
        "units": [
            {
                "id": "audit-api",
                "wave_id": "audit",
                "lane_id": "backend",
                "kind": "audit",
                "objective": "Audit the API surface.",
                "dependencies": [],
                "boundary_ids": ["api"],
                "risk": "none",
                "irreversible": False,
                "inventory": None,
                "restore_point": None,
                "approval": None,
                "evidence": ["scope-record"],
            },
            {
                "id": "audit-ui",
                "wave_id": "audit",
                "lane_id": "frontend",
                "kind": "audit",
                "objective": "Audit the UI surface.",
                "dependencies": [],
                "boundary_ids": ["ui"],
                "risk": "none",
                "irreversible": False,
                "inventory": None,
                "restore_point": None,
                "approval": None,
                "evidence": ["scope-record"],
            },
            {
                "id": "gate-audit",
                "wave_id": "verification-audit",
                "lane_id": "control",
                "kind": "gate-runner",
                "objective": "Freeze scope and verify the pre-change restore point.",
                "dependencies": ["audit-api", "audit-ui"],
                "boundary_ids": [],
                "risk": "none",
                "irreversible": False,
                "inventory": None,
                "restore_point": None,
                "approval": None,
                "evidence": [
                    "frozen-manifest",
                    "prechange-restore-verification",
                ],
            },
            {
                "id": "implement-api",
                "wave_id": "execution-low",
                "lane_id": "backend",
                "kind": "implementation",
                "objective": "Implement the API slice.",
                "dependencies": ["gate-audit"],
                "boundary_ids": ["api"],
                "risk": "low",
                "irreversible": False,
                "inventory": None,
                "restore_point": None,
                "approval": None,
                "evidence": ["command-evidence"],
            },
            {
                "id": "implement-ui",
                "wave_id": "execution-low",
                "lane_id": "frontend",
                "kind": "implementation",
                "objective": "Implement the UI slice.",
                "dependencies": ["gate-audit"],
                "boundary_ids": ["ui"],
                "risk": "low",
                "irreversible": False,
                "inventory": None,
                "restore_point": None,
                "approval": None,
                "evidence": ["command-evidence"],
            },
            {
                "id": "gate-low",
                "wave_id": "verification-low",
                "lane_id": "control",
                "kind": "gate-runner",
                "objective": "Independently verify the low-risk wave.",
                "dependencies": ["implement-api", "implement-ui"],
                "boundary_ids": [],
                "risk": "low",
                "irreversible": False,
                "inventory": None,
                "restore_point": None,
                "approval": None,
                "evidence": [
                    "test-report",
                    "review-verdict",
                    "security-report",
                ],
            },
            {
                "id": "migrate-data",
                "wave_id": "execution-restricted",
                "lane_id": "backend",
                "kind": "implementation",
                "objective": "Apply the approved migration inventory.",
                "dependencies": ["gate-low"],
                "boundary_ids": ["migration"],
                "risk": "restricted",
                "irreversible": True,
                "inventory": {
                    "artifact_id": "migration-inventory",
                    "artifact_digest": "5" * 64,
                    "items_digest": "6" * 64,
                    "item_count": 12,
                    "expected_post_count": 12,
                },
                "restore_point": {
                    "tag_ref": "refs/tags/runtime-portability-wave-4",
                    "commit": "7" * 40,
                    "verification_artifact_id": "wave-4-restore-verification",
                    "verification_digest": "8" * 64,
                },
                "approval": {
                    "request_artifact_id": "migration-approval-request",
                    "request_digest": "9" * 64,
                    "action_digest": "a" * 64,
                    "authorization_artifact_id": "migration-approval-authorization",
                    "authorization_digest": "b" * 64,
                    "inventory_artifact_digest": "5" * 64,
                    "restore_point_commit": "7" * 40,
                },
                "evidence": [
                    "migration-inventory",
                    "wave-4-restore-verification",
                    "migration-approval-request",
                    "migration-approval-authorization",
                ],
            },
            {
                "id": "gate-restricted",
                "wave_id": "verification-restricted",
                "lane_id": "control",
                "kind": "gate-runner",
                "objective": "Verify the restricted migration and inventory counts.",
                "dependencies": ["migrate-data"],
                "boundary_ids": [],
                "risk": "restricted",
                "irreversible": False,
                "inventory": None,
                "restore_point": None,
                "approval": None,
                "evidence": [
                    "test-report",
                    "security-report",
                    "review-verdict",
                ],
            },
            {
                "id": "knowledge-closeout",
                "wave_id": "knowledge-closeout",
                "lane_id": "knowledge",
                "kind": "knowledge-closeout",
                "objective": "Update durable project guidance.",
                "dependencies": ["gate-restricted"],
                "boundary_ids": ["knowledge"],
                "risk": "low",
                "irreversible": False,
                "inventory": None,
                "restore_point": None,
                "approval": None,
                "evidence": ["closeout-record"],
            },
        ],
        "owners": [
            {"unit_id": "audit-api", "route": "classification"},
            {"unit_id": "audit-ui", "route": "classification"},
            {"unit_id": "gate-audit", "route": "code-review"},
            {"unit_id": "implement-api", "route": "backend-delivery"},
            {"unit_id": "implement-ui", "route": "frontend-delivery"},
            {"unit_id": "gate-low", "route": "code-review"},
            {"unit_id": "migrate-data", "route": "general-delivery"},
            {"unit_id": "gate-restricted", "route": "code-review"},
            {"unit_id": "knowledge-closeout", "route": "general-delivery"},
        ],
        "gates": [
            {
                "id": "wave-0-audit-complete",
                "order": 0,
                "kind": "program-wave",
                "wave_id": "verification-audit",
                "owner_unit_id": "gate-audit",
                "evidence": [
                    "frozen-manifest",
                    "prechange-restore-verification",
                ],
            },
            {
                "id": "wave-2-regression",
                "order": 1,
                "kind": "program-wave",
                "wave_id": "verification-low",
                "owner_unit_id": "gate-low",
                "evidence": ["test-report", "security-report"],
            },
            {
                "id": "code-review",
                "order": 2,
                "kind": "pipeline",
                "wave_id": "verification-low",
                "owner_unit_id": "gate-low",
                "evidence": ["review-verdict"],
            },
            {
                "id": "wave-4-safety",
                "order": 3,
                "kind": "program-wave",
                "wave_id": "verification-restricted",
                "owner_unit_id": "gate-restricted",
                "evidence": ["security-report", "review-verdict"],
            },
            {
                "id": "build-green",
                "order": 4,
                "kind": "pipeline",
                "wave_id": "verification-restricted",
                "owner_unit_id": "gate-restricted",
                "evidence": ["test-report"],
            },
        ],
    }
    return seal_program_manifest(document)


def _write_manifest(path: Path, document: dict[str, Any]) -> None:
    if path.suffix == ".json":
        path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    else:
        path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")


@pytest.mark.parametrize("suffix", [".json", ".yaml"])
def test_loads_typed_frozen_manifest_with_format_independent_digest(
    payload: Path, tmp_path: Path, suffix: str
) -> None:
    document = _manifest_document()
    path = tmp_path / f"program{suffix}"
    _write_manifest(path, document)

    manifest = load_program_manifest(
        path, schema_path=payload / "schemas/program-manifest.schema.json"
    )

    assert manifest.digest == program_manifest_digest(document)
    assert manifest.waves[0].kind is ProgramWaveKind.AUDIT
    assert manifest.waves[-1].kind is ProgramWaveKind.CLOSEOUT
    assert manifest.units[0].kind is ProgramUnitKind.AUDIT
    assert manifest.units[-1].risk is RiskTier.LOW
    assert manifest.boundaries[0].kind is BoundaryKind.TREE
    assert isinstance(manifest.pre_change_restore_point, ProgramRestorePointReference)
    irreversible = next(unit for unit in manifest.units if unit.irreversible)
    assert isinstance(irreversible.inventory, ProgramInventoryReference)
    assert irreversible.inventory.item_count == 12
    assert irreversible.inventory.expected_post_count == 12
    assert isinstance(irreversible.restore_point, ProgramRestorePointReference)
    assert isinstance(irreversible.approval, ProgramApprovalReference)
    assert validate_program_manifest_for_gates(
        manifest, ("code-review", "build-green")
    ) == ("code-review", "build-green")


def test_digest_rejects_any_post_freeze_edit(payload: Path, tmp_path: Path) -> None:
    document = _manifest_document()
    document["units"][2]["objective"] = "Tampered after approval."
    path = tmp_path / "program.json"
    _write_manifest(path, document)

    with pytest.raises(ProgramManifestValidationError, match="digest"):
        load_program_manifest(
            path, schema_path=payload / "schemas/program-manifest.schema.json"
        )


def test_loader_rejects_duplicate_yaml_keys_and_symlink(
    payload: Path, tmp_path: Path
) -> None:
    duplicate = tmp_path / "duplicate.yaml"
    duplicate.write_text("schema_version: 1\nschema_version: 1\n", encoding="utf-8")
    with pytest.raises(ProgramManifestValidationError, match="duplicate key"):
        load_program_manifest(
            duplicate, schema_path=payload / "schemas/program-manifest.schema.json"
        )

    real = tmp_path / "real.json"
    _write_manifest(real, _manifest_document())
    link = tmp_path / "link.json"
    try:
        os.symlink(real, link)
    except OSError:
        pytest.skip("symlinks are unavailable")
    with pytest.raises(ProgramManifestValidationError, match="regular file"):
        load_program_manifest(
            link, schema_path=payload / "schemas/program-manifest.schema.json"
        )


def test_loader_rejects_duplicate_json_keys_and_yaml_aliases(
    payload: Path, tmp_path: Path
) -> None:
    document = _manifest_document()
    encoded = json.dumps(document)
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(
        encoded.replace(
            '"schema_version": 1,',
            '"schema_version": 1, "schema_version": 1,',
            1,
        ),
        encoding="utf-8",
    )
    with pytest.raises(ProgramManifestValidationError, match="duplicate key"):
        load_program_manifest(
            duplicate, schema_path=payload / "schemas/program-manifest.schema.json"
        )

    alias = tmp_path / "alias.yaml"
    alias.write_text("shared: &shared [one]\ncopy: *shared\n", encoding="utf-8")
    with pytest.raises(ProgramManifestValidationError, match="YAML aliases"):
        load_program_manifest(
            alias, schema_path=payload / "schemas/program-manifest.schema.json"
        )


def _semantic_failure(
    payload: Path,
    tmp_path: Path,
    mutate: Callable[[dict[str, Any]], None],
    match: str,
) -> None:
    document = _manifest_document()
    mutate(document)
    document = seal_program_manifest(document)
    path = tmp_path / "invalid.json"
    _write_manifest(path, document)
    with pytest.raises(ProgramManifestValidationError, match=match):
        load_program_manifest(
            path, schema_path=payload / "schemas/program-manifest.schema.json"
        )


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (
            lambda document: document["units"][1].update(id="audit-api"),
            "unit ids must be unique",
        ),
        (
            lambda document: document["waves"][1].update(id="audit"),
            "wave ids must be unique",
        ),
        (
            lambda document: document["waves"][2].update(order=8),
            "wave order must be contiguous",
        ),
        (
            lambda document: document["units"][2].update(dependencies=["unknown-unit"]),
            "unknown dependency",
        ),
        (
            lambda document: document["units"][2].update(dependencies=["implement-ui"]),
            "earlier waves",
        ),
        (
            lambda document: document["waves"][4].update(risk="low"),
            "wave risk must equal",
        ),
        (
            lambda document: document["waves"][4].update(risk="medium"),
            "wave risk must equal",
        ),
        (
            lambda document: document["waves"][2]["budget"].update(hard_spawn_cap=1),
            "spawn cap",
        ),
        (
            lambda document: document["gates"][0].update(owner_unit_id="implement-api"),
            "gate-runner",
        ),
        (
            lambda document: document["units"][5].update(
                dependencies=["implement-api"]
            ),
            "all units in work wave",
        ),
        (
            lambda document: document["units"][3].update(dependencies=["audit-api"]),
            "preceding verification gate-runners",
        ),
        (
            lambda document: document["units"][6].update(approval=None),
            "inventory, restore point, and approval bindings",
        ),
        (
            lambda document: document["pre_change_restore_point"].update(
                commit="d" * 40
            ),
            "pre-change restore point",
        ),
    ],
)
def test_rejects_invalid_program_invariants(
    payload: Path,
    tmp_path: Path,
    mutate: Callable[[dict[str, Any]], None],
    match: str,
) -> None:
    _semantic_failure(payload, tmp_path, mutate, match)


def test_rejects_overlapping_boundaries_in_parallel_wave(
    payload: Path, tmp_path: Path
) -> None:
    def overlap(document: dict[str, Any]) -> None:
        document["boundaries"][1] = {
            "id": "ui",
            "kind": "tree",
            "path": "src/api/internal",
        }

    _semantic_failure(payload, tmp_path, overlap, "overlapping boundaries")


@pytest.mark.parametrize("path", ["src/./api", "src/api/", "C:/source/api"])
def test_rejects_noncanonical_boundary_paths(
    payload: Path, tmp_path: Path, path: str
) -> None:
    def noncanonical(document: dict[str, Any]) -> None:
        document["boundaries"][0]["path"] = path

    _semantic_failure(payload, tmp_path, noncanonical, "path")


def test_rejects_execution_without_immediate_verification(
    payload: Path, tmp_path: Path
) -> None:
    def break_pair(document: dict[str, Any]) -> None:
        document["waves"][2]["gate_wave_id"] = "verification-restricted"

    _semantic_failure(payload, tmp_path, break_pair, "immediate verification wave")


def test_rejects_application_boundary_in_final_knowledge_closeout(
    payload: Path, tmp_path: Path
) -> None:
    def application_closeout(document: dict[str, Any]) -> None:
        document["boundaries"][3]["path"] = "src/runtime-closeout"

    _semantic_failure(payload, tmp_path, application_closeout, "closeout.*docs")


def test_rejects_gate_owner_order_that_differs_from_verification_unit_order(
    payload: Path, tmp_path: Path
) -> None:
    def reverse_gate_owners(document: dict[str, Any]) -> None:
        second = copy.deepcopy(document["units"][5])
        second["id"] = "gate-low-second"
        document["units"].insert(6, second)
        document["lanes"][2]["unit_ids"].insert(2, "gate-low-second")
        document["waves"][3]["unit_ids"] = ["gate-low", "gate-low-second"]
        document["owners"].insert(
            6, {"unit_id": "gate-low-second", "route": "code-review"}
        )
        next(unit for unit in document["units"] if unit["id"] == "migrate-data")[
            "dependencies"
        ].append("gate-low-second")
        document["gates"][1]["owner_unit_id"] = "gate-low-second"
        document["gates"][2]["owner_unit_id"] = "gate-low"

    _semantic_failure(
        payload,
        tmp_path,
        reverse_gate_owners,
        "gate owners.*unit order",
    )


def test_rejects_ungated_audit_or_unverified_prechange_restore_point(
    payload: Path, tmp_path: Path
) -> None:
    def remove_audit_gate(document: dict[str, Any]) -> None:
        document["waves"][0]["gate_wave_id"] = None

    _semantic_failure(payload, tmp_path, remove_audit_gate, "audit wave")

    def remove_restore_evidence(document: dict[str, Any]) -> None:
        document["gates"][0]["evidence"] = ["frozen-manifest"]

    _semantic_failure(
        payload,
        tmp_path,
        remove_restore_evidence,
        "Wave 0 program gate",
    )


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (
            lambda document: document["units"][6]["approval"].update(
                inventory_artifact_digest="d" * 64
            ),
            "exact inventory",
        ),
        (
            lambda document: document["units"][6]["approval"].update(
                restore_point_commit="e" * 40
            ),
            "exact restore point",
        ),
        (
            lambda document: document["units"][6].update(
                evidence=["migration-inventory"]
            ),
            "every safeguard artifact",
        ),
        (
            lambda document: document["units"][6]["approval"].update(
                request_artifact_id="migration-inventory"
            ),
            "conflicting content digests",
        ),
    ],
)
def test_rejects_unbound_irreversible_safeguards(
    payload: Path,
    tmp_path: Path,
    mutate: Callable[[dict[str, Any]], None],
    match: str,
) -> None:
    _semantic_failure(payload, tmp_path, mutate, match)


def test_schema_rejects_inventory_without_exact_counts(
    payload: Path, tmp_path: Path
) -> None:
    def negative_post_count(document: dict[str, Any]) -> None:
        document["units"][6]["inventory"]["expected_post_count"] = -1

    _semantic_failure(payload, tmp_path, negative_post_count, "not valid")


@pytest.mark.parametrize(
    "tag_ref",
    [
        "runtime-portability",
        "refs/tags/bad..tag",
        "refs/tags/bad.lock",
        "refs/tags/bad:tag",
    ],
)
def test_rejects_noncanonical_restore_point_tags(
    payload: Path, tmp_path: Path, tag_ref: str
) -> None:
    def invalid_tag(document: dict[str, Any]) -> None:
        document["pre_change_restore_point"]["tag_ref"] = tag_ref

    _semantic_failure(payload, tmp_path, invalid_tag, "tag_ref|git reference")


def test_rejects_irreversible_unit_before_later_execution_wave(
    payload: Path, tmp_path: Path
) -> None:
    def move_irreversible_early(document: dict[str, Any]) -> None:
        restricted = document["units"][6]
        document["units"][3].update(
            risk="restricted",
            irreversible=True,
            inventory=copy.deepcopy(restricted["inventory"]),
            restore_point=copy.deepcopy(restricted["restore_point"]),
            approval=copy.deepcopy(restricted["approval"]),
            evidence=copy.deepcopy(restricted["evidence"]),
        )
        document["waves"][2].update(risk="restricted")
        document["waves"][3].update(risk="restricted")
        document["units"][5].update(risk="restricted")

    _semantic_failure(
        payload,
        tmp_path,
        move_irreversible_early,
        "final execution wave",
    )


def _load_valid_manifest(payload: Path, tmp_path: Path) -> ProgramManifest:
    path = tmp_path / "program.json"
    _write_manifest(path, _manifest_document())
    return load_program_manifest(
        path, schema_path=payload / "schemas/program-manifest.schema.json"
    )


def _binding_arguments() -> dict[str, Any]:
    return {
        "run_id": "run-001",
        "source_commit": "1" * 40,
        "workflow_definition_digest": "2" * 64,
        "gate_definition_digest": "3" * 64,
        "selection_digest": "4" * 64,
        "ordered_gates": ("code-review", "build-green"),
        "expected_revision": 1,
        "previous_manifest_digest": None,
    }


def test_authoritative_manifest_binding_returns_exact_persistence_record(
    payload: Path, tmp_path: Path
) -> None:
    manifest = _load_valid_manifest(payload, tmp_path)

    binding = validate_program_manifest_binding(manifest, **_binding_arguments())

    assert isinstance(binding, ProgramManifestBinding)
    assert binding.manifest_digest == manifest.digest
    assert binding.revision == 1
    assert binding.parent_digest is None
    assert binding.pipeline_gate_ids == ("code-review", "build-green")


@pytest.mark.parametrize(
    ("field", "replacement", "match"),
    [
        ("run_id", "run-other", "run id"),
        ("source_commit", "f" * 40, "source commit"),
        ("workflow_definition_digest", "e" * 64, "workflow definition"),
        ("gate_definition_digest", "d" * 64, "gate definition"),
        ("selection_digest", "c" * 64, "selection digest"),
        (
            "ordered_gates",
            ("build-green", "code-review"),
            "pipeline gate order",
        ),
        ("expected_revision", 2, "authoritative revision"),
        ("expected_revision", 1.0, "authoritative revision"),
    ],
)
def test_authoritative_manifest_binding_rejects_every_mismatched_input(
    payload: Path,
    tmp_path: Path,
    field: str,
    replacement: Any,
    match: str,
) -> None:
    manifest = _load_valid_manifest(payload, tmp_path)
    arguments = _binding_arguments()
    arguments[field] = replacement

    with pytest.raises(ProgramManifestValidationError, match=match):
        validate_program_manifest_binding(manifest, **arguments)


def test_authoritative_manifest_binding_checks_revision_parent_chain(
    payload: Path, tmp_path: Path
) -> None:
    document = _manifest_document()
    document["revision"] = 2
    document["parent_digest"] = "d" * 64
    document = seal_program_manifest(document)
    path = tmp_path / "revision-2.json"
    _write_manifest(path, document)
    manifest = load_program_manifest(
        path, schema_path=payload / "schemas/program-manifest.schema.json"
    )
    arguments = _binding_arguments()
    arguments.update(expected_revision=2, previous_manifest_digest="d" * 64)

    binding = validate_program_manifest_binding(manifest, **arguments)
    assert binding.parent_digest == "d" * 64

    arguments["previous_manifest_digest"] = "e" * 64
    with pytest.raises(ProgramManifestValidationError, match="revision parent"):
        validate_program_manifest_binding(manifest, **arguments)

    first_revision = _load_valid_manifest(payload, tmp_path)
    first_arguments = _binding_arguments()
    first_arguments["previous_manifest_digest"] = "d" * 64
    with pytest.raises(ProgramManifestValidationError, match="revision 1"):
        validate_program_manifest_binding(first_revision, **first_arguments)


def test_gate_plan_requires_exact_pipeline_gate_order(
    payload: Path, tmp_path: Path
) -> None:
    path = tmp_path / "program.json"
    _write_manifest(path, _manifest_document())
    manifest = load_program_manifest(
        path, schema_path=payload / "schemas/program-manifest.schema.json"
    )

    with pytest.raises(ProgramManifestValidationError, match="pipeline gate order"):
        validate_program_manifest_for_gates(manifest, ("build-green", "code-review"))


def test_schema_rejects_unknown_fields(payload: Path, tmp_path: Path) -> None:
    document = _manifest_document()
    document["provider"] = "claude"
    document = seal_program_manifest(document)
    path = tmp_path / "program.json"
    _write_manifest(path, document)

    with pytest.raises(ProgramManifestValidationError, match="provider"):
        load_program_manifest(
            path, schema_path=payload / "schemas/program-manifest.schema.json"
        )


def test_seal_is_pure_and_revision_parent_is_consistent() -> None:
    document = _manifest_document()
    original = copy.deepcopy(document)
    resealed = seal_program_manifest(document)
    assert document == original
    assert resealed["digest"] == program_manifest_digest(resealed)
