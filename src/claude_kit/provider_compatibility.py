"""Validated provider compatibility data used by native projections.

Compatibility catalogs are executable projection policy, not documentation-only
inventories.  Keep their loading here so generators and runtime renderers consume
the same schema-checked model and permission mappings.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, Mapping

import yaml

from claude_kit.components import ModelTier, PermissionClass

ProviderName = Literal["claude", "codex"]


class ProviderCompatibilityError(ValueError):
    """A provider compatibility catalog is missing or invalid."""


@dataclass(frozen=True)
class AgentProjectionCompatibility:
    """Schema-validated mappings for one provider's native agent surface."""

    provider: ProviderName
    catalog_version: int
    model_tiers: Mapping[ModelTier, str | None]
    permission_classes: Mapping[PermissionClass, str]


def _load_document(root: Path, provider: ProviderName) -> dict[str, Any]:
    catalog_path = root / "catalog" / f"{provider}-compatibility.yaml"
    schema_path = root / "schemas" / f"{provider}-compatibility.schema.json"
    try:
        document = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, yaml.YAMLError) as exc:
        raise ProviderCompatibilityError(
            f"cannot load {provider} compatibility policy: {exc}"
        ) from exc
    if not isinstance(document, dict):
        raise ProviderCompatibilityError(
            f"{provider} compatibility policy must be an object"
        )

    import jsonschema

    validator_class = jsonschema.validators.validator_for(schema)
    validator_class.check_schema(schema)
    errors = sorted(
        validator_class(schema).iter_errors(document),
        key=lambda error: list(error.path),
    )
    if errors:
        error = errors[0]
        location = "/".join(str(part) for part in error.path) or "(root)"
        raise ProviderCompatibilityError(
            f"{provider} compatibility policy is invalid at {location}: {error.message}"
        )
    return document


def load_agent_projection_compatibility(
    root: str | Path, provider: ProviderName
) -> AgentProjectionCompatibility:
    """Load schema-validated native model and permission mappings."""

    document = _load_document(Path(root), provider)
    version = document["version"]
    agents = document["agents"]
    raw_models = agents["model_tier_mapping"]
    permission_field = (
        "permission_class_mapping" if provider == "claude" else "sandbox_mapping"
    )
    raw_permissions = agents[permission_field]

    model_tiers: dict[ModelTier, str | None] = {}
    for tier in ModelTier:
        value = raw_models[tier.value]
        if value is not None and not isinstance(value, str):  # schema defense in depth
            raise ProviderCompatibilityError(
                f"{provider} model mapping for {tier.value} must be a string or null"
            )
        model_tiers[tier] = value

    permission_classes: dict[PermissionClass, str] = {}
    for permission in PermissionClass:
        value = raw_permissions[permission.value]
        if not isinstance(value, str):  # schema defense in depth
            raise ProviderCompatibilityError(
                f"{provider} permission mapping for {permission.value} must be a string"
            )
        permission_classes[permission] = value

    return AgentProjectionCompatibility(
        provider=provider,
        catalog_version=version,
        model_tiers=MappingProxyType(model_tiers),
        permission_classes=MappingProxyType(permission_classes),
    )


__all__ = [
    "AgentProjectionCompatibility",
    "ProviderCompatibilityError",
    "load_agent_projection_compatibility",
]
