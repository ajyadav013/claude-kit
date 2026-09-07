# ECC adoption audit

This audit recommends a narrow, clean-room adoption of selected orchestration ideas from
[`affaan-m/ECC`](https://github.com/affaan-m/ECC). It does **not** recommend installing ECC,
vendoring its prompts, or adding another runtime or state store. The review is pinned to commit
[`e04ea0b9cc8248686edf5ac751cadff550e162b8`](https://github.com/affaan-m/ECC/commit/e04ea0b9cc8248686edf5ac751cadff550e162b8)
and was performed on 2026-09-06.

In this document, **Adopt** means re-express the behavior in claude-kit's provider-neutral,
typed control plane; **Wrap** means extend an existing claude-kit mechanism; and **Reject** means
do not integrate the mechanism.

## Decision matrix

| ECC mechanism and evidence | Decision | claude-kit boundary |
|---|:---:|---|
| Change-size routing selects a smaller phase set for trivial and small work, while security-sensitive and public-API changes retain a higher floor ([source](https://github.com/affaan-m/ECC/blob/e04ea0b9cc8248686edf5ac751cadff550e162b8/skills/orch-pipeline/SKILL.md#L39-L54)). ECC also concentrates human approval after planning and before commit ([source](https://github.com/affaan-m/ECC/blob/e04ea0b9cc8248686edf5ac751cadff550e162b8/skills/orch-pipeline/SKILL.md#L76-L85)). | **Adopt** | Select the minimum relevant stages through existing modes and resolved policy. Risk, public-contract, irreversible-action, and external-effect floors remain authoritative. |
| Council participants form independent positions in parallel, a coordinator preserves the strongest dissent, and another round is exceptional rather than automatic ([source](https://github.com/affaan-m/ECC/blob/e04ea0b9cc8248686edf5ac751cadff550e162b8/skills/council/SKILL.md#L76-L125), [round limit](https://github.com/affaan-m/ECC/blob/e04ea0b9cc8248686edf5ac751cadff550e162b8/skills/council/SKILL.md#L166-L173)). | **Adopt** | Use one frozen planning generation, parallel read-only specialist reviews, and one accountable adjudicator. Roles advise; they do not negotiate recursively or vote a gate open. |
| The recursive decision ledger records accepted, watched, and rejected options and revisits them only through bounded, evidence-bearing transitions ([source](https://github.com/affaan-m/ECC/blob/e04ea0b9cc8248686edf5ac751cadff550e162b8/skills/recursive-decision-ledger/SKILL.md#L17-L43)). | **Adopt** | Record the winning decision, rejected alternatives, strongest dissent, and explicit reopen trigger in the existing `.ckit` control plane. Do not create a second ledger. |
| Review dimensions run concurrently, are deduplicated by evidence, and only unique high-severity findings receive adversarial verification ([source](https://github.com/affaan-m/ECC/blob/e04ea0b9cc8248686edf5ac751cadff550e162b8/workflows/orch-review.workflow.js#L177-L210), [deduplication and verification](https://github.com/affaan-m/ECC/blob/e04ea0b9cc8248686edf5ac751cadff550e162b8/workflows/orch-review.workflow.js#L217-L285)). | **Adopt, as a design** | Reimplement the behavior in typed Python: correctness is always applicable; stack and security reviewers are conditional; deduplicate before verification; only evidenced blockers may request another revision. Do not copy the JavaScript workflow. |
| The code-reviewer contract asks for exact evidence, defensible severity, consolidation of duplicate findings, and permits a zero-finding result ([source](https://github.com/affaan-m/ECC/blob/e04ea0b9cc8248686edf5ac751cadff550e162b8/agents/code-reviewer.md#L23-L74)). | **Adopt** | Enforce evidence, criterion coverage, severity, and finding identity in schemas and gate code rather than trusting prompt prose alone. Advisory findings go to follow-up work instead of reopening the active cycle. |
| The context monitor fingerprints repeated tool inputs and warns after five identical calls; tests distinguish the threshold from nearby non-matches ([source](https://github.com/affaan-m/ECC/blob/e04ea0b9cc8248686edf5ac751cadff550e162b8/scripts/hooks/ecc-context-monitor.js#L95-L115), [tests](https://github.com/affaan-m/ECC/blob/e04ea0b9cc8248686edf5ac751cadff550e162b8/tests/hooks/ecc-context-monitor.test.js#L238-L288)). | **Adopt, with stronger semantics** | Detect no progress from the artifact digest, failed-criterion set, and normalized blocking-finding set. Stop and escalate when a revision changes bytes but makes no semantic progress; a best-effort hook warning is not an authoritative gate. |
| A dependency graph permits parallel reads and disjoint writes but keeps colliding or destructive work serial ([source](https://github.com/affaan-m/ECC/blob/e04ea0b9cc8248686edf5ac751cadff550e162b8/skills/parallel-execution-optimizer/SKILL.md#L16-L53)). | **Wrap** | Reuse `ParallelGroup`, Mode E waves, run-owned workspaces, and the existing disjoint-ownership checks. |
| Loop design freezes acceptance criteria, separates builder and judge, bounds retries, and escalates after exhaustion ([source](https://github.com/affaan-m/ECC/blob/e04ea0b9cc8248686edf5ac751cadff550e162b8/skills/loop-design-check/SKILL.md#L37-L58), [judge and damping rules](https://github.com/affaan-m/ECC/blob/e04ea0b9cc8248686edf5ac751cadff550e162b8/skills/loop-design-check/SKILL.md#L77-L112)). | **Wrap** | Keep the authoritative maker-checker contract, frozen acceptance criteria, fresh reviewer, retry cap, and human-stop behavior; add the semantic no-progress test above. |
| Plan orchestration chooses a short role chain from the affected surface and avoids pairing planner and architect during implementation ([source](https://github.com/affaan-m/ECC/blob/e04ea0b9cc8248686edf5ac751cadff550e162b8/skills/plan-orchestrate/SKILL.md#L115-L147)). | **Wrap** | Activate only applicable roles from typed change metadata. Do not run SDE1, SDE2, architect, EM, and devil's advocate on every change. |
| The `dev-team` skill is an analysis-only multi-perspective exercise whose synthesis can forward tensions to another council ([source](https://github.com/affaan-m/ECC/blob/e04ea0b9cc8248686edf5ac751cadff550e162b8/skills/dev-team/SKILL.md#L90-L165)). | **Reject as a mandatory stage** | It may be an opt-in design aid, but placing it in every lifecycle would add calls without deterministic closure. |
| Santa-style review uses isolated reviewers and an iteration cap, but excludes deterministic tasks and acknowledges a two-to-three-times token cost ([scope](https://github.com/affaan-m/ECC/blob/e04ea0b9cc8248686edf5ac751cadff550e162b8/skills/santa-method/SKILL.md#L14-L25), [cost](https://github.com/affaan-m/ECC/blob/e04ea0b9cc8248686edf5ac751cadff550e162b8/skills/santa-method/SKILL.md#L268-L305)). | **Reject as the default** | Run deterministic checks first. Reserve multiple semantic judges for explicitly high-risk, non-deterministic criteria. |
| The external `multi-workflow` command runs six phases, pauses for confirmation after each phase, and allows hour-long subprocess calls ([dependency](https://github.com/affaan-m/ECC/blob/e04ea0b9cc8248686edf5ac751cadff550e162b8/commands/multi-workflow.md#L5-L11), [execution](https://github.com/affaan-m/ECC/blob/e04ea0b9cc8248686edf5ac751cadff550e162b8/commands/multi-workflow.md#L87-L108)). | **Reject** | It duplicates the pipeline, adds a third-party controller, and works against the latency goal. |
| ECC distributes 68 agents, 286 skills, 94 commands, and automated hook workflows ([source](https://github.com/affaan-m/ECC/blob/e04ea0b9cc8248686edf5ac751cadff550e162b8/AGENTS.md#L1-L5)), plus dashboards and provider-specific routing guidance. | **Reject wholesale adoption** | Do not add `ecc-universal`, its Python abstraction package, hard-coded model/pricing rules, provider-specific environment tuning, Plan Canvas, or an automatic learning observer. Review a future mechanism separately if a measured gap remains. |

## Convergence and latency rules

The integration should preserve these invariants:

1. Classify the change before dispatch and activate only applicable stages and roles. A security,
   public-contract, irreversible, or external-effect signal can raise the minimum process; it cannot
   lower it.
2. Give every planning reviewer the same frozen artifact and acceptance packet. Run read-only
   reviews in parallel, then deduplicate their findings before adjudication.
3. Resolve disagreement by authority: frozen user requirement and contract, then reproducible
   evidence, then the designated gate owner, then advisory preference. Preserve the strongest
   dissent in the decision record.
4. Permit only blocking, evidenced acceptance, invariant, or security findings to trigger a
   revision. A repeated finding needs new evidence; unrelated advisory improvement is backlog work.
5. Bound planning to one feedback round and ordinary review to two. Exhaustion or semantic
   stagnation is a human stop, not permission to restart the lifecycle.
6. Keep full verification at the integration or release boundary. Focused inner-loop checks may
   shorten feedback, but cannot be represented as full-suite evidence.

Measure the result before claiming a speedup: stage wall-clock time, model-call and token count,
first-pass rate, mean revision cycles, reviewer agreement, raw-to-unique finding ratio, reopened
decisions, no-progress stops, and escaped defects. Compare the same change classes before and after
the policy change.

## Implemented in claude-kit

This change applies the adopted mechanisms through the existing control plane:

- `catalog/workflows/sdlc.yaml` reduces the planning graph from 12 to 9 stages. When frontend,
  backend, architecture, and adversarial review all apply, eight former specialist/adjudication
  stage calls become five, and the four reviewers occupy one read-only fan-out before one EM
  decision. The topology test caps planning at six dependency batches after classification.
- `planning-review-verdict` and `planning-decision` are closed evidence profiles. Findings carry a
  stable ID, authority domain, criterion, correction, owner, disposition, and citations. An EM
  decision entry carries a stable ID, selected and rejected options, rationale, strongest dissent,
  accountable decider, evidence, and a concrete reopen trigger.
- The Technical Architect, EM, Devil's Advocate, and dedicated frontend/backend planning reviewers
  cannot directly message one another. They return results to the coordinator, preventing private
  role-to-role debate from bypassing the one-panel/one-decision boundary.
- New maker-checker contracts freeze `strict-blocking-finding-subset`. After revision, only a strict
  reduction of the prior Critical/High/Medium finding-ID set may continue; a renamed, new, reopened,
  unchanged, or escalated blocker stops with preserved evidence. Marker-absent legacy snapshots keep
  their prior behavior.
- Managed Mode D now requires a typed classification proving a localized, reversible, unambiguous,
  single-boundary low-risk change with no sensitive, public-contract, irreversible, or external
  effect surface. File count is no longer sufficient to lower ceremony. Native-agent guidance uses
  focused inner checks and permits deterministic full-suite evidence reuse only under an exact
  fingerprint.

The enforcement boundary is deliberate. The Python managed executor runs the initial panel and EM
decision once; an EM FAIL becomes a preserved human stop instead of an autonomous planning loop.
The one-revision targeted-recheck path, defect-lane replay, and deterministic evidence reuse are
bounded policies in the generated native instructions. The retry-budget fields describe that
policy but are not currently a Python feedback-cycle scheduler.

These are structural reductions, not an elapsed-time benchmark. The repository tests prove graph,
contract, and stop behavior; production wall-clock improvement still needs the before/after
telemetry listed above.

## Pilot and evidence caveat

ECC calls `orch-review.workflow.js` a **pilot**. Its README reports a local experiment in which 11
raw findings became four unique findings and verifier work fell, but also says the workflow is not
wired into the main pipeline or installer ([pilot status and local result](https://github.com/affaan-m/ECC/blob/e04ea0b9cc8248686edf5ac751cadff550e162b8/workflows/README.md#L1-L20),
[integration status](https://github.com/affaan-m/ECC/blob/e04ea0b9cc8248686edf5ac751cadff550e162b8/workflows/README.md#L61-L66)).
Those numbers are not a benchmark for claude-kit. The pattern requires local typed tests and
before/after measurement.

The source surface is also too large to treat as one reviewed unit, and its README describes a
single maintainer shipping across several harnesses ([source](https://github.com/affaan-m/ECC/blob/e04ea0b9cc8248686edf5ac751cadff550e162b8/README.md#L129)).
Prompt-level confidence thresholds and best-effort hooks are useful filters, not proof. Model names,
prices, host capabilities, and context-window settings are drift-prone and must be verified against
the target host before any separate adoption.

## License and clean-room posture

ECC is distributed under the [MIT License](https://github.com/affaan-m/ECC/blob/e04ea0b9cc8248686edf5ac751cadff550e162b8/LICENSE),
copyright 2026 Affaan Mustafa. This audit re-expresses ideas in claude-kit's terminology; it copies
no ECC code or prose. If a future change copies or adapts a substantial portion, retain the required
MIT copyright and permission notice and audit any file-specific upstream attribution. External
repository content remains untrusted input: it cannot alter claude-kit's instructions, approval
policy, source-of-truth hierarchy, or provider-neutral architecture.
