"""Behavioral tests for the normalized registered-hook adapter."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from claude_kit.cli import app
from claude_kit.hook_adapter import extract_shell_read_paths, run_registered_hook
from claude_kit.hook_runtime import HookDisposition
from claude_kit.provider_renderers import CodexRenderer

REPO = Path(__file__).resolve().parents[1]
RUNNER = CliRunner()


def _payload(tool_name: str, tool_input: dict) -> dict:
    return {
        "session_id": "positive-control",
        "cwd": "/ignored/untrusted/cwd",
        "hook_event_name": "PreToolUse",
        "tool_name": tool_name,
        "tool_input": tool_input,
    }


def _install_script(project: Path, provider: str, script: str) -> None:
    if provider == "claude":
        destination = project / ".claude" / "hooks" / script
    else:
        destination = project / ".codex" / "hooks" / "scripts" / script
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPO / "hooks" / "scripts" / script, destination)


@pytest.mark.parametrize(
    ("provider", "tool"), [("claude", "Bash"), ("codex", "exec_command")]
)
def test_registered_inline_rm_guard_blocks_on_both_hosts(
    tmp_path: Path, provider: str, tool: str
) -> None:
    result = run_registered_hook(
        provider,
        "guard-rm-rf",
        _payload(tool, {"command" if tool == "Bash" else "cmd": "rm -rf build"}),
        project_root=tmp_path,
    )
    assert result.disposition is HookDisposition.BLOCK
    assert "permissionDecision" in result.stdout
    assert "rm -rf" in result.stdout


@pytest.mark.parametrize(
    ("provider", "tool"), [("claude", "Read"), ("codex", "read_file")]
)
def test_registered_secret_read_guard_blocks_on_both_hosts(
    tmp_path: Path, provider: str, tool: str
) -> None:
    result = run_registered_hook(
        provider,
        "protect-secrets",
        _payload(tool, {"file_path": ".env"}),
        project_root=tmp_path,
    )
    assert result.disposition is HookDisposition.BLOCK
    assert "secrets file" in result.stdout


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("cat .env", (".env",)),
        ("head -n 5 credentials.json", ("5", "credentials.json")),
        ("tail ./id_rsa", ("./id_rsa",)),
        ("sed -n '1p' .env", (".env",)),
        ("grep TOKEN .env", (".env",)),
        ("rg TOKEN secrets.pem", ("secrets.pem",)),
        ("sh -c 'cat .env'", (".env",)),
        ("tool < .env", (".env",)),
        ("dd if=credentials.json of=/dev/null", ("credentials.json",)),
    ],
)
def test_shell_read_path_extraction_is_narrow_and_deterministic(
    command: str, expected: tuple[str, ...]
) -> None:
    assert extract_shell_read_paths(command) == expected


@pytest.mark.parametrize(
    "command",
    [
        "printf '%s\\n' .env",
        "git status --short",
        "echo credentials.json",
        "grep env src/config.py",
    ],
)
def test_shell_read_path_extraction_ignores_non_read_mentions(command: str) -> None:
    extracted = extract_shell_read_paths(command)
    assert not any(path in {".env", "credentials.json"} for path in extracted)


@pytest.mark.parametrize(
    "command",
    [
        "cat .env",
        "head -n 1 credentials.json",
        "sed -n '1p' key.pem",
        "grep TOKEN ./credentials",
        "sh -c 'tail id_ed25519'",
        "wc -c < .env",
    ],
)
def test_codex_generated_secret_guard_blocks_native_shell_reads(
    tmp_path: Path, command: str
) -> None:
    result = run_registered_hook(
        "codex",
        "protect-secrets",
        _payload("unified_exec", {"cmd": command}),
        project_root=tmp_path,
    )
    assert result.disposition is HookDisposition.BLOCK
    assert result.exit_code == 0
    payload = json.loads(result.stdout)["hookSpecificOutput"]
    assert payload["permissionDecision"] == "deny"
    assert "refusing to read a secrets file" in payload["permissionDecisionReason"]


def test_codex_generated_secret_guard_allows_harmless_shell_read(
    tmp_path: Path,
) -> None:
    result = run_registered_hook(
        "codex",
        "protect-secrets",
        _payload("unified_exec", {"cmd": "cat README.md"}),
        project_root=tmp_path,
    )
    assert result.disposition is HookDisposition.ALLOW
    assert result.exit_code == 0
    assert result.stdout == result.stderr == ""


def test_codex_generated_secret_guard_fails_closed_on_malformed_shell_command(
    tmp_path: Path,
) -> None:
    result = run_registered_hook(
        "codex",
        "protect-secrets",
        _payload("unified_exec", {"cmd": "cat '.env"}),
        project_root=tmp_path,
    )
    assert result.disposition is HookDisposition.BLOCK
    assert result.exit_code == 2
    assert result.stdout == ""
    assert "blocking hook handler failed" in result.stderr


@pytest.mark.parametrize("provider", ["claude", "codex"])
@pytest.mark.parametrize(
    ("hook_id", "script", "command", "message"),
    [
        (
            "guard-push-main",
            "guard-push-main.sh",
            "git push origin main",
            "main/master",
        ),
        (
            "guard-destructive-git",
            "guard-destructive-git.sh",
            "git reset --hard HEAD~1",
            "reset --hard",
        ),
        (
            "guard-kubectl-delete",
            "guard-kubectl-delete.sh",
            "kubectl delete deployment api",
            "kubectl delete",
        ),
    ],
)
def test_registered_shell_script_guards_block_on_both_hosts(
    tmp_path: Path,
    provider: str,
    hook_id: str,
    script: str,
    command: str,
    message: str,
) -> None:
    _install_script(tmp_path, provider, script)
    tool = "Bash" if provider == "claude" else "shell"
    result = run_registered_hook(
        provider,
        hook_id,
        _payload(tool, {"command": command}),
        project_root=tmp_path,
    )
    assert result.disposition is HookDisposition.BLOCK
    assert message in result.stdout


@pytest.mark.parametrize("provider", ["claude", "codex"])
def test_registered_commit_secret_guard_blocks_on_both_hosts(
    tmp_path: Path, provider: str
) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".env").write_text("TOKEN=not-a-real-secret\n", encoding="utf-8")
    subprocess.run(["git", "add", ".env"], cwd=tmp_path, check=True)
    _install_script(tmp_path, provider, "guard-secrets.sh")
    tool = "Bash" if provider == "claude" else "exec_command"
    key = "command" if provider == "claude" else "cmd"
    result = run_registered_hook(
        provider,
        "guard-commit-secrets",
        _payload(tool, {key: "git commit -m test"}),
        project_root=tmp_path,
    )
    assert result.disposition is HookDisposition.BLOCK
    assert ".env" in result.stdout


def test_apply_patch_is_evaluated_once_per_exact_file_path(tmp_path: Path) -> None:
    script = tmp_path / ".codex" / "hooks" / "scripts" / "warn-sensitive-files.sh"
    script.parent.mkdir(parents=True)
    script.write_text(
        "#!/usr/bin/env bash\n"
        "input=$(cat)\n"
        "path=$(printf '%s' \"$input\" | jq -r .tool_input.file_path)\n"
        'jq -n --arg ctx "seen:$path" '
        "'{hookSpecificOutput:{hookEventName:\"PreToolUse\",additionalContext:$ctx}}'\n",
        encoding="utf-8",
    )
    patch = """*** Begin Patch
