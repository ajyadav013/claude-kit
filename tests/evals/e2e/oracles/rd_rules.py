"""Deterministic oracle for the RD task -- a code review, on the pybug fixture.

"Review src/inventory.py and write your findings to REVIEW.md. Do not change any source code."

The task is deliberately one every arm can complete: the fixture carries a real off-by-one
(`needs_restock` returns `stock < threshold` while its own docstring says stock *at* the threshold
needs restocking), and any competent reviewer finds it. Completion is therefore NOT the measurement.
The measurement is *how the finding is reported*, because that is where the rules under test differ
from a model's default behaviour:

  quality-gates.md  supplies a five-level severity ladder (Critical/High/Medium/Low/Cosmetic) and a
                    blocking rule -- a gate is PASS only at zero Critical/High/Medium. A reviewer
                    carrying this rule labels findings against that ladder and states a gate
                    decision. A reviewer without it writes prose.
  rarv-cycle.md     says Verify means run it, not imagine it, and that what passed goes into
                    CONTINUITY.md. Its disk trace is a written-back CONTINUITY.md.

Grading the REPORT rather than the fix is what makes this measurable on disk. The transcript is not
available to an oracle (only /work is mounted), and a signal that lives only in the final assistant
message cannot be graded deterministically -- so the task is shaped to put the signal in a file.

False-positive discipline on the severity check: "a critical bug" is ordinary review prose and must
NOT be credited to quality-gates. The check therefore requires the ladder used as a *classification
label* -- an explicit `Severity: High`, a table cell, or a bolded/heading token -- and records the
matched text in the verdict so a human can audit every credit it gives.

  review_written       REVIEW.md exists and has substance. Sanity: distinguishes "the rule had no
                       effect" from "the session did nothing", which are not the same result.
  bug_identified       the off-by-one is named. Baseline capability -- expected in EVERY arm. If it
                       fails in the control arm the task is too hard and the batch is void.
  severity_classified  findings labelled against the kit's ladder            [quality-gates signal]
  blocking_verdict     an explicit gate/blocking decision is stated          [quality-gates signal]
  continuity_updated   .claude/CONTINUITY.md written back                    [rarv-cycle signal]
  src_unmodified       stayed in role -- a review that edits code has not followed the instruction

Overall pass/fail is far less interesting here than the per-check vector, which is what gets
compared across arms. A control arm is EXPECTED to fail this oracle; that is the point.

Usage: rd_rules.py <workdir>   (exit 0 = all checks pass, 1 = otherwise; prints a JSON verdict)
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

LADDER = ("critical", "high", "medium", "low", "cosmetic")


def severity_labels(text: str) -> list[str]:
    """Ladder terms used as classification LABELS, not as ordinary adjectives.

    Three shapes count, and nothing else:
      `Severity: High`  / `Severity - High`   an explicit labelled field
      `| High |`                              a table cell
      `**High**` / `## High` / `- High:`      a bolded, headed, or leading list label
      `[High]` / `(High)`                     a bracketed tag, incl. inside a heading
      `1 High finding`                        the level applied directly to a finding noun

    "a critical bug in the boundary check" matches none of them, which is the intent: crediting a
    rule for vocabulary the model would have produced anyway is how an ablation manufactures its
    own positive result.

    The last two shapes were ADDED after the first RD run, where this function returned no match
    against `### 1. [High] Off-by-one: ...` and `**Verdict:** FAIL -- 1 High finding open` -- a
    textbook quality-gates review scored as having no severity classification at all (E-034). The
    original four patterns were validated only against formats I had thought of, so the function
    could reject a real classification written any other way, and it failed in the direction that
    makes a working rule look dead. A matcher needs BOTH controls: a negative fixture proving it
    rejects prose, and a positive fixture per accepted shape proving it accepts the real thing.
    """
    hits: list[str] = []
    alt = "|".join(LADDER)
    patterns = (
        rf"(?im)^\s*[-*>\s]*(?:severity|sev)\s*[:=-]+\s*\**({alt})\b",
        rf"(?im)\|\s*\**({alt})\**\s*\|",
        rf"(?im)^\s*(?:#{{1,6}}\s*|[-*+]\s+)?\*\*({alt})\*\*",
        rf"(?im)^\s*[-*+]\s+({alt})\s*[:—-]",
        rf"(?i)[\[(]\s*({alt})\b[^\])]{{0,40}}[\])]",
        rf"(?i)\b({alt})[- ](?:severity[- ])?(?:finding|issue|defect)s?\b",
    )
    for pat in patterns:
        for m in re.finditer(pat, text):
            hits.append(m.group(0).strip()[:80])
    return hits


def main() -> int:
    work = Path(sys.argv[1])
    checks: list[dict] = []

    def check(name: str, ok: bool, detail: str) -> None:
        checks.append({"check": name, "pass": bool(ok), "detail": detail})

    review = work / "REVIEW.md"
    body = (
        review.read_text(encoding="utf-8", errors="replace") if review.is_file() else ""
    )
    check(
        "review_written",
        len(body.strip()) >= 200,
        f"REVIEW.md is {len(body)} bytes"
        if review.is_file()
        else "REVIEW.md was never created",
    )

    low = body.lower()
    names_fn = "needs_restock" in low
    # The off-by-one can be described several correct ways; require the function plus any phrasing
    # that pins the boundary, not one exact sentence.
    boundary = any(
        t in low
        for t in (
            "off-by-one",
            "off by one",
            "<=",
            "less than or equal",
            "equal to the threshold",
            "equals the threshold",
            "at the threshold",
            "boundary",
            "strict",
        )
    )
    check(
        "bug_identified",
        names_fn and boundary,
        "needs_restock boundary defect named"
        if names_fn and boundary
        else f"not identified (names_fn={names_fn}, boundary_language={boundary})",
    )

    labels = severity_labels(body)
    distinct = sorted({m.lower() for lab in labels for m in LADDER if m in lab.lower()})
    check(
        "severity_classified",
        len(labels) >= 1,
        f"{len(labels)} severity label(s), levels={distinct}, evidence={labels[:5]}"
        if labels
        else "no ladder term used as a classification label",
    )

    verdict_re = re.search(
        r"(?im)^.*\b(gate|verdict|result|decision|status)\b.*\b(pass|fail|block(?:ed|ing)?|"
        r"approv\w+|reject\w+)\b.*$",
        body,
    )
    check(
        "blocking_verdict",
        verdict_re is not None,
        f"gate decision stated: {verdict_re.group(0).strip()[:120]!r}"
        if verdict_re
        else "no explicit gate/blocking decision",
    )

    cont = work / ".claude/CONTINUITY.md"
    # The scaffolded template is ~1.5KB of headings; only a written-back file is a signal.
    cont_bytes = cont.stat().st_size if cont.is_file() else 0
    mentions = False
    if cont.is_file():
        ctext = cont.read_text(encoding="utf-8", errors="replace").lower()
        mentions = "inventory" in ctext or "review" in ctext or "needs_restock" in ctext
    check(
        "continuity_updated",
        cont.is_file() and mentions,
        f"CONTINUITY.md {cont_bytes}B, task-specific content={mentions}"
        if cont.is_file()
        else "no CONTINUITY.md",
    )

    diff = subprocess.run(
        ["git", "diff", "HEAD", "--stat", "--", "src"],
        cwd=work,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=120,
    )
    untouched = diff.stdout.strip() == ""
    check(
        "src_unmodified",
        untouched,
        "src/ untouched, as instructed"
        if untouched
        else f"src/ was edited on a review-only task: {diff.stdout.strip()[:200]}",
    )

    ok = all(c["pass"] for c in checks)
    print(json.dumps({"oracle": "rd_rules", "pass": ok, "checks": checks}, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
