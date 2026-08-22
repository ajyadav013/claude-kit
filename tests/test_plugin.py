"""Validate the Claude Code *plugin* payload (manifest + hooks file).

These guard the plugin-distribution channel (as opposed to the pip CLI, which builds
``.claude/settings.json`` from ``claude_kit.hooks.HOOK_REGISTRY``). Claude Code **auto-discovers** a
plugin's ``hooks/hooks.json`` from the plugin root, and that file must be shaped like a settings
fragment: a top-level ``hooks`` record mapping event names to matcher groups. A flat ``{event: [...]}``
file is rejected (``invalid_type … path: ["hooks"] … expected record, received undefined``).

The manifest's ``hooks`` field is reserved for *additional* hook files. Pointing it back at the
auto-discovered ``./hooks/hooks.json`` makes the loader read the same file twice and fail with
``Hook load failed: Duplicate hooks file detected``, so this module also guards against that.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from claude_kit.validator import KNOWN_EVENTS

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_MANIFEST = REPO_ROOT / ".claude-plugin" / "plugin.json"
HOOKS_FILE = REPO_ROOT / "hooks" / "hooks.json"
CODEX_PLUGIN_ROOT = REPO_ROOT / "providers" / "codex" / "claude-kit"
CODEX_HOOKS_FILE = CODEX_PLUGIN_ROOT / "hooks" / "hooks.json"
CODEX_HOOK_SCRIPTS = CODEX_PLUGIN_ROOT / "hooks" / "scripts"

pytestmark = pytest.mark.skipif(
    not PLUGIN_MANIFEST.exists(),
    reason="plugin manifest only present in a source checkout, not the wheel",
)


def test_plugin_hooks_file_is_wrapped() -> None:
    """The auto-discovered hooks file must wrap events under a top-level ``hooks`` record."""
    data = json.loads(HOOKS_FILE.read_text())
    assert isinstance(data, dict) and "hooks" in data, (
        "plugin hooks file must be {'hooks': {<event>: [...]}}; a flat event map is rejected "
        "by the plugin loader (expected record at path 'hooks', received undefined)"
    )
    assert isinstance(data["hooks"], dict) and data["hooks"], (
        "`hooks` must be a non-empty record"
    )


def test_plugin_hooks_event_structure() -> None:
    """Every event maps to matcher groups, each with a non-empty ``hooks`` list of typed entries."""
    events = json.loads(HOOKS_FILE.read_text())["hooks"]
    for event, groups in events.items():
        assert event in KNOWN_EVENTS, f"unknown hook event: {event}"
        assert isinstance(groups, list) and groups, f"{event} must be a non-empty list"
        for group in groups:
            entries = group.get("hooks")
            assert isinstance(entries, list) and entries, (
                f"{event} group needs a 'hooks' list"
            )
            for entry in entries:
                assert entry.get("type") in {"command", "prompt"}, (
                    f"{event}: bad hook type"
                )


def test_compatibility_catalog_recognizes_current_official_events() -> None:
    assert {
        "PostToolUseFailure",
        "PermissionRequest",
        "SubagentStart",
        "Setup",
        "TeammateIdle",
        "TaskCreated",
        "TaskCompleted",
        "ConfigChange",
        "WorktreeCreate",
        "WorktreeRemove",
        "Elicitation",
        "ElicitationResult",
    } <= KNOWN_EVENTS


def test_manifest_does_not_redeclare_standard_hooks() -> None:
    """``plugin.json`` must not point ``hooks`` at the auto-discovered ``./hooks/hooks.json``.

    Claude Code already loads ``hooks/hooks.json`` automatically; referencing it again in the manifest
    makes the loader read the same file twice and fail with "Duplicate hooks file detected". The
    manifest ``hooks`` field is reserved for *additional* hook files.
    """
    manifest = json.loads(PLUGIN_MANIFEST.read_text())
    ref = manifest.get("hooks")
    if ref is None:
        return  # relies purely on auto-discovery (the norm for claude-kit)
    # A string (or list of strings) is a path reference; an inline object declares hooks directly
    # (no path to collide). None of the referenced paths may resolve to the standard file.
    if isinstance(ref, str):
        paths = [ref]
    elif isinstance(ref, list):
        paths = [p for p in ref if isinstance(p, str)]
    else:
        paths = []
    for p in paths:
        assert (REPO_ROOT / p).resolve() != HOOKS_FILE.resolve(), (
            "plugin.json must not reference the auto-discovered ./hooks/hooks.json; it is loaded "
            "automatically, so re-declaring it triggers 'Duplicate hooks file detected'"
        )


def _load_gen_hooks():
    """Load scripts/gen_hooks.py (not a package) so tests share its exact JSON rendering."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "gen_hooks", REPO_ROOT / "scripts" / "gen_hooks.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_static_hook_files_match_registry() -> None:
    """hooks/hooks.json and templates/settings.json must equal the registry-driven generator output.

    This is the drift guard for the single-source-of-truth model: edit hooks.py, run
    `python scripts/gen_hooks.py`, commit. A hand-edit to either JSON file fails here.
    """
    from claude_kit import hooks

    gen = _load_gen_hooks()
    assert gen._render(hooks.generate_plugin_hooks_json()) == HOOKS_FILE.read_text(
        encoding="utf-8"
    ), "hooks/hooks.json drifted from the registry — run `python scripts/gen_hooks.py`"
    starter = REPO_ROOT / "templates" / "settings.json"
    assert gen._render(hooks.generate_starter_settings()) == starter.read_text(
        encoding="utf-8"
    ), (
        "templates/settings.json drifted from the registry — run `python scripts/gen_hooks.py`"
    )
    assert gen._render(hooks.generate_codex_plugin_hooks_json()) == (
        CODEX_HOOKS_FILE.read_text(encoding="utf-8")
    ), "native Codex plugin hooks drifted — run `python scripts/gen_hooks.py`"

    expected_scripts = set(hooks.plugin_script_names())
    assert {path.name for path in CODEX_HOOK_SCRIPTS.glob("*.sh")} == expected_scripts
    for name in expected_scripts:
        assert (CODEX_HOOK_SCRIPTS / name).read_text(encoding="utf-8") == (
            gen.render_codex_plugin_script(name)
        )


