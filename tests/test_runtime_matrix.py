"""Cross-runtime matrix invariants for every maturity axis and live stack."""

from __future__ import annotations

import json
import re
from itertools import product

import pytest

from claude_kit import catalog
from claude_kit.canonical_rules import selected_rule_records
from claude_kit.hooks import HOOK_REGISTRY
from claude_kit.models import InstallRequest, Runtime
from claude_kit.runtime_scaffold import compile_runtime_projection
from tests._helpers import make_selection

RUNTIMES = ("claude", "codex", "both")
PROFILES = ("lean", "standard", "enterprise")
SCOPES = ("individual", "team", "organization")


def _assert_logical_roster_is_projected(plan, projection) -> None:
    expected_agents = set(plan.agents) | set(plan.overlay_agents)
    expected_skills = set(plan.skills)
    if plan.org is not None:
        expected_agents.update(plan.org.org_agents)
        expected_skills.update(plan.org.org_skills)

    for provider in projection.providers:
        components = {item.component.uri for item in projection.files_for(provider)}
        assert {f"agent://{name}" for name in expected_agents} <= components
        assert {f"skill://{name}" for name in expected_skills} <= components


def _assert_rule_and_hook_rosters_are_projected(payload, plan, projection) -> None:
    expected_rules = {
        f"rule://{record.spec.id}" for record in selected_rule_records(payload, plan)
    }
    expected_hooks = set(plan.hooks)

    for provider in projection.providers:
        files = projection.files_for(provider)
        rule_components = {
            item.component.uri
            for item in files
            if item.component.uri.startswith("rule://")
        }
        assert rule_components == expected_rules

        hook_path = (
            ".claude/settings.json"
            if provider.value == "claude"
            else ".codex/hooks.json"
        )
        hook_file = next(item for item in files if item.path == hook_path)
        document = json.loads(hook_file.text_content)
        commands = [
            handler["command"]
            for groups in document["hooks"].values()
            for group in groups
            for handler in group["hooks"]
        ]
        assert len(commands) == len(expected_hooks)
        if provider.value == "claude":
            assert {
                HOOK_REGISTRY[hook_id]["entry"]["command"] for hook_id in plan.hooks
            } == set(commands)
        else:
            projected_hooks = {
                match.group(1)
                for command in commands
                if (match := re.search(r"--hook-id ([a-z0-9-]+)(?: |$)", command))
            }
            assert projected_hooks == expected_hooks


@pytest.mark.parametrize(
    ("runtime", "profile", "scope"),
    tuple(product(RUNTIMES, PROFILES, SCOPES)),
)
def test_runtime_profile_scope_matrix_has_one_logical_plan_and_gate_digest(
    payload, runtime, profile, scope
):
    selection = make_selection(payload, profile=profile, scope=scope)
    plan = catalog.resolve(payload, selection)

    projection = compile_runtime_projection(
        payload,
        plan,
        InstallRequest(selection=selection, runtime=runtime),
    )

    assert tuple(provider.value for provider in projection.providers) == (
        Runtime.parse(runtime).providers
    )
    assert catalog.resolve(payload, selection).gates == plan.gates
    assert (
        catalog.resolve(payload, selection).gate_definition_digest
        == plan.gate_definition_digest
    )
    _assert_logical_roster_is_projected(plan, projection)
    _assert_rule_and_hook_rosters_are_projected(payload, plan, projection)


LIVE_STACK_CASES = (
    {
        "frontend_framework": "none",
        "frontend_language": "none",
        "backend_language": "python",
        "backend_framework": "fastapi",
        "database": "none",
    },
    {
        "frontend_framework": "react",
        "frontend_language": "typescript",
        "backend_language": "python",
        "backend_framework": "django",
        "database": "postgres",
    },
    {
        "frontend_framework": "react",
        "frontend_language": "javascript",
        "backend_language": "go",
        "backend_framework": "net-http",
        "database": "mongodb",
    },
    {
        "frontend_framework": "react",
        "frontend_language": "typescript",
        "backend_language": "node",
        "backend_framework": "express",
        "database": "postgres",
    },
    {
        "frontend_framework": "react",
        "frontend_language": "typescript",
        "backend_language": "none",
        "backend_framework": "none",
        "database": "none",
    },
)


@pytest.mark.parametrize("runtime", RUNTIMES)
@pytest.mark.parametrize("stack", LIVE_STACK_CASES)
def test_every_live_stack_is_exercised_in_each_runtime(payload, runtime, stack):
    selection = make_selection(payload, profile="standard", scope="team", **stack)
    plan = catalog.resolve(payload, selection)

    projection = compile_runtime_projection(
        payload,
        plan,
        InstallRequest(selection=selection, runtime=runtime),
    )

    _assert_logical_roster_is_projected(plan, projection)
    _assert_rule_and_hook_rosters_are_projected(payload, plan, projection)
    assert plan.gates
    assert len(plan.gate_definition_digest) == 64


def test_live_stack_cases_track_every_catalog_live_entry(payload):
    options = catalog.list_options(payload)
    covered_frontends = {case["frontend_framework"] for case in LIVE_STACK_CASES}
    covered_backends = {
        (case["backend_language"], case["backend_framework"])
        for case in LIVE_STACK_CASES
    }
    covered_databases = {case["database"] for case in LIVE_STACK_CASES}

    expected_frontends = {
        entry["id"] for entry in options["frontend"] if entry["status"] != "planned"
    }
    expected_backends = {
        (language["id"], framework["id"])
        for language in options["backend"]
        if language["status"] != "planned"
        for framework in language["frameworks"]
        if framework["status"] != "planned"
    }
    expected_databases = {entry["id"] for entry in options["database"]}

    assert covered_frontends == expected_frontends
    assert covered_backends == expected_backends
    assert covered_databases == expected_databases
