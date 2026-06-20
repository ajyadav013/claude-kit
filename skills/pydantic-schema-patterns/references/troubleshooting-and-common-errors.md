# Troubleshooting and Common Errors

Common Pydantic errors encountered in production codebases and their solutions.

---

## ValidationError: missing positional argument (v2 field_validator)

**Error:**
```
TypeError: validate_priority() missing 1 required positional argument: 'v'
```

**Cause:** Forgot `@classmethod` decorator with `@field_validator` in v2.

**Fix:**
```python
# Wrong (v2)
@field_validator("priority")
def validate_priority(cls, v):  # Missing @classmethod
    return v

# Correct (v2)
@field_validator("priority")
@classmethod
def validate_priority(cls, v):
    return v
```

**Context:** Common mistake when migrating from v1 to v2. Production query serializers demonstrate correct usage.

---

## ModuleNotFoundError: No module named 'pydantic_settings'

**Error:**
```
ModuleNotFoundError: No module named 'pydantic_settings'
```

**Cause:** Using v2 `from pydantic_settings import BaseSettings` without installing the package.

**Fix:**
```bash
pip install pydantic-settings
```

**Note:** In Pydantic v2, BaseSettings was moved to a separate package. v1 included it in the main `pydantic` package.

**Context:** All v2 services require `pydantic-settings` in requirements.txt.

---

## AttributeError: 'Settings' object has no attribute 'from_attributes'

**Error:**
```
AttributeError: type object 'Config' has no attribute 'from_attributes'
```

**Cause:** Using v1 Pydantic with v2 syntax, or mixing v1/v2 imports.

**Fix:**
- If on v1, use `orm_mode = True` instead of `from_attributes = True`
- If on v2, ensure `pydantic>=2.0` in requirements.txt
- Check imports: v1 uses `from pydantic import BaseSettings`, v2 uses `from pydantic_settings import BaseSettings`

**Mixed codebase issue:** Some modules import v2 but keep v1 Config syntax. Ensure all v2 idioms are used together.

---

## Enum serialization as integer instead of string

**Error:** API returns `{"status": 1}` instead of `{"status": "PENDING"}`.

**Cause:** Enum doesn't inherit from `str`.

**Fix:**
```python
# Wrong
class Status(Enum):  # Serializes as int
    PENDING = "PENDING"
    APPROVED = "APPROVED"

# Correct
class Status(str, Enum):  # Serializes as string
    PENDING = "PENDING"
    APPROVED = "APPROVED"
```

**Note:** Order matters: `(str, Enum)` not `(Enum, str)`.

**Pattern:** Production services use `(str, Enum)` pattern consistently.

---

## ValidationError: field required

**Error:**
```
ValidationError: field required (type=value_error.missing)
```

**Cause:** Required field not provided when creating model instance.

**Common scenarios:**
1. **ORM mode disabled:** Forgot `from_attributes = True` / `orm_mode = True` when loading from SQLAlchemy models
2. **Field alias mismatch:** API sends `Business_owner` but schema expects `business_owner` without alias
3. **Missing default:** Field has no default value or `...` (ellipsis) marking it required

**Fix:**
```python
# Scenario 1: Enable ORM mode
class ItemOut(BaseModel):
    id: UUID
    name: str
    
    class Config:
        from_attributes = True  # v2 (or orm_mode = True for v1)

# Scenario 2: Add field alias
class AWBOut(BaseModel):
    business_owner: Optional[str] = Field(None, alias="Business_owner")

# Scenario 3: Provide default
class ItemCreate(BaseModel):
    name: str
    status: str = "PENDING"  # Has default, not required
```

---

## Multiple Settings instantiation causes config drift

**Issue:** Different parts of code see different config values.

**Cause:** Instantiating `Settings()` multiple times instead of using singleton pattern.

**Wrong:**
```python
# service/routes.py
from config.docker_config import Settings
settings = Settings()  # New instance!

# service/worker.py
from config.docker_config import Settings
settings = Settings()  # Another new instance!
```

