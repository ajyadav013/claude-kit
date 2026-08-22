#!/usr/bin/env python3
"""Generate skill and command compatibility payloads from canonical sources.

Normal write mode reads only ``canonical/skills`` and ``canonical/commands``.
``--check`` renders in memory and reports drift or unmanaged payload files.
The one-time ``--bootstrap-from-legacy`` mode is explicit and refuses to run
once canonical skill/command sources exist; this prevents generated provider
output from accidentally becoming the source of truth later.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Mapping

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

CODEX_PLUGIN_ROOT = Path("providers/codex/claude-kit")

from claude_kit.canonical_skills import (  # noqa: E402
    CanonicalCommand,
    CanonicalSkill,
    CanonicalSkillAsset,
    RequestMode,
    discover_canonical_commands,
    discover_canonical_skill_assets,
    discover_canonical_skills,
    project_codex_inline_tokens,
    project_codex_skill,
    project_codex_skill_asset,
)
from claude_kit.components import Capability, InvocationMode  # noqa: E402

_REFERENCE_RE = re.compile(
    r"\b(?:agent|skill|rule|command|hook|workflow|stage|handler|gate|state|artifact)"
    r"://[a-z0-9][a-z0-9._-]*"
)

# Literals about an external integration are not portable host settings and
# must not be silently remapped to a different model or CLI.  Canonical source
# names their semantic role; both projections retain the documented literal.
_EXTERNAL_LITERALS = {
    "external-model-current-balanced": "claude-sonnet-4-6",
    "external-model-versioned-balanced": "claude-sonnet-4@20250514",
    "external-model-legacy-balanced": "claude-3-5-sonnet-v2@20241022",
    "external-model-legacy-fast": "claude-3-5-haiku@20241022",
    "external-model-family-balanced": "claude-sonnet-4",
    "external-model-multimodal": "gpt-4o",
    "external-model-env-balanced": "CLAUDE_SONNET_MODEL",
    "external-model-env-deep": "CLAUDE_OPUS_MODEL",
    "external-plugin-collection": "claude-plugins-official",
    "external-skill-collection": "claude-night-market",
    "external-status-extension": "claude-hud",
    "external-shannon-cli-max-output-tokens": "CLAUDE_CODE_MAX_OUTPUT_TOKENS",
    "external-shannon-cli-use-bedrock": "CLAUDE_CODE_USE_BEDROCK",
    "external-shannon-cli-use-vertex": "CLAUDE_CODE_USE_VERTEX",
    "external-shannon-cli-adaptive-thinking": "CLAUDE_ADAPTIVE_THINKING",
}

_CLAUDE_ORCHESTRATION_APPENDIX = """## Claude Code host appendix

### Where personas live

Plugin subagents live in `agents/` at the plugin root. This repository's
`.claude-plugin/plugin.json` manifest makes `agents/code-reviewer.md`,
`agents/security-auditor.md`, and `agents/test-engineer.md` discoverable when
the plugin is enabled; no extra path configuration is required.

### Subagents versus Agent Teams

Claude Code exposes two parallelism primitives. Use subagents for independent
fan-out whose results return to the main session. Use Agent Teams only when
workers must message one another or coordinate through a shared task list.

| | Subagents | Agent Teams |
|--|-----------|-------------|
| Coordination | Main session fans out; workers report back | Teammates message one another and share a task list |
| Context | One context per subagent | One context per teammate |
| Best fit | Independent reports with one merge | Collaborative investigation or adversarial debate |
| Status | Stable | Experimental; requires `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` |
| Cost | Lower | Higher; every teammate is a separate model instance |

The same persona definitions work in both modes. When used as subagents they
report to the main session. When used as teammates their persona instructions
are appended to the team-coordination prompt and they can challenge one
another directly.

The `skills` and `mcpServers` persona-frontmatter fields apply to subagents but
are ignored for teammates. Teammates inherit project and user session settings.
If a persona requires a skill or MCP server in both modes, configure it at the
session level.

### Platform-enforced nesting rules

- Subagents cannot spawn other subagents.
- Teammates cannot create nested teams.

These restrictions enforce the no-persona-trees rule. Keep the main session as
the orchestration owner instead of trying to work around them.

### Built-in subagents

Check the built-ins before defining a custom research persona:

| Built-in | Purpose |
|----------|---------|
| `Explore` | Read-only codebase search and analysis for research isolation |
| `Plan` | Read-only research during plan mode |
| `general-purpose` | Multi-step work that needs exploration and modification |

Do not redefine them. Add specialist personas such as `code-reviewer`,
`security-auditor`, and `test-engineer` alongside them.

### Plugin-agent frontmatter

Plugin subagents do not honor `hooks`, `mcpServers`, or `permissionMode`; those
fields are silently ignored. A persona that truly needs those fields must be
copied into `.claude/agents/` or `~/.claude/agents/` and treated as user- or
project-owned configuration.

Supported plugin-agent fields include `name`, `description`, `tools`,
`disallowedTools`, `model`, `maxTurns`, `skills`, `memory`, `background`,
`effort`, `isolation`, `color`, and `initialPrompt`. Choose an explicit model
only when the persona's cost or reasoning needs justify it; for example, Haiku
can fit a bounded coverage scan, Sonnet a routine review, and Opus a deep
security analysis.

### Parallel dispatch

Parallel fan-out requires multiple Agent tool calls in one assistant turn.
Putting the calls in sequential turns serializes the workers. Require one
explicit merge after all workers return.

### Competing-hypothesis debugging with Agent Teams

Use Agent Teams when several plausible causes fit an intermittent failure and
workers must actively disprove one another. For example, one teammate can
investigate races and blocking calls, a second authentication and synchronous
network boundaries, and a third tests that distinguish the hypotheses. Ask
them to message counter-evidence directly and converge only when at least two
can rule out the alternatives.

This is different from a ship review. A ship review needs independent lenses
and one verdict; competing-hypothesis debugging needs discussion among the
investigators. Agent Teams therefore earns its higher cost only when the
cross-worker debate materially improves the conclusion.

Agent Teams requires Claude Code v2.1.32 or later and this one-time setting:

```json
{
  "env": {
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"
  }
}
```

When the investigation finishes, tell the lead to clean up the team. Teammates
lack the lead's complete team context and must not own cleanup.

