"""Read access to the APIM connector's durable apply records (PRP-34 item 10).

The executor worker writes apply records through ``CosmosGatewayRecordStore`` with the
connector's ``ApplyRecord`` model, one store per gateway partition ``(customer_id, domain_id)``
of the ``gateways`` container (``neurosphere_workers.actions.apim.apim_record_store``). Recording
a Grant publication needs to READ the record of the publish (which resources it ``created``), in
the API (``app.state.apim_apply_records``) and in the worker's post-success recorder.

:class:`ApplyRecordLookup` is that read side: ``for_domain`` returns the store of one partition,
over the SAME container and the same core store class, read with :class:`RecordedApply`, a
read-only view of the facets the catalog records (ids, status, and per step the name, operation
and ownership). It never imports the connector, so the API stays free of connector packages.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from azure.cosmos.aio import CosmosClient
from neurosphere_core.gateway import (
    DEFAULT_GATEWAY_CONTAINER,
    CosmosGatewayRecordStore,
    InMemoryGatewayRecordStore,
)
from pydantic import BaseModel, ConfigDict

__all__ = [
    "ApplyRecordLookup",
    "ApplyRecordReader",
    "CosmosApplyRecordLookup",
    "InMemoryApplyRecordLookup",
    "RecordedApply",
    "RecordedStep",
    "reader_for",
]


class RecordedStep(BaseModel):
    """One step of an apply record, as far as ownership recording needs it."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    name: str
    operation: str
    ownership: str


class RecordedApply(BaseModel):
    """Read-only view of the connector's ``ApplyRecord`` (never written through this model)."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    id: str
    gateway_id: str
    target: str
    plan_digest: str
    status: str
    steps: tuple[RecordedStep, ...] = ()


@runtime_checkable
class ApplyRecordReader(Protocol):
    async def latest(self, record_id: str) -> Any: ...


@runtime_checkable
class ApplyRecordLookup(Protocol):
    def for_domain(self, customer_id: str, domain_id: str) -> ApplyRecordReader:
        """The apply-record store of one gateway partition."""
        ...


class CosmosApplyRecordLookup:
    """Partitioned reads over the ``gateways`` container the executor writes to."""

    def __init__(
        self,
        client: CosmosClient,
        *,
        database: str,
        container: str = DEFAULT_GATEWAY_CONTAINER,
    ) -> None:
        self._client = client
        self._database = database
        self._container = container

    @property
    def database(self) -> str:
        return self._database

    @property
    def container(self) -> str:
        return self._container

    def for_domain(
        self, customer_id: str, domain_id: str
    ) -> CosmosGatewayRecordStore[RecordedApply]:
        return CosmosGatewayRecordStore.from_client(
            self._client,
            database=self._database,
            customer_id=customer_id,
            domain_id=domain_id,
            model=RecordedApply,
            container=self._container,
        )


class InMemoryApplyRecordLookup:
    """Per-process partitions (``NS_ENV=local`` with an in-memory gateway store, tests)."""

    def __init__(self) -> None:
        self._stores: dict[tuple[str, str], InMemoryGatewayRecordStore[RecordedApply]] = {}

    def for_domain(
        self, customer_id: str, domain_id: str
    ) -> InMemoryGatewayRecordStore[RecordedApply]:
        key = (customer_id, domain_id)
        if key not in self._stores:
            self._stores[key] = InMemoryGatewayRecordStore(RecordedApply)
        return self._stores[key]


def reader_for(records: object, customer_id: str, domain_id: str) -> ApplyRecordReader | None:
    """The reader for one partition: a lookup's ``for_domain``, or a store already bound to one
    partition; ``None`` when nothing usable is wired (ownership is then ``unrecorded``)."""
    if records is None:
        return None
    if isinstance(records, ApplyRecordLookup):
        return records.for_domain(customer_id, domain_id)
    if isinstance(records, ApplyRecordReader):
        return records
    return None
