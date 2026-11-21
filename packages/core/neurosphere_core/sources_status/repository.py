"""Where connector run statuses live: the ``admin_config`` container, record kind
``connector_run_status`` (PRP-139 clarification 9). No new container and no contract change.

One row per ``(customer, connector kind)``, id ``connector_run_status:<kind>``, partition
``/customer_id``, ``doc_type`` ``connector_run_status``. The admin-config store reads and scans
only ``doc_type == "admin_config"`` rows, so these rows are invisible to it, and this repository
touches only its own rows. Workers write, the API reads.

``record`` carries the previous ``last_success_at`` forward when the new status has none, so an
``idle`` or ``failed`` run never erases the time of the last good run.
"""

from __future__ import annotations

import builtins
from abc import ABC, abstractmethod
from typing import Any, Final, NoReturn

from azure.cosmos.aio import ContainerProxy, CosmosClient
from azure.cosmos.exceptions import CosmosHttpResponseError, CosmosResourceNotFoundError
from pydantic import ValidationError

from neurosphere_core.admin.models import ADMIN_CONFIG_CONTAINER
from neurosphere_core.errors import (
    DependencyTransientError,
    NeuroSphereError,
    RateLimitedError,
)
from neurosphere_core.sources_status.models import ConnectorRunStatus

__all__ = [
    "RUN_STATUS_DOC_TYPE",
    "CosmosSourceStatusRepository",
    "InMemorySourceStatusRepository",
    "SourceStatusRepository",
    "run_status_item_id",
]

RUN_STATUS_DOC_TYPE: Final = "connector_run_status"
_UNAVAILABLE: Final = "source_status_unavailable"


def run_status_item_id(kind: str) -> str:
    return f"{RUN_STATUS_DOC_TYPE}:{kind}"


def _unavailable() -> DependencyTransientError:
    return DependencyTransientError("source status store unavailable", reason=_UNAVAILABLE)


def _invalid_row() -> DependencyTransientError:
    return DependencyTransientError(
        "source status row failed validation", reason="source_status_invalid", upstream_invalid=True
    )


def _carry(previous: ConnectorRunStatus | None, new: ConnectorRunStatus) -> ConnectorRunStatus:
    if new.last_success_at is not None or previous is None or previous.last_success_at is None:
        return new
    return new.model_copy(update={"last_success_at": previous.last_success_at})


class SourceStatusRepository(ABC):
    """Reads and writes the run status of each connector kind, per customer."""

    @abstractmethod
    async def get(self, customer_id: str, kind: str) -> ConnectorRunStatus | None: ...

    @abstractmethod
    async def list(self, customer_id: str) -> builtins.list[ConnectorRunStatus]: ...

    @abstractmethod
    async def _write(self, customer_id: str, status: ConnectorRunStatus) -> None: ...

    async def record(self, customer_id: str, status: ConnectorRunStatus) -> ConnectorRunStatus:
        """Store ``status`` (last success carried forward); returns what was stored."""
        merged = _carry(await self.get(customer_id, status.kind), status)
        await self._write(customer_id, merged)
        return merged


class InMemorySourceStatusRepository(SourceStatusRepository):
    """Twin for tests and the local sandbox. Never a production store."""

    def __init__(self) -> None:
        self._rows: dict[tuple[str, str], ConnectorRunStatus] = {}
        self.error: BaseException | None = None

    def fail_with(self, error: BaseException | None) -> None:
        self.error = error

    def _guard(self) -> None:
        if self.error is not None:
            raise self.error

    async def get(self, customer_id: str, kind: str) -> ConnectorRunStatus | None:
        self._guard()
        return self._rows.get((customer_id, kind))

    async def list(self, customer_id: str) -> builtins.list[ConnectorRunStatus]:
        self._guard()
        rows = [s for (c, _), s in self._rows.items() if c == customer_id]
        return sorted(rows, key=lambda s: s.kind)

    async def _write(self, customer_id: str, status: ConnectorRunStatus) -> None:
        self._guard()
        self._rows[(customer_id, status.kind)] = status


def _raise_mapped(exc: Exception) -> NoReturn:
    if isinstance(exc, NeuroSphereError):
        raise exc
    if isinstance(exc, CosmosHttpResponseError) and exc.status_code == 429:
        raise RateLimitedError(1, "source status store throttled the request") from exc
    raise _unavailable() from exc


def _from_row(row: dict[str, Any], customer_id: str) -> ConnectorRunStatus:
    body = row.get("status")
    if not isinstance(body, dict) or row.get("customer_id") != customer_id:
        raise _invalid_row()
    try:
        parsed = ConnectorRunStatus.model_validate(body)
    except ValidationError as exc:
        raise _invalid_row() from exc
    if row.get("id") != run_status_item_id(parsed.kind):
        raise _invalid_row()
    return parsed


class CosmosSourceStatusRepository(SourceStatusRepository):
    """The ``admin_config`` container (partition ``/customer_id``), rows of its own doc type."""

    def __init__(self, container: ContainerProxy) -> None:
        self._container = container

    @classmethod
    def from_client(
        cls,
        client: CosmosClient,
        *,
        database: str,
        container: str = ADMIN_CONFIG_CONTAINER,
    ) -> CosmosSourceStatusRepository:
        return cls(client.get_database_client(database).get_container_client(container))

    async def get(self, customer_id: str, kind: str) -> ConnectorRunStatus | None:
        try:
            row = await self._container.read_item(
                item=run_status_item_id(kind), partition_key=customer_id
            )
        except CosmosResourceNotFoundError:
            return None
        except Exception as exc:
            _raise_mapped(exc)
        if row.get("doc_type") != RUN_STATUS_DOC_TYPE:
            return None
        return _from_row(row, customer_id)

    async def list(self, customer_id: str) -> builtins.list[ConnectorRunStatus]:
        sql = "SELECT * FROM c WHERE c.doc_type = @doc_type ORDER BY c.id ASC"
        params: builtins.list[dict[str, Any]] = [
            {"name": "@doc_type", "value": RUN_STATUS_DOC_TYPE}
        ]
        try:
            rows = [
                row
                async for row in self._container.query_items(
                    sql, parameters=params, partition_key=customer_id
                )
            ]
        except Exception as exc:
            _raise_mapped(exc)
        return [_from_row(row, customer_id) for row in rows]

    async def _write(self, customer_id: str, status: ConnectorRunStatus) -> None:
        body: dict[str, Any] = {
            "id": run_status_item_id(status.kind),
            "doc_type": RUN_STATUS_DOC_TYPE,
            "customer_id": customer_id,
            "kind": RUN_STATUS_DOC_TYPE,
            "status": status.model_dump(mode="json"),
        }
        try:
            await self._container.upsert_item(body=body)
        except Exception as exc:
            _raise_mapped(exc)
