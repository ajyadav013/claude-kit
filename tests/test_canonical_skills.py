"""Canonical skill/command inventory, contracts, and generated compatibility surfaces."""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import stat
from dataclasses import replace
from pathlib import Path
from types import ModuleType

import pytest
import yaml

from claude_kit.canonical_skills import (
    CanonicalSkill,
    CanonicalSkillError,
    RequestMode,
    SkillSourceKind,
    _ensure_unique_skill_asset_destinations,
    codex_reference_target,
    discover_canonical_commands,
    discover_canonical_skill_assets,
    discover_canonical_skills,
    load_canonical_skill,
    project_codex_reference_tokens,
    project_codex_skill,
    project_codex_skill_asset,
    provider_leakage,
    raw_skill_invocations,
)
from claude_kit.components import Capability, InvocationMode
from claude_kit.provider_renderers import codex_provider_leakage_scan_text

ROOT = Path(__file__).resolve().parents[1]

_MARKDOWN_LINK_RE = re.compile(
    r"!?\[[^\]]*\]\(\s*(?:<(?P<angled>[^>]+)>|(?P<plain>[^)\s]+))"
)
_FENCED_BLOCK_RE = re.compile(r"(?:```|~~~).*?(?:```|~~~)", re.DOTALL)
_SOURCE_HOST_WIRE_RE = re.compile(
    r"(?:"
    r"(?:^|[^a-zA-Z0-9_])\.claude(?:/|\\)|"
    r"\bCLAUDE_CODE_[A-Z0-9_]+\b|"
    r"\bAskUserQuestion\b|"
    r"\ballowed-tools\s*:|"
    r"\$(?:ARGUMENTS|ARGUMENTS\[[0-9]+\])\b|"
    r"\bExplore agent\b|`Explore`"
    r")",
    re.IGNORECASE,
)


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


def _local_markdown_targets(source: Path, boundary: Path) -> tuple[Path, ...]:
    """Resolve bundled Markdown links while ignoring examples and project paths."""
    text = _FENCED_BLOCK_RE.sub("", source.read_text(encoding="utf-8"))
    targets: list[Path] = []
    boundary = boundary.resolve()
    for match in _MARKDOWN_LINK_RE.finditer(text):
        raw = (match.group("angled") or match.group("plain")).strip()
        if not raw or raw.startswith(("#", "/")):
            continue
        if "{" in raw or "}" in raw:
            continue
        if re.match(r"^[a-z][a-z0-9+.-]*:", raw, flags=re.IGNORECASE):
            continue
        relative = raw.split("#", 1)[0].split("?", 1)[0]
        if not relative:
            continue
        target = (source.parent / relative).resolve()
        try:
            target.relative_to(boundary)
        except ValueError:
            # Templates may link to files in the project being scaffolded. They
            # are not links to bundled skill assets.
            continue
        targets.append(target)
    return tuple(targets)


def _expected_codex_auxiliary_assets(codex_root: Path) -> dict[Path, str]:
    assets = discover_canonical_skill_assets(ROOT)
    shared = {
        asset.relative_path.stem: asset
        for asset in assets
        if asset.skill_id == "_references"
    }
    expected = {
        codex_root / asset.skill_id / asset.relative_path: project_codex_skill_asset(
            asset, plugin_context=True
        )
        for asset in assets
        if asset.skill_id != "_references"
    }
    for record in discover_canonical_skills(ROOT):
        if record.kind is not SkillSourceKind.CORE:
            continue
        for reference in record.spec.references:
            prefix = "artifact://skill-reference-"
            if not reference.uri.startswith(prefix):
                continue
            reference_id = reference.uri.removeprefix(prefix)
            expected[
                codex_root / record.spec.id / "references" / f"{reference_id}.md"
            ] = project_codex_skill_asset(shared[reference_id], plugin_context=True)
    return expected


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


