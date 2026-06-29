"""Optional JSON Schema validation for catalog files and persisted artifacts.

Schemas (Draft 2020-12) live under the payload ``schemas/`` directory and are loaded via
:func:`claude_kit.scaffold.payload_dir` (so they resolve from both a source checkout and the
bundled wheel). This is a *structural* quality layer on top of the *referential* checks in
:mod:`claude_kit.validator`: it catches shape/type typos (a missing ``version``, a section that
isn't a map, an org-pack component missing its ``existing`` flag) that referential checks don't.

``jsonschema`` is an **optional** dependency (``pip install claude-kit[schema]``). The deliberate
3-dependency runtime install is preserved: when ``jsonschema`` is absent, every caller degrades to
a no-op via :func:`available`, so schema validation simply doesn't run (it never hard-fails).
"""

from __future__ import annotations

import json
from contextlib import ExitStack
from pathlib import Path
from typing import Any

#: Logical name -> schema filename under the payload ``schemas/`` dir.
SCHEMAS = {
    "stacks": "catalog-stacks.schema.json",
    "profiles": "catalog-profiles.schema.json",
    "mcp": "catalog-mcp.schema.json",
    "capture": "catalog-capture.schema.json",
    "org": "catalog-org.schema.json",
    "org-pack": "org-pack.schema.json",
    "mcp-lock": "mcp-lock.schema.json",
    "pipeline-snapshot": "pipeline-snapshot.schema.json",
}


def available() -> bool:
    """True if the optional ``jsonschema`` package is importable."""
    try:
        import jsonschema  # noqa: F401
    except ModuleNotFoundError:
        return False
    return True


def schema_dir(stack: ExitStack) -> Path:
    """Filesystem path to the bundled ``schemas/`` directory."""
    from claude_kit import scaffold

    return scaffold.payload_dir(stack) / "schemas"


def load_schema(name: str, stack: ExitStack) -> dict[str, Any]:
    """Load and parse a schema by its logical name (see :data:`SCHEMAS`)."""
    path = schema_dir(stack) / SCHEMAS[name]
    return json.loads(path.read_text(encoding="utf-8"))


def validate_doc(doc: Any, name: str, stack: ExitStack) -> list[str]:
    """Validate ``doc`` against schema ``name``; return human-readable errors ([] == valid).

    Raises :class:`ModuleNotFoundError` if ``jsonschema`` is not installed — callers should guard
    with :func:`available` and skip gracefully.
    """
    import jsonschema

    schema = load_schema(name, stack)
    cls = jsonschema.validators.validator_for(schema)
    cls.check_schema(schema)
    validator = cls(schema)
    out: list[str] = []
    for err in sorted(validator.iter_errors(doc), key=lambda e: list(e.path)):
        loc = "/".join(str(p) for p in err.path) or "(root)"
        out.append(f"{loc}: {err.message}")
    return out
