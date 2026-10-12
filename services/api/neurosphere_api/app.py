"""FastAPI application factory.

``create_app(settings)`` builds a fresh application; nothing is created at import time.
Routers attach only through :class:`~neurosphere_api.routers.RouterRegistry` (see
``neurosphere_api/routers.py``); ``extra_routers`` lets callers and tests add more.
Authentication and authorization are out of scope here (PRP-06).
"""

from __future__ import annotations

from collections.abc import Mapping

from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from neurosphere_core.cloud import Settings
from neurosphere_core.errors import InvalidSchemaError, NeuroSphereError, ValidationIssue
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse

from neurosphere_api.middleware import (
    DEFAULT_MAX_REQUEST_BYTES,
    CorrelationIdMiddleware,
    RequestSizeLimitMiddleware,
    correlation_id_of,
    generic_problem_response,
    problem_response,
)
from neurosphere_api.routers import RouterRegistry, register_default_routers

API_TITLE = "NeuroSphere API"
API_VERSION = "0.1.0"
_GENERIC_500_DETAIL = "An internal error occurred."


def _cid(request: Request) -> str:
    return correlation_id_of(request.scope)


async def _on_neurosphere_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, NeuroSphereError)
    return problem_response(exc, _cid(request), request.url.path)


async def _on_validation_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    # Only the location and pydantic's generic message are used; never the submitted input.
    issues = [
        ValidationIssue("/" + "/".join(str(p) for p in e["loc"]), str(e["msg"])[:500])
        for e in exc.errors()[:50]
    ]
    error = InvalidSchemaError("Request failed schema validation.", errors=issues)
    return problem_response(error, _cid(request), request.url.path)


async def _on_http_exception(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    # Contract-less statuses (404/405/...) keep their HTTP status with a minimal RFC 9457 body.
    return generic_problem_response(exc.status_code, _cid(request), request.url.path)


async def _on_unhandled(request: Request, exc: Exception) -> JSONResponse:
    # No exception text, trace or hostname leaves the process; logging is item 4's concern.
    return generic_problem_response(500, _cid(request), request.url.path, _GENERIC_500_DETAIL)


def create_app(
    settings: Settings,
    *,
    max_request_bytes: int = DEFAULT_MAX_REQUEST_BYTES,
    extra_routers: Mapping[str, APIRouter] | None = None,
) -> FastAPI:
    app = FastAPI(title=API_TITLE, version=API_VERSION)
    app.state.settings = settings

    app.add_exception_handler(NeuroSphereError, _on_neurosphere_error)
    app.add_exception_handler(RequestValidationError, _on_validation_error)
    app.add_exception_handler(StarletteHTTPException, _on_http_exception)
    app.add_exception_handler(Exception, _on_unhandled)

    # Last added is outermost: correlation wraps size limit so every response carries the id.
    app.add_middleware(RequestSizeLimitMiddleware, max_bytes=max_request_bytes)
    app.add_middleware(CorrelationIdMiddleware)

    registry = RouterRegistry()
    register_default_routers(registry)
    for prefix, router in (extra_routers or {}).items():
        registry.register(prefix, router)
    registry.attach(app)
    return app
