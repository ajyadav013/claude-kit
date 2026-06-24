"""Standard-library HTTP API for the task store.

Uses ``http.server`` (stdlib) so the sample needs no web framework. The handler is
built by a factory that closes over a ``TaskStore`` instance, which keeps it testable
by binding a server to an ephemeral port (see ../tests/test_api.py).
"""

from __future__ import annotations

import json
import re
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlsplit

from tasktracker.store import TaskStore, ValidationError

__version__ = "0.1.0"

_COMPLETE_RE = re.compile(r"^/tasks/(\d+)/complete$")


def make_handler(store: TaskStore) -> type[BaseHTTPRequestHandler]:
    """Build a request handler bound to ``store``."""

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, payload: dict) -> None:
            body = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 - http.server dispatch name
            parts = urlsplit(self.path)
            if parts.path == "/health":
                self._send(200, {"status": "ok", "version": __version__})
                return
            if parts.path == "/tasks":
                status = parse_qs(parts.query).get("status", [None])[0]
                try:
                    tasks = store.list(status=status)
                except ValidationError as exc:
                    self._send(400, {"error": str(exc)})
                    return
                self._send(200, {"tasks": [t.as_dict() for t in tasks]})
                return
            self._send(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802 - http.server dispatch name
            try:
                length = int(self.headers.get("Content-Length", 0))
            except ValueError:
                self._send(400, {"error": "invalid Content-Length header"})
                return
            raw = self.rfile.read(length) if length else b""
            match = _COMPLETE_RE.match(urlsplit(self.path).path)
            if match:
                try:
                    task = store.complete(int(match.group(1)))
                except KeyError:
                    self._send(404, {"error": "task not found"})
                    return
                self._send(200, task.as_dict())
                return
            if urlsplit(self.path).path == "/tasks":
                try:
                    data = json.loads(raw or b"{}")
                except json.JSONDecodeError:
                    self._send(400, {"error": "invalid JSON"})
                    return
                if not isinstance(data, dict):
                    self._send(400, {"error": "request body must be a JSON object"})
                    return
                try:
                    task = store.add(
                        data.get("title", ""), data.get("priority", "medium")
                    )
                except ValidationError as exc:
                    self._send(400, {"error": str(exc)})
                    return
                self._send(201, task.as_dict())
                return
            self._send(404, {"error": "not found"})

        def log_message(self, *args, **kwargs) -> None:  # noqa: N802 - silence test logs
            return

    return Handler


def make_server(store: TaskStore, host: str = "127.0.0.1", port: int = 0) -> HTTPServer:
    """Create (but do not start) an ``HTTPServer`` serving ``store``."""
    return HTTPServer((host, port), make_handler(store))
