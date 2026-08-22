"""Hook registry — the single definition of every hook claude-kit can install.

A *profile* selects hook ids (see ``catalog/profiles.yaml``); the installer turns the selected ids
into (a) the set of ``.sh`` scripts to copy into ``.claude/hooks/`` and (b) an assembled
``.claude/settings.json`` ``hooks`` block. Keeping the registry in one module lets both
:mod:`claude_kit.catalog` (to resolve the ``all`` token) and :mod:`claude_kit.scaffold`
(to build settings) share it without duplication.

Hooks are deliberately **conservative**: guardrails block obviously dangerous actions; the quality
hooks only *suggest* running tools. Script-backed hooks reference ``${CLAUDE_PROJECT_DIR}`` so they
work in a scaffolded project (the plugin variant uses ``${CLAUDE_PLUGIN_ROOT}``).
"""

from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import Any, Callable

from claude_kit.components import (
    HookEffect,
    HookEvent,
    HookSeverity,
    HookSpec,
    SymbolicRef,
)
from claude_kit.models import InitOptions, StateLayout
from claude_kit.secure_fs import ProjectFS
from claude_kit.state import detect_state_layout

# --- inline guard commands (no script file needed) -------------------------------------------------

_RM_RF_GUARD = (
    "command -v jq >/dev/null 2>&1 || exit 0; "
    "CMD=$(jq -r '.tool_input.command' 2>/dev/null || true); "
    "if printf '%s' \"$CMD\" | grep -qE '(^|[^[:alnum:]_])rm([[:space:]]|$)' "
    "&& printf '%s' \"$CMD\" | grep -qE '(^|[[:space:]])-[a-zA-Z]*[rR]|--recursive' "
    "&& printf '%s' \"$CMD\" | grep -qE '(^|[[:space:]])-[a-zA-Z]*f|--force'; then "
    "echo 'BLOCKED: rm -rf (recursive+force, any flag order/spelling) is disabled by claude-kit. "
    "Move to trash or delete specific paths explicitly.' >&2; exit 2; fi"
)

# Block pushes whose *target* ref is main/master. This is a SCRIPT guard (guard-push-main.sh) rather
# than an inline command because the matcher needs a small shell tokenizer: it normalizes the command
# (stripping `git` + global options like `-c k=v` / `-C dir`) so those can't be used to evade it, and
# widens the branch boundary so force-push refspecs (`+main`, `HEAD:refs/heads/main`) are caught too.
# Legit branches that merely contain the substring (maintenance, main-feature, feature/main-ui) stay
# spared. A single inline `grep` string can't express the multi-token normalization, hence the script.

_SECRETS_GUARD = (
    "command -v jq >/dev/null 2>&1 || exit 0; "
    "FP=$(jq -r '.tool_input.file_path // empty' 2>/dev/null || true); "
    'if echo "$FP" | grep -qE \'(^|/)\\.env$|\\.pem$|\\.key$|(^|/)id_rsa|(^|/)id_ed25519|'
    "(^|/)credentials(\\.json)?$|\\.p12$'; then "
    "echo 'BLOCKED: refusing to read a secrets file. Use .env.example or a secret manager.' >&2; "
    "exit 2; fi"
)


def _script_entry(
    name: str, arg: str = "", timeout: int | None = None
) -> dict[str, Any]:
    """Build a settings.json command entry that runs a project-local hook script.

    Args:
        name: Script basename under ``.claude/hooks/``.
        arg: Optional single positional argument appended to the command (e.g. a dispatch mode like
            ``end``/``stop``/``catchup`` so several hook ids can share one script).
        timeout: Optional per-hook timeout in **seconds** (the hooks-reference unit). Only worth
            setting where the event's default budget is tight — e.g. SessionEnd's 1.5s, which the
            settings channel may raise via per-hook timeouts (plugin-channel timeouts do not raise
            that budget, per the reference).
    """
    command = f'bash "${{CLAUDE_PROJECT_DIR}}/.claude/hooks/{name}"'
    if arg:
        command += f" {arg}"
    entry: dict[str, Any] = {"type": "command", "command": command}
    if timeout is not None:
        entry["timeout"] = timeout
    return entry


def _plugin_entry(
    name: str, arg: str = "", timeout: int | None = None
) -> dict[str, Any]:
    """Build a settings.json command entry that runs a hook script from the plugin root.

    The plugin variant of :func:`_script_entry` — Claude Code exposes the plugin's own directory via
    ``${CLAUDE_PLUGIN_ROOT}``, so the auto-discovered ``hooks/hooks.json`` references scripts there
    rather than in a scaffolded project's ``.claude/hooks/``.
    """
    command = f'bash "${{CLAUDE_PLUGIN_ROOT}}/hooks/scripts/{name}"'
    if arg:
        command += f" {arg}"
    entry: dict[str, Any] = {"type": "command", "command": command}
    if timeout is not None:
        entry["timeout"] = timeout
    return entry


