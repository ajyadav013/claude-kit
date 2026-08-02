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

# Emit $1 as a JSON string literal, quotes included.
#
# The previous sed version was line-oriented: a multi-line `sh -c` payload wrote literal newlines
# inside the string, so meta.json only parsed with Python's json.loads(strict=False) and a
# spec-compliant reader would reject the entry outright. An evidence ledger that a strict parser
# drops is indistinguishable from an evidence ledger that was never written.
json_string() {
	printf '%s' "$1" | awk '
		BEGIN {
			for (i = 1; i < 32; i++) ord[sprintf("%c", i)] = i
			printf "\""
		}
		{
			if (NR > 1) printf "\\n"
			n = length($0)
			for (i = 1; i <= n; i++) {
				c = substr($0, i, 1)
				if (c == "\"") printf "\\\""
				else if (c == "\\") printf "\\\\"
				else if (c == "\t") printf "\\t"
				else if (c in ord) printf "\\u%04x", ord[c]
				else printf "%s", c
			}
		}
		END { printf "\"" }
	'
}

ROOT="$(repo_root)"
RUN_DIR="${EVAL_RUN_DIR:-$ROOT/.claude/state/full-self-evaluation}"
RUN_ID="${EVAL_RUN_ID:-$( [ -f "$RUN_DIR/run-id.txt" ] && cat "$RUN_DIR/run-id.txt" || echo unknown )}"
COMPOSE_FILE="${EVAL_COMPOSE_FILE:-$ROOT/docker-compose.evals.yml}"
# Compose rejects a project name containing uppercase, and run ids carry an ISO-8601 stamp.
COMPOSE_PROJECT="claude-kit-eval-$(printf '%s' "$RUN_ID" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9_-' '-')"
# EXPORT, not merely assign: docker-compose.evals.yml interpolates `${EVAL_RUN_ID:-unknown}` into
# every service's `ck-eval-run` label, and compose reads it from the ENVIRONMENT. Left unexported,
# every compose container was labelled the literal string "unknown", so a leak query by run id
# matched nothing and the ownership label could not identify what this run created.
export EVAL_RUN_ID="$RUN_ID"

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
# so the command must never run.
#
# `pipefail` is requested but does NOT reach a payload of the form `sh -c '... | tail'` — the option
# is not exported, so the nested shell starts without it. That was equally true of the earlier
# string-splicing form; the real control against a pipeline reporting only its last command's status
# is `pipe_in_payload` in the evidence record, plus validate-suite.sh never piping a check.
# INNER_CMD is for the EVIDENCE RECORD ONLY. The payload itself is handed to the container as real
# argv and re-executed with `exec "$@"`, so nothing is ever re-quoted: `printf %q` emits bash's
# $'...' form for a payload containing a newline or tab, which POSIX /bin/sh (dash) cannot parse —
# the container then exited 127, indistinguishable from "command not found". A wrapper that mangles
# its payload and reports a plausible failure code is worse than one that refuses to run.
INNER_CMD="$(printf '%q ' "$@")"
WRAPPED="if [ ! -f /.dockerenv ]; then echo 'FATAL: /.dockerenv absent — not inside Docker' >&2; exit ${DOCKERENV_FAILURE}; fi; (set -o pipefail) 2>/dev/null && set -o pipefail; exec \"\$@\""

pipe_risk=false
case " $* " in
*"|"*) pipe_risk=true ;;
esac

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
	docker create "${docker_args[@]}" "$IMAGE" sh -c "$WRAPPED" ck-eval "$@" >"$EV_DIR/create.txt" 2>&1 || {
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
	run_env=()
	for kv in ${ENVS+"${ENVS[@]}"}; do
		run_env+=(--env "$kv")
	done
	for mnt in ${MOUNTS+"${MOUNTS[@]}"}; do
		run_env+=(--volume "$mnt")
	done
	watchdog &
	wd=$!
	# --entrypoint sh is explicit: the runner services declare `entrypoint: ["sh","-c"]` for
	# interactive use, which would otherwise swallow the wrapped command as $0.
	docker compose "${compose_args[@]}" run --name "$CONTAINER_NAME" --no-TTY --rm=false \
		--workdir "$WORKDIR" --user "$USER_SPEC" --entrypoint sh \
		${run_env+"${run_env[@]}"} \
		"$SERVICE" -c "$WRAPPED" ck-eval "$@" >"$EV_DIR/stdout.txt" 2>"$EV_DIR/stderr.txt" || rc=$?
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
	printf '  "command": %s,\n' "$(json_string "$INNER_CMD")"
	printf '  "container_id": "%s",\n' "$container_id"
	printf '  "image_id": "%s",\n' "$image_id"
	printf '  "started_at": "%s",\n' "$STARTED_AT"
	printf '  "finished_at": "%s",\n' "$finished_at"
	printf '  "timeout_seconds": %s,\n' "$TIMEOUT"
	printf '  "timed_out": %s,\n' "$timed_out"
	printf '  "dockerenv_verified": %s,\n' "$dockerenv_verified"
	printf '  "pipe_in_payload": %s,\n' "$pipe_risk"
	printf '  "network": "%s",\n' "$NETWORK"
	printf '  "exit_code": %s\n' "$rc"
	printf '}\n'
} >"$EV_DIR/meta.json"

cleanup

printf 'run-in-docker: exit=%s dockerenv=%s evidence=%s\n' "$rc" "$dockerenv_verified" "$EV_DIR" >&2
exit "$rc"
