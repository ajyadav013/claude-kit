"""Release preflight: fail closed on metadata, HTTP ambiguity, and digest drift."""

from __future__ import annotations

import hashlib
import io
import json
import urllib.error
from pathlib import Path

import pytest

from scripts import release_preflight


def _dist(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "claude_code_kit-1.2.3-py3-none-any.whl").write_bytes(b"wheel")
    (dist / "claude_code_kit-1.2.3.tar.gz").write_bytes(b"sdist")
    return dist


def test_prepare_requires_nonempty_changelog_and_writes_sha256s(tmp_path):
    dist = _dist(tmp_path)
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname="claude-code-kit"\nversion="1.2.3"\n')
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        "## [1.2.3] - today\n\nFixed the release.\n\n## [1.2.2]\nold\n"
    )

    version, notes = release_preflight.prepare(pyproject, changelog, dist)

    assert version == "1.2.3"
    assert notes.strip() == "Fixed the release."
    lines = (dist / "SHA256SUMS").read_text().splitlines()
    assert len(lines) == 2
    assert release_preflight.verify_sha256s(dist) == []


def test_prepare_fails_when_changelog_section_is_missing(tmp_path):
    dist = _dist(tmp_path)
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname="claude-code-kit"\nversion="1.2.3"\n')
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("## [1.2.2]\nold\n")
    with pytest.raises(release_preflight.ReleaseError, match="CHANGELOG"):
        release_preflight.prepare(pyproject, changelog, dist)


def test_prepare_rejects_artifacts_for_a_different_version(tmp_path):
    dist = _dist(tmp_path)
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname="claude-code-kit"\nversion="1.2.4"\n')
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("## [1.2.4]\nnotes\n")
    with pytest.raises(release_preflight.ReleaseError, match="match project"):
        release_preflight.prepare(pyproject, changelog, dist)


def test_pypi_status_distinguishes_404_200_and_server_error(tmp_path):
    dist = _dist(tmp_path)
    release_preflight.write_sha256s(dist)

    def missing(_request, timeout):
        raise urllib.error.HTTPError("url", 404, "missing", {}, None)

    assert release_preflight.pypi_status("1.2.3", dist, opener=missing) == "missing"

    files = []
    for path in release_preflight.distribution_files(dist):
        files.append(
            {
                "filename": path.name,
                "digests": {"sha256": hashlib.sha256(path.read_bytes()).hexdigest()},
                "url": f"https://files.example/{path.name}",
            }
        )

    def present(_request, timeout):
        return io.BytesIO(json.dumps({"urls": files}).encode())

    assert release_preflight.pypi_status("1.2.3", dist, opener=present) == "identical"

    def broken(_request, timeout):
        raise urllib.error.HTTPError("url", 503, "broken", {}, None)

    with pytest.raises(release_preflight.ReleaseError, match="503"):
        release_preflight.pypi_status("1.2.3", dist, opener=broken, retries=1)


def test_pypi_status_fails_when_existing_filename_digest_differs(tmp_path):
    dist = _dist(tmp_path)
    files = release_preflight.distribution_files(dist)
    wheel = files[0]
    metadata = {
        "urls": [
            {
                "filename": wheel.name,
                "digests": {"sha256": "0" * 64},
                "url": "https://files.example/wheel",
            },
            {
                "filename": files[1].name,
                "digests": {
                    "sha256": hashlib.sha256(files[1].read_bytes()).hexdigest()
                },
                "url": "https://files.example/sdist",
            },
        ]
    }

    def present(_request, timeout):
        return io.BytesIO(json.dumps(metadata).encode())

    with pytest.raises(release_preflight.ReleaseError, match="digest mismatch"):
        release_preflight.pypi_status("1.2.3", dist, opener=present)


def test_verify_sha256s_reports_tampering(tmp_path):
    dist = _dist(tmp_path)
    release_preflight.write_sha256s(dist)
    (dist / "claude_code_kit-1.2.3.tar.gz").write_bytes(b"tampered")
    assert any(
        "digest mismatch" in error for error in release_preflight.verify_sha256s(dist)
    )


def test_release_asset_recovery_rejects_extras_and_requires_exact_final_set(tmp_path):
    dist = _dist(tmp_path)
    release_preflight.write_sha256s(dist)
    expected = [
        {"name": path.name} for path in release_preflight.distribution_files(dist)
    ] + [{"name": "SHA256SUMS"}]
    assets = tmp_path / "assets.json"

    assets.write_text(json.dumps({"assets": expected[:-1]}), encoding="utf-8")
    release_preflight.verify_release_assets(dist, assets, allow_missing=True)
    with pytest.raises(release_preflight.ReleaseError, match="asset set differs"):
        release_preflight.verify_release_assets(dist, assets)

    assets.write_text(
        json.dumps({"assets": expected + [{"name": "stale-old.whl"}]}),
        encoding="utf-8",
    )
    with pytest.raises(release_preflight.ReleaseError, match="unexpected assets"):
        release_preflight.verify_release_assets(dist, assets, allow_missing=True)

    assets.write_text(json.dumps({"assets": expected}), encoding="utf-8")
    release_preflight.verify_release_assets(dist, assets)


def test_verify_published_fails_cleanly_when_registry_omits_a_download_url(tmp_path):
    dist = _dist(tmp_path)
    files = release_preflight.distribution_files(dist)
    metadata = {
        "urls": [
            {
                "filename": path.name,
                "digests": {"sha256": hashlib.sha256(path.read_bytes()).hexdigest()},
                **(
                    {"url": f"https://files.example/{path.name}"}
                    if path == files[0]
                    else {}
                ),
            }
            for path in files
        ]
    }

    def present(_request, timeout):
        return io.BytesIO(json.dumps(metadata).encode())

    with pytest.raises(release_preflight.ReleaseError, match="download URLs differ"):
        release_preflight.verify_published(
            "1.2.3",
            dist,
            tmp_path / "download",
            opener=present,
            retries=1,
        )


def test_verify_published_retries_a_transient_artifact_download(tmp_path):
    dist = _dist(tmp_path)
    files = release_preflight.distribution_files(dist)
    metadata = {
        "urls": [
            {
                "filename": path.name,
                "digests": {"sha256": hashlib.sha256(path.read_bytes()).hexdigest()},
                "url": f"https://files.example/{path.name}",
            }
            for path in files
        ]
    }
    calls: dict[str, int] = {}

    def transient(request, timeout):
        url = request.full_url
        calls[url] = calls.get(url, 0) + 1
        if url.startswith("https://pypi.org/"):
            return io.BytesIO(json.dumps(metadata).encode())
        if calls[url] == 1:
            raise urllib.error.URLError("temporary")
        filename = url.rsplit("/", 1)[1]
        return io.BytesIO((dist / filename).read_bytes())

    release_preflight.verify_published(
        "1.2.3",
        dist,
        tmp_path / "download",
        opener=transient,
        retries=2,
        sleeper=lambda _seconds: None,
    )
    assert all(calls[f"https://files.example/{path.name}"] == 2 for path in files)
