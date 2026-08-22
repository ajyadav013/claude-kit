"""StateLayout consumers share one neutral control plane while legacy paths stay readable."""

from __future__ import annotations

import json
import subprocess
from copy import deepcopy

import pytest
import yaml
from typer.testing import CliRunner

from claude_kit import (
    board_html,
    catalog,
    hooks,
    learning_capture,
    scaffold,
    tickets,
    upgrader,
    validator,
)
from claude_kit.cli import app
from claude_kit.models import InstallRequest, StateLayout
from claude_kit.runtime_scaffold import install_runtime
from tests.test_tickets import write_store

runner = CliRunner()


def _install_native(payload, target, runtime: str) -> None:
    selection = catalog.defaults(payload)
    plan = catalog.resolve(payload, selection)
    install_runtime(payload, target, plan, InstallRequest(selection, runtime))


def test_codex_status_and_doctor_use_neutral_state_without_claude(
    payload, tmp_path, monkeypatch
):
    target = tmp_path / "codex"
    _install_native(payload, target, "codex")
    layout = StateLayout.neutral()
    (target / layout.continuity).write_text(
        "# Working Memory\nneutral-only continuity\n", encoding="utf-8"
    )

    status = runner.invoke(app, ["status", str(target)])
    assert status.exit_code == 0, status.output
    assert "neutral-only continuity" in status.output
    assert layout.continuity in status.output
    assert not (target / ".claude").exists()

    monkeypatch.setattr(validator.shutil, "which", lambda _tool: None)
    ok, messages = validator.doctor(target)
    assert ok, "\n".join(messages)
    report = "\n".join(messages)
    assert any(f"{layout.state}/" in message for message in messages)
    assert "installed runtime(s): codex; mutable state: .ckit" in report
    assert "detected host CLI(s): none" in report
    assert "Codex fidelity:" in report
    assert "Codex trust boundary:" in report
    assert "no project-local plugin-plus-scaffold duplication" in report
    assert "installed-plugin duplication could not be checked for Codex" in report
    assert "Claude fidelity:" not in report
    assert "Claude Code not on PATH" not in report
    assert ".claude/state/" not in report


def test_codex_doctor_detects_project_local_plugin_and_scaffold_duplication(
    payload, tmp_path, monkeypatch
):
    target = tmp_path / "codex"
    _install_native(payload, target, "codex")
    manifest = target / ".codex-plugin/plugin.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(validator.shutil, "which", lambda _tool: None)

    ok, messages = validator.doctor(target)

    assert ok, "\n".join(messages)
    assert any(
        "duplicate project-local delivery detected for Codex" in message
        for message in messages
    )


def test_doctor_detects_enabled_native_plugins_that_duplicate_scaffolds(
    payload, tmp_path, monkeypatch
):
    target = tmp_path / "both"
    _install_native(payload, target, "both")
    monkeypatch.setattr(
        validator.shutil,
        "which",
        lambda tool: f"/usr/bin/{tool}" if tool in {"claude", "codex"} else None,
    )
    monkeypatch.setattr(validator, "_claude_version", lambda _executable: "9.9.9")

    def fake_run(command, **_kwargs):
        if command[0].endswith("claude"):
            output = json.dumps([{"id": "claude-kit@claude-kit", "enabled": True}])
        else:
            output = json.dumps(
                {
                    "installed": [
                        {
                            "pluginId": "claude-kit@claude-kit",
                            "installed": True,
                            "enabled": True,
                        }
                    ]
                }
            )
        return subprocess.CompletedProcess(command, 0, output, "")

    monkeypatch.setattr(validator.subprocess, "run", fake_run)

    ok, messages = validator.doctor(target)

    assert ok, "\n".join(messages)
    assert any(
        "duplicate installed-plugin delivery detected for Claude, Codex" in message
        for message in messages
    )
    assert any(
        "skills, hooks, MCP servers, or SessionStart" in message for message in messages
    )


def test_codex_doctor_checks_native_mcp_command_and_declared_environment(
    payload, tmp_path, monkeypatch
):
    target = tmp_path / "codex"
    selection = catalog.defaults(payload)
    selection.mcp = ["github"]
    plan = catalog.resolve(payload, selection)
    install_runtime(payload, target, plan, InstallRequest(selection, "codex"))
    monkeypatch.setenv("GITHUB_PERSONAL_ACCESS_TOKEN", "set-for-this-test")
    monkeypatch.setattr(validator.shutil, "which", lambda tool: f"/usr/bin/{tool}")
    monkeypatch.setattr(validator, "_claude_version", lambda _executable: "0.148.0")

    ok, messages = validator.doctor(target, mcp=True)

    assert ok, "\n".join(messages)
    report = "\n".join(messages)
    assert "MCP github: command 'npx' found" in report
    assert "GITHUB_PERSONAL_ACCESS_TOKEN" not in report
    assert ".mcp.lock.json" not in report


