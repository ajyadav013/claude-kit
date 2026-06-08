"""Reusable factory helpers for the test suite (kept out of conftest to avoid double-import)."""

from __future__ import annotations

from pathlib import Path

from claude_kit import catalog, scaffold
from claude_kit.models import ResolvedPlan, Selection


def make_selection(payload: Path, **overrides: object) -> Selection:
    """Return the default :class:`Selection` with the given fields overridden."""
    sel = catalog.defaults(payload)
    for key, value in overrides.items():
        setattr(sel, key, value)
    return sel


def install(payload: Path, target: Path, **overrides: object) -> ResolvedPlan:
    """Resolve a plan (defaults + overrides) and install it into ``target``; return the plan."""
    plan = catalog.resolve(payload, make_selection(payload, **overrides))
    scaffold.install_sdlc(payload, target, plan, force=False, log=[])
    return plan
