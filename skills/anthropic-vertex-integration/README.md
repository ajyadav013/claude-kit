# anthropic-vertex-integration

Production patterns for calling Claude on Vertex AI via the AnthropicVertex SDK.

## What this covers

- **Lazy client initialization** with Application Default Credentials (ADC)
- **Project-ID and region resolution** from env-var fallback chains
- **Async generate helpers** (`generate_text`, `generate_json_text`) with exponential-backoff retry
- **System-prompt composition** from personas and task instructions
- **JSON extraction** helpers for structured output
- **Optional Langfuse tracing** for observability (latency, input/output, errors)
- **LazyClient pattern** for SDK singletons with test-reset hooks
- **Vision and tool-use** support (image input, function calling)

## Origins

This skill derives from production backend services using Claude on Google Cloud Vertex AI. It captures real patterns for:

- Reusing BigQuery project IDs for Vertex AI calls (fallback chains)
- Graceful degradation when tracing is misconfigured
- Async wrappers around the sync Anthropic SDK
- Multi-attempt retry for transient 503/504 errors
- Persona-driven system prompts for reusable role definitions

All examples are genericized for public use—no internal service names, project IDs, or credentials appear in this skill.

## When to use this skill

Ask Claude to use this skill when:

- Integrating Claude via Vertex AI (not the direct Anthropic API)
- Building async LLM helpers for one-shot completions or JSON extraction
- Adding exponential-backoff retry to Claude calls
- Setting up Langfuse observability for Claude completions
- Migrating from API-key-based Anthropic SDK to Vertex AI ADC auth

## Files

- `SKILL.md` — the full skill (conventions, examples, anti-patterns)
- `references/vertex-client-and-auth.md` — client construction, ADC, project/region resolution, LazyClient
- `references/generate-helpers-and-retry.md` — generate_text/generate_json_text, retry loop, vision, tool-use
- `references/repo-evidence.md` — genericized snippets from real production services
