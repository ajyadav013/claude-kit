"""Command discovery (:mod:`claude_kit.detect`) — unit probes + the init/dry-run/snapshot wiring.

Two layers:

* unit tests call :func:`detect.detect_commands` directly against a hand-built repo and assert the
  ``*_cmd`` overrides for each package manager (and that a malformed file fails open, never raising);
* integration tests install into a *populated* target and assert the discovered commands reach the
  rendered ``CLAUDE.md`` and the stack snapshot — while an empty target stays a no-op (the invariant
  that keeps ``init --dry-run`` ≡ a real install).
"""

from __future__ import annotations

import json

import yaml

from claude_kit import catalog, detect, scaffold
from tests._helpers import make_selection


def _write(path, text=""):
    path.write_text(text, encoding="utf-8")


# --------------------------------------------------------------------------- unit: JS


def test_empty_target_detects_nothing(tmp_path):
    """No lockfiles / no package.json -> {} (this is what preserves dry-run ≡ install)."""
    assert detect.detect_commands(tmp_path) == {}


def test_missing_target_is_fail_open(tmp_path):
    assert detect.detect_commands(tmp_path / "does-not-exist") == {}


def test_pnpm_lockfile_and_scripts(tmp_path):
    _write(tmp_path / "pnpm-lock.yaml")
    _write(
        tmp_path / "package.json",
        json.dumps(
            {"scripts": {"dev": "vite", "test": "vitest", "build": "vite build"}}
        ),
    )
    out = detect.detect_commands(tmp_path)
    assert out["frontend_install_cmd"] == "pnpm install"
    assert out["frontend_dev_cmd"] == "pnpm run dev"
    assert out["frontend_test_cmd"] == "pnpm run test"
    assert out["frontend_build_cmd"] == "pnpm run build"


def test_yarn_omits_run_keyword(tmp_path):
    """yarn invokes scripts without the `run` word (yarn test, not yarn run test)."""
    _write(tmp_path / "yarn.lock")
    _write(tmp_path / "package.json", json.dumps({"scripts": {"test": "jest"}}))
    out = detect.detect_commands(tmp_path)
    assert out["frontend_install_cmd"] == "yarn install"
    assert out["frontend_test_cmd"] == "yarn test"


def test_bun_lockfile(tmp_path):
    _write(tmp_path / "bun.lockb")
    _write(tmp_path / "package.json", json.dumps({"scripts": {"test": "bun test"}}))
    out = detect.detect_commands(tmp_path)
    assert out["frontend_install_cmd"] == "bun install"
    assert out["frontend_test_cmd"] == "bun run test"


def test_package_json_without_lockfile_falls_back_to_npm(tmp_path):
    _write(tmp_path / "package.json", json.dumps({"scripts": {"test": "jest"}}))
    out = detect.detect_commands(tmp_path)
    assert out["frontend_install_cmd"] == "npm install"
    assert out["frontend_test_cmd"] == "npm run test"


def test_typecheck_alias_maps_to_one_key(tmp_path):
    """Both `typecheck` and `type-check` script names map to frontend_typecheck_cmd."""
    _write(
        tmp_path / "package.json",
        json.dumps({"scripts": {"type-check": "tsc --noEmit"}}),
    )
    out = detect.detect_commands(tmp_path)
    assert out["frontend_typecheck_cmd"] == "npm run type-check"


def test_no_scripts_still_yields_install(tmp_path):
    _write(tmp_path / "package.json", json.dumps({"name": "x"}))
    out = detect.detect_commands(tmp_path)
    assert out["frontend_install_cmd"] == "npm install"
    assert "frontend_test_cmd" not in out


def test_malformed_package_json_is_fail_open(tmp_path):
    """A broken package.json must not raise — install command still comes from the lockfile."""
    _write(tmp_path / "pnpm-lock.yaml")
    _write(tmp_path / "package.json", "{ this is not json")
    out = detect.detect_commands(tmp_path)
    assert out["frontend_install_cmd"] == "pnpm install"
    assert "frontend_test_cmd" not in out


