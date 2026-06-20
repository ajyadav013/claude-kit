# Pydantic Schema Patterns

This skill encodes Pydantic usage conventions from real-world production Python/FastAPI backend microservices, covering both Pydantic v1 and v2 idioms. It documents the BaseSettings singleton pattern (with config_parser or env_file sources), request/response schema organization, field validation, ORM mode configuration, SettingsConfigDict usage, field aliasing, and string Enum usage.

## What this skill covers

- **Settings modules:** `Settings(BaseSettings)` pattern with `config_parser.docker_args` source and `loaded_config` singleton, or `SettingsConfigDict(env_file=".env")` and `settings` singleton (cleaner modern approach)
- **Version-specific imports:** `pydantic_settings.BaseSettings` (v2) vs `pydantic.BaseSettings` (v1)
- **ORM mode:** `from_attributes = True` / `ConfigDict(from_attributes=True)` (v2) vs `orm_mode = True` (v1)
- **SettingsConfigDict:** Modern v2 pattern for env-based config (`model_config = SettingsConfigDict(env_file=".env", extra="ignore")`)
- **Validators:** `@field_validator` with `@classmethod` (v2) vs `@validator` (v1)
- **Field constraints:** `Field(..., min_length=, ge=, alias=, description=)`
- **String Enums:** `class FieldName(str, Enum)` for status/role/type fields
- **Schema organization:** `Base` → `Create`/`Update`/`Retrieve` pattern in `serializers.py` / `schemas.py`

## Provenance

Derived from real-world production Python/FastAPI services covering both Pydantic v1 (legacy services) and v2 (modern services) patterns.

## How to apply

1. **For new services:** Use Pydantic v2 idioms (pydantic_settings, from_attributes, field_validator).
2. **For v1 services:** Maintain v1 patterns (pydantic.BaseSettings, orm_mode, @validator) unless migrating.
3. **Settings module:** Always define `loaded_config = Settings()` or `settings = Settings()` at module level; import from `config.docker_config` or `config.settings`.
4. **Schemas:** Use `Field(alias=...)` for API/Python naming mismatches; define string Enums for categorical fields; organize as `Base` → variants.
5. **Validators:** Prefer `Field` constraints over validators for simple rules; use validators for complex logic only.
6. **Migration:** When moving v1 → v2, update imports, Config class, and validator decorators together (see `v1-vs-v2.md`).

## Pattern provenance

- **Production-derived:**
  - Settings singleton pattern (`loaded_config = Settings()` or `settings = Settings()`)
  - Field aliasing for camelCase API keys (`Field(alias="Business_owner")`)
  - String Enum usage (`class Status(str, Enum)`)
  - Schema organization (`serializers.py` per domain, Base → Create/Retrieve variants)
  - LogLevel enum (often unused)
  
- **Internet-confirmed:**
  - Pydantic v2 migration (pydantic_settings package, from_attributes, field_validator) — confirmed against https://docs.pydantic.dev/latest/migration/
  - ConfigDict usage — confirmed against https://docs.pydantic.dev/latest/api/config/
