# Agentic Design Patterns — coverage map

This document maps the 21 patterns (plus Appendix A) of *Agentic Design Patterns: A Hands-On Guide to
Building Intelligent Systems* by Antonio Gulli onto claude-kit, and records what the kit deliberately
does **not** implement and why.

It exists for two reasons: to show that every pattern in the book is **accounted for** (either already
present or consciously out of scope), and to document the provenance of the rules that were added to
fill the genuine gaps. Concepts are paraphrased and adapted to this kit — no text is copied from the
book.

## How the kit already realizes the patterns

claude-kit is a stack-agnostic, config-only SDLC kit. Most agentic patterns are not new ideas to add —
they are already embodied in its rules, agents, skills, and the orchestration model. The table shows
**where each pattern lives**.

| # | Pattern | Where it lives in claude-kit | Status |
|---|---------|------------------------------|--------|
| 1 | Prompt Chaining | `rules/mandatory-workflow.md` (sequential stages); `skills/_references/orchestration-patterns.md` §4 | covered |
| 2 | Routing | `orchestrator` classifies bug / feature / fast-track; "Which Workflow?" in mandatory-workflow | covered |
| 3 | Parallelization | parallel backend/frontend lanes; orchestration-patterns §3 (fan-out + merge; multiple `Agent` calls in one turn) | covered |
| 4 | Reflection | `rules/rarv-cycle.md` (Reflect); `agents/devils-advocate.md`; `skills/doubt-driven-development`; blind review in `rules/quality-gates.md` | covered (strong) |
| 5 | Tool Use | each agent's `tools:` frontmatter; MCP integration | covered |
| 6 | Planning | `agents/spec-doc-writer`, `story-planner`, `technical-architect`; `skills/spec-driven-development`, `planning-and-task-breakdown`, `scope`, `sprint` | covered (strong) |
| 7 | Multi-Agent Collaboration | 28 agents; subagents + Agent-Teams worked example in orchestration-patterns | covered (strong) |
| 8 | Memory Management | `rules/continuity.md` (working) + `rules/agent-memory.md` (durable, now with the **working/episodic/semantic/procedural** taxonomy); `skills/remember`, `consolidate-learnings`, `context-engineering` | covered (taxonomy added) |
| 9 | Learning & Adaptation | `rules/agent-memory.md`; `skills/remember`; the `load-learnings` SessionStart hook | covered |
| 10 | Model Context Protocol (MCP) | `catalog/mcp.yaml` → `.mcp.json`; `skills/browser-testing-with-devtools` | covered (strong) |
| 11 | Goal Setting & Monitoring | **`rules/goal-setting-and-monitoring.md`** (new) + spec acceptance criteria + `acceptance-reviewer` + quality-gates process signals | **rule added** |
| 12 | Exception Handling & Recovery | **`rules/agent-resilience.md`** (new) + gate retry budgets + `skills/debugging-and-error-recovery` (product bugs) | **rule added** |
| 13 | Human-in-the-Loop | **`rules/human-in-the-loop.md`** (new, consolidates) + mandatory-workflow 1b/3d + `skills/interview-me` | **rule added** |
| 14 | Knowledge Retrieval (RAG) | `skills/source-driven-development` (official-docs grounding); a docs MCP server; native file reading | covered for the kit's scope |
| 15 | Inter-Agent Communication (A2A) | CONTINUITY handoffs; the `Task` tool; Agent-Teams messaging in orchestration-patterns | covered |
| 16 | Resource-Aware Optimization | model-tier + effort section of **`rules/reasoning-techniques.md`** (new); `skills/context-engineering`, `code-simplification`, `performance-optimization`; per-agent `model:` | covered (note added) |
| 17 | Reasoning Techniques | **`rules/reasoning-techniques.md`** (new): CoT, ReAct, ToT/self-consistency, step-back, extended thinking | **rule added** |
| 18 | Guardrails / Safety | **`rules/agent-guardrails.md`** (new, agent operation) + `agents/security-reviewer` + sub-scanners + `skills/security-and-hardening`, `security-verification` (product) | **rule added** |
| 19 | Evaluation & Monitoring | `skills/code-review-and-quality`, `smoke-test`, `manual-test`, `playwright-verification`; `rules/quality-gates.md`; `agents/devils-advocate` | covered |
| 20 | Prioritization | folded into `rules/goal-setting-and-monitoring.md`; `skills/planning-and-task-breakdown`, `triage`, `sprint`, `backlog`; `story-planner` ordering | covered |
| 21 | Exploration & Discovery | research isolation via the built-in `Explore` subagent; `skills/idea-refine` | out of scope (see below) |
| A | Advanced Prompting | folded into `rules/reasoning-techniques.md`; `skills/execute`, `context-engineering`, `idea-refine` | covered |

## What was added to fill the gaps

The book's recurring thesis — *treat agents as complex software* — pointed at one coherent layer the
kit under-specified: how the **agents themselves** reason, stay safe, and recover (as opposed to how
the **product** they build is secured and tested, which was already strong). Five always-on rules were
added (shipped to every profile, since core rules are not profile-gated):

- `rules/reasoning-techniques.md` — Chain-of-Thought, ReAct, Tree-of-Thought / self-consistency,
  step-back, extended-thinking budget, and resource-aware model-tier selection (Ch. 17, App. A, Ch. 16).
- `rules/agent-guardrails.md` — untrusted-input handling (prompt-injection defense), output validation
  before handoff, and tool least-privilege (Ch. 18, *agent operation*).
- `rules/agent-resilience.md` — bounded retries/backoff, fallback, circuit-breaker, graceful
  degradation, idempotency, and checkpointing (Ch. 12).
- `rules/goal-setting-and-monitoring.md` — measurable success criteria, progress monitoring, and
  prioritization with dynamic re-prioritization (Ch. 11, Ch. 20).
- `rules/human-in-the-loop.md` — the consolidated set of decision points where the pipeline must pause
  for a human, plus the escalation protocol (Ch. 13).

Plus a light enhancement: the **memory taxonomy** in `rules/agent-memory.md` (Ch. 8).

## What we deliberately did NOT add, and why

- **A vector RAG store (Ch. 14).** claude-kit ships configuration, not infrastructure. Grounding in
  authoritative sources is handled by `skills/source-driven-development`, an optional docs MCP server,
  and native file reading. Standing up an embeddings store is an application concern, out of scope for
  a config kit.
- **Exploration & Discovery agents (Ch. 21).** That pattern targets open-ended research/science agents
  (hypothesis generation, experiment design). claude-kit is a software-**delivery** lifecycle; read-
  heavy investigation is already served by the built-in `Explore` subagent and `skills/idea-refine`.
- **Redundant rules for already-covered patterns.** Patterns 1–7, 9, 10, 15, 19, 20 are implemented by
  existing rules/agents/skills. Adding parallel rules would dilute description-based agent selection
  (the kit's golden rule #1) and add maintenance cost for no behavioral gain — so they were left as is
  and simply mapped here.

---

*Source: Antonio Gulli, "Agentic Design Patterns: A Hands-On Guide to Building Intelligent Systems."
Patterns referenced for attribution; all rule content in this kit is original paraphrase.*
