# Scenario 03 — Backward-incompatible API change

**Request:** *"The `GET /tasks` response is over-wrapped — just return the array of tasks directly
instead of `{"tasks": [...]}`. It's cleaner."*

A small, reasonable-sounding change that silently breaks every existing client. This scenario shows the
**contract-clear** gate refusing it: the public response *shape* changed without a version bump or
migration path, and an existing consumer test goes RED to prove the break is real.

## The change (`../evidence/03-breaking.diff`)

The diff unwraps the list response — from an object envelope to a bare array:

```diff
-                self._send(200, {"tasks": [t.as_dict() for t in tasks]})
+                self._send(200, [t.as_dict() for t in tasks])  # BREAKING: was {"tasks": [...]}
```

No version bump, no deprecation window, no `Sunset`/`Deprecation` signaling. Any client that reads
`response["tasks"]` now gets a `TypeError`/`KeyError` instead of a list — a hard break.

## Gate: contract-clear — **BLOCK**

The break isn't a matter of opinion — it's demonstrated. The existing integration test
`test_create_and_list_task` reads `payload["tasks"][0]["title"]`, exactly as a real client would, and
now fails (`../evidence/03-pytest-red.txt`):

```
>       assert payload["tasks"][0]["title"] == "ship it"
E       TypeError: list indices must be integers or slices, not str

1 failed, 11 passed in 2.58s
```

A previously-passing consumer test going RED **is** the evidence of a backward-incompatible change.
The gate blocks pipeline progression and requires one of:

1. **Additive instead of breaking** — keep the `{"tasks": [...]}` envelope and add the bare-array form
   under a new path or `Accept` negotiation; deprecate the old shape on a schedule. (No break; gate
   passes.)
2. **Owned break** — bump the API major version, ship a migration note, and update the consumer
   contract tests in the same change so the RED test becomes a deliberate, documented update — not a
   surprise to whoever depends on the field.

## Why this matters

"It's cleaner" is how most breaking changes are framed. The kit doesn't argue about taste — it checks
whether the *observable contract* changed and whether a consumer breaks, then forces the change to be
either non-breaking or **explicitly versioned and migrated**. The verdict is grounded in a real
failing test (`../evidence/03-pytest-red.txt`), not a reviewer's recollection of who depends on the
shape.
