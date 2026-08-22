"""Provider-aware staged rendering and transactional installation.

This is the native-runtime install spine.  Catalog resolution has already
finished when it receives a :class:`ResolvedPlan`; the module compiles the
selected Claude/Codex projections once, validates them before mutation, and
commits every provider surface together with one neutral ``.ckit`` control
plane.

The legacy :func:`claude_kit.scaffold.install_sdlc` remains available during the
compatibility window.  New CLI runtime installs use this module.
"""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml

try:  # pragma: no cover - Python 3.11+ takes the first branch
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.9/3.10 dependency
    import tomli as tomllib  # type: ignore[no-redef]

from claude_kit import __version__, detect
from claude_kit.claude_renderer import ClaudeRenderer
from claude_kit.models import (
    FileRecord,
    InitOptions,
    InstallRequest,
    ResolvedPlan,
    Runtime,
    StateLayout,
)
from claude_kit.projection import (
    ProjectionCompiler,
    ProjectionFile,
    ProjectionPlan,
    RendererRegistry,
)
from claude_kit.provider_renderers import CodexRenderer
from claude_kit.secure_fs import ProjectFS, ProjectTransaction

_AGENTS_START = "<!-- ckit:managed:start -->"
_AGENTS_END = "<!-- ckit:managed:end -->"
_TOML_START = "# ckit:managed:start"
_TOML_END = "# ckit:managed:end"
_AGENTS_MAX_BYTES = 32 * 1024
_SIDECAR_SUFFIX = ".claude-kit"
_PROTECTED_PATHS = (
    ".ckit",
    ".claude",
    ".codex",
    ".agents",
    "CLAUDE.md",
    "CLAUDE.md.claude-kit",
    "AGENTS.md",
    "AGENTS.md.claude-kit",
    "README.claude-sdlc.md",
    "README.claude-sdlc.md.claude-kit",
    ".mcp.json",
    ".mcp.json.claude-kit",
    ".mcp.lock.json",
    ".gitignore",
)
_GITIGNORE_ENTRIES = (
    ".ckit/state/*",
    "!.ckit/state/.gitkeep",
    ".ckit/tmp/*",
    "!.ckit/tmp/.gitkeep",
    ".ckit/config/upgrade-in-progress.json",
    ".ckit.bak-*/",
    ".claude.bak-*/",
    ".codex.bak-*/",
    ".agents.bak-*/",
    ".claude-kit-txn-*/",
    "*.claude-kit",
    "*.codex-kit",
)


class RuntimeInstallError(RuntimeError):
    """A provider projection or live merge could not be installed safely."""


@dataclass(frozen=True)
class RuntimeArtifact:
    """A provider or shared file ready for validated installation."""

    path: str
    content: bytes
    provider: str
    component_id: str
    owner: str
    executable: bool = False

    @classmethod
    def from_projection(cls, item: ProjectionFile) -> RuntimeArtifact:
        return cls(
            path=item.path,
            content=item.content,
            provider=item.provider.value,
            component_id=item.component.uri,
            owner=item.owner.value,
            executable=item.executable,
        )


def compile_runtime_projection(
    source: Path,
    plan: ResolvedPlan,
    request: InstallRequest,
) -> ProjectionPlan:
    """Compile the selected providers from one already-resolved logical plan."""

    registry = RendererRegistry((ClaudeRenderer(source), CodexRenderer(source)))
    try:
        projection = ProjectionCompiler(registry).compile(plan, request)
    except ValueError as exc:
        raise RuntimeInstallError(f"native projection is incompatible: {exc}") from exc
    validate_projection(projection)
    return projection


def _frontmatter(document: str, *, path: str) -> dict[str, Any]:
    lines = document.splitlines()
    if not lines or lines[0].strip() != "---":
        raise RuntimeInstallError(f"{path} has no YAML frontmatter")
    try:
        end = lines[1:].index("---") + 1
    except ValueError as exc:
        raise RuntimeInstallError(f"{path} has unterminated YAML frontmatter") from exc
    parsed = yaml.safe_load("\n".join(lines[1:end]))
    if not isinstance(parsed, dict):
        raise RuntimeInstallError(f"{path} frontmatter is not a mapping")
    return parsed


