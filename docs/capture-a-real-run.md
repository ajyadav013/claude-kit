# Capture a real `/sdlc` run

The repo ships a **real, harness-captured** run under [`examples/real-run/`](../examples/real-run/)
(produced exactly the way this guide describes) alongside a hand-written **synthetic** walkthrough. The
most convincing evidence, though, is *your own* run: a real request that flowed through the pipeline,
with the real spec, real gate verdicts, and the real diff it produced. This guide turns one completed
run into a publishable, redaction-scrubbed bundle.

> **You run this — not the kit.** `/sdlc` is interactive inside Claude Code; Preview Codex managed
> runs use the provider entry points documented in the CLI guide. The script here only *collects and
> scrubs* what a finished run left behind; it never drives the pipeline and never edits your project.
> Supporting a Codex or dual-runtime control-plane layout is not a claim of live-host parity.

## Where a run leaves its evidence

A `/sdlc` run scatters its artifacts on purpose — two of the four are gitignored runtime state, so
they never show up in a normal `git diff`:

| Artifact | Location | Tracked? |
|---|---|---|
| Feature spec | `docs/specs/<feature>_spec.md` | committed |
| Run lifecycle and gate state (resolved gate, exact findings, evidence hashes, not-applicable conditions, accepted risks, terminal summary) | `.ckit/state/pipeline-snapshot.json` | shared provider-neutral runtime state |
| Verdict log / phase history | `.ckit/CONTINUITY.md` | shared provider-neutral working state |
| Install snapshot (profile + resolved gate set) | `.ckit/config/stack-catalog.snapshot.yaml` | shared provider-neutral install state |
| The code itself + the PR | git history (`diff` vs your base branch) | committed |

Fresh `--runtime claude`, `codex`, and `both` installs use the `.ckit` paths above. An unmigrated
legacy Claude install uses the corresponding `.claude/{state,config}` paths and
`.claude/CONTINUITY.md`. The collector selects one complete layout with neutral state taking
precedence; it never fills missing `.ckit` files from `.claude` or combines two histories.
Control-plane markers and copied state files must be regular files reached without symlinks; the
collector fails closed instead of following an unsafe path into a publishable bundle.

## Steps

1. **Run a real task to completion** in a project that has claude-kit installed:

   ```text
   /sdlc Add a CSV export button to the reports page
   ```

   Let it run through its gates. A small, real feature is more convincing than a toy.

2. **Capture the bundle** from the project root:

   ```bash
   # from your project (with fresh .ckit/ or an unmigrated legacy .claude/ control plane):
   bash /path/to/claude-kit/scripts/capture-sdlc-run.sh --base main --slug csv-export
   ```

   Options: `--project DIR` (capture a different checkout), `--out DIR` (choose the output folder),
   `--base BRANCH` (what to diff the code against; default `main`), `--slug NAME` (label the folder).
   Run with `--help` for the full list. The script is read-only against your project.

3. **Review the secret scan.** The script lists any files matching *generic* secret shapes (private
   keys, AWS/GitHub tokens, `password=`/`token=` assignments, bearer tokens). It prints **file names
   only**, never the secret values. Inspect each flagged file.

4. **Finish the redaction checklist.** Every bundle gets a `REDACTION-CHECKLIST.md`. The automated
   scan cannot know *your* internal names — company, team, service, repo, host, cluster, namespace,
   cloud project, customer/personal data. Replace real identifiers with neutral placeholders
   (`acme`, `example.com`, `service-a`) rather than deleting them, so the run still reads as a story.

5. **Publish what you want.** Copy the scrubbed files into [`examples/`](../examples/) (mirroring the
   `01-request.md → 02-feature-spec.md → 03-story-breakdown.md → 04-gate-verdicts.md →
   05-sample-pr.diff` layout) or into a blog post / PR description. Keep a private, unscrubbed copy if
   you need the originals.

## What the bundle contains

```text
claude-kit-run-<timestamp>-<slug>/
├── specs/                         # docs/specs/*_spec.md
├── state/
│   ├── pipeline-snapshot.json     # lifecycle, gates, findings, evidence, accepted risks
│   └── stack-catalog.snapshot.yaml
├── evidence/                      # every project-contained artifact referenced by the snapshot
├── continuity.md                  # verdict log / phase history
├── git/
│   ├── log.txt                    # recent commits
│   ├── diff.stat.txt              # files changed (summary)
│   └── changes.diff               # the full diff vs your base branch
└── REDACTION-CHECKLIST.md         # finish this before publishing
```

Missing optional run files are reported, not fatal — if you point the script at a checkout where
`/sdlc` has not run yet, it tells you what it could not find. A snapshot whose declared evidence is
missing, outside the project, unreadable, or malformed is different: capture fails rather than
publishing a bundle that claims to be self-contained. The collector requires `python3` to parse the
snapshot structurally; it never scrapes nested JSON with text tools.
