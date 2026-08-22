"""Concrete provider renderers built on the projection contracts.

This module is intentionally not imported by :mod:`claude_kit.projection` and
does not mutate the default renderer registry.  Callers opt into a renderer
explicitly while the scaffold migration is still under construction.
"""

from __future__ import annotations

import json
import posixpath
import re
from collections import OrderedDict
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

from claude_kit.canonical_agents import (
    AgentSourceKind,
    CanonicalAgent,
    find_canonical_agent,
    load_canonical_agent,
)
from claude_kit.canonical_rules import (
    RuleLayer,
    compile_codex_rule_layers,
    render_codex_rule_layer,
    selected_rule_layers,
)
from claude_kit.canonical_skills import (
    CanonicalSkill,
    CanonicalSkillAsset,
    codex_reference_target,
    discover_canonical_skill_assets,
    discover_canonical_skills,
    load_canonical_skill,
    project_codex_inline_tokens,
    project_codex_reference_tokens,
    project_codex_skill,
    project_codex_skill_asset,
)
from claude_kit.canonical_templates import (
    CanonicalTemplate,
    TemplateFormat,
    discover_canonical_templates,
)
from claude_kit.components import (
    Capability,
    HookEvent,
    InvocationMode,
    ModelTier,
    NestedDelegationPolicy,
    PermissionClass,
    SymbolicRef,
)
from claude_kit.hooks import HOOK_REGISTRY, HOOK_SPECS
from claude_kit.mcp import adapt_codex_server_config, project_resolved_servers
from claude_kit.models import InstallRequest, ResolvedPlan
from claude_kit.projection import ProjectionFile, Provider, ProviderSpec
from claude_kit.provider_compatibility import (
    AgentProjectionCompatibility,
    load_agent_projection_compatibility,
)
from claude_kit.render import render_text

_AGENTS_MAX_BYTES = 32 * 1024
_MARKDOWN_LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
_FENCED_BLOCK_RE = re.compile(r"(?:```|~~~).*?(?:```|~~~)", re.DOTALL)
_CAPTURE_SCRIPT = "capture-learnings.sh"
_TELEMETRY_SCRIPT = "capture-ticket-telemetry.sh"
_CODEX_TEMPLATE_PLACEHOLDERS = {
    "provider.path.config_root": ".ckit/",
    "provider.path.rules": ".ckit/rules/",
    "provider.path.agents": ".codex/agents/",
    "provider.path.skills": ".agents/skills/",
    "provider.path.settings": ".codex/hooks.json",
    "provider.path.settings_local": ".codex/config.toml",
    "provider.path.project_instructions": "AGENTS.md",
    "provider.path.sdlc_readme": ".ckit/README.sdlc.md",
    "provider.path.mcp_config": ".codex/config.toml",
    "provider.path.user_config": "~/.codex/",
    "provider.path.loop_script": ".ckit/scripts/sdlc-loop.sh",
    "provider.executable.cli": "ckit",
    "provider.executable.cli_legacy": "ckit",
    "provider.name.host": "Codex",
    "provider.name.agent": "Codex",
    "provider.environment.kit_prefix": "CKIT",
}
_FORBIDDEN_TEXT = (
    re.compile(r"\$ARGUMENTS"),
    re.compile(r"\bAskUserQuestion\b"),
    re.compile(r"\bCLAUDE_CODE_[A-Z0-9_]*\b"),
    re.compile(r"\bCLAUDE_PROJECT_DIR\b"),
    re.compile(r"\bCLAUDE_PLUGIN_ROOT\b"),
    re.compile(r"CLAUDE\.md"),
    re.compile(r"\.claude(?:/|\\)"),
    re.compile(r"(?<![\w./:-])/(?:claude-kit:[a-z-]+|sdlc\b)"),
)
_SHANNON_EXTERNAL_CLI_ENV_NAMES = frozenset(
    {
        "CLAUDE_CODE_MAX_OUTPUT_TOKENS",
        "CLAUDE_CODE_USE_BEDROCK",
        "CLAUDE_CODE_USE_VERTEX",
        "CLAUDE_ADAPTIVE_THINKING",
    }
)
_SHANNON_CODEX_DOCUMENTS = frozenset(
    {
        ".agents/skills/shannon-ai-pentest/SKILL.md",
        ".agents/skills/shannon-ai-pentest/references/operating-guide.md",
        "providers/codex/claude-kit/skills/shannon-ai-pentest/SKILL.md",
        "providers/codex/claude-kit/skills/shannon-ai-pentest/references/operating-guide.md",
    }
)

_CODEX_HOOK_EVENTS: dict[HookEvent, str] = {
    HookEvent.SESSION_START: "SessionStart",
    HookEvent.USER_PROMPT: "UserPromptSubmit",
    HookEvent.PRE_TOOL: "PreToolUse",
    HookEvent.POST_TOOL: "PostToolUse",
    HookEvent.TOOL_FAILURE: "PostToolUseFailure",
    HookEvent.STOP: "Stop",
    HookEvent.SUBAGENT_START: "SubagentStart",
    HookEvent.SUBAGENT_STOP: "SubagentStop",
    HookEvent.PRE_COMPACT: "PreCompact",
    HookEvent.SESSION_END: "SessionEnd",
}

_CODEX_HOOK_MATCHERS: dict[str | None, str] = {
    None: "",
    "shell": "Bash|exec_command|shell|unified_exec",
    "file-read": "Read|read_file",
    "file-read|shell": "Read|read_file|Bash|exec_command|shell|unified_exec",
    "file-write|apply-patch": "Write|apply_patch",
    "file-edit|file-write|apply-patch": "Edit|MultiEdit|Write|apply_patch",
}

_CODEX_PROJECT_ROOT_PREAMBLE = r"""# Resolve the physical project root. Codex may launch hooks from a nested session cwd and does not
# guarantee CKIT_PROJECT_ROOT. Never follow provider-state/control symlinks while choosing a root.
_CKIT_ROOT_EXPLICIT=0
if [ -n "${CKIT_PROJECT_ROOT:-}" ]; then
  _CKIT_ROOT_START="$CKIT_PROJECT_ROOT"
  _CKIT_ROOT_EXPLICIT=1
else
  _CKIT_ROOT_START="$PWD"
fi
ROOT="$(cd -P -- "$_CKIT_ROOT_START" 2>/dev/null && pwd -P)" || exit 0
while :; do
  if [ -L "$ROOT/.ckit" ] || [ -L "$ROOT/.codex" ] || [ -L "$ROOT/.git" ] || \
     [ -L "$ROOT/.codex/hooks.json" ] || [ -L "$ROOT/.ckit/config" ] || \
     [ -L "$ROOT/.ckit/config/init-options.json" ]; then
    exit 0
  fi
  if { [ -d "$ROOT/.codex" ] && [ -f "$ROOT/.codex/hooks.json" ]; } || \
     { [ -d "$ROOT/.ckit/config" ] && [ -f "$ROOT/.ckit/config/init-options.json" ]; } || \
     [ -d "$ROOT/.git" ] || [ -f "$ROOT/.git" ]; then
    break
  fi
  [ "$_CKIT_ROOT_EXPLICIT" -eq 0 ] || exit 0
  [ "$ROOT" != "/" ] || exit 0
  ROOT="${ROOT%/*}"
  [ -n "$ROOT" ] || ROOT="/"
done
unset _CKIT_ROOT_EXPLICIT _CKIT_ROOT_START
"""

