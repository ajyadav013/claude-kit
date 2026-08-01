#!/usr/bin/env bash
# Canonical Docker execution wrapper for the self-evaluation program.
#
# No verification result counts unless its evidence proves the command ran inside a container, so
# every command is prefixed with a `/.dockerenv` assertion and the wrapper records the image ID,
# container ID, timestamps, captured streams, and the REAL exit code under the run directory.
#
#   run-in-docker.sh --image <ref>   [opts] -- <cmd...>    # ad-hoc container
#   run-in-docker.sh --service <name> [opts] -- <cmd...>   # docker-compose.evals.yml service
#
# Options:
#   --label <slug>        evidence directory name suffix (default: derived from the command)
#   --timeout <seconds>   watchdog kill (default: 900)
#   --network <name>      docker network (default: none — no egress unless asked for)
#   --mount <src:dst[:ro]>  bind mount, repeatable (host paths must be absolute)
#   --env <K=V>           environment variable, repeatable
#   --workdir <path>      working directory inside the container (default: /repo)
#   --user <uid[:gid]>    run as a non-root UID (default: the invoking host user)
#
# Exit code: the container's own exit code. 97 means the /.dockerenv assertion failed, 124 a
# timeout, 125 a wrapper/Docker-level error before the command ever ran.

set -Eeuo pipefail

DOCKERENV_FAILURE=97
TIMEOUT_FAILURE=124
WRAPPER_FAILURE=125

die() {
	printf 'run-in-docker: %s\n' "$1" >&2
	exit "$WRAPPER_FAILURE"
}

repo_root() {
	git rev-parse --show-toplevel 2>/dev/null || pwd
}

ROOT="$(repo_root)"
RUN_DIR="${EVAL_RUN_DIR:-$ROOT/.claude/state/full-self-evaluation}"
RUN_ID="${EVAL_RUN_ID:-$( [ -f "$RUN_DIR/run-id.txt" ] && cat "$RUN_DIR/run-id.txt" || echo unknown )}"
COMPOSE_FILE="${EVAL_COMPOSE_FILE:-$ROOT/docker-compose.evals.yml}"
COMPOSE_PROJECT="claude-kit-eval-${RUN_ID}"

IMAGE=""
SERVICE=""
LABEL=""
TIMEOUT=900
NETWORK="none"
WORKDIR="/repo"
USER_SPEC="$(id -u):$(id -g)"
MOUNTS=()
ENVS=()

while [ $# -gt 0 ]; do
	case "$1" in
	--image) IMAGE="${2:?--image needs a value}"; shift 2 ;;
	--service) SERVICE="${2:?--service needs a value}"; shift 2 ;;
	--label) LABEL="${2:?--label needs a value}"; shift 2 ;;
	--timeout) TIMEOUT="${2:?--timeout needs a value}"; shift 2 ;;
	--network) NETWORK="${2:?--network needs a value}"; shift 2 ;;
	--workdir) WORKDIR="${2:?--workdir needs a value}"; shift 2 ;;
	--user) USER_SPEC="${2:?--user needs a value}"; shift 2 ;;
	--mount) MOUNTS+=("${2:?--mount needs a value}"); shift 2 ;;
	--env) ENVS+=("${2:?--env needs a value}"); shift 2 ;;
	--) shift; break ;;
	*) die "unknown option: $1" ;;
	esac
done

