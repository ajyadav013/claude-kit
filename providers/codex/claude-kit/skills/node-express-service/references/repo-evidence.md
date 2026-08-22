# Repository Evidence

This document provides short, genericized snippets from real production codebases that ground the patterns in this skill. All internal identifiers, company names, service names, and filesystem paths have been removed or replaced with generic placeholders.

## Mode dispatch (index.js)

**File**: `index.js` (entrypoint)

```javascript
require('newrelic');
require('./instrument');

const conf = require('./config');
const logger = require('./app/common/winston')('index');

process.setMaxListeners(30);

switch (conf.mode) {
  case 'server':
    require('./app/server');
    break;
  default:
    logger.error('Unknown app mode');
    break;
}
```

**Pattern**: Mode-based dispatch to start different app types (server, consumer, worker) from a single codebase.

---

## App factory with server-type dispatch

**File**: `app/server/app.js`

```javascript
const express = require('express');
const Sentry = require('@sentry/node');
const bodyParser = require('body-parser');
const cors = require('cors');
const timeout = require('connect-timeout');

const conf = require('../../config');
const logger = require('../common/winston')('app');
const { requestLoggingMW } = require('./middlewares');

const app = new express();
app.disable('x-powered-by');
app.use(timeout(30 * 1000));

logger.info(`App running in ${conf.app_env} mode`);

if (conf.app_env !== 'test') {
  app.set('trust proxy', 1);
}

app.use(require('cookie-parser')());
app.use(bodyParser.json());
app.use(requestLoggingMW);

// Mount routes based on server type
switch (conf.server_type) {
  case 'internal':
    logger.info('Mounting [INTERNAL] routes');
    require('./routes/internal')(app);
    break;
  case 'panel':
    logger.info('Mounting [PANEL] routes');
    require('./routes/panel')(app);
    break;
  case 'platform':
    logger.info('Mounting [Platform] routes');
    require('./routes/platform')(app);
    break;
  case 'admin':
    logger.info('Mounting [ADMIN] routes');
    require('./routes/administrator')(app);
    break;
  case 'webhook':
    logger.info('Mounting [WEBHOOK] routes');
    require('./routes/webhook')(app);
    break;
  default:
    logger.info('No matching server type');
    break;
}

// 404 handler
app.use((req, res, next) => {
  const err = new Error('Not Found');
  err.statusCode = 404;
  logger.error(`requested url not found: ${req.originalUrl}`);
  next(err);
});

// Custom error handler
app.use((err, req, res, next) => {
  const status = Number(err.statusCode) || 500;
  if (status !== 404) logger.error(err.message);

  const customErrorObj = {
    success: false,
    status,
    message: err.message || err.toString(),
    stack: Number(err.statusCode) === 404 || conf.app_env !== 'development' ? '' : err.stack,
    requestId: req.id,
  };

  if (conf.sentry.dsn && status === 500) Sentry.captureException(err);
  res.status(status).json(customErrorObj);
});

module.exports = { app };
```

**Pattern**: Conditional route mounting based on `server_type` config; custom error handler with statusCode convention.

---

## Convict hierarchical config

**File**: `config.js`

```javascript
const convict = require('convict');

const conf = convict({
  mode: {
    doc: 'mode',
    format: ['consumer', 'server'],
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
    format: ['production', 'development', 'pre-production', 'test'],
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
  cookie: {
    maxAge: {
      doc: 'cookie age',
      format: 'nat',
      default: 7 * 24 * 60 * 60 * 1000,
      env: 'COOKIE_AGE',
      arg: 'cookie_age',
    },
    secure: 'auto',
    sameSite: 'none',
  },
  tokens: {
    sessionCookieName: {
      doc: 'session cookie name',
      format: String,
      default: 'app.session',
      env: 'SESSION_COOKIE_NAME',
    },
    sessionSecret: {
      doc: 'session secret',
      format: String,
      default: '',
      env: 'SESSION_SECRET',
    },
  },
  sentry: {
    dsn: {
      doc: 'sentry url',
      format: String,
      default: '',
      env: 'SENTRY_DSN',
    },
    environment: {
      doc: 'sentry environment',
      format: String,
      default: '',
      env: 'SENTRY_ENVIRONMENT',
    },
  },
});

try {
  conf.validate({ allowed: 'strict' });
} catch (err) {
  console.error(err);
}

module.exports = Object.assign(conf, conf.get());
```

**Pattern**: Schema-driven config with format validation, strict mode, and dual access (`.get()` and direct property access).

