# Launch Announcement Drafts

## Show HN

### Title
Show HN: Claude-kit – autonomous SDLC config that rejects fabricated "it works" verdicts

### First Comment

I made this (MIT).

Claude-kit scaffolds an autonomous SDLC pipeline into Claude Code projects. The difference: quality gates pass ONLY on real, cited command output. A fabricated/assumed/partial-output "it works" is itself an auto-Critical finding. When a review reaches a UNANIMOUS pass, a devils-advocate agent runs and hunts for what everyone missed.

Evidence it works: examples/real-run/ is a genuine harness-captured /sdlc run (a DELETE /tasks/{id} feature on a Go task API). The devils-advocate caught and reproduced a Medium bug a unanimous review missed. The deterministic gate refused to advance until it was fixed. 7 tests / 85.2% coverage / -race clean.

What it does: /sdlc <task> drives spec → review → build → test → security → ship through profile-aware quality gates (lean/standard/enterprise). It installs configuration only — no application code, no Docker. Working memory (CONTINUITY.md) and a self-improving learnings loop (agent-memory/). 28 agents, 104 skills, 24 stack-agnostic core rules, 18 event-hook scripts. Supports React, Python/FastAPI, Go/net-http, PostgreSQL, MongoDB.

Ships two ways from one source: (1) Claude Code plugin, (2) pip package.

Install:
```
pip install claude-code-kit
claude-kit init .
```

Or:
```
/plugin marketplace add ajyadav013/claude-kit
/plugin install claude-kit@claude-kit
/sdlc <task>
```

Honest limitations: the guard hooks are convenience guardrails (need POSIX shell + jq; silently no-op without them; no-op on Windows outside WSL/Git Bash) — NOT a hardened security boundary. Most quality gates are agent protocols the model self-verifies, NOT mechanical enforcement — only the hook scripts are host-enforced. MCP servers are third-party code the kit references but does not vendor or audit.

GitHub: https://github.com/ajyadav013/claude-kit  
PyPI: https://pypi.org/project/claude-code-kit/

Feedback welcome.

---

## Reddit (r/ClaudeAI)

### Title
Built an autonomous SDLC config for Claude Code that auto-rejects fabricated "it works" verdicts — looking for feedback

### Body

I built claude-kit: an autonomous SDLC pipeline configuration for Claude Code that treats fabricated test results as a Critical bug.

The core idea: quality gates pass ONLY on real, cited command output. If an agent says "tests pass" without running the actual test command and showing the output, that's an auto-Critical finding. When a review reaches a UNANIMOUS pass, a devils-advocate agent runs and hunts for what everyone missed.

I have a real captured run (examples/real-run/) where the devils-advocate caught a Medium bug a unanimous review missed (a Go DELETE /tasks/{id} feature). The deterministic gate refused to advance until the bug was fixed. Final output: 7 tests / 85.2% coverage / -race clean.

What it does: /sdlc <task> drives spec → review → build → test → security → ship through profile-aware quality gates (lean/standard/enterprise). It installs configuration only — no application code, no Docker. It self-improves via agent-memory/ and maintains working memory in CONTINUITY.md. 28 agents, 104 skills, 24 stack-agnostic rules, 18 event-hook scripts.

Supports: React, Python/FastAPI, Go/net-http, PostgreSQL, MongoDB.

Ships as: (1) Claude Code plugin, (2) pip package (MIT license).

Install:
```
pip install claude-code-kit
claude-kit init .
```

Or:
```
/plugin marketplace add ajyadav013/claude-kit
/plugin install claude-kit@claude-kit
/sdlc <task>
```

Honest caveats: the guard hooks are convenience guardrails (need POSIX shell + jq; silently no-op without them; no-op on Windows outside WSL/Git Bash) — NOT a security boundary. Most quality gates are agent protocols the model self-verifies, NOT mechanical enforcement. MCP servers are third-party code the kit references but does not vendor or audit.

GitHub: https://github.com/ajyadav013/claude-kit  
PyPI: https://pypi.org/project/claude-code-kit/

Looking for feedback — especially if you've hit the "agent says it works but it doesn't" problem.

---

## X/Twitter Thread

### Tweet 1 (lead)
I built an autonomous SDLC config for Claude Code that treats a fabricated "it works" verdict as a Critical bug.

Quality gates pass ONLY on real, cited command output. On a unanimous pass, a devils-advocate runs and hunts for what everyone missed.

### Tweet 2 (evidence)
Real example: a Go DELETE /tasks/{id} feature. Unanimous review → PASS. Devils-advocate ran → caught a Medium bug everyone missed → reproduced it → gate refused to advance until fixed.

Final: 7 tests / 85.2% coverage / -race clean.

The run is captured in examples/real-run/.

### Tweet 3 (what it is)
/sdlc <task> drives spec → review → build → test → security → ship through profile-aware gates (lean/standard/enterprise).

Configuration only — no app code, no Docker. 28 agents, 104 skills, 24 stack-agnostic rules. React, Python/FastAPI, Go, PostgreSQL, MongoDB.

### Tweet 4 (install + link)
Install:
pip install claude-code-kit
claude-kit init .

Or: /plugin marketplace add ajyadav013/claude-kit

MIT. GitHub: https://github.com/ajyadav013/claude-kit

Caveat: hooks are convenience guardrails, not a security boundary; most gates are agent protocols.

---

## Posting Etiquette Notes

1. **Disclose authorship**: Always state "I made this" (HN) or "I built" (Reddit/X) upfront. Do not use third-person or pretend to be a neutral observer.

2. **Respond to feedback**: Monitor the thread for at least 24-48 hours after posting. Answer questions honestly. If someone finds a bug or limitation, acknowledge it — do not defend or deflect.

3. **Do not spam cross-post**: Space out posts across platforms by at least a few hours. Do not post the same content to multiple subreddits on the same day.

4. **HN-specific**: The first comment is your chance to provide context. Do not editorialize in the title. If the post gets flagged or doesn't gain traction, do not repost within 30 days.

5. **Reddit-specific**: Choose ONE relevant subreddit (r/ClaudeAI, r/MachineLearning, r/programming, r/devops). Follow the sub's rules (some ban self-promotion). Flair as "Project" or "Show and Tell" if available.

6. **X/Twitter-specific**: Do not tag unrelated accounts. Do not use trending hashtags unrelated to the project. If the thread gets engagement, continue the conversation in replies — do not spam new threads.

7. **Tone**: Stay technical and humble. If someone criticizes the approach, ask clarifying questions rather than arguing. The project's brand is anti-sycophancy — overselling in replies would undermine it.
