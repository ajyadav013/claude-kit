# Settings and Validation Patterns

Deep dive into the BaseSettings singleton pattern, validators, field constraints, enums, and aliasing as observed in production Python/FastAPI services.

---

## BaseSettings singleton pattern

All services follow a singleton pattern for application settings, with two common approaches:

### Approach 1: config_parser pattern

1. Define `Settings(BaseSettings)` in `config/docker_config.py`
2. Fields pull values from `config.config_parser.docker_args`
3. Create module-level singleton: `loaded_config = Settings()`
4. Import `loaded_config` throughout the service

### Approach 2: env_file pattern (cleaner v2 approach)

1. Define `Settings(BaseSettings)` in `config/settings.py`
2. Use `model_config = SettingsConfigDict(env_file=".env", extra="ignore")`
3. Fields load directly from `.env` file (no config_parser intermediary)
4. Create module-level singleton: `settings = Settings()`
5. Import `settings` throughout the service

### Example (v2 service with config_parser)

**config/docker_config.py:**
```python
from pydantic_settings import BaseSettings
from config.config_parser import docker_args

args = docker_args

class Settings(BaseSettings):
    # Environment
    ENV: str = args.ENV
    DEBUG: bool = args.DEBUG
    
    # Database
    db_url: str = args.POSTGRES_READ_WRITE
    DB_ECHO: bool = args.DEBUG
    
    # Redis
    REDIS_READ_WRITE: str = args.REDIS_READ_WRITE
    
    # Kafka
    KAFKA_BROKER_LIST: str = args.KAFKA_BROKER_LIST
    WORKER_MODE: str = args.WORKER_MODE or "default_consumer"
    
    # Temporal
    TEMPORAL_HOST: str = args.TEMPORAL_HOST
    TEMPORAL_NAMESPACE: str = args.TEMPORAL_NAMESPACE
    
    # Service clients (may be None initially)
    http: AsyncHTTPClient | None = None

loaded_config = Settings()
```

**Usage elsewhere:**
```python
from config.docker_config import loaded_config

@router.get("/health")
async def health():
    return {"env": loaded_config.ENV, "debug": loaded_config.DEBUG}
```

### Example (v2 service with SettingsConfigDict - cleanest approach)

**config/settings.py:**
```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    
    # Environment
    ENV: str = "development"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    
    # Database
    DATABASE_URL: str
    DB_POOL_SIZE: int = 10
    
    # Redis
    REDIS_URL: str | None = None
    
    # API Keys
    API_KEY: str

settings = Settings()
```

**Usage elsewhere:**
```python
from config.docker_config import loaded_config

@router.get("/health")
async def health():
    return {"env": loaded_config.ENV, "debug": loaded_config.DEBUG}
```

**Usage elsewhere:**
```python
from config.settings import settings

@router.get("/health")
async def health():
    return {"env": settings.ENV, "debug": settings.DEBUG}
```

**Advantages of SettingsConfigDict approach:**
- No need for separate `config_parser` module
- Direct `.env` file support (respects env vars > .env hierarchy)
- Cleaner v2 syntax with `model_config` at class level
- `extra="ignore"` prevents errors from undefined env vars
- Better type hints with modern Python syntax (`str | None`)

### Example (v2 service with env fallbacks)

**config/docker_config.py:**
```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    class Config:
        env_file = "../../.env"
        env_file_encoding = "utf-8"

    ENV: str = args.ENV
    POSTGRES_READ_WRITE: str = os.environ.get(
        "POSTGRES_READ_WRITE",
        "postgresql://postgres:<REDACTED>@localhost:5432/app_db",
    )
    REDIS_URL: str = os.environ.get("REDIS_READ_WRITE", "")
    # ... more fields with os.environ.get fallbacks for local dev

loaded_config = Settings()
```

### Example (v1 service)

