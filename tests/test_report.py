"""report.Report parsing + the CLI ``--json`` surfaces (validate/doctor/diff/status/pipeline/init)."""

from __future__ import annotations

import json
from contextlib import ExitStack
from pathlib import Path

from typer.testing import CliRunner

from claude_kit import report, scaffold
from claude_kit.cli import app
from tests._helpers import install

runner = CliRunner()


def _install(target: Path) -> None:
    with ExitStack() as stack:
        install(scaffold.payload_dir(stack), target)


def test_from_lines_parses_status_prefixes():
    rep = report.Report.from_lines(
        False, ["OK    a", "FAIL  b", "WARN  c", "INFO  d", "no prefix"]
    )
    assert [(m.level, m.text) for m in rep.messages] == [
        ("ok", "a"),
        ("fail", "b"),
        ("warn", "c"),
        ("info", "d"),
        ("plain", "no prefix"),
    ]
    assert rep.ok is False


def test_to_json_shape_and_extra():
    rep = report.Report.from_lines(True, ["OK    all good"])
    doc = json.loads(rep.to_json(extra={"strict": True}))
    assert doc == {
        "ok": True,
        "messages": [{"level": "ok", "text": "all good"}],
        "strict": True,
    }


def test_validate_json_output(tmp_path):
    _install(tmp_path)
    res = runner.invoke(app, ["validate", str(tmp_path), "--json"])
    assert res.exit_code == 0, res.output
    doc = json.loads(res.output)
    assert doc["ok"] is True
    assert doc["messages"] and all({"level", "text"} <= set(m) for m in doc["messages"])


def test_validate_text_output_unchanged(tmp_path):
    """The default (text) path must still print prefixed lines, not JSON."""
    _install(tmp_path)
    res = runner.invoke(app, ["validate", str(tmp_path)])
    assert res.exit_code == 0, res.output
    assert "OK" in res.output and not res.output.lstrip().startswith("{")


def test_diff_and_pipeline_json(tmp_path):
    _install(tmp_path)
    for cmd in (
        ["diff", str(tmp_path), "--json"],
        ["pipeline", "validate", str(tmp_path), "--json"],
        ["pipeline", "status", str(tmp_path), "--json"],
    ):
        res = runner.invoke(app, cmd)
        assert res.exit_code == 0, (cmd, res.output)
        assert "messages" in json.loads(res.output)


def test_status_json_output(tmp_path):
    _install(tmp_path)
    res = runner.invoke(app, ["status", str(tmp_path), "--json"])
    assert res.exit_code == 0, res.output
    doc = json.loads(res.output)
    assert doc["installed"] is True
    assert set(doc["components"]) == {"rules", "agents", "skills", "hooks"}
    assert doc["selection"] is not None


def test_status_json_not_installed(tmp_path):
    res = runner.invoke(app, ["status", str(tmp_path / "nope"), "--json"])
    assert res.exit_code == 0, res.output
    assert json.loads(res.output)["installed"] is False


def test_init_dry_run_json(tmp_path):
    res = runner.invoke(
        app, ["init", str(tmp_path / "proj"), "--defaults", "--dry-run", "--json"]
    )
    assert res.exit_code == 0, res.output
    doc = json.loads(res.output)
    assert doc["dry_run"] is True
    assert (
        doc["profile"] and isinstance(doc["would_write"], list) and doc["would_write"]
    )
    assert not (tmp_path / "proj" / ".claude").exists()  # dry run wrote nothing


def test_init_json_requires_dry_run(tmp_path):
    res = runner.invoke(app, ["init", str(tmp_path / "proj"), "--defaults", "--json"])
    assert res.exit_code == 2
    assert "--dry-run" in res.output
