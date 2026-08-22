"""Provider projection contracts and branch-free compilation.

Catalog resolution remains unaware of native hosts.  A
:class:`ProjectionCompiler` receives the already-resolved logical plan and asks
the renderers registered for the installation request's concrete providers to
produce files.  This keeps Claude/Codex differences at one adapter boundary.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from pathlib import PurePosixPath
from typing import Iterable, Optional, Protocol, Union, runtime_checkable

from claude_kit.components import Capability, SymbolicRef
from claude_kit.mcp import require_runtime_support
from claude_kit.models import (
    InstallRequest,
    ResolvedPlan,
    StateLayout,
    contained_relpath,
)


class Provider(str, Enum):
    """Concrete native hosts supported by the projection seam."""

    CLAUDE = "claude"
    CODEX = "codex"

    @classmethod
    def parse(cls, value: Union[str, Provider]) -> Provider:
        """Return a concrete provider, rejecting installation-mode aliases."""
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).strip().lower())
        except ValueError as exc:
            allowed = ", ".join(provider.value for provider in cls)
            raise ValueError(f"provider must be one of: {allowed}") from exc


class ProjectionOwner(str, Enum):
    """Upgrade ownership policy for a rendered artifact."""

    KIT = "kit"
    OVERLAY = "overlay"
    USER_EDITABLE = "user-editable"


@dataclass(frozen=True)
class ProviderSpec:
    """Versioned capabilities exposed by one concrete provider renderer."""

    provider: Provider
    rendering_version: int = 1
    compatibility_catalog_version: int = 1
    capabilities: frozenset[Capability] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", Provider.parse(self.provider))
        for name in ("rendering_version", "compatibility_catalog_version"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        capabilities = frozenset(
            value if isinstance(value, Capability) else Capability(value)
            for value in self.capabilities
        )
        object.__setattr__(self, "capabilities", capabilities)


@dataclass(frozen=True)
class ProjectionFile:
    """One validated file emitted by a provider renderer."""

    provider: Provider
    component: SymbolicRef
    path: str
    content: bytes
    owner: ProjectionOwner = ProjectionOwner.KIT
    executable: bool = False
    media_type: str = "text/plain"

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", Provider.parse(self.provider))
        object.__setattr__(self, "component", SymbolicRef.coerce(self.component))
        path = contained_relpath(self.path)
        if path in {".", ""} or PurePosixPath(path).name in {".", ".."}:
            raise ValueError(
                "projection file path must identify a project-relative file"
            )
        object.__setattr__(self, "path", path)
        if isinstance(self.content, str):
            object.__setattr__(self, "content", self.content.encode("utf-8"))
        elif not isinstance(self.content, bytes):
            raise ValueError("projection file content must be bytes")
        try:
            owner = (
                self.owner
                if isinstance(self.owner, ProjectionOwner)
                else ProjectionOwner(self.owner)
            )
        except ValueError as exc:
            allowed = ", ".join(owner.value for owner in ProjectionOwner)
            raise ValueError(
                f"projection file owner must be one of: {allowed}"
            ) from exc
        object.__setattr__(self, "owner", owner)
        if not isinstance(self.executable, bool):
            raise ValueError("projection file executable must be a boolean")
        if not isinstance(self.media_type, str) or not self.media_type.strip():
            raise ValueError("projection file media_type must be a non-empty string")
        object.__setattr__(self, "media_type", self.media_type.strip())

    @classmethod
    def text(
        cls,
        *,
        provider: Provider,
        component: SymbolicRef,
        path: str,
        content: str,
        owner: ProjectionOwner = ProjectionOwner.KIT,
        executable: bool = False,
        media_type: str = "text/plain",
    ) -> ProjectionFile:
        """Construct a UTF-8 projection file without encoding at call sites."""
        if not isinstance(content, str):
            raise ValueError("text projection content must be a string")
        return cls(
            provider=provider,
            component=component,
            path=path,
            content=content.encode("utf-8"),
            owner=owner,
            executable=executable,
            media_type=media_type,
        )

    @property
    def sha256(self) -> str:
        """Stable content digest used by install and upgrade manifests."""
        return hashlib.sha256(self.content).hexdigest()

    @property
    def text_content(self) -> str:
        """Decode textual content for assertions and format-specific validation."""
        return self.content.decode("utf-8")


@dataclass(frozen=True)
class ProjectionPlan:
    """Deterministic output for every concrete provider in one install request."""

    providers: tuple[Provider, ...]
    provider_specs: tuple[ProviderSpec, ...]
    files: tuple[ProjectionFile, ...]
    state_layout: StateLayout = field(default_factory=StateLayout.neutral)

    def __post_init__(self) -> None:
        providers = tuple(Provider.parse(provider) for provider in self.providers)
        if not providers:
            raise ValueError("projection plan must contain at least one provider")
        if len(set(providers)) != len(providers):
            raise ValueError("projection plan providers must be unique")
        object.__setattr__(self, "providers", providers)

        specs = tuple(self.provider_specs)
        if any(not isinstance(spec, ProviderSpec) for spec in specs):
            raise ValueError("provider_specs must contain ProviderSpec records")
        if tuple(spec.provider for spec in specs) != providers:
            raise ValueError("provider_specs must match projection providers in order")
        object.__setattr__(self, "provider_specs", specs)

        files = tuple(self.files)
        if any(not isinstance(item, ProjectionFile) for item in files):
            raise ValueError("files must contain ProjectionFile records")
        unexpected = {item.provider for item in files} - set(providers)
        if unexpected:
            names = ", ".join(sorted(item.value for item in unexpected))
            raise ValueError(f"projection files contain unselected providers: {names}")
        paths = [item.path for item in files]
        if len(set(paths)) != len(paths):
            raise ValueError("projection plan contains duplicate destination paths")
        object.__setattr__(self, "files", files)

        if self.state_layout != StateLayout.neutral():
            raise ValueError("fresh projection plans must use StateLayout.neutral()")

    @property
    def compatibility_catalog_versions(self) -> dict[str, int]:
        """Provider versions ready to persist in ``init-options.json``."""
        return {
            spec.provider.value: spec.compatibility_catalog_version
            for spec in self.provider_specs
        }

    @property
    def rendering_versions(self) -> dict[str, int]:
        """Renderer contract versions keyed by concrete provider id."""
        return {
            spec.provider.value: spec.rendering_version for spec in self.provider_specs
        }

    def files_for(self, provider: Union[str, Provider]) -> tuple[ProjectionFile, ...]:
        """Return the files emitted for one selected provider."""
        concrete = Provider.parse(provider)
        if concrete not in self.providers:
            raise ValueError(f"provider {concrete.value!r} is not selected")
        return tuple(item for item in self.files if item.provider is concrete)


@runtime_checkable
class ProviderRenderer(Protocol):
    """Adapter contract implemented by each concrete native host renderer."""

    @property
    def spec(self) -> ProviderSpec:
        """Return the renderer's versioned provider declaration."""
        ...

    def render(
        self, resolved_plan: ResolvedPlan, request: InstallRequest
    ) -> Iterable[ProjectionFile]:
        """Render selected logical components without re-resolving the catalog."""
        ...


