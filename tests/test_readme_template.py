"""The scaffolded README advertises only slash commands that exist (round-3 item 7).

Claude Code silently treats an unknown ``/name`` as plain prose — no error, no skill guardrails —
so a phantom command in ``README.claude-sdlc.md`` trains muscle memory that does nothing. These
tests render the template exactly the way ``init`` does (per scope) and assert every advertised
``/command`` resolves to a real payload skill/command, that org-only playbooks never leak into a
non-organization render, and that the org-pack governance pointer only appears when the packs
directory is actually installed.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests._helpers import install

#: A slash command as the template writes them: start-of-line (the examples code block) or
#: preceded by whitespace/backtick/paren (prose, table cells). Path segments like
#: ``.claude/rules/`` never match — their ``/`` follows a word character.
_TOKEN = re.compile(r"(?:^|[\s`(])/([a-z][a-z0-9-]*)", re.M)


def _advertised(target: Path) -> set[str]:
    text = (target / "README.claude-sdlc.md").read_text(encoding="utf-8")
    return set(_TOKEN.findall(text))


def _core_names(payload: Path) -> set[str]:
    skills = {p.name for p in (payload / "skills").iterdir() if p.is_dir()}
    commands = {p.stem for p in (payload / "commands").glob("*.md")}
    return skills | commands


def _org_skill_names(payload: Path) -> set[str]:
    return {
        p.name
        for p in (payload / "templates" / "org" / "skills").iterdir()
        if p.is_dir()
    }


def test_team_scope_readme_has_no_phantom_commands(tmp_path, payload):
    """Every /command in a default (team-scope) render exists in skills/ or commands/."""
    install(payload, tmp_path)
    advertised = _advertised(tmp_path)
    assert advertised, "token regex matched nothing — extraction is broken"
    phantoms = advertised - _core_names(payload)
    assert not phantoms, (
        f"README advertises commands with no payload skill: {sorted(phantoms)}"
    )
    # The org-only playbooks are real skills but NOT installed at this scope — advertising
    # them here is the same defect as a phantom.
    leaked = advertised & _org_skill_names(payload)
    assert not leaked, f"org-only skills leaked into a non-org README: {sorted(leaked)}"


def test_org_scope_readme_commands_all_resolve(tmp_path, payload):
    install(payload, tmp_path, scope="organization", teams=["engineering"])
    advertised = _advertised(tmp_path)
    allowed = _core_names(payload) | _org_skill_names(payload)
    phantoms = advertised - allowed
    assert not phantoms, (
        f"README advertises commands with no payload skill: {sorted(phantoms)}"
    )
    # The non-engineer playbooks ARE part of the org pitch — make sure the gate shows them here.
    assert "feature-from-idea" in advertised
    text = (tmp_path / "README.claude-sdlc.md").read_text(encoding="utf-8")
    assert ".claude/org-packs/README.md" in text
    assert (tmp_path / ".claude" / "org-packs" / "README.md").is_file()


def test_org_scope_without_packs_drops_the_governance_pointer(tmp_path, payload):
    """Declining packs at init must not leave the README pointing at a file that isn't there."""
    install(
        payload, tmp_path, scope="organization", teams=["engineering"], org_packs=False
    )
    text = (tmp_path / "README.claude-sdlc.md").read_text(encoding="utf-8")
    assert ".claude/org-packs/README.md" not in text
    assert not (tmp_path / ".claude" / "org-packs").exists()


def test_readme_privacy_reflects_capture_off_default(tmp_path, payload):
    """The scaffolded README states THIS install's capture state — a default install says OFF
    (the generic 'on by default' claim was the 0.76.0 truth-in-advertising defect)."""
    install(payload, tmp_path)
    text = (tmp_path / "README.claude-sdlc.md").read_text(encoding="utf-8")
    assert "Learning capture is **OFF for this install**" in text
    assert "ON for this install" not in text
    assert "{%" not in text and "{{" not in text  # no unrendered Jinja leaked


def test_readme_privacy_reflects_enabled_capture(tmp_path, payload):
    """An install that chose a mode gets the ON wording, the mode, and the audit pointer."""
    install(payload, tmp_path, capture_mode="session-end-catchup")
    text = (tmp_path / "README.claude-sdlc.md").read_text(encoding="utf-8")
    assert "Learning capture is **ON for this install**" in text
    assert "session-end-catchup" in text
    assert "privacy-report" in text
