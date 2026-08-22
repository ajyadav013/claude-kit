"""Native runtime projection and transactional install integration tests."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

try:  # pragma: no cover - Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.9/3.10
    import tomli as tomllib  # type: ignore[no-redef]

from claude_kit import catalog
from claude_kit.models import (
    FileRecord,
    InitOptions,
    InstallRequest,
    Runtime,
    StateLayout,
)
from claude_kit.provider_renderers import CodexRenderer
from claude_kit.runtime_scaffold import (
    RuntimeInstallError,
    _merge_agents,
    install_runtime,
    preview_runtime_install,
    render_runtime_artifacts,
    transition_runtime,
)

_LEGACY_TEMPLATE_PATH = ".ckit/artifacts/templates/adr.md"


def _add_legacy_template_record(
    target: Path, *, baseline: bytes, live: bytes | None = None
) -> bytes:
    """Model one obsolete native manifest record from the prior release."""

    path = target / _LEGACY_TEMPLATE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(baseline if live is None else live)
    manifest = target / StateLayout.neutral().manifest
    options = InitOptions.from_dict(json.loads(manifest.read_text(encoding="utf-8")))
    options.files.append(
        FileRecord(
            path=_LEGACY_TEMPLATE_PATH,
            sha256=hashlib.sha256(baseline).hexdigest(),
            owner="kit",
            provider="shared",
            component_id="artifact://templates",
        )
    )
    encoded = (json.dumps(options.to_dict(), indent=2) + "\n").encode("utf-8")
    manifest.write_bytes(encoded)
    return encoded


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
    memory_index = target / ".ckit/agent-memory/MEMORY.md"
    assert memory_index.is_file()
    memory_text = memory_index.read_text(encoding="utf-8")
    assert "across coding-agent sessions" in memory_text
    assert "across Claude sessions" not in memory_text
    assert "across Codex sessions" not in memory_text
    assert (target / ".ckit/artifacts/.gitkeep").is_file()
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


def test_dual_runtime_has_no_redundant_shared_template_projection(payload, tmp_path):
    selection = catalog.defaults(payload)
    plan = catalog.resolve(payload, selection)
    request = InstallRequest(selection=selection, runtime="both")

    _projection, artifacts = render_runtime_artifacts(
        payload, tmp_path / "both", plan, request
    )

    native_template_content = {
        artifact.content
        for artifact in artifacts
        if artifact.path.startswith((".claude/templates/", ".ckit/templates/"))
    }
    redundant_shared = {
        artifact.path
        for artifact in artifacts
        if artifact.provider == "shared"
        and artifact.owner == "kit"
        and artifact.content in native_template_content
    }
    assert native_template_content
    assert redundant_shared == set()
    assert not any(
        artifact.path.startswith(".ckit/artifacts/templates/") for artifact in artifacts
    )


def test_reinstall_retires_hash_matched_legacy_template(payload, tmp_path):
    target = tmp_path / "legacy-template"
    selection = catalog.defaults(payload)
    plan = catalog.resolve(payload, selection)
    request = InstallRequest(selection=selection, runtime="claude")
    install_runtime(payload, target, plan, request)
    _add_legacy_template_record(target, baseline=b"legacy duplicate template\n")

    _projection, preview = preview_runtime_install(payload, target, plan, request)

    assert _LEGACY_TEMPLATE_PATH in preview
    assert (target / _LEGACY_TEMPLATE_PATH).is_file()

    log = install_runtime(payload, target, plan, request)

    assert not (target / _LEGACY_TEMPLATE_PATH).exists()
    options = InitOptions.from_dict(
        json.loads((target / StateLayout.neutral().manifest).read_text())
    )
    assert _LEGACY_TEMPLATE_PATH not in {record.path for record in options.files}
    assert any(
        f"retired duplicate legacy template {_LEGACY_TEMPLATE_PATH}" in line
        for line in log
    )
    assert (target / ".ckit/artifacts/.gitkeep").is_file()


def test_reinstall_preserves_modified_legacy_template_but_retires_ownership(
    payload, tmp_path
):
    target = tmp_path / "modified-legacy-template"
    selection = catalog.defaults(payload)
    plan = catalog.resolve(payload, selection)
    request = InstallRequest(selection=selection, runtime="claude")
    install_runtime(payload, target, plan, request)
    modified = b"user notes based on the old duplicate template\n"
    _add_legacy_template_record(
        target,
        baseline=b"legacy duplicate template\n",
        live=modified,
    )

    _projection, preview = preview_runtime_install(payload, target, plan, request)

    assert _LEGACY_TEMPLATE_PATH not in preview
    assert (target / _LEGACY_TEMPLATE_PATH).read_bytes() == modified

    log = install_runtime(payload, target, plan, request)

    assert (target / _LEGACY_TEMPLATE_PATH).read_bytes() == modified
    options = InitOptions.from_dict(
        json.loads((target / StateLayout.neutral().manifest).read_text())
    )
    assert _LEGACY_TEMPLATE_PATH not in {record.path for record in options.files}
    assert any(
        f"preserved user-modified legacy template {_LEGACY_TEMPLATE_PATH}" in line
        for line in log
    )

    # Once ownership is retired, later reinits continue treating the bytes as
    # untracked user content.
    install_runtime(payload, target, plan, request)
    assert (target / _LEGACY_TEMPLATE_PATH).read_bytes() == modified


def test_legacy_template_retirement_refuses_nonregular_destination(payload, tmp_path):
    target = tmp_path / "nonregular-legacy-template"
    selection = catalog.defaults(payload)
    plan = catalog.resolve(payload, selection)
    request = InstallRequest(selection=selection, runtime="claude")
    install_runtime(payload, target, plan, request)
    manifest = target / StateLayout.neutral().manifest
    options = InitOptions.from_dict(json.loads(manifest.read_text(encoding="utf-8")))
    options.files.append(
        FileRecord(
            path=_LEGACY_TEMPLATE_PATH,
            sha256=hashlib.sha256(b"legacy duplicate template\n").hexdigest(),
            owner="kit",
            provider="shared",
            component_id="artifact://templates",
        )
    )
    manifest.write_text(json.dumps(options.to_dict(), indent=2) + "\n")
    (target / _LEGACY_TEMPLATE_PATH).mkdir(parents=True)
    before = manifest.read_bytes()

    with pytest.raises(RuntimeInstallError, match="not a regular file"):
        preview_runtime_install(payload, target, plan, request)
    with pytest.raises(RuntimeInstallError, match="not a regular file"):
        install_runtime(payload, target, plan, request)

    assert (target / _LEGACY_TEMPLATE_PATH).is_dir()
    assert manifest.read_bytes() == before


def test_legacy_template_retirement_rolls_back_with_later_install_failure(
    payload, tmp_path, monkeypatch
):
    from claude_kit import runtime_scaffold

    target = tmp_path / "retirement-rollback"
    selection = catalog.defaults(payload)
    plan = catalog.resolve(payload, selection)
    request = InstallRequest(selection=selection, runtime="claude")
    install_runtime(payload, target, plan, request)
    before_manifest = _add_legacy_template_record(
        target, baseline=b"legacy duplicate template\n"
    )
    before_template = (target / _LEGACY_TEMPLATE_PATH).read_bytes()

    def fail_after_retirement(*_args, **_kwargs):
        raise RuntimeError("injected post-retirement failure")

    monkeypatch.setattr(runtime_scaffold, "_write_artifact", fail_after_retirement)
    with pytest.raises(RuntimeError, match="post-retirement failure"):
        install_runtime(payload, target, plan, request)

    assert (target / _LEGACY_TEMPLATE_PATH).read_bytes() == before_template
    assert (target / StateLayout.neutral().manifest).read_bytes() == before_manifest
    assert not (target / StateLayout.neutral().journal).exists()


@pytest.mark.parametrize(
    "marker_field",
    ["manifest", "stack_snapshot", "pipeline_snapshot", "continuity"],
)
def test_runtime_spine_refuses_each_authoritative_legacy_state_marker(
    payload, tmp_path, marker_field
):
    target = tmp_path / f"legacy-{marker_field}"
    marker = target / getattr(StateLayout.legacy_claude(), marker_field)
    marker.parent.mkdir(parents=True)
    expected = f"KEEP-{marker_field}\n".encode()
    marker.write_bytes(expected)
    selection = catalog.defaults(payload)
    plan = catalog.resolve(payload, selection)

    with pytest.raises(RuntimeInstallError, match="--migrate-state"):
        install_runtime(
            payload,
            target,
            plan,
            InstallRequest(selection=selection, runtime="claude"),
        )

    assert marker.read_bytes() == expected
    assert not (target / StateLayout.neutral().root).exists()
    assert not list(target.glob(".claude-kit-txn-*"))


def test_neutral_marker_precedence_ignores_stranded_legacy_manifest(payload, tmp_path):
    target = tmp_path / "neutral-authoritative"
    neutral_continuity = target / StateLayout.neutral().continuity
    neutral_continuity.parent.mkdir(parents=True)
    expected = b"# Neutral continuity\n\nKEEP-ME\n"
    neutral_continuity.write_bytes(expected)
    legacy_manifest = target / StateLayout.legacy_claude().manifest
    legacy_manifest.parent.mkdir(parents=True)
    legacy_manifest.write_text("not authoritative JSON\n", encoding="utf-8")
    selection = catalog.defaults(payload)
    plan = catalog.resolve(payload, selection)

    install_runtime(
        payload,
        target,
        plan,
        InstallRequest(selection=selection, runtime="claude"),
    )

    assert neutral_continuity.read_bytes() == expected
    assert legacy_manifest.read_text(encoding="utf-8") == "not authoritative JSON\n"
    options = InitOptions.from_dict(
        json.loads((target / StateLayout.neutral().manifest).read_text())
    )
    assert options.runtimes == ["claude"]


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


def test_runtime_validation_preserves_only_scoped_shannon_cli_settings(
    payload, tmp_path
):
    selection = catalog.defaults(payload)
    selection.profile = "standard"
    plan = catalog.resolve(payload, selection)

    _projection, artifacts = render_runtime_artifacts(
        payload,
        tmp_path / "shannon-runtime-validation",
        plan,
        InstallRequest(selection=selection, runtime="codex"),
    )
    paths = {artifact.path: artifact.content.decode("utf-8") for artifact in artifacts}
    names = {
        "CLAUDE_CODE_MAX_OUTPUT_TOKENS",
        "CLAUDE_CODE_USE_BEDROCK",
        "CLAUDE_CODE_USE_VERTEX",
        "CLAUDE_ADAPTIVE_THINKING",
    }

    for path in (
        ".agents/skills/shannon-ai-pentest/SKILL.md",
        ".agents/skills/shannon-ai-pentest/references/operating-guide.md",
    ):
        assert all(name in paths[path] for name in names)


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
