"""Central schema-registry coverage for the provider-neutral workflow catalog."""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path

import yaml

from claude_kit import schemas


def test_sdlc_workflow_is_registered_and_matches_its_strict_schema(
    payload: Path,
) -> None:
    workflow_path = payload / "catalog" / "workflows" / "sdlc.yaml"
    document = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))

    assert schemas.SCHEMAS["workflow"] == "workflow.schema.json"
    with ExitStack() as stack:
        assert schemas.validate_doc(document, "workflow", stack) == []
        assert schemas.validate_doc(
            {**document, "schema_version": 999}, "workflow", stack
        )
