"""Root host instructions are generated from one accurate canonical source."""

from __future__ import annotations

import subprocess
import sys

from scripts.gen_contributor_guides import ROOT, check, generated_guides


def test_root_contributor_guides_are_generated_and_truthful() -> None:
    assert check() == []
    guides = {path.name: text for path, text in generated_guides().items()}
    assert set(guides) == {"CLAUDE.md", "AGENTS.md"}
    for text in guides.values():
        assert "Selection\n    -> catalog.resolve()\n    -> ResolvedPlan" in text
        assert ".ckit/" in text
        assert ".codex/agents/*.toml" in text
        assert "`workflow_evidence.py`" in text
        assert "`program_execution.py`" in text
        assert "`twine upload`" in text
        assert ".Codex/" not in text
        assert "Codex-kit" not in text
    assert "Claude Code contributor guidance" in guides["CLAUDE.md"]
    assert "Codex contributor guidance" in guides["AGENTS.md"]


def test_contributor_generator_check_cli() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/gen_contributor_guides.py", "--check"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "current" in result.stdout
