"""End-to-end CLI behavior via Typer's CliRunner: init modes, lifecycle exit codes, payload resolution."""

from __future__ import annotations

from contextlib import ExitStack

from typer.testing import CliRunner

from claude_kit import scaffold
from claude_kit.cli import app
from tests._helpers import install

runner = CliRunner()


def test_version_flag():
    from claude_kit import __version__

    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_init_defaults_end_to_end(tmp_path):
    target = tmp_path / "proj"
    result = runner.invoke(app, ["init", str(target), "--defaults"])
    assert result.exit_code == 0, result.stdout
    assert (target / "CLAUDE.md").is_file()
    assert (target / ".claude" / "skills" / "sdlc" / "SKILL.md").is_file()
    # validate the freshly created config through the CLI too.
    assert runner.invoke(app, ["validate", str(target)]).exit_code == 0


def test_init_config_mongo_enterprise(tmp_path):
    cfg = tmp_path / "init.yaml"
    cfg.write_text(
        "database: mongodb\nprofile: enterprise\nmcp: [github]\n", encoding="utf-8"
    )
    target = tmp_path / "proj"
    result = runner.invoke(app, ["init", str(target), "--config", str(cfg)])
    assert result.exit_code == 0, result.stdout
    assert (target / ".mcp.json").is_file()
    assert (target / ".claude" / "rules" / "mongodb-patterns.md").is_file()


def test_init_capture_mode_config_and_default(tmp_path):
    """`capture_mode` flows through --config and --defaults into settings.json hook wiring."""
    import json

    def events(target):
        s = json.loads(
            (target / ".claude" / "settings.json").read_text(encoding="utf-8")
        )
        return {
            ev: " ".join(
                h["command"] for blk in s["hooks"].get(ev, []) for h in blk["hooks"]
            )
            for ev in ("SessionStart", "Stop", "SessionEnd")
        }

    # --config: per-task wires the Stop trigger and no SessionEnd capture.
    cfg = tmp_path / "init.yaml"
    cfg.write_text("capture_mode: per-task\n", encoding="utf-8")
    pt = tmp_path / "pt"
    assert runner.invoke(app, ["init", str(pt), "--config", str(cfg)]).exit_code == 0
    ev = events(pt)
    assert "capture-learnings.sh" in ev["Stop"] and ev["Stop"].rstrip().endswith("stop")
    assert "capture-learnings.sh" not in ev["SessionEnd"]

    # --defaults: the recommended catch-up default (SessionEnd end + SessionStart catchup).
    dflt = tmp_path / "dflt"
    assert runner.invoke(app, ["init", str(dflt), "--defaults"]).exit_code == 0
    ev = events(dflt)
    assert "catchup" in ev["SessionStart"]
    assert "capture-learnings.sh" in ev["SessionEnd"]


def test_existing_claude_abort_changes_nothing(tmp_path, payload):
    target = tmp_path / "proj"
    install(payload, target)
    before = (target / ".claude" / "config" / "init-options.json").read_text(
        encoding="utf-8"
    )
    result = runner.invoke(app, ["init", str(target)], input="abort\n")
    assert result.exit_code == 0
    assert "aborted" in result.stdout.lower()
    after = (target / ".claude" / "config" / "init-options.json").read_text(
        encoding="utf-8"
    )
    assert before == after


def test_existing_claude_backup_moves_old_aside(tmp_path, payload):
    target = tmp_path / "proj"
    install(payload, target)
    # Interactive: choose "backup"; the selection prompts then fall through to defaults on EOF.
    result = runner.invoke(app, ["init", str(target)], input="backup\n")
    assert result.exit_code == 0, result.stdout
    assert (target / ".claude.bak-1").is_dir()
    assert (target / ".claude" / "skills" / "sdlc" / "SKILL.md").is_file()


def test_existing_claude_force_overwrites(tmp_path, payload):
    target = tmp_path / "proj"
    install(payload, target)
    result = runner.invoke(app, ["init", str(target), "--defaults", "--force"])
    assert result.exit_code == 0, result.stdout
    assert (target / ".claude").is_dir()


