"""validate / doctor: green on a fresh install, red when the config is broken."""

from __future__ import annotations

import json
import shutil

import pytest
import yaml

from claude_kit import catalog, validator
from claude_kit.models import InstallRequest
from claude_kit.runtime_scaffold import install_runtime
from claude_kit.secure_fs import ProjectFS, ProjectTransaction
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


@pytest.mark.parametrize(
    "document",
    [[], {"claude_kit_version": "0.82.0", "selection": [], "files": []}],
)
def test_validate_fails_cleanly_on_wrong_shaped_init_options(
    tmp_path, payload, document
):
    install(payload, tmp_path)
    config = tmp_path / ".claude" / "config" / "init-options.json"
    config.write_text(json.dumps(document), encoding="utf-8")

    ok, messages = validator.validate(tmp_path, strict=True)

    assert not ok
    assert any("init-options.json is unreadable" in message for message in messages)


def test_validate_fails_when_installed_selection_no_longer_resolves(tmp_path, payload):
    install(payload, tmp_path)
    options = tmp_path / ".claude" / "config" / "init-options.json"
    document = json.loads(options.read_text(encoding="utf-8"))
    document["selection"]["profile"] = "bogus-profile"
    options.write_text(json.dumps(document), encoding="utf-8")

    ok, messages = validator.validate(tmp_path, strict=True)

    assert not ok
    assert any("selection that does not resolve" in message for message in messages)
    assert any("bogus-profile" in message for message in messages)


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
    """doctor separates native mutation refusal from the missing hook runtime."""
    install(payload, tmp_path)
    monkeypatch.setattr(validator.platform, "system", lambda: "Windows")
    monkeypatch.setattr(validator.shutil, "which", lambda _tool: None)
    ok, messages = validator.doctor(tmp_path)
    assert ok, "\n".join(messages)
    assert any(
        "native Windows project mutation is unsupported" in m and "WSL" in m
        for m in messages
    )
    assert any("hooks" in m and "jq not on PATH" in m for m in messages)


# --- strict installed-config checks ---------------------------------------------------------------


def _install_native_mcp(payload, target, runtime, server_id):
    selection = catalog.defaults(payload)
    selection.mcp = [server_id]
    plan = catalog.resolve(payload, selection)
    install_runtime(payload, target, plan, InstallRequest(selection, runtime))


@pytest.mark.parametrize(
    ("server_id", "field"),
    [
        ("github", "command"),
        ("github", "args"),
        ("github", "env"),
        ("linear", "url"),
        ("linear", "headers"),
    ],
)
def test_native_strict_validation_rejects_claude_mcp_semantic_changes(
    tmp_path, payload, server_id, field
):
    target = tmp_path / f"claude-{field}"
    _install_native_mcp(payload, target, "claude", server_id)
    path = target / ".mcp.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    server = document["mcpServers"][server_id]
    if field == "command":
        server["command"] = "user-modified"
    elif field == "args":
        server["args"] = [*server["args"], "--user-modified"]
    elif field == "env":
        server["env"] = {"GITHUB_PERSONAL_ACCESS_TOKEN": "${OTHER_TOKEN}"}
    elif field == "url":
        server["url"] = "https://example.invalid/mcp"
    else:
        server["headers"] = {"X-Debug": "user-modified"}
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")

    ok, messages = validator.validate(target, strict=True)

    assert not ok
    assert any(
        f"Claude MCP server '{server_id}' differs from the current resolved "
        "native projection" in message
        for message in messages
    ), "\n".join(messages)


