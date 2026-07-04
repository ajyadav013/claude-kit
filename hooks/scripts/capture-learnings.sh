#!/usr/bin/env bash
# Agent-side half of the self-improving learnings loop -- NON-BLOCKING. One script, three triggers,
# chosen at init by `capture_mode` (catalog/capture.yaml); dispatched by $1:
#
#   end      (SessionEnd)   capture the session that just ended (the default mode).
#   stop     (Stop)         per-task: capture only the file edits made SINCE the previous Stop.
#   catchup  (SessionStart) capture any PRIOR session that ended without being captured -- i.e. one
#                           closed abruptly (Ctrl-C / kill / terminal close), where SessionEnd never
#                           ran. This is what makes capture robust to abrupt close.
#
# In every mode: if there are file edits to learn from, fire a fully-detached background `claude` job
# that reviews what changed and records any DURABLE learning into .claude/agent-memory/ (the store the
# `remember` skill uses, auto-loaded next session by load-learnings.sh). The hook returns instantly and
# never blocks the session or the next prompt -- the work happens out-of-band in a reparented orphan.
#
# Conservative + safe by construction:
#   * Silent no-op without jq/claude, without a transcript, or when the project has no agent-memory.
#   * Only spawns when there were actually file edits (chat-only sessions/turns cost nothing).
#   * Opt out (or break recursion) with CLAUDE_KIT_NO_AUTOCAPTURE=1 -- the one var serves both: a user
#     sets it to disable; the spawned child inherits it so its OWN hooks self-skip. Belt-and-suspenders:
#     the child also runs with --settings '{"disableAllHooks":true}'.
#   * The background job runs sandboxed (Read/Grep/Glob/Write/Edit only -- NO shell/Bash) and inherits
#     the user's logged-in auth. Override the model with CLAUDE_KIT_CAPTURE_MODEL.
#   * .claude/ is a Claude-Code-protected path that acceptEdits CANNOT write in a non-interactive
#     (no-TTY) background context -- even with a scoped allow-rule the agent reliably gives up. So the
#     child runs with --permission-mode bypassPermissions. That is safe here: it has only file tools
#     (no shell to run commands) and the prompt confines all writes to .claude/agent-memory/.
#   * A per-transcript "done" marker in the temp dir lets `end`/`stop` tell `catchup` "already handled",
#     so a cleanly-exited session is never re-captured on the next launch.
set -u

MODE="${1:-end}"   # end | stop | catchup

TMP="${TMPDIR:-/tmp}"

# --- privacy: skip sensitive files, redact secret-shaped values, bound the payload --------------
# Capture is ON by default and reads your session -- so it must never carry credentials into
# .claude/agent-memory/ (a committed store). Mirrors guard-secrets.sh: EXCLUDE secret-bearing file
# paths from the changed-file list entirely, and REDACT leaked-credential VALUE shapes (not env var
# NAMES) from anything handed to the background job. Bounds are env-overridable.
_SENSITIVE_FILE_RE='(^|/)\.env($|\.)|\.(pem|key|p12|pfx)$|credentials?\.(json|ya?ml|md)$'
_SECRET_VALUE_RE='-----BEGIN [A-Z ]*PRIVATE KEY-----|AKIA[0-9A-Z]{16}|sk_live_[0-9a-zA-Z]{16,}|xox[baprs]-[0-9A-Za-z-]{10,}|gh[ps]_[0-9A-Za-z]{30,}'

CAP_MAX_LINES="${CLAUDE_KIT_CAPTURE_MAX_LINES:-50}"
case "$CAP_MAX_LINES" in '' | *[!0-9]*) CAP_MAX_LINES=50 ;; esac
CAP_MAX_BYTES="${CLAUDE_KIT_CAPTURE_MAX_BYTES:-8000}"
case "$CAP_MAX_BYTES" in '' | *[!0-9]*) CAP_MAX_BYTES=8000 ;; esac

# Replace leaked-credential value shapes with [REDACTED] before a blob reaches the prompt/log.
_redact() { sed -E "s/(${_SECRET_VALUE_RE})/[REDACTED]/g"; }

# --- helpers -------------------------------------------------------------------------------------

# Canonical key for a transcript: its basename without .jsonl (== the session id Claude Code uses for
# the filename). Shared by all modes so `end`'s done-marker matches `catchup`'s lookup.
tkey() { local b; b=$(basename "$1"); printf '%s' "${b%.jsonl}"; }

# Filesystem-safe token for marker/lock/log filenames.
_safe() { printf '%s' "$1" | tr -c 'A-Za-z0-9._-' '_'; }

_marker() { printf '%s/claude-kit-captured-%s.done' "$TMP" "$(_safe "$1")"; }
mark_done() { : >"$(_marker "$1")" 2>/dev/null || true; }
is_done() { [ -f "$(_marker "$1")" ]; }

