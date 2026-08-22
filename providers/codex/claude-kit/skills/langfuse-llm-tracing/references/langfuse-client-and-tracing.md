# Langfuse Client and Tracing Patterns

## Lazy Singleton Client (Python)

The `get_langfuse()` function returns a module-level singleton client initialized on first call:

```python
_langfuse_client: Any | None = None

def get_langfuse() -> Any | None:
    """Return the lazily-initialized Langfuse client, or None if disabled."""
    global _langfuse_client
    settings = get_settings()

    if not settings.langfuse_enabled:
        return None

    if not settings.langfuse_public_key or not settings.langfuse_secret_key:
        logger.warning("LANGFUSE_ENABLED=true but keys are not configured; tracing disabled")
        return None

    if _langfuse_client is None:
        try:
            from langfuse import Langfuse
            _langfuse_client = Langfuse(
                public_key=settings.langfuse_public_key,
                secret_key=settings.langfuse_secret_key,
                host=settings.langfuse_host,
            )
            logger.info("Langfuse client initialized (host=%s)", settings.langfuse_host)
        except Exception:
            logger.exception("Failed to initialize Langfuse client")
            return None

    return _langfuse_client
```

**Key patterns:**
- Global `_langfuse_client` variable for singleton storage
- Check `langfuse_enabled` flag before initialization
- Validate presence of keys before creating client
- Lazy import (`from langfuse import Langfuse`) wrapped in try/except
- Return `None` on any failure; caller must handle gracefully
- Log warning if enabled but keys missing (common misconfiguration)

## Completion Tracer Context Manager (Python)

The `trace_completion()` context manager yields a tracer instance that records input/output/error:

```python
class _CompletionTracer:
    """One-shot tracer for an LLM completion. No-op when langfuse is None."""

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
        """Record the prompt sent to the model."""
        self._input = prompt

    def set_output(self, output: str) -> None:
        """Record the model's output text."""
        self._output = output

    def set_error(self, error: BaseException) -> None:
        """Record an exception as the generation's error."""
        self._error = f"{type(error).__name__}: {error}"

    def _flush(self) -> None:
        """Emit the captured generation to Langfuse if enabled."""
        langfuse = get_langfuse()
        if langfuse is None:
            return
        latency_ms = (time.time() - self._start) * 1000 if self._start else None
        try:
            generation = langfuse.start_observation(
                name=self.name,
                as_type="generation",
                model=self.model,
                input=(self._input or "")[:8000],
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
            logger.exception("Failed to flush completion trace to Langfuse")

@contextmanager
def trace_completion(
    *,
    name: str,
    model: str,
    provider: str = "anthropic-vertex",
    metadata: dict[str, Any] | None = None,
) -> Iterator[_CompletionTracer]:
    """Context manager yielding a tracer that records one LLM completion."""
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

**Key patterns:**
- `_CompletionTracer` is a private class that stores generation metadata
- `set_input()`, `set_output()`, `set_error()` methods for caller to populate
- `_flush()` checks `get_langfuse()` and no-ops if disabled
- Latency calculated as `(time.time() - self._start) * 1000`
- Input/output truncated to 8000 chars to avoid payload size limits
- `level="ERROR"` if error is set, otherwise `level="DEFAULT"`
- Context manager captures start time, yields tracer, flushes on both success and error paths
- Always re-raises exceptions after flushing to preserve error handling

## Usage Example (Python)

```python
from lib.langfuse_client import trace_completion
from anthropic import AnthropicVertex

client = AnthropicVertex(project_id="my-project", region="us-east5")

def extract_entities(text: str) -> dict:
    with trace_completion(
        name="entity_extraction",
        model="claude-sonnet-4-6",
        provider="anthropic-vertex",
        metadata={"task": "extraction", "text_length": len(text)},
    ) as tracer:
        prompt = f"Extract entities from:\n\n{text}"
        tracer.set_input(prompt)
        
        try:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1000,
                messages=[{"role": "user", "content": prompt}],
            )
            
            output = response.content[0].text
            tracer.set_output(output)
            return json.loads(output)
        except Exception as e:
            # Error is auto-recorded by context manager's except handler
            raise
```

## Shutdown Hook (Python)

The `shutdown_langfuse()` function flushes and shuts down the client:

```python
def shutdown_langfuse() -> None:
    """Flush and shut down the module-level Langfuse client."""
    global _langfuse_client
    if _langfuse_client is not None:
        try:
            _langfuse_client.flush()
            _langfuse_client.shutdown()
        except Exception:
            logger.warning("Error shutting down Langfuse", exc_info=True)
        finally:
            _langfuse_client = None
```

**Key patterns:**
- Best-effort shutdown; never raises exceptions
- Calls `flush()` before `shutdown()` to send pending events
- Sets `_langfuse_client = None` in finally block to reset state
- Logs warnings on failure but doesn't crash the app

**Integration with FastAPI lifespan:**

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from lib.langfuse_client import shutdown_langfuse

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("App starting")
    yield
    # Shutdown
    shutdown_langfuse()
    logger.info("App shutdown complete")

app = FastAPI(lifespan=lifespan)
```

## Generation Event Structure (Python)

The `start_observation()` call creates a generation event with:

- `name` — operation/task identifier (e.g., "entity_extraction")
- `as_type="generation"` — marks this as an LLM generation event (not a span or event)
- `model` — model identifier (e.g., "claude-sonnet-4-6", "gpt-4o")
- `input` — the prompt sent to the model (truncated to 8000 chars)
- `metadata` — enriched dict with `provider`, `latency_ms`, and any user-provided metadata
- `level` — `"ERROR"` if error occurred, otherwise `"DEFAULT"`
- `output` — the model's response or error message (truncated to 8000 chars)

The generation is immediately ended with `generation.end()` (no streaming support in this pattern).

## Metadata Enrichment Strategy

Always include:
- `provider` — e.g., "anthropic-vertex", "openai", "claude"
- `latency_ms` — calculated from start to end time
- `model` — redundant with generation model field but useful for filtering
- `task` — human-readable operation type (e.g., "summarization", "code_review")

Optionally include:
- `input_length` / `output_length` — character counts for size analysis
- `user_id` / `session_id` — for per-user or per-conversation filtering
- `version` / `release` — for A/B testing or rollback correlation
- `environment` — "production", "staging", "dev"

Never include high-cardinality values as metadata keys (use sessionId/userId fields instead).
