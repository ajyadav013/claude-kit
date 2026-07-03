#!/usr/bin/env bash
#
# backfill-releases.sh — retroactively create the git tag + GitHub Release for every past claude-kit
# version that predates the automated release job.
#
# As of 0.57.0, publish.yml's `github-release` job creates `vX.Y.Z` + a GitHub Release on every
# publish. Versions released *before* that automation shipped to PyPI via merge-to-main and never got a
# tag or Release, so the tag/Release ledger is missing history. This one-off backfill reads every
# `## [x.y.z]` section from CHANGELOG.md (the source of truth for what has shipped) and, for any version
# that has no GitHub Release yet, creates the tag + Release using that section as the notes.
#
# It is idempotent: versions that already have a Release are skipped, so it is safe to re-run.
#
# Tag placement: each tag is anchored to the commit that introduced `version = "x.y.z"` into
# pyproject.toml (found via git's pickaxe), i.e. that version's release commit. If that commit cannot be
# located the version is skipped with a warning (never silently tagged at the wrong commit).
#
# Requires: `git`, `gh` (authenticated: `gh auth status`), and `awk`. Run from the repo root.
#
# Usage:
#   scripts/backfill-releases.sh --dry-run     # preview every action; create nothing (recommended first)
#   scripts/backfill-releases.sh               # create the missing tags + Releases
#   scripts/backfill-releases.sh --help
#
set -euo pipefail

DRY_RUN=0
CHANGELOG="CHANGELOG.md"

usage() {
  sed -n '2,32p' "$0" | sed 's/^# \{0,1\}//'
}

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --changelog) CHANGELOG="${2:?--changelog needs a path}"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "backfill-releases.sh: unknown argument: $1" >&2; echo "Try --help." >&2; exit 2 ;;
  esac
  shift
done

# --- Preconditions -------------------------------------------------------------------------------
for tool in git gh awk; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "backfill-releases.sh: required tool not found: $tool" >&2
    exit 1
  fi
done
if [ ! -f "$CHANGELOG" ]; then
  echo "backfill-releases.sh: $CHANGELOG not found — run from the repo root." >&2
  exit 1
fi
if ! gh auth status >/dev/null 2>&1; then
  echo "backfill-releases.sh: gh is not authenticated — run 'gh auth login' first." >&2
  exit 1
fi

if [ "$DRY_RUN" -eq 1 ]; then
  echo "== DRY RUN — no tags or Releases will be created =="
fi

# --- Backfill ------------------------------------------------------------------------------------
# Every version heading in the CHANGELOG, e.g. "## [0.56.0] — 2026-07-01" -> "0.56.0".
versions="$(grep -Eo '^## \[[0-9]+\.[0-9]+\.[0-9]+\]' "$CHANGELOG" | grep -Eo '[0-9]+\.[0-9]+\.[0-9]+')"

created=0
skipped=0
missing_commit=0

for ver in $versions; do
  tag="v$ver"

  if gh release view "$tag" >/dev/null 2>&1; then
    echo "skip   $tag — Release already exists"
    skipped=$((skipped + 1))
    continue
  fi

  # The commit that first introduced this version line into pyproject.toml = the release commit.
  # Pickaxe lists newest-first; the oldest match (tail -1) is the introducing commit.
  commit="$(git log --format='%H' -S "version = \"$ver\"" -- pyproject.toml | tail -1)"
  if [ -z "$commit" ]; then
    echo "WARN   $tag — could not locate a release commit in pyproject.toml history; skipping"
    missing_commit=$((missing_commit + 1))
    continue
  fi

  # This version's CHANGELOG body: lines between its heading and the next "## [" heading.
  notes="$(awk -v ver="$ver" '
    index($0, "## [" ver "]") == 1 { capture = 1; next }
    capture && index($0, "## [") == 1 { exit }
    capture { print }
  ' "$CHANGELOG")"
  if [ -z "$(printf '%s' "$notes" | tr -d '[:space:]')" ]; then
    notes="Release $tag. See CHANGELOG.md for details."
  fi

  if [ "$DRY_RUN" -eq 1 ]; then
    echo "would   create $tag at ${commit:0:12} with $(printf '%s\n' "$notes" | grep -c '') line(s) of notes"
    created=$((created + 1))
    continue
  fi

  tmp_notes="$(mktemp)"
  printf '%s\n' "$notes" > "$tmp_notes"
  gh release create "$tag" --target "$commit" --title "$tag" --notes-file "$tmp_notes"
  rm -f "$tmp_notes"
  echo "create $tag at ${commit:0:12}"
  created=$((created + 1))
done

echo
if [ "$DRY_RUN" -eq 1 ]; then
  echo "== dry run complete: would create $created, already present $skipped, unlocatable $missing_commit =="
else
  echo "== done: created $created, skipped $skipped, unlocatable $missing_commit =="
fi
