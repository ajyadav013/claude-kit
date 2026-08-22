"""Provider-neutral component contracts for payload projection.

The catalog selects *which* logical components are active.  These records describe
what those components mean without embedding Claude or Codex file layouts, model
names, or tool identifiers.  Provider renderers translate the semantic fields into
their native formats later in the install pipeline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Mapping, Optional, Type, TypeVar, Union


class ComponentKind(str, Enum):
    """Kinds of installable logical payload components."""

    AGENT = "agent"
    SKILL = "skill"
    RULE = "rule"
    COMMAND = "command"
    HOOK = "hook"
    WORKFLOW = "workflow"


class ReferenceKind(str, Enum):
    """Closed set of symbolic-reference schemes used by the component IR."""

    AGENT = "agent"
    SKILL = "skill"
    RULE = "rule"
    COMMAND = "command"
    HOOK = "hook"
    WORKFLOW = "workflow"
    STAGE = "stage"
    HANDLER = "handler"
    GATE = "gate"
    STATE = "state"
    ARTIFACT = "artifact"


class Capability(str, Enum):
    """Provider-independent capabilities an agent or skill may require."""

    FILE_READ = "filesystem.read"
    FILE_WRITE = "filesystem.write"
    SEARCH = "filesystem.search"
    SHELL = "shell"
    DELEGATE = "delegation"
    MESSAGE = "delegation.message"
    TASK_LEDGER = "workflow.ledger"
    BROWSER = "browser"
    USER_INPUT = "human.input"
    MCP = "mcp"
    EXTERNAL_MUTATION = "external.mutation"
    DESCENDANT_CONTAINMENT = "process.descendant_containment"


class ModelTier(str, Enum):
    """Semantic model routing tiers resolved by each provider adapter."""

    FAST = "fast"
    BALANCED = "balanced"
    DEEP = "deep"


class PermissionClass(str, Enum):
    """Provider-neutral mutation and orchestration boundaries."""

    READ_ONLY = "read_only"
    WORKSPACE_WRITE = "workspace_write"
    EXTERNAL_EFFECT = "external_effect"


# Compatibility alias for the short-lived foundation name.  Canonical payloads
# and new callers use PermissionClass.
PermissionLevel = PermissionClass


class IsolationRequirement(str, Enum):
    """How strongly a role requires an isolated working tree."""

    NONE = "none"
    PREFERRED = "preferred"
    REQUIRED = "required"
    NATIVE = "native"


class NestedDelegationPolicy(str, Enum):
    """Whether a spawned role may create further workers."""

    FORBIDDEN = "forbidden"
    ALLOWED = "allowed"
    REQUIRED = "required"


class InvocationMode(str, Enum):
    """Whether a skill or command may be selected implicitly."""

    IMPLICIT = "implicit"
    EXPLICIT = "explicit"


class RuleStrength(str, Enum):
    """How strongly a rendered instruction must be applied."""

    ADVISORY = "advisory"
    REQUIRED = "required"


class HookEvent(str, Enum):
    """Semantic lifecycle events independent of provider wire spelling."""

    SESSION_START = "session-start"
    USER_PROMPT = "user-prompt"
    PRE_TOOL = "pre-tool"
    POST_TOOL = "post-tool"
    TOOL_FAILURE = "tool-failure"
    STOP = "stop"
    SUBAGENT_START = "subagent-start"
    SUBAGENT_STOP = "subagent-stop"
    PRE_COMPACT = "pre-compact"
    SESSION_END = "session-end"
    NOTIFICATION = "notification"


class HookEffect(str, Enum):
    """The control-flow effect a hook is allowed to have."""

    ADVISORY = "advisory"
    BLOCKING = "blocking"


class HookSeverity(str, Enum):
    """Portable diagnostic severity independent of host output encoding."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class MCPTransport(str, Enum):
    """Provider-independent MCP connection transports."""

    STDIO = "stdio"
    HTTP = "http"
    SSE = "sse"