def validate_projection(projection: ProjectionPlan) -> None:
    """Strictly validate native syntax and cross-provider leakage before mutation."""

    paths = {item.path for item in projection.files}
    for provider in projection.providers:
        if not projection.files_for(provider):
            raise RuntimeInstallError(
                f"{provider.value} renderer produced no native configuration"
            )
    if "AGENTS.md" in paths:
        agents = next(item for item in projection.files if item.path == "AGENTS.md")
        if len(agents.content) >= _AGENTS_MAX_BYTES:
            raise RuntimeInstallError(
                "generated AGENTS.md exceeds Codex's 32 KiB budget"
            )

    for item in projection.files:
        try:
            text = item.text_content
        except UnicodeDecodeError as exc:
            raise RuntimeInstallError(
                f"native configuration must be UTF-8 text: {item.path}"
            ) from exc
        if item.path.endswith(".json"):
            try:
                json.loads(text)
            except json.JSONDecodeError as exc:
                raise RuntimeInstallError(
                    f"invalid JSON in {item.path}: {exc}"
                ) from exc
        if item.path.endswith(".toml"):
            try:
                document = tomllib.loads(text)
            except tomllib.TOMLDecodeError as exc:
                raise RuntimeInstallError(
                    f"invalid TOML in {item.path}: {exc}"
                ) from exc
            if item.path.startswith(".codex/agents/"):
                missing = {
                    "name",
                    "description",
                    "developer_instructions",
                } - set(document)
                if missing:
                    raise RuntimeInstallError(
                        f"{item.path} is missing required Codex agent fields: "
                        + ", ".join(sorted(missing))
                    )
        if item.path.endswith("/SKILL.md"):
            metadata = _frontmatter(text, path=item.path)
            if not all(
                isinstance(metadata.get(key), str) and metadata[key].strip()
                for key in ("name", "description")
            ):
                raise RuntimeInstallError(
                    f"{item.path} requires non-empty name and description"
                )
        if item.provider == "codex" and re.search(
            r"CLAUDE_CODE_|CLAUDE_PROJECT_DIR|\.claude(?:/|\\)", text
        ):
            raise RuntimeInstallError(f"Claude operational leakage in {item.path}")
        if item.provider == "claude" and ".codex/" in text:
            raise RuntimeInstallError(f"Codex operational leakage in {item.path}")


def _neutral_continuity(source: Path) -> str:
    text = (source / "templates" / "CONTINUITY.template.md").read_text(encoding="utf-8")
    replacements = (
        (".claude/CONTINUITY.md", ".ckit/CONTINUITY.md"),
        (".claude/state/", ".ckit/state/"),
        (".claude/agent-memory/", ".ckit/agent-memory/"),
        (
            "See `.claude/rules/continuity.md`.",
            "Follow the active host's continuity guidance.",
        ),
    )
    for old, new in replacements:
        text = text.replace(old, new)
    return text


def _stack_snapshot(plan: ResolvedPlan, request: InstallRequest) -> bytes:
    document = {
        "schema_version": 1,
        "selection": plan.selection.to_dict(),
        "runtimes": list(request.runtimes),
        "agents": plan.agents,
        "skills": plan.skills,
        "overlay_rules": plan.overlay_rules,
        "overlay_agents": plan.overlay_agents,
        "hooks": plan.hooks,
        "gates": plan.gates,
        "gate_definitions": {
            gate: definition.to_dict()
            for gate, definition in plan.gate_definitions.items()
        },
        "gate_definition_digest": plan.gate_definition_digest,
        "mcp": list(plan.mcp_servers),
        "mcp_semantics": plan.mcp_semantics,
        "org": plan.org.to_dict() if plan.org else None,
        "detected_commands": plan.detected_commands or {},
    }
    return yaml.safe_dump(document, sort_keys=False).encode("utf-8")


