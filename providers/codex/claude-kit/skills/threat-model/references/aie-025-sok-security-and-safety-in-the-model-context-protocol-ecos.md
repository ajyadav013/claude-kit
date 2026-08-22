---
source: https://arxiv.org/html/2512.08290v2
author: Shiva Gaire, Srijan Gyawali, Saroj Mishra, Suman Niroula, Dilip Thakur, Umesh Yadav (arXiv preprint)
license-note: ideas absorbed in own words; no text or code reproduced
---

# In MCP, read-only Resources escalate into privileged Tool calls

## What it teaches
This systematization argues that MCP dissolves the usual boundary between a
security failure (an adversary forces an unauthorized action) and a safety
failure (the system does exactly what the protocol says and still causes
harm), because the caller deciding the execution path is a probabilistic
model reading attacker-reachable context. It splits the risk surface across
the three MCP primitives — Resources (passive read), Tools (action), Prompts
(server-supplied templates) — and shows that each lives in a different trust
domain spread over independent Hosts, Clients, and Servers, so the single
safety perimeter that a monolithic LLM app relies on no longer exists. The
paper's sharpest structural claim is cross-primitive escalation: a low-trust
Resource can carry an instruction that a high-privilege Tool Server then
executes. It then catalogues defenses as five layers — signed tool
provenance, capability-bound authorization, context validation, session and
transport isolation, continuous monitoring — and grounds them in
reconstructed incidents, notably the 2025 Supabase leak where an agent
holding a service_role credential read a token table that role-based
policies denied to every human in the workflow.

## Key patterns & decisions
- **Security and safety are one threat model here, not two** — an injected
  document (security) makes the model sincerely believe it is authorized to
  destroy data (safety), and a parameter hallucination (safety) exfiltrates
  secrets to a log (security). Threat modelling an agent that treats them as
  separate columns will under-count the real failure paths.
- **Cross-primitive escalation is the systemic gap** — read access is
  usually approved casually because "it cannot do anything." In MCP the
  content that read access pulls in becomes the instruction stream for a
  Tool that can write. Scope the *combination*, not each primitive alone.
- **Tool definitions are mutable, so install-time approval is not enough** —
  the paper attributes rug-pull attacks to four structural causes: server-side
  logic that can change, no continuous integrity checking, no trigger that
  forces re-approval, and the reuse of trust earned on day one. The proposed
  answer (ETDI) is a provider-signed manifest plus an immutable version tag,
  verified at both load and invocation, with any functional change demanding
  a new signature and explicit re-authorization.
- **Name collisions and server shadowing are a real routing attack** — when
  two connected servers both expose a plausible function name, a malicious
  one can absorb the call while the agent and user believe the trusted server
  handled it. Namespace isolation and a canonical registry record are the
  controls, not user vigilance.
- **Capability tokens beat identity-based permissions** — bind rights to the
  specific action (read-only, no network) in a short-lived token that cannot
  be replayed outside its scope, enforce it at a gateway that intercepts
  tool calls, and pair it with mTLS and continuous re-authorization rather
  than persistent grants.
- **Instruction/data segregation needs deterministic filters, not prompt
  pleading** — the recommended layering is unambiguous structural delimiters
  around external content, deterministic sanitization and output encoding of
  every tool output, and provenance analysis that attributes a tool call back
  to genuine user intent rather than to injected metadata.
- **Least privilege is the control that bounds injection damage** — the
  Supabase post-mortems converge on the same point: a scoped read-only
  credential would have capped the incident at a read, because the exfil
  step required write access to a customer-visible channel.
- **Efficiency optimizations become cross-tenant side channels** — sharing
  key-value caches across requests with identical prompt prefixes leaks
  whether two users' prompts share a prefix, which is enough to reconstruct
  another tenant's prompt token by token. Multi-tenant serving should
  partition caches and vector indexes per tenant and accept the cost.
- **Policy has to be federated or it will conflict** — a database rule that
  the AI deputy never learns about is not a control. Translate data-layer
  classifications into the agent's operating envelope, decide which layer is
  the final gatekeeper, and log *which* policy fired on every decision.

## When to apply / trade-offs
Reach for this when a system lets a model call tools over MCP against real
data — especially with more than one server connected, more than one tenant
served, or any credential broader than read-only. The controls are not free:
signing and registry verification impose an operator burden and central
authority that cuts against the permissionless ecosystem that made MCP
spread; per-tenant cache and index partitioning trades measurable serving
efficiency for isolation; and human-in-the-loop gating on high-impact actions
slows throughput and, if over-triggered, produces alert fatigue that makes
the gate decorative. Skip the heavier machinery for a single-user local agent
whose servers you wrote and whose credentials are already read-only — there
the payoff is scoping the credential and reading the tool definitions, not
building a registry. Also note the paper's own limits: it is a survey, its
central defenses (signed manifests, decision-provenance guards, formal
verification of the protocol) are proposals and prototypes rather than
deployed standards, and its long-horizon predictions about MCP becoming an
OS layer are speculative.

## Fidelity check
1. Claim: cross-primitive escalation is the paper's named structural
   vulnerability class. Support: the contributions list calls out analysing
   how decoupling Resources from Tools creates Cross-Primitive Escalation
   where read-only access is weaponized to trigger write actions, and a
   dedicated subsection on Cross-Primitive Execution Attacks repeats it.
2. Claim: rug-pull attacks have four structural causes and ETDI answers them
   with signatures verified at load and invocation plus immutable versions.
   Support: the supply-chain section attributes rug-pulls to mutable
   server-side logic, absent continuous integrity checks, no re-approval
   triggers, and exploitation of established trust; the mitigation section
   describes provider-signed manifests, verification at load and invocation,
   and immutable version tags requiring re-authorization on change.
3. Claim: the Supabase incident turned on an over-privileged credential that
   bypassed row-level policies. Support: the case study states the agent held
   service_role credentials that ignore RLS, that the human support role could
   not reach the token table, and that a scoped read-only credential would
   have limited the damage.