# Edit-like file paths in a transcript. Optional $2 = 1-based first line to scan from (for `stop`).
# Handles both transcript shapes (.message.content and a bare .content); malformed lines yield none.
changed_files() {
  local t="$1" start="${2:-1}"
  tail -n "+${start}" "$t" 2>/dev/null | jq -rs '
    [ .[]?
      | ((.message.content? // .content?) // empty)
      | select(type == "array")
      | .[]?
      | select(.type? == "tool_use")
      | select(.name? == "Edit" or .name? == "Write" or .name? == "MultiEdit" or .name? == "NotebookEdit")
      | (.input?.file_path? // .input?.notebook_path? // empty)
    ] | unique | .[]
  ' 2>/dev/null | grep -ivE "$_SENSITIVE_FILE_RE" | head -n "$CAP_MAX_LINES"
}

line_count() { wc -l <"$1" 2>/dev/null | tr -d ' '; }

# spawn_capture <transcript> <changed-files> <lock-key>
# Fire a fully-detached background `claude` that records at most one durable learning. The ( ... )
# </dev/null >/dev/null 2>&1 & idiom reparents the child to init/launchd so this hook returns
# immediately and the job survives the session ending. A per-key mkdir lock keeps it idempotent.
spawn_capture() {
  local transcript="$1" changed="$2" key="$3"
  local lock log today prompt
  # Defence in depth: redact any leaked-credential value shapes and bound the size of the
  # changed-file blob before it reaches the prompt or the log.
  changed=$(printf '%s' "$changed" | _redact | head -c "$CAP_MAX_BYTES")
  lock="$TMP/claude-kit-capture-$(_safe "$key").lock"
  log="$TMP/claude-kit-capture-$(_safe "$key").log"
  today=$(date -u +%Y-%m-%d 2>/dev/null)

  # Self-contained prompt: does NOT depend on the remember skill being discoverable in the child.
  prompt="You are claude-kit's background learning-capture agent. A coding session in this project
produced the file changes below. Decide whether it produced a DURABLE, REUSABLE learning and, if so,
record exactly one into this project's agent-memory. Act autonomously; do not ask questions; then stop.

Files changed:
${changed}

Session transcript (JSONL -- read the last ~300 lines for the reasoning/context): ${transcript}
Today: ${today}

You have ONLY the Read/Grep/Glob/Write/Edit tools -- there is no shell. Create and update files DIRECTLY
with the Write and Edit tools (do not attempt Bash/heredocs); writes under .claude/agent-memory/ are
permitted.

PRIVACY (mandatory): .claude/agent-memory/ is a committed store. NEVER record secrets, credentials,
API keys, tokens, connection strings, or personal data into it. If a candidate learning can only be
expressed by quoting such a value, skip it. Capture the durable lesson, never the secret.

Steps:
1. Read the changed files above and the tail of the transcript to understand WHAT changed and WHY.
2. Read .claude/agent-memory/MEMORY.md and skim the matching category folder to avoid duplicates.
3. Decide with a STRICT bar: is there a learning a FUTURE session should follow -- a correction,
   preference, rule/convention, architecture decision, gotcha, API quirk, or performance insight? Do
   NOT record anything already visible in the code, standard framework behavior, or routine/one-off
   task state. MOST sessions yield nothing; if so, write nothing and stop.
4. Only if there is a genuine durable learning, do BOTH of these -- both are REQUIRED:
   (a) Write .claude/agent-memory/<category>/<kebab-slug>.md (category = one of ux, architecture,
       debugging, patterns, api, performance, gotchas), or refine a closely-matching existing file
       instead of duplicating. Use YAML frontmatter with: title, category, date (${today}), trigger;
       then sections: Context, Learning (capture the WHY, not just the what), Evidence, Apply when.
   (b) Append ONE index line to .claude/agent-memory/MEMORY.md -- under the matching '###' section if
       one exists, otherwise at the end of the file -- in exactly this form:
       - [Title](category/filename.md) -- one-line hook | applies when: <trigger>
   CRITICAL: step (b) is mandatory. The SessionStart loader reads ONLY MEMORY.md, so a learning that is
   not indexed there is INVISIBLE to every future session. After doing both, RE-READ MEMORY.md and
   confirm your index line is present; if it is missing, add it before you finish.
   (If the remember skill is available you may follow it; it uses this same format.)
5. Output one line: 'No learning captured.' or 'Recorded: <path> (indexed in MEMORY.md)'. Then stop."

  local args=(-p "$prompt" --permission-mode bypassPermissions \
    --allowedTools Read Grep Glob Write Edit --settings '{"disableAllHooks":true}')
  [ -n "${CLAUDE_KIT_CAPTURE_MODEL:-}" ] && args+=(--model "$CLAUDE_KIT_CAPTURE_MODEL")

  (
    mkdir "$lock" 2>/dev/null || exit 0
    trap 'rmdir "$lock" 2>/dev/null' EXIT INT TERM
    {
      echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] capture start (mode=${MODE}, key=${key}, ${PROJ})"
      cd "$PROJ" 2>/dev/null || exit 0
      CLAUDE_KIT_NO_AUTOCAPTURE=1 claude "${args[@]}"
      echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] capture done"
    } >>"$log" 2>&1
  ) </dev/null >/dev/null 2>&1 &
}

# --- main: opt-out, parse input, dispatch --------------------------------------------------------
# When sourced (e.g. by the test suite) rather than executed, stop here so only the helper functions
# above are defined -- everything below has side effects (reads stdin, spawns a background job).
if [ "${BASH_SOURCE[0]}" != "$0" ]; then
  return 0
fi

# --- opt-out + recursion guard -> silent no-op ---------------------------------------------------
[ -n "${CLAUDE_KIT_NO_AUTOCAPTURE:-}" ] && exit 0
command -v jq >/dev/null 2>&1 || exit 0
command -v claude >/dev/null 2>&1 || exit 0

INPUT=$(cat 2>/dev/null) || exit 0
[ -n "$INPUT" ] || exit 0

TRANSCRIPT=$(printf '%s' "$INPUT" | jq -r '.transcript_path // empty' 2>/dev/null)
PROJ=$(printf '%s' "$INPUT" | jq -r '.cwd // empty' 2>/dev/null)
[ -n "$PROJ" ] || PROJ="${CLAUDE_PROJECT_DIR:-$PWD}"

# Need the learnings store to write into, and a transcript path to locate work.
[ -d "$PROJ/.claude/agent-memory" ] || exit 0
[ -n "$TRANSCRIPT" ] || exit 0

case "$MODE" in
  end)
    # The session that just ended. Capture if it edited files; mark done either way so a later
    # `catchup` never re-handles this (cleanly-exited) session.
    [ -f "$TRANSCRIPT" ] || exit 0
    key=$(tkey "$TRANSCRIPT")
    changed=$(changed_files "$TRANSCRIPT")
    [ -n "$changed" ] && spawn_capture "$TRANSCRIPT" "$changed" "$key"
    mark_done "$key"
    ;;

  stop)
    # Per-task: only the edits since the previous Stop (a per-session line-count sentinel scopes
    # "this task"). Each task gets its own lock key so a slow capture never makes the next one skip.
    [ -f "$TRANSCRIPT" ] || exit 0
    key=$(tkey "$TRANSCRIPT")
    sentinel="$TMP/claude-kit-capture-$(_safe "$key").line"
    last=$(cat "$sentinel" 2>/dev/null); case "$last" in (''|*[!0-9]*) last=0;; esac
    total=$(line_count "$TRANSCRIPT"); case "$total" in (''|*[!0-9]*) total=0;; esac
    changed=$(changed_files "$TRANSCRIPT" "$((last + 1))")
    printf '%s' "$total" >"$sentinel" 2>/dev/null || true
    [ -n "$changed" ] && spawn_capture "$TRANSCRIPT" "$changed" "${key}-${total}"
    mark_done "$key"
    ;;

  catchup)
    # SessionStart: review sibling transcripts in this project's session dir. Any that has edits, is
    # stale (mtime > 2 min so it's not the current/a live session) but recent (< 7 days), and has no
    # done-marker, is a session whose SessionEnd never ran (abrupt close) -> capture it now. Bounded
    # to a few per launch to cap cost; the markers mean the rest are picked up on later launches.
    # Writes NOTHING to stdout (must not pollute the SessionStart context injected by load-learnings).
    dir=$(dirname "$TRANSCRIPT")
    [ -d "$dir" ] || exit 0
    cur=$(tkey "$TRANSCRIPT")
    CATCHUP_MAX=3
    spawned=0
    # Newest-first so the most recently abandoned session is caught first.
    while IFS= read -r sib; do
      [ -n "$sib" ] || continue
      [ "$spawned" -ge "$CATCHUP_MAX" ] && break
      sid=$(tkey "$sib")
      [ "$sid" = "$cur" ] && continue
      is_done "$sid" && continue
      changed=$(changed_files "$sib")
      if [ -z "$changed" ]; then
        mark_done "$sid"   # no edits to learn from; don't re-scan it next launch
        continue
      fi
      spawn_capture "$sib" "$changed" "$sid"
      mark_done "$sid"
      spawned=$((spawned + 1))
    done < <(find "$dir" -maxdepth 1 -name '*.jsonl' -mmin +2 -mmin -10080 -print0 2>/dev/null \
             | xargs -0 ls -1t 2>/dev/null)
    ;;

  *)
    exit 0
    ;;
esac

exit 0
