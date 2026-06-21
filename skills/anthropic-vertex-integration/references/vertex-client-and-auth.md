# Vertex Client and Auth

## AnthropicVertex SDK installation

Install the Anthropic SDK with the Vertex AI extra:

```bash
pip install 'anthropic[vertex]'
```

The `[vertex]` extra includes Google Cloud dependencies for Application Default Credentials (ADC) authentication.

## Application Default Credentials (ADC)

The `AnthropicVertex` client uses Google Cloud ADC for authentication. No API keys are required.

**Local development**:
```bash
gcloud auth application-default login
```

**Production**: set `GOOGLE_APPLICATION_CREDENTIALS` to point to a service-account JSON key, or rely on GCE/Cloud Run/GKE metadata service.

## Project-ID resolution fallback chain

Services often have a BigQuery project ID (`BQ_PROJECT_ID`) but not a dedicated Vertex AI project ID. The fallback chain reuses existing config:

```python
def _resolve_project_id(project_id: Optional[str] = None) -> str:
    """Resolve Vertex AI project ID from parameter or env-var fallback chain."""
    resolved = (
        project_id
        or os.environ.get("VERTEX_PROJECT_ID")
        or os.environ.get("BQ_PROJECT_ID")
        or os.environ.get("GOOGLE_CLOUD_PROJECT")
        or os.environ.get("GCLOUD_PROJECT")
        or ""
    ).strip()
    if not resolved:
        raise ValueError(
            "Vertex AI project ID not found. Set VERTEX_PROJECT_ID, BQ_PROJECT_ID, "
            "GOOGLE_CLOUD_PROJECT, or pass project_id."
        )
    return resolved
```

This pattern:
- Checks explicit parameter first
- Falls back to `VERTEX_PROJECT_ID` (most specific)
- Falls back to `BQ_PROJECT_ID` (common in data services)
- Falls back to `GOOGLE_CLOUD_PROJECT` (standard GCP env var)
- Falls back to `GCLOUD_PROJECT` (legacy gcloud CLI env var)
- Raises `ValueError` with clear message if all are empty

## Region/location resolution

```python
def _resolve_location(location: Optional[str] = None) -> str:
    """Resolve Vertex AI region from parameter or env var."""
    return (
        location
        or os.environ.get("VERTEX_LOCATION")
        or os.environ.get("GOOGLE_CLOUD_LOCATION")
        or "us-central1"  # default
    ).strip()
```

Claude on Vertex AI is available in specific regions. As of 2025-06, supported regions include:
- `us-central1`
- `us-east5`
- `europe-west1`
- `asia-northeast1`

Check [Vertex AI Claude documentation](https://cloud.google.com/vertex-ai/docs/generative-ai/model-reference/claude) for the current list.

## Lazy client factory

```python
from anthropic import AnthropicVertex
from typing import Tuple, Optional

def get_vertex_client(
    project_id: Optional[str] = None,
    location: Optional[str] = None,
) -> Tuple[AnthropicVertex, str, str]:
    """Return an AnthropicVertex client, resolved project, and location.
    
    Raises ImportError with install hint if anthropic[vertex] not installed.
    """
    try:
        from anthropic import AnthropicVertex
    except ImportError as exc:
        raise ImportError(
            "anthropic[vertex] is required. Install with: pip install 'anthropic[vertex]'"
        ) from exc

    resolved_project = _resolve_project_id(project_id)
    resolved_location = _resolve_location(location)
    client = AnthropicVertex(
        project_id=resolved_project,
        region=resolved_location,
    )
    return client, resolved_project, resolved_location
```

This factory:
- Lazy-imports `AnthropicVertex` to defer credential checks
- Returns a 3-tuple: `(client, project, location)` for logging
- Raises helpful error if the `[vertex]` extra isn't installed

## LazyClient caching pattern

For services that call Claude frequently, cache the client to avoid repeated ADC checks:

```python
from collections.abc import Callable
from typing import Generic, TypeVar

T = TypeVar("T")

class LazyClient(Generic[T]):
    """Defer construction of T until first get(), then cache it."""

    def __init__(self, build: Callable[[], T]) -> None:
        self._build = build
        self._instance: T | None = None

    def get(self) -> T:
        if self._instance is None:
            self._instance = self._build()
        return self._instance

    def reset(self) -> None:
        """Drop cache (for tests that change env vars mid-run)."""
        self._instance = None
```

**Usage**:

```python
def _build_client() -> AnthropicVertex:
    """Construct the AnthropicVertex client from settings."""
    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "my-project")
    region = os.environ.get("VERTEX_LOCATION", "us-central1")
    return AnthropicVertex(project_id=project, region=region)

_client = LazyClient(_build_client)

def client() -> AnthropicVertex:
    """Return the lazily-constructed, cached client."""
    return _client.get()

def reset_client() -> None:
    """Drop the cached client (for tests)."""
    _client.reset()
```

This pattern:
- Defers client construction until first use (no startup cost)
- Caches the client across calls (avoids repeated ADC checks)
- Exposes `.reset()` for tests that monkeypatch env vars

## Settings dataclass pattern

Centralize all Vertex AI config in a frozen settings dataclass:

```python
import os
from dataclasses import dataclass, field

@dataclass(frozen=True)
class Settings:
    """Vertex AI config from env vars."""

    gcp_project: str = field(
        default_factory=lambda: os.environ.get("GOOGLE_CLOUD_PROJECT", "my-project")
    )
    gcp_location: str = field(
        default_factory=lambda: os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
    )
    claude_sonnet_model: str = field(
        default_factory=lambda: os.environ.get("CLAUDE_SONNET_MODEL", "claude-sonnet-4-6")
    )

_settings: Settings | None = None

def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings

def reset_settings() -> None:
    global _settings
    _settings = None
```

Use `get_settings().gcp_project` in `_build_client()`. Tests can `reset_settings()` after monkeypatching env vars.

## Contrast with direct Anthropic API

**Direct Anthropic SDK** (API key):
```python
from anthropic import Anthropic

client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=1024,
    messages=[{"role": "user", "content": "Hello"}],
)
```

**AnthropicVertex SDK** (ADC):
```python
from anthropic import AnthropicVertex

client = AnthropicVertex(
    project_id="my-gcp-project",
    region="us-central1",
)
response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=1024,
    messages=[{"role": "user", "content": "Hello"}],
)
```

Key differences:
- `AnthropicVertex` uses GCP ADC (no API key in env/secrets)
- `AnthropicVertex` requires `project_id` and `region` parameters
- Model IDs are the same across both SDKs
- Messages API is identical (same params, same response shape)

Choose `AnthropicVertex` when:
- Running on GCP (Cloud Run, GKE, GCE, Cloud Functions)
- Want to avoid managing Anthropic API keys
- Need unified GCP IAM for both Vertex AI and other GCP services

Choose direct `Anthropic` when:
- Running outside GCP (AWS, Azure, on-prem)
- Using Anthropic API features not yet available on Vertex (e.g., prompt caching, extended context)
