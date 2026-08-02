"""Jinja2 rendering: fail-loud, .tmpl-gating, dotfile rename, verbatim copy."""

from __future__ import annotations

import pytest

from claude_kit import render


def test_render_text_substitutes():
    assert render.render_text("hi {{ name }}", {"name": "kit"}) == "hi kit"


def test_render_text_is_fail_loud():
    """A missing variable must raise KeyError (StrictUndefined), never render an empty string."""
    with pytest.raises(KeyError):
        render.render_text("hi {{ missing }}", {})


def test_render_tree_only_renders_tmpl_and_renames_dotfiles(tmp_path):
    src = tmp_path / "src"
    dest = tmp_path / "dest"
    src.mkdir()
    # A .tmpl file is rendered and loses its suffix.
    (src / "greeting.txt.tmpl").write_text("hello {{ who }}", encoding="utf-8")
    # A non-.tmpl file is copied byte-for-byte, even if it contains braces.
    (src / "literal.txt").write_text("not a {{ template }}", encoding="utf-8")
    # dot__ prefix becomes a real dotfile.
    (src / "dot__gitignore").write_text("ignored\n", encoding="utf-8")

    render.render_tree(src, dest, {"who": "world"})

    assert (dest / "greeting.txt").read_text(encoding="utf-8") == "hello world"
    assert not (dest / "greeting.txt.tmpl").exists()
    assert (dest / "literal.txt").read_text(encoding="utf-8") == "not a {{ template }}"
    assert (dest / ".gitignore").read_text(encoding="utf-8") == "ignored\n"


# --- render_tree: what is skipped, what is created, and what fails loudly -----------------------


def test_render_tree_fails_loudly_on_a_missing_source(tmp_path):
    with pytest.raises(FileNotFoundError, match="template source not found"):
        render.render_tree(tmp_path / "nope", tmp_path / "out", {})


def test_render_tree_skips_build_junk_and_recreates_directories(tmp_path):
    """Build/VCS junk must never reach a user's project, but real subdirectories must."""
    src = tmp_path / "src"
    (src / "__pycache__").mkdir(parents=True)
    (src / "__pycache__" / "stale.pyc").write_text("junk", encoding="utf-8")
    (src / "nested" / "deep").mkdir(parents=True)
    (src / "nested" / "deep" / "keep.txt").write_text("kept\n", encoding="utf-8")
    (src / ".DS_Store").write_text("junk", encoding="utf-8")
    (src / "stray.pyo").write_text("junk", encoding="utf-8")

    dest = tmp_path / "out"
    written = render.render_tree(src, dest, {})

    assert (dest / "nested" / "deep").is_dir()
    kept = dest / "nested" / "deep" / "keep.txt"
    assert kept.read_text(encoding="utf-8") == "kept\n"
    assert not (dest / "__pycache__").exists()
    assert not (dest / ".DS_Store").exists()
    assert not (dest / "stray.pyo").exists()
    assert [p.name for p in written] == ["keep.txt"]


def test_is_ignored_covers_dirs_names_and_suffixes():
    from pathlib import Path

    assert render._is_ignored(Path("__pycache__/x.txt"))
    assert render._is_ignored(Path("a/.DS_Store"))
    assert render._is_ignored(Path("a/mod.pyc"))
    assert not render._is_ignored(Path("a/keep.md"))
