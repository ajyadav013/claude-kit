# temporal-developer

Temporal **fundamentals** for durable execution, language-agnostic: the workflow/activity/worker
split, why workflows must be deterministic (history replay), signals/queries/updates, child
workflows, saga, continue-as-new, retry/timeout/cancellation, safe versioning of running workflows,
testing, and the `temporal` CLI dev loop.

This is the conceptual layer *underneath* a Temporal codebase. It is **complementary** to this kit's
`temporal-config-driven` skill, which encodes a specific config-driven worker-map / DAG-as-data
architecture and assumes these fundamentals. See each skill's `description` for the auto-trigger
boundary.

## Source provenance

Re-derived **concisely, in claude-kit's own idiom** from the official, MIT-licensed
[`temporalio/skill-temporal-developer`](https://github.com/temporalio/skill-temporal-developer)
(© Temporal Technologies Inc., MIT License). **Nothing is vendored** — the upstream reference files
were read for grounding and the concepts paraphrased into compact notes, with cross-checks against
the public Temporal docs (https://docs.temporal.io).

The upstream skill is the **authority** and carries the full per-language depth (Python, TypeScript,
Go, Java, .NET, Ruby, Rust) plus integrations and ops material. These notes deliberately stay lean
and point back to it; when the two disagree, trust upstream.

## How to apply

1. **Read `SKILL.md`** for the durable-execution model and the workflow/activity/worker rules — the
   ideas every Temporal codebase depends on.
2. **Hit a non-determinism / command-mismatch error?** Go straight to
   [`references/determinism.md`](references/determinism.md).
3. **Changing a workflow with in-flight executions?** Use
   [`references/versioning.md`](references/versioning.md) before you touch the Command sequence.
4. **Writing tests?** Use [`references/testing.md`](references/testing.md) (time-skipping env, replay
   tests, activity mocking).
5. **Need the full per-language API?** Use [`references/languages.md`](references/languages.md) for
   compact starters, then follow the upstream link for your SDK.
6. **For this kit's config-driven worker maps / DAG interpreter / cron schedules**, use the sibling
   `temporal-config-driven` skill instead.
