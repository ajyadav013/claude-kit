# Example Patterns

Representative code patterns from production Python/FastAPI services demonstrating Pydantic schema conventions.

---

## Service A (Pydantic v2 - Cleanest Reference)

**What to copy:** SettingsConfigDict, env_file pattern, settings singleton (not loaded_config), clean v2 idioms without legacy config_parser.

### config/settings.py
```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    All configuration is typed and validated at startup.  Secrets must
    never be committed -- use ``.env`` or environment injection.
    """
    
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    
    # Environment
    ENV: str = "development"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    
    # Database
    DATABASE_URL: str
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    
    # Redis
    REDIS_URL: str | None = None
    
    # API Keys
    API_KEY: str
    # ... more typed fields loaded from .env

settings = Settings()
```

**Key differences from config_parser pattern:**
- Uses `settings = Settings()` instead of `loaded_config = Settings()`
- No `config_parser.docker_args` intermediary — fields load directly from `.env` via SettingsConfigDict
- Uses `model_config = SettingsConfigDict(...)` at class level instead of nested `class Config`
- Cleaner type hints with v2 union syntax (`str | None` instead of `Optional[str]`)
- `extra="ignore"` prevents errors from extra env vars not defined in schema

---

## Service B (Pydantic v2.8)

**What to copy:** pydantic_settings import, from_attributes, field_validator, string Enum definitions.

### config/docker_config.py
```python
from pydantic_settings import BaseSettings
from config.config_parser import docker_args

class LogLevel(enum.Enum):
    NOTSET = "NOTSET"
    DEBUG = "DEBUG"
    INFO = "INFO"
    # ... more levels

class Settings(BaseSettings):
    HOST: str = args.HOST
    ENV: str = args.ENV
    # ... 100+ fields from args
    http: AsyncHTTPClient | None = None

loaded_config = Settings()
```

### app/v1/audit/serializers.py
```python
from pydantic import BaseModel, field_validator

class AuditBase(BaseModel):
    vendor_status: Optional[str] = None
    internal_status: Optional[str] = None
    # ... more fields

    class Config:
        from_attributes = True

class CreateAudit(AuditBase):
    @field_validator("*")
    def convert_to_upper(cls, v, field):
        if isinstance(v, AuditInternalStatus) or isinstance(v, AuditVendorStatus):
            return v.value
        return v
```

### app/v1/audit/constants.py
```python
import enum

class AuditInternalStatus(enum.Enum):
    NEW = "NEW"
    IN_RECONCILIATION = "IN_RECONCILIATION"
    COMPLETED = "COMPLETED"
    # ... more statuses

class AuditVendorStatus(enum.Enum):
    NEW = "NEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
```

---

## Service C (Pydantic v2.11)

**What to copy:** Field(alias=...), str Enum, model_config, field_validator with @classmethod.

### app/v1/shipments/serializers.py
```python
from pydantic import BaseModel, Field

class AWBOut(BaseModel):
    awb_number: str
    shipping_charge: Optional[float] = None
    business_owner: Optional[str] = Field(None, alias="Business_owner")
    modified_owner: Optional[str] = Field(None, alias="Modified_Owner")
    # ... 60+ fields

    class Config:
        from_attributes = True

class AllAWBsResponse(BaseModel):
    awbs: List[AWBOut] = []
    paginated_info: Optional[Dict[Any, Any]] = None

    class Config:
        from_attributes = True
```

### app/v1/member/serializers.py
```python
from enum import Enum
from pydantic import BaseModel, EmailStr, Field

class Role(str, Enum):
    L1 = "L1"
    L2 = "L2"
    ADMIN = "ADMIN"

class MemberBase(BaseModel):
    email: EmailStr
    name: str
    role: Role = Role.L1

class MemberOut(MemberBase):
    id: uuid.UUID
    is_deleted: Optional[bool] = Field(False, description="Soft delete status")

    class Config:
        from_attributes = True
```

### app/v1/query/serializers.py
```python
from pydantic import field_validator

class RaiseQueryRequest(BaseModel):
    priority: str
    description: str
    affected_invoices: List[str]

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

---

## Service D (Pydantic v2.11)

**What to copy:** pydantic_settings, class Config with env_file, os.environ fallbacks for settings.

### config/docker_config.py
```python
from pydantic_settings import BaseSettings
from config.config_parser import docker_args

class Settings(BaseSettings):
    class Config:
        env_file = "../../.env"
        env_file_encoding = "utf-8"

    ENV: str = args.ENV
    POSTGRES_READ_WRITE: str = os.environ.get(
        "POSTGRES_READ_WRITE",
        "postgresql://postgres:<REDACTED>@localhost:5432/app_db",
    )
    # ... many fields with os.environ.get fallbacks
    http: Union[AsyncHTTPClient, None] = None

loaded_config = Settings()
```

---

## Service E (Pydantic v1.10)

**What to copy:** pydantic.BaseSettings, orm_mode, @validator.

### config/docker_config.py
```python
from pydantic import BaseSettings
from config.config_parser import docker_args

class LogLevel(enum.Enum):
    NOTSET = "NOTSET"
    DEBUG = "DEBUG"
    # ... more levels

class Settings(BaseSettings):
    host: str = args.host
    ENV: str = args.env
    db_url = args.postgres_read_write
    # ... many fields from args

loaded_config = Settings()
```

### app/shipment/schemas.py
```python
from pydantic import BaseModel, validator, EmailStr

class ContactDetails(BaseModel):
    contact_name: str
    contact_email: Optional[EmailStr]

    @validator("contact_email", pre=True)
    def validate_empty_string(cls, v):
        if v == "":
            return None
        return v

class ShipmentDetails(ShipmentBase):
    packages: List[Package]

    class Config:
        orm_mode = True
```

---

## Service F (Pydantic v1.10)

**What to copy:** pydantic.BaseSettings (v1), loaded_config pattern.

### config/docker_config.py
```python
from pydantic import BaseSettings
from config.config_parser import docker_args

class LogLevel(enum.Enum):
    NOTSET = "NOTSET"
    DEBUG = "DEBUG"
    # ... more levels

class Settings(BaseSettings):
    host: str = args.host
    ENV: str = args.env
    db_url = args.postgres_read_write
    redis_read_write_url = args.redis_read_write
    # ... many fields

loaded_config = Settings()
loaded_config.http = AsyncHTTPClient()
```

---

## Key patterns to copy

1. **Settings singleton:** `loaded_config = Settings()` or `settings = Settings()` at module level — never instantiate more than once
2. **Settings source (two approaches):**
   - **config_parser pattern:** Fields assigned from `docker_args.<FIELD>`, defined in `config/docker_config.py`
   - **env_file pattern:** `model_config = SettingsConfigDict(env_file=".env", extra="ignore")`, fields load directly from environment
3. **ORM mode:** `from_attributes = True` (v2) or `orm_mode = True` (v1) for SQLAlchemy models
4. **String Enums:** `class FieldName(str, Enum): VALUE = "VALUE"` (note: str first, then Enum)
5. **Field aliasing:** `Field(None, alias="CamelCase")` to map API naming to Python conventions
6. **Validators:** `@field_validator` + `@classmethod` (v2) or `@validator` (v1) — v2 requires explicit @classmethod
7. **Schema organization:** `Base` → `Create`/`Update`/`Retrieve` classes per domain in `serializers.py` or `schemas.py`
