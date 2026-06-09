# MongoDB patterns

Database conventions. Installed into `.claude/rules/` only when **MongoDB** is selected. Read
`.claude/rules/design-patterns.md` and your backend overlay rule first; this file makes the data
layer concrete for MongoDB.

## Access

- Use one shared async client (e.g. Motor) with a connection pool — never a client per request.
- Validate **all** input with your schema layer (e.g. Pydantic v2) *before* it reaches the driver.
  A document store will happily persist a misshapen document; the application is the schema gatekeeper.
- Never interpolate user input into query operators. Treat keys/values as data; guard against
  operator-injection (e.g. a user value of `{"$gt": ""}` reaching a filter).

## Schema & migrations

- MongoDB is schema-flexible, but your **application has a schema** (your models). Keep a single
  source of truth for document shape and version it.
- Store a `schema_version` field on documents that may evolve. Write **idempotent, reversible
  migration scripts** for backfills/transformations; run them as an explicit, reviewed step — not
  silently at boot.
- Prefer additive changes (new optional fields) over destructive ones; backfill before requiring a
  new field.

## Modeling

- **Model around access patterns, not normalization.** Embed data read together; reference data that
  is large, shared, or independently updated. Watch the 16 MB document limit and unbounded arrays.
- Create **indexes** for every query filter/sort on a hot path; add unique indexes where the domain
  requires uniqueness (enforce it in the database, not only in code).
- Use the right BSON types: `Date` for instants (store UTC), `Decimal128` for money (never float),
  `ObjectId` (or a deliberate string key) for ids.

## Operations

- Keep the connection string in env (`MONGODB_URI`); never commit it. Document required vars in
  `.env.example`.
- Use transactions (multi-document) only when you need atomicity across documents; design to avoid
  needing them where possible. Call out index builds and large backfills in the release/runbook notes.
