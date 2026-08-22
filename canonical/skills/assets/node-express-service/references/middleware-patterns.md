# Middleware Patterns

Production Express services use a layered middleware stack for request logging, header parsing, session management, and error handling. This document covers the custom middleware patterns observed in real services.

## Request logging with nanoid request IDs

Every request gets a unique ID for correlation across logs. Sensitive fields are masked before logging.

```javascript
// app/server/middlewares/request-logger.js
const { customAlphabet } = require('nanoid/non-secure');
const nanoid = customAlphabet('0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ', 8);
const logger = require('@utils/logger')('request-logger');

const METHODS_WITH_BODY = ['POST', 'PUT', 'PATCH'];
const URLS_TO_IGNORE = ['/_healthz', '/_readyz', '/swagger.json'];

const loggingMiddleware = (req, res, next) => {
  if (URLS_TO_IGNORE.includes(req.url)) return next();

  req.id = nanoid(); // 8-character alphanumeric ID
  const reqLog = { REQUEST_ID: req.id, METHOD: req.method, URL: req.originalUrl, IP: req.ip };

  // Log request body (if applicable)
  if (METHODS_WITH_BODY.includes(req.method) && req.body) {
    const bodyLog = JSON.parse(JSON.stringify(req.body));
    if (req.body?.password) bodyLog.password = '*******'; // Mask passwords
    reqLog.BODY = bodyLog;
  }

  logger.info(reqLog);

  // Log response status and headers on finish
  res.on('finish', () => {
    const resLog = { REQUEST_ID: req.id, STATUS: res.statusCode };
    logger.info(resLog);
  });

  return next();
};

module.exports = { loggingMiddleware };
```

**Key points**:
- **nanoid for request IDs**: 8-character alphanumeric IDs (collision-resistant for millions of requests).
- **Skip health checks**: avoid log noise by ignoring `/_healthz`, `/_readyz`, `/swagger.json`.
- **Mask sensitive fields**: always redact `password`, `token`, `apiKey`, `secret` before logging.
- **Log on finish**: use `res.on('finish', ...)` to capture final status code and headers.

## Ingress header parser (x-user-data)

Services behind an ingress gateway receive user context as a JSON header (`x-user-data`). This middleware parses it into `req.userId`, `req.roleIds`, etc.

```javascript
// app/server/middlewares/ingress-parser.js
const logger = require('@utils/logger')('ingress-parser');
const conf = require('@configs');

const nginxIngressParser = (req, res, next) => {
  const userData = req.get('x-user-data');
  const whiteListedURL = ['/_healthz', '/_readyz', '/swagger.json'];

  if (!userData) {
    // For admin servers, x-user-data is mandatory (except for health checks)
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
    req.userHubIds = userJSON?.userHubIds;
    req.account = userJSON?.account;
    req.orgId = userJSON?.orgId;

    // Allow superAdmin to override orgId via query param
    if (req.userId == '1' && req.query.orgId) {
      req.orgId = req.query.orgId;
    }

    return next();
  } catch (error) {
    logger.error(`[nginxIngressParser] ${error.message}`);
    return next(); // Don't fail the request on parse error
  }
};

module.exports = { nginxIngressParser };
```

**Key points**:
- **Whitelist health checks**: never reject health check requests due to missing headers.
- **Admin server enforcement**: for admin servers, `x-user-data` is mandatory (catches misconfigured ingress).
- **Graceful parse errors**: log and continue if JSON parsing fails (avoids 500s on malformed headers).
- **SuperAdmin org override**: allow root user (userId === '1') to impersonate orgs via `?orgId=...` query param.

## Redis-backed sessions with connect-redis

Sessions are stored in Redis (not in-memory) to support horizontal scaling.

```javascript
// app/server/middlewares/session.js
const URI = require('urijs');
const expressSession = require('express-session');
const RedisStore = require('connect-redis')(expressSession);
const conf = require('@configs');
const { getRedis } = require('@connections/redis');

const redisClient = getRedis();

const { getHost } = require('@utils/express.util');

const sessionMW = (req, res, next) => {
  const host = getHost(req);
  let domain;
  if (host) domain = URI(`https://${host}`).domain(); // Extract domain from host

  const middleware = expressSession({
    store: new RedisStore({ client: redisClient, disableTouch: true }),
    name: conf.tokens.sessionCookieName,
    secret: conf.tokens.sessionSecret,
    resave: false,
    proxy: true, // Trust X-Forwarded-For headers
    saveUninitialized: false,
    cookie: {
      ...conf.cookie,
      ...(domain ? { domain: `.${domain}` } : {}), // Set cookie domain dynamically
    },
  });

  middleware(req, res, next);
};

module.exports = { sessionMW };
```

**Key points**:
- **RedisStore with `disableTouch: true`**: avoids unnecessary session updates on every request (reduces Redis writes).
- **Dynamic cookie domain**: extract domain from request host and set cookie domain to `.example.com` for subdomain sharing.
- **`proxy: true`**: required when behind a reverse proxy to extract correct client IP.
- **`saveUninitialized: false`**: don't create sessions for unauthenticated requests (reduces Redis bloat).

## Session tracking with active session limits

Track active sessions per user in a Redis sorted set and enforce a limit.

```javascript
// app/server/middlewares/session.js (extended)
const { userKey } = require('@helpers/session.helper');

