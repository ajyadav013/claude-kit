#!/usr/bin/env bash
#
# capture-sdlc-run.sh — bundle ONE completed `/sdlc` run into a publishable, redaction-scrubbed folder.
#
# A real `/sdlc` run leaves its evidence scattered across the project: the spec lands in
# `docs/specs/`, the gate state in gitignored `.claude/state/`, the verdict log in gitignored
# `.claude/CONTINUITY.md`, and the code in git itself. This script gathers those into one folder,
# runs a generic secret scan, and prints a manual-redaction checklist — so you can turn a run into
# a worked example without hand-collecting files.
#
# It is READ-ONLY against your project: it copies files out, never edits or deletes anything in place.
#
# Usage:
#   scripts/capture-sdlc-run.sh [--project DIR] [--out DIR] [--base BRANCH] [--slug NAME]
#
#   --project DIR   Project root to capture from        (default: current directory)
#   --out DIR       Where to write the bundle           (default: ./claude-kit-run-<UTC-timestamp>)
#   --base BRANCH   Base branch to diff the code against (default: main)
#   --slug NAME     Short label folded into the default --out name
#   -h, --help      Show this help
#
# The bundle is NOT auto-published and NOT auto-committed. Review it, finish the redaction checklist,
# then copy what you want into `examples/` (or your own docs) yourself.

set -euo pipefail

PROJECT="."
OUT=""
BASE="main"
SLUG=""

die() { printf 'error: %s\n' "$1" >&2; exit 1; }

usage() {
  sed -n '2,28p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

while [ $# -gt 0 ]; do
  case "$1" in
    --project) PROJECT="${2:-}"; shift 2 ;;
    --out)     OUT="${2:-}";     shift 2 ;;
    --base)    BASE="${2:-}";    shift 2 ;;
    --slug)    SLUG="${2:-}";    shift 2 ;;
    -h|--help) usage 0 ;;
    *) die "unknown argument: $1 (try --help)" ;;
  esac
done

[ -d "$PROJECT" ] || die "project directory not found: $PROJECT"
PROJECT="$(cd "$PROJECT" && pwd)"

if [ -z "$OUT" ]; then
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  if [ -n "$SLUG" ]; then
    OUT="./claude-kit-run-${stamp}-${SLUG}"
  else
    OUT="./claude-kit-run-${stamp}"
  fi
fi

mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"
[ "$OUT" = "$PROJECT" ] && die "--out must not be the project root itself"

printf '==> capturing /sdlc run from: %s\n' "$PROJECT"
printf '==> writing bundle to:       %s\n\n' "$OUT"

missing=0

# copy_one SRC DEST_SUBPATH LABEL — copy a single file if it exists, else note it.
copy_one() {
  src="$PROJECT/$1"; dest="$OUT/$2"; label="$3"
  if [ -f "$src" ]; then
    mkdir -p "$(dirname "$dest")"
    cp "$src" "$dest"
    printf '  [ok]   %s\n' "$label"
  else
    printf '  [skip] %s (not found: %s)\n' "$label" "$1"
    missing=$((missing + 1))
  fi
}

# --- 1. The artifacts a run produces -----------------------------------------------------------
printf 'Collecting run artifacts:\n'
copy_one ".claude/state/pipeline-snapshot.json"        "state/pipeline-snapshot.json"        "pipeline snapshot (gate state, findings, evidence)"
copy_one ".claude/config/stack-catalog.snapshot.yaml"  "state/stack-catalog.snapshot.yaml"   "install snapshot (profile + resolved gate set)"
copy_one ".claude/CONTINUITY.md"                       "continuity.md"                       "working memory / verdict log"

# Specs (docs/specs/*_spec.md) and filled artifacts may be many — copy whatever is present.
if [ -d "$PROJECT/docs/specs" ]; then
  spec_count="$(find "$PROJECT/docs/specs" -maxdepth 1 -name '*_spec.md' -type f 2>/dev/null | wc -l | tr -d ' ')"
  if [ "$spec_count" != "0" ]; then
    mkdir -p "$OUT/specs"
    find "$PROJECT/docs/specs" -maxdepth 1 -name '*_spec.md' -type f -exec cp {} "$OUT/specs/" \;
    printf '  [ok]   %s spec file(s) from docs/specs/\n' "$spec_count"
  else
    printf '  [skip] no *_spec.md in docs/specs/\n'; missing=$((missing + 1))
  fi
else
  printf '  [skip] docs/specs/ (not found)\n'; missing=$((missing + 1))
fi

# --- 1b. Evidence files the snapshot points at -------------------------------------------------
# The pipeline snapshot records a `gate_evidence` map of absolute paths. Pull those artifacts into
# the bundle and rewrite the snapshot to point at the copied, bundle-relative files — so the bundle
# is self-contained and leaks no local filesystem paths. Needs python3 (json); skipped with a note
# if it is absent, leaving the snapshot untouched.
snap_copy="$OUT/state/pipeline-snapshot.json"
if [ -f "$snap_copy" ]; then
  if command -v python3 >/dev/null 2>&1; then
    printf '\nCollecting gate-evidence referenced by the snapshot:\n'
    CK_PROJECT="$PROJECT" CK_OUT="$OUT" CK_SNAP="$snap_copy" python3 - <<'PY' || printf '  [skip] could not process gate_evidence (snapshot left as-is)\n'
import json, os, pathlib, shutil

