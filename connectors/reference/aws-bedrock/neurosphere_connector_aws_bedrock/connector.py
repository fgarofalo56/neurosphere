"""AWS Bedrock metadata connector: read-only, advisory, Commercial only, bounded.

One instance reads one AWS account and one region. It returns the Bedrock inventory (foundation
models, custom models, provisioned throughput, guardrails, agents), hourly CloudWatch usage per
model, daily Cost Explorer amounts for the Bedrock service, and whether model invocation logging
is configured (destination types only). It never invokes a model and never reads a prompt, a
response, a log or an object; the reader protocol has no such operation and the typed outputs
have no field that could hold one. The verified API table is in ``reader.py``.

A source list is ``None`` (unknown) when its call failed, never ``[]``. Each list is capped at
``max_items``; hitting the cap (or the reader's page budget) sets ``truncated`` and partial
coverage. A missing CloudWatch or Cost Explorer datapoint is ``None``, never ``0``. Freshness lag
is unknown (``None``): CloudWatch and Cost Explorer publish no delay guarantee that this
connector could measure.

A Government NeuroSphere deployment refuses the connector at construction with the typed
``capability_unavailable`` error and reason ``aws_bedrock_government_unsupported``; nothing is
read and no request is made. GovCloud regions are refused the same way.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from neurosphere_connector import BaseConnector
from neurosphere_connector.health import Clock, CoverageReport, FreshnessReport, utc_now
from neurosphere_contracts.connectors.v1.connector_manifest import ConnectorManifest, CredentialRef
from neurosphere_core.cloud.profile import CloudName
from neurosphere_core.errors import CapabilityUnavailableError, NeuroSphereError

from neurosphere_connector_aws_bedrock.manifest import AuthMode, build_aws_bedrock_manifest
from neurosphere_connector_aws_bedrock.models import (
    MAX_MODEL_IDS,
    USAGE_METRICS,
    BedrockCostPoint,
    BedrockCostResult,
    BedrockInventory,
    BedrockUsagePoint,
    BedrockUsageResult,
    CostWindow,
    InventoryItem,
    InvocationLoggingState,
    UsageWindow,
    clip,
)
from neurosphere_connector_aws_bedrock.reader import INVENTORY_SOURCES, BedrockReader, ReaderPage

__all__ = [
    "DEFAULT_COST_SERVICES",
    "DEFAULT_MAX_ITEMS",
    "GOVERNMENT_REASON",
    "AwsBedrockConnector",
]

GOVERNMENT_REASON = "aws_bedrock_government_unsupported"
DEFAULT_MAX_ITEMS = 500
DEFAULT_MAX_POINTS = 20_000
#: Cost Explorer ``SERVICE`` dimension value for Bedrock (documented example in the AWS docs).
DEFAULT_COST_SERVICES = ("Amazon Bedrock",)
_REGION_RE = re.compile(r"^[a-z]{2}(-[a-z]+)+-[0-9]$")
_MAX_MODALITIES = 16


def _refuse(detail: str) -> CapabilityUnavailableError:
    return CapabilityUnavailableError(GOVERNMENT_REASON, detail)


def _utc(value: Any) -> datetime | None:
    if isinstance(value, datetime) and value.tzinfo is not None:
        return value.astimezone(UTC)
    return None


def _modalities(value: Any) -> list[str] | None:
    if not isinstance(value, (list, tuple)):
        return None
    out = [s for s in (clip(v, 64) for v in value[:_MAX_MODALITIES]) if s is not None]  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
    return out


def _item(raw: Mapping[str, Any]) -> InventoryItem | None:
    """Whitelisted fields only: any other key a reader passes is ignored here."""
    ident = clip(raw.get("id"))
    if ident is None:
        return None
    return InventoryItem(
        id=ident,
        name=clip(raw.get("name")),
        status=clip(raw.get("status"), 64),
        provider=clip(raw.get("provider")),
        input_modalities=_modalities(raw.get("input_modalities")),
        output_modalities=_modalities(raw.get("output_modalities")),
        created_at=_utc(raw.get("created_at")),
    )


def _items(page: ReaderPage, limit: int) -> tuple[list[InventoryItem], bool]:
    built = [i for i in (_item(r) for r in page.items) if i is not None]
    if len(built) > limit:
        return built[:limit], True
    return built, page.truncated


class AwsBedrockConnector(BaseConnector):
    """Metadata reader for one account and region. The reader owns the credential path."""

    def __init__(
        self,
        *,
        reader: BedrockReader,
        cloud: CloudName,
        region: str,
        max_items: int = DEFAULT_MAX_ITEMS,
        max_points: int = DEFAULT_MAX_POINTS,
        cost_services: Sequence[str] = DEFAULT_COST_SERVICES,
        auth_mode: AuthMode = "workload_identity_federation",
        credential_refs: Sequence[CredentialRef] = (),
        clock: Clock = utc_now,
    ) -> None:
        # Refuse before anything else, so no reader call or request can follow.
        if cloud is not CloudName.COMMERCIAL:
            raise _refuse("AWS Bedrock is Commercial only; a Government deployment refuses it")
        if region.startswith(("us-gov-", "cn-")) or not _REGION_RE.match(region):
            raise _refuse("only AWS commercial-partition regions are supported")
        if max_items < 1 or max_points < 1:
            raise ValueError("max_items and max_points must be at least 1")
        if not cost_services:
            raise ValueError("cost_services must not be empty")
        super().__init__(clock=clock)
        self._reader = reader
        self._region = region
        self._max_items = max_items
        self._max_points = max_points
        self._cost_services = tuple(cost_services)
        self._manifest = build_aws_bedrock_manifest(
            auth_mode=auth_mode, credential_refs=credential_refs
        )
        self._clock = clock

    @property
    def manifest(self) -> ConnectorManifest:
        return self._manifest

    @property
    def region(self) -> str:
        return self._region

    def __repr__(self) -> str:
        return f"AwsBedrockConnector(region={self._region!r})"

    # ------------------------------------------------------------------ inventory

    async def inventory(self) -> BedrockInventory:
        """One bounded inventory pass; raises only if every source failed."""
        return await self.guarded_call(
            self._inventory,
            freshness=lambda r: FreshnessReport(lag_ms=None, observed_at=r.observed_at),
            coverage=lambda r: CoverageReport(
                expected_sources=len(INVENTORY_SOURCES),
                answered_sources=len(INVENTORY_SOURCES) - len(r.failed_sources),
                partial=bool(r.failed_sources or r.truncated),
            ),
        )

    async def _inventory(self) -> BedrockInventory:
        readers: dict[str, Callable[..., Any]] = {
            "foundation_models": self._reader.list_foundation_models,
            "custom_models": self._reader.list_custom_models,
            "provisioned_throughput": self._reader.list_provisioned_throughput,
            "guardrails": self._reader.list_guardrails,
            "agents": self._reader.list_agents,
        }
        lists: dict[str, list[InventoryItem] | None] = {}
        failed: dict[str, str] = {}
        truncated: list[str] = []
        last_error: NeuroSphereError | None = None
        for source in INVENTORY_SOURCES:
            try:
                page: ReaderPage = await readers[source](limit=self._max_items)
            except NeuroSphereError as exc:
                lists[source] = None
                failed[source] = exc.code
                last_error = exc
                continue
            items, cut = _items(page, self._max_items)
            lists[source] = items
            if cut:
                truncated.append(source)
        if len(failed) == len(INVENTORY_SOURCES) and last_error is not None:
            raise last_error
        return BedrockInventory.model_validate(
            {
                "region": self._region,
                "observed_at": self._clock(),
                "truncated": truncated,
                "failed_sources": failed,
                **lists,
            }
        )

    # ------------------------------------------------------------------ usage

    async def usage(self, window: UsageWindow, model_ids: Sequence[str]) -> BedrockUsageResult:
        """Hourly invocation and token counts per model for an explicit window.

        Every (model, metric, hour) cell is returned; one CloudWatch did not report is ``None``.
        """
        ids = list(dict.fromkeys(m for m in model_ids if m))
        if not ids:
            raise ValueError("model_ids must not be empty")
        if len(ids) > MAX_MODEL_IDS:
            raise ValueError(f"at most {MAX_MODEL_IDS} model ids per call")
        return await self.guarded_call(
            lambda: self._usage(window, ids),
            freshness=lambda r: FreshnessReport(lag_ms=None, observed_at=r.observed_at),
            coverage=lambda r: CoverageReport(
                expected_sources=1, answered_sources=1, partial=r.truncated
            ),
        )

    async def _usage(self, window: UsageWindow, model_ids: list[str]) -> BedrockUsageResult:
        page = await self._reader.get_usage(
            model_ids=model_ids, window=window, limit=self._max_points
        )
        reported: dict[tuple[str, str, datetime], float] = {}
        for raw in page.items:
            model_id = clip(raw.get("model_id"))
            metric = raw.get("metric")
            hour = _utc(raw.get("hour"))
            value = raw.get("value")
            if (
                model_id is None
                or metric not in USAGE_METRICS
                or hour is None
                or isinstance(value, bool)
                or not isinstance(value, (int, float))
            ):
                continue
            reported[(model_id, metric, hour)] = float(value)
        hours = window.hours()
        points: list[BedrockUsagePoint] = []
        cut = page.truncated
        for model_id in model_ids:
            for metric in USAGE_METRICS:
                for hour in hours:
                    if len(points) >= self._max_points:
                        cut = True
                        break
                    points.append(
                        BedrockUsagePoint(
                            model_id=model_id,
                            metric=metric,
                            hour=hour,
                            value=reported.get((model_id, metric, hour)),
                        )
                    )
        return BedrockUsageResult(
            region=self._region,
            observed_at=self._clock(),
            window=window,
            points=points,
            truncated=cut,
        )

    # ------------------------------------------------------------------ cost

    async def cost(self, window: CostWindow) -> BedrockCostResult:
        """Daily Cost Explorer amounts for the Bedrock service(s); no price is computed.

        A service-day with no row is returned with ``amount=None`` rather than as zero.
        """
        return await self.guarded_call(
            lambda: self._cost(window),
            freshness=lambda r: FreshnessReport(lag_ms=None, observed_at=r.observed_at),
            coverage=lambda r: CoverageReport(
                expected_sources=1, answered_sources=1, partial=r.truncated
            ),
        )

    async def _cost(self, window: CostWindow) -> BedrockCostResult:
        page = await self._reader.get_cost(
            window=window, services=self._cost_services, limit=self._max_points
        )
        rows: dict[tuple[date, str], BedrockCostPoint] = {}
        for raw in page.items:
            day, service = raw.get("day"), clip(raw.get("service"))
            if not isinstance(day, date) or isinstance(day, datetime) or service is None:
                continue
            amount: Decimal | None
            try:
                text = raw.get("amount")
                amount = Decimal(text) if isinstance(text, str) else None
            except InvalidOperation:
                amount = None
            estimated = raw.get("estimated")
            kind = (
                None
                if not isinstance(estimated, bool)
                else "estimated"
                if estimated
                else "invoiced"
            )
            rows[(day, service)] = BedrockCostPoint(
                day=day,
                service=service,
                amount=amount if amount is None or amount.is_finite() else None,
                currency=clip(raw.get("currency"), 16),
                amount_kind=kind,
            )
        points: list[BedrockCostPoint] = []
        for day in window.days():
            for service in self._cost_services:
                points.append(
                    rows.get((day, service)) or BedrockCostPoint(day=day, service=service)
                )
        cut = page.truncated
        if len(points) > self._max_points:
            points, cut = points[: self._max_points], True
        return BedrockCostResult(
            region=self._region,
            observed_at=self._clock(),
            window=window,
            points=points,
            truncated=cut,
        )

    # ------------------------------------------------------------------ logging setting

    async def logging_state(self) -> InvocationLoggingState:
        """Whether invocation logging is configured: a boolean and destination types only."""
        return await self.guarded_call(
            self._logging_state,
            freshness=lambda r: FreshnessReport(lag_ms=None, observed_at=r.observed_at),
            coverage=lambda _r: CoverageReport(expected_sources=1, answered_sources=1),
        )

    async def _logging_state(self) -> InvocationLoggingState:
        raw = await self._reader.get_invocation_logging()
        cloudwatch = raw.get("cloudwatch") is True
        s3 = raw.get("s3") is True
        return InvocationLoggingState(
            region=self._region,
            observed_at=self._clock(),
            configured=cloudwatch or s3,
            cloudwatch=cloudwatch,
            s3=s3,
        )

    async def close(self) -> None:
        await self._reader.close()
        await super().close()
