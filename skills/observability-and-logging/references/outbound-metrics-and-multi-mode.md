# Outbound HTTP Metrics and Multi-Mode Service Instrumentation

Additional observability patterns for outbound HTTP calls and non-FastAPI service modes (consumers, workers, cron, Temporal).

## Outbound HTTP Metrics (production service pattern)

Track metrics for HTTP requests sent FROM your service TO external APIs/services.

### HTTP_REQUEST_SENT Metric

Example from a production service (`src/metrics/constant.py`):

```python
from prometheus_client import Histogram

HTTP_REQUEST_SENT = Histogram(
    "app_http_request_sent",
    "Duration of HTTP requests sent to external services",
    ["method", "path", "status_code", "service_name"],
    buckets=CUSTOM_HISTOGRAM_BUCKETS,
    registry=_metrics_registry,
)
```

**File**: `src/metrics/constant.py`

### Recording Helper

Example from a production service (`src/metrics/helper.py`):

```python
def record_http_request_sent(
    method: str,
    path: str,
    status_code: int,
    duration: float,
) -> None:
    """Record a completed HTTP request sent to external services."""
    HTTP_REQUEST_SENT.labels(
        method=method, 
        path=path, 
        status_code=str(status_code), 
        service_name=METRIC_SERVICE_IDENTIFIER
    ).observe(duration)
```

**File**: `src/metrics/helper.py`

### Decorator Pattern for Outbound Calls

Example from a production service (`src/metrics/decorators.py`):

```python
import time
from functools import wraps
from urllib.parse import urlparse

def prometheus_http_outbound(
    method_key: str = "method", 
    url_key: str = "raw_url"
):
    """Async decorator to record Prometheus metrics for HTTP calls.
    
    Expects wrapped function signature like (self, data: Dict[str, Any], ...)
    and returned value to be a dict with `status_code` or `status`.
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Extract data argument
            data = kwargs.get("data") or (args[1] if len(args) >= 2 else {})
            
            method = data.get(method_key, "POST")
            url = data.get(url_key, "")
            path = _normalize_path_from_url(str(url))
            
            start_time = time.time()
            status_code = None
            try:
                result = await func(*args, **kwargs)
                if isinstance(result, dict):
                    status_code = result.get("status_code") or result.get("status")
                return result
            finally:
                duration = time.time() - start_time
                sc = int(status_code) if status_code else 500
                record_http_request_sent(
                    method=str(method).upper(),
                    path=path,
                    status_code=sc,
                    duration=duration,
                )
        return wrapper
    return decorator

def _normalize_path_from_url(url: str) -> str:
    """Extract and normalize path from URL for metrics labels."""
    try:
        parsed = urlparse(url or "")
        path = parsed.path or "/"
        path = path.replace("//", "/")  # Collapse slashes
        if path != "/" and path.endswith("/"):
            path = path[:-1]  # Strip trailing slash
        return path
    except Exception:
        return "/"
```

**File**: `src/metrics/decorators.py`

### Usage Example

```python
from src.metrics.decorators import prometheus_http_outbound

class ExternalAPIClient:
    @prometheus_http_outbound(method_key="method", url_key="raw_url")
    async def call_external_api(self, data: dict):
        """Make an HTTP call to an external API."""
        response = await http_client.request(
            method=data["method"],
            url=data["raw_url"],
            # ...
        )
        return {"status_code": response.status, "data": response.json()}
```

**Why normalize path from URL**: Extracts only the path component for the metric label (e.g., `/api/v1/users` from `https://api.example.com/api/v1/users?key=123`), avoiding high cardinality from query params or hostnames.

## Multi-Mode Service Instrumentation (production service pattern)

FastAPI apps often run multiple service modes in the same codebase: HTTP server, Kafka consumers, background workers, cron jobs, Temporal workflows. Each needs separate metrics instrumentation.

### Service Name Per Mode

Example from a production service (`src/metrics/service_init.py`):

```python
import os

def get_service_name(mode: str) -> str:
    """Get the service name based on the service mode."""
    base_name = os.environ.get("SERVICE_NAME", "myservice")
    deployment_name = os.environ.get("DEPLOYMENT_NAME", "app").lower()
    deployment_type = os.environ.get("DEPLOYMENT_TYPE", "server").lower()
    
    return f"{base_name}-{deployment_name}-{deployment_type}"
```