@pytest.mark.parametrize(
    ("server_id", "old", "new"),
    [
        ("github", '"command" = "npx"', '"command" = "user-modified"'),
        (
            "github",
            '"args" = ["-y", "@modelcontextprotocol/server-github@2025.4.8"]',
            '"args" = ["--user-modified"]',
        ),
        (
            "github",
            '"env_vars" = ["GITHUB_PERSONAL_ACCESS_TOKEN"]',
            '"env_vars" = ["OTHER_TOKEN"]',
        ),
        (
            "linear",
            '"url" = "https://mcp.linear.app/mcp"',
            '"url" = "https://example.invalid/mcp"',
        ),
    ],
)
def test_native_strict_validation_rejects_codex_mcp_semantic_changes(
    tmp_path, payload, server_id, old, new
):
    target = tmp_path / f"codex-{server_id}"
    _install_native_mcp(payload, target, "codex", server_id)
    path = target / ".codex/config.toml"
    content = path.read_text(encoding="utf-8")
    assert content.count(old) == 1
    path.write_text(content.replace(old, new), encoding="utf-8")

    ok, messages = validator.validate(target, strict=True)

    assert not ok
    assert any(
        f"Codex MCP server '{server_id}' differs from the current resolved "
        "native projection" in message
        for message in messages
    ), "\n".join(messages)


def test_native_strict_validation_rejects_codex_mcp_header_changes(tmp_path, payload):
    target = tmp_path / "codex-headers"
    _install_native_mcp(payload, target, "codex", "linear")
    path = target / ".codex/config.toml"
    content = path.read_text(encoding="utf-8")
    content += '\n[mcp_servers."linear".http_headers]\n"X-Debug" = "user-modified"\n'
    path.write_text(content, encoding="utf-8")

    ok, messages = validator.validate(target, strict=True)

    assert not ok
    assert any(
        "Codex MCP server 'linear' differs from the current resolved native projection"
        in message
        for message in messages
    ), "\n".join(messages)


@pytest.mark.parametrize("changed_provider", ["claude", "codex"])
def test_dual_runtime_strict_validation_detects_one_sided_mcp_divergence(
    tmp_path, payload, changed_provider
):
    target = tmp_path / changed_provider
    _install_native_mcp(payload, target, "both", "github")
    if changed_provider == "claude":
        path = target / ".mcp.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        document["mcpServers"]["github"]["command"] = "user-modified"
        path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    else:
        path = target / ".codex/config.toml"
        content = path.read_text(encoding="utf-8")
        assert content.count('"command" = "npx"') == 1
        path.write_text(
            content.replace('"command" = "npx"', '"command" = "user-modified"'),
            encoding="utf-8",
        )

    ok, messages = validator.validate(target, strict=True)

    assert not ok
    label = changed_provider.title()
    other = "Codex" if label == "Claude" else "Claude"
    assert any(
        f"{label} MCP server 'github' differs" in message for message in messages
    ), "\n".join(messages)
    assert not any(
        f"{other} MCP server 'github' differs" in message for message in messages
    ), "\n".join(messages)


def test_native_strict_validation_allows_unselected_user_mcp_servers(tmp_path, payload):
    target = tmp_path / "user-servers"
    (target / ".codex").mkdir(parents=True)
    (target / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"user-claude": {"command": "user-command"}}}) + "\n",
        encoding="utf-8",
    )
    (target / ".codex/config.toml").write_text(
        '[mcp_servers."user-codex"]\ncommand = "user-command"\n',
        encoding="utf-8",
    )
    _install_native_mcp(payload, target, "both", "github")

    ok, messages = validator.validate(target, strict=True)

    assert ok, "\n".join(messages)
    assert any(
        "Claude MCP config exactly matches every selected server projection" in message
        for message in messages
    )
    assert any(
        "Codex MCP config exactly matches every selected server projection" in message
        for message in messages
    )


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


def test_strict_validate_warns_on_unrecognized_future_hook_event(tmp_path, payload):
    install(payload, tmp_path)
    settings = tmp_path / ".claude" / "settings.json"
    doc = json.loads(settings.read_text(encoding="utf-8"))
    doc["hooks"]["NotARealEvent"] = [{"matcher": "", "hooks": []}]
    settings.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    ok, messages = validator.validate(tmp_path, strict=True)
    assert ok, "\n".join(messages)
    assert any(
        m.startswith("WARN") and "NotARealEvent" in m and "official validator" in m
        for m in messages
    )


