---
name: object-oriented-design
description: Class-level design before code — OOP pillars, class relationships, SOLID as heuristics, all 22 GoF patterns, UML diagrams, concurrency primitives, 33 worked object models. Use when designing classes and object collaborations before writing code.
---

A catalog of class-level (low-level) design vocabulary — how to carve responsibilities into classes, choose the weakest relationship that works, recognize which pattern a problem shape calls for, communicate the design in diagrams, and get shared-mutable-state code right — with 33 worked object models as reference designs.

## When to use

- Designing the classes and object collaborations for a feature before writing any code
- Reviewing a class design or PR for leaked internals, mode-flag switch ladders, or type-inspection dispatch
- Choosing between inheritance and composition, or between an abstract class, an interface, and a plain class
- Naming the pattern a problem shape calls for — and deciding whether it earns the indirection
- Modeling an entity lifecycle as a state machine and auditing its transitions before implementation
- Promoting a relationship (membership, registration, connection) to a first-class entity
- Writing or reviewing any wait/notify, locking, or shared-mutable-state code
- Auditing a shutdown path, worker pool, or pipeline for stranded waiters and deadlock conditions
- Working an LLD interview problem — the 33-problem map below links a worked object model for each
- Preparing the object-design section of a spec for `spec-driven-development` or the `/sdlc` pipeline

System-level architecture (estimation, caching, fan-out, service boundaries) belongs to `system-design-patterns`; this skill is the layer below it — the object model inside one process.

## OOP pillars as design decisions

Each pillar is a decision with a failure mode, not a definition to recite.

1. **Encapsulation is invariant enforcement at the object boundary.**
    - Group data with the only operations allowed to touch it, and encode business rules as guards inside the mutators — an order that refuses edits after submission makes the illegal state unreachable through its public surface.
    - Scattered parallel data structures can never make that guarantee; only an object that owns both the state and its rules can refuse to enter an invalid state.
    - The test of good encapsulation is not "are the fields private" but "can any caller sequence produce an invalid object."

2. **Never expose the raw backing container.**
    - Handing out an internal collection grants every caller mutation rights — one caller can wipe it — and welds all of them to the chosen representation.
    - Return copies, read-only views, or a traversal object instead; the Iterator row in the pattern table is this rule generalized.
    - The same leak happens through mutable field references: a getter returning a mutable sub-object hands out write access to state the class thinks it owns.

3. **Abstraction has three mechanisms — pick the lightest.**
    - An *abstract class* fits a family with genuinely shared behavior that subtypes specialize.
    - An *interface* fits a contract honored by otherwise unrelated types — and is what lets a consumer accept a real provider, a not-yet-written one, or a test double without changing a line.
    - A *plain well-surfaced class* with no hierarchy at all is the correct answer more often than either — the over-abstraction antidote.
    - Introduce the hierarchy when a second real implementation exists or is certain, not when one is imaginable.

4. **Composition first; inheritance when the domain insists on is-a.**
    - The default is justified by refactoring asymmetry: promoting a composed collaborator into a hierarchy later is easy, while untangling a deep inheritance tree back into composition is hard.
    - Composition swaps parts at runtime and mixes capabilities freely; inheritance locks the parent choice at compile time.
    - Reserve inheritance for true is-a relationships where subtypes honor the full parent contract — the LSP test below is the acceptance criterion.

5. **Polymorphism means the receiver chooses the behavior.**
    - One call site, many behaviors, selected by whichever concrete object receives the call; callers touch abstractions, never concrete types.
    - Its inverse is the smell: a ladder of runtime type checks followed by downcasts is dispatch written in the wrong place — each branch is a method the missing abstraction should have declared.

6. **Enums are compiler-checked domain vocabularies.**
    - A closed set of named members beats raw strings (typos the compiler cannot see) and raw integers (magic numbers nobody can read) for states, roles, and categories.
    - In most languages members carry data and behavior, turning a fragile external lookup table into a self-contained domain type.
    - Exhaustive-match handling turns a status enum into a compiler-audited state machine — the lightweight end of the state-modeling spectrum (see the UML section).

7. **Copy discipline for mutable reference fields.**
    - A shallow copy is fine for primitives and immutables; every mutable nested field must be recursively duplicated, or original and copy silently share state and mutations alias across them.
    - This is a recurring production bug class — and it is the entire hard part of the Prototype pattern.

## Class relationships

1. **The coupling spectrum, weakest to strongest:** dependency → association → aggregation → composition → interface realization → inheritance.
    - The operating heuristic: pick the weakest relationship that satisfies the need, and escalate only when the domain forces it.
    - Every step right buys guarantees (lifecycle control, structural coherence) and costs flexibility (coupling, reuse, testability).
    - The UML shorthand for the spectrum: dashed arrow (dependency), solid line (association), hollow diamond (aggregation), filled diamond (composition), triangle (realization/inheritance) — the class-diagram section below reads each of these as a coupling claim to challenge.

2. **Field storage is the association threshold.**
    - A collaborator that arrives as a method parameter, is created as a local variable, or appears only as a return type is a *dependency* — the weakest link, alive for one call.
    - The moment you cache it in an instance field, you have hardened a transient dependency into a persistent association: longer lifetime, wider class state, deeper coupling.
    - Make that promotion deliberately, in review — it is a one-line change with a relationship-class consequence.

