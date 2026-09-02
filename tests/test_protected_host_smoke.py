"""Deterministic contracts for the credentialed native-host behavior harness."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from claude_kit.models import INIT_OPTIONS_SCHEMA
from scripts import protected_host_smoke as smoke

ROOT = Path(__file__).parents[1]


def _ckit_wrapper(directory: Path) -> Path:
    wrapper = directory / "ckit"
    python = directory / "python"
    environment = shutil.which("env") or "/usr/bin/env"
    wrapper.write_text(
        f"#!/bin/sh\nexec {shlex.quote(environment)} {shlex.quote(sys.executable)} "
        '-m claude_kit "$@"\n',
        encoding="utf-8",
    )
    wrapper.chmod(0o700)
    python.write_text(
        f'#!/bin/sh\nexec {shlex.quote(sys.executable)} "$@"\n',
        encoding="utf-8",
    )
    python.chmod(0o700)
    return wrapper


def _fake_managed_codex(directory: Path) -> tuple[Path, Path]:
    executable = directory / "codex"
    invocation_log = directory / "managed-codex-invocations.jsonl"
    source = f"""#!{sys.executable}
import json
import os
import sys
from pathlib import Path

LOG = Path({json.dumps(str(invocation_log))})
SECRET_NAMES = {{
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "CODEX_ACCESS_TOKEN",
    "CODEX_API_KEY",
    "OPENAI_API_KEY",
}}

def record(document):
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(document, sort_keys=True) + "\\n")

args = sys.argv[1:]
present = sorted(name for name in SECRET_NAMES if os.environ.get(name))
if args == ["--version"]:
    record({{"kind": "version", "provider_secret_env": present}})
    print("codex-cli 0.147.0")
    raise SystemExit(0)
if args[:2] == ["features", "list"]:
    # Compatibility discovery is local and must remain credential-free. The
    # provider credential belongs only to the later native execution process.
    assert present == []
    disabled = [args[index + 1] for index, value in enumerate(args[:-1]) if value == "--disable"]
    record({{
        "kind": "features",
        "disabled": disabled,
        "provider_secret_env": present,
    }})
    for feature in disabled:
        print(f"{{feature}} stable false")
    raise SystemExit(0)
if args and args[0] == "exec":
    assert present == ["OPENAI_API_KEY"]
    disabled = {{args[index + 1] for index, value in enumerate(args[:-1]) if value == "--disable"}}
    assert {{"hooks", "multi_agent", "plugins", "shell_tool", "unified_exec"}} <= disabled
    assert "--ignore-rules" in args
    assert args[args.index("--sandbox") + 1] == "read-only"
    overrides = [args[index + 1] for index, value in enumerate(args[:-1]) if value == "-c"]
    assert 'approval_policy="never"' in overrides
    assert "agents.enabled=false" in overrides
    assert "hooks={{}}" in overrides
    assert "mcp_servers={{}}" in overrides
    assert 'web_search="disabled"' in overrides
    prompt = sys.stdin.read()
    credential = os.environ["OPENAI_API_KEY"]
    assert credential not in prompt
    assert "Declared role write scope (verified against the managed git worktree): none" in prompt
    if "Native role: risk-classifier" in prompt:
        assert "Required evidence references: artifact://scope-record" in prompt
        evidence = {{
            "scope-record": {{
                "mode": "D",
                "surfaces": ["repository"],
                "constraints": ["passive read-only classification"],
                "risks": [],
            }}
        }}
        references = ["artifact://scope-record"]
    elif "Native role: em-reviewer" in prompt:
        assert "Stage planning-merge:" in prompt
        assert "artifact://architecture-plan" in prompt
        assert "artifact://review-verdict" in prompt
        assert "specs/protected_gate_owner_spec.md" in prompt
        evidence = {{
            "architecture-plan": {{
                "boundaries": ["committed documentation-only fixture"],
                "dependencies": ["fixture-seeded spec-complete gate"],
                "interfaces": ["public managed pipeline ledger"],
                "verification": ["owner-bound em-approved gate bundle"],
            }},
            "review-verdict": {{
                "status": "PASS",
                "reviewer": "em-reviewer",
                "findings": [],
                "evidence": ["specs/protected_gate_owner_spec.md"],
            }},
        }}
        references = [
            "artifact://architecture-plan",
            "artifact://review-verdict",
        ]
    else:
        raise AssertionError("unexpected native managed role")
    record({{
        "kind": "exec",
        "argv": args,
        "prompt": prompt,
        "provider_secret_env": present,
    }})
    print(json.dumps({{
        "status": "succeeded",
        "output": json.dumps({{"evidence": evidence}}, sort_keys=True),
        "evidence": references,
    }}, sort_keys=True))
    raise SystemExit(0)
