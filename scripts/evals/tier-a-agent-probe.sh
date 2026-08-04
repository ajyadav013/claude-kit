#!/usr/bin/env bash
# One Tier A agent scenario: given a real task on a real fixture, does the right agent get used,
# does it stay inside its declared role, and does the workspace end up actually working?
#
# Tier B could not answer this. It concedes criteria 3 and 12 outright, and an agent is exactly the
# component where "did it reach a working solution" is the interesting question. So this probe gives
# the session a codebase and a job, and grades the WORKSPACE afterwards, not the conversation.
#
# The prompt is derived mechanically from the agent's own `description` frontmatter and never names
# the agent. Naming it would measure my prompt-writing; withholding the name is what makes criterion
# 1 falsifiable -- if a plain statement of the work the agent advertises does not reach it, that is
# a selection finding.
#
# EXECUTION PLANE. `claude -p` runs on the host, so this probe must not let the session run project
# code: no pytest, no build, no linter. Bash is restricted to inspection. Criterion 3 is therefore
# graded by a Docker oracle over the resulting workspace, never by the agent's own say-so, and
# criterion 5 degrades to "did it ATTEMPT verification" -- a denied test invocation is still
# evidence the agent tried, and silence is evidence it did not.
#
# Deviations, recorded in every probe record, neither optional:
#   profile=enterprise   several agents install only at enterprise; a default install cannot
#                        delegate to an agent it never laid down.
#   rules withheld       a default install auto-loads ~446KB of rules and dies before doing any
#                        work (F-014). Every dynamic arm in this run carries this (E-014).
#
# Usage: tier-a-agent-probe.sh --agent <name> --fixture <f> --out <dir> [--max-turns N] [--arm A]
set -Eeuo pipefail

# Prompt-injection surface, stated deliberately: every input to the derived prompt is a repo-local
# file under version control -- the agent's own frontmatter and, optionally, a situation file I
# author. No web content, no user submissions, no model output is interpolated. The child session
# is sandboxed to a throwaway workspace with Bash restricted to inspection.
#
# PIPELINE MODE (--sdlc-task). E-060 says an ad-hoc "do this work" request may simply be the wrong
# entry point for a coordinator agent, and that no coordinator may be called a criterion-1 defect on
# ad-hoc evidence alone. This mode drives the shipped `sdlc` skill instead and records which agents
# the PIPELINE dispatches. The entry point is named on purpose here: what is under test is agent
# dispatch inside the pipeline, not whether the pipeline gets selected. That is a separate question,
# already measured elsewhere, and conflating them would answer neither.
AGENT="" FIXTURE="pybug" OUT="" MAX_TURNS=40 ARM="a1" SITUATION="" DB="none" LABEL=""
SDLC_TASK="" KEEP_RULES=no
while [ $# -gt 0 ]; do
	case "$1" in
	--agent) AGENT="${2:?}"; shift 2 ;;
	--sdlc-task) SDLC_TASK="${2:?}"; shift 2 ;;
	--keep-rules) KEEP_RULES=yes; shift ;;
	--rules-ondemand) KEEP_RULES=ondemand; shift ;;
	--fixture) FIXTURE="${2:?}"; shift 2 ;;
	--out) OUT="${2:?}"; shift 2 ;;
	--max-turns) MAX_TURNS="${2:?}"; shift 2 ;;
	--arm) ARM="${2:?}"; shift 2 ;;
	--situation) SITUATION="${2:?}"; shift 2 ;;
	--db) DB="${2:?}"; shift 2 ;;
	--label) LABEL="${2:?}"; shift 2 ;;
	*) echo "unknown arg: $1" >&2; exit 2 ;;
	esac
done
[ -n "$SDLC_TASK" ] && [ -z "$AGENT" ] && AGENT="skills/sdlc/SKILL.md"
[ -n "$AGENT" ] && [ -n "$OUT" ] || { echo "missing required arg (--agent or --sdlc-task)" >&2; exit 2; }

# The session runs from inside $WORK, so a RELATIVE evidence path stops resolving there and the
# prompt `cat` silently yields nothing. That is E-049 exactly, and it cost 40 fabricated skill
# defects the first time. Absolutise before anything else, and refuse to run on an empty prompt
# rather than measuring one.
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SRC=""
if [ -f "$ROOT/$AGENT" ]; then
	# An explicit path. Two overlay agents share the basename `migration-specialist` across the
	# postgres and mongodb stacks, so a name lookup cannot address them unambiguously.
	SRC="$ROOT/$AGENT"
	AGENT="$(basename "$AGENT" .md)"
else
	for cand in "$ROOT/agents/$AGENT.md" "$ROOT/templates/org/agents/$AGENT.md"; do
		[ -f "$cand" ] && SRC="$cand" && break
	done
	if [ -z "$SRC" ]; then
		SRC="$(find "$ROOT/templates/stacks" -name "$AGENT.md" -print -quit 2>/dev/null || true)"
	fi
