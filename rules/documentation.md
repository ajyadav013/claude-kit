# Documentation Standards

Mandatory documentation standards for all code in this repository. Every change must maintain or improve documentation.

## 1. README.md — Project Documentation

The root `README.md` must be kept current after every meaningful change. It must contain:

### Required Sections
```markdown
# [Project Name]

## Overview
One-paragraph description of what the project is and what problem it solves.

## Architecture
- Backend: [backend stack/framework]
- Frontend: [frontend stack/framework]
- Infrastructure: [deployment/containerization approach]

## Quick Start
### Prerequisites
- [Runtime/language versions]
- [Package managers/tools]
- [Infrastructure dependencies]

### Run the full stack
[command to start all services]

### Run backend only (development)
[commands to set up and run backend in dev mode]

### Run frontend only (development)
[commands to set up and run frontend in dev mode]

### Verify health
[commands to verify services are running]

## API Endpoints
| Method | URL | Description | Auth |
|--------|-----|-------------|------|
(table of all endpoints, kept current)

## Environment Variables
| Variable | Default | Description |
|----------|---------|-------------|
(table of all env vars from compose/deployment config + .env.example)

## Project Structure
(tree showing project layout)

## Testing
### Backend
[command to run backend tests]

### Frontend
[command to run frontend tests]

## Contributing
Link to CLAUDE.md for the engineering delivery workflow.
```

### Update Rule
After adding or modifying any endpoint, env var, service, or major feature, the developer must update README.md to reflect the change. The code reviewer must verify README.md is current.

---

## 2. Module Docstrings — Every File

**Every source file** in the project must have a module-level docstring explaining what the file is for.

**Backend example (Python/Java/Go/etc.):**
```python
"""Authentication handlers for the identity service.

Handles login, registration, logout, password reset, and session
management endpoints. All handlers delegate to the service layer for
business logic.
"""
```

**Frontend example (TypeScript/JavaScript):**
```typescript
/**
 * Authentication state store.
 *
 * Manages user session state, login/logout flows, and auth status.
 * Sessions are cookie-based — no tokens stored client-side.
 */
```

### What the Module Docstring Must Contain
1. **What** the file/module does (one sentence)
2. **Why** it exists / what role it plays in the architecture (one sentence)
3. **Key exports** if not obvious from the filename (optional, for large modules)

---

## 3. Function & Method Docstrings — Every Public Function

**Every** public function, method, and class must have a docstring. Use the documentation style appropriate for your language ecosystem.

### Backend Example (Python Google-style)

```python
async def create_user(
    db: DatabaseSession,
    payload: UserCreate,
    *,
    actor: User,
) -> User:
    """Create a new user with a hashed password.

    Validates that the email is not already registered, hashes the
    password with a strong algorithm, and persists the user to the database.

    Args:
        db: Database session or connection.
        payload: Validated user creation data (email, password, name).
        actor: The authenticated user performing the action (for authorization scoping).

    Returns:
        The newly created User entity with a generated ID.

    Raises:
        ConflictError: If the email is already registered.
        PermissionError: If the actor lacks permission to create users.
    """
```

### Frontend Example (TypeScript JSDoc)

```typescript
/**
 * Create a new user via the API.
 *
 * @param payload - User creation data (email, password, name).
 * @returns The created user object from the API response.
 * @throws Error with status 409 if the email is already registered.
 */
export async function createUser(payload: UserCreate): Promise<UserRead> {
  const { data } = await apiClient.post<ApiResponse<UserRead>>("/v1/users", payload);
  return data.data;
}
```

### What the Function Docstring Must Contain
1. **Summary line** — what the function does (imperative mood: "Create", "Validate", "Return")
2. **Extended description** — how it works, side effects, important behavior (optional for trivial functions)
3. **Args / @param** — every parameter with type and purpose
4. **Returns / @returns** — what is returned and its type
5. **Raises / @throws** — exceptions/errors the caller should handle

### Skip Docstrings Only For
- Private helper functions (prefixed with `_` or similar convention) that are < 5 lines and obviously named
- Test functions (test name is the documentation)
- Constructor/initialization methods that only perform simple field assignment

---

## 4. Type Annotations — Every Function Signature

**Every** function must have full type annotations on all parameters and the return type (where the language supports static typing).

### Statically-Typed Languages (Python, TypeScript, Java, Go, etc.)

