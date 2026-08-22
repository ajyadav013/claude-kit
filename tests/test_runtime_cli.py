"""CLI contracts for explicit native runtime installation."""

from __future__ import annotations

import json
from copy import deepcopy

import pytest
from typer.testing import CliRunner

from claude_kit import catalog, pipeline, workflow_executor
from claude_kit.cli import app
from claude_kit.dispatch import (
    DispatchHandle,
    DispatchStatus,
    HumanStopReason,
    HumanStopRequest,
)
from claude_kit.models import StateLayout
from claude_kit.workflow_executor import (
    StageArtifactRef,
    StageExecution,
    WorkflowExecutionResult,
    WorkflowExecutionStatus,
)

runner = CliRunner()


@pytest.mark.parametrize("runtime", ["claude", "codex", "both"])
def test_init_explicit_runtime_uses_native_projection(tmp_path, runtime):
    target = tmp_path / runtime
    env = {"CKIT_EXPERIMENTAL": "1"} if runtime != "claude" else None
    result = runner.invoke(
        app,
        ["init", str(target), "--defaults", "--runtime", runtime],
        env=env,
    )

    assert result.exit_code == 0, result.output
    manifest = json.loads((target / StateLayout.neutral().manifest).read_text())
    expected = ["claude", "codex"] if runtime == "both" else [runtime]
    assert manifest["runtimes"] == expected
    assert (target / ".claude").is_dir() is (runtime in {"claude", "both"})
    assert (target / ".codex").is_dir() is (runtime in {"codex", "both"})
    assert (target / ".agents").is_dir() is (runtime in {"codex", "both"})
    validation = runner.invoke(app, ["validate", "--strict", str(target)])
    assert validation.exit_code == 0, validation.output


def test_codex_runtime_requires_preview_opt_in_before_target_mutation(tmp_path):
    target = tmp_path / "codex"
    result = runner.invoke(
        app,
        ["init", str(target), "--defaults", "--runtime", "codex"],
        env={"CKIT_EXPERIMENTAL": ""},
    )

    assert result.exit_code == 2
    assert "preview features" in result.output
    assert not target.exists()


def test_runtime_is_validated_before_target_mutation(tmp_path):
    target = tmp_path / "bad"
    result = runner.invoke(
        app,
        ["init", str(target), "--defaults", "--runtime", "other"],
    )

    assert result.exit_code == 2
    assert "runtime must be one of" in result.output
    assert not target.exists()


def test_native_runtime_dry_run_is_exact_and_non_mutating(tmp_path):
    target = tmp_path / "preview"
    result = runner.invoke(
        app,
        [
            "init",
            str(target),
            "--defaults",
            "--runtime",
            "both",
            "--dry-run",
            "--json",
        ],
        env={"CKIT_EXPERIMENTAL": "1"},
    )

    assert result.exit_code == 0, result.output
    document = json.loads(result.output)
    assert document["runtime"] == "both"
    assert ".claude/agents/orchestrator.md" in document["would_write"]
    assert ".codex/agents/orchestrator.toml" in document["would_write"]
    assert StateLayout.neutral().manifest in document["would_write"]
    assert not target.exists()


@pytest.mark.parametrize("dry_run", [False, True])
def test_init_reports_incompatible_mcp_runtime_without_mutation(
    tmp_path, monkeypatch, dry_run
):
    target = tmp_path / ("dry" if dry_run else "install")
    config = tmp_path / "selection.yaml"
    config.write_text("runtime: both\nmcp: [github]\n", encoding="utf-8")
    original_load = catalog._load

    def provider_limited(root, name):
        document = deepcopy(original_load(root, name))
        if name == "mcp.yaml":
            document["servers"]["github"]["runtime_support"] = ["claude"]
        return document

    monkeypatch.setattr(catalog, "_load", provider_limited)
    command = ["init", str(target), "--config", str(config)]
    if dry_run:
        command.append("--dry-run")

    result = runner.invoke(app, command, env={"CKIT_EXPERIMENTAL": "1"})

    assert result.exit_code == 1, result.output
    assert "github lacks codex" in result.output
    assert "Traceback" not in result.output
    assert not target.exists()


def test_config_runtime_is_an_install_concern_and_cli_flag_wins(tmp_path):
    config = tmp_path / "selection.yaml"
    config.write_text("runtime: codex\nprofile: lean\n")
    from_config = tmp_path / "from-config"
    configured = runner.invoke(
        app,
        ["init", str(from_config), "--config", str(config)],
        env={"CKIT_EXPERIMENTAL": "1"},
    )
    assert configured.exit_code == 0, configured.output
    assert json.loads((from_config / StateLayout.neutral().manifest).read_text())[
        "runtimes"
    ] == ["codex"]

    overridden = tmp_path / "overridden"
    explicit = runner.invoke(
        app,
        [
            "init",
            str(overridden),
            "--config",
            str(config),
            "--runtime",
            "claude",
        ],
    )
    assert explicit.exit_code == 0, explicit.output
    assert json.loads((overridden / StateLayout.neutral().manifest).read_text())[
        "runtimes"
    ] == ["claude"]


