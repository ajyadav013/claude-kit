---
name: node-express-service
description: Encodes production Express.js service patterns covering app factory, multi-mode server dispatch (platform/panel/internal/admin), convict hierarchical config, module-alias path mapping, swagger-jsdoc API docs, custom error-handling middleware with statusCode convention, Sentry/New Relic wiring, and the custom middleware suite (ingress header parser, request logger with nanoid IDs, connect-redis sessions, connect-timeout, basic-auth, passport). Use when building a Node.js backend service, structuring Express apps for multi-tenancy or role-based routing, implementing session management with Redis, setting up API documentation with Swagger, or migrating from a monolithic Express server to a mode-dispatched architecture.
---

Standardize Express.js service architecture, mode-based server dispatch, hierarchical configuration, middleware composition, and error handling following production patterns.

## When to use

- Scaffolding a new Express.js backend service or microservice
- Setting up mode-based dispatch to run one codebase as multiple servers (platform API, admin panel, internal services, webhooks)
- Implementing hierarchical configuration with convict (env vars, format validation, defaults)
- Configuring module-alias path mapping for clean imports (@controllers, @services, @utils)
- Generating API documentation with swagger-jsdoc
- Building custom middleware for ingress header parsing (x-user-data → userId/roleIds/orgId)
- Implementing request logging with unique request IDs, response timing, and sensitive field masking
- Setting up Redis-backed sessions with connect-redis
- Wiring Sentry error tracking and New Relic APM
- Creating a custom error-handling middleware with statusCode convention
- Migrating from a single Express app to a multi-mode architecture

## Core conventions

1. **Mode-based entrypoint in `index.js`**: switch on `conf.mode` (from env `MODE`) to load different app types—`server` (HTTP API), `consumer` (Kafka consumer), `worker` (background job processor). For `server` mode, load the Express app factory and listen on `conf.port`. Require `newrelic` at the top for APM, followed by Sentry instrumentation. Set `process.setMaxListeners(30)` to avoid EventEmitter warnings.

2. **App factory with server-type dispatch in `app/server/app.js` or `server.js`**: export a `getAppServer(serverType)` function that creates a fresh Express app, applies common middleware (timeout, body-parser, CORS, logging, ingress parser), then conditionally mounts routes based on `serverType` (from env `SERVER_TYPE`). Supported server types: `platform` (public API), `panel` (authenticated UI), `internal` (service-to-service), `admin` (privileged admin operations), `webhook` (event callbacks), `ui` (static SPA). For test mode, mount all route sets. Disable `x-powered-by` header via `app.disable('x-powered-by')`. Set `trust proxy` in production for correct client IP extraction.

3. **Convict hierarchical config in `config.js`**: define a schema with `doc`, `format`, `default`, `env`, and `arg` for each config field. Use strict formats: `['production', 'development', 'test']` for `app_env`, `Number` for `port`, `Boolean` for flags, `String` for URLs. Call `conf.validate({ allowed: 'strict' })` to enforce schema. Export `Object.assign(conf, conf.get())` to allow both `conf.get('key')` and `conf.key` access. Typical top-level fields: `mode`, `server_type`, `app_env`, `port`, `enable_cors`, `sentry.dsn`, `newrelic_app`, `redis.readWrite`, `postgres.url`, `tokens.sessionSecret`, `cookie.maxAge`.

4. **Module-alias setup in `registerAlias.js` or top of `index.js`**: use `module-alias` to map `@controllers`, `@services`, `@models`, `@validators`, `@middlewares`, `@utils`, `@constants`, `@configs` to absolute paths under `__dirname`. Require `module-alias/register` after defining aliases. This allows imports like `require('@controllers/user.controller')` instead of `../../../app/server/controllers/user.controller`.

5. **Swagger docs with swagger-jsdoc**: define `swaggerOptions` with `info`, `openapi: '3.0.2'`, and `apis` array pointing to route definition files (e.g., `./swaggerDefinition/panel/*.js`) and model YAML files. Use `swaggerJSDoc(swaggerOptions)` to generate `swaggerSpec`. Conditionally adjust `swaggerSpec.paths` to inject a base path per server type (e.g., `/service/panel/users` for panel, `/service/platform/users` for platform). Serve spec at `GET /swagger.json` and optionally mount `swagger-ui-express` at `/docs`.

