"""Deterministic, non-executing operations on the ``/sdlc`` pipeline state files.

The ``/sdlc`` skill drives the actual pipeline; this module only **validates and mutates the state
files** it leaves behind, so a human or CI can inspect a run, record a passed gate with evidence, or
abort — without an LLM in the loop. It reads the runtime snapshot ``.claude/state/pipeline-snapshot.json``
(schema in ``rules/continuity.md``) and cross-checks gate names against the **execution-ordered**
gate list recorded in ``.claude/config/stack-catalog.snapshot.yaml``. Every function returns the
``(ok, messages)`` contract used by :mod:`claude_kit.validator`.

Trust model (0.76.0):

- Gates close through an **append-only ledger** (``gate_history``): each entry records the gate, a
  status (``passed`` / ``skipped`` / ``overridden``), the evidence path **and its sha256**, a
  ``verification`` level (``agent`` today; ``mechanical`` / ``human`` are reserved for the evidence
  parsers of issue #74), and a UTC timestamp. ``last_gate_passed`` + ``gate_evidence`` are still
  mirrored for older tooling.
- **Order is enforced.** The run's position is the furthest gate recorded in the ledger (or, for
  legacy snapshots, ``last_gate_passed``); only the next gate in the installed ordered list may be
  closed or skipped. The very first record may anchor anywhere (a run adopted mid-flight), after
  which order applies. ``--force --override-reason`` bypasses and is recorded as ``overridden``.
- **Evidence is content-addressed.** ``validate`` re-hashes every historical entry, so evidence
  cannot silently change after its gate closed.
- **Writes are atomic** (temp file + ``os.replace``) under a short-lived ``O_EXCL`` lockfile.
- **Strict mode fails closed**: with ``strict=True`` a missing/unreadable install snapshot is an
  error, not a warning (for CI; the lenient default keeps mid-run human use workable).
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

#: Runtime pipeline snapshot, relative to the project root (gitignored state).
SNAPSHOT_REL = ".claude/state/pipeline-snapshot.json"
#: Resolved install snapshot (records the profile's execution-ordered gate set + selection).
STACK_SNAPSHOT_REL = ".claude/config/stack-catalog.snapshot.yaml"

#: Closed value-sets the snapshot fields must draw from (see rules/continuity.md).
PROFILES = frozenset({"lean", "standard", "enterprise"})
SCOPES = frozenset({"individual", "team", "organization"})
MODES = frozenset({"A", "B", "C", "D", "E"})
LANE_STATES = frozenset({"not-started", "in-progress", "passed", "failed"})
FINDING_KEYS = frozenset({"critical", "high", "medium", "low"})
#: Ledger entry statuses and verification levels (gate_history in rules/continuity.md).
GATE_STATUSES = frozenset({"passed", "skipped", "overridden"})
VERIFICATIONS = frozenset({"agent", "mechanical", "human", "override"})
#: Severities that block a gate (rules/quality-gates.md: a gate is PASS only with zero of these;
#: low/cosmetic may pass with notes). Ordered for stable messages.
BLOCKING_FINDINGS = ("critical", "high", "medium")

#: How long a writer waits for the snapshot lockfile before giving up.
_LOCK_TIMEOUT_S = 5.0


def _snapshot_path(target: str | Path) -> Path:
    return Path(target).expanduser().resolve() / SNAPSHOT_REL


def _load_snapshot(target: str | Path) -> tuple[dict[str, Any] | None, str | None]:
    """Return ``(snapshot, error)`` — ``error`` set if the file exists but won't parse."""
    path = _snapshot_path(target)
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
    path = Path(target).expanduser().resolve() / STACK_SNAPSHOT_REL
    if not path.is_file():
        return None, None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        return None, f"install snapshot is invalid YAML: {exc}"
    if not isinstance(data, dict):
        return None, "install snapshot is not a YAML mapping"
    return data, None


