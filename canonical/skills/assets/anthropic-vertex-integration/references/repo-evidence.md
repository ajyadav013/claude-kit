# Repo Evidence

Genericized snippets from production services using Claude on Vertex AI. All internal service names, project IDs, bucket names, and credentials are replaced with placeholders.

## Project-ID resolution fallback chain

**From**: `backend-service-a/llm/vertex_client.py`

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

This pattern appears in **4 production services**. The `BQ_PROJECT_ID` fallback lets data-engineering services reuse their BigQuery config for Vertex AI calls.

## Region resolution

**From**: `worker-service/llm/vertex_client.py`

```python
def _resolve_location(location: Optional[str] = None) -> str:
    """Resolve Vertex AI region from parameter or env var."""
    return (
        location
        or os.environ.get("VERTEX_LOCATION")
        or os.environ.get("GOOGLE_CLOUD_LOCATION")
        or "us-central1"
    ).strip()
```

Default region varies by service:
- `us-central1` — data services
- `us-east5` — knowledge-base services

## AnthropicVertex client factory

**From**: `backend-service-a/llm/vertex_client.py`

```python
from anthropic import AnthropicVertex
from typing import Tuple, Optional

def get_vertex_client(
    project_id: Optional[str] = None,
    location: Optional[str] = None,
) -> Tuple[AnthropicVertex, str, str]:
    """Return an AnthropicVertex client, resolved project, and location."""
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

The 3-tuple return `(client, project, location)` is used for structured logging:

```python
client, project, location = get_vertex_client()
logger.info("Claude client initialized", extra={"project": project, "region": location})
```

## Async generate_text with retry

**From**: `backend-service-a/llm/vertex_client.py`

```python
async def generate_text(
    user_prompt: str,
    personas: Iterable[str],
    task_instruction: str,
    model: str = "claude-sonnet-4-6",
    project_id: Optional[str] = None,
    location: Optional[str] = None,
    max_tokens: int = 16384,
) -> str:
    """Generate text with persona-based system prompt."""
    return await _generate_content(
        user_prompt=user_prompt,
        personas=personas,
        task_instruction=task_instruction,
        model=model,
        project_id=project_id,
        location=location,
        max_tokens=max_tokens,
        want_json=False,
    )
```

## Exponential-backoff retry loop

**From**: `backend-service-a/llm/vertex_client.py`

```python
async def _generate_content(
    user_prompt: str,
    personas: Iterable[str],
    task_instruction: str,
    model: str,
    project_id: Optional[str],
    location: Optional[str],
    max_retries: int = 5,
    max_tokens: int = 16384,
    want_json: bool = False,
) -> str:
    """Generate content with exponential-backoff retry."""
    system_prompt = await build_system_prompt(
        personas=personas, task_instruction=task_instruction
    )

    if want_json:
        system_prompt += (
            "\n\nIMPORTANT: You MUST respond with valid JSON only. "
            "Do not include any text outside the JSON structure."
        )

    error = None
    delay = 1

    for attempt in range(max_retries):
        try:
            client, _, _ = get_vertex_client(project_id=project_id, location=location)
            response = await client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            text = ""
            for block in response.content:
                if block.type == "text":
                    text += block.text
            return text.strip()
        except Exception as e:
            error = e
            if attempt < max_retries - 1:
                print(f"Vertex AI attempt {attempt + 1} failed: {e}. Retrying in {delay}s...")
                await asyncio.sleep(delay)
                delay *= 2
            else:
                print(f"All {max_retries} Vertex AI attempts failed.")

    raise error
```

## System-prompt composition from personas

**From**: `backend-service-a/llm/personas.py`

```python
from pathlib import Path
from typing import Iterable

async def build_system_prompt(
    personas: Iterable[str],
    task_instruction: str,
) -> str:
    """Load persona templates and concatenate with task instruction."""
    persona_dir = Path(__file__).parent / "personas"
    parts = []
    
    for persona_name in personas:
        persona_path = persona_dir / f"{persona_name}.txt"
        if persona_path.exists():
            parts.append(persona_path.read_text(encoding="utf-8"))
    
    parts.append(task_instruction)
    return "\n\n".join(parts)
```

**Example persona** (`personas/data_analyst.txt`):
```
You are an expert data analyst with deep knowledge of retail metrics and customer behavior.
You excel at extracting structured data from unstructured text and identifying patterns.
You always provide responses in the exact format requested.
```

## LazyClient pattern

**From**: `knowledge-base-service/lib/lazyclient.py`

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

**Usage** in `knowledge-base-service/lib/claude.py`:

```python
def _build_client() -> AnthropicVertex:
    """Construct the AnthropicVertex client from settings."""
    settings = get_settings()
    return AnthropicVertex(region=settings.gcp_location, project_id=settings.gcp_project)

_client: LazyClient[AnthropicVertex] = LazyClient(_build_client)

