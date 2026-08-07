"""Discover every shipped claude-kit component from disk + catalog, for the evaluation harness.

Runs INSIDE the Docker evaluation container (never on the host): it imports the real
``claude_kit`` resolver so profile membership is the product's own answer rather than a
re-implementation that could drift. Emits one JSON manifest describing every discovered component
with the fields the evaluation program requires (id, type, path, risk, profiles, stacks, scopes,
evaluation method, and empty slots for scenarios/evidence/findings/disposition).

Counts are never hardcoded — everything is derived from the tree and the catalog.
"""

from __future__ import annotations

import ast
import dataclasses
import json
import os
import sys
from pathlib import Path
from typing import Any

import yaml

REPO = Path(os.environ.get("REPO_ROOT", "/repo"))
OUT = Path(os.environ.get("OUT_DIR", "/out"))
sys.path.insert(0, str(REPO / "src"))

from claude_kit import catalog  # noqa: E402
from claude_kit import hooks as hooks_mod  # noqa: E402

# Substrings that mark a component as high risk: it can block delivery, gate a pipeline, touch
# permissions/secrets, or perform an irreversible action. Everything else defaults to medium/low.
HIGH_RISK_TOKENS = (
    "security",
    "secret",
    "owasp",
    "pentest",
    "policy",
    "dependency-scanner",
    "guard",
    "destructive",
    "quality-gates",
    "risk-classification",
    "autonomy",
    "human-in-the-loop",
    "acceptance",
    "merge-reviewer",
    "devils-advocate",
    "orchestrator",
    "incident",
    "migration",
    "pipeline",
    "upgrade",
    "capture",
    "privacy",
)
LOW_RISK_TYPES = {"doc", "example", "reference", "template-artifact"}
MEDIUM_RISK_TYPES = {
    "agent",
    "overlay-agent",
    "org-agent",
    "hook",
    "hook-script",
    "cli-command",
    "pipeline-op",
}


def load_yaml(name: str) -> dict[str, Any]:
    data = yaml.safe_load((REPO / "catalog" / name).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"catalog/{name} did not parse to a mapping")
    return data


def risk_for(comp_type: str, ident: str, path: str) -> str:
    hay = f"{ident} {path}".lower()
    if comp_type in LOW_RISK_TYPES:
        return "low"
    if any(tok in hay for tok in HIGH_RISK_TOKENS):
        return "high"
    if comp_type in MEDIUM_RISK_TYPES:
        return "medium"
    return "low"


