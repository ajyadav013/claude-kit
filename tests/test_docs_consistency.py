"""The repo's docs/versions/counts stay in sync — and the checker that proves it actually bites."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPT = (
    Path(__file__).resolve().parent.parent / "scripts" / "check_docs_consistency.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("check_docs_consistency", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_docs_are_consistent():
    """Version strings, component counts, and profile→gate tables all agree across the repo."""
    errors = _load().run()
    assert errors == [], "docs consistency drift:\n  " + "\n  ".join(errors)


def test_checker_detects_version_drift(monkeypatch):
    """Guard against a vacuously-passing checker: a planted bad version must be reported."""
    mod = _load()
    real_read = mod._read

    def fake_read(rel: str) -> str:
        if rel == "SECURITY.md":
            return "claude-kit is pre-1.0 ... (currently **9.9.9**) receives security fixes."
        return real_read(rel)

    monkeypatch.setattr(mod, "_read", fake_read)
    errors = mod.check_versions()
    assert any("SECURITY.md" in e for e in errors)


def test_checker_detects_count_drift(monkeypatch):
    """A planted wrong component count must be reported."""
    mod = _load()
    real_actuals = mod._actuals

    monkeypatch.setattr(mod, "_actuals", lambda: {**real_actuals(), "agents": 999})
    errors = mod.check_counts()
    assert any("agents" in e for e in errors)


def test_checker_detects_duplicate_gate_tables(monkeypatch):
    """A second (stale) gate table must be flagged, not silently shadowed by a later correct one."""
    mod = _load()
    real_read = mod._read
    stale = (
        "| **lean** | stale-gate |\n"
        "| **standard** | stale-gate |\n"
        "| **enterprise** | stale-gate |\n\n"
    )

    def fake_read(rel: str) -> str:
        if rel == "README.md":
            return stale + real_read(rel)  # a stale table ahead of the real one
        return real_read(rel)

    monkeypatch.setattr(mod, "_read", fake_read)
    errors = mod.check_profile_gates()
    assert any("duplicate gate table" in e for e in errors), errors
