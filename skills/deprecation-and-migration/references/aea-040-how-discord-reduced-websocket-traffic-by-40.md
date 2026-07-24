---
source: https://discord.com/blog/how-discord-reduced-websocket-traffic-by-40-percent
author: Discord
license-note: ideas absorbed in own words; no text or code reproduced
---

# Data-driven gateway bandwidth reduction: Discord's zstandard migration and payload-delta win

## What it teaches
How to run a compression migration (zlib to zstandard on the real-time
gateway) as a sequence of cheap, reversible experiments rather than a big
bet. Discord's method: mirror a slice of production traffic through both
codecs server-side ("dark launch") before touching any client, let metrics
kill or confirm each hypothesis, and be willing to abandon sub-ideas
(dictionaries, adaptive buffer upsizing) whose complexity outweighed measured
gains. The instrumentation also surfaced an unrelated jackpot: one dispatch
type consumed roughly a third of gateway bandwidth while being about 2% of
message count, and replacing its full-snapshot payloads with deltas cut
cluster bandwidth about 20% — more than half the total 40% saving.

## Key patterns & decisions
- **Dark launch for codec comparison** — compress a small share of live
  traffic with both algorithms server-side, record metrics, discard the new
  codec's output; iteration takes days instead of the month-plus needed to
  ship client support first.
- **Streaming (stateful) compression context per connection** — small
  payloads give a fresh compressor nothing to learn from; keeping one
  compression stream alive for the connection's lifetime let zstandard leap
  from losing to zlib to clearly beating it on both ratio and CPU time.
- **Fork-and-upstream when bindings lag** — the Elixir zstandard binding
  lacked streaming support, so they forked it, added streaming, and
  contributed the change back rather than switching stacks.
- **Tune within a memory budget** — compression parameters (window/hash/chain
  sizes) were raised only as far as would still fit contexts in existing node
  memory, treating extra hosts as a real cost against compression gains.
- **Reject marginal complexity: dictionaries** — pre-trained dictionaries
  (built from anonymized samples, one per wire encoding) helped tiny payloads
  in the lab but were mixed-to-negative in production and required shipping
  synchronized dictionaries to every client; the idea was dropped.
- **Reject marginal complexity: off-peak buffer upgrading** — a feedback loop
  upsizing compression buffers when nodes had spare memory underperformed
  because runtime memory fragmentation misled the loop; rather than tuning
  allocator internals indefinitely, they reverted it.
- **Experiment-gated client rollout** — a change that could brick the client
  went out behind a kill-switchable experiment that validated lab results and
  watched baseline metrics across platforms over months.
- **Audit bandwidth by dispatch type, not just volume** — per-type payload
  metrics exposed that periodic full-state snapshots for passive sessions
  dominated traffic; sending only what changed since the last update (a v2
  delta dispatch) dwarfed the compression work itself.
- **Privacy guard on training data** — dictionary samples were anonymized
  before training because dictionaries embed fragments of their training
  data and ship to clients.

## When to apply / trade-offs
The dark-launch pattern applies to any encoder/protocol swap where client
changes are expensive: measure server-side against real traffic first. The
deeper lesson is a cost-of-complexity discipline — two technically promising
optimizations were reverted purely because measured gains didn't justify
operational surface. Also a caution for load-test realism and metric
design: aggregate bandwidth hid the snapshot problem until per-dispatch-type
instrumentation existed. Delta-over-snapshot pushes state-tracking burden to
both ends, so it's justified when redundant snapshot bytes dominate.

## Fidelity check
1. Claim: naive per-message zstandard initially lost to zlib. Support: the
   capture shows early dark-launch results where a common message type
   averaged roughly 250 bytes under zlib but over 750 under non-streaming
   zstandard, traced to the lack of cross-message compression context.
2. Claim: dictionaries were dropped despite working on small payloads.
   Support: the capture reports a small typing-notification payload shrinking
   markedly with a dictionary, yet production results were mixed (worse for
   the flagship message type), so the added client/server coordination
   complexity wasn't judged worth it.
3. Claim: the delta dispatch was the larger contributor to the 40% figure.
   Support: the capture says the passive-session snapshot dispatch fell from
   about 35% of gateway bandwidth to 5% (about a 20% cluster-wide cut) after
   switching to change-only updates, alongside zstandard's April rollout.
