---
source: https://algomaster.io/learn/lld/adapter
author: ashishps1
license-note: ideas absorbed in own words; no text or code reproduced
---

# Adapter: wrapping an incompatible API behind the interface your code already speaks

## What it teaches

A structural pattern for making two interfaces that "do the same thing in
different languages" cooperate without touching either side. The driving
scenario: a checkout service is coded against an in-house payment interface,
and the business mandates integrating a vendor's legacy gateway whose method
names, parameter shapes, and return types all differ. Neither the checkout code
(used system-wide) nor the vendor SDK (external) may be modified. The answer is
a thin translator class that implements the expected interface and internally
delegates to the legacy object, converting names, parameters, and types at the
boundary.

## Key patterns & decisions

- **Translator at the seam instead of conditionals in the core.** Sprinkling
  legacy-type branches through business logic couples everything to every
  integration and violates the open/closed principle; a dedicated wrapper
  confines all translation to one class.
- **Four fixed roles.** Target (the interface clients depend on), Adaptee (the
  useful-but-incompatible existing class), Adapter (implements Target, holds
  the Adaptee, translates every call and result), Client (talks only to Target
  and never learns the Adaptee exists).
- **Object adapter over class adapter.** Composition — holding a reference to
  the wrapped object — is the recommended form: it works without multiple
  inheritance, stays loosely coupled, tests easily, and can wrap any
  compatible implementation. Inheritance-based class adapters mainly suit
  languages with multiple inheritance.
- **Translation is more than renaming.** In the payment example the adapter
  renames operations, supplies a parameter the legacy status check demands that
  the target interface never exposes (the adapter remembers the reference
  number itself), and converts a numeric legacy identifier into the string ID
  the client expects (with a prefix marking its origin).
- **Adapter as a quirk firewall.** When the vendor ships a new SDK with
  different method names, only the adapter changes; the rest of the codebase is
  insulated from the churn.
- **Open for new integrations via new adapters.** The media-player example
  shows format support growing by adding one adapter per codec library, never
  by editing the player: the player keeps talking to its own interface while
  adapters bridge to third-party codec calls.

## When to apply / trade-offs

- Reach for it when integrating legacy systems or third-party libraries whose
  contracts you cannot change, or when reusing proven functionality without
  forking its source.
- Preconditions that make it the right tool: both sides are frozen, and the
  mismatch is interface shape (names/types/parameters), not missing behavior.
- The plug-adapter analogy captures the intent: you convert the connector, not
  the appliance or the wall socket.
- Costs are modest — one extra hop and one more class per integration — but a
  proliferation of adapters stacking on adapters can signal the underlying
  model needs redesign rather than more shims.
- State can live in the adapter when the two interfaces disagree about who
  tracks context (e.g., the wrapper retaining a transaction reference so the
  client-facing interface can stay parameter-free).

## Fidelity check

1. *Claim:* the pattern requires changing neither the client's interface nor
   the wrapped class. *Capture support:* the chapter's constraint list states
   the checkout service cannot be altered because it is depended on
   system-wide, and the legacy gateway cannot be altered because it comes from
   an external vendor — yet they must interoperate.
2. *Claim:* translation includes type conversion, not just method renaming.
   *Capture support:* the mismatch table shows the legacy gateway returning a
   numeric (long) reference where the target contract returns a string
   transaction ID, and the adapter bridges this by producing a prefixed string
   so callers never see the raw number.
3. *Claim:* composition is the preferred adapter form. *Capture support:* the
   capture labels the object adapter (holding a reference to the adaptee) as
   the most common and recommended approach, noting the inheritance-based
   class adapter needs multiple inheritance, which Java classes lack.
