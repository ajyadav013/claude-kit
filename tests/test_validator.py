"""validate / doctor: green on a fresh install, red when the config is broken."""

from __future__ import annotations

from claude_kit import validator
from tests._helpers import install


def test_validate_is_green_on_fresh_install(tmp_path, payload):
    install(payload, tmp_path)
    ok, messages = validator.validate(tmp_path)
    assert ok, "\n".join(messages)
    assert any(m.startswith("OK") and "frontmatter complete" in m for m in messages)


def test_validate_fails_when_a_rule_is_deleted(tmp_path, payload):
    install(payload, tmp_path)
    # Remove a recorded file → validate must catch the missing tracked file.
    (tmp_path / ".claude" / "rules" / "quality-gates.md").unlink()
    ok, messages = validator.validate(tmp_path)
    assert not ok
    assert any(m.startswith("FAIL") for m in messages)


def test_validate_fails_when_not_installed(tmp_path):
    ok, messages = validator.validate(tmp_path)
    assert not ok
    assert any("no .claude" in m for m in messages)


def test_doctor_runs_environment_checks(tmp_path, payload):
    install(payload, tmp_path)
    ok, messages = validator.doctor(tmp_path)
    assert ok, "\n".join(messages)
    assert any(".claude/state/ is gitignored" in m for m in messages)


def test_doctor_warns_on_windows_without_jq(tmp_path, payload, monkeypatch):
    """doctor: Windows + no jq → actionable WSL/Git Bash guidance, and never a failure."""
    install(payload, tmp_path)
    monkeypatch.setattr(validator.platform, "system", lambda: "Windows")
    monkeypatch.setattr(validator.shutil, "which", lambda _tool: None)
    ok, messages = validator.doctor(tmp_path)
    assert ok, "\n".join(messages)
    assert any("Windows" in m and "WSL" in m for m in messages)
