---
source: https://algomaster.io/learn/system-design/tcp-vs-udp
author: AlgoMaster (Ashish Pratap Singh)
license-note: ideas absorbed in own words; no text or code reproduced
---

# TCP, UDP, and QUIC: choose by your answer to "what happens when data is late or lost?"

## What it teaches

Both protocols sit above IP and add ports so data reaches the right *program*,
not just the right machine. From there they diverge in what the OS handles for
you. TCP hands the application a reliable, ordered byte stream: handshake-based
connection setup, retransmission of lost segments, duplicate suppression via
sequence numbers, receiver-driven flow control, and network-sensing congestion
control. UDP hands over bare datagrams — ports, a length, a checksum, no
delivery or ordering promises — leaving pacing, recovery, and ordering to the
application or to a protocol layered on top.

Two corrections to folklore anchor the piece. First, TCP is a *stream*, not a
message protocol: writes can arrive merged or split, so the application
protocol must mark its own message boundaries (length prefixes, delimiters,
structured formats); UDP, by contrast, preserves one-send-one-datagram
boundaries. Second, "TCP is slow, UDP is fast" is rejected — TCP is fast on
healthy networks, and a UDP application that mishandles loss, pacing, or
packet sizing performs worse than TCP would have.

The deepest lesson: TCP's guarantees end at byte delivery. A connection can
close cleanly after the server committed a transaction but before the client
read the response — so applications still need timeouts, retries, idempotency
keys, and deduplication regardless of transport. QUIC completes the picture:
it runs *inside UDP* but re-implements reliability, congestion control,
multiplexed streams, built-in TLS 1.3, and connection migration — fixing TCP's
cross-stream head-of-line blocking (loss on one QUIC stream doesn't stall the
others) while inheriting UDP's reachability risks.

## Key patterns & decisions

- **Late-or-lost as the deciding question**: pick the transport by what the
  application should do with missing, stale, duplicated, or reordered data —
  a delayed SQL result is a stall; a delayed voice packet is garbage.
- **Stream vs datagram framing**: over TCP you must define message boundaries
  yourself; over UDP each datagram is a natural message.
- **Transport reliability ≠ business-operation success**: even over TCP,
  state-changing APIs need idempotency keys, request IDs, and dedup because a
  broken connection leaves outcomes unknown.
- **Responsible UDP = rebuilding selected TCP features**: serious UDP apps add
  sequence numbers, timestamps to discard stale data, selective app-level
  acks, forward error correction, rate control, and encryption (DTLS/SRTP/
  QUIC) — UDP is not permission to ignore congestion.
- **QUIC as UDP-with-batteries**: encryption by default, per-stream loss
  recovery, and connection IDs that survive client IP/port changes (mobile
  Wi-Fi-to-cellular handoff).
- **MTU discipline for datagrams**: keep UDP payloads well under common path
  MTUs — losing one fragment discards the whole datagram; don't assume jumbo
  frames outside controlled networks.
- **Five-tuple affinity for UDP load balancing**: with no transport connection
  to pin, balancers hash source/destination address+port+protocol; NAT churn
  breaks this, which QUIC connection IDs mitigate.
- **Protocol-specific monitoring**: TCP gives resets/retransmits/queue depth
  for free; UDP systems must invent loss-estimate, jitter, and reordering
  metrics; QUIC deployments should track handshake failures and TCP-fallback
  rates.
- **Amplification defense for public UDP**: spoofable source addresses mean
  rate limits and client validation before sending large responses.

## When to apply / trade-offs

Default to TCP for request/response APIs, databases, file transfer, mail, SSH,
and standard gRPC — anywhere every byte matters and order is required; it is
also the path of least resistance through firewalls and middleboxes. Choose
UDP when freshness beats completeness (voice/video, game state where the next
update supersedes a lost one, DNS lookups, lossy telemetry) or when a
UDP-based protocol already supplies the missing machinery. Choose QUIC/HTTP/3
when handshake latency, mobile network migration, or multi-stream
head-of-line blocking are real costs — but only if you can serve UDP on the
HTTPS port and fall back cleanly to TCP-based HTTP, since some networks block
or degrade UDP. Hybrid designs are normal: games pair lossy UDP state updates
with a reliable channel for purchases and inventory; AI platforms use
TCP-based HTTPS for API correctness while streaming tokens via SSE, chunked
responses, WebSockets, or HTTP/3.

## Fidelity check

1. *Claim*: TCP does not preserve application message boundaries. — *Capture
   support*: the article states three application writes may be read as one
   merged chunk, three chunks, or partial fragments, so the app protocol must
   supply length prefixes, delimiters, or structured framing.
2. *Claim*: a clean TCP close still leaves business outcomes unknown in a
   failure window. — *Capture support*: the capture gives the scenario of a
   server committing a database transaction with the connection breaking
   before the client sees the response, concluding real systems need
   timeouts, retries, idempotency keys, and duplicate handling.
3. *Claim*: QUIC avoids TCP's cross-stream stall problem. — *Capture
   support*: the article contrasts HTTP/2-over-TCP, where one lost segment
   blocks every stream on the connection, with QUIC's independent streams
   where loss on one does not block unrelated ones.
