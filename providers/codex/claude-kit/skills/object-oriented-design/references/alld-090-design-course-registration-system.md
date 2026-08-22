---
source: https://github.com/ashishps1/awesome-low-level-design/blob/main/problems/course-registration-system.md
author: ashishps1 for in-repo problems
license-note: ideas absorbed in own words; no text or code reproduced
---

# Course registration: capacity enforcement under concurrent contention

## What it teaches

The essence of this problem is a bounded resource fought over by concurrent
actors: each course has a fixed seat count, many students race to claim
seats, and the system must never oversell. The entity model is a textbook
many-to-many: students on one side, courses on the other, and a registration
record reifying the link between them with a timestamp — the association
itself becomes a first-class object so it can carry metadata and be queried
independently.

Courses carry their identity (code, name, instructor) plus two numbers that
define the invariant: maximum capacity and current enrollment count. The
enforcement rule is simply that enrollment may never exceed capacity, and
the entire design exists to keep that true when requests arrive
simultaneously.

The concurrency strategy is two-layered. Read-heavy shared collections (the
course catalog, the registration list) use thread-safe structures suited to
their access pattern — a concurrent map for keyed lookup, a copy-on-write
list for iterate-mostly data. But the critical section — checking remaining
capacity and then enrolling — is guarded by mutual exclusion on the
registration operation itself, because a check-then-act sequence cannot be
made safe by thread-safe collections alone. This is the design's sharpest
lesson: concurrent containers protect single operations; compound invariants
need an atomic critical section.

Around that core, the system is a singleton facade offering course/student
management, search by code or name, registration, and per-student enrollment
lookup, with an observer-style hook stubbed in for pushing enrollment
changes to interested parties such as a UI.

## Key patterns & decisions

- Association entity: the student-course link is reified as a registration
  record with a timestamp, not a bare foreign-key pair.
- Capacity invariant enforced at write time: reject enrollment when a course
  is full — the one rule the whole design defends.
- Synchronized critical section for check-then-enroll, because
  capacity-check-plus-insert is a compound action no lock-free collection
  makes atomic on its own.
- Collection choice matched to access pattern: concurrent map for the keyed
  catalog, copy-on-write list where reads dominate writes.
- Singleton facade exposing the full use-case surface (add, search,
  register, list-my-courses) as the single consistency authority.
- Observer hook (stubbed) for broadcasting enrollment changes, keeping
  presentation concerns out of the domain core.
- Extensibility called out as an explicit requirement — the flat entity
  model leaves room for waitlists, prerequisites, or drop/swap flows.

## When to apply / trade-offs

This is the miniature of every finite-inventory allocation problem: event
tickets, warehouse stock, seat booking, API quota grants. The transferable
rule is to identify the compound invariant (available count vs. claims) and
give it one atomic guardian, whether that is a synchronized method, a
database transaction with a conditional update, or an atomic
compare-and-set. Trade-offs: a single synchronized registration path
serializes all enrollments across all courses — correct but coarse; per-
course locking or optimistic conditional writes would restore parallelism.
Copy-on-write lists degrade badly if writes become frequent (registration
day is exactly a write burst), so the "reads dominate" assumption deserves
scrutiny. And as with the other problems in this series, the in-process
singleton stands in for what would be a transactional datastore in a real
deployment.

## Fidelity check

1. Claim: the registration link is modeled as its own timestamped entity.
   Support: the capture describes a registration class that associates a
   student with a course and records the moment of registration.
2. Claim: the enroll path is made thread-safe with mutual exclusion, not
   just concurrent collections. Support: the capture states the
   course-registration method is synchronized to stay safe when many
   students register at once, on top of concurrent map and copy-on-write
   list usage for shared data.
3. Claim: the system must refuse enrollment beyond a course's seat limit.
   Support: the capture's requirements say registration must be prevented
   once a course reaches its maximum enrollment capacity, and the course
   entity tracks both capacity and current enrolled count.
