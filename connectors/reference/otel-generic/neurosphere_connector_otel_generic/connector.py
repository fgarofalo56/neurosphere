"""``OtelGenericConnector``: push OTLP/JSON and CloudEvents to the PRP-07 ingest edge.

Wire format (matches the edge, no second format): OTLP/JSON to ``/otlp/traces`` and
``/otlp/metrics``, CloudEvents 1.0 structured-batch JSON to ``/events``. The edge maps OTLP to
``TelemetryEvent``; this connector never maps, so there is one mapping.

Behaviour:

* Bodies (prompt/response attributes) are dropped before send, always.
* The producer credential (``Bearer <producer_id>.<secret>``) is resolved through the
  ``CredentialBroker`` on every attempt, so rotation applies without a restart, and is revealed
  only when the header is built. It is never logged.
* Batches are bounded by item count and serialized size; requests are retried a bounded number
  of times (transport errors, 5xx, 429). The edge dedupes on deterministic ids, so a retry after
  a partial failure is safe. A 429 that outlasts the retries raises ``RateLimitedError`` and the
  health state becomes ``rate_limited``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from typing import Any, Final

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
    CredentialRef,
    Granularity,
)
from neurosphere_core.errors import (
    DependencyTransientError,
    ForbiddenError,
    InvalidSchemaError,
    RateLimitedError,
    UnauthorizedError,
)
from neurosphere_core.observability.redaction import RedactionFilter
from pydantic import BaseModel, ConfigDict, Field

from neurosphere_connector_otel_generic.convert import (
    readable_spans_to_otlp,
    redact_outgoing,
    validate_cloudevents,
)

__all__ = [
    "CLOUDEVENTS_SPEC_URL",
    "CREDENTIAL_NAME",
    "DEFAULT_CREDENTIAL_REF",
    "OTLP_SPEC_URL",
    "SPEC_OBSERVED_DATE",
    "OtelGenericConnector",
    "PushSummary",
]

OTLP_SPEC_URL: Final = "https://opentelemetry.io/docs/specs/otlp/"
CLOUDEVENTS_SPEC_URL: Final = "https://github.com/cloudevents/spec/blob/v1.0.2/cloudevents/spec.md"
SPEC_OBSERVED_DATE: Final = "2026-10-17"
CREDENTIAL_NAME: Final = "producer_credential"
DEFAULT_CREDENTIAL_REF: Final = CredentialRef(
    name=CREDENTIAL_NAME,
    vault_ref="https://ns-connectors.vault.azure.net/secrets/otel-producer-credential",
)

_CLOUD_BY_VAULT_HOST: Final = {
    "vault.azure.net": "commercial",
    "vault.usgovcloudapi.net": "government",
}
_RETRYABLE_STATUS: Final = frozenset({500, 502, 503, 504})
_JSON: Final = "application/json"
_EVENTS_BATCH: Final = "application/cloudevents-batch+json"

_log = logging.getLogger("neurosphere_connector_otel_generic")
_log.addFilter(RedactionFilter())

Sleep = Callable[[float], Awaitable[None]]


class PushSummary(BaseModel):
    """What the edge reported, summed over batches. Counts and reason codes only."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    requests: int = Field(ge=0)
    accepted: int = Field(ge=0)
    rejected: int = Field(ge=0)
    ignored: int = Field(ge=0)
    # Body fields removed (name -> count): by the connector before send plus by the edge.
    dropped_fields: dict[str, int] = Field(default_factory=dict)


def _manifest(ref: CredentialRef) -> ConnectorManifest:
    host = ref.vault_ref.removeprefix("https://").split("/", 1)[0]
    cloud = next((c for suffix, c in _CLOUD_BY_VAULT_HOST.items() if host.endswith(suffix)), None)
    return build_manifest(
        name="otel-generic",
        version="0.1.0",
        capabilities=["telemetry_ingest", "health_reporting"],
        supported_clouds=["government" if cloud == "government" else "commercial"],
        granularity=Granularity(time_grain="event", subject_level="request"),
        scopes=["telemetry:ingest"],
        credential_refs=[ref],
        documentation_url=OTLP_SPEC_URL,
    )


