"""Fail-closed schema parsing for persisted model documents."""

from __future__ import annotations

import pytest

from claude_kit.models import (
    FileRecord,
    GateDefinition,
    InitOptions,
    UpgradeJournal,
    digest_gate_definitions,
)
from tests._helpers import make_selection


def _init_options_doc(payload):
    return {
        "claude_kit_version": "0.0.0-test",
        "selection": make_selection(payload).to_dict(),
        "files": [],
    }


def test_init_options_absent_schema_is_explicit_legacy_v1(payload):
    options = InitOptions.from_dict(_init_options_doc(payload))
    assert options.schema_version == 2
    assert options.runtimes == ["claude"]
    assert options.state_layout.root == ".claude"


def test_init_options_rejects_future_and_malformed_schema(payload):
    document = _init_options_doc(payload)
    with pytest.raises(
        ValueError, match="unsupported future init-options schema_version 3"
    ):
        InitOptions.from_dict({**document, "schema_version": 3})
    with pytest.raises(ValueError, match="must be an integer"):
        InitOptions.from_dict({**document, "schema_version": "1"})


@pytest.mark.parametrize(
    "document, message",
    [
        ([], "root must be an object"),
        ({"selection": [], "files": []}, "selection must be an object"),
        ({"selection": {}, "files": {}}, "files must be an array"),
    ],
)
def test_init_options_rejects_wrong_container_shapes(document, message):
    with pytest.raises(ValueError, match=message):
        InitOptions.from_dict(document)


@pytest.mark.parametrize(
    "kwargs, message",
    [
        (
            {"path": "CLAUDE.md", "sha256": "not-a-digest", "owner": "kit"},
            "sha256",
        ),
        (
            {"path": "CLAUDE.md", "sha256": "0" * 64, "owner": "unknown"},
            "owner",
        ),
    ],
)
def test_file_records_reject_malformed_integrity_and_ownership(kwargs, message):
    with pytest.raises(ValueError, match=message):
        FileRecord(**kwargs)


def test_upgrade_journal_absent_schema_is_explicit_legacy_v1():
    journal = UpgradeJournal.from_dict(
        {
            "from_version": "0.1.0",
            "to_version": "0.2.0",
            "started_at": "2026-01-01T00:00:00+00:00",
            "actions": [],
        }
    )
    assert journal.schema_version == 1


def test_upgrade_journal_rejects_secure_transaction_and_future_schemas():
    base = {
        "from_version": "0.1.0",
        "to_version": "0.2.0",
        "started_at": "2026-01-01T00:00:00+00:00",
        "actions": [],
    }
    with pytest.raises(
        ValueError, match="unsupported future upgrade journal schema_version 2"
    ):
        UpgradeJournal.from_dict({**base, "schema_version": 2})
    with pytest.raises(
        ValueError, match="unsupported future upgrade journal schema_version 999"
    ):
        UpgradeJournal.from_dict({**base, "schema_version": 999})


@pytest.mark.parametrize(
    "bad, message",
    [
        (
            {
                "requirement": "conditional",
                "skippable": True,
                "skip_conditions": "no-surface",
            },
            "list of strings",
        ),
        (
            {
                "requirement": "required",
                "skippable": "false",
                "skip_conditions": [],
            },
            "must be a boolean",
        ),
    ],
)
def test_gate_definition_from_dict_rejects_wrong_container_types(bad, message):
    with pytest.raises(ValueError, match=message):
        GateDefinition.from_dict(bad)


def test_gate_definition_digest_requires_an_exact_unique_definition_set():
    required = GateDefinition("required", False, [])
    with pytest.raises(ValueError, match="missing definitions: build-green"):
        digest_gate_definitions(
            ["code-review", "build-green"], {"code-review": required}
        )
    with pytest.raises(ValueError, match="extra definitions: build-green"):
        digest_gate_definitions(
            ["code-review"], {"code-review": required, "build-green": required}
        )
    with pytest.raises(ValueError, match="contains duplicates"):
        digest_gate_definitions(
            ["code-review", "code-review"], {"code-review": required}
        )
