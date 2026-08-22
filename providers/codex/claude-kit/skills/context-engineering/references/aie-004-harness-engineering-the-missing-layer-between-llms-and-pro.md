---
source: https://ranjankumar.in/harness-engineering-the-missing-layer-between-llms-and-production-systems
author: Ranjan Kumar
license-note: ideas absorbed in own words; no text or code reproduced
---

# A production harness is seven runtime layers, built validation-first

## What it adds beyond the primary

Three things the primary survey framing does not give you operationally.
First, a **build-order prescription** rather than a taxonomy: start with schema
validation, then wire the repair loop, then input normalization, then the
execution gate, then degradation, then checkpointing, and optimize context
assembly *last* — explicitly because tuning the retrieval pipeline before
fixing validation is premature. Second, a crisp **framework-is-not-a-harness**
distinction: LangChain, LangGraph, CrewAI and AutoGen are build-time component
kits, whereas the harness is the runtime environment that governs what context
the model sees, which tools it may call, what output is accepted, and what is
allowed to execute — you can hold one without the other, which is why
framework-built agents demo well and die in production. Third, a set of
**harness-level operational metrics** that replace model-quality scores:
validation failure rate, repair-loop success rate, and circuit-breaker trip
count. It also supplies two numeric arguments for why the layer exists at all
(below), and names "lost in the middle" as a context-*design* failure rather
than a model failure.

## Primary source for this cluster

[aie-002-what-is-an-ai-agent-harness.md](aie-002-what-is-an-ai-agent-harness.md)

## Fidelity check

1. Claim: the recommended build order is validation → repair loop →
   normalization → gated execution → graceful degradation → state management →
   context orchestration. Support: the capture's build-order section lists them
   First through Seventh in that exact sequence, and says not to over-engineer
   the context pipeline before validation is fixed.
