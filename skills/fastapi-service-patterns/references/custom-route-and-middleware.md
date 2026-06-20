# Custom Route Handler and Middleware Stack

Deep pattern inventory for custom `APIRoute` subclass, middleware patterns, and the `ResponseData` envelope.

## CustomRequestRoute pattern

### Purpose

Wrap every route handler with cross-cutting concerns:

1. **Request logging** (method, path, timing)
2. **Exception handling** (validation errors, HTTP exceptions, generic exceptions)
3. **Response formatting** (wrap in `ResponseData` envelope)
4. **Request state enrichment** (parse x-user-data header into `request.state.user_data`)

### Implementation structure

```python
from fastapi import Request, Response
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.responses import ORJSONResponse
from fastapi.routing import APIRoute
from pydantic import ValidationError

class CustomRequestRoute(APIRoute):
    def get_route_handler(self) -> Callable:
        original_route_handler = super().get_route_handler()

        async def custom_route_handler(request: Request) -> Response:
            # 1. Preprocessing: parse headers, extract request data
            # 2. Invoke original route handler
            # 3. Log request + response
            # 4. Exception handling: catch and format errors
            # 5. Return ORJSONResponse with ResponseData envelope
        return custom_route_handler
```

### Timing and logging

```python
import time
from config.logging import get_logger

logger = get_logger(__name__)

async def custom_route_handler(request: Request) -> Response:
    start_time = time.perf_counter()
    try:
        response: Response = await original_route_handler(request)
        duration = time.perf_counter() - start_time
        logger.info(
            "request_handled",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration=round(duration, 4),
        )
        return response
    except ...:
        # Exception branches below
```

### Exception handling: RequestValidationError

**Simple error list**:

```python
except (RequestValidationError, ValidationError) as exc:
    raw_errors = [
        {"field": e["loc"][-1] if e.get("loc") else "unknown", "msg": e["msg"]}
        for e in exc.errors()
    ]
    logger.warning("validation_error", path=request.url.path, errors=raw_errors)
    errors = [f"{e['field']}: {e['msg']}" if isinstance(e, dict) else str(e) for e in raw_errors]
    return ORJSONResponse(
        content=ResponseData.error(errors=errors, message="Validation error").model_dump(),
        status_code=HTTP_400_BAD_REQUEST,
    )
```

**With error code**:

```python
except (RequestValidationError, ValidationError) as exc:
    request_data["error"] = [
        {"field": error["loc"][-1], "msg": error["msg"]}
        for error in exc.errors()
    ]
    logger.exception(f"HTTP request Exception Occurred for {route_name}", extra={"request_data": request_data})
    error_response = ResponseData.model_construct(
        errors=request_data["error"], success=False, error_code=["AE101"]
    ).dict()
    return ORJSONResponse(content=error_response, status_code=HTTP_400_BAD_REQUEST)
```

**Key points**:
- Extract field name from `error["loc"][-1]` (last element of location tuple)
- Format as `{"field": "...", "msg": "..."}` or `"field: msg"`
- Optional: add error_code (e.g., `["AE101"]` for validation errors)

### Exception handling: HTTPException

```python
except HTTPException as exc:
    logger.warning("http_exception", path=request.url.path, status=exc.status_code, detail=exc.detail)
    return ORJSONResponse(
        content=ResponseData.error(errors=[exc.detail], message=exc.detail).model_dump(),
        status_code=exc.status_code,
    )
```

### Exception handling: generic Exception

```python
except Exception as exc:
    logger.exception("unhandled_exception", path=request.url.path, error=str(exc))
    return ORJSONResponse(
        content=ResponseData.error(errors=[str(exc)], message="Internal server error").model_dump(),
        status_code=HTTP_500_INTERNAL_SERVER_ERROR,
    )
```

### Request data extraction and x-user-data parsing

