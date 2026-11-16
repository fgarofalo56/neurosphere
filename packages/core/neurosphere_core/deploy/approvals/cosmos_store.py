"""Cosmos DB NoSQL plan-approval repository. Container ``deploy_plan_approvals``, partition
``/customer_id`` (PRP-55 item 1).

The document id is the plan id (unique per customer partition), so ``get`` is a point read. A
first approval is a ``create_item`` (a concurrent create loses with 409 and is re-decided against
the winner); replacing an expired approval is an ETag-conditioned ``replace_item``. Nothing is
ever deleted or evicted here. The client is built by ``neurosphere_core.clients`` and injected.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from azure.core import MatchConditions
from azure.cosmos.aio import ContainerProxy, CosmosClient
from azure.cosmos.exceptions import (
    CosmosAccessConditionFailedError,
    CosmosResourceExistsError,
    CosmosResourceNotFoundError,
)

from neurosphere_core.clients import translating
from neurosphere_core.deploy.approvals.models import PLAN_ID_CONFLICT, PlanApprovalRecord, decide
from neurosphere_core.deploy.approvals.store import Clock, utc_now
from neurosphere_core.errors import InvalidSchemaError

__all__ = [
    "DEFAULT_APPROVALS_CONTAINER",
    "DOC_TYPE",
    "PARTITION_KEY_PATH",
    "CosmosPlanApprovalRepository",
]

DEFAULT_APPROVALS_CONTAINER: Final = "deploy_plan_approvals"
PARTITION_KEY_PATH: Final = "/customer_id"
DOC_TYPE: Final = "plan_approval"
_STORAGE_FIELDS: Final = frozenset({"id", "doc_type"})


def _strip(document: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in document.items() if not k.startswith("_") and k not in _STORAGE_FIELDS}


class CosmosPlanApprovalRepository:
    def __init__(self, container: ContainerProxy, *, clock: Clock = utc_now) -> None:
        self._container = container
        self._clock = clock

    @classmethod
    def from_client(
        cls,
        client: CosmosClient,
        *,
        database: str,
        container: str = DEFAULT_APPROVALS_CONTAINER,
        clock: Clock = utc_now,
    ) -> CosmosPlanApprovalRepository:
        return cls(
            client.get_database_client(database).get_container_client(container), clock=clock
        )

    async def _read(self, customer_id: str, plan_id: str) -> dict[str, Any] | None:
        try:
            return dict(await self._container.read_item(item=plan_id, partition_key=customer_id))
        except CosmosResourceNotFoundError:
            return None

    async def create(self, record: PlanApprovalRecord) -> PlanApprovalRecord:
        body = {**record.model_dump(mode="json"), "id": record.plan_id, "doc_type": DOC_TYPE}
        with translating():
            current = await self._read(record.customer_id, record.plan_id)
            existing = PlanApprovalRecord.model_validate(_strip(current)) if current else None
            kept = decide(existing, record, self._clock())
            if kept is not None:
                return kept
            try:
                if current is None:
                    await self._container.create_item(body=body)
                else:
                    await self._container.replace_item(
                        item=record.plan_id,
                        body=body,
                        etag=str(current["_etag"]),
                        match_condition=MatchConditions.IfNotModified,
                    )
            except (CosmosResourceExistsError, CosmosAccessConditionFailedError):
                # Another approver won the race: the winner decides (same hash = idempotent).
                winner = await self._read(record.customer_id, record.plan_id)
                found = PlanApprovalRecord.model_validate(_strip(winner)) if winner else None
                if found is not None and found.plan_hash == record.plan_hash:
                    return found
                raise InvalidSchemaError(
                    "another plan was approved under this plan id concurrently",
                    reason=PLAN_ID_CONFLICT,
                ) from None
        return record

    async def get(self, customer_id: str, plan_id: str) -> PlanApprovalRecord | None:
        with translating():
            doc = await self._read(customer_id, plan_id)
        if doc is None:
            return None
        record = PlanApprovalRecord.model_validate(_strip(doc))
        return record if record.live_at(self._clock()) else None
