---
source: https://www.linkedin.com/blog/engineering/messaging-notifications/unifying-messaging-experiences-across-linkedin
author: LinkedIn Engineering
license-note: ideas absorbed in own words; no text or code reproduced
---

# Unifying a cross-app feature by shipping it as an internal SDK (shared data layer, thin UIs)

## What it teaches

LinkedIn runs one messaging backend but many client applications (the main
app, Recruiter, Sales Navigator, a lightweight app, and later a China jobs
app). Each product team had been re-implementing the hard client-side parts
of messaging — local mailbox state, real-time updates, failure recovery —
which made features inconsistent and slow to ship. The fix was to package the
entire messaging capability as an internal SDK with two halves: an API-side
library that host services embed, and per-platform client data-layer
libraries (iOS, Android, Web) that keep a local replica of the mailbox in
sync with the server. Product teams then build only UI on top. Reported
payoff: some screens shrank from thousands of lines to hundreds (~10x), new
messaging experiences ship in weeks instead of months, and a brand-new app
(InCareers) saved 40+ developer-weeks by adopting the SDK.

## Key patterns & decisions

- **Platform-as-SDK for a cross-cutting feature**: when several apps need the
  same complex capability, extract it into shared libraries covering both the
  server-side API integration and the on-device data layer, leaving each app
  a thin UI shell.
- **Two-library split (API library vs. client data library)**: the API-side
  library bridges client GraphQL queries to the backend platform and
  validates data arriving from adjacent systems; the client libraries own the
  local mailbox replica. Each half has a crisp contract.
- **Host-app customization via callback hooks, not forks**: the embedding
  service can inject request-permission checks, app-specific message content
  extensions, and per-app field decoration through defined callback
  interfaces. Because the library runs in-process with the host service, the
  hooks are cheap.
- **Event-driven local data layer with reactive observation**: the device
  keeps a store (SQLite on mobile, an immutable in-memory state container on
  web) that is the single source for rendering; UI code observes the store
  and re-renders on change rather than orchestrating fetches itself.
- **Dual data sources reconciled behind one store**: an on-demand GraphQL
  query path for pulling mailbox data plus a near-real-time push channel for
  new events both feed the same store, so the UI never cares which path
  delivered an update.
- **Component decomposition of the client**: store, mailbox operations API,
  reactive adapter, a real-time subscription manager, and a networking/query
  layer — the same conceptual architecture implemented natively per platform.
- **Decouple UI from data management to divide complexity**: both sides of a
  messaging client are individually hard; the data-layer boundary lets each
  be conquered separately and lets reliability work (sync recovery, missing-
  data repair) live in one place.
- **Roadmap sequencing: data layer first, reusable UI components second**:
  the team validated the shared data foundation across flagship apps before
  attempting shared UI, with a long-term goal of drop-in high-level
  components for low-customization integrations.

## When to apply / trade-offs

- Worth it when an organization has multiple sizable apps consuming the same
  interactive, real-time feature; a single-app shop gains little from the
  SDK packaging overhead.
- The SDK team becomes a dependency and potential bottleneck for every
  product team — the callback/customization surface is what keeps product
  teams unblocked, and designing it well is the hard part.
- Local-replica reactive architectures add complexity (persistence, sync,
  conflict recovery) but that complexity already existed, duplicated and
  inconsistently handled, in every client; centralizing it is the win.
- The closing argument generalizes: large multi-app organizations should
  treat apps as thin layers over reusable platform libraries rather than
  standalone codebases — a strong claim best tested on one high-value
  feature (as done here) before becoming doctrine.

## Fidelity check

1. *Claim: the SDK cut some screen implementations by ~10x.* Capture reports
   moving from upwards of 3,000 lines down to a few hundred in certain cases,
   framed as a 10x lines-of-code reduction.
2. *Claim: a new app validated the SDK's leverage.* Capture describes the
   InCareers launch (August 2022) building messaging on the SDK, saving 40+
   developer-weeks and keeping the app around one-eighth the code size of the
   legacy app it replaced.
3. *Claim: the client store is implemented differently per platform but
   behaves identically.* Capture states mobile uses a persistent SQLite-backed
   store while web keeps an immutable in-memory state managed through
   action-driven transitions (Redux-style), both observed reactively by UI.
