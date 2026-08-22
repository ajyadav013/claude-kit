---
source: https://netflixtechblog.com/rapid-event-notification-system-at-netflix-6deb1d2b57d1
author: Netflix TechBlog
license-note: ideas absorbed in own words; no text or code reproduced
---

# Server-initiated device notifications at 150k events/sec: Netflix's RENO

## What it teaches

Netflix needed backend systems to push state changes (continue-watching updates,
recommendation refreshes, plan changes, profile edits, diagnostic signals) out
to 220M+ members' devices quickly enough that the experience stays consistent
across phones, TVs, and browsers. The resulting service, RENO, is a case study
in designing a high-RPS fan-out system around heterogeneous device
connectivity: one event source feeding priority-sharded queues and processing
clusters, a hybrid push-plus-pull delivery model, and a set of load-shedding
and isolation techniques that keep a thundering herd from taking down either
RENO or its downstreams.

## Key patterns & decisions

- **Single event source via an indirection layer**: rather than integrating
  with every producing microservice, RENO listens to one internal event
  management framework (Manhattan) that funnels all triggering events, making
  new use cases a configuration exercise ("plug-and-play") instead of a new
  integration.
- **Priority-sharded queues and clusters**: each use case gets a priority;
  events route to priority-specific queues (SQS) consumed by matching
  processing clusters, so scaling policies and tuning are independent per
  priority tier — a member-visible profile change never queues behind a
  diagnostic ping.
- **Hybrid push AND pull delivery**: pure pull makes mobile apps chatty and
  trips OS background-activity limits; pure push loses smart TVs that are
  powered off most of the day. So the server pushes immediately to everything
  reachable, while devices also call home at lifecycle checkpoints — which
  additionally covers legacy devices that support only one of the two models.
- **Persistent notification store for self-paced pull**: every emitted
  notification is written per-device to Cassandra so a device that was offline
  can poll for its messages at its own cadence.
- **Staleness filter as a gating check**: time-sensitive events older than a
  configurable age are dropped early, protecting queues from floods of
  backed-up upstream events that no longer have value to a device.
- **Online-device gating**: delivery attempts consult a registry of currently
  connected devices (maintained by their edge gateway) so outbound traffic is
  spent only on reachable targets.
- **Asymmetric autoscaling**: scale-up policies are deliberately more
  aggressive than scale-down, so compute catches up fast when queues grow
  during spikes.
- **Event deduplication under high RPS**: duplicates are merged when doing so
  loses no device-relevant context — partly forced by mobile OS restrictions
  on background app activity.
- **Bulkheaded per-platform delivery**: pushes to APNS, FCM, and their
  homegrown persistent-connection push (Zuul Push) run in parallel and
  best-effort per platform, so one failing downstream provider cannot block
  notifications to other device families.
- **Edge-of-service observability**: beyond CPU/memory alerts they add
  metrics/logging specifically at the upstream and downstream boundaries,
  trend analysis for slow degradations, real-time per-device stream tracing
  (Mantis), and per-platform alerting to localize root causes faster.

## When to apply / trade-offs

The design applies to any server-initiated notification/fan-out layer serving
clients with mixed connectivity: segment work by priority so tuning is
per-tier; combine push (latency) with pull (reliability for intermittently
connected clients); and treat staleness filtering, dedup, online-only
targeting, and per-downstream bulkheads as the standard toolkit for surviving
burst load. Trade-offs: delivery is best-effort — guaranteed delivery and
message batching are explicitly listed as future work, so consumers must
tolerate missed pushes (mitigated by pull plus the Cassandra store); the hybrid
model doubles the delivery machinery to maintain; and dedup/merging is safe
only when context loss can be ruled out.

## Fidelity check

1. Claim: RENO handles roughly 150k events/second at peak. Support: the
   high-RPS section states peak service load of about 150,000 events per
   second and frames the thundering-herd mitigations around it.
2. Claim: the hybrid model exists because device connectivity is bimodal.
   Support: the article contrasts nearly-always-connected mobile devices with
   smart TVs that are online only while in use, and cites OS-imposed
   per-app communication limits as the reason pure pull fails on mobile.
3. Claim: per-platform delivery is isolated so one provider outage doesn't
   cascade. Support: the bulkhead section describes parallelized, best-effort
   delivery across APNS, FCM, and their own push channel, with failures on one
   platform not blocking the others.
4. Claim: offline devices can still catch up. Support: the architecture lists
   a Cassandra-backed persistent store holding every emitted notification per
   device precisely so devices can poll on their own schedule.
