"""JSON Schema validity, real-catalog conformance, and rejection of bad shapes."""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path

import jsonschema
import pytest
import yaml

from claude_kit import schemas


def test_every_schema_file_is_itself_a_valid_draft_2020_12_schema():
    with ExitStack() as stack:
        for name in schemas.SCHEMAS:
            schema = schemas.load_schema(name, stack)
            cls = jsonschema.validators.validator_for(schema)
            cls.check_schema(schema)
            assert schema.get("$schema", "").endswith("2020-12/schema")


def test_real_catalog_files_match_their_schemas():
    from claude_kit import catalog, scaffold

    with ExitStack() as stack:
        root = scaffold.payload_dir(stack)
        cat_dir = catalog.catalog_dir(root)
        for sname, fn in [
            ("stacks", "stacks.yaml"),
            ("profiles", "profiles.yaml"),
            ("mcp", "mcp.yaml"),
            ("capture", "capture.yaml"),
            ("org", "org.yaml"),
            ("claude-compatibility", "claude-compatibility.yaml"),
            ("codex-compatibility", "codex-compatibility.yaml"),
            ("plugin-metadata", "plugin-metadata.yaml"),
        ]:
            if not (cat_dir / fn).is_file():
                continue
            doc = catalog._load(root, fn)
            assert schemas.validate_doc(doc, sname, stack) == [], fn


def test_real_org_pack_manifests_match_schema():
    import yaml

    from claude_kit import scaffold

    with ExitStack() as stack:
        root = scaffold.payload_dir(stack)
        packs = sorted((root / "templates" / "org" / "packs").glob("*/pack.yaml"))
        assert packs, "expected at least one org pack manifest"
        for pf in packs:
            doc = yaml.safe_load(pf.read_text(encoding="utf-8"))
            assert schemas.validate_doc(doc, "org-pack", stack) == [], str(pf)


def test_invalid_capture_mode_missing_hooks_is_rejected():
    with ExitStack() as stack:
        bad = {"version": 1, "default": "off", "modes": {"off": {"label": "x"}}}
        errs = schemas.validate_doc(bad, "capture", stack)
        assert errs and any("hooks" in e for e in errs)


def test_invalid_org_pack_component_missing_existing_is_rejected():
    with ExitStack() as stack:
        bad = {
            "id": "x",
            "label": "X",
            "version": "0.1.0",
            "skills": [{"name": "sdlc"}],  # missing required 'existing'
        }
        errs = schemas.validate_doc(bad, "org-pack", stack)
        assert errs and any("existing" in e for e in errs)


@pytest.mark.parametrize(
    ("schema_name", "doc"),
    [
        ("stacks", {"version": 999}),
        ("profiles", {"version": 999, "profiles": {}, "gate_definitions": {}}),
        ("mcp", {"version": 999, "servers": {}}),
        ("capture", {"version": 999, "default": "off", "modes": {}}),
        ("org", {"version": 999}),
        ("mcp-lock", {"schema": 999, "servers": {}}),
    ],
)
def test_versioned_documents_reject_future_versions(schema_name, doc):
    with ExitStack() as stack:
        assert schemas.validate_doc(doc, schema_name, stack) != []


def test_current_stack_snapshot_is_valid_and_future_version_is_rejected():
    current = {
        "schema_version": 1,
        "selection": {},
        "agents": [],
        "skills": [],
        "overlay_rules": [],
        "overlay_agents": [],
        "hooks": [],
        "gates": [],
        "gate_definitions": {},
        "gate_definition_digest": "0" * 64,
        "mcp": [],
    }
    with ExitStack() as stack:
        assert schemas.validate_doc(current, "stack-catalog-snapshot", stack) == []
        assert (
            schemas.validate_doc(
                {**current, "schema_version": 999}, "stack-catalog-snapshot", stack
            )
            != []
        )


def test_stack_snapshot_schema_validates_optional_mcp_semantics():
    base = {
        "schema_version": 1,
        "selection": {},
        "agents": [],
        "skills": [],
        "overlay_rules": [],
        "overlay_agents": [],
        "hooks": [],
        "gates": [],
        "gate_definitions": {},
        "gate_definition_digest": "0" * 64,
        "mcp": ["limited"],
    }
    semantics = {
        "limited": {
            "label": "Limited server",
            "transport": "stdio",
            "authentication": "oauth",
            "runtime_support": ["claude"],
            "health_check": "mcp-initialize",
            "environment_references": ["LIMITED_TOKEN"],
        }
    }
    with ExitStack() as stack:
        assert (
            schemas.validate_doc(
                {**base, "mcp_semantics": semantics},
                "stack-catalog-snapshot",
                stack,
            )
            == []
        )
    for field, invalid in (
        ("authentication", "unknown"),
        ("runtime_support", ["cursor"]),
        ("health_check", "shell-command"),
        ("environment_references", ["TOKEN", "TOKEN"]),
    ):
        record = {**semantics["limited"], field: invalid}
        with ExitStack() as stack:
            assert schemas.validate_doc(
                {**base, "mcp_semantics": {"limited": record}},
                "stack-catalog-snapshot",
                stack,
            )