---

## Module-alias setup

**File**: `registerAlias.js`

```javascript
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

**Pattern**: Absolute path mapping for clean imports.

---

## Request logging with nanoid

**File**: `app/server/middlewares/request-logger.js`

```javascript
const { customAlphabet } = require('nanoid/non-secure');
const nanoid = customAlphabet('0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ', 8);
const logger = require('../../common/winston')('request-logger');

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

**Pattern**: Unique request IDs, password masking, response logging on finish.

---

## Ingress header parser

**File**: `app/server/middlewares/ingress-parser.js`

```javascript
const logger = require('../../common/winston')('ingress-MW');
const conf = require('../../../config');

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

    if (req.userId == '1' && req.query.orgId) req.orgId = req.query.orgId;

    return next();
  } catch (error) {
    logger.error(`[nginxIngressParser] ${error.message}`);
    return next();
  }
};

module.exports = { nginxIngressParser };
```

**Pattern**: Parse JSON header into request properties; enforce presence for admin servers; allow superAdmin org override.

---

## Redis-backed sessions

**File**: `app/server/middlewares/session.js`

```javascript
const URI = require('urijs');
const expressSession = require('express-session');
const RedisStore = require('connect-redis')(expressSession);
const conf = require('../../../config');
const { getRedis } = require('../../common/init');

const redisClient = getRedis();
const { getHost } = require('../../common/util/express.util');

const sessionMW = (req, res, next) => {
  const host = getHost(req);
  let domain;
  if (host) domain = URI(`https://${host}`).domain();

  const middleware = expressSession({
    store: new RedisStore({ client: redisClient, disableTouch: true }),
    name: conf.tokens.sessionCookieName,
    secret: conf.tokens.sessionSecret,
    resave: false,
    proxy: true,
    saveUninitialized: false,
    cookie: { ...conf.cookie, ...(domain ? { domain: `.${domain}` } : {}) },
  });

  middleware(req, res, next);
};

module.exports = { sessionMW };
```

**Pattern**: RedisStore with dynamic cookie domain extraction.

---

## Swagger docs with server-type base paths

**File**: `app/server/app.js` (swagger setup)

```javascript
const swaggerJSDoc = require('swagger-jsdoc');
const YAML = require('json2yaml');
const glob = require('glob');
const path = require('path');

const apiRoutesDir = [];
let basePath;

if (conf.server_type === 'panel') {
  apiRoutesDir.push(`${path.resolve(__dirname, './swaggerDefinition/panel/*.js')}`);
  basePath = '/service/panel/users';
} else if (conf.server_type === 'platform') {
  apiRoutesDir.push(`${path.resolve(__dirname, './swaggerDefinition/platform/*.js')}`);
  basePath = '/service/platform/users';
} else if (conf.server_type === 'internal') {
  apiRoutesDir.push(`${path.resolve(__dirname, './swaggerDefinition/internal/*.js')}`);
  basePath = '/service/__internal/users';
}

const modelsDir = `${path.resolve(__dirname, './models/swagger')}/**/*.yaml`;
const swaggerOptions = {
  swaggerDefinition: {
    info: { title: 'Service API', version: '1.0.0' },
    openapi: '3.0.2',
  },
  apis: [...apiRoutesDir, modelsDir],
};

const swaggerSpec = swaggerJSDoc(swaggerOptions);
swaggerSpec.paths = Object.entries(swaggerSpec.paths).reduce((paths, [k, v]) => {
  paths[basePath + k] = v;
  return paths;
}, {});

app.get('/swagger.json', (req, res) => {
  res.setHeader('Content-Type', 'application/json');
  res.send(swaggerSpec);
});
```

**Pattern**: Conditional swagger API file loading and base path injection per server type.

---

## Middleware centralization

**File**: `app/server/middlewares/index.js`

```javascript
const { loggingMiddleware } = require('./request-logger');
const { sessionMW, sessionTrackerMW } = require('./session');
const passport = require('./passport');
const { nginxIngressParser } = require('./ingress-parser');

module.exports = {
  requestLoggingMW: loggingMiddleware,
  sessionMW,
  sessionTrackerMW,
  passport,
  nginxIngressParser,
};
```

**Pattern**: Single export point for all custom middleware.

---

## Notes

- All file paths, service names, and company identifiers have been replaced with generic placeholders.
- No secret values or credentials are included.
- Snippets are representative of the real code structure but simplified for clarity.
- Patterns are derived from multiple production services to ensure generalizability.