def test_complete_canonical_skill_asset_inventory_and_modes() -> None:
    assets = discover_canonical_skill_assets(ROOT)
    direct = tuple(asset for asset in assets if asset.skill_id != "_references")
    shared = tuple(asset for asset in assets if asset.skill_id == "_references")

    assert len(assets) == 543
    assert len(direct) == 538
    assert len(shared) == 5
    assert {asset.relative_path.as_posix() for asset in shared} == {
        "accessibility-checklist.md",
        "orchestration-patterns.md",
        "performance-checklist.md",
        "security-checklist.md",
        "testing-patterns.md",
    }
    assert all(not asset.executable for asset in assets)
    assert {asset.mode for asset in assets} == {0o644}
    assert all(
        stat.S_IMODE(asset.canonical_path.stat().st_mode) == 0o644 for asset in assets
    )


def test_orchestration_source_is_neutral_and_appendices_are_provider_owned() -> None:
    assets = discover_canonical_skill_assets(ROOT)
    orchestration = next(
        asset
        for asset in assets
        if asset.destination == Path("skills/_references/orchestration-patterns.md")
    )
    known_skill_ids = frozenset(
        record.spec.id for record in discover_canonical_skills(ROOT)
    )

    assert (
        provider_leakage(orchestration.content, known_skill_ids=known_skill_ids) == ()
    )
    assert (
        orchestration.content.count("{{provider_appendix:orchestration-patterns}}") == 1
    )
    assert "CLAUDE.md" not in orchestration.content
    assert "AGENTS.md" not in orchestration.content
    assert ".claude" not in orchestration.content.lower()
    assert ".codex" not in orchestration.content.lower()
    assert "{{ref:artifact://project-instructions}}" in orchestration.content

    generator = _generator()
    claude = generator.render_claude_skill_asset(orchestration)
    codex = project_codex_skill_asset(orchestration, plugin_context=True)

    assert "## Claude Code host appendix" in claude
    assert "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1" in claude
    assert "permissionMode" in claude
    assert ".claude/agents/" in claude
    assert "CLAUDE.md" in claude
    assert "## Codex host appendix" in codex
    assert ".agents/skills/" in codex
    assert ".codex/agents/" in codex
    assert "AGENTS.md" in codex
    assert "Claude Code host appendix" not in codex
    assert "{{provider_appendix:" not in claude
    assert "{{provider_appendix:" not in codex


def test_shared_skill_reference_loader_rejects_either_host_wire_syntax(
    tmp_path: Path,
) -> None:
    root = tmp_path / "payload"
    shutil.copytree(ROOT / "canonical", root / "canonical")
    shutil.copytree(ROOT / "schemas", root / "schemas")
    orchestration = (
        root
        / "canonical"
        / "skills"
        / "assets"
        / "_references"
        / "orchestration-patterns.md"
    )

    for leaked in ("Read `.claude/rules/evals.md`.", "Read `.codex/config.toml`."):
        original = orchestration.read_text(encoding="utf-8")
        orchestration.write_text(original + "\n" + leaked + "\n", encoding="utf-8")
        with pytest.raises(CanonicalSkillError, match="contains provider syntax"):
            discover_canonical_skill_assets(root)
        orchestration.write_text(original, encoding="utf-8")


def test_canonical_skill_asset_destinations_reject_casefold_collisions() -> None:
    source = discover_canonical_skill_assets(ROOT)[0]
    records = (
        replace(source, relative_path=Path("references/Guide.md")),
        replace(source, relative_path=Path("REFERENCES/guide.MD")),
    )

    with pytest.raises(CanonicalSkillError, match="duplicate destination"):
        _ensure_unique_skill_asset_destinations(records)


