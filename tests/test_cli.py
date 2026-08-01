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


def test_init_detect_commands_flag(tmp_path):
    """`init` discovers a populated repo's commands by default; --no-detect-commands opts out."""

    def claude_md(target):
        return (target / "CLAUDE.md").read_text(encoding="utf-8")

    # Default: a uv.lock in the target → `uv sync` is wired into CLAUDE.md.
    on = tmp_path / "on"
    on.mkdir()
    (on / "uv.lock").write_text("", encoding="utf-8")
    assert runner.invoke(app, ["init", str(on), "--defaults"]).exit_code == 0
    assert "uv sync" in claude_md(on)

    # --no-detect-commands keeps the generic catalog command (no `uv sync`).
    off = tmp_path / "off"
    off.mkdir()
    (off / "uv.lock").write_text("", encoding="utf-8")
    assert (
        runner.invoke(
            app, ["init", str(off), "--defaults", "--no-detect-commands"]
        ).exit_code
        == 0
    )
    assert "uv sync" not in claude_md(off)


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


def test_init_config_malformed_yaml_is_friendly(tmp_path):
    """A YAML syntax error in --config exits 2 with `error: …`, not a raw traceback."""
    cfg = tmp_path / "bad.yaml"
    cfg.write_text("profile: standard\n  backend: [unclosed\n", encoding="utf-8")
    target = tmp_path / "proj"
    result = runner.invoke(app, ["init", str(target), "--config", str(cfg)])
    assert result.exit_code == 2
    # Click <8.2 mixes stderr into ``output`` and makes ``result.stderr`` raise;
    # Click >=8.2 separates the streams. Read whichever holds the message.
    combined = result.output
    try:
        combined += result.stderr
    except ValueError:
        pass
    assert "not valid yaml" in combined.lower()
    assert "Traceback" not in combined
    # No partial install may be left behind.
    assert not target.exists() or not any(target.iterdir())


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
    # Assert the dispatch argument on the capture entry itself; other hooks also bind Stop, so
    # its position in the concatenated command string is incidental.
    assert 'capture-learnings.sh" stop' in ev["Stop"]
    assert "capture-learnings.sh" not in ev["SessionEnd"]

    # --defaults: capture is OFF (consent gate, 0.76.0) — no capture hook on any event. Only an
    # explicit choice (interactive init or a config file, as above) wires the background job.
    dflt = tmp_path / "dflt"
    assert runner.invoke(app, ["init", str(dflt), "--defaults"]).exit_code == 0
    ev = events(dflt)
    assert "capture-learnings.sh" not in ev["SessionStart"]
    assert "capture-learnings.sh" not in ev["SessionEnd"]
    assert "capture-learnings.sh" not in ev["Stop"]
    assert (
        "load-learnings.sh" in ev["SessionStart"]
    )  # recall stays on — only capture is gated


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


def test_planned_commands_hidden_from_help_by_default():
    """Planned commands are hidden from --help so they can't be mistaken for features."""
    top = runner.invoke(app, ["--help"]).output
    assert "package-org-pack" not in top
    assert "install-org-pack" not in top
    sub = runner.invoke(app, ["research", "--help"]).output
    assert "import-sources" not in sub


def test_planned_commands_visible_and_marked_with_experimental(monkeypatch):
    """With CLAUDE_KIT_EXPERIMENTAL=1 the planned commands surface in --help, marked [planned]."""
    import importlib

    from claude_kit import cli as cli_mod

    monkeypatch.setenv("CLAUDE_KIT_EXPERIMENTAL", "1")
    try:
        importlib.reload(cli_mod)
        r = CliRunner()
        top = r.invoke(cli_mod.app, ["--help"]).output
        assert "package-org-pack" in top
        assert "install-org-pack" in top
        sub = r.invoke(cli_mod.app, ["research", "--help"]).output
        assert "import-sources" in sub
        # the "[planned]" marker lives in each command's own --help (the main
        # listing truncates the help column, so assert it on the detail screen)
        detail = r.invoke(cli_mod.app, ["package-org-pack", "--help"]).output
        assert "[planned]" in detail
    finally:
        monkeypatch.delenv("CLAUDE_KIT_EXPERIMENTAL", raising=False)
        importlib.reload(cli_mod)  # restore default (hidden) state for later tests


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


