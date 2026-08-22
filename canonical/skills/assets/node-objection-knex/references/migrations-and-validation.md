# Migrations and Validation Patterns

Knex migration workflow and Joi validation middleware for Express routes.

## knexfile.js Configuration

```javascript
// db/knexfile.js
const path = require('path');
const config = require('../config');

module.exports = {
  client: 'pg',
  connection: config.databaseUrl, // or config.postgres[process.env.SERVICE_NAME]
  migrations: {
    directory: path.join(__dirname, './migrations'),
  },
};
```

**Common patterns:**
- Load connection string from `config` or environment variable
- Use `process.env.SERVICE_NAME` or similar to switch connection strings per environment
- Set `migrations.directory` to `./migrations` or `./db/migrations`

## Migration Workflow

**Create a migration:**

```bash
npx knex migrate:make create_users_table
```

**Run migrations:**

```bash
npx knex migrate:latest
```

**Rollback last migration:**

```bash
npx knex migrate:rollback
```

**Migration file structure:**

```javascript
// db/migrations/20240828_create_users_table.js
exports.up = async (knex) => {
  await knex.schema.createTable('users', (table) => {
    table.increments('_id').primary();
    table.string('email', 64).notNullable().unique();
    table.string('firstName', 32).notNullable();
    table.string('lastName', 32).notNullable();
    table.string('hash', 255);
    table.string('salt', 255);
    table.boolean('active').defaultTo(true);
    table.timestamp('createdAt').notNullable().defaultTo(knex.fn.now());
    table.timestamp('updatedAt').notNullable().defaultTo(knex.fn.now());
    table.jsonb('meta');
  });
};

exports.down = async (knex) => {
  await knex.schema.dropTableIfExists('users');
};
```

## Common Migration Patterns

**UUID primary key:**

```javascript
table.uuid('id').primary().defaultTo(knex.raw('gen_random_uuid()'));
```

**Foreign key constraints:**

```javascript
table.integer('user_id').notNullable();
table.foreign('user_id').references('_id').inTable('users');
```

**JSONB column:**

```javascript
table.jsonb('meta');
table.jsonb('settings').defaultTo('{}');
```

**Timestamps with defaults:**

```javascript
table.timestamp('createdAt').notNullable().defaultTo(knex.fn.now());
table.timestamp('updatedAt').notNullable().defaultTo(knex.fn.now());
```

**Unique constraints:**

```javascript
table.string('email', 64).notNullable().unique();
table.unique(['userId', 'orgId']); // composite unique
```

**Indexes:**

```javascript
table.index('email');
table.index(['orgId', 'active']);
```

**Enum-like columns:**

```javascript
table.enu('status', ['pending', 'active', 'inactive']).defaultTo('pending');
```

## Full Migration Example with Foreign Keys

```javascript
// db/migrations/20240828_create_audit_logs_table.js
exports.up = async (knex) => {
  await knex.schema.createTable('audit_logs', (table) => {
    table.uuid('id').primary().defaultTo(knex.raw('gen_random_uuid()'));
    table.integer('user_id').notNullable();
    table.integer('org_id').notNullable();
    table.integer('role_id').notNullable();
    table.string('action', 255).notNullable();
    table.integer('created_by').notNullable();
    table.timestamp('timestamp').notNullable().defaultTo(knex.fn.now());
    table.jsonb('meta');
    table.string('file_path', 255);

    table.foreign('user_id').references('_id').inTable('users');
    table.foreign('org_id').references('_id').inTable('organizations');
    table.foreign('role_id').references('_id').inTable('roles');
    table.foreign('created_by').references('_id').inTable('users');
  });
};

exports.down = async (knex) => {
  await knex.schema.dropTableIfExists('audit_logs');
};
```

## Joi Validation Middleware

**commonUtil.js (middleware factory):**

```javascript
// validators/commonUtil.js
const validateReq =
  (schema, type = 'body') =>
  async (req, res, next) => {
    try {
      let param;

      switch (type) {
        case 'body':
          param = req.body;
          break;
        case 'query':
          param = req.query;
          break;
        default:
          throw new Error('Type not supported in [validateReq]');
      }

      const { error, value } = schema.validate(param, { abortEarly: false });

      if (error) {
        return res.status(400).json({
          success: false,
          status: 400,
          message: 'Invalid request parameters',
          errors: error.details
            ? error.details.map((detail) => detail.message)
            : ['Validation failed'],
        });
      }

      req.body = value; // replace with validated/coerced value
      return next();
    } catch (err) {
      return res.status(500).json({
        success: false,
        status: 500,
        message: 'Internal Server Error',
        error: err.message || 'Unknown validation error occurred',
      });
    }
  };

module.exports = { validateReq };
```

**Key features:**
- `abortEarly: false` — collect all validation errors, not just the first
- Replace `req.body` with validated/coerced value from Joi
- Standardized error envelope: `{ success, status, message, errors: [...] }`
- Support for validating `body` or `query` params via `type` parameter

## Shared Validation Rules (commonRules.js)

