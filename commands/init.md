---
description: Scaffold the claude-kit SDLC config (CLAUDE.md + .claude/rules, agents, skills, hooks) into this project
argument-hint: '[target-dir] [--defaults] [--force]'
allowed-tools: Skill
---

Invoke the `ckit-command-init` skill and follow it to completion. Forward the caller's request unchanged as `$ARGUMENTS`. This wrapper is only the stable legacy slash-command alias; the generated skill is the behavior-bearing implementation.
