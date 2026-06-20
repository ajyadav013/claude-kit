# node-objection-knex

Production patterns for Objection.js + Knex data layer and Joi request validation in Express services.

## What this covers

- **Objection.js models**: BaseModel with AJV jsonSchema validation, lifecycle hooks (`$beforeInsert`, `$beforeUpdate`, `$afterDelete`), `$formatJson()` for sensitive field stripping, password hashing in model setters, static vs instance methods
- **Knex integration**: `bindKnex()` per connection, non-table models (query builder factories), knexfile.js configuration
- **Migrations**: `knex migrate:make`, `exports.up` / `exports.down`, common schema patterns (UUID primary keys, foreign keys, JSONB, timestamps)
- **Joi validation middleware**: `validateReq(schema, type)` higher-order middleware, `abortEarly: false` to collect all errors, standardized `{ success, status, message, errors[] }` envelope
- **Shared validation rules**: `commonRules.js` with reusable Joi rules (firstName, lastName, email, password, phoneNumber), custom `.messages()` for user-friendly errors
- **Express route integration**: applying `validateReq()` middleware to routes, handling validation errors, success/error response envelopes

## How it was derived

This skill is derived from real production Express services using Objection.js + Knex for Postgres data access and Joi for request validation. All examples are genericized to remove internal service names, database connection details, and proprietary business logic. Patterns are extracted from multiple microservices with consistent conventions.

## Usage

See [SKILL.md](SKILL.md) for detailed conventions, skeleton code, and anti-patterns.

## References

- [objection-model-and-knex.md](references/objection-model-and-knex.md) — Objection.js model patterns, Knex integration
- [migrations-and-validation.md](references/migrations-and-validation.md) — Knex migrations, Joi validation middleware
- [repo-evidence.md](references/repo-evidence.md) — genericized snippets from source repositories