# Gate ownership is workflow semantics, not provider syntax.  Only roles that
# are actually selected are named in the rendered AGENTS.md.
_GATE_ROLE_CANDIDATES: dict[str, tuple[str, ...]] = {
    "spec-complete": ("spec-doc-writer", "story-planner"),
    "em-approved": ("em-reviewer",),
    "code-review": ("sdlc-code-reviewer",),
    "build-green": ("tester", "developer"),
    "contract-clear": ("technical-architect", "merge-reviewer"),
    "test-coverage": ("senior-tester", "unit-tester", "e2e-tester"),
    "security-clear": ("security-reviewer",),
    "pipeline-green": ("devops-engineer",),
    "observability-ready": ("observability-engineer",),
    "acceptance": ("acceptance-reviewer",),
}

_CODEX_VALIDATE_FRONTMATTER = """#!/usr/bin/env bash
# PreToolUse: validate native agent TOML and Open Agent Skills frontmatter.
# Advisory only; malformed in-progress content produces context but never blocks.
command -v jq >/dev/null 2>&1 || exit 0
INPUT="$(cat)"
FILE_PATH="$(printf '%s' "$INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null || true)"
BODY="$(printf '%s' "$INPUT" | jq -r '.tool_input.content // empty' 2>/dev/null || true)"
[ -n "$FILE_PATH" ] && [ -n "$BODY" ] || exit 0

W=""
case "$FILE_PATH" in
  */.codex/agents/*.toml|.codex/agents/*.toml)
    for key in name description developer_instructions; do
      printf '%s\n' "$BODY" | grep -qE "^[[:space:]]*$key[[:space:]]*=" || W="WARN: agent $FILE_PATH is missing required '$key'."
    done
    ;;
  */.agents/skills/*/SKILL.md|.agents/skills/*/SKILL.md)
    case "$BODY" in
      ---*)
        FM="$(printf '%s\n' "$BODY" | awk 'NR==1&&/^---/{f=1;next} f&&/^---/{exit} f{print}')"
        printf '%s\n' "$FM" | grep -qE '^name:[[:space:]]*[^[:space:]]' || W="WARN: skill $FILE_PATH is missing 'name:'."
        printf '%s\n' "$FM" | grep -qE '^description:[[:space:]]*[^[:space:]]' || W="WARN: skill $FILE_PATH is missing 'description:'."
        ;;
      *) W="WARN: skill $FILE_PATH has no YAML frontmatter." ;;
    esac
    ;;
  *) exit 0 ;;
esac

[ -n "$W" ] && jq -n --arg ctx "$W" '{hookSpecificOutput: {hookEventName: "PreToolUse", additionalContext: $ctx}}'
exit 0
"""

_CODEX_VALIDATE_SETTINGS = """#!/usr/bin/env bash
# PreToolUse: fail closed when a write would corrupt native hook JSON.
command -v jq >/dev/null 2>&1 || exit 0
INPUT="$(cat)"
FILE_PATH="$(printf '%s' "$INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null || true)"
case "$FILE_PATH" in
  */.codex/hooks.json|.codex/hooks.json) : ;;
  *) exit 0 ;;
esac
BODY="$(printf '%s' "$INPUT" | jq -r '.tool_input.content // empty' 2>/dev/null || true)"
[ -n "$BODY" ] || exit 0
if ! printf '%s' "$BODY" | jq empty >/dev/null 2>&1; then
  echo "BLOCKED: $FILE_PATH would not be valid JSON; invalid hook configuration disables guardrails." >&2
  exit 2
fi
exit 0
"""

_UNSUPPORTED_TELEMETRY = """#!/usr/bin/env bash
# Automatic ticket telemetry is unsupported on this provider projection.
# Session transcript formats are provider-owned and are not treated as interchangeable.
echo "NOTICE: automatic ticket telemetry is unsupported; use explicit ckit ticket reporting." >&2
exit 0
"""


