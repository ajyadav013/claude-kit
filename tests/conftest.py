"""Shared pytest fixtures for the claude-kit test suite.

Tests call the library functions directly (no subprocess) for speed and determinism, using the
bundled payload resolved exactly the way the CLI resolves it (:func:`claude_kit.scaffold.payload_dir`).
Reusable factory helpers live in :mod:`tests._helpers`.
"""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path

import pytest

from claude_kit import scaffold


@pytest.fixture(scope="session")
def payload() -> Path:
    """The bundled payload root (source checkout or wheel ``_payload``)."""
    with ExitStack() as stack:
        yield scaffold.payload_dir(stack)
