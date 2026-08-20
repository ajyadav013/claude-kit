#!/usr/bin/env python3
"""Fail-closed release metadata and artifact-digest checks.

The CI build is the only build. This utility writes/verifies its SHA256SUMS, requires release notes,
and distinguishes an absent PyPI version (404) from an identical existing release (200) and every
ambiguous transport/server response (error). It deliberately has no "skip existing" behavior.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised by the Python 3.9 CI lane
    import tomli as tomllib  # type: ignore[no-redef]

PACKAGE = "claude-code-kit"


class ReleaseError(RuntimeError):
    """A condition under which publishing must stop."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def distribution_files(dist_dir: Path) -> list[Path]:
    """Return the one wheel and one sdist that make up a release."""
    files = sorted(
        path
        for path in dist_dir.iterdir()
        if path.is_file() and (path.suffix == ".whl" or path.name.endswith(".tar.gz"))
    )
    wheels = [path for path in files if path.suffix == ".whl"]
    sdists = [path for path in files if path.name.endswith(".tar.gz")]
    if len(wheels) != 1 or len(sdists) != 1 or len(files) != 2:
        raise ReleaseError(
            f"expected exactly one wheel and one sdist in {dist_dir}, found: "
            + ", ".join(path.name for path in files)
        )
    return files


def project_metadata(pyproject: Path) -> tuple[str, str]:
    doc = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    project = doc.get("project") or {}
    name, version = project.get("name"), project.get("version")
    if name != PACKAGE:
        raise ReleaseError(f"distribution must be {PACKAGE!r}, found {name!r}")
    if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ReleaseError(f"invalid project version: {version!r}")
    return name, version


def changelog_section(changelog: Path, version: str) -> str:
    """Extract a required, nonblank ``## [version]`` section."""
    text = changelog.read_text(encoding="utf-8")
    heading = re.compile(rf"^## \[{re.escape(version)}\](?:[ \t].*)?$", re.MULTILINE)
    match = heading.search(text)
    if not match:
        raise ReleaseError(f"CHANGELOG has no section for {version}")
    following = re.search(r"^## \[", text[match.end() :], re.MULTILINE)
    end = match.end() + following.start() if following else len(text)
    notes = text[match.end() : end].strip()
    if not notes:
        raise ReleaseError(f"CHANGELOG section for {version} is empty")
    return notes + "\n"


def write_sha256s(dist_dir: Path) -> Path:
    files = distribution_files(dist_dir)
    output = dist_dir / "SHA256SUMS"
    output.write_text(
        "".join(f"{_sha256(path)}  {path.name}\n" for path in files), encoding="utf-8"
    )
    return output


def _read_sha256s(dist_dir: Path) -> dict[str, str]:
    checksum_file = dist_dir / "SHA256SUMS"
    if not checksum_file.is_file():
        raise ReleaseError("SHA256SUMS is missing")
    expected: dict[str, str] = {}
    for line in checksum_file.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([^/]+)", line)
        if not match:
            raise ReleaseError(f"malformed SHA256SUMS line: {line!r}")
        digest, filename = match.groups()
        expected[filename] = digest
    return expected


def verify_sha256s(dist_dir: Path) -> list[str]:
    expected = _read_sha256s(dist_dir)
    actual_files = distribution_files(dist_dir)
    actual_names = {path.name for path in actual_files}
    errors: list[str] = []
    if set(expected) != actual_names:
        errors.append(
            f"SHA256SUMS filenames differ: expected {sorted(expected)}, found {sorted(actual_names)}"
        )
    for path in actual_files:
        if path.name in expected and _sha256(path) != expected[path.name]:
            errors.append(f"digest mismatch for {path.name}")
    return errors