project = pathlib.Path(os.environ["CK_PROJECT"]).resolve()
out = pathlib.Path(os.environ["CK_OUT"])
snap = pathlib.Path(os.environ["CK_SNAP"])
data = json.loads(snap.read_text())
ev = data.get("gate_evidence")
if not isinstance(ev, dict):
    raise SystemExit(0)
changed = False
for gate, p in list(ev.items()):
    if not isinstance(p, str):
        continue
    src = pathlib.Path(p)
    if not src.is_file():
        print(f"  [skip] {gate}: evidence not found ({p})")
        continue
    resolved = src.resolve()
    try:
        resolved.relative_to(project)
    except ValueError:
        print(f"  [skip] {gate}: evidence outside the project ({p})")
        continue
    # the spec already lives under specs/; point there instead of duplicating it.
    if resolved.suffix == ".md" and "specs" in resolved.parts:
        ev[gate] = f"specs/{resolved.name}"
        changed = True
        print(f"  [ok]   {gate} -> specs/{resolved.name}")
        continue
    (out / "evidence").mkdir(parents=True, exist_ok=True)
    dest_name = f"{gate}{resolved.suffix or '.txt'}"
    shutil.copyfile(resolved, out / "evidence" / dest_name)
    ev[gate] = f"evidence/{dest_name}"
    changed = True
    print(f"  [ok]   {gate} -> evidence/{dest_name}")
if changed:
    snap.write_text(json.dumps(data, indent=2) + "\n")
PY
  else
    printf '\n  [skip] python3 not found — snapshot keeps absolute gate_evidence paths\n'
  fi
fi

# --- 2. The code the run produced (git) --------------------------------------------------------
printf '\nCollecting git evidence (base = %s):\n' "$BASE"
if git -C "$PROJECT" rev-parse --git-dir >/dev/null 2>&1; then
  mkdir -p "$OUT/git"
  git -C "$PROJECT" log --oneline -30 > "$OUT/git/log.txt" 2>/dev/null || true
  if git -C "$PROJECT" rev-parse --verify --quiet "$BASE" >/dev/null 2>&1; then
    mb="$(git -C "$PROJECT" merge-base "$BASE" HEAD 2>/dev/null || true)"
    if [ -n "$mb" ]; then
      git -C "$PROJECT" diff --stat "$mb"..HEAD > "$OUT/git/diff.stat.txt" 2>/dev/null || true
      git -C "$PROJECT" diff "$mb"..HEAD        > "$OUT/git/changes.diff"  2>/dev/null || true
      printf '  [ok]   diff vs %s (stat + full)\n' "$BASE"
    fi
  else
    printf '  [skip] base branch %s not found — captured git log only\n' "$BASE"
  fi
else
  printf '  [skip] not a git repository — no code diff captured\n'; missing=$((missing + 1))
fi

# --- 3. Generic secret scan (lists matching FILES only, never their contents) -------------------
printf '\nScanning the bundle for generic secret patterns:\n'
# Deliberately generic — org-specific names are YOUR job to scrub (see the checklist below).
patterns='-----BEGIN [A-Z ]*PRIVATE KEY-----|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{30,}|xox[baprs]-[A-Za-z0-9-]{10,}|(secret|token|password|passwd|api[_-]?key)[[:space:]"'\'']*[:=][[:space:]"'\'']*[^[:space:]"'\'']+|Bearer[[:space:]]+[A-Za-z0-9._-]{16,}'
# `-e` is required: $patterns starts with "-----BEGIN", which grep would otherwise read as options.
hits="$(grep -rIlE -e "$patterns" "$OUT" 2>/dev/null || true)"
if [ -n "$hits" ]; then
  printf '  [WARN] possible secrets in these files — INSPECT and scrub before publishing:\n'
  printf '%s\n' "$hits" | sed 's/^/         /'
else
  printf '  [ok]   no generic secret patterns matched (still do the manual checklist)\n'
fi

# --- 4. Manual redaction checklist -------------------------------------------------------------
cat > "$OUT/REDACTION-CHECKLIST.md" <<'EOF'
# Redaction checklist — finish before publishing this bundle

This bundle was copied verbatim from a real project. The automated scan only catches *generic*
secret shapes. Before you publish it (e.g. into `examples/` or a blog post), manually confirm:

- [ ] No company / team / internal-service / repo / registry / cluster / namespace / project-id names
- [ ] No internal hostnames, IPs, URLs, or cloud project identifiers
- [ ] No customer / personal data in the spec, diff, or verdict log
- [ ] No secret VALUES (keys, tokens, passwords, connection strings) — the scan flags shapes, not all
- [ ] `changes.diff` reviewed line-by-line (it contains your actual source)
- [ ] `continuity.md` reviewed (it may quote commands, paths, and findings verbatim)

Tip: keep a private copy, publish a scrubbed copy. Replace real identifiers with neutral
placeholders (`acme`, `example.com`, `service-a`) rather than deleting context.
EOF
printf '  [ok]   wrote REDACTION-CHECKLIST.md\n'

# --- 5. Summary --------------------------------------------------------------------------------
printf '\nDone. Bundle at:\n  %s\n' "$OUT"
if [ "$missing" != "0" ]; then
  printf '\nNote: %s expected item(s) were not found. If you have not run /sdlc in this project\n' "$missing"
  printf 'yet, or ran it in a different directory, point --project at the right checkout.\n'
fi
printf '\nNext: complete %s/REDACTION-CHECKLIST.md, then copy what you want into examples/.\n' "$OUT"