**Why**: Each deployment mode (server, consumer, worker) gets a distinct service identifier in metrics, allowing you to filter/aggregate by mode in Prometheus/Grafana.

**Environment variables**:
- `SERVICE_NAME`: Base service name (e.g., `myservice`)
- `DEPLOYMENT_NAME`: Deployment identifier (e.g., `app`, `webhook`)
- `DEPLOYMENT_TYPE`: Mode identifier (e.g., `server`, `consumer`, `worker`)

Result: `myservice-app-server`, `myservice-webhook-consumer`

### Metrics HTTP Server for Non-FastAPI Modes

Example from a production service (`src/metrics/service_init.py`):

```python
from prometheus_client import start_http_server

def get_metrics_port(mode: str) -> int:
    """Get the metrics port for each service mode."""
    port_map = {
        "server": 8000,       # FastAPI (handled by middleware)
        "consumer": 8001,     # Kafka consumers
        "worker": 8002,       # Background workers
        "cron": 8003,         # Cron jobs
        "temporal_worker": 8004,  # Temporal workflows
    }
    return port_map.get(mode, 8005)

def init_metrics_for_service(mode: str):
    """Initialize metrics collection for a specific service mode."""
    service_name = get_service_name(mode)
    registry = get_metrics_registry()
    
    # For FastAPI server, metrics are handled by PrometheusMiddleware
    if mode == "server":
        return None
    
    # For all other modes, start a dedicated HTTP server
    metrics_port = get_metrics_port(mode)
    start_http_server(metrics_port, registry=registry)
    logger.info(f"Started metrics server for {service_name} on port {metrics_port}")
    return metrics_port
```

**File**: `src/metrics/service_init.py`

**Why different ports**: Each non-FastAPI service mode runs in its own process/container and needs a separate HTTP endpoint for Prometheus to scrape.

**Why FastAPI is different**: The FastAPI server already has an HTTP server (Uvicorn), so it exposes `/metrics` via PrometheusMiddleware instead of starting a separate server.

### Execute Mode with Metrics Exporter

Example from a production service (`src/metrics/service_init.py`):

```python
from src.metrics.exporter import start_metrics_exporter_task, stop_metrics_exporter_task

async def execute_mode(mode_main_func, *args, **kwargs):
    """Execute the main function for a given mode with metrics exporter."""
    try:
        await start_metrics_exporter_task()  # Start background file exporter
        await mode_main_func(*args, **kwargs)
    finally:
        await stop_metrics_exporter_task()  # Clean shutdown
```

**File**: `src/metrics/service_init.py`

**Usage**:

```python
# Consumer entrypoint
async def consumer_main():
    # Initialize metrics HTTP server on port 8001
    init_metrics_for_service("consumer")
    
    # Start consuming messages
    await consume_kafka_messages()

if __name__ == "__main__":
    import asyncio
    from src.metrics.service_init import execute_mode
    
    asyncio.run(execute_mode(consumer_main))
```

**Why**: Ensures the metrics exporter task (which writes to `/var/data/metrics/{POD_NAME}.prom`) starts before the main logic and cleanly shuts down after.

## Key Differences: Inbound vs. Outbound Metrics

| Aspect | Inbound (HTTP_REQUEST_RECEIVED) | Outbound (HTTP_REQUEST_SENT) |
|--------|--------------------------------|------------------------------|
| **Measures** | Requests received BY this service | Requests sent TO external APIs |
| **Captured by** | PrometheusMiddleware | Decorator on HTTP client methods |
| **Path normalization** | UUIDs/IDs in incoming URL | Path from outgoing URL (no query params) |
| **Status code source** | Response from your handler | Response from external API |
| **Use case** | Service RED metrics | External dependency latency tracking |

## Design Principles

1. **Separate metrics for inbound/outbound**: Never conflate requests received with requests sent. Use distinct metric names and labels.

2. **Path normalization on both sides**: Inbound paths need UUID/ID normalization; outbound paths need query-param stripping and host removal.

3. **Multi-mode service naming**: Include deployment mode in service name so Prometheus can filter consumers/workers/cron independently.

4. **Non-FastAPI needs dedicated HTTP server**: Consumers/workers don't have an HTTP server by default, so `start_http_server()` is required for scraping.

5. **File exporter for all modes**: Whether FastAPI or not, the file exporter pattern (`/var/data/metrics/{POD_NAME}.prom`) works universally for all service modes.
