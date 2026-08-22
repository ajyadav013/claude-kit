from __future__ import annotations

import json

import pytest

from claude_kit.workflow_evidence import (
    EvidenceValidationError,
    managed_evidence_projection,
    normalized_findings,
    parse_evidence_envelope,
    validate_evidence_document,
)
from claude_kit.workflows import load_workflow


def _documents(mode: str = "B") -> dict[str, dict]:
    return {
        "scope-record": {
            "mode": mode,
            "surfaces": ["repository"],
            "constraints": [],
            "risks": [],
        },
        "specification": {
            "outcome": "Return the requested behavior.",
            "acceptance-criteria": ["A focused test passes."],
            "non-goals": [],
            "risks": [],
        },
        "architecture-plan": {
            "boundaries": ["owned workspace"],
            "dependencies": [],
            "interfaces": [],
            "verification": ["focused tests"],
        },
        "review-verdict": {
            "status": "PASS",
            "reviewer": "reviewer",
            "findings": [],
            "evidence": ["src/example.py:10"],
        },
        "command-evidence": {
            "command": "pytest -q",
            "exit-status": 0,
            "output": "passed",
        },
        "test-report": {
            "scope": ["unit tests"],
            "passed": 1,
            "failed": 0,
            "skipped": 0,
            "residual-risk": [],
        },
        "security-report": {
            "scanners": ["scanner"],
            "findings": [],
            "dispositions": [],
            "residual-risk": [],
        },
        "delivery-report": {
            "checks": ["pipeline"],
            "rollback": {"strategy": "revert"},
            "residual-risk": [],
        },
        "human-approval": {
            "approver": "owner",
            "scope": "exact action",
            "decision": "approved",
            "timestamp": "2026-01-01T00:00:00Z",
        },
        "frozen-manifest": {
            "lanes": ["lane"],
            "boundaries": ["workspace"],
            "waves": ["wave"],
            "owners": ["owner"],
            "gates": ["gate"],
            "digest": "a" * 64,
        },
        "restore-point": {
            "scope": "workspace",
            "reference": "commit:abc",
            "verification": "verified",
        },
        "closeout-record": {
            "outcome": "completed",
            "gates": [
                {
                    "id": "gate",
                    "status": "passed",
                    "evidence": ["tests/test_workflow_evidence.py"],
                }
            ],
            "accepted-risks": [],
            "learnings": [],
        },
    }


@pytest.mark.parametrize("evidence_id", sorted(_documents()))
def test_every_canonical_evidence_profile_accepts_content_bearing_pass(
    payload, evidence_id
):
    workflow = load_workflow(payload)
    validate_evidence_document(
        _documents()[evidence_id],
        workflow.evidence_requirements[evidence_id],
        workflow.findings_policy,
        mode="B",
        require_pass=True,
    )


@pytest.mark.parametrize(
    ("evidence_id", "field", "placeholder"),
    [
        ("specification", "outcome", 1),
        ("specification", "acceptance-criteria", True),
        ("architecture-plan", "boundaries", "all files"),
        ("architecture-plan", "verification", False),
        ("delivery-report", "checks", "green"),
        ("delivery-report", "rollback", ["revert"]),
        ("delivery-report", "rollback", {"verified": True}),
        ("test-report", "scope", True),
        ("security-report", "residual-risk", 0),
        ("human-approval", "approver", True),
        ("frozen-manifest", "lanes", "lane"),
        ("restore-point", "verification", 1),
        ("closeout-record", "outcome", 1),
        ("closeout-record", "gates", True),
    ],
)
def test_canonical_profiles_reject_scalar_or_wrong_collection_placeholders(
    payload, evidence_id, field, placeholder
):
    workflow = load_workflow(payload)
    document = _documents()[evidence_id]
    document[field] = placeholder
    with pytest.raises(EvidenceValidationError):
        validate_evidence_document(
            document,
            workflow.evidence_requirements[evidence_id],
            workflow.findings_policy,
            mode="B",
        )


def test_exact_envelope_rejects_echoed_refs_and_extra_evidence(payload):
    workflow = load_workflow(payload)
    requirement = {"scope-record": workflow.evidence_requirements["scope-record"]}
    with pytest.raises(EvidenceValidationError, match="invalid JSON"):
        parse_evidence_envelope(
            "artifact://scope-record",
            expected_ids=("scope-record",),
            requirements=requirement,
            findings_policy=workflow.findings_policy,
            mode="B",
        )
    with pytest.raises(EvidenceValidationError, match="exact evidence set"):
        parse_evidence_envelope(
            json.dumps(
                {
                    "evidence": {
                        "scope-record": _documents()["scope-record"],
                        "review-verdict": _documents()["review-verdict"],
                    }
                }
            ),
            expected_ids=("scope-record",),
            requirements=requirement,
            findings_policy=workflow.findings_policy,
            mode="B",
        )


def test_medium_findings_are_identified_but_critical_findings_cannot_pass(payload):
    workflow = load_workflow(payload)
    requirement = {"review-verdict": workflow.evidence_requirements["review-verdict"]}
    medium = _documents()["review-verdict"]
    medium["findings"] = [
        {
            "id": "MED-1",
            "severity": "medium",
            "disposition": "open",
            "evidence": ["src/example.py:10"],
        }
    ]
    payloads = parse_evidence_envelope(
        json.dumps({"evidence": {"review-verdict": medium}}),
        expected_ids=("review-verdict",),
        requirements=requirement,
        findings_policy=workflow.findings_policy,
        mode="B",
    )
    findings, counts = normalized_findings(payloads)
    assert counts["medium"] == 1
    assert [item["finding_id"] for item in findings] == ["MED-1"]

    critical = _documents()["review-verdict"]
    critical["findings"] = [
        {
            "id": "CRIT-1",
            "severity": "critical",
            "disposition": "open",
            "evidence": ["src/example.py:20"],
        }
    ]
    with pytest.raises(EvidenceValidationError, match="forbidden for success"):
        parse_evidence_envelope(
            json.dumps({"evidence": {"review-verdict": critical}}),
            expected_ids=("review-verdict",),
            requirements=requirement,
            findings_policy=workflow.findings_policy,
            mode="B",
        )


def test_managed_projection_freezes_stage_gate_requirements_and_findings(payload):
    workflow = load_workflow(payload)
    projection = managed_evidence_projection(
        workflow,
        active_stages=("classify", "fast-review"),
        ordered_gates=("code-review",),
    )
    assert projection["evidence_contract_version"] == 1
    assert projection["active_stage_evidence"] == {
        "classify": ["scope-record"],
        "fast-review": ["review-verdict"],
    }
    assert projection["gate_evidence"] == {"code-review": ["review-verdict"]}
    assert projection["findings_policy"]["pass_requires_zero"] == [
        "critical",
        "high",
    ]
