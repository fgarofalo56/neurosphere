"""Ingest service: all edge logic, unit-testable without HTTP. Handlers only call this.

Order of work for one request: authenticate (401) -> edge/registration cloud match (403) ->
rate limit (429) -> [router reads the body under the size cap] -> depth scan -> parse ->
drop prompt/response bodies -> verify claims (403, nothing published) -> map and validate each
item (invalid items rejected individually) -> publish the valid ones -> result.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from neurosphere_contracts.cost.v1.cost_record import CostRecord
from neurosphere_contracts.telemetry.v1.telemetry_event import TelemetryEvent
from neurosphere_core.errors import ForbiddenError, InvalidSchemaError
from neurosphere_core.payload import (
    CLOUDEVENT_TYPE_COST,
    CLOUDEVENT_TYPE_TELEMETRY,
    HubMessage,
    HubMessageKind,
    drop_body_fields,
)
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from neurosphere_api.ingest import otlp_mapping as om
from neurosphere_api.ingest.auth import Authenticator, ProducerRegistration
from neurosphere_api.ingest.cloudevents import BATCH_MEDIA_TYPE, STRUCTURED_MEDIA_TYPE, CloudEvent
from neurosphere_api.ingest.limits import TokenBucketLimiter, check_depth
from neurosphere_api.ingest.publisher import Publisher
from neurosphere_api.ingest.reasons import ReasonCode
from neurosphere_api.ingest.settings import IngestSettings


class RejectedItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    index: int
    reason_code: ReasonCode


class IgnoredItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    reason_code: ReasonCode


class IngestResult(BaseModel):
    """202 body. Counts and reason codes only; never payload values."""

    model_config = ConfigDict(extra="forbid")
    accepted: int
    rejected: list[RejectedItem] = Field(default_factory=list)
    ignored: list[IgnoredItem] = Field(default_factory=list)
    dropped_fields: dict[str, int] = Field(default_factory=dict)


def _utc_z(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def _forbidden(reason: ReasonCode) -> ForbiddenError:
    return ForbiddenError("Payload claims do not match the producer registration.", reason=reason)


def resolve_scope(producer: ProducerRegistration, claims: om.Claims) -> om.Scope:
    """Check payload claims against the registration. Absent claims are filled from it."""
    if claims.customer_id is not None and claims.customer_id != producer.customer_id:
        raise _forbidden(ReasonCode.CLAIM_MISMATCH)
    if claims.cloud is not None and claims.cloud != producer.cloud:
        raise _forbidden(ReasonCode.CLAIM_MISMATCH)
    source = claims.source_id
    if source is None:
        if len(producer.sources) != 1:
            raise _forbidden(ReasonCode.CLAIM_MISMATCH)
        source = next(iter(producer.sources))
    elif source not in producer.sources:
        raise _forbidden(ReasonCode.CLAIM_MISMATCH)
    return om.Scope(cloud=producer.cloud, customer_id=producer.customer_id, source_id=source)


class IngestService:
    def __init__(
        self,
        *,
        settings: IngestSettings,
        edge_cloud: str,
        authenticator: Authenticator,
        publisher: Publisher,
        limiter: TokenBucketLimiter,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.settings = settings
        self._edge_cloud = edge_cloud
        self._authenticator = authenticator
        self._publisher = publisher
        self._limiter = limiter
        self._now = now

    # -- admission -------------------------------------------------------------------------
    def authorize(self, authorization: str | None) -> ProducerRegistration:
        producer = self._authenticator.authenticate(authorization)
        if producer.cloud != self._edge_cloud:
            # Never accept Government data on a Commercial edge (or the reverse).
            raise _forbidden(ReasonCode.CLOUD_MISMATCH)
        self._limiter.acquire(producer.producer_id)
        return producer

    # -- parsing ---------------------------------------------------------------------------
    def _parse(self, raw: bytes) -> tuple[Any, dict[str, int]]:
        check_depth(raw, self.settings.max_depth)
        try:
            parsed = json.loads(raw)
        except (ValueError, RecursionError) as exc:
            raise InvalidSchemaError(
                "Body is not valid JSON.", reason=ReasonCode.MALFORMED_JSON
            ) from exc
        return drop_body_fields(parsed)

    @staticmethod
    def _envelope_error() -> InvalidSchemaError:
        return InvalidSchemaError("Unexpected document shape.", reason=ReasonCode.INVALID_ENVELOPE)

    @staticmethod
    def _list_of(container: Any, key: str) -> list[Any]:
        value = container.get(key) if isinstance(container, Mapping) else None
        if value is None:
            return []
        if not isinstance(value, list):
            raise IngestService._envelope_error()
        return value

    def _message(
        self,
        producer: ProducerRegistration,
        *,
        kind: HubMessageKind,
        event_id: str,
        scope: om.Scope,
        received_at: str,
        request_id: str | None,
        data: dict[str, Any],
    ) -> HubMessage:
        return HubMessage(
            kind=kind,
            event_id=event_id,
            cloud=producer.cloud,
            customer_id=producer.customer_id,
            source_id=scope.source_id,
            producer_id=producer.producer_id,
            received_at=received_at,
            request_id=request_id,
            observation_kind=producer.sources[scope.source_id],
            data=data,
        )

    def _telemetry_message(
        self, producer: ProducerRegistration, scope: om.Scope, event: TelemetryEvent, at: str
    ) -> HubMessage:
        return self._message(
            producer,
            kind=HubMessageKind.TELEMETRY,
            event_id=event.event_id.root,
            scope=scope,
            received_at=at,
            request_id=event.request_id.root if event.request_id else None,
            data=event.model_dump(mode="json"),
        )

    async def _finish(
        self,
        messages: list[HubMessage],
        rejected: list[RejectedItem],
        ignored: list[IgnoredItem],
        dropped: dict[str, int],
    ) -> IngestResult:
        if messages:
            await self._publisher.publish(messages)
        return IngestResult(
            accepted=len(messages), rejected=rejected, ignored=ignored, dropped_fields=dropped
        )

    # -- OTLP traces -----------------------------------------------------------------------
    async def ingest_otlp_traces(self, producer: ProducerRegistration, raw: bytes) -> IngestResult:
        doc, dropped = self._parse(raw)
        received_at = _utc_z(self._now())
        messages: list[HubMessage] = []
        rejected: list[RejectedItem] = []
        index = 0
        for resource_spans in self._list_of(doc, "resourceSpans"):
            resource = (
                resource_spans.get("resource") if isinstance(resource_spans, Mapping) else None
            )
            scope = resolve_scope(producer, om.resource_claims(resource))
            for scope_spans in self._list_of(resource_spans, "scopeSpans"):
                for span in self._list_of(scope_spans, "spans"):
                    try:
                        event = om.map_span(span, scope, received_at)
                        messages.append(
                            self._telemetry_message(producer, scope, event, received_at)
                        )
                    except om.MappingError as exc:
                        rejected.append(RejectedItem(index=index, reason_code=exc.reason))
                    index += 1
        return await self._finish(messages, rejected, [], dropped)

    # -- OTLP metrics ----------------------------------------------------------------------
    async def ingest_otlp_metrics(self, producer: ProducerRegistration, raw: bytes) -> IngestResult:
        doc, dropped = self._parse(raw)
        received_at = _utc_z(self._now())
        messages: list[HubMessage] = []
        rejected: list[RejectedItem] = []
        ignored: list[IgnoredItem] = []
        index = 0
        for r, resource_metrics in enumerate(self._list_of(doc, "resourceMetrics")):
            resource = (
                resource_metrics.get("resource") if isinstance(resource_metrics, Mapping) else None
            )
            scope = resolve_scope(producer, om.resource_claims(resource))
            for s, scope_metrics in enumerate(self._list_of(resource_metrics, "scopeMetrics")):
                for m, metric in enumerate(self._list_of(scope_metrics, "metrics")):
                    path = f"resourceMetrics/{r}/scopeMetrics/{s}/metrics/{m}"
                    points, why = self._metric_points(metric)
                    if why is not None:
                        ignored.append(IgnoredItem(path=path, reason_code=why))
                        continue
                    for point in points:
                        try:
                            event = om.map_metric_point(
                                str(metric["name"]), point, scope, received_at
                            )
                            messages.append(
                                self._telemetry_message(producer, scope, event, received_at)
                            )
                        except om.MappingError as exc:
                            rejected.append(RejectedItem(index=index, reason_code=exc.reason))
                        index += 1
        return await self._finish(messages, rejected, ignored, dropped)

    @staticmethod
    def _metric_points(metric: Any) -> tuple[list[Any], ReasonCode | None]:
        if not isinstance(metric, Mapping):
            return [], ReasonCode.UNSUPPORTED_METRIC_TYPE
        kind = om.metric_kind(metric)
        if kind not in ("sum", "gauge"):
            return [], ReasonCode.UNSUPPORTED_METRIC_TYPE
        if metric.get("name") not in om.TOKEN_METRICS:
            return [], ReasonCode.UNMAPPED_METRIC_NAME
        body = metric[kind]
        if kind == "sum" and (
            not isinstance(body, Mapping)
            or body.get("aggregationTemporality") not in (2, "AGGREGATION_TEMPORALITY_DELTA")
        ):
            # Cumulative sums would be double counted downstream, so only deltas are mapped.
            return [], ReasonCode.UNSUPPORTED_TEMPORALITY
        points = body.get("dataPoints") if isinstance(body, Mapping) else None
        return (points if isinstance(points, list) else []), None

    # -- CloudEvents -----------------------------------------------------------------------
    async def ingest_events(
        self, producer: ProducerRegistration, raw: bytes, content_type: str
    ) -> IngestResult:
        media = content_type.split(";", 1)[0].strip().lower()
        if media not in (STRUCTURED_MEDIA_TYPE, BATCH_MEDIA_TYPE):
            raise InvalidSchemaError(
                "Unsupported media type.", reason=ReasonCode.UNSUPPORTED_MEDIA_TYPE
            )
        doc, dropped = self._parse(raw)
        if media == BATCH_MEDIA_TYPE:
            if not isinstance(doc, list):
                raise self._envelope_error()
            items: list[Any] = doc
        else:
            if not isinstance(doc, dict):
                raise self._envelope_error()
            items = [doc]

        received_at = _utc_z(self._now())
        messages: list[HubMessage] = []
        rejected: list[RejectedItem] = []
        for index, item in enumerate(items):
            try:
                messages.append(self._cloudevent_message(producer, item, received_at))
            except om.MappingError as exc:
                rejected.append(RejectedItem(index=index, reason_code=exc.reason))
        return await self._finish(messages, rejected, [], dropped)

    def _cloudevent_message(
        self, producer: ProducerRegistration, item: Any, received_at: str
    ) -> HubMessage:
        try:
            event = CloudEvent.model_validate(item)
        except ValidationError as exc:
            raise om.MappingError(ReasonCode.INVALID_CLOUDEVENT) from exc
        if event.type not in (CLOUDEVENT_TYPE_TELEMETRY, CLOUDEVENT_TYPE_COST):
            raise om.MappingError(ReasonCode.UNSUPPORTED_EVENT_TYPE)
        if event.data is None:
            raise om.MappingError(ReasonCode.INVALID_EVENT)
        data = dict(event.data)

        def text(name: str) -> str | None:
            value = data.get(name)
            return value if isinstance(value, str) else None

        # Claims are checked on the raw data before schema validation; a mismatch is a 403 for
        # the whole request (raised out of the loop), not a per-item rejection.
        claims = om.Claims(text("customer_id"), text("source_id"), text("cloud"))
        for name in ("customer_id", "source_id", "cloud"):
            if name in data and not isinstance(data[name], str):
                raise om.MappingError(ReasonCode.INVALID_EVENT)
        scope = resolve_scope(producer, claims)
        data.update(cloud=scope.cloud, customer_id=scope.customer_id, source_id=scope.source_id)

        try:
            if event.type == CLOUDEVENT_TYPE_TELEMETRY:
                data["ingestion_time"] = received_at
                telemetry = TelemetryEvent.model_validate(data)
                return self._telemetry_message(producer, scope, telemetry, received_at)
            if data.get("observation_source") not in (None, producer.sources[scope.source_id]):
                raise _forbidden(ReasonCode.CLAIM_MISMATCH)
            cost = CostRecord.model_validate(data)
        except ValidationError as exc:
            raise om.MappingError(ReasonCode.INVALID_EVENT) from exc
        return self._message(
            producer,
            kind=HubMessageKind.COST,
            event_id=cost.cost_id.root,
            scope=scope,
            received_at=received_at,
            request_id=event.request_id,
            data=cost.model_dump(mode="json"),
        )
