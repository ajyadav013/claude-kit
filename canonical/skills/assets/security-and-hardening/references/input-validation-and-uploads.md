# Input Validation, Uploads, Archives, ReDoS — code patterns

Deep-dive reference for the `security-and-hardening` skill. Loaded on demand from SKILL.md —
the boundary rules and review checklist live there.

## Schema Validation at Boundaries

Use the project's schema validation framework (e.g., Pydantic for Python, Zod/Yup for TypeScript, JSR-303 for Java):

```python
# Python example
from pydantic import BaseModel, EmailStr, Field, field_validator

class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    first_name: str = Field(min_length=1, max_length=100)

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if not any(c.isupper() for c in v):
            raise ValueError("must contain an uppercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("must contain a digit")
        return v
# The framework returns 422 automatically on validation failure.
```

```typescript
// TypeScript example with Zod
import { z } from 'zod';

const UserCreateSchema = z.object({
  email: z.string().email(),
  password: z.string().min(12).max(128).refine(
    (val) => /[A-Z]/.test(val) && /[0-9]/.test(val),
    { message: "must contain uppercase letter and digit" }
  ),
  firstName: z.string().min(1).max(100),
});
```

## File Upload Safety

```python
ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_SIZE = 5 * 1024 * 1024  # 5 MB

def validate_upload(content_type: str, size: int) -> None:
    if content_type not in ALLOWED_TYPES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "file type not allowed")
    if size > MAX_SIZE:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "file too large (max 5MB)")
    # Don't trust the extension — verify magic bytes if it matters
```

## Archive Extraction Safety (zip-slip / symlink)

Extracting an uploaded or downloaded archive (`.zip`, `.tar`, `.tar.gz`, …) is a classic
remote-code/overwrite vector: the archive controls the *paths* of the files it writes. Two attacks:

- **Path traversal ("zip-slip"):** an entry named `../../etc/cron.d/x` or an absolute path escapes the
  extraction directory and overwrites files anywhere the process can write.
- **Symlink attack:** the archive contains a symlink pointing outside the target (or at a sensitive
  file), then a later entry writes *through* it.

Harden extraction — don't trust any entry name:

```python
import os

def safe_extract_path(dest_dir: str, member_name: str) -> str:
    # Resolve the final path and confirm it stays inside dest_dir (defeats ../ and absolute paths)
    dest = os.path.realpath(dest_dir)
    target = os.path.realpath(os.path.join(dest, member_name))
    if not (target == dest or target.startswith(dest + os.sep)):
        raise ValueError(f"unsafe archive entry escapes target: {member_name!r}")
    return target
```

- **Canonicalize then contain:** resolve each entry to an absolute real path and reject anything not
  under the target directory (covers `..`, absolute paths, and `..`-laden symlink targets).
- **Refuse or sanitize symlinks/hardlinks** in untrusted archives unless you explicitly need them — and
  if you do, validate their targets the same way.
- **Bound the output, too:** cap total uncompressed size and entry count to defeat decompression bombs
  (a few KB inflating to GBs is a DoS — pair with the upload size limit above).
- Prefer a safe-by-default extraction API/library over hand-rolled loops where your stack offers one.

> Stack-agnostic adaptation of archive-extraction hardening (path-traversal containment, symlink-attack
> prevention, safe-by-default extraction) from the Apache-2.0
> [`google/safearchive`](https://github.com/google/safearchive). Re-derived in prose; not vendored.

## Regex DoS (ReDoS) on untrusted input

When a regular expression runs against attacker-controlled input — search filters, validators, log
parsers, user-supplied patterns — a "catastrophic backtracking" pattern can take *exponential* time on a
short crafted string and hang the request (a CPU denial of service). Nested quantifiers and overlapping
alternations are the usual culprits (`(a+)+$`, `(\w+\s*)*`, `(.*)*`).

- **Prefer a linear-time engine.** Some regex engines (RE2-family, Rust `regex`, Go's `regexp`) guarantee
  linear-time matching with no backtracking — use one for any regex over untrusted input. In
  backtracking engines (PCRE, Python `re`, JS `RegExp`, Java), this guarantee does **not** hold.
- **Never compile a user-supplied pattern** in a backtracking engine without a linear-time engine, a
  strict pattern allowlist, and/or a match **timeout/length cap**.
- **Audit your own static regexes** for nested quantifiers; bound input length before matching.
- This is the regex-specific case of the general rule: untrusted input must not be able to make the
  server do unbounded work.

> Stack-agnostic adaptation of linear-time regex matching as ReDoS defense from the BSD-3-Clause
> [`google/re2`](https://github.com/google/re2). Re-derived in prose; not vendored — the principle
> (linear-time engine / bounded matching for untrusted patterns) generalizes across regex libraries.
