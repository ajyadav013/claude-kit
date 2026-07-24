# Digest: Apache Kafka: Crash Course

- **Source:** https://x.com/Harry_The_Nerd/status/2062165677033820383
- **Author:** Harshit Khosla (@Harry_The_Nerd)
- **Category:** Engineering Articles
- **Fetched:** 2026-07-23/24 via logged-out browser render
- **License note:** Content (c) the author; this digest is an own-words summary for internal engineering reference — no verbatim text.

## Patterns

### Durable log as a decoupling layer between services and the database
Instead of letting client traffic write straight into a transactional database (which degrades, exhausts its connection pool, and eventually collapses under firehose ingestion), put a distributed, persistent, replicated log between producers and consumers. Writers append to the log; readers consume at whatever rate they can sustain; neither side ever blocks the other. This also replaces the N-to-N mesh of bespoke point-to-point pipelines (the pre-Kafka LinkedIn failure mode, where one slow downstream propagated backpressure upstream) with a single hub. Use it whenever ingest rate can spike far beyond what downstream stores tolerate. Trade-off: you add an operational system and shift from synchronous to eventual consistency. Scale reference from the article: Uber handles on the order of 1 trillion events/day through this style of infrastructure.

### Async fan-out from a single event write
A user action (e.g., an order) becomes one appended event, and the HTTP response returns immediately. Separate consumers then independently handle persistence, inventory adjustment, notification email, and analytics. Contrast: the naive design does all of those side effects synchronously inside one request, coupling every subsystem's latency and failure modes together. With fan-out, each downstream can fail, scale, and pace itself independently. Netflix applies the same idea as one canonical event stream feeding dashboards, warehouses, model training, and A/B systems (hundreds of billions of events/day) without consumers interfering with each other. Trade-off: side effects become eventually consistent and you must reason about partial completion.

### Metered database ingestion
Once the log absorbs the burst, the database receives writes only from one (or a few) controlled consumers at a sustainable rate — the uncontrolled firehose becomes a managed drain. Use when the DB is the bottleneck under spiky write load; the cost is added end-to-end latency between the user action and the DB reflecting it.

### Event replay from retained history
The database holds only current state; the log retains the sequence of events that produced it. A service added months later can bootstrap by replaying the topic from the start — impossible with a state-only store. Uber's fraud detection illustrates the streaming-read side: consuming payment events in-flight gives millisecond-scale flagging, versus per-transaction DB queries.

### Topics as append-only, keyed event logs
An event carries a key, a value, a timestamp, and optional headers. A topic groups events like a table or folder, but is append-only and ordered — no in-place updates or deletes. This immutability is what makes replay and multi-reader independence safe.

### Partitioning as the unit of parallelism, with per-key ordering
A topic splits into partitions — ordered, immutable, on-disk sequences. Throughput scales roughly linearly by adding partitions (illustrative figure: 100 MB/s per partition → 1 GB/s across 10). Events sharing a key are routed to one partition, so all events for a given user or order are strictly ordered relative to each other while unrelated keys flow in parallel. Trade-off: ordering is guaranteed only within a partition, and your key choice fixes both ordering scope and load distribution.

### Leader/follower replication across brokers
Partitions are spread over broker nodes; each partition has one leader serving reads/writes plus followers replicating it. On leader loss a follower is promoted automatically. With replication factor 3 the cluster survives two broker failures without data loss. Trade-off: replication multiplies storage and network cost.

### Producer batching and tunable acknowledgment
Producers accumulate events and flush them in batches rather than issuing a disk write per event — a major source of the system's throughput. Acknowledgment level is configurable (none, leader-only, or all replicas), letting you trade durability guarantees against write latency per workload.

### Consumer groups with automatic partition rebalancing
Instances in the same group divide a topic's partitions among themselves (12 partitions over 4 instances → 3 each). Adding instances raises consumption throughput; removing them triggers automatic rebalance. Effective parallelism is capped by partition count.

