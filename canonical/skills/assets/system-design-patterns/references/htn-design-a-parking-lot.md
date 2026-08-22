# Digest: Design a Parking Lot

- **Source:** https://x.com/Harry_The_Nerd/status/2057821348450402614
- **Author:** Harshit Khosla (@Harry_The_Nerd)
- **Category:** LLD (Low-Level Design series #3)
- **Fetched:** 2026-07-23/24 via logged-out browser render
- **License note:** Content (c) the author; this digest is an own-words summary for internal engineering reference — no verbatim text.

## Patterns

### Base-class-plus-enum vehicle modeling
Instead of unrelated sibling classes per vehicle kind (bike, car, truck), the design uses one `Vehicle` base type whose shared attributes live in one place, with the kind expressed as an enum field. The kind still matters — it drives which spots a vehicle may occupy — but it becomes data, not a class-hierarchy explosion. Use this whenever variants differ only by a discriminating attribute rather than by behavior; the trade-off is that genuinely divergent per-type behavior later would push you back toward polymorphism.

### Per-type availability index (map of type → priority queue)
Free-spot tracking is a `Map<VehicleType, PriorityQueue<Spot>>` held by the lot. Looking up the right queue for a vehicle's type is O(1); pulling the best spot is O(log n) on reinsertion — a clear win over scanning every spot in every floor, which is O(n). This is the article's core data-structure insight: index availability by the attribute you match on, so assignment never walks the whole inventory. Trade-off: the index is a second source of truth about occupancy and must be kept consistent with the spots themselves on assign/release.

### Nearest-first ordering via a comparable spot
Spots implement a natural ordering keyed on floor number, so the priority queue automatically yields the lowest-floor free spot: O(1) to fetch the head, O(log n) to push a released spot back. Encoding the allocation policy ("closest floor wins") in the element's comparison logic means the container enforces the policy for free. The trade-off is that changing policy (e.g., prefer spots near an elevator) means changing the ordering or supplying a different comparator.

### Billing as a standalone single-responsibility service
Fee calculation lives in its own `BillingService`, which consumes a spot (carrying entry timestamp and hourly rate) plus an exit time. Neither `Spot` nor `ParkingLot` grows billing logic — pricing rules can evolve (or be tested) without touching allocation code. Standard SRP application: the cost is one more class, the benefit is an isolated seam for the part of the system most likely to change (pricing).

### Deliberately thin entities ("dumb container" floor)
`Floor` is nothing but a holder of spots; it does not know which are free. All availability bookkeeping is centralized in `ParkingLot`. Concentrating the mutable coordination state in one owner keeps the smaller entities trivial to reason about and avoids split-brain availability data. The trade-off is a fatter lot class — acceptable here because there is exactly one coordination concern.

### Explicit aggregation-vs-composition lifecycle mapping
The relationships are typed by lifetime: lot→floor and floor→spot are composition (a floor or spot has no existence outside its container), while spot→vehicle is aggregation (a vehicle exists independently and is merely parked). Making ownership semantics explicit up front tells you what cascades on deletion and what is only a temporary reference — a cheap modeling discipline that prevents lifecycle bugs later.

## Not absorbed

- Series branding ("Low-Level Design series #3") — interview-prep framing, no engineering content.
- Closing call to like, comment, repost, and share — engagement promotion.
- Post metadata (timestamp, view/like/reply counters) — platform noise, not article content.

## Fidelity check

- **Post count in capture:** 1 (single long-form post; `postCount: 1` in the JSON).
- **Article outline as authored:**
  1. Overview (Problem statement)
  2. Entities & Classes — 1. Vehicle (Base Class + Subtypes)
  3. Entities & Classes — 2. Spot Class
  4. Entities & Classes — 3. Floor Class
  5. Entities & Classes — 4. ParkingLot Class
  6. Entities & Classes — 5. BillingService Class
  7. Class Relationship Summary (Aggregation vs Composition)
  8. Key design decisions
  9. Sign-off
- **Pattern → section citations:**
  - Base-class-plus-enum vehicle modeling → "1. Vehicle (Base Class + Subtypes)" and the "Key design decisions" list.
  - Per-type availability index → "4. ParkingLot Class" and "Key design decisions".
  - Nearest-first ordering via a comparable spot → "4. ParkingLot Class" and "Key design decisions" (Comparable bullet).
  - Billing as a standalone single-responsibility service → "5. BillingService Class" and "Key design decisions".
  - Deliberately thin entities → "3. Floor Class" and "Key design decisions" (dumb-container bullet).
  - Aggregation-vs-composition lifecycle mapping → "Class Relationship Summary".
- **Capture caveats:** the ParkingLot section reads as if a code snippet or image followed "It uses:" — the text render carries only prose, so any class-diagram/code images in the original post were not captured. Complexity figures (O(1) lookup/fetch, O(log n) assignment/reinsert, O(n) scan baseline) are restated as facts from the text.
