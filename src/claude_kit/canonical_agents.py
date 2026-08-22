"""Typed loading for the provider-neutral canonical agent source tree.

Each Markdown source carries strict YAML frontmatter matching :class:`AgentSpec`
semantics and a provider-independent instruction body.  Provider adapters may
translate symbolic references and semantic capabilities, but selection remains
the responsibility of the existing branch-free catalog resolver.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Optional

import jsonschema
import yaml

from claude_kit.components import AgentSpec, SymbolicRef

CANONICAL_AGENT_SCHEMA_VERSION = 1
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")

# These patterns describe host wire syntax, not ordinary words such as "read"
# or "agent" that legitimately appear in portable instructions.
_PROVIDER_LEAKAGE = (
    re.compile(r"\b(?:Claude(?: Code)?|Codex)\b", re.IGNORECASE),
    re.compile(r"\b(?:sonnet|opus|haiku|gpt-[a-z0-9.-]+)\b", re.IGNORECASE),
    re.compile(r"\b(?:permissionMode|acceptEdits|bypassPermissions|dontAsk)\b"),
    re.compile(
        r"\b(?:AskUserQuestion|SendMessage|TaskCreate|TaskGet|TaskList|TaskUpdate|spawn_agent|send_message|wait_agent|request_user_input)\b"
    ),
    re.compile(r"\bmcp__[a-zA-Z0-9_-]+\b"),
    re.compile(r"(?:^|[^a-zA-Z0-9_])\.(?:claude|codex)(?:/|\\|\b)", re.IGNORECASE),
    re.compile(r"(?:^|[^a-zA-Z0-9_])\.agents(?:/|\\)skills(?:/|\\)", re.IGNORECASE),
    re.compile(r"\b(?:CLAUDE|AGENTS)\.md\b"),
    re.compile(r"\b(?:CLAUDE|CODEX)_[A-Z0-9_]+\b"),
    re.compile(r"(?<![\w./:-])/(?:claude-kit:[a-z-]+|sdlc\b)"),
    re.compile(r"`(?:Read|Write|Edit|Glob|Grep|Bash|Agent)`"),
    re.compile(
        r"\b(?:Read, Glob, Grep|Read/Glob/Grep|Glob/Grep|Grep/Bash|Write/Edit)\b"
    ),
    re.compile(r"\bAgent[- ]tool\b"),
    re.compile(r"(?<!state://)\bCONTINUITY\.md\b"),
    re.compile(r"(?<!state://)\bagent-memory/"),
    re.compile(r"\bSKILL\.md\b"),
    re.compile(r"://[a-z0-9._-]+://"),
)


class CanonicalAgentError(ValueError):
    """Raised when canonical source structure or semantics are invalid."""


class AgentSourceKind(str, Enum):
    """Placement class for a canonical agent definition."""

    CORE = "core"
    STACK = "stack"
    ORG = "org"


class WorkflowTier(str, Enum):
    """Portable orchestration role used by generated agent discovery metadata."""

    ORCHESTRATOR = "orchestrator"
    STAGE_LEAD = "stage-lead"
    REVIEW = "review"
    SPECIALIST = "specialist"


@dataclass(frozen=True)
class CanonicalAgent:
    """One validated canonical definition and its logical placement."""

    spec: AgentSpec
    workflow_tier: WorkflowTier
    kind: AgentSourceKind
    canonical_path: Path
    stack_dir: Optional[str] = None

    @property
    def destination(self) -> Path:
        """Return the repository-relative generated compatibility destination."""
        if self.kind is AgentSourceKind.CORE:
            return Path("agents") / f"{self.spec.id}.md"
        if self.kind is AgentSourceKind.ORG:
            return Path("templates/org/agents") / f"{self.spec.id}.md"
        if self.stack_dir is None:  # pragma: no cover - constructor owns invariant
            raise CanonicalAgentError("stack agent is missing stack_dir")
        return (
            Path("templates/stacks") / self.stack_dir / "agents" / f"{self.spec.id}.md"
        )


class _UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects ambiguous duplicate keys."""


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
            raise CanonicalAgentError("canonical agent key must be scalar") from exc
        if exists:
            raise CanonicalAgentError(f"duplicate canonical agent key: {key!r}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _read_frontmatter(path: Path) -> tuple[dict[str, Any], str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CanonicalAgentError(f"cannot read canonical agent {path}: {exc}") from exc
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise CanonicalAgentError(f"{path} is missing YAML frontmatter")
    end = next(
        (
            index
            for index, line in enumerate(lines[1:], start=1)
            if line.strip() == "---"
        ),
        None,
    )
    if end is None:
        raise CanonicalAgentError(f"{path} has unterminated YAML frontmatter")
    try:
        raw = yaml.load("".join(lines[1:end]), Loader=_UniqueKeyLoader)
    except yaml.YAMLError as exc:
        raise CanonicalAgentError(
            f"invalid canonical agent YAML in {path}: {exc}"
        ) from exc
    if not isinstance(raw, dict):
        raise CanonicalAgentError(f"{path} frontmatter must be an object")
    body = "".join(lines[end + 1 :]).strip()
    if not body:
        raise CanonicalAgentError(f"{path} instruction body must not be empty")
    return raw, body + "\n"


def _load_schema(payload_root: Path) -> dict[str, Any]:
    path = payload_root / "schemas" / "canonical-agent.schema.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CanonicalAgentError(
            f"cannot load canonical agent schema {path}: {exc}"
        ) from exc
    if not isinstance(raw, dict):
        raise CanonicalAgentError("canonical agent schema root must be an object")
    return raw