6. **Custom error-handling middleware at the end of the app**: define a 4-argument error handler `(err, req, res, next)` that extracts `err.statusCode || 500`, logs the error (skip 404), captures to Sentry if `status === 500`, and returns JSON `{ success: false, status, message, stack (dev-only), requestId }`. Place after Sentry error handler (if enabled). For 404s, add a catch-all route before error handlers that creates `err = new Error('Not Found'); err.statusCode = 404` and calls `next(err)`.

7. **Request logging middleware with nanoid request IDs**: use `nanoid` (or `customAlphabet('0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ', 8)`) to generate `req.id` for each request. Log request (METHOD, URL, IP, HEADERS, BODY for POST/PUT/PATCH) and response (STATUS, RES_HEADERS) via `res.on('finish', ...)`. Mask sensitive fields like `password` in the body log (replace with `'*******'`). Skip logging for health check URLs (`/_healthz`, `/_readyz`, `/swagger.json`). Log via Winston or similar structured logger.

8. **Ingress header parser middleware (`nginxIngressParser`)**: parse the `x-user-data` header (JSON payload set by an ingress gateway or upstream service) into `req.userId`, `req.roleIds`, `req.roleSlug`, `req.userHubIds`, `req.account`, `req.orgId`. If the header is missing and `server_type === 'admin'`, reject with 400 unless the URL is whitelisted (`/_healthz`, `/swagger.json`). For superAdmin users, allow query param `orgId` override. Wrap `JSON.parse` in try-catch and log errors without failing the request.

9. **Connect-timeout middleware**: use `timeout(30 * 1000)` (or 10s/60s per service SLA) as the first middleware to auto-terminate slow requests. No explicit timeout handler needed; the middleware sets `req.timedout` and aborts.

10. **CORS middleware for development**: in `app_env === 'development'`, use `cors()` with dynamic `origin: true`, `credentials: true`, `maxAge: 86400`, and explicit `allowedHeaders` (content-type, authorization, x-user-data, x-application-id, x-application-token, x-currency-code, etc.) and `exposedHeaders` (Accept-Ranges, Content-Range, etc.). Optionally skip CORS if `req.header('X-Skip-Cors') === 'true'`. In production, rely on ingress for CORS.

11. **Redis-backed sessions with connect-redis**: use `express-session` with `RedisStore` (from `connect-redis(expressSession)`). Set `name` to custom cookie name (e.g., `bg.session`), `secret` from config, `resave: false`, `saveUninitialized: false`, `proxy: true`, `store: new RedisStore({ client: redisClient, disableTouch: true })`. Derive cookie domain from request host via `URI(\`https://\${host}\`).domain()` and set `cookie: { ...conf.cookie, domain: \`.\${domain}\` }`. Optional: support dynamic `maxAge` from request body.

12. **Session tracking with Redis sorted sets**: wrap `req.logIn` and `req.logOut` to track active sessions in Redis sorted sets (key: `user:<userId>:sessions`, score: expiry timestamp). On login, check `redis.zcard(userKey)` against `ACTIVE_SESSION_LIMIT`; on logout, call `redis.zrem(userKey, \`sess:\${sessionId}\`)`. Remove expired sessions via `zremrangebyscore`.

13. **Passport.js integration**: configure passport strategies (local, google-oauth20, custom) and serialize/deserialize user via `passport.use(...)` and `passport.serializeUser/deserializeUser`. Apply `passport.initialize()` and `passport.session()` middleware after session middleware. Strategies live in `app/server/passport/`.

14. **Basic auth middleware**: use `express-basic-auth` with a static user map for internal or admin routes: `basicAuth({ users: { admin: 'secret' } })`. Apply selectively to routes requiring basic auth.

15. **Sentry integration**: require `@sentry/node` at the top, call `Sentry.init({ dsn, release: packageJson.version, environment })` if `sentry.dsn` is set, add `Sentry.Handlers.requestHandler({ request: true, ip: true, user: ['email'] })` early in middleware stack, and `Sentry.Handlers.errorHandler()` before the custom error handler. Capture unhandled exceptions via `process.on('uncaughtException', (err) => Sentry.captureException(err))`.

