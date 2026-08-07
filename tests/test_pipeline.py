"""pipeline: validate/status/close-gate/abort operate on the snapshot state files, no SDLC run."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from claude_kit import pipeline
from tests._helpers import install


def _write_snapshot(target, **fields):
    snap = target / ".claude" / "state" / "pipeline-snapshot.json"
    snap.parent.mkdir(parents=True, exist_ok=True)
    snap.write_text(json.dumps(fields), encoding="utf-8")
    return snap


def _coherent():
    return dict(
        schema=1,
        task="demo run",
        profile="standard",
        scope="team",
        mode="B",
        stage="build",
        lanes={"backend": "in-progress", "frontend": "passed"},
        last_gate_passed="code-review",
        open_findings={"critical": 0, "high": 0},
        next="run tests",
    )


def test_validate_absent_snapshot_is_ok(tmp_path, payload):
    install(payload, tmp_path)
    ok, msgs = pipeline.validate(tmp_path)
    assert ok
    assert any("no run in progress" in m for m in msgs)


def test_validate_coherent_snapshot(tmp_path, payload):
    install(payload, tmp_path)
    _write_snapshot(tmp_path, **_coherent())
    ok, msgs = pipeline.validate(tmp_path)
    assert ok, "\n".join(msgs)
    assert any("coherent" in m for m in msgs)


def test_validate_rejects_bad_enums(tmp_path, payload):
    install(payload, tmp_path)
    bad = _coherent()
    bad.update(profile="bogus", scope="nope", mode="Z", lanes={"x": "weird"})
    _write_snapshot(tmp_path, **bad)
    ok, msgs = pipeline.validate(tmp_path)
    assert not ok
    joined = "\n".join(msgs)
    assert "profile 'bogus'" in joined
    assert "scope 'nope'" in joined
    assert "mode 'Z'" in joined
    assert "invalid state 'weird'" in joined


def test_validate_rejects_unknown_gate(tmp_path, payload):
    install(payload, tmp_path)  # standard profile defines a known gate set
    snap = _coherent()
    snap["last_gate_passed"] = "totally-made-up"
    _write_snapshot(tmp_path, **snap)
    ok, msgs = pipeline.validate(tmp_path)
    assert not ok
    assert any("last_gate_passed 'totally-made-up'" in m for m in msgs)


def test_validate_rejects_noninteger_findings(tmp_path, payload):
    install(payload, tmp_path)
    snap = _coherent()
    snap["open_findings"] = {"high": "lots"}
    _write_snapshot(tmp_path, **snap)
    ok, msgs = pipeline.validate(tmp_path)
    assert not ok
    assert any("must be an integer" in m for m in msgs)


def test_validate_rejects_unparseable_snapshot(tmp_path, payload):
    install(payload, tmp_path)
    snap = tmp_path / ".claude" / "state" / "pipeline-snapshot.json"
    snap.parent.mkdir(parents=True, exist_ok=True)
    snap.write_text("{ not json", encoding="utf-8")
    ok, msgs = pipeline.validate(tmp_path)
    assert not ok
    assert any("invalid JSON" in m for m in msgs)


def test_status_renders_fields(tmp_path, payload):
    install(payload, tmp_path)
    _write_snapshot(tmp_path, **_coherent())
    ok, msgs = pipeline.status(tmp_path)
    assert ok
    blob = "\n".join(msgs)
    assert (
        "demo run" in blob
        and "stage:   build" in blob
        and "backend: in-progress" in blob
    )


def test_close_gate_records_evidence_and_gate(tmp_path, payload):
    install(payload, tmp_path)
    _write_snapshot(tmp_path, **_coherent())
    evidence = tmp_path / "coverage.txt"
    evidence.write_text("100%", encoding="utf-8")
    ok, msgs = pipeline.close_gate(tmp_path, "build-green", evidence)
    assert ok, "\n".join(msgs)
    snap = json.loads(
        (tmp_path / ".claude" / "state" / "pipeline-snapshot.json").read_text(
            encoding="utf-8"
        )
    )
    assert snap["last_gate_passed"] == "build-green"
    assert snap["gate_evidence"]["build-green"].endswith("coverage.txt")


def test_close_gate_requires_existing_evidence(tmp_path, payload):
    install(payload, tmp_path)
    _write_snapshot(tmp_path, **_coherent())
    ok, msgs = pipeline.close_gate(tmp_path, "build-green", tmp_path / "missing.txt")
    assert not ok
    assert any("evidence file not found" in m for m in msgs)


def test_close_gate_rejects_unknown_gate(tmp_path, payload):
    install(payload, tmp_path)
    evidence = tmp_path / "e.txt"
    evidence.write_text("x", encoding="utf-8")
    ok, msgs = pipeline.close_gate(tmp_path, "not-a-gate", evidence)
    assert not ok
    assert any("is not a gate of this profile" in m for m in msgs)


def test_close_gate_seeds_snapshot_when_absent(tmp_path, payload):
    install(payload, tmp_path)  # writes the install snapshot (profile=standard)
    evidence = tmp_path / "e.txt"
    evidence.write_text("x", encoding="utf-8")
    assert not (tmp_path / ".claude" / "state" / "pipeline-snapshot.json").is_file()
    ok, msgs = pipeline.close_gate(tmp_path, "code-review", evidence)
    assert ok, "\n".join(msgs)
    snap = json.loads(
        (tmp_path / ".claude" / "state" / "pipeline-snapshot.json").read_text(
            encoding="utf-8"
        )
    )
    assert snap["last_gate_passed"] == "code-review"
    assert snap["profile"] == "standard"  # pulled from the install snapshot


def test_abort_marks_run_aborted(tmp_path, payload):
    install(payload, tmp_path)
    _write_snapshot(tmp_path, **_coherent())
    ok, msgs = pipeline.abort(tmp_path)
    assert ok
    snap = json.loads(
        (tmp_path / ".claude" / "state" / "pipeline-snapshot.json").read_text(
            encoding="utf-8"
        )
    )
    assert snap["stage"] == "aborted"


def test_abort_without_snapshot_is_noop(tmp_path, payload):
    install(payload, tmp_path)
    ok, msgs = pipeline.abort(tmp_path)
    assert ok
    assert any("nothing to abort" in m for m in msgs)


def test_validate_rejects_nondict_lanes_and_findings(tmp_path, payload):
    install(payload, tmp_path)
    snap = _coherent()
    snap["lanes"] = ["backend", "frontend"]  # should be an object
    snap["open_findings"] = [1, 2]  # should be an object
    _write_snapshot(tmp_path, **snap)
    ok, msgs = pipeline.validate(tmp_path)
    assert not ok
    joined = "\n".join(msgs)
    assert "lanes must be an object" in joined
    assert "open_findings must be an object" in joined


def test_validate_rejects_nonobject_snapshot_root(tmp_path, payload):
    install(payload, tmp_path)
    snap = tmp_path / ".claude" / "state" / "pipeline-snapshot.json"
    snap.parent.mkdir(parents=True, exist_ok=True)
    snap.write_text('["not", "an", "object"]', encoding="utf-8")
    ok, msgs = pipeline.validate(tmp_path)
    assert not ok
    assert any("not a JSON object" in m for m in msgs)


def test_close_gate_refuses_blocking_findings(tmp_path, payload):
    install(payload, tmp_path)
    snap = _coherent()
    snap["open_findings"] = {"critical": 1, "high": 0, "medium": 2}
    _write_snapshot(tmp_path, **snap)
    evidence = tmp_path / "e.txt"
    evidence.write_text("x", encoding="utf-8")
    ok, msgs = pipeline.close_gate(tmp_path, "code-review", evidence)
    assert not ok
    joined = "\n".join(msgs)
    assert "cannot close" in joined and "critical=1" in joined and "medium=2" in joined
    # the gate must NOT have been recorded
    written = json.loads(
        (tmp_path / ".claude" / "state" / "pipeline-snapshot.json").read_text(
            encoding="utf-8"
        )
    )
    assert (
        written.get("last_gate_passed") == "code-review"
    )  # the pre-existing value, unchanged
    assert "build-green" not in (written.get("gate_evidence") or {})


def test_close_gate_allows_low_findings(tmp_path, payload):
    install(payload, tmp_path)
    snap = _coherent()
    snap["open_findings"] = {"critical": 0, "high": 0, "medium": 0, "low": 5}
    _write_snapshot(tmp_path, **snap)
    evidence = tmp_path / "e.txt"
    evidence.write_text("x", encoding="utf-8")
    ok, msgs = pipeline.close_gate(tmp_path, "build-green", evidence)
    assert ok, "\n".join(msgs)  # low findings do not block


def test_close_gate_force_requires_reason(tmp_path, payload):
    install(payload, tmp_path)
    snap = _coherent()
    snap["open_findings"] = {"high": 3}
    _write_snapshot(tmp_path, **snap)
    evidence = tmp_path / "e.txt"
    evidence.write_text("x", encoding="utf-8")
    ok, msgs = pipeline.close_gate(tmp_path, "build-green", evidence, force=True)
    assert not ok
    assert any("--force requires --override-reason" in m for m in msgs)


def test_close_gate_force_with_reason_records_override(tmp_path, payload):
    install(payload, tmp_path)
    snap = _coherent()
    snap["open_findings"] = {"high": 3}
    _write_snapshot(tmp_path, **snap)
    evidence = tmp_path / "e.txt"
    evidence.write_text("x", encoding="utf-8")
    ok, msgs = pipeline.close_gate(
        tmp_path,
        "build-green",
        evidence,
        force=True,
        override_reason="hotfix: blocked finding tracked in TICKET-1",
    )
    assert ok, "\n".join(msgs)
    assert any("force-closed" in m for m in msgs)
    written = json.loads(
        (tmp_path / ".claude" / "state" / "pipeline-snapshot.json").read_text(
            encoding="utf-8"
        )
    )
    assert written["last_gate_passed"] == "build-green"
    assert written["gate_overrides"]["build-green"].startswith("hotfix:")


def test_validate_fails_when_evidence_file_gone(tmp_path, payload):
    install(payload, tmp_path)
    snap = _coherent()
    snap["gate_evidence"] = {"code-review": str(tmp_path / "deleted-evidence.txt")}
    _write_snapshot(tmp_path, **snap)
    ok, msgs = pipeline.validate(tmp_path)
    assert not ok
    assert any("evidence file is missing" in m for m in msgs)


def test_validate_passes_when_evidence_file_present(tmp_path, payload):
    install(payload, tmp_path)
    evidence = tmp_path / "review.md"
    evidence.write_text("approved", encoding="utf-8")
    snap = _coherent()
    snap["gate_evidence"] = {"code-review": str(evidence)}
    _write_snapshot(tmp_path, **snap)
    ok, msgs = pipeline.validate(tmp_path)
    assert ok, "\n".join(msgs)


def test_validate_surfaces_forced_gate(tmp_path, payload):
    install(payload, tmp_path)
    evidence = tmp_path / "review.md"
    evidence.write_text("approved", encoding="utf-8")
    snap = _coherent()
    snap["gate_evidence"] = {"code-review": str(evidence)}
    snap["gate_overrides"] = {"code-review": "bypassed for hotfix"}
    _write_snapshot(tmp_path, **snap)
    ok, msgs = pipeline.validate(tmp_path)
    assert ok, "\n".join(msgs)
    assert any("force-closed" in m for m in msgs)


def test_close_gate_warns_when_install_snapshot_missing(tmp_path):
    # No install() → no .claude/config/stack-catalog.snapshot.yaml to confirm the gate against.
    (tmp_path / ".claude" / "state").mkdir(parents=True, exist_ok=True)
    evidence = tmp_path / "e.txt"
    evidence.write_text("x", encoding="utf-8")
    ok, msgs = pipeline.close_gate(tmp_path, "some-gate", evidence)
    assert ok  # a warning, not a failure
    assert any("cannot confirm the gate name" in m for m in msgs)


# --- Mode E (wave/program runs) ---------------------------------------------------------------


def test_validate_accepts_mode_e_snapshot(tmp_path, payload):
    install(payload, tmp_path)
    snap = _coherent()
    snap["mode"] = "E"
    snap["lanes"] = {"wave-0-audit": "passed", "wave-1-mechanical": "in-progress"}
    _write_snapshot(tmp_path, **snap)
    ok, msgs = pipeline.validate(tmp_path)
    assert ok, "\n".join(msgs)


def test_status_renders_mode_e(tmp_path, payload):
    install(payload, tmp_path)
    snap = _coherent()
    snap["mode"] = "E"
    _write_snapshot(tmp_path, **snap)
    ok, msgs = pipeline.status(tmp_path)
    assert ok
    assert any("mode: E" in m for m in msgs)


def test_modes_drift_guard_against_continuity_rule(payload):
    """The mode enum lives in pipeline.MODES; rules/continuity.md documents it. Keep them equal."""
    import re

    doc = (payload / "rules" / "continuity.md").read_text(encoding="utf-8")
    match = re.search(r'"mode":\s*"([A-Z\s|]+)"', doc)
    assert match, "rules/continuity.md no longer documents the mode enum"
    documented = {tok.strip() for tok in match.group(1).split("|")}
    assert documented == set(pipeline.MODES), (
        f"mode enum drift: rules/continuity.md documents {sorted(documented)}, "
        f"pipeline.MODES is {sorted(pipeline.MODES)}"
    )


# --- Gate ledger: order enforcement -----------------------------------------------------------
# Standard-profile execution order: spec-complete, em-approved, code-review, build-green,
# contract-clear (MR2), test-coverage, security-clear (pinned in test_catalog.py's
# test_gates_resolve_in_execution_order). _coherent() anchors at code-review → next is build-green.


def _read_snap(target):
    return json.loads(
        (target / ".claude" / "state" / "pipeline-snapshot.json").read_text(
            encoding="utf-8"
        )
    )


def test_close_gate_rejects_out_of_order(tmp_path, payload):
    install(payload, tmp_path)
    _write_snapshot(tmp_path, **_coherent())
    evidence = tmp_path / "e.txt"
    evidence.write_text("x", encoding="utf-8")
    ok, msgs = pipeline.close_gate(tmp_path, "security-clear", evidence)
    assert not ok
    joined = "\n".join(msgs)
    assert "out of order" in joined and "'build-green'" in joined
    assert _read_snap(tmp_path)["last_gate_passed"] == "code-review"  # unchanged


def test_close_gate_rejects_regression_behind_position(tmp_path, payload):
    install(payload, tmp_path)
    _write_snapshot(tmp_path, **_coherent())
    evidence = tmp_path / "e.txt"
    evidence.write_text("x", encoding="utf-8")
    ok, msgs = pipeline.close_gate(tmp_path, "spec-complete", evidence)
    assert not ok
    assert any("recorded or superseded" in m for m in msgs)


def test_close_gate_force_overrides_order(tmp_path, payload):
    install(payload, tmp_path)
    _write_snapshot(tmp_path, **_coherent())
    evidence = tmp_path / "e.txt"
    evidence.write_text("x", encoding="utf-8")
    ok, msgs = pipeline.close_gate(
        tmp_path,
        "security-clear",
        evidence,
        force=True,
        override_reason="hotfix lane: security scan ran ahead of build",
    )
    assert ok, "\n".join(msgs)
    snap = _read_snap(tmp_path)
    entry = snap["gate_history"][-1]
    assert entry["status"] == "overridden"
    assert entry["verification"] == "override"
    assert snap["gate_overrides"]["security-clear"].startswith("hotfix lane")


def test_close_gate_bootstrap_anchors_anywhere_then_enforces(tmp_path, payload):
    install(payload, tmp_path)  # no run snapshot yet: first record may open at any gate
    evidence = tmp_path / "e.txt"
    evidence.write_text("x", encoding="utf-8")
    ok, msgs = pipeline.close_gate(tmp_path, "build-green", evidence)
    assert ok, "\n".join(msgs)
    ok, msgs = pipeline.close_gate(
        tmp_path, "code-review", evidence
    )  # behind the anchor
    assert not ok
    assert any("recorded or superseded" in m for m in msgs)


def test_close_gate_appends_ledger_entry_with_hash(tmp_path, payload):
    import hashlib

    install(payload, tmp_path)
    _write_snapshot(tmp_path, **_coherent())
    evidence = tmp_path / "coverage.txt"
    evidence.write_text("94% lines", encoding="utf-8")
    ok, msgs = pipeline.close_gate(tmp_path, "build-green", evidence)
    assert ok, "\n".join(msgs)
    entry = _read_snap(tmp_path)["gate_history"][-1]
    assert entry["gate"] == "build-green"
    assert entry["status"] == "passed"
    assert entry["verification"] == "agent"
    assert entry["evidence_sha256"] == hashlib.sha256(b"94% lines").hexdigest()
    assert entry["recorded_at"]  # UTC ISO timestamp present


# --- Gate ledger: skip-gate --------------------------------------------------------------------


def test_skip_gate_requires_reason(tmp_path, payload):
    install(payload, tmp_path)
    _write_snapshot(tmp_path, **_coherent())
    ok, msgs = pipeline.skip_gate(tmp_path, "build-green", "  ")
    assert not ok
    assert any("requires --reason" in m for m in msgs)


def test_skip_gate_records_and_advances_position(tmp_path, payload):
    install(payload, tmp_path)
    _write_snapshot(tmp_path, **_coherent())
    ok, msgs = pipeline.skip_gate(
        tmp_path, "build-green", "docs-only change: nothing to build"
    )
    assert ok, "\n".join(msgs)
    entry = _read_snap(tmp_path)["gate_history"][-1]
    assert entry["status"] == "skipped" and entry["evidence_path"] is None
    assert entry["verification"] == "agent"  # a skip is NOT a human attestation
    # the skip advanced the position: contract-clear (MR2) is now the legal next gate
    evidence = tmp_path / "e.txt"
    evidence.write_text("x", encoding="utf-8")
    ok, msgs = pipeline.close_gate(tmp_path, "contract-clear", evidence)
    assert ok, "\n".join(msgs)


def test_skip_gate_rejects_out_of_order(tmp_path, payload):
    install(payload, tmp_path)
    _write_snapshot(tmp_path, **_coherent())
    ok, msgs = pipeline.skip_gate(tmp_path, "security-clear", "not applicable")
    assert not ok
    assert any("out of order" in m for m in msgs)


# --- Gate ledger: validate re-verifies every entry ----------------------------------------------


def test_validate_fails_on_evidence_hash_mismatch(tmp_path, payload):
    install(payload, tmp_path)
    _write_snapshot(tmp_path, **_coherent())
    evidence = tmp_path / "review.md"
    evidence.write_text("approved", encoding="utf-8")
    ok, msgs = pipeline.close_gate(tmp_path, "build-green", evidence)
    assert ok, "\n".join(msgs)
    evidence.write_text("approved (edited after the gate closed)", encoding="utf-8")
    ok, msgs = pipeline.validate(tmp_path)
    assert not ok
    assert any("hash mismatch" in m for m in msgs)


def test_validate_fails_on_disordered_history(tmp_path, payload):
    install(payload, tmp_path)
    evidence = tmp_path / "e.txt"
    evidence.write_text("x", encoding="utf-8")
    snap = _coherent()
    snap["gate_history"] = [
        {"gate": "build-green", "status": "passed", "evidence_path": str(evidence)},
        {"gate": "code-review", "status": "passed", "evidence_path": str(evidence)},
    ]
    _write_snapshot(tmp_path, **snap)
    ok, msgs = pipeline.validate(tmp_path)
    assert not ok
    assert any("out of the installed gate order" in m for m in msgs)


def test_validate_checks_historical_entries_not_just_latest(tmp_path, payload):
    install(payload, tmp_path)
    evidence = tmp_path / "e.txt"
    evidence.write_text("x", encoding="utf-8")
    snap = _coherent()
    snap["gate_history"] = [
        {
            "gate": "code-review",
            "status": "passed",
            "evidence_path": str(tmp_path / "gone.txt"),  # historical evidence deleted
        },
        {"gate": "build-green", "status": "passed", "evidence_path": str(evidence)},
    ]
    snap["last_gate_passed"] = "build-green"
    _write_snapshot(tmp_path, **snap)
    ok, msgs = pipeline.validate(tmp_path)
    assert not ok
    assert any("gate_history[0]" in m and "missing" in m for m in msgs)


# --- Strict mode fails closed --------------------------------------------------------------------


def test_close_gate_strict_fails_without_install_snapshot(tmp_path):
    (tmp_path / ".claude" / "state").mkdir(parents=True, exist_ok=True)
    evidence = tmp_path / "e.txt"
    evidence.write_text("x", encoding="utf-8")
    ok, msgs = pipeline.close_gate(tmp_path, "some-gate", evidence, strict=True)
    assert not ok
    assert any("--strict" in m for m in msgs)


def test_validate_strict_fails_without_install_snapshot(tmp_path):
    _write_snapshot(tmp_path, **_coherent())
    ok, msgs = pipeline.validate(tmp_path, strict=True)
    assert not ok
    assert any("--strict" in m for m in msgs)


# --- Atomic writes + locking ---------------------------------------------------------------------


def test_leftover_tmp_file_is_ignored(tmp_path, payload):
    install(payload, tmp_path)
    _write_snapshot(tmp_path, **_coherent())
    state = tmp_path / ".claude" / "state"
    (state / "pipeline-snapshot.json.tmp12345").write_text(
        "{ crashed", encoding="utf-8"
    )
    ok, msgs = pipeline.validate(tmp_path)
    assert ok, "\n".join(
        msgs
    )  # a crashed writer's temp file never corrupts the snapshot


def test_stale_lock_fails_cleanly(tmp_path, payload, monkeypatch):
    monkeypatch.setattr(pipeline, "_LOCK_TIMEOUT_S", 0.2)
    install(payload, tmp_path)
    _write_snapshot(tmp_path, **_coherent())
    state = tmp_path / ".claude" / "state"
    (state / "pipeline-snapshot.json.lock").write_text("", encoding="utf-8")
    evidence = tmp_path / "e.txt"
    evidence.write_text("x", encoding="utf-8")
    ok, msgs = pipeline.close_gate(tmp_path, "build-green", evidence)
    assert not ok
    assert any("could not lock" in m for m in msgs)
    assert _read_snap(tmp_path)["last_gate_passed"] == "code-review"  # nothing written


# --- adversarial-review regressions (0.76.0 pre-merge hardening) ----------------------------


def test_force_rerecord_keeps_validate_ok(tmp_path, payload):
    """A sanctioned --force re-record is `overridden`, and validate treats it as reviewable —
    never as order tampering that poisons every later validate of the run."""
    install(payload, tmp_path)
    _write_snapshot(tmp_path, **_coherent())
    ev = tmp_path / "e.txt"
    ev.write_text("x", encoding="utf-8")
    assert pipeline.close_gate(tmp_path, "build-green", ev)[0]
    ok, msgs = pipeline.close_gate(
        tmp_path,
        "build-green",
        ev,
        force=True,
        override_reason="re-ran the build after a flaky failure",
    )
    assert ok, "\n".join(msgs)
    ok, msgs = pipeline.validate(tmp_path)
    assert ok, "\n".join(msgs)  # WARNs surface the override; the run stays coherent
    assert any("force-closed" in m for m in msgs)


def test_force_rerecord_without_reason_fails_on_order_path(tmp_path, payload):
    """--force without --override-reason is refused on the order path too (not only findings)."""
    install(payload, tmp_path)
    _write_snapshot(tmp_path, **_coherent())
    ev = tmp_path / "e.txt"
    ev.write_text("x", encoding="utf-8")
    assert pipeline.close_gate(tmp_path, "build-green", ev)[0]
    ok, msgs = pipeline.close_gate(tmp_path, "build-green", ev, force=True)
    assert not ok
    assert any("--override-reason" in m for m in msgs)


def test_position_never_rewinds_after_forced_backfill(tmp_path, payload):
    """A forced backfill of an earlier gate must not rewind the run: the resume anchor stays,
    and the next legal gate is still derived from the FURTHEST recorded position."""
    install(payload, tmp_path)
    _write_snapshot(tmp_path, **_coherent())  # position: code-review
    ev = tmp_path / "e.txt"
    ev.write_text("x", encoding="utf-8")
    assert pipeline.close_gate(tmp_path, "build-green", ev)[0]
    ok, msgs = pipeline.close_gate(
        tmp_path,
        "spec-complete",
        ev,
        force=True,
        override_reason="backfilling the spec record for audit completeness",
    )
    assert ok, "\n".join(msgs)
    assert _read_snap(tmp_path)["last_gate_passed"] == "build-green"
    assert any("never moves backwards" in m for m in msgs)
    # Next legal gate is contract-clear (after build-green) — NOT em-approved (after the backfill).
    ok, msgs = pipeline.close_gate(tmp_path, "test-coverage", ev)
    assert not ok and any("contract-clear" in m for m in msgs)
    assert pipeline.close_gate(tmp_path, "contract-clear", ev)[0]


def test_close_and_skip_refuse_on_aborted_run(tmp_path, payload):
    """Abort is terminal for the ledger — no gate may be recorded onto an aborted run."""
    install(payload, tmp_path)
    _write_snapshot(tmp_path, **_coherent())
    assert pipeline.abort(tmp_path)[0]
    ev = tmp_path / "e.txt"
    ev.write_text("x", encoding="utf-8")
    ok, msgs = pipeline.close_gate(tmp_path, "build-green", ev)
    assert not ok and any("aborted" in m for m in msgs)
    ok, msgs = pipeline.skip_gate(tmp_path, "build-green", "does not apply")
    assert not ok and any("aborted" in m for m in msgs)


def test_relative_evidence_resolves_against_project_root_not_cwd(
    tmp_path, payload, monkeypatch
):
    """A relative --evidence path means project-relative — the caller's CWD is irrelevant,
    and the stored path stays project-relative so the ledger is portable."""
    install(payload, tmp_path)
    _write_snapshot(tmp_path, **_coherent())
    (tmp_path / "artifacts").mkdir()
    (tmp_path / "artifacts" / "build.log").write_text("ok", encoding="utf-8")
    elsewhere = tmp_path / "unrelated-cwd"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    ok, msgs = pipeline.close_gate(tmp_path, "build-green", "artifacts/build.log")
    assert ok, "\n".join(msgs)
    entry = _read_snap(tmp_path)["gate_history"][-1]
    assert entry["evidence_path"] == "artifacts/build.log"
    ok, msgs = pipeline.validate(tmp_path)  # still from the foreign CWD
    assert ok, "\n".join(msgs)


def test_ledger_survives_relocated_checkout(tmp_path, payload):
    """CI clones land at a different absolute path — a project-relative ledger still verifies."""
    proj = tmp_path / "proj"
    proj.mkdir()
    install(payload, proj)
    _write_snapshot(proj, **_coherent())
    (proj / "cov.txt").write_text("100%", encoding="utf-8")
    assert pipeline.close_gate(proj, "build-green", proj / "cov.txt")[0]
    moved = tmp_path / "renamed-checkout"
    proj.rename(moved)
    ok, msgs = pipeline.validate(moved)
    assert ok, "\n".join(msgs)


def test_evidence_outside_project_recorded_absolute_with_warning(tmp_path, payload):
    """Out-of-tree evidence still closes the gate, but the non-portability is said out loud."""
    install(payload, tmp_path)
    _write_snapshot(tmp_path, **_coherent())
    outside = tmp_path.parent / f"{tmp_path.name}-outside-evidence.txt"
    outside.write_text("x", encoding="utf-8")
    ok, msgs = pipeline.close_gate(tmp_path, "build-green", outside)
    assert ok, "\n".join(msgs)
    assert any("outside the project" in m for m in msgs)
    entry = _read_snap(tmp_path)["gate_history"][-1]
    assert Path(entry["evidence_path"]).is_absolute()


def test_concurrent_closes_one_wins_one_refused(tmp_path, payload):
    """The lock spans the whole read-modify-write: two racers on the same gate cannot both
    win, and the loser gets a clean refusal instead of silently overwriting the winner."""
    install(payload, tmp_path)
    _write_snapshot(tmp_path, **_coherent())
    ev = tmp_path / "e.txt"
    ev.write_text("x", encoding="utf-8")
    results = []
    barrier = threading.Barrier(2)

    def racer():
        barrier.wait()
        results.append(pipeline.close_gate(tmp_path, "build-green", ev))

    threads = [threading.Thread(target=racer) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wins = [msgs for ok, msgs in results if ok]
    losses = [msgs for ok, msgs in results if not ok]
    assert len(wins) == 1 and len(losses) == 1, results
    assert any("recorded or superseded" in m for m in losses[0])
    assert (
        len(_read_snap(tmp_path)["gate_history"]) == 1
    )  # no lost update, no double entry


def test_validate_warns_on_foreign_profile_history_entry(tmp_path, payload):
    """A history gate from another profile's set is reviewable drift, not corruption — the
    snapshot may have been recorded before a profile change."""
    install(payload, tmp_path)  # standard: pipeline-green is enterprise-only
    snap = _coherent()
    snap["gate_history"] = [
        {
            "gate": "pipeline-green",
            "status": "passed",
            "evidence_path": "e.txt",
            "evidence_sha256": None,
            "verification": "agent",
            "recorded_at": "2026-08-01T00:00:00+00:00",
            "override": None,
        }
    ]
    _write_snapshot(tmp_path, **snap)
    (tmp_path / "e.txt").write_text("x", encoding="utf-8")
    ok, msgs = pipeline.validate(tmp_path)
    assert ok, "\n".join(msgs)
    assert any("not a gate of the installed profile" in m for m in msgs)


def test_stale_lock_is_reclaimed_with_warning(tmp_path, payload):
    """A lock left by a crashed writer (old mtime) is stolen with a WARN, not a dead pipeline."""
    install(payload, tmp_path)
    _write_snapshot(tmp_path, **_coherent())
    lock = tmp_path / ".claude" / "state" / "pipeline-snapshot.json.lock"
    lock.write_text("99999", encoding="utf-8")
    old = time.time() - 120  # well past _LOCK_STALE_S
    os.utime(lock, (old, old))
    ev = tmp_path / "e.txt"
    ev.write_text("x", encoding="utf-8")
    ok, msgs = pipeline.close_gate(tmp_path, "build-green", ev)
    assert ok, "\n".join(msgs)
    assert any("stale snapshot lock" in m for m in msgs)
    assert not lock.exists()


# --- Unreadable install snapshot: lenient by default, fail-closed under --strict ----------------
# The gate list comes from the install snapshot. When it cannot be read, the validator must say so
# rather than silently reporting "coherent" against an empty gate set — that is the difference
# between "order was checked and held" and "order could not be checked at all".


def _install_snapshot(target):
    return target / ".claude" / "config" / "stack-catalog.snapshot.yaml"


def test_validate_warns_when_install_snapshot_is_unparseable(tmp_path, payload):
    install(payload, tmp_path)
    _install_snapshot(tmp_path).write_text("gates: [a, b\n", encoding="utf-8")
    _write_snapshot(tmp_path, **_coherent())
    ok, msgs = pipeline.validate(tmp_path)
    assert ok, "\n".join(msgs)
    assert any(m.startswith("WARN") and "invalid YAML" in m for m in msgs)


def test_validate_strict_fails_on_unparseable_install_snapshot(tmp_path, payload):
    install(payload, tmp_path)
    _install_snapshot(tmp_path).write_text("gates: [a, b\n", encoding="utf-8")
    _write_snapshot(tmp_path, **_coherent())
    ok, msgs = pipeline.validate(tmp_path, strict=True)
    assert not ok
    assert any("invalid YAML" in m and "--strict" in m for m in msgs)


def test_validate_warns_when_install_snapshot_is_not_a_mapping(tmp_path, payload):
    """A YAML document that parses but isn't a mapping has no gate list to offer."""
    install(payload, tmp_path)
    _install_snapshot(tmp_path).write_text("- gates\n- selection\n", encoding="utf-8")
    _write_snapshot(tmp_path, **_coherent())
    ok, msgs = pipeline.validate(tmp_path)
    assert ok, "\n".join(msgs)
    assert any("not a YAML mapping" in m for m in msgs)


