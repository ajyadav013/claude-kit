"""Provider-neutral text-template inventory, leakage, and drift tests."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import yaml

from claude_kit.canonical_templates import (
    TEXT_TEMPLATE_INVENTORY,
    TemplateFormat,
    discover_canonical_templates,
    provider_template_leakage,
)

_SYMBOLIC_REF = re.compile(
    r"\b(?:agent|skill|rule|command|hook|workflow|stage|handler|gate|state|artifact)://"
)


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
    placeholders = set()
    for record in records:
        assert provider_template_leakage(record.content) == (), record.body_path
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
