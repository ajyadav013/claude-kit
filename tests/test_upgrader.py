"""diff / upgrade: pristine is a no-op, and user edits survive repeated upgrades."""

from __future__ import annotations

from claude_kit import catalog, upgrader
from tests._helpers import install, make_selection


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


def _age_install(target, rel: str, old_content: str) -> None:
    """Rewrite one tracked file + its recorded checksum to simulate an install from an
    older kit: the live file holds the old kit's content and init-options.json records
    exactly that sha (a CONSISTENT old install — the user never touched the file)."""
    import hashlib
    import json

    live = target / rel
    live.write_text(old_content, encoding="utf-8")
    opts_path = target / ".claude" / "config" / "init-options.json"
    doc = json.loads(opts_path.read_text(encoding="utf-8"))
    doc["claude_kit_version"] = "0.0.1"
    hit = [r for r in doc["files"] if r["path"] == rel]
    assert hit, f"no record for {rel}"
    hit[0]["sha256"] = hashlib.sha256(old_content.encode()).hexdigest()
    opts_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")


def test_cross_version_upgrade_refreshes_cleanly_without_backups(tmp_path, payload):
    """An outdated-but-unmodified kit file (old content, matching old record) is refreshed
    silently: no user_modified flag, no backup dir, version transition reported."""
    install(payload, tmp_path)
    rel = ".claude/rules/testing.md"
    _age_install(tmp_path, rel, "OLD KIT CONTENT\n")

    ok, messages = upgrader.diff(tmp_path)
    assert ok
    assert any("0.0.1 ->" in m for m in messages)  # version transition surfaced
    blob = "\n".join(messages)
    assert "update" in blob and rel in blob
    assert "[local changes will be backed up]" not in blob  # not user-modified

    ok, _ = upgrader.upgrade(tmp_path)
    assert ok
    healed = (tmp_path / rel).read_text(encoding="utf-8")
    assert healed != "OLD KIT CONTENT\n" and len(healed) > 100
    assert not list(tmp_path.glob(".claude-kit.bak-*"))  # nothing needed backing up
    ok, messages = upgrader.upgrade(tmp_path)
    assert ok and any("nothing to upgrade" in m for m in messages)


def test_upgrade_force_overwrites_user_editable_with_backup(tmp_path, payload):
    """--force honors its documented contract: overwrite the user-edited user-editable file
    (backing the edit up) instead of writing a sidecar. Regression for the dead-code force
    path found in round-2 R7: the `keep` branch used to ignore force entirely."""
    install(payload, tmp_path)
    claude_md = tmp_path / "CLAUDE.md"
    pristine = claude_md.read_text(encoding="utf-8")
    marker = "<!-- FORCE ME AWAY -->"
    claude_md.write_text(pristine + f"\n{marker}\n", encoding="utf-8")

    ok, messages = upgrader.upgrade(tmp_path, force=True)
    assert ok, messages
    assert marker not in claude_md.read_text(encoding="utf-8")  # overwritten
    assert claude_md.read_text(encoding="utf-8") == pristine  # back to canonical
    assert not (tmp_path / "CLAUDE.md.claude-kit").exists()  # no sidecar in force mode
    assert any("forced; your edits backed up" in m for m in messages)
    # The edit is recoverable from the backup dir.
    backups = list(tmp_path.glob(".claude-kit.bak-*/CLAUDE.md"))
    assert backups and marker in backups[0].read_text(encoding="utf-8")


def test_upgrade_without_force_still_sidecars(tmp_path, payload):
    """Control for the force test: the default path keeps the edit + writes the sidecar."""
    install(payload, tmp_path)
    claude_md = tmp_path / "CLAUDE.md"
    marker = "<!-- KEEP ME -->"
    claude_md.write_text(
        claude_md.read_text(encoding="utf-8") + f"\n{marker}\n", encoding="utf-8"
    )
    ok, _ = upgrader.upgrade(tmp_path, force=False)
    assert ok
    assert marker in claude_md.read_text(encoding="utf-8")
    assert (tmp_path / "CLAUDE.md.claude-kit").is_file()


def test_same_version_rerun_does_not_rewrite_identical_sidecar(tmp_path, payload):
    """R6 churn guard: once the sidecar holds the kit's current copy, a re-run must not
    rewrite it, must not claim a "new version" exists, and must skip the sidecar hint."""
    install(payload, tmp_path)
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text(
        claude_md.read_text(encoding="utf-8") + "\n<!-- MINE -->\n", encoding="utf-8"
    )

    ok, first = upgrader.upgrade(tmp_path)
    assert ok
    assert any("kept; kit's version ->" in m for m in first)
    assert any("delete the sidecar" in m for m in first)  # one-time hint
    assert not any("new version" in m for m in first)  # the false claim is gone
    sidecar = tmp_path / "CLAUDE.md.claude-kit"
    mtime_after_first = sidecar.stat().st_mtime_ns

    ok, second = upgrader.upgrade(tmp_path)
    assert ok
    assert any("sidecar already current" in m for m in second)
    assert not any("kit's version ->" in m for m in second)  # nothing rewritten
    assert not any("delete the sidecar" in m for m in second)  # hint only when writing
    assert sidecar.stat().st_mtime_ns == mtime_after_first  # literally untouched


def test_stale_or_tampered_sidecar_is_refreshed(tmp_path, payload):
    """The churn guard compares content, so a sidecar that no longer matches the kit's
    current copy (tampered, or left by an older kit) is healed, not skipped."""
    install(payload, tmp_path)
    pristine = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text(pristine + "\n<!-- MINE -->\n", encoding="utf-8")
    upgrader.upgrade(tmp_path)

    sidecar = tmp_path / "CLAUDE.md.claude-kit"
    sidecar.write_text("JUNK FROM AN OLDER KIT\n", encoding="utf-8")
    ok, msgs = upgrader.upgrade(tmp_path)
    assert ok
    assert any("kept; kit's version ->" in m for m in msgs)  # rewrite happened
    assert sidecar.read_text(encoding="utf-8") == pristine  # healed to canonical


def test_merge_install_reports_merge_not_upgrade(tmp_path, payload):
    """R6: init's merge path must not close with "upgrade complete"."""
    install(payload, tmp_path)
    plan = catalog.resolve(payload, make_selection(payload))

    # No-op merge: everything current.
    ok, msgs = upgrader.merge_install(payload, tmp_path, plan)
    assert ok
    assert any("nothing to merge" in m for m in msgs)
    assert not any("upgrade" in m.lower() for m in msgs)

    # Real merge work: a drifted kit file.
    (tmp_path / ".claude" / "rules" / "testing.md").write_text(
        "DRIFTED\n", encoding="utf-8"
    )
    ok, msgs = upgrader.merge_install(payload, tmp_path, plan)
    assert ok
    assert any("merge complete" in m for m in msgs)
    assert not any("upgrade complete" in m for m in msgs)
