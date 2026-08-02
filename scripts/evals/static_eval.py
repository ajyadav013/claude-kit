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
import ast
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


def hook_reach_set(payload: Path) -> tuple[set[str], set[str]]:
    """Every hook id that some channel installs, and every script some entry references.

    PLUGIN_ONLY_HOOKS run from the auto-discovered ``hooks/hooks.json`` and are deliberately absent
    from every profile (CONTRIBUTING.md: each carries a ``reason``). Omitting them reported
    ``guard-kubectl-delete`` as unreachable when it is reachable by design — a false positive, and
    a false finding costs more than a missed one because it teaches the reader to discount the
    ledger.
    """
    from claude_kit import hooks as hooks_mod

    ids = (
        set(reachable_sets(payload)["hooks"])
        | set(hooks_mod.PLUGIN_HOOK_IDS)
        | set(hooks_mod.STARTER_HOOK_IDS)
        | set(hooks_mod.PLUGIN_ONLY_HOOKS)
    )
    scripts = {
        str(spec.get("script"))
        for spec in list(hooks_mod.HOOK_REGISTRY.values())
        + list(hooks_mod.PLUGIN_ONLY_HOOKS.values())
        if spec.get("script")
    }
    return ids, scripts


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


PROSE_TYPES = frozenset(
    {
        "agent",
        "overlay-agent",
        "org-agent",
        "skill",
        "org-skill",
        "rule",
        "org-rule",
        "overlay-rule",
    }
)


def check_hook(comp, payload, hook_reach):
    """A registry entry must name a real event, a real executable script, and its data access."""
    from claude_kit import validator

    findings = []

    def add(sev, check, detail):
        findings.append({"severity": sev, "check": check, "detail": detail})

    hid = comp["id"].split(":", 1)[1]
    from claude_kit import hooks as hooks_mod

    spec = hooks_mod.HOOK_REGISTRY.get(hid) or hooks_mod.PLUGIN_ONLY_HOOKS.get(hid)
    if spec is None:
        add(
            "high",
            "hook_registered",
            f"{hid!r} is not in HOOK_REGISTRY or PLUGIN_ONLY_HOOKS",
        )
        return findings
    event = spec.get("event")
    if event not in validator.KNOWN_EVENTS:
        add(
            "high",
            "hook_event",
            f"event {event!r} is not a Claude Code event — it will never fire",
        )
    script = spec.get("script")
    if script:
        sp = payload / "hooks" / "scripts" / script
        if not sp.is_file():
            add(
                "critical",
                "hook_script_exists",
                f"registry points at a missing script: {script}",
            )
        elif not (sp.stat().st_mode & 0o111):
            # Both channels invoke `bash "<path>"`, so the guard still fires today; the cost is
            # direct invocation failing and the payload being internally inconsistent.
            add(
                "low",
                "hook_script_executable",
                f"hooks/scripts/{script} is not executable in the shipped payload; the hook "
                "still fires (both channels run `bash <script>`) but the file cannot be run "
                "directly and is inconsistent with every sibling script",
            )
    if not str(spec.get("data_access", "")).strip():
        add(
            "medium",
            "hook_data_access",
            "no data_access note — `claude-kit privacy-report` derives its informed-consent "
            "output from this field, so the hook would be listed without saying what it reads",
        )
    if hid not in hook_reach:
        add(
            "low",
            "reachability",
            "no profile, plugin, or starter set installs this hook",
        )
    return findings


def check_hook_script(comp, payload, registered_scripts):
    """A hook script must be executable, self-identifying, and degrade when a tool is absent."""
    findings = []

    def add(sev, check, detail):
        findings.append({"severity": sev, "check": check, "detail": detail})

    path = payload / comp["path"]
    if not path.is_file():
        add("critical", "exists", f"declared path is absent: {comp['path']}")
        return findings
    text = path.read_text(encoding="utf-8")
    if not (path.stat().st_mode & 0o111):
        add(
            "low",
            "executable",
            "not executable in the shipped payload — invoked via `bash <script>` so it still "
            "runs, but direct invocation fails and scaffold.py chmods 0o755 on install, so the "
            "repo and the installed copy disagree",
        )
    if not text.startswith("#!"):
        add("medium", "shebang", "no shebang line")
    # Golden rule #4: a hook degrades to a no-op when a tool is missing, never a hard failure.
    if re.search(r"\bjq\b", text) and not re.search(
        r"command -v jq|which jq|has_jq", text
    ):
        add(
            "high",
            "tool_degradation",
            "uses jq without probing for it — on a machine without jq this hook fails "
            "instead of degrading to a no-op (golden rule #4)",
        )
    if path.name not in registered_scripts:
        add("low", "orphan", "no HOOK_REGISTRY entry references this script")
    return findings


