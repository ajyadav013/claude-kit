"""Deterministic, non-executing operations on the ``/sdlc`` pipeline state files.

The ``/sdlc`` skill drives the actual pipeline; this module only **validates and mutates the state
files** it leaves behind, so a human or CI can inspect a run, record a passed gate with evidence, or
abort — without an LLM in the loop. It reads the runtime snapshot ``.claude/state/pipeline-snapshot.json``
(schema in ``rules/continuity.md``) and cross-checks gate names against the **execution-ordered**
gate list recorded in ``.claude/config/stack-catalog.snapshot.yaml``. Every function returns the
``(ok, messages)`` contract used by :mod:`claude_kit.validator`.

Trust model (schema v2):

- A run is created explicitly with ``start`` or ``adopt`` and is bound to repository root, branch,
  commits, active ordered gates, and the digest of their canonical catalog definitions. Completion
  and abort are terminal. Legacy v1 snapshots remain readable with warnings and migrate only via an
  explicit adoption that preserves the old record.
- Gate resolutions are ``passed``, catalog-authorized ``not-applicable``, or the distinct
  ``accepted-risk`` status for structured Medium exceptions. Critical/High have no waiver; Medium
  never becomes an ordinary PASS; required gates cannot be skipped. Old ``skipped``/``overridden``
  entries are compatibility inputs, not valid schema-v2 transitions.
- **Order is enforced.** Fresh runs begin at the first installed gate. Only ``adopt`` may establish
  historical earlier gates; every later resolution follows the frozen ordered list. ``--force``
  cannot bypass findings or order.
- **Evidence is content-addressed and portable.** ``validate`` re-hashes every historical entry, so
  evidence cannot silently change after its gate closed. Evidence paths are resolved against the
  **project root** (never the process CWD) and stored project-relative when inside it, so a ledger
  survives a different checkout path (CI).
- **Writes are atomic and root-bound** through :class:`ProjectFS`, under an ``O_EXCL`` lock held
  across the whole read-modify-write. Lock age is never treated as ownership proof; contention
  fails closed instead of risking an ABA unlink race.
- **Terminal runs are closed.** No transition follows ``completed`` or ``aborted``.
- **Strict mode fails closed**: with ``strict=True`` a missing/unreadable install snapshot is an
  error, not a warning (for CI; the lenient default keeps mid-run human use workable).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import stat
import subprocess
import time
import uuid
from collections.abc import Iterator, Mapping
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional, Sequence, cast

import yaml

from claude_kit import __version__
from claude_kit.components import Capability
from claude_kit.models import (
    GateDefinition,
    InitOptions,
    StateLayout,
    digest_gate_definitions,
)
from claude_kit.program_runtime import ProgramManifest, ProgramManifestBinding
from claude_kit.secure_fs import ProjectFS, UnsafePathError
from claude_kit.state import detect_state_layout
from claude_kit.workflow_evidence import (
    EVIDENCE_CONTRACT_VERSION,
    MAX_EVIDENCE_ENVELOPE_BYTES,
    EvidenceValidationError,
    managed_evidence_projection,
    normalized_findings,
    parse_evidence_envelope,
    validate_evidence_document,
)
from claude_kit.worktrees import (
    WorkspaceCheckpoint,
    WorktreeError,
    WorktreeManager,
    WorktreeStatus,
)

#: Legacy runtime pipeline snapshot retained as a public compatibility constant.
SNAPSHOT_REL = ".claude/state/pipeline-snapshot.json"
#: Legacy install snapshot retained as a public compatibility constant.
STACK_SNAPSHOT_REL = ".claude/config/stack-catalog.snapshot.yaml"
#: Current explicit lifecycle schema. Legacy snapshots used optional ``schema: 1``.
PIPELINE_SCHEMA_VERSION = 2

#: Raw headless-loop transition tokens are process-local. Only their position-bound digest is
#: persisted, and an iteration expires fail-closed for token-bearing commands after this window.
HEADLESS_TRANSITION_TOKEN_ENV = "CKIT_PIPELINE_TRANSITION_TOKEN"
HEADLESS_TRANSITION_ALLOWANCE_VERSION = 1
HEADLESS_TRANSITION_ALLOWANCE_TTL_S = 60 * 60
_MAX_PROVIDER_CONTROL_FILES = 10_000
_MAX_PROVIDER_CONTROL_BYTES = 512 * 1024 * 1024
_PROVIDER_CONTROL_HASH_TIMEOUT_SECONDS = 20
_MAX_PROGRAM_ARTIFACT_BYTES = 4 * 1024 * 1024
_MAX_PROGRAM_SAFEGUARD_BYTES = 8 * 1024 * 1024
_MAX_PROGRAM_SAFEGUARD_AGGREGATE_BYTES = 64 * 1024 * 1024
_MAX_MANAGED_OUTPUT_ARTIFACT_BYTES = 8 * 1024 * 1024

#: Closed value-sets the snapshot fields must draw from (see rules/continuity.md).
PROFILES = frozenset({"lean", "standard", "enterprise"})
SCOPES = frozenset({"individual", "team", "organization"})
MODES = frozenset({"A", "B", "C", "D", "E"})
LANE_STATES = frozenset({"not-started", "in-progress", "passed", "failed"})
FINDING_KEYS = frozenset({"critical", "high", "medium", "low", "cosmetic"})
#: Ledger entry statuses and verification levels (gate_history in rules/continuity.md).
GATE_STATUSES = frozenset(
    {"passed", "not-applicable", "accepted-risk", "failed", "aborted"}
)
LEGACY_GATE_STATUSES = frozenset({"passed", "skipped", "overridden"})
POSITION_STATUSES = frozenset({"passed", "not-applicable", "accepted-risk"})
VERIFICATIONS = frozenset({"agent", "mechanical", "human", "override"})
RUN_STATUSES = frozenset({"active", "completed", "aborted"})
HUMAN_STOP_REASONS = frozenset(
    {
        "missing-requirements",
        "scope-expansion",
        "irreversible-operation",
        "external-side-effect",
        "operator-aborted",
        "retry-budget-exhausted",
        "conflicting-evidence",
        "unsupported-required-capability",
    }
)
STAGE_STATUSES = frozenset({"running", "succeeded", "failed", "cancelled"})
TERMINAL_STAGE_STATUSES = STAGE_STATUSES - {"running"}
PROGRAM_UNIT_STATUSES = frozenset({"running", "succeeded", "failed", "cancelled"})
PROGRAM_EXECUTION_STATUSES = frozenset({"active", "completed", "aborted"})
PROGRAM_WAVE_STATUSES = frozenset({"pending", "running", "completed"})
PROGRAM_GATE_STATUSES = frozenset({"passed"})
_STAGE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_PROGRAM_EVIDENCE_PROFILES = frozenset(
    {
        "scope-record",
        "command-evidence",
        "review-verdict",
        "test-report",
        "security-report",
        "closeout-record",
    }
)
_SYMBOLIC_EVIDENCE_PLACEHOLDER_RE = re.compile(
    r"^(?:agent|artifact|command|mcp|rule|skill|stage|state|template)://\S+$"
)
_STALE_ATTEMPT_FORBIDDEN_CAPABILITIES = frozenset(
    {
        Capability.FILE_WRITE.value,
        Capability.SHELL.value,
        Capability.DELEGATE.value,
        Capability.BROWSER.value,
        Capability.USER_INPUT.value,
        Capability.MCP.value,
        Capability.EXTERNAL_MUTATION.value,
    }
)
#: Severities that block a gate (rules/quality-gates.md: a gate is PASS only with zero of these;
#: low/cosmetic may pass with notes). Ordered for stable messages.
BLOCKING_FINDINGS = ("critical", "high", "medium")

#: How long a writer waits for the snapshot lockfile before giving up.
_LOCK_TIMEOUT_S = 5.0
#: Retained for compatibility/diagnostics only. Age is never ownership proof, so locks are not
#: automatically reclaimed; recovery requires an operator to verify and remove the exact lock.
_LOCK_STALE_S = 60.0


def _state_layout(target: str | Path) -> StateLayout:
    """Return the project's single active control-plane layout."""

    return detect_state_layout(target)


def _snapshot_rel(target: str | Path) -> str:
    return _state_layout(target).pipeline_snapshot


def _stack_snapshot_rel(target: str | Path) -> str:
    return _state_layout(target).stack_snapshot


def _snapshot_path(target: str | Path) -> Path:
    """Return the snapshot path after link/reparse-safe project containment checks."""
    return ProjectFS(Path(target).expanduser()).path(_snapshot_rel(target))


def _load_snapshot(target: str | Path) -> tuple[dict[str, Any] | None, str | None]:
    """Return ``(snapshot, error)`` — ``error`` set if the file exists but won't parse."""
    try:
        path = _snapshot_path(target)
    except (OSError, ValueError) as exc:
        return None, f"unsafe pipeline snapshot path: {exc}"
    if not path.is_file():
        return None, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return None, f"pipeline snapshot is invalid JSON: {exc}"
    if not isinstance(data, dict):
        return None, "pipeline snapshot is not a JSON object"
    return data, None


def _read_install_snapshot(
    target: str | Path,
) -> tuple[dict[str, Any] | None, str | None]:
    """Return ``(data, error)``: ``(None, None)`` = absent, ``(None, msg)`` = unreadable."""
    try:
        path = ProjectFS(Path(target).expanduser()).path(_stack_snapshot_rel(target))
    except (OSError, ValueError) as exc:
        return None, f"unsafe install snapshot path: {exc}"
    if not path.is_file():
        return None, None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        return None, f"install snapshot is invalid YAML: {exc}"
    if not isinstance(data, dict):
        return None, "install snapshot is not a YAML mapping"
    if "schema_version" in data:
        version = data.get("schema_version")
        if not isinstance(version, int) or isinstance(version, bool):
            return None, "install snapshot schema_version must be an integer"
        if version != 1:
            return (
                None,
                f"unsupported future install snapshot schema_version {version!r} "
                "(supported: 1)",
            )
    return data, None


def installed_gates(target: str | Path) -> list[str]:
    """Read the execution-ordered gate list from the install snapshot ([] if absent/unreadable)."""
    data, _err = _read_install_snapshot(target)
    gates = (data or {}).get("gates")
    return list(gates) if isinstance(gates, list) else []


def installed_gate_definitions(target: str | Path) -> dict[str, GateDefinition]:
    """Read canonical gate policy from the install snapshot.

    A pre-hardening install has no metadata. For compatibility it is interpreted safely as an
    all-required gate set: old installs can start and pass gates, but cannot mark any gate not
    applicable until upgraded/reinstalled with canonical definitions.
    """
    data, _err = _read_install_snapshot(target)
    gates = installed_gates(target)
    raw = (data or {}).get("gate_definitions")
    out: dict[str, GateDefinition] = {}
    if isinstance(raw, dict):
        if set(raw) != set(gates):
            return {}
        for gate in gates:
            value = raw.get(gate)
            if not isinstance(value, dict):
                return {}
            try:
                out[gate] = GateDefinition.from_dict(value)
            except ValueError:
                return {}
        return out
    return {
        gate: GateDefinition(
            requirement="required", skippable=False, skip_conditions=[]
        )
        for gate in gates
    }


def installed_gate_definition_digest(target: str | Path) -> str:
    """Recompute the active gate-policy digest and reject stale persisted metadata."""
    data, err = _read_install_snapshot(target)
    if err or data is None:
        return ""
    persisted = (data or {}).get("gate_definition_digest")
    gates = installed_gates(target)
    definitions = installed_gate_definitions(target)
    if not gates or set(definitions) != set(gates):
        return ""
    computed = digest_gate_definitions(gates, definitions)
    if persisted is not None and (
        not isinstance(persisted, str)
        or len(persisted) != 64
        or any(char not in "0123456789abcdef" for char in persisted)
        or persisted != computed
    ):
        return ""
    return computed


def _selection(target: str | Path) -> dict[str, Any]:
    """Read the recorded selection from the install snapshot ({} if absent)."""
    data, _err = _read_install_snapshot(target)
    sel = (data or {}).get("selection")
    return sel if isinstance(sel, dict) else {}


def installed_selection_digest(target: str | Path) -> str:
    """Return a stable digest of the complete installed selection."""
    selection = _selection(target)
    if not selection:
        return ""
    encoded = json.dumps(
        selection,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@lru_cache(maxsize=8)
def _load_current_workflow_cached(payload_path: str, content_digest: str) -> Any:
    del content_digest
    from claude_kit.workflows import load_workflow

    return load_workflow(Path(payload_path))


def _current_workflow_definition() -> Any:
    """Load the packaged canonical workflow without coupling catalog resolution."""
    from claude_kit import scaffold

    with ExitStack() as resources:
        payload = scaffold.payload_dir(resources)
        digest = hashlib.sha256()
        for relative in (
            "catalog/workflows/sdlc.yaml",
            "schemas/workflow.schema.json",
        ):
            content = (payload / relative).read_bytes()
            _framed_digest(digest, relative.encode("utf-8"))
            _framed_digest(digest, content)
        return _load_current_workflow_cached(str(payload), digest.hexdigest())


def _framed_digest(digest: Any, value: bytes) -> None:
    digest.update(len(value).to_bytes(8, "big"))
    digest.update(value)


@lru_cache(maxsize=256)
def _load_canonical_agent_spec_cached(
    payload_path: str,
    source_path: str,
    source_digest: str,
    schema_digest: str,
) -> Any:
    del source_digest, schema_digest
    from claude_kit.canonical_agents import load_canonical_agent

    return load_canonical_agent(Path(payload_path), Path(source_path)).spec


def _current_workflow_identity() -> tuple[str, int, str]:
    from claude_kit.workflows import workflow_definition_digest

    workflow = _current_workflow_definition()
    return (
        str(workflow.id),
        int(workflow.schema_version),
        workflow_definition_digest(workflow),
    )


def _installed_runtime_options(root: Path) -> InitOptions:
    fs = ProjectFS(root)
    layout = detect_state_layout(root)
    try:
        raw_manifest = json.loads(fs.read_text(layout.manifest))
        return InitOptions.from_dict(raw_manifest)
    except (
        FileNotFoundError,
        json.JSONDecodeError,
        OSError,
        TypeError,
        ValueError,
    ) as exc:
        raise ValueError(f"cannot load installed runtime manifest: {exc}") from exc


def _installed_provider_projection(
    target: str | Path,
) -> tuple[tuple[str, ...], str]:
    """Return the exact installed provider set and content-addressed projection.

    The runtime manifest is mutable control-plane input and the generated provider
    files can change without moving ``HEAD``.  Managed execution therefore freezes
    both their semantic metadata and their current bytes.  A later provider install,
    removal, regeneration, or hand edit changes this digest and fails closed before
    another stage can be claimed.
    """

    root = Path(target).expanduser()
    fs = ProjectFS(root)
    layout = detect_state_layout(root)
    options = _installed_runtime_options(fs.root)

    providers = tuple(options.runtimes)
    records = _provider_control_records(fs.root, options, providers)
    if not records:
        raise ValueError("runtime manifest contains no immutable provider files")
    install, install_error = _read_install_snapshot(root)
    if install_error or install is None:
        raise ValueError(install_error or "installed stack snapshot is unavailable")
    document = {
        "providers": list(providers),
        "rendering_version": options.rendering_version,
        "compatibility_catalog_versions": options.compatibility_catalog_versions,
        "selection": options.selection.to_dict(),
        "provider_files": records,
        "stack_snapshot_sha256": hashlib.sha256(
            fs.read_bytes(layout.stack_snapshot)
        ).hexdigest(),
    }
    encoded = json.dumps(
        document, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return providers, hashlib.sha256(encoded).hexdigest()


def _mutable_execution_context_path(
    layout: StateLayout, path: str, *, owner: str
) -> bool:
    """Return whether a shared record is mutable run context, not provider control."""

    if owner != "user-editable":
        return False
    exact = {layout.continuity, layout.journal}
    prefixes = {
        layout.state,
        layout.memory,
        layout.artifacts,
        layout.temporary,
    }
    return path in exact or any(
        path == prefix or path.startswith(prefix + "/") for prefix in prefixes
    )


def _provider_control_records(
    root: Path, options: InitOptions, providers: tuple[str, ...]
) -> list[dict[str, str]]:
    """Hash immutable controls in one bounded Git-native, non-writing pass."""

    root = Path(root).resolve(strict=True)
    layout = options.state_layout
    selected = sorted(
        (
            item
            for item in options.files
            if item.provider in providers or item.provider == "shared"
            if not _mutable_execution_context_path(layout, item.path, owner=item.owner)
        ),
        key=lambda item: (item.provider, item.path, item.component_id),
    )
    if len(selected) > _MAX_PROVIDER_CONTROL_FILES:
        raise ValueError("provider control surface exceeds the 10000-file safety limit")

    paths: list[bytes] = []
    metadata: list[tuple[Any, os.stat_result]] = []
    directory_signatures: dict[Path, tuple[int, int, int, int]] = {}
    total_bytes = 0
    for record in selected:
        raw = os.fsencode(record.path)
        relative = Path(record.path)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or b"\n" in raw
            or b"\r" in raw
        ):
            raise ValueError(f"provider control path is unsafe: {record.path!r}")
        parent = root
        for part in relative.parts[:-1]:
            parent /= part
            if parent in directory_signatures:
                continue
            info = parent.lstat()
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                raise ValueError(
                    f"provider control parent is redirectable: {record.path!r}"
                )
            directory_signatures[parent] = (
                info.st_dev,
                info.st_ino,
                info.st_mode,
                info.st_ctime_ns,
            )
        path = root / relative
        try:
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
                raise ValueError("provider control path is not a regular file")
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise ValueError(
                f"installed provider file {record.path!r} is unavailable: {exc}"
            ) from exc
        total_bytes += info.st_size
        if total_bytes > _MAX_PROVIDER_CONTROL_BYTES:
            raise ValueError(
                "provider control surface exceeds the 512 MiB safety limit"
            )
        paths.append(raw)
        metadata.append((record, info))

    if not paths:
        return []
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "hash-object",
                "--no-filters",
                "--stdin-paths",
            ],
            input=b"".join(b"./" + path + b"\n" for path in paths),
            check=True,
            capture_output=True,
            timeout=_PROVIDER_CONTROL_HASH_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError(f"cannot hash provider control surface: {exc}") from exc
    identities = result.stdout.splitlines()
    if len(identities) != len(paths) or any(
        not re.fullmatch(rb"[0-9a-f]{40}|[0-9a-f]{64}", identity)
        for identity in identities
    ):
        raise ValueError("git returned malformed provider control identities")

    for parent, signature in directory_signatures.items():
        current = parent.lstat()
        if (
            current.st_dev,
            current.st_ino,
            current.st_mode,
            current.st_ctime_ns,
        ) != signature:
            raise ValueError("provider control directory changed while hashing")

    records: list[dict[str, str]] = []
    for (record, before), identity in zip(metadata, identities):
        after = (root / record.path).lstat()
        before_signature = (
            before.st_dev,
            before.st_ino,
            before.st_mode,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        after_signature = (
            after.st_dev,
            after.st_ino,
            after.st_mode,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        if before_signature != after_signature or not stat.S_ISREG(after.st_mode):
            raise ValueError("provider control file changed while hashing")
        records.append(
            {
                "provider": record.provider,
                "path": record.path,
                "component_id": record.component_id,
                "executable": "yes" if after.st_mode & stat.S_IXUSR else "no",
                "content_identity": identity.decode("ascii"),
            }
        )
    return records


def _provider_control_surface_digest(
    root: Path, options: InitOptions, providers: tuple[str, ...]
) -> str:
    records = _provider_control_records(root, options, providers)
    if not records:
        raise ValueError("runtime manifest contains no immutable provider files")
    encoded = json.dumps(
        records, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _managed_active_graph(
    target: str | Path, mode_code: str, ordered_gates: Sequence[str]
) -> tuple[
    tuple[str, ...],
    dict[str, tuple[str, ...]],
    dict[str, tuple[str, ...]],
    dict[str, dict[str, Any]],
    dict[str, str],
]:
    """Project the canonical graph and freeze its installed role contracts."""

    workflow = _current_workflow_definition()
    modes = [item for item in workflow.modes.values() if item.code == mode_code]
    if len(modes) != 1:
        raise ValueError(f"canonical workflow has no unique mode {mode_code!r}")
    mode = modes[0]
    selected = (
        {stage.id for stage in workflow.stages} if mode.all_stages else set(mode.stages)
    )
    active_gates = set(ordered_gates)
    stages = tuple(
        stage
        for stage in workflow.stages
        if stage.id in selected
        and (not stage.gates or bool(set(stage.gates) & active_gates))
    )
    active_ids = {stage.id for stage in stages}
    implicit: dict[str, list[str]] = {stage.id: [] for stage in stages}
    for group in workflow.parallel_groups.values():
        if group.join_before not in active_ids:
            continue
        for lane in group.lanes:
            active_lane = tuple(item for item in lane.stages if item in active_ids)
            if active_lane:
                implicit[group.join_before].append(active_lane[-1])
    dependencies = {
        stage.id: tuple(dict.fromkeys(stage.depends_on + tuple(implicit[stage.id])))
        for stage in stages
    }
    requirements = {
        stage.id: tuple(sorted(item.value for item in stage.required_capabilities))
        for stage in stages
    }
    install, install_error = _read_install_snapshot(target)
    if install_error or install is None:
        raise ValueError(install_error or "installed stack snapshot is unavailable")
    installed_roles = {
        str(item)
        for field in ("agents", "overlay_agents")
        for item in install.get(field, [])
        if isinstance(item, str)
    }
    org = install.get("org")
    if isinstance(org, dict):
        installed_roles.update(
            str(item) for item in org.get("org_agents", []) if isinstance(item, str)
        )

    from claude_kit import scaffold

    role_contracts: dict[str, dict[str, Any]] = {}
    with ExitStack() as resources:
        payload = scaffold.payload_dir(resources)
        agent_schema_digest = hashlib.sha256(
            (payload / "schemas/canonical-agent.schema.json").read_bytes()
        ).hexdigest()
        for stage in stages:
            if stage.execution_kind.value == "typed-external-action":
                if stage.action_kind is None:
                    raise ValueError(
                        f"typed external-action stage {stage.id!r} has no action kind"
                    )
                exact_capabilities = tuple(
                    sorted(item.value for item in stage.required_capabilities)
                )
                requirements[stage.id] = exact_capabilities
                role_contracts[stage.id] = {
                    "execution_kind": stage.execution_kind.value,
                    "action_kind": stage.action_kind.value,
                    "required_capabilities": list(exact_capabilities),
                }
                continue
            route = workflow.roles[stage.route]
            candidates = (route.primary,) + route.fallbacks
            selected_role = ""
            for candidate in candidates:
                if candidate in installed_roles:
                    selected_role = candidate
                    break
            if not selected_role:
                raise ValueError(
                    f"installed plan has no role for workflow route {route.id!r}"
                )
            source = payload / "canonical" / "agents" / "core" / f"{selected_role}.md"
            agent = _load_canonical_agent_spec_cached(
                str(payload),
                str(source),
                hashlib.sha256(source.read_bytes()).hexdigest(),
                agent_schema_digest,
            )
            exact_capabilities = tuple(
                sorted(
                    {item.value for item in agent.capabilities}
                    | set(requirements[stage.id])
                )
            )
            if Capability.SHELL.value in exact_capabilities:
                exact_capabilities = tuple(
                    sorted(
                        {
                            *exact_capabilities,
                            Capability.DESCENDANT_CONTAINMENT.value,
                        }
                    )
                )
            requirements[stage.id] = exact_capabilities
            role_contracts[stage.id] = {
                "execution_kind": stage.execution_kind.value,
                "route": route.id,
                "role": selected_role,
                "resolution": (
                    "primary" if selected_role == route.primary else "fallback"
                ),
                "required_capabilities": list(exact_capabilities),
                "permission": agent.permission.value,
                "write_scope": list(agent.write_scope),
                "isolation": agent.isolation.value,
                "nested_delegation": agent.nested_delegation.value,
            }

    mode_matches = [item for item in workflow.modes.values() if item.code == mode_code]
    assert len(mode_matches) == 1  # established above
    selected_mode = mode_matches[0]
    if selected_mode.gate_policy.value == "subset":
        owners = {gate: selected_mode.gate_stages[gate] for gate in ordered_gates}
    else:
        owners = {gate: workflow.gates[gate].stage for gate in ordered_gates}
    return (
        tuple(stage.id for stage in stages),
        dependencies,
        requirements,
        role_contracts,
        owners,
    )


def installed_gates_for_mode(target: str | Path, mode: str) -> list[str]:
    """Project the installed gate set through the canonical execution mode."""
    installed = installed_gates(target)
    try:
        workflow = _current_workflow_definition()
    except (OSError, ValueError):
        return []
    matches = [
        item for item in workflow.modes.values() if item.id == mode or item.code == mode
    ]
    if len(matches) != 1:
        return []
    selected_mode = matches[0]
    if selected_mode.gate_policy.value == "resolved-plan":
        return installed
    requested = set(selected_mode.gates)
    selected = [gate for gate in installed if gate in requested]
    return selected if set(selected) == requested else []


def installed_gate_definition_digest_for_mode(target: str | Path, mode: str) -> str:
    """Digest the exact installed gate policy active for one execution mode."""
    # The subset digest is meaningful only after the persisted full-policy digest has been
    # verified. Otherwise a stale/tampered install snapshot could be re-hashed into a seemingly
    # coherent mode projection and obscure the source inconsistency.
    if not installed_gate_definition_digest(target):
        return ""
    gates = installed_gates_for_mode(target, mode)
    definitions = installed_gate_definitions(target)
    if not gates or not set(gates).issubset(definitions):
        return ""
    return digest_gate_definitions(gates, {gate: definitions[gate] for gate in gates})


def _snapshot_version(snap: dict[str, Any]) -> tuple[int | None, str | None]:
    """Return ``(version, error)`` while recognizing pre-v2 ``schema`` documents."""
    if "schema_version" in snap:
        value = snap.get("schema_version")
        if not isinstance(value, int) or isinstance(value, bool):
            return None, "pipeline snapshot schema_version must be an integer"
        if value > PIPELINE_SCHEMA_VERSION:
            return value, (
                f"unsupported future pipeline snapshot schema_version {value} "
                f"(maximum supported: {PIPELINE_SCHEMA_VERSION})"
            )
        if value != PIPELINE_SCHEMA_VERSION:
            return value, f"unsupported pipeline snapshot schema_version {value}"
        return value, None
    legacy = snap.get("schema")
    if legacy in (None, 1):
        return 1, None
    if isinstance(legacy, int) and legacy > 1:
        return legacy, (
            f"unsupported future pipeline snapshot schema {legacy} "
            f"(maximum legacy schema: 1; current schema_version: {PIPELINE_SCHEMA_VERSION})"
        )
    return None, f"unsupported pipeline snapshot schema {legacy!r}"


def _git_identity(root: Path) -> tuple[dict[str, str] | None, str | None]:
    """Return machine-derived repository root, branch, and HEAD for a lifecycle mutation."""

    def run(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()

    try:
        repo_root = Path(run("rev-parse", "--show-toplevel")).resolve()
        branch = run("rev-parse", "--abbrev-ref", "HEAD")
        commit = run("rev-parse", "HEAD")
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"cannot establish repository identity with git: {exc}"
    if repo_root != root:
        return None, (
            f"target {root} is not the repository root (git reports {repo_root}); "
            "run pipeline commands at the repository root"
        )
    return {"repository_root": str(repo_root), "branch": branch, "commit": commit}, None


def _git_contains_commit(root: Path, commit: Any) -> bool:
    """Return whether a persisted hexadecimal commit still belongs to this repository."""
    if not (
        isinstance(commit, str)
        and len(commit) in {40, 64}
        and all(char in "0123456789abcdefABCDEF" for char in commit)
    ):
        return False
    try:
        subprocess.run(
            ["git", "-C", str(root), "cat-file", "-e", f"{commit}^{{commit}}"],
            check=True,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return True


def _claude_code_version() -> str | None:
    try:
        result = subprocess.run(
            ["claude", "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    rendered = (result.stdout or result.stderr).strip()
    return rendered or None


def _stored_evidence(root: Path, evidence: str | Path) -> tuple[Path, str, list[str]]:
    """Resolve evidence project-relatively and return path, portable form, and warnings."""
    raw = Path(evidence).expanduser()
    path = (raw if raw.is_absolute() else root / raw).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"evidence file not found: {evidence}")
    warnings: list[str] = []
    try:
        stored = str(path.relative_to(root))
    except ValueError:
        snap, snapshot_error = _load_snapshot(root)
        contract = snap.get("managed_execution") if isinstance(snap, dict) else None
        workspace = contract.get("workspace") if isinstance(contract, dict) else None
        target_path = (
            workspace.get("target_path") if isinstance(workspace, dict) else None
        )
        active_workspace: Path | None = None
        if snapshot_error is None and isinstance(target_path, str):
            try:
                active_workspace = (root / target_path).resolve(strict=True)
                path.relative_to(active_workspace)
            except (OSError, ValueError):
                active_workspace = None
        if active_workspace is not None:
            workspace_fs = ProjectFS(active_workspace)
            data, content_sha, _content_size = _read_managed_file_bounded(
                workspace_fs,
                workspace_fs.relpath(path),
                maximum_bytes=MAX_EVIDENCE_ENVELOPE_BYTES,
            )
            safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", path.name).strip("-.")
            safe_name = safe_name[:80] or "evidence.bin"
            layout = detect_state_layout(root)
            stored = f"{layout.artifacts}/evidence/{content_sha}-{safe_name}"
            copied = ProjectFS(root).write_bytes(stored, data, mode=0o600)
            return copied, stored, []
        stored = str(path)
        warnings.append(
            f"WARN  evidence {path} is outside the project — recorded as an absolute path, "
            "which will not survive a different checkout location"
        )
    return path, stored, warnings


def _blocking_findings(snap: dict[str, Any]) -> dict[str, int]:
    """Return the ``{severity: count}`` of open findings that block a gate (count > 0).

    Callers must first validate a schema-v2 snapshot, which requires the complete closed severity
    set and non-negative integer counts. Only :data:`BLOCKING_FINDINGS` severities block; Low and
    Cosmetic findings remain reportable without being gate blockers.
    """
    raw = snap.get("open_findings")
    if not isinstance(raw, dict):
        return {}
    out: dict[str, int] = {}
    for sev in BLOCKING_FINDINGS:
        count = raw.get(sev, 0)
        if isinstance(count, int) and not isinstance(count, bool) and count > 0:
            out[sev] = count
    return out


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_utc_timestamp(value: Any) -> datetime | None:
    """Parse one timezone-aware ISO timestamp into UTC, or return ``None``."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _headless_allowance_digest(
    token: str,
    *,
    run_id: str,
    starting_gate: str,
    starting_history_length: int,
) -> str:
    """Bind a process-local token to the exact run and gate-ledger position."""
    binding = json.dumps(
        {
            "run_id": run_id,
            "starting_gate": starting_gate,
            "starting_history_length": starting_history_length,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(token.encode("utf-8") + b"\0" + binding).hexdigest()


def _headless_coordinator_digest(
    token: str,
    *,
    run_id: str,
    starting_gate: str,
    starting_history_length: int,
) -> str:
    """Domain-separate the cleanup authority from the worker transition token."""

    return _headless_allowance_digest(
        "coordinator\0" + token,
        run_id=run_id,
        starting_gate=starting_gate,
        starting_history_length=starting_history_length,
    )


def _headless_coordinator_matches(allowance: Mapping[str, Any], token: str) -> bool:
    if not isinstance(token, str) or not token:
        return False
    try:
        expected = _headless_coordinator_digest(
            token,
            run_id=str(allowance["run_id"]),
            starting_gate=str(allowance["starting_gate"]),
            starting_history_length=int(allowance["starting_history_length"]),
        )
    except (KeyError, TypeError, ValueError):
        return False
    return hmac.compare_digest(expected, str(allowance.get("coordinator_digest")))


def _headless_allowance_expired(allowance: Mapping[str, Any]) -> bool:
    expires_at = _parse_utc_timestamp(allowance.get("expires_at"))
    return expires_at is None or expires_at <= datetime.now(timezone.utc)


def _headless_allowance_shape_problem(run: Mapping[str, Any]) -> str | None:
    """Return a semantic error for a persisted headless transition allowance."""
    raw = run.get("headless_transition_allowance")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        return "headless_transition_allowance must be an object"
    required = {
        "schema_version",
        "run_id",
        "starting_gate",
        "starting_history_length",
        "token_digest",
        "coordinator_digest",
        "created_at",
        "expires_at",
        "consumed",
    }
    optional = {"consumed_at", "action", "gate", "coordinator_closed_at"}
    missing = required - set(raw)
    extra = set(raw) - required - optional
    if missing:
        return "headless_transition_allowance is missing " + ", ".join(sorted(missing))
    if extra:
        return "headless_transition_allowance has unknown fields: " + ", ".join(
            sorted(extra)
        )
    if raw.get("schema_version") != HEADLESS_TRANSITION_ALLOWANCE_VERSION:
        return "headless_transition_allowance has an unsupported schema_version"
    run_id = raw.get("run_id")
    if not isinstance(run_id, str) or not run_id or run_id != run.get("run_id"):
        return "headless_transition_allowance is bound to a different run"
    gates = run.get("ordered_gates")
    starting_gate = raw.get("starting_gate")
    if not (
        isinstance(starting_gate, str)
        and starting_gate
        and (
            starting_gate == "ready-to-complete"
            or (isinstance(gates, list) and starting_gate in gates)
        )
    ):
        return "headless_transition_allowance has an invalid starting_gate"
    starting_length = raw.get("starting_history_length")
    if (
        not isinstance(starting_length, int)
        or isinstance(starting_length, bool)
        or starting_length < 0
    ):
        return "headless_transition_allowance has an invalid starting_history_length"
    token_digest = raw.get("token_digest")
    if not (
        isinstance(token_digest, str)
        and len(token_digest) == 64
        and all(char in "0123456789abcdef" for char in token_digest)
    ):
        return "headless_transition_allowance token_digest must be 64 lowercase hex characters"
    coordinator_digest = raw.get("coordinator_digest")
    if not (
        isinstance(coordinator_digest, str)
        and len(coordinator_digest) == 64
        and all(char in "0123456789abcdef" for char in coordinator_digest)
    ):
        return (
            "headless_transition_allowance coordinator_digest must be 64 lowercase "
            "hex characters"
        )
    created_at = _parse_utc_timestamp(raw.get("created_at"))
    expires_at = _parse_utc_timestamp(raw.get("expires_at"))
    if created_at is None or expires_at is None or expires_at <= created_at:
        return (
            "headless_transition_allowance has invalid created_at/expires_at timestamps"
        )
    consumed = raw.get("consumed")
    if not isinstance(consumed, bool):
        return "headless_transition_allowance consumed must be a boolean"
    if (
        "coordinator_closed_at" in raw
        and _parse_utc_timestamp(raw.get("coordinator_closed_at")) is None
    ):
        return "headless_transition_allowance coordinator_closed_at is invalid"
    raw_history = run.get("gate_history")
    if not isinstance(raw_history, list):
        return "headless_transition_allowance cannot bind a malformed gate_history"
    if consumed:
        action = raw.get("action")
        consumed_at = _parse_utc_timestamp(raw.get("consumed_at"))
        if action not in {"close-gate", "not-applicable", "accept-risk", "complete"}:
            return "consumed headless_transition_allowance has an invalid action"
        if consumed_at is None:
            return "consumed headless_transition_allowance has no consumed_at timestamp"
        if action == "complete":
            if starting_gate != "ready-to-complete" or raw.get("gate") is not None:
                return "completion allowance is not bound to ready-to-complete"
            if len(raw_history) != starting_length or run.get("status") != "completed":
                return (
                    "completion allowance does not match the terminal history position"
                )
        else:
            gate = raw.get("gate")
            if gate != starting_gate:
                return (
                    "consumed headless_transition_allowance gate differs from its start"
                )
            if (
                len(raw_history) != starting_length + 1
                or run.get("last_gate_resolved") != gate
            ):
                return "consumed headless_transition_allowance has an invalid history delta"
    else:
        if any(field in raw for field in {"consumed_at", "action", "gate"}):
            return "unconsumed headless_transition_allowance has transition metadata"
        if len(raw_history) != starting_length:
            return "unconsumed headless_transition_allowance no longer matches its start position"
        if run.get("status") == "active" and run.get("stage") != starting_gate:
            return "unconsumed headless_transition_allowance no longer matches its start position"
        if run.get("status") not in {"active", "aborted"}:
            return "unconsumed headless_transition_allowance has an invalid run status"
    return None


def _headless_transition_problem(
    run: Mapping[str, Any], *, action: str, gate: str | None
) -> str | None:
    """Authorize one resolution for an active headless-loop iteration, when present."""
    supplied = os.environ.get(HEADLESS_TRANSITION_TOKEN_ENV)
    raw = run.get("headless_transition_allowance")
    if raw is None:
        if supplied:
            return (
                "a headless iteration token was supplied without its matching active allowance; "
                "the iteration has ended or the run position changed"
            )
        return None
    shape_problem = _headless_allowance_shape_problem(run)
    if shape_problem:
        return shape_problem
    allowance = cast(dict[str, Any], raw)
    if "coordinator_closed_at" in allowance:
        return (
            "the prior headless host invocation is durably closed; only its coordinator "
            "authority can rotate to another iteration"
        )
    if _headless_allowance_expired(allowance):
        return (
            "headless iteration transition allowance expired; fail-closed recovery is "
            "required before lifecycle transitions can continue"
        )
    if not supplied:
        return (
            "an active headless iteration owns this gate position; lifecycle transitions require "
            f"the inherited {HEADLESS_TRANSITION_TOKEN_ENV} token"
        )
    expected = _headless_allowance_digest(
        supplied,
        run_id=str(allowance["run_id"]),
        starting_gate=str(allowance["starting_gate"]),
        starting_history_length=int(allowance["starting_history_length"]),
    )
    if not hmac.compare_digest(expected, str(allowance["token_digest"])):
        return "headless iteration transition token does not match this run position"
    if allowance["consumed"]:
        return "headless iteration already consumed its one transition allowance"
    expected_gate = str(allowance["starting_gate"])
    if action == "complete":
        if gate is not None or expected_gate != "ready-to-complete":
            return "headless completion allowance was not minted at ready-to-complete"
    elif gate != expected_gate:
        return f"headless iteration is bound to gate {expected_gate!r}, not {gate!r}"
    return None


def _consume_headless_transition_allowance(
    run: dict[str, Any], *, action: str, gate: str | None
) -> None:
    """Consume or discard the already-authorized allowance before the atomic snapshot write."""
    raw = run.get("headless_transition_allowance")
    if not isinstance(raw, dict):
        return
    raw["consumed"] = True
    raw["consumed_at"] = _utc_now()
    raw["action"] = action
    if gate is not None:
        raw["gate"] = gate


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _finding_set_digest(
    counts: dict[str, int],
    *,
    evidence_sha256: str,
    repository_commit: str,
    workspace_content_digest: str | None = None,
) -> str:
    """Bind exact severity counts to their evidence artifact and repository commit."""
    document = {
        "counts": {severity: counts[severity] for severity in sorted(FINDING_KEYS)},
        "evidence_sha256": evidence_sha256,
        "repository_commit": repository_commit,
    }
    if workspace_content_digest is not None:
        document["workspace_content_digest"] = workspace_content_digest
    return hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _document_sha256(document: dict[str, Any]) -> str:
    """Hash a JSON object using the canonical encoding used by persisted audit records."""
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def _archive_terminal_snapshot(existing: dict[str, Any]) -> list[dict[str, Any]]:
    """Return prior archives plus an immutable record of the current terminal run."""
    prior = existing.get("run_archives")
    archives = list(prior) if isinstance(prior, list) else []
    archived_snapshot = dict(existing)
    archived_snapshot.pop("run_archives", None)
    archives.append(
        {
            "run_id": str(archived_snapshot.get("run_id")),
            "status": str(archived_snapshot.get("status")),
            "archived_at": _utc_now(),
            "snapshot_sha256": _document_sha256(archived_snapshot),
            "snapshot": archived_snapshot,
        }
    )
    return archives


def _run_archive_problems(root: Path, raw_archives: object) -> list[str]:
    """Validate non-recursive terminal snapshot envelopes retained by either run kind."""

    if not isinstance(raw_archives, list):
        return ["schema-v2 run_archives must be an array"]
    problems: list[str] = []
    for archive_index, archive in enumerate(raw_archives):
        label = f"run_archives[{archive_index}]"
        if not isinstance(archive, dict):
            problems.append(f"{label} must be an object")
            continue
        for archive_field in (
            "run_id",
            "status",
            "archived_at",
            "snapshot_sha256",
        ):
            if not (
                isinstance(archive.get(archive_field), str)
                and archive[archive_field].strip()
            ):
                problems.append(f"{label} has no non-empty {archive_field!r}")
        archived_snapshot = archive.get("snapshot")
        if not isinstance(archived_snapshot, dict):
            problems.append(f"{label} has no terminal snapshot object")
            continue
        if "run_archives" in archived_snapshot:
            problems.append(
                f"{label} snapshot must not recursively contain run_archives"
            )
        if archived_snapshot.get("status") not in {"completed", "aborted"}:
            problems.append(f"{label} snapshot is not terminal")
        if archive.get("run_id") != archived_snapshot.get("run_id"):
            problems.append(f"{label} run_id differs from its snapshot")
        if archive.get("status") != archived_snapshot.get("status"):
            problems.append(f"{label} status differs from its snapshot")
        if archive.get("snapshot_sha256") != _document_sha256(archived_snapshot):
            problems.append(f"{label} terminal snapshot hash mismatch")

        try:
            from claude_kit import schemas

            with ExitStack() as stack:
                schema_errors = schemas.validate_doc(
                    archived_snapshot, "pipeline-snapshot", stack
                )
        except (ModuleNotFoundError, OSError, ValueError) as exc:
            problems.append(f"{label} snapshot schema could not be verified: {exc}")
            schema_errors = []
        problems.extend(
            f"{label} snapshot schema invalid: {message}"
            for message in schema_errors[:3]
        )

        from claude_kit.maker_checker import (
            is_maker_checker_snapshot,
            validate_maker_checker_snapshot,
        )

        if is_maker_checker_snapshot(archived_snapshot):
            valid, validation_messages = validate_maker_checker_snapshot(
                root,
                archived_snapshot,
                historical_terminal=True,
            )
            if not valid:
                problems.extend(
                    f"{label} {message.removeprefix('FAIL  ')}"
                    for message in validation_messages
                )
        else:
            if "snapshot_kind" in archived_snapshot:
                problems.append(f"{label} has an unsupported snapshot_kind")
            archived_version, archived_version_error = _snapshot_version(
                archived_snapshot
            )
            if archived_version_error or archived_version != PIPELINE_SCHEMA_VERSION:
                problems.append(
                    f"{label} does not contain a supported schema-v2 snapshot"
                )
            archived_artifact_problem = _managed_archived_artifacts_problem(
                root, archived_snapshot
            )
            if archived_artifact_problem:
                problems.append(f"{label} {archived_artifact_problem}")
    return problems


def _findings_evidence_errors(
    root: Path, snap: dict[str, Any], *, current_commit: str | None
) -> list[str]:
    """Return integrity failures for the current structured finding-set evidence."""
    record = snap.get("findings_evidence")
    if not isinstance(record, dict):
        return [
            "run has no current structured findings evidence; use pipeline record-findings"
        ]
    errors: list[str] = []
    counts = record.get("counts")
    if counts != snap.get("open_findings"):
        errors.append("findings evidence counts differ from open_findings")
    evidence = record.get("evidence_path")
    evidence_sha = record.get("evidence_sha256")
    evidence_path: Path | None = None
    if not isinstance(evidence, str) or not evidence:
        errors.append("findings evidence has no project-relative evidence_path")
    elif Path(evidence).is_absolute():
        errors.append("findings evidence path must remain inside the project")
    else:
        evidence_path = (root / evidence).resolve()
        try:
            evidence_path.relative_to(root)
        except ValueError:
            errors.append("findings evidence path escapes the project")
            evidence_path = None
    if evidence_path is not None:
        try:
            _evidence_bytes, actual_sha, _evidence_size = _read_managed_file_bounded(
                ProjectFS(root),
                str(evidence),
                maximum_bytes=MAX_EVIDENCE_ENVELOPE_BYTES,
            )
        except FileNotFoundError:
            errors.append(f"findings evidence file is missing: {evidence}")
        except (UnsafePathError, OSError, ValueError) as exc:
            errors.append(f"findings evidence path is unsafe: {exc}")
        else:
            if not isinstance(evidence_sha, str) or actual_sha != evidence_sha:
                errors.append("findings evidence hash mismatch")
    recorded_commit = record.get("repository_commit")
    if current_commit is not None and recorded_commit != current_commit:
        errors.append(
            f"findings evidence belongs to commit {recorded_commit!r}, current HEAD is "
            f"{current_commit!r}"
        )
    workspace_digest: str | None = None
    if snap.get("managed_execution") is not None:
        checkpoint, checkpoint_problem = _managed_workspace_checkpoint(root, snap)
        if checkpoint_problem or checkpoint is None:
            errors.append(
                checkpoint_problem or "managed workspace checkpoint is unavailable"
            )
        else:
            workspace_digest = checkpoint.content_digest
            if record.get("workspace_content_digest") != checkpoint.content_digest:
                errors.append(
                    "findings evidence belongs to a different workspace content"
                )
            if record.get("workspace_head_commit") != checkpoint.head_commit:
                errors.append("findings evidence belongs to a different workspace HEAD")
        contract = snap.get("managed_execution")
        if (
            isinstance(contract, dict)
            and contract.get("evidence_contract_version") == EVIDENCE_CONTRACT_VERSION
        ):
            if record.get("managed_gate") is not None:
                bundle_problem = _managed_findings_bundle_problem(
                    ProjectFS(root), snap, record
                )
                if bundle_problem:
                    errors.append(bundle_problem)
            else:
                successful = [
                    item
                    for item in snap.get("stage_history", [])
                    if isinstance(item, dict) and item.get("status") == "succeeded"
                ]
                raw_counts = record.get("counts")
                has_findings = isinstance(raw_counts, dict) and any(
                    isinstance(value, int) and value > 0
                    for value in raw_counts.values()
                )
                if successful or snap.get("gate_history") or has_findings:
                    errors.append(
                        "managed findings evidence is an unverified bootstrap record"
                    )
    expected_digest = ""
    if (
        isinstance(counts, dict)
        and set(counts) == FINDING_KEYS
        and all(
            isinstance(value, int) and not isinstance(value, bool) and value >= 0
            for value in counts.values()
        )
        and isinstance(evidence_sha, str)
        and isinstance(recorded_commit, str)
    ):
        expected_digest = _finding_set_digest(
            counts,
            evidence_sha256=evidence_sha,
            repository_commit=recorded_commit,
            workspace_content_digest=workspace_digest,
        )
    if not expected_digest or record.get("finding_set_digest") != expected_digest:
        errors.append("findings evidence identity binding is invalid")
    if not (
        isinstance(record.get("recorded_at"), str) and record["recorded_at"].strip()
    ):
        errors.append("findings evidence has no recorded_at timestamp")
    return errors


def _current_findings_problem(
    root: Path, snap: dict[str, Any], *, current_commit: str
) -> str | None:
    errors = _findings_evidence_errors(root, snap, current_commit=current_commit)
    return "; ".join(errors) if errors else None


def _history(snap: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the ledger entries that are well-formed dicts (lenient on the rest)."""
    raw = snap.get("gate_history")
    if not isinstance(raw, list):
        return []
    return [e for e in raw if isinstance(e, dict)]


def _position(
    gates: list[str],
    history: list[dict[str, Any]],
    last_gate_passed: Any,
    *,
    legacy: bool = False,
    adoption: Any = None,
) -> int | None:
    """Return the run's furthest recorded gate index, or ``None`` when nothing anchors it yet.

    The position is the **max** of the ledger and the legacy ``last_gate_passed`` anchor. Schema-v2
    adoption supplies explicit historical gates; a fresh run with no record remains before gate 0.
    """
    statuses = POSITION_STATUSES | LEGACY_GATE_STATUSES if legacy else POSITION_STATUSES
    anchors = [
        gates.index(e["gate"])
        for e in history
        if e.get("status") in statuses and e.get("gate") in gates
    ]
    if isinstance(last_gate_passed, str) and last_gate_passed in gates:
        anchors.append(gates.index(last_gate_passed))
    if not anchors and not legacy and isinstance(adoption, dict):
        historical = adoption.get("historical_gates")
        if isinstance(historical, list):
            anchors.extend(gates.index(g) for g in historical if g in gates)
    return max(anchors) if anchors else None


@contextmanager
def _snapshot_lock(
    path: Path,
    msgs: list[str] | None = None,
    *,
    project_fs: ProjectFS,
) -> Iterator[None]:
    """Hold an ``O_EXCL`` lockfile next to the snapshot for a whole read-modify-write.

    The holder's pid is written into the lockfile for diagnostics. Lock age is never used for
    reclamation: an age-only unlink has an ABA race and can steal a legitimate long-running
    holder. Contention raises ``TimeoutError`` after :data:`_LOCK_TIMEOUT_S`; an operator may
    remove the exact lock only after independently verifying that no writer owns it.
    """
    lock = path.with_name(path.name + ".lock")
    lock_rel = f"{project_fs.relpath(path)}.lock"
    deadline = time.monotonic() + _LOCK_TIMEOUT_S
    while True:
        try:
            project_fs.create_exclusive(lock_rel, str(os.getpid()).encode("ascii"))
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"could not lock {lock} within {_LOCK_TIMEOUT_S:g}s — another claude-kit "
                    "process may be writing; if recovery is required, verify that no writer "
                    "owns the exact lock before removing it manually"
                ) from None
            time.sleep(0.05)
    try:
        yield
    finally:
        project_fs.unlink(lock_rel, missing_ok=True)


@contextmanager
def _pipeline_write_lock(
    fs: ProjectFS, path: Path, *, msgs: list[str] | None = None
) -> Iterator[None]:
    """Acquire the project lease before the subordinate snapshot lock.

    Install/merge/upgrade transactions hold the exclusive form of this lease across their backup
    and rollback window. Runtime pipeline writers take a shared lease, so an acknowledged snapshot
    write cannot be erased by a concurrent transaction rollback.
    """
    with fs.mutation_lease():
        state_dir = Path(fs.relpath(path)).parent.as_posix()
        fs.mkdir(state_dir)
        with _snapshot_lock(path, msgs=msgs, project_fs=fs):
            yield


def _write_snapshot_locked(target: str | Path, snap: dict[str, Any]) -> None:
    """Atomically persist the snapshot through the project-root filesystem capability."""
    fs = ProjectFS(Path(target).expanduser())
    fs.write_text(_snapshot_rel(target), json.dumps(snap, indent=2) + "\n")


def _gate_set_preamble(
    target: str | Path, *, strict: bool, msgs: list[str]
) -> tuple[list[str], bool]:
    """Shared close/skip preamble: resolve the gate list, honouring strict fail-closed.

    Returns ``(gates, ok)``; appends the WARN/FAIL wording to ``msgs``.
    """
    install, install_err = _read_install_snapshot(target)
    if install_err:
        if strict:
            msgs.append(f"FAIL  {install_err} — refusing to record a gate (--strict)")
            return [], False
        msgs.append(f"WARN  {install_err} — cannot confirm the gate name or order")
        return [], True
    if install is None:
        if strict:
            msgs.append(
                "FAIL  no install snapshot — refusing to record a gate (--strict); "
                f"expected {_stack_snapshot_rel(target)}"
            )
            return [], False
        msgs.append(
            "WARN  no install snapshot — cannot confirm the gate name against the profile"
        )
        return [], True
    gates = install.get("gates")
    return (list(gates) if isinstance(gates, list) else []), True


def _managed_typed_evidence_markers(run: Mapping[str, Any]) -> bool:
    """Return whether a snapshot unambiguously used the typed managed contract."""

    if run.get("execution_binding") is not None:
        return True
    contract = run.get("managed_execution")
    if isinstance(contract, Mapping) and any(
        field in contract
        for field in (
            "evidence_contract_version",
            "active_stage_evidence",
            "gate_evidence",
            "evidence_requirements",
            "findings_policy",
            "binding_workspace_checkpoint",
        )
    ):
        return True
    history = run.get("stage_history")
    if isinstance(history, list):
        for record in history:
            if not isinstance(record, Mapping):
                continue
            if record.get("evidence_records") or record.get("findings"):
                return True
            raw_counts = record.get("finding_counts")
            if isinstance(raw_counts, Mapping) and any(
                isinstance(value, int) and not isinstance(value, bool) and value > 0
                for value in raw_counts.values()
            ):
                return True
            output_path = record.get("output_path")
            if (
                isinstance(output_path, str)
                and "/artifacts/dispatch/runs/" in output_path
            ):
                return True
    findings = run.get("findings_evidence")
    if isinstance(findings, Mapping) and (
        findings.get("managed_gate") is not None
        or "/artifacts/evidence/runs/" in str(findings.get("evidence_path", ""))
    ):
        return True
    gate_history = run.get("gate_history")
    if isinstance(gate_history, list) and any(
        isinstance(entry, Mapping)
        and (
            entry.get("owner_stage") is not None
            or "/artifacts/evidence/runs/"
            in str(
                entry.get("condition_evidence_path") or entry.get("evidence_path") or ""
            )
        )
        for entry in gate_history
    ):
        return True
    completion = run.get("managed_completion")
    return isinstance(completion, Mapping) and (
        completion.get("evidence_contract_version") is not None
    )


def _managed_execution_binding(contract: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "kind": "managed",
        "schema_version": 1,
        "contract_digest": _document_sha256(dict(contract)),
    }


def _managed_execution_problem(
    target: str | Path, run: Mapping[str, Any]
) -> str | None:
    contract = run.get("managed_execution")
    typed_markers = _managed_typed_evidence_markers(run)
    if contract is None:
        if typed_markers:
            return "typed managed evidence exists without its execution contract"
        return None
    if not isinstance(contract, dict):
        return "managed execution contract is malformed"
    evidence_contract_version = contract.get("evidence_contract_version")
    if typed_markers and evidence_contract_version != EVIDENCE_CONTRACT_VERSION:
        return "typed managed evidence contract version is missing or unsupported"
    execution_binding = run.get("execution_binding")
    if evidence_contract_version == EVIDENCE_CONTRACT_VERSION:
        if execution_binding != _managed_execution_binding(contract):
            return "typed managed execution binding is missing or differs from its contract"
    elif execution_binding is not None:
        return "managed execution binding exists without a typed managed contract"
    try:
        workflow_id, workflow_version, workflow_digest = _current_workflow_identity()
    except (OSError, ValueError) as exc:
        return f"cannot load the canonical managed workflow: {exc}"
    if contract.get("workflow_id") != workflow_id:
        return "managed workflow id differs from the installed canonical workflow"
    if contract.get("workflow_schema_version") != workflow_version:
        return "managed workflow schema version differs from the installed workflow"
    if contract.get("workflow_definition_digest") != workflow_digest:
        return "managed workflow definition digest changed after this run started"
    if contract.get("mode") != run.get("mode"):
        return "managed workflow mode differs from the active pipeline mode"
    if contract.get("ordered_gates") != run.get("ordered_gates"):
        return "managed workflow gate order differs from the active pipeline"
    if contract.get("gate_definition_digest") != run.get("gate_definition_digest"):
        return "managed workflow gate digest differs from the active pipeline"
    try:
        providers, projection_digest = _installed_provider_projection(target)
    except (OSError, ValueError) as exc:
        return f"cannot verify installed provider projection: {exc}"
    if contract.get("providers") != list(providers):
        return "managed workflow provider set changed after this run started"
    if contract.get("provider_projection_digest") != projection_digest:
        return "managed workflow provider projection changed after this run started"
    owners = contract.get("gate_owner_stages")
    gates = run.get("ordered_gates")
    if (
        not isinstance(owners, dict)
        or not isinstance(gates, list)
        or set(owners) != set(gates)
        or any(
            not isinstance(stage, str) or not _STAGE_ID_RE.fullmatch(stage)
            for stage in owners.values()
        )
    ):
        return "managed workflow gate-owner map is malformed"
    workspace = contract.get("workspace")
    if not isinstance(workspace, dict) or set(workspace) != {
        "worker_id",
        "target_path",
        "base_commit",
    }:
        return "managed workflow workspace binding is malformed"
    worker_id = workspace.get("worker_id")
    target_path = workspace.get("target_path")
    base_commit = workspace.get("base_commit")
    if not isinstance(worker_id, str) or not _STAGE_ID_RE.fullmatch(worker_id):
        return "managed workflow workspace worker id is malformed"
    if (
        not isinstance(target_path, str)
        or Path(target_path).is_absolute()
        or ".." not in Path(target_path).parts
    ):
        return "managed workflow workspace target path is malformed"
    if not isinstance(base_commit, str) or not re.fullmatch(
        r"[0-9a-f]{40}|[0-9a-f]{64}", base_commit
    ):
        return "managed workflow workspace base commit is malformed"
    try:
        managed_root = ProjectFS(Path(target).expanduser()).root
    except (OSError, ValueError) as exc:
        return f"cannot verify managed source checkout identity: {exc}"
    root_identity, identity_problem = _git_identity(managed_root)
    if identity_problem or root_identity is None:
        return identity_problem or "cannot verify managed source checkout identity"
    if root_identity["commit"] != base_commit:
        return "source checkout HEAD changed after the managed workflow was bound"
    run_id = run.get("run_id")
    if not isinstance(run_id, str) or not _STAGE_ID_RE.fullmatch(run_id):
        return "managed workflow run id is malformed"
    try:
        manager = WorktreeManager(managed_root)
        record = manager.verify(run_id, str(worker_id))
        if record.target_path != target_path or record.base_commit != base_commit:
            return "managed workflow workspace differs from its ownership record"
        workspace_root = (managed_root / record.target_path).resolve(strict=True)
        options = _installed_runtime_options(managed_root)
        control_digest = _provider_control_surface_digest(
            workspace_root, options, providers
        )
    except (OSError, ValueError, WorktreeError) as exc:
        return f"cannot verify managed provider control surface: {exc}"
    if contract.get("provider_control_surface_digest") != control_digest:
        return "managed workspace provider control surface changed after binding"
    binding_checkpoint = contract.get("binding_workspace_checkpoint")
    if contract.get("evidence_contract_version") is not None:
        try:
            if not isinstance(binding_checkpoint, dict):
                raise WorktreeError("checkpoint is missing")
            WorkspaceCheckpoint.from_dict(binding_checkpoint)
        except WorktreeError as exc:
            return f"managed binding workspace checkpoint is invalid: {exc}"
    try:
        (
            active_stages,
            active_dependencies,
            active_requirements,
            active_routes,
            canonical_owners,
        ) = _managed_active_graph(
            target, str(contract.get("mode")), tuple(str(item) for item in gates)
        )
    except (OSError, ValueError) as exc:
        return f"cannot project the canonical managed stage graph: {exc}"
    if contract.get("active_stages") != list(active_stages):
        return "managed workflow active stage order differs from the canonical graph"
    expected_dependencies = {
        stage: list(active_dependencies[stage]) for stage in active_stages
    }
    if contract.get("active_stage_dependencies") != expected_dependencies:
        return "managed workflow dependency graph differs from the canonical graph"
    expected_requirements = {
        stage: list(active_requirements[stage]) for stage in active_stages
    }
    if contract.get("active_stage_requirements") != expected_requirements:
        return (
            "managed workflow capability requirements differ from the canonical graph"
        )
    expected_routes = {stage: active_routes[stage] for stage in active_stages}
    if contract.get("active_stage_routes") != expected_routes:
        return "managed workflow role routes differ from the canonical installed graph"
    if owners != canonical_owners:
        return "managed workflow gate-owner map differs from the canonical mode policy"
    expected_evidence = managed_evidence_projection(
        _current_workflow_definition(),
        active_stages=active_stages,
        ordered_gates=tuple(str(item) for item in gates),
    )
    if evidence_contract_version is None:
        if run.get("status") == "active":
            return (
                "active managed workflow predates typed evidence authority; "
                "abort and restart the run"
            )
        return None
    for field, expected in expected_evidence.items():
        if contract.get(field) != expected:
            return f"managed workflow {field.replace('_', ' ')} differs from the canonical evidence contract"
    return None


def _program_required_capabilities(kind: str) -> tuple[str, ...]:
    """Return the closed capability floor for one program unit kind."""

    values: tuple[Capability, ...]
    if kind == "audit":
        values = (Capability.FILE_READ, Capability.SEARCH)
    elif kind == "gate-runner":
        values = (Capability.FILE_READ, Capability.SEARCH, Capability.SHELL)
    elif kind in {"implementation", "knowledge-closeout"}:
        values = (
            Capability.FILE_READ,
            Capability.FILE_WRITE,
            Capability.SEARCH,
            Capability.SHELL,
        )
    else:
        raise ValueError(f"unsupported program unit kind: {kind!r}")
    return tuple(sorted(value.value for value in values))


def _read_program_file_bounded(
    fs: ProjectFS, relative: str, *, maximum_bytes: int
) -> tuple[bytes, str, int]:
    """Read/hash one no-follow regular file with a hard allocation limit."""

    canonical = fs.relpath(relative)
    path = fs.path(canonical)
    expected = fs.stat(canonical)
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (
            expected.st_dev,
            expected.st_ino,
        ):
            raise ValueError("program artifact changed identity or is not regular")
        if opened.st_size > maximum_bytes:
            raise ValueError(
                f"program artifact exceeds the {maximum_bytes}-byte safety limit"
            )
        content = bytearray()
        digest = hashlib.sha256()
        while True:
            chunk = os.read(descriptor, 64 * 1024)
            if not chunk:
                break
            if len(content) + len(chunk) > maximum_bytes:
                raise ValueError("program artifact grew beyond its byte safety limit")
            content.extend(chunk)
            digest.update(chunk)
        final = os.fstat(descriptor)
        if (
            final.st_size != len(content)
            or (final.st_dev, final.st_ino) != (opened.st_dev, opened.st_ino)
            or final.st_mtime_ns != opened.st_mtime_ns
            or final.st_ctime_ns != opened.st_ctime_ns
        ):
            raise ValueError("program artifact changed while it was being verified")
        return bytes(content), digest.hexdigest(), len(content)
    finally:
        os.close(descriptor)


def _read_managed_file_bounded(
    fs: ProjectFS, relative: str, *, maximum_bytes: int
) -> tuple[bytes, str, int]:
    """Use the hardened project-file reader for managed A--D artifacts."""

    try:
        return _read_program_file_bounded(fs, relative, maximum_bytes=maximum_bytes)
    except ValueError as exc:
        raise ValueError(
            str(exc).replace("program artifact", "managed artifact")
        ) from exc


def _program_contract_projection(manifest: Any) -> dict[str, Any]:
    """Project a typed manifest into the immutable execution contract."""

    workflow = _current_workflow_definition()
    routes = workflow.roles
    mode_e = next(mode for mode in workflow.modes.values() if mode.code == "E")
    if mode_e.program is None:
        raise ValueError("canonical Mode E has no program policy")
    program_wave_evidence_policy = {
        wave.kind: list(wave.evidence) for wave in mode_e.program.waves
    }
    boundaries = {
        boundary.id: {
            "id": boundary.id,
            "kind": boundary.kind.value,
            "path": boundary.path.as_posix(),
        }
        for boundary in manifest.boundaries
    }
    owners = {owner.unit_id: owner.route for owner in manifest.owners}
    referenced_evidence = {
        evidence_id for unit in manifest.units for evidence_id in unit.evidence
    } | {evidence_id for gate in manifest.gates for evidence_id in gate.evidence}
    typed_evidence = {
        manifest.pre_change_restore_point.verification_artifact_id,
        "frozen-manifest",
    }
    for unit in manifest.units:
        if unit.inventory is not None:
            typed_evidence.add(unit.inventory.artifact_id)
        if unit.restore_point is not None:
            typed_evidence.add(unit.restore_point.verification_artifact_id)
        if unit.approval is not None:
            typed_evidence.add(unit.approval.request_artifact_id)
            typed_evidence.add(unit.approval.authorization_artifact_id)
    ordinary_evidence = sorted(referenced_evidence - typed_evidence)
    unknown_evidence = [
        evidence_id
        for evidence_id in ordinary_evidence
        if evidence_id not in workflow.evidence_requirements
        or evidence_id not in _PROGRAM_EVIDENCE_PROFILES
    ]
    if unknown_evidence:
        raise ValueError(
            "program manifest uses evidence outside the canonical workflow: "
            + ", ".join(unknown_evidence)
        )
    wave_by_id = {wave.id: wave for wave in manifest.waves}
    audit_required = set(program_wave_evidence_policy["read-only"])
    verification_allowed = set(program_wave_evidence_policy["verification"])
    closeout_required = set(program_wave_evidence_policy["closeout"])
    for unit in manifest.units:
        wave = wave_by_id[unit.wave_id]
        ordinary = set(unit.evidence) - typed_evidence
        if wave.kind.value == "audit" and ordinary != audit_required:
            raise ValueError(f"audit unit {unit.id!r} lacks canonical audit evidence")
        if (
            wave.kind.value == "verification"
            and wave.verifies_wave_id != manifest.waves[0].id
        ):
            if not ordinary or not ordinary.issubset(verification_allowed):
                raise ValueError(
                    f"verification unit {unit.id!r} uses evidence outside the "
                    "canonical verification policy"
                )
        if wave.kind.value == "closeout" and ordinary != closeout_required:
            raise ValueError(
                f"closeout unit {unit.id!r} must provide the canonical closeout evidence"
            )
    for wave in manifest.waves:
        if (
            wave.kind.value != "verification"
            or wave.verifies_wave_id == manifest.waves[0].id
        ):
            continue
        unit_coverage = {
            evidence_id
            for unit in manifest.units
            if unit.wave_id == wave.id
            for evidence_id in unit.evidence
            if evidence_id not in typed_evidence
        }
        gate_coverage = {
            evidence_id
            for gate in manifest.gates
            if gate.wave_id == wave.id
            for evidence_id in gate.evidence
            if evidence_id not in typed_evidence
        }
        if unit_coverage != verification_allowed:
            raise ValueError(
                f"verification wave {wave.id!r} must collectively provide the exact "
                "canonical verification evidence set"
            )
        if gate_coverage != verification_allowed:
            raise ValueError(
                f"verification wave {wave.id!r} gates must collectively bind the "
                "exact canonical verification evidence set"
            )
    evidence_requirements = {
        evidence_id: {
            "validation_profile": evidence_id,
            "kind": workflow.evidence_requirements[evidence_id].kind.value,
            "required_fields": list(
                workflow.evidence_requirements[evidence_id].required_fields
            ),
            "project_contained": workflow.evidence_requirements[
                evidence_id
            ].project_contained,
        }
        for evidence_id in ordinary_evidence
    }

    def inventory_record(value: Any) -> dict[str, Any] | None:
        if value is None:
            return None
        return {
            "artifact_id": value.artifact_id,
            "artifact_digest": value.artifact_digest,
            "items_digest": value.items_digest,
            "item_count": value.item_count,
            "expected_post_count": value.expected_post_count,
        }

    def restore_record(value: Any) -> dict[str, Any] | None:
        if value is None:
            return None
        return {
            "tag_ref": value.tag_ref,
            "commit": value.commit,
            "verification_artifact_id": value.verification_artifact_id,
            "verification_digest": value.verification_digest,
        }

    def approval_record(value: Any) -> dict[str, Any] | None:
        if value is None:
            return None
        return {
            "request_artifact_id": value.request_artifact_id,
            "request_digest": value.request_digest,
            "action_digest": value.action_digest,
            "authorization_artifact_id": value.authorization_artifact_id,
            "authorization_digest": value.authorization_digest,
            "inventory_artifact_digest": value.inventory_artifact_digest,
            "restore_point_commit": value.restore_point_commit,
        }

    units: dict[str, dict[str, Any]] = {}
    typed_external_routes = {
        stage.route
        for stage in workflow.stages
        if stage.execution_kind.value == "typed-external-action"
    }
    for unit in manifest.units:
        route_id = owners[unit.id]
        if route_id in typed_external_routes:
            raise ValueError(
                f"program unit {unit.id!r} uses typed external-action route "
                f"{route_id!r}; external actions require the coordinator broker leaf"
            )
        route = routes.get(route_id)
        if route is None:
            raise ValueError(
                f"program unit {unit.id!r} uses unknown workflow route {route_id!r}"
            )
        required_capabilities = list(_program_required_capabilities(unit.kind.value))
        units[unit.id] = {
            "wave_id": unit.wave_id,
            "lane_id": unit.lane_id,
            "kind": unit.kind.value,
            "objective": unit.objective,
            "dependencies": list(unit.dependencies),
            "boundaries": [boundaries[item] for item in unit.boundary_ids],
            "risk": unit.risk.value,
            "irreversible": unit.irreversible,
            "inventory": inventory_record(unit.inventory),
            "restore_point": restore_record(unit.restore_point),
            "approval": approval_record(unit.approval),
            "evidence": list(unit.evidence),
            "route": route_id,
            "route_candidates": [route.primary, *route.fallbacks],
            "required_capabilities": required_capabilities,
            "physical_containment_required": bool(
                {Capability.FILE_WRITE.value, Capability.SHELL.value}
                & set(required_capabilities)
            ),
        }
    waves = {
        wave.id: {
            "order": wave.order,
            "kind": wave.kind.value,
            "parallel": wave.parallel,
            "risk": wave.risk.value,
            "unit_ids": list(wave.unit_ids),
            "gate_ids": list(wave.gate_ids),
            "gate_wave_id": wave.gate_wave_id,
            "verifies_wave_id": wave.verifies_wave_id,
            "budget": {
                "hard_spawn_cap": wave.budget.hard_spawn_cap,
                "max_attempts_per_unit": wave.budget.max_attempts_per_unit,
                "max_turns_per_worker": wave.budget.max_turns_per_worker,
                "wall_clock_seconds": wave.budget.wall_clock_seconds,
                "token_ceiling": wave.budget.token_ceiling,
                "on_exceed": wave.budget.on_exceed.value,
            },
        }
        for wave in manifest.waves
    }
    gates = {
        gate.id: {
            "order": gate.order,
            "kind": gate.kind.value,
            "wave_id": gate.wave_id,
            "owner_unit_id": gate.owner_unit_id,
            "evidence": list(gate.evidence),
        }
        for gate in manifest.gates
    }
    return {
        "pre_change_restore_point": restore_record(manifest.pre_change_restore_point),
        "evidence_requirements": evidence_requirements,
        "program_wave_evidence_policy": program_wave_evidence_policy,
        "program_blocking_severities": list(
            workflow.findings_policy.blocking_severities
        ),
        "ordered_waves": [wave.id for wave in manifest.waves],
        "ordered_units": [unit.id for unit in manifest.units],
        "ordered_program_gates": [gate.id for gate in manifest.gates],
        "waves": waves,
        "units": units,
        "gates": gates,
    }


def _program_evidence_content_problem(
    value: Any, *, label: str, allow_empty_collection: bool = False
) -> str | None:
    """Reject empty/symbolic wrappers while accepting bounded JSON content."""

    if isinstance(value, str):
        if not value.strip():
            return f"{label} must be content-bearing"
        if _SYMBOLIC_EVIDENCE_PLACEHOLDER_RE.fullmatch(value.strip()):
            return f"{label} must not be an echoed symbolic reference"
        return None
    if isinstance(value, bool) or isinstance(value, int):
        return None
    if isinstance(value, float):
        if value != value or value in {float("inf"), float("-inf")}:
            return f"{label} contains a non-finite number"
        return None
    if isinstance(value, list):
        if not value and not allow_empty_collection:
            return f"{label} must not be empty"
        for index, item in enumerate(value):
            problem = _program_evidence_content_problem(item, label=f"{label}[{index}]")
            if problem:
                return problem
        return None
    if isinstance(value, dict):
        if not value and not allow_empty_collection:
            return f"{label} must not be empty"
        for key, item in value.items():
            if not isinstance(key, str) or not key.strip():
                return f"{label} contains an invalid field name"
            problem = _program_evidence_content_problem(item, label=f"{label}.{key}")
            if problem:
                return problem
        return None
    return f"{label} has an unsupported JSON value"


def _program_text_array_problem(
    value: Any, *, label: str, allow_empty: bool
) -> str | None:
    """Require an exact array of content-bearing, non-symbolic strings."""

    if not isinstance(value, list) or (not value and not allow_empty):
        qualifier = "an array" if allow_empty else "a non-empty array"
        return f"{label} must be {qualifier} of strings"
    for index, item in enumerate(value):
        if not isinstance(item, str):
            return f"{label}[{index}] must be a string"
        problem = _program_evidence_content_problem(item, label=f"{label}[{index}]")
        if problem:
            return problem
    return None


def _program_citation_problem(value: Any, *, label: str) -> str | None:
    """Validate one concrete citation without accepting JSON scalar stand-ins."""

    if isinstance(value, str):
        return _program_evidence_content_problem(value, label=label)
    if not isinstance(value, dict):
        return f"{label} must be a concrete citation string or digest-bound object"
    keys = set(value)
    if keys == {"artifact_id", "sha256"}:
        identity = value.get("artifact_id")
    elif keys == {"path", "sha256"}:
        identity = value.get("path")
    else:
        return f"{label} must contain an exact identity and sha256 binding"
    digest = value.get("sha256")
    if not isinstance(identity, str):
        return f"{label} identity must be a string"
    problem = _program_evidence_content_problem(identity, label=f"{label}.identity")
    if problem:
        return problem
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        return f"{label}.sha256 must be a lowercase sha256 digest"
    return None


def _program_citations_problem(value: Any, *, label: str) -> str | None:
    if not isinstance(value, list) or not value:
        return f"{label} must be a non-empty array of concrete citations"
    for index, item in enumerate(value):
        problem = _program_citation_problem(item, label=f"{label}[{index}]")
        if problem:
            return problem
    return None


def _program_finding_problem(value: Any, *, label: str) -> str | None:
    if not isinstance(value, dict):
        return f"{label} must be a structured object"
    if not {"severity", "disposition", "evidence"}.issubset(value):
        return f"{label} must cite severity, disposition, and evidence"
    identity_fields = {"id", "finding-id", "summary"} & set(value)
    if not identity_fields:
        return f"{label} must have an id or summary"
    if not any(
        isinstance(value.get(field), str) and value[field].strip()
        for field in identity_fields
    ):
        return f"{label} id or summary must be a content-bearing string"
    severity = value.get("severity")
    if not isinstance(severity, str) or severity.strip().lower() not in {
        "critical",
        "high",
        "medium",
        "low",
        "info",
        "cosmetic",
    }:
        return f"{label} has an invalid severity"
    disposition = value.get("disposition")
    if not isinstance(disposition, str):
        return f"{label} has an invalid disposition"
    problem = _program_evidence_content_problem(
        disposition, label=f"{label}.disposition"
    )
    if problem:
        return problem
    return _program_citations_problem(value.get("evidence"), label=f"{label}.evidence")


def _program_evidence_profile_problem(
    document: Mapping[str, Any], profile: str
) -> str | None:
    """Apply the closed, content-bearing Mode E evidence profile."""

    if profile == "scope-record":
        if document.get("mode") != "E":
            return "program scope evidence must bind Mode E"
        for field in ("surfaces", "constraints", "risks"):
            problem = _program_text_array_problem(
                document.get(field),
                label=f"program scope evidence {field}",
                allow_empty=field != "surfaces",
            )
            if problem:
                return problem
        return None
    if profile == "command-evidence":
        if (
            not isinstance(document.get("command"), str)
            or not isinstance(document.get("exit-status"), int)
            or isinstance(document.get("exit-status"), bool)
            or not isinstance(document.get("output"), str)
        ):
            return "program command evidence fields have invalid types"
        command_problem = _program_evidence_content_problem(
            document["command"], label="program command evidence command"
        )
        if command_problem:
            return command_problem
        output = document["output"]
        if output and _SYMBOLIC_EVIDENCE_PLACEHOLDER_RE.fullmatch(output.strip()):
            return "program command evidence output must not echo a symbolic reference"
        return None
    if profile == "review-verdict":
        status_value = document.get("status")
        if (
            not isinstance(status_value, str)
            or status_value.lower() not in {"pass", "fail"}
            or not isinstance(document.get("reviewer"), str)
        ):
            return "program verdict evidence status/reviewer has an invalid type"
        reviewer_problem = _program_evidence_content_problem(
            document["reviewer"], label="program verdict reviewer"
        )
        if reviewer_problem:
            return reviewer_problem
        findings = document.get("findings")
        evidence = document.get("evidence")
        if (
            not isinstance(findings, list)
            or not isinstance(evidence, list)
            or not evidence
        ):
            return "program verdict findings/evidence must be concrete arrays"
        for index, finding in enumerate(findings):
            problem = _program_finding_problem(
                finding, label=f"program verdict finding[{index}]"
            )
            if problem:
                return problem
        return _program_citations_problem(evidence, label="program verdict evidence")
    if profile == "test-report":
        for count_field in ("passed", "failed", "skipped"):
            value = document.get(count_field)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                return "program test-report counts must be non-negative integers"
        if int(document["passed"]) + int(document["failed"]) == 0:
            return "program test-report must contain at least one executed test"
        for field in ("scope", "residual-risk"):
            problem = _program_text_array_problem(
                document.get(field),
                label=f"program test-report {field}",
                allow_empty=field == "residual-risk",
            )
            if problem:
                return problem
        return None
    if profile == "security-report":
        scanners = document.get("scanners")
        findings = document.get("findings")
        dispositions = document.get("dispositions")
        if not isinstance(scanners, list) or not scanners:
            return "program security-report scanners must be a non-empty array"
        if not isinstance(findings, list) or not isinstance(dispositions, list):
            return "program security-report findings/dispositions must be arrays"
        problem = _program_text_array_problem(
            scanners, label="program security-report scanners", allow_empty=False
        )
        if problem:
            return problem
        for index, finding in enumerate(findings):
            problem = _program_finding_problem(
                finding, label=f"program security finding[{index}]"
            )
            if problem:
                return problem
            finding_id = finding.get("id") if isinstance(finding, dict) else None
            if not isinstance(finding_id, str) or not _STAGE_ID_RE.fullmatch(
                finding_id
            ):
                return f"program security finding[{index}] requires a stable id"
        finding_ids = [str(finding["id"]) for finding in findings]
        if len(finding_ids) != len(set(finding_ids)):
            return "program security-report finding ids must be unique"
        disposition_ids: list[str] = []
        for index, disposition in enumerate(dispositions):
            if not isinstance(disposition, dict) or not {
                "finding-id",
                "disposition",
                "evidence",
            }.issubset(disposition):
                return (
                    f"program security disposition[{index}] must bind a finding, "
                    "decision, and evidence"
                )
            disposition_id = disposition.get("finding-id")
            if not isinstance(disposition_id, str) or not _STAGE_ID_RE.fullmatch(
                disposition_id
            ):
                return (
                    f"program security disposition[{index}] has an invalid finding id"
                )
            decision = disposition.get("disposition")
            if not isinstance(decision, str):
                return (
                    f"program security disposition[{index}] decision must be a string"
                )
            problem = _program_evidence_content_problem(
                decision, label=f"program security disposition[{index}].disposition"
            )
            if problem:
                return problem
            problem = _program_citations_problem(
                disposition.get("evidence"),
                label=f"program security disposition[{index}].evidence",
            )
            if problem:
                return problem
            disposition_ids.append(disposition_id)
        if len(disposition_ids) != len(set(disposition_ids)):
            return "program security-report disposition ids must be unique"
        if set(disposition_ids) != set(finding_ids):
            return "program security-report dispositions must exactly cover every finding id"
        return _program_text_array_problem(
            document.get("residual-risk"),
            label="program security-report residual-risk",
            allow_empty=True,
        )
    if profile == "closeout-record":
        outcome = document.get("outcome")
        if not isinstance(outcome, str):
            return "program closeout outcome must be a string"
        outcome_problem = _program_evidence_content_problem(
            outcome, label="program closeout outcome"
        )
        if outcome_problem:
            return outcome_problem
        gates = document.get("gates")
        if not isinstance(gates, list) or not gates:
            return "program closeout gate ledger must be a non-empty array"
        for index, gate in enumerate(gates):
            if (
                not isinstance(gate, dict)
                or not {"id", "status", "evidence"}.issubset(gate)
                or gate.get("status")
                not in {"passed", "not-applicable", "accepted-risk"}
                or not isinstance(gate.get("evidence"), list)
                or not gate["evidence"]
            ):
                return f"program closeout gate[{index}] is not a resolved gate ledger object"
            if not isinstance(gate.get("id"), str):
                return f"program closeout gate[{index}] id must be a string"
            problem = _program_citations_problem(
                gate.get("evidence"),
                label=f"program closeout gate[{index}].evidence",
            )
            if problem:
                return problem
        accepted_risks = document.get("accepted-risks")
        learnings = document.get("learnings")
        if not isinstance(accepted_risks, list) or not isinstance(learnings, list):
            return "program closeout accepted-risks/learnings must be arrays"
        required_risk_fields = {
            "risk_id",
            "finding_id",
            "reason",
            "accepted_by",
            "owner",
            "ticket",
            "revisit",
            "affected_gate",
            "evidence_path",
            "evidence_sha256",
        }
        for index, risk in enumerate(accepted_risks):
            if not isinstance(risk, dict) or not required_risk_fields.issubset(risk):
                return f"program closeout accepted-risk[{index}] is incomplete"
            for field in required_risk_fields:
                if not isinstance(risk[field], str):
                    return (
                        f"program closeout accepted-risk[{index}].{field} "
                        "must be a string"
                    )
                problem = _program_evidence_content_problem(
                    risk[field],
                    label=f"program closeout accepted-risk[{index}].{field}",
                )
                if problem:
                    return problem
        return _program_text_array_problem(
            learnings,
            label="program closeout learnings",
            allow_empty=True,
        )
    return "ordinary program evidence has no closed Mode E validation profile"


def _program_evidence_document_problem(
    content: bytes, requirement: Mapping[str, Any]
) -> str | None:
    """Validate one canonical typed workflow-evidence JSON document."""

    if requirement.get("project_contained") is not True:
        return "program evidence is not declared project-contained"
    required_fields = requirement.get("required_fields")
    if not isinstance(required_fields, list) or any(
        not isinstance(item, str) or not item for item in required_fields
    ):
        return "program evidence required-field contract is malformed"
    try:
        document = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return f"program evidence is not valid JSON: {exc}"
    if not isinstance(document, dict):
        return "program evidence must be a JSON object"
    missing = [field for field in required_fields if field not in document]
    if missing:
        return "program evidence is missing required fields: " + ", ".join(missing)
    if any(document[field] is None for field in required_fields):
        return "program evidence required fields must not be null"
    profile = requirement.get("validation_profile")
    kind = requirement.get("kind")
    expected_kind = {
        "scope-record": "artifact",
        "command-evidence": "command-output",
        "review-verdict": "verdict",
        "test-report": "findings-report",
        "security-report": "findings-report",
        "closeout-record": "artifact",
    }.get(str(profile))
    if expected_kind is None or kind != expected_kind:
        return "program evidence profile differs from its canonical kind"
    return _program_evidence_profile_problem(document, str(profile))


def _program_evidence_pass_problem(
    content: bytes,
    requirement: Mapping[str, Any],
    blocking_severities: Sequence[str],
) -> str | None:
    """Require evidence used by a successful unit/gate to carry passing semantics."""

    try:
        document = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return "program evidence is not valid JSON"
    if not isinstance(document, dict):
        return "program evidence must be a JSON object"
    kind = requirement.get("kind")
    if kind == "command-output" and document.get("exit-status") != 0:
        return "program command evidence has a non-zero exit status"
    if kind == "verdict" and str(document.get("status", "")).lower() != "pass":
        return "program verdict evidence is not PASS"
    if kind in {"verdict", "findings-report"}:
        failed = document.get("failed")
        if isinstance(failed, int) and not isinstance(failed, bool) and failed > 0:
            return "program findings report contains failed checks"
        findings = document.get("findings")
        if findings is not None:
            if not isinstance(findings, list) or any(
                not isinstance(item, dict) for item in findings
            ):
                return "program findings report entries must be structured objects"
            blocking = {str(value).strip().lower() for value in blocking_severities}
            present = sorted(
                {
                    str(item.get("severity", "")).strip().lower()
                    for item in findings
                    if str(item.get("severity", "")).strip().lower() in blocking
                }
            )
            if present:
                return (
                    "program findings report contains blocking severities: "
                    + ", ".join(present)
                )
    return None


def _program_closeout_projection(
    run: Mapping[str, Any], contract: Mapping[str, Any]
) -> tuple[list[dict[str, Any]] | None, list[dict[str, Any]] | None, str | None]:
    """Project the exact authoritative gate/risk ledger a closeout must repeat."""

    ordered = contract.get("ordered_program_gates")
    checkpoints = contract.get("gate_checkpoints")
    gates = contract.get("gates")
    history = run.get("gate_history")
    risks = run.get("accepted_risks")
    if (
        not isinstance(ordered, list)
        or not isinstance(checkpoints, list)
        or not isinstance(gates, dict)
        or not isinstance(history, list)
        or not isinstance(risks, list)
        or any(not isinstance(item, dict) for item in [*checkpoints, *history, *risks])
    ):
        return None, None, "program closeout authoritative ledgers are malformed"
    by_checkpoint = {
        item.get("gate_id"): item
        for item in checkpoints
        if isinstance(item.get("gate_id"), str)
    }
    if len(by_checkpoint) != len(checkpoints) or set(by_checkpoint) != set(ordered):
        return None, None, "program closeout requires every ordered gate checkpoint"
    projected: list[dict[str, Any]] = []
    for gate_id in ordered:
        gate = gates.get(gate_id)
        checkpoint = by_checkpoint.get(gate_id)
        if not isinstance(gate, dict) or not isinstance(checkpoint, dict):
            return None, None, "program closeout references an unknown gate"
        status = "passed"
        if gate.get("kind") == "pipeline":
            resolved = [
                entry
                for entry in history
                if entry.get("gate") == gate_id
                and entry.get("status") in POSITION_STATUSES
            ]
            if len(resolved) != 1:
                return (
                    None,
                    None,
                    (
                        f"program closeout pipeline gate {gate_id!r} has no unique "
                        "authoritative resolution"
                    ),
                )
            status = str(resolved[0]["status"])
        elif gate.get("kind") != "program-wave":
            return None, None, "program closeout gate kind is malformed"
        records = checkpoint.get("verification_records")
        if not isinstance(records, list) or any(
            not isinstance(item, dict) for item in records
        ):
            return None, None, "program closeout gate evidence ledger is malformed"
        evidence = [
            {
                "artifact_id": record.get("artifact_id"),
                "sha256": record.get("artifact_sha256"),
            }
            for record in records
        ]
        if any(
            not isinstance(item["artifact_id"], str)
            or not isinstance(item["sha256"], str)
            for item in evidence
        ):
            return None, None, "program closeout gate evidence identity is malformed"
        projected.append({"id": gate_id, "status": status, "evidence": evidence})
    return projected, [dict(item) for item in risks], None


def _program_closeout_document_problem(
    content: bytes, run: Mapping[str, Any], contract: Mapping[str, Any]
) -> str | None:
    try:
        document = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return "program closeout evidence is not valid JSON"
    if not isinstance(document, dict):
        return "program closeout evidence must be an object"
    gates, risks, problem = _program_closeout_projection(run, contract)
    if problem:
        return problem
    if document.get("gates") != gates:
        return "program closeout gate ledger differs from authoritative checkpoints"
    if document.get("accepted-risks") != risks:
        return "program closeout accepted-risk ledger differs from pipeline state"
    return None


def _program_containment_record(
    unit: Mapping[str, Any],
    *,
    provider: Any,
    route: Any,
    dispatch_id: Any,
    unit_id: Any,
    workspace_target: Any,
    pre_workspace_checkpoint_digest: Any,
    issuer: Any,
) -> dict[str, Any]:
    boundaries = unit.get("boundaries")
    boundary_digest = hashlib.sha256(
        json.dumps(
            boundaries,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    core = {
        "schema_version": 1,
        "kind": "physical-program-boundary-containment",
        "enforcement": "adapter-physical-no-follow",
        "issuer": issuer,
        "policy": "bounded-writes" if boundaries else "deny-all-writes",
        "boundary_digest": boundary_digest,
        "provider": provider,
        "route": route,
        "dispatch_id": dispatch_id,
        "unit_id": unit_id,
        "workspace_target": workspace_target,
        "pre_workspace_checkpoint_digest": pre_workspace_checkpoint_digest,
    }
    attestation_sha256 = hashlib.sha256(
        json.dumps(
            core,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return {**core, "attestation_sha256": attestation_sha256}


def _program_safeguard_problem(
    root: Path,
    run: Mapping[str, Any],
    contract: Mapping[str, Any],
    manifest: ProgramManifest,
) -> str | None:
    """Revalidate every persisted program artifact and immutable git binding."""

    records = contract.get("safeguard_verifications")
    if not isinstance(records, list) or any(
        not isinstance(item, dict) for item in records
    ):
        return "program safeguard verification ledger is malformed"
    manifest_record = contract.get("manifest")
    if not isinstance(manifest_record, dict):
        return "program manifest record is malformed"
    typed: dict[tuple[str, str], tuple[str, str, dict[str, Any]]] = {}

    def add(
        unit_id: str,
        artifact_id: str,
        kind: str,
        digest: str,
        details: Mapping[str, Any],
    ) -> None:
        typed[(unit_id, artifact_id)] = (kind, digest, dict(details))

    for unit in manifest.units:
        if unit.inventory is not None:
            add(
                unit.id,
                unit.inventory.artifact_id,
                "inventory",
                unit.inventory.artifact_digest,
                {
                    "items_digest": unit.inventory.items_digest,
                    "item_count": unit.inventory.item_count,
                    "expected_post_count": unit.inventory.expected_post_count,
                },
            )
        if unit.restore_point is not None:
            add(
                unit.id,
                unit.restore_point.verification_artifact_id,
                "restore-point",
                unit.restore_point.verification_digest,
                {
                    "tag_ref": unit.restore_point.tag_ref,
                    "commit": unit.restore_point.commit,
                },
            )
        if unit.approval is not None:
            approval_details = {
                "action_digest": unit.approval.action_digest,
                "inventory_artifact_digest": unit.approval.inventory_artifact_digest,
                "restore_point_commit": unit.approval.restore_point_commit,
                "authorization_consumed": False,
            }
            add(
                unit.id,
                unit.approval.request_artifact_id,
                "approval-request",
                unit.approval.request_digest,
                approval_details,
            )
            add(
                unit.id,
                unit.approval.authorization_artifact_id,
                "approval-authorization",
                unit.approval.authorization_digest,
                approval_details,
            )

    seen: set[tuple[str, str]] = set()
    fs = ProjectFS(root)
    binding = contract.get("binding")
    if not isinstance(binding, dict):
        return "program safeguard verification has no manifest binding"
    aggregate_bytes = 0
    for raw in records:
        record = cast(dict[str, Any], raw)
        unit_id = record.get("unit_id")
        artifact_id = record.get("artifact_id")
        key = (str(unit_id), str(artifact_id))
        if key in seen:
            return "program safeguard verification ledger contains duplicates"
        seen.add(key)
        units = {unit.id: unit for unit in manifest.units}
        manifest_unit = units.get(str(unit_id))
        if manifest_unit is None:
            return "program safeguard verification references an unknown unit"
        if record.get("run_id") != binding.get("run_id") or record.get(
            "manifest_digest"
        ) != binding.get("manifest_digest"):
            return "program safeguard verification belongs to another run or manifest"
        artifact_path = record.get("artifact_path")
        artifact_sha = record.get("artifact_sha256")
        if not isinstance(artifact_path, str) or not isinstance(artifact_sha, str):
            return "program safeguard artifact identity is malformed"
        try:
            content, actual_sha, byte_count = _read_program_file_bounded(
                fs,
                artifact_path,
                maximum_bytes=_MAX_PROGRAM_SAFEGUARD_BYTES,
            )
        except (FileNotFoundError, OSError, UnsafePathError, ValueError) as exc:
            return f"program safeguard artifact is unavailable: {exc}"
        aggregate_bytes += byte_count
        if aggregate_bytes > _MAX_PROGRAM_SAFEGUARD_AGGREGATE_BYTES:
            return "program safeguard artifacts exceed the aggregate safety limit"
        if actual_sha != artifact_sha:
            return (
                f"program safeguard artifact {artifact_id!r} changed after verification"
            )

        expected = typed.get(key)
        if artifact_id == "frozen-manifest":
            expected = (
                "manifest",
                str(manifest_record.get("file_sha256")),
                {
                    "manifest_digest": manifest.digest,
                    "revision": manifest.revision,
                    "parent_digest": manifest.parent_digest,
                },
            )
            if artifact_path != manifest_record.get("path"):
                return "frozen-manifest verification points at a different file"
        elif artifact_id == manifest.pre_change_restore_point.verification_artifact_id:
            expected = (
                "restore-point",
                manifest.pre_change_restore_point.verification_digest,
                {
                    "tag_ref": manifest.pre_change_restore_point.tag_ref,
                    "commit": manifest.pre_change_restore_point.commit,
                },
            )
        if expected is not None:
            kind, digest, details = expected
            if (
                record.get("kind") != kind
                or artifact_sha != digest
                or record.get("details") != details
            ):
                return f"program safeguard {artifact_id!r} differs from its typed reference"
            if kind == "inventory":
                try:
                    document = json.loads(content)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    return f"program inventory artifact is invalid JSON: {exc}"
                if not isinstance(document, dict) or not isinstance(
                    document.get("items"), list
                ):
                    return "program inventory artifact has no items array"
                items = document["items"]
                items_digest = hashlib.sha256(
                    json.dumps(
                        items,
                        ensure_ascii=False,
                        allow_nan=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    ).encode("utf-8")
                ).hexdigest()
                if (
                    items_digest != details["items_digest"]
                    or len(items) != details["item_count"]
                    or document.get("item_count") != details["item_count"]
                    or document.get("expected_post_count")
                    != details["expected_post_count"]
                ):
                    return "program inventory artifact count/digest contract changed"
            if kind == "restore-point":
                try:
                    resolved = subprocess.run(
                        [
                            "git",
                            "-C",
                            str(root),
                            "rev-parse",
                            "--verify",
                            f"{details['tag_ref']}^{{commit}}",
                        ],
                        check=True,
                        capture_output=True,
                        text=True,
                        timeout=15,
                    ).stdout.strip()
                except (OSError, subprocess.SubprocessError) as exc:
                    return f"program restore tag is unavailable: {exc}"
                if resolved != details["commit"]:
                    return "program restore tag moved after verification"
        else:
            if (
                record.get("kind") != "evidence"
                or artifact_id not in manifest_unit.evidence
            ):
                return "program evidence verification is not declared by its unit"
            evidence_details = record.get("details")
            if not isinstance(evidence_details, dict) or evidence_details.get(
                "content_bytes"
            ) != len(content):
                return "program evidence byte-count verification is inconsistent"
            evidence_requirements = contract.get("evidence_requirements")
            requirement = (
                evidence_requirements.get(artifact_id)
                if isinstance(evidence_requirements, dict)
                else None
            )
            if not isinstance(requirement, dict):
                return "ordinary program evidence has no frozen workflow requirement"
            if (
                evidence_details.get("evidence_kind") != requirement.get("kind")
                or evidence_details.get("validation_profile")
                != requirement.get("validation_profile")
                or evidence_details.get("required_fields")
                != requirement.get("required_fields")
                or evidence_details.get("source") != "structured-terminal-output"
                or not isinstance(evidence_details.get("source_output_sha256"), str)
            ):
                return (
                    "program evidence verification differs from its workflow contract"
                )
            evidence_problem = _program_evidence_document_problem(content, requirement)
            if evidence_problem:
                return evidence_problem
            pass_problem = _program_evidence_pass_problem(
                content,
                requirement,
                cast(Sequence[str], contract.get("program_blocking_severities", [])),
            )
            if pass_problem:
                return pass_problem
            if requirement.get("validation_profile") == "closeout-record":
                closeout_problem = _program_closeout_document_problem(
                    content, run, contract
                )
                if closeout_problem:
                    return closeout_problem

    audit_gate_ids = set(manifest.waves[1].gate_ids)
    checkpoints = contract.get("gate_checkpoints", [])
    checkpoint_ids = {
        item.get("gate_id") for item in checkpoints if isinstance(item, dict)
    }
    if audit_gate_ids.issubset(checkpoint_ids):
        required = {
            (
                gate.owner_unit_id,
                evidence_id,
            )
            for gate in manifest.gates
            if gate.id in audit_gate_ids
            for evidence_id in gate.evidence
        }
        if not required.issubset(seen):
            return "completed Wave 0 gate lacks live content-addressed evidence"
    return None


def _program_completion_digest(contract: Mapping[str, Any]) -> str:
    attempts = contract.get("unit_attempts", [])
    checkpoints = contract.get("gate_checkpoints", [])
    safeguards = contract.get("safeguard_verifications", [])
    projection = {
        "binding": contract.get("binding"),
        "completed_units": contract.get("completed_units"),
        "attempts": [
            {
                "unit_id": item.get("unit_id"),
                "attempt": item.get("attempt"),
                "dispatch_id": item.get("dispatch_id"),
                "provider": item.get("provider"),
                "route": item.get("route"),
                "status": item.get("status"),
                "output_artifact_sha256": item.get("output_artifact_sha256"),
                "workspace_checkpoint": item.get("post_workspace_checkpoint"),
                "evidence": item.get("evidence_verifications"),
            }
            for item in attempts
            if isinstance(item, dict)
        ],
        "gates": checkpoints,
        "safeguards": safeguards,
        "completion_workspace_checkpoint": contract.get(
            "completion_workspace_checkpoint"
        ),
    }
    return hashlib.sha256(
        json.dumps(
            projection,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _program_reconciliation_problem(
    root: Path,
    run: Mapping[str, Any],
    contract: Mapping[str, Any],
    record: Mapping[str, Any],
    artifact_document: Mapping[str, Any],
) -> str | None:
    """Validate one explicit operator reconciliation of an orphaned Mode E claim."""

    reconciliation = record.get("reconciliation")
    if not isinstance(reconciliation, dict):
        return "program stale-attempt reconciliation record is malformed"
    expected_fields = {
        "schema_version",
        "kind",
        "run_id",
        "program_manifest_digest",
        "unit_id",
        "dispatch_id",
        "attempt",
        "provider",
        "route",
        "reason",
        "reconciled_by",
        "reconciled_at",
        "evidence_path",
        "evidence_sha256",
        "workspace_checkpoint",
    }
    if set(reconciliation) != expected_fields:
        return "program stale-attempt reconciliation has unexpected or missing fields"
    if (
        reconciliation.get("schema_version") != 1
        or reconciliation.get("kind") != "operator-stale-program-attempt-reconciliation"
        or reconciliation.get("reason") != "coordinator-crash"
        or record.get("status") != "cancelled"
    ):
        return "program stale-attempt reconciliation has an invalid type or status"
    expected_values = {
        "run_id": run.get("run_id"),
        "program_manifest_digest": cast(Mapping[str, Any], contract.get("binding"))[
            "manifest_digest"
        ],
        "unit_id": record.get("unit_id"),
        "dispatch_id": record.get("dispatch_id"),
        "attempt": record.get("attempt"),
        "provider": record.get("provider"),
        "route": record.get("route"),
    }
    for field, expected in expected_values.items():
        if reconciliation.get(field) != expected:
            return f"program stale-attempt reconciliation differs from its {field}"
    operator = reconciliation.get("reconciled_by")
    if (
        not isinstance(operator, str)
        or not operator.strip()
        or len(operator.encode("utf-8")) > 256
    ):
        return "program stale-attempt reconciliation has no bounded operator identity"
    if reconciliation.get("reconciled_at") != record.get("completed_at"):
        return "program stale-attempt reconciliation timestamp is inconsistent"
    required = record.get("required_capabilities")
    if not isinstance(required, list):
        return "program stale-attempt capability contract is malformed"
    if set(required) & _STALE_ATTEMPT_FORBIDDEN_CAPABILITIES:
        return "side-effect-capable program attempt has a stale reconciliation"
    before = record.get("pre_workspace_checkpoint")
    after = record.get("post_workspace_checkpoint")
    if before != after or reconciliation.get("workspace_checkpoint") != before:
        return (
            "program stale-attempt reconciliation did not preserve its pre-checkpoint"
        )
    if (
        record.get("changed_paths") != []
        or record.get("evidence") != []
        or record.get("evidence_verifications") != []
        or record.get("output_sha256") is not None
    ):
        return "program stale-attempt reconciliation contains worker output or changes"
    if not isinstance(before, dict):
        return "program stale-attempt reconciliation checkpoint is missing"
    expected_boundary_digest = hashlib.sha256(
        json.dumps(
            {
                "before": before.get("content_digest"),
                "after": before.get("content_digest"),
                "changed_paths": [],
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    if record.get("boundary_snapshot_digest") != expected_boundary_digest:
        return "program stale-attempt reconciliation boundary digest is inconsistent"

    evidence_path = reconciliation.get("evidence_path")
    evidence_sha = reconciliation.get("evidence_sha256")
    evidence_prefix = _state_layout(root).artifacts + "/reconciliation/"
    if (
        not isinstance(evidence_path, str)
        or not evidence_path.startswith(evidence_prefix)
        or Path(evidence_path).is_absolute()
        or ".." in Path(evidence_path).parts
        or not isinstance(evidence_sha, str)
        or not re.fullmatch(r"[0-9a-f]{64}", evidence_sha)
    ):
        return "program stale-attempt reconciliation evidence reference is invalid"
    try:
        _evidence, actual_sha, _byte_count = _read_program_file_bounded(
            ProjectFS(root),
            evidence_path,
            maximum_bytes=_MAX_PROGRAM_ARTIFACT_BYTES,
        )
    except (FileNotFoundError, OSError, UnsafePathError, ValueError):
        return "program stale-attempt reconciliation evidence is unavailable"
    if actual_sha != evidence_sha:
        return "program stale-attempt reconciliation evidence changed after recording"
    if dict(artifact_document) != reconciliation:
        return "program stale-attempt reconciliation artifact differs from its ledger"
    return None


def _program_terminal_artifact_problem(
    root: Path,
    run: Mapping[str, Any],
    contract: Mapping[str, Any],
    record: Mapping[str, Any],
) -> str | None:
    """Re-hash and semantically bind one terminal Mode E result artifact."""

    output_path = record.get("output_path")
    artifact_sha = record.get("output_artifact_sha256")
    binding = contract.get("binding")
    run_id = run.get("run_id")
    manifest_digest = (
        binding.get("manifest_digest") if isinstance(binding, Mapping) else None
    )
    unit_id = record.get("unit_id")
    attempt = record.get("attempt")
    if (
        not isinstance(run_id, str)
        or not _STAGE_ID_RE.fullmatch(run_id)
        or not isinstance(manifest_digest, str)
        or not re.fullmatch(r"[0-9a-f]{64}", manifest_digest)
        or not isinstance(unit_id, str)
        or not _STAGE_ID_RE.fullmatch(unit_id)
        or not isinstance(attempt, int)
        or isinstance(attempt, bool)
        or attempt < 1
        or not isinstance(output_path, str)
        or Path(output_path).is_absolute()
        or ".." in Path(output_path).parts
        or not isinstance(artifact_sha, str)
        or not re.fullmatch(r"[0-9a-f]{64}", artifact_sha)
    ):
        return "program terminal result artifact identity is invalid"
    artifact_kind = (
        "reconciliation" if record.get("reconciliation") is not None else "terminal"
    )
    expected_path = (
        f"{_state_layout(root).artifacts}/program/runs/{run_id}/"
        f"{manifest_digest}/{unit_id}/{attempt}/{artifact_kind}-{artifact_sha}.json"
    )
    if output_path != expected_path:
        return "program terminal result artifact belongs to another run or manifest"
    try:
        fs = ProjectFS(root)
        artifact_info = fs.path(output_path).lstat()
        content, actual_sha, _byte_count = _read_program_file_bounded(
            fs,
            output_path,
            maximum_bytes=_MAX_PROGRAM_ARTIFACT_BYTES,
        )
        if (
            actual_sha != artifact_sha
            or not stat.S_ISREG(artifact_info.st_mode)
            or stat.S_IMODE(artifact_info.st_mode) != 0o600
        ):
            return "program terminal result artifact changed after recording"
        document = json.loads(content)
    except (
        FileNotFoundError,
        json.JSONDecodeError,
        OSError,
        UnsafePathError,
        ValueError,
    ):
        return "program terminal result artifact is unavailable or malformed"
    if not isinstance(document, dict):
        return "program terminal result artifact is not an object"
    if record.get("reconciliation") is not None:
        return _program_reconciliation_problem(root, run, contract, record, document)

    expected_fields = {
        "schema_version",
        "run_id",
        "program_manifest_digest",
        "unit_id",
        "attempt",
        "dispatch_id",
        "dispatch_attempt",
        "provider",
        "route",
        "status",
        "output",
        "error",
        "evidence",
    }
    if set(document) != expected_fields or document.get("schema_version") != 1:
        return "program terminal result artifact has an invalid contract"
    if (
        document.get("run_id") != run_id
        or document.get("program_manifest_digest") != manifest_digest
    ):
        return "program terminal result artifact differs from its run or manifest"
    if (
        document.get("status") not in TERMINAL_STAGE_STATUSES
        or not isinstance(document.get("dispatch_attempt"), int)
        or isinstance(document.get("dispatch_attempt"), bool)
        or cast(int, document["dispatch_attempt"]) < 1
        or not isinstance(document.get("evidence"), list)
        or any(not isinstance(item, str) for item in document["evidence"])
        or (
            document.get("error") is not None
            and not isinstance(document.get("error"), str)
        )
    ):
        return "program terminal result artifact fields are malformed"
    for field in ("unit_id", "attempt", "dispatch_id", "provider", "route"):
        if document.get(field) != record.get(field):
            return f"program terminal result artifact differs from its {field}"
    if document.get("evidence") != record.get("evidence"):
        return "program terminal result evidence differs from the attempt ledger"
    output = document.get("output")
    output_sha = record.get("output_sha256")
    if output is None:
        if output_sha is not None:
            return "program terminal output digest exists without output content"
    elif (
        not isinstance(output, str)
        or hashlib.sha256(output.encode("utf-8")).hexdigest() != output_sha
    ):
        return "program terminal output digest differs from its artifact document"
    document_status = document.get("status")
    record_status = record.get("status")
    enforcement_error = record.get("error")
    pipeline_enforced = isinstance(enforcement_error, str) and (
        enforcement_error.startswith(
            "program worker changed files outside its exact boundary:"
        )
        or enforcement_error.startswith("required evidence was not returned:")
        or enforcement_error.startswith("program evidence verification failed:")
        or enforcement_error
        == "every declared evidence artifact requires one exact content-addressed verification"
        or enforcement_error
        in {
            "program wave token ceiling was exceeded",
            "program wave wall-clock budget was exceeded",
        }
    )
    if document_status != record_status:
        if not (
            document_status == "succeeded"
            and record_status == "failed"
            and pipeline_enforced
        ):
            return "program terminal result status differs from the attempt ledger"
    elif document.get("error") != record.get("error") and not pipeline_enforced:
        return "program terminal result error differs from the attempt ledger"
    return None


def _program_execution_problem(
    target: str | Path, run: Mapping[str, Any]
) -> str | None:
    """Validate the frozen Mode E binding and its no-replay transition ledger."""

    contract = run.get("program_execution")
    if contract is None:
        return None
    if run.get("managed_execution") is not None:
        return "managed and program execution contracts are mutually exclusive"
    if not isinstance(contract, dict):
        return "program execution contract is malformed"
    if run.get("mode") != "E":
        return "program execution may be bound only to Mode E"
    if contract.get("schema_version") != 1:
        return "program execution schema version is unsupported"
    if contract.get("status") not in PROGRAM_EXECUTION_STATUSES:
        return "program execution status is malformed"

    binding = contract.get("binding")
    manifest_record = contract.get("manifest")
    if not isinstance(binding, dict) or not isinstance(manifest_record, dict):
        return "program manifest binding is malformed"
    manifest_path = manifest_record.get("path")
    if (
        not isinstance(manifest_path, str)
        or not manifest_path
        or Path(manifest_path).is_absolute()
        or ".." in Path(manifest_path).parts
    ):
        return "program manifest path is not project-relative and contained"
    try:
        root = ProjectFS(Path(target).expanduser()).root
        manifest_file = ProjectFS(root).path(manifest_path)
        raw_manifest, raw_manifest_sha, _manifest_bytes = _read_program_file_bounded(
            ProjectFS(root),
            manifest_path,
            maximum_bytes=_MAX_PROGRAM_SAFEGUARD_BYTES,
        )
        from claude_kit import scaffold
        from claude_kit.program_runtime import (
            ProgramManifestValidationError,
            load_program_manifest,
            validate_program_manifest_binding,
        )

        with ExitStack() as resources:
            packaged_schema = (
                scaffold.payload_dir(resources)
                / "schemas"
                / "program-manifest.schema.json"
            )
            manifest = load_program_manifest(manifest_file, schema_path=packaged_schema)
    except (
        FileNotFoundError,
        OSError,
        UnsafePathError,
        ValueError,
        ProgramManifestValidationError,
    ) as exc:
        return f"cannot verify frozen program manifest: {exc}"
    if manifest_record.get("file_sha256") != raw_manifest_sha:
        return "program manifest file bytes changed after binding"
    expected_manifest_record = {
        "path": manifest_path,
        "digest": manifest.digest,
        "file_sha256": raw_manifest_sha,
        "revision": manifest.revision,
        "parent_digest": manifest.parent_digest,
    }
    if manifest_record != expected_manifest_record:
        return "program manifest identity differs from its frozen binding"

    try:
        _workflow_id, _workflow_version, workflow_digest = _current_workflow_identity()
        validated = validate_program_manifest_binding(
            manifest,
            run_id=str(run.get("run_id", "")),
            source_commit=str(binding.get("source_commit", "")),
            workflow_definition_digest=workflow_digest,
            gate_definition_digest=str(run.get("gate_definition_digest", "")),
            selection_digest=str(run.get("selection_digest", "")),
            ordered_gates=cast(Sequence[str], run.get("ordered_gates", [])),
            expected_revision=manifest.revision,
            previous_manifest_digest=contract.get("previous_manifest_digest"),
        )
    except (OSError, ValueError, ProgramManifestValidationError) as exc:
        return f"program manifest authoritative binding is invalid: {exc}"
    expected_binding = {
        "manifest_digest": validated.manifest_digest,
        "revision": validated.revision,
        "parent_digest": validated.parent_digest,
        "run_id": validated.run_id,
        "source_commit": validated.source_commit,
        "workflow_definition_digest": validated.workflow_definition_digest,
        "gate_definition_digest": validated.gate_definition_digest,
        "selection_digest": validated.selection_digest,
        "pipeline_gate_ids": list(validated.pipeline_gate_ids),
    }
    if binding != expected_binding:
        return "program manifest binding differs from authoritative run inputs"
    if contract.get("program_id") != manifest.program_id:
        return "program id differs from the frozen manifest"
    if contract.get("objective") != manifest.objective or manifest.objective != run.get(
        "task"
    ):
        return "program objective differs from the active pipeline task"

    identity, identity_problem = _git_identity(root)
    if identity_problem or identity is None:
        return identity_problem or "cannot verify program source checkout identity"
    if identity["commit"] != binding.get("source_commit"):
        return "source checkout HEAD changed after the program manifest was bound"

    try:
        expected_projection = _program_contract_projection(manifest)
    except (OSError, ValueError) as exc:
        return f"cannot project the canonical program contract: {exc}"
    for field, expected in expected_projection.items():
        if contract.get(field) != expected:
            return f"program {field.replace('_', ' ')} differs from the frozen manifest"
    safeguard_problem = _program_safeguard_problem(root, run, contract, manifest)
    if safeguard_problem:
        return safeguard_problem

    try:
        providers, projection_digest = _installed_provider_projection(root)
    except (OSError, ValueError) as exc:
        return f"cannot verify installed provider projection: {exc}"
    if contract.get("providers") != list(providers):
        return "program provider set changed after binding"
    if contract.get("provider_projection_digest") != projection_digest:
        return "program provider projection changed after binding"

    workspace = contract.get("workspace")
    if not isinstance(workspace, dict) or set(workspace) != {
        "worker_id",
        "target_path",
        "base_commit",
    }:
        return "program workspace binding is malformed"
    if workspace.get("base_commit") != binding.get("source_commit"):
        return "program workspace base commit differs from the manifest source commit"
    run_id = run.get("run_id")
    try:
        manager = WorktreeManager(root)
        record = manager.verify(str(run_id), str(workspace.get("worker_id")))
        if record.target_path != workspace.get(
            "target_path"
        ) or record.base_commit != workspace.get("base_commit"):
            return "program workspace differs from its ownership record"
        workspace_root = (root / record.target_path).resolve(strict=True)
        options = _installed_runtime_options(root)
        control_digest = _provider_control_surface_digest(
            workspace_root, options, providers
        )
    except (OSError, ValueError, WorktreeError) as exc:
        return f"cannot verify program workspace ownership: {exc}"
    if contract.get("provider_control_surface_digest") != control_digest:
        return "program workspace provider control surface changed after binding"
    raw_binding_checkpoint = contract.get("binding_workspace_checkpoint")
    try:
        if not isinstance(raw_binding_checkpoint, dict):
            raise WorktreeError("binding checkpoint is missing")
        binding_checkpoint = WorkspaceCheckpoint.from_dict(raw_binding_checkpoint)
    except WorktreeError as exc:
        return f"program binding workspace checkpoint is invalid: {exc}"

    attempts = contract.get("unit_attempts")
    completed = contract.get("completed_units")
    wave_states = contract.get("wave_states")
    checkpoints = contract.get("gate_checkpoints")
    if not isinstance(attempts, list) or any(
        not isinstance(item, dict) for item in attempts
    ):
        return "program unit-attempt ledger is malformed"
    if (
        not isinstance(completed, list)
        or len(completed) != len(set(completed))
        or any(item not in expected_projection["ordered_units"] for item in completed)
    ):
        return "program completed-unit ledger is malformed"
    if not isinstance(wave_states, dict) or set(wave_states) != set(
        expected_projection["ordered_waves"]
    ):
        return "program wave-state ledger is malformed"
    if not isinstance(checkpoints, list) or any(
        not isinstance(item, dict) for item in checkpoints
    ):
        return "program gate-checkpoint ledger is malformed"

    succeeded: set[str] = set()
    expected_pre_checkpoint = binding_checkpoint.to_dict()
    safeguard_records = contract.get("safeguard_verifications")
    if not isinstance(safeguard_records, list):
        return "program safeguard verification ledger is malformed"
    safeguard_by_key = {
        (item.get("unit_id"), item.get("artifact_id")): item
        for item in safeguard_records
        if isinstance(item, dict)
    }
    attempt_numbers: dict[str, list[int]] = {
        unit_id: [] for unit_id in expected_projection["ordered_units"]
    }
    for sequence, raw_attempt in enumerate(attempts, start=1):
        unit_id = raw_attempt.get("unit_id")
        if unit_id not in expected_projection["units"]:
            return "program attempt references an unknown unit"
        unit_contract = expected_projection["units"][unit_id]
        if raw_attempt.get("sequence") != sequence:
            return "program attempt sequence is not contiguous"
        attempt = raw_attempt.get("attempt")
        if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
            return "program attempt number is malformed"
        attempt_numbers[unit_id].append(attempt)
        if unit_id in succeeded:
            return f"completed program unit {unit_id!r} was replayed"
        if raw_attempt.get("provider") not in providers:
            return "program attempt provider is outside the frozen provider set"
        if raw_attempt.get("route") not in unit_contract["route_candidates"]:
            return "program attempt route is outside the frozen route candidates"
        effective = raw_attempt.get("required_capabilities")
        floor = set(unit_contract["required_capabilities"])
        allowed = floor | {Capability.MESSAGE.value}
        if (
            not isinstance(effective, list)
            or any(not isinstance(item, str) for item in effective)
            or effective != sorted(effective)
            or len(effective) != len(set(effective))
            or not floor.issubset(effective)
            or not set(effective).issubset(allowed)
        ):
            return "program attempt effective capability closure is invalid"
        attested = raw_attempt.get("attested_capabilities")
        if not isinstance(attested, list) or attested != effective:
            return "program attempt lacks exact capability attestation"
        if Capability.EXTERNAL_MUTATION.value in set(attested):
            return "program attempts cannot attest coordinator-owned external mutation"
        supplied_containment = raw_attempt.get("physical_boundary_containment")
        expected_containment = None
        if {
            Capability.FILE_WRITE.value,
            Capability.SHELL.value,
        } & set(attested):
            if not isinstance(supplied_containment, dict):
                return "program attempt physical boundary containment is missing"
            issuer = supplied_containment.get("issuer")
            pre_checkpoint = raw_attempt.get("pre_workspace_checkpoint")
            if (
                not isinstance(issuer, str)
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", issuer)
                or not isinstance(pre_checkpoint, dict)
            ):
                return "program attempt physical boundary attestation is malformed"
            expected_containment = _program_containment_record(
                unit_contract,
                provider=raw_attempt.get("provider"),
                route=raw_attempt.get("route"),
                dispatch_id=raw_attempt.get("dispatch_id"),
                unit_id=unit_id,
                workspace_target=workspace.get("target_path"),
                pre_workspace_checkpoint_digest=pre_checkpoint.get("content_digest"),
                issuer=issuer,
            )
        if supplied_containment != expected_containment:
            return "program attempt physical boundary containment is missing or changed"
        status = raw_attempt.get("status")
        if status not in PROGRAM_UNIT_STATUSES:
            return "program attempt status is malformed"
        try:
            pre = raw_attempt.get("pre_workspace_checkpoint")
            if not isinstance(pre, dict):
                raise WorktreeError("pre-checkpoint missing")
            WorkspaceCheckpoint.from_dict(pre)
            if pre != expected_pre_checkpoint:
                return (
                    "program attempt pre-checkpoint does not continue the exact "
                    "workspace chain"
                )
            post = raw_attempt.get("post_workspace_checkpoint")
            if status == "running":
                if (
                    post is not None
                    or raw_attempt.get("output_path") is not None
                    or raw_attempt.get("output_artifact_sha256") is not None
                    or raw_attempt.get("output_sha256") is not None
                    or raw_attempt.get("reconciliation") is not None
                ):
                    return "running program attempt contains terminal state"
            else:
                if not isinstance(post, dict):
                    raise WorktreeError("post-checkpoint missing")
                WorkspaceCheckpoint.from_dict(post)
                artifact_problem = _program_terminal_artifact_problem(
                    root, run, contract, raw_attempt
                )
                if artifact_problem:
                    return artifact_problem
        except (OSError, UnsafePathError, ValueError, WorktreeError) as exc:
            return f"program attempt workspace checkpoint is invalid: {exc}"
        if status == "succeeded":
            verification_documents = raw_attempt.get("evidence_verifications")
            if not isinstance(verification_documents, list) or any(
                not isinstance(item, dict) for item in verification_documents
            ):
                return "successful program attempt evidence verifications are malformed"
            expected_evidence_ids = set(unit_contract["evidence"])
            if {
                item.get("artifact_id") for item in verification_documents
            } != expected_evidence_ids:
                return (
                    "successful program attempt lacks exact content-addressed "
                    "evidence verification"
                )
            for verification in verification_documents:
                if (
                    safeguard_by_key.get((unit_id, verification.get("artifact_id")))
                    != verification
                ):
                    return (
                        "successful program attempt evidence differs from the "
                        "root-owned safeguard ledger"
                    )
                if verification.get("kind") != "evidence":
                    continue
                details = verification.get("details")
                if (
                    not isinstance(details, dict)
                    or details.get("unit_id") != unit_id
                    or details.get("dispatch_id") != raw_attempt.get("dispatch_id")
                    or details.get("workspace_content_digest")
                    != cast(dict[str, Any], post).get("content_digest")
                    or details.get("source") != "structured-terminal-output"
                    or details.get("source_output_sha256")
                    != raw_attempt.get("output_sha256")
                ):
                    return (
                        "program evidence verification is not bound to its exact "
                        "attempt/workspace checkpoint"
                    )
                expected_prefix = (
                    _state_layout(root).artifacts
                    + "/program/runs/"
                    + str(binding.get("run_id"))
                    + "/"
                    + str(binding.get("manifest_digest"))
                    + "/"
                    + str(unit_id)
                    + "/"
                    + str(raw_attempt.get("attempt"))
                    + "/"
                )
                artifact_path = verification.get("artifact_path")
                artifact_sha = verification.get("artifact_sha256")
                if (
                    details.get("ledger_attempt") != raw_attempt.get("attempt")
                    or not isinstance(artifact_path, str)
                    or not artifact_path.startswith(expected_prefix)
                    or not isinstance(artifact_sha, str)
                    or not artifact_path.endswith(f"-{artifact_sha}.json")
                ):
                    return (
                        "program evidence verification is not stored in its exact "
                        "content-addressed run/manifest/attempt namespace"
                    )
            succeeded.add(str(unit_id))
            expected_pre_checkpoint = cast(dict[str, Any], post)
        elif status in {"failed", "cancelled"}:
            # A failed worker may have crossed its boundary.  Retrying from its
            # dirty post-state would launder that violation into a no-op success.
            expected_pre_checkpoint = pre
    for unit_id, numbers in attempt_numbers.items():
        if numbers != list(range(1, len(numbers) + 1)):
            return f"program unit {unit_id!r} attempt numbers are not contiguous"
    if completed != [
        unit_id
        for unit_id in expected_projection["ordered_units"]
        if unit_id in succeeded
    ]:
        return "program completed units are not the deterministic succeeded-unit prefix"

    checkpoint_ids = [item.get("gate_id") for item in checkpoints]
    expected_gate_prefix = expected_projection["ordered_program_gates"][
        : len(checkpoint_ids)
    ]
    if checkpoint_ids != expected_gate_prefix:
        return "program gates were not checkpointed in deterministic order"
    resolved_pipeline = set(
        _resolved_gate_names(cast(dict[str, Any], run), list(run["ordered_gates"]))
    )
    for checkpoint in checkpoints:
        gate_contract = expected_projection["gates"][checkpoint["gate_id"]]
        if checkpoint.get("status") not in PROGRAM_GATE_STATUSES:
            return "program gate checkpoint status is malformed"
        if gate_contract["owner_unit_id"] not in succeeded:
            return "program gate was checkpointed before its owner unit succeeded"
        owner_attempts = [
            item
            for item in attempts
            if item.get("unit_id") == gate_contract["owner_unit_id"]
            and item.get("status") == "succeeded"
        ]
        if len(owner_attempts) != 1:
            return "program gate owner attempt is ambiguous"
        owner_verifications = owner_attempts[0].get("evidence_verifications")
        checkpoint_verifications = checkpoint.get("verification_records")
        if not isinstance(owner_verifications, list) or not isinstance(
            checkpoint_verifications, list
        ):
            return "program gate evidence verification ledger is malformed"
        owner_by_id = {
            item.get("artifact_id"): item
            for item in owner_verifications
            if isinstance(item, dict)
        }
        if {
            item.get("artifact_id")
            for item in checkpoint_verifications
            if isinstance(item, dict)
        } != set(gate_contract["evidence"]) or any(
            not isinstance(item, dict)
            or owner_by_id.get(item.get("artifact_id")) != item
            for item in checkpoint_verifications
        ):
            return "program gate evidence differs from its owner attempt"
        try:
            checkpoint_workspace = checkpoint.get("workspace_checkpoint")
            if not isinstance(checkpoint_workspace, dict):
                raise WorktreeError("checkpoint missing")
            WorkspaceCheckpoint.from_dict(checkpoint_workspace)
        except WorktreeError as exc:
            return f"program gate workspace checkpoint is invalid: {exc}"
        if checkpoint_workspace != owner_attempts[0].get("post_workspace_checkpoint"):
            return "program gate workspace differs from its owner attempt"
        if (
            gate_contract["kind"] == "pipeline"
            and checkpoint["gate_id"] not in resolved_pipeline
        ):
            return "program pipeline gate checkpoint has no pipeline resolution"

    first_work_wave = manifest.waves[0]
    audit_gate_ids = tuple(manifest.waves[1].gate_ids)
    audit_complete = set(audit_gate_ids).issubset(checkpoint_ids)
    if contract.get("audit_gate_completed") is not audit_complete:
        return "program audit-gate completion marker is inconsistent"
    execution_started = any(
        expected_projection["waves"][
            expected_projection["units"][item["unit_id"]]["wave_id"]
        ]["kind"]
        == "execution"
        for item in attempts
    )
    if execution_started and not audit_complete:
        return "program execution began before the Wave 0 audit gate completed"
    del first_work_wave

    for wave_id, state in wave_states.items():
        if (
            not isinstance(state, dict)
            or state.get("status") not in PROGRAM_WAVE_STATUSES
        ):
            return f"program wave state {wave_id!r} is malformed"
        wave_attempts = [
            item
            for item in attempts
            if expected_projection["units"][item["unit_id"]]["wave_id"] == wave_id
        ]
        if state.get("spawns_used") != len(wave_attempts):
            return f"program wave {wave_id!r} spawn counter is inconsistent"
        if state.get("turns_used") != len(wave_attempts):
            return f"program wave {wave_id!r} turn counter is inconsistent"
        token_total = sum(
            item.get("token_upper_bound", 0)
            for item in wave_attempts
            if isinstance(item.get("token_upper_bound", 0), int)
        )
        if state.get("token_upper_bound_used") != token_total:
            return f"program wave {wave_id!r} token counter is inconsistent"
        budget = expected_projection["waves"][wave_id]["budget"]
        if len(wave_attempts) > budget["hard_spawn_cap"]:
            return f"program wave {wave_id!r} exceeded its hard spawn cap"
        for unit_id in expected_projection["waves"][wave_id]["unit_ids"]:
            if len(attempt_numbers[unit_id]) > budget["max_attempts_per_unit"]:
                return f"program unit {unit_id!r} exceeded its attempt budget"
            if len(attempt_numbers[unit_id]) > budget["max_turns_per_worker"]:
                return f"program unit {unit_id!r} exceeded its turn budget"

    if contract.get("status") == "completed":
        if completed != expected_projection["ordered_units"]:
            return "completed program execution has unresolved units"
        if checkpoint_ids != expected_projection["ordered_program_gates"]:
            return "completed program execution has unresolved program gates"
        if not isinstance(contract.get("completed_at"), str):
            return "completed program execution has no completion timestamp"
        completion_checkpoint = contract.get("completion_workspace_checkpoint")
        try:
            if not isinstance(completion_checkpoint, dict):
                raise WorktreeError("completion checkpoint is missing")
            frozen_completion = WorkspaceCheckpoint.from_dict(completion_checkpoint)
            current_completion = manager.checkpoint(record.run_id, record.worker_id)
        except (OSError, ValueError, WorktreeError) as exc:
            return f"program completion workspace checkpoint is invalid: {exc}"
        if current_completion != frozen_completion:
            return "program workspace changed after terminal completion"
        if contract.get("completion_workflow_definition_digest") != binding.get(
            "workflow_definition_digest"
        ):
            return "program completion belongs to a different workflow definition"
        if contract.get("completion_state_digest") != _program_completion_digest(
            contract
        ):
            return "program completion state digest is invalid"
    elif (
        contract.get("status") == "active"
        and "completion_workspace_checkpoint" in contract
    ):
        return "active program execution retains a completion checkpoint"
    return None


def _managed_workspace_checkpoint(
    root: Path, run: Mapping[str, Any]
) -> tuple[WorkspaceCheckpoint | None, str | None]:
    """Recompute the exact workspace identity frozen by managed execution."""

    contract = run.get("managed_execution")
    if contract is None:
        program = run.get("program_execution")
        if program is None:
            return None, None
        if not isinstance(program, dict):
            return None, "program execution contract is malformed"
        problem = _program_execution_problem(root, run)
        if problem:
            return None, problem
        return _program_current_workspace_checkpoint(root, program)
    problem = _managed_execution_problem(root, run)
    if problem:
        return None, problem
    assert isinstance(contract, dict)  # narrowed by the semantic check
    workspace = cast(dict[str, Any], contract["workspace"])
    run_id = run.get("run_id")
    if not isinstance(run_id, str) or not _STAGE_ID_RE.fullmatch(run_id):
        return None, "managed workflow run id is malformed"
    try:
        manager = WorktreeManager(root)
        record = manager.verify(run_id, str(workspace["worker_id"]))
        if record.status is WorktreeStatus.REMOVED:
            return None, "managed workflow workspace was removed"
        if record.target_path != workspace["target_path"]:
            return None, "managed workflow workspace path differs from its binding"
        if record.base_commit != workspace["base_commit"]:
            return (
                None,
                "managed workflow workspace base commit differs from its binding",
            )
        return manager.checkpoint(run_id, record.worker_id), None
    except (OSError, ValueError, WorktreeError) as exc:
        return None, f"cannot verify managed workspace checkpoint: {exc}"


def _managed_owner_stage_record(
    run: Mapping[str, Any], gate: str, *, allow_skipped: bool = False
) -> tuple[dict[str, Any] | None, str | None]:
    contract = run.get("managed_execution")
    if contract is None:
        program = run.get("program_execution")
        if program is None:
            return None, None
        if not isinstance(program, dict):
            return None, "program execution contract is malformed"
        gates = program.get("gates")
        if not isinstance(gates, dict) or not isinstance(gates.get(gate), dict):
            return None, f"program pipeline gate {gate!r} has no owning unit"
        gate_contract = gates[gate]
        if gate_contract.get("kind") != "pipeline":
            return None, f"program gate {gate!r} is not pipeline-owned"
        owner = gate_contract.get("owner_unit_id")
        attempts = program.get("unit_attempts")
        matches = (
            []
            if not isinstance(attempts, list)
            else [
                item
                for item in attempts
                if isinstance(item, dict)
                and item.get("unit_id") == owner
                and item.get("status") == "succeeded"
            ]
        )
        if len(matches) != 1:
            return None, (
                f"program pipeline gate {gate!r} requires successful owner unit "
                f"{owner!r}"
            )
        attempt = dict(matches[0])
        attempt["stage"] = owner
        attempt["workspace_checkpoint"] = attempt.get("post_workspace_checkpoint")
        return attempt, None
    if not isinstance(contract, dict):
        return None, "managed execution contract is malformed"
    owners = contract.get("gate_owner_stages")
    if not isinstance(owners, dict) or not isinstance(owners.get(gate), str):
        return None, f"managed gate {gate!r} has no owning stage"
    owner = str(owners[gate])
    history = run.get("stage_history", [])
    matches = (
        []
        if not isinstance(history, list)
        else [
            record
            for record in history
            if isinstance(record, dict)
            and record.get("stage") == owner
            and record.get("status") == "succeeded"
        ]
    )
    owner_record: dict[str, Any] | None = matches[0] if len(matches) == 1 else None
    if owner_record is None and allow_skipped:
        raw_skips = run.get("skipped_stage_history", [])
        skipped = (
            []
            if not isinstance(raw_skips, list)
            else [
                record
                for record in raw_skips
                if isinstance(record, dict) and record.get("stage") == owner
            ]
        )
        if len(skipped) == 1:
            skip_problem = _managed_skip_attestation_problem(run, skipped[0])
            if skip_problem:
                return None, skip_problem
            owner_record = skipped[0]
    if owner_record is None:
        qualifier = (
            "successful or canonically skipped" if allow_skipped else "successful"
        )
        return None, f"managed gate {gate!r} requires {qualifier} owner stage {owner!r}"
    checkpoint = owner_record.get("workspace_checkpoint")
    try:
        if not isinstance(checkpoint, dict):
            raise WorktreeError("checkpoint is missing")
        WorkspaceCheckpoint.from_dict(checkpoint)
    except WorktreeError as exc:
        return (
            None,
            f"managed gate {gate!r} owner workspace checkpoint is invalid: {exc}",
        )
    return owner_record, None


def _managed_gate_owner_problem(run: Mapping[str, Any], gate: str) -> str | None:
    _record, problem = _managed_owner_stage_record(run, gate)
    return problem


def _managed_gate_transition_checkpoint(
    root: Path,
    run: Mapping[str, Any],
    gate: str,
    *,
    allow_skipped_owner: bool = False,
) -> tuple[WorkspaceCheckpoint | None, str | None]:
    owner, problem = _managed_owner_stage_record(
        run, gate, allow_skipped=allow_skipped_owner
    )
    if problem or owner is None:
        return None, problem
    current, problem = _managed_workspace_checkpoint(root, run)
    if problem or current is None:
        return None, problem or "managed workspace checkpoint is unavailable"
    recorded = owner.get("workspace_checkpoint")
    if recorded != current.to_dict():
        return (
            None,
            f"managed workspace changed after owner stage {owner.get('stage')!r}; "
            f"gate {gate!r} requires a fresh owning-stage review",
        )
    return current, None


def _active_v2_run(
    target: str | Path,
    snap: dict[str, Any] | None,
    *,
    allow_pending_human_stop: bool = False,
) -> tuple[dict[str, Any] | None, dict[str, str] | None, str | None]:
    """Validate the immutable identity of a run before a mutation."""
    if snap is None:
        return (
            None,
            None,
            "no explicit pipeline run exists — start or adopt first with "
            "`claude-kit pipeline start` / `claude-kit pipeline adopt`",
        )
    version, version_error = _snapshot_version(snap)
    if version_error:
        return None, None, version_error
    if version != PIPELINE_SCHEMA_VERSION:
        return (
            None,
            None,
            "legacy pipeline snapshot schema v1 is readable but cannot be mutated; explicitly "
            "adopt the run into schema v2 with `claude-kit pipeline adopt`",
        )
    status_value = snap.get("status")
    if status_value != "active":
        return None, None, f"this run is {status_value!r} and is terminal"
    if not allow_pending_human_stop:
        pending = [
            item
            for item in snap.get("human_stops", [])
            if isinstance(item, dict) and item.get("status") == "pending"
        ]
        if pending:
            stop = pending[0]
            return (
                None,
                None,
                "pipeline is paused for human input "
                f"({stop.get('stop_id')}: {stop.get('reason')}); resolve the pause before "
                "recording evidence or advancing a gate",
            )

    try:
        root = ProjectFS(Path(target).expanduser()).root
    except (UnsafePathError, OSError, ValueError) as exc:
        return None, None, f"unsafe pipeline project root: {exc}"
    if snap.get("repository_root") != str(root):
        return (
            None,
            None,
            f"run repository root is {snap.get('repository_root')!r}, not {str(root)!r}",
        )
    identity, identity_error = _git_identity(root)
    if identity_error or identity is None:
        return None, None, identity_error or "cannot establish repository identity"
    if identity["branch"] != snap.get("branch"):
        return (
            None,
            None,
            f"run belongs to branch {snap.get('branch')!r}, current branch is "
            f"{identity['branch']!r}",
        )

    gates = snap.get("ordered_gates")
    if not isinstance(gates, list) or not gates:
        return None, None, "schema-v2 run has no ordered_gates"
    _install, install_error = _read_install_snapshot(target)
    if install_error:
        return None, None, install_error
    mode = snap.get("mode")
    if not isinstance(mode, str):
        return None, None, "schema-v2 run has no execution mode"
    installed = installed_gates_for_mode(target, mode)
    if installed and gates != installed:
        return None, None, "installed ordered gate list changed after this run started"
    current_digest = installed_gate_definition_digest_for_mode(target, mode)
    if not current_digest or snap.get("gate_definition_digest") != current_digest:
        return None, None, "gate definition digest changed after this run started"
    current_selection_digest = installed_selection_digest(target)
    frozen_selection_digest = snap.get("selection_digest")
    if frozen_selection_digest is not None and (
        not current_selection_digest
        or frozen_selection_digest != current_selection_digest
    ):
        return None, None, "installed selection changed after this run started"
    managed_problem = _managed_execution_problem(target, snap)
    if managed_problem:
        return None, None, managed_problem
    program_problem = _program_execution_problem(target, snap)
    if program_problem:
        return None, None, program_problem
    return snap, identity, None


def _create_run(
    target: str | Path,
    *,
    task: str,
    mode: str,
    start_type: str,
    gate: str | None = None,
    reason: str | None = None,
    adopted_by: str | None = None,
    coordinator_token: str | None = None,
) -> tuple[bool, list[str]]:
    """Shared locked implementation for :func:`start` and :func:`adopt`."""
    if not (task and task.strip()):
        return False, ["FAIL  pipeline run task must be non-empty"]
    if mode not in MODES:
        return False, [f"FAIL  mode {mode!r} is not one of {sorted(MODES)}"]
    if start_type == "adopted":
        if not (reason and reason.strip()):
            return False, ["FAIL  adopt requires a non-empty reason"]
        if not (adopted_by and adopted_by.strip()):
            return False, ["FAIL  adopt requires the adopting person or role identity"]

    msgs: list[str] = []
    installed_gate_order, preamble_ok = _gate_set_preamble(
        target, strict=True, msgs=msgs
    )
    if not preamble_ok:
        return False, msgs
    if not installed_gate_order:
        return False, ["FAIL  installed profile has no ordered gates"]
    gates = installed_gates_for_mode(target, mode)
    if not gates:
        return False, [f"FAIL  workflow mode {mode!r} has no valid installed gate set"]
    if start_type == "adopted" and gate not in gates:
        return False, [f"FAIL  adoption gate {gate!r} is not in {gates}"]

    definitions = installed_gate_definitions(target)
    if set(definitions) != set(installed_gate_order):
        return False, ["FAIL  installed gate definitions are missing or malformed"]
    digest = installed_gate_definition_digest_for_mode(target, mode)
    if not digest:
        return False, ["FAIL  could not derive the installed gate definition digest"]
    try:
        fs = ProjectFS(Path(target).expanduser())
        root = fs.root
    except (UnsafePathError, OSError, ValueError) as exc:
        return False, [f"FAIL  unsafe pipeline project root: {exc}"]
    identity, identity_error = _git_identity(root)
    if identity_error or identity is None:
        return False, [
            f"FAIL  {identity_error or 'cannot establish repository identity'}"
        ]
    selection = _selection(target)
    profile = selection.get("profile")
    scope = selection.get("scope")
    if profile not in PROFILES or scope not in SCOPES:
        return False, ["FAIL  install snapshot has no valid profile/scope selection"]
    selection_digest = installed_selection_digest(target)
    if not selection_digest:
        return False, ["FAIL  could not derive the installed selection digest"]

    starting_gate = gate if start_type == "adopted" and gate is not None else gates[0]
    historical = gates[: gates.index(starting_gate)] if start_type == "adopted" else []
    snap: dict[str, Any] = {
        "schema_version": PIPELINE_SCHEMA_VERSION,
        "run_id": str(uuid.uuid4()),
        "repository_root": identity["repository_root"],
        "branch": identity["branch"],
        "starting_commit": identity["commit"],
        "current_commit": identity["commit"],
        "kit_version": __version__,
        "claude_code_version": _claude_code_version(),
        "profile": profile,
        "scope": scope,
        "mode": mode,
        "ordered_gates": gates,
        "gate_definition_digest": digest,
        "selection_digest": selection_digest,
        "start_type": start_type,
        "adoption": (
            {
                "starting_gate": starting_gate,
                "historical_gates": historical,
                "reason": reason.strip() if reason else "",
                "adopted_by": adopted_by.strip() if adopted_by else "",
            }
            if start_type == "adopted"
            else None
        ),
        "created_at": _utc_now(),
        "status": "active",
        "task": task.strip(),
        "stage": starting_gate,
        "next": f"resolve gate {starting_gate}",
        "lanes": {},
        "open_findings": {
            "critical": 0,
            "high": 0,
            "medium": 0,
            "low": 0,
            "cosmetic": 0,
        },
        "findings_evidence": None,
        "gate_evidence": {},
        "accepted_risks": [],
        "human_stops": [],
        "stage_history": [],
        "skipped_stage_history": [],
        "gate_history": [],
    }

    try:
        path = fs.path(_snapshot_rel(target))
    except (UnsafePathError, OSError, ValueError) as exc:
        return False, [f"FAIL  unsafe pipeline state path: {exc}"]
    try:
        with _pipeline_write_lock(fs, path, msgs=msgs):
            # The install/upgrade transaction lease is acquired only here. Re-read every seed
            # value under that lease so a policy transaction that committed between the optimistic
            # preflight above and lock acquisition cannot produce an immediately stale run.
            locked_install, locked_install_error = _read_install_snapshot(target)
            if locked_install_error:
                return False, [f"FAIL  {locked_install_error}"]
            locked_installed_gates = (
                list(locked_install.get("gates", []))
                if isinstance(locked_install, dict)
                and isinstance(locked_install.get("gates"), list)
                else []
            )
            if not locked_installed_gates:
                return False, ["FAIL  installed profile has no ordered gates"]
            locked_gates = installed_gates_for_mode(target, mode)
            if not locked_gates:
                return False, [
                    f"FAIL  workflow mode {mode!r} has no valid installed gate set"
                ]
            if start_type == "adopted" and gate not in locked_gates:
                return False, [f"FAIL  adoption gate {gate!r} is not in {locked_gates}"]
            locked_definitions = installed_gate_definitions(target)
            if set(locked_definitions) != set(locked_installed_gates):
                return False, [
                    "FAIL  installed gate definitions are missing or malformed"
                ]
            if not isinstance((locked_install or {}).get("gate_definitions"), dict):
                msgs.append(
                    "WARN  legacy install snapshot has no gate metadata; all gates are treated "
                    "as required until the install is upgraded"
                )
            locked_digest = installed_gate_definition_digest_for_mode(target, mode)
            if not locked_digest:
                return False, [
                    "FAIL  could not derive the installed gate definition digest"
                ]
            locked_selection = _selection(target)
            locked_profile = locked_selection.get("profile")
            locked_scope = locked_selection.get("scope")
            if locked_profile not in PROFILES or locked_scope not in SCOPES:
                return False, [
                    "FAIL  install snapshot has no valid profile/scope selection"
                ]
            locked_selection_digest = installed_selection_digest(target)
            if not locked_selection_digest:
                return False, ["FAIL  could not derive the installed selection digest"]
            locked_identity, locked_identity_error = _git_identity(root)
            if locked_identity_error or locked_identity is None:
                return False, [
                    f"FAIL  {locked_identity_error or 'cannot establish repository identity'}"
                ]
            starting_gate = (
                gate
                if start_type == "adopted" and gate is not None
                else locked_gates[0]
            )
            historical = (
                locked_gates[: locked_gates.index(starting_gate)]
                if start_type == "adopted"
                else []
            )
            snap.update(
                {
                    "repository_root": locked_identity["repository_root"],
                    "branch": locked_identity["branch"],
                    "starting_commit": locked_identity["commit"],
                    "current_commit": locked_identity["commit"],
                    "profile": locked_profile,
                    "scope": locked_scope,
                    "ordered_gates": locked_gates,
                    "gate_definition_digest": locked_digest,
                    "selection_digest": locked_selection_digest,
                    "adoption": (
                        {
                            "starting_gate": starting_gate,
                            "historical_gates": historical,
                            "reason": reason.strip() if reason else "",
                            "adopted_by": adopted_by.strip() if adopted_by else "",
                        }
                        if start_type == "adopted"
                        else None
                    ),
                    "stage": starting_gate,
                    "next": f"resolve gate {starting_gate}",
                }
            )
            existing, err = _load_snapshot(target)
            if err:
                return False, [f"FAIL  {err}"]
            if existing is not None:
                existing_version, existing_error = _snapshot_version(existing)
                existing_status = existing.get("status")
                allowance = existing.get("headless_transition_allowance")
                if isinstance(allowance, dict) and not _headless_coordinator_matches(
                    allowance, coordinator_token or ""
                ):
                    return False, [
                        "FAIL  a headless invocation owns the prior run; only its "
                        "coordinator authority may archive it and start/adopt another run"
                    ]
                if (
                    existing_error is None
                    and existing_version == PIPELINE_SCHEMA_VERSION
                    and existing_status in {"completed", "aborted"}
                ):
                    terminal_ok, terminal_messages = validate(
                        target, strict=True, _historical_terminal=True
                    )
                    if not terminal_ok:
                        return False, [
                            "FAIL  existing terminal pipeline snapshot is invalid and cannot "
                            "be archived safely",
                            *terminal_messages,
                        ]
                    snap["run_archives"] = _archive_terminal_snapshot(existing)
                    msgs.append(
                        f"OK    archived terminal pipeline run {existing.get('run_id')} "
                        f"({existing_status}) before starting the new run"
                    )
                elif (
                    start_type != "adopted"
                    or existing_error is not None
                    or existing_version != 1
                ):
                    return False, [
                        "FAIL  an active pipeline snapshot already exists; resume or abort it. "
                        "Use adopt only to migrate a readable legacy-v1 snapshot"
                    ]
                else:
                    legacy_ok, legacy_messages = validate(target)
                    if not legacy_ok:
                        return False, [
                            "FAIL  legacy snapshot is invalid and cannot be adopted safely",
                            *legacy_messages,
                        ]
                    snap["legacy_migration"] = {
                        "from_schema": 1,
                        "migrated_at": _utc_now(),
                        "legacy_snapshot_sha256": _document_sha256(existing),
                        "legacy_snapshot": existing,
                    }
                    msgs.append(
                        "WARN  migrated legacy schema v1 snapshot by explicit adoption; the "
                        "complete legacy document is preserved under legacy_migration"
                    )
            _write_snapshot_locked(target, snap)
    except TimeoutError as exc:
        return False, [f"FAIL  {exc}"]
    except (UnsafePathError, OSError, ValueError) as exc:
        return False, [f"FAIL  unsafe pipeline state mutation refused: {exc}"]
    label = "ADOPTED" if start_type == "adopted" else "started"
    msgs.append(
        f"OK    pipeline run {label} at gate {starting_gate!r} ({snap['run_id']})"
    )
    return True, msgs


def start(
    target: str | Path,
    *,
    task: str,
    mode: str = "B",
    coordinator_token: str | None = None,
) -> tuple[bool, list[str]]:
    """Explicitly start a fresh schema-v2 run at the first installed gate."""
    return _create_run(
        target,
        task=task,
        mode=mode,
        start_type="fresh",
        coordinator_token=coordinator_token,
    )


def adopt(
    target: str | Path,
    *,
    task: str,
    gate: str,
    reason: str,
    adopted_by: str,
    mode: str = "B",
    coordinator_token: str | None = None,
) -> tuple[bool, list[str]]:
    """Explicitly adopt work already in flight, recording all historical preceding gates."""
    return _create_run(
        target,
        task=task,
        mode=mode,
        start_type="adopted",
        gate=gate,
        reason=reason,
        adopted_by=adopted_by,
        coordinator_token=coordinator_token,
    )


def resume(target: str | Path) -> tuple[bool, list[str]]:
    """Verify that an active run still belongs to this repository, branch, and gate policy."""
    snap, err = _load_snapshot(target)
    if err:
        return False, [f"FAIL  {err}"]
    from claude_kit.maker_checker import (
        is_maker_checker_snapshot,
        validate_maker_checker_snapshot,
    )

    if is_maker_checker_snapshot(snap):
        if not isinstance(snap, dict) or snap.get("status") != "active":
            return False, [
                f"FAIL  maker-checker run {(snap or {}).get('run_id')!r} is terminal"
            ]
        ok, messages = validate_maker_checker_snapshot(
            target, snap, verify_current_policy=True
        )
        if not ok:
            return False, messages
        return True, [
            f"OK    maker-checker run {snap.get('run_id')} can resume at "
            f"{snap.get('stage')}; use `ckit maker-checker run --resume "
            f"{snap.get('run_id')}`"
        ]
    run, identity, problem = _active_v2_run(target, snap)
    if problem or run is None or identity is None:
        return False, [f"FAIL  {problem or 'invalid run'}"]
    ok, msgs = validate(target, strict=True)
    if not ok:
        return False, msgs
    try:
        from claude_kit.worktrees import WorktreeManager

        worktrees = WorktreeManager(target).resume_run(str(run.get("run_id")))
    except (OSError, ValueError, RuntimeError) as exc:
        return False, [f"FAIL  run-owned worktree verification failed: {exc}"]
    kind = "ADOPTED" if run.get("start_type") == "adopted" else "fresh"
    messages = [
        f"OK    resumed {kind} run {run.get('run_id')} at {run.get('stage')} "
        f"(commit {identity['commit']})"
    ]
    if worktrees:
        messages.append(f"OK    verified {len(worktrees)} run-owned worktree(s)")
    return True, messages


def begin_headless_iteration(
    target: str | Path,
    *,
    prior_coordinator_token: str | None = None,
) -> tuple[str | None, str | None, list[str]]:
    """Fail closed until the host process tree can be portably contained.

    POSIX process groups do not contain a child that creates a new session, and
    caller-supplied cleanup claims cannot prove that every descendant is dead.
    Minting a gate-transition token would therefore reopen the lifecycle ledger
    to a detached child after coordinator exit. Existing allowance documents
    remain recoverable through :func:`end_headless_iteration`, but no new one is
    issued by this Preview runtime.
    """

    del target, prior_coordinator_token
    return (
        None,
        None,
        [
            "FAIL  headless automated gate transitions are unsupported: the active "
            "host cannot attest portable descendant-process containment; use an "
            "interactive/manual gate transition"
        ],
    )


def end_headless_iteration(
    target: str | Path,
    coordinator_token: str,
    *,
    process_tree_terminalized: bool = False,
) -> tuple[bool, list[str]]:
    """Close an invocation, removing it only after its owned process tree is dead."""
    if not isinstance(coordinator_token, str) or not coordinator_token:
        return False, [
            "FAIL  headless iteration cleanup requires coordinator authority"
        ]
    msgs: list[str] = []
    try:
        fs = ProjectFS(Path(target).expanduser())
        path = fs.path(_snapshot_rel(target))
    except (UnsafePathError, OSError, ValueError) as exc:
        return False, [f"FAIL  unsafe pipeline state path: {exc}"]
    try:
        with _pipeline_write_lock(fs, path, msgs=msgs):
            snap, err = _load_snapshot(target)
            if err:
                return False, [f"FAIL  {err}"]
            if snap is None:
                return True, ["OK    no pipeline snapshot — allowance already absent"]
            version, version_error = _snapshot_version(snap)
            if version_error or version != PIPELINE_SCHEMA_VERSION:
                return False, [
                    f"FAIL  {version_error or 'headless iteration requires schema v2'}"
                ]
            raw = snap.get("headless_transition_allowance")
            if raw is None:
                return True, ["OK    headless iteration allowance already absent"]
            shape_problem = _headless_allowance_shape_problem(snap)
            if shape_problem or not isinstance(raw, dict):
                return False, [f"FAIL  {shape_problem or 'malformed allowance'}"]
            if not _headless_coordinator_matches(raw, coordinator_token):
                return False, [
                    "FAIL  headless iteration coordinator authority does not match the "
                    "active allowance"
                ]
            consumed = bool(raw["consumed"])
            if "coordinator_closed_at" in raw:
                if not process_tree_terminalized:
                    return True, [
                        "OK    headless invocation was already durably closed"
                    ]
                snap.pop("headless_transition_allowance", None)
                _write_snapshot_locked(target, snap)
                return True, [
                    "OK    closed headless invocation removed after process-tree "
                    "terminalization"
                ]
            if process_tree_terminalized:
                snap.pop("headless_transition_allowance", None)
                _write_snapshot_locked(target, snap)
                return True, [
                    "OK    headless invocation removed after process-tree terminalization"
                ]
            raw["coordinator_closed_at"] = _utc_now()
            _write_snapshot_locked(target, snap)
        return True, [
            "OK    headless invocation durably closed "
            f"({'one transition consumed' if consumed else 'without a transition'})"
        ]
    except TimeoutError as exc:
        return False, [f"FAIL  {exc}"]
    except (UnsafePathError, OSError, ValueError) as exc:
        return False, [f"FAIL  unsafe pipeline state mutation refused: {exc}"]


def pause_for_human(
    target: str | Path,
    *,
    reason: str,
    message: str,
    requested_action: str,
) -> tuple[bool, list[str]]:
    """Persist a provider-neutral mandatory human stop on the active run."""

    if reason not in HUMAN_STOP_REASONS:
        return False, [
            "FAIL  human stop reason must be one of: "
            + ", ".join(sorted(HUMAN_STOP_REASONS))
        ]
    if not isinstance(message, str) or not message.strip():
        return False, ["FAIL  human stop message must be non-empty"]
    if not isinstance(requested_action, str) or not requested_action.strip():
        return False, ["FAIL  human stop requested action must be non-empty"]
    msgs: list[str] = []
    try:
        fs = ProjectFS(Path(target).expanduser())
        path = fs.path(_snapshot_rel(target))
    except (UnsafePathError, OSError, ValueError) as exc:
        return False, [f"FAIL  unsafe pipeline state path: {exc}"]
    try:
        with _pipeline_write_lock(fs, path, msgs=msgs):
            snap, err = _load_snapshot(target)
            if err:
                return False, [f"FAIL  {err}"]
            run, identity, problem = _active_v2_run(target, snap)
            if problem or run is None or identity is None:
                return False, [f"FAIL  {problem or 'invalid run'}"]
            stop_id = str(uuid.uuid4())
            current_next = str(run.get("next", ""))
            stops = run.setdefault("human_stops", [])
            if not isinstance(stops, list):
                return False, ["FAIL  human_stops ledger is malformed"]
            stops.append(
                {
                    "stop_id": stop_id,
                    "reason": reason,
                    "message": message.strip(),
                    "requested_action": requested_action.strip(),
                    "status": "pending",
                    "requested_at": _utc_now(),
                    "repository_commit": identity["commit"],
                    "resume_next": current_next,
                }
            )
            run["current_commit"] = identity["commit"]
            run["next"] = f"await human resolution for {stop_id} ({reason})"
            _write_snapshot_locked(target, run)
        msgs.append(f"OK    pipeline paused for human input ({stop_id}: {reason})")
        return True, msgs
    except TimeoutError as exc:
        return False, [f"FAIL  {exc}"]
    except (UnsafePathError, OSError, ValueError) as exc:
        return False, [f"FAIL  unsafe pipeline state mutation refused: {exc}"]


def resolve_human_stop(
    target: str | Path,
    stop_id: str,
    *,
    decision: str,
    resolved_by: str,
    note: str,
    evidence: str | Path | None = None,
    coordinator_token: str | None = None,
) -> tuple[bool, list[str]]:
    """Resolve one pending stop with an auditable human decision and contained evidence."""

    if decision not in {"approved", "rejected"}:
        return False, ["FAIL  human stop decision must be approved or rejected"]
    if not stop_id.strip() or not resolved_by.strip() or not note.strip():
        return False, ["FAIL  stop id, resolver, and note must be non-empty"]
    if decision == "approved" and evidence is None:
        return False, [
            "FAIL  an approved human stop requires project-contained evidence"
        ]
    msgs: list[str] = []
    try:
        fs = ProjectFS(Path(target).expanduser())
        root = fs.root
        path = fs.path(_snapshot_rel(target))
    except (UnsafePathError, OSError, ValueError) as exc:
        return False, [f"FAIL  unsafe pipeline state path: {exc}"]

    stored_evidence: str | None = None
    evidence_sha: str | None = None
    if evidence is not None:
        try:
            evidence_path, stored, warnings = _stored_evidence(root, evidence)
        except FileNotFoundError as exc:
            return False, [f"FAIL  {exc}"]
        if warnings or Path(stored).is_absolute():
            return False, ["FAIL  human-stop evidence must be contained in the project"]
        stored_evidence = stored
        evidence_sha = _sha256(evidence_path)
    try:
        with _pipeline_write_lock(fs, path, msgs=msgs):
            snap, err = _load_snapshot(target)
            if err:
                return False, [f"FAIL  {err}"]
            run, identity, problem = _active_v2_run(
                target, snap, allow_pending_human_stop=True
            )
            if problem or run is None or identity is None:
                return False, [f"FAIL  {problem or 'invalid run'}"]
            allowance = run.get("headless_transition_allowance")
            if isinstance(allowance, dict) and not _headless_coordinator_matches(
                allowance, coordinator_token or ""
            ):
                return False, [
                    "FAIL  an active headless coordinator owns this iteration; its host "
                    "cannot resolve human stops"
                ]
            stops = run.get("human_stops")
            if not isinstance(stops, list):
                return False, ["FAIL  human_stops ledger is malformed"]
            matches = [
                item
                for item in stops
                if isinstance(item, dict) and item.get("stop_id") == stop_id
            ]
            if len(matches) != 1:
                return False, [f"FAIL  pending human stop not found: {stop_id}"]
            record = matches[0]
            if record.get("status") != "pending":
                return False, [
                    f"FAIL  human stop {stop_id} is already {record.get('status')!r}"
                ]
            if decision == "approved" and (
                isinstance(run.get("managed_execution"), dict)
                or isinstance(run.get("program_execution"), dict)
            ):
                return False, [
                    "FAIL  managed/program approvals are unsupported until an "
                    "operator authorization is scoped to one exact originating stage, "
                    "attempt, provider, workspace checkpoint, workflow, and action digest, "
                    "then delivered to and consumed by only that one retry; the verifier "
                    "must be outside the managed worker trust boundary"
                ]
            record.update(
                {
                    "status": decision,
                    "resolved_by": resolved_by.strip(),
                    "resolution_note": note.strip(),
                    "resolved_at": _utc_now(),
                    "resolution_commit": identity["commit"],
                    "evidence_path": stored_evidence,
                    "evidence_sha256": evidence_sha,
                }
            )
            run["current_commit"] = identity["commit"]
            if decision == "approved":
                run["next"] = (
                    record.get("resume_next") or f"resolve gate {run.get('stage')}"
                )
            else:
                run["next"] = (
                    f"re-plan after rejected human stop {stop_id}; do not perform the rejected action"
                )
            _write_snapshot_locked(target, run)
        msgs.append(
            f"OK    human stop {stop_id} resolved as {decision} by {resolved_by.strip()}"
        )
        return True, msgs
    except TimeoutError as exc:
        return False, [f"FAIL  {exc}"]
    except (UnsafePathError, OSError, ValueError) as exc:
        return False, [f"FAIL  unsafe pipeline state mutation refused: {exc}"]


def _risk_fingerprint(
    *,
    finding_id: str,
    affected_gate: str,
    evidence_sha256: str,
    medium_finding_count: int,
    finding_set_digest: str,
    gate_definition_digest: str,
    repository_commit: str,
) -> str:
    """Bind an acceptance to the exact finding, gate, evidence, count, commit, and policy."""
    document = {
        "affected_gate": affected_gate,
        "evidence_sha256": evidence_sha256,
        "finding_id": finding_id,
        "finding_set_digest": finding_set_digest,
        "gate_definition_digest": gate_definition_digest,
        "medium_finding_count": medium_finding_count,
        "repository_commit": repository_commit,
    }
    return hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _accepted_risk_staleness(
    root: Path,
    run: Mapping[str, Any],
    risk: dict[str, Any],
    *,
    current_commit: str,
    current_medium_count: int,
    current_finding_set_digest: str,
    gate_definition_digest: str,
) -> list[str]:
    """Return every reason an existing acceptance needs explicit re-attestation."""
    reasons: list[str] = []
    if risk.get("repository_commit") != current_commit:
        reasons.append("repository commit changed")
    if risk.get("medium_finding_count") != current_medium_count:
        reasons.append("Medium finding count changed")
    if risk.get("finding_set_digest") != current_finding_set_digest:
        reasons.append("recorded finding set changed")
    if risk.get("gate_definition_digest") != gate_definition_digest:
        reasons.append("gate definition changed")
    evidence_sha = risk.get("evidence_sha256")
    evidence = risk.get("evidence_path")
    contract = run.get("managed_execution")
    if (
        isinstance(contract, dict)
        and contract.get("evidence_contract_version") == EVIDENCE_CONTRACT_VERSION
    ):
        evidence_problem = _managed_accepted_risk_evidence_problem(
            ProjectFS(root), run, risk
        )
        if evidence_problem:
            reasons.append(evidence_problem)
    elif not isinstance(evidence, str) or not evidence:
        reasons.append("evidence path is missing")
    else:
        evidence_path = Path(evidence).expanduser()
        if not evidence_path.is_absolute():
            evidence_path = root / evidence_path
        if not evidence_path.is_file():
            reasons.append("evidence file is missing")
        elif (
            not isinstance(evidence_sha, str) or _sha256(evidence_path) != evidence_sha
        ):
            reasons.append("evidence changed")
    raw_medium_count = risk.get("medium_finding_count")
    fingerprint_medium_count = (
        cast(int, raw_medium_count)
        if isinstance(raw_medium_count, int) and not isinstance(raw_medium_count, bool)
        else -1
    )
    expected = _risk_fingerprint(
        finding_id=str(risk.get("finding_id")),
        affected_gate=str(risk.get("affected_gate")),
        evidence_sha256=str(evidence_sha),
        medium_finding_count=fingerprint_medium_count,
        finding_set_digest=str(risk.get("finding_set_digest")),
        gate_definition_digest=str(risk.get("gate_definition_digest")),
        repository_commit=str(risk.get("repository_commit")),
    )
    if risk.get("finding_fingerprint") != expected or risk.get("risk_id") != expected:
        reasons.append("finding identity binding changed")
    return reasons


def _advance_run(snap: dict[str, Any], gates: list[str], gate: str) -> None:
    """Advance an active run after one gate is resolved."""
    snap["last_gate_resolved"] = gate
    idx = gates.index(gate)
    if idx + 1 < len(gates):
        next_gate = gates[idx + 1]
        snap["stage"] = next_gate
        snap["next"] = f"resolve gate {next_gate}"
    else:
        snap["stage"] = "ready-to-complete"
        snap["next"] = "complete the pipeline run"


def _resolved_gate_names(snap: dict[str, Any], gates: list[str]) -> set[str]:
    """Return gates resolved by the v2 ledger plus explicit adoption history."""
    resolved = {
        str(entry.get("gate"))
        for entry in _history(snap)
        if entry.get("status") in POSITION_STATUSES and entry.get("gate") in gates
    }
    adoption = snap.get("adoption")
    if isinstance(adoption, dict):
        historical = adoption.get("historical_gates")
        if isinstance(historical, list):
            resolved.update(str(gate) for gate in historical if gate in gates)
    return resolved


def _final_summary_projection(
    snap: dict[str, Any], *, repository_commit: str, completed_at: str
) -> dict[str, Any]:
    """Build the exact deterministic terminal evidence projection for a v2 run."""
    gates = list(snap.get("ordered_gates") or [])
    entries = {entry.get("gate"): entry for entry in _history(snap)}
    return {
        "schema_version": PIPELINE_SCHEMA_VERSION,
        "run_id": snap.get("run_id"),
        "status": "completed",
        "repository_commit": repository_commit,
        "completed_at": completed_at,
        "gate_definition_digest": snap.get("gate_definition_digest"),
        "gates": [
            {
                "gate": gate,
                "status": (
                    "historical-adoption"
                    if gate not in entries
                    else entries[gate].get("status")
                ),
                "evidence_sha256": (
                    entries.get(gate, {}).get("evidence_sha256")
                    or entries.get(gate, {}).get("condition_evidence_sha256")
                ),
            }
            for gate in gates
        ],
        "accepted_risks": list(snap.get("accepted_risks") or []),
    }


def snapshot_document(target: str | Path) -> tuple[dict[str, Any] | None, str | None]:
    """Return the raw persisted run document for structured CLI output (read-only)."""
    return _load_snapshot(target)


def _stage_capabilities(
    values: tuple[str, ...] | list[str], *, field_name: str
) -> tuple[str, ...]:
    """Validate and deterministically order semantic capability attestations."""
    if isinstance(values, (str, bytes)):
        raise ValueError(f"{field_name} must be a sequence")
    try:
        normalized = tuple(Capability(str(value)).value for value in values)
    except ValueError as exc:
        raise ValueError(f"{field_name} contains an unsupported capability") from exc
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{field_name} must not contain duplicates")
    return tuple(sorted(normalized))


def completed_stage_ids(target: str | Path) -> tuple[set[str], str | None]:
    """Return stages durably completed in the current shared schema-v2 run."""
    snap, error = _load_snapshot(target)
    if error:
        return set(), error
    if snap is None:
        return set(), "no explicit pipeline run exists"
    version, version_error = _snapshot_version(snap)
    if version_error:
        return set(), version_error
    if version != PIPELINE_SCHEMA_VERSION:
        return set(), "legacy pipeline snapshots have no authoritative stage history"
    raw = snap.get("stage_history", [])
    if not isinstance(raw, list) or any(not isinstance(item, dict) for item in raw):
        return set(), "stage_history must be an array of objects"
    return {
        str(item["stage"])
        for item in raw
        if item.get("status") == "succeeded" and isinstance(item.get("stage"), str)
    }, None


def workflow_condition_decisions(
    target: str | Path,
) -> tuple[dict[str, bool], str | None]:
    """Read the immutable stable-condition decisions for the current run."""
    snap, error = _load_snapshot(target)
    if error:
        return {}, error
    if snap is None:
        return {}, "no explicit pipeline run exists"
    version, version_error = _snapshot_version(snap)
    if version_error:
        return {}, version_error
    if version != PIPELINE_SCHEMA_VERSION:
        return {}, "legacy pipeline snapshots have no workflow condition decisions"
    raw = snap.get("condition_decisions", {})
    if not isinstance(raw, dict):
        return {}, "condition_decisions must be an object"
    decisions: dict[str, bool] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not _STAGE_ID_RE.fullmatch(key):
            return {}, "condition_decisions contains an invalid condition identifier"
        if not isinstance(value, bool):
            return {}, f"condition_decisions[{key!r}] must be boolean"
        decisions[key] = value
    return decisions, None


def bind_workflow_condition_decisions(
    target: str | Path,
    decisions: Mapping[str, bool],
) -> tuple[dict[str, bool] | None, str | None]:
    """Freeze stable workflow decisions, or verify an identical frozen set.

    This is the resume boundary for conditional stages. Once any host begins
    executing the structured workflow, another host cannot silently flip a
    false surface/mode decision and run a stage that the first host skipped.
    """
    if not isinstance(decisions, Mapping):
        return None, "workflow condition decisions must be a mapping"
    normalized: dict[str, bool] = {}
    for key, value in decisions.items():
        if not isinstance(key, str) or not _STAGE_ID_RE.fullmatch(key):
            return None, "workflow condition decisions contain an invalid identifier"
        if not isinstance(value, bool):
            return None, f"workflow condition decision {key!r} must be boolean"
        normalized[key] = value
    normalized = dict(sorted(normalized.items()))

    msgs: list[str] = []
    try:
        fs = ProjectFS(Path(target).expanduser())
        path = fs.path(_snapshot_rel(target))
    except (UnsafePathError, OSError, ValueError) as exc:
        return None, f"unsafe pipeline state path: {exc}"
    try:
        with _pipeline_write_lock(fs, path, msgs=msgs):
            snap, error = _load_snapshot(target)
            if error:
                return None, error
            run, identity, problem = _active_v2_run(target, snap)
            if problem or run is None or identity is None:
                return None, problem or "invalid run"
            raw = run.get("condition_decisions")
            if raw is None:
                run["condition_decisions"] = normalized
                _write_snapshot_locked(target, run)
                return dict(normalized), None
            if not isinstance(raw, dict):
                return None, "condition_decisions ledger is malformed"
            existing: dict[str, bool] = {}
            for key, value in raw.items():
                if (
                    not isinstance(key, str)
                    or not _STAGE_ID_RE.fullmatch(key)
                    or not isinstance(value, bool)
                ):
                    return None, "condition_decisions ledger is malformed"
                existing[key] = value
            if existing != normalized:
                return (
                    None,
                    "workflow condition decisions differ from the frozen run decisions",
                )
            return dict(existing), None
    except TimeoutError as exc:
        return None, str(exc)
    except (UnsafePathError, OSError, ValueError) as exc:
        return None, f"unsafe pipeline state mutation refused: {exc}"


def _not_applicable_condition(stage_condition: str) -> str | None:
    if stage_condition.endswith("-present"):
        return "no-" + stage_condition[: -len("-present")]
    return None


def _skip_attestation_payload(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "stage": record.get("stage"),
        "condition": record.get("condition"),
        "decision": record.get("decision"),
        "dependencies": record.get("dependencies"),
        "dependency_states": record.get("dependency_states"),
        "not_applicable_condition": record.get("not_applicable_condition"),
        "workflow_definition_digest": record.get("workflow_definition_digest"),
        "workspace_checkpoint": record.get("workspace_checkpoint"),
    }


def _skip_attestation_sha256(record: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        _skip_attestation_payload(record),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _managed_skip_attestation_problem(
    run: Mapping[str, Any], record: Mapping[str, Any]
) -> str | None:
    contract = run.get("managed_execution")
    if not isinstance(contract, dict):
        return "skip attestation exists without a managed execution contract"
    stage = record.get("stage")
    active = contract.get("active_stages")
    dependencies = contract.get("active_stage_dependencies")
    if (
        not isinstance(stage, str)
        or not isinstance(active, list)
        or stage not in active
        or not isinstance(dependencies, dict)
        or not isinstance(dependencies.get(stage), list)
    ):
        return "skip attestation names a stage outside the frozen managed graph"
    try:
        workflow = _current_workflow_definition()
        stage_definition = workflow.stage_by_id[stage]
    except (OSError, KeyError, ValueError) as exc:
        return f"cannot resolve skipped stage in the canonical workflow: {exc}"
    condition = record.get("condition")
    if condition != stage_definition.condition or condition == "always":
        return f"skip attestation for {stage!r} has a non-canonical condition"
    decisions = run.get("condition_decisions")
    if not isinstance(decisions, dict) or decisions.get(condition) is not False:
        return (
            f"skip attestation for {stage!r} is not backed by a frozen false condition"
        )
    expected_dependencies = list(dependencies[stage])
    if record.get("dependencies") != expected_dependencies:
        return f"skip attestation for {stage!r} has a different dependency set"
    states = record.get("dependency_states")
    if not isinstance(states, dict) or set(states) != set(expected_dependencies):
        return f"skip attestation for {stage!r} has malformed dependency states"
    stage_history = run.get("stage_history", [])
    skip_history = run.get("skipped_stage_history", [])
    if not isinstance(stage_history, list) or not isinstance(skip_history, list):
        return "managed stage/skip history is malformed"
    active_set = set(active)
    for dependency in expected_dependencies:
        state = states.get(dependency)
        if dependency not in active_set:
            if state != "inactive":
                return f"inactive dependency {dependency!r} has state {state!r}"
            continue
        succeeded = sum(
            1
            for item in stage_history
            if isinstance(item, dict)
            and item.get("stage") == dependency
            and item.get("status") == "succeeded"
        )
        skipped = sum(
            1
            for item in skip_history
            if isinstance(item, dict) and item.get("stage") == dependency
        )
        if state == "succeeded" and succeeded == 1:
            continue
        if state == "skipped" and skipped == 1:
            continue
        return f"dependency {dependency!r} is not durably settled as {state!r}"
    raw_checkpoint = record.get("workspace_checkpoint")
    try:
        if not isinstance(raw_checkpoint, dict):
            raise WorktreeError("checkpoint is missing")
        WorkspaceCheckpoint.from_dict(raw_checkpoint)
    except WorktreeError as exc:
        return f"skip attestation for {stage!r} has invalid workspace checkpoint: {exc}"
    if record.get("workflow_definition_digest") != contract.get(
        "workflow_definition_digest"
    ):
        return f"skip attestation for {stage!r} has a stale workflow digest"
    expected_n_a = _not_applicable_condition(str(condition))
    if record.get("not_applicable_condition") != expected_n_a:
        return f"skip attestation for {stage!r} has a non-canonical N/A condition"
    if record.get("attestation_sha256") != _skip_attestation_sha256(record):
        return f"skip attestation for {stage!r} has an invalid identity digest"
    if not (
        isinstance(record.get("attested_at"), str) and record["attested_at"].strip()
    ):
        return f"skip attestation for {stage!r} has no timestamp"
    if not (
        isinstance(record.get("repository_commit"), str)
        and record["repository_commit"].strip()
    ):
        return f"skip attestation for {stage!r} has no repository commit"
    return None


def skipped_stage_ids(target: str | Path) -> tuple[set[str], str | None]:
    """Return the canonical false-condition skips frozen in the active run."""

    snap, error = _load_snapshot(target)
    if error or snap is None:
        return set(), error or "no explicit pipeline run exists"
    raw = snap.get("skipped_stage_history", [])
    if not isinstance(raw, list) or any(not isinstance(item, dict) for item in raw):
        return set(), "skipped_stage_history must be an array of objects"
    result: set[str] = set()
    for item in raw:
        problem = _managed_skip_attestation_problem(snap, item)
        if problem:
            return set(), problem
        stage = str(item["stage"])
        if stage in result:
            return set(), f"stage {stage!r} has duplicate skip attestations"
        result.add(stage)
    return result, None


def skipped_stage_attestation(
    target: str | Path, stage: str
) -> tuple[dict[str, Any] | None, str | None]:
    """Return one verified skip record used for an authenticated handoff."""

    skipped, error = skipped_stage_ids(target)
    if error:
        return None, error
    if stage not in skipped:
        return None, None
    snap, error = _load_snapshot(target)
    if error or snap is None:
        return None, error or "no explicit pipeline run exists"
    matches = [
        item
        for item in snap.get("skipped_stage_history", [])
        if isinstance(item, dict) and item.get("stage") == stage
    ]
    if len(matches) != 1:
        return None, f"stage {stage!r} has no unique skip attestation"
    return dict(matches[0]), None


def attest_skipped_stage(
    target: str | Path,
    *,
    stage: str,
    condition: str,
    dependencies: Sequence[str],
    dependency_states: Mapping[str, str],
    workspace_checkpoint: Mapping[str, Any] | None,
) -> tuple[bool, list[str]]:
    """Persist one condition-false stage without inventing a dispatch result."""

    if not _STAGE_ID_RE.fullmatch(stage) or not _STAGE_ID_RE.fullmatch(condition):
        return False, ["FAIL  skipped stage/condition must be contained identifiers"]
    if any(not _STAGE_ID_RE.fullmatch(item) for item in dependencies):
        return False, ["FAIL  skipped stage dependencies contain an invalid identifier"]
    if set(dependency_states) != set(dependencies) or any(
        value not in {"succeeded", "skipped", "inactive"}
        for value in dependency_states.values()
    ):
        return False, ["FAIL  skipped stage dependency states are malformed"]
    try:
        supplied = (
            WorkspaceCheckpoint.from_dict(dict(workspace_checkpoint))
            if workspace_checkpoint is not None
            else None
        )
    except (TypeError, WorktreeError) as exc:
        return False, [f"FAIL  invalid skipped-stage workspace checkpoint: {exc}"]
    msgs: list[str] = []
    try:
        fs = ProjectFS(Path(target).expanduser())
        path = fs.path(_snapshot_rel(target))
        with _pipeline_write_lock(fs, path, msgs=msgs):
            snap, error = _load_snapshot(target)
            if error:
                return False, [f"FAIL  {error}"]
            run, identity, problem = _active_v2_run(target, snap)
            if problem or run is None or identity is None:
                return False, [f"FAIL  {problem or 'invalid run'}"]
            current, checkpoint_problem = _managed_workspace_checkpoint(fs.root, run)
            if checkpoint_problem or current is None:
                return False, [
                    f"FAIL  {checkpoint_problem or 'managed checkpoint missing'}"
                ]
            if supplied != current:
                return False, ["FAIL  skipped-stage workspace checkpoint is stale"]
            contract = cast(dict[str, Any], run.get("managed_execution"))
            workflow_digest = contract.get("workflow_definition_digest")
            record: dict[str, Any] = {
                "schema_version": 1,
                "stage": stage,
                "condition": condition,
                "decision": False,
                "dependencies": list(dependencies),
                "dependency_states": {
                    item: dependency_states[item] for item in dependencies
                },
                "not_applicable_condition": _not_applicable_condition(condition),
                "workflow_definition_digest": workflow_digest,
                "workspace_checkpoint": current.to_dict(),
                "attested_at": _utc_now(),
                "repository_commit": identity["commit"],
            }
            record["attestation_sha256"] = _skip_attestation_sha256(record)
            history = run.setdefault("skipped_stage_history", [])
            if not isinstance(history, list) or any(
                not isinstance(item, dict) for item in history
            ):
                return False, ["FAIL  skipped_stage_history ledger is malformed"]
            existing = [item for item in history if item.get("stage") == stage]
            if existing:
                if len(existing) == 1 and _skip_attestation_payload(existing[0]) == (
                    _skip_attestation_payload(record)
                ):
                    return True, [f"OK    stage {stage!r} already attested skipped"]
                return False, [
                    f"FAIL  stage {stage!r} has a conflicting skip attestation"
                ]
            raw_stage_history = run.get("stage_history", [])
            if not isinstance(raw_stage_history, list) or any(
                isinstance(item, dict) and item.get("stage") == stage
                for item in raw_stage_history
            ):
                return False, [f"FAIL  stage {stage!r} already has dispatch history"]
            semantic_problem = _managed_skip_attestation_problem(
                {**run, "skipped_stage_history": history + [record]}, record
            )
            if semantic_problem:
                return False, [f"FAIL  {semantic_problem}"]
            history.append(record)
            run["next"] = f"continue after condition-false stage {stage}"
            _write_snapshot_locked(target, run)
        msgs.append(f"OK    stage {stage!r} condition-false skip attested")
        return True, msgs
    except TimeoutError as exc:
        return False, [f"FAIL  {exc}"]
    except (UnsafePathError, OSError, ValueError) as exc:
        return False, [f"FAIL  unsafe pipeline state mutation refused: {exc}"]


def _program_binding_document(binding: ProgramManifestBinding) -> dict[str, Any]:
    return {
        "manifest_digest": binding.manifest_digest,
        "revision": binding.revision,
        "parent_digest": binding.parent_digest,
        "run_id": binding.run_id,
        "source_commit": binding.source_commit,
        "workflow_definition_digest": binding.workflow_definition_digest,
        "gate_definition_digest": binding.gate_definition_digest,
        "selection_digest": binding.selection_digest,
        "pipeline_gate_ids": list(binding.pipeline_gate_ids),
    }


def bind_program_execution(
    target: str | Path,
    *,
    manifest: ProgramManifest,
    manifest_path: str,
    binding: ProgramManifestBinding,
    workspace: Mapping[str, str],
) -> tuple[dict[str, Any] | None, str | None]:
    """Atomically freeze a Mode E manifest and initialize its transition ledger.

    The manifest is reloaded with the packaged schema before binding.  A later
    invocation may bind the exact immediate child revision only while no unit or
    gate has run; execution history is never rewritten during a re-plan.
    """

    if (
        not isinstance(manifest_path, str)
        or not manifest_path
        or Path(manifest_path).is_absolute()
        or ".." in Path(manifest_path).parts
        or Path(manifest_path).as_posix() != manifest_path
    ):
        return None, "program manifest path must be canonical and project-relative"
    workspace_binding = dict(workspace)
    if set(workspace_binding) != {"worker_id", "target_path", "base_commit"}:
        return None, "program workspace binding must contain exact identity fields"
    if not isinstance(
        workspace_binding["worker_id"], str
    ) or not _STAGE_ID_RE.fullmatch(workspace_binding["worker_id"]):
        return None, "program workspace worker id must be a contained identifier"
    if (
        not isinstance(workspace_binding["target_path"], str)
        or not workspace_binding["target_path"]
        or Path(workspace_binding["target_path"]).is_absolute()
        or ".." not in Path(workspace_binding["target_path"]).parts
    ):
        return None, "program workspace target must be a sibling-relative path"
    if not isinstance(workspace_binding["base_commit"], str) or not re.fullmatch(
        r"[0-9a-f]{40}|[0-9a-f]{64}", workspace_binding["base_commit"]
    ):
        return None, "program workspace base commit must be a commit id"

    try:
        fs = ProjectFS(Path(target).expanduser())
        root = fs.root
        path = fs.path(_snapshot_rel(target))
        frozen_path = fs.path(manifest_path)
        _frozen_bytes, frozen_sha, _manifest_bytes = _read_program_file_bounded(
            fs,
            manifest_path,
            maximum_bytes=_MAX_PROGRAM_SAFEGUARD_BYTES,
        )
        from claude_kit import scaffold
        from claude_kit.program_runtime import load_program_manifest

        with ExitStack() as resources:
            packaged_schema = (
                scaffold.payload_dir(resources)
                / "schemas"
                / "program-manifest.schema.json"
            )
            reloaded = load_program_manifest(frozen_path, schema_path=packaged_schema)
        if reloaded != manifest:
            return (
                None,
                "typed program manifest differs from its packaged-schema reload",
            )
        projection = _program_contract_projection(manifest)
        providers, provider_projection_digest = _installed_provider_projection(root)
        options = _installed_runtime_options(root)
        manager = WorktreeManager(root)
        record = manager.verify(binding.run_id, workspace_binding["worker_id"])
        if (
            record.target_path != workspace_binding["target_path"]
            or record.base_commit != workspace_binding["base_commit"]
        ):
            return None, "program workspace differs from its ownership record"
        initial_workspace_checkpoint = manager.checkpoint(
            record.run_id, record.worker_id
        )
        workspace_root = (root / record.target_path).resolve(strict=True)
        source_control_digest = _provider_control_surface_digest(
            root, options, providers
        )
        workspace_control_digest = _provider_control_surface_digest(
            workspace_root, options, providers
        )
        if source_control_digest != workspace_control_digest:
            return None, (
                "program workspace provider control surface differs from the installed "
                "source projection; commit the installed controls before execution"
            )
    except (OSError, UnsafePathError, ValueError, WorktreeError) as exc:
        return None, f"cannot prepare program execution binding: {exc}"

    manifest_record = {
        "path": manifest_path,
        "digest": manifest.digest,
        "file_sha256": frozen_sha,
        "revision": manifest.revision,
        "parent_digest": manifest.parent_digest,
    }
    now = _utc_now()
    wave_states = {
        wave.id: {
            "status": "pending",
            "started_at": None,
            "completed_at": None,
            "spawns_used": 0,
            "turns_used": 0,
            "token_upper_bound_used": 0,
            "wall_clock_elapsed_seconds": 0,
            "budget_exhausted": None,
        }
        for wave in manifest.waves
    }

    msgs: list[str] = []
    try:
        with _pipeline_write_lock(fs, path, msgs=msgs):
            snap, error = _load_snapshot(root)
            if error:
                return None, error
            run, identity, problem = _active_v2_run(root, snap)
            if problem or run is None or identity is None:
                return None, problem or "invalid run"
            if run.get("mode") != "E":
                return None, "program execution can be attached only to Mode E"
            if run.get("managed_execution") is not None:
                return (
                    None,
                    "program execution cannot replace a managed workflow contract",
                )
            if run.get("task") != manifest.objective:
                return None, "program objective differs from the active pipeline task"
            if identity["commit"] != manifest.source_commit:
                return (
                    None,
                    "program source commit differs from the current checkout HEAD",
                )
            if workspace_binding["base_commit"] != manifest.source_commit:
                return (
                    None,
                    "program workspace was not created from the manifest source commit",
                )
            if record.run_id != run.get("run_id"):
                return None, "program workspace belongs to a different pipeline run"

            # The filesystem preflight above keeps expensive failures out of the
            # mutation lock.  Repeat every identity-bearing read while holding the
            # lock so a successful bind can never persist an already-stale contract.
            _live_bytes, live_frozen_sha, _live_manifest_bytes = (
                _read_program_file_bounded(
                    fs,
                    manifest_path,
                    maximum_bytes=_MAX_PROGRAM_SAFEGUARD_BYTES,
                )
            )
            with ExitStack() as resources:
                live_packaged_schema = (
                    scaffold.payload_dir(resources)
                    / "schemas"
                    / "program-manifest.schema.json"
                )
                live_manifest = load_program_manifest(
                    frozen_path, schema_path=live_packaged_schema
                )
            if live_frozen_sha != frozen_sha or live_manifest != manifest:
                return None, "program manifest changed during authoritative bind"
            live_providers, live_provider_projection_digest = (
                _installed_provider_projection(root)
            )
            live_options = _installed_runtime_options(root)
            if (
                live_providers != providers
                or live_provider_projection_digest != provider_projection_digest
                or live_options != options
            ):
                return None, "installed provider projection changed during program bind"
            live_record = manager.verify(binding.run_id, workspace_binding["worker_id"])
            if (
                live_record.target_path != workspace_binding["target_path"]
                or live_record.base_commit != workspace_binding["base_commit"]
                or live_record.run_id != run.get("run_id")
            ):
                return None, "program workspace ownership changed during bind"
            live_workspace_checkpoint = manager.checkpoint(
                live_record.run_id, live_record.worker_id
            )
            if live_workspace_checkpoint != initial_workspace_checkpoint:
                return None, "program workspace changed during authoritative bind"
            live_workspace_root = (root / live_record.target_path).resolve(strict=True)
            live_source_control_digest = _provider_control_surface_digest(
                root, live_options, live_providers
            )
            live_workspace_control_digest = _provider_control_surface_digest(
                live_workspace_root, live_options, live_providers
            )
            if (
                live_source_control_digest != source_control_digest
                or live_workspace_control_digest != workspace_control_digest
                or live_source_control_digest != live_workspace_control_digest
            ):
                return None, "provider control surface changed during program bind"

            existing = run.get("program_execution")
            previous_digest: str | None = None
            history: list[dict[str, Any]] = []
            if isinstance(existing, dict):
                existing_manifest = existing.get("manifest")
                if (
                    isinstance(existing_manifest, dict)
                    and existing_manifest == manifest_record
                    and existing.get("binding") == _program_binding_document(binding)
                ):
                    return dict(existing), None
                if (
                    existing.get("unit_attempts")
                    or existing.get("gate_checkpoints")
                    or run.get("gate_history")
                ):
                    return None, (
                        "program manifest revision cannot change after unit or gate "
                        "execution has started"
                    )
                if not isinstance(existing_manifest, dict):
                    return None, "existing program manifest binding is malformed"
                previous_digest = existing_manifest.get("digest")
                previous_revision = existing_manifest.get("revision")
                if (
                    not isinstance(previous_digest, str)
                    or not isinstance(previous_revision, int)
                    or manifest.revision != previous_revision + 1
                    or manifest.parent_digest != previous_digest
                ):
                    return None, (
                        "program re-plan must be the immediate content-addressed child "
                        "of the frozen revision"
                    )
                raw_history = existing.get("manifest_history", [])
                if not isinstance(raw_history, list) or any(
                    not isinstance(item, dict) for item in raw_history
                ):
                    return None, "program manifest revision history is malformed"
                history = [*raw_history, dict(existing_manifest)]
            elif existing is not None:
                return None, "existing program execution contract is malformed"
            elif manifest.revision != 1:
                return None, "the first manifest bound to a run must be revision 1"

            from claude_kit.program_runtime import (
                ProgramManifestValidationError,
                validate_program_manifest_binding,
            )

            try:
                authoritative = validate_program_manifest_binding(
                    manifest,
                    run_id=str(run["run_id"]),
                    source_commit=identity["commit"],
                    workflow_definition_digest=_current_workflow_identity()[2],
                    gate_definition_digest=str(run["gate_definition_digest"]),
                    selection_digest=str(run["selection_digest"]),
                    ordered_gates=cast(Sequence[str], run["ordered_gates"]),
                    expected_revision=manifest.revision,
                    previous_manifest_digest=previous_digest,
                )
            except ProgramManifestValidationError as exc:
                return None, str(exc)
            if authoritative != binding:
                return None, "supplied program binding is not the authoritative binding"

            document: dict[str, Any] = {
                "schema_version": 1,
                "binding": _program_binding_document(authoritative),
                "manifest": manifest_record,
                "previous_manifest_digest": previous_digest,
                "manifest_history": history,
                "program_id": manifest.program_id,
                "objective": manifest.objective,
                "providers": list(providers),
                "provider_projection_digest": provider_projection_digest,
                "provider_control_surface_digest": workspace_control_digest,
                "workspace": workspace_binding,
                "binding_workspace_checkpoint": initial_workspace_checkpoint.to_dict(),
                **projection,
                "status": "active",
                "created_at": now,
                "current_wave": manifest.waves[0].id,
                "audit_gate_completed": False,
                "wave_states": wave_states,
                "unit_attempts": [],
                "completed_units": [],
                "gate_checkpoints": [],
                "safeguard_verifications": [],
            }
            if run.get("stage_history") or run.get("skipped_stage_history"):
                return None, (
                    "program execution cannot be attached after managed stage history exists"
                )
            run["program_execution"] = document
            prospective_problem = _program_execution_problem(root, run)
            if prospective_problem:
                return None, prospective_problem
            _write_snapshot_locked(root, run)
            return dict(document), None
    except TimeoutError as exc:
        return None, str(exc)
    except (OSError, UnsafePathError, ValueError) as exc:
        return None, f"unsafe pipeline state mutation refused: {exc}"


def bind_managed_execution(
    target: str | Path,
    *,
    workflow_id: str,
    workflow_schema_version: int,
    workflow_definition_digest: str,
    mode: str,
    ordered_gates: tuple[str, ...],
    gate_definition_digest: str,
    gate_owner_stages: Mapping[str, str],
    workspace: Mapping[str, str],
) -> tuple[dict[str, Any] | None, str | None]:
    """Freeze the complete workflow/gate-owner contract before managed execution."""
    if not _STAGE_ID_RE.fullmatch(workflow_id):
        return None, "managed workflow id must be a contained identifier"
    if (
        not isinstance(workflow_schema_version, int)
        or isinstance(workflow_schema_version, bool)
        or workflow_schema_version < 1
    ):
        return None, "managed workflow schema version must be positive"
    for label, digest in (
        ("workflow definition", workflow_definition_digest),
        ("gate definition", gate_definition_digest),
    ):
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            return None, f"managed {label} digest must be lowercase sha256"
    if mode not in MODES:
        return None, f"managed workflow mode must be one of {sorted(MODES)}"
    if not ordered_gates or len(set(ordered_gates)) != len(ordered_gates):
        return None, "managed workflow gates must be non-empty and unique"
    owners = dict(gate_owner_stages)
    if set(owners) != set(ordered_gates) or any(
        not isinstance(stage, str) or not _STAGE_ID_RE.fullmatch(stage)
        for stage in owners.values()
    ):
        return None, "managed workflow must map every gate to one owning stage"
    workspace_binding = dict(workspace)
    if set(workspace_binding) != {"worker_id", "target_path", "base_commit"}:
        return None, "managed workspace binding must contain exact identity fields"
    if not isinstance(
        workspace_binding["worker_id"], str
    ) or not _STAGE_ID_RE.fullmatch(workspace_binding["worker_id"]):
        return None, "managed workspace worker id must be a contained identifier"
    if (
        not isinstance(workspace_binding["target_path"], str)
        or not workspace_binding["target_path"]
        or Path(workspace_binding["target_path"]).is_absolute()
        or ".." not in Path(workspace_binding["target_path"]).parts
    ):
        return None, "managed workspace target must be a sibling-relative path"
    if not isinstance(workspace_binding["base_commit"], str) or not re.fullmatch(
        r"[0-9a-f]{40}|[0-9a-f]{64}", workspace_binding["base_commit"]
    ):
        return None, "managed workspace base commit must be a commit id"
    try:
        current_id, current_version, current_digest = _current_workflow_identity()
    except (OSError, ValueError) as exc:
        return None, f"cannot load the canonical managed workflow: {exc}"
    if (
        workflow_id,
        workflow_schema_version,
        workflow_definition_digest,
    ) != (current_id, current_version, current_digest):
        return (
            None,
            "managed workflow identity differs from the installed canonical workflow",
        )
    try:
        (
            active_stages,
            active_dependencies,
            active_requirements,
            active_routes,
            canonical_owners,
        ) = _managed_active_graph(target, mode, ordered_gates)
        providers, provider_projection_digest = _installed_provider_projection(target)
        options = _installed_runtime_options(Path(target).expanduser())
        source_control_digest = _provider_control_surface_digest(
            Path(target).expanduser(), options, providers
        )
        manager = WorktreeManager(target)
        matching_records = [
            record
            for record in manager.records()
            if record.worker_id == workspace_binding["worker_id"]
            and record.target_path == workspace_binding["target_path"]
            and record.base_commit == workspace_binding["base_commit"]
        ]
        if len(matching_records) != 1:
            return None, "managed workspace has no unique ownership record"
        workspace_record = manager.verify(
            matching_records[0].run_id, matching_records[0].worker_id
        )
        initial_workspace_checkpoint = manager.checkpoint(
            workspace_record.run_id, workspace_record.worker_id
        )
        workspace_root = (
            ProjectFS(Path(target).expanduser()).root / workspace_record.target_path
        ).resolve(strict=True)
        workspace_control_digest = _provider_control_surface_digest(
            workspace_root, options, providers
        )
    except (OSError, ValueError) as exc:
        return None, f"cannot project managed workflow stage graph: {exc}"
    except WorktreeError as exc:
        return None, f"cannot verify managed workspace ownership: {exc}"
    if workspace_control_digest != source_control_digest:
        return None, (
            "managed workspace provider control surface differs from the installed "
            "source projection; commit the installed controls before execution"
        )
    if owners != canonical_owners:
        return None, "managed gate-owner map differs from the canonical mode policy"
    inactive_owners = sorted(set(owners.values()) - set(active_stages))
    if inactive_owners:
        return None, (
            "managed gate owners are outside the active stage graph: "
            + ", ".join(inactive_owners)
        )
    evidence_projection = managed_evidence_projection(
        _current_workflow_definition(),
        active_stages=active_stages,
        ordered_gates=ordered_gates,
    )
    document: dict[str, Any] = {
        "workflow_id": workflow_id,
        "workflow_schema_version": workflow_schema_version,
        "workflow_definition_digest": workflow_definition_digest,
        "mode": mode,
        "ordered_gates": list(ordered_gates),
        "gate_definition_digest": gate_definition_digest,
        "gate_owner_stages": {gate: owners[gate] for gate in ordered_gates},
        "providers": list(providers),
        "provider_projection_digest": provider_projection_digest,
        "provider_control_surface_digest": workspace_control_digest,
        "workspace": workspace_binding,
        "binding_workspace_checkpoint": initial_workspace_checkpoint.to_dict(),
        "active_stages": list(active_stages),
        "active_stage_dependencies": {
            stage: list(active_dependencies[stage]) for stage in active_stages
        },
        "active_stage_requirements": {
            stage: list(active_requirements[stage]) for stage in active_stages
        },
        "active_stage_routes": {stage: active_routes[stage] for stage in active_stages},
        **evidence_projection,
    }

    msgs: list[str] = []
    try:
        fs = ProjectFS(Path(target).expanduser())
        path = fs.path(_snapshot_rel(target))
    except (UnsafePathError, OSError, ValueError) as exc:
        return None, f"unsafe pipeline state path: {exc}"
    try:
        with _pipeline_write_lock(fs, path, msgs=msgs):
            snap, error = _load_snapshot(target)
            if error:
                return None, error
            run, identity, problem = _active_v2_run(target, snap)
            if problem or run is None or identity is None:
                return None, problem or "invalid run"
            if run.get("run_id") != workspace_record.run_id:
                return None, "managed workspace belongs to a different pipeline run"
            if list(ordered_gates) != run.get("ordered_gates") or (
                gate_definition_digest != run.get("gate_definition_digest")
            ):
                return None, "managed workflow gate policy differs from the active run"
            if run.get("program_execution") is not None:
                return (
                    None,
                    "managed execution cannot replace a program execution contract",
                )

            # Repeat every identity-bearing projection under the mutation lock.
            # Preflight remains useful for clear diagnostics, but it is never the
            # authority persisted into a run that may have changed meanwhile.
            try:
                live_workflow_identity = _current_workflow_identity()
                (
                    live_active_stages,
                    live_active_dependencies,
                    live_active_requirements,
                    live_active_routes,
                    live_canonical_owners,
                ) = _managed_active_graph(fs.root, mode, ordered_gates)
                live_evidence_projection = managed_evidence_projection(
                    _current_workflow_definition(),
                    active_stages=live_active_stages,
                    ordered_gates=ordered_gates,
                )
                live_providers, live_provider_projection_digest = (
                    _installed_provider_projection(fs.root)
                )
                live_options = _installed_runtime_options(fs.root)
                live_record = manager.verify(
                    str(run.get("run_id")), workspace_binding["worker_id"]
                )
                live_checkpoint = manager.checkpoint(
                    live_record.run_id, live_record.worker_id
                )
                live_workspace_root = (fs.root / live_record.target_path).resolve(
                    strict=True
                )
                live_source_control_digest = _provider_control_surface_digest(
                    fs.root, live_options, live_providers
                )
                live_workspace_control_digest = _provider_control_surface_digest(
                    live_workspace_root, live_options, live_providers
                )
            except (OSError, ValueError, WorktreeError) as exc:
                return None, f"cannot revalidate managed bind authority: {exc}"
            if live_workflow_identity != (
                current_id,
                current_version,
                current_digest,
            ):
                return None, "canonical workflow changed during managed bind"
            if (
                live_active_stages != active_stages
                or live_active_dependencies != active_dependencies
                or live_active_requirements != active_requirements
                or live_active_routes != active_routes
                or live_canonical_owners != canonical_owners
                or live_evidence_projection != evidence_projection
            ):
                return None, "canonical managed graph changed during authoritative bind"
            if (
                live_providers != providers
                or live_provider_projection_digest != provider_projection_digest
                or live_options != options
            ):
                return None, "installed provider projection changed during managed bind"
            if (
                live_record.run_id != run.get("run_id")
                or live_record.target_path != workspace_binding["target_path"]
                or live_record.base_commit != workspace_binding["base_commit"]
            ):
                return None, "managed workspace ownership changed during bind"
            if identity["commit"] != live_record.base_commit:
                return None, (
                    "source checkout HEAD changed during managed bind; recreate the "
                    "run-owned workspace from the authoritative source commit"
                )
            if live_checkpoint != initial_workspace_checkpoint:
                return None, "managed workspace changed during authoritative bind"
            if (
                live_source_control_digest != source_control_digest
                or live_workspace_control_digest != workspace_control_digest
                or live_source_control_digest != live_workspace_control_digest
            ):
                return None, "provider control surface changed during managed bind"
            existing = run.get("managed_execution")
            if isinstance(existing, dict) and isinstance(
                existing.get("binding_workspace_checkpoint"), dict
            ):
                idempotent_document = dict(document)
                idempotent_document["binding_workspace_checkpoint"] = existing[
                    "binding_workspace_checkpoint"
                ]
                if existing == idempotent_document:
                    return dict(existing), None
            if existing is None:
                if run.get("stage_history") or run.get("gate_history"):
                    return None, (
                        "managed execution cannot be attached after stage or gate history exists"
                    )
                run["managed_execution"] = document
                run["execution_binding"] = _managed_execution_binding(document)
                run.setdefault("skipped_stage_history", [])
                _write_snapshot_locked(target, run)
                return dict(document), None
            if isinstance(existing, dict):
                legacy_projection = dict(document)
                legacy_projection.pop("active_stages", None)
                legacy_projection.pop("active_stage_dependencies", None)
                legacy_projection.pop("active_stage_requirements", None)
                legacy_projection.pop("active_stage_routes", None)
                legacy_projection.pop("providers", None)
                legacy_projection.pop("provider_projection_digest", None)
                legacy_projection.pop("provider_control_surface_digest", None)
                legacy_projection.pop("binding_workspace_checkpoint", None)
                for evidence_field in (
                    "evidence_contract_version",
                    "active_stage_evidence",
                    "gate_evidence",
                    "evidence_requirements",
                    "findings_policy",
                ):
                    legacy_projection.pop(evidence_field, None)
                if existing == legacy_projection:
                    existing = dict(document)
                    run["managed_execution"] = existing
                    run["execution_binding"] = _managed_execution_binding(existing)
                    run.setdefault("skipped_stage_history", [])
                    _write_snapshot_locked(target, run)
            if existing != document:
                return (
                    None,
                    "managed execution contract differs from the frozen run contract",
                )
            if "skipped_stage_history" not in run:
                run["skipped_stage_history"] = []
                _write_snapshot_locked(target, run)
            return dict(document), None
    except TimeoutError as exc:
        return None, str(exc)
    except (UnsafePathError, OSError, ValueError) as exc:
        return None, f"unsafe pipeline state mutation refused: {exc}"


def _managed_evidence_relative(
    run_id: str,
    stage: str,
    dispatch_attempt: int,
    evidence_id: str,
    digest: str,
    *,
    layout: StateLayout,
) -> str:
    return (
        f"{layout.artifacts}/evidence/runs/{run_id}/{stage}/"
        f"{dispatch_attempt}/{evidence_id}-{digest}.json"
    )


def _managed_dispatch_artifact_relative(
    run_id: str,
    stage: str,
    ledger_attempt: int,
    digest: str,
    *,
    layout: StateLayout,
) -> str:
    """Return the immutable run-owned terminal artifact path for one attempt."""

    return (
        f"{layout.artifacts}/dispatch/runs/{run_id}/{stage}/{ledger_attempt}/"
        f"terminal-{digest}.json"
    )


def _managed_closeout_projection(
    fs: ProjectFS,
    run: Mapping[str, Any],
) -> tuple[list[dict[str, Any]] | None, list[dict[str, Any]] | None, str | None]:
    """Project and revalidate the exact resolved A--D gate/risk ledgers."""

    ordered = run.get("ordered_gates")
    history = run.get("gate_history")
    risks = run.get("accepted_risks")
    if (
        not isinstance(ordered, list)
        or not isinstance(history, list)
        or not isinstance(risks, list)
        or any(not isinstance(item, dict) for item in [*history, *risks])
    ):
        return None, None, "managed closeout authoritative ledgers are malformed"
    resolved = [item for item in history if item.get("status") in POSITION_STATUSES]
    if [item.get("gate") for item in resolved] != ordered:
        return (
            None,
            None,
            "managed closeout resolutions differ from the exact ordered gate set",
        )
    projected_gates: list[dict[str, Any]] = []
    status_by_gate: dict[str, str] = {}
    for gate, entry in zip(ordered, resolved):
        status = entry.get("status")
        if status == "not-applicable":
            if any(key in entry for key in ("evidence_path", "evidence_sha256")):
                return (
                    None,
                    None,
                    (
                        f"managed closeout gate {gate!r} mixes ordinary and "
                        "not-applicable evidence"
                    ),
                )
            bundle_problem = _managed_not_applicable_bundle_problem(fs, run, entry)
            evidence_path = entry.get("condition_evidence_path")
            evidence_sha = entry.get("condition_evidence_sha256")
        else:
            if any(
                key in entry
                for key in (
                    "condition_evidence_path",
                    "condition_evidence_sha256",
                )
            ):
                return (
                    None,
                    None,
                    (
                        f"managed closeout gate {gate!r} uses not-applicable evidence "
                        f"for status {status!r}"
                    ),
                )
            bundle_problem = _managed_gate_bundle_problem(fs, run, entry)
            evidence_path = entry.get("evidence_path")
            evidence_sha = entry.get("evidence_sha256")
        if bundle_problem:
            return None, None, bundle_problem
        if (
            not isinstance(status, str)
            or not isinstance(evidence_path, str)
            or not isinstance(evidence_sha, str)
            or not re.fullmatch(r"[0-9a-f]{64}", evidence_sha)
        ):
            return None, None, f"managed closeout gate {gate!r} has no evidence digest"
        status_by_gate[str(gate)] = status
        projected_gates.append(
            {
                "id": gate,
                "status": status,
                "evidence": [{"path": evidence_path, "sha256": evidence_sha}],
            }
        )
    projected_risks: list[dict[str, Any]] = []
    risk_ids_by_gate: dict[str, list[str]] = {}
    for risk in risks:
        evidence_path = risk.get("evidence_path")
        evidence_sha = risk.get("evidence_sha256")
        affected_gate = risk.get("affected_gate")
        if (
            not isinstance(evidence_path, str)
            or not isinstance(evidence_sha, str)
            or not re.fullmatch(r"[0-9a-f]{64}", evidence_sha)
            or not isinstance(affected_gate, str)
            or status_by_gate.get(affected_gate) != "accepted-risk"
        ):
            return None, None, "managed closeout accepted-risk evidence is malformed"
        risk_evidence_problem = _managed_accepted_risk_evidence_problem(fs, run, risk)
        if risk_evidence_problem:
            return None, None, risk_evidence_problem
        risk_id = risk.get("risk_id")
        if not isinstance(risk_id, str):
            return None, None, "managed closeout accepted-risk identity is malformed"
        risk_ids_by_gate.setdefault(affected_gate, []).append(risk_id)
        projected_risks.append(
            {
                "risk-id": risk_id,
                "affected-gate": affected_gate,
                "finding-id": risk.get("finding_id"),
                "reason": risk.get("reason"),
                "accepter": risk.get("accepted_by"),
                "owner": risk.get("owner"),
                "ticket": risk.get("ticket"),
                "revisit-trigger": risk.get("revisit"),
                "evidence": [{"path": evidence_path, "sha256": evidence_sha}],
                "compensating-control": risk.get("compensating_control"),
                "timestamp": risk.get("timestamp"),
                "repository-commit": risk.get("repository_commit"),
                "medium-finding-count": risk.get("medium_finding_count"),
                "finding-set-digest": risk.get("finding_set_digest"),
                "finding-fingerprint": risk.get("finding_fingerprint"),
                "gate-definition-digest": risk.get("gate_definition_digest"),
                "workspace-head-commit": risk.get("workspace_head_commit"),
                "workspace-content-digest": risk.get("workspace_content_digest"),
            }
        )
    for entry in resolved:
        gate = entry.get("gate")
        if entry.get("status") == "accepted-risk":
            if entry.get("accepted_risk_ids") != risk_ids_by_gate.get(str(gate), []):
                return (
                    None,
                    None,
                    f"managed closeout gate {gate!r} is not bound to its exact risk ledger",
                )
        elif risk_ids_by_gate.get(str(gate)):
            return None, None, f"managed closeout gate {gate!r} has unexpected risks"
    return projected_gates, projected_risks, None


def _managed_closeout_document_problem(
    fs: ProjectFS, content: bytes, run: Mapping[str, Any]
) -> str | None:
    try:
        document = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return "managed closeout evidence is not valid JSON"
    if not isinstance(document, dict):
        return "managed closeout evidence must be an object"
    gates, risks, problem = _managed_closeout_projection(fs, run)
    if problem:
        return problem
    if document.get("gates") != gates:
        return "managed closeout gate ledger differs from authoritative resolutions"
    if document.get("accepted-risks") != risks:
        return "managed closeout accepted-risk ledger differs from pipeline state"
    return None


def _managed_reconciliation_artifact_relative(
    run_id: str,
    stage: str,
    ledger_attempt: int,
    digest: str,
    *,
    layout: StateLayout,
) -> str:
    return (
        f"{layout.artifacts}/dispatch/runs/{run_id}/{stage}/{ledger_attempt}/"
        f"reconciliation-{digest}.json"
    )


def materialize_managed_stage_evidence(
    target: str | Path,
    *,
    stage: str,
    dispatch_id: str,
    dispatch_attempt: int,
    output: str | None,
    require_pass: bool = True,
) -> tuple[tuple[dict[str, Any], ...] | None, str | None]:
    """Validate and persist one exact managed A--D evidence envelope.

    Files are coordinator-owned, content-addressed, atomically written with mode
    ``0600``, and subsequently re-read by :func:`finish_stage` under the ledger
    lock.  An orphaned content-addressed file is harmless if ledger completion
    loses a race or otherwise fails.
    """

    if not _STAGE_ID_RE.fullmatch(stage) or not dispatch_id.strip():
        return None, "managed evidence stage/dispatch identity is malformed"
    if (
        not isinstance(dispatch_attempt, int)
        or isinstance(dispatch_attempt, bool)
        or dispatch_attempt < 1
    ):
        return None, "managed evidence dispatch attempt must be positive"
    snap, error = _load_snapshot(target)
    if error or not isinstance(snap, dict):
        return None, error or "managed pipeline snapshot is unavailable"
    contract = snap.get("managed_execution")
    if not isinstance(contract, dict):
        return None, "managed execution contract is missing"
    if contract.get("evidence_contract_version") != EVIDENCE_CONTRACT_VERSION:
        return None, "managed typed evidence contract is missing or unsupported"
    stage_map = contract.get("active_stage_evidence")
    requirements = contract.get("evidence_requirements")
    policy = contract.get("findings_policy")
    expected = stage_map.get(stage) if isinstance(stage_map, dict) else None
    if (
        not isinstance(expected, list)
        or not expected
        or any(not isinstance(item, str) for item in expected)
        or not isinstance(requirements, dict)
        or not isinstance(policy, dict)
    ):
        return None, "managed stage has no frozen typed evidence contract"
    try:
        fs = ProjectFS(Path(target).expanduser())
        payloads = parse_evidence_envelope(
            output,
            expected_ids=expected,
            requirements=requirements,
            findings_policy=policy,
            mode=str(contract.get("mode")),
            require_pass=require_pass,
        )
        for evidence_id, payload in payloads.items():
            requirement = requirements.get(evidence_id)
            if (
                isinstance(requirement, dict)
                and requirement.get("validation_profile") == "closeout-record"
            ):
                closeout_problem = _managed_closeout_document_problem(fs, payload, snap)
                if closeout_problem:
                    return None, closeout_problem
        findings, _counts = normalized_findings(payloads)
        layout = _state_layout(fs.root)
    except (EvidenceValidationError, OSError, UnsafePathError, ValueError) as exc:
        return None, str(exc)
    run_id = snap.get("run_id")
    if not isinstance(run_id, str) or not _STAGE_ID_RE.fullmatch(run_id):
        return None, "managed run id is malformed"
    source_sha = hashlib.sha256((output or "").encode("utf-8")).hexdigest()
    finding_ids_by_evidence: dict[str, list[str]] = {}
    for finding in findings:
        finding_ids_by_evidence.setdefault(
            str(finding["source_evidence_id"]), []
        ).append(str(finding["finding_id"]))
    records: list[dict[str, Any]] = []
    try:
        for evidence_id in expected:
            payload = payloads[evidence_id]
            digest = hashlib.sha256(payload).hexdigest()
            relative = _managed_evidence_relative(
                run_id,
                stage,
                dispatch_attempt,
                evidence_id,
                digest,
                layout=layout,
            )
            try:
                existing, _existing_sha, _existing_size = _read_managed_file_bounded(
                    fs, relative, maximum_bytes=len(payload)
                )
            except FileNotFoundError:
                fs.write_bytes(relative, payload, mode=0o600)
                existing, _existing_sha, _existing_size = _read_managed_file_bounded(
                    fs, relative, maximum_bytes=len(payload)
                )
            if existing != payload:
                return None, (
                    f"root-owned managed evidence {evidence_id!r} conflicts with "
                    "its content address"
                )
            info = fs.path(relative).lstat()
            if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
                return None, (
                    f"root-owned managed evidence {evidence_id!r} must be a 0600 regular file"
                )
            requirement = cast(dict[str, Any], requirements[evidence_id])
            records.append(
                {
                    "schema_version": 1,
                    "kind": "managed-workflow-evidence",
                    "run_id": run_id,
                    "stage": stage,
                    "dispatch_id": dispatch_id,
                    "dispatch_attempt": dispatch_attempt,
                    "evidence_id": evidence_id,
                    "artifact_path": relative,
                    "artifact_sha256": digest,
                    "evidence_kind": requirement["kind"],
                    "validation_profile": requirement["validation_profile"],
                    "required_fields": list(requirement["required_fields"]),
                    "source_output_sha256": source_sha,
                    "finding_ids": finding_ids_by_evidence.get(evidence_id, []),
                }
            )
    except (FileNotFoundError, OSError, UnsafePathError, ValueError) as exc:
        return None, f"cannot persist managed stage evidence: {exc}"
    return tuple(records), None


def _managed_stage_evidence_problem(
    fs: ProjectFS,
    run: Mapping[str, Any],
    *,
    stage: str,
    dispatch_id: str,
    dispatch_attempt: int,
    output_sha256: str | None,
    records: Any,
    require_pass: bool = True,
) -> tuple[str | None, list[dict[str, Any]], dict[str, int]]:
    """Re-read and semantically validate the exact root-owned stage records."""

    empty_counts = {key: 0 for key in FINDING_KEYS}
    contract = run.get("managed_execution")
    if not isinstance(contract, dict):
        return "managed execution contract is missing", [], empty_counts
    if contract.get("evidence_contract_version") != EVIDENCE_CONTRACT_VERSION:
        return (
            "managed typed evidence contract is missing or unsupported",
            [],
            empty_counts,
        )
    stage_map = contract.get("active_stage_evidence")
    requirements = contract.get("evidence_requirements")
    policy = contract.get("findings_policy")
    expected = stage_map.get(stage) if isinstance(stage_map, dict) else None
    if (
        not isinstance(expected, list)
        or not expected
        or not isinstance(requirements, dict)
        or not isinstance(policy, dict)
        or not isinstance(records, (list, tuple))
        or any(not isinstance(item, Mapping) for item in records)
    ):
        return "managed stage evidence ledger is malformed", [], empty_counts
    by_id = {
        str(item.get("evidence_id")): item
        for item in records
        if isinstance(item.get("evidence_id"), str)
    }
    if len(by_id) != len(records) or set(by_id) != set(expected):
        return (
            "managed stage evidence ledger differs from the exact evidence set",
            [],
            empty_counts,
        )
    run_id = run.get("run_id")
    if not isinstance(run_id, str):
        return "managed run id is malformed", [], empty_counts
    layout = _state_layout(fs.root)
    payloads: dict[str, bytes] = {}
    expected_record_fields = {
        "schema_version",
        "kind",
        "run_id",
        "stage",
        "dispatch_id",
        "dispatch_attempt",
        "evidence_id",
        "artifact_path",
        "artifact_sha256",
        "evidence_kind",
        "validation_profile",
        "required_fields",
        "source_output_sha256",
        "finding_ids",
    }
    for evidence_id in expected:
        record = by_id[evidence_id]
        requirement = requirements.get(evidence_id)
        if not isinstance(requirement, dict) or set(record) != expected_record_fields:
            return (
                f"managed evidence record {evidence_id!r} has an invalid shape",
                [],
                empty_counts,
            )
        digest = record.get("artifact_sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            return (
                f"managed evidence record {evidence_id!r} has no content digest",
                [],
                empty_counts,
            )
        expected_path = _managed_evidence_relative(
            run_id,
            stage,
            dispatch_attempt,
            evidence_id,
            digest,
            layout=layout,
        )
        if (
            record.get("schema_version") != 1
            or record.get("kind") != "managed-workflow-evidence"
            or record.get("run_id") != run_id
            or record.get("stage") != stage
            or record.get("dispatch_id") != dispatch_id
            or record.get("dispatch_attempt") != dispatch_attempt
            or record.get("artifact_path") != expected_path
            or record.get("source_output_sha256") != output_sha256
            or record.get("evidence_kind") != requirement.get("kind")
            or record.get("validation_profile") != requirement.get("validation_profile")
            or record.get("required_fields") != requirement.get("required_fields")
        ):
            return (
                f"managed evidence record {evidence_id!r} has inconsistent provenance",
                [],
                empty_counts,
            )
        try:
            info = fs.path(expected_path).lstat()
            payload, actual_digest, _payload_size = _read_managed_file_bounded(
                fs,
                expected_path,
                maximum_bytes=MAX_EVIDENCE_ENVELOPE_BYTES,
            )
        except (FileNotFoundError, OSError, UnsafePathError, ValueError) as exc:
            return (
                f"managed evidence record {evidence_id!r} is unavailable: {exc}",
                [],
                empty_counts,
            )
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o600
            or len(payload) > _MAX_PROGRAM_ARTIFACT_BYTES
        ):
            return (
                f"managed evidence record {evidence_id!r} is not a bounded 0600 regular file",
                [],
                empty_counts,
            )
        if actual_digest != digest:
            return (
                f"managed evidence record {evidence_id!r} hash mismatch",
                [],
                empty_counts,
            )
        try:
            document = json.loads(payload)
            validate_evidence_document(
                document,
                requirement,
                policy,
                mode=str(contract.get("mode")),
                require_pass=require_pass,
            )
            if requirement.get("validation_profile") == "closeout-record":
                closeout_problem = _managed_closeout_document_problem(fs, payload, run)
                if closeout_problem:
                    return (
                        f"managed evidence record {evidence_id!r} is invalid: "
                        f"{closeout_problem}",
                        [],
                        empty_counts,
                    )
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            EvidenceValidationError,
        ) as exc:
            return (
                f"managed evidence record {evidence_id!r} is invalid: {exc}",
                [],
                empty_counts,
            )
        payloads[evidence_id] = payload
    try:
        findings, counts = normalized_findings(payloads)
    except EvidenceValidationError as exc:
        return str(exc), [], empty_counts
    expected_ids_by_evidence: dict[str, list[str]] = {}
    for finding in findings:
        expected_ids_by_evidence.setdefault(
            str(finding["source_evidence_id"]), []
        ).append(str(finding["finding_id"]))
    for evidence_id in expected:
        finding_ids = by_id[evidence_id].get("finding_ids")
        if finding_ids != expected_ids_by_evidence.get(evidence_id, []):
            return (
                f"managed evidence record {evidence_id!r} finding identities differ",
                [],
                empty_counts,
            )
    return None, findings, counts


def _write_private_content_addressed_json(
    fs: ProjectFS, relative: str, document: Mapping[str, Any]
) -> tuple[str, str]:
    content = (
        json.dumps(
            dict(document),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    return _write_private_content_addressed_bytes(fs, relative, content)


def _write_private_content_addressed_bytes(
    fs: ProjectFS, relative: str, content: bytes
) -> tuple[str, str]:
    """Atomically persist exact bounded bytes at a private content address."""

    if len(content) > MAX_EVIDENCE_ENVELOPE_BYTES:
        raise ValueError("root-owned content-addressed record exceeds the safety limit")
    digest = hashlib.sha256(content).hexdigest()
    resolved_relative = relative.replace("{sha256}", digest)
    try:
        existing, _existing_sha, _existing_size = _read_managed_file_bounded(
            fs, resolved_relative, maximum_bytes=len(content)
        )
    except FileNotFoundError:
        fs.write_bytes(resolved_relative, content, mode=0o600)
        existing, _existing_sha, _existing_size = _read_managed_file_bounded(
            fs, resolved_relative, maximum_bytes=len(content)
        )
    if existing != content:
        raise ValueError("root-owned content-addressed record conflicts")
    info = fs.path(resolved_relative).lstat()
    if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
        raise ValueError(
            "root-owned content-addressed record is not a 0600 regular file"
        )
    return resolved_relative, digest


def _managed_risk_evidence_relative(
    run_id: str,
    gate: str,
    finding_id: str,
    digest: str,
    *,
    layout: StateLayout,
) -> str:
    finding_digest = hashlib.sha256(finding_id.encode("utf-8")).hexdigest()[:16]
    return (
        f"{layout.artifacts}/evidence/runs/{run_id}/risks/{gate}/"
        f"{finding_digest}-{digest}.bin"
    )


def _materialize_managed_risk_evidence(
    fs: ProjectFS,
    run: Mapping[str, Any],
    *,
    gate: str,
    finding_id: str,
    source_relative: str,
) -> tuple[str, str]:
    """Copy one bounded human risk attestation into the run-owned evidence store."""

    if Path(source_relative).is_absolute():
        raise ValueError("managed accepted-risk evidence must be inside the project")
    run_id = run.get("run_id")
    if (
        not isinstance(run_id, str)
        or not _STAGE_ID_RE.fullmatch(run_id)
        or not _STAGE_ID_RE.fullmatch(gate)
        or not finding_id.strip()
    ):
        raise ValueError("managed accepted-risk evidence identity is malformed")
    content, source_digest, _source_size = _read_managed_file_bounded(
        fs,
        source_relative,
        maximum_bytes=MAX_EVIDENCE_ENVELOPE_BYTES,
    )
    template = _managed_risk_evidence_relative(
        run_id,
        gate,
        finding_id,
        "{sha256}",
        layout=_state_layout(fs.root),
    )
    relative, digest = _write_private_content_addressed_bytes(fs, template, content)
    if digest != source_digest:
        raise ValueError("managed accepted-risk evidence changed while materializing")
    return relative, digest


def _managed_accepted_risk_evidence_problem(
    fs: ProjectFS, run: Mapping[str, Any], risk: Mapping[str, Any]
) -> str | None:
    """Verify one exact run-owned human accepted-risk evidence artifact."""

    run_id = run.get("run_id")
    gate = risk.get("affected_gate")
    finding_id = risk.get("finding_id")
    digest = risk.get("evidence_sha256")
    relative = risk.get("evidence_path")
    if (
        not isinstance(run_id, str)
        or not _STAGE_ID_RE.fullmatch(run_id)
        or not isinstance(gate, str)
        or not _STAGE_ID_RE.fullmatch(gate)
        or not isinstance(finding_id, str)
        or not finding_id.strip()
        or not isinstance(digest, str)
        or not re.fullmatch(r"[0-9a-f]{64}", digest)
        or not isinstance(relative, str)
    ):
        return "managed accepted-risk evidence identity is malformed"
    expected = _managed_risk_evidence_relative(
        run_id,
        gate,
        finding_id,
        digest,
        layout=_state_layout(fs.root),
    )
    if relative != expected:
        return "managed accepted-risk evidence is outside its exact run/gate binding"
    try:
        info = fs.path(relative).lstat()
        _content, actual_digest, _content_size = _read_managed_file_bounded(
            fs,
            relative,
            maximum_bytes=MAX_EVIDENCE_ENVELOPE_BYTES,
        )
    except (FileNotFoundError, OSError, UnsafePathError, ValueError):
        return "managed accepted-risk evidence is unavailable"
    if (
        not stat.S_ISREG(info.st_mode)
        or stat.S_IMODE(info.st_mode) != 0o600
        or actual_digest != digest
    ):
        return "managed accepted-risk evidence content or mode changed after recording"
    return None


def _managed_owner_evidence(
    fs: ProjectFS, run: Mapping[str, Any], gate: str
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], dict[str, int], str | None]:
    owner, problem = _managed_owner_stage_record(run, gate)
    empty_counts = {key: 0 for key in FINDING_KEYS}
    if problem or owner is None:
        return None, [], empty_counts, problem or "managed gate owner is missing"
    evidence_problem, findings, counts = _managed_stage_evidence_problem(
        fs,
        run,
        stage=str(owner.get("stage")),
        dispatch_id=str(owner.get("dispatch_id")),
        dispatch_attempt=cast(int, owner.get("dispatch_attempt")),
        output_sha256=cast(Optional[str], owner.get("output_sha256")),
        records=owner.get("evidence_records"),
    )
    return owner, findings, counts, evidence_problem


def _next_unresolved_gate(run: Mapping[str, Any]) -> str | None:
    gates = run.get("ordered_gates")
    if not isinstance(gates, list):
        return None
    resolved = _resolved_gate_names(cast(dict[str, Any], run), gates)
    return next((str(gate) for gate in gates if gate not in resolved), None)


def _managed_gate_finding_projection(
    fs: ProjectFS, run: Mapping[str, Any], gate: str
) -> tuple[
    dict[str, Any] | None,
    list[dict[str, Any]],
    dict[str, int],
    list[dict[str, Any]],
    str | None,
]:
    """Aggregate findings over the owner's exact active dependency closure."""

    owner, _owner_findings, _owner_counts, owner_problem = _managed_owner_evidence(
        fs, run, gate
    )
    empty_counts = {key: 0 for key in FINDING_KEYS}
    if owner_problem or owner is None:
        return (
            None,
            [],
            empty_counts,
            [],
            owner_problem or "managed owner is unavailable",
        )
    contract = run.get("managed_execution")
    history = run.get("stage_history")
    if not isinstance(contract, dict) or not isinstance(history, list):
        return None, [], empty_counts, [], "managed stage ledger is malformed"
    active = contract.get("active_stages")
    dependencies = contract.get("active_stage_dependencies")
    if not isinstance(active, list) or not isinstance(dependencies, dict):
        return None, [], empty_counts, [], "managed dependency graph is malformed"
    owner_stage = owner.get("stage")
    if not isinstance(owner_stage, str) or owner_stage not in active:
        return None, [], empty_counts, [], "managed gate owner is outside the graph"
    active_set = set(active)
    closure = {owner_stage}
    pending = [owner_stage]
    while pending:
        current = pending.pop()
        raw_dependencies = dependencies.get(current)
        if not isinstance(raw_dependencies, list):
            return None, [], empty_counts, [], "managed dependency graph is malformed"
        for dependency in raw_dependencies:
            if dependency in active_set and dependency not in closure:
                closure.add(str(dependency))
                pending.append(str(dependency))

    contributors: list[dict[str, Any]] = []
    findings_by_id: dict[str, dict[str, Any]] = {}
    for stage in (str(item) for item in active if item in closure):
        observations = [
            record
            for record in history
            if isinstance(record, dict)
            and record.get("stage") == stage
            and record.get("status") in {"succeeded", "failed"}
            and bool(record.get("evidence_records"))
        ]
        observations.sort(key=lambda item: int(item.get("attempt", 0)))
        for record in observations:
            evidence_problem, record_findings, _record_counts = (
                _managed_stage_evidence_problem(
                    fs,
                    run,
                    stage=stage,
                    dispatch_id=str(record.get("dispatch_id")),
                    dispatch_attempt=cast(int, record.get("dispatch_attempt")),
                    output_sha256=cast(Optional[str], record.get("output_sha256")),
                    records=record.get("evidence_records"),
                    require_pass=record.get("status") == "succeeded",
                )
            )
            if evidence_problem:
                return None, [], empty_counts, [], evidence_problem
            raw_records = cast(list[dict[str, Any]], record["evidence_records"])
            evidence_set = [
                {
                    "evidence_id": item.get("evidence_id"),
                    "artifact_sha256": item.get("artifact_sha256"),
                }
                for item in raw_records
            ]
            contributors.append(
                {
                    "stage": stage,
                    "status": record.get("status"),
                    "ledger_attempt": record.get("attempt"),
                    "dispatch_id": record.get("dispatch_id"),
                    "dispatch_attempt": record.get("dispatch_attempt"),
                    "output_sha256": record.get("output_sha256"),
                    "output_artifact_sha256": record.get("output_artifact_sha256"),
                    "evidence_set": evidence_set,
                }
            )
            for finding in record_findings:
                finding_id = str(finding["finding_id"])
                prior = findings_by_id.get(finding_id)
                if prior is None:
                    findings_by_id[finding_id] = finding
                elif prior.get("fingerprint") != finding.get("fingerprint"):
                    return (
                        None,
                        [],
                        empty_counts,
                        [],
                        f"finding {finding_id!r} has conflicting evidence identities "
                        "inside the gate dependency closure",
                    )
    findings = sorted(
        findings_by_id.values(),
        key=lambda item: (str(item["finding_id"]), str(item["fingerprint"])),
    )
    counts = {key: 0 for key in FINDING_KEYS}
    for finding in findings:
        severity = str(finding.get("severity", "")).lower()
        count_key = "cosmetic" if severity == "info" else severity
        if count_key not in counts:
            return None, [], empty_counts, [], "managed finding severity is invalid"
        counts[count_key] += 1
    projection_digest = hashlib.sha256(
        json.dumps(
            contributors,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return owner, findings, counts, contributors, projection_digest


def _managed_findings_bundle(
    fs: ProjectFS, run: Mapping[str, Any], *, gate: str, persist: bool = True
) -> tuple[dict[str, Any] | None, str | None]:
    owner, findings, counts, contributors, projection_digest = (
        _managed_gate_finding_projection(fs, run, gate)
    )
    if (
        owner is None
        or not isinstance(projection_digest, str)
        or not re.fullmatch(r"[0-9a-f]{64}", projection_digest)
    ):
        return None, projection_digest or "managed owner evidence is unavailable"
    evidence_set_digest = projection_digest
    document = {
        "schema_version": 1,
        "kind": "managed-workflow-findings",
        "run_id": run.get("run_id"),
        "gate": gate,
        "owner_stage": owner.get("stage"),
        "owner_dispatch_id": owner.get("dispatch_id"),
        "owner_dispatch_attempt": owner.get("dispatch_attempt"),
        "owner_output_sha256": owner.get("output_sha256"),
        "workspace_checkpoint": owner.get("workspace_checkpoint"),
        "workflow_definition_digest": cast(
            dict[str, Any], run["managed_execution"]
        ).get("workflow_definition_digest"),
        "gate_definition_digest": run.get("gate_definition_digest"),
        "evidence_set_digest": evidence_set_digest,
        "contributors": contributors,
        "counts": counts,
        "findings": findings,
    }
    layout = _state_layout(fs.root)
    relative_template = (
        f"{layout.artifacts}/evidence/runs/{run.get('run_id')}/findings/"
        f"{gate}-{owner.get('stage')}-{{sha256}}.json"
    )
    encoded = (
        json.dumps(
            document,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    expected_digest = hashlib.sha256(encoded).hexdigest()
    relative = relative_template.replace("{sha256}", expected_digest)
    digest = expected_digest
    try:
        if persist:
            relative, digest = _write_private_content_addressed_json(
                fs, relative_template, document
            )
    except (OSError, UnsafePathError, ValueError) as exc:
        return None, f"cannot persist managed findings bundle: {exc}"
    return {
        "path": relative,
        "sha256": digest,
        "document": document,
    }, None


def _managed_findings_bundle_problem(
    fs: ProjectFS, run: Mapping[str, Any], record: Mapping[str, Any]
) -> str | None:
    gate = record.get("managed_gate")
    if not isinstance(gate, str):
        return "managed findings evidence has no gate binding"
    expected, problem = _managed_findings_bundle(fs, run, gate=gate, persist=False)
    if problem or expected is None:
        return problem or "managed findings evidence is unavailable"
    document = cast(dict[str, Any], expected["document"])
    if (
        record.get("evidence_path") != expected["path"]
        or record.get("evidence_sha256") != expected["sha256"]
        or record.get("counts") != document["counts"]
        or record.get("finding_ids")
        != [item["finding_id"] for item in document["findings"]]
        or record.get("finding_index") != document["findings"]
        or record.get("owner_stage") != document["owner_stage"]
        or record.get("owner_dispatch_id") != document["owner_dispatch_id"]
        or record.get("owner_dispatch_attempt") != document["owner_dispatch_attempt"]
        or record.get("owner_output_sha256") != document["owner_output_sha256"]
        or record.get("evidence_set_digest") != document["evidence_set_digest"]
    ):
        return "managed findings evidence differs from its exact owner-stage bundle"
    try:
        content, actual_sha, _content_size = _read_managed_file_bounded(
            fs,
            str(expected["path"]),
            maximum_bytes=MAX_EVIDENCE_ENVELOPE_BYTES,
        )
        info = fs.path(str(expected["path"])).lstat()
        actual_document = json.loads(content)
    except (
        FileNotFoundError,
        OSError,
        UnsafePathError,
        ValueError,
        json.JSONDecodeError,
    ):
        return "managed findings evidence bundle is unavailable or malformed"
    if (
        not stat.S_ISREG(info.st_mode)
        or stat.S_IMODE(info.st_mode) != 0o600
        or actual_sha != expected["sha256"]
        or actual_document != document
    ):
        return "managed findings evidence bundle content is invalid"
    return None


def _managed_findings_record(
    run: Mapping[str, Any],
    bundle: Mapping[str, Any],
    *,
    repository_commit: str,
    workspace_checkpoint: WorkspaceCheckpoint,
) -> dict[str, Any]:
    document = cast(dict[str, Any], bundle["document"])
    counts = cast(dict[str, int], document["counts"])
    evidence_sha = str(bundle["sha256"])
    return {
        "counts": dict(counts),
        "evidence_path": str(bundle["path"]),
        "evidence_sha256": evidence_sha,
        "finding_set_digest": _finding_set_digest(
            counts,
            evidence_sha256=evidence_sha,
            repository_commit=repository_commit,
            workspace_content_digest=workspace_checkpoint.content_digest,
        ),
        "repository_commit": repository_commit,
        "recorded_at": _utc_now(),
        "managed_gate": document["gate"],
        "owner_stage": document["owner_stage"],
        "owner_dispatch_id": document["owner_dispatch_id"],
        "owner_dispatch_attempt": document["owner_dispatch_attempt"],
        "owner_output_sha256": document["owner_output_sha256"],
        "evidence_set_digest": document["evidence_set_digest"],
        "finding_ids": [item["finding_id"] for item in document["findings"]],
        "finding_index": document["findings"],
        "workspace_head_commit": workspace_checkpoint.head_commit,
        "workspace_content_digest": workspace_checkpoint.content_digest,
    }


def _managed_gate_bundle(
    fs: ProjectFS, run: Mapping[str, Any], *, gate: str, persist: bool = True
) -> tuple[dict[str, Any] | None, str | None]:
    owner, _findings, _counts, problem = _managed_owner_evidence(fs, run, gate)
    if problem or owner is None:
        return None, problem or "managed owner evidence is unavailable"
    (
        _projection_owner,
        gate_findings,
        gate_finding_counts,
        finding_contributors,
        finding_projection_digest,
    ) = _managed_gate_finding_projection(fs, run, gate)
    if not isinstance(finding_projection_digest, str) or not re.fullmatch(
        r"[0-9a-f]{64}", finding_projection_digest
    ):
        return None, finding_projection_digest or "managed findings are unavailable"
    contract = cast(dict[str, Any], run.get("managed_execution"))
    gate_map = contract.get("gate_evidence")
    expected = gate_map.get(gate) if isinstance(gate_map, dict) else None
    owner_records = owner.get("evidence_records")
    if not isinstance(expected, list) or not isinstance(owner_records, list):
        return None, "managed gate evidence contract is malformed"
    by_id = {
        item.get("evidence_id"): item
        for item in owner_records
        if isinstance(item, dict) and isinstance(item.get("evidence_id"), str)
    }
    if not set(expected).issubset(by_id):
        return None, "managed gate owner does not contain the exact gate evidence set"
    selected = [dict(by_id[evidence_id]) for evidence_id in expected]
    evidence_set_digest = hashlib.sha256(
        json.dumps(
            [
                {
                    "evidence_id": item["evidence_id"],
                    "artifact_sha256": item["artifact_sha256"],
                }
                for item in selected
            ],
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    document = {
        "schema_version": 1,
        "kind": "managed-workflow-gate-evidence",
        "run_id": run.get("run_id"),
        "gate": gate,
        "owner_stage": owner.get("stage"),
        "owner_dispatch_id": owner.get("dispatch_id"),
        "owner_dispatch_attempt": owner.get("dispatch_attempt"),
        "owner_output_sha256": owner.get("output_sha256"),
        "workspace_checkpoint": owner.get("workspace_checkpoint"),
        "workflow_definition_digest": contract.get("workflow_definition_digest"),
        "gate_definition_digest": run.get("gate_definition_digest"),
        "evidence_ids": list(expected),
        "evidence_set_digest": evidence_set_digest,
        "evidence_records": selected,
        "finding_evidence_set_digest": finding_projection_digest,
        "finding_contributors": finding_contributors,
        "finding_counts": gate_finding_counts,
        "finding_ids": [item["finding_id"] for item in gate_findings],
    }
    layout = _state_layout(fs.root)
    relative_template = (
        f"{layout.artifacts}/evidence/runs/{run.get('run_id')}/gates/{gate}/"
        f"{owner.get('stage')}-{owner.get('dispatch_attempt')}-{{sha256}}.json"
    )
    encoded = (
        json.dumps(
            document,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    expected_digest = hashlib.sha256(encoded).hexdigest()
    relative = relative_template.replace("{sha256}", expected_digest)
    digest = expected_digest
    try:
        if persist:
            relative, digest = _write_private_content_addressed_json(
                fs, relative_template, document
            )
    except (OSError, UnsafePathError, ValueError) as exc:
        return None, f"cannot persist managed gate evidence bundle: {exc}"
    return {
        "path": relative,
        "sha256": digest,
        "document": document,
    }, None


def _managed_gate_bundle_problem(
    fs: ProjectFS,
    run: Mapping[str, Any],
    entry: Mapping[str, Any],
) -> str | None:
    gate = entry.get("gate")
    if not isinstance(gate, str):
        return "managed gate entry has no gate identifier"
    expected, problem = _managed_gate_bundle(fs, run, gate=gate, persist=False)
    if problem or expected is None:
        return problem or "managed gate evidence bundle is unavailable"
    if (
        entry.get("evidence_path") != expected["path"]
        or entry.get("evidence_sha256") != expected["sha256"]
        or entry.get("owner_stage") != expected["document"]["owner_stage"]
        or entry.get("owner_dispatch_id") != expected["document"]["owner_dispatch_id"]
        or entry.get("owner_dispatch_attempt")
        != expected["document"]["owner_dispatch_attempt"]
        or entry.get("owner_output_sha256")
        != expected["document"]["owner_output_sha256"]
        or entry.get("evidence_set_digest")
        != expected["document"]["evidence_set_digest"]
    ):
        return f"managed gate {gate!r} differs from its exact owner evidence bundle"
    try:
        content, actual_sha, _content_size = _read_managed_file_bounded(
            fs,
            str(expected["path"]),
            maximum_bytes=MAX_EVIDENCE_ENVELOPE_BYTES,
        )
        info = fs.path(str(expected["path"])).lstat()
        document = json.loads(content)
    except (
        FileNotFoundError,
        OSError,
        UnsafePathError,
        ValueError,
        json.JSONDecodeError,
    ):
        return f"managed gate {gate!r} evidence bundle is unavailable or malformed"
    if (
        not stat.S_ISREG(info.st_mode)
        or stat.S_IMODE(info.st_mode) != 0o600
        or actual_sha != expected["sha256"]
        or document != expected["document"]
    ):
        return f"managed gate {gate!r} evidence bundle content is invalid"
    return None


def _managed_not_applicable_owner(
    fs: ProjectFS, run: Mapping[str, Any], gate: str
) -> tuple[dict[str, Any] | None, str | None]:
    """Project the exact successful or skipped owner of a managed N/A gate."""

    owner, problem = _managed_owner_stage_record(run, gate, allow_skipped=True)
    if problem or owner is None:
        return None, problem or "managed not-applicable owner is unavailable"
    if owner.get("decision") is False:
        skip_problem = _managed_skip_attestation_problem(run, owner)
        if skip_problem:
            return None, skip_problem
        return {
            "kind": "skipped",
            "stage": owner.get("stage"),
            "workspace_checkpoint": owner.get("workspace_checkpoint"),
            "attestation_sha256": owner.get("attestation_sha256"),
            "attestation": dict(owner),
        }, None

    gate_bundle, bundle_problem = _managed_gate_bundle(
        fs, run, gate=gate, persist=False
    )
    if bundle_problem or gate_bundle is None:
        return None, bundle_problem or "managed owner evidence is unavailable"
    document = cast(dict[str, Any], gate_bundle["document"])
    return {
        "kind": "succeeded",
        "stage": document["owner_stage"],
        "dispatch_id": document["owner_dispatch_id"],
        "dispatch_attempt": document["owner_dispatch_attempt"],
        "output_sha256": document["owner_output_sha256"],
        "workspace_checkpoint": document["workspace_checkpoint"],
        "evidence_ids": document["evidence_ids"],
        "evidence_set_digest": document["evidence_set_digest"],
        "evidence_records": document["evidence_records"],
    }, None


def _managed_not_applicable_predicate_problem(
    run: Mapping[str, Any], *, gate: str, condition: str
) -> str | None:
    """Bind a managed N/A transition to its frozen positive stage predicate."""

    contract = run.get("managed_execution")
    if (
        not isinstance(contract, dict)
        or contract.get("evidence_contract_version") != EVIDENCE_CONTRACT_VERSION
    ):
        return None
    owners = contract.get("gate_owner_stages")
    owner_stage = owners.get(gate) if isinstance(owners, dict) else None
    try:
        workflow = _current_workflow_definition()
        stage_condition = workflow.stage_by_id[str(owner_stage)].condition
    except (KeyError, OSError, ValueError) as exc:
        return f"cannot derive managed not-applicable predicate: {exc}"
    inverse = _not_applicable_condition(stage_condition)
    if inverse != condition:
        return (
            "managed not-applicable condition is not the canonical inverse of "
            f"owner predicate {stage_condition!r}"
        )
    decisions = run.get("condition_decisions")
    if not isinstance(decisions, dict) or decisions.get(stage_condition) is not False:
        return (
            f"managed not-applicable condition {condition!r} requires frozen "
            f"{stage_condition!r}=false"
        )
    history = run.get("stage_history")
    if isinstance(history, list) and any(
        isinstance(record, dict)
        and record.get("stage") == owner_stage
        and record.get("status") == "succeeded"
        for record in history
    ):
        return (
            f"managed gate {gate!r} cannot be not-applicable after owner stage "
            f"{owner_stage!r} succeeded under a frozen false predicate"
        )
    return None


def _managed_condition_evidence_copy(
    fs: ProjectFS,
    run: Mapping[str, Any],
    *,
    gate: str,
    source: Path,
) -> tuple[dict[str, str] | None, str | None]:
    """Copy condition input into the private run namespace by exact content hash."""

    try:
        source_relative = fs.relpath(source)
        content, digest, _content_size = _read_managed_file_bounded(
            fs,
            source_relative,
            maximum_bytes=MAX_EVIDENCE_ENVELOPE_BYTES,
        )
    except (OSError, UnsafePathError, ValueError) as exc:
        return None, f"cannot read managed condition evidence: {exc}"
    layout = _state_layout(fs.root)
    relative = (
        f"{layout.artifacts}/evidence/runs/{run.get('run_id')}/conditions/"
        f"{gate}-{digest}.bin"
    )
    try:
        try:
            existing, _existing_sha, _existing_size = _read_managed_file_bounded(
                fs, relative, maximum_bytes=len(content)
            )
        except FileNotFoundError:
            fs.write_bytes(relative, content, mode=0o600)
            existing, _existing_sha, _existing_size = _read_managed_file_bounded(
                fs, relative, maximum_bytes=len(content)
            )
        info = fs.path(relative).lstat()
    except (OSError, UnsafePathError, ValueError) as exc:
        return None, f"cannot persist managed condition evidence: {exc}"
    if existing != content:
        return None, "root-owned managed condition evidence conflicts with its hash"
    if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
        return None, "root-owned managed condition evidence must be a 0600 regular file"
    return {"artifact_path": relative, "artifact_sha256": digest}, None


def _managed_not_applicable_bundle(
    fs: ProjectFS,
    run: Mapping[str, Any],
    *,
    gate: str,
    condition: str,
    reason: str,
    condition_source: Path,
) -> tuple[dict[str, Any] | None, str | None]:
    """Persist the exact owner and copied condition input for a managed N/A gate."""

    owner, owner_problem = _managed_not_applicable_owner(fs, run, gate)
    if owner_problem or owner is None:
        return None, owner_problem or "managed not-applicable owner is unavailable"
    condition_evidence, evidence_problem = _managed_condition_evidence_copy(
        fs, run, gate=gate, source=condition_source
    )
    if evidence_problem or condition_evidence is None:
        return None, evidence_problem or "managed condition evidence is unavailable"
    contract = cast(dict[str, Any], run.get("managed_execution"))
    document = {
        "schema_version": 1,
        "kind": "managed-workflow-not-applicable",
        "run_id": run.get("run_id"),
        "gate": gate,
        "condition": condition,
        "reason": reason,
        "workflow_definition_digest": contract.get("workflow_definition_digest"),
        "gate_definition_digest": run.get("gate_definition_digest"),
        "condition_evidence": condition_evidence,
        "owner": owner,
    }
    layout = _state_layout(fs.root)
    relative_template = (
        f"{layout.artifacts}/evidence/runs/{run.get('run_id')}/gates/{gate}/"
        f"{owner.get('stage')}-not-applicable-{{sha256}}.json"
    )
    try:
        relative, digest = _write_private_content_addressed_json(
            fs, relative_template, document
        )
    except (OSError, UnsafePathError, ValueError) as exc:
        return None, f"cannot persist managed not-applicable bundle: {exc}"
    return {"path": relative, "sha256": digest, "document": document}, None


def _managed_not_applicable_bundle_problem(
    fs: ProjectFS,
    run: Mapping[str, Any],
    entry: Mapping[str, Any],
) -> str | None:
    """Re-read and rederive one managed N/A bundle from its exact current owner."""

    relative = entry.get("condition_evidence_path")
    recorded_sha = entry.get("condition_evidence_sha256")
    if not isinstance(relative, str) or not isinstance(recorded_sha, str):
        return "managed not-applicable gate has no root-owned evidence bundle"
    try:
        content, actual_sha, _content_size = _read_managed_file_bounded(
            fs,
            relative,
            maximum_bytes=MAX_EVIDENCE_ENVELOPE_BYTES,
        )
        info = fs.path(relative).lstat()
        document = json.loads(content)
    except (
        FileNotFoundError,
        OSError,
        UnsafePathError,
        ValueError,
        json.JSONDecodeError,
    ):
        return "managed not-applicable evidence bundle is unavailable or malformed"
    if (
        not stat.S_ISREG(info.st_mode)
        or stat.S_IMODE(info.st_mode) != 0o600
        or actual_sha != recorded_sha
        or not isinstance(document, dict)
    ):
        return "managed not-applicable evidence bundle content is invalid"
    layout = _state_layout(fs.root)
    owner = document.get("owner")
    gate = entry.get("gate")
    expected_relative = (
        f"{layout.artifacts}/evidence/runs/{run.get('run_id')}/gates/{gate}/"
        f"{owner.get('stage') if isinstance(owner, dict) else ''}-"
        f"not-applicable-{recorded_sha}.json"
    )
    contract = run.get("managed_execution")
    if (
        relative != expected_relative
        or document.get("schema_version") != 1
        or document.get("kind") != "managed-workflow-not-applicable"
        or document.get("run_id") != run.get("run_id")
        or document.get("gate") != gate
        or document.get("condition") != entry.get("condition")
        or document.get("reason") != entry.get("reason")
        or not isinstance(contract, dict)
        or document.get("workflow_definition_digest")
        != contract.get("workflow_definition_digest")
        or document.get("gate_definition_digest") != run.get("gate_definition_digest")
    ):
        return "managed not-applicable evidence bundle has inconsistent provenance"
    predicate_problem = _managed_not_applicable_predicate_problem(
        run,
        gate=str(gate),
        condition=str(entry.get("condition")),
    )
    if predicate_problem:
        return predicate_problem
    expected_owner, owner_problem = _managed_not_applicable_owner(fs, run, str(gate))
    if owner_problem or expected_owner is None:
        return owner_problem or "managed not-applicable owner is unavailable"
    if owner != expected_owner:
        return "managed not-applicable gate differs from its exact owner record"
    condition_evidence = document.get("condition_evidence")
    if not isinstance(condition_evidence, dict) or set(condition_evidence) != {
        "artifact_path",
        "artifact_sha256",
    }:
        return "managed not-applicable condition evidence record is malformed"
    condition_path = condition_evidence.get("artifact_path")
    condition_sha = condition_evidence.get("artifact_sha256")
    expected_condition_path = (
        f"{layout.artifacts}/evidence/runs/{run.get('run_id')}/conditions/"
        f"{gate}-{condition_sha}.bin"
    )
    if (
        not isinstance(condition_path, str)
        or not isinstance(condition_sha, str)
        or not re.fullmatch(r"[0-9a-f]{64}", condition_sha)
        or condition_path != expected_condition_path
    ):
        return "managed not-applicable condition evidence has inconsistent provenance"
    try:
        condition_content, condition_actual_sha, _condition_size = (
            _read_managed_file_bounded(
                fs,
                condition_path,
                maximum_bytes=MAX_EVIDENCE_ENVELOPE_BYTES,
            )
        )
        condition_info = fs.path(condition_path).lstat()
    except (FileNotFoundError, OSError, UnsafePathError, ValueError):
        return "managed not-applicable condition evidence is unavailable"
    if (
        not stat.S_ISREG(condition_info.st_mode)
        or stat.S_IMODE(condition_info.st_mode) != 0o600
        or condition_actual_sha != condition_sha
    ):
        return "managed not-applicable condition evidence content is invalid"
    if entry.get("owner_stage") != expected_owner.get("stage"):
        return "managed not-applicable gate has inconsistent owner provenance"
    if expected_owner.get("kind") == "succeeded":
        if (
            entry.get("owner_dispatch_id") != expected_owner.get("dispatch_id")
            or entry.get("owner_dispatch_attempt")
            != expected_owner.get("dispatch_attempt")
            or entry.get("owner_output_sha256") != expected_owner.get("output_sha256")
            or entry.get("evidence_set_digest")
            != expected_owner.get("evidence_set_digest")
        ):
            return "managed not-applicable gate has inconsistent owner evidence"
    elif entry.get("owner_skip_attestation_sha256") != expected_owner.get(
        "attestation_sha256"
    ):
        return "managed not-applicable gate has inconsistent skip attestation"
    return None


def _program_current_workspace_checkpoint(
    root: Path, contract: Mapping[str, Any]
) -> tuple[WorkspaceCheckpoint | None, str | None]:
    workspace = contract.get("workspace")
    binding = contract.get("binding")
    if not isinstance(workspace, dict) or not isinstance(binding, dict):
        return None, "program workspace or manifest binding is malformed"
    try:
        manager = WorktreeManager(root)
        record = manager.verify(
            str(binding.get("run_id")), str(workspace.get("worker_id"))
        )
        if record.target_path != workspace.get(
            "target_path"
        ) or record.base_commit != workspace.get("base_commit"):
            return None, "program workspace differs from its binding"
        return manager.checkpoint(record.run_id, record.worker_id), None
    except (OSError, ValueError, WorktreeError) as exc:
        return None, f"cannot verify program workspace checkpoint: {exc}"


def _program_checkpoint(
    value: Mapping[str, Any], *, label: str
) -> tuple[WorkspaceCheckpoint | None, str | None]:
    try:
        return WorkspaceCheckpoint.from_dict(dict(value)), None
    except (TypeError, ValueError, WorktreeError) as exc:
        return None, f"{label} is invalid: {exc}"


def _program_wave_elapsed_seconds(state: Mapping[str, Any], now: str) -> int:
    started = state.get("started_at")
    if not isinstance(started, str):
        return 0
    try:
        beginning = datetime.fromisoformat(started)
        ending = datetime.fromisoformat(now)
    except ValueError:
        return 0
    return max(0, int((ending - beginning).total_seconds()))


def claim_program_unit(
    target: str | Path,
    *,
    unit_id: str,
    provider: str,
    route: str,
    dispatch_id: str,
    attempt: int,
    required_capabilities: tuple[str, ...],
    attested_capabilities: tuple[str, ...],
    pre_workspace_checkpoint: Mapping[str, Any],
    prompt_token_upper_bound: int,
    physical_boundary_containment: Mapping[str, Any] | None = None,
) -> tuple[bool, list[str]]:
    """Reserve one exact program-unit attempt before its worker can make progress."""

    if (
        not isinstance(prompt_token_upper_bound, int)
        or isinstance(prompt_token_upper_bound, bool)
        or prompt_token_upper_bound < 0
    ):
        return False, ["FAIL  prompt token upper bound must be non-negative"]
    if not isinstance(dispatch_id, str) or not dispatch_id.strip():
        return False, ["FAIL  dispatch_id must be non-empty"]
    supplied_checkpoint, checkpoint_problem = _program_checkpoint(
        pre_workspace_checkpoint, label="program pre-dispatch workspace checkpoint"
    )
    if checkpoint_problem or supplied_checkpoint is None:
        return False, [f"FAIL  {checkpoint_problem}"]
    try:
        required = _stage_capabilities(
            required_capabilities, field_name="required_capabilities"
        )
        attested = _stage_capabilities(
            attested_capabilities, field_name="attested_capabilities"
        )
    except ValueError as exc:
        return False, [f"FAIL  {exc}"]
    if required != attested:
        return False, [
            "FAIL  program route must attest its exact effective native capability set"
        ]

    msgs: list[str] = []
    try:
        fs = ProjectFS(Path(target).expanduser())
        root = fs.root
        path = fs.path(_snapshot_rel(root))
    except (OSError, UnsafePathError, ValueError) as exc:
        return False, [f"FAIL  unsafe pipeline state path: {exc}"]
    try:
        with _pipeline_write_lock(fs, path, msgs=msgs):
            snap, error = _load_snapshot(root)
            if error:
                return False, [f"FAIL  {error}"]
            run, identity, problem = _active_v2_run(root, snap)
            if problem or run is None or identity is None:
                return False, [f"FAIL  {problem or 'invalid run'}"]
            contract = run.get("program_execution")
            if not isinstance(contract, dict):
                return False, ["FAIL  no frozen program execution contract exists"]
            if contract.get("status") != "active":
                return False, ["FAIL  program execution is terminal"]
            units = contract.get("units")
            waves = contract.get("waves")
            wave_states = contract.get("wave_states")
            attempts = contract.get("unit_attempts")
            completed = contract.get("completed_units")
            if (
                not isinstance(units, dict)
                or not isinstance(waves, dict)
                or not isinstance(wave_states, dict)
                or not isinstance(attempts, list)
                or not isinstance(completed, list)
            ):
                return False, ["FAIL  program execution ledger is malformed"]
            unit = units.get(unit_id)
            if not isinstance(unit, dict):
                return False, [f"FAIL  unknown program unit {unit_id!r}"]
            if unit.get("irreversible") is True:
                return False, [
                    "FAIL  irreversible program units cannot be claimed until a scoped "
                    "approval broker consumes an exact authorization"
                ]
            if unit_id in completed:
                return False, [
                    f"FAIL  completed program unit {unit_id!r} cannot be replayed"
                ]
            if any(item.get("status") == "running" for item in attempts):
                return False, ["FAIL  another program unit attempt is still running"]
            dependencies = unit.get("dependencies")
            if not isinstance(dependencies, list) or not set(dependencies).issubset(
                completed
            ):
                return False, [
                    f"FAIL  program unit {unit_id!r} has unresolved dependencies"
                ]
            wave_id = unit.get("wave_id")
            wave = waves.get(wave_id)
            state = wave_states.get(wave_id)
            if not isinstance(wave, dict) or not isinstance(state, dict):
                return False, ["FAIL  program unit wave contract is malformed"]
            ordered_waves = contract.get("ordered_waves")
            if not isinstance(ordered_waves, list) or wave_id not in ordered_waves:
                return False, ["FAIL  program wave order is malformed"]
            for previous_wave in ordered_waves[: ordered_waves.index(wave_id)]:
                previous_state = wave_states.get(previous_wave)
                if (
                    not isinstance(previous_state, dict)
                    or previous_state.get("status") != "completed"
                ):
                    return False, [
                        f"FAIL  program wave {wave_id!r} cannot start before "
                        f"{previous_wave!r} completes"
                    ]
            if wave.get("kind") == "execution" and not contract.get(
                "audit_gate_completed"
            ):
                return False, [
                    "FAIL  Wave 0 audit verification must complete before execution"
                ]
            if provider not in contract.get("providers", []):
                return False, [
                    "FAIL  provider is outside the frozen program provider set"
                ]
            if route not in unit.get("route_candidates", []):
                return False, [
                    "FAIL  route is outside the frozen program route candidates"
                ]
            capability_floor = unit.get("required_capabilities")
            if not isinstance(capability_floor, list):
                return False, ["FAIL  program unit capability contract is malformed"]
            floor = set(capability_floor)
            effective = set(required)
            allowed = floor | {Capability.MESSAGE.value}
            if not floor.issubset(effective) or not effective.issubset(allowed):
                return False, [
                    "FAIL  program route effective capability set exceeds the frozen "
                    "Mode E closure"
                ]
            containment_required = bool(
                {Capability.FILE_WRITE.value, Capability.SHELL.value} & effective
            )
            supplied_containment = (
                dict(physical_boundary_containment)
                if isinstance(physical_boundary_containment, Mapping)
                else None
            )
            if containment_required:
                workspace = contract.get("workspace")
                issuer = (
                    supplied_containment.get("issuer")
                    if isinstance(supplied_containment, dict)
                    else None
                )
                if (
                    not isinstance(workspace, dict)
                    or not isinstance(issuer, str)
                    or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", issuer)
                ):
                    return False, [
                        "FAIL  shell-capable or writable program unit lacks a typed "
                        "adapter boundary-containment attestation"
                    ]
                expected_containment = _program_containment_record(
                    unit,
                    provider=provider,
                    route=route,
                    dispatch_id=dispatch_id,
                    unit_id=unit_id,
                    workspace_target=workspace.get("target_path"),
                    pre_workspace_checkpoint_digest=supplied_checkpoint.content_digest,
                    issuer=issuer,
                )
                if supplied_containment != expected_containment:
                    return False, [
                        "FAIL  adapter boundary-containment attestation is not bound "
                        "to the exact unit, handle, workspace, boundaries, and checkpoint"
                    ]
            elif supplied_containment is not None:
                return False, [
                    "FAIL  read-only program unit supplied an unexpected boundary "
                    "containment attestation"
                ]
            if Capability.EXTERNAL_MUTATION.value in effective:
                return False, [
                    "FAIL  program units cannot attest coordinator-owned external mutation"
                ]
            unit_attempts = [
                item for item in attempts if item.get("unit_id") == unit_id
            ]
            if attempt != len(unit_attempts) + 1:
                return False, ["FAIL  program unit attempt number is not contiguous"]
            budget = wave.get("budget")
            if not isinstance(budget, dict):
                return False, ["FAIL  program wave budget is malformed"]
            if attempt > budget.get("max_attempts_per_unit", 0):
                return False, ["FAIL  program unit attempt budget is exhausted"]
            if attempt > budget.get("max_turns_per_worker", 0):
                return False, ["FAIL  program unit turn budget is exhausted"]
            if state.get("spawns_used", 0) >= budget.get("hard_spawn_cap", 0):
                return False, ["FAIL  program wave hard spawn cap is exhausted"]
            if state.get(
                "token_upper_bound_used", 0
            ) + prompt_token_upper_bound > budget.get("token_ceiling", 0):
                return False, ["FAIL  program wave token ceiling is exhausted"]
            now = _utc_now()
            if state.get("started_at") is not None:
                elapsed = _program_wave_elapsed_seconds(state, now)
                if elapsed >= budget.get("wall_clock_seconds", 0):
                    return False, ["FAIL  program wave wall-clock budget is exhausted"]
            current_checkpoint, workspace_problem = (
                _program_current_workspace_checkpoint(root, contract)
            )
            if workspace_problem or current_checkpoint is None:
                return False, [f"FAIL  {workspace_problem}"]
            expected_pre = contract.get("binding_workspace_checkpoint")
            terminal_attempts = [
                item
                for item in attempts
                if isinstance(item, dict) and item.get("status") != "running"
            ]
            if terminal_attempts:
                previous = terminal_attempts[-1]
                expected_pre = (
                    previous.get("post_workspace_checkpoint")
                    if previous.get("status") == "succeeded"
                    else previous.get("pre_workspace_checkpoint")
                )
            if expected_pre != supplied_checkpoint.to_dict():
                return False, [
                    "FAIL  program workspace must match the exact prior checkpoint; "
                    "restore a failed attempt to its pre-checkpoint before retrying"
                ]
            if current_checkpoint != supplied_checkpoint:
                return False, [
                    "FAIL  program workspace changed between preflight and attempt claim"
                ]

            if state.get("started_at") is None:
                state["started_at"] = now
            state["status"] = "running"
            state["spawns_used"] = int(state.get("spawns_used", 0)) + 1
            state["turns_used"] = int(state.get("turns_used", 0)) + 1
            state["token_upper_bound_used"] = (
                int(state.get("token_upper_bound_used", 0)) + prompt_token_upper_bound
            )
            state["wall_clock_elapsed_seconds"] = _program_wave_elapsed_seconds(
                state, now
            )
            record = {
                "sequence": len(attempts) + 1,
                "unit_id": unit_id,
                "wave_id": wave_id,
                "provider": provider,
                "route": route,
                "dispatch_id": dispatch_id,
                "attempt": attempt,
                "required_capabilities": list(required),
                "attested_capabilities": list(attested),
                "status": "running",
                "claimed_at": now,
                "claim_commit": identity["commit"],
                "pre_workspace_checkpoint": supplied_checkpoint.to_dict(),
                "post_workspace_checkpoint": None,
                "changed_paths": [],
                "boundary_snapshot_digest": None,
                "evidence": [],
                "evidence_verifications": [],
                "output_sha256": None,
                "output_path": None,
                "output_artifact_sha256": None,
                "error": None,
                "token_upper_bound": prompt_token_upper_bound,
                "physical_boundary_containment": (
                    supplied_containment if containment_required else None
                ),
            }
            attempts.append(record)
            contract["current_wave"] = wave_id
            run["current_commit"] = identity["commit"]
            run["next"] = f"complete program unit {unit_id} attempt {attempt}"
            prospective_problem = _program_execution_problem(root, run)
            if prospective_problem:
                return False, [f"FAIL  {prospective_problem}"]
            _write_snapshot_locked(root, run)
        msgs.append(f"OK    program unit {unit_id!r} attempt {attempt} claimed")
        return True, msgs
    except TimeoutError as exc:
        return False, [f"FAIL  {exc}"]
    except (OSError, UnsafePathError, ValueError) as exc:
        return False, [f"FAIL  unsafe pipeline state mutation refused: {exc}"]


def _program_path_within_boundary(path: str, boundary: Mapping[str, Any]) -> bool:
    boundary_path = boundary.get("path")
    if not isinstance(boundary_path, str):
        return False
    if boundary.get("kind") == "file":
        return path == boundary_path
    return path == boundary_path or path.startswith(boundary_path + "/")


def finish_program_unit(
    target: str | Path,
    *,
    unit_id: str,
    dispatch_id: str,
    attempt: int,
    status: str,
    evidence: tuple[str, ...],
    evidence_verifications: Sequence[Mapping[str, Any]],
    output_sha256: str | None,
    output_path: str,
    output_artifact_sha256: str,
    error: str | None,
    post_workspace_checkpoint: Mapping[str, Any],
    changed_paths: tuple[str, ...],
    boundary_snapshot_digest: str,
    output_token_upper_bound: int,
) -> tuple[bool, list[str]]:
    """Terminalize one program attempt and enforce its exact write boundary."""

    if status not in TERMINAL_STAGE_STATUSES:
        return False, ["FAIL  program unit status must be terminal"]
    if (
        not isinstance(output_token_upper_bound, int)
        or isinstance(output_token_upper_bound, bool)
        or output_token_upper_bound < 0
    ):
        return False, ["FAIL  output token upper bound must be non-negative"]
    if not re.fullmatch(r"[0-9a-f]{64}", boundary_snapshot_digest):
        return False, ["FAIL  boundary snapshot digest must be lowercase sha256"]
    if output_sha256 is not None and not re.fullmatch(r"[0-9a-f]{64}", output_sha256):
        return False, ["FAIL  output digest must be lowercase sha256"]
    if (
        not isinstance(output_path, str)
        or not output_path
        or Path(output_path).is_absolute()
        or ".." in Path(output_path).parts
        or not re.fullmatch(r"[0-9a-f]{64}", output_artifact_sha256)
    ):
        return False, ["FAIL  terminal result artifact identity is malformed"]
    if (
        len(changed_paths) != len(set(changed_paths))
        or tuple(sorted(changed_paths)) != changed_paths
    ):
        return False, ["FAIL  changed paths must be unique and sorted"]
    for changed in changed_paths:
        candidate = Path(changed)
        if (
            not changed
            or candidate.is_absolute()
            or ".." in candidate.parts
            or candidate.as_posix() != changed
        ):
            return False, ["FAIL  changed path is not canonical and project-relative"]
    supplied_checkpoint, checkpoint_problem = _program_checkpoint(
        post_workspace_checkpoint, label="program post-dispatch workspace checkpoint"
    )
    if checkpoint_problem or supplied_checkpoint is None:
        return False, [f"FAIL  {checkpoint_problem}"]

    msgs: list[str] = []
    try:
        fs = ProjectFS(Path(target).expanduser())
        root = fs.root
        path = fs.path(_snapshot_rel(root))
    except (OSError, UnsafePathError, ValueError) as exc:
        return False, [f"FAIL  unsafe pipeline state path: {exc}"]
    try:
        with _pipeline_write_lock(fs, path, msgs=msgs):
            snap, load_error = _load_snapshot(root)
            if load_error:
                return False, [f"FAIL  {load_error}"]
            run, identity, problem = _active_v2_run(root, snap)
            if problem or run is None or identity is None:
                return False, [f"FAIL  {problem or 'invalid run'}"]
            contract = run.get("program_execution")
            if not isinstance(contract, dict):
                return False, ["FAIL  no frozen program execution contract exists"]
            attempts = contract.get("unit_attempts")
            units = contract.get("units")
            waves = contract.get("waves")
            states = contract.get("wave_states")
            if (
                not isinstance(attempts, list)
                or not isinstance(units, dict)
                or not isinstance(waves, dict)
                or not isinstance(states, dict)
            ):
                return False, ["FAIL  program execution ledger is malformed"]
            matches = [
                item
                for item in attempts
                if item.get("unit_id") == unit_id
                and item.get("dispatch_id") == dispatch_id
                and item.get("attempt") == attempt
            ]
            if len(matches) != 1 or matches[0].get("status") != "running":
                return False, ["FAIL  exact running program unit attempt was not found"]
            record = matches[0]
            unit = units.get(unit_id)
            if not isinstance(unit, dict):
                return False, ["FAIL  program unit contract is malformed"]
            effective_error = (
                error.strip() if isinstance(error, str) and error.strip() else None
            )
            candidate_record = dict(record)
            candidate_record.update(
                {
                    "status": status,
                    "post_workspace_checkpoint": supplied_checkpoint.to_dict(),
                    "changed_paths": list(changed_paths),
                    "boundary_snapshot_digest": boundary_snapshot_digest,
                    "evidence": list(evidence),
                    "evidence_verifications": [
                        dict(item) for item in evidence_verifications
                    ],
                    "output_sha256": output_sha256,
                    "output_path": output_path,
                    "output_artifact_sha256": output_artifact_sha256,
                    "error": effective_error,
                }
            )
            artifact_problem = _program_terminal_artifact_problem(
                root, run, contract, candidate_record
            )
            if artifact_problem:
                return False, [f"FAIL  {artifact_problem}"]
            current_checkpoint, workspace_problem = (
                _program_current_workspace_checkpoint(root, contract)
            )
            if workspace_problem or current_checkpoint is None:
                return False, [f"FAIL  {workspace_problem}"]
            if current_checkpoint != supplied_checkpoint:
                return False, [
                    "FAIL  supplied program post-checkpoint does not identify the workspace"
                ]
            before_checkpoint = record.get("pre_workspace_checkpoint")
            if not isinstance(before_checkpoint, dict):
                return False, ["FAIL  program attempt has no pre-checkpoint"]
            expected_boundary_digest = hashlib.sha256(
                json.dumps(
                    {
                        "before": before_checkpoint.get("content_digest"),
                        "after": supplied_checkpoint.content_digest,
                        "changed_paths": list(changed_paths),
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest()
            if boundary_snapshot_digest != expected_boundary_digest:
                return False, [
                    "FAIL  program boundary digest differs from the exact checkpoints"
                ]

            effective_status = status
            boundaries = unit.get("boundaries")
            if not isinstance(boundaries, list):
                return False, ["FAIL  program unit boundary contract is malformed"]
            boundary_violation = bool(changed_paths) and (
                unit.get("kind") in {"audit", "gate-runner"}
                or any(
                    not any(
                        isinstance(boundary, dict)
                        and _program_path_within_boundary(changed, boundary)
                        for boundary in boundaries
                    )
                    for changed in changed_paths
                )
            )
            if boundary_violation:
                effective_status = "failed"
                effective_error = (
                    "program worker changed files outside its exact boundary: "
                    + ", ".join(changed_paths)
                )
            required_evidence = {
                f"artifact://{item}" for item in unit.get("evidence", [])
            }
            if effective_status == "succeeded" and set(evidence) != required_evidence:
                missing = sorted(required_evidence - set(evidence))
                unexpected = sorted(set(evidence) - required_evidence)
                effective_status = "failed"
                effective_error = "required evidence was not returned: " + "; ".join(
                    part
                    for part in (
                        "missing " + ", ".join(missing) if missing else "",
                        "unexpected " + ", ".join(unexpected) if unexpected else "",
                    )
                    if part
                )
            verification_documents = [dict(item) for item in evidence_verifications]
            verification_ids = {
                item.get("artifact_id") for item in verification_documents
            }
            expected_verification_ids = {
                item.removeprefix("artifact://") for item in required_evidence
            }
            if effective_status == "succeeded" and (
                verification_ids != expected_verification_ids
                or len(verification_documents) != len(expected_verification_ids)
            ):
                effective_status = "failed"
                effective_error = (
                    "every declared evidence artifact requires one exact "
                    "content-addressed verification"
                )
            wave_id = unit.get("wave_id")
            wave = waves.get(wave_id)
            state = states.get(wave_id)
            if not isinstance(wave, dict) or not isinstance(state, dict):
                return False, ["FAIL  program wave state is malformed"]
            state["token_upper_bound_used"] = (
                int(state.get("token_upper_bound_used", 0)) + output_token_upper_bound
            )
            state["wall_clock_elapsed_seconds"] = _program_wave_elapsed_seconds(
                state, _utc_now()
            )
            budget = wave.get("budget")
            if not isinstance(budget, dict):
                return False, ["FAIL  program wave budget is malformed"]
            if state["token_upper_bound_used"] > budget.get("token_ceiling", 0):
                state["budget_exhausted"] = "token-ceiling"
                effective_status = "failed"
                effective_error = "program wave token ceiling was exceeded"
            if state["wall_clock_elapsed_seconds"] > budget.get(
                "wall_clock_seconds", 0
            ):
                state["budget_exhausted"] = "wall-clock"
                effective_status = "failed"
                effective_error = "program wave wall-clock budget was exceeded"

            if effective_status == "succeeded":
                normalized_verifications, normalization_problem = (
                    _normalize_program_safeguards(
                        fs,
                        run,
                        contract,
                        identity,
                        unit_id=unit_id,
                        records=verification_documents,
                        allow_attempt_evidence=True,
                    )
                )
                if normalization_problem or normalized_verifications is None:
                    effective_status = "failed"
                    effective_error = "program evidence verification failed: " + (
                        normalization_problem or "unknown verification error"
                    )
                    verification_documents = []
                else:
                    verification_documents = normalized_verifications
            else:
                verification_documents = []

            record.update(
                {
                    "status": effective_status,
                    "completed_at": _utc_now(),
                    "completion_commit": identity["commit"],
                    "post_workspace_checkpoint": supplied_checkpoint.to_dict(),
                    "changed_paths": list(changed_paths),
                    "boundary_snapshot_digest": boundary_snapshot_digest,
                    "evidence": list(evidence),
                    "evidence_verifications": verification_documents,
                    "output_sha256": output_sha256,
                    "output_path": output_path,
                    "output_artifact_sha256": output_artifact_sha256,
                    "error": effective_error,
                    "token_upper_bound": int(record["token_upper_bound"])
                    + output_token_upper_bound,
                }
            )
            completed = contract.get("completed_units")
            if not isinstance(completed, list):
                return False, ["FAIL  program completed-unit ledger is malformed"]
            if effective_status == "succeeded":
                succeeded = {
                    item.get("unit_id")
                    for item in attempts
                    if item.get("status") == "succeeded"
                }
                ordered_units = contract.get("ordered_units")
                if not isinstance(ordered_units, list):
                    return False, ["FAIL  program unit order is malformed"]
                contract["completed_units"] = [
                    item for item in ordered_units if item in succeeded
                ]
                completed = contract["completed_units"]
            wave_done = set(wave.get("unit_ids", [])).issubset(
                completed
            ) and not wave.get("gate_ids")
            if wave_done:
                state["status"] = "completed"
                state["completed_at"] = _utc_now()
                ordered_waves = contract.get("ordered_waves", [])
                next_index = ordered_waves.index(wave_id) + 1
                contract["current_wave"] = (
                    ordered_waves[next_index]
                    if next_index < len(ordered_waves)
                    else None
                )
            run["current_commit"] = identity["commit"]
            run["next"] = (
                f"continue after program unit {unit_id}"
                if effective_status == "succeeded"
                else f"retry or re-plan failed program unit {unit_id}"
            )
            prospective_problem = _program_execution_problem(root, run)
            if prospective_problem:
                return False, [f"FAIL  {prospective_problem}"]
            _write_snapshot_locked(root, run)
        msgs.append(
            f"OK    program unit {unit_id!r} attempt {attempt} recorded {effective_status}"
        )
        return effective_status == status, msgs
    except TimeoutError as exc:
        return False, [f"FAIL  {exc}"]
    except (OSError, UnsafePathError, ValueError) as exc:
        return False, [f"FAIL  unsafe pipeline state mutation refused: {exc}"]


def _normalize_program_safeguards(
    fs: ProjectFS,
    run: Mapping[str, Any],
    contract: dict[str, Any],
    identity: Mapping[str, str],
    *,
    unit_id: str,
    records: Sequence[Mapping[str, Any]],
    allow_attempt_evidence: bool,
) -> tuple[list[dict[str, Any]] | None, str | None]:
    """Validate and merge safeguard records into an in-memory locked snapshot."""

    ledger = contract.get("safeguard_verifications")
    binding = contract.get("binding")
    if not isinstance(ledger, list) or not isinstance(binding, dict):
        return None, "program safeguard ledger is malformed"
    normalized: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    aggregate_bytes = 0
    for supplied in records:
        record = dict(supplied)
        artifact_id = record.get("artifact_id")
        artifact_path = record.get("artifact_path")
        artifact_sha = record.get("artifact_sha256")
        kind = record.get("kind")
        details = record.get("details")
        if (
            not isinstance(artifact_id, str)
            or not _STAGE_ID_RE.fullmatch(artifact_id)
            or not isinstance(artifact_path, str)
            or not artifact_path
            or Path(artifact_path).is_absolute()
            or ".." in Path(artifact_path).parts
            or not isinstance(artifact_sha, str)
            or not re.fullmatch(r"[0-9a-f]{64}", artifact_sha)
            or kind
            not in {
                "manifest",
                "inventory",
                "restore-point",
                "approval-request",
                "approval-authorization",
                "evidence",
            }
            or (kind == "evidence" and not allow_attempt_evidence)
            or not isinstance(details, dict)
        ):
            return None, "program safeguard record is malformed"
        try:
            content, actual_sha, byte_count = _read_program_file_bounded(
                fs,
                artifact_path,
                maximum_bytes=_MAX_PROGRAM_SAFEGUARD_BYTES,
            )
        except (FileNotFoundError, OSError, UnsafePathError, ValueError) as exc:
            return None, f"program safeguard artifact is unavailable: {exc}"
        aggregate_bytes += byte_count
        if aggregate_bytes > _MAX_PROGRAM_SAFEGUARD_AGGREGATE_BYTES:
            return None, "program safeguard artifacts exceed the aggregate safety limit"
        if actual_sha != artifact_sha:
            return None, "program safeguard artifact digest mismatch"
        if kind == "evidence":
            evidence_requirements = contract.get("evidence_requirements")
            requirement = (
                evidence_requirements.get(artifact_id)
                if isinstance(evidence_requirements, dict)
                else None
            )
            if not isinstance(requirement, dict):
                return (
                    None,
                    "ordinary program evidence has no frozen workflow requirement",
                )
            evidence_problem = _program_evidence_document_problem(content, requirement)
            if evidence_problem:
                return None, evidence_problem
            pass_problem = _program_evidence_pass_problem(
                content,
                requirement,
                cast(Sequence[str], contract.get("program_blocking_severities", [])),
            )
            if pass_problem:
                return None, pass_problem
            if requirement.get("validation_profile") == "closeout-record":
                closeout_problem = _program_closeout_document_problem(
                    content, run, contract
                )
                if closeout_problem:
                    return None, closeout_problem
        full = {
            "run_id": run["run_id"],
            "manifest_digest": binding["manifest_digest"],
            "unit_id": unit_id,
            "kind": kind,
            "artifact_id": artifact_id,
            "artifact_path": artifact_path,
            "artifact_sha256": artifact_sha,
            "details": details,
            "verified_at": _utc_now(),
            "repository_commit": identity["commit"],
        }
        matches = [
            item
            for item in [*ledger, *pending]
            if isinstance(item, dict)
            and (
                item.get("unit_id"),
                item.get("kind"),
                item.get("artifact_id"),
            )
            == (unit_id, kind, artifact_id)
        ]
        if len(matches) > 1:
            return None, "program safeguard verification is ambiguous"
        if matches:
            comparable = dict(full)
            comparable["verified_at"] = matches[0].get("verified_at")
            if matches[0] != comparable:
                return None, "program safeguard verification conflicts"
            normalized.append(matches[0])
        else:
            pending.append(full)
            normalized.append(full)
    if len({item["artifact_id"] for item in normalized}) != len(normalized):
        return None, "program safeguard verification input contains duplicates"
    ledger.extend(pending)
    return normalized, None


def record_program_safeguards(
    target: str | Path,
    *,
    unit_id: str,
    records: Sequence[Mapping[str, Any]],
) -> tuple[bool, list[str]]:
    """Persist root-owned content-addressed safeguard verification records."""

    if not records:
        return True, ["OK    no program safeguards required"]
    msgs: list[str] = []
    try:
        fs = ProjectFS(Path(target).expanduser())
        root = fs.root
        path = fs.path(_snapshot_rel(root))
    except (OSError, UnsafePathError, ValueError) as exc:
        return False, [f"FAIL  unsafe pipeline state path: {exc}"]
    try:
        with _pipeline_write_lock(fs, path, msgs=msgs):
            snap, error = _load_snapshot(root)
            if error:
                return False, [f"FAIL  {error}"]
            run, identity, problem = _active_v2_run(root, snap)
            if problem or run is None or identity is None:
                return False, [f"FAIL  {problem or 'invalid run'}"]
            contract = run.get("program_execution")
            if not isinstance(contract, dict):
                return False, ["FAIL  no frozen program execution contract exists"]
            units = contract.get("units")
            if not isinstance(units, dict) or not isinstance(units.get(unit_id), dict):
                return False, [f"FAIL  unknown program unit {unit_id!r}"]
            _normalized, normalization_problem = _normalize_program_safeguards(
                fs,
                run,
                contract,
                identity,
                unit_id=unit_id,
                records=records,
                allow_attempt_evidence=False,
            )
            if normalization_problem:
                return False, [f"FAIL  {normalization_problem}"]
            prospective_problem = _program_execution_problem(root, run)
            if prospective_problem:
                return False, [f"FAIL  {prospective_problem}"]
            _write_snapshot_locked(root, run)
        msgs.append(f"OK    recorded {len(records)} program safeguard verification(s)")
        return True, msgs
    except TimeoutError as exc:
        return False, [f"FAIL  {exc}"]
    except (OSError, UnsafePathError, ValueError) as exc:
        return False, [f"FAIL  unsafe pipeline state mutation refused: {exc}"]


def checkpoint_program_gate(
    target: str | Path,
    *,
    gate_id: str,
    verification_records: Sequence[Mapping[str, Any]] = (),
) -> tuple[bool, list[str]]:
    """Checkpoint the next manifest gate after its dedicated owner succeeds."""

    msgs: list[str] = []
    try:
        fs = ProjectFS(Path(target).expanduser())
        root = fs.root
        path = fs.path(_snapshot_rel(root))
    except (OSError, UnsafePathError, ValueError) as exc:
        return False, [f"FAIL  unsafe pipeline state path: {exc}"]
    try:
        with _pipeline_write_lock(fs, path, msgs=msgs):
            snap, error = _load_snapshot(root)
            if error:
                return False, [f"FAIL  {error}"]
            run, identity, problem = _active_v2_run(root, snap)
            if problem or run is None or identity is None:
                return False, [f"FAIL  {problem or 'invalid run'}"]
            contract = run.get("program_execution")
            if not isinstance(contract, dict):
                return False, ["FAIL  no frozen program execution contract exists"]
            ordered = contract.get("ordered_program_gates")
            checkpoints = contract.get("gate_checkpoints")
            gates = contract.get("gates")
            attempts = contract.get("unit_attempts")
            states = contract.get("wave_states")
            waves = contract.get("waves")
            if (
                not isinstance(ordered, list)
                or not isinstance(checkpoints, list)
                or not isinstance(gates, dict)
                or not isinstance(states, dict)
                or not isinstance(waves, dict)
                or not isinstance(attempts, list)
            ):
                return False, ["FAIL  program gate ledger is malformed"]
            position = len(checkpoints)
            if position >= len(ordered) or ordered[position] != gate_id:
                expected = ordered[position] if position < len(ordered) else "(none)"
                return False, [
                    f"FAIL  next program gate is {expected!r}, not {gate_id!r}"
                ]
            gate = gates.get(gate_id)
            if not isinstance(gate, dict):
                return False, ["FAIL  program gate contract is malformed"]
            owner = gate.get("owner_unit_id")
            owner_attempts = [
                item
                for item in attempts
                if item.get("unit_id") == owner and item.get("status") == "succeeded"
            ]
            if len(owner_attempts) != 1:
                return False, [
                    f"FAIL  program gate {gate_id!r} requires one successful owner {owner!r}"
                ]
            owner_attempt = owner_attempts[0]
            required_evidence = {
                f"artifact://{item}" for item in gate.get("evidence", [])
            }
            if not required_evidence.issubset(owner_attempt.get("evidence", [])):
                return False, [
                    "FAIL  program gate owner did not return required evidence"
                ]
            if gate.get("kind") == "pipeline" and gate_id not in _resolved_gate_names(
                run, list(run["ordered_gates"])
            ):
                return False, [
                    f"FAIL  pipeline gate {gate_id!r} must be resolved in the authoritative "
                    "pipeline ledger first"
                ]
            current, workspace_problem = _program_current_workspace_checkpoint(
                root, contract
            )
            if workspace_problem or current is None:
                return False, [f"FAIL  {workspace_problem}"]
            if owner_attempt.get("post_workspace_checkpoint") != current.to_dict():
                return False, [
                    f"FAIL  program workspace changed after gate owner {owner!r} completed"
                ]
            records = [dict(record) for record in verification_records]
            gate_evidence = set(gate.get("evidence", []))
            if {record.get("artifact_id") for record in records} != gate_evidence:
                return False, [
                    "FAIL  every program gate evidence item requires one exact "
                    "content-addressed verification"
                ]
            owner_verifications = owner_attempt.get("evidence_verifications")
            if not isinstance(owner_verifications, list):
                return False, ["FAIL  program gate owner evidence ledger is malformed"]
            owner_by_id = {
                item.get("artifact_id"): item
                for item in owner_verifications
                if isinstance(item, dict)
            }
            if any(owner_by_id.get(item["artifact_id"]) != item for item in records):
                return False, [
                    "FAIL  program gate evidence differs from its successful owner attempt"
                ]
            checkpoint = {
                "gate_id": gate_id,
                "status": "passed",
                "kind": gate.get("kind"),
                "wave_id": gate.get("wave_id"),
                "owner_unit_id": owner,
                "owner_dispatch_id": owner_attempt.get("dispatch_id"),
                "owner_attempt": owner_attempt.get("attempt"),
                "provider": owner_attempt.get("provider"),
                "route": owner_attempt.get("route"),
                "evidence": list(gate.get("evidence", [])),
                "verification_records": records,
                "workspace_checkpoint": current.to_dict(),
                "recorded_at": _utc_now(),
                "repository_commit": identity["commit"],
            }
            checkpoints.append(checkpoint)
            wave_id = gate.get("wave_id")
            wave = waves.get(wave_id)
            state = states.get(wave_id)
            if not isinstance(wave, dict) or not isinstance(state, dict):
                return False, ["FAIL  program gate wave is malformed"]
            resolved_ids = {item.get("gate_id") for item in checkpoints}
            if set(wave.get("gate_ids", [])).issubset(resolved_ids):
                state["status"] = "completed"
                state["completed_at"] = _utc_now()
                ordered_waves = contract.get("ordered_waves", [])
                next_index = ordered_waves.index(wave_id) + 1
                contract["current_wave"] = (
                    ordered_waves[next_index]
                    if next_index < len(ordered_waves)
                    else None
                )
            ordered_waves = contract.get("ordered_waves")
            if not isinstance(ordered_waves, list) or len(ordered_waves) < 2:
                return False, ["FAIL  program audit-wave order is malformed"]
            audit_wave = waves.get(ordered_waves[1])
            if not isinstance(audit_wave, dict):
                return False, ["FAIL  program audit wave is malformed"]
            audit_gate_ids = set(audit_wave["gate_ids"])
            contract["audit_gate_completed"] = audit_gate_ids.issubset(resolved_ids)
            run["current_commit"] = identity["commit"]
            run["next"] = f"continue after program gate {gate_id}"
            prospective_problem = _program_execution_problem(root, run)
            if prospective_problem:
                return False, [f"FAIL  {prospective_problem}"]
            _write_snapshot_locked(root, run)
        msgs.append(f"OK    program gate {gate_id!r} checkpointed")
        return True, msgs
    except TimeoutError as exc:
        return False, [f"FAIL  {exc}"]
    except (OSError, UnsafePathError, ValueError) as exc:
        return False, [f"FAIL  unsafe pipeline state mutation refused: {exc}"]


def complete_program_execution(target: str | Path) -> tuple[bool, list[str]]:
    """Persist terminal Mode E completion without completing the outer pipeline."""

    msgs: list[str] = []
    try:
        fs = ProjectFS(Path(target).expanduser())
        root = fs.root
        path = fs.path(_snapshot_rel(root))
    except (OSError, UnsafePathError, ValueError) as exc:
        return False, [f"FAIL  unsafe pipeline state path: {exc}"]
    try:
        with _pipeline_write_lock(fs, path, msgs=msgs):
            snap, error = _load_snapshot(root)
            if error:
                return False, [f"FAIL  {error}"]
            run, identity, problem = _active_v2_run(root, snap)
            if problem or run is None or identity is None:
                return False, [f"FAIL  {problem or 'invalid run'}"]
            contract = run.get("program_execution")
            if not isinstance(contract, dict):
                return False, ["FAIL  no frozen program execution contract exists"]
            if contract.get("completed_units") != contract.get("ordered_units"):
                return False, ["FAIL  program execution still has unresolved units"]
            checkpoints = contract.get("gate_checkpoints")
            if not isinstance(checkpoints, list) or [
                item.get("gate_id") for item in checkpoints
            ] != contract.get("ordered_program_gates"):
                return False, ["FAIL  program execution still has unresolved gates"]
            unresolved_pipeline = set(run["ordered_gates"]) - set(
                _resolved_gate_names(run, list(run["ordered_gates"]))
            )
            if unresolved_pipeline:
                return False, [
                    "FAIL  selected pipeline gates remain unresolved: "
                    + ", ".join(sorted(unresolved_pipeline))
                ]
            current_checkpoint, workspace_problem = (
                _program_current_workspace_checkpoint(root, contract)
            )
            if workspace_problem or current_checkpoint is None:
                return False, [f"FAIL  {workspace_problem}"]
            attempts = contract.get("unit_attempts")
            succeeded_attempts = (
                []
                if not isinstance(attempts, list)
                else [
                    item
                    for item in attempts
                    if isinstance(item, dict) and item.get("status") == "succeeded"
                ]
            )
            if (
                not succeeded_attempts
                or succeeded_attempts[-1].get("post_workspace_checkpoint")
                != current_checkpoint.to_dict()
            ):
                return False, [
                    "FAIL  program workspace changed after the final successful unit"
                ]
            contract["status"] = "completed"
            contract["completed_at"] = _utc_now()
            contract["completion_workspace_checkpoint"] = current_checkpoint.to_dict()
            contract["completion_workflow_definition_digest"] = contract["binding"][
                "workflow_definition_digest"
            ]
            contract["completion_state_digest"] = _program_completion_digest(contract)
            contract["current_wave"] = None
            run["current_commit"] = identity["commit"]
            run["next"] = "complete the outer pipeline run"
            prospective_problem = _program_execution_problem(root, run)
            if prospective_problem:
                return False, [f"FAIL  {prospective_problem}"]
            _write_snapshot_locked(root, run)
        msgs.append("OK    program execution completion persisted")
        return True, msgs
    except TimeoutError as exc:
        return False, [f"FAIL  {exc}"]
    except (OSError, UnsafePathError, ValueError) as exc:
        return False, [f"FAIL  unsafe pipeline state mutation refused: {exc}"]


def claim_stage(
    target: str | Path,
    *,
    stage: str,
    role: str,
    provider: str,
    dispatch_id: str,
    attempt: int,
    required_capabilities: tuple[str, ...] = (),
    attested_capabilities: tuple[str, ...] = (),
) -> tuple[bool, list[str]]:
    """Atomically reserve one stage before its host prompt is submitted.

    The reservation is the cross-runtime duplicate-execution boundary. A
    succeeded or currently running stage cannot be claimed again. Provider and
    capability attestations are frozen into the record before execution.
    """
    for label, value in (("stage", stage), ("role", role), ("provider", provider)):
        if not isinstance(value, str) or not _STAGE_ID_RE.fullmatch(value):
            return False, [f"FAIL  {label} must be a contained identifier"]
    if not isinstance(dispatch_id, str) or not dispatch_id.strip():
        return False, ["FAIL  dispatch_id must be non-empty"]
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
        return False, ["FAIL  dispatch attempt must be a positive integer"]
    try:
        required = _stage_capabilities(
            required_capabilities, field_name="required_capabilities"
        )
        attested = _stage_capabilities(
            attested_capabilities, field_name="attested_capabilities"
        )
    except ValueError as exc:
        return False, [f"FAIL  {exc}"]
    missing = sorted(set(required) - set(attested))
    if missing:
        return False, [
            "FAIL  unsupported required capabilities cannot be attested: "
            + ", ".join(missing)
        ]

    msgs: list[str] = []
    try:
        fs = ProjectFS(Path(target).expanduser())
        path = fs.path(_snapshot_rel(target))
    except (UnsafePathError, OSError, ValueError) as exc:
        return False, [f"FAIL  unsafe pipeline state path: {exc}"]
    try:
        with _pipeline_write_lock(fs, path, msgs=msgs):
            snap, error = _load_snapshot(target)
            if error:
                return False, [f"FAIL  {error}"]
            run, identity, problem = _active_v2_run(target, snap)
            if problem or run is None or identity is None:
                return False, [f"FAIL  {problem or 'invalid run'}"]
            raw_history = run.setdefault("stage_history", [])
            if not isinstance(raw_history, list) or any(
                not isinstance(item, dict) for item in raw_history
            ):
                return False, ["FAIL  stage_history ledger is malformed"]
            history = cast(list[dict[str, Any]], raw_history)
            raw_skips = run.get("skipped_stage_history", [])
            if not isinstance(raw_skips, list) or any(
                not isinstance(item, dict) for item in raw_skips
            ):
                return False, ["FAIL  skipped_stage_history ledger is malformed"]
            skips = cast(list[dict[str, Any]], raw_skips)
            contract = run.get("managed_execution")
            route_id: str | None = None
            if isinstance(contract, dict):
                active_stages = contract.get("active_stages")
                requirements = contract.get("active_stage_requirements")
                routes = contract.get("active_stage_routes")
                dependencies = contract.get("active_stage_dependencies")
                providers = contract.get("providers")
                if (
                    not isinstance(active_stages, list)
                    or stage not in active_stages
                    or not isinstance(requirements, dict)
                    or not isinstance(requirements.get(stage), list)
                    or not isinstance(routes, dict)
                    or not isinstance(routes.get(stage), dict)
                    or not isinstance(dependencies, dict)
                    or not isinstance(dependencies.get(stage), list)
                ):
                    return False, [
                        f"FAIL  stage {stage!r} is outside the frozen managed graph"
                    ]
                route_contract = cast(dict[str, Any], routes[stage])
                if route_contract.get("execution_kind") == "typed-external-action":
                    return False, [
                        f"FAIL  typed external-action stage {stage!r} cannot be "
                        "claimed through a native role"
                    ]
                route_id_value = route_contract.get("route")
                canonical_role = route_contract.get("role")
                if not isinstance(route_id_value, str) or role != canonical_role:
                    return False, [
                        f"FAIL  stage {stage!r} must use its frozen canonical role "
                        f"{canonical_role!r} for route {route_id_value!r}"
                    ]
                route_id = route_id_value
                if not isinstance(providers, list) or provider not in providers:
                    return False, [
                        f"FAIL  provider {provider!r} is outside the frozen managed provider set"
                    ]
                expected_required = tuple(str(item) for item in requirements[stage])
                if required != expected_required:
                    return False, [
                        "FAIL  dispatch claim capabilities differ from the frozen "
                        f"role/stage contract: expected {list(expected_required)!r}"
                    ]
                if attested != expected_required:
                    return False, [
                        "FAIL  dispatch capability attestation differs from the frozen "
                        f"role/stage contract: expected {list(expected_required)!r}"
                    ]
                stage_condition = (
                    _current_workflow_definition().stage_by_id[stage].condition
                )
                condition_decisions = run.get("condition_decisions")
                if (
                    isinstance(condition_decisions, dict)
                    and condition_decisions.get(stage_condition) is False
                ):
                    return False, [
                        f"FAIL  stage {stage!r} cannot be claimed because frozen "
                        f"condition {stage_condition!r} is false"
                    ]
                active_set = set(str(item) for item in active_stages)
                for dependency in dependencies[stage]:
                    if dependency not in active_set:
                        continue
                    successful = [
                        item
                        for item in history
                        if item.get("stage") == dependency
                        and item.get("status") == "succeeded"
                    ]
                    skipped_records = [
                        item for item in skips if item.get("stage") == dependency
                    ]
                    if len(successful) == 1 and not skipped_records:
                        continue
                    if len(skipped_records) == 1 and not successful:
                        skip_problem = _managed_skip_attestation_problem(
                            run, skipped_records[0]
                        )
                        if skip_problem is None:
                            continue
                    return False, [
                        f"FAIL  dependency {dependency!r} is not authoritatively "
                        f"settled before stage {stage!r}"
                    ]
                current_checkpoint, checkpoint_problem = _managed_workspace_checkpoint(
                    fs.root, run
                )
                if checkpoint_problem or current_checkpoint is None:
                    return False, [
                        "FAIL  "
                        + (
                            checkpoint_problem
                            or "managed pre-attempt workspace checkpoint is unavailable"
                        )
                    ]
                prior_stage_attempts = [
                    item for item in history if item.get("stage") == stage
                ]
                if any(
                    item.get("status") == "failed"
                    and bool(item.get("evidence_records"))
                    for item in prior_stage_attempts
                ):
                    return False, [
                        f"FAIL  stage {stage!r} has unresolved authoritative typed "
                        "evidence; abort or re-plan instead of erasing it with a retry"
                    ]
                if prior_stage_attempts and prior_stage_attempts[-1].get("status") in {
                    "failed",
                    "cancelled",
                }:
                    expected_pre = prior_stage_attempts[-1].get(
                        "workspace_checkpoint_before"
                    )
                    if expected_pre != current_checkpoint.to_dict():
                        return False, [
                            f"FAIL  workspace changed during failed stage {stage!r}; "
                            "restore its exact pre-attempt checkpoint before retrying"
                        ]
                workspace_checkpoint_before: dict[str, Any] | None = (
                    current_checkpoint.to_dict()
                )
            else:
                workspace_checkpoint_before = None
            if any(
                isinstance(item, dict) and item.get("stage") == stage for item in skips
            ):
                return False, [
                    f"FAIL  stage {stage!r} is durably skipped and cannot be dispatched"
                ]
            prior = [item for item in history if item.get("stage") == stage]
            if any(item.get("status") == "succeeded" for item in prior):
                return False, [
                    f"FAIL  stage {stage!r} is already completed and cannot run twice"
                ]
            if any(item.get("status") == "running" for item in prior):
                return False, [f"FAIL  stage {stage!r} already has a running attempt"]
            stage_attempt = len(prior) + 1
            history.append(
                {
                    "stage": stage,
                    "status": "running",
                    "route": route_id,
                    "role": role,
                    "provider": provider,
                    "dispatch_id": dispatch_id.strip(),
                    "attempt": stage_attempt,
                    "dispatch_attempt": attempt,
                    "required_capabilities": list(required),
                    "attested_capabilities": list(attested),
                    "workspace_checkpoint_before": workspace_checkpoint_before,
                    "started_at": _utc_now(),
                    "repository_commit": identity["commit"],
                }
            )
            run["next"] = f"finish stage {stage} attempt {stage_attempt}"
            run["current_commit"] = identity["commit"]
            _write_snapshot_locked(target, run)
        msgs.append(
            f"OK    claimed stage {stage!r} attempt {stage_attempt} on {provider}"
        )
        return True, msgs
    except TimeoutError as exc:
        return False, [f"FAIL  {exc}"]
    except (UnsafePathError, OSError, ValueError) as exc:
        return False, [f"FAIL  unsafe pipeline state mutation refused: {exc}"]


def finish_stage(
    target: str | Path,
    *,
    stage: str,
    dispatch_id: str,
    attempt: int,
    status: str,
    output_sha256: str | None = None,
    output_path: str | None = None,
    output_artifact_sha256: str | None = None,
    workspace_checkpoint: Mapping[str, Any] | None = None,
    evidence: tuple[str, ...] = (),
    evidence_records: Sequence[Mapping[str, Any]] | None = None,
    error: str | None = None,
) -> tuple[bool, list[str]]:
    """Finish the exact running stage attempt without allowing a second result."""
    if status not in TERMINAL_STAGE_STATUSES:
        return False, [
            f"FAIL  terminal stage status must be one of {sorted(TERMINAL_STAGE_STATUSES)}"
        ]
    if not _STAGE_ID_RE.fullmatch(stage):
        return False, ["FAIL  stage must be a contained identifier"]
    if not dispatch_id.strip():
        return False, ["FAIL  dispatch_id must be non-empty"]
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
        return False, ["FAIL  dispatch attempt must be a positive integer"]
    if output_sha256 is not None and not re.fullmatch(r"[0-9a-f]{64}", output_sha256):
        return False, ["FAIL  output_sha256 must be a lowercase sha256 digest"]
    if output_path is not None and (
        not isinstance(output_path, str)
        or not output_path
        or Path(output_path).is_absolute()
        or ".." in Path(output_path).parts
    ):
        return False, ["FAIL  output_path must be a contained project-relative path"]
    if output_artifact_sha256 is not None and not re.fullmatch(
        r"[0-9a-f]{64}", output_artifact_sha256
    ):
        return False, ["FAIL  output_artifact_sha256 must be a lowercase sha256 digest"]
    supplied_checkpoint: WorkspaceCheckpoint | None = None
    if workspace_checkpoint is not None:
        try:
            supplied_checkpoint = WorkspaceCheckpoint.from_dict(
                dict(workspace_checkpoint)
            )
        except (TypeError, WorktreeError) as exc:
            return False, [f"FAIL  invalid workspace checkpoint: {exc}"]
    if isinstance(evidence, (str, bytes)) or any(
        not isinstance(item, str) or not item.strip() for item in evidence
    ):
        return False, ["FAIL  stage evidence must be non-empty reference strings"]
    if len(set(evidence)) != len(evidence):
        return False, ["FAIL  stage evidence must not contain duplicates"]
    if evidence_records is not None and (
        isinstance(evidence_records, (str, bytes))
        or any(not isinstance(item, Mapping) for item in evidence_records)
    ):
        return False, ["FAIL  managed evidence records must be structured objects"]
    if status in {"failed", "cancelled"} and not (error and error.strip()):
        return False, [f"FAIL  {status} stage result requires an error"]

    msgs: list[str] = []
    try:
        fs = ProjectFS(Path(target).expanduser())
        path = fs.path(_snapshot_rel(target))
    except (UnsafePathError, OSError, ValueError) as exc:
        return False, [f"FAIL  unsafe pipeline state path: {exc}"]
    try:
        with _pipeline_write_lock(fs, path, msgs=msgs):
            snap, load_error = _load_snapshot(target)
            if load_error:
                return False, [f"FAIL  {load_error}"]
            run, identity, problem = _active_v2_run(target, snap)
            if problem or run is None or identity is None:
                return False, [f"FAIL  {problem or 'invalid run'}"]
            current_checkpoint, checkpoint_problem = _managed_workspace_checkpoint(
                fs.root, run
            )
            if checkpoint_problem:
                return False, [f"FAIL  {checkpoint_problem}"]
            if run.get("managed_execution") is not None:
                if supplied_checkpoint is None:
                    return False, [
                        "FAIL  managed stage result has no workspace checkpoint"
                    ]
                if current_checkpoint != supplied_checkpoint:
                    return False, [
                        "FAIL  managed workspace changed between stage capture and ledger finish"
                    ]
            elif supplied_checkpoint is not None:
                return False, [
                    "FAIL  unmanaged stage result cannot attach a managed workspace checkpoint"
                ]
            artifact_document: dict[str, Any] | None = None
            if output_path is not None:
                if output_artifact_sha256 is None:
                    return False, ["FAIL  stage output artifact has no content digest"]
                try:
                    artifact_bytes, actual_artifact_sha, _artifact_size = (
                        _read_managed_file_bounded(
                            fs,
                            output_path,
                            maximum_bytes=_MAX_MANAGED_OUTPUT_ARTIFACT_BYTES,
                        )
                    )
                except (FileNotFoundError, UnsafePathError, OSError, ValueError) as exc:
                    return False, [f"FAIL  stage output artifact is unavailable: {exc}"]
                if actual_artifact_sha != output_artifact_sha256:
                    return False, ["FAIL  stage output artifact hash mismatch"]
                if run.get("managed_execution") is not None:
                    try:
                        decoded_artifact = json.loads(artifact_bytes)
                    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                        return False, [
                            f"FAIL  managed stage output artifact is malformed: {exc}"
                        ]
                    if not isinstance(decoded_artifact, dict):
                        return False, [
                            "FAIL  managed stage output artifact must be an object"
                        ]
                    artifact_document = decoded_artifact
            raw_history = run.get("stage_history", [])
            if not isinstance(raw_history, list) or any(
                not isinstance(item, dict) for item in raw_history
            ):
                return False, ["FAIL  stage_history ledger is malformed"]
            matches = [
                item
                for item in raw_history
                if item.get("stage") == stage
                and item.get("dispatch_id") == dispatch_id
                and item.get("dispatch_attempt") == attempt
            ]
            if len(matches) != 1:
                return False, ["FAIL  exact running stage attempt was not found"]
            record = matches[0]
            if record.get("status") != "running":
                return False, [
                    f"FAIL  stage {stage!r} attempt is already {record.get('status')!r}"
                ]
            required = record.get("required_capabilities")
            attested = record.get("attested_capabilities")
            if not isinstance(required, list) or not isinstance(attested, list):
                return False, ["FAIL  stage capability attestation is malformed"]
            if status == "succeeded" and not set(required).issubset(attested):
                return False, [
                    "FAIL  unsupported required capabilities cannot be marked succeeded"
                ]
            managed = run.get("managed_execution") is not None
            if managed:
                if (
                    output_path is None
                    or output_artifact_sha256 is None
                    or artifact_document is None
                ):
                    return False, [
                        "FAIL  managed terminal result has no authenticated output artifact"
                    ]
                expected_output_path = _managed_dispatch_artifact_relative(
                    str(run.get("run_id")),
                    stage,
                    cast(int, record.get("attempt")),
                    output_artifact_sha256,
                    layout=_state_layout(fs.root),
                )
                if output_path != expected_output_path:
                    return False, [
                        "FAIL  managed terminal result artifact belongs to another "
                        "run, stage, or ledger attempt"
                    ]
                try:
                    artifact_info = fs.path(output_path).lstat()
                except (FileNotFoundError, OSError, UnsafePathError, ValueError) as exc:
                    return False, [
                        f"FAIL  managed terminal result artifact is unavailable: {exc}"
                    ]
                if (
                    not stat.S_ISREG(artifact_info.st_mode)
                    or stat.S_IMODE(artifact_info.st_mode) != 0o600
                ):
                    return False, [
                        "FAIL  managed terminal result artifact must be a 0600 regular file"
                    ]
            managed_findings: list[dict[str, Any]] = []
            managed_counts = {key: 0 for key in FINDING_KEYS}
            has_typed_evidence = bool(evidence_records)
            if managed and (status == "succeeded" or has_typed_evidence):
                if (
                    output_sha256 is None
                    or output_path is None
                    or artifact_document is None
                ):
                    return False, [
                        "FAIL  successful managed stage has no authenticated output artifact"
                    ]
                evidence_problem, managed_findings, managed_counts = (
                    _managed_stage_evidence_problem(
                        fs,
                        run,
                        stage=stage,
                        dispatch_id=dispatch_id,
                        dispatch_attempt=attempt,
                        output_sha256=output_sha256,
                        records=evidence_records,
                        require_pass=status == "succeeded",
                    )
                )
                if evidence_problem:
                    return False, [f"FAIL  {evidence_problem}"]
            if managed:
                if artifact_document is None:  # pragma: no cover - guarded above
                    return False, ["FAIL  managed terminal artifact was lost"]
                artifact_output = artifact_document.get("output")
                if output_sha256 is None:
                    if artifact_output is not None:
                        return False, [
                            "FAIL  managed output artifact has unbound output content"
                        ]
                elif (
                    not isinstance(artifact_output, str)
                    or hashlib.sha256(artifact_output.encode("utf-8")).hexdigest()
                    != output_sha256
                ):
                    return False, [
                        "FAIL  managed output artifact output hash differs from the stage result"
                    ]
                expected_artifact = {
                    "schema_version": 1,
                    "run_id": run.get("run_id"),
                    "stage": stage,
                    "ledger_attempt": record.get("attempt"),
                    "provider": record.get("provider"),
                    "route": record.get("role"),
                    "dispatch_id": dispatch_id,
                    "dispatch_attempt": attempt,
                    "status": status,
                    "output": artifact_output,
                    "error": error.strip() if error else None,
                    "evidence": list(evidence),
                    "evidence_records": [
                        dict(item) for item in (evidence_records or ())
                    ],
                    "workspace_checkpoint": supplied_checkpoint.to_dict()
                    if supplied_checkpoint is not None
                    else None,
                }
                if artifact_document != expected_artifact:
                    return False, [
                        "FAIL  managed output artifact differs from the exact stage result"
                    ]
            record.update(
                {
                    "status": status,
                    "completed_at": _utc_now(),
                    "completion_commit": identity["commit"],
                    "output_sha256": output_sha256,
                    "output_path": output_path,
                    "output_artifact_sha256": output_artifact_sha256,
                    "workspace_checkpoint": (
                        supplied_checkpoint.to_dict()
                        if supplied_checkpoint is not None
                        else None
                    ),
                    "evidence": list(evidence),
                    "evidence_records": (
                        [dict(item) for item in (evidence_records or ())]
                        if managed
                        else []
                    ),
                    "findings": managed_findings,
                    "finding_counts": managed_counts,
                    "error": error.strip() if error else None,
                }
            )
            run["current_commit"] = identity["commit"]
            run["next"] = (
                f"continue after completed stage {stage}"
                if status == "succeeded"
                else f"retry or re-plan failed stage {stage}"
            )
            _write_snapshot_locked(target, run)
        msgs.append(f"OK    stage {stage!r} attempt recorded {status}")
        return True, msgs
    except TimeoutError as exc:
        return False, [f"FAIL  {exc}"]
    except (UnsafePathError, OSError, ValueError) as exc:
        return False, [f"FAIL  unsafe pipeline state mutation refused: {exc}"]


def _copy_stale_attempt_evidence(
    fs: ProjectFS, evidence: str | Path
) -> tuple[str, str]:
    """Copy operator evidence into the root-owned, content-addressed artifact store."""

    raw = Path(evidence).expanduser()
    source = (raw if raw.is_absolute() else fs.root / raw).resolve(strict=True)
    try:
        relative = source.relative_to(fs.root).as_posix()
    except ValueError as exc:
        raise ValueError(
            "stale-attempt reconciliation evidence must be inside the source project"
        ) from exc
    data, digest, _byte_count = _read_program_file_bounded(
        fs, relative, maximum_bytes=_MAX_PROGRAM_ARTIFACT_BYTES
    )
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", source.name).strip("-.")
    safe_name = safe_name[:80] or "operator-evidence.bin"
    layout = _state_layout(fs.root)
    stored = f"{layout.artifacts}/reconciliation/{digest}-{safe_name}"
    fs.write_bytes(stored, data, mode=0o600)
    return stored, digest


def _reconcile_stale_stage_attempt_under_lease(
    target: str | Path,
    *,
    stage: str,
    dispatch_id: str,
    reconciled_by: str,
    evidence: str | Path,
) -> tuple[bool, list[str]]:
    """Terminalize one provably side-effect-free orphaned claim under the lease."""

    if not _STAGE_ID_RE.fullmatch(stage):
        return False, ["FAIL  stage must be a contained identifier"]
    if not isinstance(dispatch_id, str) or not dispatch_id.strip():
        return False, ["FAIL  dispatch_id must be non-empty"]
    if not isinstance(reconciled_by, str) or not reconciled_by.strip():
        return False, ["FAIL  reconciled_by must identify the operator"]
    operator = reconciled_by.strip()
    if len(operator.encode("utf-8")) > 256:
        return False, ["FAIL  reconciled_by exceeds the 256-byte safety limit"]

    msgs: list[str] = []
    try:
        fs = ProjectFS(Path(target).expanduser())
        path = fs.path(_snapshot_rel(target))
    except (UnsafePathError, OSError, ValueError) as exc:
        return False, [f"FAIL  unsafe pipeline state path: {exc}"]
    try:
        with _pipeline_write_lock(fs, path, msgs=msgs):
            snap, load_error = _load_snapshot(target)
            if load_error:
                return False, [f"FAIL  {load_error}"]
            run, identity, problem = _active_v2_run(target, snap)
            if problem or run is None or identity is None:
                return False, [f"FAIL  {problem or 'invalid run'}"]
            contract = run.get("managed_execution")
            if not isinstance(contract, dict):
                return False, [
                    "FAIL  stale-attempt reconciliation is available only for a "
                    "frozen managed workflow"
                ]
            raw_history = run.get("stage_history", [])
            if not isinstance(raw_history, list) or any(
                not isinstance(item, dict) for item in raw_history
            ):
                return False, ["FAIL  stage_history ledger is malformed"]
            matches = [
                item
                for item in raw_history
                if item.get("stage") == stage
                and item.get("dispatch_id") == dispatch_id.strip()
            ]
            if len(matches) != 1 or matches[0].get("status") != "running":
                return False, ["FAIL  exact stale running stage attempt was not found"]
            record = matches[0]
            if record.get("provider") != "claude":
                return False, [
                    "FAIL  stale-attempt reconciliation is unsupported for this provider; "
                    "only a Claude claim with an enforced exact no-shell tool contract is "
                    "eligible"
                ]
            routes = contract.get("active_stage_routes")
            route = routes.get(stage) if isinstance(routes, dict) else None
            if not isinstance(route, dict):
                return False, ["FAIL  stale attempt has no frozen route contract"]
            raw_required = record.get("required_capabilities")
            if not isinstance(raw_required, list):
                return False, [
                    "FAIL  stale attempt required_capabilities must be an array"
                ]
            try:
                required = _stage_capabilities(
                    raw_required,
                    field_name="stale attempt required_capabilities",
                )
            except (TypeError, ValueError) as exc:
                return False, [f"FAIL  {exc}"]
            forbidden = sorted(set(required) & _STALE_ATTEMPT_FORBIDDEN_CAPABILITIES)
            if (
                forbidden
                or route.get("permission") != "read_only"
                or route.get("write_scope") != []
                or route.get("nested_delegation") != "forbidden"
            ):
                rendered = ", ".join(forbidden) or "non-read-only route semantics"
                return False, [
                    "FAIL  stale attempt cannot be reconciled because its frozen role "
                    f"may have side effects ({rendered}); abort and investigate manually"
                ]
            current, checkpoint_problem = _managed_workspace_checkpoint(fs.root, run)
            if checkpoint_problem or current is None:
                return False, [
                    "FAIL  "
                    + (
                        checkpoint_problem
                        or "managed workspace checkpoint is unavailable"
                    )
                ]
            before = record.get("workspace_checkpoint_before")
            if before != current.to_dict():
                return False, [
                    "FAIL  managed workspace changed after the stale attempt was claimed; "
                    "automatic reconciliation is forbidden"
                ]
            try:
                evidence_path, evidence_sha256 = _copy_stale_attempt_evidence(
                    fs, evidence
                )
            except (FileNotFoundError, UnsafePathError, OSError, ValueError) as exc:
                return False, [f"FAIL  invalid reconciliation evidence: {exc}"]

            reconciled_at = _utc_now()
            reconciliation = {
                "schema_version": 1,
                "kind": "operator-stale-attempt-reconciliation",
                "run_id": run["run_id"],
                "stage": stage,
                "dispatch_id": dispatch_id.strip(),
                "dispatch_attempt": record["dispatch_attempt"],
                "reason": "coordinator-crash",
                "reconciled_by": operator,
                "reconciled_at": reconciled_at,
                "evidence_path": evidence_path,
                "evidence_sha256": evidence_sha256,
                "workspace_head_commit": current.head_commit,
                "workspace_content_digest": current.content_digest,
                "provider_control_surface_digest": contract[
                    "provider_control_surface_digest"
                ],
                "workflow_definition_digest": contract["workflow_definition_digest"],
            }
            artifact = (
                json.dumps(
                    reconciliation,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )
                + "\n"
            ).encode("utf-8")
            layout = _state_layout(fs.root)
            artifact_sha256 = hashlib.sha256(artifact).hexdigest()
            artifact_path = _managed_reconciliation_artifact_relative(
                str(run["run_id"]),
                stage,
                cast(int, record["attempt"]),
                artifact_sha256,
                layout=layout,
            )
            try:
                existing, _existing_sha, _existing_size = _read_managed_file_bounded(
                    fs, artifact_path, maximum_bytes=len(artifact)
                )
            except FileNotFoundError:
                fs.write_bytes(artifact_path, artifact, mode=0o600)
                existing, _existing_sha, _existing_size = _read_managed_file_bounded(
                    fs, artifact_path, maximum_bytes=len(artifact)
                )
            if existing != artifact:
                return False, [
                    "FAIL  stale-attempt reconciliation artifact conflicts with its "
                    "content address"
                ]
            record.update(
                {
                    "status": "cancelled",
                    "completed_at": reconciled_at,
                    "completion_commit": identity["commit"],
                    "output_sha256": None,
                    "output_path": artifact_path,
                    "output_artifact_sha256": artifact_sha256,
                    "workspace_checkpoint": current.to_dict(),
                    "evidence": [f"reconciliation://{artifact_sha256}"],
                    "evidence_records": [],
                    "findings": [],
                    "finding_counts": {key: 0 for key in FINDING_KEYS},
                    "error": (
                        "operator reconciled a stale side-effect-free attempt after "
                        "coordinator interruption"
                    ),
                    "reconciliation": reconciliation,
                }
            )
            run["current_commit"] = identity["commit"]
            run["next"] = f"retry reconciled stage {stage}"
            _write_snapshot_locked(target, run)
        msgs.append(
            f"OK    stale stage {stage!r} was reconciled as cancelled by {operator}"
        )
        return True, msgs
    except TimeoutError as exc:
        return False, [f"FAIL  {exc}"]
    except (UnsafePathError, OSError, ValueError) as exc:
        return False, [f"FAIL  unsafe pipeline state mutation refused: {exc}"]


def reconcile_stale_stage_attempt(
    target: str | Path,
    *,
    stage: str,
    dispatch_id: str,
    reconciled_by: str,
    evidence: str | Path,
) -> tuple[bool, list[str]]:
    """Explicitly recover a stale, side-effect-free managed stage claim.

    Recovery is never automatic. The caller must acquire the crash-released
    coordinator lease, identify the exact claim, supply root-contained operator
    evidence, and prove the frozen workspace and provider controls are unchanged.
    Shell, write, external-effect, or nested-delegation roles remain fail-closed.
    """

    from claude_kit.execution_lease import (
        ManagedExecutionLeaseHeld,
        managed_execution_lease,
    )

    try:
        root = ProjectFS(Path(target).expanduser()).root
        with managed_execution_lease(root):
            return _reconcile_stale_stage_attempt_under_lease(
                root,
                stage=stage,
                dispatch_id=dispatch_id,
                reconciled_by=reconciled_by,
                evidence=evidence,
            )
    except ManagedExecutionLeaseHeld:
        return False, [
            "FAIL  managed workflow coordinator is still running; interrupt it before "
            "reconciling a stale stage attempt"
        ]
    except (UnsafePathError, OSError, ValueError) as exc:
        return False, [f"FAIL  unsafe pipeline state mutation refused: {exc}"]


def _reconcile_stale_program_attempt_under_lease(
    target: str | Path,
    *,
    unit_id: str,
    dispatch_id: str,
    reconciled_by: str,
    evidence: str | Path,
) -> tuple[bool, list[str]]:
    """Reconcile an orphaned Mode E claim only when it was side-effect-free."""

    if not _STAGE_ID_RE.fullmatch(unit_id):
        return False, ["FAIL  program unit id must be a contained identifier"]
    if not dispatch_id.strip() or not reconciled_by.strip():
        return False, ["FAIL  dispatch id and reconciler must be non-empty"]
    operator = reconciled_by.strip()
    if len(operator.encode("utf-8")) > 256:
        return False, ["FAIL  reconciler identity exceeds the 256-byte safety limit"]
    msgs: list[str] = []
    try:
        fs = ProjectFS(Path(target).expanduser())
        root = fs.root
        path = fs.path(_snapshot_rel(root))
    except (OSError, UnsafePathError, ValueError) as exc:
        return False, [f"FAIL  unsafe pipeline state path: {exc}"]
    try:
        with _pipeline_write_lock(fs, path, msgs=msgs):
            snap, error = _load_snapshot(root)
            if error:
                return False, [f"FAIL  {error}"]
            run, identity, problem = _active_v2_run(root, snap)
            if problem or run is None or identity is None:
                return False, [f"FAIL  {problem or 'invalid run'}"]
            contract = run.get("program_execution")
            if not isinstance(contract, dict):
                return False, ["FAIL  no frozen program execution contract exists"]
            attempts = contract.get("unit_attempts")
            if not isinstance(attempts, list):
                return False, ["FAIL  program attempt ledger is malformed"]
            matches = [
                item
                for item in attempts
                if isinstance(item, dict)
                and item.get("unit_id") == unit_id
                and item.get("dispatch_id") == dispatch_id.strip()
                and item.get("status") == "running"
            ]
            if len(matches) != 1:
                return False, [
                    "FAIL  exact stale running program attempt was not found"
                ]
            record = matches[0]
            required = record.get("required_capabilities")
            if not isinstance(required, list):
                return False, ["FAIL  stale program capability contract is malformed"]
            forbidden = sorted(set(required) & _STALE_ATTEMPT_FORBIDDEN_CAPABILITIES)
            if forbidden:
                return False, [
                    "FAIL  stale program attempt may have side effects and cannot be "
                    "reconciled automatically: " + ", ".join(forbidden)
                ]
            current, workspace_problem = _program_current_workspace_checkpoint(
                root, contract
            )
            if workspace_problem or current is None:
                return False, [f"FAIL  {workspace_problem}"]
            if record.get("pre_workspace_checkpoint") != current.to_dict():
                return False, [
                    "FAIL  program workspace changed after the stale claim; abort and "
                    "investigate instead of reconciling"
                ]
            try:
                evidence_path, evidence_sha = _copy_stale_attempt_evidence(fs, evidence)
            except (FileNotFoundError, OSError, UnsafePathError, ValueError) as exc:
                return False, [f"FAIL  invalid reconciliation evidence: {exc}"]
            reconciled_at = _utc_now()
            reconciliation = {
                "schema_version": 1,
                "kind": "operator-stale-program-attempt-reconciliation",
                "run_id": run["run_id"],
                "program_manifest_digest": contract["binding"]["manifest_digest"],
                "unit_id": unit_id,
                "dispatch_id": dispatch_id.strip(),
                "attempt": record["attempt"],
                "provider": record["provider"],
                "route": record["route"],
                "reason": "coordinator-crash",
                "reconciled_by": operator,
                "reconciled_at": reconciled_at,
                "evidence_path": evidence_path,
                "evidence_sha256": evidence_sha,
                "workspace_checkpoint": current.to_dict(),
            }
            artifact = (
                json.dumps(
                    reconciliation,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )
                + "\n"
            ).encode("utf-8")
            layout = _state_layout(root)
            artifact_sha = hashlib.sha256(artifact).hexdigest()
            artifact_path = (
                f"{layout.artifacts}/program/runs/{run['run_id']}/"
                f"{contract['binding']['manifest_digest']}/{unit_id}/"
                f"{record['attempt']}/reconciliation-{artifact_sha}.json"
            )
            fs.write_bytes(artifact_path, artifact, mode=0o600)
            record.update(
                {
                    "status": "cancelled",
                    "completed_at": reconciled_at,
                    "completion_commit": identity["commit"],
                    "post_workspace_checkpoint": current.to_dict(),
                    "changed_paths": [],
                    "boundary_snapshot_digest": hashlib.sha256(
                        json.dumps(
                            {
                                "before": current.content_digest,
                                "after": current.content_digest,
                                "changed_paths": [],
                            },
                            separators=(",", ":"),
                            sort_keys=True,
                        ).encode("utf-8")
                    ).hexdigest(),
                    "evidence": [],
                    "evidence_verifications": [],
                    "output_sha256": None,
                    "output_path": artifact_path,
                    "output_artifact_sha256": artifact_sha,
                    "error": "operator reconciled a stale side-effect-free program attempt",
                    "reconciliation": reconciliation,
                }
            )
            run["current_commit"] = identity["commit"]
            run["next"] = f"retry reconciled program unit {unit_id}"
            prospective_problem = _program_execution_problem(root, run)
            if prospective_problem:
                return False, [f"FAIL  {prospective_problem}"]
            _write_snapshot_locked(root, run)
        msgs.append(f"OK    stale program unit {unit_id!r} reconciled as cancelled")
        return True, msgs
    except TimeoutError as exc:
        return False, [f"FAIL  {exc}"]
    except (OSError, UnsafePathError, ValueError) as exc:
        return False, [f"FAIL  unsafe pipeline state mutation refused: {exc}"]


def reconcile_stale_program_attempt(
    target: str | Path,
    *,
    unit_id: str,
    dispatch_id: str,
    reconciled_by: str,
    evidence: str | Path,
) -> tuple[bool, list[str]]:
    """Recover only an unchanged, side-effect-free orphaned program claim."""

    from claude_kit.execution_lease import (
        ManagedExecutionLeaseHeld,
        managed_execution_lease,
    )

    try:
        root = ProjectFS(Path(target).expanduser()).root
        with managed_execution_lease(root):
            return _reconcile_stale_program_attempt_under_lease(
                root,
                unit_id=unit_id,
                dispatch_id=dispatch_id,
                reconciled_by=reconciled_by,
                evidence=evidence,
            )
    except ManagedExecutionLeaseHeld:
        return False, [
            "FAIL  program coordinator is still running; interrupt it before "
            "reconciling a stale unit attempt"
        ]
    except (OSError, UnsafePathError, ValueError) as exc:
        return False, [f"FAIL  unsafe pipeline state mutation refused: {exc}"]


def _stale_attempt_reconciliation_problem(
    root: Path, run: Mapping[str, Any], record: Mapping[str, Any]
) -> str | None:
    reconciliation = record.get("reconciliation")
    if reconciliation is None:
        return None
    if not isinstance(reconciliation, dict):
        return "stale-attempt reconciliation record is malformed"
    expected_fields = {
        "schema_version",
        "kind",
        "run_id",
        "stage",
        "dispatch_id",
        "dispatch_attempt",
        "reason",
        "reconciled_by",
        "reconciled_at",
        "evidence_path",
        "evidence_sha256",
        "workspace_head_commit",
        "workspace_content_digest",
        "provider_control_surface_digest",
        "workflow_definition_digest",
    }
    if set(reconciliation) != expected_fields:
        return "stale-attempt reconciliation has unexpected or missing fields"
    if (
        reconciliation.get("schema_version") != 1
        or reconciliation.get("kind") != "operator-stale-attempt-reconciliation"
        or reconciliation.get("reason") != "coordinator-crash"
        or record.get("status") != "cancelled"
    ):
        return "stale-attempt reconciliation has invalid type or terminal status"
    if record.get("provider") != "claude":
        return "non-Claude stage has a stale-attempt reconciliation"
    for field in ("run_id", "stage", "dispatch_id", "dispatch_attempt"):
        expected = run.get(field) if field == "run_id" else record.get(field)
        if reconciliation.get(field) != expected:
            return f"stale-attempt reconciliation differs from its {field}"
    operator = reconciliation.get("reconciled_by")
    if (
        not isinstance(operator, str)
        or not operator.strip()
        or len(operator.encode("utf-8")) > 256
    ):
        return "stale-attempt reconciliation has no bounded operator identity"
    if reconciliation.get("reconciled_at") != record.get("completed_at"):
        return "stale-attempt reconciliation timestamp differs from stage completion"

    contract = run.get("managed_execution")
    if not isinstance(contract, dict):
        return "stale-attempt reconciliation is outside managed execution"
    if reconciliation.get("provider_control_surface_digest") != contract.get(
        "provider_control_surface_digest"
    ) or reconciliation.get("workflow_definition_digest") != contract.get(
        "workflow_definition_digest"
    ):
        return "stale-attempt reconciliation differs from frozen execution controls"
    routes = contract.get("active_stage_routes")
    route = routes.get(record.get("stage")) if isinstance(routes, dict) else None
    if not isinstance(route, dict):
        return "stale-attempt reconciliation has no frozen route contract"
    raw_required = record.get("required_capabilities")
    if not isinstance(raw_required, list):
        return "stale attempt required_capabilities must be an array"
    try:
        required = _stage_capabilities(
            raw_required,
            field_name="stale attempt required_capabilities",
        )
    except (TypeError, ValueError) as exc:
        return str(exc)
    if (
        set(required) & _STALE_ATTEMPT_FORBIDDEN_CAPABILITIES
        or route.get("permission") != "read_only"
        or route.get("write_scope") != []
        or route.get("nested_delegation") != "forbidden"
    ):
        return "side-effect-capable stage has a stale-attempt reconciliation"

    raw_checkpoint = record.get("workspace_checkpoint")
    before_checkpoint = record.get("workspace_checkpoint_before")
    try:
        if not isinstance(raw_checkpoint, dict):
            raise WorktreeError("checkpoint is missing")
        checkpoint = WorkspaceCheckpoint.from_dict(raw_checkpoint)
    except WorktreeError as exc:
        return f"stale-attempt reconciliation checkpoint is invalid: {exc}"
    if raw_checkpoint != before_checkpoint:
        return "stale-attempt reconciliation did not preserve the pre-attempt workspace"
    if (
        reconciliation.get("workspace_head_commit") != checkpoint.head_commit
        or reconciliation.get("workspace_content_digest") != checkpoint.content_digest
    ):
        return "stale-attempt reconciliation workspace identity is inconsistent"

    evidence_path = reconciliation.get("evidence_path")
    evidence_sha256 = reconciliation.get("evidence_sha256")
    evidence_prefix = _state_layout(root).artifacts + "/reconciliation/"
    if (
        not isinstance(evidence_path, str)
        or not evidence_path.startswith(evidence_prefix)
        or Path(evidence_path).is_absolute()
        or ".." in Path(evidence_path).parts
        or not isinstance(evidence_sha256, str)
        or not re.fullmatch(r"[0-9a-f]{64}", evidence_sha256)
    ):
        return "stale-attempt reconciliation evidence reference is invalid"
    try:
        _evidence_bytes, actual_evidence_sha, _evidence_size = (
            _read_managed_file_bounded(
                ProjectFS(root),
                evidence_path,
                maximum_bytes=MAX_EVIDENCE_ENVELOPE_BYTES,
            )
        )
    except (FileNotFoundError, UnsafePathError, OSError, ValueError):
        return "stale-attempt reconciliation evidence is unavailable"
    if actual_evidence_sha != evidence_sha256:
        return "stale-attempt reconciliation evidence hash mismatch"

    output_path = record.get("output_path")
    output_sha = record.get("output_artifact_sha256")
    ledger_attempt = record.get("attempt")
    if (
        not isinstance(output_path, str)
        or not isinstance(output_sha, str)
        or not isinstance(ledger_attempt, int)
        or output_path
        != _managed_reconciliation_artifact_relative(
            str(run.get("run_id")),
            str(record.get("stage")),
            ledger_attempt,
            output_sha,
            layout=_state_layout(root),
        )
    ):
        return "stale-attempt reconciliation artifact has inconsistent run ownership"
    try:
        artifact_info = ProjectFS(root).path(output_path).lstat()
        artifact_bytes, artifact_actual_sha, _artifact_size = (
            _read_managed_file_bounded(
                ProjectFS(root),
                output_path,
                maximum_bytes=_MAX_MANAGED_OUTPUT_ARTIFACT_BYTES,
            )
        )
        artifact_document = json.loads(artifact_bytes)
    except (
        FileNotFoundError,
        json.JSONDecodeError,
        UnsafePathError,
        OSError,
        ValueError,
    ):
        return "stale-attempt reconciliation artifact is unavailable or malformed"
    if (
        artifact_actual_sha != output_sha
        or not stat.S_ISREG(artifact_info.st_mode)
        or stat.S_IMODE(artifact_info.st_mode) != 0o600
        or artifact_document != reconciliation
    ):
        return "stale-attempt reconciliation artifact differs from the ledger record"
    return None


def _managed_terminal_artifact_problem(
    root: Path, run: Mapping[str, Any], record: Mapping[str, Any]
) -> str | None:
    """Re-derive one ordinary managed A--D terminal result artifact exactly."""

    if record.get("reconciliation") is not None:
        return None
    run_id = run.get("run_id")
    stage = record.get("stage")
    ledger_attempt = record.get("attempt")
    artifact_sha = record.get("output_artifact_sha256")
    output_path = record.get("output_path")
    if (
        not isinstance(run_id, str)
        or not _STAGE_ID_RE.fullmatch(run_id)
        or not isinstance(stage, str)
        or not _STAGE_ID_RE.fullmatch(stage)
        or not isinstance(ledger_attempt, int)
        or isinstance(ledger_attempt, bool)
        or ledger_attempt < 1
        or not isinstance(artifact_sha, str)
        or not re.fullmatch(r"[0-9a-f]{64}", artifact_sha)
        or not isinstance(output_path, str)
    ):
        return "managed terminal artifact identity is malformed"
    expected_path = _managed_dispatch_artifact_relative(
        run_id,
        stage,
        ledger_attempt,
        artifact_sha,
        layout=_state_layout(root),
    )
    if output_path != expected_path:
        return "managed terminal artifact belongs to another run, stage, or attempt"
    try:
        fs = ProjectFS(root)
        info = fs.path(output_path).lstat()
        content, actual_sha, _byte_count = _read_managed_file_bounded(
            fs,
            output_path,
            maximum_bytes=_MAX_MANAGED_OUTPUT_ARTIFACT_BYTES,
        )
        document = json.loads(content)
    except (
        FileNotFoundError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        OSError,
        UnsafePathError,
        ValueError,
    ):
        return "managed terminal artifact is unavailable or malformed"
    if (
        actual_sha != artifact_sha
        or not stat.S_ISREG(info.st_mode)
        or stat.S_IMODE(info.st_mode) != 0o600
        or not isinstance(document, dict)
    ):
        return "managed terminal artifact content or mode changed after recording"
    output = document.get("output")
    output_sha = record.get("output_sha256")
    if output_sha is None:
        if output is not None:
            return "managed terminal artifact has unbound output content"
    elif (
        not isinstance(output_sha, str)
        or not isinstance(output, str)
        or hashlib.sha256(output.encode("utf-8")).hexdigest() != output_sha
    ):
        return "managed terminal artifact output hash is inconsistent"
    expected = {
        "schema_version": 1,
        "run_id": run_id,
        "stage": stage,
        "ledger_attempt": ledger_attempt,
        "provider": record.get("provider"),
        "route": record.get("role"),
        "dispatch_id": record.get("dispatch_id"),
        "dispatch_attempt": record.get("dispatch_attempt"),
        "status": record.get("status"),
        "output": output,
        "error": record.get("error"),
        "evidence": record.get("evidence"),
        "evidence_records": record.get("evidence_records"),
        "workspace_checkpoint": record.get("workspace_checkpoint"),
    }
    if document != expected:
        return "managed terminal artifact differs from the exact ledger result"
    return None


def _managed_archived_artifacts_problem(
    root: Path, run: Mapping[str, Any]
) -> str | None:
    """Live-verify every typed root-owned artifact retained by an archived A--D run."""

    contract = run.get("managed_execution")
    if not _managed_typed_evidence_markers(run):
        # Historical/manual snapshots predate the typed managed artifact contract.
        return None
    if (
        not isinstance(contract, dict)
        or contract.get("evidence_contract_version") != EVIDENCE_CONTRACT_VERSION
    ):
        return "typed managed evidence contract version is missing or unsupported"
    raw_history = run.get("stage_history")
    if not isinstance(raw_history, list):
        return "typed managed archive has no stage_history array"
    fs = ProjectFS(root)
    for index, raw_record in enumerate(raw_history):
        if not isinstance(raw_record, dict):
            return f"stage_history[{index}] is not an object"
        status = raw_record.get("status")
        if status == "running":
            return f"stage_history[{index}] is still running"
        terminal_problem = _managed_terminal_artifact_problem(root, run, raw_record)
        if terminal_problem:
            return f"stage_history[{index}] {terminal_problem}"
        reconciliation_problem = _stale_attempt_reconciliation_problem(
            root, run, raw_record
        )
        if reconciliation_problem:
            return f"stage_history[{index}] {reconciliation_problem}"
        has_typed_evidence = bool(raw_record.get("evidence_records"))
        if status == "succeeded" or has_typed_evidence:
            stage = raw_record.get("stage")
            dispatch_id = raw_record.get("dispatch_id")
            dispatch_attempt = raw_record.get("dispatch_attempt")
            if (
                not isinstance(stage, str)
                or not isinstance(dispatch_id, str)
                or not isinstance(dispatch_attempt, int)
                or isinstance(dispatch_attempt, bool)
            ):
                return f"stage_history[{index}] has malformed typed evidence identity"
            evidence_problem, findings, counts = _managed_stage_evidence_problem(
                fs,
                run,
                stage=stage,
                dispatch_id=dispatch_id,
                dispatch_attempt=dispatch_attempt,
                output_sha256=cast(Optional[str], raw_record.get("output_sha256")),
                records=raw_record.get("evidence_records"),
                require_pass=status == "succeeded",
            )
            if evidence_problem:
                return f"stage_history[{index}] {evidence_problem}"
            if raw_record.get("findings") != findings:
                return (
                    f"stage_history[{index}] finding index differs from typed evidence"
                )
            if raw_record.get("finding_counts") != counts:
                return (
                    f"stage_history[{index}] finding counts differ from typed evidence"
                )

    findings_record = run.get("findings_evidence")
    if (
        isinstance(findings_record, dict)
        and findings_record.get("managed_gate") is not None
    ):
        findings_problem = _managed_findings_bundle_problem(fs, run, findings_record)
        if findings_problem:
            return findings_problem

    raw_risks = run.get("accepted_risks")
    if not isinstance(raw_risks, list):
        return "typed managed archive has no accepted_risks array"
    for index, raw_risk in enumerate(raw_risks):
        if not isinstance(raw_risk, dict):
            return f"accepted_risks[{index}] is not an object"
        risk_problem = _managed_accepted_risk_evidence_problem(fs, run, raw_risk)
        if risk_problem:
            return f"accepted_risks[{index}] {risk_problem}"

    raw_gate_history = run.get("gate_history")
    if not isinstance(raw_gate_history, list):
        return "typed managed archive has no gate_history array"
    for index, raw_entry in enumerate(raw_gate_history):
        if not isinstance(raw_entry, dict):
            return f"gate_history[{index}] is not an object"
        gate_status = raw_entry.get("status")
        if gate_status == "not-applicable":
            bundle_problem = _managed_not_applicable_bundle_problem(fs, run, raw_entry)
        elif gate_status in {"passed", "accepted-risk"}:
            bundle_problem = _managed_gate_bundle_problem(fs, run, raw_entry)
        else:
            bundle_problem = None
        if bundle_problem:
            return f"gate_history[{index}] {bundle_problem}"
    return None


def _managed_stage_state_projection(run: Mapping[str, Any]) -> list[dict[str, Any]]:
    contract = cast(Mapping[str, Any], run.get("managed_execution") or {})
    active = contract.get("active_stages", [])
    history = run.get("stage_history", [])
    skips = run.get("skipped_stage_history", [])
    projection: list[dict[str, Any]] = []
    for stage in active if isinstance(active, list) else []:
        succeeded = [
            item
            for item in history
            if isinstance(history, list)
            if isinstance(item, dict)
            and item.get("stage") == stage
            and item.get("status") == "succeeded"
        ]
        skipped = [
            item
            for item in skips
            if isinstance(skips, list)
            if isinstance(item, dict) and item.get("stage") == stage
        ]
        if len(succeeded) == 1 and not skipped:
            projection.append(
                {
                    "stage": stage,
                    "status": "succeeded",
                    "dispatch_id": succeeded[0].get("dispatch_id"),
                    "dispatch_attempt": succeeded[0].get("dispatch_attempt"),
                    "output_artifact_sha256": succeeded[0].get(
                        "output_artifact_sha256"
                    ),
                    "evidence_set_digest": hashlib.sha256(
                        json.dumps(
                            succeeded[0].get("evidence_records", []),
                            separators=(",", ":"),
                            sort_keys=True,
                        ).encode("utf-8")
                    ).hexdigest(),
                    "finding_counts": succeeded[0].get("finding_counts"),
                    "workspace_content_digest": (
                        succeeded[0].get("workspace_checkpoint") or {}
                    ).get("content_digest"),
                }
            )
        elif len(skipped) == 1 and not succeeded:
            projection.append(
                {
                    "stage": stage,
                    "status": "skipped",
                    "attestation_sha256": skipped[0].get("attestation_sha256"),
                    "workspace_content_digest": (
                        skipped[0].get("workspace_checkpoint") or {}
                    ).get("content_digest"),
                }
            )
        else:
            projection.append({"stage": stage, "status": "unsettled"})
    return projection


def _managed_completion_digest(run: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        _managed_stage_state_projection(run),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _managed_completion_problem(
    run: Mapping[str, Any], *, current: WorkspaceCheckpoint | None = None
) -> str | None:
    contract = run.get("managed_execution")
    if contract is None:
        return None
    if not isinstance(contract, dict):
        return "managed execution contract is malformed"
    active = contract.get("active_stages")
    if not isinstance(active, list) or not active:
        return "managed workflow has no frozen active stage set"
    projection = _managed_stage_state_projection(run)
    unsettled = [
        str(item.get("stage")) for item in projection if item["status"] == "unsettled"
    ]
    if unsettled:
        return "managed workflow stages are not all terminal: " + ", ".join(unsettled)
    attestation = run.get("managed_completion")
    if not isinstance(attestation, dict):
        return "managed workflow has no coordinator completion attestation"
    if attestation.get("workflow_definition_digest") != contract.get(
        "workflow_definition_digest"
    ):
        return "managed completion belongs to a different workflow definition"
    if attestation.get("active_stages") != active:
        return "managed completion stage set differs from the frozen graph"
    if attestation.get("stage_state_digest") != _managed_completion_digest(run):
        return "managed completion stage-state digest is invalid"
    raw_checkpoint = attestation.get("workspace_checkpoint")
    try:
        if not isinstance(raw_checkpoint, dict):
            raise WorktreeError("checkpoint is missing")
        attested_checkpoint = WorkspaceCheckpoint.from_dict(raw_checkpoint)
    except WorktreeError as exc:
        return f"managed completion workspace checkpoint is invalid: {exc}"
    if current is not None and attested_checkpoint != current:
        return "managed workspace changed after workflow completion attestation"
    if not (
        isinstance(attestation.get("attested_at"), str)
        and attestation["attested_at"].strip()
    ):
        return "managed completion has no timestamp"
    if not (
        isinstance(attestation.get("repository_commit"), str)
        and attestation["repository_commit"].strip()
    ):
        return "managed completion has no repository commit"
    return None


def attest_managed_workflow_completion(
    target: str | Path,
    *,
    active_stages: Sequence[str],
    workspace_checkpoint: Mapping[str, Any] | None,
) -> tuple[bool, list[str]]:
    """Attest that every selected stage settled after the final gate checkpoint."""

    try:
        supplied = (
            WorkspaceCheckpoint.from_dict(dict(workspace_checkpoint))
            if workspace_checkpoint is not None
            else None
        )
    except (TypeError, WorktreeError) as exc:
        return False, [f"FAIL  invalid completion workspace checkpoint: {exc}"]
    msgs: list[str] = []
    try:
        fs = ProjectFS(Path(target).expanduser())
        path = fs.path(_snapshot_rel(target))
        with _pipeline_write_lock(fs, path, msgs=msgs):
            snap, error = _load_snapshot(target)
            if error:
                return False, [f"FAIL  {error}"]
            run, identity, problem = _active_v2_run(target, snap)
            if problem or run is None or identity is None:
                return False, [f"FAIL  {problem or 'invalid run'}"]
            contract = run.get("managed_execution")
            if not isinstance(contract, dict):
                return False, ["FAIL  managed execution contract is missing"]
            if list(active_stages) != contract.get("active_stages"):
                return False, [
                    "FAIL  completion stage set differs from the frozen graph"
                ]
            current, checkpoint_problem = _managed_workspace_checkpoint(fs.root, run)
            if checkpoint_problem or current is None:
                return False, [
                    f"FAIL  {checkpoint_problem or 'managed checkpoint missing'}"
                ]
            if supplied != current:
                return False, ["FAIL  completion workspace checkpoint is stale"]
            unresolved = [
                gate
                for gate in run.get("ordered_gates", [])
                if gate not in _resolved_gate_names(run, list(run["ordered_gates"]))
            ]
            if unresolved:
                return False, [
                    "FAIL  cannot attest workflow completion with unresolved gates: "
                    + ", ".join(unresolved)
                ]
            projection = _managed_stage_state_projection(run)
            unsettled = [
                str(item["stage"])
                for item in projection
                if item["status"] == "unsettled"
            ]
            if unsettled:
                return False, [
                    "FAIL  managed workflow stages are not all terminal: "
                    + ", ".join(unsettled)
                ]
            document = {
                "schema_version": 1,
                "workflow_definition_digest": contract["workflow_definition_digest"],
                "active_stages": list(active_stages),
                "stage_state_digest": _managed_completion_digest(run),
                "workspace_checkpoint": current.to_dict(),
                "attested_at": _utc_now(),
                "repository_commit": identity["commit"],
            }
            existing = run.get("managed_completion")
            if existing is not None:
                comparable = dict(existing) if isinstance(existing, dict) else {}
                for field in ("attested_at", "repository_commit"):
                    comparable.pop(field, None)
                expected = dict(document)
                for field in ("attested_at", "repository_commit"):
                    expected.pop(field, None)
                if comparable != expected:
                    return False, ["FAIL  managed completion attestation conflicts"]
                return True, ["OK    managed workflow completion already attested"]
            run["managed_completion"] = document
            _write_snapshot_locked(target, run)
        msgs.append("OK    managed workflow completion attested")
        return True, msgs
    except TimeoutError as exc:
        return False, [f"FAIL  {exc}"]
    except (UnsafePathError, OSError, ValueError) as exc:
        return False, [f"FAIL  unsafe pipeline state mutation refused: {exc}"]


def validate(
    target: str | Path,
    *,
    strict: bool = False,
    _refresh_gate: str | None = None,
    _refresh_findings: bool = False,
    _historical_terminal: bool = False,
) -> tuple[bool, list[str]]:
    """Validate the pipeline snapshot's shape and coherence (no writes).

    Absence is not an error — a repo with no active run is valid. When a snapshot is present, every
    field that *is* set must hold a legal value (the schema lets fields be omitted, not malformed),
    ``last_gate_passed`` must name a gate the installed profile actually defines, and **every**
    ``gate_history`` entry is re-verified: its evidence file must exist and still match the recorded
    sha256, and the entries must follow the installed gate order. ``strict=True`` additionally fails
    (rather than warns) when the install snapshot is missing or unreadable.
    """
    msgs: list[str] = []
    ok = True
    try:
        root = ProjectFS(Path(target).expanduser()).root
    except (UnsafePathError, OSError, ValueError) as exc:
        return False, [f"FAIL  unsafe pipeline project root: {exc}"]

    def fail(m: str) -> None:
        nonlocal ok
        ok = False
        msgs.append(f"FAIL  {m}")

    def resolve_evidence(ev: str) -> Path:
        """Non-absolute recorded evidence paths are project-relative, never CWD-relative."""
        p = Path(ev).expanduser()
        return p if p.is_absolute() else root / p

    snap, err = _load_snapshot(target)
    if err:
        fail(err)
        return ok, msgs
    install, install_err = _read_install_snapshot(target)
    if install_err:
        if strict:
            fail(f"{install_err} (--strict)")
        else:
            msgs.append(f"WARN  {install_err}")
    elif install is None and strict:
        fail(f"no install snapshot at {_stack_snapshot_rel(target)} (--strict)")
    if snap is None:
        if ok:
            msgs.append("OK    no pipeline snapshot — no run in progress")
        return ok, msgs

    from claude_kit.maker_checker import (
        is_maker_checker_snapshot,
        validate_maker_checker_snapshot,
    )

    if is_maker_checker_snapshot(snap):
        maker_ok, maker_messages = validate_maker_checker_snapshot(
            root,
            snap,
            verify_current_policy=strict and snap.get("status") == "active",
            historical_terminal=_historical_terminal,
        )
        return ok and maker_ok, [*msgs, *maker_messages]

    version, version_error = _snapshot_version(snap)
    if version_error:
        if strict:
            fail(version_error)
        else:
            msgs.append(f"WARN  {version_error}; snapshot was not interpreted")
        return ok, msgs
    legacy = version == 1
    if _historical_terminal and (
        legacy or snap.get("status") not in {"completed", "aborted"}
    ):
        fail("historical validation is only valid for a terminal schema-v2 snapshot")
    if legacy:
        msgs.append(
            "WARN  legacy schema v1 pipeline snapshot is readable for compatibility but "
            "cannot accept new transitions; use `pipeline adopt` to migrate it explicitly"
        )

    for field, allowed in (
        ("profile", PROFILES),
        ("scope", SCOPES),
        ("mode", MODES),
    ):
        val = snap.get(field)
        if not legacy and field not in snap:
            fail(f"schema-v2 snapshot has no required {field!r}")
        elif val is not None and val not in allowed:
            fail(f"{field} {val!r} is not one of {sorted(allowed)}")

    lanes = snap.get("lanes")
    if lanes is not None:
        if not isinstance(lanes, dict):
            fail("lanes must be an object of {lane: state}")
        else:
            for lane, state in lanes.items():
                if state not in LANE_STATES:
                    fail(
                        f"lane {lane!r} has invalid state {state!r} ({sorted(LANE_STATES)})"
                    )

    findings = snap.get("open_findings")
    if not legacy:
        if "findings_evidence" not in snap:
            fail("schema-v2 snapshot has no explicit findings_evidence field")
        if not isinstance(findings, dict):
            fail("schema-v2 open_findings must be an object of {severity: count}")
        else:
            missing = FINDING_KEYS - set(findings)
            extra = set(findings) - FINDING_KEYS
            if missing or extra:
                details = []
                if missing:
                    details.append(f"missing severities: {', '.join(sorted(missing))}")
                if extra:
                    details.append(f"unknown severities: {', '.join(sorted(extra))}")
                fail(
                    "schema-v2 open_findings must contain exactly "
                    f"{', '.join(sorted(FINDING_KEYS))} ({'; '.join(details)})"
                )
            for sev, count in findings.items():
                if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                    fail(
                        f"open_findings[{sev!r}] must be a non-negative integer, got {count!r}"
                    )
    elif findings is not None:
        if not isinstance(findings, dict):
            fail("open_findings must be an object of {severity: count}")
        else:
            for sev, count in findings.items():
                if sev not in FINDING_KEYS:
                    msgs.append(f"WARN  open_findings has unknown severity {sev!r}")
                if not isinstance(count, int) or isinstance(count, bool):
                    fail(f"open_findings[{sev!r}] must be an integer, got {count!r}")

    gate = snap.get("last_gate_passed")
    installed = (
        installed_gates(target)
        if legacy
        else installed_gates_for_mode(target, str(snap.get("mode", "")))
    )
    raw_ordered = snap.get("ordered_gates")
    gates = (
        installed
        if legacy
        else (list(raw_ordered) if isinstance(raw_ordered, list) else [])
    )
    definitions = installed_gate_definitions(target)
    identity: dict[str, str] | None = None
    freshness_commit: str | None = None
    if not legacy:
        required_strings = (
            "run_id",
            "repository_root",
            "branch",
            "starting_commit",
            "current_commit",
            "kit_version",
            "gate_definition_digest",
            "created_at",
            "task",
            "stage",
        )
        for field in required_strings:
            if not (isinstance(snap.get(field), str) and snap[field].strip()):
                fail(f"schema-v2 snapshot has no non-empty {field!r}")
        if (
            not isinstance(raw_ordered, list)
            or not raw_ordered
            or any(not isinstance(item, str) or not item for item in raw_ordered)
        ):
            fail("schema-v2 ordered_gates must be a non-empty array of gate names")
        elif len(set(raw_ordered)) != len(raw_ordered):
            fail("schema-v2 ordered_gates contains duplicates")
        if not _historical_terminal and installed and gates != installed:
            fail("schema-v2 ordered_gates differs from the installed profile")
        expected_digest = (
            ""
            if _historical_terminal
            else installed_gate_definition_digest_for_mode(
                target, str(snap.get("mode", ""))
            )
        )
        if not _historical_terminal and installed and not expected_digest:
            fail(
                "installed gate definitions or persisted gate digest are missing, malformed, "
                "or semantically inconsistent"
            )
        elif (
            not _historical_terminal
            and expected_digest
            and snap.get("gate_definition_digest") != expected_digest
        ):
            fail("gate definition digest differs from the installed gate policy")
        persisted_digest = snap.get("gate_definition_digest")
        if not (
            isinstance(persisted_digest, str)
            and len(persisted_digest) == 64
            and all(char in "0123456789abcdef" for char in persisted_digest)
        ):
            fail("schema-v2 gate_definition_digest must be 64 lowercase hex characters")
        selection_digest = snap.get("selection_digest")
        if selection_digest is not None:
            if not (
                isinstance(selection_digest, str)
                and len(selection_digest) == 64
                and all(char in "0123456789abcdef" for char in selection_digest)
            ):
                fail("schema-v2 selection_digest must be 64 lowercase hex characters")
            elif (
                not _historical_terminal
                and selection_digest != installed_selection_digest(target)
            ):
                fail("selection digest differs from the installed selection")
        status_value = snap.get("status")
        if status_value not in RUN_STATUSES:
            fail(f"status {status_value!r} is not one of {sorted(RUN_STATUSES)}")
        start_type = snap.get("start_type")
        if start_type not in {"fresh", "adopted"}:
            fail("start_type must be 'fresh' or 'adopted'")
        adoption = snap.get("adoption")
        if start_type == "adopted":
            if not isinstance(adoption, dict):
                fail("adopted run has no structured adoption record")
            else:
                for field in ("starting_gate", "reason", "adopted_by"):
                    if not (
                        isinstance(adoption.get(field), str) and adoption[field].strip()
                    ):
                        fail(f"adoption has no non-empty {field!r}")
                historical = adoption.get("historical_gates")
                starting_gate = adoption.get("starting_gate")
                if isinstance(starting_gate, str) and starting_gate in gates:
                    expected_historical = gates[: gates.index(starting_gate)]
                    if historical != expected_historical:
                        fail(
                            "adoption historical_gates must be exactly the gates preceding "
                            f"{starting_gate!r}"
                        )
                else:
                    fail(
                        f"adoption starting_gate {starting_gate!r} is not in ordered_gates"
                    )
            msgs.append(
                "WARN  ADOPTED run: preceding gates are historical, not newly evidenced "
                f"({(adoption or {}).get('reason', 'reason missing')})"
            )
        elif adoption not in (None, {}):
            fail("fresh run must not contain adoption metadata")
        for archive_problem in _run_archive_problems(
            root, snap.get("run_archives", [])
        ):
            fail(archive_problem)
        root_identity, identity_error = _git_identity(root)
        if identity_error or root_identity is None:
            fail(identity_error or "cannot establish repository identity")
        else:
            identity = root_identity
            if _historical_terminal:
                if not _git_contains_commit(root, snap.get("starting_commit")):
                    fail(
                        "historical terminal run starting_commit does not belong to this "
                        "repository"
                    )
            else:
                if snap.get("repository_root") != identity["repository_root"]:
                    fail("schema-v2 run belongs to a different repository root")
                if snap.get("branch") != identity["branch"]:
                    fail(
                        f"schema-v2 run belongs to branch {snap.get('branch')!r}, not "
                        f"{identity['branch']!r}"
                    )
            if status_value == "completed":
                freshness_commit = str(snap.get("current_commit"))
            elif status_value == "aborted":
                findings_record = snap.get("findings_evidence")
                freshness_commit = (
                    str(findings_record.get("repository_commit"))
                    if isinstance(findings_record, dict)
                    else str(snap.get("current_commit"))
                )
            else:
                freshness_commit = identity["commit"]
        if not _refresh_findings:
            evidence_record = snap.get("findings_evidence")
            if evidence_record is not None:
                for evidence_error in _findings_evidence_errors(
                    root,
                    snap,
                    current_commit=freshness_commit,
                ):
                    fail(evidence_error)
            elif snap.get("gate_history") or snap.get("accepted_risks"):
                fail(
                    "schema-v2 run has gate/risk records without structured findings evidence"
                )
    if gate is not None and gates and gate not in gates:
        fail(f"last_gate_passed {gate!r} is not a gate of this profile ({gates})")

    overrides = snap.get("gate_overrides")
    if overrides is not None and not isinstance(overrides, dict):
        fail("gate_overrides must be an object of {gate: reason}")

    if not legacy:
        managed_problem = _managed_execution_problem(root, snap)
        if managed_problem:
            fail(managed_problem)
        managed_contract = snap.get("managed_execution")
        if (
            isinstance(managed_contract, dict)
            and managed_contract.get("evidence_contract_version") is None
            and snap.get("status") in {"completed", "aborted"}
        ):
            msgs.append(
                "WARN  historical terminal managed run predates typed evidence authority; "
                "it is readable but cannot resume or advance"
            )
        program_problem = _program_execution_problem(root, snap)
        if program_problem:
            fail(program_problem)
        raw_conditions = snap.get("condition_decisions", {})
        if not isinstance(raw_conditions, dict):
            fail("schema-v2 condition_decisions must be an object")
        else:
            for condition, decision in raw_conditions.items():
                if not isinstance(condition, str) or not _STAGE_ID_RE.fullmatch(
                    condition
                ):
                    fail("condition_decisions contains an invalid condition identifier")
                if not isinstance(decision, bool):
                    fail(f"condition_decisions[{condition!r}] must be boolean")

        raw_stages = snap.get("stage_history", [])
        if not isinstance(raw_stages, list):
            fail("schema-v2 stage_history must be an array")
            raw_stages = []
        stage_records = [item for item in raw_stages if isinstance(item, dict)]
        if len(stage_records) != len(raw_stages):
            fail("stage_history contains non-object entries")
        managed_contract = snap.get("managed_execution")
        managed_routes = (
            managed_contract.get("active_stage_routes", {})
            if isinstance(managed_contract, dict)
            else {}
        )
        managed_dependencies = (
            managed_contract.get("active_stage_dependencies", {})
            if isinstance(managed_contract, dict)
            else {}
        )
        managed_requirements = (
            managed_contract.get("active_stage_requirements", {})
            if isinstance(managed_contract, dict)
            else {}
        )
        managed_providers = (
            managed_contract.get("providers", [])
            if isinstance(managed_contract, dict)
            else []
        )
        managed_stage_conditions: dict[str, str] = {}
        if isinstance(managed_contract, dict):
            try:
                managed_stage_conditions = {
                    stage.id: stage.condition
                    for stage in _current_workflow_definition().stages
                }
            except (OSError, ValueError):
                pass
        raw_skip_records = snap.get("skipped_stage_history", [])
        skip_records_for_dependencies = (
            [item for item in raw_skip_records if isinstance(item, dict)]
            if isinstance(raw_skip_records, list)
            else []
        )
        attempts_by_stage: dict[str, int] = {}
        terminal_by_dispatch: set[tuple[str, int]] = set()
        completed_stages: set[str] = set()
        running_stages: set[str] = set()
        unresolved_typed_failures: set[str] = set()
        for index, record in enumerate(stage_records):
            label = f"stage_history[{index}]"
            for field in (
                "stage",
                "status",
                "role",
                "provider",
                "dispatch_id",
                "started_at",
                "repository_commit",
            ):
                if not (isinstance(record.get(field), str) and record[field].strip()):
                    fail(f"{label} has no non-empty {field!r}")
            stage_name = record.get("stage")
            if not isinstance(stage_name, str) or not _STAGE_ID_RE.fullmatch(
                stage_name
            ):
                fail(f"{label} has an invalid stage identifier")
                continue
            status = record.get("status")
            if status not in STAGE_STATUSES:
                fail(f"{label} has unsupported status {status!r}")
            if stage_name in unresolved_typed_failures:
                fail(
                    f"{label} occurs after unresolved typed evidence failed for "
                    f"stage {stage_name!r}"
                )
            attempt = record.get("attempt")
            dispatch_attempt = record.get("dispatch_attempt")
            if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
                fail(f"{label} has no positive attempt")
            else:
                expected_attempt = attempts_by_stage.get(stage_name, 0) + 1
                if attempt != expected_attempt:
                    fail(
                        f"{label} stage attempt is {attempt!r}; expected {expected_attempt}"
                    )
                attempts_by_stage[stage_name] = attempt
            if (
                not isinstance(dispatch_attempt, int)
                or isinstance(dispatch_attempt, bool)
                or dispatch_attempt < 1
            ):
                fail(f"{label} has no positive dispatch_attempt")
            dispatch_id = record.get("dispatch_id")
            if isinstance(dispatch_id, str) and isinstance(dispatch_attempt, int):
                dispatch_key = (dispatch_id, dispatch_attempt)
                if dispatch_key in terminal_by_dispatch:
                    fail(f"{label} duplicates a dispatch attempt")
                terminal_by_dispatch.add(dispatch_key)
            required_raw = record.get("required_capabilities")
            attested_raw = record.get("attested_capabilities")
            if not isinstance(required_raw, list) or not isinstance(attested_raw, list):
                fail(f"{label} capability attestations must be arrays")
                required: tuple[str, ...] = ()
                attested: tuple[str, ...] = ()
            else:
                try:
                    required = _stage_capabilities(
                        required_raw, field_name=f"{label} required_capabilities"
                    )
                    attested = _stage_capabilities(
                        attested_raw, field_name=f"{label} attested_capabilities"
                    )
                except ValueError as exc:
                    fail(str(exc))
                    required = ()
                    attested = ()
            if status == "succeeded" and not set(required).issubset(attested):
                fail(f"{label} succeeded without every required capability attested")
            if isinstance(managed_contract, dict):
                route_contract = (
                    managed_routes.get(stage_name)
                    if isinstance(managed_routes, dict)
                    else None
                )
                expected_required = (
                    managed_requirements.get(stage_name)
                    if isinstance(managed_requirements, dict)
                    else None
                )
                if not isinstance(route_contract, dict) or not isinstance(
                    expected_required, list
                ):
                    fail(f"{label} names a stage outside the frozen managed graph")
                else:
                    if record.get("route") != route_contract.get("route"):
                        fail(f"{label} has a non-canonical workflow route")
                    if record.get("role") != route_contract.get("role"):
                        fail(f"{label} has a non-canonical managed role")
                    if (
                        required_raw != expected_required
                        or attested_raw != expected_required
                    ):
                        fail(
                            f"{label} differs from its exact managed capability contract"
                        )
                if record.get("provider") not in managed_providers:
                    fail(f"{label} uses a provider outside the frozen managed set")
                stage_condition = managed_stage_conditions.get(stage_name)
                if (
                    isinstance(stage_condition, str)
                    and raw_conditions.get(stage_condition) is False
                ):
                    fail(
                        f"{label} was claimed while frozen condition "
                        f"{stage_condition!r} was false"
                    )
                before_checkpoint = record.get("workspace_checkpoint_before")
                try:
                    if not isinstance(before_checkpoint, dict):
                        raise WorktreeError("checkpoint is missing")
                    WorkspaceCheckpoint.from_dict(before_checkpoint)
                except WorktreeError as exc:
                    fail(f"{label} pre-attempt workspace checkpoint is invalid: {exc}")
                prior_same_stage = [
                    item
                    for item in stage_records[:index]
                    if item.get("stage") == stage_name
                ]
                if (
                    prior_same_stage
                    and prior_same_stage[-1].get("status")
                    in {
                        "failed",
                        "cancelled",
                    }
                    and before_checkpoint
                    != prior_same_stage[-1].get("workspace_checkpoint_before")
                ):
                    fail(
                        f"{label} retry did not restore the failed attempt's exact "
                        "pre-attempt workspace checkpoint"
                    )
                dependencies = (
                    managed_dependencies.get(stage_name)
                    if isinstance(managed_dependencies, dict)
                    else None
                )
                started_at = record.get("started_at")
                if not isinstance(dependencies, list) or not isinstance(
                    started_at, str
                ):
                    fail(f"{label} has no canonical dependency contract")
                else:
                    active = set(managed_contract.get("active_stages", []))
                    for dependency in dependencies:
                        if dependency not in active:
                            continue
                        dependency_successes = [
                            item
                            for item in stage_records[:index]
                            if item.get("stage") == dependency
                            and item.get("status") == "succeeded"
                            and isinstance(item.get("completed_at"), str)
                            and str(item["completed_at"]) <= started_at
                        ]
                        dependency_skips = [
                            item
                            for item in skip_records_for_dependencies
                            if item.get("stage") == dependency
                            and isinstance(item.get("attested_at"), str)
                            and str(item["attested_at"]) <= started_at
                        ]
                        if (len(dependency_successes), len(dependency_skips)) not in {
                            (1, 0),
                            (0, 1),
                        }:
                            fail(
                                f"{label} was claimed before dependency "
                                f"{dependency!r} settled"
                            )
            if stage_name in completed_stages:
                fail(f"{label} occurs after stage {stage_name!r} already succeeded")
            if status == "succeeded":
                completed_stages.add(stage_name)
            if status == "running":
                if stage_name in running_stages:
                    fail(f"{label} duplicates a running stage")
                running_stages.add(stage_name)
            else:
                running_stages.discard(stage_name)
                if not (
                    isinstance(record.get("completed_at"), str)
                    and record["completed_at"].strip()
                ):
                    fail(f"{label} terminal result has no completed_at")
                if not (
                    isinstance(record.get("completion_commit"), str)
                    and record["completion_commit"].strip()
                ):
                    fail(f"{label} terminal result has no completion_commit")
                if status in {"failed", "cancelled"} and not (
                    isinstance(record.get("error"), str) and record["error"].strip()
                ):
                    fail(f"{label} {status} result has no error")
                if snap.get("managed_execution") is not None:
                    raw_checkpoint = record.get("workspace_checkpoint")
                    try:
                        if not isinstance(raw_checkpoint, dict):
                            raise WorktreeError("checkpoint is missing")
                        WorkspaceCheckpoint.from_dict(raw_checkpoint)
                    except WorktreeError as exc:
                        fail(f"{label} has invalid workspace checkpoint: {exc}")
                    output_path = record.get("output_path")
                    artifact_sha = record.get("output_artifact_sha256")
                    dispatch_prefix = _state_layout(target).artifacts + "/dispatch/"
                    if not isinstance(output_path, str) or not output_path:
                        fail(f"{label} has no root-owned output_path")
                    elif Path(output_path).is_absolute():
                        fail(f"{label} output_path must be project-relative")
                    elif not output_path.startswith(dispatch_prefix):
                        fail(
                            f"{label} output_path is outside the dispatch artifact root"
                        )
                    elif not isinstance(artifact_sha, str) or not re.fullmatch(
                        r"[0-9a-f]{64}", artifact_sha
                    ):
                        fail(f"{label} has no valid output_artifact_sha256")
                    else:
                        try:
                            artifact_bytes, actual_artifact_sha, _artifact_size = (
                                _read_managed_file_bounded(
                                    ProjectFS(root),
                                    output_path,
                                    maximum_bytes=_MAX_MANAGED_OUTPUT_ARTIFACT_BYTES,
                                )
                            )
                        except (
                            FileNotFoundError,
                            UnsafePathError,
                            OSError,
                            ValueError,
                        ):
                            fail(f"{label} output artifact is unavailable")
                        else:
                            if actual_artifact_sha != artifact_sha:
                                fail(f"{label} output artifact hash mismatch")
                    typed_contract = (
                        isinstance(managed_contract, dict)
                        and managed_contract.get("evidence_contract_version")
                        == EVIDENCE_CONTRACT_VERSION
                    )
                    if typed_contract:
                        terminal_artifact_problem = _managed_terminal_artifact_problem(
                            root, snap, record
                        )
                        if terminal_artifact_problem:
                            fail(f"{label} {terminal_artifact_problem}")
                    has_typed_evidence = bool(record.get("evidence_records"))
                    if typed_contract and (status == "succeeded" or has_typed_evidence):
                        evidence_problem, derived_findings, derived_counts = (
                            _managed_stage_evidence_problem(
                                ProjectFS(root),
                                snap,
                                stage=stage_name,
                                dispatch_id=str(record.get("dispatch_id")),
                                dispatch_attempt=cast(
                                    int, record.get("dispatch_attempt")
                                ),
                                output_sha256=cast(
                                    Optional[str], record.get("output_sha256")
                                ),
                                records=record.get("evidence_records"),
                                require_pass=status == "succeeded",
                            )
                        )
                        if evidence_problem:
                            fail(f"{label} {evidence_problem}")
                        if record.get("findings") != derived_findings:
                            fail(f"{label} finding index differs from typed evidence")
                        if record.get("finding_counts") != derived_counts:
                            fail(f"{label} finding counts differ from typed evidence")
                        if status != "succeeded":
                            unresolved_typed_failures.add(stage_name)
                    elif (
                        typed_contract
                        and status != "succeeded"
                        and (
                            record.get("evidence_records") not in (None, [])
                            or record.get("findings") not in (None, [])
                            or record.get("finding_counts")
                            != {key: 0 for key in FINDING_KEYS}
                        )
                    ):
                        fail(f"{label} has malformed failed typed evidence state")
                    reconciliation_problem = _stale_attempt_reconciliation_problem(
                        root, snap, record
                    )
                    if reconciliation_problem:
                        fail(f"{label} {reconciliation_problem}")

        raw_skips = snap.get("skipped_stage_history", [])
        if not isinstance(raw_skips, list):
            fail("schema-v2 skipped_stage_history must be an array")
            raw_skips = []
        skip_records = [item for item in raw_skips if isinstance(item, dict)]
        if len(skip_records) != len(raw_skips):
            fail("skipped_stage_history contains non-object entries")
        seen_skips: set[str] = set()
        for index, record in enumerate(skip_records):
            problem = _managed_skip_attestation_problem(snap, record)
            if problem:
                fail(f"skipped_stage_history[{index}] {problem}")
            stage_name = record.get("stage")
            if isinstance(stage_name, str):
                if stage_name in seen_skips:
                    fail(f"stage {stage_name!r} has duplicate skip attestations")
                if stage_name in completed_stages:
                    fail(f"stage {stage_name!r} is both succeeded and skipped")
                seen_skips.add(stage_name)

        if snap.get("managed_execution") is not None:
            managed_completion = snap.get("managed_completion")
            if managed_completion is not None or snap.get("status") == "completed":
                current_checkpoint, checkpoint_problem = _managed_workspace_checkpoint(
                    root, snap
                )
                if checkpoint_problem or current_checkpoint is None:
                    fail(
                        checkpoint_problem
                        or "managed completion workspace checkpoint is unavailable"
                    )
                else:
                    completion_problem = _managed_completion_problem(
                        snap, current=current_checkpoint
                    )
                    if completion_problem:
                        fail(completion_problem)

        managed_gate_history = snap.get("gate_history", [])
        for entry in (
            managed_gate_history if isinstance(managed_gate_history, list) else []
        ):
            if (
                isinstance(entry, dict)
                and entry.get("status") in {"passed", "not-applicable", "accepted-risk"}
                and isinstance(entry.get("gate"), str)
            ):
                allow_skipped = entry.get("status") == "not-applicable"
                owner_record, owner_problem = _managed_owner_stage_record(
                    snap,
                    str(entry["gate"]),
                    allow_skipped=allow_skipped,
                )
                if owner_problem:
                    fail(owner_problem)
                    continue
                if owner_record is not None:
                    if owner_record.get("decision") is False and entry.get(
                        "condition"
                    ) != owner_record.get("not_applicable_condition"):
                        fail(
                            "managed not-applicable gate condition differs from its "
                            "skipped owner attestation"
                        )
                    owner_checkpoint = owner_record.get("workspace_checkpoint")
                    if not isinstance(owner_checkpoint, dict):
                        fail("managed gate owner workspace checkpoint is missing")
                    elif entry.get("workspace_content_digest") != owner_checkpoint.get(
                        "content_digest"
                    ):
                        fail(
                            "managed gate workspace digest differs from its owner stage"
                        )
                    elif entry.get("workspace_head_commit") != owner_checkpoint.get(
                        "head_commit"
                    ):
                        fail("managed gate workspace HEAD differs from its owner stage")
                    contract = snap.get("managed_execution")
                    if (
                        isinstance(contract, dict)
                        and contract.get("evidence_contract_version")
                        == EVIDENCE_CONTRACT_VERSION
                    ):
                        if entry.get("status") == "not-applicable":
                            bundle_problem = _managed_not_applicable_bundle_problem(
                                ProjectFS(root), snap, entry
                            )
                        elif entry.get("status") in {"passed", "accepted-risk"}:
                            bundle_problem = _managed_gate_bundle_problem(
                                ProjectFS(root), snap, entry
                            )
                        else:
                            bundle_problem = None
                        if bundle_problem:
                            fail(bundle_problem)

        raw_stops = snap.get("human_stops", [])
        if not isinstance(raw_stops, list):
            fail("schema-v2 human_stops must be an array")
            raw_stops = []
        stops = [item for item in raw_stops if isinstance(item, dict)]
        if len(stops) != len(raw_stops):
            fail("human_stops contains non-object entries")
        pending_count = 0
        seen_stop_ids: set[str] = set()
        for index, stop in enumerate(stops):
            label = f"human_stops[{index}]"
            human_stop_required_fields = (
                "stop_id",
                "reason",
                "message",
                "requested_action",
                "status",
                "requested_at",
                "repository_commit",
            )
            for field in human_stop_required_fields:
                if not (isinstance(stop.get(field), str) and stop[field].strip()):
                    fail(f"{label} has no non-empty {field!r}")
            stop_id = stop.get("stop_id")
            if isinstance(stop_id, str):
                if stop_id in seen_stop_ids:
                    fail(f"{label} duplicates stop_id {stop_id!r}")
                seen_stop_ids.add(stop_id)
            if stop.get("reason") not in HUMAN_STOP_REASONS:
                fail(f"{label} has unsupported reason {stop.get('reason')!r}")
            status = stop.get("status")
            if status not in {"pending", "approved", "rejected"}:
                fail(f"{label} has unsupported status {status!r}")
            if status == "pending":
                pending_count += 1
                continue
            for field in (
                "resolved_by",
                "resolution_note",
                "resolved_at",
                "resolution_commit",
            ):
                if not (isinstance(stop.get(field), str) and stop[field].strip()):
                    fail(f"{label} resolved stop has no non-empty {field!r}")
            evidence_path = stop.get("evidence_path")
            evidence_sha = stop.get("evidence_sha256")
            if status == "approved" and not (
                isinstance(evidence_path, str) and evidence_path
            ):
                fail(f"{label} approved stop has no evidence_path")
            if isinstance(evidence_path, str) and evidence_path:
                resolved = resolve_evidence(evidence_path)
                if not resolved.is_file():
                    fail(
                        f"{label} human-stop evidence file is missing: {evidence_path}"
                    )
                elif _sha256(resolved) != evidence_sha:
                    fail(f"{label} human-stop evidence hash mismatch")
        if pending_count > 1:
            fail("schema-v2 run has more than one pending human stop")
        if pending_count and snap.get("status") != "active":
            fail("terminal pipeline run retains a pending human stop")

    # --- gate_history ledger: verify EVERY entry, not just the latest gate. -----------------
    raw_history = snap.get("gate_history")
    if not legacy and not isinstance(raw_history, list):
        fail("schema-v2 gate_history must be an array")
    elif raw_history is not None and not isinstance(raw_history, list):
        fail("gate_history must be an array of ledger entries")
    history = _history(snap)
    if isinstance(raw_history, list) and len(raw_history) != len(history):
        fail("gate_history contains non-object entries")
    if not legacy:
        allowance_problem = _headless_allowance_shape_problem(snap)
        if allowance_problem:
            fail(allowance_problem)
    adoption = snap.get("adoption")
    initial_position = _position(
        gates,
        [],
        None,
        legacy=legacy,
        adoption=adoption,
    )
    last_index = initial_position if initial_position is not None else -1
    risk_entries_by_gate: dict[str, dict[str, Any]] = {}
    for i, entry in enumerate(history):
        label = f"gate_history[{i}]"
        name = entry.get("gate")
        if not isinstance(name, str) or not name:
            fail(f"{label} has no gate name")
            continue
        status = entry.get("status")
        allowed_statuses = LEGACY_GATE_STATUSES if legacy else GATE_STATUSES
        if status not in allowed_statuses:
            fail(
                f"{label} ({name}) status {status!r} is not one of {sorted(allowed_statuses)}"
            )
        verification = entry.get("verification")
        if verification is not None and verification not in VERIFICATIONS:
            msgs.append(
                f"WARN  {label} ({name}) verification {verification!r} is not one of "
                f"{sorted(VERIFICATIONS)}"
            )
        if not legacy and not (
            isinstance(entry.get("recorded_at"), str) and entry["recorded_at"].strip()
        ):
            fail(f"{label} ({name}) has no recorded_at timestamp")
        if not legacy and not (
            isinstance(entry.get("repository_commit"), str)
            and entry["repository_commit"].strip()
        ):
            fail(f"{label} ({name}) has no repository_commit")
        if gates and name in gates:
            idx = gates.index(name)
            resolves = status in (LEGACY_GATE_STATUSES if legacy else POSITION_STATUSES)
            if (
                resolves
                and idx <= last_index
                and not (legacy and status == "overridden")
            ):
                fail(
                    f"{label} ({name}) is out of the installed gate order "
                    f"(after {gates[last_index]!r})"
                )
            if resolves:
                expected = last_index + 1
                if not legacy and idx != expected:
                    next_name = gates[expected] if expected < len(gates) else "(none)"
                    fail(f"{label} ({name}) is out of order; expected {next_name!r}")
                last_index = max(last_index, idx)
        elif gates:
            msgs.append(
                f"WARN  {label} ({name}) is not a gate of the installed profile "
                f"({', '.join(gates)}) — recorded under a different profile? review"
            )
        if legacy and status == "skipped":
            if not (isinstance(entry.get("reason"), str) and entry["reason"].strip()):
                msgs.append(f"WARN  {label} ({name}) is skipped without a reason")
            msgs.append(
                f"WARN  {label} ({name}) is a legacy skipped entry and lacks structured "
                "condition evidence"
            )
            continue
        if legacy and status == "overridden":
            msgs.append(
                f"WARN  {label} ({name}) is a legacy overridden entry; its unstructured "
                "waiver is readable but is not a valid schema-v2 transition"
            )
        if not legacy and status == "not-applicable":
            definition = definitions.get(name)
            condition = entry.get("condition")
            if _historical_terminal:
                if not (isinstance(condition, str) and condition.strip()):
                    fail(f"{label} ({name}) has no historical condition identifier")
            else:
                if definition is None:
                    fail(f"{label} ({name}) has no installed gate definition")
                elif (
                    definition.requirement != "conditional" or not definition.skippable
                ):
                    fail(f"{label} ({name}) marks a required gate not-applicable")
                if (
                    definition is not None
                    and condition not in definition.skip_conditions
                ):
                    fail(f"{label} ({name}) uses unknown condition {condition!r}")
            if not (isinstance(entry.get("reason"), str) and entry["reason"].strip()):
                fail(f"{label} ({name}) has no not-applicable reason")
            ev = entry.get("condition_evidence_path")
            sha_key = "condition_evidence_sha256"
        elif not legacy and status == "accepted-risk":
            risk_entries_by_gate[name] = entry
            continue
        else:
            ev = entry.get("evidence_path")
            sha_key = "evidence_sha256"
        if not legacy and status in {"failed", "aborted"} and not ev:
            # A failure/abort record may be a state marker rather than an evidence claim.
            continue
        if not (isinstance(ev, str) and ev):
            fail(
                f"{label} ({name}) has no {('condition_' if status == 'not-applicable' else '')}evidence_path"
            )
            continue
        ev_path = resolve_evidence(ev)
        if not ev_path.is_file():
            fail(f"{label} ({name}) evidence file is missing: {ev}")
            continue
        recorded_sha = entry.get(sha_key)
        if isinstance(recorded_sha, str) and recorded_sha:
            actual = _sha256(ev_path)
            if actual != recorded_sha:
                fail(
                    f"{label} ({name}) evidence hash mismatch — the file changed after the "
                    f"gate closed (recorded {recorded_sha[:12]}…, actual {actual[:12]}…)"
                )
        else:
            msgs.append(f"WARN  {label} ({name}) has no {sha_key} (pre-v2 entry)")
        if legacy and (status == "overridden" or entry.get("override")):
            msgs.append(
                f"WARN  {label} ({name}) was force-closed "
                f"(override: {entry.get('override')!r}) — review"
            )

    if not legacy:
        raw_risks = snap.get("accepted_risks")
        if not isinstance(raw_risks, list):
            fail("schema-v2 accepted_risks must be an array")
            raw_risks = []
        risks = [risk for risk in raw_risks if isinstance(risk, dict)]
        if len(risks) != len(raw_risks):
            fail("accepted_risks contains non-object entries")
        seen_pairs: set[tuple[str, str]] = set()
        risks_by_gate: dict[str, list[dict[str, Any]]] = {}
        current_medium = _blocking_findings(snap).get("medium", 0)
        for i, risk in enumerate(risks):
            label = f"accepted_risks[{i}]"
            risk_required_fields = (
                "risk_id",
                "finding_id",
                "reason",
                "accepted_by",
                "owner",
                "ticket",
                "revisit",
                "timestamp",
                "repository_commit",
                "affected_gate",
                "evidence_path",
                "evidence_sha256",
                "finding_set_digest",
                "finding_fingerprint",
                "gate_definition_digest",
            )
            for field in risk_required_fields:
                if not (isinstance(risk.get(field), str) and risk[field].strip()):
                    fail(f"{label} has no non-empty {field!r}")
            affected = risk.get("affected_gate")
            finding_id = risk.get("finding_id")
            if affected not in gates:
                fail(f"{label} affected_gate {affected!r} is not in ordered_gates")
            if isinstance(affected, str) and isinstance(finding_id, str):
                pair = (affected, finding_id)
                if pair in seen_pairs:
                    fail(
                        f"{label} duplicates finding {finding_id!r} for gate {affected!r}"
                    )
                seen_pairs.add(pair)
                risks_by_gate.setdefault(affected, []).append(risk)
            medium_count = risk.get("medium_finding_count")
            valid_medium_count = (
                isinstance(medium_count, int)
                and not isinstance(medium_count, bool)
                and medium_count >= 1
            )
            if not valid_medium_count:
                fail(
                    f"{label} medium_finding_count must be a positive integer, "
                    f"got {medium_count!r}"
                )
            # An explicit refresh may be one step in a sequential repair across several gates.
            # Temporarily tolerate only risk freshness/binding failures globally; structural,
            # policy, order, and ordinary gate-evidence checks still fail closed below/above.
            refreshing = _refresh_gate is not None or _refresh_findings
            if medium_count != current_medium and not refreshing:
                fail(
                    f"{label} finding count changed after acceptance "
                    f"(accepted {medium_count!r}, current {current_medium})"
                )
            current_finding_set_digest = str(
                (snap.get("findings_evidence") or {}).get("finding_set_digest", "")
            )
            if (
                risk.get("finding_set_digest") != current_finding_set_digest
                and not refreshing
            ):
                fail(f"{label} belongs to a different recorded finding set")
            if risk.get("gate_definition_digest") != snap.get("gate_definition_digest"):
                fail(f"{label} belongs to a different gate definition digest")
            risk_contract = snap.get("managed_execution")
            risk_managed_typed = (
                isinstance(risk_contract, dict)
                and risk_contract.get("evidence_contract_version")
                == EVIDENCE_CONTRACT_VERSION
            )
            if risk_managed_typed:
                risk_evidence_problem = _managed_accepted_risk_evidence_problem(
                    ProjectFS(root), snap, risk
                )
                if risk_evidence_problem and not refreshing:
                    fail(f"{label} {risk_evidence_problem}")
            else:
                ev = risk.get("evidence_path")
                if isinstance(ev, str) and ev:
                    ev_path = resolve_evidence(ev)
                    if not ev_path.is_file():
                        if not refreshing:
                            fail(
                                f"{label} accepted-risk evidence file is missing: {ev}"
                            )
                    else:
                        actual = _sha256(ev_path)
                        if actual != risk.get("evidence_sha256") and not refreshing:
                            fail(f"{label} accepted-risk evidence hash mismatch")
            fingerprint_medium_count = (
                cast(int, medium_count) if valid_medium_count else -1
            )
            expected_fingerprint = _risk_fingerprint(
                finding_id=str(finding_id),
                affected_gate=str(affected),
                evidence_sha256=str(risk.get("evidence_sha256")),
                medium_finding_count=fingerprint_medium_count,
                finding_set_digest=str(risk.get("finding_set_digest")),
                gate_definition_digest=str(risk.get("gate_definition_digest")),
                repository_commit=str(risk.get("repository_commit")),
            )
            if (
                risk.get("finding_fingerprint") != expected_fingerprint
                or risk.get("risk_id") != expected_fingerprint
            ) and not refreshing:
                fail(f"{label} finding identity/gate binding is invalid")
            if (
                freshness_commit
                and snap.get("status") != "aborted"
                and risk.get("repository_commit") != freshness_commit
                and not refreshing
            ):
                fail(
                    f"{label} accepted risk belongs to commit "
                    f"{risk.get('repository_commit')!r}, expected {freshness_commit!r}"
                )
            msgs.append(
                f"WARN  ACCEPTED RISK {finding_id} at {affected}: "
                f"{risk.get('reason', '(reason missing)')} (owner={risk.get('owner')}, "
                f"ticket={risk.get('ticket')})"
            )
        for affected, entry in risk_entries_by_gate.items():
            bound_ids = entry.get("accepted_risk_ids")
            expected_ids = [
                risk.get("risk_id") for risk in risks_by_gate.get(affected, [])
            ]
            refreshing = _refresh_gate is not None or _refresh_findings
            if not refreshing and (
                not isinstance(bound_ids, list)
                or sorted(cast(list[str], bound_ids))
                != sorted(cast(list[str], expected_ids))
            ):
                fail(
                    f"accepted-risk gate entry {affected!r} is not bound to the exact current "
                    "finding identities"
                )
            if len(expected_ids) != current_medium and not refreshing:
                fail(
                    f"accepted-risk gate {affected!r} covers {len(expected_ids)} finding(s), "
                    f"but open_findings.medium is {current_medium}"
                )
            if current_medium == 0 and not refreshing:
                clearance = entry.get("risk_clearance")
                if not isinstance(clearance, dict):
                    fail(
                        f"accepted-risk gate {affected!r} has no structured clearance for "
                        "the now-fixed Medium findings"
                    )
                else:
                    for field in (
                        "reason",
                        "cleared_by",
                        "owner",
                        "ticket",
                        "revisit",
                        "evidence_path",
                        "evidence_sha256",
                        "cleared_at",
                        "repository_commit",
                        "finding_set_digest",
                    ):
                        if not (
                            isinstance(clearance.get(field), str)
                            and clearance[field].strip()
                        ):
                            fail(
                                f"accepted-risk gate {affected!r} clearance has no "
                                f"non-empty {field!r}"
                            )
                    evidence = clearance.get("evidence_path")
                    if isinstance(evidence, str) and evidence:
                        evidence_path = resolve_evidence(evidence)
                        if not evidence_path.is_file():
                            fail(
                                f"accepted-risk gate {affected!r} clearance evidence is "
                                f"missing: {evidence}"
                            )
                        elif _sha256(evidence_path) != clearance.get("evidence_sha256"):
                            fail(
                                f"accepted-risk gate {affected!r} clearance evidence hash mismatch"
                            )
                    if (
                        freshness_commit
                        and snap.get("status") != "aborted"
                        and clearance.get("repository_commit") != freshness_commit
                    ):
                        fail(
                            f"accepted-risk gate {affected!r} clearance belongs to a "
                            "different commit"
                        )
                    if clearance.get("finding_set_digest") != str(
                        (snap.get("findings_evidence") or {}).get(
                            "finding_set_digest", ""
                        )
                    ):
                        fail(
                            f"accepted-risk gate {affected!r} clearance belongs to a "
                            "different recorded finding set"
                        )
        run_status = snap.get("status")
        resolved_gate_names = _resolved_gate_names(snap, gates)
        unresolved = [
            gate_name for gate_name in gates if gate_name not in resolved_gate_names
        ]
        if run_status == "active":
            for terminal_field in ("completed_at", "aborted_at", "final_summary"):
                if terminal_field in snap:
                    fail(
                        f"active schema-v2 run must not retain terminal field "
                        f"{terminal_field!r}"
                    )
            expected_stage = unresolved[0] if unresolved else "ready-to-complete"
            if gates and snap.get("stage") != expected_stage:
                fail(
                    f"active run stage {snap.get('stage')!r} does not match the first "
                    f"unresolved gate {expected_stage!r}"
                )
        elif run_status == "completed":
            if snap.get("stage") != "completed":
                fail("completed schema-v2 run must have stage 'completed'")
            completed_at = snap.get("completed_at")
            if not (isinstance(completed_at, str) and completed_at.strip()):
                fail("completed schema-v2 run has no completed_at timestamp")
            if "aborted_at" in snap:
                fail("completed schema-v2 run must not retain aborted_at")
            if unresolved:
                fail(
                    "completed schema-v2 run has unresolved gates: "
                    + ", ".join(unresolved)
                )
            summary = snap.get("final_summary")
            if not isinstance(summary, dict):
                fail("completed schema-v2 run has no final_summary evidence bundle")
            elif isinstance(completed_at, str):
                expected_summary = _final_summary_projection(
                    snap,
                    repository_commit=str(snap.get("current_commit")),
                    completed_at=completed_at,
                )
                if summary != expected_summary:
                    fail(
                        "final_summary differs from the deterministic terminal evidence projection"
                    )
        elif run_status == "aborted":
            if snap.get("stage") != "aborted":
                fail("aborted schema-v2 run must have stage 'aborted'")
            aborted_at = snap.get("aborted_at")
            if not (isinstance(aborted_at, str) and aborted_at.strip()):
                fail("aborted schema-v2 run has no aborted_at timestamp")
            for completed_field in ("completed_at", "final_summary"):
                if completed_field in snap:
                    fail(f"aborted schema-v2 run must not retain {completed_field!r}")

    # A recorded gate's evidence artifact must still exist on disk. Lenient on the upgrade path:
    # a snapshot with no gate_evidence map at all simply doesn't track evidence (the norm for
    # orchestrator-written snapshots) — stay silent; only flag a *partial* map that omits this gate.
    if gate is not None:
        evidence_map = snap.get("gate_evidence")
        if isinstance(evidence_map, dict) and gate in evidence_map:
            ev_val = evidence_map[gate]
            if not (isinstance(ev_val, str) and resolve_evidence(ev_val).is_file()):
                fail(
                    f"last_gate_passed {gate!r} is recorded passed but its evidence file is "
                    f"missing: {ev_val!r}"
                )
        elif isinstance(evidence_map, dict) and not history:
            msgs.append(
                f"WARN  last_gate_passed {gate!r} has no recorded gate_evidence path"
            )
        if isinstance(overrides, dict) and gate in overrides:
            msgs.append(
                f"WARN  gate {gate!r} was force-closed (override: {overrides[gate]!r}) — review"
            )

    for field in ("task", "stage", "next"):
        if field not in snap or snap[field] is None:
            msgs.append(f"WARN  snapshot has no {field!r} (resume context is weaker)")

    if ok:
        msgs.append(
            f"OK    pipeline snapshot is coherent (stage: {snap.get('stage', '?')})"
        )
    return ok, msgs


def status(target: str | Path) -> tuple[bool, list[str]]:
    """Print a human-readable summary of the current pipeline snapshot (no writes)."""
    snap, err = _load_snapshot(target)
    if err:
        return False, [f"FAIL  {err}"]
    if snap is None:
        return True, ["no pipeline run in progress (no snapshot)"]

    from claude_kit.maker_checker import is_maker_checker_snapshot

    if is_maker_checker_snapshot(snap):
        state = snap.get("maker_checker")
        state = state if isinstance(state, dict) else {}
        bindings = state.get("bindings")
        bindings = bindings if isinstance(bindings, dict) else {}
        maker_msgs = [
            f"run:     {snap.get('run_id', '(none)')}   status: {snap.get('status', '?')}",
            "type:    maker-checker",
            f"task:    {snap.get('task', '(none)')}",
            f"kind:    {snap.get('kind', '?')}",
            f"stage:   {snap.get('stage', '(none)')}",
            f"iteration: {state.get('iteration', '?')} / "
            f"{(state.get('max_revisions', 0) + 1) if isinstance(state.get('max_revisions'), int) else '?'}",
        ]
        for slot in ("maker", "reviewer"):
            binding = bindings.get(slot)
            if isinstance(binding, dict):
                maker_msgs.append(
                    f"{slot}: {binding.get('provider', '?')} / "
                    f"{binding.get('requested_model') or '(provider default)'}"
                )
        artifact = state.get("artifact")
        if isinstance(artifact, dict):
            maker_msgs.append(
                f"artifact: {artifact.get('path', '?')} "
                f"(sha256 {str(artifact.get('digest', ''))[:12]}…)"
            )
        human_stop = snap.get("human_stop")
        if isinstance(human_stop, dict):
            maker_msgs.append(
                f"human stop: {human_stop.get('reason', '?')} — "
                f"{human_stop.get('message', '?')}"
            )
        unsafe_dispatch = state.get("unsafe_dispatch")
        if isinstance(unsafe_dispatch, dict):
            maker_msgs.append(
                "unsafe dispatch: "
                f"{unsafe_dispatch.get('attempt_id', '?')} / "
                f"{unsafe_dispatch.get('route', '?')} / host "
                f"{unsafe_dispatch.get('dispatch_id', '?')}#"
                f"{unsafe_dispatch.get('dispatch_attempt', '?')}"
            )
            maker_msgs.append(
                "reconcile: ckit maker-checker confirm-terminated . "
                f"--run-id {snap.get('run_id', '?')} "
                f"--attempt-id {unsafe_dispatch.get('attempt_id', '?')} "
                f"--route {unsafe_dispatch.get('route', '?')} "
                f"--dispatch-id {unsafe_dispatch.get('dispatch_id', '?')} "
                f"--dispatch-attempt {unsafe_dispatch.get('dispatch_attempt', '?')} "
                "--evidence 'DESCRIBE VERIFIED TERMINATION'"
            )
        archives = snap.get("run_archives")
        if isinstance(archives, list) and archives:
            maker_msgs.append(f"archived terminal runs: {len(archives)}")
        maker_msgs.append(f"next:    {snap.get('next', '(none)')}")
        return True, maker_msgs

    version, version_error = _snapshot_version(snap)
    msgs: list[str] = []
    if version_error:
        msgs.append(f"WARN  {version_error}")
    elif version == 1:
        msgs.append("WARN  legacy schema v1 snapshot (read-only; adopt to migrate)")
    else:
        msgs.append(
            f"run:     {snap.get('run_id', '(none)')}   status: {snap.get('status', '?')}"
        )
        if snap.get("start_type") == "adopted":
            adoption = snap.get("adoption") or {}
            msgs.append(
                f"ADOPTED:  at {adoption.get('starting_gate', '?')} by "
                f"{adoption.get('adopted_by', '?')} — {adoption.get('reason', '?')}"
            )
    msgs.append(f"task:    {snap.get('task', '(none)')}")
    profile = snap.get("profile", "?")
    scope = snap.get("scope", "?")
    mode = snap.get("mode", "?")
    msgs.append(f"profile: {profile}   scope: {scope}   mode: {mode}")
    msgs.append(f"stage:   {snap.get('stage', '(none)')}")
    lanes = snap.get("lanes") or {}
    if lanes:
        msgs.append("lanes:")
        for lane, state in lanes.items():
            msgs.append(f"  - {lane}: {state}")
    msgs.append(f"last gate passed: {snap.get('last_gate_passed', '(none)')}")
    history = _history(snap)
    if history:
        msgs.append("gate history:")
        for entry in history:
            bits = [str(entry.get("gate", "?")), str(entry.get("status", "?"))]
            if entry.get("verification"):
                bits.append(f"verification={entry['verification']}")
            if entry.get("override"):
                bits.append(f"override={entry['override']!r}")
            if entry.get("reason"):
                bits.append(f"reason={entry['reason']!r}")
            msgs.append(
                f"  - {': '.join(bits[:2])} ({', '.join(bits[2:])})"
                if bits[2:]
                else f"  - {': '.join(bits[:2])}"
            )
    findings = snap.get("open_findings") or {}
    findings_evidence = snap.get("findings_evidence")
    if version == PIPELINE_SCHEMA_VERSION and not isinstance(findings_evidence, dict):
        msgs.append(
            "findings: UNRECORDED — placeholder counts are not evidence; run "
            "`pipeline record-findings`"
        )
    elif findings:
        rendered = ", ".join(f"{k}={v}" for k, v in findings.items())
        msgs.append(f"open findings: {rendered}")
    if isinstance(findings_evidence, dict):
        evidence_path = findings_evidence.get("evidence_path", "?")
        finding_digest = str(findings_evidence.get("finding_set_digest", ""))
        msgs.append(
            f"findings evidence: {evidence_path} (finding set: {finding_digest[:12]}…)"
        )
    risks = snap.get("accepted_risks") or []
    if isinstance(risks, list) and risks:
        msgs.append("ACCEPTED RISKS:")
        for risk in risks:
            if isinstance(risk, dict):
                msgs.append(
                    f"  - ACCEPTED RISK {risk.get('finding_id', '?')} at "
                    f"{risk.get('affected_gate', '?')}: {risk.get('reason', '?')} "
                    f"(accepted_by={risk.get('accepted_by', '?')}, "
                    f"owner={risk.get('owner', '?')}, ticket={risk.get('ticket', '?')}, "
                    f"revisit={risk.get('revisit', '?')})"
                )
    human_stops = snap.get("human_stops") or []
    if isinstance(human_stops, list) and human_stops:
        msgs.append("human stops:")
        for stop in human_stops:
            if isinstance(stop, dict):
                msgs.append(
                    f"  - {stop.get('stop_id', '?')}: {stop.get('status', '?')} "
                    f"({stop.get('reason', '?')}) — {stop.get('message', '?')}"
                )
    if isinstance(snap.get("final_summary"), dict):
        msgs.append(
            "final evidence summary: persisted in this schema-v2 pipeline snapshot "
            f"({_snapshot_rel(target)})"
        )
    archives = snap.get("run_archives")
    if isinstance(archives, list) and archives:
        msgs.append(f"archived terminal runs: {len(archives)}")
    msgs.append(f"next:    {snap.get('next', '(none)')}")
    return True, msgs


def record_findings(
    target: str | Path,
    *,
    critical: int,
    high: int,
    medium: int,
    low: int,
    cosmetic: int,
    evidence: str | Path,
) -> tuple[bool, list[str]]:
    """Atomically bind the exact current finding counts to evidence and repository HEAD.

    This is the only supported schema-v2 write path for ``open_findings``. A new record makes any
    prior accepted-risk attestations stale by changing the finding-set digest; those records must
    then be explicitly refreshed before another gate transition or completion.
    """
    counts = {
        "critical": critical,
        "high": high,
        "medium": medium,
        "low": low,
        "cosmetic": cosmetic,
    }
    for severity, count in counts.items():
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            return False, [
                f"FAIL  {severity} finding count must be a non-negative integer, got {count!r}"
            ]

    try:
        fs = ProjectFS(Path(target).expanduser())
        root = fs.root
        path = fs.path(_snapshot_rel(target))
    except (UnsafePathError, OSError, ValueError) as exc:
        return False, [f"FAIL  unsafe pipeline state path: {exc}"]

    try:
        evidence_path, stored_evidence, warnings = _stored_evidence(root, evidence)
    except FileNotFoundError as exc:
        return False, [f"FAIL  {exc}"]
    if warnings or Path(stored_evidence).is_absolute():
        return False, [
            "FAIL  findings evidence must be a regular file contained inside the project root"
        ]

    msgs: list[str] = []
    try:
        with _pipeline_write_lock(fs, path, msgs=msgs):
            snap, err = _load_snapshot(target)
            if err:
                return False, [f"FAIL  {err}"]
            run, identity, problem = _active_v2_run(target, snap)
            if problem or run is None or identity is None:
                return False, [f"FAIL  {problem or 'invalid run'}"]
            coherent, validation_messages = validate(
                target,
                strict=True,
                _refresh_findings=True,
            )
            if not coherent:
                return False, validation_messages

            workspace_checkpoint, workspace_problem = _managed_workspace_checkpoint(
                root, run
            )
            if workspace_problem:
                return False, [f"FAIL  {workspace_problem}"]

            managed_bundle: dict[str, Any] | None = None
            contract = run.get("managed_execution")
            if (
                isinstance(contract, dict)
                and contract.get("evidence_contract_version")
                == EVIDENCE_CONTRACT_VERSION
            ):
                managed_gate = _next_unresolved_gate(run)
                if managed_gate is None:
                    return False, [
                        "FAIL  managed findings cannot be refreshed after every gate resolved"
                    ]
                managed_bundle, bundle_problem = _managed_findings_bundle(
                    fs, run, gate=managed_gate
                )
                if bundle_problem or managed_bundle is None:
                    successful = [
                        item
                        for item in run.get("stage_history", [])
                        if isinstance(item, dict) and item.get("status") == "succeeded"
                    ]
                    if successful or run.get("gate_history") or any(counts.values()):
                        return False, [
                            f"FAIL  {bundle_problem or 'managed findings bundle is unavailable'}"
                        ]
                    managed_bundle = None
                if managed_bundle is not None:
                    derived_counts = cast(
                        dict[str, int], managed_bundle["document"]["counts"]
                    )
                    if counts != derived_counts:
                        return False, [
                            "FAIL  supplied finding counts differ from canonical owner-stage "
                            f"evidence (supplied={counts}, derived={derived_counts})"
                        ]
                    stored_evidence = str(managed_bundle["path"])
                    evidence_sha = str(managed_bundle["sha256"])
                else:
                    _content, evidence_sha, _content_size = _read_managed_file_bounded(
                        fs,
                        stored_evidence,
                        maximum_bytes=MAX_EVIDENCE_ENVELOPE_BYTES,
                    )
            else:
                _content, evidence_sha, _content_size = _read_managed_file_bounded(
                    fs,
                    stored_evidence,
                    maximum_bytes=MAX_EVIDENCE_ENVELOPE_BYTES,
                )
            finding_digest = _finding_set_digest(
                counts,
                evidence_sha256=evidence_sha,
                repository_commit=identity["commit"],
                workspace_content_digest=(
                    workspace_checkpoint.content_digest
                    if workspace_checkpoint is not None
                    else None
                ),
            )
            recorded_at = _utc_now()
            run["open_findings"] = dict(counts)
            run["findings_evidence"] = {
                "counts": dict(counts),
                "evidence_path": stored_evidence,
                "evidence_sha256": evidence_sha,
                "finding_set_digest": finding_digest,
                "repository_commit": identity["commit"],
                "recorded_at": recorded_at,
            }
            if managed_bundle is not None:
                managed_document = cast(dict[str, Any], managed_bundle["document"])
                run["findings_evidence"].update(
                    {
                        "managed_gate": managed_document["gate"],
                        "owner_stage": managed_document["owner_stage"],
                        "owner_dispatch_id": managed_document["owner_dispatch_id"],
                        "owner_dispatch_attempt": managed_document[
                            "owner_dispatch_attempt"
                        ],
                        "owner_output_sha256": managed_document["owner_output_sha256"],
                        "evidence_set_digest": managed_document["evidence_set_digest"],
                        "finding_ids": [
                            item["finding_id"] for item in managed_document["findings"]
                        ],
                        "finding_index": managed_document["findings"],
                    }
                )
            if workspace_checkpoint is not None:
                run["findings_evidence"].update(
                    {
                        "workspace_head_commit": workspace_checkpoint.head_commit,
                        "workspace_content_digest": workspace_checkpoint.content_digest,
                    }
                )
            run["current_commit"] = identity["commit"]
            _write_snapshot_locked(target, run)
        rendered = ", ".join(
            f"{severity}={counts[severity]}" for severity in sorted(counts)
        )
        msgs.append(
            f"OK    recorded current findings ({rendered}); evidence: {stored_evidence}, "
            f"finding set: {finding_digest[:12]}…"
        )
        return True, msgs
    except TimeoutError as exc:
        return False, [f"FAIL  {exc}"]
    except (UnsafePathError, OSError, ValueError) as exc:
        return False, [f"FAIL  unsafe pipeline state mutation refused: {exc}"]


def _order_check(
    gates: list[str],
    snap: dict[str, Any],
    gate: str,
    *,
    action: str,
) -> str | None:
    """Return a FAIL message when recording ``gate`` would violate the installed order."""
    if not gates or gate not in gates:
        return None
    version, _ = _snapshot_version(snap)
    legacy = version == 1
    pos = _position(
        gates,
        _history(snap),
        snap.get("last_gate_passed"),
        legacy=legacy,
        adoption=snap.get("adoption"),
    )
    if pos is None:
        if legacy:
            return None
        expected: str | None = gates[0]
        if gate != expected:
            return (
                f"cannot {action} {gate!r} out of order: the next gate is {expected!r}"
            )
        return None
    idx = gates.index(gate)
    if idx <= pos:
        return (
            f"cannot {action} {gate!r}: the run is already at {gates[pos]!r} "
            f"(gate {gate!r} is recorded or superseded)"
        )
    expected = gates[pos + 1] if pos + 1 < len(gates) else None
    if expected is not None and idx > pos + 1:
        return (
            f"cannot {action} {gate!r} out of order: the next gate is {expected!r}. "
            "Resolve that gate first (or use not-applicable when its canonical condition holds)."
        )
    return None


def close_gate(
    target: str | Path,
    gate: str,
    evidence: str | Path,
    *,
    force: bool = False,
    override_reason: str | None = None,
    strict: bool = False,
) -> tuple[bool, list[str]]:
    """Record the next gate as an ordinary pass with content-addressed evidence.

    ``force`` remains in the Python signature for 0.x API compatibility, but is never a waiver:
    Critical/High are unwaivable and Medium must use :func:`accept_risk`.
    """
    del strict  # schema-v2 lifecycle mutations always fail closed
    msgs: list[str] = []
    try:
        fs = ProjectFS(Path(target).expanduser())
        root = fs.root
    except (UnsafePathError, OSError, ValueError) as exc:
        return False, [f"FAIL  unsafe pipeline project root: {exc}"]
    try:
        evidence_path, stored_evidence, warnings = _stored_evidence(root, evidence)
        msgs.extend(warnings)
    except FileNotFoundError as exc:
        return False, [f"FAIL  {exc}"]
    _install, install_error = _read_install_snapshot(target)
    if install_error:
        return False, [f"FAIL  {install_error}"]
    gates = installed_gates(target)
    if gate not in gates:
        return False, [
            f"FAIL  {gate!r} is not a gate of this profile (choices: {', '.join(gates)})"
        ]
    if force or override_reason:
        snap, _ = _load_snapshot(target)
        blocking = _blocking_findings(snap or {})
        unwaivable = {k: v for k, v in blocking.items() if k in {"critical", "high"}}
        if unwaivable:
            rendered = ", ".join(f"{k}={v}" for k, v in unwaivable.items())
            return False, [
                f"FAIL  {rendered}: Critical and High findings are never waivable"
            ]
        if blocking.get("medium"):
            return False, [
                "FAIL  Medium findings never become an ordinary pass; use pipeline accept-risk"
            ]
        return False, [
            "FAIL  --force is reserved for out-of-band repair/migration and cannot record a "
            "normal gate transition"
        ]

    try:
        snap_path = fs.path(_snapshot_rel(target))
    except (UnsafePathError, OSError, ValueError) as exc:
        return False, [f"FAIL  unsafe pipeline state path: {exc}"]
    try:
        with _pipeline_write_lock(fs, snap_path, msgs=msgs):
            snap, err = _load_snapshot(target)
            if err:
                return False, [f"FAIL  {err}"]
            run, identity, problem = _active_v2_run(target, snap)
            if problem or run is None or identity is None:
                return False, [f"FAIL  {problem or 'invalid run'}"]
            workspace_checkpoint, owner_problem = _managed_gate_transition_checkpoint(
                root, run, gate
            )
            if owner_problem:
                return False, [f"FAIL  {owner_problem}"]
            prevalidation_contract = run.get("managed_execution")
            coherent, validation_messages = validate(
                target,
                strict=True,
                _refresh_findings=(
                    isinstance(prevalidation_contract, dict)
                    and prevalidation_contract.get("evidence_contract_version")
                    == EVIDENCE_CONTRACT_VERSION
                ),
            )
            if not coherent:
                return False, validation_messages
            managed_contract = run.get("managed_execution")
            if (
                workspace_checkpoint is not None
                and isinstance(managed_contract, dict)
                and managed_contract.get("evidence_contract_version")
                == EVIDENCE_CONTRACT_VERSION
            ):
                findings_bundle, findings_bundle_problem = _managed_findings_bundle(
                    fs, run, gate=gate
                )
                if findings_bundle_problem or findings_bundle is None:
                    return False, [
                        f"FAIL  {findings_bundle_problem or 'managed findings evidence is unavailable'}"
                    ]
                derived_counts = findings_bundle["document"]["counts"]
                if run.get("open_findings") != derived_counts:
                    return False, [
                        "FAIL  open finding counts differ from the exact owner-stage evidence "
                        f"for managed gate {gate!r}"
                    ]
                run["findings_evidence"] = _managed_findings_record(
                    run,
                    findings_bundle,
                    repository_commit=identity["commit"],
                    workspace_checkpoint=workspace_checkpoint,
                )
            findings_problem = _current_findings_problem(
                root, run, current_commit=identity["commit"]
            )
            if findings_problem:
                return False, [f"FAIL  {findings_problem}"]
            gates = list(run["ordered_gates"])
            blocking = _blocking_findings(run)
            if blocking:
                rendered = ", ".join(
                    f"{sev}={count}" for sev, count in blocking.items()
                )
                if blocking.get("critical") or blocking.get("high"):
                    return False, [
                        f"FAIL  cannot close {gate!r}: {rendered}; Critical and High findings "
                        "are never waivable"
                    ]
                return False, [
                    f"FAIL  cannot close {gate!r}: {rendered}; Medium requires the structured "
                    "pipeline accept-risk transition"
                ]

            order_problem = _order_check(gates, run, gate, action="close")
            if order_problem:
                return False, [f"FAIL  {order_problem}"]
            transition_problem = _headless_transition_problem(
                run, action="close-gate", gate=gate
            )
            if transition_problem:
                return False, [f"FAIL  {transition_problem}"]

            managed_bundle: dict[str, Any] | None = None
            contract = run.get("managed_execution")
            if (
                isinstance(contract, dict)
                and contract.get("evidence_contract_version")
                == EVIDENCE_CONTRACT_VERSION
            ):
                findings_record = run.get("findings_evidence")
                if (
                    not isinstance(findings_record, dict)
                    or findings_record.get("managed_gate") != gate
                ):
                    return False, [
                        f"FAIL  managed gate {gate!r} requires findings derived from "
                        "its exact owner-stage evidence"
                    ]
                managed_bundle, bundle_problem = _managed_gate_bundle(
                    fs, run, gate=gate
                )
                if bundle_problem or managed_bundle is None:
                    return False, [
                        f"FAIL  {bundle_problem or 'managed gate evidence is unavailable'}"
                    ]
                stored_evidence = str(managed_bundle["path"])
                evidence_path = fs.path(stored_evidence)
            entry: dict[str, Any] = {
                "gate": gate,
                "status": "passed",
                "evidence_path": stored_evidence,
                "evidence_sha256": _sha256(evidence_path),
                "verification": "agent",
                "recorded_at": _utc_now(),
                "repository_commit": identity["commit"],
            }
            if managed_bundle is not None:
                bundle_document = cast(dict[str, Any], managed_bundle["document"])
                entry.update(
                    {
                        "owner_stage": bundle_document["owner_stage"],
                        "owner_dispatch_id": bundle_document["owner_dispatch_id"],
                        "owner_dispatch_attempt": bundle_document[
                            "owner_dispatch_attempt"
                        ],
                        "owner_output_sha256": bundle_document["owner_output_sha256"],
                        "evidence_set_digest": bundle_document["evidence_set_digest"],
                    }
                )
            if workspace_checkpoint is not None:
                entry.update(
                    {
                        "workspace_head_commit": workspace_checkpoint.head_commit,
                        "workspace_content_digest": workspace_checkpoint.content_digest,
                    }
                )
            history = run.get("gate_history")
            if not isinstance(history, list):
                history = []
            history.append(entry)
            run["gate_history"] = history

            run["last_gate_passed"] = gate
            evidence_map = run.get("gate_evidence")
            if not isinstance(evidence_map, dict):
                evidence_map = {}
            evidence_map[gate] = stored_evidence
            run["gate_evidence"] = evidence_map
            run["current_commit"] = identity["commit"]
            _advance_run(run, gates, gate)
            _consume_headless_transition_allowance(run, action="close-gate", gate=gate)

            _write_snapshot_locked(target, run)
        msgs.append(
            f"OK    gate {gate!r} recorded passed "
            f"(evidence: {stored_evidence}, sha256: {entry['evidence_sha256'][:12]}…)"
        )
        return True, msgs
    except TimeoutError as exc:
        return False, [f"FAIL  {exc}"]
    except (UnsafePathError, OSError, ValueError) as exc:
        return False, [f"FAIL  unsafe pipeline state mutation refused: {exc}"]


def skip_gate(
    target: str | Path,
    gate: str,
    reason: str,
    *,
    condition: str | None = None,
    evidence: str | Path | None = None,
    strict: bool = False,
) -> tuple[bool, list[str]]:
    """Compatibility spelling for structured ``not-applicable`` transitions."""
    if condition is None or evidence is None:
        return False, [
            "FAIL  legacy skip-gate is no longer a valid transition; provide --condition and "
            "--evidence (the recorded status will be not-applicable)"
        ]
    return not_applicable(
        target,
        gate,
        condition=condition,
        reason=reason,
        evidence=evidence,
        strict=strict,
    )


def not_applicable(
    target: str | Path,
    gate: str,
    *,
    condition: str,
    reason: str,
    evidence: str | Path,
    strict: bool = False,
) -> tuple[bool, list[str]]:
    """Resolve the next conditional gate using canonical condition metadata and evidence."""
    del strict  # schema-v2 lifecycle mutations always fail closed
    if not (condition and condition.strip()):
        return False, ["FAIL  not-applicable requires a condition identifier"]
    if not (reason and reason.strip()):
        return False, ["FAIL  not-applicable requires a non-empty reason"]
    try:
        fs = ProjectFS(Path(target).expanduser())
        root = fs.root
    except (UnsafePathError, OSError, ValueError) as exc:
        return False, [f"FAIL  unsafe pipeline project root: {exc}"]
    msgs: list[str] = []
    try:
        evidence_path, stored_evidence, warnings = _stored_evidence(root, evidence)
        msgs.extend(warnings)
    except FileNotFoundError as exc:
        return False, [f"FAIL  {exc}"]
    _install, install_error = _read_install_snapshot(target)
    if install_error:
        return False, [f"FAIL  {install_error}"]
    gates = installed_gates(target)
    if gate not in gates:
        return False, [f"FAIL  {gate!r} is not a gate of this profile"]
    definitions = installed_gate_definitions(target)
    definition = definitions.get(gate)
    if definition is None:
        return False, [f"FAIL  {gate!r} has no canonical gate definition"]
    if definition.requirement != "conditional" or not definition.skippable:
        return False, [f"FAIL  required gate {gate!r} cannot be marked not-applicable"]
    if condition not in definition.skip_conditions:
        return False, [
            f"FAIL  unknown condition {condition!r} for {gate!r}; choices: "
            f"{', '.join(definition.skip_conditions)}"
        ]
    try:
        path = fs.path(_snapshot_rel(target))
    except (UnsafePathError, OSError, ValueError) as exc:
        return False, [f"FAIL  unsafe pipeline state path: {exc}"]
    try:
        with _pipeline_write_lock(fs, path, msgs=msgs):
            snap, err = _load_snapshot(target)
            if err:
                return False, [f"FAIL  {err}"]
            run, identity, problem = _active_v2_run(target, snap)
            if problem or run is None or identity is None:
                return False, [f"FAIL  {problem or 'invalid run'}"]
            workspace_checkpoint, owner_problem = _managed_gate_transition_checkpoint(
                root, run, gate, allow_skipped_owner=True
            )
            if owner_problem:
                return False, [f"FAIL  {owner_problem}"]
            skipped_owner, _ = _managed_owner_stage_record(
                run, gate, allow_skipped=True
            )
            if (
                isinstance(skipped_owner, dict)
                and skipped_owner.get("decision") is False
                and skipped_owner.get("not_applicable_condition") != condition
            ):
                return False, [
                    "FAIL  not-applicable condition does not match the canonical "
                    "skipped-owner attestation"
                ]
            managed_contract = run.get("managed_execution")
            managed_typed = (
                isinstance(managed_contract, dict)
                and managed_contract.get("evidence_contract_version")
                == EVIDENCE_CONTRACT_VERSION
            )
            predicate_problem = _managed_not_applicable_predicate_problem(
                run, gate=gate, condition=condition
            )
            if predicate_problem:
                return False, [f"FAIL  {predicate_problem}"]
            coherent, validation_messages = validate(
                target,
                strict=True,
                _refresh_findings=managed_typed,
            )
            if not coherent:
                return False, validation_messages
            if managed_typed and not (
                isinstance(skipped_owner, dict)
                and skipped_owner.get("decision") is False
            ):
                findings_bundle, findings_bundle_problem = _managed_findings_bundle(
                    fs, run, gate=gate
                )
                if findings_bundle_problem or findings_bundle is None:
                    return False, [
                        f"FAIL  {findings_bundle_problem or 'managed findings evidence is unavailable'}"
                    ]
                derived_counts = findings_bundle["document"]["counts"]
                if run.get("open_findings") != derived_counts:
                    return False, [
                        "FAIL  open finding counts differ from the exact owner-stage evidence "
                        f"for managed gate {gate!r}"
                    ]
                assert workspace_checkpoint is not None
                run["findings_evidence"] = _managed_findings_record(
                    run,
                    findings_bundle,
                    repository_commit=identity["commit"],
                    workspace_checkpoint=workspace_checkpoint,
                )
            findings_problem = _current_findings_problem(
                root, run, current_commit=identity["commit"]
            )
            if findings_problem:
                return False, [f"FAIL  {findings_problem}"]
            gates = list(run["ordered_gates"])
            order_problem = _order_check(gates, run, gate, action="mark not-applicable")
            if order_problem:
                return False, [f"FAIL  {order_problem}"]
            blocking = _blocking_findings(run)
            if blocking:
                rendered = ", ".join(
                    f"{severity}={blocking[severity]}"
                    for severity in BLOCKING_FINDINGS
                    if severity in blocking
                )
                return False, [
                    f"FAIL  cannot mark gate {gate!r} not-applicable while blocking "
                    f"findings remain ({rendered})"
                ]
            transition_problem = _headless_transition_problem(
                run, action="not-applicable", gate=gate
            )
            if transition_problem:
                return False, [f"FAIL  {transition_problem}"]
            managed_bundle: dict[str, Any] | None = None
            if managed_typed:
                managed_bundle, bundle_problem = _managed_not_applicable_bundle(
                    fs,
                    run,
                    gate=gate,
                    condition=condition,
                    reason=reason.strip(),
                    condition_source=evidence_path,
                )
                if bundle_problem or managed_bundle is None:
                    return False, [
                        f"FAIL  {bundle_problem or 'managed not-applicable evidence is unavailable'}"
                    ]
                stored_evidence = str(managed_bundle["path"])
                evidence_path = fs.path(stored_evidence)
            entry: dict[str, Any] = {
                "gate": gate,
                "status": "not-applicable",
                "condition": condition,
                "reason": reason.strip(),
                "condition_evidence_path": stored_evidence,
                "condition_evidence_sha256": _sha256(evidence_path),
                "verification": "agent",
                "recorded_at": _utc_now(),
                "repository_commit": identity["commit"],
            }
            if managed_bundle is not None:
                bundle_document = cast(dict[str, Any], managed_bundle["document"])
                owner_document = cast(dict[str, Any], bundle_document["owner"])
                condition_document = cast(
                    dict[str, Any], bundle_document["condition_evidence"]
                )
                entry.update(
                    {
                        "owner_stage": owner_document["stage"],
                        "condition_source_path": condition_document["artifact_path"],
                        "condition_source_sha256": condition_document[
                            "artifact_sha256"
                        ],
                    }
                )
                if owner_document["kind"] == "succeeded":
                    entry.update(
                        {
                            "owner_dispatch_id": owner_document["dispatch_id"],
                            "owner_dispatch_attempt": owner_document[
                                "dispatch_attempt"
                            ],
                            "owner_output_sha256": owner_document["output_sha256"],
                            "evidence_set_digest": owner_document[
                                "evidence_set_digest"
                            ],
                        }
                    )
                else:
                    entry["owner_skip_attestation_sha256"] = owner_document[
                        "attestation_sha256"
                    ]
            if workspace_checkpoint is not None:
                entry.update(
                    {
                        "workspace_head_commit": workspace_checkpoint.head_commit,
                        "workspace_content_digest": workspace_checkpoint.content_digest,
                    }
                )
            history = run.get("gate_history")
            if not isinstance(history, list):
                history = []
            history.append(entry)
            run["gate_history"] = history
            run["current_commit"] = identity["commit"]
            _advance_run(run, gates, gate)
            _consume_headless_transition_allowance(
                run, action="not-applicable", gate=gate
            )
            _write_snapshot_locked(target, run)
        msgs.append(
            f"OK    gate {gate!r} recorded not-applicable under condition {condition!r}"
        )
        return True, msgs
    except TimeoutError as exc:
        return False, [f"FAIL  {exc}"]
    except (UnsafePathError, OSError, ValueError) as exc:
        return False, [f"FAIL  unsafe pipeline state mutation refused: {exc}"]


def accept_risk(
    target: str | Path,
    gate: str,
    *,
    finding_id: str,
    reason: str,
    accepted_by: str,
    owner: str,
    ticket: str,
    revisit: str,
    evidence: str | Path,
    compensating_control: str | None = None,
    refresh: bool = False,
    supersedes_finding_id: str | None = None,
    strict: bool = False,
) -> tuple[bool, list[str]]:
    """Accept one Medium finding; optionally re-attest stale risk at the same gate.

    ``refresh`` is an explicit recovery path after commit, evidence, count, or finding identity
    changes. It preserves the superseded record in ``accepted_risk_history`` and rebinds the gate
    entry atomically. It cannot repair unrelated ledger/schema failures or a gate-policy change.
    """
    del strict  # schema-v2 lifecycle mutations always fail closed
    fields = {
        "finding id": finding_id,
        "reason": reason,
        "accepted by": accepted_by,
        "owner": owner,
        "ticket": ticket,
        "revisit": revisit,
    }
    for label, value in fields.items():
        if not (isinstance(value, str) and value.strip()):
            return False, [f"FAIL  accept-risk requires a non-empty {label}"]
    try:
        fs = ProjectFS(Path(target).expanduser())
        root = fs.root
    except (UnsafePathError, OSError, ValueError) as exc:
        return False, [f"FAIL  unsafe pipeline project root: {exc}"]
    msgs: list[str] = []
    try:
        evidence_path, stored_evidence, warnings = _stored_evidence(root, evidence)
        msgs.extend(warnings)
    except FileNotFoundError as exc:
        return False, [f"FAIL  {exc}"]
    _install, install_error = _read_install_snapshot(target)
    if install_error:
        return False, [f"FAIL  {install_error}"]
    gates = installed_gates(target)
    if gate not in gates:
        return False, [f"FAIL  {gate!r} is not a gate of this profile"]
    try:
        path = fs.path(_snapshot_rel(target))
    except (UnsafePathError, OSError, ValueError) as exc:
        return False, [f"FAIL  unsafe pipeline state path: {exc}"]
    try:
        with _pipeline_write_lock(fs, path, msgs=msgs):
            snap, err = _load_snapshot(target)
            if err:
                return False, [f"FAIL  {err}"]
            run, identity, problem = _active_v2_run(target, snap)
            if problem or run is None or identity is None:
                return False, [f"FAIL  {problem or 'invalid run'}"]
            workspace_checkpoint, owner_problem = _managed_gate_transition_checkpoint(
                root, run, gate
            )
            if owner_problem:
                return False, [f"FAIL  {owner_problem}"]
            coherent, validation_messages = validate(
                target,
                strict=True,
                _refresh_gate=gate if refresh else None,
            )
            if not coherent:
                return False, validation_messages
            findings_problem = _current_findings_problem(
                root, run, current_commit=identity["commit"]
            )
            if findings_problem:
                return False, [f"FAIL  {findings_problem}"]
            finding_set_digest = str(run["findings_evidence"]["finding_set_digest"])
            blocking = _blocking_findings(run)
            if blocking.get("critical") or blocking.get("high"):
                rendered = ", ".join(
                    f"{severity}={blocking[severity]}"
                    for severity in ("critical", "high")
                    if blocking.get(severity)
                )
                return False, [
                    f"FAIL  {rendered}: Critical and High are never waivable"
                ]
            medium_count = blocking.get("medium", 0)
            if medium_count < 1 and not refresh:
                return False, [
                    "FAIL  accept-risk requires at least one open Medium finding"
                ]
            managed_contract = run.get("managed_execution")
            managed_typed = (
                isinstance(managed_contract, dict)
                and managed_contract.get("evidence_contract_version")
                == EVIDENCE_CONTRACT_VERSION
            )
            managed_evidence_sha: str | None = None
            if managed_typed:
                findings_record = run.get("findings_evidence")
                finding_index = (
                    findings_record.get("finding_index")
                    if isinstance(findings_record, dict)
                    else None
                )
                exact_medium_ids = (
                    {
                        str(item.get("finding_id"))
                        for item in finding_index
                        if isinstance(item, dict) and item.get("severity") == "medium"
                    }
                    if isinstance(finding_index, list)
                    else set()
                )
                if (
                    not isinstance(findings_record, dict)
                    or findings_record.get("managed_gate") != gate
                    or finding_id.strip() not in exact_medium_ids
                ):
                    return False, [
                        f"FAIL  {finding_id.strip()!r} is not an exact current Medium "
                        f"finding id in owner evidence for gate {gate!r}"
                    ]
                try:
                    stored_evidence, managed_evidence_sha = (
                        _materialize_managed_risk_evidence(
                            fs,
                            run,
                            gate=gate,
                            finding_id=finding_id.strip(),
                            source_relative=stored_evidence,
                        )
                    )
                except (FileNotFoundError, OSError, UnsafePathError, ValueError) as exc:
                    return False, [
                        f"FAIL  cannot persist managed accepted-risk evidence: {exc}"
                    ]
            gates = list(run["ordered_gates"])
            history = run.get("gate_history")
            if not isinstance(history, list):
                history = []
            gate_entry = next(
                (
                    entry
                    for entry in history
                    if isinstance(entry, dict)
                    and entry.get("gate") == gate
                    and entry.get("status") == "accepted-risk"
                ),
                None,
            )
            if refresh:
                if gate_entry is None:
                    return False, [
                        f"FAIL  --refresh requires an existing accepted-risk resolution at {gate!r}"
                    ]
            else:
                order_problem = _order_check(gates, run, gate, action="accept risk at")
                if order_problem:
                    return False, [f"FAIL  {order_problem}"]
            risks = run.get("accepted_risks")
            if not isinstance(risks, list):
                risks = []
            existing_same = next(
                (
                    risk
                    for risk in risks
                    if isinstance(risk, dict)
                    and risk.get("affected_gate") == gate
                    and risk.get("finding_id") == finding_id.strip()
                ),
                None,
            )
            if existing_same is not None and not refresh:
                return False, [
                    f"FAIL  finding {finding_id.strip()!r} already has an acceptance at {gate!r}"
                ]
            superseded: dict[str, Any] | None = None
            if refresh:
                replace_id = (
                    supersedes_finding_id.strip()
                    if isinstance(supersedes_finding_id, str)
                    and supersedes_finding_id.strip()
                    else finding_id.strip()
                )
                superseded = next(
                    (
                        risk
                        for risk in risks
                        if isinstance(risk, dict)
                        and risk.get("affected_gate") == gate
                        and risk.get("finding_id") == replace_id
                    ),
                    None,
                )
                gate_risks_before = [
                    risk
                    for risk in risks
                    if isinstance(risk, dict) and risk.get("affected_gate") == gate
                ]
                stale_reasons = {
                    id(risk): _accepted_risk_staleness(
                        root,
                        run,
                        risk,
                        current_commit=identity["commit"],
                        current_medium_count=medium_count,
                        current_finding_set_digest=finding_set_digest,
                        gate_definition_digest=str(run["gate_definition_digest"]),
                    )
                    for risk in gate_risks_before
                }
                # A refresh never silently carries a stale acceptance forward. Count and commit
                # changes make every old record stale; changed evidence retires only its record.
                # The caller then explicitly re-attests the exact current finding set.
                retired = [
                    risk for risk in gate_risks_before if stale_reasons[id(risk)]
                ]
                if superseded is not None and all(
                    candidate is not superseded for candidate in retired
                ):
                    retired.append(superseded)
                remaining_gate_risks = [
                    risk
                    for risk in gate_risks_before
                    if all(risk is not retired_risk for retired_risk in retired)
                ]
                # A count increase can add a newly discovered finding without replacing one.
                if superseded is None and len(remaining_gate_risks) >= medium_count:
                    return False, [
                        f"FAIL  no accepted risk {replace_id!r} exists at {gate!r} to refresh; "
                        "use --supersedes-finding-id when the finding identity changed"
                    ]
                if retired:
                    retired_at = _utc_now()
                    prior = run.get("accepted_risk_history")
                    if not isinstance(prior, list):
                        prior = []
                    for retired_risk in retired:
                        audit_record = dict(retired_risk)
                        audit_record["superseded_at"] = retired_at
                        audit_record["superseded_by_finding_id"] = finding_id.strip()
                        reasons = stale_reasons.get(id(retired_risk)) or []
                        audit_record["superseded_reason"] = (
                            "; ".join(reasons)
                            if reasons
                            else "explicit finding re-attestation"
                        )
                        prior.append(audit_record)
                    run["accepted_risk_history"] = prior
                    risks = [
                        risk
                        for risk in risks
                        if all(risk is not retired_risk for retired_risk in retired)
                    ]
                if medium_count == 0:
                    if (
                        gate_entry is None
                    ):  # guarded above; narrows the type for readers
                        return False, [
                            f"FAIL  --refresh requires an existing accepted-risk resolution at {gate!r}"
                        ]
                    cleared_at = _utc_now()
                    gate_entry["accepted_risk_ids"] = []
                    gate_entry["recorded_at"] = cleared_at
                    gate_entry["repository_commit"] = identity["commit"]
                    if workspace_checkpoint is not None:
                        gate_entry["workspace_head_commit"] = (
                            workspace_checkpoint.head_commit
                        )
                        gate_entry["workspace_content_digest"] = (
                            workspace_checkpoint.content_digest
                        )
                    gate_entry["risk_clearance"] = {
                        "reason": reason.strip(),
                        "cleared_by": accepted_by.strip(),
                        "owner": owner.strip(),
                        "ticket": ticket.strip(),
                        "revisit": revisit.strip(),
                        "evidence_path": stored_evidence,
                        "evidence_sha256": (
                            managed_evidence_sha or _sha256(evidence_path)
                        ),
                        "cleared_at": cleared_at,
                        "repository_commit": identity["commit"],
                        "finding_set_digest": finding_set_digest,
                    }
                    if workspace_checkpoint is not None:
                        gate_entry["risk_clearance"].update(
                            {
                                "workspace_head_commit": workspace_checkpoint.head_commit,
                                "workspace_content_digest": workspace_checkpoint.content_digest,
                            }
                        )
                    run["accepted_risks"] = risks
                    run["gate_history"] = history
                    run["current_commit"] = identity["commit"]
                    _write_snapshot_locked(target, run)
                    msgs.append(
                        f"OK    gate {gate!r} accepted-risk ledger cleared after all Medium "
                        "findings were fixed; prior acceptances remain in audit history"
                    )
                    return True, msgs
            gate_risks = [
                risk
                for risk in risks
                if isinstance(risk, dict) and risk.get("affected_gate") == gate
            ]
            if len(gate_risks) >= medium_count:
                return False, [
                    f"FAIL  gate {gate!r} already has {len(gate_risks)} acceptance(s) for "
                    f"open_findings.medium={medium_count}"
                ]
            will_resolve_gate = (
                gate_entry is None and len(gate_risks) + 1 == medium_count
            )
            if will_resolve_gate:
                transition_problem = _headless_transition_problem(
                    run, action="accept-risk", gate=gate
                )
                if transition_problem:
                    return False, [f"FAIL  {transition_problem}"]
            evidence_sha = managed_evidence_sha or _sha256(evidence_path)
            digest = str(run["gate_definition_digest"])
            fingerprint = _risk_fingerprint(
                finding_id=finding_id.strip(),
                affected_gate=gate,
                evidence_sha256=evidence_sha,
                medium_finding_count=medium_count,
                finding_set_digest=finding_set_digest,
                gate_definition_digest=digest,
                repository_commit=identity["commit"],
            )
            record: dict[str, Any] = {
                "risk_id": fingerprint,
                "finding_id": finding_id.strip(),
                "reason": reason.strip(),
                "accepted_by": accepted_by.strip(),
                "owner": owner.strip(),
                "ticket": ticket.strip(),
                "revisit": revisit.strip(),
                "compensating_control": (
                    compensating_control.strip()
                    if isinstance(compensating_control, str)
                    and compensating_control.strip()
                    else None
                ),
                "timestamp": _utc_now(),
                "repository_commit": identity["commit"],
                "affected_gate": gate,
                "evidence_path": stored_evidence,
                "evidence_sha256": evidence_sha,
                "medium_finding_count": medium_count,
                "finding_set_digest": finding_set_digest,
                "finding_fingerprint": fingerprint,
                "gate_definition_digest": digest,
            }
            if workspace_checkpoint is not None:
                record.update(
                    {
                        "workspace_head_commit": workspace_checkpoint.head_commit,
                        "workspace_content_digest": workspace_checkpoint.content_digest,
                    }
                )
            risks.append(record)
            run["accepted_risks"] = risks
            current_gate_risks = gate_risks + [record]
            if len(current_gate_risks) == medium_count:
                if gate_entry is None:
                    gate_entry = {
                        "gate": gate,
                        "status": "accepted-risk",
                        "verification": "human",
                    }
                    history.append(gate_entry)
                    _advance_run(run, gates, gate)
                    _consume_headless_transition_allowance(
                        run, action="accept-risk", gate=gate
                    )
                if managed_typed:
                    managed_bundle, bundle_problem = _managed_gate_bundle(
                        fs, run, gate=gate
                    )
                    if bundle_problem or managed_bundle is None:
                        return False, [
                            f"FAIL  {bundle_problem or 'managed gate evidence is unavailable'}"
                        ]
                    bundle_document = cast(dict[str, Any], managed_bundle["document"])
                    gate_entry.update(
                        {
                            "evidence_path": managed_bundle["path"],
                            "evidence_sha256": managed_bundle["sha256"],
                            "owner_stage": bundle_document["owner_stage"],
                            "owner_dispatch_id": bundle_document["owner_dispatch_id"],
                            "owner_dispatch_attempt": bundle_document[
                                "owner_dispatch_attempt"
                            ],
                            "owner_output_sha256": bundle_document[
                                "owner_output_sha256"
                            ],
                            "evidence_set_digest": bundle_document[
                                "evidence_set_digest"
                            ],
                        }
                    )
                gate_entry["accepted_risk_ids"] = [
                    risk["risk_id"] for risk in current_gate_risks
                ]
                gate_entry["recorded_at"] = _utc_now()
                gate_entry["repository_commit"] = identity["commit"]
                if workspace_checkpoint is not None:
                    gate_entry["workspace_head_commit"] = (
                        workspace_checkpoint.head_commit
                    )
                    gate_entry["workspace_content_digest"] = (
                        workspace_checkpoint.content_digest
                    )
                run["gate_history"] = history
            elif gate_entry is not None:
                # Preserve the resolved position while making the incomplete re-attestation highly
                # visible and invalid until all current Medium findings have fresh records.
                gate_entry["accepted_risk_ids"] = [
                    risk["risk_id"] for risk in current_gate_risks
                ]
                gate_entry["recorded_at"] = _utc_now()
                gate_entry["repository_commit"] = identity["commit"]
                if workspace_checkpoint is not None:
                    gate_entry["workspace_head_commit"] = (
                        workspace_checkpoint.head_commit
                    )
                    gate_entry["workspace_content_digest"] = (
                        workspace_checkpoint.content_digest
                    )
            run["current_commit"] = identity["commit"]
            _write_snapshot_locked(target, run)
        remaining = medium_count - len(current_gate_risks)
        verb = "refreshed" if refresh else "recorded"
        if remaining:
            msgs.append(
                f"OK    ACCEPTED RISK {finding_id.strip()} {verb}; {remaining} Medium "
                f"finding(s) at {gate!r} still require acceptance"
            )
        else:
            msgs.append(
                f"OK    gate {gate!r} {'re-attested' if refresh else 'resolved'} as "
                f"ACCEPTED RISK for {medium_count} Medium "
                "finding(s); this is not an ordinary PASS"
            )
        return True, msgs
    except TimeoutError as exc:
        return False, [f"FAIL  {exc}"]
    except (UnsafePathError, OSError, ValueError) as exc:
        return False, [f"FAIL  unsafe pipeline state mutation refused: {exc}"]


def complete(target: str | Path) -> tuple[bool, list[str]]:
    """Complete an active run only after every active gate has an explicit resolution."""
    msgs: list[str] = []
    try:
        fs = ProjectFS(Path(target).expanduser())
        root = fs.root
        path = fs.path(_snapshot_rel(target))
    except (UnsafePathError, OSError, ValueError) as exc:
        return False, [f"FAIL  unsafe pipeline state path: {exc}"]
    try:
        with _pipeline_write_lock(fs, path, msgs=msgs):
            snap, err = _load_snapshot(target)
            if err:
                return False, [f"FAIL  {err}"]
            run, identity, problem = _active_v2_run(target, snap)
            if problem or run is None or identity is None:
                return False, [f"FAIL  {problem or 'invalid run'}"]
            valid, validation_messages = validate(target, strict=True)
            if not valid:
                return False, validation_messages
            findings_problem = _current_findings_problem(
                root, run, current_commit=identity["commit"]
            )
            if findings_problem:
                return False, [f"FAIL  {findings_problem}"]
            blocking = _blocking_findings(run)
            never_waivable = {
                severity: blocking[severity]
                for severity in ("critical", "high")
                if severity in blocking
            }
            if never_waivable:
                rendered = ", ".join(
                    f"{severity}={count}" for severity, count in never_waivable.items()
                )
                return False, [
                    f"FAIL  cannot complete with open {rendered}; Critical and High are "
                    "never waivable"
                ]
            medium_count = blocking.get("medium", 0)
            if medium_count:
                risks = [
                    risk
                    for risk in (run.get("accepted_risks") or [])
                    if isinstance(risk, dict)
                ]
                managed_contract = run.get("managed_execution")
                findings_record = run.get("findings_evidence")
                if (
                    isinstance(managed_contract, dict)
                    and managed_contract.get("evidence_contract_version")
                    == EVIDENCE_CONTRACT_VERSION
                    and isinstance(findings_record, dict)
                ):
                    managed_gate = findings_record.get("managed_gate")
                    exact_medium_ids = {
                        str(item.get("finding_id"))
                        for item in findings_record.get("finding_index", [])
                        if isinstance(item, dict) and item.get("severity") == "medium"
                    }
                    accepted_ids = {
                        str(risk.get("finding_id"))
                        for risk in risks
                        if risk.get("affected_gate") == managed_gate
                    }
                    covered = (
                        accepted_ids == exact_medium_ids
                        and len(exact_medium_ids) == medium_count
                    )
                else:
                    covered = any(
                        entry.get("status") == "accepted-risk"
                        and len(
                            [
                                risk
                                for risk in risks
                                if risk.get("affected_gate") == entry.get("gate")
                            ]
                        )
                        == medium_count
                        for entry in _history(run)
                    )
                if not covered:
                    return False, [
                        f"FAIL  cannot complete with medium={medium_count} unless the exact "
                        "current findings have structured accepted-risk records"
                    ]
            gates = list(run["ordered_gates"])
            resolved = _resolved_gate_names(run, gates)
            unresolved = [gate for gate in gates if gate not in resolved]
            if unresolved:
                return False, [f"FAIL  unresolved gates: {', '.join(unresolved)}"]
            if run.get("managed_execution") is not None:
                current_checkpoint, workspace_problem = _managed_workspace_checkpoint(
                    root, run
                )
                if workspace_problem or current_checkpoint is None:
                    return False, [
                        f"FAIL  {workspace_problem or 'managed workspace checkpoint missing'}"
                    ]
                completion_problem = _managed_completion_problem(
                    run, current=current_checkpoint
                )
                if completion_problem:
                    return False, [f"FAIL  {completion_problem}"]
            program_execution = run.get("program_execution")
            if program_execution is not None:
                if (
                    not isinstance(program_execution, dict)
                    or program_execution.get("status") != "completed"
                ):
                    return False, [
                        "FAIL  program execution has no terminal completion checkpoint"
                    ]
                current_checkpoint, workspace_problem = _managed_workspace_checkpoint(
                    root, run
                )
                if workspace_problem or current_checkpoint is None:
                    return False, [
                        f"FAIL  {workspace_problem or 'program workspace checkpoint missing'}"
                    ]
                if (
                    program_execution.get("completion_workspace_checkpoint")
                    != current_checkpoint.to_dict()
                ):
                    return False, [
                        "FAIL  program workspace changed after its terminal completion "
                        "checkpoint"
                    ]
            transition_problem = _headless_transition_problem(
                run, action="complete", gate=None
            )
            if transition_problem:
                return False, [f"FAIL  {transition_problem}"]
            completed_at = _utc_now()
            run["status"] = "completed"
            run["stage"] = "completed"
            run["next"] = "(run completed)"
            run["completed_at"] = completed_at
            run["current_commit"] = identity["commit"]
            # The snapshot is the deterministic evidence bundle: this projection contains only
            # persisted run records and is rebuilt in ordered-gate order at the terminal transition.
            run["final_summary"] = _final_summary_projection(
                run,
                repository_commit=identity["commit"],
                completed_at=completed_at,
            )
            _consume_headless_transition_allowance(run, action="complete", gate=None)
            _write_snapshot_locked(target, run)
        return True, [
            "OK    pipeline run completed; final evidence summary persisted in "
            f"{_snapshot_rel(target)}"
        ]
    except TimeoutError as exc:
        return False, [f"FAIL  {exc}"]
    except (UnsafePathError, OSError, ValueError) as exc:
        return False, [f"FAIL  unsafe pipeline state mutation refused: {exc}"]


def _abort_under_managed_lease(
    target: str | Path,
    *,
    coordinator_token: str | None = None,
    _project_lease_held: bool = False,
) -> tuple[bool, list[str]]:
    """Mark an explicit schema-v2 run aborted; abort is terminal."""
    msgs: list[str] = []
    try:
        fs = ProjectFS(Path(target).expanduser())
        snap_path = fs.path(_snapshot_rel(target))
    except (UnsafePathError, OSError, ValueError) as exc:
        return False, [f"FAIL  unsafe pipeline state path: {exc}"]
    if not snap_path.is_file():
        return True, ["OK    no pipeline run in progress — nothing to abort"]
    preflight, preflight_error = _load_snapshot(target)
    if preflight_error:
        return False, [f"FAIL  {preflight_error}"]
    from claude_kit.maker_checker import (
        MakerCheckerError,
        abort_maker_checker_run,
        is_maker_checker_snapshot,
    )

    if is_maker_checker_snapshot(preflight):
        assert isinstance(preflight, dict)
        try:
            result = abort_maker_checker_run(
                target,
                run_id=str(preflight.get("run_id")),
                _managed_lease_held=True,
            )
        except MakerCheckerError as exc:
            return False, [f"FAIL  {exc}"]
        return True, [
            f"OK    maker-checker run {result.run_id} marked aborted; terminal result persisted"
        ]
    aborted_run_id: str | None = None
    try:
        with _pipeline_write_lock(fs, snap_path, msgs=msgs):
            snap, err = _load_snapshot(target)
            if err:
                return False, [f"FAIL  {err}"]
            if snap is None:
                return True, ["OK    no pipeline run in progress — nothing to abort"]
            if is_maker_checker_snapshot(snap):
                return False, [
                    "FAIL  pipeline snapshot changed to maker-checker during abort; retry"
                ]
            run, identity, problem = _active_v2_run(
                target, snap, allow_pending_human_stop=True
            )
            if problem or run is None or identity is None:
                return False, [f"FAIL  {problem or 'invalid run'}"]
            allowance = run.get("headless_transition_allowance")
            if isinstance(allowance, dict) and not _headless_coordinator_matches(
                allowance, coordinator_token or ""
            ):
                return False, [
                    "FAIL  a headless invocation owns this run; its host cannot abort or "
                    "launder the allowance into a fresh run"
                ]
            run["status"] = "aborted"
            run["stage"] = "aborted"
            run["aborted_at"] = _utc_now()
            program_execution = run.get("program_execution")
            if isinstance(program_execution, dict):
                program_execution["status"] = "aborted"
                program_execution["aborted_at"] = run["aborted_at"]
            run["current_commit"] = identity["commit"]
            run["next"] = "(run aborted via claude-kit pipeline abort)"
            aborted_run_id = str(run.get("run_id"))
            _write_snapshot_locked(target, run)
        msgs.append("OK    pipeline run marked aborted")
        if aborted_run_id:
            try:
                from claude_kit.worktrees import WorktreeManager

                workers = WorktreeManager(target).abort_run(
                    aborted_run_id,
                    _managed_lease_held=True,
                    _project_lease_held=_project_lease_held,
                )
            except (OSError, ValueError, RuntimeError) as exc:
                msgs.append(
                    "WARN  pipeline is aborted but run-owned worktree state could not be "
                    f"updated; artifacts were not deleted: {exc}"
                )
            else:
                if workers:
                    msgs.append(
                        f"OK    preserved {len(workers)} run-owned worktree(s) as aborted"
                    )
        return True, msgs
    except TimeoutError as exc:
        return False, [f"FAIL  {exc}"]
    except (UnsafePathError, OSError, ValueError) as exc:
        return False, [f"FAIL  unsafe pipeline state mutation refused: {exc}"]


def abort(
    target: str | Path, *, coordinator_token: str | None = None
) -> tuple[bool, list[str]]:
    """Abort only after proving no live managed coordinator owns native workers."""

    from claude_kit.execution_lease import (
        ManagedExecutionLeaseHeld,
        managed_execution_lease,
    )

    try:
        fs = ProjectFS(Path(target).expanduser())
        with managed_execution_lease(fs.root), fs.mutation_lease():
            return _abort_under_managed_lease(
                fs.root,
                coordinator_token=coordinator_token,
                _project_lease_held=True,
            )
    except ManagedExecutionLeaseHeld:
        return False, [
            "FAIL  managed workflow coordinator is still running; interrupt it so it can "
            "cancel and ledger every native worker before aborting"
        ]
    except (UnsafePathError, OSError, ValueError) as exc:
        return False, [f"FAIL  unsafe pipeline state mutation refused: {exc}"]