# --------------------------------------------------------------------------- unit: Python


def test_uv_lock_detects_uv_sync(tmp_path):
    _write(tmp_path / "uv.lock")
    assert detect.detect_commands(tmp_path)["backend_install_cmd"] == "uv sync"


def test_poetry_lock_detects_poetry_install(tmp_path):
    _write(tmp_path / "poetry.lock")
    assert detect.detect_commands(tmp_path)["backend_install_cmd"] == "poetry install"


def test_pdm_lock_detects_pdm_install(tmp_path):
    _write(tmp_path / "pdm.lock")
    assert detect.detect_commands(tmp_path)["backend_install_cmd"] == "pdm install"


def test_hatch_marker_detects_hatch(tmp_path):
    _write(tmp_path / "pyproject.toml", "[tool.hatch.envs.default]\n")
    assert detect.detect_commands(tmp_path)["backend_install_cmd"] == "hatch env create"


def test_uv_table_marker_without_lockfile(tmp_path):
    _write(tmp_path / "pyproject.toml", "[tool.uv]\n")
    assert detect.detect_commands(tmp_path)["backend_install_cmd"] == "uv sync"


def test_lockfile_wins_over_marker(tmp_path):
    """A real uv.lock takes precedence even if a stray poetry marker is present in pyproject."""
    _write(tmp_path / "uv.lock")
    _write(tmp_path / "pyproject.toml", "[tool.poetry]\n")
    assert detect.detect_commands(tmp_path)["backend_install_cmd"] == "uv sync"


# --------------------------------------------------------------------------- integration


def _install_into(payload, target, **overrides):
    plan = catalog.resolve(payload, make_selection(payload, **overrides))
    scaffold.install_sdlc(payload, target, plan, force=True, log=[])
    return plan


def test_detected_commands_reach_claude_md(tmp_path, payload):
    """A populated target's real pnpm/uv commands appear in the rendered CLAUDE.md."""
    _write(tmp_path / "pnpm-lock.yaml")
    _write(tmp_path / "package.json", json.dumps({"scripts": {"test": "vitest"}}))
    _write(tmp_path / "uv.lock")
    _install_into(payload, tmp_path)
    claude_md = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert "pnpm install" in claude_md
    assert "pnpm run test" in claude_md
    assert "uv sync" in claude_md


def test_detected_commands_recorded_in_snapshot(tmp_path, payload):
    _write(tmp_path / "uv.lock")
    _install_into(payload, tmp_path)
    snap = yaml.safe_load(
        (tmp_path / ".claude" / "config" / "stack-catalog.snapshot.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert snap["detected_commands"]["backend_install_cmd"] == "uv sync"


def test_empty_target_records_no_detected_commands(tmp_path, payload):
    """Snapshot's detected_commands is empty on a bare target — the dry-run ≡ install invariant."""
    _install_into(payload, tmp_path)
    snap = yaml.safe_load(
        (tmp_path / ".claude" / "config" / "stack-catalog.snapshot.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert snap["detected_commands"] == {}


def test_no_detect_commands_disables_discovery(tmp_path, payload):
    """Selection.detect_commands=False keeps the generic catalog commands even on a populated repo."""
    _write(tmp_path / "uv.lock")
    _install_into(payload, tmp_path, detect_commands=False)
    snap = yaml.safe_load(
        (tmp_path / ".claude" / "config" / "stack-catalog.snapshot.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert snap["detected_commands"] == {}
    assert "uv sync" not in (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")


def test_preview_reflects_real_target_tooling(tmp_path, payload):
    """preview_install detects against the real target (not its empty sandbox) → dry-run ≡ install."""
    _write(tmp_path / "uv.lock")
    plan = catalog.resolve(payload, make_selection(payload))
    log, paths = scaffold.preview_install(payload, tmp_path, plan)
    assert plan.detected_commands == {"backend_install_cmd": "uv sync"}
