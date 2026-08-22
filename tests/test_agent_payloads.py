"""Canonical-agent coverage, schema, projection, and drift tests."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

try:
    import tomllib
except ImportError:  # pragma: no cover - Python 3.9/3.10 compatibility
    import tomli as tomllib  # type: ignore[no-redef]

from claude_kit import catalog
from claude_kit.canonical_agents import (
    AgentSourceKind,
    CanonicalAgentError,
    discover_canonical_agents,
    find_canonical_agent,
    load_canonical_agent,
    provider_leakage,
)
from claude_kit.components import Capability, ModelTier, PermissionClass
from claude_kit.models import InstallRequest, Runtime
from claude_kit.provider_compatibility import ProviderCompatibilityError
from claude_kit.provider_renderers import CodexRenderer
from scripts.gen_provider_payloads import (
    check_agents as check_generated_agents,
)
from scripts.gen_provider_payloads import generated_agents
from tests._helpers import make_selection

_SYMBOLIC_REF = re.compile(
    r"\b(?:agent|skill|rule|command|hook|workflow|stage|handler|gate|state|artifact)://"
)
_CODEX_AGENT_CLAUDE_LEAKAGE = (
    re.compile(r"\bClaude(?: Code)?\b", re.IGNORECASE),
    re.compile(r"\b(?:sonnet|opus|haiku)\b", re.IGNORECASE),
    re.compile(r"\b(?:permissionMode|acceptEdits|bypassPermissions)\b"),
    re.compile(r"\b(?:SendMessage|TaskCreate|TaskGet|TaskList|TaskUpdate)\b"),
    re.compile(r"\.claude(?:/|\\|\b)", re.IGNORECASE),
    re.compile(r"\bCLAUDE\.md\b"),
)


def _frontmatter(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    _, raw, body = text.split("---", 2)
    parsed = yaml.safe_load(raw)
    assert isinstance(parsed, dict)
    return parsed, body.strip()


def test_complete_agent_surface_is_canonical(payload: Path) -> None:
    records = discover_canonical_agents(payload)

    assert len(records) == 40
    assert sum(record.kind is AgentSourceKind.CORE for record in records) == 29
    assert sum(record.kind is AgentSourceKind.STACK for record in records) == 5
    assert sum(record.kind is AgentSourceKind.ORG for record in records) == 6
    assert {
        record.spec.id for record in records if record.kind is AgentSourceKind.CORE
    } == set(catalog.available(payload)["agents"])
    migrations = [
        record for record in records if record.spec.id == "migration-specialist"
    ]
    assert {record.stack_dir for record in migrations} == {"db/mongodb", "db/postgres"}
    assert migrations[0].spec.instructions != migrations[1].spec.instructions


def test_every_canonical_agent_is_a_complete_leak_free_agent_spec(
    payload: Path,
) -> None:
    records = discover_canonical_agents(payload)

    for record in records:
        source = record.canonical_path.read_text(encoding="utf-8")
        assert provider_leakage(source) == (), record.canonical_path
        assert record.spec.model_tier in set(ModelTier)
        assert record.spec.permission in set(PermissionClass)
        assert Capability.FILE_READ in record.spec.capabilities
        if record.spec.permission is PermissionClass.READ_ONLY:
            assert record.spec.write_scope == ()
            assert Capability.FILE_WRITE not in record.spec.capabilities
        else:
            assert record.spec.write_scope
        if record.spec.nested_delegation.value != "forbidden":
            assert Capability.DELEGATE in record.spec.capabilities
        assert all(reference.uri in source for reference in record.spec.references)
        assert all(
            reference.uri in {item.uri for item in record.spec.references}
            for reference in record.spec.required_skills
        )


def test_generated_claude_agents_are_valid_and_match_canonical_specs(
    payload: Path,
) -> None:
    records = discover_canonical_agents(payload)

    for record in records:
        generated = payload / record.destination
        metadata, body = _frontmatter(generated)
        expected_metadata = {
            "name",
            "description",
            "tools",
            "permissionMode",
            "model",
            "color",
            "tier",
        }
        if record.spec.isolation.value != "none":
            expected_metadata.add("isolation")
            assert metadata["isolation"] == "worktree"
        assert set(metadata) == expected_metadata
        assert metadata["name"] == record.spec.id
        assert metadata["description"] == record.spec.description
        assert metadata["tools"]
        assert metadata["permissionMode"] in {"plan", "acceptEdits"}
        assert metadata["model"] in {"haiku", "sonnet", "opus"}
        assert metadata["tier"] == record.workflow_tier.value
        assert body
        assert "## Semantic role contract" in body
        assert f"- Permission class: `{record.spec.permission.value}`" in body
        assert f"- Isolation: `{record.spec.isolation.value}`" in body
        assert f"- Nested delegation: `{record.spec.nested_delegation.value}`" in body
        assert f"- Model tier: `{record.spec.model_tier.value}`" in body
        assert not _SYMBOLIC_REF.search(body), generated


def test_claude_agent_generation_uses_schema_validated_compatibility_mappings(
    payload: Path, tmp_path: Path
) -> None:
    root = tmp_path / "payload"
    shutil.copytree(payload / "canonical", root / "canonical")
    (root / "catalog").mkdir(parents=True)
    (root / "schemas").mkdir(parents=True)
    shutil.copy2(payload / "catalog" / "claude-compatibility.yaml", root / "catalog")
    for name in ("canonical-agent.schema.json", "claude-compatibility.schema.json"):
        shutil.copy2(payload / "schemas" / name, root / "schemas")

    policy_path = root / "catalog" / "claude-compatibility.yaml"
    policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    policy["agents"]["model_tier_mapping"] = {
        "fast": "opus",
        "balanced": "opus",
        "deep": "opus",
    }
    policy["agents"]["permission_class_mapping"] = {
        "read_only": "acceptEdits",
        "workspace_write": "acceptEdits",
        "external_effect": "acceptEdits",
    }
    policy_path.write_text(yaml.safe_dump(policy, sort_keys=False), encoding="utf-8")

    content = generated_agents(root)[root / "agents" / "orchestrator.md"]
    metadata = yaml.safe_load(content.split("---", 2)[1])
    assert metadata["model"] == "opus"
    assert metadata["permissionMode"] == "acceptEdits"

    del policy["agents"]["model_tier_mapping"]["fast"]
    policy_path.write_text(yaml.safe_dump(policy, sort_keys=False), encoding="utf-8")
    with pytest.raises(ProviderCompatibilityError, match="model_tier_mapping"):
        generated_agents(root)


def test_generator_check_is_clean_and_write_is_byte_deterministic(
    payload: Path,
) -> None:
    paths = [
        payload / record.destination for record in discover_canonical_agents(payload)
    ]
    before = {path: path.read_bytes() for path in paths}

    checked = subprocess.run(
        [sys.executable, "scripts/gen_provider_payloads.py", "--check"],
        cwd=payload,
        text=True,
        capture_output=True,
        check=False,
    )
    written = subprocess.run(
        [sys.executable, "scripts/gen_provider_payloads.py"],
        cwd=payload,
        text=True,
        capture_output=True,
        check=False,
    )

    assert checked.returncode == 0, checked.stderr
    assert written.returncode == 0, written.stderr
    assert before == {path: path.read_bytes() for path in paths}


def test_generator_reports_stale_and_unmanaged_agents(
    payload: Path, tmp_path: Path
) -> None:
    root = tmp_path / "payload"
    shutil.copytree(payload / "canonical", root / "canonical")
    (root / "catalog").mkdir(parents=True)
    (root / "schemas").mkdir(parents=True)
    shutil.copy2(payload / "catalog" / "claude-compatibility.yaml", root / "catalog")
    for name in ("canonical-agent.schema.json", "claude-compatibility.schema.json"):
        shutil.copy2(payload / "schemas" / name, root / "schemas")
    records = discover_canonical_agents(payload)
    for record in records:
        target = root / record.destination
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(payload / record.destination, target)
    assert check_generated_agents(root) == []

    (root / "agents" / "orchestrator.md").write_text("stale\n", encoding="utf-8")
    (root / "agents" / "unmanaged.md").write_text("unmanaged\n", encoding="utf-8")
    diagnostics = check_generated_agents(root)

    assert "stale generated agent: agents/orchestrator.md" in diagnostics
    assert (
        "unmanaged agent outside canonical source: agents/unmanaged.md" in diagnostics
    )


def test_canonical_schema_rejects_unknown_fields(payload: Path, tmp_path: Path) -> None:
    root = tmp_path / "payload"
    source_dir = root / "canonical" / "agents" / "core"
    schema_dir = root / "schemas"
    source_dir.mkdir(parents=True)
    schema_dir.mkdir(parents=True)
    shutil.copy2(payload / "schemas" / "canonical-agent.schema.json", schema_dir)
    metadata, body = _frontmatter(
        payload / "canonical" / "agents" / "core" / "developer.md"
    )
    metadata["native_model"] = "forbidden"
    source = source_dir / "developer.md"
    source.write_text(
        "---\n"
        + yaml.safe_dump(metadata, sort_keys=False, allow_unicode=True)
        + "---\n\n"
        + body
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(CanonicalAgentError, match="native_model"):
        load_canonical_agent(root, source)


@pytest.mark.parametrize("database", ["postgres", "mongodb"])
def test_codex_renderer_reads_all_selected_agents_from_canonical_sources(
    payload: Path, database: str
) -> None:
    selection = make_selection(
        payload,
        profile="enterprise",
        scope="organization",
        database=database,
    )
    plan = catalog.resolve(payload, selection)
    request = InstallRequest(selection=selection, runtime=Runtime.CODEX)
    files = tuple(CodexRenderer(payload).render(plan, request))
    native = {
        Path(item.path).stem: tomllib.loads(item.text_content)
        for item in files
        if item.path.startswith(".codex/agents/")
    }
    expected_ids = set(plan.agents + plan.overlay_agents + plan.org.org_agents)

    assert set(native) == expected_ids
    for agent_id in plan.agents:
        source = find_canonical_agent(payload, agent_id, kind=AgentSourceKind.CORE)
        assert native[agent_id]["description"] == source.spec.description
    for agent_id in plan.overlay_agents:
        source = find_canonical_agent(
            payload,
            agent_id,
            kind=AgentSourceKind.STACK,
            stack_dir=f"db/{database}",
        )
        assert native[agent_id]["description"] == source.spec.description
    for agent_id in plan.org.org_agents:
        source = find_canonical_agent(payload, agent_id, kind=AgentSourceKind.ORG)
        assert native[agent_id]["description"] == source.spec.description

    for document in native.values():
        assert {
            "name",
            "description",
            "developer_instructions",
            "sandbox_mode",
            "agents",
            "features",
            "sandbox_workspace_write",
            "shell_environment_policy",
        } <= set(document)
        assert document["sandbox_mode"] in {"read-only", "workspace-write"}
        assert isinstance(document["agents"]["enabled"], bool)
        assert isinstance(document["features"]["multi_agent"], bool)
        assert document["sandbox_workspace_write"]["network_access"] is False
        assert document["shell_environment_policy"] == {
            "inherit": "core",
            "ignore_default_excludes": False,
            "experimental_use_profile": False,
        }
        assert "model" not in document
        assert "## Semantic role contract" in document["developer_instructions"]
        for pattern in _CODEX_AGENT_CLAUDE_LEAKAGE:
            assert not pattern.search(document["developer_instructions"]), (
                pattern.pattern
            )