def test_status_skill_count_matches_validate(tmp_path):
    """R15: status must count skills like validate does (SKILL.md dirs; _references/ is not a skill)."""
    import re

    target = tmp_path / "proj"
    assert runner.invoke(app, ["init", str(target), "--defaults"]).exit_code == 0
    status_out = runner.invoke(app, ["status", str(target)]).stdout
    validate_out = runner.invoke(app, ["validate", str(target)]).stdout
    status_n = int(re.search(r"skills/: (\d+)", status_out).group(1))
    validate_n = int(re.search(r"\((\d+) skills\)", validate_out).group(1))
    assert status_n == validate_n
    # The shared-reference dir exists but is support content, not a skill.
    assert (target / ".claude" / "skills" / "_references").is_dir()


def _ticket_store(root, status="IN PROGRESS", relations=None):
    """Write a one-ticket store; returns the project root."""
    import json as _json

    directory = root / "docs" / "project" / "tickets"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "DEMO-1-thing.md").write_text(
        f"# DEMO-1: Do the thing\n\n- **Status:** {status}\n- **Branch:** feat/demo\n",
        encoding="utf-8",
    )
    (directory / "DEMO-2-other.md").write_text(
        "# DEMO-2: Other thing\n\n- **Status:** OPEN\n",
        encoding="utf-8",
    )
    (directory / "index.json").write_text(
        _json.dumps(
            {"prefix": "DEMO", "tickets": {"DEMO-2": {"relations": relations or {}}}}
        ),
        encoding="utf-8",
    )
    return root


def test_tickets_board_without_a_store_is_friendly_not_a_traceback(tmp_path):
    """A freshly scaffolded project has no tickets yet — that must not look like a crash."""
    result = runner.invoke(
        app, ["tickets", "--path", str(tmp_path), "--transcript-dir", str(tmp_path)]
    )
    assert result.exit_code == 0, result.stdout
    assert "no tickets yet" in result.stdout
    assert "Traceback" not in result.stdout


def test_tickets_board_renders_without_any_transcripts(tmp_path):
    """Regression: telemetry is optional — the board still renders when there is none."""
    _ticket_store(tmp_path)
    result = runner.invoke(
        app, ["tickets", "--path", str(tmp_path), "--transcript-dir", str(tmp_path)]
    )
    assert result.exit_code == 0, result.stdout
    assert "DEMO-1" in result.stdout
    assert "IN PROGRESS" in result.stdout


def test_tickets_header_reports_open_and_actionable(tmp_path):
    _ticket_store(tmp_path, relations={"depends_on": ["DEMO-1"]})
    result = runner.invoke(
        app, ["tickets", "--path", str(tmp_path), "--transcript-dir", str(tmp_path)]
    )
    assert result.exit_code == 0
    assert "2 open" in result.stdout and "1 actionable" in result.stdout
    assert "BLOCKED" in result.stdout


