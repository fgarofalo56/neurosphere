"""Thin HTTP handlers for the ingest edge. All logic is in :class:`IngestService`.

The service lives on ``app.state.ingest_service`` (set with :func:`configure_ingest`); until it
is configured every route fails closed with 503, like the audit router.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import APIRouter, FastAPI, Request
from neurosphere_core.cloud import Settings
from neurosphere_core.errors import DependencyTransientError, InvalidSchemaError

from neurosphere_api.deprecation import register_with_alias
from neurosphere_api.ingest.auth import (
    ProducerRegistration,
    RegisteredCredentialAuthenticator,
    StaticProducerRegistry,
)
from neurosphere_api.ingest.limits import TokenBucketLimiter, check_declared_length, read_limited
from neurosphere_api.ingest.publisher import Publisher
from neurosphere_api.ingest.reasons import ReasonCode
from neurosphere_api.ingest.service import IngestResult, IngestService
from neurosphere_api.ingest.settings import IngestSettings
from neurosphere_api.routers import RouterRegistry

ROUTE_PREFIX = "/api/v1/ingest"
#: Deprecated alias for one release (PRP-29 item 4): external producers need the overlap.
ALIAS_PREFIX = "/v1/ingest"
_JSON = "application/json"


def build_service(
    settings: Settings,
    ingest_settings: IngestSettings,
    publisher: Publisher,
    *,
    registry: StaticProducerRegistry | None = None,
) -> IngestService:
    if registry is None:
        path = ingest_settings.producers_file
        registry = StaticProducerRegistry.from_file(path) if path else StaticProducerRegistry([])
    return IngestService(
        settings=ingest_settings,
        edge_cloud=settings.cloud_profile.cloud.value,
        authenticator=RegisteredCredentialAuthenticator(registry),
        publisher=publisher,
        limiter=TokenBucketLimiter(
            ingest_settings.rate_limit_rps, ingest_settings.rate_limit_burst
        ),
    )


def configure_ingest(app: FastAPI, service: IngestService) -> None:
    app.state.ingest_service = service


def _service(request: Request) -> IngestService:
    service = getattr(request.app.state, "ingest_service", None)
    if not isinstance(service, IngestService):
        raise DependencyTransientError("Ingest is not configured.", reason="ingest_not_configured")
    return service


def _media_type(request: Request) -> str:
    return request.headers.get("content-type", "").split(";", 1)[0].strip().lower()


async def _read(
    request: Request, service: IngestService, *, media_types: tuple[str, ...]
) -> tuple[ProducerRegistration, bytes]:
    producer = service.authorize(request.headers.get("authorization"))
    if _media_type(request) not in media_types or request.headers.get(
        "content-encoding", "identity"
    ).lower() not in ("", "identity"):
        raise InvalidSchemaError(
            "Unsupported media type or content encoding.",
            reason=ReasonCode.UNSUPPORTED_MEDIA_TYPE,
        )
    limit = service.settings.max_body_bytes
    check_declared_length(request.headers.get("content-length"), limit)
    return producer, await read_limited(request.stream(), limit)


def build_router() -> APIRouter:
    router = APIRouter(tags=["ingest"])

    async def otlp(
        request: Request,
        call: Callable[[IngestService, ProducerRegistration, bytes], Awaitable[IngestResult]],
    ) -> IngestResult:
        service = _service(request)
        producer, raw = await _read(request, service, media_types=(_JSON,))
        return await call(service, producer, raw)

    @router.post("/otlp/traces", status_code=202, response_model=IngestResult)
    async def traces(request: Request) -> IngestResult:
        return await otlp(request, IngestService.ingest_otlp_traces)

    @router.post("/otlp/metrics", status_code=202, response_model=IngestResult)
    async def metrics(request: Request) -> IngestResult:
        return await otlp(request, IngestService.ingest_otlp_metrics)

    @router.post("/events", status_code=202, response_model=IngestResult)
    async def events(request: Request) -> IngestResult:
        service = _service(request)
        producer, raw = await _read(
            request,
            service,
            media_types=("application/cloudevents+json", "application/cloudevents-batch+json"),
        )
        return await service.ingest_events(producer, raw, request.headers["content-type"])

    return router


def register(registry: RouterRegistry) -> None:
    """Router-registry hook (see ``neurosphere_api/routers.py``)."""
    register_with_alias(registry, build_router(), prefix=ROUTE_PREFIX, alias_prefix=ALIAS_PREFIX)
