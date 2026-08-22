"""Provider-neutral text-template inventory, leakage, and drift tests."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import yaml

from claude_kit import catalog
from claude_kit.canonical_templates import (
    TEXT_TEMPLATE_INVENTORY,
    TemplateFormat,
    discover_canonical_templates,
    provider_template_leakage,
)
from claude_kit.models import InstallRequest, Runtime
from claude_kit.provider_renderers import CodexRenderer

_SYMBOLIC_REF = re.compile(
    r"\b(?:agent|skill|rule|command|hook|workflow|stage|handler|gate|state|artifact)://"
)
_COMPONENT_REF = re.compile(r"\b(agent|skill|rule|command)://([a-z0-9][a-z0-9._-]*)")
_SLASH_INVOCATION = re.compile(r"(?<![\w./:-])/([a-z][a-z0-9-]+)\b")


def test_complete_text_template_inventory_is_canonical(payload: Path) -> None:
    records = discover_canonical_templates(payload)

    assert len(records) == 29
    assert {record.destination.as_posix() for record in records} == set(
        TEXT_TEMPLATE_INVENTORY
    )
    assert len({record.id for record in records}) == len(records)
    assert not any(
        part in {"agents", "skills", "rules", "hooks", "scripts"}
        for record in records
        for part in record.destination.parts[1:-1]
    )
    assert "templates/settings.json" not in TEXT_TEMPLATE_INVENTORY
    assert "templates/scripts/sdlc-loop.sh" not in TEXT_TEMPLATE_INVENTORY


def test_canonical_templates_are_parameterized_and_leak_free(payload: Path) -> None:
    records = discover_canonical_templates(payload)
    known_skill_ids = frozenset(
        path.stem
        for path in (payload / "canonical/skills").rglob("*.md")
        if path.name != "README.md"
    )
    placeholders = set()
    for record in records:
        assert (
            provider_template_leakage(record.content, known_skill_ids=known_skill_ids)
            == ()
        ), record.body_path
        placeholders.update(record.provider_placeholders)
        assert {reference.uri for reference in record.references} == set(
            re.findall(
                r"\b(?:agent|skill|rule|command|hook|workflow|stage|handler|gate|state|artifact)://[a-z0-9][a-z0-9._-]*",
                record.content,
            )
        )
    assert {
        "provider.path.config_root",
        "provider.path.project_instructions",
        "provider.executable.cli",
        "provider.name.host",
        "provider.name.agent",
        "provider.environment.kit_prefix",
    } <= placeholders

    assert provider_template_leakage(
        "Run /scope now.", known_skill_ids=known_skill_ids
    ) == ("/scope",)
    assert (
        provider_template_leakage(
            "GET /scope returns 200; https://example.test/scope is public.",
            known_skill_ids=known_skill_ids,
        )
        == ()
    )
    assert (
        provider_template_leakage(
            "Run /unknown-route now.", known_skill_ids=known_skill_ids
        )
        == ()
    )
    assert provider_template_leakage("Dispatch the Explore agent.") == (
        "Explore agent",
    )


def test_canonical_template_component_references_and_invocations_exist(
    payload: Path,
) -> None:
    inventories = {
        "agent": {
            path.stem
            for path in (payload / "canonical/agents").rglob("*.md")
            if path.name != "README.md"
        },
        "skill": {
            path.stem
            for path in (payload / "canonical/skills").rglob("*.md")
            if path.name != "README.md"
        },
        "rule": {
            path.stem
            for path in (payload / "canonical/rules").rglob("*.md")
            if path.name != "README.md"
        },
        "command": {
            path.stem
            for path in (payload / "canonical/commands").rglob("*.md")
            if path.name != "README.md"
        },
    }
    # Canonical templates historically use command:// for directly invocable skills as well as
    # the four compatibility commands. Both must resolve to a real component.
    inventories["command"].update(inventories["skill"])

    for record in discover_canonical_templates(payload):
        for kind, component_id in _COMPONENT_REF.findall(record.content):
            assert component_id in inventories[kind], (
                record.body_path,
                kind,
                component_id,
            )
        for component_id in _SLASH_INVOCATION.findall(record.content):
            assert component_id in inventories["command"], (
                record.body_path,
                component_id,
            )


def test_canonical_org_pack_examples_use_semantic_skill_references(
    payload: Path,
) -> None:
    for record in discover_canonical_templates(payload):
        relative = record.body_path.relative_to(payload).as_posix()
        if not relative.startswith("canonical/templates/org/packs/"):
            continue
        assert _SLASH_INVOCATION.findall(record.content) == [], record.body_path


def test_generated_text_templates_resolve_adapter_tokens_and_parse(
    payload: Path,
) -> None:
    for record in discover_canonical_templates(payload):
        generated = payload / record.destination
        text = generated.read_text(encoding="utf-8")
        assert "{{ provider." not in text, generated
        assert not _SYMBOLIC_REF.search(text), generated
        if record.format is TemplateFormat.YAML:
            parsed = yaml.safe_load(text)
            assert isinstance(parsed, dict), generated
            assert parsed["id"]


def test_template_skill_invocations_render_natively_for_each_host(
    payload: Path,
) -> None:
    claude_engineering = (
        payload / "templates/org/packs/engineering-core/README.md"
    ).read_text(encoding="utf-8")
    claude_readme = (payload / "templates/README.claude-sdlc.md.tmpl").read_text(
        encoding="utf-8"
    )

    assert "Use `/code-simplification` to simplify" in claude_engineering
    assert "/code-simplification Simplify the billing service" in claude_readme
    assert "{{skill_invocation:" not in claude_engineering
    assert "{{skill_invocation:" not in claude_readme
    assert "Explore" not in claude_engineering

    selection = catalog.defaults(payload)
    selection.profile = "enterprise"
    selection.scope = "organization"
    selection.org_packs = True
    plan = catalog.resolve(payload, selection)
    files = CodexRenderer(payload).render(
        plan, InstallRequest(selection=selection, runtime=Runtime.CODEX)
    )
    paths = {item.path: item.text_content for item in files}
    codex_engineering = paths[".ckit/org-packs/engineering-core/README.md"]
    codex_readme = paths[".ckit/README.sdlc.md"]

    assert "Use `$code-simplification` to simplify" in codex_engineering
    assert "$code-simplification Simplify the billing service" in codex_readme
    assert "{{skill_invocation:" not in codex_engineering
    assert "{{skill_invocation:" not in codex_readme
    template_text = "\n".join(
        content
        for path, content in paths.items()
        if path == ".ckit/README.sdlc.md" or path.startswith(".ckit/org-packs/")
    )
    assert "Explore" not in template_text


def test_text_template_generator_is_clean_and_byte_deterministic(payload: Path) -> None:
    records = discover_canonical_templates(payload)
    paths = [payload / record.destination for record in records]
    before = {path: path.read_bytes() for path in paths}

    checked = subprocess.run(
        [sys.executable, "scripts/gen_template_payloads.py", "--check"],
        cwd=payload,
        text=True,
        capture_output=True,
        check=False,
    )
    written = subprocess.run(
        [sys.executable, "scripts/gen_template_payloads.py"],
        cwd=payload,
        text=True,
        capture_output=True,
        check=False,
    )

    assert checked.returncode == 0, checked.stderr
    assert written.returncode == 0, written.stderr
    assert before == {path: path.read_bytes() for path in paths}


def test_export_guide_does_not_assume_other_hosts_are_single_agent(
    payload: Path,
) -> None:
    record = next(
        item
        for item in discover_canonical_templates(payload)
        if item.id == "export-workflow-guide"
    )

    assert "destination host supports named delegation" in record.content
    assert (
        "Outside {{ provider.name.host }} you are a **single agent**"
        not in record.content
    )


def test_codex_org_pack_readmes_name_only_real_skill_invocations(
    payload: Path,
) -> None:
    selection = catalog.defaults(payload)
    selection.profile = "enterprise"
    selection.scope = "organization"
    selection.org_packs = True
    plan = catalog.resolve(payload, selection)
    files = CodexRenderer(payload).render(
        plan,
        InstallRequest(selection=selection, runtime=Runtime.CODEX),
    )
    readmes = "\n".join(
        item.text_content
        for item in files
        if item.path.startswith(".ckit/org-packs/") and item.path.endswith("/README.md")
    )

    invented_aliases = {
        "release-plan",
        "rollback-plan",
        "incident-runbook",
        "refactor-safely",
        "write-tests",
        "docs-update",
        "prd-to-stories",
        "review-pr",
        "security-review",
        "dependency-audit",
    }
    for alias in invented_aliases:
        assert not re.search(
            rf"(?<![a-z0-9-]){re.escape(alias)}(?![a-z0-9-])",
            readmes,
        )
    for skill_id in {
        "shipping-and-launch",
        "incident-postmortem",
        "code-simplification",
        "test-driven-development",
        "refresh-docs",
        "planning-and-task-breakdown",
        "code-review-and-quality",
        "security-and-hardening",
        "security-verification",
    }:
        assert f"${skill_id}" in readmes
    assert "skill://" not in readmes
    assert "command://" not in readmes
