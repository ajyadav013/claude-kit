"""validate / doctor: green on a fresh install, red when the config is broken."""

from __future__ import annotations

import json

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


def test_validate_warns_on_kit_owned_drift(tmp_path, payload):
    """A hand-edited kit/overlay file is surfaced via the sha256 manifest, not just presence (WARN)."""
    install(payload, tmp_path)
    opts = json.loads(
        (tmp_path / ".claude" / "config" / "init-options.json").read_text(
            encoding="utf-8"
        )
    )
    rec = next(
        f
        for f in opts["files"]
        if f["owner"] in ("kit", "overlay") and f["path"].endswith(".md")
    )
    fp = tmp_path / rec["path"]
    fp.write_text(
        fp.read_text(encoding="utf-8") + "\n<!-- local edit -->\n", encoding="utf-8"
    )
    ok, messages = validator.validate(tmp_path)
    assert ok, "\n".join(messages)  # drift is a WARN, never a FAIL
    assert any(
        m.startswith("WARN")
        and "modified since install" in m
        and "claude-kit diff" in m
        for m in messages
    ), "\n".join(messages)


def test_validate_fails_on_corrupt_init_options(tmp_path, payload):
    """A corrupt manifest is a distinct, louder signal (FAIL) — not the same as a missing one."""
    install(payload, tmp_path)
    (tmp_path / ".claude" / "config" / "init-options.json").write_text(
        "{ not valid json", encoding="utf-8"
    )
    ok, messages = validator.validate(tmp_path)
    assert not ok
    assert any(m.startswith("FAIL") and "unreadable" in m for m in messages), "\n".join(
        messages
    )


def test_validate_warns_on_missing_init_options(tmp_path, payload):
    """A missing manifest (old install) stays a WARN, distinct from the corrupt FAIL above."""
    install(payload, tmp_path)
    (tmp_path / ".claude" / "config" / "init-options.json").unlink()
    ok, messages = validator.validate(tmp_path)
    assert any(
        m.startswith("WARN") and "no .claude/config/init-options.json" in m
        for m in messages
    ), "\n".join(messages)
    assert not any("unreadable" in m for m in messages)


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


# --- strict installed-config checks ---------------------------------------------------------------


def test_strict_validate_green_on_fresh_install(tmp_path, payload):
    install(payload, tmp_path)
    ok, messages = validator.validate(tmp_path, strict=True)
    assert ok, "\n".join(messages)
    assert any("fire on known events" in m for m in messages)
    assert any(m.startswith("OK    catalog:") for m in messages)


def test_strict_validate_flags_nonexecutable_hook_script(tmp_path, payload):
    install(payload, tmp_path)
    script = next((tmp_path / ".claude" / "hooks").glob("*.sh"))
    script.chmod(0o644)
    ok, messages = validator.validate(tmp_path, strict=True)
    assert not ok
    assert any("not executable" in m and script.name in m for m in messages)
    # Non-strict validate stays green — the deep check is opt-in.
    assert validator.validate(tmp_path)[0]


def test_strict_validate_flags_unknown_hook_event(tmp_path, payload):
    install(payload, tmp_path)
    settings = tmp_path / ".claude" / "settings.json"
    doc = json.loads(settings.read_text(encoding="utf-8"))
    doc["hooks"]["NotARealEvent"] = [{"matcher": "", "hooks": []}]
    settings.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    ok, messages = validator.validate(tmp_path, strict=True)
    assert not ok
    assert any("unknown event" in m and "NotARealEvent" in m for m in messages)


def test_strict_validate_flags_broken_mcp_json(tmp_path, payload):
    install(payload, tmp_path, mcp=["github"])
    mcp = tmp_path / ".mcp.json"
    mcp.write_text(json.dumps({"mcpServers": {"github": {}}}), encoding="utf-8")
    ok, messages = validator.validate(tmp_path, strict=True)
    assert not ok
    assert any("neither a command nor a url" in m for m in messages)


def test_strict_validate_flags_snapshot_drift(tmp_path, payload):
    plan = install(payload, tmp_path)
    # Delete an installed overlay rule that the snapshot still records.
    overlay = plan.overlay_rules[0]
    (tmp_path / ".claude" / "rules" / overlay).unlink()
    ok, messages = validator.validate(tmp_path, strict=True)
    assert not ok
    assert any("snapshot lists files not installed" in m for m in messages)


# --- catalog referential integrity ----------------------------------------------------------------