def test_tickets_graph_flag(tmp_path):
    _ticket_store(tmp_path, relations={"child_of": ["DEMO-1"]})
    result = runner.invoke(
        app,
        [
            "tickets",
            "--path",
            str(tmp_path),
            "--graph",
            "--transcript-dir",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert "DEMO-1" in result.stdout and "DEMO-2" in result.stdout


def test_tickets_graph_and_graph_git_are_mutually_exclusive(tmp_path):
    _ticket_store(tmp_path)
    result = runner.invoke(
        app, ["tickets", "--path", str(tmp_path), "--graph", "--graph-git"]
    )
    assert result.exit_code == 2
    assert "only one" in result.stdout


def test_tickets_detail_view(tmp_path):
    _ticket_store(tmp_path)
    result = runner.invoke(
        app,
        [
            "tickets",
            "DEMO-1",
            "--path",
            str(tmp_path),
            "--transcript-dir",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert "Do the thing" in result.stdout
    assert "no telemetry recorded" in result.stdout


def test_tickets_unknown_id_exits_nonzero(tmp_path):
    """Scripts need to distinguish 'no such ticket' from a successful render."""
    _ticket_store(tmp_path)
    result = runner.invoke(
        app,
        [
            "tickets",
            "DEMO-99",
            "--path",
            str(tmp_path),
            "--transcript-dir",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 2
    assert "unknown ticket" in result.stdout


def test_tickets_json_is_machine_readable(tmp_path):
    import json as _json

    _ticket_store(tmp_path, relations={"depends_on": ["DEMO-1"]})
    result = runner.invoke(
        app,
        [
            "tickets",
            "--path",
            str(tmp_path),
            "--json",
            "--transcript-dir",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.stdout
    payload = _json.loads(result.stdout)
    assert payload["prefix"] == "DEMO"
    assert payload["counts"]["open"] == 2
    blocked = next(t for t in payload["tickets"] if t["id"] == "DEMO-2")
    assert blocked["display_status"] == "BLOCKED"
    assert blocked["blockers"] == ["DEMO-1"]
    assert blocked["actionable"] is False


def test_tickets_html_writes_a_self_contained_board(tmp_path):
    from claude_kit import board_html

    _ticket_store(tmp_path)
    result = runner.invoke(
        app,
        [
            "tickets",
            "--path",
            str(tmp_path),
            "--html",
            "--transcript-dir",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.stdout

    board = tmp_path / board_html.BOARD_REL
    assert board.is_file(), "the board lands under the gitignored .claude/state/"
    assert "file://" in result.stdout, "the printed URL is how you actually open it"

    html = board.read_text(encoding="utf-8")
    assert "DEMO-1" in html and "Do the thing" in html
    assert '<meta http-equiv="refresh" content="10">' in html
    assert "<script" not in html and "https://" not in html


def test_tickets_html_refresh_zero_produces_a_static_page(tmp_path):
    from claude_kit import board_html

    _ticket_store(tmp_path)
    result = runner.invoke(
        app,
        [
            "tickets",
            "--path",
            str(tmp_path),
            "--html",
            "--refresh",
            "0",
            "--transcript-dir",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.stdout
    html = (tmp_path / board_html.BOARD_REL).read_text(encoding="utf-8")
    assert 'http-equiv="refresh"' not in html


def test_privacy_report_default_install_capture_off(tmp_path):
    """privacy-report on a --defaults install: capture OFF, recall listed, exit 0."""
    target = tmp_path / "proj"
    assert runner.invoke(app, ["init", str(target), "--defaults"]).exit_code == 0
    result = runner.invoke(app, ["privacy-report", str(target)])
    assert result.exit_code == 0, result.stdout
    assert "background learning capture: OFF" in result.stdout
    assert "load-learnings" in result.stdout  # recall stays on and is disclosed


def test_privacy_report_flags_enabled_capture(tmp_path):
    """A config-file install that opts into capture shows capture: ON with the disclosure."""
    cfg = tmp_path / "init.yaml"
    cfg.write_text("capture_mode: session-end-catchup\n", encoding="utf-8")
    target = tmp_path / "proj"
    assert (
        runner.invoke(app, ["init", str(target), "--config", str(cfg)]).exit_code == 0
    )
    result = runner.invoke(app, ["privacy-report", str(target)])
    assert result.exit_code == 0, result.stdout
    assert "background learning capture: ON" in result.stdout
    assert "transcript" in result.stdout  # the disclosure names what is read


def test_privacy_report_without_settings_shows_plugin_roster(tmp_path):
    """No settings.json → describe the static plugin channel; plugin ships no capture."""
    result = runner.invoke(app, ["privacy-report", str(tmp_path)])
    assert result.exit_code == 0, result.stdout
    assert "plugin channel" in result.stdout
    assert "plugin ships no capture hooks" in result.stdout
