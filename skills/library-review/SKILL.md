---
name: library-review
description: Structured pre-add evaluation of a third-party dependency before adopting it — need, alternatives, maintenance, license, security. NOT for deciding if you need a dependency or auditing installed deps for CVEs.
---

# Library Review (pre-add dependency evaluation)

> Health-signal dimensions adapted (stack-agnostic, re-cast as an *adoption* decision) from the
> MIT-licensed [`wdm0006/python-skills`](https://github.com/wdm0006/python-skills)
> `reviewing-python-libraries` skill (© Will McGinnis). That skill audits a library's *own* quality
> for publishing; this one turns the same signals into a **"should we take on this dependency?"** gate.

## What this is (and is not)

Adding a dependency is a long-lived liability: it ships its bugs, its CVEs, its license, its
maintainer's availability, and its transitive tree into your project, and removing it later is rarely
free. This skill is the **structured evaluation you run before adopting a specific candidate** — or
when choosing between two or three.

It is deliberately scoped, and it composes with three things already in the kit — use those first /
alongside, don't duplicate them:

- **Do we even need a new dependency?** That is the **§2a.5 Reuse & YAGNI Gate**
  (`.claude/rules/mandatory-workflow.md`) and the `over-engineering-review` skill — walk the ladder
  (need it at all? → in the codebase? → stdlib? → native platform? → an *existing* dependency?) and
  only reach this skill once a *new* dependency is genuinely on the table.
- **Auditing dependencies you have ALREADY installed** for known CVEs / outdated versions is the
  `dependency-scanner` agent. This skill is its **pre-add counterpart** — it runs *before* the
  dependency is in the lockfile.
- The 5-point "Before adding any dependency" list in `code-review-and-quality` is the quick form;
  this skill is its full expansion.

## When to use

- A new third-party dependency is being proposed (by you or in review)
- Choosing between 2–3 candidate libraries for the same need
- §2a.5 rung 5 surfaced a *new* dependency as the cheapest option
- A dependency upgrade crosses a major version, changes its license, or changes maintainership

**When NOT to use:** deciding *whether* you need a dependency (→ §2a.5 / `over-engineering-review`);
scanning installed deps for CVEs (→ `dependency-scanner`); reviewing your *own* code (→
`code-review-and-quality`).

## Evaluation dimensions

Score each; a single hard failure (incompatible license, unpatched critical CVE, abandoned) is
disqualifying regardless of the rest.

| Dimension | What to check | Disqualifier |
|-----------|---------------|--------------|
| **Need & fit** | Does it solve the *actual* problem, not a superset? How much of its API will you really use? | You'd use 5% of a large lib for one function |
| **Alternatives** | stdlib / native platform feature / an already-installed dep / ~20 lines of your own | A cheaper rung of §2a.5 satisfies it |
| **Maintenance & bus factor** | Recent commits, release cadence, issue/PR responsiveness, number of active maintainers, is it archived/deprecated? | Abandoned (no commits ~1yr), sole unresponsive maintainer, archived |
| **Adoption & trust** | Real-world usage; downloads/dependents as *weak* signals (not popularity contests); who else relies on it | Effectively unused / no track record for critical use |
| **License** | Compatible with *your* project's license and distribution model. Copyleft (GPL/AGPL) vs permissive (MIT/BSD/Apache); transitive licenses too. A copyleft dep in a permissive project may mean *document, don't vendor* | Incompatible / missing license |
| **Security & supply chain** | CVE/advisory history *and how fast they're patched*; signed/2FA'd releases; typosquat/name-confusion check; provenance | Unpatched critical CVE; suspicious provenance |
| **Weight & transitive deps** | Install/bundle/binary size; count and quality of transitive deps (each is its own liability); platform/runtime support | Huge transitive blast radius for a small need |
| **API fit & lock-in** | Idiomatic for your stack? Type stubs/typings? How deeply would it thread through your code — i.e. exit cost? | Pervasive lock-in with no seam to swap it |
| **Operational fit** | Compatible version range with your runtime/other deps; maintenance burden of pinning/upgrading | Conflicts with existing pinned deps |

## Red flags 🚩 / Green flags ✅

**🚩** No tests · no license · last release long ago · single unresponsive maintainer · exact-pins
everything (fragile) · heavy transitive tree for a tiny need · unpatched advisories · you'd vendor
just one helper from it.

**✅** Active, regular releases · clear changelog + semver · permissive compatible license · security
scanning / signed releases · small focused surface · typings available · several reputable dependents.

## The decision

Conclude explicitly — never let a dependency slip in undecided:

1. **Adopt** — passes every dimension; pin sensibly and move on. Then use its *current* API, not the
   model's memory of it: pull the library's author-shipped, version-synced skills with `library-skills`
   (or its live docs via Context7) — see the `dependency-verification` "use its current API" layer.
2. **Adopt behind a seam** — acceptable but with real lock-in/risk → wrap it behind a thin interface
   so it can be swapped, and note the exit path.
3. **Reject** — a disqualifier fires, or a cheaper §2a.5 rung wins → record what you'll do instead.

**Adding a dependency needs user approval** (per §2a.5 rung 5 / mandatory-workflow 2a). Record the
decision and its rationale where future readers will find it — an ADR via `documentation-and-adrs`
for a consequential one, or at minimum a line in the PR / change proposal. A rejected candidate is
worth recording too, so the question isn't re-litigated.

## Quick checklist

```
- [ ] §2a.5 walked first — a new dependency is genuinely the cheapest rung
- [ ] Need & fit: solves the real problem; we use a meaningful share of it
- [ ] No cheaper alternative (stdlib / native / existing dep / a few lines)
- [ ] Actively maintained; bus factor > 1; not archived/deprecated
- [ ] License compatible with the project (incl. transitive)
- [ ] No unpatched critical/high CVEs; releases are patched promptly
- [ ] Transitive-dep weight acceptable for the value gained
- [ ] Lock-in understood; seam added if exit cost is high
- [ ] User approval obtained; decision + rationale recorded
```

## Related

- `.claude/rules/mandatory-workflow.md` (§2a.5 Reuse & YAGNI Gate) — the gate that decides *whether* a dep is needed
- `over-engineering-review` — reactive twin of §2a.5; stdlib/native/yagni lenses
- `dependency-verification` — the *pre-install* name check (does this package name even exist / is it a typosquat) that runs before this evaluation
- [`library-skills`](https://library-skills.io) (MIT) — *after* you adopt, installs the library's author-shipped, version-synced skills into `.claude/skills/` so the agent uses its current API rather than stale training-data patterns (complements the Context7 live-docs MCP); for libraries that ship skills today
- `dependency-scanner` agent — audits *already-installed* deps for CVEs + lockfile/artifact integrity (this skill's post-add counterpart)
- `code-review-and-quality` (Dependency Discipline) — the quick 5-point form of this evaluation
- `documentation-and-adrs` — record a consequential adopt/reject as an ADR
