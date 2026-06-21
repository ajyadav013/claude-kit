# Security-Regression Tests

Functional tests prove a feature works. **Security-regression tests prove it can't be abused** — and
they're the test class most often missing. Every authz or isolation bug you fix should leave behind a
test that fails if the boundary is ever re-broken.

## The fixtures you need

Most security tests need clients at different privilege levels and data in different tenants. Build these
once in `conftest.py`:

```python
@pytest.fixture
async def admin_client(client):
    await _login(client, role="admin")
    yield client

@pytest.fixture
async def member_client(client):
    await _login(client, role="member")
    yield client

@pytest.fixture
async def tenant_a_client(client):
    await _login(client, tenant_id=TENANT_A_ID)
    yield client

@pytest.fixture
async def raw_client(app):
    # A client that does NOT go through the gateway-signing step — used to assert services
    # reject unsigned/forged forwarded-identity headers.
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

@pytest.fixture
async def seed_tenant_b_order(db_connection):
    async with db_connection() as session:
        await session.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": str(TENANT_B_ID)})
        order = await OrderDAO(session).create(OrderCreate(...))
        await session.commit()
        return order
```

## 1. Negative authorization

For every role-gated endpoint, assert the **rejections**, not only the success:

```python
@pytest.mark.security
@pytest.mark.parametrize("method,path", [
    ("GET", "/v1/admin/users"),
    ("POST", "/v1/admin/users"),
    ("DELETE", "/v1/admin/users/{id}"),
])
async def test_admin_routes_reject_unauthenticated(client, method, path):
    resp = await client.request(method, path.format(id="00000000-0000-0000-0000-000000000000"))
    assert resp.status_code == 401

@pytest.mark.security
async def test_admin_route_forbids_member(member_client):
    resp = await member_client.get("/v1/admin/users")
    assert resp.status_code == 403
```

## 2. Cross-tenant isolation (route + DAO/RLS)

Test at **both** layers so isolation survives a handler that forgets to scope:

```python
@pytest.mark.security
async def test_route_blocks_cross_tenant(tenant_a_client, seed_tenant_b_order):
    resp = await tenant_a_client.get(f"/v1/orders/{seed_tenant_b_order.id}")
    assert resp.status_code == 404          # 404 not 403: don't leak existence

@pytest.mark.security
async def test_rls_blocks_cross_tenant_at_dao(db_connection, seed_tenant_b_order):
    async with db_connection() as session:
        await session.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": str(TENANT_A_ID)})
        assert await OrderDAO(session).get_by_id(seed_tenant_b_order.id) is None
```

## 3. IDOR (insecure direct object reference)

```python
@pytest.mark.security
async def test_cannot_access_other_users_object(user_a_client, seed_user_b_document):
    resp = await user_a_client.get(f"/v1/documents/{seed_user_b_document.id}")
    assert resp.status_code in (403, 404)
```

Cover sequential ids, guessable ids, and ids captured from another session.

## 4. Login lockout & rate limiting

```python
@pytest.mark.security
async def test_lockout_after_failures(client):
    for _ in range(5):
        await client.post("/v1/auth/login", json={"email": "u@example.com", "password": "wrong"})
    # Even the CORRECT password must fail while locked / rate-limited:
    resp = await client.post("/v1/auth/login", json={"email": "u@example.com", "password": "correct"})
    assert resp.status_code in (423, 429)

@pytest.mark.security
async def test_login_error_is_uniform(client):
    # No user-enumeration: unknown email and wrong password return the same error
    r1 = await client.post("/v1/auth/login", json={"email": "nobody@example.com", "password": "x"})
    r2 = await client.post("/v1/auth/login", json={"email": "u@example.com", "password": "wrong"})
    assert r1.status_code == r2.status_code and r1.json()["error"] == r2.json()["error"]
```

## 5. Forwarded-identity / signed-header trust

For services behind a signing gateway (see `edge-to-service-trust-boundary`):

```python
@pytest.mark.security
async def test_unsigned_request_rejected(raw_client):
    resp = await raw_client.get("/v1/internal/profile", headers={"x-user-role": "admin"})
    assert resp.status_code == 401          # naked header, no signature

@pytest.mark.security
async def test_forged_signature_rejected(raw_client):
    resp = await raw_client.get("/v1/internal/profile", headers={
        "x-user-role": "admin", "x-gateway-signature": "deadbeef", "x-gateway-timestamp": "9999999999",
    })
    assert resp.status_code == 401
```

## 6. Input-boundary rejection

```python
@pytest.mark.security
@pytest.mark.parametrize("payload", ["' OR 1=1 --", "../../etc/passwd", "<script>alert(1)</script>"])
async def test_injection_shaped_input_rejected_or_neutralized(authenticated_client, payload):
    resp = await authenticated_client.post("/v1/search", json={"q": payload})
    # Either rejected at the schema boundary, or accepted but provably not executed/reflected raw:
    assert resp.status_code in (200, 422)
    if resp.status_code == 200:
        assert payload not in resp.text     # no raw reflection (XSS)
```

## Wire it into CI as a dedicated gate

Register the marker and run security tests as their own job so a regression is unmissable:

```ini
# pytest.ini  (or setup.cfg under [tool:pytest])
[pytest]
markers =
    security: security-regression tests (authz, tenant isolation, IDOR, lockout, signed-header trust)
```

```toml
# pyproject.toml — markers is a LIST under [tool.pytest.ini_options]
[tool.pytest.ini_options]
markers = [
    "security: security-regression tests (authz, tenant isolation, IDOR, lockout, signed-header trust)",
]
```

```yaml
# .github/workflows/backend-tests.yml (excerpt)
  security-tests:
    needs: [lint]
    services:
      postgres: { image: postgres:15, ... }
      redis: { image: redis:7, ... }
    steps:
      - run: pytest -m security -v        # must pass; separate from unit/integration
```

## Principles

- **Assert the rejection.** A test that only checks the allowed case can't catch a removed check.
- **Prefer 404 over 403 for cross-tenant/IDOR** so you don't leak that the resource exists.
- **Test the data layer too** (RLS / DAO scoping), not just the route — defense in depth needs both
  proven.
- **Every fixed authz/isolation bug becomes a permanent test.** That's what makes it a *regression* suite.
