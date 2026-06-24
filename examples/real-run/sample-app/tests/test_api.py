"""Integration tests for the HTTP API — a real server on an ephemeral port."""

import json
import socket
import threading
import urllib.error
import urllib.request
from urllib.parse import urlsplit

import pytest
from tasktracker.api import make_server
from tasktracker.store import TaskStore


@pytest.fixture()
def base_url():
    server = make_server(TaskStore())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _request(url, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_health(base_url):
    status, payload = _request(base_url + "/health")
    assert status == 200
    assert payload["status"] == "ok"


def test_create_and_list_task(base_url):
    status, created = _request(
        base_url + "/tasks", method="POST", body={"title": "ship it"}
    )
    assert status == 201
    assert created["id"] == 1
    status, payload = _request(base_url + "/tasks")
    assert status == 200
    assert payload["tasks"][0]["title"] == "ship it"


def test_create_rejects_empty_title(base_url):
    status, payload = _request(base_url + "/tasks", method="POST", body={"title": ""})
    assert status == 400
    assert "error" in payload


def test_complete_task(base_url):
    _request(base_url + "/tasks", method="POST", body={"title": "a"})
    status, payload = _request(base_url + "/tasks/1/complete", method="POST")
    assert status == 200
    assert payload["done"] is True


def test_complete_missing_returns_404(base_url):
    status, payload = _request(base_url + "/tasks/999/complete", method="POST")
    assert status == 404


def test_post_non_dict_body_returns_400(base_url):
    # A JSON array (not an object) must not crash the handler.
    # Regression for a bug the devils-advocate caught — see
    # ../scenarios/02-devils-advocate-catch.md.
    status, payload = _request(
        base_url + "/tasks", method="POST", body=["not", "a", "dict"]
    )
    assert status == 400
    assert "error" in payload


def test_malformed_content_length_returns_400(base_url):
    # A non-numeric Content-Length must not crash the handler. Uses a raw socket
    # because urllib would compute a valid length for us. Regression — see
    # ../scenarios/02-devils-advocate-catch.md.
    parts = urlsplit(base_url)
    conn = socket.create_connection((parts.hostname, parts.port), timeout=5)
    try:
        conn.sendall(
            b"POST /tasks HTTP/1.1\r\nHost: x\r\nContent-Length: notanumber\r\n\r\n"
        )
        response = conn.recv(4096)
    finally:
        conn.close()
    assert b"400" in response.split(b"\r\n", 1)[0]
