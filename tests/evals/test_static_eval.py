"""Negative controls for the static evaluator.

A checker that cannot fail reports CLEAN on a broken payload, which is worse than no checker at
all — the same false-verdict class as a test command whose exit status is masked by a pipe. Each
check therefore gets a synthetic component built to violate exactly it, and must fire.
"""

from __future__ import annotations

import importlib.util
import json
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


# --- negative controls: the catalog-derived check families ---------------------------------------
#
# Batch 3 evaluated 30 components and returned one finding. That is only good news if each check
# can fail; otherwise it is a false CLEAN over 29 components.


def _catalog(tmp_path: Path, name: str, text: str) -> Path:
    d = tmp_path / "catalog"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(text, encoding="utf-8")
    return d / name


def test_capture_mode_absent_from_the_catalog_is_flagged(tmp_path):
    _catalog(
        tmp_path,
        "capture.yaml",
        "version: 1\ndefault: 'off'\nmodes:\n  'off': {label: x}\n",
    )
    comp = {
        "id": "capture-mode:ghost",
        "type": "capture-mode",
        "path": "catalog/capture.yaml",
    }
    assert _checks(static_eval.check_capture_mode(comp, tmp_path, set())) == {
        "mode_exists"
    }


def test_capture_mode_naming_an_unknown_hook_is_flagged(tmp_path):
    _catalog(
        tmp_path,
        "capture.yaml",
        "version: 1\ndefault: 'off'\nmodes:\n  m: {label: L, hooks: [no-such-hook]}\n",
    )
    comp = {
        "id": "capture-mode:m",
        "type": "capture-mode",
        "path": "catalog/capture.yaml",
    }
    assert "hook_exists" in _checks(
        static_eval.check_capture_mode(comp, tmp_path, {"real"})
    )


def test_a_default_capture_mode_that_installs_hooks_is_a_consent_regression(tmp_path):
    """0.76.0 made background capture opt-in; a default that installs hooks silently undoes it."""
    _catalog(
        tmp_path,
        "capture.yaml",
        "version: 1\ndefault: m\nmodes:\n  m: {label: L, hooks: [capture-learnings]}\n",
    )
    comp = {
        "id": "capture-mode:m",
        "type": "capture-mode",
        "path": "catalog/capture.yaml",
    }
    findings = static_eval.check_capture_mode(comp, tmp_path, {"capture-learnings"})
    assert "consent_default" in _checks(findings)


def test_a_clean_capture_mode_produces_no_findings(tmp_path):
    _catalog(
        tmp_path,
        "capture.yaml",
        "version: 1\ndefault: 'off'\nmodes:\n  m: {label: L, hooks: [real]}\n",
    )
    comp = {
        "id": "capture-mode:m",
        "type": "capture-mode",
        "path": "catalog/capture.yaml",
    }
    assert static_eval.check_capture_mode(comp, tmp_path, {"real"}) == []


def test_unparseable_catalog_file_is_critical(tmp_path):
    _catalog(tmp_path, "x.yaml", "a: [1,\n  b: {\n")
    comp = {"id": "catalog-file:x", "type": "catalog-file", "path": "catalog/x.yaml"}
    assert _checks(static_eval.check_catalog_file(comp, tmp_path)) == {"parses"}


def test_unversioned_catalog_file_is_flagged(tmp_path):
    _catalog(tmp_path, "x.yaml", "stacks: {}\n")
    comp = {"id": "catalog-file:x", "type": "catalog-file", "path": "catalog/x.yaml"}
    assert "versioned" in _checks(static_eval.check_catalog_file(comp, tmp_path))


def test_a_clean_catalog_file_produces_no_findings(tmp_path):
    _catalog(tmp_path, "x.yaml", "version: 1\nstacks: {}\n")
    comp = {"id": "catalog-file:x", "type": "catalog-file", "path": "catalog/x.yaml"}
    assert static_eval.check_catalog_file(comp, tmp_path) == []


