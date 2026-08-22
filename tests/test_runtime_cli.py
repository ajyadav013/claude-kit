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


def _tree_snapshot(root):
    """Return an exact-enough byte/type inventory for lifecycle rollback tests."""

    return {
        path.relative_to(root).as_posix(): (
            "directory" if path.is_dir() else "file",
            b"" if path.is_dir() else path.read_bytes(),
        )
        for path in sorted(root.rglob("*"))
    }


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


@pytest.mark.parametrize("force", [False, True])
def test_native_runtime_dry_run_reports_existing_tree_destinations(tmp_path, force):
    target = tmp_path / ("force" if force else "merge")
    target.mkdir()
    readme = target / "README.claude-sdlc.md"
    readme.write_text("user-owned readme\n", encoding="utf-8")
    mcp = target / ".mcp.json"
    mcp.write_text('{"mcpServers":{"mine":{"command":"echo"}}}\n', encoding="utf-8")
    config = tmp_path / f"{target.name}.yaml"
    config.write_text("runtime: claude\nmcp: [github]\n", encoding="utf-8")
    command = [
        "init",
        str(target),
        "--config",
        str(config),
        "--dry-run",
        "--json",
    ]
    if force:
        command.append("--force")

    result = runner.invoke(app, command)

    assert result.exit_code == 0, result.output
    document = json.loads(result.output)
    expected_readme = (
        "README.claude-sdlc.md" if force else "README.claude-sdlc.md.claude-kit"
    )
    assert expected_readme in document["would_write"]
    assert ".mcp.json" in document["would_write"]
    assert ".mcp.json.claude-kit" not in document["would_write"]
    assert readme.read_text(encoding="utf-8") == "user-owned readme\n"
    assert json.loads(mcp.read_text(encoding="utf-8")) == {
        "mcpServers": {"mine": {"command": "echo"}}
    }
    assert not (target / "README.claude-sdlc.md.claude-kit").exists()


def test_native_runtime_dry_run_rejects_ambiguous_claude_mcp_without_mutation(
    tmp_path,
):
    target = tmp_path / "duplicate"
    target.mkdir()
    original = '{"mcpServers":{"github":{"command":"user-owned"}}}\n'
    mcp = target / ".mcp.json"
    mcp.write_text(original, encoding="utf-8")
    config = tmp_path / "duplicate.yaml"
    config.write_text("runtime: claude\nmcp: [github]\n", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "init",
            str(target),
            "--config",
            str(config),
            "--dry-run",
            "--json",
        ],
    )

    assert result.exit_code == 1, result.output
    assert "duplicate MCP definitions" in result.output
    assert mcp.read_text(encoding="utf-8") == original
    assert not (target / ".ckit").exists()


