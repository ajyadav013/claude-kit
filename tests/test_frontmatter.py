"""Frontmatter hygiene for every shipped component (agents, commands, skills — core, org, stacks).

Claude Code parses YAML frontmatter at load time. Two papercuts are easy to introduce by hand and
invisible until something loads them:

* an unquoted ``: `` inside a scalar makes strict YAML raise *"mapping values are not allowed here"*;
* a skill ``description`` over Anthropic's hard 1024-char cap risks truncation/rejection on load.

This sweeps the whole payload and fails fast on either. (It would have caught ``security-reviewer``,
``smoke-test`` and two ``templates/org`` skills.) Source-checkout only — the wheel ships the payload
under ``claude_kit/_payload`` instead of these repo-root directories.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(
    not (REPO_ROOT / "skills").is_dir(),
    reason="component sources only present in a source checkout, not the wheel",
)

#: Every directory layout that ships a component with YAML frontmatter.
_GLOBS = (
    "agents/*.md",
    "commands/*.md",
    "skills/*/SKILL.md",
    "templates/org/agents/*.md",
    "templates/org/skills/*/SKILL.md",
    "templates/stacks/*/*/agents/*.md",
    "templates/stacks/*/*/skills/*/SKILL.md",
)

#: Anthropic's hard cap on a skill ``description``.
DESCRIPTION_LIMIT = 1024


def _component_files() -> list[Path]:
    files: list[Path] = []
    for pattern in _GLOBS:
        files.extend(sorted(REPO_ROOT.glob(pattern)))
    return files


def _frontmatter(path: Path) -> dict:
    """Parse a component's YAML frontmatter under *strict* rules (raises on the ``: `` bug)."""
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---", text, re.S)
    assert match, f"{path.relative_to(REPO_ROOT)} has no YAML frontmatter block"
    data = yaml.safe_load(match.group(1))
    assert isinstance(data, dict), (
        f"{path.relative_to(REPO_ROOT)} frontmatter is not a mapping"
    )
    return data


def _ids(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def test_sweep_finds_the_payload() -> None:
    """Guard against a silently-empty glob hiding real failures (148 components at time of writing)."""
    assert len(_component_files()) > 50


@pytest.mark.parametrize("path", _component_files(), ids=_ids)
def test_component_frontmatter_is_strict_yaml(path: Path) -> None:
    """Frontmatter must parse under strict YAML and carry a non-empty ``description``.

    ``safe_load`` raises on an unquoted ``: `` scalar, so a malformed description fails here even
    though Claude Code's lenient parser would tolerate it.
    """
    fm = _frontmatter(path)
    assert fm.get("description"), f"{_ids(path)} frontmatter missing a description"


@pytest.mark.parametrize(
    "path", [p for p in _component_files() if p.name == "SKILL.md"], ids=_ids
)
def test_skill_description_within_limit(path: Path) -> None:
    """A skill ``description`` must stay within the 1024-char cap to avoid truncation on load."""
    desc = _frontmatter(path)["description"]
    assert len(desc) <= DESCRIPTION_LIMIT, (
        f"{_ids(path)} description is {len(desc)} chars (limit {DESCRIPTION_LIMIT})"
    )


def test_claude_md_lists_exactly_the_slash_only_skills() -> None:
    """The routing section in ``templates/CLAUDE.md`` names every ``disable-model-invocation`` skill.

    Such a skill never surfaces on its own -- the picker will not volunteer it -- so if the routing
    section does not name it, nothing will, and the work silently gets done some other way. That
    makes the list load-bearing rather than decorative, in both directions: a skill that gains the
    flag and is missing from the list goes quietly unreachable, and one that loses the flag but
    stays listed is described by a rationale that no longer applies to it.

    Not a prohibition, and the distinction matters: a routing wave measured these skills being
    invoked by name in 13 of 14 runs once the section named them (F-103). The flag suppresses
    volunteering, not invocation.
    """
    declared = {
        p.parent.name
        for p in (REPO_ROOT / "skills").glob("*/SKILL.md")
        if _frontmatter(p).get("disable-model-invocation") is True
    }
    text = (REPO_ROOT / "templates" / "CLAUDE.md").read_text(encoding="utf-8")
    section = text.split("## Skill routing", 1)
    assert len(section) == 2, "templates/CLAUDE.md has no '## Skill routing' section"
    body = section[1].split("\n## ", 1)[0]
    # The section names several DIFFERENT populations -- substitution pairs, silent skills, and
    # the slash-only set. Scan only the slash-only paragraph, or a name from any other group reads
    # as a claim that it is slash-only too.
    marker = "**Why these particular skills need naming.**"
    _, sep, tail = body.partition(marker)
    assert sep, (
        f"the routing section lost its {marker!r} paragraph; this test parses on it"
    )
    para = tail.split("\n\n", 1)[0]
    listed = set(re.findall(r"`([a-z0-9][a-z0-9-]*)`", para))

    missing = sorted(declared - listed)
    assert not missing, (
        f"slash-only skills absent from the CLAUDE.md routing list: {missing}. "
        "They will read as model-selectable."
    )
    stale = sorted(
        n
        for n in listed - declared
        if (REPO_ROOT / "skills" / n / "SKILL.md").is_file()
    )
    assert not stale, (
        f"listed as slash-only but model-selectable: {stale}. "
        "Remove them from the list or restore the frontmatter flag."
    )
