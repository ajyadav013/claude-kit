// INTENTIONALLY VULNERABLE FIXTURE — DO NOT COPY, DEPLOY, OR REUSE.
//
// This exists so the evaluation program can exercise its security scanners and its authorized
// local pentest path against a target it owns. It runs only on the `pentest-isolated` Docker
// network, which is declared `internal: true`, so it has no route to the internet, the host LAN,
// or any other fixture. It holds no real credentials and no real data.
//
// Planted defects, all deliberate:
//   1. Reflected XSS       — /search?q= echoes the query into HTML unescaped.
//   2. Injection           — /users?name= concatenates input into a query-like string.
//   3. Broken access ctrl  — /admin trusts a client-supplied header.
//   4. Info disclosure     — /debug returns internal configuration.
'use strict';

const http = require('node:http');

const PORT = Number(process.env.PORT || 8082);

// Fake, obviously-not-real values. No secret here is valid anywhere.
const FAKE_CONFIG = {
  environment: 'eval-fixture',
  db_dsn: 'postgres://fixture:fixture@localhost:5432/fixture',
  feature_flags: ['vuln-xss', 'vuln-injection', 'vuln-authz'],
};

const USERS = [
  { name: 'alice', role: 'user' },
  { name: 'bob', role: 'user' },
  { name: 'root', role: 'admin' },
];

function html(res, status, body) {
  res.writeHead(status, { 'content-type': 'text/html; charset=utf-8' });
  res.end(`<!doctype html><html lang="en"><body>${body}</body></html>`);
}

function json(res, status, body) {
  res.writeHead(status, { 'content-type': 'application/json; charset=utf-8' });
  res.end(JSON.stringify(body));
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url, `http://${req.headers.host || 'localhost'}`);

  if (url.pathname === '/') {
    html(res, 200, '<h1>Vulnerable eval fixture</h1><p>Authorized local target only.</p>');
    return;
  }

  // 1. Reflected XSS: the query is interpolated without escaping.
  if (url.pathname === '/search') {
    const q = url.searchParams.get('q') || '';
    html(res, 200, `<h1>Results for ${q}</h1><p>No matches.</p>`);
    return;
  }

  // 2. Injection: input is concatenated into a query string and the "parser" honours the operator.
  if (url.pathname === '/users') {
    const name = url.searchParams.get('name') || '';
    const query = `SELECT * FROM users WHERE name = '${name}'`;
    const alwaysTrue = /'\s*OR\s*'?1'?\s*=\s*'?1/i.test(query);
    json(res, 200, { query, users: alwaysTrue ? USERS : USERS.filter((u) => u.name === name) });
    return;
  }

  // 3. Broken access control: authorization is decided by a client-controlled header.
  if (url.pathname === '/admin') {
    if (req.headers['x-is-admin'] === 'true') {
      json(res, 200, { ok: true, secret_note: 'fixture admin area reached' });
    } else {
      json(res, 403, { error: 'forbidden' });
    }
    return;
  }

  // 4. Information disclosure.
  if (url.pathname === '/debug') {
    json(res, 200, FAKE_CONFIG);
    return;
  }

  json(res, 404, { error: 'not found' });
});

server.listen(PORT, '0.0.0.0', () => {
  process.stdout.write(`VULNERABLE eval fixture listening on ${PORT} (isolated network only)\n`);
});
