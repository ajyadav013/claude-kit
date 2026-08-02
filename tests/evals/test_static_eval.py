"""Negative controls for the static evaluator.

A checker that cannot fail reports CLEAN on a broken payload, which is worse than no checker at
all — the same false-verdict class as a test command whose exit status is masked by a pipe. Each
check therefore gets a synthetic component built to violate exactly it, and must fire.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "static_eval",
    Path(__file__).resolve().parents[2] / "scripts" / "evals" / "static_eval.py",
)
static_eval = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(static_eval)


def _agent(tmp_path: Path, name: str, frontmatter: str) -> dict:
    d = tmp_path / "agents"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.md").write_text(
        f"---\n{frontmatter}\n---\n\n# {name}\n", encoding="utf-8"
    )
    return {
        "id": f"agent:{name}",
        "type": "agent",
        "path": f"agents/{name}.md",
        "risk": "high",
    }


def _run(comp, tmp_path, *, reach=None, rules=None, tiers=None):
    return static_eval.check_prose_component(
        comp,
        tmp_path,
        reach or {"agents": set(), "skills": set(), "hooks": set()},
        rules or set(),
        tiers or {"orchestrator", "stage-lead", "specialist", "review"},
    )


def _checks(findings):
    return {f["check"] for f in findings}


def test_missing_file_is_critical(tmp_path):
    comp = {
        "id": "agent:ghost",
        "type": "agent",
        "path": "agents/ghost.md",
        "risk": "high",
    }
    findings = _run(comp, tmp_path)
    assert _checks(findings) == {"exists"}
    assert findings[0]["severity"] == "critical"


def test_read_only_promise_with_a_write_tool_is_flagged(tmp_path):
    comp = _agent(
        tmp_path,
        "auditor",
        "name: auditor\ndescription: Read-only — produces audit reports.\n"
        "tools: Read, Grep, Write\ntier: review",
    )
    findings = _run(comp, tmp_path)
    assert "role_vs_tools" in _checks(findings)
    assert any(f["severity"] == "high" and "Write" in f["detail"] for f in findings)


def test_a_writing_agent_without_a_read_only_promise_is_not_flagged(tmp_path):
    """The check must not fire on every agent that holds Write — only on a contradicted promise."""
    comp = _agent(
        tmp_path,
        "developer",
        "name: developer\ndescription: Writes production code from approved specs.\n"
        "tools: Read, Write, Edit\ntier: specialist",
    )
    assert "role_vs_tools" not in _checks(_run(comp, tmp_path))


def test_orchestrator_writing_state_is_not_a_contradiction(tmp_path):
    """'Never writes code' + Write is consistent: it writes snapshots, not application code."""
    comp = _agent(
        tmp_path,
        "orchestrator",
        "name: orchestrator\ndescription: Never writes code — only delegates and gates.\n"
        "tools: Read, Write, Edit\ntier: orchestrator",
    )
    assert "role_vs_tools" not in _checks(_run(comp, tmp_path))


def test_name_must_match_the_filename(tmp_path):
    comp = _agent(
        tmp_path,
        "reviewer",
        "name: reviewer-v2\ndescription: x\ntools: Read\ntier: review",
    )
    assert "name_matches_path" in _checks(_run(comp, tmp_path))


def test_unknown_tool_is_flagged(tmp_path):
    comp = _agent(
        tmp_path, "typo", "name: typo\ndescription: x\ntools: Read, Reed\ntier: review"
    )
    findings = _run(comp, tmp_path)
    assert "tools_known" in _checks(findings)
    assert any("Reed" in f["detail"] for f in findings)


def test_undocumented_tier_is_flagged_but_a_documented_one_is_not(tmp_path):
    bad = _agent(tmp_path, "a", "name: a\ndescription: x\ntools: Read\ntier: wizard")
    assert "tier" in _checks(_run(bad, tmp_path))
    good = _agent(
        tmp_path, "b", "name: b\ndescription: x\ntools: Read\ntier: stage-lead"
    )
    assert "tier" not in _checks(_run(good, tmp_path))


def test_missing_tier_is_flagged(tmp_path):
    comp = _agent(tmp_path, "c", "name: c\ndescription: x\ntools: Read")
    assert "tier" in _checks(_run(comp, tmp_path))


def test_missing_description_is_flagged(tmp_path):
    comp = _agent(tmp_path, "d", "name: d\ntools: Read\ntier: review")
    assert "description" in _checks(_run(comp, tmp_path))


def test_invalid_frontmatter_yaml_is_reported(tmp_path):
    comp = _agent(
        tmp_path,
        "e",
        "name: e\ndescription: Reviews things: carefully\ntools: Read\ntier: review",
    )
    findings = _run(comp, tmp_path)
    assert "frontmatter" in _checks(findings)
    assert any("not valid YAML" in f["detail"] for f in findings)


def test_unreachable_agent_is_reported(tmp_path):
    comp = _agent(tmp_path, "f", "name: f\ndescription: x\ntools: Read\ntier: review")
    assert "reachability" in _checks(_run(comp, tmp_path))
    reach = {"agents": {"f"}, "skills": set(), "hooks": set()}
    assert "reachability" not in _checks(_run(comp, tmp_path, reach=reach))


def test_rule_referencing_a_missing_rule_is_flagged(tmp_path):
    (tmp_path / "rules").mkdir()
    (tmp_path / "rules" / "a.md").write_text(
        "# A\n\nSee `.claude/rules/ghost.md` and `.claude/rules/real.md`.\n",
        encoding="utf-8",
    )
    comp = {"id": "rule:a", "type": "rule", "path": "rules/a.md", "risk": "high"}
    findings = _run(comp, tmp_path, rules={"real.md"})
    assert "rule_ref" in _checks(findings)
    assert any("ghost.md" in f["detail"] for f in findings)


def test_rule_without_an_h1_is_flagged(tmp_path):
    (tmp_path / "rules").mkdir()
    (tmp_path / "rules" / "b.md").write_text("no heading here\n", encoding="utf-8")
    comp = {"id": "rule:b", "type": "rule", "path": "rules/b.md", "risk": "low"}
    assert "rule_h1" in _checks(_run(comp, tmp_path, rules=set()))


def test_a_clean_agent_produces_no_findings(tmp_path):
    comp = _agent(
        tmp_path,
        "clean",
        "name: clean\ndescription: Reviews code for defects.\ntools: Read, Grep\ntier: review",
    )
    reach = {"agents": {"clean"}, "skills": set(), "hooks": set()}
    assert _run(comp, tmp_path, reach=reach) == []


def test_tier_enum_is_parsed_from_the_shipped_documentation(payload):
    """The evaluator's expectation must come from the doc, not from a hardcoded guess."""
    tiers, err = static_eval.documented_tiers(payload)
    assert err is None, err
    assert "stage-lead" in tiers
    declared = set()
    for md in (payload / "agents").glob("*.md"):
        fm, _ = static_eval.frontmatter(md)
        if fm.get("tier"):
            declared.add(str(fm["tier"]))
    assert declared <= tiers, (
        f"agents declare undocumented tier(s): {sorted(declared - tiers)}"
    )


@pytest.mark.parametrize("bad", ["", "not a mapping", "- a\n- b"])
def test_frontmatter_reports_structural_problems(tmp_path, bad):
    p = tmp_path / "x.md"
    p.write_text(f"---\n{bad}\n---\n\nbody\n", encoding="utf-8")
    _fm, err = static_eval.frontmatter(p)
    assert err is not None
