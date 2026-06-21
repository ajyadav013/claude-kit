# PII & Secret Redaction in Logs

Structured logging makes it trivial to log a whole request body, ORM object, or DB URL — which is the
most common way PII and secrets reach a log aggregator (where they are then indexed, retained, and shared
far more widely than the database they came from). Redact **in the logging pipeline**, so coverage does
not depend on every developer remembering at every call site.

## Where redaction goes

In the structlog processor chain, **after** your own context processors and **before** the renderer:

```python
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        redact_processor,                         # <-- redact before rendering
        structlog.processors.JSONRenderer(),      # renderer last
    ],
    ...
)
```

Running it before the renderer means it sees the structured event dict (keys + values) rather than a
flattened string, so it can mask by key *and* by content.

## 1. Sensitive-key denylist (mask by key)

Mask the value of any key whose name indicates a secret or PII, regardless of content:

```python
SENSITIVE_KEYS = {
    "password", "passwd", "secret", "token", "access_token", "refresh_token",
    "authorization", "api_key", "apikey", "cookie", "set-cookie", "session",
    "private_key", "client_secret", "x-user-data", "ssn", "card", "card_number", "cvv",
}

def _redact_keys(d: dict) -> dict:
    for k, v in list(d.items()):
        if k.lower() in SENSITIVE_KEYS:
            d[k] = "***"
        elif isinstance(v, dict):
            d[k] = _redact_keys(v)            # recurse into nested dicts
        elif isinstance(v, list):             # and into lists of dicts (arrays of objects)
            d[k] = [_redact_keys(i) if isinstance(i, dict) else i for i in v]
    return d
```

Keep the key with a `"***"` value rather than dropping it — the *shape* of the log line stays useful for
debugging, the *value* is gone.

## 2. Pattern masking (mask by content)

Free-text messages and string fields can embed PII even when the key is innocuous (`message`, `detail`,
`error`). Mask common patterns:

```python
import re

_EMAIL  = re.compile(r"([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*(@[A-Za-z0-9.-]+)")
_DIGITS = re.compile(r"\b\d{13,19}\b")            # card-like / long numeric runs
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._-]+")
_DSN    = re.compile(r"(\w+://[^:/\s]*:)([^@/\s]+)(@)")   # creds in a connection string (incl. redis://:pass@host)

def _mask_str(s: str) -> str:
    s = _EMAIL.sub(r"\1***\2", s)        # j***@example.com
    s = _DIGITS.sub("****", s)
    s = _BEARER.sub("Bearer ***", s)
    s = _DSN.sub(r"\1***\3", s)          # postgresql://user:***@host/db
    return s
```

Tune the patterns to your data (phone formats, national IDs). Over-masking is safer than under-masking.

## 3. The processor

```python
def _mask_recursive(value):                  # pattern-mask every string at any depth
    if isinstance(value, dict):
        return {k: _mask_recursive(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_mask_recursive(v) for v in value]
    if isinstance(value, str):
        return _mask_str(value)
    return value

def redact_processor(_logger, _method, event_dict):
    event_dict = _redact_keys(event_dict)    # 1. mask by key (recurses dicts + lists)
    return _mask_recursive(event_dict)       # 2. pattern-mask string values at every depth
```

## 4. DB URLs / connection strings

The single most common leak: logging a connector config or a connection error that includes the DSN.
Always mask the password component before logging:

```python
def safe_dsn(dsn: str) -> str:
    return _DSN.sub(r"\1***\3", dsn)

logger.info("db.connecting", dsn=safe_dsn(settings.DATABASE_URL))
```

Never log `settings.DATABASE_URL` (or any `*_URL` with credentials) directly.

## 5. Audit-event field allowlist

Audit/access logs are high-value and high-exposure. **Allowlist** the fields you emit instead of dumping
the user or request object:

```python
AUDIT_FIELDS = ("user_id", "user_role", "tenant_id", "action", "resource_id", "result")

def audit_log(action: str, **fields) -> None:
    safe = {k: fields[k] for k in AUDIT_FIELDS if k in fields}
    logger.info("audit", **safe)          # no user_email, user_name, token, body
```

Prefer opaque identifiers (`user_id`, `tenant_id`) over `user_email` / `user_name`. If a human-readable
field is genuinely required, mask it (`j***@example.com`).

## 6. Truncate large payloads

```python
def truncate(s: str, limit: int = 2048) -> str:
    return s if len(s) <= limit else s[:limit] + f"...<+{len(s) - limit} bytes>"
```

Run truncation *and* redaction on any request/response body you log — full bodies leak data and bloat log
volume.

## Verification

- Grep your codebase for direct logging of risky values:
  `grep -rnE "logger\.(info|debug|warning|error).*(password|token|DATABASE_URL|x-user-data|request\.body)"`
- Add a unit test: log a record containing an email, a card number, a bearer token, and a DSN with a
  password; assert the rendered output contains none of the raw values.
- Confirm the processor is in the chain **before** the renderer in every entrypoint (server, consumer,
  worker, cron) — redaction must be configured for *all* modes, not just the API.

## Anti-patterns

- Redacting at call sites instead of in the pipeline (one forgotten call = a leak).
- Masking only by key (misses PII embedded in free-text messages) or only by content (misses structured
  secret fields) — do both.
- Logging the whole user/ORM object or full request body.
- Logging a DSN/connection string with credentials.
- Configuring redaction for the API process but not for consumers/workers/cron (they log too).
