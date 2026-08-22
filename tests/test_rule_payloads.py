"""Canonical rule schema, selection, projection, and drift tests."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest
import yaml

from claude_kit import catalog
from claude_kit.canonical_rules import (
    CanonicalRuleError,
    RuleSourceKind,
    compile_codex_rule_layers,
    discover_canonical_rules,
    load_canonical_rule,
    project_codex_rule_text,
    provider_rule_leakage,
    selected_rule_layers,
    selected_rule_records,
)
from claude_kit.canonical_skills import discover_canonical_skills
from scripts.gen_rule_payloads import check as check_generated_rules
from tests._helpers import make_selection

_SYMBOLIC_REF = re.compile(
    r"\b(?:agent|skill|rule|command|hook|workflow|stage|handler|gate|state|artifact)://"
)


def _generated_frontmatter(path: Path) -> tuple[dict[str, object], str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}, text
    _, raw, body = text.split("---", 2)
    metadata = yaml.safe_load(raw)
    assert isinstance(metadata, dict)
    return metadata, body.lstrip("\n")


def _claude_glob(path_glob: str) -> str:
    prefixes = {
        "@agents/": ".claude/agents/",
        "@skills/": ".claude/skills/",
        "@memory/": ".claude/agent-memory/",
        "@runtime/": ".claude/",
    }
    for prefix, replacement in prefixes.items():
        if path_glob.startswith(prefix):
            return replacement + path_glob[len(prefix) :]
    return path_glob


def test_complete_rule_surface_is_canonical(payload: Path) -> None:
    records = discover_canonical_rules(payload)

    assert len(records) == 50
    assert Counter(record.kind for record in records) == {
        RuleSourceKind.CORE: 25,
        RuleSourceKind.STACK: 15,
        RuleSourceKind.ORG: 10,
    }
    assert len({record.spec.id for record in records}) == len(records)
    assert len({record.destination for record in records}) == len(records)


def test_every_canonical_rule_is_leak_free_and_has_exact_metadata(
    payload: Path,
) -> None:
    known_skill_ids = frozenset(
        record.spec.id for record in discover_canonical_skills(payload)
    )
    for record in discover_canonical_rules(payload):
        source = record.body_path.read_text(encoding="utf-8")
        assert provider_rule_leakage(source, known_skill_ids=known_skill_ids) == (), (
            record.body_path
        )
        assert record.spec.content == source.strip()
        assert all(
            not path_glob.startswith((".claude/", ".codex/"))
            for path_glob in record.spec.path_globs
        )
        assert {reference.uri for reference in record.spec.references} == set(
            re.findall(
                r"\b(?:agent|skill|rule|command|hook|workflow|stage|handler|gate|state|artifact)://[a-z0-9][a-z0-9._-]*",
                source,
            )
        )


def test_rule_leakage_detects_spaced_tool_sequences_without_flagging_prose() -> None:
    assert provider_rule_leakage("Use Read / Grep / Bash before acting.") == (
        "Read / Grep / Bash",
    )
    assert provider_rule_leakage("Use Read/Grep/Bash before acting.") == (
        "Read/Grep/Bash",
    )
    assert (
        provider_rule_leakage(
            "Read the file, search the codebase, then run a harmless shell command."
        )
        == ()
    )


def test_rule_leakage_detects_provider_worker_and_frontmatter_syntax_precisely() -> (
    None
):
    assert provider_rule_leakage("Dispatch the Explore agent.") == ("Explore agent",)
    assert provider_rule_leakage("Use `Explore` for discovery.") == ("`Explore`",)
    assert provider_rule_leakage("Set `model:` in agent frontmatter.") == ("`model:`",)
    assert (
        provider_rule_leakage(
            "Explore the Grafana Explore view with a semantic fast model tier."
        )
        == ()
    )


def test_generated_claude_rules_preserve_path_scopes(payload: Path) -> None:
    for record in discover_canonical_rules(payload):
        metadata, body = _generated_frontmatter(payload / record.destination)
        expected_paths = [_claude_glob(value) for value in record.spec.path_globs]
        if expected_paths:
            assert metadata == {"paths": expected_paths}, record.destination
        else:
            assert metadata == {}, record.destination
        assert body.strip()
        assert not _SYMBOLIC_REF.search(body), record.destination
        assert "{{ provider." not in body


def test_resolved_plan_binds_core_stack_and_org_rules(payload: Path) -> None:
    selection = make_selection(
        payload,
        profile="enterprise",
        scope="organization",
        org_packs=True,
        frontend_framework="react",
        backend_language="python",
        backend_framework="fastapi",
        database="postgres",
    )
    plan = catalog.resolve(payload, selection)
    selected = selected_rule_records(payload, plan)
    selected_ids = {record.spec.id for record in selected}
    core_ids = {
        record.spec.id
        for record in discover_canonical_rules(payload)
        if record.kind is RuleSourceKind.CORE
    }
    expected_selected = core_ids | {
        Path(filename).stem for filename in plan.overlay_rules
    }
    assert plan.org is not None
    expected_selected.update(Path(filename).stem for filename in plan.org.org_rules)

    assert selected_ids == expected_selected
    assert len(selected) == 46


def test_codex_rule_compiler_is_deterministic_truthful_and_bounded(
    payload: Path,
) -> None:
    plan = catalog.resolve(
        payload,
        make_selection(payload, profile="enterprise", scope="organization"),
    )
    layers = selected_rule_layers(payload, plan)
    first = compile_codex_rule_layers(layers, max_bytes=12_000)
    second = compile_codex_rule_layers(layers, max_bytes=12_000)

    assert first == second
    assert first.byte_size == len(first.markdown.encode("utf-8"))
    assert first.byte_size <= first.max_bytes == 12_000
    assert first.included_rule_ids
    assert first.omitted_rule_ids
    assert set(first.included_rule_ids) | set(first.omitted_rule_ids) == {
        layer.id for layer in layers
    }
    assert not set(first.included_rule_ids) & set(first.omitted_rule_ids)
    assert ".claude" not in first.markdown.lower()
    assert "Claude" not in first.markdown
    assert "{{ provider." not in first.markdown
    assert not _SYMBOLIC_REF.search(first.markdown)
    assert ".codex/agents/" in first.markdown or ".agents/skills/" in first.markdown

    for layer in layers:
        projected = project_codex_rule_text(layer.content)
        assert "{{ provider." not in projected, layer.id
        assert ".claude" not in projected.lower(), layer.id
        assert not _SYMBOLIC_REF.search(projected), layer.id


def test_rule_generator_is_clean_and_byte_deterministic(payload: Path) -> None:
    paths = [
        payload / record.destination for record in discover_canonical_rules(payload)
    ]
    before = {path: path.read_bytes() for path in paths}

    checked = subprocess.run(
        [sys.executable, "scripts/gen_rule_payloads.py", "--check"],
        cwd=payload,
        text=True,
        capture_output=True,
        check=False,
    )
    written = subprocess.run(
        [sys.executable, "scripts/gen_rule_payloads.py"],
        cwd=payload,
        text=True,
        capture_output=True,
        check=False,
    )

    assert checked.returncode == 0, checked.stderr
    assert written.returncode == 0, written.stderr
    assert before == {path: path.read_bytes() for path in paths}


def test_rule_generator_reports_stale_and_unmanaged(
    payload: Path, tmp_path: Path
) -> None:
    root = tmp_path / "payload"
    shutil.copytree(payload / "canonical/rules", root / "canonical/rules")
    (root / "schemas").mkdir(parents=True)
    shutil.copy2(payload / "schemas/canonical-rule.schema.json", root / "schemas")
    for record in discover_canonical_rules(payload):
        target = root / record.destination
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(payload / record.destination, target)
    assert check_generated_rules(root) == []

    (root / "rules/continuity.md").write_text("stale\n", encoding="utf-8")
    (root / "rules/unmanaged.md").write_text("unmanaged\n", encoding="utf-8")
    diagnostics = check_generated_rules(root)

    assert "stale generated rule: rules/continuity.md" in diagnostics
    assert "unmanaged rule outside canonical source: rules/unmanaged.md" in diagnostics


def test_canonical_rule_schema_rejects_unknown_fields(
    payload: Path, tmp_path: Path
) -> None:
    root = tmp_path / "payload"
    source_dir = root / "canonical/rules/core"
    source_dir.mkdir(parents=True)
    (root / "schemas").mkdir()
    shutil.copy2(payload / "schemas/canonical-rule.schema.json", root / "schemas")
    source = payload / "canonical/rules/core/continuity.md"
    metadata = payload / "canonical/rules/core/continuity.yaml"
    shutil.copy2(source, source_dir / source.name)
    raw = yaml.safe_load(metadata.read_text(encoding="utf-8"))
    raw["provider"] = "claude"
    (source_dir / metadata.name).write_text(
        yaml.safe_dump(raw, sort_keys=False), encoding="utf-8"
    )

    with pytest.raises(CanonicalRuleError, match="Additional properties"):
        load_canonical_rule(root, source_dir / source.name)
