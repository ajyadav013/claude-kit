"""Deterministic, non-executing operations on the ``/sdlc`` pipeline state files.

The ``/sdlc`` skill drives the actual pipeline; this module only **validates and mutates the state
files** it leaves behind, so a human or CI can inspect a run, record a passed gate with evidence, or
abort — without an LLM in the loop. It reads the runtime snapshot ``.claude/state/pipeline-snapshot.json``
(schema in ``rules/continuity.md``) and cross-checks gate names against the resolved gate set recorded
in ``.claude/config/stack-catalog.snapshot.yaml``. Every function returns the ``(ok, messages)``
contract used by :mod:`claude_kit.validator`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

#: Runtime pipeline snapshot, relative to the project root (gitignored state).
SNAPSHOT_REL = ".claude/state/pipeline-snapshot.json"
#: Resolved install snapshot (records the profile's gate set + selection).
STACK_SNAPSHOT_REL = ".claude/config/stack-catalog.snapshot.yaml"

#: Closed value-sets the snapshot fields must draw from (see rules/continuity.md).
PROFILES = frozenset({"lean", "standard", "enterprise"})
SCOPES = frozenset({"individual", "team", "organization"})
MODES = frozenset({"A", "B", "C", "D"})
LANE_STATES = frozenset({"not-started", "in-progress", "passed", "failed"})
FINDING_KEYS = frozenset({"critical", "high", "medium", "low"})
#: Severities that block a gate (rules/quality-gates.md: a gate is PASS only with zero of these;
#: low/cosmetic may pass with notes). Ordered for stable messages.
BLOCKING_FINDINGS = ("critical", "high", "medium")


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


def _installed_gates(target: str | Path) -> list[str]:
    """Read the resolved gate set from the install snapshot ([] if absent/unreadable)."""
    path = Path(target).expanduser().resolve() / STACK_SNAPSHOT_REL
    if not path.is_file():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return []
    gates = data.get("gates")
    return list(gates) if isinstance(gates, list) else []


def _selection(target: str | Path) -> dict[str, Any]:
    """Read the recorded selection from the install snapshot ({} if absent)."""
    path = Path(target).expanduser().resolve() / STACK_SNAPSHOT_REL
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {}
    sel = data.get("selection")
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


def validate(target: str | Path) -> tuple[bool, list[str]]:
    """Validate the pipeline snapshot's shape and coherence (no writes).

    Absence is not an error — a repo with no active run is valid. When a snapshot is present, every
    field that *is* set must hold a legal value (the schema lets fields be omitted, not malformed),
    and ``last_gate_passed`` must name a gate the installed profile actually defines.
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
    if snap is None:
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

    # A recorded gate's evidence artifact must still exist on disk. Lenient on the upgrade path:
    # a snapshot with no gate_evidence map at all simply doesn't track evidence (the norm for
    # orchestrator-written snapshots) — stay silent; only flag a *partial* map that omits this gate.
    if gate is not None:
        evidence_map = snap.get("gate_evidence")
        if isinstance(evidence_map, dict) and gate in evidence_map:
            ev = evidence_map[gate]
            if not (isinstance(ev, str) and Path(ev).expanduser().is_file()):
                fail(
                    f"last_gate_passed {gate!r} is recorded passed but its evidence file is "
                    f"missing: {ev!r}"
                )
        elif isinstance(evidence_map, dict):
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
    findings = snap.get("open_findings") or {}
    if findings:
        rendered = ", ".join(f"{k}={v}" for k, v in findings.items())
        msgs.append(f"open findings: {rendered}")
    msgs.append(f"next:    {snap.get('next', '(none)')}")
    return True, msgs


def close_gate(
    target: str | Path,
    gate: str,
    evidence: str | Path,
    *,
    force: bool = False,
    override_reason: str | None = None,
) -> tuple[bool, list[str]]:
    """Record ``gate`` as passed (with an evidence artifact) in the snapshot.

    Validates that the evidence file exists and that ``gate`` is a real gate for the installed
    profile, **refuses to pass a gate while critical/high/medium findings are open** (per
    ``rules/quality-gates.md``), then sets ``last_gate_passed`` and stores the evidence path. Seeds a
    minimal snapshot (profile/scope from the install snapshot) if no run snapshot exists yet.

    A forced close (``force=True`` with a non-empty ``override_reason``) bypasses the blocking-findings
    rule but records the reason under ``gate_overrides[gate]`` so ``validate``/``status`` can surface it
    for human review.
    """
    msgs: list[str] = []
    evidence_path = Path(evidence).expanduser().resolve()
    if not evidence_path.is_file():
        return False, [f"FAIL  evidence file not found: {evidence}"]

    gates = _installed_gates(target)
    if gates and gate not in gates:
        return False, [
            f"FAIL  {gate!r} is not a gate of this profile (choices: {', '.join(gates)})"
        ]
    if not gates:
        msgs.append(
            "WARN  no install snapshot — cannot confirm the gate name against the profile"
        )

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

    blocking = _blocking_findings(snap)
    if blocking:
        rendered = ", ".join(f"{sev}={count}" for sev, count in blocking.items())
        if not force:
            return False, [
                f"FAIL  cannot close {gate!r}: {rendered} open finding(s) must be resolved first "
                "(critical/high/medium block a gate per quality-gates.md). "
                "Re-run with --force --override-reason '<why>' to record a deliberate override."
            ]
        if not (override_reason and override_reason.strip()):
            return False, [
                "FAIL  --force requires --override-reason '<why>' explaining why the open "
                f"finding(s) ({rendered}) are being bypassed"
            ]
        overrides = snap.get("gate_overrides")
        if not isinstance(overrides, dict):
            overrides = {}
        overrides[gate] = override_reason.strip()
        snap["gate_overrides"] = overrides
        msgs.append(
            f"WARN  gate {gate!r} force-closed with open findings ({rendered}): "
            f"{override_reason.strip()}"
        )

    snap["last_gate_passed"] = gate
    evidence_map = snap.get("gate_evidence")
    if not isinstance(evidence_map, dict):
        evidence_map = {}
    evidence_map[gate] = str(evidence_path)
    snap["gate_evidence"] = evidence_map

    path = _snapshot_path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snap, indent=2) + "\n", encoding="utf-8")
    msgs.append(f"OK    gate {gate!r} recorded passed (evidence: {evidence_path})")
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
    path = _snapshot_path(target)
    path.write_text(json.dumps(snap, indent=2) + "\n", encoding="utf-8")
    return True, ["OK    pipeline run marked aborted"]