class MCPAuthenticationMode(str, Enum):
    """How an MCP server obtains authentication without embedding credentials."""

    INFERRED = "inferred"
    NONE = "none"
    OAUTH = "oauth"
    HOST = "host"


_ENV_REF_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_SECRET_KEY_RE = re.compile(r"(?:token|secret|password|credential|api[_-]?key)", re.I)


_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_EnumT = TypeVar("_EnumT", bound=Enum)
_RefInput = Union["SymbolicRef", str]


def _component_id(value: object, *, field_name: str = "id") -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    normalized = value.strip().lower()
    if not _ID_RE.fullmatch(normalized) or ".." in normalized:
        raise ValueError(
            f"{field_name} must use lowercase letters, digits, dots, underscores, "
            "or hyphens"
        )
    return normalized


def _required_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _enum_value(value: object, enum_type: Type[_EnumT], *, field_name: str) -> _EnumT:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        allowed = ", ".join(str(item.value) for item in enum_type)
        raise ValueError(f"{field_name} must be one of: {allowed}") from exc


def _string_tuple(values: Iterable[str], *, field_name: str) -> tuple[str, ...]:
    if isinstance(values, str):
        raise ValueError(f"{field_name} must be a sequence of strings")
    normalized = tuple(
        _required_text(item, field_name=f"{field_name} item") for item in values
    )
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{field_name} must not contain duplicates")
    return normalized


@dataclass(frozen=True, order=True)
class SymbolicRef:
    """A stable logical URI such as ``agent://orchestrator``.

    References deliberately contain no provider path.  A renderer is responsible
    for resolving a URI to a concrete destination such as ``agents/orchestrator.md``
    or ``.codex/agents/orchestrator.toml``.
    """

    kind: ReferenceKind
    id: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "kind",
            _enum_value(self.kind, ReferenceKind, field_name="reference kind"),
        )
        object.__setattr__(
            self, "id", _component_id(self.id, field_name="reference id")
        )

    @classmethod
    def parse(cls, value: str) -> SymbolicRef:
        """Parse and validate a symbolic URI."""
        if not isinstance(value, str) or value.count("://") != 1:
            raise ValueError("symbolic reference must have the form kind://id")
        scheme, component_id = value.split("://", 1)
        return cls(
            _enum_value(scheme, ReferenceKind, field_name="reference kind"),
            component_id,
        )

    @classmethod
    def coerce(cls, value: _RefInput) -> SymbolicRef:
        """Return ``value`` as a validated :class:`SymbolicRef`."""
        if isinstance(value, SymbolicRef):
            return value
        return cls.parse(value)

    @property
    def uri(self) -> str:
        """Canonical string representation used in manifests and diagnostics."""
        return f"{self.kind.value}://{self.id}"

    def __str__(self) -> str:
        return self.uri


def _references(
    values: Iterable[_RefInput],
    *,
    field_name: str,
    expected: Optional[ReferenceKind] = None,
) -> tuple[SymbolicRef, ...]:
    if isinstance(values, str):
        raise ValueError(f"{field_name} must be a sequence of symbolic references")
    refs = tuple(SymbolicRef.coerce(value) for value in values)
    if expected is not None:
        wrong = [ref.uri for ref in refs if ref.kind is not expected]
        if wrong:
            raise ValueError(
                f"{field_name} must contain only {expected.value} references: "
                + ", ".join(wrong)
            )
    if len(set(refs)) != len(refs):
        raise ValueError(f"{field_name} must not contain duplicates")
    return refs


def _capabilities(values: Iterable[Capability]) -> frozenset[Capability]:
    if isinstance(values, str):
        values = (values,)  # type: ignore[assignment]
    return frozenset(
        _enum_value(value, Capability, field_name="capability") for value in values
    )


def _component_ref(kind: ReferenceKind, component_id: str) -> SymbolicRef:
    return SymbolicRef(kind, component_id)


