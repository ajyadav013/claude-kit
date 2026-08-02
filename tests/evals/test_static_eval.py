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


# --- negative controls: hooks, hook scripts, callables -------------------------------------------
#
# These patch attributes on the real claude_kit.hooks module rather than swapping sys.modules:
# `from claude_kit import hooks` resolves the already-imported submodule as a package attribute,
# so a sys.modules substitution would be silently ignored and every control would pass vacuously.


def _hook_module(monkeypatch, registry=None, plugin_only=None):
    from claude_kit import hooks as hooks_mod

    monkeypatch.setattr(
        hooks_mod, "HOOK_REGISTRY", registry if registry is not None else {}
    )
    monkeypatch.setattr(
        hooks_mod, "PLUGIN_ONLY_HOOKS", plugin_only if plugin_only is not None else {}
    )
    return hooks_mod


def _script(
    tmp_path: Path, name: str, body: str = "#!/usr/bin/env sh\necho hi\n", mode=0o755
):
    d = tmp_path / "hooks" / "scripts"
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text(body, encoding="utf-8")
    p.chmod(mode)
    return p


def _hook_comp(hid):
    return {
        "id": f"hook:{hid}",
        "type": "hook",
        "path": f"hooks/scripts/{hid}.sh",
        "risk": "high",
    }


def test_unregistered_hook_is_flagged(tmp_path, monkeypatch):
    _hook_module(monkeypatch)
    findings = static_eval.check_hook(_hook_comp("ghost"), tmp_path, set())
    assert _checks(findings) == {"hook_registered"}


def test_hook_with_an_unknown_event_is_flagged(tmp_path, monkeypatch):
    _script(tmp_path, "h.sh")
    reg = {
        "h": {"event": "NotAnEvent", "script": "h.sh", "data_access": "reads nothing"}
    }
    _hook_module(monkeypatch, reg)
    assert "hook_event" in _checks(
        static_eval.check_hook(_hook_comp("h"), tmp_path, {"h"})
    )


def test_hook_pointing_at_a_missing_script_is_critical(tmp_path, monkeypatch):
    reg = {"h": {"event": "SessionStart", "script": "gone.sh", "data_access": "x"}}
    _hook_module(monkeypatch, reg)
    findings = static_eval.check_hook(_hook_comp("h"), tmp_path, {"h"})
    assert any(
        f["check"] == "hook_script_exists" and f["severity"] == "critical"
        for f in findings
    )


def test_hook_without_a_data_access_note_is_flagged(tmp_path, monkeypatch):
    """privacy-report derives its informed-consent output from this field."""
    _script(tmp_path, "h.sh")
    reg = {"h": {"event": "SessionStart", "script": "h.sh", "data_access": "  "}}
    _hook_module(monkeypatch, reg)
    assert "hook_data_access" in _checks(
        static_eval.check_hook(_hook_comp("h"), tmp_path, {"h"})
    )


def test_a_clean_registry_entry_produces_no_findings(tmp_path, monkeypatch):
    _script(tmp_path, "h.sh")
    reg = {
        "h": {
            "event": "SessionStart",
            "script": "h.sh",
            "data_access": "reads CONTINUITY.md",
        }
    }
    _hook_module(monkeypatch, reg)
    assert static_eval.check_hook(_hook_comp("h"), tmp_path, {"h"}) == []


def test_a_plugin_only_hook_is_registered_and_reachable(tmp_path, payload, monkeypatch):
    """PLUGIN_ONLY_HOOKS are absent from every profile by design — not orphans.

    Reported guard-kubectl-delete as unreachable before the reach set included that channel.
    """
    _script(tmp_path, "h.sh")
    spec = {
        "event": "PreToolUse",
        "script": "h.sh",
        "data_access": "x",
        "reason": "plugin only",
    }
    _hook_module(monkeypatch, {}, {"h": spec})
    assert static_eval.check_hook(_hook_comp("h"), tmp_path, {"h"}) == []
    ids, scripts = static_eval.hook_reach_set(payload)
    assert "h" in ids and "h.sh" in scripts


def test_every_plugin_only_hook_is_reachable_in_the_shipped_payload(payload):
    from claude_kit import hooks as hooks_mod

    ids, _ = static_eval.hook_reach_set(payload)
    assert set(hooks_mod.PLUGIN_ONLY_HOOKS) <= ids