def test_strict_validate_accepts_current_official_hook_events(tmp_path, payload):
    install(payload, tmp_path)
    settings = tmp_path / ".claude" / "settings.json"
    doc = json.loads(settings.read_text(encoding="utf-8"))
    for event in (
        "PostToolUseFailure",
        "PermissionRequest",
        "SubagentStart",
        "Setup",
        "TeammateIdle",
        "TaskCompleted",
        "ConfigChange",
        "WorktreeCreate",
        "ElicitationResult",
    ):
        doc["hooks"][event] = []
    settings.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    ok, messages = validator.validate(tmp_path, strict=True)
    assert ok, "\n".join(messages)
    assert not any("not in the tested compatibility catalog" in m for m in messages)


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
    assert any("workflows/sdlc.yaml matches its JSON Schema" in m for m in messages)


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


# --- Frontmatter parsing: the lenient reader must mirror Claude Code's, not strict YAML ----------


def _uninstall(tmp_path, *rel_paths):
    """Delete installed paths *and* drop their manifest records.

    Removing a file alone is a different scenario ("recorded file missing"); these tests are about
    how validate behaves when an optional piece was never installed at all.
    """
    cfg = tmp_path / ".claude" / "config" / "init-options.json"
    doc = json.loads(cfg.read_text(encoding="utf-8"))
    doc["files"] = [
        r for r in doc["files"] if not any(r["path"].startswith(p) for p in rel_paths)
    ]
    cfg.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    for rel in rel_paths:
        path = tmp_path / rel
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()


def _write_agent(tmp_path, name, text):
    path = tmp_path / ".claude" / "agents" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_validate_flags_agent_without_any_frontmatter(tmp_path, payload):
    install(payload, tmp_path)
    _write_agent(tmp_path, "bare.md", "# just a heading\n")
    ok, messages = validator.validate(tmp_path)
    assert not ok
    assert any(
        "missing name/description frontmatter" in m and "bare.md" in m for m in messages
    )


def test_validate_flags_agent_with_unterminated_frontmatter(tmp_path, payload):
    install(payload, tmp_path)
    _write_agent(tmp_path, "unterminated.md", "---\nname: x\ndescription: y\n")
    ok, messages = validator.validate(tmp_path)
    assert not ok
    assert any("unterminated.md" in m for m in messages)


def test_validate_accepts_frontmatter_with_comments_and_bare_lines(tmp_path, payload):
    """Blank lines, indented continuations, comments, and colon-free lines are skipped, not fatal."""
    install(payload, tmp_path)
    _write_agent(
        tmp_path,
        "annotated.md",
        "---\n# a comment\nname: annotated\n\nbare-line-without-a-colon\n"
        "description: Reviews things \u2014 read-only: never edits\n  continued: indented\n---\nbody\n",
    )
    ok, messages = validator.validate(tmp_path)
    assert ok, "\n".join(messages)


# --- Absent optional pieces are warnings, not crashes -------------------------------------------


def test_validate_warns_when_settings_json_is_absent(tmp_path, payload):
    install(payload, tmp_path)
    _uninstall(tmp_path, ".claude/settings.json")
    ok, messages = validator.validate(tmp_path)
    assert ok, "\n".join(messages)
    assert any("no .claude/settings.json" in m for m in messages)


def test_validate_warns_when_agents_dir_is_absent(tmp_path, payload):
    install(payload, tmp_path)
    _uninstall(tmp_path, ".claude/agents")
    ok, messages = validator.validate(tmp_path)
    assert ok, "\n".join(messages)
    assert any("no .claude/agents/" in m for m in messages)


def test_validate_is_quiet_when_skills_dir_is_absent(tmp_path, payload):
    install(payload, tmp_path)
    _uninstall(tmp_path, ".claude/skills")
    ok, messages = validator.validate(tmp_path)
    assert ok, "\n".join(messages)
    assert not any("skills/" in m for m in messages)


