---
name: pydantic-schema-patterns
description: Pydantic v1 and v2 patterns for Python/FastAPI — BaseSettings singleton, request/response schemas, field validation, ORM mode config, aliasing, Enums. Use for settings, API schemas, or version migration.
---

# Pydantic schema patterns

Encoding Pydantic conventions from real-world production Python/FastAPI backend services. Both Pydantic v1 and v2 are in active use across the codebase.

## When to use

- Defining application settings with BaseSettings and a config_parser source
- Creating request/response schemas for FastAPI endpoints
- Adding field validators or aliasing for API compatibility
- Configuring ORM mode for SQLAlchemy model serialization
- Defining string-based Enums for status/type fields
- Migrating schemas from Pydantic v1 to v2

## Core conventions

1. **Settings singleton pattern.** Define `Settings(BaseSettings)` in `config/docker_config.py` or `config/settings.py` with fields sourced from `config_parser.docker_args` (one common approach) or environment variables via `model_config = SettingsConfigDict(env_file=".env")` (cleaner modern approach). Create a module-level singleton: `loaded_config = Settings()` or `settings = Settings()`. Import throughout the service. Never instantiate Settings more than once.

2. **Version-specific BaseSettings import.** v2 services import from `pydantic_settings`; v1 services import from `pydantic.BaseSettings`. v2 services (2.8+, 2.11+) use `pydantic_settings`; v1 services (1.10) use `pydantic`.

3. **ORM mode configuration varies by version.** v2 uses `class Config: from_attributes = True` inside the model class or `model_config = ConfigDict(from_attributes=True)` at class level; v1 uses `class Config: orm_mode = True`. For settings classes, v2 prefers `model_config = SettingsConfigDict(env_file=".env", extra="ignore")` for environment loading. Most modern services use v2 idioms; legacy services use v1.

4. **Field validators follow version-specific decorators.** v2 uses `@field_validator("field_name")` with `@classmethod`; v1 uses `@validator("field_name")`. Modern services use `@field_validator`; legacy services use `@validator`.

5. **Field aliasing maps API to Python naming.** Use `Field(..., alias="CamelCase")` to map external camelCase API keys to internal snake_case fields. Common in response schemas that integrate with external APIs or legacy systems.

6. **String Enums for categorical fields.** Define enums as `class FieldName(str, Enum)` with uppercase values for status, role, type fields. Import `enum.Enum` from standard library. Examples: Role, AuditInternalStatus, AuditVendorStatus.

7. **Schema organization per domain.** Request/response schemas live in domain-specific `serializers.py` or `schemas.py` files, inheriting from `BaseModel`. Common pattern: `Base` → `Create`/`Update`/`Retrieve` variants.

8. **LogLevel enum in settings is often unused.** Many services define `class LogLevel(enum.Enum)` in docker_config.py but never reference it—flag as dead code if not used.

9. **Field constraints use Field parameters.** v2 schemas use `Field(..., min_length=, ge=, description=)` for validation and docs. Validators are for complex logic only.

10. **Mixed v1/v2 idioms flag inconsistency.** Some modules have leftover `Config.orm_mode` alongside v2 `model_config` imports; consolidate to one version's idiom.

11. **SettingsConfigDict for env-based config (v2).** Modern v2 services use `model_config = SettingsConfigDict(env_file=".env", extra="ignore")` at class level instead of nested `Config` class. This pattern cleanly loads environment variables without a config_parser intermediary.

## Skeleton / example

```python
# config/docker_config.py (v2)
import enum
from pydantic_settings import BaseSettings
from config.config_parser import docker_args

args = docker_args

class LogLevel(enum.Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"

class Settings(BaseSettings):
    ENV: str = args.ENV
    DEBUG: bool = args.DEBUG
    db_url: str = args.POSTGRES_READ_WRITE
    REDIS_URL: str = args.REDIS_READ_WRITE
    KAFKA_BROKER_LIST: str = args.KAFKA_BROKER_LIST
    # ... more fields from docker_args

loaded_config = Settings()
```

```python
# config/settings.py (v2 with SettingsConfigDict - cleanest approach)
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    """Application settings loaded from .env file."""
    
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    
    # Environment
    ENV: str = "development"
    DEBUG: bool = False
    
    # Database
    DATABASE_URL: str
    DB_POOL_SIZE: int = 10
    
    # Redis
    REDIS_URL: str | None = None
    
    # Service config
    LOG_LEVEL: str = "INFO"
    API_KEY: str

settings = Settings()
```

```python
# domain/serializers.py (v2)
from datetime import datetime
from enum import Enum
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, Field, field_validator

class Status(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"

class ItemBase(BaseModel):
    name: str
    status: Status
    amount: Optional[float] = Field(None, ge=0, description="Amount in currency")
    business_owner: Optional[str] = Field(None, alias="Business_owner")

    class Config:
        from_attributes = True

class ItemCreate(ItemBase):
    @field_validator("name")
    @classmethod
    def validate_name(cls, v):
        if not v or not v.strip():
            raise ValueError("Name must not be empty")
        return v

class ItemOut(ItemBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class ListItemOut(BaseModel):
    items: List[ItemOut] = []
    total: int

    class Config:
        from_attributes = True
```

```python
# domain/schemas.py (v1)
from pydantic import BaseModel, validator, EmailStr

class ContactDetails(BaseModel):
    contact_name: str
    contact_email: Optional[EmailStr]

    @validator("contact_email", pre=True)
    def validate_empty_string(cls, v):
        if v == "":
            return None
        return v

    class Config:
        orm_mode = True
```

## Anti-patterns to avoid

- Importing `BaseSettings` from `pydantic` in v2 projects (use `pydantic_settings`)
- Mixing `orm_mode = True` (v1) with `model_config = ConfigDict(...)` (v2) in the same codebase
- Leaving `LogLevel` enum defined but unused (dead code — common pattern to flag in reviews)
- Using validators for simple constraints that `Field(min_length=, ge=)` can handle
- Forgetting `@classmethod` decorator with `@field_validator` in v2 (runtime error: missing positional argument)
- Instantiating `Settings()` multiple times instead of using the singleton pattern
- Using nested `class Config` for settings when `model_config = SettingsConfigDict(...)` is cleaner (v2)
- Not aliasing fields when API contract uses different naming than Python conventions (common in legacy SAP/ERP integrations)

## References

- [repo-evidence.md](references/repo-evidence.md) — example patterns from production services
- [v1-vs-v2.md](references/v1-vs-v2.md) — side-by-side migration table with SettingsConfigDict
- [settings-and-validation.md](references/settings-and-validation.md) — BaseSettings patterns (config_parser vs env_file), validators, enums, aliasing
- [troubleshooting-and-common-errors.md](references/troubleshooting-and-common-errors.md) — ValidationError fixes, migration issues, dead code patterns