class CodexRenderer:
    """Render the currently selected payload as native Codex project files."""

    def __init__(self, payload_root: Path) -> None:
        root = Path(payload_root)
        if not root.is_dir():
            raise ValueError(f"payload root is not a directory: {root}")
        self._payload_root = root
        self._compatibility = load_agent_projection_compatibility(root, "codex")

    @property
    def spec(self) -> ProviderSpec:
        """Declare renderer versions and capabilities without selecting a model."""
        return ProviderSpec(
            provider=Provider.CODEX,
            rendering_version=1,
            compatibility_catalog_version=self._compatibility.catalog_version,
            capabilities=frozenset(Capability),
        )

    def render(
        self, resolved_plan: ResolvedPlan, request: InstallRequest
    ) -> Iterable[ProjectionFile]:
        """Render one resolved plan without re-reading or branching on catalogs."""
        if resolved_plan.selection != request.selection:
            raise ValueError(
                "install request selection must match the resolved plan selection"
            )
        if Provider.CODEX.value not in request.runtimes:
            raise ValueError("CodexRenderer requires a request selecting codex")

        known_skill_ids = self._discover_skill_ids()
        codex_servers = project_resolved_servers(
            resolved_plan.mcp_servers,
            resolved_plan.mcp_server_specs,
            Provider.CODEX.value,
        )
        rules = selected_rule_layers(self._payload_root, resolved_plan)
        selected_agent_ids = set(resolved_plan.agents)
        selected_agent_ids.update(resolved_plan.overlay_agents)
        selected_skill_ids = set(resolved_plan.skills)
        if resolved_plan.org is not None:
            selected_agent_ids.update(resolved_plan.org.org_agents)
            selected_skill_ids.update(resolved_plan.org.org_skills)
        selected_inventory = {
            "agent": frozenset(selected_agent_ids),
            "skill": frozenset(selected_skill_ids),
            "rule": frozenset(layer.id for layer in rules),
            "command": frozenset({"abort", "init", "status"} | selected_skill_ids),
        }
        agents = self._read_selected_agents(
            resolved_plan,
            selected_inventory["skill"],
            selected_inventory=selected_inventory,
            mcp_server_ids=tuple(codex_servers),
        )
        skills = self._read_selected_skills(
            resolved_plan,
            selected_inventory["skill"],
            selected_inventory=selected_inventory,
        )
        skill_assets = self._read_selected_skill_assets(
            resolved_plan,
            selected_inventory=selected_inventory,
        )
        output: list[ProjectionFile] = []

        agents_document = _render_agents_document(
            resolved_plan,
            agents,
            skills,
            rules,
            selected_inventory=selected_inventory,
        )
        output.append(
            _text_file(
                component="artifact://agents-instructions",
                path="AGENTS.md",
                content=agents_document,
                media_type="text/markdown",
            )
        )

        for component_id, metadata, body in agents:
            output.append(
                _text_file(
                    component=f"agent://{component_id}",
                    path=f".codex/agents/{component_id}.toml",
                    content=_render_agent_toml(
                        metadata, body, compatibility=self._compatibility
                    ),
                    media_type="application/toml",
                )
            )

        for component_id, metadata, body in skills:
            output.append(
                _text_file(
                    component=f"skill://{component_id}",
                    path=f".agents/skills/{component_id}/SKILL.md",
                    content=_render_skill_document(metadata, body),
                    media_type="text/markdown",
                )
            )
            if metadata.get("disable-model-invocation") is True:
                output.append(
                    _text_file(
                        component=f"skill://{component_id}",
                        path=f".agents/skills/{component_id}/agents/openai.yaml",
                        content=("policy:\n  allow_implicit_invocation: false\n"),
                        media_type="application/yaml",
                    )
                )

        for asset, path in skill_assets:
            component = (
                f"artifact://skill-reference-{asset.relative_path.stem}"
                if asset.skill_id == "_references"
                else f"skill://{asset.skill_id}"
            )
            output.append(
                _text_file(
                    component=component,
                    path=path,
                    content=project_codex_skill_asset(
                        asset, selected_inventory=selected_inventory
                    ),
                    executable=asset.executable,
                    media_type=_skill_asset_media_type(asset.relative_path),
                )
            )

        for layer in rules:
            output.append(
                _text_file(
                    component=f"rule://{layer.id}",
                    path=f".ckit/rules/{layer.id}.md",
                    content=render_codex_rule_layer(
                        layer, selected_inventory=selected_inventory
                    ),
                    media_type="text/markdown",
                )
            )

        output.extend(
            self._render_templates(
                resolved_plan,
                known_skill_ids,
                selected_inventory=selected_inventory,
                agent_count=len(agents),
                skill_count=len(skills),
            )
        )
        hook_files = self._render_hooks(resolved_plan, selected_inventory["skill"])
        output.extend(hook_files)
        output.append(
            _text_file(
                component="artifact://codex-config",
                path=".codex/config.toml",
                content=_render_mcp_config(codex_servers),
                media_type="application/toml",
            )
        )

        output.sort(key=lambda item: item.path)
        for item in output:
            _assert_no_provider_leakage(item.text_content, location=item.path)
        return tuple(output)

    def _discover_skill_ids(self) -> frozenset[str]:
        return frozenset(
            record.spec.id for record in discover_canonical_skills(self._payload_root)
        )

    def _read_selected_agents(
        self,
        plan: ResolvedPlan,
        skill_invocations: frozenset[str],
        *,
        selected_inventory: Mapping[str, frozenset[str]],
        mcp_server_ids: tuple[str, ...],
    ) -> list[tuple[str, dict[str, Any], str]]:
        sources: list[CanonicalAgent] = []
        for component_id in plan.agents:
            sources.append(
                find_canonical_agent(
                    self._payload_root,
                    component_id,
                    kind=AgentSourceKind.CORE,
                )
            )
        for component_id in plan.overlay_agents:
            candidates = [
                self._payload_root
                / "canonical"
                / "agents"
                / "stacks"
                / stack_dir
                / f"{component_id}.md"
                for stack_dir in plan.stack_dirs.values()
            ]
            sources.append(
                load_canonical_agent(
                    self._payload_root, _one_existing(component_id, candidates)
                )
            )
        if plan.org is not None:
            for component_id in plan.org.org_agents:
                sources.append(
                    find_canonical_agent(
                        self._payload_root,
                        component_id,
                        kind=AgentSourceKind.ORG,
                    )
                )
        records: list[tuple[str, dict[str, Any], str]] = []
        seen: set[str] = set()
        for source in sources:
            if source.spec.id in seen:
                continue
            seen.add(source.spec.id)
            records.append(
                (
                    source.spec.id,
                    {
                        "name": source.spec.id,
                        "description": source.spec.description,
                        "permission": source.spec.permission.value,
                        "model_tier": source.spec.model_tier.value,
                        "capabilities": tuple(
                            capability.value
                            for capability in sorted(
                                source.spec.capabilities,
                                key=lambda item: item.value,
                            )
                        ),
                        "write_scope": source.spec.write_scope,
                        "isolation": source.spec.isolation.value,
                        "nested_delegation": source.spec.nested_delegation.value,
                        "mcp_server_ids": mcp_server_ids,
                    },
                    _render_codex_agent_instructions(
                        source,
                        skill_invocations,
                        selected_inventory=selected_inventory,
                        profile=plan.selection.profile,
                    ),
                )
            )
        return records

    def _read_selected_skills(
        self,
        plan: ResolvedPlan,
        skill_invocations: frozenset[str],
        *,
        selected_inventory: Mapping[str, frozenset[str]],
    ) -> list[tuple[str, dict[str, Any], str]]:
        sources: list[CanonicalSkill] = [
            load_canonical_skill(
                self._payload_root,
                self._payload_root
                / "canonical"
                / "skills"
                / "core"
                / f"{component_id}.md",
            )
            for component_id in plan.skills
        ]
        if plan.org is not None:
            sources.extend(
                load_canonical_skill(
                    self._payload_root,
                    self._payload_root
                    / "canonical"
                    / "skills"
                    / "org"
                    / f"{component_id}.md",
                )
                for component_id in plan.org.org_skills
            )
        records: list[tuple[str, dict[str, Any], str]] = []
        seen: set[str] = set()
        for source in sources:
            if source.spec.id in seen:
                continue
            seen.add(source.spec.id)
            projection = project_codex_skill(
                source, selected_inventory=selected_inventory
            )
            metadata: dict[str, Any] = {
                "name": projection.name,
                "description": projection.description,
            }
            if source.spec.invocation is InvocationMode.EXPLICIT:
                metadata["disable-model-invocation"] = True
            records.append(
                (
                    source.spec.id,
                    metadata,
                    _project_codex_skill_invocations(
                        projection.instructions, skill_invocations
                    ).strip()
                    + "\n",
                )
            )
        return records

    def _read_selected_skill_assets(
        self,
        plan: ResolvedPlan,
        *,
        selected_inventory: Mapping[str, frozenset[str]],
    ) -> list[tuple[CanonicalSkillAsset, str]]:
        """Return selected auxiliary assets plus cross-owner link closure."""
        all_assets = discover_canonical_skill_assets(self._payload_root)
        assets_by_source_path = {
            asset.destination.as_posix(): asset for asset in all_assets
        }
        selected_skill_ids = selected_inventory["skill"]
        included: dict[str, CanonicalSkillAsset] = {
            path: asset
            for path, asset in assets_by_source_path.items()
            if asset.skill_id in selected_skill_ids
        }

        selected_sources = [
            record
            for record in discover_canonical_skills(self._payload_root)
            if record.spec.id in selected_skill_ids
        ]
        for source in selected_sources:
            for reference in source.spec.references:
                prefix = "artifact://skill-reference-"
                if not reference.uri.startswith(prefix):
                    continue
                reference_id = reference.uri.removeprefix(prefix)
                source_path = f"skills/_references/{reference_id}.md"
                try:
                    included[source_path] = assets_by_source_path[source_path]
                except KeyError as exc:
                    raise ValueError(
                        f"selected skill {source.spec.id!r} requires missing shared "
                        f"reference {reference_id!r}"
                    ) from exc

        documents: list[tuple[str, str]] = [
            (
                f"skills/{record.spec.id}/SKILL.md",
                project_codex_skill(
                    record, selected_inventory=selected_inventory
                ).instructions,
            )
            for record in selected_sources
        ]
        queued_assets = set(included)
        documents.extend(
            (
                path,
                project_codex_skill_asset(asset, selected_inventory=selected_inventory),
            )
            for path, asset in included.items()
        )
        for document_path, content in documents:
            for target in _local_markdown_targets(document_path, content):
                asset = assets_by_source_path.get(target)
                if asset is None:
                    parts = Path(target).parts
                    selected_skill_target = (
                        len(parts) == 3
                        and parts[0] == "skills"
                        and parts[1] in selected_skill_ids
                        and parts[2] == "SKILL.md"
                    ) or (
                        len(parts) == 2
                        and parts[0] == "skills"
                        and parts[1] in selected_skill_ids
                    )
                    if selected_skill_target:
                        continue
                    raise ValueError(
                        f"selected skill asset link is missing: {document_path} -> {target}"
                    )
                if target in queued_assets:
                    continue
                included[target] = asset
                queued_assets.add(target)
                documents.append(
                    (
                        target,
                        project_codex_skill_asset(
                            asset, selected_inventory=selected_inventory
                        ),
                    )
                )

        return [
            (
                asset,
                ".agents/skills/" + source_path.removeprefix("skills/"),
            )
            for source_path, asset in sorted(included.items())
        ]

    def _render_templates(
        self,
        plan: ResolvedPlan,
        known_skill_ids: frozenset[str],
        *,
        selected_inventory: Mapping[str, frozenset[str]],
        agent_count: int,
        skill_count: int,
    ) -> tuple[ProjectionFile, ...]:
        """Render the selected canonical text templates to truthful native paths."""
        context = dict(plan.context)
        context.setdefault("project_name", "project")
        context["agent_count"] = str(agent_count)
        context["skill_count"] = str(skill_count)
        context["overlay_rules_list"] = ", ".join(plan.overlay_rules) or "none"
        context["org_packs_list"] = (
            ", ".join(plan.org.packs) if plan.org is not None else "none"
        )
        for key in (
            "frontend_overlay_rule",
            "backend_overlay_rule",
            "db_overlay_rule",
        ):
            context[key] = Path(context.get(key, "")).stem

        output: list[ProjectionFile] = []
        for record in _selected_codex_templates(self._payload_root, plan):
            path = _codex_template_destination(record)
            content = _render_codex_template(
                record,
                plan,
                context,
                known_skill_ids,
                selected_inventory,
            )
            media_type = (
                "application/yaml"
                if record.format is TemplateFormat.YAML
                else "text/markdown"
            )
            output.append(
                _text_file(
                    component=f"artifact://{record.id}",
                    path=path,
                    content=content,
                    media_type=media_type,
                )
            )
        return tuple(output)

    def _render_hooks(
        self, plan: ResolvedPlan, skill_invocations: frozenset[str]
    ) -> tuple[ProjectionFile, ...]:
        selected = set(plan.hooks)
        unknown = selected - set(HOOK_REGISTRY)
        if unknown:
            raise ValueError("unknown hook ids: " + ", ".join(sorted(unknown)))
        hook_ids = [hook_id for hook_id in HOOK_REGISTRY if hook_id in selected]

        grouped: OrderedDict[str, OrderedDict[str, list[dict[str, Any]]]] = (
            OrderedDict()
        )
        scripts: set[str] = set()
        for hook_id in hook_ids:
            hook = HOOK_REGISTRY[hook_id]
            semantic = HOOK_SPECS[hook_id]
            try:
                event = _CODEX_HOOK_EVENTS[semantic.event]
            except KeyError as exc:
                raise ValueError(
                    f"hook {hook_id!r} uses unsupported Codex event {semantic.event.value!r}"
                ) from exc
            try:
                matcher = _CODEX_HOOK_MATCHERS[semantic.operation_matcher]
            except KeyError as exc:
                raise ValueError(
                    f"hook {hook_id!r} uses unsupported operation matcher "
                    f"{semantic.operation_matcher!r}"
                ) from exc
            script = hook.get("script")
            if script:
                scripts.add(str(script))
            entry: dict[str, Any] = {
                "type": "command",
                "command": (
                    "ckit hook-run --provider codex "
                    f'--hook-id {hook_id} --path "${{CKIT_PROJECT_ROOT:-$PWD}}" '
                    "--discover-project-root"
                ),
            }
            if hook.get("timeout") is not None:
                entry["timeout"] = hook["timeout"]
            grouped.setdefault(event, OrderedDict()).setdefault(matcher, []).append(
                entry
            )

        hooks_document = {
            "hooks": {
                event: [
                    {"matcher": matcher, "hooks": entries}
                    for matcher, entries in matchers.items()
                ]
                for event, matchers in grouped.items()
            }
        }
        output = [
            _text_file(
                component="artifact://codex-hooks",
                path=".codex/hooks.json",
                content=json.dumps(
                    hooks_document,
                    indent=2,
                    ensure_ascii=False,
                    separators=(",", ": "),
                )
                + "\n",
                media_type="application/json",
            )
        ]
        for script in sorted(scripts):
            output.append(
                _text_file(
                    component=f"handler://{script}",
                    path=f".codex/hooks/scripts/{script}",
                    content=self._adapt_hook_script(script, skill_invocations),
                    executable=True,
                    media_type="text/x-shellscript",
                )
            )
        return tuple(output)

    def _adapt_hook_script(self, script: str, skill_invocations: frozenset[str]) -> str:
        if script == _TELEMETRY_SCRIPT:
            return _UNSUPPORTED_TELEMETRY
        if script == "validate-frontmatter.sh":
            return _CODEX_VALIDATE_FRONTMATTER
        if script == "validate-settings.sh":
            return _CODEX_VALIDATE_SETTINGS
        source = self._payload_root / "hooks" / "scripts" / script
        if not source.is_file():
            raise FileNotFoundError(f"selected hook script does not exist: {source}")
        adapted = _adapt_text(
            source.read_text(encoding="utf-8"), skill_invocations, script=True
        )
        if script == _CAPTURE_SCRIPT:
            # The universal adapter selects its executable from CKIT_HOOK_PROVIDER. Keep the Codex
            # projection free of a literal command for the other host, including unreachable code.
            adapted = re.sub(r"\bclaude\b", "codex", adapted)
        if script == "load-learnings.sh":
            adapted = re.sub(
                r'SETTINGS="[^\n]+"\nif \[ -f "\$SETTINGS" \].*?\nfi\n',
                'CAPTURE_NOTE="Automatic capture is unsupported on this provider; use the explicit $remember skill for durable learnings."\n',
                adapted,
                count=1,
                flags=re.DOTALL,
            )
        root_patterns = (
            'ROOT="${CKIT_PROJECT_ROOT:-$PWD}"',
            'MEM_DIR="${CKIT_PROJECT_ROOT:-$PWD}/.ckit/agent-memory"',
            'cd "${CKIT_PROJECT_ROOT:-$PWD}" 2>/dev/null || exit 0',
        )
        if any(pattern in adapted for pattern in root_patterns):
            lines = adapted.splitlines()
            lines[1:1] = _CODEX_PROJECT_ROOT_PREAMBLE.rstrip().splitlines()
            adapted = "\n".join(lines) + ("\n" if adapted.endswith("\n") else "")
            adapted = adapted.replace('ROOT="${CKIT_PROJECT_ROOT:-$PWD}"\n', "", 1)
            adapted = adapted.replace(
                'MEM_DIR="${CKIT_PROJECT_ROOT:-$PWD}/.ckit/agent-memory"',
                'MEM_DIR="$ROOT/.ckit/agent-memory"',
                1,
            )
            adapted = adapted.replace(
                'cd "${CKIT_PROJECT_ROOT:-$PWD}" 2>/dev/null || exit 0',
                'cd "$ROOT" 2>/dev/null || exit 0',
                1,
            )
        return adapted.rstrip() + "\n"