@dataclass(frozen=True)
class AgentSpec:
    """Provider-neutral definition of a selectable specialist agent."""

    id: str
    description: str
    instructions: str
    model_tier: ModelTier = ModelTier.BALANCED
    permission: PermissionClass = PermissionClass.READ_ONLY
    capabilities: frozenset[Capability] = field(default_factory=frozenset)
    write_scope: tuple[str, ...] = ()
    isolation: IsolationRequirement = IsolationRequirement.NONE
    nested_delegation: NestedDelegationPolicy = NestedDelegationPolicy.FORBIDDEN
    required_skills: tuple[SymbolicRef, ...] = ()
    references: tuple[SymbolicRef, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _component_id(self.id))
        object.__setattr__(
            self,
            "description",
            _required_text(self.description, field_name="description"),
        )
        object.__setattr__(
            self,
            "instructions",
            _required_text(self.instructions, field_name="instructions"),
        )
        object.__setattr__(
            self,
            "model_tier",
            _enum_value(self.model_tier, ModelTier, field_name="model_tier"),
        )
        permission = _enum_value(
            self.permission, PermissionClass, field_name="permission"
        )
        capabilities = _capabilities(self.capabilities)
        if permission is PermissionClass.READ_ONLY and capabilities & {
            Capability.FILE_WRITE,
            Capability.EXTERNAL_MUTATION,
        }:
            raise ValueError("a read-only agent cannot require mutation capabilities")
        if (
            Capability.EXTERNAL_MUTATION in capabilities
            and permission is not PermissionClass.EXTERNAL_EFFECT
        ):
            raise ValueError(
                "external.mutation requires the external_effect permission class"
            )
        object.__setattr__(self, "permission", permission)
        object.__setattr__(self, "capabilities", capabilities)
        write_scope = _string_tuple(self.write_scope, field_name="write_scope")
        if any(
            scope.startswith(("/", "\\")) or ".." in scope.split("/")
            for scope in write_scope
        ):
            raise ValueError("write_scope must be project-relative and contained")
        if permission is PermissionClass.READ_ONLY and write_scope:
            raise ValueError("a read-only agent cannot declare a write_scope")
        object.__setattr__(self, "write_scope", write_scope)
        object.__setattr__(
            self,
            "isolation",
            _enum_value(self.isolation, IsolationRequirement, field_name="isolation"),
        )
        object.__setattr__(
            self,
            "nested_delegation",
            _enum_value(
                self.nested_delegation,
                NestedDelegationPolicy,
                field_name="nested_delegation",
            ),
        )
        required_skills = _references(
            self.required_skills,
            field_name="required_skills",
            expected=ReferenceKind.SKILL,
        )
        if (
            self.nested_delegation is not NestedDelegationPolicy.FORBIDDEN
            and Capability.DELEGATE not in capabilities
        ):
            raise ValueError("nested delegation requires the delegation capability")
        object.__setattr__(self, "required_skills", required_skills)
        object.__setattr__(
            self,
            "references",
            _references(self.references, field_name="references"),
        )

    @property
    def ref(self) -> SymbolicRef:
        return _component_ref(ReferenceKind.AGENT, self.id)


@dataclass(frozen=True)
class SkillSpec:
    """Provider-neutral reusable skill instructions and requirements."""

    id: str
    description: str
    instructions: str
    invocation: InvocationMode = InvocationMode.IMPLICIT
    capabilities: frozenset[Capability] = field(default_factory=frozenset)
    references: tuple[SymbolicRef, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _component_id(self.id))
        object.__setattr__(
            self,
            "description",
            _required_text(self.description, field_name="description"),
        )
        object.__setattr__(
            self,
            "instructions",
            _required_text(self.instructions, field_name="instructions"),
        )
        object.__setattr__(
            self,
            "invocation",
            _enum_value(self.invocation, InvocationMode, field_name="invocation"),
        )
        object.__setattr__(self, "capabilities", _capabilities(self.capabilities))
        object.__setattr__(
            self,
            "references",
            _references(self.references, field_name="references"),
        )

    @property
    def ref(self) -> SymbolicRef:
        return _component_ref(ReferenceKind.SKILL, self.id)


