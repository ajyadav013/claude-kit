"""Transactional project-scoped maker/reviewer configuration."""

from __future__ import annotations

import json

import pytest

from claude_kit.execution_config import (
    ExecutionConfigError,
    configure_execution_policy,
    disable_execution_policy,
    load_execution_policy,
)
from claude_kit.models import (
    ExecutionPolicy,
    InitOptions,
    ModelChoice,
    StateLayout,
    WorkerBinding,
)
from tests._helpers import make_selection


def _policy() -> ExecutionPolicy:
    return ExecutionPolicy(
        maker=WorkerBinding("claude", ModelChoice("tier", "deep")),
        reviewer=WorkerBinding("codex", ModelChoice("exact", "gpt-reviewer")),
        max_revisions=2,
    )


def _write_manifest(target, payload, *, execution_policy=None) -> None:
    options = InitOptions(
        claude_kit_version="0.0.0-test",
        selection=make_selection(payload),
        files=[],
        runtimes=["claude", "codex"],
        state_layout=StateLayout.neutral(),
        compatibility_catalog_versions={"claude": 1, "codex": 1},
        execution_policy=execution_policy,
    )
    manifest = target / StateLayout.neutral().manifest
    manifest.parent.mkdir(parents=True)
    document = options.to_dict()
    document["future_extension"] = {"preserve": True}
    manifest.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def test_configure_round_trips_policy_and_preserves_unknown_manifest_keys(
    tmp_path, payload
):
    _write_manifest(tmp_path, payload)

    configured = configure_execution_policy(tmp_path, _policy())

    assert configured == _policy()
    assert load_execution_policy(tmp_path) == _policy()
    document = json.loads(
        (tmp_path / StateLayout.neutral().manifest).read_text(encoding="utf-8")
    )
    assert document["execution"] == _policy().to_dict()
    assert document["future_extension"] == {"preserve": True}
    assert not (tmp_path / StateLayout.legacy_claude().manifest).exists()


def test_disable_is_idempotent_and_preserves_the_shared_manifest(tmp_path, payload):
    _write_manifest(tmp_path, payload, execution_policy=_policy())

    assert disable_execution_policy(tmp_path) is True
    assert disable_execution_policy(tmp_path) is False
    assert load_execution_policy(tmp_path) is None
    document = json.loads(
        (tmp_path / StateLayout.neutral().manifest).read_text(encoding="utf-8")
    )
    assert document["execution"] is None
    assert document["future_extension"] == {"preserve": True}


def test_configuration_requires_a_neutral_runtime_aware_install(tmp_path):
    with pytest.raises(ExecutionConfigError, match="neutral .ckit"):
        load_execution_policy(tmp_path)


def test_configuration_refuses_a_corrupt_manifest_without_rewriting_it(
    tmp_path,
):
    manifest = tmp_path / StateLayout.neutral().manifest
    manifest.parent.mkdir(parents=True)
    original = b'{"schema_version":3,"execution":'
    manifest.write_bytes(original)

    with pytest.raises(ExecutionConfigError, match="corrupt"):
        configure_execution_policy(tmp_path, _policy())

    assert manifest.read_bytes() == original
