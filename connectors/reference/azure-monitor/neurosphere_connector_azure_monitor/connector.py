"""Azure Monitor bounded polling connector (Log Analytics and Application Insights query APIs).

Read-only and advisory. Each poll is bounded three ways: an explicit time window
(``PollBounds.max_window``), a page budget (``max_pages`` time slices, each queried against every
source) and a watermark. The query APIs have no cursor paging, so a "page" is one time slice. If
the budget runs out the result is ``partial`` and no further slice is fetched; the next poll
resumes from ``next_watermark``. The watermark only advances over slices every source answered.

Query text comes from fixed templates (``queries.py``); callers cannot supply KQL. Government
hosts are configuration only and unverified (see ``endpoints.py``); they need an explicit
``allow_unverified_government`` opt-in and never fall back to Commercial.

Throttling: HTTP 429 maps to ``RateLimitedError`` (health ``rate_limited``). ``Retry-After`` is
honored when it is a whole number of seconds not above ``max_backoff_s``; otherwise a bounded
exponential backoff is used, for at most ``max_attempts`` tries per request.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from neurosphere_connector import (
    BaseConnector,
    CoverageReport,
    CredentialBroker,
    FreshnessReport,
    build_manifest,
)
from neurosphere_connector.health import Clock, utc_now
from neurosphere_contracts.connectors.v1.connector_manifest import (
    ConnectorManifest,
    Granularity,
    RateLimit,
)
from neurosphere_core.cloud.profile import CloudName
from neurosphere_core.errors import (
    DependencyTransientError,
    ForbiddenError,
    InvalidSchemaError,
    NeuroSphereError,
    RateLimitedError,
    UnauthorizedError,
)
from neurosphere_core.payload import drop_body_fields

from neurosphere_connector_azure_monitor.auth import TokenProvider
from neurosphere_connector_azure_monitor.endpoints import MonitorEndpoints, endpoints_for
from neurosphere_connector_azure_monitor.queries import (
    MAX_ROWS,
    MonitorSource,
    SourceKind,
    template_for,
)

__all__ = ["AzureMonitorConnector", "PollBounds", "PollResult"]

Sleeper = Callable[[float], Awaitable[None]]
_DOC_URL = "https://learn.microsoft.com/en-us/azure/azure-monitor/logs/api/request-format"
_TIME_COLUMNS = ("TimeGenerated", "timestamp")


@dataclass(frozen=True)
class PollBounds:
    slice_length: timedelta = timedelta(minutes=15)
    max_pages: int = 4
    max_window: timedelta = timedelta(hours=6)
    initial_lookback: timedelta = timedelta(hours=1)
    # Safety margin so late rows are not skipped (a configured choice, not a documented SLA).
    ingestion_delay: timedelta = timedelta(minutes=5)
    max_attempts: int = 3
    base_backoff_s: float = 1.0
    max_backoff_s: float = 60.0

    def __post_init__(self) -> None:
        if self.max_pages < 1 or self.max_attempts < 1:
            raise ValueError("max_pages and max_attempts must be >= 1")
        if self.slice_length <= timedelta(0) or self.max_window <= timedelta(0):
            raise ValueError("slice_length and max_window must be positive")
        if self.initial_lookback > self.max_window:
            raise ValueError("initial_lookback must not exceed max_window")
        if self.base_backoff_s < 0 or self.max_backoff_s < 0:
            raise ValueError("backoff values must be >= 0")


@dataclass(frozen=True)
class PollResult:
    records: list[dict[str, Any]]
    next_watermark: datetime
    partial: bool
    pages_used: int
    page_budget: int
    requests_made: int
    coverage: CoverageReport
    freshness: FreshnessReport
    failed_sources: dict[str, str] = field(default_factory=dict)  # source_id -> error code
    truncated_pages: int = 0
    dropped_body_fields: dict[str, int] = field(default_factory=dict)


@dataclass
class _Page:
    rows: list[dict[str, Any]]
    partial: bool


def _retry_after(response: httpx.Response) -> int | None:
    raw = response.headers.get("Retry-After", "").strip()
    return int(raw) if raw.isdigit() else None


def _fmt(ts: datetime) -> str:
    return ts.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


class AzureMonitorConnector(BaseConnector):
    """Polls Log Analytics workspaces and Application Insights apps within fixed bounds."""

    def __init__(
        self,
        *,
        token_provider: TokenProvider,
        cloud: CloudName = CloudName.COMMERCIAL,
        allow_unverified_government: bool = False,
        bounds: PollBounds | None = None,
        client: httpx.AsyncClient | None = None,
        credentials: CredentialBroker | None = None,
        clock: Clock = utc_now,
        sleeper: Sleeper = asyncio.sleep,
    ) -> None:
        super().__init__(credentials=credentials, clock=clock)
        self._endpoints: MonitorEndpoints = endpoints_for(
            cloud, allow_unverified_government=allow_unverified_government
        )
        self._tokens = token_provider
        self._bounds = bounds or PollBounds()
        self._clock = clock
        self._sleep = sleeper
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(60.0))

    @property
    def manifest(self) -> ConnectorManifest:
        # Commercial only until Government host/scope are verified (see endpoints.py). No
        # credential refs: auth is managed identity via the injected token provider.
        return build_manifest(
            name="azure-monitor",
            version="0.1.0",
            capabilities=["telemetry_ingest", "health_reporting"],
            supported_clouds=["commercial"],
            granularity=Granularity(time_grain="minute", subject_level="unknown"),
            scopes=["Data.Read"],
            rate_limits=[
                RateLimit(limit_scope="per_principal", max_requests=200, window_ms=30_000)
            ],
            documentation_url=_DOC_URL,
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()
        await super().close()

    async def poll(
        self, sources: Sequence[MonitorSource], *, watermark: datetime | None = None
    ) -> PollResult:
        """Fetch at most ``max_pages`` slices after ``watermark``; health is updated either way."""
        return await self.guarded_call(
            lambda: self._poll(list(sources), watermark),
            freshness=lambda r: r.freshness,
            coverage=lambda r: r.coverage,
        )

    async def _poll(self, sources: list[MonitorSource], watermark: datetime | None) -> PollResult:
        b = self._bounds
        now = self._clock()
        horizon = now - b.ingestion_delay
        start = watermark or horizon - b.initial_lookback
        window_end = min(horizon, start + b.max_window)
        partial = window_end < horizon  # window cap hit: more data waits for the next poll
        records: list[dict[str, Any]] = []
        dropped: dict[str, int] = {}
        failed: dict[str, str] = {}
        pages = requests = truncated = 0
        cursor = start
        last_error: NeuroSphereError | None = None

        for _ in range(b.max_pages):
            if cursor >= window_end:
                break
            page_end = min(cursor + b.slice_length, window_end)
            page_rows: list[dict[str, Any]] = []
            page_failed: dict[str, str] = {}
            for src in sources:
                requests += 1
                try:
                    page = await self._query(src, cursor, page_end)
                except RateLimitedError:
                    raise
                except NeuroSphereError as exc:
                    page_failed[src.source_id] = exc.code
                    last_error = exc
                    continue
                truncated += page.partial
                for row in page.rows:
                    clean, counts = drop_body_fields(
                        {"source_kind": src.kind.value, "source_id": src.source_id, **row}
                    )
                    page_rows.append(clean)
                    for name, n in counts.items():
                        dropped[name] = dropped.get(name, 0) + n
            if page_failed:
                failed = page_failed
                if len(page_failed) == len(sources) and pages == 0 and last_error is not None:
                    raise last_error  # nothing answered at all: a failure, not a partial poll
                partial = True
                break  # do not advance past a slice some source did not answer
            records.extend(page_rows)
            pages += 1
            cursor = page_end

        # Page budget exhausted (cursor short of the window) or any truncated/partial page.
        partial = partial or cursor < window_end or truncated > 0
        expected = len(sources)
        coverage = CoverageReport(
            expected_sources=expected, answered_sources=expected - len(failed), partial=partial
        )
        return PollResult(
            records=records,
            next_watermark=cursor,
            partial=partial,
            pages_used=pages,
            page_budget=b.max_pages,
            requests_made=requests,
            coverage=coverage,
            freshness=self._freshness(records, now),
            failed_sources=failed,
            truncated_pages=truncated,
            dropped_body_fields=dropped,
        )

    @staticmethod
    def _freshness(records: list[dict[str, Any]], now: datetime) -> FreshnessReport:
        latest: datetime | None = None
        for rec in records:
            for col in _TIME_COLUMNS:
                ts = _parse_time(rec.get(col))
                if ts is not None and (latest is None or ts > latest):
                    latest = ts
        if latest is None:
            return FreshnessReport()  # unknown, never 0
        return FreshnessReport(
            lag_ms=max(0, int((now - latest).total_seconds() * 1000)),
            watermark=latest,
            observed_at=now,
        )

    async def _query(self, src: MonitorSource, start: datetime, end: datetime) -> _Page:
        ep = self._endpoints
        timespan = f"{_fmt(start)}/{_fmt(end)}"
        text = template_for(src.kind)
        if src.kind is not SourceKind.APP_INSIGHTS:  # workspace kinds, incl. APIM gateway and MCP
            scope = ep.log_analytics_scope
            url = f"{ep.log_analytics_base}/v1/workspaces/{src.source_id}/query"
            kwargs: dict[str, Any] = {"json": {"query": text, "timespan": timespan}}
        else:
            if ep.app_insights_base is None or ep.app_insights_scope is None:
                raise DependencyTransientError("app insights query host unavailable in this cloud")
            scope = ep.app_insights_scope
            url = f"{ep.app_insights_base}/v1/apps/{src.source_id}/query"
            kwargs = {"params": {"query": text, "timespan": timespan}}
        response = await self._send(url, scope, kwargs)
        return self._parse(response)

    async def _send(self, url: str, scope: str, kwargs: dict[str, Any]) -> httpx.Response:
        b = self._bounds
        delay = 0
        for attempt in range(b.max_attempts):
            token = await self._tokens(scope)  # fetched per call so rotation applies
            method = "POST" if "json" in kwargs else "GET"
            try:
                response = await self._client.request(
                    method, url, headers={"Authorization": f"Bearer {token}"}, **kwargs
                )
            except httpx.HTTPError as exc:
                raise DependencyTransientError("azure monitor request failed") from exc
            if response.status_code != 429:
                return self._check(response)
            header = _retry_after(response)
            delay = (
                header
                if header is not None
                else min(b.base_backoff_s * 2**attempt, b.max_backoff_s)
            )
            if delay > b.max_backoff_s or attempt == b.max_attempts - 1:
                break
            await self._sleep(delay)
        raise RateLimitedError(math.ceil(delay), "azure monitor throttled the query")

    @staticmethod
    def _check(response: httpx.Response) -> httpx.Response:
        code = response.status_code
        if code == 200:
            return response
        if code == 401:
            raise UnauthorizedError("azure monitor rejected the token")
        if code == 403:
            raise ForbiddenError("azure monitor denied access to the source")
        if code in (400, 404):
            raise InvalidSchemaError("azure monitor rejected the request or source")
        raise DependencyTransientError("azure monitor unavailable", upstream_invalid=code < 500)

    @staticmethod
    def _parse(response: httpx.Response) -> _Page:
        try:
            body = response.json()
            table = body["tables"][0]
            names = [str(c["name"]) for c in table["columns"]]
            raw_rows = table["rows"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise DependencyTransientError(
                "azure monitor returned an unreadable body", upstream_invalid=True
            ) from exc
        rows = [dict(zip(names, row, strict=False)) for row in raw_rows]
        error = body.get("error")
        partial_error = isinstance(error, dict) and error.get("code") == "PartialError"
        return _Page(rows=rows, partial=partial_error or len(rows) >= MAX_ROWS)
