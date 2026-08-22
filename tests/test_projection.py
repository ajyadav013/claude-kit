"""Branch-free provider projection compiler contracts."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from claude_kit.components import Capability, MCPServerSpec, MCPTransport, SymbolicRef
from claude_kit.models import (
    GateDefinition,
    InstallRequest,
    ResolvedPlan,
    Selection,
    StateLayout,
    digest_gate_definitions,
)
from claude_kit.projection import (
    ProjectionCompiler,
    ProjectionFile,
    ProjectionPlan,
    Provider,
    ProviderSpec,
    RendererRegistry,
)


def _selection(*, profile: str = "lean") -> Selection:
    return Selection(
        frontend_framework="none",
        frontend_language="none",
        backend_language="python",
        backend_framework="none",
        database="none",
        profile=profile,
    )


def _plan(selection: Selection) -> ResolvedPlan:
    definition = GateDefinition("required", False, [])
    return ResolvedPlan(
        selection=selection,
        agents=["orchestrator"],
        skills=["sdlc"],
        overlay_rules=[],
        overlay_agents=[],
        hooks=["load-continuity"],
        gates=["scope-approved"],
        gate_definitions={"scope-approved": definition},
        gate_definition_digest=digest_gate_definitions(
            ["scope-approved"], {"scope-approved": definition}
        ),
        mcp_servers={},
        context={},
        stack_dirs={},
    )


@dataclass
class _Renderer:
    spec: ProviderSpec
    path: str

    def render(self, resolved_plan, request):
        return (
            ProjectionFile.text(
                provider=self.spec.provider,
                component=SymbolicRef.parse("agent://orchestrator"),
                path=self.path,
                content=f"{self.spec.provider.value}:{resolved_plan.agents[0]}\n",
            ),
        )


def _registry() -> RendererRegistry:
    return RendererRegistry(
        (
            _Renderer(
                ProviderSpec(
                    Provider.CLAUDE,
                    capabilities=frozenset({Capability.DELEGATE}),
                ),
                ".claude/agents/orchestrator.md",
            ),
            _Renderer(
                ProviderSpec(
                    Provider.CODEX,
                    rendering_version=2,
                    compatibility_catalog_version=3,
                    capabilities=frozenset({Capability.DELEGATE}),
                ),
                ".codex/agents/orchestrator.toml",
            ),
        )
    )


def test_compiler_projects_every_requested_provider_with_neutral_state():
    selection = _selection()
    request = InstallRequest(selection=selection, runtime="both")  # type: ignore[arg-type]
    compiled = ProjectionCompiler(_registry()).compile(_plan(selection), request)

    assert compiled.providers == (Provider.CLAUDE, Provider.CODEX)
    assert compiled.state_layout == StateLayout.neutral()
    assert [item.path for item in compiled.files] == [
        ".claude/agents/orchestrator.md",
        ".codex/agents/orchestrator.toml",
    ]
    assert compiled.files_for("codex")[0].text_content == "codex:orchestrator\n"
    assert compiled.rendering_versions == {"claude": 1, "codex": 2}
    assert compiled.compatibility_catalog_versions == {"claude": 1, "codex": 3}


def test_compiler_rejects_request_for_a_different_resolved_selection():
    plan_selection = _selection()
    request = InstallRequest(
        selection=_selection(profile="enterprise"), runtime="codex"
    )  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="selection must match"):
        ProjectionCompiler(_registry()).compile(_plan(plan_selection), request)


def test_compiler_rejects_incompatible_mcp_before_invoking_renderers():
    selection = _selection()
    plan = _plan(selection)
    spec = MCPServerSpec(
        id="claude-only",
        label="Claude-only test server",
        transport=MCPTransport.STDIO,
        command="server",
        runtime_support=frozenset({"claude"}),
    )
    plan.mcp_server_specs = {spec.id: spec}
    plan.mcp_servers = {spec.id: spec.provider_config}
    invoked: list[str] = []

    @dataclass
    class CountingRenderer(_Renderer):
        def render(self, resolved_plan, request):
            invoked.append(self.spec.provider.value)
            return super().render(resolved_plan, request)

    registry = RendererRegistry(
        (
            CountingRenderer(
                ProviderSpec(Provider.CLAUDE), ".claude/agents/orchestrator.md"
            ),
            CountingRenderer(
                ProviderSpec(Provider.CODEX), ".codex/agents/orchestrator.toml"
            ),
        )
    )

    with pytest.raises(ValueError, match="claude-only lacks codex"):
        ProjectionCompiler(registry).compile(
            plan, InstallRequest(selection=selection, runtime="both")
        )
    assert invoked == []


def test_compiler_requires_registered_concrete_provider():
    selection = _selection()
    request = InstallRequest(selection=selection, runtime="codex")  # type: ignore[arg-type]
    claude_only = RendererRegistry(
        (
            _Renderer(
                ProviderSpec(Provider.CLAUDE),
                ".claude/agents/orchestrator.md",
            ),
        )
    )
    with pytest.raises(ValueError, match="no renderer registered.*codex"):
        ProjectionCompiler(claude_only).compile(_plan(selection), request)


def test_compiler_rejects_wrong_provider_and_destination_collisions():
    selection = _selection()
    request = InstallRequest(selection=selection, runtime="claude")  # type: ignore[arg-type]

    wrong = _Renderer(ProviderSpec(Provider.CLAUDE), ".claude/agents/orchestrator.md")

    def wrong_render(resolved_plan, install_request):
        return (
            ProjectionFile.text(
                provider=Provider.CODEX,
                component=SymbolicRef.parse("agent://orchestrator"),
                path=".codex/agents/orchestrator.toml",
                content="wrong",
            ),
        )

    wrong.render = wrong_render  # type: ignore[method-assign]
    with pytest.raises(ValueError, match="emitted a codex projection"):
        ProjectionCompiler(RendererRegistry((wrong,))).compile(
            _plan(selection), request
        )

    duplicate = ProjectionFile.text(
        provider=Provider.CLAUDE,
        component=SymbolicRef.parse("agent://orchestrator"),
        path="agents/orchestrator.md",
        content="same destination",
    )
    with pytest.raises(ValueError, match="duplicate destination paths"):
        ProjectionPlan(
            providers=(Provider.CLAUDE,),
            provider_specs=(ProviderSpec(Provider.CLAUDE),),
            files=(duplicate, duplicate),
        )


def test_projection_file_paths_and_fresh_state_fail_closed():
    with pytest.raises(ValueError, match="escapes"):
        ProjectionFile.text(
            provider=Provider.CODEX,
            component=SymbolicRef.parse("artifact://manifest"),
            path="../plugin.json",
            content="{}",
        )

    with pytest.raises(ValueError, match="StateLayout.neutral"):
        ProjectionPlan(
            providers=(Provider.CODEX,),
            provider_specs=(ProviderSpec(Provider.CODEX),),
            files=(),
            state_layout=StateLayout.legacy_claude(),
        )


def test_registry_rejects_accidental_provider_replacement():
    registry = RendererRegistry()
    renderer = _Renderer(ProviderSpec(Provider.CODEX), "codex/plugin.json")
    registry.register(renderer)
    with pytest.raises(ValueError, match="already registered"):
        registry.register(renderer)
