# Rules context budget — the auto-load problem and the redesign options

> **Status: DESIGN SPEC, decision pending.** Nothing in this document is implemented yet. It is
> the verified problem statement + measured data + candidate directions for a 0.59.0-scale
> change to how the kit ships rule content.

## The verified problem

Claude Code **natively auto-loads `.claude/rules/*.md`** (recursively; shipped in CC 2.0.64 —
the kit's entire lifetime). Per the official memory documentation: rules **without `paths:`
frontmatter load at launch, unconditionally**, at the same priority as `.claude/CLAUDE.md`;
rules *with* `paths:` load only when Claude touches a matching file.

All 25 core kit rules are unscoped. Measured empirically (headless `claude -p "Reply with
exactly: OK"` runs, 2026-07-07; total input = `input + cache_creation + cache_read` from
`--output-format json`):

| Scenario | Total input tokens |
|---|---|
| Empty directory (harness baseline) | 59,843 |
| Default scaffolded project (react + fastapi + postgres) | 163,759 |
| Same project, `.claude/rules/` removed | 66,728 |

**Attribution: `.claude/rules/` = 97,031 tokens (93% of the kit's 103,916-token injection).
Everything else the kit installs — CLAUDE.md, 42 skills, 28 agents, hooks, settings — totals
6,885 tokens.** The lean design works everywhere except the one directory the original design
assumed was inert, on-demand reference material. `CLAUDE.md`'s "live on-demand in
`.claude/rules/`" sentence is false under real semantics.

Cross-check: 258,098 bytes of core rules at the measured 2.66 bytes/token ≈ 97,029. Exact.

(Stack **overlay** rules are mostly unaffected at launch: 12 of 13 carry `paths:` — a prior
pass scoped them for exactly this reason — and load only when matching files are touched.
`mongodb-patterns.md` (~3k tokens) is the *documented, test-pinned* exception: a document
store has no reliable file signal, and a glob that never matches would mean the rule never
loads. Whether that trade still holds belongs inside this redesign, not as a side patch. The
Cursor export is also unaffected — `.mdc` projection is on-demand-by-description by design.
Note the asymmetry that pass left behind: overlays were scoped because unscoped rules "ride
every session," yet the core set was declared an always-on contract without measuring its
cost, and `CLAUDE.md` kept claiming on-demand. The measurement above is what's new.)

## Per-rule weight (sorted; ~= bytes / 2.66 for tokens)

| bytes | lines | file |
|---:|---:|---|
| 23,152 | 559 | testing.md |
| 22,601 | 392 | mandatory-workflow.md |
| 17,009 | 229 | agent-guardrails.md |
| 15,020 | 332 | linting-and-formatting.md |
| 13,296 | 422 | design-patterns.md |
| 12,389 | 353 | responsive-and-accessibility.md |
| 11,115 | 153 | devops-observability.md |
| 11,087 | 156 | human-in-the-loop.md |
| 10,834 | 323 | code-organization.md |
| 10,818 | 143 | resilience-engineering.md |
| 10,739 | 330 | documentation.md |
| 10,440 | 157 | evals.md |
| 10,197 | 164 | wave-orchestration.md |
| 9,643 | 136 | quality-gates.md |
| 9,626 | 144 | tool-design.md |
| 9,169 | 118 | reasoning-techniques.md |
| 8,744 | 145 | continuity.md |
| 8,056 | 120 | model-tiers.md |
| 7,660 | 157 | frontend-best-practices.md |
| 6,441 | 114 | agent-memory.md |
| 6,283 | 105 | goal-setting-and-monitoring.md |
| 6,034 | 92 | agent-resilience.md |
| 2,985 | 31 | rarv-cycle.md |
| 2,518 | 40 | risk-classification.md |
| 2,242 | 30 | autonomy-levels.md |

## The shape of the fix (candidate directions)

The docs' own guidance is the budget: content that loads at launch should be *CLAUDE.md-sized*
(target ≲ 200 lines). The kit currently ships ~25× that. Any fix must preserve two things:
(1) the pipeline still *works* — agents can still be pointed at the full rule text when their
stage runs; (2) `claude-kit upgrade` remains safe across the layout change.

**Direction A — split each file: always-on covenant + on-demand detail (recommended).**
`.claude/rules/` keeps a *small* always-on set: the non-negotiables that must shape every turn
(rarv-cycle, risk-classification, autonomy-levels — already lean — plus *slimmed* cores of
mandatory-workflow, quality-gates, continuity: the routing table, the severity contract, the
resume contract). Target ≤ ~10k tokens at launch. Everything else — the how-to depth of
testing, linting, design-patterns, devops, documentation, etc. — moves to the stage skills
(`.claude/skills/…`, loaded on invocation) or `references/` files cited by the relevant agents.
Pros: conforms to native semantics; keeps `.claude/rules/` meaningful; agents already cite
rules per-stage so re-pointing is mechanical. Cons: largest diff (touches most rule files +
every cross-reference); the "36 rules" README claim changes meaning.

**Direction B — relocate wholesale; rules dir becomes pointers.** Move full rule texts to a
non-auto-loaded home (e.g. `.claude/skills/_references/rules/`), leave `.claude/rules/` holding
only a handful of tiny covenant files. Pros: rule texts stay byte-identical (pure moves), the
upgrade diff is clean. Cons: `.claude/rules/<name>.md` citations in ~100s of places must be
re-pointed anyway; two homes for "rules" is a permanent naming wart.

**Direction C — `paths:`-scope the core rules.** Works only for the few with a real file
signal even in a stack-agnostic core (frontend-best-practices, responsive-and-accessibility —
via broad web-file globs). Process rules — the bulk of the weight — apply to every file, so
this direction caps out at ~15-20% of the problem. Useful as a *component* of A, not a fix.

**Direction D — mitigation toggle only.** Document the cost and how to prune. Rejected as the
primary fix: the kit's headline is a working default, not a footgun with a warning label.

## What any fix touches

- The rule files themselves + every `.claude/rules/<name>.md` citation in `agents/`, `skills/`,
  `templates/CLAUDE.md`, `rules/` cross-refs, `docs/`, and `README.md`.
- `catalog.resolve()` stays branch-free (golden rule): the split is a payload/layout change,
  not a resolver change.
- `exporter` — `.mdc` projection should keep exporting the FULL rule text (Cursor's on-demand
  model has no launch cost); the synthesizer's rule index needs the new locations.
- `upgrader` — moved files = remove + add under checksum tracking; needs an explicit
  cross-version test (old layout → new layout upgrade preserves user edits as sidecars).
- `check_docs_consistency.py` anchors ("36 rules", "25 files") and the README feature claims.
- `validator` structural checks for the new layout.

## Measurement methodology (reproducible)

```
# control                                  # scaffolded                 # attribution
D=$(mktemp -d); cd $D                      claude-kit init $P --defaults; cd $P     mv .claude/rules /tmp/parked
claude -p "Reply with exactly: OK" \
  --output-format json [--model <id>]      # same command              # same command
# total input = usage.input_tokens + cache_creation_input_tokens + cache_read_input_tokens
```

Re-run the three scenarios after any fix lands; the scaffolded-minus-control delta is the
number the README should eventually cite honestly.
