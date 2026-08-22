"""Provider-neutral hook normalization, decisions, and fail-mode controls."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from claude_kit.components import HookEffect, HookEvent
from claude_kit.hook_runtime import (
    HookDecision,
    HookDisposition,
    HookInputError,
    HookProvider,
    ToolOperation,
    execute_hook,
    extract_apply_patch_paths,
    normalize_hook_input,
    resolve_plugin_root,
)
from claude_kit.hooks import HOOK_REGISTRY, HOOK_SPECS, PLUGIN_ONLY_HOOKS


def _tool_input(
    tool_name: str,
    tool_input: object,
    *,
    event: str = "PreToolUse",
) -> dict:
    return {
        "session_id": "session-1",
        "cwd": "/workspace",
        "hook_event_name": event,
        "tool_name": tool_name,
        "tool_input": tool_input,
    }


def test_every_hook_has_one_typed_provider_neutral_contract() -> None:
    all_records = {**HOOK_REGISTRY, **PLUGIN_ONLY_HOOKS}
    assert set(HOOK_SPECS) == set(all_records)
    for hook_id, spec in HOOK_SPECS.items():
        record = all_records[hook_id]
        assert spec.id == hook_id
        assert spec.action.uri == f"handler://{hook_id}"
        assert record["semantic_event"] is spec.event
        assert record["operation_matcher"] == spec.operation_matcher
        assert record["effect"] is spec.effect
        assert record["severity"] is spec.severity
        assert spec.data_access


def test_known_safety_guards_are_blocking_semantic_hooks() -> None:
    blocking = {
        hook_id
        for hook_id, spec in HOOK_SPECS.items()
        if spec.effect.value == "blocking"
    }
    assert blocking == {
        "guard-rm-rf",
        "guard-push-main",
        "guard-destructive-git",
        "protect-secrets",
        "guard-commit-secrets",
        "validate-settings",
        "guard-kubectl-delete",
        "lint-fix",
        "type-check",
        "verify-continuity-writeback",
    }
    assert HOOK_SPECS["guard-rm-rf"].operation_matcher == "shell"
    assert HOOK_SPECS["protect-secrets"].operation_matcher == "file-read|shell"
    assert HOOK_SPECS["validate-settings"].operation_matcher == "file-write|apply-patch"


@pytest.mark.parametrize(
    ("provider", "tool_name"),
    [(HookProvider.CLAUDE, "Bash"), (HookProvider.CODEX, "Bash")],
)
def test_shell_commands_normalize_for_both_hosts(provider, tool_name) -> None:
    envelope = normalize_hook_input(
        provider,
        HookEffect.BLOCKING,
        _tool_input(tool_name, {"command": "git status --short"}),
    )

    assert envelope.event is HookEvent.PRE_TOOL
    assert envelope.effect is HookEffect.BLOCKING
    assert envelope.operation is ToolOperation.SHELL
    assert envelope.command == "git status --short"
    assert envelope.file_paths == ()
    assert envelope.write_content is None


def test_claude_powershell_and_codex_exec_compatibility_command_normalize() -> None:
    powershell = normalize_hook_input(
        "claude",
        "blocking",
        _tool_input("PowerShell", {"command": "Get-ChildItem"}),
    )
    codex_exec = normalize_hook_input(
        "codex",
        "blocking",
        _tool_input("exec_command", {"cmd": "pytest -q"}),
    )

    assert powershell.command == "Get-ChildItem"
    assert codex_exec.command == "pytest -q"


def test_codex_unified_exec_command_normalizes_as_shell() -> None:
    envelope = normalize_hook_input(
        "codex",
        "blocking",
        _tool_input("unified_exec", {"cmd": "cat .env"}),
    )
    assert envelope.operation is ToolOperation.SHELL
    assert envelope.command == "cat .env"


@pytest.mark.parametrize(
    ("tool_name", "tool_input", "operation", "content"),
    [
        (
            "Write",
            {"file_path": r"C:\project\src\app.py", "content": "print('ok')\n"},
            ToolOperation.FILE_WRITE,
            "print('ok')\n",
        ),
        (
            "Edit",
            {
                "file_path": "/workspace/src/app.py",
                "old_string": "old",
                "new_string": "new",
            },
            ToolOperation.FILE_EDIT,
            "new",
        ),
        (
            "Read",
            {"file_path": "/workspace/src/app.py"},
            ToolOperation.FILE_READ,
            None,
        ),
    ],
)
def test_claude_file_tools_normalize_paths_and_proposed_content(
    tool_name, tool_input, operation, content
) -> None:
    envelope = normalize_hook_input(
        HookProvider.CLAUDE,
        HookEffect.BLOCKING,
        _tool_input(tool_name, tool_input),
    )

    assert envelope.operation is operation
    assert envelope.file_paths[0].startswith(("C:/project/", "/workspace/"))
    assert envelope.write_content == content


def test_claude_multi_edit_normalizes_all_replacement_content() -> None:
    envelope = normalize_hook_input(
        "claude",
        "advisory",
        _tool_input(
            "MultiEdit",
            {
                "file_path": "/workspace/app.py",
                "edits": [{"new_string": "first"}, {"new_string": "second"}],
            },
        ),
    )
    assert envelope.operation is ToolOperation.FILE_EDIT
    assert envelope.write_content == "first\nsecond"


def test_codex_apply_patch_normalizes_patch_content_and_every_path() -> None:
    patch = """*** Begin Patch