class RendererRegistry:
    """Explicit renderer registry used as the compiler's only provider branch."""

    def __init__(self, renderers: Iterable[ProviderRenderer] = ()) -> None:
        self._renderers: dict[Provider, ProviderRenderer] = {}
        for renderer in renderers:
            self.register(renderer)

    def register(
        self, renderer: ProviderRenderer, *, replace: bool = False
    ) -> ProviderRenderer:
        """Register ``renderer`` and reject accidental provider replacement."""
        if not isinstance(renderer.spec, ProviderSpec):
            raise ValueError("renderer spec must be a ProviderSpec")
        provider = renderer.spec.provider
        if provider in self._renderers and not replace:
            raise ValueError(f"renderer already registered for {provider.value}")
        self._renderers[provider] = renderer
        return renderer

    def get(self, provider: Union[str, Provider]) -> ProviderRenderer:
        """Return a renderer or fail with an actionable provider diagnostic."""
        concrete = Provider.parse(provider)
        try:
            return self._renderers[concrete]
        except KeyError as exc:
            raise ValueError(
                f"no renderer registered for provider {concrete.value!r}"
            ) from exc

    @property
    def providers(self) -> tuple[Provider, ...]:
        """Registered provider ids in deterministic order."""
        return tuple(sorted(self._renderers, key=lambda provider: provider.value))


DEFAULT_RENDERER_REGISTRY = RendererRegistry()


class ProjectionCompiler:
    """Compile one logical plan into all providers selected by an install request."""

    def __init__(self, registry: Optional[RendererRegistry] = None) -> None:
        self._registry = registry or DEFAULT_RENDERER_REGISTRY

    def compile(
        self, resolved_plan: ResolvedPlan, request: InstallRequest
    ) -> ProjectionPlan:
        """Render a logical plan without catalog lookups or provider conditionals."""
        if not isinstance(resolved_plan, ResolvedPlan):
            raise ValueError("resolved_plan must be a ResolvedPlan")
        if not isinstance(request, InstallRequest):
            raise ValueError("request must be an InstallRequest")
        if resolved_plan.selection != request.selection:
            raise ValueError(
                "install request selection must match the resolved plan selection"
            )

        providers = tuple(Provider.parse(value) for value in request.runtimes)
        require_runtime_support(
            resolved_plan.mcp_server_specs,
            (provider.value for provider in providers),
        )
        specs: list[ProviderSpec] = []
        files: list[ProjectionFile] = []
        destinations: dict[str, ProjectionFile] = {}

        for provider in providers:
            renderer = self._registry.get(provider)
            spec = renderer.spec
            if spec.provider is not provider:
                raise ValueError(
                    f"renderer registered for {provider.value} declares "
                    f"{spec.provider.value}"
                )
            specs.append(spec)
            rendered = renderer.render(resolved_plan, request)
            if isinstance(rendered, (str, bytes)):
                raise ValueError(
                    f"renderer for {provider.value} must return ProjectionFile records"
                )
            for item in rendered:
                if not isinstance(item, ProjectionFile):
                    raise ValueError(
                        f"renderer for {provider.value} returned a non-ProjectionFile"
                    )
                if item.provider is not provider:
                    raise ValueError(
                        f"renderer for {provider.value} emitted a "
                        f"{item.provider.value} projection file"
                    )
                previous = destinations.get(item.path)
                if previous is not None:
                    raise ValueError(
                        f"projection destination collision at {item.path!r} between "
                        f"{previous.provider.value} and {item.provider.value}"
                    )
                destinations[item.path] = item
                files.append(item)

        provider_order = {provider: index for index, provider in enumerate(providers)}
        files.sort(key=lambda item: (provider_order[item.provider], item.path))
        return ProjectionPlan(
            providers=providers,
            provider_specs=tuple(specs),
            files=tuple(files),
            state_layout=StateLayout.neutral(),
        )


__all__ = [
    "DEFAULT_RENDERER_REGISTRY",
    "ProjectionCompiler",
    "ProjectionFile",
    "ProjectionOwner",
    "ProjectionPlan",
    "Provider",
    "ProviderRenderer",
    "ProviderSpec",
    "RendererRegistry",
]
