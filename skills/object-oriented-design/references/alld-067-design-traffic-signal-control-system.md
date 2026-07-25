---
source: https://github.com/ashishps1/awesome-low-level-design/blob/main/problems/traffic-signal.md
author: ashishps1 for in-repo problems
license-note: ideas absorbed in own words; no text or code reproduced
---

# Intersection traffic-light controller as a small state-machine design exercise

## What it teaches

This LLD interview problem asks you to model the software that runs the lights
at a road intersection. The interesting parts are not the data model (it is
tiny) but the behavioral concerns: a strict cyclic state machine per light,
timing that must be tunable at runtime, coordinated transitions across several
lights so that conflicting roads are never simultaneously green, and a
priority-override path for emergency vehicles that preempts the normal cycle
and then restores it.

The reference design decomposes the domain into a signal-color enumeration, a
road entity, a light entity that owns its current color plus a configurable
duration for each color, and one central coordinator object. Lights push
change notifications outward (an observer-style arrangement, so a road or a
display can react when its light flips), while the coordinator owns the
master loop that steps every light through its cycle and injects emergency
overrides. The coordinator is modeled as a singleton so exactly one authority
sequences the intersection.

## Key patterns & decisions

- **Per-entity finite state machine**: each light cycles through a closed set
  of color states; transitions are legal only in one fixed order, which makes
  invalid jumps (green straight to green on a crossing road) unrepresentable.
- **Configurable phase durations as data**: how long each color holds is a
  stored parameter per light, not a hard-coded constant, so timing can adapt
  to observed traffic without code changes.
- **Observer notifications on state change**: the light broadcasts its
  transitions to interested parties instead of those parties polling it,
  decoupling the state holder from its consumers.
- **Single central coordinator (singleton)**: one controller instance owns
  the intersection-wide schedule, preventing two schedulers from issuing
  contradictory green phases.
- **Emergency preemption channel**: the design carves out an explicit
  interrupt path for ambulances/fire trucks that bypasses the normal rotation
  — priority handling is a first-class requirement, not an afterthought.
- **Composition over inheritance for the domain**: a road *has* a light; a
  controller *has* roads; there is no deep class hierarchy.

## When to apply / trade-offs

- Reach for this shape whenever hardware-like resources cycle through phases
  under one scheduler: signal control, irrigation zones, batch job windows,
  rate-limit token refresh phases.
- The singleton coordinator is defensible here because the intersection is
  genuinely a single physical resource, but it hurts testability and would
  not survive a multi-intersection system — there you would want one
  coordinator instance per intersection plus a higher-level supervisor.
- Observer callbacks keep coupling low but make timing bugs harder to trace;
  in a safety-adjacent domain you would add an interlock check (assert no two
  conflicting greens) independent of the notification machinery.
- The problem's "smooth transition" requirement implies yellow is a mandatory
  intermediate state — a good reminder that safety margins belong in the
  state machine itself, not in caller discipline.

## Fidelity check

1. Claim: the design uses an enumeration of exactly three signal colors.
   Support: the capture lists a signal enum whose states are red, yellow, and
   green.
2. Claim: signal durations are configurable rather than fixed. Support: the
   requirements state each signal's duration must be adjustable based on
   traffic conditions, and the light entity carries per-state durations.
3. Claim: a singleton controller manages roads, runs the control loop, and
   handles emergencies. Support: the capture describes a central traffic
   controller class that follows the singleton pattern, manages roads and
   their lights, starts the control process, and deals with emergency
   situations such as approaching ambulances or fire trucks.
