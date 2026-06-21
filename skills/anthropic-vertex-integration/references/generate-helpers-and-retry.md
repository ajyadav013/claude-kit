# Generate Helpers and Retry

## Async generate_text wrapper

```python
import asyncio
from typing import Optional

async def generate_text(
    user_prompt: str,
    *,
    system: Optional[str] = None,
    model: str = "claude-sonnet-4-6",
    project_id: Optional[str] = None,
    location: Optional[str] = None,
    max_tokens: int = 4096,
    max_retries: int = 5,
) -> str:
    """Generate text completion with retry."""
    return await _generate_content(
        user_prompt=user_prompt,
        system=system,
        model=model,
        project_id=project_id,
        location=location,
        max_tokens=max_tokens,
        max_retries=max_retries,
        want_json=False,
    )
```

## Exponential-backoff retry loop

```python
async def _generate_content(
    user_prompt: str,
    *,
    system: Optional[str] = None,
    model: str = "claude-sonnet-4-6",
    project_id: Optional[str] = None,
    location: Optional[str] = None,
    max_retries: int = 5,
    max_tokens: int = 4096,
    want_json: bool = False,
) -> str:
    """Generate content with exponential-backoff retry on transient errors."""
    final_system = system or ""
    if want_json:
        final_system += (
            "\n\nIMPORTANT: You MUST respond with valid JSON only. "
            "Do not include any text outside the JSON structure."
        )

    error = None
    delay = 1  # start with 1-second delay

    for attempt in range(max_retries):
        try:
            client, _, _ = get_vertex_client(project_id=project_id, location=location)
            
            # Wrap sync SDK call in executor for async apps
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: client.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    system=final_system if final_system else None,
                    messages=[{"role": "user", "content": user_prompt}],
                ),
            )
            
            # Concatenate text blocks
            text = "".join(
                block.text for block in response.content if hasattr(block, "text")
            )
            return text.strip()
            
        except Exception as e:
            error = e
            if attempt < max_retries - 1:
                print(
                    f"Vertex AI attempt {attempt + 1} failed: {e}. "
                    f"Retrying in {delay} seconds..."
                )
                await asyncio.sleep(delay)
                delay *= 2  # exponential backoff
            else:
                print(f"All {max_retries} Vertex AI attempts failed.")

    # Re-raise the last error after all retries exhausted
    raise error
```

Key points:
- `for attempt in range(max_retries)` — try up to `max_retries` times
- `delay = 1` — start with 1-second delay
- `delay *= 2` — double delay on each retry (1s → 2s → 4s → 8s → 16s)
- `await asyncio.sleep(delay)` — async sleep to avoid blocking event loop
- Print attempt number and delay for debugging
- Re-raise the last exception after all retries exhausted

## JSON extraction

### Simple approach (system prompt only)

```python
async def generate_json_text(
    user_prompt: str,
    *,
    system: Optional[str] = None,
    model: str = "claude-sonnet-4-6",
    project_id: Optional[str] = None,
    location: Optional[str] = None,
    max_tokens: int = 4096,
) -> str:
    """Generate JSON completion (raw text; caller parses)."""
    return await _generate_content(
        user_prompt=user_prompt,
        system=system,
        model=model,
        project_id=project_id,
        location=location,
        max_tokens=max_tokens,
        want_json=True,  # appends JSON instruction to system prompt
    )
```

**Caller parses**:
```python
import json

response = await generate_json_text("Extract entities from: ...")
data = json.loads(response)
```

### Robust approach (with fence stripping)