def test_canonical_skill_assets_ignore_only_interpreter_bytecode_cache(
    tmp_path: Path,
) -> None:
    root = tmp_path / "payload"
    shutil.copytree(ROOT / "canonical", root / "canonical")
    shutil.copytree(ROOT / "schemas", root / "schemas")
    cache = (
        root
        / "canonical"
        / "skills"
        / "assets"
        / "zap-vapt-scanning"
        / "scripts"
        / "__pycache__"
    )
    cache.mkdir()
    (cache / "zap_vapt.cpython-314.pyc").write_bytes(b"interpreter-cache")

    records = discover_canonical_skill_assets(root)

    assert len(records) == 543
    assert all("__pycache__" not in record.canonical_path.parts for record in records)

    (cache / "unexpected.txt").write_text("not interpreter cache\n", encoding="utf-8")
    with pytest.raises(CanonicalSkillError, match="unexpected file"):
        discover_canonical_skill_assets(root)


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

    known_skill_ids = frozenset(record.spec.id for record in skills)
    for record in (*skills, *commands):
        text = record.canonical_path.read_text(encoding="utf-8")
        assert not provider_leakage(text, known_skill_ids=known_skill_ids), (
            record.canonical_path
        )
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


def test_semantic_skill_invocations_project_natively_for_each_host() -> None:
    generator = _generator()
    records = {record.spec.id: record for record in discover_canonical_skills(ROOT)}

    claude_sprint = generator.render_claude_skill(records["sprint"])
    codex_sprint = generator.render_codex_skill(records["sprint"])

    assert "/scope" in claude_sprint
    assert "/archive-sprint" in claude_sprint
    assert "$scope" in codex_sprint
    assert "$archive-sprint" in codex_sprint
    assert "{{skill_invocation:" not in claude_sprint
    assert "{{skill_invocation:" not in codex_sprint


def test_shannon_external_cli_names_project_exactly_for_both_hosts() -> None:
    names = {
        "CLAUDE_CODE_MAX_OUTPUT_TOKENS",
        "CLAUDE_CODE_USE_BEDROCK",
        "CLAUDE_CODE_USE_VERTEX",
        "CLAUDE_ADAPTIVE_THINKING",
    }
    records = {record.spec.id: record for record in discover_canonical_skills(ROOT)}
    shannon = records["shannon-ai-pentest"]
    generator = _generator()

    canonical_skill = shannon.canonical_path.read_text(encoding="utf-8")
    claude_skill = generator.render_claude_skill(shannon)
    codex_skill = generator.render_codex_skill(shannon, plugin_context=True)
    guide = next(
        asset
        for asset in discover_canonical_skill_assets(ROOT)
        if asset.destination
        == Path("skills/shannon-ai-pentest/references/operating-guide.md")
    )
    canonical_guide = guide.content
    claude_guide = generator.render_claude_skill_asset(guide)
    codex_guide = project_codex_skill_asset(guide, plugin_context=True)

    assert "{{host_env:code-" not in canonical_skill
    assert all(name not in canonical_skill for name in names)
    assert all(name not in canonical_guide for name in names)
    assert canonical_skill.count("{{external_literal:external-shannon-cli-") == 4
    assert canonical_guide.count("{{external_literal:external-shannon-cli-") == 4
    for projected in (claude_skill, codex_skill, claude_guide, codex_guide):
        assert names <= set(re.findall(r"\bCLAUDE(?:_CODE)?_[A-Z0-9_]+\b", projected))
        assert "<host-env:code-" not in projected

    skill_path = ".agents/skills/shannon-ai-pentest/SKILL.md"
    guide_path = ".agents/skills/shannon-ai-pentest/references/operating-guide.md"
    assert "CLAUDE_CODE_" not in codex_provider_leakage_scan_text(
        codex_skill, location=skill_path
    )
    assert "CLAUDE_CODE_" not in codex_provider_leakage_scan_text(
        codex_guide, location=guide_path
    )
    assert "CLAUDE_CODE_UNREVIEWED" in codex_provider_leakage_scan_text(
        codex_guide + "\nCLAUDE_CODE_UNREVIEWED=1\n", location=guide_path
    )
    assert "CLAUDE_CODE_USE_BEDROCK" in codex_provider_leakage_scan_text(
        codex_guide, location=".agents/skills/other/SKILL.md"
    )