[ $# -gt 0 ] || die "no command given (use -- <cmd...>)"
[ -n "$IMAGE" ] || [ -n "$SERVICE" ] || die "one of --image or --service is required"
[ -z "$IMAGE" ] || [ -z "$SERVICE" ] || die "--image and --service are mutually exclusive"
command -v docker >/dev/null 2>&1 || die "docker CLI not found"
docker info >/dev/null 2>&1 || die "docker daemon unreachable"

# --- evidence directory -------------------------------------------------------------------------
if [ -z "$LABEL" ]; then
	LABEL="$(printf '%s' "$1" | tr -cs 'a-zA-Z0-9' '-' | cut -c1-32)"
fi
STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
EV_DIR="$RUN_DIR/raw/docker/${STAMP}-${LABEL}"
mkdir -p "$EV_DIR" || die "cannot create evidence dir $EV_DIR"

CONTAINER_NAME="ckeval-$(printf '%s' "$RUN_ID" | tr -cs 'a-zA-Z0-9' '-' | cut -c1-24)-${STAMP}-$$"
TIMEOUT_MARKER="$EV_DIR/.timed-out"

# The assertion that makes a result admissible: if this file is absent we are not in a container,
# so the command must never run. "$@" is re-quoted so the payload survives the sh -c hop intact.
INNER_CMD="$(printf '%q ' "$@")"
WRAPPED="if [ ! -f /.dockerenv ]; then echo 'FATAL: /.dockerenv absent — not inside Docker' >&2; exit ${DOCKERENV_FAILURE}; fi; ${INNER_CMD}"

docker_args=(
	--name "$CONTAINER_NAME"
	--label "ck-eval-run=$RUN_ID"
	--label "ck-eval-label=$LABEL"
	--network "$NETWORK"
	--workdir "$WORKDIR"
	--user "$USER_SPEC"
	--cap-drop ALL
	--security-opt no-new-privileges
	--memory 4g
	--pids-limit 512
)
for mnt in ${MOUNTS+"${MOUNTS[@]}"}; do
	docker_args+=(--volume "$mnt")
done
for kv in ${ENVS+"${ENVS[@]}"}; do
	docker_args+=(--env "$kv")
done

cleanup() {
	docker rm --force "$CONTAINER_NAME" >/dev/null 2>&1 || true
}

watchdog() {
	local waited=0
	while [ "$waited" -lt "$TIMEOUT" ]; do
		sleep 1
		waited=$((waited + 1))
		docker inspect "$CONTAINER_NAME" >/dev/null 2>&1 || return 0
		[ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER_NAME" 2>/dev/null)" = "true" ] || return 0
	done
	: >"$TIMEOUT_MARKER"
	docker kill "$CONTAINER_NAME" >/dev/null 2>&1 || true
}

# --- run ------------------------------------------------------------------------------------------
rc=0
if [ -n "$IMAGE" ]; then
	docker create "${docker_args[@]}" "$IMAGE" sh -c "$WRAPPED" >"$EV_DIR/create.txt" 2>&1 || {
		cp "$EV_DIR/create.txt" "$EV_DIR/stderr.txt" 2>/dev/null || true
		die "docker create failed — see $EV_DIR/create.txt"
	}
	watchdog &
	wd=$!
	docker start --attach "$CONTAINER_NAME" >"$EV_DIR/stdout.txt" 2>"$EV_DIR/stderr.txt" || rc=$?
	kill "$wd" 2>/dev/null || true
	wait "$wd" 2>/dev/null || true
else
	[ -f "$COMPOSE_FILE" ] || die "compose file not found: $COMPOSE_FILE"
	compose_args=(--project-name "$COMPOSE_PROJECT" --file "$COMPOSE_FILE")
	watchdog &
	wd=$!
	docker compose "${compose_args[@]}" run --name "$CONTAINER_NAME" --no-TTY --rm=false \
		--workdir "$WORKDIR" --user "$USER_SPEC" \
		"$SERVICE" sh -c "$WRAPPED" >"$EV_DIR/stdout.txt" 2>"$EV_DIR/stderr.txt" || rc=$?
	kill "$wd" 2>/dev/null || true
	wait "$wd" 2>/dev/null || true
fi

# --- evidence ---------------------------------------------------------------------------------------
container_id="$(docker inspect -f '{{.Id}}' "$CONTAINER_NAME" 2>/dev/null || echo unknown)"
image_id="$(docker inspect -f '{{.Image}}' "$CONTAINER_NAME" 2>/dev/null || echo unknown)"
state_rc="$(docker inspect -f '{{.State.ExitCode}}' "$CONTAINER_NAME" 2>/dev/null || echo "$rc")"
finished_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# The container's own recorded exit status is the authority; the client's status can be masked by
# an attach/transport error, so only fall back to it when Docker has no answer.
if [ "$state_rc" != "unknown" ] && [ -n "$state_rc" ]; then
	rc="$state_rc"
fi
timed_out=false
if [ -f "$TIMEOUT_MARKER" ]; then
	timed_out=true
	rc="$TIMEOUT_FAILURE"
	rm -f "$TIMEOUT_MARKER"
fi

dockerenv_verified=true
if [ "$rc" = "$DOCKERENV_FAILURE" ]; then
	dockerenv_verified=false
fi

{
	printf '{\n'
	printf '  "run_id": "%s",\n' "$RUN_ID"
	printf '  "label": "%s",\n' "$LABEL"
	printf '  "mode": "%s",\n' "$([ -n "$IMAGE" ] && echo image || echo service)"
	printf '  "target": "%s",\n' "${IMAGE:-$SERVICE}"
	printf '  "command": %s,\n' "$(printf '%s' "$INNER_CMD" | sed 's/\\/\\\\/g; s/"/\\"/g; s/^/"/; s/ $/"/')"
	printf '  "container_id": "%s",\n' "$container_id"
	printf '  "image_id": "%s",\n' "$image_id"
	printf '  "started_at": "%s",\n' "$STARTED_AT"
	printf '  "finished_at": "%s",\n' "$finished_at"
	printf '  "timeout_seconds": %s,\n' "$TIMEOUT"
	printf '  "timed_out": %s,\n' "$timed_out"
	printf '  "dockerenv_verified": %s,\n' "$dockerenv_verified"
	printf '  "network": "%s",\n' "$NETWORK"
	printf '  "exit_code": %s\n' "$rc"
	printf '}\n'
} >"$EV_DIR/meta.json"

cleanup

printf 'run-in-docker: exit=%s dockerenv=%s evidence=%s\n' "$rc" "$dockerenv_verified" "$EV_DIR" >&2
exit "$rc"
