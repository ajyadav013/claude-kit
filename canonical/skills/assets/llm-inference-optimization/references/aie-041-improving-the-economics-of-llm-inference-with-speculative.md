---
source: https://www.redhat.com/en/blog/solving-economics-llm-inference-speculative-decoding
author: Megan Flynn, Rob Greenberg, Alexandre Marques, Dipika Sikka (Red Hat)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Speculative decoding is lossless on quality but conditional on economics

## What it teaches
Serving a large model is a recurring cost paid on every request, and generation
is autoregressive and memory-bandwidth-bound, so latency tracks sequence length.
Speculative decoding attacks this by splitting generation into two roles: a small
fast draft model (the "speculator") proposes candidate tokens ahead of time, and
the large model (the "verifier") checks them in far less time than generating
them itself — several tokens for roughly the cost of one verifier pass. The key
property is that verification is exact, not approximate: with the full-size model
as verifier the output matches what that model would have emitted alone, so this
is a latency/cost lever that does not trade away quality. But the payoff is not
unconditional. It is governed by two quantities — what drafting plus verification
costs, and how often drafted tokens are accepted. When acceptance is low and the
server is saturated with concurrent requests, the drafting overhead is wasted and
throughput can actually regress. The decision is therefore an empirical,
per-workload measurement, not a global "turn it on" setting.

## Key patterns & decisions
- **Two roles, one distribution** — the speculator proposes, the verifier accepts
  or rejects. Because rejection falls back to the verifier's own token, the
  generation distribution is unaltered; the article frames the speedup as
  near-lossless and quality-identical rather than a quality/speed trade.
- **Acceptance length is the governing metric** — the useful number is the mean
  number of drafted tokens accepted per verifier pass. Higher acceptance means a
  larger expected speedup; the article's guidance is to inspect per-token
  acceptance rates to quantify the benefit for a specific use case before
  committing.
- **Task predictability decides the win, not model size** — on a coding
  benchmark (HumanEval) a DFlash speculator for Gemma 4 31B reached mean
  acceptance length 4.91 and delivered roughly 4x lower inter-token latency
  consistently across request rates. On summarization, acceptance length was 2.53
  and the speedup shrank as request rate rose. Coding is highly predictable;
  creative writing is not.
- **It can be a pessimization under load** — whether the bottleneck is compute or
  memory movement depends on context length and concurrency. Many in-flight
  requests plus a short acceptance length means the draft work is pure overhead
  and the server can slow down. High acceptance plus moderate request rate is
  where the large gains sit.
- **Distribution match drives acceptance** — a speculator behaves best on data
  resembling what it was trained on, including chat-template shape. A speculator
  trained essentially on English is expected to do poorly on other languages
  without fine-tuning, which makes fine-tuning (or training a speculator from
  scratch) a real deployment step, not an optional extra.
- **Long context is a known weak spot** — context length is called out as a
  factor affecting acceptance, with improvement work described as still in
  progress. Treat long-context workloads as needing their own measurement.
- **Composable with quantization** — speculators can run against a verifier that
  has itself been quantized (via llm-compressor), stacking two independent
  inference-cost levers for what is described as a nearly lossless combined
  speedup.
- **Productization is the actual gap being closed** — Speculators is an Apache
  2.0 open source library packaging algorithm definitions, draft-model training
  (dense and MoE), offline data generation, and a HuggingFace-compatible
  serialization format that deploys into vLLM. Pre-trained speculators are
  published for common families (Llama 3.1/3.3, the Qwen3 family up to 235B,
  gpt-oss 20B/120B, gemma 4 31B/26B), trained end-to-end with the Eagle 3
  algorithm.
- **Framing: the era shift** — the argument is that the field has moved from
  making models capable to making capable models practical, so inference
  optimization is now a first-class deployment concern rather than a research
  curiosity.

## When to apply / trade-offs
Reach for speculative decoding when you are self-hosting a large model behind an
interactive or latency-sensitive surface and the alternative on the table is
downgrading to a smaller, weaker model. It is the rare optimization that does not
cost quality, which makes it strictly preferable to model downgrade when it
works. The costs are real though: you need a speculator that matches your
workload's distribution (possibly fine-tuned or trained), you need benchmarking
infrastructure to measure per-token acceptance at your actual concurrency, and
you carry an extra model in your serving stack. Do not apply it blind to
high-concurrency, low-predictability traffic — creative generation or heavily
multilingual traffic served by an English-trained speculator on a saturated
server is the documented case where it makes things worse. It is also irrelevant
if you consume a hosted model API, since the provider owns the decoding path.
Measure acceptance length first; if it is near 2 and your request rate is high,
the answer is no.

## Fidelity check
1. Claim: speculative decoding can slow a server down rather than speed it up.
   Support: the capture states that if a server is handling many requests and the
   acceptance length is low, speculators can potentially slow down the server, and
   that drafting cost is not justified when tokens are unlikely to be accepted.
2. Claim: the Gemma 4 31B case study shows acceptance length 4.91 on coding versus
   2.53 on summarization, with roughly 4x inter-token-latency reduction on coding.
   Support: the capture reports mean DFlash acceptance lengths of 4.91 and 2.53
   and describes a 4x ITL reduction that holds fairly consistently across request
   rates for the coding dataset, with summarization speedup dependent on request
   rate.
3. Claim: output quality is preserved exactly when the full-size model is the
   verifier. Support: the capture states that with the full-sized large model as
   verifier the speedup comes at no cost and the output is guaranteed to be the
   same as the large model by itself, and separately that verification is not an
   approximation.
