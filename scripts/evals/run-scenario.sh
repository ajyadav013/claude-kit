#!/usr/bin/env bash
# Run one end-to-end pipeline scenario and judge it with a deterministic oracle.
#
# This is the piece the evaluation was missing. Every batch before it evaluated components in
# isolation — frontmatter, reachability, exit codes — which says nothing about whether the SDLC
# pipeline those components make up actually works. A scenario run is the only evidence that does.
#
# Three planes, kept strictly separate:
#
#   Docker   scaffolding (`claude-kit init`), the oracle, and every test the fixture runs. The
#            host never executes project code.
#   Host     the `claude -p` child session. Claude Code is a control-plane tool and the eval
#            images have neither the CLI nor egress, so the session runs here, against a fixture
#            directory that Docker prepared.
#   Evidence everything lands under raw/task-runs/<scenario>/<stamp>/ — prompt, raw JSON result,
#            metrics, oracle verdict, and the end-state git diff.
#
#   run-scenario.sh --scenario SC-01 --fixture pyservice --oracle sc01_docs_only.py \
#                   --prompt-file <path> [--arm baseline|candidate] [--max-turns N]
#
# Exit code is the ORACLE's, not the child session's: a session that exits 0 having done nothing
# is a failure, and conflating the two is how a scenario harness starts reporting false passes.
set -Eeuo pipefail

SCENARIO="" FIXTURE="" ORACLE="" PROMPT_FILE="" ARM="baseline" MAX_TURNS=60
# The container the ORACLE runs in. Fixtures are not all Python: a Node fixture is graded by a
# JS oracle in the node image, which has no python (and no git — hence the manifest below).
SERVICE="python"
# Optional sealed-holdout directory under tests/evals/e2e/holdouts/. It is copied into the
# workspace only AFTER the session ends; see the injection block.
HOLDOUT=""
# The suite command scripts/test.sh runs INSIDE the container, per fixture toolchain.
TEST_COMMAND="env python -m pytest -q -p no:cacheprovider"
# --rules-mode none strips .claude/rules after scaffolding. This is a DEVIATION from the shipped
# product, not a configuration the product offers, and it exists for one reason: Claude Code
# auto-loads .claude/rules/*.md in full at launch, the kit ships 446KB there, and a default install
# therefore has too little context left for a real task (F-014). Any run using it is recorded with
# `deviation` set, so no result from a deviating arm can be mistaken for the shipped default.
RULES_MODE="full"

while [ $# -gt 0 ]; do
	case "$1" in
	--scenario) SCENARIO="${2:?}"; shift 2 ;;
	--fixture) FIXTURE="${2:?}"; shift 2 ;;
	--oracle) ORACLE="${2:?}"; shift 2 ;;
	--prompt-file) PROMPT_FILE="${2:?}"; shift 2 ;;
	--arm) ARM="${2:?}"; shift 2 ;;
	--max-turns) MAX_TURNS="${2:?}"; shift 2 ;;
	--rules-mode) RULES_MODE="${2:?}"; shift 2 ;;
	--service) SERVICE="${2:?}"; shift 2 ;;
	--holdout) HOLDOUT="${2:?}"; shift 2 ;;
	--test-command) TEST_COMMAND="${2:?}"; shift 2 ;;
	*) echo "run-scenario: unknown option $1" >&2; exit 2 ;;
	esac
done
for v in SCENARIO FIXTURE ORACLE PROMPT_FILE; do
	[ -n "${!v}" ] || { echo "run-scenario: --${v,,} is required" >&2; exit 2; }
done

ROOT="$(git rev-parse --show-toplevel)"
RUN_DIR="$ROOT/.claude/state/full-self-evaluation"
RUN_ID="${EVAL_RUN_ID:-$( [ -f "$RUN_DIR/run-id.txt" ] && cat "$RUN_DIR/run-id.txt" || echo unknown )}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
EVID="$RUN_DIR/raw/task-runs/$SCENARIO/$ARM-$STAMP"
# The scenario workspace must live OUTSIDE the repo's own .claude/ tree. Sited under
# .claude/state/... the child session's edits were denied by path-based permission rules and the
# run looked like a pipeline failure when the agent had in fact produced the correct edit and was
# simply refused permission to write it. Evidence still lands in the repo; only the scratch
# workspace moves.
WORK="${EVAL_SCENARIO_WORKDIR:-${TMPDIR:-/tmp}/ck-eval-scenarios}/$SCENARIO-$ARM-$STAMP"
mkdir -p "$EVID" "$WORK"

