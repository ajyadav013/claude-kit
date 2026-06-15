---
name: simplification-debt
description: Harvests deliberately-deferred shortcuts from the codebase into one debt ledger, so "later" does not quietly become "never". Greps for TODO/FIXME/HACK markers and inline upgrade-path notes, groups them by file, and flags any shortcut that names no upgrade trigger as a silent-rot risk. Use when the user says "what did we defer", "list the shortcuts", "tech-debt ledger", "what's marked to do later", or "simplification debt". Reports only — changes nothing unless asked to persist the ledger.
---

# Simplification Debt

> Inspired by the [ponytail](https://github.com/DietrichGebert/ponytail) plugin's debt-harvest idea.
> A deliberate shortcut is fine — an *untracked* one rots. This skill collects them into one place so a
> deferral stays visible until someone revisits it.

## The convention it harvests

A deliberate shortcut should record two things at the point it's taken: its **ceiling** (the limit it
hits) and its **upgrade path** (the trigger to revisit). claude-kit recognizes two equivalent forms
(see `.claude/rules/documentation.md`):

- **Ticketed:** `TODO(PROJ-123): naive O(n²) scan; switch to an index if the list grows.`
- **Inline upgrade path:** `# shortcut: global lock — per-account locks if throughput matters.`

Both are legitimate. A shortcut with **no** trigger ("TODO: fix later") is the one that rots.

## Scan

Grep the repo for shortcut markers, skipping vendored and build output (`node_modules`, `.git`,
`dist`, `build`, `vendor`, `target`, etc.). The pattern is language-neutral — markers live in comments,
so match common comment prefixes (`#`, `//`, `--`, `;`, `<!--`):

```
grep -rniE '(#|//|--|;|<!--)[[:space:]]*(TODO|FIXME|HACK|XXX|shortcut|ponytail):' . \
  --exclude-dir={.git,node_modules,dist,build,vendor,target,.venv}
```

Add your stack's comment prefix if it differs. Each hit is one ledger row. Matching on the comment
prefix keeps prose that merely *mentions* the convention out of the ledger.

## Output

One row per marker, grouped by file:

```
<file>:<line> — <what was simplified>. ceiling: <the limit named>. upgrade: <the trigger to revisit>.
```

Pull the ceiling and trigger straight from the comment when the `<ceiling>, <upgrade>` form is used.
Want an owner per row? add `git blame -L<line>,<line> <file>`.

**Flag the rot risk:** any marker that names no upgrade path or trigger gets a `no-trigger` tag — those
are the deferrals that silently become permanent.

End with a one-line tally:

```
<N> markers, <M> with no trigger.
```

Nothing found: `No deferred shortcuts. Clean ledger.`

## Persisting (only if asked)

By default this reports to the conversation and changes nothing. If the user wants it tracked, write the
ledger to a file they choose (e.g. `SIMPLIFICATION-DEBT.md` at the repo root, or an entry under the
artifacts dir). Don't create the file unprompted.

## Boundaries

- **Reads and reports only.** It never edits code or removes markers.
- **Not a linter.** It surfaces *intentional* shortcuts to keep them honest; it does not judge code it
  wasn't told about.
- Pairs with `over-engineering-review` (find complexity to cut now) and `code-simplification` (perform
  the cut). This skill is about the shortcuts you *chose* to leave behind.