_ORG = """version: 1
teams:
  - {id: security, label: Security}
autonomy:
  levels:
    good: {label: G, policy: "may edit", hooks: [real]}
    nohook: {label: N, policy: "may edit", hooks: [ghost-hook]}
    nopolicy: {label: N, policy: "  ", hooks: []}
    nolabel: {policy: "may edit", hooks: []}
packs:
  - {id: good-pack, label: P, teams: [security]}
  - {id: bad-pack, label: P, teams: [not-a-team]}
"""


def _org_comp(dotted, ctype="autonomy-level"):
    return {"id": f"x:{dotted}", "type": ctype, "path": f"catalog/org.yaml::{dotted}"}


def test_org_entry_absent_at_its_declared_path_is_flagged(tmp_path):
    _catalog(tmp_path, "org.yaml", _ORG)
    findings = static_eval.check_org_entry(
        _org_comp("autonomy.levels.ghost"), tmp_path, {"real"}
    )
    assert _checks(findings) == {"entry_exists"}


def test_org_entry_naming_an_unknown_hook_is_flagged(tmp_path):
    _catalog(tmp_path, "org.yaml", _ORG)
    findings = static_eval.check_org_entry(
        _org_comp("autonomy.levels.nohook"), tmp_path, {"real"}
    )
    assert "hook_exists" in _checks(findings)


def test_an_autonomy_level_with_a_blank_policy_is_flagged(tmp_path):
    """The policy string is rendered into CLAUDE.md; blank means the project states no boundary."""
    _catalog(tmp_path, "org.yaml", _ORG)
    findings = static_eval.check_org_entry(
        _org_comp("autonomy.levels.nopolicy"), tmp_path, {"real"}
    )
    assert "policy" in _checks(findings)


def test_an_unlabelled_org_entry_is_flagged(tmp_path):
    _catalog(tmp_path, "org.yaml", _ORG)
    findings = static_eval.check_org_entry(
        _org_comp("autonomy.levels.nolabel"), tmp_path, {"real"}
    )
    assert "label" in _checks(findings)


def test_a_pack_referencing_an_undeclared_team_is_flagged(tmp_path):
    _catalog(tmp_path, "org.yaml", _ORG)
    findings = static_eval.check_org_entry(
        _org_comp("packs.bad-pack", "org-capability"), tmp_path, {"real"}
    )
    assert "team_exists" in _checks(findings)


def test_a_clean_org_entry_produces_no_findings(tmp_path):
    _catalog(tmp_path, "org.yaml", _ORG)
    assert (
        static_eval.check_org_entry(
            _org_comp("autonomy.levels.good"), tmp_path, {"real"}
        )
        == []
    )
    assert (
        static_eval.check_org_entry(
            _org_comp("packs.good-pack", "org-capability"), tmp_path, set()
        )
        == []
    )


def _schema(tmp_path, body: str):
    d = tmp_path / "schemas"
    d.mkdir(parents=True, exist_ok=True)
    (d / "s.schema.json").write_text(body, encoding="utf-8")
    (tmp_path / "src").mkdir(exist_ok=True)
    return {"id": "schema:s", "type": "schema", "path": "schemas/s.schema.json"}


def test_unparseable_schema_is_critical(tmp_path):
    comp = _schema(tmp_path, "{not json")
    assert _checks(static_eval.check_schema(comp, tmp_path)) == {"parses"}


def test_a_schema_no_source_file_references_is_flagged(tmp_path):
    comp = _schema(tmp_path, '{"$schema": "x", "type": "object"}')
    (tmp_path / "src" / "a.py").write_text("pass\n", encoding="utf-8")
    assert "referenced" in _checks(static_eval.check_schema(comp, tmp_path))


def test_a_schema_without_a_dialect_or_type_is_flagged(tmp_path):
    comp = _schema(tmp_path, "{}")
    (tmp_path / "src" / "a.py").write_text("s = 's.schema.json'\n", encoding="utf-8")
    assert _checks(static_eval.check_schema(comp, tmp_path)) == {"dialect", "typed"}


