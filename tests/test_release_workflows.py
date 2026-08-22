"""Static security contracts for the build-once, publish-exact-artifact workflows."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
WORKFLOWS = list((ROOT / ".github" / "workflows").glob("*.yml"))
CI = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
PUBLISH = (ROOT / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")
PIN_LEDGER = (ROOT / "docs" / "operations" / "github-repository-settings.md").read_text(
    encoding="utf-8"
)


def _action_refs(text: str) -> list[str]:
    return re.findall(r"^\s*-?\s*uses:\s*([^\s#]+)", text, re.MULTILINE)


def _advertised_action_pins(text: str) -> list[tuple[str, str, str]]:
    return [
        (match.group("component"), match.group("ref"), match.group("sha"))
        for match in re.finditer(
            r"^\s*-?\s*uses:\s*(?P<component>[^@\s#]+)@"
            r"(?P<sha>[0-9a-f]{40})\s+#\s+(?P<ref>\S+)\s*$",
            text,
            re.MULTILINE,
        )
    ]


def _ledger_pins(text: str) -> set[tuple[str, str, str]]:
    return {
        (match.group("component"), match.group("ref"), match.group("sha"))
        for match in re.finditer(
            r"^\| `(?P<component>[^`]+)` \| `(?P<ref>[^`]+)` \| "
            r"`(?P<sha>[0-9a-f]{40})` \|$",
            text,
            re.MULTILINE,
        )
    }


def test_all_third_party_actions_are_pinned_to_full_commit_shas():
    refs = [
        ref
        for workflow in WORKFLOWS
        for ref in _action_refs(workflow.read_text(encoding="utf-8"))
    ]
    assert refs
    assert all(re.fullmatch(r"[^@]+@[0-9a-f]{40}", ref) for ref in refs), refs


def test_supply_chain_ledger_matches_every_tracked_workflow_action_pin():
    refs = [
        ref
        for workflow in WORKFLOWS
        for ref in _action_refs(workflow.read_text(encoding="utf-8"))
    ]
    advertised = [
        pin
        for workflow in WORKFLOWS
        for pin in _advertised_action_pins(workflow.read_text(encoding="utf-8"))
    ]
    assert len(advertised) == len(refs), (
        "every workflow action pin needs an audited ref comment"
    )

    workflow_pins = set(advertised)
    workflow_components = {component for component, _ref, _sha in workflow_pins}
    documented = {
        pin for pin in _ledger_pins(PIN_LEDGER) if pin[0] in workflow_components
    }
    assert documented == workflow_pins


def test_ci_builds_once_and_wheel_smoke_downloads_that_artifact():
    assert CI.count("python -m build") == 1
    assert "name: verified-dist" in CI
    wheel_smoke = CI.split("wheel-smoke:", 1)[1]
    assert "needs: build" in wheel_smoke
    assert "actions/download-artifact" in wheel_smoke
    assert "python -m build" not in wheel_smoke
    assert "release_preflight.py verify" in wheel_smoke


def test_ci_splits_only_the_expensive_live_matrix_for_bounded_parallelism():
    test_job = CI.split("  test:\n", 1)[1].split("\n  runtime-unit:", 1)[0]
    matrix_node = (
        "tests/test_scaffold.py::test_self_test_matrix_resolves_installs_and_validates"
    )

    assert '-k "not test_self_test_matrix_resolves_installs_and_validates"' in test_job
    assert matrix_node in test_job
    assert "-n 4" in test_job
    assert "--dist=worksteal" in test_job
    assert "timeout-minutes: 180" in test_job


def test_ci_runs_official_claude_validator_at_pinned_minimum_and_current():
    assert "claude-compatibility.yaml" in CI
    assert "@anthropic-ai/claude-code@" in CI
    assert "claude plugin validate . --strict" in CI
    assert "actionlint" in CI and "zizmor" in CI


def test_ci_fetches_each_codex_validator_bundle_from_catalog_hashes():
    assert '**entry["plugin_validator"]' in CI
    assert "matrix.validate_plugin_sha256" in CI
    assert "matrix.identifier_validation_sha256" in CI
    assert "identifier_validation.py" in CI
    assert "CODEX_PLUGIN_VALIDATOR" in CI
    assert "VALIDATOR_SHA256: ebda00" not in CI


def test_native_plugin_compatibility_jobs_install_the_checkout_before_pytest():
    claude_job = CI.split("  official-plugin-validation:", 1)[1].split(
        "  claude-plugin-compat:", 1
    )[0]
    codex_job = CI.split("  official-codex-plugin-conformance:", 1)[1].split(
        "  codex-plugin-compat:", 1
    )[0]
    assert "python -m pip install -e . pytest==8.4.2" in claude_job
    assert "python -m pip install -e . pytest==8.4.2 pyyaml==6.0.3" in codex_job
    assert "tests/test_plugin_host_smoke.py" in claude_job
    assert "tests/test_plugin_host_smoke.py" in codex_job


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
