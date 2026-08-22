"""Semantic MCP definitions project provider-specific values at render time."""

from __future__ import annotations

import json

import pytest

from claude_kit import catalog, scaffold
from claude_kit.components import MCPServerSpec, MCPTransport
from claude_kit.mcp import (
    MCP_CLIENT_CONTEXT_REF,
    project_server_config,
    project_server_specs,
    require_runtime_support,
)


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
