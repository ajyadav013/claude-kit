# CONTINUITY — Working Memory

## Current task
**`DELETE /tasks/{id}` — remove a task by id (Go / net-http backend lane, standard profile).**
Status: **COMPLETE** — all gates passed, defect loop closed, ready for PR.

## Phase history / verdict log

| Phase | Gate | Verdict | Evidence |
|------|------|---------|----------|
| Spec | spec-complete | PASS | `docs/specs/delete-task_spec.md` |
| Spec review (EM) | em-approved | APPROVED | `.sdlc-evidence/em-approved.txt` |
| Code review | code-review | PASS (0C/0H/0M, 3 low) | `.sdlc-evidence/code-review.txt` |
| Build | build-green | PASS (`go build`+`go vet`+`gofmt`) | `.sdlc-evidence/build-green.txt` |
| Tests | test-coverage | PASS (7 tests, 85.2%, `-race` clean) | `.sdlc-evidence/test-coverage.txt` |
| Security | security-clear | SECURITY CLEAR (0C/0H/0M, 4 low demo) | `.sdlc-evidence/security-clear.txt` |
| **Devil's advocate** (spawned on the unanimous PASS) | — | **OVERTURNED → 1 Medium** | `.sdlc-evidence/devils-advocate.txt` |
| Defect loop | contract-clear | **REFUSED while Medium open** | `.sdlc-evidence/gate-refused.txt` |
| Fix + re-verify | — | DA **UPHELD** (Medium resolved) | `.sdlc-evidence/defect-loop-reverify.txt` |
| Contract | contract-clear | CONTRACT CLEAR (additive) | `.sdlc-evidence/contract-clear.txt` |
| Acceptance | (acceptance) | ACCEPT (5/5 criteria MET) | `.sdlc-evidence/acceptance.txt` |

## The defect loop (the story of this run)
Four reviewers returned a unanimous clean verdict. The `devils-advocate`, spawned *because* of that
unanimity, attacked the id-parsing seam over a **raw TCP socket** (the Go `http.Client` used by every
test silently normalizes paths) and found a **Medium**: `strconv.Atoi` aliased `01`/`+1`/`%2B1`/
`00000000001` onto task `1` and deleted it, while `-1` returned 404 — inconsistent and destructive.
The deterministic gate then **refused** to close `contract-clear` while the Medium was open. The fix
(`server.go`: reject non-canonical ids) + a mux-level regression test + a tightened spec criterion 3
closed it; the DA **re-verified UPHELD** over the raw wire. 7/7 tests green, `-race` clean.

## Final state
- last gate passed: **contract-clear**; open findings: **critical=0 high=0 medium=0 low=1** (non-blocking).
- `pipeline validate` → coherent.
- Blind-spot recorded: *path/id-parsing handlers must be tested at the mux level or over a raw socket —
  Go's `http.Client` normalizes paths and hides aliasing / leading-zero / encoded-char bugs.*
