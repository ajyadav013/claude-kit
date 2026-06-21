---
name: node-objection-knex
description: Encodes production Objection.js + Knex data layer patterns covering BaseModel with AJV validation, lifecycle hooks, bindKnex() per connection, Knex query builder, migration workflow, and Joi request validation middleware with standardized error envelopes. Use when building an Express service with Postgres, implementing request validation, defining Objection models, or managing database migrations with Knex.
---

Standardize Objection.js model definitions, Knex query patterns, migration workflow, and Joi validation middleware for Express services.

## When to use

- Scaffolding a new Express service with Postgres and Objection.js
- Defining Objection models with AJV jsonSchema validation and lifecycle hooks
- Implementing BaseModel patterns for reusable model logic (validation, formatting)
- Building request validation middleware with Joi for Express routes
- Setting up Knex migrations and knexfile.js configuration
- Creating non-table models (query builder factories) for flexible queries
- Implementing password hashing, sensitive field stripping, or timestamp management in models
- Adding custom validation rules and error formatting to request handlers
- Migrating from raw SQL or Sequelize to Objection.js + Knex
- Standardizing validation error responses with `{ success, status, message, errors[] }` envelope

## Core conventions

1. **BaseModel with AJV validator**: create a `BaseModel` extending `objection.Model` that defines `createValidator()` returning an `AjvValidator` with `ajv-formats` support. Set `options: { allErrors: true, validateSchema: false, ownProperties: true }` to collect all validation errors. All domain models inherit from `BaseModel`.

2. **Static jsonSchema per model**: each model defines `static get jsonSchema()` returning AJV schema with `type`, `required`, and `properties` (including format validators like `date-time`). Objection validates against this schema on insert/update.

3. **Lifecycle hooks for data normalization**: use `$beforeInsert()` to set timestamps (`createdAt`, `updatedAt`), normalize fields (lowercase email, capitalize names), and call custom validation. Use `$beforeUpdate()` to update `updatedAt`, delete immutable fields like `createdAt`, and revalidate. Use `$afterDelete()` for cleanup (e.g., delete related sessions).

4. **$formatJson() to strip sensitive fields**: override `$formatJson(json)` to remove sensitive fields (`hash`, `salt`) from serialized output. Always call `super.$formatJson(json)` first, then destructure and return sanitized object.

5. **bindKnex() per connection**: models are bound to a Knex instance via `module.exports = MyModel.bindKnex(getConnection())`. This allows using the same model class with different databases or connections (multi-tenant, read replicas).

6. **Static vs instance methods**: static methods (`create()`, `getUserById()`, `getUserByEmail()`) use `this.query()` for queries. Instance methods use `this.$query()` to operate on the current instance (e.g., `user.$query().patch({ active: false })`). Use `patchAndFetchById()` or `updateAndFetch()` to apply updates and retrieve the updated row in one call.

7. **Non-table models (query builder factories)**: for tables not represented by Objection models, export query builder factories like `const orgModel = () => knex('organizations')`. These return fresh query builders for ad-hoc queries without full model lifecycle.

8. **Knexfile.js configuration**: define `client: 'pg'`, `connection` (from config), and `migrations: { directory: path.join(__dirname, './migrations') }`. Use `process.env.SERVICE_NAME` or similar to switch connection strings per environment.

9. **Migration workflow**: generate migrations with `knex migrate:make <name>`, define `exports.up` and `exports.down` functions that use `knex.schema.createTable()` / `dropTableIfExists()`. Common patterns: `table.uuid('id').primary().defaultTo(knex.raw('gen_random_uuid()'))`, `table.foreign('user_id').references('_id').inTable(USER_TABLE)`, `table.timestamp('created_at').defaultTo(knex.fn.now())`, `table.jsonb('meta')`.

10. **Joi validation middleware (validateReq)**: create a higher-order middleware `validateReq(schema, type = 'body')` that validates `req.body` or `req.query` using the provided Joi schema. Set `{ abortEarly: false }` to collect all validation errors. On error, return `{ success: false, status: 400, message: 'Invalid request parameters', errors: error.details.map(d => d.message) }`.

