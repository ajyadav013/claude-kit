"""Stamp the commit a coverage report was generated at into the report itself.

Coverage reports do not record what they measured. `coverage.json` carries a timestamp and
nothing else, so a report and a working tree can drift apart silently and there is no field to
notice it by. E-029: the file named `latest-coverage.json` was the OLDEST of four snapshots and
produced a confident high-severity finding against `upgrader.py` describing a state that had
stopped existing an hour earlier, when F-010 and F-012 were fixed.

The fix has to be at generation time. Stamping later means trusting whoever ran it to remember
which tree it came from, which is the same trust that failed.

Usage:
    stamp-coverage-provenance.py <coverage.json> <sha> [--dirty] [--out <path>]

`--dirty` records that the tree had uncommitted changes when coverage ran, so a consumer can
tell "measured at a7e229b" from "measured at a7e229b plus edits". A stamp that cannot express
that would launder a dirty measurement into a clean-looking provenance claim.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("report")
    ap.add_argument("sha")
    ap.add_argument(
        "--generated-at", default="", help="ISO timestamp of the coverage run"
    )
    ap.add_argument(
        "--dirty",
        action="store_true",
        help="the working tree had uncommitted changes when coverage ran",
    )
    ap.add_argument("--out", default="", help="write here instead of in place")
    args = ap.parse_args()

    path = pathlib.Path(args.report)
    if not path.is_file():
        print(f"no such coverage report: {path}", file=sys.stderr)
        return 2

    doc = json.loads(path.read_text(encoding="utf-8"))
    if "files" not in doc:
        print(f"{path} does not look like a coverage json report", file=sys.stderr)
        return 2

    existing = (doc.get("ck_provenance") or {}).get("sha")
    if existing and existing != args.sha:
        # Re-stamping a report with a different commit is how a stale report becomes a
        # fresh-looking one. Refuse; regenerate instead.
        print(
            f"{path} is already stamped at {existing}; refusing to re-stamp it as {args.sha}. "
            "Regenerate coverage rather than relabelling it.",
            file=sys.stderr,
        )
        return 3

    doc["ck_provenance"] = {
        "sha": args.sha,
        "dirty": bool(args.dirty),
        "generated_at": args.generated_at or doc.get("meta", {}).get("timestamp", ""),
        "stamped_by": "scripts/evals/stamp-coverage-provenance.py",
    }

    out = pathlib.Path(args.out) if args.out else path
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_text(json.dumps(doc), encoding="utf-8")
    os.replace(tmp, out)
    print(f"stamped {out} sha={args.sha} dirty={bool(args.dirty)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
