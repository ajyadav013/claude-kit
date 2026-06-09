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
    """The package/install-org-pack commands are registered, exit 0, and announce 'planned'."""
    pkg = runner.invoke(app, ["package-org-pack", "engineering-core"])
    assert pkg.exit_code == 0, pkg.stdout
    assert "planned" in pkg.stdout.lower()

    inst = runner.invoke(app, ["install-org-pack", "engineering-core"])
    assert inst.exit_code == 0, inst.stdout
    assert "planned" in inst.stdout.lower()


def test_payload_dir_resolves_from_checkout():
    with ExitStack() as stack:
        root = scaffold.payload_dir(stack)
    assert (root / "catalog").is_dir()
    assert (root / "rules").is_dir()
    assert (root / "agents").is_dir()
