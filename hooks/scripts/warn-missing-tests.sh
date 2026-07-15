#!/usr/bin/env bash
# PostToolUse(Edit|Write): after a source-code change, check for EVIDENCE of tests before nudging.
# Evidence-based, not a blanket reminder: looks for a sibling/convention-named test file
# (test_<stem>.py, <stem>_test.py, <stem>.test|spec.<ext>, <stem>_test.go, <stem>Test(s).cs, ...)
# in the same dir and in tests//test//__tests__ dirs walking up from the file; if a test file
# exists, checks .pytest_cache/v/cache/lastfailed for a recorded RED test for the module (Python).
# Emits a SPECIFIC message only when evidence is absent; stays quiet when a test file exists.
# Advisory only (always exits 0). Quiet for test files, docs, config, generated/infra trees, and
# the .claude/ config itself. Degrades to a no-op without jq.
# The reminder returns as hookSpecificOutput.additionalContext JSON on stdout (Claude reads it next
# to the tool result, per the current hooks reference) -- exit-0 stderr is debug-log-only.
command -v jq >/dev/null 2>&1 || exit 0
INPUT="$(cat)"
FILE_PATH="$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_response.filePath // empty' 2>/dev/null || true)"
[ -z "$FILE_PATH" ] || [ "$FILE_PATH" = "null" ] && exit 0

low="$(printf '%s' "$FILE_PATH" | tr '[:upper:]' '[:lower:]')"

# Skip non-source: tests, docs, config, markdown, and the kit's own config.
case "$low" in
  *test*|*spec*|*.md|*.markdown|*.json|*.ya?ml|*.toml|*.ini|*.cfg|*.txt|*.lock|*/.claude/*)
    exit 0 ;;
esac

# Curated skip list: trees that legitimately ship without sibling tests (generated, infra, vendored).
case "$low" in
  */migrations/*|*/alembic/*|*/terraform/*|*/generated/*|*/proto/*|*/infra/*|*/dist/*|*/build/*|*/node_modules/*|*/vendor/*|*/.venv/*)
    exit 0 ;;
esac

# Only check recognisable source files.
case "$low" in
  *.py|*.ts|*.tsx|*.js|*.jsx|*.go|*.rs|*.rb|*.java|*.kt|*.cs|*.php|*.swift|*.scala|*.c|*.cc|*.cpp|*.h|*.hpp) : ;;
  *) exit 0 ;;
esac

base="$(basename "$FILE_PATH")"
dir="$(dirname "$FILE_PATH")"
stem="${base%.*}"
ext="${base##*.}"

# Test-file name candidates per ecosystem convention.
cands=()
case "$ext" in
  py)          cands=("test_${stem}.py" "${stem}_test.py") ;;
  go)          cands=("${stem}_test.go") ;;
  cs)          cands=("${stem}Tests.cs" "${stem}Test.cs") ;;
  rb)          cands=("${stem}_spec.rb" "${stem}_test.rb") ;;
  ts|tsx|js|jsx) cands=("${stem}.test.${ext}" "${stem}.spec.${ext}") ;;
  *)           cands=("test_${stem}.${ext}" "${stem}_test.${ext}" "${stem}.test.${ext}" "${stem}.spec.${ext}") ;;
esac

# Evidence search: sibling in the same dir, then tests//test//__tests__ dirs walking up (bounded).
found=""
for cand in "${cands[@]}"; do
  [ -f "$dir/$cand" ] && { found=1; break; }
done
if [ -z "$found" ]; then
  d="$dir"
  for _ in 1 2 3 4 5 6; do
    for td in tests test __tests__; do
      [ -d "$d/$td" ] || continue
      for cand in "${cands[@]}"; do
        if find "$d/$td" -maxdepth 4 -name "$cand" -print -quit 2>/dev/null | grep -q .; then
          found=1
          break 3
        fi
      done
    done
    parent="$(dirname "$d")"
    [ "$parent" = "$d" ] && break
    d="$parent"
  done
fi

W=""
if [ -z "$found" ]; then
  W="REMINDER: no test file found for $FILE_PATH (searched sibling + tests//test//__tests__ conventions: ${cands[*]}) -- create one before marking work complete (.claude/rules/testing.md)."
elif [ "$ext" = "py" ] && [ -f ".pytest_cache/v/cache/lastfailed" ]; then
  # A test file exists; for Python, check whether a RED test was ever recorded for this module.
  if ! jq -r 'keys[]' .pytest_cache/v/cache/lastfailed 2>/dev/null | grep -q "$stem"; then
    W="NOTE: tests exist for $stem but no failing test was recorded for it -- if this change adds behavior, write the RED test first (.claude/rules/testing.md)."
  fi
fi

if [ -n "$W" ]; then
  # stdout must be ONLY the JSON object for Claude Code to process it.
  jq -n --arg ctx "$W" '{hookSpecificOutput: {hookEventName: "PostToolUse", additionalContext: $ctx}}'
fi
exit 0