def _codex_plugin_entry(
    name: str, arg: str = "", timeout: int | None = None
) -> dict[str, Any]:
    """Build a command entry for a script in a native Codex plugin archive.

    Codex exposes the installed plugin directory through ``${PLUGIN_ROOT}``. Keep this separate
    from :func:`_plugin_entry`: the established Claude plugin document must retain its
    ``${CLAUDE_PLUGIN_ROOT}`` commands byte-for-byte.
    """
    command = f'bash "${{PLUGIN_ROOT}}/hooks/scripts/{name}"'
    if arg:
        command += f" {arg}"
    entry: dict[str, Any] = {"type": "command", "command": command}
    if timeout is not None:
        entry["timeout"] = timeout
    return entry


# Format decisions, verified against the official hooks reference (Jul 2026) — don't re-litigate
# without new evidence:
# - Matchers here ("Bash", "Read", "Edit|Write") use only exact-match-set characters, so Claude Code
#   compares them as exact strings / exact alternatives — NOT unanchored regexes. Anchoring them as
#   ^Bash$ would move them onto the regex path for zero behavioral gain.
# - Shell form (command string, no ``args``) is deliberate. Exec form (``args: [...]``) is the
#   docs-recommended style for path placeholders, but it was only introduced in Claude Code 2.1.139;
#   on older versions an ``args`` entry degrades to bare ``bash`` eating hook JSON on stdin — every
#   guard silently dead. Our double-quoted placeholders are already space/char-safe. Revisit when
#   the 2.1.139 floor is comfortably old.
# - Blocking guards use exit code 2 + stderr, which the docs keep as a fully supported signaling
#   path (only *top-level* decision/reason is deprecated, and only for PreToolUse). JSON output
#   (hookSpecificOutput.permissionDecision) buys nothing for a hard block and adds a stdout-purity
#   constraint to every bash script. A plugin auto-ALLOWING commands would loosen the user's own
#   permission posture — never do that from here.
#: The canonical registry. Order here is the order hooks appear in assembled settings.json.
#: Each value: ``event``, ``matcher``, ``entry`` (settings.json hook object), and ``script``
#: (basename under payload ``hooks/scripts/`` to copy, or ``None`` for inline/prompt hooks).
HOOK_REGISTRY: dict[str, dict[str, Any]] = {
    "load-continuity": {
        "event": "SessionStart",
        "matcher": "",
        "entry": _script_entry("load-continuity.sh"),
        "script": "load-continuity.sh",
        "data_access": "reads .claude/CONTINUITY.md (seeded from the template when missing) into "
        "session context; local only, no background job",
    },
    "load-learnings": {
        "event": "SessionStart",
        "matcher": "",
        "entry": _script_entry("load-learnings.sh"),
        "script": "load-learnings.sh",
        "data_access": "reads .claude/agent-memory/MEMORY.md (the learnings index) into session "
        "context; local only, no background job",
    },
    "load-autonomy": {
        "event": "SessionStart",
        "matcher": "",
        "entry": _script_entry("load-autonomy.sh"),
        "script": "load-autonomy.sh",
        "data_access": "reads the installed autonomy-level config into session context; local only",
    },
    "guard-rm-rf": {
        "event": "PreToolUse",
        "matcher": "Bash",
        "entry": {"type": "command", "command": _RM_RF_GUARD},
        "script": None,
        "data_access": "inspects the Bash command JSON on stdin to block rm -rf; reads no files, "
        "writes nothing",
    },
    "guard-push-main": {
        "event": "PreToolUse",
        "matcher": "Bash",
        "entry": _script_entry("guard-push-main.sh"),
        "script": "guard-push-main.sh",
        "data_access": "inspects the Bash command JSON on stdin to block pushes targeting "
        "main/master; reads no files",
    },
    "guard-destructive-git": {
        "event": "PreToolUse",
        "matcher": "Bash",
        "entry": _script_entry("guard-destructive-git.sh"),
        "script": "guard-destructive-git.sh",
        "data_access": "inspects the Bash command JSON on stdin to block git reset --hard / "
        "clean -f / worktree-wide discards; reads no files",
    },
    "protect-secrets": {
        "event": "PreToolUse",
        "matcher": "Read",
        "entry": {"type": "command", "command": _SECRETS_GUARD},
        "script": None,
        "data_access": "inspects native Read paths and, through the scaffolded Codex adapter, "
        "explicit local file operands in shell commands to block secrets files (.env, keys, "
        "credentials); never reads file contents",
    },
    "guard-commit-secrets": {
        "event": "PreToolUse",
        "matcher": "Bash",
        "entry": _script_entry("guard-secrets.sh"),
        "script": "guard-secrets.sh",
        "data_access": "inspects Bash commit commands and staged file names to block committing "
        "secret-looking files",
    },
    "warn-shared-modules": {
        "event": "PreToolUse",
        "matcher": "Edit|Write",
        "entry": _script_entry("warn-shared-modules.sh"),
        "script": "warn-shared-modules.sh",
        "data_access": "inspects the edited file path for shared/project-wide config; advisory "
        "warning only, never blocks",
    },
    "warn-llm-io": {
        "event": "PreToolUse",
        "matcher": "Edit|Write",
        "entry": _script_entry("warn-llm-io.sh"),
        "script": "warn-llm-io.sh",
        "data_access": "inspects the edit's path and proposed content for LLM-SDK/prompt patterns; "
        "advisory warning only",
    },
    "warn-sensitive-files": {
        "event": "PreToolUse",
        "matcher": "Edit|Write",
        "entry": _script_entry("warn-sensitive-files.sh"),
        "script": "warn-sensitive-files.sh",
        "data_access": "inspects the edited file path for security-sensitive surfaces (auth, "
        "payments, migrations, infra); advisory only",
    },
    "warn-large-edits": {
        "event": "PreToolUse",
        "matcher": "Edit|Write",
        "entry": _script_entry("warn-large-edits.sh"),
        "script": "warn-large-edits.sh",
        "data_access": "counts changed lines in the proposed edit; advisory only",
    },
    "validate-frontmatter": {
        "event": "PreToolUse",
        "matcher": "Write",
        "entry": _script_entry("validate-frontmatter.sh"),
        "script": "validate-frontmatter.sh",
        # Its sibling validate-settings does block (exit 2); this one deliberately does not, and
        # said otherwise in the note privacy-report shows the user.
        "data_access": "parses the YAML frontmatter of a written agent/skill file; advisory "
        "only, never blocks — warnings return as additionalContext",
    },
    "validate-settings": {
        "event": "PreToolUse",
        "matcher": "Write",
        "entry": _script_entry("validate-settings.sh"),
        "script": "validate-settings.sh",
        "data_access": "parses a written settings.json for JSON validity; blocks only invalid JSON",
    },
    "warn-missing-tests": {
        "event": "PostToolUse",
        "matcher": "Edit|Write",
        "entry": _script_entry("warn-missing-tests.sh"),
        "script": "warn-missing-tests.sh",
        "data_access": "checks for a convention-named test file next to the edited source; "
        "advisory only",
    },
    "audit-log": {
        "event": "PostToolUse",
        "matcher": "",
        "entry": _script_entry("audit-log.sh"),
        "script": "audit-log.sh",
        "data_access": "appends timestamp|tool|target lines to .claude/state/audit.log; local "
        "only, never leaves the machine",
    },
    "lint-fix": {
        "event": "Stop",
        "matcher": "",
        "entry": _script_entry("lint-fix.sh"),
        "script": "lint-fix.sh",
        "data_access": "runs the project's own linter/formatter on the working tree; best-effort, "
        "may request one guarded Stop continuation when issues remain",
    },
    "type-check": {
        "event": "Stop",
        "matcher": "",
        "entry": _script_entry("type-check.sh"),
        "script": "type-check.sh",
        "data_access": "runs the project's own type checker; best-effort, may request one guarded "
        "Stop continuation when issues remain",
    },
    # The write half of the continuity pair. load-continuity reads working memory at SessionStart;
    # until this hook there was no mechanism behind rarv-cycle.md's "update CONTINUITY.md with what
    # passed", and the behaviour was observed 0/12 even with rarv-cycle as the only rule loaded.
    "verify-continuity-writeback": {
        "event": "Stop",
        "matcher": "",
        "entry": _script_entry("verify-continuity-writeback.sh"),
        "script": "verify-continuity-writeback.sh",
        "data_access": "reads `git status` and file mtimes to tell whether CONTINUITY.md was "
        "written after the session's changes; may request one guarded Stop continuation, writes "
        "nothing",
    },
    # --- learning capture: one script, three triggers, chosen by capture_mode (catalog/capture.yaml).
    # Never put these in a profile's hooks: list or rely on the `all` token — catalog._apply_capture_mode
    # is the sole installer (it strips all three, then adds back the chosen mode's set).
    # SessionEnd's default budget is 1.5s; the per-hook timeout below raises it on the settings
    # channel (belt-and-suspenders — the script itself returns in ms since the transcript scan
    # moved into the detached background job). Plugin-channel timeouts don't raise the budget.
    "capture-learnings": {
        "event": "SessionEnd",
        "matcher": "",
        "entry": _script_entry("capture-learnings.sh", "end", timeout=30),
        "script": "capture-learnings.sh",
        "arg": "end",
        "timeout": 30,
        "data_access": "SPAWNS A DETACHED PROVIDER-SELECTED BACKGROUND JOB on clean session exit; "
        "Claude mode reads the session transcript and changed files, while the Codex coordinator "
        "sends only bounded sensitive-path-filtered/redacted changed-file diff context to a "
        "read-only classifier; durable output goes to the shared agent-memory store and reaches "
        "the selected model provider; opt-in at init (capture_mode)",
    },
    "capture-learnings-catchup": {
        "event": "SessionStart",
        "matcher": "",
        "entry": _script_entry("capture-learnings.sh", "catchup"),
        "script": "capture-learnings.sh",
        "arg": "catchup",
        "data_access": "Claude uses the same background capture job on next launch for sessions "
        "that ended abruptly; Codex has no stable historical transcript contract and safely "
        "no-ops; opt-in at init (capture_mode)",
    },
    "capture-learnings-stop": {
        "event": "Stop",
        "matcher": "",
        "entry": _script_entry("capture-learnings.sh", "stop"),
        "script": "capture-learnings.sh",
        "arg": "stop",
        "data_access": "same background capture job as capture-learnings, fired after each "
        "file-editing task (highest token cost); opt-in at init (capture_mode)",
    },
    # Keeps ticket token/model/timing figures in the repo after the session transcript they were
    # derived from is gone. Self-throttling and detached, so the per-turn cost is ~nothing.
    "capture-ticket-telemetry": {
        "event": "Stop",
        "matcher": "",
        "entry": _script_entry("capture-ticket-telemetry.sh"),
        "script": "capture-ticket-telemetry.sh",
        "arg": "",
        "data_access": "spawns a detached local job reading transcript *metadata only* (tokens, "
        "model, agent, branch — never message content) into docs/project/tickets/; no LLM call",
    },
}

