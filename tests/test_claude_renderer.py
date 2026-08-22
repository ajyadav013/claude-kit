"""Claude native renderer compatibility and neutral-state contracts."""

from __future__ import annotations

import os
import subprocess

import yaml

from claude_kit import catalog
from claude_kit.claude_renderer import ClaudeRenderer
from claude_kit.models import InstallRequest


def test_claude_renderer_preserves_native_surface_and_removes_legacy_state(payload):
    selection = catalog.defaults(payload)
    plan = catalog.resolve(payload, selection)
    rendered = tuple(
        ClaudeRenderer(payload).render(
            plan, InstallRequest(selection=selection, runtime="claude")
        )
    )
    paths = {item.path for item in rendered}

    assert "CLAUDE.md" in paths
    assert ".claude/agents/orchestrator.md" in paths
    assert ".claude/skills/sdlc/SKILL.md" in paths
    assert ".claude/rules/quality-gates.md" in paths
    assert ".claude/settings.json" in paths
    assert "AGENTS.md" not in paths
    assert ".claude/config/init-options.json" not in paths
    assert not any(path.startswith(".claude/state/") for path in paths)
    assert not any(path.startswith(".claude/agent-memory/") for path in paths)


def test_claude_renderer_records_loaded_compatibility_catalog_version(payload):
    policy = yaml.safe_load(
        (payload / "catalog/claude-compatibility.yaml").read_text(encoding="utf-8")
    )

    assert (
        ClaudeRenderer(payload).spec.compatibility_catalog_version == policy["version"]
    )


def test_claude_renderer_rewrites_only_mutable_state_paths(payload):
    selection = catalog.defaults(payload)
    plan = catalog.resolve(payload, selection)
    rendered = tuple(
        ClaudeRenderer(payload).render(
            plan, InstallRequest(selection=selection, runtime="claude")
        )
    )
    text = "\n".join(
        item.text_content for item in rendered if item.media_type.startswith("text/")
    )

    assert ".ckit/CONTINUITY.md" in text
    assert ".ckit/agent-memory" in text
    assert ".claude/CONTINUITY.md" not in text
    assert ".claude/agent-memory" not in text
    # Claude's native discovery tree must not be mechanically renamed.
    assert ".claude/agents" in text
    assert ".claude/rules" in text


def test_projected_claude_continuity_hook_executes_against_shared_state(
    payload, tmp_path
):
    selection = catalog.defaults(payload)
    plan = catalog.resolve(payload, selection)
    rendered = tuple(
        ClaudeRenderer(payload).render(
            plan, InstallRequest(selection=selection, runtime="claude")
        )
    )
    projected = next(
        item for item in rendered if item.path == ".claude/hooks/load-continuity.sh"
    )
    script = tmp_path / projected.path
    script.parent.mkdir(parents=True)
    script.write_bytes(projected.content)
    script.chmod(0o755)
    continuity = tmp_path / ".ckit/CONTINUITY.md"
    continuity.parent.mkdir(parents=True)
    marker = "shared continuity loaded by projected Claude hook"
    continuity.write_text(marker + "\n", encoding="utf-8")

    result = subprocess.run(
        ("bash", str(script)),
        cwd=tmp_path,
        env={**os.environ, "CLAUDE_PROJECT_DIR": str(tmp_path)},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert marker in result.stdout
    assert ".ckit/CONTINUITY.md" in result.stdout


def test_claude_renderer_is_deterministic(payload):
    selection = catalog.defaults(payload)
    plan = catalog.resolve(payload, selection)
    request = InstallRequest(selection=selection, runtime="claude")
    first = tuple(ClaudeRenderer(payload).render(plan, request))
    second = tuple(ClaudeRenderer(payload).render(plan, request))

    assert [(item.path, item.sha256) for item in first] == [
        (item.path, item.sha256) for item in second
    ]
