"""Static security policy for the opt-in credentialed host workflow."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
WORKFLOW = ROOT / ".github/workflows/protected-host-behavior.yml"
TEXT = WORKFLOW.read_text(encoding="utf-8")
CI = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
HARNESS = (ROOT / "scripts/protected_host_smoke.py").read_text(encoding="utf-8")


def test_protected_host_workflow_never_runs_for_pull_requests_or_pushes() -> None:
    trigger = TEXT.split("permissions:", 1)[0]
    assert "workflow_dispatch:" in trigger
    assert "schedule:" in trigger
    assert "pull_request" not in trigger
    assert "push:" not in trigger
    assert "environment: protected-host-behavior" in TEXT
    assert "ACTUAL_REF: ${{ github.ref }}" in TEXT
    assert (
        "EXPECTED_REF: refs/heads/${{ github.event.repository.default_branch }}" in TEXT
    )
    assert 'test "$ACTUAL_REF" = "$EXPECTED_REF"' in TEXT
    assert "github.ref_name" not in TEXT


def test_protected_host_workflow_uses_pinned_hosts_and_exact_built_wheel() -> None:
    assert "catalog/claude-compatibility.yaml" in TEXT
    assert "catalog/codex-compatibility.yaml" in TEXT
    assert 'policy["minimum"]' in TEXT
    assert 'policy["current_stable"]' in TEXT
    assert "python -m build --wheel" in TEXT
    assert '"$wheel_env/bin/pip" install "${wheels[0]}"' in TEXT
    assert 'npm install --global "@openai/codex@$CODEX_CLI_VERSION"' in TEXT
    assert "protected_host_smoke.py prepare" in TEXT
    assert '--ckit-executable "$CKIT_WHEEL_EXE"' in TEXT
    assert "SMOKE_DIRECTION: ${{ matrix.direction }}" in TEXT
    assert '--direction "$SMOKE_DIRECTION"' in TEXT
    assert '--direction "${{ matrix.direction }}"' not in TEXT
    assert '--runtime", "both"' not in TEXT  # runtime choice stays inside the harness


def test_codex_key_has_only_the_two_explicit_protected_host_channels() -> None:
    match = re.search(r"uses: openai/codex-action@([0-9a-f]{40})", TEXT)
    assert match is not None
    assert match.group(1) == "86365089eb2b84e0a8fb0717b304f8bdcb13b20e"
    assert "openai-api-key: ${{ secrets.CKIT_OPENAI_API_KEY }}" in TEXT
    direct = "OPENAI_API_KEY: ${{ secrets.CKIT_OPENAI_API_KEY }}"
    assert TEXT.count(direct) == 1
    managed_step = TEXT.split(
        "- name: Exercise exact-wheel managed Codex passive stages and gate owner", 1
    )[1].split("\n      - name:", 1)[0]
    assert direct in managed_step
    assert "protected_host_smoke.py run-managed-codex" in managed_step
    assert "-u CODEX_ACCESS_TOKEN" in managed_step
    assert "-u CODEX_API_KEY" in managed_step
    assert "-u CKIT_OPENAI_API_KEY" in managed_step
    assert "--executable codex" in managed_step
    assert "seed-managed-gate-owner" in HARNESS
    assert "close-managed-gate-owner" in HARNESS
    assert "execute_bound_workflow(" in HARNESS
    assert "pipeline.record_findings(" in HARNESS
    assert "pipeline.close_gate(" in HARNESS
    assert '"native_host_claim": False' in HARNESS
    assert '"native_host_claim": True' in HARNESS
    assert "snapshot_document" not in managed_step
    assert 'permission-profile: ":read-only"' in TEXT
    assert "safety-strategy: drop-sudo" in TEXT
    assert "codex-args: '[\"--ephemeral\"]'" in TEXT
    assert "action rejects hook-trust bypasses under protected profiles" in TEXT
    for forbidden in (
        "--dangerously-bypass-hook-trust",
        '"--enable"',
        '"-c"',
        "sandbox: read-only",
    ):
        assert forbidden not in TEXT
    assert "environment: protected-host-behavior" in TEXT
    assert "--dangerously-bypass-hook-trust" not in CI


def test_protected_matrix_exercises_both_shared_ledger_provider_orders() -> None:
    assert 'for direction in ("claude-codex", "codex-claude")' in TEXT
    assert (
        "name: protected-host-behavior-${{ matrix.tier }}-${{ matrix.direction }}"
        in TEXT
    )
    assert "if: matrix.direction == 'claude-codex'" in TEXT
    assert "if: matrix.direction == 'codex-claude'" in TEXT
    codex_action = TEXT.index("uses: openai/codex-action@")
    claude_first = TEXT.index("- name: Exercise protected Claude behavior\n")
    claude_second = TEXT.index("- name: Exercise protected Claude behavior after Codex")
    assert claude_first < codex_action < claude_second
    assert "SMOKE_DIRECTION: ${{ matrix.direction }}" in TEXT
    assert '--direction "$SMOKE_DIRECTION"' in TEXT


def test_codex_trust_is_vetted_outside_the_project_before_the_proxy_runs() -> None:
    trust_step = TEXT.index(
        "Trust only the prepared project in the isolated Codex home"
    )
    action_step = TEXT.index("uses: openai/codex-action@")
    assert trust_step < action_step
    assert 'project="$(realpath -e "$CKIT_SMOKE_ROOT/project")"' in TEXT
    assert (
        'f"[projects.{json.dumps(project)}]\\ntrust_level = \\"trusted\\"\\n"' in TEXT
    )
    assert 'chmod 600 "$config"' in TEXT
    assert "features.multi_agent" not in TEXT
    assert "agents.enabled" not in TEXT


def test_codex_generated_hooks_are_staged_as_exact_managed_system_policy() -> None:
    stage_step = TEXT.index(
        "Stage exact generated Codex hooks as managed system policy"
    )
    action_step = TEXT.index("uses: openai/codex-action@")
    assert stage_step < action_step
    for required in (
        'source_hooks="$project/.codex/hooks.json"',
        'system_root="/etc/codex"',
        'policy_stage="$(mktemp -d "$RUNNER_TEMP/ckit-codex-system-policy.XXXXXX")"',
        'test ! -L "$source_hooks"',
        'test "$(realpath -e "$source_hooks")" = "$source_hooks"',
        'if sudo test -e "$system_root" || sudo test -L "$system_root"; then',
        "refusing to replace pre-existing Codex system policy",
        "printf '[features]\\nhooks = true\\n'",
        'sudo install -d -o root -g root -m 0755 "$system_root"',
        'sudo install -o root -g root -m 0644 "$staged_config" "$system_root/config.toml"',
        'sudo install -o root -g root -m 0644 "$source_hooks" "$system_root/hooks.json"',
        'cmp -s "$source_hooks" "$system_root/hooks.json"',
        'test "$source_sha" = "$system_sha"',
        'test "$(stat -c \'%U:%G:%a\' "$system_root")" = "root:root:755"',
        'test "$(stat -c \'%U:%G:%a\' "$system_root/config.toml")" = "root:root:644"',
        'test "$(stat -c \'%U:%G:%a\' "$system_root/hooks.json")" = "root:root:644"',
    ):
        assert required in TEXT
    assert '"$codex_home/hooks.json"' not in TEXT


def test_claude_key_uses_an_external_helper_and_is_absent_from_host_child_env() -> None:
    assert "apiKeyHelper" in TEXT
    assert '--auth-settings "$CKIT_CLAUDE_AUTH_SETTINGS"' in TEXT
    assert "-u ANTHROPIC_API_KEY" in TEXT
    assert "-u CLAUDE_CODE_OAUTH_TOKEN" in TEXT
    assert "Remove staged Claude credential material" in TEXT
    assert ': > "$credential_file"' in TEXT
    assert 'rm -f -- "$credential_file"' in TEXT


def test_workflow_asserts_real_components_hooks_and_shared_gate_history() -> None:
    contract = TEXT + HARNESS
    for required in (
        "$using-agent-skills",
        "risk-classifier",
        "SessionStart",
        "PostToolUse",
        "blocking_reason",
        "advisory_marker",
        "record-codex",
        "run-managed-codex",
        "managed-workflow-evidence",
        "scope-record",
        "pipeline-snapshot.json",
        '"close-gate"',
        '"record-findings"',
        "protect-secrets",
        "guard-proxy",
        "expected_commitments",
        "observation_commitments",
        "generated_guard_disposition",
        "generated_stop_disposition",
        "definition-read",
        "unapproved-shell-command",
        "additionalContext",
        "verify --root",
    ):
        assert required in contract
    assert "CKIT_ANTHROPIC_API_KEY" not in CI
    assert "CKIT_OPENAI_API_KEY" not in CI
    assert 'printf \'%s\\n\' "$wheel_env/bin" >> "$GITHUB_PATH"' in TEXT
    assert "cat .env" in TEXT
    assert "shell/unified-exec" in TEXT


def test_protected_verifier_has_no_plaintext_or_raw_output_artifact_oracle() -> None:
    assert '"expected": expected' not in HARNESS
    assert '"blocked_canary": blocked_canary' not in HARNESS
    assert '"observation": dict(observation)' not in HARNESS
    assert '"expected_commitments": expected_commitments' in HARNESS
    assert '"blocked_canary_commitment"' in HARNESS
    assert '"observation_commitments"' in HARNESS
    assert "output.unlink(missing_ok=True)" in HARNESS
    upload = TEXT.split("uses: actions/upload-artifact@", 1)[1]
    assert "control/control.json" not in upload
    assert "codex-output.json" not in upload
    assert "managed-project/.ckit/state/pipeline-snapshot.json" in upload
    assert "managed-gate-owner-project/.ckit/state/pipeline-snapshot.json" in upload
    assert "managed-gate-owner-project/.ckit/artifacts/evidence/runs/" in upload
    assert "managed-gate-owner-project/.ckit/artifacts/dispatch/runs/" in upload
    assert "managed-gate-owner-project/.ckit/artifacts/protected-host/" in upload
    assert "include-hidden-files: true" in upload
    assert "if: success()" in upload
    assert "if: always()" not in upload


def test_generated_guard_evidence_is_provider_native_and_exactly_attributed() -> None:
    for required in (
        "expected exactly 1",
        'event.get("handler_sha256") != expected_hash',
        "_recorded_guard_disposition(provider, event)",
        'event.get("native_operation") == expected_operation',
        '"record_schema_version": 1',
        "_write_all(1, completed.stdout)",
        "_write_all(2, completed.stderr)",
    ):
        assert required in HARNESS


def test_every_action_reference_in_the_protected_workflow_is_immutable() -> None:
    references = re.findall(r"^\s*-?\s*uses:\s*([^\s#]+)", TEXT, re.MULTILINE)
    assert references
    assert all(
        re.fullmatch(r"[^@]+@[0-9a-f]{40}", reference) for reference in references
    )
