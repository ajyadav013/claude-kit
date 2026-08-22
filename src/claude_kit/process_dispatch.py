"""Concrete bounded subprocess adapters for Claude Code and Codex.

The adapters deliberately keep provider wire syntax out of the neutral dispatch
contract. A host process is started with an argv sequence (never a shell), receives
bounded input on stdin, and is given a hard lifetime. Claude uses the documented
stream-JSON protocol for active corrections. Codex defaults to the isolated one-shot
``exec`` path and exposes a separately selected, passive-only app-server backend.
Tests inject the small ``ProcessBackend`` protocol, so no credentialed host is
contacted by unit tests.
"""

from __future__ import annotations

import hashlib
import json
import os
import queue
import re
import signal
import stat
import subprocess
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from pathlib import Path
from typing import (
    IO,
    Any,
    Callable,
    Mapping,
    Optional,
    Protocol,
    Sequence,
)

import yaml

try:  # pragma: no cover - exercised only on Python 3.9/3.10
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

from claude_kit.components import (
    Capability,
    IsolationRequirement,
    ModelTier,
    NestedDelegationPolicy,
    PermissionClass,
    SymbolicRef,
)
from claude_kit.dispatch import (
    DispatchHandle,
    DispatchMessage,
    DispatchRequest,
    DispatchResult,
    DispatchStatus,
    HumanStopReason,
    HumanStopRequest,
    WaitMode,
    WaitResult,
    public_human_stop_text,
)
from claude_kit.projection import Provider
from claude_kit.secure_fs import ProjectFS
from claude_kit.state import detect_state_layout