@dataclass(frozen=True)
class RuleSpec:
    """Provider-neutral engineering instruction with optional path scopes."""

    id: str
    description: str
    content: str
    strength: RuleStrength = RuleStrength.REQUIRED
    path_globs: tuple[str, ...] = ()
    references: tuple[SymbolicRef, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _component_id(self.id))
        object.__setattr__(
            self,
            "description",
            _required_text(self.description, field_name="description"),
        )
        object.__setattr__(
            self, "content", _required_text(self.content, field_name="content")
        )
        object.__setattr__(
            self,
            "strength",
            _enum_value(self.strength, RuleStrength, field_name="strength"),
        )
        globs = _string_tuple(self.path_globs, field_name="path_globs")
        if any(
            glob.startswith(("/", "\\")) or ".." in glob.split("/") for glob in globs
        ):
            raise ValueError("path_globs must be project-relative and contained")
        object.__setattr__(self, "path_globs", globs)
        object.__setattr__(
            self,
            "references",
            _references(self.references, field_name="references"),
        )

    @property
    def ref(self) -> SymbolicRef:
        return _component_ref(ReferenceKind.RULE, self.id)


@dataclass(frozen=True)
class CommandSpec:
    """Provider-neutral explicitly invoked workflow entry point."""

    id: str
    description: str
    instructions: str
    arguments: str = ""
    invocation: InvocationMode = InvocationMode.EXPLICIT
    capabilities: frozenset[Capability] = field(default_factory=frozenset)
    references: tuple[SymbolicRef, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _component_id(self.id))
        object.__setattr__(
            self,
            "description",
            _required_text(self.description, field_name="description"),
        )
        object.__setattr__(
            self,
            "instructions",
            _required_text(self.instructions, field_name="instructions"),
        )
        if not isinstance(self.arguments, str):
            raise ValueError("arguments must be a string")
        object.__setattr__(self, "arguments", self.arguments.strip())
        object.__setattr__(
            self,
            "invocation",
            _enum_value(self.invocation, InvocationMode, field_name="invocation"),
        )
        object.__setattr__(self, "capabilities", _capabilities(self.capabilities))
        object.__setattr__(
            self,
            "references",
            _references(self.references, field_name="references"),
        )

    @property
    def ref(self) -> SymbolicRef:
        return _component_ref(ReferenceKind.COMMAND, self.id)


@dataclass(frozen=True)
class HookSpec:
    """Logical lifecycle hook linked to a symbolic handler, never a shell path."""

    id: str
    description: str
    event: HookEvent
    action: SymbolicRef
    operation_matcher: Optional[str] = None
    effect: HookEffect = HookEffect.ADVISORY
    severity: HookSeverity = HookSeverity.WARNING
    data_access: tuple[str, ...] = ()
    timeout_seconds: int = 10
    references: tuple[SymbolicRef, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _component_id(self.id))
        object.__setattr__(
            self,
            "description",
            _required_text(self.description, field_name="description"),
        )
        object.__setattr__(
            self,
            "event",
            _enum_value(self.event, HookEvent, field_name="event"),
        )
        action = SymbolicRef.coerce(self.action)
        if action.kind is not ReferenceKind.HANDLER:
            raise ValueError("action must be a handler:// symbolic reference")
        object.__setattr__(self, "action", action)
        if self.operation_matcher is not None:
            object.__setattr__(
                self,
                "operation_matcher",
                _required_text(self.operation_matcher, field_name="operation_matcher"),
            )
        object.__setattr__(
            self,
            "effect",
            _enum_value(self.effect, HookEffect, field_name="effect"),
        )
        object.__setattr__(
            self,
            "severity",
            _enum_value(self.severity, HookSeverity, field_name="severity"),
        )
        object.__setattr__(
            self,
            "data_access",
            _string_tuple(self.data_access, field_name="data_access"),
        )
        if (
            not isinstance(self.timeout_seconds, int)
            or isinstance(self.timeout_seconds, bool)
            or self.timeout_seconds < 1
        ):
            raise ValueError("timeout_seconds must be a positive integer")
        object.__setattr__(
            self,
            "references",
            _references(self.references, field_name="references"),
        )

    @property
    def ref(self) -> SymbolicRef:
        return _component_ref(ReferenceKind.HOOK, self.id)


