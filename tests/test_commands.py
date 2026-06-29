"""Slash-command markdown safety (P0-1).

A slash command's `$ARGUMENTS` is substituted *textually* before the shell runs, so embedding it raw in
an executable code block lets a crafted argument word-split, glob, or inject a command. The commands
must instead instruct the agent to pass user arguments as separate, individually-quoted argv items —
so `$ARGUMENTS` must never appear inside a fenced shell code block.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

COMMANDS_DIR = Path(__file__).resolve().parents[1] / "commands"

_FENCE_RE = re.compile(r"```.*?\n(.*?)```", re.DOTALL)


def _fenced_blocks(text: str) -> list[str]:
    return _FENCE_RE.findall(text)


@pytest.mark.parametrize(
    "cmd_file", sorted(COMMANDS_DIR.glob("*.md")), ids=lambda p: p.name
)
def test_no_raw_arguments_in_shell_blocks(cmd_file: Path) -> None:
    for block in _fenced_blocks(cmd_file.read_text(encoding="utf-8")):
        assert "$ARGUMENTS" not in block, (
            f"{cmd_file.name}: $ARGUMENTS is interpolated into a shell code block — pass the user's "
            "arguments as separate, individually-quoted argv items instead (P0-1)."
        )


def test_at_least_one_command_scanned() -> None:
    """Guard against the glob silently matching nothing (which would make the scan vacuous)."""
    assert list(COMMANDS_DIR.glob("*.md"))
