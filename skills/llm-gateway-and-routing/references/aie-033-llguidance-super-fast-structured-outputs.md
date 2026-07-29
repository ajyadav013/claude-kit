---
source: https://github.com/guidance-ai/llguidance
author: guidance-ai (Microsoft)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Enforce schema during sampling, not after — if the token mask stays cheap

## What it teaches
Structured output has two possible enforcement points: after the model has
spoken (parse, validate, retry) or during sampling (compute, at every
decoding step, the set of tokens that can still lead to a string in the
target language, and zero out the rest of the logits). llguidance is an
implementation of the second. It takes a grammar — a JSON Schema subset, a
regular expression, or a Lark-flavoured context-free grammar — plus a
tokenizer and the tokens emitted so far, and returns a token mask. The
engineering claim is that this can be made cheap: roughly 50µs of
single-core CPU per token on a 128k-vocabulary tokenizer, with no
meaningful startup cost. That number is what makes the approach deployable,
because a constrained decoder that costs more than a forward pass silently
converts a correctness feature into a throughput regression. The README
also lays out why competing designs land at different points on the
startup-cost / steady-state-cost curve, which is the actual decision an
inference-platform team has to make.

## Key patterns & decisions
- **Constrain at sample time, not at validation time** — the mask is
  applied to the logits, so an out-of-grammar token is never emitted. This
  removes the retry loop entirely for syntactic validity, though it says
  nothing about semantic correctness of the values inside the schema.
- **Earley parser over a regex-derivative lexer** — the design pairs a
  context-free grammar parser (Earley's algorithm) with a lexer built on
  derivatives of regular expressions, rather than a character-level
  backtracking parser. The README attributes llama.cpp's slowness
  specifically to having no lexer plus a backtracking parser.
- **Lazy automata beat precomputed ones for arbitrary schemas** — Outlines
  precomputes masks for every automaton state, which makes steady-state
  sampling fast but caps constraint complexity and pays startup cost and
  memory. llguidance builds lexer automata lazily; the CFG supplies the
  top-level structure so the automata stay small.
- **Precomputation is a bimodal risk** — XGrammar precomputes some masks;
  when the precomputation fits the input, masks land under 8µs (in half the
  cases tested), but when it does not, mask time can reach tens or hundreds
  of milliseconds. A p50 win with a three-orders-of-magnitude tail is a bad
  trade for a shared serving tier.
- **Optimise the common case, then measure the tail** — a full mask for a
  typical JSON schema costs about 1.5ms; a "slicer" optimisation pulls the
  benchmark average under 50µs, with under 1% of masks above 1ms and
  0.001% above 10ms (still bounded under 30ms). Report the distribution,
  not the mean.
- **Budget constrained decoding against the forward pass** — the stated
  arithmetic: 16 cores against a 10ms forward pass supports batch sizes to
  ~3200 before the constraint engine becomes the limiter. That is the
  sizing calculation to run before enabling grammar mode in production.
- **Grammar as a decode accelerator, not only a restriction** — when the
  grammar admits exactly one continuation, those "fast-forward" tokens can
  be emitted without invoking the model, so constraining can be net
  cheaper than unconstrained decoding on rigid schemas.
- **Same engine, many hosts** — the library is Rust with C and Python
  bindings and has been integrated into vLLM, SGLang, llama.cpp,
  mistral.rs, onnxruntime-genai, TensorRT-LLM via LLGTRT, Chromium's
  `window.ai`, and OpenAI's JSON-Schema structured outputs. Portability of
  the grammar layer across serving stacks is a real property, not marketing.
- **Describing JSON Schema support as a large subset is the honest
  framing** — support is explicitly a subset, so a schema that validates in
  your application's validator may not be expressible as a decoding
  constraint. Test the actual schemas you ship.

## When to apply / trade-offs
Reach for grammar-constrained decoding when a downstream system parses the
model's output mechanically — tool-call arguments, config generation, data
extraction into a typed record — and a malformed response costs a retry or
a page. It is most valuable with smaller or weaker models, which fail
syntactic conformance far more often than frontier models do. The costs
are real: you take a CPU dependency on every decode step and a new failure
mode where an unsupported schema construct is silently narrowed or
rejected at grammar-compile time; you also constrain only *shape*, so a
perfectly-formed object with hallucinated field values still passes. Do not
use it as a substitute for validating and authorising the parsed result —
prompt-injection and bad-value risks are untouched by a token mask. And do
not assume all engines behave alike: if you are choosing a backend, the
question is not raw speed but the tail latency and startup cost measured on
your own schemas, because the designs differ most at exactly those two
points.

## Fidelity check
1. Claim: mask computation is around 50µs of single-core CPU time for a
   128k tokenizer with negligible startup cost. Support: the capture states
   this figure twice — in the About section and again under Technical
   details.
2. Claim: the parser is Earley's algorithm layered on a lexer built from
   derivatives of regular expressions, and masks are computed by walking a
   token prefix tree. Support: the Technical details section states exactly
   this construction and links a toktrie document.
3. Claim: full mask for a typical JSON schema is ~1.5ms, a slicer
   optimisation brings the benchmark average under 50µs, with <1% over 1ms
   and 0.001% over 10ms. Support: the capture reports these percentiles
   against JSON Schema Bench (2.5M tokens, 10k schemas).