def test_codex_skill_projection_marks_unselected_references_unavailable() -> None:
    records = {record.spec.id: record for record in discover_canonical_skills(ROOT)}
    selected_inventory = {
        "agent": frozenset(),
        "skill": frozenset({"sprint"}),
        "rule": frozenset({"continuity"}),
    }

    projection = project_codex_skill(
        records["sprint"], selected_inventory=selected_inventory
    )

    assert (
        "the optional `scope` skill (not installed for this selection; do not invoke)"
        in projection.instructions
    )
    assert (
        "the optional `archive-sprint` skill "
        "(not installed for this selection; do not invoke)" in projection.instructions
    )
    assert ".agents/skills/scope" not in projection.instructions
    assert "$scope" not in projection.instructions
    assert (
        "the optional `quality-gates` engineering rule "
        "(not installed for this selection; do not rely on it)"
        in projection.instructions
    )
    assert codex_reference_target(
        "agent",
        "security-reviewer",
        skill_reference_base=None,
        plugin_context=False,
        selected_inventory=selected_inventory,
    ) == (
        "the optional `security-reviewer` role "
        "(not installed for this selection; do not dispatch)"
    )

    selected_inventory["skill"] = frozenset({"archive-sprint", "scope", "sprint"})
    selected_inventory["rule"] = frozenset(
        {"agent-resilience", "continuity", "quality-gates"}
    )
    selected = project_codex_skill(
        records["sprint"], selected_inventory=selected_inventory
    )
    assert "$scope" in selected.instructions
    assert "$archive-sprint" in selected.instructions
    assert "not installed for this selection" not in selected.instructions


def test_codex_command_references_follow_the_selected_skill_inventory() -> None:
    records = {record.spec.id: record for record in discover_canonical_skills(ROOT)}
    inventory = {
        "agent": frozenset(),
        "skill": frozenset({"object-oriented-design"}),
        "rule": frozenset(),
    }

    unavailable = project_codex_skill(
        records["object-oriented-design"], selected_inventory=inventory
    ).instructions
    assert (
        "the optional `sdlc` skill "
        "(not installed for this selection; do not invoke)" in unavailable
    )
    assert "$sdlc" not in unavailable

    inventory["skill"] = frozenset({"object-oriented-design", "sdlc"})
    available = project_codex_skill(
        records["object-oriented-design"], selected_inventory=inventory
    ).instructions
    assert "$sdlc" in available
    assert "not installed for this selection" not in available
    assert (
        codex_reference_target(
            "command",
            "status",
            skill_reference_base=None,
            plugin_context=False,
            selected_inventory=inventory,
        )
        == "`ckit status`"
    )


def test_codex_reference_projection_preserves_one_markdown_code_span() -> None:
    selected_inventory = {
        "agent": frozenset(),
        "skill": frozenset({"scope"}),
        "rule": frozenset({"quality-gates"}),
    }
    source = (
        "Use `rule://quality-gates`, `skill://scope --short`, "
        "`skill://shipping-and-launch --check`, and `command://abort`."
    )

    projected = project_codex_reference_tokens(
        source,
        lambda kind, component_id: codex_reference_target(
            kind,
            component_id,
            skill_reference_base=None,
            plugin_context=False,
            selected_inventory=selected_inventory,
        ),
    )

    assert "`.ckit/rules/quality-gates.md`" in projected
    assert "`.agents/skills/scope/SKILL.md --short`" in projected
    assert (
        "the optional `shipping-and-launch` skill "
        "(not installed for this selection; do not invoke) --check" in projected
    )
    assert "`ckit abort`" in projected
    assert "`the optional `" not in projected
    assert "``ckit abort``" not in projected


