"""Fail-closed behavior of the shipped headless-loop compatibility entrypoint."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None, reason="bash not available"
)

SCRIPT = Path(__file__).resolve().parents[1] / "templates" / "scripts" / "sdlc-loop.sh"


def _project(tmp_path: Path, *, state_root: str = ".ckit") -> Path:
    project = tmp_path / "project"
    (project / state_root / "state").mkdir(parents=True)
    return project


def _environment(
    tmp_path: Path, *, validator_exit: int = 0, host_marker: Path | None = None
) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    validator = bin_dir / "ckit"
    validator.write_text(
        "#!/usr/bin/env bash\n"
        '[ "$*" = "pipeline validate . --strict" ] || exit 64\n'
        f"exit {validator_exit}\n",
        encoding="utf-8",
    )
    validator.chmod(validator.stat().st_mode | stat.S_IXUSR)
    for host in ("claude", "codex"):
        shim = bin_dir / host
        body = f"touch {host_marker}\n" if host_marker is not None else "exit 99\n"
        shim.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8")
        shim.chmod(shim.stat().st_mode | stat.S_IXUSR)
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    return env


def _run(project: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )


@pytest.mark.parametrize("state_root", [".ckit", ".claude"])
def test_completed_run_succeeds_only_after_strict_validation(
    tmp_path: Path, state_root: str
) -> None:
    project = _project(tmp_path, state_root=state_root)
    snapshot = {
        "schema_version": 2,
        "run_id": "completed-run",
        "status": "completed",
        "last_gate_resolved": "build-green",
    }
    (project / state_root / "state/pipeline-snapshot.json").write_text(
        json.dumps(snapshot), encoding="utf-8"
    )

    result = _run(project, _environment(tmp_path))

    assert result.returncode == 0, result.stderr
    assert "pipeline complete and strictly validated" in result.stdout
    assert "build-green" in result.stdout


def test_unvalidated_completed_run_is_refused(tmp_path: Path) -> None:
    project = _project(tmp_path)
    (project / ".ckit/state/pipeline-snapshot.json").write_text(
        json.dumps({"status": "completed"}), encoding="utf-8"
    )

    result = _run(project, _environment(tmp_path, validator_exit=1))

    assert result.returncode == 1
    assert "REFUSING unvalidated completed status" in result.stderr


@pytest.mark.parametrize("status", ["active", "aborted", "waiting"])
def test_noncompleted_run_is_unsupported_and_starts_no_host(
    tmp_path: Path, status: str
) -> None:
    project = _project(tmp_path)
    (project / ".ckit/state/pipeline-snapshot.json").write_text(
        json.dumps({"status": status}), encoding="utf-8"
    )
    marker = tmp_path / "host-started"

    result = _run(project, _environment(tmp_path, host_marker=marker))

    assert result.returncode == 3
    assert "Unsupported" in result.stderr
    assert "descendant-process containment" in result.stderr
    assert not marker.exists()


def test_malformed_or_missing_snapshot_fails_without_a_host(tmp_path: Path) -> None:
    project = _project(tmp_path)
    marker = tmp_path / "host-started"
    env = _environment(tmp_path, host_marker=marker)

    missing = _run(project, env)
    assert missing.returncode == 2
    (project / ".ckit/state/pipeline-snapshot.json").write_text(
        "not json\n", encoding="utf-8"
    )
    malformed = _run(project, env)

    assert malformed.returncode == 1
    assert "malformed pipeline snapshot" in malformed.stderr
    assert not marker.exists()


def test_script_contains_no_dormant_host_launch_or_token_path() -> None:
    script = SCRIPT.read_text(encoding="utf-8")

    assert "subprocess.Popen" not in script
    assert "begin_headless_iteration" not in script
    assert "CKIT_PIPELINE_TRANSITION_TOKEN" not in script
    assert "codex exec" not in script
    assert "claude -p" not in script
