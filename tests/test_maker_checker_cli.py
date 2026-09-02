"""CLI coverage for project-scoped maker/reviewer configuration and readiness."""

from __future__ import annotations

import json
import subprocess

import pytest
from typer.testing import CliRunner

from claude_kit import cli
from claude_kit.cli import app
from claude_kit.execution_config import load_execution_policy
from claude_kit.models import (
    ExecutionPolicy,
    InitOptions,
    ModelChoice,
    Runtime,
    StateLayout,
    WorkerBinding,
)
from tests._helpers import make_selection

runner = CliRunner()


def _policy() -> ExecutionPolicy:
    return ExecutionPolicy(
        maker=WorkerBinding("claude", ModelChoice("tier", "deep")),
        reviewer=WorkerBinding("codex", ModelChoice("exact", "gpt-reviewer")),
        max_revisions=1,
    )


def _write_manifest(target, payload, *, policy=None, runtimes=None) -> None:
    providers = runtimes or ["claude", "codex"]
    options = InitOptions(
        claude_kit_version="0.0.0-test",
        selection=make_selection(payload),
        files=[],
        runtimes=providers,
        state_layout=StateLayout.neutral(),
        compatibility_catalog_versions={provider: 1 for provider in providers},
        execution_policy=policy,
    )
    manifest = target / StateLayout.neutral().manifest
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(options.to_dict(), indent=2) + "\n", encoding="utf-8"
    )


def test_maker_checker_configure_persists_complete_noninteractive_pair(
    tmp_path, payload
):
    _write_manifest(tmp_path, payload)

    result = runner.invoke(
        app,
        [
            "maker-checker",
            "configure",
            str(tmp_path),
            "--maker-provider",
            "claude",
            "--maker-model-tier",
            "deep",
            "--reviewer-provider",
            "codex",
            "--reviewer-model-id",
            "gpt-reviewer",
            "--max-revisions",
            "1",
        ],
    )

    assert result.exit_code == 0, result.output
    assert load_execution_policy(tmp_path) == _policy()
    assert "configured" in result.output.lower()


@pytest.mark.parametrize(
    "extra, message",
    [
        (
            ["--maker-model-tier", "fast"],
            "exactly one of --maker-model-tier, --maker-model-id, or --maker-inherit",
        ),
        (
            [],
            "reviewer requires exactly one of --reviewer-model-tier, "
            "--reviewer-model-id, or --reviewer-inherit",
        ),
    ],
)
def test_maker_checker_configure_rejects_ambiguous_or_incomplete_flags(
    tmp_path, payload, extra, message, monkeypatch
):
    _write_manifest(tmp_path, payload)
    prompted = False

    def unexpected_prompt(_runtime):
        nonlocal prompted
        prompted = True
        return _policy()

    monkeypatch.setattr(cli.prompts, "interactive_execution", unexpected_prompt)
    args = [
        "maker-checker",
        "configure",
        str(tmp_path),
        "--maker-provider",
        "claude",
        "--maker-inherit",
        "--reviewer-provider",
        "codex",
    ]

    result = runner.invoke(app, [*args, *extra])

    assert result.exit_code == 2
    assert message in result.output
    assert load_execution_policy(tmp_path) is None
    assert prompted is False


def test_maker_checker_configure_requires_each_concrete_provider(tmp_path, payload):
    _write_manifest(tmp_path, payload)

    result = runner.invoke(
        app,
        [
            "maker-checker",
            "configure",
            str(tmp_path),
            "--maker-provider",
            "claude",
            "--maker-inherit",
            "--reviewer-model-id",
            "gpt-reviewer",
        ],
    )

    assert result.exit_code == 2
    assert "reviewer requires --reviewer-provider" in result.output
    assert load_execution_policy(tmp_path) is None


