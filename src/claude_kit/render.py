"""Minimal, dependency-free template renderer for claude-kit's project generator.

Design goals:

* **No third-party deps.** claude-kit's CLI is stdlib-only; the generator keeps that promise.
* **Never corrupt literal braces.** Only files whose name ends in ``.tmpl`` are substituted; every
  other file is copied byte-for-byte. That means React JSX (``{foo}``), shell ``${VAR}``, and CSS
  ``{}`` in non-template files are left exactly as written — no escaping gymnastics.
* **Ship dotfiles reliably.** Files/dirs whose name starts with ``dot__`` are written with a leading
  ``.`` instead (``dot__gitignore`` -> ``.gitignore``). This keeps real dotfiles out of the template
  tree, where some build/packaging tools silently drop them, and keeps them greppable in the repo.

Substitution syntax is ``{{ name }}`` (optional surrounding whitespace). A placeholder with no
matching key in the context raises ``KeyError`` — generation fails loud rather than writing a file
with a blank where a value should be.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

#: Placeholder pattern: ``{{ name }}`` with optional inner whitespace.
_PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")

#: Suffix marking a file as a template (stripped from the rendered output name).
TEMPLATE_SUFFIX = ".tmpl"

#: Prefix marking a path segment that should become a dotfile/dotdir on output.
DOTFILE_PREFIX = "dot__"

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


def render_text(text: str, context: dict[str, str]) -> str:
    """Substitute ``{{ name }}`` placeholders in ``text`` using ``context``.

    Args:
        text: Template text that may contain ``{{ name }}`` placeholders.
        context: Mapping of placeholder name to replacement value.

    Returns:
        ``text`` with every placeholder replaced by its context value.

    Raises:
        KeyError: If a placeholder name is absent from ``context``.
    """

    def _sub(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in context:
            raise KeyError(
                f"template placeholder {{{{ {key} }}}} has no value in the render context"
            )
        return context[key]

    return _PLACEHOLDER.sub(_sub, text)


def _resolve_name(name: str) -> str:
    """Map a single template path segment to its output name.

    Applies the ``dot__`` -> ``.`` rewrite and strips a trailing ``.tmpl`` suffix.

    Args:
        name: A single path segment from the template tree.

    Returns:
        The corresponding output segment name.
    """
    if name.endswith(TEMPLATE_SUFFIX):
        name = name[: -len(TEMPLATE_SUFFIX)]
    if name.startswith(DOTFILE_PREFIX):
        name = "." + name[len(DOTFILE_PREFIX) :]
    return name


def _resolve_relpath(rel: Path) -> Path:
    """Apply :func:`_resolve_name` to every segment of a relative path."""
    return Path(*[_resolve_name(part) for part in rel.parts])


def render_tree(src: Path, dest: Path, context: dict[str, str]) -> list[Path]:
    """Render the template directory ``src`` into ``dest``.

    The *contents* of ``src`` are written into ``dest`` (not ``src`` itself). ``*.tmpl`` files are
    substituted with ``context`` and written without the suffix; all other files are copied
    verbatim. ``dot__``-prefixed segments become dotfiles/dotdirs. Existing destination files are
    overwritten; parent directories are created as needed.

    Args:
        src: Source template directory.
        dest: Destination directory (created if missing).
        context: Substitution values applied to ``.tmpl`` files.

    Returns:
        The list of written destination file paths (directories excluded).

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
            rendered = render_text(entry.read_text(encoding="utf-8"), context)
            target.write_text(rendered, encoding="utf-8")
        else:
            shutil.copy2(entry, target)
        written.append(target)
    return written