def _split(
    items: Sequence[Any],
    build: Callable[[Sequence[Any]], Any],
    *,
    max_items: int,
    max_bytes: int,
) -> list[bytes]:
    """Serialize ``items`` into bodies of at most ``max_items`` items and ``max_bytes`` bytes."""
    bodies: list[bytes] = []
    pending = [items[i : i + max_items] for i in range(0, len(items), max_items)]
    pending.reverse()
    while pending:
        chunk = pending.pop()
        body = json.dumps(build(chunk), separators=(",", ":")).encode("utf-8")
        if len(body) <= max_bytes:
            bodies.append(body)
        elif len(chunk) > 1:
            mid = len(chunk) // 2
            pending.append(chunk[mid:])
            pending.append(chunk[:mid])
        else:
            raise InvalidSchemaError("A single item exceeds the batch size limit.")
    return bodies


def _flatten(document: Any, outer: str, inner: str, leaf: str) -> list[tuple[Any, Any, Any]]:
    """OTLP ``outer[].inner[].leaf[]`` -> ``(outer_wrapper, inner_wrapper, leaf_item)`` triples."""
    triples: list[tuple[Any, Any, Any]] = []
    for o in document.get(outer) or []:
        for i in o.get(inner) or []:
            for item in i.get(leaf) or []:
                triples.append(
                    (
                        {k: v for k, v in o.items() if k != inner},
                        {k: v for k, v in i.items() if k != leaf},
                        item,
                    )
                )
    return triples


def _rebuild(triples: Sequence[tuple[Any, Any, Any]], outer: str, inner: str, leaf: str) -> Any:
    outers: list[dict[str, Any]] = []
    last_o: Any = None
    last_i: Any = None
    for o, i, item in triples:
        if last_o is None or o != last_o:
            outers.append({**o, inner: []})
            last_o, last_i = o, None
        if last_i is None or i != last_i:
            outers[-1][inner].append({**i, leaf: []})
            last_i = i
        outers[-1][inner][-1][leaf].append(item)
    return {outer: outers}


