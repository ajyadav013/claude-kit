"""Privacy hardening of the background learning-capture hook (P0-2).

`hooks/scripts/capture-learnings.sh` reads a session transcript and spawns a background job that can
write to a *committed* store (`.claude/agent-memory/`). These tests exercise its privacy helpers
directly by sourcing the script (a run-vs-source guard stops the side-effecting dispatch when sourced)
and asserting: secret-bearing files are dropped from the changed-file list, leaked-credential value
shapes are redacted, and the line cap is env-overridable.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "hooks" / "scripts" / "capture-learnings.sh"

_NEED_JQ = pytest.mark.skipif(
    shutil.which("jq") is None,
    reason="jq required for the capture hook's transcript parsing",
)


def _bash(snippet: str, env: dict | None = None) -> str:
    """Source the capture script (helpers only, via its source-guard) and run `snippet`; return stdout."""
    proc = subprocess.run(
        ["bash", "-c", f'source "{SCRIPT}"\n{snippet}'],
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def _edit(path: str) -> str:
    return json.dumps(
        {
            "message": {
                "content": [
                    {"type": "tool_use", "name": "Edit", "input": {"file_path": path}}
                ]
            }
        }
    )


@_NEED_JQ
def test_changed_files_excludes_sensitive_paths(tmp_path):
    t = tmp_path / "transcript.jsonl"
    t.write_text(
        "\n".join(
            [
                _edit("src/app.py"),
                _edit(".env"),
                _edit(".env.local"),
                _edit("config/credentials.json"),
                _edit("deploy/tls.pem"),
                _edit("secrets/id_rsa.key"),
                _edit("src/util.ts"),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    files = set(_bash(f'changed_files "{t}"').split())
    assert files == {"src/app.py", "src/util.ts"}, files


@_NEED_JQ
def test_changed_files_honours_max_lines_env(tmp_path):
    t = tmp_path / "transcript.jsonl"
    t.write_text(
        "\n".join(_edit(f"src/a{i}.py") for i in range(5)) + "\n", encoding="utf-8"
    )
    out = _bash(f'changed_files "{t}"', env={"CLAUDE_KIT_CAPTURE_MAX_LINES": "2"})
    assert len([line for line in out.split() if line]) == 2


@pytest.mark.parametrize(
    "secret",
    [
        "ghp_" + "A" * 36,
        "AKIA" + "B" * 16,
        "sk_live_" + "c" * 24,
        "xoxb-" + "1" * 14,
        "-----BEGIN RSA PRIVATE KEY-----",
    ],
)
def test_redact_masks_secret_value_shapes(secret):
    out = _bash(f'printf "%s\\n" "pre {secret} post" | _redact')
    assert "[REDACTED]" in out
    assert secret not in out


def test_redact_leaves_ordinary_text_untouched():
    out = _bash(
        'printf "%s\\n" "just a normal sentence about API_KEY naming" | _redact'
    )
    assert "[REDACTED]" not in out
    assert "API_KEY" in out


def test_caps_default_to_bounded_values():
    out = _bash('printf "lines=%s bytes=%s\\n" "$CAP_MAX_LINES" "$CAP_MAX_BYTES"')
    assert out.strip() == "lines=50 bytes=8000"


def test_prompt_carries_a_no_secrets_instruction():
    """The capture prompt must instruct the background agent never to record secrets/PII."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert "NEVER record secrets" in text


@_NEED_JQ
def test_end_mode_returns_immediately_and_detaches_the_capture(tmp_path):
    """SessionEnd runs under a 1.5s default budget: `end` must mark done and return before the
    transcript scan, with the scan + spawn detached to the background (the capture still fires)."""
    import time

    bindir = tmp_path / "bin"
    bindir.mkdir()
    ran = tmp_path / "claude-ran.txt"
    shim = bindir / "claude"
    shim.write_text(f'#!/usr/bin/env bash\necho ran > "{ran}"\n', encoding="utf-8")
    shim.chmod(0o755)

    proj = tmp_path / "proj"
    (proj / ".claude" / "agent-memory").mkdir(parents=True)
    hook_tmp = tmp_path / "hook-tmp"
    hook_tmp.mkdir()
    transcript = tmp_path / "sess-endmode.jsonl"
    transcript.write_text(_edit("src/app.py") + "\n", encoding="utf-8")

    env = {
        **os.environ,
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "TMPDIR": str(hook_tmp),
    }
    env.pop("CLAUDE_KIT_NO_AUTOCAPTURE", None)
    proc = subprocess.run(
        ["bash", str(SCRIPT), "end"],
        input=json.dumps({"transcript_path": str(transcript), "cwd": str(proj)}),
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 0
    # Done-marker is written by the hook itself, before any heavy work.
    assert (hook_tmp / "claude-kit-captured-sess-endmode.done").exists()
    # The detached job still fires the (shimmed) claude capture.
    for _ in range(100):
        if ran.exists():
            break
        time.sleep(0.1)
    assert ran.exists(), "background capture never ran"
