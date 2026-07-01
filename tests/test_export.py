"""Exporter coverage — projecting a resolved plan into Cursor / AGENTS.md / Copilot formats.

Unit tests call :func:`claude_kit.export.export_targets` directly against the bundled payload; CLI
tests drive the ``claude-kit export`` command through Typer's ``CliRunner`` (dry-run, sidecar/force,
installed-selection resolution, unknown-target). Together they pin the invariants the export promises:
valid ``.mdc`` frontmatter, per-lane globs, a ``type``-free MCP file, an honest fidelity note, and
**no** application code or Docker in any emitted file.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from typer.testing import CliRunner

from claude_kit import catalog
from claude_kit import export as exporter
from claude_kit.cli import app
from claude_kit.models import ResolvedPlan
from tests._helpers import install, make_selection

runner = CliRunner()

# A rich, fully-live stack: TypeScript React front end, Python/FastAPI back end, PostgreSQL — so every
# glob lane (frontend/backend/database) and the MCP path are exercised at once.
_RICH = {
    "frontend_framework": "react",
    "frontend_language": "typescript",
    "backend_language": "python",
    "backend_framework": "fastapi",
    "database": "postgres",
    "mcp": ["github"],
}


def _plan(payload: Path, **overrides: object) -> ResolvedPlan:
    """Resolve a plan straight from the catalog (defaults + overrides) — no install required."""
    return catalog.resolve(payload, make_selection(payload, **overrides))


def _frontmatter(mdc_text: str) -> dict:
    """Parse (and validate) the YAML frontmatter block of a ``.mdc`` file."""
    assert mdc_text.startswith("---\n"), "missing frontmatter fence"
    block = mdc_text.split("---\n", 2)[1]
    data = yaml.safe_load(block)
    assert isinstance(data, dict), "frontmatter is not a mapping"
    return data


# --- Cursor .mdc structure -------------------------------------------------------------------------


def test_cursor_rules_are_valid_mdc(tmp_path, payload):
    plan = _plan(payload, **_RICH)
    exporter.export_targets(payload, tmp_path, plan, ["cursor"])

    rules = sorted((tmp_path / ".cursor" / "rules").glob("*.mdc"))
    assert len(rules) > 1

    always = []
    for p in rules:
        fm = _frontmatter(p.read_text(encoding="utf-8"))
        assert fm.get("description"), f"{p.name}: empty description"
        if fm.get("alwaysApply") is True:
            always.append(p.name)
    # Only the synthesized charter is always-applied; the rule set loads on demand.
    assert always == ["000-project.mdc"]


def test_cursor_overlay_globs_per_lane(tmp_path, payload):
    """Overlay rules auto-attach on their lane's language/db; core rules carry no globs."""
    plan = _plan(payload, **_RICH)
    exporter.export_targets(payload, tmp_path, plan, ["cursor"])
    rules = tmp_path / ".cursor" / "rules"

    assert _frontmatter((rules / "react-patterns.mdc").read_text())["globs"] == (
        "**/*.ts,**/*.tsx"
    )
    assert _frontmatter((rules / "fastapi-patterns.mdc").read_text())["globs"] == (
        "**/*.py"
    )
    assert _frontmatter((rules / "postgres-patterns.mdc").read_text())["globs"] == (
        "**/*.sql"
    )
    # A core (non-overlay) rule is description-only — no globs key.
    assert "globs" not in _frontmatter((rules / "testing.mdc").read_text())


def test_go_backend_glob(tmp_path, payload):
    """A non-Python backend derives its own glob from the language table (no per-stack branching)."""
    plan = _plan(payload, backend_language="go", backend_framework="net-http")
    exporter.export_targets(payload, tmp_path, plan, ["cursor"])
    go = tmp_path / ".cursor" / "rules" / "go-patterns.mdc"
    assert go.is_file()
    assert _frontmatter(go.read_text())["globs"] == "**/*.go"


def test_mongodb_overlay_has_no_glob(tmp_path, payload):
    """A document store has no reliable file signal → its overlay loads by description, no globs."""
    plan = _plan(payload, database="mongodb")
    exporter.export_targets(payload, tmp_path, plan, ["cursor"])
    mongo = tmp_path / ".cursor" / "rules" / "mongodb-patterns.mdc"
    assert mongo.is_file()
    fm = _frontmatter(mongo.read_text())
    assert fm.get("description")
    assert "globs" not in fm


# --- MCP projection --------------------------------------------------------------------------------