def test_check_catalog_clean_on_bundled_payload(payload):
    ok, messages = validator.check_catalog(payload)
    assert ok, "\n".join(messages)
    assert any("profiles reference only existing" in m for m in messages)


def _minimal_payload(root, *, profile_agents, overlay_rules=(), profile_skills=()):
    """Build a tiny payload tree just sufficient for check_catalog to run."""
    (root / "catalog").mkdir(parents=True)
    (root / "agents").mkdir()
    (root / "skills").mkdir()
    (root / "catalog" / "stacks.yaml").write_text(
        "frontend:\n"
        "  default: react\n"
        "  frameworks:\n"
        "    react:\n"
        "      label: React\n"
        "      stack_dir: frontend/react\n"
        f"      overlay_rules: [{', '.join(overlay_rules)}]\n"
        "backend:\n"
        "  default: python\n"
        "  languages:\n"
        "    python:\n"
        "      label: Python\n"
        "      default_framework: fastapi\n"
        "      frameworks:\n"
        "        fastapi: {label: FastAPI, stack_dir: backend/fastapi}\n"
        "database:\n"
        "  default: postgres\n"
        "  options:\n"
        "    postgres: {label: Postgres, stack_dir: database/postgres}\n",
        encoding="utf-8",
    )
    (root / "catalog" / "profiles.yaml").write_text(
        "version: 1\ndefault: lean\nprofiles:\n"
        "  lean:\n"
        f"    agents: [{', '.join(profile_agents)}]\n"
        f"    skills: [{', '.join(profile_skills)}]\n"
        "    gates: []\n"
        "    hooks: [load-continuity]\n",
        encoding="utf-8",
    )


def test_check_catalog_detects_profile_referencing_missing_agent(tmp_path):
    _minimal_payload(tmp_path, profile_agents=["ghost"])
    ok, messages = validator.check_catalog(tmp_path)
    assert not ok
    assert any("agent ghost" in m for m in messages)


def test_check_catalog_detects_missing_stack_overlay(tmp_path):
    _minimal_payload(tmp_path, profile_agents=[], overlay_rules=["nope-patterns.md"])
    ok, messages = validator.check_catalog(tmp_path)
    assert not ok
    assert any(
        "overlay files missing" in m and "nope-patterns.md" in m for m in messages
    )


def test_check_catalog_detects_duplicate_skill_in_profile(tmp_path):
    _minimal_payload(
        tmp_path,
        profile_agents=[],
        profile_skills=["api-integration", "api-integration"],
    )
    skill = tmp_path / "skills" / "api-integration"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: api-integration\ndescription: x\n---\n", encoding="utf-8"
    )
    ok, messages = validator.check_catalog(tmp_path)
    assert not ok
    assert any("duplicate skill" in m and "api-integration" in m for m in messages), (
        "\n".join(messages)
    )


def test_doctor_mcp_warns_on_unset_env(tmp_path, payload, monkeypatch):
    install(payload, tmp_path, mcp=["github"])
    monkeypatch.delenv("GITHUB_PERSONAL_ACCESS_TOKEN", raising=False)
    ok, messages = validator.doctor(tmp_path, mcp=True)
    assert ok, "\n".join(messages)
    assert any(
        "GITHUB_PERSONAL_ACCESS_TOKEN" in m and m.startswith("WARN") for m in messages
    )


def test_strict_validate_flags_hook_referencing_missing_script(tmp_path, payload):
    install(payload, tmp_path)
    settings = tmp_path / ".claude" / "settings.json"
    doc = json.loads(settings.read_text(encoding="utf-8"))
    doc["hooks"]["SessionStart"] = [
        {"matcher": "", "hooks": [{"command": ".claude/hooks/nonexistent.sh"}]}
    ]
    settings.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    ok, messages = validator.validate(tmp_path, strict=True)
    assert not ok
    assert any("missing script" in m and "nonexistent.sh" in m for m in messages)


def test_check_catalog_detects_missing_org_overlay(tmp_path):
    _minimal_payload(tmp_path, profile_agents=[])
    (tmp_path / "catalog" / "org.yaml").write_text(
        "new_skills: [ghost-skill]\n", encoding="utf-8"
    )
    ok, messages = validator.check_catalog(tmp_path)
    assert not ok
    assert any(
        "org overlay files missing" in m and "ghost-skill" in m for m in messages
    )


