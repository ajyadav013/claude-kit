"""Execute the deterministic hook fire / no-fire scenarios and grade them.

Runs INSIDE Docker (asserts /.dockerenv) because the scripts shell out to jq, git and friends and
the host control plane must not execute project code.

The grading contract, by script class:
  blocker   fires  -> exit 2 and BLOCKED on stderr;  quiet -> exit 0 and empty stdout
  advisory  fires  -> exit 0 and a hookSpecificOutput JSON object on stdout;  quiet -> empty stdout

A no-fire case is not filler. Several of them are the NEAR MISSES a script's own header claims to
spare -- `feature/main-ui` for guard-push-main, `git clean -n` for guard-destructive-git,
`kubectl scale --replicas=0` for guard-kubectl-delete. Those are the false-positive controls
(measure 7), and they are where a guard is most likely to be wrong.

Self-test: before reporting anything, the runner grades a known result against a deliberately wrong
expectation and asserts the comparison FAILS. A checker that cannot fail reports CLEAN on a broken
payload, which is the failure mode this whole program exists to catch -- including in itself.
"""

import json
import os
import pathlib
import subprocess
import sys

ADVISORY_MARKER = "hookSpecificOutput"


def grade(exp, rc, out, err):
    """Return a list of human-readable mismatches. Empty list == the scenario passed."""
    bad = []
    if "exit" in exp and rc != exp["exit"]:
        bad.append(f"exit {rc} != expected {exp['exit']}")
    if exp.get("stdout_empty") and out.strip():
        bad.append(f"expected empty stdout, got {out.strip()[:120]!r}")
    if "stdout_contains" in exp and exp["stdout_contains"] not in out:
        bad.append(f"stdout missing {exp['stdout_contains']!r}")
    if "stderr_contains" in exp and exp["stderr_contains"] not in err:
        bad.append(f"stderr missing {exp['stderr_contains']!r}")
    return bad


def selftest():
    """Prove `grade` can fail. If this passes silently, every result below is worthless."""
    checks = [
        ({"exit": 0}, 2, "", ""),
        ({"stdout_empty": True}, 0, "noise", ""),
        ({"stdout_contains": "nope"}, 0, "", ""),
        ({"stderr_contains": "nope"}, 0, "", ""),
    ]
    for exp, rc, out, err in checks:
        if not grade(exp, rc, out, err):
            print(
                f"SELFTEST FAILED: grade() accepted a wrong result for {exp}",
                file=sys.stderr,
            )
            return False
    # ...and that it accepts a correct one, so it is not merely rejecting everything.
    if grade({"exit": 0, "stdout_empty": True}, 0, "", ""):
        print("SELFTEST FAILED: grade() rejected a correct result", file=sys.stderr)
        return False
    return True


def build_stdin(sc):
    if "stdin" in sc:
        return sc["stdin"]
    payload = json.loads(json.dumps(sc["stdin_template"]))
    body = payload["tool_input"]["content"]
    if body.startswith("@@LINES:"):
        n = int(body.split(":")[1].rstrip("@"))
        payload["tool_input"]["content"] = "\n".join(f"line {i}" for i in range(n))
    return payload


def main():
    if not pathlib.Path("/.dockerenv").is_file():
        print("refusing to run outside Docker (no /.dockerenv)", file=sys.stderr)
        return 3
    if not selftest():
        return 3

    here = pathlib.Path(__file__).resolve().parent
    repo = pathlib.Path(os.environ.get("HOOK_REPO", "/repo"))
    spec = json.loads((here / "hook-scenarios.json").read_text())

    results, per_script = [], {}
    for sc in spec["scenarios"]:
        script = repo / "hooks/scripts" / sc["script"]
        payload = json.dumps(build_stdin(sc))
        p = subprocess.run(
            ["bash", str(script)],
            input=payload,
            capture_output=True,
            text=True,
            timeout=60,
        )
        bad = grade(sc["expect"], p.returncode, p.stdout, p.stderr)
        ok = not bad
        # An advisory that fires must emit the JSON envelope Claude Code actually reads; a bare
        # message on stdout would be silently discarded in production.
        if ok and sc["kind"] == "fire" and sc["expect"].get("exit") == 0:
            if ADVISORY_MARKER not in p.stdout:
                ok, bad = (
                    False,
                    [f"advisory fired without a {ADVISORY_MARKER} envelope"],
                )
        results.append(
            {
                "id": sc["id"],
                "script": sc["script"],
                "kind": sc["kind"],
                "ok": ok,
                "exit": p.returncode,
                "mismatches": bad,
                "stdout_head": p.stdout[:200],
                "stderr_head": p.stderr[:200],
            }
        )
        s = per_script.setdefault(
            sc["script"], {"fire": 0, "nofire": 0, "fire_ok": 0, "nofire_ok": 0}
        )
        s[sc["kind"]] += 1
        if ok:
            s[f"{sc['kind']}_ok"] += 1

    # A script is only credited when it BOTH fires when it should and stays quiet when it should.
    # Crediting on fire alone would pass a hook that blocks everything.
    for name, s in per_script.items():
        s["component"] = f"hook-script:{name}"
        # Parenthesised deliberately: a conditional expression binds LOOSER than `|`, so the
        # unbracketed form parses as `{1,3} if fired else (set() | {7} if quiet else set())` and
        # silently drops the false-positive credit whenever the fire cases pass.
        fired_ok = bool(s["fire"]) and s["fire_ok"] == s["fire"]
        quiet_ok = bool(s["nofire"]) and s["nofire_ok"] == s["nofire"]
        s["measures"] = sorted(
            ({1, 3} if fired_ok else set()) | ({7} if quiet_ok else set())
        )
        s["complete"] = (
            s["fire"] > 0
            and s["nofire"] > 0
            and s["fire_ok"] == s["fire"]
            and s["nofire_ok"] == s["nofire"]
        )

    failed = [r for r in results if not r["ok"]]
    out = {
        "selftest": "passed — grade() rejects wrong results and accepts correct ones",
        "dockerenv_verified": True,
        "total": len(results),
        "passed": len(results) - len(failed),
        "failed": len(failed),
        "scripts_covered": len(per_script),
        "scripts_complete": sum(1 for s in per_script.values() if s["complete"]),
        "per_script": per_script,
        "failures": failed,
        "results": results,
    }
    print(json.dumps(out, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
