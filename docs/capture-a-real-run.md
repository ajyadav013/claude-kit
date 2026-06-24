# Capture a real `/sdlc` run

The repo ships a **synthetic** worked example under [`examples/`](../examples/) — useful, but
hand-written. The most convincing evidence is *your own* run: a real request that flowed through the
pipeline, with the real spec, real gate verdicts, and the real diff it produced. This guide turns one
completed run into a publishable, redaction-scrubbed bundle.

> **You run this — not the kit.** `/sdlc` is interactive (it runs inside Claude Code). The script here
> only *collects and scrubs* what a finished run left behind; it never drives the pipeline and never
> edits your project.

## Where a run leaves its evidence

A `/sdlc` run scatters its artifacts on purpose — two of the four are gitignored runtime state, so
they never show up in a normal `git diff`:

| Artifact | Location | Tracked? |
|---|---|---|
| Feature spec | `docs/specs/<feature>_spec.md` | committed |
| Gate state (last gate passed, open findings by severity, evidence, overrides) | `.claude/state/pipeline-snapshot.json` | gitignored runtime state |
| Verdict log / phase history | `.claude/CONTINUITY.md` | gitignored runtime state |
| Install snapshot (profile + resolved gate set) | `.claude/config/stack-catalog.snapshot.yaml` | committed |
| The code itself + the PR | git history (`diff` vs your base branch) | committed |

## Steps

1. **Run a real task to completion** in a project that has claude-kit installed:

   ```text
   /sdlc Add a CSV export button to the reports page
   ```

   Let it run through its gates. A small, real feature is more convincing than a toy.

2. **Capture the bundle** from the project root:

   ```bash
   # from your project (the one with .claude/ in it):
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
│   ├── pipeline-snapshot.json     # gate state, findings, evidence, overrides
│   └── stack-catalog.snapshot.yaml
├── continuity.md                  # verdict log / phase history
├── git/
│   ├── log.txt                    # recent commits
│   ├── diff.stat.txt              # files changed (summary)
│   └── changes.diff               # the full diff vs your base branch
└── REDACTION-CHECKLIST.md         # finish this before publishing
```

Missing files are reported, not fatal — if you point the script at a checkout where `/sdlc` hasn't run
yet, it tells you which artifacts it couldn't find.
