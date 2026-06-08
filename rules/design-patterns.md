# Design Patterns

Mandatory design patterns for backend and frontend code. Apply the appropriate pattern whenever the described situation arises.

**Async-first consideration:** When your project uses async I/O (async/await, promises, event loops), all patterns below should be implemented with async primitives. No blocking I/O should exist in the request path. See `.claude/rules/code-organization.md` for async architecture guidance.

---

## Backend Patterns

### 1. Repository Pattern
**When:** Any database access.
**Why:** Isolate data access logic from business rules. Makes services testable without DB.

```
<domain>/<resource>/
├── repository.{ext}   ← Repository (DB I/O only)
├── service.{ext}      ← Service (business rules)
├── handler.{ext}      ← Router/handler (HTTP interface)
└── schemas.{ext}      ← Typed request/response schemas
```

**Rules:**
- Repository functions accept a database connection/session as first param
- Repositories return domain objects or `None`/`null` — never raise HTTP-level exceptions
- Repositories never commit — they call `flush()` or equivalent at most
- One repository per domain aggregate (User, Organization, Tenant)

**Example (Python with async ORM):**
```python
# repository.py
async def get_by_email(db: AsyncSession, email: str) -> User | None:
    stmt = select(User).where(User.email == email.lower())
    result = await db.execute(stmt)
    return result.scalar_one_or_none()

async def create(db: AsyncSession, **fields: Any) -> User:
    user = User(**fields)
    db.add(user)
    await db.flush()
    return user
```

**Example (TypeScript/Node with Prisma):**
```typescript
// repository.ts
async function getByEmail(db: PrismaClient, email: string): Promise<User | null> {
  return db.user.findUnique({ where: { email: email.toLowerCase() } });
}

async function create(db: PrismaClient, fields: CreateUserData): Promise<User> {
  return db.user.create({ data: fields });
}
```

### 2. Service Layer Pattern
**When:** Any business logic that involves validation, orchestration, or side effects.
**Why:** Keeps handlers thin. Business rules live in one testable place.

**Rules:**
- Services call repositories for DB access
- Services raise HTTP-level exceptions (or return error types) for user-facing errors
- Services own the transaction commit — not repositories, not handlers
- Services accept typed schemas or primitives as input — never raw dictionaries/objects
- Services can call multiple repositories in a single operation

**Example (Python):**
```python
# service.py
async def create_user(
    db: AsyncSession,
    payload: UserCreate,
    *,
    actor: User,
) -> User:
    if await repository.get_by_email(db, payload.email):
        raise HTTPException(status_code=409, detail="email already registered")

    user = await repository.create(
        db,
        email=payload.email,
        password_hash=hash_password(payload.password),
        organization_id=actor.organization_id,
    )
    await db.commit()
    return user
```

**Example (TypeScript/Node):**
```typescript
// service.ts
async function createUser(
  db: PrismaClient,
  payload: UserCreate,
  actor: User
): Promise<User> {
  const existing = await repository.getByEmail(db, payload.email);
  if (existing) {
    throw new ConflictError("email already registered");
  }

  const user = await repository.create(db, {
    email: payload.email,
    passwordHash: hashPassword(payload.password),
    organizationId: actor.organizationId,
  });
  
  return user;
}
```

### 3. Dependency Injection
**When:** Any cross-cutting concern — auth, DB session, permissions, rate limiting.
**Why:** Composable, testable, declarative dependencies.

**Rules:**
- Reusable deps in a common dependencies module or per-domain deps file
- Named clearly: `getCurrentUser`, `getDbSession`, `requireRole("admin")`
- Order in handler signature: request artifacts → auth → authorization → DB/cache clients
- Never instantiate services or sessions manually inside handlers — always via dependency injection

**Example (FastAPI with Depends):**
```python
@router.post("", response_model=UserRead, status_code=201)
async def create_user(
    payload: UserCreate,
    current_user: User = Depends(get_current_user),
    _: None = Depends(require_role("org_admin")),
    db: AsyncSession = Depends(get_db_session),
) -> UserRead:
    user = await service.create_user(db, payload, actor=current_user)
    return UserRead.model_validate(user)
```

