"""Exercise the fourteen library modules that make up the install lifecycle, end to end.

These modules are heavily unit-tested already, and that is exactly why a unit-test count is not
evidence here: the question a Tier A row answers is whether the module does its job in a real
install, and whether it FAILS when it should. So every check below is a pair -- a working arm with
an asserted observable effect, and an arm where the module must refuse, report, or preserve rather
than silently proceed.

The refusing arm is the one that matters. An upgrader that always overwrites passes any
"does upgrade work" test; only a user-edited file it must NOT clobber tells you anything. A
validator that always returns True passes on a healthy install. A renderer that silently emits an
empty string for a missing key produces a plausible file with a hole in it.

Usage: tier_a_lifecycle.py --out <path> [--only id,id] [--break-pairs]
  --break-pairs  mutation control: skip the negative arm of every pair and pass the row on the
                 positive arm alone. Every pair-based row must then still be reported as
                 unexercised -- if a row survives on its happy path, the pair is decorative.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import pathlib
import shutil
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

import yaml  # noqa: E402

from claude_kit import (  # noqa: E402
    board_html,
    catalog,
    export,
    hooks,
    pipeline,
    prompts,
    render,
    scaffold,
    telemetry,
    tickets,
    upgrader,
    validator,
)

STACK = contextlib.ExitStack()
SRC = scaffold.payload_dir(STACK)

FULL = dict(
    frontend_framework="react",
    frontend_language="typescript",
    backend_language="python",
    backend_framework="fastapi",
    database="postgres",
    profile="standard",
)


def read(p: pathlib.Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""


def fresh(tmp: pathlib.Path, name: str, **over) -> tuple[pathlib.Path, object]:
    from claude_kit.models import Selection

    d = tmp / name
    d.mkdir(parents=True, exist_ok=True)
    plan = catalog.resolve(SRC, Selection(**{**FULL, **over}))
    scaffold.install_sdlc(SRC, d, plan, force=True, log=[], detect_target=None)
    return d, plan


class Pair:
    """One component's two arms. `works` and `refuses` must BOTH hold for the row to count."""

    def __init__(self, cid: str, skip_negative: bool):
        self.cid = cid
        self.skip_negative = skip_negative
        self.problems: list[str] = []
        self.notes: list[str] = []
        self.saw_negative = False

    def works(self, ok: bool, detail: str) -> None:
        if not ok:
            self.problems.append(f"positive arm: {detail}")
        else:
            self.notes.append(detail)

    def refuses(self, ok: bool, detail: str) -> None:
        if self.skip_negative:
            return
        self.saw_negative = True
        if not ok:
            self.problems.append(f"negative arm: {detail}")
        else:
            self.notes.append(detail)

    def row(self) -> dict:
        # A pair with no negative arm is NOT exercised, however green the positive arm looks.
        if not self.saw_negative:
            return {
                "id": self.cid,
                "ok": False,
                "exercised": False,
                "why": "no negative arm ran -- a module judged only on its happy path is untested",
            }
        # `exercised` and `ok` are different questions. Both arms running IS a measurement even
        # when the module misbehaves -- that is the measurement finding the defect. Conflating the
        # two would make a component drop out of coverage precisely because it is broken.
        return {
            "id": self.cid,
            "ok": not self.problems,
            "exercised": True,
            "why": "; ".join(self.problems) or " | ".join(self.notes),
        }


# --------------------------------------------------------------------------------------------


def c_prompts(tmp: pathlib.Path, neg: bool) -> dict:
    p = Pair("module:prompts", neg)
    cfg = tmp / "sel.yaml"
    cfg.write_text(yaml.safe_dump({**FULL, "scope": "organization"}), encoding="utf-8")
    s = prompts.from_config(cfg, SRC)
    p.works(
        s.backend_framework == "fastapi" and s.scope == "organization",
        f"config file produced the selection it declared ({s.backend_framework}/{s.scope})",
    )
    # NOT an unknown profile: from_config deliberately defers value validation to catalog.resolve
    # (one validation point), and resolve does reject it by name. What from_config owns is SHAPE --
    # a mapping where a list belongs must fail here rather than be iterated key-by-key deep inside
    # the resolver.
    bad = tmp / "bad.yaml"
    bad.write_text(yaml.safe_dump({**FULL, "mcp": {"github": True}}), encoding="utf-8")
    try:
        got = prompts.from_config(bad, SRC)
        p.refuses(False, f"accepted a mapping for `mcp` and produced {got.mcp!r}")
    except ValueError as e:
        p.refuses("mcp" in str(e), f"rejected the malformed shape: {str(e)[:90]}")
    return p.row()


