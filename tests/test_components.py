"""Provider-neutral component IR contracts."""

from __future__ import annotations

import pytest

from claude_kit.components import (
    AgentSpec,
    Capability,
    CommandSpec,
    HookEffect,
    HookEvent,
    HookSeverity,
    HookSpec,
    InvocationMode,
    IsolationRequirement,
    MCPAuthenticationMode,
    MCPServerSpec,
    MCPTransport,
    ModelTier,
    NestedDelegationPolicy,
    PermissionClass,
    ReferenceKind,
    RuleSpec,
    SkillSpec,
    SymbolicRef,
    WorkflowSpec,
    WorkflowStage,
)


def test_mcp_spec_is_semantic_credential_free_and_provider_neutral():
    spec = MCPServerSpec.from_catalog(
        "github",
        {
            "label": "GitHub",
            "runtime_support": ["claude", "codex"],
            "authentication": {"mode": "inferred"},
            "health_check": {"kind": "mcp-initialize"},
            "config": {
                "type": "stdio",
                "command": "npx",
                "args": ["-y", "server@1.0.0"],
                "env": {"GITHUB_TOKEN": "${GITHUB_TOKEN}"},
            },
        },
    )

    assert spec.transport is MCPTransport.STDIO
    assert spec.authentication is MCPAuthenticationMode.INFERRED
    assert spec.runtime_support == {"claude", "codex"}
    assert spec.health_check == "mcp-initialize"
    assert spec.environment_references == ("GITHUB_TOKEN",)
    assert spec.semantic_metadata == {
        "label": "GitHub",
        "transport": "stdio",
        "authentication": "inferred",
        "runtime_support": ["claude", "codex"],
        "health_check": "mcp-initialize",
        "environment_references": ["GITHUB_TOKEN"],
    }
    assert spec.provider_config == {
        "type": "stdio",
        "command": "npx",
        "args": ["-y", "server@1.0.0"],
        "env": {"GITHUB_TOKEN": "${GITHUB_TOKEN}"},
    }


def test_mcp_spec_rejects_inline_credentials_and_incomplete_transport():
    common = {
        "label": "Unsafe",
        "runtime_support": ["claude", "codex"],
        "authentication": {"mode": "inferred"},
        "health_check": {"kind": "mcp-initialize"},
    }
    with pytest.raises(ValueError, match="environment reference"):
        MCPServerSpec.from_catalog(
            "unsafe",
            {
                **common,
                "config": {
                    "type": "stdio",
                    "command": "server",
                    "env": {"API_TOKEN": "literal-secret"},
                },
            },
        )
    with pytest.raises(ValueError, match="require a URL"):
        MCPServerSpec.from_catalog(
            "missing-url", {**common, "config": {"type": "http"}}
        )


@pytest.mark.parametrize(
    "environment_name", ["AUTH", "BEARER", "SESSION_COOKIE", "PRIVATE_KEY"]
)
def test_mcp_spec_rejects_literal_sensitive_environment_values(environment_name):
    with pytest.raises(ValueError, match="environment reference"):
        MCPServerSpec.from_catalog(
            "unsafe-environment",
            {
                "label": "Unsafe environment",
                "runtime_support": ["claude", "codex"],
                "authentication": {"mode": "inferred"},
                "health_check": {"kind": "mcp-initialize"},
                "config": {
                    "type": "stdio",
                    "command": "server",
                    "env": {environment_name: "fixed-value"},
                },
            },
        )


@pytest.mark.parametrize(
    "header_name",
    [
        "Authorization",
        "authorization",
        "Proxy-Authorization",
        "Cookie",
        "Set-Cookie",
        "X-API-Key",
        "ApiKey",
        "X-Auth",
        "X-Auth-Token",
        "X-Access-Token",
        "X-Private-Key",
    ],
)
def test_mcp_spec_rejects_literal_sensitive_header_values(header_name):
    with pytest.raises(ValueError, match="environment reference"):
        MCPServerSpec.from_catalog(
            "unsafe-header",
            {
                "label": "Unsafe header",
                "runtime_support": ["claude", "codex"],
                "authentication": {"mode": "inferred"},
                "health_check": {"kind": "mcp-initialize"},
                "config": {
                    "type": "http",
                    "url": "https://mcp.example.test",
                    "headers": {header_name: "fixed-value"},
                },
            },
        )


