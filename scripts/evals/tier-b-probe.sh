#!/usr/bin/env bash
# One Tier B batched trigger probe: does a set of skills fire on the right input and not the wrong one?
#
# Tier B exists because demanding a full SDLC scenario for a one-line skill made 100% dynamic
# coverage arithmetically impossible (E-031). What Tier B claims is narrow and stated in
# dynamic-tiering.md: criterion 1 (selects/triggers correctly), plus 2, 9, 11, 13, 14 and the
# triggering half of 7. It CONCEDES 3, 4, 5, 6, 8-beyond-triggering, 10 and 12.
#
# The measurement that makes it worth anything is the NEGATIVE case. A probe that only shows a
# skill firing when it should cannot see false triggering, and dynamic-tiering.md says in terms:
# "A probe without negative cases is not a Tier B measurement." Each batch therefore carries decoy
# requests that must match nothing, and every other batch's targets act as further negatives.
#
# Two deviations from the shipped product, both recorded in the probe record, neither optional:
#   profile=enterprise   64 of the 117 Tier B components install only in the enterprise profile.
#                        A default install cannot trigger a skill it did not lay down.
#   rules withheld       a default install auto-loads 446KB of rules and dies before doing any work
#                        (F-014). Every dynamic arm in this run carries this deviation (E-014).
#
# Usage: tier-b-probe.sh --label <id> --prompt-file <path> --out <dir> [--max-turns N]
set -Eeuo pipefail

LABEL="" PROMPT_FILE="" OUT="" MAX_TURNS=12 FIXTURE=""
while [ $# -gt 0 ]; do
	case "$1" in
	--label) LABEL="${2:?}"; shift 2 ;;
	--prompt-file) PROMPT_FILE="${2:?}"; shift 2 ;;
	--out) OUT="${2:?}"; shift 2 ;;
	--max-turns) MAX_TURNS="${2:?}"; shift 2 ;;
	--fixture) FIXTURE="${2:?}"; shift 2 ;;
	*) echo "unknown arg: $1" >&2; exit 2 ;;
	esac
done
[ -n "$LABEL" ] && [ -n "$PROMPT_FILE" ] && [ -n "$OUT" ] || { echo "missing required arg" >&2; exit 2; }

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
EVID="$OUT/$LABEL-$STAMP"
mkdir -p "$EVID"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/ck-tierb-$LABEL-XXXXXX")"

echo "### workspace $WORK"
# An EMPTY workspace cannot distinguish "the skill failed to trigger" from "the skill correctly
# declined because there is nothing to work on" (E-047). Five of six silences in the first batch
# were the latter -- skills naming their own missing prerequisite and refusing to invent work.
# A fixture with real code removes that confound for every skill whose job needs a codebase.
if [ -n "$FIXTURE" ]; then
	cp -a "$ROOT/tests/evals/e2e/fixtures/$FIXTURE/." "$WORK/"
	echo "### fixture $FIXTURE materialised"
else
	printf 'placeholder\n' >"$WORK/README.md"
fi
git -C "$WORK" init -q
git -C "$WORK" add -A
git -C "$WORK" -c user.email=eval@local -c user.name=eval commit -qm baseline

# enterprise profile so every Tier B component is actually installed
cat >"$WORK/.ck-selection.yaml" <<'YAML'
profile: enterprise
scope: organization
backend: none
frontend: none
database: none
mcp: []
YAML

echo "### scaffold (Docker; the host never runs project code)"
"$ROOT/scripts/evals/run-in-docker.sh" --service python --label "tierb-$LABEL-scaffold" \
	--mount "$WORK:/work" --workdir /repo --timeout 600 -- \
	env PYTHONPATH=/repo/src python -m claude_kit.cli init /work --config /work/.ck-selection.yaml

SKILLS_INSTALLED="$(find "$WORK/.claude/skills" -name SKILL.md 2>/dev/null | wc -l | tr -d ' ')"
echo "### installed $SKILLS_INSTALLED skills"

RULE_BYTES="$(cat "$WORK"/.claude/rules/*.md 2>/dev/null | wc -c | tr -d ' ')"
mv "$WORK/.claude/rules" "$EVID/rules-withheld" 2>/dev/null || true
echo "### DEVIATION rules withheld ($RULE_BYTES bytes) — F-014"

# Isolated config: `claude -p` would otherwise inherit the OPERATOR's ~/.claude guard hooks and
# measure their permission posture instead of the kit's (E-006).
CFG="$EVID/claude-config"
mkdir -p "$CFG"
cat >"$CFG/settings.json" <<'JSON'
{
  "permissions": {
    "allow": ["Read", "Glob", "Grep", "Skill", "TaskCreate", "TaskList", "TaskUpdate",
              "Bash(ls:*)", "Bash(cat:*)", "Bash(pwd)"],
    "deny": ["Bash(rm:*)", "Write", "Edit"]
  }
}
JSON

cp "$PROMPT_FILE" "$EVID/prompt.txt"
set +e
( cd "$WORK" && CLAUDE_CONFIG_DIR="$CFG" claude -p "$(cat "$PROMPT_FILE")" \
	--max-turns "$MAX_TURNS" --output-format stream-json --verbose \
	--permission-mode acceptEdits ) >"$EVID/session.jsonl" 2>"$EVID/session.stderr"
SESSION_RC=$?
set -e

python3 - "$EVID/session.jsonl" "$EVID/probe.json" "$LABEL" "$SESSION_RC" "$SKILLS_INSTALLED" "$RULE_BYTES" "$FIXTURE" <<'PY'
import json, sys
jsonl, out, label, rc, installed, rule_bytes = sys.argv[1:7]
skills, agents, tools, first_cache = [], [], [], None
for line in open(jsonl, encoding="utf-8", errors="replace"):
    line = line.strip()
    if not line:
        continue
    try:
        ev = json.loads(line)
    except json.JSONDecodeError:
        continue
    if ev.get("type") == "assistant":
        usage = (ev.get("message") or {}).get("usage") or {}
        if first_cache is None and "cache_creation_input_tokens" in usage:
            first_cache = usage["cache_creation_input_tokens"]
        for block in (ev.get("message") or {}).get("content") or []:
            if block.get("type") != "tool_use":
                continue
            name = block.get("name", "")
            tools.append(name)
            inp = block.get("input") or {}
            if name == "Skill":
                # `skill` is the documented field; absent means the call carried no skill name,
                # which is NOT the same as "no skill invoked" and must not read as one.
                if "skill" in inp:
                    skills.append(inp["skill"])
                else:
                    skills.append(f"<Skill call with no `skill` field: {sorted(inp)}>")
            if name == "Agent":
                agents.append(inp.get("subagent_type", "<unspecified>"))
json.dump({
    "label": label, "session_rc": int(rc), "skills_installed": int(installed),
    "rule_bytes_withheld": int(rule_bytes), "first_msg_cache_creation": first_cache,
    "skills_invoked": skills, "agents_spawned": agents, "tool_calls": tools,
    "deviations": ["profile=enterprise", "rules withheld (F-014)"], "fixture": sys.argv[7] if len(sys.argv) > 7 else "",
}, open(out, "w"), indent=2)
print(f"skills_invoked={skills}")
PY

echo "### evidence $EVID"
