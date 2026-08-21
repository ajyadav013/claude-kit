"""Adversarial coverage for project-bound filesystem mutations.

The project tree is untrusted input.  A destination that looks relative is not
safe when one of its parents (or the leaf itself) is a symlink/junction, and a
failed multi-file install must restore the tree it started from.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from claude_kit import catalog, scaffold, upgrader, validator
from claude_kit.secure_fs import (
    TRANSACTION_SCHEMA,
    ProjectFS,
    ProjectTransaction,
    UnsafePathError,
    inspect_interrupted_transaction,
    normalize_relative_path,
    recover_interrupted_transaction,
)
from tests._helpers import make_selection


@pytest.mark.parametrize(
    "hostile",
    [
        "../escape",
        "a/../../escape",
        "/absolute",
        r"C:\Windows\System32\drivers\etc\hosts",
        r"C:drive-relative",
        r"\\server\share\escape",
        r"\\?\C:\escape",
        r"\rooted-on-current-drive",
        "",
        ".",
    ],
)
def test_normalize_relative_path_rejects_cross_platform_escapes(hostile):
    with pytest.raises(UnsafePathError):
        normalize_relative_path(hostile)


def test_project_fs_atomic_write_succeeds_for_an_ordinary_path(tmp_path):
    fs = ProjectFS(tmp_path)
    fs.write_text(".claude/config/example.json", "{}\n")
    assert (tmp_path / ".claude" / "config" / "example.json").read_text() == "{}\n"


def test_project_fs_rejects_a_symlink_in_project_root_ancestry(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)

    with pytest.raises(UnsafePathError, match="link-free|symlink|reparse|junction"):
        ProjectFS(alias / "project")
    assert not (real / "project").exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX descriptor-anchored creation")
def test_project_root_creation_anchor_swap_cannot_escape(tmp_path, monkeypatch):
    anchor = tmp_path / "anchor"
    held = tmp_path / "anchor-held"
    outside = tmp_path / "outside"
    anchor.mkdir()
    outside.mkdir()
    fs = ProjectFS(anchor / "new" / "project")

    def swap_anchor(_anchor, _missing):
        anchor.rename(held)
        anchor.symlink_to(outside, target_is_directory=True)

    monkeypatch.setattr(fs, "_before_root_create", swap_anchor)
    with pytest.raises(UnsafePathError, match="link-free|symlink|reparse|junction"):
        fs.ensure_root()
    assert not (outside / "new").exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX descriptor-anchored root")
def test_root_replaced_by_symlink_after_validation_is_refused(tmp_path):
    project = tmp_path / "project"
    held = tmp_path / "project-held"
    project.mkdir()
    fs = ProjectFS(project)
    project.rename(held)
    project.symlink_to(held, target_is_directory=True)

    with pytest.raises(UnsafePathError, match="link-free|symlink|reparse|junction"):
        fs.write_text("CLAUDE.md", "hostile\n")
    assert not (held / "CLAUDE.md").exists()


def test_project_fs_exclusive_lock_primitive_is_root_bound(tmp_path):
    fs = ProjectFS(tmp_path / "project")
    lock = ".claude/state/pipeline-snapshot.json.lock"
    fs.create_exclusive(lock, b"123\n")
    assert fs.read_bytes(lock) == b"123\n"
    with pytest.raises(FileExistsError):
        fs.create_exclusive(lock, b"456\n")
    fs.unlink(lock)
    assert not fs.exists(lock)


def test_platform_without_descriptor_anchoring_is_read_only_and_fails_closed(
    tmp_path, monkeypatch
):
    existing = tmp_path / "existing.txt"
    existing.write_text("safe\n", encoding="utf-8")
    fs = ProjectFS(tmp_path)
    monkeypatch.setattr(fs, "_supports_descriptor_walk", lambda: False)
    monkeypatch.setattr(fs, "_supports_dir_fd_replace", lambda: False)

    assert fs.read_text("existing.txt") == "safe\n"
    with pytest.raises(UnsafePathError, match="WSL|POSIX"):
        fs.write_text("existing.txt", "hostile\n")
    assert existing.read_text(encoding="utf-8") == "safe\n"


def test_project_fs_rejects_a_symlinked_parent_without_writing_outside(tmp_path):
    project = tmp_path / "project"
    outside = tmp_path / "outside"
    project.mkdir()
    outside.mkdir()
    (project / ".claude").symlink_to(outside, target_is_directory=True)

    fs = ProjectFS(project)
    with pytest.raises(UnsafePathError, match="symlink|reparse|junction"):
        fs.write_text(".claude/settings.json", "hostile\n")
    assert not (outside / "settings.json").exists()


def test_project_fs_rejects_a_symlinked_destination_file(tmp_path):
    project = tmp_path / "project"
    outside = tmp_path / "outside.txt"
    project.mkdir()
    outside.write_text("SAFE\n", encoding="utf-8")
    (project / "CLAUDE.md").symlink_to(outside)

    fs = ProjectFS(project)
    with pytest.raises(UnsafePathError, match="symlink|reparse|junction"):
        fs.write_text("CLAUDE.md", "overwritten\n")
    assert outside.read_text(encoding="utf-8") == "SAFE\n"


@pytest.mark.parametrize(
    ("linked_parent", "destination"),
    [
        (".claude/config", ".claude/config/init-options.json"),
        (".claude-kit.bak-1", ".claude-kit.bak-1/.claude/rules/a.md"),
    ],
)
def test_project_fs_rejects_config_and_backup_parent_links(
    tmp_path, linked_parent, destination
):
    project = tmp_path / "project"
    outside = tmp_path / "outside"
    project.mkdir()
    outside.mkdir()
    parent = project / linked_parent
    parent.parent.mkdir(parents=True, exist_ok=True)
    parent.symlink_to(outside, target_is_directory=True)

    with pytest.raises(UnsafePathError, match="symlink|reparse|junction"):
        ProjectFS(project).write_text(destination, "hostile\n")
    assert not list(outside.iterdir())


def test_project_fs_rejects_a_sidecar_leaf_link(tmp_path):
    project = tmp_path / "project"
    outside = tmp_path / "outside.txt"
    project.mkdir()
    outside.write_text("SAFE\n", encoding="utf-8")
    (project / "CLAUDE.md.claude-kit").symlink_to(outside)

    with pytest.raises(UnsafePathError, match="symlink|reparse|junction"):
        ProjectFS(project).write_text("CLAUDE.md.claude-kit", "hostile\n")
    assert outside.read_text(encoding="utf-8") == "SAFE\n"


def test_project_fs_rejects_relative_parent_symlink_with_dot_dot(tmp_path):
    project = tmp_path / "project"
    outside = tmp_path / "outside"
    project.mkdir()
    outside.mkdir()
    (project / ".claude").symlink_to(Path("..") / "outside", target_is_directory=True)

    with pytest.raises(UnsafePathError, match="symlink|reparse|junction"):
        ProjectFS(project).write_text(".claude/settings.json", "hostile\n")
    assert not (outside / "settings.json").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows reparse-point behavior")
def test_project_fs_rejects_a_windows_reparse_destination(tmp_path):
    project = tmp_path / "project"
    outside = tmp_path / "outside"
    project.mkdir()
    outside.mkdir()
    (project / ".claude").symlink_to(outside, target_is_directory=True)
    with pytest.raises(UnsafePathError, match="symlink|reparse|junction"):
        ProjectFS(project).write_text(".claude/settings.json", "hostile\n")


@pytest.mark.skipif(os.name != "posix", reason="POSIX directory-descriptor hardening")
def test_project_fs_uses_directory_descriptor_atomic_replace(tmp_path):
    assert ProjectFS(tmp_path)._supports_dir_fd_replace()


@pytest.mark.skipif(os.name != "posix", reason="POSIX directory-descriptor hardening")
def test_parent_swap_at_final_mutation_cannot_write_through_new_symlink(
    tmp_path, monkeypatch
):
    project = tmp_path / "project"
    outside = tmp_path / "outside"
    original = project / ".claude"
    original.mkdir(parents=True)
    outside.mkdir()
    fs = ProjectFS(project)

    def swap_parent(_rel, _path):
        original.rename(project / ".claude-held")
        original.symlink_to(outside, target_is_directory=True)

    monkeypatch.setattr(fs, "_before_replace", swap_parent)
    with pytest.raises(UnsafePathError, match="symlink|reparse|junction"):
        fs.write_text(".claude/settings.json", "hostile\n")
    assert not (outside / "settings.json").exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX descriptor-pinned chmod")
def test_chmod_swap_to_outside_hardlink_is_refused(tmp_path, monkeypatch):
    project = tmp_path / "project"
    hook = project / ".claude/hooks/managed.sh"
    hook.parent.mkdir(parents=True)
    hook.write_text("#!/bin/sh\n", encoding="utf-8")
    outside = tmp_path / "outside.sh"
    outside.write_text("safe\n", encoding="utf-8")
    outside.chmod(0o600)
    fs = ProjectFS(project)

    def swap_to_hardlink(_rel, _path):
        hook.unlink()
        os.link(outside, hook)

    monkeypatch.setattr(fs, "_before_chmod", swap_to_hardlink)
    with pytest.raises(UnsafePathError, match="hard link|changed"):
        fs.chmod(".claude/hooks/managed.sh", 0o755)
    assert outside.stat().st_mode & 0o777 == 0o600


@pytest.mark.skipif(os.name != "posix", reason="POSIX descriptor-recursive removal")
def test_recursive_removal_ancestor_swap_cannot_delete_outside(tmp_path, monkeypatch):
    project = tmp_path / "project"
    original = project / ".claude"
    held = project / ".claude-held"
    outside = tmp_path / "outside"
    (original / "rules").mkdir(parents=True)
    (original / "rules" / "inside.md").write_text("inside\n", encoding="utf-8")
    outside.mkdir()
    sentinel = outside / "sentinel.md"
    sentinel.write_text("safe\n", encoding="utf-8")
    fs = ProjectFS(project)

    def swap_ancestor(_rel, _path):
        original.rename(held)
        original.symlink_to(outside, target_is_directory=True)

    monkeypatch.setattr(fs, "_before_remove_tree", swap_ancestor)
    with pytest.raises(UnsafePathError, match="symlink|reparse|junction"):
        fs.remove_tree(".claude/rules")
    assert sentinel.read_text(encoding="utf-8") == "safe\n"


@pytest.mark.skipif(os.name != "posix", reason="POSIX descriptor-pinned promotion")
def test_promoted_source_leaf_swap_is_removed_and_transaction_restores(
    tmp_path, monkeypatch
):
    project = tmp_path / "project"
    original = project / ".claude" / "rules" / "original.md"
    original.parent.mkdir(parents=True)
    original.write_text("original\n", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "sentinel.md").write_text("safe\n", encoding="utf-8")
    fs = ProjectFS(project)

    with pytest.raises(UnsafePathError, match="move source changed"):
        with ProjectTransaction(fs, operation="force") as transaction:
            assembled = f"{transaction.transaction_rel}/assembled/rules"
            retired = f"{transaction.transaction_rel}/retired/rules"
            fs.write_text(f"{assembled}/new.md", "new\n")
            fs.move(".claude/rules", retired)
            assembled_path = project / assembled
            held = assembled_path.with_name("rules-held")

            def swap_source(source_rel, _destination_rel):
                if source_rel != assembled:
                    return
                assembled_path.rename(held)
                assembled_path.symlink_to(outside, target_is_directory=True)

            monkeypatch.setattr(fs, "_before_move", swap_source)
            fs.move(assembled, ".claude/rules")

    assert not (project / ".claude" / "rules").is_symlink()
    assert original.read_text(encoding="utf-8") == "original\n"
    assert (outside / "sentinel.md").read_text(encoding="utf-8") == "safe\n"
    assert not list(project.glob(".claude-kit-txn-*"))


def test_project_transaction_rolls_back_files_and_directories(tmp_path):
    project = tmp_path / "project"
    (project / ".claude" / "rules").mkdir(parents=True)
    original = project / ".claude" / "rules" / "ours.md"
    original.write_text("ours\n", encoding="utf-8")
    root_doc = project / "CLAUDE.md"
    root_doc.write_text("original\n", encoding="utf-8")
    fs = ProjectFS(project)

    with pytest.raises(RuntimeError, match="injected"):
        with ProjectTransaction(fs, operation="install"):
            fs.write_text(".claude/rules/ours.md", "replaced\n")
            fs.write_text(".claude/rules/new.md", "new\n")
            fs.write_text("CLAUDE.md", "new root\n")
            raise RuntimeError("injected failure")

    assert original.read_text(encoding="utf-8") == "ours\n"
    assert not (project / ".claude" / "rules" / "new.md").exists()
    assert root_doc.read_text(encoding="utf-8") == "original\n"
    assert not (project / ".claude" / "config" / "upgrade-in-progress.json").exists()
    assert not list(project.glob(".claude-kit-txn-*"))


def test_project_transaction_exclusive_lease_refuses_a_second_begin(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    first = ProjectTransaction(ProjectFS(project), operation="install")
    first.begin()
    try:
        with pytest.raises(UnsafePathError, match="busy|another.*transaction"):
            ProjectTransaction(ProjectFS(project), operation="merge").begin()
        assert len(list(project.glob(".claude-kit-txn-*"))) == 1
    finally:
        first.rollback()
    assert not list(project.glob(".claude-kit-txn-*"))


def test_transaction_snapshot_failure_leaves_no_stale_transaction_dir(
    tmp_path, monkeypatch
):
    project = tmp_path / "project"
    original = project / ".claude" / "rules" / "ours.md"
    original.parent.mkdir(parents=True)
    original.write_text("ours\n", encoding="utf-8")
    fs = ProjectFS(project)

    def fail_snapshot(*_args, **_kwargs):
        raise RuntimeError("snapshot failed")

    monkeypatch.setattr(fs, "copy_file", fail_snapshot)
    with pytest.raises(RuntimeError, match="snapshot failed"):
        ProjectTransaction(fs, operation="upgrade").begin()
    assert original.read_text(encoding="utf-8") == "ours\n"
    assert not list(project.glob(".claude-kit-txn-*"))
    assert not (project / ".claude" / "config" / "upgrade-in-progress.json").exists()


@pytest.mark.parametrize("preexisting", [False, True])
def test_transaction_journal_publish_failure_restores_setup_atomically(
    tmp_path, monkeypatch, preexisting
):
    project = tmp_path / "project"
    original = project / ".claude" / "rules" / "ours.md"
    if preexisting:
        original.parent.mkdir(parents=True)
        original.write_text("ours\n", encoding="utf-8")
    fs = ProjectFS(project)
    real_write = fs.write_text

    def fail_journal(rel, *args, **kwargs):
        if str(rel) == ".claude/config/upgrade-in-progress.json":
            raise OSError("injected journal publish failure")
        return real_write(rel, *args, **kwargs)

    monkeypatch.setattr(fs, "write_text", fail_journal)
    with pytest.raises(OSError, match="journal publish"):
        ProjectTransaction(fs, operation="install").begin()

    if preexisting:
        assert original.read_text(encoding="utf-8") == "ours\n"
        assert not (project / ".claude" / "config").exists()
    else:
        assert not project.exists()
    if project.exists():
        assert not list(project.glob(".claude-kit-txn-*"))


def test_interrupted_transaction_is_schema_versioned_and_recoverable(tmp_path):
    project = tmp_path / "project"
    (project / ".claude" / "rules").mkdir(parents=True)
    original = project / ".claude" / "rules" / "ours.md"
    original.write_text("ours\n", encoding="utf-8")
    fs = ProjectFS(project)
    txn = ProjectTransaction(fs, operation="install")
    txn.begin()
    fs.write_text(".claude/rules/ours.md", "partial\n")

    journal = project / ".claude" / "config" / "upgrade-in-progress.json"
    doc = json.loads(journal.read_text(encoding="utf-8"))
    assert doc["schema_version"] == TRANSACTION_SCHEMA
    assert doc["transaction_kind"] == "install"

    assert recover_interrupted_transaction(fs)
    assert original.read_text(encoding="utf-8") == "ours\n"
    assert not journal.exists()
    assert not list(project.glob(".claude-kit-txn-*"))


def test_recovery_preflights_complete_snapshot_before_touching_live_tree(tmp_path):
    project = tmp_path / "project"
    original = project / "CLAUDE.md"
    original.parent.mkdir()
    original.write_text("original\n", encoding="utf-8")
    fs = ProjectFS(project)
    txn = ProjectTransaction(fs, operation="install")
    txn.begin()
    fs.write_text("CLAUDE.md", "valuable partial state\n")
    fs.unlink(f"{txn.transaction_rel}/rollback/CLAUDE.md")

    with pytest.raises(UnsafePathError, match="file backup missing"):
        recover_interrupted_transaction(fs)
    assert original.read_text(encoding="utf-8") == "valuable partial state\n"


def test_recovery_refuses_future_transaction_schema_without_overwriting_it(tmp_path):
    fs = ProjectFS(tmp_path)
    document = {"schema_version": 999, "transaction_kind": "install"}
    fs.write_text(
        ".claude/config/upgrade-in-progress.json",
        json.dumps(document) + "\n",
    )

    with pytest.raises(UnsafePathError, match="unsupported journal schema 999"):
        recover_interrupted_transaction(fs)
    assert (
        json.loads(fs.read_text(".claude/config/upgrade-in-progress.json")) == document
    )


def test_recovery_deliberately_leaves_legacy_schema_one_for_upgrader(tmp_path):
    fs = ProjectFS(tmp_path)
    document = {
        "schema_version": 1,
        "from_version": "0.1.0",
        "to_version": "0.2.0",
        "started_at": "2026-01-01T00:00:00+00:00",
        "actions": [],
    }
    fs.write_text(
        ".claude/config/upgrade-in-progress.json",
        json.dumps(document) + "\n",
    )

    assert not recover_interrupted_transaction(fs)
    assert (
        json.loads(fs.read_text(".claude/config/upgrade-in-progress.json")) == document
    )


class _SimulatedCommitProcessDeath(BaseException):
    pass


def test_committed_orphan_marker_is_cleaned_without_rollback(tmp_path, monkeypatch):
    project = tmp_path / "project"
    original = project / "CLAUDE.md"
    original.parent.mkdir()
    original.write_text("original\n", encoding="utf-8")
    fs = ProjectFS(project)
    txn = ProjectTransaction(fs, operation="install")
    txn.begin()
    fs.write_text("CLAUDE.md", "committed\n")
    real_remove = fs.remove_tree

    def die_during_cleanup(rel, *args, **kwargs):
        if str(rel) == txn.transaction_rel:
            raise _SimulatedCommitProcessDeath()
        return real_remove(rel, *args, **kwargs)

    monkeypatch.setattr(fs, "remove_tree", die_during_cleanup)
    with pytest.raises(_SimulatedCommitProcessDeath):
        txn.commit()
    assert not fs.exists(".claude/config/upgrade-in-progress.json")
    marker = project / txn.transaction_rel / "transaction.json"
    assert json.loads(marker.read_text(encoding="utf-8"))["phase"] == "committed"

    monkeypatch.undo()
    assert recover_interrupted_transaction(ProjectFS(project))
    assert original.read_text(encoding="utf-8") == "committed\n"
    assert not marker.parent.exists()


def test_missing_selected_component_fails_before_target_is_touched(tmp_path, payload):
    target = tmp_path / "project"
    plan = catalog.resolve(payload, make_selection(payload))
    plan = replace(plan, agents=[*plan.agents, "definitely-missing-agent"])

    with pytest.raises(FileNotFoundError, match="definitely-missing-agent"):
        scaffold.install_sdlc(payload, target, plan)

    assert not target.exists()


def test_packager_bytecode_is_not_installed_as_payload(tmp_path):
    """Pip compileall output inside ``_payload`` is not selected product content."""

    source = tmp_path / "source-skill"
    (source / "scripts" / "__pycache__").mkdir(parents=True)
    (source / "SKILL.md").write_text("# Skill\n", encoding="utf-8")
    (source / "scripts" / "tool.py").write_text("pass\n", encoding="utf-8")
    (source / "scripts" / "__pycache__" / "tool.cpython-314.pyc").write_bytes(
        b"compiled junk"
    )
    (source / "scripts" / "stray.pyo").write_bytes(b"optimized junk")

    project = tmp_path / "project"
    project.mkdir()
    fs = ProjectFS(project)
    destination = project / ".claude" / "skills" / "example"
    scaffold._copy_tree(source, destination, fs=fs)

    assert (destination / "SKILL.md").is_file()
    assert (destination / "scripts" / "tool.py").is_file()
    assert not (destination / "scripts" / "__pycache__").exists()
    assert not (destination / "scripts" / "stray.pyo").exists()


def test_staged_manifest_missing_target_fails_validation(tmp_path):
    stage = tmp_path / "stage"
    config = stage / ".claude" / "config"
    config.mkdir(parents=True)
    (config / "init-options.json").write_text(
        json.dumps(
            {
                "files": [
                    {
                        "path": ".claude/rules/missing.md",
                        "sha256": "0" * 64,
                        "owner": "kit",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="missing target"):
        scaffold._validate_stage(stage)


def test_live_apply_uses_validated_stage_after_payload_changes(
    tmp_path, payload, monkeypatch
):
    source = tmp_path / "payload"
    for name in ("rules", "agents", "skills", "hooks", "templates"):
        shutil.copytree(payload / name, source / name)
    plan = catalog.resolve(payload, make_selection(payload))
    original = (source / "rules" / "testing.md").read_bytes()

    def mutate_payload(_stage):
        (source / "rules" / "testing.md").write_text(
            "MUTATED AFTER VALIDATION\n", encoding="utf-8"
        )

    monkeypatch.setattr(scaffold, "_before_live_apply", mutate_payload)
    target = tmp_path / "project"
    scaffold.install_sdlc(source, target, plan)

    assert (source / "rules" / "testing.md").read_bytes() != original
    assert (target / ".claude" / "rules" / "testing.md").read_bytes() == original


def test_force_downgrade_matches_clean_selected_component_tree(tmp_path, payload):
    downgraded = tmp_path / "downgraded"
    clean = tmp_path / "clean"
    enterprise = catalog.resolve(
        payload,
        make_selection(payload, profile="enterprise", scope="organization"),
    )
    enterprise.context["project_name"] = "same-project"
    scaffold.install_sdlc(payload, downgraded, enterprise, force=True)

    lean = catalog.resolve(
        payload, make_selection(payload, profile="lean", scope="team")
    )
    lean.context["project_name"] = "same-project"
    scaffold.install_sdlc(payload, downgraded, lean, force=True)
    clean_lean = catalog.resolve(
        payload, make_selection(payload, profile="lean", scope="team")
    )
    clean_lean.context["project_name"] = "same-project"
    scaffold.install_sdlc(payload, clean, clean_lean, force=True)

    def installed_files(root):
        return {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*")
            if path.is_file()
        }

    assert installed_files(downgraded) == installed_files(clean)
    assert not (downgraded / ".claude" / "org-packs").exists()
    ok, messages = validator.validate(downgraded, strict=True)
    assert ok, messages


def test_upgrade_refuses_future_stack_snapshot_schema_without_overwrite(
    tmp_path, payload
):
    plan = catalog.resolve(payload, make_selection(payload))
    scaffold.install_sdlc(payload, tmp_path, plan)
    snapshot = tmp_path / ".claude/config/stack-catalog.snapshot.yaml"
    document = yaml.safe_load(snapshot.read_text(encoding="utf-8"))
    document["schema_version"] = 999
    snapshot.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    before = snapshot.read_bytes()

    ok, messages = upgrader.upgrade(tmp_path)

    assert not ok
    assert any("future stack snapshot schema_version 999" in item for item in messages)
    assert snapshot.read_bytes() == before
    assert not list(tmp_path.glob(".claude-kit.bak-*"))


def test_install_gitignores_transaction_and_both_backup_families(tmp_path, payload):
    plan = catalog.resolve(payload, make_selection(payload))
    scaffold.install_sdlc(payload, tmp_path, plan)
    entries = set((tmp_path / ".gitignore").read_text(encoding="utf-8").splitlines())
    assert {".claude-kit-txn-*/", ".claude-kit.bak-*/", ".claude.bak-*/"} <= entries


def test_selected_mcp_preserves_user_config_without_claiming_missing_lock(
    tmp_path, payload
):
    user_mcp = tmp_path / ".mcp.json"
    user_mcp.write_text(
        '{"mcpServers":{"mine":{"command":"echo","args":[]}}}\n',
        encoding="utf-8",
    )
    plan = catalog.resolve(payload, make_selection(payload, mcp=["github"]))

    scaffold.install_sdlc(payload, tmp_path, plan, force=False)

    assert json.loads(user_mcp.read_text(encoding="utf-8")) == {
        "mcpServers": {"mine": {"command": "echo", "args": []}}
    }
    assert (tmp_path / ".mcp.json.claude-kit").is_file()
    assert not (tmp_path / ".mcp.lock.json").exists()
    options = json.loads(
        (tmp_path / ".claude/config/init-options.json").read_text(encoding="utf-8")
    )
    assert ".mcp.lock.json" not in {record["path"] for record in options["files"]}


def test_no_mcp_plan_preserves_an_untracked_orphan_lock(tmp_path, payload):
    lock = tmp_path / ".mcp.lock.json"
    lock.write_text(
        '{"schema":1,"servers":{"mine":{"type":"stdio","command":"echo"}}}\n',
        encoding="utf-8",
    )
    before = lock.read_bytes()
    plan = catalog.resolve(payload, make_selection(payload, mcp=[]))

    scaffold.install_sdlc(payload, tmp_path, plan)

    assert lock.read_bytes() == before
    options = json.loads(
        (tmp_path / ".claude/config/init-options.json").read_text(encoding="utf-8")
    )
    assert ".mcp.lock.json" not in {record["path"] for record in options["files"]}


def test_failed_stage_is_cleaned_without_creating_live_target(
    tmp_path, payload, monkeypatch
):
    target = tmp_path / "project"
    plan = catalog.resolve(payload, make_selection(payload))
    captured: Path | None = None

    def reject(stage):
        nonlocal captured
        captured = stage
        raise RuntimeError("invalid staged output")

    monkeypatch.setattr(scaffold, "_validate_stage", reject)
    with pytest.raises(RuntimeError, match="invalid staged"):
        scaffold.install_sdlc(payload, target, plan)
    assert captured is not None and not captured.exists()
    assert not target.exists()


@pytest.mark.parametrize(
    ("failure_symbol", "failure_call"),
    [
        ("_promote_staged_subtree", 2),  # core rules were already promoted
        ("_promote_staged_subtree", 3),  # selected agents were already promoted
        ("_copy_staged_user_file", 2),  # settings.json was already handled
        ("_write_final_manifest_from_stage", 1),
    ],
)
def test_failed_live_install_restores_the_previous_tree(
    tmp_path, payload, monkeypatch, failure_symbol, failure_call
):
    target = tmp_path / "project"
    plan = catalog.resolve(payload, make_selection(payload))
    scaffold.install_sdlc(payload, target, plan)
    user_rule = target / ".claude" / "rules" / "company.md"
    user_rule.write_text("keep\n", encoding="utf-8")
    before = {
        p.relative_to(target): p.read_bytes() for p in target.rglob("*") if p.is_file()
    }

    real = getattr(scaffold, failure_symbol)
    calls = 0

    def fail_second_call(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == failure_call:
            raise RuntimeError("injected before manifest commit")
        return real(*args, **kwargs)

    monkeypatch.setattr(scaffold, failure_symbol, fail_second_call)
    with pytest.raises(RuntimeError, match="before manifest"):
        scaffold.install_sdlc(payload, target, plan, force=True)

    after = {
        p.relative_to(target): p.read_bytes() for p in target.rglob("*") if p.is_file()
    }
    assert after == before
    assert user_rule.read_text(encoding="utf-8") == "keep\n"
    assert not list(target.glob(".claude-kit-txn-*"))


def test_backup_install_is_committed_inside_the_transaction(tmp_path, payload):
    target = tmp_path / "project"
    custom = target / ".claude" / "custom.txt"
    custom.parent.mkdir(parents=True)
    custom.write_text("mine\n", encoding="utf-8")
    plan = catalog.resolve(payload, make_selection(payload))

    scaffold.install_sdlc(payload, target, plan, backup_existing=True)

    assert (target / ".claude.bak-1" / "custom.txt").read_text() == "mine\n"
    assert (target / ".claude" / "config" / "init-options.json").is_file()
    assert not list(target.glob(".claude-kit-txn-*"))


def test_failed_backup_install_restores_active_tree_and_removes_new_backup(
    tmp_path, payload, monkeypatch
):
    target = tmp_path / "project"
    custom = target / ".claude" / "custom.txt"
    custom.parent.mkdir(parents=True)
    custom.write_text("mine\n", encoding="utf-8")
    plan = catalog.resolve(payload, make_selection(payload))

    def fail_live(*_args, **_kwargs):
        raise RuntimeError("injected backup install failure")

    monkeypatch.setattr(scaffold, "_write_final_manifest_from_stage", fail_live)
    with pytest.raises(RuntimeError, match="backup install"):
        scaffold.install_sdlc(payload, target, plan, backup_existing=True)

    assert custom.read_text(encoding="utf-8") == "mine\n"
    assert not (target / ".claude.bak-1").exists()
    assert not list(target.glob(".claude-kit-txn-*"))


class _SimulatedInstallProcessDeath(BaseException):
    pass


def test_interrupted_first_install_retains_journal_then_recovers_and_converges(
    tmp_path, payload, monkeypatch
):
    target = tmp_path / "project"
    plan = catalog.resolve(payload, make_selection(payload))

    def die_live(*_args, **_kwargs):
        raise _SimulatedInstallProcessDeath()

    monkeypatch.setattr(scaffold, "_write_final_manifest_from_stage", die_live)
    with pytest.raises(_SimulatedInstallProcessDeath):
        scaffold.install_sdlc(payload, target, plan)

    journal = target / ".claude" / "config" / "upgrade-in-progress.json"
    assert journal.is_file()
    assert json.loads(journal.read_text())["transaction_kind"] == "install"

    monkeypatch.undo()
    scaffold.install_sdlc(payload, target, plan)
    assert not journal.exists()
    assert (target / ".claude" / "config" / "init-options.json").is_file()
    assert not list(target.glob(".claude-kit-txn-*"))


def test_interrupted_first_install_merge_keeps_the_exclusive_lease_on_live_root(
    tmp_path, payload, monkeypatch
):
    """CLI-style merge recovery cannot keep a flock on a deleted root inode."""
    target = tmp_path / "project"
    fs = ProjectFS(target)
    with pytest.raises(_SimulatedInstallProcessDeath):
        with ProjectTransaction(fs, operation="install"):
            fs.write_text(".claude/rules/partial.md", "partial\n")
            raise _SimulatedInstallProcessDeath()

    plan = catalog.resolve(payload, make_selection(payload))
    real_recover = upgrader.recover_interrupted_transaction
    observed = False

    def assert_root_lock_identity(locked_fs, **kwargs):
        nonlocal observed
        result = real_recover(locked_fs, **kwargs)
        held = os.fstat(locked_fs._lease_local.fd)
        live = os.stat(locked_fs.root, follow_symlinks=False)
        assert (held.st_dev, held.st_ino) == (live.st_dev, live.st_ino)
        with pytest.raises(UnsafePathError, match="project mutation is busy"):
            with ProjectFS(target).mutation_lease(exclusive=True):
                pass
        observed = True
        return result

    monkeypatch.setattr(
        upgrader, "recover_interrupted_transaction", assert_root_lock_identity
    )
    ok, messages = upgrader.merge_install(payload, target, plan)

    assert observed
    assert ok, "\n".join(messages)
    assert (target / ".claude/config/init-options.json").is_file()


def test_interrupted_backup_install_is_visible_via_authoritative_top_marker(
    tmp_path, payload, monkeypatch
):
    target = tmp_path / "project"
    custom = target / ".claude/custom.txt"
    custom.parent.mkdir(parents=True)
    custom.write_text("mine\n", encoding="utf-8")
    plan = catalog.resolve(payload, make_selection(payload))

    def die_live(*_args, **_kwargs):
        raise _SimulatedInstallProcessDeath()

    monkeypatch.setattr(scaffold, "_write_final_manifest_from_stage", die_live)
    with pytest.raises(_SimulatedInstallProcessDeath):
        scaffold.install_sdlc(payload, target, plan, backup_existing=True)

    assert not (target / ".claude/config/upgrade-in-progress.json").exists()
    document = inspect_interrupted_transaction(ProjectFS(target))
    assert document is not None
    assert document["schema_version"] == TRANSACTION_SCHEMA
    assert document["phase"] == "applying"
    assert document["transaction_kind"] == "force"

    monkeypatch.undo()
    scaffold.install_sdlc(payload, target, plan, backup_existing=True)
    assert (target / ".claude.bak-1/custom.txt").read_text(encoding="utf-8") == "mine\n"
    assert (target / ".claude/config/init-options.json").is_file()
    assert inspect_interrupted_transaction(ProjectFS(target)) is None
