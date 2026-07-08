#!/usr/bin/env bash
# sdlc-loop.sh — bounded headless /sdlc loop (installed by claude-kit).
#
# Each iteration runs `claude -p` with a one-gate contract: re-enter the pipeline at the
# first gate after `last_gate_passed`, pass AT MOST one more gate, update the snapshot,
# stop. Three deliberate brakes keep an unattended run honest:
#
#   1. iteration cap      — SDLC_MAX_ITER   (default 8)
#   2. per-iteration spend — SDLC_BUDGET_USD (default 5; passed to --max-budget-usd)
#   3. stall detection    — the same gate token twice in a row exits nonzero for a human
#
# The exit condition is the installed profile's FINAL gate token. By default it is read
# from .claude/config/stack-catalog.snapshot.yaml (written by `claude-kit init`; its
# `gates:` list is in execution order, so the last entry is the finish line). Every knob
# is an environment variable:
#
#   SDLC_FINAL_GATE       final gate token (required if the snapshot yaml is absent,
#                         e.g. after the no-pip init.sh fallback install)
#   SDLC_MAX_ITER         iteration cap (default 8)
#   SDLC_BUDGET_USD       per-iteration --max-budget-usd (default 5)
#   SDLC_PERMISSION_MODE  --permission-mode per run (default acceptEdits)
#   SDLC_PROMPT           full replacement prompt (advanced — keep the one-gate contract)
#
# Safety posture (details: docs/autonomous-operation.md in the claude-kit repo):
#   - headless runs DENY anything not pre-authorized — pre-authorize narrowly, never bypass
#   - a stalled or capped loop exits nonzero FOR A HUMAN; read the transcript and the
#     snapshot — never restart with looser brakes
#   - run from the project root (the directory containing .claude/)
set -u

[ -d .claude ] || { echo "sdlc-loop: run from the project root (no .claude/ here)" >&2; exit 2; }
command -v claude >/dev/null 2>&1 || { echo "sdlc-loop: 'claude' CLI not found on PATH" >&2; exit 2; }

SNAP=.claude/state/pipeline-snapshot.json
CATALOG=.claude/config/stack-catalog.snapshot.yaml

FINAL_GATE="${SDLC_FINAL_GATE:-}"
if [ -z "$FINAL_GATE" ] && [ -f "$CATALOG" ]; then
  # Last entry of the top-level `gates:` block sequence (the list is execution-ordered).
  FINAL_GATE=$(awk '/^gates:/{f=1; next} f && /^- /{g=$2} f && /^[a-zA-Z_]/{exit} END{if (g) print g}' "$CATALOG")
fi
if [ -z "$FINAL_GATE" ]; then
  echo "sdlc-loop: no final gate token. Set SDLC_FINAL_GATE=<token> (no $CATALOG to read it from)." >&2
  exit 2
fi

MAX_ITER="${SDLC_MAX_ITER:-8}"
BUDGET="${SDLC_BUDGET_USD:-5}"
MODE="${SDLC_PERMISSION_MODE:-acceptEdits}"
PROMPT="${SDLC_PROMPT:-Continue the /sdlc run per .claude/CONTINUITY.md. Re-enter at the first gate after last_gate_passed in $SNAP. Pass at most ONE more gate, update the snapshot, then stop.}"

echo "sdlc-loop: final gate '$FINAL_GATE' | $MAX_ITER iteration(s) max | \$$BUDGET/iteration | mode $MODE"

prev_gate=""
for i in $(seq 1 "$MAX_ITER"); do
  echo "sdlc-loop: iteration $i/$MAX_ITER"
  claude -p --permission-mode "$MODE" --max-budget-usd "$BUDGET" "$PROMPT" ||
    echo "sdlc-loop: claude exited nonzero (continuing; the stall brake decides)" >&2
  gate=$(sed -n 's/.*"last_gate_passed": *"\([^"]*\)".*/\1/p' "$SNAP" 2>/dev/null)
  if [ "$gate" = "$FINAL_GATE" ]; then
    echo "sdlc-loop: pipeline complete: $gate"
    exit 0
  fi
  if [ "$gate" = "$prev_gate" ]; then
    echo "sdlc-loop: STALLED at gate '${gate:-none}' — human review needed (read the transcript and $SNAP; do NOT loosen the brakes)" >&2
    exit 1
  fi
  prev_gate="$gate"
done
echo "sdlc-loop: iteration cap ($MAX_ITER) reached at gate '${prev_gate:-none}' — human review needed" >&2
exit 1
