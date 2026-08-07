"""Exercise the resolver-observable components: every gate, capture mode, autonomy level,
review-strictness level, planned-stack rejection, overlay rule, org rule, org capability,
template, and schema.

These are configuration, not code, so the temptation is to "verify" them by reading the YAML back
out -- which proves only that a parser can parse. Each family here is driven through a real
resolve+install (or a real ledger walk) and judged on what lands on disk.

DISTINCTNESS IS ENFORCED. Within a family, if two variants produce the same observable, then no
run can tell them apart and neither is measured -- a green row would be an artefact of the two
being indistinguishable, not of either working. Every multi-variant family therefore ends with an
all-pairs comparison and BOTH members of any identical pair are failed. This is the concrete form
of dynamic-tiering.md's rule that a cheaper tier must not become a lower bar.

Usage: tier_a_config.py --out <path> [--only family,family] [--break-distinctness]
  --break-distinctness  mutation control: collapse each family's observable to a constant. Every
                        multi-variant family must then fail. A distinctness check that still
                        passes when every variant looks identical is not checking anything.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import pathlib
import shutil
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

import yaml  # noqa: E402

from claude_kit import catalog, hooks, pipeline, scaffold, schemas  # noqa: E402
from claude_kit.models import Selection  # noqa: E402

STACK = contextlib.ExitStack()
SRC = scaffold.payload_dir(STACK)

BASE = dict(
    frontend_framework="none",
    frontend_language="typescript",
    backend_language="none",
    backend_framework="none",
    database="none",
    profile="standard",
)


def sel(**kw) -> Selection:
    return Selection(**{**BASE, **kw})


def install(s: Selection, tmp: pathlib.Path, name: str) -> pathlib.Path:
    """Resolve and install into a fresh directory; return the project root."""
    d = tmp / name
    d.mkdir(parents=True, exist_ok=True)
    plan = catalog.resolve(SRC, s)
    scaffold.install_sdlc(SRC, d, plan, force=True, log=[], detect_target=None)
    return d


def read(p: pathlib.Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""


def row(cid: str, ok: bool, why: str, **extra) -> dict:
    return {"id": cid, "ok": ok, "why": why, **extra}


# --------------------------------------------------------------------------------------------
# gates -- a real ordered ledger walk, not a membership check
# --------------------------------------------------------------------------------------------
def fam_gates(tmp: pathlib.Path) -> list[dict]:
    """Close every gate of the enterprise profile in order, and prove each one refuses misuse.

    Positive arm: the gate closes in its ordered position and lands in the ledger with a sha256.
    Negative arm: differs by position, because the ledger is bootstrap-anchored -- the FIRST entry
    may legally anchor at any gate, so "close a later gate first" is only a violation once the
    ledger is anchored. For the first gate the negative arm is instead a re-close of the same gate,
    which must be refused as already recorded. Asserting the anchor rule as if it were an
    out-of-order bug would manufacture a false positive against documented behaviour.
    """
    d = install(sel(profile="enterprise"), tmp, "gates")
    gates = pipeline._installed_gates(d)
    if not gates:
        return [
            row("gate:*", False, "no gates in the install snapshot -- nothing to walk")
        ]

    ev = d / "evidence"
    ev.mkdir(exist_ok=True)
    out: list[dict] = []
    for i, g in enumerate(gates):
        f = ev / f"{g}.txt"
        f.write_text(f"real output for {g}\n", encoding="utf-8")

        problems = []
        if i + 1 < len(gates) and i > 0:
            later = gates[i + 1]
            lf = ev / f"{later}-early.txt"
            lf.write_text("x\n", encoding="utf-8")
            jumped, msg = pipeline.close_gate(d, later, str(lf))
            if jumped:
                problems.append(f"accepted {later} out of order")
            elif later not in " ".join(msg) and g not in " ".join(msg):
                problems.append(
                    f"refused out-of-order close without naming a gate: {msg}"
                )

        ok, msg = pipeline.close_gate(d, g, str(f))
        if not ok:
            problems.append(f"in-order close refused: {' '.join(msg)[:160]}")

        again, _ = pipeline.close_gate(d, g, str(f))
        if again:
            problems.append("re-closed an already-recorded gate")

        snap = json.loads(read(pipeline._snapshot_path(d)) or "{}")
        entry = next(
            (e for e in snap.get("gate_history", []) if e.get("gate") == g), None
        )
        if entry is None:
            problems.append("no ledger entry after a successful close")
        elif "evidence_sha256" not in entry:
            problems.append("ledger entry has no evidence_sha256 field at all")
        elif not entry["evidence_sha256"]:
            problems.append("ledger entry carries an empty evidence hash")

        out.append(
            row(
                f"gate:{g}",
                not problems,
                "; ".join(problems)
                or "closed in order, hashed, and refused both misuses",
                position=i,
            )
        )

    # one tamper check for the ledger as a whole -- validate must notice a changed artefact
    victim = ev / f"{gates[0]}.txt"
    victim.write_text("tampered\n", encoding="utf-8")
    good, msgs = pipeline.validate(d, strict=True)
    out.append(
        row(
            "gate:*tamper",
            (not good)
            and any("sha" in m.lower() or "evidence" in m.lower() for m in msgs),
            "validate FAILed on the altered evidence"
            if not good
            else "validate passed with evidence altered after the close",
        )
    )
    return out


# --------------------------------------------------------------------------------------------
# families driven by resolve+install, each with a discriminating observable
# --------------------------------------------------------------------------------------------
CAPTURE_ALL = {
    "capture-learnings",
    "capture-learnings-catchup",
    "capture-learnings-stop",
}


def _capture_command(hid: str) -> str:
    """The exact settings.json command string for a capture hook id.

    All three capture hooks share ONE script and differ only by a dispatch argument
    (`end`/`catchup`/`stop`), so the hook id never appears in settings.json and searching for it
    finds the wrong thing: "capture-learnings" is a substring of the shared script filename, so a
    naive scan reports the `end` hook installed for every mode. The command string, taken from the
    registry rather than reconstructed here, is the only faithful discriminator.
    """
    return str(hooks.HOOK_REGISTRY[hid]["entry"]["command"])


def _commands(node) -> set[str]:
    """Every `command` string anywhere in a parsed settings.json."""
    found: set[str] = set()
    if isinstance(node, dict):
        cmd = node["command"] if "command" in node else None
        if isinstance(cmd, str):
            found.add(cmd)
        for v in node.values():
            found |= _commands(v)
    elif isinstance(node, list):
        for v in node:
            found |= _commands(v)
    return found


def fam_capture(tmp: pathlib.Path) -> tuple[list[dict], dict[str, str]]:
    modes = yaml.safe_load(read(REPO / "catalog/capture.yaml"))["modes"]
    out, obs = [], {}
    for mode, spec in modes.items():
        want = set(spec.get("hooks") or [])
        plan = catalog.resolve(SRC, sel(capture_mode=mode))
        got = set(plan.hooks) & CAPTURE_ALL
        d = install(sel(capture_mode=mode), tmp, f"cap-{mode}")
        # Compare against the PARSED settings, not its text: the command embeds quotes that JSON
        # escapes on disk, so a substring test against the raw file silently matches nothing.
        installed = _commands(json.loads(read(d / ".claude/settings.json") or "{}"))
        on_disk = {h for h in CAPTURE_ALL if _capture_command(h) in installed}
        problems = []
        if got != want:
            problems.append(f"plan hooks {sorted(got)} != declared {sorted(want)}")
        if on_disk != want:
            problems.append(
                f"settings.json commands {sorted(on_disk)} != declared {sorted(want)}"
            )
        obs[mode] = json.dumps(sorted(want if not problems else got))
        out.append(
            row(
                f"capture-mode:{mode}",
                not problems,
                "; ".join(problems)
                or f"installed exactly {sorted(want) or 'no capture hooks'}",
            )
        )
    return out, obs


def fam_autonomy(tmp: pathlib.Path) -> tuple[list[dict], dict[str, str]]:
    org = yaml.safe_load(read(REPO / "catalog/org.yaml"))
    levels = org["autonomy"]["levels"]
    out, obs = [], {}
    for lid, spec in levels.items():
        s = sel(scope="organization", autonomy=lid, teams=["engineering"])
        d = install(s, tmp, f"aut-{lid}")
        readme = read(d / "README.claude-sdlc.md")
        policy = str(spec["policy"]) if "policy" in spec else ""
        others = [
            str(v["policy"])
            for k, v in levels.items()
            if k != lid and "policy" in v and v["policy"]
        ]
        plan = catalog.resolve(SRC, s)
        problems = []
        if policy and policy not in readme:
            problems.append("its policy text is absent from the generated README")
        leaked = [p[:40] for p in others if p and p in readme]
        if leaked:
            problems.append(f"another level's policy leaked in: {leaked}")
        missing = set(spec.get("hooks") or []) - set(plan.hooks)
        if missing:
            problems.append(f"declared hooks not resolved: {sorted(missing)}")
        obs[lid] = policy
        out.append(
            row(
                f"org-autonomy:{lid}",
                not problems,
                "; ".join(problems)
                or "policy rendered, hooks resolved, no cross-level leak",
            )
        )
    return out, obs


def fam_strictness(tmp: pathlib.Path) -> tuple[list[dict], dict[str, str]]:
    org = yaml.safe_load(read(REPO / "catalog/org.yaml"))
    levels = org["strictness"]["levels"]
    out, obs = [], {}
    for lid, spec in levels.items():
        s = sel(scope="organization", review_strictness=lid, teams=["engineering"])
        d = install(s, tmp, f"str-{lid}")
        readme = read(d / "README.claude-sdlc.md")
        plan = catalog.resolve(SRC, s)
        extra = set(spec.get("extra_gates") or [])
        problems = []
        if f"`{lid}`" not in readme:
            problems.append("the chosen level is not named in the generated README")
        missing = extra - set(plan.gates)
        if missing:
            problems.append(f"extra gates not resolved: {sorted(missing)}")
        # the two-sided half: a level that declares no extra gates must not acquire the
        # regulated-only ones from somewhere else
        regulated = set(levels.get("regulated", {}).get("extra_gates") or [])
        stolen = (regulated - extra) & set(plan.gates)
        if stolen and lid != "regulated":
            allowed = set(catalog.resolve(SRC, sel()).gates)
            stolen -= (
                allowed  # gates the base profile already had are not this level's doing
            )
            if stolen:
                problems.append(f"acquired regulated-only gates: {sorted(stolen)}")
        obs[lid] = json.dumps([lid, sorted(extra)])
        out.append(
            row(
                f"org-strictness:{lid}",
                not problems,
                "; ".join(problems)
                or "named in the README with exactly its declared gates",
            )
        )
    return out, obs


PLANNED = {
    "stack:frontend:vue": dict(frontend_framework="vue"),
    "stack:frontend:svelte": dict(frontend_framework="svelte"),
    "stack:backend:python-django": dict(
        backend_language="python", backend_framework="django"
    ),
    "stack:backend-language:node": dict(
        backend_language="node", backend_framework="express"
    ),
    "stack:backend:node-express": dict(
        backend_language="node", backend_framework="express"
    ),
}


def fam_planned() -> list[dict]:
    """Each planned entry must be REJECTED by name; a live selection must still resolve.

    `node-express` shares a selection with `node` (express is only reachable through the node
    language, which is itself planned). Whether it has an independently observable rejection is
    decided by what the message names -- not assumed either way.
    """
    out = []
    live_ok = True
    try:
        catalog.resolve(SRC, sel())
    except (
        Exception
    ) as e:  # a live baseline that fails invalidates every rejection below
        live_ok = False
        live_why = str(e)
    for cid, kw in PLANNED.items():
        token = cid.rsplit(":", 1)[-1].split("-")[-1]
        problems = []
        if not live_ok:
            problems.append(
                f"the live control selection itself failed to resolve: {live_why}"
            )
        try:
            catalog.resolve(SRC, sel(**kw))
            problems.append("resolved a planned stack instead of rejecting it")
            msg = ""
        except ValueError as e:
            msg = str(e)
            if token not in msg:
                parent = next(
                    (
                        p
                        for p, pk in PLANNED.items()
                        if p != cid
                        and pk == kw
                        and p.rsplit(":", 1)[-1].split("-")[-1] in msg
                    ),
                    None,
                )
                problems.append(
                    f"MASKED by {parent}: its own rejection path is unreachable, because the only "
                    f"selection that reaches it is already rejected upstream ({msg[:80]})"
                    if parent
                    else f"rejected without naming {token!r}: {msg[:120]}"
                )
        except Exception as e:
            problems.append(
                f"crashed instead of rejecting cleanly: {type(e).__name__}: {e}"
            )
            msg = ""
        out.append(
            row(
                cid,
                not problems,
                "; ".join(problems) or f"rejected by name: {msg[:100]}",
                message=msg,
            )
        )
    return out


OVERLAY = {
    "postgres": (dict(database="postgres"), dict(database="none")),
    "mongodb": (dict(database="mongodb"), dict(database="none")),
    "react": (
        dict(frontend_framework="react", frontend_language="typescript"),
        dict(frontend_framework="none"),
    ),
}


def fam_overlay(tmp: pathlib.Path) -> list[dict]:
    """Present when its stack is chosen, ABSENT when it is not. Presence alone proves nothing:
    a rule copied unconditionally would pass a presence-only check for every stack."""
    out = []
    for stack, (on, off) in OVERLAY.items():
        d_on = install(sel(**on), tmp, f"ov-{stack}-on")
        d_off = install(sel(**off), tmp, f"ov-{stack}-off")
        src_dir = next(
            (
                p
                for p in (REPO / "templates/stacks").rglob(f"{stack}/rules")
                if p.is_dir()
            ),
            None,
        )
        if src_dir is None:
            out.append(
                row(f"overlay-rule:{stack}:*", False, "no overlay rules dir on disk")
            )
            continue
        for f in sorted(src_dir.glob("*.md")):
            cid = f"overlay-rule:{stack}:{f.stem}"
            here = (d_on / ".claude/rules" / f.name).is_file()
            there = (d_off / ".claude/rules" / f.name).is_file()
            problems = []
            if not here:
                problems.append("not installed when its stack was selected")
            if there:
                problems.append("installed even when its stack was NOT selected")
            out.append(
                row(
                    cid,
                    not problems,
                    "; ".join(problems) or "installed only with its stack",
                )
            )
    return out


def fam_org_rules(tmp: pathlib.Path) -> list[dict]:
    org = yaml.safe_load(read(REPO / "catalog/org.yaml"))
    d_org = install(
        sel(scope="organization", teams=["engineering"]), tmp, "orgrules-on"
    )
    d_ind = install(sel(scope="individual"), tmp, "orgrules-off")
    out = []
    for name in org.get("new_rules") or []:
        cid = f"org-rule:{name[:-3] if name.endswith('.md') else name}"
        here = (d_org / ".claude/rules" / name).is_file()
        there = (d_ind / ".claude/rules" / name).is_file()
        problems = []
        if not here:
            problems.append("missing in organization scope")
        if there:
            problems.append("leaked into individual scope (the layer is scope-gated)")
        out.append(
            row(cid, not problems, "; ".join(problems) or "organization-only, as gated")
        )
    return out


def fam_org_capability(tmp: pathlib.Path) -> list[dict]:
    out = []
    d_sec = install(
        sel(scope="organization", teams=["security"], org_packs=True), tmp, "orgcap-sec"
    )
    d_eng = install(
        sel(scope="organization", teams=["engineering"], org_packs=False),
        tmp,
        "orgcap-eng",
    )
    readme_sec, readme_eng = (
        read(d_sec / "README.claude-sdlc.md"),
        read(d_eng / "README.claude-sdlc.md"),
    )
    problems = []
    if "security" not in readme_sec.lower():
        problems.append("the selected team is not reflected in the generated README")
    if "security" in readme_eng.lower() and "security" not in readme_sec.lower():
        problems.append("team text appears regardless of selection")
    out.append(
        row(
            "org-team:security",
            not problems,
            "; ".join(problems) or "the chosen team personalises the generated README",
        )
    )

    pack = "security-and-compliance"
    here = list(d_sec.glob(f".claude/**/{pack}/pack.yaml"))
    there = list(d_eng.glob(f".claude/**/{pack}/pack.yaml"))
    problems = []
    if not here:
        problems.append("pack manifest not installed when packs were requested")
    if there:
        problems.append("pack manifest installed even with org_packs off")
    out.append(
        row(
            f"org-pack:{pack}",
            not problems,
            "; ".join(problems) or "manifest installed only when packs are requested",
        )
    )
    return out


RENDERED = {
    "template:CLAUDE.md": "CLAUDE.md",
    "template:README.claude-sdlc.md.tmpl": "README.claude-sdlc.md",
    "template:settings.json": ".claude/settings.json",
}
# Copied verbatim, NOT rendered: it is the template the agent fills in at runtime, so its
# placeholders are the payload. Judging it by "no unrendered markers" would fail a correct file.
COPIED = {"template:CONTINUITY.template.md": ".claude/CONTINUITY.template.md"}


def fam_templates(tmp: pathlib.Path) -> list[dict]:
    """A rendered template must exist, be substantial, and contain no unrendered markers.

    Leftover `{{ ... }}` is the failure that matters: the file still looks fine to a human skim and
    is silently wrong to the agent that reads it.
    """
    d = install(
        sel(
            frontend_framework="react",
            backend_language="python",
            backend_framework="fastapi",
            database="postgres",
        ),
        tmp,
        "tpl",
    )
    out = []
    for cid, rel in RENDERED.items():
        p = d / rel
        text = read(p)
        problems = []
        if not text:
            problems.append(f"{rel} was not written")
        elif len(text) < 200:
            problems.append(f"{rel} is only {len(text)} bytes -- rendered to a stub")
        if "{{" in text or "{%" in text:
            problems.append("contains unrendered Jinja markers")
        if rel.endswith(".json") and text:
            try:
                json.loads(text)
            except Exception as e:
                problems.append(f"is not valid JSON: {e}")
        out.append(
            row(cid, not problems, "; ".join(problems) or f"{rel} rendered cleanly")
        )

    for cid, rel in COPIED.items():
        name = cid.split(":", 1)[1]
        landed, origin = read(d / rel), read(REPO / "templates" / name)
        problems = []
        if not landed:
            problems.append(f"{rel} was not installed")
        elif landed != origin:
            problems.append(
                f"{rel} differs from the shipped template it is copied from"
            )
        out.append(
            row(
                cid,
                not problems,
                "; ".join(problems) or f"{rel} installed byte-identical",
            )
        )

    # CLAUDE.stack.md.tmpl has no file of its own: it renders INTO CLAUDE.md. Prove it by
    # difference -- stack text present with a stack, absent without one.
    d_bare = install(sel(), tmp, "tpl-bare")
    with_stack, without = read(d / "CLAUDE.md"), read(d_bare / "CLAUDE.md")
    hits = [t for t in ("fastapi", "postgres", "react") if t in with_stack.lower()]
    leaks = [t for t in ("fastapi", "postgres", "react") if t in without.lower()]
    problems = []
    if not hits:
        problems.append(
            "no stack detail reached CLAUDE.md when a full stack was selected"
        )
    if leaks:
        problems.append(f"stack detail present with no stack selected: {leaks}")
    out.append(
        row(
            "template:CLAUDE.stack.md.tmpl",
            not problems,
            "; ".join(problems)
            or f"stack section rendered ({hits}) and absent without a stack",
        )
    )
    return out


def fam_schemas(tmp: pathlib.Path) -> list[dict]:
    if not schemas.available():
        return [
            row(cid, False, "jsonschema is not installed -- NOT exercised, not a pass")
            for cid in ("schema:capture", "schema:pipeline-snapshot")
        ]
    out = []
    good_cap = yaml.safe_load(read(REPO / "catalog/capture.yaml"))
    bad_cap = json.loads(json.dumps(good_cap))
    bad_cap.pop("modes", None)

    d = install(sel(), tmp, "schema")
    ev = d / "e.txt"
    ev.write_text("x\n", encoding="utf-8")
    gates = pipeline._installed_gates(d)
    seeded, why = pipeline.close_gate(d, gates[0], str(ev))
    if not seeded:
        return [
            row(
                "schema:pipeline-snapshot",
                False,
                f"could not produce a real snapshot to validate: {' '.join(why)[:160]}",
            )
        ]
    good_snap = json.loads(read(pipeline._snapshot_path(d)))
    bad_snap = json.loads(json.dumps(good_snap))
    bad_snap["mode"] = "Z"

    for cid, name, good, bad in (
        ("schema:capture", "capture", good_cap, bad_cap),
        ("schema:pipeline-snapshot", "pipeline-snapshot", good_snap, bad_snap),
    ):
        clean = schemas.validate_doc(good, name, STACK)
        caught = schemas.validate_doc(bad, name, STACK)
        problems = []
        if clean:
            problems.append(f"rejected the real shipped document: {clean[:2]}")
        if not caught:
            problems.append("accepted a document with a required part removed/invalid")
        out.append(
            row(
                cid,
                not problems,
                "; ".join(problems) or "accepts the real doc, rejects a broken one",
            )
        )
    return out


def distinctness(family: str, obs: dict[str, str], collapse: bool) -> list[dict]:
    """Fail BOTH members of any pair of variants that look the same to the harness."""
    if collapse:
        obs = {k: "IDENTICAL" for k in obs}
    bad: set[str] = set()
    pairs = []
    keys = sorted(obs)
    for i, a in enumerate(keys):
        for b in keys[i + 1 :]:
            if obs[a] == obs[b]:
                bad |= {a, b}
                pairs.append(f"{a}=={b}")
    if not bad:
        return []
    return [
        row(
            f"{family}:{k}",
            False,
            f"indistinguishable from another variant of this family ({'; '.join(pairs)}) -- "
            "no run could tell them apart, so neither is measured",
            distinctness=True,
        )
        for k in sorted(bad)
    ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", default="")
    ap.add_argument("--break-distinctness", action="store_true")
    a = ap.parse_args()
    only = {x.strip() for x in a.only.split(",") if x.strip()}

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="ck-tac-"))
    rows: list[dict] = []
    try:

        def want(f: str) -> bool:
            return not only or f in only

        if want("gates"):
            rows += fam_gates(tmp)
        if want("capture"):
            r, obs = fam_capture(tmp)
            rows += r + distinctness("capture-mode", obs, a.break_distinctness)
        if want("autonomy"):
            r, obs = fam_autonomy(tmp)
            rows += r + distinctness("org-autonomy", obs, a.break_distinctness)
        if want("strictness"):
            r, obs = fam_strictness(tmp)
            rows += r + distinctness("org-strictness", obs, a.break_distinctness)
        if want("planned"):
            rows += fam_planned()
        if want("overlay"):
            rows += fam_overlay(tmp)
        if want("orgrules"):
            rows += fam_org_rules(tmp)
        if want("orgcap"):
            rows += fam_org_capability(tmp)
        if want("templates"):
            rows += fam_templates(tmp)
        if want("schemas"):
            rows += fam_schemas(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        STACK.close()

    # a distinctness row overrides an earlier green row for the same id
    collapsed: dict[str, dict] = {}
    for r in rows:
        prev = collapsed[r["id"]] if r["id"] in collapsed else None
        if prev is None or (prev["ok"] and not r["ok"]):
            collapsed[r["id"]] = r
    final = [collapsed[k] for k in sorted(collapsed)]

    pathlib.Path(a.out).write_text(
        json.dumps({"rows": final}, indent=2) + "\n", encoding="utf-8"
    )
    good = [r for r in final if r["ok"]]
    print(f"tier A config: {len(good)}/{len(final)} exercised")
    for r in final:
        if not r["ok"]:
            print(f"  [FAIL] {r['id']:<44} {r['why']}")
    return 0 if len(good) == len(final) else 1


if __name__ == "__main__":
    sys.exit(main())
