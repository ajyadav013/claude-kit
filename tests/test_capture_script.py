"""The real-run collector keeps schema-v2 evidence bundles complete and contained."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from claude_kit import catalog
from claude_kit.models import InstallRequest
from claude_kit.runtime_scaffold import install_runtime

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


def _write_snapshot(project: Path, document: dict, *, root: str = ".claude") -> None:
    state = project / root / "state"
    state.mkdir(parents=True, exist_ok=True)
    (state / "pipeline-snapshot.json").write_text(
        json.dumps(document, indent=2) + "\n", encoding="utf-8"
    )


def _write_control_plane(project: Path, root: str, label: str) -> None:
    config = project / root / "config"
    config.mkdir(parents=True, exist_ok=True)
    (config / "init-options.json").write_text(
        json.dumps({"test_layout": label}) + "\n", encoding="utf-8"
    )
    (config / "stack-catalog.snapshot.yaml").write_text(
        f"test_layout: {label}\n", encoding="utf-8"
    )
    _write_snapshot(
        project,
        {"schema_version": 2, "test_layout": label},
        root=root,
    )
    (project / root / "CONTINUITY.md").write_text(
        f"# Continuity\n\n{label}\n", encoding="utf-8"
    )


def _assert_captured_layout(bundle: Path, label: str) -> None:
    snapshot = json.loads(
        (bundle / "state/pipeline-snapshot.json").read_text(encoding="utf-8")
    )
    assert snapshot["test_layout"] == label
    assert (bundle / "state/stack-catalog.snapshot.yaml").read_text(
        encoding="utf-8"
    ) == f"test_layout: {label}\n"
    assert (
        (bundle / "continuity.md").read_text(encoding="utf-8").endswith(f"\n{label}\n")
    )


@pytest.mark.parametrize("runtime", ["claude", "codex", "both"])
def test_capture_uses_neutral_control_plane_for_every_native_runtime(
    payload, tmp_path, runtime
):
    project = tmp_path / runtime
    selection = catalog.defaults(payload)
    plan = catalog.resolve(payload, selection)
    install_runtime(payload, project, plan, InstallRequest(selection, runtime))

    neutral_label = f"neutral-{runtime}"
    _write_control_plane(project, ".ckit", neutral_label)
    _write_control_plane(project, ".claude", f"legacy-poison-{runtime}")
    bundle = tmp_path / f"bundle-{runtime}"

    result = _run(project, bundle)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "neutral control plane at .ckit/" in result.stdout
    _assert_captured_layout(bundle, neutral_label)
    assert "legacy-poison" not in "".join(
        path.read_text(encoding="utf-8") for path in bundle.rglob("*") if path.is_file()
    )


def test_capture_falls_back_to_one_legacy_claude_control_plane(tmp_path):
    project = tmp_path / "legacy"
    _write_control_plane(project, ".claude", "legacy")
    bundle = tmp_path / "legacy-bundle"

    result = _run(project, bundle)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "legacy Claude control plane at .claude/" in result.stdout
    _assert_captured_layout(bundle, "legacy")


def test_neutral_marker_never_backfills_missing_files_from_legacy(tmp_path):
    project = tmp_path / "split-state"
    _write_control_plane(project, ".claude", "legacy-poison")
    _write_snapshot(
        project,
        {"schema_version": 2, "test_layout": "neutral-authoritative"},
        root=".ckit",
    )
    bundle = tmp_path / "split-bundle"

    result = _run(project, bundle)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "neutral control plane at .ckit/" in result.stdout
    captured = json.loads(
        (bundle / "state/pipeline-snapshot.json").read_text(encoding="utf-8")
    )
    assert captured["test_layout"] == "neutral-authoritative"
    assert not (bundle / "state/stack-catalog.snapshot.yaml").exists()
    assert not (bundle / "continuity.md").exists()
    assert "legacy-poison" not in result.stdout


@pytest.mark.parametrize("unsafe_kind", ["symlink", "directory"])
def test_capture_rejects_unsafe_control_plane_marker(tmp_path, unsafe_kind):
    project = tmp_path / "unsafe-control-plane"
    state = project / ".ckit" / "state"
    state.mkdir(parents=True)
    marker = state / "pipeline-snapshot.json"
    if unsafe_kind == "symlink":
        outside = tmp_path / "outside-snapshot.json"
        outside.write_text('{"secret": "must-not-copy"}\n', encoding="utf-8")
        marker.symlink_to(outside)
    else:
        marker.mkdir()

    bundle = tmp_path / f"unsafe-bundle-{unsafe_kind}"
    result = _run(project, bundle)

    assert result.returncode != 0
    output = result.stdout + result.stderr
    expected = "symlink" if unsafe_kind == "symlink" else "non-regular"
    assert f"refusing {expected}" in output
    assert not (bundle / "state" / "pipeline-snapshot.json").exists()


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