def test_dual_doctor_reports_semantics_and_checks_both_native_mcp_surfaces(
    payload, tmp_path, monkeypatch
):
    target = tmp_path / "both-mcp"
    selection = catalog.defaults(payload)
    selection.mcp = ["github"]
    plan = catalog.resolve(payload, selection)
    install_runtime(payload, target, plan, InstallRequest(selection, "both"))
    monkeypatch.setenv("GITHUB_PERSONAL_ACCESS_TOKEN", "not-reported")
    monkeypatch.setattr(
        validator.shutil,
        "which",
        lambda tool: "/usr/bin/npx" if tool == "npx" else None,
    )

    def unexpected_launch(*_args, **_kwargs):
        raise AssertionError("doctor must not launch an MCP server")

    monkeypatch.setattr(validator.subprocess, "run", unexpected_launch)

    ok, messages = validator.doctor(target, mcp=True)

    assert ok, "\n".join(messages)
    report = "\n".join(messages)
    assert "MCP github semantics: runtimes=claude,codex" in report
    assert "authentication=inferred" in report
    assert "declared-health=mcp-initialize" in report
    assert "compatible" in report
    assert "MCP github: command 'npx' found (.mcp.json)" in report
    assert "MCP github: command 'npx' found (.codex/config.toml)" in report
    assert "not-reported" not in report


def test_native_strict_validation_rejects_mcp_semantic_drift(payload, tmp_path):
    target = tmp_path / "semantic-drift"
    selection = catalog.defaults(payload)
    selection.mcp = ["github"]
    plan = catalog.resolve(payload, selection)
    install_runtime(payload, target, plan, InstallRequest(selection, "codex"))
    snapshot_path = target / StateLayout.neutral().stack_snapshot
    snapshot = yaml.safe_load(snapshot_path.read_text(encoding="utf-8"))
    snapshot["mcp_semantics"]["github"]["authentication"] = "oauth"
    snapshot_path.write_text(
        yaml.safe_dump(snapshot, sort_keys=False), encoding="utf-8"
    )

    ok, messages = validator.validate(target, strict=True)

    assert not ok
    assert any("snapshot MCP semantics differ" in message for message in messages)


def test_native_strict_validation_rejects_provider_incompatible_mcp(
    payload, tmp_path, monkeypatch
):
    target = tmp_path / "runtime-drift"
    selection = catalog.defaults(payload)
    selection.mcp = ["github"]
    plan = catalog.resolve(payload, selection)
    install_runtime(payload, target, plan, InstallRequest(selection, "codex"))
    original_load = catalog._load

    def provider_limited(root, name):
        document = deepcopy(original_load(root, name))
        if name == "mcp.yaml":
            document["servers"]["github"]["runtime_support"] = ["claude"]
        return document

    monkeypatch.setattr(catalog, "_load", provider_limited)

    ok, messages = validator.validate(target, strict=True)

    assert not ok
    assert any("github lacks codex" in message for message in messages)


def test_native_strict_validation_requires_selected_mcp_on_each_provider(
    payload, tmp_path
):
    target = tmp_path / "missing-native-mcp"
    selection = catalog.defaults(payload)
    selection.mcp = ["github"]
    plan = catalog.resolve(payload, selection)
    install_runtime(payload, target, plan, InstallRequest(selection, "both"))
    claude_path = target / ".mcp.json"
    document = json.loads(claude_path.read_text(encoding="utf-8"))
    document["mcpServers"].pop("github")
    document["mcpServers"]["user-owned"] = {
        "type": "http",
        "url": "https://example.invalid/mcp",
    }
    claude_path.write_text(json.dumps(document), encoding="utf-8")

    ok, messages = validator.validate(target, strict=True)

    assert not ok
    assert any(
        "Claude MCP config omits selected server(s): github" in message
        for message in messages
    )