def c_catalog(tmp: pathlib.Path, neg: bool) -> dict:
    from claude_kit.models import Selection

    p = Pair("module:catalog", neg)
    lean = catalog.resolve(SRC, Selection(**{**FULL, "profile": "lean"}))
    ent = catalog.resolve(SRC, Selection(**{**FULL, "profile": "enterprise"}))
    p.works(
        set(lean.agents) < set(ent.agents) and len(ent.gates) > len(lean.gates),
        f"lean resolves to a strict subset of enterprise ({len(lean.agents)} < {len(ent.agents)} agents)",
    )
    try:
        catalog.resolve(SRC, Selection(**{**FULL, "database": "no-such-db"}))
        p.refuses(False, "resolved a database that does not exist in the catalog")
    except ValueError as e:
        p.refuses("no-such-db" in str(e), f"rejected by name: {str(e)[:90]}")
    return p.row()


def c_render(tmp: pathlib.Path, neg: bool) -> dict:
    p = Pair("module:render", neg)
    out = render.render_text(
        "stack is {{ backend_framework }}", {"backend_framework": "fastapi"}
    )
    p.works(out == "stack is fastapi", f"rendered {out!r}")
    try:
        blank = render.render_text("stack is {{ nope }}", {})
        p.refuses(
            False,
            f"rendered a missing key as {blank!r} instead of raising -- a plausible file with a hole in it",
        )
    except Exception as e:
        p.refuses(
            True, f"undefined key raised {type(e).__name__} rather than rendering blank"
        )
    return p.row()


def c_scaffold(tmp: pathlib.Path, neg: bool) -> dict:
    p = Pair("module:scaffold", neg)
    d, _ = fresh(tmp, "sc")
    opts = json.loads(read(d / ".claude/config/init-options.json") or "{}")
    files = opts.get("files") if "files" in opts else None
    n = len(files) if isinstance(files, (list, dict)) else 0
    has_sums = bool(files) and all(
        ("sha256" in f or "checksum" in f)
        for f in (files.values() if isinstance(files, dict) else files)
    )
    p.works(
        n > 20 and has_sums,
        f"recorded {n} installed files, each with a checksum for the upgrader to compare",
    )
    # Not a refusal but the property that makes upgrade safe: reinstalling must not churn.
    before = read(d / ".claude/rules/quality-gates.md")
    d2, plan2 = fresh(tmp, "sc")  # same dir, force=True
    p.refuses(
        read(d2 / ".claude/rules/quality-gates.md") == before,
        "a second install left an installed rule byte-identical (no churn)",
    )
    return p.row()


def c_validator(tmp: pathlib.Path, neg: bool) -> dict:
    p = Pair("module:validator", neg)
    d, _ = fresh(tmp, "val")
    ok, msgs = validator.validate(d, strict=True)
    p.works(ok, f"a fresh install validates strictly ({len(msgs)} messages)")
    victim = d / ".claude/rules/quality-gates.md"
    victim.unlink()
    bad, msgs2 = validator.validate(d, strict=True)
    p.refuses(
        (not bad) and any("quality-gates" in m for m in msgs2),
        f"missing rule reported: {[m for m in msgs2 if 'quality-gates' in m][:1]}"
        if not bad
        else "validate still passed after a required rule was deleted",
    )
    return p.row()


