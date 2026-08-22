"""Strict loading for provider-neutral canonical skills and commands.

The Markdown bodies describe behavior once.  Provider adapters translate only
semantic markers (for example ``{{request}}`` and ``rule://quality-gates``) and
host discovery metadata.  No provider path, tool spelling, model name, or
permission wire syntax is valid in this source tree.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

import jsonschema
import yaml

from claude_kit.components import Capability, CommandSpec, SkillSpec, SymbolicRef

CANONICAL_SKILL_SCHEMA_VERSION = 1
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_REFERENCE_RE = re.compile(
    r"\b(?:agent|skill|rule|command|hook|workflow|stage|handler|gate|state|artifact)"
    r"://[a-z0-9][a-z0-9._-]*"
)
_PAUSE_RE = re.compile(r"\{\{pause_for_human:([a-z0-9][a-z0-9._-]*)\}\}")

# Match host wire syntax, not ordinary prose such as "read the file" or a
# domain concept such as an Anthropic API.  Explicit external-provider examples
# are represented by named semantic literals during migration.
_PROVIDER_LEAKAGE = (
    re.compile(r"\b(?:Claude(?: Code)?|Codex)\b", re.IGNORECASE),
    re.compile(r"\b(?:sonnet|opus|haiku|gpt-[a-z0-9.-]+)\b", re.IGNORECASE),
    re.compile(r"\b(?:permissionMode|acceptEdits|bypassPermissions|dontAsk)\b"),
    re.compile(r"--approval-mode(?:=|\s+)[a-z-]+\b"),
    re.compile(r"\ballowed-tools\s*:"),
    re.compile(r"\bAskUserQuestion\b"),
    re.compile(r"\$(?:ARGUMENTS|ARGUMENTS\[[0-9]+\])\b"),
    re.compile(r"(?:^|[^a-zA-Z0-9_])\.(?:claude|codex)(?:/|\\|\b)", re.I),
    re.compile(r"(?:^|[^a-zA-Z0-9_])\.agents(?:/|\\)skills(?:/|\\)", re.I),
    re.compile(r"\b(?:CLAUDE|CODEX)_[A-Z0-9_]+\b"),
    re.compile(r"\b(?:CLAUDE|AGENTS)\.md\b"),
    re.compile(r"`(?:Read|Write|Edit|Glob|Grep|Bash|Agent|Skill)`"),
    re.compile(r"\b(?:Read, Glob, Grep|Read/Glob/Grep|Glob/Grep|Grep/Bash)\b"),
    re.compile(r"\b(?:Agent|Skill)[- ]tool\b"),
    re.compile(r"\b(?:TaskCreate|TaskGet|TaskList|TaskUpdate|SendMessage)\b"),
    re.compile(r"\bmcp__[a-zA-Z0-9_-]+\b"),
    re.compile(r"(?<![\w./:-])/(?:claude-kit:[a-z-]+|sdlc\b)"),
)


class CanonicalSkillError(ValueError):
    """Raised when canonical skill or command source is invalid."""


class SkillSourceKind(str, Enum):
    """Placement class for a canonical skill."""

    CORE = "core"
    ORG = "org"


class RequestMode(str, Enum):
    """Whether an invocation accepts a caller-supplied request."""

    NONE = "none"
    OPTIONAL = "optional"
    REQUIRED = "required"


@dataclass(frozen=True)
class RequestInput:
    """Provider-independent invocation input contract."""

    mode: RequestMode
    hint: str = ""

    def __post_init__(self) -> None:
        try:
            mode = (
                self.mode
                if isinstance(self.mode, RequestMode)
                else RequestMode(self.mode)
            )
        except ValueError as exc:
            raise CanonicalSkillError(
                f"invalid request input mode: {self.mode!r}"
            ) from exc
        hint = self.hint.strip()
        if mode is RequestMode.NONE and hint:
            raise CanonicalSkillError("request input mode none must not declare a hint")
        if mode is not RequestMode.NONE and not hint:
            raise CanonicalSkillError(
                "request input accepting values must declare a hint"
            )
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "hint", hint)


@dataclass(frozen=True)
class PausePoint:
    """A deliberate interaction point which a provider adapter must surface."""

    id: str
    reason: str

    def __post_init__(self) -> None:
        if not _ID_RE.fullmatch(self.id) or ".." in self.id:
            raise CanonicalSkillError(f"invalid pause id: {self.id!r}")
        if not self.reason.strip():
            raise CanonicalSkillError("pause reason must not be empty")
        object.__setattr__(self, "reason", self.reason.strip())


@dataclass(frozen=True)
class CanonicalSkill:
    """One validated reusable skill and its generated legacy placement."""

    spec: SkillSpec
    request_input: RequestInput
    pause_for_human: tuple[PausePoint, ...]
    kind: SkillSourceKind
    canonical_path: Path

    @property
    def destination(self) -> Path:
        if self.kind is SkillSourceKind.CORE:
            return Path("skills") / self.spec.id / "SKILL.md"
        return Path("templates/org/skills") / self.spec.id / "SKILL.md"


@dataclass(frozen=True)
class CanonicalCommand:
    """One explicitly invoked workflow plus its stable aliases."""

    spec: CommandSpec
    aliases: tuple[str, ...]
    request_input: RequestInput
    pause_for_human: tuple[PausePoint, ...]
    canonical_path: Path

    @property
    def destination(self) -> Path:
        return Path("commands") / f"{self.spec.id}.md"

    @property
    def adapter_skill_id(self) -> str:
        return f"ckit-command-{self.spec.id}"


class _UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys."""


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
            raise CanonicalSkillError("canonical key must be scalar") from exc
        if exists:
            raise CanonicalSkillError(f"duplicate canonical key: {key!r}")
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
        raise CanonicalSkillError(
            f"cannot read canonical source {path}: {exc}"
        ) from exc
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise CanonicalSkillError(f"{path} is missing YAML frontmatter")
    end = next(
        (
            index
            for index, line in enumerate(lines[1:], start=1)
            if line.strip() == "---"
        ),
        None,
    )
    if end is None:
        raise CanonicalSkillError(f"{path} has unterminated YAML frontmatter")
    try:
        raw = yaml.load("".join(lines[1:end]), Loader=_UniqueKeyLoader)
    except yaml.YAMLError as exc:
        raise CanonicalSkillError(f"invalid canonical YAML in {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise CanonicalSkillError(f"{path} frontmatter must be an object")
    body = "".join(lines[end + 1 :]).strip()
    if not body:
        raise CanonicalSkillError(f"{path} instruction body must not be empty")
    return raw, body + "\n"


def _load_schema(payload_root: Path, filename: str) -> dict[str, Any]:
    path = payload_root / "schemas" / filename
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CanonicalSkillError(
            f"cannot load canonical schema {path}: {exc}"
        ) from exc
    if not isinstance(raw, dict):
        raise CanonicalSkillError(f"canonical schema {path} must be an object")
    return raw


def _validate_schema(
    raw: Mapping[str, Any], schema: Mapping[str, Any], path: Path
) -> None:
    validator_type = jsonschema.validators.validator_for(schema)
    try:
        validator_type.check_schema(schema)
    except jsonschema.SchemaError as exc:
        raise CanonicalSkillError(f"invalid canonical schema: {exc.message}") from exc
    errors = sorted(
        validator_type(schema).iter_errors(raw), key=lambda item: list(item.path)
    )
    if not errors:
        return
    details = []
    for error in errors:
        location = "/".join(str(part) for part in error.path) or "(root)"
        details.append(f"{location}: {error.message}")
    raise CanonicalSkillError(
        f"canonical schema validation failed for {path}: " + "; ".join(details)
    )


def provider_leakage(text: str) -> tuple[str, ...]:
    """Return provider-specific wire syntax found in canonical text."""
    return tuple(
        match.group(0)
        for pattern in _PROVIDER_LEAKAGE
        for match in pattern.finditer(text)
    )


def _request_input(raw: Mapping[str, Any]) -> RequestInput:
    value = raw["request_input"]
    if not isinstance(value, Mapping):  # schema should catch; keeps typing honest
        raise CanonicalSkillError("request_input must be an object")
    return RequestInput(
        mode=RequestMode(str(value["mode"])),
        hint=str(value.get("hint", "")),
    )


def _pauses(raw: Mapping[str, Any]) -> tuple[PausePoint, ...]:
    pauses = tuple(
        PausePoint(id=str(value["id"]), reason=str(value["reason"]))
        for value in raw["pause_for_human"]
    )
    ids = [pause.id for pause in pauses]
    if len(ids) != len(set(ids)):
        raise CanonicalSkillError("pause_for_human ids must not contain duplicates")
    return pauses


def _references(raw: Mapping[str, Any]) -> tuple[SymbolicRef, ...]:
    return tuple(SymbolicRef.parse(str(value)) for value in raw["references"])


def _validate_semantics(
    *,
    source: Path,
    description: str,
    body: str,
    request_input: RequestInput,
    pauses: tuple[PausePoint, ...],
    capabilities: frozenset[Capability],
    references: tuple[SymbolicRef, ...],
) -> None:
    found_pauses = set(_PAUSE_RE.findall(body))
    declared_pauses = {pause.id for pause in pauses}
    if found_pauses != declared_pauses:
        raise CanonicalSkillError(
            f"pause markers in {source} do not match pause_for_human metadata"
        )
    if declared_pauses and Capability.USER_INPUT not in capabilities:
        raise CanonicalSkillError(
            f"pause_for_human in {source} requires the human.input capability"
        )
    if "{{request}}" in body and request_input.mode is RequestMode.NONE:
        raise CanonicalSkillError(
            f"request marker in {source} requires optional or required request_input"
        )
    instruction_refs = set(_REFERENCE_RE.findall(description + "\n" + body))
    declared_refs = {reference.uri for reference in references}
    if instruction_refs != declared_refs:
        missing = ", ".join(sorted(instruction_refs - declared_refs)) or "none"
        extra = ", ".join(sorted(declared_refs - instruction_refs)) or "none"
        raise CanonicalSkillError(
            f"canonical references in {source} do not match instructions "
            f"(missing: {missing}; extra: {extra})"
        )


def load_canonical_skill(payload_root: Path, path: Path) -> CanonicalSkill:
    """Load and validate one canonical skill Markdown source."""
    root = Path(payload_root)
    source = Path(path)
    raw, body = _read_frontmatter(source)
    _validate_schema(raw, _load_schema(root, "canonical-skill.schema.json"), source)
    leakage = provider_leakage(source.read_text(encoding="utf-8"))
    if leakage:
        raise CanonicalSkillError(
            f"canonical skill {source} contains provider syntax: "
            + ", ".join(sorted(set(leakage)))
        )
    try:
        references = _references(raw)
        capabilities = frozenset(
            Capability(str(value)) for value in raw["capabilities"]
        )
        spec = SkillSpec(
            id=str(raw["id"]),
            description=str(raw["description"]),
            instructions=body,
            invocation=str(raw["invocation"]),  # type: ignore[arg-type]
            capabilities=capabilities,
            references=references,
        )
        request_input = _request_input(raw)
        pauses = _pauses(raw)
    except (KeyError, TypeError, ValueError) as exc:
        raise CanonicalSkillError(f"invalid SkillSpec in {source}: {exc}") from exc
    if source.stem != spec.id:
        raise CanonicalSkillError(
            f"canonical filename {source.stem!r} does not match skill id {spec.id!r}"
        )
    relative = source.relative_to(root / "canonical" / "skills")
    if len(relative.parts) != 2 or relative.parts[0] not in {"core", "org"}:
        raise CanonicalSkillError(
            f"canonical skill path must be core/<id>.md or org/<id>.md: {relative}"
        )
    _validate_semantics(
        source=source,
        description=spec.description,
        body=body,
        request_input=request_input,
        pauses=pauses,
        capabilities=capabilities,
        references=references,
    )
    return CanonicalSkill(
        spec=spec,
        request_input=request_input,
        pause_for_human=pauses,
        kind=SkillSourceKind(relative.parts[0]),
        canonical_path=source,
    )


def load_canonical_command(payload_root: Path, path: Path) -> CanonicalCommand:
    """Load and validate one canonical command Markdown source."""
    root = Path(payload_root)
    source = Path(path)
    raw, body = _read_frontmatter(source)
    _validate_schema(raw, _load_schema(root, "canonical-command.schema.json"), source)
    leakage = provider_leakage(source.read_text(encoding="utf-8"))
    if leakage:
        raise CanonicalSkillError(
            f"canonical command {source} contains provider syntax: "
            + ", ".join(sorted(set(leakage)))
        )
    try:
        references = _references(raw)
        capabilities = frozenset(
            Capability(str(value)) for value in raw["capabilities"]
        )
        request_input = _request_input(raw)
        spec = CommandSpec(
            id=str(raw["id"]),
            description=str(raw["description"]),
            instructions=body,
            arguments=request_input.hint,
            invocation=str(raw["invocation"]),  # type: ignore[arg-type]
            capabilities=capabilities,
            references=references,
        )
        aliases = tuple(str(value) for value in raw["aliases"])
        pauses = _pauses(raw)
    except (KeyError, TypeError, ValueError) as exc:
        raise CanonicalSkillError(f"invalid CommandSpec in {source}: {exc}") from exc
    if source.stem != spec.id:
        raise CanonicalSkillError(
            f"canonical filename {source.stem!r} does not match command id {spec.id!r}"
        )
    if spec.id not in aliases:
        raise CanonicalSkillError(
            f"canonical command {source} must retain its id as an alias"
        )
    _validate_semantics(
        source=source,
        description=spec.description,
        body=body,
        request_input=request_input,
        pauses=pauses,
        capabilities=capabilities,
        references=references,
    )
    return CanonicalCommand(
        spec=spec,
        aliases=aliases,
        request_input=request_input,
        pause_for_human=pauses,
        canonical_path=source,
    )


def discover_canonical_skills(payload_root: Path) -> tuple[CanonicalSkill, ...]:
    """Return all canonical skills in deterministic generated-path order."""
    root = Path(payload_root)
    source_root = root / "canonical" / "skills"
    if not source_root.is_dir():
        raise CanonicalSkillError(f"canonical skill root does not exist: {source_root}")
    records = tuple(
        load_canonical_skill(root, path)
        for path in sorted(source_root.glob("*/*.md"))
        if path.name != "README.md"
    )
    destinations = [record.destination.as_posix() for record in records]
    if len(destinations) != len(set(destinations)):
        raise CanonicalSkillError("canonical skills resolve to duplicate destinations")
    return tuple(sorted(records, key=lambda record: record.destination.as_posix()))


def discover_canonical_commands(payload_root: Path) -> tuple[CanonicalCommand, ...]:
    """Return all canonical commands in deterministic alias order."""
    root = Path(payload_root)
    source_root = root / "canonical" / "commands"
    if not source_root.is_dir():
        raise CanonicalSkillError(
            f"canonical command root does not exist: {source_root}"
        )
    records = tuple(
        load_canonical_command(root, path)
        for path in sorted(source_root.glob("*.md"))
        if path.name != "README.md"
    )
    aliases = [alias for record in records for alias in record.aliases]
    if len(aliases) != len(set(aliases)):
        raise CanonicalSkillError("canonical commands declare duplicate aliases")
    return tuple(sorted(records, key=lambda record: record.spec.id))


__all__ = [
    "CANONICAL_SKILL_SCHEMA_VERSION",
    "CanonicalCommand",
    "CanonicalSkill",
    "CanonicalSkillError",
    "PausePoint",
    "RequestInput",
    "RequestMode",
    "SkillSourceKind",
    "discover_canonical_commands",
    "discover_canonical_skills",
    "load_canonical_command",
    "load_canonical_skill",
    "provider_leakage",
]
