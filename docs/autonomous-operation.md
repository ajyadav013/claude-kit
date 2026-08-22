# Autonomous operation — running the kit unattended, safely

claude-kit installs one versioned provider-selectable loop interface at
`.ckit/scripts/sdlc-loop.sh`. New unattended iterations currently fail closed before either Claude
Code or Codex starts, because the portable runtime cannot prove descendant-process containment.
This document records that boundary and the controls required for a future promotion.

Run `ckit doctor` before automating a host. The compatibility catalogs pin the minimum and currently
tested host versions; CLI flags can drift between host releases.

## 1. Native host boundaries

The experimental managed executor adapts these native commands; the fail-closed compatibility loop
does not invoke either one:

```text
Claude Code:  claude -p --permission-mode <mode> --max-budget-usd <amount> <prompt>
Codex:        codex exec --ephemeral --sandbox <sandbox> --cd <project> -
```

Their controls are deliberately not normalized into a fictional common permission model:

- Claude Code supports native permission modes and a per-run USD ceiling, but the compatibility loop
  does not expose or apply them.
- Codex Preview uses its native sandbox selection. It does **not** receive a fabricated USD ceiling;
  managed execution relies on the provider sandbox and its own ledger boundaries.
- Headless permission prompts cannot be answered. Pre-authorize only the operations the run needs,
  and treat every issue, PR, and prompt body as untrusted input.
- Review and trust the project before relying on Codex project hooks. A headless command is not a
  substitute for that trust decision.
- Validate before the run. Missing or malformed host settings can remove controls you expected to
  be present.

Claude's `--bare` strips project instruction discovery and hooks, so do not combine it with a kit
run. The analogous general rule for either host is: do not select a mode that disables the native
instructions, skills, or hooks on which your operating contract depends.

## 2. The shared resume contract

Fresh native installs keep the long-running control plane under `.ckit`:

```text
.ckit/CONTINUITY.md
.ckit/config/stack-catalog.snapshot.yaml
.ckit/state/pipeline-snapshot.json
.ckit/agent-memory/
.ckit/artifacts/
```

Start a new run with `ckit pipeline start`; use `pipeline adopt` for work already in flight. Resume
means reload and continue at the first unresolved gate, never replay committed work. Before a gate
transition, a manual run's `record-findings` binds all five exact severity counts to the current
commit and a project-contained evidence report. A managed run instead derives the canonical finding
index from its validated owner-stage records and rejects caller counts that differ.

Completion is also explicit. The loop accepts success only when the snapshot says `completed` and
`ckit pipeline validate . --strict` succeeds. A final-gate token or prose claim alone is not enough.
The adjacent evidence hashes detect drift, but they are integrity checks rather than signatures: a
writer that can alter both an artifact and its ledger entry remains inside the trust boundary.

Legacy `.claude` state is read only as a compatibility fallback. Migrate it to `.ckit` before a
native runtime transition; see [runtime migration](runtime-migration.md).

### Managed stage execution (Preview)

`CKIT_EXPERIMENTAL=1 ckit pipeline run --provider claude|codex` is the bounded executable path for
Modes A–D. It launches native workers through argv arrays with prompt input on stdin, persists stage
claims/results and bounded output artifacts under `.ckit`, and resumes the same frozen workflow after
a provider switch. Task-dependent stage conditions must be supplied as repeatable
`--condition NAME=true|false` values on the first invocation; they are then immutable in the shared
ledger.

The command stops at an unresolved gate instead of resolving it by model prose. A successful managed
owner must return the exact frozen typed evidence envelope. The coordinator checks required fields,
pass predicates, and normalized findings; writes root-owned content-addressed records; and derives
the gate bundle from that exact attempt. The controlling session inspects those records, records the
matching finding set, performs the appropriate gate transition, and invokes `pipeline run` again.
Managed PASS/accepted-risk is rejected unless the frozen gate-owning stage and its semantic evidence
both succeed. A human stop exits 3 and must remain a stop. Generic local approval evidence is not
a stage/attempt/workspace-scoped, one-shot authorization, so managed `approved` resolution is
unsupported and leaves the stop pending. A recorded rejection is only a replan/abort signal.

The closeout graph does not mix those boundaries: a normal `pull-request-prepare` worker performs
the local checks and writes the commit-bound plan, then the typed `pull-request` leaf stops before
the external API call. A native-role fallback cannot satisfy that leaf.

Portable process-group cleanup cannot contain a deliberately re-sessioned (`setsid`) descendant.
Consequently the managed contract adds `process.descendant_containment` to every selected shell-
capable Claude role. The bundled Codex adapter has a narrow passive exception: exact pinned hosts
may run a read-only, nondelegating role only after a fail-closed probe disables every command,
extension, and delegation surface and the coordinator supplies a bounded tracked-text projection.
All other Codex roles require descendant containment. The built-in subprocess backend does not
attest it; those invocations stop before process creation. This is an explicit Preview limitation,
not a retryable or resolvable worker failure: use an independently contained backend or obtain a human
acknowledgement before choosing the manual orchestration path.