def test_maker_checker_configure_without_role_flags_is_interactive(
    tmp_path, payload, monkeypatch
):
    _write_manifest(tmp_path, payload)
    seen = []

    def configured(runtime):
        seen.append(runtime)
        return _policy()

    monkeypatch.setattr(cli.prompts, "interactive_execution", configured)

    result = runner.invoke(app, ["maker-checker", "configure", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert seen == [Runtime.BOTH]
    assert load_execution_policy(tmp_path) == _policy()


def test_maker_checker_show_and_disable_are_clear_and_disable_is_idempotent(
    tmp_path, payload
):
    _write_manifest(tmp_path, payload, policy=_policy())

    shown = runner.invoke(app, ["maker-checker", "show", str(tmp_path)])

    assert shown.exit_code == 0, shown.output
    assert "maker: claude / tier:deep" in shown.output.lower()
    assert "reviewer: codex / exact:gpt-reviewer" in shown.output.lower()
    assert "maximum revisions: 1" in shown.output.lower()

    disabled = runner.invoke(app, ["maker-checker", "disable", str(tmp_path)])
    again = runner.invoke(app, ["maker-checker", "disable", str(tmp_path)])

    assert disabled.exit_code == 0, disabled.output
    assert "disabled" in disabled.output.lower()
    assert again.exit_code == 0, again.output
    assert "already disabled" in again.output.lower()
    assert load_execution_policy(tmp_path) is None


def test_maker_checker_probe_is_read_only_and_never_makes_an_inference_call(
    tmp_path, payload, monkeypatch
):
    _write_manifest(tmp_path, payload, policy=_policy())
    executables = {"claude": "/tools/claude", "codex": "/tools/codex"}
    versions = {
        "/tools/claude": "2.1.239 (Claude Code)\n",
        "/tools/codex": "codex-cli 0.149.0\n",
    }
    calls = []

    monkeypatch.setattr(cli.shutil, "which", executables.get)

    def run(command, **kwargs):
        calls.append((tuple(command), kwargs))
        return subprocess.CompletedProcess(
            command, 0, stdout=versions[command[0]], stderr=""
        )

    monkeypatch.setattr(cli.subprocess, "run", run)

    result = runner.invoke(app, ["maker-checker", "probe", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert [call[0] for call in calls] == [
        ("/tools/claude", "--version"),
        ("/tools/codex", "--version"),
    ]
    assert all(call[1]["stdin"] is subprocess.DEVNULL for call in calls)
    assert "no inference call was made" in result.output.lower()
    assert "model access was not probed" in result.output.lower()


def test_maker_checker_probe_fails_when_a_configured_provider_is_missing(
    tmp_path, payload, monkeypatch
):
    _write_manifest(tmp_path, payload, policy=_policy())
    calls = []
    monkeypatch.setattr(
        cli.shutil,
        "which",
        lambda provider: "/tools/claude" if provider == "claude" else None,
    )

    def run(command, **kwargs):
        calls.append(tuple(command))
        return subprocess.CompletedProcess(command, 0, stdout="2.1.239\n", stderr="")

    monkeypatch.setattr(cli.subprocess, "run", run)

    result = runner.invoke(app, ["maker-checker", "probe", str(tmp_path)])

    assert result.exit_code == 1
    assert "codex executable not found" in result.output.lower()
    assert calls == [("/tools/claude", "--version")]


def test_runtime_init_config_policy_is_resolved_once_persisted_and_previewed(
    tmp_path, monkeypatch
):
    policy = _policy()
    config = tmp_path / "init.yaml"
    config.write_text(
        """\
runtime: both
execution:
  strategy: maker-reviewer
  maker:
    provider: claude
    model: {kind: tier, value: deep}
  reviewer:
    provider: codex
    model: {kind: exact, value: gpt-reviewer}
  max_revisions: 1
""",
        encoding="utf-8",
    )
    calls = []
    original = cli.prompts.execution_from_config

    def counted(path, runtime):
        calls.append((path, runtime))
        return original(path, runtime)

    monkeypatch.setattr(cli.prompts, "execution_from_config", counted)
    preview_target = tmp_path / "preview"

    preview = runner.invoke(
        app,
        [
            "init",
            str(preview_target),
            "--config",
            str(config),
            "--dry-run",
            "--json",
        ],
        env={"CKIT_EXPERIMENTAL": "1"},
    )

    assert preview.exit_code == 0, preview.output
    assert json.loads(preview.output)["execution"] == policy.to_dict()
    assert calls == [(str(config), Runtime.BOTH)]

    calls.clear()
    installed_target = tmp_path / "installed"
    installed = runner.invoke(
        app,
        ["init", str(installed_target), "--config", str(config)],
        env={"CKIT_EXPERIMENTAL": "1"},
    )

    assert installed.exit_code == 0, installed.output
    assert load_execution_policy(installed_target) == policy
    assert calls == [(str(config), Runtime.BOTH)]


def test_runtime_init_defaults_disable_policy_without_prompting(tmp_path, monkeypatch):
    def unexpected_prompt(_runtime):
        raise AssertionError("--defaults must not prompt for execution configuration")

    monkeypatch.setattr(cli.prompts, "interactive_execution", unexpected_prompt)

    result = runner.invoke(
        app,
        [
            "init",
            str(tmp_path / "preview"),
            "--runtime",
            "claude",
            "--defaults",
            "--dry-run",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["execution"] is None


def test_runtime_init_interactive_policy_is_resolved_once(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        cli.prompts, "interactive", lambda source: cli.catalog.defaults(source)
    )

    def configured(runtime):
        calls.append(runtime)
        return _policy()

    monkeypatch.setattr(cli.prompts, "interactive_execution", configured)

    result = runner.invoke(
        app,
        [
            "init",
            str(tmp_path / "preview"),
            "--runtime",
            "both",
            "--dry-run",
            "--json",
        ],
        env={"CKIT_EXPERIMENTAL": "1"},
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["execution"] == _policy().to_dict()
    assert calls == [Runtime.BOTH]
