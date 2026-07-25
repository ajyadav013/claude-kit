---
source: https://github.com/ashishps1/awesome-low-level-design/blob/main/problems/task-management-system.md
author: ashishps1 for in-repo problems
license-note: ideas absorbed in own words; no text or code reproduced
---

# Task manager LLD: CRUD plus lifecycle status, assignment, and lock-free concurrent collections

## What it teaches

This problem builds the domain kernel of a to-do/project tool: users create,
edit, delete, assign, search, filter, and complete tasks, with reminders and
per-user history, and the whole thing must stay consistent when many callers
touch it at once. It is essentially a lesson in modeling a rich entity (a
task with title, description, due date, priority, lifecycle status, and an
assignee) and centralizing its lifecycle behind one manager.

The reference structure is compact: a user entity (identity plus contact
info), a status enumeration covering the pending / in-progress / completed
lifecycle, the task entity itself, and a singleton manager that owns every
operation on tasks. The notable implementation decision is the concurrency
strategy — instead of explicit locks, the manager stores its state in
concurrent collections (a concurrent hash map for lookup plus a
copy-on-write list where iteration dominates), buying thread safety from the
data structures rather than from synchronized critical sections.

## Key patterns & decisions

- **Status as an explicit lifecycle enum**: a task's progress lives in a
  closed enumeration (pending → in progress → completed), making state
  transitions inspectable and filterable rather than encoded in booleans.
- **Rich entity, thin operations**: all task attributes (priority, due date,
  assignee, status) sit on the task; behavior (create/update/delete/search/
  complete/history) is concentrated in a manager, keeping the entity a data
  holder that is easy to persist and index.
- **Singleton manager as the consistency choke point**: every mutation flows
  through one instance, which is what makes the concurrent-collection
  strategy sufficient.
- **Concurrent collections over explicit locking**: thread safety is
  delegated to a concurrent map (fast keyed access under contention) and a
  copy-on-write list (cheap consistent iteration, expensive writes) —
  choosing structures whose contention profile matches the read-heavy
  search/filter workload.
- **Query as first-class capability**: searching and filtering by priority,
  due date, and assignee are listed as core requirements, so the design
  treats retrieval paths as primary API, not an afterthought over CRUD.
- **Per-user history**: completed work is retrievable per user, implying the
  manager maintains or derives an assignee-indexed view.

## When to apply / trade-offs

- The concurrent-collections approach is ideal when operations are
  individually atomic (put/remove/lookup) and read-heavy; it breaks down the
  moment you need multi-step invariants (e.g., "reassign and update status
  atomically"), where you must fall back to locks, compare-and-swap loops,
  or a transactional store.
- Copy-on-write lists are only sane when writes are rare relative to
  iteration; a high-churn task board would pay a full array copy per
  mutation.
- The status enum is deliberately minimal; real systems usually need a
  transition table (who may move a task from which state to which) — the
  enum is the foundation that makes such a table possible.
- The singleton manager mirrors an in-memory service layer; mapping this to
  production means replacing it with a repository over a database and moving
  the consistency guarantees there.

## Fidelity check

1. Claim: tasks carry title, description, due date, priority, status, and
   an assigned user. Support: the capture's requirements and task-class
   description enumerate exactly these attributes.
2. Claim: thread safety comes from concurrent data structures rather than
   coarse locks. Support: the capture states the manager uses a concurrent
   hash map and a copy-on-write list to handle concurrent access safely.
3. Claim: search/filter by criteria such as priority, due date, and assignee
   is a core requirement. Support: the requirements list supporting search
   and filtering of tasks on various criteria including priority, due date,
   and assigned user, and the manager exposes searching/filtering methods.
