---
source: https://algomaster.io/learn/system-design/what-is-an-api
author: AlgoMaster (Ashish Pratap Singh)
license-note: ideas absorbed in own words; no text or code reproduced
---

# APIs as contracts and boundaries, not just endpoints

## What it teaches

The chapter reframes an API from "some HTTP endpoints" to a written agreement
plus an enforced boundary. The agreement (contract) must answer a checklist of
questions: available operations, required inputs, response shapes, failure
modes and retry safety, caller identity, per-caller access scope, operational
limits (rate, size, timeout, pagination), and an evolution story (versioning,
optional fields, support windows). The contract can live in OpenAPI, protobuf,
a GraphQL schema, AsyncAPI, or — for in-process library APIs — in signatures,
types, and tests; the medium differs but the agreement is the same.

The boundary framing is the second half: callers interact with the front desk,
never the database or internal services. That indirection is what lets the
provider swap storage, queues, caches, or internal topology without breaking
clients, and it concentrates security checks, logging, tracing, and ownership
at one edge. The flip side is responsibility: a public API that breaks breaks
customers, and an unowned internal API turns every change into a negotiation.

It then classifies APIs by audience — public (needs docs, stability, quotas,
deprecation discipline), partner (per-tenant access, audit logs, contract
review), internal (still needs owners, timeouts, and stable shapes because it
sits on critical paths like checkout and login), and library (in-process). A
survey of network API styles (REST, GraphQL, gRPC, WebSocket, SSE, webhooks,
message-driven, SOAP) is paired with the pragmatic advice that a small
product's first API is usually REST, with other styles added for specific
needs like token streaming or two-way sessions.

The operational sections cover the three access questions (who is calling, what
may they do, how much may they send), reliability primitives (timeouts on every
call, retries only when safe, idempotency keys for money-moving POSTs), and an
observability minimum: request/trace ID, caller, route, status, latency, sizes,
rate-limit outcome, and downstream time — while keeping secrets and sensitive
payloads out of logs.

## Key patterns & decisions

- API contract as an explicit checklist: operations, inputs, outputs, errors, identity, access scope, limits, and change policy all written down before clients build on it.
- API-as-boundary: internals stay swappable as long as externally observed behavior holds; the edge becomes the single place for auth, limits, and audit.
- Authentication vs authorization split: proving identity is separate from checking that this caller may touch this specific resource/tenant.
- Secrets belong in headers, never query strings — URLs leak into browser history, proxy logs, analytics, and referrer headers.
- Idempotency keys as duplicate-protection for unsafe operations: retrying a read is free, retrying a payment creation without a key can double-charge.
- Status codes carry the outcome — never a 200 wrapping a body-level failure flag, because gateways, SDKs, and monitors all key off the code.
- Cost-aware rate limiting for AI APIs: request count alone is meaningless when one call is a tiny prompt and another processes a huge document; meter tokens, size, model tier, and concurrency.
- Observability floor per request: trace ID, caller, route, status, duration, sizes, rate-limit result, downstream latency — with an explicit no-secrets-in-logs rule.
- Internal-does-not-mean-informal: internal APIs need owners, docs, timeouts, and stable shapes because they sit under checkout, login, and inference paths.

## When to apply / trade-offs

Use the contract checklist when designing any new endpoint or reviewing an
integration — it doubles as a review rubric. The boundary discipline matters
most when multiple clients or teams depend on a service; for a single-consumer
prototype the ceremony can be lighter, but retrofit auth/limits/idempotency
before real traffic or money flows. The style survey is a selection heuristic,
not dogma: start REST, add streaming or typed RPC styles only when a concrete
need appears. Cost-based metering adds complexity and only pays off when call
costs genuinely vary by orders of magnitude (LLM and batch APIs).

## Fidelity check

1. Claim: the chapter warns against tokens in query parameters. Support: the capture explicitly says URLs end up in browser history, proxy logs, analytics tools, referrer headers, and monitoring systems, so credentials belong in an Authorization-style header.
2. Claim: retry safety is tied to idempotency, with payments as the canonical hazard. Support: the capture contrasts re-fetching an order (safe read) with re-posting a payment without an idempotency key, which can charge a customer twice.
3. Claim: request-count rate limiting is called insufficient for AI APIs. Support: the capture notes a small prompt and a large document-processing call cost very different amounts, so token counts, file size, model type, parallelism, and queue time should factor into limits.
