---
name: scope
description: Generate a detailed scope document for a backlog item by analyzing the codebase, dependencies, and reference docs.
argument-hint: [backlog item number]
disable-model-invocation: true
---

Scope backlog item #$ARGUMENTS for implementation.

## Steps

1. **Read the backlog entry**: Read `docs/backlog/README.md` to find which horizon file contains item #$ARGUMENTS, then read that horizon file (e.g., `docs/backlog/now.md`) and find the item. Extract the title, priority, status, and full description.

2. **Read the scope template**: Read the [scope template](scope-template.md) to understand the output structure.

3. **Gather context**: Based on what the backlog item describes, read the relevant reference docs:
   - For domain-specific definitions: read any reference docs in `docs/reference/` that define terminology, metrics, or business rules
   - For component/UI changes: read `CLAUDE.md` for design system rules and component patterns
   - For user journey changes: read product specs or user journey documentation
   - For role/authorization changes: read architecture docs defining roles and permissions

4. **Explore the codebase**: Use the Explore agent to find the actual code that's relevant:
   - Find existing components, modules, and data files that would be modified
   - Identify data structures (schemas, models, mock data) that need changes
   - Find state management (stores, hooks, contexts) that would change
   - Look for existing patterns to follow in similar modules

5. **Check dependencies**: Look at the execution horizons in `docs/backlog/README.md` to find items that block or are blocked by this one. Check the dependency chain.

6. **Generate the scope doc**: Create a slug from the item title (e.g., "Semantic HTML Landmarks" → "semantic-html"). Write the scope document to `docs/planning/{slug}/scope.md` following the template structure. Fill in:
   - Problem statement from the backlog entry
   - Current state from your codebase exploration (with file paths and line references)
   - Target state with specific, testable outcomes
   - Component/module changes: specific components/modules to create/modify, with file paths
   - Data/schema changes: new data structures or modifications to existing ones
   - Route/endpoint changes: new or modified routes/endpoints
   - State changes: state management additions or modifications
   - Wireframes (ASCII) for any new or modified screens (frontend changes)
   - Dependencies from the backlog
   - Open questions that need human decision

7. **Summarize**: Tell the user what you wrote, list the open questions that need their input, and suggest they review the scope doc before asking for a sprint plan.

## Guidelines

- Be specific — reference actual file paths, function names, and module names from the codebase
- Don't be vague ("add a module") — name the module, its interface, and where it integrates
- Identify the riskiest parts and call them out
- If the item is too large for a single sprint, suggest how to break it into phases
- Mark the scope doc status as "Draft"
- **Frontend wireframes**: If the feature has any frontend impact (new screens, modified screens, new UI components), you MUST include wireframes in the scope doc. Use ASCII wireframes for visual review so the user can validate layout, flow, and information hierarchy before implementation.
- Adapt to the project's architecture — scope documents should reflect whether the project has a backend/frontend split, is frontend-only, is a CLI tool, is a library, etc.
