"""CORS allow-list fallback (PRP-29 C7). Same-origin serving through a reverse proxy is primary.

``NS_CORS_ALLOWED_ORIGINS`` unset or empty: no CORS middleware at all (browsers enforce
same-origin). Set: Starlette ``CORSMiddleware`` with exactly those origins. A wildcard or a
non-origin value refuses startup (``invalid_schema``, reason ``config``). Credentials are never
allowed (the SPA sends bearer tokens, not cookies); methods and request headers are fixed
allow-lists. A preflight from any other origin gets no ``Access-Control-Allow-Origin``.
"""

from __future__ import annotations

from typing import Final

from fastapi import FastAPI
from neurosphere_core.errors import InvalidSchemaError, ValidationIssue
from pydantic import ValidationError
from starlette.middleware.cors import CORSMiddleware

from neurosphere_api.middleware import CORRELATION_HEADER
from neurosphere_api.runtime.settings import CorsSettings

__all__ = [
    "ALLOWED_HEADERS",
    "ALLOWED_METHODS",
    "EXPOSED_HEADERS",
    "PREFLIGHT_MAX_AGE_SECONDS",
    "install_cors",
    "load_cors_settings",
]

ALLOWED_METHODS: Final = ("GET", "POST", "PUT", "PATCH", "DELETE")
ALLOWED_HEADERS: Final = ("Authorization", "Content-Type", "If-Match", CORRELATION_HEADER)
EXPOSED_HEADERS: Final = (
    "ETag",
    CORRELATION_HEADER,
    "Retry-After",
    "Deprecation",
    "Sunset",
    "Link",
)
PREFLIGHT_MAX_AGE_SECONDS: Final = 600


def load_cors_settings() -> CorsSettings:
    """Read ``NS_CORS_*``; an invalid list raises ``invalid_schema`` (startup is refused)."""
    try:
        return CorsSettings()
    except ValidationError as exc:
        issues = [
            ValidationIssue("/" + "/".join(str(p) for p in err["loc"]), str(err["msg"])[:200])
            for err in exc.errors(include_input=False, include_url=False)
        ]
        error = InvalidSchemaError("invalid NS_CORS_ALLOWED_ORIGINS", reason="config")
        error.errors = tuple(issues)
        raise error from None


def install_cors(app: FastAPI, settings: CorsSettings | None = None) -> bool:
    """Add ``CORSMiddleware`` for the configured origins. True when installed."""
    conf = settings if settings is not None else load_cors_settings()
    if not conf.allowed_origins:
        return False
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(conf.allowed_origins),
        allow_credentials=False,
        allow_methods=list(ALLOWED_METHODS),
        allow_headers=list(ALLOWED_HEADERS),
        expose_headers=list(EXPOSED_HEADERS),
        max_age=PREFLIGHT_MAX_AGE_SECONDS,
    )
    return True
