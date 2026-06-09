"""Installer behavior: full tree, no-Docker mandate, profile subsets, MCP gating, idempotency."""

from __future__ import annotations

import json

from claude_kit.models import InitOptions
from tests._helpers import install


def test_install_writes_the_full_tree(tmp_path, payload):
    install(payload, tmp_path)
    claude = tmp_path / ".claude"
    assert (tmp_path / "CLAUDE.md").is_file()
    assert (tmp_path / "README.claude-sdlc.md").is_file()
    for sub in ("rules", "agents", "skills", "hooks", "templates", "config"):
        assert (claude / sub).is_dir(), f"missing .claude/{sub}/"
    assert (claude / "skills" / "sdlc" / "SKILL.md").is_file()
    assert (claude / "config" / "init-options.json").is_file()
    # Runtime dirs exist but are seeded empty.
    assert (claude / "state" / ".gitkeep").is_file()
    assert (claude / "tmp" / ".gitkeep").is_file()


def test_agent_operation_rules_ship_in_every_profile(tmp_path, payload):
    """The agentic-patterns rules are core (not profile-gated) — present even in lean."""
    expected = {
        "reasoning-techniques.md",
        "agent-guardrails.md",
        "agent-resilience.md",
        "goal-setting-and-monitoring.md",
        "human-in-the-loop.md",
    }
    for profile in ("lean", "standard", "enterprise"):
        target = tmp_path / profile
        install(payload, target, profile=profile)
        rules = {p.name for p in (target / ".claude" / "rules").glob("*.md")}
        assert expected <= rules, f"{profile} missing rules: {expected - rules}"


def test_model_tiers_rule_ships_in_every_profile(tmp_path, payload):
    """model-tiers.md is a core rule — present even in lean (not profile-gated)."""
    for profile in ("lean", "standard", "enterprise"):
        target = tmp_path / profile
        install(payload, target, profile=profile)
        assert (target / ".claude" / "rules" / "model-tiers.md").is_file(), (
            f"{profile} missing model-tiers.md"
        )


def test_ops_skills_gated_by_profile(tmp_path, payload):
    """incident-postmortem + load-testing arrive in standard (not lean), persist in enterprise."""
    ops = {"incident-postmortem", "load-testing"}
    lean = tmp_path / "lean"
    standard = tmp_path / "standard"
    enterprise = tmp_path / "enterprise"
    install(payload, lean, profile="lean")
    install(payload, standard, profile="standard")
    install(payload, enterprise, profile="enterprise")

    def skills(target):
        return {p.name for p in (target / ".claude" / "skills").iterdir() if p.is_dir()}

    assert not (ops & skills(lean)), "ops skills must not ship in lean"
    assert ops <= skills(standard), "ops skills must ship in standard"
    assert ops <= skills(enterprise), "ops skills must ship in enterprise"


def test_incident_responder_is_enterprise_only(tmp_path, payload):
    """The incident-responder agent is gated to the enterprise profile."""
    for profile, present in (
        ("lean", False),
        ("standard", False),
        ("enterprise", True),
    ):
        target = tmp_path / profile
        install(payload, target, profile=profile)
        exists = (target / ".claude" / "agents" / "incident-responder.md").is_file()
        assert exists is present, f"{profile}: incident-responder present={exists}"


def test_guard_commit_secrets_hook_in_standard(tmp_path, payload):
    """The commit-time secret guard installs its script and wires into settings.json (standard+)."""
    target = tmp_path / "standard"
    install(payload, target, profile="standard")
    script = target / ".claude" / "hooks" / "guard-secrets.sh"
    assert script.is_file(), "guard-secrets.sh not copied"
    settings = json.loads(
        (target / ".claude" / "settings.json").read_text(encoding="utf-8")
    )
    commands = [
        h["command"]
        for block in settings["hooks"].get("PreToolUse", [])
        if block["matcher"] == "Bash"
        for h in block["hooks"]
    ]
    assert any("guard-secrets.sh" in c for c in commands), (
        "commit-secret hook not wired"
    )


def test_postgres_performance_overlays_install(tmp_path, payload):
    """Selecting PostgreSQL pulls in the perf overlay rule + reviewer agent; Mongo does not."""
    pg = tmp_path / "pg"
    mg = tmp_path / "mg"
    install(payload, pg, database="postgres")
    install(payload, mg, database="mongodb")
    assert (pg / ".claude" / "rules" / "database-performance.md").is_file()
    assert (pg / ".claude" / "agents" / "db-performance-reviewer.md").is_file()
    assert not (mg / ".claude" / "rules" / "database-performance.md").exists()
    assert not (mg / ".claude" / "agents" / "db-performance-reviewer.md").exists()