def test_validate_flags_skill_without_a_description(tmp_path, payload):
    install(payload, tmp_path)
    skill = tmp_path / ".claude" / "skills" / "undocumented"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: undocumented\n---\nbody\n", encoding="utf-8"
    )
    ok, messages = validator.validate(tmp_path)
    assert not ok
    assert any(
        "skills missing description" in m and "undocumented" in m for m in messages
    )


def test_validate_fails_when_the_rules_dir_is_empty(tmp_path, payload):
    install(payload, tmp_path)
    rules = tmp_path / ".claude" / "rules"
    for rule in rules.glob("*.md"):
        rule.unlink()
    ok, messages = validator.validate(tmp_path)
    assert not ok
    assert any("no .claude/rules/ content" in m for m in messages)


def test_strict_validate_fails_when_the_catalog_is_inconsistent(
    tmp_path, payload, monkeypatch
):
    """validate --strict must inherit a catalog failure rather than reporting a green install."""
    install(payload, tmp_path)
    monkeypatch.setattr(
        validator,
        "check_catalog",
        lambda *a, **k: (False, ["FAIL  catalog: synthetic defect"]),
    )
    ok, messages = validator.validate(tmp_path, strict=True)
    assert not ok
    assert any("synthetic defect" in m for m in messages)


# --- Strict checks skip absent optional inputs but reject malformed ones -------------------------


def test_strict_checks_skip_absent_settings_and_snapshot(tmp_path, payload):
    install(payload, tmp_path)
    _uninstall(
        tmp_path, ".claude/settings.json", ".claude/config/stack-catalog.snapshot.yaml"
    )
    ok, messages = validator.validate(tmp_path, strict=True)
    assert ok, "\n".join(messages)
    assert not any("settings.json hooks" in m for m in messages)
    assert not any("stack snapshot" in m for m in messages)


def test_strict_checks_reject_settings_json_that_is_not_an_object(tmp_path, payload):
    install(payload, tmp_path)
    (tmp_path / ".claude" / "settings.json").write_text("[]", encoding="utf-8")
    ok, messages = validator.validate(tmp_path, strict=True)
    assert not ok
    assert any("settings.json root must be an object" in m for m in messages)


def test_strict_validate_checks_a_present_pipeline_snapshot(tmp_path, payload):
    install(payload, tmp_path)
    state = tmp_path / ".claude" / "state"
    state.mkdir(parents=True, exist_ok=True)
    (state / "pipeline-snapshot.json").write_text(
        json.dumps({"schema": 1, "profile": "standard", "mode": "B"}), encoding="utf-8"
    )
    ok, messages = validator.validate(tmp_path, strict=True)
    assert ok, "\n".join(messages)
    assert any("pipeline-snapshot.json matches" in m for m in messages)


def test_strict_validate_flags_an_mcp_lock_that_breaks_its_schema(tmp_path, payload):
    install(payload, tmp_path)
    (tmp_path / ".mcp.lock.json").write_text(
        json.dumps({"servers": {}}), encoding="utf-8"
    )  # no required "schema" key
    ok, messages = validator.validate(tmp_path, strict=True)
    assert not ok
    assert any(".mcp.lock.json fails its JSON Schema" in m for m in messages)


def test_strict_validate_flags_mcp_json_without_servers(tmp_path, payload):
    install(payload, tmp_path)
    (tmp_path / ".mcp.json").write_text(json.dumps({"servers": {}}), encoding="utf-8")
    ok, messages = validator.validate(tmp_path, strict=True)
    assert not ok
    assert any("no valid 'mcpServers' object" in m for m in messages)


def test_strict_validate_fails_cleanly_on_non_object_mcp_and_settings(
    tmp_path, payload
):
    install(payload, tmp_path)
    (tmp_path / ".mcp.json").write_text("[]\n", encoding="utf-8")
    (tmp_path / ".claude" / "settings.json").write_text(
        json.dumps({"hooks": []}), encoding="utf-8"
    )

    ok, messages = validator.validate(tmp_path, strict=True)

    assert not ok
    assert any(".mcp.json root must be an object" in message for message in messages)
    assert any(
        "settings.json 'hooks' must be an object" in message for message in messages
    )

    doctor_ok, doctor_messages = validator.doctor(tmp_path, mcp=True)
    assert not doctor_ok
    assert any("no valid mcpServers object" in message for message in doctor_messages)