def _shared_artifacts(
    source: Path, plan: ResolvedPlan, request: InstallRequest
) -> list[RuntimeArtifact]:
    layout = StateLayout.neutral()
    output = [
        RuntimeArtifact(
            path=layout.stack_snapshot,
            content=_stack_snapshot(plan, request),
            provider="shared",
            component_id="state://stack-snapshot",
            owner="kit",
        ),
        RuntimeArtifact(
            path=layout.continuity,
            content=_neutral_continuity(source).encode("utf-8"),
            provider="shared",
            component_id="state://continuity",
            owner="user-editable",
        ),
        RuntimeArtifact(
            path=f"{layout.state}/.gitkeep",
            content=b"",
            provider="shared",
            component_id="state://pipeline",
            owner="kit",
        ),
        RuntimeArtifact(
            path=f"{layout.temporary}/.gitkeep",
            content=b"",
            provider="shared",
            component_id="state://temporary",
            owner="kit",
        ),
    ]
    memory = source / "templates" / "agent-memory"
    for path in sorted(memory.rglob("*")):
        if path.is_file():
            relative = path.relative_to(memory).as_posix()
            output.append(
                RuntimeArtifact(
                    path=f"{layout.memory}/{relative}",
                    content=path.read_bytes(),
                    provider="shared",
                    component_id="state://memory",
                    owner="user-editable",
                )
            )
    templates = source / "templates" / "artifacts"
    for path in sorted(templates.rglob("*")):
        if path.is_file():
            relative = path.relative_to(templates).as_posix()
            output.append(
                RuntimeArtifact(
                    path=f"{layout.artifacts}/templates/{relative}",
                    content=path.read_bytes(),
                    provider="shared",
                    component_id="artifact://templates",
                    owner="kit",
                )
            )
    scripts = source / "templates" / "scripts"
    for path in sorted(scripts.rglob("*")):
        if path.is_file():
            relative = path.relative_to(scripts).as_posix()
            output.append(
                RuntimeArtifact(
                    path=f".ckit/scripts/{relative}",
                    content=path.read_bytes(),
                    provider="shared",
                    component_id="artifact://runtime-scripts",
                    owner="kit",
                    executable=True,
                )
            )
    return output


def _prepared_plan(plan: ResolvedPlan, target: Path) -> ResolvedPlan:
    prepared = deepcopy(plan)
    prepared.context["project_name"] = target.name
    if prepared.selection.detect_commands:
        overrides = detect.detect_commands(target, prepared.selection)
        if overrides:
            prepared.context.update(overrides)
        prepared.detected_commands = overrides
    return prepared


def render_runtime_artifacts(
    source: Path,
    target: Path,
    plan: ResolvedPlan,
    request: InstallRequest,
) -> tuple[ProjectionPlan, tuple[RuntimeArtifact, ...]]:
    """Render and validate all provider plus shared artifacts without mutation."""

    prepared = _prepared_plan(plan, target)
    prepared_request = InstallRequest(
        selection=prepared.selection, runtime=request.runtime
    )
    projection = compile_runtime_projection(source, prepared, prepared_request)
    artifacts = [RuntimeArtifact.from_projection(item) for item in projection.files]
    artifacts.extend(_shared_artifacts(source, prepared, prepared_request))
    paths = [item.path for item in artifacts]
    if len(paths) != len(set(paths)):
        duplicates = sorted({path for path in paths if paths.count(path) > 1})
        raise RuntimeInstallError(
            "shared/provider projection collision: " + ", ".join(duplicates)
        )
    return projection, tuple(sorted(artifacts, key=lambda item: item.path))


def _strip_managed(text: str, start: str, end: str) -> tuple[str, bool]:
    if start not in text and end not in text:
        return text, False
    if text.count(start) != 1 or text.count(end) != 1:
        raise RuntimeInstallError("managed section markers are malformed or duplicated")
    before, remainder = text.split(start, 1)
    _managed, after = remainder.split(end, 1)
    return (before.rstrip() + "\n" + after.lstrip()).strip(), True


def _merge_agents(existing: str, generated: str) -> str:
    base, _had_managed = _strip_managed(existing, _AGENTS_START, _AGENTS_END)
    rendered = generated.rstrip()

    def compose(managed: str) -> str:
        block = f"{_AGENTS_START}\n{managed}\n{_AGENTS_END}"
        return f"{base.rstrip()}\n\n{block}\n" if base.strip() else block + "\n"

    merged = compose(rendered)
    if len(merged.encode("utf-8")) >= _AGENTS_MAX_BYTES:
        # A fresh Codex projection intentionally uses most of the instruction budget to inline
        # selected rules. Existing project prose has higher ownership: retain the workflow/roles/
        # gates prefix, omit only the inline rule bodies, and point at the complete shared files.
        # This also converts an unedited legacy generic AGENTS export without discarding it.
        heading = "\n# Selected engineering rules\n"
        prefix, separator, _rules = rendered.partition(heading)
        if separator:
            rendered = (
                prefix.rstrip()
                + heading
                + "\nInline rule bodies are omitted here to preserve existing project instructions "
                "within Codex's 32 KiB default budget. The complete selected projections remain "
                "under `.ckit/rules/`; load the relevant rule before acting.\n"
            )
            merged = compose(rendered.rstrip())
    if len(merged.encode("utf-8")) >= _AGENTS_MAX_BYTES:
        raise RuntimeInstallError(
            "preserved AGENTS.md plus managed Codex instructions exceeds 32 KiB; "
            "shorten the user-owned prose before installing"
        )
    return merged


