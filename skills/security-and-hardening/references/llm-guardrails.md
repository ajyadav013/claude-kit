# LLM / AI Feature Guardrails — input/output screening, tool least-privilege, LLM Top 10 map

Deep-dive reference for the `security-and-hardening` skill's *LLM / AI Feature Security* section.
Loaded on demand from SKILL.md — the guard architecture, opt-in/bypass protocol, and the
"Security implications of bypassing" table live there.

## Input guardrails (before the prompt reaches the model)

- **Prompt-injection / jailbreak screening** — treat retrieved docs, tool results, and user text as
  data, never instructions; screen for "ignore previous instructions" / embedded commands before
  sending. (Pairs with `agent-guardrails.md` §1.)
- **Secrets scan** — never forward API keys, credentials, or internal tokens into a prompt.
- **PII anonymisation (vault pattern)** — mask PII (names, emails, cards) *before* the model sees it
  and restore it on the way out via the same vault, so the provider never receives raw PII.
- **Token / length budget** — cap input size to bound cost and prevent model-DoS.
- **Topic / content limits** — block disallowed topics or substrings where policy requires.
- **Canonicalise** — strip zero-width / invisible / homoglyph unicode used to smuggle instructions.

## Output guardrails (before the app uses the response)

- **Treat output as UNTRUSTED.** Never `eval`/`exec` it, render it as raw HTML, build SQL/shell from
  it, or auto-execute the tool/function calls it requests **without validation**. This is the existing
  no-eval-of-untrusted-data rule (OWASP A08) applied to model output — it stays a **Critical** at the
  security gate.
- **Leak scan** — check the response for leaked secrets/PII (de-anonymise via the vault).
- **URL / SSRF check** — validate any URL the model emits against an allowlist before fetching or
  showing it; block internal/private ranges.
- **Structured-output validation** — when you expect JSON/a schema, validate it; reject or repair on
  mismatch rather than trusting the shape.
- **Use-case checks** — relevance, refusal, toxicity/bias as your product requires.

## Least privilege for model-invoked tools

If the model can call tools/functions, give it the **minimum** set, require confirmation for
destructive/outward-facing actions, and scope credentials narrowly (mirrors `agent-guardrails.md` §3).

## OWASP LLM Top 10 — quick map

| Risk | Guardrail above |
|------|-----------------|
| LLM01 Prompt injection | input: injection screening; treat retrieved/tool content as data |
| LLM02 Insecure output handling | output: never eval / render-raw / auto-run unvalidated output |
| LLM04 Model DoS | input: token/length budget + rate limits |
| LLM06 Sensitive info disclosure | input PII vault + output leak scan; don't send secrets |
| LLM08 Excessive agency | least-privilege tools + human confirm for destructive actions |
