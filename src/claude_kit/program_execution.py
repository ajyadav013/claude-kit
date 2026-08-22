"""Authoritative Mode E execution over the shared pipeline control plane.

The program manifest is governance, not authorization.  This coordinator can
run read-only audits, gate verification, and reversible bounded work.  It
always stops before an irreversible unit because the approval broker has no
scoped consume-once integration yet.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Protocol, Sequence, runtime_checkable

from claude_kit import pipeline, scaffold
from claude_kit.components import (
    Capability,
    NestedDelegationPolicy,
    PermissionClass,
    SymbolicRef,
)
from claude_kit.dispatch import (
    Dispatcher,
    DispatchHandle,
    DispatchRequest,
    DispatchResult,
    DispatchStatus,
    HumanStopReason,
    HumanStopRequest,
    WaitMode,
)
from claude_kit.process_dispatch import (
    DispatchAdapterError,
    FilesystemNativeRoleLoader,
    ProcessDispatcher,
    RoleUnavailableError,
    UnsupportedCapabilityError,
)
from claude_kit.program_runtime import (
    ProgramApprovalReference,
    ProgramInventoryReference,
    ProgramManifest,
    ProgramManifestValidationError,
    ProgramRestorePointReference,
    ProgramUnit,
    ProgramUnitKind,
    ProgramWaveKind,
    load_program_manifest,
    validate_program_manifest_binding,
)
from claude_kit.projection import Provider
from claude_kit.secure_fs import ProjectFS, UnsafePathError
from claude_kit.state import detect_state_layout
from claude_kit.workflow_executor import (
    ManagedWorktreeResolver,
    StageArtifactRef,
    StageExecution,
    WorkflowExecutionResult,
    WorkflowExecutionStatus,
)
from claude_kit.workflows import (
    BoundWorkflow,
    WorkflowValidationError,
    workflow_definition_digest,
)

_MAX_ARTIFACT_BYTES = 8 * 1024 * 1024
_MAX_TERMINAL_ARTIFACT_BYTES = 4 * 1024 * 1024
_MAX_WORKSPACE_PATHS = 100_000
_MAX_WORKSPACE_BYTES = 2 * 1024 * 1024 * 1024
_MAX_HANDOFF_BYTES = 512 * 1024
_MAX_HANDOFF_ARTIFACT_BYTES = 8 * 1024 * 1024
_MAX_HANDOFF_SCANNED_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True)
class ProgramBoundaryContainmentAttestation:
    """Adapter-owned, content-bound proof of a reserved physical write sandbox."""

    issuer: str
    provider: str
    route: str
    dispatch_id: str
    unit_id: str
    workspace_target: str
    boundary_digest: str
    pre_workspace_checkpoint_digest: str
    policy: str
    attestation_sha256: str
    schema_version: int = 1
    kind: str = "physical-program-boundary-containment"
    enforcement: str = "adapter-physical-no-follow"

    @classmethod
    def issue(
        cls,
        *,
        issuer: str,
        provider: str,
        route: str,
        dispatch_id: str,
        unit_id: str,
        workspace_target: str,
        boundary_digest: str,
        pre_workspace_checkpoint_digest: str,
        policy: str,
    ) -> ProgramBoundaryContainmentAttestation:
        """Bind an adapter assertion to the exact queued attempt and checkpoint."""

        core = {
            "schema_version": 1,
            "kind": "physical-program-boundary-containment",
            "enforcement": "adapter-physical-no-follow",
            "issuer": issuer,
            "provider": provider,
            "route": route,
            "dispatch_id": dispatch_id,
            "unit_id": unit_id,
            "workspace_target": workspace_target,
            "boundary_digest": boundary_digest,
            "pre_workspace_checkpoint_digest": pre_workspace_checkpoint_digest,
            "policy": policy,
        }
        return cls(
            issuer=issuer,
            provider=provider,
            route=route,
            dispatch_id=dispatch_id,
            unit_id=unit_id,
            workspace_target=workspace_target,
            boundary_digest=boundary_digest,
            pre_workspace_checkpoint_digest=pre_workspace_checkpoint_digest,
            policy=policy,
            attestation_sha256=_canonical_digest(core),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "enforcement": self.enforcement,
            "issuer": self.issuer,
            "provider": self.provider,
            "route": self.route,
            "dispatch_id": self.dispatch_id,
            "unit_id": self.unit_id,
            "workspace_target": self.workspace_target,
            "boundary_digest": self.boundary_digest,
            "pre_workspace_checkpoint_digest": self.pre_workspace_checkpoint_digest,
            "policy": self.policy,
            "attestation_sha256": self.attestation_sha256,
        }


@runtime_checkable
class ProgramBoundaryContainedDispatcher(Protocol):
    """Trusted injected adapter seam for physically confined queued workers."""

    queued_spawn: bool

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
        """Attest the sandbox reserved for this exact queued handle."""
        ...


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return _sha256_bytes(encoded)


def _stream_regular_file(
    root: Path,
    relative: str,
    *,
    maximum_bytes: int,
    prefix_bytes: int = 0,
) -> tuple[str, int, bytes, int]:
    """Hash a no-follow regular file while retaining only a bounded prefix."""

    fs = ProjectFS(root)
    canonical = fs.relpath(relative)
    path = fs.path(canonical)
    try:
        expected = fs.stat(canonical)
        flags = os.O_RDONLY
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags)
    except (OSError, UnsafePathError, ValueError) as exc:
        raise WorkflowValidationError(
            f"cannot securely open program file {relative!r}: {exc}"
        ) from exc
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (
            expected.st_dev,
            expected.st_ino,
        ):
            raise WorkflowValidationError(
                f"program file {relative!r} changed identity or is not regular"
            )
        if opened.st_size > maximum_bytes:
            raise WorkflowValidationError(
                f"program file {relative!r} exceeds the {maximum_bytes}-byte limit"
            )
        digest = hashlib.sha256()
        prefix = bytearray()
        consumed = 0
        while True:
            chunk = os.read(descriptor, 64 * 1024)
            if not chunk:
                break
            consumed += len(chunk)
            if consumed > maximum_bytes:
                raise WorkflowValidationError(
                    f"program file {relative!r} grew beyond its byte limit"
                )
            digest.update(chunk)
            if len(prefix) < prefix_bytes:
                prefix.extend(chunk[: prefix_bytes - len(prefix)])
        final = os.fstat(descriptor)
        if (
            consumed != final.st_size
            or (final.st_dev, final.st_ino) != (opened.st_dev, opened.st_ino)
            or final.st_mtime_ns != opened.st_mtime_ns
            or final.st_ctime_ns != opened.st_ctime_ns
        ):
            raise WorkflowValidationError(
                f"program file {relative!r} changed while it was being hashed"
            )
        return digest.hexdigest(), consumed, bytes(prefix), opened.st_mode
    except OSError as exc:
        raise WorkflowValidationError(
            f"cannot securely read program file {relative!r}: {exc}"
        ) from exc
    finally:
        os.close(descriptor)


def load_packaged_program_manifest(
    project_root: Path, manifest_path: Path
) -> tuple[ProgramManifest, str]:
    """Load a contained manifest using only the schema shipped by claude-kit."""

    root = Path(project_root).resolve(strict=True)
    supplied = Path(manifest_path).expanduser()
    candidate = supplied if supplied.is_absolute() else root / supplied
    try:
        relative = candidate.relative_to(root).as_posix()
    except ValueError as exc:
        raise WorkflowValidationError(
            "program manifest must be contained in the target project"
        ) from exc
    try:
        contained = ProjectFS(root).path(relative)
    except (OSError, UnsafePathError, ValueError) as exc:
        raise WorkflowValidationError(
            f"program manifest path is unsafe: {exc}"
        ) from exc
    with ExitStack() as resources:
        packaged_schema = (
            scaffold.payload_dir(resources) / "schemas" / "program-manifest.schema.json"
        )
        try:
            manifest = load_program_manifest(contained, schema_path=packaged_schema)
        except ProgramManifestValidationError as exc:
            raise WorkflowValidationError(str(exc)) from exc
    return manifest, relative


def program_artifact_path(project_root: Path, artifact_id: str) -> Path:
    """Return the deterministic root-owned file for a program artifact id."""

    if (
        not artifact_id
        or any(
            character not in "abcdefghijklmnopqrstuvwxyz0123456789._-"
            for character in artifact_id
        )
        or artifact_id[0] not in "abcdefghijklmnopqrstuvwxyz0123456789"
    ):
        raise WorkflowValidationError(
            "program artifact id must be a contained lowercase identifier"
        )
    root = Path(project_root).resolve(strict=True)
    layout = detect_state_layout(root)
    relative = f"{layout.artifacts}/program/{artifact_id}.json"
    try:
        return ProjectFS(root).path(relative)
    except (OSError, UnsafePathError, ValueError) as exc:
        raise WorkflowValidationError(
            f"program artifact path is unsafe: {exc}"
        ) from exc


def _read_artifact(project_root: Path, artifact_id: str) -> tuple[Path, bytes, str]:
    path = program_artifact_path(project_root, artifact_id)
    try:
        root = Path(project_root).resolve(strict=True)
        relative = path.relative_to(root).as_posix()
        _digest, _size, data, _mode = _stream_regular_file(
            root,
            relative,
            maximum_bytes=_MAX_ARTIFACT_BYTES,
            prefix_bytes=_MAX_ARTIFACT_BYTES,
        )
    except (OSError, ValueError, WorkflowValidationError) as exc:
        raise WorkflowValidationError(
            f"cannot read program artifact {artifact_id!r}: {exc}"
        ) from exc
    return path, data, relative


def _artifact_record(
    project_root: Path,
    *,
    kind: str,
    artifact_id: str,
    expected_digest: str,
    details: Mapping[str, Any],
) -> dict[str, Any]:
    _path, content, relative = _read_artifact(project_root, artifact_id)
    actual = _sha256_bytes(content)
    if actual != expected_digest:
        raise WorkflowValidationError(
            f"program artifact {artifact_id!r} digest mismatch"
        )
    return {
        "kind": kind,
        "artifact_id": artifact_id,
        "artifact_path": relative,
        "artifact_sha256": actual,
        "details": dict(details),
    }


def _verify_inventory(
    project_root: Path, reference: ProgramInventoryReference
) -> dict[str, Any]:
    _path, content, relative = _read_artifact(project_root, reference.artifact_id)
    if _sha256_bytes(content) != reference.artifact_digest:
        raise WorkflowValidationError(
            f"program inventory {reference.artifact_id!r} digest mismatch"
        )
    try:
        document = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorkflowValidationError(
            f"program inventory {reference.artifact_id!r} is invalid JSON: {exc}"
        ) from exc
    if not isinstance(document, dict) or not isinstance(document.get("items"), list):
        raise WorkflowValidationError(
            f"program inventory {reference.artifact_id!r} has no items array"
        )
    items = document["items"]
    actual_items_digest = _canonical_digest(items)
    actual_count = len(items)
    if actual_items_digest != reference.items_digest:
        raise WorkflowValidationError(
            f"program inventory {reference.artifact_id!r} items digest mismatch"
        )
    if actual_count != reference.item_count:
        raise WorkflowValidationError(
            f"program inventory {reference.artifact_id!r} item count mismatch"
        )
    if (
        document.get("item_count") != reference.item_count
        or document.get("expected_post_count") != reference.expected_post_count
    ):
        raise WorkflowValidationError(
            f"program inventory {reference.artifact_id!r} count contract mismatch"
        )
    return {
        "kind": "inventory",
        "artifact_id": reference.artifact_id,
        "artifact_path": relative,
        "artifact_sha256": reference.artifact_digest,
        "details": {
            "items_digest": reference.items_digest,
            "item_count": reference.item_count,
            "expected_post_count": reference.expected_post_count,
        },
    }


def _verify_restore_point(
    project_root: Path, reference: ProgramRestorePointReference
) -> dict[str, Any]:
    root = Path(project_root).resolve(strict=True)
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "rev-parse",
                "--verify",
                f"{reference.tag_ref}^{{commit}}",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise WorkflowValidationError(
            f"cannot verify restore tag {reference.tag_ref!r}: {exc}"
        ) from exc
    resolved = result.stdout.strip()
    if resolved != reference.commit:
        raise WorkflowValidationError(
            f"restore tag {reference.tag_ref!r} resolves to {resolved!r}, "
            f"not {reference.commit!r}"
        )
    return _artifact_record(
        root,
        kind="restore-point",
        artifact_id=reference.verification_artifact_id,
        expected_digest=reference.verification_digest,
        details={"tag_ref": reference.tag_ref, "commit": reference.commit},
    )


def _verify_approval(
    project_root: Path, reference: ProgramApprovalReference
) -> tuple[dict[str, Any], dict[str, Any]]:
    details = {
        "action_digest": reference.action_digest,
        "inventory_artifact_digest": reference.inventory_artifact_digest,
        "restore_point_commit": reference.restore_point_commit,
        "authorization_consumed": False,
    }
    request = _artifact_record(
        project_root,
        kind="approval-request",
        artifact_id=reference.request_artifact_id,
        expected_digest=reference.request_digest,
        details=details,
    )
    authorization = _artifact_record(
        project_root,
        kind="approval-authorization",
        artifact_id=reference.authorization_artifact_id,
        expected_digest=reference.authorization_digest,
        details=details,
    )
    return request, authorization


def _manifest_record(
    project_root: Path, manifest: ProgramManifest, manifest_relative: str
) -> dict[str, Any]:
    fs = ProjectFS(project_root)
    content = fs.read_bytes(manifest_relative)
    return {
        "kind": "manifest",
        "artifact_id": "frozen-manifest",
        "artifact_path": manifest_relative,
        "artifact_sha256": _sha256_bytes(content),
        "details": {
            "manifest_digest": manifest.digest,
            "revision": manifest.revision,
            "parent_digest": manifest.parent_digest,
        },
    }


def _unit_safeguards(
    project_root: Path, unit: ProgramUnit
) -> tuple[dict[str, Any], ...]:
    records: list[dict[str, Any]] = []
    if unit.inventory is not None:
        records.append(_verify_inventory(project_root, unit.inventory))
    if unit.restore_point is not None:
        records.append(_verify_restore_point(project_root, unit.restore_point))
    if unit.approval is not None:
        records.extend(_verify_approval(project_root, unit.approval))
    return tuple(records)


def _persist_structured_evidence(
    project_root: Path,
    artifact_id: str,
    *,
    run_id: str,
    manifest_digest: str,
    unit_id: str,
    ledger_attempt: int,
    requirement: Mapping[str, Any],
    content: bytes,
    source_output_sha256: str,
) -> dict[str, Any]:
    """Persist one validated structured worker result in a run-owned namespace."""

    candidate_data = content
    evidence_problem = pipeline._program_evidence_document_problem(  # noqa: SLF001
        candidate_data, requirement
    )
    if evidence_problem:
        raise WorkflowValidationError(
            f"worker evidence {artifact_id!r} is invalid: {evidence_problem}"
        )
    root = Path(project_root).resolve(strict=True)
    candidate_digest = _sha256_bytes(candidate_data)
    layout = detect_state_layout(root)
    relative = (
        f"{layout.artifacts}/program/runs/{run_id}/{manifest_digest}/"
        f"{unit_id}/{ledger_attempt}/{artifact_id}-{candidate_digest}.json"
    )
    try:
        destination = ProjectFS(root).path(relative)
        destination_info = destination.lstat()
    except FileNotFoundError:
        destination_info = None
    except OSError as exc:
        raise WorkflowValidationError(
            f"cannot inspect root-owned evidence {artifact_id!r}: {exc}"
        ) from exc
    if destination_info is not None:
        if (
            not stat.S_ISREG(destination_info.st_mode)
            or destination_info.st_size > _MAX_ARTIFACT_BYTES
        ):
            raise WorkflowValidationError(
                f"root-owned evidence {artifact_id!r} must be a bounded regular file"
            )
        try:
            _digest, _size, existing, _mode = _stream_regular_file(
                root,
                relative,
                maximum_bytes=_MAX_ARTIFACT_BYTES,
                prefix_bytes=_MAX_ARTIFACT_BYTES,
            )
        except (OSError, ValueError, WorkflowValidationError) as exc:
            raise WorkflowValidationError(
                f"cannot read root-owned evidence {artifact_id!r}: {exc}"
            ) from exc
        if (
            not hashlib.sha256(existing).digest()
            == hashlib.sha256(candidate_data).digest()
        ):
            raise WorkflowValidationError(
                f"worker evidence {artifact_id!r} conflicts with the root-owned artifact"
            )
        candidate_data = existing
    if destination_info is None:
        ProjectFS(root).write_bytes(relative, candidate_data, mode=0o600)
    return {
        "kind": "evidence",
        "artifact_id": artifact_id,
        "artifact_path": relative,
        "artifact_sha256": candidate_digest,
        "details": {
            "content_bytes": len(candidate_data),
            "evidence_kind": requirement["kind"],
            "validation_profile": requirement["validation_profile"],
            "required_fields": list(requirement["required_fields"]),
            "source": "structured-terminal-output",
            "source_output_sha256": source_output_sha256,
        },
    }


def _structured_evidence_payloads(
    unit: ProgramUnit,
    result: DispatchResult,
    evidence_requirements: Mapping[str, Mapping[str, Any]],
    blocking_severities: Sequence[str],
) -> dict[str, bytes]:
    """Extract exact typed evidence from the bounded host result envelope."""

    expected = {
        artifact_id
        for artifact_id in unit.evidence
        if artifact_id in evidence_requirements
    }
    if not expected:
        return {}
    if (
        result.output is None
        or len(result.output.encode("utf-8")) > _MAX_ARTIFACT_BYTES
    ):
        raise WorkflowValidationError(
            "worker must return a bounded JSON evidence envelope in terminal output"
        )
    try:
        envelope = json.loads(result.output)
    except json.JSONDecodeError as exc:
        raise WorkflowValidationError(
            f"worker evidence envelope is invalid JSON: {exc}"
        ) from exc
    if not isinstance(envelope, dict) or set(envelope) != {"evidence"}:
        raise WorkflowValidationError(
            "worker evidence output must be exactly {'evidence': {...}}"
        )
    evidence = envelope.get("evidence")
    if not isinstance(evidence, dict) or set(evidence) != expected:
        raise WorkflowValidationError(
            "worker evidence envelope does not contain the exact ordinary evidence set"
        )
    payloads: dict[str, bytes] = {}
    for artifact_id in sorted(expected):
        document = evidence[artifact_id]
        if not isinstance(document, dict):
            raise WorkflowValidationError(
                f"worker evidence {artifact_id!r} must be a JSON object"
            )
        payload = (
            json.dumps(
                document,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        problem = pipeline._program_evidence_document_problem(  # noqa: SLF001
            payload, evidence_requirements[artifact_id]
        )
        if problem:
            raise WorkflowValidationError(
                f"worker evidence {artifact_id!r} is invalid: {problem}"
            )
        pass_problem = pipeline._program_evidence_pass_problem(  # noqa: SLF001
            payload,
            evidence_requirements[artifact_id],
            blocking_severities,
        )
        if pass_problem:
            raise WorkflowValidationError(
                f"worker evidence {artifact_id!r} cannot support success: {pass_problem}"
            )
        payloads[artifact_id] = payload
    return payloads


def _evidence_records(
    project_root: Path,
    manifest: ProgramManifest,
    manifest_relative: str,
    unit: ProgramUnit,
    result: DispatchResult,
    ledger_attempt: int,
    run_id: str,
    evidence_requirements: Mapping[str, Mapping[str, Any]],
    blocking_severities: Sequence[str],
    workspace_content_digest: str,
) -> tuple[dict[str, Any], ...]:
    safeguards = {
        record["artifact_id"]: record for record in _unit_safeguards(project_root, unit)
    }
    structured_payloads = _structured_evidence_payloads(
        unit, result, evidence_requirements, blocking_severities
    )
    records: list[dict[str, Any]] = []
    for artifact_id in unit.evidence:
        if artifact_id == "frozen-manifest":
            record = _manifest_record(project_root, manifest, manifest_relative)
        elif artifact_id == manifest.pre_change_restore_point.verification_artifact_id:
            record = _verify_restore_point(
                project_root, manifest.pre_change_restore_point
            )
        elif artifact_id in safeguards:
            record = safeguards[artifact_id]
        else:
            requirement = evidence_requirements.get(artifact_id)
            if not isinstance(requirement, Mapping):
                raise WorkflowValidationError(
                    f"ordinary evidence {artifact_id!r} has no frozen workflow contract"
                )
            record = _persist_structured_evidence(
                project_root,
                artifact_id,
                run_id=run_id,
                manifest_digest=manifest.digest,
                unit_id=unit.id,
                ledger_attempt=ledger_attempt,
                requirement=requirement,
                content=structured_payloads[artifact_id],
                source_output_sha256=_sha256_bytes(
                    (result.output or "").encode("utf-8")
                ),
            )
            record["details"].update(
                {
                    "unit_id": unit.id,
                    "dispatch_id": result.handle.id,
                    "dispatch_attempt": result.handle.attempt,
                    "ledger_attempt": ledger_attempt,
                    "workspace_content_digest": workspace_content_digest,
                }
            )
        records.append(record)
    return tuple(records)


def _persist_terminal_result(
    project_root: Path,
    *,
    run_id: str,
    manifest_digest: str,
    unit_id: str,
    attempt: int,
    result: DispatchResult,
) -> tuple[str, str]:
    if (
        not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", run_id)
        or not re.fullmatch(r"[0-9a-f]{64}", manifest_digest)
        or not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", unit_id)
        or not isinstance(attempt, int)
        or isinstance(attempt, bool)
        or attempt < 1
    ):
        raise WorkflowValidationError(
            "program terminal result requires an exact run/manifest/unit/attempt identity"
        )
    document = {
        "schema_version": 1,
        "run_id": run_id,
        "program_manifest_digest": manifest_digest,
        "unit_id": unit_id,
        "attempt": attempt,
        "dispatch_id": result.handle.id,
        "dispatch_attempt": result.handle.attempt,
        "provider": result.handle.provider,
        "route": result.handle.route,
        "status": result.status.value,
        "output": result.output,
        "error": result.error,
        "evidence": [item.uri for item in result.evidence],
    }
    content = (
        json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
    if len(content) > _MAX_TERMINAL_ARTIFACT_BYTES:
        raise WorkflowValidationError(
            "program terminal result exceeds the bounded artifact limit"
        )
    digest = _sha256_bytes(content)
    layout = detect_state_layout(project_root)
    relative = (
        f"{layout.artifacts}/program/runs/{run_id}/{manifest_digest}/"
        f"{unit_id}/{attempt}/terminal-{digest}.json"
    )
    root = Path(project_root).resolve(strict=True)
    fs = ProjectFS(root)
    try:
        destination_info = fs.path(relative).lstat()
    except FileNotFoundError:
        destination_info = None
    except (OSError, ValueError) as exc:
        raise WorkflowValidationError(
            f"cannot inspect root-owned terminal result: {exc}"
        ) from exc
    if destination_info is None:
        fs.write_bytes(relative, content, mode=0o600)
    else:
        if not stat.S_ISREG(destination_info.st_mode):
            raise WorkflowValidationError(
                "program terminal result content address is not a regular file"
            )
        try:
            existing_digest, _size, existing, existing_mode = _stream_regular_file(
                root,
                relative,
                maximum_bytes=_MAX_TERMINAL_ARTIFACT_BYTES,
                prefix_bytes=_MAX_TERMINAL_ARTIFACT_BYTES,
            )
        except (OSError, ValueError, WorkflowValidationError) as exc:
            raise WorkflowValidationError(
                f"cannot inspect root-owned terminal result: {exc}"
            ) from exc
        if (
            existing_digest != digest
            or existing != content
            or stat.S_IMODE(existing_mode) != 0o600
        ):
            raise WorkflowValidationError(
                "program terminal result conflicts with its content address"
            )
    return relative, digest


def _dependency_handoff(
    project_root: Path, program: Mapping[str, Any], unit: ProgramUnit
) -> str:
    attempts = program.get("unit_attempts")
    if not isinstance(attempts, list) or not unit.dependencies:
        return ""
    root = Path(project_root).resolve(strict=True)
    rendered = bytearray(
        b"Verified dependency handoff from root-owned program artifacts:\n"
    )
    scanned = 0
    for dependency in unit.dependencies:
        matches = [
            item
            for item in attempts
            if isinstance(item, dict)
            and item.get("unit_id") == dependency
            and item.get("status") == "succeeded"
        ]
        if len(matches) != 1:
            raise WorkflowValidationError(
                f"dependency {dependency!r} has no unique successful attempt"
            )
        attempt = matches[0]
        artifacts = attempt.get("evidence_verifications")
        if not isinstance(artifacts, list):
            raise WorkflowValidationError(
                f"dependency {dependency!r} evidence ledger is malformed"
            )
        ordered_artifacts = sorted(
            artifacts,
            key=lambda item: (
                str(item.get("artifact_id")) if isinstance(item, dict) else ""
            ),
        )
        for artifact in ordered_artifacts:
            if not isinstance(artifact, dict):
                raise WorkflowValidationError(
                    f"dependency {dependency!r} evidence record is malformed"
                )
            relative = artifact.get("artifact_path")
            digest = artifact.get("artifact_sha256")
            if not isinstance(relative, str) or not isinstance(digest, str):
                raise WorkflowValidationError(
                    f"dependency {dependency!r} evidence identity is malformed"
                )
            header = (
                f"\n--- {dependency}/{artifact.get('artifact_id')} sha256={digest}"
            ).encode("utf-8")
            remaining_prefix = max(
                0,
                _MAX_HANDOFF_BYTES - len(rendered) - len(header) - 96,
            )
            actual_digest, size, prefix, _mode = _stream_regular_file(
                root,
                relative,
                maximum_bytes=_MAX_HANDOFF_ARTIFACT_BYTES,
                prefix_bytes=remaining_prefix,
            )
            scanned += size
            if scanned > _MAX_HANDOFF_SCANNED_BYTES:
                raise WorkflowValidationError(
                    "dependency evidence exceeds the aggregate handoff scan limit"
                )
            if actual_digest != digest:
                raise WorkflowValidationError(
                    f"dependency evidence {relative!r} changed after verification"
                )
            header += f" bytes={size} ---\n".encode("utf-8")
            if len(rendered) + len(header) <= _MAX_HANDOFF_BYTES:
                rendered.extend(header)
            room = max(0, _MAX_HANDOFF_BYTES - len(rendered))
            if room:
                rendered.extend(prefix[:room])
            if len(prefix) < size and len(rendered) < _MAX_HANDOFF_BYTES:
                marker = b"\n[artifact prefix truncated by handoff byte limit]"
                rendered.extend(marker[: _MAX_HANDOFF_BYTES - len(rendered)])
    return rendered.decode("utf-8", errors="ignore")


def _workspace_snapshot(workspace: Path) -> tuple[dict[str, str], str]:
    """Hash the exact index plus tracked, untracked, and ignored workspace state."""

    try:
        tracked = subprocess.run(
            [
                "git",
                "-C",
                str(workspace),
                "ls-files",
                "--stage",
                "-z",
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
        untracked = subprocess.run(
            [
                "git",
                "-C",
                str(workspace),
                "ls-files",
                "--others",
                "--exclude-standard",
                "-z",
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
        ignored = subprocess.run(
            [
                "git",
                "-C",
                str(workspace),
                "ls-files",
                "--others",
                "--ignored",
                "--exclude-standard",
                "-z",
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise WorkflowValidationError(
            f"cannot enumerate program workspace files: {exc}"
        ) from exc

    tracked_metadata: dict[bytes, bytes] = {}
    for entry in tracked.stdout.split(b"\0"):
        if not entry:
            continue
        try:
            metadata, raw_path = entry.split(b"\t", 1)
            index_mode, object_id, stage = metadata.split(b" ", 2)
        except ValueError as exc:
            raise WorkflowValidationError(
                "git returned malformed program index metadata"
            ) from exc
        if (
            not re.fullmatch(rb"[0-7]{6}", index_mode)
            or not re.fullmatch(rb"[0-9a-f]{40}|[0-9a-f]{64}", object_id)
            or stage != b"0"
        ):
            raise WorkflowValidationError(
                "program workspace has malformed or conflicted index state"
            )
        if raw_path in tracked_metadata:
            raise WorkflowValidationError(
                "program workspace index contains duplicate paths"
            )
        tracked_metadata[raw_path] = metadata
    untracked_paths = {item for item in untracked.stdout.split(b"\0") if item}
    ignored_paths = {item for item in ignored.stdout.split(b"\0") if item}
    if (
        set(tracked_metadata) & untracked_paths
        or set(tracked_metadata) & ignored_paths
        or untracked_paths & ignored_paths
    ):
        raise WorkflowValidationError(
            "git returned overlapping program workspace path classifications"
        )
    raw_paths = sorted(set(tracked_metadata) | untracked_paths | ignored_paths)
    if len(raw_paths) > _MAX_WORKSPACE_PATHS:
        raise WorkflowValidationError("program workspace exceeds the path safety limit")
    records: dict[str, str] = {}
    consumed = 0
    root = workspace.resolve(strict=True)
    for raw in raw_paths:
        try:
            relative = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise WorkflowValidationError(
                "program workspace contains a non-UTF-8 path"
            ) from exc
        candidate = Path(relative)
        if (
            not relative
            or candidate.is_absolute()
            or ".." in candidate.parts
            or candidate.as_posix() != relative
        ):
            raise WorkflowValidationError(
                f"program workspace contains unsafe path {relative!r}"
            )
        path = root / candidate
        if raw in tracked_metadata:
            classification = "tracked:" + tracked_metadata[raw].decode("ascii")
        elif raw in ignored_paths:
            classification = "ignored"
        else:
            classification = "untracked"
        try:
            info = path.lstat()
        except FileNotFoundError:
            records[relative] = f"{classification}:missing"
            continue
        if stat.S_ISREG(info.st_mode):
            try:
                digest, size, _prefix, file_mode = _stream_regular_file(
                    root,
                    relative,
                    maximum_bytes=_MAX_WORKSPACE_BYTES - consumed,
                )
            except WorkflowValidationError as exc:
                raise WorkflowValidationError(
                    f"cannot hash program workspace path {relative!r}: {exc}"
                ) from exc
            consumed += size
            kind = "file-executable" if file_mode & stat.S_IXUSR else "file"
            records[relative] = f"{classification}:{kind}:{digest}"
        elif stat.S_ISLNK(info.st_mode):
            try:
                records[relative] = f"{classification}:symlink:" + os.readlink(path)
            except OSError as exc:
                raise WorkflowValidationError(
                    f"cannot inspect program workspace symlink {relative!r}: {exc}"
                ) from exc
        else:
            raise WorkflowValidationError(
                f"program workspace path {relative!r} is not a regular file or symlink"
            )
    return records, _canonical_digest(records)


def _stable_workspace_capture(
    workspace: Path,
    workspace_resolver: ManagedWorktreeResolver,
    *,
    label: str,
) -> tuple[dict[str, str], Mapping[str, Any]]:
    """Bind a per-path inventory to one stable authoritative checkpoint."""

    first_files, first_digest = _workspace_snapshot(workspace)
    first_checkpoint = workspace_resolver.checkpoint()
    second_files, second_digest = _workspace_snapshot(workspace)
    second_checkpoint = workspace_resolver.checkpoint()
    if (
        first_files != second_files
        or first_digest != second_digest
        or first_checkpoint != second_checkpoint
    ):
        raise WorkflowValidationError(
            f"program workspace changed during {label} inventory/checkpoint capture"
        )
    return second_files, second_checkpoint


def _changed_paths(
    before: Mapping[str, str],
    after: Mapping[str, str],
    *,
    before_head: str,
    after_head: str,
) -> tuple[str, ...]:
    changed = {
        path for path in set(before) | set(after) if before.get(path) != after.get(path)
    }
    if before_head != after_head:
        changed.add(".git/HEAD")
    return tuple(sorted(changed))


def _boundary_problem(
    unit: ProgramUnit,
    boundaries: Sequence[Mapping[str, Any]],
    changed_paths: Sequence[str],
) -> Optional[str]:
    if not changed_paths:
        return None
    if unit.kind in {ProgramUnitKind.AUDIT, ProgramUnitKind.GATE_RUNNER}:
        return "read-only program worker changed the workspace"
    for changed in changed_paths:
        allowed = False
        for boundary in boundaries:
            path = boundary.get("path")
            kind = boundary.get("kind")
            if not isinstance(path, str):
                continue
            if kind == "file" and changed == path:
                allowed = True
            elif kind == "tree" and (changed == path or changed.startswith(path + "/")):
                allowed = True
            if allowed:
                break
        if not allowed:
            return f"program worker changed out-of-boundary path {changed!r}"
    return None


def _physical_boundary_problem(
    workspace: Path, boundaries: Sequence[Mapping[str, Any]]
) -> Optional[str]:
    """Reject link/reparse/special nodes anywhere in a writable boundary."""

    fs = ProjectFS(workspace)
    for boundary in boundaries:
        relative = boundary.get("path")
        kind = boundary.get("kind")
        if not isinstance(relative, str) or kind not in {"file", "tree"}:
            return "program writable boundary contract is malformed"
        try:
            if kind == "tree":
                fs.assert_tree_safe(relative)
            else:
                fs.assert_safe(relative)
        except (OSError, UnsafePathError, ValueError) as exc:
            return (
                f"program writable boundary {relative!r} contains or traverses a "
                f"symlink, reparse point, or special node: {exc}"
            )
    return None


def _state(project_root: Path) -> dict[str, Any]:
    document, error = pipeline.snapshot_document(project_root)
    if error or document is None:
        raise WorkflowValidationError(error or "program pipeline state is unavailable")
    program = document.get("program_execution")
    if not isinstance(program, dict):
        raise WorkflowValidationError("program execution binding is unavailable")
    return program


def _completed_attempts(program: Mapping[str, Any]) -> tuple[str, ...]:
    completed = program.get("completed_units")
    if not isinstance(completed, list):
        raise WorkflowValidationError("program completed-unit ledger is malformed")
    return tuple(str(item) for item in completed)


def _attempt_number(program: Mapping[str, Any], unit_id: str) -> int:
    attempts = program.get("unit_attempts")
    if not isinstance(attempts, list):
        raise WorkflowValidationError("program attempt ledger is malformed")
    return 1 + sum(
        1
        for item in attempts
        if isinstance(item, dict) and item.get("unit_id") == unit_id
    )


def _result(
    status: WorkflowExecutionStatus,
    program: Mapping[str, Any],
    attempts: Sequence[StageExecution],
    *,
    pending_gates: Sequence[str] = (),
    human_stop: Optional[HumanStopRequest] = None,
    messages: Sequence[str] = (),
) -> WorkflowExecutionResult:
    return WorkflowExecutionResult(
        status=status,
        completed_stages=_completed_attempts(program),
        skipped_stages=(),
        attempts=tuple(attempts),
        pending_gates=tuple(pending_gates),
        human_stop=human_stop,
        messages=tuple(messages),
    )


def _pause(
    project_root: Path,
    program: Mapping[str, Any],
    attempts: Sequence[StageExecution],
    *,
    reason: HumanStopReason,
    message: str,
    requested_action: str,
) -> WorkflowExecutionResult:
    stop = HumanStopRequest(reason, message, requested_action)
    ok, messages = pipeline.pause_for_human(
        project_root,
        reason=reason.value,
        message=message,
        requested_action=requested_action,
    )
    if not ok:
        raise WorkflowValidationError("; ".join(messages))
    return _result(
        WorkflowExecutionStatus.HUMAN_STOP,
        program,
        attempts,
        human_stop=stop,
        messages=messages,
    )


def _select_role(
    *,
    provider: Provider,
    candidates: Sequence[str],
    required_capabilities: Sequence[Capability],
    loader: FilesystemNativeRoleLoader,
) -> tuple[str, tuple[Capability, ...]]:
    """Select only a role whose complete native authority is Mode-E closed."""

    unavailable: list[str] = []
    required = set(required_capabilities)
    allowed = required | {Capability.MESSAGE}
    expected_permission = (
        PermissionClass.WORKSPACE_WRITE
        if Capability.FILE_WRITE in required
        else PermissionClass.READ_ONLY
    )
    for candidate in candidates:
        try:
            native = loader.load(provider, candidate)
        except RoleUnavailableError as exc:
            unavailable.append(str(exc))
            continue
        missing = required - set(native.capabilities)
        if missing:
            unavailable.append(
                f"{candidate}: missing "
                + ", ".join(sorted(item.value for item in missing))
            )
            continue
        effective = set(native.capabilities)
        excess = effective - allowed
        if excess:
            unavailable.append(
                f"{candidate}: excess Mode E authority "
                + ", ".join(sorted(item.value for item in excess))
            )
            continue
        if native.permission is not expected_permission:
            unavailable.append(
                f"{candidate}: permission {native.permission.value} exceeds the "
                f"Mode E {expected_permission.value} boundary"
            )
            continue
        if native.nested_delegation is not NestedDelegationPolicy.FORBIDDEN:
            unavailable.append(f"{candidate}: nested delegation is not forbidden")
            continue
        if native.mcp_server_ids:
            unavailable.append(f"{candidate}: native MCP access is not Mode E bounded")
            continue
        return candidate, tuple(sorted(effective, key=lambda item: item.value))
    raise UnsupportedCapabilityError(
        candidates[0] if candidates else "program-route", tuple(required)
    )


def _request_context(
    *,
    manifest: ProgramManifest,
    unit: ProgramUnit,
    boundaries: Sequence[Mapping[str, Any]],
    evidence_requirements: Mapping[str, Mapping[str, Any]],
    closeout_expectation: Mapping[str, Any] | None,
    context: str,
    runtime_context: str,
) -> str:
    boundary_lines = (
        "\n".join(f"- {item['kind']}: {item['path']}" for item in boundaries)
        or "- no writes are permitted"
    )
    governance = (
        f"Frozen program manifest {manifest.program_id} revision {manifest.revision} "
        f"sha256={manifest.digest} is the source of truth.\n"
        f"Unit: {unit.id}; lane: {unit.lane_id}; risk: {unit.risk.value}.\n"
        "Exact permitted boundaries:\n"
        f"{boundary_lines}\n"
        "If reality disagrees with the manifest or work requires any other path, "
        "stop and report; do not improvise. Return every declared artifact:// evidence ref."
    )
    ordinary = {
        artifact_id: {
            "validation_profile": requirement["validation_profile"],
            "required_fields": requirement["required_fields"],
        }
        for artifact_id in unit.evidence
        if isinstance((requirement := evidence_requirements.get(artifact_id)), Mapping)
    }
    evidence_contract = ""
    if ordinary:
        evidence_contract = (
            "Set the host result's output string to a JSON-serialized inner document "
            "with exact shape "
            '{"evidence": {<artifact-id>: <typed-document>}}; do not use a Markdown '
            "fence. The evidence map and documents must contain concrete results, never "
            "echoed artifact:// or stage:// placeholders. Frozen profiles/required fields: "
            + json.dumps(ordinary, sort_keys=True, separators=(",", ":"))
        )
        if closeout_expectation is not None:
            evidence_contract += (
                " The closeout document must repeat these authoritative fields "
                "byte-for-byte after JSON normalization: "
                + json.dumps(
                    closeout_expectation, sort_keys=True, separators=(",", ":")
                )
            )
    return "\n\n".join(
        part
        for part in (governance, evidence_contract, context, runtime_context)
        if part.strip()
    )


def _collect_one(
    dispatcher: Dispatcher,
    handle: DispatchHandle,
    *,
    timeout_seconds: float,
) -> DispatchResult:
    waited = dispatcher.wait((handle,), WaitMode.ALL, timeout_seconds=timeout_seconds)
    if waited.timed_out:
        dispatcher.cancel(handle, "program unit wait timeout")
    results = dispatcher.collect((handle,))
    if len(results) != 1 or results[0].handle != handle:
        raise DispatchAdapterError(
            "dispatcher returned a result for a different program attempt"
        )
    return results[0]


def _terminalize_interrupted_attempt(
    *,
    project_root: Path,
    workspace: Path,
    workspace_resolver: ManagedWorktreeResolver,
    dispatcher: Dispatcher,
    handle: DispatchHandle,
    unit: ProgramUnit,
    attempt: int,
    before_files: Mapping[str, str],
    before_checkpoint: Mapping[str, Any],
    reason: str,
) -> None:
    """Best-effort cancel, collect, and ledger a claimed interrupted attempt."""

    try:
        dispatcher.cancel(handle, reason)
    except BaseException:
        pass
    try:
        collected = dispatcher.collect((handle,))
        result = collected[0] if len(collected) == 1 else None
    except BaseException:
        result = None
    if result is None or result.handle != handle:
        result = DispatchResult(
            handle,
            DispatchStatus.CANCELLED,
            error="coordinator interrupted; host result was unavailable after cancel",
        )
    elif result.status is DispatchStatus.SUCCEEDED:
        result = DispatchResult(
            handle,
            DispatchStatus.CANCELLED,
            output=result.output,
            error=reason,
            evidence=result.evidence,
        )
    after_files, after_checkpoint = _stable_workspace_capture(
        workspace,
        workspace_resolver,
        label="interrupted-attempt post-state",
    )
    changed = _changed_paths(
        before_files,
        after_files,
        before_head=str(before_checkpoint["head_commit"]),
        after_head=str(after_checkpoint["head_commit"]),
    )
    boundary_digest = _canonical_digest(
        {
            "before": before_checkpoint["content_digest"],
            "after": after_checkpoint["content_digest"],
            "changed_paths": list(changed),
        }
    )
    program = _state(project_root)
    binding = program.get("binding")
    if not isinstance(binding, dict):
        raise WorkflowValidationError("program terminal artifact binding is malformed")
    output_path, output_artifact_sha = _persist_terminal_result(
        project_root,
        run_id=str(binding.get("run_id", "")),
        manifest_digest=str(binding.get("manifest_digest", "")),
        unit_id=unit.id,
        attempt=attempt,
        result=result,
    )
    pipeline.finish_program_unit(
        project_root,
        unit_id=unit.id,
        dispatch_id=handle.id,
        attempt=attempt,
        status=result.status.value,
        evidence=tuple(item.uri for item in result.evidence),
        evidence_verifications=(),
        output_sha256=(
            _sha256_bytes(result.output.encode("utf-8"))
            if result.output is not None
            else None
        ),
        output_path=output_path,
        output_artifact_sha256=output_artifact_sha,
        error=result.error or reason,
        post_workspace_checkpoint=after_checkpoint,
        changed_paths=changed,
        boundary_snapshot_digest=boundary_digest,
        output_token_upper_bound=len((result.output or "").encode("utf-8"))
        + len((result.error or "").encode("utf-8")),
    )


def _best_effort_terminalize_interrupted_attempt(
    *,
    project_root: Path,
    workspace: Path,
    workspace_resolver: ManagedWorktreeResolver,
    dispatcher: Dispatcher,
    handle: DispatchHandle,
    unit: ProgramUnit,
    attempt: int,
    before_files: Mapping[str, str],
    before_checkpoint: Mapping[str, Any],
    reason: str,
) -> None:
    """Never mask the triggering exception while attempting durable cleanup."""

    try:
        _terminalize_interrupted_attempt(
            project_root=project_root,
            workspace=workspace,
            workspace_resolver=workspace_resolver,
            dispatcher=dispatcher,
            handle=handle,
            unit=unit,
            attempt=attempt,
            before_files=before_files,
            before_checkpoint=before_checkpoint,
            reason=reason,
        )
    except BaseException:
        # A hard host/filesystem failure remains recoverable only through the
        # separately authenticated stale-attempt reconciliation contract.
        pass


def _bind(
    project_root: Path,
    *,
    manifest: ProgramManifest,
    manifest_relative: str,
    bound_workflow: BoundWorkflow,
    workspace_resolver: ManagedWorktreeResolver,
) -> dict[str, Any]:
    run, error = pipeline.snapshot_document(project_root)
    if error or run is None:
        raise WorkflowValidationError(error or "active pipeline state is unavailable")
    try:
        source_commit = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise WorkflowValidationError(
            f"cannot resolve program source commit: {exc}"
        ) from exc
    existing = run.get("program_execution")
    previous: Optional[str] = None
    if isinstance(existing, dict):
        existing_manifest = existing.get("manifest")
        if isinstance(existing_manifest, dict):
            if existing_manifest.get("digest") == manifest.digest:
                previous = existing.get("previous_manifest_digest")
            else:
                previous = str(existing_manifest.get("digest"))
    try:
        binding = validate_program_manifest_binding(
            manifest,
            run_id=str(run.get("run_id", "")),
            source_commit=source_commit,
            workflow_definition_digest=workflow_definition_digest(
                bound_workflow.definition
            ),
            gate_definition_digest=str(run.get("gate_definition_digest", "")),
            selection_digest=str(run.get("selection_digest", "")),
            ordered_gates=tuple(str(item) for item in run.get("ordered_gates", [])),
            expected_revision=manifest.revision,
            previous_manifest_digest=previous,
        )
    except ProgramManifestValidationError as exc:
        raise WorkflowValidationError(str(exc)) from exc
    frozen, bind_error = pipeline.bind_program_execution(
        project_root,
        manifest=manifest,
        manifest_path=manifest_relative,
        binding=binding,
        workspace=workspace_resolver.binding(),
    )
    if bind_error or frozen is None:
        raise WorkflowValidationError(
            bind_error or "program execution binding was not persisted"
        )
    return frozen


def execute_program_manifest(
    project_root: Path,
    *,
    provider: Provider,
    objective: str,
    bound_workflow: BoundWorkflow,
    manifest_path: Path,
    dispatcher: Dispatcher,
    workspace_resolver: ManagedWorktreeResolver,
    role_loader: FilesystemNativeRoleLoader,
    context: str = "",
    runtime_context: str = "",
    wait_timeout_seconds: float = 900.0,
) -> WorkflowExecutionResult:
    """Execute/resume safe Mode E units until a durable mandatory checkpoint."""

    root = Path(project_root).resolve(strict=True)
    manifest, manifest_relative = load_packaged_program_manifest(root, manifest_path)
    if manifest.objective != objective.strip():
        raise WorkflowValidationError(
            "program manifest objective differs from the active pipeline task"
        )
    _bind(
        root,
        manifest=manifest,
        manifest_relative=manifest_relative,
        bound_workflow=bound_workflow,
        workspace_resolver=workspace_resolver,
    )
    if (
        not isinstance(dispatcher, ProcessDispatcher)
        and getattr(dispatcher, "queued_spawn", False) is not True
    ):
        return _pause(
            root,
            _state(root),
            (),
            reason=HumanStopReason.UNSUPPORTED_REQUIRED_CAPABILITY,
            message=(
                "Mode E requires spawn to reserve a queued handle without starting "
                "worker execution before the durable claim"
            ),
            requested_action=(
                "use ProcessDispatcher or an injected contained dispatcher that "
                "explicitly attests queued_spawn=True"
            ),
        )
    workspace = workspace_resolver.ensure_workspace()
    unit_by_id = {unit.id: unit for unit in manifest.units}
    gate_by_id = {gate.id: gate for gate in manifest.gates}
    wave_by_id = {wave.id: wave for wave in manifest.waves}
    observed_attempts: list[StageExecution] = []

    while True:
        program = _state(root)
        if program.get("status") == "completed":
            return _result(
                WorkflowExecutionStatus.SUCCEEDED, program, observed_attempts
            )
        completed = set(_completed_attempts(program))
        checkpointed = {
            item.get("gate_id")
            for item in program.get("gate_checkpoints", [])
            if isinstance(item, dict)
        }
        next_gate_id = next(
            (
                str(gate_id)
                for gate_id in program.get("ordered_program_gates", [])
                if gate_id not in checkpointed
            ),
            None,
        )
        if next_gate_id is not None:
            gate = gate_by_id[next_gate_id]
            if gate.owner_unit_id in completed:
                owner_attempts = [
                    item
                    for item in program.get("unit_attempts", [])
                    if isinstance(item, dict)
                    and item.get("unit_id") == gate.owner_unit_id
                    and item.get("status") == "succeeded"
                ]
                if len(owner_attempts) != 1 or not isinstance(
                    owner_attempts[0].get("evidence_verifications"), list
                ):
                    raise WorkflowValidationError(
                        "program gate owner has no unique verified evidence ledger"
                    )
                by_id = {
                    item.get("artifact_id"): item
                    for item in owner_attempts[0]["evidence_verifications"]
                    if isinstance(item, dict)
                }
                verification_records = [
                    dict(by_id[artifact_id]) for artifact_id in gate.evidence
                ]
                if gate.kind.value == "pipeline":
                    run, error = pipeline.snapshot_document(root)
                    if error or run is None:
                        raise WorkflowValidationError(
                            error or "pipeline state unavailable"
                        )
                    if gate.id not in {
                        item.get("gate")
                        for item in run.get("gate_history", [])
                        if isinstance(item, dict)
                        and item.get("status")
                        in {"passed", "not-applicable", "accepted-risk"}
                    }:
                        return _result(
                            WorkflowExecutionStatus.WAITING_GATE,
                            program,
                            observed_attempts,
                            pending_gates=(gate.id,),
                        )
                ok, messages = pipeline.checkpoint_program_gate(
                    root,
                    gate_id=gate.id,
                    verification_records=verification_records,
                )
                if not ok:
                    raise WorkflowValidationError("; ".join(messages))
                continue
        ordered_units = [str(item) for item in program.get("ordered_units", [])]
        pending_unit_id = next(
            (unit_id for unit_id in ordered_units if unit_id not in completed), None
        )
        if pending_unit_id is None:
            ok, messages = pipeline.complete_program_execution(root)
            if not ok:
                unresolved = [
                    str(item)
                    for item in program.get("ordered_program_gates", [])
                    if item
                    not in {
                        checkpoint.get("gate_id")
                        for checkpoint in program.get("gate_checkpoints", [])
                        if isinstance(checkpoint, dict)
                    }
                ]
                if unresolved:
                    return _result(
                        WorkflowExecutionStatus.WAITING_GATE,
                        program,
                        observed_attempts,
                        pending_gates=unresolved[:1],
                        messages=messages,
                    )
                raise WorkflowValidationError("; ".join(messages))
            return _result(
                WorkflowExecutionStatus.SUCCEEDED,
                _state(root),
                observed_attempts,
                messages=messages,
            )

        unit = unit_by_id[pending_unit_id]
        wave = wave_by_id[unit.wave_id]
        if not set(unit.dependencies).issubset(completed):
            raise WorkflowValidationError(
                f"program unit {unit.id!r} has unresolved dependencies"
            )

        if wave.kind is ProgramWaveKind.EXECUTION and not program.get(
            "audit_gate_completed"
        ):
            return _pause(
                root,
                program,
                observed_attempts,
                reason=HumanStopReason.CONFLICTING_EVIDENCE,
                message="Wave 0 audit verification is incomplete",
                requested_action="complete the frozen audit gate before any execution unit",
            )

        safeguard_records: tuple[dict[str, Any], ...]
        try:
            safeguard_records = _unit_safeguards(root, unit)
        except WorkflowValidationError as exc:
            return _pause(
                root,
                program,
                observed_attempts,
                reason=HumanStopReason.CONFLICTING_EVIDENCE,
                message=str(exc),
                requested_action="restore the exact declared artifact/tag and resume",
            )
        if safeguard_records:
            ok, messages = pipeline.record_program_safeguards(
                root, unit_id=unit.id, records=safeguard_records
            )
            if not ok:
                raise WorkflowValidationError("; ".join(messages))

        if unit.irreversible:
            return _pause(
                root,
                _state(root),
                observed_attempts,
                reason=HumanStopReason.IRREVERSIBLE_OPERATION,
                message=(
                    f"irreversible program unit {unit.id!r} is frozen and its "
                    "content-addressed safeguards verify, but no scoped consume-once "
                    "approval broker is integrated"
                ),
                requested_action=(
                    "do not execute this unit through Mode E; integrate an out-of-worker "
                    "approval consumer bound to the exact action, inventory, restore point, "
                    "provider, route, attempt, and workspace checkpoint"
                ),
            )

        unit_contract = program.get("units", {}).get(unit.id)
        if not isinstance(unit_contract, dict):
            raise WorkflowValidationError("program unit contract is unavailable")
        raw_capabilities = unit_contract.get("required_capabilities")
        candidates = unit_contract.get("route_candidates")
        boundaries = unit_contract.get("boundaries")
        if (
            not isinstance(raw_capabilities, list)
            or not isinstance(candidates, list)
            or not isinstance(boundaries, list)
        ):
            raise WorkflowValidationError(
                "program unit route/boundary contract is malformed"
            )
        typed_boundaries = tuple(item for item in boundaries if isinstance(item, dict))
        if len(typed_boundaries) != len(boundaries):
            raise WorkflowValidationError("program unit boundary contract is malformed")
        program_evidence_requirements = program.get("evidence_requirements")
        if not isinstance(program_evidence_requirements, dict):
            raise WorkflowValidationError(
                "program evidence requirement contract is malformed"
            )
        capability_floor = tuple(Capability(str(value)) for value in raw_capabilities)
        try:
            route, effective_capabilities = _select_role(
                provider=provider,
                candidates=tuple(str(value) for value in candidates),
                required_capabilities=capability_floor,
                loader=role_loader,
            )
        except (RoleUnavailableError, UnsupportedCapabilityError) as exc:
            return _pause(
                root,
                program,
                observed_attempts,
                reason=HumanStopReason.UNSUPPORTED_REQUIRED_CAPABILITY,
                message=str(exc),
                requested_action="install a route that attests the frozen unit capabilities",
            )
        containment_required = bool(
            {Capability.FILE_WRITE, Capability.SHELL} & set(effective_capabilities)
        )
        if containment_required and not isinstance(
            dispatcher, ProgramBoundaryContainedDispatcher
        ):
            return _pause(
                root,
                program,
                observed_attempts,
                reason=HumanStopReason.UNSUPPORTED_REQUIRED_CAPABILITY,
                message=(
                    f"program unit {unit.id!r} requires a physically enforced "
                    "no-follow write boundary, but the selected dispatcher cannot "
                    "attest one for its queued handle"
                ),
                requested_action=(
                    "resume with a trusted contained dispatcher implementing the "
                    "typed program-boundary attestation contract"
                ),
            )

        closeout_expectation: Mapping[str, Any] | None = None
        if unit.kind is ProgramUnitKind.KNOWLEDGE_CLOSEOUT:
            outer_run, outer_error = pipeline.snapshot_document(root)
            if outer_error or outer_run is None:
                raise WorkflowValidationError(
                    outer_error or "pipeline state is unavailable for closeout"
                )
            closeout_gates, closeout_risks, closeout_problem = (
                pipeline._program_closeout_projection(  # noqa: SLF001
                    outer_run, program
                )
            )
            if closeout_problem or closeout_gates is None or closeout_risks is None:
                raise WorkflowValidationError(
                    closeout_problem or "program closeout ledger is unavailable"
                )
            closeout_expectation = {
                "gates": closeout_gates,
                "accepted-risks": closeout_risks,
            }
        unit_context = _request_context(
            manifest=manifest,
            unit=unit,
            boundaries=typed_boundaries,
            evidence_requirements=program_evidence_requirements,
            closeout_expectation=closeout_expectation,
            context="\n\n".join(
                part
                for part in (context, _dependency_handoff(root, program, unit))
                if part.strip()
            ),
            runtime_context=runtime_context,
        )
        request = DispatchRequest(
            route=route,
            objective=f"Program unit {unit.id}: {unit.objective}",
            lane=unit.lane_id,
            dependencies=tuple(
                SymbolicRef.parse(f"stage://{item}") for item in unit.dependencies
            ),
            evidence=tuple(
                SymbolicRef.parse(f"artifact://{item}") for item in unit.evidence
            ),
            retry_budget="orchestration",
            context=unit_context,
            required_capabilities=effective_capabilities,
            workspace=str(workspace),
        )
        prompt_bound = len((request.objective + "\n" + request.context).encode("utf-8"))
        before_files, before_checkpoint = _stable_workspace_capture(
            workspace,
            workspace_resolver,
            label="pre-dispatch state",
        )
        if containment_required:
            physical_problem = _physical_boundary_problem(workspace, typed_boundaries)
            if physical_problem is not None:
                return _pause(
                    root,
                    program,
                    observed_attempts,
                    reason=HumanStopReason.UNSUPPORTED_REQUIRED_CAPABILITY,
                    message=physical_problem,
                    requested_action=(
                        "remove the unsafe filesystem node without changing the frozen "
                        "boundary, then resume with a physically contained dispatcher"
                    ),
                )
        handle: Optional[DispatchHandle] = None
        claimed = False
        attempt_number = _attempt_number(program, unit.id)
        try:
            handle = dispatcher.spawn(request)
            effective_provider = handle.provider or provider.value
            if effective_provider != provider.value or handle.route != route:
                raise DispatchAdapterError(
                    "program dispatch handle changed the selected provider or route"
                )
            if (
                handle.required_capabilities != effective_capabilities
                or handle.attested_capabilities != effective_capabilities
            ):
                raise DispatchAdapterError(
                    "program dispatch handle did not attest the exact selected native "
                    "capability closure"
                )
            containment_attestation: Mapping[str, Any] | None = None
            if containment_required:
                assert isinstance(dispatcher, ProgramBoundaryContainedDispatcher)
                attestation = dispatcher.attest_program_boundary_containment(
                    request,
                    handle,
                    unit_id=unit.id,
                    workspace_target=str(program["workspace"]["target_path"]),
                    boundary_digest=_canonical_digest(typed_boundaries),
                    pre_workspace_checkpoint_digest=str(
                        before_checkpoint["content_digest"]
                    ),
                    policy=(
                        "bounded-writes" if typed_boundaries else "deny-all-writes"
                    ),
                )
                if not isinstance(attestation, ProgramBoundaryContainmentAttestation):
                    raise DispatchAdapterError(
                        "contained dispatcher returned an untyped boundary attestation"
                    )
                containment_attestation = attestation.to_dict()
            ok, messages = pipeline.claim_program_unit(
                root,
                unit_id=unit.id,
                provider=provider.value,
                route=route,
                dispatch_id=handle.id,
                attempt=attempt_number,
                required_capabilities=tuple(
                    item.value for item in effective_capabilities
                ),
                attested_capabilities=tuple(
                    item.value for item in handle.attested_capabilities
                ),
                pre_workspace_checkpoint=before_checkpoint,
                prompt_token_upper_bound=prompt_bound,
                physical_boundary_containment=containment_attestation,
            )
            if not ok:
                dispatcher.cancel(handle, "program unit ledger claim failed")
                try:
                    dispatcher.collect((handle,))
                except BaseException:
                    pass
                if any(
                    "budget" in message or "ceiling" in message for message in messages
                ):
                    return _pause(
                        root,
                        program,
                        observed_attempts,
                        reason=HumanStopReason.RETRY_BUDGET_EXHAUSTED,
                        message="; ".join(messages),
                        requested_action="review the frozen wave budget and issue a child manifest revision",
                    )
                raise WorkflowValidationError("; ".join(messages))
            claimed = True
            result = _collect_one(
                dispatcher, handle, timeout_seconds=wait_timeout_seconds
            )
        except BaseException:
            if handle is not None and claimed:
                _best_effort_terminalize_interrupted_attempt(
                    project_root=root,
                    workspace=workspace,
                    workspace_resolver=workspace_resolver,
                    dispatcher=dispatcher,
                    handle=handle,
                    unit=unit,
                    attempt=attempt_number,
                    before_files=before_files,
                    before_checkpoint=before_checkpoint,
                    reason="program coordinator interrupted",
                )
            elif handle is not None:
                try:
                    dispatcher.cancel(handle, "program dispatch failed before claim")
                    dispatcher.collect((handle,))
                except BaseException:
                    pass
            raise

        assert handle is not None
        try:
            post_physical_problem = (
                _physical_boundary_problem(workspace, typed_boundaries)
                if containment_required
                else None
            )
            after_files, after_checkpoint = _stable_workspace_capture(
                workspace,
                workspace_resolver,
                label="post-dispatch state",
            )
            changed = _changed_paths(
                before_files,
                after_files,
                before_head=str(before_checkpoint["head_commit"]),
                after_head=str(after_checkpoint["head_commit"]),
            )
            boundary_digest = _canonical_digest(
                {
                    "before": before_checkpoint["content_digest"],
                    "after": after_checkpoint["content_digest"],
                    "changed_paths": list(changed),
                }
            )
        except BaseException:
            _best_effort_terminalize_interrupted_attempt(
                project_root=root,
                workspace=workspace,
                workspace_resolver=workspace_resolver,
                dispatcher=dispatcher,
                handle=handle,
                unit=unit,
                attempt=attempt_number,
                before_files=before_files,
                before_checkpoint=before_checkpoint,
                reason="program coordinator failed during post-state capture",
            )
            raise
        effective_result = result
        evidence_verifications: tuple[dict[str, Any], ...] = ()
        returned_evidence = {item.uri for item in result.evidence}
        required_evidence = {f"artifact://{item}" for item in unit.evidence}
        boundary_error = _boundary_problem(
            unit,
            typed_boundaries,
            changed,
        )
        preverification_error: Optional[str] = None
        if result.status is DispatchStatus.SUCCEEDED:
            if returned_evidence != required_evidence:
                preverification_error = (
                    "program worker did not return the exact declared evidence set"
                )
            elif post_physical_problem is not None:
                preverification_error = post_physical_problem
            elif boundary_error is not None:
                preverification_error = boundary_error
        if preverification_error is not None:
            effective_result = DispatchResult(
                result.handle,
                DispatchStatus.FAILED,
                output=result.output,
                error=preverification_error,
                evidence=result.evidence,
            )
        elif result.status is DispatchStatus.SUCCEEDED:
            try:
                program_binding = program.get("binding")
                evidence_requirements = program.get("evidence_requirements")
                blocking_severities = program.get("program_blocking_severities")
                if (
                    not isinstance(program_binding, dict)
                    or not isinstance(evidence_requirements, dict)
                    or not isinstance(blocking_severities, list)
                ):
                    raise WorkflowValidationError(
                        "program evidence/workflow binding is malformed"
                    )
                evidence_verifications = _evidence_records(
                    root,
                    manifest,
                    manifest_relative,
                    unit,
                    result,
                    attempt_number,
                    str(program_binding["run_id"]),
                    evidence_requirements,
                    tuple(str(item) for item in blocking_severities),
                    str(after_checkpoint["content_digest"]),
                )
            except WorkflowValidationError as exc:
                effective_result = DispatchResult(
                    result.handle,
                    DispatchStatus.FAILED,
                    output=result.output,
                    error=f"program evidence verification failed: {exc}",
                    evidence=result.evidence,
                )
                evidence_verifications = ()
            except BaseException:
                _best_effort_terminalize_interrupted_attempt(
                    project_root=root,
                    workspace=workspace,
                    workspace_resolver=workspace_resolver,
                    dispatcher=dispatcher,
                    handle=handle,
                    unit=unit,
                    attempt=attempt_number,
                    before_files=before_files,
                    before_checkpoint=before_checkpoint,
                    reason="program coordinator failed during evidence persistence",
                )
                raise
        try:
            terminal_binding = program.get("binding")
            if not isinstance(terminal_binding, dict):
                raise WorkflowValidationError(
                    "program terminal artifact binding is malformed"
                )
            result_artifact_path, result_artifact_digest = _persist_terminal_result(
                root,
                run_id=str(terminal_binding.get("run_id", "")),
                manifest_digest=str(terminal_binding.get("manifest_digest", "")),
                unit_id=unit.id,
                attempt=attempt_number,
                result=effective_result,
            )
            output_digest = (
                _sha256_bytes(effective_result.output.encode("utf-8"))
                if effective_result.output is not None
                else None
            )
            output_bound = len((effective_result.output or "").encode("utf-8")) + len(
                (effective_result.error or "").encode("utf-8")
            )
            ok, finish_messages = pipeline.finish_program_unit(
                root,
                unit_id=unit.id,
                dispatch_id=effective_result.handle.id,
                attempt=attempt_number,
                status=effective_result.status.value,
                evidence=tuple(item.uri for item in effective_result.evidence),
                evidence_verifications=evidence_verifications,
                output_sha256=output_digest,
                output_path=result_artifact_path,
                output_artifact_sha256=result_artifact_digest,
                error=effective_result.error,
                post_workspace_checkpoint=after_checkpoint,
                changed_paths=changed,
                boundary_snapshot_digest=boundary_digest,
                output_token_upper_bound=output_bound,
            )
        except BaseException:
            _best_effort_terminalize_interrupted_attempt(
                project_root=root,
                workspace=workspace,
                workspace_resolver=workspace_resolver,
                dispatcher=dispatcher,
                handle=handle,
                unit=unit,
                attempt=attempt_number,
                before_files=before_files,
                before_checkpoint=before_checkpoint,
                reason="program coordinator failed before terminal acknowledgement",
            )
            raise
        observed_attempts.append(
            StageExecution(
                unit.id,
                route,
                effective_result.handle,
                effective_result.status,
                effective_result.evidence,
                effective_result.error,
                StageArtifactRef(
                    result_artifact_path,
                    result_artifact_digest,
                    False,
                    "program-terminal-result",
                ),
            )
        )
        if not ok:
            _best_effort_terminalize_interrupted_attempt(
                project_root=root,
                workspace=workspace,
                workspace_resolver=workspace_resolver,
                dispatcher=dispatcher,
                handle=handle,
                unit=unit,
                attempt=attempt_number,
                before_files=before_files,
                before_checkpoint=before_checkpoint,
                reason="program terminal acknowledgement was rejected",
            )
            return _result(
                WorkflowExecutionStatus.FAILED,
                _state(root),
                observed_attempts,
                messages=finish_messages,
            )
        if effective_result.human_stop is not None:
            return _pause(
                root,
                _state(root),
                observed_attempts,
                reason=effective_result.human_stop.reason,
                message=effective_result.human_stop.message,
                requested_action=effective_result.human_stop.requested_action,
            )
        if effective_result.status is not DispatchStatus.SUCCEEDED:
            return _result(
                WorkflowExecutionStatus.FAILED,
                _state(root),
                observed_attempts,
                messages=finish_messages,
            )


__all__ = [
    "ProgramBoundaryContainedDispatcher",
    "ProgramBoundaryContainmentAttestation",
    "execute_program_manifest",
    "load_packaged_program_manifest",
    "program_artifact_path",
]
