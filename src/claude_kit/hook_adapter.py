"""Execute legacy hook policies through the provider-neutral hook contract.

The existing shell policies are intentionally retained while the payload is migrated: they contain
years of false-positive controls.  This adapter is the strangler seam.  It normalizes either host's
wire envelope, presents a compatibility-shaped document to the trusted policy script, interprets
the script's semantic result, and lets :mod:`claude_kit.hook_runtime` render host-correct output.

Only registered hook IDs may be executed.  Script paths are resolved beneath the selected runtime's
managed hook directory (or a validated plugin root), never from hook stdin.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from claude_kit.hook_runtime import (
    HookDecision,
    HookEnvelope,
    HookProvider,
    HookRunResult,
    ToolOperation,
    execute_hook,
)
from claude_kit.hooks import HOOK_REGISTRY, HOOK_SPECS, PLUGIN_ONLY_HOOKS


class HookAdapterError(RuntimeError):
    """A registered policy could not be executed or returned an invalid result."""


_SHELL_CONTROL_RE = re.compile(r"^[;&|()]+$")
_SHELL_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_SECRET_PATH_RE = re.compile(
    r"(?:^|/)\.env$|\.(?:pem|key|p12)$|(?:^|/)(?:id_rsa|id_ed25519)$|"
    r"(?:^|/)credentials(?:\.json)?$",
    re.IGNORECASE,
)
_SIMPLE_FILE_READERS = frozenset(
    {
        ".",
        "base64",
        "cat",
        "cut",
        "fold",
        "head",
        "less",
        "more",
        "nl",
        "od",
        "rev",
        "sort",
        "source",
        "strings",
        "tac",
        "tail",
        "uniq",
        "wc",
        "xxd",
    }
)
_PATTERN_FILE_READERS = frozenset(
    {"awk", "egrep", "fgrep", "gawk", "grep", "jq", "rg", "sed"}
)
_SHELL_INTERPRETERS = frozenset({"bash", "dash", "ksh", "sh", "zsh"})
_PATTERN_OPTIONS = frozenset({"-e", "--expression", "--regexp"})
_FILE_OPTIONS = frozenset({"-f", "--file", "--from-file"})
_NON_FILE_OPTION_VALUES = frozenset(
    {
        "-A",
        "-B",
        "-C",
        "-g",
        "-m",
        "-t",
        "-T",
        "-v",
        "--after-context",
        "--arg",
        "--argjson",
        "--before-context",
        "--context",
        "--glob",
        "--max-count",
        "--type",
        "--type-not",
    }
)
_SECRET_READ_REASON = (
    "BLOCKED: refusing to read a secrets file. Use .env.example or a secret manager."
)


def _shell_tokens(command: str) -> list[str]:
    if not isinstance(command, str) or not command.strip():
        raise HookAdapterError("shell read guard requires a non-empty command")
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()<>")
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        return list(lexer)
    except ValueError as exc:
        raise HookAdapterError(
            f"shell command could not be parsed safely: {exc}"
        ) from exc


def _command_segments(tokens: Sequence[str]) -> tuple[tuple[str, ...], ...]:
    segments: list[tuple[str, ...]] = []
    current: list[str] = []
    for token in tokens:
        if _SHELL_CONTROL_RE.fullmatch(token):
            if current:
                segments.append(tuple(current))
                current = []
            continue
        current.append(token)
    if current:
        segments.append(tuple(current))
    return tuple(segments)


def _normalized_candidate(token: str) -> str | None:
    value = token.strip().replace("\\", "/")
    if not value or value == "-" or value.startswith(("$", "`")):
        return None
    if value.startswith("file://"):
        value = value[len("file://") :]
    return value


def _reader_arguments(executable: str, arguments: Sequence[str]) -> list[str]:
    if executable == "dd":
        return [argument[3:] for argument in arguments if argument.startswith("if=")]
    if executable in _SIMPLE_FILE_READERS:
        return [argument for argument in arguments if not argument.startswith("-")]
    if executable not in _PATTERN_FILE_READERS:
        return []

    files: list[str] = []
    positional: list[str] = []
    pattern_supplied = False
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument == "--":
            positional.extend(arguments[index + 1 :])
            break
        if argument in _FILE_OPTIONS:
            if index + 1 >= len(arguments):
                raise HookAdapterError(f"{executable} {argument} has no value")
            files.append(arguments[index + 1])
            pattern_supplied = True
            index += 2
            continue
        if argument in _PATTERN_OPTIONS:
            if index + 1 >= len(arguments):
                raise HookAdapterError(f"{executable} {argument} has no value")
            pattern_supplied = True
            index += 2
            continue
        if argument in _NON_FILE_OPTION_VALUES:
            if index + 1 >= len(arguments):
                raise HookAdapterError(f"{executable} {argument} has no value")
            index += 2
            continue
        if argument.startswith("-"):
            index += 1
            continue
        positional.append(argument)
        index += 1
    if positional and not pattern_supplied:
        positional = positional[1:]
    files.extend(positional)
    return files


def extract_shell_read_paths(command: str) -> tuple[str, ...]:
    """Extract explicit file operands from a narrow set of local read commands.

    This is intentionally not a general shell evaluator. Unknown commands are ignored; malformed
    quoting and incomplete known-reader options raise so the blocking hook fails closed.
    """

    tokens = _shell_tokens(command)
    candidates: list[str] = []
    for index, token in enumerate(tokens[:-1]):
        if token == "<":
            candidates.append(tokens[index + 1])
    for segment in _command_segments(tokens):
        parts = list(segment)
        while parts and _SHELL_ASSIGNMENT_RE.match(parts[0]):
            parts.pop(0)
        while parts and Path(parts[0]).name in {"command", "env", "sudo"}:
            parts.pop(0)
            while parts and (
                parts[0].startswith("-") or _SHELL_ASSIGNMENT_RE.match(parts[0])
            ):
                parts.pop(0)
        if not parts:
            continue
        executable = Path(parts[0]).name
        arguments = parts[1:]
        if executable in _SHELL_INTERPRETERS and "-c" in arguments:
            command_index = arguments.index("-c") + 1
            if command_index >= len(arguments):
                raise HookAdapterError(f"{executable} -c has no command")
            candidates.extend(extract_shell_read_paths(arguments[command_index]))
            continue
        candidates.extend(_reader_arguments(executable, arguments))

    normalized: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        value = _normalized_candidate(candidate)
        if value is not None and value not in seen:
            normalized.append(value)
            seen.add(value)
    return tuple(normalized)


def _protect_secret_shell_read(envelope: HookEnvelope) -> HookDecision:
    paths = extract_shell_read_paths(envelope.command or "")
    if any(_SECRET_PATH_RE.search(path) for path in paths):
        return HookDecision.block(_SECRET_READ_REASON)
    return HookDecision.allow()


def _project_path(root: Path, value: str) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise HookAdapterError(f"hook file path escapes project root: {value}") from exc
    return resolved


def _patch_file_section(patch: str, wanted: str) -> tuple[str, list[str]] | None:
    """Return ``(operation, body lines)`` for one file in Codex's apply_patch dialect."""

    normalized_wanted = wanted.replace("\\", "/").lstrip("./")
    lines = patch.splitlines()
    for index, line in enumerate(lines):
        operation: str | None = None
        path: str | None = None
        for label, name in (
            ("*** Add File: ", "add"),
            ("*** Update File: ", "update"),
            ("*** Delete File: ", "delete"),
        ):
            if line.startswith(label):
                operation = name
                path = line[len(label) :].strip().replace("\\", "/").lstrip("./")
                break
        if operation is None or path != normalized_wanted:
            continue
        body: list[str] = []
        for following in lines[index + 1 :]:
            if following.startswith("*** "):
                break
            body.append(following)
        return operation, body
    return None


