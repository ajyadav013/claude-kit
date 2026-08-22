"""Canonical skill/command inventory, contracts, and generated compatibility surfaces."""

from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path
from types import ModuleType

import pytest
import yaml

from claude_kit.canonical_skills import (
    CanonicalSkill,
    CanonicalSkillError,
    RequestMode,
    SkillSourceKind,
    discover_canonical_commands,
    discover_canonical_skills,
    load_canonical_skill,
    provider_leakage,
)
from claude_kit.components import Capability, InvocationMode

ROOT = Path(__file__).resolve().parents[1]


def _generator() -> ModuleType:
    path = ROOT / "scripts" / "gen_canonical_skill_payloads.py"
    spec = importlib.util.spec_from_file_location("gen_canonical_skill_payloads", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _frontmatter(text: str) -> tuple[dict[str, object], str]:
    parts = text.split("---", 2)
    assert len(parts) == 3
    metadata = yaml.safe_load(parts[1])
    assert isinstance(metadata, dict)
    return metadata, parts[2].strip()


def test_complete_reviewed_skill_and_command_inventory() -> None:
    skills = discover_canonical_skills(ROOT)
    commands = discover_canonical_commands(ROOT)

    assert len(skills) == 131
    assert sum(record.kind is SkillSourceKind.CORE for record in skills) == 122
    assert sum(record.kind is SkillSourceKind.ORG for record in skills) == 9
    assert len(commands) == 4
    assert {record.spec.id for record in commands} == {
        "abort",
        "init",
        "sdlc",
        "status",
    }
    assert {alias for record in commands for alias in record.aliases} == {
        "abort",
        "init",
        "sdlc",
        "status",
    }

    canonical_destinations = {record.destination for record in skills}
    expected_destinations = {
        path.relative_to(ROOT)
        for path in (ROOT / "skills").glob("*/SKILL.md")
        if path.parent.name != "_references"
        and not path.parent.name.startswith("ckit-command-")
    }
    expected_destinations.update(
        path.relative_to(ROOT)
        for path in (ROOT / "templates/org/skills").glob("*/SKILL.md")
    )
    assert canonical_destinations == expected_destinations


def test_invocation_input_pause_and_references_are_semantic() -> None:
    skills = discover_canonical_skills(ROOT)
    commands = discover_canonical_commands(ROOT)

    assert (
        sum(record.spec.invocation is InvocationMode.EXPLICIT for record in skills)
        == 16
    )
    assert (
        sum(record.request_input.mode is not RequestMode.NONE for record in skills)
        == 20
    )
    paused = {record.spec.id: record for record in skills if record.pause_for_human}
    assert set(paused) == {"idea-refine", "refresh-docs"}
    assert all(
        Capability.USER_INPUT in record.spec.capabilities for record in paused.values()
    )
    assert all(record.spec.invocation is InvocationMode.EXPLICIT for record in commands)
    assert all(record.spec.id in record.aliases for record in commands)

    for record in (*skills, *commands):
        text = record.canonical_path.read_text(encoding="utf-8")
        assert not provider_leakage(text), record.canonical_path
        assert all("://" in reference.uri for reference in record.spec.references)
        assert "$ARGUMENTS" not in text
        assert ".claude" not in text.lower()
        assert "AskUserQuestion" not in text


def test_codex_documents_use_only_supported_discovery_frontmatter() -> None:
    generator = _generator()
    records = (
        *discover_canonical_skills(ROOT),
        *discover_canonical_commands(ROOT),
    )
    for record in records:
        rendered = generator.render_codex_skill(record)
        metadata, body = _frontmatter(rendered)
        assert set(metadata) == {"name", "description"}
        assert isinstance(metadata["name"], str) and metadata["name"]
        assert isinstance(metadata["description"], str) and metadata["description"]
        assert body
        assert "$ARGUMENTS" not in rendered
        assert "AskUserQuestion" not in rendered
        assert ".claude/" not in rendered.lower()
        assert "disable-model-invocation" not in metadata
        assert "allowed-tools" not in metadata

        policy = generator.render_codex_policy(record)
        if record.spec.invocation is InvocationMode.EXPLICIT:
            sidecar = yaml.safe_load(policy)
            assert sidecar["policy"] == {"allow_implicit_invocation": False}
            assert set(sidecar["interface"]) == {
                "display_name",
                "short_description",
            }
            assert sidecar["interface"]["display_name"]
            assert sidecar["interface"]["short_description"]
        else:
            assert policy is None


def test_generator_is_current_and_owns_every_skill_command_payload() -> None:
    generator = _generator()
    assert generator.check(ROOT) == []
    outputs = generator.generated_payloads(ROOT)
    codex_plugin_root = ROOT / generator.CODEX_PLUGIN_ROOT
    legacy_outputs = {
        path for path in outputs if not path.is_relative_to(codex_plugin_root)
    }
    assert len(legacy_outputs) == 139  # 131 skills + four adapters + four wrappers

    codex_root = codex_plugin_root / "skills"
    codex_skills = sorted(codex_root.glob("*/SKILL.md"))
    codex_sidecars = sorted(codex_root.glob("*/agents/openai.yaml"))
    codex_references = sorted(codex_root.glob("*/references/*.md"))
    assert len(codex_skills) == 126  # 122 public skills + four command adapters
    assert len(codex_sidecars) == 20  # 16 explicit skills + four adapters
    assert len(codex_references) == 10
    assert not (codex_root / "_references").exists()
    assert not {
        record.spec.id
        for record in discover_canonical_skills(ROOT)
        if record.kind is SkillSourceKind.ORG
    } & {path.parent.name for path in codex_skills}

    for skill_path in codex_skills:
        metadata, body = _frontmatter(skill_path.read_text(encoding="utf-8"))
        assert set(metadata) == {"name", "description"}
        assert metadata["name"] == skill_path.parent.name
        assert "disable-model-invocation" not in metadata
        assert "allowed-tools" not in metadata
        assert "$ARGUMENTS" not in body
        assert "AskUserQuestion" not in body
        assert ".claude/" not in body.lower()

    for sidecar_path in codex_sidecars:
        sidecar = yaml.safe_load(sidecar_path.read_text(encoding="utf-8"))
        assert sidecar["policy"] == {"allow_implicit_invocation": False}
        assert sidecar["interface"]["display_name"]
        assert sidecar["interface"]["short_description"]

    for record in (
        *(
            record
            for record in discover_canonical_skills(ROOT)
            if record.kind is SkillSourceKind.CORE
        ),
        *discover_canonical_commands(ROOT),
    ):
        component_id = (
            record.spec.id
            if isinstance(record, CanonicalSkill)
            else record.adapter_skill_id
        )
        skill_root = codex_root / component_id
        declared_references = {
            reference.uri.removeprefix("artifact://skill-reference-")
            for reference in record.spec.references
            if reference.uri.startswith("artifact://skill-reference-")
        }
        installed_references = {
            path.stem for path in (skill_root / "references").glob("*.md")
        }
        assert installed_references == declared_references
        rendered = (skill_root / "SKILL.md").read_text(encoding="utf-8")
        for reference_id in declared_references:
            assert f"references/{reference_id}.md" in rendered

    orchestration = (
        codex_root
        / "doubt-driven-development"
        / "references"
        / "orchestration-patterns.md"
    ).read_text(encoding="utf-8")
    assert "## Host compatibility" in orchestration
    assert "Claude Code compatibility" not in orchestration
    assert ".claude/" not in orchestration.lower()

    command_paths = {
        ROOT / "commands" / f"{name}.md" for name in ("abort", "init", "sdlc", "status")
    }
    adapter_paths = {
        ROOT / "skills" / f"ckit-command-{name}" / "SKILL.md"
        for name in ("abort", "init", "sdlc", "status")
    }
    assert command_paths | adapter_paths <= set(outputs)
    for command in discover_canonical_commands(ROOT):
        wrapper, body = _frontmatter(outputs[ROOT / command.destination])
        assert wrapper["allowed-tools"] == "Skill"
        assert command.adapter_skill_id in body
        if command.request_input.mode is RequestMode.NONE:
            assert "$ARGUMENTS" not in body
        else:
            assert "$ARGUMENTS" in body
        adapter, _ = _frontmatter(
            outputs[ROOT / "skills" / command.adapter_skill_id / "SKILL.md"]
        )
        assert adapter["name"] == command.adapter_skill_id
        assert adapter["disable-model-invocation"] is True


def test_codex_command_adapters_use_explicit_native_runtime_contract() -> None:
    generator = _generator()
    root = ROOT / generator.CODEX_PLUGIN_ROOT / "skills"
    rendered = {
        name: (root / f"ckit-command-{name}" / "SKILL.md").read_text(encoding="utf-8")
        for name in ("abort", "init", "sdlc", "status")
    }

    init = rendered["init"]
    compact_init = " ".join(init.split())
    assert init.index("command -v ckit") < init.index("command -v claude-kit")
    assert "append `--runtime codex`" in init
    assert "CKIT_EXPERIMENTAL=1" in init
    assert "--config <temp-file> --runtime codex" in init
    assert "runtime: codex" in init
    assert ".ckit/config/init-options.json" in init
    assert "silently recorded `claude`" in init
    assert "CKIT_NO_AUTOCAPTURE=1" in init
    assert "CLAUDE_KIT_NO_AUTOCAPTURE" not in init
    assert "repository's changed-path set" in compact_init
    assert "does not assume a historical transcript contract" in compact_init
    assert "catch-up safely no-ops" in compact_init
    assert "reads session transcripts" not in init
    assert "legacy `CLAUDE_KIT_BASIC` alias" in init
    for native_path in (
        "AGENTS.md",
        ".agents/skills/",
        ".codex/agents/",
        ".codex/hooks.json",
        ".codex/hooks/scripts/",
        ".codex/config.toml",
        ".ckit/",
    ):
        assert native_path in init
    assert ".ckit/{rules, agents, skills, hooks" not in init

    assert "`ckit pipeline abort`" in rendered["abort"]
    assert "`ckit pipeline status`" in rendered["abort"]
    assert "`ckit status`" in rendered["status"]
    assert "`ckit validate`" in rendered["status"]
    assert ".agents/skills/" in rendered["status"]
    assert ".codex/agents/" in rendered["status"]
    assert "`mandatory-workflow`" in rendered["sdlc"]
    assert "`quality-gates`" in rendered["sdlc"]

    for command in rendered.values():
        assert "`the `" not in command
        assert "the `the " not in command
        assert "claude-kit pipeline" not in command


def test_generator_reports_unmanaged_payload(tmp_path: Path) -> None:
    generator = _generator()
    for relative in (
        "canonical",
        "schemas",
        "skills",
        "templates/org/skills",
        "commands",
        generator.CODEX_PLUGIN_ROOT,
    ):
        source = ROOT / relative
        destination = tmp_path / relative
        if source.is_dir():
            shutil.copytree(source, destination)
    unmanaged = tmp_path / "skills" / "unmanaged" / "SKILL.md"
    unmanaged.parent.mkdir(parents=True)
    unmanaged.write_text(
        "---\nname: unmanaged\ndescription: x\n---\nbody\n", encoding="utf-8"
    )

    diagnostics = generator.check(tmp_path)
    assert diagnostics == [
        "unmanaged skill/command outside canonical source: skills/unmanaged/SKILL.md"
    ]


def test_generator_reports_unmanaged_codex_plugin_skill_file(tmp_path: Path) -> None:
    generator = _generator()
    for relative in (
        "canonical",
        "schemas",
        "skills",
        "templates/org/skills",
        "commands",
        generator.CODEX_PLUGIN_ROOT,
    ):
        source = ROOT / relative
        destination = tmp_path / relative
        if source.is_dir():
            shutil.copytree(source, destination)
    unmanaged = (
        tmp_path / generator.CODEX_PLUGIN_ROOT / "skills" / "unmanaged" / "notes.md"
    )
    unmanaged.parent.mkdir(parents=True)
    unmanaged.write_text("not canonical\n", encoding="utf-8")

    assert generator.check(tmp_path) == [
        "unmanaged skill/command outside canonical source: "
        "providers/codex/claude-kit/skills/unmanaged/notes.md"
    ]


def test_loader_rejects_provider_leakage_and_reference_drift(tmp_path: Path) -> None:
    (tmp_path / "schemas").mkdir()
    shutil.copy2(
        ROOT / "schemas" / "canonical-skill.schema.json",
        tmp_path / "schemas" / "canonical-skill.schema.json",
    )
    source = tmp_path / "canonical" / "skills" / "core" / "bad.md"
    source.parent.mkdir(parents=True)
    metadata = {
        "schema_version": 1,
        "id": "bad",
        "description": "Portable description",
        "invocation": "implicit",
        "capabilities": [],
        "request_input": {"mode": "none"},
        "pause_for_human": [],
        "references": [],
    }

    source.write_text(
        "---\n"
        + yaml.safe_dump(metadata, sort_keys=False)
        + "---\n\nRead `.claude/rules/testing.md`.\n",
        encoding="utf-8",
    )
    with pytest.raises(CanonicalSkillError, match="provider syntax"):
        load_canonical_skill(tmp_path, source)

    source.write_text(
        "---\n"
        + yaml.safe_dump(metadata, sort_keys=False)
        + "---\n\nApply rule://testing.\n",
        encoding="utf-8",
    )
    with pytest.raises(CanonicalSkillError, match="references.*do not match"):
        load_canonical_skill(tmp_path, source)


def test_schemas_are_valid_draft_2020_12_documents() -> None:
    import jsonschema

    for name in ("canonical-skill.schema.json", "canonical-command.schema.json"):
        schema = json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)
