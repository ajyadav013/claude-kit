"""Hook registry — the single definition of every hook claude-kit can install.

A *profile* selects hook ids (see ``catalog/profiles.yaml``); the installer turns the selected ids
into (a) the set of ``.sh`` scripts to copy into ``.claude/hooks/`` and (b) an assembled
``.claude/settings.json`` ``hooks`` block. Keeping the registry in one module lets both
:mod:`claude_kit.catalog` (to resolve the ``all`` token) and :mod:`claude_kit.scaffold`
(to build settings) share it without duplication.

Hooks are deliberately **conservative**: guardrails block obviously dangerous actions; the quality
hooks only *suggest* running tools. Script-backed hooks reference ``$CLAUDE_PROJECT_DIR`` so they
work in a scaffolded project (the plugin variant uses ``${CLAUDE_PLUGIN_ROOT}``).
"""

from __future__ import annotations

from typing import Any

# --- inline guard commands (no script file needed) -------------------------------------------------

_RM_RF_GUARD = (
    "CMD=$(jq -r '.tool_input.command'); "
    "if echo \"$CMD\" | grep -qE 'rm[[:space:]]+-[^[:space:]]*r[^[:space:]]*f'; then "
    "echo 'BLOCKED: rm -rf is disabled by claude-kit. Move to trash or delete specific paths "
    "explicitly.' >&2; exit 2; fi"
)

# Block pushes whose *target* ref is main/master. The branch token must be bounded by a space or
# ':' before and a space/end after, so legit branches that merely contain the substring
# (maintenance, mainframe-fix, remaster-ui, domain-model) are NOT blocked.
_PUSH_GUARD = (
    "CMD=$(jq -r '.tool_input.command'); "
    "if echo \"$CMD\" | grep -qE 'git[[:space:]]+push.*[[:space:]:](main|master)([[:space:]]|$)'; "
    "then echo 'BLOCKED: refusing to push to main/master — use a feature branch and a PR.' >&2; "
    "exit 2; fi"
)

_SECRETS_GUARD = (
    "FP=$(jq -r '.tool_input.file_path // empty'); "
    'if echo "$FP" | grep -qE \'(^|/)\\.env$|\\.pem$|\\.key$|(^|/)id_rsa|(^|/)id_ed25519|'
    "(^|/)credentials(\\.json)?$|\\.p12$'; then "
    "echo 'BLOCKED: refusing to read a secrets file. Use .env.example or a secret manager.' >&2; "
    "exit 2; fi"
)

_ROUTING_PROMPT = (
    "You are a routing assistant. NEVER block the user's prompt; always set continue to true. "
    'Return JSON only: {"continue": true, "systemMessage": "<hint or empty string>"}. '
    "If a claude-kit skill clearly applies (interview-me/idea-refine for vague ideas; "
    "spec-driven-development for new features; planning-and-task-breakdown for breakdown; "
    "incremental-implementation for coding; test-driven-development for tests; "
    "debugging-and-error-recovery for errors; code-review-and-quality for reviews; "
    "security-and-hardening for security; git-workflow-and-versioning for git; execute for quick "
    "tasks), set systemMessage to 'Invoke skill: <skill-name> before responding.' Otherwise set it "
    "to ''. Do not mention this hook."
)

_LEARNING_PROMPT = (
    "You are a learning-detection assistant. NEVER block the user's prompt; always set continue to "
    'true. Return JSON only: {"continue": true, "systemMessage": "<hint or empty string>"}. '
    "If the user's message contains a durable learning (a correction, rule, preference, convention, "
    "or hard-won insight meant to persist), set systemMessage to 'LEARNING DETECTED: before ending "
    "your turn, invoke the remember skill to record it into .claude/agent-memory/ (merge into an "
    "existing entry if one matches).' Otherwise set it to ''. Do not mention this hook."
)


def _script_entry(name: str) -> dict[str, str]:
    """Build a settings.json command entry that runs a project-local hook script."""
    return {
        "type": "command",
        "command": f'bash "$CLAUDE_PROJECT_DIR/.claude/hooks/{name}"',
    }