def test_strict_validate_flags_snapshot_listing_missing_agent_and_skill(
    tmp_path, payload
):
    install(payload, tmp_path)
    snap = tmp_path / ".claude" / "config" / "stack-catalog.snapshot.yaml"
    snap.write_text(
        "agents: [ghost-agent]\nskills: [ghost-skill]\noverlay_agents: []\noverlay_rules: []\n",
        encoding="utf-8",
    )
    ok, messages = validator.validate(tmp_path, strict=True)
    assert not ok
    joined = "\n".join(messages)
    assert "agents/ghost-agent.md" in joined and "skills/ghost-skill/SKILL.md" in joined


def test_strict_validate_fails_cleanly_on_non_object_stack_snapshot(tmp_path, payload):
    install(payload, tmp_path)
    snap = tmp_path / ".claude" / "config" / "stack-catalog.snapshot.yaml"
    snap.write_text("[wrong-root]\n", encoding="utf-8")

    ok, messages = validator.validate(tmp_path, strict=True)

    assert not ok
    assert any(
        "stack snapshot root must be an object" in message for message in messages
    )
    assert any("fails its JSON Schema" in message for message in messages)


def test_strict_validate_directs_legacy_stack_snapshots_to_upgrade(tmp_path, payload):
    """Pre-0.83 snapshots fail closed with a migration command, not only schema jargon."""
    install(payload, tmp_path)
    snap = tmp_path / ".claude" / "config" / "stack-catalog.snapshot.yaml"
    doc = yaml.safe_load(snap.read_text(encoding="utf-8"))
    doc.pop("schema_version")
    doc.pop("gate_definitions")
    doc.pop("gate_definition_digest")
    snap.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")

    ok, messages = validator.validate(tmp_path, strict=True)

    assert not ok
    assert any(
        "legacy unversioned stack snapshot" in message
        and "claude-kit upgrade" in message
        for message in messages
    )


def test_strict_schema_artifact_check_fails_closed_without_jsonschema(
    tmp_path, payload, monkeypatch
):
    """Strict validation must never silently accept an unvalidated artifact."""
    from claude_kit import schemas

    install(payload, tmp_path)
    (tmp_path / ".mcp.lock.json").write_text(
        json.dumps({"servers": {}}), encoding="utf-8"
    )
    monkeypatch.setattr(schemas, "available", lambda: False)
    ok, messages = validator.validate(tmp_path, strict=True)
    assert not ok
    assert any(
        m.startswith("FAIL")
        and "jsonschema not installed" in m
        and "cannot continue" in m
        for m in messages
    )


def test_unicode_findings_are_capped_with_a_remainder_line(tmp_path, payload):
    """A poisoned tree stays readable: the first hits name the files, the rest are counted."""
    install(payload, tmp_path)
    rules = tmp_path / ".claude" / "rules"
    for i in range(10):
        (rules / f"poisoned-{i}.md").write_text(
            f"# r{i}\n\U000e0041\n", encoding="utf-8"
        )
    ok, messages = validator.validate(tmp_path, strict=True)
    assert not ok
    assert any("more critical finding(s)" in m for m in messages)


def test_unicode_scan_covers_a_project_without_a_root_claude_md(tmp_path, payload):
    install(payload, tmp_path)
    _uninstall(tmp_path, "CLAUDE.md")
    ok, messages = validator.validate(tmp_path, strict=True)
    assert ok, "\n".join(messages)
    assert any("free of hidden/deceptive Unicode" in m for m in messages)


# --- Catalog integrity: org overlay and stack-entry edge cases ----------------------------------