def test_default_reinit_merges_and_preserves_user_files(tmp_path, payload):
    """A default (non-interactive) re-init uses merge mode — it must NOT delete the user's files."""
    target = tmp_path / "proj"
    install(payload, target)
    policy = target / ".claude" / "rules" / "company-policy.md"
    policy.write_text("ours\n", encoding="utf-8")

    result = runner.invoke(app, ["init", str(target), "--defaults"])
    assert result.exit_code == 0, result.stdout
    assert policy.is_file()  # survived the merge
    assert policy.read_text(encoding="utf-8") == "ours\n"
    assert (target / ".claude" / "skills" / "sdlc" / "SKILL.md").is_file()


def test_force_overwrite_is_the_only_destructive_path(tmp_path, payload):
    """--force overwrites kit-managed dirs wholesale (the documented escape hatch), unlike default."""
    target = tmp_path / "proj"
    install(payload, target)
    policy = target / ".claude" / "rules" / "company-policy.md"
    policy.write_text("ours\n", encoding="utf-8")

    result = runner.invoke(app, ["init", str(target), "--defaults", "--force"])
    assert result.exit_code == 0, result.stdout
    assert not policy.exists()  # explicit --force is allowed to remove it


def test_diff_and_upgrade_exit_codes(tmp_path, payload):
    target = tmp_path / "proj"
    install(payload, target)
    assert runner.invoke(app, ["diff", str(target)]).exit_code == 0
    assert runner.invoke(app, ["upgrade", str(target)]).exit_code == 0
    # Not-installed dir → non-zero.
    empty = tmp_path / "empty"
    empty.mkdir()
    assert runner.invoke(app, ["diff", str(empty)]).exit_code == 1


def test_list_options_runs(tmp_path):
    result = runner.invoke(app, ["list-options"])
    assert result.exit_code == 0
    assert "React" in result.stdout and "PostgreSQL" in result.stdout


def test_init_config_organization_scope(tmp_path):
    """A --config with organization scope installs the org overlay end-to-end via the CLI."""
    cfg = tmp_path / "init.yaml"
    cfg.write_text(
        "profile: enterprise\n"
        "scope: organization\n"
        "teams: [engineering, product, security]\n"
        "autonomy: enterprise-controlled\n"
        "review_strictness: regulated\n"
        "org_packs: true\n",
        encoding="utf-8",
    )
    target = tmp_path / "proj"
    result = runner.invoke(app, ["init", str(target), "--config", str(cfg)])
    assert result.exit_code == 0, result.stdout
    assert (target / ".claude" / "org-packs" / "README.md").is_file()
    assert (target / ".claude" / "agents" / "pm-copilot.md").is_file()
    assert (target / ".claude" / "rules" / "autonomy-levels.md").is_file()
    assert runner.invoke(app, ["validate", str(target)]).exit_code == 0


def test_init_config_team_scope_has_no_org(tmp_path):
    """Omitting scope (defaults to team) installs no org overlay."""
    cfg = tmp_path / "init.yaml"
    cfg.write_text("profile: enterprise\n", encoding="utf-8")
    target = tmp_path / "proj"
    result = runner.invoke(app, ["init", str(target), "--config", str(cfg)])
    assert result.exit_code == 0, result.stdout
    assert not (target / ".claude" / "org-packs").exists()
    assert not (target / ".claude" / "agents" / "pm-copilot.md").exists()


def test_org_pack_stub_commands_are_planned(tmp_path):
    """Planned commands announce 'planned' and exit non-zero (not a silent success)."""
    pkg = runner.invoke(app, ["package-org-pack", "engineering-core"])
    assert pkg.exit_code == 2, pkg.stdout
    assert "planned" in pkg.stdout.lower()

    inst = runner.invoke(app, ["install-org-pack", "engineering-core"])
    assert inst.exit_code == 2, inst.stdout
    assert "planned" in inst.stdout.lower()

    res = runner.invoke(app, ["research", "import-sources", "sources.yaml"])
    assert res.exit_code == 2, res.stdout
    assert "planned" in res.stdout.lower()