16. **New Relic integration**: require `newrelic` at the very top of `index.js` (before any other require). Configure via `newrelic.js` or env vars `NEW_RELIC_APP_NAME` and `NEW_RELIC_LICENSE_KEY`.

17. **Middleware composition in `middlewares/index.js`**: centralize middleware exports (`loggingMiddleware`, `sessionMW`, `sessionTrackerMW`, `nginxIngressParser`, `captchaValidatorMW`, `convertCredsToPlainText`, `passport`, etc.) to avoid scattered imports. Apply in order: timeout → Sentry request handler → cookie-parser → body-parser → custom header parser → request logger → CORS → session → passport → route-specific middlewares.

18. **Health check routes**: mount `GET /_healthz` and `GET /_readyz` early (before logging middleware) that return `{ ok: 'ok' }` with 200 status. These are used by Kubernetes liveness/readiness probes.

19. **Credential decryption middleware (optional)**: if `cred_encryption.disable === false`, apply a middleware that decrypts AES-encrypted credentials from request body/headers using a key and IV from config. Skip if encryption is disabled.

20. **Post-header-set middleware**: a custom middleware to inject or transform response headers based on config (e.g., setting custom headers for specific routes or server types).

## Skeleton / example

```javascript
// index.js (entrypoint with mode dispatch)
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

```javascript
// app/server/server.js (app factory with server-type dispatch)
const express = require('express');
const Sentry = require('@sentry/node');
const timeout = require('connect-timeout');
const bodyParser = require('body-parser');
const cors = require('cors');
const cookieParser = require('cookie-parser');
const swaggerJSDoc = require('swagger-jsdoc');

const conf = require('@configs');
const { swaggerSpec } = require('../../misc/generateSwagger');
const { loggingMiddleware } = require('@middlewares/request-logger');
const { nginxIngressParser } = require('@middlewares/ingress-parser');
const { sessionMW, sessionTrackerMW } = require('@middlewares/session');
const passport = require('@middlewares/passport');

const logger = require('@utils/logger')('server');

const getAppServer = (serverType) => {
  const app = express();
  app.disable('x-powered-by');

  app.use(timeout(10 * 1000));

  if (conf.sentry.dsn) {
    Sentry.init({ dsn: conf.sentry.dsn, environment: conf.sentry.environment });
    app.use(Sentry.Handlers.requestHandler({ request: true, ip: true, user: ['email'] }));
  }

  const checkHealth = (req, res) => res.json({ ok: 'ok' });
  app.get('/_healthz', checkHealth);
  app.get('/_readyz', checkHealth);

  if (conf.app_env === 'development' && conf.enableCORS) {
    const allowedHeaders = ['content-type', 'authorization', 'x-user-data', 'x-application-id'];
    const corsAllowedDomain = (req, callback) => {
      const corsOptions = { origin: true, credentials: true, maxAge: 86400, allowedHeaders };
      callback(null, corsOptions);
    };
    const setCORS = cors(corsAllowedDomain);
    app.use((req, res, next) => {
      if (req.header('X-Skip-Cors') !== 'true') setCORS(req, res, next);
      else next();
    });
  }

  app.use(cookieParser());
  app.use(bodyParser.json());
  app.use(nginxIngressParser);
  app.use(loggingMiddleware);

  // Session + Passport (if needed)
  app.use(sessionMW);
  app.use(sessionTrackerMW);
  app.use(passport.initialize());
  app.use(passport.session());

  app.get('/swagger.json', (req, res) => {
    res.setHeader('Content-Type', 'application/json');
    res.send(swaggerSpec);
  });

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
    logger.error(`requested url not found: ${req.originalUrl}`);
    next(err);
  });

  if (conf.sentry.dsn) app.use(Sentry.Handlers.errorHandler());

  // Custom error handler
  app.use((err, req, res, next) => {
    const status = err.statusCode || 500;
    if (status !== 404) logger.error(err.message);
    if (conf.sentry.dsn && status === 500) Sentry.captureException(err);

    res.status(status).json({
      success: false,
      status,
      message: err.message || err.toString(),
      stack: status === 404 || conf.app_env !== 'development' ? '' : err.stack,
      requestId: req.id,
    });
  });

  return app;
};

process.on('uncaughtException', (err) => {
  logger.error(err);
  if (conf.sentry.dsn) Sentry.captureException(err);
});

