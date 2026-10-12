"""Cosmos NoSQL policy repository over an injected async client (``neurosphere_core.clients``).

Point reads only (id + partition key ``customer_id``); no queries are built from request input.
Not-found is the only failure mapped to ``None``. Every other SDK or transport failure, including
401/403 from the store, becomes ``dependency_transient`` (503): an unreadable policy store is an
outage, never an allow and never an empty scope. A document that does not validate becomes
``dependency_transient`` with ``upstream_invalid`` (502). Error messages never echo SDK text or
document content.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from azure.cosmos.aio import ContainerProxy, CosmosClient
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from pydantic import BaseModel, ValidationError

from neurosphere_core.auth.scope.policy import (
    POLICY_HEAD_ID,
    PolicyHead,
    PrincipalPolicy,
    principal_document_id,
)
from neurosphere_core.errors import DependencyTransientError

__all__ = ["DEFAULT_POLICY_CONTAINER", "CosmosPolicyRepository"]

DEFAULT_POLICY_CONTAINER: Final = "policy"


def _strip_system_properties(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Drop Cosmos system members (``_rid``, ``_etag``, ``_ts``, ...) before strict validation."""
    return {k: v for k, v in raw.items() if not k.startswith("_")}


class CosmosPolicyRepository:
    def __init__(
        self,
        client: CosmosClient,
        *,
        database: str,
        container: str = DEFAULT_POLICY_CONTAINER,
    ) -> None:
        self._container: ContainerProxy = client.get_database_client(database).get_container_client(
            container
        )

    async def _read[M: BaseModel](self, model: type[M], item_id: str, customer_id: str) -> M | None:
        try:
            raw = await self._container.read_item(item=item_id, partition_key=customer_id)
        except CosmosResourceNotFoundError:
            return None
        except Exception as exc:
            raise DependencyTransientError(
                "policy store unavailable", reason="policy_store_unavailable"
            ) from exc
        try:
            return model.model_validate(_strip_system_properties(raw))
        except ValidationError as exc:
            raise DependencyTransientError(
                "policy document failed validation",
                reason="policy_document_invalid",
                upstream_invalid=True,
            ) from exc

    async def get_policy_head(self, customer_id: str) -> PolicyHead | None:
        head = await self._read(PolicyHead, POLICY_HEAD_ID, customer_id)
        if head is not None and head.customer_id != customer_id:
            raise DependencyTransientError(
                "policy head partition mismatch",
                reason="policy_document_invalid",
                upstream_invalid=True,
            )
        return head

    async def get_principal_policy(
        self, customer_id: str, principal_id: str
    ) -> PrincipalPolicy | None:
        doc = await self._read(PrincipalPolicy, principal_document_id(principal_id), customer_id)
        if doc is not None and (doc.customer_id != customer_id or doc.principal_id != principal_id):
            raise DependencyTransientError(
                "policy document does not belong to the requested principal",
                reason="policy_document_invalid",
                upstream_invalid=True,
            )
        return doc