def test_iter_stack_entries_skips_planned_entries():
    """Planned (not-yet-shipped) stack entries carry no overlay files, so they are not checked."""
    stacks = {
        "frontend": {
            "frameworks": {"vue": {"status": "planned", "stack_dir": "frontend/vue"}}
        },
        "backend": {
            "languages": {
                "rust": {
                    "status": "planned",
                    "frameworks": {"axum": {"stack_dir": "x"}},
                },
                "python": {
                    "frameworks": {
                        "fastapi": {"stack_dir": "backend/fastapi"},
                        "django": {"status": "planned", "stack_dir": "backend/django"},
                    }
                },
            }
        },
        "database": {
            "options": {
                "postgres": {"stack_dir": "database/postgres"},
                "mysql": {"status": "planned", "stack_dir": "database/mysql"},
            }
        },
    }
    dirs = [d for _entry, d in validator._iter_stack_entries(stacks)]
    assert dirs == ["backend/fastapi", "database/postgres"]


def test_check_catalog_detects_missing_stack_overlay_agent(tmp_path):
    (tmp_path / "catalog").mkdir(parents=True)
    (tmp_path / "agents").mkdir()
    (tmp_path / "skills").mkdir()
    (tmp_path / "catalog" / "stacks.yaml").write_text(
        "frontend: {default: react, frameworks: {react: {label: React, "
        "stack_dir: frontend/react}}}\n"
        "backend: {default: python, languages: {python: {label: Python, "
        "default_framework: fastapi, frameworks: {fastapi: {label: FastAPI, "
        "stack_dir: backend/fastapi}}}}}\n"
        "database: {default: postgres, options: {postgres: {label: Postgres, "
        "stack_dir: database/postgres, overlay_agents: [ghost-specialist]}}}\n",
        encoding="utf-8",
    )
    (tmp_path / "catalog" / "profiles.yaml").write_text(
        "version: 1\ndefault: lean\nprofiles:\n"
        "  lean: {agents: [], skills: [], gates: [], hooks: []}\n",
        encoding="utf-8",
    )
    ok, messages = validator.check_catalog(tmp_path)
    assert not ok
    assert any("ghost-specialist.md" in m for m in messages)


def test_check_catalog_detects_missing_org_agents_rules_and_packs(tmp_path):
    _minimal_payload(tmp_path, profile_agents=[])
    (tmp_path / "catalog" / "org.yaml").write_text(
        "new_agents: [ghost-persona]\nnew_rules: [ghost-policy.md]\npacks:\n  - id: ghost-pack\n",
        encoding="utf-8",
    )
    ok, messages = validator.check_catalog(tmp_path)
    assert not ok
    joined = "\n".join(messages)
    assert "agents/ghost-persona.md" in joined
    assert "rules/ghost-policy.md" in joined
    assert "packs/ghost-pack/pack.yaml" in joined


def test_check_catalog_flags_a_pack_manifest_that_breaks_its_schema(tmp_path):
    _minimal_payload(tmp_path, profile_agents=[])
    pack = tmp_path / "templates" / "org" / "packs" / "broken"
    pack.mkdir(parents=True)
    (pack / "pack.yaml").write_text(
        "purpose: no id, label or version\n", encoding="utf-8"
    )
    ok, messages = validator.check_catalog(tmp_path)
    assert not ok
    assert any("broken/pack.yaml fails its JSON Schema" in m for m in messages)


def test_check_catalog_skips_schema_checks_without_jsonschema(tmp_path, monkeypatch):
    from claude_kit import schemas

    _minimal_payload(tmp_path, profile_agents=[])
    monkeypatch.setattr(schemas, "available", lambda: False)
    ok, messages = validator.check_catalog(tmp_path)
    assert ok, "\n".join(messages)
    assert any(
        m.startswith("WARN") and "jsonschema not installed" in m for m in messages
    )


def test_check_catalog_can_require_schema_support(tmp_path, monkeypatch):
    from claude_kit import schemas

    _minimal_payload(tmp_path, profile_agents=[])
    monkeypatch.setattr(schemas, "available", lambda: False)
    ok, messages = validator.check_catalog(tmp_path, require_schema=True)
    assert not ok
    assert any(
        m.startswith("FAIL") and "strict validation cannot continue" in m
        for m in messages
    )


