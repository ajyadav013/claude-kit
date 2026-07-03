# Demo Script — 60–90s terminal capture

**Goal:** After 90 seconds, a viewer should believe: *"this is real, gated, and catches what a rubber-stamp review misses."* The devils-advocate catching a Medium bug a unanimous panel missed is the emotional peak.

Everything below is grounded in the genuine captured run in `examples/real-run/` (Go `net/http` `DELETE /tasks/{id}`). Do not script anything that did not happen — quote the committed artifacts.

## Constraints

- **Runtime:** 60–90 seconds total (90s hard cap)
- **Format:** Terminal capture (asciinema/asciicast, or any `.cast` → GIF/mp4 recorder)
- **Dimensions:** 1280×720 minimum; readable font (14–16pt monospace)
- **Audio:** Not required; use on-screen captions for narration
- **Authenticity:** Replay the existing `examples/real-run/cast/gate-checks.cast` (genuine gate checks: 7 tests, 85.2% coverage) plus the committed artifact text under `run-artifacts/`. Do NOT re-run live or fabricate screens. Every displayed line must come from a file in `examples/real-run/`.

## Shot list

Windows below sum to 90s (the hard cap); trim in post to land in the 60–90s band.

| # | Time | On-screen action | Caption |
|---|------|------------------|---------|
| **1** | 0:00–0:08 | Show the plugin install one-liner in a Claude Code session: `/plugin marketplace add ajyadav013/claude-kit` → `/plugin install claude-kit@claude-kit` → confirmation message. (Alternative: `pip install claude-code-kit`.) | "Install as a Claude Code plugin (or `pip install claude-code-kit`)." |
| **2** | 0:08–0:18 | Run `/sdlc Add DELETE /tasks/{id} to a Go net/http task API`. Show the command executing and the pipeline launching from the first gate (`spec-complete`). | "One command drives spec → review → build → test → security → ship." |
| **3** | 0:18–0:35 | Show the recorded gate state: `spec-complete` ✓, `em-approved` ✓, `code-review` ✓, `build-green` ✓, `test-coverage` ✓, `security-clear` ✓ — with the four reviewer verdicts underneath (code-review PASS, em APPROVED, security CLEAR, acceptance ACCEPT, from `run-artifacts/devils-advocate.txt` line 3). Then note the kit spawns the devils-advocate because that pass was unanimous. | "Four reviewers return a unanimous pass — so the kit spawns a devils-advocate." |
| **4** | 0:35–0:50 | Show the devils-advocate excerpt from `run-artifacts/devils-advocate.txt`: the FINDING 1 [Medium] server.go:25 id-aliasing summary (`strconv.Atoi` accepts `+`, leading zeros, arbitrary zero-padding, so `"01"`, `"+1"`, `"%2B1"`, `"00000000001"` are all treated as id 1 and DELETE it) plus the raw-socket reproduction (`DELETE /tasks/01 -> HTTP/1.1 204 No Content (task 1 deleted)`). Highlight `VERDICT: OVERTURNED` and `FINDINGS: critical=0 high=0 medium=1 low=1`. | "Devils-advocate attacks over a raw TCP socket. Finds a Medium: /tasks/01 deletes task 1." |
| **5** | 0:50–1:00 | Show the gate refusal verbatim from `run-artifacts/gate-refused.txt`: `FAIL  cannot close 'contract-clear': medium=1 open finding(s) must be resolved first`. | "Gate REFUSES to advance: an open Medium blocks it, per quality-gates.md." |
| **6** | 1:00–1:15 | Show a one-line fix being applied (caption note: "reject non-canonical ids, server.go:25"), then the re-verification excerpt from `run-artifacts/defect-loop-reverify.txt`: `WIRE DELETE /tasks/01 -> "HTTP/1.1 400 Bad Request"` … `VERDICT: UPHELD`, `FINDINGS: critical=0 high=0 medium=0 low=1`. | "Fix + mux-level regression test. Re-verify over the raw wire. UPHELD." |
| **7** | 1:15–1:25 | Replay `cast/gate-checks.cast` (gate checks running green): `build` → `vet` → `gofmt` → `test` → `coverage: 85.2% of statements`. Show the green output. | "Gate checks pass: 7 tests, 85.2% coverage." |
| **8** | 1:25–1:30 | Show the final recorded state from `captured-bundle/state/pipeline-snapshot.json`: `last_gate_passed: contract-clear`, `open_findings: {critical:0, high:0, medium:0, low:1}`. | "Ship-ready — no open Critical/High/Medium. Gates backed by real command output." |

