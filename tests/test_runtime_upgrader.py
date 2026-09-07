"""Native same-runtime upgrade and explicit transition contracts."""

from __future__ import annotations

import json
import subprocess

import pytest

from claude_kit import catalog, pipeline, upgrader
from claude_kit.execution_lease import managed_execution_lease
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


def _init_git_repo(target) -> str:
    subprocess.run(
        ["git", "init", "-b", "upgrade-main"],
        cwd=target,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "upgrade@example.invalid"],
        cwd=target,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Upgrade Test"], cwd=target, check=True
    )
    subprocess.run(["git", "add", "-A"], cwd=target, check=True)
    subprocess.run(
        ["git", "commit", "-m", "freeze installed runtime"],
        cwd=target,
        check=True,
        capture_output=True,
    )
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=target,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


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


def test_native_upgrade_refuses_while_managed_execution_is_active(payload, tmp_path):
    target = tmp_path / "managed"
    selection = catalog.defaults(payload)
    plan = catalog.resolve(payload, selection)
    install_runtime(
        payload,
        target,
        plan,
        InstallRequest(selection, "both", _maker_checker_policy()),
    )
    manifest = target / StateLayout.neutral().manifest
    role = target / ".codex/agents/maker-checker-reviewer.toml"
    before_manifest = manifest.read_bytes()
    before_role = role.read_bytes()

    with managed_execution_lease(target):
        ok, messages = upgrader.upgrade(target)

    assert not ok
    assert "managed workflow coordinator is running" in "\n".join(messages)
    assert manifest.read_bytes() == before_manifest
    assert role.read_bytes() == before_role
    assert not list(target.glob(".claude-kit-txn-*"))


def test_same_runtime_upgrade_refuses_persisted_083_managed_run_without_mutation(
    payload, tmp_path
):
    target = tmp_path / "active-083-managed-run"
    selection = catalog.defaults(payload)
    plan = catalog.resolve(payload, selection)
    install_runtime(
        payload,
        target,
        plan,
        InstallRequest(selection, "both", _maker_checker_policy()),
    )
    source_commit = _init_git_repo(target)
    started, start_messages = pipeline.start(
        target, task="finish the active 0.83 run", mode="B"
    )
    assert started, start_messages
    manifest = target / StateLayout.neutral().manifest
    manifest_document = json.loads(manifest.read_text(encoding="utf-8"))
    manifest_document["claude_kit_version"] = "0.83.0"
    manifest.write_text(
        json.dumps(manifest_document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    snapshot = target / StateLayout.neutral().pipeline_snapshot
    snapshot_document = json.loads(snapshot.read_text(encoding="utf-8"))
    snapshot_document["kit_version"] = "0.83.0"
    snapshot_document["managed_execution"] = {
        "workflow_id": "sdlc",
        "workflow_schema_version": 1,
        "workflow_definition_digest": "0" * 64,
        "mode": snapshot_document["mode"],
        "ordered_gates": snapshot_document["ordered_gates"],
        "gate_definition_digest": snapshot_document["gate_definition_digest"],
        "gate_owner_stages": {
            gate: "legacy-owner" for gate in snapshot_document["ordered_gates"]
        },
        "workspace": {
            "worker_id": "managed-workflow",
            "target_path": "../.ckit-worktrees/active-083-managed-run",
            "base_commit": source_commit,
        },
    }
    snapshot.write_text(
        json.dumps(
            snapshot_document,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    role = target / ".codex/agents/orchestrator.toml"
    before_manifest = manifest.read_bytes()
    before_snapshot = snapshot.read_bytes()
    before_role = role.read_bytes()

    ok, messages = upgrader.upgrade(target)

    assert not ok
    assert "active frozen managed workflow run" in "\n".join(messages)
    assert manifest.read_bytes() == before_manifest
    assert snapshot.read_bytes() == before_snapshot
    assert role.read_bytes() == before_role
    assert not list(target.glob(".claude-kit-txn-*"))
    assert not list(target.glob(".ckit.bak-*"))


def test_upgrade_invalid_existing_target_does_not_create_coordination_files(
    tmp_path,
):
    target = tmp_path / "not-installed"
    target.mkdir()

    ok, messages = upgrader.upgrade(target)

    assert not ok
    assert "no .claude/" in "\n".join(messages)
    assert list(target.iterdir()) == []


def test_runtime_transition_rebases_onto_current_execution_policy(payload, tmp_path):
    target = tmp_path / "policy-rebase"
    selection = catalog.defaults(payload)
    plan = catalog.resolve(payload, selection)
    policy = _maker_checker_policy()
    install_runtime(
        payload,
        target,
        plan,
        InstallRequest(selection, "both", policy),
    )

    # Model a caller that resolved its request before configuration changed.
    transition_runtime(
        payload,
        target,
        plan,
        InstallRequest(selection, "both", None),
    )

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
