"""Prove each registry hook is actually WIRED, not merely that its script works.

Batch 1 and 2 executed all 19 hook scripts directly. That says nothing about whether Claude Code
would ever call them: a script can pass every fire/no-fire case while being bound to the wrong
event, carrying a matcher that never matches, or pointing at a path the installer does not create.
The 23 `hook:` registry entries are a separate claim from the 19 `hook-script:` files, and this is
the check for that claim.

Two surfaces, because the kit ships two ways:

  scaffold  resolve a plan per profile, install it, and compare .claude/settings.json against the
            registry -- right event, right matcher, script present AND executable AND parseable.
  plugin    hooks/hooks.json must wire every PLUGIN_HOOK_ID through ${CLAUDE_PLUGIN_ROOT} to a
            script that exists in the repo.

The negative half matters as much: a hook the resolved plan does NOT include must be ABSENT from
settings.json. Without that, a scaffold that installed every hook regardless of profile would score
perfectly, and profile gating -- the thing the catalog exists to do -- would be unverified.

Runs inside Docker; the host control plane must not execute project code.
"""

import json
import pathlib
import subprocess
import sys
import tempfile

sys.path.insert(0, "/repo/src")

from claude_kit import catalog, scaffold, upgrader  # noqa: E402
from claude_kit.hooks import (  # noqa: E402
    HOOK_REGISTRY,
    PLUGIN_HOOK_IDS,
    PLUGIN_ONLY_HOOKS,
    STARTER_HOOK_IDS,
)

REPO = pathlib.Path("/repo")
PROFILES = ["lean", "standard", "enterprise"]
# (profile, capture_mode, upgrade_after). Capture is opt-in and off by default, so the three
# capture-learnings entries are wired by no default profile; the upgraded arm re-checks a config
# after upgrade() has rewritten settings.json.
VARIANTS = [
    ("standard", "session-end", False),
    ("standard", "session-end-catchup", False),
    ("enterprise", "session-end-catchup", False),
    ("enterprise", "per-task", False),
    ("standard", "per-task", False),
    ("standard", None, True),
    ("enterprise", None, True),
]
MUTATE = "--mutate" in sys.argv


def installed_commands(settings, event):
    """Every command string wired to `event`, paired with the matcher it sits under."""
    out = []
    for block in (settings.get("hooks") or {}).get(event, []) or []:
        for h in block.get("hooks") or []:
            out.append((block.get("matcher", ""), h.get("command", "")))
    return out


def wires(spec, command):
    """Does `command` wire this registry entry?

    Two hooks -- guard-rm-rf and protect-secrets -- carry `script: null` and ship their logic as
    inline shell. Matching on a script filename reports them as unwired, which is how the first run
    of this checker produced six false findings against a perfectly wired install. For those, match
    on a distinctive slice of the registry's own command text instead.
    """
    script = spec.get("script")
    if script:
        return script in command
    inline = (spec.get("entry") or {}).get("command", "")
    probe = inline[:80].strip()
    return bool(probe) and probe in command


def check_inline_hook(hid, spec, fire_value, quiet_value, key):
    """Execute a script-less hook's inline shell against a firing and a non-firing input.

    These two are real, blocking guards with no script file, so the batch-1/2 harness could never
    reach them. Same credit rule as the scripts: it must block when it should AND stay silent when
    it should.
    """
    inline = spec["entry"]["command"]
    out = {}
    for label, value in (("fire", fire_value), ("nofire", quiet_value)):
        p = subprocess.run(
            ["bash", "-c", inline],
            input=json.dumps(
                {"tool_name": spec["matcher"], "tool_input": {key: value}}
            ),
            capture_output=True,
            text=True,
            timeout=60,
        )
        out[label] = {"exit": p.returncode, "stderr": p.stderr.strip()[:160]}
    fire_ok = out["fire"]["exit"] == 2 and "BLOCKED" in out["fire"]["stderr"]
    quiet_ok = out["nofire"]["exit"] == 0 and not out["nofire"]["stderr"]
    return {
        "id": f"hook:{hid}",
        "fire_ok": fire_ok,
        "nofire_ok": quiet_ok,
        "complete": fire_ok and quiet_ok,
        **out,
    }


