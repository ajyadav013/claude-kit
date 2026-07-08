#!/usr/bin/env python3
"""Fail-loud guard against documentation / version / count drift in this repo.

claude-kit ships from one source of truth but advertises itself in many places — the README,
SECURITY.md, the CHANGELOG, the plugin manifests, and the `/sdlc` skill. Those numbers and version
strings drift the moment a component is added without a doc sweep (e.g. PR #25 added a 17th hook
script but left the README saying "16"). This script re-derives the facts from the filesystem and
the catalog and asserts the docs agree.

It checks three classes of drift:

1. **Version parity** — the single version string must be identical across ``pyproject.toml``,
   ``src/claude_kit/__init__.py``, both plugin manifests, the latest ``CHANGELOG.md`` heading, and
   ``SECURITY.md``.
2. **Component counts** — agents / core rules / core skills / collection skills / hook scripts /
   MCP fragments, counted on disk (or in ``catalog/mcp.yaml``), must match every number the docs
   quote for them.
3. **Profile → gate tables** — the gate lists in ``README.md`` and ``skills/sdlc/SKILL.md`` must
   match the effective gate sets resolved from ``catalog/profiles.yaml`` (inheritance included).

Run directly (``python scripts/check_docs_consistency.py``) — exits 0 when consistent, 1 otherwise
and prints every mismatch. Also exercised by ``tests/test_docs_consistency.py`` and CI.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


# --------------------------------------------------------------------------------------------------
# 1) Version parity
# --------------------------------------------------------------------------------------------------


def _versions() -> dict[str, str]:
    """Return the version string each source declares, keyed by a human label."""
    out: dict[str, str] = {}
    m = re.search(r'^version\s*=\s*"([^"]+)"', _read("pyproject.toml"), re.MULTILINE)
    out["pyproject.toml"] = m.group(1) if m else "??"
    m = re.search(r'__version__\s*=\s*"([^"]+)"', _read("src/claude_kit/__init__.py"))
    out["src/claude_kit/__init__.py"] = m.group(1) if m else "??"
    out[".claude-plugin/plugin.json"] = json.loads(
        _read(".claude-plugin/plugin.json")
    ).get("version", "??")
    market = json.loads(_read(".claude-plugin/marketplace.json"))
    for i, p in enumerate(market.get("plugins", [])):
        out[f".claude-plugin/marketplace.json[{i}]"] = p.get("version", "??")
    m = re.search(r"^##\s*\[([^\]]+)\]", _read("CHANGELOG.md"), re.MULTILINE)
    out["CHANGELOG.md (latest)"] = m.group(1) if m else "??"
    m = re.search(r"currently\s*\*\*([^*]+)\*\*", _read("SECURITY.md"))
    out["SECURITY.md"] = m.group(1) if m else "??"
    return out


def check_versions() -> list[str]:
    versions = _versions()
    distinct = set(versions.values())
    if len(distinct) == 1:
        return []
    canonical = versions["pyproject.toml"]
    return [
        f"version drift: {label} says {ver!r} (canonical pyproject.toml = {canonical!r})"
        for label, ver in versions.items()
        if ver != canonical
    ]


# --------------------------------------------------------------------------------------------------
# 2) Component counts
# --------------------------------------------------------------------------------------------------


def _count_skills() -> tuple[int, int]:
    """Return (core, collection): collection skills carry a README.md, core ones do not."""
    core = collection = 0
    for d in sorted((ROOT / "skills").iterdir()):
        if not d.is_dir() or d.name.startswith("_"):
            continue
        if (d / "README.md").is_file():
            collection += 1
        else:
            core += 1
    return core, collection


def _actuals() -> dict[str, int]:
    core, collection = _count_skills()
    mcp = yaml.safe_load(_read("catalog/mcp.yaml")).get("servers", {})
    rules = len(list((ROOT / "rules").glob("*.md")))
    # The README's worked example is the default stack (React + FastAPI + PostgreSQL).
    default_stack_overlays = sum(
        len(list((ROOT / "templates" / "stacks" / d / "rules").glob("*.md")))
        for d in ("frontend/react", "backend/python/fastapi", "db/postgres")
    )
    return {
        "agents": len(list((ROOT / "agents").glob("*.md"))),
        "rules": rules,
        "overlay rules": len(list((ROOT / "templates" / "stacks").rglob("rules/*.md"))),
        "default-stack overlay rules": default_stack_overlays,
        "default-stack rules": rules + default_stack_overlays,
        "skills": core + collection,
        "core skills": core,
        "collection skills": collection,
        "hook scripts": len(list((ROOT / "hooks" / "scripts").glob("*.sh"))),
        "mcp servers": len(mcp),
    }


# Each anchor ties a component count to one regex (single capture group = the number) in one file.
# Every listed regex must match at least once, and every match must equal the on-disk count — so a
# count change forces a doc update, and a reworded sentence that drops the number trips "anchor not
# found". Subset counts elsewhere ("8 agent-operation rules") are deliberately NOT anchored.
_ANCHORS: list[tuple[str, str, str]] = [
    ("agents", "README.md", r"\*\*(\d+)\*\* tiered agents"),
    ("agents", "README.md", r"(\d+) specialized agents"),
    ("agents", "README.md", r"(\d+) specialized roles"),
    ("agents", "README.md", r"(\d+) SDLC agents"),
    ("rules", "README.md", r"\*\*(\d+)\*\* stack-agnostic core rules"),
    ("rules", "README.md", r"(\d+) stack-agnostic core rules"),
    ("rules", "README.md", r"(\d+) stack-agnostic contracts"),
    ("rules", "README.md", r"(\d+) engineering rules"),
    # The headline skill number is the FULL catalog (core + collection); the breakdown pins each part.
    ("skills", "README.md", r"\*\*(\d+)\*\* context-activated skills"),
    ("skills", "README.md", r"(\d+) on-demand skills"),
    ("skills", "README.md", r"(\d+) skills, gates"),
    ("core skills", "README.md", r"\((\d+) core \+"),
    ("collection skills", "README.md", r"\+ (\d+) stack-collection\)"),
    ("hook scripts", "README.md", r"\*\*(\d+)\*\* event hooks"),
    ("hook scripts", "README.md", r"(\d+) event hook scripts"),
    ("mcp servers", "README.md", r"\*\*(\d+)\*\* ready MCP fragments"),
    ("mcp servers", "README.md", r"(\d+) MCP server fragments"),
    # Rule-count truth: overlay files on disk, and the README's default-stack worked example
    # (25 core + react/fastapi/postgres overlays) — the numbers that drifted before 0.58.1.
    ("overlay rules", "README.md", r"\*\*(\d+)\*\* overlay rule files"),
    ("overlay rules", "README.md", r"\*\*(\d+) stack overlay rule files\*\*"),
    ("default-stack overlay rules", "README.md", r"\((\d+) for this stack"),
    ("default-stack rules", "README.md", r"for this stack = (\d+)\)"),
    ("rules", "docs/architecture.md", r"rules/ \((\d+)\)"),
    ("rules", "docs/architecture.md", r"rules/ — (\d+) contracts"),
]


def check_counts() -> list[str]:
    actuals = _actuals()
    errors: list[str] = []
    for component, relfile, pattern in _ANCHORS:
        text = _read(relfile)
        matches = re.findall(pattern, text)
        if not matches:
            errors.append(
                f"{relfile}: anchor for {component!r} not found (pattern {pattern!r}) — "
                "doc reworded? update check_docs_consistency.py"
            )
            continue
        want = actuals[component]
        for got in matches:
            if int(got) != want:
                errors.append(
                    f"{relfile}: {component} count says {got}, but there are {want} "
                    f"(pattern {pattern!r})"
                )

    # Collection skills also drive the living index table in docs/stack-skills/README.md.
    idx = _read("docs/stack-skills/README.md")
    rows = [ln for ln in idx.splitlines() if re.match(r"\|\s*\*\*", ln)]
    if len(rows) != actuals["collection skills"]:
        errors.append(
            f"docs/stack-skills/README.md: {len(rows)} skill rows, but "
            f"{actuals['collection skills']} collection skills exist on disk"
        )
    return errors


# --------------------------------------------------------------------------------------------------
# 3) Profile -> gate tables
# --------------------------------------------------------------------------------------------------


def _effective_gates() -> dict[str, set[str]]:
    """Resolve each profile's effective gate set from profiles.yaml (unioning ``inherit``)."""
    profiles = yaml.safe_load(_read("catalog/profiles.yaml"))["profiles"]
    cache: dict[str, set[str]] = {}

    def resolve(name: str) -> set[str]:
        if name in cache:
            return cache[name]
        p = profiles[name]
        gates = set(p.get("gates") or [])
        if p.get("inherit"):
            gates |= resolve(p["inherit"])
        cache[name] = gates
        return gates

    return {name: resolve(name) for name in profiles}


