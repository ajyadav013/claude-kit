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


def live_matrix(payload: Path) -> list[dict[str, str]]:
    """Every LIVE frontend × backend(framework) × database × profile × scope as Selection overrides.

    Driven off :func:`catalog.list_options` so a newly-promoted stack (e.g. the Go backend) auto-joins
    the sweep with no test edit. Used by the self-test matrix to assert install+validate across the
    whole installable surface, where silent breakage otherwise hides.
    """
    opts = catalog.list_options(payload)
    frontends = [f for f in opts["frontend"] if f["status"] != "planned"]
    backends = [
        (b["id"], fw["id"])
        for b in opts["backend"]
        if b["status"] != "planned"
        for fw in b["frameworks"]
        if fw["status"] != "planned"
    ]
    databases = [d["id"] for d in opts["database"]]
    profiles = [p["id"] for p in opts["profiles"]]
    return [
        {
            "frontend_framework": fe["id"],
            "frontend_language": fe["default_language"] or "typescript",
            "backend_language": be_lang,
            "backend_framework": be_fw,
            "database": db,
            "profile": profile,
            "scope": scope,
        }
        for fe in frontends
        for (be_lang, be_fw) in backends
        for db in databases
        for profile in profiles
        for scope in ("team", "organization")
    ]
