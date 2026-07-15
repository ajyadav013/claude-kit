# Supply Chain & Dependency Audits — triage tree, SBOM, reproducibility, missing patches, agent-config intake

Deep-dive reference for the `security-and-hardening` skill. Loaded on demand from SKILL.md —
the triage rules-of-thumb and review checklist live there.

## Triaging Dependency Audit Results — the decision tree

> **Supply-chain layers.** A CVE audit catches *known-vulnerable* versions — it does not catch a
> *hallucinated*, *typosquatted*, or *compromised* package. Pair it with the `dependency-verification`
> skill (pre-install: confirm the package name exists and isn't a typosquat/slopsquat) and the
> `dependency-scanner` agent's supply-chain integrity mode (post-resolve: lockfile-hash + artifact
> scanning + known-bad versions). Pre-install name check → install → CVE + integrity audit.

Not every finding is an emergency. Decision tree:

```
Vulnerability reported (dependency audit)
├── Severity: critical or high
│   ├── Is the vulnerable code path reachable in your app?
│   │   ├── YES --> Fix immediately (upgrade / patch / replace)
│   │   └── NO (dev-only dep, unused path) --> Fix soon, not a release blocker
│   └── Is a fix available?
│       ├── YES --> Upgrade to the patched version (flag major bumps as breaking)
│       └── NO --> Workaround, replace the dep, or allowlist with a review date
├── Severity: moderate
│   ├── Reachable in prod? --> Fix next release cycle
│   └── Dev-only? --> Track in backlog
└── Severity: low --> Fix during regular dependency updates
```

Editing dependency manifests requires user approval — the `dependency-scanner` recommends, the developer lane applies. Document any deferral with a reason and a review date.

## Software Bill of Materials (SBOM)

A CVE audit answers *"are any of my dependencies known-vulnerable today?"*. An **SBOM** answers a
different, complementary question: *"what exactly is in this build?"* — a machine-readable inventory of
every component and version, emitted as a standard format (**SPDX** or **CycloneDX**) so it can be
scanned, archived, and diffed later. It is a transparency/compliance artifact, increasingly required
for regulated or enterprise software, and the substrate that makes a *future* CVE or a supply-chain
incident traceable to the exact releases that shipped it.

- **Generate it in the release pipeline**, not by hand: scan the project for components → emit an
  SPDX/CycloneDX manifest → attach it to the release as an artifact. This is a build/release step,
  distinct from the pre-merge CVE audit above (both belong in CI; they answer different questions).
- **Version it with the release.** An SBOM is only useful if it corresponds to a specific build —
  store it alongside the artifact it describes so "which versions were in release X?" is answerable
  months later when a new CVE lands.
- **Pairs with the rest of the supply-chain stack:** pre-install name check (`dependency-verification`)
  → CVE + integrity audit (`dependency-scanner`) → **SBOM** for the shipped inventory.

