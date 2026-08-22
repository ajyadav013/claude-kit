"""Fail-closed tests for the trusted Codex learning-capture boundary."""

from __future__ import annotations

import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from typer.testing import CliRunner

from claude_kit.cli import app
from claude_kit.learning_capture import (
    MAX_MODEL_OUTPUT_BYTES,
    LearningCaptureError,
    LearningCaptureResult,
    build_changed_context,
    parse_model_output,
    record_model_output,
    run_codex_learning_capture,
)
from claude_kit.models import StateLayout
from claude_kit.secure_fs import UnsafePathError


def _model_output(**overrides: str) -> str:
    document = {
        "status": "learning",
        "title": "Keep cache keys versioned",
        "category": "architecture",
        "trigger": "Changing a serialized cache payload.",
        "context": "Cache readers and writers share one persisted representation.",
        "learning": "Version the key whenever the serialized representation changes.",
        "evidence": "A reader failed after a writer changed the stored shape.",
        "apply_when": "Editing cache serialization or deserialization.",
    }
    document.update(overrides)
    return json.dumps(document)


def _none_output() -> str:
    return json.dumps(
        {
            "status": "none",
            "title": "",
            "category": "none",
            "trigger": "",
            "context": "",
            "learning": "",
            "evidence": "",
            "apply_when": "",
        }
    )


def _memory_index() -> str:
    return """# Agent Memory

### UX / Design

### Architecture Decisions

### Debugging Insights

### Project Patterns

### API & Integration

### Performance

### Gotchas & Pitfalls

_No learnings recorded yet. They accumulate here automatically as you work._
"""


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(("git", "init", "-q"), cwd=project, check=True)
    memory = project / ".ckit" / "agent-memory"
    memory.mkdir(parents=True)
    (memory / "MEMORY.md").write_text(_memory_index(), encoding="utf-8")
    manifest = project / StateLayout.neutral().manifest
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "runtimes": ["codex"],
                "state_layout": StateLayout.neutral().to_dict(),
            }
        ),
        encoding="utf-8",
    )
    source = project / "src" / "service.py"
    source.parent.mkdir()
    source.write_text("CACHE_VERSION = 1\n", encoding="utf-8")
    subprocess.run(("git", "add", "."), cwd=project, check=True)
    subprocess.run(
        (
            "git",
            "-c",
            "user.name=ckit tests",
            "-c",
            "user.email=ckit@example.invalid",
            "commit",
            "-qm",
            "baseline",
        ),
        cwd=project,
        check=True,
    )
    source.write_text("CACHE_VERSION = 2\n", encoding="utf-8")
    return project


def _memory_files(project: Path) -> list[Path]:
    return sorted(
        path
        for path in (project / ".ckit" / "agent-memory").rglob("*.md")
        if path.name != "MEMORY.md"
    )


