#!/usr/bin/env bash
# Report Docker resources this evaluation run created and did not clean up.
#
# "No leaked run-owned Docker resources" is a terminal condition of the self-evaluation program, so
# the query that decides it must be committed rather than retyped each turn. It was retyped, and it
# carried a label name that does not exist anywhere in this repo (`claude-kit-eval-run`; the real
# one is `ck-eval-run`). A filter on a nonexistent label matches nothing, so the check reported
# CLEAN for fourteen turns without ever being able to report anything else — while a real orphan
# sat in the compose project.
#
# Ownership is therefore established through BOTH channels, because neither alone is sufficient:
#
#   ck-eval-run=<run-id>              the wrapper's own label. Correct on the ad-hoc `docker create`
#                                     path, where it is passed as a literal argument.
#   com.docker.compose.project=<proj> the compose path. Authoritative even when the label above is
#                                     wrong, which it was for every compose container until
#                                     EVAL_RUN_ID was exported.
#
#   check-docker-leaks.sh [--remove]
#
# Exit 0 when nothing is leaked, 1 when something is. --remove deletes ONLY resources matched by the
# two ownership channels above; anything this run did not create is never touched.
set -Eeuo pipefail

REMOVE=0
[ "${1:-}" = "--remove" ] && REMOVE=1

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
RUN_DIR="${EVAL_RUN_DIR:-$ROOT/.claude/state/full-self-evaluation}"
RUN_ID="${EVAL_RUN_ID:-$( [ -f "$RUN_DIR/run-id.txt" ] && cat "$RUN_DIR/run-id.txt" || echo unknown )}"
PROJECT="claude-kit-eval-$(printf '%s' "$RUN_ID" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9_-' '-')"

# ids_for <kind> — union of both ownership channels, deduplicated.
ids_for() {
	{
		docker "$1" ls -q --filter "label=ck-eval-run=$RUN_ID" 2>/dev/null || true
		docker "$1" ls -q --filter "label=com.docker.compose.project=$PROJECT" 2>/dev/null || true
	} | sort -u
}

CONTAINERS="$(
	{
		docker ps -aq --filter "label=ck-eval-run=$RUN_ID" 2>/dev/null || true
		docker ps -aq --filter "label=com.docker.compose.project=$PROJECT" 2>/dev/null || true
	} | sort -u
)"
VOLUMES="$(ids_for volume)"
NETWORKS="$(ids_for network)"

count() { [ -z "$1" ] && echo 0 || printf '%s\n' "$1" | wc -l | tr -d ' '; }

NC="$(count "$CONTAINERS")"
NV="$(count "$VOLUMES")"
NN="$(count "$NETWORKS")"

printf 'run_id=%s project=%s\n' "$RUN_ID" "$PROJECT"
printf 'containers=%s volumes=%s networks=%s\n' "$NC" "$NV" "$NN"

if [ "$NC" -gt 0 ]; then
	printf '%s\n' "$CONTAINERS" | while read -r id; do
		[ -n "$id" ] && docker ps -a --filter "id=$id" --format '  container {{.Names}}  {{.Status}}'
	done
fi
[ "$NV" -gt 0 ] && printf '  volume %s\n' $VOLUMES
[ "$NN" -gt 0 ] && printf '  network %s\n' $NETWORKS

TOTAL=$((NC + NV + NN))
if [ "$TOTAL" -eq 0 ]; then
	echo "OK: no run-owned Docker resources remain"
	exit 0
fi

if [ "$REMOVE" -eq 1 ]; then
	[ -n "$CONTAINERS" ] && printf '%s\n' "$CONTAINERS" | xargs -r docker rm --force >/dev/null
	[ -n "$VOLUMES" ] && printf '%s\n' "$VOLUMES" | xargs -r docker volume rm --force >/dev/null
	[ -n "$NETWORKS" ] && printf '%s\n' "$NETWORKS" | xargs -r docker network rm >/dev/null 2>&1 || true
	echo "removed $TOTAL run-owned resource(s)"
	exit 0
fi

echo "LEAK: $TOTAL run-owned Docker resource(s) remain"
exit 1