#: Hooks the plugin ships but the pip CLI does NOT — the single declared exception to "the registry
#: is the source of truth". These run from the auto-discovered ``hooks/hooks.json`` only; they are
#: deliberately absent from ``HOOK_REGISTRY`` / ``catalog/profiles.yaml`` so ``claude-kit init`` output
#: is unchanged. Each entry carries a ``reason`` so the divergence is documented data, not an accident.
PLUGIN_ONLY_HOOKS: dict[str, dict[str, Any]] = {
    "guard-kubectl-delete": {
        "event": "PreToolUse",
        "matcher": "Bash",
        "script": "guard-kubectl-delete.sh",
        "arg": "",
        "data_access": "inspects the Bash command JSON on stdin to block kubectl delete; reads "
        "no files",
        "reason": (
            "Blocks destructive `kubectl delete` from the agent's Bash tool. Plugin-only by design: "
            "intentionally not added to the CLI scaffold registry / profiles, so `claude-kit init` "
            "output is unchanged (see PR #25)."
        ),
    },
}


# Provider-neutral hook contract ---------------------------------------------------------------
#
# ``HOOK_REGISTRY`` remains the compatibility adapter consumed by the historical Claude renderer
# and by profile resolution.  Every entry is enriched below with the semantic fields used by the
# projection compiler.  ``HOOK_SPECS`` is the typed, provider-neutral view; renderers must use it
# for event/effect/matcher decisions and use the legacy ``entry`` only when producing Claude's
# backwards-compatible command document.
_SEMANTIC_EVENTS: dict[str, HookEvent] = {
    "SessionStart": HookEvent.SESSION_START,
    "UserPromptSubmit": HookEvent.USER_PROMPT,
    "PreToolUse": HookEvent.PRE_TOOL,
    "PostToolUse": HookEvent.POST_TOOL,
    "PostToolUseFailure": HookEvent.TOOL_FAILURE,
    "Stop": HookEvent.STOP,
    "SubagentStart": HookEvent.SUBAGENT_START,
    "SubagentStop": HookEvent.SUBAGENT_STOP,
    "PreCompact": HookEvent.PRE_COMPACT,
    "SessionEnd": HookEvent.SESSION_END,
    "Notification": HookEvent.NOTIFICATION,
}