def test_codex_plugin_hooks_are_native_self_contained_and_leak_free() -> None:
    """The nested plugin must not depend on Claude paths or a pip-installed ckit adapter."""
    from claude_kit import hooks

    document = json.loads(CODEX_HOOKS_FILE.read_text(encoding="utf-8"))
    entries = [
        entry
        for groups in document["hooks"].values()
        for group in groups
        for entry in group["hooks"]
    ]
    assert len(entries) == len(hooks.PLUGIN_HOOK_IDS) + len(hooks.PLUGIN_ONLY_HOOKS)
    assert not any("ckit hook-run" in entry["command"] for entry in entries)
    script_commands = [
        entry["command"] for entry in entries if "/hooks/scripts/" in entry["command"]
    ]
    assert script_commands
    assert all(
        "${PLUGIN_ROOT}/hooks/scripts/" in command for command in script_commands
    )

    matchers = {
        group["matcher"] for groups in document["hooks"].values() for group in groups
    }
    assert "Bash|exec_command|shell|unified_exec" in matchers
    assert "Read|read_file" in matchers
    assert "Edit|MultiEdit|Write|apply_patch" in matchers
    assert "Write|apply_patch" in matchers

    forbidden = re.compile(
        r"CLAUDE_(?:PROJECT_DIR|PLUGIN_ROOT|CODE_)|\.claude(?:/|\\)|"
        r"\bClaude(?: Code)?\b|\bclaude-kit\b"
    )
    generated = [CODEX_HOOKS_FILE, *sorted(CODEX_HOOK_SCRIPTS.glob("*.sh"))]
    for path in generated:
        match = forbidden.search(path.read_text(encoding="utf-8"))
        assert match is None, f"{path.relative_to(REPO_ROOT)} leaked {match.group(0)!r}"


