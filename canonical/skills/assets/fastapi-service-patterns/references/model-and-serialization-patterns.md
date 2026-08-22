# Model and Serialization Patterns

FastAPI request/response serialization patterns using Pydantic v2.

## Pydantic model conventions

### Input models (request payloads)

```python
from pydantic import BaseModel, EmailStr, Field

class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
```

**What to copy**: use `Field()` for validation constraints (min_length, max_length, pattern, ge, le, etc.). Use `EmailStr` for email validation (requires `pydantic[email]`).

### Update models (partial updates)

```python
from typing import Optional

class UserUpdate(BaseModel):
    first_name: Optional[str] = Field(None, min_length=1, max_length=100)
    last_name: Optional[str] = Field(None, min_length=1, max_length=100)
    email: Optional[EmailStr] = None
```

**What to copy**: all fields `Optional` with `None` default for PATCH-style partial updates.

### Output models (response payloads)

```python
from pydantic import ConfigDict
from uuid import UUID
from datetime import datetime

class UserOut(BaseModel):
    id: UUID
    email: str
    first_name: str
    last_name: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
```

**What to copy**: use `model_config = ConfigDict(from_attributes=True)` (Pydantic v2) to enable ORM mode (populate from SQLAlchemy model attributes). Legacy Pydantic v1 used `Config.orm_mode = True`.

## ORM to Pydantic serialization

### Converting SQLAlchemy models to Pydantic

```python
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

async def get_user(user_id: UUID, session: AsyncSession) -> UserOut:
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserOut.model_validate(user)  # Pydantic v2: model_validate() instead of from_orm()
```

**What to copy**: use `Model.model_validate(orm_obj)` (Pydantic v2) or `Model.from_orm(orm_obj)` (Pydantic v1) to convert ORM instances to Pydantic models.

### In route handlers

```python
from fastapi import Depends
from app.connection import ConnectionHandler, get_connection_handler
from app.utils import ResponseData

async def get_user_endpoint(
    user_id: UUID,
    connection_handler: ConnectionHandler = Depends(get_connection_handler),
) -> ResponseData:
    dao = UserDAO(connection_handler.session)
    user = await dao.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return ResponseData.ok(data=UserOut.model_validate(user).model_dump(), message="User retrieved")
```

**What to copy**: convert ORM → Pydantic via `.model_validate()`, then Pydantic → dict via `.model_dump()` (Pydantic v2) or `.dict()` (v1) before passing to `ResponseData`.

## Settings with pydantic-settings

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    DEBUG: bool = False
    DATABASE_URL: str
    REDIS_URL: str
    JWT_SECRET: str
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
```

**What to copy**: use `pydantic_settings.BaseSettings` with `SettingsConfigDict(env_file=".env", extra="ignore")` to load from environment variables and `.env` file. `extra="ignore"` suppresses validation errors for unknown env vars.

## Validation patterns

### Field-level validation

```python
from pydantic import Field, field_validator

class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50, pattern=r"^[a-z0-9_]+$")

    @field_validator("username")
    @classmethod
    def username_must_not_start_with_digit(cls, v: str) -> str:
        if v[0].isdigit():
            raise ValueError("username cannot start with a digit")
        return v
```

**What to copy**: use `@field_validator("field_name")` (Pydantic v2) for custom validation. Must be a `@classmethod` returning the validated value.

### Model-level validation

```python
from pydantic import model_validator

class UserPasswordUpdate(BaseModel):
    password: str = Field(min_length=8)
    confirm_password: str = Field(min_length=8)

    @model_validator(mode="after")
    def passwords_match(self) -> "UserPasswordUpdate":
        if self.password != self.confirm_password:
            raise ValueError("passwords do not match")
        return self
```

**What to copy**: use `@model_validator(mode="after")` for cross-field validation. The method receives `self` (the model instance) and must return `self`.

## Nested models

```python
from typing import List

class AddressCreate(BaseModel):
    street: str
    city: str
    postal_code: str

class UserWithAddressCreate(BaseModel):
    email: EmailStr
    first_name: str
    last_name: str
    addresses: List[AddressCreate] = Field(default_factory=list)
```

**What to copy**: nest Pydantic models to represent one-to-many or one-to-one relationships in request payloads.

## model_dump() options

```python
user_out = UserOut.model_validate(user)
data = user_out.model_dump(
    mode="json",          # Serialize datetime/UUID to JSON-compatible types
    exclude_unset=True,   # Omit fields that weren't explicitly set
    exclude_none=True,    # Omit fields with None values
    by_alias=True,        # Use field aliases (e.g., camelCase) if defined
)
```

**What to copy**: use `mode="json"` to auto-serialize datetime/UUID/etc. to JSON-compatible types. `exclude_unset` and `exclude_none` reduce response payload size.

## Summary checklist

- [ ] Use Pydantic `BaseModel` for request/response schemas
- [ ] Add `Field()` constraints for validation (min_length, max_length, pattern, ge, le)
- [ ] Use `EmailStr` for email fields (requires `pydantic[email]`)
- [ ] Set `model_config = ConfigDict(from_attributes=True)` on output models for ORM compatibility
- [ ] Convert ORM to Pydantic via `Model.model_validate(orm_obj)`
- [ ] Convert Pydantic to dict via `.model_dump(mode="json")` before passing to `ResponseData`
- [ ] Use `pydantic_settings.BaseSettings` with `SettingsConfigDict(env_file=".env")` for app settings
- [ ] Use `@field_validator` for single-field validation, `@model_validator(mode="after")` for cross-field validation
- [ ] Define update models with all `Optional` fields for partial updates
- [ ] Nest Pydantic models to represent relationships in request payloads
