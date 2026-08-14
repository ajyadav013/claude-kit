"""Overwrite mode replaces kit-owned trees without destroying what the user put in them.

``_copy_tree`` replaces whole directories (``.claude/rules/``, ``.claude/templates/``,
``.claude/skills/<name>/``). Files the user added to those trees are not recorded in
``init-options.json`` — the kit never wrote them — so the upgrader's checksum/sidecar machinery
does not cover them. These tests pin the only thing that does: they are moved into
``.claude-kit.bak-N/`` rather than deleted, and kit content is *not* mistaken for user content.
"""

from __future__ import annotations

import pytest

from claude_kit import catalog, scaffold, upgrader
from tests._helpers import install, make_selection


def _reinstall(payload, target, log, **overrides):
    """Re-run the installer over an existing target in overwrite mode."""
    plan = catalog.resolve(payload, make_selection(payload, **overrides))
    scaffold.install_sdlc(payload, target, plan, force=True, log=log)


def _rescued(target, name):
    """Return rescued copies of ``name`` found under any .claude-kit.bak-N/."""
    return list(target.glob(f".claude-kit.bak-*/**/{name}"))


def test_fresh_install_creates_no_backup_directory(tmp_path, payload):
    install(payload, tmp_path)
    assert not list(tmp_path.glob(".claude-kit.bak-*")), (
        "the rescue directory must be created lazily, only when something is rescued"
    )


@pytest.mark.parametrize(
    ("relpath", "body"),
    [
        (".claude/rules/team-conventions.md", "our own rule\n"),
        (".claude/templates/my-template.md", "our own template\n"),
    ],
)
def test_force_reinstall_rescues_user_files_from_kit_trees(
    tmp_path, payload, relpath, body
):
    install(payload, tmp_path)
    mine = tmp_path / relpath
    mine.write_text(body, encoding="utf-8")

    _reinstall(payload, tmp_path, [])

    rescued = _rescued(tmp_path, mine.name)
    assert mine.is_file() or rescued, f"{relpath} was destroyed with no backup"
    if rescued:
        assert rescued[0].read_text(encoding="utf-8") == body
        # The rescued path mirrors the project-relative one, so it is unambiguous.
        assert rescued[0].as_posix().endswith(relpath)


def test_force_reinstall_rescues_a_file_added_inside_a_skill(tmp_path, payload):
    install(payload, tmp_path)
    skills = tmp_path / ".claude" / "skills"
    first = sorted(
        d for d in skills.iterdir() if d.is_dir() and not d.name.startswith("_")
    )[0]
    note = first / "MY-NOTES.md"
    note.write_text("notes\n", encoding="utf-8")

    _reinstall(payload, tmp_path, [])

    rescued = _rescued(tmp_path, "MY-NOTES.md")
    assert note.is_file() or rescued, "a user file inside a skill dir was destroyed"


def test_force_reinstall_reports_what_it_rescued(tmp_path, payload):
    install(payload, tmp_path)
    (tmp_path / ".claude" / "rules" / "team-conventions.md").write_text(
        "mine\n", encoding="utf-8"
    )
    log: list[str] = []
    _reinstall(payload, tmp_path, log)
    assert any("kept your" in line and "team-conventions.md" in line for line in log), (
        f"a rescue must be visible in the install log, got: {log}"
    )


@pytest.mark.parametrize("scope", ["team", "organization"])
def test_overlay_and_org_rules_are_not_mistaken_for_user_files(
    tmp_path, payload, scope
):
    """Overlay/org rules land in .claude/rules/ *after* the core tree is replaced.

    Without ``also_shipped`` they look like user additions on every re-install: the backup dir
    fills with kit files and the log tells the user their own content was preserved when it was
    not theirs. This is the regression guard for that.
    """
    install(payload, tmp_path, scope=scope, profile="enterprise")
    log: list[str] = []
    _reinstall(payload, tmp_path, log, scope=scope, profile="enterprise")

    rescued_names = {p.name for p in tmp_path.glob(".claude-kit.bak-*/**/*.md")}
    assert not rescued_names, (
        f"kit-owned files were rescued as if the user wrote them: {sorted(rescued_names)}"
    )
    assert not [line for line in log if "kept your" in line]


@pytest.mark.parametrize("scope", ["team", "organization"])
def test_force_reinstall_leaves_a_clean_install_behind(tmp_path, payload, scope):
    """Rescuing must not cost correctness: the result still validates as pristine."""
    install(payload, tmp_path, scope=scope, profile="enterprise")
    (tmp_path / ".claude" / "rules" / "team-conventions.md").write_text(
        "mine\n", encoding="utf-8"
    )
    _reinstall(payload, tmp_path, [], scope=scope, profile="enterprise")

    ok, messages = upgrader.diff(tmp_path)
    assert ok, (
        f"force re-install left a dirty tree: {[m for m in messages if 'FAIL' in m]}"
    )


def test_repeated_force_reinstalls_use_separate_backup_dirs(tmp_path, payload):
    install(payload, tmp_path)
    for i in range(2):
        (tmp_path / ".claude" / "rules" / f"mine-{i}.md").write_text(
            f"{i}\n", encoding="utf-8"
        )
        _reinstall(payload, tmp_path, [])
    baks = sorted(p.name for p in tmp_path.glob(".claude-kit.bak-*"))
    assert baks == [".claude-kit.bak-1", ".claude-kit.bak-2"], baks