def test_close_gate_refuses_unreadable_install_snapshot_under_strict(tmp_path, payload):
    install(payload, tmp_path)
    _install_snapshot(tmp_path).write_text("gates: [a, b\n", encoding="utf-8")
    ev = tmp_path / "e.txt"
    ev.write_text("x", encoding="utf-8")
    ok, msgs = pipeline.close_gate(tmp_path, "build-green", ev, strict=True)
    assert not ok
    assert any("refusing to record a gate (--strict)" in m for m in msgs)
    assert not (tmp_path / ".claude" / "state" / "pipeline-snapshot.json").exists()


def test_close_gate_warns_and_records_on_unreadable_install_snapshot(tmp_path, payload):
    """Default (lenient) mode keeps a mid-run human unblocked, but flags the blind spot."""
    install(payload, tmp_path)
    _install_snapshot(tmp_path).write_text("gates: [a, b\n", encoding="utf-8")
    ev = tmp_path / "e.txt"
    ev.write_text("x", encoding="utf-8")
    ok, msgs = pipeline.close_gate(tmp_path, "build-green", ev)
    assert ok, "\n".join(msgs)
    assert any("cannot confirm the gate name or order" in m for m in msgs)
    assert _read_snap(tmp_path)["last_gate_passed"] == "build-green"


