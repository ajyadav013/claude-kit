#!/usr/bin/env python3
"""Deterministic static evaluation of shipped claude-kit components.

Runs inside Docker (the self-evaluation program's execution plane) over a bounded slice of the
component manifest and emits one machine-readable record per component.

The checks here deliberately do **not** duplicate CI. ``scripts/check_*.py`` and the pytest suite
already pin frontmatter fences, description lengths, rule sizes, cross-references, and version
parity; re-running them would produce green lines that prove nothing new. What is checked instead
are the contracts a component *advertises* and nothing currently verifies:

- **Role vs. capability.** An agent whose description promises "Read-only" or "Reports only" must
  not be granted a mutating tool. This is a permission boundary stated in prose and enforced
  nowhere — the exact shape of gap the program exists to find.
- **Identity.** ``name:`` must equal the filename/dirname, because that is the id the plugin
  registry, the catalog, and every prose reference use interchangeably.
- **Tier.** Every agent carries a ``tier:`` (CLAUDE.md); an unknown or missing tier silently drops
  the agent out of tier-driven routing.
- **Reachability.** A component no profile resolves to is shipped but unreachable — dead payload
  that still costs review effort and context budget.
- **Declared tools exist.** A typo'd tool name is accepted by the loader and simply never granted.

Every finding carries the component id, the file, and enough detail to act on. Nothing is mutated.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

# Tool names Claude Code grants to a subagent. A name outside this set is silently ignored at load
# time, so the agent quietly runs without the capability its prose assumes.
KNOWN_TOOLS = frozenset(
    {
        "Agent",
        "Bash",
        "Edit",
        "Glob",
        "Grep",
        "Read",
        "Write",
        "NotebookEdit",
        "WebFetch",
        "WebSearch",
        "TaskCreate",
        "TaskGet",
        "TaskList",
        "TaskUpdate",
        "SendMessage",
        "Skill",
        "AskUserQuestion",
        "ExitPlanMode",
        "LSP",
        "TodoWrite",
        "KillShell",
        "BashOutput",
        "NotebookRead",
        "LS",
        "SlashCommand",
    }
)
#: Tools that can change the working tree.
MUTATING_TOOLS = frozenset({"Write", "Edit", "NotebookEdit", "MultiEdit"})
#: The agent tier enum is PARSED from its documentation, never hardcoded here. A hardcoded guess
#: produced two false "unknown tier" findings against `stage-lead`, which is perfectly valid — a
#: checker that invents its own expectations manufactures defects instead of finding them. Parsing
#: also turns this into a real drift guard: doc and payload must agree.
TIER_DOC = "docs/agents.md"
_TIER_LINE = re.compile(r"carries a `tier:`\s*\(([^)]+)\)")
#: Unqualified read-only promises. "Never writes code" is deliberately absent: an orchestrator that
#: writes state files while writing no application code is consistent, not contradictory.
READ_ONLY_CLAIMS = (
    "read-only",
    "reports only",
    "never edits code",
    "never edits any file",
    "produces audit reports",
)

_FENCE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
_RULE_REF = re.compile(r"\.claude/rules/([a-z0-9][a-z0-9-]*\.md)")


def frontmatter(path: Path) -> tuple[dict[str, Any], str | None]:
    """Return ``(mapping, error)`` for a markdown file's frontmatter block."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return {}, f"unreadable: {exc}"
    match = _FENCE.match(text)
    if not match:
        return {}, "no frontmatter block"
    try:
        data = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        # The known trap: `description: Foo: bar` is invalid YAML mid-scalar, and a lenient reader
        # hides it. Claude Code's own reader is lenient, so this is a WARN, not a FAIL.
        return {}, f"frontmatter is not valid YAML ({' '.join(str(exc).split())[:120]})"
    if not isinstance(data, dict):
        return {}, "frontmatter is not a mapping"
    return data, None


def tool_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [t.strip() for t in value.split(",") if t.strip()]
    if isinstance(value, list):
        return [str(t).strip() for t in value if str(t).strip()]
    return []


def documented_tiers(payload: Path) -> tuple[set[str], str | None]:
    """Return ``(tiers, error)`` parsed from the tier documentation — the single source of truth."""
    doc = payload / TIER_DOC
    if not doc.is_file():
        return (
            set(),
            f"{TIER_DOC} is missing — cannot verify agent tiers against a documented set",
        )
    match = _TIER_LINE.search(doc.read_text(encoding="utf-8"))
    if not match:
        return (
            set(),
            f"{TIER_DOC} no longer documents the tier enum in a parseable form",
        )
    return {
        t.strip(" `") for t in match.group(1).split("\u00b7") if t.strip(" `")
    }, None


def reachable_sets(payload: Path) -> dict[str, set[str]]:
    """Union of agents/skills/hooks every profile resolves to (the reachable payload)."""
    from claude_kit import catalog

    profiles = catalog._load(payload, "profiles.yaml")
    avail = catalog.available(payload)
    out: dict[str, set[str]] = {"agents": set(), "skills": set(), "hooks": set()}
    for name in profiles.get("profiles", {}):
        res = catalog._resolve_profile(profiles, name, avail)
        for key in out:
            out[key] |= set(res.get(key, []))
    return out