```python
async def process_request_data(request: Request) -> dict:
    request_data = {
        "client_host": request.client,
        "url": request.url.components,
        "url_path": request.scope["route"].path,
        "request_method": request.method,
        "path_params": request.path_params.items(),
        "query_params": request.query_params.items(),
        "headers": request.headers.items(),
        "request_body": await request.body(),
    }
    return request_data

# Inside custom_route_handler:
request_data = await process_request_data(request=request)
start_time = time.perf_counter()
try:
    content_type = request.headers.get("content-type")
    request_data["request_body"] = (
        orjson.loads(request_data["request_body"])
        if request_data["request_body"] and not content_type.startswith("multipart/form-data")
        else {}
    )
    if x_user_data := request.headers.get("x-user-data"):
        x_user_data = orjson.loads(x_user_data)
        request.state.user_data = x_user_data  # Attach to request state for downstream use
    # ... continue
except orjson.JSONDecodeError as exc:
    return ORJSONResponse(
        content=ResponseData.model_construct(errors=[str(exc)], success=False).dict(),
        status_code=HTTP_400_BAD_REQUEST,
    )
```

**What to copy**: Parse x-user-data JWT header (base64-encoded JSON payload containing user ID, role, tenant ID) and attach to `request.state.user_data` for access in route handlers.

### Response logging

```python
response: Response = await original_route_handler(request)
end_time = time.perf_counter()
request_data["request_duration"] = end_time - start_time
response_data = {
    "status_code": response.status_code,
    "body": orjson.loads(response.body.decode("utf-8")),
}
logger.info(
    f"HTTP request for {request_data['url_path']} with method {request.method}",
    request_data=request_data,
    response_data=response_data,
)
return response
```

**Note**: Parsing response.body works for JSON responses; skip for binary/streaming.

## ResponseData envelope

### Schema

```python
from pydantic import BaseModel, Field
from uuid import uuid4

class ResponseData(BaseModel):
    success: bool
    data: List | Dict = Field(default_factory=list)
    errors: List = Field(default_factory=list)
    identifier: str = Field(default_factory=lambda: str(uuid4()))
    failed_entries: List = Field(default_factory=list)
    pagination: Dict = None
```

### Helpers

```python
class ResponseData(BaseModel):
    # ... fields

    @classmethod
    def ok(cls, data=None, message: str = "") -> "ResponseData":
        return cls(success=True, data=data or [], errors=[], message=message)

    @classmethod
    def error(cls, errors: List[str], message: str = "") -> "ResponseData":
        return cls(success=False, data=[], errors=errors, message=message)
```

### Typed wrappers

```python
class CommonResponseModel(BaseModel):
    identifier: str
    success: bool
    errors: List
    failed_entries: List

class ListDataResponse(CommonResponseModel):
    data: List

class DictDataResponse(CommonResponseModel):
    data: Dict
```

**Usage**: define endpoint return type as `ListDataResponse` or `DictDataResponse` for OpenAPI schema clarity.

### Example usage in route

```python
async def list_items(
    connection_handler: ConnectionHandler = Depends(get_connection_handler),
) -> ResponseData:
    items = await SomeDAO(connection_handler.session).list_all()
    return ResponseData.ok(data=[i.model_dump() for i in items], message="Items listed")
```

CustomRequestRoute automatically wraps any exceptions; successful responses are logged and returned as-is.

## Middleware stack

### RBAC middleware

