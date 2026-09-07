from __future__ import annotations

import json

import pytest

from claude_kit.workflow_evidence import (
    EvidenceValidationError,
    managed_evidence_projection,
    normalized_findings,
    parse_evidence_envelope,
    stage_instruction,
    validate_evidence_document,
)
from claude_kit.workflows import load_workflow


def _planning_finding(
    *,
    severity: str = "medium",
    disposition: str = "open",
    authority_domain: str = "backend",
) -> dict:
    return {
        "finding-id": "PLAN-1",
        "severity": severity,
        "disposition": disposition,
        "authority-domain": authority_domain,
        "criterion": "AC-1 requires an explicit failure contract.",
        "requested-correction": "Define the failure response and its verification.",
        "owner": "senior-backend-reviewer",
        "evidence": ["docs/spec.md:20"],
    }


def _planning_decision() -> dict:
    return {
        "decision-id": "DEC-1",
        "authority-domain": "delivery",
        "selected-option": "Use the existing reversible delivery path.",
        "rejected-alternatives": ["Introduce a second delivery controller."],
        "rationale": "The existing path satisfies the frozen contract with less state.",
        "dissent": ["A second controller could isolate experimental behavior."],
        "reopen-trigger": "The existing controller cannot represent a required invariant.",
        "decider": "em-reviewer",
        "evidence": ["docs/spec.md:30"],
    }


def _fast_track_scope_record(**overrides) -> dict:
    document = {
        "mode": "D",
        "surfaces": ["one local implementation boundary"],
        "constraints": [],
        "risks": [],
        "risk-tier": "low",
        "localized-single-boundary": True,
        "unambiguous": True,
        "reversible": True,
        "sensitive-surface": False,
        "public-contract-surface": False,
        "irreversible-action": False,
        "external-effect": False,
    }
    document.update(overrides)
    return document


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
        "story-breakdown": {
            "stories": [
                {
                    "story-id": "STORY-1",
                    "goal": "Deliver the approved behavior.",
                    "acceptance-criteria": ["A focused test passes."],
                    "surfaces": ["owned workspace"],
                    "risk": "low",
                    "batchable": True,
                    "verification": ["Run the focused test."],
                }
            ],
            "dependencies": [{"story-id": "STORY-1", "blocked-by": []}],
            "parallelizable": ["STORY-1"],
            "sequencing": ["STORY-1"],
            "traceability": [
                {"criterion": "A focused test passes.", "story-ids": ["STORY-1"]}
            ],
        },
        "review-verdict": {
            "status": "PASS",
            "reviewer": "reviewer",
            "findings": [],
            "evidence": ["src/example.py:10"],
        },
        "planning-review-verdict": {
            "status": "PASS",
            "reviewer": "senior-backend-reviewer",
            "planning-generation": "b" * 64,
            "authority-domain": "backend",
            "findings": [],
            "evidence": ["docs/spec.md:1"],
        },
        "planning-decision": {
            "status": "PASS",
            "reviewer": "em-reviewer",
            "planning-generation": "b" * 64,
            "panel-reviewers": ["senior-backend-reviewer"],
            "findings": [],
            "decisions": [],
            "evidence": ["docs/spec.md:1"],
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
        ("story-breakdown", "stories", "STORY-1"),
        ("story-breakdown", "sequencing", False),
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


def test_story_breakdown_ready_set_must_match_dependency_graph(payload):
    workflow = load_workflow(payload)
    document = _documents()["story-breakdown"]
    document["parallelizable"] = []

    with pytest.raises(EvidenceValidationError, match="exactly name the unblocked"):
        validate_evidence_document(
            document,
            workflow.evidence_requirements["story-breakdown"],
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


@pytest.mark.parametrize(
    ("field", "unsafe_value"),
    [
        ("risk-tier", "medium"),
        ("localized-single-boundary", False),
        ("unambiguous", False),
        ("reversible", False),
        ("sensitive-surface", True),
        ("public-contract-surface", True),
        ("irreversible-action", True),
        ("external-effect", True),
    ],
)
def test_fast_track_scope_records_unsafe_facts_but_cannot_pass(
    payload, field, unsafe_value
):
    workflow = load_workflow(payload)
    requirement = workflow.evidence_requirements["fast-track-scope-record"]
    document = _fast_track_scope_record(**{field: unsafe_value})

    validate_evidence_document(
        document,
        requirement,
        workflow.findings_policy,
        mode="D",
        require_pass=False,
    )
    with pytest.raises(EvidenceValidationError, match="Mode D safety floor"):
        validate_evidence_document(
            document,
            requirement,
            workflow.findings_policy,
            mode="D",
            require_pass=True,
        )


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("risk-tier", "unknown"),
        ("localized-single-boundary", 1),
        ("reversible", "yes"),
        ("external-effect", None),
    ],
)
def test_fast_track_scope_rejects_missing_or_wrongly_typed_facts(
    payload, field, invalid_value
):
    workflow = load_workflow(payload)
    document = _fast_track_scope_record(**{field: invalid_value})

    with pytest.raises(EvidenceValidationError):
        validate_evidence_document(
            document,
            workflow.evidence_requirements["fast-track-scope-record"],
            workflow.findings_policy,
            mode="D",
            require_pass=False,
        )