def mutate(settings, plan):
    """Break a correct install three ways, so a run that stays green indicts the checker.

    Each mutation targets a different claim: (a) a planned hook silently vanishes, (b) a planned
    hook survives but under a matcher that will never match, (c) a hook the profile EXCLUDED gets
    wired anyway -- the profile-gating leak the negative half exists to catch.
    """
    out = json.loads(json.dumps(settings))
    dropped = paired = leaked = False
    for hid in sorted(plan.hooks):
        spec = HOOK_REGISTRY.get(hid)
        if not spec or not spec.get("script"):
            continue
        for block in (out.get("hooks") or {}).get(spec["event"], []):
            entries = block.get("hooks") or []
            keep = [h for h in entries if spec["script"] not in h.get("command", "")]
            if len(keep) == len(entries):
                continue
            if not dropped:
                block["hooks"] = keep
                dropped = True
            elif not paired:
                block["matcher"] = "NeverMatchesAnything"
                paired = True
            break
        if dropped and paired:
            break
    for hid, spec in HOOK_REGISTRY.items():
        if hid in plan.hooks or hid in PLUGIN_ONLY_HOOKS or not spec.get("script"):
            continue
        out.setdefault("hooks", {}).setdefault(spec["event"], []).append(
            {
                "matcher": spec["matcher"],
                "hooks": [{"command": f"bash {spec['script']}"}],
            }
        )
        leaked = True
        break
    if not (dropped and paired and leaked):
        raise SystemExit(
            f"mutation control could not be applied: {dropped=} {paired=} {leaked=}"
        )
    return out


# (firing input, non-firing input, tool_input key) for the two script-less guards. The non-firing
# case is the near miss the guard must spare, not an unrelated no-op: `rm README.md` is a real
# delete that simply is not recursive-and-forced, and `.env.example` is the file people commit.
INLINE_CASES = {
    "guard-rm-rf": ("rm -rf /tmp/scratch", "rm README.md", "command"),
    "protect-secrets": ("/proj/.env", "/proj/.env.example", "file_path"),
}


def check_profile(profile, capture_mode=None, upgrade_after=False):
    """Verify one installed configuration.

    `capture_mode` selects a capture trigger. Capture is opt-in and off by default, so the three
    capture-learnings registry entries are wired by NO default profile -- without this axis they can
    only ever be evaluated as "never installed anywhere", which says nothing about whether choosing
    the mode works.

    `upgrade_after` re-checks the same install after `upgrader.upgrade()` has run over it. That is a
    genuinely different configuration, not a re-score: an upgrade rewrites settings.json, and a hook
    silently dropped on upgrade would leave every fresh-install check green.
    """
    label = profile + (f"+{capture_mode}" if capture_mode else "")
    label += "+upgraded" if upgrade_after else ""
    findings, checked = [], 0
    sel = catalog.defaults(REPO)
    sel.profile = profile
    if capture_mode:
        sel.capture_mode = capture_mode
    plan = catalog.resolve(REPO, sel)
    target = pathlib.Path(tempfile.mkdtemp(prefix=f"wire-{label}-"))
    scaffold.install_sdlc(REPO, target, plan)
    if upgrade_after:
        ok, msgs = upgrader.upgrade(target)
        if not ok:
            findings.append(f"{label}: upgrade failed: {msgs[:3]}")

    profile = label
    settings_path = target / ".claude/settings.json"
    if not settings_path.is_file():
        return [f"{profile}: no .claude/settings.json installed"], 0, {}, {}, {}
    settings = json.loads(settings_path.read_text())
    if MUTATE:
        settings = mutate(settings, plan)

    planned = set(plan.hooks)
    wired, inline, absent = {}, {}, {}
    for hid in sorted(planned):
        spec = HOOK_REGISTRY.get(hid)
        if not spec:
            findings.append(f"{profile}/{hid}: planned but absent from HOOK_REGISTRY")
            continue
        checked += 1
        cmds = installed_commands(settings, spec["event"])
        hit = [(m, c) for m, c in cmds if wires(spec, c)]
        if not hit:
            findings.append(f"{profile}/{hid}: not wired to {spec['event']}")
            continue
        matcher, cmd = hit[0]
        if matcher != spec["matcher"]:
            findings.append(
                f"{profile}/{hid}: matcher {matcher!r} != registry {spec['matcher']!r}"
            )
        script = spec["script"]
        if script:
            if "${CLAUDE_PROJECT_DIR}" not in cmd:
                findings.append(
                    f"{profile}/{hid}: command is not project-dir relative: {cmd!r}"
                )
            sp = target / ".claude/hooks" / script
            if not sp.is_file():
                findings.append(f"{profile}/{hid}: script not installed at {sp}")
            else:
                if not sp.stat().st_mode & 0o111:
                    findings.append(
                        f"{profile}/{hid}: installed script is not executable"
                    )
                if (
                    subprocess.run(
                        ["bash", "-n", str(sp)], capture_output=True
                    ).returncode
                    != 0
                ):
                    findings.append(
                        f"{profile}/{hid}: installed script fails `bash -n`"
                    )
        else:
            # Script-less hooks are inline shell carried in the registry entry. They still have to
            # parse once installed -- a syntax error would disable them silently.
            if (
                subprocess.run(
                    ["bash", "-n", "-c", cmd], capture_output=True
                ).returncode
                != 0
            ):
                findings.append(
                    f"{profile}/{hid}: installed inline command fails `bash -n`"
                )
            # ...and they have to actually guard. The batch-1/2 script harness could never reach
            # these two, so without this they would sit at "correctly bound, never executed".
            if hid in INLINE_CASES:
                res = check_inline_hook(hid, spec, *INLINE_CASES[hid])
                inline[hid] = res
                if not res["complete"]:
                    findings.append(
                        f"{profile}/{hid}: inline guard misbehaved: "
                        f"fire={res['fire']} nofire={res['nofire']}"
                    )
        wired[hid] = True

    # A plugin-only hook is a documented divergence: it ships in hooks/hooks.json and is
    # deliberately kept out of the scaffold so `claude-kit init` output is unchanged. Skipping it
    # here would leave the second half of that promise -- the ABSENCE -- permanently unverified.
    for hid, spec in PLUGIN_ONLY_HOOKS.items():
        checked += 1
        script = spec.get("script")
        if script and any(
            script in c for _, c in installed_commands(settings, spec["event"])
        ):
            findings.append(
                f"{profile}/{hid}: plugin-only hook leaked into the scaffolded install"
            )
        else:
            # Verified absence is a real verification of this component, not a skipped check: the
            # plugin manifest can only ever offer it one surface, and "stays out of the scaffold"
            # is half of what it promises.
            absent[hid] = True

    # Negative half: anything the plan excluded must not have been wired anyway.
    for hid, spec in HOOK_REGISTRY.items():
        if hid in planned or hid in PLUGIN_ONLY_HOOKS:
            continue
        script = spec.get("script")
        if not script:
            continue
        if any(script in c for _, c in installed_commands(settings, spec["event"])):
            findings.append(
                f"{profile}/{hid}: NOT in the resolved plan yet wired anyway (profile gating leak)"
            )
        checked += 1
    return findings, checked, wired, inline, absent


