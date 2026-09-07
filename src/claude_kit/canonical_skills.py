"""Strict loading for provider-neutral canonical skills and commands.

The Markdown bodies describe behavior once.  Provider adapters translate only
semantic markers (for example ``{{request}}`` and ``rule://quality-gates``) and
host discovery metadata.  No provider path, tool spelling, model name, or
permission wire syntax is valid in this source tree.
"""

from __future__ import annotations

import hashlib
import json
import re
import stat
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

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
_SKILL_ASSET_RE = re.compile(
    r"\{\{skill_asset:skill://([a-z0-9][a-z0-9._-]*)/"
    r"([a-zA-Z0-9][a-zA-Z0-9._/-]*)\}\}"
)
_CROSS_SKILL_LINK_RE = re.compile(
    r"\[([^\]\n]+)\]\(\.\./([a-z0-9][a-z0-9._-]*)"
    r"(?:/SKILL\.md|/)?(?:#[^)\s]+)?\)"
)
_INLINE_CODE_SPAN_RE = re.compile(r"(?<!`)`(?!`)([^`\n]+)(?<!`)`(?!`)")
_CODEX_COMPONENT_ID_PATTERN = r"[a-z0-9](?:[a-z0-9._-]*[a-z0-9_-])?"
_CODEX_SYMBOLIC_REFERENCE_RE = re.compile(
    r"\b(agent|skill|rule|command|hook|workflow|stage|handler|gate|state|artifact)"
    rf"://({_CODEX_COMPONENT_ID_PATTERN})"
)

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
    re.compile(r"(?:\bExplore agent\b|`Explore`)"),
)


class CanonicalSkillError(ValueError):
    """Raised when canonical skill or command source is invalid."""


_SourceFingerprint = tuple[tuple[str, int, int, int, int, int, int, str], ...]


def _source_tree_fingerprint(
    paths: Iterable[Path], *, boundary: Path
) -> _SourceFingerprint:
    """Return a cheap cache key that changes with source bytes or topology."""
    records: list[tuple[str, int, int, int, int, int, int, str]] = []
    for path in paths:
        try:
            metadata = path.lstat()
        except OSError as exc:
            raise CanonicalSkillError(
                f"cannot inspect canonical source {path}: {exc}"
            ) from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise CanonicalSkillError(f"canonical source must not be a symlink: {path}")
        if stat.S_ISREG(metadata.st_mode):
            try:
                content_digest = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError as exc:
                raise CanonicalSkillError(
                    f"cannot read canonical source {path}: {exc}"
                ) from exc
        elif stat.S_ISDIR(metadata.st_mode):
            content_digest = ""
        else:
            raise CanonicalSkillError(
                f"canonical source must be a regular file or directory: {path}"
            )
        records.append(
            (
                path.relative_to(boundary).as_posix(),
                metadata.st_mode,
                metadata.st_size,
                metadata.st_mtime_ns,
                metadata.st_ctime_ns,
                metadata.st_dev,
                metadata.st_ino,
                content_digest,
            )
        )
    return tuple(records)


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
class CanonicalSkillAsset:
    """One provider-neutral support file owned by a canonical skill."""

    skill_id: str
    relative_path: Path
    canonical_path: Path
    content: str
    mode: int

    @property
    def executable(self) -> bool:
        """Whether the canonical file carries any executable bit."""
        return bool(self.mode & 0o111)

    @property
    def destination(self) -> Path:
        """Claude compatibility destination generated from this source."""
        return Path("skills") / self.skill_id / self.relative_path


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


