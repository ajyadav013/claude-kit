# Engineering Delivery Rules

These rules are mandatory for all work in this repository. They define an autonomous,
agent-driven software development lifecycle (SDLC): every change moves through spec →
review → implementation → code review → testing → security → delivery, with quality
gates between phases.

> Installed by **claude-kit**. The full pipeline, agents, skills, and rule details live in
> `.claude/rules/`, `.claude/agents/`, and `.claude/skills/`. This file is the entry point.

---

## Coding Behavior (applies to ALL implementation work)

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

### Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them — don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it — don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

### Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan with a verification check per step.

Strong success criteria let you loop independently. Weak criteria ("make it work")
require constant clarification.

---

## 1) Spec-first rule
Do not write implementation code until a written spec exists.

Before coding:
- identify whether a relevant spec already exists
- if not, draft one first
- if the task changes, update the spec before continuing

A task is not ready for implementation until the spec is explicit enough to review.

## 2) Review workflow before implementation
Before writing code, follow this workflow:

1. **Spec & Doc Writer** writes specification + developer documentation in a single pass
2. **UI Designer** (if UI work) — drafts and self-reviews the design spec
3. Spec is reviewed by the appropriate **Senior Developer** (per work stream)
4. Spec is reviewed by the **Technical Architect** — validates system design, scalability, integration
5. Spec is reviewed by the **Engineering Manager** — final strategic and completeness check
6. **Implementation** starts only after all reviews are complete

At any stage, reviewers may request corrections. If anything is missing, update the spec
and re-run the affected review.

### Parallel execution for multi-stream work
When a task spans two or more **independent work streams** (the canonical example is a
backend lane and a frontend lane, but it applies to any split — service A vs. service B,
API vs. client, data layer vs. UI):

- Each stream's review chain (Senior Developer → Technical Architect → EM) runs **in parallel**.
- After all review chains pass, a **Merge Reviewer** verifies cross-stream consistency
  (shared contracts, data models, shared state).
- Implementation then runs **in parallel**, one stream per isolated worktree, each with
  its own **Code Reviewer**.
- After all implementations pass code review and unit tests, the **Merge Reviewer** verifies
  integration compatibility.
- Only then does integration testing proceed.

Independent work streams must never block each other. Merge-reviewer gates ensure
consistency at join points.

## 3) Design-first workflow for UI changes
For any frontend, UI, UX, or interaction change:

1. the **UI Designer** drafts a design spec (includes self-review against a quality checklist)
2. the design spec describes: screen states, interactions, component behavior,
   empty/loading/error states, responsive behavior, accessibility
3. UI implementation begins only after the design spec is complete

Do not start UI implementation from a vague request when a design spec is required.

## 4) Required roles
Each role maps to a dedicated agent in `.claude/agents/`:

**Spec & Documentation:** Spec & Doc Writer · UI Designer
**Review chain (per work stream):** Senior Developer · Technical Architect · Engineering Manager
**Implementation & code review:** Developer · Code Reviewer
**Testing:** Tester · Senior Tester · Unit Tester · E2E Tester
**Security:** Security Reviewer + sub-scanners (Secret · Dependency · OWASP · Policy)
**Review rigor:** Devil's Advocate (anti-sycophancy, on a unanimous PASS)
**Integration:** Merge Reviewer
**Delivery & operability:** DevOps Engineer · Observability Engineer · PR Raiser
**Coordination:** Orchestrator (never writes code — only delegates and gates)

State which role is being simulated at each stage when it helps clarity.

## 5) Testing workflow
After implementation, testing runs in parallel lanes for multi-stream work:

- **Tester phase (parallel):** API/contract tester · UI tester · integration (end-to-end) tester
- **Senior Tester phase (parallel, after testers):** each independently verifies a tester's
  coverage and findings
- **Test-coverage merge review:** the Merge Reviewer confirms every acceptance criterion is
  covered across lanes, with no gaps and no contradictions

For single-stream or small features, a single Tester + single Senior Tester is sufficient.
Testing is not complete until senior verification AND the coverage merge review pass.