> Stack-agnostic adaptation of SBOM generation as a release-pipeline practice from the MIT
> [`microsoft/sbom-tool`](https://github.com/microsoft/sbom-tool) (SPDX SBOM generation). Re-derived in
> prose; not vendored — the practice generalizes across SBOM tools and formats.

## Reproducible-build verification

A CVE audit and an SBOM both reason about *what you declared you depend on*. Neither catches a
**compromised build** — a published artifact that does not actually correspond to its source (a
backdoored release, a poisoned build server, the xz-style attack). The defense is **reproducibility**:
rebuild the artifact independently from its published source + metadata and verify the result is
**equivalent** to what was shipped.

- **Rebuild from declared inputs, in a clean environment.** Take the published source ref and build
  recipe and produce the artifact yourself; you are checking that *source → artifact* is the claimed
  mapping, not trusting the uploaded binary.
- **Normalize benign nondeterminism before comparing.** Builds differ in ways that aren't tampering —
  embedded timestamps, file ordering in archives, compression level, absolute build paths, locale.
  Apply *stabilizers* that canonicalize these (e.g. `SOURCE_DATE_EPOCH`, sorted archive entries, fixed
  paths) so a real divergence stands out instead of drowning in noise.
- **Attest the equivalence.** When the independent rebuild matches, record a signed attestation
  ("artifact X reproduces from source Y") and keep it with the release; a *mismatch* is a supply-chain
  incident, not a flaky build. This pairs with build-provenance/SLSA attestation and the SBOM above:
  SBOM says what's inside, provenance says where it came from, reproducibility *proves* the binary
  matches the source.
- **Where it fits:** a release-pipeline / periodic-verification step for the artifacts you publish *and*
  (where feasible) a trust check on critical third-party dependencies before you pin them.

> Stack-agnostic adaptation of reproducible-build verification (independent rebuild → stabilize benign
> differences → attest equivalence) from the Apache-2.0
> [`google/oss-rebuild`](https://github.com/google/oss-rebuild). Re-derived in prose; not vendored — the
> practice generalizes across package ecosystems and build systems.

## Missing-patch detection (source-level)

A dependency CVE audit only sees *packaged* dependencies at their declared versions. It is blind to
code you **vendored, forked, or copy-pasted** — a known-vulnerable function that was inlined into your
tree, or a fork that never picked up an upstream security fix. Version metadata can't help here because
the vulnerable code no longer carries a version. The complementary technique is **signature-based source
scanning**:

- **Derive signatures from the fix, not the version.** For a known vulnerability, the security patch
  shows exactly which code changed; turn the *vulnerable* (pre-patch) code into resilient signatures —
  line-level n-grams and function-level abstractions — so the match survives renaming, reformatting,
  and minor edits in a fork.
- **Scan your source for those signatures** (including vendored/third-party directories) and flag any
  region that matches a vulnerable pattern *without* the corresponding fix. Public vulnerability
  databases (OSV) provide the patch data to build signatures from at scale.
- **Triage like any finding:** is the matched code reachable? is the fix already applied differently?
  — then patch, re-vendor from a fixed upstream, or record a risk acceptance with a review date.

> Stack-agnostic adaptation of signature-based missing-patch detection (OSV-derived line/function
> signatures matched against source, metadata-agnostic) from the BSD-3-Clause
> [`google/vanir`](https://github.com/google/vanir). Re-derived in prose; not vendored.

## Agent-config supply chain (skills · agents · MCP entries · hooks)

Everything above audits *code* dependencies. An agent-config artifact — a third-party skill, agent
definition, MCP server entry, or hook — is a dependency whose payload is **instructions executed with
your agent's privileges**: prose the agent follows, frontmatter that grants tools, scripts that run
deterministically, env vars that route credentials. The attack surface is different (hidden Unicode
instructions, over-broad `allowed-tools:`, credential mis-routing) and so is the sharpest footgun: a
stdio MCP entry **executes its command the moment a client loads the config**, so "adding it to
inspect its tools" is already running untrusted code.

The **canonical intake procedure** — provenance pinning (repo + SHA), structural read, the
deterministic hidden-content scan, and never-load-to-inspect — lives in the `dependency-verification`
skill's *Agent-config supply chain* section. Apply it before any third-party artifact enters
`.claude/` or `.mcp.json`; this reference only records where it fits in the audit stack.

## The credential-ownership routing test

For every env var an MCP server entry (or any tool config) requests, ask one question: **does this
credential belong to the service this server fronts?** A docs-search server has no business receiving
your Git token; a database server needs its connection string and nothing else; a "utility" server
requesting cloud credentials is an exfiltration channel wearing a convenience costume. The test is
mechanical — list the requested env vars, name the service each credential authenticates to, and flag
every pair that doesn't match. Run it at intake (above) *and* whenever an update to an existing entry
adds a new env var — scope creep in a config diff is the same attack, delivered patiently.