@dataclass(frozen=True)
class MCPServerSpec:
    """A semantic MCP definition compiled into either host's native configuration.

    Catalog entries describe transport and authentication once. ``provider_config`` intentionally
    returns the long-standing neutral fragment shape consumed by existing Claude and Codex
    renderers, preserving backward compatibility while making the source contract explicit.
    """

    id: str
    label: str
    transport: MCPTransport
    command: Optional[str] = None
    url: Optional[str] = None
    arguments: tuple[str, ...] = ()
    environment: tuple[tuple[str, str], ...] = ()
    headers: tuple[tuple[str, str], ...] = ()
    authentication: MCPAuthenticationMode = MCPAuthenticationMode.INFERRED
    runtime_support: frozenset[str] = field(
        default_factory=lambda: frozenset({"claude", "codex"})
    )
    health_check: str = "mcp-initialize"
    environment_references: tuple[str, ...] = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _component_id(self.id))
        object.__setattr__(
            self, "label", _required_text(self.label, field_name="MCP label")
        )
        transport = _enum_value(
            self.transport, MCPTransport, field_name="MCP transport"
        )
        object.__setattr__(self, "transport", transport)
        command = self.command.strip() if isinstance(self.command, str) else None
        url = self.url.strip() if isinstance(self.url, str) else None
        if transport is MCPTransport.STDIO and not command:
            raise ValueError("stdio MCP servers require a command")
        if transport in {MCPTransport.HTTP, MCPTransport.SSE} and not url:
            raise ValueError("HTTP/SSE MCP servers require a URL")
        object.__setattr__(self, "command", command)
        object.__setattr__(self, "url", url)
        object.__setattr__(
            self,
            "arguments",
            _string_tuple(self.arguments, field_name="MCP arguments"),
        )
        environment = self._key_value_pairs(
            self.environment, field_name="MCP environment"
        )
        headers = self._key_value_pairs(self.headers, field_name="MCP headers")
        for key, value in (*environment, *headers):
            if _SECRET_KEY_RE.search(key) and not _ENV_REF_RE.fullmatch(value):
                raise ValueError(
                    f"MCP credential field {key!r} must be an environment reference"
                )
        object.__setattr__(self, "environment", environment)
        object.__setattr__(self, "headers", headers)
        object.__setattr__(
            self,
            "authentication",
            _enum_value(
                self.authentication,
                MCPAuthenticationMode,
                field_name="MCP authentication mode",
            ),
        )
        runtimes = frozenset(self.runtime_support)
        if not runtimes or not runtimes <= {"claude", "codex"}:
            raise ValueError(
                "MCP runtime_support must contain only claude and/or codex"
            )
        object.__setattr__(self, "runtime_support", runtimes)
        object.__setattr__(
            self,
            "health_check",
            _required_text(self.health_check, field_name="MCP health check"),
        )
        reference_values = [command or "", url or "", *self.arguments]
        reference_values.extend(value for _, value in environment)
        reference_values.extend(value for _, value in headers)
        references = tuple(
            sorted(
                {
                    match.group(1)
                    for value in reference_values
                    for match in _ENV_REF_RE.finditer(value)
                }
            )
        )
        object.__setattr__(self, "environment_references", references)

    @staticmethod
    def _key_value_pairs(
        values: Iterable[tuple[str, str]], *, field_name: str
    ) -> tuple[tuple[str, str], ...]:
        if isinstance(values, (str, bytes)):
            raise ValueError(f"{field_name} must be key/value pairs")
        pairs: list[tuple[str, str]] = []
        for raw_key, raw_value in values:
            key = _required_text(raw_key, field_name=f"{field_name} key")
            value = _required_text(raw_value, field_name=f"{field_name} value")
            pairs.append((key, value))
        if len({key for key, _ in pairs}) != len(pairs):
            raise ValueError(f"{field_name} must not contain duplicate keys")
        return tuple(sorted(pairs))

    @classmethod
    def from_catalog(cls, server_id: str, record: Mapping[str, Any]) -> MCPServerSpec:
        """Validate and load one ``catalog/mcp.yaml`` server record."""

        config = record.get("config")
        auth = record.get("authentication")
        health = record.get("health_check")
        if not isinstance(config, Mapping):
            raise ValueError(f"MCP server {server_id!r} config must be a mapping")
        if not isinstance(auth, Mapping):
            raise ValueError(
                f"MCP server {server_id!r} authentication must be a mapping"
            )
        if not isinstance(health, Mapping):
            raise ValueError(f"MCP server {server_id!r} health_check must be a mapping")
        environment = config.get("env", {})
        headers = config.get("headers", {})
        if not isinstance(environment, Mapping) or not isinstance(headers, Mapping):
            raise ValueError(f"MCP server {server_id!r} env/headers must be mappings")
        runtimes = record.get("runtime_support", ())
        if isinstance(runtimes, str):
            raise ValueError(
                f"MCP server {server_id!r} runtime_support must be an array"
            )
        transport = _enum_value(
            config.get("type"), MCPTransport, field_name="MCP transport"
        )
        authentication = _enum_value(
            auth.get("mode"),
            MCPAuthenticationMode,
            field_name="MCP authentication mode",
        )
        health_check = _required_text(health.get("kind"), field_name="MCP health check")
        return cls(
            id=server_id,
            label=str(record.get("label", "")),
            transport=transport,
            command=config.get("command"),
            url=config.get("url"),
            arguments=tuple(config.get("args", ())),
            environment=tuple(
                (str(key), str(value)) for key, value in environment.items()
            ),
            headers=tuple((str(key), str(value)) for key, value in headers.items()),
            authentication=authentication,
            runtime_support=frozenset(runtimes),
            health_check=health_check,
        )

    @property
    def provider_config(self) -> dict[str, Any]:
        """Return the credential-free fragment rendered by both provider adapters."""

        config: dict[str, Any] = {"type": self.transport.value}
        if self.command:
            config["command"] = self.command
        if self.url:
            config["url"] = self.url
        if self.arguments:
            config["args"] = list(self.arguments)
        if self.environment:
            config["env"] = dict(self.environment)
        if self.headers:
            config["headers"] = dict(self.headers)
        return config

    @property
    def semantic_metadata(self) -> dict[str, Any]:
        """Return the provider-neutral policy retained beside rendered config.

        Native MCP documents do not have portable fields for authentication policy,
        runtime support, or health-check intent.  Keeping that information in the
        resolved plan and shared stack snapshot lets projection fail closed and lets
        validation/doctor report the actual catalog contract without adding
        provider-invalid keys to ``.mcp.json`` or Codex TOML.
        """

        return {
            "label": self.label,
            "transport": self.transport.value,
            "authentication": self.authentication.value,
            "runtime_support": sorted(self.runtime_support),
            "health_check": self.health_check,
            "environment_references": list(self.environment_references),
        }