def test_positive_capture_derives_one_contained_slug_and_updates_index(tmp_path):
    project = _project(tmp_path)

    result = record_model_output(project, _model_output())

    assert result.status == "recorded"
    assert result.relative_path is not None
    assert result.relative_path.startswith(".ckit/agent-memory/architecture/")
    assert ".." not in result.relative_path
    records = _memory_files(project)
    assert len(records) == 1
    assert records[0].name.startswith("keep-cache-keys-versioned-")
    assert "## Learning\nVersion the key" in records[0].read_text(encoding="utf-8")
    index = (project / ".ckit/agent-memory/MEMORY.md").read_text(encoding="utf-8")
    assert "[Keep cache keys versioned](architecture/" in index
    assert (
        index.index("### Architecture Decisions")
        < index.index("[Keep cache keys versioned]")
        < index.index("### Debugging Insights")
    )


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        '{"status":"none","status":"learning"}',
        _model_output(category="../../outside"),
        json.dumps({**json.loads(_model_output()), "path": "../../outside.md"}),
        b"x" * (MAX_MODEL_OUTPUT_BYTES + 1),
    ],
)
def test_malformed_oversized_and_path_directing_output_is_rejected(tmp_path, raw):
    project = _project(tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text("unchanged\n", encoding="utf-8")

    with pytest.raises(LearningCaptureError):
        record_model_output(project, raw)

    assert outside.read_text(encoding="utf-8") == "unchanged\n"
    assert _memory_files(project) == []


@pytest.mark.parametrize("linked_leaf", ["MEMORY.md", "architecture"])
def test_symlinked_memory_surfaces_fail_closed_without_outside_write(
    tmp_path, linked_leaf
):
    project = _project(tmp_path)
    memory = project / ".ckit" / "agent-memory"
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel.md"
    sentinel.write_text("unchanged\n", encoding="utf-8")
    link = memory / linked_leaf
    if link.exists():
        link.unlink()
    link.symlink_to(outside, target_is_directory=True)

    with pytest.raises((LearningCaptureError, UnsafePathError)):
        record_model_output(project, _model_output())

    assert sentinel.read_text(encoding="utf-8") == "unchanged\n"
    assert list(outside.iterdir()) == [sentinel]


def test_concurrent_captures_do_not_lose_index_entries_and_replay_is_idempotent(
    tmp_path,
):
    project = _project(tmp_path)
    first = _model_output()
    second = _model_output(
        title="Keep cache readers backward compatible",
        trigger="Changing a cache reader.",
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(lambda raw: record_model_output(project, raw), (first, second))
        )

    replay = record_model_output(project, first)
    assert len(_memory_files(project)) == 2
    assert replay.relative_path == results[0].relative_path
    index = (project / ".ckit/agent-memory/MEMORY.md").read_text(encoding="utf-8")
    assert index.count("[Keep cache keys versioned]") == 1
    assert index.count("[Keep cache readers backward compatible]") == 1


def test_no_learning_is_a_harmless_noop(tmp_path):
    project = _project(tmp_path)
    before = (project / ".ckit/agent-memory/MEMORY.md").read_bytes()

    result = record_model_output(project, _none_output())

    assert result == LearningCaptureResult("none")
    assert (project / ".ckit/agent-memory/MEMORY.md").read_bytes() == before
    assert _memory_files(project) == []


def test_changed_context_filters_secret_paths_redacts_values_and_is_bounded(tmp_path):
    project = _project(tmp_path)
    secret = "sk_live_" + "A" * 24
    (project / "src/service.py").write_text(
        f'CACHE_VERSION = 2\nAPI_KEY = "{secret}"\n', encoding="utf-8"
    )
    (project / ".env").write_text(f"API_KEY={secret}\n", encoding="utf-8")

    rendered = build_changed_context(project, max_files=10, max_bytes=1_024)

    assert rendered is not None
    assert len(rendered.encode("utf-8")) <= 1_024
    document = json.loads(rendered)
    assert [item["path"] for item in document["files"]] == ["src/service.py"]
    assert secret not in rendered
    assert "[REDACTED]" in rendered
    assert document["withheld_path_count"] >= 1
    assert document["redaction_count"] >= 1


def test_codex_runner_has_fixed_read_only_tool_free_argv_and_no_project_access(
    tmp_path,
):
    project = _project(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("unchanged\n", encoding="utf-8")
    observed: dict[str, object] = {}

    def fake_runner(argv, **kwargs):
        observed["argv"] = tuple(argv)
        observed["kwargs"] = kwargs
        output_path = Path(argv[argv.index("--output-last-message") + 1])
        schema_path = Path(argv[argv.index("--output-schema") + 1])
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        assert schema["additionalProperties"] is False
        output_path.write_text(_model_output(), encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0)

    result = run_codex_learning_capture(
        project,
        process_runner=fake_runner,
        lockdown_probe=lambda *_args: True,
    )

    argv = observed["argv"]
    kwargs = observed["kwargs"]
    assert isinstance(argv, tuple)
    assert argv[:2] == ("codex", "exec")
    assert "--ignore-user-config" in argv
    assert "--ignore-rules" in argv
    assert "--strict-config" in argv
    assert argv[argv.index("--sandbox") + 1] == "read-only"
    assert "workspace-write" not in argv
    disabled = {
        argv[index + 1] for index, value in enumerate(argv[:-1]) if value == "--disable"
    }
    assert {
        "browser_use",
        "hooks",
        "multi_agent",
        "plugins",
        "shell_tool",
        "unified_exec",
        "tool_suggest",
        "workspace_dependencies",
    } <= disabled
    assert "mcp_servers={}" in argv
    assert 'web_search="disabled"' in argv
    assert "tools.web_search=false" in argv
    assert str(project.resolve()) not in "\n".join(argv)
    assert Path(kwargs["cwd"]).resolve() != project.resolve()
    assert str(project.resolve()) not in kwargs["input"]
    assert kwargs["start_new_session"] is True
    assert outside.read_text(encoding="utf-8") == "unchanged\n"
    assert result.status == "recorded"
    assert len(_memory_files(project)) == 1


def test_noncanonical_or_non_codex_state_is_refused(tmp_path):
    project = _project(tmp_path)
    manifest = project / StateLayout.neutral().manifest
    document = json.loads(manifest.read_text(encoding="utf-8"))
    document["runtimes"] = ["claude"]
    manifest.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(LearningCaptureError, match="canonical Codex state"):
        record_model_output(project, _model_output())
    with pytest.raises(LearningCaptureError, match="canonical Codex state"):
        record_model_output(project, _none_output())

    assert _memory_files(project) == []


def test_capture_executable_is_not_model_or_configurable_input(tmp_path):
    project = _project(tmp_path)

    with pytest.raises(LearningCaptureError, match="fixed to 'codex'"):
        run_codex_learning_capture(project, executable="../../bin/sh")


def test_capture_refuses_an_unattested_codex_host_before_model_spawn(tmp_path):
    project = _project(tmp_path)
    spawned = False

    def forbidden_runner(*_args, **_kwargs):
        nonlocal spawned
        spawned = True
        raise AssertionError("classifier must not start")

    with pytest.raises(LearningCaptureError, match="verified tool lockdown"):
        run_codex_learning_capture(
            project,
            process_runner=forbidden_runner,
            lockdown_probe=lambda *_args: False,
        )

    assert spawned is False
    assert _memory_files(project) == []


def test_hidden_cli_delegates_only_bounded_options(monkeypatch, tmp_path):
    calls: list[tuple[object, ...]] = []

    def fake_capture(path, *, model, max_files, max_bytes):
        calls.append((path, model, max_files, max_bytes))
        return LearningCaptureResult("no-changes")

    monkeypatch.setattr("claude_kit.cli.run_codex_learning_capture", fake_capture)
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "learning-capture",
            "--path",
            str(tmp_path),
            "--model",
            "capture-model",
            "--max-files",
            "7",
            "--max-bytes",
            "2048",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls == [(str(tmp_path), "capture-model", 7, 2048)]
    assert result.output == "No learning captured.\n"
    assert "learning-capture" not in runner.invoke(app, ["--help"]).output


def test_hidden_cli_reports_trusted_boundary_failures(monkeypatch, tmp_path):
    def refuse(*_args, **_kwargs):
        raise LearningCaptureError("unsafe output")

    monkeypatch.setattr("claude_kit.cli.run_codex_learning_capture", refuse)
    result = CliRunner().invoke(app, ["learning-capture", "--path", str(tmp_path)])

    assert result.exit_code == 2
    assert "learning capture error: unsafe output" in result.output


def test_parse_model_output_rejects_secret_shaped_memory_content():
    with pytest.raises(LearningCaptureError, match="secret-shaped"):
        parse_model_output(_model_output(learning="Use token=ghp_" + "A" * 36))