def _doc_gate_sets(relfile: str) -> dict[str, list[set[str]]]:
    """Parse *every* lean/standard/enterprise gate row from a doc (one entry per table occurrence).

    Returns a list of gate sets per profile rather than a single value, so a second (possibly stale)
    gate table can't silently overwrite an earlier one — each occurrence is checked independently.
    """
    raw: dict[str, list[str]] = {}
    for line in _read(relfile).splitlines():
        m = re.match(r"\|\s*\*\*(lean|standard|enterprise)\*\*\s*\|(.+?)\|\s*$", line)
        if m:
            raw.setdefault(m.group(1), []).append(m.group(2))

    def tokens(cell: str) -> set[str]:
        return {
            t.strip().strip("*").strip("\\").strip()
            for t in cell.split("·")
            if t.strip().strip("*").strip("\\").strip()
        }

    def expand(cell: str) -> set[str]:
        if (
            "+" in cell
        ):  # e.g. "standard + pipeline-green · observability-ready · acceptance"
            base, extra = cell.split("+", 1)
            base_name = base.strip().strip("*").lower()
            base_cells = raw.get(base_name)
            base_gates = expand(base_cells[0]) if base_cells else set()
            return base_gates | tokens(extra)
        return tokens(cell)

    return {p: [expand(c) for c in cells] for p, cells in raw.items()}


