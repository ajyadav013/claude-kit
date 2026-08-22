"""Reproducible distribution archives and isolated native-runtime installation smokes."""

from __future__ import annotations

import configparser
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import venv
import zipfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import pytest
import yaml

try:  # pragma: no cover - Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.9/3.10
    import tomli as tomllib  # type: ignore[no-redef]

REPO_ROOT = Path(__file__).resolve().parents[1]
PAYLOAD_DIRS = (
    "agents",
    "skills",
    "rules",
    "hooks",
    "commands",
    "canonical",
    "templates",
    "catalog",
    "schemas",
    ".claude-plugin",
    "providers",
)
PAYLOAD_FILES = ("AGENTS.md", ".agents/plugins/marketplace.json")
PROVIDER_MANIFESTS = (
    ".claude-plugin/plugin.json",
    ".claude-plugin/marketplace.json",
    "providers/codex/claude-kit/.codex-plugin/plugin.json",
    ".agents/plugins/marketplace.json",
)
CLI_ALIASES = {
    "claude-kit": "claude_kit.cli:main",
    "ckit": "claude_kit.cli:main",
    "claude-sdlc": "claude_kit.cli:main",
}
FORBIDDEN_ARCHIVE_PARTS = frozenset(
    {
        ".cache",
        ".codex",
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "cache",
        "caches",
        "dist",
        "node_modules",
        "tests",
    }
)
_RUN_ISOLATED_SMOKE = os.environ.get("CKIT_RUN_DISTRIBUTION_SMOKE") == "1"
REQUIRED_PR_CHECKS = {
    "claude-plugin-compat",
    "codex-plugin-compat",
    "docs-manifest-drift",
    "provider-payload-drift",
    "runtime-goldens",
    "runtime-unit",
    "runtime-upgrade-matrix",
    "wheel-smoke-both",
    "wheel-smoke-claude",
    "wheel-smoke-codex",
}