def client() -> AnthropicVertex:
    """Return the lazily-constructed, cached AnthropicVertex client."""
    return _client.get()

def reset_client() -> None:
    """Drop the cached client (for tests)."""
    _client.reset()
```

## Langfuse tracing wrapper

**From**: `knowledge-base-service/lib/langfuse_client.py`

```python
import logging
import time
from contextlib import contextmanager
from typing import Any, Iterator

logger = logging.getLogger(__name__)

_langfuse_client: Any | None = None

def get_langfuse() -> Any | None:
    """Return lazy Langfuse client or None if disabled/missing keys."""
    global _langfuse_client
    
    enabled = os.environ.get("LANGFUSE_ENABLED", "false").lower() == "true"
    if not enabled:
        return None

    public_key = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
    secret_key = os.environ.get("LANGFUSE_SECRET_KEY", "")
    if not public_key or not secret_key:
        logger.warning("LANGFUSE_ENABLED=true but keys missing; tracing disabled")
        return None

    if _langfuse_client is None:
        try:
            from langfuse import Langfuse
            _langfuse_client = Langfuse(
                public_key=public_key,
                secret_key=secret_key,
                host=os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com"),
            )
            logger.info("Langfuse client initialized")
        except Exception:
            logger.exception("Failed to initialize Langfuse")
            return None
    return _langfuse_client


class _CompletionTracer:
    """One-shot tracer for a Claude completion."""

    def __init__(self, name: str, model: str, provider: str, metadata: dict[str, Any] | None):
        self.name = name
        self.model = model
        self.provider = provider
        self.metadata = metadata or {}
        self._start: float | None = None
        self._input: str | None = None
        self._output: str | None = None
        self._error: str | None = None

    def set_input(self, prompt: str) -> None:
        self._input = prompt

    def set_output(self, output: str) -> None:
        self._output = output

    def set_error(self, error: BaseException) -> None:
        self._error = f"{type(error).__name__}: {error}"

    def _flush(self) -> None:
        langfuse = get_langfuse()
        if langfuse is None:
            return
        latency_ms = (time.time() - self._start) * 1000 if self._start else None
        try:
            generation = langfuse.start_observation(
                name=self.name,
                as_type="generation",
                model=self.model,
                input=(self._input or "")[:8000],  # truncate to 8k chars
                metadata={
                    "provider": self.provider,
                    "latency_ms": latency_ms,
                    **self.metadata,
                },
                level="ERROR" if self._error else "DEFAULT",
                output=(self._error or self._output or "")[:8000],
            )
            generation.end()
        except Exception:
            logger.exception("Failed to flush completion trace")


@contextmanager
def trace_completion(
    *,
    name: str,
    model: str,
    provider: str = "anthropic-vertex",
    metadata: dict[str, Any] | None = None,
) -> Iterator[_CompletionTracer]:
    """Context manager for tracing one Claude completion."""
    tracer = _CompletionTracer(name=name, model=model, provider=provider, metadata=metadata)
    tracer._start = time.time()
    try:
        yield tracer
    except BaseException as exc:
        tracer.set_error(exc)
        tracer._flush()
        raise
    else:
        tracer._flush()
```

**Usage** in `knowledge-base-service/lib/claude.py`:

```python
from .langfuse_client import trace_completion

def complete(
    prompt: str,
    *,
    system: str | None = None,
    max_tokens: int = 4096,
    model: str = "claude-sonnet-4-6",
    trace_name: str = "claude_complete",
) -> str:
    """Single-turn completion with tracing."""
    with trace_completion(
        name=trace_name,
        model=model,
        metadata={"max_tokens": max_tokens, "has_system": system is not None},
    ) as tracer:
        tracer.set_input(prompt if system is None else f"[system]\n{system}\n\n[user]\n{prompt}")
        response = client().messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(block.text for block in response.content if hasattr(block, "text"))
        tracer.set_output(text)
        return text
```

## JSON extraction helper

**From**: `knowledge-base-service/lib/claude.py`

```python
import json
import re

_JSON_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)

def extract_json(text: str) -> dict[str, Any]:
    """Strip ```json fences and parse. Falls back to first {...} block."""
    cleaned = _JSON_FENCE.sub("", text).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise
```

## Prompt template loading

**From**: `knowledge-base-service/lib/claude.py`

```python
import string
from pathlib import Path
from typing import Any

def with_template(template_path: Path | str, **kwargs: Any) -> str:
    """Load a prompt template and substitute $name placeholders.
    
    Uses string.Template (safe_substitute) so prompts can contain literal
    JSON braces without escaping.
    """
    template = string.Template(Path(template_path).read_text(encoding="utf-8"))
    return template.safe_substitute(**kwargs)
```

**Example template** (`prompts/extract_entities.txt`):
```
You are extracting structured data from retail location descriptions.

