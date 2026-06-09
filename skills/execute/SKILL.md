---
name: execute
description: Takes raw text/requirement, optimizes it into a precise prompt, then executes it immediately. Use when you have a rough idea and want Claude to refine and act on it in one step.
argument-hint: <your raw requirement text>
---

You received raw text from the user: $ARGUMENTS

## Step 1: Optimize into a precise prompt

Analyze the raw text and transform it into a well-structured prompt by:

1. **Clarify intent** — What exactly does the user want done? Extract the core action.
2. **Add specificity** — Fill in implicit details (file paths, technologies, scope) based on the current project context.
3. **Structure it** — Break vague requests into concrete steps.
4. **Add constraints** — Include quality bars, edge cases, and acceptance criteria the user likely expects but didn't state.
5. **Remove ambiguity** — Replace vague words ("fix it", "make it better", "clean up") with specific actions.

Output the optimized prompt in a blockquote so the user can see what you're about to execute:

> **Optimized prompt:** [the refined prompt]

## Step 2: Execute immediately

Now execute the optimized prompt as if the user had typed it directly. Follow all project rules (CLAUDE.md, mandatory workflow, etc.) and complete the task end-to-end.

Do NOT stop after showing the prompt. Do NOT ask for confirmation. Optimize and execute in one shot.
