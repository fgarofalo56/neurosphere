"""Cosmos NoSQL recommendation store (azure-cosmos aio), PRP-29 item 2.

Container ``recommendations``: hierarchical partition key ``/customer_id``, ``/domain_id``
(``MultiHash``). One document per recommendation: the contract document plus the query fields
``id`` (a Cosmos-safe encoding of ``recommendation_id``), ``doc_type`` and ``sort_key`` (the raw
``recommendation_id``, which is what listing orders and pages by, exactly as the in-memory store).

Every query is single-partition (``partition_key=[customer, domain]``) AND repeats the customer,
domain and cloud predicates, so a mis-built partition key can never widen a read. A domain outside
the scope's allowed domains never reaches Cosmos: ``list`` returns an empty page and ``get``
returns ``None``. ``q`` is the same bounded plain-text, case-insensitive substring match as the
in-memory store, sent as a parameter (never interpolated). Outages map to
``dependency_transient`` (``recommendation_store_unavailable``), 429 to ``rate_limited``, and a
stored document that fails validation to ``dependency_transient`` + ``upstream_invalid``.
"""

from __future__ import annotations

import base64
import re
from collections.abc import Mapping
from typing import Any, Final, NoReturn

from azure.cosmos import PartitionKey
from azure.cosmos.aio import ContainerProxy, CosmosClient, DatabaseProxy
from azure.cosmos.exceptions import CosmosHttpResponseError, CosmosResourceNotFoundError
from neurosphere_contracts.recommendations.v1.recommendation import Recommendation
from pydantic import ValidationError

from neurosphere_core.errors import (
    DependencyTransientError,
    InvalidSchemaError,
    NeuroSphereError,
    RateLimitedError,
)
from neurosphere_core.paging import Page
from neurosphere_core.paging.models import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from neurosphere_core.recommendations.store import (
    MAX_QUERY_LENGTH,
    _decode_cursor,  # pyright: ignore[reportPrivateUsage]
    _encode_cursor,  # pyright: ignore[reportPrivateUsage]
)
from neurosphere_core.scope import IdentityScope

__all__ = [
    "DEFAULT_RECOMMENDATION_CONTAINER",
    "RECOMMENDATION_PARTITION_KEY_PATHS",
    "CosmosRecommendationStore",
    "create_recommendation_container",
]

DEFAULT_RECOMMENDATION_CONTAINER: Final = "recommendations"
RECOMMENDATION_PARTITION_KEY_PATHS: Final = ("/customer_id", "/domain_id")
RECOMMENDATION_DOC_TYPE: Final = "recommendation"
BY_ID_QUERY: Final = "SELECT * FROM c WHERE c.id = @id"
RECOMMENDATION_STORE_UNAVAILABLE: Final = "recommendation_store_unavailable"
_SAFE_ID: Final = re.compile(r"^[A-Za-z0-9._:=-]{1,200}$")
_SYSTEM_FIELDS: Final = frozenset({"id", "doc_type", "sort_key"})


async def create_recommendation_container(
    database: DatabaseProxy, container_id: str = DEFAULT_RECOMMENDATION_CONTAINER
) -> ContainerProxy:
    """Create (or open) the recommendations container with the hierarchical key."""
    return await database.create_container_if_not_exists(
        id=container_id,
        partition_key=PartitionKey(path=list(RECOMMENDATION_PARTITION_KEY_PATHS), kind="MultiHash"),
    )


def _doc_id(recommendation_id: str) -> str:
    """Cosmos forbids ``/ \\ ? #`` in ids; encode anything outside a conservative alphabet."""
    if _SAFE_ID.match(recommendation_id):
        return recommendation_id
    raw = base64.urlsafe_b64encode(recommendation_id.encode("utf-8")).decode("ascii")
    return "b64-" + raw.rstrip("=")


def _unavailable() -> DependencyTransientError:
    return DependencyTransientError(
        "recommendation store unavailable", reason=RECOMMENDATION_STORE_UNAVAILABLE
    )


def _invalid() -> DependencyTransientError:
    return DependencyTransientError(
        "stored recommendation failed validation",
        reason="recommendation_record_invalid",
        upstream_invalid=True,
    )


def _raise_mapped(exc: Exception) -> NoReturn:
    if isinstance(exc, NeuroSphereError):
        raise exc
    if isinstance(exc, CosmosHttpResponseError) and exc.status_code == 429:
        raise RateLimitedError(1, "recommendation store throttled the request") from exc
    raise _unavailable() from exc


def _from_row(row: Mapping[str, Any]) -> Recommendation:
    document = {k: v for k, v in row.items() if not k.startswith("_") and k not in _SYSTEM_FIELDS}
    try:
        return Recommendation.model_validate(document)
    except ValidationError as exc:
        raise _invalid() from exc