def frontmatter(path: Path) -> dict[str, str]:
    """Parse a leading YAML frontmatter block into flat top-level key/value strings."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    out: dict[str, str] = {}
    for line in text[3:end].splitlines():
        if ":" in line and not line.startswith((" ", "\t", "#")):
            key, _, val = line.partition(":")
            out[key.strip()] = val.strip()
    return out


def rel(p: Path) -> str:
    return str(p.relative_to(REPO))


class Manifest:
    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []
        self.exclusions: list[dict[str, str]] = []
        self._seen: set[str] = set()

    def add(
        self,
        *,
        cid: str,
        ctype: str,
        path: str,
        method: str,
        profiles: list[str] | str = "n/a",
        stacks: list[str] | str = "n/a",
        scopes: list[str] | str = "all",
        risk: str | None = None,
        notes: str = "",
    ) -> None:
        if cid in self._seen:
            raise SystemExit(f"duplicate component id {cid!r} — ids must be unique")
        self._seen.add(cid)
        self.items.append(
            {
                "id": cid,
                "type": ctype,
                "path": path,
                "risk": risk or risk_for(ctype, cid, path),
                "profiles": profiles,
                "stacks": stacks,
                "scopes": scopes,
                "evaluation_method": method,
                "scenarios": [],
                "evidence": [],
                "findings": [],
                "static_done": False,
                "dynamic_done": False,
                "disposition": "PENDING",
                "notes": notes,
            }
        )

    def exclude(self, path: str, reason: str) -> None:
        self.exclusions.append({"path": path, "reason": reason})


def profile_membership() -> dict[str, dict[str, list[str]]]:
    """Resolve which profiles install each agent / skill / hook / gate, via the real resolver."""
    base = catalog.defaults(REPO)
    out: dict[str, dict[str, list[str]]] = {
        "agents": {},
        "skills": {},
        "hooks": {},
        "gates": {},
    }
    for name in load_yaml("profiles.yaml")["profiles"]:
        plan = catalog.resolve(REPO, dataclasses.replace(base, profile=name))
        for bucket, values in (
            ("agents", plan.agents),
            ("skills", plan.skills),
            ("hooks", plan.hooks),
            ("gates", plan.gates),
        ):
            for value in values:
                out[bucket].setdefault(value, []).append(name)
    return out


def public_defs(path: Path) -> list[str]:
    """Return the names of top-level public functions."""
    return [
        node.name
        for node in ast.parse(path.read_text(encoding="utf-8")).body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and not node.name.startswith("_")
    ]


def typer_commands(path: Path) -> list[tuple[str, str, str]]:
    """Return (function, invocation path, sub-app) for every Typer command in a CLI module.

    Two commands can share a leaf name across apps (``validate`` exists on both the root app and
    the ``pipeline`` sub-app), so the sub-app prefix is resolved from the module's own
    ``add_typer(..., name=...)`` calls rather than guessed from the variable name.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    subapps: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "add_typer" or not node.args:
            continue
        target = node.args[0]
        for kw in node.keywords:
            if (
                kw.arg == "name"
                and isinstance(kw.value, ast.Constant)
                and isinstance(target, ast.Name)
            ):
                subapps[target.id] = str(kw.value.value)

    out: list[tuple[str, str, str]] = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            func = dec.func if isinstance(dec, ast.Call) else dec
            if not isinstance(func, ast.Attribute) or func.attr != "command":
                continue
            owner = func.value.id if isinstance(func.value, ast.Name) else "?"
            leaf = node.name.replace("_", "-")
            if isinstance(dec, ast.Call):
                for arg in dec.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        leaf = arg.value
                        break
                for kw in dec.keywords:
                    if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                        leaf = str(kw.value.value)
            prefix = subapps.get(owner, "")
            out.append((node.name, f"{prefix} {leaf}".strip(), prefix or "root"))
            break
    return out


def add_agents(m: Manifest, member: dict[str, dict[str, list[str]]]) -> None:
    for p in sorted((REPO / "agents").glob("*.md")):
        fm = frontmatter(p)
        m.add(
            cid=f"agent:{p.stem}",
            ctype="agent",
            path=rel(p),
            method="static+dynamic",
            profiles=member["agents"].get(p.stem, []),
            notes=f"tier={fm.get('tier', '?')} model={fm.get('model', '?')}",
        )
    for p in sorted((REPO / "templates" / "stacks").glob("*/*/agents/*.md")):
        m.add(
            cid=f"overlay-agent:{p.parents[1].name}:{p.stem}",
            ctype="overlay-agent",
            path=rel(p),
            method="static+dynamic",
            stacks=[f"{p.parents[2].name}/{p.parents[1].name}"],
        )
    for p in sorted((REPO / "templates" / "org" / "agents").glob("*.md")):
        m.add(
            cid=f"org-agent:{p.stem}",
            ctype="org-agent",
            path=rel(p),
            method="static+dynamic",
            scopes=["organization"],
        )


def add_skills(m: Manifest, member: dict[str, dict[str, list[str]]]) -> None:
    for p in sorted(REPO.rglob("SKILL.md")):
        r = rel(p)
        if r.startswith(".claude/"):
            continue
        d = p.parent
        is_org = r.startswith("templates/org/skills/")
        m.add(
            cid=("org-skill:" if is_org else "skill:") + d.name,
            ctype="org-skill" if is_org else "skill",
            path=r,
            method="static+dynamic",
            profiles=[] if is_org else member["skills"].get(d.name, []),
            scopes=["organization"] if is_org else "all",
        )
        for ref in sorted(d.rglob("*.md")):
            if ref.name != "SKILL.md":
                m.exclude(
                    rel(ref),
                    "skill reference file — not independently selectable or executable; audited "
                    "for links/licence/freshness as part of its parent skill",
                )