**Correct:**
```python
# config/docker_config.py
class Settings(BaseSettings):
    # ... fields

loaded_config = Settings()  # Singleton

# service/routes.py
from config.docker_config import loaded_config

# service/worker.py
from config.docker_config import loaded_config
```

**Pattern:** All services use singleton pattern at module level: either `loaded_config = Settings()` or `settings = Settings()`.

---

## Field alias not working in response

**Issue:** Response shows Python field name (snake_case) instead of API name (camelCase).

**Cause:** Using `.model_dump()` without `by_alias=True` parameter.

**Fix:**
```python
class AWBOut(BaseModel):
    business_owner: Optional[str] = Field(None, alias="Business_owner")
    
    class Config:
        from_attributes = True

# Wrong
awb.model_dump()  # {"business_owner": "Team A"}

# Correct
awb.model_dump(by_alias=True)  # {"Business_owner": "Team A"}
```

**Note:** FastAPI automatically uses `by_alias=True` for response_model serialization, but manual `.model_dump()` calls need it explicitly.

---

## Extra environment variables causing errors

**Error:**
```
ValidationError: extra fields not permitted (type=value_error.extra)
```

**Cause:** `.env` file contains variables not defined in Settings schema, and Pydantic rejects them by default.

**Fix:**
```python
# v2 with SettingsConfigDict
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore"  # Ignore undefined env vars
    )
    
    DATABASE_URL: str
    # ... defined fields

# v1 or v2 with Config class
class Settings(BaseSettings):
    class Config:
        env_file = ".env"
        extra = "ignore"
    
    DATABASE_URL: str
```

**Pattern:** Modern services use `extra="ignore"` in SettingsConfigDict. Prevents errors when shared .env file has vars for multiple services.

---

## LogLevel enum defined but unused (dead code)

**Issue:** `class LogLevel(enum.Enum)` defined in docker_config.py but never imported or used elsewhere.

**Cause:** Copy-paste from template; never cleaned up.

**Fix:** Remove if truly unused, or use for typed log level field:
```python
class Settings(BaseSettings):
    LOG_LEVEL: str = LogLevel.INFO.value  # Use the enum
```

**Pattern:** Many services define LogLevel but never use it. Flag as dead code in reviews.

---

## Validator not triggering (mode issue)

**Issue:** v2 validator doesn't run on input data.

**Cause:** Missing `mode="before"` for pre-validation (runs after parsing).

**Fix:**
```python
# Run before Pydantic parsing (like v1 pre=True)
@field_validator("field_name", mode="before")
@classmethod
def validate_field(cls, v):
    # Transform raw input before type coercion
    return v

# Run after Pydantic parsing (default)
@field_validator("field_name")
@classmethod
def validate_field(cls, v):
    # Validate after type coercion
    return v
```

**Pattern:** v1 services use `@validator("contact_email", pre=True)`; equivalent v2 is `@field_validator("contact_email", mode="before")`.

---

## Common patterns summary

| Error | Cause | Fix |
|-------|-------|-----|
| Missing positional argument in validator | Forgot `@classmethod` with `@field_validator` (v2) | Add `@classmethod` below `@field_validator` |
| ModuleNotFoundError: pydantic_settings | v2 without pydantic-settings installed | `pip install pydantic-settings` |
| from_attributes not found | Using v2 syntax with v1 Pydantic | Use `orm_mode = True` (v1) or upgrade to v2 |
| Enum serializes as int | `class Status(Enum)` without str | Use `class Status(str, Enum)` |
| field required error | Missing ORM mode or field alias | Enable `from_attributes = True` or add `Field(alias=...)` |
| Config drift | Multiple Settings() instantiations | Use singleton pattern: `loaded_config = Settings()` |
| Alias not in response | `.model_dump()` without by_alias | Use `.model_dump(by_alias=True)` |
| Extra env vars error | .env has undefined variables | Add `extra="ignore"` to Config/SettingsConfigDict |
| Validator not running | Wrong mode (before vs after) | Add `mode="before"` if needed (v2) |
