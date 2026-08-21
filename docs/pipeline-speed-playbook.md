# Pipeline Speed Playbook — for in-flight runs (installs ≤ 0.81.0)

Run-level instructions that recover most of 0.82.0's speed levers **without upgrading**. Each
recipe says what to paste into your orchestrator dispatch (or run yourself). After
`claude-kit upgrade`, the payload carries all of this natively and this doc is obsolete.

## 1. Probe model tiers before any fan-out

Most agents pin `model: sonnet`/`opus` in frontmatter; if your deployment doesn't serve an alias,
the spawn dies **instantly with ~0 tokens**. Before the first fan-out, spawn one trivial agent per
tier ("reply with one word"). On instant death: pass an explicit `model:` override on **every**
dispatch for that run and note it in CONTINUITY.md. Re-probe each new session — availability
flips. Refresh credentials before long sessions (e.g. `! gcloud auth login --update-adc` on
Vertex).

## 2. One story per dispatch + resume from the snapshot

Ask for one story per orchestrator invocation, not "stories 2–5". A 90-minute dispatch that dies
at minute 85 loses everything unwritten; two 40-minute dispatches lose at most half. On crash,
run `claude-kit pipeline resume` and re-enter at the first unresolved gate reported by the
schema-v2 snapshot (`last_gate_resolved` records the latest passed, not-applicable, or accepted-risk
transition). Never re-run resolved gates or re-apply committed edits.

## 3. Bound the orchestrator's own verification (paste into the dispatch)

> Your independent VALIDATE is exactly: re-run the test/lint/build commands (capture exit codes),
> `git diff --name-only` vs the story's declared file scope, record the printed coverage number.
> Nothing deeper — no line-by-line diff reading, no content proofs. The code reviewer owns
> correctness. Reviewer reports: read the verdict + severity counts + findings table only; persist
> the body verbatim without re-analyzing it.

## 4. Cap the review chain; accept residual Medium risk explicitly

State at dispatch: "2 full re-review generations, then escalate." Critical and High remain blocked.
A human may accept a residual Medium only with the structured command and all accountability fields:

```bash
claude-kit pipeline accept-risk <gate> \
  --finding-id <id> --reason '<why>' --accepted-by '<human or accountable role>' \
  --owner '<role>' --ticket '<issue>' --revisit '<expiry or trigger>' \
  --compensating-control '<control, if any>' --evidence <artifact>
```

The ledger records `accepted-risk`, never PASS, and binds it to the current gate, commit, evidence,
finding set, and gate-definition digest. `validate`/`status` keep it visible. If it becomes stale,
fix the finding or use `accept-risk --refresh` for a new human attestation; never hand-edit the
ledger and never fall back to `close-gate --force`.

## 5. Fan out disjoint stories across orchestrators

When ≥2 unblocked stories have disjoint file boundaries: one orchestrator per story group, each in
its own `git worktree` (each gets its own CONTINUITY/snapshot). Merge in dependency order — you
approve each mainline merge — then run the run-level gates (test coverage, security) on the merged
output in the primary checkout.

## 6. Route ceremony by story risk; batch the mechanical tail

Low-risk stories (docs/changelog/packaging/config; nothing touching auth, queries, secrets,
tenancy, migrations): developer → code reviewer → tester only. Batch up to 3 of them into one
dispatch, one commit per story. Any story touching a sensitive surface gets the full chain —
decide by surface, never by size.

## 7. Keep the spec requirements-sized

Move executed-evidence blocks (command output, measurements) out of `docs/specs/*` into
`.claude/state/gate-evidence/`, leaving one-line citations. Every agent reads the spec on every
spawn — a 7,000-line spec is a per-spawn tax.

## 8. Two habits that round it out

Queue non-blocking questions in CONTINUITY "Open Questions"; raise them as one batch at the next
gate (blocking stops stay immediate). Start shared test services once per run and reuse across
defect-loop cycles (reset state between tests; the final clean-cold-start check still runs).

## What NOT to cut

Code review (it catches Criticals that reading alone approves), the security pass on sensitive
surfaces, and the real-environment verification your project relies on. Speed comes from cutting
re-verification and idle ceremony — not verification.
