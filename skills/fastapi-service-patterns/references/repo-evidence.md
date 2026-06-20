# Example Patterns

Illustrative code snippets demonstrating FastAPI patterns. All credentials redacted.

## Example Service A (Modern Async Service)

### app/application.py

```python
def get_app() -> FastAPI:
    app = FastAPI(
        debug=settings.DEBUG,
        title="MyService",
        default_response_class=ORJSONResponse,
        lifespan=lifespan,
        docs_url="/docs" if settings.DEBUG else None,
    )
    app.include_router(api_router)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-Skip-Cache"],
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next: object) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        # ... CSP, Referrer-Policy, Permissions-Policy, HSTS
        return response
```

**What to copy**: FastAPI init with lifespan, ORJSONResponse default, CORS middleware with explicit origins, security headers middleware.

### app/lifetime.py

```python
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    setup_logging()
    ConnectionManager()
    yield
    from app.telemetry import shutdown_telemetry
    shutdown_telemetry()
    await ConnectionManager().close_connections()
```

**What to copy**: lifespan context manager for startup/shutdown resource management.

### app/routing.py

```python
class CustomRequestRoute(APIRoute):
    def get_route_handler(self) -> Callable:
        original_route_handler = super().get_route_handler()

        async def custom_route_handler(request: Request) -> Response:
            start_time = time.perf_counter()
            try:
                response: Response = await original_route_handler(request)
                duration = time.perf_counter() - start_time
                logger.info("request_handled", method=request.method, path=request.url.path,
                            status_code=response.status_code, duration=round(duration, 4))
                return response
            except (RequestValidationError, ValidationError) as exc:
                raw_errors = [{"field": e["loc"][-1], "msg": e["msg"]} for e in exc.errors()]
                errors = [f"{e['field']}: {e['msg']}" for e in raw_errors]
                return ORJSONResponse(
                    content=ResponseData.error(errors=errors, message="Validation error").model_dump(),
                    status_code=HTTP_400_BAD_REQUEST,
                )
            except HTTPException as exc:
                return ORJSONResponse(
                    content=ResponseData.error(errors=[exc.detail], message=exc.detail).model_dump(),
                    status_code=exc.status_code,
                )
            except Exception as exc:
                logger.exception("unhandled_exception", path=request.url.path, error=str(exc))
                return ORJSONResponse(
                    content=ResponseData.error(errors=[str(exc)], message="Internal server error").model_dump(),
                    status_code=HTTP_500_INTERNAL_SERVER_ERROR,
                )
        return custom_route_handler
```

**What to copy**: CustomRequestRoute pattern with structured logging, timing, exception handling (RequestValidationError, HTTPException, generic Exception), ResponseData envelope.

### app/connection.py

```python
class ConnectionManager:
    _instance: Optional["ConnectionManager"] = None

    def __new__(cls) -> "ConnectionManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True, ...)
            cls._instance._db_session_factory = async_scoped_session(
                sessionmaker(engine, expire_on_commit=False, class_=AsyncSession),
                scopefunc=current_task,
            )
            cls._instance._redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
        return cls._instance

    async def close_connections(self) -> None:
        await self._db_engine.dispose()
        await self._redis.close()

class ConnectionHandler:
    @property
    def session(self) -> AsyncSession:
        if not self._session:
            self._session = self._connection_manager.get_session_factory()()
        return self._session

    async def set_tenant_context(self, tenant_id: UUID) -> None:
        await self.session.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tenant_id)})

async def get_connection_handler() -> AsyncGenerator[ConnectionHandler, None]:
    handler = ConnectionHandler()
    try:
        yield handler
    finally:
        await handler.close()
```

**What to copy**: Singleton ConnectionManager with scoped session factory, lazy ConnectionHandler session property, RLS/schema context methods, dependency factory.

### app/views.py

```python
async def list_pending_actions(
    session: dict[str, object] = Depends(require_auth),
    connection_handler: ConnectionHandler = Depends(get_connection_handler),
) -> ResponseData:
    user_id = get_caller_user_id(session)
    helper = RequiredActionHelper(connection_handler)
    actions = await helper.list_pending_actions(user_id)
    return ResponseData.ok(data=[a.model_dump(mode="json") for a in actions], message="Pending actions listed")
```

**What to copy**: Dependency injection pattern with `Depends(require_auth)` and `Depends(get_connection_handler)`, returning ResponseData envelope.

## Example Service B (Multi-Environment Service)

### app/application.py

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    await run_on_startup()
    yield
    await run_on_exit()

