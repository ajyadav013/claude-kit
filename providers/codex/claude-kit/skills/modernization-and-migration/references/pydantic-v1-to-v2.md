# Pydantic v1 to v2 Migration

Concrete migration patterns for upgrading from Pydantic v1 to v2, derived from contrasting legacy services against modern reference services.

## Key Breaking Changes

### 1. `@validator` → `@field_validator`

**Before (Pydantic v1 - legacy service example):**
```python
from pydantic import BaseModel, validator

class Package(BaseModel):
    contact_email: str
    
    @validator('contact_email', pre=True)
    def validate_email(cls, v):
        if not v or '@' not in v:
            raise ValueError('Invalid email')
        return v.lower()
```

**After (Pydantic v2 - reference service):**
```python
from pydantic import BaseModel, field_validator

class Package(BaseModel):
    contact_email: str
    
    @field_validator('contact_email', mode='before')
    @classmethod
    def validate_email(cls, v: str) -> str:
        if not v or '@' not in v:
            raise ValueError('Invalid email')
        return v.lower()
```

**Migration steps:**
1. Replace `@validator` with `@field_validator`
2. Replace `pre=True` with `mode='before'`
3. Add `@classmethod` decorator (required in v2)
4. Add type hints to validator method signature

**Example patterns:**
- Legacy: `app/shipment/schemas.py` line 112 (`@validator('contact_email', pre=True)`)
- Legacy: `app/shipment/map_utils.py` line 23 (`@validator("latitude", "longitude", pre=True)`)

### 2. `class Config` → `model_config`

**Before (Pydantic v1 - legacy service example):**
```python
from pydantic import BaseModel

class ContactDetails(BaseModel):
    contact_name: str
    contact_email: str
    
    class Config:
        orm_mode = True
```

**After (Pydantic v2 - reference service):**
```python
from pydantic import BaseModel, ConfigDict

class OrgOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    
    model_config = ConfigDict(from_attributes=True)
```

**Migration steps:**
1. Import `ConfigDict` from `pydantic`
2. Replace `class Config:` with `model_config = ConfigDict(...)`
3. Replace `orm_mode = True` with `from_attributes=True`

**Common Config options mapping:**
- `orm_mode = True` → `from_attributes=True`
- `allow_population_by_field_name = True` → `populate_by_name=True`
- `use_enum_values = True` → `use_enum_values=True` (unchanged)
- `arbitrary_types_allowed = True` → `arbitrary_types_allowed=True` (unchanged)

**Example patterns:**
- Legacy: `app/shipment/schemas.py` lines 66, 162, 178, 212 (`class Config: orm_mode = True`)
- Modern: `app/identity/v1/organization/serializers.py` lines 65, 76, 93, 104 (`model_config = ConfigDict(from_attributes=True)`)

### 3. `BaseSettings` Import Move

**Before (Pydantic v1 - legacy service example):**
```python
from pydantic import BaseSettings

class Settings(BaseSettings):
    database_url: str
    redis_host: str
    
    class Config:
        env_file = '.env'
        case_sensitive = False
```

**After (Pydantic v2 - requires pydantic-settings package):**
```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    database_url: str
    redis_host: str
    
    model_config = SettingsConfigDict(
        env_file='.env',
        case_sensitive=False,
    )
```

**Migration steps:**
1. Install `pydantic-settings` package: `pip install pydantic-settings`
2. Change import from `pydantic` to `pydantic_settings`
3. Import `SettingsConfigDict` for config
4. Replace `class Config:` with `model_config = SettingsConfigDict(...)`

**Example patterns:**
- Legacy: `config/docker_config.py` line 6 (`from pydantic import BaseSettings`)

### 4. Field Constraints Syntax

**Before (Pydantic v1 - legacy service example):**
```python
from pydantic import BaseModel, Field, constr, conint

class EwaybillSchema(BaseModel):
    transaction_id: constr(min_length=1, max_length=15)
    vehicle_number: constr(regex=r'^[A-Z]{2}\d{2}[A-Z]{2}\d{4}$')
    distance: conint(ge=0, le=4000)
```

**After (Pydantic v2):**
```python
from pydantic import BaseModel, Field
from typing import Annotated

class EwaybillSchema(BaseModel):
    transaction_id: Annotated[str, Field(min_length=1, max_length=15)]
    vehicle_number: Annotated[str, Field(pattern=r'^[A-Z]{2}\d{2}[A-Z]{2}\d{4}$')]
    distance: Annotated[int, Field(ge=0, le=4000)]
```

**Migration steps:**
1. Replace `constr(...)` with `Annotated[str, Field(...)]`
2. Replace `conint(...)` with `Annotated[int, Field(...)]`
3. Replace `regex=` with `pattern=` in Field
4. Import `Annotated` from `typing`

**Example patterns:**
- Legacy: `app/ewaybill/serializer.py` line 7 (`from pydantic import BaseModel, Field, constr, conint`)

### 5. Schema Inheritance and Generic Models

**Before (Pydantic v1):**
```python
from pydantic import BaseModel
from pydantic.generics import GenericModel
from typing import Generic, TypeVar

T = TypeVar('T')

class PaginatedResponse(GenericModel, Generic[T]):
    items: List[T]
    total: int
```

**After (Pydantic v2):**
```python
from pydantic import BaseModel
from typing import Generic, TypeVar

T = TypeVar('T')

class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
```

**Migration steps:**
1. Remove `pydantic.generics.GenericModel` import
2. Replace `GenericModel` with `BaseModel` in generic classes
3. Use `list[T]` instead of `List[T]` (Python 3.9+ syntax)

## Migration Checklist

1. **Dependency update**:
   - Update `pydantic` to `>=2.0` in requirements.txt
   - Add `pydantic-settings` if using `BaseSettings`

2. **Code changes**:
   - [ ] Replace all `@validator` with `@field_validator` + `@classmethod`
   - [ ] Replace `class Config` with `model_config = ConfigDict(...)`
   - [ ] Replace `orm_mode = True` with `from_attributes=True`
   - [ ] Update `BaseSettings` import to `pydantic_settings`
   - [ ] Replace `constr`/`conint` with `Annotated[str/int, Field(...)]`
   - [ ] Replace `regex=` with `pattern=` in Field validators
   - [ ] Remove `GenericModel` and use `BaseModel` for generics

3. **Testing**:
   - [ ] Run full test suite
   - [ ] Verify ORM model serialization (`.model_dump()` instead of `.dict()`)
   - [ ] Verify JSON serialization (`.model_dump_json()` instead of `.json()`)
   - [ ] Check validation error messages (format changed in v2)

## Common Gotchas

1. **`pre=True` vs `mode='before'`**: The `mode` parameter is required in v2; omitting it defaults to `mode='after'` which validates after parsing.

2. **Validator must be classmethod**: Pydantic v2 requires `@classmethod` on all validators, even if you don't use `cls`.

3. **`.dict()` → `.model_dump()`**: Serialization method renamed in v2. Use `.model_dump()` for dict, `.model_dump_json()` for JSON.

4. **`parse_obj()` → `model_validate()`**: Parsing method renamed. Use `Model.model_validate(data)` instead of `Model.parse_obj(data)`.

5. **`update_forward_refs()` → `model_rebuild()`**: Forward reference resolution method renamed.

## Reference Service as the Authoritative Example

When migrating, use the reference service as the authoritative Pydantic v2 example:
- `app/identity/v1/organization/serializers.py`
- `app/identity/v1/tenant/serializers.py`
- `app/identity/v1/token/serializers.py`

All reference service serializers use `model_config = ConfigDict(from_attributes=True)` and no legacy v1 patterns.
