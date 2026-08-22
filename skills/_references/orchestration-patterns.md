# Orchestration Patterns

Reference catalog of agent-orchestration patterns this kit endorses, plus anti-patterns to avoid.
Read this before adding an explicit workflow that coordinates multiple personas, or before
introducing a persona that wraps existing ones.

The governing rule: **the user or an explicit workflow is the orchestrator. Personas do not invoke
other personas.** Skills are mandatory hops inside a persona's workflow.

---

## Endorsed patterns

### 1. Direct invocation

Use one persona for one perspective and one artifact. This is the default and least expensive
shape.

```text
user -> code-reviewer -> report -> user
```

**Use when:** the work is one perspective on one artifact and can be described in one sentence.

**Examples:**

- "Review this change" -> `code-reviewer`
- "Find security issues in `auth.ts`" -> `security-auditor`
- "What tests are missing for checkout?" -> `test-engineer`

**Cost:** one round trip. Compare every orchestrated pattern against this baseline.

---

### 2. Single-persona workflow

An explicit workflow can wrap one persona with the project's skills, saving the user from
re-explaining the same setup.

```text
review workflow -> code-reviewer with the code-review skill -> report
```

**Use when:** the same single-persona invocation happens repeatedly with the same setup.

**Cost:** the same as direct invocation. The workflow is a saved, explicit prompt.

**Anti-signal:** if the workflow mostly decides which persona to call, delete it and let the user
invoke the persona directly.

---

### 3. Parallel fan-out with merge

Multiple personas operate on the same input concurrently and produce independent reports. The main
session synthesizes them into one decision.

```text
                         +-> code-reviewer -----+
ship workflow -> fan-out +-> security-auditor --+-> merge -> verdict + rollback plan
                         +-> test-engineer ------+
```

**Use when:**

- The sub-tasks are independent, with no shared mutable state or ordering dependency.
- Each worker benefits from its own context window.
- Each persona produces a different kind of finding.
- The merge step fits in the main session's remaining context.
- Wall-clock latency matters.

**Cost:** N parallel worker contexts plus one merge turn. It costs more than direct invocation but
usually finishes sooner and keeps each perspective focused.

**Validation checklist:**

- [ ] Can every worker run at the same time without ordering issues?
- [ ] Does each persona use a distinct failure-mode lens?
- [ ] Will the merge fit in the main session's remaining context?
- [ ] Is the wait long enough for parallelism to matter?

If any answer is "no," use direct invocation or a single-persona workflow.

---

### 4. Sequential pipeline driven by the user

The user runs explicit workflows in a defined order, carrying artifacts or commit history between
them. There is no routing persona; the user is the orchestrator.

```text
define -> plan -> build -> test -> review -> ship
```

**Use when:** later steps depend on earlier outputs and human judgment between steps adds value.

**Cost:** one worker context per step, with no extra routing context.

**Why not hide it behind a routing persona:** that would lose human checkpoints, compress important
handoff context, and add a paraphrasing turn at every step.

---

### 5. Research isolation

When a task requires reading a large amount of material that should not consume the main session's
context, delegate the research and request only a compact digest.

```text
main session -> read-only research worker -> digest -> main session continues
```

**Use when:**

- The main session must stay focused on a downstream decision.
- The result is much smaller than the material inspected.
- The research can be constrained to read and search capabilities.

**Cost:** one isolated worker context. Use a host-native read-only research worker when one is
available; otherwise delegate with an explicit read-only scope and require a compact digest.

---

## Claude Code host appendix

### Where personas live

Plugin subagents live in `agents/` at the plugin root. This repository's
`.claude-plugin/plugin.json` manifest makes `agents/code-reviewer.md`,
`agents/security-auditor.md`, and `agents/test-engineer.md` discoverable when
the plugin is enabled; no extra path configuration is required.

### Subagents versus Agent Teams

Claude Code exposes two parallelism primitives. Use subagents for independent
fan-out whose results return to the main session. Use Agent Teams only when
workers must message one another or coordinate through a shared task list.

| | Subagents | Agent Teams |
|--|-----------|-------------|
| Coordination | Main session fans out; workers report back | Teammates message one another and share a task list |
| Context | One context per subagent | One context per teammate |
| Best fit | Independent reports with one merge | Collaborative investigation or adversarial debate |
| Status | Stable | Experimental; requires `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` |
| Cost | Lower | Higher; every teammate is a separate model instance |

The same persona definitions work in both modes. When used as subagents they
report to the main session. When used as teammates their persona instructions
are appended to the team-coordination prompt and they can challenge one
another directly.

The `skills` and `mcpServers` persona-frontmatter fields apply to subagents but
are ignored for teammates. Teammates inherit project and user session settings.
If a persona requires a skill or MCP server in both modes, configure it at the
session level.

### Platform-enforced nesting rules

- Subagents cannot spawn other subagents.
- Teammates cannot create nested teams.

These restrictions enforce the no-persona-trees rule. Keep the main session as
the orchestration owner instead of trying to work around them.

### Built-in subagents

Check the built-ins before defining a custom research persona:

| Built-in | Purpose |
|----------|---------|
| `Explore` | Read-only codebase search and analysis for research isolation |
| `Plan` | Read-only research during plan mode |
| `general-purpose` | Multi-step work that needs exploration and modification |

Do not redefine them. Add specialist personas such as `code-reviewer`,
`security-auditor`, and `test-engineer` alongside them.

### Plugin-agent frontmatter

