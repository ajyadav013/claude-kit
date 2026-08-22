#!/usr/bin/env python3
"""Generate Claude compatibility text templates from canonical neutral sources."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from claude_kit.canonical_templates import (  # noqa: E402
    TEXT_TEMPLATE_INVENTORY,
    CanonicalTemplate,
    discover_canonical_templates,
)

_PROVIDER = {
    "provider.path.config_root": ".claude/",
    "provider.path.rules": ".claude/rules/",
    "provider.path.agents": ".claude/agents/",
    "provider.path.skills": ".claude/skills/",
    "provider.path.hooks": ".claude/hooks/",
    "provider.path.settings": ".claude/settings.json",
    "provider.path.settings_local": ".claude/settings.local.json",
    "provider.path.continuity": ".claude/CONTINUITY.md",
    "provider.path.memory": ".claude/agent-memory/",
    "provider.path.artifacts": ".claude/artifacts/",
    "provider.path.state": ".claude/state/",
    "provider.path.project_instructions": "CLAUDE.md",
    "provider.path.sdlc_readme": "README.claude-sdlc.md",
    "provider.path.mcp_config": ".mcp.json",
    "provider.path.user_config": "~/.claude/",
    "provider.path.loop_script": ".claude/scripts/sdlc-loop.sh",
    "provider.executable.cli": "claude-kit",
    "provider.executable.cli_legacy": "claude-sdlc",
    "provider.name.host": "Claude Code",
    "provider.name.agent": "Claude",
    "provider.environment.kit_prefix": "CKIT",
}
_REFERENCE_KINDS = (
    "agent",
    "skill",
    "rule",
    "command",
    "hook",
    "workflow",
    "stage",
    "handler",
    "gate",
    "state",
    "artifact",
)


def _reference_target(kind: str, component_id: str) -> str:
    if kind == "agent":
        return f".claude/agents/{component_id}.md"
    if kind == "skill":
        return f".claude/skills/{component_id}/SKILL.md"
    if kind == "rule":
        return f".claude/rules/{component_id}.md"
    if kind == "command":
        if component_id in {"init", "status", "abort"}:
            return f"/claude-kit:{component_id}"
        return f"/{component_id}"
    if kind == "state":
        return {
            "continuity": ".claude/CONTINUITY.md",
            "agent-memory": ".claude/agent-memory",
            "workflow": ".claude/state",
            "artifacts": ".claude/artifacts",
            "configuration": ".claude/config",
        }.get(component_id, f".claude/state/{component_id}")
    if kind == "artifact":
        return {
            "project-instructions": "CLAUDE.md",
            "templates": ".claude/templates",
            "org-packs": ".claude/org-packs",
            "sdlc-readme": "README.claude-sdlc.md",
        }.get(component_id, component_id)
    return f"{kind}://{component_id}"


def render_claude_template(record: CanonicalTemplate) -> str:
    """Project one canonical body to the existing Claude install contract."""
    kinds = "|".join(_REFERENCE_KINDS)
    rendered = re.sub(
        r"\{\{skill_invocation:skill://([a-z0-9][a-z0-9._-]*)\}\}",
        lambda match: f"/{match.group(1)}",
        record.content,
    )
    rendered = re.sub(
        rf"\b({kinds})://([a-z0-9][a-z0-9._-]*)",
        lambda match: _reference_target(match.group(1), match.group(2)),
        rendered,
    )
    for name, value in _PROVIDER.items():
        rendered = re.sub(r"\{\{\s*" + re.escape(name) + r"\s*\}\}", value, rendered)
    return rendered


def generated_templates(root: Path = ROOT) -> dict[Path, str]:
    return {
        root / record.destination: render_claude_template(record)
        for record in discover_canonical_templates(root)
    }


def check(root: Path = ROOT) -> list[str]:
    expected = generated_templates(root)
    diagnostics: list[str] = []
    for path, content in expected.items():
        relative = path.relative_to(root).as_posix()
        if not path.is_file():
            diagnostics.append(f"missing generated text template: {relative}")
        elif path.read_text(encoding="utf-8") != content:
            diagnostics.append(f"stale generated text template: {relative}")
    expected_destinations = {path.relative_to(root).as_posix() for path in expected}
    for relative in sorted(TEXT_TEMPLATE_INVENTORY - expected_destinations):
        diagnostics.append(f"unmanaged text template inventory entry: {relative}")
    return diagnostics


def write(root: Path = ROOT) -> int:
    expected = generated_templates(root)
    changed = 0
    for path, content in expected.items():
        if path.is_file() and path.read_text(encoding="utf-8") == content:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        changed += 1
        print(f"generated {path.relative_to(root).as_posix()}")
    print(f"text templates current ({len(expected)} files, {changed} changed)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if args.check:
        diagnostics = check()
        if diagnostics:
            for diagnostic in diagnostics:
                print(diagnostic, file=sys.stderr)
            return 1
        print("text template payloads are current")
        return 0
    return write()


if __name__ == "__main__":
    raise SystemExit(main())
