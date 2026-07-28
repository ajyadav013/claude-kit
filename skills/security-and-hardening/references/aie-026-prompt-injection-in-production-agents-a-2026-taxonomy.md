---
source: https://www.digitalapplied.com/blog/prompt-injection-production-agents-2026-taxonomy
author: Digital Applied Team
license-note: ideas absorbed in own words; no text or code reproduced
---

# Prompt injection's control surface is every channel writing into context

## What it teaches

Most agent security reviews start and end at the chat textarea, which the piece
argues is the decoy: of ten observed delivery vectors, only one is direct user
input, and the other nine arrive through channels the agent already trusts —
fetched pages, tool and MCP results, long-term memory, RAG corpora, peer
subagents, uploaded attachments, inbound email, third-party API payloads, and
shared multi-tenant session state. The organising move is to classify attacks
by *delivery vector* rather than by attacker goal, on the reasoning that
delivery is the surface a platform team actually owns, while target capability
varies per agent and detection signal varies per telemetry stack. Each class
gets a named observable that indicates exploitation, so the taxonomy doubles as
a monitoring checklist. The framing throughout is that injection is a property
of instruction-following architectures rather than a defect awaiting a patch:
assume the payload lands, and constrain what it can reach. Mitigation is
therefore four layers deep — ingestion sanitisation, tool restriction, output
validation, human review — sized to each action's blast radius, plus a
recurring red-team pass timed to capability changes.

## Key patterns & decisions

- **Classify by delivery vector, not by attacker intent** — the taxonomy's ten
  rows are channels (content fetch, tool output, memory, RAG, subagent, file
  attachment, email body, API response, shared session, direct input) because
  channels are what a team can enumerate, own, and instrument. Intent-based
  taxonomies do not map onto controls.

- **Every class needs a named detection signal** — the article pairs each
  vector with an observable: imperative density in retrieved chunks, tool-call
  chains that diverge from the planned execution graph, cross-session
  behavioural drift, API string fields exceeding historical p99 size, responses
  citing another tenant's identifiers. Prevention is treated as unachievable;
  detection and capability gating are the load-bearing controls.

- **Gate tool availability on context taint** — the sharpest control listed is
  dynamic: disable privileged tools *while untrusted content is in the context
  window*, and key tool allowlists on the current task context rather than on a
  static per-agent grant. The worked travel-agent example fails precisely
  because a send-email capability stayed live while third-party review text was
  being summarised.

- **The tell is a read-to-privileged transition** — a specific, cheap alert:
  flag any tool-call chain that moves from read-only operations into
  exfiltration-capable ones (send-email, http-post, file-write) immediately
  after ingesting free-form untrusted text. This is a trace-level rule, not a
  content classifier, so it survives payload obfuscation.

- **Memory converts a one-shot exploit into a persistent backdoor** — anything
  written into long-term memory is read back as trusted context in every later
  session. The hygiene rules are provenance tags per entry, explicit
  confirmation before writing user-derived facts, periodic audits scanning
  stored entries for imperative content, idle expiry, and purge as a
  first-class operation rather than an admin escape hatch.

- **Treat subagent output as untrusted content, not trusted context** — in
  multi-agent chains a compromised peer becomes an injection channel for its
  parent, which the article places under OWASP Agentic Top 10 T6 (tool-chain
  compromise). Controls: schema-validated inter-agent messages that reject
  free-form instruction strings, minimum tool scope per subagent, and logged
  handoffs with full message provenance.

- **Cross-tenant leakage is an isolation failure that presents as injection** —
  shared context caches, one shared embedding index, or batched summarisation
  pipelines let a payload planted in one tenancy surface in another. Called the
  highest-severity class because it breaks the isolation contract the product
  is sold on; fixes are per-tenant memory partitions and embedding indexes,
  session-ID scoping on every retrieval and memory write, plus output-side PII
  and secret scanning as the last line.

- **Four layers, each covering what the others cannot** — (1) ingestion:
  provenance tags on every context chunk, untrusted-content delimiters,
  instruction-density classifiers, jailbreak-family matchers; (2) tool
  restriction: per-session and per-tenant scoped credentials, capability gating
  on sensitive tools; (3) output validation: PII/secret detection, destination
  allowlists for emitted URLs, schema-constrained responses, tool-argument
  validation; (4) human review on irreversible actions with resolved arguments
  shown, and — notably — rate limits on approvals so reviewers cannot
  fatigue-click, with an audit trail linking each approval to its originating
  context.

- **Red-team on a cadence keyed to capability change, not the calendar alone** —
  a four-week baseline pass: map every channel that writes into the context
  window and tier each tool by blast radius; build at least five payloads per
  class including encoding variants; inject per channel in isolation under
  production-equivalent conditions and record whether detection fired and how
  fast; then rank findings by severity times likelihood *and detection gap*.
  Success is defined as every class having a mitigation and a bounded detection
  window, not as a zero-finding report.

## When to apply / trade-offs

This applies to any agent that reads content it did not author — which in
practice means any agent with retrieval, tool use, file upload, an inbox, peer
subagents, or persistent memory. The taxonomy is most useful as a gap-analysis
grid: one row per channel, one column for the control and one for the detection
signal, run before shipping and again after any tool-chain change. The costs
are real: taint-aware tool gating means the agent will refuse work it could
technically do while untrusted content sits in context, per-tenant embedding
indexes cost more than one shared store, and four weeks of red-teaming per
significant release is a standing budget line. Skip the heavy end for agents
with a genuinely small blast radius — read-only assistants with no outbound
capability and no persistent memory get most of the benefit from ingestion
tagging and output scanning alone. Treat the quantitative claims with care:
this is an agency's marketing content, the audit sample and incident ratios are
self-reported and not independently verifiable, and the OWASP mappings are the
only externally checkable part. Adopt the structure and the controls; do not
cite the statistics as evidence.

## Fidelity check

1. Claim: only one of ten delivery vectors is the direct input box, and the
   taxonomy groups by delivery vector because that is the surface teams own.
   Support: the capture states that nine of ten attack classes arrive through
   trusted channels, and explicitly says the grouping is by delivery vector
   because delivery is the control surface, while target capability varies by
   agent and detection signal varies by telemetry stack.

2. Claim: each class carries a named detection signal, including tool-call
   chains diverging from the planned execution graph and cross-session
   behavioural drift. Support: the capture presents a ten-row table with a
   Detection Signal column, and the per-class sections repeat signals such as
   anomalous post-tool call chains, cross-session behavioural drift, retrieved
   chunks containing imperatives, and API response sizes exceeding historical
   p99.

3. Claim: privileged tools should be disabled while untrusted content is in
   context, illustrated by an agent that emailed an itinerary after reading a
   poisoned hotel review. Support: the capture describes that anonymised
   travel-booking incident and states the control was that an unscoped
   send-email tool should not have been available while third-party content was
   being processed; Layer 2 of the mitigation matrix separately lists disabling
   privileged tools while untrusted content is in context.