def verify_release_assets(
    dist_dir: Path, assets_json: Path, *, allow_missing: bool = False
) -> None:
    """Require a GitHub Release to contain only the verified CI artifact set.

    ``allow_missing`` is used immediately before recovery uploads: an interrupted
    release may be missing an expected file, but an unexpected stale asset must
    never be retained. The post-upload call requires exact set equality.
    """
    expected = {path.name for path in distribution_files(dist_dir)} | {"SHA256SUMS"}
    if not (dist_dir / "SHA256SUMS").is_file():
        raise ReleaseError("SHA256SUMS is missing")
    try:
        document = json.loads(assets_json.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ReleaseError(f"GitHub Release asset metadata is invalid: {exc}") from exc
    if not isinstance(document, dict) or not isinstance(document.get("assets"), list):
        raise ReleaseError("GitHub Release asset metadata must contain an assets array")
    names = [
        item.get("name") if isinstance(item, dict) else None
        for item in document["assets"]
    ]
    if any(not isinstance(name, str) or not name for name in names):
        raise ReleaseError("GitHub Release asset metadata contains an invalid name")
    if len(names) != len(set(names)):
        raise ReleaseError("GitHub Release contains duplicate asset names")
    actual = set(names)
    unexpected = actual - expected
    if unexpected:
        raise ReleaseError(
            "GitHub Release contains unexpected assets: "
            + ", ".join(sorted(unexpected))
        )
    if not allow_missing and actual != expected:
        raise ReleaseError(
            "GitHub Release asset set differs from the verified artifacts: "
            f"expected {sorted(expected)}, found {sorted(actual)}"
        )


def prepare(pyproject: Path, changelog: Path, dist_dir: Path) -> tuple[str, str]:
    """Validate release inputs and create the digest manifest."""
    _name, version = project_metadata(pyproject)
    notes = changelog_section(changelog, version)
    files = distribution_files(dist_dir)
    expected_prefix = f"{PACKAGE.replace('-', '_')}-{version}"
    wrong = [path.name for path in files if not path.name.startswith(expected_prefix)]
    if wrong:
        raise ReleaseError(
            f"artifact filename(s) do not match project {PACKAGE} {version}: {wrong}"
        )
    write_sha256s(dist_dir)
    errors = verify_sha256s(dist_dir)
    if errors:
        raise ReleaseError("; ".join(errors))
    return version, notes


def _open_json(
    url: str,
    *,
    opener: Callable[..., Any],
    timeout: float,
    retries: int,
    retry_not_found: bool = False,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any] | None:
    last_error: Exception | None = None
    request = urllib.request.Request(
        url, headers={"User-Agent": "claude-code-kit-release"}
    )
    for attempt in range(retries):
        try:
            response = opener(request, timeout=timeout)
            status = getattr(response, "status", 200)
            if status != 200:
                raise ReleaseError(f"PyPI returned unexpected HTTP {status}")
            raw = response.read()
            close = getattr(response, "close", None)
            if close:
                close()
            doc = json.loads(raw)
            if not isinstance(doc, dict):
                raise ReleaseError("PyPI returned non-object JSON")
            return doc
        except urllib.error.HTTPError as exc:
            if exc.code == 404 and not retry_not_found:
                return None
            last_error = ReleaseError(f"PyPI returned unexpected HTTP {exc.code}")
        except (
            urllib.error.URLError,
            TimeoutError,
            json.JSONDecodeError,
            OSError,
        ) as exc:
            last_error = exc
        except ReleaseError:
            raise
        if attempt + 1 < retries:
            sleeper(min(2**attempt, 4))
    if (
        retry_not_found
        and isinstance(last_error, ReleaseError)
        and "HTTP 404" in str(last_error)
    ):
        return None
    raise ReleaseError(
        f"PyPI metadata request failed after {retries} attempt(s): {last_error}"
    )


def pypi_metadata(
    version: str,
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
    timeout: float = 15,
    retries: int = 3,
    retry_not_found: bool = False,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any] | None:
    return _open_json(
        f"https://pypi.org/pypi/{PACKAGE}/{version}/json",
        opener=opener,
        timeout=timeout,
        retries=retries,
        retry_not_found=retry_not_found,
        sleeper=sleeper,
    )


def compare_pypi_digests(metadata: dict[str, Any], dist_dir: Path) -> None:
    local = {path.name: _sha256(path) for path in distribution_files(dist_dir)}
    remote: dict[str, str] = {}
    for item in metadata.get("urls", []):
        if not isinstance(item, dict):
            continue
        filename = item.get("filename")
        digest = (item.get("digests") or {}).get("sha256")
        if isinstance(filename, str) and isinstance(digest, str):
            remote[filename] = digest
    if set(local) != set(remote):
        raise ReleaseError(
            f"PyPI filenames differ: local {sorted(local)}, remote {sorted(remote)}"
        )
    for filename, digest in local.items():
        if remote[filename] != digest:
            raise ReleaseError(f"PyPI digest mismatch for {filename}")


def pypi_status(
    version: str,
    dist_dir: Path,
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
    timeout: float = 15,
    retries: int = 3,
) -> str:
    metadata = pypi_metadata(version, opener=opener, timeout=timeout, retries=retries)
    if metadata is None:
        return "missing"
    compare_pypi_digests(metadata, dist_dir)
    return "identical"


def verify_published(
    version: str,
    dist_dir: Path,
    download_dir: Path,
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
    retries: int = 6,
    sleeper: Callable[[float], None] = time.sleep,
) -> None:
    """Download the PyPI files and compare both metadata and bytes to the CI artifact."""
    metadata = pypi_metadata(
        version,
        opener=opener,
        retries=retries,
        retry_not_found=True,
        sleeper=sleeper,
    )
    if metadata is None:
        raise ReleaseError(f"{PACKAGE} {version} is still absent from PyPI")
    compare_pypi_digests(metadata, dist_dir)
    urls = {
        item["filename"]: item["url"]
        for item in metadata.get("urls", [])
        if isinstance(item, dict)
        and isinstance(item.get("filename"), str)
        and isinstance(item.get("url"), str)
    }
    expected_names = {path.name for path in distribution_files(dist_dir)}
    if set(urls) != expected_names:
        raise ReleaseError(
            "PyPI download URLs differ from the verified artifacts: "
            f"expected {sorted(expected_names)}, found {sorted(urls)}"
        )
    download_dir.mkdir(parents=True, exist_ok=True)
    for local in distribution_files(dist_dir):
        request = urllib.request.Request(
            urls[local.name], headers={"User-Agent": "claude-code-kit-release"}
        )
        downloaded = download_dir / local.name
        downloaded.write_bytes(
            _open_bytes(
                request,
                opener=opener,
                timeout=30,
                retries=retries,
                sleeper=sleeper,
            )
        )
        if _sha256(downloaded) != _sha256(local):
            raise ReleaseError(f"downloaded PyPI digest mismatch for {local.name}")


def _open_bytes(
    request: urllib.request.Request,
    *,
    opener: Callable[..., Any],
    timeout: float,
    retries: int,
    sleeper: Callable[[float], None],
) -> bytes:
    """Download bytes with bounded retries; any non-200 response remains a hard failure."""
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            response = opener(request, timeout=timeout)
            status = getattr(response, "status", 200)
            if status != 200:
                raise ReleaseError(
                    f"artifact download returned unexpected HTTP {status}"
                )
            raw = response.read()
            close = getattr(response, "close", None)
            if close:
                close()
            return raw
        except urllib.error.HTTPError as exc:
            last_error = ReleaseError(
                f"artifact download returned unexpected HTTP {exc.code}"
            )
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
        except ReleaseError as exc:
            last_error = exc
        if attempt + 1 < retries:
            sleeper(min(2**attempt, 4))
    raise ReleaseError(
        f"artifact download failed after {retries} attempt(s): {last_error}"
    )


def _append_github_output(**values: str) -> None:
    target = os.environ.get("GITHUB_OUTPUT")
    if not target:
        return
    with Path(target).open("a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--pyproject", type=Path, default=Path("pyproject.toml"))
    prep.add_argument("--changelog", type=Path, default=Path("CHANGELOG.md"))
    prep.add_argument("--dist-dir", type=Path, default=Path("dist"))
    prep.add_argument("--notes-output", type=Path)
    verify = sub.add_parser("verify")
    verify.add_argument("--dist-dir", type=Path, default=Path("dist"))
    status = sub.add_parser("pypi-status")
    status.add_argument("--version", required=True)
    status.add_argument("--dist-dir", type=Path, default=Path("dist"))
    published = sub.add_parser("verify-published")
    published.add_argument("--version", required=True)
    published.add_argument("--dist-dir", type=Path, default=Path("dist"))
    published.add_argument("--download-dir", type=Path, default=Path("pypi-download"))
    release_assets = sub.add_parser("verify-release-assets")
    release_assets.add_argument("--dist-dir", type=Path, default=Path("dist"))
    release_assets.add_argument("--assets-json", type=Path, required=True)
    release_assets.add_argument("--allow-missing", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            version, notes = prepare(args.pyproject, args.changelog, args.dist_dir)
            if args.notes_output:
                args.notes_output.write_text(notes, encoding="utf-8")
            _append_github_output(version=version)
            print(version)
        elif args.command == "verify":
            errors = verify_sha256s(args.dist_dir)
            if errors:
                raise ReleaseError("; ".join(errors))
            print("SHA256SUMS verified")
        elif args.command == "pypi-status":
            state = pypi_status(args.version, args.dist_dir)
            _append_github_output(status=state)
            print(state)
        elif args.command == "verify-published":
            verify_published(args.version, args.dist_dir, args.download_dir)
            print("published artifacts match the verified CI artifact")
        else:
            verify_release_assets(
                args.dist_dir,
                args.assets_json,
                allow_missing=args.allow_missing,
            )
            print("GitHub Release assets match the verified CI artifact policy")
    except (OSError, ReleaseError) as exc:
        print(f"release preflight failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