@dataclass(frozen=True)
class WorkflowStage:
    """One dependency-aware stage in a provider-neutral workflow graph."""

    id: str
    description: str
    agents: tuple[SymbolicRef, ...] = ()
    skills: tuple[SymbolicRef, ...] = ()
    rules: tuple[SymbolicRef, ...] = ()
    gates: tuple[SymbolicRef, ...] = ()
    depends_on: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _component_id(self.id, field_name="stage id"))
        object.__setattr__(
            self,
            "description",
            _required_text(self.description, field_name="stage description"),
        )
        object.__setattr__(
            self,
            "agents",
            _references(self.agents, field_name="agents", expected=ReferenceKind.AGENT),
        )
        object.__setattr__(
            self,
            "skills",
            _references(self.skills, field_name="skills", expected=ReferenceKind.SKILL),
        )
        object.__setattr__(
            self,
            "rules",
            _references(self.rules, field_name="rules", expected=ReferenceKind.RULE),
        )
        object.__setattr__(
            self,
            "gates",
            _references(self.gates, field_name="gates", expected=ReferenceKind.GATE),
        )
        dependencies = tuple(
            _component_id(value, field_name="stage dependency")
            for value in self.depends_on
        )
        if len(set(dependencies)) != len(dependencies):
            raise ValueError("depends_on must not contain duplicates")
        if self.id in dependencies:
            raise ValueError(f"workflow stage {self.id!r} cannot depend on itself")
        object.__setattr__(self, "depends_on", dependencies)

    @property
    def ref(self) -> SymbolicRef:
        return _component_ref(ReferenceKind.STAGE, self.id)