def add_rules(m: Manifest) -> None:
    for p in sorted((REPO / "rules").glob("*.md")):
        m.add(
            cid=f"rule:{p.stem}",
            ctype="rule",
            path=rel(p),
            method="static+ablation",
            profiles="all",
        )
    for p in sorted((REPO / "templates" / "stacks").glob("*/*/rules/*.md")):
        m.add(
            cid=f"overlay-rule:{p.parents[1].name}:{p.stem}",
            ctype="overlay-rule",
            path=rel(p),
            method="static+ablation",
            stacks=[f"{p.parents[2].name}/{p.parents[1].name}"],
        )
    for p in sorted((REPO / "templates" / "org" / "rules").glob("*.md")):
        m.add(
            cid=f"org-rule:{p.stem}",
            ctype="org-rule",
            path=rel(p),
            method="static+ablation",
            scopes=["organization"],
        )


def add_hooks(m: Manifest, member: dict[str, dict[str, list[str]]]) -> None:
    registry = {**hooks_mod.HOOK_REGISTRY, **hooks_mod.PLUGIN_ONLY_HOOKS}
    for hid, spec in registry.items():
        script = spec.get("script")
        m.add(
            cid=f"hook:{hid}",
            ctype="hook",
            path=f"hooks/scripts/{script}"
            if script
            else "src/claude_kit/hooks.py (inline)",
            method="static+deterministic-scenarios",
            profiles=member["hooks"].get(hid, []),
            notes=f"event={spec.get('event')} matcher={spec.get('matcher')!r}",
        )
    for p in sorted((REPO / "hooks" / "scripts").glob("*")):
        if p.is_file():
            m.add(
                cid=f"hook-script:{p.name}",
                ctype="hook-script",
                path=rel(p),
                method="static+deterministic-scenarios",
            )


def add_commands_and_cli(m: Manifest) -> None:
    for p in sorted((REPO / "commands").glob("*.md")):
        m.add(
            cid=f"command:{p.stem}",
            ctype="slash-command",
            path=rel(p),
            method="static+dynamic",
        )
    cli = REPO / "src" / "claude_kit" / "cli.py"
    for fn, invocation, subapp in typer_commands(cli):
        m.add(
            cid=f"cli:{invocation.replace(' ', ':')}",
            ctype="cli-command",
            path=f"{rel(cli)}::{fn}",
            method="static+dynamic",
            notes=f"invocation='claude-kit {invocation}' app={subapp}",
        )
    pipe = REPO / "src" / "claude_kit" / "pipeline.py"
    for fn in public_defs(pipe):
        m.add(
            cid=f"pipeline-op:{fn}",
            ctype="pipeline-op",
            path=f"{rel(pipe)}::{fn}",
            method="static+dynamic",
        )