def _selected_codex_templates(
    payload_root: Path, plan: ResolvedPlan
) -> tuple[CanonicalTemplate, ...]:
    """Select canonical templates with a useful, non-colliding Codex destination."""
    base_ids = {
        "stack-instructions",
        "continuity-seed",
        "memory-index",
        "sdlc-readme",
    }
    selected: list[CanonicalTemplate] = []
    selected_packs = set(plan.org.packs) if plan.org is not None else set()
    for record in discover_canonical_templates(payload_root):
        if record.id in base_ids or record.id.startswith("artifact-"):
            selected.append(record)
            continue
        if record.id == "org-readme" and selected_packs:
            selected.append(record)
            continue
        if any(record.id.startswith(f"org-pack-{pack}-") for pack in selected_packs):
            selected.append(record)
    return tuple(selected)


def _codex_template_destination(record: CanonicalTemplate) -> str:
    """Map one selected canonical template to its native or neutral runtime path."""
    fixed = {
        "stack-instructions": ".ckit/STACK.md",
        "continuity-seed": ".ckit/CONTINUITY.template.md",
        "memory-index": ".ckit/templates/agent-memory/MEMORY.md",
        "sdlc-readme": ".ckit/README.sdlc.md",
        "org-readme": ".ckit/org-packs/README.md",
    }
    if record.id in fixed:
        return fixed[record.id]
    if record.id.startswith("artifact-"):
        return f".ckit/templates/{record.destination.name}"
    if record.id.startswith("org-pack-"):
        try:
            pack_index = record.destination.parts.index("packs") + 1
            pack = record.destination.parts[pack_index]
        except (ValueError, IndexError) as exc:
            raise ValueError(
                f"canonical org template {record.id!r} has no pack destination"
            ) from exc
        return f".ckit/org-packs/{pack}/{record.destination.name}"
    raise ValueError(f"canonical template {record.id!r} has no Codex destination")