def test_static_codex_plugin_secret_guard_remains_honestly_read_only() -> None:
    """Shell-read enforcement belongs to the exact-wheel scaffolded adapter, not this subset."""
    groups = json.loads(CODEX_HOOKS_FILE.read_text(encoding="utf-8"))["hooks"][
        "PreToolUse"
    ]
    protect_groups = [
        group
        for group in groups
        if any(
            "refusing to read a secrets file" in entry.get("command", "")
            for entry in group["hooks"]
        )
    ]
    assert len(protect_groups) == 1
    assert protect_groups[0]["matcher"] == "Read|read_file"
    assert "unified_exec" not in protect_groups[0]["matcher"]


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_static_codex_sessionstart_scripts_find_root_from_nested_cwd(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    nested = repo / "src" / "package"
    memory = repo / ".ckit" / "agent-memory"
    memory.mkdir(parents=True)
    nested.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / ".ckit" / "CONTINUITY.md").write_text(
        "nested-root-continuity\n", encoding="utf-8"
    )
    (memory / "MEMORY.md").write_text(
        "# Memory\n\n- [Nested root lesson](patterns/root.md) — test\n",
        encoding="utf-8",
    )
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(tmp_path / "home"),
        "PLUGIN_ROOT": str(CODEX_PLUGIN_ROOT),
    }

    continuity = subprocess.run(
        ["bash", str(CODEX_HOOK_SCRIPTS / "load-continuity.sh")],
        cwd=nested,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    learnings = subprocess.run(
        ["bash", str(CODEX_HOOK_SCRIPTS / "load-learnings.sh")],
        cwd=nested,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert continuity.returncode == 0, continuity.stderr
    assert "nested-root-continuity" in continuity.stdout
    assert learnings.returncode == 0, learnings.stderr
    assert "Nested root lesson" in learnings.stdout
    assert not (nested / ".ckit").exists()


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_static_codex_root_resolver_rejects_symlinked_state(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    nested = repo / "nested"
    outside = tmp_path / "outside"
    nested.mkdir(parents=True)
    outside.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (outside / "CONTINUITY.md").write_text("must-not-load\n", encoding="utf-8")
    (repo / ".ckit").symlink_to(outside, target_is_directory=True)

    result = subprocess.run(
        ["bash", str(CODEX_HOOK_SCRIPTS / "load-continuity.sh")],
        cwd=nested,
        env={
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(tmp_path / "home"),
            "PLUGIN_ROOT": str(CODEX_PLUGIN_ROOT),
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout == result.stderr == ""


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq not installed")
@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_static_codex_writeback_stop_uses_native_continuation_and_loop_guard(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    nested = repo / "nested"
    nested.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    continuity = repo / ".ckit" / "CONTINUITY.md"
    continuity.parent.mkdir()
    continuity.write_text("# Continuity\n", encoding="utf-8")
    changed = repo / "src.py"
    changed.write_text("x = 1\n", encoding="utf-8")
    os.utime(continuity, (1_700_000_000, 1_700_000_000))
    os.utime(changed, (1_700_000_010, 1_700_000_010))
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(tmp_path / "home"),
        "PLUGIN_ROOT": str(CODEX_PLUGIN_ROOT),
    }

    first = subprocess.run(
        [
            "bash",
            str(CODEX_HOOK_SCRIPTS / "verify-continuity-writeback.sh"),
        ],
        input=json.dumps({"hook_event_name": "Stop", "stop_hook_active": False}),
        cwd=nested,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    guarded = subprocess.run(
        [
            "bash",
            str(CODEX_HOOK_SCRIPTS / "verify-continuity-writeback.sh"),
        ],
        input=json.dumps({"hook_event_name": "Stop", "stop_hook_active": True}),
        cwd=nested,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert first.returncode == 0, first.stderr
    assert json.loads(first.stdout)["decision"] == "block"
    assert "RARV step 4" in json.loads(first.stdout)["reason"]
    assert guarded.returncode == 0
    assert guarded.stdout == guarded.stderr == ""


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq not installed")
@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
@pytest.mark.parametrize(
    ("script_name", "package_script", "diagnostic", "npm_exit"),
    [
        ("lint-fix.sh", "lint", "problem: static lint", 0),
        ("type-check.sh", "typecheck", "error TS2304", 1),
    ],
)
def test_static_codex_feedback_stops_use_native_continuation_and_loop_guard(
    tmp_path: Path,
    script_name: str,
    package_script: str,
    diagnostic: str,
    npm_exit: int,
) -> None:
    repo = tmp_path / "repo"
    nested = repo / "nested"
    nested.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "package.json").write_text(
        json.dumps({"scripts": {package_script: "tool"}}), encoding="utf-8"
    )
    shim = tmp_path / "bin"
    shim.mkdir()
    npm = shim / "npm"
    npm.write_text(
        f"#!/bin/sh\nprintf '%s\\n' '{diagnostic}'\nexit {npm_exit}\n",
        encoding="utf-8",
    )
    npm.chmod(0o755)
    env = {
        "PATH": f"{shim}:{os.environ.get('PATH', '/usr/bin:/bin')}",
        "HOME": str(tmp_path / "home"),
        "PLUGIN_ROOT": str(CODEX_PLUGIN_ROOT),
        "CKIT_AUTOFIX": "1",
    }

    def invoke(active: bool) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(CODEX_HOOK_SCRIPTS / script_name)],
            input=json.dumps({"hook_event_name": "Stop", "stop_hook_active": active}),
            cwd=nested,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    first = invoke(False)
    guarded = invoke(True)
    assert first.returncode == 0, first.stderr
    assert json.loads(first.stdout)["decision"] == "block"
    assert diagnostic in json.loads(first.stdout)["reason"]
    assert guarded.returncode == 0
    assert guarded.stdout == guarded.stderr == ""


def test_gen_hooks_check_reports_in_sync() -> None:
    """The `gen_hooks.py --check` entrypoint passes against the committed files."""
    assert _load_gen_hooks().main(["--check"]) == 0


def test_plugin_only_hooks_declared_with_reason() -> None:
    """Plugin-only hooks are explicit data (with a reason) and absent from the CLI registry."""
    from claude_kit import hooks

    assert hooks.PLUGIN_ONLY_HOOKS, "expected at least one declared plugin-only hook"
    for hid, spec in hooks.PLUGIN_ONLY_HOOKS.items():
        assert spec.get("reason"), f"plugin-only hook {hid} must carry a reason"
        assert hid not in hooks.HOOK_REGISTRY, (
            f"{hid} is plugin-only; not in HOOK_REGISTRY"
        )


def test_kubectl_guard_is_plugin_only() -> None:
    """guard-kubectl-delete ships in the plugin file but NOT the CLI starter or the registry."""
    from claude_kit import hooks

    assert "guard-kubectl-delete" in hooks.PLUGIN_ONLY_HOOKS
    assert "guard-kubectl-delete.sh" in HOOKS_FILE.read_text(encoding="utf-8")
    starter = (REPO_ROOT / "templates" / "settings.json").read_text(encoding="utf-8")
    assert "guard-kubectl-delete" not in starter


def test_plugin_hooks_include_protect_secrets_read() -> None:
    """The always-on plugin must guard secret-file reads (PreToolUse/Read), not only via `init`.

    protect-secrets is in HOOK_REGISTRY and the standard/all profiles, so the CLI installs it — but it
    was missing from PLUGIN_HOOK_IDS, leaving plugin-only users unprotected until they ran an init.
    """
    groups = json.loads(HOOKS_FILE.read_text())["hooks"]["PreToolUse"]
    read = [g for g in groups if g.get("matcher") == "Read"]
    assert read, (
        "plugin hooks.json must have a PreToolUse 'Read' matcher group (protect-secrets)"
    )
    cmds = [h.get("command", "") for g in read for h in g["hooks"]]
    assert any("refusing to read a secrets file" in c for c in cmds), (
        "the Read group must contain the protect-secrets guard"
    )


def test_inline_guards_suppress_jq_errors() -> None:
    """Inline guard jq calls must use ``2>/dev/null || true`` so malformed hook JSON stays quiet.

    The ``command -v jq`` prefix handles a *missing* jq; this guards the call itself against malformed
    input spamming stderr or aborting the guard — matching the robust style in hooks/scripts/*.sh.
    """
    from claude_kit import hooks

    for name in ("_RM_RF_GUARD", "_SECRETS_GUARD"):
        guard = getattr(hooks, name)
        for segment in guard.split("$(jq")[1:]:
            call = segment.split(")")[0]
            assert "2>/dev/null" in call and "|| true" in call, (
                f"{name}: inline jq call must use '2>/dev/null || true'"
            )


def test_script_git_guards_suppress_jq_errors() -> None:
    """The script-backed git guards must also use the ``2>/dev/null || true`` safe jq pattern."""
    scripts = REPO_ROOT / "hooks" / "scripts"
    for name in ("guard-push-main.sh", "guard-destructive-git.sh", "guard-secrets.sh"):
        text = (scripts / name).read_text(encoding="utf-8")
        for segment in text.split("$(jq")[1:]:
            call = segment.split(")")[0]
            assert "2>/dev/null" in call and "|| true" in call, (
                f"{name}: jq call must use '2>/dev/null || true'"
            )


INIT_COMMAND = REPO_ROOT / "commands" / "init.md"
INIT_COMMAND_SKILL = REPO_ROOT / "skills" / "ckit-command-init" / "SKILL.md"
INIT_SH = REPO_ROOT / "scripts" / "init.sh"


def test_init_command_requires_cli_and_fails_loud() -> None:
    """/claude-kit:init must require the CLI and refuse to silently degrade when it's absent."""
    wrapper = INIT_COMMAND.read_text(encoding="utf-8")
    assert "allowed-tools: Skill" in wrapper
    assert "ckit-command-init" in wrapper
    text = INIT_COMMAND_SKILL.read_text(encoding="utf-8")
    assert "CKIT_CLI_MISSING" in text and "STOP" in text, (
        "must detect a missing CLI and stop"
    )
    assert (
        "pipx install claude-code-kit" in text or "pip install claude-code-kit" in text
    )
    # No environment variable may restore the retired shell-write bypass.
    assert "CLAUDE_KIT_BASIC=1" not in text
    assert (
        "do not scaffold anything" in text.lower()
        or "not silently fall back" in text.lower()
    )
    # 0.61.0: a missing CLI OFFERS a self-install (with re-detection) before the stop path.
    assert (
        "Install claude-code-kit now" in text and "re-run the detection" in text.lower()
    )


def test_init_script_is_a_non_mutating_cli_dispatcher(tmp_path: Path) -> None:
    """Historical init.sh callers dispatch safely or fail before touching the project."""
    text = INIT_SH.read_text(encoding="utf-8")
    assert 'exec claude-kit init "$@"' in text
    assert 'exec ckit init "$@"' in text
    assert 'exec claude-sdlc init "$@"' in text
    assert "pipx install claude-code-kit" in text
    for mutation in ("rm -", "cp ", "mkdir", "mv ", '>"'):
        assert mutation not in text, (
            f"compatibility launcher must not contain {mutation!r}"
        )

    target = tmp_path / "untouched"
    result = subprocess.run(
        ["bash", str(INIT_SH), str(target)],
        check=False,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 2
    assert "No project files were changed" in result.stderr
    assert not target.exists()


@pytest.mark.parametrize("runtime", ["codex", "both"])
def test_init_script_forwards_native_runtime_to_ckit(
    tmp_path: Path, runtime: str
) -> None:
    """The compatibility launcher preserves the explicit native runtime argument byte-for-byte."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    capture = tmp_path / "argv.txt"
    executable = bin_dir / "ckit"
    executable.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$@" > "$CKIT_CAPTURE"\n',
        encoding="utf-8",
    )
    executable.chmod(0o755)
    target = tmp_path / "project"

    result = subprocess.run(
        [
            "bash",
            str(INIT_SH),
            str(target),
            "--defaults",
            "--runtime",
            runtime,
        ],
        check=False,
        capture_output=True,
        text=True,
        env={
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "CKIT_CAPTURE": str(capture),
        },
    )

    assert result.returncode == 0, result.stderr
    assert capture.read_text(encoding="utf-8").splitlines() == [
        "init",
        str(target),
        "--defaults",
        "--runtime",
        runtime,
    ]


# --- functional rm-rf guard behaviour (order-independent recursive+force regex) ----------------

_NEED_JQ = pytest.mark.skipif(
    shutil.which("jq") is None,
    reason="the rm-rf guard degrades to a no-op without jq; its blocking can't be asserted",
)


def _run_rm_rf_guard(command: str) -> int:
    """Pipe a PreToolUse JSON payload through the inline rm-rf guard; return its exit code."""
    from claude_kit import hooks

    payload = json.dumps({"tool_input": {"command": command}})
    proc = subprocess.run(
        ["sh", "-c", hooks._RM_RF_GUARD],
        input=payload,
        capture_output=True,
        text=True,
    )
    return proc.returncode


@_NEED_JQ
@pytest.mark.parametrize(
    "command",
    [
        "rm -rf /tmp/x",
        "rm -fr /tmp/x",  # force before recursive
        "rm -r -f /tmp/x",  # split flags
        "rm -f -r /tmp/x",
        "rm -Rf /tmp/x",  # capital R
        "rm --recursive --force /tmp/x",
        "rm --force --recursive /tmp/x",
        "sudo rm -rf /tmp/x",  # leading command
    ],
)
def test_rm_rf_guard_blocks_recursive_force(command: str) -> None:
    """Every recursive+force spelling/ordering is blocked (exit 2), not only the literal ``-rf``."""
    assert _run_rm_rf_guard(command) == 2, command


@_NEED_JQ
@pytest.mark.parametrize(
    "command",
    [
        "rm /tmp/x",  # no flags
        "rm -f /tmp/x",  # force, not recursive
        "rm -i /tmp/x",  # interactive
        "docker rm -f mycontainer",  # removes a container, not files
        "git rm --cached file",  # unstage, no force/recursive
        "ls -alF /tmp",  # unrelated command
    ],
)
def test_rm_rf_guard_spares_safe_commands(command: str) -> None:
    """A command that is not a recursive *and* forced rm is allowed (exit 0)."""
    assert _run_rm_rf_guard(command) == 0, command


# --- functional git-guard behaviour: global-option + refspec bypass coverage (F1/F2) -----------

_SCRIPTS_DIR = REPO_ROOT / "hooks" / "scripts"


def _run_script_guard(script: str, command: str, project_dir: str | None = None) -> int:
    """Pipe a PreToolUse JSON payload through a script-backed guard; return its exit code."""
    payload = json.dumps({"tool_input": {"command": command}})
    env = dict(os.environ)
    if project_dir:
        env["CLAUDE_PROJECT_DIR"] = project_dir
    proc = subprocess.run(
        ["bash", str(_SCRIPTS_DIR / script)],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
    )
    return proc.returncode


@_NEED_JQ
@pytest.mark.parametrize(
    "command",
    [
        "git push origin main",
        "git push -f origin master",
        "git push --force origin main",
        "git push origin HEAD:main",
        "git push origin +main",  # '+' force-push prefix
        "git push origin HEAD:refs/heads/main",  # fully-qualified refspec
        "git push origin +refs/heads/master",
        "git -c k=v push origin main",  # global option before subcommand
        "git -C /some/dir push origin main",
        "git --git-dir=/x/.git push origin main",
        "deploy && git push origin main",  # compound segment
        # Quoted forms: word-splitting keeps quote chars as literal token text, so these evaded
        # the word-boundary regex until the guards stripped shell quoting before matching (R3).
        'git push origin "main"',
        "git push origin 'main'",
        'git push origin "+main"',
        'git push origin "HEAD:refs/heads/main"',
        'git push "origin" "master"',
        '"git" push origin main',  # even the git token itself quoted
        "git push origin ma\\in",  # backslash inside the ref name
    ],
)
def test_push_main_guard_blocks(command: str) -> None:
    assert _run_script_guard("guard-push-main.sh", command) == 2, command


@_NEED_JQ
@pytest.mark.parametrize(
    "command",
    [
        "git push origin feature-x",
        "git push origin main-feature",  # boundary: main followed by '-'
        "git push origin feature/main-ui",
        "git push origin maintenance",  # substring, not the ref
        "git -c k=v push origin develop",
        "git commit -m 'fix main loop'",  # not a push at all
        "echo main",  # not git
        'git push origin "feature/main-ui"',  # quoted legit branch stays spared
        'git push origin "remaster-ui"',
    ],
)
def test_push_main_guard_spares(command: str) -> None:
    assert _run_script_guard("guard-push-main.sh", command) == 0, command


@_NEED_JQ
@pytest.mark.parametrize(
    "command",
    [
        "git reset --hard",
        "git reset --hard HEAD~1",
        "git clean -fd",
        "git clean --force",
        "git checkout .",
        "git restore .",
        "git -c k=v reset --hard",  # global option before subcommand
        "git -C /some/dir clean -f",
        "foo; git reset --hard",  # compound segment
        'git checkout "."',  # quoted '.' evaded rule 3's boundary until quote-stripping (R3)
        "git restore '.'",
        "git restore --staged --worktree .",  # --worktree discards worktree changes too
        "git restore -SW .",  # combined short flags: -W makes it destructive
        "git restore --staged . && git checkout .",  # safe unstage must not mask a discard
        "git restore -s HEAD~1 .",  # lowercase -s is --source, NOT --staged: still a discard
    ],
)
def test_destructive_git_guard_blocks(command: str) -> None:
    assert _run_script_guard("guard-destructive-git.sh", command) == 2, command


@_NEED_JQ
@pytest.mark.parametrize(
    "command",
    [
        "git clean -n",  # dry run
        "git checkout mybranch",
        "git checkout -- file.txt",  # single file, not '.'
        "git reset HEAD",  # soft reset, not --hard
        "git reset --soft HEAD~1",
        "git status",
        'git commit -m "reset --hard is scary"',  # the phrase inside a message, not a reset
        "git restore --staged .",  # unstage-only: index -> HEAD, worktree untouched
        "git restore -S .",  # short form of --staged
    ],
)
def test_destructive_git_guard_spares(command: str) -> None:
    assert _run_script_guard("guard-destructive-git.sh", command) == 0, command


@_NEED_JQ
@pytest.mark.parametrize(
    "command",
    [
        "kubectl delete pod x",
        'kubectl "delete" pod x',  # quoted verb evaded the word boundary until quote-stripping
        "kubectl get pods -o name | xargs kubectl delete",  # compound segment (header claim)
        "kubectl -n prod delete deployment api",
    ],
)
def test_kubectl_delete_guard_blocks(command: str) -> None:
    assert _run_script_guard("guard-kubectl-delete.sh", command) == 2, command


@_NEED_JQ
@pytest.mark.parametrize(
    "command",
    [
        "kubectl config delete-context staging",  # hyphenated look-alike
        "kubectl drain node1 --delete-emptydir-data",
        "kubectl wait --for=delete pod/x",
        "kubectl auth can-i delete pods",  # read-only RBAC query
        'kubectl logs pod -c "delete-worker"',  # quoted container name, not the verb
        "helm delete myrelease",  # not kubectl
    ],
)
def test_kubectl_delete_guard_spares(command: str) -> None:
    assert _run_script_guard("guard-kubectl-delete.sh", command) == 0, command


# --- functional guard-secrets behaviour: staged files + staged values (R2) ----------------------
#
# The secret-shaped VALUES below are assembled by concatenation so the shape never appears
# literally in this file: the kit dogfoods guard-secrets.sh on its own commits, and a literal
# AKIA…/ghp_… string in the staged diff would block the commit that adds these tests.
# All parts are fake or canonical documentation examples.

_NEED_GIT = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _staged_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    """Init a throwaway git repo with ``files`` written and staged (never committed)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    for name, content in files.items():
        p = repo / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    return repo


@_NEED_JQ
@_NEED_GIT
@pytest.mark.parametrize(
    "fname",
    [
        ".env",
        ".env.production",
        "server.pem",
        "deploy.key",
        "credentials.json",
        "cfg/credentials.yaml",
    ],
)
def test_secrets_guard_blocks_secretlike_staged_files(
    tmp_path: Path, fname: str
) -> None:
    repo = _staged_repo(tmp_path, {fname: "placeholder\n"})
    assert (
        _run_script_guard(
            "guard-secrets.sh", "git commit -m msg", project_dir=str(repo)
        )
        == 2
    ), fname


@_NEED_JQ
@_NEED_GIT
@pytest.mark.parametrize(
    "fname",
    [".env.example", ".env.sample", ".env.template", ".env.dist"],
)
def test_secrets_guard_spares_env_placeholder_files(tmp_path: Path, fname: str) -> None:
    """Placeholder env files hold variable names for onboarding and are committed on purpose."""
    repo = _staged_repo(tmp_path, {fname: "API_KEY=\nDATABASE_URL=\n"})
    assert (
        _run_script_guard(
            "guard-secrets.sh", "git commit -m msg", project_dir=str(repo)
        )
        == 0
    ), fname


@_NEED_JQ
@_NEED_GIT
@pytest.mark.parametrize(
    "value",
    [
        "aws_key = "
        + "AKIA"
        + "IOSFODNN7EXAMPLE",  # AWS docs' canonical example key id
        "-----BEGIN RSA " + "PRIVATE KEY-----",
        "token = " + "ghp_" + "a1B2c3D4" * 5,  # 40 chars after the prefix
        "stripe = " + "sk_live_" + "x9" * 12,
        "slack = " + "xoxb-" + "123456789012-abcdefghij",
    ],
)
def test_secrets_guard_blocks_secret_values_in_staged_diff(
    tmp_path: Path, value: str
) -> None:
    repo = _staged_repo(tmp_path, {"settings.py": value + "\n"})
    assert (
        _run_script_guard(
            "guard-secrets.sh", "git commit -m msg", project_dir=str(repo)
        )
        == 2
    )


@_NEED_JQ
@_NEED_GIT
def test_secrets_guard_blocks_through_git_global_options(tmp_path: Path) -> None:
    """`git -c user.email=x commit` cannot slip a secret-bearing commit past the normalizer."""
    repo = _staged_repo(tmp_path, {".env": "placeholder\n"})
    cmd = "git -c user.email=x commit -m msg"
    assert _run_script_guard("guard-secrets.sh", cmd, project_dir=str(repo)) == 2


@_NEED_JQ
@_NEED_GIT
def test_secrets_guard_spares_names_without_values(tmp_path: Path) -> None:
    """Env-var NAMES (SECRET_KEY, API_KEY) are not secrets — only value shapes block."""
    repo = _staged_repo(
        tmp_path,
        {
            "app.py": 'SECRET_KEY = os.environ["SECRET_KEY"]\n',
            "README.md": "Set API_KEY and DATABASE_PASSWORD in your environment.\n",
        },
    )
    assert (
        _run_script_guard(
            "guard-secrets.sh", "git commit -m msg", project_dir=str(repo)
        )
        == 0
    )


@_NEED_JQ
@_NEED_GIT
def test_secrets_guard_ignores_non_commit_commands(tmp_path: Path) -> None:
    """A dirty stage does not block unrelated git commands — only `commit` is gated."""
    repo = _staged_repo(tmp_path, {".env": "placeholder\n"})
    assert (
        _run_script_guard("guard-secrets.sh", "git status", project_dir=str(repo)) == 0
    )


@_NEED_JQ
def test_secrets_guard_degrades_outside_a_git_repo(tmp_path: Path) -> None:
    """Fail-open: a commit command with CLAUDE_PROJECT_DIR at a non-repo is a no-op."""
    plain = tmp_path / "plain"
    plain.mkdir()
    assert (
        _run_script_guard(
            "guard-secrets.sh", "git commit -m msg", project_dir=str(plain)
        )
        == 0
    )


def test_gate_ledger_guidance_probes_capability_not_cli_presence(payload: Path) -> None:
    """No payload file may gate the gate-ledger commands on `command -v claude-kit`.

    A presence test is satisfied by a binary of any age. A CLI pip-installed once while the plugin
    moved on is the ordinary state, not an exotic one, and `skip-gate` only shipped in 0.76.0 — so
    presence-testing let a live run announce that a command "doesn't exist in this version" when it
    existed in the version the project actually had (F-075). The fix is to probe the subcommand
    (`claude-kit pipeline close-gate --help`), and this pins it: prose drifts back easily, and the
    failure it causes is a false statement about the product rather than a crash anyone would spot.

    `commands/init.md` is deliberately NOT covered. It probes presence only to locate the required
    Python installer; the compatibility shell launcher performs no project writes.
    """
    offenders = []
    for rel in ("rules", "skills", "agents", "templates"):
        root = payload / rel
        if not root.is_dir():
            continue
        for md in root.rglob("*.md"):
            text = md.read_text(encoding="utf-8", errors="replace")
            if "command -v claude-kit" not in text:
                continue
            # Only a file that then relies on the ledger subcommands is making the bad promise.
            if "close-gate" not in text and "skip-gate" not in text:
                continue
            # A POSITIVE requirement, after two attempts at negative ones failed in opposite
            # directions: "line contains no 'never'" passed the planted pre-fix wording (these
            # paragraphs are single unwrapped lines that all say "never by hand-editing" further
            # along), and "no 'never' in the 40 chars before" then flagged the fixed text, which
            # has to quote the bad probe in order to warn against it. Prose is a poor thing to
            # pattern-match for absence. So: a file that reaches for the ledger and mentions the
            # presence probe must ALSO carry the capability probe. That is one unambiguous string,
            # it cannot be satisfied by accident, and deleting it is exactly the regression.
            if "close-gate --help" not in text:
                offenders.append(str(md.relative_to(payload)))
    assert not offenders, (
        "gate-ledger guidance still gates on CLI presence instead of subcommand capability "
        f"(F-075): {offenders}"
    )
