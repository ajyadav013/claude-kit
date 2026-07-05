#!/usr/bin/env bash
# PreToolUse(Edit|Write): advisory (never blocks) -- when an edited file appears to call an LLM
# provider SDK or build prompts, surface the LLM-feature security guardrails and the risk of skipping
# them. The LLM-security layer is OPT-IN and BYPASSABLE: this hook *informs*, it does not gate
# (always exits 0). Degrades to a no-op without jq or a recognisable payload.
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
  echo "WARN: this change looks like an LLM/AI feature ($FILE_PATH). Secure the model boundary." >&2
  echo "      Guardrails (opt-in) -- see .claude/skills/security-and-hardening/SKILL.md -> 'LLM / AI Feature Security' (OWASP LLM Top 10):" >&2
  echo "        INPUT  : screen for prompt injection, strip/scan secrets, anonymise PII, cap tokens before the model." >&2
  echo "        OUTPUT : treat output as UNTRUSTED -- never eval/render-raw/auto-run tools from it; scan for PII/secret leaks + malicious URLs; validate structured output." >&2
  echo "      This is ADVISORY and does NOT block. If you bypass it you accept: prompt-injection data exfiltration," >&2
  echo "      PII leaking to the model provider (privacy/compliance), and insecure-output-handling XSS/SSRF/RCE." >&2
  echo "      To skip deliberately, record a one-line risk acceptance (what / why / who / review date) in the spec or PR." >&2
fi
exit 0