The runner uses one persistent run-owned integration worktree created from `HEAD`. The selected
provider's scaffolded files and all application inputs must therefore be committed first; only
mutable `.ckit/` state is exempt. The runner refuses missing or dirty provider/application context
and preserves the worktree for inspection. It does not merge to the main checkout automatically.
Mode E requires `pipeline run --program-manifest <project-contained-file>` and uses a separate
typed program ledger for waves, units, budgets, evidence, checkpoints, and no-replay. The bundled
adapters can execute pure read/search audits only. Gate, shell, write, and closeout units require an
independently contained dispatcher, while every irreversible unit stops at the absent consume-once
approval broker. Mode E therefore remains Degraded Preview, not general autonomous execution.

## 3. Use the fail-closed loop interface

From the project root, the versioned interface strictly validates an already-completed run. Any
active, waiting, or aborted run exits 3 without launching Claude or Codex:

```bash
.ckit/scripts/sdlc-loop.sh
```

Automated headless iterations are currently unsupported and fail closed before either a host process
or transition token is created. A portable process group cannot prove that a hostile host left no
detached descendants, so it cannot safely enforce the former “one transition per invocation” claim.
The script is retained as the versioned interface and can still validate an already-completed run,
but it does not launch new unattended work. Use the interactive lifecycle. Do not bypass this stop
with a prompt convention or environment token; promotion requires a true descendant-containment
primitive and a crash-recoverable coordinator identity.

The script reads `status` and `last_gate_resolved` from the shared snapshot:

- a missing or malformed snapshot exits nonzero;
- every non-completed status is unsupported and exits 3;
- a completed but invalid snapshot is refused; and
- only a strictly validated completed snapshot exits zero.

A nonzero exit is a request for human inspection. Read `.ckit/CONTINUITY.md`, the snapshot, and the
current diff. Do not bypass the containment stop with environment variables or prompt conventions.

## 4. Autonomy and permissions

The installed `autonomy-levels` rule defines five semantic ceilings. Provider controls implement
only the parts their host supports.

| Kit level | Claude Code guidance | Codex Preview guidance |
|---|---|---|
| `advisory` | `plan` | read-only sandbox/approval posture; verify host policy |
| `assisted` (default) | interactive/manual approval | interactive approval; do not treat unattended denial as consent |
| `autonomous-local` | `acceptEdits` with push/PR denied | bounded `workspace-write` sandbox with external effects denied |
| `autonomous-pr` | narrowly allow branch/commit/push/draft-PR; merge denied | explicitly configure only equivalent external effects; merge remains human |
| `enterprise-controlled` | managed policy plus audit hook | organization-managed Codex policy plus reviewed trusted hooks |

`bypassPermissions` maps to no kit autonomy level. A provider's most permissive mode is not a
portable autonomy setting. The generated Codex agents keep semantic permission and write-scope
instructions, but native sandbox and approval policy remain authoritative; equivalent per-agent
enforcement is not yet proven.

## 5. Anti-gaming checks

| Sign | Meaning | Response |
|---|---|---|
| A gate advanced without its artifact | verdict may be asserted rather than earned | rerun strict validation and inspect the exact evidence binding |
| “Tests pass” without captured runner output | fabricated or assumed verdict | treat it as an auto-Critical finding under the quality-gate policy |
| An iteration changes only continuity/state | progress theater or a genuine stall | stop; inspect the diff and host transcript |
| Review/security gates pass implausibly fast | rubber-stamping | sample the independent reports and require the Devil's Advocate protocol |
| Budget/iterations move while status and gate do not | runaway or thrash | let the loop stop; do not auto-restart |

The governing principle is “Verify means run it, not imagine it.” The Python lifecycle enforces
order, allowed transitions, findings/evidence bindings, and hashes. Managed A–D and Mode E also
validate their frozen structured evidence profiles, but the manual file-evidence API does not
semantically prove that an arbitrary file means the tests passed.

## 6. CI and issue-triggered runs

The kit deliberately ships no provider-specific CI workflow template. If you wire either headless
host into CI, preserve these constraints:

1. A maintainer action, such as applying a restricted label, is authorization. Issue content is not.
2. Pass issue/PR text as data, never interpolate it into shell source.
3. Give the job a minimal token and host sandbox. Branch protection remains the final boundary.
4. Stage work through artifacts; a missing predecessor artifact stops rather than being guessed.
5. Deliver at most a draft PR. Merge stays human.
6. Bound every run. Claude gets iteration + USD + permission brakes; Codex gets iteration + sandbox
   + stall brakes unless your surrounding CI supplies an independent budget control.
7. Run `ckit pipeline validate . --strict` between stages.

## Related

- [Runtime support contract](runtime-support.md)
- [Runtime migration guide](runtime-migration.md)
- [Organization capabilities](org-capabilities.md)
- Installed rules: `autonomy-levels`, `human-in-the-loop`, `risk-classification`, `continuity`, and
  `agent-resilience`