3. **Default to unidirectional references.**
    - One-way knowledge (an order knows its payment; the payment does not know its order) suffices far more often than intuition suggests.
    - Add the reverse pointer only on demonstrated need: bidirectionality doubles the coupling and introduces a new invariant — both sides must always agree.

4. **A single mutator keeps bidirectional links in sync.**
    - When both directions are genuinely required, route every link change through one method that updates both ends atomically.
    - Letting each side set its own pointer eventually produces the split-brain state where A points to B but B points elsewhere — a bug no test on either class alone will catch.

5. **Aggregation vs composition is a lifecycle question.**
    - *Aggregation*: the whole groups parts it neither creates nor destroys — parts are shared across containers and outlive any of them (a playlist and its songs).
    - *Composition*: the whole is the sole creator, owner, and destroyer, and the part is meaningless alone (an order and its line items).
    - Decide on three axes: lifetime coupling, part reusability across wholes, and who constructs the parts. If the container manufactures and disposes of its members, the relationship has already drifted to composition regardless of what the diagram says.

6. **Promote the relationship to an entity when it acquires state.**
    - A bare reference or join is fine until the link itself needs metadata (when it formed, what role) or a lifecycle (requested → accepted).
    - Then reify it: a connection, membership, or registration object standing between the two parties, so neither references the other directly.
    - This is a recurring production modeling call — friend requests, memberships-with-roles, invitations — and the course-registration and social-network models below are worked examples.

## Design principles as heuristics

Principles are pressure gauges, not laws — each has a cost the slogan omits.

1. **SOLID, one line and one trade-off each:**
    - **SRP** — one reason to change per class, so a change's blast radius is the class that owns the concern. Overdone, it scatters one behavior across so many files that no single class explains anything.
    - **OCP** — extend by adding new types at a prepared abstraction point rather than editing tested code. The trap is preparing points speculatively: an extension seam nobody extends is indirection debt.
    - **LSP** — every subtype must honor the base contract honestly; if a subtype must stub, fake, or forbid an inherited operation, the contract is wrong — generalize it or abandon the is-a claim.
    - **ISP** — role-sized interfaces over one fat one, so clients depend only on what they use; the cost is interface proliferation, paid only when clients genuinely differ.
    - **DIP** — high-level policy depends on abstractions with implementations injected; but do not invert a dependency that never varies.
    - The five worked violation stories — a user manager bundling auth, profile, and email; a shape calculator edited per shape; a bicycle forced to implement engine-start; a fat media-player interface; an email service hard-wired to one provider — are in [alld-016-solid-principles-with-code.md](references/alld-016-solid-principles-with-code.md).

2. **Prefer injection over global access.**
    - A self-managed single instance is hidden global state: it couples callers invisibly, serializes tests through shared fixtures, and hides the dependency graph.
    - Injection is the default; the singleton is the documented exception for genuinely process-unique resources.

3. **DRY is about knowledge, not lines.**
    - Every fact the system depends on — a business rule, a config value, a schema, a threshold — gets exactly one authoritative representation, referenced from everywhere else.
    - Two textually different snippets encoding the same rule still violate DRY; when the rule changes, one of them will be missed and the modules will disagree about what is valid.
    - Two identical-looking snippets encoding *different* facts do not violate it — merging them creates the wrong abstraction. Judge duplication by what the code knows, not what it looks like.

4. **YAGNI and KISS are enforced elsewhere.** The kit's delete-list discipline for speculative generality lives in `over-engineering-review` — apply it to every pattern candidate below before adopting one.

5. **Separate what varies from what stays the same.**
    - The organizing meta-principle behind most of the pattern catalog: isolate the varying part (an algorithm, a format, a creation step) behind a stable seam so change lands in one place.
    - Strategy, Decorator, Builder, and Template Method are this principle applied at four different joints.

6. **Split along orthogonal variation axes.**
    - When one class varies along two independent dimensions, subclassing multiplies: 2 shapes × 2 renderers is 4 classes, a third renderer makes 6, and every new shape multiplies again.
    - Cut the class into two hierarchies joined by composition — one per axis — so each axis extends independently. Recognizing the two-axis shape is the whole skill; the pattern is Bridge.

7. **Recognize the telescoping constructor.**
    - Overloaded constructors of increasing arity, callers passing positional placeholder values for fields they don't care about, adjacent same-typed parameters inviting silent argument swaps.
    - That trio is the Builder trigger, and it is diagnosable at review time before it compounds.

8. **Mine the problem statement: nouns become candidate entities, verbs become candidate operations.**
    - The first-pass class model falls out of the agreed requirements text — no invention required.
    - Then design in three passes — relationships, then behavioral contracts, then a single system facade — and sweep error cases and hostile inputs last.
    - This five-step spine (from the interview-method digest) is equally the shape of the object-design section of any spec.

## GoF pattern selection

Patterns are vocabulary plus selection pressure — a shared name for a recurring problem shape and its known resolution, never a target to hit. A design's quality is measured by how little ceremony it needed, not how many patterns it cites. Three cautions govern every row:

- Reach for a pattern only when the naive design's failure mode has actually appeared or is certain to — the "Problem shape" column is the admission test, and a plain class passes it more often than any pattern.
- The composition-first default applies inside the catalog too: Strategy, Decorator, Bridge, and State are composition moves; Template Method is the inheritance variant of the same varying-step idea, and the composition form is the weaker (better-default) coupling.
- Every pattern is indirection with a maintenance bill; the needless-indirection test from `over-engineering-review` applies before adoption, not after.