def _render_codex_template(
    record: CanonicalTemplate,
    plan: ResolvedPlan,
    context: dict[str, str],
    known_skill_ids: frozenset[str],
    selected_inventory: Mapping[str, frozenset[str]],
) -> str:
    """Project one canonical template without preserving host-specific assumptions."""
    rendered = record.content
    for placeholder in record.provider_placeholders:
        try:
            replacement = _CODEX_TEMPLATE_PLACEHOLDERS[placeholder]
        except KeyError as exc:
            raise ValueError(
                f"canonical template {record.id!r} uses unsupported Codex placeholder "
                f"{placeholder!r}"
            ) from exc
        rendered = re.sub(
            r"\{\{\s*" + re.escape(placeholder) + r"\s*\}\}",
            replacement,
            rendered,
        )
    if "{{ provider." in rendered:
        raise ValueError(
            f"canonical template {record.id!r} retained a provider placeholder"
        )
    skill_invocation_re = re.compile(
        r"\{\{skill_invocation:skill://([a-z0-9][a-z0-9._-]*)\}\}"
    )
    rendered = project_codex_inline_tokens(
        rendered,
        skill_invocation_re,
        lambda match: (
            f"${match.group(1)}"
            if match.group(1) in selected_inventory["skill"]
            else codex_reference_target(
                "skill",
                match.group(1),
                skill_reference_base=None,
                plugin_context=False,
                selected_inventory=selected_inventory,
            )
        ),
    )
    rendered = _project_codex_agent_references(
        rendered,
        selected_inventory["skill"],
        selected_inventory,
    )
    if record.format is TemplateFormat.JINJA_MARKDOWN:
        rendered = render_text(rendered, context)
    rendered = _project_codex_template_slash_commands(
        rendered,
        known_skill_ids,
        selected_inventory,
    )
    rendered = rendered.replace(
        "auto-discovered .ckit/ locations", "provider-projected native locations"
    )
    rendered = rendered.replace("(slash commands)", "(explicit skill invocations)")
    rendered = rendered.replace(
        "personal `settings.local.json`", "personal local overrides"
    )
    rendered = rendered.replace(".codex/agents/<name>.md", ".codex/agents/<name>.toml")
    rendered = rendered.replace(".codex/agents/*.md", ".codex/agents/*.toml")
    if record.id == "sdlc-readme":
        rendered = _adapt_codex_readme(rendered, plan)
    if "{{ provider." in rendered or "{%" in rendered:
        raise ValueError(f"canonical template {record.id!r} was not fully rendered")
    return rendered.rstrip() + "\n"


def _project_codex_template_slash_commands(
    text: str,
    known_skill_ids: frozenset[str],
    selected_inventory: Mapping[str, frozenset[str]],
) -> str:
    """Fail closed for known legacy skill invocations without touching URL routes."""

    if not known_skill_ids:
        return text
    names = "|".join(
        re.escape(name) for name in sorted(known_skill_ids, key=len, reverse=True)
    )

    def replace(match: re.Match[str]) -> str:
        component_id = match.group(1)
        if component_id in selected_inventory["skill"]:
            return f"${component_id}"
        return codex_reference_target(
            "skill",
            component_id,
            skill_reference_base=None,
            plugin_context=False,
            selected_inventory=selected_inventory,
        )

    invocation_re = re.compile(
        rf"(?<![\w./:-])/({names})(?=$|[\s`),:;!?\]}}]|\.(?![a-zA-Z0-9]))"
    )
    return project_codex_inline_tokens(
        text,
        invocation_re,
        replace,
    )


