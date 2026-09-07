#!/usr/bin/env python3
"""Protected, credentialed native-host behavior smoke for Claude Code and Codex.

The ordinary test suite must never contact either model provider.  This helper is intentionally
split into prepare/run/record/verify phases so a protected GitHub workflow can keep credentials in
host-owned channels:

* Claude receives an out-of-project ``apiKeyHelper`` settings file.
* Codex is invoked by ``openai/codex-action``, whose local proxy owns the API key.
* A separate passive managed Codex probe receives ``OPENAI_API_KEY`` only in the exact-wheel
  coordinator process; its native adapter denies shell, hooks, MCP, network, and delegation.
* Project hooks are launched through ``env -i`` and fail if a credential variable is visible.

The fixture is deliberately tiny.  Provider-specific random values stored independently in project
instructions, one skill, one read-only custom agent, and the real ``.ckit`` pipeline state make
discovery observable without putting the expected values in the user prompt.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import secrets
import shlex
import shutil
import stat
import subprocess
import sys
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

# The protected harness control document and the installed init-options manifest
# evolve independently. Keep both explicit so a control-format change cannot
# accidentally weaken the exact-wheel manifest assertion.
SCHEMA_VERSION = 2
INIT_OPTIONS_SCHEMA_VERSION = 3
CONTROL_FILE = "control.json"
EVENT_LOG = Path(".ckit/artifacts/protected-host-events.jsonl")
PIPELINE_SNAPSHOT = Path(".ckit/state/pipeline-snapshot.json")
PIPELINE_EVIDENCE_DIR = Path(".ckit/artifacts/protected-host")
MANAGED_PROJECT_DIR = "managed-project"
MANAGED_PASSIVE_STAGE = "fast-track-classify"
MANAGED_PASSIVE_ROLE = "risk-classifier"
MANAGED_PASSIVE_EVIDENCE = "fast-track-scope-record"
MANAGED_PASSIVE_CAPABILITIES = (
    "delegation.message",
    "filesystem.read",
    "filesystem.search",
)
MANAGED_GATE_OWNERS = {
    "code-review": "fast-review",
    "build-green": "fast-verify",
}
MANAGED_GATE_OWNER_PROJECT_DIR = "managed-gate-owner-project"
MANAGED_GATE_OWNER_STAGE = "planning-merge"
MANAGED_GATE_OWNER_ROLE = "em-reviewer"
MANAGED_GATE_OWNER_GATE = "em-approved"
MANAGED_GATE_OWNER_CAPABILITIES = (
    "filesystem.read",
    "filesystem.search",
)
MANAGED_PLANNING_REVIEW_STAGE = "architecture-review"
MANAGED_PLANNING_REVIEW_ROUTE = "architecture"
MANAGED_PLANNING_REVIEW_ROLE = "technical-architect"
MANAGED_PLANNING_REVIEW_AUTHORITY = "architecture"
MANAGED_PLANNING_REVIEW_CAPABILITIES = (
    "filesystem.read",
    "filesystem.search",
)
MANAGED_GATE_SEED_STAGES = (
    "classify",
    "specification",
    "planning-gate",
)
MANAGED_GATE_SEED_GATE = "spec-complete"
MANAGED_GATE_OBJECTIVE = (
    "Review specs/protected_gate_owner_spec.md and decide whether its bounded "
    "fixture plan is ready."
)
SKILL_ARGUMENT = "protected-argument-v1"
REAL_SKILL_MARKER = "Using Agent Skills"
ADVISORY_MARKER = "CKIT_SMOKE_POST_TOOL_ADVISORY"
BLOCK_TARGET = ".env"
STOP_SENTINEL = "protected-stop-writeback.txt"
BLOCK_REASON = "BLOCKED: refusing to read a secrets file"
GENERATED_BLOCK_REASON = (
    "BLOCKED: refusing to read a secrets file. Use .env.example or a secret manager."
)
REQUIRED_FIELDS = (
    "instruction_nonce",
    "skill_nonce",
    "skill_argument",
    "real_skill_marker",
    "agent_nonce",
    "role_result",
    "gate_digest",
    "pipeline_stage",
    "gate_history_count",
    "prior_provider_transition",
    "blocking_reason",
    "advisory_marker",
)
CONTROL_EXPECTED_FIELDS = tuple(
    field
    for field in REQUIRED_FIELDS
    if field
    not in {"pipeline_stage", "gate_history_count", "prior_provider_transition"}
)
COMMITMENT_DOMAIN = "ckit-protected-host/v2"
CANARY_PATTERN = re.compile(r"blocked-canary-[0-9a-f]{32}")
MAX_HOST_OUTPUT_BYTES = 1_048_576
PROVIDER_SECRET_ENV = frozenset(
    {
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "CLAUDE_CODE_OAUTH_TOKEN",
        "CODEX_ACCESS_TOKEN",
        "CODEX_API_KEY",
        "OPENAI_API_KEY",
    }
)
PROVIDER_ORDERS = {
    "claude-codex": ("claude", "codex"),
    "codex-claude": ("codex", "claude"),
}
HOOK_SECRET_ENV = PROVIDER_SECRET_ENV | frozenset({"GH_TOKEN", "GITHUB_TOKEN"})
PROTECTED_DISCOVERY_PATHS = {
    "claude": frozenset(
        {
            "CLAUDE.md",
            ".claude/skills/ckit-protected-smoke/SKILL.md",
            ".claude/skills/using-agent-skills/SKILL.md",
            ".claude/agents/risk-classifier.md",
        }
    ),
    "codex": frozenset(
        {
            "AGENTS.md",
            ".agents/skills/ckit-protected-smoke/SKILL.md",
            ".agents/skills/using-agent-skills/SKILL.md",
            ".codex/agents/risk-classifier.toml",
        }
    ),
}
ALLOWED_FIXTURE_READ_PATHS = frozenset(
    {
        "README.md",
        BLOCK_TARGET,
        ".ckit/STACK.md",
        PIPELINE_SNAPSHOT.as_posix(),
    }
)

CLAUDE_PROMPT = """\
This is a protected native-host conformance check. Do not infer or fabricate any value.

1. Apply the real generated /using-agent-skills skill and report its top heading without manually
   reading its SKILL.md file.
2. Apply /ckit-protected-smoke with the exact argument protected-argument-v1. Report the skill
   nonce and the argument that the skill receives.
3. Delegate exactly once to the generated risk-classifier custom agent. Ask it to classify a task
   that only reads .ckit/STACK.md and makes no changes. Report its tier as role_result and the
   agent nonce it is asked to echo. Use the native named-agent mechanism.
4. Report the nonce supplied by the automatically discovered project instructions.
5. Read .ckit/state/pipeline-snapshot.json. Report its gate_definition_digest, current stage, and
   gate_history length as a decimal string. If the history is non-empty, read only its most recent
   evidence_path and report that evidence document's provider; otherwise report "none". Report the
   PostToolUse advisory marker delivered after reading the pipeline snapshot.
6. Attempt exactly once to read .env with the native file-read capability. The generated
   protect-secrets hook must deny it. Report only the public marker
   "BLOCKED: refusing to read a secrets file", never the file contents.

Do not inspect the instruction, skill, or agent definition files manually. Do not use shell,
network, write, or edit capabilities. Return only the requested JSON object.
"""

CODEX_PROMPT = """\
This is a protected native-host conformance check. Do not infer or fabricate any value.

1. Apply the real generated $using-agent-skills skill and report its top heading without manually
   reading its SKILL.md file.
2. Apply $ckit-protected-smoke with the exact argument protected-argument-v1. Report the skill
   nonce and the argument that the skill receives.
3. Delegate exactly once to the generated risk-classifier custom agent. Ask it to classify a task
   that only reads .ckit/STACK.md and makes no changes. Report its tier as role_result and the
   agent nonce it is asked to echo. Use the native named-agent mechanism.
4. Report the nonce supplied by the automatically discovered project instructions.
5. Run exactly `cat .ckit/state/pipeline-snapshot.json`. Report its gate_definition_digest,
   current stage, and
   gate_history length as a decimal string. If the history is non-empty, read only its most recent
   evidence_path with one exact `cat <evidence_path>` command and report that evidence document's
   provider; otherwise report "none". Report the PostToolUse advisory marker delivered after
   reading the pipeline snapshot.
6. Attempt exactly once to run `cat .env` through the ordinary native shell/unified-exec read
   operation. The generated protect-secrets hook must deny it. Report only the public marker
   "BLOCKED: refusing to read a secrets file", never the file contents.

Do not inspect the instruction, skill, or agent definition files manually. Do not use network,
write, or edit capabilities. Return only the requested JSON object.
"""

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {field: {"type": "string"} for field in REQUIRED_FIELDS},
    "required": list(REQUIRED_FIELDS),
    "additionalProperties": False,
}


class SmokeError(RuntimeError):
    """The protected host did not satisfy a fail-closed conformance assertion."""


class _FixtureSeedDispatcher:
    """Coordinator-only adapter for prerequisites outside the native-host claim.

    This adapter never starts a process.  Its closed stage allowlist materializes
    typed fixture evidence through the ordinary managed ledger so the protected
    native proof can begin at one canonical passive gate owner.  The resulting
    dispatch ids are recorded as an explicit non-native seed boundary.
    """

    queued_spawn = True
    _ROLES = {
        "classify": "risk-classifier",
        "specification": "spec-doc-writer",
        "planning-gate": "orchestrator",
    }

    def __init__(self) -> None:
        self.requests: dict[Any, Any] = {}
        self.stages: dict[Any, str] = {}
        self.cancelled: set[Any] = set()

    @staticmethod
    def _stage(request: Any) -> str:
        match = re.match(r"^Stage ([a-z0-9][a-z0-9-]*):", str(request.objective))
        if match is None:
            raise RuntimeError("fixture seed request has no canonical stage identity")
        return match.group(1)

    def spawn(self, request: Any) -> Any:
        from claude_kit.dispatch import DispatchHandle

        stage = self._stage(request)
        expected_role = self._ROLES.get(stage)
        if expected_role is None or request.route != expected_role:
            raise RuntimeError(
                f"fixture seed refuses non-prerequisite stage {stage!r} "
                f"or role {request.route!r}"
            )
        handle = DispatchHandle(
            f"protected-fixture-seed-{stage}",
            request.route,
            provider="codex",
            required_capabilities=request.required_capabilities,
            attested_capabilities=request.required_capabilities,
        )
        self.requests[handle] = request
        self.stages[handle] = stage
        return handle

    def message(self, handle: Any, message: Any) -> None:
        if handle not in self.requests or not str(message.content).strip():
            raise RuntimeError("fixture seed received an invalid queued message")

    def wait(
        self,
        handles: Sequence[Any],
        mode: Any = None,
        timeout_seconds: float | None = None,
    ) -> Any:
        from claude_kit.dispatch import WaitResult

        del mode, timeout_seconds
        if any(handle not in self.requests for handle in handles):
            raise RuntimeError("fixture seed wait referenced an unknown dispatch")
        return WaitResult(tuple(handles), (), False)

    def collect(self, handles: Sequence[Any]) -> tuple[Any, ...]:
        from claude_kit.dispatch import DispatchResult, DispatchStatus

        results: list[Any] = []
        for handle in handles:
            request = self.requests[handle]
            if handle in self.cancelled:
                results.append(
                    DispatchResult(
                        handle,
                        DispatchStatus.CANCELLED,
                        error="fixture seed dispatch was cancelled",
                    )
                )
                continue
            evidence = {
                reference.uri.removeprefix("artifact://"): (
                    _fixture_seed_evidence_document(
                        reference.uri.removeprefix("artifact://")
                    )
                )
                for reference in request.evidence
            }
            results.append(
                DispatchResult(
                    handle,
                    DispatchStatus.SUCCEEDED,
                    output=json.dumps({"evidence": evidence}, sort_keys=True),
                    evidence=request.evidence,
                )
            )
        return tuple(results)

    def retry(self, handle: Any, reason: str) -> Any:
        del handle, reason
        raise RuntimeError("fixture seed evidence is deterministic and never retryable")

    def cancel(self, handle: Any, reason: str) -> None:
        if handle not in self.requests or not reason.strip():
            raise RuntimeError("fixture seed cancellation is invalid")
        self.cancelled.add(handle)


def _fixture_seed_evidence_document(evidence_id: str) -> dict[str, Any]:
    provenance = {
        "kind": "protected-fixture-seed",
        "native_host_claim": False,
        "dispatcher": "closed-no-process-coordinator-adapter",
    }
    documents: dict[str, dict[str, Any]] = {
        "scope-record": {
            "mode": "A",
            "surfaces": ["protected gate-owner fixture"],
            "constraints": ["fixture prerequisites only; not native-host evidence"],
            "risks": [],
            "fixture_provenance": provenance,
        },
        "specification": {
            "outcome": "Exercise one canonical passive managed gate owner.",
            "acceptance-criteria": [
                "The native em-reviewer returns a typed PASS verdict.",
                "The em-approved gate closes from its exact owner attempt.",
            ],
            "non-goals": ["Prove shell, write, delegation, or external effects."],
            "risks": ["Fixture-seeded prerequisites are excluded from native claims."],
            "fixture_provenance": provenance,
        },
        "architecture-plan": {
            "boundaries": ["read-only protected fixture"],
            "dependencies": ["coordinator-seeded prerequisite ledger"],
            "interfaces": ["public managed pipeline and gate APIs"],
            "verification": ["owner-bound typed evidence and gate bundle"],
            "fixture_provenance": provenance,
        },
        "review-verdict": {
            "status": "PASS",
            "reviewer": "protected-fixture-seed",
            "findings": [],
            "evidence": ["specs/protected_gate_owner_spec.md"],
            "fixture_provenance": provenance,
        },
    }
    try:
        return documents[evidence_id]
    except KeyError as exc:
        raise RuntimeError(
            f"fixture seed refuses unknown evidence {evidence_id!r}"
        ) from exc


def _gate_history_digest(history: Any) -> str:
    if not isinstance(history, list) or any(
        not isinstance(item, Mapping) for item in history
    ):
        raise SmokeError("managed gate history is malformed")
    encoded = json.dumps(
        history,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _json_bytes(document: Any) -> bytes:
    return (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _write(path: Path, data: bytes, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    path.chmod(mode)


def _write_text(path: Path, text: str, *, mode: int = 0o600) -> None:
    _write(path, text.encode("utf-8"), mode=mode)


def _write_json(path: Path, document: Any, *, mode: int = 0o600) -> None:
    _write(path, _json_bytes(document), mode=mode)


def _paths(root: Path) -> tuple[Path, Path, Path]:
    resolved = root.expanduser().resolve(strict=False)
    return resolved, resolved / "project", resolved / "control"


def _nonce(label: str) -> str:
    return f"{label}-{secrets.token_hex(16)}"


def _commitment(provider: str, field: str, value: str) -> str:
    payload = json.dumps(
        [COMMITMENT_DOMAIN, provider, field, value],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{64}", value))


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _hook_command(root: Path, provider: str, event: str) -> str:
    script = Path(__file__).resolve(strict=True)
    _root, project, control = _paths(root)
    hook_home = control / "hook-home"
    event_log = project / EVENT_LOG
    environment = shutil.which("env") or "/usr/bin/env"
    argv = [
        environment,
        "-i",
        "PATH=/usr/bin:/bin",
        f"HOME={hook_home}",
        "LANG=C.UTF-8",
        "NO_COLOR=1",
        sys.executable,
        str(script),
        "hook",
        "--provider",
        provider,
        "--event",
        event,
        "--log",
        str(event_log),
    ]
    return shlex.join(argv)


def _guard_proxy_command(
    root: Path,
    provider: str,
    handler: str,
    *,
    ckit_executable: str,
) -> tuple[str, str]:
    script = Path(__file__).resolve(strict=True)
    _resolved, project, control = _paths(root)
    hook_home = control / "hook-home"
    event_log = project / EVENT_LOG
    handler_sha256 = hashlib.sha256(handler.encode("utf-8")).hexdigest()
    environment = shutil.which("env") or "/usr/bin/env"
    exact_ckit = Path(ckit_executable).resolve(strict=True)
    if exact_ckit.name != "ckit":
        raise SmokeError(
            "protected generated hooks require an exact executable named ckit"
        )
    path_entries = [str(exact_ckit.parent)]
    for program in ("jq", "sh"):
        resolved = shutil.which(program)
        if resolved is None:
            raise SmokeError(
                f"{program} is required by the generated hook positive control"
            )
        parent = str(Path(resolved).resolve(strict=True).parent)
        if parent not in path_entries:
            path_entries.append(parent)
    for parent in ("/usr/local/bin", "/usr/bin", "/bin"):
        if parent not in path_entries:
            path_entries.append(parent)
    argv = [
        environment,
        "-i",
        f"PATH={':'.join(path_entries)}",
        f"HOME={hook_home}",
        "LANG=C.UTF-8",
        "NO_COLOR=1",
        f"CKIT_PROJECT_ROOT={project}",
        f"CLAUDE_PROJECT_DIR={project}",
        f"CKIT_HOOK_PROVIDER={provider}",
        sys.executable,
        str(script),
        "guard-proxy",
        "--provider",
        provider,
        "--handler-id",
        "protect-secrets",
        "--handler",
        handler,
        "--handler-sha256",
        handler_sha256,
        "--project",
        str(project),
        "--log",
        str(event_log),
    ]
    return shlex.join(argv), handler_sha256


def _stop_proxy_command(
    root: Path,
    provider: str,
    handler: str,
    *,
    ckit_executable: str,
) -> tuple[str, str]:
    script = Path(__file__).resolve(strict=True)
    _resolved, project, control = _paths(root)
    hook_home = control / "hook-home"
    event_log = project / EVENT_LOG
    handler_sha256 = hashlib.sha256(handler.encode("utf-8")).hexdigest()
    exact_ckit = Path(ckit_executable).resolve(strict=True)
    path_entries = [str(exact_ckit.parent)]
    for program in ("git", "jq", "sh"):
        resolved = shutil.which(program)
        if resolved is None:
            raise SmokeError(
                f"{program} is required by the generated Stop positive control"
            )
        parent = str(Path(resolved).resolve(strict=True).parent)
        if parent not in path_entries:
            path_entries.append(parent)
    for parent in ("/usr/local/bin", "/usr/bin", "/bin"):
        if parent not in path_entries:
            path_entries.append(parent)
    environment = shutil.which("env") or "/usr/bin/env"
    argv = [
        environment,
        "-i",
        f"PATH={':'.join(path_entries)}",
        f"HOME={hook_home}",
        "LANG=C.UTF-8",
        "NO_COLOR=1",
        f"CKIT_PROJECT_ROOT={project}",
        f"CLAUDE_PROJECT_DIR={project}",
        f"CKIT_HOOK_PROVIDER={provider}",
        sys.executable,
        str(script),
        "stop-proxy",
        "--provider",
        provider,
        "--handler-id",
        "verify-continuity-writeback",
        "--handler",
        handler,
        "--handler-sha256",
        handler_sha256,
        "--project",
        str(project),
        "--log",
        str(event_log),
    ]
    return shlex.join(argv), handler_sha256


def _hooks_document(root: Path, provider: str) -> dict[str, Any]:
    def entry(event: str) -> dict[str, str]:
        return {"type": "command", "command": _hook_command(root, provider, event)}

    return {
        "hooks": {
            "SessionStart": [{"matcher": "", "hooks": [entry("session-start")]}],
            "SubagentStart": [{"matcher": "", "hooks": [entry("subagent-start")]}],
            "PreToolUse": [
                {
                    "matcher": "Read|read_file|Bash|exec_command|shell|unified_exec",
                    "hooks": [entry("definition-read")],
                }
            ],
            "PostToolUse": [
                {
                    "matcher": "Read|read_file|Bash|exec_command|shell|unified_exec",
                    "hooks": [entry("post-tool")],
                }
            ],
        }
    }


def _merge_probe_hooks(
    path: Path,
    root: Path,
    provider: str,
    *,
    ckit_executable: str,
) -> tuple[str, str, str]:
    """Retain the exact-wheel hook projection and add isolated observation hooks."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SmokeError(
            f"generated {provider} hook configuration is invalid: {exc}"
        ) from exc
    hooks = document.get("hooks")
    if not isinstance(hooks, dict):
        raise SmokeError(f"generated {provider} hook configuration has no hooks object")
    pre_tool = hooks.get("PreToolUse")
    if not isinstance(pre_tool, list):
        raise SmokeError(
            f"generated {provider} hook configuration has no PreToolUse hooks"
        )
    guard_needle = (
        "refusing to read a secrets file"
        if provider == "claude"
        else "--hook-id protect-secrets"
    )
    guard_entries: list[dict[str, Any]] = []
    for group in pre_tool:
        if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
            continue
        for hook in group["hooks"]:
            if (
                isinstance(hook, dict)
                and isinstance(hook.get("command"), str)
                and guard_needle in str(hook["command"])
            ):
                guard_entries.append(hook)
    if len(guard_entries) != 1:
        raise SmokeError(
            f"generated {provider} protect-secrets hook is not uniquely discoverable"
        )

    stop_groups = hooks.get("Stop")
    if not isinstance(stop_groups, list):
        raise SmokeError(f"generated {provider} hook configuration has no Stop hooks")
    stop_entries: list[dict[str, Any]] = []
    for group in stop_groups:
        if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
            continue
        for hook in group["hooks"]:
            command = hook.get("command") if isinstance(hook, dict) else None
            if isinstance(command, str) and "verify-continuity-writeback" in command:
                stop_entries.append(hook)
    if len(stop_entries) != 1:
        raise SmokeError(
            f"generated {provider} verify-continuity-writeback hook is not uniquely discoverable"
        )

    probe = _hooks_document(root, provider)["hooks"]
    original_handler = str(guard_entries[0]["command"])
    proxy, handler_sha256 = _guard_proxy_command(
        root,
        provider,
        original_handler,
        ckit_executable=ckit_executable,
    )
    guard_entries[0]["command"] = proxy
    original_stop_handler = str(stop_entries[0]["command"])
    stop_proxy, stop_handler_sha256 = _stop_proxy_command(
        root,
        provider,
        original_stop_handler,
        ckit_executable=ckit_executable,
    )
    stop_entries[0]["command"] = stop_proxy
    for event in ("SessionStart", "SubagentStart", "PreToolUse", "PostToolUse"):
        groups = hooks.setdefault(event, [])
        if not isinstance(groups, list):
            raise SmokeError(f"generated {provider} {event} hook group is invalid")
        groups.extend(probe[event])
    _write_json(path, document)
    return handler_sha256, stop_handler_sha256, original_stop_handler


