"""Azure billing export connector: read-only, advisory, bounded by the export manifest.

Reads one export run (``manifest.json`` plus its CSV partitions) and returns the rows and the
daily-per-resource-per-meter aggregates, with coverage = partitions read of partitions listed
and ``partial`` set when the parsed row count differs from the manifest's ``dataRowCount``.
Freshness lag is unknown (None): the documented export latency is "up to 24 hours" for a run to
complete, which is a maximum, not a measured lag. Government availability of Cost Management
exports is not verified here, so the manifest lists Commercial only (G04 stays OPEN).

Documentation (observed 2026-10-17):
https://learn.microsoft.com/azure/cost-management-billing/costs/tutorial-improved-exports
"""

from __future__ import annotations

from neurosphere_connector import BaseConnector, build_manifest
from neurosphere_connector.health import Clock, CoverageReport, FreshnessReport, utc_now
from neurosphere_contracts.connectors.v1.connector_manifest import (
    ConnectorManifest,
    Freshness,
    Granularity,
)
from pydantic import BaseModel, ConfigDict

from neurosphere_connector_azure_billing.export_reader import (
    AmountKind,
    BillingAggregate,
    CostBasis,
    ExportBlobSource,
    ExportReadResult,
    aggregate_daily,
    read_export,
)

__all__ = ["AzureBillingConnector", "BillingReadResult"]

DOCUMENTATION_URL = (
    "https://learn.microsoft.com/azure/cost-management-billing/costs/tutorial-improved-exports"
)
EXPORT_MAX_COMPLETION_MS = 24 * 60 * 60 * 1000  # documented: an export run can take up to 24 h


class BillingReadResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    export: ExportReadResult
    aggregates: list[BillingAggregate]


class AzureBillingConnector(BaseConnector):
    """Cost export reader. ``basis`` and ``amount_kind`` are declared by the operator."""

    def __init__(
        self,
        *,
        source: ExportBlobSource,
        basis: CostBasis,
        amount_kind: AmountKind = "estimated",
        clock: Clock = utc_now,
    ) -> None:
        super().__init__(clock=clock)
        self._source = source
        self._basis: CostBasis = basis
        self._amount_kind: AmountKind = amount_kind
        self._clock = clock

    @property
    def manifest(self) -> ConnectorManifest:
        return build_manifest(
            name="azure-billing-export",
            version="0.1.0",
            capabilities=["cost_ingest", "health_reporting"],
            supported_clouds=["commercial"],
            granularity=Granularity(time_grain="day", subject_level="unknown"),
            freshness=Freshness(typical_delay_ms=None, max_delay_ms=EXPORT_MAX_COMPLETION_MS),
            documentation_url=DOCUMENTATION_URL,
        )

    async def read(self) -> BillingReadResult:
        """Read one export run. Cost cells that are blank stay None."""
        return await self.guarded_call(
            self._read,
            freshness=lambda _r: FreshnessReport(lag_ms=None, observed_at=self._clock()),
            coverage=lambda r: CoverageReport(
                expected_sources=r.export.blobs_expected,
                answered_sources=r.export.blobs_read,
                partial=not r.export.complete,
            ),
        )

    async def _read(self) -> BillingReadResult:
        export = await read_export(self._source, basis=self._basis, amount_kind=self._amount_kind)
        return BillingReadResult(export=export, aggregates=aggregate_daily(export.rows))