### Pull-based consumption with consumer-owned offsets
Consumers pull and advance their own offset (an integer bookmark into the log); nothing is pushed. A slow consumer merely lags and later catches up — it exerts zero backpressure on producers or the broker. Distinct groups keep independent offsets, so analytics and notifications can read the same topic at unrelated speeds.

### Log retention instead of delete-on-consume
Classic queues destroy a message once it is consumed; this system retains events for a configured time window or size budget regardless of consumption. That retention is precisely what enables replay and multi-group reads — the article frames it as the defining difference: a log, not a queue.

### KRaft replacing ZooKeeper for cluster metadata
Cluster coordination (metadata, leader election, config) historically required an external ZooKeeper ensemble. KRaft — an internal Raft-based consensus mode introduced in Kafka 2.8 and production-ready from 3.3 — removes that dependency; modern deployments should use it for simpler operations.

### At-least-once delivery via commit-after-processing
In the described Go example: a hash-based partitioner keys events by order ID so an order's lifecycle events ("placed", then "payment confirmed") stay ordered; two consumer groups (DB writer, notifications) each independently receive every event; and offsets are committed only after processing succeeds, so a crash mid-work causes reprocessing rather than silent loss. Trade-off: consumers must tolerate duplicates (idempotency) since redelivery is possible.

## Not absorbed

- The Uber Friday-night outage narrative — motivational scene-setting, not a technique (its underlying lesson is captured in the decoupling pattern).
- The LinkedIn ~2010 origin story and the naming of Kreps/Narkhede/Rao — project history, no engineering content beyond the anti-pattern already absorbed.
- The postal-sorting-facility analogy — pedagogical metaphor restating the decoupling idea.
- Netflix/Uber name-dropping as social proof — the transferable mechanics and scale figures were folded into the relevant patterns; the case-study framing itself adds nothing.
- The closing sign-off line — pure salutation.
- Trailing timestamp/view/engagement counters — platform chrome captured with the post, not article content.

## Fidelity check

- **Post count in capture:** 1 (single long-form article post).
- **Article outline as authored:**
  1. Title block ("Apache Kafka: Crash Course" + subtitle)
  2. The Problem: Your Database Is Not a Message Queue
  3. What Is Kafka?
  4. Kafka and the Database: A Better Architecture
  5. The Architecture of Kafka
     1. Events and Topics
     2. Partitions: The Unit of Parallelism
     3. Brokers and the Cluster
     4. Producers
     5. Consumers and Consumer Groups
     6. Retention: Kafka Is Not a Queue
     7. ZooKeeper and KRaft
  6. Kafka in Production: What Netflix and Uber Actually Do With It
  7. A Kafka Producer and Consumer in Go
  8. Sign-off
- **Pattern-to-section mapping:**
  - Durable log as a decoupling layer — "The Problem: Your Database Is Not a Message Queue" + "What Is Kafka?"
  - Async fan-out from a single event write — "Kafka and the Database: A Better Architecture" (Netflix detail from "Kafka in Production")
  - Metered database ingestion — "What Is Kafka?" + "Kafka and the Database: A Better Architecture"
  - Event replay from retained history — "Kafka and the Database: A Better Architecture" (Uber fraud detail from "Kafka in Production")
  - Topics as append-only, keyed event logs — "Events and Topics"
  - Partitioning with per-key ordering — "Partitions: The Unit of Parallelism"
  - Leader/follower replication — "Brokers and the Cluster"
  - Producer batching and tunable acks — "Producers"
  - Consumer groups with rebalancing — "Consumers and Consumer Groups"
  - Pull-based consumption with owned offsets — "Consumers and Consumer Groups"
  - Log retention instead of delete-on-consume — "Retention: Kafka Is Not a Queue"
  - KRaft replacing ZooKeeper — "ZooKeeper and KRaft"
  - At-least-once via commit-after-processing — "A Kafka Producer and Consumer in Go"