module.exports = { getAppServer };
```

```javascript
// config.js (convict hierarchical config)
const convict = require('convict');

const conf = convict({
  service_name: {
    doc: 'the name of service',
    format: String,
    default: '',
    env: 'SERVICE_NAME',
    arg: 'service_name',
  },
  mode: {
    doc: 'mode',
    format: ['consumer', 'server', 'worker'],
    default: '',
    env: 'MODE',
    arg: 'mode',
  },
  server_type: {
    doc: 'server type',
    format: ['panel', 'platform', 'admin', 'internal', 'webhook', 'ui'],
    default: '',
    env: 'SERVER_TYPE',
    arg: 'server_type',
  },
  app_env: {
    doc: 'App Env',
    format: ['production', 'development', 'test'],
    default: 'development',
    env: 'NODE_ENV',
    arg: 'node_env',
  },
  port: {
    doc: 'The port to bind',
    format: Number,
    default: '',
    env: 'PORT',
    arg: 'port',
  },
  enableCORS: {
    doc: 'enable cors in nodejs',
    format: Boolean,
    default: true,
    env: 'ENABLE_CORS',
    arg: 'enable_cors',
  },
  redis: {
    readWrite: {
      doc: 'redis url',
      format: String,
      default: '',
      env: 'REDIS_URL',
      arg: 'redis_url',
    },
  },
  postgres: {
    url: {
      doc: 'postgres url',
      format: String,
      default: '',
      env: 'POSTGRES_URL',
      arg: 'postgres_url',
    },
  },
  tokens: {
    sessionCookieName: {
      doc: 'session cookie name',
      format: String,
      default: 'app.session',
      env: 'SESSION_COOKIE_NAME',
      arg: 'session_cookie_name',
    },
    sessionSecret: {
      doc: 'session secret',
      format: String,
      default: '',
      env: 'SESSION_SECRET',
      arg: 'session_secret',
    },
  },
  cookie: {
    maxAge: {
      doc: 'cookie age in milliseconds',
      format: 'nat',
      default: 7 * 24 * 60 * 60 * 1000, // 7 days
      env: 'COOKIE_AGE',
      arg: 'cookie_age',
    },
    secure: 'auto',
    sameSite: 'none',
  },
  sentry: {
    dsn: {
      doc: 'sentry url',
      format: String,
      default: '',
      env: 'SENTRY_DSN',
      arg: 'sentry_dsn',
    },
    environment: {
      doc: 'sentry environment',
      format: String,
      default: '',
      env: 'SENTRY_ENVIRONMENT',
      arg: 'sentry_environment',
    },
  },
  newrelic_app: {
    doc: 'new relic app name',
    format: String,
    default: '',
    env: 'NEW_RELIC_APP_NAME',
    arg: 'new_relic_app_name',
  },
  newrelic_license_key: {
    doc: 'new relic license key',
    format: String,
    default: '',
    env: 'NEW_RELIC_LICENSE_KEY',
    arg: 'new_relic_license_key',
  },
});

try {
  conf.validate({ allowed: 'strict' });
} catch (err) {
  console.error(err);
}

module.exports = Object.assign(conf, conf.get());
```

```javascript
// registerAlias.js (module-alias setup)
const path = require('path');
const moduleAlias = require('module-alias');

moduleAlias.addAliases({
  '@controllers': path.join(__dirname, '/app/server/controllers'),
  '@services': path.join(__dirname, '/app/server/services'),
  '@models': path.join(__dirname, '/app/server/models'),
  '@validators': path.join(__dirname, '/app/server/validators'),
  '@middlewares': path.join(__dirname, '/app/server/middlewares'),
  '@utils': path.join(__dirname, '/app/common/util'),
  '@constants': path.join(__dirname, '/app/server/constants.js'),
  '@configs': path.join(__dirname, '/config.js'),
});

require('module-alias/register');
```

```javascript
// app/server/middlewares/request-logger.js (request logging with nanoid)
const { customAlphabet } = require('nanoid/non-secure');
const nanoid = customAlphabet('0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ', 8);
const logger = require('@utils/logger')('request-logger');

const METHODS_WITH_BODY = ['POST', 'PUT', 'PATCH'];
const URLS_TO_IGNORE = ['/_healthz', '/_readyz', '/swagger.json'];