@pytest.mark.parametrize(
    "header_name",
    ["Authorization", "Proxy_Authorization", "Cookie", "Set_Cookie", "X-API-Key"],
)
def test_mcp_spec_accepts_sensitive_header_environment_references(header_name):
    spec = MCPServerSpec.from_catalog(
        "referenced-header",
        {
            "label": "Referenced header",
            "runtime_support": ["claude", "codex"],
            "authentication": {"mode": "inferred"},
            "health_check": {"kind": "mcp-initialize"},
            "config": {
                "type": "http",
                "url": "https://mcp.example.test",
                "headers": {
                    header_name: "${MCP_HEADER_VALUE}",
                    "Content-Type": "application/json",
                },
            },
        },
    )

    assert dict(spec.headers) == {
        "Content-Type": "application/json",
        header_name: "${MCP_HEADER_VALUE}",
    }
    assert spec.environment_references == ("MCP_HEADER_VALUE",)


@pytest.mark.parametrize("value", ["Bearer literal-token", "Basic dXNlcjpwYXNz"])
def test_mcp_spec_rejects_authorization_schemes_in_custom_headers(value):
    with pytest.raises(ValueError, match="environment reference"):
        MCPServerSpec.from_catalog(
            "custom-auth-header",
            {
                "label": "Custom authorization header",
                "runtime_support": ["claude", "codex"],
                "authentication": {"mode": "inferred"},
                "health_check": {"kind": "mcp-initialize"},
                "config": {
                    "type": "http",
                    "url": "https://mcp.example.test",
                    "headers": {"X-Whatever": value},
                },
            },
        )


@pytest.mark.parametrize(
    "url",
    [
        "https://service-account:fixed-value@mcp.example.test",
        "https://service-account@mcp.example.test",
        "https://%73ervice:%66ixed@mcp.example.test",
        "https://${MCP_USER}:fixed-value@mcp.example.test",
    ],
)
def test_mcp_spec_rejects_literal_url_userinfo(url):
    with pytest.raises(
        ValueError, match="userinfo values must be environment references"
    ):
        MCPServerSpec.from_catalog(
            "userinfo",
            {
                "label": "URL userinfo",
                "runtime_support": ["claude", "codex"],
                "authentication": {"mode": "inferred"},
                "health_check": {"kind": "mcp-initialize"},
                "config": {"type": "http", "url": url},
            },
        )


@pytest.mark.parametrize(
    "query",
    [
        "access_token=fixed-value",
        "api_key=fixed-value",
        "%61ccess_token=fixed-value",
        "client%5Fsecret=fixed-value",
        "AUTHORIZATION=fixed-value",
        "private_key=fixed-value",
    ],
)
def test_mcp_spec_rejects_literal_sensitive_url_query_values(query):
    with pytest.raises(ValueError, match="credential parameter.*environment reference"):
        MCPServerSpec.from_catalog(
            "query-credential",
            {
                "label": "Query credential",
                "runtime_support": ["claude", "codex"],
                "authentication": {"mode": "inferred"},
                "health_check": {"kind": "mcp-initialize"},
                "config": {
                    "type": "http",
                    "url": f"https://mcp.example.test/mcp?{query}",
                },
            },
        )


def test_mcp_spec_accepts_url_credential_environment_references_and_benign_query():
    url = (
        "https://${MCP_USER}:${MCP_PASSWORD}@mcp.example.test/mcp"
        "?access_token=${MCP_ACCESS_TOKEN}&format=json&tokenizer=v2"
    )
    spec = MCPServerSpec.from_catalog(
        "referenced-url",
        {
            "label": "Referenced URL",
            "runtime_support": ["claude", "codex"],
            "authentication": {"mode": "inferred"},
            "health_check": {"kind": "mcp-initialize"},
            "config": {"type": "http", "url": url},
        },
    )

    assert spec.url == url
    assert spec.environment_references == (
        "MCP_ACCESS_TOKEN",
        "MCP_PASSWORD",
        "MCP_USER",
    )


@pytest.mark.parametrize(
    "arguments",
    [
        ("serve", "--token", "fixed-value"),
        ("serve", "--api-key=fixed-value"),
        ("serve", "--access_token", "fixed-value"),
        ("serve", "--client-secret=fixed-value"),
        ("serve", "--githubToken", "fixed-value"),
        ("serve", "--private-key", "fixed-value"),
        ("serve", "--user", "alice:literal-password"),
        ("serve", "--user=alice:literal-password"),
        ("serve", "--proxy-user", "alice:literal-password"),
        ("serve", "-ualice:literal-password"),
    ],
)
def test_mcp_spec_rejects_literal_values_after_sensitive_stdio_flags(arguments):
    with pytest.raises(ValueError, match="credential flag.*environment reference"):
        MCPServerSpec.from_catalog(
            "argument-credential",
            {
                "label": "Argument credential",
                "runtime_support": ["claude", "codex"],
                "authentication": {"mode": "inferred"},
                "health_check": {"kind": "mcp-initialize"},
                "config": {
                    "type": "stdio",
                    "command": "server",
                    "args": list(arguments),
                },
            },
        )


