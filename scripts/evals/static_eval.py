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


# A skill is selected by its description alone, so the description has to be actionable. The first
# pass at this check demanded an explicit "use when…" and flagged five shipped skills; two of those
# state a temporal trigger in other words ("BEFORE tests are written", "before and during
# implementation") and three open with an imperative naming the action ("Write unit tests for…"),
# which is a perfectly good selection signal. So the check now fires only on the shape that is
# genuinely unselectable: a description that opens as a NOUN PHRASE about a topic and states no
# condition anywhere. Narrow on purpose — an over-eager finding here would flag most of the
# catalogue and teach the reader to skip the whole report.
_TRIGGER = re.compile(
    r"\buse (this |it )?(skill )?(when|for|to|after|before)\b"
    r"|\bwhen (you|the|a|an|working|starting|asked|building|reviewing|debugging|writing)\b"
    r"|\b(before|during|after|prior to)\s+\w+"
    r"|\btriggers? (on|when)\b"
    r"|\bapplies (when|to)\b"
    r"|\bfor (any|every|all)\b",
    re.I,
)
_TOPIC_OPENER = re.compile(
    r"^(guidance|notes?|reference|information|documentation|docs|overview|background|about|"
    r"a collection|collection|helpers?|utilities|tips|patterns for|thoughts)\b",
    re.I,
)


# Spawning subagents is a fan-out capability, not a convenience. A specialist or review agent
# holding `Agent` can start work nobody is coordinating and nobody is gating — the orchestrator
# stops being the single point of control the pipeline's design depends on. Only the tiers whose
# job IS coordination may hold it.
COORDINATING_TIERS = frozenset({"orchestrator", "stage-lead"})


def check_agent_fanout(comp, payload):
    """Only a coordinating tier may hold the subagent-spawning tool."""
    if comp["type"] not in ("agent", "overlay-agent", "org-agent"):
        return []
    data, err = frontmatter(payload / comp["path"])
    if err:
        return []  # the frontmatter check owns this
    if "Agent" not in tool_list(data.get("tools")):
        return []
    tier = str(data.get("tier") or "").strip()
    if tier in COORDINATING_TIERS:
        return []
    return [
        {
            "severity": "high",
            "check": "fanout_authority",
            "detail": f"tier {tier!r} holds the `Agent` tool, so it can spawn subagents while "
            "sitting outside the coordination layer; work would start that the orchestrator did "
            "not schedule and no gate is watching",
        }
    ]


def check_skill_trigger(comp, payload):
    """A skill's description must be actionable, not a topic label."""
    if comp["type"] not in ("skill", "org-skill"):
        return []
    data, err = frontmatter(payload / comp["path"])
    if err:
        return []  # already reported by the frontmatter check; do not double-count
    desc = str(data.get("description") or "").strip()  # an empty key yields None
    if not desc:
        return []  # likewise
    if _TRIGGER.search(desc) or not _TOPIC_OPENER.match(desc):
        return []
    return [
        {
            "severity": "medium",
            "check": "trigger",
            "detail": "the description opens as a topic label and states no condition for use; "
            "selection is driven by this text alone, so the model has to guess when it applies: "
            f"{desc[:110]!r}",
        }
    ]


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


#: A non-zero exit anywhere — `if …; then …; exit 2; fi` is one line in the inline guards, so
#: anchoring to the start of a line hides every blocker that is not on its own statement line.
_NONZERO_EXIT = re.compile(r"(?:^|[;&|(\s])exit[ \t]+[1-9][0-9]*")
#: A `data_access` note claims blocking. The lookbehinds matter: three notes end "never blocks",
#: and reading that as a blocking claim inverts the verdict on correct advisory hooks.
_BLOCK_CLAIM = re.compile(
    r"(?<!never )(?<!not )(?<!nor )\b(?:block|deny|refus|reject)", re.IGNORECASE
)


