"""from_config: friendly YAML is normalised, and malformed/typo'd config fails loudly."""

from __future__ import annotations

import pytest

from claude_kit import catalog, prompts


def _write(tmp_path, body: str):
    p = tmp_path / "init.yaml"
    p.write_text(body, encoding="utf-8")
    return p


def test_bare_mcp_string_is_normalised_to_a_list(tmp_path, payload):
    """`mcp: github` (a scalar) becomes ["github"] instead of being iterated char-by-char."""
    cfg = _write(tmp_path, "mcp: github\n")
    sel = prompts.from_config(cfg, payload)
    assert sel.mcp == ["github"]
    # ...and it resolves to a real server, not 'g','i','t',... :
    plan = catalog.resolve(payload, sel)
    assert "github" in plan.mcp_servers


def test_mcp_wrong_shape_is_rejected(tmp_path, payload):
    """A mapping (or any non-string-list) for a list field fails with a clear message."""
    cfg = _write(tmp_path, "mcp:\n  github: true\n")
    with pytest.raises(ValueError, match="mcp"):
        prompts.from_config(cfg, payload)


def test_unknown_config_key_is_rejected(tmp_path, payload):
    """A typo'd top-level key (databse) is reported rather than silently ignored."""
    cfg = _write(tmp_path, "databse: postgres\n")
    with pytest.raises(ValueError, match="unknown config key"):
        prompts.from_config(cfg, payload)


def test_teams_string_is_normalised(tmp_path, payload):
    """A bare `teams: engineering` becomes a one-element list."""
    cfg = _write(tmp_path, "scope: organization\nteams: engineering\n")
    sel = prompts.from_config(cfg, payload)
    assert sel.teams == ["engineering"]


def test_malformed_yaml_is_a_friendly_valueerror(tmp_path, payload):
    """A YAML syntax error becomes a one-line ValueError (the CLI renders those as
    `error: … / exit 2`) instead of a raw PyYAML ScannerError escaping to the user."""
    cfg = _write(tmp_path, "profile: standard\n  backend: [unclosed\n")
    with pytest.raises(ValueError, match="not valid YAML"):
        prompts.from_config(cfg, payload)