@pytest.mark.parametrize(
    "arguments",
    [
        ("serve", "--header", "Authorization: Bearer fixed-value"),
        ("serve", "-H", "X-Auth: fixed-value"),
        ("serve", "-HX-API-Key: fixed-value"),
        ("serve", "--env", "API_TOKEN=fixed-value"),
        ("serve", "-eAUTH=fixed-value"),
        ("serve", "https://mcp.example.test?access_token=fixed-value"),
        ("serve", "--url=https://mcp.example.test?access_token=fixed-value"),
        ("serve", "--endpoint=https://mcp.example.test?private_key=fixed-value"),
        ("serve", "--header", "X-Whatever: Bearer literal-token"),
        ("serve", "-H", "X-Whatever: Basic dXNlcjpwYXNz"),
    ],
)
def test_mcp_spec_rejects_embedded_stdio_credentials(arguments):
    with pytest.raises(ValueError, match="environment reference"):
        MCPServerSpec.from_catalog(
            "embedded-credential",
            {
                "label": "Embedded credential",
                "runtime_support": ["claude", "codex"],
                "authentication": {"mode": "inferred"},
                "health_check": {"kind": "mcp-initialize"},
                "config": {
                    "type": "stdio",
                    "command": "server",
                    "args": list(arguments),
                },
            },
        )


def test_mcp_spec_accepts_stdio_flag_environment_references_and_benign_arguments():
    arguments = [
        "serve",
        "--token",
        "${MCP_TOKEN}",
        "--api-key=${MCP_API_KEY}",
        "--token-cache",
        "/tmp/mcp-token-cache",
        "--api-key-file",
        "/tmp/mcp-api-key",
        "--header",
        "Authorization: ${MCP_AUTH_HEADER}",
        "--user=${MCP_BASIC_AUTH}",
        "-u",
        "${MCP_PROXY_AUTH}",
        "--env",
        "SESSION_COOKIE=${MCP_COOKIE}",
        "--timeout",
        "30",
        "-url=https://mcp.example.test?format=json",
        "-use-feature",
        "-unsafe-mode",
    ]
    spec = MCPServerSpec.from_catalog(
        "referenced-arguments",
        {
            "label": "Referenced arguments",
            "runtime_support": ["claude", "codex"],
            "authentication": {"mode": "inferred"},
            "health_check": {"kind": "mcp-initialize"},
            "config": {
                "type": "stdio",
                "command": "server",
                "args": arguments,
            },
        },
    )

    assert spec.arguments == tuple(arguments)
    assert spec.environment_references == (
        "MCP_API_KEY",
        "MCP_AUTH_HEADER",
        "MCP_BASIC_AUTH",
        "MCP_COOKIE",
        "MCP_PROXY_AUTH",
        "MCP_TOKEN",
    )


def test_mcp_spec_rejects_malformed_url_percent_encoding():
    with pytest.raises(ValueError, match="invalid percent encoding"):
        MCPServerSpec.from_catalog(
            "malformed-url",
            {
                "label": "Malformed URL",
                "runtime_support": ["claude", "codex"],
                "authentication": {"mode": "inferred"},
                "health_check": {"kind": "mcp-initialize"},
                "config": {
                    "type": "http",
                    "url": "https://mcp.example.test/mcp?format=%ZZ",
                },
            },
        )


def test_every_catalog_mcp_definition_round_trips_declared_semantics(payload):
    from claude_kit import catalog

    document = catalog._load(payload, "mcp.yaml")
    for server_id, record in document["servers"].items():
        spec = MCPServerSpec.from_catalog(server_id, record)
        assert spec.runtime_support == set(record["runtime_support"])
        assert spec.authentication.value == record["authentication"]["mode"]
        assert spec.health_check == record["health_check"]["kind"]
        assert spec.semantic_metadata["runtime_support"] == sorted(
            record["runtime_support"]
        )
        assert spec.provider_config == record["config"]


def test_symbolic_reference_round_trips_without_provider_paths():
    ref = SymbolicRef.parse("agent://orchestrator")
    assert ref.kind is ReferenceKind.AGENT
    assert ref.id == "orchestrator"
    assert ref.uri == "agent://orchestrator"
    assert str(ref) == ref.uri

    with pytest.raises(ValueError, match="form kind://id"):
        SymbolicRef.parse(".claude/agents/orchestrator.md")
    with pytest.raises(ValueError, match="reference kind"):
        SymbolicRef.parse("cursor://orchestrator")