**config/docker_config.py:**
```python
from pydantic import BaseSettings
from config.config_parser import docker_args

args = docker_args

class Settings(BaseSettings):
    host: str = args.host
    ENV: str = args.env
    debug: bool = args.debug
    db_url = args.postgres_read_write
    redis_read_write_url = args.redis_read_write
    # ... many fields

loaded_config = Settings()
```

**Key points:**
- Use a singleton pattern: `loaded_config = Settings()` or `settings = Settings()`
- Never instantiate `Settings()` more than once (defeats singleton purpose, causes config drift)
- Some services mutate the singleton after creation: `loaded_config.http = AsyncHTTPClient()`
- Modern v2 services should prefer `SettingsConfigDict(env_file=".env")` over config_parser intermediary

---

## LogLevel enum (often unused)

Most services define a `LogLevel` enum but never reference it:

```python
import enum

class LogLevel(enum.Enum):
    NOTSET = "NOTSET"
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    FATAL = "FATAL"
```

**Pattern:** Many services define it.

**Usage:** Some set `log_level: str = LogLevel.INFO.value` in Settings, but most just ignore it.

**Recommendation:** Flag as dead code if `LogLevel` is defined but never imported/used elsewhere.

---

## Field validators

### v2 validators

```python
from pydantic import field_validator

class RaiseQueryRequest(BaseModel):
    priority: str
    description: str

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v):
        allowed = {"P1", "P2", "P3"}
        if v not in allowed:
            raise ValueError(f"Priority must be one of {allowed}")
        return v

    @field_validator("description")
    @classmethod
    def description_not_empty(cls, v):
        if not v or not v.strip():
            raise ValueError("Description must not be empty")
        return v
```

**Wildcard validator:**
```python
class CreateAudit(AuditBase):
    @field_validator("*")
    def convert_to_upper(cls, v, field):
        if isinstance(v, AuditInternalStatus) or isinstance(v, AuditVendorStatus):
            return v.value
        return v
```

### v1 validators

```python
from pydantic import validator

class ContactDetails(BaseModel):
    contact_email: Optional[EmailStr]

    @validator("contact_email", pre=True)
    def validate_empty_string(cls, v):
        if v == "":
            return None
        return v
```

**Key differences:**
- v2 requires explicit `@classmethod` decorator
- v1 uses `@validator`, v2 uses `@field_validator`
- `pre=True` (v1) becomes `mode="before"` (v2)

---

## Field constraints (Field parameters)

### Basic usage (both versions)

```python
from pydantic import BaseModel, Field

class MemberOut(BaseModel):
    name: str
    is_deleted: Optional[bool] = Field(False, description="Soft delete status")
    role: Role = Field(Role.L1, description="User role")
```

### v2 constraint parameters

```python
class AWBOut(BaseModel):
    shipping_charge: Optional[float] = Field(None, ge=0, description="Charge in currency")
    awb_number: str = Field(..., min_length=1, description="Unique AWB identifier")
```

**Common Field parameters:**
- `default` / `default_factory`: Default value
- `alias`: Map API field name to Python field name
- `description`: OpenAPI/schema documentation
- `ge`, `le`, `gt`, `lt`: Numeric bounds (greater-equal, less-equal, etc.)
- `min_length`, `max_length`: String/list length bounds
- `...` (ellipsis): Required field (no default)

**When to use Field vs validators:**
- **Use Field:** Simple constraints (length, numeric bounds, defaults, descriptions)
- **Use validators:** Complex logic (cross-field validation, transformations, conditional rules)

---

## Field aliasing

Maps external API names (often camelCase) to Python snake_case fields.

### Example (from shipment serializers)

```python
class AWBOut(BaseModel):
    business_owner: Optional[str] = Field(None, alias="Business_owner")
    modified_owner: Optional[str] = Field(None, alias="Modified_Owner")
```

**When API returns:**
```json
{
  "Business_owner": "Team A",
  "Modified_Owner": "admin@example.com"
}
```

**Pydantic parses to:**
```python
awb = AWBOut.model_validate(data)
awb.business_owner  # "Team A"
awb.modified_owner  # "admin@example.com"
```

