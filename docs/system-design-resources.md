# System-design resources — coverage map

Source: [awesome-system-design-resources](https://github.com/ashishps1/awesome-system-design-resources)
by Ashish Pratap Singh (GPL-3.0 repo; linked articles © their publishers). Fetched 2026-07-24 via
plain HTTP. Ideas absorbed in the kit's own words with attribution; no text or code reproduced
(see `docs/influences.md`). Digests are named `asdr-*.md` in the owning skill's `references/`.

YouTube videos, courses, books, and the classic distributed-systems papers are noted but not
fetched (note-only rows).


## Core Concepts

| # | Item | Fetched | Digest | Kit outcome |
|---|------|---------|--------|-------------|
| 1 | [Scalability](https://algomaster.io/learn/system-design/scalability) | yes | — | digested for analysis; not shipped (map-only — no owning skill) |
| 2 | [Availability](https://algomaster.io/learn/system-design/availability) | yes | `skills/system-design-patterns/references/asdr-002-availability.md` | feeds `system-design-patterns` §Edge and traffic path |
| 3 | [Reliability](https://algomaster.io/learn/system-design/reliability) | yes | `skills/system-design-patterns/references/asdr-003-reliability.md` | reference digest in `system-design-patterns` |
| 4 | [SPOF](https://algomaster.io/learn/system-design/single-point-of-failure-spof) | yes | `skills/system-design-patterns/references/asdr-004-spof.md` | feeds `system-design-patterns` §Edge and traffic path |
| 5 | [Latency vs Throughput vs Bandwidth](https://algomaster.io/learn/system-design/latency-vs-throughput) | yes | `skills/system-design-patterns/references/asdr-005-latency-vs-throughput-vs-bandwidth.md` | reference digest in `system-design-patterns` |
| 6 | [Consistent Hashing](https://algomaster.io/learn/system-design/consistent-hashing) | yes | `skills/distributed-systems-patterns/references/asdr-006-consistent-hashing.md` | reference digest in `distributed-systems-patterns` |
| 7 | [CAP Theorem](https://algomaster.io/learn/system-design/cap-theorem) | yes | `skills/distributed-systems-patterns/references/asdr-007-cap-theorem.md` | reference digest in `distributed-systems-patterns` |
| 8 | [Failover](https://www.druva.com/glossary/what-is-a-failover-definition-and-related-faqs) | yes | `skills/distributed-systems-patterns/references/asdr-008-failover.md` | reference digest in `distributed-systems-patterns` |
| 9 | [Fault Tolerance](https://www.cockroachlabs.com/blog/what-is-fault-tolerance/) | yes | `skills/system-design-patterns/references/asdr-009-fault-tolerance.md` | reference digest in `system-design-patterns` |

## Networking Fundamentals

| # | Item | Fetched | Digest | Kit outcome |
|---|------|---------|--------|-------------|
| 1 | [OSI Model](https://algomaster.io/learn/system-design/osi) | yes | `skills/debugging-and-error-recovery/references/asdr-010-osi-model.md` | reference digest in `debugging-and-error-recovery` |
| 2 | [IP Addresses](https://algomaster.io/learn/system-design/ip-address) | yes | `skills/system-design-patterns/references/asdr-011-ip-addresses.md` | feeds `system-design-patterns` §Edge and traffic path |
| 3 | [Domain Name System (DNS)](https://blog.algomaster.io/p/how-dns-actually-works) | yes | `skills/system-design-patterns/references/asdr-012-domain-name-system-dns.md` | feeds `system-design-patterns` §Edge and traffic path |
| 4 | [Proxy vs Reverse Proxy](https://blog.algomaster.io/p/proxy-vs-reverse-proxy-explained) | yes | `skills/system-design-patterns/references/asdr-013-proxy-vs-reverse-proxy.md` | feeds `system-design-patterns` §Edge and traffic path |
| 5 | [HTTP/HTTPS](https://algomaster.io/learn/system-design/http-https) | yes | `skills/api-and-interface-design/references/asdr-014-http-https.md` | reference digest in `api-and-interface-design` |
| 6 | [TCP vs UDP](https://algomaster.io/learn/system-design/tcp-vs-udp) | yes | `skills/system-design-patterns/references/asdr-015-tcp-vs-udp.md` | feeds `system-design-patterns` §Realtime transport |
| 7 | [Load Balancing](https://blog.algomaster.io/p/load-balancing-algorithms-explained-with-code) | yes | `skills/system-design-patterns/references/asdr-016-load-balancing.md` | feeds `system-design-patterns` §Edge and traffic path |
| 8 | [Checksums](https://algomaster.io/learn/system-design/checksums) | yes | `skills/distributed-systems-patterns/references/asdr-017-checksums.md` | reference digest in `distributed-systems-patterns` |

## API Fundamentals

| # | Item | Fetched | Digest | Kit outcome |
|---|------|---------|--------|-------------|
| 1 | [APIs](https://algomaster.io/learn/system-design/what-is-an-api) | yes | `skills/api-and-interface-design/references/asdr-018-apis.md` | reference digest in `api-and-interface-design` |
| 2 | [API Gateway](https://blog.algomaster.io/p/what-is-an-api-gateway) | yes | `skills/system-design-patterns/references/asdr-019-api-gateway.md` | feeds `system-design-patterns` §Edge and traffic path |
| 3 | [REST vs GraphQL](https://blog.algomaster.io/p/rest-vs-graphql) | yes | `skills/graphql-patterns/references/asdr-020-rest-vs-graphql.md` | reference digest in `graphql-patterns` |
| 4 | [WebSockets](https://blog.algomaster.io/p/websockets) | yes | `skills/system-design-patterns/references/asdr-021-websockets.md` | feeds `system-design-patterns` §Realtime transport |
| 5 | [Webhooks](https://algomaster.io/learn/system-design/webhooks) | yes | `skills/system-design-patterns/references/asdr-022-webhooks.md` | reference digest in `system-design-patterns` |
| 6 | [Idempotency](https://algomaster.io/learn/system-design/idempotency) | yes | `skills/api-and-interface-design/references/asdr-023-idempotency.md` | reference digest in `api-and-interface-design` |
| 7 | [Rate limiting](https://blog.algomaster.io/p/rate-limiting-algorithms-explained-with-code) | yes | `skills/system-design-patterns/references/asdr-024-rate-limiting.md` | reference digest in `system-design-patterns` |
| 8 | [API Design](https://abdulrwahab.medium.com/api-architecture-best-practices-for-designing-rest-apis-bf907025f5f) | yes | — | digested for analysis; not shipped (map-only — no owning skill) |

## Database Fundamentals

| # | Item | Fetched | Digest | Kit outcome |
|---|------|---------|--------|-------------|
| 1 | [ACID Transactions](https://algomaster.io/learn/system-design/acid-transactions) | yes | `skills/python-dao-and-database/references/asdr-026-acid-transactions.md` | feeds `system-design-patterns` §Choosing the datastore |
| 2 | [SQL vs NoSQL](https://algomaster.io/learn/system-design/sql-vs-nosql) | yes | `skills/system-design-patterns/references/asdr-027-sql-vs-nosql.md` | reference digest in `system-design-patterns` |
| 3 | [Database Indexes](https://algomaster.io/learn/system-design/indexing) | yes | `skills/python-dao-and-database/references/asdr-028-database-indexes.md` | feeds `system-design-patterns` §Choosing the datastore |
| 4 | [Database Sharding](https://algomaster.io/learn/system-design/sharding) | yes | `skills/distributed-systems-patterns/references/asdr-029-database-sharding.md` | reference digest in `distributed-systems-patterns` |
| 5 | [Data Replication](https://redis.com/blog/what-is-data-replication/) | yes | `skills/distributed-systems-patterns/references/asdr-030-data-replication.md` | reference digest in `distributed-systems-patterns` |
| 6 | [Database Scaling](https://blog.algomaster.io/p/system-design-how-to-scale-a-database) | yes | `skills/distributed-systems-patterns/references/asdr-031-database-scaling.md` | feeds `system-design-patterns` §Choosing the datastore |
| 7 | [Databases Types](https://blog.algomaster.io/p/15-types-of-databases) | yes | `skills/system-design-patterns/references/asdr-032-databases-types.md` | reference digest in `system-design-patterns` |
| 8 | [Bloom Filters](https://algomaster.io/learn/system-design/bloom-filters) | yes | `skills/distributed-systems-patterns/references/asdr-033-bloom-filters.md` | reference digest in `distributed-systems-patterns` |
| 9 | [Database Architectures](https://www.mongodb.com/developer/products/mongodb/active-active-application-architectures/) | yes | — | digested for analysis; not shipped (map-only — no owning skill) |

## Caching Fundamentals

| # | Item | Fetched | Digest | Kit outcome |
|---|------|---------|--------|-------------|
| 1 | [Caching 101](https://algomaster.io/learn/system-design/what-is-caching) | yes | `skills/system-design-patterns/references/asdr-035-caching-101.md` | reference digest in `system-design-patterns` |
| 2 | [Caching Strategies](https://algomaster.io/learn/system-design/caching-strategies) | yes | `skills/distributed-systems-patterns/references/asdr-036-caching-strategies.md` | reference digest in `distributed-systems-patterns` |
| 3 | [Cache Eviction Policies](https://blog.algomaster.io/p/7-cache-eviction-strategies) | yes | `skills/distributed-systems-patterns/references/asdr-037-cache-eviction-policies.md` | reference digest in `distributed-systems-patterns` |
| 4 | [Distributed Caching](https://blog.algomaster.io/p/distributed-caching) | yes | `skills/distributed-systems-patterns/references/asdr-038-distributed-caching.md` | reference digest in `distributed-systems-patterns` |
| 5 | [Content Delivery Network (CDN)](https://algomaster.io/learn/system-design/content-delivery-network-cdn) | yes | `skills/system-design-patterns/references/asdr-039-content-delivery-network-cdn.md` | reference digest in `system-design-patterns` |

## Asynchronous Communication

| # | Item | Fetched | Digest | Kit outcome |
|---|------|---------|--------|-------------|
| 1 | [Pub/Sub](https://algomaster.io/learn/system-design/pub-sub) | yes | `skills/system-design-patterns/references/asdr-040-pub-sub.md` | reference digest in `system-design-patterns` |
| 2 | [Message Queues](https://algomaster.io/learn/system-design/message-queues) | yes | `skills/system-design-patterns/references/asdr-041-message-queues.md` | reference digest in `system-design-patterns` |
| 3 | [Change Data Capture (CDC)](https://algomaster.io/learn/system-design/change-data-capture-cdc) | yes | `skills/system-design-patterns/references/asdr-042-change-data-capture-cdc.md` | reference digest in `system-design-patterns` |

## Distributed System and Microservices

| # | Item | Fetched | Digest | Kit outcome |
|---|------|---------|--------|-------------|
| 1 | [HeartBeats](https://blog.algomaster.io/p/heartbeats-in-distributed-systems) | yes | `skills/distributed-systems-patterns/references/asdr-043-heartbeats.md` | reference digest in `distributed-systems-patterns` |
| 2 | [Service Discovery](https://blog.algomaster.io/p/service-discovery-in-distributed-systems) | yes | `skills/system-design-patterns/references/asdr-044-service-discovery.md` | feeds `system-design-patterns` §Edge and traffic path |
| 3 | [Consensus Algorithms](https://medium.com/@sourabhatta1819/consensus-in-distributed-system-ac79f8ba2b8c) | no | — | not fetched (http=403) — honest row, no digest |
| 4 | [Distributed Locking](https://martin.kleppmann.com/2016/02/08/how-to-do-distributed-locking.html) | yes | `skills/distributed-systems-patterns/references/asdr-046-distributed-locking.md` | feeds `distributed-systems-patterns` §Distributed locking and fencing |
| 5 | [Gossip Protocol](http://highscalability.com/blog/2023/7/16/gossip-protocol-explained.html) | yes | `skills/distributed-systems-patterns/references/asdr-047-gossip-protocol.md` | reference digest in `distributed-systems-patterns` |
| 6 | [Circuit Breaker](https://medium.com/geekculture/design-patterns-for-microservices-circuit-breaker-pattern-276249ffab33) | no | — | not fetched (http=403) — honest row, no digest |
| 7 | [Disaster Recovery](https://cloud.google.com/learn/what-is-disaster-recovery) | yes | `skills/system-design-patterns/references/asdr-049-disaster-recovery.md` | reference digest in `system-design-patterns` |
| 8 | [Distributed Tracing](https://www.dynatrace.com/news/blog/what-is-distributed-tracing/) | yes | `skills/otel-tracing/references/asdr-050-distributed-tracing.md` | reference digest in `otel-tracing` |

## Architectural Patterns

| # | Item | Fetched | Digest | Kit outcome |
|---|------|---------|--------|-------------|
| 1 | [Client-Server Architecture](https://algomaster.io/learn/system-design/client-server-architecture) | yes | `skills/system-design-patterns/references/asdr-051-client-server-architecture.md` | reference digest in `system-design-patterns` |
| 2 | [Microservices Architecture](https://medium.com/hashmapinc/the-what-why-and-how-of-a-microservices-architecture-4179579423a9) | no | — | not fetched (http=403) — honest row, no digest |
| 3 | [Serverless Architecture](https://blog.algomaster.io/p/2edeb23b-cfa5-4b24-845e-3f6f7a39d162) | partial | — | digested; filed by verify+refute |
| 4 | [Event-Driven Architecture](https://www.confluent.io/learn/event-driven-architecture/) | yes | `skills/system-design-patterns/references/asdr-054-event-driven-architecture.md` | reference digest in `system-design-patterns` |
| 5 | [Peer-to-Peer (P2P) Architecture](https://www.spiceworks.com/tech/networking/articles/what-is-peer-to-peer/) | yes | `skills/distributed-systems-patterns/references/asdr-055-peer-to-peer-p2p-architecture.md` | reference digest in `distributed-systems-patterns` |

## System Design Tradeoffs

| # | Item | Fetched | Digest | Kit outcome |
|---|------|---------|--------|-------------|
| 1 | [Top 15 Tradeoffs](https://blog.algomaster.io/p/system-design-top-15-trade-offs) | yes | `skills/system-design-patterns/references/asdr-056-top-15-tradeoffs.md` | reference digest in `system-design-patterns` |
| 2 | [Vertical vs Horizontal Scaling](https://algomaster.io/learn/system-design/vertical-vs-horizontal-scaling) | yes | `skills/system-design-patterns/references/asdr-057-vertical-vs-horizontal-scaling.md` | reference digest in `system-design-patterns` |
| 3 | [Concurrency vs Parallelism](https://blog.algomaster.io/p/concurrency-vs-parallelism) | yes | `skills/system-design-patterns/references/asdr-058-concurrency-vs-parallelism.md` | reference digest in `system-design-patterns` |
| 4 | [Long Polling vs WebSockets](https://blog.algomaster.io/p/long-polling-vs-websockets) | yes | `skills/system-design-patterns/references/asdr-059-long-polling-vs-websockets.md` | feeds `system-design-patterns` §Realtime transport |
| 5 | [Batch vs Stream Processing](https://blog.algomaster.io/p/batch-processing-vs-stream-processing) | yes | `skills/system-design-patterns/references/asdr-060-batch-vs-stream-processing.md` | feeds `distributed-systems-patterns` §Batch vs stream processing |
| 6 | [Stateful vs Stateless Design](https://blog.algomaster.io/p/stateful-vs-stateless-architecture) | yes | `skills/system-design-patterns/references/asdr-061-stateful-vs-stateless-design.md` | reference digest in `system-design-patterns` |
| 7 | [Strong vs Eventual Consistency](https://blog.algomaster.io/p/strong-vs-eventual-consistency) | yes | `skills/distributed-systems-patterns/references/asdr-062-strong-vs-eventual-consistency.md` | feeds the consensus paragraph in `distributed-systems-patterns` §Replication and quorum |
| 8 | [Read-Through vs Write-Through Cache](https://blog.algomaster.io/p/59cae60d-9717-4e20-a59e-759e370db4e5) | partial | — | digested; filed by verify+refute |
| 9 | [Push vs Pull Architecture](https://blog.algomaster.io/p/af5fe2fe-9a4f-4708-af43-184945a243af) | partial | — | digested; filed by verify+refute |
| 10 | [REST vs RPC](https://blog.algomaster.io/p/106604fb-b746-41de-88fb-60e932b2ff68) | partial | — | digested; filed by verify+refute |
| 11 | [Synchronous vs. asynchronous communications](https://blog.algomaster.io/p/aec1cebf-6060-45a7-8e00-47364ca70761) | partial | — | digested; filed by verify+refute |
| 12 | [Latency vs Throughput](https://aws.amazon.com/compare/the-difference-between-throughput-and-latency/) | yes | `skills/system-design-patterns/references/asdr-067-latency-vs-throughput.md` | feeds `system-design-patterns` §Choosing the datastore |

## How to Answer a System Design Interview Problem(https//algomasterio/learn/system-design-interviews/answering-framework)

| # | Item | Fetched | Digest | Kit outcome |
|---|------|---------|--------|-------------|
| 1 | [How to Answer a System Design Interview Problem](https://algomaster.io/learn/system-design-interviews/answering-framework) | yes | `skills/system-design-patterns/references/asdr-068-how-to-answer-a-system-design-interview-problem.md` | reference digest in `system-design-patterns` |

## System Design Interview Problems

| # | Item | Fetched | Digest | Kit outcome |
|---|------|---------|--------|-------------|
| 1 | [Design URL Shortener like TinyURL](https://algomaster.io/learn/system-design-interviews/design-url-shortener) | yes | `skills/system-design-patterns/references/asdr-069-design-url-shortener-like-tinyurl.md` | reference digest in `system-design-patterns` |
| 2 | [Design Autocomplete for Search Engines](https://algomaster.io/learn/system-design-interviews/design-instagram) | yes | — | digested for analysis; not shipped (map-only — no owning skill) |
| 3 | [Design Load Balancer](https://algomaster.io/learn/system-design-interviews/design-load-balancer) | yes | `skills/system-design-patterns/references/asdr-071-design-load-balancer.md` | reference digest in `system-design-patterns` |
| 4 | [Design Content Delivery Network (CDN)](https://www.youtube.com/watch?v=8zX0rue2Hic) | — | — | note-only (video) |
| 5 | [Design Parking Garage](https://www.youtube.com/watch?v=NtMvNh0WFVM) | — | — | note-only (video) |
| 6 | [Design Vending Machine](https://www.youtube.com/watch?v=D0kDMUgo27c) | — | — | note-only (video) |
| 7 | [Design Distributed Key-Value Store](https://www.youtube.com/watch?v=rnZmdmlR-2M) | — | — | note-only (video) |
| 8 | [Design Distributed Cache](https://www.youtube.com/watch?v=iuqZvajTOyA) | — | — | note-only (video) |
| 9 | [Design Authentication System](https://www.youtube.com/watch?v=uj_4vxm9u90) | — | — | note-only (video) |
| 10 | [Design Unified Payments Interface (UPI)](https://www.youtube.com/watch?v=QpLy0_c_RXk) | — | — | note-only (video) |
| 11 | [Design WhatsApp](https://algomaster.io/learn/system-design-interviews/design-whatsapp) | yes | `skills/system-design-patterns/references/asdr-079-design-whatsapp.md` | reference digest in `system-design-patterns` |
| 12 | [Design Spotify](https://algomaster.io/learn/system-design-interviews/design-spotify) | yes | `skills/system-design-patterns/references/asdr-080-design-spotify.md` | reference digest in `system-design-patterns` |
| 13 | [Design Instagram](https://algomaster.io/learn/system-design-interviews/design-instagram) | — | — | deduplicated — duplicate of asdr-070 (same canonical URL) |
| 14 | [Design Notification Service](https://algomaster.io/learn/system-design-interviews/design-notification-service) | yes | `skills/system-design-patterns/references/asdr-082-design-notification-service.md` | reference digest in `system-design-patterns` |
| 15 | [Design Distributed Job Scheduler](https://blog.algomaster.io/p/design-a-distributed-job-scheduler) | yes | `skills/system-design-patterns/references/asdr-083-design-distributed-job-scheduler.md` | reference digest in `system-design-patterns` |
| 16 | [Design Tinder](https://www.youtube.com/watch?v=tndzLznxq40) | — | — | note-only (video) |
| 17 | [Design Facebook](https://www.youtube.com/watch?v=9-hjBGxuiEs) | — | — | note-only (video) |
| 18 | [Design Twitter](https://www.youtube.com/watch?v=wYk0xPP_P_8) | — | — | note-only (video) |
| 19 | [Design Reddit](https://www.youtube.com/watch?v=KYExYE_9nIY) | — | — | note-only (video) |
| 20 | [Design Netflix](https://www.youtube.com/watch?v=psQzyFfsUGU) | — | — | note-only (video) |
| 21 | [Design Youtube](https://www.youtube.com/watch?v=jPKTo1iGQiE) | — | — | note-only (video) |
| 22 | [Design Google Search](https://www.youtube.com/watch?v=CeGtqouT8eA) | — | — | note-only (video) |
| 23 | [Design E-commerce Store like Amazon](https://www.youtube.com/watch?v=EpASu_1dUdE) | — | — | note-only (video) |
| 24 | [Design TikTok](https://www.youtube.com/watch?v=Z-0g_aJL5Fw) | — | — | note-only (video) |
| 25 | [Design Shopify](https://www.youtube.com/watch?v=lEL4F_0J3l8) | — | — | note-only (video) |
| 26 | [Design Airbnb](https://www.youtube.com/watch?v=YyOXt2MEkv4) | — | — | note-only (video) |
| 27 | [Design Rate Limiter](https://www.youtube.com/watch?v=mhUQe4BKZXs) | — | — | note-only (video) |
| 28 | [Design Distributed Message Queue like Kafka](https://www.youtube.com/watch?v=iJLL-KPqBpM) | — | — | note-only (video) |
| 29 | [Design Flight Booking System](https://www.youtube.com/watch?v=qsGcfVGvFSs) | — | — | note-only (video) |
| 30 | [Design Online Code Editor](https://www.youtube.com/watch?v=07jkn4jUtso) | — | — | note-only (video) |
| 31 | [Design an Analytics Platform (Metrics & Logging)](https://www.youtube.com/watch?v=kIcq1_pBQSY) | — | — | note-only (video) |
| 32 | [Design Payment System](https://www.youtube.com/watch?v=olfaBgJrUBI) | — | — | note-only (video) |
| 33 | [Design a Digital Wallet](https://www.youtube.com/watch?v=4ijjIUeq6hE) | — | — | note-only (video) |
| 34 | [Design Location Based Service like Yelp](https://www.youtube.com/watch?v=M4lR_Va97cQ) | — | — | note-only (video) |
| 35 | [Design Uber](https://www.youtube.com/watch?v=umWABit-wbk) | — | — | note-only (video) |
| 36 | [Design Food Delivery App like Doordash](https://www.youtube.com/watch?v=iRhSAR3ldTw) | — | — | note-only (video) |
| 37 | [Design Google Docs](https://www.youtube.com/watch?v=2auwirNBvGg) | — | — | note-only (video) |
| 38 | [Design Google Maps](https://www.youtube.com/watch?v=jk3yvVfNvds) | — | — | note-only (video) |
| 39 | [Design Zoom](https://www.youtube.com/watch?v=G32ThJakeHk) | — | — | note-only (video) |
| 40 | [Design File Sharing System like Dropbox](https://www.youtube.com/watch?v=U0xTu6E2CT8) | — | — | note-only (video) |
| 41 | [Design Ticket Booking System like BookMyShow](https://www.youtube.com/watch?v=lBAwJgoO3Ek) | — | — | note-only (video) |
| 42 | [Design Distributed Web Crawler](https://www.youtube.com/watch?v=BKZxZwUgL3Y) | — | — | note-only (video) |
| 43 | [Design Code Deployment System](https://www.youtube.com/watch?v=q0KGYwNbf-0) | — | — | note-only (video) |
| 44 | [Design Distributed Cloud Storage like S3](https://www.youtube.com/watch?v=UmWtcgC96X8) | — | — | note-only (video) |
| 45 | [Design Distributed Locking Service](https://www.youtube.com/watch?v=v7x75aN9liM) | — | — | note-only (video) |

## Courses

| # | Item | Fetched | Digest | Kit outcome |
|---|------|---------|--------|-------------|
| 1 | [System Design Fundamentals](https://algomaster.io/learn/system-design/course-introduction) | — | — | note-only — course/newsletter/channel |
| 2 | [System Design Interviews](https://algomaster.io/learn/system-design-interviews/introduction) | — | — | note-only — course/newsletter/channel |

## Newsletters

| # | Item | Fetched | Digest | Kit outcome |
|---|------|---------|--------|-------------|
| 1 | [AlgoMaster Newsletter](https://blog.algomaster.io/) | — | — | note-only — course/newsletter/channel |

## Books

| # | Item | Fetched | Digest | Kit outcome |
|---|------|---------|--------|-------------|
| 1 | [Designing Data-Intensive Applications](https://www.amazon.in/dp/9352135245) | — | — | note-only (book) |

## YouTube Channels

| # | Item | Fetched | Digest | Kit outcome |
|---|------|---------|--------|-------------|
| 1 | [Tech Dummies Narendra L](https://www.youtube.com/@TechDummiesNarendraL) | — | — | note-only (video) |
| 2 | [Gaurav Sen](https://www.youtube.com/@gkcs) | — | — | note-only (video) |
| 3 | [codeKarle](https://www.youtube.com/@codeKarle) | — | — | note-only (video) |
| 4 | [ByteByteGo](https://www.youtube.com/@ByteByteGo) | — | — | note-only (video) |
| 5 | [System Design Interview](https://www.youtube.com/@SystemDesignInterview) | — | — | note-only (video) |
| 6 | [sudoCODE](https://www.youtube.com/@sudocode) | — | — | note-only (video) |
| 7 | [Success in Tech](https://www.youtube.com/@SuccessinTech/videos) | — | — | note-only (video) |

## Must-Read Engineering Articles

| # | Item | Fetched | Digest | Kit outcome |
|---|------|---------|--------|-------------|
| 1 | [How Discord stores trillions of messages](https://discord.com/blog/how-discord-stores-trillions-of-messages) | yes | `skills/deprecation-and-migration/references/asdr-125-how-discord-stores-trillions-of-messages.md` | feeds `deprecation-and-migration` §Shadow verification before cutover |
| 2 | [Building In-Video Search at Netflix](https://netflixtechblog.com/building-in-video-search-936766f0017c) | yes | — | digested for analysis; not shipped (map-only — no owning skill) |
| 3 | [How Canva scaled Media uploads from Zero to 50 Million per Day](https://www.canva.dev/blog/engineering/from-zero-to-50-million-uploads-per-day-scaling-media-at-canva/) | yes | `skills/deprecation-and-migration/references/asdr-127-how-canva-scaled-media-uploads-from-zero-to-50-million-per-d.md` | feeds `deprecation-and-migration` §Shadow verification before cutover |
| 4 | [How Airbnb avoids double payments in a Distributed Payments System](https://medium.com/airbnb-engineering/avoiding-double-payments-in-a-distributed-payments-system-2981f6b070bb) | no | — | not fetched (http=403) — honest row, no digest |
| 5 | [Stripe’s payments APIs - The first 10 years](https://stripe.com/blog/payment-api-design) | yes | `skills/api-and-interface-design/references/asdr-129-stripe-s-payments-apis-the-first-10-years.md` | reference digest in `api-and-interface-design` |
| 6 | [Real time messaging at Slack](https://slack.engineering/real-time-messaging/) | yes | `skills/system-design-patterns/references/asdr-130-real-time-messaging-at-slack.md` | reference digest in `system-design-patterns` |

## Must-Read Distributed Systems Papers

| # | Item | Fetched | Digest | Kit outcome |
|---|------|---------|--------|-------------|
| 1 | [Paxos: The Part-Time Parliament](https://lamport.azurewebsites.net/pubs/lamport-paxos.pdf) | — | — | note-only — classic paper; concepts covered by `distributed-systems-patterns` / `rules/resilience-engineering.md` |
| 2 | [MapReduce: Simplified Data Processing on Large Clusters](https://research.google.com/archive/mapreduce-osdi04.pdf) | — | — | note-only — classic paper; concepts covered by `distributed-systems-patterns` / `rules/resilience-engineering.md` |
| 3 | [The Google File System](https://static.googleusercontent.com/media/research.google.com/en//archive/gfs-sosp2003.pdf) | — | — | note-only — classic paper; concepts covered by `distributed-systems-patterns` / `rules/resilience-engineering.md` |
| 4 | [Dynamo: Amazon’s Highly Available Key-value Store](https://www.allthingsdistributed.com/files/amazon-dynamo-sosp2007.pdf) | — | — | note-only — classic paper; concepts covered by `distributed-systems-patterns` / `rules/resilience-engineering.md` |
| 5 | [Kafka: a Distributed Messaging System for Log Processing](https://notes.stephenholiday.com/Kafka.pdf) | — | — | note-only — classic paper; concepts covered by `distributed-systems-patterns` / `rules/resilience-engineering.md` |
| 6 | [Spanner: Google’s Globally-Distributed Database](https://static.googleusercontent.com/media/research.google.com/en//archive/spanner-osdi2012.pdf) | — | — | note-only — classic paper; concepts covered by `distributed-systems-patterns` / `rules/resilience-engineering.md` |
| 7 | [Bigtable: A Distributed Storage System for Structured Data](https://static.googleusercontent.com/media/research.google.com/en//archive/bigtable-osdi06.pdf) | — | — | note-only — classic paper; concepts covered by `distributed-systems-patterns` / `rules/resilience-engineering.md` |
| 8 | [ZooKeeper: Wait-free coordination for Internet-scale systems](https://www.usenix.org/legacy/event/usenix10/tech/full_papers/Hunt.pdf) | — | — | note-only — classic paper; concepts covered by `distributed-systems-patterns` / `rules/resilience-engineering.md` |
| 9 | [The Log-Structured Merge-Tree (LSM-Tree)](https://www.cs.umb.edu/~poneil/lsmtree.pdf) | — | — | note-only — classic paper; concepts covered by `distributed-systems-patterns` / `rules/resilience-engineering.md` |
| 10 | [The Chubby lock service for loosely-coupled distributed systems](https://static.googleusercontent.com/media/research.google.com/en//archive/chubby-osdi06.pdf) | — | — | note-only — classic paper; concepts covered by `distributed-systems-patterns` / `rules/resilience-engineering.md` |

---

*140 items noted; 67 shipped digests.*
