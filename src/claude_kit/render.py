"""Jinja2-backed template renderer for claude-kit.

Design goals (unchanged from the original stdlib renderer, now powered by Jinja2):

* **Never corrupt literal braces.** Only files whose name ends in ``.tmpl`` are rendered; every
  other file is copied byte-for-byte. So any literal ``{{``/``{%`` in non-template files (JSON
  examples, shell, etc.) is left exactly as written.
* **Ship dotfiles reliably.** A path segment named ``dot__foo`` is written as ``.foo``
  (``dot__gitignore`` -> ``.gitignore``). This keeps real dotfiles out of the template tree (where
  some packaging tools silently drop them) and greppable in the repo.
* **Fail loud on a missing value.** The Jinja environment uses ``StrictUndefined``; an undefined
  placeholder raises (surfaced as :class:`KeyError`) rather than rendering a blank.

Substitution syntax is Jinja2 (``{{ name }}``), so existing ``.tmpl`` files work unchanged.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from jinja2 import Environment, StrictUndefined
from jinja2.exceptions import UndefinedError

#: Suffix marking a file as a template (stripped from the rendered output name).
TEMPLATE_SUFFIX = ".tmpl"

#: Prefix marking a path segment that should become a dotfile/dotdir on output.
DOTFILE_PREFIX = "dot__"

#: Shared Jinja environment. ``keep_trailing_newline`` preserves files' final newline; autoescape is
#: off because we render Markdown/JSON/text, never HTML.
_ENV = Environment(
    undefined=StrictUndefined,
    keep_trailing_newline=True,
    autoescape=False,
    trim_blocks=False,
    lstrip_blocks=False,
)

#: Directory names never copied from a template tree (build droppings / VCS / vendored deps).
_IGNORE_DIRS = frozenset(
    {
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "dist",
        "coverage",
        ".DS_Store",
    }
)

#: File names/suffixes never copied from a template tree.
_IGNORE_FILE_SUFFIXES = (".pyc", ".pyo")
_IGNORE_FILE_NAMES = frozenset({".DS_Store"})


def _is_ignored(rel: Path) -> bool:
    """Return True if ``rel`` is build/VCS junk that must never be rendered."""
    if _IGNORE_DIRS & set(rel.parts):
        return True
    name = rel.name
    return name in _IGNORE_FILE_NAMES or name.endswith(_IGNORE_FILE_SUFFIXES)


def render_text(text: str, context: dict[str, Any]) -> str:
    """Render Jinja2 ``text`` against ``context``.

    Args:
        text: Template text (Jinja2 syntax, e.g. ``{{ name }}``).
        context: Mapping of placeholder name to replacement value.

    Returns:
        The rendered text.

    Raises:
        KeyError: If the template references a name absent from ``context`` (fail-loud parity
            with the previous renderer).
    """
    try:
        return _ENV.from_string(text).render(**context)
    except UndefinedError as exc:  # surface as KeyError to keep the existing contract
        raise KeyError(str(exc)) from exc


def _resolve_name(name: str) -> str:
    """Map a single template path segment to its output name (strip ``.tmpl``, ``dot__`` -> ``.``)."""
    if name.endswith(TEMPLATE_SUFFIX):
        name = name[: -len(TEMPLATE_SUFFIX)]
    if name.startswith(DOTFILE_PREFIX):
        name = "." + name[len(DOTFILE_PREFIX) :]
    return name


def _resolve_relpath(rel: Path) -> Path:
    """Apply :func:`_resolve_name` to every segment of a relative path."""
    return Path(*[_resolve_name(part) for part in rel.parts])


def render_tree(src: Path, dest: Path, context: dict[str, Any]) -> list[Path]:
    """Render the template directory ``src`` into ``dest``.

    The *contents* of ``src`` are written into ``dest``. ``*.tmpl`` files are rendered with Jinja2
    and written without the suffix; all other files are copied verbatim. ``dot__``-prefixed segments
    become dotfiles/dotdirs. Existing destination files are overwritten; parents are created.

    Args:
        src: Source template directory.
        dest: Destination directory (created if missing).
        context: Substitution values for ``.tmpl`` files.

    Returns:
        The written destination file paths (directories excluded).

    Raises:
        FileNotFoundError: If ``src`` is not an existing directory.
        KeyError: If a ``.tmpl`` file references an unknown placeholder.
    """
    if not src.is_dir():
        raise FileNotFoundError(f"template source not found: {src}")

    written: list[Path] = []
    for entry in sorted(src.rglob("*")):
        rel = entry.relative_to(src)
        if _is_ignored(rel):
            continue
        target = dest / _resolve_relpath(rel)
        if entry.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if entry.name.endswith(TEMPLATE_SUFFIX):
            target.write_text(
                render_text(entry.read_text(encoding="utf-8"), context),
                encoding="utf-8",
            )
        else:
            shutil.copy2(entry, target)
        written.append(target)
    return written
