"""Grade Tier A agent scenarios: selection, role adherence, working result, interoperation.

Two subcommands, deliberately split so the verdict cannot be tuned to the transcript:

  oracle  runs INSIDE Docker over each preserved workspace and records whether the project still
          works. This is the only thing allowed to answer criterion 3. The agent's own claim that
          it finished is not evidence, and neither is mine.
  grade   pure analysis of the transcript plus the oracle record.

What makes criterion 2 gradeable at all is that the stream carries `parent_tool_use_id`: every tool
call made by a subagent points back at the Agent call that created it, so a subagent's tools can be
separated from the main session's. Without that this tier would have had to concede role adherence.

THREE ROLE CLASSES, derived from the agent's own frontmatter and description rather than from a
list I maintain by hand:

  read-only    declares neither Write nor Edit. Success = a substantive verdict, and the agent
               itself mutated nothing. For a reviewer, touching the code IS the failure.
  test-author  mutating, and its own description is about tests. Success = it ADDED tests that
               collect. Whether those tests pass is not the bar: `pybug` ships a deliberate bug,
               so a test that fails against it is the agent succeeding.
  implementer  mutating, anything else. Success = it changed something without adding failures.

Two errors were made here before this settled, both the same shape -- an instrument that reports
the product broken whenever the product behaves correctly:

  * judging a test-author by whether the suite is green, which fails it for exposing the bug;
  * judging an agent by the WORKSPACE, when the main session has Write too. In the first wave the
    main session edited the fixture while the reviewer and the tester read only, and both were
    booked defects for staying in role. Criterion 3 is therefore attributed to the agent via its
    own tool calls, never to the session.

An agent that runs, stays in role and mutates nothing is `NO_CONTRIBUTION`, not a defect -- on a
fixture where its job does not apply, doing nothing is the correct answer, and summing that with
"did the wrong thing" would hide which actually happened.

The admissibility guard is asymmetric, as everywhere else in this harness (E-050, E-058): a session
that died or was cut off cannot support a NEGATIVE, but a spawn or a tool call that already happened
is not unmade by a later truncation.

Usage:
  tier_a_agents.py oracle --probe-dir <dir>
  tier_a_agents.py grade  --probe-dir <dir> [--json <out>]
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import shutil
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]


def run_dirs(probe_dir: pathlib.Path) -> list[pathlib.Path]:
    return sorted(p.parent for p in probe_dir.glob("*/probe.json"))


SCAFFOLD = (".claude/", ".claude", ".ck-selection.yaml", "CLAUDE.md", ".mcp.json")


def node_counts(ws: pathlib.Path) -> dict | None:
    """Same shape as the python side, for `node --test` fixtures. None if node is not here."""
    if not shutil.which("node"):
        return None
    run = subprocess.run(
        ["node", "--test", "test/"],
        cwd=ws,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=600,
    )
    tail = ((run.stdout or "") + (run.stderr or ""))[-2000:]
    m_p = re.search(r"^# pass (\d+)", tail, re.M)
    m_f = re.search(r"^# fail (\d+)", tail, re.M)
    passed = int(m_p.group(1)) if m_p else 0
    failed = int(m_f.group(1)) if m_f else 0
    return {
        # A node suite that cannot even be parsed reports neither counter.
        "collects": bool(m_p or m_f),
        "tests_failed": failed,
        "tests_passed": passed,
        "tests_total": failed + passed,
        "tests_tail": tail[-600:],
    }


def suite_counts(ws: pathlib.Path) -> dict | None:
    """Dispatch on what the fixture actually is. None means 'wrong container', never 'broken'."""
    if (ws / "package.json").is_file() and not (ws / "pyproject.toml").is_file():
        return node_counts(ws)
    return pytest_counts(ws)


def pytest_counts(ws: pathlib.Path) -> dict:
    """Collectability and pass/fail counts. Collectability is the real 'did you break it' signal."""
    col = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "--collect-only",
        ],
        cwd=ws,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=600,
    )
    run = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
        cwd=ws,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=600,
    )
    tail = (run.stdout or "")[-1500:]
    m_f = re.search(r"(\d+) failed", tail)
    m_p = re.search(r"(\d+) passed", tail)
    failed = int(m_f.group(1)) if m_f else 0
    passed = int(m_p.group(1)) if m_p else 0
    return {
        "collects": col.returncode == 0,
        "tests_failed": failed,
        "tests_passed": passed,
        "tests_total": failed + passed,
        "tests_tail": tail[-600:],
    }


def changed_paths(ws: pathlib.Path) -> list[str]:
    g = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ws,
        capture_output=True,
        text=True,
        errors="replace",
    )
    out = []
    for ln in (g.stdout or "").splitlines():
        if not ln.strip():
            continue
        path = ln[3:].strip().strip('"')
        if path.startswith(SCAFFOLD):
            continue  # the kit's own install is not the agent's work
        out.append(ln)
    return out


def oracle(probe_dir: pathlib.Path) -> int:
    """Record what the workspace became, RELATIVE to the pristine fixture. Docker only.

    Absolute pass/fail is the wrong bar and the first version proved it: `pybug` ships a deliberate
    bug, so `unit-tester` writing tests that EXPOSE that bug came back as a failing suite and would
    have been booked a defect for doing its job correctly. An agent whose purpose is to find
    problems must not be scored by whether problems remain.

    So the oracle records counts and the grader compares them against the untouched fixture. What
    stays absolute is COLLECTABILITY: an agent that leaves the suite unimportable broke the project
    no matter what its job was.
    """
    if not pathlib.Path("/.dockerenv").exists():
        print("refusing to run project code outside Docker", file=sys.stderr)
        return 2

    baselines: dict[str, dict] = {}
    for d in run_dirs(probe_dir):
        ws = d / "workspace"
        rec: dict = {"workspace_present": ws.is_dir()}
        if ws.is_dir():
            probe = json.loads((d / "probe.json").read_text(encoding="utf-8"))
            fx = probe.get("fixture") or ""
            if fx and fx not in baselines:
                src = REPO / "tests/evals/e2e/fixtures" / fx
                if src.is_dir():
                    tmp = probe_dir / f".baseline-{fx}"
                    if not tmp.is_dir():
                        shutil.copytree(src, tmp)
                    b = suite_counts(tmp)
                    if b is not None:
                        baselines[fx] = b
            counts = suite_counts(ws)
            if counts is None:
                # This container cannot run this fixture's suite. Recording a verdict anyway would
                # be a fabricated one, and OVERWRITING a good record from the right container would
                # be worse. Leave whatever is already there alone.
                print(f"{d.name}: skipped -- wrong container for this fixture")
                continue
            rec["baseline"] = baselines.get(fx)
            rec.update(counts)
            ch = changed_paths(ws)
            rec["changed_paths"] = ch[:50]
            rec["changed_count"] = len(ch)
            rec["test_files_touched"] = sum(1 for x in ch if "test" in x.lower())
        (d / "oracle.json").write_text(
            json.dumps(rec, indent=2) + "\n", encoding="utf-8"
        )
        print(
            f"{d.name}: collects={rec.get('collects')} "
            f"total={rec.get('tests_total')} failed={rec.get('tests_failed')} "
            f"changed={rec.get('changed_count')}"
        )
    return 0


def subagent_tools(jsonl: pathlib.Path) -> tuple[dict[str, list[str]], list[str]]:
    """Split tool calls into per-subagent and main-session, via parent_tool_use_id."""
    agent_of: dict[str, str] = {}
    per: dict[str, list[str]] = {}
    main: list[str] = []
    for line in jsonl.open(encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") != "assistant":
            continue
        parent = ev.get("parent_tool_use_id")
        for b in (ev.get("message") or {}).get("content") or []:
            if b.get("type") != "tool_use":
                continue
            name = b.get("name", "")
            if name == "Agent":
                agent_of[b.get("id", "")] = (b.get("input") or {}).get(
                    "subagent_type", "<unspecified>"
                )
            if parent:
                per.setdefault(parent, []).append(name)
            else:
                main.append(name)
    named = {agent_of.get(k, f"<unmapped:{k[:10]}>"): v for k, v in per.items()}
    return named, main


def final_result(jsonl: pathlib.Path) -> tuple[str, str]:
    last, subtype = "", ""
    for line in jsonl.open(encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "result":
            if isinstance(ev.get("result"), str):
                last = ev["result"]
            if isinstance(
                ev.get("subtype"), str
            ):  # absent-ok: "" branches nowhere, it only annotates
                subtype = ev["subtype"]
    return last, subtype


def grade_one(d: pathlib.Path) -> dict:
    probe = json.loads((d / "probe.json").read_text(encoding="utf-8"))
    agent = probe["agent"]
    declared = probe.get("declared_tools") or []
    mutating = any(t in declared for t in ("Write", "Edit"))
    # Role is derived from the agent's OWN frontmatter and description, never from a list I keep by
    # hand -- the same anti-tuning discipline the prompt derivation uses.
    # Keyed on the agent's NAME, not its description. Matching the description on /test/ swept in
    # every implementer that merely mentions testing as part of its remit -- `senior-backend-dev`
    # fixed the fixture's bug (2 failures to 0) and was booked a defect for not adding tests it was
    # never asked for. The name is the component's own declaration of what it is.
    if not mutating:
        role = "read-only"
    elif re.search(r"(^|-)(unit-)?test(er)?$|(^|-)qa$", agent, re.I):
        role = "test-author"
    else:
        role = "implementer"
    answer, subtype = final_result(d / "session.jsonl")
    per, main = subagent_tools(d / "session.jsonl")
    spawned = probe.get("agents_spawned") or []
    selected = agent in spawned

    row: dict = {
        "agent": agent,
        "run": d.name,
        "class": "mutating" if mutating else "read-only",
        "session_rc": probe.get("session_rc"),
        "result_subtype": subtype,
        "spawned": spawned,
    }

    # Asymmetric admissibility: a broken session cannot support a negative, but a spawn that
    # happened, happened.
    broken = probe.get("session_rc") != 0 or not answer.strip()
    if broken and not selected:
        row["outcome"] = "UNRUN"
        row["detail"] = (
            f"session unusable ({subtype or 'no result'}); silence proves nothing"
        )
        return row

    # criterion 1 -- selection, with the agent's name withheld from the prompt
    row["c1_selected"] = selected
    row["c1_substituted"] = sorted(set(spawned) - {agent}) if not selected else []

    # criterion 2 -- role adherence, only gradeable if the agent ran and used tools
    used = sorted(set(per.get(agent, [])))
    row["subagent_tools"] = used
    row["declared_tools"] = declared
    if not selected or not used:
        row["c2_in_role"] = None
        row["c2_note"] = (
            "not gradeable: agent did not run, or made no tool call of its own"
        )
    else:
        # Task* and Skill are harness affordances every agent gets; they are not a role breach.
        allowed = set(declared) | {
            "Skill",
            "TaskCreate",
            "TaskList",
            "TaskUpdate",
            "TaskGet",
        }
        breach = [t for t in used if t not in allowed]
        row["c2_in_role"] = not breach
        row["c2_breach"] = breach

    # criterion 3 -- the workspace, judged by the Docker oracle and nothing else
    op = d / "oracle.json"
    if not op.is_file():
        row["c3_working"] = None
        row["c3_note"] = "no oracle record; criterion 3 not measured"
    else:
        orc = json.loads(op.read_text(encoding="utf-8"))
        base = orc.get("baseline") or {}
        changed = orc.get("changed_count", 0)
        collects = orc.get("collects")
        row["changed_count"] = changed
        row["collects"] = collects
        row["tests_total"] = orc.get("tests_total")
        row["tests_failed"] = orc.get("tests_failed")
        row["baseline_total"] = base.get("tests_total")
        row["baseline_failed"] = base.get("tests_failed")
        row["role"] = role
        # Attribute work to the AGENT, not to the session. The main session has Write too, and in
        # the first wave it was the main session that edited the fixture while the reviewer and the
        # tester read only. Judging the agent by the workspace booked both as defects for behaving
        # correctly -- the same shape of error as scoring a test-author by whether tests pass.
        mutators = {"Write", "Edit", "NotebookEdit"}
        attempted = bool(set(used) & mutators)
        # ATTEMPTED is not EFFECTIVE. `senior-frontend-dev` issued an Edit that left the workspace
        # byte-identical; scoring that as "mutated, and the mutation was bad" invented a defect out
        # of an agent that simply did not deliver on an underspecified request. No trace means no
        # contribution (E-047), which is a different event from doing the wrong thing.
        agent_mutated = attempted and changed > 0
        row["mutation_attempted"] = attempted
        row["agent_mutated"] = agent_mutated
        if not base:
            row["c3_working"] = None
            row["c3_note"] = (
                "no fixture baseline; a delta cannot be computed and will not be faked"
            )
        elif role == "read-only":
            # For a reviewer, touching the code IS the failure -- but only ITS touching.
            row["c3_working"] = len(answer.strip()) >= 200 and not agent_mutated
            row["c3_note"] = (
                "read-only: substantive verdict, agent itself mutated nothing"
            )
        elif not collects:
            row["c3_working"] = False
            row["c3_note"] = (
                "left the suite uncollectable -- broke the project whatever the job"
            )
        elif not agent_mutated:
            # The agent ran, stayed in role, and produced nothing the workspace can show. That is
            # not the same event as doing the wrong thing, and summing them into one "defect" count
            # would hide which of the two actually happened.
            row["c3_working"] = None
            row["c3_note"] = (
                "agent made no mutating call; on this fixture its job may not apply -- "
                "recorded as no contribution rather than as a defect"
            )
            row["no_contribution"] = True
        elif role == "test-author":
            # Writing a test that FAILS against a known-buggy fixture is success, not failure.
            row["c3_working"] = (
                orc.get("tests_total", 0) > base.get("tests_total", 0)
                and orc.get("test_files_touched", 0) > 0
            )
            row["c3_note"] = (
                "test-author: added tests that collect; their failing is not a defect"
            )
        else:
            row["c3_working"] = changed > 0 and orc.get("tests_failed", 0) <= base.get(
                "tests_failed", 0
            )
            row["c3_note"] = "implementer: changed something without adding failures"

    # criterion 5 -- degraded to intent, because bash is inspection-only on the host
    row["c5_attempted_verification"] = bool(probe.get("attempted_verification"))

    # criterion 12 -- did anything else in the kit participate?
    others = sorted(set(spawned) - {agent})
    skills = [t for t in main if t == "Skill"]
    row["c12_interop"] = bool(others) or bool(skills) or len(spawned) > 1
    row["c12_note"] = (
        f"other agents={others}; skill calls in main session={len(skills)}"
    )

    graded = [row.get(k) for k in ("c1_selected", "c2_in_role", "c3_working")]
    if row.get("c1_selected") is False:
        # A sibling taking the work is not the same event as nobody taking it (Tier B learned this
        # the expensive way), so the two are never summed.
        row["outcome"] = "SUBSTITUTED" if row.get("c1_substituted") else "NOT_SELECTED"
    elif any(v is False for v in graded):
        row["outcome"] = "DEFECT"
    elif row.get("no_contribution"):
        row["outcome"] = "NO_CONTRIBUTION"
    elif any(v is None for v in graded):
        row["outcome"] = "PARTIAL"
    else:
        row["outcome"] = "PASS"
    return row


RANK = [
    "PASS",
    "PARTIAL",
    "NO_CONTRIBUTION",
    "DEFECT",
    "SUBSTITUTED",
    "NOT_SELECTED",
    "UNRUN",
]


def grade(probe_dir: pathlib.Path, out: str) -> int:
    rows = [grade_one(d) for d in run_dirs(probe_dir)]
    per: dict[str, list[dict]] = {}
    for r in rows:
        per.setdefault(r["agent"], []).append(r)

    summary = []
    for agent, runs in sorted(per.items()):
        adm = [r for r in runs if r["outcome"] != "UNRUN"]
        best = min((r["outcome"] for r in adm), key=RANK.index) if adm else "UNRUN"
        summary.append(
            {
                "agent": agent,
                "outcome": best,
                "runs": len(runs),
                "admissible": len(adm),
                "selected_runs": sum(1 for r in adm if r.get("c1_selected")),
                "detail": runs,
            }
        )
        print(
            "%-26s %-13s admissible=%d/%d selected=%d/%d"
            % (
                agent,
                best,
                len(adm),
                len(runs),
                sum(1 for r in adm if r.get("c1_selected")),
                len(adm),
            )
        )
    tally: dict[str, int] = {}
    for s in summary:
        tally[s["outcome"]] = tally.get(s["outcome"], 0) + 1
    print("\n" + json.dumps(tally, sort_keys=True))
    target = pathlib.Path(out) if out else probe_dir / "grades-agents.json"
    target.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    o = sub.add_parser("oracle")
    o.add_argument("--probe-dir", required=True)
    g = sub.add_parser("grade")
    g.add_argument("--probe-dir", required=True)
    g.add_argument("--json", default="")
    a = ap.parse_args()
    if a.cmd == "oracle":
        return oracle(pathlib.Path(a.probe_dir))
    return grade(pathlib.Path(a.probe_dir), a.json)


if __name__ == "__main__":
    raise SystemExit(main())
