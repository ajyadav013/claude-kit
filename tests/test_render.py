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