**Python example:**
```python
# ✅ Correct — fully typed
async def get_by_email(db: DatabaseSession, email: str) -> User | None:
    ...

async def create_user(db: DatabaseSession, payload: UserCreate, *, actor: User) -> User:
    ...

async def list_users(db: DatabaseSession, org_id: str, page: int = 1, page_size: int = 20) -> list[User]:
    ...

def hash_password(password: str) -> str:
    ...

# ❌ Forbidden — missing return type
async def get_by_email(db: DatabaseSession, email: str):
    ...

# ❌ Forbidden — missing param type
async def create_user(db, payload):
    ...

# ❌ Forbidden — untyped dict/map
async def get_session(session_id: str) -> dict:
    ...
# ✅ Correct — typed data structure
async def get_session(session_id: str) -> SessionData:
    ...
```

**TypeScript example:**
```typescript
// ✅ Correct
export async function fetchUsers(orgId: string, page: number): Promise<PaginatedResponse<UserRead>> {
  ...
}

// ❌ Forbidden — no return type
export async function fetchUsers(orgId: string, page: number) {
  ...
}

// ❌ Forbidden — `any`
export async function fetchUsers(orgId: any): Promise<any> {
  ...
}
```

### Rules
- No bare generic containers as return types (e.g., `dict`, `list`, `Map`, `Array`) — define structured types
- Always parameterize generic types: `list[User]`, `Array<User>`, etc.
- No `Any` / `any` / `Object` unless genuinely needed and documented with a comment explaining why
- Explicit return types required — `-> None` / `: void` must be explicit if the function returns nothing

---

## 5. Class Docstrings

Every class must have a docstring explaining its purpose and usage.

**Example (Python):**
```python
class ConnectionManager:
    """Singleton that manages database connections and cache clients.

    Creates connection pool on first instantiation. Provides
    factory methods for session creation. Thread-safe via singleton pattern.

    Usage:
        manager = ConnectionManager()
        session = manager.get_session()
        cache = manager.get_cache_client()
    """
```

**Example (validation/schema class):**
```python
class UserCreate(BaseModel):
    """Input schema for user registration.

    Validates email format, password strength, and name constraints.
    Never returned to the client (contains password field).
    """
```

---

## 6. Inline Comments — When and How

### Do Comment
- **Non-obvious business rules**: `# Tenant admins can only see users in their own tenant`
- **Workarounds with context**: `# Database driver doesn't support feature X in connection pooling`
- **Performance decisions**: `# Eager-load to prevent N+1 on the list page`
- **Security decisions**: `# Rate limit to 5 req/min to prevent credential stuffing`
- **TODO with ticket**: `# TODO(PROJ-123): Replace with proper RBAC once permissions service is built`

### Do NOT Comment
- What the code does when it's obvious from the code itself
- Narrating changes: `# Added this field for the new feature`
- Commented-out code — delete it; git has history

---

## 7. API Endpoint Documentation

Every HTTP endpoint must be documented with appropriate metadata for the framework being used.

**Example (OpenAPI/Swagger-compatible frameworks):**
```python
@router.post(
    "",
    response_model=UserRead,
    status_code=201,
    summary="Create a new user",
    description="Creates a user in the caller's organization with a hashed password.",
    responses={
        409: {"description": "Email already registered"},
        403: {"description": "Insufficient permissions"},
    },
)
async def create_user(...) -> UserRead:
    """Create a new user in the caller's organization."""
```

### Required Endpoint Metadata (adapt to framework conventions)
- Short description/summary — what the endpoint does
- Response schema/type — structured return type
- Status code(s) — explicit success status
- Error responses — document non-success status codes the endpoint can return
- Extended description — if summary isn't sufficient (optional)

---

## 8. Changelog Discipline

When making significant changes, add a brief note to the spec file or a changelog:
- New endpoint → update README.md API table + spec traceability
- New env var → update README.md env var table + deployment config + .env.example
- Schema/migration change → migration documentation + spec update
- Breaking change → note in PR description + README

---

## Enforcement

### Code Reviewer Must Check
- [ ] Every new/modified file has a module docstring
- [ ] Every new/modified public function has a docstring with parameters/returns/errors documented
- [ ] Every function has full type annotations (params + return) where the language supports it
- [ ] No untyped generic containers (bare `dict`, `list`, `Map`, `Array`, `any`, `Any`) without justification
- [ ] README.md is updated if endpoints, env vars, or architecture changed
- [ ] API endpoint metadata is complete (summary, response type, status codes, error responses)

### Pre-Commit Mental Checklist
Before committing any change, ask:
1. Would a new engineer understand what this file does from its module docstring?
2. Would a new engineer understand what each function does from its docstring?
3. Can the project's type checker infer every type, or are there gaps?
4. Is the README still accurate?