def _locate_lines(haystack: list[str], needle: list[str], start: int) -> int:
    if not needle:
        return start
    limit = len(haystack) - len(needle) + 1
    for index in range(start, max(start, limit)):
        if haystack[index : index + len(needle)] == needle:
            return index
    raise HookAdapterError("apply_patch hunk does not match the current hooks.json")


def _apply_update_lines(current: str, body: list[str]) -> str:
    """Apply the context/removal/addition lines needed for a settings validity check."""

    source = current.splitlines()
    trailing_newline = current.endswith("\n")
    groups: list[list[str]] = []
    active: list[str] = []
    for line in body:
        if line.startswith("@@"):
            if active:
                groups.append(active)
                active = []
            continue
        active.append(line)
    if active:
        groups.append(active)
    if not groups:
        raise HookAdapterError("apply_patch update contains no hunk body")

    cursor = 0
    for group in groups:
        old: list[str] = []
        new: list[str] = []
        for line in group:
            if not line:
                # An unprefixed empty line is context in the patch dialect.
                old.append("")
                new.append("")
            elif line[0] == "+":
                new.append(line[1:])
            elif line[0] == "-":
                old.append(line[1:])
            elif line[0] == " ":
                old.append(line[1:])
                new.append(line[1:])
            else:
                # Codex apply_patch accepts bare context lines after a named @@ locator.
                old.append(line)
                new.append(line)
        position = _locate_lines(source, old, cursor)
        source[position : position + len(old)] = new
        cursor = position + len(new)
    rendered = "\n".join(source)
    if trailing_newline or rendered:
        rendered += "\n"
    return rendered