def test_cursor_mcp_json_strips_type(tmp_path, payload):
    plan = _plan(payload, **_RICH)
    exporter.export_targets(payload, tmp_path, plan, ["cursor"])
    mcp = json.loads((tmp_path / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
    assert "mcpServers" in mcp
    gh = mcp["mcpServers"]["github"]
    assert "command" in gh  # stdio server keeps its launch command
    assert "type" not in gh  # …but the claude-kit discriminator is dropped for Cursor


def test_zero_mcp_writes_no_mcp_json(tmp_path, payload):
    """With no MCP servers selected (the default), no ``.cursor/mcp.json`` is emitted."""
    plan = _plan(payload)  # default selection → mcp == []
    assert not plan.mcp_servers
    exporter.export_targets(payload, tmp_path, plan, ["cursor"])
    assert (tmp_path / ".cursor" / "rules" / "000-project.mdc").is_file()
    assert not (tmp_path / ".cursor" / "mcp.json").exists()


# --- AGENTS.md / Copilot documents -----------------------------------------------------------------


def test_agents_and_copilot_documents(tmp_path, payload):
    plan = _plan(payload, **_RICH)
    exporter.export_targets(payload, tmp_path, plan, ["agents", "copilot"])

    agents = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    copilot = (tmp_path / ".github" / "copilot-instructions.md").read_text(
        encoding="utf-8"
    )
    assert agents == copilot  # same synthesized document
    for body in (agents, copilot):
        assert "SDLC workflow guide" in body  # the single-agent workflow
        assert "What ports from Claude Code" in body  # the honest fidelity note
        assert "Claude-Code-only" in body  # gates/subagents don't reproduce
        assert "Engineering rules (index)" in body  # the rule digest


# --- no application code / no Docker ----------------------------------------------------------------


def test_export_writes_no_appcode_or_docker(tmp_path, payload):
    plan = _plan(payload, **_RICH)
    exporter.export_targets(payload, tmp_path, plan, list(exporter.VALID_TARGETS))

    emitted = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert emitted
    for p in emitted:
        name = p.name.lower()
        assert name != "dockerfile" and not name.startswith("docker-compose")
        assert p.suffix != ".py"  # configuration only — never source code
        body = p.read_text(encoding="utf-8").lower()
        assert "dockerfile" not in body and "docker-compose" not in body
    # Every Cursor rule is a .mdc (no stray file types leaked into the tree).
    for p in (tmp_path / ".cursor" / "rules").iterdir():
        assert p.suffix == ".mdc"


# --- CLI surface -----------------------------------------------------------------------------------


def test_cli_export_dry_run_writes_nothing(tmp_path):
    target = tmp_path / "proj"
    assert runner.invoke(app, ["init", str(target), "--defaults"]).exit_code == 0
    result = runner.invoke(app, ["export", str(target), "-t", "cursor", "--dry-run"])
    assert result.exit_code == 0, result.stdout
    assert "nothing written" in result.stdout
    assert not (target / ".cursor").exists()


def test_cli_export_sidecar_then_force(tmp_path):
    target = tmp_path / "proj"
    assert runner.invoke(app, ["init", str(target), "--defaults"]).exit_code == 0
    charter = target / ".cursor" / "rules" / "000-project.mdc"

    # First real export creates the charter.
    assert runner.invoke(app, ["export", str(target), "-t", "cursor"]).exit_code == 0
    assert charter.is_file()

    # A hand-edit must survive a re-export without --force (content lands in a sidecar).
    charter.write_text("USER EDIT\n", encoding="utf-8")
    assert runner.invoke(app, ["export", str(target), "-t", "cursor"]).exit_code == 0
    assert charter.read_text(encoding="utf-8") == "USER EDIT\n"
    assert charter.with_name("000-project.mdc.claude-kit").is_file()

    # --force is the documented escape hatch: it refreshes the file in place.
    assert (
        runner.invoke(app, ["export", str(target), "-t", "cursor", "--force"]).exit_code
        == 0
    )
    assert charter.read_text(encoding="utf-8").startswith("---")


def test_cli_export_reads_installed_selection(tmp_path, payload):
    """`export` with no --config/--defaults resolves from the project's saved selection."""
    target = tmp_path / "proj"
    install(payload, target, mcp=["github"])  # non-default: pins an MCP server
    result = runner.invoke(app, ["export", str(target), "-t", "cursor"])
    assert result.exit_code == 0, result.stdout
    # The default selection has no MCP, so an emitted mcp.json proves the saved one was read.
    mcp = json.loads((target / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
    assert "github" in mcp["mcpServers"]


def test_cli_export_unknown_target_errors(tmp_path):
    target = tmp_path / "proj"
    assert runner.invoke(app, ["init", str(target), "--defaults"]).exit_code == 0
    result = runner.invoke(app, ["export", str(target), "-t", "bogus"])
    assert result.exit_code == 2
    assert "unknown export target" in result.stderr.lower()


def test_cli_export_json_output(tmp_path):
    target = tmp_path / "proj"
    assert runner.invoke(app, ["init", str(target), "--defaults"]).exit_code == 0
    result = runner.invoke(app, ["export", str(target), "-t", "agents", "--json"])
    assert result.exit_code == 0, result.stdout
    payload_out = json.loads(result.stdout)
    assert payload_out["targets"] == ["agents"]
    assert "AGENTS.md" in payload_out["written"]