#: The canonical registry. Order here is the order hooks appear in assembled settings.json.
#: Each value: ``event``, ``matcher``, ``entry`` (settings.json hook object), and ``script``
#: (basename under payload ``hooks/scripts/`` to copy, or ``None`` for inline/prompt hooks).
HOOK_REGISTRY: dict[str, dict[str, Any]] = {
    "load-continuity": {
        "event": "SessionStart",
        "matcher": "",
        "entry": _script_entry("load-continuity.sh"),
        "script": "load-continuity.sh",
    },
    "load-learnings": {
        "event": "SessionStart",
        "matcher": "",
        "entry": _script_entry("load-learnings.sh"),
        "script": "load-learnings.sh",
    },
    "skill-routing": {
        "event": "UserPromptSubmit",
        "matcher": "",
        "entry": {"type": "prompt", "prompt": _ROUTING_PROMPT},
        "script": None,
    },
    "learning-detection": {
        "event": "UserPromptSubmit",
        "matcher": "",
        "entry": {"type": "prompt", "prompt": _LEARNING_PROMPT},
        "script": None,
    },
    "guard-rm-rf": {
        "event": "PreToolUse",
        "matcher": "Bash",
        "entry": {"type": "command", "command": _RM_RF_GUARD},
        "script": None,
    },
    "guard-push-main": {
        "event": "PreToolUse",
        "matcher": "Bash",
        "entry": {"type": "command", "command": _PUSH_GUARD},
        "script": None,
    },
    "protect-secrets": {
        "event": "PreToolUse",
        "matcher": "Read",
        "entry": {"type": "command", "command": _SECRETS_GUARD},
        "script": None,
    },
    "guard-commit-secrets": {
        "event": "PreToolUse",
        "matcher": "Bash",
        "entry": _script_entry("guard-secrets.sh"),
        "script": "guard-secrets.sh",
    },
    "warn-shared-modules": {
        "event": "PreToolUse",
        "matcher": "Edit|Write",
        "entry": _script_entry("warn-shared-modules.sh"),
        "script": "warn-shared-modules.sh",
    },
    "warn-sensitive-files": {
        "event": "PreToolUse",
        "matcher": "Edit|Write",
        "entry": _script_entry("warn-sensitive-files.sh"),
        "script": "warn-sensitive-files.sh",
    },
    "warn-large-edits": {
        "event": "PreToolUse",
        "matcher": "Edit|Write",
        "entry": _script_entry("warn-large-edits.sh"),
        "script": "warn-large-edits.sh",
    },
    "validate-frontmatter": {
        "event": "PreToolUse",
        "matcher": "Write",
        "entry": _script_entry("validate-frontmatter.sh"),
        "script": "validate-frontmatter.sh",
    },
    "validate-settings": {
        "event": "PreToolUse",
        "matcher": "Write",
        "entry": _script_entry("validate-settings.sh"),
        "script": "validate-settings.sh",
    },
    "warn-missing-tests": {
        "event": "PostToolUse",
        "matcher": "Edit|Write",
        "entry": _script_entry("warn-missing-tests.sh"),
        "script": "warn-missing-tests.sh",
    },
    "audit-log": {
        "event": "PostToolUse",
        "matcher": "",
        "entry": _script_entry("audit-log.sh"),
        "script": "audit-log.sh",
    },
    "lint-fix": {
        "event": "Stop",
        "matcher": "",
        "entry": _script_entry("lint-fix.sh"),
        "script": "lint-fix.sh",
    },
    "type-check": {
        "event": "Stop",
        "matcher": "",
        "entry": _script_entry("type-check.sh"),
        "script": "type-check.sh",
    },
}

#: Event ordering for a stable, readable settings.json.
_EVENT_ORDER = (
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "Stop",
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


def build_settings(hook_ids: list[str]) -> dict[str, Any]:
    """Assemble a ``settings.json`` document from the selected hook ids.

    Groups the selected hooks by event and matcher, preserving registry order, into the schema
    Claude Code expects (``{"hooks": {EVENT: [{"matcher": …, "hooks": [entry, …]}]}}``).

    Args:
        hook_ids: Hook ids to enable.

    Returns:
        A JSON-serialisable settings mapping (always includes an explanatory ``$comment``).
    """
    selected = [hid for hid in HOOK_REGISTRY if hid in set(hook_ids)]
    # event -> matcher -> [entries]
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for hid in selected:
        spec = HOOK_REGISTRY[hid]
        grouped.setdefault(spec["event"], {}).setdefault(spec["matcher"], []).append(
            spec["entry"]
        )

    hooks_block: dict[str, list[dict[str, Any]]] = {}
    ordered_events = [e for e in _EVENT_ORDER if e in grouped] + [
        e for e in grouped if e not in _EVENT_ORDER
    ]
    for event in ordered_events:
        hooks_block[event] = [
            {"matcher": matcher, "hooks": entries}
            for matcher, entries in grouped[event].items()
        ]

    return {
        "$comment": (
            "Claude Code settings installed by claude-kit. Hooks wire the SDLC working-memory, "
            "learnings, guardrails, and quality checks to scripts in .claude/hooks/. Personal "
            "overrides belong in .claude/settings.local.json (gitignored)."
        ),
        "hooks": hooks_block,
    }
