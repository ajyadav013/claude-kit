// Dependency-free HTTP API fixture for the evaluation harness. Backs the frontend fixture so the
// browser plane has a real request to inspect, and gives contract/integration scenarios a target.
'use strict';

const http = require('node:http');

const PORT = Number(process.env.PORT || 8081);

const ITEMS = [
  { id: 1, title: 'Write the spec', status: 'done' },
  { id: 2, title: 'Review the spec', status: 'in-progress' },
  { id: 3, title: 'Ship the feature', status: 'todo' },
];

function json(res, status, body) {
  const payload = JSON.stringify(body);
  res.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'content-length': Buffer.byteLength(payload),
    'cache-control': 'no-store',
    'x-content-type-options': 'nosniff',
  });
  res.end(payload);
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url, `http://${req.headers.host || 'localhost'}`);
  if (req.method !== 'GET') {
    json(res, 405, { error: 'method not allowed' });
    return;
  }
  if (url.pathname === '/api/health') {
    json(res, 200, { status: 'ok' });
    return;
  }
  if (url.pathname === '/api/items') {
    const status = url.searchParams.get('status');
    const items = status ? ITEMS.filter((i) => i.status === status) : ITEMS;
    json(res, 200, { items, count: items.length });
    return;
  }
  json(res, 404, { error: 'not found' });
});

server.listen(PORT, '0.0.0.0', () => {
  process.stdout.write(`api fixture listening on ${PORT}\n`);
});
