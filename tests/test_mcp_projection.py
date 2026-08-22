"""Semantic MCP definitions project provider-specific values at render time."""

from __future__ import annotations

import json

import pytest

from claude_kit import catalog, scaffold
from claude_kit.components import MCPServerSpec, MCPTransport
from claude_kit.mcp import (
    MCP_CLIENT_CONTEXT_REF,
    adapt_codex_server_config,
    project_server_config,
    project_server_specs,
    project_servers,
    require_runtime_support,
)
from claude_kit.models import InstallRequest
from claude_kit.runtime_scaffold import RuntimeInstallError, install_runtime


def test_project_server_config_resolves_nested_context_without_mutating_source():
    source = {
        "type": "stdio",
        "command": "server",
        "args": ["--context", MCP_CLIENT_CONTEXT_REF],
        "env": {"CONTEXT": MCP_CLIENT_CONTEXT_REF},
    }

    assert project_server_config(source, "claude")["args"][-1] == "claude-code"
    assert project_server_config(source, "codex")["args"][-1] == "codex"
    assert project_server_config(source, "cursor")["args"][-1] == "ide"
    assert source["args"][-1] == MCP_CLIENT_CONTEXT_REF
    with pytest.raises(ValueError, match="unsupported MCP projection runtime"):
        project_server_config(source, "unknown")


@pytest.mark.parametrize("runtime", ["claude", "codex"])
def test_config_only_projection_cannot_bypass_semantic_credential_validation(runtime):
    with pytest.raises(ValueError, match="environment reference"):
        project_servers(
            {
                "unsafe": {
                    "type": "http",
                    "url": "https://mcp.example.test/mcp",
                    "headers": {"Authorization": "Bearer literal-secret"},
                }
            },
            runtime,
        )


@pytest.mark.parametrize(
    ("support", "runtimes", "accepted"),
    [
        ({"claude"}, ("claude",), True),
        ({"claude"}, ("codex",), False),
        ({"claude"}, ("claude", "codex"), False),
        ({"codex"}, ("claude",), False),
        ({"codex"}, ("codex",), True),
        ({"codex"}, ("claude", "codex"), False),
        ({"claude", "codex"}, ("claude",), True),
        ({"claude", "codex"}, ("codex",), True),
        ({"claude", "codex"}, ("claude", "codex"), True),
    ],
)
def test_selected_mcp_runtime_support_matrix(support, runtimes, accepted):
    spec = MCPServerSpec(
        id="limited",
        label="Limited test server",
        transport=MCPTransport.STDIO,
        command="server",
        runtime_support=frozenset(support),
    )

    if accepted:
        require_runtime_support({"limited": spec}, runtimes)
    else:
        with pytest.raises(
            ValueError,
            match=r"limited lacks (claude|codex).*supports:",
        ):
            require_runtime_support({"limited": spec}, runtimes)


@pytest.mark.parametrize(
    "config",
    [
        {"type": "sse", "url": "https://mcp.example.test/events"},
        {
            "type": "stdio",
            "command": "server",
            "env": {"DESTINATION": "${SOURCE}"},
        },
        {
            "type": "stdio",
            "command": "server",
            "args": ["--endpoint", "${MCP_ENDPOINT}"],
        },
    ],
)
def test_declared_codex_support_must_be_natively_adaptable(config):
    spec = MCPServerSpec.from_catalog(
        "false-codex-support",
        {
            "label": "False Codex support",
            "runtime_support": ["claude", "codex"],
            "authentication": {"mode": "inferred"},
            "health_check": {"kind": "mcp-initialize"},
            "config": config,
        },
    )

    require_runtime_support({spec.id: spec}, ("claude",))
    with pytest.raises(ValueError, match="cannot be adapted to codex"):
        require_runtime_support({spec.id: spec}, ("codex",))


def test_project_server_specs_checks_support_and_preserves_source():
    spec = MCPServerSpec(
        id="contextual",
        label="Contextual server",
        transport=MCPTransport.STDIO,
        command="server",
        arguments=("--context", MCP_CLIENT_CONTEXT_REF),
        runtime_support=frozenset({"claude", "codex"}),
    )

    claude = project_server_specs({"contextual": spec}, "claude")
    codex = project_server_specs({"contextual": spec}, "codex")

    assert claude["contextual"]["args"][-1] == "claude-code"
    assert codex["contextual"]["args"][-1] == "codex"
    assert spec.arguments[-1] == MCP_CLIENT_CONTEXT_REF