**Example (NestJS with decorators):**
```typescript
@Post()
@UseGuards(AuthGuard, RoleGuard)
@Roles('org_admin')
async createUser(
  @Body() payload: UserCreateDto,
  @CurrentUser() currentUser: User,
  @InjectDb() db: PrismaClient,
): Promise<UserRead> {
  const user = await this.service.createUser(db, payload, currentUser);
  return new UserRead(user);
}
```

### 4. Unit of Work
**When:** Multiple DB operations that must succeed or fail together.
**Why:** Transactional consistency without explicit transaction management.

**Rules:**
- The DB session dependency wraps operations in a transaction — rollback on exception
- Service layer calls `commit()` at the end of a successful operation
- Use `flush()` or equivalent when you need a generated ID before commit
- Never call `commit()` in repository functions
- For multi-step workflows, keep all operations in the same session/transaction

### 5. Mixin Pattern (for ORM models)
**When:** Cross-cutting model fields (timestamps, soft-delete).
**Why:** DRY — mixins applied once, inherited everywhere.

**Example (Python with SQLAlchemy):**
```python
class User(Base, CreatedAtMixin, UpdatedAtMixin, SoftDeleteMixin):
    ...
```

**Example (TypeScript with TypeORM):**
```typescript
@Entity()
class User extends CreatedAtEntity {
  // ...
}
```

**Rules:**
- New cross-cutting fields → add a mixin, don't copy-paste columns
- Mixins provide column definitions via framework-specific mechanisms
- Mixins never define relationships — keep them pure column providers

### 6. Factory Pattern (App Factory)
**When:** Application setup.
**Why:** Testability (fresh app per test), configurable middleware/routers.

**Rules:**
- Never import a module-level app object — always call a factory function
- Tests use the factory to create isolated app instances

**Example (Python):**
```python
def get_app() -> Application:
    app = Application()
    # configure middleware, routes, etc.
    return app
```

**Example (Node/Express):**
```typescript
function createApp(): Express {
  const app = express();
  // configure middleware, routes, etc.
  return app;
}
```

### 7. Strategy Pattern
**When:** Multiple algorithms for the same operation (e.g., hashing, notification channels, export formats).
**Why:** Swap behavior without modifying callers.

**Example (Python with Protocol):**
```python
from typing import Protocol

class PasswordHasher(Protocol):
    def hash(self, password: str) -> str: ...
    def verify(self, password: str, hash: str) -> bool: ...

class StrongHasher:
    def hash(self, password: str) -> str: ...
    def verify(self, password: str, hash: str) -> bool: ...
```

**Example (TypeScript with interface):**
```typescript
interface PasswordHasher {
  hash(password: string): string;
  verify(password: string, hash: string): boolean;
}

class StrongHasher implements PasswordHasher {
  hash(password: string): string { /* ... */ }
  verify(password: string, hash: string): boolean { /* ... */ }
}
```

**Rules:**
- Use interface/protocol for strategy contracts
- Inject via dependency — not hardcoded `if/else` chains
- Use when there are 2+ interchangeable implementations

### 8. Enum Pattern
**When:** Constrained string fields with a known set of values (roles, statuses, types).
**Why:** Type safety, autocomplete, no magic strings.

**Example (Python):**
```python
class UserRole(str, Enum):
    SYS_ADMIN = "sys_admin"
    ORG_ADMIN = "org_admin"
    MEMBER = "member"
```

**Example (TypeScript):**
```typescript
enum UserRole {
  SYS_ADMIN = "sys_admin",
  ORG_ADMIN = "org_admin",
  MEMBER = "member",
}
```

**Rules:**
- Always use string-based enums for JSON-serializable values
- Use enums in typed schemas and data models
- Never compare with raw strings: `if role == "admin"` → `if role == UserRole.SYS_ADMIN`

---

## Frontend Patterns

### 9. Container / Presentational Split
**When:** A component both fetches data and renders UI.
**Why:** Separation of concerns — data logic vs display logic.

```
src/pages/UsersPage.{ext}         ← Container (data fetching, state)
src/components/UserList.{ext}     ← Presentational (props → UI)
src/components/UserCard.{ext}     ← Presentational (props → UI)
```

