#!/usr/bin/env bash
# Measure the standing context a scaffolded claude-kit project injects into a fresh session.
#
# Standing context is what a session pays BEFORE any work: it is the number F-041 is about.
# The only honest way to attribute it is by difference -- an empty-directory control establishes
# the harness baseline, and the kit's cost is (scaffolded - control). Quoting the scaffolded
# total as "the kit's cost" overstates it by the whole harness baseline, which is the mistake
# this script exists to make impossible to repeat.
#
# Usage: measure-standing-context.sh <label> <dir>
# Prints one TSV row: label  input  cache_creation  cache_read  total
set -uo pipefail
LABEL="${1:?label}"; DIR="${2:?dir}"
[ -d "$DIR" ] || { echo "$LABEL	ERR	no such dir" >&2; exit 1; }
OUT=$(cd "$DIR" && claude -p "Reply with exactly: OK" --output-format json 2>/dev/null)
[ -n "$OUT" ] || { echo "$LABEL	ERR	empty response" >&2; exit 1; }
printf '%s' "$OUT" | python3 -c '
import json,sys
d=json.load(sys.stdin); u=d.get("usage",d)
i=u.get("input_tokens",0); cc=u.get("cache_creation_input_tokens",0); cr=u.get("cache_read_input_tokens",0)
print(f"{sys.argv[1]}\t{i}\t{cc}\t{cr}\t{i+cc+cr}")' "$LABEL"