11. **Shared commonRules module**: define reusable Joi validation rules in `commonRules.js` (e.g., `firstName`, `lastName`, `email`, `password`, `phoneNumber`). Each rule uses `.messages({})` to customize error messages. Import and compose these rules in per-route schemas (e.g., `registerUserSchema`, `loginWithPasswordSchema`).

12. **Standardized error envelope**: all validation errors return `{ success: boolean, status: number, message: string, errors: string[] }`. Success responses use the same envelope with `success: true, data: {...}, message: '...'`.

13. **Custom Joi patterns and messages**: use `Joi.string().pattern(REGEX).messages({ 'string.pattern.base': 'Custom error' })` for phone numbers, passwords, usernames. Use `Joi.alternatives([...])` for fields that accept multiple formats (e.g., email or phone).

14. **Custom validation functions in models**: define a standalone `validate(model)` function that throws `objection.ValidationError({ message, type })` for domain-specific checks (e.g., email format, URL format). Call this from `$beforeInsert()` and `$beforeUpdate()`.

15. **Password hashing in model setters**: use `set password(password)` to intercept password assignment, hash with `pbkdf2Sync(password, salt, 27500, 64, 'sha256')`, and store `hash` and `salt` on the model. Define `verifyPassword(password, callback)` instance method to compare hashes asynchronously.

## Skeleton / example

```javascript
// models/base.model.js
const addFormats = require('ajv-formats');
const { Model, AjvValidator } = require('objection');

class BaseModel extends Model {
  static createValidator() {
    return new AjvValidator({
      onCreateAjv: (ajv) => {
        addFormats(ajv);
      },
      options: {
        allErrors: true,
        validateSchema: false,
        ownProperties: true,
      },
    });
  }
}

module.exports = BaseModel;
```

```javascript
// models/user.model.js
const { pbkdf2Sync, pbkdf2, randomBytes } = require('crypto');
const objection = require('objection');
const BaseModel = require('./base.model');
const { getConnection } = require('../db.init');

class User extends BaseModel {
  static get tableName() {
    return 'users';
  }

  static get idColumn() {
    return '_id';
  }

  static get jsonSchema() {
    return {
      type: 'object',
      required: ['email', 'firstName', 'lastName'],
      properties: {
        _id: { type: 'string', minLength: 1 },
        email: { type: 'string', minLength: 8, maxLength: 64 },
        firstName: { type: 'string', minLength: 1, maxLength: 32 },
        lastName: { type: 'string', minLength: 1, maxLength: 32 },
        hash: { type: 'string' },
        salt: { type: 'string' },
        active: { type: 'boolean' },
        createdAt: { type: 'string', format: 'date-time' },
        updatedAt: { type: 'string', format: 'date-time' },
      },
    };
  }

  static generatePassHash(password) {
    const salt = randomBytes(16);
    const hash = pbkdf2Sync(password, salt, 27500, 64, 'sha256');
    return { hash: hash.toString('base64'), salt: salt.toString('base64') };
  }

  set password(password) {
    const { hash, salt } = User.generatePassHash(password);
    this.salt = salt;
    this.hash = hash;
    this.$password = password;
  }

  get password() {
    return this.$password;
  }

  verifyPassword(password, callback) {
    const salt = Buffer.from(this.salt, 'base64');
    pbkdf2(password, salt, 27500, 64, 'sha256', (err, derivedKey) => {
      if (err) return callback(new Error('Unauthenticated'));
      if (derivedKey.toString('base64') === this.hash) return callback(null, true);
      return callback(null, false);
    });
  }

  static async create(rawUser) {
    const user = await this.query().insert(rawUser).returning('*');
    return user;
  }

  static getUserById(id) {
    return this.query().where({ _id: id }).first();
  }

  static getUserByEmail(email) {
    // Use bound parameters — never interpolate user input into raw SQL
    return this.query().whereRaw('lower(email) = lower(?)', [email]).first();
  }

  $beforeInsert() {
    this.firstName = this.firstName.charAt(0).toUpperCase() + this.firstName.slice(1).toLowerCase();
    this.lastName = this.lastName.charAt(0).toUpperCase() + this.lastName.slice(1).toLowerCase();
    if (this.email) {
      this.email = this.email.toLowerCase();
    }
    this.createdAt = new Date().toISOString();
    this.updatedAt = new Date().toISOString();
  }

  $beforeUpdate() {
    this.updatedAt = new Date().toISOString();
    delete this.createdAt;
  }

  $formatJson(json) {
    const jsonTemp = super.$formatJson(json);
    const { hash, salt, ...rest } = jsonTemp;
    return { ...rest };
  }
}

module.exports = User.bindKnex(getConnection());
```

