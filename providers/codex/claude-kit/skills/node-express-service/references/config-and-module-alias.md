# Hierarchical Config and Module-Alias

Production Express services use **convict** for hierarchical, validated configuration and **module-alias** for clean import paths.

## Convict hierarchical config

Convict provides schema-driven configuration with env var overrides, format validation, and strict mode to catch typos.

```javascript
// config.js
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
    doc: 'app mode',
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
    format: 'port', // built-in validator for port numbers
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
    },
    sessionSecret: {
      doc: 'session secret',
      format: String,
      default: '',
      env: 'SESSION_SECRET',
    },
  },
  cookie: {
    maxAge: {
      doc: 'cookie age in milliseconds',
      format: 'nat', // natural number
      default: 7 * 24 * 60 * 60 * 1000, // 7 days
      env: 'COOKIE_AGE',
    },
    secure: 'auto', // auto-detect HTTPS
    sameSite: 'none',
  },
  sentry: {
    dsn: {
      doc: 'sentry DSN',
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
  newrelic_app: {
    doc: 'new relic app name',
    format: String,
    default: '',
    env: 'NEW_RELIC_APP_NAME',
  },
  newrelic_license_key: {
    doc: 'new relic license key',
    format: String,
    default: '',
    env: 'NEW_RELIC_LICENSE_KEY',
  },
});

try {
  conf.validate({ allowed: 'strict' }); // Fail on unknown env vars
} catch (err) {
  console.error(err); // Use console instead of logger to avoid circular dependency
}

module.exports = Object.assign(conf, conf.get());
```

**Key points**:
- **Strict validation**: `conf.validate({ allowed: 'strict' })` rejects unknown env vars (catches typos like `PORT` vs `PROT`).
- **Format validators**: use `'port'`, `'nat'`, `Boolean`, `['value1', 'value2']` to enforce types and enums.
- **Dual access**: `Object.assign(conf, conf.get())` allows both `conf.get('port')` and `conf.port`.
- **No secrets in defaults**: sensitive values (session secrets, DB passwords) default to `''` and must be set via env vars.

## Module-alias path mapping

Deep relative imports (`require('../../../app/server/controllers/user.controller')`) are fragile and hard to refactor. Module-alias maps `@controllers`, `@services`, etc. to absolute paths.

```javascript
// registerAlias.js (or top of index.js)
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
  '@connections': path.join(__dirname, '/connections'),
  '@events': path.join(__dirname, '/app/server/events'),
});

require('module-alias/register');
```

**Usage**:
```javascript
// Before
const userController = require('../../../app/server/controllers/user.controller');
const logger = require('../../common/util/logger');

// After
const userController = require('@controllers/user.controller');
const logger = require('@utils/logger');
```

**Setup**:
1. Require `registerAlias.js` at the very top of `index.js` (before any other requires).
2. All aliases must be absolute paths (`path.join(__dirname, ...)`) to avoid resolution issues.
3. Use `@` prefix to distinguish aliases from npm packages (convention, not required).

## Typical config hierarchy

```
config.js               # Service-level config (mode, server_type, port, env)
  ├── redis.readWrite   # Redis connection strings
  ├── postgres.url      # DB connection
  ├── tokens            # Session secrets, cookie names
  ├── sentry            # Error tracking
  ├── newrelic          # APM
  ├── smtp              # Email provider (SendGrid/Twilio)
  └── kafka             # Kafka brokers, consumer groups
```

## Validation patterns

```javascript
// Enum validation
format: ['production', 'development', 'test']

// Port number (1-65535)
format: 'port'

// Natural number (non-negative integer)
format: 'nat'

// Boolean
format: Boolean

// String (any value)
format: String

// Number (any numeric value)
format: Number

// Email
format: 'email'

// URL
format: 'url'

// IP address
format: 'ipaddress'
```

## Environment variable override priority

1. Command-line args (`--port=8080`)
2. Environment variables (`PORT=8080`)
3. Defaults in schema

**Best practice**: Use env vars for all deployment-specific values. Reserve defaults for development-only settings.
