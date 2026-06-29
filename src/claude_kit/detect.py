"""Best-effort discovery of a project's real build/test commands, to override catalog defaults.

When ``init``/``upgrade`` runs against a populated repo, the generic catalog commands
("npm run test", "pip install -e '.[dev]'") may not match the repo's toolchain. This module inspects
the target for **unambiguous** signals — a JS package-manager lockfile + ``package.json`` scripts, a
Python package-manager lockfile/marker — and returns overrides for the ``*_cmd`` render-context keys
so CLAUDE.md documents commands that actually work.

Design — **fail-open and conservative**:

* every probe is wrapped so a malformed file never raises (it just yields no override);
* a key is overridden ONLY on an unambiguous signal;
* on an empty target nothing is detected, so the output is identical to the catalog defaults — which
  preserves the ``init --dry-run`` ≡ real-install invariant (the previewer installs into an empty
  sandbox keyed on the real target).

Scope today: JS package managers (npm·pnpm·yarn·bun) → install + present ``package.json`` scripts;
Python package managers (uv·poetry·pdm·hatch) → the install command. Task runners (just·task·make)
and Python *run*-command rewriting are deliberate future extensions — the override-merge design makes
them purely additive.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

#: JS lockfile -> (package manager, how it invokes a script). yarn omits "run".
_JS_LOCKFILES = [
    ("pnpm-lock.yaml", "pnpm", "pnpm run"),
    ("yarn.lock", "yarn", "yarn"),
    ("bun.lockb", "bun", "bun run"),
    ("bun.lock", "bun", "bun run"),
    ("package-lock.json", "npm", "npm run"),
]
#: package.json script name -> frontend render-context key it maps to.
_JS_SCRIPT_KEYS = {
    "dev": "frontend_dev_cmd",
    "test": "frontend_test_cmd",
    "lint": "frontend_lint_cmd",
    "build": "frontend_build_cmd",
    "typecheck": "frontend_typecheck_cmd",
    "type-check": "frontend_typecheck_cmd",
}


def detect_commands(target: str | Path, selection: Any = None) -> dict[str, str]:
    """Return ``{context_key: command}`` overrides discovered in ``target`` ({} if none/empty)."""
    overrides: dict[str, str] = {}
    try:
        root = Path(target)
        if not root.is_dir():
            return overrides
        _detect_js(root, overrides)
        _detect_python(root, overrides)
    except Exception:
        return overrides  # fail-open: discovery must never break an install
    return overrides


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _detect_js(root: Path, out: dict[str, str]) -> None:
    if not (root / "package.json").is_file():
        return
    pm, run = "npm", "npm run"  # package.json but no lockfile -> npm
    for fn, name, prefix in _JS_LOCKFILES:
        if (root / fn).is_file():
            pm, run = name, prefix
            break
    out["frontend_install_cmd"] = f"{pm} install"
    data = _read_json(root / "package.json") or {}
    scripts = data.get("scripts") if isinstance(data, dict) else None
    if not isinstance(scripts, dict):
        return
    for script, key in _JS_SCRIPT_KEYS.items():
        if script in scripts and key not in out:
            out[key] = f"{run} {script}"


def _detect_python(root: Path, out: dict[str, str]) -> None:
    text = ""
    try:
        pyproject = root / "pyproject.toml"
        if pyproject.is_file():
            text = pyproject.read_text(encoding="utf-8")
    except Exception:
        text = ""
    if (root / "uv.lock").is_file() or "[tool.uv]" in text:
        out["backend_install_cmd"] = "uv sync"
    elif (root / "poetry.lock").is_file() or "[tool.poetry]" in text:
        out["backend_install_cmd"] = "poetry install"
    elif (root / "pdm.lock").is_file() or "[tool.pdm]" in text:
        out["backend_install_cmd"] = "pdm install"
    elif "[tool.hatch" in text:
        out["backend_install_cmd"] = "hatch env create"
