# zustand-state-patterns

Production-tested Zustand state management conventions extracted from real frontend applications.

## What this covers

This skill encodes patterns for:

- **Typed stores** with State + Actions interfaces and StateCreator slices
- **Exported selector functions** for granular component subscriptions and computed values
- **Async actions** with loading flags, error handling, and API integration
- **Polling patterns** for real-time status updates (video generation, job progress) with cleanup
- **Optimistic updates** to provide instant UI feedback before API responses resolve
- **Session restoration** for authentication and multi-tenant workspace switching
- **Persistence middleware** for localStorage/sessionStorage with field partializing
- **HMR persistence wrappers** to preserve state during hot module replacement (dev-only)
- **Pagination state** with filters and page reset logic
- **Immutable nested updates** via spread operators

## Origins

These conventions derive from production services handling:

- Multi-tenant SaaS applications with brand/workspace context switching
- Real-time async workflows (video generation, AI chat with job polling, trend discovery)
- Authentication flows with token refresh and session restoration
- Complex UI state (modals, filters, pagination, optimistic updates)
- Developer experience optimizations (HMR persistence, devtools integration)

No internal service names, company identifiers, or proprietary details are included.

## Usage

This skill is designed for Claude Code agents scaffolding or refactoring Zustand stores in React/Next.js applications. It provides concrete patterns for common scenarios like authentication, async jobs with polling, and multi-tenant context management.

Cross-reference with `frontend-repo-architecture` for overall project structure.
