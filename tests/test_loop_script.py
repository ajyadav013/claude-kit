"""Behavior of the shipped bounded headless loop (templates/scripts/sdlc-loop.sh).

Runs the real script with a fake ``claude`` CLI on PATH. Each case asserts one brake:
final-gate completion (exit 0), stall detection (exit 1), the iteration cap (exit 1),
the missing-finish-line refusal (exit 2), and final-gate auto-detection from the same
``yaml.safe_dump(sort_keys=False)`` serialization scaffold writes.
"""

from __future__ import annotations

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


def _claude_shim(tmp_path: Path, body: str) -> dict[str, str]:
    """Put a fake ``claude`` CLI on PATH; ``body`` is the bash it runs per invocation."""
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    shim = bindir / "claude"
    shim.write_text("#!/usr/bin/env bash\n" + body + "\n", encoding="utf-8")
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
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


def _write_gate(gate: str) -> str:
    """Shim body: write the pipeline snapshot with the given last_gate_passed token."""
    # Plain concatenation — str.format/f-strings would misread the JSON braces as fields.
    return (
        'printf \'{"last_gate_passed": "%s"}\' "' + gate + '"'
        " > .claude/state/pipeline-snapshot.json"
    )


def test_completes_when_final_gate_reached(tmp_path):
    proj = _project(tmp_path, gates=["code-review", "build-green"])
    env = _claude_shim(tmp_path, _write_gate("build-green"))
    res = _run(proj, env)
    assert res.returncode == 0, res.stderr
    assert "pipeline complete: build-green" in res.stdout


def test_autodetects_last_gate_from_enterprise_snapshot(tmp_path):
    """The awk parser picks the LAST entry of `gates:` — not the first, not a selection item."""
    proj = _project(tmp_path, gates=ENTERPRISE_GATES)
    env = _claude_shim(tmp_path, _write_gate("acceptance"))
    res = _run(proj, env)
    assert res.returncode == 0, res.stderr
    assert "final gate 'acceptance'" in res.stdout


def test_env_override_beats_snapshot(tmp_path):
    proj = _project(tmp_path, gates=["code-review", "build-green"])
    env = _claude_shim(tmp_path, _write_gate("code-review"))
    res = _run(proj, env, {"SDLC_FINAL_GATE": "code-review"})
    assert res.returncode == 0, res.stderr
    assert "pipeline complete: code-review" in res.stdout


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
        'printf \'{"last_gate_passed": "gate-%s"}\' "$n" > .claude/state/pipeline-snapshot.json'
    )
    env = _claude_shim(tmp_path, body)
    res = _run(proj, env, {"SDLC_MAX_ITER": "3"})
    assert res.returncode == 1
    assert "iteration cap (3) reached" in res.stderr
    assert (proj / ".claude" / "count").read_text().strip() == "3"


def test_refuses_to_guess_a_finish_line(tmp_path):
    """No snapshot yaml (the init.sh fallback case) + no env override → exit 2, no claude runs."""
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


def test_nonzero_claude_exit_does_not_abort_the_loop(tmp_path):
    """A failed iteration is the stall brake's job, not an abort — progress still counts."""
    proj = _project(tmp_path, gates=["code-review", "build-green"])
    env = _claude_shim(tmp_path, _write_gate("build-green") + "\nexit 1")
    res = _run(proj, env)
    assert res.returncode == 0, res.stderr
    assert "pipeline complete: build-green" in res.stdout