echo "### materialise the fixture (a fresh git repo, so the oracle can diff the end state)"
cp -a "$ROOT/tests/evals/e2e/fixtures/$FIXTURE/." "$WORK/"
git -C "$WORK" init -q
git -C "$WORK" add -A
git -C "$WORK" -c user.email=eval@local -c user.name=eval commit -qm "fixture baseline"
FIXTURE_SHA="$(git -C "$WORK" rev-parse --short HEAD)"

echo "### install the kit into the fixture (Docker — the host never runs project code)"
"$ROOT/scripts/evals/run-in-docker.sh" --service python --label "$SCENARIO-$ARM-scaffold" \
	--mount "$WORK:/work" --workdir /repo --timeout 600 -- \
	env PYTHONPATH=/repo/src python -m claude_kit.cli init /work --defaults

if [ "$RULES_MODE" = "none" ]; then
	RULE_BYTES="$(cat "$WORK"/.claude/rules/*.md 2>/dev/null | wc -c | tr -d ' ')"
	RULE_FILES="$(find "$WORK/.claude/rules" -name '*.md' 2>/dev/null | wc -l | tr -d ' ')"
	# Withheld rules go to the EVIDENCE directory, not into the workspace: nothing scenario-owned
	# may exist inside the tree the performer works in until grading time.
	mv "$WORK/.claude/rules" "$EVID/rules-withheld"
	echo "### DEVIATION rules-mode=none: withheld $RULE_FILES rule files ($RULE_BYTES bytes)"
fi

