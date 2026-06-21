---
name: anthropic-vertex-integration
description: Encodes production patterns for calling Claude on Vertex AI via the AnthropicVertex SDK, including lazy client initialization with Application Default Credentials, project-ID and region resolution from env-var fallback chains, async generate helpers with exponential-backoff retry, system-prompt composition, JSON extraction, and optional Langfuse tracing. Use when integrating Claude via Vertex AI (not the direct Anthropic API), building async LLM helpers for one-shot completions or JSON extraction, or adding observability via Langfuse to Claude calls.
---

Integrate Claude on Vertex AI using the AnthropicVertex SDK with lazy authentication, resilient helpers, and optional tracing.

## When to use

- Calling Claude via Google Cloud Vertex AI (not the direct Anthropic API with API keys)
- Building async helpers for one-shot completions, JSON extraction, or tool-use calls
- Implementing exponential-backoff retry for transient Vertex AI errors
- Composing system prompts from personas or task instructions
- Adding Langfuse observability to Claude completions (latency, input/output, errors)
- Migrating from direct Anthropic SDK (API-key auth) to Vertex AI (ADC auth)
- Setting up lazy client initialization with env-var-based project/region resolution
- Creating a reusable LazyClient pattern for SDK singletons with test reset hooks

## Core conventions

1. **AnthropicVertex SDK installation**: install with `pip install 'anthropic[vertex]'` (the `[vertex]` extra is required). The SDK uses Google Cloud Application Default Credentials (ADC) — run `gcloud auth application-default login` locally or rely on service-account credentials in production (GOOGLE_APPLICATION_CREDENTIALS env var).

2. **Project-ID resolution fallback chain**: `_resolve_project_id(project_id)` checks `project_id` parameter → `VERTEX_PROJECT_ID` → `BQ_PROJECT_ID` → `GOOGLE_CLOUD_PROJECT` → `GCLOUD_PROJECT` env vars in order, raising `ValueError` if all are empty. This lets BigQuery-focused services reuse `BQ_PROJECT_ID` for Vertex calls without duplicating config.

3. **Region/location resolution**: `_resolve_location(location)` checks `location` parameter → `VERTEX_LOCATION` or `GOOGLE_CLOUD_LOCATION` env vars → a default (e.g., `us-central1`, `us-east5`). Claude on Vertex AI is available in specific regions; check Vertex AI docs for current list.

4. **Lazy client factory**: `get_vertex_client(project_id, location) -> (client, resolved_project, resolved_location)` imports `AnthropicVertex` lazily (raising `ImportError` with install hint if missing), resolves project/location, and returns `(AnthropicVertex(project_id=..., region=...), project, location)`. Construct on each call for simplicity, or wrap in a `LazyClient[AnthropicVertex]` singleton (see references) for caching and test-reset support.

