---
source: https://blaxel.ai/blog/multi-tenant-isolation-ai-agents
author: Nicolas Lecomte (Blaxel)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Agent tenant leaks are unbounded: leaked rows become reasoning, then actions

## What it adds beyond the primary

The MCP-security primary treats the server/tool surface; this piece reframes
tenancy itself as an agent problem and names the leakage paths a "filter by
tenant_id" habit misses. Its central argument: in ordinary SaaS a boundary
miss returns wrong data to one requester and stops there, whereas in an agent
platform the wrong data becomes reasoning input and the blast radius grows to
whatever the agent's tools can reach. It then walks four layers that each need
their own control — retrieval, compute, identity, telemetry — and argues that
getting one right while ignoring another leaves the platform exploitable.

Concrete additions worth carrying: (1) retrieval leakage can be *structural*
rather than adversarial — the article cites an arXiv preprint where, on a
four-tenant corpus, up to 95% of benign queries produced cross-tenant leakage,
because shared vendors and personnel create organic entity links; vector-only
retrieval with metadata prefilters held up, but when vector hits seeded
knowledge-graph traversal the authorization applied at the vector layer was
simply absent during graph expansion. OWASP's 2025 LLM Top 10 gets a dedicated
LLM08 entry for vector/embedding weaknesses. (2) Caches are a side channel:
prefix-cache hits are observable through time-to-first-token differences, and
a semantic cache in a multi-tenant deployment can hand one tenant another's
stored intermediate result. (3) Compute isolation must match the threat model
of *LLM-generated* code — containers share the host kernel (CVE-2024-21626 is
the cited escape), gVisor's Sentry intercepts syscalls in user space at a
compatibility and overhead cost, and microVMs give each workload its own
kernel over KVM (Firecracker boots in under 125 ms with under 5 MiB overhead
per VM). (4) Observability is both control and leak: agent logs carry
reasoning steps, retrieved chunks, tool parameters, and generated code, so the
fix is segregated OpenTelemetry pipelines by risk tier with redaction
processors in the Collector transform stage before anything reaches a shared
backend. (5) Per-tenant KEK envelope encryption enables crypto-shredding —
destroy the key and the data is unreachable without deleting it.

The identity section is the closest thing to a rule the kit could adopt
verbatim in spirit: backend services, never the model, resolve tenant context,
so the context window can't become an exfiltration path; every tool call,
retrieval, and model request carries an authorization envelope of action type,
resource id, and tenant; and OWASP LLM06 is quoted as forbidding delegation of
privilege separation and authorization bounds checks to the LLM. Governance
adds OPA/Rego policies wired as CI/CD gates so an infra change that breaks
tenant isolation fails before deploy, plus audit records keyed by trace id,
tenant-scoped id, agent instance id, and action type, with prompt context
stored as a hash rather than raw text to avoid manufacturing new leak surface.
Note the vendor framing: the compute section is a pitch for the author's
microVM sandbox product, so treat the 25 ms resume and zero-standby-cost
figures as marketing rather than independent measurement.

## Primary source for this cluster

[aie-024-model-context-protocol-security-best-practices.md](../../security-and-hardening/references/aie-024-model-context-protocol-security-best-practices.md)

## Fidelity check

1. Claim: an agent boundary failure is unbounded because leaked data enters
   the reasoning chain and is acted on via tools. Support: the capture opens
   by contrasting ordinary SaaS, where a miss is contained and usually
   noticeable, with agent platforms whose reach is limited only by what the
   agent's tools can touch, and returns to the same point in its FAQ.
