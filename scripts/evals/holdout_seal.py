"""Seal the holdout suite so its expectations cannot be edited after seeing a result.

"Do not modify a holdout expected result after seeing candidate output" is a rule the evaluation
spec states and that nothing was enforcing. A promise made by the same party that benefits from
breaking it is not a control. This records a sha256 of the holdout file BEFORE it runs and refuses
to grade against a changed one.

Reseal is allowed, because a holdout suite that can never grow is a dead one -- but it is loud: it
demands a written reason and appends to a history that keeps every prior hash. A silent edit is
what this prevents, not editing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
SUITE = REPO / "tests/evals/holdouts/accepted_changes.py"
SEAL = REPO / "tests/evals/holdouts/holdout-seal.json"


def _digest() -> str:
    return hashlib.sha256(SUITE.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("action", choices=["seal", "verify", "reseal"])
    ap.add_argument("--reason", help="required for reseal")
    ap.add_argument("--at", default="unstamped", help="ISO date of the seal")
    args = ap.parse_args()

    now = _digest()
    doc = json.loads(SEAL.read_text(encoding="utf-8")) if SEAL.is_file() else None

    if args.action == "verify":
        if doc is None:
            print(
                "UNSEALED: no seal recorded; a holdout suite must be sealed before it grades"
            )
            return 2
        if doc["sha256"] != now:
            print(
                "SEAL BROKEN: the holdout suite changed since it was sealed",
                file=sys.stderr,
            )
            print(f"  sealed:  {doc['sha256']}", file=sys.stderr)
            print(f"  current: {now}", file=sys.stderr)
            print(
                "  reseal with a written reason if the change is legitimate.",
                file=sys.stderr,
            )
            return 1
        print(f"seal OK ({now[:12]}, sealed {doc['sealed_at']})")
        return 0

    if args.action == "seal" and doc is not None:
        if doc["sha256"] == now:
            print("already sealed at this hash")
            return 0
        print(
            "refusing: already sealed at a different hash; use reseal --reason",
            file=sys.stderr,
        )
        return 2

    if args.action == "reseal" and not args.reason:
        print("refusing: reseal requires --reason", file=sys.stderr)
        return 2

    history = list((doc or {}).get("history", []))
    if doc is not None:
        history.append(
            {
                "sha256": doc["sha256"],
                "sealed_at": doc["sealed_at"],
                "superseded_by": args.reason,
            }
        )
    SEAL.write_text(
        json.dumps(
            {
                "suite": str(SUITE.relative_to(REPO)),
                "sha256": now,
                "sealed_at": args.at,
                "reason": args.reason or "initial seal",
                "history": history,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"sealed {SUITE.name} at {now[:12]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
