# Repository Evidence (Genericized)

This document contains short, genericized code snippets from real production services. All internal names, project IDs, service accounts, and proprietary details have been removed or replaced with placeholders.

## Python Langfuse Client (Backend Service)

**File:** `lib/langfuse_client.py`

```python
"""Langfuse client + completion tracer.

Lazy singleton; gracefully no-ops when LANGFUSE_ENABLED is false or keys are missing.

Usage:

    with trace_completion(name="text_analysis", model="claude-sonnet-4-6",
                          provider="anthropic-vertex") as tracer:
        text = client.messages.create(...)
        tracer.set_output(text)
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from .config import get_settings

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)

_langfuse_client: Any | None = None


def get_langfuse() -> Any | None:
    """Return the lazily-initialised Langfuse client, or None if disabled."""
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
            logger.info("Langfuse client initialised (host=%s)", settings.langfuse_host)
        except Exception:
            logger.exception("Failed to initialise Langfuse client")
            return None

    return _langfuse_client


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


class _CompletionTracer:
    """One-shot tracer for a Claude completion. No-op when langfuse is None."""

    def __init__(self, name: str, model: str, provider: str, metadata: dict[str, Any] | None):
        """Capture the generation's name/model/provider/metadata."""
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
    """Context manager yielding a tracer that records one LLM completion to Langfuse."""
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

**Configuration (Pydantic Settings):**

```python
# config/settings.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    langfuse_enabled: bool = False
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str = "https://cloud.langfuse.com"

    class Config:
        env_file = ".env"
        case_sensitive = False
```

## TypeScript Langfuse Service (Backend Service)

**File:** `services/langfuse/index.ts`

```typescript
import { Langfuse } from 'langfuse';
import OpenAI from 'openai';
import dotenv from 'dotenv';
import { readFileSync } from 'fs';
import { join } from 'path';

dotenv.config();

/**
 * Langfuse Service
 * Provides observability and tracing for LLM calls
 */
export class LangfuseService {
  private static instance: LangfuseService;
  private langfuse: Langfuse | null = null;
  private enabled: boolean = false;
  private appVersion: string;
  private appRelease: string;

  private constructor() {
    // Load application version and release info
    try {
      const packageJsonPath = join(process.cwd(), 'package.json');
      const packageJson = JSON.parse(readFileSync(packageJsonPath, 'utf-8'));
      this.appVersion = packageJson.version || '1.0.0';
    } catch {
      this.appVersion = '1.0.0';
    }

    this.appRelease = process.env.APP_RELEASE || process.env.GIT_COMMIT_SHA || this.appVersion;

    // Initialize Langfuse only if credentials are provided
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
      console.log('ℹ️ Langfuse not configured');
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
      reasoning_effort?: 'low' | 'medium' | 'high';
      max_tokens?: number;
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
    if (params.reasoning_effort !== undefined) {
      modelParameters.reasoning_effort = params.reasoning_effort;
    }
    if (params.max_tokens !== undefined) {
      modelParameters.max_tokens = params.max_tokens;
    }

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
```

## Usage Example (Python Service)

**File:** `services/analysis_service.py`

```python
from lib.langfuse_client import trace_completion
from anthropic import AnthropicVertex

class AnalysisService:
    def __init__(self):
        self.client = AnthropicVertex(
            project_id=settings.vertex_project_id,
            region=settings.vertex_region,
        )

    def analyze_text(self, text: str, task_type: str) -> dict:
        with trace_completion(
            name=f"text_analysis_{task_type}",
            model="claude-sonnet-4-6",
            provider="anthropic-vertex",
            metadata={"task": task_type, "input_length": len(text)},
        ) as tracer:
            prompt = f"Analyze the following text for {task_type}:\n\n{text}"
            tracer.set_input(prompt)
            
            response = self.client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}],
            )
            
            output = response.content[0].text
            tracer.set_output(output)
            
            return {"analysis": output, "model": "claude-sonnet-4-6"}
```

## Usage Example (TypeScript Service)

**File:** `services/generation_service.ts`

```typescript
import { langfuseService } from './langfuse';
import OpenAI from 'openai';

export class GenerationService {
  private client: OpenAI;

  constructor() {
    this.client = new OpenAI({
      apiKey: process.env.OPENAI_API_KEY,
    });
  }

  async generateContent(
    prompt: string,
    userId: string,
    sessionId: string
  ): Promise<string> {
    const response = await langfuseService.traceOpenAICall(
      'content_generation',
      {
        model: 'gpt-4o',
        messages: [{ role: 'user', content: prompt }],
        max_tokens: 1500,
      },
      () =>
        this.client.chat.completions.create({
          model: 'gpt-4o',
          messages: [{ role: 'user', content: prompt }],
          max_tokens: 1500,
        }),
      { userId, sessionId, task: 'content_generation' }
    );

    return response.choices[0]?.message?.content || '';
  }
}
```

## Environment Variables

**Python (.env):**
```bash
LANGFUSE_ENABLED=true
LANGFUSE_PUBLIC_KEY=pk-lf-<key>
LANGFUSE_SECRET_KEY=sk-lf-<secret>
LANGFUSE_HOST=https://cloud.langfuse.com
```

**TypeScript (.env):**
```bash
LANGFUSE_PUBLIC_KEY=pk-lf-<key>
LANGFUSE_SECRET_KEY=sk-lf-<secret>
LANGFUSE_BASE_URL=https://cloud.langfuse.com
APP_RELEASE=v1.2.3
NODE_ENV=production
```

## FastAPI Integration (Python)

**File:** `app/lifetime.py`

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from lib.langfuse_client import shutdown_langfuse

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Application starting")
    yield
    # Shutdown
    shutdown_langfuse()
    logger.info("Application shutdown complete")

app = FastAPI(lifespan=lifespan)
```

## Serverless Integration (TypeScript)

**File:** `handlers/processor.ts`

```typescript
import { langfuseService } from '../services/langfuse';

export const handler = async (event: any) => {
  try {
    const result = await processEvent(event);
    
    // Flush before Lambda terminates
    await langfuseService.flush();
    
    return {
      statusCode: 200,
      body: JSON.stringify(result),
    };
  } catch (error) {
    // Flush on error too
    await langfuseService.flush();
    
    return {
      statusCode: 500,
      body: JSON.stringify({ error: 'Processing failed' }),
    };
  }
};
```

## Key Patterns Observed

1. **Lazy initialization** — client created on first use, not at module import
2. **Environment-gated** — checks for enable flag and keys before initializing
3. **Graceful degradation** — returns None/disabled state on any failure
4. **Context manager (Python)** — automatic flush on exit, both success and error paths
5. **Wrapper pattern (TypeScript)** — wraps existing async functions with tracing
6. **Metadata enrichment** — always includes provider, model, latency, task type
7. **Token usage tracking (TypeScript)** — extracts promptTokens/completionTokens from response
8. **Tool call support** — handles both text and tool_calls outputs
9. **Truncation** — 8000 char limit on input/output to avoid payload errors
10. **Lifecycle management** — explicit flush/shutdown in app shutdown hooks and serverless handlers
