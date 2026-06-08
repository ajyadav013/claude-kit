"""diff / upgrade: pristine is a no-op, and user edits survive repeated upgrades."""

from __future__ import annotations

from claude_kit import upgrader
from tests._helpers import install


def test_diff_on_pristine_install_is_a_noop(tmp_path, payload):
    install(payload, tmp_path)
    ok, messages = upgrader.diff(tmp_path)
    assert ok
    assert any("up to date" in m for m in messages)


def test_diff_writes_nothing(tmp_path, payload):
    install(payload, tmp_path)
    before = {
        p: p.read_bytes() for p in (tmp_path / ".claude").rglob("*") if p.is_file()
    }
    upgrader.diff(tmp_path)
    after = {
        p: p.read_bytes() for p in (tmp_path / ".claude").rglob("*") if p.is_file()
    }
    assert before == after


def test_diff_classifies_mutations(tmp_path, payload):
    install(payload, tmp_path)
    # kit file modified, user-editable file modified, kit file deleted.
    (tmp_path / ".claude" / "rules" / "quality-gates.md").write_text(
        "tweaked\n", encoding="utf-8"
    )
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text(
        claude_md.read_text(encoding="utf-8") + "\nmine\n", encoding="utf-8"
    )
    (tmp_path / ".claude" / "agents" / "developer.md").unlink()

    ok, messages = upgrader.diff(tmp_path)
    blob = "\n".join(messages)
    assert "update" in blob and ".claude/rules/quality-gates.md" in blob
    assert "keep" in blob and "CLAUDE.md" in blob
    assert "add" in blob and ".claude/agents/developer.md" in blob


def test_upgrade_heals_and_protects_user_edits(tmp_path, payload):
    install(payload, tmp_path)
    claude_md = tmp_path / "CLAUDE.md"
    marker = "<!-- KEEP ME -->"
    claude_md.write_text(
        claude_md.read_text(encoding="utf-8") + f"\n{marker}\n", encoding="utf-8"
    )
    rule = tmp_path / ".claude" / "rules" / "quality-gates.md"
    sentinel = "ZZ_CORRUPTED_BY_TEST_ZZ\n"
    rule.write_text(sentinel, encoding="utf-8")
    (tmp_path / ".claude" / "agents" / "developer.md").unlink()

    ok, _ = upgrader.upgrade(tmp_path)
    assert ok
    # Kit files healed:
    assert (tmp_path / ".claude" / "agents" / "developer.md").is_file()
    assert sentinel not in rule.read_text(encoding="utf-8")
    assert len(rule.read_text(encoding="utf-8")) > 100  # restored to real content
    # User edit preserved + a sidecar of the canonical version written:
    assert marker in claude_md.read_text(encoding="utf-8")
    assert (tmp_path / "CLAUDE.md.claude-kit").is_file()


def test_user_edit_survives_repeated_upgrades(tmp_path, payload):
    """Regression: the post-upgrade baseline must stay the kit's canonical sha, not the user's."""
    install(payload, tmp_path)
    claude_md = tmp_path / "CLAUDE.md"
    marker = "<!-- PERSIST -->"
    claude_md.write_text(
        claude_md.read_text(encoding="utf-8") + f"\n{marker}\n", encoding="utf-8"
    )

    upgrader.upgrade(tmp_path)
    upgrader.upgrade(tmp_path)  # second round must still protect, not clobber

    assert marker in claude_md.read_text(encoding="utf-8")
    ok, messages = upgrader.diff(tmp_path)
    assert any("keep" in m and "CLAUDE.md" in m for m in messages)


def test_upgrade_fails_when_not_installed(tmp_path):
    ok, messages = upgrader.upgrade(tmp_path)
    assert not ok
