---
source: https://collinwilkins.com/articles/structured-output
author: Collin Wilkins
license-note: ideas absorbed in own words; no text or code reproduced
---

# Schema-constrained decoding kills syntax errors, not semantic ones

## What it teaches
Provider-native structured output (constrained decoding at inference time) has
become table stakes across the major APIs, and it makes malformed JSON
impossible by construction. That solves exactly one failure class. The article
argues the remaining engineering work is where the value sits: design the
schema before the prompt as if it were an API contract; give every field a
downstream justification (a branch, a join, or a stored artifact); use enums
for anything that drives routing; and treat everything the model returns —
including tool results — as untrusted until it clears both schema validation
and *semantic* validation in your own code. It then walks the divergence
between providers (parameter names, which JSON Schema keywords each one
actually honours, hard limits, refusal shapes), the self-hosted constrained
decoding engines and how to choose between them, and a catalogue of production
failure modes that schema enforcement does not catch — silent keyword drops,
over-constrained schemas that blow compile budgets, confidence scores frozen at
a constant, and answer fields emitted before reasoning fields.

## Key patterns & decisions
- **Schema before prompt, contract before content** — the schema is the spec
  and the prompt merely fills it. Every field must justify itself in one
  sentence; if it does not drive a decision, support a join, or get stored,
  drop it. Flat schemas with a few tightly-constrained fields beat rich schemas
  with many loose ones.
- **Enums for anything that branches** — freeform strings on a routing field
  invite invented values. Enums plus regex-bounded IDs, numeric bounds on
  scores, string length limits, and array size caps push the constraint into
  the contract rather than into downstream cleanup code.
- **Reasoning fields must precede answer fields** — schema field order is
  logic, not formatting. Required properties emit in order, so a chain-of-
  thought model that hits the answer field first commits before it has
  reasoned. The output is wrong, the JSON is valid, and validation catches
  nothing.
- **Constrained decoding is faster, not slower** — grammar enforcement prunes
  the model's search space, so fewer tokens go to dead ends. The cited claim is
  that it can beat unconstrained generation by up to an order of magnitude.
- **Provider portability is not free** — the article tabulates distinct
  parameter shapes per vendor, notes that one provider silently ignores
  unsupported schema keywords (no error, wrong-shaped JSON), that another
  rejects a larger slice of the JSON Schema spec (no recursion, no min/max, no
  string lengths) with published caps of 20 strict tools, 24 optional params
  and 16 union-typed params, and that grammar compilation is cached ~24 hours
  but invalidated by any schema edit.
- **Refusals bypass the schema** — a safety-blocked input returns a refusal
  object, not schema-compliant data. A naive validate-and-retry loop will spin
  forever on it. Detect refusal as a distinct terminal outcome.
- **Validate, repair, retry — with a cap and a metric** — feed the actual
  validator error text back and regenerate, bounded by a retry ceiling, then
  fail safely. Track retry rate per prompt: a prompt that routinely needs two
  or more repairs is a broken prompt or a broken schema, not a case for more
  retries.
- **Semantic validators check distributions, not types** — the author's own
  sentiment classifier passed schema validation for two weeks while emitting a
  constant confidence of 0.99 on every input including gibberish. Monitor
  per-field distributions; a distribution that stops moving is the alarm.
  Demanding verbatim evidence quotes makes hallucination measurably harder.
- **Store the validated output as a replayable event** — persist the record
  alongside input hash, prompt version, schema version, model id, retry count,
  latency and token counts. That turns "which fields fail most" and "which
  labels are drifting" into SQL queries instead of eyeballing raw output.

## When to apply / trade-offs
Apply this wherever model output crosses a system boundary and becomes another
system's input — extraction into analytics columns, routing and triage,
normalisation, RAG citation metadata, and agent tool results (the November 2025
MCP spec makes output-schema conformance mandatory for tool servers). The costs
are real: schemas are breaking changes and must be versioned in lockstep with
prompts; over-constraining (very large enums, tight array bounds, dense
cross-field constraints) can push constrained-decoding engines into compilation
timeouts, so only constrain what downstream code actually relies on; and the
validate-repair loop spends tokens. It is overkill when the output is genuinely
prose for a human to read, when a one-off exploratory call will never be stored
or joined, or when the schema would be so large that the grammar cost exceeds
the parsing pain it removes. The recommended entry point is deliberately
small — one painful workflow, a compact schema, one repair retry, JSONL event
storage, and two dashboards (validation error rate and label distribution).

## Fidelity check
1. Claim: reasoning fields must be ordered before answer fields or the model
   commits early. Support: the capture has a dedicated failure-mode section
   stating that required properties are emitted first, that putting the answer
   before reasoning makes chain-of-thought models commit prematurely, that the
   JSON stays valid so validation misses it, and that field order is logic
   rather than formatting.
2. Claim: constrained decoding is faster than unconstrained generation, not
   slower. Support: the capture explicitly says grammar enforcement trims the
   model's search space so fewer tokens are spent on dead ends, and describes
   the speedup as sometimes an order of magnitude.
3. Claim: schema-valid output can still be semantically meaningless, so
   validators must inspect distributions. Support: the capture recounts a
   sentiment classifier that produced valid JSON with correct types and enums
   for two weeks while confidence sat at 0.99 for every record including
   gibberish, and prescribes distribution tracking plus verbatim evidence spans
   as the fix.
