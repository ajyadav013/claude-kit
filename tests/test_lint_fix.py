"""Stop-hook lint-fix scoping (P0-3).

`lint-fix.sh` must not reformat files the user never touched. By default it formats only files changed
in the repo (git-scoped); `CLAUDE_KIT_AUTOFIX=1` restores whole-repo formatting. These tests build a
throwaway git repo with one committed-but-unrelated file and one changed file and assert the scoping.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "hooks" / "scripts" / "lint-fix.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None or shutil.which("ruff") is None,
    reason="git + ruff required to exercise lint-fix scoping",
)

_BAD = "a   =   1\n"  # ruff format rewrites this to "a = 1\n"
_GOOD = "a = 1\n"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    return repo


def _run_hook(repo: Path, autofix: bool = False) -> None:
    env = {"PATH": os.environ["PATH"], "CLAUDE_PROJECT_DIR": str(repo)}
    if autofix:
        env["CLAUDE_KIT_AUTOFIX"] = "1"
    subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=str(repo),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        env=env,
        check=True,
    )


def test_scoped_run_leaves_unchanged_files_alone(tmp_path):
    repo = _make_repo(tmp_path)
    # An unrelated file committed already (badly formatted) — NOT a working-tree change.
    (repo / "untouched.py").write_text(_BAD, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "init")
    # A new, badly-formatted file the agent just created (untracked => in scope).
    (repo / "changed.py").write_text(_BAD, encoding="utf-8")

    _run_hook(repo)

    assert (repo / "changed.py").read_text(encoding="utf-8") == _GOOD
    assert (repo / "untouched.py").read_text(encoding="utf-8") == _BAD


def test_autofix_formats_the_whole_repo(tmp_path):
    repo = _make_repo(tmp_path)
    (repo / "untouched.py").write_text(_BAD, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "init")
    (repo / "changed.py").write_text(_BAD, encoding="utf-8")

    _run_hook(repo, autofix=True)

    assert (repo / "changed.py").read_text(encoding="utf-8") == _GOOD
    assert (repo / "untouched.py").read_text(encoding="utf-8") == _GOOD
