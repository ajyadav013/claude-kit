"""Typed data structures for claude-kit's catalog-driven scaffolder.

These dataclasses are the contract between the prompt layer (:mod:`claude_kit.prompts`), the
catalog resolver (:mod:`claude_kit.catalog`), and the installer (:mod:`claude_kit.scaffold`).
Using explicit types (rather than loose dicts) honours the kit's own "no bare container types"
documentation rule and keeps ``init-options.json`` round-trippable for ``validate``/``upgrade``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

#: Schema version of the persisted ``.claude/config/init-options.json`` document.
INIT_OPTIONS_SCHEMA = 1


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
        mcp: Selected MCP server ids (empty means no ``.mcp.json`` is written).
    """

    frontend_framework: str
    frontend_language: str
    backend_language: str
    backend_framework: str
    database: str
    profile: str
    mcp: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON/YAML-serialisable mapping of this selection."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Selection:
        """Build a :class:`Selection` from a mapping, ignoring unknown keys.

        Args:
            data: A mapping with the selection fields (e.g. parsed from ``--config``).

        Returns:
            A populated :class:`Selection`.
        """
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        kwargs = {k: v for k, v in data.items() if k in known}
        kwargs.setdefault("mcp", [])
        return cls(**kwargs)


@dataclass
class ResolvedPlan:
    """The concrete install plan produced by :func:`claude_kit.catalog.resolve`.

    Attributes:
        selection: The originating :class:`Selection`.
        agents: Core agent names to install (profile subset).
        skills: Skill directory names to install (profile subset ∪ stack-suggested).
        overlay_rules: Overlay rule filenames to copy from the selected stacks.
        overlay_agents: Overlay agent names to copy from the selected stacks.
        hooks: Hook ids to enable (drives copied scripts + assembled ``settings.json``).
        gates: Quality-gate ids active for the chosen profile.
        mcp_servers: Mapping of selected MCP server id to its ``.mcp.json`` config fragment.
        context: Flat string context for rendering ``CLAUDE.md`` / ``README`` (labels + commands).
        stack_dirs: Mapping of selected stack kind to its ``templates/stacks`` subdir.
    """

    selection: Selection
    agents: list[str]
    skills: list[str]
    overlay_rules: list[str]
    overlay_agents: list[str]
    hooks: list[str]
    gates: list[str]
    mcp_servers: dict[str, dict[str, Any]]
    context: dict[str, str]
    stack_dirs: dict[str, str]


@dataclass
class FileRecord:
    """A single installed file tracked in ``init-options.json`` for safe upgrades.

    Attributes:
        path: Path relative to the project root (POSIX separators).
        sha256: Hex SHA-256 of the file contents at install time.
        owner: One of ``"kit"`` (refreshed on upgrade), ``"overlay"`` (follows the selection),
            or ``"user-editable"`` (never clobbered).
    """

    path: str
    sha256: str
    owner: str

    def to_dict(self) -> dict[str, str]:
        """Return a JSON-serialisable mapping of this record."""
        return asdict(self)


@dataclass
class InitOptions:
    """The persisted ``.claude/config/init-options.json`` document.

    Attributes:
        claude_kit_version: Kit version that produced the install.
        selection: The user's resolved choices.
        files: Per-file checksum + ownership records (drives ``diff``/``upgrade``).
        schema_version: Document schema version (:data:`INIT_OPTIONS_SCHEMA`).
    """

    claude_kit_version: str
    selection: Selection
    files: list[FileRecord]
    schema_version: int = INIT_OPTIONS_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable mapping (checksums excluded from no field)."""
        return {
            "schema_version": self.schema_version,
            "claude_kit_version": self.claude_kit_version,
            "selection": self.selection.to_dict(),
            "files": [r.to_dict() for r in self.files],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InitOptions:
        """Reconstruct :class:`InitOptions` from a parsed ``init-options.json`` mapping."""
        return cls(
            claude_kit_version=str(data.get("claude_kit_version", "")),
            selection=Selection.from_dict(data.get("selection", {})),
            files=[FileRecord(**r) for r in data.get("files", [])],
            schema_version=int(data.get("schema_version", INIT_OPTIONS_SCHEMA)),
        )
