"""`.mcp.lock.json`: deterministic resolved-version capture + doctor --mcp lock agreement."""

from __future__ import annotations

import json

from claude_kit import scaffold, validator
from tests._helpers import install


def test_no_lock_without_mcp(tmp_path, payload):
    install(payload, tmp_path)
    assert not (tmp_path / ".mcp.lock.json").exists()
    assert not (tmp_path / ".mcp.json").exists()


def test_lock_written_and_tracked_as_kit_owned(tmp_path, payload):
    install(payload, tmp_path, mcp=["github"])
    lock = tmp_path / ".mcp.lock.json"
    assert lock.is_file()
    opts = json.loads(
        (tmp_path / ".claude" / "config" / "init-options.json").read_text(
            encoding="utf-8"
        )
    )
    rec = next(f for f in opts["files"] if f["path"] == ".mcp.lock.json")
    assert rec["owner"] == "kit"  # derived, refreshed on upgrade — never a user sidecar


def test_lock_captures_package_version_and_url():
    servers = {
        "github": {
            "type": "stdio",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-github@2025.4.8"],
        },
        "jira": {
            "type": "stdio",
            "command": "npx",
            "args": ["-y", "mcp-atlassian@2.1.0"],
        },
        "linear": {"type": "http", "url": "https://mcp.linear.app/mcp"},
        "repowise": {"type": "stdio", "command": "repowise", "args": ["mcp", "${X}"]},
    }
    lock = scaffold._mcp_lock(servers)["servers"]
    assert lock["github"] == {
        "type": "stdio",
        "package": "@modelcontextprotocol/server-github",
        "version": "2025.4.8",
    }
    assert (
        lock["jira"]["package"] == "mcp-atlassian"
        and lock["jira"]["version"] == "2.1.0"
    )
    assert lock["linear"] == {"type": "http", "url": "https://mcp.linear.app/mcp"}
    # No npx package to pin — fall back to recording the command.
    assert lock["repowise"] == {"type": "stdio", "command": "repowise"}


def test_lock_handles_unpinned_and_unresolvable_specs():
    servers = {
        "unpinned": {"type": "stdio", "command": "npx", "args": ["-y", "some-pkg"]},
        "scoped_unpinned": {
            "type": "stdio",
            "command": "npx",
            "args": ["-y", "@scope/pkg"],
        },
        "only_env": {"type": "stdio", "command": "npx", "args": ["-y", "${PKG}"]},
        "url_arg": {
            "type": "stdio",
            "command": "npx",
            "args": ["-y", "https://x/server.js"],
        },
    }
    lock = scaffold._mcp_lock(servers)["servers"]
    assert lock["unpinned"] == {"type": "stdio", "package": "some-pkg"}
    assert lock["scoped_unpinned"] == {"type": "stdio", "package": "@scope/pkg"}
    # No resolvable npm package (all-env or a URL arg) → fall back to recording the command.
    assert lock["only_env"] == {"type": "stdio", "command": "npx"}
    assert lock["url_arg"] == {"type": "stdio", "command": "npx"}


def test_lock_removed_when_servers_dropped(tmp_path, payload):
    install(payload, tmp_path, mcp=["github"])
    assert (tmp_path / ".mcp.lock.json").is_file()
    # Source config gone, then re-init with no servers → the orphaned lockfile is cleaned up.
    (tmp_path / ".mcp.json").unlink()
    install(payload, tmp_path)  # default selection has no MCP servers
    assert not (tmp_path / ".mcp.lock.json").exists()


def test_lock_is_deterministic(tmp_path, payload):
    install(payload, tmp_path, mcp=["github", "linear"])
    first = (tmp_path / ".mcp.lock.json").read_text(encoding="utf-8")
    # Re-deriving from the same catalog config yields byte-identical content (no timestamps).
    from claude_kit import catalog
    from tests._helpers import make_selection

    plan = catalog.resolve(payload, make_selection(payload, mcp=["github", "linear"]))
    again = json.dumps(scaffold._mcp_lock(plan.mcp_servers), indent=2) + "\n"
    assert again == first


def test_doctor_mcp_reports_lock_agreement(tmp_path, payload):
    install(payload, tmp_path, mcp=["github"])
    ok, msgs = validator.doctor(tmp_path, mcp=True)
    assert ok
    assert any(".mcp.lock.json matches .mcp.json" in m for m in msgs)


def test_doctor_mcp_flags_lock_drift(tmp_path, payload):
    install(payload, tmp_path, mcp=["github"])
    # User adds a server to .mcp.json but the lock wasn't regenerated.
    mcp = tmp_path / ".mcp.json"
    doc = json.loads(mcp.read_text(encoding="utf-8"))
    doc["mcpServers"]["extra"] = {"type": "http", "url": "https://example.com/mcp"}
    mcp.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    ok, msgs = validator.doctor(tmp_path, mcp=True)
    assert ok  # drift is a warning, never a failure
    assert any("out of sync" in m for m in msgs)
