#!/usr/bin/env bash
# PreToolUse(Bash): BLOCK `kubectl delete` — destructive deletes must not run from an agent session.
#
# Why a guard (block, exit 2) and not a warn: a delete is irreversible and trivially misfires against
# the wrong namespace or cluster. A PreToolUse advisory would be theatre — the resource would already
# be gone. So this refuses and points at the reversible alternatives (scale to 0, rollout undo, or
# removing the object from the Git/Helm source and letting the pipeline reconcile). It joins the
# guard-rm-rf / guard-push-main / guard-destructive-git destructive-command family.
#
# Scope is deliberately the `delete` SUBCOMMAND only, matched as a whole word, so it spares the safe
# look-alikes that merely contain the string "delete":
#   - `kubectl config delete-context|delete-cluster|delete-user` (local kubeconfig edits, hyphenated)
#   - `kubectl drain ... --delete-emptydir-data`                 (a drain flag, hyphenated)
#   - `kubectl wait --for=delete ...`                            (a wait condition, after '=')
#   - `kubectl auth can-i delete <res>`                          (a READ-ONLY RBAC query)
# Compound commands are split on ; | & first, so a chained delete (e.g. `get -o name | xargs kubectl
# delete`) is caught per-segment. Threat model: this prevents accidental agent deletes, not a determined
# operator who deliberately crafts a bypass string (they own the machine and can disable the hook).
#
# Degrades to a no-op (fail-open) without jq — consistent with the other script-backed guards.
command -v jq >/dev/null 2>&1 || exit 0
CMD="$(jq -r '.tool_input.command // empty' 2>/dev/null || true)"
[ -z "$CMD" ] && exit 0

# Split on shell separators → one segment per line; drop read-only `auth can-i` queries; keep only
# kubectl segments; then look for a bare `delete` verb (not delete-context, --delete-*, or --for=delete).
if printf '%s' "$CMD" | tr ';|&' '\n\n\n' \
  | grep -vE 'auth[[:space:]]+can-i' \
  | grep -E '(^|[[:space:]])kubectl(\.exe)?[[:space:]]' \
  | grep -qE '(^|[[:space:]])delete([[:space:]]|$)'; then
  echo "BLOCKED: 'kubectl delete' is disabled by claude-kit — destructive deletes must not run from an agent session." >&2
  echo "  Use a reversible alternative: 'kubectl scale --replicas=0' to stop a workload, 'kubectl rollout undo' to roll back," >&2
  echo "  or remove the resource from the Git/Helm source and let the pipeline reconcile." >&2
  echo "  Read-only checks still work ('kubectl auth can-i delete <res>', 'kubectl get/describe'). (guard-kubectl-delete.sh)" >&2
  exit 2
fi
exit 0
