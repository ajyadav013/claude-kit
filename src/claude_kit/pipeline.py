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
import json
import os
import subprocess
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import yaml

from claude_kit import __version__
from claude_kit.models import GateDefinition, digest_gate_definitions
from claude_kit.secure_fs import ProjectFS, UnsafePathError

#: Runtime pipeline snapshot, relative to the project root (gitignored state).
SNAPSHOT_REL = ".claude/state/pipeline-snapshot.json"
#: Resolved install snapshot (records the profile's execution-ordered gate set + selection).
STACK_SNAPSHOT_REL = ".claude/config/stack-catalog.snapshot.yaml"
#: Current explicit lifecycle schema. Legacy snapshots used optional ``schema: 1``.
PIPELINE_SCHEMA_VERSION = 2

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
#: Severities that block a gate (rules/quality-gates.md: a gate is PASS only with zero of these;
#: low/cosmetic may pass with notes). Ordered for stable messages.
BLOCKING_FINDINGS = ("critical", "high", "medium")

#: How long a writer waits for the snapshot lockfile before giving up.
_LOCK_TIMEOUT_S = 5.0
#: Retained for compatibility/diagnostics only. Age is never ownership proof, so locks are not
#: automatically reclaimed; recovery requires an operator to verify and remove the exact lock.
_LOCK_STALE_S = 60.0


def _snapshot_path(target: str | Path) -> Path:
    """Return the snapshot path after link/reparse-safe project containment checks."""
    return ProjectFS(Path(target).expanduser()).path(SNAPSHOT_REL)


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
        path = ProjectFS(Path(target).expanduser()).path(STACK_SNAPSHOT_REL)
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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _finding_set_digest(
    counts: dict[str, int], *, evidence_sha256: str, repository_commit: str
) -> str:
    """Bind exact severity counts to their evidence artifact and repository commit."""
    document = {
        "counts": {severity: counts[severity] for severity in sorted(FINDING_KEYS)},
        "evidence_sha256": evidence_sha256,
        "repository_commit": repository_commit,
    }
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
            evidence_bytes = ProjectFS(root).read_bytes(str(evidence))
        except FileNotFoundError:
            errors.append(f"findings evidence file is missing: {evidence}")
        except (UnsafePathError, OSError, ValueError) as exc:
            errors.append(f"findings evidence path is unsafe: {exc}")
        else:
            actual_sha = hashlib.sha256(evidence_bytes).hexdigest()
            if not isinstance(evidence_sha, str) or actual_sha != evidence_sha:
                errors.append("findings evidence hash mismatch")
    recorded_commit = record.get("repository_commit")
    if current_commit is not None and recorded_commit != current_commit:
        errors.append(
            f"findings evidence belongs to commit {recorded_commit!r}, current HEAD is "
            f"{current_commit!r}"
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
    lock_rel = f"{SNAPSHOT_REL}.lock"
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
        fs.mkdir(".claude/state")
        with _snapshot_lock(path, msgs=msgs, project_fs=fs):
            yield


def _write_snapshot_locked(target: str | Path, snap: dict[str, Any]) -> None:
    """Atomically persist the snapshot through the project-root filesystem capability."""
    fs = ProjectFS(Path(target).expanduser())
    fs.write_text(SNAPSHOT_REL, json.dumps(snap, indent=2) + "\n")


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
                f"expected {STACK_SNAPSHOT_REL}"
            )
            return [], False
        msgs.append(
            "WARN  no install snapshot — cannot confirm the gate name against the profile"
        )
        return [], True
    gates = install.get("gates")
    return (list(gates) if isinstance(gates, list) else []), True


def _active_v2_run(
    target: str | Path, snap: dict[str, Any] | None
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
    installed = installed_gates(target)
    if installed and gates != installed:
        return None, None, "installed ordered gate list changed after this run started"
    current_digest = installed_gate_definition_digest(target)
    if not current_digest or snap.get("gate_definition_digest") != current_digest:
        return None, None, "gate definition digest changed after this run started"
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
    gates, preamble_ok = _gate_set_preamble(target, strict=True, msgs=msgs)
    if not preamble_ok:
        return False, msgs
    if not gates:
        return False, ["FAIL  installed profile has no ordered gates"]
    if start_type == "adopted" and gate not in gates:
        return False, [f"FAIL  adoption gate {gate!r} is not in {gates}"]

    definitions = installed_gate_definitions(target)
    if set(definitions) != set(gates):
        return False, ["FAIL  installed gate definitions are missing or malformed"]
    digest = installed_gate_definition_digest(target)
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
        "gate_history": [],
    }

    try:
        path = fs.path(SNAPSHOT_REL)
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
            locked_gates = (
                list(locked_install.get("gates", []))
                if isinstance(locked_install, dict)
                and isinstance(locked_install.get("gates"), list)
                else []
            )
            if not locked_gates:
                return False, ["FAIL  installed profile has no ordered gates"]
            if start_type == "adopted" and gate not in locked_gates:
                return False, [f"FAIL  adoption gate {gate!r} is not in {locked_gates}"]
            locked_definitions = installed_gate_definitions(target)
            if set(locked_definitions) != set(locked_gates):
                return False, [
                    "FAIL  installed gate definitions are missing or malformed"
                ]
            if not isinstance((locked_install or {}).get("gate_definitions"), dict):
                msgs.append(
                    "WARN  legacy install snapshot has no gate metadata; all gates are treated "
                    "as required until the install is upgraded"
                )
            locked_digest = installed_gate_definition_digest(target)
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
) -> tuple[bool, list[str]]:
    """Explicitly start a fresh schema-v2 run at the first installed gate."""
    return _create_run(target, task=task, mode=mode, start_type="fresh")


