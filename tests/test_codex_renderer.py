"""Native Codex payload rendering from the unchanged source payload."""

from __future__ import annotations

import json
import posixpath
import re
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

try:
    import tomllib
except ImportError:  # pragma: no cover - Python 3.9/3.10 compatibility
    import tomli as tomllib  # type: ignore[no-redef]

from claude_kit import catalog
from claude_kit.canonical_rules import (
    render_codex_rule_layer,
    selected_rule_layers,
)
from claude_kit.canonical_skills import (
    SkillSourceKind,
    discover_canonical_skill_assets,
    discover_canonical_skills,
    raw_skill_invocations,
)
from claude_kit.components import Capability
from claude_kit.hooks import HOOK_REGISTRY, HOOK_SPECS
from claude_kit.models import InstallRequest, Runtime
from claude_kit.projection import ProjectionCompiler, Provider, RendererRegistry
from claude_kit.provider_compatibility import ProviderCompatibilityError
from claude_kit.provider_renderers import (
    CodexRenderer,
    _assert_no_provider_leakage,
    _render_agent_toml,
    _render_mcp_config,
)

_FORBIDDEN = (
    re.compile(r"\$ARGUMENTS"),
    re.compile(r"\bAskUserQuestion\b"),
    re.compile(r"\bCLAUDE_CODE_[A-Z0-9_]*\b"),
    re.compile(r"\bCLAUDE_PROJECT_DIR\b"),
    re.compile(r"\bCLAUDE_PLUGIN_ROOT\b"),
    re.compile(r"CLAUDE\.md"),
    re.compile(r"\.claude(?:/|\\)"),
    re.compile(r"(?<![\w./:-])/(?:claude-kit:[a-z-]+|sdlc\b)"),
    re.compile(r"--provider(?:=|\s+)claude\b"),
    re.compile(r"\buser corrects Claude\b", re.IGNORECASE),
    re.compile(r"\bwant Claude to\b", re.IGNORECASE),
    re.compile(r"\bCodex(?:'s)? (?:native dynamic-workflow|statusline API)\b"),
    re.compile(r"\bCodex prevents nested delegation\b"),
    re.compile(r"detached `claude`", re.IGNORECASE),
)
_MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
_FENCED_BLOCK = re.compile(r"(?:```|~~~).*?(?:```|~~~)", re.DOTALL)


def _local_skill_links(path: str, text: str) -> tuple[str, ...]:
    targets: list[str] = []
    for match in _MARKDOWN_LINK.finditer(_FENCED_BLOCK.sub("", text)):
        raw = match.group(1).strip()
        if raw.startswith("<") and ">" in raw:
            raw = raw[1 : raw.index(">")]
        else:
            raw = raw.split(maxsplit=1)[0]
        raw = raw.split("#", 1)[0]
        if (
            not raw
            or raw.startswith(("/", "#"))
            or "{" in raw
            or "}" in raw
            or "://" in raw
        ):
            continue
        target = posixpath.normpath(posixpath.join(posixpath.dirname(path), raw))
        if target.startswith(".agents/skills/"):
            targets.append(target)
    return tuple(dict.fromkeys(targets))


@pytest.fixture
def codex_projection(payload):
    selection = catalog.defaults(payload)
    selection.profile = "lean"
    selection.capture_mode = "session-end"
    selection.mcp = ["github", "linear"]
    plan = catalog.resolve(payload, selection)
    request = InstallRequest(selection=selection, runtime=Runtime.CODEX)
    renderer = CodexRenderer(payload)
    files = tuple(renderer.render(plan, request))
    return payload, selection, plan, request, renderer, files


def _by_path(files):
    return {item.path: item for item in files}


def _frontmatter(text: str):
    assert text.startswith("---\n")
    parsed = yaml.safe_load(text.split("---", 2)[1])
    assert isinstance(parsed, dict)
    return parsed