if [ "$RULES_MODE" = "ondemand" ]; then
	# `none` cannot be used to test the PIPELINE: the sdlc skill is explicitly told to read
	# .claude/rules/mandatory-workflow.md, quality-gates.md and rarv-cycle.md, so withholding them
	# would break the pipeline by construction and no failure could be attributed to the product.
	#
	# This arm instead uses the lever docs/rules-context-budget.md already identifies: a rule
	# carrying `paths:` frontmatter loads only when a matching file is touched. Every rule stays at
	# its canonical .claude/rules/<name>.md path and remains readable on request; it simply stops
	# being force-fed into the context window at launch. The glob deliberately matches nothing, so
	# "auto-loaded" is off while "readable" is untouched. Still a DEVIATION from the shipped
	# default, and recorded as one.
	scoped=0
	for rf in "$WORK"/.claude/rules/*.md; do
		[ -f "$rf" ] || continue
		head -n1 "$rf" | grep -q '^---$' && continue # already has frontmatter; leave it alone
		{
			printf -- '---\npaths:\n  - "**/__ck_eval_never_matches__/**"\n---\n\n'
			cat "$rf"
		} >"$rf.scoped" && mv "$rf.scoped" "$rf"
		scoped=$((scoped + 1))
	done
	echo "### DEVIATION rules-mode=ondemand: added paths: frontmatter to $scoped rule files (still readable at .claude/rules/)"
fi

echo "### project test command (delegates into Docker)"
# The execution-plane rule forbids the host from running project tests, but a pipeline that cannot
# run tests cannot pass a test gate — which is exactly what happened in the first /sdlc arm
# (build-green UNVERIFIED, ten refused pytest calls). Giving the fixture a real test command that
# shells into the run's Docker wrapper resolves the conflict instead of choosing a side: the child
# runs the project's tests, and the tests run in a container, with the usual evidence record.
#
# This is harness-provided project tooling, not grading criteria — it is committed with the scaffold
# and appears in the manifest, so it is never mistaken for something the session created.
mkdir -p "$WORK/scripts"
cat >"$WORK/scripts/test.sh" <<EOF
#!/usr/bin/env sh
# The project's test command. Runs the suite inside a container; never on the host.
#
# The three EVAL_* exports are load-bearing: run-in-docker.sh derives its repo root from
# \`git rev-parse --show-toplevel\`, and this script is invoked with the SCENARIO WORKSPACE as cwd —
# itself a git repo. Without them the wrapper looked for docker-compose.evals.yml inside the
# workspace, died "compose file not found", and the pipeline concluded it had no way to run tests.
export EVAL_COMPOSE_FILE="$ROOT/docker-compose.evals.yml"
export EVAL_RUN_DIR="$RUN_DIR"
export EVAL_RUN_ID="$RUN_ID"
exec "$ROOT/scripts/evals/run-in-docker.sh" --echo --service "$SERVICE" \\
	--label "$SCENARIO-$ARM-projtest" --mount "$WORK:/work" --workdir /work --timeout 600 -- \\
	$TEST_COMMAND
EOF
chmod +x "$WORK/scripts/test.sh"

# A claude-kit CLI for the child, pinned to the REPO's version. The host happens to carry 0.54.0 on
# PATH, which predates the gate ledger entirely — letting the pipeline find that binary would
# guarantee a false negative about ledger recording. The shim lives outside the workspace so it is
# never mistaken for a project artifact.
mkdir -p "$EVID/bin"
cat >"$EVID/bin/claude-kit" <<EOF
#!/usr/bin/env sh
export EVAL_COMPOSE_FILE="$ROOT/docker-compose.evals.yml"
export EVAL_RUN_DIR="$RUN_DIR"
export EVAL_RUN_ID="$RUN_ID"
exec "$ROOT/scripts/evals/run-in-docker.sh" --echo --service python \\
	--label "$SCENARIO-$ARM-ckit" --mount "$WORK:/work" --workdir /work --timeout 600 -- \\
	env PYTHONPATH=/repo/src python -m claude_kit.cli "\$@"
EOF
chmod +x "$EVID/bin/claude-kit"
cp "$EVID/bin/claude-kit" "$EVID/bin/ckit"
# Fill in the scaffolded CLAUDE.md's command section the way a real user would after `init`.
cat >>"$WORK/CLAUDE.md" <<'EOF'

## Project commands

- **Test:** `bash scripts/test.sh` — this is the ONLY way to run the suite in this project. It
  executes the tests inside a container. Do not invoke the test runner directly; a direct
  invocation is not permitted here and will be refused.
EOF

# Commit the scaffold BEFORE the session, so the end-state diff and the oracle's stray-artifact
# check see the session's work alone. Without this the installed kit (203 files) is indistinguishable
# from something the run created, and every scenario reports stray artifacts.
git -C "$WORK" add -A
git -C "$WORK" -c user.email=eval@local -c user.name=eval commit -qm "kit scaffold installed"
SCAFFOLD_SHA="$(git -C "$WORK" rev-parse --short HEAD)"
echo "scaffold committed as $SCAFFOLD_SHA (fixture baseline was $FIXTURE_SHA)"

echo "### pre-session manifest (path -> sha256 of every file the session could touch)"
# Written OUTSIDE the workspace and injected only at grading time. It replaces `git diff` in the
# oracles for two reasons: the node image ships no git, and a performer is free to commit its own
# work — a hash manifest is indifferent to whether a change was committed.
"$ROOT/scripts/evals/run-in-docker.sh" --service python --label "$SCENARIO-$ARM-manifest" \
	--mount "$WORK:/work:ro" --mount "$EVID:/evid" --workdir /work --timeout 300 -- \
	env python -c '
import hashlib, json, pathlib
root = pathlib.Path("/work")
out = {}
for p in sorted(root.rglob("*")):
    rel = p.relative_to(root).as_posix()
    if not p.is_file() or rel.startswith(".git/"):
        continue
    out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
pathlib.Path("/evid/manifest.json").write_text(json.dumps(out, indent=2, sort_keys=True))
print(f"manifest: {len(out)} files")'

echo "### child Claude session (host control plane, isolated config)"
PROMPT="$(cat "$PROMPT_FILE")"
cp "$PROMPT_FILE" "$EVID/prompt.txt"

# ISOLATED CONFIG. `claude -p` otherwise loads the OPERATOR's ~/.claude, including PreToolUse guard
# hooks that deny any Bash line starting python/pip/npm/docker. Every scenario before this one was
# therefore measured through the operator's permission posture rather than the kit's — up to 28
# denials in a single run, with roughly ten pytest invocations refused across the session, the
# developer agent and the reviewer (E-006).
#
# The allow-list is deliberately narrow rather than "Bash". The program forbids the host from
# running project tests, so the child may not invoke pytest directly; it gets `scripts/test.sh`,
# which delegates into the Docker wrapper. That keeps both statements true at once: the pipeline
# ran the tests, and the tests ran in a container.
CFG="$EVID/claude-config"
mkdir -p "$CFG"
cat >"$CFG/settings.json" <<'JSON'
{
  "permissions": {
    "allow": [
      "Read", "Write", "Edit", "Glob", "Grep",
      "Agent", "Skill", "TaskCreate", "TaskGet", "TaskList", "TaskUpdate",
      "Bash(bash scripts/test.sh)", "Bash(sh scripts/test.sh)", "Bash(./scripts/test.sh)",
      "Bash(claude-kit:*)", "Bash(ckit:*)",
      "Bash(git status:*)", "Bash(git diff:*)", "Bash(git log:*)", "Bash(git show:*)",
      "Bash(ls:*)", "Bash(cat:*)", "Bash(head:*)", "Bash(tail:*)", "Bash(wc:*)",
      "Bash(find:*)", "Bash(grep:*)", "Bash(rg:*)", "Bash(sed:*)", "Bash(awk:*)",
      "Bash(mkdir:*)", "Bash(cp:*)", "Bash(mv:*)", "Bash(echo:*)", "Bash(printf:*)",
      "Bash(command:*)", "Bash(which:*)", "Bash(pwd)", "Bash(date:*)"
    ],
    "deny": []
  }
}
JSON

set +e
( cd "$WORK" && PATH="$EVID/bin:$PATH" CLAUDE_CONFIG_DIR="$CFG" claude -p "$PROMPT" \
	--max-turns "$MAX_TURNS" \
	--output-format stream-json --verbose \
	--permission-mode acceptEdits ) >"$EVID/session.jsonl" 2>"$EVID/session.stderr"
SESSION_RC=$?
set -e

# The stream carries every tool_use; the single `result` event at the end is what the old
# --output-format json produced, so downstream metrics keep working unchanged.
python3 - "$EVID/session.jsonl" "$EVID/session.json" "$EVID/tool-use.json" <<'PY'
import collections, json, sys

stream, result_out, tools_out = sys.argv[1], sys.argv[2], sys.argv[3]
events = []
for line in open(stream, encoding="utf-8"):
    line = line.strip()
    if not line:
        continue
    try:
        events.append(json.loads(line))
    except json.JSONDecodeError:
        pass

result = next((e for e in reversed(events) if e.get("type") == "result"), {})
json.dump(result, open(result_out, "w"), indent=2)

counts = collections.Counter()
skills, agents, bash, denied_like = [], [], [], []
for e in events:
    msg = e.get("message") or {}
    for block in msg.get("content") or []:
        if not isinstance(block, dict) or block.get("type") != "tool_use":
            continue
        name = block.get("name", "?")
        counts[name] += 1
        inp = block.get("input") or {}
        if name == "Skill":
            skills.append(inp.get("skill") or inp.get("name"))
        elif name in ("Agent", "Task"):
            agents.append(inp.get("subagent_type") or inp.get("description"))
        elif name == "Bash":
            bash.append(str(inp.get("command", ""))[:200])

json.dump({
    "tool_calls": dict(counts.most_common()),
    "skills_invoked": skills,
    "agents_spawned": agents,
    "bash_commands": bash,
    "stream_events": len(events),
}, open(tools_out, "w"), indent=2)
print(json.dumps({"tool_calls": dict(counts.most_common()),
                  "skills_invoked": skills, "agents_spawned": agents}, indent=2))
PY
echo "child session exit=$SESSION_RC ($(wc -l <"$EVID/session.jsonl" | tr -d ' ') stream events)"

echo "### metrics"
python3 - "$EVID/session.json" "$EVID/metrics.json" "$SCENARIO" "$ARM" "$SESSION_RC" <<'PY'
import json, sys
raw, out, scenario, arm, rc = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5])
try:
    d = json.loads(open(raw, encoding="utf-8").read())
except Exception as e:                      # a crashed session still has to produce a record
    d = {"_unparseable": str(e)}
u = d.get("usage") or {}
m = {
    "scenario": scenario, "arm": arm, "session_exit_code": rc,
    "is_error": d.get("is_error"), "api_error_status": d.get("api_error_status"),
    "stop_reason": d.get("stop_reason"), "terminal_reason": d.get("terminal_reason"),
    "num_turns": d.get("num_turns"), "wall_time_seconds": (d.get("duration_ms") or 0) / 1000.0,
    "tokens": {
        "input": u.get("input_tokens"), "output": u.get("output_tokens"),
        "cache_read": u.get("cache_read_input_tokens"),
        "cache_creation": u.get("cache_creation_input_tokens"),
    },
    "cost_usd": d.get("total_cost_usd"),
    "models": sorted((d.get("modelUsage") or {})),
    "permission_denials": d.get("permission_denials"),
    "session_id": d.get("session_id"),
}
open(out, "w", encoding="utf-8").write(json.dumps(m, indent=2) + "\n")
print(json.dumps({k: m[k] for k in ("num_turns", "wall_time_seconds", "cost_usd", "is_error")}, indent=2))
PY

echo "### end-state diff"
git -C "$WORK" add -A >/dev/null 2>&1 || true
git -C "$WORK" diff --cached --stat >"$EVID/end-state.diffstat" 2>/dev/null || true
git -C "$WORK" diff --cached >"$EVID/end-state.diff" 2>/dev/null || true
cat "$EVID/end-state.diffstat"

echo "### pipeline artifacts (observation, not a gate)"
# Whether the SDLC pipeline actually RAN is a separate question from whether the task was done, and
# conflating them is how a scenario starts claiming stage coverage it has not earned: SC-01..SC-03
# all passed their oracles while producing no ticket, board or gate ledger whatsoever (E-005). This
# records what the run left behind so stage claims rest on artifacts rather than on a PASS.
"$ROOT/scripts/evals/run-in-docker.sh" --service python --label "$SCENARIO-$ARM-artifacts" \
	--mount "$WORK:/work:ro" --mount "$EVID:/evid" --workdir /work --timeout 300 -- \
	env python -c '
import json, pathlib
w = pathlib.Path("/work")
def listing(rel):
    d = w / rel
    return sorted(p.relative_to(w).as_posix() for p in d.rglob("*") if p.is_file()) if d.is_dir() else []
snap = w / ".claude/state/pipeline-snapshot.json"
parsed = None
if snap.is_file():
    try:
        parsed = json.loads(snap.read_text(encoding="utf-8"))
    except Exception as e:
        parsed = {"_unparseable": str(e)}
out = {
    "tickets": listing(".claude/tickets"),
    "pipeline_state_files": listing(".claude/state"),
    "pipeline_snapshot_present": snap.is_file(),
    "gate_history": (parsed or {}).get("gate_history"),
    "last_gate_passed": (parsed or {}).get("last_gate_passed"),
    "mode": (parsed or {}).get("mode"),
    "lanes": (parsed or {}).get("lanes"),
    "board_html": [p for p in listing(".claude") if p.endswith(".html")],
    "continuity_bytes": (w / ".claude/CONTINUITY.md").stat().st_size
        if (w / ".claude/CONTINUITY.md").is_file() else 0,
}
pathlib.Path("/evid/pipeline-artifacts.json").write_text(json.dumps(out, indent=2))
print(json.dumps({k: (len(v) if isinstance(v, list) else v) for k, v in out.items()}, indent=2))'

echo "### inject the grader (AFTER the session — never before)"
# The oracle used to be copied in before the child session started, which put the grading criteria
# inside the performer's own workspace. Any run could have read `.scenario/oracle.py` and satisfied
# the checks directly, and a sealed holdout would have been impossible: the spec forbids revealing
# holdout expectations to a task performer. Everything the grader needs therefore lands here, after
# the session has ended and after the end-state diff has been captured.
mkdir -p "$WORK/.scenario"
ORACLE_EXT="${ORACLE##*.}"
cp "$ROOT/tests/evals/e2e/oracles/$ORACLE" "$WORK/.scenario/oracle.$ORACLE_EXT"
cp -a "$ROOT/tests/evals/e2e/fixtures/$FIXTURE" "$WORK/.scenario/pristine"
cp "$EVID/manifest.json" "$WORK/.scenario/manifest.json"
# SC-01's oracle predates the manifest and reads baseline-hashes.json; the manifest is a superset.
cp "$EVID/manifest.json" "$WORK/.scenario/baseline-hashes.json"
printf '%s\n' "$SCAFFOLD_SHA" >"$WORK/.scenario/scaffold-sha.txt"
if [ -n "$HOLDOUT" ]; then
	cp -a "$ROOT/tests/evals/e2e/holdouts/$HOLDOUT" "$WORK/.scenario/holdout"
	echo "sealed holdout injected: $(find "$WORK/.scenario/holdout" -type f | wc -l | tr -d ' ') file(s)"
fi

echo "### deterministic oracle (Docker, service=$SERVICE)"
case "$ORACLE_EXT" in
py) ORACLE_INTERP=python ;;
js) ORACLE_INTERP=node ;;
*) echo "run-scenario: no interpreter for .$ORACLE_EXT oracles" >&2; exit 2 ;;
esac
set +e
"$ROOT/scripts/evals/run-in-docker.sh" --service "$SERVICE" --label "$SCENARIO-$ARM-oracle" \
	--mount "$WORK:/work" --workdir /work --timeout 600 -- \
	env "$ORACLE_INTERP" "/work/.scenario/oracle.$ORACLE_EXT" /work
ORACLE_RC=$?
set -e

LAST_ORACLE="$(ls -dt "$RUN_DIR"/raw/docker/*-"$SCENARIO-$ARM-oracle" | head -1)"
cp "$LAST_ORACLE/stdout.txt" "$EVID/oracle-verdict.json" 2>/dev/null || true

python3 - "$EVID/run.json" "$SCENARIO" "$ARM" "$FIXTURE_SHA" "$ORACLE_RC" "$EVID" "$RULES_MODE" \
	"$FIXTURE" "$ORACLE" "$HOLDOUT" "$SERVICE" "$SCAFFOLD_SHA" <<'PY'
import json, sys
out, scenario, arm, fx, rc, evid, rules_mode, fixture, oracle, holdout, service, scaffold = sys.argv[1:13]
json.dump({
    "scenario": scenario, "arm": arm, "fixture": fixture,
    "fixture_baseline_sha": fx, "scaffold_sha": scaffold,
    "oracle": oracle, "oracle_service": service,
    "sealed_holdout": holdout or None,
    "grader_injected": "after the session ended (never visible to the performer)",
    "oracle_exit_code": int(rc), "verdict": "PASS" if int(rc) == 0 else "FAIL",
    "rules_mode": rules_mode,
    "deviation": {
        "full": None,
        "none": ".claude/rules withheld entirely after scaffold — NOT the shipped default (F-014)",
        "ondemand": "paths: frontmatter added to .claude/rules/*.md so they are readable but not "
                    "auto-loaded — NOT the shipped default (F-014); the lever docs/"
                    "rules-context-budget.md calls Direction C",
    }.get(rules_mode, f"unrecognised rules_mode {rules_mode!r}"),
    "evidence_dir": evid,
}, open(out, "w"), indent=2)
PY

echo "=== $SCENARIO/$ARM verdict: $([ "$ORACLE_RC" -eq 0 ] && echo PASS || echo FAIL) (evidence: $EVID)"
exit "$ORACLE_RC"
