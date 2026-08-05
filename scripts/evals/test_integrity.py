"""Scan a commit's test diff for the ways a suite gets quietly weakened.

WHY THIS IS A SCRIPT AND NOT A PARAGRAPH. Gate item 19 asks every accepted change to pass a
test-integrity review. Four changes had been accepted and none had one, so the obvious move was to
read the four diffs and write down that they looked fine. That is an opinion with a timestamp: it
cannot be re-run against the fifth change, it cannot be shown to fail, and the reader has to take
it on trust from the same process that made the changes.

The violation shapes are the ones the run's own safety rules name: deleting a failing test,
weakening an assertion, adding a skip or xfail to go green, lowering a coverage threshold, adding
blanket no-cover pragmas, and replacing real behaviour with an unconditional mock.

WHAT IT CANNOT SEE, stated so the PASS is not read as more than it is. It compares added and
removed lines; it cannot tell a genuinely stronger replacement assertion from a weaker one, and it
cannot tell a legitimate targeted patch from a mock that hollows out the unit. Both are reported as
findings requiring a written justification rather than silently judged, because a checker that
guesses at intent is a checker that can be argued with.

Removals are not automatically violations -- 5801277 deleted a pin whose rationale measurement had
refuted, which is correct. They are findings that must be ANSWERED, in test-integrity.json, keyed
by commit. An unanswered removal fails.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

TEST_PATH = re.compile(r"^\+\+\+ b/(.*(?:^|/)(?:tests?/|test_|conftest)[^\s]*)", re.M)
SKIP_MARK = re.compile(r"pytest\.mark\.(skip|xfail)|pytest\.(skip|xfail)\(")
THRESHOLD = re.compile(r"fail[-_]under\s*[=:]\s*(\d+(?:\.\d+)?)")
NO_COVER = re.compile(r"pragma:\s*no\s*cover")
DEF_TEST = re.compile(r"^\s*(?:async\s+)?def\s+(test_\w+)")
ASSERT = re.compile(r"^\s*assert\b")
BLANKET_MOCK = re.compile(
    r"(MagicMock|Mock)\(\s*\)\s*$|patch\([^)]*autospec\s*=\s*False"
)


def scan_diff(diff: str) -> list[dict]:
    """Findings in one commit's diff. Only hunks touching test files are considered."""
    out: list[dict] = []
    current: str | None = None
    in_test = False
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            current = line[6:]
            in_test = bool(
                re.search(r"(^|/)(tests?)/", current) or "/test_" in f"/{current}"
            )
            continue
        if not in_test or current is None:
            continue
        added, removed = line.startswith("+"), line.startswith("-")
        if not (added or removed):
            continue
        body = line[1:]

        if removed and DEF_TEST.match(body):
            out.append(
                {
                    "kind": "test_removed",
                    "file": current,
                    "detail": DEF_TEST.match(body).group(1),  # type: ignore[union-attr]
                }
            )
        if removed and ASSERT.match(body):
            out.append(
                {"kind": "assertion_removed", "file": current, "detail": body.strip()}
            )
        if added and SKIP_MARK.search(body):
            out.append({"kind": "skip_added", "file": current, "detail": body.strip()})
        if added and NO_COVER.search(body):
            out.append(
                {"kind": "no_cover_added", "file": current, "detail": body.strip()}
            )
        if added and BLANKET_MOCK.search(body):
            out.append(
                {"kind": "blanket_mock_added", "file": current, "detail": body.strip()}
            )
        m = THRESHOLD.search(body)
        if m:
            out.append(
                {
                    "kind": "threshold_" + ("raised_or_set" if added else "removed"),
                    "file": current,
                    "detail": body.strip(),
                }
            )
    return out


def review(sha: str, diff: str, subject: str, answers: dict) -> dict:
    found = scan_diff(diff)
    given = answers.get(sha, {})
    unanswered = [f for f in found if f["kind"] not in given]
    return {
        "commit": sha,
        "subject": subject,
        "findings": found,
        "answered": {
            k: v for k, v in given.items() if any(f["kind"] == k for f in found)
        },
        "unanswered": unanswered,
        "pass": not unanswered,
    }


def self_test() -> int:
    """Two-sided control: the checker must fire on planted weakenings and stay quiet on a real one."""
    planted = (
        "+++ b/tests/test_thing.py\n"
        "-def test_the_important_case():\n"
        "-    assert widget.total() == 7\n"
        "+@pytest.mark.skip(reason='flaky')\n"
        "+def test_the_important_case():\n"
        "+    m = MagicMock()\n"
        "+# pragma: no cover\n"
        "+fail_under = 40\n"
    )
    benign = (
        "+++ b/tests/test_thing.py\n"
        "+def test_a_new_case():\n"
        "+    assert widget.total() == 7\n"
        "+++ b/src/thing.py\n"
        "-    assert legacy_guard()\n"
    )
    got = {f["kind"] for f in scan_diff(planted)}
    want = {
        "test_removed",
        "assertion_removed",
        "skip_added",
        "no_cover_added",
        "blanket_mock_added",
        "threshold_raised_or_set",
    }
    quiet = scan_diff(benign)
    missed, noise = sorted(want - got), [f["kind"] for f in quiet]
    print("mutation control on synthetic diffs")
    print(f"  planted  detected={sorted(got)}  missed={missed}")
    print(f"  benign   findings={noise}")
    ok = not missed and not noise
    print(f"  -> {'DETECTS weakenings, quiet on benign' if ok else 'CONTROL FAILED'}")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--diff-dir",
        default="",
        help="directory of <sha>.diff files (optionally <sha>.subject)",
    )
    ap.add_argument("--answers", default="")
    ap.add_argument("--json", default="")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()

    answers = (
        json.loads(pathlib.Path(a.answers).read_text(encoding="utf-8"))["answers"]
        if a.answers
        else {}
    )
    # Diffs are supplied as files rather than fetched with git. This repo is checked out as a
    # worktree, whose .git is a pointer file into the parent repository, so git cannot run inside
    # the container at all -- and a checker that silently could not read its input would report
    # zero findings and PASS. Producing the diff is host work (git is a control-plane tool);
    # reading it is not.
    dd = pathlib.Path(a.diff_dir)
    if not dd.is_dir():
        print(f"no diff directory at {dd}", file=sys.stderr)
        return 2
    diffs = sorted(dd.glob("*.diff"))
    if not diffs:
        print(f"no *.diff files in {dd}; nothing to review", file=sys.stderr)
        return 2
    rows = []
    for p in diffs:
        sha = p.stem
        subj = dd / f"{sha}.subject"
        rows.append(
            review(
                sha,
                p.read_text(encoding="utf-8"),
                subj.read_text(encoding="utf-8").strip() if subj.is_file() else "",
                answers,
            )
        )
    for r in rows:
        mark = "PASS" if r["pass"] else "FAIL"
        print(f"  [{mark}] {r['commit']}  {r['subject'][:64]}")
        for f in r["findings"]:
            state = "answered" if f["kind"] in r["answered"] else "UNANSWERED"
            print(f"         {state}: {f['kind']} in {f['file']} -- {f['detail'][:70]}")
    ok = sum(1 for r in rows if r["pass"])
    print(f"\n{ok}/{len(rows)} changes pass test-integrity review")
    if a.json:
        pathlib.Path(a.json).write_text(
            json.dumps({"reviewed": rows}, indent=2) + "\n", encoding="utf-8"
        )
    return 0 if ok == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