Notes on fidelity:

- Shot 3 lists the seven real gate keys from `pipeline-snapshot.json`'s `gate_evidence` (`spec-complete`, `em-approved`, `code-review`, `build-green`, `test-coverage`, `security-clear`, `contract-clear`). "Acceptance" is a **reviewer verdict** (ACCEPT), not a pipeline gate — show it as a verdict, not a gate row.
- `pipeline status` (`run-artifacts/pipeline-status.txt`) prints `task / profile / scope / mode / stage / last gate passed / open findings / next`; it does **not** print a "spawning devils-advocate" line. Convey the unanimity → devils-advocate spawn via a caption, not by inventing terminal output.
- The `-race` clean claim is supported by `run-artifacts/defect-loop-reverify.txt` ("`go test -race` clean (7/7)") and `run-artifacts/test-race.txt`; include it only if you show that source.

## Assets to use

All material exists in `examples/real-run/`:

1. **Asciicast of gate checks:** `cast/gate-checks.cast` (replay with `asciinema play`, or convert to GIF/mp4 via `agg`/`svg-term`/`asciinema-player`). Static render: `cast/gate-checks.svg`.
2. **Devils-advocate verdict:** `run-artifacts/devils-advocate.txt` (excerpt: finding summary + raw-socket reproduction + `VERDICT: OVERTURNED`).
3. **Gate refusal:** `run-artifacts/gate-refused.txt` (`FAIL  cannot close 'contract-clear': medium=1 open finding(s) …`).
4. **Re-verification verdict:** `run-artifacts/defect-loop-reverify.txt` (excerpt: fix verified over the raw wire + `VERDICT: UPHELD`).
5. **Pipeline state:** `captured-bundle/state/pipeline-snapshot.json` (source for the `pipeline status` view; `last_gate_passed: contract-clear`, `open_findings: {…, low:1}` after the fix). Human-readable form: `run-artifacts/pipeline-status.txt`.
6. **The feature under test:** Go `DELETE /tasks/{id}` on a `net/http` task API — source in `sample-app/` (`server.go`, `store.go`), described in `examples/real-run/README.md`.

Do NOT invent UI, web views, or dashboard screens — none exist. This is a terminal-only capture.

## Post-production

1. **Trim to 60–90s.** If the install or `/sdlc` invocation runs long, cut dead time (`asciinema cut` or a video editor).
2. **Add captions** (overlay text or interstitial slides) per the table above. Make captions large enough to read at 1280×720.
3. **Export as GIF + mp4:**
   - GIF (for inline README embedding): e.g. `agg gate-checks.cast demo.gif`, or `svg-term`.
   - mp4 (for platforms that don't auto-play GIF): screen-record `asciinema-player`, or convert the GIF with `ffmpeg`.
4. **Verify readability:** font must be legible at 1280×720; test on a phone screen.
5. **Where it lands:**
   - **README.md:** replace the `<!-- DEMO PLACEHOLDER … -->` comment (already present just above the badge row) with the demo GIF/video embed.
   - **Launch posts** (HN/Reddit/social): inline the GIF or link the mp4.
   - **Anthropic plugin directory submission:** attach the mp4 as a demo asset if the submission form allows.

## Acceptance criteria

- [ ] Total runtime 60–90 seconds (90s hard cap).
- [ ] Every shot maps to a file that exists in `examples/real-run/` (no invented content or UI).
- [ ] Displayed terminal text is quoted from the committed artifacts, not paraphrased into fake output.
- [ ] The devils-advocate catch (shot 4) is the peak — the viewer sees the raw-socket reproduction and understands this is not a rubber stamp.
- [ ] The gate refusal (shot 5) is the trust moment — the harness enforces the rule, not just the agent.
- [ ] No fabricated UI, dashboards, or web views (terminal only).
- [ ] Captions are readable at 1280×720.
- [ ] Final artifact is a GIF (for README) + mp4 (for platforms that need it).