def test_check_catalog_detects_bad_org_core_agent(tmp_path):
    _minimal_payload(tmp_path, profile_agents=[])
    (tmp_path / "catalog" / "org.yaml").write_text(
        "core_agents_added: [nonexistent]\n", encoding="utf-8"
    )
    ok, messages = validator.check_catalog(tmp_path)
    assert not ok
    assert any("core_agents_added not found" in m for m in messages)


def test_check_catalog_detects_stack_suggesting_missing_skill(tmp_path):
    (tmp_path / "catalog").mkdir(parents=True)
    (tmp_path / "agents").mkdir()
    (tmp_path / "skills").mkdir()
    (tmp_path / "catalog" / "stacks.yaml").write_text(
        "frontend:\n"
        "  default: react\n"
        "  frameworks:\n"
        "    react:\n"
        "      label: React\n"
        "      stack_dir: frontend/react\n"
        "      skills: [nonexistent-skill]\n"
        "backend: {default: python, languages: {python: {label: Python, "
        "default_framework: fastapi, frameworks: {fastapi: {label: FastAPI, "
        "stack_dir: backend/fastapi}}}}}\n"
        "database: {default: postgres, options: {postgres: {label: Postgres, "
        "stack_dir: database/postgres}}}\n",
        encoding="utf-8",
    )
    (tmp_path / "catalog" / "profiles.yaml").write_text(
        "version: 1\ndefault: lean\nprofiles:\n"
        "  lean: {agents: [], skills: [], gates: [], hooks: []}\n",
        encoding="utf-8",
    )
    ok, messages = validator.check_catalog(tmp_path)
    assert not ok
    assert any(
        "stacks suggest missing skills" in m and "nonexistent-skill" in m
        for m in messages
    )


def _append_to_rule(tmp_path, payload_text):
    """Append text to an installed rule file (drift is a WARN, so ok is unaffected by the edit itself)."""
    rule = tmp_path / ".claude" / "rules" / "quality-gates.md"
    rule.write_text(rule.read_text(encoding="utf-8") + payload_text, encoding="utf-8")


def test_strict_validate_fails_on_critical_hidden_unicode(tmp_path, payload):
    """A bidi override in deployed prose is an invisible-instruction channel → strict FAIL."""
    install(payload, tmp_path)
    _append_to_rule(tmp_path, "\n\u202egnihton od\u202c\n")
    ok, messages = validator.validate(tmp_path, strict=True)
    assert not ok
    assert any(
        m.startswith("FAIL") and "hidden unicode" in m and "bidi" in m for m in messages
    ), "\n".join(messages)


def test_strict_validate_warns_on_zero_width_characters(tmp_path, payload):
    install(payload, tmp_path)
    _append_to_rule(tmp_path, "\nzero\u200bwidth\n")
    ok, messages = validator.validate(tmp_path, strict=True)
    assert ok, "\n".join(messages)  # suspicious, not fatal
    assert any(m.startswith("WARN") and "zero-width" in m for m in messages)


def test_strict_validate_flags_midfile_bom(tmp_path, payload):
    """A leading BOM is a benign encoding artifact; one appearing mid-file is flagged (WARN)."""
    install(payload, tmp_path)
    _append_to_rule(tmp_path, "\nx\ufeffy\n")
    ok, messages = validator.validate(tmp_path, strict=True)
    assert ok, "\n".join(messages)
    assert any(
        m.startswith("WARN") and "byte-order mark mid-file" in m for m in messages
    )


def test_strict_validate_reports_nbsp_as_info(tmp_path, payload):
    install(payload, tmp_path)
    _append_to_rule(tmp_path, "\nnon\u00a0breaking\n")
    ok, messages = validator.validate(tmp_path, strict=True)
    assert ok, "\n".join(messages)
    assert any(m.startswith("INFO") and "non-breaking" in m for m in messages)


def test_strict_validate_unicode_clean_on_fresh_install(tmp_path, payload):
    """The shipped payload itself must stay free of hidden Unicode on every tier."""
    install(payload, tmp_path)
    ok, messages = validator.validate(tmp_path, strict=True)
    assert ok, "\n".join(messages)
    assert any(
        m.startswith("OK") and "free of hidden/deceptive Unicode" in m for m in messages
    )
    assert not any(m.startswith("INFO") and "hidden unicode" in m for m in messages)


def test_nonstrict_validate_skips_unicode_scan(tmp_path, payload):
    install(payload, tmp_path)
    _append_to_rule(tmp_path, "\n\u202e\n")
    ok, messages = validator.validate(tmp_path)
    assert ok, "\n".join(messages)  # the scan is a strict-mode check
    assert not any("hidden unicode" in m for m in messages)
