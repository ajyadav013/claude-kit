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

while [ $# -gt 0 ]; do
	case "$1" in
	--scenario) SCENARIO="${2:?}"; shift 2 ;;
	--fixture) FIXTURE="${2:?}"; shift 2 ;;
	--oracle) ORACLE="${2:?}"; shift 2 ;;
	--prompt-file) PROMPT_FILE="${2:?}"; shift 2 ;;
	--arm) ARM="${2:?}"; shift 2 ;;
	--max-turns) MAX_TURNS="${2:?}"; shift 2 ;;
	*) echo "run-scenario: unknown option $1" >&2; exit 2 ;;
	esac
done
for v in SCENARIO FIXTURE ORACLE PROMPT_FILE; do
	[ -n "${!v}" ] || { echo "run-scenario: --${v,,} is required" >&2; exit 2; }
done

ROOT="$(git rev-parse --show-toplevel)"
RUN_DIR="$ROOT/.claude/state/full-self-evaluation"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
EVID="$RUN_DIR/raw/task-runs/$SCENARIO/$ARM-$STAMP"
WORK="$RUN_DIR/scenario-work/$SCENARIO-$ARM-$STAMP"
mkdir -p "$EVID" "$WORK"

echo "### materialise the fixture (a fresh git repo, so the oracle can diff the end state)"
cp -a "$ROOT/tests/evals/e2e/fixtures/$FIXTURE/." "$WORK/"
mkdir -p "$WORK/.scenario"
cp "$ROOT/tests/evals/e2e/oracles/$ORACLE" "$WORK/.scenario/oracle.py"
git -C "$WORK" init -q
git -C "$WORK" add -A
git -C "$WORK" -c user.email=eval@local -c user.name=eval commit -qm "fixture baseline"
FIXTURE_SHA="$(git -C "$WORK" rev-parse --short HEAD)"

echo "### baseline hashes (computed from the pristine fixture, never hardcoded in the oracle)"
"$ROOT/scripts/evals/run-in-docker.sh" --service python --label "$SCENARIO-$ARM-hashes" \
	--mount "$WORK:/work" --workdir /work --timeout 300 -- \
	env python -c '
import hashlib, json, pathlib
out = {f: hashlib.sha256(pathlib.Path(f).read_bytes()).hexdigest()
       for f in ("src/calc.py", "tests/test_calc.py", "pyproject.toml")}
pathlib.Path(".scenario/baseline-hashes.json").write_text(json.dumps(out, indent=2))
print("baseline hashes:", json.dumps(out, indent=2))'

echo "### install the kit into the fixture (Docker — the host never runs project code)"
"$ROOT/scripts/evals/run-in-docker.sh" --service python --label "$SCENARIO-$ARM-scaffold" \
	--mount "$WORK:/work" --workdir /repo --timeout 600 -- \
	env PYTHONPATH=/repo/src python -m claude_kit.cli init /work --defaults

# Commit the scaffold BEFORE the session, so the end-state diff and the oracle's stray-artifact
# check see the session's work alone. Without this the installed kit (203 files) is indistinguishable
# from something the run created, and every scenario reports stray artifacts.
git -C "$WORK" add -A
git -C "$WORK" -c user.email=eval@local -c user.name=eval commit -qm "kit scaffold installed"
SCAFFOLD_SHA="$(git -C "$WORK" rev-parse --short HEAD)"
echo "scaffold committed as $SCAFFOLD_SHA (fixture baseline was $FIXTURE_SHA)"

echo "### child Claude session (host control plane)"
PROMPT="$(cat "$PROMPT_FILE")"
cp "$PROMPT_FILE" "$EVID/prompt.txt"
set +e
( cd "$WORK" && claude -p "$PROMPT" \
	--max-turns "$MAX_TURNS" \
	--output-format json \
	--permission-mode acceptEdits ) >"$EVID/session.json" 2>"$EVID/session.stderr"
SESSION_RC=$?
set -e
echo "child session exit=$SESSION_RC ($(wc -c <"$EVID/session.json" | tr -d ' ') bytes of result)"

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

echo "### deterministic oracle (Docker)"
set +e
"$ROOT/scripts/evals/run-in-docker.sh" --service python --label "$SCENARIO-$ARM-oracle" \
	--mount "$WORK:/work" --workdir /work --timeout 600 -- \
	env python /work/.scenario/oracle.py /work
ORACLE_RC=$?
set -e

LAST_ORACLE="$(ls -dt "$RUN_DIR"/raw/docker/*-"$SCENARIO-$ARM-oracle" | head -1)"
cp "$LAST_ORACLE/stdout.txt" "$EVID/oracle-verdict.json" 2>/dev/null || true

python3 - "$EVID/run.json" "$SCENARIO" "$ARM" "$FIXTURE_SHA" "$ORACLE_RC" "$EVID" <<'PY'
import json, sys
out, scenario, arm, fx, rc, evid = sys.argv[1:7]
json.dump({
    "scenario": scenario, "arm": arm, "fixture_baseline_sha": fx,
    "oracle_exit_code": int(rc), "verdict": "PASS" if int(rc) == 0 else "FAIL",
    "evidence_dir": evid,
}, open(out, "w"), indent=2)
PY

echo "=== $SCENARIO/$ARM verdict: $([ "$ORACLE_RC" -eq 0 ] && echo PASS || echo FAIL) (evidence: $EVID)"
exit "$ORACLE_RC"
