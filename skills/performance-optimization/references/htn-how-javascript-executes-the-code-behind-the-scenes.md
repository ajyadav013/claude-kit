# Digest: How JavaScript Executes The Code - Behind The Scenes

- **Source:** https://x.com/Harry_The_Nerd/status/2075158256826335454
- **Author:** Harshit Khosla (@Harry_The_Nerd)
- **Category:** Engineering Articles
- **Fetched:** 2026-07-23/24 via logged-out browser render
- **License note:** Content (c) the author; this digest is an own-words summary for internal
  engineering reference — no verbatim text.

The article walks the V8 execution pipeline (Chrome / Node.js) end to end: plain-text source
through tokenizer, parser, bytecode interpreter, profiler, and optimizing JIT, plus the
object-model machinery (hidden classes, inline caches) that makes dynamic property access fast.

## Patterns

### Lexical analysis (tokenizing)
The first pipeline stage scans the raw source character stream and emits typed tokens
(keywords, identifiers, literals, operators, punctuation), discarding whitespace and comments.
It assigns no meaning — it only segments text. Use this mental model whenever building any
language tooling: tokenizing is a cheap, meaning-free preprocessing step that everything
downstream depends on. Trade-off: none within JS itself; it is the mandatory entry cost of
turning text into structure.

### Parsing into an Abstract Syntax Tree
The parser consumes the flat token list and produces a tree whose nodes correspond to the
grammatical constructs of the program (statements, expressions, declarations). The AST is the
shared substrate for the whole ecosystem — transpilers and linters (Babel, ESLint) operate by
producing and traversing this same structure. Relevant whenever writing codemods, custom lint
rules, or static analysis: work at the AST level, not with regexes over text.

### Lazy (two-pass) parsing
V8 does not fully parse everything up front. A fast pre-parse skims function bodies —
functions not invoked immediately are skipped — and the expensive full parse is deferred until
a function is actually about to run. This is why engines cold-start quickly even on very large
bundles: parse cost is paid proportionally to code that executes, not code that ships.
Engineering takeaway: shipping dead code still costs pre-parse time and bytes, but its full
parse cost is largely avoided. Trade-off: work is deferred, not eliminated — first invocation
of a lazily parsed function pays the parse latency then.

### Bytecode as the interpretation target (Ignition)
Rather than walking the AST at runtime (slow: pointer chasing and node-type dispatch on every
step), V8's Ignition interpreter first lowers the AST into a compact, engine-specific bytecode
— register-style instructions on the order of load-constant / add-registers / store-to-local.
Bytecode is fast to generate and fast to begin executing, which is what lets JS start running
near-instantly instead of waiting on an ahead-of-time compile the way C++ does. Trade-off:
bytecode interpretation has per-instruction overhead, so it is a startup-latency win, not a
steady-state throughput win.

### Runtime profiling / type feedback
While interpreting, the engine records how the code actually behaves: which value types flow
into each function, which functions are invoked often enough to count as hot, and what
structural shapes objects have. This feedback is the input that makes speculative optimization
possible later. The general pattern — run cheaply first while gathering evidence, then invest
optimization effort only where the evidence justifies it — generalizes well beyond JS engines
(e.g., profile-guided optimization, adaptive caching).

### Tiered JIT compilation (TurboFan)
When profiling identifies a hot function, the optimizing compiler (TurboFan) recompiles it —
from bytecode plus the accumulated type feedback — into native machine code specialized to the
observed behavior. If a function has only ever seen numeric arguments, the emitted code can
drop JS's dynamic type checks and do raw arithmetic. Use-when framing: this is the canonical
resolution of the interpreter-vs-compiler trade-off — interpreters start fast but run slowly;
ahead-of-time compilers run fast but start slowly; a tiered engine starts in the interpreter
and promotes only hot paths to compiled code. Trade-off: the speed comes from assumptions that
can be invalidated (see deoptimization), and compilation effort is wasted on code that runs
once.

### Deoptimization (speculation bailout)
Because JS is dynamically typed, the JIT's specializations are bets. If an optimized function
is later called in a way that violates its assumptions (a string arrives where only numbers
were observed), the engine discards the machine-code version and drops back to bytecode
interpretation rather than compute wrong results; the function can be re-optimized once its
behavior stabilizes. Practical consequence for application code: keep argument types and
object shapes consistent — monomorphic call sites stay optimized, while type churn causes
repeated bailout/reoptimize cycles.

### Hidden classes (shapes)
JS objects have no declared layout, but V8 internally assigns each object a hidden class
derived from its property set and the order properties were added; objects built identically
share one. This lets the engine treat objects like fixed-layout structs with known field
offsets instead of doing a hash-map lookup per property access. Coding implication: construct
objects with the same properties in the same order (and avoid adding/deleting properties
post-construction) so they share shapes.

### Inline caching
For a repeated operation like reading a specific property, the engine caches the resolved
property offset keyed on the hidden class seen at that call site, so subsequent accesses jump
straight to the memory location. Combined with shared hidden classes, this turns the hottest
operation in typical JS — property access — into near-constant-time work. Trade-off: the
cache pays off only while the site keeps seeing the same shape; polymorphic sites degrade.

### Microbenchmark validity caveat
Because hot code is promoted to optimized machine code and cold code never leaves the
interpreter, code executed once and code executed thousands of times in a loop run under
different execution regimes. A one-shot timing measures interpreter behavior; a tight-loop
timing measures JIT-optimized behavior. When benchmarking JS, account for warm-up or the
numbers describe the wrong tier.

## Not absorbed

- Opening framing ("JS looks simple on the surface... let's break this down, folks") —
  motivational lead-in, no technical content.
- The "gets broken into tokens like" example placeholder — the referenced code line did not
  survive the text render (likely an embedded image); the token list itself was captured and
  absorbed above.
- The AST "becomes something like:" placeholder — the tree diagram is likewise missing from
  the capture; nothing to absorb beyond the concept.
- Closing sign-off ("That's all, folks..Cheers!!") and engagement metrics (views/likes) —
  social boilerplate.

## Fidelity check

- **Post count in capture:** 1 (single long-form article post; `postCount: 1` in the JSON,
  no `---AUTHOR-POST-BREAK---` separators present).
- **Article outline as authored:**
  1. Intro (untitled)
  2. Stage 1: The Source Code
  3. Stage 2: Lexical Analysis (Tokenizing)
  4. Stage 3: Parsing and the Abstract Syntax Tree (AST)
  5. Stage 4: From AST to Bytecode
  6. Stage 5: Interpretation Begins
  7. Stage 6: The JIT Compiler Kicks In
  8. Stage 7: Deoptimization (The Safety Net)
  9. Stage 8: Hidden Classes and Inline Caching
  10. Putting It All Together
- **Pattern-to-section citations:**
  - Lexical analysis (tokenizing) — Stage 2
  - Parsing into an Abstract Syntax Tree — Stage 3
  - Lazy (two-pass) parsing — Stage 3 (V8 pre-parse discussion)
  - Bytecode as the interpretation target (Ignition) — Stage 4
  - Runtime profiling / type feedback — Stage 5
  - Tiered JIT compilation (TurboFan) — Stage 6, with the start-fast/run-fast trade-off
    restated in "Putting It All Together"
  - Deoptimization (speculation bailout) — Stage 7
  - Hidden classes (shapes) — Stage 8
  - Inline caching — Stage 8
  - Microbenchmark validity caveat — "Putting It All Together"