def add_catalog(m: Manifest, member: dict[str, dict[str, list[str]]]) -> None:
    for p in sorted((REPO / "catalog").glob("*.yaml")):
        m.add(
            cid=f"catalog-file:{p.stem}",
            ctype="catalog-file",
            path=rel(p),
            method="static+schema",
        )

    stacks = load_yaml("stacks.yaml")

    def stack_entry(kind: str, key: str, val: dict[str, Any], label: str) -> None:
        planned = str(val.get("status", "live")) == "planned"
        m.add(
            cid=f"stack:{kind}:{key}",
            ctype="planned-stack" if planned else "live-stack",
            path=f"catalog/stacks.yaml::{label}",
            method="static+rejection-path" if planned else "static+matrix",
            stacks=[f"{kind}/{key}"],
            notes=f"stack_dir={val.get('stack_dir', '-')}",
        )

    for key, val in (stacks["frontend"]["frameworks"] or {}).items():
        stack_entry("frontend", key, val, f"frontend.frameworks.{key}")
    for lang, lval in (stacks["backend"]["languages"] or {}).items():
        stack_entry("backend-language", lang, lval, f"backend.languages.{lang}")
        for fw, fval in (lval.get("frameworks") or {}).items():
            # A framework under a planned language is itself unreachable — inherit planned status.
            merged = dict(fval)
            if str(lval.get("status", "live")) == "planned":
                merged["status"] = "planned"
            stack_entry(
                "backend",
                f"{lang}-{fw}",
                merged,
                f"backend.languages.{lang}.frameworks.{fw}",
            )
    for key, val in (stacks["database"]["options"] or {}).items():
        stack_entry("database", key, val, f"database.options.{key}")

    for name in load_yaml("profiles.yaml")["profiles"]:
        m.add(
            cid=f"profile:{name}",
            ctype="profile",
            path=f"catalog/profiles.yaml::profiles.{name}",
            method="static+matrix",
            profiles=[name],
        )
    for gate, profs in member["gates"].items():
        m.add(
            cid=f"gate:{gate}",
            ctype="gate",
            path="catalog/profiles.yaml::gates",
            method="static+dynamic",
            profiles=profs,
            risk="high",
        )
    for mid in load_yaml("capture.yaml").get("modes") or {}:
        m.add(
            cid=f"capture-mode:{mid}",
            ctype="capture-mode",
            path=f"catalog/capture.yaml::modes.{mid}",
            method="static+matrix",
            risk="high",
        )
    for key in load_yaml("mcp.yaml").get("servers") or {}:
        m.add(
            cid=f"mcp:{key}",
            ctype="mcp-entry",
            path=f"catalog/mcp.yaml::servers.{key}",
            method="static+stub-integration",
        )

    org = load_yaml("org.yaml")
    for entry in org.get("scopes") or []:
        sid = entry["id"]
        m.add(
            cid=f"scope:{sid}",
            ctype="scope",
            path=f"catalog/org.yaml::scopes.{sid}",
            method="static+matrix",
            scopes=[sid],
        )
    for entry in org.get("teams") or []:
        m.add(
            cid=f"org-team:{entry['id']}",
            ctype="org-capability",
            path=f"catalog/org.yaml::teams.{entry['id']}",
            method="static+matrix",
            scopes=["organization"],
        )
    for entry in org.get("packs") or []:
        m.add(
            cid=f"org-pack:{entry['id']}",
            ctype="org-capability",
            path=f"catalog/org.yaml::packs.{entry['id']}",
            method="static+matrix",
            scopes=["organization"],
        )
    for section, ctype in (
        ("autonomy", "autonomy-level"),
        ("strictness", "review-strictness"),
    ):
        for lid in (org.get(section) or {}).get("levels") or {}:
            m.add(
                cid=f"org-{section}:{lid}",
                ctype=ctype,
                path=f"catalog/org.yaml::{section}.levels.{lid}",
                method="static+matrix",
                scopes=["organization"],
                risk="high",
            )


