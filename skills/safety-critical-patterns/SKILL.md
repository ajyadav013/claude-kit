---
name: safety-critical-patterns
description: High-reliability coding lens adapted from NASA's Power of 10 — bounded loops & recursion, assertion density at boundaries/invariants, minimal variable scope, check every return value, restrained metaprogramming, strictest warnings — applied with rigor MATCHED TO CONSEQUENCE (full for money movement, medical, data-integrity, auth, irreversible actions; selective for core business logic; light for scripts/prototypes). Use when writing or reviewing code whose failure is expensive. Do NOT use as a general style/quality pass (use code-review-and-quality) or to scan for complexity to delete (use over-engineering-review) — this is the reliability lens, gated by consequence so it never over-applies to ordinary CRUD.
---

# Safety-Critical Coding Patterns

> A high-reliability review/authoring lens adapted (stack-agnostic) from NASA JPL's **Power of 10**
> rules, via the MIT-licensed [`athola/claude-night-market`](https://github.com/athola/claude-night-market)
> `safety-critical-patterns` skill. The rules are language-neutral *intent*, not C-specific mandates.

## Match rigor to consequence (the gate)

This is the most important rule — apply the rest **proportional to what a failure costs**, never
uniformly. Use `.claude/rules/risk-classification.md` to place the change:

| Rigor | Apply to |
|-------|----------|
| **Full** | Money movement, medical/clinical, data-integrity, authn/authz, anything irreversible |
| **Selective** | Core business logic, public API handlers, core algorithms |
| **Light** | Scripts, prototypes, non-critical utilities, throwaway tooling |

Forcing all ten rules onto a CRUD endpoint is itself an over-engineering smell
(`over-engineering-review`). The point is reliability where reliability is worth paying for.

## The 10 rules (adapted, language-neutral)

1. **Restrict control flow.** Avoid arbitrary jumps; **bound recursion**. Recursion is fine with a
   provable termination (tail call, bounded depth, tree of known size).
2. **Fixed loop bounds.** Every loop has a verifiable upper bound. Give a potentially-unbounded loop a
   safety limit and a reason it terminates.
   ```python
   for i in range(min(len(items), MAX_ITEMS)):   # bound is explicit
       process(items[i])
   # vs.  while not done:  ...                    # when does this end?
   ```
3. **Bound resource acquisition.** Don't allocate without limit on a hot/critical path; pre-size and
   reuse where allocation failure mid-operation would be unrecoverable (GC languages relax this).
4. **Keep functions short (~60 lines / one screen).** Cognitive limits are real; long functions hide
   bugs. Flexible for declarative/config, strict for complex logic.
5. **Assert boundaries and invariants.** Add defensive assertions for preconditions, postconditions,
   and the things that "can't happen." Focus on real invariants, not a quota.
   ```python
   def transfer(src, dst, amount):
       assert src != dst, "cannot transfer to same account"
       assert amount > 0, "amount must be positive"
       assert src.balance >= amount, "insufficient funds"
   ```
6. **Minimal variable scope.** Declare at the narrowest scope; don't hoist state into a wider scope
   than its use.
7. **Check every return value and validate every input.** Never ignore a result that can signal
   failure; never trust an unvalidated parameter. (This is the reliability-side of
   `agent-guardrails.md`'s "validate inputs.")
   ```python
   cfg = parse_config(path)
   if cfg is None:
       raise ConfigError(f"failed to parse {path}")   # not: parse_config(path)  # result dropped
   ```
8. **Restrain metaprogramming.** Limit macros/decorators/codegen/reflection; they defeat static
   analysis and obscure control flow. Prefer explicit over magic; document any metaprogramming.
9. **Discipline indirection & ownership.** Limit levels of indirection; be explicit about who owns and
   mutates state. Prefer immutable data and clear types over deep optional/pointer chains.
10. **Compile/lint at the strictest setting from day one.** Turn on all warnings and treat them as
    errors. (e.g. `ruff --select=ALL` + `mypy --strict`; `tsc --strict`; `-Wall -Werror`; `clippy`.)

## Rules that may not apply

| Rule | Relax when |
|------|-----------|
| Bounded recursion | Tree traversal / parser combinators with provably bounded depth |
| Bounded allocation | GC languages, short-lived processes |
| ~60-line functions | Declarative config, exhaustive state machines |
| Restrained indirection | Callbacks, event handlers, strategy patterns are legitimate |

## Reporting violations

Each finding is **grounded** (per `code-review-and-quality`): cite `Rule N`, a `file:line` Location,
and a verbatim Anchor from that line, plus the issue and a concrete fix. Re-verify the citation before
reporting.

## Related

- `.claude/rules/risk-classification.md` — sets the consequence tier that gates how much of this to apply
- `code-review-and-quality` — the general multi-axis review; this is the reliability lens layered on top for high-consequence code
- `over-engineering-review` — the opposite guard: don't apply full rigor where consequence doesn't warrant it
- `.claude/rules/testing.md` — assertions complement, never replace, the runnable test for non-trivial logic
