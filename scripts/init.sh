#!/usr/bin/env bash
# Compatibility launcher for historical callers of scripts/init.sh.
#
# Project installation now requires the Python CLI because only that path can share
# ProjectFS containment checks, strict staging validation, and the rollback journal.
# This wrapper deliberately performs no filesystem mutation of its own.
set -euo pipefail

if command -v claude-kit >/dev/null 2>&1; then
  exec claude-kit init "$@"
fi
if command -v ckit >/dev/null 2>&1; then
  exec ckit init "$@"
fi
if command -v claude-sdlc >/dev/null 2>&1; then
  exec claude-sdlc init "$@"
fi

cat >&2 <<'EOF'
error: the legacy shell scaffolder was retired in claude-kit 0.83.0.

It could not provide the Python installer's path-containment, symlink/reparse-point,
strict-staging, and rollback-transaction guarantees. Install the supported CLI, then retry:

  pipx install claude-code-kit
  claude-kit init <target> [options]

No project files were changed.
EOF
exit 2
