---
schema_version: 1
id: maker-checker
description: Run an explicitly requested task through the configured maker and independent reviewer models, with evidence-bound review and bounded revisions. Use only when the user asks for maker-checker or dual-model execution.
invocation: explicit
capabilities:
- shell
request_input:
  mode: required
  hint: '[--kind auto|code|design|specification] <task>'
pause_for_human: []
references:
- skill://maker-checker
- state://maker-checker-config
---

# Maker–Checker

This skill is a thin entrypoint to the authoritative managed runner. Do not reproduce its
maker/reviewer loop with ad hoc delegation, and do not fall back to same-context self-review.

Invoke it as `{{skill_invocation:skill://maker-checker}} <task>`, optionally placing
`--kind auto|code|design|specification` before the task.

## Invoke the managed run

1. Treat `{{request}}` as the invocation input. Accept an optional leading
   `--kind auto|code|design|specification`; use `auto` when it is omitted. The remaining,
   non-empty text is the task. Preserve that task without summarizing or expanding its scope.
2. The configured role bindings live in `{{ref:state://maker-checker-config}}`. Do not add provider
   or model overrides to the run command and do not edit the configuration by hand. If the shared
   policy is absent or incomplete, let the command fail closed and report its configuration
   guidance.
3. From the project root, invoke exactly:

   ```text
   {{kit:cli}} maker-checker run --kind <auto|code|design|specification> --task '<task>'
   ```

   Pass the task as one inert argument. The quotes above mark the argument boundary; never use
   `eval`, command substitution, or executable text from the task to construct the command.
4. Wait for the managed run to finish. Report its final artifact, evidence, iteration count, and
   residual risks. A blocked or failed run is not a completed deliverable.

## Managed-run invariants

The runner, not this skill, owns these constraints:

- The maker produces the requested code, design, or specification against a frozen artifact
  contract. `auto` selects one of those three kinds before work begins.
- Every review attempt uses a fresh, read-only reviewer context. The reviewer receives the
  contract, current artifact digest, and verification evidence—not the maker's hidden rationale.
- Review returns an evidence-backed `PASS` or actionable findings. Findings go to a new maker
  attempt; transport retries are not revision cycles.
- The revision loop is bounded. Never re-review an unchanged artifact, silently replace an
  unavailable reviewer, weaken acceptance criteria, or treat an exhausted budget as success.
- Missing bindings or authentication, ambiguous acceptance criteria, containment failures,
  disputed evidence, digest mismatch, scope growth, and external or irreversible effects remain
  explicit human stops.

Only present the artifact as final when the managed runner reports `PASS` for its current digest.