def test_a_clean_schema_produces_no_findings(tmp_path):
    comp = _schema(tmp_path, '{"$schema": "x", "type": "object"}')
    (tmp_path / "src" / "a.py").write_text("s = 's.schema.json'\n", encoding="utf-8")
    assert static_eval.check_schema(comp, tmp_path) == []


def _mod(tmp_path, body: str):
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "m.py").write_text(body, encoding="utf-8")
    return {"id": "module:m", "type": "workflow-upgrade", "path": "src/m.py"}


def _cov(**summary):
    base = {
        "num_statements": 10,
        "covered_lines": 10,
        "num_branches": 4,
        "covered_branches": 4,
    }
    base.update(summary)
    return {"files": {"src/m.py": {"summary": base}}}


def test_a_module_under_the_coverage_floor_is_flagged(tmp_path):
    comp = _mod(tmp_path, '"""Doc."""\n')
    findings = static_eval.check_module(comp, tmp_path, _cov(covered_lines=9))
    assert "coverage" in _checks(findings)


def test_a_module_with_untaken_branches_is_flagged(tmp_path):
    comp = _mod(tmp_path, '"""Doc."""\n')
    cov = _cov(covered_branches=1)
    cov["files"]["src/m.py"]["missing_branches"] = [[1, 2], [1, 3], [1, 4]]
    findings = static_eval.check_module(comp, tmp_path, cov)
    assert "branch_coverage" in _checks(findings)
    assert any("3 untaken" in f["detail"] for f in findings)


def test_a_branch_shortfall_without_an_arc_list_is_a_data_failure_not_a_pass(tmp_path):
    """Missing coverage DATA must never read as a clean verdict."""
    comp = _mod(tmp_path, '"""Doc."""\n')
    findings = static_eval.check_module(comp, tmp_path, _cov(covered_branches=1))
    assert [f["severity"] for f in findings if f["check"] == "coverage_data"] == [
        "high"
    ]


def test_an_undocumented_module_is_flagged(tmp_path):
    comp = _mod(tmp_path, "x = 1\n")
    assert "documented" in _checks(static_eval.check_module(comp, tmp_path, _cov()))


def test_a_clean_module_produces_no_findings(tmp_path):
    comp = _mod(tmp_path, '"""Doc."""\n')
    assert static_eval.check_module(comp, tmp_path, _cov()) == []


def test_a_gate_no_profile_installs_is_flagged(tmp_path, payload):
    comp = {
        "id": "gate:invented-gate",
        "type": "gate",
        "path": "catalog/profiles.yaml::gates",
    }
    findings = static_eval.check_gate(comp, payload, "", [])
    assert {"gate_installed", "gate_documented"} <= _checks(findings)


def test_a_gate_ordered_inconsistently_across_profiles_is_flagged(tmp_path, payload):
    comp = {
        "id": "gate:code-review",
        "type": "gate",
        "path": "catalog/profiles.yaml::gates",
    }
    conflicts = ["lean and standard disagree on code-review vs build-green"]
    findings = static_eval.check_gate(comp, payload, "code-review", conflicts)
    assert "gate_order" in _checks(findings)


def test_the_shipped_profiles_order_their_shared_gates_consistently(payload):
    """close_gate derives the expected next gate from this order; a disagreement means the same
    evidence closes in one profile and is rejected as out-of-order in another."""
    assert static_eval.gate_order_conflicts(payload) == []


def test_a_documented_installed_gate_produces_no_findings(payload):
    comp = {
        "id": "gate:code-review",
        "type": "gate",
        "path": "catalog/profiles.yaml::gates",
    }
    assert static_eval.check_gate(comp, payload, "code-review", []) == []


# --- negative controls: repo validation scripts --------------------------------------------------


def _repo_script(tmp_path: Path, name: str, body: str):
    d = tmp_path / "scripts"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(body, encoding="utf-8")
    return {
        "id": f"repo-script:{name}",
        "type": "repo-validation-script",
        "path": f"scripts/{name}",
    }


