"""Prove that every Tier C component is actually consumed by something.

dynamic-tiering.md commits Tier C to a reachability proof: "evidence that some resolver, installer,
or renderer actually consumes this artefact, so a component that ships but is never read is caught
rather than assumed fine." Without that, Tier C degenerates into the exemption the document says it
must not be -- which is exactly the state the manifest was in, with 8 rows marked done under the
older "reference-only: no dynamic requirement" note and no evidence at all (E-051).

Each component type gets ONE applicable proof method. There is deliberately no catch-all:

  installed   the artefact's path appears in a real scaffolded project
  resolved    the component's key appears as a string leaf of a real ResolvedPlan
  imported    the payload filename appears in the resolver/installer source that must open it
  referenced  the file is linked or named by some other shipped file

A type with no method returns UNPROVEN. A method that finds nothing returns UNPROVEN. Neither is a
pass: "no rule matched" must never read the same as "the rule passed", which is the failure this
whole program keeps rediscovering.

Usage:
  tier_c_reach.py --manifest <path> --out <path> [--plant <id>]
    --plant injects a synthetic unreachable component with the given id, for the mutation control.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import sys
import tempfile

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

# type -> proof method. Absent from this map means UNPROVEN, never a silent pass.
METHOD = {
    "template-artifact": "installed",
    "org-rule": "installed",
    "schema": "imported",
    "manifest": "referenced",
    "catalog-file": "imported",
    "profile": "resolved",
    "live-stack": "resolved",
    "mcp-entry": "resolved",
    "scope": "resolved",
    "org-capability": "resolved",
    "detection": "imported",
    "contracts": "referenced",
    "example": "referenced",
    "doc": "referenced",
}


def string_leaves(obj, out: set) -> set:
    """Every string that actually appears in a resolved plan, exactly -- not a substring search."""
    if isinstance(obj, str):
        out.add(obj)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            out.add(str(k))
            string_leaves(v, out)
    elif isinstance(obj, (list, tuple, set)):
        for v in obj:
            string_leaves(v, out)
    elif dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        # NOT dataclasses.asdict: it deep-copies, and rebuilding a set whose members are dicts
        # raises "unhashable type: 'dict'". That exception was being caught per-variant, so every
        # resolve silently produced nothing and the whole `resolved` method was matching against
        # list_options alone -- 28 components would have been reported unreachable on the strength
        # of a swallowed error. Walk the fields instead.
        for f in dataclasses.fields(obj):
            string_leaves(getattr(obj, f.name), out)
    return out


def build_plans(payload: pathlib.Path) -> set:
    """Resolve the widest reasonable set of Selections and pool their string leaves."""
    from claude_kit import catalog

    leaves: set = set()
    base = catalog.defaults(payload)
    opts = catalog.list_options(payload)
    org = catalog.org_options(payload)
    packs = (
        yaml.safe_load((payload / "catalog/org.yaml").read_text()).get("packs") or []
    )
    team_ids = [t["id"] for t in (org.get("teams") or [])]
    pack_ids = [p["id"] for p in packs]
    scopes = [s["id"] if isinstance(s, dict) else s for s in (org.get("scopes") or [])]
    variants = []
    for profile in [
        p["id"] if isinstance(p, dict) else p for p in opts.get("profiles", [])
    ]:
        for scope in scopes:
            variants.append(dataclasses.replace(base, profile=profile, scope=scope))
    # Every stack axis, every team, every pack. A catalog row that is never selected by any
    # variant cannot be distinguished from one nothing consumes, so the sweep must cover them.
    wide = dict(profile="enterprise", scope="organization")
    for fe in opts.get("frontend", []):
        for lang in fe.get("languages") or [fe.get("default_language") or ""]:
            variants.append(
                dataclasses.replace(
                    base, frontend_framework=fe["id"], frontend_language=lang, **wide
                )
            )
    for be in opts.get("backend", []):
        for fw in be.get("frameworks") or []:
            variants.append(
                dataclasses.replace(
                    base, backend_language=be["id"], backend_framework=fw["id"], **wide
                )
            )
    for db in opts.get("database", []):
        variants.append(dataclasses.replace(base, database=db["id"], **wide))
    if team_ids:
        variants.append(dataclasses.replace(base, teams=list(team_ids), **wide))
    if pack_ids:
        variants.append(
            dataclasses.replace(
                base, teams=list(team_ids), org_packs=list(pack_ids), **wide
            )
        )
    if opts.get(
        "mcp"
    ):  # absent-ok: no mcp key and an empty list both mean nothing to add
        variants.append(
            dataclasses.replace(
                base,
                mcp=[m["id"] if isinstance(m, dict) else m for m in opts["mcp"]],
                **wide,
            )
        )
    errors: list[str] = []
    for sel in variants:
        try:
            string_leaves(catalog.resolve(payload, sel), leaves)
        except ValueError as exc:  # the resolver legitimately rejecting a combination
            errors.append(f"{sel.profile}/{sel.scope}: {exc}")
        except (
            Exception
        ) as exc:  # anything else is a harness fault and must not be swallowed
            raise SystemExit(
                f"build_plans crashed resolving {sel.profile}/{sel.scope}: {exc!r}. "
                "A swallowed crash here silently empties the leaf set and turns every "
                "`resolved` proof into a false negative."
            ) from exc
    if not leaves:
        raise SystemExit(f"no plan resolved at all; rejections: {errors[:4]}")
    string_leaves(opts, leaves)
    return leaves


def scaffold(payload: pathlib.Path) -> set:
    """Install a real enterprise/organization project and return its relative paths."""
    from claude_kit import catalog
    from claude_kit import scaffold as sc

    target = pathlib.Path(tempfile.mkdtemp(prefix="ck-tierc-"))
    sel = dataclasses.replace(
        catalog.defaults(payload), profile="enterprise", scope="organization"
    )
    sc.install_sdlc(payload, target, catalog.resolve(payload, sel))
    return {str(p.relative_to(target)) for p in target.rglob("*") if p.is_file()}


def shipped_text(payload: pathlib.Path) -> str:
    """Concatenated text of every SHIPPED file, for reference proofs.

    Scoped to an explicit allow-list of payload directories. Walking the repo root instead let
    this run's own evidence under `.claude/state/` into the corpus, and a planted `ghost-doc.md`
    duly "proved" itself against a previous run's stdout log. A reachability corpus that contains
    the evaluator's output measures the evaluator, not the product.
    """
    roots = [
        "agents",
        "skills",
        "commands",
        "rules",
        "hooks",
        "templates",
        "catalog",
        "docs",
        "examples",
        "scripts",
        "src",
        "tests",
        ".claude-plugin",
    ]
    exts = {".md", ".yaml", ".yml", ".json", ".py", ".sh", ".toml", ".txt", ".tmpl"}
    files = [f for f in payload.glob("*") if f.is_file() and f.suffix.lower() in exts]
    for r in roots:
        d = payload / r
        if d.is_dir():
            files += [
                f for f in d.rglob("*") if f.is_file() and f.suffix.lower() in exts
            ]
    parts = []
    for f in files:
        try:
            parts.append(
                f"\n<<{f.relative_to(payload)}>>\n" + f.read_text(errors="replace")
            )
        except OSError:
            continue
    return "\n".join(parts)


def key_of(comp: dict) -> str:
    """The identifier a resolver would carry: the part after the type prefix."""
    return comp["id"].split(":", 1)[1] if ":" in comp["id"] else comp["id"]


def prove(
    comp: dict, installed: set, leaves: set, text: str, payload: pathlib.Path
) -> dict:
    method = METHOD.get(comp["type"])
    rel = comp.get("path") or ""
    base = pathlib.Path(rel).name
    row = {"id": comp["id"], "type": comp["type"], "method": method, "proven": False}
    if method is None:
        row["why"] = f"no reachability method defined for type {comp['type']!r}"
        return row

    if method == "installed":
        hits = sorted(p for p in installed if pathlib.Path(p).name == base)
        row["proven"] = bool(hits)
        row["why"] = (
            f"installed at {hits[0]}"
            if hits
            else f"{base} absent from a real enterprise scaffold"
        )
    elif method == "resolved":
        # Ids are namespaced several ways (`stack:backend:python-fastapi`,
        # `org-pack:devops-and-release`), while a plan carries the bare value or a path segment.
        # Candidates are matched EXACTLY against the leaf set -- never as substrings, which would
        # let a short id like "none" pass off any longer string as proof.
        # Candidates are deliberately NARROW. An earlier version also threw in every path
        # segment and every '-'-split fragment, which manufactured generic tokens: a planted
        # `profile:ghost-profile` "proved" itself on the word "profile", which appears in every
        # plan. Anything that can prove a ghost proves nothing.
        last = comp["id"].rsplit(":", 1)[-1]
        cands = {comp["id"], key_of(comp), last}
        if comp["type"] == "live-stack" and "-" in last:
            # a stack id encodes a path: backend:python-fastapi <-> backend/python/fastapi
            cands |= set(last.split("-"))
        segs = set()
        for leaf in leaves:
            if "/" in leaf:
                segs |= set(leaf.split("/"))
        hit = sorted(c for c in cands if c and (c in leaves or c in segs))
        row["proven"] = bool(hit)
        row["candidates"] = sorted(cands)
        row["why"] = (
            f"resolved as {hit[0]!r}"
            if hit
            else f"none of {sorted(cands)} appears in any plan"
        )
    elif method == "imported":
        # the file must be named by code that opens it, not merely exist on disk
        src = (
            "\n".join(
                p.read_text(errors="replace")
                for p in (payload / "src").rglob("*.py")
                if p.is_file()
            )
            if (payload / "src").is_dir()
            else ""
        )
        src += "\n".join(
            p.read_text(errors="replace")
            for p in (REPO / "src").rglob("*.py")
            if p.is_file()
        )
        stem = pathlib.Path(base).stem
        row["proven"] = base in src or stem in src
        row["why"] = (
            f"{base} is named in resolver/installer source"
            if row["proven"]
            else f"{base} is not named anywhere in src/"
        )
    elif method == "referenced":
        # a self-reference proves nothing: strip the file's own section before searching
        marker = f"<<{rel}>>"
        body = text
        if marker in body:
            i = body.index(marker)
            j = body.find("\n<<", i + 1)
            body = body[:i] + (body[j:] if j != -1 else "")
        row["proven"] = base in body
        row["why"] = (
            f"{base} is referenced by another shipped file"
            if row["proven"]
            else f"{base} is never mentioned outside itself"
        )
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument(
        "--plant", default="", help="inject a synthetic unreachable component"
    )
    a = ap.parse_args()

    from contextlib import ExitStack

    from claude_kit import scaffold as sc

    stack = ExitStack()
    payload = pathlib.Path(sc.payload_dir(stack))
    comps = json.loads(pathlib.Path(a.manifest).read_text(encoding="utf-8"))[
        "components"
    ]
    tier_c = [c for c in comps if c["tier"] == "C"]
    if a.plant:
        kind, _, name = a.plant.partition(":")
        tier_c = tier_c + [
            {
                "id": a.plant,
                "type": kind,
                "tier": "C",
                "path": f"does/not/exist/{name or 'ghost'}",
            }
        ]

    installed = scaffold(payload)
    leaves = build_plans(payload)
    text = shipped_text(payload)

    if a.plant:
        # A ghost whose name already occurs in the corpus proves itself and reports PROVEN --
        # the control then says "the checker cannot be fooled" when it simply was not tested.
        # `ghost-doc.md` is the live example: naming it in this file's own docstring put it in
        # the corpus, because scripts/ is part of the corpus. Refuse rather than mislead.
        ghost = pathlib.Path(
            f"does/not/exist/{a.plant.partition(':')[2] or 'ghost'}"
        ).name
        if ghost in text:
            print(
                f"refusing to plant {a.plant!r}: {ghost!r} already appears in the shipped "
                "corpus, so the ghost would prove itself. Use a random token "
                "(mutation_controls.py generates one per run).",
                file=sys.stderr,
            )
            return 2

    rows = [prove(c, installed, leaves, text, payload) for c in tier_c]
    proven = [r for r in rows if r["proven"]]
    unproven = [r for r in rows if not r["proven"]]

    pathlib.Path(a.out).write_text(
        json.dumps({"rows": rows, "installed_files": len(installed)}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"tier C reachability: {len(proven)}/{len(rows)} proven")
    for r in unproven:
        print(f"  [UNPROVEN] {r['id']:<52} {r['why']}")
    return 0 if not unproven else 1


if __name__ == "__main__":
    sys.exit(main())