def check_plugin_manifest():
    findings, wired = [], {}
    manifest = json.loads((REPO / "hooks/hooks.json").read_text())
    if "hooks" not in manifest:
        findings.append(
            "hooks/hooks.json has no top-level 'hooks' key — plugin hooks silently ignored"
        )
        return findings, wired
    for hid in sorted(set(PLUGIN_HOOK_IDS) | set(PLUGIN_ONLY_HOOKS)):
        spec = HOOK_REGISTRY.get(hid) or PLUGIN_ONLY_HOOKS.get(hid)
        if not spec:
            findings.append(f"plugin/{hid}: not in HOOK_REGISTRY")
            continue
        cmds = installed_commands(manifest, spec["event"])
        script = spec["script"]
        hit = [c for _, c in cmds if wires(spec, c)]
        if not hit:
            findings.append(
                f"plugin/{hid}: not wired to {spec['event']} in hooks/hooks.json"
            )
            continue
        # Only a script-backed hook needs the plugin-root prefix; an inline command has no path
        # to resolve, and demanding one here is what produced this checker's second false finding.
        if script:
            if "${CLAUDE_PLUGIN_ROOT}" not in hit[0]:
                findings.append(
                    f"plugin/{hid}: command does not use ${{CLAUDE_PLUGIN_ROOT}}"
                )
            if not (REPO / "hooks/scripts" / script).is_file():
                findings.append(
                    f"plugin/{hid}: referenced script missing from the repo"
                )
        elif subprocess.run(
            ["bash", "-n", "-c", hit[0]], capture_output=True
        ).returncode:
            findings.append(f"plugin/{hid}: inline command fails `bash -n`")
        wired[hid] = True
    return findings, wired


