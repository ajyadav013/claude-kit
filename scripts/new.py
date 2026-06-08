#!/usr/bin/env python3
"""Standalone entry point for ``claude-kit new`` from the plugin (no pip install required).

The ``/claude-kit:new`` slash command runs this when the ``claude-kit`` CLI is not on PATH. It adds
the plugin's bundled ``src/`` to ``sys.path`` and delegates to the real CLI; the template payload is
resolved from the plugin root via :func:`claude_kit.scaffold.payload_dir`'s source-checkout
fallback. One implementation, two install channels.
"""

from __future__ import annotations

import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT / "src"))

from claude_kit.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(["new", *sys.argv[1:]]))