def test_agent_and_skill_specs_normalize_semantic_enums_and_refs():
    agent = AgentSpec(
        id="Review-Agent",
        description="Reviews changes.",
        instructions="Inspect the diff and report evidence.",
        model_tier="deep",  # type: ignore[arg-type]
        permission="workspace_write",  # type: ignore[arg-type]
        capabilities=frozenset({"filesystem.read", "filesystem.search", "delegation"}),  # type: ignore[arg-type]
        write_scope=("src/**",),
        isolation="preferred",  # type: ignore[arg-type]
        nested_delegation="allowed",  # type: ignore[arg-type]
        required_skills=("skill://security-review",),  # type: ignore[arg-type]
        references=("rule://quality-gates",),  # type: ignore[arg-type]
    )
    skill = SkillSpec(
        id="Review",
        description="Run an evidence-backed review.",
        instructions="Use the selected project checks.",
        invocation="explicit",  # type: ignore[arg-type]
    )

    assert agent.id == "review-agent"
    assert agent.model_tier is ModelTier.DEEP
    assert agent.permission is PermissionClass.WORKSPACE_WRITE
    assert agent.capabilities == frozenset(
        {Capability.FILE_READ, Capability.SEARCH, Capability.DELEGATE}
    )
    assert agent.write_scope == ("src/**",)
    assert agent.isolation is IsolationRequirement.PREFERRED
    assert agent.nested_delegation is NestedDelegationPolicy.ALLOWED
    assert agent.required_skills[0].uri == "skill://security-review"
    assert agent.references[0].uri == "rule://quality-gates"
    assert agent.ref.uri == "agent://review-agent"
    assert skill.invocation is InvocationMode.EXPLICIT
    assert skill.ref.uri == "skill://review"


def test_component_validation_rejects_invalid_permissions_and_paths():
    with pytest.raises(ValueError, match="read-only agent"):
        AgentSpec(
            id="writer",
            description="Writes files.",
            instructions="Change the project.",
            capabilities=frozenset({Capability.FILE_WRITE}),
        )

    with pytest.raises(ValueError, match="project-relative"):
        RuleSpec(
            id="security",
            description="Security requirements.",
            content="Validate inputs.",
            path_globs=("../outside/**",),
        )


def test_commands_and_hooks_use_semantic_invocation_and_handlers():
    command = CommandSpec(
        id="status",
        description="Show pipeline status.",
        instructions="Read the workflow ledger.",
    )
    hook = HookSpec(
        id="guard-secrets",
        description="Block likely credential writes.",
        event=HookEvent.PRE_TOOL,
        action=SymbolicRef.parse("handler://guard-secrets"),
        operation_matcher="filesystem.write",
        effect=HookEffect.BLOCKING,
        severity=HookSeverity.CRITICAL,
        data_access=("tool.input.file_path", "tool.input.content"),
    )

    assert command.invocation is InvocationMode.EXPLICIT
    assert hook.ref.uri == "hook://guard-secrets"
    assert hook.action.uri == "handler://guard-secrets"
    assert hook.severity is HookSeverity.CRITICAL

    with pytest.raises(ValueError, match="handler://"):
        HookSpec(
            id="bad-hook",
            description="Invalid handler type.",
            event=HookEvent.STOP,
            action=SymbolicRef.parse("command://status"),
        )


def test_workflow_validates_dependencies_reference_kinds_and_cycles():
    shape = WorkflowStage(
        id="shape",
        description="Shape the change.",
        agents=(SymbolicRef.parse("agent://planner"),),
        skills=(SymbolicRef.parse("skill://planning"),),
        gates=(SymbolicRef.parse("gate://scope-approved"),),
    )
    build = WorkflowStage(
        id="build",
        description="Implement the approved scope.",
        depends_on=("shape",),
    )
    workflow = WorkflowSpec(
        id="sdlc",
        description="Evidence-gated delivery.",
        stages=(shape, build),
    )
    assert tuple(stage.id for stage in workflow.stages) == ("shape", "build")
    assert workflow.ref.uri == "workflow://sdlc"

    with pytest.raises(ValueError, match="only agent references"):
        WorkflowStage(
            id="bad",
            description="Bad reference kind.",
            agents=(SymbolicRef.parse("skill://planning"),),
        )

    cycle_a = WorkflowStage(id="a", description="First.", depends_on=("b",))
    cycle_b = WorkflowStage(id="b", description="Second.", depends_on=("a",))
    with pytest.raises(ValueError, match="contain a cycle"):
        WorkflowSpec(
            id="cyclic",
            description="Invalid cyclic workflow.",
            stages=(cycle_a, cycle_b),
        )