```python
import json
import re

_JSON_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)

def extract_json(text: str) -> dict:
    """Strip ```json fences and parse. Falls back to first {...} block."""
    cleaned = _JSON_FENCE.sub("", text).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Fallback: extract first {...} block
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise
```

**Usage**:
```python
response = await generate_json_text("Extract entities from: ...")
data = extract_json(response)
```

This handles:
- Plain JSON: `{"key": "value"}`
- Fenced JSON: ` ```json\n{"key": "value"}\n``` `
- JSON embedded in text: `Here's the result: {"key": "value"} Done.`

## System-prompt composition

### Persona-driven pattern

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

**Example personas** (`personas/data_analyst.txt`):
```
You are an expert data analyst with deep knowledge of retail metrics and customer behavior.
You excel at extracting structured data from unstructured text and identifying patterns.
```

**Usage**:
```python
system = await build_system_prompt(
    personas=["data_analyst", "json_expert"],
    task_instruction="Extract store names, addresses, and opening hours from the text.",
)
response = await generate_text(user_prompt="...", system=system)
```

This separates:
- **Personas** — reusable role definitions (data_analyst, json_expert, code_reviewer)
- **Task instruction** — task-specific context

## Vision (image input) support

```python
from typing import Any

async def complete_with_vision(
    prompt: str,
    images: list[dict[str, str]],
    *,
    model: str = "claude-sonnet-4-6",
    system: Optional[str] = None,
    max_tokens: int = 4096,
    project_id: Optional[str] = None,
    location: Optional[str] = None,
) -> str:
    """Complete a prompt with image inputs."""
    client, _, _ = get_vertex_client(project_id=project_id, location=location)
    
    # Build content list with images + text
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
    
    response = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system if system else None,
            messages=messages,
        ),
    )
    
    return response.content[0].text
```

**Usage**:
```python
response = await complete_with_vision(
    prompt="Describe this image.",
    images=[
        {"url": "https://example.com/image.jpg"},
        {"base64": "iVBORw0KGgo...", "media_type": "image/png"},
    ],
)
```

Supported image types:
- `image/jpeg`
- `image/png`
- `image/gif`
- `image/webp`

## Tool-use (function calling) support

```python
async def complete_with_tools(
    messages: list[dict],
    tools: list[dict],
    *,
    system: Optional[str] = None,
    model: str = "claude-sonnet-4-6",
    max_tokens: int = 4096,
    temperature: float = 0.7,
    project_id: Optional[str] = None,
    location: Optional[str] = None,
) -> Any:
    """Call Claude with tool definitions.
    
    Returns the full response object (content blocks + stop_reason) so
    caller can inspect tool_use blocks and drive an agentic loop.
    """
    client, _, _ = get_vertex_client(project_id=project_id, location=location)
    
    response = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system if system else None,
            messages=messages,
            tools=tools,
        ),
    )
    
    return response
```

**Usage** (agentic loop):
```python
tools = [
    {
        "name": "get_weather",
        "description": "Get current weather for a location",
        "input_schema": {
            "type": "object",
            "properties": {
                "location": {"type": "string"},
            },
            "required": ["location"],
        },
    }
]

messages = [{"role": "user", "content": "What's the weather in Tokyo?"}]

while True:
    response = await complete_with_tools(
        messages=messages,
        tools=tools,
        system="You are a helpful assistant.",
    )
    
    if response.stop_reason == "end_turn":
        # Final text response
        print(response.content[0].text)
        break
    
    elif response.stop_reason == "tool_use":
        # Process tool calls
        for block in response.content:
            if block.type == "tool_use":
                tool_name = block.name
                tool_input = block.input
                
                # Execute tool (stubbed here)
                result = execute_tool(tool_name, tool_input)
                
                # Append assistant message + tool result
                messages.append({
                    "role": "assistant",
                    "content": response.content,
                })
                messages.append({
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        }
                    ],
                })
        # Loop to next turn
```

## Streaming responses

```python
async def stream_text(
    user_prompt: str,
    *,
    system: Optional[str] = None,
    model: str = "claude-sonnet-4-6",
    max_tokens: int = 4096,
    project_id: Optional[str] = None,
    location: Optional[str] = None,
):
    """Stream text completion (yields chunks)."""
    client, _, _ = get_vertex_client(project_id=project_id, location=location)
    
    loop = asyncio.get_event_loop()
    
    # Create stream context manager
    def create_stream():
        return client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            system=system if system else None,
            messages=[{"role": "user", "content": user_prompt}],
        )
    
    stream_context = await loop.run_in_executor(None, create_stream)
    
    # Enter context
    stream = await loop.run_in_executor(None, lambda: stream_context.__enter__())
    
    try:
        # Iterate text chunks
        text_stream = await loop.run_in_executor(None, lambda: stream.text_stream)
        
        while True:
            text = await loop.run_in_executor(
                None,
                lambda: next(text_stream, None),
            )
            if text is None:
                break
            yield text
    finally:
        # Exit context
        await loop.run_in_executor(
            None,
            lambda: stream_context.__exit__(None, None, None),
        )
```

**Usage**:
```python
async for chunk in stream_text("Write a poem about mountains."):
    print(chunk, end="", flush=True)
```

## Sync vs async SDK

The `anthropic` SDK (as of 2025-06) is **sync-only**. For async apps:

**Option 1**: Wrap in executor (shown above)
```python
response = await asyncio.get_event_loop().run_in_executor(
    None,
    lambda: client.messages.create(...),
)
```

**Option 2**: Use `asyncio.to_thread` (Python 3.9+)
```python
response = await asyncio.to_thread(client.messages.create, ...)
```

Both patterns offload the sync call to a thread pool, avoiding blocking the event loop.

## Model selection via settings

```python
@dataclass(frozen=True)
class Settings:
    claude_sonnet_model: str = field(
        default_factory=lambda: os.environ.get("CLAUDE_SONNET_MODEL", "claude-sonnet-4-6")
    )
    claude_opus_model: str = field(
        default_factory=lambda: os.environ.get("CLAUDE_OPUS_MODEL", "claude-sonnet-4-6")
    )
```

**Usage**:
```python
settings = get_settings()
response = await generate_text(
    user_prompt="...",
    model=settings.claude_sonnet_model,
)
```

**Available Claude models on Vertex AI** (as of 2025-06):
- `claude-sonnet-4-6` (Claude Sonnet 4)
- `claude-sonnet-4@20250514` (versioned)
- `claude-3-5-sonnet-v2@20241022` (Claude 3.5 Sonnet)
- `claude-3-5-haiku@20241022` (Claude 3.5 Haiku)

Check [Vertex AI model documentation](https://cloud.google.com/vertex-ai/docs/generative-ai/model-reference/claude) for the current list and pricing.
