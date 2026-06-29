---
name: dependency-verification
description: Pre-install check that a package NAME exists in its registry and is not a typosquat. Use before adding any dependency. NOT for judging worth (use library-review) or CVE audits (use dependency-scanner).
---

# Dependency Verification (pre-install name check)

> A package name the model produced is a **claim**, not a fact. The registry is the fact. Verify
> before you install. Adapted (stack-agnostic) from the MIT-licensed
> [`athola/claude-night-market`](https://github.com/athola/claude-night-market) `dependency-verification` skill.

## Why this exists

Code-generating models recommend packages that **do not exist** at a measured rate of ~5% (commercial
models) to ~22% (open models), and ~58% of the hallucinated names *recur* across reruns — so an
attacker can predict a commonly-hallucinated name, register the empty slot, and ship malware. This is
**"slopsquatting"** (the LLM-era cousin of typosquatting). A proof-of-concept package registered
against a frequently-hallucinated name drew tens of thousands of installs. The rate does *not* fall to
zero with a better model. The defense is cheap: **confirm the name exists in its registry before you
install or recommend it.**

## When to use

Before any of:
- running an install command — `pip install`, `uv add`, `npm install`, `pnpm add`, `yarn add`,
  `cargo add`, `go get`, `poetry add`, `gem install`, `composer require`, …
- writing a dependency into a manifest — `pyproject.toml`, `requirements.txt`, `package.json`,
  `Cargo.toml`, `go.mod`, `Gemfile`, …
- **recommending a package to the user in prose** (a hallucinated recommendation is still a defect).

## The two failure signals

A candidate fails verification on **either**:

1. **Nonexistent** — the name is absent from its registry (e.g. HTTP 404). Likely a hallucination.
   Do not install; find the correct name, or confirm the package was renamed/removed.
2. **Typosquat / slopsquat** — the name is one or two edits from a popular package (`reqeusts` vs
   `requests`, `python-dateutil` vs a look-alike). Either a typo or deliberate impersonation —
   restate the exact name you intend and confirm before proceeding.

## Three states (never fail closed on a network error)

| State | Registry result | Action |
|-------|-----------------|--------|
| **exists** | 200 / found | pass |
| **nonexistent** | 404 / not found | block — likely hallucination |
| **unverified** | timeout / rate-limit / offline / non-404 error | **warn only, never block** — don't fail closed on a network problem |

## Verification procedure

1. Extract the exact names the command or manifest edit would fetch (strip version specifiers/flags).
2. Confirm existence in the ecosystem's registry. A common, well-known package needn't be checked;
   verify anything unfamiliar, freshly-suggested, or near a popular name.
3. For any name close to a popular package, restate the intended name and confirm.
4. Capture the check as evidence (registry URL + HTTP status) when the install lands in a PR.

### Registry existence endpoints

| Ecosystem | URL (`{name}` = package) | Exists / Absent |
|-----------|--------------------------|------------------|
| PyPI | `https://pypi.org/pypi/{name}/json` | 200 / 404 |
| npm | `https://registry.npmjs.org/{name}` | 200 / 404 |
| crates.io | `https://crates.io/api/v1/crates/{name}` | 200 / 404 |
| other | the ecosystem's registry/index API | found / not-found |

```bash
# Prints the HTTP status: 200 = exists, 404 = does not. (PyPI shown; swap the URL per ecosystem.)
curl -s -o /dev/null -w '%{http_code}\n' "https://pypi.org/pypi/requests/json"
```

## A confidence signal, not a second gate

Once a name clears the two signals, real-world usage is a *softer* signal that the name is the
established one, not a freshly-registered impostor: GitHub dependents / code-search hits for the exact
name, repo stars + recent activity, download history (a popular-sounding name registered yesterday is
a red flag; a modest name with years of releases is reassuring). **Low usage never blocks on its own**
— new, niche, internal, and private packages are legitimately low-usage. Use it to build confidence
and disambiguate two similar names, then hand a *real* candidate to `library-review` for the full
adopt/reject evaluation.

## Where this sits (the supply-chain layers)

```
need a dep at all?      → mandatory-workflow.md §2a.5 (Reuse & YAGNI gate)
which dep, is it healthy?→ library-review skill (adopt/reject evaluation)
does this NAME exist?    → THIS skill (pre-install: hallucination/typosquat)   ◄── you are here
            install
use its CURRENT api?     → Context7 MCP (live docs) · library-skills (author-shipped, version-synced skills)
installed deps: CVEs?    → dependency-scanner agent (post-install CVE/outdated audit)
lockfile/artifact integrity? → dependency-scanner agent (supply-chain integrity mode)
```

**The "use its current API" layer** is the same root defense as the name check, one step later: the
model's memory of a library's API is also a *claim*, and it goes stale as the library releases. Ground
usage in the source — [`library-skills`](https://library-skills.io) (MIT) installs a dependency's
*author-shipped, version-synced* skills into `.claude/skills/` (managed symlinks; `uvx library-skills`
/ `npx library-skills`) for the growing set of libraries that ship them, and the Context7 MCP (live
docs) covers the rest. Both beat reconstructing an out-of-date API from training data.

**Optional enforcement:** a `PreToolUse` hook on install commands can run this check automatically
(warn-by-default; block on nonexistent/typosquat when configured). The hook is a backstop — verify
deliberately when you add a dependency rather than waiting for the gate.

## Exit criteria

- [ ] Every package in the install command / manifest edit is confirmed present in its registry, or the install is abandoned
- [ ] Any name within ~2 edits of a popular package is restated and confirmed before install
- [ ] A name that couldn't be verified online is reported as *unverified* and not silently installed
- [ ] For PR-bound installs, the registry check is captured as evidence
