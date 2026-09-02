"""Validation and health checks for a scaffolded claude-kit configuration.

``validate`` performs structural checks (files present, JSON parses, frontmatter complete,
referenced overlays installed). Passing ``strict=True`` adds deep checks: settings.json hooks point
at installed, executable scripts on valid events; ``.mcp.json`` has a sane shape; the resolved stack
snapshot agrees with what's on disk; deployed prose is free of hidden/deceptive Unicode (an
invisible-instruction channel — critical classes FAIL); and the **bundled catalog** is referentially
consistent (profiles → existing agents/skills/hooks, stack overlay files present). ``doctor`` runs the strict
validate plus environment checks (git/jq available, hook scripts executable, runtime dirs gitignored)
and, with ``--mcp``, MCP command/env-var health. All return ``(ok, messages)`` so the CLI can print a
report and choose an exit code.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Callable, Mapping

import yaml

try:  # pragma: no cover - Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.9/3.10 dependency
    import tomli as tomllib  # type: ignore[no-redef]

from claude_kit.mcp import (
    adapt_codex_server_config,
    project_resolved_servers,
    require_runtime_support,
)
from claude_kit.models import (
    InitOptions,
    ResolvedPlan,
    Selection,
    StateLayout,
    UpgradeJournal,
)
from claude_kit.secure_fs import (
    TRANSACTION_SCHEMA,
    ProjectFS,
    inspect_interrupted_transaction,
)
from claude_kit.state import detect_state_layout


def _load_claude_compatibility() -> dict:
    """Load the bundled, schema-validated Claude Code compatibility policy."""
    import yaml

    from claude_kit import scaffold

    with ExitStack() as stack:
        path = scaffold.payload_dir(stack) / "catalog" / "claude-compatibility.yaml"
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _load_codex_compatibility() -> dict:
    """Load the bundled, schema-validated Codex compatibility policy."""

    from claude_kit import scaffold

    with ExitStack() as stack:
        path = scaffold.payload_dir(stack) / "catalog" / "codex-compatibility.yaml"
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


CLAUDE_COMPATIBILITY = _load_claude_compatibility()
# Internal/public compatibility alias retained for callers from the Claude-only implementation.
CLAUDE_CODE_COMPATIBILITY = CLAUDE_COMPATIBILITY
CODEX_COMPATIBILITY = _load_codex_compatibility()
_KIT_PLUGIN_ID = "claude-kit@claude-kit"
#: Officially recognized events are data, separate from the hook implementations the kit ships.
KNOWN_EVENTS = frozenset(CLAUDE_COMPATIBILITY["events"]["recognized"])

#: Extracts the script basenames a hook command runs from ``.claude/hooks/`` (inline guards match none).
_HOOK_SCRIPT_RE = re.compile(r"\.claude/hooks/([^\"'\s]+\.sh)")
#: Extracts ``${VAR}`` placeholders from an .mcp.json fragment (valid shell identifiers only — a
#: leading digit like ``${1}`` is a positional parameter, not an env var to warn about).
_ENV_VAR_RE = re.compile(r"\$\{([A-Za-z_]\w*)\}")

#: Hidden/deceptive Unicode in deployed prose, tiered by severity. **critical** characters have no
#: legitimate role in kit prose and form an invisible-instruction channel (content a human reviewer
#: cannot see but a model reads): Unicode tag characters, bidi overrides/isolates, variation
#: selectors 17-256. **warning** characters are suspicious but occasionally legitimate: zero-width
#: characters and bidi marks (a BOM appearing *mid-file* is flagged separately — a leading one is a
#: benign encoding artifact). **info** is NBSP — common in prose pasted from rich-text editors.
_UNICODE_CLASSES: tuple[tuple[str, str, tuple[tuple[int, int], ...]], ...] = (
    ("critical", "tag characters (U+E0001-E007F)", ((0xE0001, 0xE007F),)),
    (
        "critical",
        "bidi overrides/isolates (U+202A-E, U+2066-9)",
        ((0x202A, 0x202E), (0x2066, 0x2069)),
    ),
    ("critical", "variation selectors 17-256 (U+E0100-E01EF)", ((0xE0100, 0xE01EF),)),
    ("warning", "zero-width characters (U+200B-D)", ((0x200B, 0x200D),)),
    ("warning", "bidi marks (U+200E/F)", ((0x200E, 0x200F),)),
    ("info", "non-breaking spaces (U+00A0)", ((0x00A0, 0x00A0),)),
)


def _resolve_installed_plan(selection: Selection) -> ResolvedPlan:
    """Resolve one persisted selection against the bundled semantic catalogs."""

    from claude_kit import catalog, scaffold

    with ExitStack() as stack:
        return catalog.resolve(scaffold.payload_dir(stack), selection)


def _check_mcp_runtime_support(
    plan: ResolvedPlan,
    runtimes: tuple[str, ...] | list[str] | set[str],
    fail: Callable[[str], None],
    good: Callable[[str], None],
) -> bool:
    """Validate required MCP/runtime compatibility from retained semantic specs."""

    try:
        require_runtime_support(plan.mcp_server_specs, sorted(runtimes))
    except ValueError as exc:
        fail(str(exc))
        return False
    else:
        if plan.mcp_server_specs:
            good(
                "selected MCP servers support installed runtime(s): "
                + ", ".join(sorted(runtimes))
            )
        return True


def _check_native_mcp_projection(
    plan: ResolvedPlan,
    provider: str,
    native_servers: Mapping[str, Any] | None,
    fail: Callable[[str], None],
    good: Callable[[str], None],
) -> None:
    """Require selected native MCP records to equal the current projection.

    A project may contain additional user-owned server ids. Selected ids are
    kit-managed capabilities, however, so membership alone is insufficient: a
    changed command, URL, argument, environment mapping, or HTTP header would no
    longer represent the resolved semantic plan.
    """

    if not plan.mcp_servers or native_servers is None:
        return
    try:
        projected = project_resolved_servers(
            plan.mcp_servers,
            plan.mcp_server_specs,
            provider,
        )
        if provider == "codex":
            expected = {
                server_id: adapt_codex_server_config(server_id, config)
                for server_id, config in projected.items()
            }
        else:
            expected = projected
    except (TypeError, ValueError) as exc:
        fail(f"{provider.title()} MCP projection cannot be validated: {exc}")
        return

    mismatched: list[str] = []
    for server_id, expected_config in expected.items():
        # The structural pass already emits the more actionable omission error.
        if server_id not in native_servers:
            continue
        if native_servers[server_id] != expected_config:
            mismatched.append(server_id)
            fail(
                f"{provider.title()} MCP server {server_id!r} differs from "
                "the current resolved native projection"
            )
    if not mismatched and set(expected).issubset(native_servers):
        good(
            f"{provider.title()} MCP config exactly matches every selected "
            "server projection"
        )


def _doctor_mcp_semantic_summary(
    selection: Selection, runtimes: set[str], msgs: list[str]
) -> None:
    """Report the catalog policy that native MCP syntax cannot encode."""

    try:
        plan = _resolve_installed_plan(selection)
    except (FileNotFoundError, TypeError, ValueError):
        return  # strict validation already reports the actionable catalog failure
    for server_id in sorted(plan.mcp_server_specs):
        spec = plan.mcp_server_specs[server_id]
        support = ",".join(sorted(spec.runtime_support))
        missing = sorted(runtimes - set(spec.runtime_support))
        disposition = (
            "unsupported for installed runtime(s) " + ",".join(missing)
            if missing
            else "compatible"
        )
        msgs.append(
            f"INFO  MCP {server_id} semantics: runtimes={support}; "
            f"authentication={spec.authentication.value}; "
            f"declared-health={spec.health_check}; {disposition}"
        )


def _check_snapshot_mcp_semantics(
    snapshot: object,
    plan: ResolvedPlan,
    fail: Callable[[str], None],
    warn: Callable[[str], None],
    good: Callable[[str], None],
) -> None:
    """Compare additive persisted MCP policy with the current resolved selection."""

    expected = plan.mcp_semantics
    persisted = snapshot.get("mcp_semantics") if isinstance(snapshot, dict) else None
    if persisted is None:
        if expected:
            warn(
                "stack snapshot predates semantic MCP metadata; run `ckit upgrade` "
                "to record runtime/auth/health policy"
            )
    elif persisted != expected:
        fail("stack snapshot MCP semantics differ from the current resolved selection")
    else:
        good("stack snapshot retains resolved MCP semantics")


def _check_maker_checker_execution_policy(
    target: Path,
    options: InitOptions,
    fail: Callable[[str], None],
    warn: Callable[[str], None],
    good: Callable[[str], None],
) -> None:
    """Validate one configured maker/reviewer pair without contacting a host.

    Parsing :class:`InitOptions` already enforces the bounded configuration
    schema. This check makes that policy visible and verifies the two installed
    native routes through the same loader used by process dispatch. Model tiers
    are resolved only against the pinned compatibility catalog; exact model
    availability remains a live run preflight concern.
    """

    policy = options.execution_policy
    if policy is None:
        return

    from claude_kit.components import (
        Capability,
        IsolationRequirement,
        ModelTier,
        NestedDelegationPolicy,
        PermissionClass,
    )
    from claude_kit.models import ModelChoiceKind
    from claude_kit.process_dispatch import (
        FilesystemNativeRoleLoader,
        RoleUnavailableError,
    )
    from claude_kit.projection import Provider
    from claude_kit.provider_compatibility import (
        ProviderCompatibilityError,
        load_agent_projection_compatibility,
    )

    try:
        policy.validate_providers(options.runtimes)
    except ValueError as exc:  # defensive: InitOptions normally rejects this first
        fail(
            f"maker-checker execution policy references an unavailable provider: {exc}"
        )
        return

    good(
        "maker-checker execution policy is enabled "
        f"(max revisions={policy.max_revisions})"
    )
    if policy.maker == policy.reviewer:
        warn(
            "maker and reviewer use the same provider/model binding; "
            "review independence is reduced"
        )

    role_loader = FilesystemNativeRoleLoader(target)
    expected_capabilities = frozenset({Capability.FILE_READ, Capability.SEARCH})
    routes = (
        ("maker", "maker-checker-maker", policy.maker),
        ("reviewer", "maker-checker-reviewer", policy.reviewer),
    )
    compatibility: dict[str, object] = {}
    with ExitStack() as stack:
        from claude_kit import scaffold

        payload = scaffold.payload_dir(stack)
        for slot, route, binding in routes:
            provider_name = binding.provider.value
            provider = Provider.parse(provider_name)
            try:
                provider_policy = compatibility.get(provider_name)
                if provider_policy is None:
                    provider_policy = load_agent_projection_compatibility(
                        payload,
                        provider_name,  # type: ignore[arg-type]
                    )
                    compatibility[provider_name] = provider_policy
            except (OSError, ProviderCompatibilityError, ValueError) as exc:
                fail(
                    f"maker-checker {slot} provider compatibility is unavailable "
                    f"for {provider_name}: {exc}"
                )
                continue

            choice = binding.model
            if choice.kind is ModelChoiceKind.EXACT:
                # ModelChoice construction has applied the bounded native-id
                # grammar. Do not turn this into an availability claim.
                good(
                    f"maker-checker {slot} exact model id has valid syntax "
                    f"for {provider_name}; validate/doctor do not make a live availability claim"
                )
            elif choice.kind is ModelChoiceKind.INHERIT:
                good(
                    f"maker-checker {slot} is configured to inherit the "
                    f"{provider_name} host model"
                )
            else:
                tier = ModelTier(str(choice.value))
                mapped_model = provider_policy.model_tiers[tier]  # type: ignore[attr-defined]
                if mapped_model is None:
                    warn(
                        f"maker-checker {slot} tier {tier.value!r} has no pinned "
                        f"{provider_name} model mapping and resolves to the host default; "
                        "use an exact model id when deterministic model routing is required"
                    )
                else:
                    good(
                        f"maker-checker {slot} tier {tier.value!r} has a pinned "
                        f"{provider_name} compatibility mapping"
                    )

            try:
                native_role = role_loader.load(provider, route)
            except (OSError, RoleUnavailableError, UnicodeError, ValueError) as exc:
                fail(
                    f"maker-checker {slot} route {route!r} is unavailable for "
                    f"{provider_name}: {exc}"
                )
                continue

            violations: list[str] = []
            if native_role.permission is not PermissionClass.READ_ONLY:
                violations.append(f"permission={native_role.permission.value}")
            if native_role.capabilities != expected_capabilities:
                rendered = (
                    ",".join(
                        capability.value
                        for capability in sorted(
                            native_role.capabilities, key=lambda item: item.value
                        )
                    )
                    or "none"
                )
                violations.append(f"capabilities={rendered}")
            if native_role.write_scope:
                violations.append("write-scope-present")
            if native_role.isolation is not IsolationRequirement.NONE:
                violations.append(f"isolation={native_role.isolation.value}")
            if native_role.nested_delegation is not NestedDelegationPolicy.FORBIDDEN:
                violations.append(
                    f"nested-delegation={native_role.nested_delegation.value}"
                )
            if violations:
                fail(
                    f"maker-checker {slot} route {route!r} is not passive on "
                    f"{provider_name}: " + ", ".join(violations)
                )
            else:
                good(
                    f"maker-checker {slot} route {route!r} is passive on "
                    f"{provider_name} (read/search only, no writes or delegation)"
                )


def _parse_frontmatter(text: str) -> dict[str, str] | None:
    """Return the frontmatter key/values at the top of a markdown file, or None if absent.

    Uses lenient line-based parsing (``key: value`` at column 0), deliberately mirroring Claude
    Code's own frontmatter reader rather than strict YAML. Real agent/skill files routinely carry
    a colon inside a ``description`` ("Read-only: routes fixes…") or a bracketed ``argument-hint``
    (``[optional: "x"]``); ``yaml.safe_load`` rejects both even though Claude Code accepts them, so
    validating with strict YAML would fail on valid files. Indented continuation lines, blanks, and
    comments are skipped — only the top-level scalar fields this module checks (``name``,
    ``description``) need to be recovered.
    """
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    data: dict[str, str] = {}
    for line in text[3:end].splitlines():
        if not line.strip() or line[0] in (" ", "\t", "#"):
            continue
        key, sep, value = line.partition(":")
        if sep:
            data[key.strip()] = value.strip()
    return data


def _sha256(path: Path) -> str:
    """Hex SHA-256 of a file's bytes (matches the digest recorded in init-options.json)."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_init_options(claude_dir: Path) -> tuple[InitOptions | None, str | None]:
    """Load ``init-options.json``, distinguishing *missing* from *corrupt*.

    Returns ``(options, None)`` on success; ``(None, "missing")`` when the file is absent; and
    ``(None, "corrupt: <detail>")`` when it exists but cannot be parsed. Callers can then surface a
    distinct, louder signal for a corrupt manifest (a real problem worth a FAIL) versus a missing
    one (an older install that merely predates upgrade tracking — a WARN).
    """
    path = claude_dir / "config" / "init-options.json"
    if not path.is_file():
        return None, "missing"
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ValueError("document root must be an object")
        if not isinstance(document.get("selection", {}), dict):
            raise ValueError("selection must be an object")
        if not isinstance(document.get("files", []), list):
            raise ValueError("files must be an array")
        return InitOptions.from_dict(document), None
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        return None, f"corrupt: {exc}"