**Why used:** External APIs (especially legacy/SAP integrations) use different naming conventions than Python code. Aliasing keeps internal code Pythonic while maintaining API compatibility.

---

## String Enums for categorical fields

All status/role/type fields use `(str, Enum)` pattern:

### Example (from member serializers)

```python
from enum import Enum

class Role(str, Enum):
    L1 = "L1"
    L2 = "L2"
    ADMIN = "ADMIN"

class MemberBase(BaseModel):
    role: Role = Role.L1
```

### Example (from audit constants)

```python
import enum

class AuditInternalStatus(enum.Enum):
    NEW = "NEW"
    IN_RECONCILIATION = "IN_RECONCILIATION"
    SIGNOFF_PENDING = "SIGNOFF_PENDING"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"

class AuditVendorStatus(enum.Enum):
    NEW = "NEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
```

**Pattern:**
- Define in `constants.py` or at top of `serializers.py`
- Inherit from `(str, Enum)` (note the order)
- Use UPPERCASE values matching field names
- Import into schemas and use as field types

**Why `(str, Enum)`:** Ensures enum serializes as string in JSON (not int). Must inherit `str` first, then `Enum`.

> Confirmed against: https://docs.pydantic.dev/latest/concepts/types/#enums-and-choices (Pydantic automatically validates and serializes str Enums)

---

## Schema organization patterns

### Base → Create/Update/Retrieve pattern

**Example (from audit serializers):**

```python
class AuditBase(BaseModel):
    """Shared fields"""
    vendor_comment: Optional[str] = None
    invoice_amount: Optional[float] = None
    vendor_status: Optional[str] = None
    # ... common fields

    class Config:
        from_attributes = True

class CreateAudit(AuditBase):
    """Request schema for creating an audit"""
    @field_validator("*")
    def convert_to_upper(cls, v, field):
        # custom validation for create
        return v

class UpdateAudit(BaseModel):
    """Request schema for updating an audit (all fields optional)"""
    vendor_comment: Optional[str] = None
    invoice_amount: Optional[float] = None
    # ... update-specific fields + optional overrides

class RetrieveAudit(AuditBase):
    """Response schema with DB-generated fields"""
    id: int = None
    created_on: datetime = None
    vendor: Optional[RetrieveVendor] = None
    
    @classmethod
    def from_audit_data(cls, audit, invoice_ledger=None, ...):
        # custom factory method for complex response assembly
        audit_data = cls.model_validate(audit).model_dump()
        audit_data["invoice_ledger"] = RetrieveReport.model_validate(invoice_ledger).model_dump() if invoice_ledger else None
        return cls(**audit_data)

    class Config:
        from_attributes = True
```

**List response wrapper:**

```python
class ListAudit(BaseModel):
    audits: List[RetrieveAudit] = []
    paginated_info: Optional[Dict[Any, Any]] = None

    class Config:
        from_attributes = True
```

**Key principles:**
- `Base`: Common fields + ORM config
- `Create`: Inherits Base, adds validators for creation
- `Update`: Independent model, all fields optional (partial update)
- `Retrieve`: Inherits Base, adds DB-generated fields (id, timestamps, relations)
- `List<Entity>`: Wraps list of Retrieve models + pagination metadata

---

## Common patterns summary

| Pattern | Purpose | Applicable Services |
|---------|---------|---------------------|
| `loaded_config = Settings()` | Singleton settings instance | All services |
| `Field(alias="ApiName")` | Map external API names to Python fields | v2 services |
| `class Status(str, Enum)` | Categorical field values | All services |
| `@field_validator` + `@classmethod` | v2 field validation | v2 services |
| `@validator` | v1 field validation | v1 services |
| `from_attributes = True` | v2 ORM mode | v2 services |
| `orm_mode = True` | v1 ORM mode | v1 services |
| `Base` → `Create`/`Update`/`Retrieve` | Schema inheritance pattern | All services |
| `LogLevel` enum (unused) | Dead code to flag | Common pattern across services |
