"""Typed data structures for claude-kit's catalog-driven scaffolder.

These dataclasses are the contract between the prompt layer (:mod:`claude_kit.prompts`), the
catalog resolver (:mod:`claude_kit.catalog`), and the installer (:mod:`claude_kit.scaffold`).
Using explicit types (rather than loose dicts) honours the kit's own "no bare container types"
documentation rule and keeps ``init-options.json`` round-trippable for ``validate``/``upgrade``.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import PurePosixPath
from typing import Any

from claude_kit.components import MCPServerSpec, ModelTier

#: Schema version of the persisted runtime-neutral ``init-options.json`` document.
INIT_OPTIONS_SCHEMA = 3

#: Filename (under ``.claude/config/``) of the transactional upgrade journal.
UPGRADE_JOURNAL = "upgrade-in-progress.json"

#: Schema version of the upgrade-journal document.
UPGRADE_JOURNAL_SCHEMA = 1


class Runtime(str, Enum):
    """A requested native host projection.

    ``both`` is an installation mode rather than a third provider.  Persisted
    manifests therefore record its two concrete providers in :attr:`providers`.
    Keeping this outside :class:`Selection` preserves the branch-free catalog
    invariant: runtime affects projection and installation, never stack/profile
    resolution.
    """

    CLAUDE = "claude"
    CODEX = "codex"
    BOTH = "both"

    @classmethod
    def parse(cls, value: str | Runtime) -> Runtime:
        """Return a validated runtime value with a concise error on bad input."""
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).strip().lower())
        except ValueError as exc:
            allowed = ", ".join(item.value for item in cls)
            raise ValueError(f"runtime must be one of: {allowed}") from exc

    @property
    def providers(self) -> tuple[str, ...]:
        """Concrete provider ids represented by this installation mode."""
        if self is Runtime.BOTH:
            return (Runtime.CLAUDE.value, Runtime.CODEX.value)
        return (self.value,)

    @classmethod
    def from_providers(cls, providers: list[str] | tuple[str, ...]) -> Runtime:
        """Reconstruct the installation mode from persisted concrete providers."""
        normalized = tuple(str(item).strip().lower() for item in providers)
        if len(set(normalized)) != len(normalized):
            raise ValueError(
                "runtimes must contain claude, codex, or both concrete providers exactly once"
            )
        if normalized == (cls.CLAUDE.value,):
            return cls.CLAUDE
        if normalized == (cls.CODEX.value,):
            return cls.CODEX
        if (
            set(normalized) == {cls.CLAUDE.value, cls.CODEX.value}
            and len(normalized) == 2
        ):
            return cls.BOTH
        raise ValueError(
            "runtimes must contain claude, codex, or both concrete providers exactly once"
        )


class ModelChoiceKind(str, Enum):
    """How an execution worker's native model is selected."""

    INHERIT = "inherit"
    TIER = "tier"
    EXACT = "exact"


_NATIVE_MODEL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,127}$")


@dataclass(frozen=True)
class ModelChoice:
    """Provider-bound model choice kept outside the canonical catalog.

    Semantic tiers remain portable. Exact ids are user configuration consumed
    only by the selected provider adapter, while ``inherit`` leaves selection
    to that host.
    """

    kind: ModelChoiceKind
    value: str | ModelTier | None = None

    def __post_init__(self) -> None:
        try:
            kind = (
                self.kind
                if isinstance(self.kind, ModelChoiceKind)
                else ModelChoiceKind(str(self.kind).strip().lower())
            )
        except ValueError as exc:
            allowed = ", ".join(item.value for item in ModelChoiceKind)
            raise ValueError(f"model choice kind must be one of: {allowed}") from exc

        raw_value = self.value
        if kind is ModelChoiceKind.INHERIT:
            if raw_value is not None:
                raise ValueError("inherit model choice must not define a value")
            value: str | None = None
        elif kind is ModelChoiceKind.TIER:
            if raw_value is None:
                raise ValueError("tier model choice requires a value")
            try:
                value = (
                    raw_value.value
                    if isinstance(raw_value, ModelTier)
                    else ModelTier(str(raw_value).strip().lower()).value
                )
            except ValueError as exc:
                allowed = ", ".join(item.value for item in ModelTier)
                raise ValueError(f"model tier must be one of: {allowed}") from exc
        else:
            if not isinstance(raw_value, str):
                raise ValueError(
                    "exact model choice requires a safe non-empty model id"
                )
            value = raw_value.strip()
            if not _NATIVE_MODEL_ID_RE.fullmatch(value):
                raise ValueError(
                    "exact model id must be 1-128 ASCII letters, digits, or ._:/@+- "
                    "and must start with a letter or digit"
                )

        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "value", value)

    def to_dict(self) -> dict[str, str]:
        """Return the strict persisted representation."""
        document = {"kind": self.kind.value}
        if self.value is not None:
            document["value"] = self.value
        return document

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ModelChoice:
        """Parse a model choice, rejecting unknown fields."""
        if not isinstance(data, dict):
            raise ValueError("model choice must be an object")
        unknown = set(data) - {"kind", "value"}
        if unknown:
            raise ValueError(
                "unknown model choice field(s): " + ", ".join(sorted(map(str, unknown)))
            )
        if "kind" not in data:
            raise ValueError("model choice requires kind")
        return cls(kind=data["kind"], value=data.get("value"))


