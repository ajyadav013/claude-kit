"""pipeline: validate/status/close-gate/abort operate on the snapshot state files, no SDLC run."""

from __future__ import annotations

import json

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
# Standard-profile order: spec-complete, em-approved, code-review, build-green, test-coverage,
# security-clear, contract-clear. _coherent() anchors at code-review → next is build-green.


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
    # the skip advanced the position: test-coverage is now the legal next gate
    evidence = tmp_path / "e.txt"
    evidence.write_text("x", encoding="utf-8")
    ok, msgs = pipeline.close_gate(tmp_path, "test-coverage", evidence)
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