def _adapt_codex_readme(text: str, plan: ResolvedPlan) -> str:
    """Replace topology and runtime sections whose semantics differ by provider."""
    topology = """## What got installed

```
AGENTS.md                         managed workflow, gate, and selected-rule instructions
.codex/agents/*.toml             named specialist roles
.agents/skills/*/SKILL.md        reusable skills; invoke manual skills with `$skill-name`
.codex/hooks.json                native hook event registration
.codex/hooks/scripts/            selected hook adapters
.codex/config.toml               project MCP registrations
.ckit/STACK.md                   selected stack conventions and project commands
.ckit/rules/*.md                 complete selected rule projections
.ckit/CONTINUITY.md              live cross-session working memory
.ckit/agent-memory/              durable project learnings
.ckit/templates/                 provider-projected artifact and seed templates
.ckit/config/                    selection, checksums, and catalog snapshot
.ckit/state/  .ckit/tmp/         shared runtime state and scratch space
.ckit/scripts/sdlc-loop.sh       bounded provider-selectable unattended loop
.ckit/README.sdlc.md             this guide
```

Codex loads `AGENTS.md` as project instructions, discovers named roles under
`.codex/agents/`, discovers skills under `.agents/skills/`, reads project MCP servers from
`.codex/config.toml`, and uses `.codex/hooks.json` for the selected lifecycle adapters.

Only concrete paths and `$skill` invocations in this guide are installed for this selection.
Later capability matrices describe the broader package catalog; optional-component labels are
context only and are not runnable in this project.
"""
    text = re.sub(
        r"## What got installed\n.*?(?=\n## Privacy — learning capture)",
        topology.rstrip() + "\n",
        text,
        count=1,
        flags=re.DOTALL,
    )

    if plan.selection.capture_mode == "off":
        privacy = """## Privacy — learning capture

Learning capture is **OFF for this install**. Existing project learnings still load from
`.ckit/agent-memory/`. Re-run `ckit init` with an explicit capture mode to enable background
capture, and inspect the resulting hooks with `ckit privacy-report`.
"""
    else:
        privacy = f"""## Privacy — learning capture

Learning capture is **ON for this install** (`{plan.selection.capture_mode}`). Codex capture uses
the repository's changed-path set and a sandboxed background task; it does not assume access to a
provider transcript directory. Secret-bearing paths are excluded, secret-shaped values are
redacted, and payload size is bounded. Historical-session catch-up is a safe no-op without a stable
transcript contract; use `$remember` for anything missed. Review new `.ckit/agent-memory/` entries
before committing them.

- `CKIT_NO_AUTOCAPTURE=1` disables capture.
- `CKIT_CAPTURE_MAX_LINES` / `CKIT_CAPTURE_MAX_BYTES` bound each capture input.
- `ckit privacy-report` audits installed hooks and their read/write behavior.
"""
    text = re.sub(
        r"## Privacy — learning capture\n.*?(?=\n## Start the workflow)",
        privacy.rstrip() + "\n",
        text,
        count=1,
        flags=re.DOTALL,
    )

    return text


def _text_file(
    *,
    component: str,
    path: str,
    content: str,
    executable: bool = False,
    media_type: str,
) -> ProjectionFile:
    return ProjectionFile.text(
        provider=Provider.CODEX,
        component=SymbolicRef.parse(component),
        path=path,
        content=content,
        executable=executable,
        media_type=media_type,
    )


def _skill_asset_media_type(path: Path) -> str:
    return {
        ".md": "text/markdown",
        ".py": "text/x-python",
        ".sh": "text/x-shellscript",
        ".txt": "text/plain",
    }[path.suffix.lower()]


def _local_markdown_targets(document_path: str, text: str) -> tuple[str, ...]:
    """Resolve local Markdown links against a virtual generated skill tree."""
    targets: list[str] = []
    document = _FENCED_BLOCK_RE.sub("", text)
    for match in _MARKDOWN_LINK_RE.finditer(document):
        raw = match.group(1).strip()
        if raw.startswith("<") and ">" in raw:
            raw = raw[1 : raw.index(">")]
        else:
            raw = raw.split(maxsplit=1)[0]
        raw = raw.split("#", 1)[0]
        if (
            not raw
            or raw.startswith(("/", "#"))
            or "{" in raw
            or "}" in raw
            or "://" in raw
            or raw.startswith(("mailto:", "data:"))
        ):
            continue
        resolved = posixpath.normpath(
            posixpath.join(posixpath.dirname(document_path), raw)
        )
        if resolved.startswith("skills/"):
            targets.append(resolved)
    return tuple(dict.fromkeys(targets))


def _one_existing(component_id: str, candidates: Iterable[Path]) -> Path:
    existing = [candidate for candidate in candidates if candidate.is_file()]
    if len(existing) != 1:
        rendered = ", ".join(str(path) for path in existing) or "none"
        raise ValueError(
            f"overlay agent {component_id!r} must resolve to one selected stack file; "
            f"found {rendered}"
        )
    return existing[0]


def _codex_agent_reference(
    kind: str,
    component_id: str,
    skill_invocations: frozenset[str],
    selected_inventory: Mapping[str, frozenset[str]],
) -> str:
    if kind == "agent":
        if component_id in selected_inventory["agent"]:
            return f".codex/agents/{component_id}.toml"
        return codex_reference_target(
            kind,
            component_id,
            skill_reference_base=None,
            plugin_context=False,
            selected_inventory=selected_inventory,
        )
    if kind == "skill":
        if component_id in skill_invocations:
            return f"${component_id}"
        return codex_reference_target(
            kind,
            component_id,
            skill_reference_base=None,
            plugin_context=False,
            selected_inventory=selected_inventory,
        )
    if kind == "rule":
        if component_id in selected_inventory["rule"]:
            return f".ckit/rules/{component_id}.md"
        return codex_reference_target(
            kind,
            component_id,
            skill_reference_base=None,
            plugin_context=False,
            selected_inventory=selected_inventory,
        )
    if kind == "command":
        if component_id in skill_invocations:
            return f"${component_id}"
        if component_id in {"init", "status", "abort"}:
            return f"`ckit {component_id}`"
        return codex_reference_target(
            "skill",
            component_id,
            skill_reference_base=None,
            plugin_context=False,
            selected_inventory=selected_inventory,
        )
    if kind == "state":
        return {
            "continuity": ".ckit/CONTINUITY.md",
            "agent-memory": ".ckit/agent-memory",
            "workflow": ".ckit/state",
            "artifacts": ".ckit/artifacts",
            "configuration": ".ckit/config",
        }.get(component_id, f".ckit/state/{component_id}")
    if kind == "artifact":
        return {
            "project-instructions": "AGENTS.md",
            "templates": ".ckit/templates",
            "org-packs": ".ckit/org-packs",
            "browser-service": "the configured browser service",
        }.get(component_id, component_id)
    return f"the `{kind}:{component_id}` contract"


def _project_codex_agent_references(
    text: str,
    skill_invocations: frozenset[str],
    selected_inventory: Mapping[str, frozenset[str]],
) -> str:
    return project_codex_reference_tokens(
        text,
        lambda kind, component_id: _codex_agent_reference(
            kind,
            component_id,
            skill_invocations,
            selected_inventory,
        ),
    )


def _render_codex_agent_instructions(
    source: CanonicalAgent,
    skill_invocations: frozenset[str],
    *,
    selected_inventory: Mapping[str, frozenset[str]],
    profile: str,
) -> str:
    spec = source.spec
    capabilities = (
        ", ".join(
            capability.value
            for capability in sorted(spec.capabilities, key=lambda item: item.value)
        )
        or "none"
    )
    write_scope = ", ".join(f"`{scope}`" for scope in spec.write_scope) or "none"
    required_skills = (
        ", ".join(
            _codex_agent_reference(
                "skill", reference.id, skill_invocations, selected_inventory
            )
            for reference in spec.required_skills
        )
        or "none"
    )
    contract = (
        "## Semantic role contract\n\n"
        f"- Permission class: `{spec.permission.value}`\n"
        f"- Capabilities: {capabilities}\n"
        f"- Write scope: {write_scope}\n"
        f"- Isolation: `{spec.isolation.value}`\n"
        f"- Nested delegation: `{spec.nested_delegation.value}`\n"
        f"- Model tier: `{spec.model_tier.value}`\n"
        f"- Required skills: {required_skills}\n"
        f"- Workflow tier: `{source.workflow_tier.value}`\n\n"
        f"Only components installed for the `{profile}` profile are active. Optional-component "
        "labels are context only; do not dispatch, invoke, or rely on them. This boundary does "
        "not relax the ordered gates in `AGENTS.md`.\n\n"
    )
    instructions = _project_codex_agent_references(
        spec.instructions, skill_invocations, selected_inventory
    ).strip()
    return contract + instructions + "\n"