@dataclass(frozen=True)
class WorkflowSpec:
    """A validated acyclic graph of SDLC stages."""

    id: str
    description: str
    stages: tuple[WorkflowStage, ...]
    references: tuple[SymbolicRef, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _component_id(self.id))
        object.__setattr__(
            self,
            "description",
            _required_text(self.description, field_name="description"),
        )
        if isinstance(self.stages, (str, bytes)):
            raise ValueError("stages must be a sequence of WorkflowStage records")
        stages = tuple(self.stages)
        if not stages or any(not isinstance(stage, WorkflowStage) for stage in stages):
            raise ValueError("stages must contain at least one WorkflowStage")
        by_id = {stage.id: stage for stage in stages}
        if len(by_id) != len(stages):
            raise ValueError("workflow stage ids must be unique")
        for stage in stages:
            missing = set(stage.depends_on) - set(by_id)
            if missing:
                raise ValueError(
                    f"workflow stage {stage.id!r} has unknown dependencies: "
                    + ", ".join(sorted(missing))
                )
        _assert_acyclic(by_id)
        object.__setattr__(self, "stages", stages)
        object.__setattr__(
            self,
            "references",
            _references(self.references, field_name="references"),
        )

    @property
    def ref(self) -> SymbolicRef:
        return _component_ref(ReferenceKind.WORKFLOW, self.id)


def _assert_acyclic(stages: dict[str, WorkflowStage]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(stage_id: str) -> None:
        if stage_id in visited:
            return
        if stage_id in visiting:
            raise ValueError(f"workflow dependencies contain a cycle at {stage_id!r}")
        visiting.add(stage_id)
        for dependency in stages[stage_id].depends_on:
            visit(dependency)
        visiting.remove(stage_id)
        visited.add(stage_id)

    for stage_id in stages:
        visit(stage_id)


__all__ = [
    "AgentSpec",
    "Capability",
    "CommandSpec",
    "ComponentKind",
    "HookEffect",
    "HookEvent",
    "HookSeverity",
    "HookSpec",
    "IsolationRequirement",
    "InvocationMode",
    "MCPAuthenticationMode",
    "MCPServerSpec",
    "MCPTransport",
    "ModelTier",
    "NestedDelegationPolicy",
    "PermissionClass",
    "PermissionLevel",
    "ReferenceKind",
    "RuleSpec",
    "RuleStrength",
    "SkillSpec",
    "SymbolicRef",
    "WorkflowSpec",
    "WorkflowStage",
]
