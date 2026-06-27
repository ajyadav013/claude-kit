"""Installer behavior: full tree, no-Docker mandate, profile subsets, MCP gating, idempotency."""

from __future__ import annotations

import json

from claude_kit import validator
from claude_kit.models import InitOptions
from tests._helpers import install, live_matrix


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
        "evals.md",
        "tool-design.md",
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


def test_self_test_matrix_resolves_installs_and_validates(tmp_path, payload):
    """Brief #2 P2-5: sweep EVERY live frontend × backend × database × profile × scope. Each combo
    must resolve, install, validate green, carry gates, and stay Docker-free — the matrix where
    silent breakage hides. New live stacks (e.g. the Go backend) auto-join via catalog.list_options."""
    combos = live_matrix(payload)
    # 1 frontend × 2 live backends (fastapi, go) × 2 dbs × 3 profiles × 2 scopes = 24.
    assert len(combos) >= 24, (
        f"matrix too small ({len(combos)}) — a live stack may be missing"
    )
    for i, overrides in enumerate(combos):
        target = tmp_path / f"combo{i}"
        plan = install(payload, target, **overrides)
        ok, messages = validator.validate(target)
        assert ok, f"validate failed for {overrides}:\n" + "\n".join(messages)
        assert plan.gates, f"no gates resolved for {overrides}"
        offenders = [
            p.name
            for p in (target / ".claude").rglob("*")
            if p.is_file()
            and (p.name == "Dockerfile" or p.name.startswith("docker-compose"))
        ]
        assert offenders == [], f"Docker artifact for {overrides}: {offenders}"


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


def test_sentry_mcp_written_when_selected(tmp_path, payload):
    """The opt-in sentry server lands in .mcp.json as the hosted OAuth HTTP endpoint when selected."""
    target = tmp_path / "sentry"
    install(payload, target, mcp=["sentry"])
    doc = json.loads((target / ".mcp.json").read_text(encoding="utf-8"))
    assert "sentry" in doc["mcpServers"]
    assert doc["mcpServers"]["sentry"]["type"] == "http"
    assert doc["mcpServers"]["sentry"]["url"] == "https://mcp.sentry.dev/mcp"


def test_repowise_mcp_written_when_selected(tmp_path, payload):
    """The opt-in repowise server lands in .mcp.json with its repo-path placeholder when selected."""
    target = tmp_path / "rw"
    install(payload, target, mcp=["repowise"])
    doc = json.loads((target / ".mcp.json").read_text(encoding="utf-8"))
    assert "repowise" in doc["mcpServers"]
    assert doc["mcpServers"]["repowise"]["args"] == [
        "mcp",
        "${REPOWISE_PROJECT_ROOT}",
        "--transport",
        "stdio",
    ]


def test_gitignore_is_selective(tmp_path, payload):
    install(payload, tmp_path)
    gi = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    for entry in (".claude/state/", ".claude/tmp/", ".claude/settings.local.json"):
        assert entry in gi
    # The whole .claude/ must NOT be blanket-ignored (we commit the config).
    assert "\n.claude/\n" not in "\n" + gi


def test_gitignore_ignores_upgrade_backups(tmp_path, payload):
    """`claude-kit upgrade` writes .claude-kit.bak-N/ dirs and *.claude-kit sidecars — never commit
    them. A fresh scaffold's .gitignore must list both so `git add -A` skips them."""
    install(payload, tmp_path)
    gi = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    for entry in (".claude-kit.bak-*/", "*.claude-kit"):
        assert entry in gi, f"managed .gitignore must ignore upgrade artifact {entry!r}"


def test_core_org_rules_ship_in_every_profile(tmp_path, payload):
    """autonomy-levels + risk-classification are core rules — present even in lean, team scope."""
    expected = {"autonomy-levels.md", "risk-classification.md"}
    for profile in ("lean", "standard", "enterprise"):
        target = tmp_path / profile
        install(payload, target, profile=profile)
        rules = {p.name for p in (target / ".claude" / "rules").glob("*.md")}
        assert expected <= rules, (
            f"{profile} missing core org rules: {expected - rules}"
        )