fi
[ -n "$SRC" ] && [ -f "$SRC" ] || { echo "agent definition not found: $AGENT" >&2; exit 2; }
[ -n "$LABEL" ] || LABEL="$AGENT"
[ -n "$SDLC_TASK" ] && [ "$LABEL" = "SKILL" ] && LABEL="sdlc-pipeline" && AGENT="sdlc-pipeline"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
EVID="$OUT/$LABEL-$ARM-$STAMP"
mkdir -p "$EVID"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/ck-tiera-$LABEL-XXXXXX")"
echo "### workspace $WORK"

cp -a "$ROOT/tests/evals/e2e/fixtures/$FIXTURE/." "$WORK/"
git -C "$WORK" init -q

cat >"$WORK/.ck-selection.yaml" <<YAML
profile: enterprise
scope: organization
backend: none
frontend: none
database: $DB
mcp: []
YAML

echo "### scaffold (Docker; the host never runs project code)"
"$ROOT/scripts/evals/run-in-docker.sh" --service python --label "tiera-$AGENT-scaffold" \
	--mount "$WORK:/work" --workdir /repo --timeout 600 -- \
	env PYTHONPATH=/repo/src python -m claude_kit.cli init /work --config /work/.ck-selection.yaml

AGENTS_INSTALLED="$(find "$WORK/.claude/agents" -name '*.md' 2>/dev/null | wc -l | tr -d ' ')"
AGENT_PRESENT=no
[ -f "$WORK/.claude/agents/$AGENT.md" ] && AGENT_PRESENT=yes
echo "### installed $AGENTS_INSTALLED agents; $AGENT present=$AGENT_PRESENT"

