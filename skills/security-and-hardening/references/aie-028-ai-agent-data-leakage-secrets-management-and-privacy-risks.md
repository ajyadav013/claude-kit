---
source: https://rafter.so/blog/ai-agent-data-leakage-secrets-management
author: Rafter Team (rafter.so)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Treat the agent as untrusted: a broker injects secrets at tool-execution time

## What it adds beyond the primary

Mostly reinforces ground the kit already holds (redact in the logging
pipeline, mask DSN credentials, short-lived per-request scoped
credentials, PII vault before the provider sees text), but it contributes
three specifics the kit does not currently state. First, a *secrets broker*
as an explicit architectural boundary: the agent's context lists only
capability names such as "billing API, credentials managed elsewhere",
while a separate process holds the vault, validates the requested
operation, and attaches the credential at call time — so extraction via
prompt injection returns nothing usable. Second, it names the agent's own
chain-of-thought / reasoning trace as a distinct leak sink separate from
application logs: an agent narrating "connecting with this connection
string" writes a plaintext password into monitoring systems that usually
have looser access control than the database did. Third, it treats the
telemetry fan-out as its own exfiltration surface — prompts and tool calls
land in APM and product-analytics platforms (Datadog, Mixpanel, Amplitude
are named) where secrets have been discovered months later, after dozens
of engineers already had read access. It pairs this with retention tiers
per log category (an illustrative 7 days for conversations, 30 for tool
calls, 90 for errors), encryption of logs at rest, and an audit trail over
*who read the logs*, which the kit's observability guidance does not
require. Framing claims: it cites research putting a 78% eventual-exposure
rate on secrets held in LLM context, and anchors the cost side on GDPR
penalties reaching 4% of global revenue.

## Primary source for this cluster

[aie-024-model-context-protocol-security-best-practices.md](aie-024-model-context-protocol-security-best-practices.md)

## Fidelity check

1. Claim: a broker holds vault-loaded secrets, receives an operation
   request from the agent, and supplies credentials at execution time.
   Support: the capture shows a `SecretsBroker` example that loads from a
   vault in an isolated process and passes auth into the API client, while
   the agent's own context is rewritten to say only that credentials are
   managed securely.
