---
name: langfuse-llm-tracing
description: Langfuse LLM observability for Python and TypeScript applications with lazy singleton initialization, environment-gated tracing (LANGFUSE_PUBLIC_KEY/SECRET_KEY/HOST), context manager for completion tracing with input/output/error recording, and graceful no-op when disabled. Use when adding LLM call tracing and observability to production services, tracking model performance and latency, debugging LLM failures with structured error capture, or implementing cost and usage analytics across Claude/OpenAI/other provider calls. Distinct from general observability-and-logging (structured logs/metrics/traces); cross-reference that for broader instrumentation patterns.
---

# Langfuse LLM Tracing

Production-grade LLM observability patterns for Python and TypeScript services: lazy Langfuse client initialization, completion tracing with latency and metadata, graceful degradation when disabled, and lifecycle management.

## When to use

- Adding LLM call observability to a new or existing service
- Tracking model performance, latency, and cost across Claude, OpenAI, or other providers
- Debugging LLM failures with structured error capture and input/output logging
- Implementing usage analytics and dashboards for LLM generations
- Tracing multi-step LLM workflows with sessionId and userId correlation
- Monitoring production LLM API calls without impacting service reliability
- Setting up LLM observability in serverless environments (Lambda, Cloud Run) with proper flush/shutdown
- Migrating from logging-only LLM tracking to structured tracing platform
- Cross-referencing with general observability-and-logging for non-LLM telemetry

## Core conventions

### Python: Lazy Singleton Client (get_langfuse)

**Environment-gated initialization**: Check `LANGFUSE_ENABLED` (boolean) and presence of `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` / `LANGFUSE_HOST` before creating the client; return `None` if disabled or keys missing. Log warning if enabled but keys are absent.

**Module-level singleton**: Store client in a global `_langfuse_client` variable; initialize lazily on first `get_langfuse()` call. Wrap `from langfuse import Langfuse` in `try`/`except ImportError` to allow the app to run without the library installed.

**Graceful failure**: If initialization fails (missing env vars, network error, import error), log the exception and return `None`. All downstream code must handle `None` client as a no-op.

**Settings integration**: Read configuration from a central `get_settings()` singleton (Pydantic BaseSettings or similar) rather than direct `os.getenv` calls for testability.

### Python: Completion Tracer Context Manager (trace_completion)

**Context manager pattern**: Use `@contextmanager` yielding a `_CompletionTracer` instance; capture start time on entry, flush on normal exit and on exception.

**Tracer methods**: Provide `set_input(prompt: str)`, `set_output(output: str)`, `set_error(error: BaseException)` to record generation details. Tracer stores name, model, provider, metadata internally.

**Flush on exit**: Call `tracer._flush()` in both `try`/`else` (success) and `except` (error) branches. Re-raise exceptions after flushing so tracing never swallows errors.

**No-op when disabled**: `_flush()` checks `get_langfuse()` and returns early if `None`. No exceptions raised; tracing is always safe to add.

**Generation event structure**: Call `langfuse.start_observation(name=..., as_type="generation", model=..., input=..., metadata={provider, latency_ms, ...}, level="ERROR" or "DEFAULT", output=...)` then `generation.end()`.

**Latency calculation**: Capture `self._start = time.time()` in tracer init, compute `latency_ms = (time.time() - self._start) * 1000` in flush.

**Truncation for large payloads**: Truncate input/output to 8000 chars to avoid payload size limits: `input=(self._input or "")[:8000]`.

**Metadata enrichment**: Include `{"provider": self.provider, "latency_ms": latency_ms, **self.metadata}` in metadata dict; merge user-provided metadata.

**Level-based error marking**: Set `level="ERROR"` if `self._error` is set, otherwise `level="DEFAULT"`.

### Python: Shutdown Hook (shutdown_langfuse)

**Best-effort flush and shutdown**: Call `_langfuse_client.flush()` and `_langfuse_client.shutdown()` in a `try`/`finally` block that sets `_langfuse_client = None` even if shutdown fails.

**Never raise on shutdown**: Wrap in `except Exception` with `logger.warning("Error shutting down Langfuse", exc_info=True)` to prevent shutdown errors from crashing the app.

**Call in app lifespan shutdown**: Invoke `shutdown_langfuse()` in FastAPI `lifespan` context manager's shutdown phase or equivalent app shutdown hook.

### TypeScript: Singleton Service Class (LangfuseService)

**Singleton pattern**: Use static `instance` property and private constructor; expose `getInstance()` static method.

