#!/usr/bin/env python3
"""Generate Claude Code and Codex plugin manifests from one catalog record.

``catalog/plugin-metadata.yaml`` owns provider-neutral identity plus the few provider-specific
presentation fields. The package version remains canonical in ``pyproject.toml``. Generated JSON
must never be edited by hand; use this script's write mode or ``--check`` drift guard.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised by the Python 3.9/3.10 CI matrix
    import tomli as tomllib

ROOT = Path(__file__).resolve().parent.parent
TARGETS = (
    Path(".claude-plugin/plugin.json"),
    Path(".claude-plugin/marketplace.json"),
    Path("providers/codex/claude-kit/.codex-plugin/plugin.json"),
    Path(".agents/plugins/marketplace.json"),
)


def _read_metadata(root: Path) -> dict[str, Any]:
    path = root / "catalog" / "plugin-metadata.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"{path} must contain a YAML object")
    return document


def _read_version(root: Path) -> str:
    document = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    version = document.get("project", {}).get("version")
    if not isinstance(version, str) or not version:
        raise ValueError("pyproject.toml must declare a non-empty project.version")
    return version


def _render(document: dict[str, Any]) -> str:
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def generated_documents(root: Path = ROOT) -> dict[Path, dict[str, Any]]:
    """Return all provider manifest documents keyed by their repository-relative path."""
    metadata = _read_metadata(root)
    version = _read_version(root)
    identity = metadata["identity"]
    author = identity["author"]
    claude = metadata["providers"]["claude"]
    codex = metadata["providers"]["codex"]
    claude_market = claude["marketplace"]
    codex_interface = codex["interface"]
    codex_market = codex["marketplace"]

    claude_manifest = {
        "name": identity["name"],
        "displayName": identity["display_name"],
        "version": version,
        "description": claude["manifest_description"],
        "author": author,
        "homepage": identity["homepage"],
        "repository": identity["repository"],
        "license": identity["license"],
        "keywords": identity["keywords"],
    }
    claude_marketplace = {
        "name": claude_market["name"],
        "description": claude_market["description"],
        "owner": author,
        "plugins": [
            {
                "name": identity["name"],
                "displayName": identity["display_name"],
                "source": "./",
                "description": claude_market["plugin_description"],
                "version": version,
                "license": identity["license"],
                "keywords": claude_market["keywords"],
            }
        ],
    }
    codex_manifest = {
        "name": identity["name"],
        "version": version,
        "description": identity["description"],
        "author": author,
        "homepage": identity["homepage"],
        "repository": identity["repository"],
        "license": identity["license"],
        "keywords": identity["keywords"],
        "skills": codex["skills"],
        "interface": {
            "displayName": codex_interface["display_name"],
            "shortDescription": codex_interface["short_description"],
            "longDescription": codex_interface["long_description"],
            "developerName": codex_interface["developer_name"],
            "category": codex_interface["category"],
            "capabilities": codex_interface["capabilities"],
            "websiteURL": codex_interface["website_url"],
            "defaultPrompt": codex_interface["default_prompts"],
        },
    }
    codex_marketplace = {
        "name": codex_market["name"],
        "interface": {"displayName": codex_market["display_name"]},
        "plugins": [
            {
                "name": identity["name"],
                "source": codex_market["source"],
                "policy": codex_market["policy"],
                "category": codex_market["category"],
            }
        ],
    }
    return {
        TARGETS[0]: claude_manifest,
        TARGETS[1]: claude_marketplace,
        TARGETS[2]: codex_manifest,
        TARGETS[3]: codex_marketplace,
    }


def generated_text(root: Path = ROOT) -> dict[Path, str]:
    """Return canonical serialized JSON for every generated file."""
    return {path: _render(doc) for path, doc in generated_documents(root).items()}


def main(argv: list[str] | None = None, *, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="report generated-file drift without writing",
    )
    args = parser.parse_args(argv)

    drifted: list[Path] = []
    for relative, expected in generated_text(root).items():
        target = root / relative
        if args.check:
            if not target.is_file() or target.read_text(encoding="utf-8") != expected:
                drifted.append(relative)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(expected, encoding="utf-8")
        print(f"generated {relative}")

    if drifted:
        print(
            "provider manifests are out of date: "
            + ", ".join(str(path) for path in drifted),
            file=sys.stderr,
        )
        print("run `python scripts/gen_provider_manifests.py`", file=sys.stderr)
        return 1
    if args.check:
        print("provider manifests are in sync")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
