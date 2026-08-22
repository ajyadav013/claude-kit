---
name: express
description: Express.js backend stack patterns for routing, middleware, error handling, TypeScript setup, and testing. Use when building or refactoring a Node.js Express service.
---

# Express

This is the stack-facing skill for Node.js + Express projects. It keeps the catalog entry small and
points users to the broader, production-grounded guidance in `node-express-service`.

## Use this skill when

- Scaffolding a new Express backend service
- Setting up routing, middleware order, and error handling
- Adding TypeScript support, request validation, or HTTP tests
- Adopting the repository's package-manager scripts for lint, typecheck, test, and build

## Core guidance

- Keep routes thin and move business logic into services.
- Centralize middleware for request IDs, logging, auth, and header normalization.
- Use a final error handler that maps domain failures to structured HTTP responses.
- Make `package.json` scripts the source of truth for `dev`, `test`, `lint`, `typecheck`, and `build`.
- Prefer the more detailed `node-express-service` skill when you need full production patterns or
  code examples.

## Cross-reference

- `node-express-service` for the fuller app-factory, config, middleware, and observability patterns
