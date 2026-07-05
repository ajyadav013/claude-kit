#!/usr/bin/env python3
"""Generate (or --check) the two *static* hook files from the single ``hooks.py`` registry.

claude-kit ships hooks through three channels, but only one should ever be hand-maintained:

* the **installed** ``.claude/settings.json`` -- built per-profile by ``hooks.build_settings`` at init;
* the auto-discovered **plugin** ``hooks/hooks.json`` (``${CLAUDE_PLUGIN_ROOT}`` paths);
* the thin no-pip **starter** ``templates/settings.json`` (``$CLAUDE_PROJECT_DIR`` paths).

The latter two used to be edited by hand and silently drifted from the registry (and each other).
This script regenerates both from ``claude_kit.hooks`` so the registry is the single source of truth.

Usage::

    python scripts/gen_hooks.py            # regenerate the two files in place
    python scripts/gen_hooks.py --check    # exit 1 if either file is out of sync (CI / tests)
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

#: (path on disk, generator) for each static file derived from the registry.
TARGETS = [
    (ROOT / "hooks" / "hooks.json", hooks.generate_plugin_hooks_json),
    (ROOT / "templates" / "settings.json", hooks.generate_starter_settings),
]


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
            path.write_text(want, encoding="utf-8")
            print(f"wrote {path.relative_to(ROOT)}")
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