def check_prose_component(
    comp: dict[str, Any],
    payload: Path,
    reach: dict[str, set[str]],
    rule_files: set[str],
    tiers: set[str],
) -> list[dict[str, str]]:
    """Static checks for an agent / skill / rule component. Returns a list of findings."""
    findings: list[dict[str, str]] = []
    ctype = comp["type"]
    path = payload / comp["path"]

    def add(severity: str, check: str, detail: str) -> None:
        findings.append({"severity": severity, "check": check, "detail": detail})

    if not path.exists():
        add("critical", "exists", f"declared path is absent: {comp['path']}")
        return findings

    if ctype in ("rule", "org-rule", "overlay-rule"):
        text = path.read_text(encoding="utf-8")
        body = _FENCE.sub("", text, count=1)
        if not re.search(r"^# .+", body, re.MULTILINE):
            add("low", "rule_h1", "no H1 heading — renders without a title in exports")
        for ref in set(_RULE_REF.findall(text)):
            if ref not in rule_files:
                add(
                    "medium",
                    "rule_ref",
                    f"references .claude/rules/{ref}, which is not shipped",
                )
        return findings

    fm, err = frontmatter(path)
    if err:
        sev = "medium" if "not valid YAML" in err else "high"
        add(sev, "frontmatter", err)
        if not fm:
            return findings

    expected = path.parent.name if path.name == "SKILL.md" else path.stem
    name = str(fm.get("name", ""))
    if not name:
        add("high", "name", "no name: field")
    elif name != expected:
        add("high", "name_matches_path", f"name {name!r} != path identity {expected!r}")

    description = str(fm.get("description", ""))
    if not description:
        add(
            "high",
            "description",
            "no description: field — the agent/skill cannot be routed to",
        )

    if ctype in ("agent", "overlay-agent", "org-agent"):
        tier = fm.get("tier")
        if tier is None:
            add(
                "medium",
                "tier",
                "no tier: field (CLAUDE.md requires one on every agent)",
            )
        elif tiers and tier not in tiers:
            add(
                "medium",
                "tier",
                f"tier {tier!r} is not one of the documented tiers {sorted(tiers)} "
                f"({TIER_DOC}) — drift between the payload and its documentation",
            )

        tools = tool_list(fm.get("tools"))
        unknown = [t for t in tools if t not in KNOWN_TOOLS]
        if unknown:
            add(
                "medium",
                "tools_known",
                f"declares tool(s) Claude Code will not grant: {', '.join(unknown)}",
            )
        blob = f"{description}\n{fm.get('role', '')}".lower()
        claim = next((c for c in READ_ONLY_CLAIMS if c in blob), None)
        mutating = sorted(set(tools) & MUTATING_TOOLS)
        if claim and mutating:
            add(
                "high",
                "role_vs_tools",
                f"promises {claim!r} but is granted {', '.join(mutating)} — the stated "
                "permission boundary is not enforced by its tool grant",
            )

    key = "skills" if ctype == "skill" else "agents"
    if ctype in ("agent", "skill") and expected not in reach[key]:
        add(
            "low",
            "reachability",
            f"no profile resolves to this {ctype} — shipped but unreachable via a profile",
        )
    return findings


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--payload", default="/repo")
    ap.add_argument("--out", required=True)
    ap.add_argument(
        "--ids", required=True, help="comma-separated component ids, or @file"
    )
    args = ap.parse_args()

    payload = Path(args.payload)
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    by_id = {c["id"]: c for c in manifest["components"]}

    raw = args.ids
    if raw.startswith("@"):
        raw = Path(raw[1:]).read_text(encoding="utf-8")
    ids = [i.strip() for i in raw.replace("\n", ",").split(",") if i.strip()]
    missing = [i for i in ids if i not in by_id]
    if missing:
        print(f"unknown component id(s): {', '.join(missing)}", file=sys.stderr)
        return 2

    tiers, tier_err = documented_tiers(payload)
    if tier_err:
        print(f"  [high    ] {TIER_DOC:<40} tier_doc: {tier_err}")
    reach = reachable_sets(payload)
    rule_files = {p.name for p in (payload / "rules").glob("*.md")}
    for extra in ("templates/org/rules",):
        rule_files |= {p.name for p in (payload / extra).glob("*.md")}
    for stack_rules in (payload / "templates" / "stacks").glob("*/*/rules"):
        rule_files |= {p.name for p in stack_rules.glob("*.md")}

    records = []
    for cid in ids:
        comp = by_id[cid]
        findings = check_prose_component(comp, payload, reach, rule_files, tiers)
        worst = "none"
        for sev in ("critical", "high", "medium", "low"):
            if any(f["severity"] == sev for f in findings):
                worst = sev
                break
        records.append(
            {
                "id": cid,
                "type": comp["type"],
                "path": comp["path"],
                "risk": comp["risk"],
                "checks_run": [
                    "exists",
                    "frontmatter",
                    "name_matches_path",
                    "description",
                    "tier",
                    "tools_known",
                    "role_vs_tools",
                    "reachability",
                    "rule_ref",
                ],
                "findings": findings,
                "worst_severity": worst,
                "disposition": "NO_CHANGE_REQUIRED" if not findings else "FINDINGS",
            }
        )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"records": records}, indent=2) + "\n", encoding="utf-8")

    flagged = [r for r in records if r["findings"]]
    print(f"evaluated {len(records)} components; {len(flagged)} with findings")
    for r in flagged:
        for f in r["findings"]:
            print(f"  [{f['severity']:<8}] {r['id']:<40} {f['check']}: {f['detail']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
