"""Native same-runtime upgrade and explicit transition contracts."""

from __future__ import annotations

import json

import pytest

from claude_kit import catalog, upgrader
from claude_kit.models import (
    ExecutionPolicy,
    InitOptions,
    InstallRequest,
    ModelChoice,
    StateLayout,
    WorkerBinding,
)
from claude_kit.runtime_scaffold import install_runtime, transition_runtime


def _options(target):
    return InitOptions.from_dict(
        json.loads((target / StateLayout.neutral().manifest).read_text())
    )


def _maker_checker_policy() -> ExecutionPolicy:
    return ExecutionPolicy(
        maker=WorkerBinding("claude", ModelChoice("exact", "claude-maker")),
        reviewer=WorkerBinding("codex", ModelChoice("exact", "codex-reviewer")),
    )


def test_plain_native_upgrade_preserves_installed_runtime(payload, tmp_path):
    target = tmp_path / "codex"
    selection = catalog.defaults(payload)
    plan = catalog.resolve(payload, selection)
    install_runtime(
        payload,
        target,
        plan,
        InstallRequest(selection=selection, runtime="codex"),
    )

    diff_ok, diff_messages = upgrader.diff(target)
    upgrade_ok, upgrade_messages = upgrader.upgrade(target)

    assert diff_ok, diff_messages
    assert upgrade_ok, upgrade_messages
    assert _options(target).runtimes == ["codex"]
    assert not (target / ".claude").exists()
    assert (target / ".codex/agents/orchestrator.toml").is_file()


def test_native_upgrade_preserves_execution_policy(payload, tmp_path):
    target = tmp_path / "configured"
    selection = catalog.defaults(payload)
    plan = catalog.resolve(payload, selection)
    policy = _maker_checker_policy()
    install_runtime(
        payload,
        target,
        plan,
        InstallRequest(selection, "both", policy),
    )

    diff_ok, diff_messages = upgrader.diff(target)
    upgrade_ok, upgrade_messages = upgrader.upgrade(target)

    assert diff_ok, diff_messages
    assert upgrade_ok, upgrade_messages
    assert _options(target).execution_policy == policy


def test_native_upgrade_refuses_runtime_removal_referenced_by_execution_policy(
    payload, tmp_path
):
    target = tmp_path / "configured-removal"
    selection = catalog.defaults(payload)
    plan = catalog.resolve(payload, selection)
    policy = _maker_checker_policy()
    install_runtime(
        payload,
        target,
        plan,
        InstallRequest(selection, "both", policy),
    )

    ok, messages = upgrader.upgrade(
        target,
        runtime="claude",
        confirm_runtime_removal=True,
    )

    assert not ok
    assert "reviewer provider 'codex' is not installed" in "\n".join(messages)
    assert _options(target).runtime.value == "both"


def test_native_upgrade_adds_a_runtime_without_a_second_state_root(payload, tmp_path):
    target = tmp_path / "claude"
    selection = catalog.defaults(payload)
    plan = catalog.resolve(payload, selection)
    install_runtime(
        payload,
        target,
        plan,
        InstallRequest(selection=selection, runtime="claude"),
    )
    continuity = target / StateLayout.neutral().continuity
    continuity.write_text("# Keep cross-runtime state\n")

    ok, messages = upgrader.upgrade(target, runtime="both")

    assert ok, messages
    assert _options(target).runtimes == ["claude", "codex"]
    assert continuity.read_text() == "# Keep cross-runtime state\n"
    assert (target / ".claude").is_dir()
    assert (target / ".codex").is_dir()
    assert not (target / ".codex/state").exists()


def test_native_upgrade_requires_confirmation_and_backs_up_removed_runtime(
    payload, tmp_path
):
    target = tmp_path / "both"
    selection = catalog.defaults(payload)
    plan = catalog.resolve(payload, selection)
    install_runtime(
        payload,
        target,
        plan,
        InstallRequest(selection=selection, runtime="both"),
    )
    assert (target / "README.claude-sdlc.md").is_file()

    refused, refused_messages = upgrader.upgrade(target, runtime="codex")
    assert not refused
    assert "confirmation is required" in "\n".join(refused_messages)
    assert (target / ".claude").is_dir()

    ok, messages = upgrader.upgrade(
        target,
        runtime="codex",
        confirm_runtime_removal=True,
    )
    assert ok, messages
    assert _options(target).runtimes == ["codex"]
    assert not (target / ".claude").exists()
    assert not (target / "CLAUDE.md").exists()
    assert not (target / "README.claude-sdlc.md").exists()
    assert not (target / ".mcp.json").exists()
    assert not (target / ".mcp.lock.json").exists()
    assert (target / ".codex").is_dir()
    assert list(target.glob(".ckit.bak-*/providers/.claude"))
    assert list(target.glob(".ckit.bak-*/providers/README.claude-sdlc.md"))


class _SimulatedLateUpgradeDeath(BaseException):
    pass


def test_native_upgrade_recovers_late_interrupted_transition_before_routing(
    payload, tmp_path, monkeypatch
):
    from claude_kit import runtime_scaffold

    target = tmp_path / "late-interrupted-upgrade"
    selection = catalog.defaults(payload)
    plan = catalog.resolve(payload, selection)
    install_runtime(
        payload,
        target,
        plan,
        InstallRequest(selection=selection, runtime="both"),
    )
    original_apply = runtime_scaffold._apply_runtime_files

    def apply_then_die(*args, **kwargs):
        original_apply(*args, **kwargs)
        raise _SimulatedLateUpgradeDeath()

    monkeypatch.setattr(runtime_scaffold, "_apply_runtime_files", apply_then_die)
    with pytest.raises(_SimulatedLateUpgradeDeath):
        transition_runtime(
            payload,
            target,
            plan,
            InstallRequest(selection=selection, runtime="codex"),
            confirm_removal=True,
        )
    monkeypatch.setattr(runtime_scaffold, "_apply_runtime_files", original_apply)
    assert _options(target).runtimes == ["codex"]
    assert not (target / ".claude").exists()
    assert (target / StateLayout.neutral().journal).is_file()

    ok, messages = upgrader.upgrade(
        target,
        runtime="codex",
        confirm_runtime_removal=True,
    )

    assert ok, messages
    assert _options(target).runtimes == ["codex"]
    assert not (target / ".claude").exists()
    assert not (target / StateLayout.neutral().journal).exists()
    assert list(target.glob(".ckit.bak-*/providers/.claude"))
