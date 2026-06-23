"""merge_install: a default re-init reconciles non-destructively — user files always survive.

This is the regression guard for the data-loss bug where ``init`` in (default) ``merge`` mode used to
``shutil.rmtree`` whole kit-managed directories (``rules/``, ``skills/<name>/``, ``skills/_references/``),
silently deleting any file the user had added under them. ``merge_install`` reuses the upgrader's
owner-aware reconcile, so it refreshes kit/overlay files, backs up user-modified ones, prunes only
kit-owned orphans, and never touches files the kit doesn't track.
"""

from __future__ import annotations

from claude_kit import catalog, upgrader
from tests._helpers import install, make_selection


def test_merge_install_preserves_user_authored_files(tmp_path, payload):
    """Hand-written files under wholesale-replaced dirs survive a default merge."""
    target = tmp_path / "proj"
    install(payload, target)

    policy = target / ".claude" / "rules" / "company-policy.md"
    policy.write_text("internal policy\n", encoding="utf-8")
    skill = target / ".claude" / "skills" / "company-skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text("# company skill\n", encoding="utf-8")
    ref_extra = target / ".claude" / "skills" / "_references" / "company-ref.md"
    ref_extra.parent.mkdir(parents=True, exist_ok=True)
    ref_extra.write_text("ref\n", encoding="utf-8")
    hook = target / ".claude" / "hooks" / "custom.sh"
    hook.write_text("#!/usr/bin/env bash\n", encoding="utf-8")

    plan = catalog.resolve(payload, make_selection(payload))
    ok, _ = upgrader.merge_install(payload, target, plan)
    assert ok

    assert policy.read_text(encoding="utf-8") == "internal policy\n"
    assert (skill / "SKILL.md").read_text(encoding="utf-8") == "# company skill\n"
    assert ref_extra.read_text(encoding="utf-8") == "ref\n"
    assert hook.is_file()
    # ...and the kit content is genuinely there (the merge did install, not skip):
    assert (target / ".claude" / "skills" / "sdlc" / "SKILL.md").is_file()


def test_merge_install_is_idempotent_on_pristine(tmp_path, payload):
    """Re-merging the same selection over a pristine install changes nothing."""
    target = tmp_path / "proj"
    install(payload, target)
    before = {
        p.relative_to(target): p.read_bytes()
        for p in (target / ".claude").rglob("*")
        if p.is_file()
    }

    plan = catalog.resolve(payload, make_selection(payload))
    ok, messages = upgrader.merge_install(payload, target, plan)
    assert ok
    assert any("up to date" in m for m in messages)

    after = {
        p.relative_to(target): p.read_bytes()
        for p in (target / ".claude").rglob("*")
        if p.is_file()
    }
    assert before == after


def test_merge_install_backs_up_user_modified_kit_file(tmp_path, payload):
    """A user-edited *kit* file is refreshed to canonical content, but backed up first."""
    target = tmp_path / "proj"
    install(payload, target)
    rule = target / ".claude" / "rules" / "quality-gates.md"
    rule.write_text("MINE ONLY\n", encoding="utf-8")

    plan = catalog.resolve(payload, make_selection(payload))
    ok, _ = upgrader.merge_install(payload, target, plan)
    assert ok

    assert "MINE ONLY" not in rule.read_text(encoding="utf-8")  # healed
    baks = list(target.glob(".claude-kit.bak-*/.claude/rules/quality-gates.md"))
    assert baks and baks[0].read_text(encoding="utf-8") == "MINE ONLY\n"


def test_merge_install_prunes_kit_orphans_on_downgrade(tmp_path, payload):
    """Switching to a narrower profile removes kit files the new selection no longer ships."""
    target = tmp_path / "proj"
    install(payload, target, profile="enterprise")
    orphan = target / ".claude" / "agents" / "incident-responder.md"
    assert orphan.is_file()  # enterprise-only agent

    lean = catalog.resolve(payload, make_selection(payload, profile="lean"))
    ok, _ = upgrader.merge_install(payload, target, lean)
    assert ok

    assert not orphan.exists()  # kit orphan pruned
    assert (target / ".claude" / "skills" / "sdlc" / "SKILL.md").is_file()  # core kept


def test_merge_install_into_untracked_claude_backs_up_collisions(tmp_path, payload):
    """A hand-rolled .claude/ with no init-options.json: collisions are backed up, user files kept."""
    target = tmp_path / "proj"
    rules = target / ".claude" / "rules"
    rules.mkdir(parents=True)
    collision = rules / "quality-gates.md"  # collides with a real kit path
    collision.write_text("HANDROLLED\n", encoding="utf-8")
    mine = rules / "company-policy.md"  # purely the user's
    mine.write_text("ours\n", encoding="utf-8")

    plan = catalog.resolve(payload, make_selection(payload))
    ok, _ = upgrader.merge_install(payload, target, plan)
    assert ok

    # Collision: kit content now in place, the hand-rolled version backed up.
    assert "HANDROLLED" not in collision.read_text(encoding="utf-8")
    baks = list(target.glob(".claude-kit.bak-*/.claude/rules/quality-gates.md"))
    assert baks and baks[0].read_text(encoding="utf-8") == "HANDROLLED\n"
    # Purely-user file untouched, and the tree is now claude-kit-tracked.
    assert mine.read_text(encoding="utf-8") == "ours\n"
    assert (target / ".claude" / "config" / "init-options.json").is_file()