**Environment-gated initialization**: Read `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL` (defaults to `https://cloud.langfuse.com`) from `process.env`; only create client if keys are present.

**Enabled flag**: Store `private enabled: boolean` set to `true` if client init succeeds, `false` otherwise. Provide `isEnabled()` method checked by all tracing methods.

**App version tracking**: Read `version` from `package.json` and `APP_RELEASE` or `GIT_COMMIT_SHA` from env for release metadata. Include in trace metadata.

**Graceful degradation**: Wrap `new Langfuse({...})` in `try`/`catch` logging warnings on failure. All tracing methods check `isEnabled()` and return early if false.

**BaseUrl config**: Only include `baseUrl` in Langfuse config if it differs from the default cloud URL to support self-hosted instances.

### TypeScript: Tracing LLM Calls (traceOpenAICall / traceConversation)

**Generic wrapper pattern**: Accept `operation: string`, LLM params, `executeFn: () => Promise<Response>`, and optional `metadata: {userId?, sessionId?, ...}`.

**Early return when disabled**: Check `isEnabled()` and return `executeFn()` directly if tracing is off; no overhead when disabled.

**Trace creation**: Create trace with `langfuse.trace({name, userId?, sessionId?, version, release, metadata})`. Only include `userId` / `sessionId` if defined and non-empty.

**Generation event**: Create `trace.generation({name, model, modelParameters?, input, metadata?})` with filtered params (remove undefined values to avoid schema errors).

**Timing and token usage**: Capture `startTime = Date.now()`, compute `duration = endTime - startTime`, extract `usage: {promptTokens, completionTokens, totalTokens}` from response, pass to `generation.end({output, usage, metadata})`.

**Error handling**: Wrap `executeFn()` in `try`/`catch`; on error, call `generation.end({level: "ERROR", statusMessage: error.message})` and update trace metadata with `success: false, error: error.message`. Always re-throw.

**Metadata filtering**: Remove undefined keys from `modelParameters` and `metadata` objects before passing to Langfuse to avoid serialization issues.

**Tool call support**: If `response.choices[0].message.tool_calls` is present, include in output as `{tool_calls: toolCalls}` and record `toolCallsCount` in metadata.

**Trace update with status**: Call `trace.update({metadata: {duration, success: true/false, ...}})` after generation completes.

### TypeScript: Flush and Shutdown

**Flush for serverless**: Expose `async flush()` calling `langfuse.flushAsync()` when enabled; invoke before Lambda/Cloud Run handler returns to ensure events are sent.

**Shutdown in process exit**: Expose `async shutdown()` calling `langfuse.shutdownAsync()` for graceful cleanup; hook into `process.on("SIGTERM")` or equivalent.

### Cross-language Patterns

**Provider and model labeling**: Always include `provider` (anthropic-vertex, openai, claude, etc.) and `model` (claude-sonnet-4-6, gpt-4o, etc.) as metadata to enable per-provider/model filtering in Langfuse UI.

**Task metadata**: Add `task` or `operation` label (e.g., "code_review", "summarization", "extraction") to group generations by use case.

**Session and user correlation**: Pass `sessionId` (conversation/request ID) and `userId` (end user or tenant ID) when available to enable multi-turn conversation analysis.

**No-op by default**: Tracing must be opt-in via environment variables; services should run normally without Langfuse configured.

**Input/output truncation**: Limit stored text to avoid payload size errors and cost; 8000 chars is a safe default for most use cases.

## Skeleton / example

```python
# lib/langfuse_client.py (Python pattern)
from __future__ import annotations
import logging
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)

_langfuse_client: Any | None = None

def get_langfuse() -> Any | None:
    """Return the lazily-initialized Langfuse client, or None if disabled."""
    global _langfuse_client
    from config import get_settings
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

def shutdown_langfuse() -> None:
    """Flush and shut down the module-level Langfuse client (best-effort; safe if never initialized)."""
    global _langfuse_client
    if _langfuse_client is not None:
        try:
            _langfuse_client.flush()
            _langfuse_client.shutdown()
        except Exception:
            logger.warning("Error shutting down Langfuse", exc_info=True)
        finally:
            _langfuse_client = None

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
    """Context manager yielding a tracer that records one LLM completion to Langfuse (no-op when disabled)."""
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

# Usage in a service
from anthropic import AnthropicVertex

client = AnthropicVertex(project_id="my-project", region="us-east5")

def generate_summary(text: str) -> str:
    with trace_completion(
        name="generate_summary",
        model="claude-sonnet-4-6",
        provider="anthropic-vertex",
        metadata={"task": "summarization", "input_length": len(text)},
    ) as tracer:
        prompt = f"Summarize:\n\n{text}"
        tracer.set_input(prompt)
        
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        
        output = response.content[0].text
        tracer.set_output(output)
        return output
```

