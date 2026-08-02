#!/usr/bin/env sh
# The repository's full validation suite, run inside a container.
#
# Used for baseline validation and replayed unchanged for the final-validation runs, so the two
# are comparable by construction. Every check records its OWN exit code into a JSON report; the
# script never pipes a verification command, because a pipeline reports only its last command's
# status and would turn a failing suite into a pass.
#
#   MODE=full        every check, with line+branch coverage (the pinned-lint interpreter)
#   MODE=tests-only  the pytest suite alone (declared floor / ceiling interpreters)
#
# The repo is mounted read-only, so anything needing to write works from a copy in /tmp.
set -u

MODE="${MODE:-full}"
LABEL="${LABEL:-py}"
REPORT_DIR="${REPORT_DIR:-/out/raw/baseline/$LABEL}"
SRC=/tmp/src

mkdir -p "$REPORT_DIR"
: >"$REPORT_DIR/checks.tsv"

FAILED=0
TOTAL=0

# run <name> <command...> — execute, echo the real exit code, never mask it behind a pipe.
run() {
	name="$1"
	shift
	TOTAL=$((TOTAL + 1))
	printf '\n=== [%s] %s ===\n' "$name" "$*"
	"$@" >"$REPORT_DIR/$name.log" 2>&1
	rc=$?
	tail -n 15 "$REPORT_DIR/$name.log"
	printf '%s\t%s\n' "$name" "$rc" >>"$REPORT_DIR/checks.tsv"
	if [ "$rc" -ne 0 ]; then
		FAILED=$((FAILED + 1))
		printf '!!! %s FAILED rc=%s (full log: %s/%s.log)\n' "$name" "$rc" "$REPORT_DIR" "$name"
	fi
	return 0
}

echo "### interpreter"
python --version
echo "### working copy (repo is read-only; copy so builds and scaffolds can write)"
mkdir -p "$SRC"
cp -a /repo/. "$SRC"/
cd "$SRC" || exit 1

export COVERAGE_FILE=/tmp/.coverage
export PYTHONPATH="$SRC/src"

if [ "$MODE" = "tests-only" ]; then
	run pytest python -m pytest -q -p no:cacheprovider
	echo
	echo "### summary ($LABEL): $((TOTAL - FAILED))/$TOTAL checks passed"
	exit "$FAILED"
fi

# --- tests + coverage ---------------------------------------------------------------------------
run pytest python -m pytest -q -p no:cacheprovider
run coverage python -m pytest -q -p no:cacheprovider \
	--cov=src/claude_kit --cov-branch --cov-report=term-missing \
	--cov-report="json:$REPORT_DIR/coverage.json" \
	--cov-report="xml:$REPORT_DIR/coverage.xml" \
	--cov-fail-under=91

# --- lint / format / types / shell ----------------------------------------------------------------
run ruff_check ruff check src scripts tests skills
run ruff_format ruff format --check src scripts tests
run mypy mypy
run shellcheck sh -c 'shellcheck -S warning hooks/scripts/*.sh scripts/*.sh $(ls templates/scripts/*.sh 2>/dev/null)'

# --- repository drift and consistency guards --------------------------------------------------------
for s in gen_hooks.py check_docs_consistency.py check_skill_descriptions.py check_mcp_pins.py \
	check_rule_sizes.py check_cross_references.py; do
	[ -f "scripts/$s" ] || continue
	name="script_$(printf '%s' "$s" | tr -c 'a-zA-Z0-9' '_')"
	if [ "$s" = "gen_hooks.py" ]; then
		run "$name" python "scripts/$s" --check
	else
		run "$name" python "scripts/$s"
	fi
done

run catalog_integrity python -c \
	"import sys; from claude_kit import validator; ok, msgs = validator.check_catalog('.'); [print(m) for m in msgs]; sys.exit(0 if ok else 1)"