def _merge_codex_toml(existing: str, generated: str) -> str:
    base, _had_managed = _strip_managed(existing, _TOML_START, _TOML_END)
    try:
        base_doc = tomllib.loads(base) if base.strip() else {}
        generated_doc = tomllib.loads(generated)
    except tomllib.TOMLDecodeError as exc:
        raise RuntimeInstallError(
            f"cannot merge invalid .codex/config.toml: {exc}"
        ) from exc
    existing_servers = base_doc.get("mcp_servers", {})
    generated_servers = generated_doc.get("mcp_servers", {})
    if not isinstance(existing_servers, dict) or not isinstance(
        generated_servers, dict
    ):
        raise RuntimeInstallError("mcp_servers must be TOML tables")
    duplicates = set(existing_servers) & set(generated_servers)
    if duplicates:
        raise RuntimeInstallError(
            "duplicate MCP definitions in user and generated Codex config: "
            + ", ".join(sorted(duplicates))
        )
    block = f"{_TOML_START}\n{generated.rstrip()}\n{_TOML_END}"
    merged = f"{base.rstrip()}\n\n{block}\n" if base.strip() else block + "\n"
    try:
        tomllib.loads(merged)
    except tomllib.TOMLDecodeError as exc:  # pragma: no cover - defensive invariant
        raise RuntimeInstallError(
            f"merged .codex/config.toml is invalid: {exc}"
        ) from exc
    return merged


def _old_records(fs: ProjectFS) -> dict[str, FileRecord]:
    for rel in (
        StateLayout.neutral().manifest,
        StateLayout.legacy_claude().manifest,
    ):
        if not fs.is_file(rel):
            continue
        try:
            options = InitOptions.from_dict(json.loads(fs.read_text(rel)))
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise RuntimeInstallError(
                f"existing init-options is corrupt: {exc}"
            ) from exc
        return {record.path: record for record in options.files}
    return {}


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _write_artifact(
    fs: ProjectFS,
    artifact: RuntimeArtifact,
    *,
    old_records: dict[str, FileRecord],
    force: bool,
    log: list[str],
) -> tuple[str, bytes] | None:
    path = artifact.path
    content = artifact.content
    mode = 0o755 if artifact.executable else 0o644
    exists = fs.is_file(path)

    if path == "AGENTS.md":
        generated = content.decode("utf-8")
        if exists and not force:
            rendered = _merge_agents(fs.read_text(path), generated)
        else:
            rendered = f"{_AGENTS_START}\n{generated.rstrip()}\n{_AGENTS_END}\n"
        content = rendered.encode("utf-8")
        fs.write_bytes(path, content, mode=mode)
        message = (
            "  • AGENTS.md managed instructions updated; user prose preserved"
            if exists and not force
            else "  • AGENTS.md"
        )
        log.append(message)
        return path, content
    if path == ".codex/config.toml":
        generated = content.decode("utf-8")
        if exists and not force:
            rendered = _merge_codex_toml(fs.read_text(path), generated)
        else:
            rendered = f"{_TOML_START}\n{generated.rstrip()}\n{_TOML_END}\n"
        content = rendered.encode("utf-8")
        fs.write_bytes(path, content, mode=mode)
        message = (
            "  • .codex/config.toml merged; unknown keys/comments preserved"
            if exists and not force
            else "  • .codex/config.toml"
        )
        log.append(message)
        return path, content

    if exists and not force:
        current = fs.read_bytes(path)
        if current == content:
            return path, content
        if path == StateLayout.neutral().continuity:
            log.append(f"  • preserved live working memory {path}")
            return None
        previous = old_records.get(path)
        safe_to_refresh = (
            previous is not None
            and previous.owner != "user-editable"
            and previous.sha256 == _sha256(current)
        )
        if artifact.owner == "user-editable" or not safe_to_refresh:
            if path.startswith(".ckit/agent-memory/"):
                log.append(f"  • preserved user memory {path}")
                return None
            sidecar = path + _SIDECAR_SUFFIX
            fs.write_bytes(sidecar, content, mode=mode)
            log.append(f"  • preserved {path}; wrote {sidecar}")
            return sidecar, content

    fs.write_bytes(path, content, mode=mode)
    log.append(f"  • {path}")
    return path, content