const ACTIVE_SESSION_LIMIT = 5;

function login(req, res, redis) {
  const oldLogIn = req.logIn;

  return async (user, options, done) => {
    if (typeof options === 'function') {
      done = options;
      options = {};
    }
    if (!user.active) return done(new Error('This user has been disabled'));

    // Check active session limit
    const activeSessions = await redis.zcard(userKey(user._id));
    if (activeSessions >= ACTIVE_SESSION_LIMIT) {
      return done(new Error(`Active session limit: ${ACTIVE_SESSION_LIMIT} exceeded`));
    }

    // Perform login
    oldLogIn.call(req, user, options, async () => {
      req.session.misc = {
        ip: req.ip,
        user_agent: req.headers['user-agent'],
        sessionCreatedAt: new Date().toISOString(),
      };

      const sessionId = req.sessionID;
      const key = userKey(user._id);
      const age = req.session.cookie.maxAge;

      try {
        const transaction = redis.multi();
        transaction.zremrangebyscore(key, -1, `(${Date.now()}`); // Remove expired sessions
        transaction.zadd(key, Date.now() + age, `sess:${sessionId}`); // Add new session
        transaction.expire(key, age / 1000); // Set key expiry
        await transaction.exec();
        done();
      } catch (err) {
        logger.error(err);
        done(err);
      }
    });
  };
}

const sessionTrackerMW = (req, res, next) => {
  req.login = login(req, res, redisClient);
  req.logIn = login(req, res, redisClient);
  next();
};

module.exports = { sessionMW, sessionTrackerMW };
```

**Key points**:
- **Sorted set per user**: key format `user:<userId>:sessions`, members are `sess:<sessionId>`, scores are expiry timestamps.
- **Limit enforcement**: reject login if `zcard(userKey)` exceeds threshold.
- **Auto-cleanup**: `zremrangebyscore(key, -1, <now>)` removes expired sessions before adding a new one.
- **Transaction safety**: use `redis.multi()` to ensure atomicity.

## Custom error handler with statusCode convention

All errors are funneled through a custom error handler that logs, reports to Sentry, and returns structured JSON.

```javascript
// app/server/server.js (error handler at end of middleware stack)
app.use((err, req, res, next) => {
  const status = err.statusCode || 500;

  if (status !== 404) {
    logger.error(err.message);
    if (conf.sentry.dsn && status === 500) {
      Sentry.captureException(err);
    }
  }

  res.status(status).json({
    success: false,
    status,
    message: err.message || err.toString(),
    stack: status === 404 || conf.app_env !== 'development' ? '' : err.stack,
    requestId: req.id, // From logging middleware
  });
});
```

**Key points**:
- **statusCode convention**: set `err.statusCode` to control HTTP status (defaults to 500).
- **Skip 404 logging**: 404s are expected and don't warrant error logs.
- **Sentry for 500s**: only capture 500s (not 4xx client errors).
- **Hide stack in production**: only include `err.stack` in development.
- **Request correlation**: include `requestId` in response for log correlation.

## Middleware order

```javascript
app.use(timeout(10 * 1000));                  // 1. Request timeout
app.use(Sentry.Handlers.requestHandler(...)); // 2. Sentry request context
app.use(cookieParser());                      // 3. Cookie parsing
app.use(bodyParser.json());                   // 4. Body parsing
app.use(nginxIngressParser);                  // 5. Parse x-user-data header
app.use(loggingMiddleware);                   // 6. Request logging
app.use(cors(...));                           // 7. CORS (if enabled)
app.use(sessionMW);                           // 8. Session loading
app.use(sessionTrackerMW);                    // 9. Session tracking
app.use(passport.initialize());               // 10. Passport initialization
app.use(passport.session());                  // 11. Passport session

// Routes
app.use('/api', apiRouter);

// Error handlers
app.use(Sentry.Handlers.errorHandler());      // 12. Sentry error handler
app.use((err, req, res, next) => { ... });    // 13. Custom error handler
```

**Critical order constraints**:
- **timeout must come first** (before any async work).
- **body-parser before any middleware that reads req.body**.
- **ingress parser before logging** (to include userId in logs).
- **session before passport** (passport needs session).
- **Sentry error handler before custom error handler** (to capture errors before response is sent).

## CORS for development

```javascript
if (conf.app_env === 'development' && conf.enableCORS) {
  const allowedHeaders = ['content-type', 'authorization', 'x-user-data', 'x-application-id'];
  const exposedHeaders = ['Accept-Ranges', 'Content-Range'];

  const corsAllowedDomain = (req, callback) => {
    const corsOptions = { origin: true, credentials: true, maxAge: 86400, allowedHeaders, exposedHeaders };
    callback(null, corsOptions);
  };

  const setCORS = cors(corsAllowedDomain);
  app.use((req, res, next) => {
    if (req.header('X-Skip-Cors') !== 'true') setCORS(req, res, next);
    else next();
  });
}
```

**Key points**:
- **Development only**: CORS is handled by ingress in production.
- **Dynamic origin**: `origin: true` allows any origin (acceptable in dev, unsafe in prod).
- **Explicit headers**: list all custom headers (x-user-data, x-application-id, etc.).
- **Skip CORS header**: allow `X-Skip-Cors: true` to bypass CORS for testing.