```javascript
// validators/commonRules.js
const Joi = require('joi');

const PHONE_NUMBER_VALIDATOR = new RegExp('^\\d{6,10}');
const PASSWORD_VALIDATOR = new RegExp('^(?=.*?[A-Z])(?=.*?[a-z])(?=.*?[0-9])(?=.*?[#?!@$ %^&*-]).{8,}$');

const commonValidationRules = {
  firstName: Joi.string()
    .trim()
    .alphanum()
    .min(1)
    .max(32)
    .pattern(/^[A-Za-z]+$/)
    .messages({
      'string.base': 'firstName must be a string',
      'string.empty': 'firstName cannot be empty',
      'string.min': 'firstName must have at least {#limit} character',
      'string.max': 'firstName cannot exceed {#limit} characters',
      'string.pattern.base': 'firstName must only contain alphabets',
    }),
  lastName: Joi.string()
    .trim()
    .alphanum()
    .min(1)
    .max(32)
    .pattern(/^[A-Za-z]+$/)
    .messages({
      'string.base': 'lastName must be a string',
      'string.empty': 'lastName cannot be empty',
      'string.pattern.base': 'lastName must only contain alphabets',
    }),
  email: Joi.string().trim().email().lowercase().messages({
    'string.email': 'Invalid email',
  }),
  password: Joi.string()
    .pattern(PASSWORD_VALIDATOR)
    .messages({
      'string.pattern.base':
        'Password must contain at least 8 characters, including upper+lower case, digit & special character',
    }),
  phoneNumber: Joi.string().pattern(PHONE_NUMBER_VALIDATOR).messages({
    'string.pattern.base': 'Invalid phone number',
  }),
  userId: Joi.number().integer().positive(),
  active: Joi.boolean(),
};

module.exports = { commonValidationRules };
```

**Best practices:**
- Define reusable rules once, compose them into per-route schemas
- Use `.messages({})` to customize error messages per validation rule
- Use `.trim()` and `.lowercase()` for normalization
- Define regex validators as constants for reuse

## Composing Schemas from Common Rules

```javascript
// validators/userValidator.js
const Joi = require('joi');
const {
  commonValidationRules: { firstName, lastName, password, email, phoneNumber },
} = require('./commonRules');

const registerUserSchema = Joi.object({
  email: email.required(),
  firstName: firstName.required(),
  lastName: lastName.required(),
  password: password.required(),
  phoneNumber: phoneNumber.required(),
  inviteCode: Joi.string().trim().length(8),
});

const loginSchema = Joi.object({
  email: email.required(),
  password: Joi.string().required(), // plain string, detailed validation in handler
});

const searchSchema = Joi.object({
  email: email.required(),
});

module.exports = { registerUserSchema, loginSchema, searchSchema };
```

**Pattern:**
- Import common rules and mark them `.required()` or optional per schema
- Override specific rules when needed (e.g., password validation for login is just `.string().required()` to avoid revealing password rules in error messages)
- Add route-specific fields (e.g., `inviteCode`) directly in the schema

## Using validateReq in Routes

```javascript
// routes/user.routes.js
const express = require('express');
const router = express.Router();
const { validateReq } = require('../validators/commonUtil');
const { registerUserSchema, searchSchema } = require('../validators/userValidator');
const userModel = require('../models/user.model');

router.post('/register', validateReq(registerUserSchema), async (req, res, next) => {
  try {
    const user = await userModel.create(req.body);
    res.status(201).json({
      success: true,
      message: 'User registered',
      data: { user },
    });
  } catch (err) {
    next(err);
  }
});

router.get('/search', validateReq(searchSchema, 'query'), async (req, res, next) => {
  const { email } = req.query;
  try {
    const user = await userModel.getUserByEmail(email);
    if (!user) {
      return res.status(404).json({
        success: false,
        message: 'User not found',
      });
    }
    res.status(200).json({
      success: true,
      message: 'User found',
      data: { user },
    });
  } catch (err) {
    next(err);
  }
});

module.exports = router;
```

**Pattern:**
- Apply `validateReq(schema)` middleware before route handler
- Use `validateReq(schema, 'query')` for GET routes with query params
- Route handler receives validated/coerced data in `req.body` or `req.query`
- Validation errors are caught and formatted as 400 responses by the middleware

## Standardized Response Envelope

All responses use the same envelope structure:

**Success:**

```json
{
  "success": true,
  "status": 200,
  "message": "User registered",
  "data": { "user": { ... } }
}
```

**Validation error:**

```json
{
  "success": false,
  "status": 400,
  "message": "Invalid request parameters",
  "errors": [
    "firstName must only contain alphabets",
    "password must contain at least 8 characters, including upper+lower case, digit & special character"
  ]
}
```

**Server error:**

```json
{
  "success": false,
  "status": 500,
  "message": "Internal Server Error",
  "error": "Unexpected error occurred"
}
```

**Best practice:**
- Consistent envelope across all routes (success/error)
- `errors` field is an array to support multiple validation errors
- `status` field mirrors HTTP status code for client-side parsing
