"""Cosmos NoSQL price snapshot store (azure-cosmos SYNC client), PRP-29 item 2.

Unlike the other Cosmos stores this one uses the synchronous ``azure.cosmos`` client: the existing
``PriceSnapshotStore`` protocol is synchronous (``put``/``get``/``resolve`` return values, not
awaitables) and its callers (the right-sizing projection) call it without ``await``. The protocol
is not changed here; a caller on an event loop should run these calls in a thread.

Container ``price_snapshots``: partition key ``/snapshot_id`` (``Hash``), the registry's choice
(Cosmos ids are unique only within a logical partition, so keying by the id keeps the
put-conflict rule exact). One document per snapshot: the ``PriceSnapshot`` JSON dump plus
``id`` = ``snapshot_id``. Snapshots are append-only:

* ``put``: a point read; equal ``content_hash`` -> ``False``, differing ->
  ``SnapshotConflictError``, absent -> create-only (a racing 409 re-checks the same way).
* ``get``: a single point read.
* ``list_snapshots`` / ``resolve``: one bounded cross-partition query (``TOP`` ``MAX_SNAPSHOTS``).
  Snapshot counts are tiny (one per refresh). A store holding more than ``MAX_SNAPSHOTS``
  snapshots in the queried range fails loudly rather than resolving against a truncated list.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Final, NoReturn

from azure.cosmos import ContainerProxy, CosmosClient, DatabaseProxy, PartitionKey
from azure.cosmos.exceptions import (
    CosmosHttpResponseError,
    CosmosResourceExistsError,
    CosmosResourceNotFoundError,
)
from pydantic import ValidationError

from neurosphere_core.errors import (
    DependencyTransientError,
    NeuroSphereError,
    RateLimitedError,
)
from neurosphere_core.ledger.prices import PriceVersion
from neurosphere_core.pricing.models import PriceSnapshot
from neurosphere_core.pricing.store import ResolvedTokenPrice, SnapshotConflictError

__all__ = [
    "DEFAULT_PRICE_SNAPSHOT_CONTAINER",
    "MAX_SNAPSHOTS",
    "PRICE_SNAPSHOT_PARTITION_KEY_PATH",
    "CosmosPriceSnapshotStore",
    "create_price_snapshot_container",
]

DEFAULT_PRICE_SNAPSHOT_CONTAINER: Final = "price_snapshots"
PRICE_SNAPSHOT_PARTITION_KEY_PATH: Final = "/snapshot_id"
MAX_SNAPSHOTS: Final = 1_000


def create_price_snapshot_container(
    database: DatabaseProxy, container_id: str = DEFAULT_PRICE_SNAPSHOT_CONTAINER
) -> ContainerProxy:
    """Create (or open) the price snapshot container (sync client)."""
    return database.create_container_if_not_exists(
        id=container_id, partition_key=PartitionKey(path=PRICE_SNAPSHOT_PARTITION_KEY_PATH)
    )


def _unavailable() -> DependencyTransientError:
    return DependencyTransientError(
        "price snapshot store unavailable", reason="price_snapshot_store_unavailable"
    )


def _invalid() -> DependencyTransientError:
    return DependencyTransientError(
        "stored price snapshot failed validation",
        reason="price_snapshot_record_invalid",
        upstream_invalid=True,
    )


def _raise_mapped(exc: Exception) -> NoReturn:
    if isinstance(exc, NeuroSphereError):
        raise exc
    if isinstance(exc, CosmosHttpResponseError) and exc.status_code == 429:
        raise RateLimitedError(1, "price snapshot store throttled the request") from exc
    raise _unavailable() from exc


def _from_row(row: dict[str, Any]) -> PriceSnapshot:
    document = {k: v for k, v in row.items() if not k.startswith("_") and k != "id"}
    try:
        return PriceSnapshot.model_validate(document)
    except ValidationError as exc:
        raise _invalid() from exc


class CosmosPriceSnapshotStore:
    """:class:`neurosphere_core.pricing.store.PriceSnapshotStore` on one container."""

    def __init__(self, container: ContainerProxy) -> None:
        self._container = container
        self._versions: dict[str, PriceVersion] = {}

    @classmethod
    def from_client(
        cls,
        client: CosmosClient,
        *,
        database: str,
        container: str = DEFAULT_PRICE_SNAPSHOT_CONTAINER,
    ) -> CosmosPriceSnapshotStore:
        return cls(client.get_database_client(database).get_container_client(container))

    def put(self, snapshot: PriceSnapshot) -> bool:
        existing = self.get(snapshot.snapshot_id)
        if existing is None:
            body = snapshot.model_dump(mode="json")
            body["id"] = snapshot.snapshot_id
            try:
                self._container.create_item(body=body)
                return True
            except CosmosResourceExistsError:
                existing = self.get(snapshot.snapshot_id)  # lost a race: compare, don't overwrite
            except Exception as exc:
                _raise_mapped(exc)
        if existing is None:
            raise _unavailable()
        if existing.content_hash == snapshot.content_hash:
            return False
        raise SnapshotConflictError(
            f"snapshot {snapshot.snapshot_id!r} already exists with a different content_hash"
        )

    def get(self, snapshot_id: str) -> PriceSnapshot | None:
        try:
            row = self._container.read_item(item=snapshot_id, partition_key=snapshot_id)
        except CosmosResourceNotFoundError:
            return None
        except Exception as exc:
            _raise_mapped(exc)
        return _from_row(dict(row))

    def _query(self, cloud: str | None, on: date | None) -> list[PriceSnapshot]:
        clauses: list[str] = []
        params: list[dict[str, Any]] = [{"name": "@limit", "value": MAX_SNAPSHOTS + 1}]
        if cloud is not None:
            clauses.append("ARRAY_CONTAINS(c.clouds, @cloud)")
            params.append({"name": "@cloud", "value": cloud})
        if on is not None:
            clauses.append("c.effective_date <= @on")
            params.append({"name": "@on", "value": on.isoformat()})
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        # Only fixed clause text and parameter placeholders are interpolated.
        sql = f"SELECT TOP @limit * FROM c{where} ORDER BY c.effective_date DESC"  # noqa: S608
        try:
            rows = list(
                self._container.query_items(
                    sql, parameters=params, enable_cross_partition_query=True
                )
            )
        except Exception as exc:
            _raise_mapped(exc)
        if len(rows) > MAX_SNAPSHOTS:
            raise DependencyTransientError(
                "price snapshot set exceeds the supported bound", reason="price_set_too_large"
            )
        snapshots = [_from_row(dict(row)) for row in rows]
        return sorted(snapshots, key=lambda s: (s.effective_date, s.snapshot_id), reverse=True)

    def list_snapshots(self, cloud: str | None = None) -> list[PriceSnapshot]:
        return self._query(cloud, None)

    def resolve(self, cloud: str, on: date) -> PriceSnapshot | None:
        snapshots = self._query(cloud, on)
        return snapshots[0] if snapshots else None

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
        for snapshot in self._query(cloud, on):
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