def c_upgrader(tmp: pathlib.Path, neg: bool) -> dict:
    """Two ownership classes, two contracts -- and the distinction is the whole design.

    A USER-EDITABLE file (CLAUDE.md, settings.json, README.claude-sdlc.md, ...) is kept in place and
    the kit's new version arrives beside it as a `.claude-kit` sidecar. A KIT-OWNED file is refreshed,
    with the drifted original backed up to `.claude-kit.bak-N/`. My first version of this check
    asserted the user-editable contract against a kit-owned rule and read the result as the upgrader
    destroying user work; docs/org-capabilities.md states the real contract and
    tests/test_merge_install.py pins it. What must be true either way is that no edit is DESTROYED --
    kept in place, or recoverable from the backup.
    """
    p = Pair("module:upgrader", neg)
    d, _ = fresh(tmp, "up")
    user_file = d / "README.claude-sdlc.md"
    user_file.write_text(read(user_file) + "\nMY USER EDIT\n", encoding="utf-8")
    kit_file = d / ".claude/rules/quality-gates.md"
    kit_file.write_text(
        read(kit_file) + "\n<!-- MY KIT-FILE EDIT -->\n", encoding="utf-8"
    )
    untouched = d / ".claude/rules/testing.md"
    before_untouched = read(untouched)

    ok, msgs = upgrader.upgrade(d)
    kept = "MY USER EDIT" in read(user_file)
    p.works(
        ok and kept and read(untouched) == before_untouched,
        f"upgrade completed ({len(msgs)} messages): the user-editable edit stayed in place and "
        "unmodified kit files were left alone",
    )
    backed_up = [
        q
        for q in d.glob(".claude-kit.bak-*/.claude/rules/quality-gates.md")
        if "MY KIT-FILE EDIT" in read(q)
    ]
    refreshed = "MY KIT-FILE EDIT" not in read(kit_file)
    p.refuses(
        refreshed and bool(backed_up),
        f"a drifted KIT-owned rule was refreshed and its original preserved in {backed_up[0].parts[-4]}"
        if refreshed and backed_up
        else (
            "a drifted kit-owned rule was overwritten with NO backup of the user's version"
            if refreshed
            else "a drifted kit-owned rule was not refreshed at all"
        ),
    )
    return p.row()


def c_export(tmp: pathlib.Path, neg: bool) -> dict:
    p = Pair("module:export", neg)
    d, plan = fresh(tmp, "ex")
    written, skipped = export.export_targets(
        SRC, d, plan, ["cursor", "agents", "copilot"], force=True
    )
    agents_md = read(d / "AGENTS.md")
    mdc = list(d.glob(".cursor/rules/*.mdc"))
    copilot = read(d / ".github/copilot-instructions.md")
    p.works(
        len(agents_md) > 500 and len(mdc) > 3 and len(copilot) > 500,
        f"three targets produced real content (AGENTS.md {len(agents_md)}B, {len(mdc)} .mdc, copilot {len(copilot)}B)",
    )
    try:
        export.export_targets(SRC, d, plan, ["no-such-target"], force=True)
        p.refuses(False, "accepted an unknown export target")
    except Exception as e:
        p.refuses(True, f"unknown target rejected: {type(e).__name__}: {str(e)[:70]}")
    return p.row()


def c_report(tmp: pathlib.Path, neg: bool) -> dict:
    """report.Report is the shared shape doctor/status render; judge it by discrimination."""
    p = Pair("module:report", neg)
    d, _ = fresh(tmp, "rep")
    ok_i, msgs_i = validator.validate(d)
    empty = tmp / "rep-empty"
    empty.mkdir(exist_ok=True)
    ok_e, msgs_e = validator.validate(empty)
    p.works(
        ok_i and bool(msgs_i) is not None,
        f"an installed project reports cleanly ({len(msgs_i)} lines)",
    )
    p.refuses(
        (not ok_e) and msgs_e != msgs_i,
        "an empty directory produces different, non-clean output"
        if not ok_e
        else "an empty directory reported the same clean result as a real install",
    )
    return p.row()


def c_tickets(tmp: pathlib.Path, neg: bool) -> dict:
    p = Pair("module:tickets", neg)
    d, _ = fresh(tmp, "tk")
    tdir = d / tickets.TICKETS_REL
    tdir.mkdir(parents=True, exist_ok=True)
    # The parser reads a markdown heading `# <ID>: <title>` and bold field lines -- NOT YAML
    # frontmatter. My first fixture used frontmatter and every title came back empty.
    (tdir / "CK-1.md").write_text(
        "# CK-1: Reticulate splines\n\n- **Status:** in_progress\n\n## Work Log\n",
        encoding="utf-8",
    )
    store = tickets.load_store(d)
    titles = [t.title for t in store.ordered()]
    p.works(
        store.exists and "Reticulate splines" in titles,
        f"read the ticket back from disk: {titles}",
    )
    empty = tmp / "tk-empty"
    empty.mkdir(exist_ok=True)
    none = tickets.load_store(empty)
    p.refuses(
        (not none.exists) and not list(none.ordered()),
        "a project with no ticket store reports exists=False rather than inventing an empty board"
        if not none.exists
        else "reported a ticket store that does not exist",
    )
    return p.row()


