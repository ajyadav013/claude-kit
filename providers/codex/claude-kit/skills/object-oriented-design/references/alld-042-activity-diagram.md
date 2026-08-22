---
source: https://algomaster.io/learn/lld/activity-diagram
author: AlgoMaster.io
license-note: ideas absorbed in own words; no text or code reproduced
---

# Activity diagrams: workflow maps with decisions, forks, loops, and swimlanes

## What it teaches
How to model an end-to-end process as a flowchart-with-superpowers: ordered
actions, guarded branches, genuinely parallel paths, retry loops, and — via
swimlanes — an explicit assignment of every step to a responsible actor or
component. Where a sequence diagram is about messages between objects, an
activity diagram is about the flow of work through a process. The chapter
catalogs the node vocabulary, the four control-flow patterns built from it, a
six-step authoring recipe, and a full ATM-withdrawal example that uses every
pattern at once.

## Key patterns & decisions
- Small closed node vocabulary: one initial node (filled circle) starts the
  flow; action nodes (rounded rectangles) are single verb-noun steps; a final
  node (bullseye) kills the whole activity including still-running parallel
  branches; a flow-final node (circled X) kills only its own branch.
- Final vs flow-final distinction: an error branch that just logs and stops
  should end in a flow-final so the rest of the process keeps running;
  reaching any true final node terminates everything — choosing the wrong one
  changes program semantics.
- Decision/merge pairing: a diamond with mutually exclusive guard conditions
  splits the flow (every outgoing edge must be labeled); its mirror-image
  merge diamond funnels whichever single branch was taken back into one flow
  without waiting, preventing an ever-widening fan of unreconverged paths.
- Fork/join pairing for real concurrency: a thick bar splits one flow into
  branches that all execute; the matching join bar blocks until every branch
  completes. The chapter's rule of thumb: an unmatched fork is usually a
  design bug.
- Parallel vs conditional is the exam question: after a decision exactly one
  branch runs; after a fork all branches run — and the parallel pattern is a
  latency lever (three 2-second independent steps cost the max, not the sum,
  when forked).
- Loop as a routed-back edge: retry logic (PIN entry with an attempt counter,
  API retries) is modeled by a decision node whose failure edge points back
  to an earlier action, with a second guard providing the loop exit (lock the
  account after exhausted attempts).
- Action naming discipline: verb-first, one coherent step per node; a node
  name that contains "and" should be split, and state-like names ("check
  done") are rejected in favor of action names ("reserve inventory").
- Swimlanes assign responsibility: partitioning the diagram one lane per
  actor/system makes every lane-crossing arrow a visible handoff, exposes
  workload imbalance between lanes, and often maps lanes directly onto
  services or teams in the implementation.
- Six-step authoring recipe: name the specific process, brain-dump the
  actions, order them, add decisions where conditions branch, extract
  independent steps into fork/join pairs, and add swimlanes only when
  multiple parties are involved.

## When to apply / trade-offs
- Reach for an activity diagram when the complexity is process-shaped
  (approvals, fulfillment, onboarding, retries) rather than object-shaped;
  it doubles as a stakeholder-readable bridge between prose requirements and
  code structure.
- Drawing the workflow surfaces hidden parallelism (a confirmation email
  need not wait for an inventory update) and convergence bottlenecks that a
  verbal description hides.
- Swimlanes are optional overhead for single-actor flows but essential once
  handoffs exist — each lane boundary is an integration point worth testing.
- The notation's discipline (guards on every decision edge, a join for every
  fork) is what keeps diagrams unambiguous; skipping it produces pretty
  pictures that different readers execute differently.

## Fidelity check
1. Claim: a true final node terminates even still-running parallel branches,
   while flow-final ends only its own path. Support: the capture states that
   reaching any final node stops the entire activity including live parallel
   branches, and separately shows an error-logging branch ending in a
   flow-final while the main activity continues.
2. Claim: forked parallel steps cost the slowest branch rather than the sum.
   Support: the capture's order example runs email, inventory, and payment
   concurrently and works the arithmetic — three sequential 2-second steps
   take 6 seconds versus 2 seconds when forked.
3. Claim: the ATM example encodes a bounded retry loop. Support: the capture
   walks a PIN-entry section where a wrong PIN routes to an attempt-count
   check that either loops back to the prompt or, after three failures,
   retains the card and locks the account.