# --- Snapshot field validation: each malformed field is reported, not ignored -------------------


def test_validate_warns_on_unexpected_schema(tmp_path, payload):
    install(payload, tmp_path)
    snap = _coherent()
    snap["schema"] = 2
    _write_snapshot(tmp_path, **snap)
    ok, msgs = pipeline.validate(tmp_path)
    assert ok, "\n".join(msgs)
    assert any("unexpected snapshot schema" in m for m in msgs)


def test_validate_accepts_minimal_snapshot_but_flags_thin_resume_context(
    tmp_path, payload
):
    """No lanes, no findings, no gate — legal, but the resume context is called out as weak."""
    install(payload, tmp_path)
    _write_snapshot(tmp_path, schema=1, profile="standard")
    ok, msgs = pipeline.validate(tmp_path)
    assert ok, "\n".join(msgs)
    for field in ("task", "stage", "next"):
        assert any(f"no {field!r}" in m for m in msgs), field


def test_validate_warns_on_unknown_finding_severity(tmp_path, payload):
    install(payload, tmp_path)
    snap = _coherent()
    snap["open_findings"] = {"critical": 0, "cosmetic": 2}
    _write_snapshot(tmp_path, **snap)
    ok, msgs = pipeline.validate(tmp_path)
    assert ok, "\n".join(msgs)
    assert any("unknown severity 'cosmetic'" in m for m in msgs)


