---
source: https://algomaster.io/learn/lld/yagni
author: ashishps1 (AlgoMaster)
license-note: ideas absorbed in own words; no text or code reproduced
---

# YAGNI: build for the requirement in front of you, not the one you imagine

## What it teaches

The chapter is a working treatment of "You Aren't Gonna Need It," the Extreme
Programming discipline of refusing to implement functionality until a concrete
requirement demands it. Its core argument: when a future need is only guessed
at, deferring the work is strictly better, because by the time the need
materializes you will understand it far more precisely and can build the right
thing instead of a speculative approximation. The principle is explicitly
distinguished from sloppiness — clean, well-structured code for today's scope
is fine; what YAGNI forbids is speculative layers, interfaces, and knobs with
no present consumer.

The teaching vehicle is a profile-picture uploader whose real scope is three
operations (accept an image, resize to a fixed dimension, persist locally).
The author walks through how "what if" reasoning — future video support, a
possible cloud-storage migration, hypothetical third-party plugins — balloons
that into roughly half a dozen classes and interfaces, several of which end up
as hollow shells: a cloud adapter with unimplemented bodies, a factory that
dispatches to exactly one handler, an interface exposing operations no caller
invokes. The lean alternative satisfies the actual requirement completely,
stays trivially testable, and leaves the door open for a real refactor when
(if) the new requirement arrives.

## Key patterns & decisions

- **Defer until a real requirement exists** — implement when the need is
  actual, never merely foreseen; later you will have better information about
  the correct shape of the feature.
- **Speculative code carries four compounding costs** — the chapter enumerates
  them: wasted build/review/test effort, added complexity that intimidates
  future readers, delayed delivery of the features users actually asked for,
  and ongoing maintenance drag (dead code still breaks during dependency
  upgrades and blocks refactors).
- **Accidental permanence of speculation** — newcomers assume elaborate
  machinery exists for a reason and are afraid to delete it, so unused
  abstractions fossilize into the codebase.
- **Empty-shell smell test** — factories managing a single implementation,
  adapters with stub bodies, and interface methods nothing calls are direct
  evidence of a YAGNI violation.
- **Known-constraint exception** — up-front investment is legitimate when the
  need is concrete rather than imagined: legally mandated security/compliance
  controls (audit trails, encryption for regulated data), contractual SLAs or
  cross-region availability that are prohibitively expensive to retrofit, and
  public library APIs where breaking changes hurt many consumers (though even
  libraries should start with a minimal surface and grow from observed usage).
- **"What if" vs. "we know"** — the litmus test separating forbidden
  speculation from justified planning is whether the driver is imagination or
  a documented requirement/regulation/contract.

## When to apply / trade-offs

Apply as the default posture on application code: any time you catch yourself
justifying a layer with a hypothetical future ("might switch providers",
"other teams could plug in"), stop and build the direct version. Bend the rule
only when the future constraint is already known and concrete — compliance
regimes, hard SLA/architecture commitments, and shared library API design —
because retrofitting those is genuinely more expensive than building them in.
The trade-off the chapter emphasizes: deferral is not free-form laziness; you
still write clean code that can be refactored, so that extension at
need-time is a controlled change rather than a rewrite.

## Fidelity check

1. Claim: YAGNI originates in Extreme Programming and is tied to a Ron
   Jeffries maxim. Support: the capture attributes the "implement when you
   actually need, never when you foresee" formulation to Jeffries as an XP
   co-founder and explains XP's premise that requirements shift constantly,
   making predicted-future work wasteful.
2. Claim: the worked example contrasts a three-step uploader with a
   ~six-class speculative design containing dead members. Support: the capture
   describes the requirement as accept/resize/store and the violation as six
   classes and interfaces including a cloud adapter with empty bodies, a
   factory over one handler, and unused retrieve/delete interface methods.
3. Claim: the chapter names three exception categories where up-front work is
   justified. Support: it lists security/compliance obligations, architectures
   with known long-term constraints (SLAs, cross-region replication), and
   reusable libraries/frameworks, unified by the need being known rather than
   guessed.
