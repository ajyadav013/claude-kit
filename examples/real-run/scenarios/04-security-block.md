# Scenario 04 — Security gate blocks a planted secret

**Request:** *"Add a tiny admin endpoint to reset the store; gate it with a shared admin token."*

This exercises the **Security Clear** gate and its `secret-scanner` sub-scanner. A hardcoded admin
token was planted in the change to verify the scanner actually catches it — and that the gate
**blocks** rather than warns. In the kit, a leaked secret is an
[auto-Critical](../../rules/quality-gates.md): no severity debate, no pass-with-a-note.

## The change (planted secret)

A throwaway admin module shipped with the token inline (`admin.py`):

```python
# admin.py
API_TOKEN = "sk-live-9f8e7d6c5b4a3f2e1d0c9b8a7f6e5d4c"   # planted for the demo (not a real key)

def is_admin(request_token: str) -> bool:
    return request_token == API_TOKEN
```

Two problems, not one: a **hardcoded credential in source**, and an admin action guarded by a
**string compared in code** rather than an injected, rotatable secret.

## Gate: Security Clear → `secret-scanner` — **FAIL** (`../evidence/04-security-fail.txt`)

The real scan flagged the credential by file and line (captured output, verbatim):

```
=== secret scan WITH vuln present (should FAIL) ===
examples/real-run/sample-app/tasktracker/admin.py:7:API_TOKEN = "sk-live-9f8e7d6c5b4a3f2e1d0c9b8a7f6e5d4c"
--- grep exit (0 = match found = secret present) ---
```

A located, high-entropy vendor-prefixed credential is auto-Critical, so the gate **blocks**. There is
no "ship it with a follow-up ticket" path for a live-looking credential in source.

`security-reviewer` (the stage coordinator) corroborated the broader posture for this demo: in-memory
store, no auth on the main endpoints, and an **unbounded request body** (`SEC-01`, High) — acceptable
for a localhost demo, **not** for production. The secret, by contrast, blocks regardless of context.

## The fix → **PASS** (`../evidence/04-security-pass.txt`)

The credential moves out of source to an injected environment variable, and the code fails closed when
it's unset (so a missing secret can't silently disable the gate):

```python
import os
API_TOKEN = os.environ.get("ADMIN_API_TOKEN")  # injected, never committed

def is_admin(request_token: str) -> bool:
    return bool(API_TOKEN) and request_token == API_TOKEN
```

Re-running the scanner on the cleaned tree (captured output, verbatim):

```
=== secret scan AFTER removing vuln (should PASS = no output) ===
clean: no secrets found
```

> `admin.py` is **not** committed to the repo — it existed only during the demo to be scanned, then
> was removed (which is also why the "after" scan is clean). Its before/after scan output is preserved
> in `../evidence/`.

## Why this matters

Secret scanning isn't the differentiator — plenty of tools grep for keys. What the kit adds is that
the finding is **classified auto-Critical and wired to a hard gate**: a located secret cannot be
graded down to a warning, the pipeline cannot advance past it, and the fix has to fail closed. The
verdict is grounded in a real scan with a `file:line`, not a model's assurance that "it looks fine."
