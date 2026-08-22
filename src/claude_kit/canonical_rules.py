"""Strict loading and provider-neutral compilation for canonical rules.

Rule bodies and their applicability metadata deliberately live in separate files.
The body is portable prose; the YAML sidecar owns path globs, selection placement,
strength, and symbolic references.  Provider generators project those semantics to
host-specific rule files without making the catalog resolver provider-aware.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence

import jsonschema
import yaml

from claude_kit.components import RuleSpec, SymbolicRef
from claude_kit.models import ResolvedPlan

CANONICAL_RULE_SCHEMA_VERSION = 1
DEFAULT_CODEX_RULE_BUDGET = 32 * 1024
_SYMBOLIC_REF_RE = re.compile(
    r"\b(?:agent|skill|rule|command|hook|workflow|stage|handler|gate|state|artifact)"
    r"://[a-z0-9][a-z0-9._-]*"
)
_PROVIDER_PLACEHOLDER_RE = re.compile(
    r"\{\{\s*provider\.(?:path|executable|model|tool)\.[a-z0-9_.-]+\s*\}\}"
)
_PROVIDER_LEAKAGE = (
    re.compile(r"\b(?:Claude(?: Code)?|Codex)\b", re.IGNORECASE),
    re.compile(r"\b(?:sonnet|opus|haiku|gpt-[a-z0-9.-]+)\b", re.IGNORECASE),
    re.compile(r"\b(?:permissionMode|acceptEdits|bypassPermissions|dontAsk)\b"),
    re.compile(
        r"\b(?:AskUserQuestion|SendMessage|TaskCreate|TaskGet|TaskList|TaskUpdate|"
        r"spawn_agent|send_message|wait_agent|request_user_input)\b"
    ),
    re.compile(r"\bmcp__[a-zA-Z0-9_-]+\b"),
    re.compile(r"(?:^|[^a-zA-Z0-9_])\.(?:claude|codex)(?:/|\\|\b)", re.IGNORECASE),
    re.compile(r"\b(?:CLAUDE|CODEX)_[A-Z0-9_]+\b"),
    re.compile(r"\b(?:CLAUDE|AGENTS)\.md\b"),
    re.compile(r"(?<![\w./:-])/(?:claude-kit:[a-z-]+|sdlc\b)"),
    re.compile(r"`(?:Read|Write|Edit|Glob|Grep|Bash|Agent)`"),
)


class CanonicalRuleError(ValueError):
    """Raised when the canonical rule surface is ambiguous or invalid."""


class RuleSourceKind(str, Enum):
    """Selection layer that owns a rule."""

    CORE = "core"
    STACK = "stack"
    ORG = "org"


@dataclass(frozen=True)
class CanonicalRule:
    """One validated canonical rule and its compatibility placement."""

    spec: RuleSpec
    kind: RuleSourceKind
    body_path: Path
    metadata_path: Path
    stack_dir: Optional[str] = None

    @property
    def destination(self) -> Path:
        """Repository-relative Claude compatibility destination."""
        if self.kind is RuleSourceKind.CORE:
            return Path("rules") / f"{self.spec.id}.md"
        if self.kind is RuleSourceKind.ORG:
            return Path("templates/org/rules") / f"{self.spec.id}.md"
        if self.stack_dir is None:  # pragma: no cover - loader owns invariant
            raise CanonicalRuleError("stack rule is missing stack_dir")
        return (
            Path("templates/stacks") / self.stack_dir / "rules" / (f"{self.spec.id}.md")
        )


@dataclass(frozen=True)
class RuleLayer:
    """A selected full-fidelity body before an AGENTS size budget is applied."""

    id: str
    description: str
    content: str
    strength: str
    path_globs: tuple[str, ...]
    source: RuleSourceKind


@dataclass(frozen=True)
class CompiledRuleLayers:
    """Deterministic whole-rule projection bounded by ``max_bytes``."""

    markdown: str
    included_rule_ids: tuple[str, ...]
    omitted_rule_ids: tuple[str, ...]
    byte_size: int
    max_bytes: int


class _UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate keys."""


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
            raise CanonicalRuleError("canonical rule key must be scalar") from exc
        if exists:
            raise CanonicalRuleError(f"duplicate canonical rule key: {key!r}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def provider_rule_leakage(text: str) -> tuple[str, ...]:
    """Return host wire syntax present in provider-neutral rule prose."""
    return tuple(
        match.group(0)
        for pattern in _PROVIDER_LEAKAGE
        for match in pattern.finditer(text)
    )


def provider_placeholders(text: str) -> tuple[str, ...]:
    """Return explicit provider adapter placeholders in deterministic order."""
    return tuple(
        dict.fromkeys(
            match.group(0) for match in _PROVIDER_PLACEHOLDER_RE.finditer(text)
        )
    )


def _load_schema(payload_root: Path) -> dict[str, Any]:
    path = payload_root / "schemas" / "canonical-rule.schema.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CanonicalRuleError(
            f"cannot load canonical rule schema {path}: {exc}"
        ) from exc
    if not isinstance(raw, dict):
        raise CanonicalRuleError("canonical rule schema root must be an object")
    return raw


