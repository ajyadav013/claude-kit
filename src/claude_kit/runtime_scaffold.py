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
from claude_kit.provider_renderers import (
    CodexRenderer,
    codex_provider_leakage_scan_text,
)
from claude_kit.secure_fs import (
    ProjectFS,
    ProjectTransaction,
    recover_interrupted_transaction,
)
from claude_kit.state import active_state_layout
from claude_kit.state_migration import (
    StateMigrationResult,
    _apply_legacy_state_migration,
)

_AGENTS_START = "<!-- ckit:managed:start -->"
_AGENTS_END = "<!-- ckit:managed:end -->"
_TOML_START = "# ckit:managed:start"
_TOML_END = "# ckit:managed:end"
_AGENTS_MAX_BYTES = 32 * 1024
_SIDECAR_SUFFIX = ".claude-kit"
_LEGACY_TEMPLATE_COMPONENT = "artifact://templates"
_LEGACY_TEMPLATE_PREFIX = f"{StateLayout.neutral().artifacts}/templates/"
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
    ".mcp.lock.json.claude-kit",
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
_MIGRATION_REMOVAL_ERROR = (
    "migrating legacy state directly to the requested runtime would remove the "
    "installed provider projection without confirmation or a recoverable backup; "
    "run `ckit migrate-state <path>` first, then `ckit upgrade <path> --runtime "
    "<runtime> --confirm-runtime-removal`"
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


@dataclass(frozen=True)
class _LegacyTemplateRetirement:
    """Prior duplicate template records retired by a native reinstall."""

    manifest_paths: frozenset[str]
    removable_paths: tuple[str, ...]
    preserved_paths: tuple[str, ...]


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
        if item.provider == "codex":
            scanned = codex_provider_leakage_scan_text(text, location=item.path)
            if re.search(r"CLAUDE_CODE_|CLAUDE_PROJECT_DIR|\.claude(?:/|\\)", scanned):
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
        RuntimeArtifact(
            path=f"{layout.artifacts}/.gitkeep",
            content=b"",
            provider="shared",
            component_id="state://artifacts",
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
        selection=prepared.selection,
        runtime=request.runtime,
        execution_policy=request.execution_policy,
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


def _merge_claude_mcp(
    existing: str,
    generated: str,
    *,
    prior_managed_ids: frozenset[str] = frozenset(),
) -> str:
    """Merge generated Claude MCP servers without shadowing user definitions.

    A previously installed ``.mcp.json`` may contain both user servers and the
    kit's prior selected servers. ``prior_managed_ids`` comes only from the
    matching native manifest and names the subset replaced on upgrade. Any
    other overlap is an ambiguous duplicate and fails closed.
    """

    try:
        base_doc = json.loads(existing)
        generated_doc = json.loads(generated)
    except json.JSONDecodeError as exc:
        raise RuntimeInstallError(f"cannot merge invalid .mcp.json: {exc}") from exc
    if not isinstance(base_doc, dict) or not isinstance(generated_doc, dict):
        raise RuntimeInstallError(".mcp.json root must be an object")
    existing_servers = base_doc.get("mcpServers", {})
    generated_servers = generated_doc.get("mcpServers", {})
    if not isinstance(existing_servers, dict) or not isinstance(
        generated_servers, dict
    ):
        raise RuntimeInstallError(".mcp.json mcpServers must be an object")

    preserved_servers = dict(existing_servers)
    for server_id in prior_managed_ids:
        preserved_servers.pop(server_id, None)
    duplicates = set(preserved_servers) & set(generated_servers)
    if duplicates:
        raise RuntimeInstallError(
            "duplicate MCP definitions in user and generated Claude config: "
            + ", ".join(sorted(duplicates))
        )

    merged = dict(base_doc)
    for key, value in generated_doc.items():
        if key == "mcpServers":
            continue
        if key in merged and merged[key] != value:
            raise RuntimeInstallError(
                f"duplicate top-level .mcp.json definition for {key!r}"
            )
        merged[key] = value
    merged["mcpServers"] = {**preserved_servers, **generated_servers}
    return json.dumps(merged, indent=2, ensure_ascii=False) + "\n"


def _remove_managed_claude_mcp_servers(
    existing: str, prior_managed_ids: frozenset[str]
) -> bytes | None:
    """Remove only the prior managed subset from a mixed Claude MCP file.

    ``None`` means the resulting document has neither user server definitions
    nor any other user-owned top-level key and can be removed entirely.
    """

    rendered = _merge_claude_mcp(
        existing,
        '{"mcpServers": {}}\n',
        prior_managed_ids=prior_managed_ids,
    )
    document = json.loads(rendered)
    servers = document.get("mcpServers")
    if servers or any(key != "mcpServers" for key in document):
        return rendered.encode("utf-8")
    return None


def _old_options(fs: ProjectFS) -> InitOptions | None:
    """Return the manifest from the authoritative existing state layout."""

    layout = active_state_layout(fs)
    if layout is None or not fs.is_file(layout.manifest):
        return None
    try:
        return InitOptions.from_dict(json.loads(fs.read_text(layout.manifest)))
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeInstallError(f"existing init-options is corrupt: {exc}") from exc


def _old_records(fs: ProjectFS) -> dict[str, FileRecord]:
    options = _old_options(fs)
    return {record.path: record for record in options.files} if options else {}


def _prior_managed_claude_mcp_ids(
    fs: ProjectFS,
    options: InitOptions | None,
    records: dict[str, FileRecord],
) -> frozenset[str]:
    """Return the selected Claude MCP ids owned by a prior native install.

    ``.mcp.json`` is a mixed-ownership document: unknown server ids belong to
    the user, while ids explicitly selected into the prior kit manifest are the
    managed semantic subset. Replacing only that subset preserves later user
    additions without allowing a user definition to shadow the resolved plan.
    A pre-existing file with no matching manifest record remains wholly
    user-owned and therefore collides fail-closed.
    """

    if (
        options is None
        or "claude" not in options.runtimes
        or ".mcp.json" not in records
        or not fs.is_file(".mcp.json")
    ):
        return frozenset()
    return frozenset(options.selection.mcp)


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _legacy_template_retirement(
    fs: ProjectFS, records: dict[str, FileRecord]
) -> _LegacyTemplateRetirement:
    """Classify the retired duplicate-template surface without mutating it.

    Older native manifests tracked a second copy of each canonical artifact
    template under ``.ckit/artifacts/templates``.  Only the exact historical
    component identity, ownership, provider, and path prefix qualify here.  A
    qualifying live path must still be a link-free regular file; unchanged kit
    bytes may be removed, while modified bytes become preserved user content.
    In both cases the obsolete manifest ownership is retired.
    """

    manifest_paths: set[str] = set()
    removable_paths: list[str] = []
    preserved_paths: list[str] = []
    for record in sorted(records.values(), key=lambda item: item.path):
        if not (
            record.owner == "kit"
            and record.provider == "shared"
            and record.component_id == _LEGACY_TEMPLATE_COMPONENT
            and record.path.startswith(_LEGACY_TEMPLATE_PREFIX)
        ):
            continue
        manifest_paths.add(record.path)
        if not fs.exists(record.path):
            continue
        if not fs.is_file(record.path):
            raise RuntimeInstallError(
                "legacy duplicate template destination is not a regular file: "
                f"{record.path}"
            )
        if _sha256(fs.read_bytes(record.path)) == record.sha256:
            removable_paths.append(record.path)
        else:
            preserved_paths.append(record.path)
    return _LegacyTemplateRetirement(
        manifest_paths=frozenset(manifest_paths),
        removable_paths=tuple(removable_paths),
        preserved_paths=tuple(preserved_paths),
    )


def _write_artifact(
    fs: ProjectFS,
    artifact: RuntimeArtifact,
    *,
    old_records: dict[str, FileRecord],
    prior_managed_claude_mcp_ids: frozenset[str],
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
    if path == ".mcp.json":
        generated = content.decode("utf-8")
        if exists and not force:
            rendered = _merge_claude_mcp(
                fs.read_text(path),
                generated,
                prior_managed_ids=prior_managed_claude_mcp_ids,
            )
        else:
            rendered = generated
        content = rendered.encode("utf-8")
        fs.write_bytes(path, content, mode=mode)
        message = (
            "  • .mcp.json merged; user server definitions preserved"
            if exists and not force
            else "  • .mcp.json"
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
            and (previous.owner != "user-editable" or path == ".mcp.lock.json")
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
    request: InstallRequest,
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
        execution_policy=request.execution_policy,
    )
    return (json.dumps(options.to_dict(), indent=2) + "\n").encode("utf-8")


def preview_runtime_install(
    source: Path,
    target: Path,
    plan: ResolvedPlan,
    request: InstallRequest,
    *,
    force: bool = False,
) -> tuple[ProjectionPlan, list[str]]:
    """Return the exact live-target write inventory without mutation.

    The preview runs the same pure merge and collision decisions as the real
    installer. It therefore reports sidecars on an existing project and
    refuses ambiguous native configuration before claiming success.
    """

    fs = ProjectFS(Path(target).expanduser())
    if fs.root.exists() and (
        fs.exists(StateLayout.neutral().journal)
        or fs.exists(StateLayout.legacy_claude().journal)
        or any(child.name.startswith(".claude-kit-txn-") for child in fs.root.iterdir())
    ):
        raise RuntimeInstallError(
            "exact runtime preview is unavailable while an interrupted lifecycle "
            "transaction awaits recovery; rerun the real lifecycle command to recover "
            "it before requesting --dry-run"
        )
    projection, artifacts = render_runtime_artifacts(source, target, plan, request)
    options = _old_options(fs)
    records = {record.path: record for record in options.files} if options else {}
    retirement = _legacy_template_retirement(fs, records)
    managed_mcp_ids = _prior_managed_claude_mcp_ids(fs, options, records)
    # Preview reports the exact hash-matched files that the transaction would
    # remove. Modified legacy copies remain user content and are intentionally
    # absent from this mutation list.
    paths: list[str] = list(retirement.removable_paths)
    artifact_paths = {artifact.path for artifact in artifacts}
    if managed_mcp_ids and ".mcp.json" not in artifact_paths:
        _remove_managed_claude_mcp_servers(fs.read_text(".mcp.json"), managed_mcp_ids)
        paths.append(".mcp.json")
        previous_lock = records.get(".mcp.lock.json")
        if previous_lock is not None and fs.is_file(".mcp.lock.json"):
            if previous_lock.sha256 == _sha256(fs.read_bytes(".mcp.lock.json")):
                paths.append(".mcp.lock.json")
    for artifact in artifacts:
        path = artifact.path
        exists = fs.is_file(path)
        if fs.exists(path) and not exists:
            raise RuntimeInstallError(
                f"native artifact destination is not a regular file: {path}"
            )
        if path == "AGENTS.md":
            if exists and not force:
                _merge_agents(fs.read_text(path), artifact.content.decode("utf-8"))
            paths.append(path)
            continue
        if path == ".codex/config.toml":
            if exists and not force:
                _merge_codex_toml(fs.read_text(path), artifact.content.decode("utf-8"))
            paths.append(path)
            continue
        if path == ".mcp.json":
            if exists and not force:
                _merge_claude_mcp(
                    fs.read_text(path),
                    artifact.content.decode("utf-8"),
                    prior_managed_ids=managed_mcp_ids,
                )
            paths.append(path)
            continue
        if not exists or force:
            paths.append(path)
            continue
        current = fs.read_bytes(path)
        if current == artifact.content or path == StateLayout.neutral().continuity:
            continue
        previous = records.get(path)
        safe_to_refresh = (
            previous is not None
            and (previous.owner != "user-editable" or path == ".mcp.lock.json")
            and previous.sha256 == _sha256(current)
        )
        if artifact.owner == "user-editable" or not safe_to_refresh:
            if path.startswith(".ckit/agent-memory/"):
                continue
            sidecar = path + _SIDECAR_SUFFIX
            if fs.exists(sidecar) and not fs.is_file(sidecar):
                raise RuntimeInstallError(
                    f"native sidecar destination is not a regular file: {sidecar}"
                )
            paths.append(sidecar)
        else:
            paths.append(path)

    if fs.exists(".gitignore") and not fs.is_file(".gitignore"):
        raise RuntimeInstallError(
            "native artifact destination is not a regular file: .gitignore"
        )
    existing_ignore = (
        fs.read_text(".gitignore").splitlines() if fs.is_file(".gitignore") else []
    )
    if any(entry not in set(existing_ignore) for entry in _GITIGNORE_ENTRIES):
        paths.append(".gitignore")
    paths.append(StateLayout.neutral().manifest)
    return projection, sorted(set(paths))


def _apply_runtime_files(
    fs: ProjectFS,
    plan: ResolvedPlan,
    projection: ProjectionPlan,
    artifacts: Iterable[RuntimeArtifact],
    *,
    request: InstallRequest,
    force: bool,
    old_records: dict[str, FileRecord] | None = None,
) -> list[str]:
    """Apply a prevalidated projection while an encompassing transaction is held."""

    log: list[str] = []
    previous_options = _old_options(fs)
    previous = old_records if old_records is not None else _old_records(fs)
    prior_managed_claude_mcp_ids = _prior_managed_claude_mcp_ids(
        fs, previous_options, previous
    )
    artifacts = tuple(artifacts)
    installed: list[tuple[RuntimeArtifact, str, bytes]] = []
    artifact_paths = {artifact.path for artifact in artifacts}
    if prior_managed_claude_mcp_ids and ".mcp.json" not in artifact_paths:
        remaining = _remove_managed_claude_mcp_servers(
            fs.read_text(".mcp.json"), prior_managed_claude_mcp_ids
        )
        if remaining is None:
            fs.unlink(".mcp.json")
            log.append("  • removed prior managed .mcp.json (no MCP servers selected)")
        else:
            fs.write_bytes(".mcp.json", remaining)
            log.append(
                "  • removed prior managed MCP servers; user definitions preserved"
            )
        previous_lock = previous.get(".mcp.lock.json")
        if previous_lock is not None and fs.is_file(".mcp.lock.json"):
            current_lock = fs.read_bytes(".mcp.lock.json")
            if previous_lock.sha256 == _sha256(current_lock):
                fs.unlink(".mcp.lock.json")
                log.append("  • removed prior managed .mcp.lock.json")
            else:
                log.append("  • preserved user-modified .mcp.lock.json")
    retirement = _legacy_template_retirement(fs, previous)
    for path in retirement.removable_paths:
        # Recheck immediately before deletion. The transaction lease excludes
        # cooperating lifecycle writers, and ProjectFS refuses link/reparse
        # swaps and non-regular read targets.
        record = previous[path]
        if _sha256(fs.read_bytes(path)) != record.sha256:
            log.append(
                f"  • preserved user-modified legacy template {path}; "
                "retired kit ownership"
            )
            continue
        fs.unlink(path)
        log.append(f"  • retired duplicate legacy template {path}")
    for path in retirement.preserved_paths:
        log.append(
            f"  • preserved user-modified legacy template {path}; retired kit ownership"
        )
    for artifact in artifacts:
        result = _write_artifact(
            fs,
            artifact,
            old_records=previous,
            prior_managed_claude_mcp_ids=prior_managed_claude_mcp_ids,
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
        request=request,
        preserved_records=(
            record
            for record in previous.values()
            if record.path not in retirement.manifest_paths and fs.is_file(record.path)
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

    log, _migration = _install_runtime_transaction(
        source,
        target,
        plan,
        request,
        force=force,
        migrate_legacy=False,
        require_legacy_source=False,
    )
    return log


def install_runtime_with_state_migration(
    source: Path,
    target: Path,
    plan: ResolvedPlan,
    request: InstallRequest,
    *,
    force: bool = False,
    require_legacy_source: bool = True,
) -> tuple[list[str], StateMigrationResult]:
    """Migrate legacy state and install native projections in one transaction.

    Projection compilation and validation finish before the transaction starts.
    Once mutation begins, both legacy-state copying and every provider/shared
    write are covered by the same rollback snapshot, so an install refusal can
    never leave a separately committed ``.ckit`` migration behind.
    """

    target = Path(target).expanduser()
    fs = ProjectFS(target)
    if active_state_layout(fs) == StateLayout.legacy_claude():
        legacy_options = _old_options(fs)
        if legacy_options is not None and set(legacy_options.runtime.providers) - set(
            request.runtime.providers
        ):
            # Refuse before projection work for a stable, actionable CLI error.
            # The same check runs again under the transaction lease below to
            # close a concurrent legacy-manifest change between check and use.
            raise RuntimeInstallError(_MIGRATION_REMOVAL_ERROR)

    log, migration = _install_runtime_transaction(
        source,
        target,
        plan,
        request,
        force=force,
        migrate_legacy=True,
        require_legacy_source=require_legacy_source,
    )
    if migration is None:  # pragma: no cover - internal invariant
        raise RuntimeInstallError("legacy state migration result was not recorded")
    return log, migration


def _install_runtime_transaction(
    source: Path,
    target: Path,
    plan: ResolvedPlan,
    request: InstallRequest,
    *,
    force: bool,
    migrate_legacy: bool,
    require_legacy_source: bool,
    fs: ProjectFS | None = None,
) -> tuple[list[str], StateMigrationResult | None]:
    """Apply one pre-rendered runtime install under one lifecycle transaction."""

    target = Path(target).expanduser()
    projection, artifacts = render_runtime_artifacts(source, target, plan, request)
    fs = fs or ProjectFS(target)
    log: list[str] = []
    migration: StateMigrationResult | None = None
    operation = "force" if force else ("merge" if fs.root.exists() else "install")
    with ProjectTransaction(
        fs,
        operation=operation,
        to_version=__version__,
        protected_paths=_PROTECTED_PATHS,
        journal_path=StateLayout.neutral().journal,
    ):
        state_layout = active_state_layout(fs)
        if migrate_legacy and state_layout == StateLayout.neutral():
            migration = StateMigrationResult(migrated=False, already_neutral=True)
        elif migrate_legacy:
            migration = _apply_legacy_state_migration(
                fs, require_source=require_legacy_source
            )
        elif state_layout == StateLayout.legacy_claude():
            raise RuntimeInstallError(
                "legacy mutable state is installed under .claude; rerun with "
                "--migrate-state to copy it transactionally into .ckit"
            )
        installed_options = _old_options(fs)
        if (
            installed_options is not None
            and fs.is_file(StateLayout.neutral().manifest)
            and installed_options.runtime is not request.runtime
        ):
            if migration is not None and migration.migrated:
                # Legacy Claude -> both is additive.  The migrated manifest still
                # names Claude until this encompassing transaction writes the final
                # dual-runtime manifest, so only provider removal is a transition.
                removed_providers = set(installed_options.runtime.providers) - set(
                    request.runtime.providers
                )
                if removed_providers:
                    raise RuntimeInstallError(_MIGRATION_REMOVAL_ERROR)
            else:
                raise RuntimeInstallError(
                    "installed runtime differs from the requested runtime; use "
                    "`ckit upgrade --runtime <runtime>` so provider removal is "
                    "confirmed and backed up"
                )
        log.extend(
            _apply_runtime_files(
                fs,
                plan,
                projection,
                artifacts,
                request=request,
                force=force,
            )
        )
    return log, migration


def _next_provider_backup(fs: ProjectFS) -> str:
    index = 1
    while fs.exists(f".ckit.bak-{index}"):
        index += 1
    return f".ckit.bak-{index}"


def _removed_surfaces(options: InitOptions, target: Runtime) -> tuple[str, ...]:
    current_providers = set(options.runtime.providers)
    target_providers = set(target.providers)
    removed = current_providers - target_providers
    surfaces = {record.path for record in options.files if record.provider in removed}
    if "claude" in removed:
        surfaces.update(
            (
                ".claude",
                "CLAUDE.md",
                "CLAUDE.md.claude-kit",
                "README.claude-sdlc.md",
                "README.claude-sdlc.md.claude-kit",
                ".mcp.json",
                ".mcp.json.claude-kit",
                ".mcp.lock.json",
                ".mcp.lock.json.claude-kit",
            )
        )
    if "codex" in removed:
        surfaces.update(
            (
                ".codex",
                ".agents",
                "AGENTS.md",
                "AGENTS.md.claude-kit",
            )
        )
    return tuple(sorted(surfaces))


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
    if not fs.root.exists():
        raise RuntimeInstallError(
            "runtime transitions require a neutral .ckit manifest; migrate legacy state first"
        )
    with fs.mutation_lease(exclusive=True):
        # The live manifest may be a partially applied target-runtime manifest.
        # Recover before choosing same-runtime upgrade versus provider transition,
        # and retain this lease until the new transaction commits.
        recover_interrupted_transaction(fs, preserve_root=True)
        if not fs.is_file(StateLayout.neutral().manifest):
            raise RuntimeInstallError(
                "runtime transitions require a neutral .ckit manifest; "
                "migrate legacy state first"
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
            log, _migration = _install_runtime_transaction(
                source,
                target,
                plan,
                request,
                force=force,
                migrate_legacy=False,
                require_legacy_source=False,
                fs=fs,
            )
            return log

        removed = _removed_surfaces(options, request.runtime)
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
        log = []
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
                    request=request,
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
    "install_runtime_with_state_migration",
    "preview_runtime_install",
    "render_runtime_artifacts",
    "transition_runtime",
    "validate_projection",
]