def test_no_docker_anywhere(tmp_path, payload):
    """The acceptance criterion: a scaffolded config contains no Docker artifacts."""
    install(payload, tmp_path)
    offenders = [
        p.name
        for p in tmp_path.rglob("*")
        if p.is_file()
        and (
            p.name == "Dockerfile"
            or p.name.startswith("docker-compose")
            or p.name == ".dockerignore"
        )
    ]
    assert offenders == [], f"unexpected Docker files: {offenders}"


def test_init_options_round_trips_and_records_files(tmp_path, payload):
    install(payload, tmp_path)
    data = json.loads(
        (tmp_path / ".claude" / "config" / "init-options.json").read_text(
            encoding="utf-8"
        )
    )
    options = InitOptions.from_dict(data)
    assert options.schema_version == 1
    assert options.selection.database == "postgres"
    assert options.files, "no files recorded"
    owners = {r.owner for r in options.files}
    assert owners <= {"kit", "overlay", "user-editable"}
    # CLAUDE.md is user-editable; an overlay rule is overlay-owned.
    by_path = {r.path: r.owner for r in options.files}
    assert by_path["CLAUDE.md"] == "user-editable"
    assert by_path[".claude/rules/react-patterns.md"] == "overlay"


def test_custom_path_does_not_touch_cwd(tmp_path, payload, monkeypatch):
    work = tmp_path / "elsewhere"
    work.mkdir()
    monkeypatch.chdir(work)
    target = tmp_path / "project"
    install(payload, target)
    assert (target / ".claude").is_dir()
    assert not (work / ".claude").exists()


def test_postgres_vs_mongo_overlays_are_exclusive(tmp_path, payload):
    pg = tmp_path / "pg"
    mg = tmp_path / "mg"
    install(payload, pg, database="postgres")
    install(payload, mg, database="mongodb")
    pg_rules = {p.name for p in (pg / ".claude" / "rules").glob("*.md")}
    mg_rules = {p.name for p in (mg / ".claude" / "rules").glob("*.md")}
    assert "postgres-patterns.md" in pg_rules and "mongodb-patterns.md" not in pg_rules
    assert "mongodb-patterns.md" in mg_rules and "postgres-patterns.md" not in mg_rules
    assert (pg / ".claude" / "agents" / "postgres-specialist.md").is_file()
    assert (mg / ".claude" / "agents" / "mongodb-specialist.md").is_file()


def test_profiles_install_strict_subsets(tmp_path, payload):
    counts = {}
    for profile in ("lean", "standard", "enterprise"):
        target = tmp_path / profile
        install(payload, target, profile=profile)
        agents = {p.name for p in (target / ".claude" / "agents").glob("*.md")}
        skills = {
            p.name for p in (target / ".claude" / "skills").iterdir() if p.is_dir()
        }
        counts[profile] = (agents, skills)
    assert counts["lean"][0] < counts["standard"][0] < counts["enterprise"][0]
    assert counts["lean"][1] < counts["standard"][1] <= counts["enterprise"][1]


def test_mcp_written_only_when_selected(tmp_path, payload):
    none = tmp_path / "none"
    with_mcp = tmp_path / "with"
    install(payload, none)
    install(payload, with_mcp, mcp=["github"])
    assert not (none / ".mcp.json").exists()
    doc = json.loads((with_mcp / ".mcp.json").read_text(encoding="utf-8"))
    assert set(doc["mcpServers"]) == {"github"}


def test_gitignore_is_selective(tmp_path, payload):
    install(payload, tmp_path)
    gi = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    for entry in (".claude/state/", ".claude/tmp/", ".claude/settings.local.json"):
        assert entry in gi
    # The whole .claude/ must NOT be blanket-ignored (we commit the config).
    assert "\n.claude/\n" not in "\n" + gi


def test_reinstall_is_idempotent(tmp_path, payload):
    """Re-running install produces identical recorded checksums (deterministic config)."""
    install(payload, tmp_path)
    first = (tmp_path / ".claude" / "config" / "init-options.json").read_text(
        encoding="utf-8"
    )
    install(
        payload,
        tmp_path,
    )  # second pass over the same tree
    second = (tmp_path / ".claude" / "config" / "init-options.json").read_text(
        encoding="utf-8"
    )
    assert first == second