def c_board_html(tmp: pathlib.Path, neg: bool) -> dict:
    p = Pair("module:board_html", neg)
    d, _ = fresh(tmp, "bh")
    tdir = d / tickets.TICKETS_REL
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / "CK-7.md").write_text(
        "# CK-7: Unmistakable Card Title\n\n- **Status:** todo\n\n## Work Log\n",
        encoding="utf-8",
    )
    html = board_html.render_html(tickets.load_store(d), refresh=0)
    p.works(
        "Unmistakable Card Title" in html and "<html" in html.lower(),
        f"rendered a {len(html)}B document containing the ticket's title",
    )
    blank = board_html.render_html(tickets.load_store(tmp / "bh-none"), refresh=0)
    p.refuses(
        "Unmistakable Card Title" not in blank and "<html" in blank.lower(),
        "an empty store renders a valid but ticket-free board"
        if "Unmistakable Card Title" not in blank
        else "rendered a ticket that is not in the store",
    )
    return p.row()


def c_telemetry(tmp: pathlib.Path, neg: bool) -> dict:
    p = Pair("module:telemetry", neg)
    t = tmp / "tel"
    t.mkdir(exist_ok=True)
    good = t / "session.jsonl"
    rec = {
        "requestId": "req-1",
        "gitBranch": "feature/x",
        "timestamp": dt.datetime(2026, 8, 3, 12, 0, 0).isoformat() + "Z",
        "message": {
            "model": "claude-test",
            "usage": {
                "input_tokens": 111,
                "output_tokens": 222,
                "cache_read_input_tokens": 5,
                "cache_creation_input_tokens": 7,
            },
        },
    }
    # the same billed request twice: dedup by requestId must not double-count
    good.write_text(json.dumps(rec) + "\n" + json.dumps(rec) + "\n", encoding="utf-8")
    got = telemetry.scan([good])
    tel = got.get("feature/x") if "feature/x" in got else None
    p.works(
        tel is not None
        and tel.input_tokens == 111
        and tel.output_tokens == 222
        and tel.requests == 1,
        f"parsed one billed request from two records: in={getattr(tel, 'input_tokens', None)} "
        f"out={getattr(tel, 'output_tokens', None)} requests={getattr(tel, 'requests', None)}",
    )
    junk = t / "junk.jsonl"
    junk.write_text('not json\n{\n{"message": 3}\n', encoding="utf-8")
    try:
        empty = telemetry.scan([junk])
        p.refuses(
            not empty or all(v.empty for v in empty.values()),
            "an unparseable transcript yields nothing rather than invented totals"
            if not empty or all(v.empty for v in empty.values())
            else f"invented totals from junk: {empty}",
        )
    except Exception as e:
        p.refuses(
            False, f"crashed on an unparseable transcript: {type(e).__name__}: {e}"
        )
    return p.row()


def c_hooks(tmp: pathlib.Path, neg: bool) -> dict:
    p = Pair("module:hooks", neg)
    d, plan = fresh(tmp, "hk")
    missing = [
        hid
        for hid, spec in hooks.HOOK_REGISTRY.items()
        if "script" in spec
        and spec["script"]
        and not (SRC / "hooks/scripts" / spec["script"]).is_file()
    ]
    installed = set()
    settings = json.loads(read(d / ".claude/settings.json") or "{}")

    def walk(node):
        if isinstance(node, dict):
            if isinstance(node.get("command") if "command" in node else None, str):
                installed.add(node["command"])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(settings)
    want = {
        str(hooks.HOOK_REGISTRY[h]["entry"]["command"])
        for h in plan.hooks
        if h in hooks.HOOK_REGISTRY and "command" in hooks.HOOK_REGISTRY[h]["entry"]
    }
    absent = sorted(want - installed)
    p.works(
        not missing and not absent,
        f"every registry script exists on disk and all {len(want)} resolved hooks reached settings.json",
    )
    unresolved = {
        str(spec["entry"]["command"])
        for hid, spec in hooks.HOOK_REGISTRY.items()
        if hid not in plan.hooks and "command" in spec["entry"]
    }
    leaked = sorted(unresolved & installed)
    p.refuses(
        not leaked,
        "no hook outside the resolved set reached settings.json"
        if not leaked
        else f"unresolved hooks installed anyway: {leaked[:3]}",
    )
    return p.row()


