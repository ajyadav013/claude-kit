"""Provider-neutral command-hook normalization and result rendering.

Claude Code and Codex both send one JSON object to command hooks, but their tool surfaces are not
identical. Claude exposes ``Write``/``Edit``/``Read`` directly; Codex reports local shell work as
``Bash`` and file mutations as ``apply_patch`` with the patch in ``tool_input.command``. This module
normalizes those wire shapes before policy code sees them and renders the policy result back into the
host's event-specific contract.

The runtime deliberately treats ``allow`` as *no opinion*: it never emits a host decision that would
skip the user's normal permission flow. Blocking hooks fail closed when their input or handler is
invalid. Advisory hooks fail open and quietly no-op when an event or output effect is unsupported.

Current host contracts:

* https://code.claude.com/docs/en/hooks
* https://learn.chatgpt.com/docs/hooks
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping

from claude_kit.components import HookEffect, HookEvent


class HookProvider(str, Enum):
    """Hook host whose wire contract should be parsed and emitted."""

    CLAUDE = "claude"
    CODEX = "codex"


class ToolOperation(str, Enum):
    """Portable operation categories exposed to hook policy handlers."""

    NONE = "none"
    SHELL = "shell"
    FILE_READ = "file-read"
    FILE_WRITE = "file-write"
    FILE_EDIT = "file-edit"
    APPLY_PATCH = "apply-patch"
    OTHER = "other"


class HookDisposition(str, Enum):
    """Semantic result returned by a provider-neutral policy handler."""

    ALLOW = "allow"
    ADVISORY = "advisory"
    BLOCK = "block"
    NOOP = "noop"


class HookInputError(ValueError):
    """The host input cannot be safely normalized."""


class UnsupportedHookEvent(HookInputError):
    """The host event has no semantic event in this runtime version."""


@dataclass(frozen=True)
class HookEnvelope:
    """Normalized hook input passed to provider-neutral policy code."""

    provider: HookProvider
    event: HookEvent
    effect: HookEffect
    wire_event: str
    operation: ToolOperation
    tool_name: str | None
    tool_input: Any
    command: str | None
    file_paths: tuple[str, ...]
    write_content: str | None
    cwd: str | None
    session_id: str | None
    plugin_root: Path | None
    raw: Mapping[str, Any]


@dataclass(frozen=True)
class HookDecision:
    """Portable decision from a policy handler.

    ``ALLOW`` means the hook has no objection; the renderer emits no explicit provider permission
    grant, so ordinary permission rules and prompts still apply.
    """

    disposition: HookDisposition
    message: str = ""

    def __post_init__(self) -> None:
        disposition = _coerce_enum(
            HookDisposition, self.disposition, field_name="disposition"
        )
        object.__setattr__(self, "disposition", disposition)
        if not isinstance(self.message, str):
            raise TypeError("message must be a string")
        message = self.message.strip()
        if (
            disposition in (HookDisposition.ADVISORY, HookDisposition.BLOCK)
            and not message
        ):
            raise ValueError(f"{disposition.value} decisions require a message")
        object.__setattr__(self, "message", message)

    @classmethod
    def allow(cls) -> HookDecision:
        return cls(HookDisposition.ALLOW)

    @classmethod
    def advisory(cls, message: str) -> HookDecision:
        return cls(HookDisposition.ADVISORY, message)

    @classmethod
    def block(cls, reason: str) -> HookDecision:
        return cls(HookDisposition.BLOCK, reason)

    @classmethod
    def noop(cls) -> HookDecision:
        return cls(HookDisposition.NOOP)


@dataclass(frozen=True)
class HookRunResult:
    """Process-level output a thin command-hook adapter can write and exit with."""

    exit_code: int
    stdout: str
    stderr: str
    disposition: HookDisposition
    envelope: HookEnvelope | None = None


HookHandler = Callable[[HookEnvelope], HookDecision]


_WIRE_EVENTS: dict[str, HookEvent] = {
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

# The semantic model intentionally excludes host-only events until a portable meaning is defined.
# In particular, Codex PermissionRequest and PostCompact remain unsupported here.
_PROVIDER_EVENTS: dict[HookProvider, frozenset[HookEvent]] = {
    HookProvider.CLAUDE: frozenset(HookEvent),
    HookProvider.CODEX: frozenset(
        {
            HookEvent.SESSION_START,
            HookEvent.USER_PROMPT,
            HookEvent.PRE_TOOL,
            HookEvent.POST_TOOL,
            HookEvent.STOP,
            HookEvent.SUBAGENT_START,
            HookEvent.SUBAGENT_STOP,
            HookEvent.PRE_COMPACT,
            HookEvent.SESSION_END,
        }
    ),
}

# Events on which the current hosts accept advisory output. SessionEnd and Notification discard
# steering output, so advisory handlers deliberately no-op there.
_ADVISORY_OUTPUT_EVENTS: dict[HookProvider, frozenset[HookEvent]] = {
    HookProvider.CLAUDE: frozenset(
        {
            HookEvent.SESSION_START,
            HookEvent.USER_PROMPT,
            HookEvent.PRE_TOOL,
            HookEvent.POST_TOOL,
            HookEvent.TOOL_FAILURE,
            HookEvent.STOP,
            HookEvent.SUBAGENT_START,
            HookEvent.SUBAGENT_STOP,
            HookEvent.PRE_COMPACT,
        }
    ),
    HookProvider.CODEX: frozenset(
        {
            HookEvent.SESSION_START,
            HookEvent.USER_PROMPT,
            HookEvent.PRE_TOOL,
            HookEvent.POST_TOOL,
            HookEvent.STOP,
            HookEvent.SUBAGENT_START,
            HookEvent.SUBAGENT_STOP,
            HookEvent.PRE_COMPACT,
        }
    ),
}

# Codex only places advisory text into model context when the event-specific output object carries
# ``additionalContext``. A top-level ``systemMessage`` is merely a UI warning and therefore cannot
# be used as evidence that SessionStart, PreToolUse, PostToolUse, or subagent context reached the
# model. Stop/SubagentStop use the separate top-level decision/reason continuation contract.
_CODEX_ADDITIONAL_CONTEXT_EVENTS = frozenset(
    {
        HookEvent.SESSION_START,
        HookEvent.USER_PROMPT,
        HookEvent.PRE_TOOL,
        HookEvent.POST_TOOL,
        HookEvent.SUBAGENT_START,
    }
)

_TOP_LEVEL_BLOCK_EVENTS = frozenset(
    {
        HookEvent.USER_PROMPT,
        HookEvent.POST_TOOL,
        HookEvent.TOOL_FAILURE,
        HookEvent.STOP,
        HookEvent.SUBAGENT_STOP,
        HookEvent.PRE_COMPACT,
    }
)
_SHELL_TOOLS = frozenset(
    {"Bash", "PowerShell", "exec_command", "shell", "unified_exec"}
)
_READ_TOOLS = frozenset({"Read", "read_file"})
_WRITE_TOOLS = frozenset({"Write"})
_EDIT_TOOLS = frozenset({"Edit", "MultiEdit"})
_APPLY_PATCH_TOOLS = frozenset({"apply_patch"})
_PATCH_PATH_RE = re.compile(
    r"^\*\*\*\s+(?:(?:Add|Update|Delete)\s+File|Move to):\s*(?P<path>.+?)\s*$",
    re.MULTILINE,
)


def _coerce_enum(enum_type, value, *, field_name: str):  # noqa: ANN001, ANN202
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        allowed = ", ".join(item.value for item in enum_type)
        raise ValueError(f"{field_name} must be one of: {allowed}") from exc


def resolve_plugin_root(env: Mapping[str, str] | None = None) -> Path | None:
    """Return the plugin root, preferring Codex's native variable over compatibility fallback."""
    source = os.environ if env is None else env
    for name in ("PLUGIN_ROOT", "CLAUDE_PLUGIN_ROOT"):
        value = source.get(name)
        if isinstance(value, str) and value.strip():
            return Path(value.strip()).expanduser()
    return None