def test_validate_rejects_nondict_gate_overrides(tmp_path, payload):
    install(payload, tmp_path)
    snap = _coherent()
    snap["gate_overrides"] = ["code-review"]
    _write_snapshot(tmp_path, **snap)
    ok, msgs = pipeline.validate(tmp_path)
    assert not ok
    assert any("gate_overrides must be an object" in m for m in msgs)


def test_validate_warns_when_last_gate_has_no_recorded_evidence_path(tmp_path, payload):
    """A partial gate_evidence map that omits the passed gate is a gap worth surfacing."""
    install(payload, tmp_path)
    snap = _coherent()
    snap["gate_evidence"] = {"spec-complete": "docs/spec.md"}
    _write_snapshot(tmp_path, **snap)
    ok, msgs = pipeline.validate(tmp_path)
    assert ok, "\n".join(msgs)
    assert any("has no recorded gate_evidence path" in m for m in msgs)


# --- Ledger entry validation --------------------------------------------------------------------


def test_validate_rejects_nonlist_gate_history(tmp_path, payload):
    install(payload, tmp_path)
    snap = _coherent()
    snap["gate_history"] = {"code-review": "passed"}
    _write_snapshot(tmp_path, **snap)
    ok, msgs = pipeline.validate(tmp_path)
    assert not ok
    assert any("gate_history must be an array" in m for m in msgs)


