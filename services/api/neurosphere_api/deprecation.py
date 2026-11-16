"""Deprecated path aliases (PRP-29 item 4, Clarification 9).

Routers moved under ``/api/v1`` keep their old prefix for one release. :func:`register_with_alias`
registers the router at the successor prefix, and its operations again at the old prefix through
an alias router (same endpoints, same dependencies) that marks every operation ``deprecated`` in
OpenAPI and adds the response headers
``Deprecation: @<epoch>`` (RFC 9745), ``Sunset: <HTTP-date>`` (RFC 8594) and
``Link: <successor>; rel="successor-version"``. Handlers, dependencies and permissions are shared,
so both forms authorize identically; the alias adds no permission and removes none.

The headers are set on the dependency-injected ``Response`` (every response a handler produces)
and by :func:`install_alias_headers`, an ASGI middleware keyed on the alias prefixes that
:func:`register_with_alias` records, so error responses built by the app-level exception
handlers (401, 403, 422, 503) carry them too. Both write identical values.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, MutableMapping
from datetime import UTC, datetime
from email.utils import format_datetime
from typing import Any, Final
from urllib.parse import quote

from fastapi import APIRouter, Depends, FastAPI, Request, Response
from fastapi.routing import APIRoute

from neurosphere_api.routers import RouterRegistry

__all__ = [
    "ALIAS_SUCCESSORS",
    "DEPRECATED_AT",
    "DEPRECATION_HEADER",
    "SUNSET",
    "SUNSET_AT",
    "alias_headers",
    "deprecated_alias",
    "install_alias_headers",
    "register_with_alias",
    "successor_path",
]

#: End of the one-release overlap for every alias (the single place to change it).
SUNSET_AT: Final = datetime(2027, 4, 30, tzinfo=UTC)
#: ``Sunset`` header value: an IMF-fixdate (RFC 8594 section 3).
SUNSET: Final = format_datetime(SUNSET_AT, usegmt=True)
#: When the aliases were deprecated (ASSUMPTION: the PRP-29 release month; change here only).
DEPRECATED_AT: Final = datetime(2026, 11, 1, tzinfo=UTC)
#: ``Deprecation`` header value: an RFC 9745 structured-field date, ``@<epoch seconds>``.
DEPRECATION_HEADER: Final = f"@{int(DEPRECATED_AT.timestamp())}"
#: Alias prefix -> successor prefix, recorded by :func:`register_with_alias`.
ALIAS_SUCCESSORS: Final[dict[str, str]] = {}

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


def alias_headers(
    request_path: str, *, alias_prefix: str, successor_prefix: str
) -> tuple[tuple[str, str], ...]:
    """The three alias response headers for a request path (root path already stripped)."""
    successor = successor_path(
        request_path, alias_prefix=alias_prefix, successor_prefix=successor_prefix
    )
    return (
        ("Deprecation", DEPRECATION_HEADER),
        ("Sunset", SUNSET),
        ("Link", f'<{successor}>; rel="successor-version"'),
    )


def _match_alias(path: str) -> str | None:
    """The longest registered alias prefix of ``path`` (segment boundary), else ``None``."""
    best: str | None = None
    for alias in ALIAS_SUCCESSORS:
        if (path == alias or path.startswith(alias + "/")) and (
            best is None or len(alias) > len(best)
        ):
            best = alias
    return best


class _AliasHeadersMiddleware:
    """Pure ASGI: adds the alias headers to every HTTP response on an alias path."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = str(scope.get("path", ""))
        root = scope.get("root_path", "")
        if isinstance(root, str) and root and path.startswith(root):
            path = path[len(root) :]
        alias = _match_alias(path)
        if alias is None:
            await self.app(scope, receive, send)
            return
        extra = alias_headers(path, alias_prefix=alias, successor_prefix=ALIAS_SUCCESSORS[alias])

        async def send_with_headers(message: MutableMapping[str, Any]) -> None:
            if message["type"] == "http.response.start":
                names = {name.lower().encode("latin-1") for name, _ in extra}
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() not in names]
                headers.extend((n.lower().encode("latin-1"), v.encode("latin-1")) for n, v in extra)
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)


def install_alias_headers(app: FastAPI) -> None:
    """Install the alias-header middleware (error responses included) on ``app``."""
    app.add_middleware(_AliasHeadersMiddleware)


def _headers_dependency(
    alias_prefix: str, successor_prefix: str
) -> Callable[[Request, Response], Awaitable[None]]:
    async def deprecated_path_headers(request: Request, response: Response) -> None:
        path = request.url.path
        root = request.scope.get("root_path", "")
        if isinstance(root, str) and root and path.startswith(root):
            path = path[len(root) :]
        for name, value in alias_headers(
            path, alias_prefix=alias_prefix, successor_prefix=successor_prefix
        ):
            response.headers[name] = value

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
    ALIAS_SUCCESSORS[alias_prefix.rstrip("/")] = prefix.rstrip("/")