def test_legacy_runtime_transition_requires_and_preserves_explicit_state_migration(
    tmp_path,
):
    target = tmp_path / "legacy"
    legacy = runner.invoke(app, ["init", str(target), "--defaults"])
    assert legacy.exit_code == 0, legacy.output
    continuity = target / ".claude/CONTINUITY.md"
    continuity.write_text("# User continuity\n\nPreserve this exact state.\n")
    pipeline = target / ".claude/state/pipeline-snapshot.json"
    pipeline.write_text('{"status":"active","gate_history":[]}\n')

    refused = runner.invoke(
        app,
        ["init", str(target), "--defaults", "--runtime", "both"],
        env={"CKIT_EXPERIMENTAL": "1"},
    )
    assert refused.exit_code == 1
    assert "--migrate-state" in refused.output
    assert not (target / ".ckit").exists()

    transitioned = runner.invoke(
        app,
        [
            "init",
            str(target),
            "--defaults",
            "--runtime",
            "both",
            "--migrate-state",
        ],
        env={"CKIT_EXPERIMENTAL": "1"},
    )
    assert transitioned.exit_code == 0, transitioned.output
    assert (target / ".ckit/CONTINUITY.md").read_bytes() == continuity.read_bytes()
    assert (target / ".ckit/state/pipeline-snapshot.json").read_bytes() == (
        pipeline.read_bytes()
    )
    manifest = json.loads((target / StateLayout.neutral().manifest).read_text())
    assert manifest["runtimes"] == ["claude", "codex"]


def test_pipeline_run_reaches_structured_executor_and_emits_bounded_json(
    tmp_path, monkeypatch
):
    observed = {}
    monkeypatch.setattr(
        pipeline,
        "snapshot_document",
        lambda _path: (
            {"status": "active", "task": "Ship safely", "mode": "B"},
            None,
        ),
    )

    def fake_execute(project_root, **kwargs):
        observed["project_root"] = project_root
        observed.update(kwargs)
        return WorkflowExecutionResult(
            status=WorkflowExecutionStatus.WAITING_GATE,
            completed_stages=("classify",),
            skipped_stages=("fast-classify",),
            attempts=(),
            pending_gates=("spec-complete",),
            messages=("Gate evidence must be reviewed before continuing.",),
        )

    monkeypatch.setattr(workflow_executor, "execute_bound_workflow", fake_execute)
    result = runner.invoke(
        app,
        [
            "pipeline",
            "run",
            "--provider",
            "codex",
            "--condition",
            "contract-changing=true",
            "--condition",
            "external-side-effect=false",
            "--json",
            str(tmp_path),
        ],
        env={"CKIT_EXPERIMENTAL": "1"},
    )

    assert result.exit_code == 0, result.output
    document = json.loads(result.output)
    assert document == {
        "attempts": [],
        "completed_stages": ["classify"],
        "human_stop": None,
        "messages": ["Gate evidence must be reviewed before continuing."],
        "pending_gates": ["spec-complete"],
        "skipped_stages": ["fast-classify"],
        "status": "waiting-gate",
    }
    assert observed["project_root"] == tmp_path
    assert observed["provider"] == "codex"
    assert observed["objective"] == "Ship safely"
    assert observed["mode"] == "B"
    assert observed["conditions"] == {
        "contract-changing": True,
        "external-side-effect": False,
    }


def test_pipeline_run_human_stop_is_structured_and_nonzero(tmp_path, monkeypatch):
    monkeypatch.setattr(
        pipeline,
        "snapshot_document",
        lambda _path: (
            {"status": "active", "task": "Deploy", "mode": "A"},
            None,
        ),
    )
    monkeypatch.setattr(
        workflow_executor,
        "execute_bound_workflow",
        lambda *_args, **_kwargs: WorkflowExecutionResult(
            status=WorkflowExecutionStatus.HUMAN_STOP,
            completed_stages=(),
            skipped_stages=(),
            attempts=(),
            human_stop=HumanStopRequest(
                HumanStopReason.EXTERNAL_SIDE_EFFECT,
                "Deployment changes an external system",
                "Approve or reject deployment",
            ),
        ),
    )

    result = runner.invoke(
        app,
        ["pipeline", "run", "--provider", "claude", "--json", str(tmp_path)],
        env={"CKIT_EXPERIMENTAL": "1"},
    )

    assert result.exit_code == 3
    document = json.loads(result.output)
    assert document["status"] == "human-stop"
    assert document["human_stop"] == {
        "message": "Deployment changes an external system",
        "reason": "external-side-effect",
        "requested_action": "Approve or reject deployment",
    }


