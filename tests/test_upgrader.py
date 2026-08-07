"""diff / upgrade: pristine is a no-op, and user edits survive repeated upgrades."""

from __future__ import annotations

import json

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


def test_upgrade_warns_when_recorded_capture_is_on(tmp_path, payload):
    """An install that consented to capture keeps it across upgrades — but the upgrade says so
    (pre-0.76 --defaults installs recorded capture nobody explicitly chose)."""
    install(payload, tmp_path, capture_mode="session-end")
    _age_install(tmp_path, ".claude/rules/testing.md", "OLD KIT CONTENT\n")
    ok, messages = upgrader.upgrade(tmp_path)
    assert ok
    assert any("background learning capture is ON" in m for m in messages)
    assert any("privacy-report" in m for m in messages)


def test_upgrade_stays_silent_when_capture_off(tmp_path, payload):
    """No capture recorded -> no notice, and the upgrade must not resurrect capture hooks."""
    import json

    install(payload, tmp_path)  # 0.76.0 default: off
    _age_install(tmp_path, ".claude/rules/testing.md", "OLD KIT CONTENT\n")
    ok, messages = upgrader.upgrade(tmp_path)
    assert ok
    assert not any("background learning capture is ON" in m for m in messages)
    settings = json.loads(
        (tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8")
    )
    blob = json.dumps(settings)
    assert "capture-learnings" not in blob


# --- the decisions the upgrader makes when the target is not in the shape it recorded -----------
#
# These are the paths that rewrite or delete a user's files, so an untaken branch here is not a
# coverage statistic — it is an unexercised way to lose work.


def test_corrupt_init_options_is_distinguished_from_a_missing_one(tmp_path, payload):
    """Both refuse the upgrade, but the operator needs different remedies for each."""
    install(payload, tmp_path)
    cfg = tmp_path / ".claude" / "config" / "init-options.json"
    cfg.write_text("{not json", encoding="utf-8")
    ok, messages = upgrader.upgrade(tmp_path)
    assert not ok
    assert any("unreadable (invalid JSON)" in m for m in messages), messages

    cfg.unlink()
    ok, messages = upgrader.upgrade(tmp_path)
    assert not ok
    assert any("predates upgrade tracking" in m for m in messages), messages
    assert not any("invalid JSON" in m for m in messages)


def test_orphan_the_user_already_deleted_is_not_planned_for_removal(tmp_path, payload):
    """A recorded file that is gone from disk must produce no `remove` action.

    Reaching this needs a record the current plan no longer ships AND no file on disk — so the
    manifest is given a stale record directly. Deleting a still-planned file instead leaves it in
    the reference, the loop `continue`s one line earlier, and the assertion passes without ever
    touching the branch it claims to cover.
    """
    install(payload, tmp_path)
    cfg = tmp_path / ".claude" / "config" / "init-options.json"
    doc = json.loads(cfg.read_text(encoding="utf-8"))
    stale = ".claude/rules/retired-in-an-older-kit.md"
    template = next(r for r in doc["files"] if r["path"].startswith(".claude/rules/"))
    doc["files"].append({**template, "path": stale})
    cfg.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    assert not (tmp_path / stale).exists()

    cmp_ = upgrader._compare(payload, tmp_path)
    assert not isinstance(cmp_, str), f"_compare refused the fixture: {cmp_}"
    try:
        removals = [a.rel for a in cmp_.actions if a.kind == "remove"]
        assert stale not in removals, "planned to remove a file that is already absent"
        # The same record WITH a file on disk must be planned for removal, or the assertion above
        # would hold for the wrong reason.
        (tmp_path / stale).write_text("left over\n", encoding="utf-8")
        cmp2 = upgrader._compare(payload, tmp_path)
        assert not isinstance(cmp2, str)
        try:
            assert stale in [a.rel for a in cmp2.actions if a.kind == "remove"]
        finally:
            upgrader._cleanup(cmp2.ref_root)
    finally:
        upgrader._cleanup(cmp_.ref_root)


def test_upgrade_of_an_install_with_no_pending_actions_reports_up_to_date(
    tmp_path, payload
):
    """The action loop must tolerate an empty plan rather than assuming at least one entry."""
    install(payload, tmp_path)
    ok, first = upgrader.upgrade(tmp_path)
    assert ok, first
    ok, second = upgrader.upgrade(tmp_path)
    assert ok
    assert any("up to date" in m for m in second), second


def test_explain_error_covers_every_compare_failure_code(tmp_path):
    """Each code must produce its own actionable remedy, and none may fall through silently."""
    seen = {}
    for code in ("not-installed", "corrupt-options", "no-options"):
        ok, msgs = upgrader._explain_error(code, tmp_path)
        assert not ok
        assert len(msgs) == 1 and msgs[0].startswith("FAIL")
        seen[code] = msgs[0]
    assert len({*seen.values()}) == 3, f"two codes share a message: {seen}"
    assert "claude-kit init" in seen["not-installed"]
    assert "invalid JSON" in seen["corrupt-options"]
    assert "predates upgrade tracking" in seen["no-options"]


def test_two_orphans_are_both_removed(tmp_path, payload):
    """The remove branch must hand control back to the loop, not fall out after the first file.

    A single orphan cannot show this: the loop ends either way. Two are needed for the back-edge
    to be exercised at all.
    """
    install(payload, tmp_path)
    cfg = tmp_path / ".claude" / "config" / "init-options.json"
    doc = json.loads(cfg.read_text(encoding="utf-8"))
    template = next(r for r in doc["files"] if r["path"].startswith(".claude/rules/"))
    stale = [".claude/rules/retired-a.md", ".claude/rules/retired-b.md"]
    for rel in stale:
        doc["files"].append({**template, "path": rel})
        (tmp_path / rel).write_text("left over\n", encoding="utf-8")
    cfg.write_text(json.dumps(doc, indent=2), encoding="utf-8")

    ok, messages = upgrader.upgrade(tmp_path)
    assert ok, messages
    for rel in stale:
        assert not (tmp_path / rel).exists(), f"{rel} survived the upgrade"
        assert any(rel in m and "orphan removed" in m for m in messages), messages


def test_apply_tolerates_a_reference_missing_a_config_file(tmp_path, payload):
    """`_apply` copies the reference's config verbatim; a reference lacking one must not crash.

    Driven through `_apply` directly because `_compare` always renders a complete reference — the
    guard exists for a truncated or partially-written tree, which the public path cannot produce.
    """
    install(payload, tmp_path)
    cmp_ = upgrader._compare(payload, tmp_path)
    assert not isinstance(cmp_, str), cmp_
    try:
        (cmp_.ref_root / ".claude" / "config" / "stack-catalog.snapshot.yaml").unlink()
        victim = ".claude/rules/quality-gates.md"
        (tmp_path / victim).write_text("edited away\n", encoding="utf-8")
        cmp_.actions.append(
            upgrader._Action(victim, "update", "kit", user_modified=True)
        )

        ok, messages = upgrader._apply(cmp_, force=False)
        assert ok, messages
        # The surviving config file is still adopted, and the absent one is simply not copied.
        assert (tmp_path / ".claude" / "config" / "init-options.json").is_file()
        assert (tmp_path / victim).read_text(encoding="utf-8") != "edited away\n"
    finally:
        upgrader._cleanup(cmp_.ref_root)


def test_update_actions_never_carry_a_user_modified_user_editable_file(
    tmp_path, payload
):
    """The invariant that lets `_apply`'s update branch skip the sidecar decision entirely.

    `_diff_actions` classifies a user-modified user-editable file as "keep", so the sidecar path
    lives there alone. `_apply` previously duplicated it under "update", where it was unreachable.
    If the classifier ever starts emitting "update" for that case, this fails — and the sidecar
    handling has to be reinstated rather than silently lost.
    """
    install(payload, tmp_path)
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text(
        claude_md.read_text(encoding="utf-8") + "\nmine\n", encoding="utf-8"
    )
    _age_install(tmp_path, ".claude/rules/quality-gates.md", "aged\n")

    cmp_ = upgrader._compare(payload, tmp_path)
    assert not isinstance(cmp_, str), cmp_
    try:
        offenders = [
            a
            for a in cmp_.actions
            if a.kind == "update" and a.owner == "user-editable" and a.user_modified
        ]
        assert not offenders, (
            f"classifier emitted update for a protected file: {offenders}"
        )
        # And the case genuinely occurs in this fixture — otherwise the assertion is vacuous.
        assert any(
            a.kind == "keep" and a.owner == "user-editable" and a.user_modified
            for a in cmp_.actions
        ), "fixture produced no user-modified user-editable file to classify"
    finally:
        upgrader._cleanup(cmp_.ref_root)
