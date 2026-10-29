"""``GatewayPoller``: one tick polls every registered gateway's Log Analytics workspace.

Per gateway: build the connector for the gateway's cloud, compute the window from the stored
``poll_watermark`` (or the first-poll lookback), query ``APIM_GATEWAY`` and ``APIM_MCP``, map rows
to ``TelemetryEvent``s (gateway rows emit no ``CostRecord``: they carry no price, PRP-33 D2) and
post them to the ingest API as CloudEvents under the ``apim-gateway-poll`` producer. The connector
only returns records for slices every source answered, so the watermark advances to its
``next_watermark`` and a partial slice is simply re-polled on the next tick. Replays are safe:
the ingestion pipeline dedupes on ``(customer_id, source_id, event_id)``.

Nothing raises out of :meth:`GatewayPoller.tick` for an upstream failure (ARM/Log Analytics 429,
ingest 5xx, a bad row): the outcome is recorded as ``poll_status`` on the registration and the
next tick tries again. Only store outages propagate (the supervisor restarts the role).
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Protocol

import httpx
from neurosphere_connector_azure_monitor import (
    AzureMonitorConnector,
    ManagedIdentityTokenProvider,
    MonitorSource,
    PollBounds,
    PollResult,
    SourceKind,
    map_gateway_row,
    map_mcp_row,
)
from neurosphere_contracts.telemetry.v1.telemetry_event import TelemetryEvent
from neurosphere_core.cloud.profile import CloudName
from neurosphere_core.errors import NeuroSphereError, RateLimitedError, StaleVersionError
from neurosphere_core.gateway.models import GatewayRegistration
from neurosphere_core.gateway.store import GatewayStore
from neurosphere_core.payload import CLOUDEVENT_TYPE_TELEMETRY

from neurosphere_workers.ingestion.gateway_poll.settings import GatewayPollSettings

__all__ = [
    "STATUS_CLOUD_MISMATCH",
    "STATUS_INGEST_FAILED",
    "STATUS_OK",
    "STATUS_PARTIAL",
    "STATUS_REFUSED_GOVERNMENT",
    "ConnectorFactory",
    "GatewayPoller",
    "IngestClient",
    "MonitorPort",
    "default_connector_factory",
]

logger = logging.getLogger("neurosphere.workers.gateway_poll")

STATUS_OK: Final = "ok"
STATUS_PARTIAL: Final = "partial"
STATUS_REFUSED_GOVERNMENT: Final = "refused_government_unverified"
STATUS_CLOUD_MISMATCH: Final = "cloud_mismatch"
STATUS_INGEST_FAILED: Final = "ingest_failed"
_INGEST_PATH: Final = "/api/v1/ingest/events"
_BATCH_MEDIA_TYPE: Final = "application/cloudevents-batch+json"
_SLICE: Final = timedelta(minutes=15)
_PAGE_SIZE: Final = 100


class MonitorPort(Protocol):
    """What the poller needs from the Azure Monitor connector (a fake in tests)."""

    async def poll(
        self, sources: Sequence[MonitorSource], *, watermark: datetime | None = None
    ) -> PollResult: ...

    async def close(self) -> None: ...


ConnectorFactory = Callable[[str, PollBounds], MonitorPort]
"""``(cloud, bounds) -> connector``. The Government opt-in is checked before this is called."""


class _OwnedConnector:
    """The real connector plus the managed-identity credential it was given."""

    def __init__(self, cloud: CloudName, bounds: PollBounds, allow_government: bool) -> None:
        self._tokens = ManagedIdentityTokenProvider(cloud)
        self._connector = AzureMonitorConnector(
            token_provider=self._tokens,
            cloud=cloud,
            allow_unverified_government=allow_government,
            bounds=bounds,
        )

    async def poll(
        self, sources: Sequence[MonitorSource], *, watermark: datetime | None = None
    ) -> PollResult:
        return await self._connector.poll(sources, watermark=watermark)

    async def close(self) -> None:
        await self._connector.close()
        await self._tokens.aclose()


def default_connector_factory(allow_unverified_government: bool) -> ConnectorFactory:
    def make(cloud: str, bounds: PollBounds) -> MonitorPort:
        return _OwnedConnector(CloudName(cloud), bounds, allow_unverified_government)

    return make


class IngestPostError(Exception):
    """The ingest API did not accept a batch. Carries the status only, never headers or body."""

    def __init__(self, status: int | None) -> None:
        super().__init__(f"ingest_post_failed:{status}")
        self.status = status


class IngestClient:
    """Posts CloudEvents batches to the ingest API as one registered producer."""

    def __init__(
        self, client: httpx.AsyncClient, *, base_url: str, producer_id: str, secret: str
    ) -> None:
        self._client = client
        self._url = base_url.rstrip("/") + _INGEST_PATH
        self._authorization = f"Bearer {producer_id}.{secret}"

    async def post(self, events: Sequence[Mapping[str, Any]]) -> int:
        """Post one batch; the number of events the API accepted. Raises ``IngestPostError``."""
        try:
            response = await self._client.post(
                self._url,
                json=list(events),
                headers={
                    "Authorization": self._authorization,
                    "Content-Type": _BATCH_MEDIA_TYPE,
                },
            )
        except httpx.HTTPError:
            raise IngestPostError(None) from None
        if response.status_code != 202:
            raise IngestPostError(response.status_code)
        try:
            body = response.json()
            accepted = int(body.get("accepted", 0))
            rejected = len(body.get("rejected", []))
        except (ValueError, AttributeError, TypeError):
            return len(events)
        if rejected:
            logger.warning(
                "ingest rejected polled events",
                extra={"event": "gateway_poll.rejected", "rejected": rejected},
            )
        return accepted


@dataclass(frozen=True, slots=True)
class _Outcome:
    status: str
    watermark: datetime | None = None
    freshness_seconds: int | None = None
    coverage: float | None = None


def _cloud_event(event: TelemetryEvent) -> dict[str, Any]:
    data = event.model_dump(mode="json", exclude_none=True)
    return {
        "specversion": "1.0",
        "id": data["event_id"],
        "source": "neurosphere/gateway-poll",
        "type": CLOUDEVENT_TYPE_TELEMETRY,
        "datacontenttype": "application/json",
        "data": data,
    }


class GatewayPoller:
    def __init__(
        self,
        *,
        store: GatewayStore,
        ingest: IngestClient,
        settings: GatewayPollSettings,
        customer_id: str,
        domain_ids: Sequence[str],
        cloud: str,
        connector_factory: ConnectorFactory,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._store = store
        self._ingest = ingest
        self._settings = settings
        self._customer_id = customer_id
        self._domain_ids = tuple(domain_ids)
        self._cloud = cloud
        self._factory = connector_factory
        self._clock = clock

    async def tick(self) -> None:
        for domain_id in self._domain_ids:
            for gateway in await self._registrations(domain_id):
                if gateway.workspace_id is None:
                    continue  # no Log Analytics workspace discovered for this gateway yet
                await self._poll_one(gateway)

    async def _registrations(self, domain_id: str) -> list[GatewayRegistration]:
        found: list[GatewayRegistration] = []
        cursor: str | None = None
        while True:
            page = await self._store.list(
                self._customer_id, domain_id, cursor=cursor, limit=_PAGE_SIZE
            )
            found.extend(page.items)
            cursor = page.next_cursor
            if cursor is None:
                return found

    async def _poll_one(self, gateway: GatewayRegistration) -> None:
        try:
            outcome = await self._run(gateway)
        except Exception as exc:  # a poll must never crash the role
            logger.warning(
                "gateway poll failed",
                extra={
                    "event": "gateway_poll.failed",
                    "gateway_id": gateway.id,
                    "error": type(exc).__name__,
                },
            )
            outcome = _Outcome(status=f"poll_failed:{type(exc).__name__}"[:64])
        await self._record(gateway, outcome)

    async def _run(self, gateway: GatewayRegistration) -> _Outcome:
        if gateway.cloud != self._cloud:
            # Never bridge clouds: this worker's producer is registered for one cloud only.
            return _Outcome(status=STATUS_CLOUD_MISMATCH)
        if gateway.cloud == "government" and not self._settings.allow_unverified_government:
            logger.warning(
                "government gateway not polled: unverified opt-in not set",
                extra={"event": "gateway_poll.refused", "gateway_id": gateway.id},
            )
            return _Outcome(status=STATUS_REFUSED_GOVERNMENT)
        assert gateway.workspace_id is not None
        now = self._clock()
        cfg = self._settings
        watermark = gateway.poll_watermark or now - timedelta(seconds=cfg.lookback_seconds)
        bounds = PollBounds(
            slice_length=_SLICE,
            max_pages=max(1, math.ceil(cfg.window_seconds / _SLICE.total_seconds())),
            max_window=timedelta(seconds=cfg.window_seconds),
            initial_lookback=timedelta(0),
        )
        connector = self._factory(gateway.cloud, bounds)
        try:
            result = await connector.poll(
                [
                    MonitorSource(SourceKind.APIM_GATEWAY, gateway.workspace_id),
                    MonitorSource(SourceKind.APIM_MCP, gateway.workspace_id),
                ],
                watermark=watermark,
            )
        except RateLimitedError:
            return _Outcome(status="rate_limited")
        except NeuroSphereError as exc:
            return _Outcome(status=f"poll_failed:{exc.code}"[:64])
        finally:
            await connector.close()

        events = self._events(gateway, result)
        try:
            for start in range(0, len(events), cfg.batch_size):
                await self._ingest.post(events[start : start + cfg.batch_size])
        except IngestPostError as exc:
            # Nothing is acknowledged: the watermark stays, the window is re-polled and the
            # pipeline dedupes whatever did land.
            logger.warning(
                "ingest post failed",
                extra={"event": "gateway_poll.ingest_failed", "status": exc.status},
            )
            return _Outcome(status=STATUS_INGEST_FAILED)

        fraction = result.coverage.fraction
        full = fraction == 1.0 and not result.partial
        if not full:
            logger.info(
                "gateway poll partial; unanswered slices are re-polled next tick",
                extra={
                    "event": "gateway_poll.partial",
                    "gateway_id": gateway.id,
                    "failed_sources": sorted(result.failed_sources.values()),
                },
            )
        lag_ms = result.freshness.lag_ms
        return _Outcome(
            status=STATUS_OK if full else STATUS_PARTIAL,
            watermark=result.next_watermark,
            freshness_seconds=None if lag_ms is None else lag_ms // 1000,
            coverage=fraction,
        )

    def _events(self, gateway: GatewayRegistration, result: PollResult) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        skipped = 0
        for row in result.records:
            kind = row.get("source_kind")
            try:
                if kind == SourceKind.APIM_GATEWAY.value:
                    telemetry = map_gateway_row(
                        row,
                        cloud=gateway.cloud,
                        customer_id=gateway.customer_id,
                        source_id=self._settings.source_id,
                        domain_id=gateway.domain_id,
                    ).telemetry  # the unpriced cost side is deliberately not posted (D2)
                elif kind == SourceKind.APIM_MCP.value:
                    telemetry = map_mcp_row(
                        row,
                        cloud=gateway.cloud,
                        customer_id=gateway.customer_id,
                        source_id=self._settings.source_id,
                        domain_id=gateway.domain_id,
                    ).telemetry
                else:
                    skipped += 1
                    continue
            except ValueError:
                skipped += 1
                continue
            events.append(_cloud_event(telemetry))
        if skipped:
            logger.warning(
                "rows skipped: unmappable",
                extra={"event": "gateway_poll.skipped", "count": skipped},
            )
        return events

    async def _record(self, gateway: GatewayRegistration, outcome: _Outcome) -> None:
        current = gateway
        for attempt in range(2):
            if current.etag is None:
                return
            updated = _apply(current, outcome, self._clock())
            try:
                await self._store.replace(updated, if_match=current.etag)
                return
            except StaleVersionError:
                if attempt == 1:
                    logger.warning(
                        "gateway registration changed concurrently; poll result dropped",
                        extra={"event": "gateway_poll.stale", "gateway_id": gateway.id},
                    )
                    return
                fresh = await self._store.get(gateway.customer_id, gateway.domain_id, gateway.id)
                if fresh is None:
                    return
                current = fresh


def _apply(gateway: GatewayRegistration, outcome: _Outcome, now: datetime) -> GatewayRegistration:
    changes: dict[str, Any] = {"poll_status": outcome.status, "updated_at": now}
    watermark = outcome.watermark
    if watermark is not None and (
        gateway.poll_watermark is None or watermark > gateway.poll_watermark
    ):
        changes["poll_watermark"] = watermark
    if watermark is not None:
        if outcome.freshness_seconds is not None:
            changes["freshness_seconds"] = outcome.freshness_seconds
        if outcome.coverage is not None:
            changes["coverage"] = outcome.coverage
    return gateway.model_copy(update=changes)
