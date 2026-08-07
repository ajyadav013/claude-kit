"""The batch gate: four assertions about the evaluation apparatus, not about the product.

This run has now recorded nineteen instances of the same failure: the evaluator produced a
confident, well-formed, WRONG answer and did not crash. A crashed grader booked as a clean FAIL
that fabricated the strongest possible result (E-024). Records advertising nine checks that never
ran (E-025). A checker inventing seven findings against a correct catalog (E-026). Six write-once
scalars read as if maintained (E-028). A coverage report describing a tree that had not existed for
an hour (E-029). A final report claiming zero product changes because a missing dict key read as
False (E-033). A severity matcher scoring a textbook review as having no severities (E-034).

Every one was caught by a human-style act of reading the raw artefact. None was caught by the
harness. That is the gap this closes.

Four checks, each written so it CAN fail:

  1. MUTATION CONTROL   every checker has a recorded control, taken at the current commit, proving
                        it fails on a planted defect. A checker that cannot fail reports CLEAN on a
                        broken payload.
  2. DERIVED SCALARS    every headline number in state.json is recomputed here from the underlying
                        records and must match. A scalar written once and read forever is a scalar
                        that stops describing its data (E-028).
  3. INPUT PROVENANCE   every data input carries a commit stamp matching the commit under
                        evaluation (E-029).
  4. ABSENT != FALSE    no `.get(k)` on an optional field may decide a reported verdict. `absent`
                        and `false` are different answers and a bare `.get` collapses them (E-033).

Exit 0 = gate open. Exit 1 = gate closed, batch may not be marked done. Exit 2 = the meta-check
itself could not run, which is NOT a pass.

Usage: meta_check.py [--state DIR] [--sha SHA] [--json OUT]
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]

# Checkers whose verdicts feed component dispositions. A checker absent from its control registry
# is a finding, not an omission to be waved through.
CHECKERS = [
    "scripts/evals/static_eval.py",
    "scripts/evals/rule_load_proof.py",
    "scripts/evals/stamp-coverage-provenance.py",
    "tests/evals/e2e/oracles/rd_rules.py",
    "tests/evals/e2e/oracles/ra_rules.py",
    "tests/evals/e2e/oracles/rb_rules.py",
    "tests/evals/e2e/oracles/rc_rules.py",
    "tests/evals/e2e/oracles/sc01_docs_only.py",
    "tests/evals/e2e/oracles/sc02_bug_fix.py",
    "scripts/evals/tier_b_reconcile.py",
    "scripts/evals/tier_c_reach.py",
    "scripts/evals/tier_a_cli.py",
    "scripts/evals/tier_a_scripts.py",
    "scripts/evals/tier_a_config.py",
    "scripts/evals/tier_a_lifecycle.py",
    "scripts/evals/tier_b_batches.py",
    "scripts/evals/test_integrity.py",
    "scripts/evals/blind_ab.py",
    "scripts/evals/holdout_seal.py",
    "tests/evals/e2e/oracles/transcript_stop.py",
    # This file is a checker too, and a gate exempt from its own rule is not a gate.
    "scripts/evals/meta_check.py",
]

# An `absent != false` exemption must state WHY, at the site. A bare marker with no reason does
# not waive anything.
WAIVER = "# absent-ok:"


class Result:
    def __init__(self) -> None:
        self.checks: list[dict] = []

    def add(
        self, name: str, ok: bool, detail: str, findings: list[str] | None = None
    ) -> None:
        self.checks.append(
            {
                "check": name,
                "pass": bool(ok),
                "detail": detail,
                "findings": findings or [],
            }
        )

    @property
    def ok(self) -> bool:
        # `pass is None` means the check reported that it proved nothing (F-080). It is neither a
        # pass nor a failure, so it is excluded rather than counted -- `all()` reads None as falsy
        # and would fail a run on the strength of a check that never ran.
        return all(c["pass"] for c in self.checks if c["pass"] is not None)


def check_mutation_controls(state: pathlib.Path, sha: str, r: Result) -> None:
    """Each checker needs a control recorded AT THIS COMMIT proving it can fail."""
    registry = state / "mutation-controls.json"
    if not registry.is_file():
        r.add(
            "mutation_control",
            False,
            f"no control registry at {registry.name}; {len(CHECKERS)} checkers are unverified",
            [f"{c}: no recorded mutation control" for c in CHECKERS],
        )
        return
    doc = json.loads(registry.read_text(encoding="utf-8"))
    recorded = {e["checker"]: e for e in doc.get("controls", [])}
    missing, stale = [], []
    for c in CHECKERS:
        e = recorded.get(c)
        if not e:
            missing.append(f"{c}: no recorded mutation control")
        elif e.get("sha") != sha:
            stale.append(
                f"{c}: control taken at {e.get('sha')}, current commit is {sha}"
            )
        elif e.get("detected") is not True:
            missing.append(
                f"{c}: control recorded but the planted defect was NOT detected"
            )
    bad = missing + stale
    r.add(
        "mutation_control",
        not bad,
        f"{len(CHECKERS) - len(bad)}/{len(CHECKERS)} checkers carry a passing control at {sha}",
        bad,
    )


# A scenario counts toward task-domain coverage only if it MEASURED something. RUN_FAILED counts:
# a real failure is a result. Listed as an allowlist rather than `!= "NOT_RUN"`, because with a
# denylist every status invented later is credited as coverage by default -- and one was:
# RUN_UNMEASURED, for scenarios that executed but whose verdict says nothing about the product
# (the harness had no approval channel, or the fixture contradicted the scenario premise).
MEASURED_TASK_STATUSES = frozenset(
    {"RUN_PASSED", "RUN_PASSED_WITH_DEVIATION", "RUN_FAILED"}
)


def derived_scalars(state: pathlib.Path) -> dict:
    """Recompute every headline scalar from the records. The single definition of each formula.

    Every scalar the terminal gate reads must be computed here. One that is not cannot drift-fail,
    which is the same "a checker that cannot fail reports CLEAN" shape the program keeps finding
    in the product -- and it had already happened: task_domain_coverage_percent was absent from
    this set and stored 35.3 against a real 6.2, having picked up an unrelated tier-A figure.

    It returns the dict rather than asserting on it so that the checker and the corrector share
    one arithmetic. Two copies of a formula is how the stored value drifted from the computed one
    in the first place; a corrector with its own copy just moves the seam.
    """
    man = json.loads((state / "component-manifest.json").read_text(encoding="utf-8"))
    comps = man["components"] if isinstance(man, dict) else man
    fnd = json.loads((state / "findings.json").read_text(encoding="utf-8"))["findings"]
    bank = json.loads((state / "task-bank-manifest.json").read_text(encoding="utf-8"))

    def pct(n: int, d: int) -> float:
        return round(n / d * 100, 1) if d else 0.0

    def done(xs: list) -> int:
        return sum(1 for c in xs if c.get("dynamic_done") is True)

    total = len(comps)
    # The gate asks for 100% *required* dynamic coverage. Dividing by all 447 caps the metric at
    # 97.5%, because 11 components are reference-only and can never be dynamic_done -- so on that
    # denominator the gate is unreachable by construction rather than by any shortfall in work.
    required = [c for c in comps if c.get("dynamic_required") is True]
    rules = [c for c in comps if c.get("type") == "rule"]
    hook_family = [c for c in comps if c.get("type") in ("hook", "hook-script")]
    tasks = bank["tasks"]

    derived = {
        "components_total": total,
        "component_static_coverage_percent": pct(
            sum(1 for c in comps if c.get("static_done") is True), total
        ),
        "component_dynamic_coverage_percent": pct(done(required), len(required)),
        "rule_evaluation_coverage_percent": pct(done(rules), len(rules)),
        "hook_evaluation_coverage_percent": pct(done(hook_family), len(hook_family)),
        "task_domain_coverage_percent": pct(
            sum(1 for t in tasks if t.get("status") in MEASURED_TASK_STATUSES),
            len(tasks),
        ),
    }
    sev = {"critical": 0, "high": 0, "medium": 0, "low": 0, "cosmetic": 0}
    for f in fnd:
        if f.get("status") == "open":
            sev[f["severity"]] = sev.get(f["severity"], 0) + 1
    derived["open_findings"] = sev
    return derived


def check_derived_scalars(state: pathlib.Path, r: Result) -> None:
    """Compare every stored headline scalar against the value its records imply."""
    st = json.loads((state / "state.json").read_text(encoding="utf-8"))
    derived = derived_scalars(state)

    drift = []
    for k, v in derived.items():
        stored = st.get(k)
        if stored != v:
            drift.append(f"{k}: state.json says {stored!r}, records give {v!r}")
    r.add(
        "derived_scalars",
        not drift,
        f"{len(derived) - len(drift)}/{len(derived)} headline scalars match their records",
        drift,
    )


def check_input_provenance(state: pathlib.Path, sha: str, r: Result) -> None:
    """Every data input must record the commit it was produced at, and it must match."""
    problems = []
    cov = state / "latest-coverage.json"
    if not cov.is_file():
        problems.append(
            "latest-coverage.json is absent; coverage verdicts have no input"
        )
    else:
        prov = (
            json.loads(cov.read_text(encoding="utf-8")).get("ck_provenance") or {}
        ).get("sha")
        if not prov:
            problems.append("latest-coverage.json carries no ck_provenance.sha")
        elif not sha.startswith(prov) and not prov.startswith(sha):
            problems.append(
                f"latest-coverage.json was generated at {prov}, evaluating {sha}"
            )
    r.add(
        "input_provenance",
        not problems,
        "all data inputs carry a matching commit stamp"
        if not problems
        else "provenance mismatch",
        problems,
    )


def check_absent_is_not_false(r: Result) -> None:
    """Flag `.get(k)` with no default used where a verdict is decided.

    Deliberately narrow: only `.get` with a SINGLE argument, and only inside a boolean-deciding
    context (if/while test, a boolean operator, or an aggregator like sum/all/any). A `.get(k, d)`
    with an explicit default has stated what absent means and is fine. This cannot see every
    instance -- a `.get` assigned to a variable that later decides a verdict passes -- and that
    limitation is reported rather than implied.
    """
    hits = []
    AGG = {"sum", "all", "any", "filter", "min", "max"}

    class V(ast.NodeVisitor):
        def __init__(self, path: str) -> None:
            self.path = path
            self.ctx: list[str] = []

        def _bare_get(self, node: ast.AST) -> list[ast.Call]:
            """`.get(k)` calls whose absence-behaviour is NOT stated somewhere else.

            The first version flagged 44 sites and the first three inspected were all noise, which
            is its own failure: a gate that cries wolf gets switched off. But the SECOND version
            over-corrected and silently dropped `static_eval.py:316` -- the one site already
            verified by hand as a genuine defect (E-038). De-noising a checker is itself a change
            that can introduce a false negative, and it did.

            The two exclusions are therefore stated as narrowly as the idiom they describe:

              x.get(k) or default   `or` is the DEFAULTING idiom: the expression evaluates to a
                                    value and the final operand is the stated default. Excluded.
                                    `and`, by contrast, COMBINES truth values -- there is no
                                    default in it -- so `.get` operands of an `and` still count.
              a == x.get(k)         a comparison against the value. Only a DIRECT operand of the
                                    comparison is excluded. `"Agent" not in tool_list(d.get(k))`
                                    is a comparison too, but the `.get` there is buried inside a
                                    call whose argument decides the branch -- excluding it was
                                    exactly the bug.
            """
            excluded: set[int] = set()
            for n in ast.walk(node):
                if isinstance(n, ast.BoolOp) and isinstance(n.op, ast.Or):
                    for v in n.values:
                        if isinstance(v, ast.Call):
                            excluded.add(id(v))
                if isinstance(n, ast.Compare):
                    for v in [n.left, *n.comparators]:
                        if isinstance(v, ast.Call):
                            excluded.add(id(v))
            out = []
            for n in ast.walk(node):
                if (
                    isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "get"
                    and len(n.args) == 1
                    and not n.keywords
                    and id(n) not in excluded
                ):
                    out.append(n)
            return out

        def _record(self, call: ast.Call, why: str, ctx: ast.AST | None = None) -> None:
            # Span, not a single line: the formatter splits a long call across lines, so a waiver
            # comment written next to it lands on a DIFFERENT line than `call.lineno`. Keying the
            # waiver to one line silently un-waived two sites the moment ruff reflowed them.
            # The span is the ENCLOSING expression, not the `.get()` call. A comment -- waiver or
            # control marker -- attaches to the statement, and the formatter puts it on the line
            # holding the closing paren. Keying to the inner call's own span put the marker one
            # line outside it, which broke a waiver and then broke the control that checks waivers.
            outer = ctx if ctx is not None else call
            hits.append(
                {
                    "path": self.path,
                    "line": call.lineno,
                    "end": max(
                        getattr(call, "end_lineno", call.lineno) or call.lineno,
                        getattr(outer, "end_lineno", call.lineno) or call.lineno,
                    ),
                    "why": why,
                }
            )

        def visit_If(self, node: ast.If) -> None:
            for c in self._bare_get(node.test):
                self._record(c, "decides an `if`", node.test)
            self.generic_visit(node)

        def visit_Call(self, node: ast.Call) -> None:
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")
            if name in AGG:
                for a in node.args:
                    for c in self._bare_get(a):
                        self._record(c, f"inside {name}()", a)
            self.generic_visit(node)

        def visit_BoolOp(self, node: ast.BoolOp) -> None:
            for c in self._bare_get(node):
                self._record(c, "in a boolean expression", node)
            self.generic_visit(node)

    scanned = 0
    waived = 0
    for rel in CHECKERS:
        p = REPO / rel
        if not p.is_file():
            continue
        scanned += 1
        src = p.read_text(encoding="utf-8")
        try:
            tree = ast.parse(src)
        except SyntaxError as e:
            hits.append(f"{rel}: unparseable ({e})")
            continue
        before = len(hits)
        V(rel).visit(tree)
        # A waiver is written AT the site, so it appears in the diff that introduces it and a
        # reviewer sees it next to the code it excuses. Waivers are counted in the headline rather
        # than silently subtracted -- a gate that hides how much it forgave is not a gate.
        #
        # "At the site" includes the comment block directly ABOVE the statement, not only a
        # trailing comment inside it. Requiring the marker to fall within the expression's own
        # span made comment PLACEMENT load-bearing: tier_b_batches.py:217 carried a two-line
        # waiver immediately above the `if`, which is where anyone would write a reason too long
        # to trail, and the checker reported it as unwaived -- an accusation produced by the
        # instrument's formatting preference rather than by the code. The block is walked upward
        # only while lines are contiguous comments, so nothing distant can reach down and forgive
        # a site.
        lines = src.splitlines()
        kept = []
        for h in hits[before:]:
            span_lines = lines[h["line"] - 1 : h["end"]]
            i = h["line"] - 2
            while i >= 0 and lines[i].lstrip().startswith("#"):
                span_lines.insert(0, lines[i])
                i -= 1
            span = "\n".join(span_lines)
            if WAIVER in span and span.split(WAIVER, 1)[1].strip():
                waived += 1
            else:
                kept.append(h)
        hits[before:] = kept
    sites = list(hits)
    hits[:] = [f"{h['path']}:{h['line']}: bare .get() {h['why']}" for h in hits]
    detail = f"scanned {scanned} checkers for verdict-deciding bare .get()"
    if waived:
        detail += f"; {waived} site(s) waived with a stated reason"
    r.add("absent_is_not_false", not hits, detail, hits)
    # Keep the spans: the self-test has to match a hit against a marker that the formatter may
    # have pushed onto a different line than the call starts on.
    r.checks[-1]["sites"] = sites


def self_test() -> int:
    """Mutation control: prove the checker fires on planted defects and not on benign shapes.

    Expectations are read from the fixture's own `# FLAG` markers rather than hardcoded line
    numbers, so a reformat cannot silently invalidate the control.
    """
    global CHECKERS, REPO
    fx = REPO / "tests/fixtures/evals/absent_is_not_false_fixture.py"
    if not fx.is_file():
        print(f"control fixture missing: {fx}", file=sys.stderr)
        return 2
    src = fx.read_text(encoding="utf-8").splitlines()
    marked = {i for i, ln in enumerate(src, 1) if "# FLAG" in ln}

    saved_c, saved_r = CHECKERS, REPO
    CHECKERS, REPO = [str(fx.relative_to(saved_r))], saved_r
    r = Result()
    check_absent_is_not_false(r)
    CHECKERS, REPO = saved_c, saved_r

    # Match a hit to its marker by SPAN, not by start line. The claim that marker-keyed
    # expectations were reformat-proof was false: ruff split the E-038 line and pushed its
    # `# FLAG` comment two lines below the call, so the control reported a miss AND a false
    # positive for the same site. Same span bug as the waivers, in the control itself.
    sites = r.checks[0].get("sites") or []
    flagged = {h["line"] for h in sites}
    covered = {i for h in sites for i in range(h["line"], h["end"] + 1)} & marked
    missed = sorted(marked - covered)

    # A benign line is one holding a `.get(` that no flagged span covers and that carries no
    # marker anywhere in a flagged span.
    benign = {
        i
        for i, ln in enumerate(src, 1)
        if ".get(" in ln and not any(h["line"] <= i <= h["end"] for h in sites)
    }
    false_pos = sorted(
        {h["line"] for h in sites if not (set(range(h["line"], h["end"] + 1)) & marked)}
    )
    must, must_not = marked, benign
    print(f"mutation control on {fx.name}")
    print(f"  flagged      {sorted(flagged)}")
    print(f"  must-flag    {sorted(must)}  missed={missed}")
    print(f"  must-NOT     {sorted(must_not)}  false positives={false_pos}")
    ok = not missed and not false_pos
    print(
        f"  -> {'DETECTS planted defects, clean on benign shapes' if ok else 'CONTROL FAILED'}"
    )
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", default=".claude/state/full-self-evaluation")
    ap.add_argument("--sha", default="")
    ap.add_argument("--json", default="")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        return self_test()

    state = pathlib.Path(args.state)
    if not (state / "state.json").is_file():
        print(f"no state at {state}", file=sys.stderr)
        return 2
    sha = (
        args.sha
        or subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            cwd=REPO,
        ).stdout.strip()
    )

    r = Result()
    check_mutation_controls(state, sha, r)
    check_derived_scalars(state, r)
    check_input_provenance(state, sha, r)
    check_absent_is_not_false(r)

    print(f"META-CHECK at {sha}\n")
    for c in r.checks:
        print(f"  [{'PASS' if c['pass'] else 'FAIL'}] {c['check']:<22} {c['detail']}")
        for f in c["findings"][:12]:
            print(f"           - {f}")
        if len(c["findings"]) > 12:
            print(f"           ... and {len(c['findings']) - 12} more")
    print(f"\nGATE {'OPEN' if r.ok else 'CLOSED'}")

    if args.json:
        pathlib.Path(args.json).write_text(
            json.dumps({"sha": sha, "gate_open": r.ok, "checks": r.checks}, indent=2)
            + "\n",
            encoding="utf-8",
        )
    return 0 if r.ok else 1


if __name__ == "__main__":
    sys.exit(main())
