"""Frontmatter invariants for every agent file the payload ships (round-3 item 5).

Claude Code silently ignores unknown frontmatter keys, so a typo'd permission key is an
*invisible* defect: the agent simply runs without the intended mode. That exact bug shipped
twice (``mode: plan`` in 0.7.0-era core agents, then again in all six org personas), so this
pins the class shut across the whole payload: core ``agents/``, stack overlay agents, and the
org personas.
"""

from __future__ import annotations

import re
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


def test_auditor_is_read_only_by_allowlist_not_by_discipline(payload):
    """The auditor must not hold Write/Edit/Agent (F-023).

    It used to omit `tools:` entirely -- inheriting the full toolset -- on the stated grounds that
    an explicit list would exclude its Chrome DevTools MCP tools. That premise is false: the
    subagent frontmatter accepts server-level MCP patterns, so `mcp__chrome-devtools` grants the
    whole server while still excluding the write and spawn tools its own description disclaims.
    """
    text = (payload / "agents" / "auditor.md").read_text(encoding="utf-8")
    front = text.split("---", 2)[1]
    line = next(
        (ln for ln in front.splitlines() if ln.startswith("tools:")),
        "",
    )
    assert line, "auditor.md must declare an explicit tools allowlist"
    granted = {t.strip() for t in line.split(":", 1)[1].split(",")}
    assert "mcp__chrome-devtools" in granted, "the MCP server grant must survive"
    assert not (granted & {"Write", "Edit", "Agent", "Task", "NotebookEdit"})


# Claude Code selects a subagent by matching the request against `description`. A description whose
# FIRST sentence says when the agent runs in the pipeline, rather than what work it does, gives the
# matcher nothing a user's request can match -- measured at 2 PASS / 5 not-PASS for position-shaped
# descriptions against 19 PASS / 14 not-PASS for task-shaped ones (F-069). Two position-shaped
# agents were substituted under auto-selection yet passed cleanly when dispatched BY NAME, which is
# what makes this a selection defect rather than a capability one.
_POSITION_LEAD = re.compile(
    r"\bPhase\s+\d|\bRuns\s+(?:at|after)\b|\bUse\s+after\b|^Final\s+\w+\s+gate\b",
    re.IGNORECASE,
)


def _first_sentence(text: str) -> str:
    for sep in (". ", "; "):
        if sep in text:
            return text.split(sep, 1)[0]
    return text


def test_agent_descriptions_lead_with_a_trigger_not_a_pipeline_position(payload):
    """Pipeline position may appear, but not as the first thing the matcher reads (F-069)."""
    offenders = []
    for f in sorted((payload / "agents").glob("*.md")):
        fm = _frontmatter(f)
        desc = str(fm.get("description", ""))
        if _POSITION_LEAD.search(_first_sentence(desc)):
            offenders.append(f"{f.name}: {_first_sentence(desc)!r}")
    assert not offenders, (
        "these agent descriptions open with a pipeline position instead of the work that "
        "triggers them; move the position to a trailing clause:\n  "
        + "\n  ".join(offenders)
    )