def hook_body(spec, payload: Path) -> str:
    """The shell a hook actually runs — a script file, or the inline `entry.command`."""
    script = spec.get("script")
    if script:
        sp = payload / "hooks" / "scripts" / script
        return sp.read_text(encoding="utf-8") if sp.is_file() else ""
    return str((spec.get("entry") or {}).get("command", "") or "")


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
    access = str(spec.get("data_access", "")).strip()
    if not access:
        add(
            "medium",
            "hook_data_access",
            "no data_access note — `claude-kit privacy-report` derives its informed-consent "
            "output from this field, so the hook would be listed without saying what it reads",
        )
    else:
        # The suite already asserts every hook HAS a consent note. Nothing asserted it was TRUE,
        # so a note could describe behaviour the script does not have — in either direction.
        can_block = bool(_NONZERO_EXIT.search(hook_body(spec, payload)))
        claims_block = bool(_BLOCK_CLAIM.search(access))
        if can_block and not claims_block:
            add(
                "high",
                "undeclared_blocker",
                "exits non-zero — it can refuse the user's tool call — but its data_access note "
                f"does not say so: {access!r}. privacy-report would present a gate as an "
                "observer.",
            )
        elif claims_block and not can_block:
            add(
                "medium",
                "blocking_claim_unbacked",
                f"data_access claims it blocks ({access!r}) but no path exits non-zero, so it "
                "cannot. Either the guard is toothless or the consent note overstates it.",
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


JUSTIFICATIONS = "tests/evals/coverage-justifications.json"


def load_justifications(payload: Path) -> dict[str, dict]:
    """Analysed-unreachable branches, keyed ``file::arc``. Missing file means none are claimed."""
    f = payload / JUSTIFICATIONS
    if not f.is_file():
        return {}
    doc = json.loads(f.read_text(encoding="utf-8"))
    return {f"{j['file']}::{j['arc']}": j for j in doc.get("justifications", [])}


def classify_arcs(rel, arcs, source_lines, justified):
    """Split a file's untaken arcs into (unjustified, analysed, stale).

    A justification is honoured only if the line it was written against still reads the same. If
    the file shifted, the entry now points at a different branch and must be re-earned — silently
    applying it would let one analysis excuse an arbitrary future branch.
    """
    unjustified, analysed, stale = [], [], []
    for a, b in arcs:
        key = f"{rel}::{a}->{b}"
        j = justified.get(key)
        if j is None:
            unjustified.append((a, b))
            continue
        actual = source_lines[a - 1].strip() if 0 < a <= len(source_lines) else ""
        if actual != j.get("origin_line_text", "").strip():
            stale.append((key, j.get("origin_line_text", ""), actual))
        else:
            analysed.append((a, b))
    return unjustified, analysed, stale


def orphan_justifications(rel, arcs, justified):
    """Justifications for branches that are now covered — they must be deleted, not left to rot."""
    live = {f"{rel}::{a}->{b}" for a, b in arcs}
    return [k for k in justified if k.startswith(f"{rel}::") and k not in live]


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
    justified = load_justifications(payload)
    arcs = [tuple(a) for a in info.get("missing_branches") or []]
    shortfall = (summary.get("num_branches") or 0) - (
        summary.get("covered_branches") or 0
    )
    if shortfall and not arcs:
        # Without the arc list there is nothing to justify or report, so a silent pass here would
        # turn missing coverage DATA into a clean verdict.
        add(
            "high",
            "coverage_data",
            f"{rel} reports {shortfall} untaken branch(es) but no missing_branches list; the "
            "coverage report cannot be used to verify this module",
        )
        return findings
    lines = path.read_text(encoding="utf-8").splitlines()
    unjustified, analysed, stale = classify_arcs(rel, arcs, lines, justified)
    for key, expected, actual in stale:
        add(
            "high",
            "stale_justification",
            f"{key} was justified against {expected!r} but that line now reads {actual!r} — the "
            "analysis no longer describes this branch and must be re-earned",
        )
    for key in orphan_justifications(rel, arcs, justified):
        add(
            "medium",
            "orphan_justification",
            f"{key} is justified as unreachable but is now covered; delete the entry so the file "
            "does not accumulate excuses that no longer apply",
        )
    if unjustified:
        add(
            "medium",
            "branch_coverage",
            f"{len(unjustified)} untaken branch(es) in {rel} with no recorded analysis: "
            + ", ".join(f"{a}->{b}" for a, b in unjustified[:8]),
        )
    if analysed:
        add(
            "cosmetic",
            "analysed_unreachable",
            f"{len(analysed)} untaken branch(es) in {rel} recorded as unreachable in "
            f"{JUSTIFICATIONS}; they still count against the coverage totals",
        )
    return findings


def prose_index(payload: Path) -> str:
    """Every shipped rule and skill body, concatenated — the corpus a gate must be named in."""
    parts = []
    for sub in ("rules", "skills"):
        for f in (payload / sub).rglob("*.md"):
            parts.append(f.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(parts)


def invocation_corpus(payload: Path) -> str:
    """Everything that tells someone — CI or a human — to run a repo script.

    Prose counts: an operator tool is "invoked" by the doc that instructs you to run it, so
    docs/ and examples/ belong here. CHANGELOG.md deliberately does NOT: it records that a script
    once existed, which is not an instruction to run it, and including it would silence exactly
    the dead-script case this check exists to surface.
    """
    parts = []
    for rel in (".github/workflows", "scripts/evals", "docs", "examples", "skills"):
        d = payload / rel
        if d.is_dir():
            for f in sorted(d.rglob("*")):
                if f.is_file() and f.suffix in (
                    ".md",
                    ".yml",
                    ".yaml",
                    ".sh",
                    ".py",
                    ".toml",
                ):
                    parts.append(f.read_text(encoding="utf-8", errors="ignore"))
    for rel in (
        "CONTRIBUTING.md",
        "CLAUDE.md",
        "README.md",
        "Makefile",
        "pyproject.toml",
    ):
        f = payload / rel
        if f.is_file():
            parts.append(f.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(parts)


def check_repo_script(comp, payload, corpus):
    """A repository validation script must exist, be documented, be invoked, and be able to fail."""
    findings = []

    def add(sev, check, detail):
        findings.append({"severity": sev, "check": check, "detail": detail})

    rel = comp["path"]
    path = payload / rel
    if not path.is_file():
        return [{"severity": "critical", "check": "exists", "detail": f"absent: {rel}"}]
    text = path.read_text(encoding="utf-8", errors="ignore")

    if path.suffix == ".py":
        try:
            tree = ast.parse(text)
        except SyntaxError as exc:
            return [
                {
                    "severity": "critical",
                    "check": "parses",
                    "detail": f"syntax error: {exc}",
                }
            ]
        if not ast.get_docstring(tree):
            add(
                "medium",
                "documented",
                "no module docstring — nothing states what drift it guards",
            )
        # The defect this whole program exists to catch: a checker that cannot report failure.
        # `sys.exit(0)` unconditionally, or no non-zero exit at all, is a guard that always passes.
        exits = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "exit"
        ]
        nonzero = any(
            not (
                a.args
                and isinstance(a.args[0], ast.Constant)
                and a.args[0].value in (0, None)
            )
            for a in exits
        )
        raises = any(isinstance(n, ast.Raise) for n in ast.walk(tree))
        if not nonzero and not raises:
            add(
                "high",
                "can_fail",
                "no non-zero exit and no raise — this guard reports success on a broken payload, "
                "which is worse than not having it: CI stays green and the drift ships",
            )
    elif not text.startswith("#!"):
        add("medium", "shebang", "no shebang line")

    if path.name not in corpus:
        add(
            "low",
            "referenced",
            f"{path.name} is named in no CI workflow, eval suite, or shipped document — nothing "
            "in the repository tells anyone to run it. For a drift guard that means it never "
            "fires; for a one-shot operator tool it means the script has outlived its purpose",
        )
    return findings


def _entry_comment_block(payload: Path, name: str, sid: str) -> str:
    """Comment lines belonging to one catalog entry — safe_load drops comments.

    Both placements are idiomatic and both are used in the shipped catalog: `repowise` carries its
    note INSIDE the entry (after the key, before `config:`), while `serena` and `skillspector`
    carry it in the contiguous comment block immediately BEFORE the key. Reading only one side
    reported two correctly-annotated servers as unannotated.
    """
    text = (payload / "catalog" / name).read_text(encoding="utf-8")
    lines = text.splitlines()
    start = next(
        (i for i, ln in enumerate(lines) if ln.strip().startswith(f"{sid}:")), None
    )
    if start is None:
        return ""

    before = []
    i = start - 1
    while i >= 0 and lines[i].lstrip().startswith("#"):
        before.append(lines[i])
        i -= 1

    after = []
    for ln in lines[start + 1 :]:
        if ln and not ln.startswith((" ", "\t")):
            break
        if len(ln) - len(ln.lstrip()) <= 2 and ln.strip().endswith(":") and after:
            break
        after.append(ln)
    return "\n".join(reversed(before)) + "\n" + "\n".join(after)


_SECRETISH_NAME = re.compile(
    r"TOKEN|SECRET|PASSWORD|CREDENTIAL|_KEY\\b|APIKEY|API_KEY", re.I
)
_SECRETISH_VALUE = re.compile(
    r"^(gh[pousr]_|sk-|xox[baprs]-|AKIA|eyJ)|^[A-Za-z0-9/+=_-]{24,}$"
)


def check_mcp_entry(comp, payload):
    """An MCP fragment must be labelled, typed, version-pinned, credential-free, and risk-noted.

    Every rule here is one the catalog's own header states, so the check enforces the file's
    stated contract rather than an opinion imported from outside it.
    """
    findings = []

    def add(sev, check, detail):
        findings.append({"severity": sev, "check": check, "detail": detail})

    doc = _yaml(payload, "mcp.yaml")
    sid = comp["id"].split(":", 1)[1]
    entry = (doc.get("servers") or {}).get(sid)
    if entry is None:
        add("high", "entry_exists", f"no servers.{sid} in catalog/mcp.yaml")
        return findings
    if not str(entry.get("label", "")).strip():
        add("medium", "label", "no label — the init prompt would show a blank choice")

    config = entry.get("config") or {}
    kind = config.get("type")
    if kind not in ("stdio", "http", "sse"):
        add("high", "transport", f"config.type {kind!r} is not a known MCP transport")
    if kind == "stdio":
        if not config.get("command"):
            add("high", "command", "a stdio server with no command cannot start")
        args = [str(a) for a in config.get("args") or []]
        if config.get("command") == "npx":
            pkgs = [a for a in args if "@" in a and not a.startswith("-")]
            if not pkgs:
                add("high", "pinned", "npx invocation names no versioned package")
            for a in pkgs:
                if a.endswith("@latest") or a.count("@") == (
                    1 if a.startswith("@") else 0
                ):
                    add(
                        "high",
                        "pinned",
                        f"{a!r} is not pinned to an exact version; the catalog header requires a "
                        "pinned version so a fresh upstream release cannot silently change what "
                        "runs on a user's machine",
                    )
    elif kind in ("http", "sse") and not config.get("url"):
        add("high", "url", f"a {kind} server with no url cannot connect")

    for key, value in (config.get("env") or {}).items():
        text = str(value)
        if text.startswith("${") and text.endswith("}"):
            continue
        # A literal is not automatically a secret: the catalog ships restrictive-by-default
        # switches (READ_OPERATIONS_ONLY: "true") whose whole point is to be a fixed value, not
        # something the user must supply. Flagging those would train the reader to ignore the
        # check that actually matters.
        if _SECRETISH_NAME.search(key) or _SECRETISH_VALUE.match(text):
            add(
                "critical",
                "no_credentials",
                f"env {key} carries a literal {text[:8]!r}… rather than a ${{ENV}} placeholder — "
                "the catalog guarantees no credentials are ever generated into a user's .mcp.json",
            )
        elif text.lower() not in ("true", "false", "0", "1") and not text.isdigit():
            add(
                "low",
                "literal_env",
                f"env {key} is the literal {text!r}; harmless if it is a mode switch, but a "
                "non-boolean literal in a fragment is worth a second look",
            )

    if "toxic-flow legs:" not in _entry_comment_block(payload, "mcp.yaml", sid):
        add(
            "medium",
            "toxic_flow_note",
            "no `toxic-flow legs:` note — the header requires every entry to declare which of "
            "{untrusted-content, private-data, destructive, egress} it introduces, and the "
            "fail-closed sandbox rule is keyed to that combination",
        )
    return findings


_CLI_ALIASES = r"(?:claude-kit|ckit|claude-sdlc)"
#: A command CLAIM is a mention at command position: the start of a code line, optionally behind a
#: shell prompt. ``[ \t]`` rather than ``\s`` so a match can never span a newline and stitch the
#: tail of one line onto the head of the next.
_CLI_INVOCATION = re.compile(
    rf"^[ \t]*(?:[$>][ \t]+)?{_CLI_ALIASES}[ \t]+([a-z][a-z0-9-]{{2,}})", re.MULTILINE
)
#: A trailing ``#`` comment inside a fence is prose that happens to sit in a code block.
_SHELL_COMMENT = re.compile(r"(?<!\S)#[^\n]*")
_CODE_FENCE = re.compile(r"```.*?```", re.DOTALL)
_INLINE = re.compile(r"`([^`\n]+)`")

#: Documents whose job is to record the past, exempt from ``cli_claims`` only.
#:
#: "Does this command still exist?" is the wrong question to ask a changelog. ``claude-kit new``
#: appears in CHANGELOG.md under ``### Removed`` (0.5.0) and ``### Added`` (0.2.0), and both
#: entries are correct *because* the command is gone — rewriting either would falsify the record.
#: Every other doc check still applies to these files. Mirrors the comment-justified ``ALLOWLIST``
#: idiom in ``scripts/check_cross_references.py``.
HISTORICAL_DOCS = frozenset({"CHANGELOG.md"})


def cli_commands(payload: Path) -> set[str]:
    """The names a reader may legally type directly after ``claude-kit``.

    That is the ROOT namespace: every top-level command plus the name of every ``add_typer``
    group. A group's own subcommands (``pipeline close-gate``) are deliberately excluded, because
    they are *not* valid at the root — a doc showing ``claude-kit close-gate`` should be reported.

    Attribution is by the decorator's OBJECT, not merely its attribute. ``@app.command()`` and
    ``@pipeline_app.command()`` are both ``.command``; treating them alike hid the group names
    (three docs were told ``claude-kit pipeline`` does not exist, at cli.py:73 it does) while
    promoting that group's subcommands into the root set, where they masked the inverse error.
    """
    try:
        tree = ast.parse(
            (payload / "src" / "claude_kit" / "cli.py").read_text(encoding="utf-8")
        )
    except (OSError, SyntaxError):
        return set()

    def literal_name(call: ast.Call | None) -> str | None:
        if call is None:
            return None
        explicit = next(
            (
                kw.value.value
                for kw in call.keywords
                if kw.arg == "name" and isinstance(kw.value, ast.Constant)
            ),
            None,
        )
        positional = (
            call.args[0].value
            if call.args and isinstance(call.args[0], ast.Constant)
            else None
        )
        return explicit or positional

    groups: dict[str, str] = {}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_typer"
            and node.args
            and isinstance(node.args[0], ast.Name)
        ):
            group = literal_name(node)
            if group:
                groups[node.args[0].id] = group

    names = set(groups.values())
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            # A bare `@app.command` (no parentheses) is an Attribute, not a Call.
            call = dec if isinstance(dec, ast.Call) else None
            func = call.func if call else dec
            # `callback` registers the app's own options, never a subcommand; reading it as one
            # is what put the artefact `-root` (from `def _root`) into the command namespace.
            if not isinstance(func, ast.Attribute) or func.attr != "command":
                continue
            if not isinstance(func.value, ast.Name) or func.value.id in groups:
                continue
            names.add(literal_name(call) or node.name.replace("_", "-"))
    return names


def documented_invocations(text: str) -> set[str]:
    """Names shown at COMMAND POSITION in code — a fenced line, or an inline span.

    Position is what separates a claim from a mention. ``claude-kit doctor`` starting a code line
    tells the reader to type it; the same words inside a mermaid node label
    (``subgraph SRC["claude-kit repo — single source of truth"]``) or a trailing comment
    (``# … the claude-kit plugin from the claude-kit marketplace``) do not. Matching anywhere in a
    fence reported those two lines as three nonexistent subcommands.
    """
    found = set()
    for snip in _CODE_FENCE.findall(text) + _INLINE.findall(text):
        found |= set(_CLI_INVOCATION.findall(_SHELL_COMMENT.sub("", snip)))
    return found


def check_doc(comp, payload, commands):
    """A document describing executable behaviour must not describe behaviour that is gone.

    Dangling ``.claude/{rules,skills,agents}/…`` references are NOT checked here. The product
    already ships ``scripts/check_cross_references.py`` for exactly that question, and the
    validation suite runs it every time. This file's own attempt resolved mentions against the
    repo root alone and so reported the installed-project layout that golden rule #2 *mandates*
    — ``.claude/rules/quality-gates.md`` — as a dead link, along with stack overlays, export
    targets, and files the product creates at run time: 45 flagged paths, 0 real defects. The
    shipped checker resolves core ∪ stack ∪ org and is the authority.
    """
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
    text = path.read_text(encoding="utf-8", errors="ignore")

    if comp["path"] not in HISTORICAL_DOCS:
        ghosts = sorted(documented_invocations(text) - commands)
        if ghosts:
            add(
                "high",
                "cli_claims",
                f"shows `claude-kit {', '.join(ghosts)}` at command position, but the CLI "
                "registers no such root subcommand — a reader following this document gets an "
                "error",
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
    corpus = invocation_corpus(payload)
    commands = cli_commands(payload)

    records = []
    for cid in ids:
        comp = by_id[cid]
        ctype = comp["type"]
        ran: list[str] = []
        if ctype in PROSE_TYPES:
            findings = check_prose_component(comp, payload, reach, rule_files, tiers)
            findings += check_skill_trigger(comp, payload)
            findings += check_agent_fanout(comp, payload)
            ran = ["prose_component", "skill_trigger", "agent_fanout"]
        elif ctype == "hook":
            findings = check_hook(comp, payload, hook_reach)
            ran = ["hook"]
        elif ctype == "hook-script":
            findings = check_hook_script(comp, payload, registered_scripts)
            ran = ["hook_script"]
        elif ctype in ("cli-command", "pipeline-op"):
            findings = check_callable(comp, payload, coverage)
            ran = ["callable"]
        elif ctype == "gate":
            findings = check_gate(comp, payload, prose, conflicts)
            ran = ["gate"]
        elif ctype == "capture-mode":
            findings = check_capture_mode(comp, payload, hook_ids)
            ran = ["capture_mode"]
        elif ctype == "catalog-file":
            findings = check_catalog_file(comp, payload)
            ran = ["catalog_file"]
        elif ctype in (
            "org-capability",
            "autonomy-level",
            "review-strictness",
            "scope",
        ):
            findings = check_org_entry(comp, payload, hook_ids)
            ran = ["org_entry"]
        elif ctype == "schema":
            findings = check_schema(comp, payload)
            ran = ["schema"]
        elif ctype == "repo-validation-script":
            findings = check_repo_script(comp, payload, corpus)
            ran = ["repo_script"]
        elif ctype == "mcp-entry":
            findings = check_mcp_entry(comp, payload)
            ran = ["mcp_entry"]
        elif ctype == "doc":
            findings = check_doc(comp, payload, commands)
            ran = ["doc"]
        elif ctype.startswith("workflow-") or ctype in (
            "resolver",
            "rendering",
            "detection",
            "reporting",
            "telemetry",
            "hook-registry",
        ):
            findings = check_module(comp, payload, coverage)
            ran = ["module"]
        else:
            findings = [
                {
                    "severity": "low",
                    "check": "unsupported_type",
                    "detail": f"no static checks implemented for type {ctype!r} yet",
                }
            ]
            ran = []
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
                "checks_run": ran,
                "statically_evaluated": bool(ran),
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