class OtelGenericConnector(BaseConnector):
    """Reference push connector for OpenTelemetry spans/metrics and CloudEvents."""

    def __init__(
        self,
        *,
        ingest_url: str,
        credentials: CredentialBroker,
        credential_ref: CredentialRef = DEFAULT_CREDENTIAL_REF,
        client: httpx.AsyncClient | None = None,
        customer_id: str | None = None,
        source_id: str | None = None,
        cloud: str | None = None,
        max_batch_items: int = 100,
        max_batch_bytes: int = 512 * 1024,
        max_attempts: int = 4,
        backoff_seconds: float = 0.5,
        max_sleep_seconds: float = 30.0,
        sleep: Sleep = asyncio.sleep,
        clock: Clock = utc_now,
    ) -> None:
        super().__init__(credentials=credentials, clock=clock)
        if max_batch_items < 1 or max_batch_bytes < 1 or max_attempts < 1:
            raise ValueError("batch and attempt limits must be at least 1")
        self._base = ingest_url.rstrip("/")
        self._ref = credential_ref
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(15.0))
        self._claims = {"customer_id": customer_id, "source_id": source_id, "cloud": cloud}
        self._max_items = max_batch_items
        self._max_bytes = max_batch_bytes
        self._max_attempts = max_attempts
        self._backoff = backoff_seconds
        self._max_sleep = max_sleep_seconds
        self._sleep = sleep
        self._now = clock

    @property
    def manifest(self) -> ConnectorManifest:
        return _manifest(self._ref)

    # -- public push API --------------------------------------------------------------------
    async def push_traces(self, document: Mapping[str, Any]) -> PushSummary:
        """Send an OTLP/JSON ``ExportTraceServiceRequest`` (bodies dropped, batches bounded)."""
        clean, dropped = redact_outgoing(dict(document))
        triples = _flatten(clean, "resourceSpans", "scopeSpans", "spans")
        bodies = _split(
            triples,
            lambda c: _rebuild(c, "resourceSpans", "scopeSpans", "spans"),
            max_items=self._max_items,
            max_bytes=self._max_bytes,
        )
        return await self._push("/otlp/traces", _JSON, bodies, dropped)

    async def push_metrics(self, document: Mapping[str, Any]) -> PushSummary:
        """Send an OTLP/JSON ``ExportMetricsServiceRequest`` (one metric per item)."""
        clean, dropped = redact_outgoing(dict(document))
        triples = _flatten(clean, "resourceMetrics", "scopeMetrics", "metrics")
        bodies = _split(
            triples,
            lambda c: _rebuild(c, "resourceMetrics", "scopeMetrics", "metrics"),
            max_items=self._max_items,
            max_bytes=self._max_bytes,
        )
        return await self._push("/otlp/metrics", _JSON, bodies, dropped)

    async def push_events(self, events: Sequence[Mapping[str, Any]]) -> PushSummary:
        """Send CloudEvents 1.0 (Pydantic-validated; not the ``cloudevents`` SDK) as a batch."""
        valid = validate_cloudevents(events)
        clean, dropped = redact_outgoing(valid)
        bodies = _split(clean, list, max_items=self._max_items, max_bytes=self._max_bytes)
        return await self._push("/events", _EVENTS_BATCH, bodies, dropped)

    async def export_spans(self, spans: Iterable[Any]) -> PushSummary:
        """Send ``opentelemetry-sdk`` ``ReadableSpan`` objects (what a SpanExporter receives)."""
        document = readable_spans_to_otlp(spans, **self._claims)
        return await self.push_traces(document)

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()
        await super().close()

    # -- transport --------------------------------------------------------------------------
    async def _push(
        self, path: str, content_type: str, bodies: list[bytes], dropped: dict[str, int]
    ) -> PushSummary:
        if not bodies:
            return PushSummary(
                requests=0, accepted=0, rejected=0, ignored=0, dropped_fields=dropped
            )

        async def run() -> PushSummary:
            accepted = rejected = ignored = 0
            total_dropped = dict(dropped)
            for body in bodies:
                result = await self._send(path, content_type, body)
                accepted += _count(result.get("accepted"))
                rejected += len(result.get("rejected") or [])
                ignored += len(result.get("ignored") or [])
                for name, count in (result.get("dropped_fields") or {}).items():
                    total_dropped[name] = total_dropped.get(name, 0) + _count(count)
            return PushSummary(
                requests=len(bodies),
                accepted=accepted,
                rejected=rejected,
                ignored=ignored,
                dropped_fields=total_dropped,
            )

        def freshness(_: PushSummary) -> FreshnessReport:
            # Lag is not measured by a push connector: unknown, never 0.
            return FreshnessReport(lag_ms=None, observed_at=self._now())

        def coverage(_: PushSummary) -> CoverageReport:
            return CoverageReport(
                expected_sources=len(bodies), answered_sources=len(bodies), partial=False
            )

        summary = await self.guarded_call(run, freshness=freshness, coverage=coverage)
        _log.info(
            "push complete",
            extra={"path": path, "requests": summary.requests, "accepted": summary.accepted},
        )
        return summary

    async def _send(self, path: str, content_type: str, body: bytes) -> dict[str, Any]:
        last: Exception | None = None
        for attempt in range(1, self._max_attempts + 1):
            secret = await self.credential(self._ref.name)
            headers = {
                "authorization": f"Bearer {secret.reveal()}",
                "content-type": content_type,
            }
            wait = self._backoff * 2 ** (attempt - 1)
            try:
                response = await self._client.post(self._base + path, content=body, headers=headers)
            except httpx.HTTPError:
                last = DependencyTransientError(
                    "The ingest edge could not be reached.", reason="ingest_unreachable"
                )
            else:
                status = response.status_code
                if 200 <= status < 300:
                    return _json_object(response)
                if status == 429:
                    retry_after = _retry_after(response)
                    last = RateLimitedError(retry_after, reason="ingest_rate_limited")
                    wait = float(retry_after)
                elif status in _RETRYABLE_STATUS:
                    last = DependencyTransientError(
                        "The ingest edge is temporarily unavailable.", reason="ingest_unavailable"
                    )
                else:
                    if status == 401 and self._credentials is not None:
                        # Rotated or revoked: drop the cached value so the next call re-resolves.
                        await self._credentials.notify_rotated(self._ref.name)
                    raise _terminal_error(status)
            if attempt < self._max_attempts:
                await self._sleep(min(wait, self._max_sleep))
        assert last is not None
        raise last


def _count(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _json_object(response: httpx.Response) -> dict[str, Any]:
    try:
        parsed = response.json()
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _retry_after(response: httpx.Response) -> int:
    raw = response.headers.get("retry-after", "")
    return int(raw) if raw.isdigit() else 1


def _terminal_error(status: int) -> Exception:
    if status == 401:
        return UnauthorizedError("The ingest edge rejected the producer credential.")
    if status == 403:
        return ForbiddenError("The ingest edge rejected the payload claims.")
    return InvalidSchemaError("The ingest edge rejected the request.", reason=f"edge_{status}")