def _render_agent_toml(
    metadata: dict[str, Any],
    body: str,
    *,
    compatibility: AgentProjectionCompatibility,
) -> str:
    name = str(metadata["name"])
    description = str(metadata["description"])
    try:
        permission = PermissionClass(str(metadata["permission"]))
        model_tier = ModelTier(str(metadata["model_tier"]))
        nested_delegation = NestedDelegationPolicy(str(metadata["nested_delegation"]))
        capabilities = frozenset(
            Capability(str(value)) for value in metadata["capabilities"]
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            f"Codex agent {name!r} has an invalid semantic contract"
        ) from exc
    sandbox_mode = compatibility.permission_classes[permission]
    model = compatibility.model_tiers[model_tier]
    lines = [
        f"name = {_toml_string(name)}",
        f"description = {_toml_string(description)}",
        f"developer_instructions = {_toml_string(body)}",
    ]
    if model is not None:
        lines.append(f"model = {_toml_string(model)}")
    lines.extend(
        [
            f"sandbox_mode = {_toml_string(sandbox_mode)}",
            "",
            "[agents]",
            "enabled = "
            + (
                "false"
                if nested_delegation is NestedDelegationPolicy.FORBIDDEN
                else "true"
            ),
        ]
    )
    feature_values = {
        "multi_agent": nested_delegation is not NestedDelegationPolicy.FORBIDDEN,
        "browser_use": Capability.BROWSER in capabilities,
        "browser_use_external": Capability.BROWSER in capabilities,
        "computer_use": Capability.BROWSER in capabilities,
        "apps": Capability.BROWSER in capabilities,
    }
    lines.extend(["", "[features]"])
    for key in sorted(feature_values):
        lines.append(f"{key} = {'true' if feature_values[key] else 'false'}")

    # Keep native role defaults fail-closed. Managed execution repeats these
    # values as CLI overrides because a parent Codex session can override a
    # custom agent's defaults at spawn time.
    lines.extend(
        [
            "",
            "[sandbox_workspace_write]",
            "network_access = false",
            "exclude_slash_tmp = true",
            "exclude_tmpdir_env_var = true",
            "",
            "[shell_environment_policy]",
            'inherit = "core"',
            "ignore_default_excludes = false",
            "experimental_use_profile = false",
        ]
    )

    if Capability.MCP not in capabilities:
        for server_id in metadata.get("mcp_server_ids", ()):
            lines.extend(
                [
                    "",
                    f"[mcp_servers.{_toml_key(str(server_id))}]",
                    "enabled = false",
                ]
            )
    return "\n".join(lines).rstrip() + "\n"


def _render_skill_document(metadata: dict[str, Any], body: str) -> str:
    frontmatter = {
        "name": str(metadata["name"]),
        "description": str(metadata["description"]),
    }
    rendered = yaml.safe_dump(
        frontmatter,
        sort_keys=False,
        allow_unicode=True,
        width=10_000,
    ).rstrip()
    return f"---\n{rendered}\n---\n\n{body.lstrip()}"


def _render_agents_document(
    plan: ResolvedPlan,
    agents: list[tuple[str, dict[str, Any], str]],
    skills: list[tuple[str, dict[str, Any], str]],
    rules: tuple[RuleLayer, ...],
    *,
    selected_inventory: Mapping[str, frozenset[str]],
) -> str:
    selected_agents = {component_id for component_id, _, _ in agents}
    lines = [
        "# Codex SDLC instructions",
        "",
        "This project uses a named multi-agent, evidence-gated delivery workflow. The main Codex "
        "task is the controller: named agent files make specialists available, but do not run "
        "stages automatically.",
        "",
        "## Runtime contract",
        "",
        "- Delegate independent work with `spawn_agent`; use `send_message` for bounded handoffs and "
        "wait for every required lane before a join.",
        "- Keep mutable kit state under `.ckit/`. Read `.ckit/CONTINUITY.md` before resuming and "
        "update it after verified work or a gate transition.",
        "- Read `.ckit/STACK.md` for selected stack commands and conventions. Rules summarized "
        "below are also emitted in full under `.ckit/rules/`.",
        "- Treat `.codex/agents/*.toml` as named roles and `.agents/skills/*/SKILL.md` as reusable "
        "instructions. Invoke manual skills explicitly with `$skill-name`.",
        "- Use `ckit pipeline` lifecycle commands for gate state. Do not hand-edit the pipeline "
        "snapshot or manufacture evidence.",
        "- A gate closes only with cited, project-contained evidence. A skipped or not-applicable "
        "gate is recorded explicitly and is never reported as PASS.",
        "",
        "## Active selection",
        "",
        f"- Profile: `{plan.selection.profile}`",
        f"- Gate-definition digest: `{plan.gate_definition_digest}`",
        "- State root: `.ckit/`",
        "",
        "## Named roles",
        "",
        "| Agent | Responsibility |",
        "|---|---|",
    ]
    for component_id, metadata, _ in agents:
        lines.append(
            f"| `{component_id}` | {_markdown_cell(str(metadata['description']))} |"
        )

    lines.extend(
        [
            "",
            "## Ordered quality gates",
            "",
            "Run gates in this exact order. The named owner returns evidence and a verdict; the main "
            "task records the transition and routes defects back to an implementation role.",
            "",
            "| # | Gate | Primary role | Policy |",
            "|---:|---|---|---|",
        ]
    )
    for index, gate in enumerate(plan.gates, start=1):
        owner = _gate_owner(gate, selected_agents)
        definition = plan.gate_definitions[gate]
        policy = definition.requirement
        if definition.skip_conditions:
            policy += "; conditions: " + ", ".join(definition.skip_conditions)
        lines.append(f"| {index} | `{gate}` | `{owner}` | {_markdown_cell(policy)} |")

    lines.extend(["", "## Installed skills", ""])
    for component_id, _, _ in skills:
        lines.append(f"- `${component_id}`")

    capture_hooks = [
        hook for hook in plan.hooks if hook.startswith("capture-learnings")
    ]
    if capture_hooks:
        lines.extend(
            [
                "",
                "## Provider limitation",
                "",
                "Session-end and per-task learning capture use the selected provider's headless "
                "runner and write only to `.ckit/agent-memory/`. Historical-session catch-up is a "
                "safe no-op because this provider has no stable transcript-directory contract; use "
                "the explicit `$remember` skill for anything missed.",
            ]
        )

    base = "\n".join(lines).rstrip() + "\n\n"
    remaining = _AGENTS_MAX_BYTES - len(base.encode("utf-8")) - 1
    compiled = compile_codex_rule_layers(
        rules,
        max_bytes=remaining,
        selected_inventory=selected_inventory,
    )
    rendered = base + compiled.markdown
    size = len(rendered.encode("utf-8"))
    if size >= _AGENTS_MAX_BYTES:
        raise ValueError(
            f"rendered AGENTS.md is {size} bytes; must stay below {_AGENTS_MAX_BYTES}"
        )
    return rendered


