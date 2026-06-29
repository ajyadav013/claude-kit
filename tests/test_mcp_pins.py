"""scripts/check_mcp_pins.py — offline pin gate over catalog/mcp.yaml."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "check_mcp_pins", ROOT / "scripts" / "check_mcp_pins.py"
)
assert _spec and _spec.loader
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def _doc(server):
    return {"version": 1, "servers": {"x": server}}


def test_real_catalog_is_fully_pinned():
    assert mod.check_pins() == []
    assert mod.collect_specs(), (
        "expected at least one pinnable server in the real catalog"
    )


def test_npx_latest_is_flagged():
    doc = _doc(
        {"config": {"type": "stdio", "command": "npx", "args": ["-y", "foo@latest"]}}
    )
    assert [b[0] for b in mod.check_pins(doc)] == ["x"]


def test_npx_unpinned_is_flagged():
    doc = _doc({"config": {"type": "stdio", "command": "npx", "args": ["-y", "foo"]}})
    bad = mod.check_pins(doc)
    assert bad and bad[0][3] == "(unpinned)"


def test_uvx_unpinned_is_flagged():
    doc = _doc(
        {"config": {"type": "stdio", "command": "uvx", "args": ["--from", "bar", "m"]}}
    )
    assert [b[0] for b in mod.check_pins(doc)] == ["x"]


def test_pinned_npx_and_uvx_pass():
    npx = _doc(
        {
            "config": {
                "type": "stdio",
                "command": "npx",
                "args": ["-y", "@scope/p@1.2.3"],
            }
        }
    )
    assert mod.check_pins(npx) == []
    uvx = _doc(
        {
            "config": {
                "type": "stdio",
                "command": "uvx",
                "args": ["--from", "p==1.0.0", "m"],
            }
        }
    )
    assert mod.check_pins(uvx) == []


def test_http_and_binary_servers_are_skipped():
    http = _doc({"config": {"type": "http", "url": "https://example.com/mcp"}})
    assert mod.collect_specs(http) == []
    binary = _doc({"config": {"type": "stdio", "command": "wassette", "args": ["run"]}})
    assert mod.collect_specs(binary) == []


def test_scoped_npx_without_version_is_flagged():
    doc = _doc(
        {"config": {"type": "stdio", "command": "npx", "args": ["-y", "@scope/pkg"]}}
    )
    bad = mod.check_pins(doc)
    assert bad and bad[0][3] == "(unpinned)"
