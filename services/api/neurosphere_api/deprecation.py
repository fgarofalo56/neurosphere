"""Deprecated path aliases (PRP-29 item 4, Clarification 9).

Routers moved under ``/api/v1`` keep their old prefix for one release. :func:`register_with_alias`
registers the router at the successor prefix, and its operations again at the old prefix through
an alias router (same endpoints, same dependencies) that marks every operation ``deprecated`` in
OpenAPI and adds the response headers
``Deprecation: true``, ``Sunset: <HTTP-date>`` (RFC 8594) and
``Link: <successor>; rel="successor-version"``. Handlers, dependencies and permissions are shared,
so both forms authorize identically; the alias adds no permission and removes none.

The headers are set on the dependency-injected ``Response``, so they are present on every
response a handler produces. Error responses built by the app-level exception handlers (401, 403,
422, 503) do not carry them.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from email.utils import format_datetime
from typing import Final
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request, Response
from fastapi.routing import APIRoute

from neurosphere_api.routers import RouterRegistry

__all__ = [
    "DEPRECATION_HEADER",
    "SUNSET",
    "SUNSET_AT",
    "deprecated_alias",
    "register_with_alias",
    "successor_path",
]

#: End of the one-release overlap for every alias (the single place to change it).
SUNSET_AT: Final = datetime(2027, 4, 30, tzinfo=UTC)
#: ``Sunset`` header value: an IMF-fixdate (RFC 8594 section 3).
SUNSET: Final = format_datetime(SUNSET_AT, usegmt=True)
#: ``Deprecation`` header value, as fixed by the PRP-29 wire contract.
DEPRECATION_HEADER: Final = "true"

# RFC 3986 pchar plus "/": anything else in the successor path is percent-encoded, so a request
# path can never inject a header delimiter, a ">" or a control character into the Link value.
_PATH_SAFE: Final = "/:@!$&'()*+,;=-._~"


def successor_path(request_path: str, *, alias_prefix: str, successor_prefix: str) -> str:
    """The request path rewritten from ``alias_prefix`` to ``successor_prefix``."""
    if request_path == alias_prefix or request_path.startswith(alias_prefix + "/"):
        rest = request_path[len(alias_prefix) :]
    else:
        rest = ""
    return quote(successor_prefix + rest, safe=_PATH_SAFE)


def _headers_dependency(
    alias_prefix: str, successor_prefix: str
) -> Callable[[Request, Response], Awaitable[None]]:
    async def deprecated_path_headers(request: Request, response: Response) -> None:
        path = request.url.path
        root = request.scope.get("root_path", "")
        if isinstance(root, str) and root and path.startswith(root):
            path = path[len(root) :]
        successor = successor_path(
            path, alias_prefix=alias_prefix, successor_prefix=successor_prefix
        )
        response.headers["Deprecation"] = DEPRECATION_HEADER
        response.headers["Sunset"] = SUNSET
        response.headers["Link"] = f'<{successor}>; rel="successor-version"'

    return deprecated_path_headers


def deprecated_alias(router: APIRouter, *, alias_prefix: str, successor_prefix: str) -> APIRouter:
    """A router serving ``router``'s operations again, marked deprecated, with the alias headers.

    Each ``APIRoute`` is re-declared with the SAME endpoint callable and the SAME dependency
    objects (so the permission ``require`` markers the route inventory reads are shared), plus
    the header dependency first. ``include_router`` cannot be used: FastAPI refuses to include a
    router with an empty-path operation (``POST ""`` of the deploy routes) without a prefix.
    Any other route type is refused rather than silently left without an alias.
    """
    headers = Depends(_headers_dependency(alias_prefix, successor_prefix))
    alias = APIRouter()
    for route in router.routes:
        if not isinstance(route, APIRoute):
            raise TypeError(f"cannot alias a non-API route: {route!r}")
        alias.add_api_route(
            route.path,
            route.endpoint,
            response_model=route.response_model,
            status_code=route.status_code,
            tags=list(route.tags),
            dependencies=[headers, *route.dependencies],
            summary=route.summary,
            description=route.description,
            response_description=route.response_description,
            responses=dict(route.responses),
            deprecated=True,
            methods=sorted(route.methods or ()),
            operation_id=f"{route.operation_id}_deprecated" if route.operation_id else None,
            response_model_include=route.response_model_include,
            response_model_exclude=route.response_model_exclude,
            response_model_by_alias=route.response_model_by_alias,
            response_model_exclude_unset=route.response_model_exclude_unset,
            response_model_exclude_defaults=route.response_model_exclude_defaults,
            response_model_exclude_none=route.response_model_exclude_none,
            include_in_schema=route.include_in_schema,
            response_class=route.response_class,
            name=route.name,
            route_class_override=type(route),
            callbacks=route.callbacks,
            openapi_extra=route.openapi_extra,
            generate_unique_id_function=route.generate_unique_id_function,
            strict_content_type=route.strict_content_type,
        )
    return alias


def register_with_alias(
    registry: RouterRegistry, router: APIRouter, *, prefix: str, alias_prefix: str
) -> None:
    """Register ``router`` at ``prefix`` and again at ``alias_prefix`` as a deprecated alias."""
    registry.register(prefix, router)
    registry.register(
        alias_prefix,
        deprecated_alias(router, alias_prefix=alias_prefix, successor_prefix=prefix),
    )
