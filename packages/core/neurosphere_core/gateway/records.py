"""Durable, append-only apply-record store for the APIM write connector (PRP-34 item 2).

The connector's ``ApplyRecordStore`` protocol (``append`` / ``latest``) is satisfied here
structurally: core never imports a connector, so the store is generic over the record model and
reads only five JSON facets of it (``id``, ``gateway_id``, ``target``, ``plan_digest``,
``status``). Wire it with the connector's model, e.g.
``CosmosGatewayRecordStore.from_client(..., model=ApplyRecord)``.

Rules every implementation enforces (not by convention):

* Append-only. Every ``append`` adds a new version; nothing is replaced or deleted. ``latest``
  returns the newest version, ``history`` all of them in order.
* A record's plan is immutable once it is reviewed: a later version must carry the SAME
  ``gateway_id``, ``target`` and ``plan_digest`` as the first, else ``stale_version`` reason
  ``apply_record_immutable``. Nothing is appended after a terminal status (``rolled_back``,
  ``rollback_failed``).
* ``running(gateway_id)`` is True while any record of the gateway has ``applying`` as its newest
  status; the mode switch refuses to flip a busy gateway (``gateway_applying``).

The Cosmos implementation lives in the ``gateways`` container (same partition as the gateway's
registration): ``doc_type = gateway_apply_record`` version documents
(``id = rec-<record id>-v<version>``) and one ``doc_type = gateway_apply_head`` pointer per record
(``id = rechead-<record id>``) that holds the newest version and status, so ``running`` is a
bounded query. A crash between the version write and the head move is repaired by the next
append (the orphan version becomes the head before anything new is written).
"""

from __future__ import annotations

import builtins
import copy
import itertools
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, NoReturn

from azure.core import MatchConditions
from azure.cosmos.aio import ContainerProxy, CosmosClient
from azure.cosmos.exceptions import (
    CosmosAccessConditionFailedError,
    CosmosHttpResponseError,
    CosmosResourceExistsError,
    CosmosResourceNotFoundError,
)
from pydantic import BaseModel, ValidationError

from neurosphere_core.errors import (
    DependencyTransientError,
    InvalidSchemaError,
    NeuroSphereError,
    RateLimitedError,
    StaleVersionError,
)
from neurosphere_core.gateway.cosmos_store import DEFAULT_GATEWAY_CONTAINER
from neurosphere_core.gateway.store import store_unavailable

__all__ = [
    "APPLY_RECORD_CONFLICT",
    "APPLY_RECORD_IMMUTABLE",
    "HEAD_DOC_TYPE",
    "RECORD_DOC_TYPE",
    "RUNNING_STATUS",
    "TERMINAL_STATUSES",
    "CosmosGatewayRecordStore",
    "InMemoryGatewayRecordStore",
]

RECORD_DOC_TYPE: Final = "gateway_apply_record"
HEAD_DOC_TYPE: Final = "gateway_apply_head"
RUNNING_STATUS: Final = "applying"
TERMINAL_STATUSES: Final = frozenset({"rolled_back", "rollback_failed"})
APPLY_RECORD_IMMUTABLE: Final = "apply_record_immutable"
APPLY_RECORD_CONFLICT: Final = "apply_record_conflict"
_MAX_REPAIRS: Final = 3


@dataclass(frozen=True)
class _Facets:
    id: str
    gateway_id: str
    target: str
    plan_digest: str
    status: str


def _facets(document: Mapping[str, Any]) -> _Facets:
    values: dict[str, str] = {}
    for name in ("id", "gateway_id", "target", "plan_digest", "status"):
        value = document.get(name)
        if not isinstance(value, str) or not value:
            raise InvalidSchemaError(f"apply record has no {name}", reason="bad_apply_record")
        values[name] = value
    return _Facets(**values)


def _immutable(detail: str) -> StaleVersionError:
    return StaleVersionError(detail, reason=APPLY_RECORD_IMMUTABLE)


