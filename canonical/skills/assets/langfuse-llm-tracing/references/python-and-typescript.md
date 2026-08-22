# Python and TypeScript Langfuse Patterns

## Cross-Language Comparison

### Singleton Initialization

**Python (module-level global):**
```python
_langfuse_client: Any | None = None

def get_langfuse() -> Any | None:
    global _langfuse_client
    if _langfuse_client is None:
        # initialize
    return _langfuse_client
```

**TypeScript (static class instance):**
```typescript
export class LangfuseService {
  private static instance: LangfuseService;
  private langfuse: Langfuse | null = null;

  private constructor() {
    // initialize
  }

  static getInstance(): LangfuseService {
    if (!LangfuseService.instance) {
      LangfuseService.instance = new LangfuseService();
    }
    return LangfuseService.instance;
  }
}
```

**Key differences:**
- Python uses module-level global variable; TypeScript uses static class property
- Python function-based; TypeScript class-based with private constructor
- Both achieve same goal: one client instance per process

### Environment-Gated Initialization

**Python:**
```python
settings = get_settings()
if not settings.langfuse_enabled:
    return None
if not settings.langfuse_public_key or not settings.langfuse_secret_key:
    logger.warning("LANGFUSE_ENABLED=true but keys are not configured")
    return None
```

**TypeScript:**
```typescript
const publicKey = process.env.LANGFUSE_PUBLIC_KEY;
const secretKey = process.env.LANGFUSE_SECRET_KEY;

if (publicKey && secretKey) {
  try {
    this.langfuse = new Langfuse({publicKey, secretKey});
    this.enabled = true;
  } catch (error) {
    console.warn('⚠️ Failed to initialize Langfuse:', error);
    this.enabled = false;
  }
} else {
  console.log('ℹ️ Langfuse not configured');
  this.enabled = false;
}
```

**Key differences:**
- Python uses centralized settings object (Pydantic BaseSettings pattern)
- TypeScript reads `process.env` directly
- Python has explicit enable flag; TypeScript infers from key presence
- Both log warnings on misconfiguration

### Error Handling and Graceful Degradation

**Python (return None):**
```python
try:
    from langfuse import Langfuse
    _langfuse_client = Langfuse(...)
except Exception:
    logger.exception("Failed to initialize Langfuse client")
    return None
```

**TypeScript (enabled flag):**
```typescript
try {
  this.langfuse = new Langfuse(config);
  this.enabled = true;
} catch (error) {
  console.warn('Failed to initialize Langfuse:', error);
  this.enabled = false;
}
```

**Consistency:**
- Both catch broad exception types (not just specific errors)
- Both log warnings/errors but don't crash
- Python returns `None`; TypeScript sets `enabled = false`
- Callers check `if langfuse` (Python) or `isEnabled()` (TypeScript)

## TypeScript Singleton Service Pattern

Full implementation:

```typescript
import { Langfuse } from 'langfuse';
import { readFileSync } from 'fs';
import { join } from 'path';

export class LangfuseService {
  private static instance: LangfuseService;
  private langfuse: Langfuse | null = null;
  private enabled: boolean = false;
  private appVersion: string;
  private appRelease: string;

  private constructor() {
    // Load app version from package.json
    try {
      const packageJsonPath = join(process.cwd(), 'package.json');
      const packageJson = JSON.parse(readFileSync(packageJsonPath, 'utf-8'));
      this.appVersion = packageJson.version || '1.0.0';
    } catch {
      this.appVersion = '1.0.0';
    }

    // Get release info from environment or use version
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
        
        // Only add baseUrl if it's not the default
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
}

export const langfuseService = LangfuseService.getInstance();
```

**Key patterns:**
- Private constructor prevents external instantiation
- Version loaded from `package.json` on init
- Release info from env vars (`APP_RELEASE`, `GIT_COMMIT_SHA`)
- `baseUrl` only included if non-default (self-hosted instance support)
- Module exports singleton instance as `langfuseService`

## TypeScript Trace Wrapper Pattern

```typescript
async traceOpenAICall<T>(
  operation: string,
  params: {
    model: string;
    messages: OpenAI.Chat.Completions.ChatCompletionMessageParam[];
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

  // Extract userId/sessionId from metadata
  const userId = metadata?.userId;
  const sessionId = metadata?.sessionId;
  const { userId: _, sessionId: __, ...restMetadata } = metadata || {};
  
  // Build trace metadata
  const traceMetadata: Record<string, unknown> = {
    operation,
    model: params.model,
    version: this.appVersion,
    release: this.appRelease,
    environment: process.env.NODE_ENV || 'development',
    ...restMetadata,
  };

  // Remove undefined values
  Object.keys(traceMetadata).forEach(key => {
    if (traceMetadata[key] === undefined) delete traceMetadata[key];
  });

  // Create trace config with optional userId/sessionId
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

  // Filter model parameters
  const modelParameters: Record<string, any> = {};
  if (params.max_tokens !== undefined) modelParameters.max_tokens = params.max_tokens;

  // Build generation metadata
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
```

**Key patterns:**
- Early return `executeFn()` if tracing disabled
- Destructure `userId` and `sessionId` from metadata, then spread `restMetadata`
- Filter undefined values from all objects before passing to Langfuse
- Only include `userId`/`sessionId` in trace config if non-empty strings
- Build `modelParameters` and `generationMetadata` dynamically
- Capture timing with `Date.now()` before/after `executeFn()`
- Extract token usage from response
- Handle tool calls in output
- Always re-throw errors after recording

## Flush and Shutdown Lifecycle

**Python:**
```python
def shutdown_langfuse() -> None:
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

**TypeScript:**
```typescript
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
```

**Usage in serverless (TypeScript):**
```typescript
export const handler = async (event: any) => {
  try {
    const result = await processEvent(event);
    await langfuseService.flush(); // Send pending events before Lambda terminates
    return result;
  } catch (error) {
    await langfuseService.flush(); // Flush on error too
    throw error;
  }
};
```

**Usage in process exit (TypeScript):**
```typescript
process.on('SIGTERM', async () => {
  console.log('SIGTERM received, shutting down gracefully');
  await langfuseService.shutdown();
  process.exit(0);
});
```

**Key differences:**
- Python uses sync `flush()`/`shutdown()`; TypeScript uses async `flushAsync()`/`shutdownAsync()`
- Python wraps in try/except with logging; TypeScript delegates error handling to caller
- Python resets `_langfuse_client = None`; TypeScript leaves instance intact
- Serverless: must call `flush()` before Lambda/Cloud Run handler returns
- Long-running: call `shutdown()` in SIGTERM handler
