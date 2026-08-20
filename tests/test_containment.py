"""The manifest is untrusted input: no recorded path may reach outside the project root.

``.claude/config/init-options.json`` lives inside the project being upgraded, and the upgrader
joins its ``files[].path`` entries onto the project root before copying, overwriting, and
*unlinking* the result. A hand-edited — or hostile — manifest must not be able to steer any of
those operations at a file the user did not install. These tests pin both halves of the guard:
the textual one (:func:`claude_kit.models.contained_relpath`, at parse time) and the symlink one
(:func:`claude_kit.upgrader._inside`, at the moment of use).
"""

from __future__ import annotations

import json

import pytest

from claude_kit import upgrader
from claude_kit.models import FileRecord, InitOptions, contained_relpath
from tests._helpers import install

# --- the textual guard, at parse time ---------------------------------------------------------


@pytest.mark.parametrize(
    "hostile",
    [
        "../escape.txt",
        "../../etc/passwd",
        ".claude/rules/../../../escape.txt",
        "/etc/passwd",
        "/absolute.txt",
        "..\\escape.txt",  # Windows separators: pathlib would re-read these as separators
        "..\\..\\Windows\\System32\\drivers\\etc\\hosts",
        "C:\\Windows\\hosts",
        "",
        "   ",
    ],
)
def test_file_record_rejects_paths_that_escape_the_project(hostile):
    with pytest.raises(ValueError):
        FileRecord(path=hostile, sha256="0" * 64, owner="kit")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (".claude/rules/testing.md", ".claude/rules/testing.md"),
        ("CLAUDE.md", "CLAUDE.md"),
        (".claude\\rules\\testing.md", ".claude/rules/testing.md"),
        ("./CLAUDE.md", "CLAUDE.md"),
        (".claude/skills/a/../b/SKILL.md", ".claude/skills/a/../b/SKILL.md"),
    ],
)
def test_legitimate_relative_paths_survive_normalisation(raw, expected):
    # The last case documents that a *interior* ".." is still rejected, not silently collapsed —
    # collapsing would let ".claude/x/../../../y" normalise into something that looks contained.
    if ".." in raw:
        with pytest.raises(ValueError):
            contained_relpath(raw)
    else:
        assert contained_relpath(raw) == expected


def test_hostile_manifest_is_reported_as_corrupt_not_obeyed(tmp_path, payload):
    """A poisoned manifest must fail loudly through the existing corrupt-manifest path."""
    install(payload, tmp_path)
    victim = tmp_path.parent / "VICTIM.txt"
    victim.write_text("do not delete me\n", encoding="utf-8")

    opts_path = tmp_path / ".claude" / "config" / "init-options.json"
    doc = json.loads(opts_path.read_text(encoding="utf-8"))
    doc["files"].append(
        {"path": f"../{victim.name}", "sha256": "0" * 64, "owner": "kit"}
    )
    opts_path.write_text(json.dumps(doc), encoding="utf-8")

    with pytest.raises(ValueError):
        InitOptions.from_dict(doc)

    ok, messages = upgrader.upgrade(tmp_path)
    assert victim.is_file(), "upgrade deleted a file outside the project root"
    assert victim.read_text(encoding="utf-8") == "do not delete me\n"
    blob = "\n".join(messages)
    assert not ok, f"a poisoned manifest should not report success: {blob}"


def test_diff_does_not_delete_through_a_poisoned_manifest(tmp_path, payload):
    install(payload, tmp_path)
    victim = tmp_path.parent / "VICTIM-diff.txt"
    victim.write_text("keep\n", encoding="utf-8")

    opts_path = tmp_path / ".claude" / "config" / "init-options.json"
    doc = json.loads(opts_path.read_text(encoding="utf-8"))
    doc["files"].append(
        {"path": f"../{victim.name}", "sha256": "0" * 64, "owner": "kit"}
    )
    opts_path.write_text(json.dumps(doc), encoding="utf-8")

    upgrader.diff(tmp_path)
    assert victim.is_file()


# --- the symlink guard, at the moment of use --------------------------------------------------


def test_inside_rejects_a_symlink_that_leaves_the_project(tmp_path):
    project = tmp_path / "project"
    (project / ".claude").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret\n", encoding="utf-8")

    link = project / ".claude" / "rules"
    link.symlink_to(outside, target_is_directory=True)

    assert not upgrader._inside(project, ".claude/rules/secret.txt")
    assert upgrader._inside(project, ".claude/config/init-options.json")


def test_orphan_removal_fails_closed_when_a_parent_is_symlinked(tmp_path, payload):
    """A symlinked kit directory aborts planning without deleting outside the root."""
    install(payload, tmp_path)
    outside = tmp_path.parent / "outside-tree"
    outside.mkdir(exist_ok=True)
    bystander = outside / "bystander.md"
    bystander.write_text("not yours\n", encoding="utf-8")

    ref = {}
    old_map = {
        ".claude/rules/gone.md": FileRecord(
            path=".claude/rules/gone.md", sha256="0" * 64, owner="kit"
        )
    }
    rules = tmp_path / ".claude" / "rules"
    for child in rules.iterdir():
        child.unlink()
    rules.rmdir()
    rules.symlink_to(outside, target_is_directory=True)
    (outside / "gone.md").write_text("x\n", encoding="utf-8")

    with pytest.raises(upgrader.UnsafePathError, match="symlink|reparse|junction"):
        upgrader._diff_actions(ref, old_map, tmp_path, backup_untracked=False)
    assert bystander.is_file()