def test_dual_ticket_board_and_status_read_the_same_neutral_snapshot(payload, tmp_path):
    target = tmp_path / "both"
    _install_native(payload, target, "both")
    write_store(target, [("PROJ-1", "shared state", "IN PROGRESS")])

    neutral_snapshot = target / StateLayout.neutral().pipeline_snapshot
    neutral_snapshot.write_text(
        json.dumps({"stage": "neutral-stage", "last_gate_passed": "neutral-gate"}),
        encoding="utf-8",
    )
    legacy_snapshot = target / tickets.SNAPSHOT_REL
    legacy_snapshot.parent.mkdir(parents=True, exist_ok=True)
    legacy_snapshot.write_text(
        json.dumps({"stage": "legacy-stage", "last_gate_passed": "legacy-gate"}),
        encoding="utf-8",
    )

    rendered = runner.invoke(
        app,
        [
            "tickets",
            "--path",
            str(target),
            "--html",
            "--refresh",
            "0",
            "--transcript-dir",
            str(tmp_path / "no-transcripts"),
        ],
    )
    assert rendered.exit_code == 0, rendered.output
    board = target / board_html.board_rel(target)
    assert board == target / ".ckit/state/ticket-board.html"
    html = board.read_text(encoding="utf-8")
    assert "neutral-stage" in html and "legacy-stage" not in html

    status = runner.invoke(app, ["status", str(target)])
    assert status.exit_code == 0, status.output
    assert "neutral-stage" in status.output and "legacy-stage" not in status.output


def test_dual_status_reports_each_native_projection_and_missing_codex_surface(
    payload, tmp_path
):
    target = tmp_path / "both"
    _install_native(payload, target, "both")
    (target / ".codex/agents").rename(target / ".codex/agents.missing")

    result = runner.invoke(app, ["status", str(target), "--json"])

    assert result.exit_code == 0, result.output
    document = json.loads(result.output)
    assert document["runtimes"] == ["claude", "codex"]
    assert document["provider_components"]["claude"]["agents"] > 0
    assert document["provider_components"]["codex"]["agents"] is None


@pytest.mark.parametrize("runtime", ["codex", "both"])
def test_native_privacy_report_discloses_shared_memory_and_state(
    payload, tmp_path, runtime
):
    target = tmp_path / runtime
    _install_native(payload, target, runtime)

    ok, messages = hooks.privacy_report(target)

    assert ok, "\n".join(messages)
    report = "\n".join(messages)
    assert ".codex/hooks.json" in report
    assert ".ckit/agent-memory/" in report
    assert ".ckit/state/" in report
    assert ".claude/agent-memory/" not in report
    assert ".claude/state/" not in report


@pytest.mark.parametrize("runtime", ["codex", "both"])
def test_native_privacy_report_attributes_codex_adapter_and_capture(
    runtime, payload, tmp_path
):
    target = tmp_path / runtime
    selection = catalog.defaults(payload)
    selection.capture_mode = "session-end"
    plan = catalog.resolve(payload, selection)
    install_runtime(payload, target, plan, InstallRequest(selection, runtime))

    ok, messages = hooks.privacy_report(target)

    assert ok, "\n".join(messages)
    report = "\n".join(messages)
    assert "background learning capture: ON" in report
    assert "(not a claude-kit hook)" not in report
    assert "`claude` job" not in report
    if runtime == "codex":
        assert "Codex background task" in report
        assert "historical transcript catch-up is not assumed" in report
    else:
        assert "provider-selected background task" in report


def test_legacy_public_constants_and_layout_resolution_remain_compatible(tmp_path):
    assert tickets.SNAPSHOT_REL == ".claude/state/pipeline-snapshot.json"
    assert board_html.BOARD_REL == ".claude/state/ticket-board.html"

    marker = tmp_path / ".claude/config/init-options.json"
    marker.parent.mkdir(parents=True)
    marker.write_text("{}\n", encoding="utf-8")
    snapshot = tmp_path / tickets.SNAPSHOT_REL
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_text('{"stage":"legacy-stage"}\n', encoding="utf-8")

    assert tickets.pipeline_stage(tmp_path)["stage"] == "legacy-stage"
    assert board_html.board_rel(tmp_path) == board_html.BOARD_REL


def test_named_state_consumers_derive_mutable_paths_from_state_layout():
    legacy = StateLayout.legacy_claude()
    neutral = StateLayout.neutral()

    assert scaffold._LEGACY_STATE_LAYOUT == legacy
    assert upgrader._LEGACY_STATE_LAYOUT == legacy
    assert legacy.journal in scaffold.GITIGNORE_ENTRIES
    assert f"{legacy.state}/" in scaffold.GITIGNORE_ENTRIES
    assert f"{legacy.temporary}/" in scaffold.GITIGNORE_ENTRIES
    assert learning_capture.MEMORY_ROOT == neutral.memory
    assert learning_capture.MEMORY_INDEX == f"{neutral.memory}/MEMORY.md"