def test_check_catalog_semantically_validates_every_mcp_record(payload, monkeypatch):
    from claude_kit.components import MCPServerSpec

    original = MCPServerSpec.from_catalog
    observed: set[str] = set()

    def recording_loader(_cls, server_id, record):
        observed.add(server_id)
        return original(server_id, record)

    monkeypatch.setattr(MCPServerSpec, "from_catalog", classmethod(recording_loader))

    ok, messages = validator.check_catalog(payload, require_schema=True)

    assert ok, "\n".join(messages)
    mcp_document = yaml.safe_load(
        (payload / "catalog/mcp.yaml").read_text(encoding="utf-8")
    )
    assert observed == set(mcp_document["servers"])
    assert any("MCP definitions pass semantic validation" in m for m in messages)


# --- doctor: environment reporting ----------------------------------------------------------


def test_doctor_warns_when_claude_code_is_missing(tmp_path, payload, monkeypatch):
    install(payload, tmp_path)
    original = validator.shutil.which
    monkeypatch.setattr(
        validator.shutil,
        "which",
        lambda tool: None if tool == "claude" else original(tool),
    )
    ok, messages = validator.doctor(tmp_path)
    assert ok, "\n".join(messages)
    assert any("Claude Code not on PATH" in m for m in messages)


def test_doctor_reports_tested_claude_code_version(tmp_path, payload, monkeypatch):
    install(payload, tmp_path)
    monkeypatch.setattr(validator.shutil, "which", lambda tool: f"/usr/bin/{tool}")
    monkeypatch.setattr(validator, "_claude_version", lambda _path: "2.1.163")
    ok, messages = validator.doctor(tmp_path)
    assert ok, "\n".join(messages)
    assert any("Claude Code 2.1.163 is supported and tested" in m for m in messages)


def test_doctor_warns_on_untested_supported_claude_code(tmp_path, payload, monkeypatch):
    install(payload, tmp_path)
    monkeypatch.setattr(validator.shutil, "which", lambda tool: f"/usr/bin/{tool}")
    monkeypatch.setattr(validator, "_claude_version", lambda _path: "2.1.170")
    ok, messages = validator.doctor(tmp_path)
    assert ok, "\n".join(messages)
    assert any("supported but is not in the tested matrix" in m for m in messages)
    assert any("optional feature unavailable" in m for m in messages)


def test_doctor_warns_on_unsupported_claude_code(tmp_path, payload, monkeypatch):
    install(payload, tmp_path)
    monkeypatch.setattr(validator.shutil, "which", lambda tool: f"/usr/bin/{tool}")
    monkeypatch.setattr(validator, "_claude_version", lambda _path: "2.1.100")
    ok, messages = validator.doctor(tmp_path)
    assert ok, "\n".join(messages)
    assert any("unsupported; minimum is 2.1.163" in m for m in messages)


def test_doctor_reports_windows_with_jq_but_still_refuses_native_mutation(
    tmp_path, payload, monkeypatch
):
    install(payload, tmp_path)
    monkeypatch.setattr(validator.platform, "system", lambda: "Windows")
    monkeypatch.setattr(validator.shutil, "which", lambda tool: f"/usr/bin/{tool}")
    ok, messages = validator.doctor(tmp_path)
    assert any("native Windows project mutation is unsupported" in m for m in messages)
    assert any("jq is on PATH" in m and "POSIX shell" in m for m in messages)


def test_doctor_warns_on_non_executable_hook_scripts(tmp_path, payload):
    install(payload, tmp_path)
    script = next((tmp_path / ".claude" / "hooks").glob("*.sh"))
    script.chmod(0o644)
    ok, messages = validator.doctor(tmp_path)
    assert any(
        m.startswith("WARN") and "hook scripts not executable" in m and script.name in m
        for m in messages
    )


