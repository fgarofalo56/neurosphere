"""Price sheet upload: conversion to a ``PriceSnapshot``, coverage report, append-only upload.

An operator uploads a :class:`PriceSheetUpload`; the server builds the snapshot with
``build_snapshot`` (which stamps the content hash, so an upload can never assert its own) and
appends it to the existing ``price_snapshots`` store (idempotent on an equal hash, a conflict on
the same id with another hash). Rows are NOT duplicated into ``admin_config``: the snapshot store
is the single source of truth (a 10 000-row sheet would not fit a Cosmos item twice).

The coverage report says which models a sheet prices (input and output present), which it cannot
(only one side: ``PriceSnapshot.to_price_version`` leaves those out), and how many rows carry no
token meter. Incomplete models are a warning, never a rejection.

Nothing here logs: price rows are commercially sensitive.
"""

from __future__ import annotations

import asyncio
import builtins
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Final, cast

from neurosphere_contracts.admin.v1.price_sheet_upload import PriceSheetRow, PriceSheetUpload
from pydantic import ValidationError

from neurosphere_core.admin.models import CloudName
from neurosphere_core.errors import InvalidSchemaError, StaleVersionError, ValidationIssue
from neurosphere_core.pricing.models import (
    Cloud,
    PriceRow,
    PriceSnapshot,
    TokenMeter,
    build_snapshot,
)
from neurosphere_core.pricing.store import PriceSnapshotStore, SnapshotConflictError

__all__ = [
    "CoverageReport",
    "IncompleteModel",
    "PriceSheetAdmin",
    "PriceSheetResult",
    "coverage_report",
    "price_sheet_to_snapshot",
]

_DEFAULT_PRICE_TYPE: Final = "Consumption"


def _issue(pointer: str, detail: str, reason: str) -> InvalidSchemaError:
    return InvalidSchemaError(
        "price sheet is invalid", errors=[ValidationIssue(pointer, detail)], reason=reason
    )


def _row(row: PriceSheetRow) -> PriceRow:
    meter = row.token_meter
    return PriceRow(
        service_name=row.service_name.root,
        sku_name=row.sku_name.root,
        meter_id=row.meter_id.root if row.meter_id is not None else None,
        meter_name=row.meter_name.root if row.meter_name is not None else None,
        arm_region_name=row.arm_region_name.root if row.arm_region_name is not None else None,
        unit_of_measure=row.unit_of_measure.root,
        retail_price=Decimal(row.retail_price.root),
        unit_price=Decimal(row.unit_price.root) if row.unit_price is not None else None,
        price_type=row.price_type.root if row.price_type is not None else _DEFAULT_PRICE_TYPE,
        effective_start_date=(
            date.fromisoformat(row.effective_start_date.root)
            if row.effective_start_date is not None
            else None
        ),
        token_meter=None
        if meter is None
        else TokenMeter(
            provider=meter.provider.root,
            model=meter.model.root,
            model_version=meter.model_version.root if meter.model_version is not None else None,
            kind=meter.kind,
        ),
    )


def price_sheet_to_snapshot(upload: PriceSheetUpload) -> PriceSnapshot:
    """The content-hashed snapshot for ``upload``; ``invalid_schema`` when a core rule refuses it.

    Messages never echo a price.
    """
    try:
        return build_snapshot(
            snapshot_id=upload.snapshot_id.root,
            source=upload.source,
            source_url=upload.source_url.root,
            retrieval_date=date.fromisoformat(upload.retrieval_date.root),
            effective_date=date.fromisoformat(upload.effective_date.root),
            currency=upload.currency.root,
            clouds=cast("tuple[Cloud, ...]", tuple(c.root for c in upload.clouds)),
            rows=[_row(r) for r in upload.rows],
            synthetic=upload.synthetic,
            notes=upload.notes,
        )
    except (ValidationError, ValueError) as exc:
        raise _issue("/", "sheet violates a pricing rule", "price_sheet_invalid") from exc


@dataclass(frozen=True, slots=True)
class IncompleteModel:
    provider: str
    model: str
    model_version: str | None
    missing: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CoverageReport:
    """Counts and names only; never a price."""

    snapshot_id: str
    rows: int
    models_priced: int
    models_incomplete: tuple[IncompleteModel, ...] = field(default_factory=tuple)
    rows_without_token_meter: int = 0

    @property
    def warnings(self) -> tuple[str, ...]:
        out: list[str] = []
        if self.models_incomplete:
            out.append("models_incomplete")
        if self.models_priced == 0:
            out.append("no_model_priced")
        return tuple(out)


def coverage_report(snapshot: PriceSnapshot) -> CoverageReport:
    kinds: dict[tuple[str, str, str | None], set[str]] = {}
    without_meter = 0
    for row in snapshot.rows:
        meter = row.token_meter
        if meter is None:
            without_meter += 1
            continue
        kinds.setdefault((meter.provider, meter.model, meter.model_version), set()).add(meter.kind)
    priced = 0
    incomplete: list[IncompleteModel] = []
    for (provider, model, version), present in sorted(
        kinds.items(), key=lambda item: (item[0][0], item[0][1], item[0][2] or "")
    ):
        missing = tuple(side for side in ("input", "output") if side not in present)
        if missing:
            incomplete.append(IncompleteModel(provider, model, version, missing))
        else:
            priced += 1
    return CoverageReport(
        snapshot_id=snapshot.snapshot_id,
        rows=len(snapshot.rows),
        models_priced=priced,
        models_incomplete=tuple(incomplete),
        rows_without_token_meter=without_meter,
    )


@dataclass(frozen=True, slots=True)
class PriceSheetResult:
    snapshot: PriceSnapshot
    #: False when the same snapshot (equal hash) was already stored (idempotent upload).
    created: bool
    coverage: CoverageReport


class PriceSheetAdmin:
    """Upload and read price sheets through the (sync) snapshot store, off the event loop."""

    def __init__(
        self, store: PriceSnapshotStore, *, cloud: CloudName, allow_synthetic: bool = False
    ) -> None:
        self._store = store
        self._cloud: CloudName = cloud
        self._allow_synthetic = allow_synthetic

    def _check(self, upload: PriceSheetUpload) -> None:
        if self._cloud not in {c.root for c in upload.clouds}:
            raise _issue("/clouds", "sheet does not apply to this cloud", "cross_cloud")
        if upload.synthetic and not self._allow_synthetic:
            raise _issue(
                "/synthetic", "synthetic sheets are refused outside local", "synthetic_refused"
            )

    async def upload(self, upload: PriceSheetUpload) -> PriceSheetResult:
        self._check(upload)
        snapshot = price_sheet_to_snapshot(upload)
        try:
            created = await asyncio.to_thread(self._store.put, snapshot)
        except SnapshotConflictError as exc:
            raise StaleVersionError(
                "snapshot id already exists with different content", reason="snapshot_conflict"
            ) from exc
        return PriceSheetResult(snapshot, created, coverage_report(snapshot))

    async def get(self, snapshot_id: str) -> PriceSnapshot | None:
        snapshot = await asyncio.to_thread(self._store.get, snapshot_id)
        if snapshot is None or not snapshot.applies_to(self._cloud):
            return None
        return snapshot

    async def list(self) -> builtins.list[PriceSnapshot]:
        return await asyncio.to_thread(self._store.list_snapshots, self._cloud)