_ROLE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_PERMISSION_RE = re.compile(r"^- Permission class: `([^`]+)`$", re.MULTILINE)
_CAPABILITIES_RE = re.compile(r"^- Capabilities: (.+)$", re.MULTILINE)
_WRITE_SCOPE_RE = re.compile(r"^- Write scope: (.+)$", re.MULTILINE)
_ISOLATION_RE = re.compile(r"^- Isolation: `([^`]+)`$", re.MULTILINE)
_NESTED_DELEGATION_RE = re.compile(r"^- Nested delegation: `([^`]+)`$", re.MULTILINE)
_MODEL_TIER_RE = re.compile(r"^- Model tier: `([^`]+)`$", re.MULTILINE)
_MAX_PROMPT_BYTES = 1_048_576
_MAX_OUTPUT_BYTES = 1_048_576
_MAX_DISPATCH_MESSAGES = 64
_MAX_DISPATCH_MESSAGE_BYTES = 1_048_576
_MAX_CLAUDE_STREAM_QUEUE_ITEMS = _MAX_DISPATCH_MESSAGES + 2
_CLAUDE_INTERRUPT_REQUEST_PREFIX = "ckit-interrupt-"
_MAX_CODEX_APP_SERVER_QUEUE_ITEMS = _MAX_DISPATCH_MESSAGES + 8
_MAX_CODEX_APP_SERVER_EVENTS = 4_096
_MAX_CODEX_AUTH_BYTES = 1_048_576
_CODEX_APP_SERVER_REMOTE_CONTROL_DISABLED_ENV = (
    "CODEX_INTERNAL_APP_SERVER_REMOTE_CONTROL_DISABLED"
)
_MAX_CODEX_SNAPSHOT_BYTES = 524_288
_MAX_CODEX_SNAPSHOT_FILE_BYTES = 131_072
_MAX_CODEX_SNAPSHOT_FILES = 512
_MAX_CODEX_SNAPSHOT_PATH_BYTES = 4_096
_MAX_CODEX_SNAPSHOT_METADATA_BYTES = 1_048_576
_CODEX_LOCKDOWN_VERSIONS = frozenset({"0.147.0", "0.149.0"})
_CODEX_LOCKDOWN_FEATURES = (
    "apps",
    "auth_elicitation",
    "browser_use",
    "browser_use_external",
    "browser_use_full_cdp_access",
    "code_mode",
    "code_mode_buffered_exec",
    "code_mode_host",
    "code_mode_only",
    "computer_use",
    "deferred_executor",
    "enable_mcp_apps",
    "goals",
    "hooks",
    "image_generation",
    "in_app_browser",
    "js_repl",
    "memories",
    "multi_agent",
    "multi_agent_v2",
    "network_proxy",
    "plugins",
    "plugin_sharing",
    "recommended_plugins",
    "remote_plugin",
    "request_permissions_tool",
    "search_tool",
    "shell_snapshot",
    "shell_tool",
    "skill_mcp_dependency_install",
    "skill_search",
    "tool_call_mcp_elicitation",
    "tool_suggest",
    "unified_exec",
    "view_image",
    "workspace_dependencies",
)
_CODEX_APP_SERVER_CONFIG_OVERRIDES = (
    'approval_policy="never"',
    'sandbox_mode="read-only"',
    "sandbox_workspace_write.network_access=false",
    "sandbox_workspace_write.exclude_slash_tmp=true",
    "sandbox_workspace_write.exclude_tmpdir_env_var=true",
    'shell_environment_policy.inherit="core"',
    "shell_environment_policy.ignore_default_excludes=false",
    "shell_environment_policy.experimental_use_profile=false",
    "agents.enabled=false",
    "hooks={}",
    "mcp_servers={}",
    'web_search="disabled"',
    "tools.web_search=false",
    "check_for_update_on_startup=false",
    "feedback.enabled=false",
    'history.persistence="none"',
    "project_doc_max_bytes=0",
    "project_doc_fallback_filenames=[]",
    'cli_auth_credentials_store="file"',
    'mcp_oauth_credentials_store="file"',
    "analytics.enabled=false",
)
_CODEX_APP_SERVER_SCHEMA_HASHES = {
    "ThreadStartParams.json": (
        "792e2f32e37cece971bd616664ea2053741acbed4e9c92e9d1766427718f2ecd"
    ),
    "TurnStartParams.json": (
        "ff2e7e0796fbe2ad99e5ec7d489cc8c8630b75f2ab8f17857711107587e3197d"
    ),
    "TurnSteerParams.json": (
        "4a52eb76e7a717bb388484ccd7538737fca0df35481fc30a21e259f1bfe96e37"
    ),
    "TurnInterruptParams.json": (
        "6dff382dae73d1dbc58406ed045605f647e7a49660e2540fbd2c6c24d60c5f2b"
    ),
}
_CODEX_SNAPSHOT_CONTROL_ROOTS = frozenset(
    {".agents", ".ckit", ".claude", ".codex", ".git"}
)
_CODEX_SNAPSHOT_GENERATED_COMPONENTS = frozenset(
    {
        ".cache",
        ".mypy_cache",
        ".next",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "__pycache__",
        "coverage",
        "dist",
        "node_modules",
        "target",
        "venv",
    }
)
_CODEX_SNAPSHOT_SENSITIVE_COMPONENTS = frozenset(
    {
        ".aws",
        ".azure",
        ".gcloud",
        ".gnupg",
        ".kube",
        ".ssh",
        "credential",
        "credentials",
        "private",
        "secret",
        "secrets",
        "vault",
    }
)
_CODEX_SNAPSHOT_SENSITIVE_NAME_RE = re.compile(
    r"(?:^|[._-])(?:auth|credential|password|private[-_]?key|secret|token)s?"
    r"(?:$|[._-])|^\.env(?:$|\.)|^(?:id_rsa|id_ed25519)(?:\.|$)|"
    r"^(?:\.git-credentials|\.netrc|\.npmrc|\.pypirc)$|"
    r"\.(?:jks|key|kdbx|p12|pem|pfx)$",
    re.IGNORECASE,
)
_CODEX_SNAPSHOT_TEXT_SUFFIXES = frozenset(
    {
        ".astro",
        ".bash",
        ".c",
        ".cc",
        ".cfg",
        ".conf",
        ".cpp",
        ".cs",
        ".css",
        ".fish",
        ".go",
        ".gql",
        ".gradle",
        ".graphql",
        ".h",
        ".hcl",
        ".hh",
        ".hpp",
        ".htm",
        ".html",
        ".ini",
        ".java",
        ".js",
        ".json",
        ".jsonc",
        ".jsx",
        ".kt",
        ".kts",
        ".less",
        ".lock",
        ".lua",
        ".md",
        ".mdx",
        ".mjs",
        ".mts",
        ".php",
        ".properties",
        ".proto",
        ".ps1",
        ".py",
        ".pyi",
        ".rb",
        ".rego",
        ".rs",
        ".rst",
        ".sass",
        ".scala",
        ".scss",
        ".sh",
        ".sql",
        ".svelte",
        ".swift",
        ".tf",
        ".toml",
        ".ts",
        ".tsx",
        ".txt",
        ".vue",
        ".xml",
        ".yaml",
        ".yml",
        ".zsh",
    }
)
_CODEX_SNAPSHOT_TEXT_NAMES = frozenset(
    {
        ".dockerignore",
        ".editorconfig",
        ".gitignore",
        ".prettierignore",
        "brewfile",
        "build",
        "changelog",
        "codeowners",
        "dockerfile",
        "gemfile",
        "justfile",
        "license",
        "makefile",
        "procfile",
        "rakefile",
        "readme",
        "workspace",
    }
)
_CODEX_SNAPSHOT_SECRET_VALUE_RE = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b|"
    r"\bsk_(?:live|test)_[0-9A-Za-z]{16,}\b|"
    r"\bxox[baprs]-[0-9A-Za-z-]{10,}\b|"
    r"\bgh[opsu]_[0-9A-Za-z]{30,}\b"
)
_CODEX_SNAPSHOT_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?im)(\b(?:[a-z0-9]+[_-])*(?:api[_-]?key|auth[_-]?token|"
    r"client[_-]?secret|credentials?|password|passwd|private[_-]?key|"
    r"secret|token)(?:[_-][a-z0-9]+)*\b\s*[:=]\s*[\"']?)"
    r"([^\s,;\"']{8,})"
)
# A loop transition token authorizes only the directly invoked controlling
# host process. Managed stage workers are nested children and must never
# inherit that authority.
_HEADLESS_TRANSITION_TOKEN_ENV = "CKIT_PIPELINE_TRANSITION_TOKEN"
_OUTER_HOST_IDENTITY_ENV = frozenset(
    {
        "CLAUDECODE",
        "CLAUDE_CODE_AUTO_CONNECT_IDE",
        "CLAUDE_CODE_ENTRYPOINT",
        "CODEX_INTERNAL_ORIGINATOR_OVERRIDE",
        "CODEX_PERMISSION_PROFILE",
    }
)
_MANAGED_CONTROL_PLANE_PATTERNS = (
    "AGENTS.md",
    "CLAUDE.md",
    ".agents/**",
    ".claude/**",
    ".codex/**",
    ".ckit/**",
    ".mcp.json",
)
_COMMON_CHILD_ENV = frozenset(
    {
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "SHELL",
        "TMPDIR",
        "TEMP",
        "TMP",
        "LANG",
        "TERM",
        "COLORTERM",
        "NO_COLOR",
        "CI",
        "VIRTUAL_ENV",
        "PYTHONPATH",
        "JAVA_HOME",
        "GOPATH",
        "GOROOT",
        "CARGO_HOME",
        "RUSTUP_HOME",
        "NVM_DIR",
        "PNPM_HOME",
        "UV_CACHE_DIR",
        "XDG_CONFIG_HOME",
        "XDG_CACHE_HOME",
        "XDG_DATA_HOME",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "REQUESTS_CA_BUNDLE",
        "CURL_CA_BUNDLE",
    }
)


def _nested_host_environment(source: Mapping[str, str]) -> dict[str, str]:
    """Preserve credentials/config while dropping outer-host session and IPC identity."""
    environment: dict[str, str] = {}
    for name, value in source.items():
        upper = name.upper()
        outer_session_marker = (
            upper.startswith("CLAUDE_CODE_")
            and any(
                marker in upper
                for marker in ("SESSION", "CHILD", "PARENT", "MESSAGING_SOCKET", "PID")
            )
        ) or (
            upper.startswith("CODEX_")
            and any(
                marker in upper
                for marker in ("SESSION", "THREAD", "SOCKET", "PID", "SANDBOX")
            )
        )
        if (
            name == _HEADLESS_TRANSITION_TOKEN_ENV
            or name in _OUTER_HOST_IDENTITY_ENV
            or outer_session_marker
        ):
            continue
        environment[name] = value
    return environment


class DispatchAdapterError(RuntimeError):
    """Base class for process-backed dispatch failures."""


class RoleUnavailableError(DispatchAdapterError):
    """Raised when a selected native role definition is not installed."""


class UnsupportedCapabilityError(DispatchAdapterError):
    """Raised before execution when a role's required capability is unavailable."""

    def __init__(self, role: str, missing: Sequence[Capability]) -> None:
        self.role = role
        self.missing = tuple(sorted(set(missing), key=lambda item: item.value))
        values = ", ".join(item.value for item in self.missing)
        super().__init__(f"role {role!r} requires unsupported capabilities: {values}")


@dataclass(frozen=True)
class NativeRoleDefinition:
    """Instructions and semantic controls loaded from an installed native role."""

    id: str
    description: str
    instructions: str
    permission: PermissionClass
    capabilities: frozenset[Capability]
    write_scope: tuple[str, ...] = ()
    isolation: IsolationRequirement = IsolationRequirement.NONE
    nested_delegation: NestedDelegationPolicy = NestedDelegationPolicy.FORBIDDEN
    model_tier: ModelTier = ModelTier.BALANCED
    native_tools: tuple[str, ...] = ()
    native_model: Optional[str] = None
    mcp_server_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not _ROLE_ID_RE.fullmatch(self.id) or ".." in self.id:
            raise ValueError("native role id must be a contained identifier")
        if not self.description.strip() or not self.instructions.strip():
            raise ValueError(
                "native role description and instructions must be non-empty"
            )
        permission = (
            self.permission
            if isinstance(self.permission, PermissionClass)
            else PermissionClass(self.permission)
        )
        capabilities = frozenset(
            value if isinstance(value, Capability) else Capability(value)
            for value in self.capabilities
        )
        if (
            permission is PermissionClass.READ_ONLY
            and Capability.FILE_WRITE in capabilities
        ):
            raise ValueError("read-only native roles cannot attest filesystem.write")
        if (
            Capability.EXTERNAL_MUTATION in capabilities
            and permission is not PermissionClass.EXTERNAL_EFFECT
        ):
            raise ValueError(
                "external.mutation requires the external_effect permission class"
            )
        if (
            permission is PermissionClass.EXTERNAL_EFFECT
            and Capability.EXTERNAL_MUTATION not in capabilities
        ):
            raise ValueError(
                "external_effect native roles must preserve external.mutation"
            )
        write_scope = tuple(self.write_scope)
        if any(
            not isinstance(scope, str)
            or not scope
            or scope.startswith(("/", "\\"))
            or ".." in scope.split("/")
            for scope in write_scope
        ):
            raise ValueError("native role write scope must be project-relative")
        if permission is PermissionClass.READ_ONLY and write_scope:
            raise ValueError("read-only native roles cannot declare write scope")
        try:
            isolation = (
                self.isolation
                if isinstance(self.isolation, IsolationRequirement)
                else IsolationRequirement(self.isolation)
            )
        except ValueError as exc:
            raise ValueError("native role has unknown isolation requirement") from exc
        try:
            nested_delegation = (
                self.nested_delegation
                if isinstance(self.nested_delegation, NestedDelegationPolicy)
                else NestedDelegationPolicy(self.nested_delegation)
            )
        except ValueError as exc:
            raise ValueError(
                "native role has unknown nested delegation policy"
            ) from exc
        if (
            nested_delegation is not NestedDelegationPolicy.FORBIDDEN
            and Capability.DELEGATE not in capabilities
        ):
            raise ValueError("native role delegation policy requires delegation")
        try:
            model_tier = (
                self.model_tier
                if isinstance(self.model_tier, ModelTier)
                else ModelTier(self.model_tier)
            )
        except ValueError as exc:
            raise ValueError("native role has unknown model tier") from exc
        native_tools = tuple(self.native_tools)
        if any(
            not isinstance(tool, str) or not tool.strip() for tool in native_tools
        ) or len(set(native_tools)) != len(native_tools):
            raise ValueError("native role tools must be unique non-empty strings")
        native_model = self.native_model
        if native_model is not None and (
            not isinstance(native_model, str) or not native_model.strip()
        ):
            raise ValueError("native role model must be a non-empty string when set")
        mcp_server_ids = tuple(self.mcp_server_ids)
        if any(
            not isinstance(server_id, str)
            or not _ROLE_ID_RE.fullmatch(server_id)
            or ".." in server_id
            for server_id in mcp_server_ids
        ) or len(set(mcp_server_ids)) != len(mcp_server_ids):
            raise ValueError("native role MCP server ids must be unique identifiers")
        object.__setattr__(self, "permission", permission)
        object.__setattr__(self, "capabilities", capabilities)
        object.__setattr__(self, "write_scope", write_scope)
        object.__setattr__(self, "isolation", isolation)
        object.__setattr__(self, "nested_delegation", nested_delegation)
        object.__setattr__(self, "model_tier", model_tier)
        object.__setattr__(self, "native_tools", native_tools)
        object.__setattr__(self, "native_model", native_model)
        object.__setattr__(self, "mcp_server_ids", mcp_server_ids)


class NativeRoleLoader(Protocol):
    """Load one generated native role definition."""

    def load(self, provider: Provider, role: str) -> NativeRoleDefinition:
        """Return a validated role or raise :class:`RoleUnavailableError`."""
        ...


def _contained_role_file(root: Path, relative: Path) -> Path:
    candidate = root / relative
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise RoleUnavailableError(
            f"native role is missing or unsafe: {relative}"
        ) from exc
    if not resolved.is_file():
        raise RoleUnavailableError(f"native role is not a file: {relative}")
    return resolved


def _frontmatter(path: Path) -> tuple[dict[str, object], str]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise RoleUnavailableError(f"Claude role has no frontmatter: {path}")
    end = next(
        (index for index, line in enumerate(lines[1:], 1) if line.strip() == "---"),
        None,
    )
    if end is None:
        raise RoleUnavailableError(f"Claude role has unterminated frontmatter: {path}")
    raw = yaml.safe_load("".join(lines[1:end]))
    if not isinstance(raw, dict):
        raise RoleUnavailableError(f"Claude role frontmatter is not an object: {path}")
    body = "".join(lines[end + 1 :]).strip()
    return raw, body


def _native_tool_names(tools: object) -> tuple[str, ...]:
    if isinstance(tools, str):
        values = tuple(item.strip() for item in tools.split(",") if item.strip())
    elif isinstance(tools, (list, tuple)):
        values = tuple(str(item).strip() for item in tools if str(item).strip())
    else:
        values = ()
    return tuple(dict.fromkeys(values))


def _claude_capabilities(tools: object) -> frozenset[Capability]:
    values = set(_native_tool_names(tools))
    capabilities: set[Capability] = set()
    if "Read" in values:
        capabilities.add(Capability.FILE_READ)
    if values & {"Write", "Edit"}:
        capabilities.add(Capability.FILE_WRITE)
    if values & {"Glob", "Grep"}:
        capabilities.add(Capability.SEARCH)
    if "Bash" in values:
        capabilities.add(Capability.SHELL)
    if "Agent" in values:
        capabilities.add(Capability.DELEGATE)
    if "SendMessage" in values:
        capabilities.add(Capability.MESSAGE)
    if values & {"TaskCreate", "TaskGet", "TaskList", "TaskUpdate"}:
        capabilities.add(Capability.TASK_LEDGER)
    if "AskUserQuestion" in values:
        capabilities.add(Capability.USER_INPUT)
    if any(value.startswith("mcp__") for value in values):
        capabilities.add(Capability.MCP)
    if any("chrome" in value.lower() or "browser" in value.lower() for value in values):
        capabilities.add(Capability.BROWSER)
    return frozenset(capabilities)


def _semantic_permission(instructions: str) -> PermissionClass:
    match = _PERMISSION_RE.search(instructions)
    if match is None:
        raise RoleUnavailableError("native role has no semantic permission")
    try:
        return PermissionClass(match.group(1))
    except ValueError as exc:
        raise RoleUnavailableError(
            "native role has unknown semantic permission"
        ) from exc


def _semantic_capabilities(instructions: str) -> frozenset[Capability]:
    match = _CAPABILITIES_RE.search(instructions)
    if match is None or match.group(1).strip() == "none":
        if match is None:
            raise RoleUnavailableError("native role has no semantic capabilities")
        return frozenset()
    try:
        return frozenset(
            Capability(value.strip())
            for value in match.group(1).split(",")
            if value.strip()
        )
    except ValueError as exc:
        raise RoleUnavailableError(
            "native role declares an unknown capability"
        ) from exc


def _semantic_write_scope(instructions: str) -> tuple[str, ...]:
    match = _WRITE_SCOPE_RE.search(instructions)
    if match is None:
        raise RoleUnavailableError("native role has no semantic write scope")
    rendered = match.group(1).strip()
    if rendered == "none":
        return ()
    values = tuple(value.strip() for value in re.findall(r"`([^`]+)`", rendered))
    if not values:
        raise RoleUnavailableError("native role has malformed semantic write scope")
    return values


def _semantic_isolation(instructions: str) -> IsolationRequirement:
    match = _ISOLATION_RE.search(instructions)
    if match is None:
        raise RoleUnavailableError("native role has no semantic isolation requirement")
    try:
        return IsolationRequirement(match.group(1))
    except ValueError as exc:
        raise RoleUnavailableError(
            "native role has unknown semantic isolation"
        ) from exc


def _semantic_nested_delegation(instructions: str) -> NestedDelegationPolicy:
    match = _NESTED_DELEGATION_RE.search(instructions)
    if match is None:
        raise RoleUnavailableError("native role has no nested delegation policy")
    try:
        return NestedDelegationPolicy(match.group(1))
    except ValueError as exc:
        raise RoleUnavailableError(
            "native role has unknown nested delegation policy"
        ) from exc


def _semantic_model_tier(instructions: str) -> ModelTier:
    match = _MODEL_TIER_RE.search(instructions)
    if match is None:
        raise RoleUnavailableError("native role has no semantic model tier")
    try:
        return ModelTier(match.group(1))
    except ValueError as exc:
        raise RoleUnavailableError("native role has unknown model tier") from exc


class FilesystemNativeRoleLoader:
    """Load role definitions emitted into an initialized project."""

    def __init__(self, project_root: Path) -> None:
        self.root = Path(project_root).resolve(strict=True)

    def load(self, provider: Provider, role: str) -> NativeRoleDefinition:
        if not _ROLE_ID_RE.fullmatch(role) or ".." in role:
            raise RoleUnavailableError(f"invalid native role id: {role!r}")
        if provider is Provider.CLAUDE:
            return self._load_claude(role)
        return self._load_codex(role)

    def _codex_mcp_server_ids(self) -> tuple[str, ...]:
        """Return the selected project MCP ids without consulting user config."""
        candidate = self.root / ".codex" / "config.toml"
        if not candidate.exists():
            return ()
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(self.root)
            document = tomllib.loads(resolved.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RoleUnavailableError(
                "Codex project config is invalid or unsafe"
            ) from exc
        servers = document.get("mcp_servers", {})
        if not isinstance(servers, dict):
            raise RoleUnavailableError("Codex project MCP config is not a table")
        ids = tuple(sorted(str(server_id) for server_id in servers))
        if any(not _ROLE_ID_RE.fullmatch(server_id) for server_id in ids):
            raise RoleUnavailableError("Codex project MCP id is not a safe identifier")
        return ids

    def _load_claude(self, role: str) -> NativeRoleDefinition:
        candidates = (
            Path(".claude/agents") / f"{role}.md",
            Path("agents") / f"{role}.md",
        )
        path: Optional[Path] = None
        for relative in candidates:
            try:
                path = _contained_role_file(self.root, relative)
                break
            except RoleUnavailableError:
                continue
        if path is None:
            raise RoleUnavailableError(f"Claude role is not installed: {role}")
        metadata, instructions = _frontmatter(path)
        if str(metadata.get("name", role)) != role:
            raise RoleUnavailableError(f"Claude role name does not match {role!r}")
        mode = str(metadata.get("permissionMode", "plan"))
        native_tools = _native_tool_names(metadata.get("tools"))
        native_capabilities = _claude_capabilities(native_tools)
        if _PERMISSION_RE.search(instructions) is not None:
            permission = _semantic_permission(instructions)
            capabilities = _semantic_capabilities(instructions)
            write_scope = _semantic_write_scope(instructions)
            isolation = _semantic_isolation(instructions)
            nested_delegation = _semantic_nested_delegation(instructions)
            model_tier = _semantic_model_tier(instructions)
            expected_mode = (
                "plan" if permission is PermissionClass.READ_ONLY else "acceptEdits"
            )
            if mode != expected_mode:
                raise RoleUnavailableError(
                    "Claude role permissionMode contradicts its semantic contract"
                )
            expected_isolation = isolation is not IsolationRequirement.NONE
            if (metadata.get("isolation") == "worktree") != expected_isolation:
                raise RoleUnavailableError(
                    "Claude role isolation contradicts its semantic contract"
                )
            native_semantics = capabilities - {Capability.EXTERNAL_MUTATION}
            if native_capabilities != native_semantics:
                missing = sorted(
                    capability.value
                    for capability in native_semantics - native_capabilities
                )
                extra = sorted(
                    capability.value
                    for capability in native_capabilities - native_semantics
                )
                raise RoleUnavailableError(
                    "Claude role tools contradict semantic capabilities "
                    f"(missing={missing}, extra={extra})"
                )
        else:
            # Compatibility path for pre-canonical Claude installations.  It
            # deliberately cannot infer external effects or nuanced isolation.
            permission = (
                PermissionClass.READ_ONLY
                if mode == "plan"
                else PermissionClass.WORKSPACE_WRITE
            )
            capabilities = native_capabilities
            raw_isolation = metadata.get("isolation")
            isolation = (
                IsolationRequirement.REQUIRED
                if raw_isolation == "worktree"
                else IsolationRequirement.NONE
            )
            raw_scope = metadata.get("writeScope", metadata.get("write_scope"))
            if isinstance(raw_scope, str):
                write_scope = tuple(
                    item.strip() for item in raw_scope.split(",") if item.strip()
                )
            elif isinstance(raw_scope, list):
                write_scope = tuple(str(item).strip() for item in raw_scope)
            elif permission is PermissionClass.WORKSPACE_WRITE:
                write_scope = ("**",)
            else:
                write_scope = ()
            nested_delegation = (
                NestedDelegationPolicy.ALLOWED
                if Capability.DELEGATE in capabilities
                else NestedDelegationPolicy.FORBIDDEN
            )
            model_tier = ModelTier.BALANCED
        return NativeRoleDefinition(
            id=role,
            description=str(metadata.get("description", "")).strip(),
            instructions=instructions,
            permission=permission,
            capabilities=capabilities,
            write_scope=write_scope,
            isolation=isolation,
            nested_delegation=nested_delegation,
            model_tier=model_tier,
            native_tools=native_tools,
            native_model=(
                str(metadata["model"]).strip() if metadata.get("model") else None
            ),
        )

    def _load_codex(self, role: str) -> NativeRoleDefinition:
        path = _contained_role_file(self.root, Path(".codex/agents") / f"{role}.toml")
        try:
            document = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RoleUnavailableError(
                f"invalid Codex role definition: {path}"
            ) from exc
        if document.get("name") != role:
            raise RoleUnavailableError(f"Codex role name does not match {role!r}")
        instructions = str(document.get("developer_instructions", ""))
        permission = _semantic_permission(instructions)
        capabilities = _semantic_capabilities(instructions)
        nested_delegation = _semantic_nested_delegation(instructions)
        expected_sandbox = (
            "read-only"
            if permission is PermissionClass.READ_ONLY
            else "workspace-write"
        )
        configured_sandbox = document.get("sandbox_mode")
        if configured_sandbox is not None and configured_sandbox != expected_sandbox:
            raise RoleUnavailableError(
                "Codex role sandbox contradicts its semantic permission"
            )
        agents_config = document.get("agents")
        if isinstance(agents_config, dict) and isinstance(
            agents_config.get("enabled"), bool
        ):
            enabled = bool(agents_config["enabled"])
            expected = nested_delegation is not NestedDelegationPolicy.FORBIDDEN
            if enabled != expected:
                raise RoleUnavailableError(
                    "Codex role subagent setting contradicts nested delegation"
                )
        return NativeRoleDefinition(
            id=role,
            description=str(document.get("description", "")).strip(),
            instructions=instructions,
            permission=permission,
            capabilities=capabilities,
            write_scope=_semantic_write_scope(instructions),
            isolation=_semantic_isolation(instructions),
            nested_delegation=nested_delegation,
            model_tier=_semantic_model_tier(instructions),
            mcp_server_ids=self._codex_mcp_server_ids(),
        )


@dataclass(frozen=True)
class ProcessOutcome:
    """Completed process output returned by an injectable backend."""

    returncode: int
    stdout: str = ""
    stderr: str = ""
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    stdout_byte_count: Optional[int] = None
    stderr_byte_count: Optional[int] = None

    def __post_init__(self) -> None:
        stdout_count = (
            len(self.stdout.encode("utf-8"))
            if self.stdout_byte_count is None
            else self.stdout_byte_count
        )
        stderr_count = (
            len(self.stderr.encode("utf-8"))
            if self.stderr_byte_count is None
            else self.stderr_byte_count
        )
        if (
            not isinstance(stdout_count, int)
            or isinstance(stdout_count, bool)
            or stdout_count < 0
            or not isinstance(stderr_count, int)
            or isinstance(stderr_count, bool)
            or stderr_count < 0
        ):
            raise ValueError("process output byte counts must be non-negative integers")
        object.__setattr__(self, "stdout_byte_count", stdout_count)
        object.__setattr__(self, "stderr_byte_count", stderr_count)


class ProcessBackend(Protocol):
    """Minimal asynchronous process seam used by both host adapters."""

    descendant_containment: bool
    """Whether this backend contains every descendant until terminal collection."""

    def start(
        self, argv: Sequence[str], *, cwd: Path, env: Mapping[str, str]
    ) -> object:
        """Start a process that is waiting for prompt input."""
        ...

    def submit(self, process: object, prompt: str) -> None:
        """Write the complete prompt to stdin and close it."""
        ...

    def poll(self, process: object) -> Optional[ProcessOutcome]:
        """Return terminal output, or ``None`` while the process is active."""
        ...

    def terminate(self, process: object) -> ProcessOutcome:
        """Terminate exactly this process and return its final output."""
        ...


class ActiveMessageProcessBackend(Protocol):
    """Optional native-session extension for mid-dispatch corrections.

    The ordinary one-shot subprocess backend closes stdin after the initial
    prompt and deliberately does not implement this protocol. Streaming Claude
    sessions and Codex app-server turns can implement it without leaking their
    provider wire types into :class:`~claude_kit.dispatch.Dispatcher`.
    """

    def message(self, process: object, message: DispatchMessage) -> None:
        """Deliver one bounded neutral message to the active native session."""
        ...


class CodexLockdownProbe(Protocol):
    """Attest the exact pinned CLI and disabled execution feature set."""

    def __call__(
        self,
        executable: str,
        workspace: Path,
        environment: Mapping[str, str],
        disabled_features: Sequence[str],
    ) -> bool:
        """Return true only when this invocation's native lockdown is supported."""
        ...


class CodexMcpIsolationProbe(Protocol):
    """Attest that an isolated pinned Codex invocation resolves no MCP server."""

    def __call__(
        self,
        executable: str,
        workspace: Path,
        environment: Mapping[str, str],
        disabled_features: Sequence[str],
    ) -> bool:
        """Return true only when the effective MCP server list is empty."""
        ...


def _probe_codex_lockdown(
    executable: str,
    workspace: Path,
    environment: Mapping[str, str],
    disabled_features: Sequence[str],
) -> bool:
    """Fail-closed probe for the two compatibility-pinned Codex CLIs.

    ``features list`` is a local, non-credentialed command. Passing every
    execution-surface override to it both proves that the exact host recognizes
    the names and exposes their effective states after managed configuration is
    applied. Any parse error, unknown flag, future version, or enabled feature
    keeps descendant containment mandatory.
    """
    try:
        version_result = subprocess.run(
            (executable, "--version"),
            cwd=workspace,
            env=dict(environment),
            check=False,
            capture_output=True,
            text=True,
            timeout=5.0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    version_match = re.fullmatch(
        r"codex-cli\s+([0-9]+\.[0-9]+\.[0-9]+)\s*", version_result.stdout
    )
    if (
        version_result.returncode != 0
        or version_match is None
        or version_match.group(1) not in _CODEX_LOCKDOWN_VERSIONS
    ):
        return False

    argv: list[str] = [executable, "features", "list"]
    for feature in disabled_features:
        argv.extend(("--disable", feature))
    try:
        features_result = subprocess.run(
            argv,
            cwd=workspace,
            env=dict(environment),
            check=False,
            capture_output=True,
            text=True,
            timeout=5.0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if features_result.returncode != 0:
        return False
    effective: dict[str, bool] = {}
    for line in features_result.stdout.splitlines():
        match = re.fullmatch(r"(\S+)\s+.+\s+(true|false)", line.strip())
        if match is not None:
            effective[match.group(1)] = match.group(2) == "true"
    return all(effective.get(feature) is False for feature in disabled_features)


def _probe_codex_no_mcp(
    executable: str,
    workspace: Path,
    environment: Mapping[str, str],
    disabled_features: Sequence[str],
) -> bool:
    """Fail closed unless the isolated host resolves an empty MCP server list.

    Codex config tables merge recursively, so an empty ``mcp_servers`` CLI
    table alone cannot erase a managed lower-layer server. The pinned CLI's
    local ``mcp list --json`` command lets this passive backend attest the
    effective list before a prompt or credential is sent to app-server.
    """
    argv: list[str] = [executable]
    for feature in disabled_features:
        argv.extend(("--disable", feature))
    argv.extend(("-c", "mcp_servers={}", "mcp", "list", "--json"))
    try:
        result = subprocess.run(
            argv,
            cwd=workspace,
            env=dict(environment),
            check=False,
            capture_output=True,
            text=True,
            timeout=5.0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if result.returncode != 0:
        return False
    try:
        document = json.loads(result.stdout)
    except json.JSONDecodeError:
        return False
    return document == []


@dataclass
class _BoundedCapture:
    """Continuously drain one pipe while retaining only a bounded prefix."""

    stream: IO[bytes]
    limit: int = _MAX_OUTPUT_BYTES
    buffer: bytearray = field(default_factory=bytearray)
    byte_count: int = 0
    truncated: bool = False
    _thread: Optional[threading.Thread] = field(default=None, init=False)
    _lock: threading.Lock = field(
        default_factory=threading.Lock, init=False, repr=False
    )

    def start(self) -> None:
        self._thread = threading.Thread(target=self._drain, daemon=True)
        self._thread.start()

    def _drain(self) -> None:
        try:
            # ``BufferedReader.read(n)`` may wait for all ``n`` bytes while a
            # long-lived JSONL host keeps stdout open. ``read1`` returns the
            # bytes currently available from the pipe, so polling can advance
            # protocol handshakes and active messages without waiting for EOF.
            reader = getattr(self.stream, "read1", self.stream.read)
            while True:
                chunk = reader(65_536)
                if not chunk:
                    return
                with self._lock:
                    self.byte_count += len(chunk)
                    remaining = self.limit - len(self.buffer)
                    if remaining > 0:
                        self.buffer.extend(chunk[:remaining])
                    if len(chunk) > remaining:
                        self.truncated = True
        except (OSError, ValueError):
            with self._lock:
                self.truncated = True
        finally:
            try:
                self.stream.close()
            except (OSError, ValueError):
                pass

    def finish(self) -> tuple[str, bool, int]:
        if self._thread is None:
            raise DispatchAdapterError("host output capture was not started")
        self._thread.join(timeout=2.0)
        if self._thread.is_alive():
            # The owned process group should have closed every inherited pipe.
            # Do not block the coordinator indefinitely if a hostile child did
            # not comply; the retained prefix remains bounded and is marked.
            with self._lock:
                self.truncated = True
            try:
                os.close(self.stream.fileno())
            except OSError:
                pass
            self._thread.join(timeout=0.1)
        with self._lock:
            return (
                bytes(self.buffer).decode("utf-8", errors="replace"),
                self.truncated,
                self.byte_count,
            )

    def snapshot(self) -> tuple[str, bool, int]:
        """Return a thread-safe prefix without waiting for the pipe to close."""
        with self._lock:
            return (
                bytes(self.buffer).decode("utf-8", errors="replace"),
                self.truncated,
                self.byte_count,
            )

    @property
    def closed(self) -> bool:
        return self.stream.closed


@dataclass
class _SubprocessToken:
    process: subprocess.Popen[bytes]
    stdout_capture: _BoundedCapture
    stderr_capture: _BoundedCapture
    submitted: bool = False
    prompt_thread: Optional[threading.Thread] = None
    prompt_error: Optional[str] = None
    outcome: Optional[ProcessOutcome] = None
    process_group_id: Optional[int] = None
    process_group_drained: bool = False
    process_group_error: Optional[str] = None
    termination_requested: bool = False
    termination_signal_sent: bool = False


class SubprocessBackend:
    """Real ``subprocess.Popen`` backend with no shell expansion."""

    # Portable process groups cannot contain a child that deliberately creates
    # a new session.  A platform-specific supervisor may implement the backend
    # protocol and set this true only when it owns a real containment boundary.
    descendant_containment = False

    @staticmethod
    def _cleanup_failed_start(process: subprocess.Popen[bytes]) -> None:
        """Best-effort terminalize a host created before start could return ownership."""

        owned_group = os.name == "posix" and process.pid != os.getpgrp()
        if owned_group:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except (PermissionError, ProcessLookupError):
                owned_group = False
        if not owned_group and process.poll() is None:
            try:
                process.terminate()
            except (OSError, ProcessLookupError):
                pass

        deadline = time.monotonic() + 0.25
        while owned_group and time.monotonic() < deadline:
            try:
                os.killpg(process.pid, 0)
            except (PermissionError, ProcessLookupError):
                owned_group = False
                break
            time.sleep(0.01)
        if owned_group:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (PermissionError, ProcessLookupError):
                pass
        if process.poll() is None:
            try:
                process.kill()
            except (OSError, ProcessLookupError):
                pass
        try:
            process.wait(timeout=1.0)
        except (OSError, subprocess.TimeoutExpired):
            pass
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                try:
                    stream.close()
                except (OSError, ValueError):
                    pass

    def start(
        self, argv: Sequence[str], *, cwd: Path, env: Mapping[str, str]
    ) -> object:
        if not argv or any("\x00" in value for value in argv):
            raise DispatchAdapterError("host argv is empty or contains NUL")
        try:
            process = subprocess.Popen(
                list(argv),
                cwd=str(cwd),
                env=dict(env),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                start_new_session=(os.name == "posix"),
            )
        except (OSError, ValueError) as exc:
            raise DispatchAdapterError(f"cannot start host process: {exc}") from exc
        try:
            if process.stdout is None or process.stderr is None:  # pragma: no cover
                raise DispatchAdapterError("host process has no output pipes")
            stdout_capture = _BoundedCapture(process.stdout)
            stderr_capture = _BoundedCapture(process.stderr)
            stdout_capture.start()
            stderr_capture.start()
            process_group_id: Optional[int] = None
            if os.name == "posix":
                try:
                    process_group_id = os.getpgid(process.pid)
                except ProcessLookupError:
                    process_group_id = process.pid
                if process_group_id != process.pid or process_group_id == os.getpgrp():
                    raise DispatchAdapterError(
                        "host process did not receive a uniquely owned process group"
                    )
            return _SubprocessToken(
                process,
                stdout_capture,
                stderr_capture,
                process_group_id=process_group_id,
            )
        except RuntimeError as exc:  # pragma: no cover - thread start exhaustion
            self._cleanup_failed_start(process)
            raise DispatchAdapterError(
                f"cannot start host output capture: {exc}"
            ) from exc
        except BaseException:
            self._cleanup_failed_start(process)
            raise

    @staticmethod
    def _token(process: object) -> _SubprocessToken:
        if not isinstance(process, _SubprocessToken):
            raise DispatchAdapterError("process token was not created by this backend")
        return process

    def submit(self, process: object, prompt: str) -> None:
        token = self._token(process)
        if token.submitted:
            raise DispatchAdapterError("host prompt was already submitted")
        if token.process.stdin is None:
            raise DispatchAdapterError("host process has no stdin")

        payload = prompt.encode("utf-8")

        def write_prompt() -> None:
            try:
                assert token.process.stdin is not None
                token.process.stdin.write(payload)
                token.process.stdin.close()
            except (BrokenPipeError, OSError, ValueError) as exc:
                token.prompt_error = str(exc)
                try:
                    assert token.process.stdin is not None
                    token.process.stdin.close()
                except (BrokenPipeError, OSError, ValueError):
                    pass

        writer = threading.Thread(target=write_prompt, daemon=True)
        try:
            writer.start()
        except RuntimeError as exc:  # pragma: no cover - thread start exhaustion
            raise DispatchAdapterError(
                f"cannot start host prompt submission: {exc}"
            ) from exc
        token.prompt_thread = writer
        token.submitted = True

    @staticmethod
    def _finish_prompt(token: _SubprocessToken) -> Optional[str]:
        """Join the stdin writer after the owned host process becomes terminal."""
        writer = token.prompt_thread
        if writer is None:
            if token.process.stdin is not None and not token.process.stdin.closed:
                try:
                    token.process.stdin.close()
                except (BrokenPipeError, OSError, ValueError):
                    pass
            return token.prompt_error
        writer.join(timeout=2.0)
        if writer.is_alive():
            # A terminal process should have closed the read side. Break a hostile inherited
            # descriptor without waiting indefinitely for BufferedWriter.close().
            if token.process.stdin is not None and not token.process.stdin.closed:
                try:
                    os.close(token.process.stdin.fileno())
                except (OSError, ValueError):
                    pass
            writer.join(timeout=0.1)
        if writer.is_alive():
            return "host prompt writer did not stop after process termination"
        return token.prompt_error

    @staticmethod
    def _drain_owned_process_group(token: _SubprocessToken) -> None:
        """Terminate descendants even when the native host leader exited normally."""
        if token.process_group_drained:
            return
        token.process_group_drained = True
        if os.name != "posix":  # pragma: no cover - Windows needs a Job Object
            return
        pgid = token.process_group_id
        if pgid is None or pgid != token.process.pid or pgid == os.getpgrp():
            raise DispatchAdapterError(
                "refusing to signal a process group not owned by this host process"
            )
        try:
            os.killpg(pgid, signal.SIGTERM)
            token.termination_signal_sent = True
        except ProcessLookupError:
            return
        except PermissionError:
            token.process_group_error = "owned host process group could not be drained"
            return
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline:
            try:
                os.killpg(pgid, 0)
            except ProcessLookupError:
                return
            except PermissionError:
                try:
                    os.killpg(pgid, signal.SIGKILL)
                    token.termination_signal_sent = True
                except PermissionError:
                    token.process_group_error = (
                        "owned host process group could not be drained"
                    )
                except ProcessLookupError:
                    pass
                return
            time.sleep(0.01)
        try:
            os.killpg(pgid, signal.SIGKILL)
            token.termination_signal_sent = True
        except PermissionError:
            token.process_group_error = "owned host process group could not be drained"
        except ProcessLookupError:
            pass

    def poll(self, process: object) -> Optional[ProcessOutcome]:
        token = self._token(process)
        if token.outcome is not None:
            return token.outcome
        returncode = token.process.poll()
        if returncode is None:
            return None
        self._drain_owned_process_group(token)
        prompt_error = self._finish_prompt(token)
        stdout, stdout_truncated, stdout_count = token.stdout_capture.finish()
        stderr, stderr_truncated, stderr_count = token.stderr_capture.finish()
        if token.process_group_error is not None:
            stderr = (
                f"{stderr.rstrip()}\nhost process descendant cleanup failed"
            ).lstrip()
            stderr_count = max(stderr_count, len(stderr.encode("utf-8")))
            if returncode == 0:
                returncode = 70
        if prompt_error:
            prompt_message = f"host prompt submission failed: {prompt_error}"
            stderr = f"{stderr.rstrip()}\n{prompt_message}".lstrip()
            if returncode == 0:
                returncode = 74
        token.outcome = ProcessOutcome(
            returncode,
            stdout,
            stderr,
            stdout_truncated,
            stderr_truncated,
            stdout_count,
            stderr_count,
        )
        return token.outcome

    def terminate(self, process: object) -> ProcessOutcome:
        token = self._token(process)
        existing = self.poll(token)
        if existing is not None:
            return existing
        token.termination_requested = True
        if os.name == "posix":
            self._drain_owned_process_group(token)
        else:  # pragma: no cover - exercised on Windows CI
            token.process.terminate()
            token.termination_signal_sent = True
        try:
            token.process.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            if os.name == "posix":
                try:
                    os.killpg(token.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:  # pragma: no cover - exercised on Windows CI
                token.process.kill()
            token.process.wait(timeout=1.0)
        outcome = self.poll(token)
        if outcome is None:  # pragma: no cover - Popen.wait made this terminal
            raise DispatchAdapterError("terminated host process did not exit")
        return outcome


@dataclass
class _ClaudeStreamToken:
    """Owned Claude stream-JSON session layered over a subprocess token."""

    subprocess: _SubprocessToken
    input_queue: queue.Queue[Optional[bytes]] = field(
        default_factory=lambda: queue.Queue(maxsize=_MAX_CLAUDE_STREAM_QUEUE_ITEMS)
    )
    writer: Optional[threading.Thread] = None
    submitted: bool = False
    input_closing: bool = False
    writer_error: Optional[str] = None
    protocol_error: Optional[str] = None
    result_event: Optional[Mapping[str, object]] = None
    active_message_count: int = 0
    active_message_bytes: int = 0
    next_control_request: int = 0
    interrupt_requests: set[str] = field(default_factory=set)
    acknowledged_interrupts: set[str] = field(default_factory=set)
    outcome: Optional[ProcessOutcome] = None
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


class ClaudeStreamJsonBackend:
    """Claude Code stream-JSON backend with bounded active-message delivery.

    Claude's documented streaming input keeps stdin open while one turn runs,
    allowing coordinator corrections to be delivered as additional user input.
    The provider event stream remains internal: only the terminal ``result``
    payload is returned to the provider-neutral dispatcher.
    """

    descendant_containment = False

    def __init__(self) -> None:
        self._subprocess = SubprocessBackend()

    @staticmethod
    def _token(process: object) -> _ClaudeStreamToken:
        if not isinstance(process, _ClaudeStreamToken):
            raise DispatchAdapterError(
                "process token was not created by the Claude stream backend"
            )
        return process

    @staticmethod
    def _user_event(content: str) -> bytes:
        # This is the exact streaming-input shape used by the official Agent
        # SDK and accepted by both compatibility-pinned Claude Code CLIs.
        document = {
            "type": "user",
            "message": {
                "role": "user",
                "content": content,
            },
            "parent_tool_use_id": None,
            "session_id": "default",
        }
        return ClaudeStreamJsonBackend._wire_event(document)

    @staticmethod
    def _wire_event(document: Mapping[str, object]) -> bytes:
        return (
            json.dumps(
                document,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")

    @staticmethod
    def _interrupt_event(request_id: str) -> bytes:
        return ClaudeStreamJsonBackend._wire_event(
            {
                "type": "control_request",
                "request_id": request_id,
                "request": {"subtype": "interrupt"},
            }
        )

    @staticmethod
    def _record_writer_error(token: _ClaudeStreamToken, message: str) -> None:
        with token.lock:
            if token.writer_error is None:
                token.writer_error = message

    @staticmethod
    def _enqueue_locked(token: _ClaudeStreamToken, payload: Optional[bytes]) -> None:
        """Queue one bounded frame while ``token.lock`` is held."""
        try:
            token.input_queue.put_nowait(payload)
        except queue.Full as exc:
            token.writer_error = "Claude stream input queue exceeded its bound"
            raise DispatchAdapterError(
                "Claude stream input queue exceeded its bound"
            ) from exc

    @staticmethod
    def _writer_loop(token: _ClaudeStreamToken) -> None:
        stdin = token.subprocess.process.stdin
        if stdin is None:  # pragma: no cover - SubprocessBackend guarantees this
            ClaudeStreamJsonBackend._record_writer_error(
                token, "host process has no stdin"
            )
            return
        try:
            while True:
                payload = token.input_queue.get()
                if payload is None:
                    stdin.close()
                    return
                stdin.write(payload)
                stdin.flush()
        except (BrokenPipeError, OSError, ValueError) as exc:
            ClaudeStreamJsonBackend._record_writer_error(token, str(exc))
            try:
                stdin.close()
            except (BrokenPipeError, OSError, ValueError):
                pass

    def start(
        self, argv: Sequence[str], *, cwd: Path, env: Mapping[str, str]
    ) -> object:
        base = self._subprocess.start(argv, cwd=cwd, env=env)
        if not isinstance(base, _SubprocessToken):  # pragma: no cover - internal seam
            raise DispatchAdapterError("Claude subprocess token has an invalid type")
        token = _ClaudeStreamToken(base)
        writer = threading.Thread(target=self._writer_loop, args=(token,), daemon=True)
        try:
            writer.start()
        except RuntimeError as exc:  # pragma: no cover - thread start exhaustion
            self._subprocess.terminate(base)
            raise DispatchAdapterError(
                f"cannot start Claude stream input writer: {exc}"
            ) from exc
        token.writer = writer
        return token

    def submit(self, process: object, prompt: str) -> None:
        token = self._token(process)
        if not isinstance(prompt, str):
            raise ValueError("prompt must be a string")
        if len(prompt.encode("utf-8")) > _MAX_PROMPT_BYTES:
            raise DispatchAdapterError(
                "Claude stream prompt exceeds the 1 MiB safety limit"
            )
        with token.lock:
            if token.submitted:
                raise DispatchAdapterError("host prompt was already submitted")
            if token.input_closing:
                raise DispatchAdapterError("Claude stream input is already closing")
            self._enqueue_locked(token, self._user_event(prompt))
            token.submitted = True

    def message(self, process: object, message: DispatchMessage) -> None:
        token = self._token(process)
        if not isinstance(message, DispatchMessage):
            raise ValueError("message must be a DispatchMessage")
        with token.lock:
            if not token.submitted:
                raise DispatchAdapterError(
                    "Claude stream requires the initial prompt before a message"
                )
            if token.input_closing or token.result_event is not None:
                raise DispatchAdapterError(
                    "Claude stream has already completed its turn"
                )
            if token.subprocess.process.poll() is not None:
                raise DispatchAdapterError("Claude stream process is already terminal")
            message_bytes = len(message.content.encode("utf-8"))
            if (
                token.active_message_count >= _MAX_DISPATCH_MESSAGES
                or token.active_message_bytes + message_bytes
                > _MAX_DISPATCH_MESSAGE_BYTES
            ):
                raise DispatchAdapterError(
                    "Claude stream message count or cumulative size exceeds "
                    "the safety limit"
                )
            correlation = (
                f" correlation_id={message.correlation_id}"
                if message.correlation_id is not None
                else ""
            )
            content = (
                f"Coordinator {message.kind.value}{correlation}:\n{message.content}"
            )
            payload = self._user_event(content)
            interrupt_request: Optional[str] = None
            if message.kind.value == "correction":
                token.next_control_request += 1
                interrupt_request = _CLAUDE_INTERRUPT_REQUEST_PREFIX + str(
                    token.next_control_request
                )
                # A second user frame alone is a queued follow-up. Corrections
                # first use Claude's native interrupt control request so they
                # can change an in-flight turn, then preserve the correction as
                # the next user frame on the same session.
                payload = self._interrupt_event(interrupt_request) + payload
            self._enqueue_locked(token, payload)
            token.active_message_count += 1
            token.active_message_bytes += message_bytes
            if interrupt_request is not None:
                token.interrupt_requests.add(interrupt_request)

    @staticmethod
    def _stream_events(
        text: str, *, final: bool
    ) -> tuple[Optional[Mapping[str, object]], frozenset[str], Optional[str]]:
        """Validate a captured NDJSON prefix and return its latest result.

        A live capture may end halfway through its last frame. Every complete
        line, and every line in terminal output, must be a typed JSON object.
        Raw protocol bytes never become the returned diagnostic.
        """
        result: Optional[Mapping[str, object]] = None
        acknowledged: set[str] = set()
        framed_lines = text.splitlines(keepends=True)
        for index, framed_line in enumerate(framed_lines):
            if (
                not final
                and index == len(framed_lines) - 1
                and not framed_line.endswith(("\n", "\r"))
            ):
                break
            line = framed_line.strip()
            if not line:
                continue
            try:
                document = json.loads(line)
            except json.JSONDecodeError:
                return (
                    result,
                    frozenset(acknowledged),
                    ("Claude stream emitted malformed NDJSON"),
                )
            if not isinstance(document, dict) or not isinstance(
                document.get("type"), str
            ):
                return (
                    result,
                    frozenset(acknowledged),
                    ("Claude stream emitted an untyped event"),
                )
            if document.get("type") == "control_response":
                response = document.get("response")
                if not isinstance(response, dict):
                    return (
                        result,
                        frozenset(acknowledged),
                        ("Claude stream emitted a malformed control response"),
                    )
                request_id = response.get("request_id")
                if isinstance(request_id, str) and request_id.startswith(
                    _CLAUDE_INTERRUPT_REQUEST_PREFIX
                ):
                    if response.get("subtype") != "success":
                        return (
                            result,
                            frozenset(acknowledged),
                            ("Claude rejected an active correction interrupt"),
                        )
                    acknowledged.add(request_id)
            if document.get("type") == "result":
                result = document
        return result, frozenset(acknowledged), None

    @classmethod
    def _observe_stream(
        cls, token: _ClaudeStreamToken, text: str, *, final: bool
    ) -> Optional[Mapping[str, object]]:
        result, acknowledged, problem = cls._stream_events(text, final=final)
        with token.lock:
            token.acknowledged_interrupts.update(acknowledged)
            if result is not None:
                token.result_event = result
            if problem is not None and token.protocol_error is None:
                token.protocol_error = problem
            if (
                final
                and token.protocol_error is None
                and not token.interrupt_requests.issubset(token.acknowledged_interrupts)
            ):
                token.protocol_error = (
                    "Claude stream ended before acknowledging an active correction"
                )
        return result

    @staticmethod
    def _close_input(token: _ClaudeStreamToken) -> None:
        with token.lock:
            if token.input_closing:
                return
            token.input_closing = True
            try:
                ClaudeStreamJsonBackend._enqueue_locked(token, None)
            except DispatchAdapterError:
                # The writer error forces process termination on the next poll;
                # terminal cleanup must not block trying to enqueue EOF.
                pass

    @staticmethod
    def _finish_writer(token: _ClaudeStreamToken) -> None:
        ClaudeStreamJsonBackend._close_input(token)
        writer = token.writer
        if writer is None:
            return
        writer.join(timeout=2.0)
        if writer.is_alive():
            stdin = token.subprocess.process.stdin
            if stdin is not None and not stdin.closed:
                try:
                    os.close(stdin.fileno())
                except (OSError, ValueError):
                    pass
            writer.join(timeout=0.1)
        if writer.is_alive():
            ClaudeStreamJsonBackend._record_writer_error(
                token, "Claude stream input writer did not stop"
            )

    @staticmethod
    def _translated(
        token: _ClaudeStreamToken, outcome: ProcessOutcome
    ) -> ProcessOutcome:
        # Always rescan terminal output. A poll can observe the first turn's
        # result just before a queued correction produces a later result; the
        # terminal event, not the cached prefix, is authoritative.
        event = ClaudeStreamJsonBackend._observe_stream(
            token, outcome.stdout, final=True
        )
        with token.lock:
            protocol_error = token.protocol_error
            cached_event = token.result_event
        if protocol_error is not None:
            return outcome
        event = event or cached_event
        if event is None or outcome.returncode != 0:
            return outcome
        result = event.get("result")
        if not isinstance(result, str):
            return outcome
        is_error = event.get("is_error") is True
        subtype = event.get("subtype")
        returncode = outcome.returncode
        if is_error or (isinstance(subtype, str) and subtype.endswith("error")):
            returncode = 70
        return ProcessOutcome(
            returncode,
            result,
            outcome.stderr,
            outcome.stdout_truncated,
            outcome.stderr_truncated,
            outcome.stdout_byte_count,
            outcome.stderr_byte_count,
        )

    @staticmethod
    def _stream_problem(
        token: _ClaudeStreamToken, outcome: ProcessOutcome
    ) -> ProcessOutcome:
        with token.lock:
            writer_error = token.writer_error
            protocol_error = token.protocol_error
        if writer_error is None and protocol_error is None:
            return outcome
        stderr = outcome.stderr.rstrip()
        diagnostics: list[str] = []
        if writer_error is not None:
            diagnostics.append("Claude stream input writer failed")
        if protocol_error is not None:
            diagnostics.append("Claude stream protocol validation failed")
        stderr = "\n".join((stderr, *diagnostics)).lstrip()
        failure_code = 74 if writer_error is not None else 65
        return ProcessOutcome(
            outcome.returncode if outcome.returncode != 0 else failure_code,
            outcome.stdout,
            stderr,
            outcome.stdout_truncated,
            outcome.stderr_truncated,
            outcome.stdout_byte_count,
            max(outcome.stderr_byte_count or 0, len(stderr.encode("utf-8"))),
        )

    def poll(self, process: object) -> Optional[ProcessOutcome]:
        token = self._token(process)
        if token.outcome is not None:
            return token.outcome
        stdout, truncated, _count = token.subprocess.stdout_capture.snapshot()
        event = self._observe_stream(token, stdout, final=False)
        if event is not None:
            self._close_input(token)
        elif truncated:
            self._close_input(token)
        outcome: Optional[ProcessOutcome]
        with token.lock:
            stream_failed = (
                token.writer_error is not None or token.protocol_error is not None
            )
        if stream_failed:
            self._close_input(token)
            outcome = self._subprocess.terminate(token.subprocess)
        else:
            outcome = self._subprocess.poll(token.subprocess)
        if outcome is None:
            return None
        self._finish_writer(token)
        token.outcome = self._stream_problem(token, self._translated(token, outcome))
        return token.outcome

    def terminate(self, process: object) -> ProcessOutcome:
        token = self._token(process)
        if token.outcome is not None:
            return token.outcome
        self._close_input(token)
        outcome = self._subprocess.terminate(token.subprocess)
        self._finish_writer(token)
        token.outcome = self._stream_problem(token, self._translated(token, outcome))
        return token.outcome


@dataclass
class _IsolatedCodexEnvironment:
    """Owned temporary Codex home and the environment bound to it."""

    temporary: Any
    root: Path
    environment: dict[str, str]
    cleaned: bool = False

    def cleanup(self) -> None:
        if self.cleaned:
            return
        self.temporary.cleanup()
        if os.path.lexists(self.root):
            raise DispatchAdapterError(
                "Codex app-server isolated credential home was not removed"
            )
        self.cleaned = True


@dataclass
class _CodexAppServerToken:
    """One isolated stable-v2 app-server connection and ephemeral turn."""

    subprocess: _SubprocessToken
    isolation: _IsolatedCodexEnvironment
    cwd: Path
    input_queue: queue.Queue[Optional[bytes]] = field(
        default_factory=lambda: queue.Queue(maxsize=_MAX_CODEX_APP_SERVER_QUEUE_ITEMS)
    )
    writer: Optional[threading.Thread] = None
    submitted: bool = False
    input_closing: bool = False
    writer_error: Optional[str] = None
    protocol_error: Optional[str] = None
    prompt: Optional[str] = None
    prompt_digest: Optional[str] = None
    next_request_id: int = 1
    pending_requests: dict[int, tuple[str, Optional[str]]] = field(default_factory=dict)
    parsed_lines: int = 0
    event_count: int = 0
    initialized: bool = False
    announced_thread_id: Optional[str] = None
    thread_id: Optional[str] = None
    announced_turn_id: Optional[str] = None
    turn_id: Optional[str] = None
    pending_messages: list[DispatchMessage] = field(default_factory=list)
    active_message_count: int = 0
    active_message_bytes: int = 0
    steer_request_ids: set[int] = field(default_factory=set)
    acknowledged_steers: set[int] = field(default_factory=set)
    interrupt_request_id: Optional[int] = None
    turn_completed: bool = False
    turn_status: Optional[str] = None
    agent_message: Optional[str] = None
    completion_termination_requested: bool = False
    outcome: Optional[ProcessOutcome] = None
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


class CodexAppServerBackend:
    """Optional isolated stable-v2 backend for passive Codex turns.

    The default Codex adapter remains one-shot ``codex exec``. This backend is
    opt-in because app-server has no ``--ignore-user-config`` or
    ``--ignore-rules`` flag in the compatibility-pinned releases. It obtains
    equivalent passive-lane isolation by using a fresh home, suppressing
    project instructions, denying every execution/connector feature, checking
    the effective MCP list, and admitting only read-only nondelegating roles.
    It never forwards the JSON-RPC transcript to the public dispatch result.
    """

    descendant_containment = False

    def __init__(self, *, mcp_probe: Optional[CodexMcpIsolationProbe] = None) -> None:
        self._subprocess = SubprocessBackend()
        self.mcp_probe = mcp_probe or _probe_codex_no_mcp

    @staticmethod
    def argv(executable: str) -> tuple[str, ...]:
        argv: list[str] = [
            executable,
            "app-server",
            "--strict-config",
            "--listen",
            "stdio://",
        ]
        for feature in _CODEX_LOCKDOWN_FEATURES:
            argv.extend(("--disable", feature))
        for override in _CODEX_APP_SERVER_CONFIG_OVERRIDES:
            argv.extend(("-c", override))
        return tuple(argv)

    @staticmethod
    def _safe_auth_bytes(environment: Mapping[str, str]) -> Optional[bytes]:
        configured_home = environment.get("CODEX_HOME")
        if configured_home:
            source_home = Path(configured_home).expanduser()
        else:
            ordinary_home = environment.get("HOME")
            if not ordinary_home:
                return None
            source_home = Path(ordinary_home).expanduser() / ".codex"
        if not source_home.is_absolute():
            raise DispatchAdapterError("Codex app-server auth source is unsafe")
        auth_path = source_home / "auth.json"
        try:
            auth_metadata = auth_path.lstat()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise DispatchAdapterError(
                "Codex app-server auth source is unsafe"
            ) from exc
        try:
            resolved_home = source_home.resolve(strict=True)
            resolved_auth = auth_path.resolve(strict=True)
        except OSError as exc:
            raise DispatchAdapterError(
                "Codex app-server auth source is unsafe"
            ) from exc
        if (
            resolved_home != source_home
            or resolved_auth != auth_path
            or not resolved_home.is_dir()
            or not stat.S_ISREG(auth_metadata.st_mode)
            or auth_metadata.st_nlink != 1
            or auth_metadata.st_size > _MAX_CODEX_AUTH_BYTES
            or stat.S_IMODE(auth_metadata.st_mode) & 0o077
        ):
            raise DispatchAdapterError("Codex app-server auth source is unsafe")
        if hasattr(os, "geteuid") and auth_metadata.st_uid != os.geteuid():
            raise DispatchAdapterError("Codex app-server auth source is unsafe")

        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(auth_path, flags)
        except OSError as exc:
            raise DispatchAdapterError(
                "Codex app-server auth source is unsafe"
            ) from exc
        try:
            opened_metadata = os.fstat(descriptor)
            if (
                opened_metadata.st_dev != auth_metadata.st_dev
                or opened_metadata.st_ino != auth_metadata.st_ino
                or not stat.S_ISREG(opened_metadata.st_mode)
                or opened_metadata.st_size > _MAX_CODEX_AUTH_BYTES
            ):
                raise DispatchAdapterError(
                    "Codex app-server auth source changed during validation"
                )
            remaining = opened_metadata.st_size
            chunks: list[bytes] = []
            while remaining:
                chunk = os.read(descriptor, min(65_536, remaining))
                if not chunk:
                    raise DispatchAdapterError(
                        "Codex app-server auth source changed during validation"
                    )
                chunks.append(chunk)
                remaining -= len(chunk)
            if os.read(descriptor, 1):
                raise DispatchAdapterError(
                    "Codex app-server auth source changed during validation"
                )
        finally:
            os.close(descriptor)
        payload = b"".join(chunks)
        try:
            document = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DispatchAdapterError(
                "Codex app-server auth source is malformed"
            ) from exc
        if not isinstance(document, dict):
            raise DispatchAdapterError("Codex app-server auth source is malformed")
        return payload

    @classmethod
    def _isolated_environment(
        cls,
        environment: Mapping[str, str],
        *,
        copy_auth: bool,
    ) -> _IsolatedCodexEnvironment:
        auth_payload = cls._safe_auth_bytes(environment) if copy_auth else None
        temporary = tempfile.TemporaryDirectory(prefix="ckit-codex-app-")
        try:
            root = Path(temporary.name).resolve(strict=True)
            root.chmod(0o700)
            home = root / "home"
            xdg_config = root / "xdg-config"
            xdg_cache = root / "xdg-cache"
            xdg_data = root / "xdg-data"
            temporary_files = root / "tmp"
            for directory in (
                home,
                xdg_config,
                xdg_cache,
                xdg_data,
                temporary_files,
            ):
                directory.mkdir(mode=0o700)

            isolated = dict(environment)
            retained_provider_secrets = {
                "CODEX_ACCESS_TOKEN",
                "OPENAI_API_KEY",
            }
            for name in tuple(isolated):
                upper = name.upper()
                if upper.startswith(("CODEX_", "OPENAI_", "AZURE_OPENAI_")):
                    if upper not in retained_provider_secrets:
                        isolated.pop(name, None)
            isolated.update(
                {
                    "CODEX_HOME": str(root),
                    "HOME": str(home),
                    "XDG_CONFIG_HOME": str(xdg_config),
                    "XDG_CACHE_HOME": str(xdg_cache),
                    "XDG_DATA_HOME": str(xdg_data),
                    "TMPDIR": str(temporary_files),
                    "NO_COLOR": "1",
                    _CODEX_APP_SERVER_REMOTE_CONTROL_DISABLED_ENV: "1",
                }
            )
            if auth_payload is not None:
                auth_path = root / "auth.json"
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
                descriptor = os.open(auth_path, flags, 0o600)
                try:
                    view = memoryview(auth_payload)
                    while view:
                        written = os.write(descriptor, view)
                        if written <= 0:  # pragma: no cover - OS contract
                            raise OSError("short write while isolating Codex auth")
                        view = view[written:]
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
                auth_path.chmod(0o600)
            return _IsolatedCodexEnvironment(temporary, root, isolated)
        except BaseException:
            temporary.cleanup()
            raise

    def lockdown_supported(
        self,
        executable: str,
        workspace: Path,
        environment: Mapping[str, str],
        disabled_features: Sequence[str],
        lockdown_probe: CodexLockdownProbe,
    ) -> bool:
        """Run noncredentialed feature and MCP probes in a fresh Codex home."""
        try:
            isolation = self._isolated_environment(environment, copy_auth=False)
        except (DispatchAdapterError, OSError):
            return False
        try:
            return lockdown_probe(
                executable,
                workspace,
                isolation.environment,
                disabled_features,
            ) and self.mcp_probe(
                executable,
                workspace,
                isolation.environment,
                disabled_features,
            )
        except Exception:
            return False
        finally:
            isolation.cleanup()

    @staticmethod
    def _token(process: object) -> _CodexAppServerToken:
        if not isinstance(process, _CodexAppServerToken):
            raise DispatchAdapterError(
                "process token was not created by the Codex app-server backend"
            )
        return process

    @staticmethod
    def _wire(document: Mapping[str, object]) -> bytes:
        payload = (
            json.dumps(
                document,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        if len(payload) > _MAX_PROMPT_BYTES:
            raise DispatchAdapterError(
                "Codex app-server JSONL frame exceeds the 1 MiB safety limit"
            )
        return payload

    @staticmethod
    def _record_writer_error(token: _CodexAppServerToken, message: str) -> None:
        with token.lock:
            if token.writer_error is None:
                token.writer_error = message

    @staticmethod
    def _enqueue_locked(token: _CodexAppServerToken, payload: Optional[bytes]) -> None:
        try:
            token.input_queue.put_nowait(payload)
        except queue.Full as exc:
            token.writer_error = "Codex app-server input queue exceeded its bound"
            raise DispatchAdapterError(
                "Codex app-server input queue exceeded its bound"
            ) from exc

    @classmethod
    def _request_locked(
        cls,
        token: _CodexAppServerToken,
        method: str,
        params: Mapping[str, object],
        *,
        expected: Optional[str] = None,
    ) -> int:
        request_id = token.next_request_id
        token.next_request_id += 1
        token.pending_requests[request_id] = (method, expected)
        cls._enqueue_locked(
            token,
            cls._wire({"id": request_id, "method": method, "params": params}),
        )
        return request_id

    @staticmethod
    def _writer_loop(token: _CodexAppServerToken) -> None:
        stdin = token.subprocess.process.stdin
        if stdin is None:  # pragma: no cover - SubprocessBackend guarantees this
            CodexAppServerBackend._record_writer_error(
                token, "host process has no stdin"
            )
            return
        try:
            while True:
                payload = token.input_queue.get()
                if payload is None:
                    stdin.close()
                    return
                stdin.write(payload)
                stdin.flush()
        except (BrokenPipeError, OSError, ValueError) as exc:
            CodexAppServerBackend._record_writer_error(token, str(exc))
            try:
                stdin.close()
            except (BrokenPipeError, OSError, ValueError):
                pass

    def start(
        self, argv: Sequence[str], *, cwd: Path, env: Mapping[str, str]
    ) -> object:
        if not argv or tuple(argv) != self.argv(argv[0]):
            raise DispatchAdapterError(
                "Codex app-server backend requires its exact isolated argv"
            )
        isolation = self._isolated_environment(env, copy_auth=True)
        base: Optional[_SubprocessToken] = None
        try:
            started = self._subprocess.start(argv, cwd=cwd, env=isolation.environment)
            if not isinstance(started, _SubprocessToken):  # pragma: no cover
                raise DispatchAdapterError("Codex subprocess token has an invalid type")
            base = started
            token = _CodexAppServerToken(base, isolation, cwd.resolve(strict=True))
            writer = threading.Thread(
                target=self._writer_loop,
                args=(token,),
                daemon=True,
            )
            writer.start()
            token.writer = writer
            return token
        except BaseException:
            if base is not None:
                try:
                    self._subprocess.terminate(base)
                except BaseException:
                    pass
            isolation.cleanup()
            raise

    @staticmethod
    def _output_schema() -> Mapping[str, object]:
        optional_text: Mapping[str, object] = {
            "anyOf": [
                {"type": "string", "maxLength": 65_536},
                {"type": "null"},
            ]
        }
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["succeeded", "human-stop", "failed"],
                },
                "output": optional_text,
                "error": optional_text,
                "reason": {
                    "anyOf": [
                        {
                            "type": "string",
                            "enum": [reason.value for reason in HumanStopReason],
                        },
                        {"type": "null"},
                    ]
                },
                "message": optional_text,
                "requested_action": optional_text,
                "evidence": {
                    "type": "array",
                    "maxItems": 128,
                    "items": {"type": "string", "maxLength": 4_096},
                },
            },
            "required": [
                "status",
                "output",
                "error",
                "reason",
                "message",
                "requested_action",
                "evidence",
            ],
        }

    def submit(self, process: object, prompt: str) -> None:
        token = self._token(process)
        if not isinstance(prompt, str):
            raise ValueError("prompt must be a string")
        schema_note = (
            "\nThe response schema requires all seven fields. Use null for any "
            "inapplicable output, error, reason, message, or requested_action.\n"
        )
        prompt = prompt + schema_note
        if len(prompt.encode("utf-8")) > _MAX_PROMPT_BYTES:
            raise DispatchAdapterError(
                "Codex app-server prompt exceeds the 1 MiB safety limit"
            )
        with token.lock:
            if token.submitted:
                raise DispatchAdapterError("host prompt was already submitted")
            if token.input_closing:
                raise DispatchAdapterError("Codex app-server input is already closing")
            token.prompt = prompt
            token.prompt_digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
            self._request_locked(
                token,
                "initialize",
                {
                    "clientInfo": {
                        "name": "claude_kit",
                        "title": "claude-kit",
                        "version": "0.83.0",
                    }
                },
            )
            token.submitted = True

    @staticmethod
    def _client_message_id(
        token: _CodexAppServerToken,
        ordinal: int,
        content: str,
    ) -> str:
        digest = token.prompt_digest
        if digest is None:  # pragma: no cover - submit establishes it
            raise DispatchAdapterError("Codex app-server prompt identity is missing")
        return str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"claude-kit:codex-app-server:{digest}:{ordinal}:{content}",
            )
        )

    @staticmethod
    def _message_content(message: DispatchMessage) -> str:
        correlation = (
            f" correlation_id={message.correlation_id}"
            if message.correlation_id is not None
            else ""
        )
        return f"Coordinator {message.kind.value}{correlation}:\n{message.content}"

    @classmethod
    def _send_steer_locked(
        cls,
        token: _CodexAppServerToken,
        message: DispatchMessage,
        ordinal: int,
    ) -> None:
        if token.thread_id is None or token.turn_id is None:
            token.pending_messages.append(message)
            return
        content = cls._message_content(message)
        request_id = cls._request_locked(
            token,
            "turn/steer",
            {
                "threadId": token.thread_id,
                "clientUserMessageId": cls._client_message_id(token, ordinal, content),
                "input": [{"type": "text", "text": content}],
                "expectedTurnId": token.turn_id,
            },
            expected=token.turn_id,
        )
        token.steer_request_ids.add(request_id)

    def message(self, process: object, message: DispatchMessage) -> None:
        token = self._token(process)
        if not isinstance(message, DispatchMessage):
            raise ValueError("message must be a DispatchMessage")
        with token.lock:
            if not token.submitted:
                raise DispatchAdapterError(
                    "Codex app-server requires the initial prompt before a message"
                )
            if token.input_closing or token.turn_completed:
                raise DispatchAdapterError(
                    "Codex app-server has already completed its turn"
                )
            if token.subprocess.process.poll() is not None:
                raise DispatchAdapterError(
                    "Codex app-server process is already terminal"
                )
            message_bytes = len(message.content.encode("utf-8"))
            if (
                token.active_message_count >= _MAX_DISPATCH_MESSAGES
                or token.active_message_bytes + message_bytes
                > _MAX_DISPATCH_MESSAGE_BYTES
            ):
                raise DispatchAdapterError(
                    "Codex app-server message count or cumulative size exceeds "
                    "the safety limit"
                )
            token.active_message_count += 1
            token.active_message_bytes += message_bytes
            self._send_steer_locked(token, message, token.active_message_count)

    @classmethod
    def _send_thread_start_locked(cls, token: _CodexAppServerToken) -> None:
        cls._enqueue_locked(
            token,
            cls._wire({"method": "initialized", "params": {}}),
        )
        cls._request_locked(
            token,
            "thread/start",
            {
                "cwd": str(token.cwd),
                "approvalPolicy": "never",
                "approvalsReviewer": "user",
                "sandbox": "read-only",
                "ephemeral": True,
                "serviceName": "claude_kit",
                "config": {
                    "project_doc_max_bytes": 0,
                    "project_doc_fallback_filenames": [],
                    "agents": {"enabled": False},
                    "hooks": {},
                    "mcp_servers": {},
                    "web_search": "disabled",
                    "tools": {"web_search": False},
                },
            },
        )

    @classmethod
    def _send_turn_start_locked(cls, token: _CodexAppServerToken) -> None:
        if token.thread_id is None or token.prompt is None:
            token.protocol_error = "Codex app-server turn prerequisites are missing"
            return
        cls._request_locked(
            token,
            "turn/start",
            {
                "threadId": token.thread_id,
                "clientUserMessageId": cls._client_message_id(token, 0, token.prompt),
                "input": [{"type": "text", "text": token.prompt}],
                "cwd": str(token.cwd),
                "approvalPolicy": "never",
                "approvalsReviewer": "user",
                "sandboxPolicy": {"type": "readOnly", "networkAccess": False},
                "outputSchema": cls._output_schema(),
            },
        )

    @staticmethod
    def _object_id(value: object) -> Optional[str]:
        return value if isinstance(value, str) and 0 < len(value) <= 256 else None

    @classmethod
    def _response_locked(
        cls,
        token: _CodexAppServerToken,
        document: Mapping[str, object],
    ) -> None:
        request_id = document.get("id")
        if not isinstance(request_id, int) or isinstance(request_id, bool):
            token.protocol_error = "Codex app-server returned an invalid response id"
            return
        pending = token.pending_requests.pop(request_id, None)
        if pending is None:
            token.protocol_error = "Codex app-server returned an unknown response id"
            return
        method, expected = pending
        if "error" in document:
            token.protocol_error = f"Codex app-server rejected {method}"
            return
        result = document.get("result")
        if not isinstance(result, dict):
            token.protocol_error = f"Codex app-server returned malformed {method} data"
            return

        if method == "initialize":
            try:
                reported_home = Path(str(result.get("codexHome"))).resolve(strict=True)
            except (OSError, ValueError):
                token.protocol_error = (
                    "Codex app-server did not attest its isolated home"
                )
                return
            if reported_home != token.isolation.root:
                token.protocol_error = "Codex app-server did not use its isolated home"
                return
            token.initialized = True
            cls._send_thread_start_locked(token)
            return

        if method == "thread/start":
            thread = result.get("thread")
            sandbox = result.get("sandbox")
            if not isinstance(thread, dict) or not isinstance(sandbox, dict):
                token.protocol_error = (
                    "Codex app-server returned malformed thread isolation"
                )
                return
            thread_id = cls._object_id(thread.get("id"))
            try:
                reported_cwd = Path(str(result.get("cwd"))).resolve(strict=True)
            except (OSError, ValueError):
                reported_cwd = Path()
            if (
                thread_id is None
                or thread.get("ephemeral") is not True
                or thread.get("path") is not None
                or result.get("approvalPolicy") != "never"
                or result.get("approvalsReviewer") != "user"
                or sandbox.get("type") != "readOnly"
                or sandbox.get("networkAccess") is not False
                or result.get("instructionSources") != []
                or reported_cwd != token.cwd
                or (
                    token.announced_thread_id is not None
                    and token.announced_thread_id != thread_id
                )
            ):
                token.protocol_error = (
                    "Codex app-server did not preserve passive thread isolation"
                )
                return
            token.thread_id = thread_id
            cls._send_turn_start_locked(token)
            return

        if method == "turn/start":
            turn = result.get("turn")
            if not isinstance(turn, dict):
                token.protocol_error = "Codex app-server returned a malformed turn"
                return
            turn_id = cls._object_id(turn.get("id"))
            if (
                turn_id is None
                or turn.get("status") != "inProgress"
                or (
                    token.announced_turn_id is not None
                    and token.announced_turn_id != turn_id
                )
            ):
                token.protocol_error = "Codex app-server returned a mismatched turn"
                return
            token.turn_id = turn_id
            queued = tuple(token.pending_messages)
            token.pending_messages.clear()
            for ordinal, message in enumerate(queued, 1):
                cls._send_steer_locked(token, message, ordinal)
            return

        if method == "turn/steer":
            if result.get("turnId") != expected:
                token.protocol_error = (
                    "Codex app-server acknowledged the wrong steered turn"
                )
                return
            token.acknowledged_steers.add(request_id)
            return

        if method == "turn/interrupt":
            if result:
                token.protocol_error = (
                    "Codex app-server returned malformed interrupt data"
                )
            return

        token.protocol_error = "Codex app-server returned an unexpected response"

    @classmethod
    def _record_item_locked(
        cls,
        token: _CodexAppServerToken,
        params: Mapping[str, object],
    ) -> None:
        item = params.get("item")
        if not isinstance(item, dict):
            token.protocol_error = "Codex app-server emitted a malformed item"
            return
        item_type = item.get("type")
        if not isinstance(item_type, str):
            token.protocol_error = "Codex app-server emitted an untyped item"
            return
        if item_type in {
            "collabAgentToolCall",
            "commandExecution",
            "dynamicToolCall",
            "fileChange",
            "imageGeneration",
            "imageView",
            "mcpToolCall",
            "sleep",
            "subAgentActivity",
            "webSearch",
        }:
            token.protocol_error = "Codex app-server exposed a denied passive-lane tool"
            return
        if item_type == "agentMessage":
            text = item.get("text")
            if (
                not isinstance(text, str)
                or len(text.encode("utf-8")) > _MAX_OUTPUT_BYTES
            ):
                token.protocol_error = (
                    "Codex app-server emitted an invalid agent message"
                )
                return
            token.agent_message = text

    @classmethod
    def _notification_locked(
        cls,
        token: _CodexAppServerToken,
        method: str,
        params: object,
    ) -> None:
        if not isinstance(params, dict):
            token.protocol_error = (
                "Codex app-server emitted malformed notification data"
            )
            return
        if method == "thread/started":
            thread = params.get("thread")
            if not isinstance(thread, dict):
                token.protocol_error = "Codex app-server emitted a malformed thread"
                return
            thread_id = cls._object_id(thread.get("id"))
            if thread_id is None or thread.get("ephemeral") is not True:
                token.protocol_error = "Codex app-server announced an unsafe thread"
                return
            token.announced_thread_id = thread_id
            if token.thread_id is not None and token.thread_id != thread_id:
                token.protocol_error = "Codex app-server announced the wrong thread"
            return
        if method == "turn/started":
            turn = params.get("turn")
            if not isinstance(turn, dict):
                token.protocol_error = "Codex app-server emitted a malformed turn"
                return
            turn_id = cls._object_id(turn.get("id"))
            if (
                token.thread_id is None
                or params.get("threadId") != token.thread_id
                or turn_id is None
                or turn.get("status") != "inProgress"
            ):
                token.protocol_error = "Codex app-server announced an invalid turn"
                return
            token.announced_turn_id = turn_id
            if token.turn_id is not None and token.turn_id != turn_id:
                token.protocol_error = "Codex app-server announced the wrong turn"
            return
        if method in {"item/started", "item/completed"}:
            if (
                token.thread_id is None
                or token.turn_id is None
                or params.get("threadId") != token.thread_id
                or params.get("turnId") != token.turn_id
            ):
                token.protocol_error = "Codex app-server item targeted the wrong turn"
                return
            cls._record_item_locked(token, params)
            return
        if method == "turn/completed":
            turn = params.get("turn")
            if not isinstance(turn, dict):
                token.protocol_error = (
                    "Codex app-server emitted malformed turn completion"
                )
                return
            turn_id = cls._object_id(turn.get("id"))
            status_value = turn.get("status")
            if (
                token.thread_id is None
                or token.turn_id is None
                or params.get("threadId") != token.thread_id
                or turn_id != token.turn_id
            ):
                token.protocol_error = "Codex app-server completed the wrong turn"
                return
            if status_value not in {"completed", "failed", "interrupted"}:
                token.protocol_error = (
                    "Codex app-server emitted an invalid terminal turn status"
                )
                return
            items = turn.get("items", [])
            if isinstance(items, list):
                for item in items:
                    cls._record_item_locked(token, {"item": item})
            token.turn_status = str(status_value)
            token.turn_completed = True
            if status_value != "completed" and token.protocol_error is None:
                token.protocol_error = "Codex app-server turn did not complete"
            return
        denied_prefixes = (
            "item/commandExecution/",
            "item/fileChange/",
            "item/mcpToolCall/",
            "item/collabAgentToolCall/",
            "item/webSearch/",
            "turn/diff/",
        )
        if method.startswith(denied_prefixes):
            token.protocol_error = (
                "Codex app-server exposed a denied passive-lane event"
            )
        elif method == "error":
            token.protocol_error = "Codex app-server emitted a terminal error"

    @classmethod
    def _document_locked(
        cls,
        token: _CodexAppServerToken,
        document: object,
    ) -> None:
        if not isinstance(document, dict):
            token.protocol_error = "Codex app-server emitted a non-object JSONL frame"
            return
        method = document.get("method")
        if isinstance(method, str):
            if "id" in document:
                token.protocol_error = (
                    "Codex app-server requested an unsupported client action"
                )
                return
            cls._notification_locked(token, method, document.get("params", {}))
            return
        if "id" in document:
            cls._response_locked(token, document)
            return
        token.protocol_error = "Codex app-server emitted an untyped JSONL frame"

    @classmethod
    def _observe(
        cls,
        token: _CodexAppServerToken,
        text: str,
        *,
        final: bool,
    ) -> None:
        framed_lines = text.splitlines(keepends=True)
        available = len(framed_lines)
        if not final and available and not framed_lines[-1].endswith(("\n", "\r")):
            available -= 1
        with token.lock:
            if available < token.parsed_lines:
                token.protocol_error = (
                    "Codex app-server output changed during bounded capture"
                )
                return
            for framed_line in framed_lines[token.parsed_lines : available]:
                token.parsed_lines += 1
                token.event_count += 1
                if token.event_count > _MAX_CODEX_APP_SERVER_EVENTS:
                    token.protocol_error = (
                        "Codex app-server event count exceeded its bound"
                    )
                    return
                if len(framed_line.encode("utf-8")) > _MAX_OUTPUT_BYTES:
                    token.protocol_error = (
                        "Codex app-server JSONL frame exceeded its bound"
                    )
                    return
                line = framed_line.strip()
                if not line:
                    continue
                try:
                    document = json.loads(line)
                except json.JSONDecodeError:
                    token.protocol_error = "Codex app-server emitted malformed JSONL"
                    return
                try:
                    cls._document_locked(token, document)
                except DispatchAdapterError:
                    if token.protocol_error is None:
                        token.protocol_error = (
                            "Codex app-server protocol input exceeded its bound"
                        )
                    return
                if token.protocol_error is not None:
                    return
            if final and available != len(framed_lines):  # pragma: no cover
                token.protocol_error = "Codex app-server emitted incomplete JSONL"

    @staticmethod
    def _close_input(token: _CodexAppServerToken) -> None:
        with token.lock:
            if token.input_closing:
                return
            token.input_closing = True
            try:
                CodexAppServerBackend._enqueue_locked(token, None)
            except DispatchAdapterError:
                pass

    @staticmethod
    def _finish_writer(token: _CodexAppServerToken) -> None:
        CodexAppServerBackend._close_input(token)
        writer = token.writer
        if writer is None:
            return
        writer.join(timeout=2.0)
        if writer.is_alive():
            stdin = token.subprocess.process.stdin
            if stdin is not None and not stdin.closed:
                try:
                    os.close(stdin.fileno())
                except (OSError, ValueError):
                    pass
            writer.join(timeout=0.1)
        if writer.is_alive():
            CodexAppServerBackend._record_writer_error(
                token, "Codex app-server input writer did not stop"
            )

    @classmethod
    def _translated(
        cls,
        token: _CodexAppServerToken,
        outcome: ProcessOutcome,
    ) -> ProcessOutcome:
        cls._observe(token, outcome.stdout, final=True)
        with token.lock:
            protocol_error = token.protocol_error
            writer_error = token.writer_error
            lifecycle_attested = (
                token.initialized
                and token.thread_id is not None
                and token.turn_id is not None
                and not token.pending_requests
            )
            turn_completed = token.turn_completed
            turn_status = token.turn_status
            message = token.agent_message
            steers_complete = token.steer_request_ids.issubset(
                token.acknowledged_steers
            )
            completion_termination_requested = token.completion_termination_requested
        subprocess_token = token.subprocess
        coordinator_termination_attested = (
            completion_termination_requested
            and subprocess_token.termination_requested
            and subprocess_token.termination_signal_sent
            and subprocess_token.process_group_error is None
            and (
                (
                    os.name == "posix"
                    and outcome.returncode in {-signal.SIGTERM, -signal.SIGKILL}
                )
                or (os.name != "posix" and outcome.returncode != 0)
            )
        )
        if (
            protocol_error is not None
            or writer_error is not None
            or outcome.stdout_truncated
            or outcome.stderr_truncated
            or not lifecycle_attested
            or not turn_completed
            or turn_status != "completed"
            or not steers_complete
            or message is None
            or (outcome.returncode != 0 and not coordinator_termination_attested)
        ):
            return outcome
        return ProcessOutcome(
            0,
            message,
            outcome.stderr,
            outcome.stdout_truncated,
            outcome.stderr_truncated,
            outcome.stdout_byte_count,
            outcome.stderr_byte_count,
        )

    @staticmethod
    def _protocol_problem(
        token: _CodexAppServerToken,
        outcome: ProcessOutcome,
    ) -> ProcessOutcome:
        with token.lock:
            writer_error = token.writer_error
            protocol_error = token.protocol_error
            missing_lifecycle = (
                not token.initialized
                or token.thread_id is None
                or token.turn_id is None
                or bool(token.pending_requests)
            )
            missing_completion = not token.turn_completed
            missing_steer = not token.steer_request_ids.issubset(
                token.acknowledged_steers
            )
        diagnostics: list[str] = []
        if writer_error is not None:
            diagnostics.append("Codex app-server input writer failed")
        if (
            protocol_error is not None
            or missing_lifecycle
            or missing_completion
            or missing_steer
            or outcome.stdout_truncated
            or outcome.stderr_truncated
        ):
            diagnostics.append("Codex app-server protocol validation failed")
        if not diagnostics:
            return outcome
        stderr = "\n".join((outcome.stderr.rstrip(), *diagnostics)).lstrip()
        failure_code = 74 if writer_error is not None else 65
        return ProcessOutcome(
            outcome.returncode if outcome.returncode != 0 else failure_code,
            outcome.stdout,
            stderr,
            outcome.stdout_truncated,
            outcome.stderr_truncated,
            outcome.stdout_byte_count,
            max(outcome.stderr_byte_count or 0, len(stderr.encode("utf-8"))),
        )

    def _finalize(
        self,
        token: _CodexAppServerToken,
        outcome: ProcessOutcome,
    ) -> ProcessOutcome:
        try:
            self._finish_writer(token)
            finalized = self._protocol_problem(token, self._translated(token, outcome))
        except BaseException:
            token.isolation.cleanup()
            raise
        # Do not latch a terminal outcome until copied credentials have actually
        # been removed. If cleanup fails, a subsequent terminalization attempt
        # must be able to retry it instead of returning a falsely-clean result.
        token.isolation.cleanup()
        token.outcome = finalized
        return finalized

    def poll(self, process: object) -> Optional[ProcessOutcome]:
        token = self._token(process)
        if token.outcome is not None:
            return token.outcome
        stdout, truncated, _count = token.subprocess.stdout_capture.snapshot()
        self._observe(token, stdout, final=False)
        with token.lock:
            lifecycle_attested = (
                token.initialized
                and token.thread_id is not None
                and token.turn_id is not None
                and not token.pending_requests
            )
            completion_ready = (
                lifecycle_attested
                and token.turn_completed
                and token.turn_status == "completed"
                and token.agent_message is not None
                and token.steer_request_ids.issubset(token.acknowledged_steers)
            )
            should_stop = (
                truncated
                or token.writer_error is not None
                or token.protocol_error is not None
                or completion_ready
            )
        if should_stop:
            if completion_ready and token.subprocess.process.poll() is None:
                with token.lock:
                    token.completion_termination_requested = True
            self._close_input(token)
            try:
                outcome = self._subprocess.terminate(token.subprocess)
            except BaseException:
                self._finish_writer(token)
                token.isolation.cleanup()
                raise
            return self._finalize(token, outcome)
        polled_outcome = self._subprocess.poll(token.subprocess)
        if polled_outcome is None:
            return None
        return self._finalize(token, polled_outcome)

    def terminate(self, process: object) -> ProcessOutcome:
        token = self._token(process)
        if token.outcome is not None:
            return token.outcome
        with token.lock:
            if (
                token.thread_id is not None
                and token.turn_id is not None
                and not token.turn_completed
                and token.interrupt_request_id is None
                and not token.input_closing
            ):
                token.interrupt_request_id = self._request_locked(
                    token,
                    "turn/interrupt",
                    {"threadId": token.thread_id, "turnId": token.turn_id},
                )
        deadline = time.monotonic() + 0.25
        while token.subprocess.process.poll() is None and time.monotonic() < deadline:
            stdout, _truncated, _count = token.subprocess.stdout_capture.snapshot()
            self._observe(token, stdout, final=False)
            with token.lock:
                if token.turn_completed:
                    break
            time.sleep(0.01)
        self._close_input(token)
        try:
            outcome = self._subprocess.terminate(token.subprocess)
        except BaseException:
            self._finish_writer(token)
            token.isolation.cleanup()
            raise
        return self._finalize(token, outcome)


@dataclass
class _AttemptState:
    request: DispatchRequest
    role: NativeRoleDefinition
    process: Optional[object]
    argv: tuple[str, ...]
    prompt: str
    workspace: Path
    scope_base_tree: Optional[str] = None
    messages: list[DispatchMessage] = field(default_factory=list)
    status: DispatchStatus = DispatchStatus.QUEUED
    submitted_at: Optional[float] = None
    result: Optional[DispatchResult] = None


_DEFAULT_CAPABILITIES = frozenset(
    {
        Capability.FILE_READ,
        Capability.FILE_WRITE,
        Capability.SEARCH,
        Capability.SHELL,
        Capability.DELEGATE,
        Capability.MESSAGE,
        Capability.TASK_LEDGER,
        Capability.BROWSER,
        Capability.MCP,
    }
)


class ProcessDispatcher:
    """Shared exact-six-operation implementation for one concrete host."""

    provider: Provider
    # ``spawn`` and ``retry`` only reserve an in-memory QUEUED attempt.  The
    # coordinator durably claims that handle before ``wait`` may start it.
    queued_spawn = True

    def __init__(
        self,
        project_root: Path,
        *,
        executable: str,
        role_loader: Optional[NativeRoleLoader] = None,
        backend: Optional[ProcessBackend] = None,
        supported_capabilities: Sequence[Capability] = tuple(_DEFAULT_CAPABILITIES),
        hard_timeout_seconds: float = 900.0,
        environment: Optional[Mapping[str, str]] = None,
        allowed_workspaces: Sequence[Path] = (),
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.project_root = Path(project_root).resolve(strict=True)
        if not self.project_root.is_dir():
            raise ValueError("project_root must be a directory")
        if not executable or "\x00" in executable:
            raise ValueError("executable must be a non-empty path or command name")
        if hard_timeout_seconds <= 0:
            raise ValueError("hard_timeout_seconds must be positive")
        self.executable = executable
        self.role_loader = role_loader or FilesystemNativeRoleLoader(self.project_root)
        self.backend = backend or SubprocessBackend()
        self.supported_capabilities = frozenset(
            value if isinstance(value, Capability) else Capability(value)
            for value in supported_capabilities
        )
        self.hard_timeout_seconds = float(hard_timeout_seconds)
        self.environment = _nested_host_environment(
            os.environ if environment is None else environment
        )
        self.allowed_workspaces = (self.project_root,) + tuple(
            Path(path).resolve(strict=False) for path in allowed_workspaces
        )
        self.clock = clock
        self.sleeper = sleeper
        self._attempts: dict[DispatchHandle, _AttemptState] = {}

    def _role_environment(self) -> dict[str, str]:
        """Return a minimal host environment without application/external credentials.

        The provider process still needs its own authentication and configuration,
        but a normal review or implementation role must not inherit unrelated
        deployment, GitHub, database, or cloud credentials merely because its
        native tool set includes a shell.
        """
        environment: dict[str, str] = {}
        use_bedrock = self.environment.get("CLAUDE_CODE_USE_BEDROCK") == "1"
        use_vertex = self.environment.get("CLAUDE_CODE_USE_VERTEX") == "1"
        for name, value in self.environment.items():
            upper = name.upper()
            common = (
                upper in _COMMON_CHILD_ENV
                or upper.startswith("LC_")
                or upper.startswith("CKIT_")
                or upper.startswith("PIP_")
                or upper.startswith("UV_")
                or upper.startswith("NPM_CONFIG_")
            )
            if self.provider is Provider.CLAUDE:
                provider = (
                    upper.startswith("ANTHROPIC_")
                    or upper == "CLAUDE_CONFIG_DIR"
                    or upper.startswith("CLAUDE_CODE_USE_")
                    or (
                        use_bedrock
                        and (
                            upper.startswith("AWS_")
                            or upper.startswith("ANTHROPIC_BEDROCK_")
                        )
                    )
                    or (
                        use_vertex
                        and (
                            upper.startswith("GOOGLE_")
                            or upper.startswith("CLOUD_ML_")
                            or upper.startswith("ANTHROPIC_VERTEX_")
                        )
                    )
                )
            else:
                provider = (
                    upper.startswith("OPENAI_")
                    or upper.startswith("AZURE_OPENAI_")
                    or upper == "CODEX_HOME"
                    or upper == "CODEX_ACCESS_TOKEN"
                )
            if common or provider:
                environment[name] = value
        return environment

    def _workspace(self, request: DispatchRequest) -> Path:
        workspace = (
            self.project_root
            if request.workspace is None
            else Path(request.workspace).expanduser().resolve(strict=True)
        )
        if not workspace.is_dir():
            raise DispatchAdapterError("dispatch workspace must be a directory")
        for allowed in self.allowed_workspaces:
            try:
                workspace.relative_to(allowed)
                return workspace
            except ValueError:
                continue
        raise DispatchAdapterError(
            f"dispatch workspace is outside the owned workspace set: {workspace}"
        )

    @staticmethod
    def _workspace_tree(workspace: Path) -> str:
        """Snapshot tracked, untracked, and ignored paths in an alternate index."""
        with tempfile.TemporaryDirectory(prefix="ckit-scope-index-") as temporary:
            environment = dict(os.environ)
            environment["GIT_INDEX_FILE"] = str(Path(temporary) / "index")
            tree = ""
            for command in (
                ("git", "read-tree", "--empty"),
                ("git", "add", "-A", "-f", "--", "."),
                ("git", "write-tree"),
            ):
                result = subprocess.run(
                    command,
                    cwd=workspace,
                    env=environment,
                    check=False,
                    capture_output=True,
                    text=True,
                )
                if result.returncode != 0:
                    raise DispatchAdapterError(
                        "cannot snapshot the managed role write scope with git"
                    )
                if command[1] == "write-tree":
                    tree = result.stdout.strip()
            if not re.fullmatch(r"[0-9a-f]{40,64}", tree):
                raise DispatchAdapterError(
                    "git returned an invalid managed scope tree identity"
                )
            return tree

    @staticmethod
    def _workspace_changes(
        workspace: Path, base_tree: str, current_tree: str
    ) -> tuple[str, ...]:
        result = subprocess.run(
            (
                "git",
                "diff-tree",
                "--no-commit-id",
                "--name-only",
                "-r",
                "-z",
                base_tree,
                current_tree,
            ),
            cwd=workspace,
            check=False,
            capture_output=True,
        )
        if result.returncode != 0:
            raise DispatchAdapterError(
                "cannot compare the managed role write scope with git"
            )
        return tuple(
            sorted(
                raw.decode("utf-8", errors="surrogateescape")
                for raw in result.stdout.split(b"\0")
                if raw
            )
        )

    @staticmethod
    def _scope_base(workspace: Path) -> str:
        result = subprocess.run(
            ("git", "rev-parse", "--show-toplevel"),
            cwd=workspace,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 or not result.stdout.strip():
            raise DispatchAdapterError(
                "managed dispatch requires a git worktree for scope verification"
            )
        try:
            reported = Path(result.stdout.strip()).resolve(strict=True)
        except OSError as exc:
            raise DispatchAdapterError(
                "managed dispatch git root is unavailable"
            ) from exc
        if reported != workspace.resolve(strict=True):
            raise DispatchAdapterError(
                "managed dispatch workspace must be the exact git worktree root"
            )
        return ProcessDispatcher._workspace_tree(workspace)

    @staticmethod
    def _scope_problem(state: _AttemptState) -> Optional[str]:
        if state.scope_base_tree is None:
            return None
        try:
            current_tree = ProcessDispatcher._workspace_tree(state.workspace)
            changed = ProcessDispatcher._workspace_changes(
                state.workspace, state.scope_base_tree, current_tree
            )
        except DispatchAdapterError as exc:
            return str(exc)
        protected = tuple(
            path
            for path in changed
            if any(
                fnmatchcase(path, pattern)
                for pattern in _MANAGED_CONTROL_PLANE_PATTERNS
            )
        )
        if protected:
            rendered = ", ".join(repr(path) for path in protected[:10])
            if len(protected) > 10:
                rendered += f", ... ({len(protected) - 10} more)"
            return (
                f"role {state.role.id!r} changed immutable managed control-plane paths: "
                + rendered
            )
        allowed = state.role.write_scope
        violations = tuple(
            path
            for path in changed
            if not any(fnmatchcase(path, pattern) for pattern in allowed)
        )
        if not violations:
            return None
        rendered = ", ".join(repr(path) for path in violations[:10])
        if len(violations) > 10:
            rendered += f", ... ({len(violations) - 10} more)"
        return (
            f"role {state.role.id!r} changed paths outside its declared write scope: "
            + rendered
        )

    @classmethod
    def _apply_scope_result(
        cls, state: _AttemptState, result: DispatchResult
    ) -> DispatchResult:
        return cls._apply_known_scope_problem(result, cls._scope_problem(state))

    @staticmethod
    def _apply_known_scope_problem(
        result: DispatchResult, problem: Optional[str]
    ) -> DispatchResult:
        """Apply a scope observation captured before coordinator diagnostics.

        Private host captures live under the shared control plane. On terminal
        failures the coordinator must compare role mutations before writing
        that capture, otherwise its own diagnostic becomes a false-positive
        protected-path mutation.
        """
        if problem is None:
            return result
        error = problem if result.error is None else f"{result.error}; {problem}"
        return DispatchResult(
            result.handle,
            DispatchStatus.FAILED,
            output=result.output,
            error=error,
            evidence=result.evidence,
            human_stop=HumanStopRequest(
                HumanStopReason.SCOPE_EXPANSION,
                problem,
                "inspect the preserved run-owned worktree and explicitly remediate "
                "every out-of-scope path before resuming",
            ),
        )

    def _argv(
        self, role: NativeRoleDefinition, workspace: Path
    ) -> tuple[str, ...]:  # pragma: no cover - abstract guard
        raise NotImplementedError

    def _enforceable_capabilities(
        self, role: NativeRoleDefinition
    ) -> frozenset[Capability]:  # pragma: no cover - abstract guard
        """Return controls the concrete invocation can actually attest."""
        raise NotImplementedError

    def _prompt(self, request: DispatchRequest, role: NativeRoleDefinition) -> str:
        evidence = ", ".join(reference.uri for reference in request.evidence) or "none"
        dependencies = (
            ", ".join(reference.uri for reference in request.dependencies) or "none"
        )
        context = request.context.strip() or "(no additional context)"
        write_scope = ", ".join(role.write_scope) or "none"
        prompt = (
            f"Native role: {role.id}\n"
            f"Role description: {role.description}\n\n"
            "Native role instructions:\n"
            f"{role.instructions.strip()}\n\n"
            "Bounded stage objective:\n"
            f"{request.objective}\n\n"
            "Portable context:\n"
            f"{context}\n\n"
            f"Authoritative dependency stage references: {dependencies}\n"
            "Dependency artifact content, when present, is embedded in the portable "
            "context above and was hash-verified by the coordinator.\n\n"
            f"Required evidence references: {evidence}\n\n"
            f"Declared role write scope (verified against the managed git worktree): "
            f"{write_scope}\n"
            f"Isolation requirement: {role.isolation.value}\n\n"
            "Coordinator control: do not run lifecycle commands and do not mutate "
            ".ckit state, gate ledgers, or worktree ownership records. Return bounded "
            "evidence only; the coordinator is the sole ledger writer.\n\n"
            "Return exactly one JSON object and no Markdown. Successful form: "
            '{"status":"succeeded","output":"summary","evidence":["artifact://id"]}. '
            "If a person must decide, return: "
            '{"status":"human-stop","reason":"missing-requirements",'
            '"message":"why","requested_action":"what the person must decide",'
            '"output":"summary","evidence":[]}. '
            "For an ordinary failure, return: "
            '{"status":"failed","error":"reason","evidence":[]}.\n'
        )
        if len(prompt.encode("utf-8")) > _MAX_PROMPT_BYTES:
            raise DispatchAdapterError("dispatch prompt exceeds the 1 MiB safety limit")
        return prompt

    def _workspace_prompt_context(
        self,
        role: NativeRoleDefinition,
        workspace: Path,
        *,
        scope_base_tree: Optional[str],
        native_lockdown_attested: bool,
    ) -> str:
        """Return provider-specific, coordinator-captured workspace context."""
        del role, workspace, scope_base_tree, native_lockdown_attested
        return ""

    def _can_run_without_descendant_containment(
        self,
        role: NativeRoleDefinition,
        *,
        workspace: Path,
        scope_base_tree: Optional[str],
    ) -> bool:
        """Whether this exact invocation exposes no descendant-spawning surface."""
        del workspace, scope_base_tree
        # Claude receives an exact dynamic tool allowlist, so omitting Bash is
        # already a complete process-spawn denial for the base adapter.
        return Capability.SHELL not in role.capabilities

    def _launch(
        self,
        request: DispatchRequest,
        *,
        dispatch_id: Optional[str] = None,
        attempt: int = 1,
        retry_message: Optional[DispatchMessage] = None,
    ) -> DispatchHandle:
        role = self.role_loader.load(self.provider, request.route)
        required = frozenset(request.required_capabilities) | role.capabilities
        workspace = self._workspace(request)
        if role.isolation is IsolationRequirement.REQUIRED:
            try:
                workspace.relative_to(self.project_root)
            except ValueError:
                pass
            else:
                raise DispatchAdapterError(
                    f"role {role.id!r} requires an owned non-root worktree"
                )
        scope_base_tree = (
            self._scope_base(workspace) if request.workspace is not None else None
        )
        # A process group is not a portable descendant-containment boundary: a
        # shell child can create a new session and outlive the coordinator.  Do
        # not rely on the managed workflow compiler to add this semantic
        # requirement, because ProcessDispatcher is also a public adapter seam
        # and can be used directly by another provider-neutral executor.  A
        # concrete adapter may waive this prerequisite only when it removes
        # every command/delegation/plugin surface and binds the invocation to a
        # scope-checkpointed, run-owned workspace.
        native_lockdown_attested = (
            Capability.SHELL not in role.capabilities
            and self._can_run_without_descendant_containment(
                role,
                workspace=workspace,
                scope_base_tree=scope_base_tree,
            )
        )
        needs_containment = Capability.SHELL in role.capabilities or not (
            native_lockdown_attested
        )
        backend_contains_descendants = (
            getattr(self.backend, "descendant_containment", False) is True
        )
        if needs_containment and not backend_contains_descendants:
            raise UnsupportedCapabilityError(
                role.id, (Capability.DESCENDANT_CONTAINMENT,)
            )
        # The durable task ledger is supplied by the provider-neutral Python
        # coordinator, not by a host-specific Task tool.  The child prompt is
        # explicitly read-only with respect to that ledger, while the adapter
        # provides hash-verified dependency context and records the terminal
        # result.  Treat that portable controller boundary as enforceable for
        # either host when the role declares it.
        coordinator_capabilities = frozenset({Capability.TASK_LEDGER})
        attested = (
            role.capabilities
            & self.supported_capabilities
            & (self._enforceable_capabilities(role) | coordinator_capabilities)
        )
        # Managed shell stages freeze this semantic safety capability into the
        # stage contract.  For Codex roles without semantic shell access it is
        # an adapter-only prerequisite, so do not add an extra capability to
        # the handle and break the ledger's exact provider-neutral contract.
        if (
            Capability.DESCENDANT_CONTAINMENT in required
            and backend_contains_descendants
        ):
            attested |= frozenset({Capability.DESCENDANT_CONTAINMENT})
        missing = required - attested
        if missing:
            raise UnsupportedCapabilityError(role.id, tuple(missing))
        argv = self._argv(role, workspace)
        handle = DispatchHandle(
            dispatch_id or str(uuid.uuid4()),
            role.id,
            attempt,
            provider=self.provider.value,
            required_capabilities=tuple(required),
            attested_capabilities=tuple(attested),
        )
        workspace_context = self._workspace_prompt_context(
            role,
            workspace,
            scope_base_tree=scope_base_tree,
            native_lockdown_attested=native_lockdown_attested,
        )
        if workspace_context and scope_base_tree is not None:
            after_snapshot_tree = self._workspace_tree(workspace)
            if after_snapshot_tree != scope_base_tree:
                raise DispatchAdapterError(
                    "managed workspace changed while its Codex prompt snapshot "
                    "was being captured"
                )
        prompt_request = (
            request
            if not workspace_context
            else DispatchRequest(
                route=request.route,
                objective=request.objective,
                lane=request.lane,
                dependencies=request.dependencies,
                evidence=request.evidence,
                retry_budget=request.retry_budget,
                context="\n\n".join(
                    part
                    for part in (request.context, workspace_context)
                    if part.strip()
                ),
                required_capabilities=request.required_capabilities,
                workspace=request.workspace,
            )
        )
        prompt = self._prompt(prompt_request, role)
        state = _AttemptState(
            request=request,
            role=role,
            process=None,
            argv=argv,
            prompt=prompt,
            workspace=workspace,
            scope_base_tree=scope_base_tree,
        )
        if retry_message is not None:
            state.messages.append(retry_message)
        self._attempts[handle] = state
        return handle

    def spawn(self, request: DispatchRequest) -> DispatchHandle:
        """Reserve a validated queued attempt without starting a native process.

        The workflow coordinator durably claims the returned handle before
        ``wait`` starts the detached host.  This ordering prevents an unledgered
        worker from escaping if the claim fails or the coordinator is interrupted.
        """
        if not isinstance(request, DispatchRequest):
            raise ValueError("request must be a DispatchRequest")
        return self._launch(request)

    def message(self, handle: DispatchHandle, message: DispatchMessage) -> None:
        """Deliver bounded context before start or through a steerable backend."""
        state = self._state(handle)
        if not isinstance(message, DispatchMessage):
            raise ValueError("message must be a DispatchMessage")
        total_bytes = sum(
            len(existing.content.encode("utf-8")) for existing in state.messages
        ) + len(message.content.encode("utf-8"))
        if (
            len(state.messages) >= _MAX_DISPATCH_MESSAGES
            or total_bytes > _MAX_DISPATCH_MESSAGE_BYTES
        ):
            raise DispatchAdapterError(
                "dispatch message count or cumulative size exceeds the safety limit"
            )
        if state.status is DispatchStatus.QUEUED:
            state.messages.append(message)
            return
        if state.status is not DispatchStatus.RUNNING or state.process is None:
            raise DispatchAdapterError(
                "messages require a queued or actively running dispatch"
            )
        sender = getattr(self.backend, "message", None)
        if not callable(sender):
            raise DispatchAdapterError(
                "the configured native process backend does not support active messages"
            )
        try:
            sender(state.process, message)
        except DispatchAdapterError:
            raise
        except Exception as exc:
            raise DispatchAdapterError(
                f"cannot deliver active dispatch message: {exc}"
            ) from exc
        state.messages.append(message)

    def _state(self, handle: DispatchHandle) -> _AttemptState:
        try:
            return self._attempts[handle]
        except KeyError as exc:
            raise DispatchAdapterError(f"unknown dispatch handle: {handle.id}") from exc

    @staticmethod
    def _with_messages(state: _AttemptState) -> str:
        if not state.messages:
            return state.prompt
        rendered = "\n".join(
            f"- {message.kind.value}: {message.content}" for message in state.messages
        )
        prompt = (
            state.prompt + "\nMessages received before execution:\n" + rendered + "\n"
        )
        if len(prompt.encode("utf-8")) > _MAX_PROMPT_BYTES:
            raise DispatchAdapterError(
                "dispatch prompt plus queued messages exceeds the 1 MiB safety limit"
            )
        return prompt

    def _submit(self, handle: DispatchHandle, state: _AttemptState) -> None:
        if state.status is not DispatchStatus.QUEUED:
            return
        outcome: Optional[ProcessOutcome] = None
        try:
            state.process = self.backend.start(
                state.argv,
                cwd=state.workspace,
                env=self._role_environment(),
            )
            self.backend.submit(state.process, self._with_messages(state))
        except Exception:
            if state.process is not None:
                try:
                    outcome = self.backend.terminate(state.process)
                except Exception:
                    pass
            scope_problem = self._scope_problem(state)
            state.status = DispatchStatus.FAILED
            state.submitted_at = None
            state.result = self._apply_known_scope_problem(
                DispatchResult(
                    handle,
                    DispatchStatus.FAILED,
                    error=self._capture_error(
                        handle,
                        "cannot submit host prompt",
                        outcome,
                        category="prompt-submit-failed",
                    ),
                ),
                scope_problem,
            )
            return
        state.status = DispatchStatus.RUNNING
        state.submitted_at = self.clock()

    @staticmethod
    def _json_document(stdout: str) -> Mapping[str, object]:
        text = stdout.strip()
        if text.startswith("```json") and text.endswith("```"):
            text = text[7:-3].strip()
        try:
            document = json.loads(text)
        except json.JSONDecodeError as exc:
            raise DispatchAdapterError(
                "host did not return the required JSON envelope"
            ) from exc
        if not isinstance(document, dict):
            raise DispatchAdapterError("host result envelope must be a JSON object")
        return document

    @staticmethod
    def _truncation_note(outcome: ProcessOutcome) -> Optional[str]:
        notes: list[str] = []
        stdout_count = outcome.stdout_byte_count or 0
        stderr_count = outcome.stderr_byte_count or 0
        if (
            outcome.stdout_truncated
            or stdout_count > _MAX_OUTPUT_BYTES
            or len(outcome.stdout.encode("utf-8")) > _MAX_OUTPUT_BYTES
        ):
            notes.append(
                "stdout captured prefix truncated at "
                f"{min(len(outcome.stdout.encode('utf-8')), _MAX_OUTPUT_BYTES)} "
                f"of {stdout_count} bytes"
            )
        if (
            outcome.stderr_truncated
            or stderr_count > _MAX_OUTPUT_BYTES
            or len(outcome.stderr.encode("utf-8")) > _MAX_OUTPUT_BYTES
        ):
            notes.append(
                "stderr captured prefix truncated at "
                f"{min(len(outcome.stderr.encode('utf-8')), _MAX_OUTPUT_BYTES)} "
                f"of {stderr_count} bytes"
            )
        return "; ".join(notes) or None

    def _capture_error(
        self,
        handle: DispatchHandle,
        message: str,
        outcome: Optional[ProcessOutcome],
        *,
        category: str,
    ) -> str:
        """Persist private host bytes and return metadata safe for public output."""
        if outcome is None:
            return f"{message}; diagnostic_category={category}; no host output captured"
        document = (
            json.dumps(
                {
                    "schema_version": 1,
                    "provider": self.provider.value,
                    "dispatch_id": handle.id,
                    "attempt": handle.attempt,
                    "category": category,
                    "returncode": outcome.returncode,
                    "stdout": outcome.stdout,
                    "stderr": outcome.stderr,
                    "stdout_bytes": outcome.stdout_byte_count,
                    "stderr_bytes": outcome.stderr_byte_count,
                    "stdout_truncated": outcome.stdout_truncated,
                    "stderr_truncated": outcome.stderr_truncated,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        layout = detect_state_layout(self.project_root)
        relative = f"{layout.artifacts}/dispatch/{handle.id}-{handle.attempt}-host-capture.json"
        try:
            ProjectFS(self.project_root).write_bytes(relative, document, mode=0o600)
            capture = (
                f"capture={relative}; sha256={hashlib.sha256(document).hexdigest()}"
            )
        except Exception:
            capture = "capture=unavailable"
        details = [
            message,
            f"diagnostic_category={category}",
            capture,
            f"returncode={outcome.returncode}",
            f"stdout_bytes={outcome.stdout_byte_count}",
            f"stderr_bytes={outcome.stderr_byte_count}",
        ]
        truncation = self._truncation_note(outcome)
        if truncation:
            details.append(truncation)
        return "; ".join(details)

    def _result(
        self, handle: DispatchHandle, state: _AttemptState, outcome: ProcessOutcome
    ) -> DispatchResult:
        del state
        truncation = self._truncation_note(outcome)
        if truncation is not None:
            return DispatchResult(
                handle,
                DispatchStatus.FAILED,
                error=self._capture_error(
                    handle,
                    "host output exceeds the 1 MiB safety limit",
                    outcome,
                    category="output-limit-exceeded",
                ),
            )
        if outcome.returncode != 0:
            return DispatchResult(
                handle,
                DispatchStatus.FAILED,
                error=self._capture_error(
                    handle,
                    f"host exited with status {outcome.returncode}",
                    outcome,
                    category="host-nonzero-exit",
                ),
            )
        try:
            document = self._json_document(outcome.stdout)
            evidence_raw = document.get("evidence", [])
            if not isinstance(evidence_raw, list):
                raise DispatchAdapterError("host evidence must be an array")
            evidence = tuple(SymbolicRef.parse(str(value)) for value in evidence_raw)
            status = document.get("status")
            output_raw = document.get("output")
            output = str(output_raw).strip() if output_raw is not None else None
            if status == "succeeded":
                return DispatchResult(
                    handle,
                    DispatchStatus.SUCCEEDED,
                    output=output or "completed",
                    evidence=evidence,
                )
            if status == "human-stop":
                message = public_human_stop_text(
                    document.get("message", ""),
                    fallback="native worker requested a human decision",
                )
                requested_action = public_human_stop_text(
                    document.get("requested_action", ""),
                    fallback="inspect the private dispatch artifact and decide how to proceed",
                )
                stop = HumanStopRequest(
                    HumanStopReason(str(document.get("reason", ""))),
                    message,
                    requested_action,
                )
                return DispatchResult(
                    handle,
                    DispatchStatus.FAILED,
                    # The complete host envelope is already stored in the
                    # mode-0600 capture. Do not duplicate arbitrary human-stop
                    # output into public state.
                    output=None,
                    error=(
                        message
                        + "; "
                        + self._capture_error(
                            handle,
                            "host requested a human stop",
                            outcome,
                            category="human-stop",
                        )
                    ),
                    evidence=evidence,
                    human_stop=stop,
                )
            if status == "failed":
                error = str(document.get("error", "")).strip()
                if not error:
                    raise DispatchAdapterError("failed host result has no error")
                return DispatchResult(
                    handle,
                    DispatchStatus.FAILED,
                    error=self._capture_error(
                        handle,
                        "host reported stage failure",
                        outcome,
                        category="host-reported-failure",
                    ),
                    evidence=evidence,
                )
            raise DispatchAdapterError(f"unsupported host result status: {status!r}")
        except (DispatchAdapterError, ValueError):
            return DispatchResult(
                handle,
                DispatchStatus.FAILED,
                error=self._capture_error(
                    handle,
                    "host returned a malformed result envelope",
                    outcome,
                    category="malformed-host-envelope",
                ),
            )

    def _refresh(self, handle: DispatchHandle, state: _AttemptState) -> None:
        if state.status is not DispatchStatus.RUNNING:
            return
        if state.process is None:  # pragma: no cover - guarded by _submit
            raise DispatchAdapterError("running dispatch has no native process")
        if (
            state.submitted_at is not None
            and self.clock() - state.submitted_at >= self.hard_timeout_seconds
        ):
            timeout_outcome = self.backend.terminate(state.process)
            scope_problem = self._scope_problem(state)
            state.status = DispatchStatus.FAILED
            state.result = self._apply_known_scope_problem(
                DispatchResult(
                    handle,
                    DispatchStatus.FAILED,
                    error=self._capture_error(
                        handle,
                        f"host exceeded hard timeout of {self.hard_timeout_seconds:g}s",
                        timeout_outcome,
                        category="hard-timeout",
                    ),
                ),
                scope_problem,
            )
            return
        polled_outcome = self.backend.poll(state.process)
        if polled_outcome is None:
            return
        scope_problem = self._scope_problem(state)
        state.result = self._apply_known_scope_problem(
            self._result(handle, state, polled_outcome), scope_problem
        )
        state.status = state.result.status

    def wait(
        self,
        handles: Sequence[DispatchHandle],
        mode: WaitMode = WaitMode.ALL,
        timeout_seconds: Optional[float] = None,
    ) -> WaitResult:
        """Submit all queued prompts first, then perform a bounded wait."""
        if not isinstance(mode, WaitMode):
            mode = WaitMode(mode)
        if timeout_seconds is not None and timeout_seconds < 0:
            raise ValueError("timeout_seconds must be non-negative")
        ordered = tuple(handles)
        if len(set(ordered)) != len(ordered):
            raise ValueError("wait handles must not contain duplicates")
        states = [(handle, self._state(handle)) for handle in ordered]
        try:
            for handle, state in states:
                self._submit(handle, state)
            deadline = (
                None if timeout_seconds is None else self.clock() + timeout_seconds
            )
            while True:
                for handle, state in states:
                    self._refresh(handle, state)
                completed = tuple(
                    handle for handle, state in states if state.status.terminal
                )
                pending = tuple(
                    handle for handle, state in states if not state.status.terminal
                )
                if not pending or (mode is WaitMode.FIRST_COMPLETED and completed):
                    return WaitResult(completed, pending, False)
                if deadline is not None and self.clock() >= deadline:
                    return WaitResult(completed, pending, True)
                self.sleeper(0.01)
        except BaseException:
            # Host processes own detached groups so they survive coordinator signals unless
            # explicitly terminated. Best-effort terminalize every process before preserving
            # the original KeyboardInterrupt/SystemExit for the caller.
            for handle, state in states:
                if state.status.terminal:
                    continue
                try:
                    self.cancel(handle, "coordinator interrupted")
                except BaseException:
                    pass
            raise

    def collect(self, handles: Sequence[DispatchHandle]) -> tuple[DispatchResult, ...]:
        """Collect terminal results without implicitly starting queued work."""
        results: list[DispatchResult] = []
        for handle in handles:
            state = self._state(handle)
            self._refresh(handle, state)
            if state.result is None:
                raise DispatchAdapterError(f"dispatch is not terminal: {handle.id}")
            results.append(state.result)
        return tuple(results)

    def retry(self, handle: DispatchHandle, reason: str) -> DispatchHandle:
        """Create the next queued attempt only after a failed attempt."""
        state = self._state(handle)
        if state.status is not DispatchStatus.FAILED:
            raise DispatchAdapterError("only failed dispatches may be retried")
        if not reason.strip():
            raise ValueError("retry reason must be non-empty")
        return self._launch(
            state.request,
            dispatch_id=handle.id,
            attempt=handle.attempt + 1,
            retry_message=DispatchMessage("correction", reason),  # type: ignore[arg-type]
        )

    def cancel(self, handle: DispatchHandle, reason: str) -> None:
        """Cancel one exact queued/running attempt and preserve a terminal result."""
        state = self._state(handle)
        if not reason.strip():
            raise ValueError("cancel reason must be non-empty")
        public_reason = public_human_stop_text(reason, fallback="dispatch cancelled")
        if state.status.terminal:
            raise DispatchAdapterError("terminal dispatches cannot be cancelled")
        outcome = (
            None if state.process is None else self.backend.terminate(state.process)
        )
        scope_problem = self._scope_problem(state)
        state.status = DispatchStatus.CANCELLED
        state.result = self._apply_known_scope_problem(
            DispatchResult(
                handle,
                DispatchStatus.CANCELLED,
                error=self._capture_error(
                    handle,
                    public_reason,
                    outcome,
                    category="cancelled",
                ),
            ),
            scope_problem,
        )


class ClaudeProcessDispatcher(ProcessDispatcher):
    """Claude Code adapter using native agents and bounded stream input."""

    provider = Provider.CLAUDE

    def __init__(
        self, project_root: Path, *, executable: str = "claude", **kwargs: Any
    ) -> None:
        if "backend" not in kwargs or kwargs["backend"] is None:
            kwargs["backend"] = ClaudeStreamJsonBackend()
        super().__init__(project_root, executable=executable, **kwargs)

    def _argv(self, role: NativeRoleDefinition, workspace: Path) -> tuple[str, ...]:
        permission_mode = (
            "plan" if role.permission is PermissionClass.READ_ONLY else "acceptEdits"
        )
        inline_agent = json.dumps(
            {
                role.id: {
                    "description": role.description,
                    "prompt": role.instructions,
                    "tools": list(role.native_tools),
                    "permissionMode": permission_mode,
                    **({"model": role.native_model} if role.native_model else {}),
                }
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        argv = [
            self.executable,
            "--print",
            "--output-format",
            (
                "stream-json"
                if isinstance(self.backend, ClaudeStreamJsonBackend)
                else "text"
            ),
            "--no-session-persistence",
            "--permission-mode",
            permission_mode,
            "--agents",
            inline_agent,
            "--agent",
            role.id,
        ]
        if isinstance(self.backend, ClaudeStreamJsonBackend):
            argv.extend(
                (
                    "--input-format",
                    "stream-json",
                    "--verbose",
                )
            )
        return tuple(argv)

    def _enforceable_capabilities(
        self, role: NativeRoleDefinition
    ) -> frozenset[Capability]:
        # Dynamic --agents definitions receive an exact native tool allowlist.
        # External mutation is never attested by unattended managed execution;
        # it is represented as a portable human stop instead.
        return _claude_capabilities(role.native_tools) - {Capability.EXTERNAL_MUTATION}


class CodexProcessDispatcher(ProcessDispatcher):
    """Codex adapter using ephemeral noninteractive execution and sandboxing."""

    provider = Provider.CODEX

    def __init__(
        self,
        project_root: Path,
        *,
        executable: str = "codex",
        lockdown_probe: Optional[CodexLockdownProbe] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(project_root, executable=executable, **kwargs)
        self.lockdown_probe = lockdown_probe or _probe_codex_lockdown

    @staticmethod
    def _is_passive_lockdown_role(role: NativeRoleDefinition) -> bool:
        passive_capabilities = frozenset(
            {
                Capability.FILE_READ,
                Capability.SEARCH,
                Capability.MESSAGE,
                Capability.TASK_LEDGER,
            }
        )
        return (
            role.permission is PermissionClass.READ_ONLY
            and role.nested_delegation is NestedDelegationPolicy.FORBIDDEN
            and role.capabilities.issubset(passive_capabilities)
        )

    def _argv(self, role: NativeRoleDefinition, workspace: Path) -> tuple[str, ...]:
        if isinstance(self.backend, CodexAppServerBackend):
            if not self._is_passive_lockdown_role(role):
                raise DispatchAdapterError(
                    "Codex app-server is available only for passive read-only roles"
                )
            return self.backend.argv(self.executable)
        sandbox = (
            "read-only"
            if role.permission is PermissionClass.READ_ONLY
            else "workspace-write"
        )
        argv: list[str] = [
            self.executable,
            "exec",
            "--ephemeral",
            "--ignore-user-config",
            "--strict-config",
            "--color",
            "never",
            "--sandbox",
            sandbox,
            "-c",
            'approval_policy="never"',
            "-c",
            "sandbox_workspace_write.network_access=false",
            "-c",
            "sandbox_workspace_write.exclude_slash_tmp=true",
            "-c",
            "sandbox_workspace_write.exclude_tmpdir_env_var=true",
            "-c",
            'shell_environment_policy.inherit="core"',
            "-c",
            "shell_environment_policy.ignore_default_excludes=false",
            "-c",
            "shell_environment_policy.experimental_use_profile=false",
        ]
        if role.nested_delegation is NestedDelegationPolicy.FORBIDDEN:
            argv.extend(("--disable", "multi_agent", "-c", "agents.enabled=false"))
        else:
            argv.extend(("--enable", "multi_agent", "-c", "agents.enabled=true"))
        if Capability.SHELL not in role.capabilities:
            # A semantic no-shell role gets no command, hook, connector, or
            # hosted-search escape hatch.  File read/search is supplied by the
            # complete bounded coordinator snapshot below; read-only sandboxing
            # remains the independent mutation boundary.
            argv.extend(
                (
                    "--ignore-rules",
                    "--disable",
                    "shell_tool",
                    "--disable",
                    "unified_exec",
                    "--disable",
                    "shell_snapshot",
                    "--disable",
                    "hooks",
                    "--disable",
                    "remote_plugin",
                    "--disable",
                    "skill_mcp_dependency_install",
                    "-c",
                    "hooks={}",
                    "-c",
                    'web_search="disabled"',
                    "-c",
                    "tools.web_search=false",
                    "-c",
                    "check_for_update_on_startup=false",
                    "-c",
                    "feedback.enabled=false",
                    "-c",
                    'history.persistence="none"',
                )
            )
        if self._is_passive_lockdown_role(role):
            for feature in _CODEX_LOCKDOWN_FEATURES:
                argv.extend(("--disable", feature))
            argv.extend(
                (
                    "-c",
                    "agents.enabled=false",
                    "-c",
                    "hooks={}",
                    "-c",
                    "mcp_servers={}",
                    "-c",
                    'web_search="disabled"',
                    "-c",
                    "tools.web_search=false",
                )
            )
        if Capability.BROWSER not in role.capabilities:
            for feature in (
                "apps",
                "browser_use",
                "browser_use_external",
                "computer_use",
            ):
                argv.extend(("--disable", feature))
        else:
            for feature in (
                "apps",
                "browser_use",
                "browser_use_external",
                "computer_use",
            ):
                argv.extend(("--enable", feature))
        if Capability.MCP not in role.capabilities:
            for server_id in role.mcp_server_ids:
                argv.extend(
                    (
                        "-c",
                        f"mcp_servers.{json.dumps(server_id)}.enabled=false",
                    )
                )
        argv.extend(("--cd", str(workspace), "-"))
        return tuple(argv)

    def _can_run_without_descendant_containment(
        self,
        role: NativeRoleDefinition,
        *,
        workspace: Path,
        scope_base_tree: Optional[str],
    ) -> bool:
        """Admit only the fully tool-denied managed read-only Codex lane."""
        if isinstance(self.backend, CodexAppServerBackend):
            return (
                scope_base_tree is not None
                and self._is_passive_lockdown_role(role)
                and self.backend.lockdown_supported(
                    self.executable,
                    workspace,
                    self._role_environment(),
                    _CODEX_LOCKDOWN_FEATURES,
                    self.lockdown_probe,
                )
            )
        return (
            scope_base_tree is not None
            and self._is_passive_lockdown_role(role)
            and self.lockdown_probe(
                self.executable,
                workspace,
                self._role_environment(),
                _CODEX_LOCKDOWN_FEATURES,
            )
        )

    def _workspace_prompt_context(
        self,
        role: NativeRoleDefinition,
        workspace: Path,
        *,
        scope_base_tree: Optional[str],
        native_lockdown_attested: bool,
    ) -> str:
        """Capture a bounded, sensitive-path-filtered projection for no-shell roles.

        The projection is metadata-first: Git supplies tracked path names, then
        control-plane, generated, sensitive-path, symlink, and non-text entries
        are rejected before their bytes are opened. A non-ignored untracked text
        source makes this lane unavailable rather than silently broadening the
        provider input. Any ambiguity or bound violation fails before the host
        starts.
        """
        if (
            scope_base_tree is None
            or not native_lockdown_attested
            or not self._is_passive_lockdown_role(role)
            or not (role.capabilities & {Capability.FILE_READ, Capability.SEARCH})
        ):
            return ""

        entries: list[dict[str, str]] = []
        withheld_path_count = 0
        redaction_count = 0
        opened_byte_count = 0
        snapshot_capability = (
            Capability.FILE_READ
            if Capability.FILE_READ in role.capabilities
            else Capability.SEARCH
        )

        def snapshot_error() -> UnsupportedCapabilityError:
            return UnsupportedCapabilityError(role.id, (snapshot_capability,))

        def safe_text_path(relative: str) -> bool:
            nonlocal withheld_path_count
            try:
                encoded = relative.encode("utf-8")
            except UnicodeEncodeError:
                raise snapshot_error() from None
            if (
                not relative
                or len(encoded) > _MAX_CODEX_SNAPSHOT_PATH_BYTES
                or relative.startswith("/")
                or "\\" in relative
            ):
                raise snapshot_error()
            parts = tuple(part for part in relative.split("/") if part)
            if not parts or any(part in {".", ".."} for part in parts):
                raise snapshot_error()
            lowered = tuple(part.casefold() for part in parts)
            basename = lowered[-1]
            stem = basename.split(".", 1)[0]
            if (
                lowered[0] in _CODEX_SNAPSHOT_CONTROL_ROOTS
                or relative in {"AGENTS.md", "CLAUDE.md", ".mcp.json"}
                or any(part in _CODEX_SNAPSHOT_GENERATED_COMPONENTS for part in lowered)
                or any(part in _CODEX_SNAPSHOT_SENSITIVE_COMPONENTS for part in lowered)
                or _CODEX_SNAPSHOT_SENSITIVE_NAME_RE.search(basename) is not None
                or _CODEX_SNAPSHOT_SECRET_VALUE_RE.search(relative) is not None
                or _CODEX_SNAPSHOT_SECRET_ASSIGNMENT_RE.search(relative) is not None
            ):
                withheld_path_count += 1
                return False
            suffix = Path(basename).suffix
            textual_name = (
                basename in _CODEX_SNAPSHOT_TEXT_NAMES
                or stem in _CODEX_SNAPSHOT_TEXT_NAMES
                or suffix in _CODEX_SNAPSHOT_TEXT_SUFFIXES
            )
            if not textual_name:
                withheld_path_count += 1
                return False
            return True

        def redact(content: str) -> str:
            nonlocal redaction_count
            projected, direct_count = _CODEX_SNAPSHOT_SECRET_VALUE_RE.subn(
                "[REDACTED]", content
            )
            projected, assignment_count = _CODEX_SNAPSHOT_SECRET_ASSIGNMENT_RE.subn(
                r"\1[REDACTED]", projected
            )
            redaction_count += direct_count + assignment_count
            return projected

        try:
            tracked_result = subprocess.run(
                (
                    "git",
                    "ls-files",
                    "-z",
                    "--cached",
                    "--",
                ),
                cwd=workspace,
                check=False,
                capture_output=True,
            )
            untracked_result = subprocess.run(
                (
                    "git",
                    "ls-files",
                    "-z",
                    "--others",
                    "--exclude-standard",
                    "--",
                ),
                cwd=workspace,
                check=False,
                capture_output=True,
            )
            if (
                tracked_result.returncode != 0
                or untracked_result.returncode != 0
                or len(tracked_result.stdout) + len(untracked_result.stdout)
                > _MAX_CODEX_SNAPSHOT_METADATA_BYTES
            ):
                raise snapshot_error()
            raw_paths = tuple(raw for raw in tracked_result.stdout.split(b"\0") if raw)
            raw_untracked = tuple(
                raw for raw in untracked_result.stdout.split(b"\0") if raw
            )
            if len(raw_paths) + len(raw_untracked) > _MAX_CODEX_SNAPSHOT_FILES * 8:
                raise snapshot_error()
            for raw_path in sorted(raw_untracked):
                try:
                    relative = raw_path.decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise snapshot_error() from exc
                if safe_text_path(relative):
                    raise snapshot_error()
            for raw_path in sorted(raw_paths):
                try:
                    relative = raw_path.decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise snapshot_error() from exc
                if not safe_text_path(relative):
                    continue
                candidate = workspace / relative
                info = candidate.lstat()
                if stat.S_ISLNK(info.st_mode):
                    withheld_path_count += 1
                    continue
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_size > _MAX_CODEX_SNAPSHOT_FILE_BYTES
                ):
                    raise snapshot_error()
                if (
                    len(entries) >= _MAX_CODEX_SNAPSHOT_FILES
                    or opened_byte_count + info.st_size > _MAX_CODEX_SNAPSHOT_BYTES
                ):
                    raise snapshot_error()
                resolved = candidate.resolve(strict=True)
                try:
                    resolved.relative_to(workspace)
                except ValueError as exc:
                    raise snapshot_error() from exc
                flags = os.O_RDONLY
                if hasattr(os, "O_CLOEXEC"):
                    flags |= os.O_CLOEXEC
                if hasattr(os, "O_NOFOLLOW"):
                    flags |= os.O_NOFOLLOW
                descriptor = os.open(candidate, flags)
                try:
                    opened_info = os.fstat(descriptor)
                    if (
                        not stat.S_ISREG(opened_info.st_mode)
                        or opened_info.st_dev != info.st_dev
                        or opened_info.st_ino != info.st_ino
                        or opened_info.st_size != info.st_size
                        or opened_info.st_size > _MAX_CODEX_SNAPSHOT_FILE_BYTES
                    ):
                        raise snapshot_error()
                    opened_byte_count += opened_info.st_size
                    with os.fdopen(descriptor, "rb", closefd=False) as stream:
                        content_bytes = stream.read(_MAX_CODEX_SNAPSHOT_FILE_BYTES + 1)
                finally:
                    os.close(descriptor)
                if len(content_bytes) > _MAX_CODEX_SNAPSHOT_FILE_BYTES:
                    raise snapshot_error()
                try:
                    content = content_bytes.decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise snapshot_error() from exc
                projected = redact(content)
                projected_bytes = projected.encode("utf-8")
                entries.append(
                    {
                        "path": relative,
                        "kind": "file",
                        "sha256": hashlib.sha256(projected_bytes).hexdigest(),
                        "content": projected,
                    }
                )
        except UnsupportedCapabilityError:
            raise
        except (OSError, ValueError) as exc:
            raise DispatchAdapterError(
                f"cannot capture managed Codex workspace snapshot: {exc}"
            ) from exc

        snapshot_core = {
            "schema_version": 1,
            "root": ".",
            "workspace_tree": scope_base_tree,
            "projection": "tracked-sensitive-path-filtered-text",
            "withheld_path_count": withheld_path_count,
            "redaction_count": redaction_count,
            "files": entries,
        }
        canonical = json.dumps(
            snapshot_core,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        if len(canonical) > _MAX_CODEX_SNAPSHOT_BYTES:
            raise snapshot_error()
        document = {
            **snapshot_core,
            "snapshot_sha256": hashlib.sha256(canonical).hexdigest(),
        }
        return (
            "Coordinator-captured bounded source projection for this managed "
            "no-shell Codex role. It contains only tracked, sensitive-path-filtered "
            "text; control-plane, generated, sensitive-path, symlink, and non-text "
            "entries were never opened. Secret-shaped values inside included "
            "source were heuristically redacted before hashing, but the projection "
            "must still be treated as sensitive and credentials must never be "
            "echoed. Non-ignored untracked text makes capture fail closed. This is "
            "the role's filesystem.read/filesystem.search input; the pinned-host "
            "lockdown probe verified that no shell or local command feature is "
            "available. Treat the projection digest and per-path projected-content "
            "digests as authoritative.\n"
            + json.dumps(
                document,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        )

    def _enforceable_capabilities(
        self, role: NativeRoleDefinition
    ) -> frozenset[Capability]:
        capabilities = {
            Capability.FILE_READ,
            Capability.SEARCH,
            # Returning the terminal envelope is the bounded child-to-parent
            # message channel even when nested delegation is disabled.
            Capability.MESSAGE,
        }
        if Capability.SHELL in role.capabilities:
            capabilities.add(Capability.SHELL)
        if role.permission is not PermissionClass.READ_ONLY:
            capabilities.add(Capability.FILE_WRITE)
        if role.nested_delegation is not NestedDelegationPolicy.FORBIDDEN:
            capabilities.add(Capability.DELEGATE)
        if Capability.MCP in role.capabilities and role.mcp_server_ids:
            capabilities.add(Capability.MCP)
        if Capability.BROWSER in role.capabilities:
            capabilities.add(Capability.BROWSER)
        return frozenset(capabilities)


__all__ = [
    "ActiveMessageProcessBackend",
    "ClaudeProcessDispatcher",
    "ClaudeStreamJsonBackend",
    "CodexAppServerBackend",
    "CodexLockdownProbe",
    "CodexProcessDispatcher",
    "DispatchAdapterError",
    "FilesystemNativeRoleLoader",
    "NativeRoleDefinition",
    "NativeRoleLoader",
    "ProcessBackend",
    "ProcessDispatcher",
    "ProcessOutcome",
    "RoleUnavailableError",
    "SubprocessBackend",
    "UnsupportedCapabilityError",
]
