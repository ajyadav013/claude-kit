"""Behavior of the shipped bounded headless loop (templates/scripts/sdlc-loop.sh).

Runs the real script with a fake ``claude`` CLI on PATH. Each case asserts one brake:
schema-v2 completed status (exit 0), stall detection (exit 1), the iteration cap (exit 1),
the missing-finish-line refusal (exit 2), and final-gate auto-detection from the same
``yaml.safe_dump(sort_keys=False)`` serialization scaffold writes.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None, reason="bash not available"
)

SCRIPT = Path(__file__).resolve().parents[1] / "templates" / "scripts" / "sdlc-loop.sh"

ENTERPRISE_GATES = [
    "spec-complete",
    "em-approved",
    "code-review",
    "build-green",
    "contract-clear",
    "test-coverage",
    "security-clear",
    "pipeline-green",
    "observability-ready",
    "acceptance",
]


def _project(tmp_path: Path, gates: list[str] | None = None) -> Path:
    """A minimal project dir; with ``gates`` it also gets a real-shaped stack snapshot."""
    proj = tmp_path / "proj"
    (proj / ".claude" / "state").mkdir(parents=True)
    if gates is not None:
        cfg = proj / ".claude" / "config"
        cfg.mkdir(parents=True)
        # Serialized exactly like scaffold._write_config (safe_dump, sort_keys=False) so the
        # script's awk parser is exercised against the real file shape — including nested
        # lists under `selection:` that must NOT be mistaken for gate entries.
        snapshot = {
            "selection": {"profile": "standard", "mcp": ["github", "context7"]},
            "agents": ["orchestrator", "developer"],
            "gates": gates,
            "hooks": ["load-continuity", "lint-fix"],
        }
        (cfg / "stack-catalog.snapshot.yaml").write_text(
            yaml.safe_dump(snapshot, sort_keys=False), encoding="utf-8"
        )
    return proj


def _claude_shim(
    tmp_path: Path,
    body: str,
    validator_body: str = (
        '[ "$*" = "pipeline validate . --strict" ] || exit 64\n'
        "touch .claude/strictly-validated"
    ),
) -> dict[str, str]:
    """Put fake execution and lifecycle CLIs on PATH for one loop test."""
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    shim = bindir / "claude"
    shim.write_text("#!/usr/bin/env bash\n" + body + "\n", encoding="utf-8")
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    validator = bindir / "claude-kit"
    validator.write_text(
        "#!/usr/bin/env bash\n" + validator_body + "\n", encoding="utf-8"
    )
    validator.chmod(
        validator.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith("SDLC_")}
    env["PATH"] = f"{bindir}{os.pathsep}{env['PATH']}"
    return env


def _run(
    proj: Path, env: dict[str, str], extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    env = dict(env)
    env.update(extra_env or {})
    return subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=proj,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _write_gate(gate: str, *, status: str = "active") -> str:
    """Shim body: write a minimal progress projection for the loop's read-only check."""
    # Plain concatenation — str.format/f-strings would misread the JSON braces as fields.
    return (
        'printf \'{"status": "'
        + status
        + '", "last_gate_resolved": "%s"}\' "'
        + gate
        + '"'
        " > .claude/state/pipeline-snapshot.json"
    )


def test_completes_when_final_gate_reached(tmp_path):
    proj = _project(tmp_path, gates=["code-review", "build-green"])
    # A completed v2 document repeats the status in its final evidence summary. Reading
    # matching lines with sed yields ``completed\ncompleted`` and misses completion.
    snapshot = {
        "schema_version": 2,
        "run_id": "run-completed",
        "status": "completed",
        "last_gate_resolved": "build-green",
        "final_summary": {
            "run_id": "run-completed",
            "status": "completed",
            "gates": ["code-review", "build-green"],
        },
    }
    (proj / ".claude" / "state" / "pipeline-snapshot.json").write_text(
        json.dumps(snapshot, indent=2) + "\n", encoding="utf-8"
    )
    env = _claude_shim(tmp_path, "true")
    res = _run(proj, env)
    assert res.returncode == 0, res.stderr
    assert "pipeline complete and strictly validated" in res.stdout
    assert "last resolved gate: build-green" in res.stdout
    assert (proj / ".claude" / "strictly-validated").is_file()


