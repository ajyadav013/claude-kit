---
source: https://socprime.com/blog/mcp-security-risks-and-mitigations/
author: Daryna Olyniychuk (SOC Prime)
license-note: ideas absorbed in own words; no text or code reproduced
---

# MCP's ten named risks collapse into four controls

## What it adds beyond the primary

Mostly corroborates the official MCP security guidance, but organises it the
way a SOC would: ten named risk patterns each paired with a one-line
mitigation, rather than a specification's normative prose. Three framings are
worth keeping. First, it treats the MCP server as part of the *control plane* —
once an assistant can both retrieve internal context and trigger actions, the
security posture is set by which servers are trusted and which scopes are
granted, not by the model. Second, it separates the data layer (JSON-RPC,
lifecycle, and the primitives: tools, resources, prompts, notifications) from
the transport layer (connection setup, message framing, authorization), and
argues the transport layer is where enforcement actually lives. Third, it
argues that standardisation is a security *opportunity*: one consistent surface
to police beats a bespoke integration per model per downstream system. The
concrete mitigations it names — forbid token passthrough and validate token
audience, split read tools from write tools into separate scopes, fail closed
when a tool's identity cannot be verified, sandbox and tightly bind local
servers, pin versions and integrity-check server updates, and log a correlation
ID linking prompt → tool selection → parameters → output → downstream request —
are individually familiar but are not currently stated together as an
MCP-specific checklist.

The risk taxonomy it uses: prompt injection; indirect prompt injection via
retrieved content; tool poisoning (manipulated tool descriptions, parameters,
or defaults steering the model); tool shadowing / name collision (a lookalike
tool capturing requests intended for a legitimate one); confused-deputy
authorization failure (server acts with its own broad privileges instead of
user-bound ones); token passthrough and weak audience validation; session
hijacking and event injection against resumable stateful connections; local
server compromise (file access, command execution, pivoting); excessive scopes
and permission creep; and weak auditability. Its forward-looking asks are
mandatory authentication for any networked MCP server, policy decided on full
context (prompt, user, tool, parameters, target system — not just an allowlist),
monitoring as a first-class control, and human approval gates on actions that
create, modify, delete, pay, or escalate privileges.

## Primary source for this cluster

[aie-024-model-context-protocol-security-best-practices.md](aie-024-model-context-protocol-security-best-practices.md)

## Fidelity check

1. Claim: the ten-risk taxonomy listed above. Support: the capture enumerates
   each of those risk headings in its section on the top MCP security risks,
   with a one-line mitigation tip attached to each.
