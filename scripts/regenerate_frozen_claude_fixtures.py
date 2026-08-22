#!/usr/bin/env python3
"""Regenerate the immutable Claude-only 0.83 characterization fixtures.

The generator deliberately runs the installer imported from a ``git archive`` of
``FROZEN_SOURCE_COMMIT``.  It never imports the checkout's ``claude_kit`` package, so a
provider refactor in the working tree cannot silently rewrite the historical baseline.

Regeneration is an explicit review action::

    python scripts/regenerate_frozen_claude_fixtures.py \
      --source-commit 04161917bd3c1aef270f9979e5abeabe3cd755e6 --write

Use the same command with ``--check`` to compare a fresh characterization with the checked-in
fixtures.  The full commit id is required; aliases, branches, and abbreviated ids are refused.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any

FROZEN_SOURCE_COMMIT = "04161917bd3c1aef270f9979e5abeabe3cd755e6"
FROZEN_SOURCE_TREE = "02945cbfdb7306a992d1da5fa83eb0b889e4ff75"
FROZEN_KIT_VERSION = "0.83.0"
FIXTURE_SCHEMA_VERSION = 1

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "frozen-claude-0.83"
GENERATED_ROOT = FIXTURE_ROOT / "generated"

# Each profile, shipped backend/database lane, and scope class is represented across the matrix.
# ``detect_commands`` is false because characterization must not depend on files beside the target.
CASES: tuple[dict[str, Any], ...] = (
    {
        "id": "lean_individual_go",
        "overrides": {
            "frontend_framework": "none",
            "frontend_language": "typescript",
            "backend_language": "go",
            "backend_framework": "net-http",
            "database": "none",
            "profile": "lean",
            "capture_mode": "off",
            "mcp": [],
            "scope": "individual",
            "teams": [],
            "autonomy": "assisted",
            "review_strictness": "standard",
            "org_packs": False,
            "detect_commands": False,
        },
    },
    {
        "id": "standard_team_react_fastapi",
        "overrides": {
            "frontend_framework": "react",
            "frontend_language": "typescript",
            "backend_language": "python",
            "backend_framework": "fastapi",
            "database": "postgres",
            "profile": "standard",
            "capture_mode": "session-end-catchup",
            "mcp": ["docs"],
            "scope": "team",
            "teams": [],
            "autonomy": "assisted",
            "review_strictness": "standard",
            "org_packs": False,
            "detect_commands": False,
        },
    },
    {
        "id": "enterprise_organization_django_mongodb",
        "overrides": {
            "frontend_framework": "none",
            "frontend_language": "typescript",
            "backend_language": "python",
            "backend_framework": "django",
            "database": "mongodb",
            "profile": "enterprise",
            "capture_mode": "per-task",
            "mcp": ["github", "mongodb", "playwright"],
            "scope": "organization",
            "teams": ["engineering", "security"],
            "autonomy": "enterprise-controlled",
            "review_strictness": "regulated",
            "org_packs": True,
            "detect_commands": False,
        },
    },
)


def _canonical_json(value: Any) -> bytes:
    return (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    ).encode()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical_json(value))


def _run_git(*args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.stdout.strip()


def _verify_source_pin(requested: str) -> None:
    if requested != FROZEN_SOURCE_COMMIT:
        raise SystemExit(
            "refusing regeneration: --source-commit must be the exact frozen commit "
            f"{FROZEN_SOURCE_COMMIT}"
        )
    try:
        resolved = _run_git("rev-parse", f"{requested}^{{commit}}")
        tree = _run_git("rev-parse", f"{requested}^{{tree}}")
    except (OSError, subprocess.SubprocessError) as exc:
        raise SystemExit(
            "the frozen source commit is unavailable in this checkout; fetch history before "
            f"regenerating ({exc})"
        ) from exc
    if resolved != FROZEN_SOURCE_COMMIT or tree != FROZEN_SOURCE_TREE:
        raise SystemExit(
            "refusing regeneration: frozen commit/tree identity does not match the reviewed pin"
        )


def _extract_frozen_source(destination: Path) -> None:
    archive = destination.parent / "frozen-source.tar"
    subprocess.run(
        [
            "git",
            "-C",
            str(REPO_ROOT),
            "archive",
            "--format=tar",
            f"--output={archive}",
            FROZEN_SOURCE_COMMIT,
        ],
        check=True,
        timeout=60,
    )
    destination.mkdir(parents=True)
    root = destination.resolve()
    with tarfile.open(archive, mode="r:") as bundle:
        members = bundle.getmembers()
        for member in members:
            relative = PurePosixPath(member.name)
            if relative.is_absolute() or ".." in relative.parts:
                raise RuntimeError(
                    f"unsafe path in frozen git archive: {member.name!r}"
                )
            if member.issym() or member.islnk():
                raise RuntimeError(
                    f"unexpected link in frozen git archive: {member.name!r}"
                )
            extracted = (root / Path(*relative.parts)).resolve()
            if extracted != root and root not in extracted.parents:
                raise RuntimeError(
                    f"archive path escapes extraction root: {member.name!r}"
                )
        bundle.extractall(root, members=members)  # noqa: S202 -- all members checked above


def _assert_frozen_import(module: Any, source_root: Path) -> None:
    module_path = Path(module.__file__).resolve()
    source = source_root.resolve()
    if module_path != source and source not in module_path.parents:
        raise RuntimeError(
            f"refusing mixed-source characterization: {module.__name__} came from {module_path}"
        )


def _frontmatter(path: Path, project_root: Path) -> dict[str, Any]:
    import yaml

    data = path.read_bytes()
    if not data.startswith(b"---\n"):
        raise RuntimeError(f"expected YAML frontmatter in {path}")
    closing = data.find(b"\n---\n", 4)
    if closing < 0:
        raise RuntimeError(f"unterminated YAML frontmatter in {path}")
    raw = data[4:closing]
    body = data[closing + len(b"\n---\n") :]
    metadata = yaml.safe_load(raw.decode("utf-8"))
    if not isinstance(metadata, dict):
        raise RuntimeError(f"frontmatter is not a mapping in {path}")
    return {
        "path": path.relative_to(project_root).as_posix(),
        "metadata": metadata,
        "frontmatter_sha256": _sha256(raw),
        "body_sha256": _sha256(body),
    }


def _installed_files(project_root: Path) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    candidates = sorted(
        project_root.rglob("*"),
        key=lambda path: path.relative_to(project_root).as_posix(),
    )
    for path in candidates:
        if not path.is_file():
            continue
        data = path.read_bytes()
        files.append(
            {
                "path": path.relative_to(project_root).as_posix(),
                "sha256": _sha256(data),
                "mode": f"{stat.S_IMODE(path.stat().st_mode):04o}",
                "size": len(data),
            }
        )
    return files


def _case_document(project_root: Path, plan: Any) -> dict[str, Any]:
    installed = _installed_files(project_root)
    installed_paths = {entry["path"] for entry in installed}
    init_path = project_root / ".claude" / "config" / "init-options.json"
    init_options = json.loads(init_path.read_text(encoding="utf-8"))
    records = init_options["files"]
    record_paths = {record["path"] for record in records}
    agents = [
        _frontmatter(path, project_root)
        for path in sorted(
            (project_root / ".claude" / "agents").glob("*.md"),
            key=lambda path: path.relative_to(project_root).as_posix(),
        )
    ]
    skills = [
        _frontmatter(path, project_root)
        for path in sorted(
            (project_root / ".claude" / "skills").glob("*/SKILL.md"),
            key=lambda path: path.relative_to(project_root).as_posix(),
        )
    ]
    settings = json.loads(
        (project_root / ".claude" / "settings.json").read_text(encoding="utf-8")
    )
    return {
        "fixture_schema_version": FIXTURE_SCHEMA_VERSION,
        "source": {
            "commit": FROZEN_SOURCE_COMMIT,
            "tree": FROZEN_SOURCE_TREE,
            "claude_kit_version": FROZEN_KIT_VERSION,
        },
        "selection": plan.selection.to_dict(),
        "resolved_plan": {
            "agents": plan.agents,
            "skills": plan.skills,
            "overlay_rules": plan.overlay_rules,
            "overlay_agents": plan.overlay_agents,
            "hooks": plan.hooks,
        },
        "installed_files": installed,
        "agent_frontmatter": agents,
        "skill_metadata": skills,
        "hook_settings": settings,
        "gate_policy": {
            "ordered_gates": plan.gates,
            "definition_digest": plan.gate_definition_digest,
            "definitions": [
                {"gate": gate, **plan.gate_definitions[gate].to_dict()}
                for gate in plan.gates
            ],
        },
        "init_options": {
            "schema_version": init_options["schema_version"],
            "claude_kit_version": init_options["claude_kit_version"],
            "selection": init_options["selection"],
            "record_count": len(records),
            "record_digest": _sha256(_canonical_json(records)),
            "owner_counts": dict(sorted(Counter(r["owner"] for r in records).items())),
            "installed_but_unrecorded": sorted(installed_paths - record_paths),
        },
    }


def _legacy_state() -> dict[str, Any]:
    # Schema v1 is the portable, explicitly supported migration input in 0.83.  Unlike schema v2 it
    # has no machine-derived absolute repository_root, which keeps this fixture checkout-neutral.
    return {
        "schema": 1,
        "task": "Frozen Claude 0.83 migration characterization",
        "profile": "standard",
        "scope": "team",
        "mode": "B",
        "stage": "spec-complete",
        "next": "resolve gate spec-complete",
        "lanes": {},
        "open_findings": {
            "critical": 0,
            "high": 0,
            "medium": 0,
            "low": 0,
            "cosmetic": 0,
        },
        "gate_evidence": {},
        "last_gate_passed": None,
        "gate_history": [],
    }


def _copy_legacy_fixture(
    standard_target: Path, output_root: Path, pipeline_module: Any
) -> None:
    project = output_root / "legacy-0.83" / "project"
    sources = (
        ".claude/config/init-options.json",
        ".claude/config/stack-catalog.snapshot.yaml",
        ".claude/state/.gitkeep",
    )
    for relative in sources:
        source = standard_target / relative
        destination = project / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
        destination.chmod(stat.S_IMODE(source.stat().st_mode))
    state_path = project / ".claude" / "state" / "pipeline-snapshot.json"
    _write_json(state_path, _legacy_state())
    state_path.chmod(0o644)
    valid, messages = pipeline_module.validate(project, strict=True)
    if not valid:
        raise RuntimeError(
            "portable legacy state is not accepted by the frozen 0.83 runtime: "
            + "; ".join(messages)
        )

    files = _installed_files(project)
    _write_json(
        output_root / "legacy-0.83" / "manifest.json",
        {
            "fixture_schema_version": FIXTURE_SCHEMA_VERSION,
            "source_commit": FROZEN_SOURCE_COMMIT,
            "claude_kit_version": FROZEN_KIT_VERSION,
            "based_on_case": "standard_team_react_fastapi",
            "state_root": ".claude",
            "pipeline_state_schema": 1,
            "files": files,
        },
    )


def _worker(source_root: Path, output_root: Path) -> None:
    if any(
        name == "claude_kit" or name.startswith("claude_kit.") for name in sys.modules
    ):
        raise RuntimeError(
            "claude_kit was imported before the frozen source path was installed"
        )
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(source_root / "src"))

    import claude_kit
    from claude_kit import catalog, pipeline, render, scaffold

    for module in (claude_kit, catalog, pipeline, render, scaffold):
        _assert_frozen_import(module, source_root)
    if claude_kit.__version__ != FROZEN_KIT_VERSION:
        raise RuntimeError(
            f"frozen source reported unexpected version {claude_kit.__version__!r}"
        )

    output_root.mkdir(parents=True)
    old_umask = os.umask(0o022)
    try:
        with tempfile.TemporaryDirectory(prefix="frozen-claude-installs-") as tmp:
            # macOS spells the trusted temp root through /var -> /private/var. The frozen
            # secure-filesystem implementation intentionally rejects the symlink spelling.
            installs = Path(tmp).resolve()
            targets: dict[str, Path] = {}
            case_summaries: list[dict[str, Any]] = []
            for case in CASES:
                selection = catalog.defaults(source_root)
                for key, value in case["overrides"].items():
                    setattr(selection, key, value)
                plan = catalog.resolve(source_root, selection)
                plan.context["project_name"] = case["id"]
                target = installs / case["id"]
                scaffold.install_sdlc(
                    source_root,
                    target,
                    plan,
                    force=False,
                    detect_target=target,
                )
                targets[case["id"]] = target
                document = _case_document(target, plan)
                case_path = output_root / "cases" / f"{case['id']}.json"
                _write_json(case_path, document)
                case_summaries.append(
                    {
                        "id": case["id"],
                        "path": case_path.relative_to(output_root).as_posix(),
                        "profile": selection.profile,
                        "scope": selection.scope,
                        "installed_file_count": len(document["installed_files"]),
                        "agent_count": len(document["agent_frontmatter"]),
                        "skill_count": len(document["skill_metadata"]),
                    }
                )
            _copy_legacy_fixture(
                targets["standard_team_react_fastapi"], output_root, pipeline
            )

        artifacts = []
        for path in sorted(
            output_root.rglob("*"),
            key=lambda path: path.relative_to(output_root).as_posix(),
        ):
            if not path.is_file() or path.name == "metadata.json":
                continue
            data = path.read_bytes()
            artifacts.append(
                {
                    "path": path.relative_to(output_root).as_posix(),
                    "sha256": _sha256(data),
                    "size": len(data),
                }
            )
        _write_json(
            output_root / "metadata.json",
            {
                "fixture_schema_version": FIXTURE_SCHEMA_VERSION,
                "source": {
                    "commit": FROZEN_SOURCE_COMMIT,
                    "tree": FROZEN_SOURCE_TREE,
                    "claude_kit_version": FROZEN_KIT_VERSION,
                },
                "generator": "scripts/regenerate_frozen_claude_fixtures.py",
                "cases": case_summaries,
                "artifacts": artifacts,
            },
        )
    finally:
        os.umask(old_umask)


def _files(root: Path) -> dict[str, bytes]:
    if not root.is_dir():
        return {}
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(
            root.rglob("*"), key=lambda path: path.relative_to(root).as_posix()
        )
        if path.is_file()
    }


def _check(candidate: Path) -> bool:
    expected = _files(GENERATED_ROOT)
    actual = _files(candidate)
    if expected == actual:
        print(f"frozen Claude fixtures match {FROZEN_SOURCE_COMMIT}")
        return True
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    changed = sorted(
        path
        for path in expected.keys() & actual.keys()
        if expected[path] != actual[path]
    )
    if missing:
        print("missing generated files: " + ", ".join(missing), file=sys.stderr)
    if extra:
        print("unexpected generated files: " + ", ".join(extra), file=sys.stderr)
    for relative in changed:
        print(f"changed generated file: {relative}", file=sys.stderr)
        try:
            before = expected[relative].decode("utf-8").splitlines()
            after = actual[relative].decode("utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        diff = difflib.unified_diff(
            before,
            after,
            fromfile=f"checked-in/{relative}",
            tofile=f"regenerated/{relative}",
            lineterm="",
            n=2,
        )
        for line in list(diff)[:80]:
            print(line, file=sys.stderr)
    return False


def _generate_in_subprocess(source_root: Path, output_root: Path) -> None:
    environment = os.environ.copy()
    environment.update(
        {
            "PYTHONPATH": str(source_root / "src"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONHASHSEED": "0",
            "TZ": "UTC",
        }
    )
    subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--_worker-source",
            str(source_root),
            "--_worker-output",
            str(output_root),
        ],
        cwd=source_root,
        env=environment,
        check=True,
        timeout=300,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-commit")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--write", action="store_true")
    action.add_argument("--check", action="store_true")
    parser.add_argument("--_worker-source", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--_worker-output", type=Path, help=argparse.SUPPRESS)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args._worker_source or args._worker_output:
        if not (args._worker_source and args._worker_output):
            raise SystemExit("internal worker requires source and output")
        _worker(args._worker_source, args._worker_output)
        return 0
    if not (args.write or args.check):
        raise SystemExit("choose exactly one of --write or --check")
    if args.source_commit is None:
        raise SystemExit("--source-commit with the reviewed full commit id is required")
    _verify_source_pin(args.source_commit)

    with tempfile.TemporaryDirectory(prefix="frozen-claude-regeneration-") as tmp:
        # Canonicalize only this process-created boundary; the frozen installer correctly refuses
        # macOS's symlink spelling of /var when handed it as a project path.
        temporary = Path(tmp).resolve()
        source_root = temporary / "source"
        candidate = temporary / "generated"
        _extract_frozen_source(source_root)
        _generate_in_subprocess(source_root, candidate)
        if args.check:
            return 0 if _check(candidate) else 1
        FIXTURE_ROOT.mkdir(parents=True, exist_ok=True)
        replacement = FIXTURE_ROOT / ".generated-next"
        if replacement.exists():
            shutil.rmtree(replacement)
        shutil.copytree(candidate, replacement)
        if GENERATED_ROOT.exists():
            shutil.rmtree(GENERATED_ROOT)
        replacement.replace(GENERATED_ROOT)
    print(f"wrote frozen Claude fixtures from {FROZEN_SOURCE_COMMIT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