def check_starter():
    """templates/settings.json -- the no-pip fallback that scripts/init.sh copies verbatim.

    It is generated from STARTER_HOOK_IDS, so it is a real third install surface with its own
    (smaller) roster. Both halves are checked: every starter hook wired, and nothing outside the
    set present -- the consent gate that keeps the capture hooks out of a channel with no init
    question is only meaningful if something enforces the absence.
    """
    findings, wired = [], {}
    settings = json.loads((REPO / "templates/settings.json").read_text())
    if MUTATE:
        # The repo is mounted read-only, so the starter is mutated in memory: drop one hook the
        # starter is supposed to ship. Without this the starter surface could never go red.
        victim = HOOK_REGISTRY[sorted(STARTER_HOOK_IDS)[0]]
        for block in (settings.get("hooks") or {}).get(victim["event"], []):
            block["hooks"] = [
                h
                for h in block.get("hooks") or []
                if not wires(victim, h.get("command", ""))
            ]
    for hid in sorted(STARTER_HOOK_IDS):
        spec = HOOK_REGISTRY.get(hid)
        if not spec:
            findings.append(f"starter/{hid}: not in HOOK_REGISTRY")
            continue
        if not any(
            wires(spec, c) for _, c in installed_commands(settings, spec["event"])
        ):
            findings.append(f"starter/{hid}: not wired to {spec['event']}")
            continue
        wired[hid] = True
    for hid, spec in HOOK_REGISTRY.items():
        script = spec.get("script")
        if hid in STARTER_HOOK_IDS or not script:
            continue
        if any(script in c for _, c in installed_commands(settings, spec["event"])):
            findings.append(
                f"starter/{hid}: shipped in the starter but not in STARTER_HOOK_IDS"
            )
    return findings, wired


def selftest():
    """The comparator must be able to fail. Feed it a manifest that wires nothing."""
    spec = HOOK_REGISTRY["load-continuity"]
    empty = {"hooks": {spec["event"]: [{"matcher": "", "hooks": []}]}}
    if installed_commands(empty, spec["event"]):
        return False
    populated = {
        "hooks": {
            spec["event"]: [
                {"matcher": "", "hooks": [{"command": "bash x/load-continuity.sh"}]}
            ]
        }
    }
    if not installed_commands(populated, spec["event"]):
        return False

    # The inline-guard grader needs its own proof it can fail: mutate() only edits settings.json,
    # so nothing else in this file would notice a guard that stopped guarding.
    toothless = {"matcher": "Bash", "entry": {"command": "exit 0"}}
    if check_inline_hook("x", toothless, "rm -rf /", "ls", "command")["complete"]:
        return False
    trigger_happy = {
        "matcher": "Bash",
        "entry": {"command": "echo BLOCKED >&2; exit 2"},
    }
    if check_inline_hook("x", trigger_happy, "rm -rf /", "ls", "command")["complete"]:
        return False
    return True


def main():
    if not pathlib.Path("/.dockerenv").is_file():
        print("refusing to run outside Docker (no /.dockerenv)", file=sys.stderr)
        return 3
    if not selftest():
        print(
            "SELFTEST FAILED: installed_commands() cannot discriminate", file=sys.stderr
        )
        return 3

    all_findings, checked, wired_any = [], 0, set()
    per_profile = {}
    arms = [(p, None, False) for p in PROFILES] + VARIANTS
    for p, cap, upg in arms:
        f, c, w, inl, absent = check_profile(p, capture_mode=cap, upgrade_after=upg)
        key = p + (f"+{cap}" if cap else "") + ("+upgraded" if upg else "")
        per_profile[key] = {
            "findings": f,
            "checks": c,
            "wired": sorted(w),
            "inline_exec": inl,
            "plugin_only_absent": sorted(absent),
        }
        all_findings += f
        checked += c
        wired_any |= set(w)

    pf, pw = check_plugin_manifest()
    all_findings += pf
    wired_any |= set(pw)

    sf, sw = check_starter()
    all_findings += sf
    wired_any |= set(sw)

    out = {
        "selftest": "passed — installed_commands() discriminates wired from unwired",
        "mutated": MUTATE,
        "dockerenv_verified": True,
        "profiles": per_profile,
        "plugin_manifest": {"findings": pf, "wired": sorted(pw)},
        "starter": {"findings": sf, "wired": sorted(sw)},
        "checks_performed": checked + len(PLUGIN_HOOK_IDS) + len(STARTER_HOOK_IDS),
        "registry_total": len(HOOK_REGISTRY),
        # Emitted so the host-side coverage derivation can map a registry entry to its script
        # without importing product code on the control plane.
        "script_of": {
            h: s.get("script")
            for h, s in sorted({**HOOK_REGISTRY, **PLUGIN_ONLY_HOOKS}.items())
        },
        "hooks_wired_somewhere": sorted(wired_any),
        "hooks_wired_count": len(wired_any),
        "findings": all_findings,
        "ok": not all_findings,
    }
    print(json.dumps(out, indent=2))
    return 1 if all_findings else 0


if __name__ == "__main__":
    sys.exit(main())