def raw_skill_invocations(
    text: str, known_skill_ids: tuple[str, ...] | frozenset[str]
) -> tuple[str, ...]:
    """Return raw slash invocations for known portable skills."""
    ids = tuple(sorted(set(known_skill_ids), key=len, reverse=True))
    if not ids:
        return ()
    names = "|".join(re.escape(component_id) for component_id in ids)
    pattern = re.compile(
        rf"(?<![\w./:-])/({names})(?=$|[\s`),:;!?\]}}]|\.(?![a-zA-Z0-9]))"
    )
    invocations: list[str] = []
    for match in pattern.finditer(text):
        line_start = text.rfind("\n", 0, match.start()) + 1
        prefix = text[line_start : match.start()]
        if re.search(
            r"\b(?:GET|POST|PUT|PATCH|DELETE|OPTIONS|HEAD)\s+`?$",
            prefix,
            flags=re.IGNORECASE,
        ):
            continue
        invocations.append(match.group(0))
    return tuple(invocations)


def provider_leakage(
    text: str,
    *,
    known_skill_ids: tuple[str, ...] | frozenset[str] = (),
) -> tuple[str, ...]:
    """Return provider-specific wire syntax found in canonical text."""
    provider_matches = tuple(
        match.group(0)
        for pattern in _PROVIDER_LEAKAGE
        for match in pattern.finditer(text)
    )
    return provider_matches + raw_skill_invocations(text, known_skill_ids)


def _codex_target_is_bare(target: str) -> bool:
    """Whether a resolved target is one native token/path rather than prose."""
    return bool(target) and "`" not in target and re.search(r"\s", target) is None


def project_codex_inline_tokens(
    text: str,
    pattern: re.Pattern[str],
    resolve: Callable[[re.Match[str]], str],
) -> str:
    """Project semantic tokens without creating nested Markdown code spans.

    Canonical prose commonly wraps a semantic token plus arguments in one code
    span. A selected native token/path keeps that single span. If any resolved
    target is descriptive prose or already contains its own code span, the
    canonical outer span is removed and only other bare targets are formatted.
    Tokens outside inline code are then projected normally.
    """

    def project_span(span: re.Match[str]) -> str:
        content = span.group(1)
        matches = tuple(pattern.finditer(content))
        if not matches:
            return span.group(0)
        targets = tuple(resolve(match).strip() for match in matches)
        plain_context = any(not _codex_target_is_bare(target) for target in targets)
        parts: list[str] = []
        cursor = 0
        for match, target in zip(matches, targets):
            parts.append(content[cursor : match.start()])
            if plain_context and _codex_target_is_bare(target):
                parts.append(f"`{target}`")
            else:
                parts.append(target)
            cursor = match.end()
        parts.append(content[cursor:])
        projected = "".join(parts)
        return projected if plain_context else f"`{projected}`"

    projected = _INLINE_CODE_SPAN_RE.sub(project_span, text)
    return pattern.sub(resolve, projected)


