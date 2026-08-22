---
source: https://stripe.com/blog/how-we-built-it-stripe-radar
author: Stripe
license-note: ideas absorbed in own words; no text or code reproduced
---

# Stripe Radar: seven years of lessons building a sub-100ms fraud scorer

## What it teaches

A Payment Intelligence engineer walks through the three biggest lessons from
building Stripe's fraud-detection system, which must score a transaction in
the instant between clicking "buy" and confirmation. The constraints are
brutal: over a thousand signals evaluated per transaction, a decision in
under 100 milliseconds, a base rate of fraud around one in a thousand
payments, and a false-block rate they hold to roughly 0.1% of legitimate
volume — because a wrongly blocked good payment damages both the merchant
and the customer. The article's real subject is not fraud per se but how to
keep an ML system improvable over many years: revisit the architecture,
keep hunting for signals, and invest as much in explaining decisions as in
making them.

## Key patterns & decisions

- Latency-budgeted inference in the critical path: the entire fraud
  decision (1,000+ signals) fits inside a ~100ms window at checkout time.
- Periodically re-litigate the model architecture: the team climbed from
  logistic regression to a hybrid ensemble to a pure deep network, and each
  jump delivered a step-change in quality — the guiding question being
  "what would we build if we started today?"
- Replace ensemble memorization with a multi-branch deep network: dropping
  the gradient-boosted-trees half of a wide-and-deep ensemble naively would
  have cost about 1.5% recall, so they adopted a ResNeXt-inspired design
  that splits computation into parallel small-network branches and sums
  them, recovering memorization without sacrificing generalization or
  parallelizability.
- Training time as a first-order engineering metric: the tree component
  throttled retraining and experimentation; going DNN-only cut training
  time by more than 85% (to under two hours), converting overnight
  experiments into several iterations per working day.
- Adversary-informed feature engineering: detailed forensic reviews of past
  attacks, weekly dark-web trend meetings, and network-wide correlation
  searches feed a prioritized backlog of candidate features that get
  prototyped and measured quickly.
- Validate features empirically, expect redundancy: a hand-crafted
  "merchant currently under distributed attack" flag added little because
  the accumulated model already captured the pattern implicitly.
- Data scaling as a lever: with training fast again, a 10x increase in
  training transactions still produced significant gains (with 100x being
  explored) — LLM-style scaling behavior applied to fraud detection.
- Explainability as a product surface, not an afterthought: risk-insight
  views show which transaction attributes drove a decline, maps and
  related-transaction search add context, and internal tooling ranks the
  features that pushed a score up or down — a deliberate compensation for
  choosing opaque deep networks over interpretable models.

## When to apply / trade-offs

- The architecture-migration lesson applies whenever an ensemble component
  blocks modern techniques (transfer learning, embeddings, parallel
  training): quantify what the legacy component uniquely contributes (here,
  1.5% recall) and only remove it once an equivalent capacity exists in the
  replacement.
- Deeper/wider networks improve representational capacity but overfit past
  a point; the branch-aggregation approach is presented as a better lever
  than brute-force depth/width.
- Choosing DNNs trades away interpretability; the article argues you must
  pay that debt back with explanation tooling for users and for your own
  on-call debugging.
- The experimentation-velocity argument generalizes: optimizing training
  wall-clock is worth it chiefly because it compounds through faster idea
  turnover, not because of compute cost.

## Fidelity check

1. Claim: Radar scores 1,000+ characteristics per transaction in under
   100ms with a ~0.1% false-block rate. Support: the capture states Radar
   assesses more than 1,000 characteristics, decides in less than 100
   milliseconds, and incorrectly blocks just 0.1% of billions of legitimate
   payments.
2. Claim: dropping the XGBoost side naively would have cost ~1.5% recall,
   so they adopted a ResNeXt-inspired multi-branch DNN. Support: the
   capture says removing the XGBoost component alone meant an unacceptable
   1.5% recall drop, and describes adopting a multi-branch architecture
   inspired by ResNeXt whose branch outputs are summed.
3. Claim: the DNN-only migration cut training time by over 85% to under two
   hours, transforming experiment cadence. Support: the capture states
   training time fell by over 85% to less than two hours, letting jobs that
   once ran overnight complete several times in one working day.