*** Update File: src/auth.py
@@
-old
+new
*** Add File: infra/policy.yaml
+enabled: true
*** End Patch
"""
    result = run_registered_hook(
        "codex",
        "warn-sensitive-files",
        _payload("apply_patch", {"command": patch}),
        project_root=tmp_path,
    )
    assert result.disposition is HookDisposition.ADVISORY
    rendered = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
    assert rendered == "seen:src/auth.py\n\nseen:infra/policy.yaml"


def test_advisory_script_failure_fails_open_but_blocker_failure_fails_closed(
    tmp_path: Path,
) -> None:
    advisory = tmp_path / ".codex/hooks/scripts/warn-sensitive-files.sh"
    advisory.parent.mkdir(parents=True)
    advisory.write_text("#!/usr/bin/env bash\nexit 9\n", encoding="utf-8")
    advisory_result = run_registered_hook(
        "codex",
        "warn-sensitive-files",
        _payload(
            "apply_patch",
            {"command": "*** Begin Patch\n*** Add File: a\n+x\n*** End Patch\n"},
        ),
        project_root=tmp_path,
    )
    assert advisory_result.exit_code == 0
    assert advisory_result.stdout == ""

    blocking = tmp_path / ".codex/hooks/scripts/guard-push-main.sh"
    blocking.write_text("#!/usr/bin/env bash\nexit 9\n", encoding="utf-8")
    blocking_result = run_registered_hook(
        "codex",
        "guard-push-main",
        _payload("shell", {"command": "git push origin main"}),
        project_root=tmp_path,
    )
    assert blocking_result.exit_code == 2
    assert "handler failed" in blocking_result.stderr


def test_hidden_hook_cli_forwards_stdin_and_process_result(tmp_path: Path) -> None:
    payload = _payload("exec_command", {"cmd": "rm -rf build"})
    result = RUNNER.invoke(
        app,
        [
            "hook-run",
            "--provider",
            "codex",
            "--hook-id",
            "guard-rm-rf",
            "--path",
            str(tmp_path),
        ],
        input=json.dumps(payload),
    )
    assert result.exit_code == 0
    document = json.loads(result.stdout)
    assert document["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_hidden_codex_hook_cli_discovers_project_from_nested_cwd(
    tmp_path: Path,
) -> None:
    hooks_dir = tmp_path / ".codex" / "hooks" / "scripts"
    hooks_dir.mkdir(parents=True)
    (tmp_path / ".codex" / "hooks.json").write_text('{"hooks": {}}\n', encoding="utf-8")
    (hooks_dir / "warn-sensitive-files.sh").write_text(
        "#!/usr/bin/env bash\n"
        'jq -n --arg ctx "$PWD" '
        "'{hookSpecificOutput:{hookEventName:\"PreToolUse\",additionalContext:$ctx}}'\n",
        encoding="utf-8",
    )
    nested = tmp_path / "src" / "package"
    nested.mkdir(parents=True)
    patch = "*** Begin Patch\n*** Add File: src/a.py\n+x = 1\n*** End Patch\n"

    result = RUNNER.invoke(
        app,
        [
            "hook-run",
            "--provider",
            "codex",
            "--hook-id",
            "warn-sensitive-files",
            "--path",
            str(nested),
            "--discover-project-root",
        ],
        input=json.dumps(_payload("apply_patch", {"command": patch})),
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"] == str(
        tmp_path.resolve()
    )


def test_codex_project_discovery_rejects_symlinked_hook_controls(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    (outside / "hooks" / "scripts").mkdir(parents=True)
    (outside / "hooks.json").write_text('{"hooks": {}}\n', encoding="utf-8")
    (tmp_path / ".codex").symlink_to(outside, target_is_directory=True)
    nested = tmp_path / "src"
    nested.mkdir()

    result = RUNNER.invoke(
        app,
        [
            "hook-run",
            "--provider",
            "codex",
            "--hook-id",
            "guard-rm-rf",
            "--path",
            str(nested),
            "--discover-project-root",
        ],
        input=json.dumps(_payload("exec_command", {"cmd": "rm -rf build"})),
    )

    assert result.exit_code == 2
    assert "refusing symlinked native hook controls" in result.output


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq not installed")
@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_generated_codex_writeback_stop_requests_one_native_continuation(
    tmp_path: Path,
) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    script = tmp_path / ".codex/hooks/scripts/verify-continuity-writeback.sh"
    script.parent.mkdir(parents=True)
    script.write_text(
        CodexRenderer(REPO)._adapt_hook_script(
            "verify-continuity-writeback.sh", frozenset()
        ),
        encoding="utf-8",
    )
    (tmp_path / ".codex/hooks.json").write_text('{"hooks": {}}\n', encoding="utf-8")
    continuity = tmp_path / ".ckit/CONTINUITY.md"
    continuity.parent.mkdir()
    continuity.write_text("# Continuity\n", encoding="utf-8")
    changed = tmp_path / "src.py"
    changed.write_text("x = 1\n", encoding="utf-8")
    os.utime(continuity, (1_700_000_000, 1_700_000_000))
    os.utime(changed, (1_700_000_010, 1_700_000_010))

    first = run_registered_hook(
        "codex",
        "verify-continuity-writeback",
        {"hook_event_name": "Stop", "stop_hook_active": False},
        project_root=tmp_path,
    )
    guarded = run_registered_hook(
        "codex",
        "verify-continuity-writeback",
        {"hook_event_name": "Stop", "stop_hook_active": True},
        project_root=tmp_path,
    )

    assert first.disposition is HookDisposition.BLOCK
    assert json.loads(first.stdout)["decision"] == "block"
    assert "RARV step 4" in json.loads(first.stdout)["reason"]
    assert guarded.disposition is HookDisposition.ALLOW
    assert guarded.stdout == guarded.stderr == ""


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq not installed")
@pytest.mark.parametrize(
    ("hook_id", "script_name", "package_script", "diagnostic", "npm_exit"),
    [
        ("lint-fix", "lint-fix.sh", "lint", "problem: generated lint", 0),
        ("type-check", "type-check.sh", "typecheck", "error TS2304", 1),
    ],
)
def test_generated_codex_feedback_stops_request_one_native_continuation(
    tmp_path: Path,
    hook_id: str,
    script_name: str,
    package_script: str,
    diagnostic: str,
    npm_exit: int,
) -> None:
    script = tmp_path / ".codex/hooks/scripts" / script_name
    script.parent.mkdir(parents=True)
    script.write_text(
        CodexRenderer(REPO)._adapt_hook_script(script_name, frozenset()),
        encoding="utf-8",
    )
    (tmp_path / ".codex/hooks.json").write_text('{"hooks": {}}\n', encoding="utf-8")
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {package_script: "tool"}}), encoding="utf-8"
    )
    shim = tmp_path / "bin"
    shim.mkdir()
    npm = shim / "npm"
    npm.write_text(
        f"#!/bin/sh\nprintf '%s\\n' {shlex.quote(diagnostic)}\nexit {npm_exit}\n",
        encoding="utf-8",
    )
    npm.chmod(0o755)
    env = {
        "PATH": f"{shim}:{os.environ['PATH']}",
        "CKIT_AUTOFIX": "1",
    }

    first = run_registered_hook(
        "codex",
        hook_id,
        {"hook_event_name": "Stop", "stop_hook_active": False},
        project_root=tmp_path,
        env=env,
    )
    guarded = run_registered_hook(
        "codex",
        hook_id,
        {"hook_event_name": "Stop", "stop_hook_active": True},
        project_root=tmp_path,
        env=env,
    )

    assert first.disposition is HookDisposition.BLOCK
    assert json.loads(first.stdout)["decision"] == "block"
    assert diagnostic in json.loads(first.stdout)["reason"]
    assert guarded.disposition is HookDisposition.ALLOW
    assert guarded.stdout == guarded.stderr == ""


@pytest.mark.parametrize(
    ("body", "blocked"),
    [
        ('+{"hooks": {}}', False),
        ('+{"hooks": ', True),
    ],
)
def test_codex_settings_guard_reconstructs_apply_patch_additions(
    tmp_path: Path, body: str, blocked: bool
) -> None:
    _install_script(tmp_path, "codex", "validate-settings.sh")
    patch = f"*** Begin Patch\n*** Add File: .codex/hooks.json\n{body}\n*** End Patch\n"
    result = run_registered_hook(
        "codex",
        "validate-settings",
        _payload("apply_patch", {"command": patch}),
        project_root=tmp_path,
    )
    assert (result.disposition is HookDisposition.BLOCK) is blocked


def test_codex_settings_guard_reconstructs_updates_and_blocks_deletion(
    tmp_path: Path,
) -> None:
    _install_script(tmp_path, "codex", "validate-settings.sh")
    settings = tmp_path / ".codex" / "hooks.json"
    settings.write_text('{\n  "hooks": {}\n}\n', encoding="utf-8")

    valid_patch = """*** Begin Patch
