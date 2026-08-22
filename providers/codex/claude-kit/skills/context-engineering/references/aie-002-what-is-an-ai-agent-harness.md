---
source: https://www.databricks.com/blog/ai-harness
author: Databricks (Databricks Staff)
license-note: ideas absorbed in own words; no text or code reproduced
---

# As models converge, the harness — not the model — decides agent outcomes

## What it teaches
An agent is not a model; it is a model plus a harness, and the harness is the
software layer that converts a reasoning step into an executed action and feeds
the real result back. The piece frames this as `Agent = Model + Harness` and
walks the reason → act → observe → repeat cycle (ReAct, attributed to Yao et
al., 2022) to show which half owns which responsibility: the model decides, the
harness runs the tool, captures the output, and re-enters it as context. It then
enumerates eight components every production harness carries — system prompt,
tools plus a tool executor, sandbox, durable filesystem, memory/context
management, verification feedback loops, guardrails with human approval, and
observability. The argument that matters for engineering practice is the
ranking claim: as models converge, harness quality increasingly determines
outcomes, so a strong harness around a mid-tier model can beat a weak harness
around a better one. The piece closes on the enterprise consequence — dozens of
independently-built harnesses become ungovernable "agent sprawl" — and names a
discipline ladder where prompt engineering and context engineering are both
subsets of harness engineering.

## Key patterns & decisions
- **Agent = Model + Harness, and debug accordingly** — the model reasons; the
  harness executes, remembers, and enforces. Naming which layer owns a failure
  is the first triage step, and the claim is that most production agent
  failures originate in the harness rather than in model reasoning.
- **The eight-block harness inventory as a completeness checklist** — system
  prompt, tools + execution, sandbox, filesystem/durable storage, memory and
  context management, feedback/self-verification, guardrails with
  human-in-the-loop, observability. Each block exists to patch a specific
  limitation of a raw model, so a missing block is a named, predictable defect.
- **Code execution is displacing large tool catalogues** — rather than shipping
  many narrowly-scoped tools, give the agent the general ability to write and
  run code so it can compose a workflow dynamically instead of picking from a
  fixed action set.
- **Sandboxes are both a safety control and a scaling control** — isolation
  keeps agent-generated code off real systems and gives a workspace you can
  monitor, reset, or destroy; the same isolation is what makes running many
  agents in parallel feasible.
- **A durable filesystem changes the collaboration medium** — persisting plans,
  notes, and intermediate work to files (not just chat turns) lets agents
  resume long tasks and hand work to humans or other agents through a shared
  workspace.
- **Context compaction is a harness responsibility, not a model one** — the
  harness decides what stays live and what gets summarized as history grows,
  and stores/retrieves cross-session history so the agent resumes with
  awareness of prior work.
- **Verification loops are what make long tasks survivable** — after each
  action the harness can run tests, inspect output, or force the model to
  review its own work, so errors are caught and corrected inside the loop
  rather than surfacing as a confident wrong answer at the end.
- **A named failure taxonomy for triage** — context rot (reasoning degrades as
  history grows), tool overload (too many tools slows and confuses selection),
  brittle tool wiring (small description/calling changes cause silent
  misuse), latency (multi-step chains reaching 10s or more), irrelevant
  retrieval, weak verification (stopping early or declaring false success),
  and missing guardrails on irreversible actions.
- **Shared harness infrastructure is the answer to agent sprawl** — when
  dozens of teams each build their own harness, no one can govern access,
  evaluate outputs, audit decisions, or swap the underlying model; a shared
  control plane centralises governance, observability, and evaluation.

## When to apply / trade-offs
Apply this framing the moment you move past a single-turn LLM call into
anything that takes actions across turns — it tells you what to build and what
to blame. Its cost is real: eight components is a lot of infrastructure for a
prototype, and sandboxes, durable storage, evaluation harnesses, and audit
trails are each their own build. For a one-off internal script that only reads
and summarises, most of it is overhead. The piece itself hedges its own
premise twice: as models improve at planning, self-verification, and error
recovery, some harness work is expected to migrate into the model, and it
floats disposable per-task harnesses and natural-language-configured harnesses
as directions that would make today's heavyweight, long-lived harness
infrastructure look overbuilt. Treat the eight blocks as a checklist to
consciously decide against, not a mandatory build order. Note also that this
is vendor content — the enterprise-governance section resolves to a specific
product pitch, so take the sprawl diagnosis and discount the prescribed cure.

## Fidelity check
1. Claim: an agent is a model plus a harness, with the model deciding and the
   harness executing. Support: the capture states the equation `Agent = Model +
   Harness` explicitly, and its comparison table gives the model the reasoning,
   prediction, and generation duties while the harness runs actions, holds
   memory, drives tools, and applies the rules, with the agent as the combined
   system.
2. Claim: there are eight named production harness building blocks. Support:
   the capture devotes a section to the eight building blocks a production
   harness needs, carrying exactly eight subsections — system prompts; tools
   and tool execution; sandboxes and execution environments; filesystem and
   durable storage; memory and context management; feedback loops and
   self-verification; guardrails and human-in-the-loop controls; observability
   and logging.
3. Claim: a strong harness around a weaker model can beat a weak harness around
   a stronger one. Support: the capture asserts this for workflow-heavy tasks
   and adds a benchmark datapoint — pairing GPT-5.5 with an OfficeQA Pro agent
   harness scored 52.63% versus 36.10% with GPT-5.4.