def _parse_document(stdin: str | bytes | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(stdin, Mapping):
        return dict(stdin)
    if isinstance(stdin, bytes):
        try:
            stdin = stdin.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HookInputError("hook stdin must be UTF-8 JSON") from exc
    if not isinstance(stdin, str):
        raise HookInputError("hook stdin must be a JSON string, bytes, or object")
    try:
        document = json.loads(stdin)
    except json.JSONDecodeError as exc:
        raise HookInputError("hook stdin is not valid JSON") from exc
    if not isinstance(document, dict):
        raise HookInputError("hook stdin JSON root must be an object")
    return document


def _optional_text(document: Mapping[str, Any], key: str) -> str | None:
    value = document.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise HookInputError(f"{key} must be a string when present")
    return value


def _required_text(document: Mapping[str, Any], key: str) -> str:
    value = _optional_text(document, key)
    if value is None or not value.strip():
        raise HookInputError(f"{key} must be a non-empty string")
    return value


def normalize_file_path(value: object) -> str:
    """Normalize host path separators without resolving or hiding traversal components."""
    if not isinstance(value, str) or not value.strip():
        raise HookInputError("file path must be a non-empty string")
    return value.strip().replace("\\", "/")


def extract_apply_patch_paths(patch: str) -> tuple[str, ...]:
    """Extract ordered, de-duplicated paths from Codex ``apply_patch`` text."""
    if not isinstance(patch, str) or not patch.strip():
        raise HookInputError("apply_patch content must be a non-empty string")
    found = [match.group("path") for match in _PATCH_PATH_RE.finditer(patch)]
    paths: list[str] = []
    seen: set[str] = set()
    for raw_path in found:
        path = normalize_file_path(raw_path)
        if path not in seen:
            paths.append(path)
            seen.add(path)
    if not paths:
        raise HookInputError("apply_patch content contains no recognizable file path")
    return tuple(paths)


def _multi_edit_content(tool_input: Mapping[str, Any]) -> str:
    edits = tool_input.get("edits")
    if not isinstance(edits, list):
        raise HookInputError("MultiEdit tool_input.edits must be an array")
    replacements: list[str] = []
    for edit in edits:
        if not isinstance(edit, Mapping) or not isinstance(edit.get("new_string"), str):
            raise HookInputError("every MultiEdit edit must contain string new_string")
        replacements.append(edit["new_string"])
    return "\n".join(replacements)


def _normalize_tool(
    tool_name: str | None, tool_input: Any
) -> tuple[ToolOperation, str | None, tuple[str, ...], str | None]:
    if tool_name is None:
        return ToolOperation.NONE, None, (), None
    if tool_name in _SHELL_TOOLS:
        if not isinstance(tool_input, Mapping):
            raise HookInputError(f"{tool_name} tool_input must be an object")
        command = tool_input.get("command", tool_input.get("cmd"))
        if not isinstance(command, str) or not command.strip():
            raise HookInputError(
                f"{tool_name} tool_input.command must be a non-empty string"
            )
        return ToolOperation.SHELL, command, (), None
    if tool_name in _APPLY_PATCH_TOOLS:
        if not isinstance(tool_input, Mapping):
            raise HookInputError("apply_patch tool_input must be an object")
        patch = tool_input.get("command", tool_input.get("patch"))
        if not isinstance(patch, str):
            raise HookInputError("apply_patch tool_input.command must be a string")
        return (
            ToolOperation.APPLY_PATCH,
            None,
            extract_apply_patch_paths(patch),
            patch,
        )
    if tool_name in _READ_TOOLS | _WRITE_TOOLS | _EDIT_TOOLS:
        if not isinstance(tool_input, Mapping):
            raise HookInputError(f"{tool_name} tool_input must be an object")
        file_path = normalize_file_path(tool_input.get("file_path"))
        if tool_name in _READ_TOOLS:
            return ToolOperation.FILE_READ, None, (file_path,), None
        if tool_name in _WRITE_TOOLS:
            content = tool_input.get("content")
            if not isinstance(content, str):
                raise HookInputError("Write tool_input.content must be a string")
            return ToolOperation.FILE_WRITE, None, (file_path,), content
        if tool_name == "MultiEdit":
            content = _multi_edit_content(tool_input)
        else:
            content = tool_input.get("new_string")
            if not isinstance(content, str):
                raise HookInputError("Edit tool_input.new_string must be a string")
        return ToolOperation.FILE_EDIT, None, (file_path,), content
    return ToolOperation.OTHER, None, (), None


def normalize_hook_input(
    provider: HookProvider | str,
    effect: HookEffect | str,
    stdin: str | bytes | Mapping[str, Any],
    *,
    env: Mapping[str, str] | None = None,
) -> HookEnvelope:
    """Parse one host stdin object into a provider-neutral envelope.

    This function raises :class:`HookInputError` for malformed input. Command-hook adapters should
    normally call :func:`execute_hook`, which applies fail-closed/fail-open behavior from ``effect``.
    """
    host = _coerce_enum(HookProvider, provider, field_name="provider")
    semantic_effect = _coerce_enum(HookEffect, effect, field_name="effect")
    document = _parse_document(stdin)
    wire_event = _required_text(document, "hook_event_name")
    try:
        event = _WIRE_EVENTS[wire_event]
    except KeyError as exc:
        raise UnsupportedHookEvent(f"unsupported hook event: {wire_event}") from exc

    tool_name: str | None = None
    tool_input: Any = None
    if event in (HookEvent.PRE_TOOL, HookEvent.POST_TOOL, HookEvent.TOOL_FAILURE):
        tool_name = _required_text(document, "tool_name")
        if "tool_input" not in document:
            raise HookInputError("tool_input is required for tool hook events")
        tool_input = document["tool_input"]
    operation, command, file_paths, content = _normalize_tool(tool_name, tool_input)

    return HookEnvelope(
        provider=host,
        event=event,
        effect=semantic_effect,
        wire_event=wire_event,
        operation=operation,
        tool_name=tool_name,
        tool_input=tool_input,
        command=command,
        file_paths=file_paths,
        write_content=content,
        cwd=_optional_text(document, "cwd"),
        session_id=_optional_text(document, "session_id"),
        plugin_root=resolve_plugin_root(env),
        raw=document,
    )


def _json_stdout(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"


def _no_op(
    disposition: HookDisposition = HookDisposition.NOOP,
    envelope: HookEnvelope | None = None,
) -> HookRunResult:
    return HookRunResult(0, "", "", disposition, envelope)


def _hard_failure(reason: str, envelope: HookEnvelope | None = None) -> HookRunResult:
    """Use the shared exit-2 contract when structured blocking output is unavailable."""
    message = reason.strip() or "blocking hook could not evaluate input safely"
    return HookRunResult(
        2,
        "",
        message + "\n",
        HookDisposition.BLOCK,
        envelope,
    )


def _block_payload(envelope: HookEnvelope, reason: str) -> Mapping[str, Any] | None:
    if envelope.event is HookEvent.PRE_TOOL:
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }
    if envelope.event in _TOP_LEVEL_BLOCK_EVENTS:
        return {"decision": "block", "reason": reason}
    if envelope.event is HookEvent.SESSION_START:
        return {
            "continue": False,
            "stopReason": reason,
            "systemMessage": reason,
        }
    return None


def render_hook_decision(
    envelope: HookEnvelope, decision: HookDecision
) -> HookRunResult:
    """Render a portable decision into the selected provider's current command-hook contract."""
    if envelope.event not in _PROVIDER_EVENTS[envelope.provider]:
        if envelope.effect is HookEffect.ADVISORY:
            return _no_op(envelope=envelope)
        return _hard_failure(
            f"blocking hook cannot enforce unsupported {envelope.provider.value} event "
            f"{envelope.wire_event}",
            envelope,
        )

    if decision.disposition in (HookDisposition.ALLOW, HookDisposition.NOOP):
        return _no_op(decision.disposition, envelope)
    if decision.disposition is HookDisposition.ADVISORY:
        if envelope.event not in _ADVISORY_OUTPUT_EVENTS[envelope.provider]:
            return _no_op(envelope=envelope)
        if (
            envelope.provider is HookProvider.CODEX
            and envelope.event in _CODEX_ADDITIONAL_CONTEXT_EVENTS
        ):
            return HookRunResult(
                0,
                _json_stdout(
                    {
                        "hookSpecificOutput": {
                            "hookEventName": envelope.wire_event,
                            "additionalContext": decision.message,
                        }
                    }
                ),
                "",
                HookDisposition.ADVISORY,
                envelope,
            )
        return HookRunResult(
            0,
            _json_stdout({"systemMessage": decision.message}),
            "",
            HookDisposition.ADVISORY,
            envelope,
        )
    if envelope.effect is HookEffect.ADVISORY:
        # An advisory hook is never allowed to acquire control-flow authority through its handler.
        return _no_op(envelope=envelope)

    payload = _block_payload(envelope, decision.message)
    if payload is None:
        return _hard_failure(
            f"blocking output is unsupported for {envelope.provider.value} event "
            f"{envelope.wire_event}: {decision.message}",
            envelope,
        )
    return HookRunResult(
        0,
        _json_stdout(payload),
        "",
        HookDisposition.BLOCK,
        envelope,
    )


def execute_hook(
    provider: HookProvider | str,
    effect: HookEffect | str,
    stdin: str | bytes | Mapping[str, Any],
    handler: HookHandler,
    *,
    env: Mapping[str, str] | None = None,
) -> HookRunResult:
    """Normalize input, invoke ``handler``, and return process-level host output.

    Malformed or unsupported blocking input returns exit code ``2`` with a stable stderr reason.
    Advisory input and handler failures return an empty successful result so optional diagnostics
    cannot break the user's workflow.
    """
    semantic_effect = _coerce_enum(HookEffect, effect, field_name="effect")
    try:
        envelope = normalize_hook_input(provider, semantic_effect, stdin, env=env)
    except (HookInputError, TypeError, ValueError) as exc:
        if semantic_effect is HookEffect.BLOCKING:
            return _hard_failure(f"blocking hook rejected malformed input: {exc}")
        return _no_op()

    if envelope.event not in _PROVIDER_EVENTS[envelope.provider]:
        if semantic_effect is HookEffect.BLOCKING:
            return _hard_failure(
                f"blocking hook cannot enforce unsupported {envelope.provider.value} event "
                f"{envelope.wire_event}",
                envelope,
            )
        return _no_op(envelope=envelope)

    try:
        decision = handler(envelope)
        if not isinstance(decision, HookDecision):
            raise TypeError("hook handler must return HookDecision")
        return render_hook_decision(envelope, decision)
    except (
        Exception
    ) as exc:  # policy code is an isolation boundary; preserve hook fail mode
        if semantic_effect is HookEffect.BLOCKING:
            return _hard_failure(
                f"blocking hook handler failed: {type(exc).__name__}: {exc}", envelope
            )
        return _no_op(envelope=envelope)


__all__ = [
    "HookDecision",
    "HookDisposition",
    "HookEffect",
    "HookEnvelope",
    "HookEvent",
    "HookHandler",
    "HookInputError",
    "HookProvider",
    "HookRunResult",
    "ToolOperation",
    "UnsupportedHookEvent",
    "execute_hook",
    "extract_apply_patch_paths",
    "normalize_file_path",
    "normalize_hook_input",
    "render_hook_decision",
    "resolve_plugin_root",
]
