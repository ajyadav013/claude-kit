"""Provider projection for semantic MCP catalog values."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Iterable

from claude_kit.components import MCPServerSpec

MCP_CLIENT_CONTEXT_REF = "provider://mcp-client-context"

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
    """Project a selected semantic MCP set for one host deterministically."""

    return {
        server_id: project_server_config(servers[server_id], runtime)
        for server_id in sorted(servers)
    }


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


__all__ = [
    "MCP_CLIENT_CONTEXT_REF",
    "project_server_config",
    "project_resolved_servers",
    "project_server_specs",
    "project_servers",
    "require_runtime_support",
]