def c_pipeline_abort(tmp: pathlib.Path, neg: bool) -> dict:
    p = Pair("pipeline-op:abort", neg)
    d, _ = fresh(tmp, "ab")
    ev = d / "e.txt"
    ev.write_text("x\n", encoding="utf-8")
    gates = pipeline._installed_gates(d)
    pipeline.close_gate(d, gates[0], str(ev))
    ok, msgs = pipeline.abort(d)
    snap = json.loads(read(pipeline._snapshot_path(d)) or "{}")
    # abort marks `stage`, not `status`; reading the wrong key made a working abort look inert.
    stage = snap["stage"] if "stage" in snap else None
    p.works(
        ok and stage == "aborted",
        f"abort completed and marked the run aborted (stage={stage!r})",
    )
    after, why = pipeline.close_gate(d, gates[1], str(ev))
    p.refuses(
        not after,
        f"an aborted run refuses further gate closes: {' '.join(why)[:90]}"
        if not after
        else "closed a gate on a run that had already been aborted",
    )
    return p.row()


def c_capture_file(tmp: pathlib.Path, neg: bool) -> dict:
    """The FILE as a component: its declared default governs, and every mode it lists resolves."""
    from claude_kit.models import Selection

    p = Pair("catalog-file:capture", neg)
    doc = yaml.safe_load(read(REPO / "catalog/capture.yaml"))
    declared = doc["default"]
    modes = list(doc["modes"])
    resolved_all = []
    for m in modes:
        try:
            catalog.resolve(SRC, Selection(**{**FULL, "capture_mode": m}))
            resolved_all.append(m)
        except Exception as e:
            p.problems.append(f"mode {m!r} declared but does not resolve: {e}")
    defaults = catalog.defaults(SRC)
    got_default = defaults.capture_mode
    p.works(
        got_default == declared and len(resolved_all) == len(modes),
        f"the file's declared default {declared!r} is what a non-interactive resolve uses, "
        f"and all {len(modes)} declared modes resolve",
    )
    try:
        catalog.resolve(SRC, Selection(**{**FULL, "capture_mode": "not-a-mode"}))
        p.refuses(False, "resolved a capture mode the file never declares")
    except Exception as e:
        p.refuses(True, f"an undeclared mode is rejected: {str(e)[:80]}")
    return p.row()


CHECKS = {
    "module:prompts": c_prompts,
    "module:catalog": c_catalog,
    "module:render": c_render,
    "module:scaffold": c_scaffold,
    "module:validator": c_validator,
    "module:upgrader": c_upgrader,
    "module:export": c_export,
    "module:report": c_report,
    "module:tickets": c_tickets,
    "module:board_html": c_board_html,
    "module:telemetry": c_telemetry,
    "module:hooks": c_hooks,
    "pipeline-op:abort": c_pipeline_abort,
    "catalog-file:capture": c_capture_file,
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", default="")
    ap.add_argument("--break-pairs", action="store_true")
    a = ap.parse_args()
    only = {x.strip() for x in a.only.split(",") if x.strip()}

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="ck-tal-"))
    rows = []
    try:
        for cid, fn in CHECKS.items():
            if only and cid not in only:
                continue
            try:
                rows.append(fn(tmp, a.break_pairs))
            except Exception as e:  # a check that crashes is not a check that passed
                rows.append(
                    {
                        "id": cid,
                        "ok": False,
                        "why": f"check raised {type(e).__name__}: {e}",
                    }
                )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        STACK.close()

    pathlib.Path(a.out).write_text(
        json.dumps({"rows": rows}, indent=2) + "\n", encoding="utf-8"
    )
    good = [r for r in rows if r["ok"]]
    print(f"tier A lifecycle: {len(good)}/{len(rows)} exercised")
    for r in rows:
        if not r["ok"]:
            print(f"  [FAIL] {r['id']:<26} {r['why'][:150]}")
    return 0 if len(good) == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