def test_validate_rejects_non_object_ledger_entries(tmp_path, payload):
    install(payload, tmp_path)
    snap = _coherent()
    snap["gate_history"] = ["code-review"]
    _write_snapshot(tmp_path, **snap)
    ok, msgs = pipeline.validate(tmp_path)
    assert not ok
    assert any("contains non-object entries" in m for m in msgs)


def test_validate_rejects_ledger_entry_without_a_gate_name(tmp_path, payload):
    install(payload, tmp_path)
    snap = _coherent()
    snap["gate_history"] = [{"status": "passed", "evidence_path": "e.txt"}]
    _write_snapshot(tmp_path, **snap)
    ok, msgs = pipeline.validate(tmp_path)
    assert not ok
    assert any("has no gate name" in m for m in msgs)


def test_validate_rejects_ledger_entry_with_unknown_status(tmp_path, payload):
    install(payload, tmp_path)
    ev = tmp_path / "e.txt"
    ev.write_text("x", encoding="utf-8")
    snap = _coherent()
    snap["gate_history"] = [
        {"gate": "code-review", "status": "probably", "evidence_path": "e.txt"}
    ]
    _write_snapshot(tmp_path, **snap)
    ok, msgs = pipeline.validate(tmp_path)
    assert not ok
    assert any("status 'probably' is not one of" in m for m in msgs)


