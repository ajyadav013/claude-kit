#!/usr/bin/env bash
# sdlc-loop.sh — fail-closed compatibility entrypoint for headless SDLC execution.
#
# Claude and Codex subprocesses cannot portably prove that every descendant is
# terminated: a child may create a new session and outlive the coordinator. Until
# a provider supplies real descendant containment, this script never starts a host
# process and never mints a lifecycle-transition token. It only recognizes an
# already-completed run after strict ledger validation.
set -u

if [ -d .ckit ]; then
  STATE_ROOT=.ckit
elif [ -d .claude ]; then
  STATE_ROOT=.claude
else
  echo "sdlc-loop: run from a project root containing .ckit/ or legacy .claude/" >&2
  exit 2
fi

if command -v ckit >/dev/null 2>&1; then
  CKIT_CLI=ckit
elif command -v claude-kit >/dev/null 2>&1; then
  CKIT_CLI=claude-kit
else
  echo "sdlc-loop: 'ckit' CLI not found on PATH" >&2
  exit 2
fi
command -v python3 >/dev/null 2>&1 || {
  echo "sdlc-loop: 'python3' not found on PATH" >&2
  exit 2
}

SNAP="$STATE_ROOT/state/pipeline-snapshot.json"
if [ ! -f "$SNAP" ]; then
  echo "sdlc-loop: pipeline snapshot not found at $SNAP" >&2
  exit 2
fi

state_fields=$(python3 -c 'import json, sys; data = json.load(open(sys.argv[1], encoding="utf-8")); status = data.get("status"); gate = data.get("last_gate_resolved"); print("{}\t{}".format(status if isinstance(status, str) else "", gate if isinstance(gate, str) else ""))' "$SNAP" 2>/dev/null) || {
  echo "sdlc-loop: malformed pipeline snapshot — human review needed" >&2
  exit 1
}
IFS=$'\t' read -r status gate <<< "$state_fields"

if [ "$status" = "completed" ]; then
  if validation_output=$("$CKIT_CLI" pipeline validate . --strict 2>&1); then
    echo "sdlc-loop: pipeline complete and strictly validated (last resolved gate: ${gate:-none})"
    exit 0
  fi
  echo "sdlc-loop: REFUSING unvalidated completed status — human review needed" >&2
  echo "$validation_output" >&2
  exit 1
fi

echo "sdlc-loop: Unsupported — automated host execution requires portable descendant-process containment; no Claude/Codex process was started and no lifecycle token was minted" >&2
exit 3