**Rules:**
- Pages/containers own data fetching and state
- Components are presentational — they receive props and render
- Presentational components are pure functions where possible

### 10. Custom Hook Pattern (React/Vue composables)
**When:** Shared stateful logic across components.
**Why:** Reusable, testable state logic extracted from components.

**Example (React):**
```typescript
// hooks/useAuth.ts
export function useAuth() {
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  return { user, isAuthenticated: !!user, logout };
}
```

**Example (Vue):**
```typescript
// composables/useAuth.ts
export function useAuth() {
  const store = useAuthStore();
  return {
    user: computed(() => store.user),
    isAuthenticated: computed(() => !!store.user),
    logout: () => store.logout(),
  };
}
```

**Rules:**
- One concern per hook/composable
- Return stable references (memoize functions where needed)
- Name as `use<Purpose>` — `useAuth`, `usePagination`, `useDebounce`

### 11. Store Pattern
**When:** Shared state across components that isn't server-state.
**Why:** Simple, minimal boilerplate, good type support.

**Example (with client state library):**
```typescript
interface AuthState {
  user: User | null;
  setUser: (user: User | null) => void;
  logout: () => void;
}

export const useAuthStore = createStore<AuthState>({
  user: null,
  setUser: (user) => ({ user }),
  logout: () => ({ user: null }),
});
```

**Rules:**
- Always use selectors: `useStore((s) => s.value)` — never `useStore()` (full state)
- Never create new objects/arrays inside selectors
- Actions are stable references — exclude from dependency arrays
- One store per concern — don't dump everything in one god-store

### 12. API Client Pattern
**When:** Any HTTP call from the frontend.
**Why:** Centralized error handling, auth, base URL.

**Example:**
```typescript
// lib/api.ts
import axios from "axios";

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || "http://localhost:8000",
  withCredentials: true,  // session cookies
});

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      // redirect to login
    }
    return Promise.reject(error);
  },
);

export default api;
```

**Rules:**
- One shared HTTP client instance — don't create clients per request
- Configure global interceptors for auth expiry
- Per-domain API modules for organized endpoints: `lib/users.ts`, `lib/orgs.ts`

### 13. Error Boundary Pattern
**When:** Any page or major section that could throw during render.
**Why:** Graceful degradation — don't crash the entire app.

**Rules:**
- Wrap each route-level page in an error boundary
- Show a user-friendly error message — not a blank screen
- Log the error for observability

---

## Anti-Patterns (DO NOT)

### Backend
- ❌ **God service** — one service that does everything. Split by domain.
- ❌ **Anemic domain** — models are just data bags with all logic in utilities. Put behavior near data.
- ❌ **Business logic in handlers** — handlers are thin wrappers. Logic goes in services.
- ❌ **Repository that raises HTTP exceptions** — repositories return data or None/null.
- ❌ **Raw dict/object passing** — use typed schemas or data classes for structured data.
- ❌ **Hardcoded magic strings** — use Enums or constants.
- ❌ **Circular imports** — respect the dependency direction: handler → service → repository → models.

### Frontend
- ❌ **Prop drilling 3+ levels deep** — use a state store or context instead.
- ❌ **Ad-hoc data fetching in effects** — use a data-fetching library or at minimum a dedicated hook.
- ❌ **God component** — components over 200 lines should be split.
- ❌ **Inline styles** — use a styling system (CSS modules, utility classes, styled components).
- ❌ **Direct localStorage for auth** — use secure cookie-based sessions where possible.

---

## When to Apply Which Pattern

| Situation | Pattern |
|-----------|---------|
| New API endpoint | Repository + Service + DI + Typed schemas |
| New DB model | Mixin (if applicable) + Factory (app) + Enum (for constrained fields) |
| Shared model fields | Mixin (ORM-specific) |
| Auth/permissions | DI + Strategy (if multiple auth methods) |
| Multi-step DB operation | Unit of Work |
| New frontend page | Container/Presentational + Store + API Client |
| Shared frontend state | Store + Custom Hook |
| Constrained string values | Enum (backend) or union type (frontend) |
| Multiple implementations | Strategy (interface/protocol) |
| Cross-cutting render concern | Error Boundary |
