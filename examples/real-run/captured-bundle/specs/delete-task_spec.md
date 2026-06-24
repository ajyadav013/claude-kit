# Spec — Delete a task (`DELETE /tasks/{id}`)

**Status:** approved · **Profile:** standard · **Lane:** backend (Go / net-http)

## Problem

The task API can create and list tasks but has no way to remove one. Clients that complete or
mis-create a task have no corrective action. Add a single endpoint to delete a task by id.

## Scope

- **In:** one new route, `DELETE /tasks/{id}`, over the existing in-memory `Store`.
- **Out:** bulk delete, soft-delete/archival, auth (the sample is unauthenticated by design),
  persistence.

## Acceptance criteria

1. `DELETE /tasks/{id}` removes an existing task and returns **`204 No Content`** with an empty body.
2. Deleting an id that does not exist returns **`404 Not Found`** with an `{"error": ...}` body.
3. The id must be a **canonical positive integer**. A non-integer (`/tasks/abc`), zero/negative, or
   non-canonical form (`/tasks/01`, `/tasks/+1`) returns **`400 Bad Request`** — it must not 404,
   panic, or alias another task. *(Tightened after the devils-advocate found that `strconv.Atoi` alone
   aliased `01`/`+1` onto task `1` and deleted it; see `../../.sdlc-evidence/devils-advocate.txt`.)*
4. After a successful delete, the task no longer appears in `GET /tasks`.
5. The change is **additive**: `GET /health`, `GET /tasks`, and `POST /tasks` behave exactly as before
   (no contract change to existing routes).

## Design

- `Store.Delete(id int) error` — returns `errNotFound` (sentinel) when the id is absent; otherwise
  deletes under the existing mutex. No new state.
- Route handler uses Go 1.22+ `ServeMux` method+pattern routing (`DELETE /tasks/{id}`) and
  `r.PathValue("id")`; `strconv.Atoi` distinguishes a bad id (400) from a missing task (404).

## Test plan

- `TestDeleteTask` — create then delete → 204, then `GET /tasks` is empty (criteria 1, 4).
- `TestDeleteMissingReturns404` — delete unknown id → 404 (criterion 2).
- `TestDeleteNonIntegerReturns400` — delete `/tasks/abc` → 400 (criterion 3).
- Existing `TestHealth`, `TestCreateAndListTask`, `TestCreateRejectsEmptyTitle` remain green
  (criterion 5).
