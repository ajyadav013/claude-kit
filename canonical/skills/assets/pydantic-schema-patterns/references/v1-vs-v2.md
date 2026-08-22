# Pydantic v1 vs v2 Migration Guide

Side-by-side comparison of Pydantic v1 and v2 idioms as observed in production Python/FastAPI services.

## Version distribution

| Version | Import Path | Notes |
|---------|-------------|-------|
| **v2** (2.8 - 2.11) | `pydantic_settings.BaseSettings` | Modern services |
| **v1** (1.10) | `pydantic.BaseSettings` | Legacy services |

---

## BaseSettings import

| v1 (legacy services) | v2 (modern services) |
|----------------------|-------------------------------------|
| `from pydantic import BaseSettings` | `from pydantic_settings import BaseSettings` |

> Confirmed against: https://docs.pydantic.dev/latest/migration/#basesettings-has-moved-to-pydantic-settings

**Migration:** Install `pydantic-settings` and change import line.

---

## ORM mode configuration (for ORM models)

| v1 | v2 (option 1) | v2 (option 2) |
|----|---------------|---------------|
| `class Config:` <br> `    orm_mode = True` | `class Config:` <br> `    from_attributes = True` | `from pydantic import ConfigDict` <br><br> `model_config = ConfigDict(from_attributes=True)` |

**Examples:**
- v1: legacy `shipment/schemas.py`
- v2 (option 1): `shipments/serializers.py`, `audit/serializers.py`
- v2 (option 2): `query/serializers.py` (less common)

> Confirmed against: https://docs.pydantic.dev/latest/migration/#changes-to-config

**Migration:** Replace `orm_mode = True` with `from_attributes = True` in existing `Config` class, or use `model_config = ConfigDict(from_attributes=True)` for new code.

---

## Settings configuration (for BaseSettings)

| v1 | v2 (legacy compatible) | v2 (modern - cleanest) |
|----|------------------------|------------------------|
| `class Config:` <br> `    env_file = ".env"` | `class Config:` <br> `    env_file = ".env"` <br> `    env_file_encoding = "utf-8"` | `from pydantic_settings import SettingsConfigDict` <br><br> `model_config = SettingsConfigDict(` <br> `    env_file=".env",` <br> `    extra="ignore"` <br> `)` |

**Examples:**
- v1: legacy services (though they use config_parser, not env_file)
- v2 (legacy compatible): some v2 services use nested `class Config` with env_file
- v2 (modern): cleanest approach uses `SettingsConfigDict` at class level

> Confirmed against: https://docs.pydantic.dev/latest/concepts/pydantic_settings/#dotenv-env-support

**Key advantages of SettingsConfigDict (v2 modern):**
- Cleaner syntax (class-level assignment vs nested class)
- More explicit configuration options (`extra="ignore"` prevents errors from undefined env vars)
- Aligns with ConfigDict pattern used elsewhere in v2
- No need for separate config_parser module if using .env directly

**Migration:** Replace nested `class Config` with `model_config = SettingsConfigDict(env_file=".env", extra="ignore")` for new services. Services using config_parser can continue that pattern.

---

## Validators

| v1 | v2 |
|----|-----|
| `from pydantic import validator` <br><br> `@validator("field_name", pre=True)` <br> `def validate_field(cls, v):` <br> `    # validation logic` <br> `    return v` | `from pydantic import field_validator` <br><br> `@field_validator("field_name")` <br> `@classmethod` <br> `def validate_field(cls, v):` <br> `    # validation logic` <br> `    return v` |

**Examples:**
- v1: `shipment/schemas.py` uses `@validator("contact_email", pre=True)`
- v2: `query/serializers.py` uses `@field_validator("priority")` + `@classmethod`; `audit/serializers.py` uses `@field_validator("*")`

> Confirmed against: https://docs.pydantic.dev/latest/migration/#changes-to-validators

**Key differences:**
- v2 requires `@classmethod` decorator explicitly
- `pre=True` becomes mode parameter in v2: `@field_validator("field", mode="before")`
- Wildcard validators use `"*"` in both versions

**Migration:** Replace `@validator` with `@field_validator`, add `@classmethod`, and convert `pre=True` to `mode="before"`.

---

## Field constraints and metadata

| Common (both versions) | v2 enhancements |
|------------------------|-----------------|
| `Field(default, alias="ApiName")` <br> `Field(..., min_length=1)` <br> `Field(None, description="...")` | `Field(..., ge=0, le=100)` <br> `Field(..., json_schema_extra={...})` |

**Examples:** Production services use `Field(None, alias="Business_owner")`, `Field(False, description="Soft delete status")`, `Field(..., ge=, description=)`

Field API is largely compatible; v2 adds more constraint options and replaces `schema_extra` with `json_schema_extra`.

---

## Model methods

| v1 | v2 |
|----|-----|
| `.dict()` <br> `.parse_obj(obj)` <br> `.parse_raw(json_str)` | `.model_dump()` <br> `.model_validate(obj)` <br> `.model_validate_json(json_str)` |

**Examples:** Production v2 code uses `.model_validate(audit).model_dump()` and `.model_validate(invoice_ledger).model_dump()`

> Confirmed against: https://docs.pydantic.dev/latest/migration/#changes-to-model-methods

**Migration:** Rename `.dict()` → `.model_dump()`, `.parse_obj()` → `.model_validate()`, `.parse_raw()` → `.model_validate_json()`.

---

## Summary checklist for v1 → v2 migration

1. **Install:** `pip install pydantic-settings` (if using BaseSettings)
2. **Imports:**
   - `from pydantic import BaseSettings` → `from pydantic_settings import BaseSettings`
   - `from pydantic import validator` → `from pydantic import field_validator`
3. **Config class (for ORM models):**
   - `orm_mode = True` → `from_attributes = True`
4. **Config class (for Settings models - optional modernization):**
   - Nested `class Config: env_file = ".env"` → `model_config = SettingsConfigDict(env_file=".env", extra="ignore")`
5. **Validators:**
   - Add `@classmethod` below `@field_validator`
   - `@validator("field", pre=True)` → `@field_validator("field", mode="before")`
6. **Model methods:**
   - `.dict()` → `.model_dump()`
   - `.parse_obj()` → `.model_validate()`
   - `.parse_raw()` → `.model_validate_json()`
7. **Type hints (optional modernization):**
   - `Optional[str]` → `str | None` (requires Python 3.10+)
8. **Test thoroughly:** Validators, serialization, ORM integration, settings loading.

---

## Mixed v1/v2 anti-pattern

**Observed issue:** Some files import v2 `field_validator` but retain v1-style `Config` with `orm_mode`. This causes runtime errors.

**Fix:** Ensure all v2 idioms are used together. If importing from `pydantic` v2, also update `Config` to use `from_attributes = True`.