const loggingMiddleware = (req, res, next) => {
  if (URLS_TO_IGNORE.includes(req.url)) return next();

  req.id = nanoid();
  const reqLog = { REQUEST_ID: req.id, METHOD: req.method, URL: req.originalUrl, IP: req.ip };

  if (METHODS_WITH_BODY.includes(req.method) && req.body) {
    const bodyLog = JSON.parse(JSON.stringify(req.body));
    if (req.body?.password) bodyLog.password = '*******';
    reqLog.BODY = bodyLog;
  }

  logger.info(reqLog);

  res.on('finish', () => {
    const resLog = { REQUEST_ID: req.id, STATUS: res.statusCode };
    logger.info(resLog);
  });

  return next();
};

module.exports = { loggingMiddleware };
```

```javascript
// app/server/middlewares/ingress-parser.js (x-user-data parser)
const logger = require('@utils/logger')('ingress-parser');
const conf = require('@configs');

const nginxIngressParser = (req, res, next) => {
  const userData = req.get('x-user-data');
  const whiteListedURL = ['/_healthz', '/_readyz', '/swagger.json'];

  if (!userData) {
    if (conf.server_type === 'admin' && !whiteListedURL.includes(req.originalUrl)) {
      const e = new Error(`x-user-data missing for: ${req.originalUrl}`);
      e.statusCode = 400;
      throw e;
    }
    return next();
  }

  try {
    const userJSON = JSON.parse(userData);
    req.userId = userJSON?._id;
    req.roleIds = userJSON?.roleIds;
    req.roleSlug = userJSON?.roleSlug;
    req.orgId = userJSON?.orgId;
    return next();
  } catch (error) {
    logger.error(`[nginxIngressParser] ${error.message}`);
    return next();
  }
};

module.exports = { nginxIngressParser };
```

## Anti-patterns to avoid

1. **Mounting all routes regardless of server type**: always gate routes by `serverType` to prevent exposing admin endpoints on platform servers or vice versa.
2. **Hardcoded secrets in config defaults**: use env vars for all sensitive values (session secrets, DB passwords, API keys).
3. **Skipping config validation**: always call `conf.validate({ allowed: 'strict' })` to catch misconfigurations early.
4. **Not masking sensitive fields in logs**: always redact `password`, `token`, `apiKey`, `secret` fields before logging request/response bodies.
5. **Missing Sentry request handler placement**: `Sentry.Handlers.requestHandler()` must come early in the middleware stack; `errorHandler()` must come after routes but before the custom error handler.
6. **Swallowing errors in middleware**: always propagate errors via `next(err)` instead of silently logging.
7. **Not setting `trust proxy`**: in production behind a reverse proxy, set `app.set('trust proxy', 1)` to extract correct client IPs from X-Forwarded-For.
8. **Using `res.send(err.stack)` in production**: only include stack traces when `app_env === 'development'`.
9. **Not handling timeouts**: apply `connect-timeout` early to prevent long-running requests from hanging.
10. **Ignoring uncaught exceptions**: always attach a `process.on('uncaughtException', ...)` handler to log and report to Sentry.
11. **CORS wildcard in production**: `allow_origins: ['*']` is unsafe; use explicit domain lists or dynamic origin validation.
12. **Not using module-alias for deep imports**: deep relative imports (`../../..`) are fragile; use `@controllers` aliases.
13. **Session middleware without Redis**: in multi-instance deployments, always use `RedisStore` instead of in-memory session store.
14. **Swagger base path mismatch**: ensure `swaggerSpec.paths` are rewritten to match the server type's actual base path (e.g., `/service/panel/users`).

## References

- [app-factory-and-mode-dispatch.md](references/app-factory-and-mode-dispatch.md) — app factory pattern, server-type dispatch, health checks
- [config-and-module-alias.md](references/config-and-module-alias.md) — convict hierarchical config, module-alias path mapping
- [middleware-patterns.md](references/middleware-patterns.md) — ingress parser, request logger, session tracking, error handling
- [repo-evidence.md](references/repo-evidence.md) — source file paths and snippets
- [backend-repo-architecture](../backend-repo-architecture/SKILL.md) — the Python/FastAPI analog for backend architecture patterns