def adopt(
    target: str | Path,
    *,
    task: str,
    gate: str,
    reason: str,
    adopted_by: str,
    mode: str = "B",
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
    )


def resume(target: str | Path) -> tuple[bool, list[str]]:
    """Verify that an active run still belongs to this repository, branch, and gate policy."""
    snap, err = _load_snapshot(target)
    if err:
        return False, [f"FAIL  {err}"]
    run, identity, problem = _active_v2_run(target, snap)
    if problem or run is None or identity is None:
        return False, [f"FAIL  {problem or 'invalid run'}"]
    ok, msgs = validate(target, strict=True)
    if not ok:
        return False, msgs
    kind = "ADOPTED" if run.get("start_type") == "adopted" else "fresh"
    return True, [
        f"OK    resumed {kind} run {run.get('run_id')} at {run.get('stage')} "
        f"(commit {identity['commit']})"
    ]


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
    if not isinstance(evidence, str) or not evidence:
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
        fail(f"no install snapshot at {STACK_SNAPSHOT_REL} (--strict)")
    if snap is None:
        if ok:
            msgs.append("OK    no pipeline snapshot — no run in progress")
        return ok, msgs

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
    installed = installed_gates(target)
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
            "" if _historical_terminal else installed_gate_definition_digest(target)
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
        raw_archives = snap.get("run_archives", [])
        if not isinstance(raw_archives, list):
            fail("schema-v2 run_archives must be an array")
            raw_archives = []
        for archive_index, archive in enumerate(raw_archives):
            label = f"run_archives[{archive_index}]"
            if not isinstance(archive, dict):
                fail(f"{label} must be an object")
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
                    fail(f"{label} has no non-empty {archive_field!r}")
            archived_snapshot = archive.get("snapshot")
            if not isinstance(archived_snapshot, dict):
                fail(f"{label} has no terminal snapshot object")
                continue
            if "run_archives" in archived_snapshot:
                fail(f"{label} snapshot must not recursively contain run_archives")
            archived_version, archived_version_error = _snapshot_version(
                archived_snapshot
            )
            if archived_version_error or archived_version != PIPELINE_SCHEMA_VERSION:
                fail(f"{label} does not contain a supported schema-v2 snapshot")
            if archived_snapshot.get("status") not in {"completed", "aborted"}:
                fail(f"{label} snapshot is not terminal")
            if archive.get("run_id") != archived_snapshot.get("run_id"):
                fail(f"{label} run_id differs from its snapshot")
            if archive.get("status") != archived_snapshot.get("status"):
                fail(f"{label} status differs from its snapshot")
            if archive.get("snapshot_sha256") != _document_sha256(archived_snapshot):
                fail(f"{label} terminal snapshot hash mismatch")
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

    # --- gate_history ledger: verify EVERY entry, not just the latest gate. -----------------
    raw_history = snap.get("gate_history")
    if not legacy and not isinstance(raw_history, list):
        fail("schema-v2 gate_history must be an array")
    elif raw_history is not None and not isinstance(raw_history, list):
        fail("gate_history must be an array of ledger entries")
    history = _history(snap)
    if isinstance(raw_history, list) and len(raw_history) != len(history):
        fail("gate_history contains non-object entries")
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
            required = (
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
            for field in required:
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
            ev = risk.get("evidence_path")
            if isinstance(ev, str) and ev:
                ev_path = resolve_evidence(ev)
                if not ev_path.is_file():
                    if not refreshing:
                        fail(f"{label} accepted-risk evidence file is missing: {ev}")
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
        resolved = _resolved_gate_names(snap, gates)
        unresolved = [gate_name for gate_name in gates if gate_name not in resolved]
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
    if isinstance(snap.get("final_summary"), dict):
        msgs.append(
            "final evidence summary: persisted in this schema-v2 pipeline snapshot "
            f"({SNAPSHOT_REL})"
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
        path = fs.path(SNAPSHOT_REL)
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

            evidence_sha = hashlib.sha256(fs.read_bytes(stored_evidence)).hexdigest()
            finding_digest = _finding_set_digest(
                counts,
                evidence_sha256=evidence_sha,
                repository_commit=identity["commit"],
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
        snap_path = fs.path(SNAPSHOT_REL)
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
            coherent, validation_messages = validate(target, strict=True)
            if not coherent:
                return False, validation_messages
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

            entry: dict[str, Any] = {
                "gate": gate,
                "status": "passed",
                "evidence_path": stored_evidence,
                "evidence_sha256": _sha256(evidence_path),
                "verification": "agent",
                "recorded_at": _utc_now(),
                "repository_commit": identity["commit"],
            }
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
        path = fs.path(SNAPSHOT_REL)
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
            coherent, validation_messages = validate(target, strict=True)
            if not coherent:
                return False, validation_messages
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
            entry = {
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
            history = run.get("gate_history")
            if not isinstance(history, list):
                history = []
            history.append(entry)
            run["gate_history"] = history
            run["current_commit"] = identity["commit"]
            _advance_run(run, gates, gate)
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
        path = fs.path(SNAPSHOT_REL)
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
                    gate_entry["risk_clearance"] = {
                        "reason": reason.strip(),
                        "cleared_by": accepted_by.strip(),
                        "owner": owner.strip(),
                        "ticket": ticket.strip(),
                        "revisit": revisit.strip(),
                        "evidence_path": stored_evidence,
                        "evidence_sha256": _sha256(evidence_path),
                        "cleared_at": cleared_at,
                        "repository_commit": identity["commit"],
                        "finding_set_digest": finding_set_digest,
                    }
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
            evidence_sha = _sha256(evidence_path)
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
                gate_entry["accepted_risk_ids"] = [
                    risk["risk_id"] for risk in current_gate_risks
                ]
                gate_entry["recorded_at"] = _utc_now()
                gate_entry["repository_commit"] = identity["commit"]
                run["gate_history"] = history
            elif gate_entry is not None:
                # Preserve the resolved position while making the incomplete re-attestation highly
                # visible and invalid until all current Medium findings have fresh records.
                gate_entry["accepted_risk_ids"] = [
                    risk["risk_id"] for risk in current_gate_risks
                ]
                gate_entry["recorded_at"] = _utc_now()
                gate_entry["repository_commit"] = identity["commit"]
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
        path = fs.path(SNAPSHOT_REL)
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
            _write_snapshot_locked(target, run)
        return True, [
            f"OK    pipeline run completed; final evidence summary persisted in {SNAPSHOT_REL}"
        ]
    except TimeoutError as exc:
        return False, [f"FAIL  {exc}"]
    except (UnsafePathError, OSError, ValueError) as exc:
        return False, [f"FAIL  unsafe pipeline state mutation refused: {exc}"]


def abort(target: str | Path) -> tuple[bool, list[str]]:
    """Mark an explicit schema-v2 run aborted; abort is terminal."""
    msgs: list[str] = []
    try:
        fs = ProjectFS(Path(target).expanduser())
        snap_path = fs.path(SNAPSHOT_REL)
    except (UnsafePathError, OSError, ValueError) as exc:
        return False, [f"FAIL  unsafe pipeline state path: {exc}"]
    if not snap_path.is_file():
        return True, ["OK    no pipeline run in progress — nothing to abort"]
    try:
        with _pipeline_write_lock(fs, snap_path, msgs=msgs):
            snap, err = _load_snapshot(target)
            if err:
                return False, [f"FAIL  {err}"]
            if snap is None:
                return True, ["OK    no pipeline run in progress — nothing to abort"]
            run, identity, problem = _active_v2_run(target, snap)
            if problem or run is None or identity is None:
                return False, [f"FAIL  {problem or 'invalid run'}"]
            run["status"] = "aborted"
            run["stage"] = "aborted"
            run["aborted_at"] = _utc_now()
            run["current_commit"] = identity["commit"]
            run["next"] = "(run aborted via claude-kit pipeline abort)"
            _write_snapshot_locked(target, run)
        msgs.append("OK    pipeline run marked aborted")
        return True, msgs
    except TimeoutError as exc:
        return False, [f"FAIL  {exc}"]
    except (UnsafePathError, OSError, ValueError) as exc:
        return False, [f"FAIL  unsafe pipeline state mutation refused: {exc}"]
