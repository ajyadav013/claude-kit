# GraphQL Patterns

Tactical GraphQL patterns for Strawberry (backend) and Apollo Client (frontend) from production services.

## What this skill covers

- **Backend (Strawberry)**: Schema-per-endpoint pattern; async DB access in resolvers; mounting GraphQL routers alongside REST in FastAPI
- **Frontend (Apollo Client)**: Link composition (error → auth → http); JWT + multi-tenancy headers; InMemoryCache merge policies; `cache-and-network` fetch policy
- **Query/Mutation authoring**: Hand-typed `gql` documents; no codegen; flat queries; manual TypeScript types
- **Use cases**: Filter/dropdown APIs (filter API services), dashboard queries (dashboard applications), file uploads (apollo-upload-client)

## Provenance

Derived from real-world production Python/FastAPI and React services.

## How to apply

1. **For new GraphQL filters on the backend**: Create a `@strawberry.type` query class with `@strawberry.field` methods; define a `strawberry.Schema`; mount with `GraphQLRouter` under a shared prefix.
2. **For new Apollo Client setup**: Compose `from([errorLink, authLink, httpLink])`; configure InMemoryCache with merge policies; set `cache-and-network` fetch policy.
3. **For writing queries**: Use `gql` template tag in `src/graphql/queries/`; export manually-typed TypeScript interfaces; import and use with `useQuery`/`useMutation` in components.
4. **For multi-tenancy**: Include `x-org-id` header in authLink; ensure backend resolvers respect tenant context.

## Pattern origins

- **Codebase-derived**: Strawberry schema-per-endpoint pattern, async connection handler pattern, Apollo link chain, InMemoryCache merge policies, hand-typed gql documents, useQuery/useMutation usage.
- **Internet-confirmed**: Strawberry `@strawberry.type` / `@strawberry.field` decorators (Strawberry GraphQL docs), `strawberry.fastapi.GraphQLRouter` mounting (Strawberry FastAPI integration docs), Apollo Client link composition order (Apollo Client docs), `setContext` for auth headers (Apollo Client auth docs), `apollo-upload-client` for multipart file uploads (apollo-upload-client README).

## Honesty caveats

- **Limited footprint**: GraphQL is used in ~2 applications (filter API services, dashboard applications). This is **not** the organizational default — most services use pure REST.
- **No codegen**: The pattern is hand-typed queries/mutations. No graphql-codegen or similar tools are in use.
- **Coexists with REST**: GraphQL endpoints are tactical supplements, not a full API layer. Most routes remain FastAPI REST.
