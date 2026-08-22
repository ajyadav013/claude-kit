"""Native same-runtime upgrade and explicit transition contracts."""

from __future__ import annotations

import json

from claude_kit import catalog, upgrader
from claude_kit.models import InitOptions, InstallRequest, StateLayout
from claude_kit.runtime_scaffold import install_runtime


def _options(target):
    return InitOptions.from_dict(
        json.loads((target / StateLayout.neutral().manifest).read_text())
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
    assert (target / ".codex").is_dir()
    assert list(target.glob(".ckit.bak-*/providers/.claude"))