def add_templates_and_modules(m: Manifest) -> None:
    for p in sorted((REPO / "templates").glob("*")):
        if p.is_file():
            m.add(
                cid=f"template:{p.name}",
                ctype="template",
                path=rel(p),
                method="static+render",
            )
    art = REPO / "templates" / "artifacts"
    if art.is_dir():
        for p in sorted(art.glob("*")):
            if p.is_file():
                m.add(
                    cid=f"template-artifact:{p.name}",
                    ctype="template-artifact",
                    path=rel(p),
                    method="static",
                )
    for p in (
        REPO / ".claude-plugin" / "plugin.json",
        REPO / ".claude-plugin" / "marketplace.json",
    ):
        if p.is_file():
            m.add(
                cid=f"manifest:{p.stem}",
                ctype="manifest",
                path=rel(p),
                method="static+schema",
            )

    # Each entry of the SCHEMAS registry is its own validation contract; the registry itself is
    # covered as a module. Registered-but-missing and present-but-unregistered files are findings,
    # so both directions are enumerated.
    registered: dict[str, str] = {}
    schemas_py = REPO / "src" / "claude_kit" / "schemas.py"
    if schemas_py.is_file():
        for node in ast.walk(ast.parse(schemas_py.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Assign):
                continue
            if not any(
                isinstance(t, ast.Name) and t.id == "SCHEMAS" for t in node.targets
            ):
                continue
            if isinstance(node.value, ast.Dict):
                for k, v in zip(node.value.keys, node.value.values):
                    if isinstance(k, ast.Constant) and isinstance(v, ast.Constant):
                        registered[str(k.value)] = str(v.value)
    schema_dir = REPO / "schemas"
    for name, filename in registered.items():
        target = schema_dir / filename
        m.add(
            cid=f"schema:{name}",
            ctype="schema",
            path=rel(target) if target.is_file() else f"schemas/{filename} (MISSING)",
            method="static+schema",
            notes=f"registered in schemas.py; file_present={target.is_file()}",
        )
    if schema_dir.is_dir():
        for p in sorted(schema_dir.glob("*.json")):
            if p.name not in registered.values():
                m.add(
                    cid=f"schema-orphan:{p.stem}",
                    ctype="schema",
                    path=rel(p),
                    method="static+schema",
                    notes="present on disk but NOT registered in schemas.SCHEMAS",
                )

    for mod, ctype in (
        ("export.py", "exporter"),
        ("scaffold.py", "workflow-scaffold"),
        ("validator.py", "workflow-validate"),
        ("upgrader.py", "workflow-upgrade"),
        ("tickets.py", "ticketing"),
        ("board_html.py", "ticketing"),
        ("telemetry.py", "telemetry"),
        ("report.py", "reporting"),
        ("detect.py", "detection"),
        ("render.py", "rendering"),
        ("prompts.py", "workflow-init"),
        ("models.py", "contracts"),
        ("catalog.py", "resolver"),
        ("hooks.py", "hook-registry"),
    ):
        p = REPO / "src" / "claude_kit" / mod
        if p.is_file():
            m.add(
                cid=f"module:{p.stem}",
                ctype=ctype,
                path=rel(p),
                method="static+dynamic",
            )

    for p in sorted((REPO / "scripts").glob("*.py")) + sorted(
        (REPO / "scripts").glob("*.sh")
    ):
        m.add(
            cid=f"repo-script:{p.name}",
            ctype="repo-validation-script",
            path=rel(p),
            method="static+dynamic",
        )
    wf = REPO / ".github" / "workflows"
    if wf.is_dir():
        for p in sorted(wf.glob("*.yml")):
            m.add(
                cid=f"ci-workflow:{p.stem}",
                ctype="packaging-workflow",
                path=rel(p),
                method="static",
            )


def add_examples_and_docs(m: Manifest) -> None:
    ex = REPO / "examples"
    if ex.is_dir():
        for d in sorted(x for x in ex.iterdir() if x.is_dir()):
            m.add(
                cid=f"example:{d.name}",
                ctype="example",
                path=rel(d),
                method="static+reproducibility",
            )
    for p in sorted(REPO.glob("docs/*.md")) + sorted(REPO.glob("*.md")):
        m.add(
            cid=f"doc:{p.stem}", ctype="doc", path=rel(p), method="static+claim-audit"
        )
    for p in sorted(REPO.glob("docs/launch/*.md")):
        m.exclude(
            rel(p),
            "point-in-time launch copy carrying a historical-snapshot banner — no executable "
            "behavioural claim; checked only for the banner's presence",
        )
    for p in sorted(REPO.glob("docs/references/**/*.md")):
        m.exclude(
            rel(p),
            "third-party reference digest — audited for licence/attribution only",
        )


def main() -> int:
    m = Manifest()
    member = profile_membership()
    add_agents(m, member)
    add_skills(m, member)
    add_rules(m)
    add_hooks(m, member)
    add_commands_and_cli(m)
    add_catalog(m, member)
    add_templates_and_modules(m)
    add_examples_and_docs(m)

    counts: dict[str, int] = {}
    risks: dict[str, int] = {}
    for it in m.items:
        counts[it["type"]] = counts.get(it["type"], 0) + 1
        risks[it["risk"]] = risks.get(it["risk"], 0) + 1
    doc = {
        "generated_at": os.environ.get("RUN_TS", ""),
        "baseline_sha": os.environ.get("BASELINE_SHA", ""),
        "run_id": os.environ.get("RUN_ID", ""),
        "docker_proof": Path("/.dockerenv").exists(),
        "total": len(m.items),
        "counts_by_type": dict(sorted(counts.items())),
        "counts_by_risk": dict(sorted(risks.items())),
        "components": m.items,
        "exclusions": m.exclusions,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "component-manifest.json").write_text(
        json.dumps(doc, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"docker_proof={doc['docker_proof']} total={doc['total']} excluded={len(m.exclusions)}"
    )
    print(f"risk={dict(sorted(risks.items()))}")
    for k, v in sorted(counts.items()):
        print(f"  {k:24} {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
