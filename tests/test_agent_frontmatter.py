"""Frontmatter invariants for every agent file the payload ships (round-3 item 5).

Claude Code silently ignores unknown frontmatter keys, so a typo'd permission key is an
*invisible* defect: the agent simply runs without the intended mode. That exact bug shipped
twice (``mode: plan`` in 0.7.0-era core agents, then again in all six org personas), so this
pins the class shut across the whole payload: core ``agents/``, stack overlay agents, and the
org personas.
"""

from __future__ import annotations

from pathlib import Path

import yaml

# The permission modes the kit deliberately uses. Claude Code documents more
# (default/manual, bypassPermissions, dontAsk, auto), but the kit's design only ever assigns
# these two — widening this set is a deliberate decision, not a drive-by.
_KIT_PERMISSION_MODES = {"plan", "acceptEdits"}


def _agent_files(payload: Path) -> list[Path]:
    files = sorted(payload.glob("agents/*.md"))
    files += sorted(payload.glob("templates/stacks/**/agents/*.md"))
    files += sorted(payload.glob("templates/org/agents/*.md"))
    assert len(files) >= 34, f"agent glob looks broken: found only {len(files)}"
    return files


def _frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path.name}: missing frontmatter fence"
    block = text.split("---\n", 2)[1]
    data = yaml.safe_load(block)
    assert isinstance(data, dict), f"{path.name}: frontmatter is not a mapping"
    return data


def test_every_agent_has_name_and_description(payload: Path) -> None:
    for f in _agent_files(payload):
        fm = _frontmatter(f)
        assert fm.get("name"), f"{f}: missing name"
        assert fm.get("description"), f"{f}: missing description"


def test_no_agent_uses_the_ignored_mode_key(payload: Path) -> None:
    """``mode:`` is not a Claude Code agent frontmatter key — it is silently ignored, leaving
    the agent without the permission confinement its author intended. Use ``permissionMode:``."""
    offenders = [str(f) for f in _agent_files(payload) if "mode" in _frontmatter(f)]
    assert not offenders, f"agents using the ignored 'mode:' key: {offenders}"


def test_permission_modes_are_valid_kit_values(payload: Path) -> None:
    for f in _agent_files(payload):
        fm = _frontmatter(f)
        if "permissionMode" in fm:
            assert fm["permissionMode"] in _KIT_PERMISSION_MODES, (
                f"{f}: permissionMode {fm['permissionMode']!r} is not one the kit assigns "
                f"({sorted(_KIT_PERMISSION_MODES)})"
            )
