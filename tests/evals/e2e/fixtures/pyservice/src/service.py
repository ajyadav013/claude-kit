"""A small request-handling surface over `calc`, with a real failure mode.

Why this exists: SC-24 asks a session to make the service observable — a health check, structured
logging, a stated SLO. The fixture used to be four files whose only source module was an eleven-line
calculator, so the scenario's premise contradicted its own fixture: there was no service, no request
path, and nowhere for a health check to live. A session that complied had to invent a service nobody
asked for, and one that refused failed the oracle (F-082).

Deliberately absent, because they are the task: no health check, no logging, no SLO. Deliberately
present: a request path with arguments that can be wrong, so there is something whose health and
latency could be meaningfully reported.

Stdlib only, and no HTTP server — binding a port inside a graded container buys nothing the routing
layer does not already give, and would make the fixture flaky.
"""

from __future__ import annotations

import calc


class RequestError(Exception):
    """A request that cannot be served as asked. Carries the status a caller should report."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


ROUTES = {
    "/add": calc.add,
    "/subtract": calc.subtract,
}


def _coerce(params: dict[str, str]) -> tuple[int, int]:
    missing = [k for k in ("a", "b") if k not in params]
    if missing:
        raise RequestError(400, f"missing parameter(s): {', '.join(missing)}")
    try:
        return int(params["a"]), int(params["b"])
    except (TypeError, ValueError) as exc:
        raise RequestError(400, f"parameters must be integers: {exc}") from exc


def handle(path: str, params: dict[str, str] | None = None) -> tuple[int, dict]:
    """Serve one request. Returns (status, body); never raises for an ordinary bad request."""
    handler = ROUTES.get(path)
    if handler is None:
        return 404, {"error": f"no route for {path}"}
    try:
        a, b = _coerce(params or {})
    except RequestError as exc:
        return exc.status, {"error": str(exc)}
    return 200, {"result": handler(a, b)}
