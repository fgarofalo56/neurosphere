"""Append-only price snapshot store and resolution by effective date.

``put`` rules (decided and tested):

* New ``snapshot_id`` -> stored, returns ``True``.
* Same ``snapshot_id`` AND same ``content_hash`` -> idempotent no-op, returns ``False`` (a retried
  refresh job must not fail, and nothing changes).
* Same ``snapshot_id`` but a different ``content_hash`` -> ``SnapshotConflictError``; the stored
  snapshot is untouched. A changed price list is a NEW snapshot with a new id.

There is no delete or update. Resolution mirrors the ledger price table: the newest snapshot whose
``effective_date <= on`` AND that applies to the requested cloud wins (id breaks ties
deterministically). A snapshot that does not list the cloud is never a fallback.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol, runtime_checkable

from neurosphere_core.ledger.prices import PriceVersion, Rate
from neurosphere_core.pricing.models import PriceSnapshot


class SnapshotConflictError(ValueError):
    """A snapshot id was re-used with different content."""


@dataclass(frozen=True, slots=True)
class ResolvedTokenPrice:
    snapshot: PriceSnapshot
    version: PriceVersion
    rate: Rate


@runtime_checkable
class PriceSnapshotStore(Protocol):
    def put(self, snapshot: PriceSnapshot) -> bool: ...

    def get(self, snapshot_id: str) -> PriceSnapshot | None: ...

    def list_snapshots(self, cloud: str | None = None) -> list[PriceSnapshot]:
        """Newest effective date first."""
        ...

    def resolve(self, cloud: str, on: date) -> PriceSnapshot | None: ...

    def resolve_token_price(
        self,
        cloud: str,
        provider: str | None,
        model: str | None,
        model_version: str | None,
        on: date,
    ) -> ResolvedTokenPrice | None: ...


class InMemoryPriceSnapshotStore:
    def __init__(self, snapshots: list[PriceSnapshot] | None = None) -> None:
        self._by_id: dict[str, PriceSnapshot] = {}
        self._versions: dict[str, PriceVersion] = {}
        for snapshot in snapshots or []:
            self.put(snapshot)

    def put(self, snapshot: PriceSnapshot) -> bool:
        existing = self._by_id.get(snapshot.snapshot_id)
        if existing is not None:
            if existing.content_hash == snapshot.content_hash:
                return False
            raise SnapshotConflictError(
                f"snapshot {snapshot.snapshot_id!r} already exists with a different content_hash"
            )
        self._by_id[snapshot.snapshot_id] = snapshot
        return True

    def get(self, snapshot_id: str) -> PriceSnapshot | None:
        return self._by_id.get(snapshot_id)

    def list_snapshots(self, cloud: str | None = None) -> list[PriceSnapshot]:
        items = [s for s in self._by_id.values() if cloud is None or s.applies_to(cloud)]
        return sorted(items, key=lambda s: (s.effective_date, s.snapshot_id), reverse=True)

    def resolve(self, cloud: str, on: date) -> PriceSnapshot | None:
        for snapshot in self.list_snapshots(cloud):
            if snapshot.effective_date <= on:
                return snapshot
        return None

    def resolve_token_price(
        self,
        cloud: str,
        provider: str | None,
        model: str | None,
        model_version: str | None,
        on: date,
    ) -> ResolvedTokenPrice | None:
        if provider is None or model is None:
            return None
        for snapshot in self.list_snapshots(cloud):
            if snapshot.effective_date > on:
                continue
            version = self._version(snapshot)
            rate = version.rate_for(provider, model, model_version)
            if rate is not None:
                return ResolvedTokenPrice(snapshot, version, rate)
        return None

    def _version(self, snapshot: PriceSnapshot) -> PriceVersion:
        cached = self._versions.get(snapshot.snapshot_id)
        if cached is None:
            cached = snapshot.to_price_version()
            self._versions[snapshot.snapshot_id] = cached
        return cached