def test_native_runtime_dry_run_includes_legacy_state_migration_and_requires_flag(
    tmp_path,
):
    target = tmp_path / "legacy-preview"
    legacy = runner.invoke(app, ["init", str(target), "--defaults"])
    assert legacy.exit_code == 0, legacy.output
    ticket = target / ".claude/state/user-ticket.json"
    ticket.parent.mkdir(parents=True, exist_ok=True)
    ticket.write_text('{"owner":"user"}\n', encoding="utf-8")
    before = _tree_snapshot(target)

    preview = runner.invoke(
        app,
        [
            "init",
            str(target),
            "--defaults",
            "--runtime",
            "both",
            "--migrate-state",
            "--dry-run",
            "--json",
        ],
        env={"CKIT_EXPERIMENTAL": "1"},
    )

    assert preview.exit_code == 0, preview.output
    assert ".ckit/state/user-ticket.json" in json.loads(preview.output)["would_write"]
    assert _tree_snapshot(target) == before

    refused = runner.invoke(
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
    assert refused.exit_code == 1, refused.output
    assert "--migrate-state" in refused.output
    assert _tree_snapshot(target) == before


def test_native_runtime_dry_run_reports_legacy_migration_conflict_cleanly(tmp_path):
    target = tmp_path / "legacy-conflict"
    legacy = runner.invoke(app, ["init", str(target), "--defaults"])
    assert legacy.exit_code == 0, legacy.output
    legacy_ticket = target / ".claude/state/user-ticket.json"
    legacy_ticket.parent.mkdir(parents=True, exist_ok=True)
    legacy_ticket.write_text('{"source":"legacy"}\n')
    neutral_ticket = target / ".ckit/state/user-ticket.json"
    neutral_ticket.parent.mkdir(parents=True)
    neutral_ticket.write_text('{"source":"neutral"}\n')
    before = _tree_snapshot(target)

    result = runner.invoke(
        app,
        [
            "init",
            str(target),
            "--defaults",
            "--runtime",
            "claude",
            "--migrate-state",
            "--dry-run",
        ],
    )

    assert result.exit_code == 1, result.output
    assert "legacy state migration conflicts" in result.output
    assert _tree_snapshot(target) == before


def test_native_runtime_dry_run_previews_explicit_untracked_legacy_state_migration(
    tmp_path,
):
    target = tmp_path / "untracked-legacy-state"
    ticket = target / ".claude/state/user-ticket.json"
    ticket.parent.mkdir(parents=True)
    ticket.write_text('{"owner":"user"}\n')
    before = _tree_snapshot(target)

    result = runner.invoke(
        app,
        [
            "init",
            str(target),
            "--defaults",
            "--runtime",
            "claude",
            "--migrate-state",
            "--dry-run",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert ".ckit/state/user-ticket.json" in json.loads(result.output)["would_write"]
    assert _tree_snapshot(target) == before


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


def test_init_migration_and_runtime_install_roll_back_as_one_operation(tmp_path):
    target = tmp_path / "legacy-with-user-codex"
    config = tmp_path / "selection.yaml"
    config.write_text("mcp: [github]\n", encoding="utf-8")
    legacy = runner.invoke(app, ["init", str(target), "--config", str(config)])
    assert legacy.exit_code == 0, legacy.output

    continuity = target / ".claude/CONTINUITY.md"
    continuity.write_text("# In-flight legacy work\n\nDo not lose these bytes.\n")
    codex_config = target / ".codex/config.toml"
    codex_config.parent.mkdir()
    codex_config.write_text(
        '[mcp_servers.github]\ncommand = "user-owned"\n', encoding="utf-8"
    )
    before = _tree_snapshot(target)

    result = runner.invoke(
        app,
        [
            "init",
            str(target),
            "--config",
            str(config),
            "--runtime",
            "both",
            "--migrate-state",
        ],
        env={"CKIT_EXPERIMENTAL": "1"},
    )

    assert result.exit_code == 1, result.output
    assert "duplicate MCP definitions" in result.output
    assert "legacy mutable state migrated" not in result.output
    assert not (target / ".ckit").exists()
    assert _tree_snapshot(target) == before


def test_init_does_not_migrate_state_when_runtime_projection_is_incompatible(
    tmp_path, monkeypatch
):
    target = tmp_path / "legacy-incompatible-projection"
    legacy = runner.invoke(app, ["init", str(target), "--defaults"])
    assert legacy.exit_code == 0, legacy.output
    continuity = target / ".claude/CONTINUITY.md"
    continuity.write_text("# Legacy state before projection validation\n")
    before = _tree_snapshot(target)

    config = tmp_path / "selection.yaml"
    config.write_text("mcp: [github]\n", encoding="utf-8")
    original_load = catalog._load

    def provider_limited(root, name):
        document = deepcopy(original_load(root, name))
        if name == "mcp.yaml":
            document["servers"]["github"]["runtime_support"] = ["claude"]
        return document

    monkeypatch.setattr(catalog, "_load", provider_limited)
    result = runner.invoke(
        app,
        [
            "init",
            str(target),
            "--config",
            str(config),
            "--runtime",
            "both",
            "--migrate-state",
        ],
        env={"CKIT_EXPERIMENTAL": "1"},
    )

    assert result.exit_code == 1, result.output
    assert "github lacks codex" in result.output
    assert "legacy mutable state migrated" not in result.output
    assert not (target / ".ckit").exists()
    assert _tree_snapshot(target) == before


class _SimulatedMigrationProcessDeath(BaseException):
    pass


def test_interrupted_migrate_install_retry_recovers_before_routing(
    payload, tmp_path, monkeypatch
):
    from claude_kit import runtime_scaffold
    from claude_kit.models import InstallRequest

    target = tmp_path / "interrupted-migration"
    legacy = runner.invoke(app, ["init", str(target), "--defaults"])
    assert legacy.exit_code == 0, legacy.output
    continuity = target / StateLayout.legacy_claude().continuity
    expected = "# Irreplaceable legacy continuity\n\nKEEP-ME\n"
    continuity.write_text(expected, encoding="utf-8")
    selection = catalog.defaults(payload)
    plan = catalog.resolve(payload, selection)

    original_apply = runtime_scaffold._apply_runtime_files

    def die_after_migration(*_args, **_kwargs):
        raise _SimulatedMigrationProcessDeath()

    monkeypatch.setattr(runtime_scaffold, "_apply_runtime_files", die_after_migration)
    with pytest.raises(_SimulatedMigrationProcessDeath):
        runtime_scaffold.install_runtime_with_state_migration(
            payload,
            target,
            plan,
            InstallRequest(selection=selection, runtime="both"),
        )
    monkeypatch.setattr(runtime_scaffold, "_apply_runtime_files", original_apply)

    assert (target / StateLayout.neutral().manifest).is_file()
    assert (target / StateLayout.neutral().journal).is_file()
    assert (target / StateLayout.neutral().continuity).read_text() == expected

    preview = runner.invoke(
        app,
        [
            "init",
            str(target),
            "--defaults",
            "--runtime",
            "both",
            "--migrate-state",
            "--dry-run",
        ],
        env={"CKIT_EXPERIMENTAL": "1"},
    )
    assert preview.exit_code == 1, preview.output
    assert "interrupted lifecycle transaction" in preview.output
    assert (target / StateLayout.neutral().journal).is_file()

    refused = runner.invoke(
        app,
        ["init", str(target), "--defaults", "--runtime", "both"],
        env={"CKIT_EXPERIMENTAL": "1"},
    )
    assert refused.exit_code == 1, refused.output
    assert "--migrate-state" in refused.output
    assert not (target / StateLayout.neutral().root).exists()
    assert continuity.read_text() == expected

    retry = runner.invoke(
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
    assert retry.exit_code == 0, retry.output
    assert (target / StateLayout.neutral().continuity).read_text() == expected
    assert not (target / StateLayout.neutral().journal).exists()


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