Plugin subagents do not honor `hooks`, `mcpServers`, or `permissionMode`; those
fields are silently ignored. A persona that truly needs those fields must be
copied into `.claude/agents/` or `~/.claude/agents/` and treated as user- or
project-owned configuration.

Supported plugin-agent fields include `name`, `description`, `tools`,
`disallowedTools`, `model`, `maxTurns`, `skills`, `memory`, `background`,
`effort`, `isolation`, `color`, and `initialPrompt`. Choose an explicit model
only when the persona's cost or reasoning needs justify it; for example, Haiku
can fit a bounded coverage scan, Sonnet a routine review, and Opus a deep
security analysis.

### Parallel dispatch

Parallel fan-out requires multiple Agent tool calls in one assistant turn.
Putting the calls in sequential turns serializes the workers. Require one
explicit merge after all workers return.

### Competing-hypothesis debugging with Agent Teams

Use Agent Teams when several plausible causes fit an intermittent failure and
workers must actively disprove one another. For example, one teammate can
investigate races and blocking calls, a second authentication and synchronous
network boundaries, and a third tests that distinguish the hypotheses. Ask
them to message counter-evidence directly and converge only when at least two
can rule out the alternatives.

This is different from a ship review. A ship review needs independent lenses
and one verdict; competing-hypothesis debugging needs discussion among the
investigators. Agent Teams therefore earns its higher cost only when the
cross-worker debate materially improves the conclusion.

Agent Teams requires Claude Code v2.1.32 or later and this one-time setting:

```json
{
  "env": {
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"
  }
}
```

When the investigation finishes, tell the lead to clean up the team. Teammates
lack the lead's complete team context and must not own cleanup.

---


## Anti-patterns

### A. Router persona

A persona whose only job is to decide which other persona should run.

```text
work workflow -> router -> "this needs review" -> code-reviewer -> router -> user
```

**Why it fails:**

- It adds no domain perspective.
- Two extra paraphrasing hops lose information and add cost.
- It hides a choice the user or explicit workflow can make directly.

**What to do instead:** refine explicit workflows and document intent-to-workflow mapping in
CLAUDE.md.

---

### B. Persona that calls another persona

For example, a `code-reviewer` internally invokes `security-auditor` when it sees authentication
code.

**Why it fails:**

- Personas are designed to produce one perspective; chaining defeats that boundary.
- The calling persona's summary loses context the next persona needs.
- Failure modes and output contracts become ambiguous.
- Cost becomes invisible to the user.

**What to do instead:** have the persona recommend a follow-up audit. The user or explicit workflow
runs the second pass.

---

### C. Sequential orchestrator that paraphrases

An agent that invokes define, plan, build, test, and review workflows on the user's behalf.

**Why it fails:**

- It removes the checkpoints that catch wrong-direction work.
- Every handoff summarizes context, so drift accumulates.
- It doubles the orchestration turns without adding a new perspective.

**What to do instead:** keep the user as orchestrator and document the recommended sequence.

---

### D. Deep persona trees

For example, a ship workflow calls a pre-ship coordinator, which calls a quality coordinator, which
calls `code-reviewer`.

**Why it fails:**

- Every layer adds latency and cost without decision value.
- Failures become a multi-level investigation.
- Leaf workers receive increasingly lossy summaries.

**What to do instead:** keep ordinary orchestration depth at most one: explicit workflow to
personas, followed by a merge in the main session. A managed pipeline may deliberately use a deeper
contract when each boundary is typed, persisted, and evidence-gated; do not copy that depth into ad
hoc persona trees.

---

## Decision flow

```text
Is the work one perspective on one artifact?
+-- Yes -> Direct invocation. Stop.
+-- No  -> Will the same composition repeat?
          +-- No  -> Direct invocation, assembled ad hoc. Stop.
          +-- Yes -> Are the sub-tasks independent?
                     +-- No  -> User-driven sequential workflows.
                     +-- Yes -> Parallel fan-out with one explicit merge.
                                Validate the checklist above first.
```

---

## Why these patterns work

Single-context execution drifts in predictable ways. The endorsed patterns counter three recurring
failure modes:

- **Agentic laziness** — the worker declares completion early or takes the cheapest path.
  *Counter:* isolate work items and loop with an explicit completion check.
- **Self-preferential bias** — a worker rates its own output too highly.
  *Counter:* use a separate verifier with a distinct failure-mode lens.
- **Goal drift** — a long run or lossy compaction loses the original objective.
  *Counter:* restate acceptance criteria in each fresh worker context and keep handoffs flat.

## Programmatic orchestration

The patterns above describe personas. A lower-level harness may also drive fan-out from one
orchestrator. The same isolation principle applies, with a few reusable shapes:

- **fan-out-and-synthesize** — split a work list, run each item in its own context, merge results.
- **generate-and-filter** — over-generate candidates, then retain only rubric-passing results.
- **tournament** — compare candidates pairwise when exactly one winner is needed.
- **loop-until-done / loop-until-dry** — repeat until a completion or no-new-findings check passes.

Use this layer for large, repetitive, or adversarial work. It costs more than a single pass, so pair
it with .claude/rules/evals.md to confirm the extra cost improves quality.

## When to add a new pattern

Add a pattern only after:

1. It has been used at least twice in real work.
2. A concrete artifact demonstrates it.
3. An existing pattern is demonstrably insufficient.
4. Its anti-pattern shadow is documented.

Premature catalog entries become aspirational documentation that no one follows.
