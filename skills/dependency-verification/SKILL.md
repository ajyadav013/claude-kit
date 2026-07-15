---
name: dependency-verification
description: Pre-install check that a package NAME exists and isn't a typosquat, plus intake vetting for third-party agent config (skills, MCP entries, hooks). NOT for judging worth (library-review) or CVE audits (dependency-scanner).
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
agent-config artifact?   → THIS skill (agent-config supply chain — intake vetting, section below)
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

## Agent-config supply chain — vetting third-party skills, agents, MCP entries, and hooks

Everything above verifies *code* dependencies. A third-party **skill, agent definition, MCP server
entry, hook script, or slash command is a dependency too** — one whose payload is *instructions your
agent will follow with your credentials*. Installing one grants it your agent's privileges
(`.claude/rules/agent-guardrails.md` §4). This section is the **canonical intake check** for any
agent-config artifact from outside your org; other skills and rules link here rather than restating it.

### Threat taxonomy — what a malicious artifact actually does

| Vector | Mechanism |
|--------|-----------|
| **Visible instruction poisoning** | The prose itself directs the agent to exfiltrate secrets, weaken checks, or add a backdoor — buried mid-file where a skim misses it. |
| **Hidden-content injection** | Instructions a human reviewer cannot see: zero-width characters, bidi overrides, Unicode Tags (U+E0000–E007F), HTML comments, data-URIs, base64 blobs the agent may later decode. |
| **Privilege-carrier abuse** | Frontmatter grants (`allowed-tools:`, a broad `tools:` list) far wider than the artifact's stated job needs. |
| **Executable payloads** | Hook scripts and lifecycle commands run *as your user* when triggered — deterministic execution, not "if the model decides to". |
| **Credential mis-routing** | An MCP entry requests env vars that don't belong to the service it fronts (your Git token handed to a "weather" server). |
| **Lookalike names** | The same typosquat economics as packages — a marketplace artifact one edit away from a popular one. |

### Intake procedure (before the artifact enters `.claude/` or `.mcp.json`)

1. **Provenance pin.** Install from a repository you can name **plus a commit SHA** (or a signed
   release/exact version) — never a moving branch or `@latest`. Record repo + SHA/version next to the
   artifact so a later compromise upstream can't silently change what you run. If a version must be
   resolved dynamically (a registry "latest" lookup at install time), resolve it **once, then pin the
   result** — the resolution is a step, not a policy.
2. **Structural read.** Open every file. Check: does the frontmatter privilege grant match the stated
   job? Are there hook scripts or lifecycle commands you didn't expect? Does any script reach the
   network or read paths outside the artifact? Does an MCP entry's command match its label?
3. **Hidden-content scan (deterministic).** One pass; any hit means read that region before install:

   ```bash
   # zero-width chars · bidi overrides · Unicode Tags · suspicious HTML comments · data-URIs · long base64 runs
   grep -rInP '[\x{200B}-\x{200D}\x{2060}\x{FEFF}]|[\x{202A}-\x{202E}]|[\x{2066}-\x{2069}]|[\x{E0000}-\x{E007F}]|<!--[^>]*(instruct|ignore (previous|all)|system prompt|do not (tell|mention))|data:[a-z/+.-]+;base64,|[A-Za-z0-9+/=]{50,}' <artifact-dir>
   ```

   (GNU grep with `-P`; `rg -n` with the same pattern works where PCRE grep is unavailable. The
   base64 alternation will hit legitimate hashes/lockfiles — a hit is *review*, not auto-reject.)
4. **Credential-ownership routing test.** For every env var an MCP entry requests: *does this
   credential belong to the service this server fronts?* A docs-search server has no business
   receiving a Git token; a DB server needs its connection string and nothing else. Any mismatch is
   an exfiltration channel, not a convenience.
5. **NEVER "load it to inspect it".** A stdio MCP entry **executes its command the moment a client
   loads the config** — adding an untrusted server to `.mcp.json` "to see what tools it has" *is*
   running the untrusted code. Inspect the artifact's files and its source repo instead; only load
   after it passes intake.
6. **License check before any vendoring.** If you copy content (not just reference it), read the
   LICENSE first — copyleft (GPL/AGPL) content cannot be vendored into a permissively-licensed
   project; reference it document-only instead.

**Scanners (referenced, not bundled):** static analyzers exist for exactly this intake —
`uvx snyk-agent-scan` (skill/agent-config scanning), NVIDIA **SkillSpector** (skill static analysis;
also available as the optional `skillspector` MCP fragment in `catalog/mcp.yaml`), and Invariant Labs'
**mcp-scan** (MCP config / toxic-flow scanning). Treat them as *additional* signals atop the manual
intake, run them as tools (mind each scanner's own license before copying its code), and remember a
clean scan does not replace the structural read — scanners lag novel attack patterns.

## Exit criteria

- [ ] Every package in the install command / manifest edit is confirmed present in its registry, or the install is abandoned
- [ ] Any name within ~2 edits of a popular package is restated and confirmed before install
- [ ] A name that couldn't be verified online is reported as *unverified* and not silently installed
- [ ] For PR-bound installs, the registry check is captured as evidence
- [ ] Any third-party agent-config artifact passed the intake procedure (provenance pin · structural read · hidden-content scan · credential-routing test) before entering `.claude/` or `.mcp.json`, and no untrusted MCP entry was loaded "to inspect it"
