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


def test_close_gate_warns_when_install_snapshot_missing(tmp_path):
    # No install() → no .claude/config/stack-catalog.snapshot.yaml to confirm the gate against.
    (tmp_path / ".claude" / "state").mkdir(parents=True, exist_ok=True)
    evidence = tmp_path / "e.txt"
    evidence.write_text("x", encoding="utf-8")
    ok, msgs = pipeline.close_gate(tmp_path, "some-gate", evidence)
    assert ok  # a warning, not a failure
    assert any("cannot confirm the gate name" in m for m in msgs)