Creational rows first, then structural, then behavioral.

| Problem shape | Pattern | Key trade-off | Digest |
|---|---|---|---|
| Exactly one instance must exist process-wide, globally reachable | Singleton | Global state in disguise — couples callers invisibly and poisons tests; prefer injection, keep this the exception | [alld-017-singleton.md](references/alld-017-singleton.md) |
| A shared workflow whose one varying step is which concrete object gets created | Factory Method | A parallel creator hierarchy — one creator subclass per product | [alld-020-factory-method.md](references/alld-020-factory-method.md) |
| Families of related objects that must never be mixed across families | Abstract Factory | Family coherence becomes structural, but a new product kind forces edits to every factory | [alld-023-abstract-factory.md](references/alld-023-abstract-factory.md) |
| Telescoping constructors: many optional fields, positional placeholders, silent argument swaps | Builder | A companion class per product — overkill below a handful of fields | [alld-026-builder.md](references/alld-026-builder.md) |
| Copies needed through an interface reference, or construction is costly | Prototype | Deep-vs-shallow copy discipline for every mutable field falls on the implementer | [alld-029-prototype.md](references/alld-029-prototype.md) |
| Two interfaces do the same job in different shapes and neither side may change | Adapter | One more hop — confine all translation to the seam or legacy conditionals smear through business logic | [alld-018-adapter.md](references/alld-018-adapter.md) |
| One class varying along two independent axes, subclass count multiplying | Bridge | Two hierarchies up front — speculative until the second axis actually varies | [alld-021-bridge.md](references/alld-021-bridge.md) |
| Part-whole trees where callers should not care whether they hold one item or a group | Composite | The shared contract must make sense for leaves too, or they end up stubbing child operations | [alld-024-composite.md](references/alld-024-composite.md) |
| Optional feature combinations exploding as 2^n − 1 subclasses | Decorator | Many small wrappers; deep stacks obscure identity and debugging | [alld-027-decorator.md](references/alld-027-decorator.md) |
| Every caller re-orchestrates the same multi-step subsystem | Facade | Becomes a god object if domain logic drifts into it — it should coordinate, not decide | [alld-030-facade.md](references/alld-030-facade.md) |
| Huge object counts duplicating mostly-identical state | Flyweight | Demands a strict shareable-immutable vs per-occurrence field split, designed up front | [alld-032-flyweight.md](references/alld-032-flyweight.md) |
| Access to an expensive or sensitive object needs governing, invisibly to callers | Proxy | The identical interface hides real cost and latency from the client | [alld-034-proxy.md](references/alld-034-proxy.md) |
| A ladder of independent checks needing per-deployment composition | Chain of Responsibility | Nothing guarantees any handler handles the request; the full flow is harder to read in one place | [alld-038-chain-of-responsibility.md](references/alld-038-chain-of-responsibility.md) |
| Actions that must be stored, queued, logged, scheduled, or undone | Command | One small class per action — the verb list becomes a class list | [alld-028-command.md](references/alld-028-command.md) |
| Traversal wanted without exposing the backing container | Iterator | Behavior under concurrent mutation (snapshot, live, or fail) must be chosen deliberately | [alld-019-iterator.md](references/alld-019-iterator.md) |
| N peers all reacting to each other — an N-to-N wiring mesh | Mediator | The star's center concentrates the coupling and can become the god object it replaced | [alld-036-mediator.md](references/alld-036-mediator.md) |
| Undo/rollback of object state without leaking internals | Memento | Snapshot memory cost; the history keeper must bound how much it retains | [alld-037-memento.md](references/alld-037-memento.md) |
| Many parties must react to one object's changes without it knowing them | Observer | Notification order and reentrancy are undefined; forgotten unsubscribes leak | [alld-022-observer.md](references/alld-022-observer.md) |
| Mode-dependent behavior repeating the same switch in every method | State | A class per state — past a dozen states, a transition table is the better instrument | [alld-031-state.md](references/alld-031-state.md) |
| One operation with several interchangeable algorithms, chosen at runtime | Strategy | Somebody still has to know the variants exist and pick one | [alld-025-strategy.md](references/alld-025-strategy.md) |
| An identical workflow skeleton duplicated across implementations, few steps varying | Template Method | Inheritance-locked at compile time (contrast Strategy's runtime swap); seal the skeleton or subclasses will reorder steps | [alld-033-template-method.md](references/alld-033-template-method.md) |
| Operations keep growing over a stable element hierarchy | Visitor | Double-dispatch ceremony, and a new element type forces edits to every visitor — fit only when the structure is stable and the operations are not | [alld-035-visitor.md](references/alld-035-visitor.md) |

## UML as communication

Diagrams are communication artifacts, not deliverables — each type exists to communicate one kind of decision, and a diagram that communicates no decision is decoration. Author them text-first in any text-to-diagram notation so they live in the repo, diff in review, and stay tool-neutral. Keep each one small enough to argue about.

The natural authoring order is also a design pipeline: use-case (scope) → sequence (collaboration) → class (structure) → state machine (lifecycle). Each diagram's output is the next one's input — the use case names the capability, the sequence discovers the method obligations, the class diagram records where they live, and the state machine audits the lifecycles the classes now own.

1. **Class diagram — the responsibility decision** ([alld-039-class-diagram.md](references/alld-039-class-diagram.md)).
    - Communicates which responsibilities live in which class and how tightly the classes couple, via the six relationship notations that map directly onto the coupling spectrum above.
    - Reviewing one is reviewing the coupling budget: every filled diamond and inheritance triangle is a strong claim someone should challenge.
    - Draw it after responsibilities are argued, not as a first move.

2. **Use-case diagram — the scope decision** ([alld-040-use-case-diagram.md](references/alld-040-use-case-diagram.md)).
    - States which external actors can achieve which goals; the system boundary line is its real payload — everything outside the box is explicitly not being built.
    - It deliberately says nothing about internals, which is what makes it the one diagram engineers and non-engineers can dispute honestly.

3. **Sequence diagram — the collaboration decision** ([alld-041-sequence-diagram.md](references/alld-041-sequence-diagram.md)).
    - Supplies the missing middle between a use case and a class model: the exact ordering of calls and responses that realizes one capability.
    - Storyboarding that call ordering *before* committing to classes is the bridge from requirements to class design — every message received in the diagram becomes a method some class must own, so the diagram discovers the interface obligations that the class diagram then records.

4. **Activity diagram — the workflow decision** ([alld-042-activity-diagram.md](references/alld-042-activity-diagram.md)).
    - Communicates flow of work through a process: guarded branches, genuinely parallel paths, retry loops.
    - Swimlanes assign every step to a responsible actor or component — use it when the contested question is process shape and ownership rather than object interaction.

5. **State-machine diagram — the lifecycle decision** ([alld-043-state-machine-diagram.md](references/alld-043-state-machine-diagram.md)).
    - For state-driven objects (orders, bookings, devices, sessions) it answers the question a class diagram cannot: given the object's current condition, which operations are even legal.
    - The implementation mapping is mechanical: states become enum members, transitions become one guarded advance method, and only when per-state behavior grows rich does the class-per-state ceremony of the State pattern earn its cost.
    - Its review use is the **missing-transition audit**: walk every non-terminal state against every relevant event and demand an outgoing arrow or an explicit rejection — a pre-code review that reliably surfaces mid-flow timeouts, cancellation paths, and edge cases nobody specified.

## Concurrency-primitive vocabulary

Concept vocabulary for designing object collaborations that share mutable state. For practice in this project's stack, see `async-python-patterns`; for database-level concurrency control, `python-dao-and-database`.

1. **Mutex vs semaphore vs condition variable — three different questions.**
    - A *mutex* answers "who may touch this now": exclusive ownership, one holder, and only the holder may release.
    - A *semaphore* answers "how many may proceed": counted permits with no ownership — acquiring blocks at zero, releasing never blocks and may be done by any thread. That makes it a signaling device as much as a gate, and makes a binary semaphore *not* a mutex (no owner, no reentrancy, anyone can release).
    - A *condition variable* answers "when may I continue": it parks a thread until an arbitrary predicate over shared state becomes true, and only works paired with the mutex guarding that state — the wait call atomically releases the lock and sleeps.
    - Selection test: exclusivity wanted → mutex; a count or a stored signal wanted → semaphore; an arbitrary predicate wanted → condition variable.

2. **Always re-check the predicate in a loop around a wait — never a one-shot if.** This discipline recurs in four independent lessons because it is the single most universal thread-correctness idiom.
    - Wakeups can be *spurious* (the runtime wakes a waiter with no notification), *competitive* (another thread consumed the awaited state between the notify and your wake-up), or *stale* (a broadcast reached waiters whose condition is still false).
    - The only defense is structural: hold the lock, test the predicate, wait inside a loop that re-tests on every wake, and proceed — still holding the lock — only once the predicate is genuinely true ([alld-051-condition-variables.md](references/alld-051-condition-variables.md), [alld-060-producer-consumer-pattern.md](references/alld-060-producer-consumer-pattern.md), [alld-102-design-thread-safe-blocking-queue.md](references/alld-102-design-thread-safe-blocking-queue.md)).
    - The if-check variant is the latent defect a code generator or a hurried reviewer writes by default — flag it every time.

3. **Signals need memory; use a zero-permit semaphore for one-way handoff.**
    - A condition-variable notify that fires before anyone is waiting simply vanishes; naive notification schemes are fragile for exactly this reason.
    - A semaphore created with zero permits stores the signal: the releaser banks a permit whenever it finishes, the waiter collects it whenever it arrives, and ordering between them stops mattering ([alld-058-signaling-pattern.md](references/alld-058-signaling-pattern.md)).

4. **Compare-and-swap turns blocking into optimistic retry.**
    - One indivisible instruction: check the value is what you believe, write the replacement only if so, learn you lost the race otherwise. Wrapped in a retry loop, it updates shared state with no lock at all ([alld-055-compare-and-swap-cas.md](references/alld-055-compare-and-swap-cas.md)).
    - Its trap is ABA: the value returned to what you expected via intermediate changes, so the check passes while the assumption is false.
    - Check the write's algebra before reaching for any synchronization: when writes are idempotent and monotonic — a Bloom filter's bits only ever turn on — lost updates and ABA are impossible by construction, and lock-freedom is nearly free ([alld-103-design-concurrent-bloom-filter.md](references/alld-103-design-concurrent-bloom-filter.md)).

5. **Lock granularity is a contention dial** ([alld-052-coarse-grained-vs-fine-grained-locking.md](references/alld-052-coarse-grained-vs-fine-grained-locking.md)).
    - One coarse lock over a whole structure serializes everything — a many-core machine degrades to single-core throughput even when threads touch unrelated keys.
    - A lock per element maximizes parallelism but costs memory, implementation complexity, and deadlock exposure.
    - Lock striping — a fixed pool of locks with entries hashed onto them — is the pragmatic midpoint; the right setting is a function of measured contention and workload shape, not principle.

6. **Reentrant locks and bounded acquisition.**
    - A reentrant lock tracks its owning thread and a hold count so the owner can re-acquire without self-deadlock — needed whenever a method holding the lock calls another method that takes it ([alld-053-reentrant-locks.md](references/alld-053-reentrant-locks.md)).
    - Try-lock and timed acquisition bound the willingness to wait: an instant or deadline-bounded "no" converts what would have been a hang into a recoverable decision — release what you hold, back off, retry or degrade ([alld-054-try-lock-and-timed-locking.md](references/alld-054-try-lock-and-timed-locking.md)).

7. **Deadlock prevention is the Coffman checklist** ([alld-056-deadlock.md](references/alld-056-deadlock.md)). Deadlock requires four conditions to hold simultaneously, so every prevention technique is an attack on exactly one:
    - *Circular wait* — killed by a global lock-acquisition order all threads follow.
    - *Hold-and-wait* — killed by acquiring all resources up front, or none.
    - *No preemption* — killed by try-lock with release-and-retry, making acquisition abandonable.
    - *Mutual exclusion* — killed by immutable or CAS-managed state that needs no lock at all.
    - Design reviews should name which condition the code's strategy negates; if the answer is none, the design is betting on luck. Deadlocks hide in development (low contention) and strike in production — the checklist is cheaper than the postmortem.

8. **Livelock is symmetric politeness** ([alld-057-livelock.md](references/alld-057-livelock.md)).
    - Threads that never block but never progress — perpetually yielding, retrying, and re-colliding in lockstep — look healthy on every dashboard (CPU busy, logs churning) while completions flatline.
    - It is usually born from well-intentioned resilience code: synchronized retries, polite conflict-yielding, uniform backoff.
    - The cure is breaking the symmetry, chiefly with randomized backoff jitter so contenders stop moving in unison.

9. **Three coordination shapes cover most designs.**
    - A *thread pool* amortizes thread-creation cost into a bounded worker team over a bounded queue — and forces the healthy question of an explicit rejection policy when both fill ([alld-059-thread-pool-pattern.md](references/alld-059-thread-pool-pattern.md)).
    - *Producer-consumer* absorbs speed mismatch between pipeline stages with a fixed-capacity blocking buffer whose full/empty blocking is flow control for free ([alld-060-producer-consumer-pattern.md](references/alld-060-producer-consumer-pattern.md)).
    - A *reader-writer lock* encodes "many concurrent readers or exactly one writer, never a mix" for read-dominated state — at the cost of a starvation-policy decision, since always-preferring readers can starve writers indefinitely ([alld-061-reader-writer-pattern.md](references/alld-061-reader-writer-pattern.md)).

10. **Prefer concurrent collections over hand-scattered locks — and prefer ownership over both.**
    - A concurrency-safe map or copy-on-write list delegates per-operation safety to a structure engineered for it, matched to the read/write profile; the worked models below use this as their default.
    - The delegation has a boundary: any multi-step invariant spanning two operations (check then insert, read then update) still needs a lock, CAS loop, or transaction around the pair — the collection cannot see your invariant.
    - The strongest strategy is needing neither: give each session, game, or workflow run sole ownership of its mutable state, and there is nothing to synchronize at all ([alld-088-design-a-snake-and-ladder-game.md](references/alld-088-design-a-snake-and-ladder-game.md)).

11. **Shutdown must wake every parked waiter.**
    - At end-of-stream, release every semaphore and notify every condition so blocked threads wake, observe the done flag, and exit.
    - A waiter parked on a signal that will never come is a guaranteed hang, and this broadcast is the step shutdown code most often forgets ([alld-098-fizz-buzz-multithreaded.md](references/alld-098-fizz-buzz-multithreaded.md)).

12. **Drill the vocabulary on the practice set.**
    - Strict alternation and targeted-semaphore dispatch: [alld-096-print-foobar-alternately.md](references/alld-096-print-foobar-alternately.md), [alld-097-print-zero-even-odd.md](references/alld-097-print-zero-even-odd.md) — permit-counting fundamentals in [alld-050-semaphores.md](references/alld-050-semaphores.md).
    - Ratio-constrained group formation with quota semaphores plus a rendezvous barrier: [alld-099-building-h2o-molecule.md](references/alld-099-building-h2o-molecule.md) — the same two-layer shape covers fixed-size batching and team-of-K matchmaking.
    - A TTL cache under concurrent access: [alld-100-design-thread-safe-cache-with-ttl.md](references/alld-100-design-thread-safe-cache-with-ttl.md).
    - The one-big-lock → striped locks → CAS evolution of a concurrent map: [alld-101-design-concurrent-hashmap.md](references/alld-101-design-concurrent-hashmap.md).

## Interview-problem → pattern map

Thirty-three worked object models, each digest a full design walkthrough. Use them as reference shapes when your problem resembles one — and note how few distinct shapes there actually are (recurring shapes follow the table).

| Problem | Dominant patterns | Digest |
|---|---|---|
| Parking lot | Composite containment (lot → floor → spot), spot as the unit of state, size-enum matching, singleton facade | [alld-063-design-parking-lot.md](references/alld-063-design-parking-lot.md) |
| Stack Overflow | Fine-grained entities, votes reified as objects, tags as many-to-many, reputation as derived state | [alld-064-design-stack-overflow.md](references/alld-064-design-stack-overflow.md) |
| Vending machine | State pattern for the transaction lifecycle, denomination enums, explicit failure flows | [alld-065-design-a-vending-machine.md](references/alld-065-design-a-vending-machine.md) |
| Logging framework | Strategy-seam appenders, ordered severity enum with threshold filtering, record as value object | [alld-066-design-logging-framework.md](references/alld-066-design-logging-framework.md) |
| Traffic signal control | Per-entity state machine, phase durations as data, observer notifications, emergency preemption channel | [alld-067-design-traffic-signal-control-system.md](references/alld-067-design-traffic-signal-control-system.md) |
| Coffee vending machine | Recipe-as-data, check-then-commit guarded at the inventory, fine-grained locking | [alld-068-design-coffee-vending-machine.md](references/alld-068-design-coffee-vending-machine.md) |
| Task management | Lifecycle status enum, singleton manager, concurrent collections over explicit locks | [alld-069-design-a-task-management-system.md](references/alld-069-design-a-task-management-system.md) |
| ATM | Facade over subsystems, reified transaction hierarchy, mutual exclusion at the physical dispenser | [alld-070-design-atm.md](references/alld-070-design-atm.md) |
| LinkedIn | Connections as first-class edge objects, composition over a god-object profile, typed notifications | [alld-071-design-linkedin.md](references/alld-071-design-linkedin.md) |
| LRU cache | Hash map + doubly linked list paired so each covers the other's weakness — O(1) both ways | [alld-072-design-lru-cache.md](references/alld-072-design-lru-cache.md) |
| Tic-tac-toe | Board owns state and rule queries, game as controller loop, players as thin identities | [alld-073-design-tic-tac-toe-game.md](references/alld-073-design-tic-tac-toe-game.md) |
| Pub-sub system | Topic as the decoupling point, observer at scale, fan-out on an executor rather than the publisher's thread | [alld-074-design-pub-sub-system.md](references/alld-074-design-pub-sub-system.md) |
| Elevator system | Controller dispatching to per-car request queues, direction enum, dispatch heuristic isolated in one place | [alld-075-design-an-elevator-system.md](references/alld-075-design-an-elevator-system.md) |
| Car rental | Service facade over thin entities, strategy payments, reservation as the binding entity | [alld-076-design-car-rental-system.md](references/alld-076-design-car-rental-system.md) |
| Online auction | Lifecycle enum as bid guard, append-only timestamped bid log with a cached high bid | [alld-077-design-an-online-auction-system.md](references/alld-077-design-an-online-auction-system.md) |
| Hotel management | Dual state machines (room status vs reservation status), room-type enum over subclassing | [alld-078-design-hotel-management-system.md](references/alld-078-design-hotel-management-system.md) |
| Digital wallet | Immutable transaction ledger, account (not user) as the balance unit, payment-method polymorphism | [alld-079-design-a-digital-wallet-service.md](references/alld-079-design-a-digital-wallet-service.md) |
| Airline management | Inventory/reservation manager split, booking as the tying aggregate, payment as first-class entity | [alld-080-design-airline-management-system.md](references/alld-080-design-airline-management-system.md) |
| Library management | Single registry as the only mutation path, borrowing policy enforced at the transaction boundary | [alld-081-design-a-library-management-system.md](references/alld-081-design-a-library-management-system.md) |
| Social network (Facebook) | Friend request as a two-step handshake entity, pull-model feed, copy-on-write for read-heavy lists | [alld-082-design-a-social-network-like-facebook.md](references/alld-082-design-a-social-network-like-facebook.md) |
| Restaurant management | Facade over independent domain lifecycles, order state machine, payment entity with enum tender types | [alld-083-design-restaurant-management-system.md](references/alld-083-design-restaurant-management-system.md) |
| Concert ticket booking | Per-seat state machine, two-phase reserve-then-book, contention surfaced as a domain exception | [alld-084-design-a-concert-ticket-booking-system.md](references/alld-084-design-a-concert-ticket-booking-system.md) |
| Cricinfo | Deep composite (match → innings → over → ball), ball as the atomic event, split read/update services | [alld-085-design-cricinfo.md](references/alld-085-design-cricinfo.md) |
| Splitwise | Strategy split rules, settlement as a first-class transaction, materialized pairwise balances | [alld-086-design-splitwise.md](references/alld-086-design-splitwise.md) |
| Chess | Polymorphic per-piece legality, board as the spatial truth, move as an immutable value object | [alld-087-design-chess-game.md](references/alld-087-design-chess-game.md) |
| Snake and ladder | Session-scoped state isolation, singleton session registry, snakes and ladders unified as one jump abstraction | [alld-088-design-a-snake-and-ladder-game.md](references/alld-088-design-a-snake-and-ladder-game.md) |
| Ride sharing (Uber) | Mediator-style service facade, ride state machine advanced only by service methods, concurrent pools | [alld-089-design-ride-sharing-service-like-uber.md](references/alld-089-design-ride-sharing-service-like-uber.md) |
| Course registration | Registration as association entity, capacity invariant enforced at write time | [alld-090-design-course-registration-system.md](references/alld-090-design-course-registration-system.md) |
| Movie ticket booking | Catalog/inventory split, seat as a stateful cell, booking aggregate with its own lifecycle | [alld-091-design-movie-ticket-booking-system.md](references/alld-091-design-movie-ticket-booking-system.md) |
| Online shopping (Amazon) | Cart/order separation, line-item indirection, fulfillment state machine, strategy payments | [alld-092-design-online-shopping-system-like-amazon.md](references/alld-092-design-online-shopping-system-like-amazon.md) |
| Stock brokerage | Identity/money/holdings separation, polymorphic order hierarchy, domain exceptions as rule enforcement | [alld-093-design-online-stock-brokerage-system.md](references/alld-093-design-online-stock-brokerage-system.md) |
| Music streaming (Spotify) | Three-level catalog composition, playlist as user-owned composition, manager per concern | [alld-094-design-music-streaming-service-like-spotify.md](references/alld-094-design-music-streaming-service-like-spotify.md) |
| Food delivery (Swiggy) | Three-actor entity split, menu as owned collection, order lifecycle enum, availability flags on both sides | [alld-095-design-online-food-delivery-service-like-swiggy.md](references/alld-095-design-online-food-delivery-service-like-swiggy.md) |

Recurring shapes worth internalizing, because they transfer far beyond interviews:

- **State machines dominate.** Vending machine, traffic signal, elevator, and every order/booking/ride flow reduce to a lifecycle enum plus guarded transitions — the single most reused shape in the set.
- **Reified transactions.** ATM, wallet, and Splitwise all record every change to money-like state as an explicit transaction entity rather than a silent mutation — audit trail and history come free, and the same move fits credits, quotas, and inventory adjustments.
- **Dual state machines for resource vs booking.** Hotel, concert, and movie models give the physical resource and the booking artifact separate statuses reconciled by workflows, because collapsing both into one field creates unrepresentable realities (a no-show, a cancelled-but-occupied room).
- **Immutable ledgers with derived balances.** Wallet, Splitwise, and brokerage never store a mutable balance as the only truth — the balance is a projection over append-only movement records.
- **Session-scoped isolation.** Game designs put all mutable state inside a per-session object with one owner, trading shared-structure parallelism for zero locking.
- **Two-phase holds.** Seat and booking systems make "reserved" its own state between available and committed, so contention is resolved in milliseconds and surfaced as an ordinary domain outcome rather than a lock held across a human decision.
- **Thin entities, thick coordinators.** Entities stay data-plus-guards while a manager owns the workflows across them — the models keep business rules in the entities and sequencing in the coordinator, and drift in either direction is the god-object warning sign.
- **The singleton facade is a single-process answer.** Nearly every model serializes contention through one in-process coordinator — which works exactly until the system distributes, where the same job passes to expiring holds and distributed locks (`system-design-patterns`).
- **The method itself** — interrogate requirements, extract nouns as entities, design relationships → contracts → facade, address concurrency explicitly, sweep error cases — is in [alld-062-how-to-answer-a-lld-interview-problem.md](references/alld-062-how-to-answer-a-lld-interview-problem.md).

## Anti-patterns

1. **Pattern-first design.** Choosing patterns before problem shapes exist inverts the catalog's purpose; every row above is a response to a named failure mode, not a starting move.
2. **Exposing the raw backing container.** A getter returning the internal collection grants mutation rights to every caller and welds them to the representation — return copies, views, or iterators.
3. **Runtime type-check ladders.** Repeated type inspection plus downcasting is polymorphic dispatch written in the wrong place; each branch is a method the missing abstraction should own.
4. **Bidirectional references by reflex.** Every reverse pointer doubles coupling and adds a sync invariant; default unidirectional, and when both directions are earned, route changes through a single mutator.
5. **Telescoping constructors.** Positional placeholders for unused optionals and same-typed adjacent parameters are silent-swap bait — the Builder trigger, catchable at review.
6. **The absorbing facade.** A coordinator that starts making domain decisions is a god object with better branding; facades orchestrate calls, entities own rules.
7. **A mutable balance as the only truth.** Money-like state mutated in place loses its history and its audit; store immutable movements, derive the balance.
8. **One status field for two lifecycles.** When a resource and its booking can diverge, a shared status makes real situations unrepresentable — give each its own machine.
9. **A one-shot if around a condition wait.** Spurious, competitive, and stale wakeups all break it; the predicate loop is not optional.
10. **Shutdown that strands waiters.** Ending a stream without releasing semaphores and notifying conditions leaves threads parked forever — the termination broadcast is part of the protocol.
11. **Deep inheritance for feature combinations.** Feature mixes grow 2^n − 1 subclasses; stack wrappers or compose capabilities instead.
12. **Shallow-copying mutable fields.** Original and copy silently share nested state; every mutable reference field needs a recursive copy or an immutable type.
13. **Lock scattering.** Synchronizing individual methods ad hoc instead of delegating to a concurrent structure, an ownership boundary, or one named lock discipline — and conversely, trusting a concurrent collection to protect a multi-step invariant it cannot see.
14. **Skipping the missing-transition audit.** A state machine drawn without walking every state × event pair ships its edge cases as production incidents.
15. **Association by accident.** Caching a collaborator in an instance field out of convenience silently promotes a one-call dependency into a persistent relationship — the field-storage threshold cuts both ways, and crossing it should be a reviewed decision.
16. **Speculative seams.** Extension points, hierarchies, and injected abstractions with one implementation and no second in sight — the vocabulary from `over-engineering-review` applies to every pattern in this catalog.

## References

Content synthesized from own-words digests of AlgoMaster.io LLD lessons by Ashish Pratap Singh — see `references/` (94 digests, each with a fidelity check) and `docs/lld-catalog.md` for the full source catalog. No source text or code is reproduced.

The pattern table links the 22 GoF digests and the problem map links the 33 worked models; the remaining digests group as:

- **Fundamentals** — [alld-001-classes-and-objects.md](references/alld-001-classes-and-objects.md) · [alld-002-enums.md](references/alld-002-enums.md) · [alld-003-interfaces.md](references/alld-003-interfaces.md) · [alld-004-encapsulation.md](references/alld-004-encapsulation.md) · [alld-005-abstraction.md](references/alld-005-abstraction.md) · [alld-006-inheritance.md](references/alld-006-inheritance.md) · [alld-007-polymorphism.md](references/alld-007-polymorphism.md)
- **Relationships** — [alld-008-association.md](references/alld-008-association.md) · [alld-009-aggregation.md](references/alld-009-aggregation.md) · [alld-010-composition.md](references/alld-010-composition.md) · [alld-011-dependency.md](references/alld-011-dependency.md)
- **Principles** — [alld-012-dry-principle.md](references/alld-012-dry-principle.md) · [alld-016-solid-principles-with-code.md](references/alld-016-solid-principles-with-code.md)
- **UML** — [alld-039-class-diagram.md](references/alld-039-class-diagram.md) · [alld-040-use-case-diagram.md](references/alld-040-use-case-diagram.md) · [alld-041-sequence-diagram.md](references/alld-041-sequence-diagram.md) · [alld-042-activity-diagram.md](references/alld-042-activity-diagram.md) · [alld-043-state-machine-diagram.md](references/alld-043-state-machine-diagram.md)
- **Concurrency** — [alld-050-semaphores.md](references/alld-050-semaphores.md) · [alld-051-condition-variables.md](references/alld-051-condition-variables.md) · [alld-052-coarse-grained-vs-fine-grained-locking.md](references/alld-052-coarse-grained-vs-fine-grained-locking.md) · [alld-053-reentrant-locks.md](references/alld-053-reentrant-locks.md) · [alld-054-try-lock-and-timed-locking.md](references/alld-054-try-lock-and-timed-locking.md) · [alld-055-compare-and-swap-cas.md](references/alld-055-compare-and-swap-cas.md) · [alld-056-deadlock.md](references/alld-056-deadlock.md) · [alld-057-livelock.md](references/alld-057-livelock.md) · [alld-058-signaling-pattern.md](references/alld-058-signaling-pattern.md) · [alld-059-thread-pool-pattern.md](references/alld-059-thread-pool-pattern.md) · [alld-060-producer-consumer-pattern.md](references/alld-060-producer-consumer-pattern.md) · [alld-061-reader-writer-pattern.md](references/alld-061-reader-writer-pattern.md)
- **Concurrency practice** — [alld-096-print-foobar-alternately.md](references/alld-096-print-foobar-alternately.md) · [alld-097-print-zero-even-odd.md](references/alld-097-print-zero-even-odd.md) · [alld-098-fizz-buzz-multithreaded.md](references/alld-098-fizz-buzz-multithreaded.md) · [alld-099-building-h2o-molecule.md](references/alld-099-building-h2o-molecule.md) · [alld-100-design-thread-safe-cache-with-ttl.md](references/alld-100-design-thread-safe-cache-with-ttl.md) · [alld-101-design-concurrent-hashmap.md](references/alld-101-design-concurrent-hashmap.md) · [alld-102-design-thread-safe-blocking-queue.md](references/alld-102-design-thread-safe-blocking-queue.md) · [alld-103-design-concurrent-bloom-filter.md](references/alld-103-design-concurrent-bloom-filter.md)
- **Method** — [alld-062-how-to-answer-a-lld-interview-problem.md](references/alld-062-how-to-answer-a-lld-interview-problem.md)

Neighboring skills:

- `system-design-patterns` — the layer above: HLD building blocks, estimation, fan-out, service boundaries
- `api-and-interface-design` — the contract layer these objects expose across module and network boundaries
- `over-engineering-review` — the delete-list discipline that keeps this catalog from becoming a checklist
- `code-simplification` — refactoring existing code toward the shapes taught here without changing behavior
- `async-python-patterns` — stack-level practice for the concurrency vocabulary
- `python-dao-and-database` — lock ordering, transactions, and concurrency control at the database boundary
- `spec-driven-development` — where the object-design pass (nouns → entities, sequence before classes, state-machine audit) lands in a spec
