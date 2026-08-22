"""Skill membership is a decision, not a side effect of creating a directory.

``enterprise`` used to declare ``skills: all``, which made the richest profile the least targeted
one: every directory under ``skills/`` installed regardless of the selected stack, so a Go service
with no frontend received React, FastAPI and Alembic content — and every one of those descriptions
competed in the skill picker. These tests pin the replacement contract:

* no profile may reintroduce ``skills: all``;
* a selection never receives skills for a stack it did not choose;
* every scaffold skill in the payload is still reachable through *some* live selection (nothing
  was orphaned by enumerating), with planned stacks and plugin-only command adapters called out
  explicitly;
* ``lean ⊆ standard ⊆ enterprise`` still holds.
"""

from __future__ import annotations

import pytest
import yaml

from claude_kit import catalog
from tests._helpers import make_selection

#: Skills gated behind a stack, and the marker that says which stack owns them.
_STACK_SKILLS = {
    "react": {
        "frontend-ui-engineering",
        "component-design",
        "ui-ux-design",
        "unit-test",
        "api-integration",
        "manual-test",
        "frontend-repo-architecture",
        "design-system-ops",
        "radix-tailwind-component-patterns",
        "react-hook-form-zod-patterns",
        "tanstack-react-query-patterns",
        "vitest-rtl-msw-patterns",
        "zustand-state-patterns",
        "dockerfile-frontend",
    },
    "fastapi": {
        "fastapi-service-patterns",
        "pydantic-schema-patterns",
        "python-dao-and-database",
        "alembic-migrations",
        "async-python-patterns",
        "configargparse-yaml-env-layering",
        "testing-conventions",
    },
    # Only the Django-owned skills. `testing-conventions` and the two api/repo-architecture
    # skills are shared with the fastapi lane, and a bucket asserts *ownership*, not the
    # whole installed set — see test_enterprise_on_a_go_backend_gets_no_python_or_react_skills.
    "django": {
        "django-service-patterns",
        "django-rest-framework-patterns",
        "django-rest-framework-packages",
        "django-migrations",
        "django-async-patterns",
        "django-react-integration",
    },
    "express": {"node-express-service", "node-objection-knex"},
}

# Generated compatibility adapters expose the four legacy slash commands through plugin skill
# discovery. They are plugin entrypoints, not project skills selected by the scaffold catalog.
_PLUGIN_COMMAND_SKILLS = {
    "ckit-command-abort",
    "ckit-command-init",
    "ckit-command-sdlc",
    "ckit-command-status",
}


def _skills_on_disk(payload):
    return {
        d.name
        for d in (payload / "skills").iterdir()
        if d.is_dir() and (d / "SKILL.md").is_file()
    }


def _resolve(payload, **overrides):
    return catalog.resolve(payload, make_selection(payload, **overrides))


def test_no_profile_declares_skills_all(payload):
    """`all` is fine for the small closed hook registry; for skills it is the bug we removed."""
    profiles = yaml.safe_load(
        (payload / "catalog" / "profiles.yaml").read_text(encoding="utf-8")
    )["profiles"]
    offenders = [name for name, prof in profiles.items() if prof.get("skills") == "all"]
    assert not offenders, (
        f"{offenders} use `skills: all` — enumerate them, and gate stack-specific skills "
        "through catalog/stacks.yaml's `skills:` union instead"
    )


def test_enterprise_on_a_go_backend_gets_no_python_or_react_skills(payload):
    """The motivating case: the richest profile on a stack that uses none of that content."""
    plan = _resolve(
        payload,
        profile="enterprise",
        frontend_framework="none",
        frontend_language="none",
        backend_language="go",
        backend_framework="net-http",
        database="none",
    )
    installed = set(plan.skills)
    for stack, owned in _STACK_SKILLS.items():
        leaked = sorted(owned & installed)
        assert not leaked, (
            f"{stack}-specific skills installed for a Go/no-frontend project: {leaked}"
        )


@pytest.mark.parametrize(
    ("backend_framework", "buckets"),
    [("fastapi", ("react", "fastapi")), ("django", ("react", "django"))],
)
def test_stack_skills_arrive_when_that_stack_is_chosen(
    payload, backend_framework, buckets
):
    """Gating must not mean losing: choosing the stack still brings its skills.

    The two Python frameworks are mutually exclusive selections, so each needs its own plan —
    a single react+fastapi plan cannot prove the django lane is wired.
    """
    plan = _resolve(
        payload,
        profile="enterprise",
        frontend_framework="react",
        backend_language="python",
        backend_framework=backend_framework,
    )
    installed = set(plan.skills)
    for stack in buckets:
        missing = sorted(_STACK_SKILLS[stack] - installed)
        assert not missing, (
            f"{stack} skills missing from a react+{backend_framework} enterprise plan: {missing}"
        )


def test_every_skill_is_reachable_by_some_live_selection(payload):
    """Enumerating must not orphan a skill — an unreachable directory is dead payload weight."""
    reachable: set[str] = set()
    options = catalog.list_options(payload)
    live_backends = [
        (b["id"], fw["id"])
        for b in options["backend"]
        if b["status"] != "planned"
        for fw in b["frameworks"]
        if fw["status"] != "planned"
    ]
    live_frontends = [f["id"] for f in options["frontend"] if f["status"] != "planned"]

    for profile in ("lean", "standard", "enterprise"):
        for frontend in live_frontends:
            for backend_language, backend_framework in live_backends:
                for database in [d["id"] for d in options["database"]]:
                    for scope in ("team", "organization"):
                        plan = _resolve(
                            payload,
                            profile=profile,
                            frontend_framework=frontend,
                            frontend_language=(
                                "none" if frontend == "none" else "typescript"
                            ),
                            backend_language=backend_language,
                            backend_framework=backend_framework,
                            database=database,
                            scope=scope,
                        )
                        reachable |= set(plan.skills)

    unreachable = _skills_on_disk(payload) - reachable
    # Planned-stack skills remain dormant until that stack ships. The generated command adapters
    # are intentionally plugin-only and must not be added to every scaffold just to satisfy this
    # catalog reachability invariant.
    intentionally_unselected = _STACK_SKILLS["express"] | _PLUGIN_COMMAND_SKILLS
    assert unreachable <= intentionally_unselected, (
        "skills no live selection can install: "
        f"{sorted(unreachable - intentionally_unselected)}"
    )


def test_profiles_remain_strict_supersets_on_one_stack(payload):
    """lean ⊆ standard ⊆ enterprise, holding the stack constant so gating cannot skew it."""
    sets = {
        profile: set(_resolve(payload, profile=profile).skills)
        for profile in ("lean", "standard", "enterprise")
    }
    assert sets["lean"] < sets["standard"], sorted(sets["lean"] - sets["standard"])
    assert sets["standard"] < sets["enterprise"], sorted(
        sets["standard"] - sets["enterprise"]
    )


def test_enterprise_no_longer_installs_the_whole_payload(payload):
    """A targeted selection should install meaningfully less than everything on disk."""
    plan = _resolve(
        payload,
        profile="enterprise",
        frontend_framework="none",
        frontend_language="none",
        backend_language="go",
        backend_framework="net-http",
        database="none",
    )
    on_disk = len(_skills_on_disk(payload))
    assert len(plan.skills) < on_disk, (
        "a no-frontend, no-database Go project still installs every skill in the payload"
    )