def _codex_validate_settings(
    envelope: HookEnvelope, *, project_root: Path
) -> HookDecision:
    """Validate the resulting native hook JSON for Write and apply_patch operations."""

    targets = tuple(
        path
        for path in envelope.file_paths
        if path.replace("\\", "/").endswith(".codex/hooks.json")
    )
    if not targets:
        return HookDecision.allow()
    if envelope.operation is ToolOperation.FILE_WRITE:
        candidate = envelope.write_content or ""
    elif envelope.operation is ToolOperation.APPLY_PATCH:
        if len(targets) != 1:
            return HookDecision.block(
                "cannot safely validate a multi-target hooks.json patch"
            )
        target = targets[0]
        relative = (
            _project_path(project_root, target).relative_to(project_root).as_posix()
        )
        section = _patch_file_section(envelope.write_content or "", relative)
        if section is None:
            return HookDecision.block(
                "hooks.json patch section could not be reconstructed"
            )
        operation, body = section
        if operation == "delete":
            return HookDecision.block("refusing to delete native hook configuration")
        if operation == "add":
            candidate = "\n".join(line[1:] for line in body if line.startswith("+"))
            if candidate:
                candidate += "\n"
        else:
            path = _project_path(project_root, target)
            if not path.is_file():
                return HookDecision.block(
                    "cannot validate update to missing hooks.json"
                )
            try:
                current = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                return HookDecision.block(f"cannot read current hooks.json: {exc}")
            try:
                candidate = _apply_update_lines(current, body)
            except HookAdapterError as exc:
                return HookDecision.block(str(exc))
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as exc:
        return HookDecision.block(
            f".codex/hooks.json would not be valid JSON: {exc.msg}"
        )
    if not isinstance(parsed, Mapping):
        return HookDecision.block(".codex/hooks.json must contain a JSON object")
    return HookDecision.allow()


def _contained_file(root: Path, relative: str) -> Path:
    unresolved = Path(relative)
    if unresolved.is_absolute() or ".." in unresolved.parts:
        raise HookAdapterError(f"hook path escapes managed root: {relative}")
    try:
        resolved_root = root.resolve(strict=True)
    except OSError as exc:
        raise HookAdapterError(f"managed hook root is unavailable: {root}") from exc
    cursor = resolved_root
    for part in unresolved.parts:
        cursor /= part
        try:
            if cursor.is_symlink():
                raise HookAdapterError(
                    f"registered hook path contains a symlink: {relative}"
                )
        except OSError as exc:
            raise HookAdapterError(
                f"registered hook path cannot be inspected: {relative}"
            ) from exc
    candidate = (resolved_root / unresolved).resolve(strict=False)
    try:
        candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise HookAdapterError(f"hook path escapes managed root: {relative}") from exc
    if not candidate.is_file():
        raise HookAdapterError(f"registered hook script is missing: {candidate}")
    return candidate


