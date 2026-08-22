# Objection Model and Knex Patterns

Production patterns for Objection.js models, Knex query builder, and connection management.

## BaseModel with AJV Validator

All models inherit from a shared `BaseModel` that configures AJV validation with format support:

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

**Key options:**
- `allErrors: true` — collect all validation errors, not just the first
- `validateSchema: false` — skip meta-schema validation for performance
- `ownProperties: true` — validate only the object's own properties
- `onCreateAjv` — hook to add AJV plugins like `ajv-formats` for `date-time`, `email`, etc.

## Model with jsonSchema and Lifecycle Hooks

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
        meta: { type: 'object' },
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
    delete this.createdAt; // prevent overwriting immutable field
  }

  $formatJson(json) {
    const jsonTemp = super.$formatJson(json);
    const { hash, salt, ...rest } = jsonTemp;
    return { ...rest };
  }
}

module.exports = User.bindKnex(getConnection());
```

**Lifecycle hooks:**
- `$beforeInsert()` — normalize data, set timestamps, run custom validation before insert
- `$beforeUpdate()` — update `updatedAt`, delete immutable fields, revalidate
- `$afterDelete()` — cleanup (e.g., delete related sessions, cascade soft-deletes)
- `$formatJson(json)` — strip sensitive fields (`hash`, `salt`) from serialized output

**Password hashing:**
- Use getter/setter to intercept password assignment and hash automatically
- Store `hash` and `salt` separately; never store plaintext passwords
- `verifyPassword()` accepts callback for async comparison (pbkdf2 is async-friendly)

## Static vs Instance Methods

```javascript
class User extends BaseModel {
  // Static methods: operate on the model class, use this.query()
  static async create(rawUser) {
    return this.query().insert(rawUser).returning('*');
  }

  static getUserById(id) {
    return this.query().where({ _id: id }).first();
  }

  static getUsersByIds(ids) {
    return this.query().findByIds(ids);
  }

  static getUserByEmail(email) {
    // Use bound parameters — never interpolate user input into raw SQL
    return this.query().whereRaw('lower(email) = lower(?)', [email]).first();
  }

  // Instance methods: operate on a single instance, use this.$query()
  async updateProfile(updates) {
    return this.$query().patchAndFetchById(this._id, updates);
  }

  async deactivate() {
    return this.$query().patch({ active: false });
  }
}
```

**Conventions:**
- Static methods for queries that may return 0, 1, or many rows
- Instance methods for operations on a single loaded instance
- Use `patchAndFetchById()` to update and return the updated row in one call
- Use `updateAndFetch()` to replace the entire row and return it

## bindKnex() Per Connection

Models are bound to a Knex instance at export time:

```javascript
// db.init.js
const Knex = require('knex');
const config = require('../config');

const connection = Knex({
  client: 'pg',
  useNullAsDefault: true,
  connection: config.databaseUrl,
});

module.exports = {
  getConnection: () => connection,
  connect: async () => connection.schema.hasTable('users'),
};
```

```javascript
// models/user.model.js
const { getConnection } = require('../db.init');

module.exports = User.bindKnex(getConnection());
```

**Why bindKnex()?**
- Allows using the same model class with different databases (multi-tenant, read replicas)
- Models are immutable after binding; create separate bound copies for different connections
- The bound model is what you export and import in routes/controllers

## Non-Table Models (Query Builder Factories)

For tables without full Objection models, export query builder factory functions:

```javascript
// db.init.js
const connection = Knex({ client: 'pg', connection: config.databaseUrl });

const orgModel = () => connection('organizations');
const roleModel = () => connection('roles');
const accountModel = () => connection('accounts');

module.exports = {
  getConnection: () => connection,
  orgModel,
  roleModel,
  accountModel,
};
```

**Usage:**

```javascript
const { orgModel } = require('../db.init');

const orgs = await orgModel().where({ active: true }).select('*');
const org = await orgModel().where({ _id: orgId }).first();
```

**When to use:**
- For simple lookup tables where full model lifecycle (validation, hooks) is overkill
- For tables that already have an Objection model elsewhere but you need ad-hoc queries
- For aggregations, joins, or complex queries where Objection's query builder is cumbersome

## Custom Validation in Models

Define a standalone validation function and call it from lifecycle hooks:

```javascript
function validate(model) {
  if (model.email && !isValidEmail(model.email)) {
    throw new objection.ValidationError({
      message: `${model.email} is not a valid email`,
      type: 'EmailValidationError',
    });
  }

  if (model.password && !isValidPassword(model.password)) {
    throw new objection.ValidationError({
      message: `${model.password} is not a valid password`,
      type: 'PasswordValidationError',
    });
  }
}

class User extends BaseModel {
  $beforeInsert() {
    // ... normalize fields ...
    validate(this);
  }

  $beforeUpdate() {
    this.updatedAt = new Date().toISOString();
    validate(this);
  }
}
```

**Best practice:**
- Use `objection.ValidationError` for model-level validation errors
- Distinguish validation errors from other errors using `type` field
- Catch `objection.ValidationError` in Express error middleware and format as 400 response

## Updating Related Data After Model Changes

```javascript
class User extends BaseModel {
  static async updateUserDetails(_id, updateOpts) {
    const user = await this.getUserById(_id);
    if (!user) return;

    // Validate uniqueness constraints before update
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
    // Trigger side effects (e.g., Kafka event, session update)
    await notifyUserUpdated(updatedUser);
    return updatedUser;
  }
}
```

**Pattern:**
- Fetch the instance first to validate constraints
- Use `updateAndFetch()` or `patchAndFetchById()` to apply updates and get the updated row
- Trigger side effects (events, cache invalidation) after successful update
