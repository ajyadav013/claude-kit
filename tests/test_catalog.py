"""Catalog resolution: the data-driven core that turns a Selection into a ResolvedPlan."""

from __future__ import annotations

import pytest

from claude_kit import catalog
from tests._helpers import make_selection


def test_defaults_are_live_and_complete(payload):
    sel = catalog.defaults(payload)
    assert sel.frontend_framework == "react"
    assert sel.frontend_language == "typescript"
    assert sel.backend_language == "python"
    assert sel.backend_framework == "fastapi"
    assert sel.database == "postgres"
    assert sel.profile == "standard"
    assert sel.mcp == []


def test_resolve_worked_example(payload):
    """react + python/fastapi + postgres + standard + mcp=[github] resolves as documented."""
    sel = make_selection(payload, mcp=["github"])
    plan = catalog.resolve(payload, sel)

    # Overlay rules from the three selected stacks (postgres carries a perf overlay too).
    assert set(plan.overlay_rules) == {
        "react-patterns.md",
        "fastapi-patterns.md",
        "postgres-patterns.md",
        "database-performance.md",
    }
    # Postgres overlay agents.
    assert "postgres-specialist" in plan.overlay_agents
    assert "migration-specialist" in plan.overlay_agents
    assert "db-performance-reviewer" in plan.overlay_agents
    assert "mongodb-specialist" not in plan.overlay_agents
    # MCP resolved to a config fragment for github only.
    assert set(plan.mcp_servers) == {"github"}
    # CLAUDE.md context carries the backend commands.
    assert plan.context["backend_test_cmd"] == "pytest"


def test_mongo_selection_swaps_db_overlays(payload):
    plan = catalog.resolve(payload, make_selection(payload, database="mongodb"))
    assert "mongodb-patterns.md" in plan.overlay_rules
    assert "postgres-patterns.md" not in plan.overlay_rules
    assert "mongodb-specialist" in plan.overlay_agents
    assert "postgres-specialist" not in plan.overlay_agents


def test_profiles_are_strict_supersets(payload):
    lean = catalog.resolve(payload, make_selection(payload, profile="lean"))
    standard = catalog.resolve(payload, make_selection(payload, profile="standard"))
    enterprise = catalog.resolve(payload, make_selection(payload, profile="enterprise"))

    assert set(lean.agents) < set(standard.agents) < set(enterprise.agents)
    assert set(lean.skills) < set(standard.skills) <= set(enterprise.skills)
    assert set(lean.gates) < set(standard.gates) < set(enterprise.gates)


def test_every_profile_includes_sdlc_entrypoint(payload):
    for profile in ("lean", "standard", "enterprise"):
        plan = catalog.resolve(payload, make_selection(payload, profile=profile))
        assert "sdlc" in plan.skills, f"{profile} must install the /sdlc entrypoint"
        assert "orchestrator" in plan.agents


def test_planned_stack_is_rejected(payload):
    with pytest.raises(ValueError):
        catalog.resolve(payload, make_selection(payload, frontend_framework="vue"))


def test_unknown_option_is_rejected(payload):
    with pytest.raises(ValueError):
        catalog.resolve(payload, make_selection(payload, database="cassandra"))


def test_list_options_reports_live_and_planned(payload):
    opts = catalog.list_options(payload)
    fe_ids = {f["id"] for f in opts["frontend"]}
    assert {"react", "vue", "svelte"} <= fe_ids
    db_ids = {d["id"] for d in opts["database"]}
    assert {"postgres", "mongodb"} == db_ids
    profile_ids = {p["id"] for p in opts["profiles"]}
    assert {"lean", "standard", "enterprise"} == profile_ids
