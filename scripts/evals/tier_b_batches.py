"""Build Tier B probe batches and grade the results.

Two halves, deliberately separated so the grading cannot be tuned to the prompts:

  build   pick the next N un-probed Tier B components, derive ONE user request per component from
          that component's own `description` frontmatter, and write a mixed prompt per batch that
          also contains decoys matching nothing.
  grade   read each batch's probe.json and decide, per component, whether it triggered when it
          should and stayed silent when it should not.

Why the prompt is derived from the component's own description rather than hand-written: a
hand-written prompt is a prompt I tuned until the skill fired, which measures my prompt-writing,
not the skill. Deriving it mechanically from the description the skill itself advertises makes the
question falsifiable — if a skill does not trigger on a plain restatement of what it says it is
for, that is a criterion-1 finding, not a bad prompt.

This makes the probe a LOWER BOUND on trigger quality and an UPPER BOUND on nothing. A skill that
fires here may still fail on realistic phrasing; a skill that fails here is broken for the case it
was built for. Stated as a concession rather than implied.

Negative evidence comes from two places: explicit decoys inside each batch, and every OTHER batch's
targets — a skill that fires in a batch where it was not a target is a false trigger.

Usage:
  tier_b_batches.py build --count 18 --batches 6 --out <dir>
  tier_b_batches.py grade --probe-dir <dir> --spec <dir>/batches.json
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
STATE = REPO / ".claude/state/full-self-evaluation"

# Requests that must match no kit skill. If one of these pulls a skill in, that skill triggers on
# input it has no business claiming, which is a false positive under criterion 7.
DECOYS = [
    "What is 17 times 4? Just the number.",
    "Rename the local variable `tmp` to `buffer` in a snippet I will paste later.",
    "What day of the week was 3 March 1999?",
]


def frontmatter(path: pathlib.Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    m = re.match(r"^---\n(.*?)\n---", text, re.S)
    if not m:
        return {}
    out: dict = {}
    key = None
    for line in m.group(1).splitlines():
        if re.match(r"^\w[\w-]*:", line):
            key, _, val = line.partition(":")
            out[key.strip()] = val.strip()
        elif key and line.startswith((" ", "\t")):
            out[key] = (out.get(key, "") + " " + line.strip()).strip()
    return out


def request_from_description(desc: str) -> str:
    """Turn a skill description into a user request, mechanically."""
    d = desc.strip().rstrip(".")
    # Descriptions are written for the model ("Use when...", "Helps you..."). Strip the framing so
    # the prompt reads as a user asking for the work, not as a user quoting a manifest.
    d = re.sub(r"^(use (this )?(skill )?(when|for|to)\b[: ]*)", "", d, flags=re.I)
    d = re.sub(r"^(helps? (you )?(to )?)", "", d, flags=re.I)
    d = re.sub(r"\s+", " ", d)
    if len(d) > 220:
        d = d[:220].rsplit(" ", 1)[0]
    return f"I need help with this on my project: {d}."


def build(
    count: int,
    batches: int,
    out: pathlib.Path,
    ids: str = "",
    per_batch: int = 3,
    fixture: str = "",
) -> int:
    man = json.loads((STATE / "component-manifest.json").read_text(encoding="utf-8"))
    comps = man["components"] if isinstance(man, dict) else man
    if ids:
        want = [i.strip() for i in ids.split(",") if i.strip()]
        by = {c["id"]: c for c in comps}
        unknown = [i for i in want if i not in by]
        if unknown:
            print(f"unknown component ids: {unknown}", file=sys.stderr)
            return 2
        chosen = [by[i] for i in want]
    else:
        pool = [
            c
            for c in comps
            if c["tier"] == "B"
            and c.get("dynamic_done") is not True
            # An attempted-but-missed skill re-probed with the same prompt reproduces the same
            # miss. Re-serving it would burn budget re-confirming a finding already recorded.
            and c.get("dynamic_attempted") is not True
            and c["type"] == "skill"
        ]
        pool.sort(key=lambda c: c["id"])
        chosen = pool[:count]
    if not chosen:
        print("no un-probed Tier B skills remain", file=sys.stderr)
        return 2

    targets = []
    for c in chosen:
        fm = frontmatter(REPO / c["path"])
        name = fm.get("name") or c["id"].split(":", 1)[1]
        desc = fm.get("description", "")
        if not desc:
            # No description is itself the answer to criterion 1: nothing can select it reliably.
            targets.append(
                {"id": c["id"], "skill": name, "request": None, "no_description": True}
            )
            continue
        targets.append(
            {
                "id": c["id"],
                "skill": name,
                "request": request_from_description(desc),
                "no_description": False,
            }
        )

    out.mkdir(parents=True, exist_ok=True)
    spec = {"batches": [], "decoys": DECOYS, "fixture": fixture}
    usable = [t for t in targets if t["request"]]
    per = per_batch if per_batch else max(1, -(-len(usable) // batches))
    for i in range(0, len(usable), per):
        group = usable[i : i + per]
        label = f"tb{i // per + 1:02d}"
        lines = [
            "Work through the following independent requests. For each one, do whatever you would",
            "normally do first — if a skill applies, use it. Keep every answer to one or two",
            "sentences; do not write files. Answer them in order.",
            "",
        ]
        items = [t["request"] for t in group] + [DECOYS[(i // per) % len(DECOYS)]]
        for n, req in enumerate(items, 1):
            lines.append(f"{n}. {req}")
        (out / f"{label}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        spec["batches"].append(
            {
                "label": label,
                "targets": group,
                "decoy": items[-1],
                "prompt_file": f"{label}.txt",
                "fixture": fixture,
            }
        )
    (out / "batches.json").write_text(
        json.dumps(spec, indent=2) + "\n", encoding="utf-8"
    )
    nodesc = [t["id"] for t in targets if t["request"] is None]
    print(
        f"built {len(spec['batches'])} batches covering {len(usable)} skills -> {out}"
    )
    if nodesc:
        print(f"NO DESCRIPTION (cannot be selected at all): {nodesc}")
    return 0


def final_result(probe_json: pathlib.Path) -> tuple[str, str]:
    """The session's final result text and its subtype.

    The subtype distinguishes an answer the model chose to end from one the harness cut off
    (`error_max_turns`). A truncated session that never reached the skill is not evidence that
    the skill fails to trigger -- the question was never finished being asked.
    """
    jsonl = probe_json.parent / "session.jsonl"
    if not jsonl.is_file():
        return "", ""
    last, subtype = "", ""
    for line in jsonl.open(encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "result":
            if isinstance(
                ev.get("result"), str
            ):  # absent-ok: a non-string `result` is a non-answer
                last = ev["result"]
            if isinstance(
                ev.get("subtype"), str
            ):  # absent-ok: a missing subtype leaves it "", which no verdict branches on
                subtype = ev["subtype"]
    return last, subtype


def classify(
    skill: str, fired: set[str], own: set[str], prompt: str, answer: str
) -> dict:
    """Score one target. Shared by the batch and standalone graders.

    Standalone runs are what OVERTURN batch verdicts, so they must not be scored by a looser
    rule than the batches they audit. Keeping one classifier is the only way to guarantee that:
    the confirmation path and the audited path cannot drift apart if they are the same code.
    """
    invoked = skill in fired
    circular = skill in prompt
    named = (not invoked) and (not circular) and (skill in answer)
    # A skill whose own name appears in its prompt cannot be scored on NAMED: if the answer says
    # the name, that may be an echo of the question. The guard already refuses to CREDIT it --
    # but calling the result MISSED is the opposite error, and it manufactured a false negative
    # (`backlog`). Unmeasurable is its own outcome.
    inconclusive = (not invoked) and circular and (skill in answer)
    # A sibling skill firing while the target stayed silent is not the same event as silence: the
    # request was recognised and routed elsewhere. Recorded separately so the two cannot be summed
    # into one "failed to trigger" count.
    outsiders = sorted(fired - own)
    substituted = (not invoked) and (not named) and bool(outsiders)
    return {
        "triggered": invoked,
        "named": named,
        "name_in_prompt": circular,
        "outsiders": outsiders if substituted else [],
        "outcome": "INVOKED"
        if invoked
        else (
            "NAMED"
            if named
            else (
                "INCONCLUSIVE"
                if inconclusive
                else ("SUBSTITUTED" if substituted else "MISSED")
            )
        ),
    }


def grade(probe_dir: pathlib.Path, spec_path: pathlib.Path) -> int:
    """Grade selection, not merely tool invocation.

    Criterion 1 is "selects or triggers correctly". The Skill tool call is a PROXY for that, and the
    probes showed it is a lossy one: given a request derived from a skill's own description, the
    model repeatedly answered "that's the description of the `X` skill, not a task" and declined to
    invoke -- while naming X correctly. Selection succeeded; invocation did not follow, because
    there was no concrete task to do. Scoring only tool calls would book those as trigger failures.

    Three outcomes per target:
      INVOKED  the Skill tool ran with this skill        -- criterion 1 satisfied, strongest evidence
      NAMED    the skill is named in the final answer    -- selection demonstrated, invocation withheld
      MISSED   neither                                   -- a real criterion 1 failure

    NAMED is only credited when the skill's own name does NOT appear in the prompt, otherwise the
    model could be echoing the question and the evidence would be circular.
    """
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    probes, texts = {}, {}
    for p in sorted(probe_dir.glob("*/probe.json")):
        doc = json.loads(p.read_text(encoding="utf-8"))
        probes[doc["label"]] = doc
        texts[doc["label"]] = final_result(p)[0]

    all_targets = {t["skill"]: t["id"] for b in spec["batches"] for t in b["targets"]}
    rows, unrun = [], []
    for b in spec["batches"]:
        pr = probes.get(b["label"])
        if pr is None:
            unrun.extend(t["id"] for t in b["targets"])
            continue
        # A session that exited non-zero, or produced no answer at all, did not ask the
        # question. Scoring its targets MISSED turns a harness fault into 40 skill defects --
        # which is what happened when a relative prompt path left every prompt empty.
        #
        # The discriminator is the ANSWER, not the tool calls. Keying this on "made no tool
        # call" was the same error mirrored: two batches answered every request in prose,
        # naming each skill correctly and declining for underspecification -- criteria 1 and 9
        # both passing -- and would have been discarded as never-run.
        fired = set(pr["skills_invoked"])
        own = {t["skill"] for t in b["targets"]}
        prompt = (spec_path.parent / b["prompt_file"]).read_text(encoding="utf-8")
        answer = texts.get(b["label"], "")
        # Asymmetric, as in grade_solo: a broken session cannot support a negative, but a skill
        # that already fired inside it still counts. Blanket-discarding the batch would throw
        # away real passes to avoid false failures -- the E-050 error.
        admissible = pr["session_rc"] == 0 and bool(answer.strip())
        for t in b["targets"]:
            if not admissible and t["skill"] not in fired:
                unrun.append(t["id"])
                continue
            rows.append(
                {
                    "id": t["id"],
                    "skill": t["skill"],
                    "batch": b["label"],
                    **classify(t["skill"], fired, own, prompt, answer),
                    "session_rc": pr["session_rc"],
                }
            )
        # anything that fired but was not a target of THIS batch is a false trigger
        for f in fired - own:
            if f in all_targets:
                rows.append(
                    {
                        "id": all_targets[f],
                        "skill": f,
                        "batch": b["label"],
                        "false_trigger": True,
                        "session_rc": pr["session_rc"],
                    }
                )

    fired_n = sum(1 for r in rows if r.get("triggered") is True)
    named_n = sum(1 for r in rows if r.get("named") is True)
    total = sum(1 for r in rows if "triggered" in r)
    false_n = sum(1 for r in rows if r.get("false_trigger") is True)
    circ = sum(1 for r in rows if r.get("name_in_prompt") is True)
    print(f"batches run {len(probes)}/{len(spec['batches'])}")
    print(f"INVOKED (tool call)      : {fired_n}/{total}")
    print(f"NAMED   (selected, not invoked): {named_n}/{total}")
    incon_n = sum(1 for r in rows if r.get("outcome") == "INCONCLUSIVE")
    sub_n = sum(1 for r in rows if r.get("outcome") == "SUBSTITUTED")
    print(f"SUBSTITUTED (a sibling skill fired instead): {sub_n}/{total}")
    print(f"INCONCLUSIVE (own name in prompt, cannot score): {incon_n}/{total}")
    print(
        f"MISSED (silent)          : {total - fired_n - named_n - incon_n - sub_n}/{total}"
    )
    print(f"false triggers           : {false_n}")
    if circ:
        print(f"NAMED not creditable (own name in prompt): {circ}")
    if unrun:
        print(f"UNRUN (not measured, not a pass): {len(unrun)}")
    for r in sorted(rows, key=lambda r: (r.get("outcome") or "Z", r["skill"])):
        mark = (
            "FIRED"
            if r.get("triggered")
            else ("FALSE" if r.get("false_trigger") else "silent")
        )
        print(f"  [{mark:<6}] {r['batch']}  {r['skill']}")
    (probe_dir / "grades.json").write_text(
        json.dumps({"rows": rows, "unrun": unrun}, indent=2) + "\n", encoding="utf-8"
    )
    return 0


RANK = ["INVOKED", "NAMED", "SUBSTITUTED", "INCONCLUSIVE", "MISSED"]


def grade_solo(probe_dir: pathlib.Path, installed_file: str) -> int:
    """Grade standalone single-skill probes with the batch grader's own rules.

    A standalone run exists to CONFIRM or OVERTURN a batch MISSED. It therefore inherits every
    guard the batch path has: a session that exited non-zero or produced no answer is UNRUN, not
    a failure. `error_max_turns` lands here -- the harness stopped the session, so silence up to
    that point says nothing about the skill.

    A skill probed more than once is scored on its BEST admissible run: one confirmed trigger
    refutes "it does not trigger". The fire ratio is reported alongside so a flaky trigger cannot
    hide behind a single success.
    """
    installed: set[str] = set()
    if installed_file:
        installed = set(
            pathlib.Path(installed_file).read_text(encoding="utf-8").split()
        )

    per: dict[str, list[dict]] = {}
    for p in sorted(probe_dir.glob("*/probe.json")):
        doc = json.loads(p.read_text(encoding="utf-8"))
        label = doc["label"]
        if "-" not in label:
            continue
        skill = label.split("-", 1)[1]
        answer, subtype = final_result(p)
        prompt_file = p.parent / "prompt.txt"
        prompt = (
            prompt_file.read_text(encoding="utf-8") if prompt_file.is_file() else ""
        )
        row = {"run": p.parent.name, "subtype": subtype, "rc": doc["session_rc"]}
        # The admissibility guard is ASYMMETRIC on purpose. A session that died or was cut off
        # cannot support a NEGATIVE -- silence up to the cut says nothing. It can still support a
        # POSITIVE: a Skill tool call that already happened did happen, and no later truncation
        # unmakes it. Discarding such a run is the E-050 error again, throwing away a correct
        # pass to be safe.
        if installed and skill not in installed:
            # Not installed is not a trigger failure -- there was nothing to trigger.
            row["outcome"] = "NOT_INSTALLED"
        elif skill not in set(doc["skills_invoked"]) and (
            doc["session_rc"] != 0 or not answer.strip()
        ):
            row["outcome"] = "UNRUN"
        else:
            row.update(
                classify(skill, set(doc["skills_invoked"]), {skill}, prompt, answer)
            )
        per.setdefault(skill, []).append(row)

    out = []
    for skill, runs in sorted(per.items()):
        adm = [r for r in runs if r["outcome"] not in ("UNRUN", "NOT_INSTALLED")]
        if not adm:
            best = runs[0]["outcome"]
        else:
            best = min((r["outcome"] for r in adm), key=RANK.index)
        out.append(
            {
                "skill": skill,
                "outcome": best,
                "runs": len(runs),
                "admissible": len(adm),
                "invoked_runs": sum(1 for r in adm if r["outcome"] == "INVOKED"),
                "detail": runs,
            }
        )

    for r in out:
        print(
            "%-34s %-14s admissible=%d/%d invoked=%d"
            % (r["skill"], r["outcome"], r["admissible"], r["runs"], r["invoked_runs"])
        )
    tally: dict[str, int] = {}
    for r in out:
        tally[r["outcome"]] = tally.get(r["outcome"], 0) + 1
    print("\n" + json.dumps(tally, sort_keys=True))
    (probe_dir / "grades-solo.json").write_text(
        json.dumps(out, indent=2) + "\n", encoding="utf-8"
    )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--count", type=int, default=18)
    b.add_argument("--batches", type=int, default=6)
    b.add_argument("--out", required=True)
    b.add_argument(
        "--ids", default="", help="explicit component ids instead of the next N"
    )
    b.add_argument("--per", type=int, default=3, help="targets per batch")
    b.add_argument("--fixture", default="", help="fixture name recorded in the spec")
    g = sub.add_parser("grade")
    g.add_argument("--probe-dir", required=True)
    g.add_argument("--spec", required=True)
    s = sub.add_parser("grade-solo")
    s.add_argument("--probe-dir", required=True)
    s.add_argument("--installed", default="", help="file listing installed skill names")
    a = ap.parse_args()
    if a.cmd == "build":
        return build(a.count, a.batches, pathlib.Path(a.out), a.ids, a.per, a.fixture)
    if a.cmd == "grade-solo":
        return grade_solo(pathlib.Path(a.probe_dir), a.installed)
    return grade(pathlib.Path(a.probe_dir), pathlib.Path(a.spec))


if __name__ == "__main__":
    sys.exit(main())
