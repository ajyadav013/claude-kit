---
source: https://algomaster.io/learn/lld/dry
author: ashishps1 for in-repo problems
license-note: ideas absorbed in own words; no text or code reproduced
---

# DRY: one authoritative home per piece of knowledge — with deliberate exceptions

## What it teaches

DRY is framed the way The Pragmatic Programmer originally framed it: as a
rule about *knowledge*, not lines of code. Every fact the system depends on —
a business rule ("must be 18+"), a config value, a data-model shape, a doc
definition, shared test setup — should have exactly one authoritative
representation, referenced from everywhere else. The running example is an
email-validation rule copy-pasted into auth, payments, and messaging
modules: when the rule changes (only .com/.org now allowed), every copy must
be found and fixed, and missing one produces modules that disagree about
what a valid email is.

The chapter is equally emphatic about the failure mode of *over*-applying
DRY. It gives three sanctioned reasons to tolerate repetition: the Rule of
Three (don't extract until a pattern appears a third time — two occurrences
may be coincidence that will diverge), test readability (a test should tell
its whole story inline rather than send the reader hunting through helper
factories), and triviality (wrapping something like a one-token expression
in a shared utility costs more in indirection than the duplication ever
would). It leans on Sandi Metz's line that duplication is cheaper than the
wrong abstraction.

## Key patterns & decisions

- **Knowledge-level DRY, not text-level**: the unit of deduplication is a
  fact or rule (business rules, config, schemas, docs, test fixtures), so
  two textually different snippets encoding the same rule still violate DRY.
- **Rule of Three before extraction**: wait for a third occurrence before
  factoring out shared logic; two look-alikes may evolve apart, three is
  evidence of genuine shared knowledge.
- **Divergent-copy bug class**: hand-copied logic mutates in transit (one
  copy drops a null guard), producing a module-specific crash that stays
  invisible until the right input hits the one bad copy in production.
- **Duplication multiplies test burden**: N copies of a rule need N test
  suites, and in practice rule changes get tested in fewer than N of them,
  so coverage silently decays.
- **Single-source-of-truth extraction**: centralize the rule in one
  dedicated component and have all modules delegate to it, so a future rule
  change lands in exactly one place and consistency is automatic.
- **Split by responsibility when de-duplicating**: the notification example
  extracts *two* focused collaborators (formatting vs sending) rather than
  one blob, so each future change (template tweak vs API/retry change) has
  one obvious home, each is unit-testable and mockable, and a new service
  reuses both with zero edits to existing code.
- **Tests may stay intentionally WET**: inline setup duplication in tests is
  a fair trade for a failing test being readable top-to-bottom in isolation.
- **Anti-pattern — premature abstraction**: extracting on the first
  resemblance creates misleading shared code that is harder to unwind than
  the duplication it replaced.

## When to apply / trade-offs

Apply hardest where the duplicated thing is a *rule that changes*: pricing
logic, validation, permissions, message formats. The trade-off axis the
chapter draws is maintenance risk (unsynchronized copies) vs indirection
cost (readers chasing definitions through utility layers). Its heuristic
question: if this logic changes, will I reliably remember every place it
lives? Uncertainty means centralize. But for two-time coincidences, test
fixtures, and trivial expressions, repetition is the better engineering
choice.

## Fidelity check

1. *Claim: DRY governs knowledge, not just code.* The capture quotes the
   Pragmatic Programmer's single-authoritative-representation definition and
   explicitly extends it beyond code to business rules, configuration, data
   models, documentation, and shared test setup.
2. *Claim: the chapter endorses waiting for three occurrences.* Its Rule of
   Three section argues two similar fragments may be coincidental and might
   diverge as features evolve, while a third occurrence is the evidence that
   justifies extraction.
3. *Claim: copies drift and cause module-local bugs.* The capture's
   risk section describes a pasted validation losing its null check in one
   module, so that module alone crashes on null input — a bug hidden until
   that input reaches that module in production.
