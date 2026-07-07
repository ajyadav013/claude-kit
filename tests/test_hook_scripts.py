"""Behavioral tests for the hook scripts (R4): run each script for real.

These execute the payload's ``hooks/scripts/*.sh`` against real stdin JSON, temp
project dirs, and (where relevant) real git repos — pinning what each script
*decides*, not just that its text contains the right patterns. The guard-family
scripts (push-main, destructive-git, kubectl-delete, secrets) are covered in
test_plugin.py; capture-learnings in test_capture_guard.py. This file covers the
rest: the SessionStart context loaders, the audit log, the warn-* advisories,
the validate-* checks, and the Stop-hook degrade/scoping paths.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS = REPO_ROOT / "hooks" / "scripts"

_NEED_JQ = pytest.mark.skipif(shutil.which("jq") is None, reason="jq not installed")
_NEED_GIT = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _run(
    script: str,
    payload: dict | None = None,
    project_dir: Path | str | None = None,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a hook script with hook-JSON on stdin; return the completed process."""
    import os

    env = dict(os.environ)
    env.pop("CLAUDE_PLUGIN_ROOT", None)  # tests exercise the project-dir paths
    if project_dir is not None:
        env["CLAUDE_PROJECT_DIR"] = str(project_dir)
    else:
        env.pop("CLAUDE_PROJECT_DIR", None)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", str(_SCRIPTS / script)],
        input=json.dumps(payload) if payload is not None else "",
        capture_output=True,
        text=True,
        env=env,
    )


# --- SessionStart loaders -----------------------------------------------------------------


def test_load_continuity_emits_small_file_verbatim(tmp_path: Path) -> None:
    live = tmp_path / ".claude" / "CONTINUITY.md"
    live.parent.mkdir(parents=True)
    live.write_text("# CONTINUITY\n\nCurrent task: X\n", encoding="utf-8")
    proc = _run("load-continuity.sh", project_dir=tmp_path)
    assert proc.returncode == 0
    assert "Working memory" in proc.stdout
    assert "Current task: X" in proc.stdout
    assert "Resume from" in proc.stdout
    assert "trimmed" not in proc.stdout  # small file: emitted unchanged


def test_load_continuity_caps_large_file_keeping_both_ends(tmp_path: Path) -> None:
    live = tmp_path / ".claude" / "CONTINUITY.md"
    live.parent.mkdir(parents=True)
    body = "TOP-MARKER\n" + ("middle filler line\n" * 800) + "BOTTOM-MARKER\n"
    assert len(body) > 8000
    live.write_text(body, encoding="utf-8")
    proc = _run("load-continuity.sh", project_dir=tmp_path)
    assert proc.returncode == 0
    assert "TOP-MARKER" in proc.stdout  # head kept
    assert "BOTTOM-MARKER" in proc.stdout  # tail kept
    assert "trimmed to save context" in proc.stdout


def test_load_continuity_seeds_live_from_template(tmp_path: Path) -> None:
    tpl = tmp_path / ".claude" / "CONTINUITY.template.md"
    tpl.parent.mkdir(parents=True)
    tpl.write_text("# CONTINUITY\nSEEDED-FROM-TEMPLATE\n", encoding="utf-8")
    proc = _run("load-continuity.sh", project_dir=tmp_path)
    assert proc.returncode == 0
    assert "SEEDED-FROM-TEMPLATE" in proc.stdout
    assert (tmp_path / ".claude" / "CONTINUITY.md").is_file()  # live file created
    assert (tmp_path / ".claude" / "state").is_dir()  # runtime state dir ensured


def test_load_continuity_silent_without_any_file(tmp_path: Path) -> None:
    proc = _run("load-continuity.sh", project_dir=tmp_path)
    assert proc.returncode == 0
    assert proc.stdout == ""


def test_load_learnings_emits_index_with_entries(tmp_path: Path) -> None:
    mem = tmp_path / ".claude" / "agent-memory"
    mem.mkdir(parents=True)
    (mem / "MEMORY.md").write_text(
        "# Index\n\n- [Lesson one](patterns/one.md) — hook\n", encoding="utf-8"
    )
    proc = _run("load-learnings.sh", project_dir=tmp_path)
    assert proc.returncode == 0
    assert "Accumulated learnings" in proc.stdout
    assert "Lesson one" in proc.stdout
    # A session counter is kept for the periodic consolidation nudge.
    assert (mem / ".session-count").read_text().strip() == "1"


