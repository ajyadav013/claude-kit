# App Factory and Mode Dispatch

Express services in production often run as multiple distinct servers from a single codebase. This pattern uses **mode dispatch** to determine which app type to start (HTTP server, Kafka consumer, background worker) and **server-type dispatch** to mount different route sets within the HTTP server.

## Mode dispatch (index.js)

The entrypoint switches on `conf.mode` (from env `MODE`) to load the appropriate app type.

```javascript
// index.js
require('newrelic');
require('./instrument'); // Sentry instrumentation

const conf = require('./config');
const logger = require('./app/common/winston')('index');

process.setMaxListeners(30);

switch (conf.mode) {
  case 'server':
    require('./app/server');
    break;
  case 'consumer':
    require('./kafka.worker');
    break;
  case 'worker':
    require('./app/worker');
    break;
  default:
    logger.error('Unknown app mode');
    break;
}
```

**Why this matters**: A single Docker image can run as an API server, a Kafka consumer, or a background worker by setting `MODE=server` / `MODE=consumer` / `MODE=worker`. This reduces deployment surface area and ensures consistent dependencies.

## App factory with server-type dispatch

The `getAppServer(serverType)` function creates a fresh Express app with common middleware, then conditionally mounts routes based on `serverType` (from env `SERVER_TYPE`).

```javascript
// app/server/server.js
const express = require('express');
const Sentry = require('@sentry/node');
const timeout = require('connect-timeout');
const bodyParser = require('body-parser');
const logger = require('@utils/logger')('server');

const getAppServer = (serverType) => {
  const app = express();
  app.disable('x-powered-by');
  app.use(timeout(10 * 1000));

  if (conf.sentry.dsn) {
    Sentry.init({ dsn: conf.sentry.dsn, environment: conf.sentry.environment });
    app.use(Sentry.Handlers.requestHandler({ request: true, ip: true, user: ['email'] }));
  }

  // Health checks (must come before logging middleware)
  const checkHealth = (req, res) => res.json({ ok: 'ok' });
  app.get('/_healthz', checkHealth);
  app.get('/_readyz', checkHealth);

  // Common middleware (CORS, body-parser, logging, etc.)
  app.use(bodyParser.json());
  // ... other middleware

  // Mount routes based on server type
  if (serverType === 'platform') {
    logger.info('Mounting [PLATFORM] routes');
    require('./routes/platform')(app);
  } else if (serverType === 'panel') {
    logger.info('Mounting [PANEL] routes');
    require('./routes/panel')(app);
  } else if (serverType === 'internal') {
    logger.info('Mounting [INTERNAL] routes');
    require('./routes/internal')(app);
  } else if (serverType === 'admin') {
    logger.info('Mounting [ADMIN] routes');
    require('./routes/administrator')(app);
  } else if (serverType === 'webhook') {
    logger.info('Mounting [WEBHOOK] routes');
    require('./routes/webhook')(app);
  } else {
    throw new Error('Invalid Server Type');
  }

  // 404 handler
  app.use((req, res, next) => {
    const err = new Error('Not Found');
    err.statusCode = 404;
    next(err);
  });

  // Custom error handler (see middleware-patterns.md)
  app.use((err, req, res, next) => {
    const status = err.statusCode || 500;
    res.status(status).json({ success: false, status, message: err.message });
  });

  return app;
};

module.exports = { getAppServer };
```

**Why this matters**: A single service codebase deploys as:
- `SERVER_TYPE=platform` — public API for external clients
- `SERVER_TYPE=panel` — authenticated UI backend
- `SERVER_TYPE=internal` — service-to-service endpoints
- `SERVER_TYPE=admin` — privileged admin operations
- `SERVER_TYPE=webhook` — event callback endpoints

This avoids route bloat in any single server and reduces attack surface (e.g., admin routes are never exposed on platform servers).

## Health checks

Health check endpoints (`/_healthz`, `/_readyz`) must:
1. Come **before** logging middleware (to avoid noise in logs)
2. Return immediately with `{ ok: 'ok' }` and 200 status
3. Be whitelisted in any auth/session middleware

These are called frequently by Kubernetes liveness/readiness probes and load balancers.

## Starting the server (app/server/index.js)

```javascript
// app/server/index.js
const conf = require('@configs');
const logger = require('@utils/logger')('server');
const { getAppServer } = require('./server');

const serverType = conf.get('serverType');
const PORT = conf.get('port');

const app = getAppServer(serverType);
const httpServer = app.listen(PORT, () => {
  logger.info(`server started at http://localhost:${PORT}`);
});
```

## Key conventions

- **Disable `x-powered-by`**: `app.disable('x-powered-by')` to avoid leaking Express version.
- **Set `trust proxy` in production**: `app.set('trust proxy', 1)` to extract correct client IPs from `X-Forwarded-For` when behind a reverse proxy.
- **Test mode loads all routes**: In `app_env === 'test'`, mount all route sets to enable integration tests without restarting the server.
- **Fail fast on invalid server type**: `throw new Error('Invalid Server Type')` to catch misconfigurations early.