def test_validate_warns_on_unknown_verification_level(tmp_path, payload):
    """An unrecognised verification level must not be read as a stronger claim than it is."""
    install(payload, tmp_path)
    ev = tmp_path / "e.txt"
    ev.write_text("x", encoding="utf-8")
    snap = _coherent()
    snap["gate_history"] = [
        {
            "gate": "code-review",
            "status": "passed",
            "evidence_path": "e.txt",
            "verification": "vibes",
        }
    ]
    _write_snapshot(tmp_path, **snap)
    ok, msgs = pipeline.validate(tmp_path)
    assert ok, "\n".join(msgs)
    assert any("verification 'vibes' is not one of" in m for m in msgs)


def test_validate_rejects_passed_ledger_entry_without_evidence(tmp_path, payload):
    install(payload, tmp_path)
    snap = _coherent()
    snap["gate_history"] = [{"gate": "code-review", "status": "passed"}]
    _write_snapshot(tmp_path, **snap)
    ok, msgs = pipeline.validate(tmp_path)
    assert not ok
    assert any("has no evidence_path" in m for m in msgs)


def test_validate_warns_on_skip_without_a_reason_and_accepts_one_with(
    tmp_path, payload
):
    """A skip carries no evidence, so its reason is the only record of why the gate was bypassed."""
    install(payload, tmp_path)
    snap = _coherent()
    snap["last_gate_passed"] = "spec-complete"
    snap["gate_history"] = [
        {"gate": "spec-complete", "status": "skipped"},
        {"gate": "em-approved", "status": "skipped", "reason": "solo project, no EM"},
    ]
    _write_snapshot(tmp_path, **snap)
    ok, msgs = pipeline.validate(tmp_path)
    assert ok, "\n".join(msgs)
    assert any("skipped without a reason" in m for m in msgs)
    assert sum("skipped without a reason" in m for m in msgs) == 1