```typescript
// services/langfuse/index.ts (TypeScript pattern)
import { Langfuse } from 'langfuse';
import OpenAI from 'openai';
import { readFileSync } from 'fs';
import { join } from 'path';

export class LangfuseService {
  private static instance: LangfuseService;
  private langfuse: Langfuse | null = null;
  private enabled: boolean = false;
  private appVersion: string;
  private appRelease: string;

  private constructor() {
    try {
      const packageJsonPath = join(process.cwd(), 'package.json');
      const packageJson = JSON.parse(readFileSync(packageJsonPath, 'utf-8'));
      this.appVersion = packageJson.version || '1.0.0';
    } catch {
      this.appVersion = '1.0.0';
    }

    this.appRelease = process.env.APP_RELEASE || process.env.GIT_COMMIT_SHA || this.appVersion;

    const publicKey = process.env.LANGFUSE_PUBLIC_KEY;
    const secretKey = process.env.LANGFUSE_SECRET_KEY;
    const baseUrl = process.env.LANGFUSE_BASE_URL || 'https://cloud.langfuse.com';

    if (publicKey && secretKey) {
      try {
        const config: { publicKey: string; secretKey: string; baseUrl?: string } = {
          publicKey,
          secretKey,
        };
        
        if (baseUrl && baseUrl !== 'https://cloud.langfuse.com') {
          config.baseUrl = baseUrl;
        }
        
        this.langfuse = new Langfuse(config);
        this.enabled = true;
        console.log('✅ Langfuse initialized successfully');
      } catch (error) {
        console.warn('⚠️ Failed to initialize Langfuse:', error);
        this.enabled = false;
      }
    } else {
      console.log('ℹ️ Langfuse not configured (missing keys)');
      this.enabled = false;
    }
  }

  static getInstance(): LangfuseService {
    if (!LangfuseService.instance) {
      LangfuseService.instance = new LangfuseService();
    }
    return LangfuseService.instance;
  }

  isEnabled(): boolean {
    return this.enabled && this.langfuse !== null;
  }

  async traceOpenAICall<T>(
    operation: string,
    params: {
      model: string;
      messages: OpenAI.Chat.Completions.ChatCompletionMessageParam[];
      max_tokens?: number;
      temperature?: number;
      tools?: OpenAI.Chat.Completions.ChatCompletionTool[];
    },
    executeFn: () => Promise<OpenAI.Chat.Completions.ChatCompletion>,
    metadata?: {
      userId?: string;
      sessionId?: string;
      [key: string]: unknown;
    }
  ): Promise<OpenAI.Chat.Completions.ChatCompletion> {
    if (!this.isEnabled()) {
      return executeFn();
    }

    const userId = metadata?.userId;
    const sessionId = metadata?.sessionId;
    const { userId: _, sessionId: __, ...restMetadata } = metadata || {};
    
    const traceMetadata: Record<string, unknown> = {
      operation,
      model: params.model,
      version: this.appVersion,
      release: this.appRelease,
      environment: process.env.NODE_ENV || 'development',
      ...restMetadata,
    };

    Object.keys(traceMetadata).forEach(key => {
      if (traceMetadata[key] === undefined) delete traceMetadata[key];
    });

    const traceConfig: any = {
      name: operation,
      version: this.appVersion,
      release: this.appRelease,
      metadata: traceMetadata,
    };

    if (userId && typeof userId === 'string' && userId.trim() !== '') {
      traceConfig.userId = userId;
    }
    if (sessionId && typeof sessionId === 'string' && sessionId.trim() !== '') {
      traceConfig.sessionId = sessionId;
    }

    const trace = this.langfuse!.trace(traceConfig);

    const modelParameters: Record<string, any> = {};
    if (params.max_tokens !== undefined) modelParameters.max_tokens = params.max_tokens;
    if (params.temperature !== undefined) modelParameters.temperature = params.temperature;

    const generationMetadata: Record<string, unknown> = {};
    if (params.tools) {
      generationMetadata.tools = params.tools.map(t => t.function?.name || 'unknown');
    }

    const generation = trace.generation({
      name: `${operation}_generation`,
      model: params.model,
      modelParameters: Object.keys(modelParameters).length > 0 ? modelParameters : undefined,
      input: params.messages,
      metadata: Object.keys(generationMetadata).length > 0 ? generationMetadata : undefined,
    });

    try {
      const startTime = Date.now();
      const response = await executeFn();
      const endTime = Date.now();

      const output = response.choices[0]?.message?.content || '';
      const toolCalls = response.choices[0]?.message?.tool_calls || [];

      generation.end({
        output: output || (toolCalls.length > 0 ? { tool_calls: toolCalls } : undefined),
        usage: {
          promptTokens: response.usage?.prompt_tokens || 0,
          completionTokens: response.usage?.completion_tokens || 0,
          totalTokens: response.usage?.total_tokens || 0,
        },
        metadata: {
          finishReason: response.choices[0]?.finish_reason,
          model: response.model,
          toolCallsCount: toolCalls.length,
        },
      });

      trace.update({
        metadata: {
          ...metadata,
          duration: endTime - startTime,
          success: true,
        },
      });

      return response;
    } catch (error) {
      generation.end({
        level: 'ERROR',
        statusMessage: error instanceof Error ? error.message : 'Unknown error',
      });

      trace.update({
        metadata: {
          ...metadata,
          success: false,
          error: error instanceof Error ? error.message : 'Unknown error',
        },
      });

      throw error;
    }
  }

  async flush(): Promise<void> {
    if (this.isEnabled()) {
      await this.langfuse!.flushAsync();
    }
  }

  async shutdown(): Promise<void> {
    if (this.isEnabled()) {
      await this.langfuse!.shutdownAsync();
    }
  }
}

export const langfuseService = LangfuseService.getInstance();

// Usage in a service
import { langfuseService } from './services/langfuse';

async function generateCode(prompt: string, userId: string): Promise<string> {
  const client = new OpenAI({apiKey: process.env.OPENAI_API_KEY});
  
  const response = await langfuseService.traceOpenAICall(
    'generate_code',
    {
      model: 'gpt-4o',
      messages: [{role: 'user', content: prompt}],
      max_tokens: 2000,
    },
    () => client.chat.completions.create({
      model: 'gpt-4o',
      messages: [{role: 'user', content: prompt}],
      max_tokens: 2000,
    }),
    {userId, task: 'code_generation'}
  );

  return response.choices[0]?.message?.content || '';
}
```

