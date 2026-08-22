---
source: https://martin.kleppmann.com/2016/02/08/how-to-do-distributed-locking.html
author: Martin Kleppmann (martin.kleppmann.com)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Why distributed locks need fencing tokens, and why Redlock is unsafe for correctness

## What it teaches

Kleppmann's critique of the Redis Redlock algorithm doubles as a general theory of
distributed locking. The core move is a classification question: before choosing a lock
mechanism, decide whether the lock exists for *efficiency* (avoiding duplicated work,
where a rare failure costs a few cents or a duplicate email) or for *correctness*
(where two concurrent holders corrupt state, lose data, or worse). The whole design
space flows from that answer.

For efficiency locks, one plain Redis instance with conditional-set acquire and
value-checked delete is enough — just document loudly that the lock is best-effort.
For correctness locks, no timing-based lease scheme is sufficient on its own, because
a client can be paused (GC, page fault, EBS-turned-network-read, SIGSTOP, scheduler
starvation) or its packets delayed past lease expiry, and it will then act while
believing it still holds a lock that has long since been granted to someone else.
He cites a real HBase data-corruption bug and a GitHub incident where packets sat
in the network for roughly a minute and a half.

The fix is not a better lock service but a change of contract: the *resource* must
participate. The lock service hands out a strictly monotonically increasing fencing
token on every acquisition; every write to the protected resource carries its token;
the storage side rejects any write whose token is lower than one it has already
accepted. A stale, paused client's late write then bounces harmlessly. ZooKeeper's
transaction id or node version can serve as this token. Redlock cannot produce such
a token at all — its random lock values carry no ordering — which alone disqualifies
it for correctness use.

The second half grounds this in systems theory. Sound distributed algorithms are
built for the asynchronous model: safety must hold no matter how badly processes
pause, packets stall, or clocks jump; timing may only degrade liveness. Redlock
instead bakes timing into safety — it needs bounded network delay, bounded pauses,
and well-behaved clocks (Redis key expiry uses wall-clock time, which NTP or an
admin can yank around). He walks through two concrete break scenarios: a clock jump
on one replica letting two clients each assemble a majority, and a client GC pause
spanning lock expiry so both clients believe they hold the lock. Consensus-grade
systems (ZooKeeper, Raft-family) survive these because they never let timing affect
safety.

## Key patterns & decisions

- **Efficiency-vs-correctness lock triage**: classify every distributed lock by what a
  failure costs before choosing infrastructure; the two classes need entirely different
  machinery.
- **Fencing tokens for lock safety**: monotonically increasing token issued per
  acquisition, attached to every guarded operation, enforced by the resource rejecting
  lower tokens than it has seen.
- **Resource-side enforcement**: a lock is only as safe as the storage system's
  willingness to reject stale writers; a "perfect" lock service alone cannot prevent
  paused-client races.
- **Leases over indefinite locks**: always time-limit lock ownership so a crashed
  holder cannot wedge the system — but treat the lease expiry as the exact moment the
  fencing problem begins.
- **Asynchronous-model safety discipline**: timing assumptions (clocks, delays, pauses)
  may affect liveness only, never safety; any algorithm whose correctness needs bounded
  timing is fragile in real datacenters.
- **Single-instance best-effort locking**: for efficiency-only locks, one Redis node
  with atomic conditional acquire/release beats a five-node quorum in both cost and
  honesty about guarantees.
- **Consensus systems for correctness locks**: use ZooKeeper (or equivalent
  Raft/Paxos-family coordination, or at minimum a transactional database) plus fencing
  when a lock failure would corrupt data.
- **Process pauses are unavoidable**: GC, page faults, network-backed disks, CPU
  contention, and signals mean any client can freeze at the worst possible instant;
  design so a frozen client cannot do damage after it wakes.

## When to apply / trade-offs

- Apply the triage question whenever an agent or service adds "grab a lock" logic:
  cron-style dedup and cache-warming are efficiency cases; anything guarding a
  read-modify-write of durable state is a correctness case.
- Fencing requires the downstream resource to check tokens, which not every storage
  system supports; when it doesn't, restructure the operation (idempotency,
  compare-and-set, transactions) rather than trusting lease timing.
- The middle ground is a trap: Redlock-style quorum locking is more expensive than the
  efficiency tier needs and weaker than the correctness tier demands — pick one end.
- Checking lock validity just before writing does not help, because a pause can land
  between the check and the write.

## Fidelity check

1. *Claim:* the article splits distributed locks into efficiency and correctness uses.
   *Support:* the capture frames the distinction by asking what happens if the lock
   fails — duplicated work and minor cost on one side, corrupted files, data loss, or
   a wrong drug dose on the other.
2. *Claim:* fencing tokens with resource-side rejection are the proposed safety fix.
   *Support:* the capture describes a client holding token 33 pausing, a second client
   acquiring token 34 and writing, and the storage server then rejecting the late write
   carrying 33 because it already saw a higher number; ZooKeeper's zxid or znode
   version is named as a usable token source.
3. *Claim:* Redlock's safety depends on timing assumptions that real systems violate.
   *Support:* the capture gives two failure walkthroughs — a clock jump on node C
   expiring a lock early so two clients each reach a majority, and a stop-the-world GC
   spanning expiry so both clients believe they hold the lock — plus the note that
   Redis key expiry uses wall-clock time subject to NTP steps.