def test_raw_skill_invocation_detector_is_precise() -> None:
    known = frozenset({"scope", "review-ux-flow"})

    assert raw_skill_invocations("Run /scope. Then /review-ux-flow now.", known) == (
        "/scope",
        "/review-ux-flow",
    )
    assert (
        raw_skill_invocations(
            "Read docs/planning/example/scope.md and https://example.test/scope.", known
        )
        == ()
    )
    assert raw_skill_invocations("GET /scope returns 200.", known) == ()
    assert raw_skill_invocations("Run /unknown-route now.", known) == ()
    assert provider_leakage("Use the Grafana Explore view and explore results.") == ()
    assert provider_leakage("Dispatch the Explore agent.") == ("Explore agent",)
    assert provider_leakage("Use `Explore` for discovery.") == ("`Explore`",)


def test_generator_is_current_and_owns_every_skill_command_payload() -> None:
    generator = _generator()
    assert generator.check(ROOT) == []
    outputs = generator.generated_payloads(ROOT)
    codex_plugin_root = ROOT / generator.CODEX_PLUGIN_ROOT
    legacy_outputs = {
        path for path in outputs if not path.is_relative_to(codex_plugin_root)
    }
    assert len(legacy_outputs) == 682  # 139 skills/commands + 543 assets

    codex_root = codex_plugin_root / "skills"
    codex_skills = sorted(codex_root.glob("*/SKILL.md"))
    codex_sidecars = sorted(codex_root.glob("*/agents/openai.yaml"))
    codex_references = sorted(codex_root.glob("*/references/*.md"))
    assert len(codex_skills) == 126  # 122 public skills + four command adapters
    assert len(codex_sidecars) == 20  # 16 explicit skills + four adapters
    assert len(codex_references) == 537  # 527 direct + ten projected shared refs
    assert not (codex_root / "_references").exists()
    assert not {
        record.spec.id
        for record in discover_canonical_skills(ROOT)
        if record.kind is SkillSourceKind.ORG
    } & {path.parent.name for path in codex_skills}

    known_skill_ids = frozenset(
        record.spec.id for record in discover_canonical_skills(ROOT)
    )
    for skill_path in codex_skills:
        metadata, body = _frontmatter(skill_path.read_text(encoding="utf-8"))
        assert set(metadata) == {"name", "description"}
        assert metadata["name"] == skill_path.parent.name
        assert "disable-model-invocation" not in metadata
        assert "allowed-tools" not in metadata
        assert "$ARGUMENTS" not in body
        assert "AskUserQuestion" not in body
        assert ".claude/" not in body.lower()
        assert raw_skill_invocations(body, known_skill_ids) == (), skill_path
        assert "`the optional `" not in body, skill_path
        assert "`the installed `" not in body, skill_path
        assert not re.search(
            r"``(?:ckit |\$[a-z0-9]|\.(?:ckit|agents|codex)/)", body
        ), skill_path

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
        assert declared_references <= installed_references
        rendered = (skill_root / "SKILL.md").read_text(encoding="utf-8")
        for reference_id in declared_references:
            assert f"references/{reference_id}.md" in rendered

    orchestration = (
        codex_root
        / "doubt-driven-development"
        / "references"
        / "orchestration-patterns.md"
    ).read_text(encoding="utf-8")
    assert "## Codex host appendix" in orchestration
    assert "Claude Code compatibility" not in orchestration
    assert ".claude/" not in orchestration.lower()

    remember = (codex_root / "remember" / "SKILL.md").read_text(encoding="utf-8")
    assert "/remember" not in remember
    assert "$remember" not in remember
    assert "explicit use of this skill remains available" in remember

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


