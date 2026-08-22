"""The documented native output topologies match fresh runtime installations."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from claude_kit import catalog
from claude_kit.models import InstallRequest
from claude_kit.runtime_scaffold import install_runtime

ROOT = Path(__file__).parents[1]


def _documented_families(runtime: str) -> set[str]:
    text = (ROOT / "docs/install.md").read_text(encoding="utf-8")
    pattern = rf"### `--runtime {runtime}`\n\n```text\n(?P<body>.*?)\n```"
    match = re.search(pattern, text, re.DOTALL)
    assert match is not None, f"missing documented layout for {runtime}"
    return {line for line in match.group("body").splitlines() if line}


def _installed_families(target: Path) -> set[str]:
    families: set[str] = set()
    for path in target.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(target)
        parts = relative.parts
        if len(parts) == 1:
            families.add(relative.as_posix())
        elif parts[0] == ".claude":
            families.add(
                ".claude/settings.json"
                if parts[1] == "settings.json"
                else f".claude/{parts[1]}/"
            )
        elif parts[0] == ".agents":
            families.add(".agents/skills/")
        elif parts[0] == ".codex":
            if parts[1] in {"config.toml", "hooks.json"}:
                families.add(f".codex/{parts[1]}")
            elif parts[1] == "hooks":
                families.add(".codex/hooks/scripts/")
            else:
                families.add(f".codex/{parts[1]}/")
        elif parts[0] == ".ckit":
            families.add(
                relative.as_posix() if len(parts) == 2 else f".ckit/{parts[1]}/"
            )
        else:
            families.add(f"{parts[0]}/")
    return families


@pytest.mark.parametrize("runtime", ("claude", "codex", "both"))
def test_documented_default_layout_matches_fresh_install(payload, tmp_path, runtime):
    selection = catalog.defaults(payload)
    plan = catalog.resolve(payload, selection)
    target = tmp_path / runtime

    install_runtime(
        payload,
        target,
        plan,
        InstallRequest(selection=selection, runtime=runtime),
    )

    assert _documented_families(runtime) == _installed_families(target)
