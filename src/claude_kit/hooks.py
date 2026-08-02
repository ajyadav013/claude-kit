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
        "data_access": "inspects the Read file *path* to block secrets files (.env, keys, "
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
        "never blocks",
    },
    "type-check": {
        "event": "Stop",
        "matcher": "",
        "entry": _script_entry("type-check.sh"),
        "script": "type-check.sh",
        "data_access": "runs the project's own type checker; best-effort, never blocks",
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
        "data_access": "SPAWNS A DETACHED BACKGROUND `claude` JOB on clean session exit that "
        "reads the session transcript and changed files to distill learnings into "
        ".claude/agent-memory/ — session content reaches your model provider; opt-in at init "
        "(capture_mode), off unless you chose it",
    },
    "capture-learnings-catchup": {
        "event": "SessionStart",
        "matcher": "",
        "entry": _script_entry("capture-learnings.sh", "catchup"),
        "script": "capture-learnings.sh",
        "arg": "catchup",
        "data_access": "same background capture job as capture-learnings, fired on next launch "
        "for sessions that ended abruptly; opt-in at init (capture_mode)",
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
        # The capture-learnings hooks are DELIBERATELY absent (0.76.0): they spawn a background
        # `claude` job that reads session transcript content, and the plugin channel has no init
        # question — background capture is consent-gated, so only an explicit `capture_mode`
        # choice at `claude-kit init` (or a hand-edit of settings.json) enables it. Recall
        # (load-learnings) stays on: reading your own learnings file needs no consent.
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
        # capture-learnings hooks deliberately absent — same consent gate as PLUGIN_HOOK_IDS above:
        # the no-pip starter is copied without an init question, so background capture stays off.
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

    Reads the target's ``.claude/settings.json`` (the scaffolded channel) and prints, per hook:
    its registry id, event, and the ``data_access`` note from :data:`HOOK_REGISTRY` — what it
    reads, what it writes, and whether it spawns a background job or sends session content to the
    model provider. Hook commands the registry doesn't recognise are listed for the user's own
    review, never explained away. Without a settings.json it describes the static plugin roster
    (:data:`PLUGIN_HOOK_IDS` + :data:`PLUGIN_ONLY_HOOKS`) instead — the set any project using the
    plugin channel gets.
    """
    combined = {**HOOK_REGISTRY, **PLUGIN_ONLY_HOOKS}

    def line(hid: str, event: str) -> str:
        access = (
            combined.get(hid, {}).get("data_access") or "(no data-access note recorded)"
        )
        return f"{hid:<26} {event:<12} {access}"

    msgs: list[str] = []
    settings = Path(target).expanduser().resolve() / ".claude" / "settings.json"
    if not settings.is_file():
        msgs.append(
            "no .claude/settings.json here — showing the plugin channel's static hook set "
            "(hooks/hooks.json)"
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

    try:
        data = json.loads(settings.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return False, [f"FAIL  {settings} is not valid JSON: {exc}"]

    installed: list[tuple[str, str]] = []
    unknown: list[tuple[str, str]] = []
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
                    installed.append((event, matched))
                else:
                    unknown.append((event, cmd))

    msgs.append(f"privacy report — {settings}")
    msgs.append("")
    for event, hid in installed:
        msgs.append(line(hid, event))
    for event, cmd in unknown:
        msgs.append(
            f"{'(not a claude-kit hook)':<26} {event:<12} {cmd[:90]} — not from this kit; "
            "review it yourself"
        )

    capture_on = sorted(
        {hid for _e, hid in installed if hid.startswith("capture-learnings")}
    )
    msgs.append("")
    # OK/WARN prefixes make the ON/OFF state machine-readable via `--json` (Report levels),
    # not just a substring in prose.
    if capture_on:
        msgs.append(
            f"WARN  background learning capture: ON ({', '.join(capture_on)}) — a detached "
            "`claude` job reads session transcript content and changed files; disable by "
            "removing those entries from .claude/settings.json, or re-run `claude-kit init` "
            "and choose 'Off'"
        )
    else:
        msgs.append(
            "OK    background learning capture: OFF — only the local recall hook reads your "
            "learnings file; enable capture at `claude-kit init` (Learning capture question)"
        )
    return True, msgs