def test_load_learnings_silent_with_empty_index(tmp_path: Path) -> None:
    mem = tmp_path / ".claude" / "agent-memory"
    mem.mkdir(parents=True)
    (mem / "MEMORY.md").write_text("# Index\n\n(no entries yet)\n", encoding="utf-8")
    proc = _run("load-learnings.sh", project_dir=tmp_path)
    assert proc.returncode == 0
    assert proc.stdout == ""


def test_load_learnings_nudges_consolidation_every_tenth_session(
    tmp_path: Path,
) -> None:
    mem = tmp_path / ".claude" / "agent-memory"
    mem.mkdir(parents=True)
    entries = "".join(f"- [L{i}](p/{i}.md) — x\n" for i in range(4))
    (mem / "MEMORY.md").write_text("# Index\n\n" + entries, encoding="utf-8")
    (mem / ".session-count").write_text("9", encoding="utf-8")
    proc = _run("load-learnings.sh", project_dir=tmp_path)
    assert proc.returncode == 0
    assert "MAINTENANCE" in proc.stdout
    assert "consolidate-learnings" in proc.stdout


@_NEED_JQ
def test_load_autonomy_surfaces_recorded_level(tmp_path: Path) -> None:
    cfg = tmp_path / ".claude" / "config"
    cfg.mkdir(parents=True)
    (cfg / "init-options.json").write_text(
        json.dumps({"selection": {"autonomy": "autonomous-pr"}}), encoding="utf-8"
    )
    proc = _run("load-autonomy.sh", project_dir=tmp_path)
    assert proc.returncode == 0
    assert "Active autonomy level: autonomous-pr" in proc.stdout


@_NEED_JQ
def test_load_autonomy_silent_without_config_or_level(tmp_path: Path) -> None:
    assert _run("load-autonomy.sh", project_dir=tmp_path).stdout == ""
    cfg = tmp_path / ".claude" / "config"
    cfg.mkdir(parents=True)
    (cfg / "init-options.json").write_text(
        json.dumps({"selection": {}}), encoding="utf-8"
    )
    proc = _run("load-autonomy.sh", project_dir=tmp_path)
    assert proc.returncode == 0
    assert proc.stdout == ""


# --- audit-log ------------------------------------------------------------------------------


@_NEED_JQ
def test_audit_log_appends_tool_and_target(tmp_path: Path) -> None:
    payload = {"tool_name": "Edit", "tool_input": {"file_path": "/x/y.py"}}
    proc = _run("audit-log.sh", payload=payload, project_dir=tmp_path)
    assert proc.returncode == 0
    log = tmp_path / ".claude" / "state" / "audit.log"
    line = log.read_text(encoding="utf-8").strip()
    assert "\tEdit\t/x/y.py" in line


@_NEED_JQ
def test_audit_log_truncates_target_and_never_logs_bodies(tmp_path: Path) -> None:
    long_cmd = "echo " + "x" * 300
    payload = {"tool_name": "Bash", "tool_input": {"command": long_cmd}}
    _run("audit-log.sh", payload=payload, project_dir=tmp_path)
    line = (tmp_path / ".claude" / "state" / "audit.log").read_text().strip()
    target = line.split("\t")[2]
    assert len(target) <= 120  # record stays short


