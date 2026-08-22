"""Discovery and access helpers for the single mutable control plane.

Fresh installations use ``.ckit`` regardless of host.  During the compatibility
window, lifecycle commands continue to discover and read a legacy Claude-only
``.claude`` control plane.  Keeping this policy in one module prevents each
consumer from inventing a different precedence rule and, critically, prevents a
dual-runtime project from creating two independent gate ledgers.
"""

from __future__ import annotations

from pathlib import Path

from claude_kit.models import StateLayout
from claude_kit.secure_fs import ProjectFS


def _has_state(fs: ProjectFS, layout: StateLayout) -> bool:
    """Return whether a canonical layout has any authoritative state marker."""

    return any(
        fs.is_file(path)
        for path in (
            layout.manifest,
            layout.stack_snapshot,
            layout.pipeline_snapshot,
            layout.continuity,
        )
    )


def detect_state_layout(
    target: str | Path,
    *,
    fresh_default: StateLayout | None = None,
) -> StateLayout:
    """Discover the project's one active state layout.

    Neutral state wins once it contains an authoritative marker.  Otherwise a
    legacy Claude layout remains active and fully readable.  An uninstalled
    project receives ``fresh_default`` (neutral by default); this function never
    creates directories or files.
    """

    fs = ProjectFS(Path(target).expanduser())
    neutral = StateLayout.neutral()
    legacy = StateLayout.legacy_claude()
    if _has_state(fs, neutral):
        return neutral
    if _has_state(fs, legacy):
        return legacy
    return fresh_default or neutral


def state_path(
    target: str | Path,
    field: str,
    *,
    layout: StateLayout | None = None,
) -> Path:
    """Return a containment-checked path for one named :class:`StateLayout` field."""

    active = layout or detect_state_layout(target)
    if field not in StateLayout.__dataclass_fields__:  # type: ignore[attr-defined]
        raise ValueError(f"unknown state layout field {field!r}")
    relative = getattr(active, field)
    if not isinstance(relative, str):
        raise ValueError(f"state layout field {field!r} is not a path")
    return ProjectFS(Path(target).expanduser()).path(relative)


__all__ = ["detect_state_layout", "state_path"]
