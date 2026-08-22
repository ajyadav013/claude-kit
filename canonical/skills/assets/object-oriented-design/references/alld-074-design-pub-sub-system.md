---
source: https://github.com/ashishps1/awesome-low-level-design/blob/main/problems/pub-sub-system.md
author: ashishps1
license-note: ideas absorbed in own words; no text or code reproduced
---

# In-process publish–subscribe broker design

## What it teaches

How to build the observer pattern at system scale inside one process: topics
as named registries of subscribers, publishers that know only a topic name,
and asynchronous fan-out so a slow subscriber cannot stall a publisher. It
is the miniature of every message broker — the same decoupling story as
Kafka or SNS, reduced to a topic map plus a thread pool.

## Key patterns & decisions

- **Topic as the decoupling point.** Publishers and subscribers never
  reference each other; both reference a topic. The topic keeps the set of
  current subscribers and pushes each published message to all of them.
- **Subscriber as a single-callback interface.** Consumers implement one
  message-received hook, which makes any object a subscriber and keeps the
  broker ignorant of what consumers do; a console-printing implementation
  serves as the demo consumer.
- **Broker facade owning the topic registry.** A central system class maps
  topic names to topic objects in a concurrent map, handling topic
  creation, subscription changes, and publish requests behind one API.
- **Fan-out through an executor, not the publisher's thread.** Message
  delivery is dispatched onto a thread pool, so publishing is fire-and-
  forget and subscriber latency is isolated from publisher throughput.
- **Push-based, at-most-once, no persistence.** Messages exist only as
  objects in flight — there is no log, replay, or acknowledgment. Delivery
  is real-time to whoever is subscribed at publish time.
- **Concurrent collections for membership churn.** Subscriber sets and the
  topic map tolerate simultaneous subscribes, unsubscribes, and publishes
  without a global lock.

## When to apply / trade-offs

- Use this shape for in-process eventing: domain events, plugin/hook
  systems, UI event buses, decoupling modules so new consumers can be added
  without touching producers. It is the correct first step before reaching
  for an external broker.
- The executor-based fan-out buys publisher isolation but gives up
  ordering guarantees per subscriber and makes failure invisible — a
  production variant needs per-subscriber queues, retry/dead-letter
  handling, or at least error callbacks.
- No persistence means subscribers that connect late or crash miss
  messages; if consumers need catch-up or exactly-once, this design is a
  non-starter and a durable log (or an outbox in front of one) is the right
  tool.
- Unbounded thread-pool fan-out can amplify load under bursty publishing;
  bounded queues plus backpressure are the standard hardening.

## Fidelity check

1. *Claim:* topics hold the subscriber sets and perform delivery.
   *Support:* the capture describes the topic class as maintaining its
   subscribers, with operations to add/remove them and to publish a
   message to all of them.
2. *Claim:* delivery is made asynchronous via a thread pool. *Support:*
   the capture says the main system class uses an executor service to
   handle concurrent message publishing.
3. *Claim:* consumers plug in through a one-method contract. *Support:*
   the capture defines a subscriber interface with a single
   message-received callback and a concrete implementation that prints
   incoming messages.
