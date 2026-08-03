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


def build(count: int, batches: int, out: pathlib.Path) -> int:
    man = json.loads((STATE / "component-manifest.json").read_text(encoding="utf-8"))
    comps = man["components"] if isinstance(man, dict) else man
    pool = [
        c
        for c in comps
        if c["tier"] == "B"
        and c.get("dynamic_done") is not True
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
    spec = {"batches": [], "decoys": DECOYS}
    usable = [t for t in targets if t["request"]]
    per = max(1, -(-len(usable) // batches))
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


def grade(probe_dir: pathlib.Path, spec_path: pathlib.Path) -> int:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    probes = {}
    for p in sorted(probe_dir.glob("*/probe.json")):
        doc = json.loads(p.read_text(encoding="utf-8"))
        probes[doc["label"]] = doc

    all_targets = {t["skill"]: t["id"] for b in spec["batches"] for t in b["targets"]}
    rows, unrun = [], []
    for b in spec["batches"]:
        pr = probes.get(b["label"])
        if pr is None:
            unrun.extend(t["id"] for t in b["targets"])
            continue
        fired = set(pr["skills_invoked"])
        own = {t["skill"] for t in b["targets"]}
        for t in b["targets"]:
            rows.append(
                {
                    "id": t["id"],
                    "skill": t["skill"],
                    "batch": b["label"],
                    "triggered": t["skill"] in fired,
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

    fired_n = sum(1 for r in rows if r.get("triggered"))
    total = sum(1 for r in rows if "triggered" in r)
    false_n = sum(1 for r in rows if r.get("false_trigger"))
    print(f"batches run {len(probes)}/{len(spec['batches'])}")
    print(f"triggered on own request : {fired_n}/{total}")
    print(f"false triggers           : {false_n}")
    if unrun:
        print(f"UNRUN (not measured, not a pass): {len(unrun)}")
    for r in sorted(rows, key=lambda r: (not r.get("triggered"), r["skill"])):
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


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--count", type=int, default=18)
    b.add_argument("--batches", type=int, default=6)
    b.add_argument("--out", required=True)
    g = sub.add_parser("grade")
    g.add_argument("--probe-dir", required=True)
    g.add_argument("--spec", required=True)
    a = ap.parse_args()
    if a.cmd == "build":
        return build(a.count, a.batches, pathlib.Path(a.out))
    return grade(pathlib.Path(a.probe_dir), pathlib.Path(a.spec))


if __name__ == "__main__":
    sys.exit(main())
