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
import tempfile
import time

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

    # The background-job assertions need the same proof. A wait_for that silently passes on a file
    # that never appears would turn every detached-hook scenario into a no-op.
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        missing = {"wait_for": {"path": "never.txt", "substring": "x", "timeout_s": 1}}
        if not check_async(missing, root):
            print(
                "SELFTEST FAILED: wait_for accepted a file that never appeared",
                file=sys.stderr,
            )
            return False
        (root / "there.txt").write_text("SHIMWROTE")
        if check_async(
            {
                "wait_for": {
                    "path": "there.txt",
                    "substring": "SHIMWROTE",
                    "timeout_s": 1,
                }
            },
            root,
        ):
            print(
                "SELFTEST FAILED: wait_for rejected a file that was there",
                file=sys.stderr,
            )
            return False
        if not check_async(
            {
                "file_absent": {
                    "path": "there.txt",
                    "substring": "SHIMWROTE",
                    "settle_s": 0,
                }
            },
            root,
        ):
            print(
                "SELFTEST FAILED: file_absent accepted a file that was written",
                file=sys.stderr,
            )
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


def build_fixture(sc, idx):
    """Materialise a scratch project for hooks that read the filesystem, not just stdin.

    The loaders, audit-log, warn-missing-tests and guard-secrets all resolve CLAUDE_PROJECT_DIR and
    read or write real files, so a stdin-only harness can never fire them. Each scenario gets its
    own directory: a shared one would let an earlier scenario's audit.log or git index decide a
    later scenario's verdict.
    """
    fx = sc.get("fixture")
    if not fx:
        return None, {}
    root = pathlib.Path(tempfile.mkdtemp(prefix=f"hookfx{idx}-"))
    for rel, content in (fx.get("files") or {}).items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    if fx.get("git"):
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "eval",
            "GIT_AUTHOR_EMAIL": "eval@local",
            "GIT_COMMITTER_NAME": "eval",
            "GIT_COMMITTER_EMAIL": "eval@local",
        }
        # "init" leaves the files UNTRACKED on purpose. lint-fix scopes itself to changed files via
        # `git diff HEAD` plus `git ls-files --others`, and a fixture that stages everything has no
        # HEAD and no untracked files -- so the scoped path finds nothing and the hook correctly
        # does nothing, which would read as a broken hook rather than a broken fixture.
        cmds = [["git", "init", "-q"]]
        if fx["git"] != "init":
            cmds.append(["git", "add", "-A"])
        for cmd in cmds:
            subprocess.run(cmd, cwd=root, capture_output=True, env=env, timeout=60)
    envv = {
        k: v.replace("@@FIXTURE@@", str(root)) for k, v in (fx.get("env") or {}).items()
    }

    # PATH shims. capture-learnings and capture-ticket-telemetry both guard on `command -v <tool>`
    # and then shell out to it from a detached background job. Letting the real tools run would mean
    # spawning a live `claude` session per scenario, so the DEPENDENCY is replaced by a recording
    # double -- the hook under test is untouched, and what we assert is the decision it made and the
    # argv it built.
    if fx.get("bin"):
        bindir = root / ".bin"
        bindir.mkdir(parents=True, exist_ok=True)
        for name, body in fx["bin"].items():
            p = bindir / name
            p.write_text(body.replace("@@FIXTURE@@", str(root)), encoding="utf-8")
            p.chmod(0o755)
        envv["PATH"] = f"{bindir}:{os.environ.get('PATH', '')}"
    return root, envv


def check_async(exp, root):
    """Assertions about work a hook pushed into a detached background job.

    `wait_for` polls, because the hook returns before its child has done anything. `file_absent`
    sleeps first and then asserts nothing appeared -- without the settle time it would pass simply
    by looking too early, which is the no-fire equivalent of not running the test at all.
    """
    bad = []
    wf = exp.get("wait_for")
    if wf:
        target = root / wf["path"]
        deadline = time.monotonic() + wf.get("timeout_s", 20)
        seen = ""
        while time.monotonic() < deadline:
            if target.is_file():
                seen = target.read_text(encoding="utf-8", errors="replace")
                if wf["substring"] in seen:
                    break
            time.sleep(0.2)
        else:
            bad.append(
                f"{wf['path']} never contained {wf['substring']!r} "
                f"(exists={target.is_file()}, got {seen.strip()[:160]!r})"
            )
    fa = exp.get("file_absent")
    if fa:
        time.sleep(fa.get("settle_s", 3))
        target = root / fa["path"]
        if target.is_file() and (
            fa.get("substring") is None
            or fa["substring"] in target.read_text(encoding="utf-8", errors="replace")
        ):
            what = (
                f"gained {fa['substring']!r}" if fa.get("substring") else "was created"
            )
            bad.append(f"{fa['path']} {what} when the hook should have stayed idle")
    return bad


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
    for idx, sc in enumerate(spec["scenarios"]):
        script = repo / "hooks/scripts" / sc["script"]
        fx_root, fx_env = build_fixture(sc, idx)
        payload = json.dumps(build_stdin(sc))
        if fx_root:
            # warn-missing-tests walks the real tree looking for a sibling test, so the path it is
            # handed has to point INTO the fixture, not at a made-up /proj prefix.
            payload = payload.replace("@@FIXTURE@@", str(fx_root))
        p = subprocess.run(
            ["bash", str(script), *(sc.get("argv") or [])],
            input=payload,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(fx_root) if fx_root else None,
            env={**os.environ, **fx_env} if fx_env else None,
        )
        bad = grade(sc["expect"], p.returncode, p.stdout, p.stderr)
        # Side-effect hooks (audit-log) prove themselves on disk, not on stdout.
        fc = sc["expect"].get("file_contains")
        if fc:
            target = (fx_root or pathlib.Path(".")) / fc["path"]
            if not target.is_file():
                bad.append(f"expected file {fc['path']} was not created")
            elif fc["substring"] not in target.read_text(
                encoding="utf-8", errors="replace"
            ):
                bad.append(f"{fc['path']} missing {fc['substring']!r}")
        if fx_root:
            bad += check_async(sc["expect"], fx_root)
        ok = not bad
        # An advisory that fires must emit the JSON envelope Claude Code actually reads; a bare
        # message on stdout would be silently discarded in production. Side-effect hooks are
        # exempt: they are required to keep stdout clean, which is the opposite obligation. That
        # covers both kinds of side effect -- a file written inline (file_contains) and one written
        # by a detached background job (wait_for).
        side_effect = bool(fc) or bool(sc["expect"].get("wait_for"))
        if (
            ok
            and sc["kind"] == "fire"
            and sc["expect"].get("exit") == 0
            and not side_effect
        ):
            if ADVISORY_MARKER not in p.stdout and not sc.get("emits_plain_context"):
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