```javascript
// db/knexfile.js
const path = require('path');
const config = require('../config');

module.exports = {
  client: 'pg',
  connection: config.databaseUrl,
  migrations: {
    directory: path.join(__dirname, './migrations'),
  },
};
```

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

```javascript
// db.init.js (non-table models)
const Knex = require('knex');
const config = require('../config');

const connection = Knex({
  client: 'pg',
  useNullAsDefault: true,
  connection: config.databaseUrl,
});

const orgModel = () => connection('organizations');
const roleModel = () => connection('roles');

module.exports = {
  getConnection: () => connection,
  connect: async () => connection.schema.hasTable('users'),
  orgModel,
  roleModel,
};
```

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
};

module.exports = { commonValidationRules };
```

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
});

const loginSchema = Joi.object({
  email: email.required(),
  password: Joi.string().required(), // plain string validation, detailed check in handler
});

module.exports = { registerUserSchema, loginSchema };
```

```javascript
// validators/commonUtil.js (middleware)
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

```javascript
// routes/user.routes.js
const express = require('express');
const router = express.Router();
const { validateReq } = require('../validators/commonUtil');
const { registerUserSchema } = require('../validators/userValidator');
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

## Anti-patterns to avoid

1. **Not calling `super.$formatJson(json)` in override**: always call the parent method first before stripping fields.
2. **Hardcoding database connection strings**: load from `config` or environment variables.
3. **Using `abortEarly: true` in Joi validation**: set `abortEarly: false` to collect all errors for better UX.
4. **Not setting `allErrors: true` in AJV**: without this, only the first validation error is reported.
5. **Deleting fields in `$beforeUpdate()` without caution**: deleting `createdAt` is intentional to prevent overwriting immutable fields; don't delete fields that should be updatable.
6. **Not binding models to Knex instance**: models must be bound via `bindKnex(connection)` to execute queries.
7. **Using instance methods for queries on multiple rows**: static methods (`getUsersByIds()`) should use `this.query()`, not instance methods.
8. **Returning raw Objection ValidationError in HTTP responses**: catch and format these as `{ success: false, status: 400, errors: [...] }` in error middleware.
9. **Forgetting to run migrations in CI/CD**: `knex migrate:latest` must run before application startup in production.
10. **Not using `returning('*')` after insert/update**: without `.returning('*')`, Postgres doesn't return the inserted/updated row; explicitly request it to avoid extra queries.
11. **Mixing Objection models and raw Knex queries inconsistently**: prefer Objection models for CRUD; use raw Knex or non-table models only for complex queries where Objection's query builder is insufficient.
12. **Not validating at both model and request layers**: model `jsonSchema` enforces data integrity; Joi middleware enforces request contract. Both are necessary.
13. **Interpolating user input into `whereRaw`**: never build raw SQL with template-string interpolation of request values — it is SQL-injectable. Always pass bound parameters, e.g. `whereRaw('lower(email) = lower(?)', [email])`.

## References

- [repo-evidence.md](references/repo-evidence.md) — source file paths and genericized snippets
- [objection-model-and-knex.md](references/objection-model-and-knex.md) — BaseModel, jsonSchema, lifecycle hooks, bindKnex(), non-table models
- [migrations-and-validation.md](references/migrations-and-validation.md) — knexfile.js, migration patterns, Joi middleware, commonRules, error envelope
- [python-dao-and-database](../python-dao-and-database/SKILL.md) — Python analog: SQLAlchemy models, BaseDao, async session management
- [pydantic-schema-patterns](../pydantic-schema-patterns/SKILL.md) — Python analog: Pydantic validation, field validators, ConfigDict
