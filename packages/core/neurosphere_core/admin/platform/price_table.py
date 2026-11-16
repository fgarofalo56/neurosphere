"""Merge stored price snapshots with a file price table into one ledger ``PriceTable``.

Equal ``price_version_id`` with identical content collapses to one version; equal ids with
different content refuse startup with ``price_version_conflict`` (never a silent pick). A snapshot
that does not apply to the deployment cloud is skipped (Commercial prices are never a Government
fallback). Messages carry ids only, never a price.
"""

from __future__ import annotations

from collections.abc import Iterable

from neurosphere_core.ledger.prices import PriceTable, PriceVersion
from neurosphere_core.pricing.models import PriceSnapshot

__all__ = ["PriceVersionConflictError", "merge_price_tables"]


class PriceVersionConflictError(ValueError):
    """Two price versions share an id but differ in content."""

    reason = "price_version_conflict"

    def __init__(self, price_version_id: str) -> None:
        super().__init__(f"price_version_conflict: {price_version_id}")
        self.price_version_id = price_version_id


def merge_price_tables(
    snapshots: Iterable[PriceSnapshot],
    file_table: PriceTable | None,
    *,
    cloud: str | None = None,
) -> PriceTable:
    """File versions first, then each applicable snapshot's version."""
    by_id: dict[str, PriceVersion] = {}
    candidates: list[PriceVersion] = list(file_table.versions) if file_table is not None else []
    candidates += [s.to_price_version() for s in snapshots if cloud is None or s.applies_to(cloud)]
    for version in candidates:
        existing = by_id.get(version.price_version_id)
        if existing is None:
            by_id[version.price_version_id] = version
        elif existing != version:
            raise PriceVersionConflictError(version.price_version_id)
    return PriceTable(list(by_id.values()))