@dataclass(frozen=True)
class WorkerBinding:
    """Concrete native provider plus its model-selection policy."""

    provider: Runtime
    model: ModelChoice

    def __post_init__(self) -> None:
        try:
            provider = Runtime.parse(self.provider)
        except ValueError as exc:
            raise ValueError(
                "worker binding requires provider claude or codex"
            ) from exc
        if provider is Runtime.BOTH:
            raise ValueError("worker binding requires a concrete provider, never both")
        if not isinstance(self.model, ModelChoice):
            raise ValueError("worker binding model must be a ModelChoice")
        object.__setattr__(self, "provider", provider)

    def to_dict(self) -> dict[str, Any]:
        """Return the strict persisted representation."""
        return {"provider": self.provider.value, "model": self.model.to_dict()}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkerBinding:
        """Parse a worker binding, rejecting unknown fields."""
        if not isinstance(data, dict):
            raise ValueError("worker binding must be an object")
        unknown = set(data) - {"provider", "model"}
        if unknown:
            raise ValueError(
                "unknown worker binding field(s): "
                + ", ".join(sorted(map(str, unknown)))
            )
        if "provider" not in data or "model" not in data:
            raise ValueError("worker binding requires provider and model")
        if not isinstance(data["model"], dict):
            raise ValueError("worker binding model must be an object")
        return cls(
            provider=data["provider"],
            model=ModelChoice.from_dict(data["model"]),
        )