def test_new_core_skills_gated_by_profile(tmp_path, payload):
    """threat-model + accessibility-review arrive in standard (not lean)."""
    new_skills = {"threat-model", "accessibility-review"}
    lean = tmp_path / "lean"
    standard = tmp_path / "standard"
    install(payload, lean, profile="lean")
    install(payload, standard, profile="standard")

    def skills(target):
        return {p.name for p in (target / ".claude" / "skills").iterdir() if p.is_dir()}

    assert not (new_skills & skills(lean)), "new core skills must not ship in lean"
    assert new_skills <= skills(standard), "new core skills must ship in standard"


def test_risk_classifier_is_enterprise_only(tmp_path, payload):
    """The risk-classifier agent is gated to the enterprise profile (team scope)."""
    for profile, present in (
        ("lean", False),
        ("standard", False),
        ("enterprise", True),
    ):
        target = tmp_path / profile
        install(payload, target, profile=profile)
        exists = (target / ".claude" / "agents" / "risk-classifier.md").is_file()
        assert exists is present, f"{profile}: risk-classifier present={exists}"


def test_team_scope_installs_no_org_overlay(tmp_path, payload):
    """Default (team) scope: no org-packs/, no persona agents, no org policy rules."""
    target = tmp_path / "team"
    install(payload, target, profile="enterprise")  # scope defaults to team
    assert not (target / ".claude" / "org-packs").exists()
    assert not (target / ".claude" / "agents" / "pm-copilot.md").exists()
    assert not (target / ".claude" / "rules" / "secrets-policy.md").exists()


def test_org_scope_installs_packs_personas_and_rules(tmp_path, payload):
    """Organization scope writes the 7 pack manifests, 5 personas, 5 org skills, and org rules."""
    target = tmp_path / "org"
    install(payload, target, profile="enterprise", scope="organization")
    packs = target / ".claude" / "org-packs"
    assert packs.is_dir()
    assert (packs / "README.md").is_file()
    manifests = sorted(d.name for d in packs.iterdir() if (d / "pack.yaml").is_file())
    assert len(manifests) == 7, f"expected 7 pack manifests, got {manifests}"

    personas = {
        "pm-copilot",
        "founder-prototype-agent",
        "support-ticket-engineer",
        "data-workflow-agent",
        "internal-tools-builder",
    }
    agents = {p.stem for p in (target / ".claude" / "agents").glob("*.md")}
    assert personas <= agents, f"missing personas: {personas - agents}"

    org_skills = {
        "feature-from-idea",
        "prototype-to-production",
        "customer-issue-to-fix",
        "prompt-to-safe-task",
        "repo-onboarding",
    }
    skills = {p.name for p in (target / ".claude" / "skills").iterdir() if p.is_dir()}
    assert org_skills <= skills, f"missing org skills: {org_skills - skills}"

    assert (target / ".claude" / "rules" / "secrets-policy.md").is_file()
    assert (target / ".claude" / "rules" / "ai-working-agreement.md").is_file()


def test_org_packs_false_skips_packs_but_keeps_autonomy(tmp_path, payload):
    """Declining packs: no org-packs/ tree, but the org-core autonomy rule still ships."""
    target = tmp_path / "org-nopacks"
    install(
        payload, target, profile="enterprise", scope="organization", org_packs=False
    )
    assert not (target / ".claude" / "org-packs").exists()
    assert not (target / ".claude" / "agents" / "pm-copilot.md").exists()
    assert (target / ".claude" / "rules" / "autonomy-levels.md").is_file()


def test_org_enterprise_controlled_wires_audit_log_into_settings(tmp_path, payload):
    """enterprise-controlled autonomy copies audit-log.sh and wires it into settings.json."""
    target = tmp_path / "org-strict"
    install(
        payload,
        target,
        profile="enterprise",
        scope="organization",
        autonomy="enterprise-controlled",
    )
    assert (target / ".claude" / "hooks" / "audit-log.sh").is_file()
    settings = json.loads(
        (target / ".claude" / "settings.json").read_text(encoding="utf-8")
    )
    commands = [
        h["command"]
        for block in settings["hooks"].get("PostToolUse", [])
        for h in block["hooks"]
    ]
    assert any("audit-log.sh" in c for c in commands), (
        "audit-log hook not wired into settings"
    )