def check_profile_gates() -> list[str]:
    effective = _effective_gates()
    errors: list[str] = []
    for relfile in ("README.md", "skills/sdlc/SKILL.md"):
        doc = _doc_gate_sets(relfile)
        for profile in ("lean", "standard", "enterprise"):
            occurrences = doc.get(profile) or []
            if not occurrences:
                errors.append(f"{relfile}: no gate row found for profile {profile!r}")
                continue
            if len(occurrences) > 1:
                errors.append(
                    f"{relfile}: {len(occurrences)} gate rows for profile {profile!r} "
                    "(duplicate gate table) — keep exactly one so a stale table can't hide "
                    "behind a correct one"
                )
            for idx, gates in enumerate(occurrences):
                if gates != effective[profile]:
                    missing = effective[profile] - gates
                    extra = gates - effective[profile]
                    detail = []
                    if missing:
                        detail.append(f"missing {sorted(missing)}")
                    if extra:
                        detail.append(f"unexpected {sorted(extra)}")
                    where = "" if len(occurrences) == 1 else f" (occurrence {idx + 1})"
                    errors.append(
                        f"{relfile}: {profile} gate row{where} disagrees with "
                        "profiles.yaml — " + "; ".join(detail)
                    )
    return errors


# --------------------------------------------------------------------------------------------------


def run() -> list[str]:
    """Run every check and return the combined list of error messages (empty = consistent)."""
    return check_versions() + check_counts() + check_profile_gates()


def main() -> int:
    errors = run()
    if errors:
        print("docs consistency: FAIL")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("docs consistency: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
