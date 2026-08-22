#!/usr/bin/env python3
"""Generate (or --check) static provider hook payloads from the single ``hooks.py`` registry.

claude-kit ships hooks through four channels, but only one should ever be hand-maintained:

* the **installed** ``.claude/settings.json`` -- built per-profile by ``hooks.build_settings`` at init;
* the auto-discovered **Claude plugin** ``hooks/hooks.json``
  (``${CLAUDE_PLUGIN_ROOT}`` paths);
* the auto-discovered **Codex plugin** ``providers/codex/claude-kit/hooks/hooks.json``
  (``${PLUGIN_ROOT}`` paths), plus its exact registry-selected script inventory;
* the legacy static settings template ``templates/settings.json``
  (``$CLAUDE_PROJECT_DIR`` paths).

The generated payloads must not be edited by hand. This script regenerates them from
``claude_kit.hooks`` so the registry is the single source of truth. The static template remains a
compatibility artifact; ``scripts/init.sh`` no longer copies it.

Usage::

    python scripts/gen_hooks.py            # regenerate provider files in place
    python scripts/gen_hooks.py --check    # exit 1 if any generated file is out of sync
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(
    0, str(ROOT / "src")
)  # importable from a bare checkout (no editable install needed)

from claude_kit import hooks  # noqa: E402
from claude_kit.provider_renderers import CodexRenderer  # noqa: E402

#: (path on disk, generator) for each static file derived from the registry.
TARGETS = [
    (ROOT / "hooks" / "hooks.json", hooks.generate_plugin_hooks_json),
    (ROOT / "templates" / "settings.json", hooks.generate_starter_settings),
    (
        ROOT / "providers" / "codex" / "claude-kit" / "hooks" / "hooks.json",
        hooks.generate_codex_plugin_hooks_json,
    ),
]

CODEX_SCRIPTS_ROOT = ROOT / "providers" / "codex" / "claude-kit" / "hooks" / "scripts"
CODEX_RENDERER = CodexRenderer(ROOT)


def render_codex_plugin_script(name: str) -> str:
    """Project one registry script for direct execution from the static Codex plugin."""
    rendered = CODEX_RENDERER._adapt_hook_script(name, frozenset())
    if name == "load-learnings.sh":
        # The message names Codex's explicit skill invocation syntax; it is not a shell variable.
        rendered = rendered.replace(
            "explicit $remember skill", "explicit \\$remember skill"
        )
    return rendered


def _render(doc: dict) -> str:
    """Canonical JSON form (2-space indent, literal Unicode, trailing newline) for both files."""
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str]) -> int:
    check = "--check" in argv
    drift: list[Path] = []
    for path, generate in TARGETS:
        want = _render(generate())
        have = path.read_text(encoding="utf-8") if path.is_file() else ""
        if check:
            if want != have:
                drift.append(path)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(want, encoding="utf-8")
            print(f"wrote {path.relative_to(ROOT)}")

    expected_scripts = {
        CODEX_SCRIPTS_ROOT / name: render_codex_plugin_script(name)
        for name in hooks.plugin_script_names()
    }
    existing_scripts = (
        {path for path in CODEX_SCRIPTS_ROOT.iterdir() if path.is_file()}
        if CODEX_SCRIPTS_ROOT.is_dir()
        else set()
    )
    for destination, expected in expected_scripts.items():
        same = (
            destination.is_file()
            and destination.read_text(encoding="utf-8") == expected
        )
        if check:
            if not same:
                drift.append(destination)
        elif not same:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(expected, encoding="utf-8")
            destination.chmod(0o755)
            print(f"projected {destination.relative_to(ROOT)}")
    stale_scripts = existing_scripts - set(expected_scripts)
    if check:
        drift.extend(sorted(stale_scripts))
    else:
        for path in sorted(stale_scripts):
            path.unlink()
            print(f"removed stale generated script {path.relative_to(ROOT)}")
    if check:
        if drift:
            print(
                "hooks drift: FAIL -- run `python scripts/gen_hooks.py` to regenerate:"
            )
            for path in drift:
                print(f"  - {path.relative_to(ROOT)}")
            return 1
        print("hooks: in sync with the registry")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