## 6) Defect loop
If any failure, defect, regression, or spec mismatch is found:

1. document the issue clearly and classify it by work stream
2. update the spec if expected behavior is unclear
3. re-run **only the affected stream(s)** through their chain
4. re-run the Merge Reviewer for cross-stream consistency
5. then re-run Tester → Senior Tester for the affected lanes only

Do not patch defects informally outside the process. Do not re-run unaffected lanes.

## 7) Output expectations
For each meaningful task, produce outputs in this order unless explicitly overridden:

1. feature spec + developer documentation
2. design spec (if UI work)
3. review notes (senior developer → technical architect → EM, per stream)
4. merge review (spec consistency) — multi-stream only
5. implementation / code changes
6. code review notes (per stream)
7. merge review (code integration) — multi-stream only
8. tester reports → senior tester verification → test-coverage merge review
9. security review (Security Clear)
10. DevOps (Pipeline Green) + Observability (Observability Ready) — for deployable/observable changes
11. final summary with open issues, if any

## 8) Quality bar
Optimize for: simplicity, correctness, scalability, reliability, maintainability,
observability, testability, security, and user experience.

## 9) Documentation standard
Every change must maintain or improve documentation. See `.claude/rules/documentation.md`.

Mandatory for every change:
- **Module/file docstring or header** in every new/modified source file
- **Docstring on every public function** (arguments, return value, errors/exceptions raised)
- **Full type annotations** where the language supports them — no untyped public signatures
- **No bare/loose container types** — prefer named, typed structures over opaque maps
- **README updated** when endpoints, env vars, project structure, or architecture change
- **API metadata** (summary, response schema, status codes) on every endpoint, where applicable

## 10) Guardrails
Do not:
- skip the spec + dev-doc stage
- skip the design flow for UI work
- skip the senior developer, technical architect, or EM review
- skip the code review
- mark work complete without tester validation
- mark testing complete without senior tester verification
- skip the merge reviewer at join points for multi-stream work
- submit code with missing docstrings or type annotations
- submit code without updating the README when endpoints or architecture changed

If the user asks for speed, you may compress the process but must preserve the sequence
and outputs.

**Fast-track mode:** For bug fixes, typos, single-component changes, or config updates
(< 5 files), skip the spec/design/review chain and go straight to:
Developer → Code Reviewer → Tester → PR Raiser.

See `.claude/rules/mandatory-workflow.md` for the full step-by-step pipeline with agent
roles, gating rules, and the defect-loop protocol.

---

## 11) Working memory, self-check & quality gates

- **Working memory:** read/write `.claude/CONTINUITY.md` every turn and at each stage
  transition so work survives context compaction and new sessions. Distinct from
  `.claude/agent-memory/` (durable learnings). See `.claude/rules/continuity.md`.
- **RARV:** every agent runs Reason → Act → Reflect → Verify and shows a green Verify
  before handoff. See `.claude/rules/rarv-cycle.md`.
- **Severity model:** classify every finding Critical/High/Medium/Low/Cosmetic; a gate
  passes only with zero Critical/High/Medium open. See `.claude/rules/quality-gates.md`.
- **Blind review + Devil's Advocate:** parallel reviewers assess independently; a unanimous
  PASS triggers the `devils-advocate` agent before the gate counts. See `.claude/rules/quality-gates.md`.
- **Security review:** the `security-reviewer` dispatches `secret-scanner`,
  `dependency-scanner`, `owasp-reviewer`, and `policy-validator`, and gates **Security Clear**
  before delivery. See `.claude/rules/quality-gates.md`.
- **DevOps & Observability:** for changes touching a deployable/observable surface, the
  `devops-engineer` (Pipeline Green) and `observability-engineer` (Observability Ready)
  gates run after testing and before the PR. See `.claude/rules/devops-observability.md`.

---

## Project-specific rules

> Add your stack's conventions here (language style, framework patterns, naming, directory
> layout, test commands). The pipeline is stack-agnostic; this section is where you make it
> yours. Add matching rule files under `.claude/rules/` and reference them from the relevant
> agents.