def _installed_gates(target: str | Path) -> list[str]:
    """Read the execution-ordered gate list from the install snapshot ([] if absent/unreadable)."""
    data, _err = _read_install_snapshot(target)
    gates = (data or {}).get("gates")
    return list(gates) if isinstance(gates, list) else []


def _selection(target: str | Path) -> dict[str, Any]:
    """Read the recorded selection from the install snapshot ({} if absent)."""
    data, _err = _read_install_snapshot(target)
    sel = (data or {}).get("selection")
    return sel if isinstance(sel, dict) else {}


def _blocking_findings(snap: dict[str, Any]) -> dict[str, int]:
    """Return the ``{severity: count}`` of open findings that block a gate (count > 0).

    Only :data:`BLOCKING_FINDINGS` severities count; malformed/absent counts are ignored (lenient
    for older or partial snapshots).
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


def _history(snap: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the ledger entries that are well-formed dicts (lenient on the rest)."""
    raw = snap.get("gate_history")
    if not isinstance(raw, list):
        return []
    return [e for e in raw if isinstance(e, dict)]


def _position(
    gates: list[str], history: list[dict[str, Any]], last_gate_passed: Any
) -> int | None:
    """Return the run's furthest recorded gate index, or ``None`` when nothing anchors it yet.

    The ledger wins; a legacy snapshot with only ``last_gate_passed`` anchors there. ``None`` means
    the first record may open at any gate (a run adopted mid-flight) — order applies afterwards.
    """
    recorded = [
        gates.index(e["gate"])
        for e in history
        if e.get("status") in GATE_STATUSES and e.get("gate") in gates
    ]
    if recorded:
        return max(recorded)
    if isinstance(last_gate_passed, str) and last_gate_passed in gates:
        return gates.index(last_gate_passed)
    return None


@contextmanager
def _snapshot_lock(path: Path) -> Iterator[None]:
    """Hold an ``O_EXCL`` lockfile next to the snapshot (raises ``TimeoutError`` after 5s)."""
    lock = path.with_name(path.name + ".lock")
    deadline = time.monotonic() + _LOCK_TIMEOUT_S
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"could not lock {lock} within {_LOCK_TIMEOUT_S:g}s — another claude-kit "
                    "process may be writing; if not, delete the stale lockfile"
                ) from None
            time.sleep(0.05)
    try:
        yield
    finally:
        os.close(fd)
        lock.unlink(missing_ok=True)


