# Scenario 02 — The Devil's Advocate catches what review missed ⭐

This is the headline. It's the kit's anti-sycophancy moat working on real code: a clean review was
**not trusted**, an adversarial pass found two genuine Critical bugs, and the defect loop fixed them
with regression tests. Every artifact below is backed by captured command output in
[`../evidence/`](../evidence/).

## The setup — a comfortable PASS

After scenario [01](01-standard-feature.md), the change looked done:

- 12 tests green (`../evidence/01-pytest-green.txt`)
- `ruff` clean (`../evidence/01-lint.txt`)
- `sdlc-code-reviewer` returned **PASS**

A unanimous, comfortable green is exactly the condition the kit treats as **suspicious**. Per the
pipeline, a unanimous PASS on a review/test-coverage gate *spawns* the `devils-advocate` — it is not
optional, and it assumes the work is guilty.

## The adversarial pass — `devils-advocate`: **UPHELD with 2 Criticals**

The agent re-read the same `api.py` the review had approved and asked the question review didn't:
*what input shape does the handler assume, and what happens when that assumption is false?*

### Critical 1 — non-object JSON body crashes the handler

`do_POST` parsed the body with `json.loads` and immediately called `data.get("title")`. A valid JSON
value that isn't an object — e.g. the array `["not","a","dict"]` — has no `.get`, so the handler
raised `AttributeError` and returned a 500 (a crash), not a clean 400.

### Critical 2 — malformed `Content-Length` crashes the handler

`do_POST` did `int(self.headers.get("Content-Length", 0))` with no guard. A request with
`Content-Length: notanumber` raised `ValueError` before any validation — again a crash, not a 400.

Both are **reachable from unauthenticated input** with a one-line request. The review graded the code
on the paths it expected; the Devil's Advocate graded it on the paths an attacker would send.

## Reproduced — not asserted (`../evidence/02-bugs-before.txt`)

The kit's [§2.5 evidence rule](../../rules/quality-gates.md) forbids a finding that's merely argued.
Both bugs were **reproduced** against the running server before any fix:

```
# non-dict body
>>> POST /tasks  body=["not","a","dict"]
Traceback (most recent call last): ... AttributeError: 'list' object has no attribute 'get'

# malformed Content-Length
>>> POST /tasks  Content-Length: notanumber
Traceback (most recent call last): ... ValueError: invalid literal for int() with base 10: 'notanumber'
```

## The fix (`../evidence/02-fix.diff`)

Two guards in `do_POST`, both failing **closed** to a 400 with an `{error}` message (verbatim from
`02-fix.diff`):

```python
# guard the Content-Length parse
try:
    length = int(self.headers.get("Content-Length", 0))
except ValueError:
    self._send(400, {"error": "invalid Content-Length header"})
    return
...
                except json.JSONDecodeError:
                    self._send(400, {"error": "invalid JSON"})
                    return
                if not isinstance(data, dict):
                    self._send(400, {"error": "request body must be a JSON object"})
                    return
```

## Regression tests + GREEN (`../evidence/02-bugs-after.txt`, `../evidence/02-pytest-after.txt`)

Two new tests lock the behavior in — `test_post_non_dict_body_returns_400` (sends a JSON array) and
`test_malformed_content_length_returns_400` (raw socket, because `urllib` would compute a valid length
for you). Both bugs now return a clean **HTTP 400**, and the suite went from 12 to **14 green**:

```
14 passed in 2.87s
```

## Why this is the whole point

| | What it saw | Verdict |
|---|---|---|
| `sdlc-code-reviewer` | the expected paths | PASS |
| `devils-advocate` | the paths an attacker sends | **2 Criticals** |

A single-reviewer pipeline ships this. The kit's value isn't "an LLM reviewed the code" — every
orchestrator can do that. It's that a *unanimous green is the trigger for an adversary*, the adversary
**must reproduce** before a finding counts, and a reproduced Critical **gates the pipeline** until it's
fixed and proven fixed. That is the difference between *getting agents* and *governing them*.
