# Digest: Design A Notification System

- **Source:** https://x.com/Harry_The_Nerd/status/2044839667267494292
- **Author:** Harshit Khosla (@Harry_The_Nerd)
- **Category:** HLD (high-level design)
- **Fetched:** 2026-07-23/24 via logged-out browser render
- **License note:** Content (c) the author; this digest is an own-words summary for internal engineering reference — no verbatim text.

## Patterns

### One service per delivery channel
Split delivery into four independent services — push, email, SMS, and in-app — instead of a single monolithic sender. The rationale: each channel has a distinct scaling curve, failure mode, and latency budget, so isolating them means an SMS surge cannot degrade push delivery, and each can be scaled horizontally on its own. Trade-off: more moving parts to deploy and monitor, but independent failure domains.

### Preference-aware notification router (smarter than a gateway)
Place a routing service between the message queue and the channel services that carries real business logic, unlike an API gateway that dispatches purely on URL. The router consults per-user state to decide: suppress a channel the user has disabled, force SMS for security-critical messages (OTPs) even against stated preferences, and redirect to an alternate channel when a primary send fails. Use this when routing decisions depend on user identity and message class rather than endpoint shape.

### Two-store split: preferences vs delivery log
Keep two separate databases with different access patterns. (1) A user-preferences store holding channel opt-ins, subscription topics, and device push tokens — read on the hot path before every send. (2) A notification-log store recording every outbound message (id, user, channel, content, delivery status such as sent/delivered/failed, timestamp) — written after each send by a tracking service. Separating them keeps the read-heavy routing lookup and the append-heavy audit trail from contending.

### Cache the hot preference lookups in Redis
Since the router must resolve preferences for every single notification, front the preferences DB with a Redis cache so routing never takes a cold database hit. This is presented as the main latency lever in the whole design (the queue itself adds a small async delay that most notifications tolerate).

### Message queue as spike buffer (Kafka)
Never let event producers call channel services directly — a burst event (the article's example: a cricket wicket fanning out to 10 million users within a second) would flatten them. Events land in Kafka first; channel services consume at their own sustainable rate, so the queue absorbs the spike. Secondary benefit: durability — if a consumer service is down, messages persist in the topic until it recovers, so nothing is dropped. Cost: added asynchrony/latency, acceptable for most notification classes.

### Consumer-group scaling
Each channel service scales out horizontally, and Kafka spreads partition load across the members of each service's consumer group, giving natural load distribution without a bespoke load balancer for the consumption side.

### Retry with exponential backoff, then channel fallback (graceful degradation)
Failed sends are retried automatically on an exponential schedule — 1s, then 2s, then 4s. If retries exhaust, the system falls back to a different channel (push fails → email; email fails → SMS) rather than silently dropping the notification. The article names this graceful degradation and counts it, together with retries and broker replication, as one of three availability layers.

### Delivery tracking as a first-class stage
After every send, a tracking service records three outcomes: delivered (reached the device), opened (user engaged), or failed (bad token, bounced email, dropped SMS). Beyond triggering the retry/fallback path, this data feeds product analytics (open rates, optimal send times, fatigue signals) and cost accounting — SMS and email are per-message paid channels, so every send must be traceable.

### Latency-critical bypass lane for OTPs
OTPs are the exception to queue-everything: they demand near-instant delivery, so they skip Kafka entirely and hit the SMS service directly. General pattern: give a small, well-defined class of latency-critical traffic a synchronous fast path around the async pipeline instead of tightening latency for the whole queue.

### Broker replication for message durability
Kafka topics are replicated across multiple brokers, so a single broker failure loses no messages. This is the infrastructure-level availability layer beneath the application-level retries and fallbacks.

### End-to-end pipeline shape
The composed architecture: subscribers register into the preferences DB → an event-capturing service ingests events → Kafka buffers them → the router resolves preferences (via cache) and fans out → the four channel services deliver in parallel → the tracking service writes results to the notification log.

## Not absorbed

- Series framing ("Question-Based Series #2") and the interview-prep positioning — meta-context, not engineering content.
- The WhatsApp/Instagram/IPL name-dropping in the intro — motivational hook; the underlying spike number is kept in the Kafka pattern above.
- The restaurant/kitchen-ticket analogy for queues — pedagogical illustration adding no design substance beyond the buffer pattern already captured.
- The closing sign-off ("thanks for reading"-style) and engagement stats (views/likes) — social-platform chrome.

## Fidelity check

- **Post count in capture:** 1 (single long-form article post; `postCount: 1` in the JSON, no `---AUTHOR-POST-BREAK---` separators present).
- **Article outline (author's own section order):**
  1. Intro / motivation
  2. Functional requirements
  3. Notification channels
  4. The router, not just an API gateway
  5. The database layer — you need two
  6. The scale problem, and why Kafka solves it
  7. The full architecture
  8. Post-delivery — tracking
  9. Non-functional requirements: Scalability
  10. Non-functional requirements: Latency (incl. the OTP exception)
  11. Non-functional requirements: Availability
  12. Sign-off
- **Pattern-to-section citations:**
  - One service per delivery channel — "Notification channels" (section 3), reinforced in "Scalability" (section 9).
  - Preference-aware notification router — "The router, not just an API gateway" (section 4).
  - Two-store split — "The database layer — you need two" (section 5).
  - Redis preference caching — section 5, reinforced in "Latency" (section 10).
  - Kafka spike buffer — "The scale problem, and why Kafka solves it" (section 6).
  - Consumer-group scaling — "Scalability" (section 9).
  - Retry/backoff + channel fallback — "Post-delivery — tracking" (section 8) and "Availability" (section 11).
  - Delivery tracking stage — "Post-delivery — tracking" (section 8).
  - OTP bypass lane — "Latency" (section 10); OTP-forcing behavior also appears in section 4.
  - Broker replication — "Availability" (section 11).
  - End-to-end pipeline shape — "The full architecture" (section 7).
