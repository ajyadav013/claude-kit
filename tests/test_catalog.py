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


# --- Organization layer (scope-gated) ------------------------------------------------------------


def test_team_scope_resolves_without_org(payload):
    """Default scope (team) leaves the plan org-free — existing installs are unchanged."""
    plan = catalog.resolve(payload, make_selection(payload))  # scope defaults to "team"
    assert plan.org is None


def test_org_scope_builds_orgplan(payload):
    """Organization scope resolves an OrgPlan with all 7 packs + the new org components."""
    plan = catalog.resolve(
        payload, make_selection(payload, profile="enterprise", scope="organization")
    )
    assert plan.org is not None
    assert len(plan.org.packs) == 7
    assert len(plan.org.org_skills) == 5
    assert len(plan.org.org_agents) == 5
    assert len(plan.org.org_rules) == 10
    # The persona agents are NOT folded into the profile agent set (they install via the org overlay).
    assert "pm-copilot" not in plan.agents


def test_org_enterprise_controlled_unions_hooks_and_gates(payload):
    """enterprise-controlled autonomy + regulated strictness add hooks, the classifier, and gates."""
    plan = catalog.resolve(
        payload,
        make_selection(
            payload,
            profile="enterprise",
            scope="organization",
            autonomy="enterprise-controlled",
            review_strictness="regulated",
        ),
    )
    assert "audit-log" in plan.hooks
    assert "warn-sensitive-files" in plan.hooks
    assert "risk-classifier" in plan.agents
    assert {"security-clear", "acceptance"} <= set(plan.gates)


def test_org_assisted_adds_no_autonomy_hooks(payload):
    """The default autonomy (assisted) enables no extra hooks beyond the profile's."""
    team = catalog.resolve(payload, make_selection(payload, profile="standard"))
    org = catalog.resolve(
        payload,
        make_selection(
            payload, profile="standard", scope="organization", autonomy="assisted"
        ),
    )
    # No autonomy hooks were unioned in (gates/hook set unchanged from the team plan).
    assert set(org.hooks) == set(team.hooks)
    assert "audit-log" not in org.hooks


def test_org_packs_false_skips_pack_and_skill_content(payload):
    """Declining packs yields an OrgPlan with no packs/skills (autonomy rules still apply)."""
    plan = catalog.resolve(
        payload,
        make_selection(
            payload, profile="enterprise", scope="organization", org_packs=False
        ),
    )
    assert plan.org is not None
    assert plan.org.packs == []
    assert plan.org.org_skills == []


def test_unknown_autonomy_is_rejected(payload):
    with pytest.raises(ValueError):
        catalog.resolve(
            payload,
            make_selection(payload, scope="organization", autonomy="full-self-drive"),
        )


def test_selection_from_dict_tolerates_missing_org_fields(payload):
    """Back-compat: a pre-0.6.0 selection snapshot (no org keys) loads with safe defaults."""
    from claude_kit.models import Selection

    legacy = {
        "frontend_framework": "react",
        "frontend_language": "typescript",
        "backend_language": "python",
        "backend_framework": "fastapi",
        "database": "postgres",
        "profile": "standard",
        "mcp": [],
    }
    sel = Selection.from_dict(legacy)
    assert sel.scope == "team"
    assert sel.autonomy == "assisted"
    assert sel.review_strictness == "standard"
    assert sel.org_packs is True
    assert sel.teams == []
