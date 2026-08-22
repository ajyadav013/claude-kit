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