def _write_snapshot(target: str | Path, snap: dict[str, Any]) -> None:
    """Atomically persist the snapshot (temp file + ``os.replace``) under the lock."""
    path = _snapshot_path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _snapshot_lock(path):
        tmp = path.with_name(path.name + f".tmp{os.getpid()}")
        tmp.write_text(json.dumps(snap, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)


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


def validate(target: str | Path, *, strict: bool = False) -> tuple[bool, list[str]]:
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

    def fail(m: str) -> None:
        nonlocal ok
        ok = False
        msgs.append(f"FAIL  {m}")

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

    schema = snap.get("schema")
    if schema not in (None, 1):
        msgs.append(f"WARN  unexpected snapshot schema {schema!r} (expected 1)")

    for field, allowed in (
        ("profile", PROFILES),
        ("scope", SCOPES),
        ("mode", MODES),
    ):
        val = snap.get(field)
        if val is not None and val not in allowed:
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
    if findings is not None:
        if not isinstance(findings, dict):
            fail("open_findings must be an object of {severity: count}")
        else:
            for sev, count in findings.items():
                if sev not in FINDING_KEYS:
                    msgs.append(f"WARN  open_findings has unknown severity {sev!r}")
                if not isinstance(count, int) or isinstance(count, bool):
                    fail(f"open_findings[{sev!r}] must be an integer, got {count!r}")

    gate = snap.get("last_gate_passed")
    gates = _installed_gates(target)
    if gate is not None and gates and gate not in gates:
        fail(f"last_gate_passed {gate!r} is not a gate of this profile ({gates})")

    overrides = snap.get("gate_overrides")
    if overrides is not None and not isinstance(overrides, dict):
        fail("gate_overrides must be an object of {gate: reason}")

    # --- gate_history ledger: verify EVERY entry, not just the latest gate. -----------------
    raw_history = snap.get("gate_history")
    if raw_history is not None and not isinstance(raw_history, list):
        fail("gate_history must be an array of ledger entries")
    history = _history(snap)
    if isinstance(raw_history, list) and len(raw_history) != len(history):
        fail("gate_history contains non-object entries")
    last_index = -1
    for i, entry in enumerate(history):
        label = f"gate_history[{i}]"
        name = entry.get("gate")
        if not isinstance(name, str) or not name:
            fail(f"{label} has no gate name")
            continue
        status = entry.get("status")
        if status not in GATE_STATUSES:
            fail(
                f"{label} ({name}) status {status!r} is not one of {sorted(GATE_STATUSES)}"
            )
        verification = entry.get("verification")
        if verification is not None and verification not in VERIFICATIONS:
            msgs.append(
                f"WARN  {label} ({name}) verification {verification!r} is not one of "
                f"{sorted(VERIFICATIONS)}"
            )
        if gates and name in gates:
            idx = gates.index(name)
            if idx <= last_index:
                fail(
                    f"{label} ({name}) is out of the installed gate order "
                    f"(after {gates[last_index]!r})"
                )
            last_index = max(last_index, idx)
        elif gates:
            fail(f"{label} ({name}) is not a gate of this profile ({gates})")
        if status == "skipped":
            if not (isinstance(entry.get("reason"), str) and entry["reason"].strip()):
                msgs.append(f"WARN  {label} ({name}) is skipped without a reason")
            continue
        ev = entry.get("evidence_path")
        if not (isinstance(ev, str) and ev):
            fail(f"{label} ({name}) has no evidence_path")
            continue
        ev_path = Path(ev).expanduser()
        if not ev_path.is_file():
            fail(f"{label} ({name}) evidence file is missing: {ev}")
            continue
        recorded_sha = entry.get("evidence_sha256")
        if isinstance(recorded_sha, str) and recorded_sha:
            actual = _sha256(ev_path)
            if actual != recorded_sha:
                fail(
                    f"{label} ({name}) evidence hash mismatch — the file changed after the "
                    f"gate closed (recorded {recorded_sha[:12]}…, actual {actual[:12]}…)"
                )
        else:
            msgs.append(
                f"WARN  {label} ({name}) has no evidence_sha256 (pre-0.76 entry)"
            )
        if status == "overridden" or entry.get("override"):
            msgs.append(
                f"WARN  {label} ({name}) was force-closed "
                f"(override: {entry.get('override')!r}) — review"
            )

    # A recorded gate's evidence artifact must still exist on disk. Lenient on the upgrade path:
    # a snapshot with no gate_evidence map at all simply doesn't track evidence (the norm for
    # orchestrator-written snapshots) — stay silent; only flag a *partial* map that omits this gate.
    if gate is not None:
        evidence_map = snap.get("gate_evidence")
        if isinstance(evidence_map, dict) and gate in evidence_map:
            ev_val = evidence_map[gate]
            if not (isinstance(ev_val, str) and Path(ev_val).expanduser().is_file()):
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

    msgs = [f"task:    {snap.get('task', '(none)')}"]
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
    if findings:
        rendered = ", ".join(f"{k}={v}" for k, v in findings.items())
        msgs.append(f"open findings: {rendered}")
    msgs.append(f"next:    {snap.get('next', '(none)')}")
    return True, msgs


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
    pos = _position(gates, _history(snap), snap.get("last_gate_passed"))
    if pos is None:
        return None  # first record anchors the run — any gate may open the ledger
    idx = gates.index(gate)
    if idx <= pos:
        return (
            f"cannot {action} {gate!r}: the run is already at {gates[pos]!r} "
            f"(gate {gate!r} is recorded or superseded). Re-recording requires "
            "--force --override-reason '<why>'."
        )
    expected = gates[pos + 1] if pos + 1 < len(gates) else None
    if expected is not None and idx > pos + 1:
        return (
            f"cannot {action} {gate!r} out of order: the next gate is {expected!r}. "
            "Skip a gate that doesn't apply explicitly first: "
            f"claude-kit pipeline skip-gate {expected} --reason '<why>'."
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
    """Record ``gate`` as passed (with an evidence artifact) in the snapshot ledger.

    Validates that the evidence file exists and that ``gate`` is a real gate for the installed
    profile, **refuses to pass a gate while critical/high/medium findings are open** (per
    ``rules/quality-gates.md``), **refuses to pass a gate out of the installed order** (the next
    unrecorded gate is the only legal target; the first record may anchor anywhere), then appends an
    entry to ``gate_history`` — evidence path **and sha256**, verification level, UTC timestamp —
    and mirrors ``last_gate_passed``/``gate_evidence`` for older tooling. Seeds a minimal snapshot
    (profile/scope from the install snapshot) if no run snapshot exists yet.

    A forced close (``force=True`` with a non-empty ``override_reason``) bypasses the
    blocking-findings and gate-order rules but records the entry as ``overridden`` (and the reason
    under ``gate_overrides[gate]``) so ``validate``/``status`` surface it for human review.
    ``strict=True`` fails closed when the install snapshot is missing or unreadable.
    """
    msgs: list[str] = []
    evidence_path = Path(evidence).expanduser().resolve()
    if not evidence_path.is_file():
        return False, [f"FAIL  evidence file not found: {evidence}"]

    gates, preamble_ok = _gate_set_preamble(target, strict=strict, msgs=msgs)
    if not preamble_ok:
        return False, msgs
    if gates and gate not in gates:
        return False, [
            f"FAIL  {gate!r} is not a gate of this profile (choices: {', '.join(gates)})"
        ]

    snap, err = _load_snapshot(target)
    if err:
        return False, [f"FAIL  {err}"]
    if snap is None:
        sel = _selection(target)
        snap = {
            "schema": 1,
            "task": "(recorded via claude-kit pipeline close-gate)",
            "profile": sel.get("profile"),
            "scope": sel.get("scope"),
            "stage": gate,
        }

    overridden = False

    def _require_reason(problem: str) -> tuple[bool, list[str]] | None:
        """Force path: demand a reason; return the failure tuple when it's absent."""
        if not force:
            return False, [f"FAIL  {problem}"]
        if not (override_reason and override_reason.strip()):
            return False, [
                f"FAIL  --force requires --override-reason '<why>' explaining the bypass: {problem}"
            ]
        return None

    blocking = _blocking_findings(snap)
    if blocking:
        rendered = ", ".join(f"{sev}={count}" for sev, count in blocking.items())
        problem = (
            f"cannot close {gate!r}: {rendered} open finding(s) must be resolved first "
            "(critical/high/medium block a gate per quality-gates.md). "
            "Re-run with --force --override-reason '<why>' to record a deliberate override."
        )
        if not force:
            return False, [f"FAIL  {problem}"]
        if not (override_reason and override_reason.strip()):
            return False, [
                "FAIL  --force requires --override-reason '<why>' explaining why the open "
                f"finding(s) ({rendered}) are being bypassed"
            ]
        overridden = True
        msgs.append(
            f"WARN  gate {gate!r} force-closed with open findings ({rendered}): "
            f"{override_reason.strip()}"
        )

    order_problem = _order_check(gates, snap, gate, action="close")
    if order_problem:
        failure = _require_reason(order_problem)
        if failure is not None:
            return failure
        overridden = True
        msgs.append(f"WARN  gate {gate!r} force-closed out of order: {override_reason}")

    if overridden and override_reason:
        overrides = snap.get("gate_overrides")
        if not isinstance(overrides, dict):
            overrides = {}
        overrides[gate] = override_reason.strip()
        snap["gate_overrides"] = overrides

    entry: dict[str, Any] = {
        "gate": gate,
        "status": "overridden" if overridden else "passed",
        "evidence_path": str(evidence_path),
        "evidence_sha256": _sha256(evidence_path),
        "verification": "override" if overridden else "agent",
        "recorded_at": _utc_now(),
        "override": override_reason.strip() if overridden and override_reason else None,
    }
    history = snap.get("gate_history")
    if not isinstance(history, list):
        history = []
    history.append(entry)
    snap["gate_history"] = history

    snap["last_gate_passed"] = gate
    evidence_map = snap.get("gate_evidence")
    if not isinstance(evidence_map, dict):
        evidence_map = {}
    evidence_map[gate] = str(evidence_path)
    snap["gate_evidence"] = evidence_map

    try:
        _write_snapshot(target, snap)
    except TimeoutError as exc:
        return False, [f"FAIL  {exc}"]
    msgs.append(
        f"OK    gate {gate!r} recorded {'overridden' if overridden else 'passed'} "
        f"(evidence: {evidence_path}, sha256: {entry['evidence_sha256'][:12]}…)"
    )
    return True, msgs


def skip_gate(
    target: str | Path,
    gate: str,
    reason: str,
    *,
    strict: bool = False,
) -> tuple[bool, list[str]]:
    """Record ``gate`` as deliberately skipped (a conditional gate this run doesn't need).

    A skip needs a non-empty ``reason``, must name a real gate of the installed profile, and — like
    a close — may only target the **next** gate in order (the first record may anchor anywhere).
    The skip is a ledger entry (``status: skipped``); it never sets ``last_gate_passed``.
    """
    msgs: list[str] = []
    if not (reason and reason.strip()):
        return False, [
            "FAIL  skip-gate requires --reason '<why this gate does not apply>'"
        ]

    gates, preamble_ok = _gate_set_preamble(target, strict=strict, msgs=msgs)
    if not preamble_ok:
        return False, msgs
    if gates and gate not in gates:
        return False, [
            f"FAIL  {gate!r} is not a gate of this profile (choices: {', '.join(gates)})"
        ]

    snap, err = _load_snapshot(target)
    if err:
        return False, [f"FAIL  {err}"]
    if snap is None:
        sel = _selection(target)
        snap = {
            "schema": 1,
            "task": "(recorded via claude-kit pipeline skip-gate)",
            "profile": sel.get("profile"),
            "scope": sel.get("scope"),
            "stage": gate,
        }

    order_problem = _order_check(gates, snap, gate, action="skip")
    if order_problem:
        return False, [f"FAIL  {order_problem}"]

    history = snap.get("gate_history")
    if not isinstance(history, list):
        history = []
    history.append(
        {
            "gate": gate,
            "status": "skipped",
            "evidence_path": None,
            "evidence_sha256": None,
            "verification": "human",
            "recorded_at": _utc_now(),
            "override": None,
            "reason": reason.strip(),
        }
    )
    snap["gate_history"] = history

    try:
        _write_snapshot(target, snap)
    except TimeoutError as exc:
        return False, [f"FAIL  {exc}"]
    msgs.append(f"OK    gate {gate!r} recorded skipped: {reason.strip()}")
    return True, msgs


def abort(target: str | Path) -> tuple[bool, list[str]]:
    """Mark the current pipeline run aborted (stage=aborted); no run is not an error."""
    snap, err = _load_snapshot(target)
    if err:
        return False, [f"FAIL  {err}"]
    if snap is None:
        return True, ["OK    no pipeline run in progress — nothing to abort"]
    snap["stage"] = "aborted"
    snap["next"] = "(run aborted via claude-kit pipeline abort)"
    try:
        _write_snapshot(target, snap)
    except TimeoutError as exc:
        return False, [f"FAIL  {exc}"]
    return True, ["OK    pipeline run marked aborted"]
