"""Static security contracts for the build-once, publish-exact-artifact workflows."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
WORKFLOWS = list((ROOT / ".github" / "workflows").glob("*.yml"))
CI = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
PUBLISH = (ROOT / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")


def _action_refs(text: str) -> list[str]:
    return re.findall(r"^\s*-?\s*uses:\s*([^\s#]+)", text, re.MULTILINE)


def test_all_third_party_actions_are_pinned_to_full_commit_shas():
    refs = [
        ref
        for workflow in WORKFLOWS
        for ref in _action_refs(workflow.read_text(encoding="utf-8"))
    ]
    assert refs
    assert all(re.fullmatch(r"[^@]+@[0-9a-f]{40}", ref) for ref in refs), refs


def test_ci_builds_once_and_wheel_smoke_downloads_that_artifact():
    assert CI.count("python -m build") == 1
    assert "name: verified-dist" in CI
    wheel_smoke = CI.split("wheel-smoke:", 1)[1]
    assert "needs: build" in wheel_smoke
    assert "actions/download-artifact" in wheel_smoke
    assert "python -m build" not in wheel_smoke
    assert "release_preflight.py verify" in wheel_smoke


def test_ci_runs_official_claude_validator_at_pinned_minimum_and_current():
    assert "claude-code-compatibility.yaml" in CI
    assert "@anthropic-ai/claude-code@" in CI
    assert "claude plugin validate . --strict" in CI
    assert "actionlint" in CI and "zizmor" in CI


def test_ci_exposes_the_pinned_actionlint_binary_to_later_steps():
    assert 'GOBIN="$workflow_tools" go install' in CI
    assert 'echo "$workflow_tools" >> "$GITHUB_PATH"' in CI


def test_publish_consumes_successful_ci_artifact_and_never_rebuilds():
    assert "workflow_run:" in PUBLISH
    assert "workflows: [CI]" in PUBLISH
    assert "github.event.workflow_run.id" in PUBLISH
    assert "github.event.workflow_run.head_sha" in PUBLISH
    assert "verified-dist" in PUBLISH
    assert "python -m build" not in PUBLISH
    assert "release_preflight.py verify" in PUBLISH


def test_publish_is_fail_closed_and_verifies_post_publish_bytes():
    assert "skip-existing" not in PUBLISH
    assert "release_preflight.py pypi-status" in PUBLISH
    assert "release_preflight.py verify-published" in PUBLISH
    assert "attest-build-provenance" in PUBLISH
    assert "attestations: true" in PUBLISH
    assert "SHA256SUMS" in PUBLISH
    assert "gh release" in PUBLISH


def test_recovery_release_still_requires_successful_artifact_attestation():
    """An already-identical PyPI release must not bypass the provenance control."""
    verify = PUBLISH.split("  verify-pypi:", 1)[1].split("  github-release:", 1)[0]
    assert "needs: [preflight, attest, publish]" in verify
    assert "needs.attest.result == 'success'" in verify


def test_recovery_validates_an_existing_tag_before_inspecting_the_release():
    """A tag-only partial release cannot attach artifacts to an unverified commit."""
    job = PUBLISH.split("  github-release:", 1)[1]
    fetch = 'git fetch --force origin "$tag_ref:$tag_ref"'
    sha_check = 'test "$(git rev-list -n 1 "$tag")" = "$VERIFIED_SHA"'
    release_probe = 'if gh release view "$tag"'
    assert fetch in job and sha_check in job and release_probe in job
    assert job.index(fetch) < job.index(sha_check) < job.index(release_probe)
    assert '--target "$VERIFIED_SHA"' not in job


def test_recovery_rejects_unexpected_assets_and_verifies_the_final_exact_set():
    job = PUBLISH.split("  github-release:", 1)[1]
    command = "release_preflight.py verify-release-assets"
    assert job.count(command) == 2
    assert job.count("--allow-missing") == 1
    assert job.rindex(command) > job.index("gh release upload")


def test_workflows_declare_least_privilege_and_publish_concurrency():
    assert re.search(r"^permissions:\n\s+contents: read", CI, re.MULTILINE)
    assert re.search(r"^permissions:\n\s+contents: read", PUBLISH, re.MULTILINE)
    assert "concurrency:" in CI
    assert "concurrency:" in PUBLISH
    assert "cancel-in-progress: false" in PUBLISH


def test_dependabot_tracks_actions_and_python_dependencies():
    text = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    assert 'package-ecosystem: "github-actions"' in text
    assert 'package-ecosystem: "pip"' in text
