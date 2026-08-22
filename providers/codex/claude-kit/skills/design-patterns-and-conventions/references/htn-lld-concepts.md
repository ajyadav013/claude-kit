# Digest: LLD Concepts (Low-Level Design series #1 — The Foundation)

- **Source:** https://x.com/Harry_The_Nerd/status/2055635966568620167
- **Author:** Harshit Khosla (@Harry_The_Nerd)
- **Category:** LLD
- **Fetched:** 2026-07-23/24 via logged-out browser render
- **License note:** Content (c) the author; this digest is an own-words summary for internal
  engineering reference — no verbatim text.

The article is a primer arguing that low-level design rests on three stacked layers — object
orientation, the SOLID principles, and classic design patterns — and walks through each layer
briefly. Illustrative code was apparently attached as images/snippets that did not survive the
text capture, so only the prose descriptions are summarized here.

## Patterns

### Encapsulation
Keep a class's state and the operations on that state together, and block outside code from
reaching the internals directly — all mutation flows through a controlled surface (the author's
example is a bank-account balance only reachable via methods). Use it everywhere state has
invariants to protect; the trade-off is a bit more ceremony (accessors/methods) in exchange for
integrity guarantees.

### Abstraction
Expose only the operations a caller needs and bury the mechanics behind an interface or abstract
type. The article's example: callers program against a generic payment-processor contract and
never learn whether Stripe, Razorpay, or PayPal sits behind it. Use it at seams where the
implementation may vary; the cost is an extra indirection layer to maintain.

### Inheritance (with a composition caveat)
A subclass reuses a parent's fields/behavior and layers on specialization (an electric car
inherits movement and adds battery charging). The author explicitly warns that inheritance only
fits genuine "is-a" relationships and that composition should be preferred otherwise — a
mainstream but important trade-off call.

### Polymorphism
A single interface with multiple runtime implementations: calling code iterates over abstract
shapes and invokes an area computation without knowing the concrete type; dispatch resolves the
right method at runtime. This is what makes the abstraction layer above actually pay off.

### Single Responsibility Principle
Each class should have exactly one axis of change. The example: isolating email formatting in
its own service means a template tweak touches nothing else. Benefit is blast-radius control;
over-applied it fragments code into confetti (the article does not discuss that failure mode).

### Open/Closed Principle
Grow behavior by adding new units of code rather than editing proven ones — e.g., a new discount
type becomes a new class instead of a modification to the existing price calculator. Reduces
regression risk in stable code at the cost of designing extension points up front.

### Liskov Substitution Principle
Any subclass must be usable wherever its parent is expected without changing observable
correctness. The author frames a contract-breaking subclass as evidence the inheritance
relationship itself is wrong — a useful design smell test.

### Interface Segregation Principle
Prefer several narrow, purpose-specific interfaces over one broad one, so no implementer is
forced to stub out methods it has no use for. Keeps contracts honest; the cost is more interface
types to name and track.

### Dependency Inversion Principle
Both the orchestrating layer and the detail layer should point at an abstraction instead of the
orchestrator importing the concrete detail. The example: an order service that talks to a
database abstraction can have MySQL swapped for MongoDB with zero changes to the service.
This is the principle that makes testing with fakes and vendor swaps cheap.

### Singleton (creational)
Guarantee a single application-wide instance of a class. The article lists typical homes:
loggers, database connection managers, configuration holders, caches. (It does not cover the
well-known downsides — hidden global state, test coupling.)

### Factory (creational)
Centralize construction so clients never call constructors directly; the factory picks the
concrete type. Claimed benefits: looser coupling, easier scaling to new types, tidier creation
code. Pairs naturally with Open/Closed — new products mean new factory cases, not client edits.

### Builder (creational)
Assemble a complex object incrementally through a staged API, valuable when a class carries many
fields and telescoping constructors would get unwieldy.

### Adapter (structural)
Wrap one interface so it satisfies another, letting components that were never designed together
interoperate (the physical analogy given is a plug/charger adapter). Benefits claimed: better
compatibility, reuse of existing code, fewer dependency headaches.

### Decorator (structural)
Layer extra behavior onto an object at runtime without altering its class — the article's
example adds milk to a coffee object dynamically. Good for stackable, optional features; the
capture's code output line hints at the example but the code itself was not in the text.

### Facade (structural)
Put one simplified entry point in front of a tangle of subsystems so callers do not have to know
each internal piece. Trades a little flexibility for a much smaller public surface.

### Observer (behavioral)
One publisher, many auto-notified subscribers — a one-to-many dependency where a state change
fans out to every registered listener. Cited applications: subscription feeds (YouTube-style),
notification systems, UI event listeners.

### Strategy (behavioral)
Make an algorithm a swappable, runtime-selected component. Cited applications: payment method
selection, pluggable sorting, switching authentication providers. Complements Open/Closed and
Dependency Inversion: new strategies are new classes behind a stable interface.

### The three-layer mental model
The article's connective thesis: OOP supplies the raw material (classes/objects), SOLID supplies
the rules for arranging that material safely, and patterns supply pre-proven arrangements for
recurring problems. A reasonable pedagogical frame for onboarding docs, though not a novel
technique in itself.

## Not absorbed

- Interview-prep framing (positioning parking lot / chess / ride-sharing as interview questions
  and patterns as interview staples) — career-coaching context, not engineering content.
- Series promotion and next-episode teaser (a future Parking Lot System walkthrough with class
  diagrams and Java code) — advertisement for content that isn't in this article.
- Sign-off line and engagement counters (views/likes/reposts) — social chrome.
- Java-specific asides (abstract classes/interfaces as "the Java way") — language trivia; the
  concepts are language-agnostic and are summarized that way above.

## Fidelity check

- **Post count in capture:** 1 (a single long-form article post; `postCount: 1` in the JSON).
- **Article outline as authored:**
  1. Intro — "The Foundation" (what LLD is; the three fundamentals to master)
  2. Section 1: Object-Oriented Programming — Encapsulation, Abstraction, Inheritance,
     Polymorphism
  3. Section 2: SOLID Design Principles — S, O, L, I, D subsections
  4. Section 3: Design Patterns — three categories:
     - Creational: Singleton, Factory, Builder
     - Structural: Adapter, Decorator, Facade
     - Behavioral: Observer, Strategy
  5. "How it all connects" — the layered summary
  6. Closing teaser for series article #2
- **Pattern-to-section citations:**
  - Encapsulation, Abstraction, Inheritance, Polymorphism → Section 1 (OOP), respective pillar
    subsections.
  - Single Responsibility, Open/Closed, Liskov Substitution, Interface Segregation, Dependency
    Inversion → Section 2 (SOLID), respective lettered subsections.
  - Singleton, Factory, Builder → Section 3, Creational category.
  - Adapter, Decorator, Facade → Section 3, Structural category.
  - Observer, Strategy → Section 3, Behavioral category.
  - Three-layer mental model → "How it all connects" section.
- **Capture caveats:** the prose repeatedly narrates code examples (bank balance, shape loop,
  coffee-with-milk output) whose actual code blocks/images are absent from the text render; one
  paragraph in Section 3 is duplicated in intent (the category list appears twice); no numeric
  capacity estimates or algorithm parameters appear anywhere in the article.
