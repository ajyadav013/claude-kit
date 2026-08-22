"""Characterization checks for the immutable pre-provider Claude installer."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any

import pytest

FROZEN_COMMIT = "04161917bd3c1aef270f9979e5abeabe3cd755e6"
FROZEN_TREE = "02945cbfdb7306a992d1da5fa83eb0b889e4ff75"
FIXTURES = Path(__file__).parent / "fixtures" / "frozen-claude-0.83" / "generated"
REPO_ROOT = Path(__file__).resolve().parents[1]
GENERATOR = REPO_ROOT / "scripts" / "regenerate_frozen_claude_fixtures.py"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
MODE = re.compile(r"^0[0-7]{3}$")


def _bytes_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _assert_machine_neutral_path(value: str) -> None:
    path = PurePosixPath(value)
    assert value == path.as_posix()
    assert not path.is_absolute()
    assert ".." not in path.parts
    assert "__pycache__" not in path.parts
    assert not value.endswith((".pyc", ".pyo", ".DS_Store"))


def _assert_no_absolute_strings(value: Any) -> None:
    if isinstance(value, dict):
        for nested in value.values():
            _assert_no_absolute_strings(nested)
    elif isinstance(value, list):
        for nested in value:
            _assert_no_absolute_strings(nested)
    elif isinstance(value, str):
        assert not value.startswith("/")
        assert not re.match(r"^[A-Za-z]:[/\\]", value)


def test_frozen_baseline_is_canonical_complete_and_machine_neutral() -> None:
    metadata_path = FIXTURES / "metadata.json"
    metadata = _load(metadata_path)
    assert metadata["fixture_schema_version"] == 1
    assert metadata["source"] == {
        "commit": FROZEN_COMMIT,
        "tree": FROZEN_TREE,
        "claude_kit_version": "0.83.0",
    }

    indexed = {entry["path"]: entry for entry in metadata["artifacts"]}
    actual = {
        path.relative_to(FIXTURES).as_posix(): path
        for path in FIXTURES.rglob("*")
        if path.is_file() and path != metadata_path
    }
    assert set(indexed) == set(actual)
    for relative, path in actual.items():
        _assert_machine_neutral_path(relative)
        assert indexed[relative]["sha256"] == _bytes_sha256(path)
        assert indexed[relative]["size"] == path.stat().st_size

    # Canonical JSON makes review diffs and repeated regeneration byte-stable.
    exact_baseline_json = (
        FIXTURES
        / "legacy-0.83"
        / "project"
        / ".claude"
        / "config"
        / "init-options.json"
    )
    for path in set(actual.values()) | {metadata_path}:
        if path.suffix == ".json" and path != exact_baseline_json:
            parsed = _load(path)
            canonical = (
                json.dumps(parsed, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
            )
            assert path.read_text(encoding="utf-8") == canonical

    cases = [_load(FIXTURES / case["path"]) for case in metadata["cases"]]
    assert {
        (case["selection"]["profile"], case["selection"]["scope"]) for case in cases
    } == {
        ("lean", "individual"),
        ("standard", "team"),
        ("enterprise", "organization"),
    }
    assert len(metadata["cases"]) == len(cases)
    for summary, case in zip(metadata["cases"], cases):
        assert case["source"] == metadata["source"]
        files = case["installed_files"]
        paths = [entry["path"] for entry in files]
        assert paths == sorted(paths)
        assert len(paths) == len(set(paths)) == summary["installed_file_count"]
        assert {
            "CLAUDE.md",
            "AGENTS.md",
            "README.claude-sdlc.md",
            ".claude/settings.json",
            ".claude/config/init-options.json",
            ".claude/config/stack-catalog.snapshot.yaml",
            ".claude/state/.gitkeep",
            ".claude/tmp/.gitkeep",
        } <= set(paths)
        for entry in files:
            _assert_machine_neutral_path(entry["path"])
            assert SHA256.fullmatch(entry["sha256"])
            assert MODE.fullmatch(entry["mode"])
            assert isinstance(entry["size"], int) and entry["size"] >= 0
            if entry["path"].startswith(".claude/hooks/") or entry["path"] == (
                ".claude/scripts/sdlc-loop.sh"
            ):
                assert entry["mode"] == "0755"

        agent_paths = {item["path"] for item in case["agent_frontmatter"]}
        skill_paths = {item["path"] for item in case["skill_metadata"]}
        assert len(agent_paths) == summary["agent_count"]
        assert len(skill_paths) == summary["skill_count"]
        assert agent_paths <= set(paths)
        assert skill_paths <= set(paths)
        for item in case["agent_frontmatter"] + case["skill_metadata"]:
            _assert_machine_neutral_path(item["path"])
            assert isinstance(item["metadata"], dict) and item["metadata"]
            assert SHA256.fullmatch(item["frontmatter_sha256"])
            assert SHA256.fullmatch(item["body_sha256"])

        policy = case["gate_policy"]
        assert policy["ordered_gates"] == [
            item["gate"] for item in policy["definitions"]
        ]
        assert len(policy["ordered_gates"]) == len(set(policy["ordered_gates"]))
        assert SHA256.fullmatch(policy["definition_digest"])
        assert case["resolved_plan"]["hooks"]
        assert isinstance(case["hook_settings"].get("hooks"), dict)
        init = case["init_options"]
        assert init["schema_version"] == 1
        assert init["claude_kit_version"] == "0.83.0"
        assert init["selection"] == case["selection"]
        assert init["record_count"] > 0
        assert SHA256.fullmatch(init["record_digest"])
        assert ".claude/config/init-options.json" in init["installed_but_unrecorded"]
        assert ".claude/state/.gitkeep" in init["installed_but_unrecorded"]
        _assert_no_absolute_strings(case)


def test_legacy_083_fixture_preserves_exact_init_and_portable_state() -> None:
    manifest = _load(FIXTURES / "legacy-0.83" / "manifest.json")
    project = FIXTURES / "legacy-0.83" / "project"
    assert manifest["source_commit"] == FROZEN_COMMIT
    assert manifest["claude_kit_version"] == "0.83.0"
    assert manifest["state_root"] == ".claude"
    assert manifest["pipeline_state_schema"] == 1
    for record in manifest["files"]:
        _assert_machine_neutral_path(record["path"])
        path = project / record["path"]
        assert path.is_file()
        assert record["sha256"] == _bytes_sha256(path)
        assert MODE.fullmatch(record["mode"])

    init_options = _load(project / ".claude" / "config" / "init-options.json")
    state = _load(project / ".claude" / "state" / "pipeline-snapshot.json")
    assert init_options["schema_version"] == 1
    assert init_options["claude_kit_version"] == "0.83.0"
    assert "runtime" not in init_options
    assert state["schema"] == 1
    assert "schema_version" not in state
    assert state["last_gate_passed"] is None
    assert state["gate_history"] == []
    _assert_no_absolute_strings(init_options)
    _assert_no_absolute_strings(state)

    standard_case = _load(FIXTURES / "cases" / "standard_team_react_fastapi.json")
    installed = {item["path"]: item for item in standard_case["installed_files"]}
    for relative in (
        ".claude/config/init-options.json",
        ".claude/config/stack-catalog.snapshot.yaml",
        ".claude/state/.gitkeep",
    ):
        assert installed[relative]["sha256"] == _bytes_sha256(project / relative)


def test_regenerator_refuses_unpinned_source() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(GENERATOR),
            "--source-commit",
            "HEAD",
            "--check",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0
    assert FROZEN_COMMIT in result.stderr


def test_regenerator_matches_frozen_commit_when_history_is_available() -> None:
    available = subprocess.run(
        ["git", "cat-file", "-e", f"{FROZEN_COMMIT}^{{commit}}"],
        cwd=REPO_ROOT,
        capture_output=True,
        timeout=10,
    )
    if available.returncode != 0:
        pytest.skip(
            "shallow checkout does not contain the reviewed frozen source commit"
        )
    subprocess.run(
        [
            sys.executable,
            str(GENERATOR),
            "--source-commit",
            FROZEN_COMMIT,
            "--check",
        ],
        cwd=REPO_ROOT,
        check=True,
        timeout=300,
    )
