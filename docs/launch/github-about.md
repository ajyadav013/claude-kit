# GitHub About Panel Setup

Internal checklist for setting the GitHub repository "About" sidebar (description, topics, website).

---

## Description

Ready-to-paste candidates (kept within a self-imposed 120-character budget):

1. **Recommended:**  
   `Evidence-gated SDLC for Claude Code — gates close only on cited evidence. Stack-agnostic config, no Docker. MIT.` (113 chars)

2. **Alternative (simpler):**  
   `Autonomous SDLC pipeline for Claude Code. Spec→review→build→test→ship. Stack-agnostic config, no app code.` (106 chars)

3. **Alternative (trust-focused):**  
   `Claude Code SDLC scaffolder with quality gates that block on real evidence. Stack-agnostic config, no Docker.` (109 chars)

---

## Website

**Set to:**  
`https://pypi.org/project/claude-code-kit/`

**Rationale:** The canonical install/distribution page.

---

## Topics

Lowercase, hyphenated tags (copy-paste ready):

```
claude-code claude ai-agents sdlc agents orchestration code-review testing quality-gates workflow automation scaffold cookiecutter developer-tools python pip plugin
```

---

## Checklist (repo owner, GitHub web UI)

1. Navigate to the repository home page → click the **gear icon** next to "About" in the right sidebar.
2. Paste the chosen description (recommend option 1) and set **Website** to `https://pypi.org/project/claude-code-kit/`.
3. Add the topics from the space-separated list above → click **Save changes**.
