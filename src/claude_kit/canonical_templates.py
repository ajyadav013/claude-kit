"""Strict inventory and loading for provider-parameterized text templates."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

import jsonschema
import yaml

from claude_kit.canonical_skills import raw_skill_invocations
from claude_kit.components import SymbolicRef

CANONICAL_TEMPLATE_SCHEMA_VERSION = 1
_REF_RE = re.compile(
    r"\b(?:agent|skill|rule|command|hook|workflow|stage|handler|gate|state|artifact)"
    r"://[a-z0-9][a-z0-9._-]*"
)
_PLACEHOLDER_RE = re.compile(
    r"\{\{\s*(provider\.(?:path|executable|model|tool|name|environment)\.[a-z0-9_.-]+)\s*\}\}"
)
_LEAKAGE = (
    re.compile(r"\b(?:Claude(?: Code)?|Codex)\b", re.IGNORECASE),
    re.compile(r"\b(?:sonnet|opus|haiku|gpt-[a-z0-9.-]+)\b", re.IGNORECASE),
    re.compile(
        r"\b(?:AskUserQuestion|SendMessage|TaskCreate|TaskGet|TaskList|TaskUpdate)\b"
    ),
    re.compile(r"(?:^|[^a-zA-Z0-9_])\.(?:claude|codex)(?:/|\\|\b)", re.IGNORECASE),
    re.compile(r"\b(?:CLAUDE|CODEX)_[A-Z0-9_]+\b"),
    re.compile(r"\b(?:CLAUDE|AGENTS)\.md\b"),
    re.compile(r"(?<![\w./:-])/(?:claude-kit:[a-z-]+|sdlc\b)"),
    re.compile(r"(?:\bExplore agent\b|`Explore`|\*\*Explore\*\*)"),
)

# This is intentionally closed: settings/hooks/scripts and agent/skill/rule files are
# owned by other canonical payload lanes and must never be claimed by this generator.
TEXT_TEMPLATE_INVENTORY = frozenset(
    {
        "templates/CLAUDE.md",
        "templates/CLAUDE.stack.md.tmpl",
        "templates/CONTINUITY.template.md",
        "templates/README.claude-sdlc.md.tmpl",
        "templates/agent-memory/MEMORY.md",
        "templates/artifacts/adr.md",
        "templates/artifacts/api-change-report.md",
        "templates/artifacts/change-proposal.md",
        "templates/artifacts/feature-spec.md",
        "templates/artifacts/release-plan.md",
        "templates/artifacts/runbook.md",
        "templates/artifacts/security-review.md",
        "templates/artifacts/test-plan.md",
        "templates/export/sdlc-workflow-guide.md.tmpl",
        "templates/org/README.md",
        "templates/org/packs/devops-and-release/README.md",
        "templates/org/packs/devops-and-release/pack.yaml",
        "templates/org/packs/engineering-core/README.md",
        "templates/org/packs/engineering-core/pack.yaml",
        "templates/org/packs/non-engineer-builder/README.md",
        "templates/org/packs/non-engineer-builder/pack.yaml",
        "templates/org/packs/onboarding-and-docs/README.md",
        "templates/org/packs/onboarding-and-docs/pack.yaml",
        "templates/org/packs/product-to-code/README.md",
        "templates/org/packs/product-to-code/pack.yaml",
        "templates/org/packs/quality-and-review/README.md",
        "templates/org/packs/quality-and-review/pack.yaml",
        "templates/org/packs/security-and-compliance/README.md",
        "templates/org/packs/security-and-compliance/pack.yaml",
    }
)


class CanonicalTemplateError(ValueError):
    """Raised when canonical template metadata, content, or inventory is invalid."""


class TemplateCategory(str, Enum):
    PROJECT = "project"
    STACK = "stack"
    CONTINUITY = "continuity"
    MEMORY = "memory"
    ARTIFACT = "artifact"
    README = "readme"
    ORG = "org"


class TemplateFormat(str, Enum):
    MARKDOWN = "markdown"
    JINJA_MARKDOWN = "jinja-markdown"
    YAML = "yaml"


@dataclass(frozen=True)
class CanonicalTemplate:
    """One provider-neutral text body and its physical compatibility destination."""

    id: str
    description: str
    category: TemplateCategory
    format: TemplateFormat
    destination: Path
    content: str
    provider_placeholders: tuple[str, ...]
    references: tuple[SymbolicRef, ...]
    body_path: Path
    metadata_path: Path


class _UniqueKeyLoader(yaml.SafeLoader):
    """YAML loader rejecting ambiguous duplicate keys."""


def _construct_unique_mapping(
    loader: _UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False
) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            exists = key in mapping
        except TypeError as exc:
            raise CanonicalTemplateError(
                "canonical template key must be scalar"
            ) from exc
        if exists:
            raise CanonicalTemplateError(f"duplicate canonical template key: {key!r}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def provider_template_leakage(
    text: str,
    *,
    known_skill_ids: tuple[str, ...] | frozenset[str] = (),
) -> tuple[str, ...]:
    """Return provider-specific syntax found in a canonical template body."""
    provider_matches = tuple(
        match.group(0) for pattern in _LEAKAGE for match in pattern.finditer(text)
    )
    return provider_matches + raw_skill_invocations(text, known_skill_ids)


def _load_schema(root: Path) -> dict[str, Any]:
    path = root / "schemas/canonical-template.schema.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CanonicalTemplateError(
            f"cannot load canonical template schema {path}: {exc}"
        ) from exc
    if not isinstance(raw, dict):
        raise CanonicalTemplateError("canonical template schema root must be an object")
    return raw


def _load_metadata(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
    except (OSError, yaml.YAMLError) as exc:
        raise CanonicalTemplateError(
            f"cannot load canonical template metadata {path}: {exc}"
        ) from exc
    if not isinstance(raw, dict):
        raise CanonicalTemplateError(f"{path} metadata must be an object")
    return raw


def _validate_schema(
    raw: Mapping[str, Any], schema: Mapping[str, Any], path: Path
) -> None:
    validator_type = jsonschema.validators.validator_for(schema)
    validator_type.check_schema(schema)
    errors = sorted(
        validator_type(schema).iter_errors(raw), key=lambda item: list(item.path)
    )
    if not errors:
        return
    details = []
    for error in errors:
        location = "/".join(str(part) for part in error.path) or "(root)"
        details.append(f"{location}: {error.message}")
    raise CanonicalTemplateError(
        f"canonical template schema validation failed for {path}: " + "; ".join(details)
    )


def load_canonical_template(root: Path, body_path: Path) -> CanonicalTemplate:
    """Load one body and sidecar, including exact adapter-token inventories."""
    payload_root = Path(root)
    source = Path(body_path)
    metadata_path = source.with_name(source.name + ".meta.yaml")
    if not metadata_path.is_file():
        raise CanonicalTemplateError(
            f"canonical template {source} is missing its YAML sidecar"
        )
    raw = _load_metadata(metadata_path)
    _validate_schema(raw, _load_schema(payload_root), metadata_path)
    try:
        content = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise CanonicalTemplateError(
            f"cannot read canonical template {source}: {exc}"
        ) from exc
    if not content.strip():
        raise CanonicalTemplateError(
            f"canonical template {source} body must not be empty"
        )
    known_skill_ids = frozenset(
        candidate.stem
        for candidate in (payload_root / "canonical" / "skills").glob("*/*.md")
        if candidate.name != "README.md"
    )
    leakage = provider_template_leakage(content, known_skill_ids=known_skill_ids)
    if leakage:
        raise CanonicalTemplateError(
            f"canonical template {source} contains provider syntax: "
            + ", ".join(sorted(set(leakage)))
        )
    destination = Path(str(raw["destination"]))
    if destination.as_posix() not in TEXT_TEMPLATE_INVENTORY:
        raise CanonicalTemplateError(
            f"{metadata_path} destination is not in the closed text-template inventory: {destination}"
        )
    placeholders = tuple(
        dict.fromkeys(match.group(1) for match in _PLACEHOLDER_RE.finditer(content))
    )
    expected_placeholders = tuple(str(value) for value in raw["provider_placeholders"])
    if set(placeholders) != set(expected_placeholders):
        raise CanonicalTemplateError(
            f"{metadata_path} provider placeholder inventory differs from body"
        )
    body_refs = set(_REF_RE.findall(content))
    metadata_refs = {str(value) for value in raw["references"]}
    if body_refs != metadata_refs:
        raise CanonicalTemplateError(
            f"{metadata_path} symbolic reference inventory differs from body"
        )
    try:
        references = tuple(SymbolicRef.parse(value) for value in sorted(metadata_refs))
        category = TemplateCategory(str(raw["category"]))
        template_format = TemplateFormat(str(raw["format"]))
    except ValueError as exc:
        raise CanonicalTemplateError(
            f"invalid canonical template semantics in {metadata_path}: {exc}"
        ) from exc
    return CanonicalTemplate(
        id=str(raw["id"]),
        description=str(raw["description"]),
        category=category,
        format=template_format,
        destination=destination,
        content=content,
        provider_placeholders=tuple(sorted(placeholders)),
        references=references,
        body_path=source,
        metadata_path=metadata_path,
    )


def discover_canonical_templates(root: Path) -> tuple[CanonicalTemplate, ...]:
    """Load the complete closed template inventory in destination order."""
    payload_root = Path(root)
    source_root = payload_root / "canonical/templates"
    bodies = sorted(
        path
        for path in source_root.glob("**/*")
        if path.is_file()
        and not path.name.endswith(".meta.yaml")
        and path.name != "README.md"
    )
    metadata = sorted(source_root.glob("**/*.meta.yaml"))
    orphan_metadata = [
        path for path in metadata if not path.with_name(path.name[:-10]).is_file()
    ]
    if orphan_metadata:
        raise CanonicalTemplateError("orphan canonical template metadata exists")
    records = tuple(load_canonical_template(payload_root, path) for path in bodies)
    destinations = [record.destination.as_posix() for record in records]
    if len(destinations) != len(set(destinations)):
        raise CanonicalTemplateError(
            "canonical templates resolve to duplicate destinations"
        )
    missing = sorted(TEXT_TEMPLATE_INVENTORY - set(destinations))
    extra = sorted(set(destinations) - TEXT_TEMPLATE_INVENTORY)
    if missing or extra:
        raise CanonicalTemplateError(
            f"canonical template inventory mismatch (missing={missing}, extra={extra})"
        )
    return tuple(sorted(records, key=lambda record: record.destination.as_posix()))
