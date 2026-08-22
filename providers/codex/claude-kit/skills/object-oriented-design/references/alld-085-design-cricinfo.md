---
source: https://github.com/ashishps1/awesome-low-level-design/blob/main/problems/cricinfo.md
author: ashishps1 for in-repo problems
license-note: ideas absorbed in own words; no text or code reproduced
---

# Live sports data: deep composition hierarchies and split read/update services

## What it teaches
A cricket information system is mostly a read-heavy publishing problem with one
sharp modeling challenge: representing the game itself. The design answers it with
a strict containment hierarchy that mirrors the sport's structure — a match holds
a scorecard, a scorecard holds innings, an innings holds overs, an over holds
individual deliveries, and each delivery records who bowled, who faced it, and what
happened. This composition-all-the-way-down shape means a live update is an append
at the leaf (a new delivery) that automatically enriches every aggregate above it,
which is exactly what live commentary and statistics need. The second lesson is
service partitioning: match metadata (scheduling, status, teams, venue) is managed
by one service while scorecard mutation lives in another, with a thin system-level
entry point composing the two. That split acknowledges that fixture data and
ball-by-ball data have different write rates, different consumers, and different
consistency needs, even inside a single process.

## Key patterns & decisions
- Deep composite hierarchy for the domain: match → scorecard → innings → over →
  ball, each level a plain entity aggregating the next.
- Ball/delivery as the atomic event record (bowler, batter, outcome) — the leaf
  grain from which all higher-level statistics are derivable.
- Match lifecycle as a status enum (scheduled, live, completed, abandoned)
  separate from the score data itself.
- Two singleton services with distinct responsibilities: one for match CRUD and
  lookup, one for scorecard creation and incremental update.
- A top-level system class as a thin composition root over both services,
  exposing the high-level operations users need.
- Teams and players as shared reference entities (a team aggregates players,
  each player carries a role) referenced by matches rather than owned by them.
- Requirements explicitly demand real-time update flow, concurrent-read safety,
  search across matches/teams/players, and headroom for future features —
  pushing the design toward stateless reads over the shared hierarchy.

## When to apply / trade-offs
This hierarchy pattern fits any domain whose events nest naturally (sports
fixtures, legislative sessions, tournament brackets, multi-leg logistics). Its
strength — aggregates derived from leaf events — is also its cost: with mutable
in-place score totals you must keep aggregates and leaves consistent under
concurrent readers, which at scale argues for treating deliveries as an
append-only event log and computing scorecards as projections. The two-service
split is a good seed for that evolution. The weak spot in the interview-scale
design is search and fan-out: a singleton in-memory service serving "large
volumes of user requests" hand-waves the caching/replication layer a real
CricInfo would need; treat the model as the write-side schema only.

## Fidelity check
- Claim: the game is modeled as a five-level containment chain ending in single
  deliveries. Support: the capture lists match holding a scorecard, scorecard
  holding innings, innings holding overs, overs holding balls, with each ball
  recording bowler, batsman, and result.
- Claim: match management and scorecard management are deliberately separate
  services. Support: the capture describes one service for adding/retrieving/
  updating matches and a second one for creating and updating scorecards, both
  singletons, combined by a top-level system class.
- Claim: match progress is tracked with a dedicated status enum. Support: the
  capture lists a match-status enum covering scheduled, in-progress, completed,
  and abandoned states.
