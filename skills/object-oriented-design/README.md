# object-oriented-design

Class-level (LLD) design vocabulary for the before-code stage — the object model inside one process, one layer below `system-design-patterns`.

## What this covers

- **OOP pillars as decisions**: encapsulation as invariant enforcement, the abstract-class/interface/plain-class choice, composition-first, type-check ladders as a missing-abstraction smell
- **Class relationships**: the dependency → association → aggregation → composition coupling spectrum, field storage as the association threshold, unidirectional defaults, reified edge entities
- **Principles as heuristics**: SOLID one-liners with their trade-offs, knowledge-level DRY, separate-what-varies, the telescoping-constructor trigger
- **GoF pattern selection**: all 22 patterns in one problem-shape → pattern → trade-off table, framed as vocabulary and selection pressure, never targets
- **UML as communication**: what decision each diagram type communicates (class, use-case, sequence, activity, state-machine), text-first and tool-neutral, the missing-transition audit
- **Concurrency vocabulary**: mutex/semaphore/condition-variable selection, the predicate re-check loop, CAS and lock-freedom, the Coffman deadlock checklist, thread pool / producer-consumer / reader-writer shapes
- **Problem map**: 33 worked interview object models (parking lot … food delivery) mapped to their dominant patterns, with the recurring shapes named

## Origin

Own-words digests of AlgoMaster.io LLD lessons by Ashish Pratap Singh — 94 lessons and worked problems captured under `references/alld-*.md`, synthesized here in the kit's voice with no source text or code reproduced (the source repo is GPL-3.0; only ideas are restated). See `docs/lld-catalog.md` for the full source catalog.

## Structure

- `SKILL.md` — the pillars, relationships, principles, pattern table, UML guide, concurrency vocabulary, problem map, and anti-patterns
- `references/alld-*.md` — the 94 per-lesson digests, each with a fidelity check

## Usage

Read this skill when designing classes and object collaborations before writing code: carving responsibilities, choosing relationships and patterns, modeling lifecycles as state machines, or writing shared-mutable-state code. System-level architecture stays with `system-design-patterns`; Python/FastAPI-specific conventions with `design-patterns-and-conventions`; speculative-generality review with `over-engineering-review`.