def test_doctor_is_quiet_about_hooks_when_none_are_installed(tmp_path, payload):
    install(payload, tmp_path)
    hooks = tmp_path / ".claude" / "hooks"
    for script in hooks.glob("*.sh"):
        script.unlink()
    ok, messages = validator.doctor(tmp_path)
    assert not any("hook scripts" in m for m in messages)


def test_doctor_reports_a_missing_hooks_directory(tmp_path, payload):
    install(payload, tmp_path)
    _uninstall(tmp_path, ".claude/hooks")
    ok, messages = validator.doctor(tmp_path)
    assert not any("hook scripts are executable" in m for m in messages)


def test_doctor_warns_when_runtime_dirs_are_not_gitignored(tmp_path, payload):
    install(payload, tmp_path)
    gitignore = tmp_path / ".gitignore"
    if gitignore.is_file():
        gitignore.unlink()
    ok, messages = validator.doctor(tmp_path)
    assert any("not gitignored" in m and ".claude/state/" in m for m in messages)


def test_doctor_warns_when_learning_capture_is_enabled(tmp_path, payload):
    """Capture spawns a background job that reads the transcript \u2014 that must be stated out loud."""
    install(payload, tmp_path, capture_mode="session-end-catchup")
    ok, messages = validator.doctor(tmp_path)
    assert any("learning capture is enabled" in m for m in messages)


def test_doctor_recognizes_a_rollback_capable_install_journal(tmp_path, payload):
    install(payload, tmp_path)
    fs = ProjectFS(tmp_path)
    with pytest.raises(KeyboardInterrupt):
        with ProjectTransaction(fs, operation="force", to_version="0.83.0"):
            # Backup mode moves the nested journal away with .claude. Doctor
            # must inspect the authoritative top-level transaction marker.
            fs.move(".claude", ".claude.bak-1")
            raise KeyboardInterrupt

    assert not (tmp_path / ".claude" / "config" / "upgrade-in-progress.json").exists()
    ok, messages = validator.doctor(tmp_path)
    assert not ok  # the interrupted backup temporarily has no live .claude tree
    assert any(
        "interrupted force detected" in m
        and "re-run `claude-kit init --force`" in m
        and "rollback-capable" in m
        for m in messages
    )


# --- doctor --mcp health -----------------------------------------------------------------------


def test_mcp_health_reports_no_servers_configured(tmp_path, payload):
    install(payload, tmp_path, mcp=[])
    ok, messages = validator.doctor(tmp_path, mcp=True)
    assert ok, "\n".join(messages)
    assert any("no .mcp.json (no MCP servers configured)" in m for m in messages)


def test_mcp_health_reports_a_found_command_and_a_set_env_var(
    tmp_path, payload, monkeypatch
):
    install(payload, tmp_path, mcp=["github"])
    monkeypatch.setenv("GITHUB_PERSONAL_ACCESS_TOKEN", "set-for-this-test")
    monkeypatch.setattr(validator.shutil, "which", lambda tool: f"/usr/bin/{tool}")
    ok, messages = validator.doctor(tmp_path, mcp=True)
    assert ok, "\n".join(messages)
    assert not any("GITHUB_PERSONAL_ACCESS_TOKEN" in m for m in messages)


def test_mcp_health_warns_when_the_lockfile_drifts(tmp_path, payload):
    install(payload, tmp_path, mcp=["github"])
    lock = tmp_path / ".mcp.lock.json"
    lock.write_text(
        json.dumps({"schema": 1, "servers": {"unrelated": {}}}), encoding="utf-8"
    )
    ok, messages = validator.doctor(tmp_path, mcp=True)
    assert any(".mcp.lock.json is out of sync" in m for m in messages)


def test_mcp_health_skips_the_lockfile_check_when_absent(tmp_path, payload):
    install(payload, tmp_path, mcp=["github"])
    _uninstall(tmp_path, ".mcp.lock.json")
    ok, messages = validator.doctor(tmp_path, mcp=True)
    assert not any(".mcp.lock.json" in m for m in messages)