def _gate_owner(gate: str, selected_agents: set[str]) -> str:
    for candidate in _GATE_ROLE_CANDIDATES.get(gate, ()):
        if candidate in selected_agents:
            return candidate
    if "orchestrator" in selected_agents:
        return "orchestrator"
    return "main-task"


def _markdown_cell(value: str) -> str:
    return " ".join(value.split()).replace("|", "\\|")


def _render_mcp_config(servers: dict[str, dict[str, Any]]) -> str:
    lines = [
        "# Native Codex project configuration generated from the selected MCP set.",
        "# Authentication remains environment-owned; no credentials are generated.",
    ]
    if not servers:
        lines.extend(["", "# No MCP servers selected."])
        return "\n".join(lines) + "\n"

    for server_id in sorted(servers):
        config = adapt_codex_server_config(server_id, servers[server_id])
        table = f"mcp_servers.{_toml_key(server_id)}"
        lines.extend(["", f"[{table}]"])

        for key in sorted(config):
            value = config[key]
            if isinstance(value, dict):
                continue
            lines.append(f"{_toml_key(key)} = {_toml_value(value)}")
        for key in sorted(config):
            value = config[key]
            if not isinstance(value, dict):
                continue
            lines.extend(["", f"[{table}.{_toml_key(key)}]"])
            for nested_key in sorted(value):
                lines.append(
                    f"{_toml_key(nested_key)} = {_toml_value(value[nested_key])}"
                )
    return "\n".join(lines).rstrip() + "\n"


def _toml_key(value: str) -> str:
    return _toml_string(str(value))


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _toml_value(value: object) -> str:
    if isinstance(value, str):
        return _toml_string(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    raise ValueError(f"unsupported TOML value type: {type(value).__name__}")


def _project_codex_skill_invocations(
    text: str, skill_invocations: frozenset[str]
) -> str:
    if not skill_invocations:
        return text
    names = "|".join(
        re.escape(name) for name in sorted(skill_invocations, key=len, reverse=True)
    )
    return re.sub(
        rf"(?<![\w./:-])/({names})(?=$|[\s`),.:])",
        lambda match: f"${match.group(1)}",
        text,
    )


def _adapt_text(
    text: str, skill_invocations: frozenset[str], *, script: bool = False
) -> str:
    replacements = (
        ("${CLAUDE_PROJECT_DIR:-$PWD}", "${CKIT_PROJECT_ROOT:-$PWD}"),
        ("${CLAUDE_PROJECT_DIR:-.}", "${CKIT_PROJECT_ROOT:-$PWD}"),
        ("${CLAUDE_PROJECT_DIR}", "${CKIT_PROJECT_ROOT:-$PWD}"),
        ("CLAUDE_PROJECT_DIR", "CKIT_PROJECT_ROOT"),
        ("CLAUDE_PLUGIN_ROOT", "PLUGIN_ROOT"),
        ("CLAUDE_KIT_", "CKIT_"),
        ("CLAUDE.md", "AGENTS.md"),
        (".claude/config/", ".ckit/config/"),
        (".claude/state/", ".ckit/state/"),
        (".claude/artifacts/", ".ckit/artifacts/"),
        (".claude/agent-memory/", ".ckit/agent-memory/"),
        (".claude/CONTINUITY.md", ".ckit/CONTINUITY.md"),
        (".claude/skills/", ".agents/skills/"),
        (".claude/agents/", ".codex/agents/"),
        (".claude/hooks/", ".codex/hooks/scripts/"),
        (".claude/settings.local.json", ".codex/config.toml"),
        (".claude/settings.json", ".codex/hooks.json"),
        (".claude/templates/", ".ckit/templates/"),
    )
    adapted = text
    for old, new in replacements:
        adapted = adapted.replace(old, new)
    adapted = re.sub(r"\.claude/rules/[A-Za-z0-9_.-]+\.md", "AGENTS.md", adapted)
    adapted = adapted.replace(".claude/", ".ckit/").replace(".claude", ".ckit")
    adapted = re.sub(
        r"\bCLAUDE_CODE_[A-Z0-9_]+\b", "the provider-specific setting", adapted
    )
    adapted = adapted.replace("$ARGUMENTS", "the user's supplied request")
    adapted = adapted.replace("AskUserQuestion", "request_user_input")
    adapted = adapted.replace("Claude Code", "Codex")
    adapted = re.sub(r"(--provider(?:=|\s+))claude\b", r"\1codex", adapted)

    adapted = re.sub(
        r"(?<![\w./:-])/claude-kit:(init|status|abort)\b",
        lambda match: f"`ckit {match.group(1)}`",
        adapted,
    )
    adapted = _project_codex_skill_invocations(adapted, skill_invocations)
    builtins = {
        "clear": "the fresh-task action",
        "compact": "context compaction",
        "hooks": "hook diagnostics",
        "plugin": "plugin management",
    }
    adapted = re.sub(
        r"(?<![\w./:-])/(clear|compact|hooks|plugin)\b",
        lambda match: builtins[match.group(1)],
        adapted,
    )
    if script:
        adapted = adapted.replace("claude-kit", "ckit")
        adapted = adapted.replace("Claude", "Codex")
        adapted = adapted.replace("`claude`", "a provider background task")
    return adapted


def codex_provider_leakage_scan_text(text: str, *, location: str) -> str:
    """Remove only reviewed external-tool literals before host-wire scanning.

    Shannon's own public CLI uses environment variables whose historical names
    contain ``CLAUDE_CODE``. They configure Shannon, not the Codex host. Keep
    those exact names only in Shannon's projected skill and operating guide;
    every other path and every unrecognized variable remains subject to the
    normal fail-closed provider-leakage checks.
    """
    normalized = location.replace("\\", "/")
    if not any(
        normalized == allowed or normalized.endswith("/" + allowed)
        for allowed in _SHANNON_CODEX_DOCUMENTS
    ):
        return text
    scanned = text
    for name in sorted(_SHANNON_EXTERNAL_CLI_ENV_NAMES):
        scanned = re.sub(rf"(?<![A-Z0-9_]){re.escape(name)}(?![A-Z0-9_])", "", scanned)
    return scanned


def _assert_no_provider_leakage(text: str, *, location: str) -> None:
    scanned = codex_provider_leakage_scan_text(text, location=location)
    for pattern in _FORBIDDEN_TEXT:
        match = pattern.search(scanned)
        if match:
            excerpt = scanned[max(0, match.start() - 20) : match.end() + 20]
            raise ValueError(
                f"provider leakage in {location}: {match.group(0)!r} near {excerpt!r}"
            )


__all__ = ["CodexRenderer", "codex_provider_leakage_scan_text"]
