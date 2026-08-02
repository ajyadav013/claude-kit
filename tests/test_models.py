"""Selection.from_dict: the typed boundary between a --config file and the resolver.

Strict mode is what a `--config` file is parsed with, so a typo there must fail loudly rather than
being dropped on the floor — a silently ignored key would scaffold a project the user did not ask for.
"""

from __future__ import annotations

import pytest

from claude_kit.models import Selection


def _minimal() -> dict:
    return {
        "frontend_framework": "react",
        "frontend_language": "typescript",
        "backend_language": "python",
        "backend_framework": "fastapi",
        "database": "postgres",
        "profile": "standard",
    }


def test_from_dict_defaults_mcp_to_an_empty_list():
    sel = Selection.from_dict(_minimal())
    assert sel.mcp == []


def test_lenient_from_dict_ignores_unknown_keys():
    sel = Selection.from_dict({**_minimal(), "colour": "blue"})
    assert not hasattr(sel, "colour")


def test_strict_from_dict_rejects_unknown_keys():
    with pytest.raises(ValueError, match="unknown selection field"):
        Selection.from_dict({**_minimal(), "colour": "blue"}, strict=True)


@pytest.mark.parametrize("field_name", ["mcp", "teams"])
@pytest.mark.parametrize("bad", ["github", ["github", 7], [None]])
def test_strict_from_dict_rejects_non_string_list_fields(field_name, bad):
    with pytest.raises(ValueError, match=f"{field_name}.*list of strings"):
        Selection.from_dict({**_minimal(), field_name: bad}, strict=True)


def test_strict_from_dict_accepts_absent_list_fields():
    sel = Selection.from_dict(_minimal(), strict=True)
    assert sel.mcp == [] and sel.teams == []


def test_strict_from_dict_rejects_non_boolean_org_packs():
    with pytest.raises(ValueError, match="org_packs.*boolean"):
        Selection.from_dict({**_minimal(), "org_packs": "yes"}, strict=True)


def test_roundtrip_through_to_dict_is_lossless():
    sel = Selection.from_dict({**_minimal(), "mcp": ["github"], "teams": ["platform"]})
    assert Selection.from_dict(sel.to_dict()) == sel