def test_fast_track_scope_safe_contract_passes_without_changing_legacy_scope(payload):
    workflow = load_workflow(payload)

    assert workflow.evidence_requirements["scope-record"].required_fields == (
        "mode",
        "surfaces",
        "constraints",
        "risks",
    )
    validate_evidence_document(
        _fast_track_scope_record(),
        workflow.evidence_requirements["fast-track-scope-record"],
        workflow.findings_policy,
        mode="D",
        require_pass=True,
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


@pytest.mark.parametrize("profile", ["planning-review-verdict", "planning-decision"])
def test_planning_profiles_accept_pass_and_blocking_fail(payload, profile):
    workflow = load_workflow(payload)
    requirement = workflow.evidence_requirements[profile]

    validate_evidence_document(
        _documents()[profile],
        requirement,
        workflow.findings_policy,
        mode="B",
        require_pass=True,
    )

    failed = _documents()[profile]
    failed["status"] = "FAIL"
    failed["findings"] = [_planning_finding()]
    validate_evidence_document(
        failed,
        requirement,
        workflow.findings_policy,
        mode="B",
        require_pass=False,
    )


@pytest.mark.parametrize("profile", ["planning-review-verdict", "planning-decision"])
def test_planning_profiles_reject_unknown_top_level_fields(payload, profile):
    workflow = load_workflow(payload)
    document = _documents()[profile]
    document["untrusted-extension"] = "ignored by older validators"

    with pytest.raises(EvidenceValidationError, match="closed contract fields"):
        validate_evidence_document(
            document,
            workflow.evidence_requirements[profile],
            workflow.findings_policy,
        )


@pytest.mark.parametrize("profile", ["planning-review-verdict", "planning-decision"])
def test_planning_profiles_reject_unknown_finding_fields(payload, profile):
    workflow = load_workflow(payload)
    document = _documents()[profile]
    document["status"] = "FAIL"
    finding = _planning_finding()
    finding["untrusted-extension"] = "not part of the finding identity"
    document["findings"] = [finding]

    with pytest.raises(EvidenceValidationError, match="planning finding fields"):
        validate_evidence_document(
            document,
            workflow.evidence_requirements[profile],
            workflow.findings_policy,
            require_pass=False,
        )


def test_planning_decision_rejects_unknown_decision_fields(payload):
    workflow = load_workflow(payload)
    document = _documents()["planning-decision"]
    decision = _planning_decision()
    decision["untrusted-extension"] = "not part of the decision ledger"
    document["decisions"] = [decision]

    with pytest.raises(EvidenceValidationError, match="must contain decision-id"):
        validate_evidence_document(
            document,
            workflow.evidence_requirements["planning-decision"],
            workflow.findings_policy,
        )


@pytest.mark.parametrize(
    "authority_domain",
    [
        "product",
        "frontend",
        "backend",
        "architecture",
        "delivery",
        "gate-evidence",
    ],
)
def test_planning_review_accepts_every_authority_domain(payload, authority_domain):
    workflow = load_workflow(payload)
    document = _documents()["planning-review-verdict"]
    document["status"] = "FAIL"
    document["authority-domain"] = authority_domain
    document["findings"] = [_planning_finding(authority_domain=authority_domain)]

    validate_evidence_document(
        document,
        workflow.evidence_requirements["planning-review-verdict"],
        workflow.findings_policy,
        require_pass=False,
    )


@pytest.mark.parametrize(
    "disposition", ["open", "fixed", "advisory", "disputed", "human-required"]
)
def test_planning_finding_accepts_every_disposition(payload, disposition):
    workflow = load_workflow(payload)
    document = _documents()["planning-decision"]
    blocking = disposition in {"open", "disputed", "human-required"}
    document["status"] = "FAIL" if blocking else "PASS"
    document["findings"] = [
        _planning_finding(
            severity="medium" if blocking else "low", disposition=disposition
        )
    ]
    document["decisions"] = [_planning_decision()]

    validate_evidence_document(
        document,
        workflow.evidence_requirements["planning-decision"],
        workflow.findings_policy,
        require_pass=False,
    )


@pytest.mark.parametrize("profile", ["planning-review-verdict", "planning-decision"])
def test_planning_profiles_reject_pass_with_open_medium_finding(payload, profile):
    workflow = load_workflow(payload)
    document = _documents()[profile]
    document["findings"] = [_planning_finding()]

    with pytest.raises(EvidenceValidationError, match="PASS cannot contain"):
        validate_evidence_document(
            document,
            workflow.evidence_requirements[profile],
            workflow.findings_policy,
            require_pass=False,
        )


@pytest.mark.parametrize("profile", ["planning-review-verdict", "planning-decision"])
def test_planning_profiles_reject_fail_with_only_resolved_or_advisory_findings(
    payload, profile
):
    workflow = load_workflow(payload)
    for disposition in ("fixed", "advisory"):
        document = _documents()[profile]
        document["status"] = "FAIL"
        document["findings"] = [_planning_finding(disposition=disposition)]

        with pytest.raises(EvidenceValidationError, match="open, disputed"):
            validate_evidence_document(
                document,
                workflow.evidence_requirements[profile],
                workflow.findings_policy,
                require_pass=False,
            )


@pytest.mark.parametrize("profile", ["planning-review-verdict", "planning-decision"])
@pytest.mark.parametrize("severity", ["critical", "high"])
def test_planning_pass_preserves_fixed_blocker_history(payload, profile, severity):
    workflow = load_workflow(payload)
    document = _documents()[profile]
    document["findings"] = [_planning_finding(severity=severity, disposition="fixed")]

    validate_evidence_document(
        document,
        workflow.evidence_requirements[profile],
        workflow.findings_policy,
        require_pass=True,
    )


@pytest.mark.parametrize("generation", ["a" * 63, "A" * 64, "g" * 64])
@pytest.mark.parametrize("profile", ["planning-review-verdict", "planning-decision"])
def test_planning_profiles_reject_invalid_generation(payload, profile, generation):
    workflow = load_workflow(payload)
    document = _documents()[profile]
    document["planning-generation"] = generation

    with pytest.raises(EvidenceValidationError, match="lowercase sha256 digest"):
        validate_evidence_document(
            document,
            workflow.evidence_requirements[profile],
            workflow.findings_policy,
        )


@pytest.mark.parametrize(
    ("authority_domain", "message"),
    [
        ("security", "authority-domain"),
        ("Backend", "authority-domain"),
        ("", "authority-domain"),
        ([], "authority-domain"),
        (None, "must not be null"),
    ],
)
def test_planning_review_rejects_invalid_authority_domain(
    payload, authority_domain, message
):
    workflow = load_workflow(payload)
    document = _documents()["planning-review-verdict"]
    document["authority-domain"] = authority_domain

    with pytest.raises(EvidenceValidationError, match=message):
        validate_evidence_document(
            document,
            workflow.evidence_requirements["planning-review-verdict"],
            workflow.findings_policy,
        )


@pytest.mark.parametrize(
    "panel_reviewers",
    [[], ["reviewer", "reviewer"], ["reviewer", 1], [""]],
)
def test_planning_decision_rejects_invalid_panel_reviewers(payload, panel_reviewers):
    workflow = load_workflow(payload)
    document = _documents()["planning-decision"]
    document["panel-reviewers"] = panel_reviewers

    with pytest.raises(EvidenceValidationError, match="panel-reviewers"):
        validate_evidence_document(
            document,
            workflow.evidence_requirements["planning-decision"],
            workflow.findings_policy,
        )


@pytest.mark.parametrize("decisions", ["none", [1], [{}]])
def test_planning_decision_rejects_unstructured_decisions(payload, decisions):
    workflow = load_workflow(payload)
    document = _documents()["planning-decision"]
    document["decisions"] = decisions

    with pytest.raises(EvidenceValidationError, match="decisions"):
        validate_evidence_document(
            document,
            workflow.evidence_requirements["planning-decision"],
            workflow.findings_policy,
        )


def test_planning_decision_accepts_typed_decision_ledger(payload):
    workflow = load_workflow(payload)
    document = _documents()["planning-decision"]
    document["decisions"] = [_planning_decision()]

    validate_evidence_document(
        document,
        workflow.evidence_requirements["planning-decision"],
        workflow.findings_policy,
    )


@pytest.mark.parametrize(
    "field",
    [
        "decision-id",
        "authority-domain",
        "selected-option",
        "rejected-alternatives",
        "rationale",
        "dissent",
        "reopen-trigger",
        "decider",
        "evidence",
    ],
)
def test_planning_decision_requires_reopenable_decision_fields(payload, field):
    workflow = load_workflow(payload)
    document = _documents()["planning-decision"]
    decision = _planning_decision()
    del decision[field]
    document["decisions"] = [decision]

    with pytest.raises(EvidenceValidationError, match="must contain decision-id"):
        validate_evidence_document(
            document,
            workflow.evidence_requirements["planning-decision"],
            workflow.findings_policy,
        )


def test_planning_decision_rejects_duplicate_decision_ids(payload):
    workflow = load_workflow(payload)
    document = _documents()["planning-decision"]
    document["decisions"] = [_planning_decision(), _planning_decision()]

    with pytest.raises(EvidenceValidationError, match="duplicate decision id"):
        validate_evidence_document(
            document,
            workflow.evidence_requirements["planning-decision"],
            workflow.findings_policy,
        )


@pytest.mark.parametrize("profile", ["planning-review-verdict", "planning-decision"])
@pytest.mark.parametrize(
    "field", ["authority-domain", "criterion", "requested-correction", "owner"]
)
def test_planning_findings_require_convergence_fields(payload, profile, field):
    workflow = load_workflow(payload)
    document = _documents()[profile]
    document["status"] = "FAIL"
    finding = _planning_finding()
    del finding[field]
    document["findings"] = [finding]

    with pytest.raises(EvidenceValidationError, match="must contain authority-domain"):
        validate_evidence_document(
            document,
            workflow.evidence_requirements[profile],
            workflow.findings_policy,
            require_pass=False,
        )


@pytest.mark.parametrize("profile", ["planning-review-verdict", "planning-decision"])
def test_planning_findings_reject_invalid_domain_and_disposition(payload, profile):
    workflow = load_workflow(payload)
    requirement = workflow.evidence_requirements[profile]
    document = _documents()[profile]
    document["status"] = "FAIL"
    document["findings"] = [_planning_finding(authority_domain="security")]
    with pytest.raises(EvidenceValidationError, match="invalid authority-domain"):
        validate_evidence_document(
            document,
            requirement,
            workflow.findings_policy,
            require_pass=False,
        )

    document["findings"] = [_planning_finding(disposition="accepted")]
    with pytest.raises(EvidenceValidationError, match="planning disposition"):
        validate_evidence_document(
            document,
            requirement,
            workflow.findings_policy,
            require_pass=False,
        )


@pytest.mark.parametrize("profile", ["planning-review-verdict", "planning-decision"])
@pytest.mark.parametrize("severity", [None, "low", "info", "cosmetic"])
def test_planning_fail_requires_a_blocking_finding(payload, profile, severity):
    workflow = load_workflow(payload)
    document = _documents()[profile]
    document["status"] = "FAIL"
    document["findings"] = (
        [] if severity is None else [_planning_finding(severity=severity)]
    )

    with pytest.raises(EvidenceValidationError, match="FAIL must contain"):
        validate_evidence_document(
            document,
            workflow.evidence_requirements[profile],
            workflow.findings_policy,
            require_pass=False,
        )


@pytest.mark.parametrize("profile", ["planning-review-verdict", "planning-decision"])
def test_planning_pass_uses_existing_findings_policy(payload, profile):
    workflow = load_workflow(payload)
    document = _documents()[profile]
    document["findings"] = [_planning_finding(severity="high")]

    with pytest.raises(
        EvidenceValidationError,
        match="PASS cannot contain an open blocking finding",
    ):
        validate_evidence_document(
            document,
            workflow.evidence_requirements[profile],
            workflow.findings_policy,
            require_pass=True,
        )


def test_generic_review_findings_remain_backward_compatible(payload):
    workflow = load_workflow(payload)
    document = _documents()["review-verdict"]
    document["status"] = "FAIL"
    document["findings"] = [
        {
            "id": "LEGACY-1",
            "severity": "low",
            "disposition": "acknowledged",
            "evidence": ["src/example.py:10"],
        }
    ]

    validate_evidence_document(
        document,
        workflow.evidence_requirements["review-verdict"],
        workflow.findings_policy,
        require_pass=False,
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


def test_stage_instruction_distinguishes_advisory_review_from_em_decision(payload):
    workflow = load_workflow(payload)

    advisory = stage_instruction(
        expected_ids=("planning-review-verdict",),
        requirements=workflow.evidence_requirements,
    )
    assert (
        "FAIL is a completed advisory assessment handed to the accountable EM"
        in advisory
    )
    assert "Use PASS/zero-failure semantics." not in advisory

    decision = stage_instruction(
        expected_ids=("planning-decision",),
        requirements=workflow.evidence_requirements,
    )
    assert "Use PASS/zero-failure semantics." in decision
    assert "completed advisory assessment" not in decision