record({{"kind": "unexpected", "argv": args, "provider_secret_env": present}})
raise SystemExit(19)
"""
    executable.write_text(source, encoding="utf-8")
    executable.chmod(0o700)
    return executable, invocation_log


@pytest.fixture(scope="module")
def prepared_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    parent = tmp_path_factory.mktemp("protected-host")
    root = parent / "smoke"
    smoke._prepare(root, ckit_executable=str(_ckit_wrapper(parent)))
    return root.resolve()


def _control(root: Path) -> dict:
    return json.loads((root / "control/control.json").read_text(encoding="utf-8"))


def _append_positive_events(
    root: Path, provider: str, *, include_stop: bool = True
) -> None:
    log = root / "project" / smoke.EVENT_LOG
    for event, role in (
        ("session-start", False),
        ("subagent-start", True),
        ("post-tool", False),
    ):
        smoke._append_event(
            log,
            {
                "provider": provider,
                "event": event,
                "credential_env_present": [],
                "risk_classifier": role,
                "agent_type": "risk-classifier" if role else None,
                "target_requested": False,
                "definition_path": None,
            },
        )
    if include_stop:
        blocked, guarded = _exercise_generated_stop(root, provider)
        assert blocked.returncode == guarded.returncode == 0


def _probe_nonce(project: Path, prefix: str) -> str:
    pattern = re.compile(rf"{re.escape(prefix)}-[0-9a-f]{{32}}")
    matches: set[str] = set()
    for path in project.rglob("*"):
        if path.is_file() and ".git" not in path.parts:
            matches.update(
                pattern.findall(path.read_text(encoding="utf-8", errors="ignore"))
            )
    assert len(matches) == 1
    return next(iter(matches))


def _fixture_observation(root: Path, provider: str) -> dict[str, str]:
    project = root / "project"
    pipeline = smoke._pipeline_document(project)
    return {
        "instruction_nonce": _probe_nonce(project, f"{provider}-instruction"),
        "skill_nonce": _probe_nonce(project, f"{provider}-skill"),
        "skill_argument": smoke.SKILL_ARGUMENT,
        "real_skill_marker": smoke.REAL_SKILL_MARKER,
        "agent_nonce": _probe_nonce(project, f"{provider}-agent"),
        "role_result": "low",
        "gate_digest": str(pipeline["gate_definition_digest"]),
        "pipeline_stage": str(pipeline["stage"]),
        "gate_history_count": str(len(pipeline["gate_history"])),
        "prior_provider_transition": smoke._prior_pipeline_provider(project, pipeline),
        "blocking_reason": smoke.BLOCK_REASON,
        "advisory_marker": smoke.ADVISORY_MARKER,
    }


def _guard_proxy_command(root: Path, provider: str) -> str:
    project = root / "project"
    path = (
        project / ".claude/settings.json"
        if provider == "claude"
        else project / ".codex/hooks.json"
    )
    hooks = json.loads(path.read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
    commands = [
        entry["command"]
        for group in hooks
        for entry in group["hooks"]
        if "guard-proxy" in entry.get("command", "")
    ]
    assert len(commands) == 1
    return commands[0]


def _stop_proxy_command(root: Path, provider: str) -> str:
    project = root / "project"
    path = (
        project / ".claude/settings.json"
        if provider == "claude"
        else project / ".codex/hooks.json"
    )
    hooks = json.loads(path.read_text(encoding="utf-8"))["hooks"]["Stop"]
    commands = [
        entry["command"]
        for group in hooks
        for entry in group["hooks"]
        if "stop-proxy" in entry.get("command", "")
    ]
    assert len(commands) == 1
    return commands[0]


def _exercise_generated_stop(
    root: Path, provider: str
) -> tuple[subprocess.CompletedProcess[str], subprocess.CompletedProcess[str]]:
    project = root / "project"
    command = _stop_proxy_command(root, provider)

    def invoke(active: bool) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["/bin/sh", "-c", command],
            cwd=project,
            env=dict(os.environ),
            input=json.dumps({"hook_event_name": "Stop", "stop_hook_active": active}),
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )

    return invoke(False), invoke(True)


def _exercise_generated_guard(
    root: Path, provider: str
) -> tuple[subprocess.CompletedProcess[str], subprocess.CompletedProcess[str]]:
    project = root / "project"
    command = _guard_proxy_command(root, provider)
    tool = "Read" if provider == "claude" else "unified_exec"
    key = "file_path" if provider == "claude" else "cmd"

    def invoke(value: str, *, extra_env: dict[str, str] | None = None):
        envelope = {
            "session_id": f"{provider}-guard-control",
            "cwd": str(project),
            "hook_event_name": "PreToolUse",
            "tool_name": tool,
            "tool_input": {key: value},
        }
        environment = dict(os.environ)
        if extra_env:
            environment.update(extra_env)
        return subprocess.run(
            ["/bin/sh", "-c", command],
            cwd=project,
            env=environment,
            input=json.dumps(envelope),
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )

    safe = invoke("README.md" if provider == "claude" else "cat README.md")
    blocked = invoke(
        smoke.BLOCK_TARGET if provider == "claude" else f"cat {smoke.BLOCK_TARGET}",
        extra_env={"OPENAI_API_KEY": "must-be-stripped-by-env-i"},
    )
    return safe, blocked


def test_prepare_uses_exact_both_scaffold_and_real_native_components(
    prepared_root: Path,
) -> None:
    project = prepared_root / "project"
    control = _control(prepared_root)

    assert smoke.INIT_OPTIONS_SCHEMA_VERSION == INIT_OPTIONS_SCHEMA
    assert control["scaffold"]["runtimes"] == ["claude", "codex"]
    assert control["scaffold"]["state_root"] == ".ckit"
    inventory = control["scaffold"]["selected_native_inventory"]
    assert inventory[".claude/skills/using-agent-skills/SKILL.md"] == {
        "provider": "claude",
        "component_id": "skill://using-agent-skills",
        "sha256": inventory[".claude/skills/using-agent-skills/SKILL.md"]["sha256"],
    }
    assert (
        inventory[".agents/skills/using-agent-skills/SKILL.md"]["component_id"]
        == "skill://using-agent-skills"
    )
    assert inventory[".claude/agents/risk-classifier.md"]["component_id"] == (
        "agent://risk-classifier"
    )
    assert inventory[".codex/agents/risk-classifier.toml"]["component_id"] == (
        "agent://risk-classifier"
    )
    assert inventory[".claude/settings.json"]["component_id"] == (
        "artifact://claude-claude-settings.json"
    )
    assert inventory[".codex/hooks.json"]["component_id"] == "artifact://codex-hooks"
    assert (project / ".ckit/config/init-options.json").is_file()
    assert not (project / ".claude/state").exists()

    assert control["schema_version"] == 2
    assert "expected" not in control
    assert "blocked_canary" not in control
    assert set(control["expected_commitments"]) == {"claude", "codex"}
    for field in smoke.CONTROL_EXPECTED_FIELDS:
        assert re.fullmatch(
            r"[0-9a-f]{64}", control["expected_commitments"]["claude"][field]
        )
        assert (
            control["expected_commitments"]["claude"][field]
            != control["expected_commitments"]["codex"][field]
        )
    stack_snapshot = (project / ".ckit/config/stack-catalog.snapshot.yaml").read_text(
        encoding="utf-8"
    )
    installed_digest = control["scaffold"]["installed_gate_definition_digest"]
    assert f"gate_definition_digest: {installed_digest}" in stack_snapshot
    pipeline = smoke._pipeline_document(project)
    assert pipeline["status"] == "active"
    assert pipeline["mode"] == "D"
    assert pipeline["stage"] == "code-review"
    assert pipeline["ordered_gates"] == ["code-review", "build-green"]
    assert pipeline["gate_history"] == []
    for provider in ("claude", "codex"):
        assert control["expected_commitments"][provider]["gate_digest"] == (
            smoke._commitment(
                provider, "gate_digest", pipeline["gate_definition_digest"]
            )
        )
    assert len(control["pipeline_checkpoints"]["claude"]) == 64
    assert control["pipeline_checkpoints"]["codex"] is None
    assert (project / smoke.BLOCK_TARGET).is_file()

    for provider, hooks_path, guard_needle in (
        (
            "claude",
            project / ".claude/settings.json",
            "refusing to read a secrets file",
        ),
        (
            "codex",
            project / ".codex/hooks.json",
            "--hook-id protect-secrets",
        ),
    ):
        hooks = json.loads(hooks_path.read_text(encoding="utf-8"))["hooks"]
        assert {
            "SessionStart",
            "SubagentStart",
            "PreToolUse",
            "PostToolUse",
            "Stop",
        } <= set(hooks)
        commands = [
            hook["command"]
            for groups in hooks.values()
            for group in groups
            for hook in group["hooks"]
        ]
        assert commands
        assert any(guard_needle in command for command in commands)
        probe_commands = [
            command for command in commands if "protected_host_smoke.py" in command
        ]
        assert probe_commands
        assert all(" -i " in command for command in probe_commands)
        assert any("protected_host_smoke.py" not in command for command in commands)
        assert all(
            secret not in command
            for command in probe_commands
            for secret in smoke.HOOK_SECRET_ENV
        )
        assert f"--provider {provider}" in "\n".join(probe_commands)
        guard_command = _guard_proxy_command(prepared_root, provider)
        guard = control["generated_guard_contract"][provider]
        assert guard["handler_id"] == "protect-secrets"
        assert guard["source_artifact"] == hooks_path.relative_to(project).as_posix()
        assert guard["command_sha256"] in guard_command

    sensitive = [
        _probe_nonce(project, f"{provider}-{kind}")
        for provider in ("claude", "codex")
        for kind in ("instruction", "skill", "agent")
    ] + [(project / smoke.BLOCK_TARGET).read_text(encoding="utf-8")]
    smoke._assert_control_has_no_plaintext(prepared_root / "control", sensitive)


def test_prepare_refuses_to_overwrite_an_existing_root(tmp_path: Path) -> None:
    root = tmp_path / "already-there"
    root.mkdir()
    with pytest.raises(smoke.SmokeError, match="refusing to overwrite"):
        smoke._prepare(root, ckit_executable="not-needed")


@pytest.mark.parametrize("provider", ["claude", "codex"])
def test_proxy_attributes_the_exact_generated_guard_and_relays_native_decision(
    prepared_root: Path, provider: str
) -> None:
    document = _control(prepared_root)
    _append_positive_events(prepared_root, provider)
    safe, blocked = _exercise_generated_guard(prepared_root, provider)

    assert safe.returncode == 0
    assert safe.stdout == safe.stderr == ""
    if provider == "claude":
        assert blocked.returncode == 2
        assert blocked.stdout == ""
        assert blocked.stderr == smoke.GENERATED_BLOCK_REASON + "\n"
    else:
        assert blocked.returncode == 0
        assert blocked.stderr == ""
        denial = json.loads(blocked.stdout)["hookSpecificOutput"]
        assert denial["permissionDecision"] == "deny"
        assert denial["permissionDecisionReason"] == smoke.GENERATED_BLOCK_REASON

    counts = smoke._assert_events(prepared_root / "project", provider, document)
    assert counts["generated-guard-block"] == 1
    assert counts["generated-guard-allow"] >= 1
    records = smoke._events(prepared_root / "project", provider)
    generated = [record for record in records if record["event"] == "generated-guard"]
    assert all(record["credential_env_present"] == [] for record in generated)
    assert all(
        record["handler_sha256"]
        == document["generated_guard_contract"][provider]["command_sha256"]
        for record in generated
    )


def test_pipeline_checkpoint_detects_host_mutation(
    prepared_root: Path, tmp_path: Path
) -> None:
    scratch = tmp_path / "checkpoint"
    shutil.copytree(prepared_root, scratch)
    document = _control(scratch)
    snapshot = scratch / "project" / smoke.PIPELINE_SNAPSHOT
    snapshot.write_text(snapshot.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(smoke.SmokeError, match="mutated the authoritative pipeline"):
        smoke._assert_pipeline_checkpoint(document, scratch / "project", "claude")


def test_hook_positive_controls_block_advise_and_hide_credentials(
    tmp_path: Path,
) -> None:
    script = ROOT / "scripts/protected_host_smoke.py"
    log = tmp_path / "events.jsonl"
    clean_env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path), "LANG": "C.UTF-8"}

    def run(event: str, envelope: dict, *, env: dict[str, str] | None = None):
        return subprocess.run(
            [
                sys.executable,
                str(script),
                "hook",
                "--provider",
                "codex",
                "--event",
                event,
                "--log",
                str(log),
            ],
            input=json.dumps(envelope),
            text=True,
            capture_output=True,
            check=False,
            env=env or clean_env,
            timeout=10,
        )

    assert run("session-start", {"hook_event_name": "SessionStart"}).returncode == 0
    assert (
        run(
            "subagent-start",
            {"hook_event_name": "SubagentStart", "agent_type": "risk-classifier"},
        ).returncode
        == 0
    )
    advisory = run(
        "post-tool",
        {"tool_input": {"file_path": str(smoke.PIPELINE_SNAPSHOT)}},
    )
    assert advisory.returncode == 0
    assert json.loads(advisory.stdout) == {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": smoke.ADVISORY_MARKER,
        }
    }
    claude_advisory = subprocess.run(
        [
            sys.executable,
            str(script),
            "hook",
            "--provider",
            "claude",
            "--event",
            "post-tool",
            "--log",
            str(log),
        ],
        input=json.dumps({"tool_input": {"file_path": str(smoke.PIPELINE_SNAPSHOT)}}),
        text=True,
        capture_output=True,
        check=False,
        env=clean_env,
        timeout=10,
    )
    assert json.loads(claude_advisory.stdout) == {
        "systemMessage": smoke.ADVISORY_MARKER
    }
    definition = run(
        "definition-read",
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "unified_exec",
            "tool_input": {"cmd": "cat AGENTS.md"},
        },
    )
    assert definition.returncode == 0
    denial = json.loads(definition.stdout)["hookSpecificOutput"]
    assert denial["permissionDecision"] == "deny"

    leaked_env = dict(clean_env)
    leaked_env["OPENAI_API_KEY"] = "unit-test-only"
    leaked = run("session-start", {}, env=leaked_env)
    assert leaked.returncode == 3
    assert "CKIT_SMOKE_CREDENTIAL_ENV_LEAK" in leaked.stderr
    records = [
        json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()
    ]
    assert records[-1]["credential_env_present"] == ["OPENAI_API_KEY"]


@pytest.mark.parametrize(
    ("provider", "tool_name", "tool_input", "expected"),
    [
        ("claude", "Read", {"file_path": "./CLAUDE.md"}, "CLAUDE.md"),
        (
            "codex",
            "unified_exec",
            {"cmd": "cat .agents/skills/ckit-protected-smoke/SKILL.md"},
            ".agents/skills/ckit-protected-smoke/SKILL.md",
        ),
        (
            "codex",
            "unified_exec",
            {"cmd": "cat .agents/skills/using-agent-skills/SKILL.md"},
            ".agents/skills/using-agent-skills/SKILL.md",
        ),
        ("codex", "unified_exec", {"cmd": "echo AGENTS.md"}, None),
    ],
)
def test_discovery_definition_read_detection_is_narrow(
    provider: str, tool_name: str, tool_input: dict, expected: str | None
) -> None:
    assert (
        smoke._protected_definition_request(
            provider, {"tool_name": tool_name, "tool_input": tool_input}
        )
        == expected
    )


@pytest.mark.parametrize(
    ("command", "blocked"),
    [
        ("cat .ckit/state/pipeline-snapshot.json", False),
        ("cat .ckit/STACK.md", False),
        ("cat .ckit/artifacts/protected-host/claude-code-review.json", False),
        ("cat .env", False),
        ("rg nonce .", True),
        ("rg nonce", True),
        ("grep -R nonce .", True),
        (
            "python -c 'from pathlib import Path; print(Path(\"AGENTS.md\").read_text())'",
            True,
        ),
        ("git grep nonce", True),
        ("find .. -type f", True),
        ("cat $(find . -name AGENTS.md)", True),
    ],
)
def test_codex_fixture_shell_read_boundary_fails_closed(
    command: str, blocked: bool
) -> None:
    violation = smoke._fixture_read_boundary_violation(
        "codex",
        {
            "tool_name": "unified_exec",
            "tool_input": {"cmd": command},
        },
    )
    assert (violation is not None) is blocked


@pytest.mark.parametrize("exit_code", [0, 2, 7])
def test_guard_proxy_relays_raw_input_streams_and_exit_code(
    tmp_path: Path, exit_code: int
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    log = project / smoke.EVENT_LOG
    handler = f"cat; printf relay-stderr >&2; exit {exit_code}"
    handler_sha256 = hashlib.sha256(handler.encode("utf-8")).hexdigest()
    raw = "not-json-but-forwarded-byte-for-byte"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/protected_host_smoke.py"),
            "guard-proxy",
            "--provider",
            "codex",
            "--handler-id",
            "protect-secrets",
            "--handler",
            handler,
            "--handler-sha256",
            handler_sha256,
            "--project",
            str(project),
            "--log",
            str(log),
        ],
        input=raw,
        text=True,
        capture_output=True,
        check=False,
        env={"PATH": os.environ["PATH"], "HOME": str(tmp_path), "LANG": "C.UTF-8"},
        timeout=10,
    )
    assert result.returncode == exit_code
    assert result.stdout == raw
    assert result.stderr == "relay-stderr"
    record = json.loads(log.read_text(encoding="utf-8"))
    assert record["generated_guard_disposition"] == "error"
    assert record["stdout_sha256"] == hashlib.sha256(raw.encode()).hexdigest()
    assert record["stderr_sha256"] == hashlib.sha256(b"relay-stderr").hexdigest()


def test_guard_proxy_rejects_a_tampered_handler_digest_before_execution(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    marker = tmp_path / "must-not-exist"
    handler = f"touch {shlex.quote(str(marker))}"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/protected_host_smoke.py"),
            "guard-proxy",
            "--provider",
            "claude",
            "--handler-id",
            "protect-secrets",
            "--handler",
            handler,
            "--handler-sha256",
            "0" * 64,
            "--project",
            str(project),
            "--log",
            str(project / smoke.EVENT_LOG),
        ],
        input="{}",
        text=True,
        capture_output=True,
        check=False,
        env={"PATH": os.environ["PATH"], "HOME": str(tmp_path), "LANG": "C.UTF-8"},
        timeout=10,
    )
    assert result.returncode == 1
    assert "handler digest mismatch" in result.stderr
    assert not marker.exists()


def test_native_guard_interpretation_rejects_extra_provider_streams() -> None:
    claude_stderr = (smoke.GENERATED_BLOCK_REASON + "\n").encode()
    assert (
        smoke._generated_guard_disposition(
            "claude", exit_code=2, stdout=b"extra", stderr=claude_stderr
        )
        == "error"
    )
    codex_stdout_hash, _stderr_hash, _exit = smoke._expected_guard_hashes(
        "codex", "block"
    )
    codex_stdout = (
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": smoke.GENERATED_BLOCK_REASON,
                }
            },
            separators=(",", ":"),
        )
        + "\n"
    ).encode()
    assert hashlib.sha256(codex_stdout).hexdigest() == codex_stdout_hash
    assert (
        smoke._generated_guard_disposition(
            "codex", exit_code=0, stdout=codex_stdout, stderr=b"extra"
        )
        == "error"
    )


def test_duplicate_generated_guard_blocks_fail_exactly_once_contract(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    handler_hash = "a" * 64
    document = {
        "generated_guard_contract": {
            "codex": {
                "handler_id": "protect-secrets",
                "source_artifact": ".codex/hooks.json",
                "command_sha256": handler_hash,
            }
        }
    }
    _append_positive_events(tmp_path, "codex", include_stop=False)

    def record(disposition: str, target: bool) -> dict:
        stdout_hash, stderr_hash, exit_code = smoke._expected_guard_hashes(
            "codex", disposition
        )
        return {
            "record_schema_version": 1,
            "provider": "codex",
            "event": "generated-guard",
            "handler_id": "protect-secrets",
            "handler_sha256": handler_hash,
            "generated_guard_disposition": disposition,
            "exit_code": exit_code,
            "stdout_sha256": stdout_hash,
            "stderr_sha256": stderr_hash,
            "credential_env_present": [],
            "native_operation": "shell",
            "target_requested": target,
        }

    log = project / smoke.EVENT_LOG
    smoke._append_event(log, record("allow", False))
    smoke._append_event(log, record("block", True))
    smoke._append_event(log, record("block", True))
    with pytest.raises(smoke.SmokeError, match="expected exactly 1"):
        smoke._assert_events(project, "codex", document)


def test_named_agent_proof_rejects_a_risk_classifier_substring(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    log = project / smoke.EVENT_LOG
    smoke._append_event(
        log,
        {"provider": "codex", "event": "session-start", "credential_env_present": []},
    )
    smoke._append_event(
        log,
        {
            "provider": "codex",
            "event": "subagent-start",
            "agent_type": "risk-classifier-helper",
            "risk_classifier": False,
            "credential_env_present": [],
        },
    )

    with pytest.raises(smoke.SmokeError, match="expected exactly 1"):
        smoke._assert_events(project, "codex", {})


def test_verifier_rejects_manual_reads_of_discovery_definitions(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    log = project / smoke.EVENT_LOG
    for event in (
        {
            "provider": "codex",
            "event": "session-start",
            "credential_env_present": [],
        },
        {
            "provider": "codex",
            "event": "subagent-start",
            "agent_type": "risk-classifier",
            "risk_classifier": True,
            "credential_env_present": [],
        },
        {
            "provider": "codex",
            "event": "definition-read",
            "definition_path": "AGENTS.md",
            "credential_env_present": [],
        },
    ):
        smoke._append_event(log, event)

    with pytest.raises(smoke.SmokeError, match="outside the protected fixture"):
        smoke._assert_events(project, "codex", {})


@pytest.mark.parametrize("false_green", ["target-allow", "target-post-tool"])
def test_verifier_rejects_target_read_false_greens(
    tmp_path: Path, false_green: str
) -> None:
    root = tmp_path / false_green
    smoke._prepare(root, ckit_executable=str(_ckit_wrapper(tmp_path)))
    project = root / "project"
    document = _control(root)
    _append_positive_events(root, "codex")
    _exercise_generated_guard(root, "codex")
    if false_green == "target-allow":
        stdout_hash, stderr_hash, exit_code = smoke._expected_guard_hashes(
            "codex", "allow"
        )
        smoke._append_event(
            project / smoke.EVENT_LOG,
            {
                "record_schema_version": 1,
                "provider": "codex",
                "event": "generated-guard",
                "handler_id": "protect-secrets",
                "handler_sha256": document["generated_guard_contract"]["codex"][
                    "command_sha256"
                ],
                "generated_guard_disposition": "allow",
                "exit_code": exit_code,
                "stdout_sha256": stdout_hash,
                "stderr_sha256": stderr_hash,
                "credential_env_present": [],
                "native_operation": "shell",
                "target_requested": True,
            },
        )
        expected = "target request count"
    else:
        smoke._append_event(
            project / smoke.EVENT_LOG,
            {
                "provider": "codex",
                "event": "post-tool",
                "target_requested": True,
                "credential_env_present": [],
            },
        )
        expected = "PostToolUse"

    with pytest.raises(smoke.SmokeError, match=expected):
        smoke._assert_events(project, "codex", document)


def test_bounded_process_stops_oversized_output(tmp_path: Path) -> None:
    with pytest.raises(smoke.SmokeError, match="output exceeded"):
        smoke._run_bounded_process(
            [
                sys.executable,
                "-c",
                f"import sys; sys.stdout.write('x' * {smoke.MAX_HOST_OUTPUT_BYTES + 2})",
            ],
            cwd=tmp_path,
            env={"PATH": os.environ["PATH"]},
            timeout=10,
            label="oversized unit control",
        )


def test_codex_output_read_is_bounded_and_deleted(
    prepared_root: Path,
) -> None:
    output = prepared_root / "control" / "oversized-codex-output.json"
    output.write_bytes(b"x" * (smoke.MAX_HOST_OUTPUT_BYTES + 1))
    output.chmod(0o600)
    with pytest.raises(smoke.SmokeError, match="Codex output exceeded"):
        smoke._record_codex(
            prepared_root,
            output_file=output,
            expected_version="unit-test",
        )
    assert not output.exists()


@pytest.mark.parametrize("direction", tuple(smoke.PROVIDER_ORDERS))
def test_hashed_receipts_advance_the_real_coordinator_owned_pipeline(
    tmp_path: Path, direction: str
) -> None:
    scratch = tmp_path / "receipt-proof"
    smoke._prepare(
        scratch,
        ckit_executable=str(_ckit_wrapper(tmp_path)),
        direction=direction,
    )
    project = scratch / "project"
    control_dir = scratch / "control"
    document = _control(scratch)
    provider_order = smoke.PROVIDER_ORDERS[direction]

    for index, provider in enumerate(provider_order):
        _append_positive_events(scratch, provider)
        _exercise_generated_guard(scratch, provider)
        observation = _fixture_observation(scratch, provider)
        assert observation["prior_provider_transition"] == (
            "none" if index == 0 else provider_order[0]
        )
        assert observation["pipeline_stage"] == (
            "code-review" if index == 0 else "build-green"
        )
        assert observation["gate_history_count"] == str(index)
        commitments = smoke._assert_observation(
            document,
            project,
            provider,
            observation,
            json.dumps(observation),
        )
        receipt = smoke._write_receipt(
            control_dir,
            provider=provider,
            version=f"{provider}-test",
            observation_commitments=commitments,
            output=json.dumps(observation),
            counts=smoke._assert_events(project, provider, document),
        )
        smoke._advance_pipeline(
            document,
            project,
            control_dir,
            provider=provider,
            version=f"{provider}-test",
            receipt=receipt,
        )
        if index == 0:
            assert len(document["pipeline_checkpoints"][provider_order[1]]) == 64

    smoke._verify(scratch)
    pipeline = smoke._pipeline_document(project)
    assert pipeline["status"] == "completed"
    assert [entry["gate"] for entry in pipeline["gate_history"]] == [
        "code-review",
        "build-green",
    ]
    assert [
        json.loads((project / entry["evidence_path"]).read_text(encoding="utf-8"))[
            "provider"
        ]
        for entry in pipeline["gate_history"]
    ] == list(provider_order)
    sensitive = [
        _probe_nonce(project, f"{provider}-{kind}")
        for provider in ("claude", "codex")
        for kind in ("instruction", "skill", "agent")
    ] + [(project / smoke.BLOCK_TARGET).read_text(encoding="utf-8")]
    smoke._assert_control_has_no_plaintext(control_dir, sensitive)
    for provider in ("claude", "codex"):
        receipt = json.loads(
            (control_dir / "receipts" / f"{provider}.json").read_text(encoding="utf-8")
        )
        assert "observation" not in receipt
        assert set(receipt["observation_commitments"]) == set(smoke.REQUIRED_FIELDS)


def test_exact_wheel_managed_codex_runs_passive_stage_and_canonical_gate_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scratch = tmp_path / "managed-codex-proof"
    smoke._prepare(scratch, ckit_executable=str(_ckit_wrapper(tmp_path)))
    executable, invocation_log = _fake_managed_codex(tmp_path)
    for name in smoke.PROVIDER_SECRET_ENV | {"CKIT_OPENAI_API_KEY"}:
        monkeypatch.delenv(name, raising=False)
    credential = "protected-managed-codex-unit-test-credential"
    monkeypatch.setenv("OPENAI_API_KEY", credential)

    smoke._run_managed_codex(
        scratch,
        expected_version="0.147.0",
        executable=str(executable),
    )

    control = _control(scratch)
    proof = control["managed_codex"]
    assert proof["provider"] == "codex"
    assert proof["stage"] == smoke.MANAGED_PASSIVE_STAGE
    assert proof["role"] == smoke.MANAGED_PASSIVE_ROLE
    assert proof["required_capabilities"] == list(smoke.MANAGED_PASSIVE_CAPABILITIES)
    assert proof["gate_owners"] == smoke.MANAGED_GATE_OWNERS
    assert proof["stop_reason"] == "unsupported-required-capability"
    managed_project = scratch / smoke.MANAGED_PROJECT_DIR
    assert (
        smoke._assert_managed_codex_state(
            managed_project,
            host_version="0.147.0",
        )
        == proof
    )
    gate_proof = control["managed_codex_gate_owner"]
    assert gate_proof["provider"] == "codex"
    assert gate_proof["stage"] == smoke.MANAGED_GATE_OWNER_STAGE
    assert gate_proof["role"] == smoke.MANAGED_GATE_OWNER_ROLE
    assert gate_proof["gate"] == smoke.MANAGED_GATE_OWNER_GATE
    assert gate_proof["native_host_claim"] is True
    assert gate_proof["required_capabilities"] == list(
        smoke.MANAGED_GATE_OWNER_CAPABILITIES
    )
    assert set(gate_proof["evidence"]) == {
        "architecture-plan",
        "review-verdict",
    }
    assert gate_proof["fixture_seed"]["native_host_claim"] is False
    assert gate_proof["fixture_seed"]["seeded_stages"] == list(
        smoke.MANAGED_GATE_SEED_STAGES
    )
    assert all(
        dispatch_id.startswith("protected-fixture-seed-")
        for dispatch_id in gate_proof["fixture_seed"]["seed_dispatch_ids"]
    )
    gate_project = scratch / smoke.MANAGED_GATE_OWNER_PROJECT_DIR
    assert (
        smoke._assert_managed_codex_gate_owner_state(
            gate_project,
            seed_proof=gate_proof["fixture_seed"],
            host_version="0.147.0",
            gate_closed=True,
        )
        == gate_proof
    )
    gate_snapshot = smoke._pipeline_document(gate_project)
    assert [entry["gate"] for entry in gate_snapshot["gate_history"]] == [
        smoke.MANAGED_GATE_SEED_GATE,
        smoke.MANAGED_GATE_OWNER_GATE,
    ]
    assert gate_snapshot["gate_history"][-1]["owner_stage"] == (
        smoke.MANAGED_GATE_OWNER_STAGE
    )
    assert gate_proof["gate_history_digest"] == smoke._gate_history_digest(
        gate_snapshot["gate_history"]
    )

    invocations = [
        json.loads(line)
        for line in invocation_log.read_text(encoding="utf-8").splitlines()
    ]
    host_runs = [item for item in invocations if item["kind"] == "exec"]
    assert len(host_runs) == 2
    assert all(run["provider_secret_env"] == ["OPENAI_API_KEY"] for run in host_runs)
    assert "Native role: risk-classifier" in host_runs[0]["prompt"]
    assert "Native role: em-reviewer" in host_runs[1]["prompt"]
    assert "Stage planning-merge:" in host_runs[1]["prompt"]
    assert "predecessor records are fixture-seeded" in host_runs[1]["prompt"]
    assert all("Native role: developer" not in run["prompt"] for run in host_runs)
    assert all("Native role: story-planner" not in run["prompt"] for run in host_runs)
    assert all("Native role: orchestrator" not in run["prompt"] for run in host_runs)
    assert credential not in invocation_log.read_text(encoding="utf-8")
    assert not any(item["kind"] == "unexpected" for item in invocations)

    for tree in (scratch / "control", managed_project, gate_project):
        assert not any(
            credential.encode("utf-8") in path.read_bytes()
            for path in tree.rglob("*")
            if path.is_file() and not path.is_symlink()
        )

    gate_bundle = gate_project / gate_proof["gate_bundle"]["path"]
    original_gate_bundle = gate_bundle.read_bytes()
    forged_gate_bundle = json.loads(original_gate_bundle)
    forged_gate_bundle["owner_stage"] = "planning-gate"
    gate_bundle.write_text(json.dumps(forged_gate_bundle), encoding="utf-8")
    gate_bundle.chmod(0o600)
    with pytest.raises(smoke.SmokeError, match="gate bundle"):
        smoke._assert_managed_codex_gate_owner_state(
            gate_project,
            seed_proof=gate_proof["fixture_seed"],
            host_version="0.147.0",
            gate_closed=True,
        )
    gate_bundle.write_bytes(original_gate_bundle)
    gate_bundle.chmod(0o600)

    review_artifact = gate_project / gate_proof["evidence"]["review-verdict"]["path"]
    original_review = review_artifact.read_bytes()
    failed_review = json.loads(original_review)
    failed_review["status"] = "FAIL"
    review_artifact.write_text(json.dumps(failed_review), encoding="utf-8")
    review_artifact.chmod(0o600)
    with pytest.raises(smoke.SmokeError, match="evidence"):
        smoke._assert_managed_codex_gate_owner_state(
            gate_project,
            seed_proof=gate_proof["fixture_seed"],
            host_version="0.147.0",
            gate_closed=True,
        )
    review_artifact.write_bytes(original_review)
    review_artifact.chmod(0o600)

    monkeypatch.delenv("OPENAI_API_KEY")
    document = _control(scratch)
    project = scratch / "project"
    for provider in smoke.PROVIDER_ORDERS["claude-codex"]:
        _append_positive_events(scratch, provider)
        _exercise_generated_guard(scratch, provider)
        observation = _fixture_observation(scratch, provider)
        commitments = smoke._assert_observation(
            document,
            project,
            provider,
            observation,
            json.dumps(observation),
        )
        receipt = smoke._write_receipt(
            scratch / "control",
            provider=provider,
            version=f"{provider}-managed-proof",
            observation_commitments=commitments,
            output=json.dumps(observation),
            counts=smoke._assert_events(project, provider, document),
        )
        smoke._advance_pipeline(
            document,
            project,
            scratch / "control",
            provider=provider,
            version=f"{provider}-managed-proof",
            receipt=receipt,
        )
    smoke._verify(scratch)


def test_fixture_seed_dispatcher_refuses_the_native_gate_owner() -> None:
    from claude_kit.dispatch import DispatchRequest

    dispatcher = smoke._FixtureSeedDispatcher()
    request = DispatchRequest(
        "em-reviewer",
        "Stage planning-merge: this must be a real native-host attempt.",
    )
    with pytest.raises(RuntimeError, match="refuses non-prerequisite"):
        dispatcher.spawn(request)
    assert dispatcher.requests == {}


def test_managed_codex_rejects_any_second_provider_credential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in smoke.PROVIDER_SECRET_ENV | {"CKIT_OPENAI_API_KEY"}:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "managed-only")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-cross")

    with pytest.raises(smoke.SmokeError, match="requires only OPENAI_API_KEY"):
        smoke._run_managed_codex(
            tmp_path / "not-prepared",
            expected_version="0.147.0",
            executable="codex",
        )


def test_repository_harness_fails_closed_if_a_provider_secret_is_inherited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "unit-test-only")
    with pytest.raises(smoke.SmokeError, match="must not be inherited"):
        smoke._assert_no_provider_secret_env()


def test_external_auth_and_output_files_must_be_private(
    prepared_root: Path, tmp_path: Path
) -> None:
    project = prepared_root / "project"
    private = tmp_path / "private.json"
    private.write_text("{}", encoding="utf-8")
    private.chmod(0o600)
    assert smoke._private_external_file(private, project=project, label="test") == (
        private.resolve()
    )

    private.chmod(0o644)
    assert stat.S_IMODE(private.stat().st_mode) == 0o644
    with pytest.raises(smoke.SmokeError, match="group/world"):
        smoke._private_external_file(private, project=project, label="test")
