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

from typing import Any

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
    },
    "load-learnings": {
        "event": "SessionStart",
        "matcher": "",
        "entry": _script_entry("load-learnings.sh"),
        "script": "load-learnings.sh",
    },
    "load-autonomy": {
        "event": "SessionStart",
        "matcher": "",
        "entry": _script_entry("load-autonomy.sh"),
        "script": "load-autonomy.sh",
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
        "entry": _script_entry("guard-push-main.sh"),
        "script": "guard-push-main.sh",
    },
    "guard-destructive-git": {
        "event": "PreToolUse",
        "matcher": "Bash",
        "entry": _script_entry("guard-destructive-git.sh"),
        "script": "guard-destructive-git.sh",
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
    "warn-llm-io": {
        "event": "PreToolUse",
        "matcher": "Edit|Write",
        "entry": _script_entry("warn-llm-io.sh"),
        "script": "warn-llm-io.sh",
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
    },
    "capture-learnings-catchup": {
        "event": "SessionStart",
        "matcher": "",
        "entry": _script_entry("capture-learnings.sh", "catchup"),
        "script": "capture-learnings.sh",
        "arg": "catchup",
    },
    "capture-learnings-stop": {
        "event": "Stop",
        "matcher": "",
        "entry": _script_entry("capture-learnings.sh", "stop"),
        "script": "capture-learnings.sh",
        "arg": "stop",
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
        "reason": (
            "Blocks destructive `kubectl delete` from the agent's Bash tool. Plugin-only by design: "
            "intentionally not added to the CLI scaffold registry / profiles, so `claude-kit init` "
            "output is unchanged (see PR #25)."
        ),
    },
}

#: Which registry hooks each *static* generated file ships (the dynamic per-profile installed
#: settings.json comes from the profile's hook list instead). Declaring channel membership as data —
#: rather than hand-editing two JSON files — is what keeps the plugin file and the no-pip starter from
#: silently drifting apart; ``scripts/gen_hooks.py`` regenerates both and a drift test enforces it.
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
        "capture-learnings",
        "capture-learnings-catchup",
    }
)

#: The thin no-pip starter (templates/settings.json, copied by scripts/init.sh) ships a smaller subset
#: — the degraded fallback path keeps a minimal, broadly-safe set rather than the full plugin roster.
STARTER_HOOK_IDS: frozenset[str] = frozenset(
    {
        "load-continuity",
        "load-learnings",
        "guard-rm-rf",
        "guard-push-main",
        "warn-shared-modules",
        "lint-fix",
        "type-check",
        "capture-learnings",
        "capture-learnings-catchup",
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
#: no-pip starter, since both go through :func:`build_settings`). These trim per-session/per-turn
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
    """Generate the thin no-pip starter ``templates/settings.json`` from :data:`STARTER_HOOK_IDS`."""
    return build_settings(sorted(STARTER_HOOK_IDS), comment=_STARTER_COMMENT)


def generate_plugin_hooks_json() -> dict[str, Any]:
    """Generate the auto-discovered plugin ``hooks/hooks.json`` from the registry.

    Ships :data:`PLUGIN_HOOK_IDS` (rebuilt with ``${CLAUDE_PLUGIN_ROOT}`` script paths; inline guard
    commands are path-independent and reused verbatim) plus :data:`PLUGIN_ONLY_HOOKS`, which are
    appended after the registry hooks within their event/matcher group. No ``$comment`` (the plugin
    loader reads this as a hooks fragment).
    """
    specs: list[tuple[str, str, dict[str, Any]]] = []
    for hid in HOOK_REGISTRY:
        if hid not in PLUGIN_HOOK_IDS:
            continue
        spec = HOOK_REGISTRY[hid]
        if spec["script"]:
            entry = _plugin_entry(
                spec["script"], spec.get("arg", ""), spec.get("timeout")
            )
        else:
            entry = spec["entry"]  # inline command — no path to rewrite
        specs.append((spec["event"], spec["matcher"], entry))
    for po in PLUGIN_ONLY_HOOKS.values():
        specs.append(
            (po["event"], po["matcher"], _plugin_entry(po["script"], po.get("arg", "")))
        )
    return {"hooks": _hooks_block(specs)}