def test_a_guard_that_cannot_report_failure_is_flagged(tmp_path):
    """The defect this program exists to catch: a checker that is green on a broken payload."""
    comp = _repo_script(
        tmp_path, "c.py", '"""Guard."""\nimport sys\n\nprint("ok")\nsys.exit(0)\n'
    )
    findings = static_eval.check_repo_script(comp, tmp_path, "c.py")
    assert "can_fail" in _checks(findings)


def test_a_guard_with_a_nonzero_exit_is_not_flagged(tmp_path):
    comp = _repo_script(
        tmp_path, "c.py", '"""Guard."""\nimport sys\n\nsys.exit(1 if bad else 0)\n'
    )
    assert "can_fail" not in _checks(
        static_eval.check_repo_script(comp, tmp_path, "c.py")
    )


def test_a_guard_that_raises_is_not_flagged(tmp_path):
    comp = _repo_script(
        tmp_path, "c.py", '"""Guard."""\nif bad:\n    raise SystemExit("drift")\n'
    )
    assert "can_fail" not in _checks(
        static_eval.check_repo_script(comp, tmp_path, "c.py")
    )


def test_an_unreferenced_script_is_flagged_but_only_as_low(tmp_path):
    """Unreferenced is a real signal, but it does not distinguish a dead guard from a dead
    operator tool, so it must not carry the severity of a guard that silently never fires."""
    comp = _repo_script(tmp_path, "c.py", '"""Guard."""\nimport sys\n\nsys.exit(2)\n')
    findings = static_eval.check_repo_script(comp, tmp_path, "other.py")
    assert [f["severity"] for f in findings if f["check"] == "referenced"] == ["low"]


def test_a_script_referenced_only_from_shipped_docs_counts_as_referenced(tmp_path):
    """An operator tool is invoked by the document that tells you to run it."""
    comp = _repo_script(tmp_path, "c.py", '"""Tool."""\nimport sys\n\nsys.exit(2)\n')
    corpus = "Run `scripts/c.py` to bundle a run."
    assert "referenced" not in _checks(
        static_eval.check_repo_script(comp, tmp_path, corpus)
    )


def test_the_corpus_excludes_the_changelog(payload):
    """A changelog entry records that a script existed; it is not an instruction to run it.
    Including it would silence the dead-script case the check exists to surface."""
    corpus = static_eval.invocation_corpus(payload)
    changelog = (payload / "CHANGELOG.md").read_text(encoding="utf-8")
    marker = next(
        line for line in changelog.splitlines() if "backfill-releases" in line
    )
    assert marker not in corpus


def test_an_undocumented_script_is_flagged(tmp_path):
    comp = _repo_script(tmp_path, "c.py", "import sys\n\nsys.exit(2)\n")
    assert "documented" in _checks(
        static_eval.check_repo_script(comp, tmp_path, "c.py")
    )


def test_a_shell_script_without_a_shebang_is_flagged(tmp_path):
    comp = _repo_script(tmp_path, "c.sh", "echo hi\n")
    assert "shebang" in _checks(static_eval.check_repo_script(comp, tmp_path, "c.sh"))


def test_a_clean_repo_script_produces_no_findings(tmp_path):
    comp = _repo_script(tmp_path, "c.py", '"""Guard."""\nimport sys\n\nsys.exit(3)\n')
    assert static_eval.check_repo_script(comp, tmp_path, "run c.py here") == []


def test_the_invocation_corpus_sees_the_shipped_ci_workflows(payload):
    corpus = static_eval.invocation_corpus(payload)
    assert "gen_hooks.py" in corpus, "corpus missed a script CI demonstrably runs"


# --- negative controls: the coverage-justification mechanism -------------------------------------
#
# This mechanism decides which untaken branches stop blocking. If it cannot itself fail, it is a
# blanket exclusion wearing a justification's clothes.


