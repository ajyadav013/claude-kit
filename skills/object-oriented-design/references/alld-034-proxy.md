---
source: https://algomaster.io/learn/lld/proxy
author: algomaster.io (AlgoMaster / ashishps1)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Proxy: an interface-identical stand-in that governs access to an expensive or sensitive object

## What it teaches

The chapter starts from an image-gallery app that eagerly constructs a heavyweight
high-resolution image object for every thumbnail at startup. Because loading happens in the
constructor, the app pays disk I/O and memory for images the user may never open — slow startup
and wasted resources that get worse with gallery size. A second, subtler problem: any
cross-cutting need (logging views, permission checks, caching) would have to be bolted onto the
image class itself, entangling data management with loading policy and violating single
responsibility.

The Proxy pattern's answer is a surrogate object that implements the exact same interface as the
real one, so the client cannot tell (and does not need to know) which it holds. The proxy
intercepts every call and decides what to do: answer cheaply itself (e.g., return a stored
filename without loading anything), lazily construct the real object on first expensive use, block
the call on policy grounds, or wrap it with extra behavior before delegating. In the gallery
refactor, the proxy stores only a filename; the real image is built the first time a display is
requested, and subsequent displays reuse the already-built instance — turning a multi-second
startup near-instant and skipping load entirely for never-viewed images, with zero edits to the
real image class or the client's interface usage.

The chapter then catalogs proxy flavors sharing one structure: virtual (lazy creation), protection
(authorization gate), remote (network stand-in for a distant object), caching (memoize expensive
results), and smart (logging/monitoring/reference counting). Two design points stand out. First,
when a protection proxy needs user context, resist widening the shared interface's method
signature — inject the user role through the proxy's constructor so the interface contract stays
clean. Second, proxies compose: a logging proxy can wrap a virtual proxy, each layer owning
exactly one concern, decorator-style stacking through the common interface.

## Key patterns & decisions

- Interface-preserving surrogate: proxy and real subject implement the same interface, making them
  interchangeable to the client and the substitution invisible.
- Virtual proxy / lazy initialization: defer expensive construction until the first call that
  actually needs the real object, then cache the instance for reuse.
- Cheap-path short-circuit: the proxy answers metadata queries from its own lightweight state
  without ever materializing the real subject.
- Protection proxy with constructor-injected context: pass identity/role into the proxy at build
  time rather than polluting the shared interface's method signatures.
- Caching proxy: memoize results keyed by request so repeated identical calls skip the slow
  backend, with an explicit invalidation operation.
- Smart/logging proxy: bracket delegated calls with audit or timing instrumentation, leaving the
  real class untouched.
- Proxy stacking for concern separation: nest proxies (logging around lazy-loading) so each layer
  handles a single cross-cutting concern.
- Loading policy extracted from the data class: eager-vs-lazy, cached-vs-fresh, and
  allowed-vs-denied decisions live in the proxy, restoring single responsibility.

## When to apply / trade-offs

Reach for a proxy whenever direct access to a resource-heavy, remote, or sensitive object is
undesirable: databases, third-party APIs, filesystems, large in-memory assets. The chapter's
second domain example is a database-service caching proxy where a first query pays simulated
backend latency, an identical repeat returns immediately from cache, and clearing the cache
restores the miss path — all behind an unchanged service interface. Costs to weigh: an extra
indirection layer per call, proxy classes that must faithfully track the subject interface as it
evolves, and hidden state (lazy instances, cache entries) that can surprise callers about timing
and freshness. The pattern shines when you need behavior added around an object you cannot or
should not modify.

## Fidelity check

1. Claim: the lazy proxy avoids paying for never-used resources. Support: in the refactored
   gallery walkthrough one image is never displayed and therefore never loaded, saving its ~10MB,
   while startup drops from about six seconds to near-instant.
2. Claim: protection concerns should not distort the shared interface. Support: the capture
   explicitly warns against adding a user-role parameter to the display method and instead routes
   the role through the proxy constructor, keeping the interface contract intact; the example
   blocks non-admin users from files flagged as confidential by name.
3. Claim: proxies are stackable, one concern per layer. Support: the text shows a logging proxy
   wrapping the virtual proxy so the logger records the call and then delegates to the lazy
   loader underneath.