def _check_append(head: _Facets | None, new: _Facets) -> None:
    if head is None:
        return
    if head.status in TERMINAL_STATUSES:
        raise _immutable("the apply record is closed")
    if (head.gateway_id, head.target, head.plan_digest) != (
        new.gateway_id,
        new.target,
        new.plan_digest,
    ):
        raise _immutable("the reviewed plan of an apply record cannot change")


class InMemoryGatewayRecordStore[R: BaseModel]:
    """Per-process store with the same rules (tests, local sandbox). ``fail_with`` = outage."""

    def __init__(self, model: type[R]) -> None:
        self._model = model
        self._versions: dict[str, list[dict[str, Any]]] = {}
        self._order = itertools.count()
        self.error: Exception | None = None

    def fail_with(self, error: Exception | None) -> None:
        self.error = error

    def _check(self) -> None:
        if self.error is not None:
            raise self.error

    async def append(self, record: R) -> None:
        self._check()
        document = record.model_dump(mode="json")
        new = _facets(document)
        versions = self._versions.get(new.id)
        _check_append(_facets(versions[-1]) if versions else None, new)
        self._versions.setdefault(new.id, []).append(copy.deepcopy(document))

    async def latest(self, record_id: str) -> R | None:
        self._check()
        versions = self._versions.get(record_id)
        return self._model.model_validate(versions[-1]) if versions else None

    async def history(self, record_id: str) -> tuple[R, ...]:
        self._check()
        return tuple(self._model.model_validate(v) for v in self._versions.get(record_id, ()))

    async def running(self, gateway_id: str) -> bool:
        self._check()
        return any(
            v[-1].get("gateway_id") == gateway_id and v[-1].get("status") == RUNNING_STATUS
            for v in self._versions.values()
            if v
        )


def _raise_mapped(exc: Exception) -> NoReturn:
    if isinstance(exc, NeuroSphereError):
        raise exc
    if isinstance(exc, CosmosHttpResponseError) and exc.status_code == 429:
        raise RateLimitedError(1, "gateway store throttled the request") from exc
    raise store_unavailable() from exc


def _conflict() -> StaleVersionError:
    return StaleVersionError("the apply record changed concurrently", reason=APPLY_RECORD_CONFLICT)


def _invalid() -> DependencyTransientError:
    return DependencyTransientError(
        "stored apply record failed validation",
        reason="apply_record_invalid",
        upstream_invalid=True,
    )


def _version_id(record_id: str, version: int) -> str:
    return f"rec-{record_id}-v{version:06d}"


def _head_id(record_id: str) -> str:
    return f"rechead-{record_id}"


