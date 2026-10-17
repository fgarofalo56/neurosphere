"""Reader for Azure Cost Management export files (CSV, optionally gzip) in blob storage.

Documented format (observed 2026-10-17):

- Every export run writes data partitions plus a ``manifest.json`` listing ``blobs[].blobName``,
  ``dataRowCount``, ``deliveryConfig.fileFormat`` (``Csv``/``Parquet``) and
  ``deliveryConfig.compressionMode`` (``None``/``Gzip``). Each partition has its own header row.
  https://learn.microsoft.com/azure/cost-management-billing/costs/tutorial-improved-exports
- Cost columns (``Date``, ``CostInBillingCurrency``, ``BillingCurrencyCode``, ``ResourceId``,
  ``MeterId``, ``SubscriptionId`` ...); ``Date`` is the usage date in ``yyyy-mm-dd``.
  https://learn.microsoft.com/azure/cost-management-billing/automate/understand-usage-details-fields
- Actual and amortized cost are separate export datasets; the file itself does not say which, so
  the caller declares ``basis``. The export manifest ``type`` is kept verbatim, not interpreted.

Rules enforced here:

- Granularity is what the export reports: one row per usage day per resource per meter. Rows
  are only ever rolled up to a coarser key; nothing is apportioned below a row.
- A blank or unparseable cost is ``None`` (unknown), never 0. An aggregate whose contributing
  rows include an unknown cost is itself unknown (``cost=None``) and says how many were unknown.
- ``basis`` (actual vs amortized) and ``amount_kind`` (estimated vs invoiced) are distinct
  fields and rows of different basis/kind/currency are never merged. An export is
  ``estimated`` unless the operator asserts ``invoiced`` for a closed billing period; the file
  carries no per-row invoice status.
- Parquet is not supported (``capability_unavailable``); no new dependency is taken for it.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, Protocol

from neurosphere_core.errors import CapabilityUnavailableError, InvalidSchemaError
from pydantic import BaseModel, ConfigDict

__all__ = [
    "AmountKind",
    "BillingAggregate",
    "CostBasis",
    "CostRow",
    "ExportBlobSource",
    "ExportReadResult",
    "aggregate_daily",
    "parse_cost_csv",
    "read_export",
]

CostBasis = Literal["actual", "amortized"]
AmountKind = Literal["estimated", "invoiced"]

# Header aliases. The first match wins; matching is case-insensitive. The MCA-style names come
# first; the others appear in other documented cost-details schema variants.
_ALIASES: dict[str, tuple[str, ...]] = {
    "date": ("date", "usagedate"),
    "cost": ("costinbillingcurrency", "pretaxcost", "cost"),
    "currency": ("billingcurrencycode", "billingcurrency", "currency"),
    "resource_id": ("resourceid", "instanceid"),
    "meter_id": ("meterid",),
    "meter_name": ("metername",),
    "subscription_id": ("subscriptionid", "subscriptionguid"),
}


class CostRow(BaseModel):
    """One export row at the export's own granularity. Unknown cells are None."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    usage_date: date | None = None
    resource_id: str | None = None
    meter_id: str | None = None
    meter_name: str | None = None
    subscription_id: str | None = None
    currency: str | None = None
    cost: Decimal | None = None
    basis: CostBasis
    amount_kind: AmountKind


class BillingAggregate(BaseModel):
    """Daily per resource per meter total in one currency. ``cost`` None = unknown."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    usage_date: date
    resource_id: str | None
    meter_id: str | None
    currency: str | None
    basis: CostBasis
    amount_kind: AmountKind
    cost: Decimal | None
    row_count: int
    null_cost_rows: int


@dataclass
class _ParseStats:
    rows_read: int = 0
    rows_without_date: int = 0
    rows_with_unknown_cost: int = 0
    rows_with_bad_cost: int = 0


class ExportReadResult(BaseModel):
    """Rows plus the honest accounting of what was and was not readable."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    rows: list[CostRow]
    manifest_type: str | None = None
    manifest_row_count: int | None = None
    rows_read: int
    rows_without_date: int
    rows_with_unknown_cost: int
    rows_with_bad_cost: int
    blobs_read: int
    blobs_expected: int | None
    complete: bool
    granularity: str = "day per resource per meter (as reported by the export)"


class ExportBlobSource(Protocol):
    """Blob access the reader needs; production uses ``AzureBlobExportSource``."""

    async def read_manifest(self) -> bytes: ...

    async def read_blob(self, name: str) -> bytes: ...


def _norm(h: str) -> str:
    return h.strip().lstrip("\ufeff").replace(" ", "").replace("_", "").lower()


def _column_map(headers: Iterable[str]) -> dict[str, str | None]:
    by_norm = {_norm(h): h for h in headers}
    return {
        field_name: next((by_norm[a] for a in aliases if a in by_norm), None)
        for field_name, aliases in _ALIASES.items()
    }


def _cell(row: Mapping[str, str | None], col: str | None) -> str | None:
    if col is None:
        return None
    value = row.get(col)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _parse_date(value: str | None) -> date | None:
    if value is None:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(value[:10] if fmt == "%Y-%m-%d" else value, fmt).date()
        except ValueError:
            continue
    return None


def _parse_cost(value: str | None) -> tuple[Decimal | None, bool]:
    """Return (cost, was_present_but_unparseable). Blank -> (None, False)."""
    if value is None:
        return None, False
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        return None, True
    if not parsed.is_finite():
        return None, True
    return parsed, False