@_NEED_JQ
def test_audit_log_survives_garbage_stdin(tmp_path: Path) -> None:
    import os

    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path)
    proc = subprocess.run(
        ["bash", str(_SCRIPTS / "audit-log.sh")],
        input="not json at all",
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 0  # must never affect the tool


# --- warn-* advisories (always exit 0; warn on stderr) ---------------------------------------


@_NEED_JQ
@pytest.mark.parametrize(
    ("file_path", "expected"),
    [
        ("src/auth/login.py", "AUTH"),
        ("api/billing/checkout.ts", "PAYMENTS"),
        ("db/migrations/0002_add.sql", "DATABASE MIGRATION"),
        ("infra/.github/workflows/deploy.yml", "INFRASTRUCTURE"),
    ],
)
def test_warn_sensitive_files_flags_risky_surfaces(
    file_path: str, expected: str
) -> None:
    proc = _run(
        "warn-sensitive-files.sh", payload={"tool_input": {"file_path": file_path}}
    )
    assert proc.returncode == 0  # advisory: never blocks
    assert expected in proc.stderr


@_NEED_JQ
def test_warn_sensitive_files_silent_on_plain_paths() -> None:
    proc = _run(
        "warn-sensitive-files.sh",
        payload={"tool_input": {"file_path": "src/utils/format.py"}},
    )
    assert proc.returncode == 0
    assert proc.stderr == ""


@_NEED_JQ
def test_warn_large_edits_thresholds() -> None:
    big = {"tool_input": {"file_path": "a.py", "content": "line\n" * 200}}
    small = {"tool_input": {"file_path": "a.py", "content": "line\n" * 10}}
    assert "large edit" in _run("warn-large-edits.sh", payload=big).stderr
    assert _run("warn-large-edits.sh", payload=small).stderr == ""
    # Threshold overridable via env.
    proc = _run(
        "warn-large-edits.sh", payload=small, extra_env={"CLAUDE_LARGE_EDIT_LINES": "5"}
    )
    assert "large edit" in proc.stderr
    assert proc.returncode == 0


@_NEED_JQ
@pytest.mark.parametrize(
    ("file_path", "warns"),
    [
        ("src/service/handler.py", True),
        ("tests/test_handler.py", False),  # test file
        ("docs/guide.md", False),  # docs
        ("proj/.claude/rules/testing.md", False),  # kit config
    ],
)
def test_warn_missing_tests_nudges_only_production_source(
    file_path: str, warns: bool
) -> None:
    proc = _run(
        "warn-missing-tests.sh", payload={"tool_input": {"file_path": file_path}}
    )
    assert proc.returncode == 0
    assert ("REMINDER" in proc.stderr) is warns


@_NEED_JQ
def test_warn_llm_io_flags_llm_signatures_only() -> None:
    llm = {"tool_input": {"file_path": "svc/ai.py", "content": "import anthropic\n"}}
    plain = {"tool_input": {"file_path": "svc/math.py", "content": "x = 1 + 1\n"}}
    proc = _run("warn-llm-io.sh", payload=llm)
    assert proc.returncode == 0
    assert "LLM/AI feature" in proc.stderr
    assert _run("warn-llm-io.sh", payload=plain).stderr == ""


@_NEED_JQ
@pytest.mark.parametrize(
    ("file_path", "warns"),
    [
        ("proj/package.json", True),  # project-wide config by basename
        ("proj/.github/workflows/ci.yml", True),  # shared automation by path
        ("proj/src/feature/thing.py", False),
    ],
)
def test_warn_shared_modules_flags_cross_cutting_surfaces(
    file_path: str, warns: bool
) -> None:
    proc = _run(
        "warn-shared-modules.sh", payload={"tool_input": {"file_path": file_path}}
    )
    assert proc.returncode == 0
    assert ("WARN" in proc.stderr) is warns


# --- validate-* -----------------------------------------------------------------------------


@_NEED_JQ
def test_validate_frontmatter_warns_on_missing_fields() -> None:
    ok_agent = "---\nname: dev\ndescription: does dev\n---\nbody\n"
    no_name = "---\ndescription: does dev\n---\nbody\n"
    no_fm = "just markdown\n"
    path = "proj/.claude/agents/dev.md"

    def run(body: str) -> str:
        return _run(
            "validate-frontmatter.sh",
            payload={"tool_input": {"file_path": path, "content": body}},
        ).stderr

    assert run(ok_agent) == ""
    assert "missing 'name:'" in run(no_name)
    assert "no YAML frontmatter" in run(no_fm)
    # Skills need description but not name.
    skill = _run(
        "validate-frontmatter.sh",
        payload={
            "tool_input": {
                "file_path": "proj/.claude/skills/x/SKILL.md",
                "content": "---\nname: x\n---\nbody\n",
            }
        },
    )
    assert "missing 'description:'" in skill.stderr
    assert skill.returncode == 0  # advisory: warns, never blocks


@_NEED_JQ
def test_validate_settings_blocks_only_invalid_settings_json() -> None:
    bad = _run(
        "validate-settings.sh",
        payload={
            "tool_input": {"file_path": "p/.claude/settings.json", "content": "{oops"}
        },
    )
    assert bad.returncode == 2
    assert "BLOCKED" in bad.stderr
    good = _run(
        "validate-settings.sh",
        payload={
            "tool_input": {"file_path": "p/.claude/settings.json", "content": "{}"}
        },
    )
    assert good.returncode == 0
    other = _run(
        "validate-settings.sh",
        payload={"tool_input": {"file_path": "p/notes.json", "content": "{oops"}},
    )
    assert other.returncode == 0  # only settings writes are gated


# --- Stop hooks: degrade + scoping ------------------------------------------------------------


def test_type_check_noop_without_any_tooling(tmp_path: Path) -> None:
    proc = _run("type-check.sh", project_dir=tmp_path)
    assert proc.returncode == 0
    assert proc.stdout == ""


def test_lint_fix_noop_without_any_tooling(tmp_path: Path) -> None:
    proc = _run("lint-fix.sh", project_dir=tmp_path)
    assert proc.returncode == 0
    assert proc.stdout == ""


@_NEED_GIT
@pytest.mark.skipif(shutil.which("ruff") is None, reason="ruff not installed")
def test_lint_fix_scoped_formats_only_changed_files(tmp_path: Path) -> None:
    """P0-3: a Stop-hook autofix must never rewrite files the session never touched."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    git = ["git", "-C", str(repo)]
    ugly = "x=1\n"  # ruff format would rewrite this to `x = 1`
    (repo / "untouched.py").write_text(ugly, encoding="utf-8")
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run(
        [
            *git,
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "-q",
            "-m",
            "base",
        ],
        check=True,
    )
    (repo / "changed.py").write_text("y =2\n", encoding="utf-8")  # new (untracked) file

    proc = _run("lint-fix.sh", project_dir=repo)
    assert proc.returncode == 0
    assert (repo / "changed.py").read_text() == "y = 2\n"  # changed file formatted
    assert (repo / "untouched.py").read_text() == ugly  # committed file untouched


# --- Stop hooks: additionalContext feedback (Claude Code >= 2.1.163) --------------------------
#
# The checker/linter is faked with an `npm` shim on PATH so the tests are hermetic: no real
# toolchain is needed and the failure output is deterministic.


def _npm_shim(tmp_path: Path, stdout: str, exit_code: int) -> str:
    """Create a fake `npm` executable that prints ``stdout`` and exits ``exit_code``."""
    shim_dir = tmp_path / "shim-bin"
    shim_dir.mkdir(exist_ok=True)
    npm = shim_dir / "npm"
    npm.write_text(f"#!/bin/sh\necho '{stdout}'\nexit {exit_code}\n", encoding="utf-8")
    npm.chmod(0o755)
    return str(shim_dir)


@_NEED_JQ
def test_type_check_failure_emits_stop_feedback_json(tmp_path: Path) -> None:
    """A failing type check returns hookSpecificOutput.additionalContext (not bare stdout,
    which Claude Code writes to the debug log only)."""
    import os

    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "package.json").write_text(
        json.dumps({"scripts": {"typecheck": "tsc"}}), encoding="utf-8"
    )
    shim = _npm_shim(tmp_path, "src/app.ts(3,1): error TS2304: Cannot find name", 1)
    proc = _run(
        "type-check.sh",
        payload={"stop_hook_active": False},
        project_dir=proj,
        extra_env={"PATH": f"{shim}:{os.environ['PATH']}"},
    )
    assert proc.returncode == 0  # feedback, never a hard block
    obj = json.loads(proc.stdout)  # stdout is ONLY the JSON object
    assert obj["hookSpecificOutput"]["hookEventName"] == "Stop"
    ctx = obj["hookSpecificOutput"]["additionalContext"]
    assert "error TS2304" in ctx and "fix before finishing" in ctx


@_NEED_JQ
def test_type_check_gives_one_nudge_per_stop_chain(tmp_path: Path) -> None:
    """stop_hook_active=true means we're already continuing from a stop hook: stay silent
    so an unfixable failure can't ping-pong the session (per the hooks reference)."""
    import os

    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "package.json").write_text(
        json.dumps({"scripts": {"typecheck": "tsc"}}), encoding="utf-8"
    )
    shim = _npm_shim(tmp_path, "src/app.ts(3,1): error TS2304: Cannot find name", 1)
    proc = _run(
        "type-check.sh",
        payload={"stop_hook_active": True},
        project_dir=proj,
        extra_env={"PATH": f"{shim}:{os.environ['PATH']}"},
    )
    assert proc.returncode == 0
    assert proc.stdout == ""


@_NEED_JQ
def test_lint_fix_failure_emits_stop_feedback_json(tmp_path: Path) -> None:
    import os

    proj = tmp_path / "proj"  # not a git repo -> whole-repo (unscoped) mode
    proj.mkdir()
    (proj / "package.json").write_text(
        json.dumps({"scripts": {"lint": "eslint ."}}), encoding="utf-8"
    )
    shim = _npm_shim(tmp_path, "src/app.js:1:1 problem: x is defined but never used", 0)
    env = {"PATH": f"{shim}:{os.environ['PATH']}"}

    proc = _run(
        "lint-fix.sh",
        payload={"stop_hook_active": False},
        project_dir=proj,
        extra_env=env,
    )
    assert proc.returncode == 0
    obj = json.loads(proc.stdout)
    assert obj["hookSpecificOutput"]["hookEventName"] == "Stop"
    assert "never used" in obj["hookSpecificOutput"]["additionalContext"]

    # One nudge per stop chain here too.
    quiet = _run(
        "lint-fix.sh",
        payload={"stop_hook_active": True},
        project_dir=proj,
        extra_env=env,
    )
    assert quiet.returncode == 0
    assert quiet.stdout == ""