class CosmosGatewayRecordStore[R: BaseModel]:
    """Append-only apply records for one ``(customer_id, domain_id)`` gateway partition."""

    def __init__(
        self, container: ContainerProxy, *, customer_id: str, domain_id: str, model: type[R]
    ) -> None:
        self._container = container
        self._customer_id = customer_id
        self._domain_id = domain_id
        self._model = model

    @classmethod
    def from_client(
        cls,
        client: CosmosClient,
        *,
        database: str,
        customer_id: str,
        domain_id: str,
        model: type[R],
        container: str = DEFAULT_GATEWAY_CONTAINER,
    ) -> CosmosGatewayRecordStore[R]:
        proxy = client.get_database_client(database).get_container_client(container)
        return cls(proxy, customer_id=customer_id, domain_id=domain_id, model=model)

    @property
    def _partition(self) -> list[str]:
        return [self._customer_id, self._domain_id]

    async def _read(self, item_id: str) -> dict[str, Any] | None:
        try:
            row = await self._container.read_item(item=item_id, partition_key=self._partition)
        except CosmosResourceNotFoundError:
            return None
        except Exception as exc:
            _raise_mapped(exc)
        return dict(row)

    def _parse(self, row: Mapping[str, Any]) -> R:
        try:
            return self._model.model_validate(row.get("record"))
        except ValidationError as exc:
            raise _invalid() from exc

    def _head_body(self, new: _Facets, version: int) -> dict[str, Any]:
        return {
            "id": _head_id(new.id),
            "doc_type": HEAD_DOC_TYPE,
            "customer_id": self._customer_id,
            "domain_id": self._domain_id,
            "record_id": new.id,
            "version": version,
            "gateway_id": new.gateway_id,
            "target": new.target,
            "plan_digest": new.plan_digest,
            "status": new.status,
        }

    async def _move_head(self, head: Mapping[str, Any] | None, body: dict[str, Any]) -> None:
        try:
            if head is None:
                await self._container.create_item(body=body)
            else:
                await self._container.replace_item(
                    item=body["id"],
                    body=body,
                    etag=str(head.get("_etag", "")),
                    match_condition=MatchConditions.IfNotModified,
                )
        except (CosmosResourceExistsError, CosmosAccessConditionFailedError) as exc:
            raise _conflict() from exc
        except Exception as exc:
            _raise_mapped(exc)

    async def append(self, record: R) -> None:
        document = record.model_dump(mode="json")
        new = _facets(document)
        for _ in range(_MAX_REPAIRS + 1):
            head = await self._read(_head_id(new.id))
            current = None if head is None else _facets({**head, "id": new.id})
            _check_append(current, new)
            version = 1 if head is None else int(head["version"]) + 1
            body = {
                "id": _version_id(new.id, version),
                "doc_type": RECORD_DOC_TYPE,
                "customer_id": self._customer_id,
                "domain_id": self._domain_id,
                "record_id": new.id,
                "version": version,
                "gateway_id": new.gateway_id,
                "status": new.status,
                "record": document,
            }
            try:
                await self._container.create_item(body=body)
            except CosmosResourceExistsError:
                # A previous append wrote this version but lost the head move: repair the head
                # from that (immutable) version, then retry on top of it.
                orphan = await self._read(_version_id(new.id, version))
                if orphan is None:
                    raise _conflict() from None
                found = _facets(orphan.get("record") or {})
                await self._move_head(head, self._head_body(found, version))
                continue
            except Exception as exc:
                _raise_mapped(exc)
            await self._move_head(head, self._head_body(new, version))
            return
        raise _conflict()

    async def latest(self, record_id: str) -> R | None:
        head = await self._read(_head_id(record_id))
        if head is None:
            return None
        row = await self._read(_version_id(record_id, int(head["version"])))
        if row is None:
            raise _invalid()
        return self._parse(row)

    async def history(self, record_id: str) -> tuple[R, ...]:
        sql = (
            "SELECT * FROM c WHERE c.doc_type = @doc_type AND c.record_id = @record"
            " ORDER BY c.version ASC"
        )
        params: builtins.list[dict[str, Any]] = [
            {"name": "@doc_type", "value": RECORD_DOC_TYPE},
            {"name": "@record", "value": record_id},
        ]
        try:
            rows = [
                row
                async for row in self._container.query_items(
                    sql, parameters=params, partition_key=self._partition
                )
            ]
        except Exception as exc:
            _raise_mapped(exc)
        return tuple(self._parse(row) for row in rows)

    async def running(self, gateway_id: str) -> bool:
        sql = (
            "SELECT TOP 1 c.id FROM c WHERE c.doc_type = @doc_type"
            " AND c.gateway_id = @gateway AND c.status = @status"
        )
        params: builtins.list[dict[str, Any]] = [
            {"name": "@doc_type", "value": HEAD_DOC_TYPE},
            {"name": "@gateway", "value": gateway_id},
            {"name": "@status", "value": RUNNING_STATUS},
        ]
        try:
            rows = [
                row
                async for row in self._container.query_items(
                    sql, parameters=params, partition_key=self._partition
                )
            ]
        except Exception as exc:
            _raise_mapped(exc)
        return bool(rows)