def function_span(path, qualname):
    """Return ``(first_line, last_line)`` of a top-level function, or None."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return None
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == qualname
        ):
            return node.lineno, (node.end_lineno or node.lineno)
    return None


def check_callable(comp, payload, coverage):
    """A high-risk CLI command / pipeline op must exist, be documented, and be fully covered."""
    findings = []

    def add(sev, check, detail):
        findings.append({"severity": sev, "check": check, "detail": detail})

    rel, _, qual = comp["path"].partition("::")
    path = payload / rel
    if not path.is_file():
        add("critical", "exists", f"declared module is absent: {rel}")
        return findings
    span = function_span(path, qual)
    if span is None:
        add("high", "symbol_exists", f"{qual!r} is not a top-level function in {rel}")
        return findings
    first, last = span
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        node = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == qual
        )
        if not ast.get_docstring(node):
            add(
                "medium",
                "documented",
                f"{qual!r} has no docstring — `--help` shows nothing",
            )
    except (OSError, SyntaxError, StopIteration):
        pass

    fileinfo = (coverage.get("files") or {}).get(rel)
    if fileinfo is None:
        add(
            "low",
            "coverage_data",
            f"no coverage record for {rel}; cannot verify exercise",
        )
        return findings
    uncovered = sorted(
        n for n in fileinfo.get("missing_lines", []) if first <= n <= last
    )
    if uncovered:
        add(
            "high",
            "coverage",
            f"{qual!r} has {len(uncovered)} uncovered line(s) at {rel}:"
            f"{','.join(str(n) for n in uncovered[:12])} — a high-risk entry point with "
            "unexercised behaviour",
        )
    return findings


def _yaml(payload: Path, name: str):
    import yaml

    return (
        yaml.safe_load((payload / "catalog" / name).read_text(encoding="utf-8")) or {}
    )


def _dig(doc, dotted: str):
    """Walk a dotted path through nested mappings and id-keyed lists; None if absent."""
    cur = doc
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list):
            match = [e for e in cur if isinstance(e, dict) and e.get("id") == part]
            if not match:
                return None
            cur = match[0]
        else:
            return None
    return cur


def gate_order_conflicts(payload: Path) -> list[str]:
    """Pairs of gates two profiles order differently.

    `pipeline.close_gate` derives the expected next gate from the ordered list in the install
    snapshot, so a disagreement between profiles is not cosmetic: the same evidence closes in one
    profile and is rejected as out-of-order in another.
    """
    from claude_kit import catalog

    profiles = catalog._load(payload, "profiles.yaml")
    avail = catalog.available(payload)
    orders = {}
    for name in profiles.get("profiles", {}):
        gates = catalog._resolve_profile(profiles, name, avail).get("gates", [])
        orders[name] = {g: i for i, g in enumerate(gates)}
    conflicts = []
    names = sorted(orders)
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            shared = set(orders[a]) & set(orders[b])
            for g1 in sorted(shared):
                for g2 in sorted(shared):
                    if g1 < g2 and (orders[a][g1] < orders[a][g2]) != (
                        orders[b][g1] < orders[b][g2]
                    ):
                        conflicts.append(f"{a} and {b} disagree on {g1} vs {g2}")
    return sorted(set(conflicts))


def check_gate(comp, payload, prose_index, conflicts):
    """A gate must be installed by a profile, documented, and consistently ordered."""
    findings = []

    def add(sev, check, detail):
        findings.append({"severity": sev, "check": check, "detail": detail})

    from claude_kit import catalog

    gid = comp["id"].split(":", 1)[1]
    profiles = catalog._load(payload, "profiles.yaml")
    avail = catalog.available(payload)
    owners = [
        n
        for n in profiles.get("profiles", {})
        if gid in catalog._resolve_profile(profiles, n, avail).get("gates", [])
    ]
    if not owners:
        add(
            "high",
            "gate_installed",
            f"no profile installs {gid!r}; it can never be closed",
        )
    if gid not in prose_index:
        add(
            "medium",
            "gate_documented",
            f"{gid!r} is named in no shipped rule or skill — an agent closing it has no written "
            "statement of what evidence satisfies it",
        )
    mine = [c for c in conflicts if f" {gid} " in f" {c} "]
    if mine:
        add("high", "gate_order", "; ".join(mine))
    return findings


def check_capture_mode(comp, payload, hook_ids):
    """A capture mode must exist, be labelled, and name only real hooks."""
    findings = []

    def add(sev, check, detail):
        findings.append({"severity": sev, "check": check, "detail": detail})

    doc = _yaml(payload, "capture.yaml")
    mid = comp["id"].split(":", 1)[1]
    mode = (doc.get("modes") or {}).get(mid)
    if mode is None:
        add(
            "high",
            "mode_exists",
            f"{mid!r} is not a key under modes: in catalog/capture.yaml",
        )
        return findings
    if not str(mode.get("label", "")).strip():
        add("medium", "label", "no label — the init prompt would show a blank choice")
    for h in mode.get("hooks") or []:
        if h not in hook_ids:
            add(
                "high", "hook_exists", f"names hook {h!r}, which is in no hook registry"
            )
    if mid == doc.get("default") and (mode.get("hooks") or []):
        add(
            "high",
            "consent_default",
            "the non-interactive default installs background capture hooks; capture reads session "
            "transcript content and was made opt-in in 0.76.0",
        )
    return findings


def check_catalog_file(comp, payload):
    """A catalog file must parse, be a mapping, and declare its version."""
    import yaml

    findings = []
    path = payload / comp["path"]
    if not path.is_file():
        return [
            {
                "severity": "critical",
                "check": "exists",
                "detail": f"absent: {comp['path']}",
            }
        ]
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return [
            {
                "severity": "critical",
                "check": "parses",
                "detail": f"invalid YAML: {exc}",
            }
        ]
    if not isinstance(doc, dict):
        return [
            {
                "severity": "high",
                "check": "mapping",
                "detail": "top level is not a mapping",
            }
        ]
    if "version" not in doc:
        findings.append(
            {
                "severity": "medium",
                "check": "versioned",
                "detail": "no `version:` key — the resolver cannot detect a breaking catalog change",
            }
        )
    return findings


def check_org_entry(comp, payload, hook_ids):
    """An org catalog entry must exist at its declared path, be labelled, and resolve its refs."""
    findings = []

    def add(sev, check, detail):
        findings.append({"severity": sev, "check": check, "detail": detail})

    doc = _yaml(payload, "org.yaml")
    _, _, dotted = comp["path"].partition("::")
    entry = _dig(doc, dotted)
    if entry is None:
        add("high", "entry_exists", f"nothing at {dotted!r} in catalog/org.yaml")
        return findings
    if isinstance(entry, dict) and not str(entry.get("label", "")).strip():
        add("medium", "label", "no label — the init prompt would show a blank choice")
    if isinstance(entry, dict):
        for h in entry.get("hooks") or []:
            if h not in hook_ids:
                add(
                    "high",
                    "hook_exists",
                    f"names hook {h!r}, which is in no hook registry",
                )
        if "policy" in entry and not str(entry.get("policy", "")).strip():
            add(
                "high",
                "policy",
                "an autonomy level with an empty policy renders a blank operating posture into "
                "CLAUDE.md, so the installed project states no boundary at all",
            )
        team_ids = {t.get("id") for t in doc.get("teams") or [] if isinstance(t, dict)}
        for t in entry.get("teams") or []:
            if t not in team_ids:
                add(
                    "high",
                    "team_exists",
                    f"references team {t!r}, which is not declared",
                )
    return findings


def check_schema(comp, payload):
    """A shipped JSON Schema must parse, declare its dialect and type, and be referenced."""
    findings = []

    def add(sev, check, detail):
        findings.append({"severity": sev, "check": check, "detail": detail})

    path = payload / comp["path"]
    if not path.is_file():
        return [
            {
                "severity": "critical",
                "check": "exists",
                "detail": f"absent: {comp['path']}",
            }
        ]
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [
            {
                "severity": "critical",
                "check": "parses",
                "detail": f"invalid JSON: {exc}",
            }
        ]
    if "$schema" not in doc:
        add("medium", "dialect", "no `$schema` — the validating dialect is implicit")
    if "type" not in doc and "$ref" not in doc and "oneOf" not in doc:
        add(
            "medium",
            "typed",
            "declares no `type`, `$ref`, or `oneOf`; it constrains nothing",
        )
    name = path.name
    referenced = any(
        name in f.read_text(encoding="utf-8", errors="ignore")
        for f in (payload / "src").rglob("*.py")
    )
    if not referenced:
        add(
            "high",
            "referenced",
            f"{name} is shipped but named nowhere in src/ — a schema nothing loads validates nothing",
        )
    return findings


def check_module(comp, payload, coverage):
    """A whole-module component must exist, be documented, and be covered."""
    findings = []

    def add(sev, check, detail):
        findings.append({"severity": sev, "check": check, "detail": detail})

    rel = comp["path"]
    path = payload / rel
    if not path.is_file():
        return [{"severity": "critical", "check": "exists", "detail": f"absent: {rel}"}]
    try:
        if not ast.get_docstring(ast.parse(path.read_text(encoding="utf-8"))):
            add("medium", "documented", "no module docstring")
    except SyntaxError as exc:
        return [
            {
                "severity": "critical",
                "check": "parses",
                "detail": f"syntax error: {exc}",
            }
        ]
    info = (coverage.get("files") or {}).get(rel)
    if info is None:
        add(
            "low",
            "coverage_data",
            f"no coverage record for {rel}; cannot verify exercise",
        )
        return findings
    summary = info.get("summary") or {}
    stmts = summary.get("num_statements") or 0
    pct = 100.0 * (summary.get("covered_lines") or 0) / stmts if stmts else 100.0
    if pct < 95.0:
        add(
            "medium",
            "coverage",
            f"{rel} line coverage is {pct:.2f}%, under the 95% floor",
        )
    branches = summary.get("num_branches") or 0
    missing = branches - (summary.get("covered_branches") or 0)
    if missing:
        add("medium", "branch_coverage", f"{missing} untaken branch(es) in {rel}")
    return findings


def prose_index(payload: Path) -> str:
    """Every shipped rule and skill body, concatenated — the corpus a gate must be named in."""
    parts = []
    for sub in ("rules", "skills"):
        for f in (payload / sub).rglob("*.md"):
            parts.append(f.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--payload", default="/repo")
    ap.add_argument("--out", required=True)
    ap.add_argument(
        "--ids", required=True, help="comma-separated component ids, or @file"
    )
    ap.add_argument(
        "--coverage", help="coverage.json used for the callable-coverage check"
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

    coverage = {}
    if args.coverage:
        coverage = json.loads(Path(args.coverage).read_text(encoding="utf-8"))
    hook_reach, registered_scripts = hook_reach_set(payload)
    from claude_kit import hooks as hooks_mod

    hook_ids = set(hooks_mod.HOOK_REGISTRY) | set(hooks_mod.PLUGIN_ONLY_HOOKS)
    prose = prose_index(payload)
    conflicts = gate_order_conflicts(payload)

    records = []
    for cid in ids:
        comp = by_id[cid]
        ctype = comp["type"]
        if ctype in PROSE_TYPES:
            findings = check_prose_component(comp, payload, reach, rule_files, tiers)
        elif ctype == "hook":
            findings = check_hook(comp, payload, hook_reach)
        elif ctype == "hook-script":
            findings = check_hook_script(comp, payload, registered_scripts)
        elif ctype in ("cli-command", "pipeline-op"):
            findings = check_callable(comp, payload, coverage)
        elif ctype == "gate":
            findings = check_gate(comp, payload, prose, conflicts)
        elif ctype == "capture-mode":
            findings = check_capture_mode(comp, payload, hook_ids)
        elif ctype == "catalog-file":
            findings = check_catalog_file(comp, payload)
        elif ctype in (
            "org-capability",
            "autonomy-level",
            "review-strictness",
            "scope",
        ):
            findings = check_org_entry(comp, payload, hook_ids)
        elif ctype == "schema":
            findings = check_schema(comp, payload)
        elif ctype.startswith("workflow-") or ctype in (
            "resolver",
            "rendering",
            "detection",
            "reporting",
            "telemetry",
            "hook-registry",
        ):
            findings = check_module(comp, payload, coverage)
        else:
            findings = [
                {
                    "severity": "low",
                    "check": "unsupported_type",
                    "detail": f"no static checks implemented for type {ctype!r} yet",
                }
            ]
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
