---
source: https://algomaster.io/learn/system-design/checksums
author: AlgoMaster (Ashish Pratap Singh)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Checksums as a layered integrity toolkit: detection, not repair, and not authentication

## What it teaches

How to think about data-integrity verification as a family of tools graded by
threat model. Corruption is silent — a damaged packet, a stale disk block, or
a half-finished download does not self-report — so systems attach a small
derived value to data and recompute it at each boundary. The chapter's central
discipline is matching the mechanism to the failure you fear: parity and
additive sums for trivially cheap single-bit checks, CRCs for accidental
transport/storage damage, cryptographic hashes for content identity,
HMACs/signatures when an adversary might tamper. It also insists on two
separations that engineers routinely blur: detection is not recovery, and
integrity is not confidentiality.

## Key patterns & decisions

- **Threat-model-driven algorithm choice** — pick CRC for accidental
  corruption, a modern cryptographic hash (SHA-256 class) for content
  fingerprints, HMAC or a digital signature when provenance matters; using a
  CRC against a tamperer is a category error because the attacker just
  recomputes it.
- **Plain checksums cannot survive an attacker who controls both data and
  checksum** — if the verifier's expected value travels with the data through
  untrusted hands, integrity claims collapse; the expected digest must arrive
  via a separately trusted channel (signed manifest, package index, trusted
  site).
- **HMAC vs. signature = symmetric vs. asymmetric trust topology** — HMAC
  suits two mutually trusting parties sharing a secret (webhook provider and
  receiver), but every verifier can also forge; signatures let one private-key
  holder prove authorship to unlimited public-key verifiers, at the price of
  key-distribution trust.
- **End-to-end integrity over per-hop integrity** — a link-level frame check
  proves one hop; real protection means computing a digest at the producer,
  storing it in trusted metadata, and re-verifying after every meaningful
  boundary (upload, replication, storage, restore, download), because
  corruption can occur in client memory, NICs, kernel buffers, firmware,
  compaction, or backup tooling.
- **Detection and recovery are separate subsystems** — a checksum only tells
  you the bytes are wrong; repair comes from retransmission, another replica,
  reconstruction fragments, or backups, and the design must wire a mismatch
  to one of those paths.
- **Fail closed on mismatch** — a failing database page, backup chunk, or
  object read should trigger retry/replica-read/quarantine/alert, never a
  log-and-continue, because propagating corrupt bytes converts a contained
  fault into a systemic incident.
- **Granularity as a repair-precision dial** — one checksum over a huge
  object localizes nothing; chunk-level checksums (megabyte-scale) allow
  retrying or repairing just the damaged range, traded against extra metadata
  and verification work.
- **Verify on read (and periodically for cold data), not just on write** —
  write-time checks catch transfer errors only; bit rot in stored data is
  found only by read-time or scheduled scrubbing, and an unverified backup is
  an untested hypothesis.
- **Hashes double as cheap difference-finders in distributed systems** —
  replica repair via Merkle trees, content-addressable storage, dedup, and
  log-segment comparison all use digests so nodes can locate divergence
  without shipping full data.

## When to apply / trade-offs

- Adding any storage, transfer, replication, or backup path: decide up front
  where checksums are computed, where the expected values live, and what the
  mismatch handler does — otherwise the checksums are decorative.
- Choosing algorithms: CRC-32C is favored in storage/networking because it
  catches typical burst/bit-flip damage and has hardware acceleration; MD5
  and SHA-1 are collision-broken and belong only in legacy protocols, never
  new security-relevant designs.
- Multipart cloud uploads: provider ETags are not reliably a whole-object
  digest — use the provider's documented checksum fields.
- Co-locating a checksum with the data it protects can mask correlated
  failures (both damaged the same way); storage engines deliberately place
  checksums in page headers, manifests, or separate metadata depending on
  the failure class they target.
- Don't conflate with encryption: encryption hides content, checksums detect
  change; secure channels (TLS/QUIC) bundle both, but the properties are
  independent and each must be reasoned about separately.

## Fidelity check

1. Claim: IPv6 dropped the IP-layer header checksum and leans on adjacent
   layers. Support: the capture states IPv4 carries a header checksum while
   IPv6 removed it, relying on lower-layer (frame) and higher-layer (TCP/UDP)
   checks instead.
2. Claim: cache-of-expectation matters — a digest only authenticates content
   if the expected value comes from a trusted source. Support: the capture's
   package-distribution section says the digest helps only when the expected
   value originates from something like a signed release manifest,
   transparency log, or secure site.
3. Claim: cold data needs scheduled verification. Support: the capture argues
   read-time verification catches bit rot, that data unread for months must
   be checked periodically, and that a backup which is never restored or
   verified is "only a theory" — restated here as an untested hypothesis.