_J = {"src/m.py::10->12": {"origin_line_text": "if rare:", "reason": "r", "proof": "p"}}


def test_an_unjustified_arc_is_reported():
    lines = ["x"] * 12
    lines[9] = "if rare:"
    un, ana, stale = static_eval.classify_arcs("src/m.py", [(3, 4)], lines, _J)
    assert un == [(3, 4)] and not ana and not stale


def test_a_justified_arc_is_honoured_only_while_its_line_matches():
    lines = ["x"] * 12
    lines[9] = "if rare:"
    un, ana, stale = static_eval.classify_arcs("src/m.py", [(10, 12)], lines, _J)
    assert ana == [(10, 12)] and not un and not stale


def test_a_shifted_line_makes_the_justification_stale_not_silently_reusable():
    """The failure this guards: the file moves, and one analysis starts excusing a new branch."""
    lines = ["x"] * 12
    lines[9] = "if something_completely_different:"
    un, ana, stale = static_eval.classify_arcs("src/m.py", [(10, 12)], lines, _J)
    assert not ana and not un
    assert stale and stale[0][0] == "src/m.py::10->12"


def test_a_justification_for_a_now_covered_arc_is_reported_as_orphaned():
    assert static_eval.orphan_justifications("src/m.py", [(3, 4)], _J) == [
        "src/m.py::10->12"
    ]
    assert static_eval.orphan_justifications("src/m.py", [(10, 12)], _J) == []


def test_check_module_reports_unjustified_arcs_as_medium(tmp_path):
    comp = _mod(tmp_path, '"""Doc."""\nif x:\n    pass\n')
    cov = _cov(covered_branches=3)
    cov["files"]["src/m.py"]["missing_branches"] = [[2, 3]]
    findings = static_eval.check_module(comp, tmp_path, cov)
    assert [f["severity"] for f in findings if f["check"] == "branch_coverage"] == [
        "medium"
    ]