@dataclass(frozen=True)
class BuiltDistributions:
    """The first of two byte-identical builds plus both build directories."""

    wheel: Path
    sdist: Path
    first_dir: Path
    second_dir: Path
    source_root: Path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run(
    command: list[str], *, cwd: Path, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, (
        f"command failed ({result.returncode}): {' '.join(command)}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    return result


@pytest.fixture(scope="session")
def built_distributions(tmp_path_factory: pytest.TempPathFactory) -> BuiltDistributions:
    """Build wheel and sdist twice with one fixed reproducibility epoch."""

    base = tmp_path_factory.mktemp("distributions")
    source_root = base / "source"
    source_root.mkdir()
    source_directories = (*PAYLOAD_DIRS, "src", "scripts", "docs")
    source_files = (
        *PAYLOAD_FILES,
        "pyproject.toml",
        "README.md",
        "CHANGELOG.md",
        "CONTRIBUTING.md",
        "LICENSE",
        "CLAUDE.md",
    )
    for relative in source_directories:
        shutil.copytree(REPO_ROOT / relative, source_root / relative)
    for relative in source_files:
        destination = source_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / relative, destination)

    # Poison the staged source with representative local state. Hatch's explicit
    # inventory must keep every one of these paths out of both distributions.
    for relative in (
        ".codex/config.toml",
        ".cache/provider/session.json",
        ".pytest_cache/state",
        ".venv/bin/local-python",
        ".agents/cache/plugin-index.json",
        "node_modules/example/index.js",
        "tests/test_distribution_poison.py",
    ):
        path = source_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("machine-local\n", encoding="utf-8")

    build_env = os.environ.copy()
    build_env.update({"PYTHONHASHSEED": "0", "SOURCE_DATE_EPOCH": "1700000000"})
    outputs: list[tuple[Path, Path, Path]] = []
    for name in ("first", "second"):
        output = base / name
        output.mkdir()
        _run(
            [
                sys.executable,
                "-m",
                "build",
                "--no-isolation",
                "--wheel",
                "--sdist",
                "--outdir",
                str(output),
            ],
            cwd=source_root,
            env=build_env,
        )
        wheel = next(output.glob("*.whl"))
        sdist = next(output.glob("*.tar.gz"))
        outputs.append((output, wheel, sdist))

    first_dir, first_wheel, first_sdist = outputs[0]
    second_dir, second_wheel, second_sdist = outputs[1]
    assert first_wheel.name == second_wheel.name
    assert first_sdist.name == second_sdist.name
    return BuiltDistributions(
        first_wheel,
        first_sdist,
        first_dir,
        second_dir,
        source_root,
    )


def _is_junk(relative: str) -> bool:
    path = PurePosixPath(relative)
    return (
        path.name == ".DS_Store"
        or path.suffix == ".pyc"
        or bool(set(path.parts) & FORBIDDEN_ARCHIVE_PARTS)
    )


def _source_payload_inventory(source_root: Path) -> set[str]:
    inventory = set(PAYLOAD_FILES)
    for directory in PAYLOAD_DIRS:
        for path in sorted((source_root / directory).rglob("*")):
            if path.is_file():
                relative = path.relative_to(source_root).as_posix()
                if not _is_junk(relative):
                    inventory.add(relative)
    return inventory


def _is_payload_relative(relative: str) -> bool:
    if relative in PAYLOAD_FILES:
        return True
    parts = PurePosixPath(relative).parts
    return bool(parts) and parts[0] in PAYLOAD_DIRS


def _wheel_payload_names(
    wheel: Path,
) -> tuple[list[str], Counter[str], dict[str, bytes]]:
    prefix = "claude_kit/_payload/"
    with zipfile.ZipFile(wheel) as archive:
        archive_names = archive.namelist()
        names = [
            name[len(prefix) :]
            for name in archive_names
            if name.startswith(prefix) and not name.endswith("/")
        ]
        content = {
            name[len(prefix) :]: archive.read(name)
            for name in archive_names
            if name.startswith(prefix) and not name.endswith("/")
        }
    return names, Counter(archive_names), content


def _sdist_payload_names(
    sdist: Path,
) -> tuple[list[str], Counter[str], dict[str, bytes], str]:
    with tarfile.open(sdist, "r:gz") as archive:
        members = [member for member in archive.getmembers() if member.isfile()]
        roots = {PurePosixPath(member.name).parts[0] for member in members}
        assert len(roots) == 1
        root = roots.pop()
        selected: list[str] = []
        content: dict[str, bytes] = {}
        for member in members:
            relative = PurePosixPath(member.name).relative_to(root).as_posix()
            if not _is_payload_relative(relative):
                continue
            selected.append(relative)
            handle = archive.extractfile(member)
            assert handle is not None
            content[relative] = handle.read()
        counts = Counter(member.name for member in members)
    return selected, counts, content, root


def _source_package_content(source_root: Path) -> dict[str, bytes]:
    package = source_root / "src/claude_kit"
    return {
        path.relative_to(package).as_posix(): path.read_bytes()
        for path in sorted(package.rglob("*"))
        if path.is_file() and not _is_junk(path.relative_to(source_root).as_posix())
    }


def _wheel_package_content(wheel: Path) -> dict[str, bytes]:
    prefix = "claude_kit/"
    payload_prefix = f"{prefix}_payload/"
    with zipfile.ZipFile(wheel) as archive:
        return {
            name[len(prefix) :]: archive.read(name)
            for name in archive.namelist()
            if name.startswith(prefix)
            and not name.startswith(payload_prefix)
            and not name.endswith("/")
        }


def _sdist_package_content(sdist: Path, root: str) -> dict[str, bytes]:
    prefix = f"{root}/src/claude_kit/"
    with tarfile.open(sdist, "r:gz") as archive:
        content: dict[str, bytes] = {}
        for member in archive.getmembers():
            if not member.isfile() or not member.name.startswith(prefix):
                continue
            handle = archive.extractfile(member)
            assert handle is not None
            content[member.name[len(prefix) :]] = handle.read()
    return content


def _assert_archive_names_are_portable(names: list[str]) -> None:
    for raw in names:
        path = PurePosixPath(raw)
        assert not path.is_absolute(), raw
        assert not (set(path.parts) & FORBIDDEN_ARCHIVE_PARTS), raw
        assert path.name != ".DS_Store", raw
        assert path.suffix != ".pyc", raw


def test_fixed_epoch_builds_are_byte_reproducible(
    built_distributions: BuiltDistributions,
) -> None:
    second_wheel = built_distributions.second_dir / built_distributions.wheel.name
    second_sdist = built_distributions.second_dir / built_distributions.sdist.name
    assert _sha256(built_distributions.wheel) == _sha256(second_wheel)
    assert _sha256(built_distributions.sdist) == _sha256(second_sdist)


def test_archives_match_source_payload_once_and_exclude_machine_state(
    built_distributions: BuiltDistributions,
) -> None:
    expected = _source_payload_inventory(built_distributions.source_root)
    wheel_names, wheel_counts, wheel_content = _wheel_payload_names(
        built_distributions.wheel
    )
    sdist_names, sdist_counts, sdist_content, sdist_root = _sdist_payload_names(
        built_distributions.sdist
    )

    expected_counts = Counter({name: 1 for name in expected})
    assert Counter(wheel_names) == expected_counts
    assert Counter(sdist_names) == expected_counts
    assert wheel_content == sdist_content
    source_package = _source_package_content(built_distributions.source_root)
    assert _wheel_package_content(built_distributions.wheel) == source_package
    assert (
        _sdist_package_content(built_distributions.sdist, sdist_root) == source_package
    )
    assert wheel_names.count("AGENTS.md") == 1
    assert sdist_names.count("AGENTS.md") == 1
    assert (
        sum(
            count for name, count in wheel_counts.items() if name.endswith("/AGENTS.md")
        )
        == 1
    )
    assert (
        sum(
            count for name, count in sdist_counts.items() if name.endswith("/AGENTS.md")
        )
        == 1
    )
    for relative in PROVIDER_MANIFESTS:
        assert wheel_names.count(relative) == 1
        assert sdist_names.count(relative) == 1
        assert wheel_counts[f"claude_kit/_payload/{relative}"] == 1
        assert sdist_counts[f"{sdist_root}/{relative}"] == 1
        assert (
            sum(
                count
                for name, count in wheel_counts.items()
                if name.endswith(f"/{relative}")
            )
            == 1
        )
        assert (
            sum(
                count
                for name, count in sdist_counts.items()
                if name.endswith(f"/{relative}")
            )
            == 1
        )

    with zipfile.ZipFile(built_distributions.wheel) as archive:
        _assert_archive_names_are_portable(archive.namelist())
    with tarfile.open(built_distributions.sdist, "r:gz") as archive:
        _assert_archive_names_are_portable(archive.getnames())

    assert {name for name in wheel_names if name.startswith(".agents/")} == {
        ".agents/plugins/marketplace.json"
    }
    assert {name for name in sdist_names if name.startswith(".agents/")} == {
        ".agents/plugins/marketplace.json"
    }
    contributor_template = "canonical/contributor-guide.md.tmpl"
    assert wheel_names.count(contributor_template) == 1
    assert sdist_names.count(contributor_template) == 1

    contributor_generator = "scripts/gen_contributor_guides.py"
    with zipfile.ZipFile(built_distributions.wheel) as archive:
        assert not any(
            name.endswith(f"/{contributor_generator}") for name in archive.namelist()
        )
    with tarfile.open(built_distributions.sdist, "r:gz") as archive:
        generator_member = f"{sdist_root}/{contributor_generator}"
        assert archive.getnames().count(generator_member) == 1
        handle = archive.extractfile(generator_member)
        assert handle is not None
        assert (
            handle.read()
            == (built_distributions.source_root / contributor_generator).read_bytes()
        )


def _read_version_from_init(content: str) -> str:
    marker = '__version__ = "'
    line = next(line for line in content.splitlines() if line.startswith(marker))
    return line[len(marker) :].rstrip('"')


def test_source_wheel_sdist_versions_and_cli_aliases_match(
    built_distributions: BuiltDistributions,
) -> None:
    source_project = tomllib.loads(
        (built_distributions.source_root / "pyproject.toml").read_text()
    )
    expected_version = source_project["project"]["version"]
    assert (
        _read_version_from_init(
            (built_distributions.source_root / "src/claude_kit/__init__.py").read_text()
        )
        == expected_version
    )

    with zipfile.ZipFile(built_distributions.wheel) as archive:
        names = archive.namelist()
        metadata_name = next(
            name for name in names if name.endswith(".dist-info/METADATA")
        )
        entry_points_name = next(
            name for name in names if name.endswith(".dist-info/entry_points.txt")
        )
        metadata = archive.read(metadata_name).decode()
        wheel_init = archive.read("claude_kit/__init__.py").decode()
        wheel_claude = json.loads(
            archive.read("claude_kit/_payload/.claude-plugin/plugin.json")
        )
        wheel_claude_market = json.loads(
            archive.read("claude_kit/_payload/.claude-plugin/marketplace.json")
        )
        wheel_codex = json.loads(
            archive.read(
                "claude_kit/_payload/providers/codex/claude-kit/"
                ".codex-plugin/plugin.json"
            )
        )
        entry_points = archive.read(entry_points_name).decode()

    assert f"Version: {expected_version}\n" in metadata
    assert _read_version_from_init(wheel_init) == expected_version
    assert wheel_claude["version"] == expected_version
    assert wheel_claude_market["plugins"][0]["version"] == expected_version
    assert wheel_codex["version"] == expected_version

    parser = configparser.ConfigParser()
    parser.optionxform = str
    parser.read_string(entry_points)
    assert dict(parser["console_scripts"]) == CLI_ALIASES

    with tarfile.open(built_distributions.sdist, "r:gz") as archive:
        members = [member for member in archive.getmembers() if member.isfile()]
        root = PurePosixPath(members[0].name).parts[0]

        def read(relative: str) -> str:
            handle = archive.extractfile(f"{root}/{relative}")
            assert handle is not None
            return handle.read().decode()

        sdist_project = tomllib.loads(read("pyproject.toml"))
        sdist_init = read("src/claude_kit/__init__.py")
        sdist_claude = json.loads(read(".claude-plugin/plugin.json"))
        sdist_codex = json.loads(
            read("providers/codex/claude-kit/.codex-plugin/plugin.json")
        )

    assert sdist_project["project"]["version"] == expected_version
    assert _read_version_from_init(sdist_init) == expected_version
    assert sdist_claude["version"] == expected_version
    assert sdist_codex["version"] == expected_version
    assert sdist_project["project"]["scripts"] == CLI_ALIASES


def test_ci_exposes_required_runtime_conformance_checks() -> None:
    workflow = yaml.safe_load((REPO_ROOT / ".github/workflows/ci.yml").read_text())
    jobs = workflow["jobs"]
    check_names = {job.get("name", job_id) for job_id, job in jobs.items()}
    check_names.update(
        item["job_name"]
        for item in jobs["wheel-smoke"]["strategy"]["matrix"]["include"]
    )
    assert REQUIRED_PR_CHECKS <= check_names


def _isolated_env(environment: Path) -> tuple[Path, dict[str, str]]:
    builder = venv.EnvBuilder(with_pip=True)
    builder.create(environment)
    scripts = environment / ("Scripts" if os.name == "nt" else "bin")
    clean = os.environ.copy()
    for key in (
        "CLAUDE_KIT_EXPERIMENTAL",
        "CKIT_EXPERIMENTAL",
        "PYTHONHOME",
        "PYTHONPATH",
        "VIRTUAL_ENV",
    ):
        clean.pop(key, None)
    clean.update(
        {
            "PATH": str(scripts) + os.pathsep + clean.get("PATH", ""),
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        }
    )
    return scripts, clean


@pytest.mark.skipif(
    not _RUN_ISOLATED_SMOKE,
    reason="set CKIT_RUN_DISTRIBUTION_SMOKE=1 for the isolated artifact smoke",
)
@pytest.mark.parametrize("artifact_kind", ["wheel", "sdist"])
def test_isolated_distribution_runs_all_explicit_runtime_modes(
    artifact_kind: str,
    built_distributions: BuiltDistributions,
    tmp_path: Path,
) -> None:
    artifact = getattr(built_distributions, artifact_kind)
    environment = tmp_path / f"venv-{artifact_kind}"
    scripts, base_env = _isolated_env(environment)
    python = scripts / ("python.exe" if os.name == "nt" else "python")
    pip = [str(python), "-m", "pip"]
    _run(
        [
            *pip,
            "install",
            str(artifact),
        ],
        cwd=tmp_path,
        env=base_env,
    )

    probe = _run(
        [
            str(python),
            "-c",
            (
                "import json, pathlib, sys; from contextlib import ExitStack; "
                "import claude_kit; from claude_kit.scaffold import payload_dir; "
                "s=ExitStack(); p=payload_dir(s); "
                "print(json.dumps({'module': claude_kit.__file__, "
                "'payload': str(p), 'version': claude_kit.__version__, "
                "'prefix': sys.prefix})); s.close()"
            ),
        ],
        cwd=tmp_path,
        env=base_env,
    )
    installed = json.loads(probe.stdout)
    assert Path(installed["module"]).is_relative_to(environment)
    assert Path(installed["payload"]).is_relative_to(environment)
    assert (
        installed["version"]
        == tomllib.loads(
            (built_distributions.source_root / "pyproject.toml").read_text()
        )["project"]["version"]
    )

    aliases = {
        name: scripts / (f"{name}.exe" if os.name == "nt" else name)
        for name in CLI_ALIASES
    }
    for executable in aliases.values():
        version = _run([str(executable), "--version"], cwd=tmp_path, env=base_env)
        assert installed["version"] in version.stdout

    runtime_alias = {
        "claude": aliases["claude-kit"],
        "codex": aliases["ckit"],
        "both": aliases["claude-sdlc"],
    }
    for runtime, executable in runtime_alias.items():
        target = tmp_path / f"{artifact_kind}-{runtime}"
        runtime_env = base_env.copy()
        if runtime in {"codex", "both"}:
            runtime_env["CKIT_EXPERIMENTAL"] = "1"
        _run(
            [
                str(executable),
                "init",
                str(target),
                "--defaults",
                "--runtime",
                runtime,
            ],
            cwd=tmp_path,
            env=runtime_env,
        )
        _run(
            [str(aliases["ckit"]), "validate", "--strict", str(target)],
            cwd=tmp_path,
            env=runtime_env,
        )
        manifest = json.loads((target / ".ckit/config/init-options.json").read_text())
        expected_runtimes = ["claude", "codex"] if runtime == "both" else [runtime]
        assert manifest["runtimes"] == expected_runtimes
        assert (target / ".claude").is_dir() is (runtime in {"claude", "both"})
        assert (target / ".codex").is_dir() is (runtime in {"codex", "both"})
        assert (target / ".agents").is_dir() is (runtime in {"codex", "both"})
        assert (target / "AGENTS.md").is_file() is (runtime in {"codex", "both"})
