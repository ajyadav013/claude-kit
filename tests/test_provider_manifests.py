"""Generated Claude Code/Codex plugin metadata and distribution archive coverage."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

REPO_ROOT = Path(__file__).resolve().parents[1]
CLAUDE_MANIFEST = Path(".claude-plugin/plugin.json")
CLAUDE_MARKETPLACE = Path(".claude-plugin/marketplace.json")
CODEX_PLUGIN_ROOT = Path("providers/codex/claude-kit")
CODEX_MANIFEST = CODEX_PLUGIN_ROOT / ".codex-plugin/plugin.json"
CODEX_MARKETPLACE = Path(".agents/plugins/marketplace.json")
PROVIDER_FILES = (
    CLAUDE_MANIFEST,
    CLAUDE_MARKETPLACE,
    CODEX_MANIFEST,
    CODEX_MARKETPLACE,
)


def _load_generator():
    spec = importlib.util.spec_from_file_location(
        "gen_provider_manifests",
        REPO_ROOT / "scripts" / "gen_provider_manifests.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_json(relative: Path) -> dict:
    return json.loads((REPO_ROOT / relative).read_text(encoding="utf-8"))


def test_committed_provider_manifests_match_the_canonical_generator() -> None:
    generator = _load_generator()
    expected = generator.generated_text(REPO_ROOT)
    assert set(expected) == set(PROVIDER_FILES)
    for relative, content in expected.items():
        assert (REPO_ROOT / relative).read_text(encoding="utf-8") == content
    assert generator.main(["--check"], root=REPO_ROOT) == 0


def test_generator_write_mode_creates_all_provider_files_and_check_detects_drift(
    tmp_path: Path,
) -> None:
    generator = _load_generator()
    (tmp_path / "catalog").mkdir()
    shutil.copy2(REPO_ROOT / "pyproject.toml", tmp_path / "pyproject.toml")
    shutil.copy2(
        REPO_ROOT / "catalog" / "plugin-metadata.yaml",
        tmp_path / "catalog" / "plugin-metadata.yaml",
    )

    assert generator.main([], root=tmp_path) == 0
    assert all((tmp_path / relative).is_file() for relative in PROVIDER_FILES)
    assert generator.main(["--check"], root=tmp_path) == 0

    (tmp_path / CODEX_MANIFEST).write_text("{}\n", encoding="utf-8")
    assert generator.main(["--check"], root=tmp_path) == 1


def test_claude_outputs_preserve_the_existing_manifest_contract() -> None:
    version = _load_generator()._read_version(REPO_ROOT)
    manifest = _load_json(CLAUDE_MANIFEST)
    marketplace = _load_json(CLAUDE_MARKETPLACE)
    entry = marketplace["plugins"][0]

    assert manifest["name"] == entry["name"] == "claude-kit"
    assert manifest["displayName"] == entry["displayName"] == "Claude Kit SDLC"
    assert manifest["version"] == entry["version"] == version
    assert marketplace["name"] == "claude-kit"
    assert entry["source"] == "./"
    assert "Claude Code" in manifest["description"]


def test_codex_manifest_uses_the_native_current_shape() -> None:
    version = _load_generator()._read_version(REPO_ROOT)
    manifest = _load_json(CODEX_MANIFEST)
    interface = manifest["interface"]

    assert manifest["name"] == "claude-kit"
    assert manifest["version"] == version
    assert manifest["skills"] == "./skills/"
    assert (REPO_ROOT / CODEX_PLUGIN_ROOT / manifest["skills"]).is_dir()
    assert "hooks" not in manifest  # hooks/hooks.json is conventionally discovered
    assert {
        "displayName",
        "shortDescription",
        "longDescription",
        "developerName",
        "category",
        "capabilities",
        "websiteURL",
        "defaultPrompt",
    } <= set(interface)
    assert 1 <= len(interface["defaultPrompt"]) <= 3
    assert all(len(prompt) <= 128 for prompt in interface["defaultPrompt"])
    assert "preview" in interface["longDescription"].lower()


def test_codex_repo_marketplace_points_at_the_nested_native_plugin() -> None:
    marketplace = _load_json(CODEX_MARKETPLACE)
    assert marketplace["name"] == "claude-kit"
    assert marketplace["interface"] == {"displayName": "Claude Kit"}
    assert len(marketplace["plugins"]) == 1
    entry = marketplace["plugins"][0]
    assert entry == {
        "name": "claude-kit",
        "source": {
            "source": "local",
            "path": "./providers/codex/claude-kit",
        },
        "policy": {"installation": "AVAILABLE", "authentication": "ON_USE"},
        "category": "Productivity",
    }
    plugin_root = (REPO_ROOT / entry["source"]["path"]).resolve()
    assert (plugin_root / ".codex-plugin/plugin.json").is_file()
    assert not (REPO_ROOT / ".codex-plugin/plugin.json").exists()


def test_wheel_and_sdist_contain_both_provider_surfaces_but_not_dot_codex(
    tmp_path: Path,
) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            "--no-isolation",
            "--wheel",
            "--sdist",
            "--outdir",
            str(tmp_path),
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    wheel = next(tmp_path.glob("*.whl"))
    sdist = next(tmp_path.glob("*.tar.gz"))
    with zipfile.ZipFile(wheel) as archive:
        wheel_names = set(archive.namelist())
    wheel_prefix = PurePosixPath("claude_kit/_payload")
    for relative in PROVIDER_FILES:
        assert str(wheel_prefix / relative.as_posix()) in wheel_names
    assert str(wheel_prefix / "catalog/plugin-metadata.yaml") in wheel_names
    assert str(wheel_prefix / "schemas/plugin-metadata.schema.json") in wheel_names
    assert all(".codex" not in PurePosixPath(name).parts for name in wheel_names)

    with tarfile.open(sdist, "r:gz") as archive:
        sdist_names = set(archive.getnames())
    sdist_root = PurePosixPath(next(iter(sdist_names))).parts[0]
    for relative in PROVIDER_FILES:
        assert str(PurePosixPath(sdist_root) / relative.as_posix()) in sdist_names
    assert all(".codex" not in PurePosixPath(name).parts for name in sdist_names)