def test_current_compatibility_policy_is_valid_and_future_version_is_rejected():
    current = yaml.safe_load(
        (Path(__file__).parents[1] / "catalog" / "claude-compatibility.yaml").read_text(
            encoding="utf-8"
        )
    )
    with ExitStack() as stack:
        assert schemas.validate_doc(current, "claude-compatibility", stack) == []
        assert (
            schemas.validate_doc(
                {**current, "version": 999}, "claude-compatibility", stack
            )
            != []
        )


def test_claude_compatibility_policy_is_pinned_and_complete():
    policy = yaml.safe_load(
        (Path(__file__).parents[1] / "catalog" / "claude-compatibility.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert policy["host"] == "claude"
    assert policy["status"] == "stable"
    assert policy["minimum"] == "2.1.163"
    assert policy["current_stable"] == "2.1.239"
    assert policy["stable_as_of"] == "2026-08-22"
    ci_versions = {entry["version"] for entry in policy["tested"] if entry["ci"]}
    assert {"2.1.163", "2.1.239"} <= ci_versions
    assert policy["agents"]["project_directory"] == ".claude/agents"
    assert policy["agents"]["model_tier_mapping"] == {
        "fast": "haiku",
        "balanced": "sonnet",
        "deep": "opus",
    }
    assert policy["agents"]["permission_class_mapping"] == {
        "read_only": "plan",
        "workspace_write": "acceptEdits",
        "external_effect": "acceptEdits",
    }
    assert {"name", "description"} <= set(policy["agents"]["required_fields"])
    assert policy["skills"]["project_directory"] == ".claude/skills"
    assert policy["skills"]["manual_only_field"] == "disable-model-invocation"
    assert policy["plugins"]["manifest"] == ".claude-plugin/plugin.json"
    assert {"SessionStart", "PreToolUse", "PostToolUse", "Stop"} <= set(
        policy["events"]["recognized"]
    )


def test_codex_compatibility_policy_is_pinned_preview_and_native():
    policy = yaml.safe_load(
        (Path(__file__).parents[1] / "catalog" / "codex-compatibility.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert policy["host"] == "codex"
    assert policy["status"] == "preview"
    assert policy["minimum"] == "0.147.0"
    assert policy["current_stable"] == "0.149.0"
    assert policy["stable_as_of"] == "2026-08-22"
    ci_versions = {entry["version"] for entry in policy["tested"] if entry["ci"]}
    assert {"0.147.0", "0.149.0"} <= ci_versions
    current = next(
        entry for entry in policy["tested"] if entry["role"] == "current-stable"
    )
    assert current["plugin_validator"] == {
        "validate_plugin_sha256": (
            "6ff4bc1cc8ca94827c30c8299951efdac900ff38a5069c03e9a6554fc194a723"
        ),
        "identifier_validation_sha256": (
            "a6d51ce4a9a7e8f85626ff5808a467a67574e7f8cdf1167ffb467c5f67e57223"
        ),
    }

    assert policy["agents"]["project_directory"] == ".codex/agents"
    assert policy["agents"]["model_tier_mapping"] == {
        "fast": None,
        "balanced": None,
        "deep": None,
    }
    assert policy["agents"]["sandbox_mapping"] == {
        "read_only": "read-only",
        "workspace_write": "workspace-write",
        "external_effect": "workspace-write",
    }
    assert {"name", "description", "developer_instructions"} <= set(
        policy["agents"]["required_fields"]
    )
    assert policy["skills"]["project_directory"] == ".agents/skills"
    assert policy["skills"]["manual_only_field"] == "policy.allow_implicit_invocation"
    assert policy["plugins"]["package_root"] == "providers/codex/claude-kit"
    assert policy["plugins"]["manifest"] == ".codex-plugin/plugin.json"
    assert policy["plugins"]["repo_marketplace"] == ".agents/plugins/marketplace.json"
    assert policy["plugins"]["marketplace_source"] == ("./providers/codex/claude-kit")
    assert {"SessionStart", "PreToolUse", "PostToolUse", "Stop"} <= set(
        policy["events"]["recognized"]
    )


def test_codex_compatibility_schema_rejects_future_or_incomplete_policies():
    policy = yaml.safe_load(
        (Path(__file__).parents[1] / "catalog" / "codex-compatibility.yaml").read_text(
            encoding="utf-8"
        )
    )
    with ExitStack() as stack:
        assert schemas.validate_doc(policy, "codex-compatibility", stack) == []
        assert (
            schemas.validate_doc(
                {**policy, "version": 999}, "codex-compatibility", stack
            )
            != []
        )
        missing_agent_contract = {
            **policy,
            "agents": {
                key: value
                for key, value in policy["agents"].items()
                if key != "required_fields"
            },
        }
        errs = schemas.validate_doc(
            missing_agent_contract, "codex-compatibility", stack
        )
        assert any("required_fields" in err for err in errs)
        missing_mapping = {
            **policy,
            "agents": {
                key: value
                for key, value in policy["agents"].items()
                if key != "sandbox_mapping"
            },
        }
        assert schemas.validate_doc(missing_mapping, "codex-compatibility", stack) != []
        invalid_support = {
            **policy,
            "plugins": {**policy["plugins"], "support": "assumed"},
        }
        assert schemas.validate_doc(invalid_support, "codex-compatibility", stack)


def test_persisted_artifact_schemas_accept_representative_docs():
    with ExitStack() as stack:
        lock = {"schema": 1, "servers": {"github": {"type": "stdio", "package": "x"}}}
        assert schemas.validate_doc(lock, "mcp-lock", stack) == []
        snap = {"schema": 1, "profile": "standard", "scope": "team", "mode": "B"}
        assert schemas.validate_doc(snap, "pipeline-snapshot", stack) == []
        # 0.66.0: optional machine-derived identity anchors (git/pr) are typed and accepted
        snap_with_identity = {
            **snap,
            "git": {
                "branch": "feat/x",
                "sha": "abc123",
                "worktrees": {"backend": "/tmp/wt-b"},
            },
            "pr": {"number": "7", "url": "https://example.test/pr/7", "state": "open"},
        }
        assert (
            schemas.validate_doc(snap_with_identity, "pipeline-snapshot", stack) == []
        )
        bad_identity = {**snap, "git": {"branch": 42}}
        assert schemas.validate_doc(bad_identity, "pipeline-snapshot", stack) != []
        bad_snap = {"schema": 1, "profile": "not-a-profile"}
        assert schemas.validate_doc(bad_snap, "pipeline-snapshot", stack) != []


def test_pipeline_schema_accepts_v2_lifecycle_and_rejects_future_versions():
    with ExitStack() as stack:
        current = {
            "schema_version": 2,
            "run_id": "run-123",
            "repository_root": "/repo",
            "branch": "main",
            "starting_commit": "a" * 40,
            "current_commit": "a" * 40,
            "kit_version": "0.83.0",
            "profile": "standard",
            "scope": "team",
            "mode": "E",
            "ordered_gates": ["spec-complete"],
            "gate_definition_digest": "b" * 64,
            "selection_digest": "c" * 64,
            "start_type": "fresh",
            "created_at": "2026-08-20T00:00:00+00:00",
            "status": "active",
            "task": "demo",
            "stage": "spec-complete",
            "open_findings": {
                "critical": 0,
                "high": 0,
                "medium": 0,
                "low": 0,
                "cosmetic": 0,
            },
            "findings_evidence": None,
            "accepted_risks": [],
            "stage_history": [],
            "condition_decisions": {"frontend-surface-present": False},
            "gate_history": [],
        }
        assert schemas.validate_doc(current, "pipeline-snapshot", stack) == []
        assert (
            schemas.validate_doc(
                {**current, "schema_version": 999}, "pipeline-snapshot", stack
            )
            != []
        )
        recorded = {
            **current,
            "findings_evidence": {
                "counts": current["open_findings"],
                "evidence_path": "artifacts/findings.json",
                "evidence_sha256": "c" * 64,
                "finding_set_digest": "d" * 64,
                "repository_commit": "a" * 40,
                "recorded_at": "2026-08-20T00:01:00+00:00",
            },
        }
        assert schemas.validate_doc(recorded, "pipeline-snapshot", stack) == []
        stage_recorded = {
            **recorded,
            "stage_history": [
                {
                    "stage": "review",
                    "status": "succeeded",
                    "role": "reviewer",
                    "provider": "codex",
                    "dispatch_id": "dispatch-1",
                    "attempt": 1,
                    "dispatch_attempt": 1,
                    "required_capabilities": ["filesystem.read"],
                    "attested_capabilities": ["filesystem.read"],
                    "started_at": "2026-08-20T00:01:00+00:00",
                    "repository_commit": "a" * 40,
                    "completed_at": "2026-08-20T00:02:00+00:00",
                    "completion_commit": "a" * 40,
                    "output_sha256": "e" * 64,
                    "evidence": ["artifact://review-verdict"],
                    "error": None,
                }
            ],
        }
        assert schemas.validate_doc(stage_recorded, "pipeline-snapshot", stack) == []
        invalid_condition = {
            **current,
            "condition_decisions": {"frontend-surface-present": "no"},
        }
        assert schemas.validate_doc(invalid_condition, "pipeline-snapshot", stack) != []
        missing_count = {
            **recorded,
            "findings_evidence": {
                **recorded["findings_evidence"],
                "counts": {"critical": 0, "high": 0, "medium": 0, "low": 0},
            },
        }
        assert schemas.validate_doc(missing_count, "pipeline-snapshot", stack) != []


def test_check_catalog_emits_schema_lines_and_passes():
    from claude_kit import validator

    ok, msgs = validator.check_catalog(".")
    assert ok, [m for m in msgs if m.startswith("FAIL")]
    assert any("matches its JSON Schema" in m for m in msgs)
    assert any("codex-compatibility.yaml matches its JSON Schema" in m for m in msgs)
    assert any("plugin-metadata.yaml matches its JSON Schema" in m for m in msgs)
    assert any("org pack manifest" in m for m in msgs)
