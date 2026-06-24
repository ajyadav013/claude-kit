#!/usr/bin/env bash
#
# Reproduce the real gate checks for the sample app. These are the exact commands whose
# captured output backs the gate verdicts in ../scenarios/. Run from anywhere.
#
# Requires: python3 with pytest + ruff available (e.g. the kit's .venv, or `pip install
# pytest ruff`). The sample itself has ZERO third-party dependencies.

set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"

echo "== ruff (lint gate) =="
ruff check "$HERE/tasktracker" "$HERE/tests"

echo "== pytest (build-green + test-coverage gate) =="
python3 -m pytest "$HERE/tests" -v