def _stop_handler_positive_control(
    *,
    provider: str,
    handler: str,
    project: Path,
    control: Path,
    ckit_executable: str,
) -> str:
    exact_ckit = Path(ckit_executable).resolve(strict=True)
    path_entries = [str(exact_ckit.parent)]
    for program in ("git", "jq", "sh"):
        resolved = shutil.which(program)
        if resolved is None:
            raise SmokeError(f"{program} is required by the generated Stop control")
        parent = str(Path(resolved).resolve(strict=True).parent)
        if parent not in path_entries:
            path_entries.append(parent)
    env = {
        "PATH": ":".join(path_entries + ["/usr/local/bin", "/usr/bin", "/bin"]),
        "HOME": str(control / "hook-home"),
        "LANG": "C.UTF-8",
        "NO_COLOR": "1",
        "CKIT_PROJECT_ROOT": str(project),
        "CLAUDE_PROJECT_DIR": str(project),
        "CKIT_HOOK_PROVIDER": provider,
    }

    def invoke(active: bool) -> subprocess.CompletedProcess[bytes]:
        return _run_bounded_process(
            ["/bin/sh", "-c", handler],
            cwd=project,
            env=env,
            timeout=30,
            label=f"generated {provider} Stop handler control",
            input_data=_json_bytes(
                {"hook_event_name": "Stop", "stop_hook_active": active}
            ),
        )

    blocked = invoke(False)
    try:
        payload = json.loads(blocked.stdout.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SmokeError(
            f"generated {provider} Stop handler did not emit native JSON"
        ) from exc
    if (
        blocked.returncode != 0
        or blocked.stderr
        or not isinstance(payload, Mapping)
        or set(payload) != {"decision", "reason"}
        or payload.get("decision") != "block"
        or "RARV step 4" not in str(payload.get("reason", ""))
        or STOP_SENTINEL not in str(payload.get("reason", ""))
    ):
        raise SmokeError(
            f"generated {provider} Stop handler did not request native continuation"
        )
    guarded = invoke(True)
    if guarded.returncode != 0 or guarded.stdout.strip() or guarded.stderr.strip():
        raise SmokeError(f"generated {provider} Stop loop guard did not stay silent")
    return hashlib.sha256(blocked.stdout).hexdigest()


def _snapshot(project: Path) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for path in sorted(project.rglob("*")):
        relative = path.relative_to(project)
        if (
            ".git" in relative.parts
            or relative in {EVENT_LOG, PIPELINE_SNAPSHOT}
            or relative.parts[: len(PIPELINE_EVIDENCE_DIR.parts)]
            == PIPELINE_EVIDENCE_DIR.parts
        ):
            continue
        if path.is_symlink():
            raise SmokeError(f"fixture contains an unexpected symlink: {relative}")
        if not path.is_file():
            continue
        mode = stat.S_IMODE(path.stat().st_mode)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        snapshot[relative.as_posix()] = f"{mode:04o}:{digest}"
    return snapshot


def _assert_tree_has_no_plaintext(
    root: Path, sensitive_values: Sequence[str], *, label: str
) -> None:
    encoded = [value.encode("utf-8") for value in sensitive_values]
    for path in root.rglob("*"):
        if path.is_symlink():
            raise SmokeError(f"protected {label} contains an unexpected symlink")
        if not path.is_file():
            continue
        overlap = max((len(value) for value in encoded), default=1) - 1
        tail = b""
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(65_536)
                if not chunk:
                    break
                data = tail + chunk
                if any(value in data for value in encoded):
                    raise SmokeError(
                        f"protected {label} leaked a plaintext credential/canary: "
                        f"{path.name}"
                    )
                tail = data[-overlap:] if overlap else b""


def _assert_control_has_no_plaintext(
    control: Path, sensitive_values: Sequence[str]
) -> None:
    _assert_tree_has_no_plaintext(
        control, sensitive_values, label="coordinator control"
    )


def _installed_gate_digest(project: Path) -> str:
    snapshot = project / ".ckit/config/stack-catalog.snapshot.yaml"
    try:
        lines = snapshot.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise SmokeError(f"installed stack snapshot is missing: {exc}") from exc
    values = [
        line.split(":", 1)[1].strip()
        for line in lines
        if line.startswith("gate_definition_digest:")
    ]
    if len(values) != 1 or len(values[0]) != 64:
        raise SmokeError(
            "installed stack snapshot has no unique gate-definition digest"
        )
    try:
        bytes.fromhex(values[0])
    except ValueError as exc:
        raise SmokeError("installed gate-definition digest is not hexadecimal") from exc
    return values[0]


def _scaffold_inventory(project: Path) -> dict[str, Any]:
    manifest = project / ".ckit/config/init-options.json"
    try:
        document = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SmokeError(
            f"built-wheel scaffold manifest is missing or invalid: {exc}"
        ) from exc
    if document.get("schema_version") != INIT_OPTIONS_SCHEMA_VERSION or document.get(
        "runtimes"
    ) != ["claude", "codex"]:
        raise SmokeError(
            "built-wheel scaffold did not install the exact both-runtime contract"
        )
    state_layout = document.get("state_layout")
    if not isinstance(state_layout, Mapping) or state_layout.get("root") != ".ckit":
        raise SmokeError(
            "built-wheel scaffold did not install the shared .ckit state layout"
        )
    required = {
        ".claude/skills/using-agent-skills/SKILL.md": (
            "claude",
            "skill://using-agent-skills",
        ),
        ".agents/skills/using-agent-skills/SKILL.md": (
            "codex",
            "skill://using-agent-skills",
        ),
        ".claude/agents/risk-classifier.md": ("claude", "agent://risk-classifier"),
        ".codex/agents/risk-classifier.toml": ("codex", "agent://risk-classifier"),
        ".claude/settings.json": (
            "claude",
            "artifact://claude-claude-settings.json",
        ),
        ".codex/hooks.json": ("codex", "artifact://codex-hooks"),
    }
    raw_files = document.get("files")
    if not isinstance(raw_files, list):
        raise SmokeError("built-wheel scaffold file inventory is invalid")
    by_path = {
        str(item.get("path")): item
        for item in raw_files
        if isinstance(item, Mapping) and isinstance(item.get("path"), str)
    }
    selected: dict[str, dict[str, str]] = {}
    for path, (provider, component_id) in required.items():
        record = by_path.get(path)
        if not isinstance(record, Mapping):
            raise SmokeError(
                f"built-wheel scaffold omitted required native surface: {path}"
            )
        if (
            record.get("provider") != provider
            or record.get("component_id") != component_id
        ):
            raise SmokeError(f"built-wheel inventory ownership is wrong for: {path}")
        expected_hash = record.get("sha256")
        installed = project / path
        if (
            not isinstance(expected_hash, str)
            or hashlib.sha256(installed.read_bytes()).hexdigest() != expected_hash
        ):
            raise SmokeError(f"built-wheel inventory checksum is wrong for: {path}")
        selected[path] = {
            "provider": provider,
            "component_id": component_id,
            "sha256": expected_hash,
        }
    version = document.get("claude_kit_version")
    if not isinstance(version, str) or not version:
        raise SmokeError("built-wheel scaffold has no package version")
    return {
        "claude_kit_version": version,
        "runtimes": ["claude", "codex"],
        "state_root": ".ckit",
        "selected_native_inventory": selected,
    }


def _append_instruction_nonce(path: Path, provider: str, nonce: str) -> None:
    original = path.read_text(encoding="utf-8")
    _write_text(
        path,
        original.rstrip()
        + "\n\n## Protected native-host probe\n\n"
        + f"The {provider} project instruction nonce is `{nonce}`. Report it only when the "
        "protected conformance prompt asks for it.\n",
    )


def _append_risk_classifier_nonces(
    project: Path, *, claude_nonce: str, codex_nonce: str
) -> None:
    claude_path = project / ".claude/agents/risk-classifier.md"
    claude_text = claude_path.read_text(encoding="utf-8")
    _write_text(
        claude_path,
        claude_text.rstrip()
        + "\n\n## Protected native-host probe\n\n"
        + "When the protected conformance prompt delegates to you, also return agent nonce "
        + f"`{claude_nonce}`.\n",
    )

    codex_path = project / ".codex/agents/risk-classifier.toml"
    lines = codex_path.read_text(encoding="utf-8").splitlines()
    prefix = "developer_instructions = "
    matching = [index for index, line in enumerate(lines) if line.startswith(prefix)]
    if len(matching) != 1:
        raise SmokeError(
            "generated Codex risk-classifier instructions are not uniquely editable"
        )
    index = matching[0]
    try:
        instructions = json.loads(lines[index][len(prefix) :])
    except json.JSONDecodeError as exc:
        raise SmokeError(
            "generated Codex agent instructions are not a TOML basic string"
        ) from exc
    if not isinstance(instructions, str):
        raise SmokeError("generated Codex agent instructions are not text")
    instructions = (
        instructions.rstrip()
        + "\n\n## Protected native-host probe\n\n"
        + "When the protected conformance prompt delegates to you, also return agent nonce "
        + f"`{codex_nonce}`.\n"
    )
    lines[index] = prefix + _toml_string(instructions)
    _write_text(codex_path, "\n".join(lines) + "\n")


def _prepare(
    root: Path, *, ckit_executable: str, direction: str = "claude-codex"
) -> None:
    try:
        provider_order = PROVIDER_ORDERS[direction]
    except KeyError as exc:
        raise SmokeError(
            f"unsupported protected provider direction: {direction}"
        ) from exc
    resolved, project, control = _paths(root)
    if resolved.exists():
        raise SmokeError(
            f"smoke root already exists; refusing to overwrite it: {resolved}"
        )
    resolved.mkdir(mode=0o700, parents=True)
    control.mkdir(mode=0o700)
    (control / "hook-home").mkdir(mode=0o700)

    executable = shutil.which(ckit_executable)
    if executable is None:
        raise SmokeError(
            f"built-wheel ckit executable is unavailable: {ckit_executable}"
        )
    executable = str(Path(executable).resolve(strict=True))
    scaffold_home = control / "scaffold-home"
    scaffold_home.mkdir(mode=0o700)
    scaffold_env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(scaffold_home),
        "CKIT_EXPERIMENTAL": "1",
        "NO_COLOR": "1",
    }
    scaffolded = subprocess.run(  # noqa: S603 - executable resolved with shutil.which
        [executable, "init", str(project), "--defaults", "--runtime", "both"],
        cwd=resolved,
        env=scaffold_env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    if scaffolded.returncode != 0:
        raise SmokeError(
            "built-wheel both-runtime scaffold failed\n"
            f"stdout:\n{_bounded(scaffolded.stdout)}\n"
            f"stderr:\n{_bounded(scaffolded.stderr)}"
        )
    inventory = _scaffold_inventory(project)
    installed_gate_digest = _installed_gate_digest(project)
    inventory["installed_gate_definition_digest"] = installed_gate_digest

    expected = {
        provider: {
            "instruction_nonce": _nonce(f"{provider}-instruction"),
            "skill_nonce": _nonce(f"{provider}-skill"),
            "skill_argument": SKILL_ARGUMENT,
            "real_skill_marker": REAL_SKILL_MARKER,
            "agent_nonce": _nonce(f"{provider}-agent"),
            "role_result": "low",
            "gate_digest": "pending-mode-projection",
            "blocking_reason": BLOCK_REASON,
            "advisory_marker": ADVISORY_MARKER,
        }
        for provider in ("claude", "codex")
    }
    blocked_canary = _nonce("blocked-canary")

    _append_instruction_nonce(
        project / "CLAUDE.md", "Claude", expected["claude"]["instruction_nonce"]
    )
    _append_instruction_nonce(
        project / "AGENTS.md", "Codex", expected["codex"]["instruction_nonce"]
    )
    _append_risk_classifier_nonces(
        project,
        claude_nonce=expected["claude"]["agent_nonce"],
        codex_nonce=expected["codex"]["agent_nonce"],
    )

    claude_skill = f"""---
name: ckit-protected-smoke
description: Protected native-host discovery probe. Invoke only when explicitly requested.
disable-model-invocation: true
user-invocable: true
allowed-tools: Read
---

The skill nonce is `{expected["claude"]["skill_nonce"]}`. Return this exact value and the caller-supplied
argument `$ARGUMENTS`. Do not read, write, execute, or inspect anything else while applying this
skill.
"""
    codex_skill = f"""---
name: ckit-protected-smoke
description: Protected native-host discovery probe. Invoke only when explicitly requested.
---

The skill nonce is `{expected["codex"]["skill_nonce"]}`. Return this exact value and the invocation argument
supplied after the skill name. Do not read, write, execute, or inspect anything else while applying
this skill.
"""
    _write_text(project / ".claude/skills/ckit-protected-smoke/SKILL.md", claude_skill)
    _write_text(project / ".agents/skills/ckit-protected-smoke/SKILL.md", codex_skill)
    _write_text(
        project / ".agents/skills/ckit-protected-smoke/agents/openai.yaml",
        "interface:\n"
        "  display_name: Protected Host Smoke\n"
        "  short_description: Read-only protected native-host discovery probe.\n"
        "policy:\n"
        "  allow_implicit_invocation: false\n",
    )

    generated_guard_contract: dict[str, dict[str, str]] = {}
    generated_stop_contract: dict[str, dict[str, str]] = {}
    generated_stop_handlers: dict[str, str] = {}
    for provider, artifact in (
        ("claude", ".claude/settings.json"),
        ("codex", ".codex/hooks.json"),
    ):
        guard_hash, stop_hash, stop_handler = _merge_probe_hooks(
            project / artifact,
            root,
            provider,
            ckit_executable=executable,
        )
        generated_guard_contract[provider] = {
            "handler_id": "protect-secrets",
            "source_artifact": artifact,
            "command_sha256": guard_hash,
        }
        generated_stop_contract[provider] = {
            "handler_id": "verify-continuity-writeback",
            "source_artifact": artifact,
            "command_sha256": stop_hash,
        }
        generated_stop_handlers[provider] = stop_handler
    _write_text(project / BLOCK_TARGET, blocked_canary)
    _write_json(control / "output-schema.json", OUTPUT_SCHEMA)

    git = shutil.which("git")
    if git is None:
        raise SmokeError("git is required to prepare the native-host fixture")

    def run_git(*arguments: str, expected_returncode: int = 0) -> None:
        completed = subprocess.run(  # noqa: S603 - executable resolved with shutil.which
            [git, *arguments],
            cwd=project,
            env=scaffold_env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        if completed.returncode != expected_returncode:
            raise SmokeError(
                f"git {' '.join(arguments)} failed ({completed.returncode})\n"
                f"stdout:\n{_bounded(completed.stdout)}\n"
                f"stderr:\n{_bounded(completed.stderr)}"
            )

    run_git("init", "--quiet")
    _write_text(project / ".git/info/exclude", f"/{BLOCK_TARGET}\n")
    run_git("symbolic-ref", "HEAD", "refs/heads/main")
    run_git("config", "user.email", "protected-smoke@example.invalid")
    run_git("config", "user.name", "Protected Host Smoke")
    run_git("check-ignore", "--quiet", "--", BLOCK_TARGET)
    run_git("add", "-A")
    run_git("commit", "--quiet", "-m", "protected native-host fixture")

    started = subprocess.run(  # noqa: S603 - executable resolved with shutil.which
        [
            executable,
            "pipeline",
            "start",
            str(project),
            "--task",
            "protected native-host surface probe",
            "--mode",
            "D",
        ],
        cwd=project,
        env=scaffold_env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    if started.returncode != 0:
        raise SmokeError(
            "exact-wheel pipeline start failed\n"
            f"stdout:\n{_bounded(started.stdout)}\n"
            f"stderr:\n{_bounded(started.stderr)}"
        )
    pipeline = _pipeline_document(project)
    if (
        pipeline.get("status") != "active"
        or pipeline.get("stage") != "code-review"
        or pipeline.get("mode") != "D"
        or pipeline.get("ordered_gates") != ["code-review", "build-green"]
        or pipeline.get("gate_history") != []
    ):
        raise SmokeError("exact-wheel Mode D pipeline did not start at code-review")
    run_gate_digest = pipeline.get("gate_definition_digest")
    if not isinstance(run_gate_digest, str) or len(run_gate_digest) != 64:
        raise SmokeError("exact-wheel Mode D pipeline has no gate-definition digest")
    try:
        bytes.fromhex(run_gate_digest)
    except ValueError as exc:
        raise SmokeError("Mode D gate-definition digest is not hexadecimal") from exc
    for provider in ("claude", "codex"):
        expected[provider]["gate_digest"] = run_gate_digest

    continuity = project / ".ckit/CONTINUITY.md"
    if not continuity.is_file() or continuity.is_symlink():
        raise SmokeError("exact-wheel scaffold has no safe shared continuity file")
    stop_sentinel = project / STOP_SENTINEL
    _write_text(stop_sentinel, "intentional stale-continuity positive control\n")
    os.utime(continuity, (1_700_000_000, 1_700_000_000))
    os.utime(stop_sentinel, (1_700_000_010, 1_700_000_010))
    for provider in ("claude", "codex"):
        generated_stop_contract[provider]["expected_block_stdout_sha256"] = (
            _stop_handler_positive_control(
                provider=provider,
                handler=generated_stop_handlers[provider],
                project=project,
                control=control,
                ckit_executable=executable,
            )
        )

    expected_commitments = {
        provider: {
            field: _commitment(provider, field, str(expected[provider][field]))
            for field in CONTROL_EXPECTED_FIELDS
        }
        for provider in ("claude", "codex")
    }
    sensitive_values = [
        expected[provider][field]
        for provider in ("claude", "codex")
        for field in ("instruction_nonce", "skill_nonce", "agent_nonce")
    ] + [blocked_canary]
    control_document = {
        "schema_version": SCHEMA_VERSION,
        "expected_commitments": expected_commitments,
        "blocked_canary_commitment": _commitment(
            "shared", "blocked_canary", blocked_canary
        ),
        "generated_guard_contract": generated_guard_contract,
        "generated_stop_contract": generated_stop_contract,
        "ckit_executable": executable,
        "provider_order": list(provider_order),
        "pipeline_checkpoints": {
            provider: (
                hashlib.sha256((project / PIPELINE_SNAPSHOT).read_bytes()).hexdigest()
                if provider == provider_order[0]
                else None
            )
            for provider in ("claude", "codex")
        },
        "scaffold": inventory,
        "project_snapshot": _snapshot(project),
    }
    _write_json(control / CONTROL_FILE, control_document)
    _assert_control_has_no_plaintext(control, sensitive_values)
    print(json.dumps({"prepared": str(resolved), "schema_version": SCHEMA_VERSION}))


def _load_control(root: Path) -> tuple[Path, Path, Path, dict[str, Any]]:
    resolved, project, control = _paths(root)
    try:
        document = json.loads((control / CONTROL_FILE).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SmokeError(
            f"prepared smoke control is missing or invalid: {exc}"
        ) from exc
    if document.get("schema_version") != SCHEMA_VERSION:
        raise SmokeError("protected smoke control schema version does not match")
    if not project.is_dir() or not control.is_dir():
        raise SmokeError("prepared smoke project/control directories are missing")
    if "expected" in document or "blocked_canary" in document:
        raise SmokeError("protected smoke control contains a legacy plaintext oracle")
    expected = document.get("expected_commitments")
    if (
        not isinstance(expected, dict)
        or set(expected) != {"claude", "codex"}
        or any(
            not isinstance(expected.get(provider), dict)
            or set(expected[provider]) != set(CONTROL_EXPECTED_FIELDS)
            or not all(_is_sha256(value) for value in expected[provider].values())
            for provider in ("claude", "codex")
        )
    ):
        raise SmokeError("protected smoke commitment contract is invalid")
    if not _is_sha256(document.get("blocked_canary_commitment")):
        raise SmokeError("protected smoke canary commitment is invalid")
    guard_contract = document.get("generated_guard_contract")
    if (
        not isinstance(guard_contract, dict)
        or set(guard_contract) != {"claude", "codex"}
        or any(
            not isinstance(guard_contract.get(provider), dict)
            or guard_contract[provider].get("handler_id") != "protect-secrets"
            or not isinstance(guard_contract[provider].get("source_artifact"), str)
            or not _is_sha256(guard_contract[provider].get("command_sha256"))
            for provider in ("claude", "codex")
        )
    ):
        raise SmokeError("protected generated-guard contract is invalid")
    stop_contract = document.get("generated_stop_contract")
    if (
        not isinstance(stop_contract, dict)
        or set(stop_contract) != {"claude", "codex"}
        or any(
            not isinstance(stop_contract.get(provider), dict)
            or stop_contract[provider].get("handler_id")
            != "verify-continuity-writeback"
            or not isinstance(stop_contract[provider].get("source_artifact"), str)
            or not _is_sha256(stop_contract[provider].get("command_sha256"))
            or not _is_sha256(
                stop_contract[provider].get("expected_block_stdout_sha256")
            )
            for provider in ("claude", "codex")
        )
    ):
        raise SmokeError("protected generated-Stop contract is invalid")
    executable = document.get("ckit_executable")
    if not isinstance(executable, str) or not Path(executable).is_file():
        raise SmokeError("prepared smoke exact-wheel executable is missing")
    provider_order = document.get("provider_order")
    if tuple(provider_order) not in set(PROVIDER_ORDERS.values()):
        raise SmokeError("protected provider order is invalid")
    checkpoints = document.get("pipeline_checkpoints")
    if (
        not isinstance(checkpoints, dict)
        or set(checkpoints) != {"claude", "codex"}
        or not isinstance(checkpoints.get(provider_order[0]), str)
        or (
            checkpoints.get(provider_order[1]) is not None
            and not isinstance(checkpoints.get(provider_order[1]), str)
        )
    ):
        raise SmokeError("protected pipeline checkpoint contract is invalid")
    managed_proof = document.get("managed_codex")
    if managed_proof is not None:
        expected_fields = {
            "schema_version",
            "provider",
            "host_version",
            "run_id",
            "stage",
            "role",
            "required_capabilities",
            "gate_owners",
            "stop_reason",
            "evidence",
            "terminal_artifact",
            "snapshot_sha256",
        }
        if (
            not isinstance(managed_proof, dict)
            or set(managed_proof) != expected_fields
            or managed_proof.get("schema_version") != 1
            or managed_proof.get("provider") != "codex"
            or not isinstance(managed_proof.get("host_version"), str)
            or not isinstance(managed_proof.get("run_id"), str)
            or managed_proof.get("stage") != MANAGED_PASSIVE_STAGE
            or managed_proof.get("role") != MANAGED_PASSIVE_ROLE
            or managed_proof.get("required_capabilities")
            != list(MANAGED_PASSIVE_CAPABILITIES)
            or managed_proof.get("gate_owners") != MANAGED_GATE_OWNERS
            or managed_proof.get("stop_reason") != "unsupported-required-capability"
            or not _is_sha256(managed_proof.get("snapshot_sha256"))
            or any(
                not isinstance(managed_proof.get(field), dict)
                or set(managed_proof[field]) != {"path", "sha256"}
                or not isinstance(managed_proof[field].get("path"), str)
                or not _is_sha256(managed_proof[field].get("sha256"))
                for field in ("evidence", "terminal_artifact")
            )
        ):
            raise SmokeError("protected managed Codex proof contract is invalid")
    gate_owner_proof = document.get("managed_codex_gate_owner")
    if gate_owner_proof is not None:
        expected_fields = {
            "schema_version",
            "provider",
            "host_version",
            "run_id",
            "stage",
            "role",
            "required_capabilities",
            "gate",
            "native_host_claim",
            "fixture_seed",
            "evidence",
            "terminal_artifact",
            "gate_bundle",
            "gate_history_digest",
            "snapshot_sha256",
        }
        seed = (
            gate_owner_proof.get("fixture_seed")
            if isinstance(gate_owner_proof, dict)
            else None
        )
        evidence = (
            gate_owner_proof.get("evidence")
            if isinstance(gate_owner_proof, dict)
            else None
        )
        if (
            not isinstance(gate_owner_proof, dict)
            or set(gate_owner_proof) != expected_fields
            or gate_owner_proof.get("schema_version") != 1
            or gate_owner_proof.get("provider") != "codex"
            or not isinstance(gate_owner_proof.get("host_version"), str)
            or not isinstance(gate_owner_proof.get("run_id"), str)
            or gate_owner_proof.get("stage") != MANAGED_GATE_OWNER_STAGE
            or gate_owner_proof.get("role") != MANAGED_GATE_OWNER_ROLE
            or gate_owner_proof.get("required_capabilities")
            != list(MANAGED_GATE_OWNER_CAPABILITIES)
            or gate_owner_proof.get("gate") != MANAGED_GATE_OWNER_GATE
            or gate_owner_proof.get("native_host_claim") is not True
            or not _is_sha256(gate_owner_proof.get("gate_history_digest"))
            or not _is_sha256(gate_owner_proof.get("snapshot_sha256"))
            or not isinstance(seed, dict)
            or seed.get("kind") != "protected-fixture-seed"
            or seed.get("native_host_claim") is not False
            or seed.get("run_id") != gate_owner_proof.get("run_id")
            or seed.get("seeded_stages") != list(MANAGED_GATE_SEED_STAGES)
            or not isinstance(evidence, dict)
            or set(evidence) != {"architecture-plan", "planning-decision"}
            or any(
                not isinstance(value, dict)
                or set(value) != {"path", "sha256"}
                or not isinstance(value.get("path"), str)
                or not _is_sha256(value.get("sha256"))
                for value in evidence.values()
            )
            or any(
                not isinstance(gate_owner_proof.get(field), dict)
                or set(gate_owner_proof[field]) != {"path", "sha256"}
                or not isinstance(gate_owner_proof[field].get("path"), str)
                or not _is_sha256(gate_owner_proof[field].get("sha256"))
                for field in ("terminal_artifact", "gate_bundle")
            )
        ):
            raise SmokeError("protected managed gate-owner proof contract is invalid")
    return resolved, project, control, document


def _assert_no_provider_secret_env() -> None:
    present = sorted(name for name in PROVIDER_SECRET_ENV if os.environ.get(name))
    if present:
        raise SmokeError(
            "provider credentials must not be inherited by repository code: "
            + ", ".join(present)
        )


def _bounded(value: str) -> str:
    data = value.encode("utf-8", errors="replace")
    if len(data) > MAX_HOST_OUTPUT_BYTES:
        raise SmokeError("host output exceeded the protected 1 MiB limit")
    return value


def _run_bounded_process(
    argv: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    timeout: int,
    label: str,
    input_data: bytes | None = None,
) -> subprocess.CompletedProcess[bytes]:
    """Run a child while retaining at most 1 MiB + 1 byte from each output stream."""
    process = subprocess.Popen(  # noqa: S603 - callers resolve trusted executables
        list(argv),
        cwd=cwd,
        env=dict(env),
        stdin=subprocess.PIPE if input_data is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if (
        process.stdout is None or process.stderr is None
    ):  # pragma: no cover - Popen contract
        process.kill()
        raise SmokeError(f"{label} could not open bounded output pipes")
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    exceeded = threading.Event()

    def drain(name: str, stream: Any) -> None:
        while True:
            chunk = stream.read(65_536)
            if not chunk:
                break
            buffer = buffers[name]
            room = MAX_HOST_OUTPUT_BYTES + 1 - len(buffer)
            if room > 0:
                buffer.extend(chunk[:room])
            if len(chunk) > room or len(buffer) > MAX_HOST_OUTPUT_BYTES:
                exceeded.set()
                try:
                    process.kill()
                except ProcessLookupError:
                    pass

    threads = [
        threading.Thread(target=drain, args=("stdout", process.stdout), daemon=True),
        threading.Thread(target=drain, args=("stderr", process.stderr), daemon=True),
    ]
    for thread in threads:
        thread.start()
    if input_data is not None:
        if process.stdin is None:  # pragma: no cover - Popen contract
            process.kill()
            raise SmokeError(f"{label} could not open the input pipe")
        try:
            process.stdin.write(input_data)
            process.stdin.flush()
        except BrokenPipeError:
            pass
        finally:
            process.stdin.close()
    try:
        returncode = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.wait()
        for thread in threads:
            thread.join()
        raise SmokeError(f"{label} exceeded its protected timeout") from exc
    for thread in threads:
        thread.join()
    if exceeded.is_set():
        raise SmokeError(f"{label} output exceeded the protected 1 MiB limit")
    return subprocess.CompletedProcess(
        args=list(argv),
        returncode=returncode,
        stdout=bytes(buffers["stdout"]),
        stderr=bytes(buffers["stderr"]),
    )


def _decode_host_output(value: bytes, *, label: str) -> str:
    try:
        return value.decode("utf-8")
    except UnicodeError as exc:
        raise SmokeError(f"{label} was not valid UTF-8") from exc


def _output_summary(label: str, value: str) -> str:
    data = value.encode("utf-8", errors="replace")
    return (
        f"{label}_bytes={len(data)} {label}_sha256={hashlib.sha256(data).hexdigest()}"
    )


def _find_observation(value: Any) -> dict[str, str] | None:
    if isinstance(value, Mapping):
        if all(isinstance(value.get(field), str) for field in REQUIRED_FIELDS):
            return {field: str(value[field]) for field in REQUIRED_FIELDS}
        for key in ("structured_output", "result", "output", "message", "text"):
            nested = value.get(key)
            found = _find_observation(nested)
            if found is not None:
                return found
        for nested in value.values():
            found = _find_observation(nested)
            if found is not None:
                return found
        return None
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for nested in value:
            found = _find_observation(nested)
            if found is not None:
                return found
        return None
    if isinstance(value, str):
        candidate = value.strip()
        if candidate.startswith("```") and candidate.endswith("```"):
            lines = candidate.splitlines()
            candidate = "\n".join(lines[1:-1]).strip()
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            return None
        return _find_observation(parsed)
    return None


def _extract_observation(output: str) -> dict[str, str]:
    bounded = _bounded(output)
    try:
        parsed = json.loads(bounded)
    except json.JSONDecodeError:
        parsed = None
    found = _find_observation(parsed)
    if found is not None:
        return found
    for line in reversed(bounded.splitlines()):
        try:
            parsed_line = json.loads(line)
        except json.JSONDecodeError:
            continue
        found = _find_observation(parsed_line)
        if found is not None:
            return found
    raise SmokeError("host output did not contain the required structured observation")


def _events(project: Path, provider: str) -> list[dict[str, Any]]:
    path = project / EVENT_LOG
    if not path.is_file():
        raise SmokeError(f"{provider} did not execute any protected fixture hooks")
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SmokeError(f"protected hook event log is invalid: {exc}") from exc
        if event.get("provider") == provider:
            events.append(event)
    return events


def _assert_events(
    project: Path, provider: str, document: Mapping[str, Any]
) -> dict[str, int]:
    events = _events(project, provider)
    counts = {
        name: sum(event.get("event") == name for event in events)
        for name in (
            "session-start",
            "subagent-start",
            "post-tool",
            "stop",
        )
    }
    if counts["session-start"] != 1:
        raise SmokeError(
            f"{provider} SessionStart count was {counts['session-start']}, expected exactly 1"
        )
    if counts["subagent-start"] < 1:
        raise SmokeError(f"{provider} did not emit a SubagentStart positive control")
    named_agent_events = [
        event
        for event in events
        if event.get("event") == "subagent-start"
        and event.get("agent_type") == "risk-classifier"
        and event.get("risk_classifier") is True
    ]
    if len(named_agent_events) != 1:
        raise SmokeError(
            f"{provider} native risk-classifier start count was "
            f"{len(named_agent_events)}, expected exactly 1"
        )
    definition_reads = [
        event
        for event in events
        if event.get("read_boundary_violation") is not None
        or event.get("definition_path") in PROTECTED_DISCOVERY_PATHS[provider]
    ]
    if definition_reads:
        raise SmokeError(
            f"{provider} requested a read outside the protected fixture allowlist"
        )
    guard_contracts = document.get("generated_guard_contract")
    guard_contract = (
        guard_contracts.get(provider) if isinstance(guard_contracts, Mapping) else None
    )
    if not isinstance(guard_contract, Mapping):
        raise SmokeError(f"{provider} generated-guard contract is invalid")
    expected_hash = str(guard_contract.get("command_sha256", ""))
    guard_events = [
        event
        for event in events
        if event.get("event") == "generated-guard"
        and event.get("handler_id") == "protect-secrets"
    ]
    if not guard_events or any(
        event.get("record_schema_version") != 1
        or event.get("handler_sha256") != expected_hash
        for event in guard_events
    ):
        raise SmokeError(
            f"{provider} did not execute the exact scaffolded protect-secrets handler"
        )
    derived = [_recorded_guard_disposition(provider, event) for event in guard_events]
    if any(
        disposition == "error"
        or event.get("generated_guard_disposition") != disposition
        for event, disposition in zip(guard_events, derived)
    ):
        raise SmokeError(
            f"{provider} generated protect-secrets handler reported an error"
        )
    expected_operation = "file-read" if provider == "claude" else "shell"
    target_guards = [
        (event, disposition)
        for event, disposition in zip(guard_events, derived)
        if event.get("target_requested") is True
    ]
    blocked = [
        event
        for event, disposition in target_guards
        if disposition == "block"
        and event.get("native_operation") == expected_operation
    ]
    allowed = [
        event
        for event, disposition in zip(guard_events, derived)
        if disposition == "allow" and event.get("target_requested") is False
    ]
    counts["generated-guard-block"] = len(blocked)
    counts["generated-guard-allow"] = len(allowed)
    if len(target_guards) != 1:
        raise SmokeError(
            f"{provider} generated guard target request count was "
            f"{len(target_guards)}, expected exactly 1"
        )
    if derived.count("block") != 1 or len(blocked) != 1:
        raise SmokeError(
            f"{provider} generated guard block count was {derived.count('block')}, "
            "expected exactly 1"
        )
    if not allowed:
        raise SmokeError(f"{provider} generated guard has no harmless allow control")
    if counts["post-tool"] < 1:
        raise SmokeError(f"{provider} did not execute the PostToolUse advisory control")
    if any(
        event.get("event") == "post-tool" and event.get("target_requested") is True
        for event in events
    ):
        raise SmokeError(
            f"{provider} emitted PostToolUse after the protected target read"
        )
    stop_contracts = document.get("generated_stop_contract")
    stop_contract = (
        stop_contracts.get(provider) if isinstance(stop_contracts, Mapping) else None
    )
    if not isinstance(stop_contract, Mapping):
        raise SmokeError(f"{provider} generated-Stop contract is invalid")
    stop_events = [
        event
        for event in events
        if event.get("event") == "generated-stop"
        and event.get("handler_id") == "verify-continuity-writeback"
    ]
    if not stop_events or any(
        event.get("record_schema_version") != 1
        or event.get("handler_sha256") != stop_contract.get("command_sha256")
        for event in stop_events
    ):
        raise SmokeError(
            f"{provider} did not execute the exact scaffolded continuity Stop handler"
        )
    stop_derived = [
        _recorded_stop_disposition(event, stop_contract) for event in stop_events
    ]
    if any(
        disposition == "error" or event.get("generated_stop_disposition") != disposition
        for event, disposition in zip(stop_events, stop_derived)
    ):
        raise SmokeError(
            f"{provider} generated continuity Stop handler reported an error"
        )
    if stop_derived.count("block") != 1 or stop_derived.count("allow") < 1:
        raise SmokeError(
            f"{provider} generated Stop continuation/loop-guard counts were "
            f"{stop_derived.count('block')}/{stop_derived.count('allow')}, expected 1/>=1"
        )
    counts["stop"] = len(stop_events)
    counts["generated-stop-block"] = stop_derived.count("block")
    counts["generated-stop-loop-allow"] = stop_derived.count("allow")
    leaked = sorted(
        {
            str(name)
            for event in events
            for name in event.get("credential_env_present", [])
        }
    )
    if leaked:
        raise SmokeError(f"{provider} hook inherited credential variables: {leaked}")
    return counts


def _pipeline_document(project: Path) -> dict[str, Any]:
    path = project / PIPELINE_SNAPSHOT
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SmokeError(
            f"shared pipeline snapshot is missing or invalid: {exc}"
        ) from exc
    history = document.get("gate_history")
    if (
        document.get("schema_version") != 2
        or not isinstance(document.get("gate_definition_digest"), str)
        or not isinstance(document.get("stage"), str)
        or not isinstance(history, list)
    ):
        raise SmokeError("shared pipeline snapshot has an invalid contract")
    return document


def _assert_pipeline_checkpoint(
    document: Mapping[str, Any], project: Path, provider: str
) -> None:
    checkpoints = document.get("pipeline_checkpoints")
    expected = checkpoints.get(provider) if isinstance(checkpoints, Mapping) else None
    if not isinstance(expected, str):
        raise SmokeError(
            f"{provider} pipeline checkpoint is not coordinator-authorized"
        )
    actual = hashlib.sha256((project / PIPELINE_SNAPSHOT).read_bytes()).hexdigest()
    if actual != expected:
        raise SmokeError(f"{provider} host mutated the authoritative pipeline snapshot")


def _prior_pipeline_provider(project: Path, pipeline: Mapping[str, Any]) -> str:
    history = pipeline.get("gate_history")
    if not isinstance(history, list) or not history:
        return "none"
    last = history[-1]
    if not isinstance(last, Mapping) or not isinstance(last.get("evidence_path"), str):
        raise SmokeError("latest pipeline gate has no evidence path")
    evidence_root = (project / PIPELINE_EVIDENCE_DIR).resolve(strict=False)
    evidence = (project / str(last["evidence_path"])).resolve(strict=False)
    try:
        evidence.relative_to(evidence_root)
    except ValueError as exc:
        raise SmokeError(
            "latest pipeline gate evidence is outside the smoke evidence root"
        ) from exc
    try:
        receipt = json.loads(evidence.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SmokeError(f"latest pipeline gate evidence is invalid: {exc}") from exc
    provider = receipt.get("provider")
    if provider not in {"claude", "codex"}:
        raise SmokeError("latest pipeline gate evidence has no valid provider")
    return str(provider)


def _observation_commitments(
    provider: str, observation: Mapping[str, str]
) -> dict[str, str]:
    return {
        field: _commitment(provider, field, str(observation[field]))
        for field in REQUIRED_FIELDS
    }


def _assert_observation(
    document: Mapping[str, Any],
    project: Path,
    provider: str,
    observation: Mapping[str, str],
    raw_output: str,
) -> dict[str, str]:
    if provider not in {"claude", "codex"} or set(observation) != set(REQUIRED_FIELDS):
        raise SmokeError("host observation does not match the required field contract")
    raw_expected = document.get("expected_commitments")
    expected = raw_expected.get(provider) if isinstance(raw_expected, Mapping) else None
    if not isinstance(expected, Mapping):
        raise SmokeError("protected expected commitment contract is invalid")

    pipeline = _pipeline_document(project)
    history = pipeline["gate_history"]
    expected_dynamic = {
        "pipeline_stage": str(pipeline["stage"]),
        "gate_history_count": str(len(history)),
        "prior_provider_transition": _prior_pipeline_provider(project, pipeline),
    }
    mismatches = [
        field
        for field, value in expected_dynamic.items()
        if observation.get(field) != value
    ]
    if observation.get("gate_digest") != pipeline["gate_definition_digest"]:
        mismatches.append("gate_digest")

    commitments = _observation_commitments(provider, observation)
    mismatches.extend(
        field
        for field in CONTROL_EXPECTED_FIELDS
        if not hmac.compare_digest(commitments[field], str(expected.get(field, "")))
        and field not in mismatches
    )
    if mismatches:
        raise SmokeError("host observation mismatch for: " + ", ".join(mismatches))

    canary_commitment = str(document.get("blocked_canary_commitment", ""))
    leaked_candidates = CANARY_PATTERN.findall(raw_output)
    if (
        any(
            hmac.compare_digest(
                _commitment("shared", "blocked_canary", candidate),
                canary_commitment,
            )
            for candidate in leaked_candidates
        )
        or "blocked-canary-" in raw_output
    ):
        raise SmokeError("blocking-hook positive control leaked the protected canary")
    return commitments


def _assert_project_unchanged(project: Path, document: Mapping[str, Any]) -> None:
    current = _snapshot(project)
    raw_expected = document.get("project_snapshot")
    if not isinstance(raw_expected, Mapping) or not all(
        isinstance(path, str) and isinstance(value, str)
        for path, value in raw_expected.items()
    ):
        raise SmokeError("protected fixture snapshot contract is invalid")
    expected = {str(path): str(value) for path, value in raw_expected.items()}
    if current != expected:
        added = sorted(set(current) - set(expected))
        removed = sorted(set(expected) - set(current))
        changed = sorted(
            path
            for path in set(current) & set(expected)
            if current[path] != expected[path]
        )
        raise SmokeError(
            "read-only native-host run mutated the fixture "
            f"(added={added}, removed={removed}, changed={changed})"
        )


def _host_environment(root: Path) -> dict[str, str]:
    _resolved, _project, control = _paths(root)
    home = control / "claude-home"
    claude_config = control / "claude-config"
    xdg_config = control / "xdg-config"
    temporary = control / "tmp"
    for directory in (home, claude_config, xdg_config, temporary):
        directory.mkdir(mode=0o700, exist_ok=True)
    environment = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(home),
        "CLAUDE_CONFIG_DIR": str(claude_config),
        "XDG_CONFIG_HOME": str(xdg_config),
        "TMPDIR": str(temporary),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "CI": "true",
        "NO_COLOR": "1",
        "CLAUDE_CODE_API_KEY_HELPER_TTL_MS": "3600000",
    }
    for name in (
        "ALL_PROXY",
        "HTTPS_PROXY",
        "HTTP_PROXY",
        "NO_PROXY",
        "SSL_CERT_DIR",
        "SSL_CERT_FILE",
    ):
        if os.environ.get(name):
            environment[name] = os.environ[name]
    return environment


def _private_external_file(path: Path, *, project: Path, label: str) -> Path:
    try:
        resolved = path.expanduser().resolve(strict=True)
    except OSError as exc:
        raise SmokeError(f"{label} is missing: {path}") from exc
    try:
        resolved.relative_to(project.resolve(strict=True))
    except ValueError:
        pass
    else:
        raise SmokeError(f"{label} must be outside the model workspace")
    if not resolved.is_file():
        raise SmokeError(f"{label} is not a regular file: {resolved}")
    if stat.S_IMODE(resolved.stat().st_mode) & 0o077:
        raise SmokeError(f"{label} must not be group/world accessible: {resolved}")
    return resolved


def _write_receipt(
    control: Path,
    *,
    provider: str,
    version: str,
    observation_commitments: Mapping[str, str],
    output: str,
    counts: Mapping[str, int],
) -> Path:
    if set(observation_commitments) != set(REQUIRED_FIELDS) or not all(
        _is_sha256(value) for value in observation_commitments.values()
    ):
        raise SmokeError(f"refusing to write an invalid {provider} commitment receipt")
    receipts = control / "receipts"
    receipts.mkdir(mode=0o700, exist_ok=True)
    receipt = receipts / f"{provider}.json"
    if receipt.exists():
        raise SmokeError(f"refusing to replace an existing {provider} receipt")
    _write_json(
        receipt,
        {
            "schema_version": SCHEMA_VERSION,
            "provider": provider,
            "host_version": version,
            "observation_commitments": dict(observation_commitments),
            "output_sha256": hashlib.sha256(output.encode("utf-8")).hexdigest(),
            "event_counts": dict(counts),
            "read_only_snapshot_preserved": True,
            "pipeline_snapshot_preserved": True,
            "credential_env_in_hooks": [],
        },
    )
    return receipt


def _run_ckit(
    document: Mapping[str, Any],
    project: Path,
    control: Path,
    *arguments: str,
) -> str:
    raw_executable = document.get("ckit_executable")
    if not isinstance(raw_executable, str):
        raise SmokeError("prepared exact-wheel executable contract is invalid")
    try:
        executable = Path(raw_executable).resolve(strict=True)
    except OSError as exc:
        raise SmokeError(
            f"prepared exact-wheel executable is unavailable: {exc}"
        ) from exc
    try:
        executable.relative_to(project.resolve(strict=True))
    except ValueError:
        pass
    else:
        raise SmokeError(
            "exact-wheel executable must remain outside the model workspace"
        )
    coordinator_home = control / "coordinator-home"
    coordinator_home.mkdir(mode=0o700, exist_ok=True)
    environment = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(coordinator_home),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "CKIT_EXPERIMENTAL": "1",
        "NO_COLOR": "1",
    }
    completed = subprocess.run(  # noqa: S603 - path is protected control-plane input
        [str(executable), "pipeline", *arguments],
        cwd=project,
        env=environment,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    stdout = _bounded(completed.stdout)
    stderr = _bounded(completed.stderr)
    if completed.returncode != 0:
        raise SmokeError(
            f"exact-wheel pipeline {' '.join(arguments)} failed ({completed.returncode})\n"
            f"stdout:\n{stdout}\nstderr:\n{stderr}"
        )
    return stdout


def _fixture_seed_conditions() -> dict[str, bool]:
    """Return the closed set of external Mode A decisions for this fixture."""

    return {
        "api-contract-surface-present": False,
        "api-surface-present": False,
        "application-attack-surface-present": False,
        "backend-surface-present": False,
        "end-to-end-path-present": False,
        "frontend-surface-present": False,
        "multiple-boundaries-present": False,
        "risk-or-uncertainty-present": False,
        "ui-surface-present": False,
    }


def _write_fixture_control_artifact(
    project: Path, *, category: str, document: Mapping[str, Any]
) -> dict[str, str]:
    """Write one immutable coordinator-owned, content-addressed fixture record."""

    from claude_kit.secure_fs import ProjectFS

    encoded = _json_bytes(dict(document))
    digest = hashlib.sha256(encoded).hexdigest()
    relative = f".ckit/artifacts/protected-host/{category}/{digest[:2]}/{digest}.json"
    fs = ProjectFS(project)
    if fs.exists(relative):
        if fs.read_bytes(relative) != encoded:
            raise SmokeError("content-addressed fixture artifact has conflicting bytes")
    else:
        fs.write_bytes(relative, encoded, mode=0o600)
    _document, actual = _private_managed_artifact(
        project, relative, label=f"{category} fixture artifact"
    )
    if actual != digest:
        raise SmokeError("fixture artifact digest changed after its atomic write")
    return {"path": relative, "sha256": digest}


def _pipeline_api_ok(result: tuple[bool, list[str]], *, action: str) -> None:
    ok, messages = result
    if not ok:
        raise SmokeError(f"{action} failed: {'; '.join(messages)}")


def _seed_managed_gate_owner(project: Path) -> None:
    """Seed only canonical prerequisites through the public managed APIs."""

    _assert_no_provider_secret_env()
    from claude_kit import pipeline
    from claude_kit.workflow_executor import (
        ManagedWorktreeResolver,
        WorkflowExecutionStatus,
        execute_bound_workflow,
    )

    project = project.expanduser().resolve(strict=True)
    before = _pipeline_document(project)
    run_id = before.get("run_id")
    if (
        before.get("status") != "active"
        or before.get("mode") != "A"
        or before.get("gate_history") != []
        or before.get("stage_history") != []
        or before.get("managed_execution") is not None
        or not isinstance(run_id, str)
        or not run_id
    ):
        raise SmokeError("gate-owner fixture is not a fresh Mode A pipeline")

    dispatcher = _FixtureSeedDispatcher()
    result = execute_bound_workflow(
        project,
        provider="codex",
        objective=MANAGED_GATE_OBJECTIVE,
        mode="A",
        conditions=_fixture_seed_conditions(),
        context=(
            "Coordinator fixture seed only. No native host process is part of this "
            "prerequisite claim."
        ),
        dispatcher=dispatcher,
        workspace_resolver=ManagedWorktreeResolver(project, run_id),
        wait_timeout_seconds=30,
    )
    if (
        result.status is not WorkflowExecutionStatus.WAITING_GATE
        or set(result.completed_stages) != set(MANAGED_GATE_SEED_STAGES)
        or result.pending_gates != (MANAGED_GATE_SEED_GATE,)
        or set(item.stage for item in result.attempts) != set(MANAGED_GATE_SEED_STAGES)
        or any(item.status.value != "succeeded" for item in result.attempts)
        or set(dispatcher.stages.values()) != set(MANAGED_GATE_SEED_STAGES)
    ):
        raise SmokeError("closed fixture dispatcher did not stop at spec-complete")

    seeded = _pipeline_document(project)
    history = seeded.get("stage_history")
    managed = seeded.get("managed_execution")
    if (
        not isinstance(history, list)
        or [item.get("stage") for item in history if isinstance(item, Mapping)]
        != list(MANAGED_GATE_SEED_STAGES)
        or not isinstance(managed, Mapping)
        or managed.get("gate_owner_stages", {}).get(MANAGED_GATE_SEED_GATE)
        != "planning-gate"
    ):
        raise SmokeError("fixture seed did not bind the canonical prerequisite graph")
    seed_records: list[dict[str, Any]] = []
    for item in history:
        if not isinstance(item, Mapping):
            raise SmokeError("fixture seed stage history is malformed")
        dispatch_id = item.get("dispatch_id")
        if (
            not isinstance(dispatch_id, str)
            or not dispatch_id.startswith("protected-fixture-seed-")
            or item.get("provider") != "codex"
            or item.get("status") != "succeeded"
        ):
            raise SmokeError("fixture seed provenance is not explicit in the ledger")
        evidence_records = item.get("evidence_records")
        if not isinstance(evidence_records, list) or not evidence_records:
            raise SmokeError("fixture seed has no typed prerequisite evidence")
        for record in evidence_records:
            if not isinstance(record, Mapping):
                raise SmokeError("fixture seed evidence provenance is malformed")
            relative = record.get("artifact_path")
            expected_sha = record.get("artifact_sha256")
            if not isinstance(relative, str) or not _is_sha256(expected_sha):
                raise SmokeError("fixture seed evidence identity is malformed")
            evidence_document, actual_sha = _private_managed_artifact(
                project, relative, label="fixture-seeded typed evidence"
            )
            provenance = evidence_document.get("fixture_provenance")
            if (
                actual_sha != expected_sha
                or not isinstance(provenance, Mapping)
                or provenance.get("kind") != "protected-fixture-seed"
                or provenance.get("native_host_claim") is not False
            ):
                raise SmokeError("fixture seed evidence does not exclude native claims")
        seed_records.append(
            {
                "stage": item.get("stage"),
                "role": item.get("role"),
                "dispatch_id": dispatch_id,
                "output_path": item.get("output_path"),
                "output_artifact_sha256": item.get("output_artifact_sha256"),
                "evidence_records": evidence_records,
            }
        )

    receipt = _write_fixture_control_artifact(
        project,
        category="fixture-seeds",
        document={
            "schema_version": 1,
            "kind": "protected-fixture-seed",
            "native_host_claim": False,
            "run_id": run_id,
            "workflow_digest": managed.get("workflow_digest"),
            "gate_definition_digest": seeded.get("gate_definition_digest"),
            "seeded_stages": seed_records,
            "next_native_stage": MANAGED_PLANNING_REVIEW_STAGE,
        },
    )
    _pipeline_api_ok(
        pipeline.record_findings(
            project,
            critical=0,
            high=0,
            medium=0,
            low=0,
            cosmetic=0,
            evidence=receipt["path"],
        ),
        action="record fixture prerequisite findings",
    )
    _pipeline_api_ok(
        pipeline.close_gate(
            project,
            MANAGED_GATE_SEED_GATE,
            receipt["path"],
            strict=True,
        ),
        action="close fixture prerequisite gate",
    )
    _pipeline_api_ok(pipeline.validate(project, strict=True), action="validate seed")
    closed = _pipeline_document(project)
    gate_history = closed.get("gate_history")
    if (
        closed.get("stage") != MANAGED_GATE_OWNER_GATE
        or not isinstance(gate_history, list)
        or [item.get("gate") for item in gate_history if isinstance(item, Mapping)]
        != [MANAGED_GATE_SEED_GATE]
        or any(
            isinstance(item, Mapping) and item.get("stage") == MANAGED_GATE_OWNER_STAGE
            for item in closed.get("stage_history", [])
        )
    ):
        raise SmokeError("fixture seed did not stop before the native gate owner")
    print(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "protected-fixture-seed",
                "native_host_claim": False,
                "run_id": run_id,
                "seeded_stages": list(MANAGED_GATE_SEED_STAGES),
                "seed_dispatch_ids": [item["dispatch_id"] for item in seed_records],
                "receipt": receipt,
                "gate_history_digest": _gate_history_digest(gate_history),
            },
            sort_keys=True,
        )
    )


def _close_managed_gate_owner(project: Path) -> None:
    """Close em-approved through public APIs after its real native owner succeeds."""

    _assert_no_provider_secret_env()
    from claude_kit import pipeline

    project = project.expanduser().resolve(strict=True)
    before = _pipeline_document(project)
    history = before.get("stage_history")
    gate_history = before.get("gate_history")
    native_attempts = (
        [
            item
            for item in history
            if isinstance(item, Mapping)
            and item.get("stage") == MANAGED_GATE_OWNER_STAGE
        ]
        if isinstance(history, list)
        else []
    )
    if (
        before.get("status") != "active"
        or before.get("stage") != MANAGED_GATE_OWNER_GATE
        or not isinstance(gate_history, list)
        or [item.get("gate") for item in gate_history if isinstance(item, Mapping)]
        != [MANAGED_GATE_SEED_GATE]
        or len(native_attempts) != 1
        or native_attempts[0].get("status") != "succeeded"
        or native_attempts[0].get("provider") != "codex"
        or native_attempts[0].get("role") != MANAGED_GATE_OWNER_ROLE
    ):
        raise SmokeError("em-approved is not ready for authoritative closure")
    attempt = native_attempts[0]
    receipt = _write_fixture_control_artifact(
        project,
        category="native-gate-closures",
        document={
            "schema_version": 1,
            "kind": "protected-native-gate-close",
            "native_host_claim": True,
            "run_id": before.get("run_id"),
            "gate": MANAGED_GATE_OWNER_GATE,
            "owner_stage": MANAGED_GATE_OWNER_STAGE,
            "owner_dispatch_id": attempt.get("dispatch_id"),
            "owner_dispatch_attempt": attempt.get("dispatch_attempt"),
            "owner_output_sha256": attempt.get("output_sha256"),
            "evidence_records": attempt.get("evidence_records"),
        },
    )
    _pipeline_api_ok(
        pipeline.record_findings(
            project,
            critical=0,
            high=0,
            medium=0,
            low=0,
            cosmetic=0,
            evidence=receipt["path"],
        ),
        action="record native gate-owner findings",
    )
    _pipeline_api_ok(
        pipeline.close_gate(
            project,
            MANAGED_GATE_OWNER_GATE,
            receipt["path"],
            strict=True,
        ),
        action="close native em-approved gate",
    )
    _pipeline_api_ok(
        pipeline.validate(project, strict=True), action="validate native gate closure"
    )
    closed = _pipeline_document(project)
    final_history = closed.get("gate_history")
    if (
        not isinstance(final_history, list)
        or [item.get("gate") for item in final_history if isinstance(item, Mapping)]
        != [MANAGED_GATE_SEED_GATE, MANAGED_GATE_OWNER_GATE]
        or final_history[-1].get("owner_stage") != MANAGED_GATE_OWNER_STAGE
        or final_history[-1].get("owner_dispatch_id") != attempt.get("dispatch_id")
        or final_history[-1].get("owner_dispatch_attempt")
        != attempt.get("dispatch_attempt")
    ):
        raise SmokeError("em-approved closure is not bound to its exact native owner")
    print(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "protected-native-gate-close",
                "native_host_claim": True,
                "run_id": closed.get("run_id"),
                "receipt": receipt,
                "gate_history_digest": _gate_history_digest(final_history),
            },
            sort_keys=True,
        )
    )


def _exact_wheel_python(document: Mapping[str, Any], project: Path) -> Path:
    raw = document.get("ckit_executable")
    if not isinstance(raw, str):
        raise SmokeError("exact-wheel executable contract is invalid")
    executable = Path(raw).resolve(strict=True)
    for name in ("python", "python3"):
        candidate = executable.parent / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            try:
                candidate.relative_to(project.resolve(strict=True))
            except ValueError:
                # Preserve the venv launcher path. Resolving its interpreter symlink
                # would bypass the exact wheel's site-packages.
                return candidate
    raise SmokeError("exact-wheel Python interpreter is unavailable beside ckit")


def _run_exact_wheel_harness(
    document: Mapping[str, Any],
    project: Path,
    control: Path,
    command: str,
) -> dict[str, Any]:
    """Re-enter the harness with only the installed exact-wheel import path."""

    python = _exact_wheel_python(document, project)
    home = control / f"{command}-home"
    home.mkdir(mode=0o700, exist_ok=False)
    environment = {
        "PATH": f"{python.parent}{os.pathsep}/usr/bin:/bin",
        "HOME": str(home),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "CKIT_EXPERIMENTAL": "1",
        "NO_COLOR": "1",
        "PYTHONNOUSERSITE": "1",
    }
    completed = _run_bounded_process(
        [
            str(python),
            str(Path(__file__).resolve(strict=True)),
            command,
            "--project",
            str(project),
        ],
        cwd=project,
        env=environment,
        timeout=180,
        label=f"exact-wheel {command}",
    )
    stdout = _decode_host_output(completed.stdout, label=f"{command} stdout")
    stderr = _decode_host_output(completed.stderr, label=f"{command} stderr")
    if completed.returncode != 0:
        raise SmokeError(
            f"exact-wheel {command} failed ({completed.returncode}); "
            f"{_output_summary('stdout', stdout)}; {_output_summary('stderr', stderr)}; "
            f"stderr:\n{stderr}"
        )
    try:
        result = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise SmokeError(f"exact-wheel {command} returned invalid JSON") from exc
    if not isinstance(result, dict):
        raise SmokeError(f"exact-wheel {command} result must be an object")
    return result


def _prepare_managed_gate_owner_project(
    root: Path, document: Mapping[str, Any], control: Path
) -> tuple[Path, dict[str, Any]]:
    """Create and publicly seed the separate full-SDLC gate-owner fixture."""

    resolved = root.resolve(strict=True)
    project = resolved / MANAGED_GATE_OWNER_PROJECT_DIR
    if project.exists() or project.is_symlink():
        raise SmokeError("managed gate-owner project already exists")
    executable = document.get("ckit_executable")
    if not isinstance(executable, str) or not Path(executable).is_file():
        raise SmokeError("managed gate-owner proof has no exact-wheel executable")
    home = control / "managed-gate-owner-scaffold-home"
    home.mkdir(mode=0o700, exist_ok=False)
    config = control / "managed-gate-owner-config.yaml"
    _write_text(config, "profile: standard\ncapture_mode: off\n")
    environment = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(home),
        "CKIT_EXPERIMENTAL": "1",
        "NO_COLOR": "1",
    }
    scaffolded = subprocess.run(  # noqa: S603 - exact-wheel path is frozen control input
        [
            executable,
            "init",
            str(project),
            "--config",
            str(config),
            "--runtime",
            "both",
            "--no-detect-commands",
        ],
        cwd=resolved,
        env=environment,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    if scaffolded.returncode != 0:
        raise SmokeError(
            "managed gate-owner exact-wheel scaffold failed\n"
            f"stdout:\n{_bounded(scaffolded.stdout)}\n"
            f"stderr:\n{_bounded(scaffolded.stderr)}"
        )
    _scaffold_inventory(project)
    _write_text(
        project / "specs/protected_gate_owner_spec.md",
        "# Protected gate-owner fixture\n\n"
        "Review one committed, documentation-only plan through the canonical "
        "planning review panel and planning-merge gate owner. No source mutation, "
        "shell, MCP, hooks, network, or nested delegation is in scope.\n",
    )
    git = shutil.which("git", path=environment["PATH"])
    if git is None:
        raise SmokeError("git is required for the managed gate-owner proof")
    for arguments in (
        ("init", "--quiet"),
        ("symbolic-ref", "HEAD", "refs/heads/main"),
        ("config", "user.email", "protected-gate-owner@example.invalid"),
        ("config", "user.name", "Protected Gate Owner"),
        ("add", "-A"),
        ("commit", "--quiet", "-m", "protected managed gate-owner fixture"),
    ):
        completed = subprocess.run(  # noqa: S603 - git path is resolved above
            [git, *arguments],
            cwd=project,
            env=environment,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        if completed.returncode != 0:
            raise SmokeError(
                f"managed gate-owner git {' '.join(arguments)} failed "
                f"({completed.returncode})"
            )
    started = subprocess.run(  # noqa: S603 - exact-wheel path is frozen control input
        [
            executable,
            "pipeline",
            "start",
            str(project),
            "--task",
            MANAGED_GATE_OBJECTIVE,
            "--mode",
            "A",
        ],
        cwd=project,
        env=environment,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    if started.returncode != 0:
        raise SmokeError(
            "managed gate-owner exact-wheel pipeline start failed\n"
            f"stdout:\n{_bounded(started.stdout)}\n"
            f"stderr:\n{_bounded(started.stderr)}"
        )
    seed_proof = _run_exact_wheel_harness(
        document, project, control, "seed-managed-gate-owner"
    )
    if (
        seed_proof.get("kind") != "protected-fixture-seed"
        or seed_proof.get("native_host_claim") is not False
        or seed_proof.get("seeded_stages") != list(MANAGED_GATE_SEED_STAGES)
    ):
        raise SmokeError("managed gate-owner seed proof is invalid")
    return project, seed_proof


def _prepare_managed_codex_project(
    root: Path, document: Mapping[str, Any], control: Path
) -> Path:
    """Create a separate exact-wheel project for the managed passive-role proof."""

    resolved = root.resolve(strict=True)
    project = resolved / MANAGED_PROJECT_DIR
    if project.exists() or project.is_symlink():
        raise SmokeError("managed Codex project already exists; refusing to replace it")
    executable = document.get("ckit_executable")
    if not isinstance(executable, str) or not Path(executable).is_file():
        raise SmokeError("managed Codex proof has no exact-wheel executable")
    home = control / "managed-scaffold-home"
    home.mkdir(mode=0o700, exist_ok=False)
    environment = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(home),
        "CKIT_EXPERIMENTAL": "1",
        "NO_COLOR": "1",
    }
    scaffolded = subprocess.run(  # noqa: S603 - exact-wheel path is frozen control input
        [executable, "init", str(project), "--defaults", "--runtime", "both"],
        cwd=resolved,
        env=environment,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    if scaffolded.returncode != 0:
        raise SmokeError(
            "managed Codex exact-wheel scaffold failed\n"
            f"stdout:\n{_bounded(scaffolded.stdout)}\n"
            f"stderr:\n{_bounded(scaffolded.stderr)}"
        )
    _scaffold_inventory(project)
    git = shutil.which("git", path=environment["PATH"])
    if git is None:
        raise SmokeError("git is required for the managed Codex proof")
    for arguments in (
        ("init", "--quiet"),
        ("symbolic-ref", "HEAD", "refs/heads/main"),
        ("config", "user.email", "protected-managed@example.invalid"),
        ("config", "user.name", "Protected Managed Codex"),
        ("add", "-A"),
        ("commit", "--quiet", "-m", "protected managed Codex fixture"),
    ):
        completed = subprocess.run(  # noqa: S603 - git path is resolved above
            [git, *arguments],
            cwd=project,
            env=environment,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        if completed.returncode != 0:
            raise SmokeError(
                f"managed Codex git {' '.join(arguments)} failed "
                f"({completed.returncode})"
            )
    started = subprocess.run(  # noqa: S603 - exact-wheel path is frozen control input
        [
            executable,
            "pipeline",
            "start",
            str(project),
            "--task",
            "protected native managed passive-role probe",
            "--mode",
            "D",
        ],
        cwd=project,
        env=environment,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    if started.returncode != 0:
        raise SmokeError(
            "managed Codex exact-wheel pipeline start failed\n"
            f"stdout:\n{_bounded(started.stdout)}\n"
            f"stderr:\n{_bounded(started.stderr)}"
        )
    pipeline = _pipeline_document(project)
    if (
        pipeline.get("status") != "active"
        or pipeline.get("mode") != "D"
        or pipeline.get("stage") != "code-review"
        or pipeline.get("gate_history") != []
    ):
        raise SmokeError("managed Codex Mode D pipeline did not start cleanly")
    return project


def _private_managed_artifact(
    project: Path, relative: str, *, label: str
) -> tuple[dict[str, Any], str]:
    candidate = Path(relative)
    if not relative or candidate.is_absolute() or ".." in candidate.parts:
        raise SmokeError(f"{label} path is not project-contained")
    root = project.resolve(strict=True)
    current = root
    for part in candidate.parts:
        current = current / part
        try:
            info = current.lstat()
        except OSError as exc:
            raise SmokeError(f"{label} is unavailable: {exc}") from exc
        if stat.S_ISLNK(info.st_mode):
            raise SmokeError(f"{label} path contains a symlink")
    try:
        resolved = current.resolve(strict=True)
        resolved.relative_to(root)
        info = resolved.lstat()
    except (OSError, ValueError) as exc:
        raise SmokeError(f"{label} is outside the managed project: {exc}") from exc
    if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
        raise SmokeError(f"{label} must be a root-owned 0600 regular file")
    if info.st_size > MAX_HOST_OUTPUT_BYTES:
        raise SmokeError(f"{label} exceeds the protected 1 MiB bound")
    try:
        raw = resolved.read_bytes()
        document = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SmokeError(f"{label} is not valid bounded JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise SmokeError(f"{label} must contain a JSON object")
    return document, hashlib.sha256(raw).hexdigest()


def _assert_managed_codex_state(
    project: Path,
    *,
    result_document: Mapping[str, Any] | None = None,
    host_version: str,
) -> dict[str, Any]:
    """Verify the real managed ledger, typed evidence, and fail-closed boundary."""

    pipeline = _pipeline_document(project)
    managed = pipeline.get("managed_execution")
    history = pipeline.get("stage_history")
    human_stops = pipeline.get("human_stops")
    if (
        pipeline.get("status") != "active"
        or pipeline.get("mode") != "D"
        or pipeline.get("stage") != "code-review"
        or pipeline.get("ordered_gates") != list(MANAGED_GATE_OWNERS)
        or pipeline.get("gate_history") != []
        or not isinstance(managed, dict)
        or not isinstance(history, list)
        or len(history) != 1
        or not isinstance(history[0], dict)
        or not isinstance(human_stops, list)
        or len(human_stops) != 1
        or not isinstance(human_stops[0], dict)
    ):
        raise SmokeError(
            "managed Codex run did not preserve its exact active gate state"
        )
    if managed.get("gate_owner_stages") != MANAGED_GATE_OWNERS:
        raise SmokeError(
            "managed Codex gate owners differ from the canonical Mode D map"
        )
    route = managed.get("active_stage_routes", {}).get(MANAGED_PASSIVE_STAGE)
    requirements = managed.get("active_stage_requirements", {}).get(
        MANAGED_PASSIVE_STAGE
    )
    stage_evidence = managed.get("active_stage_evidence", {}).get(MANAGED_PASSIVE_STAGE)
    if (
        not isinstance(route, dict)
        or route.get("execution_kind") != "native-role"
        or route.get("route") != "classification"
        or route.get("role") != MANAGED_PASSIVE_ROLE
        or route.get("permission") != "read_only"
        or route.get("write_scope") != []
        or route.get("nested_delegation") != "forbidden"
        or requirements != list(MANAGED_PASSIVE_CAPABILITIES)
        or route.get("required_capabilities") != list(MANAGED_PASSIVE_CAPABILITIES)
        or stage_evidence != [MANAGED_PASSIVE_EVIDENCE]
    ):
        raise SmokeError(
            "managed Codex passive route is broader than its frozen contract"
        )
    forbidden_capabilities = {
        "browser",
        "delegation",
        "external.mutation",
        "filesystem.write",
        "mcp",
        "process.descendant_containment",
        "shell",
        "workflow.ledger",
    }
    if forbidden_capabilities.intersection(requirements):
        raise SmokeError("managed Codex passive route exposes a forbidden capability")

    attempt = history[0]
    evidence_records = attempt.get("evidence_records")
    if (
        attempt.get("stage") != MANAGED_PASSIVE_STAGE
        or attempt.get("route") != "classification"
        or attempt.get("role") != MANAGED_PASSIVE_ROLE
        or attempt.get("provider") != "codex"
        or attempt.get("status") != "succeeded"
        or attempt.get("attempt") != 1
        or attempt.get("dispatch_attempt") != 1
        or attempt.get("required_capabilities") != list(MANAGED_PASSIVE_CAPABILITIES)
        or attempt.get("attested_capabilities") != list(MANAGED_PASSIVE_CAPABILITIES)
        or attempt.get("evidence") != [f"artifact://{MANAGED_PASSIVE_EVIDENCE}"]
        or attempt.get("findings") != []
        or not isinstance(evidence_records, list)
        or len(evidence_records) != 1
        or not isinstance(evidence_records[0], dict)
    ):
        raise SmokeError("managed Codex passive attempt is not exactly ledger-bound")
    if any(
        isinstance(item, Mapping)
        and item.get("stage") in set(MANAGED_GATE_OWNERS.values())
        for item in history
    ):
        raise SmokeError(
            "managed Codex run launched a gate owner beyond the passive lane"
        )

    run_id = pipeline.get("run_id")
    dispatch_id = attempt.get("dispatch_id")
    evidence_record = evidence_records[0]
    evidence_relative = evidence_record.get("artifact_path")
    evidence_sha = evidence_record.get("artifact_sha256")
    if (
        not isinstance(run_id, str)
        or not run_id
        or not isinstance(dispatch_id, str)
        or not dispatch_id
        or evidence_record.get("kind") != "managed-workflow-evidence"
        or evidence_record.get("run_id") != run_id
        or evidence_record.get("stage") != MANAGED_PASSIVE_STAGE
        or evidence_record.get("dispatch_id") != dispatch_id
        or evidence_record.get("dispatch_attempt") != 1
        or evidence_record.get("evidence_id") != MANAGED_PASSIVE_EVIDENCE
        or evidence_record.get("validation_profile") != MANAGED_PASSIVE_EVIDENCE
        or not isinstance(evidence_relative, str)
        or not _is_sha256(evidence_sha)
        or evidence_relative
        != (
            f".ckit/artifacts/evidence/runs/{run_id}/{MANAGED_PASSIVE_STAGE}/1/"
            f"{MANAGED_PASSIVE_EVIDENCE}-{evidence_sha}.json"
        )
    ):
        raise SmokeError("managed Codex typed evidence provenance is invalid")
    evidence_document, actual_evidence_sha = _private_managed_artifact(
        project, evidence_relative, label="managed typed stage evidence"
    )
    if actual_evidence_sha != evidence_sha:
        raise SmokeError("managed Codex typed evidence hash does not match its ledger")
    if (
        evidence_document.get("mode") != "D"
        or not isinstance(evidence_document.get("surfaces"), list)
        or not evidence_document["surfaces"]
        or not all(
            isinstance(value, str) and value.strip()
            for value in evidence_document["surfaces"]
        )
        or not isinstance(evidence_document.get("constraints"), list)
        or not isinstance(evidence_document.get("risks"), list)
        or evidence_document.get("risk-tier") != "low"
        or evidence_document.get("localized-single-boundary") is not True
        or evidence_document.get("unambiguous") is not True
        or evidence_document.get("reversible") is not True
        or evidence_document.get("sensitive-surface") is not False
        or evidence_document.get("public-contract-surface") is not False
        or evidence_document.get("irreversible-action") is not False
        or evidence_document.get("external-effect") is not False
    ):
        raise SmokeError("managed Codex scope evidence is not content-bearing")

    terminal_relative = attempt.get("output_path")
    terminal_sha = attempt.get("output_artifact_sha256")
    if (
        not isinstance(terminal_relative, str)
        or not _is_sha256(terminal_sha)
        or terminal_relative
        != (
            f".ckit/artifacts/dispatch/runs/{run_id}/{MANAGED_PASSIVE_STAGE}/1/"
            f"terminal-{terminal_sha}.json"
        )
    ):
        raise SmokeError("managed Codex terminal artifact identity is invalid")
    terminal_document, actual_terminal_sha = _private_managed_artifact(
        project, terminal_relative, label="managed terminal result"
    )
    if actual_terminal_sha != terminal_sha:
        raise SmokeError(
            "managed Codex terminal artifact hash does not match its ledger"
        )
    if (
        terminal_document.get("run_id") != run_id
        or terminal_document.get("stage") != MANAGED_PASSIVE_STAGE
        or terminal_document.get("provider") != "codex"
        or terminal_document.get("route") != MANAGED_PASSIVE_ROLE
        or terminal_document.get("dispatch_id") != dispatch_id
        or terminal_document.get("dispatch_attempt") != 1
        or terminal_document.get("status") != "succeeded"
        or terminal_document.get("evidence")
        != [f"artifact://{MANAGED_PASSIVE_EVIDENCE}"]
        or terminal_document.get("evidence_records") != evidence_records
    ):
        raise SmokeError("managed Codex terminal artifact has inconsistent provenance")

    stop = human_stops[0]
    if (
        stop.get("status") != "pending"
        or stop.get("reason") != "unsupported-required-capability"
        or "process.descendant_containment" not in str(stop.get("message", ""))
    ):
        raise SmokeError("managed Codex writable boundary did not fail closed")
    if result_document is not None:
        attempts = result_document.get("attempts")
        public_stop = result_document.get("human_stop")
        if (
            result_document.get("status") != "human-stop"
            or result_document.get("completed_stages") != [MANAGED_PASSIVE_STAGE]
            or result_document.get("pending_gates") != []
            or not isinstance(attempts, list)
            or len(attempts) != 1
            or not isinstance(attempts[0], dict)
            or attempts[0].get("stage") != MANAGED_PASSIVE_STAGE
            or attempts[0].get("role") != MANAGED_PASSIVE_ROLE
            or attempts[0].get("provider") != "codex"
            or attempts[0].get("status") != "succeeded"
            or not isinstance(public_stop, dict)
            or public_stop.get("reason") != "unsupported-required-capability"
        ):
            raise SmokeError(
                "managed Codex CLI result does not match its durable ledger"
            )

    return {
        "schema_version": 1,
        "provider": "codex",
        "host_version": host_version,
        "run_id": run_id,
        "stage": MANAGED_PASSIVE_STAGE,
        "role": MANAGED_PASSIVE_ROLE,
        "required_capabilities": list(MANAGED_PASSIVE_CAPABILITIES),
        "gate_owners": dict(MANAGED_GATE_OWNERS),
        "stop_reason": "unsupported-required-capability",
        "evidence": {"path": evidence_relative, "sha256": evidence_sha},
        "terminal_artifact": {
            "path": terminal_relative,
            "sha256": terminal_sha,
        },
        "snapshot_sha256": hashlib.sha256(
            (project / PIPELINE_SNAPSHOT).read_bytes()
        ).hexdigest(),
    }


def _assert_managed_codex_gate_owner_state(
    project: Path,
    *,
    seed_proof: Mapping[str, Any],
    host_version: str,
    result_document: Mapping[str, Any] | None = None,
    gate_closed: bool,
) -> dict[str, Any]:
    """Verify the native planning panel, EM decision, and gate bundle."""

    pipeline = _pipeline_document(project)
    managed = pipeline.get("managed_execution")
    history = pipeline.get("stage_history")
    gate_history = pipeline.get("gate_history")
    expected_stages = [
        *MANAGED_GATE_SEED_STAGES,
        MANAGED_PLANNING_REVIEW_STAGE,
        MANAGED_GATE_OWNER_STAGE,
    ]
    expected_gates = [MANAGED_GATE_SEED_GATE]
    expected_stage = MANAGED_GATE_OWNER_GATE
    if gate_closed:
        expected_gates.append(MANAGED_GATE_OWNER_GATE)
        expected_stage = "code-review"
    if (
        pipeline.get("status") != "active"
        or pipeline.get("mode") != "A"
        or pipeline.get("stage") != expected_stage
        or not isinstance(managed, Mapping)
        or not isinstance(history, list)
        or [item.get("stage") for item in history if isinstance(item, Mapping)]
        != expected_stages
        or not isinstance(gate_history, list)
        or [item.get("gate") for item in gate_history if isinstance(item, Mapping)]
        != expected_gates
        or pipeline.get("human_stops") != []
    ):
        raise SmokeError("managed gate-owner proof has an unexpected ledger shape")
    run_id = pipeline.get("run_id")
    if run_id != seed_proof.get("run_id") or not isinstance(run_id, str):
        raise SmokeError("native gate owner does not share the seeded run identity")
    seed_dispatch_ids = seed_proof.get("seed_dispatch_ids")
    if (
        seed_proof.get("kind") != "protected-fixture-seed"
        or seed_proof.get("native_host_claim") is not False
        or seed_proof.get("seeded_stages") != list(MANAGED_GATE_SEED_STAGES)
        or not isinstance(seed_dispatch_ids, list)
        or len(seed_dispatch_ids) != len(MANAGED_GATE_SEED_STAGES)
    ):
        raise SmokeError("fixture predecessor boundary is not explicit")
    seed_receipt = seed_proof.get("receipt")
    if not isinstance(seed_receipt, Mapping):
        raise SmokeError("fixture predecessor receipt is missing")
    seed_receipt_path = seed_receipt.get("path")
    seed_receipt_sha = seed_receipt.get("sha256")
    if not isinstance(seed_receipt_path, str) or not _is_sha256(seed_receipt_sha):
        raise SmokeError("fixture predecessor receipt identity is malformed")
    seed_document, actual_seed_sha = _private_managed_artifact(
        project, seed_receipt_path, label="fixture predecessor receipt"
    )
    if (
        actual_seed_sha != seed_receipt_sha
        or seed_document.get("kind") != "protected-fixture-seed"
        or seed_document.get("native_host_claim") is not False
        or seed_document.get("run_id") != run_id
    ):
        raise SmokeError("fixture predecessor receipt is not live and content-bound")
    for stage, dispatch_id, item in zip(
        MANAGED_GATE_SEED_STAGES, seed_dispatch_ids, history[:3]
    ):
        if (
            not isinstance(item, Mapping)
            or item.get("stage") != stage
            or item.get("dispatch_id") != dispatch_id
            or item.get("provider") != "codex"
            or not str(dispatch_id).startswith("protected-fixture-seed-")
        ):
            raise SmokeError("seeded predecessor was confused with native host work")
        evidence_records = item.get("evidence_records")
        if not isinstance(evidence_records, list) or not evidence_records:
            raise SmokeError("seeded predecessor typed evidence is missing")
        for record in evidence_records:
            if not isinstance(record, Mapping):
                raise SmokeError("seeded predecessor evidence record is malformed")
            relative = record.get("artifact_path")
            digest = record.get("artifact_sha256")
            if not isinstance(relative, str) or not _is_sha256(digest):
                raise SmokeError("seeded predecessor evidence identity is malformed")
            evidence_document, actual_digest = _private_managed_artifact(
                project, relative, label="seeded predecessor typed evidence"
            )
            provenance = evidence_document.get("fixture_provenance")
            if (
                actual_digest != digest
                or not isinstance(provenance, Mapping)
                or provenance.get("kind") != "protected-fixture-seed"
                or provenance.get("native_host_claim") is not False
            ):
                raise SmokeError(
                    "seeded predecessor evidence overstates native provenance"
                )

    planning_gate_attempt = history[len(MANAGED_GATE_SEED_STAGES) - 1]
    planning_gate_records = planning_gate_attempt.get("evidence_records")
    if not isinstance(planning_gate_records, list):
        raise SmokeError("fixture planning packet has no typed evidence records")
    planning_packet_evidence: dict[str, str] = {}
    for record in planning_gate_records:
        if not isinstance(record, Mapping):
            raise SmokeError("fixture planning packet evidence is malformed")
        evidence_id = record.get("evidence_id")
        digest = record.get("artifact_sha256")
        if (
            not isinstance(evidence_id, str)
            or evidence_id in planning_packet_evidence
            or not _is_sha256(digest)
        ):
            raise SmokeError("fixture planning packet identity is malformed")
        planning_packet_evidence[evidence_id] = digest
    if not {"specification", "architecture-plan"}.issubset(planning_packet_evidence):
        raise SmokeError("fixture planning packet is incomplete")
    expected_planning_generation = hashlib.sha256(
        json.dumps(
            {
                "stage": "planning-gate",
                "evidence": [
                    {
                        "evidence-id": evidence_id,
                        "sha256": planning_packet_evidence[evidence_id],
                    }
                    for evidence_id in sorted(planning_packet_evidence)
                ],
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()

    panel_route = managed.get("active_stage_routes", {}).get(
        MANAGED_PLANNING_REVIEW_STAGE
    )
    panel_requirements = managed.get("active_stage_requirements", {}).get(
        MANAGED_PLANNING_REVIEW_STAGE
    )
    panel_declared_evidence = managed.get("active_stage_evidence", {}).get(
        MANAGED_PLANNING_REVIEW_STAGE
    )
    if (
        not isinstance(panel_route, Mapping)
        or panel_route.get("execution_kind") != "native-role"
        or panel_route.get("route") != MANAGED_PLANNING_REVIEW_ROUTE
        or panel_route.get("role") != MANAGED_PLANNING_REVIEW_ROLE
        or panel_route.get("permission") != "read_only"
        or panel_route.get("write_scope") != []
        or panel_route.get("nested_delegation") != "forbidden"
        or panel_route.get("required_capabilities")
        != list(MANAGED_PLANNING_REVIEW_CAPABILITIES)
        or panel_requirements != list(MANAGED_PLANNING_REVIEW_CAPABILITIES)
        or panel_declared_evidence != ["planning-review-verdict"]
    ):
        raise SmokeError("native planning-review route is broader than its contract")

    route = managed.get("active_stage_routes", {}).get(MANAGED_GATE_OWNER_STAGE)
    requirements = managed.get("active_stage_requirements", {}).get(
        MANAGED_GATE_OWNER_STAGE
    )
    declared_evidence = managed.get("active_stage_evidence", {}).get(
        MANAGED_GATE_OWNER_STAGE
    )
    if (
        managed.get("gate_owner_stages", {}).get(MANAGED_GATE_OWNER_GATE)
        != MANAGED_GATE_OWNER_STAGE
        or not isinstance(route, Mapping)
        or route.get("execution_kind") != "native-role"
        or route.get("route") != "management-review"
        or route.get("role") != MANAGED_GATE_OWNER_ROLE
        or route.get("permission") != "read_only"
        or route.get("write_scope") != []
        or route.get("nested_delegation") != "forbidden"
        or route.get("required_capabilities") != list(MANAGED_GATE_OWNER_CAPABILITIES)
        or requirements != list(MANAGED_GATE_OWNER_CAPABILITIES)
        or declared_evidence != ["architecture-plan", "planning-decision"]
    ):
        raise SmokeError("native gate-owner route is broader than its frozen contract")
    forbidden = {
        "browser",
        "external.mutation",
        "filesystem.write",
        "mcp",
        "process.descendant_containment",
        "shell",
        "workflow.ledger",
    }
    if forbidden.intersection(requirements) or forbidden.intersection(
        panel_requirements
    ):
        raise SmokeError("native gate-owner route exposes a forbidden capability")

    panel_attempt = history[-2]
    panel_records = panel_attempt.get("evidence_records")
    panel_dispatch_id = panel_attempt.get("dispatch_id")
    if (
        panel_attempt.get("stage") != MANAGED_PLANNING_REVIEW_STAGE
        or panel_attempt.get("route") != MANAGED_PLANNING_REVIEW_ROUTE
        or panel_attempt.get("role") != MANAGED_PLANNING_REVIEW_ROLE
        or panel_attempt.get("provider") != "codex"
        or panel_attempt.get("status") != "succeeded"
        or panel_attempt.get("attempt") != 1
        or panel_attempt.get("dispatch_attempt") != 1
        or panel_attempt.get("required_capabilities")
        != list(MANAGED_PLANNING_REVIEW_CAPABILITIES)
        or panel_attempt.get("attested_capabilities")
        != list(MANAGED_PLANNING_REVIEW_CAPABILITIES)
        or panel_attempt.get("workspace_checkpoint_before")
        != panel_attempt.get("workspace_checkpoint")
        or panel_attempt.get("evidence") != ["artifact://planning-review-verdict"]
        or panel_attempt.get("findings") != []
        or panel_attempt.get("finding_counts")
        != {"critical": 0, "high": 0, "medium": 0, "low": 0, "cosmetic": 0}
        or not isinstance(panel_dispatch_id, str)
        or panel_dispatch_id in seed_dispatch_ids
        or not isinstance(panel_records, list)
        or len(panel_records) != 1
    ):
        raise SmokeError("native planning reviewer is not exactly ledger-bound")
    panel_record = panel_records[0]
    if not isinstance(panel_record, Mapping):
        raise SmokeError("native planning-review evidence record is malformed")
    panel_relative = panel_record.get("artifact_path")
    panel_digest = panel_record.get("artifact_sha256")
    if (
        panel_record.get("kind") != "managed-workflow-evidence"
        or panel_record.get("run_id") != run_id
        or panel_record.get("stage") != MANAGED_PLANNING_REVIEW_STAGE
        or panel_record.get("dispatch_id") != panel_dispatch_id
        or panel_record.get("dispatch_attempt") != 1
        or panel_record.get("evidence_id") != "planning-review-verdict"
        or panel_record.get("validation_profile") != "planning-review-verdict"
        or not isinstance(panel_relative, str)
        or not _is_sha256(panel_digest)
        or panel_relative
        != (
            f".ckit/artifacts/evidence/runs/{run_id}/"
            f"{MANAGED_PLANNING_REVIEW_STAGE}/1/"
            f"planning-review-verdict-{panel_digest}.json"
        )
    ):
        raise SmokeError("native planning-review evidence provenance is invalid")
    panel_document, actual_panel_digest = _private_managed_artifact(
        project, panel_relative, label="native planning-review evidence"
    )
    planning_generation = panel_document.get("planning-generation")
    if (
        actual_panel_digest != panel_digest
        or "fixture_provenance" in panel_document
        or panel_document.get("status") != "PASS"
        or panel_document.get("reviewer") != MANAGED_PLANNING_REVIEW_ROLE
        or planning_generation != expected_planning_generation
        or panel_document.get("authority-domain") != MANAGED_PLANNING_REVIEW_AUTHORITY
        or panel_document.get("findings") != []
        or panel_document.get("evidence") != ["specs/protected_gate_owner_spec.md"]
    ):
        raise SmokeError("native planning-review verdict has an invalid identity")
    panel_terminal_path = panel_attempt.get("output_path")
    panel_terminal_sha = panel_attempt.get("output_artifact_sha256")
    if (
        not isinstance(panel_terminal_path, str)
        or not _is_sha256(panel_terminal_sha)
        or panel_terminal_path
        != (
            f".ckit/artifacts/dispatch/runs/{run_id}/"
            f"{MANAGED_PLANNING_REVIEW_STAGE}/1/"
            f"terminal-{panel_terminal_sha}.json"
        )
    ):
        raise SmokeError("native planning-review terminal identity is invalid")
    panel_terminal, actual_panel_terminal_sha = _private_managed_artifact(
        project, panel_terminal_path, label="native planning-review terminal result"
    )
    if (
        actual_panel_terminal_sha != panel_terminal_sha
        or panel_terminal.get("run_id") != run_id
        or panel_terminal.get("stage") != MANAGED_PLANNING_REVIEW_STAGE
        or panel_terminal.get("provider") != "codex"
        or panel_terminal.get("route") != MANAGED_PLANNING_REVIEW_ROLE
        or panel_terminal.get("dispatch_id") != panel_dispatch_id
        or panel_terminal.get("dispatch_attempt") != 1
        or panel_terminal.get("status") != "succeeded"
        or panel_terminal.get("evidence") != ["artifact://planning-review-verdict"]
        or panel_terminal.get("evidence_records") != panel_records
    ):
        raise SmokeError("native planning-review terminal provenance is invalid")

    attempt = history[-1]
    evidence_records = attempt.get("evidence_records")
    dispatch_id = attempt.get("dispatch_id")
    if (
        attempt.get("stage") != MANAGED_GATE_OWNER_STAGE
        or attempt.get("route") != "management-review"
        or attempt.get("role") != MANAGED_GATE_OWNER_ROLE
        or attempt.get("provider") != "codex"
        or attempt.get("status") != "succeeded"
        or attempt.get("attempt") != 1
        or attempt.get("dispatch_attempt") != 1
        or attempt.get("required_capabilities") != list(MANAGED_GATE_OWNER_CAPABILITIES)
        or attempt.get("attested_capabilities") != list(MANAGED_GATE_OWNER_CAPABILITIES)
        or attempt.get("workspace_checkpoint_before")
        != attempt.get("workspace_checkpoint")
        or attempt.get("evidence")
        != ["artifact://architecture-plan", "artifact://planning-decision"]
        or attempt.get("findings") != []
        or attempt.get("finding_counts")
        != {"critical": 0, "high": 0, "medium": 0, "low": 0, "cosmetic": 0}
        or not isinstance(dispatch_id, str)
        or dispatch_id in seed_dispatch_ids
        or dispatch_id == panel_dispatch_id
        or not isinstance(evidence_records, list)
        or len(evidence_records) != 2
    ):
        raise SmokeError("native em-reviewer attempt is not exactly ledger-bound")
    evidence_proof: dict[str, dict[str, str]] = {}
    for record, evidence_id in zip(
        evidence_records, ("architecture-plan", "planning-decision")
    ):
        if not isinstance(record, Mapping):
            raise SmokeError("native gate-owner evidence record is malformed")
        relative = record.get("artifact_path")
        digest = record.get("artifact_sha256")
        if (
            record.get("kind") != "managed-workflow-evidence"
            or record.get("run_id") != run_id
            or record.get("stage") != MANAGED_GATE_OWNER_STAGE
            or record.get("dispatch_id") != dispatch_id
            or record.get("dispatch_attempt") != 1
            or record.get("evidence_id") != evidence_id
            or record.get("validation_profile") != evidence_id
            or not isinstance(relative, str)
            or not _is_sha256(digest)
            or relative
            != (
                f".ckit/artifacts/evidence/runs/{run_id}/"
                f"{MANAGED_GATE_OWNER_STAGE}/1/{evidence_id}-{digest}.json"
            )
        ):
            raise SmokeError("native gate-owner evidence provenance is invalid")
        evidence_document, actual_digest = _private_managed_artifact(
            project, relative, label=f"native {evidence_id} evidence"
        )
        if actual_digest != digest:
            raise SmokeError("native gate-owner evidence is stale")
        if evidence_id == "architecture-plan":
            if digest != planning_packet_evidence["architecture-plan"] or any(
                not isinstance(evidence_document.get(field), list)
                or not evidence_document[field]
                or not all(
                    isinstance(value, str) and value.strip()
                    for value in evidence_document[field]
                )
                for field in (
                    "boundaries",
                    "dependencies",
                    "interfaces",
                    "verification",
                )
            ):
                raise SmokeError(
                    "native gate owner did not pass through the frozen architecture plan"
                )
        elif (
            "fixture_provenance" in evidence_document
            or evidence_document.get("status") != "PASS"
            or evidence_document.get("reviewer") != MANAGED_GATE_OWNER_ROLE
            or evidence_document.get("planning-generation") != planning_generation
            or evidence_document.get("panel-reviewers")
            != [MANAGED_PLANNING_REVIEW_ROLE]
            or evidence_document.get("findings") != []
            or evidence_document.get("decisions") != []
            or evidence_document.get("evidence")
            != ["specs/protected_gate_owner_spec.md"]
        ):
            raise SmokeError("native planning decision is not an exact bound PASS")
        evidence_proof[evidence_id] = {"path": relative, "sha256": digest}

    terminal_path = attempt.get("output_path")
    terminal_sha = attempt.get("output_artifact_sha256")
    if (
        not isinstance(terminal_path, str)
        or not _is_sha256(terminal_sha)
        or terminal_path
        != (
            f".ckit/artifacts/dispatch/runs/{run_id}/{MANAGED_GATE_OWNER_STAGE}/1/"
            f"terminal-{terminal_sha}.json"
        )
    ):
        raise SmokeError("native gate-owner terminal artifact identity is invalid")
    terminal_document, actual_terminal_sha = _private_managed_artifact(
        project, terminal_path, label="native gate-owner terminal result"
    )
    if (
        actual_terminal_sha != terminal_sha
        or terminal_document.get("run_id") != run_id
        or terminal_document.get("stage") != MANAGED_GATE_OWNER_STAGE
        or terminal_document.get("provider") != "codex"
        or terminal_document.get("route") != MANAGED_GATE_OWNER_ROLE
        or terminal_document.get("dispatch_id") != dispatch_id
        or terminal_document.get("status") != "succeeded"
        or terminal_document.get("evidence_records") != evidence_records
    ):
        raise SmokeError("native gate-owner terminal provenance is invalid")
    if result_document is not None:
        attempts = result_document.get("attempts")
        if (
            gate_closed
            or result_document.get("status") != "waiting-gate"
            or result_document.get("pending_gates") != [MANAGED_GATE_OWNER_GATE]
            or result_document.get("human_stop") is not None
            or not isinstance(attempts, list)
            or len(attempts) != 2
            or any(not isinstance(item, Mapping) for item in attempts)
            or [item.get("stage") for item in attempts]
            != [MANAGED_PLANNING_REVIEW_STAGE, MANAGED_GATE_OWNER_STAGE]
            or [item.get("role") for item in attempts]
            != [MANAGED_PLANNING_REVIEW_ROLE, MANAGED_GATE_OWNER_ROLE]
            or any(item.get("provider") != "codex" for item in attempts)
            or any(item.get("status") != "succeeded" for item in attempts)
        ):
            raise SmokeError("native gate-owner CLI result differs from its ledger")

    gate_bundle: dict[str, str] | None = None
    if gate_closed:
        transition = gate_history[-1]
        bundle_path = transition.get("evidence_path")
        bundle_sha = transition.get("evidence_sha256")
        if (
            transition.get("status") != "passed"
            or transition.get("owner_stage") != MANAGED_GATE_OWNER_STAGE
            or transition.get("owner_dispatch_id") != dispatch_id
            or transition.get("owner_dispatch_attempt") != 1
            or transition.get("owner_output_sha256") != attempt.get("output_sha256")
            or not isinstance(bundle_path, str)
            or not _is_sha256(bundle_sha)
        ):
            raise SmokeError("em-approved transition is not owner-bound")
        bundle_document, actual_bundle_sha = _private_managed_artifact(
            project, bundle_path, label="em-approved gate bundle"
        )
        if (
            actual_bundle_sha != bundle_sha
            or bundle_document.get("kind") != "managed-workflow-gate-evidence"
            or bundle_document.get("run_id") != run_id
            or bundle_document.get("gate") != MANAGED_GATE_OWNER_GATE
            or bundle_document.get("owner_stage") != MANAGED_GATE_OWNER_STAGE
            or bundle_document.get("owner_dispatch_id") != dispatch_id
            or bundle_document.get("owner_dispatch_attempt") != 1
            or bundle_document.get("owner_output_sha256")
            != attempt.get("output_sha256")
            or bundle_document.get("evidence_ids")
            != ["architecture-plan", "planning-decision"]
            or bundle_document.get("evidence_records") != evidence_records
            or bundle_document.get("evidence_set_digest")
            != transition.get("evidence_set_digest")
            or bundle_document.get("finding_counts")
            != {"critical": 0, "high": 0, "medium": 0, "low": 0, "cosmetic": 0}
        ):
            raise SmokeError("em-approved gate bundle is not authoritative")
        gate_bundle = {"path": bundle_path, "sha256": bundle_sha}

    return {
        "schema_version": 1,
        "provider": "codex",
        "host_version": host_version,
        "run_id": run_id,
        "stage": MANAGED_GATE_OWNER_STAGE,
        "role": MANAGED_GATE_OWNER_ROLE,
        "required_capabilities": list(MANAGED_GATE_OWNER_CAPABILITIES),
        "gate": MANAGED_GATE_OWNER_GATE,
        "native_host_claim": True,
        "fixture_seed": dict(seed_proof),
        "evidence": evidence_proof,
        "terminal_artifact": {"path": terminal_path, "sha256": terminal_sha},
        "gate_bundle": gate_bundle,
        "gate_history_digest": _gate_history_digest(gate_history),
        "snapshot_sha256": hashlib.sha256(
            (project / PIPELINE_SNAPSHOT).read_bytes()
        ).hexdigest(),
    }


def _run_managed_codex(root: Path, *, expected_version: str, executable: str) -> None:
    """Run bounded canonical passive stages through the exact-wheel Codex adapter."""

    inherited = {name for name in PROVIDER_SECRET_ENV if os.environ.get(name)}
    if inherited != {"OPENAI_API_KEY"} or os.environ.get("CKIT_OPENAI_API_KEY"):
        raise SmokeError(
            "managed Codex requires only OPENAI_API_KEY in its coordinator environment"
        )
    credential = os.environ["OPENAI_API_KEY"]
    resolved, _project, control, document = _load_control(root)
    if (
        document.get("managed_codex") is not None
        or document.get("managed_codex_gate_owner") is not None
    ):
        raise SmokeError("managed Codex proof is already recorded")
    resolved_executable = shutil.which(executable)
    if resolved_executable is None:
        raise SmokeError(f"Codex executable is unavailable: {executable}")
    host = Path(resolved_executable).resolve(strict=True)
    if host.name != "codex" or not os.access(host, os.X_OK):
        raise SmokeError("managed Codex proof requires an executable named codex")

    base_path = os.environ.get("PATH", "/usr/bin:/bin")
    secret_free_environment = {
        "PATH": f"{host.parent}{os.pathsep}{base_path}",
        "HOME": str(control / "managed-version-home"),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "CI": "true",
        "NO_COLOR": "1",
    }
    Path(secret_free_environment["HOME"]).mkdir(mode=0o700, exist_ok=True)
    version_result = _run_bounded_process(
        [str(host), "--version"],
        cwd=resolved,
        env=secret_free_environment,
        timeout=30,
        label="managed Codex version probe",
    )
    version_output = _decode_host_output(
        version_result.stdout + version_result.stderr,
        label="managed Codex version output",
    ).strip()
    if (
        version_result.returncode != 0
        or version_output != f"codex-cli {expected_version}"
    ):
        raise SmokeError(
            f"managed Codex host version mismatch: expected {expected_version!r}, "
            f"got {version_output!r}"
        )

    project = _prepare_managed_codex_project(root, document, control)
    home = control / "managed-coordinator-home"
    codex_home = control / "managed-codex-home"
    temporary = control / "managed-tmp"
    for directory in (home, codex_home, temporary):
        directory.mkdir(mode=0o700, exist_ok=False)
    environment = {
        "PATH": f"{host.parent}{os.pathsep}{base_path}",
        "HOME": str(home),
        "CODEX_HOME": str(codex_home),
        "TMPDIR": str(temporary),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "CI": "true",
        "NO_COLOR": "1",
        "CKIT_EXPERIMENTAL": "1",
        "OPENAI_API_KEY": credential,
    }
    for name in (
        "ALL_PROXY",
        "HTTPS_PROXY",
        "HTTP_PROXY",
        "NO_PROXY",
        "SSL_CERT_DIR",
        "SSL_CERT_FILE",
    ):
        if os.environ.get(name):
            environment[name] = os.environ[name]
    ckit = str(document["ckit_executable"])
    completed = _run_bounded_process(
        [
            ckit,
            "pipeline",
            "run",
            "--provider",
            "codex",
            str(project),
            "--json",
            "--wait-timeout-seconds",
            "300",
        ],
        cwd=project,
        env=environment,
        timeout=420,
        label="exact-wheel managed Codex pipeline run",
    )
    stdout = _decode_host_output(
        completed.stdout, label="managed Codex pipeline stdout"
    )
    stderr = _decode_host_output(
        completed.stderr, label="managed Codex pipeline stderr"
    )
    if completed.returncode != 3:
        raise SmokeError(
            "managed Codex pipeline did not stop at its unsupported writable boundary; "
            + _output_summary("stdout", stdout)
            + "; "
            + _output_summary("stderr", stderr)
        )
    try:
        result_document = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise SmokeError("managed Codex pipeline returned invalid JSON") from exc
    if not isinstance(result_document, dict):
        raise SmokeError("managed Codex pipeline result must be an object")
    proof = _assert_managed_codex_state(
        project,
        result_document=result_document,
        host_version=expected_version,
    )
    _run_ckit(
        document, project, control, "validate", str(project), "--strict", "--json"
    )

    gate_project, seed_proof = _prepare_managed_gate_owner_project(
        root, document, control
    )
    gate_completed = _run_bounded_process(
        [
            ckit,
            "pipeline",
            "run",
            "--provider",
            "codex",
            str(gate_project),
            "--json",
            "--context",
            "Architecture review and planning-merge are native; earlier predecessor "
            "records are fixture-seeded.",
            "--wait-timeout-seconds",
            "300",
        ],
        cwd=gate_project,
        env=environment,
        timeout=420,
        label="exact-wheel managed Codex gate-owner run",
    )
    gate_stdout = _decode_host_output(
        gate_completed.stdout, label="managed Codex gate-owner stdout"
    )
    gate_stderr = _decode_host_output(
        gate_completed.stderr, label="managed Codex gate-owner stderr"
    )
    if gate_completed.returncode != 0:
        raise SmokeError(
            "managed Codex gate owner did not stop at em-approved; "
            + _output_summary("stdout", gate_stdout)
            + "; "
            + _output_summary("stderr", gate_stderr)
        )
    try:
        gate_result_document = json.loads(gate_stdout)
    except json.JSONDecodeError as exc:
        raise SmokeError("managed Codex gate-owner result is invalid JSON") from exc
    if not isinstance(gate_result_document, dict):
        raise SmokeError("managed Codex gate-owner result must be an object")
    _assert_managed_codex_gate_owner_state(
        gate_project,
        seed_proof=seed_proof,
        host_version=expected_version,
        result_document=gate_result_document,
        gate_closed=False,
    )
    close_proof = _run_exact_wheel_harness(
        document, gate_project, control, "close-managed-gate-owner"
    )
    if (
        close_proof.get("kind") != "protected-native-gate-close"
        or close_proof.get("native_host_claim") is not True
        or close_proof.get("run_id") != seed_proof.get("run_id")
    ):
        raise SmokeError("managed Codex gate closure proof is invalid")
    gate_proof = _assert_managed_codex_gate_owner_state(
        gate_project,
        seed_proof=seed_proof,
        host_version=expected_version,
        gate_closed=True,
    )
    if gate_proof["gate_history_digest"] != close_proof.get("gate_history_digest"):
        raise SmokeError("managed gate-history digest changed across public closure")
    _run_ckit(
        document,
        gate_project,
        control,
        "validate",
        str(gate_project),
        "--strict",
        "--json",
    )

    workspace = document_path = None
    managed = _pipeline_document(project).get("managed_execution")
    if isinstance(managed, dict):
        raw_workspace = managed.get("workspace")
        if isinstance(raw_workspace, dict):
            document_path = raw_workspace.get("target_path")
    if isinstance(document_path, str):
        candidate = (project / document_path).resolve(strict=True)
        candidate.relative_to(resolved)
        workspace = candidate
    _assert_tree_has_no_plaintext(project, (credential,), label="managed Codex project")
    if workspace is not None:
        _assert_tree_has_no_plaintext(
            workspace, (credential,), label="managed Codex worktree"
        )
    gate_workspace: Path | None = None
    gate_managed = _pipeline_document(gate_project).get("managed_execution")
    if isinstance(gate_managed, Mapping):
        raw_workspace = gate_managed.get("workspace")
        if isinstance(raw_workspace, Mapping) and isinstance(
            raw_workspace.get("target_path"), str
        ):
            gate_workspace = (gate_project / str(raw_workspace["target_path"])).resolve(
                strict=True
            )
            gate_workspace.relative_to(resolved)
    _assert_tree_has_no_plaintext(
        gate_project, (credential,), label="managed Codex gate-owner project"
    )
    if gate_workspace is not None:
        _assert_tree_has_no_plaintext(
            gate_workspace,
            (credential,),
            label="managed Codex gate-owner worktree",
        )
    _assert_control_has_no_plaintext(control, (credential,))
    document["managed_codex"] = proof
    document["managed_codex_gate_owner"] = gate_proof
    _write_json(control / CONTROL_FILE, document)
    _assert_control_has_no_plaintext(control, (credential,))
    print(
        json.dumps(
            {
                "provider": "codex",
                "version": expected_version,
                "managed_stage": MANAGED_PASSIVE_STAGE,
                "managed_gate_owner": MANAGED_GATE_OWNER_STAGE,
                "managed_gate": MANAGED_GATE_OWNER_GATE,
                "stop_reason": proof["stop_reason"],
                "ok": True,
            },
            sort_keys=True,
        )
    )


def _advance_pipeline(
    document: dict[str, Any],
    project: Path,
    control: Path,
    *,
    provider: str,
    version: str,
    receipt: Path,
) -> None:
    pipeline = _pipeline_document(project)
    history = pipeline["gate_history"]
    raw_order = document.get("provider_order")
    if not isinstance(raw_order, list) or tuple(raw_order) not in set(
        PROVIDER_ORDERS.values()
    ):
        raise SmokeError("protected provider order is invalid")
    provider_order = tuple(raw_order)
    if provider not in provider_order:
        raise SmokeError(f"provider {provider!r} is outside the protected direction")
    provider_index = provider_order.index(provider)
    expected_stage = ("code-review", "build-green")[provider_index]
    expected_count = provider_index
    expected_prior = "none" if provider_index == 0 else provider_order[0]
    if (
        pipeline.get("status") != "active"
        or pipeline.get("stage") != expected_stage
        or len(history) != expected_count
        or _prior_pipeline_provider(project, pipeline) != expected_prior
    ):
        raise SmokeError(f"shared Mode D pipeline is not ready for {provider}")

    evidence_relative = PIPELINE_EVIDENCE_DIR / f"{provider}.json"
    evidence = project / evidence_relative
    if evidence.exists():
        raise SmokeError(f"refusing to replace existing {provider} pipeline evidence")
    _write_json(
        evidence,
        {
            "schema_version": SCHEMA_VERSION,
            "provider": provider,
            "host_version": version,
            "gate": expected_stage,
            "open_findings": {
                "critical": 0,
                "high": 0,
                "medium": 0,
                "low": 0,
                "cosmetic": 0,
            },
            "receipt_sha256": hashlib.sha256(receipt.read_bytes()).hexdigest(),
        },
    )
    evidence_arg = evidence_relative.as_posix()
    if provider_index == 0:
        _run_ckit(
            document,
            project,
            control,
            "record-findings",
            str(project),
            "--critical",
            "0",
            "--high",
            "0",
            "--medium",
            "0",
            "--low",
            "0",
            "--cosmetic",
            "0",
            "--evidence",
            evidence_arg,
        )
    _run_ckit(
        document,
        project,
        control,
        "close-gate",
        expected_stage,
        str(project),
        "--evidence",
        evidence_arg,
        "--strict",
    )
    if provider_index == 1:
        _run_ckit(document, project, control, "complete", str(project))
    _run_ckit(
        document, project, control, "validate", str(project), "--strict", "--json"
    )
    if provider_index == 0:
        checkpoints = document.get("pipeline_checkpoints")
        if not isinstance(checkpoints, dict):
            raise SmokeError("protected pipeline checkpoint contract is invalid")
        checkpoints[provider_order[1]] = hashlib.sha256(
            (project / PIPELINE_SNAPSHOT).read_bytes()
        ).hexdigest()
        _write_json(control / CONTROL_FILE, document)


def _run_claude(
    root: Path,
    *,
    auth_settings: Path,
    expected_version: str,
    executable: str,
    model: str | None,
) -> None:
    _assert_no_provider_secret_env()
    _resolved, project, control, document = _load_control(root)
    settings = _private_external_file(
        auth_settings, project=project, label="Claude auth settings"
    )
    resolved_executable = shutil.which(executable)
    if resolved_executable is None:
        raise SmokeError(f"Claude executable is unavailable: {executable}")
    resolved_executable = str(Path(resolved_executable).resolve(strict=True))
    environment = _host_environment(root)

    version_result = _run_bounded_process(
        [resolved_executable, "--version"],
        cwd=project,
        env=environment,
        timeout=30,
        label="Claude version probe",
    )
    version_output = _decode_host_output(
        version_result.stdout + version_result.stderr,
        label="Claude version output",
    ).strip()
    if version_result.returncode != 0 or expected_version not in version_output:
        raise SmokeError(
            f"Claude host version mismatch: expected {expected_version!r}, got {version_output!r}"
        )

    argv = [
        resolved_executable,
        "-p",
        CLAUDE_PROMPT,
        "--output-format",
        "json",
        "--json-schema",
        json.dumps(OUTPUT_SCHEMA, separators=(",", ":")),
        "--permission-mode",
        "dontAsk",
        "--tools",
        "Read,Agent,Skill",
        "--disallowedTools",
        "Bash,Edit,Write,NotebookEdit,WebFetch,WebSearch",
        "--max-turns",
        "16",
        "--max-budget-usd",
        "2.00",
        "--no-session-persistence",
        "--strict-mcp-config",
        "--mcp-config",
        json.dumps({"mcpServers": {}}),
        "--setting-sources",
        "project",
        "--settings",
        str(settings),
    ]
    if model:
        argv.extend(("--model", model))
    completed = _run_bounded_process(
        argv,
        cwd=project,
        env=environment,
        timeout=900,
        label="Claude protected behavior run",
    )
    stdout = _decode_host_output(completed.stdout, label="Claude stdout")
    stderr = _decode_host_output(completed.stderr, label="Claude stderr")
    if completed.returncode != 0:
        raise SmokeError(
            f"Claude protected behavior run failed ({completed.returncode}); "
            f"{_output_summary('stdout', stdout)}; "
            f"{_output_summary('stderr', stderr)}"
        )
    observation = _extract_observation(stdout)
    _assert_pipeline_checkpoint(document, project, "claude")
    observation_commitments = _assert_observation(
        document, project, "claude", observation, stdout + stderr
    )
    counts = _assert_events(project, "claude", document)
    _assert_project_unchanged(project, document)
    receipt = _write_receipt(
        control,
        provider="claude",
        version=expected_version,
        observation_commitments=observation_commitments,
        output=stdout,
        counts=counts,
    )
    _advance_pipeline(
        document,
        project,
        control,
        provider="claude",
        version=expected_version,
        receipt=receipt,
    )
    print(json.dumps({"provider": "claude", "version": expected_version, "ok": True}))


def _record_codex(root: Path, *, output_file: Path, expected_version: str) -> None:
    _assert_no_provider_secret_env()
    _resolved, project, control, document = _load_control(root)
    output = _private_external_file(output_file, project=project, label="Codex output")
    try:
        output.relative_to(control.resolve(strict=True))
    except ValueError as exc:
        raise SmokeError(
            "Codex output must be contained by the smoke control directory"
        ) from exc
    try:
        with output.open("rb") as handle:
            raw_bytes = handle.read(MAX_HOST_OUTPUT_BYTES + 1)
    finally:
        output.unlink(missing_ok=True)
    if len(raw_bytes) > MAX_HOST_OUTPUT_BYTES:
        raise SmokeError("Codex output exceeded the protected 1 MiB limit")
    raw = _decode_host_output(raw_bytes, label="Codex output")
    observation = _extract_observation(raw)
    _assert_pipeline_checkpoint(document, project, "codex")
    observation_commitments = _assert_observation(
        document, project, "codex", observation, raw
    )
    counts = _assert_events(project, "codex", document)
    _assert_project_unchanged(project, document)
    receipt = _write_receipt(
        control,
        provider="codex",
        version=expected_version,
        observation_commitments=observation_commitments,
        output=raw,
        counts=counts,
    )
    _advance_pipeline(
        document,
        project,
        control,
        provider="codex",
        version=expected_version,
        receipt=receipt,
    )
    print(json.dumps({"provider": "codex", "version": expected_version, "ok": True}))


def _read_receipt(control: Path, provider: str) -> dict[str, Any]:
    path = control / "receipts" / f"{provider}.json"
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SmokeError(
            f"{provider} protected behavior receipt is missing: {exc}"
        ) from exc
    if (
        document.get("provider") != provider
        or document.get("schema_version") != SCHEMA_VERSION
    ):
        raise SmokeError(f"{provider} protected behavior receipt is invalid")
    return document


def _verify(root: Path) -> None:
    _assert_no_provider_secret_env()
    _resolved, project, control, document = _load_control(root)
    receipts = {
        provider: _read_receipt(control, provider) for provider in ("claude", "codex")
    }
    expected_all = document["expected_commitments"]
    provider_order = tuple(document["provider_order"])
    expected_dynamic = {
        provider: {
            "pipeline_stage": ("code-review", "build-green")[index],
            "gate_history_count": str(index),
            "prior_provider_transition": "none" if index == 0 else provider_order[0],
        }
        for index, provider in enumerate(provider_order)
    }
    for provider, receipt in receipts.items():
        expected = expected_all[provider]
        commitments = receipt.get("observation_commitments")
        if (
            not isinstance(commitments, Mapping)
            or set(commitments) != set(REQUIRED_FIELDS)
            or not all(_is_sha256(value) for value in commitments.values())
            or any(
                not hmac.compare_digest(str(commitments[field]), str(expected[field]))
                for field in CONTROL_EXPECTED_FIELDS
            )
        ):
            raise SmokeError(
                f"{provider} receipt does not match the protected commitments"
            )
        for field, value in expected_dynamic[provider].items():
            if not hmac.compare_digest(
                str(commitments[field]), _commitment(provider, field, value)
            ):
                raise SmokeError(
                    f"{provider} receipt does not prove its expected pipeline transition"
                )
        if receipt.get("credential_env_in_hooks") != []:
            raise SmokeError(f"{provider} receipt reports credential exposure to hooks")
        if (
            receipt.get("read_only_snapshot_preserved") is not True
            or receipt.get("pipeline_snapshot_preserved") is not True
        ):
            raise SmokeError(
                f"{provider} receipt does not attest its read-only checkpoint"
            )
        current_counts = _assert_events(project, provider, document)
        if receipt.get("event_counts") != current_counts:
            raise SmokeError(
                f"{provider} receipt event counts do not match native hook evidence"
            )

    _run_ckit(
        document, project, control, "validate", str(project), "--strict", "--json"
    )
    pipeline = _pipeline_document(project)
    history = pipeline["gate_history"]
    shared_gate_digest = str(pipeline["gate_definition_digest"])
    for provider in ("claude", "codex"):
        expected_gate = _commitment(provider, "gate_digest", shared_gate_digest)
        if not hmac.compare_digest(
            expected_gate, str(expected_all[provider]["gate_digest"])
        ) or not hmac.compare_digest(
            expected_gate,
            str(receipts[provider]["observation_commitments"]["gate_digest"]),
        ):
            raise SmokeError(
                "Claude and Codex did not observe the same shared .ckit gate digest"
            )
    if (
        pipeline.get("status") != "completed"
        or pipeline.get("stage") != "completed"
        or pipeline.get("ordered_gates") != ["code-review", "build-green"]
        or [item.get("gate") for item in history if isinstance(item, Mapping)]
        != ["code-review", "build-green"]
    ):
        raise SmokeError(
            "shared exact-wheel Mode D pipeline is not complete and ordered"
        )
    for provider, transition in zip(provider_order, history):
        receipt_path = control / "receipts" / f"{provider}.json"
        evidence_path = project / str(transition.get("evidence_path", ""))
        try:
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SmokeError(f"{provider} pipeline evidence is invalid: {exc}") from exc
        evidence_sha = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
        receipt_sha = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
        if (
            transition.get("status") != "passed"
            or transition.get("evidence_sha256") != evidence_sha
            or evidence.get("provider") != provider
            or evidence.get("gate") != transition.get("gate")
            or evidence.get("open_findings")
            != {
                "critical": 0,
                "high": 0,
                "medium": 0,
                "low": 0,
                "cosmetic": 0,
            }
            or evidence.get("receipt_sha256") != receipt_sha
        ):
            raise SmokeError(f"{provider} gate transition is not bound to its receipt")
    managed_proof = document.get("managed_codex")
    if isinstance(managed_proof, Mapping):
        managed_project = root.resolve(strict=True) / MANAGED_PROJECT_DIR
        actual_managed_proof = _assert_managed_codex_state(
            managed_project,
            host_version=str(managed_proof["host_version"]),
        )
        if actual_managed_proof != dict(managed_proof):
            raise SmokeError(
                "managed Codex proof differs from its live root-owned evidence ledger"
            )
    gate_owner_proof = document.get("managed_codex_gate_owner")
    if isinstance(gate_owner_proof, Mapping):
        gate_project = root.resolve(strict=True) / MANAGED_GATE_OWNER_PROJECT_DIR
        raw_seed = gate_owner_proof.get("fixture_seed")
        if not isinstance(raw_seed, Mapping):
            raise SmokeError("managed gate-owner proof has no fixture boundary")
        actual_gate_owner_proof = _assert_managed_codex_gate_owner_state(
            gate_project,
            seed_proof=raw_seed,
            host_version=str(gate_owner_proof["host_version"]),
            gate_closed=True,
        )
        if actual_gate_owner_proof != dict(gate_owner_proof):
            raise SmokeError(
                "managed Codex gate-owner proof differs from its live authoritative ledger"
            )
    _assert_project_unchanged(project, document)
    print(
        json.dumps(
            {
                "ok": True,
                "providers": {
                    provider: receipts[provider]["host_version"]
                    for provider in ("claude", "codex")
                },
                "shared_gate_digest": shared_gate_digest,
                "pipeline_status": pipeline["status"],
                "shared_gate_history_entries": len(history),
                "session_start_counts": {
                    provider: receipts[provider]["event_counts"]["session-start"]
                    for provider in ("claude", "codex")
                },
            },
            sort_keys=True,
        )
    )


def _contains_text(value: Any, needle: str) -> bool:
    if isinstance(value, str):
        return needle in value.replace("\\", "/")
    if isinstance(value, Mapping):
        return any(_contains_text(item, needle) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return any(_contains_text(item, needle) for item in value)
    return False


def _normalized_discovery_path(value: str) -> str:
    normalized = value.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _shell_read_tokens(command: str) -> tuple[str, ...]:
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()")
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        tokens = list(lexer)
    except ValueError:
        return ()
    segments: list[list[str]] = [[]]
    for token in tokens:
        if token and all(char in ";&|()" for char in token):
            if segments[-1]:
                segments.append([])
            continue
        segments[-1].append(token)
    readers = {
        "cat",
        "head",
        "tail",
        "sed",
        "grep",
        "rg",
        "less",
        "more",
        "awk",
        "jq",
    }
    paths: list[str] = []
    for segment in segments:
        while segment and ("=" in segment[0] or segment[0] in {"env", "command"}):
            segment = segment[1:]
        if not segment:
            continue
        executable = Path(segment[0]).name
        if executable in {"bash", "sh", "zsh"} and "-c" in segment[1:]:
            index = segment.index("-c") + 1
            if index < len(segment):
                paths.extend(_shell_read_tokens(segment[index]))
            continue
        if executable in readers:
            paths.extend(token for token in segment[1:] if not token.startswith("-"))
    return tuple(paths)


def _protected_definition_request(
    provider: str, envelope: Mapping[str, Any]
) -> str | None:
    protected = PROTECTED_DISCOVERY_PATHS[provider]
    tool_input = envelope.get("tool_input")
    if not isinstance(tool_input, Mapping):
        return None
    candidates: tuple[str, ...] = ()
    if envelope.get("tool_name") in {"Read", "read_file"}:
        value = tool_input.get("file_path", tool_input.get("path"))
        if isinstance(value, str):
            candidates = (value,)
    elif envelope.get("tool_name") in {
        "Bash",
        "exec_command",
        "shell",
        "unified_exec",
    }:
        command = tool_input.get("command", tool_input.get("cmd"))
        if isinstance(command, str):
            candidates = _shell_read_tokens(command)
    for candidate in candidates:
        normalized = _normalized_discovery_path(candidate)
        for path in protected:
            if normalized == path or normalized.endswith("/" + path):
                return path
    return None


def _allowed_fixture_read_path(value: str) -> bool:
    normalized = _normalized_discovery_path(value)
    if any(
        normalized == allowed or normalized.endswith("/" + allowed)
        for allowed in ALLOWED_FIXTURE_READ_PATHS
    ):
        return True
    evidence = PIPELINE_EVIDENCE_DIR.as_posix() + "/"
    return (
        (normalized.startswith(evidence) or f"/{evidence}" in normalized)
        and normalized.endswith(".json")
        and ".." not in Path(normalized).parts
    )


def _fixture_read_boundary_violation(
    provider: str, envelope: Mapping[str, Any]
) -> str | None:
    """Fail closed on model reads that cannot be attributed to the tiny fixture allowlist."""

    definition = _protected_definition_request(provider, envelope)
    if definition is not None:
        return f"protected-definition:{definition}"
    tool_input = envelope.get("tool_input")
    if not isinstance(tool_input, Mapping):
        return None
    tool_name = envelope.get("tool_name")
    if tool_name in {"Read", "read_file"}:
        value = tool_input.get("file_path", tool_input.get("path"))
        if not isinstance(value, str) or not _allowed_fixture_read_path(value):
            return "unapproved-file-read"
        return None
    if tool_name not in {"Bash", "exec_command", "shell", "unified_exec"}:
        return None
    command = tool_input.get("command", tool_input.get("cmd"))
    if not isinstance(command, str) or not command.strip():
        return "unparseable-shell-read"
    if provider == "claude" or any(token in command for token in ("$(`", "$(", "`")):
        return "unapproved-shell-command"
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        return "unparseable-shell-read"
    if len(tokens) < 2 or Path(tokens[0]).name != "cat":
        return "unapproved-shell-command"
    operands = [token for token in tokens[1:] if token != "--"]
    if not operands or any(
        token.startswith("-") or not _allowed_fixture_read_path(token)
        for token in operands
    ):
        return "unapproved-shell-read"
    return None


def _append_event(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n"
    descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, data.encode("utf-8"))
    finally:
        os.close(descriptor)


def _native_operation(envelope: Mapping[str, Any]) -> str:
    tool_name = envelope.get("tool_name")
    if tool_name in {"Read", "read_file"}:
        return "file-read"
    if tool_name in {"Bash", "exec_command", "shell", "unified_exec"}:
        return "shell"
    return "other"


def _metadata_envelope(raw: bytes) -> dict[str, Any]:
    try:
        document = json.loads(raw.decode("utf-8")) if raw.strip() else {}
    except (UnicodeError, json.JSONDecodeError):
        return {}
    return document if isinstance(document, dict) else {}


def _codex_denied(stdout: bytes) -> bool:
    try:
        document = json.loads(stdout.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return False
    output = (
        document.get("hookSpecificOutput") if isinstance(document, Mapping) else None
    )
    return (
        isinstance(output, Mapping)
        and output.get("hookEventName") == "PreToolUse"
        and output.get("permissionDecision") == "deny"
        and BLOCK_REASON in str(output.get("permissionDecisionReason", ""))
    )


def _generated_guard_disposition(
    provider: str, *, exit_code: int, stdout: bytes, stderr: bytes
) -> str:
    if provider == "claude":
        if (
            exit_code == 2
            and not stdout
            and stderr == (GENERATED_BLOCK_REASON + "\n").encode("utf-8")
        ):
            return "block"
        if exit_code == 0 and not stdout.strip() and not stderr.strip():
            return "allow"
        return "error"
    if exit_code == 0 and not stderr and _codex_denied(stdout):
        return "block"
    if exit_code == 0 and not stdout.strip() and not stderr.strip():
        return "allow"
    return "error"


def _expected_guard_hashes(provider: str, disposition: str) -> tuple[str, str, int]:
    empty = b""
    if disposition == "allow":
        stdout = stderr = empty
        exit_code = 0
    elif provider == "claude":
        stdout = empty
        stderr = (GENERATED_BLOCK_REASON + "\n").encode("utf-8")
        exit_code = 2
    else:
        stdout = (
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": GENERATED_BLOCK_REASON,
                    }
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
        stderr = empty
        exit_code = 0
    return (
        hashlib.sha256(stdout).hexdigest(),
        hashlib.sha256(stderr).hexdigest(),
        exit_code,
    )


def _recorded_guard_disposition(provider: str, event: Mapping[str, Any]) -> str:
    for disposition in ("block", "allow"):
        stdout_hash, stderr_hash, exit_code = _expected_guard_hashes(
            provider, disposition
        )
        if (
            event.get("exit_code") == exit_code
            and event.get("stdout_sha256") == stdout_hash
            and event.get("stderr_sha256") == stderr_hash
        ):
            return disposition
    return "error"


def _recorded_stop_disposition(
    event: Mapping[str, Any], contract: Mapping[str, Any]
) -> str:
    empty_hash = hashlib.sha256(b"").hexdigest()
    if (
        event.get("stop_hook_active") is False
        and event.get("exit_code") == 0
        and event.get("stdout_sha256") == contract.get("expected_block_stdout_sha256")
        and event.get("stderr_sha256") == empty_hash
    ):
        return "block"
    if (
        event.get("stop_hook_active") is True
        and event.get("exit_code") == 0
        and event.get("stdout_sha256") == empty_hash
        and event.get("stderr_sha256") == empty_hash
    ):
        return "allow"
    return "error"


def _write_all(descriptor: int, data: bytes) -> None:
    remaining = memoryview(data)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:  # pragma: no cover - os.write contract
            raise SmokeError("generated guard relay made no forward progress")
        remaining = remaining[written:]


def _guard_proxy(
    provider: str,
    handler_id: str,
    handler: str,
    handler_sha256: str,
    project: Path,
    log: Path,
) -> int:
    if provider not in {"claude", "codex"} or handler_id != "protect-secrets":
        raise SmokeError("unsupported generated guard proxy contract")
    actual_handler_sha256 = hashlib.sha256(handler.encode("utf-8")).hexdigest()
    if not hmac.compare_digest(actual_handler_sha256, handler_sha256):
        raise SmokeError("generated guard proxy handler digest mismatch")
    resolved_project = project.resolve(strict=True)
    expected_log = (resolved_project / EVENT_LOG).resolve(strict=False)
    if log.resolve(strict=False) != expected_log:
        raise SmokeError("generated guard proxy log is outside the protected fixture")

    raw = sys.stdin.buffer.read(MAX_HOST_OUTPUT_BYTES + 1)
    if len(raw) > MAX_HOST_OUTPUT_BYTES:
        raise SmokeError("generated guard input exceeded the protected 1 MiB limit")

    present = sorted(name for name in HOOK_SECRET_ENV if os.environ.get(name))
    child_env = {
        name: os.environ[name]
        for name in (
            "PATH",
            "HOME",
            "LANG",
            "NO_COLOR",
            "CKIT_PROJECT_ROOT",
            "CLAUDE_PROJECT_DIR",
            "CKIT_HOOK_PROVIDER",
        )
        if os.environ.get(name)
    }
    if present:
        envelope = _metadata_envelope(raw)
        _append_event(
            expected_log,
            {
                "record_schema_version": 1,
                "provider": provider,
                "event": "generated-guard",
                "handler_id": handler_id,
                "handler_sha256": actual_handler_sha256,
                "generated_guard_disposition": "error",
                "exit_code": 3,
                "stdout_sha256": hashlib.sha256(b"").hexdigest(),
                "stderr_sha256": hashlib.sha256(
                    b"CKIT_SMOKE_CREDENTIAL_ENV_LEAK\n"
                ).hexdigest(),
                "credential_env_present": present,
                "native_operation": _native_operation(envelope),
                "target_requested": _contains_text(envelope, BLOCK_TARGET),
            },
        )
        _write_all(2, b"CKIT_SMOKE_CREDENTIAL_ENV_LEAK\n")
        return 3
    try:
        completed = _run_bounded_process(
            ["/bin/sh", "-c", handler],
            cwd=resolved_project,
            env=child_env,
            timeout=30,
            label="generated protect-secrets handler",
            input_data=raw,
        )
    except SmokeError:
        envelope = _metadata_envelope(raw)
        failure = b"CKIT_SMOKE_GENERATED_GUARD_FAILURE\n"
        _append_event(
            expected_log,
            {
                "record_schema_version": 1,
                "provider": provider,
                "event": "generated-guard",
                "handler_id": handler_id,
                "handler_sha256": actual_handler_sha256,
                "generated_guard_disposition": "error",
                "exit_code": 3,
                "stdout_sha256": hashlib.sha256(b"").hexdigest(),
                "stderr_sha256": hashlib.sha256(failure).hexdigest(),
                "credential_env_present": [],
                "native_operation": _native_operation(envelope),
                "target_requested": _contains_text(envelope, BLOCK_TARGET),
            },
        )
        _write_all(2, failure)
        return 3
    envelope = _metadata_envelope(raw)
    disposition = _generated_guard_disposition(
        provider,
        exit_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )
    _append_event(
        expected_log,
        {
            "record_schema_version": 1,
            "provider": provider,
            "event": "generated-guard",
            "handler_id": handler_id,
            "handler_sha256": actual_handler_sha256,
            "generated_guard_disposition": disposition,
            "exit_code": completed.returncode,
            "stdout_sha256": hashlib.sha256(completed.stdout).hexdigest(),
            "stderr_sha256": hashlib.sha256(completed.stderr).hexdigest(),
            "credential_env_present": [],
            "native_operation": _native_operation(envelope),
            "target_requested": _contains_text(envelope, BLOCK_TARGET),
        },
    )
    _write_all(1, completed.stdout)
    _write_all(2, completed.stderr)
    return completed.returncode


def _stop_proxy_disposition(
    *,
    active: bool | None,
    exit_code: int,
    stdout: bytes,
    stderr: bytes,
) -> str:
    if active is True:
        if exit_code == 0 and not stdout.strip() and not stderr.strip():
            return "allow"
        return "error"
    if active is not False or exit_code != 0 or stderr:
        return "error"
    try:
        payload = json.loads(stdout.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return "error"
    if (
        isinstance(payload, Mapping)
        and set(payload) == {"decision", "reason"}
        and payload.get("decision") == "block"
        and "RARV step 4" in str(payload.get("reason", ""))
        and STOP_SENTINEL in str(payload.get("reason", ""))
    ):
        return "block"
    return "error"


def _stop_proxy(
    provider: str,
    handler_id: str,
    handler: str,
    handler_sha256: str,
    project: Path,
    log: Path,
) -> int:
    if (
        provider not in {"claude", "codex"}
        or handler_id != "verify-continuity-writeback"
    ):
        raise SmokeError("unsupported generated Stop proxy contract")
    actual_handler_sha256 = hashlib.sha256(handler.encode("utf-8")).hexdigest()
    if not hmac.compare_digest(actual_handler_sha256, handler_sha256):
        raise SmokeError("generated Stop proxy handler digest mismatch")
    resolved_project = project.resolve(strict=True)
    expected_log = (resolved_project / EVENT_LOG).resolve(strict=False)
    if log.resolve(strict=False) != expected_log:
        raise SmokeError("generated Stop proxy log is outside the protected fixture")
    raw = sys.stdin.buffer.read(MAX_HOST_OUTPUT_BYTES + 1)
    if len(raw) > MAX_HOST_OUTPUT_BYTES:
        raise SmokeError("generated Stop input exceeded the protected 1 MiB limit")
    present = sorted(name for name in HOOK_SECRET_ENV if os.environ.get(name))
    child_env = {
        name: os.environ[name]
        for name in (
            "PATH",
            "HOME",
            "LANG",
            "NO_COLOR",
            "CKIT_PROJECT_ROOT",
            "CLAUDE_PROJECT_DIR",
            "CKIT_HOOK_PROVIDER",
        )
        if os.environ.get(name)
    }
    if present:
        _write_all(2, b"CKIT_SMOKE_CREDENTIAL_ENV_LEAK\n")
        return 3
    completed = _run_bounded_process(
        ["/bin/sh", "-c", handler],
        cwd=resolved_project,
        env=child_env,
        timeout=30,
        label="generated verify-continuity-writeback handler",
        input_data=raw,
    )
    envelope = _metadata_envelope(raw)
    active_value = envelope.get("stop_hook_active")
    active = active_value if isinstance(active_value, bool) else None
    disposition = _stop_proxy_disposition(
        active=active,
        exit_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )
    _append_event(
        expected_log,
        {
            "record_schema_version": 1,
            "provider": provider,
            "event": "generated-stop",
            "handler_id": handler_id,
            "handler_sha256": actual_handler_sha256,
            "generated_stop_disposition": disposition,
            "stop_hook_active": active,
            "exit_code": completed.returncode,
            "stdout_sha256": hashlib.sha256(completed.stdout).hexdigest(),
            "stderr_sha256": hashlib.sha256(completed.stderr).hexdigest(),
            "credential_env_present": [],
        },
    )
    _write_all(1, completed.stdout)
    _write_all(2, completed.stderr)
    return completed.returncode


def _hook(provider: str, event: str, log: Path) -> int:
    if provider not in {"claude", "codex"}:
        raise SmokeError(f"unsupported hook provider: {provider}")
    if event not in {
        "session-start",
        "subagent-start",
        "definition-read",
        "post-tool",
    }:
        raise SmokeError(f"unsupported protected hook event: {event}")
    present = sorted(name for name in HOOK_SECRET_ENV if os.environ.get(name))
    raw = sys.stdin.buffer.read(MAX_HOST_OUTPUT_BYTES + 1)
    if len(raw) > MAX_HOST_OUTPUT_BYTES:
        raise SmokeError("hook input exceeded the protected 1 MiB limit")
    try:
        envelope = json.loads(raw.decode("utf-8")) if raw.strip() else {}
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SmokeError(f"protected hook received invalid JSON: {exc}") from exc
    if not isinstance(envelope, dict):
        raise SmokeError("protected hook envelope must be an object")

    definition_path = _protected_definition_request(provider, envelope)
    read_boundary_violation = _fixture_read_boundary_violation(provider, envelope)
    target_requested = _contains_text(envelope, BLOCK_TARGET)
    if event == "post-tool":
        should_record = (
            _contains_text(envelope, PIPELINE_SNAPSHOT.name)
            or target_requested
            or read_boundary_violation is not None
        )
    elif event == "definition-read":
        should_record = read_boundary_violation is not None
    else:
        should_record = True
    if should_record or present:
        _append_event(
            log.resolve(strict=False),
            {
                "provider": provider,
                "event": event,
                "credential_env_present": present,
                "agent_type": envelope.get("agent_type")
                if isinstance(envelope.get("agent_type"), str)
                else None,
                "risk_classifier": envelope.get("agent_type") == "risk-classifier",
                "target_requested": target_requested,
                "definition_path": definition_path,
                "read_boundary_violation": read_boundary_violation,
            },
        )
    if present:
        print("CKIT_SMOKE_CREDENTIAL_ENV_LEAK", file=sys.stderr)
        return 3
    if event == "definition-read" and read_boundary_violation is not None:
        reason = "protected fixture reads must use the native bounded allowlist"
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": reason,
                    }
                },
                separators=(",", ":"),
            )
        )
        return 0
    if event == "post-tool" and should_record:
        output: dict[str, Any]
        if provider == "codex":
            output = {
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": ADVISORY_MARKER,
                }
            }
        else:
            output = {"systemMessage": ADVISORY_MARKER}
        print(json.dumps(output, separators=(",", ":")))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    prepare = commands.add_parser(
        "prepare", help="create a new isolated native-host fixture"
    )
    prepare.add_argument("--root", type=Path, required=True)
    prepare.add_argument(
        "--ckit-executable",
        required=True,
        help="ckit executable installed from the exact wheel under test",
    )
    prepare.add_argument(
        "--direction",
        choices=tuple(PROVIDER_ORDERS),
        default="claude-codex",
    )

    claude = commands.add_parser(
        "run-claude", help="run the protected Claude behavior proof"
    )
    claude.add_argument("--root", type=Path, required=True)
    claude.add_argument("--auth-settings", type=Path, required=True)
    claude.add_argument("--expected-version", required=True)
    claude.add_argument("--executable", default="claude")
    claude.add_argument("--model")

    codex = commands.add_parser(
        "record-codex", help="validate output produced by protected openai/codex-action"
    )
    codex.add_argument("--root", type=Path, required=True)
    codex.add_argument("--output-file", type=Path, required=True)
    codex.add_argument("--expected-version", required=True)

    managed_codex = commands.add_parser(
        "run-managed-codex",
        help="run the canonical passive managed stage and gate-owner proofs",
    )
    managed_codex.add_argument("--root", type=Path, required=True)
    managed_codex.add_argument("--expected-version", required=True)
    managed_codex.add_argument("--executable", default="codex")

    seed_gate_owner = commands.add_parser(
        "seed-managed-gate-owner", help=argparse.SUPPRESS
    )
    seed_gate_owner.add_argument("--project", type=Path, required=True)
    close_gate_owner = commands.add_parser(
        "close-managed-gate-owner", help=argparse.SUPPRESS
    )
    close_gate_owner.add_argument("--project", type=Path, required=True)

    verify = commands.add_parser(
        "verify", help="verify both native-host behavior receipts"
    )
    verify.add_argument("--root", type=Path, required=True)

    hook = commands.add_parser("hook", help=argparse.SUPPRESS)
    hook.add_argument("--provider", required=True)
    hook.add_argument("--event", required=True)
    hook.add_argument("--log", type=Path, required=True)

    guard = commands.add_parser("guard-proxy", help=argparse.SUPPRESS)
    guard.add_argument("--provider", required=True)
    guard.add_argument("--handler-id", required=True)
    guard.add_argument("--handler", required=True)
    guard.add_argument("--handler-sha256", required=True)
    guard.add_argument("--project", type=Path, required=True)
    guard.add_argument("--log", type=Path, required=True)
    stop = commands.add_parser("stop-proxy", help=argparse.SUPPRESS)
    stop.add_argument("--provider", required=True)
    stop.add_argument("--handler-id", required=True)
    stop.add_argument("--handler", required=True)
    stop.add_argument("--handler-sha256", required=True)
    stop.add_argument("--project", type=Path, required=True)
    stop.add_argument("--log", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "prepare":
            _prepare(
                args.root,
                ckit_executable=args.ckit_executable,
                direction=args.direction,
            )
        elif args.command == "run-claude":
            _run_claude(
                args.root,
                auth_settings=args.auth_settings,
                expected_version=args.expected_version,
                executable=args.executable,
                model=args.model,
            )
        elif args.command == "record-codex":
            _record_codex(
                args.root,
                output_file=args.output_file,
                expected_version=args.expected_version,
            )
        elif args.command == "run-managed-codex":
            _run_managed_codex(
                args.root,
                expected_version=args.expected_version,
                executable=args.executable,
            )
        elif args.command == "seed-managed-gate-owner":
            _seed_managed_gate_owner(args.project)
        elif args.command == "close-managed-gate-owner":
            _close_managed_gate_owner(args.project)
        elif args.command == "verify":
            _verify(args.root)
        elif args.command == "hook":
            return _hook(args.provider, args.event, args.log)
        elif args.command == "guard-proxy":
            return _guard_proxy(
                args.provider,
                args.handler_id,
                args.handler,
                args.handler_sha256,
                args.project,
                args.log,
            )
        elif args.command == "stop-proxy":
            return _stop_proxy(
                args.provider,
                args.handler_id,
                args.handler,
                args.handler_sha256,
                args.project,
                args.log,
            )
        else:  # pragma: no cover - argparse owns this boundary
            raise SmokeError(f"unknown command: {args.command}")
    except SmokeError as exc:
        print(f"protected-host-smoke: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