5. **Async messages.create wrapper**: `async def generate_text(user_prompt, *, system=None, model="claude-sonnet-4-6", max_tokens=4096, max_retries=5)` calls `client.messages.create(model=model, max_tokens=max_tokens, system=system, messages=[{"role": "user", "content": user_prompt}])`, concatenates `response.content` text blocks, and returns `str`. Wrap the call in a retry loop with exponential backoff (see #6).

6. **Exponential-backoff retry**: wrap `client.messages.create()` in a `for attempt in range(max_retries)` loop. On exception, sleep `delay` seconds (starting at 1), double `delay`, and retry. On the last attempt, re-raise the error. Log each retry attempt with attempt number and delay.

7. **JSON extraction helper**: `async def generate_json_text(...)` appends `\n\nIMPORTANT: You MUST respond with valid JSON only. Do not include any text outside the JSON structure.` to the system prompt and passes `response_mime_type="application/json"` as metadata (not a native Anthropic param; used for tracing only). Returns raw text; caller parses JSON. Optionally define `extract_json(text)` to strip `\`\`\`json` fences via regex and `json.loads()`, falling back to the first `{...}` match if the full string fails.

8. **System-prompt composition**: define `build_system_prompt(personas: Iterable[str], task_instruction: str) -> str` to load persona templates from a `personas/` directory and concatenate them with the task instruction. This separates role definition from task-specific context. Personas are reusable across tasks.

9. **LazyClient pattern for caching**: define a generic `LazyClient[T]` that takes a `Callable[[], T]` factory, builds `T` on first `.get()`, caches it, and exposes `.reset()` for tests. Use as `_client = LazyClient(_build_client); client() -> AnthropicVertex: return _client.get()`. This defers GCP credential checks until first use and lets tests reset the client after env-var changes.

10. **Langfuse tracing wrapper**: define `trace_completion(name, model, provider="anthropic-vertex", metadata=None)` as a context manager that yields a `_CompletionTracer` with `set_input(prompt)`, `set_output(text)`, `set_error(exc)` methods. On context exit, flush to Langfuse if enabled (lazy singleton `get_langfuse()`). Degrades to no-op if `LANGFUSE_ENABLED=false` or keys are missing. Env vars: `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`. Install with `pip install langfuse`.

11. **Model selection via env vars**: define a settings singleton with `CLAUDE_SONNET_MODEL` (default `claude-sonnet-4-6`), `CLAUDE_OPUS_MODEL`, etc. Use `model = model or settings.sonnet_model` in helpers. Current Vertex AI Claude models: `claude-sonnet-4-6`, `claude-sonnet-4@20250514`, `claude-3-5-sonnet-v2@20241022`, `claude-3-5-haiku@20241022`.

12. **Vision (image input) support**: `complete_with_vision(prompt, images, ...)` builds a `content` list with image blocks (either `{"type": "image", "source": {"type": "url", "url": ...}}` or `{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": ...}}`) followed by a text block. Supported MIME types: `image/jpeg`, `image/png`, `image/gif`, `image/webp`. Pass to `messages=[{"role": "user", "content": content}]`.

13. **Tool-use (function calling) support**: `complete_with_tools(messages, tools, ...)` passes a multi-turn conversation history (`messages: list[dict]`) and `tools: list[dict]` (Anthropic tool-definition format) to `client.messages.create()`. Returns the full `Message` response object so caller can inspect `response.stop_reason` and iterate `response.content` for `tool_use` blocks, execute tools, and append `tool_result` messages for the next turn.

14. **Sync vs async SDK**: the `anthropic` SDK is **sync-only** (as of 2025-06). If your app is async, wrap `client.messages.create()` in `asyncio.get_event_loop().run_in_executor(None, call_create)` to avoid blocking the event loop. The examples above use `async def` with native `await client.messages.create()`—this assumes a hypothetical async SDK; adjust to executor pattern if using the current sync SDK.

15. **Streaming responses**: `client.messages.stream()` returns a context manager yielding text chunks. Wrap in executor and yield chunks via an async generator. Not shown in examples; see Anthropic SDK docs for stream API.

## Skeleton / example

```python
# llm/vertex_claude.py
import asyncio
import os
from typing import Iterable, Optional, Tuple

from anthropic import AnthropicVertex

DEFAULT_VERTEX_MODEL = "claude-sonnet-4-6"
DEFAULT_VERTEX_LOCATION = "us-central1"


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


def _resolve_location(location: Optional[str] = None) -> str:
    """Resolve Vertex AI region from parameter or env var."""
    return (
        location
        or os.environ.get("VERTEX_LOCATION")
        or os.environ.get("GOOGLE_CLOUD_LOCATION")
        or DEFAULT_VERTEX_LOCATION
    ).strip()


def get_vertex_client(
    project_id: Optional[str] = None,
    location: Optional[str] = None,
) -> Tuple[AnthropicVertex, str, str]:
    """Return an AnthropicVertex client, resolved project, and location.
    
    Uses Google Cloud Application Default Credentials for auth.
    Run `gcloud auth application-default login` locally.
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


async def _generate_content(
    user_prompt: str,
    *,
    system: Optional[str] = None,
    model: str = DEFAULT_VERTEX_MODEL,
    project_id: Optional[str] = None,
    location: Optional[str] = None,
    max_retries: int = 5,
    max_tokens: int = 4096,
    want_json: bool = False,
) -> str:
    """Generate text with exponential-backoff retry."""
    final_system = system or ""
    if want_json:
        final_system += (
            "\n\nIMPORTANT: You MUST respond with valid JSON only. "
            "Do not include any text outside the JSON structure."
        )

    error = None
    delay = 1

    for attempt in range(max_retries):
        try:
            client, _, _ = get_vertex_client(project_id=project_id, location=location)
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: client.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    system=final_system or None,
                    messages=[{"role": "user", "content": user_prompt}],
                ),
            )
            text = "".join(block.text for block in response.content if hasattr(block, "text"))
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


async def generate_text(
    user_prompt: str,
    *,
    system: Optional[str] = None,
    model: str = DEFAULT_VERTEX_MODEL,
    project_id: Optional[str] = None,
    location: Optional[str] = None,
    max_tokens: int = 4096,
) -> str:
    """Generate text completion."""
    return await _generate_content(
        user_prompt=user_prompt,
        system=system,
        model=model,
        project_id=project_id,
        location=location,
        max_tokens=max_tokens,
        want_json=False,
    )


async def generate_json_text(
    user_prompt: str,
    *,
    system: Optional[str] = None,
    model: str = DEFAULT_VERTEX_MODEL,
    project_id: Optional[str] = None,
    location: Optional[str] = None,
    max_tokens: int = 4096,
) -> str:
    """Generate JSON completion (appends JSON instruction to system prompt)."""
    return await _generate_content(
        user_prompt=user_prompt,
        system=system,
        model=model,
        project_id=project_id,
        location=location,
        max_tokens=max_tokens,
        want_json=True,
    )
```

```python
# llm/lazyclient.py
from collections.abc import Callable
from typing import Generic, TypeVar

T = TypeVar("T")


class LazyClient(Generic[T]):
    """Defer construction of T until first get(), then cache it.
    
    Usage:
        def _build() -> MyClient: return MyClient()
        _client = LazyClient(_build)
        client = _client.get()  # builds on first call, cached thereafter
        _client.reset()  # drop cache (for tests)
    """

    def __init__(self, build: Callable[[], T]) -> None:
        self._build = build
        self._instance: T | None = None

    def get(self) -> T:
        if self._instance is None:
            self._instance = self._build()
        return self._instance

    def reset(self) -> None:
        self._instance = None
```

```python
# llm/langfuse_tracer.py (optional)
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
            logger.exception("Failed to flush completion trace")


@contextmanager
def trace_completion(
    *,
    name: str,
    model: str,
    provider: str = "anthropic-vertex",
    metadata: dict[str, Any] | None = None,
) -> Iterator[_CompletionTracer]:
    """Context manager for tracing one Claude completion to Langfuse.
    
    Usage:
        with trace_completion(name="extract", model="claude-sonnet-4-6") as tracer:
            tracer.set_input(prompt)
            response = await generate_text(prompt)
            tracer.set_output(response)
    """
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

## Anti-patterns to avoid

1. **Using direct Anthropic SDK with API keys in Vertex AI context**: if running on GCP, prefer `AnthropicVertex` with ADC over `Anthropic(api_key=...)` to avoid managing API keys.
2. **Hardcoding project ID / region**: use env-var fallback chains and default to common env vars (`GOOGLE_CLOUD_PROJECT`, `VERTEX_PROJECT_ID`) so config is reusable across services.
3. **No retry on transient errors**: Vertex AI can return 503/504 on overload; always wrap in exponential-backoff retry.
4. **Blocking the event loop with sync SDK calls**: if your app is async, use `run_in_executor` to call sync `client.messages.create()` without blocking.
5. **Not trimming input/output for tracing**: Langfuse (and most observability backends) have size limits; truncate to 8000 chars or use ellipsis to avoid trace rejection.
6. **Raising on missing Langfuse keys**: gracefully degrade to no-op if tracing is misconfigured; never block the app on telemetry failure.
7. **Rebuilding client on every call without caching**: constructing `AnthropicVertex` is cheap but imports and ADC checks add overhead; cache via `LazyClient` or module-level singleton.
8. **Not logging retry attempts**: silent retries make debugging timeout issues hard; log attempt number, error, and delay on each retry.
9. **Using `response_mime_type` as a native Anthropic param**: Anthropic SDK doesn't support `response_mime_type` (unlike Gemini); use system-prompt instructions for JSON output instead.
10. **Not validating ADC setup in dev**: run `gcloud auth application-default login` once; missing ADC causes cryptic permission errors on first call.

## References

- [vertex-client-and-auth.md](references/vertex-client-and-auth.md) — AnthropicVertex client construction, ADC, project/region resolution, LazyClient caching
- [generate-helpers-and-retry.md](references/generate-helpers-and-retry.md) — async generate_text / generate_json_text, exponential-backoff retry, system-prompt composition, vision and tool-use patterns
- [repo-evidence.md](references/repo-evidence.md) — source file paths and genericized snippets
- **Cross-references**: for Langfuse integration across multiple LLM providers, see the `langfuse-llm-tracing` skill (not included here; assumes separate skill exists)