```python
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
import re

class RbacMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, fastapi_app):
        super().__init__(app)
        self.exclude_patterns = self.get_exclude_patterns(fastapi_app)
        self.public_authenticated_patterns = self.get_public_authenticated_patterns(fastapi_app)

    def get_exclude_patterns(self, app):
        exclude_patterns = []
        for route in app.routes:
            if isinstance(route, APIRoute) and "skip_rbac" in route.tags:
                path_regex = re.compile(route.path_regex.pattern)
                exclude_patterns.append(path_regex)
        return exclude_patterns

    def get_public_authenticated_patterns(self, app):
        patterns = []
        for route in app.routes:
            if isinstance(route, APIRoute) and "public_authenticated" in route.tags:
                path_regex = re.compile(route.path_regex.pattern)
                patterns.append(path_regex)
        return patterns

    async def dispatch(self, request: Request, call_next):
        if request.url.path not in ["/redoc", "/openapi.json"]:
            path = request.url.path

            # 1. Check skip_rbac routes
            for pattern in self.exclude_patterns:
                if pattern.fullmatch(path):
                    return await call_next(request)

            # 2. Require x-user-data header
            x_user_data = request.headers.get("x-user-data")
            if not x_user_data:
                return ORJSONResponse(
                    {"success": False, "errors": ["x-user-data header is missing."]},
                    status_code=HTTP_403_FORBIDDEN,
                )
            x_user_data = orjson.loads(x_user_data)

            # 3. Check public_authenticated routes (skip role check)
            for pattern in self.public_authenticated_patterns:
                if pattern.fullmatch(path):
                    return await call_next(request)

            # 4. Check user role against route tags
            user_role = x_user_data.get("roleSlug")
            if not user_role:
                return ORJSONResponse(
                    {"success": False, "errors": ["No roles found for user."]},
                    status_code=HTTP_403_FORBIDDEN,
                )

            # 5. Match route and check if user_role in route.tags
            matched_route = None
            for route in request.app.routes:
                if isinstance(route, APIRoute) and re.fullmatch(route.path_regex.pattern, path):
                    if request.method in route.methods:
                        matched_route = route
                        break

            if not matched_route:
                return ORJSONResponse(
                    {"success": False, "errors": ["Route not found."]},
                    status_code=HTTP_404_NOT_FOUND,
                )

            route_tags = matched_route.tags
            if user_role not in route_tags:
                return ORJSONResponse(
                    {"success": False, "errors": ["Access denied. Role not authorized."]},
                    status_code=HTTP_403_FORBIDDEN,
                )

        response = await call_next(request)
        return response
```

**Usage**:

```python
app.add_middleware(RbacMiddleware, fastapi_app=app)

# In route definition:
@router.get("/public-endpoint", tags=["skip_rbac"])
async def public_endpoint():
    ...

@router.get("/authenticated-endpoint", tags=["public_authenticated"])
async def authenticated_endpoint():
    ...

@router.get("/admin-endpoint", tags=["admin", "super_admin"])
async def admin_endpoint():
    ...
```

### Other middleware patterns

1. **TraceIDMiddleware**: generate/extract trace ID from headers, attach to `request.state.trace_id`, inject into logger context.
2. **TenantMiddleware**: parse tenant ID from x-tenant-id header, set `request.state.tenant_id`.
3. **AuditMiddleware**: log request/response for audit trail.
4. **PrometheusMiddleware**: record HTTP request metrics (duration, status, method, path).
5. **SlowAPI rate limiter**: throttle requests per IP/user.

### Middleware execution order

Middleware wraps the app in reverse order of addition:

```python
app.add_middleware(CORSMiddleware, ...)       # Outermost (first to process request, last to process response)
app.add_middleware(RbacMiddleware, ...)       # Middle
@app.middleware("http")                       # Innermost (last to process request, first to process response)
async def security_headers(...): ...
```

Request flow: CORS → RBAC → security_headers → route handler → security_headers → RBAC → CORS.

## Summary checklist

When implementing custom route and middleware:

- [ ] Subclass `APIRoute` and override `get_route_handler()`
- [ ] Add timing/logging (start_time, duration, logger.info)
- [ ] Catch `RequestValidationError`, `HTTPException`, `Exception`
- [ ] Format validation errors as `{"field": ..., "msg": ...}`
- [ ] Return `ORJSONResponse` with `ResponseData` envelope
- [ ] Parse x-user-data header into `request.state.user_data` if needed
- [ ] Log both request and response data for audit trail
- [ ] Implement RBAC middleware if role-based access control is required
- [ ] Use route tags `["skip_rbac"]` or `["public_authenticated"]` to bypass RBAC on specific endpoints
- [ ] Add security headers middleware for production
- [ ] Order middleware correctly (CORS outermost, RBAC before route handler)
