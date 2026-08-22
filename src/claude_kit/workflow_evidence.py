"""Provider-neutral typed evidence for managed workflow modes A--D.

The host adapters return symbolic evidence references for routing, but those
references are not evidence.  This module defines the exact JSON envelope and
the closed validation profiles that turn a successful stage result into
content-addressable evidence owned by the coordinator.

Mode E deliberately keeps its separately frozen program evidence contract.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import fields, is_dataclass
from enum import Enum
from typing import Any, Mapping, Sequence

from claude_kit.workflows import (
    EvidenceRequirement,
    FindingsPolicy,
    WorkflowDefinition,
)

EVIDENCE_CONTRACT_VERSION = 1
MAX_EVIDENCE_ENVELOPE_BYTES = 4 * 1024 * 1024

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_FINDING_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_SYMBOLIC_RE = re.compile(
    r"(?:artifact|agent|skill|rule|state|stage|lane|gate|program)://[^\s]+",
    re.IGNORECASE,
)
_CANONICAL_PROFILE_FIELDS: dict[str, tuple[str, tuple[str, ...]]] = {
    "scope-record": ("artifact", ("mode", "surfaces", "constraints", "risks")),
    "specification": (
        "artifact",
        ("outcome", "acceptance-criteria", "non-goals", "risks"),
    ),
    "architecture-plan": (
        "artifact",
        ("boundaries", "dependencies", "interfaces", "verification"),
    ),
    "review-verdict": (
        "verdict",
        ("status", "reviewer", "findings", "evidence"),
    ),
    "command-evidence": ("command-output", ("command", "exit-status", "output")),
    "test-report": (
        "findings-report",
        ("scope", "passed", "failed", "skipped", "residual-risk"),
    ),
    "security-report": (
        "findings-report",
        ("scanners", "findings", "dispositions", "residual-risk"),
    ),
    "delivery-report": (
        "findings-report",
        ("checks", "rollback", "residual-risk"),
    ),
    "human-approval": ("approval", ("approver", "scope", "decision", "timestamp")),
    "frozen-manifest": (
        "manifest",
        ("lanes", "boundaries", "waves", "owners", "gates", "digest"),
    ),
    "restore-point": ("restore-point", ("scope", "reference", "verification")),
    "closeout-record": (
        "artifact",
        ("outcome", "gates", "accepted-risks", "learnings"),
    ),
}


class EvidenceValidationError(ValueError):
    """Raised when managed evidence cannot support a successful transition."""


def _portable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _portable(getattr(value, field.name)) for field in fields(value)
        }
    if isinstance(value, Mapping):
        return {str(key): _portable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_portable(item) for item in value]
    return value


def requirement_document(
    requirement: EvidenceRequirement | Mapping[str, Any],
) -> dict[str, Any]:
    """Return the exact serializable contract for one evidence identifier."""

    raw = _portable(requirement)
    if not isinstance(raw, dict):
        raise EvidenceValidationError("evidence requirement must be an object")
    evidence_id = raw.get("id") or raw.get("validation_profile")
    kind = raw.get("kind")
    required = raw.get("required_fields")
    project_contained = raw.get("project_contained")
    if (
        not isinstance(evidence_id, str)
        or not evidence_id
        or not isinstance(kind, str)
        or not isinstance(required, list)
        or not required
        or any(not isinstance(item, str) or not item for item in required)
        or project_contained is not True
    ):
        raise EvidenceValidationError("evidence requirement contract is malformed")
    return {
        "kind": kind,
        "validation_profile": evidence_id,
        "required_fields": list(required),
        "project_contained": True,
    }


def findings_policy_document(
    policy: FindingsPolicy | Mapping[str, Any],
) -> dict[str, Any]:
    """Return the complete portable findings policy without descriptive metadata."""

    raw = _portable(policy)
    if not isinstance(raw, dict):
        raise EvidenceValidationError("findings policy must be an object")
    accepted = raw.get("accepted_risk")
    if not isinstance(accepted, dict):
        raise EvidenceValidationError("accepted-risk policy is malformed")
    severity_order = list(raw.get("severity_order", []))
    blocking_severities = list(raw.get("blocking_severities", []))
    pass_requires_zero = list(raw.get("pass_requires_zero", []))
    document: dict[str, Any] = {
        "severity_order": severity_order,
        "blocking_severities": blocking_severities,
        "pass_requires_zero": pass_requires_zero,
        "critical_high_waivable": raw.get("critical_high_waivable"),
        "uncited_finding": raw.get("uncited_finding"),
        "accepted_risk": {
            "allowed_severities": list(accepted.get("allowed_severities", [])),
            "required_fields": list(accepted.get("required_fields", [])),
        },
    }
    if (
        not severity_order
        or any(not isinstance(item, str) or not item for item in severity_order)
        or not set(blocking_severities).issubset(severity_order)
        or not set(pass_requires_zero).issubset(severity_order)
        or document["critical_high_waivable"] is not False
        or document["uncited_finding"] not in {"incomplete", "blocking", "reject"}
    ):
        raise EvidenceValidationError("findings policy contract is malformed")
    return document


def managed_evidence_projection(
    workflow: WorkflowDefinition,
    *,
    active_stages: Sequence[str],
    ordered_gates: Sequence[str],
) -> dict[str, Any]:
    """Freeze the exact A--D stage, gate, profile, and findings contract."""

    stage_by_id = workflow.stage_by_id
    stage_evidence = {
        stage_id: list(stage_by_id[stage_id].evidence) for stage_id in active_stages
    }
    gate_evidence = {
        gate_id: list(workflow.gates[gate_id].evidence) for gate_id in ordered_gates
    }
    used = {
        evidence_id
        for values in (*stage_evidence.values(), *gate_evidence.values())
        for evidence_id in values
    }
    requirements = {
        evidence_id: requirement_document(workflow.evidence_requirements[evidence_id])
        for evidence_id in sorted(used)
    }
    return {
        "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
        "active_stage_evidence": stage_evidence,
        "gate_evidence": gate_evidence,
        "evidence_requirements": requirements,
        "findings_policy": findings_policy_document(workflow.findings_policy),
    }


def _content_problem(
    value: Any, *, label: str, allow_empty_collection: bool = False
) -> str | None:
    if isinstance(value, str):
        if not value.strip():
            return f"{label} must be content-bearing"
        if _SYMBOLIC_RE.fullmatch(value.strip()):
            return f"{label} must not be an echoed symbolic reference"
        if len(value.encode("utf-8")) > MAX_EVIDENCE_ENVELOPE_BYTES:
            return f"{label} is too large"
        return None
    if isinstance(value, bool) or isinstance(value, int) or value is None:
        return None
    if isinstance(value, float):
        return None if math.isfinite(value) else f"{label} contains a non-finite number"
    if isinstance(value, list):
        if not value and not allow_empty_collection:
            return f"{label} must not be empty"
        for index, item in enumerate(value):
            problem = _content_problem(item, label=f"{label}[{index}]")
            if problem:
                return problem
        return None
    if isinstance(value, dict):
        if not value and not allow_empty_collection:
            return f"{label} must not be empty"
        for key, item in value.items():
            if not isinstance(key, str) or not key.strip():
                return f"{label} contains an invalid field name"
            problem = _content_problem(item, label=f"{label}.{key}")
            if problem:
                return problem
        return None
    return f"{label} has an unsupported JSON value"


def _text_array_problem(value: Any, *, label: str, allow_empty: bool) -> str | None:
    if not isinstance(value, list) or (not value and not allow_empty):
        qualifier = "an array" if allow_empty else "a non-empty array"
        return f"{label} must be {qualifier} of strings"
    for index, item in enumerate(value):
        if not isinstance(item, str):
            return f"{label}[{index}] must be a string"
        problem = _content_problem(item, label=f"{label}[{index}]")
        if problem:
            return problem
    return None


def _structured_array_problem(
    value: Any, *, label: str, allow_empty: bool
) -> str | None:
    if not isinstance(value, list) or (not value and not allow_empty):
        qualifier = "an array" if allow_empty else "a non-empty array"
        return f"{label} must be {qualifier}"
    for index, item in enumerate(value):
        if item is None or isinstance(item, (bool, int, float)):
            return f"{label}[{index}] must be a content-bearing string or object"
        problem = _content_problem(item, label=f"{label}[{index}]")
        if problem:
            return problem
    return None


def _citation_problem(value: Any, *, label: str) -> str | None:
    if isinstance(value, str):
        return _content_problem(value, label=label)
    if not isinstance(value, dict):
        return f"{label} must be a citation string or digest-bound object"
    if set(value) == {"artifact_id", "sha256"}:
        identity = value.get("artifact_id")
    elif set(value) == {"path", "sha256"}:
        identity = value.get("path")
    else:
        return f"{label} must contain an exact identity and sha256 binding"
    if not isinstance(identity, str):
        return f"{label} identity must be a string"
    problem = _content_problem(identity, label=f"{label}.identity")
    if problem:
        return problem
    digest = value.get("sha256")
    if not isinstance(digest, str) or not _DIGEST_RE.fullmatch(digest):
        return f"{label}.sha256 must be a lowercase sha256 digest"
    return None


def _citations_problem(
    value: Any, *, label: str, allow_empty: bool = False
) -> str | None:
    if not isinstance(value, list) or (not value and not allow_empty):
        return f"{label} must be a {'possibly empty' if allow_empty else 'non-empty'} citation array"
    for index, item in enumerate(value):
        problem = _citation_problem(item, label=f"{label}[{index}]")
        if problem:
            return problem
    return None


def _finding_problem(
    value: Any, *, label: str, findings_policy: Mapping[str, Any]
) -> str | None:
    if not isinstance(value, dict):
        return f"{label} must be a structured object"
    required = {"severity", "disposition", "evidence"}
    if not required.issubset(value):
        return f"{label} must contain severity, disposition, and evidence"
    raw_id = value.get("id", value.get("finding-id"))
    if not isinstance(raw_id, str) or not _FINDING_ID_RE.fullmatch(raw_id):
        return f"{label} must contain a stable id or finding-id"
    allowed = set(findings_policy.get("severity_order", [])) | {"cosmetic"}
    severity = value.get("severity")
    if not isinstance(severity, str) or severity.strip().lower() not in allowed:
        return f"{label} has an invalid severity"
    disposition = value.get("disposition")
    if not isinstance(disposition, str):
        return f"{label} disposition must be a string"
    problem = _content_problem(disposition, label=f"{label}.disposition")
    if problem:
        return problem
    return _citations_problem(value.get("evidence"), label=f"{label}.evidence")


def _findings_problem(
    value: Any, *, label: str, findings_policy: Mapping[str, Any]
) -> str | None:
    if not isinstance(value, list):
        return f"{label} must be an array"
    seen: set[str] = set()
    for index, finding in enumerate(value):
        problem = _finding_problem(
            finding, label=f"{label}[{index}]", findings_policy=findings_policy
        )
        if problem:
            return problem
        assert isinstance(finding, dict)
        finding_id = str(finding.get("id", finding.get("finding-id")))
        if finding_id in seen:
            return f"{label} contains duplicate finding id {finding_id!r}"
        seen.add(finding_id)
    return None


def _profile_problem(
    document: Mapping[str, Any],
    profile: str,
    *,
    mode: str | None,
    findings_policy: Mapping[str, Any],
) -> str | None:
    if profile == "specification":
        outcome = document.get("outcome")
        if not isinstance(outcome, str):
            return "specification outcome must be a string"
        problem = _content_problem(outcome, label="specification outcome")
        if problem:
            return problem
        for field in ("acceptance-criteria", "non-goals", "risks"):
            problem = _text_array_problem(
                document.get(field),
                label=f"specification {field}",
                allow_empty=field != "acceptance-criteria",
            )
            if problem:
                return problem
        return None
    if profile == "architecture-plan":
        for field in ("boundaries", "dependencies", "interfaces", "verification"):
            problem = _structured_array_problem(
                document.get(field),
                label=f"architecture {field}",
                allow_empty=field in {"dependencies", "interfaces"},
            )
            if problem:
                return problem
        return None
    if profile == "scope-record":
        if mode is not None and document.get("mode") != mode:
            return f"scope evidence must bind managed Mode {mode}"
        for field in ("surfaces", "constraints", "risks"):
            problem = _text_array_problem(
                document.get(field),
                label=f"scope evidence {field}",
                allow_empty=field != "surfaces",
            )
            if problem:
                return problem
        return None
    if profile == "review-verdict":
        status = document.get("status")
        if not isinstance(status, str) or status.strip().lower() not in {
            "pass",
            "fail",
        }:
            return "review verdict status must be PASS or FAIL"
        if not isinstance(document.get("reviewer"), str):
            return "review verdict reviewer must be a string"
        reviewer_problem = _content_problem(
            document["reviewer"], label="review verdict reviewer"
        )
        if reviewer_problem:
            return reviewer_problem
        problem = _findings_problem(
            document.get("findings"),
            label="review verdict findings",
            findings_policy=findings_policy,
        )
        if problem:
            return problem
        return _citations_problem(
            document.get("evidence"), label="review verdict evidence"
        )
    if profile == "command-evidence":
        command = document.get("command")
        exit_status = document.get("exit-status")
        output = document.get("output")
        if (
            not isinstance(command, str)
            or not isinstance(exit_status, int)
            or isinstance(exit_status, bool)
            or not isinstance(output, str)
        ):
            return "command evidence fields have invalid types"
        problem = _content_problem(command, label="command evidence command")
        if problem:
            return problem
        if output and _SYMBOLIC_RE.fullmatch(output.strip()):
            return "command evidence output must not echo a symbolic reference"
        return None
    if profile == "test-report":
        for field in ("passed", "failed", "skipped"):
            value = document.get(field)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                return "test report counts must be non-negative integers"
        if int(document["passed"]) + int(document["failed"]) == 0:
            return "test report must contain at least one executed test"
        scope_problem = _text_array_problem(
            document.get("scope"), label="test report scope", allow_empty=False
        )
        if scope_problem:
            return scope_problem
        return _text_array_problem(
            document.get("residual-risk"),
            label="test report residual-risk",
            allow_empty=True,
        )
    if profile == "security-report":
        problem = _text_array_problem(
            document.get("scanners"), label="security scanners", allow_empty=False
        )
        if problem:
            return problem
        findings = document.get("findings")
        if not isinstance(findings, list):
            return "security findings must be an array"
        problem = _findings_problem(
            findings, label="security findings", findings_policy=findings_policy
        )
        if problem:
            return problem
        dispositions = document.get("dispositions")
        if not isinstance(dispositions, list):
            return "security dispositions must be an array"
        finding_ids = {
            str(item.get("id", item.get("finding-id")))
            for item in findings
            if isinstance(item, dict)
        }
        disposition_ids: list[str] = []
        for index, disposition in enumerate(dispositions):
            if not isinstance(disposition, dict) or not {
                "finding-id",
                "disposition",
                "evidence",
            }.issubset(disposition):
                return f"security disposition[{index}] must bind a finding, decision, and evidence"
            finding_id = disposition.get("finding-id")
            if not isinstance(finding_id, str) or not _FINDING_ID_RE.fullmatch(
                finding_id
            ):
                return f"security disposition[{index}] has an invalid finding-id"
            if not isinstance(disposition.get("disposition"), str):
                return f"security disposition[{index}] decision must be a string"
            problem = _content_problem(
                disposition["disposition"], label=f"security disposition[{index}]"
            )
            if problem:
                return problem
            problem = _citations_problem(
                disposition.get("evidence"),
                label=f"security disposition[{index}].evidence",
            )
            if problem:
                return problem
            disposition_ids.append(finding_id)
        if (
            len(disposition_ids) != len(set(disposition_ids))
            or set(disposition_ids) != finding_ids
        ):
            return "security dispositions must exactly cover every unique finding id"
        return _text_array_problem(
            document.get("residual-risk"),
            label="security residual-risk",
            allow_empty=True,
        )
    if profile == "delivery-report":
        problem = _structured_array_problem(
            document.get("checks"), label="delivery report checks", allow_empty=False
        )
        if problem:
            return problem
        rollback = document.get("rollback")
        if not isinstance(rollback, dict) or not rollback:
            return "delivery report rollback must be a structured object"
        for field, value in rollback.items():
            if not isinstance(field, str) or not field.strip():
                return "delivery report rollback has an invalid field name"
            if value is None or isinstance(value, (bool, int, float)):
                return f"delivery report rollback.{field} must be content-bearing"
        problem = _content_problem(rollback, label="delivery report rollback")
        if problem:
            return problem
        findings = document.get("findings")
        if findings is not None:
            problem = _findings_problem(
                findings, label="delivery findings", findings_policy=findings_policy
            )
            if problem:
                return problem
        return _structured_array_problem(
            document.get("residual-risk"),
            label="delivery residual-risk",
            allow_empty=True,
        )
    if profile == "human-approval":
        for field in ("approver", "scope", "timestamp"):
            if not isinstance(document.get(field), str):
                return f"approval {field} must be a string"
            problem = _content_problem(document.get(field), label=f"approval {field}")
            if problem:
                return problem
        decision = document.get("decision")
        if not isinstance(decision, str) or decision.strip().lower() not in {
            "approved",
            "rejected",
        }:
            return "approval decision must be approved or rejected"
        return None
    if profile == "frozen-manifest":
        for field in ("lanes", "boundaries", "waves", "owners", "gates"):
            problem = _text_array_problem(
                document.get(field), label=f"manifest {field}", allow_empty=False
            )
            if problem:
                return problem
        digest = document.get("digest")
        if not isinstance(digest, str) or not _DIGEST_RE.fullmatch(digest):
            return "manifest digest must be a lowercase sha256"
        return None
    if profile == "restore-point":
        for field in ("scope", "reference", "verification"):
            if not isinstance(document.get(field), str):
                return f"restore point {field} must be a string"
            problem = _content_problem(
                document.get(field), label=f"restore point {field}"
            )
            if problem:
                return problem
        return None
    if profile == "closeout-record":
        outcome = document.get("outcome")
        if not isinstance(outcome, str):
            return "closeout outcome must be a string"
        problem = _content_problem(outcome, label="closeout outcome")
        if problem:
            return problem
        problem = _structured_array_problem(
            document.get("gates"), label="closeout gates", allow_empty=False
        )
        if problem:
            return problem
        gate_ids: set[str] = set()
        for index, gate in enumerate(document["gates"]):
            if (
                not isinstance(gate, dict)
                or not {"id", "status", "evidence"}.issubset(gate)
                or gate.get("status")
                not in {"passed", "not-applicable", "accepted-risk"}
            ):
                return f"closeout gate[{index}] must be a resolved gate object"
            gate_id = gate.get("id")
            if not isinstance(gate_id, str):
                return f"closeout gate[{index}] id must be a string"
            problem = _content_problem(gate_id, label=f"closeout gate[{index}].id")
            if problem:
                return problem
            if gate_id in gate_ids:
                return f"closeout gates contain duplicate id {gate_id!r}"
            gate_ids.add(gate_id)
            problem = _citations_problem(
                gate.get("evidence"), label=f"closeout gate[{index}].evidence"
            )
            if problem:
                return problem
        accepted_risks = document.get("accepted-risks")
        if not isinstance(accepted_risks, list):
            return "closeout accepted-risks must be an array"
        required_risk_fields = set(
            findings_policy.get("accepted_risk", {}).get("required_fields", [])
        )
        for index, risk in enumerate(accepted_risks):
            if not isinstance(risk, dict) or not required_risk_fields.issubset(risk):
                return f"closeout accepted-risk[{index}] is incomplete"
            for field in required_risk_fields - {"evidence"}:
                if not isinstance(risk.get(field), str):
                    return f"closeout accepted-risk[{index}].{field} must be a string"
                problem = _content_problem(
                    risk[field], label=f"closeout accepted-risk[{index}].{field}"
                )
                if problem:
                    return problem
            problem = _citations_problem(
                risk.get("evidence"), label=f"closeout accepted-risk[{index}].evidence"
            )
            if problem:
                return problem
        return _text_array_problem(
            document.get("learnings"), label="closeout learnings", allow_empty=True
        )
    return None


def validate_evidence_document(
    document: Any,
    requirement: EvidenceRequirement | Mapping[str, Any],
    findings_policy: FindingsPolicy | Mapping[str, Any],
    *,
    mode: str | None = None,
    require_pass: bool = True,
) -> None:
    """Validate required fields, canonical types, findings, and pass semantics."""

    requirement_doc = requirement_document(requirement)
    policy_doc = findings_policy_document(findings_policy)
    if not isinstance(document, dict):
        raise EvidenceValidationError("evidence must be a JSON object")
    missing = [
        field for field in requirement_doc["required_fields"] if field not in document
    ]
    if missing:
        raise EvidenceValidationError(
            "evidence is missing required fields: " + ", ".join(missing)
        )
    if any(document[field] is None for field in requirement_doc["required_fields"]):
        raise EvidenceValidationError("evidence required fields must not be null")
    profile = str(requirement_doc["validation_profile"])
    canonical = _CANONICAL_PROFILE_FIELDS.get(profile)
    if canonical is not None and (
        requirement_doc["kind"] != canonical[0]
        or tuple(requirement_doc["required_fields"]) != canonical[1]
    ):
        raise EvidenceValidationError(
            "evidence profile differs from its canonical kind or required fields"
        )
    for field in requirement_doc["required_fields"]:
        if profile == "command-evidence" and field == "output":
            continue
        allow_empty = field in {
            "constraints",
            "risks",
            "non-goals",
            "residual-risk",
            "accepted-risks",
            "learnings",
            "findings",
            "dispositions",
            "dependencies",
            "interfaces",
        }
        problem = _content_problem(
            document[field],
            label=f"evidence.{field}",
            allow_empty_collection=allow_empty,
        )
        if problem:
            raise EvidenceValidationError(problem)
    problem = _profile_problem(document, profile, mode=mode, findings_policy=policy_doc)
    if problem:
        raise EvidenceValidationError(problem)
    if not require_pass:
        return
    kind = requirement_doc["kind"]
    if kind == "command-output" and document.get("exit-status") != 0:
        raise EvidenceValidationError("command evidence has a non-zero exit status")
    if kind == "verdict" and str(document.get("status", "")).strip().lower() != "pass":
        raise EvidenceValidationError("verdict evidence is not PASS")
    if profile == "test-report" and document.get("failed") != 0:
        raise EvidenceValidationError("test report contains failed tests")
    if (
        profile == "human-approval"
        and str(document.get("decision", "")).strip().lower() != "approved"
    ):
        raise EvidenceValidationError("approval evidence is not approved")
    status = document.get("status")
    if (
        profile == "delivery-report"
        and status is not None
        and str(status).strip().lower()
        not in {"pass", "passed", "success", "succeeded"}
    ):
        raise EvidenceValidationError("delivery report status is not passing")
    findings = document.get("findings", [])
    forbidden = set(policy_doc["pass_requires_zero"])
    present = (
        sorted(
            {
                str(item.get("severity", "")).strip().lower()
                for item in findings
                if isinstance(item, dict)
                and str(item.get("severity", "")).strip().lower() in forbidden
            }
        )
        if isinstance(findings, list)
        else []
    )
    if present:
        raise EvidenceValidationError(
            "evidence contains severities forbidden for success: " + ", ".join(present)
        )


def parse_evidence_envelope(
    output: str | None,
    *,
    expected_ids: Sequence[str],
    requirements: Mapping[str, EvidenceRequirement | Mapping[str, Any]],
    findings_policy: FindingsPolicy | Mapping[str, Any],
    mode: str | None = None,
    require_pass: bool = True,
) -> dict[str, bytes]:
    """Parse exactly ``{"evidence": {id: document}}`` into canonical bytes."""

    if output is None or len(output.encode("utf-8")) > MAX_EVIDENCE_ENVELOPE_BYTES:
        raise EvidenceValidationError(
            "stage must return a bounded JSON evidence envelope"
        )
    try:
        envelope = json.loads(
            output,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise EvidenceValidationError(
            f"stage evidence envelope is invalid JSON: {exc}"
        ) from exc
    if not isinstance(envelope, dict) or set(envelope) != {"evidence"}:
        raise EvidenceValidationError(
            "stage evidence output must be exactly {'evidence': {...}}"
        )
    evidence = envelope.get("evidence")
    expected = set(expected_ids)
    if not isinstance(evidence, dict) or set(evidence) != expected:
        raise EvidenceValidationError(
            "stage evidence envelope does not contain the exact evidence set"
        )
    payloads: dict[str, bytes] = {}
    for evidence_id in sorted(expected):
        requirement = requirements.get(evidence_id)
        if requirement is None:
            raise EvidenceValidationError(
                f"evidence {evidence_id!r} has no frozen requirement"
            )
        document = evidence[evidence_id]
        validate_evidence_document(
            document, requirement, findings_policy, mode=mode, require_pass=require_pass
        )
        try:
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
        except (TypeError, ValueError) as exc:
            raise EvidenceValidationError(
                f"evidence {evidence_id!r} is not canonical JSON: {exc}"
            ) from exc
        payloads[evidence_id] = payload
    return payloads


def normalized_findings(
    payloads: Mapping[str, bytes],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Derive exact finding identities and pipeline severity counts from typed evidence."""

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "cosmetic": 0}
    for evidence_id in sorted(payloads):
        document = json.loads(payloads[evidence_id])
        findings = document.get("findings", []) if isinstance(document, dict) else []
        if not isinstance(findings, list):
            continue
        for item in findings:
            if not isinstance(item, dict):
                continue
            finding_id = str(item.get("id", item.get("finding-id", "")))
            if finding_id in seen:
                raise EvidenceValidationError(
                    f"duplicate finding id {finding_id!r} across stage evidence"
                )
            seen.add(finding_id)
            severity = str(item.get("severity", "")).strip().lower()
            count_key = "cosmetic" if severity == "info" else severity
            if count_key not in counts:
                raise EvidenceValidationError(
                    f"finding {finding_id!r} has unsupported severity"
                )
            counts[count_key] += 1
            core = {
                "finding_id": finding_id,
                "severity": severity,
                "disposition": str(item.get("disposition", "")).strip(),
                "evidence": item.get("evidence"),
                "source_evidence_id": evidence_id,
            }
            fingerprint = hashlib.sha256(
                json.dumps(
                    core, ensure_ascii=False, separators=(",", ":"), sort_keys=True
                ).encode("utf-8")
            ).hexdigest()
            normalized.append({**core, "fingerprint": fingerprint})
    return normalized, counts


def stage_instruction(
    *,
    expected_ids: Sequence[str],
    requirements: Mapping[str, EvidenceRequirement | Mapping[str, Any]],
) -> str:
    """Render a compact, provider-neutral terminal-output contract for a stage."""

    lines = [
        "Terminal success output MUST be one JSON object with exactly the key 'evidence'.",
        "The evidence object MUST contain exactly these identifiers; symbolic artifact:// references are not evidence:",
    ]
    for evidence_id in expected_ids:
        requirement = requirement_document(requirements[evidence_id])
        lines.append(
            f"- {evidence_id}: kind={requirement['kind']}; required fields="
            + ", ".join(requirement["required_fields"])
        )
    lines.append(
        "Use PASS/zero-failure semantics. Every finding needs a stable id, severity, disposition, and concrete evidence citation."
    )
    return "\n".join(lines)