def test_validate_checks_ledger_entries_without_an_installed_gate_list(tmp_path):
    """With no install snapshot there is no order to check, but entries are still verified."""
    ev = tmp_path / "e.txt"
    ev.write_text("x", encoding="utf-8")
    _write_snapshot(
        tmp_path,
        schema=1,
        task="t",
        stage="build",
        next="n",
        gate_history=[
            {"gate": "code-review", "status": "passed", "evidence_path": "e.txt"}
        ],
    )
    ok, msgs = pipeline.validate(tmp_path)
    assert ok, "\n".join(msgs)
    assert any("no evidence_sha256" in m for m in msgs)


# --- status() rendering ---------------------------------------------------------------------


def test_status_fails_on_unparseable_snapshot(tmp_path, payload):
    install(payload, tmp_path)
    snap_path = tmp_path / ".claude" / "state" / "pipeline-snapshot.json"
    snap_path.parent.mkdir(parents=True, exist_ok=True)
    snap_path.write_text("{not json", encoding="utf-8")
    ok, msgs = pipeline.status(tmp_path)
    assert not ok
    assert any("invalid JSON" in m for m in msgs)


def test_status_renders_ledger_detail_and_omits_empty_sections(tmp_path, payload):
    """Each optional ledger annotation appears only when present; empty sections stay silent."""
    install(payload, tmp_path)
    _write_snapshot(
        tmp_path,
        schema=1,
        task="demo",
        stage="build",
        next="run tests",
        gate_history=[
            {"gate": "spec-complete", "status": "passed"},
            {"gate": "em-approved", "status": "passed", "verification": "agent"},
            {"gate": "code-review", "status": "overridden", "override": "hotfix"},
            {"gate": "build-green", "status": "skipped", "reason": "no build step"},
        ],
    )
    ok, msgs = pipeline.status(tmp_path)
    assert ok
    joined = "\n".join(msgs)
    assert "gate history:" in joined
    assert "- spec-complete: passed" in joined
    assert "verification=agent" in joined
    assert "override='hotfix'" in joined
    assert "reason='no build step'" in joined
    assert "lanes:" not in joined
    assert "open findings:" not in joined


# --- Read-modify-write failure paths ------------------------------------------------------------


def _corrupt_snapshot(target):
    path = target / ".claude" / "state" / "pipeline-snapshot.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    return path


def test_close_gate_refuses_to_overwrite_an_unparseable_snapshot(tmp_path, payload):
    """A corrupt snapshot must be reported, never silently replaced with a fresh one."""
    install(payload, tmp_path)
    path = _corrupt_snapshot(tmp_path)
    ev = tmp_path / "e.txt"
    ev.write_text("x", encoding="utf-8")
    ok, msgs = pipeline.close_gate(tmp_path, "spec-complete", ev)
    assert not ok
    assert any("invalid JSON" in m for m in msgs)
    assert path.read_text(encoding="utf-8") == "{not json"


def test_skip_gate_refuses_to_overwrite_an_unparseable_snapshot(tmp_path, payload):
    install(payload, tmp_path)
    path = _corrupt_snapshot(tmp_path)
    ok, msgs = pipeline.skip_gate(tmp_path, "spec-complete", "not applicable")
    assert not ok
    assert any("invalid JSON" in m for m in msgs)
    assert path.read_text(encoding="utf-8") == "{not json"


def test_abort_refuses_to_overwrite_an_unparseable_snapshot(tmp_path, payload):
    install(payload, tmp_path)
    path = _corrupt_snapshot(tmp_path)
    ok, msgs = pipeline.abort(tmp_path)
    assert not ok
    assert any("invalid JSON" in m for m in msgs)
    assert path.read_text(encoding="utf-8") == "{not json"


