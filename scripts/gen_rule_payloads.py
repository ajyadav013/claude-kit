#!/usr/bin/env python3
"""Generate Claude-compatible rule files from provider-neutral canonical rules.

Write mode is the default. ``--check`` renders in memory and fails for missing,
stale, or unmanaged files so canonical rule bodies remain the sole editable source.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from claude_kit.canonical_rules import (  # noqa: E402
    CanonicalRule,
    discover_canonical_rules,
)

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
_PATH_GLOBS = {
    "@agents/": ".claude/agents/",
    "@skills/": ".claude/skills/",
    "@memory/": ".claude/agent-memory/",
    "@runtime/": ".claude/",
}
_PROVIDER_PLACEHOLDERS = {
    "{{ provider.path.config_root }}": ".claude/",
    "{{ provider.path.continuity }}": ".claude/CONTINUITY.md",
    "{{ provider.path.memory }}": ".claude/agent-memory/",
    "{{ provider.path.artifacts }}": ".claude/artifacts/",
    "{{ provider.path.state }}": ".claude/state/",
    "{{ provider.path.project_instructions }}": "CLAUDE.md",
    "{{ provider.executable.cli }}": "claude-kit",
    "{{ provider.model.field }}": "model",
    "{{ provider.model.fast }}": "haiku",
    "{{ provider.model.balanced }}": "sonnet",
    "{{ provider.model.deep }}": "opus",
    "{{ provider.tool.user_input }}": "AskUserQuestion",
    "{{ provider.tool.message }}": "SendMessage",
    "{{ provider.tool.task_create }}": "TaskCreate",
    "{{ provider.tool.task_get }}": "TaskGet",
    "{{ provider.tool.task_list }}": "TaskList",
    "{{ provider.tool.task_update }}": "TaskUpdate",
    "{{ provider.tool.delegate }}": "Agent",
    "{{ provider.tool.read }}": "Read",
    "{{ provider.tool.write }}": "Write",
    "{{ provider.tool.edit }}": "Edit",
    "{{ provider.tool.search_files }}": "Glob",
    "{{ provider.tool.search_text }}": "Grep",
    "{{ provider.tool.shell }}": "Bash",
}


def _reference_target(kind: str, component_id: str) -> str:
    if kind == "agent":
        return f".claude/agents/{component_id}.md"
    if kind == "skill":
        return f".claude/skills/{component_id}/SKILL.md"
    if kind == "rule":
        return f".claude/rules/{component_id}.md"
    if kind == "command":
        if component_id == "sdlc":
            return "/sdlc"
        return f"/claude-kit:{component_id}"
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
            "agents-directory": ".claude/agents",
            "skills-directory": ".claude/skills",
            "rules-directory": ".claude/rules",
            "org-packs": ".claude/org-packs",
            "sdlc-readme": ".claude/README.claude-sdlc.md",
        }.get(component_id, component_id)
    return f"{kind}://{component_id}"


def project_claude_references(text: str) -> str:
    """Resolve symbolic references and explicit adapter placeholders for Claude."""
    kinds = "|".join(_REFERENCE_KINDS)
    projected = re.sub(
        rf"\b({kinds})://([a-z0-9][a-z0-9._-]*)",
        lambda match: _reference_target(match.group(1), match.group(2)),
        text,
    )
    for placeholder, value in _PROVIDER_PLACEHOLDERS.items():
        projected = projected.replace(placeholder, value)
    return projected


def _project_glob(path_glob: str) -> str:
    for prefix, replacement in _PATH_GLOBS.items():
        if path_glob.startswith(prefix):
            return replacement + path_glob[len(prefix) :]
    return path_glob


def render_claude_rule(record: CanonicalRule) -> str:
    """Render one canonical rule in the root plugin's native Markdown format."""
    prefix = ""
    if record.spec.path_globs:
        metadata = {"paths": [_project_glob(value) for value in record.spec.path_globs]}
        frontmatter = yaml.safe_dump(
            metadata, sort_keys=False, allow_unicode=True, width=10_000
        ).rstrip()
        prefix = f"---\n{frontmatter}\n---\n\n"
    return prefix + project_claude_references(record.spec.content).strip() + "\n"


def generated_rules(root: Path = ROOT) -> dict[Path, str]:
    """Return all compatibility destinations and deterministic rendered bytes."""
    return {
        root / record.destination: render_claude_rule(record)
        for record in discover_canonical_rules(root)
    }


def _existing_rule_paths(root: Path) -> set[Path]:
    paths = set((root / "rules").glob("*.md"))
    paths.update((root / "templates" / "org" / "rules").glob("*.md"))
    paths.update((root / "templates" / "stacks").glob("**/rules/*.md"))
    return {path for path in paths if path.is_file()}


def check(root: Path = ROOT) -> list[str]:
    """Return drift diagnostics; an empty list means generated rules are current."""
    expected = generated_rules(root)
    diagnostics: list[str] = []
    for path, content in expected.items():
        relative = path.relative_to(root).as_posix()
        if not path.is_file():
            diagnostics.append(f"missing generated rule: {relative}")
        elif path.read_text(encoding="utf-8") != content:
            diagnostics.append(f"stale generated rule: {relative}")
    for path in sorted(_existing_rule_paths(root) - set(expected)):
        diagnostics.append(
            f"unmanaged rule outside canonical source: {path.relative_to(root).as_posix()}"
        )
    return diagnostics


def write(root: Path = ROOT) -> int:
    """Write compatibility files, refusing to remove unmanaged rule files."""
    expected = generated_rules(root)
    unmanaged = sorted(_existing_rule_paths(root) - set(expected))
    if unmanaged:
        for path in unmanaged:
            print(
                "refusing to overwrite rule surface with unmanaged file: "
                + path.relative_to(root).as_posix(),
                file=sys.stderr,
            )
        return 1
    changed = 0
    for path, content in expected.items():
        if path.is_file() and path.read_text(encoding="utf-8") == content:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        changed += 1
        print(f"generated {path.relative_to(root).as_posix()}")
    print(f"rule payloads current ({len(expected)} files, {changed} changed)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if compatibility rules differ from canonical sources",
    )
    args = parser.parse_args(argv)
    if args.check:
        diagnostics = check()
        if diagnostics:
            for diagnostic in diagnostics:
                print(diagnostic, file=sys.stderr)
            return 1
        print("rule payloads are current")
        return 0
    return write()


if __name__ == "__main__":
    raise SystemExit(main())