def test_org_selection_recorded_in_snapshots(tmp_path, payload):
    """The org selection round-trips: scope into init-options, the OrgPlan into the catalog snapshot."""
    import yaml

    target = tmp_path / "org"
    install(payload, target, profile="enterprise", scope="organization")
    options = json.loads(
        (target / ".claude" / "config" / "init-options.json").read_text(
            encoding="utf-8"
        )
    )
    assert options["selection"]["scope"] == "organization"
    snapshot = yaml.safe_load(
        (target / ".claude" / "config" / "stack-catalog.snapshot.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert snapshot["org"] is not None
    assert len(snapshot["org"]["packs"]) == 7


def test_minimalism_skills_gated_by_profile(tmp_path, payload):
    """over-engineering-review + simplification-debt arrive in standard (not lean), persist in enterprise."""
    new = {"over-engineering-review", "simplification-debt"}
    lean = tmp_path / "lean"
    standard = tmp_path / "standard"
    enterprise = tmp_path / "enterprise"
    install(payload, lean, profile="lean")
    install(payload, standard, profile="standard")
    install(payload, enterprise, profile="enterprise")

    def skills(target):
        return {p.name for p in (target / ".claude" / "skills").iterdir() if p.is_dir()}

    assert not (new & skills(lean)), "minimalism skills must not ship in lean"
    assert new <= skills(standard), "minimalism skills must ship in standard"
    assert new <= skills(enterprise), "minimalism skills must ship in enterprise"


def test_load_autonomy_hook_in_standard_not_lean(tmp_path, payload):
    """load-autonomy ships its script + wires into SessionStart settings in standard, absent in lean."""
    lean = tmp_path / "lean"
    standard = tmp_path / "standard"
    install(payload, lean, profile="lean")
    install(payload, standard, profile="standard")
    assert not (lean / ".claude" / "hooks" / "load-autonomy.sh").exists()
    assert (standard / ".claude" / "hooks" / "load-autonomy.sh").is_file()
    settings = json.loads(
        (standard / ".claude" / "settings.json").read_text(encoding="utf-8")
    )
    commands = [
        h["command"]
        for block in settings["hooks"].get("SessionStart", [])
        for h in block["hooks"]
    ]
    assert any("load-autonomy.sh" in c for c in commands), (
        "load-autonomy hook not wired into SessionStart"
    )


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


def test_task_tracker_sync_skill_gated_by_profile(tmp_path, payload):
    """task-tracker-sync (spec-kit /taskstoissues) arrives in standard, not lean, persists in enterprise."""
    lean = tmp_path / "lean"
    standard = tmp_path / "standard"
    enterprise = tmp_path / "enterprise"
    install(payload, lean, profile="lean")
    install(payload, standard, profile="standard")
    install(payload, enterprise, profile="enterprise")

    def skills(target):
        return {p.name for p in (target / ".claude" / "skills").iterdir() if p.is_dir()}

    assert "task-tracker-sync" not in skills(lean), "must not ship in lean"
    assert "task-tracker-sync" in skills(standard), "must ship in standard"
    assert "task-tracker-sync" in skills(enterprise), "must ship in enterprise"


def test_story_planner_is_wired_into_installed_workflow(tmp_path, payload):
    """The (previously orphaned) story-planner coverage gate is wired into the installed pipeline."""
    target = tmp_path / "standard"
    install(payload, target, profile="standard")
    # The agent itself installs in standard.
    assert (target / ".claude" / "agents" / "story-planner.md").is_file()
    # ...and is now referenced by both the workflow rule (stage 1f) and the orchestrator.
    workflow = (target / ".claude" / "rules" / "mandatory-workflow.md").read_text(
        encoding="utf-8"
    )
    assert "1f" in workflow and "Story Planner" in workflow
    orchestrator = (target / ".claude" / "agents" / "orchestrator.md").read_text(
        encoding="utf-8"
    )
    assert "story-planner" in orchestrator


def test_feature_spec_template_has_requirement_ids_and_assumptions(tmp_path, payload):
    """feature-spec.md gained stable requirement ids + an Assumptions section (concrete coverage gate)."""
    target = tmp_path / "standard"
    install(payload, target, profile="standard")
    matches = list((target / ".claude").rglob("feature-spec.md"))
    assert matches, "feature-spec.md artifact template not installed"
    spec = matches[0].read_text(encoding="utf-8")
    assert "**R1**" in spec, "requirement ids missing"
    assert "## Assumptions" in spec, "Assumptions section missing"


def test_warn_llm_io_hook_in_standard_not_lean(tmp_path, payload):
    """warn-llm-io (llm-guard-inspired, advisory) ships + wires into PreToolUse(Edit|Write) in standard; absent in lean."""
    lean = tmp_path / "lean"
    standard = tmp_path / "standard"
    install(payload, lean, profile="lean")
    install(payload, standard, profile="standard")
    assert not (lean / ".claude" / "hooks" / "warn-llm-io.sh").exists()
    assert (standard / ".claude" / "hooks" / "warn-llm-io.sh").is_file()
    settings = json.loads(
        (standard / ".claude" / "settings.json").read_text(encoding="utf-8")
    )
    commands = [
        h["command"]
        for block in settings["hooks"].get("PreToolUse", [])
        if block["matcher"] == "Edit|Write"
        for h in block["hooks"]
    ]
    assert any("warn-llm-io.sh" in c for c in commands), (
        "warn-llm-io hook not wired into PreToolUse(Edit|Write)"
    )


def test_capture_mode_wiring(tmp_path, payload):
    """The init-time `capture_mode` decides the agent-side capture wiring; the single
    capture-learnings.sh is dispatched by an arg (end/stop/catchup). off installs nothing (script not
    even copied); session-end -> SessionEnd `end`; session-end-catchup -> +SessionStart `catchup`;
    per-task -> Stop `stop` (no SessionEnd). load-learnings (recall) is present whenever capture is on."""

    def wiring(mode):
        d = tmp_path / f"m-{mode}"
        install(payload, d, capture_mode=mode)
        s = json.loads((d / ".claude" / "settings.json").read_text(encoding="utf-8"))
        cmds = {
            ev: [h["command"] for blk in s["hooks"].get(ev, []) for h in blk["hooks"]]
            for ev in ("SessionStart", "Stop", "SessionEnd")
        }
        has_script = (d / ".claude" / "hooks" / "capture-learnings.sh").is_file()
        return cmds, has_script

    def fires(cmds, event, arg):
        return any(
            "capture-learnings.sh" in c and c.rstrip().endswith(arg)
            for c in cmds[event]
        )

    # off: capture script not copied, no capture wiring anywhere.
    c_off, has_off = wiring("off")
    assert not has_off
    assert not any("capture-learnings.sh" in c for ev in c_off for c in c_off[ev])

    # session-end: SessionEnd `end`; nothing on SessionStart/Stop.
    c_se, has_se = wiring("session-end")
    assert has_se
    assert fires(c_se, "SessionEnd", "end")
    assert not any("capture-learnings.sh" in c for c in c_se["SessionStart"])

    # session-end-catchup (default): SessionEnd `end` + SessionStart `catchup`.
    c_sec, _ = wiring("session-end-catchup")
    assert fires(c_sec, "SessionEnd", "end")
    assert fires(c_sec, "SessionStart", "catchup")

    # per-task: Stop `stop`; no SessionEnd capture.
    c_pt, _ = wiring("per-task")
    assert fires(c_pt, "Stop", "stop")
    assert not any("capture-learnings.sh" in c for c in c_pt["SessionEnd"])


def test_capture_learnings_spawn_behaviour(tmp_path, payload):
    """Behaviour of the detached, NON-blocking background spawn (fire-and-forget). A FAKE `claude` on
    PATH appends to a log so no real LLM runs; its growth proves a spawn fired. Covers `end` (spawn on
    edits, silent on no-edits / opt-out / missing transcript) and `catchup` (spawn for a stale,
    unmarked, edited prior session; idempotent via the done-marker). The hook always exits 0 and writes
    nothing to stdout."""
    import os
    import shutil
    import subprocess
    import time
    import uuid

    if not shutil.which("jq"):
        return

    standard = tmp_path / "standard"
    install(payload, standard, capture_mode="session-end-catchup")
    script = standard / ".claude" / "hooks" / "capture-learnings.sh"
    assert script.is_file(), "capture-learnings.sh not copied"

    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    fake = fakebin / "claude"
    spawnlog = tmp_path / "spawns.log"
    spawnlog.write_text("", encoding="utf-8")
    fake.write_text(
        '#!/usr/bin/env bash\nprintf "x\\n" >> "$CK_SPAWN_LOG"\n', encoding="utf-8"
    )
    fake.chmod(0o755)

    cktmp = tmp_path / "cktmp"
    cktmp.mkdir()
    proj = tmp_path / "proj"
    (proj / ".claude" / "agent-memory" / "gotchas").mkdir(parents=True)
    sessions = tmp_path / "sessions"
    sessions.mkdir()

    edit = (
        '{"type":"assistant","message":{"role":"assistant","content":'
        '[{"type":"tool_use","name":"Edit","input":{"file_path":"/x/y.py"}}]}}\n'
    )
    text = (
        '{"type":"assistant","message":{"role":"assistant","content":'
        '[{"type":"text","text":"hi"}]}}\n'
    )

    def count():
        return len(spawnlog.read_text(encoding="utf-8").splitlines())

    def run(mode, transcript, extra_env=None, timeout=2.5):
        """Run the hook in `mode`; return True if a (fake) spawn appeared within `timeout`."""
        env = dict(os.environ)
        env["PATH"] = f"{fakebin}{os.pathsep}{env['PATH']}"
        env["CK_SPAWN_LOG"] = str(spawnlog)
        env["TMPDIR"] = str(cktmp)
        if extra_env:
            env.update(extra_env)
        before = count()
        proc = subprocess.run(
            ["bash", str(script), mode],
            input=json.dumps(
                {
                    "transcript_path": transcript,
                    "session_id": uuid.uuid4().hex,
                    "cwd": str(proj),
                }
            ),
            text=True,
            capture_output=True,
            env=env,
        )
        assert proc.returncode == 0, "hook must always exit 0 (never block)"
        assert proc.stdout.strip() == "", "hook must write nothing to stdout"
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if count() > before:
                return True
            time.sleep(0.2)
        return count() > before

    # --- end ---
    edited = sessions / "s-edit.jsonl"
    edited.write_text(edit, encoding="utf-8")
    talk = sessions / "s-talk.jsonl"
    talk.write_text(text, encoding="utf-8")
    assert run("end", str(edited), timeout=10.0), (
        "end must spawn when the session edited files"
    )
    assert not run("end", str(talk)), "end must not spawn with no edits"
    assert not run("end", str(edited), {"CLAUDE_KIT_NO_AUTOCAPTURE": "1"}), (
        "opt-out/recursion guard must suppress the spawn"
    )
    assert not run("end", str(sessions / "nope.jsonl")), (
        "missing transcript degrades silently"
    )

    # --- catchup: a stale, unmarked, edited prior session is captured on next launch ---
    abrupt = sessions / "s-abrupt.jsonl"
    abrupt.write_text(edit, encoding="utf-8")
    old = (
        time.time() - 3600
    )  # 1h ago: older than the 2-min freshness window, within 7 days
    os.utime(abrupt, (old, old))
    current = sessions / "s-current.jsonl"
    current.write_text(text, encoding="utf-8")
    assert run("catchup", str(current), timeout=10.0), (
        "catchup must spawn for a stale, unmarked, edited prior session"
    )
    assert not run("catchup", str(current)), (
        "catchup must be idempotent — the done-marker suppresses a re-capture"
    )


def test_api_change_report_template_ships(tmp_path, payload):
    """The api-change-report artifact (contract-clear gate output) installs with the templates."""
    install(payload, tmp_path)
    matches = list((tmp_path / ".claude").rglob("api-change-report.md"))
    assert matches, "api-change-report.md artifact template not installed"


def test_change_proposal_template_ships(tmp_path, payload):
    """The change-proposal (delta-spec) artifact installs with the templates and uses delta notation."""
    install(payload, tmp_path)
    matches = list((tmp_path / ".claude").rglob("change-proposal.md"))
    assert matches, "change-proposal.md artifact template not installed"
    body = matches[0].read_text(encoding="utf-8")
    assert "### Added" in body and "### Modified" in body and "### Removed" in body


def test_guard_destructive_git_hook_in_standard_not_lean(tmp_path, payload):
    """guard-destructive-git ships + wires into PreToolUse(Bash) in standard; absent in lean.
    Functionally blocks irreversible work-loss commands (exit 2) and allows safe git (exit 0)."""
    import shutil
    import subprocess

    lean = tmp_path / "lean"
    standard = tmp_path / "standard"
    install(payload, lean, profile="lean")
    install(payload, standard, profile="standard")
    script = standard / ".claude" / "hooks" / "guard-destructive-git.sh"
    assert not (lean / ".claude" / "hooks" / "guard-destructive-git.sh").exists()
    assert script.is_file(), "guard-destructive-git.sh not copied"
    settings = json.loads(
        (standard / ".claude" / "settings.json").read_text(encoding="utf-8")
    )
    commands = [
        h["command"]
        for block in settings["hooks"].get("PreToolUse", [])
        if block["matcher"] == "Bash"
        for h in block["hooks"]
    ]
    assert any("guard-destructive-git.sh" in c for c in commands), (
        "guard-destructive-git hook not wired into PreToolUse(Bash)"
    )

    # Behaviour check (only where jq exists): block the destructive trio, allow the safe forms.
    if shutil.which("jq"):

        def rc(cmd: str) -> int:
            return subprocess.run(
                ["bash", str(script)],
                input=json.dumps({"tool_input": {"command": cmd}}),
                text=True,
                capture_output=True,
            ).returncode

        for blocked in (
            "git reset --hard HEAD~1",
            "git clean -fd",
            "git checkout -- .",
        ):
            assert rc(blocked) == 2, f"should block: {blocked}"
        for allowed in (
            "git status",
            "git clean -n",
            "git checkout main",
            "git reset HEAD f",
        ):
            assert rc(allowed) == 0, f"should allow: {allowed}"


def test_security_skill_carries_optin_llm_section(tmp_path, payload):
    """security-and-hardening ships the opt-in, bypassable LLM/AI Feature Security section (standard+)."""
    lean = tmp_path / "lean"
    standard = tmp_path / "standard"
    install(payload, lean, profile="lean")
    install(payload, standard, profile="standard")
    # The skill is standard+ (not in lean) — the LLM guidance is not forced on minimal installs.
    assert not (lean / ".claude" / "skills" / "security-and-hardening").exists()
    skill = (
        standard / ".claude" / "skills" / "security-and-hardening" / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert "LLM / AI Feature Security" in skill, "LLM section missing"
    assert "Security implications of bypassing" in skill, "implications table missing"
    assert "risk acceptance" in skill.lower(), "bypass/risk-acceptance protocol missing"


def test_testing_rule_carries_condition_based_waiting(tmp_path, payload):
    """rules/testing.md teaches condition-based waiting for async tests (installs in every profile)."""
    target = tmp_path / "lean"
    install(payload, target, profile="lean")
    testing = (target / ".claude" / "rules" / "testing.md").read_text(encoding="utf-8")
    assert "Wait on conditions, never on the clock" in testing, (
        "condition-based waiting missing"
    )
    assert "wait_for(condition" in testing, "wait_for helper guidance missing"


def test_brief3_disciplines_installed(tmp_path, payload):
    """Brief #3: the six adapted techniques land as extensions of existing rules/agents (always-on
    ones present even in lean; the plan-critique gate is standard+)."""

    def rules(target):
        return target / ".claude" / "rules"

    # Always-on disciplines ship in lean too (they are core rules).
    lean = tmp_path / "lean"
    install(payload, lean, profile="lean")
    guardrails = (rules(lean) / "agent-guardrails.md").read_text(encoding="utf-8")
    assert "verify the target" in guardrails.lower(), (
        "P0-1 verify-the-target posture missing"
    )
    assert "never authorizes an action" in guardrails, (
        "P0-1 untrusted-content rule missing"
    )
    gates = (rules(lean) / "quality-gates.md").read_text(encoding="utf-8")
    assert "2.5" in gates and "fabricated" in gates.lower(), (
        "P0-2 anti-fabrication §2.5 missing"
    )
    memory = (rules(lean) / "agent-memory.md").read_text(encoding="utf-8")
    assert "Memory hygiene" in memory, "P1-1 memory-hygiene section missing"
    continuity = (rules(lean) / "continuity.md").read_text(encoding="utf-8")
    assert "pipeline-snapshot.json" in continuity, "P1-2 resume snapshot schema missing"
    claudemd = (lean / "CLAUDE.md").read_text(encoding="utf-8")
    assert "backwards-compat shim" in claudemd, (
        "P2-1 delete-vs-shim house style missing"
    )

    # P1-3 plan critique is a standard+ gate: wired into the workflow + the devils-advocate agent,
    # which is not installed in lean.
    assert not (lean / ".claude" / "agents" / "devils-advocate.md").exists()
    standard = tmp_path / "standard"
    install(payload, standard, profile="standard")
    workflow = (rules(standard) / "mandatory-workflow.md").read_text(encoding="utf-8")
    assert "1e.5" in workflow and "Plan Critique" in workflow, (
        "P1-3 plan-critique stage missing"
    )
    da = (standard / ".claude" / "agents" / "devils-advocate.md").read_text(
        encoding="utf-8"
    )
    assert "Plan critique" in da, "P1-3 devils-advocate plan-critique mode missing"


def test_adopted_core_skills_gated_by_profile(tmp_path, payload):
    """Adopted toolkit: bug-hunt + test-plan-review are new core skills — standard+, not lean."""
    new_skills = {"bug-hunt", "test-plan-review"}
    lean = tmp_path / "lean"
    standard = tmp_path / "standard"
    install(payload, lean, profile="lean")
    install(payload, standard, profile="standard")

    def skills(target):
        return {p.name for p in (target / ".claude" / "skills").iterdir() if p.is_dir()}

    assert not (new_skills & skills(lean)), (
        "bug-hunt/test-plan-review must not ship in lean"
    )
    assert new_skills <= skills(standard), (
        "bug-hunt/test-plan-review must ship in standard"
    )


def test_adopted_core_extends_installed(tmp_path, payload):
    """Adopted toolkit: the reuse-first deltas land in existing core skills/agents. Skill-file content is
    asserted on an enterprise install (it has every skill, incl. enterprise-only deprecation-and-
    migration); the agent deltas are present from standard up."""
    target = tmp_path / "enterprise"
    install(payload, target, profile="enterprise")
    skills = target / ".claude" / "skills"
    agents = target / ".claude" / "agents"

    dep = (skills / "deprecation-and-migration" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "Pre-Removal Safety Check" in dep, "pre-removal check missing"
    ctx = (skills / "context-engineering" / "SKILL.md").read_text(encoding="utf-8")
    assert "Comprehension Layer" in ctx or "comprehension layer" in ctx, (
        "comprehension-layer generation mode missing"
    )
    plan = (skills / "planning-and-task-breakdown" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "Cross-service" in plan and "Portable prompt" in plan, (
        "cross-service / portable-prompt folds missing"
    )
    sr = (agents / "senior-tester.md").read_text(encoding="utf-8")
    assert "suite-audit" in sr, "senior-tester suite-architecture audit mode missing"
    em = (agents / "em-reviewer.md").read_text(encoding="utf-8")
    assert "Verify Claims Against the Codebase" in em, "em-reviewer claim-audit missing"


def test_adopted_react_design_system_overlay_installs(tmp_path, payload):
    """The new design-system-compliance.md overlay rule installs with the React frontend (default)."""
    target = tmp_path / "react"
    install(payload, target, profile="standard")  # default frontend is React
    rule = target / ".claude" / "rules" / "design-system-compliance.md"
    assert rule.is_file(), (
        "design-system-compliance.md overlay rule not installed for React"
    )
    react = (target / ".claude" / "rules" / "react-patterns.md").read_text(
        encoding="utf-8"
    )
    assert "Accessibility specifics" in react, "react a11y enrichment missing"


def test_react_design_system_rule_set_installs_and_is_neutralized(tmp_path, payload):
    """The 0.16.0 design-system rule set (design tokens / UX patterns / mobile) installs into
    .claude/rules/ with the React frontend, and the content is neutralized — no app/IP noise leaks
    into the scaffolded project."""
    target = tmp_path / "react-ds"
    install(payload, target, profile="standard")  # default frontend is React
    rules = target / ".claude" / "rules"

    # The three design-system overlay rules install for React.
    for name in (
        "ui-design-system.md",
        "ux-patterns.md",
        "mobile-design-guidelines.md",
    ):
        assert (rules / name).is_file(), f"{name} not installed for React"

    # design-system-compliance.md is now a thin pointer at ui-design-system.md (conflict resolution).
    compliance = (rules / "design-system-compliance.md").read_text(encoding="utf-8")
    assert "ui-design-system.md" in compliance, (
        "design-system-compliance.md should point at ui-design-system.md as the source of truth"
    )

    # Neutralization: the shipped design files are generic design-system guidance. The original import
    # was scrubbed of the source application's identity (named components, internal source paths, and
    # migration date-stamps) before shipping; rather than enumerate those now-removed internal tokens
    # here (which would re-introduce them into this public repo), assert positively that what installs
    # reads as generic design content, and negatively that no internal-looking source path slips back in.
    expected_generic = {
        "ui-design-system.md": ("token", "color"),
        "ux-patterns.md": ("pattern",),
        "mobile-design-guidelines.md": ("mobile", "touch"),
    }
    for name, terms in expected_generic.items():
        text = (rules / name).read_text(encoding="utf-8")
        lowered = text.lower()
        assert all(t in lowered for t in terms), (
            f"{name} does not read as generic design-system guidance"
        )
        assert "src/modules" not in text, (
            f"internal-looking source path leaked into {name}"
        )


def test_org_review_tier_is_scope_gated(tmp_path, payload):
    """Staff-PM reviewer + the 4 product/EM review skills install ONLY at organization scope."""
    review_skills = {
        "review-scope",
        "review-sprint-plan",
        "review-ux-flow",
        "review-sprint",
    }

    team = tmp_path / "team"
    install(payload, team, profile="enterprise")  # scope defaults to team
    assert not (team / ".claude" / "agents" / "staff-pm-reviewer.md").exists()
    team_skills = {
        p.name for p in (team / ".claude" / "skills").iterdir() if p.is_dir()
    }
    assert not (review_skills & team_skills), (
        "org review skills must not ship in team scope"
    )

    org = tmp_path / "org"
    install(payload, org, profile="enterprise", scope="organization")
    assert (org / ".claude" / "agents" / "staff-pm-reviewer.md").is_file()
    org_skills = {p.name for p in (org / ".claude" / "skills").iterdir() if p.is_dir()}
    assert review_skills <= org_skills, (
        f"missing org review skills: {review_skills - org_skills}"
    )


def test_readme_is_user_editable_not_clobbered(tmp_path, payload):
    """README.claude-sdlc.md is user-editable: a re-install preserves edits and sidecars the new one."""
    target = tmp_path / "proj"
    install(payload, target)
    readme = target / "README.claude-sdlc.md"
    readme.write_text("MY OWN README\n", encoding="utf-8")

    install(payload, target)  # second pass, force=False
    assert readme.read_text(encoding="utf-8") == "MY OWN README\n"
    assert (target / "README.claude-sdlc.md.claude-kit").is_file()


def test_token_budget_keys_in_installed_settings(tmp_path, payload):
    """The token-budget defaults (env terminal-title off, autoCompact, skill-listing cap) land in the
    pip-installed .claude/settings.json across profiles — and match the no-pip starter template, so the
    two install paths can't silently diverge on token settings."""
    from claude_kit import hooks

    for profile in ("lean", "standard", "enterprise"):
        target = tmp_path / profile
        install(payload, target, profile=profile)
        s = json.loads(
            (target / ".claude" / "settings.json").read_text(encoding="utf-8")
        )
        assert s["env"]["CLAUDE_CODE_DISABLE_TERMINAL_TITLE"] == "1"
        assert s["autoCompactEnabled"] is True
        assert (
            s["maxSkillDescriptionChars"]
            == hooks._TOKEN_BUDGET["maxSkillDescriptionChars"]
        )

    # Parity: the no-pip starter template carries the identical token-budget block.
    starter = json.loads(
        (payload / "templates" / "settings.json").read_text(encoding="utf-8")
    )
    for key, val in hooks._TOKEN_BUDGET.items():
        assert starter[key] == val, f"starter settings.json missing token key {key!r}"