def test_active_status_ignores_completed_status_in_archives(tmp_path):
    """Only the top-level status contributes to progress and terminal detection."""
    proj = _project(tmp_path, gates=["code-review", "build-green"])
    snapshot = {
        "schema_version": 2,
        "run_id": "run-active",
        "status": "active",
        "last_gate_resolved": None,
        "run_archives": [
            {
                "run_id": "run-completed",
                "status": "completed",
                "snapshot": {
                    "run_id": "run-completed",
                    "status": "completed",
                    "final_summary": {"status": "completed"},
                },
            }
        ],
    }
    (proj / ".claude" / "state" / "pipeline-snapshot.json").write_text(
        json.dumps(snapshot, indent=2) + "\n", encoding="utf-8"
    )
    env = _claude_shim(tmp_path, "true")

    res = _run(proj, env, {"SDLC_MAX_ITER": "2"})

    assert res.returncode == 1
    assert "STALLED at 'active:none'" in res.stderr
    assert not (proj / ".claude" / "strictly-validated").exists()


def test_autodetects_last_gate_from_enterprise_snapshot(tmp_path):
    """The awk parser picks the LAST entry of `gates:` — not the first, not a selection item."""
    proj = _project(tmp_path, gates=ENTERPRISE_GATES)
    env = _claude_shim(tmp_path, _write_gate("acceptance", status="completed"))
    res = _run(proj, env)
    assert res.returncode == 0, res.stderr
    assert "final gate 'acceptance'" in res.stdout


def test_env_override_beats_snapshot(tmp_path):
    proj = _project(tmp_path, gates=["code-review", "build-green"])
    env = _claude_shim(tmp_path, _write_gate("code-review", status="completed"))
    res = _run(proj, env, {"SDLC_FINAL_GATE": "code-review"})
    assert res.returncode == 0, res.stderr
    assert "pipeline complete and strictly validated" in res.stdout
    assert "last resolved gate: code-review" in res.stdout


def test_stalls_when_no_progress(tmp_path):
    proj = _project(tmp_path, gates=["code-review", "build-green"])
    env = _claude_shim(
        tmp_path, "true"
    )  # claude "runs" but never advances the snapshot
    res = _run(proj, env)
    assert res.returncode == 1
    assert "STALLED" in res.stderr
    assert "do NOT loosen the brakes" in res.stderr


def test_iteration_cap_stops_a_gate_treadmill(tmp_path):
    """Progress every iteration but never the final gate → the cap exits nonzero."""
    proj = _project(tmp_path, gates=["code-review", "build-green"])
    body = (
        'n=$(cat .claude/count 2>/dev/null || echo 0); n=$((n+1)); echo "$n" > .claude/count\n'
        'printf \'{"status": "active", "last_gate_resolved": "gate-%s"}\' "$n" > .claude/state/pipeline-snapshot.json'
    )
    env = _claude_shim(tmp_path, body)
    res = _run(proj, env, {"SDLC_MAX_ITER": "3"})
    assert res.returncode == 1
    assert "iteration cap (3) reached" in res.stderr
    assert (proj / ".claude" / "count").read_text().strip() == "3"


def test_refuses_to_guess_a_finish_line(tmp_path):
    """No snapshot YAML and no environment override means exit 2 with no Claude run."""
    proj = _project(tmp_path, gates=None)
    marker = tmp_path / "ran"
    env = _claude_shim(tmp_path, f"touch {marker}")
    res = _run(proj, env)
    assert res.returncode == 2
    assert "SDLC_FINAL_GATE" in res.stderr
    assert not marker.exists(), "claude must not run without a finish line"


def test_requires_project_root(tmp_path):
    (tmp_path / "elsewhere").mkdir()
    env = _claude_shim(tmp_path, "true")
    res = _run(tmp_path / "elsewhere", env)
    assert res.returncode == 2
    assert "project root" in res.stderr


def test_default_prompt_requires_evidence_bound_findings_before_a_transition():
    script = SCRIPT.read_text(encoding="utf-8")
    assert "pipeline record-findings" in script
    assert "all five exact severity counts" in script
    assert "project-contained evidence report" in script


def test_refuses_raw_completed_status_when_strict_validation_fails(tmp_path):
    proj = _project(tmp_path, gates=["code-review", "build-green"])
    env = _claude_shim(
        tmp_path,
        _write_gate("build-green", status="completed"),
        validator_body='echo "FAIL invalid terminal snapshot" >&2\nexit 1',
    )

    res = _run(proj, env)

    assert res.returncode == 1
    assert "REFUSING unvalidated completed status" in res.stderr
    assert "invalid terminal snapshot" in res.stderr


def test_nonzero_claude_exit_does_not_abort_the_loop(tmp_path):
    """A failed iteration is the stall brake's job, not an abort — progress still counts."""
    proj = _project(tmp_path, gates=["code-review", "build-green"])
    env = _claude_shim(
        tmp_path, _write_gate("build-green", status="completed") + "\nexit 1"
    )
    res = _run(proj, env)
    assert res.returncode == 0, res.stderr
    assert "pipeline complete and strictly validated" in res.stdout
    assert "last resolved gate: build-green" in res.stdout