def _merge_gitignore(fs: ProjectFS, log: list[str]) -> None:
    existing = (
        fs.read_text(".gitignore").splitlines() if fs.is_file(".gitignore") else []
    )
    missing = [entry for entry in _GITIGNORE_ENTRIES if entry not in set(existing)]
    if not missing:
        return
    lines = list(existing)
    if lines and lines[-1].strip():
        lines.append("")
    lines.append("# ckit shared runtime state and recoverable sidecars")
    lines.extend(missing)
    fs.write_text(".gitignore", "\n".join(lines) + "\n")
    log.append(f"  • .gitignore (+{len(missing)} entries)")


def _manifest(
    plan: ResolvedPlan,
    projection: ProjectionPlan,
    installed: Iterable[tuple[RuntimeArtifact, str, bytes]],
    *,
    preserved_records: Iterable[FileRecord] = (),
) -> bytes:
    records = [
        FileRecord(
            path=path,
            sha256=_sha256(content),
            owner=artifact.owner,
            provider=artifact.provider,
            component_id=artifact.component_id,
        )
        for artifact, path, content in installed
    ]
    installed_paths = {record.path for record in records}
    records.extend(
        record
        for record in preserved_records
        if record.path not in installed_paths
        and record.provider == "shared"
        and record.path.startswith(StateLayout.neutral().root + "/")
    )
    options = InitOptions(
        claude_kit_version=__version__,
        selection=plan.selection,
        files=sorted(records, key=lambda record: record.path),
        runtimes=[provider.value for provider in projection.providers],
        state_layout=StateLayout.neutral(),
        rendering_version=max(projection.rendering_versions.values()),
        compatibility_catalog_versions=projection.compatibility_catalog_versions,
    )
    return (json.dumps(options.to_dict(), indent=2) + "\n").encode("utf-8")


def preview_runtime_install(
    source: Path,
    target: Path,
    plan: ResolvedPlan,
    request: InstallRequest,
) -> tuple[ProjectionPlan, list[str]]:
    """Return the exact fresh-install provider/shared inventory without mutation."""

    projection, artifacts = render_runtime_artifacts(source, target, plan, request)
    paths = [artifact.path for artifact in artifacts]
    paths.extend([StateLayout.neutral().manifest, ".gitignore"])
    return projection, sorted(set(paths))


def _apply_runtime_files(
    fs: ProjectFS,
    plan: ResolvedPlan,
    projection: ProjectionPlan,
    artifacts: Iterable[RuntimeArtifact],
    *,
    force: bool,
    old_records: dict[str, FileRecord] | None = None,
) -> list[str]:
    """Apply a prevalidated projection while an encompassing transaction is held."""

    log: list[str] = []
    previous = old_records if old_records is not None else _old_records(fs)
    installed: list[tuple[RuntimeArtifact, str, bytes]] = []
    for artifact in artifacts:
        result = _write_artifact(
            fs,
            artifact,
            old_records=previous,
            force=force,
            log=log,
        )
        if result is not None:
            path, content = result
            installed.append((artifact, path, content))
    _merge_gitignore(fs, log)
    manifest = _manifest(
        plan,
        projection,
        installed,
        preserved_records=(
            record for record in previous.values() if fs.is_file(record.path)
        ),
    )
    fs.write_bytes(StateLayout.neutral().manifest, manifest)
    # Re-parse the durable contract before the encompassing transaction commits.
    InitOptions.from_dict(json.loads(fs.read_text(StateLayout.neutral().manifest)))
    log.append("  • .ckit/config/init-options.json")
    return log