def get_app() -> FastAPI:
    myservice_app = FastAPI(
        debug=loaded_config.debug,
        title="myservice",
        default_response_class=ORJSONResponse,
        lifespan=lifespan,
        openapi_url="/swagger.json",
        root_path=f"/service/{loaded_config.SERVER_TYPE}/{product_path}",
    )
    myservice_app.include_router(api_router)

    def custom_openapi(app: FastAPI):
        openapi_schema = get_openapi(...)
        url_prefix = f"/service/{loaded_config.SERVER_TYPE}/{product_path}"
        paths = {f"{url_prefix}{path}": path_item for path, path_item in openapi_schema["paths"].items()}
        # Conditionally add/remove headers per env
        if loaded_config.ENV != "local":
            paths[serviceability_path]["post"]["parameters"] = [
                param for param in existing_params if param.get("name") != "aggregator-account-id"
            ]
            paths[serviceability_path]["post"]["parameters"].append(account_token_param)
        openapi_schema["paths"] = paths
        return openapi_schema

    myservice_app.openapi_schema = custom_openapi(app=myservice_app)
    return myservice_app
```

**What to copy**: Custom OpenAPI schema manipulation (root_path injection, conditional header addition/removal).

### app/routing.py

```python
async def custom_route_handler(request: Request) -> Response:
    request_data = await process_request_data(request=request)
    start_time = time.perf_counter()
    try:
        content_type = request.headers.get("content-type")
        request_data["request_body"] = (
            orjson.loads(request_data["request_body"])
            if request_data["request_body"] and not content_type.startswith("multipart/form-data")
            else {}
        )
        response: Response = await original_route_handler(request)
        request_data["request_duration"] = time.perf_counter() - start_time
        response_data = {"status_code": response.status_code, "body": orjson.loads(response.body.decode("utf-8"))}
        logger.info(f"HTTP request for {request_data['url_path']}", request_data=request_data, response_data=response_data)
        return response
    except (orjson.JSONDecodeError, ApiException) as exc:
        return request_exception_handler(..., status_code=HTTP_400_BAD_REQUEST)
    # ... more exception branches
```

**What to copy**: Request data extraction, JSON body parsing with multipart/form-data guard, structured logging with request+response data.

### app/utils.py

```python
class ResponseData(BaseModel):
    success: bool
    data: List | Dict = Field(default_factory=list)
    errors: List = Field(default_factory=list)
    identifier: str = Field(default_factory=lambda: str(uuid4()))
    failed_entries: List = Field(default_factory=list)
    pagination: Dict = None

class ListDataResponse(CommonResponseModel):
    data: List

class DictDataResponse(CommonResponseModel):
    data: Dict
```

**What to copy**: ResponseData schema, typed response helpers (ListDataResponse/DictDataResponse).

### app/router.py

```python
api_router = APIRouter()
api_router_prefix = APIRouter(prefix="/v1.0")

if loaded_config.SERVER_TYPE == "public":
    api_router_prefix.include_router(shipment_router, tags=["Shipment v1.0"])
elif loaded_config.SERVER_TYPE == "internal":
    api_router_prefix.include_router(shipment_router, tags=["Shipment v1.0"])
    api_router_prefix.include_router(partner_config_router, tags=["Partner Config v1.0"])
# ... more conditional includes

api_router.include_router(api_router_prefix)
```

**What to copy**: Conditional router inclusion based on server type/environment.

## Example Service C (Service with RBAC)

### app/routing.py

```python
async def custom_route_handler(request: Request) -> Response:
    # ...
    try:
        if x_user_data := request.headers.get("x-user-data"):
            x_user_data = orjson.loads(x_user_data)
            request.state.user_data = x_user_data
    except orjson.JSONDecodeError as exc:
        return ORJSONResponse(
            content=ResponseData.model_construct(errors=[str(exc)], success=False).dict(),
            status_code=HTTP_400_BAD_REQUEST,
        )
    # ...
    except (RequestValidationError, ValidationError) as exc:
        request_data["error"] = [{"field": error["loc"][-1], "msg": error["msg"]} for error in exc.errors()]
        error_response = ResponseData.model_construct(
            errors=request_data["error"], success=False, error_code=["AE101"]
        ).dict()
        return ORJSONResponse(content=error_response, status_code=HTTP_400_BAD_REQUEST)
```

**What to copy**: Parsing x-user-data header into `request.state.user_data`, validation error formatting with error_code=["AE101"].

### app/middlewares.py

```python
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

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        for pattern in self.exclude_patterns:
            if pattern.fullmatch(path):
                return await call_next(request)

        x_user_data = request.headers.get("x-user-data")
        if not x_user_data:
            return ORJSONResponse({"success": False, "errors": ["x-user-data header is missing."]}, status_code=HTTP_403_FORBIDDEN)
        x_user_data = orjson.loads(x_user_data)

        # Check if route requires specific role tag
        if user_role not in route_tags:
            return ORJSONResponse({"success": False, "errors": ["Access denied."]}, status_code=HTTP_403_FORBIDDEN)
        return await call_next(request)
```

**What to copy**: RBAC middleware that reads route tags (`"skip_rbac"`, `"public_authenticated"`) to gate access, extracts x-user-data header, checks user role against route tags.

## Example Service D (Legacy Pattern)

### app/lifetime.py (deprecated)

```python
@app.on_event("startup")
async def _startup() -> None:
    await run_on_startup()

@app.on_event("shutdown")
async def _shutdown() -> None:
    await run_on_exit()
```

**What to copy**: DEPRECATED pattern; migrate to lifespan context manager.