_SEMANTIC_MATCHERS: dict[str, str | None] = {
    "": None,
    "Bash": "shell",
    "Read": "file-read",
    "Write": "file-write|apply-patch",
    "Edit|Write": "file-edit|file-write|apply-patch",
}

_CODEX_PLUGIN_EVENTS: dict[HookEvent, str] = {
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

_CODEX_PLUGIN_MATCHERS: dict[str | None, str] = {
    None: "",
    "shell": "Bash|exec_command|shell|unified_exec",
    "file-read": "Read|read_file",
    "file-read|shell": "Read|read_file|Bash|exec_command|shell|unified_exec",
    "file-write|apply-patch": "Write|apply_patch",
    "file-edit|file-write|apply-patch": "Edit|MultiEdit|Write|apply_patch",
}

_BLOCKING_HOOK_IDS = frozenset(
    {
        "guard-rm-rf",
        "guard-push-main",
        "guard-destructive-git",
        "protect-secrets",
        "guard-commit-secrets",
        "validate-settings",
        "guard-kubectl-delete",
        "lint-fix",
        "type-check",
        "verify-continuity-writeback",
    }
)

_INFO_HOOK_IDS = frozenset(
    {
        "load-continuity",
        "load-learnings",
        "load-autonomy",
        "audit-log",
        "capture-learnings",
        "capture-learnings-catchup",
        "capture-learnings-stop",
        "capture-ticket-telemetry",
    }
)


def _semantic_action(hook_id: str, record: dict[str, Any]) -> SymbolicRef:
    """Return a stable handler reference, independent of script names and provider paths."""

    # Several capture triggers deliberately share one implementation.  The logical hook id remains
    # part of the action so provider adapters can retain its mode without leaking a shell argument
    # into the canonical HookSpec.
    return SymbolicRef.parse(f"handler://{hook_id}")


def _build_hook_specs() -> dict[str, HookSpec]:
    """Build and validate the typed semantic registry, including plugin-only hooks."""

    specs: dict[str, HookSpec] = {}
    for hook_id, record in {**HOOK_REGISTRY, **PLUGIN_ONLY_HOOKS}.items():
        wire_event = str(record.get("event", ""))
        matcher = str(record.get("matcher", ""))
        if wire_event not in _SEMANTIC_EVENTS:
            raise ValueError(f"hook {hook_id!r} has unsupported event {wire_event!r}")
        if matcher not in _SEMANTIC_MATCHERS:
            raise ValueError(f"hook {hook_id!r} has unsupported matcher {matcher!r}")

        effect = (
            HookEffect.BLOCKING
            if hook_id in _BLOCKING_HOOK_IDS
            else HookEffect.ADVISORY
        )
        severity = (
            HookSeverity.ERROR
            if effect is HookEffect.BLOCKING
            else HookSeverity.INFO
            if hook_id in _INFO_HOOK_IDS
            else HookSeverity.WARNING
        )
        data_access = str(record.get("data_access", "")).strip()
        operation_matcher = _SEMANTIC_MATCHERS[matcher]
        if hook_id == "protect-secrets":
            # Codex exposes ordinary local reads through unified shell execution rather than a
            # dedicated Read tool. Claude keeps its native Read matcher; provider renderers map
            # this semantic union onto the complete Codex tool-name set.
            operation_matcher = "file-read|shell"
        spec = HookSpec(
            id=hook_id,
            description=hook_id.replace("-", " "),
            event=_SEMANTIC_EVENTS[wire_event],
            operation_matcher=operation_matcher,
            effect=effect,
            severity=severity,
            action=_semantic_action(hook_id, record),
            data_access=(data_access,) if data_access else (),
            timeout_seconds=int(record.get("timeout", 10)),
        )
        specs[hook_id] = spec

        # Keep old consumers working while making the semantic contract directly inspectable on
        # HOOK_REGISTRY.  Provider renderers must not infer semantics from Claude wire strings.
        record["semantic_event"] = spec.event
        record["operation_matcher"] = spec.operation_matcher
        record["effect"] = spec.effect
        record["severity"] = spec.severity
        record["action"] = spec.action.uri

    return specs


HOOK_SPECS: dict[str, HookSpec] = _build_hook_specs()

#: Which registry hooks each *static* generated file ships (the dynamic per-profile installed
#: settings.json comes from the profile's hook list instead). Declaring channel membership as data —
#: rather than hand-editing two JSON files — is what keeps the plugin file and the legacy static
#: starter template from silently drifting apart; ``scripts/gen_hooks.py`` regenerates both and a
#: drift test enforces it.
#:
#: The plugin file (hooks/hooks.json, always-on for any project using the plugin) carries the broad
#: recommended set plus the plugin-only guards above.
PLUGIN_HOOK_IDS: frozenset[str] = frozenset(
    {
        "load-continuity",
        "load-learnings",
        "load-autonomy",
        "guard-rm-rf",
        "guard-push-main",
        "guard-destructive-git",
        "protect-secrets",
        "guard-commit-secrets",
        "warn-shared-modules",
        "warn-llm-io",
        "warn-sensitive-files",
        "validate-settings",
        "lint-fix",
        "type-check",
        "verify-continuity-writeback",
        # The capture-learnings hooks are DELIBERATELY absent (0.76.0): they spawn a background
        # provider job that reads working context, and the plugin channel has no init
        # question — background capture is consent-gated, so only an explicit `capture_mode`
        # choice at `ckit init` (or a hand-edit of settings.json) enables it. Recall
        # (load-learnings) stays on: reading your own learnings file needs no consent.
    }
)

#: The legacy static starter template (templates/settings.json) carries a smaller subset. It is kept
#: for payload compatibility and registry drift checks; scripts/init.sh is a CLI dispatcher as of
#: 0.83.0 and does not install this template directly.
STARTER_HOOK_IDS: frozenset[str] = frozenset(
    {
        "load-continuity",
        "load-learnings",
        "guard-rm-rf",
        "guard-push-main",
        "warn-shared-modules",
        "lint-fix",
        "type-check",
        "verify-continuity-writeback",
        # capture-learnings hooks deliberately absent — same consent gate as PLUGIN_HOOK_IDS above:
        # the static starter template has no consent question, so background capture stays off.
    }
)

#: $comment headers for the two channels (kept here so generation is the single source).
_INSTALLED_COMMENT = (
    "Claude Code settings installed by claude-kit. Hooks wire the SDLC working-memory, "
    "learnings, guardrails, and quality checks to scripts in .claude/hooks/. Personal "
    "overrides belong in .claude/settings.local.json (gitignored)."
)
_STARTER_COMMENT = (
    "Recommended Claude Code settings installed by claude-kit. Hooks wire the SDLC working-memory, "
    "learnings, guardrails, and quality checks to the scripts in .claude/hooks/. Merge with your "
    "existing settings.json as needed."
)

#: Token-budget defaults baked into every assembled settings.json (the pip-installed file AND the
#: static starter template, since both go through :func:`build_settings`). These trim per-session/per-turn
#: context cost without lowering reasoning on any gate — we deliberately do NOT set
#: ``model``/``effortLevel``/``MAX_THINKING_TOKENS`` here, as those would cut capability on the
#: judgment-heavy review/security stages.
#:  - ``env.CLAUDE_CODE_DISABLE_TERMINAL_TITLE`` skips the background Haiku title request in
#:    headless/subagent runs (the SDLC pipeline spawns many subagents).
#:  - ``autoCompactEnabled`` is already the Claude Code default; set explicitly because the kit's
#:    CONTINUITY-survives-compaction design depends on auto-compaction staying on.
#:  - ``maxSkillDescriptionChars`` bounds the per-turn skill listing; 1100 sits above the kit's
#:    longest current skill description (~973 chars) so nothing truncates today while capping growth.
_TOKEN_BUDGET: dict[str, Any] = {
    "env": {"CLAUDE_CODE_DISABLE_TERMINAL_TITLE": "1"},
    "autoCompactEnabled": True,
    "maxSkillDescriptionChars": 1100,
}

#: Event ordering for a stable, readable settings.json.
_EVENT_ORDER = (
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "Stop",
    "SessionEnd",
)


def all_ids() -> list[str]:
    """Return every hook id, in registry order (used to expand the ``all`` profile token)."""
    return list(HOOK_REGISTRY)


def scripts_for(hook_ids: list[str]) -> list[str]:
    """Return the script basenames needed by ``hook_ids`` (inline/prompt hooks contribute none)."""
    out: list[str] = []
    for hid in hook_ids:
        spec = HOOK_REGISTRY.get(hid)
        if spec and spec["script"]:
            out.append(spec["script"])
    return sorted(set(out))


def _hooks_block(specs: list[tuple[str, str, dict[str, Any]]]) -> dict[str, Any]:
    """Group ``(event, matcher, entry)`` specs into the ``{EVENT: [{matcher, hooks}]}`` schema.

    Order is preserved from ``specs`` (callers pass them in registry order), with events sorted by
    :data:`_EVENT_ORDER`. This is the one place the settings/hooks schema is assembled, shared by the
    installed-settings, plugin, and starter generators so all three stay byte-identical in shape.
    """
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for event, matcher, entry in specs:
        grouped.setdefault(event, {}).setdefault(matcher, []).append(entry)
    ordered_events = [e for e in _EVENT_ORDER if e in grouped] + [
        e for e in grouped if e not in _EVENT_ORDER
    ]
    return {
        event: [
            {"matcher": matcher, "hooks": entries}
            for matcher, entries in grouped[event].items()
        ]
        for event in ordered_events
    }


def build_settings(
    hook_ids: list[str], *, comment: str | None = None
) -> dict[str, Any]:
    """Assemble an installed ``.claude/settings.json`` document from the selected hook ids.

    Groups the selected hooks by event and matcher, preserving registry order, into the schema
    Claude Code expects (``{"hooks": {EVENT: [{"matcher": …, "hooks": [entry, …]}]}}``). Uses the
    project-relative script paths (``${CLAUDE_PROJECT_DIR}/.claude/hooks/…``).

    Args:
        hook_ids: Hook ids to enable.
        comment: Optional ``$comment`` header (defaults to the installed-settings blurb).

    Returns:
        A JSON-serialisable settings mapping (always includes an explanatory ``$comment``).
    """
    specs = [
        (
            HOOK_REGISTRY[hid]["event"],
            HOOK_REGISTRY[hid]["matcher"],
            HOOK_REGISTRY[hid]["entry"],
        )
        for hid in HOOK_REGISTRY
        if hid in set(hook_ids)
    ]
    return {
        "$comment": comment or _INSTALLED_COMMENT,
        **_TOKEN_BUDGET,
        "hooks": _hooks_block(specs),
    }


def generate_starter_settings() -> dict[str, Any]:
    """Generate legacy static ``templates/settings.json`` from :data:`STARTER_HOOK_IDS`."""
    return build_settings(sorted(STARTER_HOOK_IDS), comment=_STARTER_COMMENT)


def _generate_plugin_hooks_json(
    entry_builder: Callable[[str, str, int | None], dict[str, Any]],
    *,
    codex_native: bool = False,
) -> dict[str, Any]:
    """Build one provider plugin hook document with provider-specific script entries."""
    specs: list[tuple[str, str, dict[str, Any]]] = []
    for hid in HOOK_REGISTRY:
        if hid not in PLUGIN_HOOK_IDS:
            continue
        spec = HOOK_REGISTRY[hid]
        event = spec["event"]
        matcher = spec["matcher"]
        if codex_native:
            semantic = HOOK_SPECS[hid]
            event = _CODEX_PLUGIN_EVENTS[semantic.event]
            matcher = _CODEX_PLUGIN_MATCHERS[semantic.operation_matcher]
            if hid == "protect-secrets":
                # The static plugin is intentionally self-contained and its compatibility inline
                # guard understands native Read envelopes only. Project scaffolds use the exact
                # installed ``ckit hook-run`` adapter and therefore receive the full shell union.
                matcher = _CODEX_PLUGIN_MATCHERS["file-read"]
        if spec["script"]:
            entry = entry_builder(
                spec["script"], spec.get("arg", ""), spec.get("timeout")
            )
        else:
            entry = dict(spec["entry"])
            if codex_native:
                entry["command"] = str(entry["command"]).replace("claude-kit", "ckit")
        specs.append((event, matcher, entry))
    for hook_id, po in PLUGIN_ONLY_HOOKS.items():
        event = po["event"]
        matcher = po["matcher"]
        if codex_native:
            semantic = HOOK_SPECS[hook_id]
            event = _CODEX_PLUGIN_EVENTS[semantic.event]
            matcher = _CODEX_PLUGIN_MATCHERS[semantic.operation_matcher]
        specs.append(
            (
                event,
                matcher,
                entry_builder(po["script"], po.get("arg", ""), po.get("timeout")),
            )
        )
    return {"hooks": _hooks_block(specs)}


def generate_plugin_hooks_json() -> dict[str, Any]:
    """Generate the auto-discovered Claude plugin ``hooks/hooks.json``.

    Ships :data:`PLUGIN_HOOK_IDS` (rebuilt with ``${CLAUDE_PLUGIN_ROOT}`` script paths; inline guard
    commands are path-independent and reused verbatim) plus :data:`PLUGIN_ONLY_HOOKS`, which are
    appended after the registry hooks within their event/matcher group. No ``$comment`` (the plugin
    loader reads this as a hooks fragment).
    """
    return _generate_plugin_hooks_json(_plugin_entry)


def generate_codex_plugin_hooks_json() -> dict[str, Any]:
    """Generate the auto-discovered native Codex plugin ``hooks/hooks.json``.

    The semantic roster and ordering are identical to the Claude plugin channel. Only script-root
    expansion differs: Codex resolves scripts through ``${PLUGIN_ROOT}``.
    """
    return _generate_plugin_hooks_json(_codex_plugin_entry, codex_native=True)


def plugin_script_names() -> tuple[str, ...]:
    """Return the exact script inventory required by either static plugin hook document."""
    records = {**HOOK_REGISTRY, **PLUGIN_ONLY_HOOKS}
    hook_ids = [hid for hid in HOOK_REGISTRY if hid in PLUGIN_HOOK_IDS]
    hook_ids.extend(PLUGIN_ONLY_HOOKS)
    return tuple(
        sorted(
            {
                str(records[hid]["script"])
                for hid in hook_ids
                if records[hid].get("script")
            }
        )
    )


def _hook_id_for_command(command: str) -> str | None:
    """Map an installed settings.json hook command back to its registry id.

    An exact entry-command match wins (it disambiguates the three capture triggers that share one
    script). The fallback requires an exact script **basename token** — never a substring — so a
    lookalike command (``.../load-learnings.sh.bak``, ``.../capture-learnings.sh-evil/x.sh``)
    is NOT claimed as a kit hook and privacy-report lists it for the user's own review. Plugin
    ``${CLAUDE_PLUGIN_ROOT}`` paths still match: their basename is the registry script name.
    """
    for hid, spec in HOOK_REGISTRY.items():
        if spec["entry"].get("command") == command:
            return hid
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    if tokens and Path(tokens[0]).name in {"ckit", "claude-kit", "claude-sdlc"}:
        try:
            hook_run = tokens.index("hook-run")
            hook_id = tokens[tokens.index("--hook-id", hook_run + 1) + 1]
        except (ValueError, IndexError):
            pass
        else:
            if hook_id in {**HOOK_REGISTRY, **PLUGIN_ONLY_HOOKS}:
                return hook_id
    basenames = {Path(tok).name for tok in tokens}
    for hid, spec in {**HOOK_REGISTRY, **PLUGIN_ONLY_HOOKS}.items():
        script = spec.get("script")
        if script and script in basenames:
            arg = spec.get("arg", "")
            if not arg or (tokens and tokens[-1] == arg):
                return hid
    return None


def privacy_report(target: str | Path = ".") -> tuple[bool, list[str]]:
    """Report every installed hook's data access — the informed-consent view of a config.

    Reads each configured runtime's hook document and prints, per hook, its registry id, event, and
    the ``data_access`` note from :data:`HOOK_REGISTRY` — what it reads, what it writes, and whether
    it spawns a background job or sends session content to the model provider. State references in
    those notes are projected through the active :class:`StateLayout`, so a Codex or dual install
    discloses its shared ``.ckit`` memory and state rather than a nonexistent provider-local copy.
    Hook commands the registry doesn't recognise are listed for the user's own review, never
    explained away. Without an installed hook document it describes the static Claude plugin roster
    (:data:`PLUGIN_HOOK_IDS` + :data:`PLUGIN_ONLY_HOOKS`) instead.
    """
    combined = {**HOOK_REGISTRY, **PLUGIN_ONLY_HOOKS}
    fs = ProjectFS(Path(target).expanduser())
    layout = detect_state_layout(fs.root, fresh_default=StateLayout.legacy_claude())

    def state_access(access: str) -> str:
        """Render legacy registry notes against the discovered shared-state layout."""

        replacements = (
            (".claude/CONTINUITY.md", layout.continuity),
            (".claude/agent-memory/", f"{layout.memory}/"),
            (".claude/artifacts/", f"{layout.artifacts}/"),
            (".claude/state/", f"{layout.state}/"),
        )
        for legacy, active in replacements:
            access = access.replace(legacy, active)
        return access

    def line(hid: str, event: str) -> str:
        access = (
            combined.get(hid, {}).get("data_access") or "(no data-access note recorded)"
        )
        return f"{hid:<26} {event:<12} {state_access(str(access))}"

    msgs: list[str] = []
    runtimes: list[str] | None = None
    manifest_present = fs.is_file(layout.manifest)
    if manifest_present:
        try:
            manifest = json.loads(fs.read_text(layout.manifest))
            runtimes = InitOptions.from_dict(manifest).runtimes
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            return False, [
                f"FAIL  {layout.manifest} is not valid init-options JSON: {exc}"
            ]

    if runtimes is not None:
        candidates = []
        if "claude" in runtimes:
            candidates.append(".claude/settings.json")
        if "codex" in runtimes:
            candidates.append(".codex/hooks.json")
    else:
        # Compatibility for hand-installed/pre-manifest configs. Once a manifest exists, runtime
        # comes only from that metadata and never from provider-directory presence.
        candidates = [
            rel
            for rel in (".claude/settings.json", ".codex/hooks.json")
            if fs.is_file(rel)
        ]

    settings_rels = [rel for rel in candidates if fs.is_file(rel)]
    missing_settings = [rel for rel in candidates if rel not in settings_rels]
    if not settings_rels:
        if manifest_present:
            expected = ", ".join(candidates) or "a runtime hook document"
            return False, [
                f"FAIL  installed runtime hook document is missing (expected {expected})"
            ]
        msgs.append(
            "no installed runtime hook document here — showing the Claude plugin channel's "
            "static hook set (hooks/hooks.json)"
        )
        msgs.append("")
        for hid in HOOK_REGISTRY:
            if hid in PLUGIN_HOOK_IDS:
                msgs.append(line(hid, HOOK_REGISTRY[hid]["event"]))
        for hid, spec in PLUGIN_ONLY_HOOKS.items():
            msgs.append(line(hid, spec["event"]))
        msgs.append("")
        msgs.append(
            "OK    background learning capture: OFF — the plugin ships no capture hooks "
            "(consent-gated); enable it by scaffolding with `claude-kit init` and choosing a "
            "Learning capture mode"
        )
        return True, msgs

    installed: list[tuple[str, str]] = []
    unknown: list[tuple[str, str, str]] = []
    for settings_rel in settings_rels:
        try:
            data = json.loads(fs.read_text(settings_rel))
        except json.JSONDecodeError as exc:
            return False, [f"FAIL  {fs.path(settings_rel)} is not valid JSON: {exc}"]
        hooks_block = data.get("hooks") if isinstance(data, dict) else None
        for event, blocks in (hooks_block or {}).items():
            if not isinstance(blocks, list):
                continue
            for block in blocks:
                entries = block.get("hooks", []) if isinstance(block, dict) else []
                for entry in entries:
                    cmd = entry.get("command", "") if isinstance(entry, dict) else ""
                    matched = _hook_id_for_command(cmd)
                    if matched:
                        pair = (event, matched)
                        if pair not in installed:
                            installed.append(pair)
                    else:
                        unknown.append((settings_rel, event, cmd))

    rendered_settings = ", ".join(str(fs.path(rel)) for rel in settings_rels)
    msgs.append(f"privacy report — {rendered_settings}")
    if manifest_present:
        msgs.append(
            f"INFO  shared control plane: memory={layout.memory}/; state={layout.state}/; "
            f"continuity={layout.continuity}"
        )
    for missing in missing_settings:
        msgs.append(
            f"WARN  installed runtime hook document is missing: {missing}; "
            "privacy coverage is incomplete"
        )
    msgs.append("")
    for event, hid in installed:
        msgs.append(line(hid, event))
    for settings_rel, event, cmd in unknown:
        msgs.append(
            f"{'(not a claude-kit hook)':<26} {event:<12} {cmd[:90]} — not from this kit "
            f"({settings_rel}); review it yourself"
        )

    capture_on = sorted(
        {hid for _e, hid in installed if hid.startswith("capture-learnings")}
    )
    msgs.append("")
    # OK/WARN prefixes make the ON/OFF state machine-readable via `--json` (Report levels),
    # not just a substring in prose.
    if capture_on:
        active_runtimes = set(runtimes or [])
        if not active_runtimes:
            active_runtimes = {
                "codex" if rel.startswith(".codex/") else "claude"
                for rel in settings_rels
            }
        if active_runtimes == {"codex"}:
            access = (
                "a sandboxed Codex background task reads the repository changed-path set; "
                "historical transcript catch-up is not assumed"
            )
        elif active_runtimes == {"claude"}:
            access = (
                "a detached Claude background task reads bounded session transcript content "
                "and changed files"
            )
        else:
            access = (
                "a provider-selected background task reads bounded Claude transcript content "
                "or the Codex repository changed-path set, depending on the active host"
            )
        msgs.append(
            f"WARN  background learning capture: ON ({', '.join(capture_on)}) — {access}; "
            f"disable by removing those entries from {', '.join(settings_rels)}, or re-run "
            "`ckit init` and choose 'Off'"
        )
    else:
        msgs.append(
            "OK    background learning capture: OFF — only the local recall hook reads your "
            "learnings file; enable capture at `claude-kit init` (Learning capture question)"
        )
    return True, msgs