def _validate_schema(
    raw: Mapping[str, Any], schema: Mapping[str, Any], path: Path
) -> None:
    validator_type = jsonschema.validators.validator_for(schema)
    try:
        validator_type.check_schema(schema)
    except jsonschema.SchemaError as exc:
        raise CanonicalAgentError(
            f"invalid canonical agent schema: {exc.message}"
        ) from exc
    errors = sorted(
        validator_type(schema).iter_errors(raw), key=lambda item: list(item.path)
    )
    if not errors:
        return
    rendered = []
    for error in errors:
        location = "/".join(str(part) for part in error.path) or "(root)"
        rendered.append(f"{location}: {error.message}")
    raise CanonicalAgentError(
        f"canonical agent schema validation failed for {path}: " + "; ".join(rendered)
    )


def provider_leakage(text: str) -> tuple[str, ...]:
    """Return provider-specific wire syntax found in canonical text."""
    return tuple(
        match.group(0)
        for pattern in _PROVIDER_LEAKAGE
        for match in pattern.finditer(text)
    )


def _placement(root: Path, path: Path) -> tuple[AgentSourceKind, Optional[str]]:
    relative = path.relative_to(root / "canonical" / "agents")
    parts = relative.parts
    if len(parts) == 2 and parts[0] == "core":
        return AgentSourceKind.CORE, None
    if len(parts) == 2 and parts[0] == "org":
        return AgentSourceKind.ORG, None
    if len(parts) >= 4 and parts[0] == "stacks":
        return AgentSourceKind.STACK, Path(*parts[1:-1]).as_posix()
    raise CanonicalAgentError(
        f"canonical agent path must be core/<id>.md, org/<id>.md, or "
        f"stacks/<stack-dir>/<id>.md: {relative}"
    )