*** Update File: src/old.py
@@
-old
+new
*** Move to: src/new.py
*** Add File: tests/test_new.py
+def test_new(): pass
*** End Patch
"""
    envelope = normalize_hook_input(
        HookProvider.CODEX,
        HookEffect.BLOCKING,
        _tool_input("apply_patch", {"command": patch}),
    )

    assert envelope.operation is ToolOperation.APPLY_PATCH
    assert envelope.command is None
    assert envelope.write_content == patch
    assert envelope.file_paths == (
        "src/old.py",
        "src/new.py",
        "tests/test_new.py",
    )


def test_apply_patch_path_extraction_normalizes_and_deduplicates() -> None:
    patch = """*** Begin Patch
*** Update File: src\\app.py
*** Update File: src/app.py
*** Delete File: old.txt
*** End Patch
"""
    assert extract_apply_patch_paths(patch) == ("src/app.py", "old.txt")
    with pytest.raises(HookInputError, match="no recognizable file path"):
        extract_apply_patch_paths("not a patch")


def test_plugin_root_prefers_native_codex_variable_then_compatibility_fallback() -> (
    None
):
    assert resolve_plugin_root(
        {
            "PLUGIN_ROOT": "/native/plugin",
            "CLAUDE_PLUGIN_ROOT": "/compat/plugin",
        }
    ) == Path("/native/plugin")
    assert resolve_plugin_root({"CLAUDE_PLUGIN_ROOT": "/compat/plugin"}) == Path(
        "/compat/plugin"
    )
    assert resolve_plugin_root({}) is None

    envelope = normalize_hook_input(
        "codex",
        "advisory",
        {"hook_event_name": "SessionStart"},
        env={"PLUGIN_ROOT": "/installed/plugin"},
    )
    assert envelope.plugin_root == Path("/installed/plugin")


def _destructive_command_guard(envelope) -> HookDecision:
    assert envelope.command is not None
    if "rm -rf" in envelope.command:
        return HookDecision.block("recursive forced removal is prohibited")
    return HookDecision.allow()


@pytest.mark.parametrize("provider", list(HookProvider))
def test_positive_control_safe_command_is_allowed_without_bypassing_permissions(
    provider,
) -> None:
    result = execute_hook(
        provider,
        HookEffect.BLOCKING,
        _tool_input("Bash", {"command": "git status"}),
        _destructive_command_guard,
    )

    assert result.exit_code == 0
    assert result.stdout == ""
    assert result.stderr == ""
    assert result.disposition is HookDisposition.ALLOW
    assert result.envelope is not None


@pytest.mark.parametrize("provider", list(HookProvider))
def test_positive_control_destructive_command_emits_pretool_deny(provider) -> None:
    result = execute_hook(
        provider,
        HookEffect.BLOCKING,
        _tool_input("Bash", {"command": "rm -rf build"}),
        _destructive_command_guard,
    )

    assert result.exit_code == 0
    assert result.stderr == ""
    assert result.disposition is HookDisposition.BLOCK
    assert json.loads(result.stdout) == {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "recursive forced removal is prohibited",
        }
    }


@pytest.mark.parametrize(
    ("provider", "tool_name", "tool_input"),
    [
        (
            HookProvider.CLAUDE,
            "Write",
            {"file_path": "/workspace/.env", "content": "TOKEN=secret\n"},
        ),
        (
            HookProvider.CODEX,
            "apply_patch",
            {
                "command": "*** Begin Patch\n*** Add File: .env\n+TOKEN=secret\n*** End Patch\n"
            },
        ),
    ],
)
def test_positive_control_secret_write_blocks_after_cross_host_normalization(
    provider, tool_name, tool_input
) -> None:
    def secret_guard(envelope) -> HookDecision:
        assert envelope.write_content == "TOKEN=secret\n" or "TOKEN=secret" in (
            envelope.write_content or ""
        )
        if any(path.endswith(".env") for path in envelope.file_paths):
            return HookDecision.block("secret-file write is prohibited")
        return HookDecision.allow()

    result = execute_hook(
        provider,
        HookEffect.BLOCKING,
        _tool_input(tool_name, tool_input),
        secret_guard,
    )
    assert result.disposition is HookDisposition.BLOCK
    assert (
        json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
    )


def test_claude_advisory_preserves_system_message_contract() -> None:
    result = execute_hook(
        HookProvider.CLAUDE,
        HookEffect.ADVISORY,
        _tool_input("Bash", {"command": "git status"}),
        lambda _envelope: HookDecision.advisory("generated files may change"),
    )
    assert result.exit_code == 0
    assert json.loads(result.stdout) == {"systemMessage": "generated files may change"}
    assert result.disposition is HookDisposition.ADVISORY


@pytest.mark.parametrize(
    ("event", "tool_name", "tool_input"),
    [
        ("SessionStart", None, None),
        ("UserPromptSubmit", None, None),
        ("PreToolUse", "unified_exec", {"cmd": "cat README.md"}),
        ("PostToolUse", "unified_exec", {"cmd": "cat README.md"}),
        ("SubagentStart", None, None),
    ],
)
def test_codex_advisory_uses_event_specific_model_context(
    event: str, tool_name: str | None, tool_input: dict | None
) -> None:
    payload: dict = {"hook_event_name": event}
    if tool_name is not None:
        payload.update({"tool_name": tool_name, "tool_input": tool_input})
    result = execute_hook(
        HookProvider.CODEX,
        HookEffect.ADVISORY,
        payload,
        lambda _envelope: HookDecision.advisory("context marker"),
    )

    assert json.loads(result.stdout) == {
        "hookSpecificOutput": {
            "hookEventName": event,
            "additionalContext": "context marker",
        }
    }
    assert result.disposition is HookDisposition.ADVISORY


def test_post_tool_advisory_preserves_claude_output_contract() -> None:
    result = execute_hook(
        HookProvider.CLAUDE,
        HookEffect.ADVISORY,
        _tool_input("Read", {"file_path": "README.md"}, event="PostToolUse"),
        lambda _envelope: HookDecision.advisory("context marker"),
    )

    assert json.loads(result.stdout) == {"systemMessage": "context marker"}


@pytest.mark.parametrize("provider", list(HookProvider))
def test_stop_block_uses_top_level_decision_shape(provider) -> None:
    result = execute_hook(
        provider,
        HookEffect.BLOCKING,
        {"hook_event_name": "Stop"},
        lambda _envelope: HookDecision.block("run the failing tests once more"),
    )
    assert result.exit_code == 0
    assert json.loads(result.stdout) == {
        "decision": "block",
        "reason": "run the failing tests once more",
    }


@pytest.mark.parametrize("provider", list(HookProvider))
def test_session_start_block_uses_common_continue_shape(provider) -> None:
    result = execute_hook(
        provider,
        HookEffect.BLOCKING,
        {"hook_event_name": "SessionStart"},
        lambda _envelope: HookDecision.block("required context is unavailable"),
    )
    assert result.exit_code == 0
    assert json.loads(result.stdout) == {
        "continue": False,
        "stopReason": "required context is unavailable",
        "systemMessage": "required context is unavailable",
    }


@pytest.mark.parametrize(
    "malformed",
    [
        "{not-json",
        [],
        {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {}},
        _tool_input("Write", {"file_path": "/workspace/a.py"}),
        _tool_input("apply_patch", {"command": "*** Begin Patch\n*** End Patch\n"}),
        {"hook_event_name": "PostCompact"},
    ],
)
def test_malformed_blocking_input_fails_closed(malformed) -> None:
    result = execute_hook(
        HookProvider.CODEX,
        HookEffect.BLOCKING,
        malformed,
        lambda _envelope: HookDecision.allow(),
    )
    assert result.exit_code == 2
    assert result.stdout == ""
    assert "blocking hook rejected malformed input" in result.stderr
    assert result.disposition is HookDisposition.BLOCK


def test_malformed_advisory_input_is_a_harmless_noop() -> None:
    result = execute_hook(
        HookProvider.CODEX,
        HookEffect.ADVISORY,
        "not-json",
        lambda _envelope: HookDecision.advisory("never reached"),
    )
    assert result.exit_code == 0
    assert result.stdout == result.stderr == ""
    assert result.disposition is HookDisposition.NOOP


def test_unsupported_codex_advisory_event_is_a_harmless_noop() -> None:
    called = False

    def handler(_envelope) -> HookDecision:
        nonlocal called
        called = True
        return HookDecision.advisory("never emitted")

    result = execute_hook(
        HookProvider.CODEX,
        HookEffect.ADVISORY,
        {"hook_event_name": "Notification"},
        handler,
    )
    assert result.exit_code == 0
    assert result.stdout == result.stderr == ""
    assert result.disposition is HookDisposition.NOOP
    assert not called


@pytest.mark.parametrize("provider", list(HookProvider))
def test_advisory_session_end_output_is_discarded_as_a_noop(provider) -> None:
    result = execute_hook(
        provider,
        HookEffect.ADVISORY,
        {"hook_event_name": "SessionEnd"},
        lambda _envelope: HookDecision.advisory("host would discard this"),
    )
    assert result.exit_code == 0
    assert result.stdout == result.stderr == ""
    assert result.disposition is HookDisposition.NOOP


def test_unknown_advisory_event_is_a_harmless_noop() -> None:
    result = execute_hook(
        HookProvider.CODEX,
        HookEffect.ADVISORY,
        {"hook_event_name": "PostCompact"},
        lambda _envelope: HookDecision.advisory("never emitted"),
    )
    assert result.exit_code == 0
    assert result.stdout == result.stderr == ""


def test_unsupported_blocking_event_fails_closed() -> None:
    result = execute_hook(
        HookProvider.CODEX,
        HookEffect.BLOCKING,
        {"hook_event_name": "Notification"},
        lambda _envelope: HookDecision.allow(),
    )
    assert result.exit_code == 2
    assert "cannot enforce unsupported codex event Notification" in result.stderr


def test_advisory_handler_cannot_escalate_itself_to_blocking() -> None:
    result = execute_hook(
        HookProvider.CLAUDE,
        HookEffect.ADVISORY,
        _tool_input("Bash", {"command": "rm -rf build"}),
        lambda _envelope: HookDecision.block("must not block"),
    )
    assert result.exit_code == 0
    assert result.stdout == result.stderr == ""
    assert result.disposition is HookDisposition.NOOP


@pytest.mark.parametrize(
    ("effect", "expected_code", "expected_disposition"),
    [
        (HookEffect.ADVISORY, 0, HookDisposition.NOOP),
        (HookEffect.BLOCKING, 2, HookDisposition.BLOCK),
    ],
)
def test_handler_failure_respects_declared_fail_mode(
    effect, expected_code, expected_disposition
) -> None:
    def broken(_envelope) -> HookDecision:
        raise RuntimeError("policy crashed")

    result = execute_hook(
        HookProvider.CLAUDE,
        effect,
        _tool_input("Bash", {"command": "git status"}),
        broken,
    )
    assert result.exit_code == expected_code
    assert result.disposition is expected_disposition
    if effect is HookEffect.BLOCKING:
        assert "blocking hook handler failed: RuntimeError" in result.stderr
    else:
        assert result.stdout == result.stderr == ""
