# Repository Evidence

Genericized snippets from production services demonstrating Objection.js + Knex patterns.

## File Paths (Genericized)

```
app/server/models/base.model.js
app/server/models/user.model.js
app/server/postgres.init.js
db/knexfile.js
db/migrations/YYYYMMDD_create_table_name.js
app/server/validators/commonUtil.js
app/server/validators/commonRules.js
app/server/validators/userValidator.js
app/server/routes/v1.0/user.routes.js
```

## BaseModel Pattern

**File: `app/server/models/base.model.js`**

```javascript
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

## User Model with Lifecycle Hooks

**File: `app/server/models/user.model.js`**

```javascript
const { pbkdf2Sync, pbkdf2, randomBytes } = require('crypto');
const objection = require('objection');
const BaseModel = require('./base.model');
const { getConnection } = require('../postgres.init');

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
    return this.query().insert(rawUser).returning('*');
  }

  static getUserById(id) {
    return this.query().where({ _id: id }).first();
  }

  static getUserByEmail(email) {
    // Use bound parameters — never interpolate user input into raw SQL
    return this.query().whereRaw('lower(email) = lower(?)', [email]).first();
  }

  static async updateUserDetails(_id, updateOpts) {
    const user = await this.getUserById(_id);
    if (!user) return;

    // Check for duplicates before update
    if (updateOpts.phoneNumber) {
      const duplicate = await this.query()
        .where({ phoneNumber: updateOpts.phoneNumber })
        .whereNot({ _id })
        .first();
      if (duplicate) {
        throw new objection.ValidationError({
          message: 'Phone number already registered',
          type: 'PhoneNumberDuplicateValidationError',
        });
      }
    }

    const updatedUser = await user.$query().updateAndFetch(updateOpts);
    return updatedUser;
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

## Knex Connection and Non-Table Models

**File: `app/server/postgres.init.js`**

```javascript
const Knex = require('knex');
const config = require('../../config');

const connection = Knex({
  client: 'pg',
  useNullAsDefault: true,
  connection: config.databaseUrl,
});

// Non-table models (query builder factories)
const orgModel = () => connection('organizations');
const roleModel = () => connection('roles');
const accountModel = () => connection('accounts');

module.exports = {
  getConnection: () => connection,
  connect: async () => connection.schema.hasTable('users'),
  orgModel,
  roleModel,
  accountModel,
};
```

## knexfile.js Configuration

**File: `db/knexfile.js`**

```javascript
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

## Migration Example

**File: `db/migrations/20240828_create_audit_logs_table.js`**

```javascript
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

**File: `app/server/validators/commonUtil.js`**

```javascript
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

      req.body = value;
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

## Common Validation Rules

**File: `app/server/validators/commonRules.js`**

```javascript
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

## Composed Validation Schema

**File: `app/server/validators/userValidator.js`**

```javascript
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
  password: Joi.string().required(),
});

module.exports = { registerUserSchema, loginSchema };
```

## Express Route with Validation

**File: `app/server/routes/v1.0/user.routes.js`**

```javascript
const express = require('express');
const router = express.Router();
const { validateReq } = require('../../validators/commonUtil');
const { registerUserSchema } = require('../../validators/userValidator');
const userModel = require('../../models/user.model');

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

## Notes

- All internal service/repo names, database connection details, and internal paths have been genericized
- Patterns are extracted from multiple production microservices with consistent Objection.js + Knex + Joi conventions
- Code snippets are safe to publish and reuse in any Express + Postgres project