def load_canonical_agent(payload_root: Path, path: Path) -> CanonicalAgent:
    """Load and validate one canonical Markdown agent definition."""
    root = Path(payload_root)
    source = Path(path)
    raw, body = _read_frontmatter(source)
    _validate_schema(raw, _load_schema(root), source)
    leakage = provider_leakage(source.read_text(encoding="utf-8"))
    if leakage:
        raise CanonicalAgentError(
            f"canonical agent {source} contains provider syntax: "
            + ", ".join(sorted(set(leakage)))
        )
    try:
        spec = AgentSpec(
            id=str(raw["id"]),
            description=str(raw["description"]),
            instructions=body,
            model_tier=str(raw["model_tier"]),  # type: ignore[arg-type]
            permission=str(raw["permission"]),  # type: ignore[arg-type]
            capabilities=frozenset(raw["capabilities"]),  # type: ignore[arg-type]
            write_scope=tuple(str(value) for value in raw["write_scope"]),
            isolation=str(raw["isolation"]),  # type: ignore[arg-type]
            nested_delegation=str(raw["nested_delegation"]),  # type: ignore[arg-type]
            required_skills=tuple(
                SymbolicRef.parse(str(value)) for value in raw["required_skills"]
            ),
            references=tuple(
                SymbolicRef.parse(str(value)) for value in raw["references"]
            ),
        )
        workflow_tier = WorkflowTier(str(raw["workflow_tier"]))
    except ValueError as exc:
        raise CanonicalAgentError(f"invalid AgentSpec in {source}: {exc}") from exc
    if source.stem != spec.id:
        raise CanonicalAgentError(
            f"canonical filename {source.stem!r} does not match agent id {spec.id!r}"
        )
    instruction_refs = set(
        re.findall(
            r"\b(?:agent|skill|rule|command|hook|workflow|stage|handler|gate|state|artifact)://[a-z0-9][a-z0-9._-]*",
            spec.instructions,
        )
    )
    declared_refs = {reference.uri for reference in spec.references}
    required_refs = {reference.uri for reference in spec.required_skills}
    expected_refs = instruction_refs | required_refs
    if declared_refs != expected_refs:
        missing = ", ".join(sorted(expected_refs - declared_refs)) or "none"
        extra = ", ".join(sorted(declared_refs - expected_refs)) or "none"
        raise CanonicalAgentError(
            f"canonical references in {source} do not match instructions "
            f"(missing: {missing}; extra: {extra})"
        )
    kind, stack_dir = _placement(root, source)
    return CanonicalAgent(
        spec=spec,
        workflow_tier=workflow_tier,
        kind=kind,
        canonical_path=source,
        stack_dir=stack_dir,
    )


def discover_canonical_agents(payload_root: Path) -> tuple[CanonicalAgent, ...]:
    """Return every canonical agent in deterministic destination order."""
    root = Path(payload_root)
    source_root = root / "canonical" / "agents"
    if not source_root.is_dir():
        raise CanonicalAgentError(f"canonical agent root does not exist: {source_root}")
    records = tuple(
        load_canonical_agent(root, path)
        for path in sorted(source_root.rglob("*.md"))
        if path.name != "README.md"
    )
    destinations = [record.destination.as_posix() for record in records]
    if len(set(destinations)) != len(destinations):
        raise CanonicalAgentError("canonical agents resolve to duplicate destinations")
    return tuple(sorted(records, key=lambda record: record.destination.as_posix()))


def find_canonical_agent(
    payload_root: Path,
    agent_id: str,
    *,
    kind: AgentSourceKind,
    stack_dir: Optional[str] = None,
) -> CanonicalAgent:
    """Resolve one selected logical agent without consulting the selection catalog."""
    if not _ID_RE.fullmatch(agent_id) or ".." in agent_id:
        raise CanonicalAgentError(f"invalid canonical agent id {agent_id!r}")
    root = Path(payload_root)
    if kind is AgentSourceKind.CORE:
        path = root / "canonical" / "agents" / "core" / f"{agent_id}.md"
    elif kind is AgentSourceKind.ORG:
        path = root / "canonical" / "agents" / "org" / f"{agent_id}.md"
    else:
        if stack_dir is None:
            raise CanonicalAgentError("stack agent lookup requires stack_dir")
        stack = Path(stack_dir)
        if stack.is_absolute() or ".." in stack.parts:
            raise CanonicalAgentError(f"invalid stack_dir {stack_dir!r}")
        path = root / "canonical" / "agents" / "stacks" / stack / f"{agent_id}.md"
    return load_canonical_agent(root, path)


__all__ = [
    "CANONICAL_AGENT_SCHEMA_VERSION",
    "AgentSourceKind",
    "CanonicalAgent",
    "CanonicalAgentError",
    "WorkflowTier",
    "discover_canonical_agents",
    "find_canonical_agent",
    "load_canonical_agent",
    "provider_leakage",
]
