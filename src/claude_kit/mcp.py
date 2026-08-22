"""Provider projection for semantic MCP catalog values."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Iterable

from claude_kit.components import MCPServerSpec

MCP_CLIENT_CONTEXT_REF = "provider://mcp-client-context"
_ENV_REFERENCE_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

_CLIENT_CONTEXTS = {
    "claude": "claude-code",
    "codex": "codex",
    "cursor": "ide",
}


def _project_value(value: Any, replacement: str) -> Any:
    if isinstance(value, str):
        return value.replace(MCP_CLIENT_CONTEXT_REF, replacement)
    if isinstance(value, list):
        return [_project_value(item, replacement) for item in value]
    if isinstance(value, tuple):
        return [_project_value(item, replacement) for item in value]
    if isinstance(value, Mapping):
        return {
            str(key): _project_value(item, replacement) for key, item in value.items()
        }
    return value


def project_server_config(config: Mapping[str, Any], runtime: str) -> dict[str, Any]:
    """Resolve provider symbols in one credential-free MCP definition."""

    try:
        context = _CLIENT_CONTEXTS[runtime]
    except KeyError as exc:
        raise ValueError(f"unsupported MCP projection runtime: {runtime}") from exc
    projected = _project_value(config, context)
    if not isinstance(
        projected, dict
    ):  # pragma: no cover - Mapping always projects to dict
        raise TypeError("MCP config projection must produce a mapping")
    return projected


def project_servers(
    servers: Mapping[str, Mapping[str, Any]], runtime: str
) -> dict[str, dict[str, Any]]:
    """Project legacy config-only MCP values after semantic safety validation.

    Older callers can omit ``ResolvedPlan.mcp_server_specs``. They do not get to
    bypass the credential and transport boundary: each compatibility fragment
    is first round-tripped through ``MCPServerSpec`` with conservative universal
    runtime metadata, then provider symbols are resolved.
    """

    projected: dict[str, dict[str, Any]] = {}
    for server_id in sorted(servers):
        spec = MCPServerSpec.from_catalog(
            server_id,
            {
                "label": f"Compatibility MCP server {server_id}",
                "runtime_support": ["claude", "codex"],
                "authentication": {"mode": "inferred"},
                "health_check": {"kind": "mcp-initialize"},
                "config": servers[server_id],
            },
        )
        projected[server_id] = project_server_config(spec.provider_config, runtime)
    return projected


def require_runtime_support(
    servers: Mapping[str, MCPServerSpec], runtimes: Iterable[str]
) -> None:
    """Fail closed when a selected semantic server cannot serve every runtime.

    MCP selection is explicit and therefore required.  Silently dropping a
    provider-limited server from one side of a ``both`` install would make the two
    projections describe different capabilities, so projection rejects the whole
    request before any project mutation.
    """

    required = tuple(
        dict.fromkeys(str(runtime).strip().lower() for runtime in runtimes)
    )
    unknown = sorted(set(required) - {"claude", "codex"})
    if unknown:
        raise ValueError("unsupported MCP projection runtime(s): " + ", ".join(unknown))
    unsupported: list[str] = []
    for server_id in sorted(servers):
        spec = servers[server_id]
        if not isinstance(spec, MCPServerSpec):
            raise ValueError(
                f"resolved MCP server {server_id!r} has no semantic MCPServerSpec"
            )
        missing = sorted(set(required) - set(spec.runtime_support))
        if missing:
            supported = ",".join(sorted(spec.runtime_support))
            unsupported.append(
                f"{server_id} lacks {','.join(missing)} (supports: {supported})"
            )
            continue
        if "codex" in required:
            try:
                adapt_codex_server_config(
                    server_id,
                    project_server_config(spec.provider_config, "codex"),
                )
            except ValueError as exc:
                unsupported.append(f"{server_id} cannot be adapted to codex ({exc})")
    if unsupported:
        raise ValueError(
            "selected MCP server runtime support is incompatible: "
            + "; ".join(unsupported)
        )


def project_server_specs(
    servers: Mapping[str, MCPServerSpec], runtime: str
) -> dict[str, dict[str, Any]]:
    """Validate and project full semantic MCP records for one native host."""

    require_runtime_support(servers, (runtime,))
    return {
        server_id: project_server_config(servers[server_id].provider_config, runtime)
        for server_id in sorted(servers)
    }


def project_resolved_servers(
    configs: Mapping[str, Mapping[str, Any]],
    specs: Mapping[str, MCPServerSpec],
    runtime: str,
) -> dict[str, dict[str, Any]]:
    """Project a resolved plan, retaining compatibility for config-only callers."""

    if specs:
        if set(configs) != set(specs):
            raise ValueError(
                "resolved MCP configs and semantic specs have different ids"
            )
        return project_server_specs(specs, runtime)
    return project_servers(configs, runtime)


def _clone_config_value(value: Any) -> Any:
    """Copy a configuration value into JSON/TOML-friendly containers."""

    if isinstance(value, Mapping):
        return {str(key): _clone_config_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clone_config_value(item) for item in value]
    return value


def _reject_codex_environment_interpolation(
    server_id: str,
    value: Any,
    *,
    location: str,
) -> None:
    """Reject placeholders that Codex would otherwise receive as literal text."""

    if isinstance(value, str):
        if _ENV_REFERENCE_RE.search(value):
            raise ValueError(
                f"MCP server {server_id!r} uses unsupported Codex environment "
                f"interpolation in {location}: {value!r}"
            )
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            _reject_codex_environment_interpolation(
                server_id,
                item,
                location=f"{location}.{key}",
            )
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_codex_environment_interpolation(
                server_id,
                item,
                location=f"{location}[{index}]",
            )


def adapt_codex_server_config(
    server_id: str,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    """Adapt one projected semantic MCP fragment to native Codex fields.

    Codex forwards same-named process variables through ``env_vars`` and resolves
    HTTP header variables through ``env_http_headers``.  It does not interpolate
    ``${ENV}`` placeholders in command arguments, URLs, literal environment
    values, or arbitrary configuration fields.  Those shapes fail closed here so
    the native host never receives a plausible-looking literal placeholder.
    """

    if not isinstance(config, Mapping):
        raise ValueError(f"MCP server {server_id!r} config must be a mapping")
    if any(not isinstance(key, str) for key in config):
        raise ValueError(f"MCP server {server_id!r} config keys must be strings")

    server_type = config.get("type")
    if server_type not in {"stdio", "http"}:
        raise ValueError(f"MCP server {server_id!r} type must be 'stdio' or 'http'")

    environment = config.get("env", {})
    headers = config.get("headers", {})
    if not isinstance(environment, Mapping):
        raise ValueError(f"MCP server {server_id!r} env must be a mapping")
    if not isinstance(headers, Mapping):
        raise ValueError(f"MCP server {server_id!r} headers must be a mapping")
    if any(not isinstance(key, str) for key in environment):
        raise ValueError(f"MCP server {server_id!r} env keys must be strings")
    if any(not isinstance(key, str) for key in headers):
        raise ValueError(f"MCP server {server_id!r} header names must be strings")
    if environment and server_type != "stdio":
        raise ValueError(
            f"MCP server {server_id!r} environment is only supported for Codex "
            "stdio servers"
        )
    if headers and server_type != "http":
        raise ValueError(
            f"MCP server {server_id!r} headers are only supported for Codex HTTP "
            "servers"
        )

    provider_native = {"env_vars", "http_headers", "env_http_headers"}
    unexpected_native = sorted(provider_native.intersection(config))
    if unexpected_native:
        raise ValueError(
            f"MCP server {server_id!r} semantic config contains Codex-native "
            f"field(s): {', '.join(unexpected_native)}"
        )

    native: dict[str, Any] = {}
    for key in sorted(config):
        if key in {"type", "env", "headers"}:
            continue
        value = config[key]
        _reject_codex_environment_interpolation(
            server_id,
            value,
            location=key,
        )
        native[key] = _clone_config_value(value)

    forwarded: list[str] = []
    literal_environment: dict[str, str] = {}
    for key in sorted(environment):
        value = environment[key]
        if not isinstance(value, str):
            raise ValueError(
                f"MCP server {server_id!r} env value for {key!r} must be a string"
            )
        match = _ENV_REFERENCE_RE.fullmatch(value)
        if match:
            source = match.group(1)
            if source != key:
                raise ValueError(
                    f"MCP server {server_id!r} cannot map Codex environment key "
                    f"{key!r} from {source!r}; env_vars forwards same-named "
                    "variables only"
                )
            forwarded.append(key)
            continue
        _reject_codex_environment_interpolation(
            server_id,
            value,
            location=f"env.{key}",
        )
        literal_environment[key] = value

    static_headers: dict[str, str] = {}
    environment_headers: dict[str, str] = {}
    for key in sorted(headers):
        value = headers[key]
        if not isinstance(value, str):
            raise ValueError(
                f"MCP server {server_id!r} header value for {key!r} must be a string"
            )
        match = _ENV_REFERENCE_RE.fullmatch(value)
        if match:
            environment_headers[key] = match.group(1)
            continue
        _reject_codex_environment_interpolation(
            server_id,
            value,
            location=f"headers.{key}",
        )
        static_headers[key] = value

    if forwarded:
        native["env_vars"] = forwarded
    if literal_environment:
        native["env"] = literal_environment
    if static_headers:
        native["http_headers"] = static_headers
    if environment_headers:
        native["env_http_headers"] = environment_headers
    return native


__all__ = [
    "MCP_CLIENT_CONTEXT_REF",
    "adapt_codex_server_config",
    "project_server_config",
    "project_resolved_servers",
    "project_server_specs",
    "project_servers",
    "require_runtime_support",
]