*** Update File: .codex/hooks.json
@@
-  "hooks": {}
+  "hooks": {"SessionStart": []}
*** End Patch
"""
    valid = run_registered_hook(
        "codex",
        "validate-settings",
        _payload("apply_patch", {"command": valid_patch}),
        project_root=tmp_path,
    )
    assert valid.disposition is HookDisposition.ALLOW

    invalid_patch = valid_patch.replace(
        '+  "hooks": {"SessionStart": []}', '+  "hooks": {'
    )
    invalid = run_registered_hook(
        "codex",
        "validate-settings",
        _payload("apply_patch", {"command": invalid_patch}),
        project_root=tmp_path,
    )
    assert invalid.disposition is HookDisposition.BLOCK
    assert "would not be valid JSON" in invalid.stdout

    deletion = run_registered_hook(
        "codex",
        "validate-settings",
        _payload(
            "apply_patch",
            {
                "command": "*** Begin Patch\n*** Delete File: .codex/hooks.json\n*** End Patch\n"
            },
        ),
        project_root=tmp_path,
    )
    assert deletion.disposition is HookDisposition.BLOCK
    assert "refusing to delete" in deletion.stdout


def test_claude_settings_guard_has_valid_and_invalid_positive_controls(
    tmp_path: Path,
) -> None:
    _install_script(tmp_path, "claude", "validate-settings.sh")
    valid = run_registered_hook(
        "claude",
        "validate-settings",
        _payload(
            "Write",
            {"file_path": ".claude/settings.json", "content": '{"hooks": {}}'},
        ),
        project_root=tmp_path,
    )
    assert valid.disposition is HookDisposition.ALLOW
    invalid = run_registered_hook(
        "claude",
        "validate-settings",
        _payload(
            "Write",
            {"file_path": ".claude/settings.json", "content": '{"hooks": '},
        ),
        project_root=tmp_path,
    )
    assert invalid.disposition is HookDisposition.BLOCK
    assert "invalid settings.json" in invalid.stdout


@pytest.mark.parametrize("provider", ["claude", "codex"])
def test_every_shell_blocker_has_a_harmless_allow_control(
    tmp_path: Path, provider: str
) -> None:
    for script in (
        "guard-push-main.sh",
        "guard-destructive-git.sh",
        "guard-secrets.sh",
        "guard-kubectl-delete.sh",
    ):
        _install_script(tmp_path, provider, script)
    tool = "Bash" if provider == "claude" else "exec_command"
    key = "command" if provider == "claude" else "cmd"
    for hook_id, command in (
        ("guard-rm-rf", "rm -r build"),
        ("guard-push-main", "git push origin feature/safe"),
        ("guard-destructive-git", "git status --short"),
        ("guard-commit-secrets", "git status --short"),
        ("guard-kubectl-delete", "kubectl get deployments"),
    ):
        result = run_registered_hook(
            provider,
            hook_id,
            _payload(tool, {key: command}),
            project_root=tmp_path,
        )
        assert result.disposition is HookDisposition.ALLOW, hook_id

    read_tool = "Read" if provider == "claude" else "read_file"
    safe_read = run_registered_hook(
        provider,
        "protect-secrets",
        _payload(read_tool, {"file_path": "src/config.py"}),
        project_root=tmp_path,
    )
    assert safe_read.disposition is HookDisposition.ALLOW
    if provider == "codex":
        safe_shell_read = run_registered_hook(
            provider,
            "protect-secrets",
            _payload("unified_exec", {"cmd": "cat README.md"}),
            project_root=tmp_path,
        )
        assert safe_shell_read.disposition is HookDisposition.ALLOW