def project_codex_reference_tokens(
    text: str, resolve: Callable[[str, str], str]
) -> str:
    """Project wrapped and bare symbolic references with Markdown context."""
    return project_codex_inline_tokens(
        text,
        _CODEX_SYMBOLIC_REFERENCE_RE,
        lambda match: resolve(match.group(1), match.group(2)),
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
    semantic_text = description + "\n" + body
    for skill_id, relative_path in _SKILL_ASSET_RE.findall(semantic_text):
        if skill_id != source.stem or ".." in Path(relative_path).parts:
            raise CanonicalSkillError(
                f"invalid skill-relative asset marker in {source}: "
                f"skill://{skill_id}/{relative_path}"
            )
    instruction_refs = set(
        _REFERENCE_RE.findall(_SKILL_ASSET_RE.sub("", semantic_text))
    )
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
    known_skill_ids = frozenset(
        candidate.stem
        for candidate in (root / "canonical" / "skills").glob("*/*.md")
        if candidate.name != "README.md"
    )
    leakage = provider_leakage(
        source.read_text(encoding="utf-8"), known_skill_ids=known_skill_ids
    )
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
    known_skill_ids = frozenset(
        candidate.stem
        for candidate in (root / "canonical" / "skills").glob("*/*.md")
        if candidate.name != "README.md"
    )
    leakage = provider_leakage(
        source.read_text(encoding="utf-8"), known_skill_ids=known_skill_ids
    )
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


def _canonical_skill_discovery_fingerprint(
    root: Path,
) -> _SourceFingerprint:
    source_root = root / "canonical" / "skills"
    if not source_root.is_dir():
        raise CanonicalSkillError(f"canonical skill root does not exist: {source_root}")
    sources = tuple(
        path for path in sorted(source_root.glob("*/*.md")) if path.name != "README.md"
    )
    return _source_tree_fingerprint(
        (*sources, root / "schemas" / "canonical-skill.schema.json"),
        boundary=root,
    )


@lru_cache(maxsize=16)
def _discover_canonical_skills_cached(
    root: Path,
    _fingerprint: _SourceFingerprint,
) -> tuple[CanonicalSkill, ...]:
    source_root = root / "canonical" / "skills"
    records = tuple(
        load_canonical_skill(root, path)
        for path in sorted(source_root.glob("*/*.md"))
        if path.name != "README.md"
    )
    destinations = [record.destination.as_posix() for record in records]
    if len(destinations) != len(set(destinations)):
        raise CanonicalSkillError("canonical skills resolve to duplicate destinations")
    if _canonical_skill_discovery_fingerprint(root) != _fingerprint:
        raise CanonicalSkillError("canonical skill sources changed during discovery")
    return tuple(sorted(records, key=lambda record: record.destination.as_posix()))


def discover_canonical_skills(payload_root: Path) -> tuple[CanonicalSkill, ...]:
    """Return all canonical skills in deterministic generated-path order.

    Canonical validation is expensive but its inputs are immutable during an
    ordinary render. A content-addressed metadata fingerprint keeps repeated
    renders fast while invalidating the cache for bytes, mode, topology, or
    schema changes.
    """
    root = Path(payload_root)
    fingerprint = _canonical_skill_discovery_fingerprint(root)
    records = _discover_canonical_skills_cached(root, fingerprint)
    if _canonical_skill_discovery_fingerprint(root) != fingerprint:
        _discover_canonical_skills_cached.cache_clear()
        raise CanonicalSkillError("canonical skill sources changed during discovery")
    return records


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


def _canonical_skill_asset_discovery_fingerprint(
    root: Path,
) -> _SourceFingerprint:
    source_root = root / "canonical" / "skills" / "assets"
    if not source_root.is_dir():
        raise CanonicalSkillError(
            f"canonical skill asset root does not exist: {source_root}"
        )
    return _source_tree_fingerprint(sorted(source_root.rglob("*")), boundary=root)


@lru_cache(maxsize=8)
def _discover_canonical_skill_assets_cached(
    root: Path,
    _asset_fingerprint: _SourceFingerprint,
    _skill_fingerprint: _SourceFingerprint,
) -> tuple[CanonicalSkillAsset, ...]:
    """Load one fingerprinted auxiliary-skill inventory."""

    source_root = root / "canonical" / "skills" / "assets"
    known_skill_ids = {
        record.spec.id
        for record in _discover_canonical_skills_cached(root, _skill_fingerprint)
    }
    records: list[CanonicalSkillAsset] = []
    for source in sorted(source_root.rglob("*")):
        if source.is_symlink():
            raise CanonicalSkillError(
                f"canonical skill asset must not be a symlink: {source}"
            )
        if not source.is_file():
            continue
        relative = source.relative_to(source_root)
        # Installing the wheel may byte-compile the bundled Python helper even
        # though it is package data rather than an importable module.  Ignore
        # only that interpreter-generated cache shape; every other unexpected
        # file under the canonical tree remains fail-closed.
        if "__pycache__" in relative.parts:
            if source.suffix == ".pyc":
                continue
            raise CanonicalSkillError(
                f"canonical skill asset cache directory has an unexpected file: {source}"
            )
        if len(relative.parts) < 2:
            raise CanonicalSkillError(
                f"canonical skill asset must be <skill-id>/<path>: {relative}"
            )
        skill_id = relative.parts[0]
        asset_path = Path(*relative.parts[1:])
        if skill_id != "_references" and skill_id not in known_skill_ids:
            raise CanonicalSkillError(
                f"canonical skill asset has no canonical owner {skill_id!r}: {source}"
            )
        if skill_id == "_references" and len(asset_path.parts) != 1:
            raise CanonicalSkillError(
                f"shared skill references must be flat files: {source}"
            )
        if any(part in {"", ".", ".."} for part in asset_path.parts):
            raise CanonicalSkillError(
                f"canonical skill asset has an unsafe relative path: {source}"
            )
        if source.suffix.lower() not in {".md", ".py", ".sh", ".txt"}:
            raise CanonicalSkillError(
                f"canonical skill asset has an unsupported type: {source}"
            )
        try:
            content = source.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise CanonicalSkillError(
                f"cannot read canonical skill asset {source}: {exc}"
            ) from exc
        if not content:
            raise CanonicalSkillError(
                f"canonical skill asset must not be empty: {source}"
            )
        if skill_id == "_references":
            leakage = provider_leakage(
                content, known_skill_ids=frozenset(known_skill_ids)
            )
            if leakage:
                raise CanonicalSkillError(
                    f"canonical shared skill reference {source} contains provider syntax: "
                    + ", ".join(sorted(set(leakage)))
                )
        mode = source.stat().st_mode & 0o777
        if mode not in {0o644, 0o755}:
            raise CanonicalSkillError(
                f"canonical skill asset has unsupported mode {mode:#o}: {source}"
            )
        records.append(
            CanonicalSkillAsset(
                skill_id=skill_id,
                relative_path=asset_path,
                canonical_path=source,
                content=content,
                mode=mode,
            )
        )
    _ensure_unique_skill_asset_destinations(records)
    if _canonical_skill_discovery_fingerprint(root) != _skill_fingerprint:
        raise CanonicalSkillError("canonical skill sources changed during discovery")
    if _canonical_skill_asset_discovery_fingerprint(root) != _asset_fingerprint:
        raise CanonicalSkillError("canonical skill assets changed during discovery")
    return tuple(sorted(records, key=lambda record: record.destination.as_posix()))


def discover_canonical_skill_assets(
    payload_root: Path,
) -> tuple[CanonicalSkillAsset, ...]:
    """Return the validated canonical auxiliary-skill inventory.

    The first path segment is either a real canonical skill id or ``_references``
    for shared checklist artifacts. Remaining segments stay skill-relative so
    projections preserve Markdown links and bundled-script paths without reading
    a generated compatibility tree. Fingerprinted caching avoids re-reading the
    multi-megabyte corpus while still invalidating on source or schema changes.
    """
    root = Path(payload_root)
    skill_fingerprint = _canonical_skill_discovery_fingerprint(root)
    asset_fingerprint = _canonical_skill_asset_discovery_fingerprint(root)
    records = _discover_canonical_skill_assets_cached(
        root,
        asset_fingerprint,
        skill_fingerprint,
    )
    if _canonical_skill_discovery_fingerprint(root) != skill_fingerprint:
        _discover_canonical_skills_cached.cache_clear()
        _discover_canonical_skill_assets_cached.cache_clear()
        raise CanonicalSkillError("canonical skill sources changed during discovery")
    if _canonical_skill_asset_discovery_fingerprint(root) != asset_fingerprint:
        _discover_canonical_skill_assets_cached.cache_clear()
        raise CanonicalSkillError("canonical skill assets changed during discovery")
    return records


def _ensure_unique_skill_asset_destinations(
    records: Iterable[CanonicalSkillAsset],
) -> None:
    """Reject aliases that collide on case-insensitive target filesystems."""
    destinations: dict[str, str] = {}
    for record in records:
        destination = record.destination.as_posix()
        destination_key = destination.casefold()
        prior = destinations.get(destination_key)
        if prior is not None:
            raise CanonicalSkillError(
                "canonical skill assets resolve to duplicate destination: "
                f"{prior} and {destination}"
            )
        destinations[destination_key] = destination


@dataclass(frozen=True)
class CodexSkillProjection:
    """Provider-native Codex text projected from one canonical skill."""

    name: str
    description: str
    instructions: str


_CODEX_EXTERNAL_LITERALS = {
    "external-model-current-balanced": "claude-sonnet-4-6",
    "external-model-versioned-balanced": "claude-sonnet-4@20250514",
    "external-model-legacy-balanced": "claude-3-5-sonnet-v2@20241022",
    "external-model-legacy-fast": "claude-3-5-haiku@20241022",
    "external-model-family-balanced": "claude-sonnet-4",
    "external-model-multimodal": "gpt-4o",
    "external-model-env-balanced": "CLAUDE_SONNET_MODEL",
    "external-model-env-deep": "CLAUDE_OPUS_MODEL",
    "external-plugin-collection": "claude-plugins-official",
    "external-skill-collection": "claude-night-market",
    "external-status-extension": "claude-hud",
    "external-shannon-cli-max-output-tokens": "CLAUDE_CODE_MAX_OUTPUT_TOKENS",
    "external-shannon-cli-use-bedrock": "CLAUDE_CODE_USE_BEDROCK",
    "external-shannon-cli-use-vertex": "CLAUDE_CODE_USE_VERTEX",
    "external-shannon-cli-adaptive-thinking": "CLAUDE_ADAPTIVE_THINKING",
}
_CODEX_TOOL_TERMS = {
    "file_read": "file reading",
    "file_write": "file creation",
    "file_edit": "file editing",
    "file_glob": "file discovery",
    "file_search": "text search",
    "shell": "shell execution",
    "delegate": "delegation",
    "skill": "skill invocation",
    "task_create": "task-ledger creation",
    "task_get": "task-ledger lookup",
    "task_list": "task-ledger listing",
    "task_update": "task-ledger update",
    "message": "worker messaging",
}
_CODEX_FIXED_COMMANDS = frozenset({"abort", "init", "status"})


def _unavailable_reference(kind: str, component_id: str) -> str:
    if kind == "agent":
        return (
            f"the optional `{component_id}` role "
            "(not installed for this selection; do not dispatch)"
        )
    if kind in {"skill", "command"}:
        return (
            f"the optional `{component_id}` skill "
            "(not installed for this selection; do not invoke)"
        )
    if kind == "rule":
        return (
            f"the optional `{component_id}` engineering rule "
            "(not installed for this selection; do not rely on it)"
        )
    raise ValueError(f"unsupported selection-aware reference kind: {kind!r}")


def codex_reference_target(
    kind: str,
    component_id: str,
    *,
    skill_reference_base: str | None,
    plugin_context: bool,
    selected_inventory: Mapping[str, frozenset[str]] | None,
) -> str:
    selected = None if selected_inventory is None else selected_inventory.get(kind)
    if kind == "command" and selected_inventory is not None and selected is None:
        selected = frozenset(
            _CODEX_FIXED_COMMANDS | selected_inventory.get("skill", frozenset())
        )
    is_available = selected is None or component_id in selected
    if kind == "agent":
        return (
            f".codex/agents/{component_id}.toml"
            if is_available
            else _unavailable_reference(kind, component_id)
        )
    if kind == "skill":
        if not is_available:
            return _unavailable_reference(kind, component_id)
        return (
            f"the {component_id} skill"
            if plugin_context
            else f".agents/skills/{component_id}/SKILL.md"
        )
    if kind == "rule":
        if not is_available:
            return _unavailable_reference(kind, component_id)
        return component_id if plugin_context else f".ckit/rules/{component_id}.md"
    if kind == "command":
        if not is_available:
            return _unavailable_reference(kind, component_id)
        if component_id in _CODEX_FIXED_COMMANDS:
            return f"`ckit {component_id}`"
        return f"the {component_id} skill" if plugin_context else f"${component_id}"
    if kind == "state":
        return {
            "root": ".ckit",
            "continuity": ".ckit/CONTINUITY.md",
            "agent-memory": ".ckit/agent-memory/",
            "agent-memory-index": ".ckit/agent-memory/MEMORY.md",
            "pipeline-snapshot": ".ckit/state/pipeline-snapshot.json",
            "ticket-board": ".ckit/state/ticket-board.html",
            "workflow": ".ckit/state/",
            "stack-catalog": ".ckit/config/stack-catalog.snapshot.yaml",
            "init-options": ".ckit/config/init-options.json",
            "maker-checker-config": ".ckit/config/init-options.json",
            "deploy-config": ".ckit/config/deploy.yaml",
            "configuration": ".ckit/config/",
        }.get(component_id, f".ckit/state/{component_id}")
    if kind == "artifact":
        return {
            "project-instructions": "AGENTS.md",
            "alternate-project-instructions": (
                "CLAUDE.md" if plugin_context else "an alternate runtime's instructions"
            ),
            "mcp-configuration": ".codex/config.toml",
            "skill-library": ".agents/skills",
            "rule-library": (
                ".ckit/rules"
                if plugin_context
                else "the installed engineering-rule library"
            ),
            "change-proposal-template": ".ckit/templates/change-proposal.md",
            "stack-rule-pattern": (
                ".ckit/rules/<stack>-patterns.md"
                if plugin_context
                else "the installed stack-specific engineering rule"
            ),
            "skill-domain-example": ".agents/skills/<domain>/SKILL.md",
            "skill-domain-directory": ".agents/skills/<domain>/",
        }.get(
            component_id,
            (
                f"{skill_reference_base or '.agents/skills/_references'}/"
                f"{component_id.removeprefix('skill-reference-')}.md"
                if component_id.startswith("skill-reference-")
                else component_id
            ),
        )
    return f"{kind}://{component_id}"


def _project_codex_skill_semantics(
    text: str,
    *,
    plugin_context: bool,
    selected_inventory: Mapping[str, frozenset[str]] | None,
) -> str:
    skill_reference_base = "references" if plugin_context else None

    def reference(match: re.Match[str]) -> str:
        return codex_reference_target(
            match.group(1),
            match.group(2),
            skill_reference_base=skill_reference_base,
            plugin_context=plugin_context,
            selected_inventory=selected_inventory,
        )

    def cross_skill_link(match: re.Match[str]) -> str:
        label, component_id = match.group(1), match.group(2)
        selected = (
            None if selected_inventory is None else selected_inventory.get("skill")
        )
        if selected is not None and component_id not in selected:
            return f"{label} ({_unavailable_reference('skill', component_id)})"
        return f"[{label}](../{component_id}/SKILL.md)"

    text = text.replace("{{state_dir:state://agent-memory}}", ".ckit/agent-memory/")
    text = _CROSS_SKILL_LINK_RE.sub(cross_skill_link, text)
    text = _SKILL_ASSET_RE.sub(
        lambda match: (
            match.group(2)
            if plugin_context
            else f".agents/skills/{match.group(1)}/{match.group(2)}"
        ),
        text,
    )
    skill_invocation_re = re.compile(
        r"\{\{skill_invocation:skill://([a-z0-9][a-z0-9._-]*)\}\}"
    )
    text = project_codex_inline_tokens(
        text,
        skill_invocation_re,
        lambda match: (
            f"${match.group(1)}"
            if selected_inventory is None
            or selected_inventory.get("skill") is None
            or match.group(1) in selected_inventory["skill"]
            else _unavailable_reference("skill", match.group(1))
        ),
    )
    ref_marker_re = re.compile(
        r"\{\{ref:(agent|skill|rule|command|hook|workflow|stage|handler|gate|state|artifact)"
        r"://([a-z0-9][a-z0-9._-]*)\}\}"
    )
    text = project_codex_inline_tokens(
        text,
        ref_marker_re,
        reference,
    )
    for marker in ("command_alias", "short_command"):
        marker_re = re.compile(
            rf"\{{\{{{marker}:command://([a-z0-9][a-z0-9._-]*)\}}\}}",
        )
        text = project_codex_inline_tokens(
            text,
            marker_re,
            lambda match: codex_reference_target(
                "command",
                match.group(1),
                skill_reference_base=skill_reference_base,
                plugin_context=plugin_context,
                selected_inventory=selected_inventory,
            ),
        )
    for marker, suffix in (
        ("skill_file", "/SKILL.md"),
        ("skill_dir", "/"),
        ("skill_path", ""),
    ):

        def project_skill(match: re.Match[str], suffix: str = suffix) -> str:
            component_id = match.group(1)
            selected = (
                None if selected_inventory is None else selected_inventory.get("skill")
            )
            if selected is not None and component_id not in selected:
                return _unavailable_reference("skill", component_id)
            if plugin_context:
                return f"the {component_id} skill"
            return f".agents/skills/{component_id}{suffix}"

        marker_re = re.compile(rf"\{{\{{{marker}:skill://([a-z0-9][a-z0-9._-]*)\}}\}}")
        text = project_codex_inline_tokens(
            text,
            marker_re,
            project_skill,
        )
    text = project_codex_reference_tokens(
        text,
        lambda kind, component_id: codex_reference_target(
            kind,
            component_id,
            skill_reference_base=skill_reference_base,
            plugin_context=plugin_context,
            selected_inventory=selected_inventory,
        ),
    )

    replacements = {
        "{{request}}": "the invocation request",
        "{{pause_for_human:input}}": "pause and request user input",
        "{{host:title}}": "Codex",
        "{{host:product}}": "Codex",
        "{{host:lower}}": "codex",
        "{{host:upper}}": "CODEX",
        "{{external_assistant:title}}": "Claude",
        "{{external_assistant:lower}}": "claude",
        "{{external_assistant:upper}}": "CLAUDE",
        "{{kit:distribution}}": "claude-code-kit",
        "{{kit:legacy-cli}}": "claude-sdlc",
        "{{kit:cli}}": "ckit",
        "{{kit:sidecar-suffix}}": ".claude-kit",
        "{{domain_literal:task-list-component}}": "TaskList",
        "{{provider_metadata:tool-allowlist}}": (
            "provider-native tool allowlist metadata"
        ),
        "{{external_permission:alternate-review-read-only}}": "--approval-mode plan",
        "{{capture_worker:job}}": "configured background capture adapter",
        "{{host_feature:statusline-api}}": (
            "the host's status interface, where available"
        ),
        "{{host_feature:dynamic-workflows}}": (
            "a native dynamic-workflow facility, where supported"
        ),
        "{{host_constraint:nested-delegation}}": (
            "the active host or policy prevents nested delegation"
        ),
        "{{model_tier:balanced-title}}": "Balanced",
        "{{model_tier:balanced}}": "balanced",
        "{{model_tier:deep-title}}": "Deep",
        "{{model_tier:deep}}": "deep",
        "{{model_tier:fast-title}}": "Fast",
        "{{model_tier:fast}}": "fast",
        "{{alternate_runtime:title}}": "an alternate model runtime",
        "{{alternate_runtime:full-title}}": "an alternate model runtime",
        "{{alternate_runtime:cli-title}}": "an alternate model CLI",
        "{{alternate_runtime:exec}}": "<alternate-model-cli> exec",
        "{{alternate_runtime:binary}}": "<alternate-model-cli>",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    for key, literal in _CODEX_EXTERNAL_LITERALS.items():
        text = text.replace(f"{{{{external_literal:{key}}}}}", literal)
    for key, value in _CODEX_TOOL_TERMS.items():
        text = text.replace(f"{{{{tool:{key}}}}}", value)
    text = re.sub(
        r"\{\{kit_env:([a-z0-9-]+)\}\}",
        lambda match: "CKIT_" + match.group(1).upper().replace("-", "_"),
        text,
    )
    text = re.sub(
        r"\{\{host_env:([a-z0-9-]+)\}\}",
        lambda match: "<host-env:" + match.group(1) + ">",
        text,
    )
    unresolved = re.findall(r"\{\{[a-z][a-z0-9_-]*:[^{}]+\}\}", text)
    if unresolved:
        raise CanonicalSkillError(
            f"unresolved Codex semantic markers: {sorted(set(unresolved))}"
        )
    return text


def project_codex_skill(
    record: CanonicalSkill,
    *,
    plugin_context: bool = False,
    selected_inventory: Mapping[str, frozenset[str]] | None = None,
) -> CodexSkillProjection:
    """Project one canonical skill into native Codex metadata and instructions."""
    return CodexSkillProjection(
        name=record.spec.id,
        description=_project_codex_skill_semantics(
            record.spec.description,
            plugin_context=plugin_context,
            selected_inventory=selected_inventory,
        ),
        instructions=_project_codex_skill_semantics(
            record.spec.instructions,
            plugin_context=plugin_context,
            selected_inventory=selected_inventory,
        ),
    )


def project_codex_skill_asset(
    asset: CanonicalSkillAsset,
    *,
    plugin_context: bool = False,
    selected_inventory: Mapping[str, frozenset[str]] | None = None,
) -> str:
    """Project one canonical text asset without changing skill-relative links."""
    content = asset.content
    if (
        asset.skill_id == "_references"
        and asset.relative_path.name == "orchestration-patterns.md"
    ):
        content = _adapt_codex_orchestration_reference(content)
    return _project_codex_skill_semantics(
        content,
        plugin_context=plugin_context,
        selected_inventory=selected_inventory,
    )


def _adapt_codex_orchestration_reference(source: str) -> str:
    """Insert the provider-owned Codex appendix into the neutral reference."""
    marker = "{{provider_appendix:orchestration-patterns}}"
    if source.count(marker) != 1:
        raise CanonicalSkillError(
            "orchestration reference must declare exactly one provider appendix marker"
        )
    appendix = """## Codex host appendix

Project skills live under `.agents/skills/`, while named project workers live
under `.codex/agents/`. Map each persona to a native delegated worker when the
active Codex surface exposes that capability. If named workers or worker
messaging are unavailable, embed the persona instructions in a generic
delegated task and require a typed result.

Treat nested delegation, shared task ledgers, worker messaging, and parallel
dispatch as capability-gated. Keep orchestration in the main session whenever
a capability is absent. Parallel fan-out still requires independent workers
and one explicit merge in the main session.

---
"""
    return source.replace(marker, appendix).rstrip() + "\n"


__all__ = [
    "CANONICAL_SKILL_SCHEMA_VERSION",
    "CodexSkillProjection",
    "CanonicalCommand",
    "CanonicalSkill",
    "CanonicalSkillAsset",
    "CanonicalSkillError",
    "PausePoint",
    "RequestInput",
    "RequestMode",
    "SkillSourceKind",
    "codex_reference_target",
    "discover_canonical_commands",
    "discover_canonical_skill_assets",
    "discover_canonical_skills",
    "load_canonical_command",
    "load_canonical_skill",
    "provider_leakage",
    "project_codex_inline_tokens",
    "project_codex_reference_tokens",
    "project_codex_skill",
    "project_codex_skill_asset",
    "raw_skill_invocations",
]
