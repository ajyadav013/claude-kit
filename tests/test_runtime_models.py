"""Provider-neutral runtime, state-layout, and manifest contracts."""

from __future__ import annotations

import pytest

from claude_kit import catalog
from claude_kit.models import (
    INIT_OPTIONS_SCHEMA,
    FileRecord,
    InitOptions,
    InstallRequest,
    Runtime,
    StateLayout,
)
from tests._helpers import make_selection


@pytest.mark.parametrize(
    ("value", "providers"),
    [
        ("claude", ("claude",)),
        ("codex", ("codex",)),
        ("both", ("claude", "codex")),
    ],
)
def test_runtime_parses_to_concrete_provider_set(value, providers):
    runtime = Runtime.parse(value)
    assert runtime.providers == providers
    assert Runtime.from_providers(list(reversed(providers))) is runtime


def test_runtime_rejects_unknown_or_duplicate_provider_sets():
    with pytest.raises(ValueError, match="runtime must be one of"):
        Runtime.parse("cursor")
    with pytest.raises(ValueError, match="exactly once"):
        Runtime.from_providers(["claude", "claude"])


def test_install_request_keeps_runtime_outside_selection_and_resolver(payload):
    selection = make_selection(payload)
    request = InstallRequest(selection=selection, runtime="codex")  # type: ignore[arg-type]
    assert "runtime" not in selection.to_dict()
    assert request.runtimes == ("codex",)
    assert catalog.resolve(payload, request.selection) == catalog.resolve(
        payload, selection
    )


def test_state_layouts_are_canonical_and_contained():
    neutral = StateLayout.neutral()
    legacy = StateLayout.legacy_claude()
    assert neutral.manifest == ".ckit/config/init-options.json"
    assert neutral.pipeline_snapshot == ".ckit/state/pipeline-snapshot.json"
    assert legacy.manifest == ".claude/config/init-options.json"
    assert StateLayout.from_dict(neutral.to_dict()) == neutral

    tampered = neutral.to_dict()
    tampered["pipeline_snapshot"] = ".claude/state/pipeline-snapshot.json"
    with pytest.raises(ValueError, match="contained under"):
        StateLayout.from_dict(tampered)


def _record(provider: str = "shared") -> FileRecord:
    return FileRecord(
        path=".gitignore",
        sha256="0" * 64,
        owner="user-editable",
        provider=provider,
        component_id="file://gitignore",
    )


@pytest.mark.parametrize(
    ("runtime", "providers"),
    [
        (Runtime.CLAUDE, ["claude"]),
        (Runtime.CODEX, ["codex"]),
        (Runtime.BOTH, ["claude", "codex"]),
    ],
)
def test_schema_v2_manifest_round_trips_runtime_and_neutral_layout(
    payload, runtime, providers
):
    options = InitOptions(
        claude_kit_version="0.0.0-test",
        selection=make_selection(payload),
        files=[_record()],
        runtimes=providers,
        state_layout=StateLayout.neutral(),
        compatibility_catalog_versions={provider: 1 for provider in providers},
    )
    restored = InitOptions.from_dict(options.to_dict())
    assert restored.schema_version == INIT_OPTIONS_SCHEMA
    assert restored.runtime is runtime
    assert restored.state_layout == StateLayout.neutral()
    assert restored.files[0].component_id == "file://gitignore"


def test_legacy_manifest_defaults_to_claude_and_legacy_layout(payload):
    restored = InitOptions.from_dict(
        {
            "schema_version": 1,
            "claude_kit_version": "0.83.0",
            "selection": make_selection(payload).to_dict(),
            "files": [
                {
                    "path": "CLAUDE.md",
                    "sha256": "0" * 64,
                    "owner": "user-editable",
                }
            ],
        }
    )
    assert restored.runtime is Runtime.CLAUDE
    assert restored.state_layout == StateLayout.legacy_claude()
    assert restored.files[0].provider == "claude"
    assert restored.to_dict()["schema_version"] == 2


def test_schema_v2_manifest_fails_closed_on_inconsistent_metadata(payload):
    base = InitOptions(
        claude_kit_version="0.0.0-test",
        selection=make_selection(payload),
        files=[],
    ).to_dict()
    with pytest.raises(ValueError, match="runtimes"):
        InitOptions.from_dict({**base, "runtimes": ["claude", "claude"]})
    with pytest.raises(ValueError, match="compatibility catalog versions"):
        InitOptions.from_dict({**base, "compatibility_catalog_versions": {"codex": 1}})