class CosmosRecommendationStore:
    """:class:`neurosphere_core.recommendations.store.RecommendationStore` on one container."""

    def __init__(self, container: ContainerProxy) -> None:
        self._container = container

    @classmethod
    def from_client(
        cls,
        client: CosmosClient,
        *,
        database: str,
        container: str = DEFAULT_RECOMMENDATION_CONTAINER,
    ) -> CosmosRecommendationStore:
        return cls(client.get_database_client(database).get_container_client(container))

    async def put(self, recommendation: Recommendation) -> None:
        body = recommendation.model_dump(mode="json")
        body["id"] = _doc_id(recommendation.recommendation_id.root)
        body["doc_type"] = RECOMMENDATION_DOC_TYPE
        body["sort_key"] = recommendation.recommendation_id.root
        try:
            await self._container.upsert_item(body=body)
            # ``recommendation_id`` is caller-supplied (not derived from the domain), and the
            # in-memory store replaces by id alone: drop any copy left in another partition.
            async for row in self._container.query_items(
                BY_ID_QUERY,
                parameters=[{"name": "@id", "value": body["id"]}],
            ):
                key = [row["customer_id"], row["domain_id"]]
                if key != [body["customer_id"], body["domain_id"]]:
                    await self._container.delete_item(item=row["id"], partition_key=key)
        except Exception as exc:
            _raise_mapped(exc)

    async def list(
        self,
        scope: IdentityScope,
        domain: str,
        kind: str | None = None,
        q: str | None = None,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> Page[Recommendation]:
        if not 1 <= limit <= MAX_PAGE_SIZE:
            raise InvalidSchemaError(f"limit must be 1..{MAX_PAGE_SIZE}", reason="invalid_limit")
        needle = None
        if q is not None:
            if len(q) > MAX_QUERY_LENGTH:
                raise InvalidSchemaError(
                    f"q is limited to {MAX_QUERY_LENGTH} characters", reason="query_too_long"
                )
            needle = q.strip().lower() or None
        after = _decode_cursor(cursor) if cursor else None
        if domain not in scope.allowed_domains:
            return Page[Recommendation](items=(), next_cursor=None)
        clauses = [
            "c.doc_type = @doc_type",
            "c.customer_id = @customer",
            "c.domain_id = @domain",
            "c.cloud = @cloud",
        ]
        params: list[dict[str, Any]] = [
            {"name": "@limit", "value": limit + 1},
            {"name": "@doc_type", "value": RECOMMENDATION_DOC_TYPE},
            {"name": "@customer", "value": scope.customer_id},
            {"name": "@domain", "value": domain},
            {"name": "@cloud", "value": scope.cloud},
        ]
        if after is not None:
            clauses.append("c.sort_key > @after")
            params.append({"name": "@after", "value": after})
        if kind is not None:
            clauses.append("c.kind = @kind")
            params.append({"name": "@kind", "value": kind})
        if needle is not None:
            clauses.append(
                "(CONTAINS(LOWER(c.kind), @q) OR "
                "EXISTS(SELECT VALUE s FROM s IN c.subject_ids WHERE CONTAINS(LOWER(s), @q)))"
            )
            params.append({"name": "@q", "value": needle})
        # Only fixed clause text and parameter placeholders are interpolated.
        sql = (
            "SELECT TOP @limit * FROM c WHERE "  # noqa: S608
            + " AND ".join(clauses)
            + " ORDER BY c.sort_key ASC"
        )
        try:
            rows = [
                row
                async for row in self._container.query_items(
                    sql, parameters=params, partition_key=[scope.customer_id, domain]
                )
            ]
        except Exception as exc:
            _raise_mapped(exc)
        found = [_from_row(row) for row in rows]
        page = found[:limit]
        next_cursor = (
            _encode_cursor(page[-1].recommendation_id.root) if len(found) > limit else None
        )
        return Page[Recommendation](items=tuple(page), next_cursor=next_cursor)

    async def get(
        self, scope: IdentityScope, domain: str, recommendation_id: str
    ) -> Recommendation | None:
        if domain not in scope.allowed_domains:
            return None
        try:
            row = await self._container.read_item(
                item=_doc_id(recommendation_id), partition_key=[scope.customer_id, domain]
            )
        except CosmosResourceNotFoundError:
            return None
        except Exception as exc:
            _raise_mapped(exc)
        if row.get("doc_type") != RECOMMENDATION_DOC_TYPE:
            return None
        rec = _from_row(row)
        if (
            rec.customer_id != scope.customer_id
            or rec.cloud != scope.cloud
            or rec.domain_id.root != domain
            or rec.recommendation_id.root != recommendation_id
        ):
            return None
        return rec
