"""Holdout checks for the four accepted changes (terminal gate item 16).

A holdout is a check the implementation was NOT tuned against. The controls that shipped with each
change prove it does what its author aimed at; these ask whether it does what the change CLAIMED,
on inputs its author never wrote down. Passing your own controls is table stakes -- an
implementation optimised for exact fixture text passes those and nothing else.

Every expectation here is declared as `expect`, next to the case, and the whole file is sealed by
sha256 in `holdout-seal.json`. Editing an expectation after seeing a result changes the hash, and
the runner refuses to grade against a broken seal. That converts "do not move the goalposts" from
a promise into something a machine checks.

Deliberately NOT holdouts, and why: anything that merely re-runs a shipped control, and anything
whose expected value I would have to look up from the implementation to write down. Both would
pass by construction.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = pathlib.Path(os.environ.get("HOLDOUT_REPO", HERE.parents[3]))

sys.path.insert(0, str(REPO / "tests/evals/hooks"))


# --------------------------------------------------------------------------------------------
# 9711e14 -- secret guard. Credential shapes no shipped scenario uses.
# --------------------------------------------------------------------------------------------
SECRET_CASES = [
    {
        "id": "holdout/9711e14/fire-mongodb-uri-credential",
        "why": "the shipped fire cases are postgres and redis; mongodb is the same shape, unseen",
        "files": {
            "conf.py": 'DSN = "mongodb://svc:Xk29rLmQ8vTz4Wb7Np@cluster0.example.net/app"\n'
        },
        "expect_blocked": True,
    },
    {
        "id": "holdout/9711e14/fire-openssh-private-key",
        "why": "the PEM header the guard matches has an OPENSSH spelling no scenario exercises",
        "files": {
            "id_ed25519.txt": "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaA==\n"
        },
        "expect_blocked": True,
    },
    {
        "id": "holdout/9711e14/nofire-uri-password-is-a-shell-var",
        "why": "a compose file interpolating a var must never block; unseen spelling",
        "files": {"compose.yml": 'DSN: "amqp://svc:$RABBIT_PASSWORD@broker:5672"\n'},
        "expect_blocked": False,
    },
    {
        "id": "holdout/9711e14/nofire-aws-key-name-in-ci-binding",
        "why": "a CI binding names the key with no value; the names-not-values rule must hold",
        "files": {
            "ci.yml": "env:\n  AWS_SECRET_ACCESS_KEY: ${{ secrets.AWS_SECRET_ACCESS_KEY }}\n"
        },
        "expect_blocked": False,
    },
    {
        "id": "holdout/9711e14/nofire-long-hex-that-is-a-checksum",
        "why": "a 40-char hex digest next to no credential name must not read as an AWS secret",
        "files": {"LOCK.md": "sha1: da39a3ee5e6b4b0d3255bfef95601890afd80709\n"},
        "expect_blocked": False,
    },
]


def _run_secret_case(case: dict) -> dict:
    from run_hook_scenarios import (
        build_fixture,  # noqa: PLC0415  (path set at import time)
    )

    sc = {
        "script": "guard-secrets.sh",
        "fixture": {
            "env": {"CLAUDE_PROJECT_DIR": "@@FIXTURE@@"},
            "git": True,
            "files": case["files"],
        },
    }
    root, env = build_fixture(sc, SECRET_CASES.index(case))
    payload = json.dumps(
        {"tool_name": "Bash", "tool_input": {"command": "git commit -m wip"}}
    )
    proc = subprocess.run(
        ["bash", str(REPO / "hooks/scripts/guard-secrets.sh")],
        input=payload,
        capture_output=True,
        text=True,
        cwd=str(root),
        env={**os.environ, **env},
        timeout=60,
    )
    blocked = proc.returncode == 2 and "BLOCKED" in proc.stderr
    return {
        "id": case["id"],
        "ok": blocked == case["expect_blocked"],
        "blocked": blocked,
    }


# --------------------------------------------------------------------------------------------
# da4590c -- hook file mode. The change fixed ONE script; the claim is about the whole set.
# --------------------------------------------------------------------------------------------
def _holdout_hook_modes() -> list[dict]:
    scripts = sorted((REPO / "hooks/scripts").glob("*.sh"))
    not_exec = [s.name for s in scripts if not os.access(s, os.X_OK)]
    return [
        {
            "id": "holdout/da4590c/every-shipped-hook-script-is-executable",
            "why": "the change fixed the one that was not; the claim only holds if none regressed",
            "ok": not not_exec and len(scripts) >= 18,
            "detail": f"{len(scripts)} scripts, non-executable: {not_exec or 'none'}",
        }
    ]


# --------------------------------------------------------------------------------------------
# 5801277 -- rule scoping. Counting frontmatter was the A/B metric, so it is NOT the holdout.
# The holdout asks the thing the count cannot: are the globs live?
# --------------------------------------------------------------------------------------------
def _holdout_rule_globs() -> list[dict]:
    import fnmatch

    # A filesystem walk, NOT `git ls-files`. The first version of this holdout shelled out to git
    # and ran inside a Docker copy of a git WORKTREE, whose `.git` is a pointer file into the
    # parent repo -- so git exited non-zero, the path list came back empty, and every scoped rule
    # was reported as having dead globs. The check failed loudly, which is the only reason the
    # instrument bug was visible at all, but the reason it printed was a fabrication: it accused
    # 18 rules of a defect none of them had. Absence read as a finding, in a holdout written for
    # a programme whose whole subject is that failure mode.
    skip = {".git", "__pycache__", "node_modules", ".venv", "dist", "build"}
    paths = [
        str(p.relative_to(REPO))
        for p in REPO.rglob("*")
        if p.is_file() and not skip & set(p.relative_to(REPO).parts)
    ]
    if len(paths) < 100:
        # The corpus itself is the prerequisite. Too small means the walk failed, and a verdict
        # computed from it would be about the walk, not about the rules.
        return [
            {
                "id": "holdout/5801277/no-scoped-rule-has-only-dead-globs",
                "ok": False,
                "detail": (
                    f"COULD NOT RUN: only {len(paths)} files found under {REPO}; the corpus is "
                    "missing, so no statement about dead globs is possible either way"
                ),
            }
        ]
    dead = []
    for rule in sorted((REPO / "rules").glob("*.md")):
        text = rule.read_text(encoding="utf-8", errors="replace")
        if not text.startswith("---"):
            continue
        front = text.split("\n---", 1)[0]
        globs = [
            ln.strip().lstrip("- ").strip("'\"")
            for ln in front.splitlines()
            if ln.strip().startswith("- ")
        ]
        if not globs:
            continue
        # A glob is live if SOME tracked path could match it. `.claude/**` paths address the
        # installed project, not this repo, so they are exempt -- they are unfalsifiable here
        # rather than dead, and calling them dead would be absence reported as a finding.
        checkable = [g for g in globs if not g.startswith(".claude/")]
        if checkable and not any(
            fnmatch.fnmatch(p, g) for g in checkable for p in paths
        ):
            dead.append(f"{rule.name}: {checkable}")
    return [
        {
            "id": "holdout/5801277/no-scoped-rule-has-only-dead-globs",
            "why": "a rule scoped by a glob that matches nothing is silently switched off; the "
            "frontmatter count that graded the A/B cannot see this",
            "ok": not dead,
            "detail": dead or "every scoped rule has at least one live glob",
        }
    ]


# --------------------------------------------------------------------------------------------
# 6c6155e -- the auditor allowlist. The change fixed one agent; the claim is about the class.
# --------------------------------------------------------------------------------------------
def _holdout_readonly_agents() -> list[dict]:
    import yaml

    WRITE = {"Write", "Edit", "NotebookEdit", "Agent", "Task"}
    offenders = []
    files = sorted(REPO.glob("agents/*.md")) + sorted(
        REPO.glob("templates/org/agents/*.md")
    )
    for f in files:
        text = f.read_text(encoding="utf-8")
        if not text.startswith("---"):
            continue
        fm = yaml.safe_load(text.split("---\n", 2)[1]) or {}
        desc = str(fm.get("description", ""))
        if "read-only" not in desc.lower() and "reports only" not in desc.lower():
            continue
        tools = {t.strip() for t in str(fm.get("tools", "")).split(",") if t.strip()}
        if not tools:
            offenders.append(f"{f.name}: advertises read-only with NO tools allowlist")
        elif tools & WRITE:
            offenders.append(f"{f.name}: read-only but holds {sorted(tools & WRITE)}")
    return [
        {
            "id": "holdout/6c6155e/no-agent-advertises-read-only-while-holding-write-tools",
            "why": "the change fixed auditor.md; nothing checked whether the class survived "
            "elsewhere, and 'reports only' agents make the same promise in different words",
            "ok": not offenders,
            "detail": offenders
            or f"{len(files)} agents checked, none contradict themselves",
        }
    ]


def main() -> int:
    if not pathlib.Path("/.dockerenv").is_file():
        print("refusing to run outside Docker (no /.dockerenv)", file=sys.stderr)
        return 3
    results = [_run_secret_case(c) for c in SECRET_CASES]
    results += (
        _holdout_hook_modes() + _holdout_rule_globs() + _holdout_readonly_agents()
    )
    failed = [r for r in results if not r["ok"]]
    doc = {
        "dockerenv_verified": True,
        "total": len(results),
        "passed": len(results) - len(failed),
        "failed": len(failed),
        "results": results,
    }
    print(json.dumps(doc, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
