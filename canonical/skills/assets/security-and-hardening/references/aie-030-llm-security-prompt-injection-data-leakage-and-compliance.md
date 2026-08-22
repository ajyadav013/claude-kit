---
source: https://myengineeringpath.dev/genai-engineer/llm-security/
author: Mohit Saxena — MyEngineeringPath
license-note: ideas absorbed in own words; no text or code reproduced
---

# Securing an LLM app is two jobs: a guardrail stack and a compliance layer

## What it adds beyond the primary

The MCP primary treats agent security as a delegation/OAuth problem; this piece
treats it as an application-security problem and then keeps going into ground
the kit does not touch. Three additions stand out. First, it splits data
leakage into three mechanically distinct forms with different owners — training
data memorisation (a base-model property, mitigated operationally by not
fine-tuning on data you would not want reproduced), system prompt leakage, and
in-context PII leakage — where the kit currently treats "leak" as one output-
scan concern. Second, it names **prompt echo detection** as a security signal
rather than a quality one: if a response reproduces a substantial share of the
system prompt, that is simultaneously a disclosure incident and evidence that
an injection landed, so it belongs in the alerting path. Third, and most
novel for the kit, it maps LLM plumbing onto GDPR, CCPA and SOC 2 concretely:
embedding user data in a prompt bound for a third-party API *is* processing
under GDPR and needs a lawful basis plus a signed DPA that forbids provider-
side training; right-to-erasure only works if request logs are keyed by user
ID and deletable; residency may force an EU-region or self-hosted deployment;
under CCPA, a provider training on your data may qualify as a "sale". It also
states the boundary the kit's guardrail reference implies but never says
outright — an LLM is not a security boundary, so any control that depends on
the model obeying instructions is probabilistic, never deterministic, and the
confidentiality guard on a system prompt is therefore a soft control that
justifies a hard rule: never place secrets in a system prompt.

## Primary source for this cluster

[aie-024-model-context-protocol-security-best-practices.md](aie-024-model-context-protocol-security-best-practices.md)

## Fidelity check

1. Claim: security and compliance are separate concerns, both required for
   enterprise deployment. Support: the capture states that compliance is not
   the same as security — a system can be compliant but insecure or secure
   but non-compliant — and that both are needed for enterprise deployment.
