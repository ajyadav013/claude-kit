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
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_MANIFEST = REPO_ROOT / ".claude-plugin" / "plugin.json"
HOOKS_FILE = REPO_ROOT / "hooks" / "hooks.json"

pytestmark = pytest.mark.skipif(
    not PLUGIN_MANIFEST.exists(),
    reason="plugin manifest only present in a source checkout, not the wheel",
)

VALID_EVENTS = {
    "PreToolUse",
    "PostToolUse",
    "UserPromptSubmit",
    "Notification",
    "Stop",
    "SubagentStop",
    "SessionStart",
    "SessionEnd",
    "PreCompact",
}


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
        assert event in VALID_EVENTS, f"unknown hook event: {event}"
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
INIT_SH = REPO_ROOT / "scripts" / "init.sh"


def test_init_command_requires_cli_and_fails_loud() -> None:
    """/claude-kit:init must require the CLI and refuse to silently degrade when it's absent."""
    text = INIT_COMMAND.read_text(encoding="utf-8")
    assert "CKIT_CLI_MISSING" in text and "STOP" in text, (
        "must detect a missing CLI and stop"
    )
    assert (
        "pipx install claude-code-kit" in text or "pip install claude-code-kit" in text
    )
    # The thin fallback must be opt-in (gated behind CLAUDE_KIT_BASIC), never the silent default.
    assert "CLAUDE_KIT_BASIC" in text
    assert (
        "do not scaffold anything" in text.lower()
        or "not silently fall back" in text.lower()
    )
    # 0.61.0: a missing CLI OFFERS a self-install (with re-detection) before the stop path.
    assert (
        "Install claude-code-kit now" in text and "re-run the detection" in text.lower()
    )


def test_basic_scaffolder_warns_it_is_degraded() -> None:
    """The no-pip shell scaffolder must announce that it is a degraded, no-resolution install."""
    text = INIT_SH.read_text(encoding="utf-8")
    assert "BASIC scaffolder" in text
    assert "upgrade" in text and "NOT work" in text


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