def install_runtime(
    source: Path,
    target: Path,
    plan: ResolvedPlan,
    request: InstallRequest,
    *,
    force: bool = False,
) -> list[str]:
    """Install every selected native projection and one shared state root atomically."""

    target = Path(target).expanduser()
    projection, artifacts = render_runtime_artifacts(source, target, plan, request)
    fs = ProjectFS(target)
    log: list[str] = []
    operation = "force" if force else ("merge" if fs.root.exists() else "install")
    with ProjectTransaction(
        fs,
        operation=operation,
        to_version=__version__,
        protected_paths=_PROTECTED_PATHS,
        journal_path=StateLayout.neutral().journal,
    ):
        log.extend(
            _apply_runtime_files(
                fs,
                plan,
                projection,
                artifacts,
                force=force,
            )
        )
    return log


def _next_provider_backup(fs: ProjectFS) -> str:
    index = 1
    while fs.exists(f".ckit.bak-{index}"):
        index += 1
    return f".ckit.bak-{index}"


def _removed_surfaces(current: Runtime, target: Runtime) -> tuple[str, ...]:
    current_providers = set(current.providers)
    target_providers = set(target.providers)
    removed = current_providers - target_providers
    surfaces: list[str] = []
    if "claude" in removed:
        surfaces.extend(
            (
                ".claude",
                "CLAUDE.md",
                "CLAUDE.md.claude-kit",
                ".mcp.json",
                ".mcp.json.claude-kit",
                ".mcp.lock.json",
            )
        )
    if "codex" in removed:
        surfaces.extend(
            (
                ".codex",
                ".agents",
                "AGENTS.md",
                "AGENTS.md.claude-kit",
            )
        )
    return tuple(surfaces)


def transition_runtime(
    source: Path,
    target: Path,
    plan: ResolvedPlan,
    request: InstallRequest,
    *,
    confirm_removal: bool = False,
    force: bool = False,
) -> list[str]:
    """Atomically add/remove provider projections while preserving shared state.

    Provider removals are copied into a numbered, project-local backup before
    their native surfaces are removed.  The backup and every live root belong to
    the same rollback transaction.
    """

    target = Path(target).expanduser()
    fs = ProjectFS(target)
    if not fs.is_file(StateLayout.neutral().manifest):
        raise RuntimeInstallError(
            "runtime transitions require a neutral .ckit manifest; migrate legacy state first"
        )
    try:
        options = InitOptions.from_dict(
            json.loads(fs.read_text(StateLayout.neutral().manifest))
        )
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeInstallError(
            f"installed runtime manifest is corrupt: {exc}"
        ) from exc
    if options.selection != plan.selection or request.selection != plan.selection:
        raise RuntimeInstallError(
            "runtime transition must reuse the installed provider-neutral selection"
        )
    current = options.runtime
    if current is request.runtime:
        return install_runtime(source, target, plan, request, force=force)

    removed = _removed_surfaces(current, request.runtime)
    if removed and not confirm_removal:
        raise RuntimeInstallError(
            "runtime transition removes native provider files; confirmation is required"
        )
    projection, artifacts = render_runtime_artifacts(source, target, plan, request)
    backup = _next_provider_backup(fs) if removed else None
    protected = _PROTECTED_PATHS + ((backup,) if backup is not None else ())
    actions = [
        {"rel": surface, "kind": "provider-remove", "owner": "kit"}
        for surface in removed
        if fs.exists(surface)
    ]
    log: list[str] = []
    with ProjectTransaction(
        fs,
        operation="upgrade",
        from_version=options.claude_kit_version,
        to_version=__version__,
        actions=actions,
        protected_paths=protected,
        journal_path=StateLayout.neutral().journal,
    ):
        old_records = _old_records(fs)
        if backup is not None:
            for surface in removed:
                if not fs.exists(surface):
                    continue
                destination = f"{backup}/providers/{surface}"
                fs.move(surface, destination)
                log.append(f"  • backed up {surface} -> {destination}")
        log.extend(
            _apply_runtime_files(
                fs,
                plan,
                projection,
                artifacts,
                force=force,
                old_records=old_records,
            )
        )
    return log


__all__ = [
    "RuntimeArtifact",
    "RuntimeInstallError",
    "compile_runtime_projection",
    "install_runtime",
    "preview_runtime_install",
    "render_runtime_artifacts",
    "transition_runtime",
    "validate_projection",
]