Extract the following from the text:
- Store name
- Address (street, city, state, ZIP)
- Opening hours (if present)

Input text:
$input_text

Return a JSON object with keys: store_name, address, opening_hours.
```

**Usage**:
```python
prompt = with_template(
    "prompts/extract_entities.txt",
    input_text="Joe's Pizza, 123 Main St, New York, NY 10001. Open Mon-Fri 11am-9pm.",
)
response = complete(prompt)
data = extract_json(response)
```

## Settings dataclass with Langfuse config

**From**: `knowledge-base-service/lib/config.py`

```python
import os
from dataclasses import dataclass, field
from pathlib import Path

@dataclass(frozen=True)
class Settings:
    """Frozen runtime config from env vars."""

    # GCP / Vertex AI
    gcp_project: str = field(
        default_factory=lambda: os.environ.get("GOOGLE_CLOUD_PROJECT", "my-project")
    )
    gcp_location: str = field(
        default_factory=lambda: os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
    )

    # Claude models on Vertex AI
    sonnet_model: str = field(
        default_factory=lambda: os.environ.get("CLAUDE_SONNET_MODEL", "claude-sonnet-4-6")
    )
    opus_model: str = field(
        default_factory=lambda: os.environ.get("CLAUDE_OPUS_MODEL", "claude-sonnet-4-6")
    )

    # Langfuse — opt-in
    langfuse_enabled: bool = field(
        default_factory=lambda: os.environ.get("LANGFUSE_ENABLED", "false").lower() == "true"
    )
    langfuse_public_key: str = field(
        default_factory=lambda: os.environ.get("LANGFUSE_PUBLIC_KEY", "")
    )
    langfuse_secret_key: str = field(
        default_factory=lambda: os.environ.get("LANGFUSE_SECRET_KEY", "")
    )
    langfuse_host: str = field(
        default_factory=lambda: os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com")
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

## Vision support

**From**: `web-service/integrations/llm/claude_vertex.py`

```python
async def complete_with_vision(
    prompt: str,
    images: list[dict[str, str]],
    model: str = "claude-sonnet-4-6",
    temperature: float = 0.7,
    max_tokens: int = 4096,
    system: str | None = None,
) -> str:
    """Complete a prompt with image inputs (vision)."""
    client = _get_client()
    
    # Build content with images and text
    content: list[dict[str, Any]] = []
    
    # Add images
    for image in images:
        if "url" in image:
            content.append({
                "type": "image",
                "source": {"type": "url", "url": image["url"]},
            })
        elif "base64" in image:
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": image.get("media_type", "image/jpeg"),
                    "data": image["base64"],
                },
            })
    
    # Add text prompt
    content.append({"type": "text", "text": prompt})
    
    messages = [{"role": "user", "content": content}]
    
    # Run in executor (sync SDK)
    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(
        None,
        lambda: client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=messages,
        ),
    )
    
    return response.content[0].text
```

## Tool-use support

**From**: `web-service/integrations/llm/claude_vertex.py`

```python
async def complete_with_tools(
    messages: list[dict],
    tools: list[dict],
    system: str | None = None,
    model: str = "claude-sonnet-4-6",
    max_tokens: int = 4096,
    temperature: float = 0.7,
) -> Any:
    """Call Claude with tool definitions via Vertex AI.
    
    Returns the full response object including content blocks and stop_reason.
    """
    client = _get_client()
    
    loop = asyncio.get_event_loop()
    
    def call_create():
        kwargs_dict: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages,
            "tools": tools,
        }
        if system:
            kwargs_dict["system"] = system
        return client.messages.create(**kwargs_dict)
    
    response = await loop.run_in_executor(None, call_create)
    
    logger.info(
        "Tool-use response received",
        extra={
            "model": model,
            "stop_reason": response.stop_reason,
            "num_content_blocks": len(response.content),
        },
    )
    
    return response
```

## File paths in production services

These patterns appear across:

1. `backend-service-a/llm/vertex_client.py` — project/region resolution, retry loop
2. `backend-service-a/llm/personas.py` — system-prompt composition
3. `knowledge-base-service/lib/claude.py` — sync wrapper, tracing, JSON extraction
4. `knowledge-base-service/lib/lazyclient.py` — LazyClient pattern
5. `knowledge-base-service/lib/langfuse_client.py` — Langfuse tracer
6. `knowledge-base-service/lib/config.py` — Settings dataclass
7. `web-service/integrations/llm/claude_vertex.py` — vision, tool-use, async executor
8. `worker-service/llm/vertex_client.py` — similar retry loop

All services use:
- `pip install 'anthropic[vertex]'`
- Google Cloud ADC for auth
- Exponential-backoff retry (5 attempts, 1s → 32s delays)
- Settings dataclass for env-var config
- Optional Langfuse tracing (degrades to no-op if disabled)
