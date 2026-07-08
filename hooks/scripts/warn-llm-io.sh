#!/usr/bin/env bash
# PreToolUse(Edit|Write): advisory (never blocks) -- when an edited file appears to call an LLM
# provider SDK or build prompts, surface the LLM-feature security guardrails and the risk of skipping
# them. The LLM-security layer is OPT-IN and BYPASSABLE: this hook *informs*, it does not gate
# (always exits 0). Degrades to a no-op without jq or a recognisable payload.
# The guidance returns as hookSpecificOutput.additionalContext JSON on stdout (Claude reads it next
# to the tool result; PreToolUse support since CC 2.1.9) -- exit-0 stderr is debug-log-only.
command -v jq >/dev/null 2>&1 || exit 0
[ -t 0 ] && exit 0  # no stdin (run by hand) -> no-op instead of blocking on `cat`
INPUT="$(cat)"
FILE_PATH="$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_response.filePath // empty' 2>/dev/null || true)"
CONTENT="$(echo "$INPUT" | jq -r '.tool_input.content // .tool_input.new_string // empty' 2>/dev/null || true)"

hay="$(printf '%s\n%s' "$FILE_PATH" "$CONTENT" | tr '[:upper:]' '[:lower:]')"
[ -z "$hay" ] && exit 0

# Provider SDKs / inference calls / prompt construction -- illustrative and provider-agnostic.
sig='openai|anthropic|langchain|llama[_-]?index|cohere|mistralai|google\.generativeai|vertexai|bedrock|ollama|huggingface|transformers|litellm|semantic-kernel|chat\.completions|chatcompletion|messages\.create|generatecontent|inferenceclient|system[_ ]?prompt|prompt[_ ]?template|few[_ ]?shot|rag\b|retrieval[_ ]?augmented'

if printf '%s' "$hay" | grep -qE "$sig"; then
  W="WARN: this change looks like an LLM/AI feature ($FILE_PATH). Secure the model boundary.
Guardrails (opt-in) -- see .claude/skills/security-and-hardening/SKILL.md -> 'LLM / AI Feature Security' (OWASP LLM Top 10):
  INPUT  : screen for prompt injection, strip/scan secrets, anonymise PII, cap tokens before the model.
  OUTPUT : treat output as UNTRUSTED -- never eval/render-raw/auto-run tools from it; scan for PII/secret leaks + malicious URLs; validate structured output.
This is ADVISORY and does NOT block. If you bypass it you accept: prompt-injection data exfiltration,
PII leaking to the model provider (privacy/compliance), and insecure-output-handling XSS/SSRF/RCE.
To skip deliberately, record a one-line risk acceptance (what / why / who / review date) in the spec or PR."
  # stdout must be ONLY the JSON object for Claude Code to process it.
  jq -n --arg ctx "$W" '{hookSpecificOutput: {hookEventName: "PreToolUse", additionalContext: $ctx}}'
fi
exit 0