def _discover_codex_project_root(start: Path) -> Path:
    """Find the nearest native project root without trusting hook input or symlinked controls."""

    try:
        current = start.expanduser().resolve(strict=True)
    except OSError as exc:
        raise HookAdapterError(
            f"hook working directory is unavailable: {start}"
        ) from exc
    if not current.is_dir():
        raise HookAdapterError(f"hook working directory is not a directory: {start}")
    for candidate in (current, *current.parents):
        codex_dir = candidate / ".codex"
        marker = codex_dir / "hooks.json"
        if codex_dir.is_symlink() or marker.is_symlink():
            raise HookAdapterError(
                f"refusing symlinked native hook controls under {candidate}"
            )
        if not marker.exists():
            continue
        if not codex_dir.is_dir() or not marker.is_file():
            raise HookAdapterError(
                f"native hook project marker has an unsafe type under {candidate}"
            )
        try:
            marker.resolve(strict=True).relative_to(candidate)
        except (OSError, ValueError) as exc:
            raise HookAdapterError(
                f"native hook project marker escapes {candidate}"
            ) from exc
        return candidate
    raise HookAdapterError(f"could not discover a native project root above {current}")


def _legacy_documents(envelope: HookEnvelope) -> tuple[dict[str, Any], ...]:
    """Project a normalized operation into the compatibility input expected by shell policies."""

    base = dict(envelope.raw)
    if envelope.operation is ToolOperation.NONE:
        return (base,)
    if envelope.operation is ToolOperation.SHELL:
        base["tool_name"] = "Bash"
        base["tool_input"] = {"command": envelope.command}
        return (base,)
    if envelope.operation is ToolOperation.FILE_READ:
        tool_name = "Read"
    elif envelope.operation is ToolOperation.FILE_EDIT:
        tool_name = "Edit"
    elif envelope.operation in (ToolOperation.FILE_WRITE, ToolOperation.APPLY_PATCH):
        tool_name = "Write"
    else:
        return (base,)

    # apply_patch may touch several files.  Evaluate the policy independently for every exact path;
    # one block blocks the host operation, while advisory messages are combined deterministically.
    documents: list[dict[str, Any]] = []
    for file_path in envelope.file_paths:
        item = dict(base)
        item["tool_name"] = tool_name
        tool_input: dict[str, Any] = {"file_path": file_path}
        if tool_name == "Write":
            content = envelope.write_content or ""
            if envelope.operation is ToolOperation.APPLY_PATCH:
                section = _patch_file_section(content, file_path)
                if section is not None:
                    _operation, body = section
                    additions = [line[1:] for line in body if line.startswith("+")]
                    if additions:
                        content = "\n".join(additions) + "\n"
            tool_input["content"] = content
        elif tool_name == "Edit":
            tool_input["old_string"] = ""
            tool_input["new_string"] = envelope.write_content or ""
        item["tool_input"] = tool_input
        documents.append(item)
    return tuple(documents) or (base,)


def _message_from_json(payload: Any) -> HookDecision | None:
    if not isinstance(payload, Mapping):
        return None
    if payload.get("decision") == "block":
        reason = payload.get("reason")
        if isinstance(reason, str) and reason.strip():
            return HookDecision.block(reason)
    specific = payload.get("hookSpecificOutput")
    if isinstance(specific, Mapping):
        if specific.get("permissionDecision") == "deny":
            reason = specific.get("permissionDecisionReason")
            if isinstance(reason, str) and reason.strip():
                return HookDecision.block(reason)
        context = specific.get("additionalContext")
        if isinstance(context, str) and context.strip():
            return HookDecision.advisory(context)
    for key in ("systemMessage", "stopReason"):
        message = payload.get(key)
        if isinstance(message, str) and message.strip():
            return HookDecision.advisory(message)
    return None


def _interpret_process(
    completed: subprocess.CompletedProcess[str], *, hook_id: str
) -> HookDecision:
    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()
    if completed.returncode == 2:
        return HookDecision.block(
            stderr or stdout or f"{hook_id} blocked the operation"
        )
    if completed.returncode != 0:
        detail = stderr or stdout or "no diagnostic"
        raise HookAdapterError(
            f"hook {hook_id!r} exited {completed.returncode}: {detail}"
        )
    if not stdout:
        return HookDecision.allow()
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return HookDecision.advisory(stdout)
    decision = _message_from_json(payload)
    if decision is None:
        raise HookAdapterError(f"hook {hook_id!r} returned unrecognized JSON output")
    return decision


