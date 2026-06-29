#!/usr/bin/env python3
"""Fail if any MCP server in ``catalog/mcp.yaml`` is unpinned or floats on ``@latest``.

The default run is **offline + deterministic** — a CI gate. Each ``stdio`` server launched via ``npx``
(npm) or ``uvx`` (PyPI) must name an exact version; a missing version or ``@latest`` is an error.
Hosted ``type: http`` servers and user-installed binaries (``wassette``/``repowise`` — no package
spec in args) have nothing to pin and are skipped.

``--check-latest`` adds an **online, advisory** probe of the npm / PyPI registry for newer versions.
It never fails the build (network errors degrade to "unknown"); the scheduled freshness workflow uses
it to surface pins that have fallen behind upstream.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import quote
from urllib.request import urlopen

import yaml

ROOT = Path(__file__).resolve().parents[1]
MCP = ROOT / "catalog" / "mcp.yaml"


def _load_doc(path: str | Path | None = None) -> dict:
    return yaml.safe_load(Path(path or MCP).read_text(encoding="utf-8")) or {}


def _npx_spec(args: list) -> tuple[str, str, str] | None:
    """Return ``(ecosystem, package, version)`` for an npx package arg, or None if not resolvable."""
    for raw in args:
        tok = str(raw)
        if not tok or tok.startswith("-") or tok.startswith("${"):
            continue
        if tok.startswith(("http://", "https://", "file://")):
            return None
        if tok.startswith("@"):  # scoped: @scope/name[@version]
            at = tok.rfind("@")
            if at > 0:
                return ("npm", tok[:at], tok[at + 1 :])
            return ("npm", tok, "")
        name, sep, ver = tok.partition("@")
        return ("npm", name, ver if sep else "")
    return None


def _uvx_spec(args: list) -> tuple[str, str, str] | None:
    """Return ``(ecosystem, package, version)`` for a uvx ``--from spec`` (or first token)."""
    toks = [str(a) for a in args]
    if "--from" in toks:
        i = toks.index("--from")
        if i + 1 < len(toks):
            name, sep, ver = toks[i + 1].partition("==")
            return ("pypi", name, ver if sep else "")
    for tok in toks:
        if not tok or tok.startswith("-") or tok.startswith("${"):
            continue
        name, sep, ver = tok.partition("==")
        return ("pypi", name, ver if sep else "")
    return None


def collect_specs(doc: dict | None = None) -> list[tuple[str, str, str, str]]:
    """Yield ``(server_id, ecosystem, package, version)`` for every pinnable MCP server."""
    if doc is None:
        doc = _load_doc()
    out: list[tuple[str, str, str, str]] = []
    for sid, entry in (doc.get("servers") or {}).items():
        cfg = (entry or {}).get("config") or {}
        if cfg.get("type") != "stdio":
            continue  # hosted http endpoints have no version to pin
        args = cfg.get("args") or []
        if cfg.get("command") == "npx":
            spec = _npx_spec(args)
        elif cfg.get("command") == "uvx":
            spec = _uvx_spec(args)
        else:
            spec = None  # user-installed binary (wassette/repowise/…) — nothing to pin
        if spec:
            out.append((sid, spec[0], spec[1], spec[2]))
    return out


def check_pins(doc: dict | None = None) -> list[tuple[str, str, str, str]]:
    """Return the list of servers that are unpinned or float on ``@latest`` ([] == all good)."""
    bad = []
    for sid, eco, pkg, ver in collect_specs(doc):
        if not ver or ver == "latest":
            bad.append((sid, eco, pkg, ver or "(unpinned)"))
    return bad


def _registry_latest(eco: str, pkg: str) -> str | None:
    """Best-effort latest version from npm/PyPI; None on any error (offline, 404, …)."""
    try:
        if eco == "npm":
            url = f"https://registry.npmjs.org/{quote(pkg, safe='@')}/latest"
            with urlopen(url, timeout=10) as resp:  # noqa: S310 - fixed https registry host
                return json.load(resp).get("version")
        if eco == "pypi":
            url = f"https://pypi.org/pypi/{quote(pkg)}/json"
            with urlopen(url, timeout=10) as resp:  # noqa: S310 - fixed https registry host
                return json.load(resp)["info"]["version"]
    except Exception:
        return None
    return None


def _report_latest(specs: list[tuple[str, str, str, str]]) -> None:
    """Advisory: print pins behind the registry latest (never raises)."""
    stale = []
    for sid, eco, pkg, ver in specs:
        latest = _registry_latest(eco, pkg)
        if latest and latest != ver:
            stale.append((sid, pkg, ver, latest))
    if stale:
        print("\nMCP_FRESHNESS: pins behind the registry latest:")
        for sid, pkg, ver, latest in stale:
            print(f"  - {sid}: {pkg} pinned {ver}, latest {latest}")
    else:
        print("\nMCP_FRESHNESS: all pins are at the registry latest")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--check-latest",
        action="store_true",
        help="also probe npm/PyPI for newer versions (online, advisory, never fails)",
    )
    args = ap.parse_args()

    specs = collect_specs()
    bad = check_pins()
    if bad:
        print("FAIL  MCP servers are not pinned to an exact version:")
        for sid, eco, pkg, ver in bad:
            print(f"  - {sid}: {pkg} [{eco}] -> {ver}")
        print(
            "Pin to an exact version (no @latest, no bare package). See catalog/mcp.yaml."
        )
        return 1
    print(
        f"OK    all {len(specs)} pinnable MCP server(s) are pinned to an exact version"
    )

    if args.check_latest:
        _report_latest(specs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