# --- packaging ----------------------------------------------------------------------------------
run build python -m build --no-isolation --outdir /tmp/dist
run twine twine check /tmp/dist/*

# --- install smoke tests: wheel and sdist ---------------------------------------------------------
# --no-deps because the container has no egress. The smoke venv is a venv-of-a-venv, so
# --system-site-packages resolves to the BASE interpreter and cannot see typer/jinja2/pyyaml; the
# dependency directory is put on PYTHONPATH explicitly instead. PYTHONPATH must NOT include the
# source tree here, or the checkout would shadow the very artifact under test.
DEPS="$(python -c 'import os, typer; print(os.path.dirname(os.path.dirname(typer.__file__)))')"
run wheel_install env PYTHONPATH="$DEPS" sh -c '
  python -m venv /tmp/venv-whl &&
  /tmp/venv-whl/bin/pip install --no-deps --quiet /tmp/dist/*.whl &&
  /tmp/venv-whl/bin/claude-kit --version &&
  /tmp/venv-whl/bin/python -c "import claude_kit; print(\"installed from\", claude_kit.__file__)"'
# The sdist is verified by rebuilding a wheel FROM it and installing that: `pip install <sdist>`
# would need the build backend inside the fresh venv, and the container has no egress. Rebuilding
# also proves the sdist is complete rather than merely present.
run sdist_install env PYTHONPATH="$DEPS" sh -c '
  mkdir -p /tmp/sdist-x &&
  tar -xzf /tmp/dist/*.tar.gz -C /tmp/sdist-x &&
  d=$(find /tmp/sdist-x -maxdepth 1 -mindepth 1 -type d | head -1) &&
  (cd "$d" && python -m build --no-isolation --wheel --outdir /tmp/dist-from-sdist) &&
  python -m venv /tmp/venv-sdist &&
  /tmp/venv-sdist/bin/pip install --no-deps --quiet /tmp/dist-from-sdist/*.whl &&
  /tmp/venv-sdist/bin/claude-kit --version &&
  /tmp/venv-sdist/bin/python -c "import claude_kit; print(\"installed from\", claude_kit.__file__)"'

# --- end-to-end CLI lifecycle ----------------------------------------------------------------------
run scaffold_default sh -c 'mkdir -p /tmp/proj && python -m claude_kit.cli init /tmp/proj --defaults'
run cli_validate sh -c 'python -m claude_kit.cli validate /tmp/proj'
run cli_doctor sh -c 'python -m claude_kit.cli doctor /tmp/proj'
run cli_diff sh -c 'python -m claude_kit.cli diff /tmp/proj'
run cli_status sh -c 'python -m claude_kit.cli status /tmp/proj'
run cli_list_options sh -c 'python -m claude_kit.cli list-options'
run cli_privacy_report sh -c 'python -m claude_kit.cli privacy-report /tmp/proj'
run cli_export_cursor sh -c 'python -m claude_kit.cli export /tmp/proj --target cursor'
run cli_export_agents sh -c 'python -m claude_kit.cli export /tmp/proj --target agents'
run cli_export_copilot sh -c 'python -m claude_kit.cli export /tmp/proj --target copilot'

# Upgrade must converge and must preserve a user edit.
run upgrade_first sh -c 'python -m claude_kit.cli upgrade /tmp/proj'
run upgrade_converges sh -c 'python -m claude_kit.cli upgrade /tmp/proj && python -m claude_kit.cli validate /tmp/proj'
run user_edit_preserved sh -c '
  printf "\n<!-- user edit sentinel -->\n" >> /tmp/proj/CLAUDE.md &&
  python -m claude_kit.cli upgrade /tmp/proj >/dev/null &&
  grep -q "user edit sentinel" /tmp/proj/CLAUDE.md'

# --- shipped invariants -------------------------------------------------------------------------
# The shipped invariant is "no Docker ARTIFACTS", matching tests/test_scaffold.py::test_no_docker_anywhere:
# no Dockerfile, no docker-compose file, no .dockerignore. Prose may legitimately mention Docker —
# the pentest skills describe running third-party tools in containers and the devops agent is
# container-optional — so a text search would flag correct content as a violation.
run no_docker_in_generated_project sh -c '
  hits=$(find /tmp/proj -type f \( -name Dockerfile -o -name "Dockerfile.*" -o -name "docker-compose*.yml" \
         -o -name "docker-compose*.yaml" -o -name ".dockerignore" \) 2>/dev/null)
  if [ -n "$hits" ]; then echo "Docker artifacts found in the generated project:"; echo "$hits"; exit 1; fi
  echo "no Docker artifacts in the generated project (prose mentions are permitted by design)"'
run manifests_valid python -c "
import json,sys
for p in ('.claude-plugin/plugin.json', '.claude-plugin/marketplace.json'):
    d = json.load(open(p))
    print(p, 'ok', sorted(d)[:6])
"

echo
echo "### summary ($LABEL): $((TOTAL - FAILED))/$TOTAL checks passed, $FAILED failed"
exit "$FAILED"
