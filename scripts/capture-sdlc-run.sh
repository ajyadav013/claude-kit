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
# Pull every v1/v2 evidence reference into the bundle and rewrite the copied snapshot to use
# bundle-relative paths. This includes findings evidence, passed-gate evidence, conditional
# not-applicable evidence, accepted-risk evidence, final-summary copies, and terminal archives.
# Project-relative paths are resolved against --project (never the caller's CWD). A declared
# artifact that is missing or outside the project makes capture fail: continuing would publish a
# bundle that falsely claims to be self-contained or leaks a local absolute path.
snap_copy="$OUT/state/pipeline-snapshot.json"
if [ -f "$snap_copy" ]; then
  if command -v python3 >/dev/null 2>&1; then
    printf '\nCollecting evidence referenced by the snapshot:\n'
    if ! CK_PROJECT="$PROJECT" CK_OUT="$OUT" CK_SNAP="$snap_copy" python3 - <<'PY'
import hashlib
import json
import os
import pathlib
import re
import shutil

project = pathlib.Path(os.environ["CK_PROJECT"]).resolve()
out = pathlib.Path(os.environ["CK_OUT"])
snap = pathlib.Path(os.environ["CK_SNAP"])
data = json.loads(snap.read_text(encoding="utf-8"))
if not isinstance(data, dict):
    raise ValueError("pipeline snapshot root must be an object")

refs = []


def add(container, key, label):
    value = container.get(key)
    if value is not None:
        if not isinstance(value, str) or not value:
            raise ValueError(f"{label} must be a non-empty path string")
        refs.append((container, key, label, value))


def collect(document, prefix="run"):
    legacy = document.get("gate_evidence")
    if legacy is not None:
        if not isinstance(legacy, dict):
            raise ValueError(f"{prefix}.gate_evidence must be an object")
        for gate in sorted(legacy):
            add(legacy, gate, f"{prefix}-legacy-{gate}")

    findings = document.get("findings_evidence")
    if findings is not None:
        if not isinstance(findings, dict):
            raise ValueError(f"{prefix}.findings_evidence must be an object or null")
        add(findings, "evidence_path", f"{prefix}-findings")

    history = document.get("gate_history", [])
    if not isinstance(history, list):
        raise ValueError(f"{prefix}.gate_history must be an array")
    for index, entry in enumerate(history):
        if not isinstance(entry, dict):
            raise ValueError(f"{prefix}.gate_history[{index}] must be an object")
        gate = entry.get("gate", f"gate-{index}")
        add(entry, "evidence_path", f"{prefix}-{gate}-gate")
        add(entry, "condition_evidence_path", f"{prefix}-{gate}-condition")

    risks = document.get("accepted_risks", [])
    if not isinstance(risks, list):
        raise ValueError(f"{prefix}.accepted_risks must be an array")
    for index, risk in enumerate(risks):
        if not isinstance(risk, dict):
            raise ValueError(f"{prefix}.accepted_risks[{index}] must be an object")
        label = risk.get("risk_id") or risk.get("finding_id") or f"risk-{index}"
        add(risk, "evidence_path", f"{prefix}-{label}-risk")

    summary = document.get("final_summary")
    if summary is not None:
        if not isinstance(summary, dict):
            raise ValueError(f"{prefix}.final_summary must be an object or null")
        summary_risks = summary.get("accepted_risks", [])
        if not isinstance(summary_risks, list):
            raise ValueError(f"{prefix}.final_summary.accepted_risks must be an array")
        for index, risk in enumerate(summary_risks):
            if not isinstance(risk, dict):
                raise ValueError(
                    f"{prefix}.final_summary.accepted_risks[{index}] must be an object"
                )
            label = risk.get("risk_id") or risk.get("finding_id") or f"risk-{index}"
            add(risk, "evidence_path", f"{prefix}-summary-{label}-risk")

    archives = document.get("run_archives", [])
    if not isinstance(archives, list):
        raise ValueError(f"{prefix}.run_archives must be an array")
    for index, archive in enumerate(archives):
        if not isinstance(archive, dict) or not isinstance(archive.get("snapshot"), dict):
            raise ValueError(f"{prefix}.run_archives[{index}] has no snapshot object")
        collect(archive["snapshot"], f"{prefix}-archive-{index}")


collect(data)
changed = False
copied = {}
failures = []
for container, key, label, recorded in refs:
    source = pathlib.Path(recorded).expanduser()
    if not source.is_absolute():
        source = project / source
    try:
        resolved = source.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        failures.append(f"{label}: evidence unavailable ({recorded!r}: {exc})")
        continue
    try:
        resolved.relative_to(project)
    except ValueError:
        failures.append(f"{label}: evidence outside the project ({recorded!r})")
        continue
    if not resolved.is_file():
        failures.append(f"{label}: evidence is not a regular file ({recorded!r})")
        continue
    relative = copied.get(resolved)
    if relative is None:
        safe_label = re.sub(r"[^A-Za-z0-9._-]+", "-", str(label)).strip("-._") or "evidence"
        suffix = resolved.suffix if re.fullmatch(r"\.[A-Za-z0-9]{1,10}", resolved.suffix) else ".bin"
        token = hashlib.sha256(str(resolved.relative_to(project)).encode()).hexdigest()[:10]
        dest_name = f"{safe_label[:80]}-{token}{suffix}"
        relative = f"evidence/{dest_name}"
        (out / "evidence").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(resolved, out / relative)
        copied[resolved] = relative
    container[key] = relative
    changed = True
    print(f"  [ok]   {label} -> {relative}")
if failures:
    for failure in failures:
        print(f"  [FAIL] {failure}")
    raise SystemExit("snapshot evidence is not project-contained and complete")
if changed:
    snap.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
PY
    then
      die "could not create a self-contained evidence bundle"
    fi
  else
    die "python3 is required to parse and safely collect snapshot evidence"
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