RULE_BYTES="$( (cat "$WORK"/.claude/rules/*.md 2>/dev/null || true) | wc -c | tr -d ' ')"
if [ "$KEEP_RULES" = ondemand ]; then
	# The third cell F-041 needs. `full` kills the pipeline and `none` is not the product, so
	# neither answers "would progressive disclosure fix it". Every rule keeps its canonical path
	# and stays readable on request; it simply stops being force-fed at launch. Same lever as
	# run-scenario.sh's ondemand arm, and a DEVIATION either way.
	scoped=0
	for rf in "$WORK"/.claude/rules/*.md; do
		[ -f "$rf" ] || continue
		head -n1 "$rf" | grep -q '^---$' && continue
		{
			printf -- '---\npaths:\n  - "**/__ck_eval_never_matches__/**"\n---\n\n'
			cat "$rf"
		} >"$rf.scoped" && mv "$rf.scoped" "$rf"
		scoped=$((scoped + 1))
	done
	echo "### rules ON-DEMAND: scoped $scoped files, still readable at .claude/rules/"
	RULE_BYTES=0
elif [ "$KEEP_RULES" = yes ]; then
	# The shipped-default arm E-014 says the run owes: if the session dies on prompt size, that is
	# F-014 reproducing on the flagship workflow rather than a harness failure, and the result
	# subtype in the record says which happened.
	echo "### rules KEPT ($RULE_BYTES bytes) — shipped-default arm"
	RULE_BYTES=0
else
	mv "$WORK/.claude/rules" "$EVID/rules-withheld" 2>/dev/null || true
	echo "### DEVIATION rules withheld ($RULE_BYTES bytes) — F-014"
fi

# A real test command, for pipeline mode only. Without one the pipeline halts at stage 0 -- it
# cannot verify the baseline, so it correctly refuses to proceed, and every agent behind that gate
# (ui-designer, observability-engineer, the reviewers) becomes unreachable for reasons that are
# mine, not the product's (E-063). The execution-plane rule is not bent to fix it: the command
# shells into the run's Docker wrapper, so the child runs the project's tests and the tests still
# run in a container, with the usual evidence record.
if [ -n "$SDLC_TASK" ]; then
	RUN_DIR="$ROOT/.claude/state/full-self-evaluation"
	RUN_ID="${EVAL_RUN_ID:-$( [ -f "$RUN_DIR/run-id.txt" ] && cat "$RUN_DIR/run-id.txt" || echo unknown )}"
	if [ -f "$WORK/package.json" ] && [ ! -f "$WORK/pyproject.toml" ]; then
		SERVICE=node; TEST_CMD="node --test test/"
	else
		SERVICE=python; TEST_CMD="env PYTHONPATH=/work/src python -m pytest -q -p no:cacheprovider"
	fi
	mkdir -p "$WORK/scripts"
	cat >"$WORK/scripts/test.sh" <<EOF
#!/usr/bin/env sh
# The project's test command. Runs the suite inside a container; never on the host.
export EVAL_COMPOSE_FILE="$ROOT/docker-compose.evals.yml"
export EVAL_RUN_DIR="$RUN_DIR"
export EVAL_RUN_ID="$RUN_ID"
exec "$ROOT/scripts/evals/run-in-docker.sh" --echo --service "$SERVICE" \\
	--label "sdlc-$ARM-projtest" --mount "$WORK:/work" --workdir /work --timeout 600 -- \\
	$TEST_CMD
EOF
	chmod +x "$WORK/scripts/test.sh"
	printf '\n## Commands\n\n- Test: `./scripts/test.sh` (runs the suite in a container)\n' >>"$WORK/CLAUDE.md"
	echo "### project test command installed (delegates into Docker, service=$SERVICE)"
fi

# Baseline is committed AFTER scaffolding, so `git status` afterwards shows the AGENT's work and
# nothing else. Committing before would have left the kit's own installed files looking like agent
# edits -- which read-only reviewers are graded on NOT making, so every reviewer would have failed.
git -C "$WORK" add -A
git -C "$WORK" -c user.email=eval@local -c user.name=eval commit -qm baseline

if [ -n "$SDLC_TASK" ]; then
	cat >"$EVID/prompt.txt" <<PROMPT
Use this project's SDLC pipeline -- the \`sdlc\` skill installed at .claude/skills/sdlc -- to deliver
the following change to this repository:

$SDLC_TASK

Run the pipeline as it is defined. Delegate each stage to the agent that stage calls for.
PROMPT
else
# Derive the request from the agent's own description. Never name the agent.
python3 - "$SRC" "$EVID/prompt.txt" "$AGENT" "$SITUATION" <<'PY'
import re, sys
src, out, agent = sys.argv[1:4]
text = open(src, encoding="utf-8", errors="replace").read()
m = re.search(r"^description:\s*(.+)$", text, re.M)
desc = (m.group(1).strip().strip('"') if m else "").strip()
desc = re.sub(r"\s+", " ", desc)
# Strip any self-reference so the prompt cannot hand the model the answer.
pretty = agent.replace("-", " ")
for token in (agent, pretty):
    desc = re.sub(re.escape(token), "the appropriate specialist", desc, flags=re.I)
if len(desc) > 400:
    desc = desc[:400].rsplit(" ", 1)[0]
situation = ""
if len(sys.argv) > 4 and sys.argv[4]:
    situation = open(sys.argv[4], encoding="utf-8", errors="replace").read().strip() + "\n\n"
# The framing must not assert what the repository IS. An earlier version opened with "this is a
# small Python package with a bug in it", which is incoherent next to a description about auditing
# web pages -- so `auditor` and `incident-responder` correctly declined, and were booked as
# selection failures for being right. The prompt states the job and lets the repo speak for itself.
open(out, "w", encoding="utf-8").write(
    f"{situation}You are working in this repository. Do the following work on it:\n\n"
    f"{desc}\n\n"
    "Work on the real files here. Delegate to a subagent if one fits the job.\n"
)
PY
fi

# Bash is inspection-only BY DESIGN -- see the execution-plane note in the header. A denied test
# invocation is a measurement, not an obstacle.
CFG="$EVID/claude-config"
mkdir -p "$CFG"
cat >"$CFG/settings.json" <<'JSON'
{
  "permissions": {
    "allow": ["Read", "Glob", "Grep", "Write", "Edit", "Agent", "Skill",
              "TaskCreate", "TaskList", "TaskUpdate", "TaskGet",
              "Bash(ls:*)", "Bash(cat:*)", "Bash(pwd)", "Bash(git status:*)", "Bash(git diff:*)",
              "Bash(./scripts/test.sh)", "Bash(sh scripts/test.sh)", "Bash(bash scripts/test.sh)",
              "Bash(scripts/test.sh)", "Bash(git log:*)", "Bash(git add:*)", "Bash(git commit:*)"],
    "deny": ["Bash(rm:*)", "Bash(git push:*)", "WebFetch", "WebSearch"]
  }
}
JSON

[ -s "$EVID/prompt.txt" ] || { echo "derived prompt is empty for $AGENT; refusing to measure it" >&2; exit 2; }

set +e
( cd "$WORK" && CLAUDE_CONFIG_DIR="$CFG" claude -p "$(cat "$EVID/prompt.txt")" \
	--max-turns "$MAX_TURNS" --output-format stream-json --verbose \
	--permission-mode acceptEdits ) >"$EVID/session.jsonl" 2>"$EVID/session.stderr"
SESSION_RC=$?
set -e

git -C "$WORK" add -A >/dev/null 2>&1 || true
git -C "$WORK" diff --cached --stat >"$EVID/workspace.diffstat" 2>/dev/null || true
cp -a "$WORK" "$EVID/workspace"

python3 - "$EVID" "$AGENT" "$SESSION_RC" "$AGENTS_INSTALLED" "$AGENT_PRESENT" "$RULE_BYTES" "$FIXTURE" "$SRC" "$LABEL" "$KEEP_RULES" <<'PY'
import json, re, sys, pathlib
evid, agent, rc, installed, present, rule_bytes, fixture, src = sys.argv[1:9]
# The LABEL only disambiguates directories (two stacks ship a `migration-specialist`).
# The `agent` field must stay the real name -- grading selection against a label the
# runtime never sees reported three correct spawns as substitutions.
label = sys.argv[9] if len(sys.argv) > 9 else agent
keep_rules = sys.argv[10] if len(sys.argv) > 10 else "no"
d = pathlib.Path(evid)

defn = open(src, encoding="utf-8", errors="replace").read()
declared = []
m = re.search(r"^tools:\s*(.+)$", defn, re.M)
if m:
    declared = [t.strip() for t in m.group(1).split(",") if t.strip()]
md = re.search(r"^description:\s*(.+)$", defn, re.M)
description = md.group(1).strip().strip('"') if md else ""

spawned, tools, denied, subagent_tools, first_cache = [], [], [], [], None
result_subtype, num_turns = "", None
for line in (d / "session.jsonl").open(encoding="utf-8", errors="replace"):
    line = line.strip()
    if not line:
        continue
    try:
        ev = json.loads(line)
    except json.JSONDecodeError:
        continue
    t = ev.get("type")
    if t == "result":
        if isinstance(ev.get("subtype"), str):
            result_subtype = ev["subtype"]
        if isinstance(ev.get("num_turns"), int):
            num_turns = ev["num_turns"]
    if t == "assistant":
        usage = (ev.get("message") or {}).get("usage") or {}
        if first_cache is None and "cache_creation_input_tokens" in usage:
            first_cache = usage["cache_creation_input_tokens"]
        for b in (ev.get("message") or {}).get("content") or []:
            if b.get("type") != "tool_use":
                continue
            name = b.get("name", "")
            tools.append(name)
            inp = b.get("input") or {}
            if name == "Agent":
                # absent `subagent_type` is not "no agent" -- record it as unspecified so it can
                # never be silently counted as a match for the target.
                spawned.append(inp.get("subagent_type", "<unspecified>"))
    if t == "user":
        for b in (ev.get("message") or {}).get("content") or []:
            if b.get("type") == "tool_result" and b.get("is_error"):
                txt = b.get("content")
                if isinstance(txt, list):
                    txt = " ".join(x.get("text", "") for x in txt if isinstance(x, dict))
                denied.append(str(txt)[:200])

# Did the session try to VERIFY? Bash is inspection-only here, so an attempt shows up as a denial.
verify_pat = re.compile(r"pytest|npm test|go test|ruff|mypy|coverage|make test", re.I)
attempted_verification = any(verify_pat.search(x) for x in denied)

# The deviations list is PROVENANCE: it decides whether a result may be quoted as the shipped
# default or must be discounted. It was hardcoded to claim rules were withheld, which was true of
# every run that existed until F-041 was fixed and --keep-rules became a usable arm -- at which
# point a safe constant became a lie that discounts correct results (F-074).
rules_deviation = {
    "no": "rules withheld (F-014)",
    "ondemand": "rules on-demand (scoped to a never-matching glob)",
}.get(keep_rules)
deviations = ["profile=enterprise", "bash inspection-only"]
if rules_deviation:
    deviations.insert(1, rules_deviation)
# A record claiming rules were withheld while reporting zero withheld bytes is unreadable as
# evidence. Surface it as a field rather than asserting: the session has already been paid for, and
# throwing its evidence away to signal a labelling bug is the worse trade.
provenance_warning = None
if int(rule_bytes) == 0 and rules_deviation == "rules withheld (F-014)":
    provenance_warning = "deviations say rules withheld but rule_bytes_withheld is 0 — do not quote this arm"
    print(f"### PROVENANCE WARNING {provenance_warning}", file=sys.stderr)

json.dump({
    "agent": agent, "label": label, "arm": d.name, "session_rc": int(rc),
    "result_subtype": result_subtype, "num_turns": num_turns,
    "agents_installed": int(installed), "agent_present": present == "yes",
    "rule_bytes_withheld": int(rule_bytes), "fixture": fixture,
    "rules_mode": keep_rules,
    "first_msg_cache_creation": first_cache,
    "declared_tools": declared, "description": description,
    "agents_spawned": spawned, "tool_calls": tools,
    "denied_tool_results": denied, "attempted_verification": attempted_verification,
    "deviations": deviations, "provenance_warning": provenance_warning,
}, (d / "probe.json").open("w"), indent=2)
print(f"agents_spawned={spawned} tools={sorted(set(tools))}")
PY

echo "### evidence $EVID"