## Anti-patterns to avoid

- **Raising exceptions on tracing failures** — tracing must never crash the service; wrap all Langfuse calls in try/except with logging.
- **Blocking on flush in request handlers** — use async flush only in shutdown hooks or serverless handler exit; never block user requests.
- **Logging entire LLM responses without truncation** — limit input/output to 8000 chars to avoid payload size errors and storage costs.
- **Using unbounded metadata cardinality** — never include raw user IDs, tenant IDs, or request IDs as top-level metadata; use sessionId/userId fields instead.
- **Forgetting to flush in serverless** — Lambda/Cloud Run terminate immediately after handler returns; must call `langfuseService.flush()` before returning.
- **Not checking isEnabled before tracing** — always gate tracing calls with `if langfuse` (Python) or `isEnabled()` (TypeScript) checks.
- **Hard-coding provider/model strings** — parameterize provider and model names so they match actual usage and enable per-provider filtering.
- **Missing error-path tracing** — ensure `set_error()` / `generation.end({level: "ERROR"})` is called in exception handlers before re-raising.
- **Initializing client per-request** — use singleton pattern to avoid creating multiple Langfuse clients (SDK maintains internal connection pooling).
- **Not re-throwing after error tracing** — tracing context managers must re-raise exceptions after recording them; silently swallowing errors breaks caller expectations.
- **Conflating LLM tracing with general observability** — use Langfuse for LLM-specific telemetry (generations, tokens, prompts) and OpenTelemetry/Prometheus for general service metrics (latency, errors, throughput). Cross-reference observability-and-logging skill for non-LLM instrumentation.

## References

- [langfuse-client-and-tracing.md](references/langfuse-client-and-tracing.md) — Lazy client initialization, completion tracer context manager, shutdown patterns
- [python-and-typescript.md](references/python-and-typescript.md) — Cross-language comparison, singleton patterns, flush/shutdown lifecycle
- [repo-evidence.md](references/repo-evidence.md) — Real file paths and code snippets from source repos
- [observability-and-logging SKILL](../observability-and-logging/SKILL.md) — General observability patterns (structlog, OpenTelemetry, Prometheus, Sentry, health checks)
