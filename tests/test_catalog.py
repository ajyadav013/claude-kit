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
    # React also carries the design-system rule set (0.16.0): design tokens, UX patterns, mobile.
    assert set(plan.overlay_rules) == {
        "react-patterns.md",
        "design-system-compliance.md",
        "ui-design-system.md",
        "ux-patterns.md",
        "mobile-design-guidelines.md",
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


def test_contract_clear_gate_in_standard_and_enterprise_not_lean(payload):
    """The contract-clear gate (API base-branch breaking-change diff) reaches the default standard
    profile (brief #2 P0-1) and enterprise, but not the fast-track lean profile. It self-skips at
    runtime when the stack exposes no API contract surface, so non-API projects are unaffected."""
    lean = catalog.resolve(payload, make_selection(payload, profile="lean"))
    std = catalog.resolve(payload, make_selection(payload, profile="standard"))
    ent = catalog.resolve(payload, make_selection(payload, profile="enterprise"))
    assert "contract-clear" in std.gates
    assert "contract-clear" in ent.gates
    assert "contract-clear" not in lean.gates


def test_sentry_mcp_is_opt_in_and_resolves(payload):
    """sentry (error-monitoring MCP for the incident-responder/observability roles) is opt-in only."""
    # Not installed unless explicitly selected.
    assert "sentry" not in catalog.resolve(payload, make_selection(payload)).mcp_servers
    # Resolves to the hosted OAuth HTTP endpoint when chosen (no credentials generated).
    plan = catalog.resolve(payload, make_selection(payload, mcp=["sentry"]))
    cfg = plan.mcp_servers["sentry"]
    assert cfg["type"] == "http"
    assert cfg["url"] == "https://mcp.sentry.dev/mcp"
    # Surfaced in list-options with the source-available licence flagged in its label.
    labels = {m["id"]: m["label"] for m in catalog.list_options(payload)["mcp"]}
    assert "sentry" in labels
    assert "FSL" in labels["sentry"] or "source-available" in labels["sentry"]


def test_repowise_mcp_is_opt_in_and_resolves(payload):
    """repowise (repowise-inspired codebase intelligence) is an opt-in MCP server, never default."""
    # Not installed unless explicitly selected.
    assert (
        "repowise" not in catalog.resolve(payload, make_selection(payload)).mcp_servers
    )
    # Resolves to its stdio launch config when chosen (path via the documented env placeholder).
    plan = catalog.resolve(payload, make_selection(payload, mcp=["repowise"]))
    cfg = plan.mcp_servers["repowise"]
    assert cfg["command"] == "repowise"
    assert cfg["args"] == ["mcp", "${REPOWISE_PROJECT_ROOT}", "--transport", "stdio"]
    # Surfaced in list-options with the AGPL-3.0 licence flagged in its label.
    labels = {m["id"]: m["label"] for m in catalog.list_options(payload)["mcp"]}
    assert "repowise" in labels
    assert "AGPL" in labels["repowise"]


def test_go_backend_is_live_and_resolves(payload):
    """The Go (stdlib net/http) backend (brief #2 P1-1) is a live, selectable compiled stack:
    its overlay rule + commands resolve, including the new `build` command key."""
    plan = catalog.resolve(
        payload,
        make_selection(payload, backend_language="go", backend_framework="net-http"),
    )
    assert "go-patterns.md" in plan.overlay_rules
    assert "fastapi-patterns.md" not in plan.overlay_rules
    # The compiled-backend `build` command is surfaced in the CLAUDE.md context.
    assert plan.context["backend_build_cmd"] == "go build ./..."
    assert plan.context["backend_test_cmd"] == "go test ./..."
    # It is offered as a live (not planned) backend by list-options.
    go = next(b for b in catalog.list_options(payload)["backend"] if b["id"] == "go")
    assert go["status"] == "live"
    assert any(
        fw["id"] == "net-http" and fw["status"] == "live" for fw in go["frameworks"]
    )


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


def test_minimalism_additions_resolve_in_standard(payload):
    """The ponytail-inspired minimalism layer resolves in standard (and not in lean)."""
    standard = catalog.resolve(payload, make_selection(payload, profile="standard"))
    lean = catalog.resolve(payload, make_selection(payload, profile="lean"))
    assert {"over-engineering-review", "simplification-debt"} <= set(standard.skills)
    assert "load-autonomy" in standard.hooks
    assert "over-engineering-review" not in lean.skills
    assert "load-autonomy" not in lean.hooks


def test_task_tracker_sync_resolves_in_standard(payload):
    """task-tracker-sync (spec-kit /taskstoissues) resolves in standard, not lean; story-planner is wired in standard."""
    standard = catalog.resolve(payload, make_selection(payload, profile="standard"))
    lean = catalog.resolve(payload, make_selection(payload, profile="lean"))
    assert "task-tracker-sync" in standard.skills
    assert "task-tracker-sync" not in lean.skills
    # story-planner ships in the standard agent set (now wired into the workflow as the 1f gate).
    assert "story-planner" in standard.agents


def test_warn_llm_io_resolves_in_standard(payload):
    """warn-llm-io (llm-guard-inspired advisory hook) resolves in standard, not lean."""
    standard = catalog.resolve(payload, make_selection(payload, profile="standard"))
    lean = catalog.resolve(payload, make_selection(payload, profile="lean"))
    assert "warn-llm-io" in standard.hooks
    assert "warn-llm-io" not in lean.hooks


def test_guard_destructive_git_resolves_in_standard(payload):
    """guard-destructive-git (completes the rm-rf/push-main destructive-command guard family)
    resolves in standard, not lean."""
    standard = catalog.resolve(payload, make_selection(payload, profile="standard"))
    lean = catalog.resolve(payload, make_selection(payload, profile="lean"))
    assert "guard-destructive-git" in standard.hooks
    assert "guard-destructive-git" not in lean.hooks


def test_capture_mode_swaps_hooks(payload):
    """The init-time `capture_mode` (catalog/capture.yaml) — NOT the profile — decides which agent-side
    capture hooks install. off -> none; session-end -> capture-learnings; session-end-catchup -> +the
    SessionStart catch-up; per-task -> the Stop variant only. Any non-off mode ensures load-learnings
    (recall) is present, even on lean. Enterprise's `hooks: all` never force-installs all three."""
    CAP = {"capture-learnings", "capture-learnings-catchup", "capture-learnings-stop"}

    def cap(profile, mode):
        plan = catalog.resolve(
            payload, make_selection(payload, profile=profile, capture_mode=mode)
        )
        return [h for h in plan.hooks if h in CAP], ("load-learnings" in plan.hooks)

    # off: no capture hooks; recall only where the profile already provides it.
    assert cap("standard", "off") == ([], True)
    assert cap("lean", "off") == ([], False)

    # exact hook sets per mode; recall always ensured when capture is on (added on lean).
    assert cap("standard", "session-end") == (["capture-learnings"], True)
    assert cap("lean", "session-end") == (["capture-learnings"], True)
    assert set(cap("standard", "session-end-catchup")[0]) == {
        "capture-learnings",
        "capture-learnings-catchup",
    }
    assert cap("standard", "per-task") == (["capture-learnings-stop"], True)

    # enterprise (hooks: all) must NOT install all three — only the chosen mode's set.
    assert cap("enterprise", "session-end")[0] == ["capture-learnings"]

    # unknown mode is rejected.
    with pytest.raises(ValueError):
        catalog.resolve(payload, make_selection(payload, capture_mode="bogus"))


def test_capture_mode_options_and_default(payload):
    """capture_mode_options surfaces the catalog modes for the prompt, with the recommended default."""
    opts = catalog.capture_mode_options(payload)
    ids = {m["id"] for m in opts["modes"]}
    assert ids == {"off", "session-end", "session-end-catchup", "per-task"}
    assert opts["default"] == "session-end-catchup"
    assert catalog.defaults(payload).capture_mode == "session-end-catchup"


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
    assert (
        len(plan.org.org_skills) == 9
    )  # 5 vibe/non-engineer + 4 senior-review (0.15.0)
    assert len(plan.org.org_agents) == 6  # 5 personas + staff-pm-reviewer (0.15.0)
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


def test_accessibility_gate_is_regulated_only(payload):
    """accessibility-clear (brief #2 P1-2) binds only at org `regulated` strictness — not at
    light/standard strictness, and not in a plain (non-org) enterprise plan."""
    regulated = catalog.resolve(
        payload,
        make_selection(
            payload,
            profile="standard",
            scope="organization",
            review_strictness="regulated",
        ),
    )
    light = catalog.resolve(
        payload,
        make_selection(
            payload, profile="standard", scope="organization", review_strictness="light"
        ),
    )
    plain_enterprise = catalog.resolve(
        payload, make_selection(payload, profile="enterprise")
    )
    assert "accessibility-clear" in regulated.gates
    assert "accessibility-clear" not in light.gates
    assert "accessibility-clear" not in plain_enterprise.gates


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