def test_pipeline_run_exposes_only_authenticated_artifact_metadata(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        pipeline,
        "snapshot_document",
        lambda _path: (
            {"status": "active", "task": "Review", "mode": "D"},
            None,
        ),
    )
    execution = StageExecution(
        stage="fast-review",
        role="sdlc-code-reviewer",
        handle=DispatchHandle(
            id="fast-review-1",
            route="review",
            provider="codex",
        ),
        status=DispatchStatus.SUCCEEDED,
        artifact=StageArtifactRef(
            path=".ckit/artifacts/dispatch/run/fast-review-1.json",
            sha256="a" * 64,
            truncated=False,
            category="host-result",
        ),
    )
    monkeypatch.setattr(
        workflow_executor,
        "execute_bound_workflow",
        lambda *_args, **_kwargs: WorkflowExecutionResult(
            status=WorkflowExecutionStatus.WAITING_GATE,
            completed_stages=("fast-review",),
            skipped_stages=(),
            attempts=(execution,),
            pending_gates=("code-review",),
        ),
    )

    json_result = runner.invoke(
        app,
        ["pipeline", "run", "--provider", "codex", "--json", str(tmp_path)],
        env={"CKIT_EXPERIMENTAL": "1"},
    )
    assert json_result.exit_code == 0, json_result.output
    attempt = json.loads(json_result.output)["attempts"][0]
    assert attempt["artifact"] == {
        "category": "host-result",
        "path": ".ckit/artifacts/dispatch/run/fast-review-1.json",
        "sha256": "a" * 64,
        "truncated": False,
    }
    assert "output" not in attempt
    assert "transcript" not in attempt

    text_result = runner.invoke(
        app,
        ["pipeline", "run", "--provider", "codex", str(tmp_path)],
        env={"CKIT_EXPERIMENTAL": "1"},
    )
    assert text_result.exit_code == 0, text_result.output
    assert (
        "artifact fast-review#1: .ckit/artifacts/dispatch/run/fast-review-1.json "
        f"sha256={'a' * 64} category=host-result truncated=false"
    ) in text_result.output


def test_pipeline_run_pending_human_stop_is_stable_exit_three_and_redacted(
    tmp_path, monkeypatch
):
    snapshot = {
        "status": "active",
        "task": "Deploy",
        "mode": "A",
        "stage": "build-green",
        "human_stops": [
            {
                "stop_id": "stop-123",
                "status": "pending",
                "reason": "external-side-effect",
                "message": "Approval needed; API_TOKEN=super-secret-value",
                "requested_action": "Review https://operator:password@example.test/change",
            }
        ],
    }
    monkeypatch.setattr(
        pipeline,
        "snapshot_document",
        lambda _path: (snapshot, None),
    )

    def must_not_execute(*_args, **_kwargs):
        raise AssertionError("pending human stop must short-circuit the executor")

    monkeypatch.setattr(workflow_executor, "execute_bound_workflow", must_not_execute)

    documents = []
    for _ in range(2):
        result = runner.invoke(
            app,
            ["pipeline", "run", "--provider", "claude", "--json", str(tmp_path)],
            env={"CKIT_EXPERIMENTAL": "1"},
        )
        assert result.exit_code == 3, result.output
        documents.append(json.loads(result.output))

    assert documents[0] == documents[1]
    document = documents[0]
    assert document["status"] == "human-stop"
    assert document["pending_gates"] == ["build-green"]
    assert document["attempts"] == []
    assert document["human_stop"] == {
        "stop_id": "stop-123",
        "reason": "external-side-effect",
        "message": "Approval needed; API_TOKEN=[REDACTED]",
        "requested_action": "Review https://operator:[REDACTED]@example.test/change",
    }


@pytest.mark.parametrize(
    "arguments, expected",
    [
        (["--provider", "both"], "Invalid value"),
        (
            ["--provider", "codex", "--condition", "ambiguous=maybe"],
            "expected NAME=true or NAME=false",
        ),
        (
            [
                "--provider",
                "codex",
                "--condition",
                "risk=true",
                "--condition",
                "risk=false",
            ],
            "provided more than once",
        ),
    ],
)
def test_pipeline_run_rejects_ambiguous_provider_or_conditions(
    tmp_path, monkeypatch, arguments, expected
):
    monkeypatch.setattr(
        pipeline,
        "snapshot_document",
        lambda _path: (
            {"status": "active", "task": "Test", "mode": "B"},
            None,
        ),
    )
    result = runner.invoke(
        app,
        ["pipeline", "run", *arguments, str(tmp_path)],
        env={"CKIT_EXPERIMENTAL": "1"},
    )

    assert result.exit_code == 2
    assert expected in result.output


def test_pipeline_run_requires_preview_opt_in(tmp_path):
    result = runner.invoke(
        app,
        ["pipeline", "run", "--provider", "claude", str(tmp_path)],
        env={"CKIT_EXPERIMENTAL": ""},
    )

    assert result.exit_code == 2
    assert "structured workflow execution is Preview" in result.output