---
"""
_EXTERNAL_ASSISTANT_SKILLS = {
    "anthropic-vertex-integration",
    "code-simplification",
    "design-system-ops",
    "langfuse-llm-tracing",
    "shannon-ai-pentest",
    "strix-ai-pentest",
}

_CLAUDE_TOOL = {
    "file_read": "Read",
    "file_write": "Write",
    "file_edit": "Edit",
    "file_glob": "Glob",
    "file_search": "Grep",
    "shell": "Bash",
    "delegate": "Agent",
    "skill": "Skill",
    "task_create": "TaskCreate",
    "task_get": "TaskGet",
    "task_list": "TaskList",
    "task_update": "TaskUpdate",
    "message": "SendMessage",
}
_CODEX_TOOL = {
    "file_read": "file reading",
    "file_write": "file creation",
    "file_edit": "file editing",
    "file_glob": "file discovery",
    "file_search": "text search",
    "shell": "shell execution",
    "delegate": "delegation",
    "skill": "skill invocation",
    "task_create": "task-ledger creation",
    "task_get": "task-ledger lookup",
    "task_list": "task-ledger listing",
    "task_update": "task-ledger update",
    "message": "worker messaging",
}

_CAPABILITY_ORDER = tuple(Capability)
_TOOL_CAPABILITIES = {
    "Bash": {Capability.SHELL},
    "Read": {Capability.FILE_READ},
    "Write": {Capability.FILE_WRITE},
    "Edit": {Capability.FILE_WRITE},
    "Glob": {Capability.SEARCH},
    "Grep": {Capability.SEARCH},
    "Agent": {Capability.DELEGATE},
    "Skill": set(),
    "TaskCreate": {Capability.TASK_LEDGER},
    "TaskGet": {Capability.TASK_LEDGER},
    "TaskList": {Capability.TASK_LEDGER},
    "TaskUpdate": {Capability.TASK_LEDGER},
    "SendMessage": {Capability.MESSAGE},
    "AskUserQuestion": {Capability.USER_INPUT},
}


def _split_frontmatter_text(text: str, *, label: str) -> tuple[dict[str, Any], str]:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise ValueError(f"legacy source has no frontmatter: {label}")
    end = next(
        (
            index
            for index, line in enumerate(lines[1:], start=1)
            if line.strip() == "---"
        ),
        None,
    )
    if end is None:
        raise ValueError(f"legacy source has unterminated frontmatter: {label}")
    frontmatter = "".join(lines[1:end])
    metadata = yaml.safe_load(frontmatter)
    if not isinstance(metadata, dict):
        raise ValueError(f"legacy frontmatter must be an object: {label}")
    hint = re.search(r"^argument-hint:\s*(.*?)\s*$", frontmatter, re.MULTILINE)
    if hint:
        authored = hint.group(1)
        if authored[:1] in {"'", '"'}:
            metadata["argument-hint"] = yaml.safe_load(authored)
        else:
            metadata["argument-hint"] = authored
    body = "".join(lines[end + 1 :]).strip()
    if not body:
        raise ValueError(f"legacy body is empty: {label}")
    return metadata, body + "\n"


def _split_frontmatter(path: Path) -> tuple[dict[str, Any], str]:
    return _split_frontmatter_text(
        path.read_text(encoding="utf-8"), label=path.as_posix()
    )


def _replace_paths(text: str) -> str:
    text = text.replace(".claude-kit", "{{kit:sidecar-suffix}}")
    text = re.sub(
        r"\.claude/skills/_references/([a-z0-9._-]+)\.md",
        lambda match: f"artifact://skill-reference-{match.group(1)}",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"\.claude/rules/([a-z0-9._-]+)\.md",
        lambda match: f"rule://{match.group(1)}",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"\.claude/skills/([a-z0-9._-]+)/SKILL\.md",
        lambda match: f"{{{{skill_file:skill://{match.group(1)}}}}}",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"\.claude/skills/([a-z0-9._-]+)/",
        lambda match: f"{{{{skill_dir:skill://{match.group(1)}}}}}",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"\.claude/skills/([a-z0-9._-]+)(?![a-z0-9._/-])",
        lambda match: f"{{{{skill_path:skill://{match.group(1)}}}}}",
        text,
        flags=re.I,
    )
    fixed = {
        ".claude/CONTINUITY.md": "state://continuity",
        ".claude/agent-memory/MEMORY.md": "state://agent-memory-index",
        ".claude/agent-memory/": "{{state_dir:state://agent-memory}}",
        ".claude/state/pipeline-snapshot.json": "state://pipeline-snapshot",
        ".claude/state/ticket-board.html": "state://ticket-board",
        ".claude/state/": "state://workflow",
        ".claude/config/stack-catalog.snapshot.yaml": "state://stack-catalog",
        ".claude/config/init-options.json": "state://init-options",
        ".claude/config/deploy.yaml": "state://deploy-config",
        ".claude/config/": "state://configuration",
        ".claude/rules/": "artifact://rule-library/",
        ".claude/skills/": "artifact://skill-library/",
        ".claude/templates/change-proposal.md": "artifact://change-proposal-template",
        ".claude/rules/<stack>-patterns.md": "artifact://stack-rule-pattern",
        ".claude/skills/<domain>/SKILL.md": "artifact://skill-domain-example",
        ".claude/skills/<domain>/": "artifact://skill-domain-directory",
        "CLAUDE.md": "{{ref:artifact://project-instructions}}",
        "AGENTS.md": "{{ref:artifact://alternate-project-instructions}}",
        ".mcp.json": "artifact://mcp-configuration",
    }
    for source, replacement in sorted(fixed.items(), key=lambda item: -len(item[0])):
        text = text.replace(source, replacement)
    # Any residual source-host root is still a symbolic reference.  Keeping the
    # suffix preserves examples such as brace-expanded directory lists.
    text = re.sub(r"\.claude\b", "state://root", text, flags=re.I)
    text = re.sub(r"\.codex\b", "state://root", text, flags=re.I)
    text = re.sub(r"\.agents/skills\b", "artifact://skill-library", text, flags=re.I)
    return text


def _neutralize_tools(text: str, *, skill_id: str) -> str:
    if skill_id == "frontend-ui-engineering":
        text = text.replace("TaskList", "{{domain_literal:task-list-component}}")
    text = text.replace("AskUserQuestion", "{{pause_for_human:input}}")
    for source, target in {
        "TaskCreate": "{{tool:task_create}}",
        "TaskGet": "{{tool:task_get}}",
        "TaskList": "{{tool:task_list}}",
        "TaskUpdate": "{{tool:task_update}}",
        "SendMessage": "{{tool:message}}",
    }.items():
        text = text.replace(source, target)
    for source, target in {
        "Agent tool": "{{tool:delegate}} tool",
        "Agent-tool": "{{tool:delegate}}-tool",
        "Skill tool": "{{tool:skill}} tool",
        "Skill-tool": "{{tool:skill}}-tool",
    }.items():
        text = text.replace(source, target)
    for source, token in {
        "Read": "file_read",
        "Write": "file_write",
        "Edit": "file_edit",
        "Glob": "file_glob",
        "Grep": "file_search",
        "Bash": "shell",
        "Agent": "delegate",
        "Skill": "skill",
    }.items():
        text = text.replace(f"`{source}`", f"`{{{{tool:{token}}}}}`")
    text = text.replace("Glob/Grep", "{{tool:file_glob}}/{{tool:file_search}}")
    text = text.replace(
        "Read/Glob/Grep", "{{tool:file_read}}/{{tool:file_glob}}/{{tool:file_search}}"
    )
    text = text.replace(
        "Read, Glob, Grep",
        "{{tool:file_read}}, {{tool:file_glob}}, {{tool:file_search}}",
    )
    text = text.replace("allowed-tools:", "{{provider_metadata:tool-allowlist}}")
    return text


def _neutralize_provider_terms(text: str, *, skill_id: str) -> str:
    for key, literal in sorted(
        _EXTERNAL_LITERALS.items(), key=lambda item: -len(item[1])
    ):
        text = text.replace(literal, f"{{{{external_literal:{key}}}}}")

    # Alternate-runtime review examples remain deliberately explicit in the
    # source-host projection, while the target-runtime projection describes the
    # role without pretending that invoking itself yields independent review.
    alternates = {
        "OpenAI Codex": "{{alternate_runtime:full-title}}",
        "Codex CLI": "{{alternate_runtime:cli-title}}",
        "codex exec": "{{alternate_runtime:exec}}",
        "which codex": "which {{alternate_runtime:binary}}",
        "Codex": "{{alternate_runtime:title}}",
        "codex": "{{alternate_runtime:binary}}",
    }
    for source, replacement in alternates.items():
        text = text.replace(source, replacement)

    text = text.replace("claude-code-kit", "{{kit:distribution}}")
    text = text.replace("claude-sdlc", "{{kit:legacy-cli}}")
    text = re.sub(r"\bclaude-kit\b", "{{kit:cli}}", text, flags=re.I)
    text = re.sub(
        r"\bCLAUDE_KIT_([A-Z0-9_]+)\b",
        lambda match: "{{kit_env:" + match.group(1).lower().replace("_", "-") + "}}",
        text,
    )
    text = re.sub(
        r"\bCLAUDE_([A-Z0-9_]+)\b",
        lambda match: "{{host_env:" + match.group(1).lower().replace("_", "-") + "}}",
        text,
    )

    if skill_id in _EXTERNAL_ASSISTANT_SKILLS:
        text = text.replace("Claude", "{{external_assistant:title}}")
        text = text.replace("claude", "{{external_assistant:lower}}")
        text = text.replace("CLAUDE", "{{external_assistant:upper}}")
    else:
        text = text.replace("Claude Code", "{{host:product}}")
        text = text.replace("Claude", "{{host:title}}")
        text = text.replace("claude", "{{host:lower}}")
        text = text.replace("CLAUDE", "{{host:upper}}")

    for value, token in (
        ("Sonnet", "balanced-title"),
        ("sonnet", "balanced"),
        ("Opus", "deep-title"),
        ("opus", "deep"),
        ("Haiku", "fast-title"),
        ("haiku", "fast"),
    ):
        text = re.sub(rf"\b{value}\b", f"{{{{model_tier:{token}}}}}", text)
    return text


def neutralize(text: str, *, skill_id: str) -> str:
    """Translate legacy host syntax into reversible semantic markers."""
    text = _replace_paths(text)
    text = text.replace("$ARGUMENTS", "{{request}}")
    if skill_id == "remember":
        text = text.replace("`claude` job", "{{capture_worker:job}}")
    if skill_id == "context-engineering":
        text = text.replace(
            "Claude Code's statusline API", "{{host_feature:statusline-api}}"
        )
    if skill_id == "sdlc":
        text = text.replace(
            "Claude Code's native dynamic-workflows engine",
            "{{host_feature:dynamic-workflows}}",
        )
    if skill_id == "doubt-driven-development":
        text = text.replace(
            "Claude Code prevents nested subagent spawn",
            "{{host_constraint:nested-delegation}}",
        )
    text = re.sub(
        r"/claude-kit:([a-z0-9._-]+)",
        lambda match: "{{command_alias:command://" + match.group(1) + "}}",
        text,
    )
    text = re.sub(
        r"(?<![\w/])/(sdlc)\b",
        lambda match: "{{short_command:command://" + match.group(1) + "}}",
        text,
    )
    text = _neutralize_tools(text, skill_id=skill_id)
    text = _neutralize_provider_terms(text, skill_id=skill_id)
    text = text.replace(
        "--approval-mode plan", "{{external_permission:alternate-review-read-only}}"
    )
    return text


def _capabilities(metadata: Mapping[str, Any], body: str) -> list[str]:
    capabilities: set[Capability] = set()
    allowed = metadata.get("allowed-tools", "")
    if isinstance(allowed, str):
        for tool in (item.strip() for item in allowed.split(",")):
            capabilities.update(_TOOL_CAPABILITIES.get(tool, set()))
    for tool, values in _TOOL_CAPABILITIES.items():
        if tool in body:
            capabilities.update(values)
    if "AskUserQuestion" in body:
        capabilities.add(Capability.USER_INPUT)
    return [value.value for value in _CAPABILITY_ORDER if value in capabilities]


def _request(metadata: Mapping[str, Any], body: str) -> dict[str, str]:
    raw_hint = metadata.get("argument-hint")
    if raw_hint is None and "$ARGUMENTS" not in body:
        return {"mode": RequestMode.NONE.value}
    hint = str(raw_hint or "[request]").strip()
    mode = RequestMode.REQUIRED if hint.startswith("<") else RequestMode.OPTIONAL
    return {"mode": mode.value, "hint": neutralize(hint, skill_id="metadata")}


def _canonical_metadata(
    *,
    component_id: str,
    metadata: Mapping[str, Any],
    body: str,
    is_command: bool,
) -> tuple[dict[str, Any], str]:
    description = neutralize(str(metadata["description"]), skill_id=component_id)
    instructions = neutralize(body, skill_id=component_id)
    request = _request(metadata, body)
    pauses = []
    capabilities = _capabilities(metadata, body)
    if "{{pause_for_human:input}}" in instructions:
        pauses.append(
            {
                "id": "input",
                "reason": "Obtain an explicit user choice at the marked interaction points.",
            }
        )
        if Capability.USER_INPUT.value not in capabilities:
            capabilities.append(Capability.USER_INPUT.value)
    references = sorted(set(_REFERENCE_RE.findall(description + "\n" + instructions)))
    canonical: dict[str, Any] = {
        "schema_version": 1,
        "id": component_id,
        "description": description,
    }
    if is_command:
        canonical["aliases"] = [component_id]
        canonical["invocation"] = InvocationMode.EXPLICIT.value
    else:
        canonical["invocation"] = (
            InvocationMode.EXPLICIT.value
            if metadata.get("disable-model-invocation") is True
            else InvocationMode.IMPLICIT.value
        )
    canonical.update(
        {
            "capabilities": capabilities,
            "request_input": request,
            "pause_for_human": pauses,
            "references": references,
        }
    )
    return canonical, instructions


def _dump_canonical(metadata: Mapping[str, Any], body: str) -> str:
    frontmatter = yaml.safe_dump(
        dict(metadata), sort_keys=False, allow_unicode=True, width=10_000
    ).rstrip()
    return f"---\n{frontmatter}\n---\n\n{body.strip()}\n"


def _legacy_commit_paths(root: Path, source_commit: str) -> list[str]:
    if not re.fullmatch(r"[0-9a-f]{7,40}", source_commit):
        raise ValueError(
            "source commit must be a 7-40 character lowercase hex object id"
        )
    result = subprocess.run(  # noqa: S603
        ["git", "ls-tree", "-r", "--name-only", source_commit],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.splitlines()


def _legacy_commit_text(root: Path, source_commit: str, relative: str) -> str:
    result = subprocess.run(  # noqa: S603
        ["git", "show", f"{source_commit}:{relative}"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def bootstrap_from_legacy(
    root: Path = ROOT,
    *,
    source_commit: str | None = None,
    refresh: bool = False,
) -> int:
    """Create canonical sources once from a reviewed legacy inventory."""
    skill_root = root / "canonical" / "skills"
    command_root = root / "canonical" / "commands"
    if (skill_root.exists() or command_root.exists()) and not refresh:
        print(
            "refusing bootstrap: canonical skill/command source already exists",
            file=sys.stderr,
        )
        return 1
    if refresh and source_commit is None:
        print("refusing refresh without an immutable --source-commit", file=sys.stderr)
        return 1
    if source_commit is None:
        core: list[Path | str] = sorted((root / "skills").glob("*/SKILL.md"))
        core = [path for path in core if Path(path).parent.name != "_references"]
        org: list[Path | str] = sorted(
            (root / "templates/org/skills").glob("*/SKILL.md")
        )
        commands: list[Path | str] = sorted((root / "commands").glob("*.md"))
    else:
        inventory = _legacy_commit_paths(root, source_commit)
        core = sorted(
            relative
            for relative in inventory
            if re.fullmatch(r"skills/[^/]+/SKILL\.md", relative)
            and relative != "skills/_references/SKILL.md"
        )
        org = sorted(
            relative
            for relative in inventory
            if re.fullmatch(r"templates/org/skills/[^/]+/SKILL\.md", relative)
        )
        commands = sorted(
            relative
            for relative in inventory
            if re.fullmatch(r"commands/[^/]+\.md", relative)
        )
    if (len(core), len(org), len(commands)) != (121, 9, 4):
        print(
            "refusing bootstrap: expected reviewed legacy inventory 121 core skills, "
            f"9 org skills, 4 commands; found {len(core)}, {len(org)}, {len(commands)}",
            file=sys.stderr,
        )
        return 1

    def read(path: Path | str) -> tuple[dict[str, Any], str]:
        if source_commit is None:
            return _split_frontmatter(Path(path))
        return _split_frontmatter_text(
            _legacy_commit_text(root, source_commit, str(path)),
            label=f"{source_commit}:{path}",
        )

    for kind, paths in (("core", core), ("org", org)):
        for path in paths:
            metadata, body = read(path)
            component_id = str(metadata["name"])
            canonical, instructions = _canonical_metadata(
                component_id=component_id,
                metadata=metadata,
                body=body,
                is_command=False,
            )
            destination = skill_root / kind / f"{component_id}.md"
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(
                _dump_canonical(canonical, instructions), encoding="utf-8"
            )
    for path in commands:
        metadata, body = read(path)
        component_id = Path(path).stem
        canonical, instructions = _canonical_metadata(
            component_id=component_id,
            metadata=metadata,
            body=body,
            is_command=True,
        )
        destination = command_root / f"{component_id}.md"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            _dump_canonical(canonical, instructions), encoding="utf-8"
        )
    source_note = f" from {source_commit}" if source_commit else ""
    print(f"bootstrapped 130 canonical skills and 4 canonical commands{source_note}")
    return 0


def _reference_target(
    kind: str,
    component_id: str,
    *,
    provider: str,
    codex_skill_reference_base: str | None = None,
    codex_plugin_context: bool = False,
) -> str:
    if provider == "claude":
        if kind == "agent":
            return f".claude/agents/{component_id}.md"
        if kind == "skill":
            return f".claude/skills/{component_id}/SKILL.md"
        if kind == "rule":
            return f".claude/rules/{component_id}.md"
        if kind == "command":
            return f"/claude-kit:{component_id}"
        if kind == "state":
            return {
                "root": ".claude",
                "continuity": ".claude/CONTINUITY.md",
                "agent-memory": ".claude/agent-memory/",
                "agent-memory-index": ".claude/agent-memory/MEMORY.md",
                "pipeline-snapshot": ".claude/state/pipeline-snapshot.json",
                "ticket-board": ".claude/state/ticket-board.html",
                "workflow": ".claude/state/",
                "stack-catalog": ".claude/config/stack-catalog.snapshot.yaml",
                "init-options": ".claude/config/init-options.json",
                "deploy-config": ".claude/config/deploy.yaml",
                "configuration": ".claude/config/",
            }.get(component_id, f".claude/state/{component_id}")
        if kind == "artifact":
            return {
                "project-instructions": "CLAUDE.md",
                "alternate-project-instructions": "AGENTS.md",
                "mcp-configuration": ".mcp.json",
                "skill-library": ".claude/skills",
                "rule-library": ".claude/rules",
                "change-proposal-template": ".claude/templates/change-proposal.md",
                "stack-rule-pattern": ".claude/rules/<stack>-patterns.md",
                "skill-domain-example": ".claude/skills/<domain>/SKILL.md",
                "skill-domain-directory": ".claude/skills/<domain>/",
            }.get(
                component_id,
                (
                    f".claude/skills/_references/{component_id.removeprefix('skill-reference-')}.md"
                    if component_id.startswith("skill-reference-")
                    else component_id
                ),
            )
    else:
        if kind == "agent":
            return f".codex/agents/{component_id}.toml"
        if kind == "skill":
            return (
                f"the {component_id} skill"
                if codex_plugin_context
                else f".agents/skills/{component_id}/SKILL.md"
            )
        if kind == "rule":
            return (
                component_id
                if codex_plugin_context
                else f"the installed `{component_id}` engineering rule"
            )
        if kind == "command":
            return f"the `{component_id}` skill"
        if kind == "state":
            return {
                "root": ".ckit",
                "continuity": ".ckit/CONTINUITY.md",
                "agent-memory": ".ckit/agent-memory/",
                "agent-memory-index": ".ckit/agent-memory/MEMORY.md",
                "pipeline-snapshot": ".ckit/state/pipeline-snapshot.json",
                "ticket-board": ".ckit/state/ticket-board.html",
                "workflow": ".ckit/state/",
                "stack-catalog": ".ckit/config/stack-catalog.snapshot.yaml",
                "init-options": ".ckit/config/init-options.json",
                "deploy-config": ".ckit/config/deploy.yaml",
                "configuration": ".ckit/config/",
            }.get(component_id, f".ckit/state/{component_id}")
        if kind == "artifact":
            return {
                "project-instructions": "AGENTS.md",
                "alternate-project-instructions": "CLAUDE.md",
                "mcp-configuration": ".codex/config.toml",
                "skill-library": ".agents/skills",
                "rule-library": (
                    ".ckit/rules"
                    if codex_plugin_context
                    else "the installed engineering-rule library"
                ),
                "change-proposal-template": ".ckit/templates/change-proposal.md",
                "stack-rule-pattern": (
                    ".ckit/rules/<stack>-patterns.md"
                    if codex_plugin_context
                    else "the installed stack-specific engineering rule"
                ),
                "skill-domain-example": ".agents/skills/<domain>/SKILL.md",
                "skill-domain-directory": ".agents/skills/<domain>/",
            }.get(
                component_id,
                (
                    f"{codex_skill_reference_base or '.agents/skills/_references'}/"
                    f"{component_id.removeprefix('skill-reference-')}.md"
                    if component_id.startswith("skill-reference-")
                    else component_id
                ),
            )
    return f"{kind}://{component_id}"


def _project_semantics(
    text: str,
    *,
    provider: str,
    codex_skill_reference_base: str | None = None,
    codex_plugin_context: bool = False,
) -> str:
    def reference(match: re.Match[str]) -> str:
        kind, component_id = match.group(1), match.group(2)
        return _reference_target(
            kind,
            component_id,
            provider=provider,
            codex_skill_reference_base=codex_skill_reference_base,
            codex_plugin_context=codex_plugin_context,
        )

    def project_token(
        source: str,
        pattern: str,
        resolve: Callable[[re.Match[str]], str],
    ) -> str:
        compiled = re.compile(pattern)
        if provider == "codex":
            return project_codex_inline_tokens(source, compiled, resolve)
        return compiled.sub(resolve, source)

    text = text.replace(
        "{{state_dir:state://agent-memory}}",
        ".claude/agent-memory/" if provider == "claude" else ".ckit/agent-memory/",
    )
    text = re.sub(
        r"\{\{skill_asset:skill://([a-z0-9][a-z0-9._-]*)/"
        r"([a-zA-Z0-9][a-zA-Z0-9._/-]*)\}\}",
        lambda match: (
            f".claude/skills/{match.group(1)}/{match.group(2)}"
            if provider == "claude"
            else (
                match.group(2)
                if codex_plugin_context
                else f".agents/skills/{match.group(1)}/{match.group(2)}"
            )
        ),
        text,
    )
    text = project_token(
        text,
        r"\{\{skill_invocation:skill://([a-z0-9][a-z0-9._-]*)\}\}",
        lambda match: (
            f"/{match.group(1)}" if provider == "claude" else f"${match.group(1)}"
        ),
    )
    text = project_token(
        text,
        r"\{\{ref:(agent|skill|rule|command|hook|workflow|stage|handler|gate|state|artifact)"
        r"://([a-z0-9][a-z0-9._-]*)\}\}",
        lambda match: _reference_target(
            match.group(1),
            match.group(2),
            provider=provider,
            codex_skill_reference_base=codex_skill_reference_base,
            codex_plugin_context=codex_plugin_context,
        ),
    )
    for marker in ("command_alias", "short_command"):
        prefix = "/claude-kit:" if marker == "command_alias" else "/"

        def project_command(match: re.Match[str], prefix: str = prefix) -> str:
            if provider == "claude":
                return prefix + match.group(1)
            if codex_plugin_context:
                return f"the {match.group(1)} skill"
            return f"the `{match.group(1)}` skill"

        text = project_token(
            text,
            rf"\{{\{{{marker}:command://([a-z0-9][a-z0-9._-]*)\}}\}}",
            project_command,
        )
    # Wrapper forms preserve whether the legacy prose named a skill file or a
    # directory.  They still contain a declared symbolic skill reference.
    for marker, suffix in (
        ("skill_file", "/SKILL.md"),
        ("skill_dir", "/"),
        ("skill_path", ""),
    ):

        def project_skill(match: re.Match[str], suffix: str = suffix) -> str:
            if provider == "claude":
                return f".claude/skills/{match.group(1)}{suffix}"
            if codex_plugin_context:
                return f"the {match.group(1)} skill"
            return f".agents/skills/{match.group(1)}{suffix}"

        text = project_token(
            text,
            rf"\{{\{{{marker}:skill://([a-z0-9][a-z0-9._-]*)\}}\}}",
            project_skill,
        )
    text = project_token(
        text,
        r"\b(agent|skill|rule|command|hook|workflow|stage|handler|gate|state|artifact)"
        r"://([a-z0-9][a-z0-9._-]*)",
        reference,
    )

    host = "Claude" if provider == "claude" else "Codex"
    replacements = {
        "{{request}}": "$ARGUMENTS"
        if provider == "claude"
        else "the invocation request",
        "{{pause_for_human:input}}": (
            "AskUserQuestion"
            if provider == "claude"
            else "pause and request user input"
        ),
        "{{host:title}}": host,
        "{{host:product}}": "Claude Code" if provider == "claude" else "Codex",
        "{{host:lower}}": host.lower(),
        "{{host:upper}}": host.upper(),
        "{{external_assistant:title}}": "Claude",
        "{{external_assistant:lower}}": "claude",
        "{{external_assistant:upper}}": "CLAUDE",
        "{{kit:distribution}}": "claude-code-kit",
        "{{kit:legacy-cli}}": "claude-sdlc",
        "{{kit:cli}}": "claude-kit" if provider == "claude" else "ckit",
        "{{kit:sidecar-suffix}}": ".claude-kit",
        "{{domain_literal:task-list-component}}": "TaskList",
        "{{provider_metadata:tool-allowlist}}": (
            "allowed-tools:"
            if provider == "claude"
            else "provider-native tool allowlist metadata"
        ),
        "{{external_permission:alternate-review-read-only}}": "--approval-mode plan",
        "{{capture_worker:job}}": (
            "`claude` job"
            if provider == "claude"
            else "configured background capture adapter"
        ),
        "{{host_feature:statusline-api}}": (
            "Claude Code's statusline API"
            if provider == "claude"
            else "the host's status interface, where available"
        ),
        "{{host_feature:dynamic-workflows}}": (
            "Claude Code's native dynamic-workflows engine"
            if provider == "claude"
            else "a native dynamic-workflow facility, where supported"
        ),
        "{{host_constraint:nested-delegation}}": (
            "Claude Code prevents nested subagent spawn"
            if provider == "claude"
            else "the active host or policy prevents nested delegation"
        ),
        "{{model_tier:balanced-title}}": "Sonnet"
        if provider == "claude"
        else "Balanced",
        "{{model_tier:balanced}}": "sonnet" if provider == "claude" else "balanced",
        "{{model_tier:deep-title}}": "Opus" if provider == "claude" else "Deep",
        "{{model_tier:deep}}": "opus" if provider == "claude" else "deep",
        "{{model_tier:fast-title}}": "Haiku" if provider == "claude" else "Fast",
        "{{model_tier:fast}}": "haiku" if provider == "claude" else "fast",
        "{{alternate_runtime:title}}": "Codex"
        if provider == "claude"
        else "an alternate model runtime",
        "{{alternate_runtime:full-title}}": "OpenAI Codex"
        if provider == "claude"
        else "an alternate model runtime",
        "{{alternate_runtime:cli-title}}": "Codex CLI"
        if provider == "claude"
        else "an alternate model CLI",
        "{{alternate_runtime:exec}}": "codex exec"
        if provider == "claude"
        else "<alternate-model-cli> exec",
        "{{alternate_runtime:binary}}": "codex"
        if provider == "claude"
        else "<alternate-model-cli>",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    for key, literal in _EXTERNAL_LITERALS.items():
        text = text.replace(f"{{{{external_literal:{key}}}}}", literal)
    tools = _CLAUDE_TOOL if provider == "claude" else _CODEX_TOOL
    for key, value in tools.items():
        text = text.replace(f"{{{{tool:{key}}}}}", value)
    text = re.sub(
        r"\{\{kit_env:([a-z0-9-]+)\}\}",
        lambda match: (
            ("CLAUDE_KIT_" if provider == "claude" else "CKIT_")
            + match.group(1).upper().replace("-", "_")
        ),
        text,
    )
    text = re.sub(
        r"\{\{host_env:([a-z0-9-]+)\}\}",
        lambda match: (
            "CLAUDE_" + match.group(1).upper().replace("-", "_")
            if provider == "claude"
            else "<host-env:" + match.group(1) + ">"
        ),
        text,
    )
    unresolved = re.findall(r"\{\{[a-z][a-z0-9_-]*:[^{}]+\}\}", text)
    if unresolved:
        raise ValueError(f"unresolved semantic markers: {sorted(set(unresolved))}")
    return text


def _yaml_frontmatter(metadata: Mapping[str, Any], body: str) -> str:
    frontmatter = yaml.safe_dump(
        dict(metadata), sort_keys=False, allow_unicode=True, width=10_000
    ).rstrip()
    return f"---\n{frontmatter}\n---\n\n{body.strip()}\n"


_CODEX_COMMAND_DESCRIPTIONS = {
    "abort": (
        "Abort the in-progress SDLC run, terminate its authoritative snapshot, "
        "and clean only its worktrees"
    ),
    "init": (
        "Install the Codex-native ckit configuration: AGENTS.md plus .agents, "
        ".codex, and shared .ckit state"
    ),
    "sdlc": "Run the full evidence-gated SDLC pipeline on a task",
    "status": "Show ckit working memory, runtime selection, and installed config status",
}


def _replace_once(text: str, old: str, new: str, *, label: str) -> str:
    if text.count(old) != 1:
        raise ValueError(
            f"reviewed Codex command projection boundary changed for {label}: "
            f"expected one match, found {text.count(old)}"
        )
    return text.replace(old, new, 1)


def _adapt_codex_command(record: CanonicalCommand, body: str) -> str:
    """Apply the native Codex runtime contract to one canonical command adapter."""
    command_id = record.spec.id
    if command_id == "abort":
        return body.replace("the sdlc skill", "the `sdlc` skill")

    if command_id == "sdlc":
        body = body.replace(
            "Invoke the **`sdlc`** skill with that request",
            "Invoke the **`sdlc` skill provided by this plugin** with that request",
        )
        return body.replace(
            "delegate to the `orchestrator` agent",
            "delegate to the project's `orchestrator` persona when one is installed; "
            "otherwise orchestrate in the current session",
        )

    if command_id == "status":
        old = (
            "2. **Installed config** — list what's present under `.ckit/`: counts of "
            "`rules/`, `agents/`,\n   `skills/`, and `hooks/`. Note if any are missing "
            "(suggest the init skill)."
        )
        new = (
            "2. **Installed config** — check each native surface separately: `AGENTS.md`,\n"
            "   `.agents/skills/`, `.codex/agents/`, `.codex/hooks.json`, "
            "`.codex/hooks/scripts/`, and\n   `.codex/config.toml`. Then summarize shared "
            "state under `.ckit/` (`rules/`, `templates/`,\n   `config/`, `state/`, "
            "`agent-memory/`, and `scripts/`). Note missing required surfaces and\n"
            "   suggest this plugin's `init` skill."
        )
        return _replace_once(body, old, new, label="status topology")

    if command_id != "init":
        raise ValueError(f"unsupported canonical command adapter: {command_id}")

    return _adapt_codex_init(body)


def _adapt_codex_init(body: str) -> str:
    old_intro = (
        "**The Python CLI is required.** It resolves the stack/profile/MCP catalog, "
        "installs overlay rules +\nagents, assembles `settings.json`, and records "
        "`init-options.json` for safe upgrades\n(`ckit upgrade` / `diff`). First detect "
        "whether it is on PATH (three entry points ship):"
    )
    new_intro = (
        "**The Python CLI is required.** It resolves the stack/profile/MCP catalog, projects\n"
        "Codex-native `AGENTS.md`, `.agents/skills/`, `.codex/agents/`, hooks, and MCP config, "
        "and records\nthe neutral `.ckit/config/init-options.json` manifest for safe upgrades "
        "(`ckit upgrade` / `diff`).\nDetect the preferred `ckit` entry point first; the "
        "older names are compatibility aliases:"
    )
    body = _replace_once(body, old_intro, new_intro, label="init introduction")

    old_detection = (
        'command -v ckit >/dev/null 2>&1 && echo "CKIT_CLI=ckit" \\\n'
        '  || { command -v ckit >/dev/null 2>&1 && echo "CKIT_CLI=ckit" \\\n'
        '  || { command -v claude-sdlc >/dev/null 2>&1 && echo "CKIT_CLI=claude-sdlc" \\\n'
        '  || echo "CKIT_CLI_MISSING"; }; }'
    )
    new_detection = (
        'command -v ckit >/dev/null 2>&1 && echo "CKIT_CLI=ckit" \\\n'
        '  || { command -v claude-kit >/dev/null 2>&1 && echo "CKIT_CLI=claude-kit" \\\n'
        '  || { command -v claude-sdlc >/dev/null 2>&1 && echo "CKIT_CLI=claude-sdlc" \\\n'
        '  || echo "CKIT_CLI_MISSING"; }; }'
    )
    body = _replace_once(body, old_detection, new_detection, label="init CLI detection")
    body = body.replace("re-run `the init skill`", "re-run this `init` skill")

    old_capture = (
        "   6. Learning capture (`off` default · `session-end-catchup` recommended · "
        "`session-end` ·\n      `per-task`) — capture is **opt-in**: tell the user the "
        "background job reads session\n      transcripts + changed files before they choose, "
        "that `CKIT_NO_AUTOCAPTURE=1` disables\n      it at runtime, and that `ckit "
        "privacy-report` audits what got installed. Only record a\n      non-`off` mode when "
        "the user explicitly picks one."
    )
    new_capture = (
        "   6. Learning capture (`off` default and recommended · `session-end` · `per-task` ·\n"
        "      `session-end-catchup` compatibility mode) — capture is **opt-in**. Explain that "
        "Codex capture\n      uses the repository's changed-path set in a sandboxed background "
        "task and does not assume a\n      historical transcript contract; catch-up safely no-ops when "
        "no stable transcript source exists.\n      `CKIT_NO_AUTOCAPTURE=1` disables capture, "
        "and `ckit privacy-report` audits the installed\n      hooks. Only record a non-`off` "
        "mode when the user explicitly picks one."
    )
    body = _replace_once(
        body, old_capture, new_capture, label="init capture disclosure"
    )

    request_marker = "   > `the invocation request`\n\n2. **Otherwise"
    runtime_contract = (
        "   > `the invocation request`\n\n"
        "   **Always make the runtime explicit.** Preserve a `--runtime claude|codex|both` "
        "argument that the\n   user supplied, or a top-level `runtime` already present in "
        "their `--config` file. Otherwise\n   append `--runtime codex`. Codex projection is "
        "preview in this release, so set\n   `CKIT_EXPERIMENTAL=1` for any `codex` or `both` "
        "init. Never invoke `init` from this adapter with\n   an implicit runtime.\n\n"
        "2. **Otherwise"
    )
    body = _replace_once(
        body, request_marker, runtime_contract, label="init runtime contract"
    )

    body = _replace_once(
        body,
        "`<CLI> init <target-dir> --config <temp-file>`",
        "`CKIT_EXPERIMENTAL=1 <CLI> init <target-dir> --config <temp-file> "
        "--runtime codex`",
        label="init config invocation",
    )
    body = _replace_once(
        body,
        "   frontend: { framework: react, language: typescript }",
        "   runtime: codex\n   frontend: { framework: react, language: typescript }",
        label="init config runtime",
    )
    body = _replace_once(
        body,
        "`ckit init /path/to/proj --defaults`.",
        "`CKIT_EXPERIMENTAL=1 ckit init /path/to/proj --defaults --runtime codex`. "
        "If the request already selected another runtime, preserve that value instead.",
        label="init argument example",
    )
    body = body.replace(
        "it invokes `ckit init`/`ckit init` when installed",
        "it invokes `ckit init` (or a compatibility CLI alias) when installed",
    )
    body = body.replace(
        "do not treat `CKIT_BASIC` as a bypass",
        "do not treat `CKIT_BASIC` as a bypass (the legacy `CLAUDE_KIT_BASIC` alias is "
        "not a bypass either)",
    )

    post_install = (
        "After it completes:\n"
        "1. Summarize the native Codex surfaces with counts: `AGENTS.md`, `.agents/skills/`,\n"
        "   `.codex/agents/`, `.codex/hooks.json`, `.codex/hooks/scripts/`, "
        "`.codex/config.toml`, and the\n   shared `.ckit/` rules, templates, "
        "configuration, state, memory, and scripts.\n"
        "2. Report the persisted runtime from `.ckit/config/init-options.json`; it must "
        "match the explicit\n   runtime selection. Do not call a Codex install successful if it "
        "silently recorded `claude`.\n"
        "3. Report managed-section merges, conflicts, and any `.claude-kit` sidecars exactly "
        "as the installer\n   logged them. Do not claim that `AGENTS.md` or "
        "`.codex/config.toml` was overwritten.\n"
        "4. Tell the user to restart Codex so newly installed project agents, skills, and "
        "hooks load.\n"
        "5. Suggest this plugin's `sdlc` skill with their first task.\n"
    )
    marker = "After it completes:"
    if body.count(marker) != 1:
        raise ValueError("reviewed Codex init post-install boundary changed")
    return body.split(marker, 1)[0] + post_install


def render_claude_skill(record: CanonicalSkill) -> str:
    metadata: dict[str, Any] = {
        "name": record.spec.id,
        "description": _project_semantics(record.spec.description, provider="claude"),
    }
    if record.request_input.mode is not RequestMode.NONE:
        metadata["argument-hint"] = _project_semantics(
            record.request_input.hint, provider="claude"
        )
    if record.spec.invocation is InvocationMode.EXPLICIT:
        metadata["disable-model-invocation"] = True
    return _yaml_frontmatter(
        metadata, _project_semantics(record.spec.instructions, provider="claude")
    )


def render_claude_skill_asset(asset: CanonicalSkillAsset) -> str:
    """Project one canonical auxiliary asset to the Claude compatibility tree."""
    content = asset.content
    if (
        asset.skill_id == "_references"
        and asset.relative_path.name == "orchestration-patterns.md"
    ):
        marker = "{{provider_appendix:orchestration-patterns}}"
        if content.count(marker) != 1:
            raise ValueError(
                "orchestration reference must declare exactly one provider appendix marker"
            )
        content = content.replace(marker, _CLAUDE_ORCHESTRATION_APPENDIX)
    return _project_semantics(content, provider="claude")


def render_codex_skill(
    record: CanonicalSkill | CanonicalCommand,
    *,
    plugin_context: bool = False,
) -> str:
    """Render a Codex-discoverable document with supported frontmatter only."""
    if isinstance(record, CanonicalSkill):
        projection = project_codex_skill(record, plugin_context=plugin_context)
        return _yaml_frontmatter(
            {
                "name": projection.name,
                "description": projection.description,
            },
            projection.instructions,
        )

    component_id = record.adapter_skill_id
    description = _CODEX_COMMAND_DESCRIPTIONS[record.spec.id]
    metadata = {
        "name": component_id,
        "description": description,
    }
    instructions = _project_semantics(
        record.spec.instructions,
        provider="codex",
        codex_skill_reference_base="references" if plugin_context else None,
        codex_plugin_context=plugin_context,
    )
    if plugin_context and isinstance(record, CanonicalCommand):
        instructions = _adapt_codex_command(record, instructions)
    return _yaml_frontmatter(
        metadata,
        instructions,
    )


def _display_name(component_id: str) -> str:
    return " ".join(
        part.upper()
        if part in {"api", "ci", "rbac", "sdlc", "ui", "ux"}
        else part.title()
        for part in component_id.removeprefix("ckit-command-").split("-")
    )


def _short_description(record: CanonicalSkill | CanonicalCommand) -> str:
    description = (
        _project_semantics(record.spec.description, provider="codex")
        if isinstance(record, CanonicalSkill)
        else _CODEX_COMMAND_DESCRIPTIONS[record.spec.id]
    )
    compact = " ".join(description.replace("`", "").split())
    if len(compact) <= 80:
        return compact
    prefix = compact[:77].rsplit(" ", 1)[0]
    return (prefix or compact[:77]).rstrip(".,;:") + "..."


def render_codex_policy(record: CanonicalSkill | CanonicalCommand) -> str | None:
    """Render explicit-only discovery policy for ``agents/openai.yaml``.

    Implicit skills need no sidecar.  Commands and explicit-only skills receive
    a policy sidecar so the target host does not silently discard the canonical
    invocation contract.
    """
    if record.spec.invocation is InvocationMode.IMPLICIT:
        return None
    return yaml.safe_dump(
        {
            "interface": {
                "display_name": _display_name(
                    record.spec.id
                    if isinstance(record, CanonicalSkill)
                    else record.adapter_skill_id
                ),
                "short_description": _short_description(record),
            },
            "policy": {"allow_implicit_invocation": False},
        },
        sort_keys=False,
        allow_unicode=True,
    )


def _codex_plugin_payloads(root: Path) -> dict[Path, str]:
    plugin_root = root / CODEX_PLUGIN_ROOT
    outputs: dict[Path, str] = {}
    assets = discover_canonical_skill_assets(root)
    shared_assets = {
        asset.relative_path.stem: asset
        for asset in assets
        if asset.skill_id == "_references"
    }
    for asset in assets:
        if asset.skill_id == "_references":
            continue
        outputs[plugin_root / "skills" / asset.skill_id / asset.relative_path] = (
            project_codex_skill_asset(asset, plugin_context=True)
        )
    records: tuple[CanonicalSkill | CanonicalCommand, ...] = (
        *(
            record
            for record in discover_canonical_skills(root)
            if record.kind.value == "core"
        ),
        *discover_canonical_commands(root),
    )
    for record in records:
        component_id = (
            record.spec.id
            if isinstance(record, CanonicalSkill)
            else record.adapter_skill_id
        )
        skill_root = plugin_root / "skills" / component_id
        outputs[skill_root / "SKILL.md"] = render_codex_skill(
            record, plugin_context=True
        )
        policy = render_codex_policy(record)
        if policy is not None:
            outputs[skill_root / "agents" / "openai.yaml"] = policy
        for reference in record.spec.references:
            prefix = "artifact://skill-reference-"
            if not reference.uri.startswith(prefix):
                continue
            reference_id = reference.uri.removeprefix(prefix)
            try:
                source_asset = shared_assets[reference_id]
            except KeyError as exc:
                raise ValueError(
                    f"missing shared skill reference for {record.spec.id}: {reference_id}"
                ) from exc
            outputs[skill_root / "references" / f"{reference_id}.md"] = (
                project_codex_skill_asset(source_asset, plugin_context=True)
            )
    return outputs


def render_claude_command_adapter(record: CanonicalCommand) -> str:
    metadata: dict[str, Any] = {
        "name": record.adapter_skill_id,
        "description": _project_semantics(record.spec.description, provider="claude"),
    }
    if record.request_input.mode is not RequestMode.NONE:
        metadata["argument-hint"] = _project_semantics(
            record.request_input.hint, provider="claude"
        )
    metadata["disable-model-invocation"] = True
    return _yaml_frontmatter(
        metadata, _project_semantics(record.spec.instructions, provider="claude")
    )


def render_legacy_command_wrapper(record: CanonicalCommand) -> str:
    metadata: dict[str, Any] = {
        "description": _project_semantics(record.spec.description, provider="claude"),
    }
    if record.request_input.mode is not RequestMode.NONE:
        metadata["argument-hint"] = _project_semantics(
            record.request_input.hint, provider="claude"
        )
    metadata["allowed-tools"] = "Skill"
    request = (
        " Forward the caller's request unchanged as `$ARGUMENTS`."
        if record.request_input.mode is not RequestMode.NONE
        else ""
    )
    body = (
        f"Invoke the `{record.adapter_skill_id}` skill and follow it to completion."
        f"{request} This wrapper is only the stable legacy slash-command alias; "
        "the generated skill is the behavior-bearing implementation."
    )
    return _yaml_frontmatter(metadata, body)


def generated_payloads(root: Path = ROOT) -> dict[Path, str]:
    outputs = {
        root / record.destination: render_claude_skill(record)
        for record in discover_canonical_skills(root)
    }
    outputs.update(
        {
            root / asset.destination: render_claude_skill_asset(asset)
            for asset in discover_canonical_skill_assets(root)
        }
    )
    for command in discover_canonical_commands(root):
        outputs[root / "skills" / command.adapter_skill_id / "SKILL.md"] = (
            render_claude_command_adapter(command)
        )
        outputs[root / command.destination] = render_legacy_command_wrapper(command)
    outputs.update(_codex_plugin_payloads(root))
    return outputs


def _existing_payloads(root: Path) -> set[Path]:
    paths = {
        path
        for path in (root / "skills").glob("*/**/*")
        if path.is_file() and path.name != "README.md"
    }
    paths.update(
        path
        for path in (root / "templates/org/skills").glob("*/**/*")
        if path.is_file() and path.name != "README.md"
    )
    paths.update((root / "commands").glob("*.md"))
    codex_skill_root = root / CODEX_PLUGIN_ROOT / "skills"
    if codex_skill_root.is_dir():
        paths.update(path for path in codex_skill_root.rglob("*") if path.is_file())
    return {path for path in paths if path.is_file()}


def generated_asset_modes(root: Path = ROOT) -> dict[Path, int]:
    """Return exact POSIX-mode expectations for every generated auxiliary asset."""
    assets = discover_canonical_skill_assets(root)
    modes = {root / asset.destination: asset.mode for asset in assets}
    shared = {
        asset.relative_path.stem: asset
        for asset in assets
        if asset.skill_id == "_references"
    }
    for asset in assets:
        if asset.skill_id == "_references":
            continue
        modes[
            root / CODEX_PLUGIN_ROOT / "skills" / asset.skill_id / asset.relative_path
        ] = asset.mode
    for record in discover_canonical_skills(root):
        if record.kind.value != "core":
            continue
        for reference in record.spec.references:
            prefix = "artifact://skill-reference-"
            if not reference.uri.startswith(prefix):
                continue
            reference_id = reference.uri.removeprefix(prefix)
            source = shared[reference_id]
            modes[
                root
                / CODEX_PLUGIN_ROOT
                / "skills"
                / record.spec.id
                / "references"
                / f"{reference_id}.md"
            ] = source.mode
    return modes


def check(root: Path = ROOT) -> list[str]:
    expected = generated_payloads(root)
    expected_modes = generated_asset_modes(root)
    diagnostics: list[str] = []
    for path, content in expected.items():
        relative = path.relative_to(root).as_posix()
        if not path.is_file():
            diagnostics.append(f"missing generated skill/command: {relative}")
        elif path.read_text(encoding="utf-8") != content:
            diagnostics.append(f"stale generated skill/command: {relative}")
        if path.is_file() and path in expected_modes:
            actual_mode = path.stat().st_mode & 0o777
            if actual_mode != expected_modes[path]:
                diagnostics.append(f"stale generated asset mode: {relative}")
    for path in sorted(_existing_payloads(root) - set(expected)):
        diagnostics.append(
            "unmanaged skill/command outside canonical source: "
            + path.relative_to(root).as_posix()
        )
    return diagnostics


def write(root: Path = ROOT) -> int:
    expected = generated_payloads(root)
    expected_modes = generated_asset_modes(root)
    unmanaged = sorted(_existing_payloads(root) - set(expected))
    if unmanaged:
        for path in unmanaged:
            print(
                "refusing to overwrite skill/command surface with unmanaged file: "
                + path.relative_to(root).as_posix(),
                file=sys.stderr,
            )
        return 1
    changed = 0
    for path, content in expected.items():
        content_current = path.is_file() and path.read_text(encoding="utf-8") == content
        mode_current = (
            path not in expected_modes
            or not path.is_file()
            or path.stat().st_mode & 0o777 == expected_modes[path]
        )
        if content_current and mode_current:
            continue
        if not content_current:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        if path in expected_modes:
            path.chmod(expected_modes[path])
        changed += 1
        print(f"generated {path.relative_to(root).as_posix()}")
    print(f"skill/command payloads current ({len(expected)} files, {changed} changed)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help="fail on missing, stale, or unmanaged generated payloads",
    )
    mode.add_argument(
        "--bootstrap-from-legacy",
        action="store_true",
        help="one-time reviewed conversion of the frozen legacy inventory",
    )
    mode.add_argument(
        "--refresh-from-legacy-commit",
        metavar="COMMIT",
        help="explicitly rebuild canonical sources from an immutable reviewed commit",
    )
    args = parser.parse_args(argv)
    if args.refresh_from_legacy_commit:
        result = bootstrap_from_legacy(
            source_commit=args.refresh_from_legacy_commit,
            refresh=True,
        )
        if result:
            return result
        return write()
    if args.bootstrap_from_legacy:
        result = bootstrap_from_legacy()
        if result:
            return result
        return write()
    if args.check:
        diagnostics = check()
        if diagnostics:
            for diagnostic in diagnostics:
                print(diagnostic, file=sys.stderr)
            return 1
        print("canonical skill/command payloads are current")
        return 0
    return write()


if __name__ == "__main__":
    raise SystemExit(main())
