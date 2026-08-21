"""The real-run collector keeps schema-v2 evidence bundles complete and contained."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "capture-sdlc-run.sh"


def _run(project: Path, bundle: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "bash",
            str(SCRIPT),
            "--project",
            str(project),
            "--out",
            str(bundle),
            "--base",
            "branch-that-does-not-exist",
        ],
        text=True,
        capture_output=True,
        check=False,
    )


def _write_snapshot(project: Path, document: dict) -> None:
    state = project / ".claude" / "state"
    state.mkdir(parents=True)
    (state / "pipeline-snapshot.json").write_text(
        json.dumps(document, indent=2) + "\n", encoding="utf-8"
    )


def test_capture_collects_all_v2_evidence_and_rewrites_project_relative_paths(
    tmp_path,
):
    project = tmp_path / "project"
    evidence = project / "run-evidence"
    evidence.mkdir(parents=True)
    artifacts = {
        name: evidence / f"{name}.json"
        for name in ("findings", "gate", "condition", "risk", "archived")
    }
    for name, path in artifacts.items():
        path.write_text(json.dumps({"artifact": name}) + "\n", encoding="utf-8")

    risk = {
        "risk_id": "risk-1",
        "finding_id": "MED-1",
        "evidence_path": "run-evidence/risk.json",
    }
    document = {
        "schema_version": 2,
        "findings_evidence": {"evidence_path": "run-evidence/findings.json"},
        "gate_evidence": {"legacy-map": str(artifacts["gate"])},
        "gate_history": [
            {
                "gate": "code-review",
                "status": "passed",
                "evidence_path": "run-evidence/gate.json",
            },
            {
                "gate": "contract-clear",
                "status": "not-applicable",
                "condition_evidence_path": "run-evidence/condition.json",
            },
        ],
        "accepted_risks": [dict(risk)],
        "final_summary": {"accepted_risks": [dict(risk)]},
        "run_archives": [
            {"snapshot": {"gate_evidence": {"old-gate": "run-evidence/archived.json"}}}
        ],
    }
    _write_snapshot(project, document)
    bundle = tmp_path / "bundle"

    result = _run(project, bundle)

    assert result.returncode == 0, result.stdout + result.stderr
    captured_path = bundle / "state" / "pipeline-snapshot.json"
    captured = json.loads(captured_path.read_text(encoding="utf-8"))
    rewritten = [
        captured["findings_evidence"]["evidence_path"],
        captured["gate_evidence"]["legacy-map"],
        captured["gate_history"][0]["evidence_path"],
        captured["gate_history"][1]["condition_evidence_path"],
        captured["accepted_risks"][0]["evidence_path"],
        captured["final_summary"]["accepted_risks"][0]["evidence_path"],
        captured["run_archives"][0]["snapshot"]["gate_evidence"]["old-gate"],
    ]
    assert all(path.startswith("evidence/") for path in rewritten)
    assert rewritten[1] == rewritten[2], "duplicate references should share one copy"
    assert rewritten[4] == rewritten[5]
    assert all((bundle / path).is_file() for path in rewritten)
    assert str(project) not in captured_path.read_text(encoding="utf-8")


def test_capture_fails_when_declared_evidence_is_outside_the_project(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("{}\n", encoding="utf-8")
    _write_snapshot(
        project,
        {
            "schema_version": 2,
            "findings_evidence": {"evidence_path": str(outside)},
        },
    )

    result = _run(project, tmp_path / "bundle")

    assert result.returncode != 0
    output = result.stdout + result.stderr
    assert "evidence outside the project" in output
    assert "could not create a self-contained evidence bundle" in output