def _source_frontmatter(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8").split("---", 2)[1])


def _selected_inventory(payload: Path, plan) -> dict[str, frozenset[str]]:
    return {
        "agent": frozenset(dict.fromkeys(plan.agents + plan.overlay_agents)),
        "skill": frozenset(dict.fromkeys(plan.skills)),
        "rule": frozenset(layer.id for layer in selected_rule_layers(payload, plan)),
    }


def test_all_selected_native_artifacts_parse(codex_projection):
    _, _, _, _, _, files = codex_projection
    paths = _by_path(files)

    for item in files:
        if item.path.endswith(".toml"):
            document = tomllib.loads(item.text_content)
            assert isinstance(document, dict)
        elif item.path.endswith(".json"):
            document = json.loads(item.text_content)
            assert isinstance(document, dict)
        elif item.path.endswith(".yaml"):
            document = yaml.safe_load(item.text_content)
            assert isinstance(document, dict)
        elif item.path.endswith("/SKILL.md"):
            document = _frontmatter(item.text_content)
            assert set(document) == {"name", "description"}

    for path, item in paths.items():
        if path.startswith(".codex/hooks/scripts/"):
            result = subprocess.run(
                ["bash", "-n"],
                input=item.content,
                capture_output=True,
                check=False,
            )
            assert result.returncode == 0, (path, result.stderr.decode())
            assert item.executable is True


def test_agent_and_skill_counts_match_the_resolved_plan(codex_projection):
    payload, _, plan, _, _, files = codex_projection
    paths = _by_path(files)
    expected_agents = tuple(dict.fromkeys(plan.agents + plan.overlay_agents))
    expected_skills = tuple(dict.fromkeys(plan.skills))

    agent_paths = [
        path
        for path in paths
        if path.startswith(".codex/agents/") and path.endswith(".toml")
    ]
    skill_paths = [path for path in paths if path.endswith("/SKILL.md")]
    assert len(agent_paths) == len(expected_agents)
    assert len(skill_paths) == len(expected_skills)
    assert {Path(path).stem for path in agent_paths} == set(expected_agents)
    assert {Path(path).parent.name for path in skill_paths} == set(expected_skills)

    source_agent = _source_frontmatter(payload / "agents" / "orchestrator.md")
    native_agent = tomllib.loads(paths[".codex/agents/orchestrator.toml"].text_content)
    assert native_agent["name"] == source_agent["name"]
    assert native_agent["description"] == source_agent["description"]
    assert {
        "name",
        "description",
        "developer_instructions",
        "sandbox_mode",
        "agents",
        "features",
        "sandbox_workspace_write",
        "shell_environment_policy",
        "mcp_servers",
    } == set(native_agent)
    assert native_agent["sandbox_mode"] == "workspace-write"
    assert native_agent["agents"] == {"enabled": True}
    assert native_agent["features"]["multi_agent"] is True
    assert native_agent["features"]["browser_use"] is False
    assert native_agent["sandbox_workspace_write"] == {
        "network_access": False,
        "exclude_slash_tmp": True,
        "exclude_tmpdir_env_var": True,
    }
    assert native_agent["shell_environment_policy"] == {
        "inherit": "core",
        "ignore_default_excludes": False,
        "experimental_use_profile": False,
    }
    assert native_agent["mcp_servers"] == {
        "github": {"enabled": False},
        "linear": {"enabled": False},
    }
    assert "- Model tier: `deep`" in native_agent["developer_instructions"]
    assert "model" not in native_agent

    source_skill = _source_frontmatter(payload / "skills" / "sdlc" / "SKILL.md")
    native_skill_text = paths[".agents/skills/sdlc/SKILL.md"].text_content
    native_skill = _frontmatter(native_skill_text)
    assert native_skill["name"] == source_skill["name"]
    assert native_skill["description"] == source_skill["description"]
    assert "pipeline run --provider codex" in native_skill_text
    assert "--provider claude" not in native_skill_text

    execute = paths[".agents/skills/execute/SKILL.md"].text_content
    assert "want Codex to refine and act" in execute
    assert "want Claude to refine and act" not in execute


def test_project_skills_render_canonical_codex_host_semantics(payload):
    selection = catalog.defaults(payload)
    selection.profile = "standard"
    plan = catalog.resolve(payload, selection)
    files = tuple(
        CodexRenderer(payload).render(
            plan, InstallRequest(selection=selection, runtime=Runtime.CODEX)
        )
    )
    paths = _by_path(files)

    remember = paths[".agents/skills/remember/SKILL.md"].text_content
    assert "user corrects Codex" in remember
    assert "configured background capture adapter" in remember
    assert "explicit use of this skill remains available" in remember
    assert "/remember" not in remember
    assert "user corrects Claude" not in remember
    assert "detached `claude`" not in remember

    sdlc = paths[".agents/skills/sdlc/SKILL.md"].text_content
    assert "pipeline run --provider codex" in sdlc
    assert "a native dynamic-workflow facility, where supported" in sdlc
    assert "Codex's native dynamic-workflow" not in sdlc

    context = paths[".agents/skills/context-engineering/SKILL.md"].text_content
    assert "the host's status interface, where available" in context
    assert "Codex's statusline API" not in context

    doubt = paths[".agents/skills/doubt-driven-development/SKILL.md"].text_content
    assert "the active host or policy prevents nested delegation" in doubt
    assert "Codex prevents nested delegation" not in doubt

    shannon_paths = (
        ".agents/skills/shannon-ai-pentest/SKILL.md",
        ".agents/skills/shannon-ai-pentest/references/operating-guide.md",
    )
    external_names = {
        "CLAUDE_CODE_MAX_OUTPUT_TOKENS",
        "CLAUDE_CODE_USE_BEDROCK",
        "CLAUDE_CODE_USE_VERTEX",
        "CLAUDE_ADAPTIVE_THINKING",
    }
    for path in shannon_paths:
        text = paths[path].text_content
        assert all(name in text for name in external_names)
        assert "<host-env:code-" not in text
        assert "Shannon's provider-specific" not in text
        _assert_no_provider_leakage(text, location=path)

    with pytest.raises(ValueError, match="provider leakage"):
        _assert_no_provider_leakage(
            "CLAUDE_CODE_UNREVIEWED=1",
            location=shannon_paths[1],
        )
    with pytest.raises(ValueError, match="provider leakage"):
        _assert_no_provider_leakage(
            "CLAUDE_CODE_USE_BEDROCK=1",
            location=".agents/skills/other/SKILL.md",
        )


def test_codex_agent_renderer_uses_schema_validated_catalog_mappings(payload, tmp_path):
    root = tmp_path / "payload"
    (root / "catalog").mkdir(parents=True)
    (root / "schemas").mkdir(parents=True)
    shutil.copy2(payload / "catalog/codex-compatibility.yaml", root / "catalog")
    shutil.copy2(payload / "schemas/codex-compatibility.schema.json", root / "schemas")
    policy_path = root / "catalog/codex-compatibility.yaml"
    policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    policy["agents"]["model_tier_mapping"]["fast"] = "future-fast-model"
    policy["agents"]["sandbox_mapping"]["read_only"] = "workspace-write"
    policy_path.write_text(yaml.safe_dump(policy, sort_keys=False), encoding="utf-8")

    renderer = CodexRenderer(root)
    rendered = _render_agent_toml(
        {
            "name": "mapped-role",
            "description": "Compatibility mapping probe.",
            "permission": "read_only",
            "model_tier": "fast",
            "nested_delegation": "forbidden",
            "capabilities": (Capability.FILE_READ.value,),
        },
        "Follow the mapped contract.\n",
        compatibility=renderer._compatibility,
    )
    document = tomllib.loads(rendered)
    assert document["model"] == "future-fast-model"
    assert document["sandbox_mode"] == "workspace-write"
    assert renderer.spec.compatibility_catalog_version == policy["version"]

    del policy["agents"]["sandbox_mapping"]
    policy_path.write_text(yaml.safe_dump(policy, sort_keys=False), encoding="utf-8")
    with pytest.raises(ProviderCompatibilityError, match="sandbox_mapping"):
        CodexRenderer(root)


def test_selected_core_skill_cannot_resolve_from_organization_source(
    payload: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    skills = list(discover_canonical_skills(payload))
    index = next(
        index for index, record in enumerate(skills) if record.spec.id == "sdlc"
    )
    skills[index] = replace(skills[index], kind=SkillSourceKind.ORG)
    monkeypatch.setattr(
        "claude_kit.provider_renderers.discover_canonical_skills",
        lambda _root: tuple(skills),
    )
    selection = catalog.defaults(payload)
    plan = catalog.resolve(payload, selection)

    with pytest.raises(
        ValueError, match="selected core skill has no canonical definition: sdlc"
    ):
        tuple(
            CodexRenderer(payload).render(
                plan, InstallRequest(selection=selection, runtime=Runtime.CODEX)
            )
        )


def test_manual_only_skills_emit_openai_policy(codex_projection):
    _, _, _, _, _, files = codex_projection
    paths = _by_path(files)
    policy_paths = sorted(path for path in paths if path.endswith("agents/openai.yaml"))
    assert policy_paths
    assert ".agents/skills/api-integration/agents/openai.yaml" in policy_paths
    for path in policy_paths:
        assert yaml.safe_load(paths[path].text_content) == {
            "policy": {"allow_implicit_invocation": False}
        }


def test_agents_document_names_roles_gates_and_digest(codex_projection):
    payload, _, plan, _, _, files = codex_projection
    paths = _by_path(files)
    document = paths["AGENTS.md"].text_content
    layers = selected_rule_layers(payload, plan)
    selected_inventory = _selected_inventory(payload, plan)

    assert len(document.encode("utf-8")) < 32 * 1024
    assert "named multi-agent" in document
    assert "`spawn_agent`" in document
    assert "`.ckit/CONTINUITY.md`" in document
    assert plan.gate_definition_digest in document
    for gate in plan.gates:
        assert f"`{gate}`" in document
    for agent in dict.fromkeys(plan.agents + plan.overlay_agents):
        assert f"`{agent}`" in document
    assert (
        "Session-end and per-task learning capture use the selected provider"
        in document
    )
    assert "Historical-session catch-up is a safe no-op" in document
    assert "# Selected engineering rules" in document
    assert "## Additional selected rules" in document
    for layer in layers:
        assert f".ckit/rules/{layer.id}.md" in paths
        assert paths[f".ckit/rules/{layer.id}.md"].text_content == (
            render_codex_rule_layer(layer, selected_inventory=selected_inventory)
        )
        assert f"## Rule: {layer.id}\n" in document or f"`{layer.id}`" in document


def test_canonical_templates_project_to_truthful_codex_paths(codex_projection):
    _, _, _, _, _, files = codex_projection
    paths = _by_path(files)

    expected = {
        ".ckit/STACK.md",
        ".ckit/CONTINUITY.template.md",
        ".ckit/templates/agent-memory/MEMORY.md",
        ".ckit/README.sdlc.md",
        ".ckit/templates/adr.md",
        ".ckit/templates/api-change-report.md",
        ".ckit/templates/change-proposal.md",
        ".ckit/templates/feature-spec.md",
        ".ckit/templates/release-plan.md",
        ".ckit/templates/runbook.md",
        ".ckit/templates/security-review.md",
        ".ckit/templates/test-plan.md",
    }
    assert expected <= set(paths)

    stack = paths[".ckit/STACK.md"].text_content
    assert "Project-specific rules" in stack
    assert ".ckit/rules/" in stack
    assert "{{" not in stack and "{%" not in stack

    readme = paths[".ckit/README.sdlc.md"].text_content
    readme_flat = " ".join(readme.split())
    assert ".codex/agents/*.toml" in readme
    assert ".agents/skills/*/SKILL.md" in readme
    assert ".ckit/scripts/sdlc-loop.sh" in readme
    assert "new unattended iterations currently fail closed" in readme_flat
    assert "resolves at most one gate per iteration" not in readme
    assert "Historical-session catch-up is a safe no-op" in readme
    assert "unsupported legacy unattended loop" not in readme
    assert "slash commands" not in readme
    assert "{{" not in readme and "{%" not in readme


@pytest.mark.parametrize(
    ("profile", "scope", "org_packs"),
    (
        ("lean", "individual", False),
        ("standard", "individual", False),
        ("enterprise", "organization", True),
    ),
)
def test_profile_projections_close_selected_native_references(
    payload: Path,
    profile: str,
    scope: str,
    org_packs: bool,
) -> None:
    selection = catalog.defaults(payload)
    selection.profile = profile
    selection.scope = scope
    selection.org_packs = org_packs
    plan = catalog.resolve(payload, selection)
    files = tuple(
        CodexRenderer(payload).render(
            plan, InstallRequest(selection=selection, runtime=Runtime.CODEX)
        )
    )
    paths = _by_path(files)
    known_skill_ids = frozenset(
        record.spec.id for record in discover_canonical_skills(payload)
    )

    for item in files:
        for target in _local_skill_links(item.path, item.text_content):
            assert target in paths, f"{item.path} -> {target}"
        for component_id in re.findall(
            r"(?<![\w/])\.codex/agents/([a-z0-9][a-z0-9._-]*)\.toml",
            item.text_content,
        ):
            assert f".codex/agents/{component_id}.toml" in paths, item.path
        for component_id in re.findall(
            r"(?<![\w/])\.agents/skills/([a-z0-9][a-z0-9._-]*)(?:/SKILL\.md|/)",
            item.text_content,
        ):
            assert f".agents/skills/{component_id}/SKILL.md" in paths, item.path
        for component_id in re.findall(
            r"(?<![\w/])\.ckit/rules/([a-z0-9][a-z0-9._-]*)\.md",
            item.text_content,
        ):
            assert f".ckit/rules/{component_id}.md" in paths, item.path
        for component_id in re.findall(
            r"(?<![\w$])\$([a-z0-9][a-z0-9._-]*)\b",
            item.text_content,
        ):
            if component_id in known_skill_ids:
                assert f".agents/skills/{component_id}/SKILL.md" in paths, item.path

    dockerfile = paths[".agents/skills/dockerfile-backend/SKILL.md"].text_content
    if profile in {"lean", "standard"}:
        assert "../containerization-and-deployment/SKILL.md" not in dockerfile
        assert (
            "the optional `containerization-and-deployment` skill "
            "(not installed for this selection; do not invoke)" in dockerfile
        )
    else:
        assert "../containerization-and-deployment/SKILL.md" in dockerfile
        assert ".agents/skills/containerization-and-deployment/SKILL.md" in paths


@pytest.mark.parametrize("profile", ("lean", "standard", "enterprise"))
@pytest.mark.parametrize("scope", ("individual", "team", "organization"))
def test_profile_scope_matrix_has_context_safe_reference_code_spans(
    payload: Path,
    profile: str,
    scope: str,
) -> None:
    selection = catalog.defaults(payload)
    selection.profile = profile
    selection.scope = scope
    selection.org_packs = scope == "organization"
    plan = catalog.resolve(payload, selection)
    files = tuple(
        CodexRenderer(payload).render(
            plan, InstallRequest(selection=selection, runtime=Runtime.CODEX)
        )
    )

    for item in files:
        text = item.text_content
        assert "`the optional `" not in text, item.path
        assert "`the installed `" not in text, item.path
        assert not re.search(
            r"``(?:ckit |\$[a-z0-9]|\.(?:ckit|agents|codex)/)", text
        ), item.path
        for span in re.findall(r"(?<!`)`(?!`)([^`\n]+)(?<!`)`(?!`)", text):
            assert not span.startswith(("the optional ", "the installed ")), item.path
            assert "not installed for this selection" not in span, item.path


def test_cross_owner_asset_closure_does_not_install_foreign_skills(
    payload: Path,
) -> None:
    selection = catalog.defaults(payload)
    selection.profile = "enterprise"
    plan = catalog.resolve(payload, selection)

    plan.skills.remove("system-design-patterns")
    files = tuple(
        CodexRenderer(payload).render(
            plan, InstallRequest(selection=selection, runtime=Runtime.CODEX)
        )
    )
    paths = _by_path(files)
    assert ".agents/skills/system-design-patterns/SKILL.md" not in paths
    assert (
        ".agents/skills/system-design-patterns/references/htn-design-instagram.md"
        in paths
    )
    assert (
        ".agents/skills/system-design-patterns/references/htn-design-youtube-hld.md"
        in paths
    )

    plan = catalog.resolve(payload, selection)
    plan.skills.remove("python-dao-and-database")
    files = tuple(
        CodexRenderer(payload).render(
            plan, InstallRequest(selection=selection, runtime=Runtime.CODEX)
        )
    )
    paths = _by_path(files)
    assert ".agents/skills/python-dao-and-database/SKILL.md" not in paths
    assert (
        ".agents/skills/python-dao-and-database/references/"
        "asdr-026-acid-transactions.md" in paths
    )
    assert (
        ".agents/skills/python-dao-and-database/references/"
        "asdr-028-database-indexes.md" in paths
    )


def test_selected_asset_missing_local_target_fails_closed(
    payload: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assets = list(discover_canonical_skill_assets(payload))
    index = next(
        index
        for index, asset in enumerate(assets)
        if asset.skill_id == "alembic-migrations"
    )
    assets[index] = replace(
        assets[index], content=assets[index].content + "\n[missing](missing.md)\n"
    )
    monkeypatch.setattr(
        "claude_kit.provider_renderers.discover_canonical_skill_assets",
        lambda _root: tuple(assets),
    )
    selection = catalog.defaults(payload)
    selection.profile = "lean"
    plan = catalog.resolve(payload, selection)

    with pytest.raises(ValueError, match="selected skill asset link is missing"):
        tuple(
            CodexRenderer(payload).render(
                plan, InstallRequest(selection=selection, runtime=Runtime.CODEX)
            )
        )


def test_organization_templates_include_only_selected_pack_manifests(payload):
    selection = catalog.defaults(payload)
    selection.profile = "enterprise"
    selection.scope = "organization"
    selection.org_packs = True
    plan = catalog.resolve(payload, selection)
    files = tuple(
        CodexRenderer(payload).render(
            plan, InstallRequest(selection=selection, runtime=Runtime.CODEX)
        )
    )
    paths = _by_path(files)

    assert plan.org is not None
    assert ".ckit/org-packs/README.md" in paths
    for pack in plan.org.packs:
        readme = f".ckit/org-packs/{pack}/README.md"
        manifest = f".ckit/org-packs/{pack}/pack.yaml"
        assert readme in paths
        assert manifest in paths
        assert yaml.safe_load(paths[manifest].text_content)["id"] == pack
        assert "{{ provider." not in paths[readme].text_content


def test_hooks_include_selected_scripts_and_provider_selected_capture(
    codex_projection,
):
    _, _, plan, _, _, files = codex_projection
    paths = _by_path(files)
    hooks = json.loads(paths[".codex/hooks.json"].text_content)["hooks"]
    entries = [
        entry
        for matchers in hooks.values()
        for matcher in matchers
        for entry in matcher["hooks"]
    ]
    assert len(entries) == len(plan.hooks)

    expected_scripts = {
        str(HOOK_REGISTRY[hook_id]["script"])
        for hook_id in plan.hooks
        if HOOK_REGISTRY[hook_id]["script"]
    }
    emitted_scripts = {
        Path(path).name for path in paths if path.startswith(".codex/hooks/scripts/")
    }
    assert emitted_scripts == expected_scripts
    for entry in entries:
        assert entry["command"].startswith("ckit hook-run --provider codex ")
        assert "CKIT_PROJECT_ROOT" in entry["command"]
        assert entry["command"].endswith("--discover-project-root")
        assert ".codex/hooks/scripts" not in entry["command"]
    for hook_id in plan.hooks:
        assert any(f"--hook-id {hook_id} " in entry["command"] for entry in entries)

    matchers = [block["matcher"] for blocks in hooks.values() for block in blocks]
    for hook_id in plan.hooks:
        semantic = HOOK_SPECS[hook_id].operation_matcher
        if semantic == "shell":
            assert "Bash|exec_command|shell|unified_exec" in matchers
        if semantic == "file-read|shell":
            assert "Read|read_file|Bash|exec_command|shell|unified_exec" in matchers
        if semantic and "apply-patch" in semantic:
            assert any("apply_patch" in matcher for matcher in matchers)

    capture = paths[".codex/hooks/scripts/capture-learnings.sh"].text_content
    assert 'CAPTURE_PROVIDER="${CKIT_HOOK_PROVIDER:-codex}"' in capture
    assert 'capture_args=(learning-capture --path "$PROJ"' in capture
    assert "workspace-write" not in capture
    assert "command -v ckit" in capture
    assert "command -v claude" not in capture
    assert " claude " not in capture
    assert ".ckit/agent-memory" in capture
    continuity = paths[".codex/hooks/scripts/load-continuity.sh"].text_content
    assert ".ckit/CONTINUITY.md" in continuity


def test_mcp_config_uses_native_tables_and_environment_forwarding(
    codex_projection,
):
    _, _, _, _, _, files = codex_projection
    config = tomllib.loads(_by_path(files)[".codex/config.toml"].text_content)
    servers = config["mcp_servers"]
    assert servers["github"] == {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-github@2025.4.8"],
        "env_vars": ["GITHUB_PERSONAL_ACCESS_TOKEN"],
    }
    assert servers["linear"] == {"url": "https://mcp.linear.app/mcp"}


def test_mcp_config_uses_codex_native_http_header_fields():
    document = tomllib.loads(
        _render_mcp_config(
            {
                "remote": {
                    "type": "http",
                    "url": "https://mcp.example.test/mcp",
                    "headers": {
                        "Authorization": "${REMOTE_BEARER_TOKEN}",
                        "X-Region": "us-east-1",
                    },
                }
            }
        )
    )

    assert document["mcp_servers"]["remote"] == {
        "url": "https://mcp.example.test/mcp",
        "http_headers": {"X-Region": "us-east-1"},
        "env_http_headers": {"Authorization": "REMOTE_BEARER_TOKEN"},
    }
    assert "headers" not in document["mcp_servers"]["remote"]


def test_mcp_semantic_client_context_projects_to_codex(payload):
    selection = catalog.defaults(payload)
    selection.mcp = ["serena"]
    plan = catalog.resolve(payload, selection)
    files = tuple(
        CodexRenderer(payload).render(
            plan, InstallRequest(selection=selection, runtime=Runtime.CODEX)
        )
    )
    text = _by_path(files)[".codex/config.toml"].text_content
    server = tomllib.loads(text)["mcp_servers"]["serena"]

    assert server["args"] == ["start-mcp-server", "--context", "codex"]
    assert "provider://" not in text
    assert "claude-code" not in text


def test_projection_is_deterministic_and_contains_no_provider_leakage(
    codex_projection,
):
    payload, _, plan, request, renderer, first = codex_projection
    second = tuple(renderer.render(plan, request))
    assert [
        (item.path, item.content, item.executable, item.media_type) for item in first
    ] == [
        (item.path, item.content, item.executable, item.media_type) for item in second
    ]

    known_skill_ids = frozenset(
        record.spec.id for record in discover_canonical_skills(payload)
    )
    for item in first:
        for pattern in _FORBIDDEN:
            assert not pattern.search(item.text_content), (
                item.path,
                pattern.pattern,
            )
        assert raw_skill_invocations(item.text_content, known_skill_ids) == (), (
            item.path
        )


def test_renderer_integrates_with_branch_free_projection_compiler(
    codex_projection,
):
    _, _, plan, request, renderer, direct = codex_projection
    registry = RendererRegistry((renderer,))
    compiled = ProjectionCompiler(registry).compile(plan, request)
    assert compiled.providers == (Provider.CODEX,)
    assert [(item.path, item.content) for item in compiled.files] == [
        (item.path, item.content) for item in direct
    ]