def _combine_decisions(decisions: Sequence[HookDecision]) -> HookDecision:
    for decision in decisions:
        if decision.disposition.value == "block":
            return decision
    messages = tuple(
        dict.fromkeys(
            decision.message
            for decision in decisions
            if decision.disposition.value == "advisory" and decision.message
        )
    )
    if messages:
        return HookDecision.advisory("\n\n".join(messages))
    return HookDecision.allow()


def _registered_command(
    hook_id: str,
    provider: HookProvider,
    *,
    project_root: Path,
    plugin_root: Path | None,
) -> list[str]:
    records = {**HOOK_REGISTRY, **PLUGIN_ONLY_HOOKS}
    record = records[hook_id]
    script = record.get("script")
    if isinstance(script, str) and script:
        if plugin_root is not None:
            path = _contained_file(plugin_root, f"hooks/scripts/{script}")
        elif provider is HookProvider.CODEX:
            path = _contained_file(project_root, f".codex/hooks/scripts/{script}")
        else:
            path = _contained_file(project_root, f".claude/hooks/{script}")
        command = ["bash", str(path)]
        arg = record.get("arg")
        if isinstance(arg, str) and arg:
            command.append(arg)
        return command

    entry = record.get("entry")
    command_text = entry.get("command") if isinstance(entry, Mapping) else None
    if not isinstance(command_text, str) or not command_text.strip():
        raise HookAdapterError(f"hook {hook_id!r} has no executable action")
    # This text is registry-owned, not user input.  Neutral branding affects diagnostics only.
    return ["bash", "-c", command_text.replace("claude-kit", "ckit")]


def run_registered_hook(
    provider: HookProvider | str,
    hook_id: str,
    stdin: str | bytes | Mapping[str, Any],
    *,
    project_root: str | Path = ".",
    plugin_root: str | Path | None = None,
    discover_project_root: bool = False,
    env: Mapping[str, str] | None = None,
) -> HookRunResult:
    """Run one registered hook and return provider-correct process output.

    Blocking policies fail closed on malformed input, missing scripts, and execution errors.
    Advisory policies fail open through :func:`execute_hook`.
    """

    if hook_id not in HOOK_SPECS:
        raise ValueError(f"unknown hook id: {hook_id}")
    host = HookProvider(provider)
    spec = HOOK_SPECS[hook_id]
    requested_root = Path(project_root)
    root = (
        _discover_codex_project_root(requested_root)
        if host is HookProvider.CODEX and discover_project_root
        else requested_root.expanduser().resolve(strict=False)
    )
    plugin = (
        Path(plugin_root).expanduser().resolve(strict=False)
        if plugin_root is not None
        else None
    )
    command = _registered_command(hook_id, host, project_root=root, plugin_root=plugin)
    process_env = dict(os.environ)
    if env is not None:
        process_env.update(env)
    process_env["CKIT_PROJECT_ROOT"] = str(root)
    process_env["CKIT_HOOK_PROVIDER"] = host.value
    # Existing Claude policies keep their compatibility variable during the migration window.
    process_env.setdefault("CLAUDE_PROJECT_DIR", str(root))
    if plugin is not None:
        process_env["PLUGIN_ROOT"] = str(plugin)
        process_env.setdefault("CLAUDE_PLUGIN_ROOT", str(plugin))

    def handler(envelope: HookEnvelope) -> HookDecision:
        if host is HookProvider.CODEX and hook_id == "validate-settings":
            return _codex_validate_settings(envelope, project_root=root)
        if (
            host is HookProvider.CODEX
            and hook_id == "protect-secrets"
            and envelope.operation is ToolOperation.SHELL
        ):
            return _protect_secret_shell_read(envelope)
        decisions: list[HookDecision] = []
        for document in _legacy_documents(envelope):
            completed = subprocess.run(  # noqa: S603 - argv resolved from the trusted registry
                command,
                input=json.dumps(document, ensure_ascii=False),
                text=True,
                capture_output=True,
                cwd=root,
                env=process_env,
                check=False,
            )
            decisions.append(_interpret_process(completed, hook_id=hook_id))
        return _combine_decisions(decisions)

    return execute_hook(host, spec.effect, stdin, handler, env=process_env)


__all__ = ["HookAdapterError", "extract_shell_read_paths", "run_registered_hook"]
