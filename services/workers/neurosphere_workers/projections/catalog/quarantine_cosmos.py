"""Durable ``CandidateQuarantine`` on the Cosmos ``catalog_quarantine`` container (PRP-43 item 1).

Hierarchical partition key ``/customer_id``, ``/domain_id`` (same shape as the review queue). The
document id is the candidate edge id, so ``write`` is an upsert and a replay leaves one record.
Records hold identifiers only. A store failure raises, which fails the outbox entry and holds the
checkpoint.
"""

from __future__ import annotations

from typing import Final

from azure.cosmos.aio import ContainerProxy, CosmosClient
from azure.cosmos.exceptions import CosmosHttpResponseError
from neurosphere_core.errors import DependencyTransientError, RateLimitedError

from neurosphere_workers.projections.catalog.quarantine import CandidateQuarantineRecord

DEFAULT_QUARANTINE_CONTAINER: Final = "catalog_quarantine"


class CosmosCandidateQuarantine:
    def __init__(self, container: ContainerProxy) -> None:
        self._container = container

    @classmethod
    def from_client(
        cls,
        client: CosmosClient,
        *,
        database: str,
        container: str = DEFAULT_QUARANTINE_CONTAINER,
    ) -> CosmosCandidateQuarantine:
        return cls(client.get_database_client(database).get_container_client(container))

    async def write(self, record: CandidateQuarantineRecord) -> None:
        try:
            await self._container.upsert_item(body=record.model_dump(mode="json"))
        except CosmosHttpResponseError as exc:
            if exc.status_code == 429:
                raise RateLimitedError(1, "candidate quarantine throttled the request") from exc
            raise DependencyTransientError(
                "candidate quarantine unavailable", reason="candidate_quarantine_unavailable"
            ) from exc
        except Exception as exc:
            raise DependencyTransientError(
                "candidate quarantine unavailable", reason="candidate_quarantine_unavailable"
            ) from exc