def parse_cost_csv(
    text: str,
    *,
    basis: CostBasis,
    amount_kind: AmountKind = "estimated",
    stats: _ParseStats | None = None,
) -> list[CostRow]:
    """Parse one export partition. Missing/blank/garbled cost -> None (never 0)."""
    stats = stats if stats is not None else _ParseStats()
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        return []
    cols = _column_map(reader.fieldnames)
    if cols["cost"] is None and cols["date"] is None:
        raise InvalidSchemaError("export has neither a date nor a cost column")
    rows: list[CostRow] = []
    for raw in reader:
        stats.rows_read += 1
        usage_date = _parse_date(_cell(raw, cols["date"]))
        cost, bad = _parse_cost(_cell(raw, cols["cost"]))
        if usage_date is None:
            stats.rows_without_date += 1
        if cost is None:
            stats.rows_with_unknown_cost += 1
        if bad:
            stats.rows_with_bad_cost += 1
        currency = _cell(raw, cols["currency"])
        rows.append(
            CostRow(
                usage_date=usage_date,
                resource_id=_cell(raw, cols["resource_id"]),
                meter_id=_cell(raw, cols["meter_id"]),
                meter_name=_cell(raw, cols["meter_name"]),
                subscription_id=_cell(raw, cols["subscription_id"]),
                currency=currency.upper() if currency else None,
                cost=cost,
                basis=basis,
                amount_kind=amount_kind,
            )
        )
    return rows


def aggregate_daily(rows: Iterable[CostRow]) -> list[BillingAggregate]:
    """Roll rows up to (day, resource, meter, currency, basis, kind). Rows without a date are
    excluded (they cannot be placed on a day); the caller sees them in ``rows_without_date``.
    Any unknown contributing cost makes the aggregate cost unknown."""
    groups: dict[tuple[Any, ...], list[CostRow]] = {}
    for r in rows:
        if r.usage_date is None:
            continue
        key = (r.usage_date, r.resource_id, r.meter_id, r.currency, r.basis, r.amount_kind)
        groups.setdefault(key, []).append(r)
    out: list[BillingAggregate] = []
    for key in sorted(groups, key=lambda k: tuple("" if p is None else str(p) for p in k)):
        members = groups[key]
        nulls = sum(1 for m in members if m.cost is None)
        total: Decimal | None = None
        if nulls == 0:
            total = sum((m.cost for m in members if m.cost is not None), Decimal(0))
        out.append(
            BillingAggregate(
                usage_date=key[0],
                resource_id=key[1],
                meter_id=key[2],
                currency=key[3],
                basis=key[4],
                amount_kind=key[5],
                cost=total,
                row_count=len(members),
                null_cost_rows=nulls,
            )
        )
    return out


@dataclass
class _ManifestInfo:
    type: str | None = None
    row_count: int | None = None
    file_format: str | None = None
    compression: str | None = None
    blobs: list[str] = field(default_factory=lambda: [])


def _read_manifest(raw: bytes) -> _ManifestInfo:
    try:
        doc = json.loads(raw)
    except ValueError:
        raise InvalidSchemaError("export manifest is not valid JSON") from None
    if not isinstance(doc, dict) or not isinstance(doc.get("blobs"), list):
        raise InvalidSchemaError("export manifest has no blobs list")
    d: dict[str, Any] = doc  # pyright: ignore[reportUnknownVariableType]
    delivery: Any = d.get("deliveryConfig")
    export: Any = d.get("exportConfig")
    info = _ManifestInfo()
    if isinstance(delivery, dict):
        info.file_format = delivery.get("fileFormat")  # pyright: ignore[reportUnknownMemberType]
        info.compression = delivery.get("compressionMode")  # pyright: ignore[reportUnknownMemberType]
    if isinstance(export, dict):
        info.type = export.get("type")  # pyright: ignore[reportUnknownMemberType]
    count = d.get("dataRowCount")
    info.row_count = count if isinstance(count, int) else None
    for blob in d["blobs"]:
        name = blob.get("blobName") if isinstance(blob, dict) else None  # pyright: ignore[reportUnknownMemberType]
        if isinstance(name, str):
            info.blobs.append(name.strip())
    return info


async def read_export(
    source: ExportBlobSource,
    *,
    basis: CostBasis,
    amount_kind: AmountKind = "estimated",
) -> ExportReadResult:
    """Read every partition named by the manifest and report completeness honestly."""
    info = _read_manifest(await source.read_manifest())
    if (info.file_format or "Csv").lower() != "csv":
        raise CapabilityUnavailableError(
            "export_format_unsupported", "only CSV exports are read; Parquet is not supported"
        )
    compression = (info.compression or "None").lower()
    if compression not in ("none", "gzip"):
        raise CapabilityUnavailableError("export_compression_unsupported")
    stats = _ParseStats()
    rows: list[CostRow] = []
    for name in info.blobs:
        data = await source.read_blob(name)
        if compression == "gzip":
            data = gzip.decompress(data)
        rows.extend(
            parse_cost_csv(
                data.decode("utf-8-sig"), basis=basis, amount_kind=amount_kind, stats=stats
            )
        )
    blobs_expected = len(info.blobs)
    complete = info.row_count is None or info.row_count == stats.rows_read
    return ExportReadResult(
        rows=rows,
        manifest_type=info.type,
        manifest_row_count=info.row_count,
        rows_read=stats.rows_read,
        rows_without_date=stats.rows_without_date,
        rows_with_unknown_cost=stats.rows_with_unknown_cost,
        rows_with_bad_cost=stats.rows_with_bad_cost,
        blobs_read=len(info.blobs),
        blobs_expected=blobs_expected,
        complete=complete,
    )