def test_abort_is_a_noop_when_the_snapshot_vanishes_mid_operation(
    tmp_path, payload, monkeypatch
):
    """Models the race where another process deletes the snapshot between the check and the read."""
    install(payload, tmp_path)
    _write_snapshot(tmp_path, **_coherent())
    monkeypatch.setattr(pipeline, "_load_snapshot", lambda target: (None, None))
    ok, msgs = pipeline.abort(tmp_path)
    assert ok
    assert any("nothing to abort" in m for m in msgs)


def test_close_gate_force_preserves_existing_overrides(tmp_path, payload):
    install(payload, tmp_path)
    snap = _coherent()
    snap["gate_overrides"] = {"spec-complete": "adopted mid-flight"}
    _write_snapshot(tmp_path, **snap)
    ev = tmp_path / "e.txt"
    ev.write_text("x", encoding="utf-8")
    ok, msgs = pipeline.close_gate(
        tmp_path,
        "security-clear",
        ev,
        force=True,
        override_reason="scanner ran ahead of build in the hotfix lane",
    )
    assert ok, "\n".join(msgs)
    overrides = _read_snap(tmp_path)["gate_overrides"]
    assert overrides["spec-complete"] == "adopted mid-flight"
    assert "hotfix lane" in overrides["security-clear"]


# --- skip_gate guard rails ------------------------------------------------------------------


def test_skip_gate_refuses_without_install_snapshot_under_strict(tmp_path):
    (tmp_path / ".claude" / "state").mkdir(parents=True, exist_ok=True)
    ok, msgs = pipeline.skip_gate(tmp_path, "build-green", "no build step", strict=True)
    assert not ok
    assert any("refusing to record a gate (--strict)" in m for m in msgs)


def test_skip_gate_rejects_a_gate_outside_the_profile(tmp_path, payload):
    install(payload, tmp_path)
    ok, msgs = pipeline.skip_gate(tmp_path, "not-a-gate", "does not apply")
    assert not ok
    assert any("is not a gate of this profile" in m for m in msgs)


def test_skip_gate_repairs_a_non_list_gate_history(tmp_path, payload):
    """A hand-mangled history must not crash the writer; the skip still lands as a real entry."""
    install(payload, tmp_path)
    snap = _coherent()
    snap["gate_history"] = "not-a-list"
    _write_snapshot(tmp_path, **snap)
    ok, msgs = pipeline.skip_gate(tmp_path, "build-green", "no build step in this repo")
    assert ok, "\n".join(msgs)
    history = _read_snap(tmp_path)["gate_history"]
    assert [e["gate"] for e in history] == ["build-green"]
    assert history[0]["status"] == "skipped"


# --- Lock contention ---------------------------------------------------------------------------


def _hold_lock(target):
    lock = (
        target / ".claude" / "state" / "pipeline-snapshot.json.lock"
    )  # fresh mtime → live holder
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("99999", encoding="utf-8")
    return lock


def test_skip_gate_reports_lock_contention(tmp_path, payload, monkeypatch):
    install(payload, tmp_path)
    _write_snapshot(tmp_path, **_coherent())
    monkeypatch.setattr(pipeline, "_LOCK_TIMEOUT_S", 0.15)
    _hold_lock(tmp_path)
    ok, msgs = pipeline.skip_gate(tmp_path, "build-green", "no build step")
    assert not ok
    assert any("could not lock" in m for m in msgs)


def test_abort_reports_lock_contention(tmp_path, payload, monkeypatch):
    install(payload, tmp_path)
    _write_snapshot(tmp_path, **_coherent())
    monkeypatch.setattr(pipeline, "_LOCK_TIMEOUT_S", 0.15)
    _hold_lock(tmp_path)
    ok, msgs = pipeline.abort(tmp_path)
    assert not ok
    assert any("could not lock" in m for m in msgs)
    assert _read_snap(tmp_path)["stage"] == "build"  # unchanged


def test_snapshot_lock_reclaims_a_stale_lock_without_a_message_sink(tmp_path):
    """The lock primitive self-heals even when no caller-supplied message list exists."""
    snap = tmp_path / "pipeline-snapshot.json"
    snap.write_text("{}", encoding="utf-8")
    lock = snap.with_name(snap.name + ".lock")
    lock.write_text("99999", encoding="utf-8")
    old = time.time() - (pipeline._LOCK_STALE_S + 60)
    os.utime(lock, (old, old))
    with pipeline._snapshot_lock(snap):
        assert lock.is_file()
    assert not lock.exists()


def test_snapshot_lock_retries_when_the_holder_releases_mid_check(
    tmp_path, monkeypatch
):
    """If the lockfile disappears between O_EXCL and the staleness stat, retry — don't error."""
    snap = tmp_path / "pipeline-snapshot.json"
    snap.write_text("{}", encoding="utf-8")
    lock = snap.with_name(snap.name + ".lock")
    lock.write_text("99999", encoding="utf-8")
    real_stat = Path.stat
    vanished = []

    def vanishing_stat(self, *args, **kwargs):
        if self == lock and not vanished:
            vanished.append(True)  # once: the holder released between O_EXCL and stat
            lock.unlink(missing_ok=True)
            raise OSError("lock vanished")
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", vanishing_stat)
    with pipeline._snapshot_lock(snap):
        pass
    assert vanished, "the race path was never exercised"
    assert not lock.exists()


def test_skip_gate_appends_to_an_existing_ledger(tmp_path, payload):
    """A skip after a real close must extend the ledger, not replace it."""
    install(payload, tmp_path)
    _write_snapshot(tmp_path, **_coherent())
    ev = tmp_path / "e.txt"
    ev.write_text("x", encoding="utf-8")
    assert pipeline.close_gate(tmp_path, "build-green", ev)[0]
    ok, msgs = pipeline.skip_gate(
        tmp_path, "contract-clear", "single-service change, no contract to verify"
    )
    assert ok, "\n".join(msgs)
    history = _read_snap(tmp_path)["gate_history"]
    assert [(e["gate"], e["status"]) for e in history] == [
        ("build-green", "passed"),
        ("contract-clear", "skipped"),
    ]