@dataclass(frozen=True)
class ExecutionPolicy:
    """Bounded maker/reviewer defaults for future managed executions."""

    maker: WorkerBinding
    reviewer: WorkerBinding
    strategy: str = "maker-reviewer"
    max_revisions: int = 2

    def __post_init__(self) -> None:
        if self.strategy != "maker-reviewer":
            raise ValueError("execution strategy must be 'maker-reviewer'")
        if not isinstance(self.maker, WorkerBinding) or not isinstance(
            self.reviewer, WorkerBinding
        ):
            raise ValueError(
                "execution policy maker and reviewer must be worker bindings"
            )
        if (
            not isinstance(self.max_revisions, int)
            or isinstance(self.max_revisions, bool)
            or not 0 <= self.max_revisions <= 3
        ):
            raise ValueError("execution max_revisions must be an integer from 0 to 3")

    def validate_providers(self, providers: tuple[str, ...] | list[str]) -> None:
        """Require every worker to use one of the installed native providers."""
        installed = set(Runtime.from_providers(providers).providers)
        for role, binding in (("maker", self.maker), ("reviewer", self.reviewer)):
            if binding.provider.value not in installed:
                rendered = ", ".join(sorted(installed))
                raise ValueError(
                    f"{role} provider {binding.provider.value!r} is not installed "
                    f"(installed: {rendered})"
                )

    def to_dict(self) -> dict[str, Any]:
        """Return the strict persisted representation."""
        return {
            "strategy": self.strategy,
            "maker": self.maker.to_dict(),
            "reviewer": self.reviewer.to_dict(),
            "max_revisions": self.max_revisions,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExecutionPolicy:
        """Parse an execution policy, rejecting unknown or missing fields."""
        if not isinstance(data, dict):
            raise ValueError("execution policy must be an object")
        known = {"strategy", "maker", "reviewer", "max_revisions"}
        unknown = set(data) - known
        if unknown:
            raise ValueError(
                "unknown execution policy field(s): "
                + ", ".join(sorted(map(str, unknown)))
            )
        missing = {"strategy", "maker", "reviewer"} - set(data)
        if missing:
            raise ValueError(
                "execution policy missing field(s): " + ", ".join(sorted(missing))
            )
        return cls(
            strategy=data["strategy"],
            maker=WorkerBinding.from_dict(data["maker"]),
            reviewer=WorkerBinding.from_dict(data["reviewer"]),
            max_revisions=data.get("max_revisions", 2),
        )


@dataclass(frozen=True)
class StateLayout:
    """Provider-neutral locations for mutable kit state.

    Fresh installations use :meth:`neutral`; :meth:`legacy_claude` keeps old
    ``.claude`` installations readable during the expand/contract migration.
    Every path is project-relative and containment-checked at construction.
    """

    name: str
    root: str
    manifest: str
    stack_snapshot: str
    pipeline_snapshot: str
    journal: str
    continuity: str
    memory: str
    artifacts: str
    state: str
    temporary: str

    def __post_init__(self) -> None:
        """Reject layouts that could escape the project or split their root."""
        root = contained_relpath(self.root)
        if "/" in root:
            raise ValueError(
                "state layout root must be one top-level project directory"
            )
        object.__setattr__(self, "root", root)
        for attr in (
            "manifest",
            "stack_snapshot",
            "pipeline_snapshot",
            "journal",
            "continuity",
            "memory",
            "artifacts",
            "state",
            "temporary",
        ):
            value = contained_relpath(getattr(self, attr))
            if value != root and not value.startswith(root + "/"):
                raise ValueError(f"state layout {attr} must be contained under {root}/")
            object.__setattr__(self, attr, value)

    @classmethod
    def neutral(cls) -> StateLayout:
        """Layout for every new Claude, Codex, or dual-runtime installation."""
        return cls(
            name="neutral-v1",
            root=".ckit",
            manifest=".ckit/config/init-options.json",
            stack_snapshot=".ckit/config/stack-catalog.snapshot.yaml",
            pipeline_snapshot=".ckit/state/pipeline-snapshot.json",
            journal=".ckit/config/upgrade-in-progress.json",
            continuity=".ckit/CONTINUITY.md",
            memory=".ckit/agent-memory",
            artifacts=".ckit/artifacts",
            state=".ckit/state",
            temporary=".ckit/tmp",
        )

    @classmethod
    def legacy_claude(cls) -> StateLayout:
        """Compatibility layout used by pre-v2 Claude-only installations."""
        return cls(
            name="legacy-claude-v1",
            root=".claude",
            manifest=".claude/config/init-options.json",
            stack_snapshot=".claude/config/stack-catalog.snapshot.yaml",
            pipeline_snapshot=".claude/state/pipeline-snapshot.json",
            journal=".claude/config/upgrade-in-progress.json",
            continuity=".claude/CONTINUITY.md",
            memory=".claude/agent-memory",
            artifacts=".claude/artifacts",
            state=".claude/state",
            temporary=".claude/tmp",
        )

    def to_dict(self) -> dict[str, str]:
        """Return a stable JSON-serialisable layout document."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StateLayout:
        """Parse a persisted layout, accepting only the two supported layouts."""
        if not isinstance(data, dict):
            raise ValueError("state_layout must be an object")
        name = data.get("name")
        known = {
            "neutral-v1": cls.neutral(),
            "legacy-claude-v1": cls.legacy_claude(),
        }
        if name not in known:
            raise ValueError(f"unsupported state layout {name!r}")
        expected = known[str(name)]

        def required_string(key: str) -> str:
            value = data.get(key)
            if not isinstance(value, str):
                raise ValueError(f"state layout {key} must be a string")
            return value

        supplied = cls(
            name=required_string("name"),
            root=required_string("root"),
            manifest=required_string("manifest"),
            stack_snapshot=required_string("stack_snapshot"),
            pipeline_snapshot=required_string("pipeline_snapshot"),
            journal=required_string("journal"),
            continuity=required_string("continuity"),
            memory=required_string("memory"),
            artifacts=required_string("artifacts"),
            state=required_string("state"),
            temporary=required_string("temporary"),
        )
        if supplied != expected:
            raise ValueError(
                f"state layout {name!r} does not match its canonical paths"
            )
        return supplied


def _read_schema_version(data: dict[str, Any], *, current: int, document: str) -> int:
    """Read a persisted schema version, treating absence as explicit legacy v1 only.

    Persisted documents predate ``schema_version``. They remain readable as v1, but a declared
    future version must never be silently coerced into the current dataclass shape.
    """
    if "schema_version" not in data:
        return 1
    value = data["schema_version"]
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{document} schema_version must be an integer")
    if value > current:
        raise ValueError(
            f"unsupported future {document} schema_version {value} "
            f"(maximum supported: {current})"
        )
    if value < 1:
        raise ValueError(
            f"unsupported {document} schema_version {value} (minimum supported: 1)"
        )
    return value


@dataclass
class Selection:
    """A fully-resolved set of user choices from ``init`` (prompts, ``--defaults``, or ``--config``).

    Attributes:
        frontend_framework: Frontend framework id (e.g. ``"react"``).
        frontend_language: Frontend language id (e.g. ``"typescript"``).
        backend_language: Backend language id (e.g. ``"python"``).
        backend_framework: Backend framework id (e.g. ``"fastapi"``).
        database: Database id (``"postgres"`` or ``"mongodb"``).
        profile: SDLC profile id (``"lean"``/``"standard"``/``"enterprise"``).
        capture_mode: Agent-side learning-capture trigger (``"off"``/``"session-end"``/
            ``"session-end-catchup"``/``"per-task"``; see ``catalog/capture.yaml``). Controls how
            often / when the background capture job fires (the token-cost knob); recall stays
            profile-driven. Defaults to ``off`` — the capture job reads session transcript
            content, so every non-interactive path is opt-in; only an explicit choice (the
            interactive ``init`` question, a config file, or this field) turns it on.
        mcp: Selected MCP server ids (empty means no ``.mcp.json`` is written).
        scope: Usage scope (``"individual"``/``"team"``/``"organization"``). Only ``organization``
            installs the org capability layer (packs, persona agents, org rules, autonomy hooks).
        teams: Teams adopting the config (organization scope only; personalises the generated README).
        autonomy: Autonomy level (``advisory``/``assisted``/``autonomous-local``/``autonomous-pr``/
            ``enterprise-controlled``); higher levels enable more guardrail hooks. Prompted only in
            organization scope; defaults to ``assisted`` everywhere else.
        review_strictness: Review strictness (``light``/``standard``/``regulated``); ``regulated``
            adds extra gates/hooks. Prompted only in organization scope.
        org_packs: Whether to generate the reusable org capability packs (organization scope only).
        detect_commands: Whether ``init``/``upgrade`` may inspect the target repo for its real
            package-manager commands and override the catalog defaults in CLAUDE.md (default True;
            a no-op on an empty target). Set False to keep the generic catalog commands.
    """

    frontend_framework: str
    frontend_language: str
    backend_language: str
    backend_framework: str
    database: str
    profile: str
    capture_mode: str = "off"
    mcp: list[str] = field(default_factory=list)
    scope: str = "team"
    teams: list[str] = field(default_factory=list)
    autonomy: str = "assisted"
    review_strictness: str = "standard"
    org_packs: bool = True
    detect_commands: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON/YAML-serialisable mapping of this selection."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, strict: bool = False) -> Selection:
        """Build a :class:`Selection` from a mapping.

        Args:
            data: A mapping with the selection fields (e.g. parsed from ``--config``). Org fields
                may be absent in older documents; their dataclass defaults apply (back-compatible).
            strict: When ``True`` (used for freshly-parsed user config), reject unknown keys and
                wrong-typed values instead of silently ignoring/accepting them. The default stays
                lenient so persisted ``init-options.json`` from older kits still round-trips.

        Returns:
            A populated :class:`Selection`.

        Raises:
            ValueError: In ``strict`` mode, if ``data`` has unknown keys or a field has the wrong
                type (the list fields must be lists of strings; ``org_packs`` must be a bool).
        """
        if not isinstance(data, dict):
            raise ValueError("selection must be an object")
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        if strict:
            unknown = set(data) - known
            if unknown:
                raise ValueError(
                    f"unknown selection field(s): {', '.join(sorted(unknown))} "
                    f"(known: {', '.join(sorted(known))})"
                )
        string_fields = (
            "frontend_framework",
            "frontend_language",
            "backend_language",
            "backend_framework",
            "database",
            "profile",
            "capture_mode",
            "scope",
            "autonomy",
            "review_strictness",
        )
        for fname in string_fields:
            if fname in data and not isinstance(data[fname], str):
                raise ValueError(f"selection field {fname!r} must be a string")
        for fname in ("mcp", "teams"):
            if fname in data and (
                not isinstance(data[fname], list)
                or any(not isinstance(x, str) for x in data[fname])
            ):
                raise ValueError(f"selection field {fname!r} must be a list of strings")
        for fname in ("org_packs", "detect_commands"):
            if fname in data and not isinstance(data[fname], bool):
                raise ValueError(f"selection field {fname!r} must be a boolean")
        kwargs = {k: v for k, v in data.items() if k in known}
        kwargs.setdefault("mcp", [])
        return cls(**kwargs)


@dataclass(frozen=True)
class InstallRequest:
    """Installation choices applied after provider-neutral catalog resolution.

    The resolver consumes :attr:`selection` exactly as it did before.  The
    projection compiler consumes :attr:`runtime`, preventing provider concerns
    from leaking into the stack/profile catalog. Optional maker/reviewer defaults
    cross the same post-resolution seam in :attr:`execution_policy`.
    """

    selection: Selection
    runtime: Runtime = Runtime.CLAUDE
    execution_policy: ExecutionPolicy | None = None

    def __post_init__(self) -> None:
        """Normalize string construction while retaining a typed public API."""
        object.__setattr__(self, "runtime", Runtime.parse(self.runtime))
        if self.execution_policy is not None:
            if not isinstance(self.execution_policy, ExecutionPolicy):
                raise ValueError("execution_policy must be an ExecutionPolicy when set")
            self.execution_policy.validate_providers(self.runtime.providers)

    @property
    def runtimes(self) -> tuple[str, ...]:
        """Concrete provider ids to persist and project."""
        return self.runtime.providers


@dataclass
class OrgPlan:
    """The resolved organization capability layer (only present when ``scope == organization``).

    Produced by :func:`claude_kit.catalog.resolve` from ``catalog/org.yaml`` and consumed by
    :func:`claude_kit.scaffold.install_sdlc` (its ``_install_org`` step). The new skills/agents/rules
    install into the standard auto-discovered ``.claude/{skills,agents,rules}`` dirs; the packs install
    as manifests under ``.claude/org-packs/``. Autonomy hooks are merged into :attr:`ResolvedPlan.hooks`
    so they flow through the normal settings assembly.

    Attributes:
        scope: The usage scope (always ``"organization"`` here).
        teams: Teams adopting the config (personalises the generated README).
        autonomy: The chosen autonomy level id.
        autonomy_policy: One-line human-readable policy for the chosen autonomy level.
        review_strictness: The chosen review-strictness id.
        packs: Org-pack ids whose manifests install under ``.claude/org-packs/``.
        org_skills: New skill dir names to copy from ``templates/org/skills/`` into ``.claude/skills/``.
        org_agents: New persona agent names to copy from ``templates/org/agents/`` into ``.claude/agents/``.
        org_rules: New rule filenames to copy from ``templates/org/rules/`` into ``.claude/rules/``.
        added_hooks: Hook ids added by the autonomy level / strictness (merged into the plan's hooks).
        added_agents: Core agent names the org layer activates regardless of profile (e.g.
            ``risk-classifier``; installed via the normal core-agent path, so merged into the plan's
            ``agents``).
        extra_gates: Quality-gate ids added by the chosen review strictness (merged into the plan's
            ``gates``).
    """

    scope: str
    teams: list[str]
    autonomy: str
    autonomy_policy: str
    review_strictness: str
    packs: list[str]
    org_skills: list[str]
    org_agents: list[str]
    org_rules: list[str]
    added_hooks: list[str]
    added_agents: list[str] = field(default_factory=list)
    extra_gates: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON/YAML-serialisable mapping of this org plan."""
        return asdict(self)


@dataclass(frozen=True)
class GateDefinition:
    """Canonical policy metadata for one quality gate.

    Profile gate lists decide membership and execution order; this record decides whether the gate
    is required or conditional and, for a conditional gate, the closed set of conditions that can
    make it not applicable. Keeping the policy beside the catalog prevents ``pipeline.py`` from
    growing gate-name branches.
    """

    requirement: str
    skippable: bool
    skip_conditions: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.requirement not in {"required", "conditional"}:
            raise ValueError(
                f"gate requirement must be 'required' or 'conditional', got {self.requirement!r}"
            )
        if self.skippable != (self.requirement == "conditional"):
            raise ValueError(
                "gate skippable flag must be true exactly when requirement is 'conditional'"
            )
        if self.requirement == "required" and self.skip_conditions:
            raise ValueError("a required gate cannot declare skip conditions")
        if self.requirement == "conditional" and not self.skip_conditions:
            raise ValueError(
                "a conditional gate must declare at least one skip condition"
            )
        if any(
            not isinstance(item, str) or not item.strip()
            for item in self.skip_conditions
        ):
            raise ValueError("gate skip conditions must be non-empty strings")
        if len(set(self.skip_conditions)) != len(self.skip_conditions):
            raise ValueError("gate skip conditions must be unique")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GateDefinition:
        requirement = data.get("requirement")
        skippable = data.get("skippable")
        conditions = data.get("skip_conditions")
        if not isinstance(requirement, str):
            raise ValueError("gate requirement must be a string")
        if not isinstance(skippable, bool):
            raise ValueError("gate skippable must be a boolean")
        if not isinstance(conditions, list) or any(
            not isinstance(item, str) for item in conditions
        ):
            raise ValueError("gate skip_conditions must be a list of strings")
        return cls(
            requirement=requirement,
            skippable=skippable,
            skip_conditions=list(conditions),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "requirement": self.requirement,
            "skippable": self.skippable,
            "skip_conditions": list(self.skip_conditions),
        }


def digest_gate_definitions(
    ordered_gates: list[str], definitions: dict[str, GateDefinition]
) -> str:
    """Return a stable sha256 over the ordered gate policy frozen into a run."""
    if len(set(ordered_gates)) != len(ordered_gates):
        raise ValueError("ordered gate list contains duplicates")
    missing = set(ordered_gates) - set(definitions)
    extra = set(definitions) - set(ordered_gates)
    if missing or extra:
        details = []
        if missing:
            details.append(f"missing definitions: {', '.join(sorted(missing))}")
        if extra:
            details.append(f"extra definitions: {', '.join(sorted(extra))}")
        raise ValueError(
            "gate definition set does not match ordered gates ("
            + "; ".join(details)
            + ")"
        )
    payload = [{"gate": gate, **definitions[gate].to_dict()} for gate in ordered_gates]
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass
class ResolvedPlan:
    """The concrete install plan produced by :func:`claude_kit.catalog.resolve`.

    Attributes:
        selection: The originating :class:`Selection`.
        agents: Core agent names to install (profile subset, ∪ org core agents in organization scope).
        skills: Skill directory names to install (profile subset ∪ stack-suggested).
        overlay_rules: Overlay rule filenames to copy from the selected stacks.
        overlay_agents: Overlay agent names to copy from the selected stacks.
        hooks: Hook ids to enable (drives copied scripts + assembled ``settings.json``).
        gates: Quality-gate ids active for the chosen profile (∪ strictness gates in org scope).
        gate_definitions: Canonical policy metadata for each active gate, in execution order.
        gate_definition_digest: Stable digest of the ordered active gate definitions.
        mcp_servers: Backward-compatible mapping of selected MCP server id to its native-neutral
            config fragment.
        mcp_server_specs: Full semantic MCP records. Their ids and provider configs must match
            ``mcp_servers`` so runtime support, authentication, and health-check intent cannot be
            discarded between catalog resolution and projection.
        context: Flat string context for rendering ``CLAUDE.md`` / ``README`` (labels + commands).
        stack_dirs: Mapping of selected stack kind to its ``templates/stacks`` subdir.
        org: The resolved org capability layer, or ``None`` for individual/team scope.
        detected_commands: ``*_cmd`` context overrides discovered in the target repo (or ``None`` if
            discovery did not run); recorded in the stack snapshot for transparency.
    """

    selection: Selection
    agents: list[str]
    skills: list[str]
    overlay_rules: list[str]
    overlay_agents: list[str]
    hooks: list[str]
    gates: list[str]
    gate_definitions: dict[str, GateDefinition]
    gate_definition_digest: str
    mcp_servers: dict[str, dict[str, Any]]
    context: dict[str, str]
    stack_dirs: dict[str, str]
    org: OrgPlan | None = None
    detected_commands: dict[str, str] | None = None
    mcp_server_specs: dict[str, MCPServerSpec] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Keep compatibility fragments and semantic MCP records in lockstep."""

        # Config-only plans remain accepted for callers of the pre-IR public
        # dataclass. Catalog resolution always supplies semantic records; when
        # present they are authoritative and must match the compatibility view.
        if not self.mcp_server_specs:
            return
        config_ids = set(self.mcp_servers)
        spec_ids = set(self.mcp_server_specs)
        if config_ids != spec_ids:
            missing_specs = sorted(config_ids - spec_ids)
            missing_configs = sorted(spec_ids - config_ids)
            details: list[str] = []
            if missing_specs:
                details.append("missing semantic specs: " + ", ".join(missing_specs))
            if missing_configs:
                details.append(
                    "missing config fragments: " + ", ".join(missing_configs)
                )
            raise ValueError("resolved MCP ids differ (" + "; ".join(details) + ")")
        for server_id, spec in self.mcp_server_specs.items():
            if not isinstance(spec, MCPServerSpec):
                raise ValueError(
                    f"resolved MCP server {server_id!r} must be an MCPServerSpec"
                )
            if spec.id != server_id:
                raise ValueError(
                    f"resolved MCP key {server_id!r} does not match spec id {spec.id!r}"
                )
            if spec.provider_config != self.mcp_servers[server_id]:
                raise ValueError(
                    f"resolved MCP server {server_id!r} config differs from its semantic spec"
                )

    @property
    def mcp_semantics(self) -> dict[str, dict[str, Any]]:
        """Return deterministic semantic metadata for persistence and diagnostics."""

        return {
            server_id: self.mcp_server_specs[server_id].semantic_metadata
            for server_id in sorted(self.mcp_server_specs)
        }


def contained_relpath(raw: str) -> str:
    """Validate ``raw`` as a project-relative POSIX path and return it normalised.

    ``init-options.json`` lives inside the project being upgraded, so its ``files[].path`` entries
    are untrusted input: :mod:`claude_kit.upgrader` joins them onto the project root and then
    copies, overwrites, and *unlinks* the result. A path that escapes the root (``../../id_rsa``)
    or is absolute (``/etc/passwd``) would let a hand-edited — or hostile — manifest reach files
    outside the project. Rejecting them here means every consumer (``validate``, ``diff``,
    ``upgrade``, ``doctor``) inherits the guarantee from one place, at parse time, before any
    filesystem call. ``_read_init_options`` already renders the resulting :class:`ValueError` as a
    ``corrupt: <detail>`` manifest, which is the correct signal.

    Backslashes are normalised to ``/`` first so a Windows-style ``..\\..\\x`` cannot slip past a
    POSIX-only segment check and then be re-interpreted as a separator by ``pathlib`` on Windows.

    Args:
        raw: The candidate path string as read from the manifest.

    Returns:
        The path in normalised POSIX form.

    Raises:
        ValueError: If the path is empty, absolute, drive-qualified, or contains a ``..`` segment.
    """
    text = str(raw).replace("\\", "/").strip()
    if not text:
        raise ValueError("file record has an empty path")
    pure = PurePosixPath(text)
    if pure.is_absolute() or text.startswith("/"):
        raise ValueError(
            f"file record path must be project-relative, got absolute {raw!r}"
        )
    if len(text) > 1 and text[1] == ":":
        raise ValueError(
            f"file record path must be project-relative, got drive-qualified {raw!r}"
        )
    if ".." in pure.parts:
        raise ValueError(f"file record path escapes the project root: {raw!r}")
    return pure.as_posix()


@dataclass
class FileRecord:
    """A single installed file tracked in ``init-options.json`` for safe upgrades.

    The ``path`` is validated on construction by :func:`contained_relpath` — it must stay inside
    the project root, because the upgrader resolves it against that root and may delete the result.

    Attributes:
        path: Path relative to the project root (POSIX separators, no ``..``).
        sha256: Hex SHA-256 of the file contents at install time.
        owner: One of ``"kit"`` (refreshed on upgrade), ``"overlay"`` (follows the selection),
            or ``"user-editable"`` (never clobbered).
    """

    path: str
    sha256: str
    owner: str
    provider: str = "claude"
    component_id: str = ""

    def __post_init__(self) -> None:
        """Normalise and containment-check :attr:`path`."""
        self.path = contained_relpath(self.path)
        if (
            not isinstance(self.sha256, str)
            or len(self.sha256) != 64
            or any(ch not in "0123456789abcdef" for ch in self.sha256)
        ):
            raise ValueError(
                "file record sha256 must be 64 lowercase hexadecimal characters"
            )
        if self.owner not in {"kit", "overlay", "user-editable"}:
            raise ValueError(
                "file record owner must be 'kit', 'overlay', or 'user-editable'"
            )
        if self.provider not in {"claude", "codex", "shared"}:
            raise ValueError(
                "file record provider must be 'claude', 'codex', or 'shared'"
            )
        if not self.component_id:
            self.component_id = f"legacy-file://{self.path}"
        if not isinstance(self.component_id, str) or "://" not in self.component_id:
            raise ValueError(
                "file record component_id must be a symbolic component URI"
            )

    def to_dict(self) -> dict[str, str]:
        """Return a JSON-serialisable mapping of this record."""
        return asdict(self)


@dataclass
class InitOptions:
    """The persisted runtime-neutral ``init-options.json`` document.

    Attributes:
        claude_kit_version: Kit version that produced the install.
        selection: The user's resolved choices.
        files: Per-file checksum + ownership records (drives ``diff``/``upgrade``).
        execution_policy: Optional provider/model defaults for maker/reviewer execution.
        schema_version: Document schema version (:data:`INIT_OPTIONS_SCHEMA`).
    """

    claude_kit_version: str
    selection: Selection
    files: list[FileRecord]
    runtimes: list[str] = field(default_factory=lambda: [Runtime.CLAUDE.value])
    state_layout: StateLayout = field(default_factory=StateLayout.legacy_claude)
    rendering_version: int = 1
    compatibility_catalog_versions: dict[str, int] = field(
        default_factory=lambda: {Runtime.CLAUDE.value: 1}
    )
    execution_policy: ExecutionPolicy | None = None
    schema_version: int = INIT_OPTIONS_SCHEMA

    def __post_init__(self) -> None:
        """Validate runtime/layout metadata before it reaches lifecycle code."""
        mode = Runtime.from_providers(self.runtimes)
        self.runtimes = list(mode.providers)
        if not isinstance(self.state_layout, StateLayout):
            raise ValueError("state_layout must be a StateLayout")
        if (
            not isinstance(self.rendering_version, int)
            or isinstance(self.rendering_version, bool)
            or self.rendering_version < 1
        ):
            raise ValueError("rendering_version must be a positive integer")
        expected = set(self.runtimes)
        if set(self.compatibility_catalog_versions) != expected:
            raise ValueError(
                "compatibility catalog versions must match the installed runtimes"
            )
        if any(
            not isinstance(version, int) or isinstance(version, bool) or version < 1
            for version in self.compatibility_catalog_versions.values()
        ):
            raise ValueError("compatibility catalog versions must be positive integers")
        if self.execution_policy is not None:
            if not isinstance(self.execution_policy, ExecutionPolicy):
                raise ValueError("execution_policy must be an ExecutionPolicy when set")
            self.execution_policy.validate_providers(self.runtimes)

    @property
    def runtime(self) -> Runtime:
        """Installation mode reconstructed from concrete persisted providers."""
        return Runtime.from_providers(self.runtimes)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable mapping (checksums excluded from no field)."""
        return {
            "schema_version": self.schema_version,
            "claude_kit_version": self.claude_kit_version,
            "selection": self.selection.to_dict(),
            "files": [r.to_dict() for r in self.files],
            "runtimes": list(self.runtimes),
            "state_layout": self.state_layout.to_dict(),
            "rendering_version": self.rendering_version,
            "compatibility_catalog_versions": dict(self.compatibility_catalog_versions),
            "execution": (
                self.execution_policy.to_dict()
                if self.execution_policy is not None
                else None
            ),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InitOptions:
        """Reconstruct :class:`InitOptions` from a parsed ``init-options.json`` mapping."""
        if not isinstance(data, dict):
            raise ValueError("init-options document root must be an object")
        schema_version = _read_schema_version(
            data, current=INIT_OPTIONS_SCHEMA, document="init-options"
        )
        selection = data.get("selection", {})
        if not isinstance(selection, dict):
            raise ValueError("init-options selection must be an object")
        files = data.get("files", [])
        if not isinstance(files, list) or any(
            not isinstance(item, dict) for item in files
        ):
            raise ValueError("init-options files must be an array of objects")
        runtimes: list[str]
        state_layout: StateLayout
        rendering_version: int
        compatibility_versions: dict[str, int]
        execution_policy: ExecutionPolicy | None = None
        if schema_version == 1:
            runtimes = [Runtime.CLAUDE.value]
            state_layout = StateLayout.legacy_claude()
            rendering_version = 1
            compatibility_versions = {Runtime.CLAUDE.value: 1}
        else:
            raw_runtimes = data.get("runtimes")
            if not isinstance(raw_runtimes, list) or any(
                not isinstance(runtime, str) for runtime in raw_runtimes
            ):
                raise ValueError("init-options runtimes must be an array of strings")
            runtimes = raw_runtimes
            raw_layout = data.get("state_layout")
            if not isinstance(raw_layout, dict):
                raise ValueError("init-options state_layout must be an object")
            state_layout = StateLayout.from_dict(raw_layout)
            raw_rendering_version = data.get("rendering_version")
            if not isinstance(raw_rendering_version, int) or isinstance(
                raw_rendering_version, bool
            ):
                raise ValueError("init-options rendering_version must be an integer")
            rendering_version = raw_rendering_version
            raw_compatibility_versions = data.get("compatibility_catalog_versions")
            if not isinstance(raw_compatibility_versions, dict) or any(
                not isinstance(key, str) or not isinstance(value, int)
                for key, value in raw_compatibility_versions.items()
            ):
                raise ValueError(
                    "init-options compatibility_catalog_versions must be an object of integers"
                )
            compatibility_versions = {
                str(key): int(value)
                for key, value in raw_compatibility_versions.items()
            }
            if schema_version >= 3:
                raw_execution = data.get("execution")
                if raw_execution is not None:
                    if not isinstance(raw_execution, dict):
                        raise ValueError(
                            "init-options execution must be an object or null"
                        )
                    execution_policy = ExecutionPolicy.from_dict(raw_execution)
        return cls(
            claude_kit_version=str(data.get("claude_kit_version", "")),
            selection=Selection.from_dict(selection),
            files=[FileRecord(**record) for record in files],
            runtimes=runtimes,
            state_layout=state_layout,
            rendering_version=rendering_version,
            compatibility_catalog_versions=compatibility_versions,
            execution_policy=execution_policy,
            schema_version=INIT_OPTIONS_SCHEMA,
        )


@dataclass
class UpgradeJournal:
    """A transactional marker written *before* an upgrade mutates the tree, removed once it commits.

    :func:`claude_kit.upgrader.upgrade` writes this under ``.claude/config/`` before touching any file
    and deletes it only after the new baseline (``init-options.json``) is in place. Because ``upgrade``
    is convergent — render-and-compare always recomputes the plan from the *live* tree — a journal left
    behind by an interrupted run is harmless: the next ``upgrade`` finishes the work and clears it.
    ``doctor`` warns when one is present so an interrupted upgrade stays visible (it is gitignored, so
    it is never committed).

    Attributes:
        from_version: Kit version recorded in the install before the upgrade.
        to_version: Kit version the upgrade is moving to.
        started_at: ISO-8601 timestamp when the journal was written.
        actions: Planned file actions (``{"rel", "kind", "owner"}``) for post-mortem inspection.
        schema_version: Document schema version (:data:`UPGRADE_JOURNAL_SCHEMA`).
    """

    from_version: str
    to_version: str
    started_at: str
    actions: list[dict[str, str]]
    schema_version: int = UPGRADE_JOURNAL_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable mapping of this journal."""
        return {
            "schema_version": self.schema_version,
            "from_version": self.from_version,
            "to_version": self.to_version,
            "started_at": self.started_at,
            "actions": [dict(a) for a in self.actions],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UpgradeJournal:
        """Reconstruct :class:`UpgradeJournal` from a parsed journal mapping (tolerant of missing keys)."""
        if not isinstance(data, dict):
            raise ValueError("upgrade journal root must be an object")
        schema_version = _read_schema_version(
            data, current=UPGRADE_JOURNAL_SCHEMA, document="upgrade journal"
        )
        actions = data.get("actions", [])
        if not isinstance(actions, list) or any(
            not isinstance(action, dict) for action in actions
        ):
            raise ValueError("upgrade journal actions must be an array of objects")
        return cls(
            from_version=str(data.get("from_version", "")),
            to_version=str(data.get("to_version", "")),
            started_at=str(data.get("started_at", "")),
            actions=[dict(action) for action in actions],
            schema_version=schema_version,
        )
