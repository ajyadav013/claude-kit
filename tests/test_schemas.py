"""JSON Schema layer: schema validity, real-catalog conformance, and rejection of bad shapes.

The whole module is skipped when the optional ``jsonschema`` dependency is absent (mirroring how
``check_catalog`` / ``validate --strict`` degrade to a no-op), so CI exercises it via the ``dev``
extra while a minimal runtime install is unaffected.
"""

from __future__ import annotations

from contextlib import ExitStack

import pytest

from claude_kit import schemas

jsonschema = pytest.importorskip("jsonschema")


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


def test_check_catalog_emits_schema_lines_and_passes():
    from claude_kit import validator

    ok, msgs = validator.check_catalog(".")
    assert ok, [m for m in msgs if m.startswith("FAIL")]
    assert any("matches its JSON Schema" in m for m in msgs)
    assert any("org pack manifest" in m for m in msgs)
