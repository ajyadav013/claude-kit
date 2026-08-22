#!/usr/bin/env python3
"""Generate all compatibility payloads from provider-neutral canonical sources.

Write mode is the default. ``--check`` composes the agent, skill/command, rule,
and text-template drift checks without changing their standalone generator APIs.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from claude_kit.canonical_agents import (  # noqa: E402
    CanonicalAgent,
    discover_canonical_agents,
)
from claude_kit.components import (  # noqa: E402
    Capability,
    IsolationRequirement,
)
from claude_kit.provider_compatibility import (  # noqa: E402
    AgentProjectionCompatibility,
    load_agent_projection_compatibility,
)
from scripts.gen_canonical_skill_payloads import (  # noqa: E402
    check as check_skills,
)
from scripts.gen_canonical_skill_payloads import (  # noqa: E402
    write as write_skills,
)
from scripts.gen_rule_payloads import (  # noqa: E402
    check as check_rules,
)
from scripts.gen_rule_payloads import (  # noqa: E402
    write as write_rules,
)
from scripts.gen_template_payloads import (  # noqa: E402
    check as check_templates,
)
from scripts.gen_template_payloads import (  # noqa: E402
    write as write_templates,
)

_COLOR = {
    "orchestrator": "indigo",
    "stage-lead": "purple",
    "review": "red",
    "specialist": "teal",
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


def _claude_tools(record: CanonicalAgent) -> str:
    capabilities = record.spec.capabilities
    tools: list[str] = []
    if Capability.DELEGATE in capabilities:
        tools.append("Agent")
    if Capability.FILE_READ in capabilities:
        tools.append("Read")
    if Capability.FILE_WRITE in capabilities:
        tools.extend(("Write", "Edit"))
    if Capability.SEARCH in capabilities:
        tools.extend(("Glob", "Grep"))
    if Capability.SHELL in capabilities:
        tools.append("Bash")
    if Capability.TASK_LEDGER in capabilities:
        tools.extend(("TaskCreate", "TaskGet", "TaskList", "TaskUpdate"))
    if Capability.MESSAGE in capabilities:
        tools.append("SendMessage")
    if Capability.USER_INPUT in capabilities:
        tools.append("AskUserQuestion")
    if Capability.BROWSER in capabilities:
        tools.append("mcp__chrome-devtools")
    return ", ".join(dict.fromkeys(tools))


def _reference_target(kind: str, component_id: str) -> str:
    if kind == "agent":
        return f".claude/agents/{component_id}.md"
    if kind == "skill":
        return f".claude/skills/{component_id}/SKILL.md"
    if kind == "rule":
        return f".claude/rules/{component_id}.md"
    if kind == "command":
        return f"/{component_id}"
    if kind == "state":
        return {
            "continuity": ".claude/CONTINUITY.md",
            "agent-memory": ".claude/agent-memory/",
            "workflow": ".claude/state/",
            "artifacts": ".claude/artifacts/",
            "configuration": ".claude/config/",
        }.get(component_id, f".claude/state/{component_id}")
    if kind == "artifact":
        return {
            "project-instructions": "CLAUDE.md",
            "templates": ".claude/templates/",
            "browser-service": "the configured Chrome DevTools service",
        }.get(component_id, component_id)
    return f"{kind}://{component_id}"


def _project_references(text: str) -> str:
    import re

    kinds = "|".join(_REFERENCE_KINDS)
    return re.sub(
        rf"\b({kinds})://([a-z0-9][a-z0-9._-]*)",
        lambda match: _reference_target(match.group(1), match.group(2)),
        text,
    )


def _semantic_contract(record: CanonicalAgent) -> str:
    """Render machine-readable provider-neutral controls into the agent body.

    Claude's native frontmatter necessarily projects some neutral values (for
    example both preferred and required isolation become ``worktree``).  Keep
    the lossless contract beside the native controls so the managed dispatcher
    can fail closed instead of inferring stronger or weaker semantics from a
    provider-specific approximation.
    """
    spec = record.spec
    capabilities = (
        ", ".join(
            capability.value
            for capability in sorted(spec.capabilities, key=lambda item: item.value)
        )
        or "none"
    )
    write_scope = ", ".join(f"`{scope}`" for scope in spec.write_scope) or "none"
    required_skills = (
        ", ".join(reference.uri for reference in spec.required_skills) or "none"
    )
    return (
        "## Semantic role contract\n\n"
        f"- Permission class: `{spec.permission.value}`\n"
        f"- Capabilities: {capabilities}\n"
        f"- Write scope: {write_scope}\n"
        f"- Isolation: `{spec.isolation.value}`\n"
        f"- Nested delegation: `{spec.nested_delegation.value}`\n"
        f"- Model tier: `{spec.model_tier.value}`\n"
        f"- Required skills: {required_skills}\n"
        f"- Workflow tier: `{record.workflow_tier.value}`\n\n"
    )


def render_claude_agent(
    record: CanonicalAgent,
    compatibility: AgentProjectionCompatibility | None = None,
) -> str:
    """Render one canonical definition as a valid root plugin agent."""
    compatibility = compatibility or load_agent_projection_compatibility(ROOT, "claude")
    model = compatibility.model_tiers[record.spec.model_tier]
    if model is None:  # Rejected by the Claude schema; keep this lookup fail closed.
        raise ValueError(
            f"Claude model mapping for {record.spec.model_tier.value} cannot inherit"
        )
    metadata = {
        "name": record.spec.id,
        "description": record.spec.description,
        "tools": _claude_tools(record),
        "permissionMode": compatibility.permission_classes[record.spec.permission],
        "model": model,
        "color": _COLOR[record.workflow_tier.value],
        "tier": record.workflow_tier.value,
    }
    if record.spec.isolation in {
        IsolationRequirement.PREFERRED,
        IsolationRequirement.REQUIRED,
        IsolationRequirement.NATIVE,
    }:
        # Claude Code supports native worktree isolation in agent frontmatter.
        # A preferred canonical isolation request is selected whenever that
        # native surface exists; REQUIRED/NATIVE must never be silently lost.
        metadata["isolation"] = "worktree"
    frontmatter = yaml.safe_dump(
        metadata,
        sort_keys=False,
        allow_unicode=True,
        width=10_000,
    ).rstrip()
    body = _project_references(
        _semantic_contract(record) + record.spec.instructions
    ).strip()
    return f"---\n{frontmatter}\n---\n\n{body}\n"


def generated_agents(root: Path = ROOT) -> dict[Path, str]:
    """Return every generated agent destination and deterministic content."""
    compatibility = load_agent_projection_compatibility(root, "claude")
    return {
        root / record.destination: render_claude_agent(record, compatibility)
        for record in discover_canonical_agents(root)
    }


def _existing_agent_paths(root: Path) -> set[Path]:
    paths = set((root / "agents").glob("*.md"))
    paths.update((root / "templates" / "org" / "agents").glob("*.md"))
    paths.update((root / "templates" / "stacks").glob("**/agents/*.md"))
    return {path for path in paths if path.is_file()}


def check_agents(root: Path = ROOT) -> list[str]:
    """Return agent-only drift diagnostics for focused callers."""
    expected = generated_agents(root)
    diagnostics: list[str] = []
    for path, content in expected.items():
        relative = path.relative_to(root).as_posix()
        if not path.is_file():
            diagnostics.append(f"missing generated agent: {relative}")
        elif path.read_text(encoding="utf-8") != content:
            diagnostics.append(f"stale generated agent: {relative}")
    for path in sorted(_existing_agent_paths(root) - set(expected)):
        diagnostics.append(
            f"unmanaged agent outside canonical source: {path.relative_to(root).as_posix()}"
        )
    return diagnostics


def check(root: Path = ROOT) -> list[str]:
    """Return combined agent/skill/command/rule/template drift diagnostics."""
    return (
        check_agents(root)
        + check_skills(root)
        + check_rules(root)
        + check_templates(root)
    )


def write_agents(root: Path = ROOT) -> int:
    """Write generated agents, refusing to delete unmanaged agent files."""
    expected = generated_agents(root)
    unmanaged = sorted(_existing_agent_paths(root) - set(expected))
    if unmanaged:
        for path in unmanaged:
            print(
                "refusing to overwrite agent surface with unmanaged file: "
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
    print(f"agent payloads current ({len(expected)} files, {changed} changed)")
    return 0


def write(root: Path = ROOT) -> int:
    """Write every canonical compatibility surface in deterministic lane order."""
    for writer in (write_agents, write_skills, write_rules, write_templates):
        result = writer(root)
        if result:
            return result
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if any generated compatibility payload differs from canonical sources",
    )
    args = parser.parse_args(argv)
    if args.check:
        diagnostics = check()
        if diagnostics:
            for diagnostic in diagnostics:
                print(diagnostic, file=sys.stderr)
            return 1
        print("provider payloads are current")
        return 0
    return write()


if __name__ == "__main__":
    raise SystemExit(main())
