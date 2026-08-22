"""Native runtime projection and transactional install integration tests."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest
import yaml

try:  # pragma: no cover - Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.9/3.10
    import tomli as tomllib  # type: ignore[no-redef]

from claude_kit import catalog
from claude_kit.models import InitOptions, InstallRequest, Runtime, StateLayout
from claude_kit.provider_renderers import CodexRenderer
from claude_kit.runtime_scaffold import (
    RuntimeInstallError,
    _merge_agents,
    install_runtime,
    preview_runtime_install,
    transition_runtime,
)


@pytest.mark.parametrize(
    ("runtime", "required", "absent"),
    [
        ("claude", ".claude/agents/orchestrator.md", ".codex/agents/orchestrator.toml"),
        ("codex", ".codex/agents/orchestrator.toml", ".claude/agents/orchestrator.md"),
        ("both", ".codex/agents/orchestrator.toml", "independent-provider-state"),
    ],
)
def test_fresh_native_runtime_install_has_one_neutral_control_plane(
    payload, tmp_path, runtime, required, absent
):
    target = tmp_path / runtime
    selection = catalog.defaults(payload)
    plan = catalog.resolve(payload, selection)
    request = InstallRequest(selection=selection, runtime=runtime)

    install_runtime(payload, target, plan, request)

    assert (target / required).is_file()
    if absent != "independent-provider-state":
        assert not (target / absent).exists()
    if runtime == "both":
        assert (target / ".claude/agents/orchestrator.md").is_file()
        assert (target / ".codex/agents/orchestrator.toml").is_file()
    assert (target / ".ckit/CONTINUITY.md").is_file()
    assert (target / ".ckit/agent-memory/MEMORY.md").is_file()
    loop = target / ".ckit/scripts/sdlc-loop.sh"
    assert loop.is_file()
    assert loop.stat().st_mode & 0o111
    loop_text = loop.read_text(encoding="utf-8")
    assert (
        "automated host execution requires portable descendant-process containment"
        in loop_text
    )
    assert "CKIT_RUNTIME" not in loop_text
    assert "codex exec" not in loop_text
    assert "claude -p" not in loop_text
    assert not (target / ".claude/state/pipeline-snapshot.json").exists()
    assert not (target / ".codex/state/pipeline-snapshot.json").exists()

    options = InitOptions.from_dict(
        json.loads((target / StateLayout.neutral().manifest).read_text())
    )
    assert options.runtime is Runtime.parse(runtime)
    assert options.state_layout == StateLayout.neutral()
    assert {record.provider for record in options.files} == set(request.runtimes) | {
        "shared"
    }
    snapshot = yaml.safe_load(
        (target / StateLayout.neutral().stack_snapshot).read_text()
    )
    assert snapshot["gate_definition_digest"] == plan.gate_definition_digest
    assert snapshot["gates"] == plan.gates


def test_codex_managed_files_preserve_user_prose_comments_and_are_idempotent(
    payload, tmp_path
):
    target = tmp_path / "project"
    (target / ".codex").mkdir(parents=True)
    (target / "AGENTS.md").write_text("# Team instructions\n\nKeep this paragraph.\n")
    (target / ".codex/config.toml").write_text(
        '# keep this comment\n[history]\npersistence = "save-all"\n'
    )
    selection = catalog.defaults(payload)
    plan = catalog.resolve(payload, selection)
    request = InstallRequest(selection=selection, runtime="codex")

    install_runtime(payload, target, plan, request)
    install_runtime(payload, target, plan, request)

    agents = (target / "AGENTS.md").read_text()
    config = (target / ".codex/config.toml").read_text()
    assert "Keep this paragraph." in agents
    assert agents.count("<!-- ckit:managed:start -->") == 1
    assert agents.count("<!-- ckit:managed:end -->") == 1
    assert "# keep this comment" in config
    assert config.count("# ckit:managed:start") == 1
    assert config.count("# ckit:managed:end") == 1
    assert tomllib.loads(config)["history"]["persistence"] == "save-all"


def test_agents_merge_compacts_only_inline_rules_to_preserve_user_prose(payload):
    selection = catalog.defaults(payload)
    plan = catalog.resolve(payload, selection)
    projection = tuple(
        item
        for item in CodexRenderer(payload).render(
            plan, InstallRequest(selection=selection, runtime="codex")
        )
        if item.path == "AGENTS.md"
    )
    assert len(projection) == 1
    user_prose = "# Team instructions\n\n" + ("preserve-this-line\n" * 500)

    merged = _merge_agents(user_prose, projection[0].text_content)

    assert user_prose.rstrip() in merged
    assert "## Named roles" in merged
    assert "## Ordered quality gates" in merged
    assert "Inline rule bodies are omitted here" in merged
    assert ".ckit/rules/" in merged
    assert len(merged.encode("utf-8")) < 32 * 1024


def test_duplicate_user_mcp_definition_fails_and_rolls_back_every_root(
    payload, tmp_path
):
    target = tmp_path / "project"
    (target / ".codex").mkdir(parents=True)
    original = '[mcp_servers.github]\ncommand = "user-owned"\n'
    (target / ".codex/config.toml").write_text(original)
    selection = catalog.defaults(payload)
    selection.mcp = ["github"]
    plan = catalog.resolve(payload, selection)

    with pytest.raises(RuntimeInstallError, match="duplicate MCP definitions"):
        install_runtime(
            payload,
            target,
            plan,
            InstallRequest(selection=selection, runtime="codex"),
        )

    assert (target / ".codex/config.toml").read_text() == original
    assert not (target / ".ckit").exists()
    assert not (target / ".agents").exists()
    assert not (target / "AGENTS.md").exists()


@pytest.mark.parametrize("runtime", ["claude", "both"])
def test_duplicate_user_claude_mcp_definition_fails_before_install(
    payload, tmp_path, runtime
):
    target = tmp_path / runtime
    target.mkdir()
    original = '{"mcpServers":{"github":{"command":"user-owned"}}}\n'
    (target / ".mcp.json").write_text(original, encoding="utf-8")
    selection = catalog.defaults(payload)
    selection.mcp = ["github"]
    plan = catalog.resolve(payload, selection)

    with pytest.raises(RuntimeInstallError, match="duplicate MCP definitions"):
        install_runtime(
            payload,
            target,
            plan,
            InstallRequest(selection=selection, runtime=runtime),
        )

    assert (target / ".mcp.json").read_text(encoding="utf-8") == original
    assert not (target / ".ckit").exists()
    assert not (target / ".claude").exists()
    assert not (target / ".codex").exists()
    assert not (target / ".agents").exists()


@pytest.mark.parametrize("runtime", ["claude", "both"])
def test_user_claude_mcp_servers_merge_with_selected_servers_idempotently(
    payload, tmp_path, runtime
):
    from claude_kit import validator

    target = tmp_path / runtime
    target.mkdir()
    (target / ".mcp.json").write_text(
        json.dumps(
            {
                "projectSetting": "preserve-me",
                "mcpServers": {"mine": {"command": "echo", "args": []}},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    selection = catalog.defaults(payload)
    selection.mcp = ["github"]
    plan = catalog.resolve(payload, selection)
    request = InstallRequest(selection=selection, runtime=runtime)

    install_runtime(payload, target, plan, request)
    first = (target / ".mcp.json").read_bytes()
    install_runtime(payload, target, plan, request)

    document = json.loads((target / ".mcp.json").read_text(encoding="utf-8"))
    assert (target / ".mcp.json").read_bytes() == first
    assert document["projectSetting"] == "preserve-me"
    assert set(document["mcpServers"]) == {"github", "mine"}
    assert document["mcpServers"]["mine"] == {"command": "echo", "args": []}
    assert not (target / ".mcp.json.claude-kit").exists()
    options = InitOptions.from_dict(
        json.loads((target / StateLayout.neutral().manifest).read_text())
    )
    assert any(record.path == ".mcp.json" for record in options.files)
    assert (
        next(
            record.owner for record in options.files if record.path == ".mcp.lock.json"
        )
        == "kit"
    )
    ok, messages = validator.validate(target, strict=True)
    assert ok, "\n".join(messages)


def test_reinstall_restores_managed_claude_mcp_and_preserves_user_servers(
    payload, tmp_path
):
    target = tmp_path / "modified"
    selection = catalog.defaults(payload)
    selection.mcp = ["github"]
    plan = catalog.resolve(payload, selection)
    request = InstallRequest(selection=selection, runtime="claude")
    install_runtime(payload, target, plan, request)
    document = json.loads((target / ".mcp.json").read_text(encoding="utf-8"))
    document["mcpServers"]["github"]["command"] = "user-modified"
    document["mcpServers"]["mine"] = {"command": "first"}
    (target / ".mcp.json").write_text(json.dumps(document) + "\n", encoding="utf-8")

    install_runtime(payload, target, plan, request)
    document = json.loads((target / ".mcp.json").read_text(encoding="utf-8"))
    assert document["mcpServers"]["github"]["command"] == "npx"
    assert document["mcpServers"]["mine"] == {"command": "first"}

    document["mcpServers"]["mine"]["command"] = "second"
    (target / ".mcp.json").write_text(json.dumps(document) + "\n", encoding="utf-8")
    install_runtime(payload, target, plan, request)
    document = json.loads((target / ".mcp.json").read_text(encoding="utf-8"))
    assert document["mcpServers"]["mine"] == {"command": "second"}


@pytest.mark.parametrize("with_user_server", [False, True])
def test_reinstall_without_selected_mcp_removes_only_prior_managed_servers(
    payload, tmp_path, with_user_server
):
    target = tmp_path / ("mixed" if with_user_server else "managed-only")
    selection = catalog.defaults(payload)
    selection.mcp = ["github"]
    plan = catalog.resolve(payload, selection)
    install_runtime(
        payload,
        target,
        plan,
        InstallRequest(selection=selection, runtime="claude"),
    )
    if with_user_server:
        document = json.loads((target / ".mcp.json").read_text(encoding="utf-8"))
        document["mcpServers"]["mine"] = {"command": "echo"}
        (target / ".mcp.json").write_text(json.dumps(document) + "\n", encoding="utf-8")

    selection = catalog.defaults(payload)
    plan = catalog.resolve(payload, selection)
    install_runtime(
        payload,
        target,
        plan,
        InstallRequest(selection=selection, runtime="claude"),
    )

    if with_user_server:
        document = json.loads((target / ".mcp.json").read_text(encoding="utf-8"))
        assert document == {"mcpServers": {"mine": {"command": "echo"}}}
    else:
        assert not (target / ".mcp.json").exists()
    assert not (target / ".mcp.lock.json").exists()


def test_runtime_preview_uses_existing_tree_merge_and_collision_decisions(
    payload, tmp_path
):
    from claude_kit.runtime_scaffold import preview_runtime_install

    target = tmp_path / "preview"
    target.mkdir()
    (target / "README.claude-sdlc.md").write_text("user readme\n", encoding="utf-8")
    (target / ".mcp.json").write_text(
        '{"mcpServers":{"mine":{"command":"echo"}}}\n', encoding="utf-8"
    )
    selection = catalog.defaults(payload)
    selection.mcp = ["github"]
    plan = catalog.resolve(payload, selection)
    request = InstallRequest(selection=selection, runtime="claude")

    _projection, paths = preview_runtime_install(payload, target, plan, request)
    assert ".mcp.json" in paths
    assert ".mcp.json.claude-kit" not in paths
    assert "README.claude-sdlc.md" not in paths
    assert "README.claude-sdlc.md.claude-kit" in paths
    assert not (target / "README.claude-sdlc.md.claude-kit").exists()

    (target / ".mcp.json").write_text(
        '{"mcpServers":{"github":{"command":"user-owned"}}}\n',
        encoding="utf-8",
    )
    with pytest.raises(RuntimeInstallError, match="duplicate MCP definitions"):
        preview_runtime_install(payload, target, plan, request)


def test_incompatible_mcp_runtime_fails_before_any_project_mutation(payload, tmp_path):
    target = tmp_path / "incompatible"
    selection = catalog.defaults(payload)
    selection.mcp = ["github"]
    plan = catalog.resolve(payload, selection)
    plan.mcp_server_specs["github"] = replace(
        plan.mcp_server_specs["github"], runtime_support=frozenset({"claude"})
    )

    with pytest.raises(
        RuntimeInstallError, match="github lacks codex.*supports: claude"
    ):
        install_runtime(
            payload,
            target,
            plan,
            InstallRequest(selection=selection, runtime="both"),
        )

    assert not target.exists()


def test_dual_runtime_mcp_uses_one_semantic_record_on_both_native_surfaces(
    payload, tmp_path
):
    target = tmp_path / "both-mcp"
    selection = catalog.defaults(payload)
    selection.mcp = ["github"]
    plan = catalog.resolve(payload, selection)

    install_runtime(
        payload,
        target,
        plan,
        InstallRequest(selection=selection, runtime="both"),
    )

    claude = json.loads((target / ".mcp.json").read_text(encoding="utf-8"))
    codex = tomllib.loads((target / ".codex/config.toml").read_text(encoding="utf-8"))
    snapshot = yaml.safe_load(
        (target / StateLayout.neutral().stack_snapshot).read_text(encoding="utf-8")
    )
    assert "github" in claude["mcpServers"]
    assert "github" in codex["mcp_servers"]
    assert snapshot["mcp_semantics"]["github"] == {
        "label": "GitHub (issues, PRs, repos)",
        "transport": "stdio",
        "authentication": "inferred",
        "runtime_support": ["claude", "codex"],
        "health_check": "mcp-initialize",
        "environment_references": ["GITHUB_PERSONAL_ACCESS_TOKEN"],
    }


def test_runtime_preview_lists_shared_and_provider_owned_files(payload, tmp_path):
    selection = catalog.defaults(payload)
    plan = catalog.resolve(payload, selection)
    projection, paths = preview_runtime_install(
        payload,
        tmp_path / "preview",
        plan,
        InstallRequest(selection=selection, runtime="both"),
    )

    assert [provider.value for provider in projection.providers] == ["claude", "codex"]
    assert ".claude/agents/orchestrator.md" in paths
    assert ".codex/agents/orchestrator.toml" in paths
    assert ".agents/skills/sdlc/SKILL.md" in paths
    assert StateLayout.neutral().manifest in paths
    assert StateLayout.neutral().continuity in paths
    assert len(paths) == len(set(paths))


@pytest.mark.parametrize(
    ("initial", "destination"),
    [
        ("claude", "both"),
        ("claude", "codex"),
        ("codex", "both"),
        ("both", "claude"),
        ("both", "codex"),
        ("claude", "claude"),
    ],
)
def test_runtime_transition_matrix_preserves_one_state_ledger(
    payload, tmp_path, initial, destination
):
    target = tmp_path / f"{initial}-to-{destination}"
    selection = catalog.defaults(payload)
    plan = catalog.resolve(payload, selection)
    install_runtime(
        payload,
        target,
        plan,
        InstallRequest(selection=selection, runtime=initial),
    )
    continuity = target / StateLayout.neutral().continuity
    continuity.write_text("# Cross-runtime continuity\n\nKeep this.\n")
    pipeline = target / StateLayout.neutral().pipeline_snapshot
    pipeline.write_text('{"status":"active","gate_history":[]}\n')

    transition_runtime(
        payload,
        target,
        plan,
        InstallRequest(selection=selection, runtime=destination),
        confirm_removal=True,
    )

    options = InitOptions.from_dict(
        json.loads((target / StateLayout.neutral().manifest).read_text())
    )
    assert options.runtime is Runtime.parse(destination)
    assert continuity.read_text() == "# Cross-runtime continuity\n\nKeep this.\n"
    assert pipeline.read_text() == '{"status":"active","gate_history":[]}\n'
    assert (target / ".claude").exists() is (destination in {"claude", "both"})
    assert (target / ".codex").exists() is (destination in {"codex", "both"})
    assert not (target / ".claude/state/pipeline-snapshot.json").exists()
    assert not (target / ".codex/state/pipeline-snapshot.json").exists()
    if set(Runtime.parse(initial).providers) - set(
        Runtime.parse(destination).providers
    ):
        assert list(target.glob(".ckit.bak-*/providers"))


def test_provider_removal_requires_confirmation(payload, tmp_path):
    target = tmp_path / "both"
    selection = catalog.defaults(payload)
    plan = catalog.resolve(payload, selection)
    install_runtime(
        payload,
        target,
        plan,
        InstallRequest(selection=selection, runtime="both"),
    )

    with pytest.raises(RuntimeInstallError, match="confirmation is required"):
        transition_runtime(
            payload,
            target,
            plan,
            InstallRequest(selection=selection, runtime="codex"),
        )

    assert (target / ".claude").is_dir()
    assert (target / ".codex").is_dir()
    assert not list(target.glob(".ckit.bak-*"))


def test_plain_install_cannot_bypass_explicit_runtime_transition(payload, tmp_path):
    target = tmp_path / "plain-install-bypass"
    selection = catalog.defaults(payload)
    plan = catalog.resolve(payload, selection)
    install_runtime(
        payload,
        target,
        plan,
        InstallRequest(selection=selection, runtime="both"),
    )

    with pytest.raises(RuntimeInstallError, match="ckit upgrade --runtime"):
        install_runtime(
            payload,
            target,
            plan,
            InstallRequest(selection=selection, runtime="codex"),
        )

    options = InitOptions.from_dict(
        json.loads((target / StateLayout.neutral().manifest).read_text())
    )
    assert options.runtimes == ["claude", "codex"]
    assert (target / ".claude").is_dir()
    assert (target / ".codex").is_dir()
    assert not list(target.glob(".ckit.bak-*"))


def test_failed_transition_restores_removed_provider_and_backup(
    payload, tmp_path, monkeypatch
):
    from claude_kit import runtime_scaffold

    target = tmp_path / "both"
    selection = catalog.defaults(payload)
    plan = catalog.resolve(payload, selection)
    install_runtime(
        payload,
        target,
        plan,
        InstallRequest(selection=selection, runtime="both"),
    )
    before = (target / ".claude/agents/orchestrator.md").read_bytes()

    def fail_apply(*_args, **_kwargs):
        raise RuntimeError("injected transition failure")

    monkeypatch.setattr(runtime_scaffold, "_apply_runtime_files", fail_apply)
    with pytest.raises(RuntimeError, match="injected transition failure"):
        transition_runtime(
            payload,
            target,
            plan,
            InstallRequest(selection=selection, runtime="codex"),
            confirm_removal=True,
        )

    assert (target / ".claude/agents/orchestrator.md").read_bytes() == before
    assert (target / ".codex").is_dir()
    assert not list(target.glob(".ckit.bak-*"))


class _SimulatedTransitionProcessDeath(BaseException):
    pass


def test_interrupted_provider_transition_recovers_then_converges(
    payload, tmp_path, monkeypatch
):
    """An abrupt death after provider removal leaves a journal that the retry restores first."""
    from claude_kit import runtime_scaffold

    target = tmp_path / "both"
    selection = catalog.defaults(payload)
    plan = catalog.resolve(payload, selection)
    install_runtime(
        payload,
        target,
        plan,
        InstallRequest(selection=selection, runtime="both"),
    )
    claude_agent = target / ".claude/agents/orchestrator.md"
    before = claude_agent.read_bytes()

    def die_after_provider_backup(*_args, **_kwargs):
        raise _SimulatedTransitionProcessDeath()

    monkeypatch.setattr(
        runtime_scaffold, "_apply_runtime_files", die_after_provider_backup
    )
    with pytest.raises(_SimulatedTransitionProcessDeath):
        transition_runtime(
            payload,
            target,
            plan,
            InstallRequest(selection=selection, runtime="codex"),
            confirm_removal=True,
        )

    assert (target / StateLayout.neutral().journal).is_file()
    assert not claude_agent.exists()
    assert list(target.glob(".ckit.bak-*"))

    monkeypatch.undo()
    transition_runtime(
        payload,
        target,
        plan,
        InstallRequest(selection=selection, runtime="codex"),
        confirm_removal=True,
    )

    manifest = InitOptions.from_dict(
        json.loads(
            (target / StateLayout.neutral().manifest).read_text(encoding="utf-8")
        )
    )
    assert manifest.runtimes == ["codex"]
    assert not (target / StateLayout.neutral().journal).exists()
    assert not claude_agent.exists()
    backups = list(target.glob(".ckit.bak-*"))
    assert len(backups) == 1
    assert (
        backups[0] / "providers/.claude/agents/orchestrator.md"
    ).read_bytes() == before


def test_late_interrupted_provider_transition_recovers_manifest_before_routing(
    payload, tmp_path, monkeypatch
):
    """A target manifest written before process death must not bypass removal on retry."""
    from claude_kit import runtime_scaffold

    target = tmp_path / "both-late-interruption"
    selection = catalog.defaults(payload)
    plan = catalog.resolve(payload, selection)
    install_runtime(
        payload,
        target,
        plan,
        InstallRequest(selection=selection, runtime="both"),
    )
    before = (target / ".claude/agents/orchestrator.md").read_bytes()
    original_apply = runtime_scaffold._apply_runtime_files

    def apply_then_die(*args, **kwargs):
        original_apply(*args, **kwargs)
        raise _SimulatedTransitionProcessDeath()

    monkeypatch.setattr(runtime_scaffold, "_apply_runtime_files", apply_then_die)
    with pytest.raises(_SimulatedTransitionProcessDeath):
        transition_runtime(
            payload,
            target,
            plan,
            InstallRequest(selection=selection, runtime="codex"),
            confirm_removal=True,
        )
    monkeypatch.setattr(runtime_scaffold, "_apply_runtime_files", original_apply)

    partial = InitOptions.from_dict(
        json.loads((target / StateLayout.neutral().manifest).read_text())
    )
    assert partial.runtimes == ["codex"]
    assert not (target / ".claude").exists()
    assert (target / StateLayout.neutral().journal).is_file()
    assert list(target.glob(".ckit.bak-*"))

    transition_runtime(
        payload,
        target,
        plan,
        InstallRequest(selection=selection, runtime="codex"),
        confirm_removal=True,
    )

    final = InitOptions.from_dict(
        json.loads((target / StateLayout.neutral().manifest).read_text())
    )
    assert final.runtimes == ["codex"]
    assert not (target / ".claude").exists()
    assert not (target / StateLayout.neutral().journal).exists()
    backups = list(target.glob(".ckit.bak-*"))
    assert len(backups) == 1
    assert (
        backups[0] / "providers/.claude/agents/orchestrator.md"
    ).read_bytes() == before
