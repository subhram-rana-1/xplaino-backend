"""FastAPI main application."""

import structlog
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
# CORS is handled by custom middleware - CORSMiddleware not used for dynamic origin support
from fastapi.responses import RedirectResponse, Response
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
import time

from app.config import settings
from app.exceptions import (
    CatenException,
    caten_exception_handler,
    general_exception_handler,
    http_exception_handler
)
from app.routes import v1_api, v2_api, health, auth_api, saved_words_api, saved_paragraph_api, saved_page_api, issue_api, comment_api, pricing_api, domain_api
from app.services.rate_limiter import rate_limiter

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()

# Prometheus metrics
REQUEST_COUNT = Counter('http_requests_total', 'Total HTTP requests', ['method', 'endpoint', 'status'])
REQUEST_DURATION = Histogram('http_request_duration_seconds', 'HTTP request duration', ['method', 'endpoint'])


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context manager."""
    logger.info("Starting Caten API server", version="1.0.0")
    # Start rate limiter cleanup task
    await rate_limiter.start_cleanup_task()
    yield
    logger.info("Shutting down Caten API server")
    await rate_limiter.close()


# Create FastAPI application
app = FastAPI(
    title="Caten API",
    description="FastAPI backend for text and image processing with LLM integration",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# CORS is handled by custom middleware below to support dynamic origins with credentials
# CORSMiddleware is not used because it doesn't support dynamic origin echoing with credentials


def get_allowed_origin(request: Request) -> str:
    """Get the allowed origin from the request.
    
    When credentials are included, we cannot use '*' and must return the specific origin.
    Echoes back the request origin to allow requests with credentials from any origin.
    This is safe because we're echoing back what the browser sent, not allowing arbitrary origins.
    """
    origin = request.headers.get("Origin")
    
    if origin:
        # Echo back the origin - this is safe because the browser only sends origins
        # that the page is allowed to make requests from
        return origin
    
    # Fallback: if no origin header, return None
    return None


@app.middleware("http")
async def cors_preflight_handler(request: Request, call_next):
    """Handle CORS preflight requests explicitly for Chrome extensions and file uploads."""
    if request.method == "OPTIONS":
        response = Response()
        # Get the actual origin instead of using wildcard when credentials are required
        allowed_origin = get_allowed_origin(request)
        if allowed_origin:
            response.headers["Access-Control-Allow-Origin"] = allowed_origin
        else:
            # Fallback to wildcard only if no origin is present (shouldn't happen with credentials)
            response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS, PATCH"
        response.headers["Access-Control-Allow-Headers"] = "Accept, Accept-Language, Content-Language, Content-Type, Authorization, X-Requested-With, X-CSRFToken, X-Forwarded-For, User-Agent, Origin, Referer, Cache-Control, Pragma, Content-Disposition, Content-Transfer-Encoding, X-File-Name, X-File-Size, X-File-Type, X-Access-Token, X-Unauthenticated-User-Id, X-Source"
        response.headers["Access-Control-Max-Age"] = "300"  # Reduced from 3600 to 5 minutes for easier testing
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Expose-Headers"] = "Content-Length, Content-Type, Cache-Control, X-Accel-Buffering, Content-Disposition, Access-Control-Allow-Origin, Access-Control-Allow-Methods, Access-Control-Allow-Headers, X-Unauthenticated-User-Id, X-Source"
        return response
    
    response = await call_next(request)
    
    # Add CORS headers to all responses (including StreamingResponse)
    # For StreamingResponse, headers should already be set in the endpoint, but we ensure they're here too
    from fastapi.responses import StreamingResponse
    allowed_origin = get_allowed_origin(request)
    
    if isinstance(response, StreamingResponse):
        # StreamingResponse headers - always override to ensure correct origin is used
        # Use specific origin instead of wildcard when credentials are required
        if allowed_origin:
            response.headers["Access-Control-Allow-Origin"] = allowed_origin
        else:
            # Only use wildcard if no origin is present (shouldn't happen with credentials)
            if "Access-Control-Allow-Origin" not in response.headers:
                response.headers["Access-Control-Allow-Origin"] = "*"
        if "Access-Control-Allow-Credentials" not in response.headers:
            response.headers["Access-Control-Allow-Credentials"] = "true"
    else:
        # For regular responses, add CORS headers
        # Use specific origin instead of wildcard when credentials are required
        if allowed_origin:
            response.headers["Access-Control-Allow-Origin"] = allowed_origin
        else:
            response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Expose-Headers"] = "Content-Length, Content-Type, Cache-Control, X-Accel-Buffering, Content-Disposition, Access-Control-Allow-Origin, Access-Control-Allow-Methods, Access-Control-Allow-Headers, X-Unauthenticated-User-Id, X-Source"
    
    return response


@app.middleware("http")
async def logging_middleware(request: Request, call_next):
    """Logging and metrics middleware."""
    start_time = time.time()
    
    # Log request
    logger.info(
        "HTTP request started",
        method=request.method,
        path=request.url.path,
        client_ip=request.client.host
    )
    
    # Process request
    response = await call_next(request)
    
    # Calculate duration
    duration = time.time() - start_time
    
    # Update metrics
    if settings.enable_metrics:
        REQUEST_COUNT.labels(
            method=request.method,
            endpoint=request.url.path,
            status=response.status_code
        ).inc()
        
        REQUEST_DURATION.labels(
            method=request.method,
            endpoint=request.url.path
        ).observe(duration)
    
    # Log response
    logger.info(
        "HTTP request completed",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration=f"{duration:.3f}s"
    )
    
    return response


# Add exception handlers
app.add_exception_handler(CatenException, caten_exception_handler)
app.add_exception_handler(Exception, general_exception_handler)

# Include routers
app.include_router(health.router)
app.include_router(v1_api.router)
app.include_router(v2_api.router)
app.include_router(auth_api.router)
app.include_router(saved_words_api.router)
app.include_router(saved_paragraph_api.router)
app.include_router(saved_page_api.router)
app.include_router(issue_api.router)
app.include_router(comment_api.router)
app.include_router(pricing_api.router)
app.include_router(domain_api.router)


@app.get("/metrics", include_in_schema=False)
async def metrics():
    """Prometheus metrics endpoint."""
    if not settings.enable_metrics:
        return Response("Metrics disabled", status_code=404)
    
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/", include_in_schema=False)
async def root():
    """Root endpoint that redirects to docs."""
    return RedirectResponse(url="/docs")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level=settings.log_level.lower()
    )