def test_check_module_downgrades_an_arc_with_a_matching_justification(tmp_path):
    comp = _mod(tmp_path, '"""Doc."""\nif x:\n    pass\n')
    (tmp_path / "tests" / "evals").mkdir(parents=True)
    (tmp_path / "tests" / "evals" / "coverage-justifications.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "justifications": [
                    {
                        "file": "src/m.py",
                        "arc": "2->3",
                        "origin_line_text": "if x:",
                        "reason": "r",
                        "proof": "p",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    cov = _cov(covered_branches=3)
    cov["files"]["src/m.py"]["missing_branches"] = [[2, 3]]
    findings = static_eval.check_module(comp, tmp_path, cov)
    assert "branch_coverage" not in _checks(findings)
    assert [
        f["severity"] for f in findings if f["check"] == "analysed_unreachable"
    ] == ["cosmetic"]


def test_every_shipped_justification_still_matches_its_source_line(payload):
    """A justification that has drifted off its line excuses whatever now sits there."""
    justified = static_eval.load_justifications(payload)
    assert justified, "the shipped justification file is empty or unreadable"
    for key, j in justified.items():
        rel, _, arc = key.partition("::")
        origin = int(arc.split("->")[0])
        lines = (payload / rel).read_text(encoding="utf-8").splitlines()
        assert lines[origin - 1].strip() == j["origin_line_text"].strip(), key
        assert j.get("reason") and j.get("proof"), f"{key} carries no proof"


# --- negative controls: MCP fragments and behavioural documentation ------------------------------


_MCP = """version: 1
servers:
  good:
    label: Good
    config:
      type: stdio
      command: npx
      args: ["-y", "@scope/pkg@1.2.3"]
      env: {TOKEN: "${TOKEN}"}
  floating:
    label: Floating
    config: {type: stdio, command: npx, args: ["-y", "@scope/pkg@latest"]}
  leaky:
    label: Leaky
    config:
      type: stdio
      command: npx
      args: ["-y", "@scope/pkg@1.0.0"]
      env: {TOKEN: "ghp_realsecret"}
  badtype:
    label: Bad
    config: {type: carrier-pigeon}
  nourl:
    label: NoUrl
    config: {type: http}
"""


def _mcp_comp(sid):
    return {
        "id": f"mcp:{sid}",
        "type": "mcp-entry",
        "path": f"catalog/mcp.yaml::servers.{sid}",
    }


def _write_mcp(tmp_path, body=_MCP, notes=True):
    d = tmp_path / "catalog"
    d.mkdir(parents=True, exist_ok=True)
    if notes:
        body = body.replace(
            "    label: Good",
            "    label: Good\n    # toxic-flow legs: egress · private-data",
        )
    (d / "mcp.yaml").write_text(body, encoding="utf-8")


def test_an_unpinned_npx_package_is_flagged(tmp_path):
    """The catalog header forbids @latest: a fresh upstream release must not silently change what
    runs on a user's machine."""
    _write_mcp(tmp_path)
    assert "pinned" in _checks(
        static_eval.check_mcp_entry(_mcp_comp("floating"), tmp_path)
    )


def test_a_literal_credential_in_an_mcp_fragment_is_critical(tmp_path):
    _write_mcp(tmp_path)
    findings = static_eval.check_mcp_entry(_mcp_comp("leaky"), tmp_path)
    assert [f["severity"] for f in findings if f["check"] == "no_credentials"] == [
        "critical"
    ]


def test_a_restrictive_mode_switch_is_not_mistaken_for_a_credential(tmp_path):
    """READ_OPERATIONS_ONLY: "true" is the catalog's restrictive-by-default posture, not a secret.
    Flagging it would train the reader to ignore the check that actually matters."""
    body = (
        _MCP
        + """  switched:
    label: Switched
    config:
      type: stdio
      command: npx
      args: ["-y", "@scope/pkg@1.0.0"]
      env: {READ_OPERATIONS_ONLY: "true", REQUIRE_MUTATION_CONSENT: "true"}
"""
    )
    _write_mcp(tmp_path, body)
    findings = static_eval.check_mcp_entry(_mcp_comp("switched"), tmp_path)
    assert "no_credentials" not in _checks(findings)


def test_an_unknown_transport_is_flagged(tmp_path):
    _write_mcp(tmp_path)
    assert "transport" in _checks(
        static_eval.check_mcp_entry(_mcp_comp("badtype"), tmp_path)
    )


def test_an_http_server_without_a_url_is_flagged(tmp_path):
    _write_mcp(tmp_path)
    assert "url" in _checks(static_eval.check_mcp_entry(_mcp_comp("nourl"), tmp_path))


def test_a_missing_toxic_flow_note_is_flagged(tmp_path):
    _write_mcp(tmp_path, notes=False)
    assert "toxic_flow_note" in _checks(
        static_eval.check_mcp_entry(_mcp_comp("good"), tmp_path)
    )


def test_an_absent_mcp_entry_is_flagged(tmp_path):
    _write_mcp(tmp_path)
    assert _checks(static_eval.check_mcp_entry(_mcp_comp("ghost"), tmp_path)) == {
        "entry_exists"
    }


def test_a_clean_mcp_entry_produces_no_findings(tmp_path):
    _write_mcp(tmp_path)
    assert static_eval.check_mcp_entry(_mcp_comp("good"), tmp_path) == []


def test_every_shipped_mcp_entry_is_version_pinned_and_credential_free(payload):
    """The two invariants with real user consequences, asserted against the shipped catalog."""
    import yaml

    doc = yaml.safe_load((payload / "catalog" / "mcp.yaml").read_text(encoding="utf-8"))
    for sid in doc["servers"]:
        findings = static_eval.check_mcp_entry(_mcp_comp(sid), payload)
        blocking = [f for f in findings if f["check"] in ("pinned", "no_credentials")]
        assert not blocking, f"{sid}: {blocking}"


def _doc(tmp_path, body):
    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs" / "d.md").write_text(body, encoding="utf-8")
    return {"id": "doc:d", "type": "doc", "path": "docs/d.md"}


def test_a_document_showing_a_nonexistent_subcommand_is_flagged(tmp_path):
    comp = _doc(tmp_path, "Run `claude-kit teleport` to finish.\n")
    assert "cli_claims" in _checks(
        static_eval.check_doc(comp, tmp_path, {"init", "doctor"})
    )


def test_prose_mentioning_the_tool_name_is_not_read_as_a_command(tmp_path):
    """Restricting to code is what keeps this check usable; every doc says 'claude-kit' in prose."""
    comp = _doc(
        tmp_path,
        "The claude-kit configuration lives in .claude/, and claude-kit rules.\n",
    )
    assert "cli_claims" not in _checks(static_eval.check_doc(comp, tmp_path, {"init"}))


def test_a_document_naming_a_missing_repository_path_is_flagged(tmp_path):
    comp = _doc(tmp_path, "See `src/claude_kit/nope.py` for details.\n")
    assert "path_claims" in _checks(static_eval.check_doc(comp, tmp_path, set()))


def test_a_clean_document_produces_no_findings(tmp_path):
    comp = _doc(tmp_path, "Run `claude-kit doctor`. See `docs/d.md`.\n")
    assert static_eval.check_doc(comp, tmp_path, {"doctor"}) == []


def test_cli_commands_reads_the_real_registrations(payload):
    cmds = static_eval.cli_commands(payload)
    assert {"init", "validate", "doctor", "upgrade", "export"} <= cmds, sorted(cmds)


# --- negative controls: skill trigger quality ----------------------------------------------------


def _skill(tmp_path: Path, name: str, description: str, ctype: str = "skill"):
    d = tmp_path / "skills" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\nBody.\n",
        encoding="utf-8",
    )
    return {"id": f"{ctype}:{name}", "type": ctype, "path": f"skills/{name}/SKILL.md"}


def test_a_topic_only_skill_description_is_flagged(tmp_path):
    """A noun-phrase topic label with no condition — the one shape that is truly unselectable."""
    comp = _skill(tmp_path, "s", "Guidance about database indexing strategies.")
    assert "trigger" in _checks(static_eval.check_skill_trigger(comp, tmp_path))


def test_an_imperative_description_is_not_flagged(tmp_path):
    """ "Write unit tests for X" names the action; demanding "use when" would flag most of the
    shipped catalogue and teach the reader to skip the report."""
    comp = _skill(tmp_path, "s", "Write unit tests for frontend components and hooks.")
    assert static_eval.check_skill_trigger(comp, tmp_path) == []


def test_a_temporal_trigger_phrased_without_use_when_is_not_flagged(tmp_path):
    comp = _skill(
        tmp_path, "s", "Review a proposed test plan BEFORE tests are written."
    )
    assert static_eval.check_skill_trigger(comp, tmp_path) == []


def test_a_description_with_a_use_when_trigger_is_not_flagged(tmp_path):
    comp = _skill(
        tmp_path, "s", "Use when a query is slow and you suspect a missing index."
    )
    assert static_eval.check_skill_trigger(comp, tmp_path) == []


def test_a_description_with_a_when_you_trigger_is_not_flagged(tmp_path):
    comp = _skill(
        tmp_path, "s", "Index strategy help, when you are tuning a slow query."
    )
    assert static_eval.check_skill_trigger(comp, tmp_path) == []


def test_the_trigger_check_ignores_non_skills(tmp_path):
    """Agents are dispatched by name and tier, not selected from a picker by description."""
    comp = _agent(tmp_path, "a", "name: a\ndescription: Reviews code.\ntier: review")
    assert static_eval.check_skill_trigger(comp, tmp_path) == []


def test_the_trigger_check_does_not_double_report_a_broken_description(tmp_path):
    """A missing description is the frontmatter check's finding; reporting it twice inflates it."""
    comp = _skill(tmp_path, "s", "")
    assert static_eval.check_skill_trigger(comp, tmp_path) == []