def test_static_codex_plugin_contains_exact_projected_auxiliary_assets() -> None:
    generator = _generator()
    codex_root = ROOT / generator.CODEX_PLUGIN_ROOT / "skills"
    expected = _expected_codex_auxiliary_assets(codex_root)
    actual = {
        path
        for path in codex_root.rglob("*")
        if path.is_file()
        and path.name != "SKILL.md"
        and not (path.name == "openai.yaml" and path.parent.name == "agents")
    }

    assert len(expected) == 548  # 538 direct assets + ten shared projections
    assert actual == set(expected)
    for path, content in expected.items():
        assert path.read_text(encoding="utf-8") == content, path
        assert stat.S_IMODE(path.stat().st_mode) == 0o644, path

    generated_modes = generator.generated_asset_modes(ROOT)
    assert len(generated_modes) == 1091  # 543 Claude + 548 Codex assets
    assert set(generated_modes.values()) == {0o644}
    for path, mode in generated_modes.items():
        assert mode == 0o644
        assert stat.S_IMODE(path.stat().st_mode) == 0o644, path


def test_static_codex_plugin_assets_have_closed_links_and_no_source_host_wire() -> None:
    generator = _generator()
    codex_root = ROOT / generator.CODEX_PLUGIN_ROOT / "skills"
    expected_assets = _expected_codex_auxiliary_assets(codex_root)
    operational_documents = {
        *codex_root.glob("*/SKILL.md"),
        *(path for path in expected_assets if path.suffix.lower() == ".md"),
    }

    for source in sorted(operational_documents):
        text = source.read_text(encoding="utf-8")
        scanned = codex_provider_leakage_scan_text(
            text, location=source.relative_to(ROOT).as_posix()
        )
        assert _SOURCE_HOST_WIRE_RE.search(scanned) is None, source
        assert "`the optional `" not in text, source
        assert "`the installed `" not in text, source
        assert not re.search(
            r"``(?:ckit |\$[a-z0-9]|\.(?:ckit|agents|codex)/)", text
        ), source
        for target in _local_markdown_targets(source, codex_root):
            assert target.exists(), f"{source.relative_to(ROOT)} -> {target}"


def test_idea_refine_asset_marker_projects_to_bundled_host_paths() -> None:
    records = {record.spec.id: record for record in discover_canonical_skills(ROOT)}
    canonical = records["idea-refine"].canonical_path.read_text(encoding="utf-8")
    generator = _generator()
    claude = generator.render_claude_skill(records["idea-refine"])
    codex = generator.render_codex_skill(records["idea-refine"], plugin_context=True)
    codex_script = (
        ROOT
        / generator.CODEX_PLUGIN_ROOT
        / "skills"
        / "idea-refine"
        / "scripts"
        / "idea-refine.sh"
    )

    assert "{{skill_asset:skill://idea-refine/scripts/idea-refine.sh}}" in canonical
    assert "bash .claude/skills/idea-refine/scripts/idea-refine.sh" in claude
    assert "bash scripts/idea-refine.sh" in codex
    assert "{{skill_asset:" not in claude
    assert "{{skill_asset:" not in codex
    assert "/mnt/" not in canonical
    assert "/mnt/" not in claude
    assert "/mnt/" not in codex
    assert codex_script.is_file()


def test_excluded_skill_readme_supplements_are_not_operational_dependencies() -> None:
    skills_root = ROOT / "skills"
    supplements = set(skills_root.glob("*/README.md"))
    assert len(supplements) == 63

    operational_documents = {
        path
        for path in skills_root.glob("*/**/*")
        if path.is_file() and path.name != "README.md" and path.suffix.lower() == ".md"
    }
    linked_supplements = {
        target
        for source in operational_documents
        for target in _local_markdown_targets(source, skills_root)
        if target in supplements
    }
    assert linked_supplements == set()


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


def test_generator_reports_unmanaged_payload_and_exact_asset_mode_drift(
    tmp_path: Path,
) -> None:
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
    mode_drift = tmp_path / "skills/idea-refine/scripts/idea-refine.sh"
    mode_drift.chmod(0o664)

    diagnostics = generator.check(tmp_path)
    assert set(diagnostics) == {
        "stale generated asset mode: skills/idea-refine/scripts/idea-refine.sh",
        "unmanaged skill/command outside canonical source: skills/unmanaged/SKILL.md",
    }


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