def test_codex_adapter_maps_native_environment_fields_without_mutating_source():
    source = {
        "type": "stdio",
        "command": "server",
        "args": ["serve"],
        "env": {
            "FORWARDED_TOKEN": "${FORWARDED_TOKEN}",
            "LOG_LEVEL": "warning",
        },
    }

    assert adapt_codex_server_config("local", source) == {
        "command": "server",
        "args": ["serve"],
        "env_vars": ["FORWARDED_TOKEN"],
        "env": {"LOG_LEVEL": "warning"},
    }
    assert source["env"]["FORWARDED_TOKEN"] == "${FORWARDED_TOKEN}"


def test_codex_adapter_maps_static_and_environment_http_headers():
    source = {
        "type": "http",
        "url": "https://mcp.example.test/mcp",
        "headers": {
            "Authorization": "${EXAMPLE_BEARER_TOKEN}",
            "X-Region": "us-east-1",
        },
    }

    assert adapt_codex_server_config("remote", source) == {
        "url": "https://mcp.example.test/mcp",
        "http_headers": {"X-Region": "us-east-1"},
        "env_http_headers": {"Authorization": "EXAMPLE_BEARER_TOKEN"},
    }


@pytest.mark.parametrize(
    ("config", "message"),
    [
        (
            {
                "type": "stdio",
                "command": "server",
                "args": ["--dsn", "${DATABASE_URL}"],
            },
            r"interpolation in args\[1\]",
        ),
        (
            {
                "type": "stdio",
                "command": "server",
                "args": ["prefix-${TOKEN}"],
            },
            r"interpolation in args\[0\]",
        ),
        (
            {
                "type": "http",
                "url": "https://mcp.example.test/mcp?token=${TOKEN}",
            },
            "interpolation in url",
        ),
        (
            {
                "type": "stdio",
                "command": "server",
                "env": {"DESTINATION_TOKEN": "${SOURCE_TOKEN}"},
            },
            "cannot map Codex environment key",
        ),
        (
            {
                "type": "http",
                "url": "https://mcp.example.test/mcp",
                "headers": {"X-Prefix": "Bearer ${TOKEN}"},
            },
            "interpolation in headers.X-Prefix",
        ),
    ],
)
def test_codex_adapter_rejects_placeholder_channels_the_host_does_not_expand(
    config, message
):
    with pytest.raises(ValueError, match=message):
        adapt_codex_server_config("unsupported", config)


@pytest.mark.parametrize(
    "server_id", ["postgres", "mongodb", "azure_devops", "repowise"]
)
@pytest.mark.parametrize("runtime", ["codex", "both"])
def test_shipped_claude_only_mcp_servers_fail_before_runtime_mutation(
    payload, tmp_path, server_id, runtime
):
    selection = catalog.defaults(payload)
    selection.mcp = [server_id]
    plan = catalog.resolve(payload, selection)
    target = tmp_path / f"{server_id}-{runtime}"

    assert plan.mcp_server_specs[server_id].runtime_support == {"claude"}
    with pytest.raises(RuntimeInstallError, match=rf"{server_id} lacks codex"):
        install_runtime(
            payload,
            target,
            plan,
            InstallRequest(selection=selection, runtime=runtime),
        )

    assert not target.exists()


def test_legacy_claude_scaffold_projects_semantic_serena_context(payload, tmp_path):
    selection = catalog.defaults(payload)
    selection.mcp = ["serena"]
    plan = catalog.resolve(payload, selection)
    assert MCP_CLIENT_CONTEXT_REF in plan.mcp_servers["serena"]["args"]

    scaffold.install_sdlc(payload, tmp_path, plan)
    document = json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))
    args = document["mcpServers"]["serena"]["args"]
    assert args[-1] == "claude-code"
    assert MCP_CLIENT_CONTEXT_REF not in json.dumps(document)