def test_payload_dir_resolves_from_checkout():
    with ExitStack() as stack:
        root = scaffold.payload_dir(stack)
    assert (root / "catalog").is_dir()
    assert (root / "rules").is_dir()
    assert (root / "agents").is_dir()


# --- new lifecycle surface (validate --strict / doctor --mcp / pipeline group) --------------------


def test_validate_strict_flag_cli(tmp_path, payload):
    install(payload, tmp_path)
    result = runner.invoke(app, ["validate", "--strict", str(tmp_path)])
    assert result.exit_code == 0, result.stdout
    assert "catalog:" in result.stdout


def test_doctor_mcp_flag_cli(tmp_path, payload):
    install(payload, tmp_path, mcp=["github"])
    result = runner.invoke(app, ["doctor", "--mcp", str(tmp_path)])
    assert result.exit_code == 0, result.stdout
    assert "MCP github" in result.stdout


def test_pipeline_validate_and_status_cli(tmp_path, payload):
    install(payload, tmp_path)
    res = runner.invoke(app, ["pipeline", "validate", str(tmp_path)])
    assert res.exit_code == 0, res.stdout
    assert "no run in progress" in res.stdout
    res = runner.invoke(app, ["pipeline", "status", str(tmp_path)])
    assert res.exit_code == 0


def test_pipeline_close_gate_and_abort_cli(tmp_path, payload):
    """Exercises the close-gate positional+option signature end-to-end (and abort)."""
    install(payload, tmp_path)
    evidence = tmp_path / "evidence.txt"
    evidence.write_text("done", encoding="utf-8")
    res = runner.invoke(
        app,
        [
            "pipeline",
            "close-gate",
            "code-review",
            "--evidence",
            str(evidence),
            str(tmp_path),
        ],
    )
    assert res.exit_code == 0, res.stdout
    assert "recorded passed" in res.stdout
    # Unknown gate for the profile → non-zero with the gate list.
    bad = runner.invoke(
        app,
        [
            "pipeline",
            "close-gate",
            "made-up",
            "--evidence",
            str(evidence),
            str(tmp_path),
        ],
    )
    assert bad.exit_code == 1
    assert "is not a gate of this profile" in bad.stdout
    assert runner.invoke(app, ["pipeline", "abort", str(tmp_path)]).exit_code == 0


def test_init_dry_run_writes_nothing(tmp_path):
    """`init --dry-run` previews the plan and must NOT create or touch the target."""
    target = tmp_path / "proj"
    result = runner.invoke(app, ["init", str(target), "--defaults", "--dry-run"])
    assert result.exit_code == 0, result.stdout
    # Safety net: a pure preview creates nothing — the target dir is never even made.
    assert not target.exists()
    assert "DRY RUN" in result.stdout
    assert "nothing was written" in result.stdout
    # It lists representative files that a real install would write.
    assert "+ CLAUDE.md" in result.stdout
    assert any(
        line.strip().startswith("+ .claude/rules/")
        for line in result.stdout.splitlines()
    )


def test_init_dry_run_matches_real_install(tmp_path):
    """The previewed file set equals the real fresh-install file set (no drift)."""
    preview_target = tmp_path / "preview"
    r = runner.invoke(app, ["init", str(preview_target), "--defaults", "--dry-run"])
    assert r.exit_code == 0, r.stdout
    previewed = sorted(
        line.strip()[2:]
        for line in r.stdout.splitlines()
        if line.strip().startswith("+ ")
    )
    assert previewed, "dry-run listed no files"

    real_target = tmp_path / "real"
    assert runner.invoke(app, ["init", str(real_target), "--defaults"]).exit_code == 0
    actual = sorted(
        str(p.relative_to(real_target)) for p in real_target.rglob("*") if p.is_file()
    )
    assert previewed == actual