def _load_metadata(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
    except (OSError, yaml.YAMLError) as exc:
        raise CanonicalRuleError(
            f"cannot load canonical rule metadata {path}: {exc}"
        ) from exc
    if not isinstance(raw, dict):
        raise CanonicalRuleError(f"{path} metadata must be an object")
    return raw


def _validate_schema(
    raw: Mapping[str, Any], schema: Mapping[str, Any], path: Path
) -> None:
    validator_type = jsonschema.validators.validator_for(schema)
    try:
        validator_type.check_schema(schema)
    except jsonschema.SchemaError as exc:
        raise CanonicalRuleError(
            f"invalid canonical rule schema: {exc.message}"
        ) from exc
    errors = sorted(
        validator_type(schema).iter_errors(raw), key=lambda item: list(item.path)
    )
    if not errors:
        return
    details = []
    for error in errors:
        location = "/".join(str(part) for part in error.path) or "(root)"
        details.append(f"{location}: {error.message}")
    raise CanonicalRuleError(
        f"canonical rule schema validation failed for {path}: " + "; ".join(details)
    )


def _placement(
    rules_root: Path, body_path: Path
) -> tuple[RuleSourceKind, Optional[str]]:
    relative = body_path.relative_to(rules_root)
    parts = relative.parts
    if len(parts) == 2 and parts[0] == "core":
        return RuleSourceKind.CORE, None
    if len(parts) == 2 and parts[0] == "org":
        return RuleSourceKind.ORG, None
    if len(parts) >= 4 and parts[0] == "stacks":
        return RuleSourceKind.STACK, Path(*parts[1:-1]).as_posix()
    raise CanonicalRuleError(
        "canonical rule path must be core/<id>.md, org/<id>.md, or "
        f"stacks/<stack-dir>/<id>.md: {relative}"
    )


def load_canonical_rule(payload_root: Path, body_path: Path) -> CanonicalRule:
    """Load one Markdown body and its strict YAML applicability sidecar."""
    root = Path(payload_root)
    source = Path(body_path)
    metadata_path = source.with_suffix(".yaml")
    if not metadata_path.is_file():
        raise CanonicalRuleError(
            f"canonical rule {source} is missing {metadata_path.name}"
        )
    raw = _load_metadata(metadata_path)
    _validate_schema(raw, _load_schema(root), metadata_path)
    try:
        content = source.read_text(encoding="utf-8").strip() + "\n"
    except OSError as exc:
        raise CanonicalRuleError(f"cannot read canonical rule {source}: {exc}") from exc
    if not content.strip():
        raise CanonicalRuleError(f"canonical rule {source} body must not be empty")
    leakage = provider_rule_leakage(content)
    if leakage:
        raise CanonicalRuleError(
            f"canonical rule {source} contains provider syntax: "
            + ", ".join(sorted(set(leakage)))
        )
    kind, stack_dir = _placement(root / "canonical" / "rules", source)
    applicability = raw["applicability"]
    if applicability["source"] != kind.value:
        raise CanonicalRuleError(
            f"{metadata_path} applicability source does not match its {kind.value} path"
        )
    if kind is RuleSourceKind.STACK and applicability["stack_dir"] != stack_dir:
        raise CanonicalRuleError(
            f"{metadata_path} stack_dir does not match canonical placement {stack_dir!r}"
        )
    try:
        spec = RuleSpec(
            id=str(raw["id"]),
            description=str(raw["description"]),
            content=content,
            strength=str(raw["strength"]),  # type: ignore[arg-type]
            path_globs=tuple(str(value) for value in raw["path_globs"]),
            references=tuple(
                SymbolicRef.parse(str(value)) for value in raw["references"]
            ),
        )
    except ValueError as exc:
        raise CanonicalRuleError(f"invalid RuleSpec in {metadata_path}: {exc}") from exc
    if source.stem != spec.id:
        raise CanonicalRuleError(
            f"canonical filename {source.stem!r} does not match rule id {spec.id!r}"
        )
    if any(glob.startswith((".claude/", ".codex/")) for glob in spec.path_globs):
        raise CanonicalRuleError(
            f"{metadata_path} contains provider path globs; use @agents/@skills/@memory/@runtime"
        )
    refs_in_body = set(_SYMBOLIC_REF_RE.findall(spec.content))
    refs_in_metadata = {ref.uri for ref in spec.references}
    if refs_in_body != refs_in_metadata:
        missing = sorted(refs_in_body - refs_in_metadata)
        stale = sorted(refs_in_metadata - refs_in_body)
        raise CanonicalRuleError(
            f"{metadata_path} reference inventory differs from body "
            f"(missing={missing}, stale={stale})"
        )
    return CanonicalRule(
        spec=spec,
        kind=kind,
        body_path=source,
        metadata_path=metadata_path,
        stack_dir=stack_dir,
    )


def discover_canonical_rules(payload_root: Path) -> tuple[CanonicalRule, ...]:
    """Discover every canonical rule, rejecting orphans and duplicate logical ids."""
    root = Path(payload_root)
    rules_root = root / "canonical" / "rules"
    bodies = sorted(
        path for path in rules_root.glob("**/*.md") if path.name != "README.md"
    )
    metadata = sorted(rules_root.glob("**/*.yaml"))
    orphan_metadata = [
        path for path in metadata if not path.with_suffix(".md").is_file()
    ]
    if orphan_metadata:
        rendered = ", ".join(
            path.relative_to(root).as_posix() for path in orphan_metadata
        )
        raise CanonicalRuleError(f"orphan canonical rule metadata: {rendered}")
    records = tuple(load_canonical_rule(root, path) for path in bodies)
    seen: dict[str, Path] = {}
    for record in records:
        prior = seen.get(record.spec.id)
        if prior is not None:
            raise CanonicalRuleError(
                f"duplicate canonical rule id {record.spec.id!r}: {prior} and {record.body_path}"
            )
        seen[record.spec.id] = record.body_path
    return records


def selected_rule_records(
    payload_root: Path, plan: ResolvedPlan
) -> tuple[CanonicalRule, ...]:
    """Bind catalog-selected filenames to canonical records without provider branches."""
    records = discover_canonical_rules(payload_root)
    selected: list[CanonicalRule] = [
        record for record in records if record.kind is RuleSourceKind.CORE
    ]
    stack_dirs = {value for value in plan.stack_dirs.values() if value}
    stack_candidates = {
        record.destination.name: record
        for record in records
        if record.kind is RuleSourceKind.STACK and record.stack_dir in stack_dirs
    }
    for filename in plan.overlay_rules:
        try:
            selected.append(stack_candidates[Path(filename).name])
        except KeyError as exc:
            raise CanonicalRuleError(
                f"resolved overlay rule {filename!r} has no canonical definition in selected stacks"
            ) from exc
    org_candidates = {
        record.destination.name: record
        for record in records
        if record.kind is RuleSourceKind.ORG
    }
    for filename in plan.org.org_rules if plan.org is not None else ():
        try:
            selected.append(org_candidates[Path(filename).name])
        except KeyError as exc:
            raise CanonicalRuleError(
                f"resolved org rule {filename!r} has no canonical definition"
            ) from exc
    deduped: list[CanonicalRule] = []
    seen: set[str] = set()
    for record in selected:
        if record.spec.id not in seen:
            deduped.append(record)
            seen.add(record.spec.id)
    return tuple(deduped)


def selected_rule_layers(
    payload_root: Path, plan: ResolvedPlan
) -> tuple[RuleLayer, ...]:
    """Return full selected bodies for a provider adapter to layer as it chooses."""
    return tuple(
        RuleLayer(
            id=record.spec.id,
            description=record.spec.description,
            content=record.spec.content,
            strength=record.spec.strength.value,
            path_globs=record.spec.path_globs,
            source=record.kind,
        )
        for record in selected_rule_records(payload_root, plan)
    )


def project_codex_rule_text(text: str) -> str:
    """Resolve neutral rule references/placeholders to truthful Codex-layer prose.

    Logical rule references point at complete explicit projections under ``.ckit``.
    Codex does not auto-discover that directory: AGENTS names it as the fallback for
    selected whole-rule bodies that do not fit its bounded inline summary.
    """
    reference_targets: Mapping[str, Callable[[str], str]] = {
        "agent": lambda item: f".codex/agents/{item}.toml",
        "skill": lambda item: f".agents/skills/{item}/SKILL.md",
        "rule": lambda item: f"`.ckit/rules/{item}.md`",
        "command": lambda item: f"the `{item}` workflow entry point",
        "hook": lambda item: f"the `{item}` hook adapter",
        "workflow": lambda item: f"the `{item}` workflow",
        "stage": lambda item: f"the `{item}` workflow stage",
        "handler": lambda item: f"the `{item}` handler",
        "gate": lambda item: f"the `{item}` gate",
        "state": lambda item: {
            "continuity": ".ckit/CONTINUITY.md",
            "agent-memory": ".ckit/agent-memory",
            "workflow": ".ckit/state",
            "artifacts": ".ckit/artifacts",
            "configuration": ".ckit/config",
        }.get(item, f".ckit/state/{item}"),
        "artifact": lambda item: {
            "project-instructions": "AGENTS.md",
            "templates": ".ckit/templates",
            "agents-directory": ".codex/agents",
            "skills-directory": ".agents/skills",
            "rules-directory": "this AGENTS rule layer",
            "org-packs": ".ckit/org-packs",
            "sdlc-readme": ".ckit/README.sdlc.md",
        }.get(item, item),
    }

    def replace_reference(match: re.Match[str]) -> str:
        kind, item = match.group(1), match.group(2)
        return reference_targets[kind](item)

    projected = re.sub(
        r"\b(agent|skill|rule|command|hook|workflow|stage|handler|gate|state|artifact)"
        r"://([a-z0-9][a-z0-9._-]*)",
        replace_reference,
        text,
    )
    placeholders = {
        "{{ provider.path.config_root }}": ".ckit/",
        "{{ provider.path.continuity }}": ".ckit/CONTINUITY.md",
        "{{ provider.path.memory }}": ".ckit/agent-memory",
        "{{ provider.path.artifacts }}": ".ckit/artifacts",
        "{{ provider.path.state }}": ".ckit/state",
        "{{ provider.path.project_instructions }}": "AGENTS.md",
        "{{ provider.executable.cli }}": "ckit",
        "{{ provider.model.field }}": "model tier",
        "{{ provider.model.fast }}": "fast tier",
        "{{ provider.model.balanced }}": "balanced tier",
        "{{ provider.model.deep }}": "deep tier",
        "{{ provider.tool.user_input }}": "human-input capability",
        "{{ provider.tool.message }}": "worker-messaging capability",
        "{{ provider.tool.task_create }}": "task-ledger create operation",
        "{{ provider.tool.task_get }}": "task-ledger read operation",
        "{{ provider.tool.task_list }}": "task-ledger list operation",
        "{{ provider.tool.task_update }}": "task-ledger update operation",
        "{{ provider.tool.delegate }}": "delegation capability",
        "{{ provider.tool.read }}": "file-read capability",
        "{{ provider.tool.write }}": "file-write capability",
        "{{ provider.tool.edit }}": "file-edit capability",
        "{{ provider.tool.search_files }}": "file-search capability",
        "{{ provider.tool.search_text }}": "text-search capability",
        "{{ provider.tool.shell }}": "shell capability",
    }
    for placeholder, value in placeholders.items():
        projected = projected.replace(placeholder, value)
    return projected


def _codex_glob(path_glob: str) -> str:
    prefixes = {
        "@agents/": ".codex/agents/",
        "@skills/": ".agents/skills/",
        "@memory/": ".ckit/agent-memory/",
        "@runtime/": ".ckit/",
    }
    for prefix, replacement in prefixes.items():
        if path_glob.startswith(prefix):
            return replacement + path_glob[len(prefix) :]
    return path_glob


def render_codex_rule_layer(layer: RuleLayer) -> str:
    """Render one complete rule for AGENTS composition or explicit native loading."""
    applicability = "all project paths"
    if layer.path_globs:
        applicability = ", ".join(
            f"`{_codex_glob(path_glob)}`" for path_glob in layer.path_globs
        )
    return (
        f"## Rule: {layer.id}\n\n"
        f"Strength: {layer.strength}. Applies to: {applicability}.\n\n"
        f"{project_codex_rule_text(layer.content).strip()}\n"
    )


def _omission_footer(ids: Sequence[str]) -> str:
    if not ids:
        return ""
    return (
        "\n## Additional selected rules\n\n"
        "The following selected rules exceeded this instruction-file byte budget. Their complete "
        "projections remain under `.ckit/rules/<id>.md`; load the relevant file before acting: "
        + ", ".join(f"`{rule_id}`" for rule_id in ids)
        + ".\n"
    )


def compile_codex_rule_layers(
    layers: Iterable[RuleLayer], *, max_bytes: int = DEFAULT_CODEX_RULE_BUDGET
) -> CompiledRuleLayers:
    """Compile whole rule bodies into deterministic Markdown within ``max_bytes``.

    No body is cut mid-rule.  Selected rules that do not fit are named explicitly so
    a renderer can surface or project them separately instead of silently dropping policy.
    """
    if max_bytes < 512:
        raise ValueError("max_bytes must be at least 512")
    ordered = tuple(layers)
    intro = (
        "# Selected engineering rules\n\n"
        "These provider-neutral rules are selected by the resolved installation plan.\n"
    )
    included: list[RuleLayer] = []
    omitted: list[RuleLayer] = []
    for index, layer in enumerate(ordered):
        candidate_included = included + [layer]
        candidate_omitted = omitted + list(ordered[index + 1 :])
        candidate = (
            intro
            + "\n".join(render_codex_rule_layer(item) for item in candidate_included)
            + _omission_footer([item.id for item in candidate_omitted])
        )
        if len(candidate.encode("utf-8")) <= max_bytes:
            included.append(layer)
        else:
            omitted.append(layer)
    markdown = (
        intro
        + "\n".join(render_codex_rule_layer(item) for item in included)
        + _omission_footer([item.id for item in omitted])
    )
    encoded = markdown.encode("utf-8")
    if len(encoded) > max_bytes:
        # Only possible for an implausibly large omission inventory. Keep the contract
        # truthful and bounded rather than truncating a rule body.
        markdown = (
            intro + "\nSelected rule bodies are available only in native projections.\n"
        )
        included = []
        omitted = list(ordered)
        encoded = markdown.encode("utf-8")
    return CompiledRuleLayers(
        markdown=markdown,
        included_rule_ids=tuple(item.id for item in included),
        omitted_rule_ids=tuple(item.id for item in omitted),
        byte_size=len(encoded),
        max_bytes=max_bytes,
    )