def _script_comp():
    return {
        "id": "hook-script:h.sh",
        "type": "hook-script",
        "path": "hooks/scripts/h.sh",
    }


def test_non_executable_hook_script_is_low_not_high(tmp_path):
    """Both channels run `bash <script>`, so the guard still fires — HIGH would overstate it."""
    _script(tmp_path, "h.sh", mode=0o644)
    findings = static_eval.check_hook_script(_script_comp(), tmp_path, {"h.sh"})
    assert [f["severity"] for f in findings if f["check"] == "executable"] == ["low"]


def test_hook_script_without_a_shebang_is_flagged(tmp_path):
    _script(tmp_path, "h.sh", body="echo hi\n")
    assert "shebang" in _checks(
        static_eval.check_hook_script(_script_comp(), tmp_path, {"h.sh"})
    )


def test_hook_script_using_jq_without_a_probe_is_flagged(tmp_path):
    _script(tmp_path, "h.sh", body="#!/usr/bin/env sh\ninput=$(jq -r .tool_input)\n")
    findings = static_eval.check_hook_script(_script_comp(), tmp_path, {"h.sh"})
    assert "tool_degradation" in _checks(findings)


def test_hook_script_probing_for_jq_is_not_flagged(tmp_path):
    body = "#!/usr/bin/env sh\ncommand -v jq >/dev/null 2>&1 || exit 0\njq -r .x\n"
    _script(tmp_path, "h.sh", body=body)
    findings = static_eval.check_hook_script(_script_comp(), tmp_path, {"h.sh"})
    assert "tool_degradation" not in _checks(findings)


def test_orphan_hook_script_is_flagged(tmp_path):
    _script(tmp_path, "h.sh")
    assert "orphan" in _checks(
        static_eval.check_hook_script(_script_comp(), tmp_path, set())
    )


def test_a_clean_hook_script_produces_no_findings(tmp_path):
    _script(tmp_path, "h.sh")
    assert static_eval.check_hook_script(_script_comp(), tmp_path, {"h.sh"}) == []


def _module(tmp_path, body: str):
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "m.py").write_text(body, encoding="utf-8")
    return {
        "id": "cli:x",
        "type": "cli-command",
        "path": "src/m.py::do_thing",
        "risk": "high",
    }


def test_missing_module_is_critical(tmp_path):
    comp = {"id": "cli:x", "type": "cli-command", "path": "src/gone.py::do_thing"}
    assert _checks(static_eval.check_callable(comp, tmp_path, {})) == {"exists"}


def test_missing_symbol_is_flagged(tmp_path):
    comp = _module(tmp_path, "def other():\n    return 1\n")
    assert _checks(static_eval.check_callable(comp, tmp_path, {})) == {"symbol_exists"}


def test_undocumented_callable_is_flagged(tmp_path):
    comp = _module(tmp_path, "def do_thing():\n    return 1\n")
    cov = {"files": {"src/m.py": {"missing_lines": []}}}
    assert "documented" in _checks(static_eval.check_callable(comp, tmp_path, cov))


def test_absent_coverage_record_is_reported_rather_than_assumed_clean(tmp_path):
    comp = _module(tmp_path, 'def do_thing():\n    """Doc."""\n    return 1\n')
    assert _checks(static_eval.check_callable(comp, tmp_path, {"files": {}})) == {
        "coverage_data"
    }


def test_uncovered_lines_inside_a_callable_are_flagged(tmp_path):
    comp = _module(tmp_path, 'def do_thing():\n    """Doc."""\n    return 1\n')
    cov = {"files": {"src/m.py": {"missing_lines": [3]}}}
    findings = static_eval.check_callable(comp, tmp_path, cov)
    assert "coverage" in _checks(findings)
    assert any("src/m.py:3" in f["detail"] for f in findings)


def test_uncovered_lines_outside_the_callable_are_ignored(tmp_path):
    src = 'def do_thing():\n    """Doc."""\n    return 1\n\n\ndef other():\n    return 2\n'
    comp = _module(tmp_path, src)
    cov = {"files": {"src/m.py": {"missing_lines": [7]}}}
    assert static_eval.check_callable(comp, tmp_path, cov) == []