def _load_init_options(claude_dir: Path) -> InitOptions | None:
    """Back-compat: the parsed options, or None for either a missing or corrupt manifest."""
    return _read_init_options(claude_dir)[0]


def _read_native_init_options(target: Path) -> tuple[InitOptions | None, str | None]:
    path = target / StateLayout.neutral().manifest
    if not path.is_file():
        return None, "missing"
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ValueError("document root must be an object")
        return InitOptions.from_dict(document), None
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        return None, f"corrupt: {exc}"


def _validate_native_runtime(target: Path, *, strict: bool) -> tuple[bool, list[str]]:
    """Validate a schema-v2 native runtime install and its shared control plane."""

    msgs: list[str] = []
    ok = True

    def fail(message: str) -> None:
        nonlocal ok
        ok = False
        msgs.append(f"FAIL  {message}")

    def warn(message: str) -> None:
        msgs.append(f"WARN  {message}")

    def good(message: str) -> None:
        msgs.append(f"OK    {message}")

    options, error = _read_native_init_options(target)
    if options is None:
        fail(f"{StateLayout.neutral().manifest} is unreadable ({error})")
        return ok, msgs
    if options.state_layout != StateLayout.neutral():
        fail("schema-v2 native install does not declare the neutral state layout")
    good(
        "native init-options.json "
        f"(schema v{options.schema_version}, runtimes={','.join(options.runtimes)})"
    )

    drifted: list[str] = []
    for record in options.files:
        path = target / record.path
        if not path.is_file():
            fail(f"recorded file missing: {record.path}")
        elif record.owner in {"kit", "overlay"} and _sha256(path) != record.sha256:
            drifted.append(record.path)
    if drifted:
        preview = ", ".join(sorted(drifted)[:3])
        warn(f"{len(drifted)} kit-owned native file(s) modified: {preview}")
    good(f"tracked native/shared files present ({len(options.files)} recorded)")

    providers = set(options.runtimes)
    selected_mcp = set(options.selection.mcp)
    native_mcp_servers: dict[str, Mapping[str, Any] | None] = {
        "claude": None,
        "codex": None,
    }
    recorded_providers = {record.provider for record in options.files}
    unexpected = recorded_providers - providers - {"shared"}
    if unexpected:
        fail("manifest records uninstalled providers: " + ", ".join(sorted(unexpected)))
    if "shared" not in recorded_providers:
        fail("manifest has no shared control-plane records")

    layout = StateLayout.neutral()
    for required in (layout.stack_snapshot, layout.continuity, layout.memory):
        if not (target / required).exists():
            fail(f"shared control-plane path missing: {required}")
    for duplicate in (
        ".claude/state/pipeline-snapshot.json",
        ".codex/state/pipeline-snapshot.json",
    ):
        if (target / duplicate).exists():
            fail(f"independent provider gate ledger is forbidden: {duplicate}")

    if "claude" in providers:
        if not (target / "CLAUDE.md").is_file():
            fail("Claude runtime has no CLAUDE.md")
        for required in (
            ".claude/agents",
            ".claude/skills",
            ".claude/rules",
            ".claude/hooks",
        ):
            if not (target / required).is_dir():
                fail(f"Claude native surface missing: {required}")
        settings = target / ".claude/settings.json"
        try:
            document = json.loads(settings.read_text(encoding="utf-8"))
            if not isinstance(document, dict):
                raise ValueError("root is not an object")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            fail(f"Claude settings are invalid: {exc}")
        else:
            good("Claude native settings/hooks parse")
        if selected_mcp:
            mcp_path = target / ".mcp.json"
            try:
                mcp_document = json.loads(mcp_path.read_text(encoding="utf-8"))
                native_servers = mcp_document.get("mcpServers")
                if not isinstance(native_servers, dict):
                    raise ValueError("mcpServers is not an object")
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                fail(f"Claude MCP config is invalid: {exc}")
            else:
                native_mcp_servers["claude"] = native_servers
                missing = selected_mcp - set(native_servers)
                if missing:
                    fail(
                        "Claude MCP config omits selected server(s): "
                        + ", ".join(sorted(missing))
                    )
                else:
                    good("Claude MCP config contains every selected server")

    if "codex" in providers:
        agents_md = target / "AGENTS.md"
        if not agents_md.is_file():
            fail("Codex runtime has no AGENTS.md")
        elif len(agents_md.read_bytes()) >= 32 * 1024:
            fail("AGENTS.md exceeds Codex's default 32 KiB instruction budget")
        agents = target / ".codex/agents"
        if not agents.is_dir() or not any(agents.glob("*.toml")):
            fail("Codex native agent TOML is missing")
        else:
            for path in agents.glob("*.toml"):
                try:
                    document = tomllib.loads(path.read_text(encoding="utf-8"))
                except tomllib.TOMLDecodeError as exc:
                    fail(f"invalid Codex agent TOML {path.name}: {exc}")
                    continue
                missing = {
                    "name",
                    "description",
                    "developer_instructions",
                } - set(document)
                if missing:
                    fail(
                        f"Codex agent {path.name} misses: " + ", ".join(sorted(missing))
                    )
            good(f"Codex native agents parse ({sum(1 for _ in agents.glob('*.toml'))})")
        skills = target / ".agents/skills"
        if not skills.is_dir() or not any(skills.glob("*/SKILL.md")):
            fail("Codex Open Agent Skills surface is missing")
        else:
            invalid = [
                path.parent.name
                for path in skills.glob("*/SKILL.md")
                if not ((_parse_frontmatter(path.read_text()) or {}).get("name"))
                or not ((_parse_frontmatter(path.read_text()) or {}).get("description"))
            ]
            if invalid:
                fail("Codex skills have incomplete frontmatter: " + ", ".join(invalid))
            else:
                good(
                    f"Codex skills parse ({sum(1 for _ in skills.glob('*/SKILL.md'))})"
                )
        hooks = target / ".codex/hooks.json"
        try:
            hooks_document = json.loads(hooks.read_text(encoding="utf-8"))
            if not isinstance(hooks_document.get("hooks"), dict):
                raise ValueError("hooks root is missing")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            fail(f"Codex hooks are invalid: {exc}")
        config = target / ".codex/config.toml"
        try:
            config_document = tomllib.loads(config.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            fail(f"Codex config TOML is invalid: {exc}")
        else:
            good("Codex hooks/config parse")
            if selected_mcp:
                native_servers = config_document.get("mcp_servers")
                if not isinstance(native_servers, dict):
                    fail("Codex MCP config has no mcp_servers table")
                else:
                    native_mcp_servers["codex"] = native_servers
                    missing = selected_mcp - set(native_servers)
                    if missing:
                        fail(
                            "Codex MCP config omits selected server(s): "
                            + ", ".join(sorted(missing))
                        )
                    else:
                        good("Codex MCP config contains every selected server")

    _check_maker_checker_execution_policy(target, options, fail, warn, good)

    try:
        snapshot = yaml.safe_load((target / layout.stack_snapshot).read_text())
    except (OSError, yaml.YAMLError) as exc:
        fail(f"shared stack snapshot is invalid: {exc}")
        snapshot = None
    if isinstance(snapshot, dict):
        if snapshot.get("runtimes") != options.runtimes:
            fail("stack snapshot runtimes differ from init-options")
        persisted_digest = snapshot.get("gate_definition_digest")
        if not (
            isinstance(persisted_digest, str)
            and len(persisted_digest) == 64
            and all(char in "0123456789abcdef" for char in persisted_digest)
        ):
            fail("stack snapshot has no valid gate-definition digest")
        else:
            good(f"shared gate-definition digest {persisted_digest[:12]}…")

    if strict:
        snapshot_path = target / layout.stack_snapshot
        if snapshot_path.is_file():
            _strict_yaml_schema_artifact(
                snapshot_path, "stack-catalog-snapshot", fail, good
            )
        try:
            plan = _resolve_installed_plan(options.selection)
        except (FileNotFoundError, TypeError, ValueError) as exc:
            fail(f"installed selection no longer resolves: {exc}")
        else:
            good("installed selection resolves against the current catalog")
            mcp_supported = _check_mcp_runtime_support(
                plan, options.runtimes, fail, good
            )
            _check_snapshot_mcp_semantics(snapshot, plan, fail, warn, good)
            if mcp_supported:
                for provider in sorted(providers):
                    _check_native_mcp_projection(
                        plan,
                        provider,
                        native_mcp_servers[provider],
                        fail,
                        good,
                    )
        catalog_ok, catalog_messages = check_catalog(require_schema=True)
        msgs.extend(catalog_messages)
        if not catalog_ok:
            ok = False
    return ok, msgs


def validate(target: str | Path, *, strict: bool = False) -> tuple[bool, list[str]]:
    """Structurally validate the claude-kit config at ``target``.

    Args:
        target: Project root containing the ``.claude/`` to validate.
        strict: When True, add deep checks — settings.json hooks resolve to installed, executable
            scripts on valid events; ``.mcp.json`` shape; the stack snapshot agrees with installed
            files; and the bundled catalog is referentially consistent (see :func:`check_catalog`).

    Returns:
        ``(ok, messages)`` where each message is prefixed ``OK``/``WARN``/``FAIL`` and ``ok`` is
        False if any ``FAIL`` was recorded.
    """
    target = Path(target).expanduser().resolve()
    if (target / StateLayout.neutral().manifest).is_file():
        return _validate_native_runtime(target, strict=strict)
    claude = target / ".claude"
    msgs: list[str] = []
    ok = True

    def fail(m: str) -> None:
        nonlocal ok
        ok = False
        msgs.append(f"FAIL  {m}")

    def warn(m: str) -> None:
        msgs.append(f"WARN  {m}")

    def info(m: str) -> None:
        msgs.append(f"INFO  {m}")

    def good(m: str) -> None:
        msgs.append(f"OK    {m}")

    if not claude.is_dir():
        fail(f"no .claude/ directory in {target} — run `claude-kit init` here")
        return ok, msgs

    options, opt_err = _read_init_options(claude)
    resolved_plan: ResolvedPlan | None = None
    if options is None:
        if opt_err == "missing":
            warn(
                "no .claude/config/init-options.json (validate/upgrade limited — "
                "re-run `claude-kit init` to start tracking)"
            )
        else:
            fail(
                f".claude/config/init-options.json is unreadable ({opt_err}) — repair the JSON "
                "or re-run `claude-kit init --force`"
            )
    else:
        good(
            f"init-options.json (schema v{options.schema_version}, kit {options.claude_kit_version})"
        )
        try:
            plan = _resolve_installed_plan(options.selection)
        except (FileNotFoundError, TypeError, ValueError) as exc:
            fail(
                ".claude/config/init-options.json contains a selection that does not resolve "
                f"against this kit's catalog ({exc}) — repair it or re-run "
                "`claude-kit init --force`"
            )
        else:
            resolved_plan = plan
            good("installed selection resolves against the current catalog")
            _check_mcp_runtime_support(plan, ("claude",), fail, good)
        drifted: list[str] = []
        for rec in options.files:
            fp = target / rec.path
            if not fp.exists():
                fail(f"recorded file missing: {rec.path}")
            elif (
                rec.owner in ("kit", "overlay")
                and fp.is_file()
                and _sha256(fp) != rec.sha256
            ):
                drifted.append(rec.path)
        good(f"tracked files present ({len(options.files)} recorded)")
        if drifted:
            preview = ", ".join(sorted(drifted)[:3])
            more = "" if len(drifted) <= 3 else f" (+{len(drifted) - 3} more)"
            warn(
                f"{len(drifted)} kit-owned file(s) modified since install: {preview}{more} "
                "— run `claude-kit diff` to review (edits to user-editable files are not flagged)"
            )

    settings = claude / "settings.json"
    if settings.is_file():
        try:
            json.loads(settings.read_text(encoding="utf-8"))
            good("settings.json is valid JSON")
        except json.JSONDecodeError as exc:
            fail(f"settings.json is invalid JSON: {exc}")
    else:
        warn("no .claude/settings.json (hooks not configured)")

    agents_dir = claude / "agents"
    if agents_dir.is_dir():
        bad = [
            p.name
            for p in agents_dir.glob("*.md")
            if not (_parse_frontmatter(p.read_text(encoding="utf-8")) or {}).get("name")
            or not (_parse_frontmatter(p.read_text(encoding="utf-8")) or {}).get(
                "description"
            )
        ]
        if bad:
            fail(
                f"agents missing name/description frontmatter: {', '.join(sorted(bad))}"
            )
        else:
            good(
                f"agents/ frontmatter complete ({sum(1 for _ in agents_dir.glob('*.md'))} agents)"
            )
    else:
        warn("no .claude/agents/")

    skills_dir = claude / "skills"
    if skills_dir.is_dir():
        bad_skills = [
            d.name
            for d in skills_dir.iterdir()
            if d.is_dir()
            and (d / "SKILL.md").is_file()
            and not (
                _parse_frontmatter((d / "SKILL.md").read_text(encoding="utf-8")) or {}
            ).get("description")
        ]
        if bad_skills:
            fail(f"skills missing description: {', '.join(sorted(bad_skills))}")
        else:
            good(
                f"skills/ descriptions present "
                f"({sum(1 for d in skills_dir.iterdir() if d.is_dir() and (d / 'SKILL.md').is_file())} skills)"
            )

    rules_dir = claude / "rules"
    if not rules_dir.is_dir() or not any(rules_dir.glob("*.md")):
        fail("no .claude/rules/ content")
    else:
        good(f"rules/ present ({sum(1 for _ in rules_dir.glob('*.md'))} rules)")

    if strict:
        _strict_checks(claude, fail, warn, good, info)
        snapshot_path = claude / "config" / "stack-catalog.snapshot.yaml"
        if resolved_plan is not None and snapshot_path.is_file():
            try:
                snapshot = yaml.safe_load(snapshot_path.read_text(encoding="utf-8"))
            except (OSError, yaml.YAMLError):
                pass  # _strict_checks already reports the parse failure
            else:
                _check_snapshot_mcp_semantics(snapshot, resolved_plan, fail, warn, good)
        cat_ok, cat_msgs = check_catalog(require_schema=True)
        msgs.extend(cat_msgs)
        if not cat_ok:
            ok = False

    return ok, msgs


# --- strict installed-config checks ---------------------------------------------------------------


def _strict_checks(
    claude: Path,
    fail: Callable[[str], None],
    warn: Callable[[str], None],
    good: Callable[[str], None],
    info: Callable[[str], None],
) -> None:
    """Deep checks on a live install: hooks→scripts, .mcp.json shape, snapshot agreement, hidden Unicode."""
    settings = claude / "settings.json"
    if settings.is_file():
        try:
            doc = json.loads(settings.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            doc = None  # base checks already reported the parse error
        if isinstance(doc, dict):
            _strict_settings_hooks(claude, doc, fail, warn, good)
        elif doc is not None:
            fail("settings.json root must be an object")

    mcp = claude.parent / ".mcp.json"
    if mcp.is_file():
        _strict_mcp_shape(mcp, fail, good)

    snap = claude / "config" / "stack-catalog.snapshot.yaml"
    if snap.is_file():
        _strict_snapshot(claude, snap, fail, good)
        _strict_yaml_schema_artifact(snap, "stack-catalog-snapshot", fail, good)

    lock = claude.parent / ".mcp.lock.json"
    if lock.is_file():
        _strict_schema_artifact(lock, "mcp-lock", fail, good)

    psnap = claude / "state" / "pipeline-snapshot.json"
    if psnap.is_file():
        _strict_schema_artifact(psnap, "pipeline-snapshot", fail, good)

    _strict_hidden_unicode(claude, fail, warn, good, info)


def _scan_hidden_unicode(target: Path, claude: Path) -> dict[str, list[str]]:
    """Scan deployed prose (``*.md`` under ``.claude/`` plus the root ``CLAUDE.md``) for hidden Unicode.

    Returns ``{"critical": [...], "warning": [...], "info": [...]}`` where each entry reads
    ``<relpath>: Nx <class> (first at line L)``. A *leading* U+FEFF is a benign encoding artifact;
    only a BOM mid-file is flagged (warning tier). A file that is not valid UTF-8 is itself a
    warning-tier finding — the scan never crashes on one.
    """
    findings: dict[str, list[str]] = {"critical": [], "warning": [], "info": []}
    files = sorted(claude.rglob("*.md"))
    if (target / "CLAUDE.md").is_file():
        files.append(target / "CLAUDE.md")
    for path in files:
        rel = path.relative_to(target)
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            findings["warning"].append(f"{rel}: not valid UTF-8 — review manually")
            continue
        body = text[1:] if text.startswith("\ufeff") else text
        counts: dict[tuple[str, str], list[int]] = {}
        for idx, ch in enumerate(body):
            code = ord(ch)
            if code < 0xA0:
                continue
            if code == 0xFEFF:  # mid-file BOM (a leading one was stripped above)
                rec = counts.setdefault(
                    ("warning", "byte-order mark mid-file"), [0, idx]
                )
                rec[0] += 1
                continue
            for tier, label, ranges in _UNICODE_CLASSES:
                if any(lo <= code <= hi for lo, hi in ranges):
                    rec = counts.setdefault((tier, label), [0, idx])
                    rec[0] += 1
                    break
        for (tier, label), (n, first) in counts.items():
            line = body.count("\n", 0, first) + 1
            findings[tier].append(f"{rel}: {n}x {label} (first at line {line})")
    return findings


def _strict_hidden_unicode(
    claude: Path,
    fail: Callable[[str], None],
    warn: Callable[[str], None],
    good: Callable[[str], None],
    info: Callable[[str], None],
) -> None:
    """Hidden-Unicode scan of deployed prose: critical classes FAIL, warning classes WARN, NBSP is INFO.

    Critical characters (tag characters, bidi overrides/isolates, variation selectors) can carry
    instructions a human reviewer cannot see but a model reads — exactly the hidden-content vector
    the ``dependency-verification`` skill's agent-config intake greps for. Their presence in an
    installed config fails strict validation outright; the softer tiers surface via ``doctor``.
    """
    findings = _scan_hidden_unicode(claude.parent, claude)
    cap = 8  # keep a poisoned tree readable — the first hits identify the files to open
    for tier, emit in (("critical", fail), ("warning", warn)):
        entries = findings[tier]
        for m in entries[:cap]:
            emit(f"hidden unicode: {m}")
        if len(entries) > cap:
            emit(f"hidden unicode: +{len(entries) - cap} more {tier} finding(s)")
    if findings["info"]:
        info(
            f"hidden unicode: non-breaking spaces in {len(findings['info'])} file(s) "
            "(informational — common in pasted prose)"
        )
    if not findings["critical"] and not findings["warning"]:
        good("deployed prose is free of hidden/deceptive Unicode")


def _strict_schema_artifact(
    path: Path,
    schema_name: str,
    fail: Callable[[str], None],
    good: Callable[[str], None],
) -> None:
    """Validate a persisted JSON artifact against its JSON Schema, failing closed."""
    from claude_kit import schemas

    if not schemas.available():
        fail(
            "jsonschema not installed — strict validation cannot continue; "
            "repair the claude-code-kit installation"
        )
        return
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"{path.name} is invalid JSON: {exc}")
        return
    with ExitStack() as stack:
        errs = schemas.validate_doc(doc, schema_name, stack)
    if errs:
        fail(f"{path.name} fails its JSON Schema: " + "; ".join(errs[:6]))
    else:
        good(f"{path.name} matches the {schema_name} schema")


def _strict_yaml_schema_artifact(
    path: Path,
    schema_name: str,
    fail: Callable[[str], None],
    good: Callable[[str], None],
) -> None:
    """Validate a persisted YAML artifact against its JSON Schema, failing closed."""
    from claude_kit import schemas

    if not schemas.available():
        fail(
            "jsonschema not installed — strict validation cannot continue; "
            "repair the claude-code-kit installation"
        )
        return
    import yaml

    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        fail(f"{path.name} is invalid YAML: {exc}")
        return
    if (
        schema_name == "stack-catalog-snapshot"
        and isinstance(doc, dict)
        and "schema_version" not in doc
    ):
        fail(
            f"{path.name} is a legacy unversioned stack snapshot; "
            "run `claude-kit upgrade` to migrate its gate-policy metadata"
        )
        return
    with ExitStack() as stack:
        errs = schemas.validate_doc(doc, schema_name, stack)
    if errs:
        fail(f"{path.name} fails its JSON Schema: " + "; ".join(errs[:6]))
    else:
        good(f"{path.name} matches the {schema_name} schema")


def _strict_settings_hooks(
    claude: Path,
    doc: dict,
    fail: Callable[[str], None],
    warn: Callable[[str], None],
    good: Callable[[str], None],
) -> None:
    """Check hook scripts and flag events outside the tested compatibility catalog."""
    clean = True
    hooks = doc.get("hooks")
    if hooks is None:
        hooks = {}
    if not isinstance(hooks, dict):
        fail("settings.json 'hooks' must be an object")
        return
    for event, groups in hooks.items():
        if not isinstance(event, str) or not isinstance(groups, list):
            fail("settings.json hook entries must map event names to arrays")
            clean = False
            continue
        if event not in KNOWN_EVENTS:
            warn(
                f"settings.json hook event {event!r} is not in the tested compatibility catalog; "
                "run the official validator (`claude plugin validate . --strict`) with the "
                "target Claude Code version"
            )
            clean = False
        for grp in groups:
            if not isinstance(grp, dict):
                fail(f"settings.json hook event {event!r} contains a non-object group")
                clean = False
                continue
            entries = grp.get("hooks") or []
            if not isinstance(entries, list):
                fail(f"settings.json hook event {event!r} has a non-array hooks field")
                clean = False
                continue
            for entry in entries:
                if not isinstance(entry, dict) or not isinstance(
                    entry.get("command", ""), str
                ):
                    fail(
                        f"settings.json hook event {event!r} contains an invalid hook command"
                    )
                    clean = False
                    continue
                for script in _HOOK_SCRIPT_RE.findall(entry.get("command", "")):
                    sp = claude / "hooks" / script
                    if not sp.is_file():
                        fail(
                            f"settings.json hook references a missing script: {script}"
                        )
                        clean = False
                    elif not (sp.stat().st_mode & 0o111):
                        fail(f"hook script not executable: .claude/hooks/{script}")
                        clean = False
    if clean:
        good("settings.json hooks fire on known events and run installed scripts")


def _strict_mcp_shape(
    mcp: Path, fail: Callable[[str], None], good: Callable[[str], None]
) -> None:
    """.mcp.json must be a ``{mcpServers: {id: {command|url, ...}}}`` document."""
    try:
        doc = json.loads(mcp.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f".mcp.json is invalid JSON: {exc}")
        return
    if not isinstance(doc, dict):
        fail(".mcp.json root must be an object")
        return
    servers = doc.get("mcpServers")
    if not isinstance(servers, dict):
        fail(".mcp.json has no valid 'mcpServers' object")
        return
    clean = True
    for sid, cfg in servers.items():
        if not isinstance(cfg, dict) or not (cfg.get("command") or cfg.get("url")):
            fail(f".mcp.json server {sid!r} has neither a command nor a url")
            clean = False
    if clean:
        good(f".mcp.json shape is valid ({len(servers)} server(s))")


def _strict_snapshot(
    claude: Path,
    snap: Path,
    fail: Callable[[str], None],
    good: Callable[[str], None],
) -> None:
    """The resolved stack snapshot must not list agents/skills/overlays absent from the install."""
    import yaml

    try:
        data = yaml.safe_load(snap.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        fail(f"stack snapshot is invalid YAML: {exc}")
        return
    if not isinstance(data, dict):
        fail("stack snapshot root must be an object")
        return

    def string_list(name: str) -> list[str]:
        raw = data.get(name) or []
        if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
            fail(f"stack snapshot {name!r} must be an array of strings")
            return []
        return raw

    missing: list[str] = []
    for agent in string_list("agents") + string_list("overlay_agents"):
        if not (claude / "agents" / f"{agent}.md").is_file():
            missing.append(f"agents/{agent}.md")
    for skill in string_list("skills"):
        if not (claude / "skills" / skill / "SKILL.md").is_file():
            missing.append(f"skills/{skill}/SKILL.md")
    for rule in string_list("overlay_rules"):
        if not (claude / "rules" / rule).is_file():
            missing.append(f"rules/{rule}")
    if missing:
        fail("stack snapshot lists files not installed: " + ", ".join(sorted(missing)))
    else:
        good("stack snapshot agrees with installed agents/skills/overlay files")


# --- catalog referential integrity (the kit's own data, checked against the payload) --------------


def _iter_stack_entries(stacks: dict) -> list[tuple[dict, str]]:
    """Yield ``(entry, stack_dir)`` for every non-planned frontend/backend/database stack entry."""
    out: list[tuple[dict, str]] = []
    for fw in (stacks.get("frontend", {}).get("frameworks", {}) or {}).values():
        if fw.get("status") != "planned":
            out.append((fw, str(fw.get("stack_dir", ""))))
    for lang in (stacks.get("backend", {}).get("languages", {}) or {}).values():
        if lang.get("status") == "planned":
            continue
        for fw in (lang.get("frameworks", {}) or {}).values():
            if fw.get("status") != "planned":
                out.append((fw, str(fw.get("stack_dir", ""))))
    for db in (stacks.get("database", {}).get("options", {}) or {}).values():
        if db.get("status") != "planned":
            out.append((db, str(db.get("stack_dir", ""))))
    return out


def _check_duplicate_skills(
    profiles: dict,
    cfail: Callable[[str], None],
    cgood: Callable[[str], None],
) -> None:
    """No profile may list the same skill twice in its own raw ``skills:`` list.

    Checks each profile's un-inherited list (not the resolved union, which dedupes by design), so it
    catches an accidental copy-paste in ``catalog/profiles.yaml``. The ``skills: all`` sentinel (a
    string) and any non-list value are skipped.
    """
    from collections import Counter

    dupes = False
    for name, prof in (profiles.get("profiles") or {}).items():
        skills = prof.get("skills") if isinstance(prof, dict) else None
        if not isinstance(skills, list):
            continue  # `all` sentinel or absent
        for skill, count in Counter(skills).items():
            if count > 1:
                dupes = True
                cfail(f"profile {name!r} has duplicate skill {skill!r} in skills list")
    if not dupes:
        cgood("no profile lists a duplicate skill")


def check_catalog(
    payload_root: str | Path | None = None, *, require_schema: bool = False
) -> tuple[bool, list[str]]:
    """Check the kit catalog is referentially consistent (used by ``validate --strict`` / CI).

    Unlike :func:`claude_kit.catalog.resolve` (which validates *ids*), this confirms the referenced
    files physically exist — the gap that today only surfaces as a soft "missing (skipped)" line at
    install time. Verifies that every profile resolves to existing agents/skills/registered hooks,
    every stack's overlay rule/agent file is present on disk, and (if ``org.yaml`` exists) the org
    layer's new skills/agents/rules/packs and added core agents all exist.

    Args:
        payload_root: Payload root to check. Defaults to the bundled payload (the installed kit).

    Returns:
        ``(ok, messages)`` with each message prefixed ``OK``/``FAIL`` and tagged ``catalog:``.
    """
    from claude_kit import catalog

    msgs: list[str] = []
    ok = True

    def cfail(m: str) -> None:
        nonlocal ok
        ok = False
        msgs.append(f"FAIL  catalog: {m}")

    def cgood(m: str) -> None:
        msgs.append(f"OK    catalog: {m}")

    with ExitStack() as stack:
        if payload_root is None:
            from claude_kit import scaffold

            payload_root = scaffold.payload_dir(stack)
        payload_root = Path(payload_root)

        stacks = catalog._load(payload_root, "stacks.yaml")
        profiles = catalog._load(payload_root, "profiles.yaml")
        avail = catalog.available(payload_root)
        agent_set = set(avail["agents"])
        skill_set = set(avail["skills"])
        hook_set = set(avail["hooks"])

        prof_missing: set[str] = set()
        for name in profiles.get("profiles", {}):
            res = catalog._resolve_profile(profiles, name, avail)
            prof_missing |= {
                f"{name}: agent {a}" for a in res["agents"] if a not in agent_set
            }
            prof_missing |= {
                f"{name}: skill {s}" for s in res["skills"] if s not in skill_set
            }
            prof_missing |= {
                f"{name}: hook {h}" for h in res["hooks"] if h not in hook_set
            }
        if prof_missing:
            cfail(
                "profiles reference missing components: "
                + "; ".join(sorted(prof_missing))
            )
        else:
            cgood(
                f"{len(profiles.get('profiles', {}))} profiles reference only existing "
                "agents/skills/hooks"
            )

        _check_duplicate_skills(profiles, cfail, cgood)

        overlay_missing: set[str] = set()
        stack_skill_missing: set[str] = set()
        templates = payload_root / "templates" / "stacks"
        for entry, stack_dir in _iter_stack_entries(stacks):
            for rule in entry.get("overlay_rules", []) or []:
                if stack_dir and not (templates / stack_dir / "rules" / rule).is_file():
                    overlay_missing.add(f"{stack_dir}/rules/{rule}")
            for agent in entry.get("overlay_agents", []) or []:
                if (
                    stack_dir
                    and not (templates / stack_dir / "agents" / f"{agent}.md").is_file()
                ):
                    overlay_missing.add(f"{stack_dir}/agents/{agent}.md")
            for skill in entry.get("skills", []) or []:
                if skill not in skill_set:
                    stack_skill_missing.add(skill)
        if overlay_missing:
            cfail("stack overlay files missing: " + ", ".join(sorted(overlay_missing)))
        else:
            cgood("stack overlay rule/agent files all present")
        if stack_skill_missing:
            cfail(
                "stacks suggest missing skills: "
                + ", ".join(sorted(stack_skill_missing))
            )

        org_path = catalog.catalog_dir(payload_root) / "org.yaml"
        if org_path.is_file():
            _check_org_catalog(payload_root, catalog, agent_set, cfail, cgood)

        from claude_kit.components import MCPServerSpec

        mcp_path = catalog.catalog_dir(payload_root) / "mcp.yaml"
        if mcp_path.is_file():
            mcp_document = catalog._load(payload_root, "mcp.yaml")
            mcp_servers = mcp_document.get("servers", {})
            semantic_failures: list[str] = []
            if not isinstance(mcp_servers, dict):
                semantic_failures.append("servers must be a mapping")
            else:
                for server_id, record in mcp_servers.items():
                    try:
                        if not isinstance(record, dict):
                            raise ValueError("record must be a mapping")
                        MCPServerSpec.from_catalog(str(server_id), record)
                    except (TypeError, ValueError) as exc:
                        semantic_failures.append(f"{server_id}: {exc}")
            if semantic_failures:
                cfail(
                    "MCP semantic definitions are invalid: "
                    + "; ".join(semantic_failures)
                )
            else:
                cgood(f"{len(mcp_servers)} MCP definitions pass semantic validation")

        _check_catalog_schemas(
            payload_root, catalog, stack, cfail, cgood, msgs, require_schema
        )

    return ok, msgs


def _check_catalog_schemas(
    payload_root: Path,
    catalog,  # noqa: ANN001 - the module, imported lazily by the caller
    stack: ExitStack,
    cfail: Callable[[str], None],
    cgood: Callable[[str], None],
    msgs: list[str],
    require_schema: bool,
) -> None:
    """Structurally validate catalog files + org pack manifests against their JSON Schemas.

    A missing runtime dependency is a failure when called from strict validation.
    """
    from claude_kit import schemas

    if not schemas.available():
        message = (
            "jsonschema not installed — strict validation cannot continue; "
            "repair the claude-code-kit installation"
        )
        if require_schema:
            cfail(message)
        else:
            msgs.append(f"WARN  catalog: {message}")
        return

    cat_dir = catalog.catalog_dir(payload_root)
    file_schemas = [
        ("stacks", "stacks.yaml"),
        ("profiles", "profiles.yaml"),
        ("mcp", "mcp.yaml"),
        ("capture", "capture.yaml"),
        ("claude-compatibility", "claude-compatibility.yaml"),
        ("codex-compatibility", "codex-compatibility.yaml"),
        ("plugin-metadata", "plugin-metadata.yaml"),
        ("workflow", "workflows/sdlc.yaml"),
    ]
    if (cat_dir / "org.yaml").is_file():
        file_schemas.append(("org", "org.yaml"))
    for sname, fn in file_schemas:
        if not (cat_dir / fn).is_file():
            continue
        errs = schemas.validate_doc(catalog._load(payload_root, fn), sname, stack)
        if errs:
            cfail(f"{fn} fails its JSON Schema: " + "; ".join(errs[:6]))
        else:
            cgood(f"{fn} matches its JSON Schema")

    import yaml

    packs_dir = payload_root / "templates" / "org" / "packs"
    pack_files = sorted(packs_dir.glob("*/pack.yaml")) if packs_dir.is_dir() else []
    pack_bad = False
    for pf in pack_files:
        doc = yaml.safe_load(pf.read_text(encoding="utf-8"))
        errs = schemas.validate_doc(doc, "org-pack", stack)
        if errs:
            cfail(
                f"{pf.parent.name}/pack.yaml fails its JSON Schema: "
                + "; ".join(errs[:6])
            )
            pack_bad = True
    if pack_files and not pack_bad:
        cgood(f"{len(pack_files)} org pack manifest(s) match the org-pack schema")


def _check_org_catalog(
    payload_root: Path,
    catalog,  # noqa: ANN001 - the module, imported lazily by the caller
    agent_set: set[str],
    cfail: Callable[[str], None],
    cgood: Callable[[str], None],
) -> None:
    """Check the org overlay's new skills/agents/rules/packs and added core agents all exist."""
    org = catalog._load(payload_root, "org.yaml")
    org_root = payload_root / "templates" / "org"
    missing: list[str] = []
    for skill in org.get("new_skills", []) or []:
        if not (org_root / "skills" / skill / "SKILL.md").is_file():
            missing.append(f"skills/{skill}/SKILL.md")
    for agent in org.get("new_agents", []) or []:
        if not (org_root / "agents" / f"{agent}.md").is_file():
            missing.append(f"agents/{agent}.md")
    for rule in org.get("new_rules", []) or []:
        if not (org_root / "rules" / rule).is_file():
            missing.append(f"rules/{rule}")
    for pack in org.get("packs", []) or []:
        pid = pack.get("id") if isinstance(pack, dict) else pack
        if pid and not (org_root / "packs" / pid / "pack.yaml").is_file():
            missing.append(f"packs/{pid}/pack.yaml")
    bad_agents = [
        a for a in org.get("core_agents_added", []) or [] if a not in agent_set
    ]
    if missing:
        cfail("org overlay files missing: " + ", ".join(sorted(missing)))
    if bad_agents:
        cfail(
            "org core_agents_added not found in agents/: "
            + ", ".join(sorted(bad_agents))
        )
    if not missing and not bad_agents:
        cgood("org overlay skills/agents/rules/packs all present")


# --- doctor (validate + environment) --------------------------------------------------------------


def _version_tuple(value: str) -> tuple[int, int, int]:
    """Parse the numeric core of a Claude Code version for compatibility comparisons."""
    match = re.search(r"(?<!\d)(\d+)\.(\d+)\.(\d+)(?!\d)", value)
    if not match:
        raise ValueError(f"unrecognized version: {value!r}")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def _claude_version(executable: str) -> str | None:
    """Return Claude Code's semantic version, or ``None`` when it cannot be queried safely."""
    try:
        proc = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            check=False,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    match = re.search(r"(?<!\d)(\d+\.\d+\.\d+)(?!\d)", proc.stdout)
    return match.group(1) if match else None


def _claude_code_health(msgs: list[str]) -> None:
    """Append missing/tested/untested/unsupported Claude Code compatibility state."""
    executable = shutil.which("claude")
    if not executable:
        msgs.append(
            "WARN  Claude Code not on PATH — official plugin validation and runtime compatibility "
            "could not be checked"
        )
        return
    version = _claude_version(executable)
    if version is None:
        msgs.append(
            f"WARN  Claude Code found at {executable}, but its version is unreadable"
        )
        return

    policy = CLAUDE_CODE_COMPATIBILITY
    minimum = str(policy["minimum"])
    if _version_tuple(version) < _version_tuple(minimum):
        msgs.append(
            f"WARN  Claude Code {version} is unsupported; minimum is {minimum} "
            "(upgrade before relying on hooks)"
        )
        return

    tested = {str(item["version"]) for item in policy.get("tested", [])}
    if version in tested:
        msgs.append(f"OK    Claude Code {version} is supported and tested")
    else:
        msgs.append(
            f"WARN  Claude Code {version} is supported but is not in the tested matrix; "
            "run `claude plugin validate . --strict`"
        )

    for feature, spec in policy.get("features", {}).items():
        feature_min = str(spec["minimum_version"])
        if not spec.get("required") and _version_tuple(version) < _version_tuple(
            feature_min
        ):
            msgs.append(
                f"INFO  optional feature unavailable: {feature} requires Claude Code {feature_min}+"
            )


def _codex_health(msgs: list[str]) -> None:
    """Append missing/tested/untested/unsupported Codex compatibility state."""

    executable = shutil.which("codex")
    if not executable:
        msgs.append(
            "WARN  Codex not on PATH — native project discovery and runtime compatibility "
            "could not be checked"
        )
        return
    version = _claude_version(executable)
    if version is None:
        msgs.append(f"WARN  Codex found at {executable}, but its version is unreadable")
        return
    minimum = str(CODEX_COMPATIBILITY["minimum"])
    if _version_tuple(version) < _version_tuple(minimum):
        msgs.append(
            f"WARN  Codex {version} is unsupported; minimum is {minimum} "
            "(upgrade before relying on native agents/hooks)"
        )
        return
    tested = {str(item["version"]) for item in CODEX_COMPATIBILITY.get("tested", [])}
    if version in tested:
        msgs.append(f"OK    Codex {version} is supported and tested")
    else:
        msgs.append(
            f"WARN  Codex {version} is supported but is not in the tested matrix; "
            "run the pinned Codex compatibility smoke before relying on hooks"
        )


def _installed_kit_plugin_state(
    executable: str, host: str, target: Path
) -> bool | None:
    """Return whether the native host reports an installed claude-kit plugin.

    ``doctor`` deliberately asks the host instead of decoding private, versioned registry files.
    The command is read-only, receives no prompt, and its output is never copied into diagnostics.
    ``None`` means the installed host could not provide a trustworthy JSON inventory.
    """

    try:
        result = subprocess.run(
            [executable, "plugin", "list", "--json"],
            cwd=target,
            stdin=subprocess.DEVNULL,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    try:
        document = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError):
        return None

    if host == "claude":
        if not isinstance(document, list):
            return None
        return any(
            isinstance(entry, dict)
            and entry.get("id") == _KIT_PLUGIN_ID
            and entry.get("enabled", True) is not False
            for entry in document
        )

    if host == "codex":
        if not isinstance(document, dict) or not isinstance(
            document.get("installed"), list
        ):
            return None
        return any(
            isinstance(entry, dict)
            and entry.get("pluginId") == _KIT_PLUGIN_ID
            and entry.get("installed", True) is not False
            and entry.get("enabled", True) is not False
            for entry in document["installed"]
        )
    raise ValueError(f"unsupported host plugin inventory: {host}")


def _doctor_runtime_summary(
    target: Path, runtimes: set[str], state_root: str, msgs: list[str]
) -> None:
    installed = ", ".join(sorted(runtimes)) or "none"
    msgs.append(f"OK    installed runtime(s): {installed}; mutable state: {state_root}")
    detected = [name for name in ("claude", "codex") if shutil.which(name)]
    msgs.append(
        "INFO  detected host CLI(s): " + (", ".join(detected) if detected else "none")
    )

    if "claude" in runtimes:
        msgs.append(
            "INFO  Claude fidelity: instructions/agents/skills/rules/hooks native; shared ledger "
            "and runtime-selectable capture adapted"
        )
    if "codex" in runtimes:
        msgs.append(
            "INFO  Codex fidelity: instructions native; rules and MCP adapted; skill, custom-agent, "
            "and hook behavior degraded pending protected native-host smokes; historical-session "
            "capture degraded (session-end and per-task capture remain active)"
        )
        msgs.append(
            "WARN  Codex trust boundary: project hooks and configuration execute only after the "
            "project is explicitly trusted; core gates remain enforced by the Python ledger"
        )

    duplicate_hosts: list[str] = []
    if "claude" in runtimes and (target / ".claude-plugin/plugin.json").is_file():
        duplicate_hosts.append("Claude")
    if "codex" in runtimes and (target / ".codex-plugin/plugin.json").is_file():
        duplicate_hosts.append("Codex")
    if duplicate_hosts:
        msgs.append(
            "WARN  duplicate project-local delivery detected for "
            + ", ".join(duplicate_hosts)
            + ": plugin source and scaffold surfaces coexist; enable only one hook/skill delivery "
            "path per host to avoid duplicate SessionStart and skills"
        )
    else:
        msgs.append("OK    no project-local plugin-plus-scaffold duplication detected")

    installed_plugin_hosts: list[str] = []
    checked_plugin_hosts: list[str] = []
    unavailable_plugin_hosts: list[str] = []
    for host, label in (("claude", "Claude"), ("codex", "Codex")):
        if host not in runtimes:
            continue
        executable = shutil.which(host)
        if executable is None:
            unavailable_plugin_hosts.append(label)
            continue
        state = _installed_kit_plugin_state(executable, host, target)
        if state is None:
            unavailable_plugin_hosts.append(label)
        elif state:
            installed_plugin_hosts.append(label)
        else:
            checked_plugin_hosts.append(label)

    if installed_plugin_hosts:
        msgs.append(
            "WARN  duplicate installed-plugin delivery detected for "
            + ", ".join(installed_plugin_hosts)
            + ": the enabled claude-kit plugin and project scaffold can expose the same skills, "
            "hooks, MCP servers, or SessionStart behavior; disable one delivery path per host"
        )
    if checked_plugin_hosts:
        msgs.append(
            "OK    no enabled installed claude-kit plugin duplicates the scaffold for "
            + ", ".join(checked_plugin_hosts)
        )
    if unavailable_plugin_hosts:
        msgs.append(
            "INFO  installed-plugin duplication could not be checked for "
            + ", ".join(unavailable_plugin_hosts)
            + "; run doctor again with the native host CLI and a readable local plugin registry"
        )


def doctor(target: str | Path, *, mcp: bool = False) -> tuple[bool, list[str]]:
    """Run a strict :func:`validate` plus environment/health checks.

    Note: ``doctor`` runs validation in **strict** mode, so it can FAIL on a deliberately hand-edited
    install (e.g. an agent/skill file removed by hand while the snapshot still records it). For a
    lenient structural check of a customized ``.claude/``, use ``validate`` without ``--strict``.

    Args:
        target: Project root to check.
        mcp: Also run MCP health checks (commands on PATH, ``${ENV}`` vars set, lockfile agreement).

    Returns:
        ``(ok, messages)``; environment issues are warnings (do not fail) unless they break config.
    """
    ok, msgs = validate(target, strict=True)
    target = Path(target).expanduser().resolve()
    layout = detect_state_layout(target, fresh_default=StateLayout.legacy_claude())
    options, _options_error = _read_init_options(target / layout.root)
    if options is not None:
        runtimes = set(options.runtimes)
    elif layout == StateLayout.legacy_claude():
        runtimes = {"claude"}
    else:
        runtimes = set()

    _doctor_runtime_summary(target, runtimes, layout.root, msgs)

    for tool, why in (
        ("git", "version control"),
        ("jq", "command hooks parse tool input with jq"),
    ):
        if shutil.which(tool):
            msgs.append(f"OK    {tool} found ({why})")
        else:
            msgs.append(f"WARN  {tool} not on PATH — {why}")

    if "claude" in runtimes:
        _claude_code_health(msgs)
    if "codex" in runtimes:
        _codex_health(msgs)

    # Native pathname fallbacks cannot exclude a junction swap. Mutation therefore fails closed;
    # read-only/plugin use remains distinguishable from the shell-hook runtime limitation.
    if platform.system() == "Windows":
        msgs.append(
            "WARN  native Windows project mutation is unsupported in this release — init, merge, "
            "upgrade, export, and pipeline writes require WSL on a filesystem with POSIX "
            "descriptor and lock semantics; read-only inspection and plugin discovery remain "
            "available"
        )
        if shutil.which("jq"):
            msgs.append(
                "INFO  jq is on PATH, but .sh hooks still require a POSIX shell such as WSL"
            )
        else:
            msgs.append(
                "WARN  Windows detected and jq not on PATH — the shell hooks (guard-*, warn-*) will "
                "no-op. Run claude-kit inside WSL with jq to enable them."
            )

    hook_roots: list[tuple[str, Path]] = []
    if "claude" in runtimes:
        hook_roots.append((".claude/hooks", target / ".claude" / "hooks"))
    if "codex" in runtimes:
        hook_roots.append(
            (".codex/hooks/scripts", target / ".codex" / "hooks" / "scripts")
        )
    for hook_rel, hooks_dir in hook_roots:
        if not hooks_dir.is_dir():
            continue
        scripts = list(hooks_dir.glob("*.sh"))
        nonexec = [path.name for path in scripts if not (path.stat().st_mode & 0o111)]
        if nonexec:
            msgs.append(
                f"WARN  hook scripts not executable in {hook_rel}: "
                f"{', '.join(sorted(nonexec))} (run: chmod +x {hook_rel}/*.sh)"
            )
        elif scripts:
            msgs.append(f"OK    hook scripts are executable ({hook_rel})")

    gitignore = target / ".gitignore"
    gi = gitignore.read_text(encoding="utf-8") if gitignore.is_file() else ""
    for entry in (f"{layout.state}/", f"{layout.temporary}/"):
        if entry in gi:
            msgs.append(f"OK    {entry} is gitignored")
        else:
            msgs.append(
                f"WARN  {entry} not gitignored (runtime artifacts may be committed)"
            )

    capture_documents = []
    if "claude" in runtimes:
        capture_documents.append(target / ".claude" / "settings.json")
    if "codex" in runtimes:
        capture_documents.append(target / ".codex" / "hooks.json")
    if any(
        document.is_file()
        and "capture-learnings" in document.read_text(encoding="utf-8")
        for document in capture_documents
    ):
        msgs.append(
            "WARN  learning capture is enabled — a provider-selected background job reads the host "
            f"transcript when available plus changed files and writes notes to {layout.memory}/ "
            "(committed). Secret files are skipped and secret-shaped values redacted; review entries "
            "before committing. Disable with CKIT_NO_AUTOCAPTURE=1; bound with "
            "CKIT_CAPTURE_MAX_LINES/_MAX_BYTES (legacy CLAUDE_KIT_* aliases remain accepted)."
        )

    transaction_doc: dict | None = None
    try:
        transaction_doc = inspect_interrupted_transaction(ProjectFS(target))
    except OSError as exc:
        msgs.append(
            "WARN  interrupted transaction marker could not be inspected safely — "
            f"{exc}; do not mutate this project until the marker is repaired"
        )
    if transaction_doc is not None:
        detail = ""
        operation = "upgrade"
        recovery = "`claude-kit upgrade`"
        rollback = ""
        try:
            if transaction_doc.get(
                "schema_version"
            ) == TRANSACTION_SCHEMA and transaction_doc.get("transaction_kind") in {
                "install",
                "force",
                "merge",
                "upgrade",
            }:
                operation = transaction_doc["transaction_kind"]
                detail = (
                    f" ({transaction_doc.get('from_version', '')} -> "
                    f"{transaction_doc.get('to_version', '')}, started "
                    f"{transaction_doc.get('started_at', '')})"
                )
                recovery = {
                    "install": "`claude-kit init`",
                    "force": "`claude-kit init --force`",
                    "merge": "`claude-kit init --merge`",
                    "upgrade": "`claude-kit upgrade`",
                }[operation]
                rollback = (
                    "; the durable commit is complete but transaction cleanup is pending"
                    if transaction_doc.get("phase") == "committed"
                    else "; the schema-v2 journal is rollback-capable"
                )
            else:
                j = UpgradeJournal.from_dict(transaction_doc)
                detail = (
                    f" ({j.from_version} -> {j.to_version}, started {j.started_at})"
                )
        except (TypeError, ValueError):
            detail = ""
        msgs.append(
            f"WARN  interrupted {operation} detected{detail}{rollback} — re-run {recovery} to "
            "recover and finish (the operation is convergent and clears the journal)"
        )

    if mcp:
        if options is not None:
            _doctor_mcp_semantic_summary(options.selection, runtimes, msgs)
        _mcp_health(target, msgs)

    return ok, msgs


def _mcp_health(target: Path, msgs: list[str]) -> None:
    """Append provider-native MCP command/auth/lock health diagnostics (warn-only)."""

    claude_mcp = target / ".mcp.json"
    codex_mcp = target / ".codex" / "config.toml"
    surfaces: list[tuple[str, dict]] = []
    claude_servers: dict | None = None
    if claude_mcp.is_file():
        try:
            document = json.loads(claude_mcp.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            msgs.append(f"WARN  .mcp.json unreadable for MCP health checks: {exc}")
        else:
            if not isinstance(document, dict) or not isinstance(
                document.get("mcpServers"), dict
            ):
                msgs.append(
                    "WARN  .mcp.json has no valid mcpServers object for health checks"
                )
            else:
                claude_servers = document["mcpServers"]
                surfaces.append((".mcp.json", claude_servers))
    if codex_mcp.is_file():
        source = ".codex/config.toml"
        try:
            document = tomllib.loads(codex_mcp.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            msgs.append(f"WARN  {source} unreadable for MCP health checks: {exc}")
        else:
            candidate = document.get("mcp_servers", {})
            if not isinstance(candidate, dict):
                msgs.append(f"WARN  {source} has no valid mcp_servers table")
            else:
                surfaces.append((source, candidate))
    if not claude_mcp.is_file() and not codex_mcp.is_file():
        msgs.append("OK    no .mcp.json (no MCP servers configured)")
        return

    for source, servers in surfaces:
        if not servers:
            msgs.append(f"OK    no MCP servers configured in {source}")
            continue
        for sid, cfg in servers.items():
            command = cfg.get("command") if isinstance(cfg, dict) else None
            if command and not shutil.which(command):
                msgs.append(
                    f"WARN  MCP {sid}: command {command!r} not on PATH ({source})"
                )
            elif command:
                msgs.append(f"OK    MCP {sid}: command {command!r} found ({source})")
            explicit_env = (
                {str(item) for item in cfg.get("env_vars", []) if isinstance(item, str)}
                if isinstance(cfg, dict) and isinstance(cfg.get("env_vars", []), list)
                else set()
            )
            referenced_env = set(_ENV_VAR_RE.findall(json.dumps(cfg))) | explicit_env
            for var in sorted(referenced_env):
                if not os.environ.get(var):
                    msgs.append(
                        f"WARN  MCP {sid}: env var ${{{var}}} is not set ({source})"
                    )

    lock = target / ".mcp.lock.json"
    if claude_servers is not None and lock.is_file():
        try:
            lock_document = json.loads(lock.read_text(encoding="utf-8"))
            if not isinstance(lock_document, dict) or not isinstance(
                lock_document.get("servers"), dict
            ):
                raise ValueError("lock root/servers has the wrong shape")
            locked = set(lock_document["servers"])
        except (json.JSONDecodeError, ValueError):
            locked = set()
        if locked != set(claude_servers):
            msgs.append(
                "WARN  .mcp.lock.json is out of sync with .mcp.json "
                "(run `claude-kit upgrade` to regenerate)"
            )
        else:
            msgs.append("OK    .mcp.lock.json matches .mcp.json")
