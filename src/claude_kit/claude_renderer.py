"""Native Claude Code projection backed by the compatibility payload renderer.

The existing installer remains the behavioral golden for Claude while the
provider-neutral component catalog is populated.  This adapter renders that
payload into an isolated directory, removes legacy mutable-state files, rewrites
state references to :class:`~claude_kit.models.StateLayout.neutral`, and returns
immutable projection records.  Live-project mutation remains the responsibility
of the runtime installer.

Keeping the strangler here is intentional: Claude output can be characterized
and kept byte-compatible independently of Codex without teaching
``catalog.resolve()`` about either provider.
"""

from __future__ import annotations

import re
import tempfile
from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
from typing import Iterable

from claude_kit.components import Capability, SymbolicRef
from claude_kit.models import InstallRequest, ResolvedPlan
from claude_kit.projection import (
    ProjectionFile,
    ProjectionOwner,
    Provider,
    ProviderSpec,
)
from claude_kit.provider_compatibility import load_agent_projection_compatibility
from claude_kit.scaffold import _install_sdlc_direct, _preflight_plan, payload_dir

_LEGACY_STATE_PREFIXES = (
    ".claude/config/",
    ".claude/state/",
    ".claude/tmp/",
    ".claude/agent-memory/",
)
_LEGACY_STATE_FILES = frozenset({".claude/CONTINUITY.template.md"})
_STATE_REWRITES = (
    # The legacy continuity hook composes its live path from this directory
    # variable, so replacing only the final literal path is insufficient.
    ('MEM_DIR="$ROOT/.claude"', 'MEM_DIR="$ROOT/.ckit"'),
    (".claude/config/init-options.json", ".ckit/config/init-options.json"),
    (
        ".claude/config/stack-catalog.snapshot.yaml",
        ".ckit/config/stack-catalog.snapshot.yaml",
    ),
    (".claude/state/pipeline-snapshot.json", ".ckit/state/pipeline-snapshot.json"),
    (".claude/CONTINUITY.md", ".ckit/CONTINUITY.md"),
    (".claude/agent-memory", ".ckit/agent-memory"),
    (".claude/artifacts", ".ckit/artifacts"),
    (".claude/state", ".ckit/state"),
    (".claude/tmp", ".ckit/tmp"),
)


def _neutralize_state_references(content: bytes) -> bytes:
    """Rewrite only legacy mutable-state locations in textual payload files."""

    if b"\x00" in content:
        return content
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return content
    for old, new in _STATE_REWRITES:
        text = text.replace(old, new)
    return text.encode("utf-8")


def _safe_id(value: str) -> str:
    """Return a symbolic-reference-safe id derived from one projected path."""

    normalized = re.sub(r"[^a-z0-9._-]+", "-", value.lower()).strip("-._")
    return normalized or "root"


def _component_for_path(path: str) -> SymbolicRef:
    """Map a native destination back to its logical component identity."""

    parts = Path(path).parts
    if len(parts) >= 3 and parts[:2] == (".claude", "agents"):
        return SymbolicRef.parse(f"agent://{_safe_id(Path(parts[-1]).stem)}")
    if len(parts) >= 4 and parts[:2] == (".claude", "skills"):
        skill = _safe_id(parts[2])
        if skill != "references":
            return SymbolicRef.parse(f"skill://{skill}")
    if len(parts) >= 3 and parts[:2] == (".claude", "rules"):
        return SymbolicRef.parse(f"rule://{_safe_id(Path(parts[-1]).stem)}")
    if len(parts) >= 3 and parts[:2] == (".claude", "hooks"):
        return SymbolicRef.parse(f"hook://{_safe_id(Path(parts[-1]).stem)}")
    return SymbolicRef.parse(f"artifact://claude-{_safe_id(path)}")


def _owner_for_path(path: str, plan: ResolvedPlan) -> ProjectionOwner:
    """Preserve the existing Claude upgrade ownership contract."""

    if path in {
        "CLAUDE.md",
        "README.claude-sdlc.md",
        ".mcp.json",
        ".mcp.lock.json",
        ".claude/settings.json",
    }:
        return ProjectionOwner.USER_EDITABLE
    overlays = {f".claude/rules/{name}" for name in plan.overlay_rules}
    overlays.update(f".claude/agents/{name}.md" for name in plan.overlay_agents)
    if path in overlays:
        return ProjectionOwner.OVERLAY
    return ProjectionOwner.KIT


class ClaudeRenderer:
    """Render the selected logical payload into Claude Code's native layout."""

    def __init__(self, source: Path | None = None) -> None:
        self._source = Path(source) if source is not None else None
        if self._source is not None:
            self._compatibility = load_agent_projection_compatibility(
                self._source, "claude"
            )
        else:
            with ExitStack() as resources:
                self._compatibility = load_agent_projection_compatibility(
                    payload_dir(resources), "claude"
                )

    @property
    def spec(self) -> ProviderSpec:
        """Declare the exact compatibility-catalog version used by this renderer."""

        return ProviderSpec(
            provider=Provider.CLAUDE,
            rendering_version=1,
            compatibility_catalog_version=self._compatibility.catalog_version,
            capabilities=frozenset(Capability),
        )

    def render(
        self, resolved_plan: ResolvedPlan, request: InstallRequest
    ) -> Iterable[ProjectionFile]:
        """Return a deterministic Claude projection without touching the project."""

        if Provider.CLAUDE.value not in request.runtimes:
            raise ValueError("ClaudeRenderer requires a Claude installation request")
        rendered_plan = deepcopy(resolved_plan)
        # Command detection is a project concern and has already been performed by
        # the caller.  Re-running it against the isolated render directory would
        # erase the caller's deterministic context.
        rendered_plan.selection.detect_commands = False
        rendered_plan.context.setdefault("project_name", "project")

        with ExitStack() as resources:
            source = self._source or payload_dir(resources)
            _preflight_plan(source, rendered_plan)
            with tempfile.TemporaryDirectory(prefix="ckit-claude-render-") as tmp:
                root = Path(tmp).resolve()
                _install_sdlc_direct(
                    source,
                    root,
                    rendered_plan,
                    force=True,
                    log=[],
                    rescue_existing=False,
                )
                files: list[ProjectionFile] = []
                for native in sorted(root.rglob("*")):
                    if not native.is_file():
                        continue
                    relative = native.relative_to(root).as_posix()
                    if relative == "AGENTS.md" or relative == ".gitignore":
                        continue
                    if relative in _LEGACY_STATE_FILES or relative.startswith(
                        _LEGACY_STATE_PREFIXES
                    ):
                        continue
                    files.append(
                        ProjectionFile(
                            provider=Provider.CLAUDE,
                            component=_component_for_path(relative),
                            path=relative,
                            content=_neutralize_state_references(native.read_bytes()),
                            owner=_owner_for_path(relative, resolved_plan),
                            executable=bool(native.stat().st_mode & 0o111),
                        )
                    )
                return tuple(files)


__all__ = ["ClaudeRenderer"]
