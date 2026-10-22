"""Cosmos NoSQL report store (azure-cosmos aio), following the PRP-17 intent store pattern.

Container ``reports``: hierarchical partition key ``/customer_id`` + ``/domain_id`` (``MultiHash``).
One document per report (``doc_type = report``, ``id = <report_id>``): the ``StoredReport`` fields
plus the query field ``sort_key``. The Cosmos ``_etag`` is the report ETag. Replace and delete are
``IfNotModified`` on ``_etag``: 412 or 404 -> ``stale_version`` ``report_modified``. Queries are
parameterized; only fixed clause text is interpolated. Result data is never written here.

Outages -> ``dependency_transient`` (``report_store_unavailable``); 429 -> ``rate_limited``; a
document that fails validation -> ``dependency_transient`` with ``upstream_invalid``. Messages
never echo SDK text or documents.
"""

import builtins
from collections.abc import Mapping
from typing import Any, Final, NoReturn

from azure.core import MatchConditions
from azure.cosmos import PartitionKey
from azure.cosmos.aio import ContainerProxy, CosmosClient, DatabaseProxy
from azure.cosmos.exceptions import (
    CosmosAccessConditionFailedError,
    CosmosHttpResponseError,
    CosmosResourceExistsError,
    CosmosResourceNotFoundError,
)
from neurosphere_core.errors import DependencyTransientError, NeuroSphereError, RateLimitedError
from neurosphere_core.paging import Page
from pydantic import ValidationError

from neurosphere_api.reports.models import PublicationState, StoredReport
from neurosphere_api.reports.store import (
    DEFAULT_LIMIT,
    check_limit,
    decode_cursor,
    encode_cursor,
    report_modified,
    sort_key,
    store_unavailable,
)

__all__ = [
    "DEFAULT_REPORT_CONTAINER",
    "REPORT_PARTITION_KEY_PATHS",
    "CosmosReportStore",
    "create_report_container",
]

DEFAULT_REPORT_CONTAINER: Final = "reports"
REPORT_PARTITION_KEY_PATHS: Final = ("/customer_id", "/domain_id")
REPORT_DOC_TYPE: Final = "report"
_QUERY_FIELDS: Final = frozenset({"doc_type", "sort_key"})


async def create_report_container(
    database: DatabaseProxy, container_id: str = DEFAULT_REPORT_CONTAINER
) -> ContainerProxy:
    """Create (or open) the report container with the hierarchical key."""
    return await database.create_container_if_not_exists(
        id=container_id,
        partition_key=PartitionKey(path=list(REPORT_PARTITION_KEY_PATHS), kind="MultiHash"),
    )


def _raise_mapped(exc: Exception) -> NoReturn:
    if isinstance(exc, NeuroSphereError):
        raise exc
    if isinstance(exc, CosmosHttpResponseError) and exc.status_code == 429:
        raise RateLimitedError(1, "report store throttled the request") from exc
    raise store_unavailable() from exc


def _invalid() -> DependencyTransientError:
    return DependencyTransientError(
        "stored report failed validation", reason="report_record_invalid", upstream_invalid=True
    )


def _body(report: StoredReport) -> dict[str, Any]:
    body = report.model_dump(mode="json", exclude={"etag"})
    body["doc_type"] = REPORT_DOC_TYPE
    body["sort_key"] = sort_key(report)
    return body


def _from_row(row: Mapping[str, Any]) -> StoredReport:
    document = {k: v for k, v in row.items() if not k.startswith("_") and k not in _QUERY_FIELDS}
    try:
        return StoredReport.model_validate({**document, "etag": str(row.get("_etag", "")) or None})
    except ValidationError as exc:
        raise _invalid() from exc


class CosmosReportStore:
    """:class:`neurosphere_api.reports.store.ReportStore` on one Cosmos container."""

    def __init__(self, container: ContainerProxy) -> None:
        self._container = container

    @classmethod
    def from_client(
        cls,
        client: CosmosClient,
        *,
        database: str,
        container: str = DEFAULT_REPORT_CONTAINER,
    ) -> "CosmosReportStore":
        return cls(client.get_database_client(database).get_container_client(container))

    async def create(self, report: StoredReport) -> StoredReport:
        try:
            row = await self._container.create_item(body=_body(report))
        except CosmosResourceExistsError as exc:
            raise report_modified() from exc
        except Exception as exc:
            _raise_mapped(exc)
        return _from_row(row)

    async def get(self, customer_id: str, domain_id: str, report_id: str) -> StoredReport | None:
        try:
            row = await self._container.read_item(
                item=report_id, partition_key=[customer_id, domain_id]
            )
        except CosmosResourceNotFoundError:
            return None
        except Exception as exc:
            _raise_mapped(exc)
        if row.get("doc_type") != REPORT_DOC_TYPE:
            return None
        return _from_row(row)

    async def replace(self, report: StoredReport, *, if_match: str) -> StoredReport:
        try:
            row = await self._container.replace_item(
                item=report.id,
                body=_body(report),
                etag=if_match,
                match_condition=MatchConditions.IfNotModified,
            )
        except (CosmosAccessConditionFailedError, CosmosResourceNotFoundError) as exc:
            raise report_modified() from exc
        except Exception as exc:
            _raise_mapped(exc)
        return _from_row(row)

    async def delete(
        self, customer_id: str, domain_id: str, report_id: str, *, if_match: str
    ) -> None:
        try:
            await self._container.delete_item(
                item=report_id,
                partition_key=[customer_id, domain_id],
                etag=if_match,
                match_condition=MatchConditions.IfNotModified,
            )
        except (CosmosAccessConditionFailedError, CosmosResourceNotFoundError) as exc:
            raise report_modified() from exc
        except Exception as exc:
            _raise_mapped(exc)

    async def list(
        self,
        customer_id: str,
        domain_id: str,
        *,
        visible_to: str | None = None,
        publication_state: PublicationState | None = None,
        cursor: str | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> Page[StoredReport]:
        check_limit(limit)
        clauses = ["c.doc_type = @doc_type"]
        params: builtins.list[dict[str, Any]] = [
            {"name": "@doc_type", "value": REPORT_DOC_TYPE},
            {"name": "@limit", "value": limit + 1},
        ]
        if visible_to is not None:
            clauses.append(
                "(c.owner = @principal OR ARRAY_CONTAINS(c.shares, @principal)"
                " OR c.publication.state = 'approved')"
            )
            params.append({"name": "@principal", "value": visible_to})
        if publication_state is not None:
            clauses.append("c.publication.state = @pub")
            params.append({"name": "@pub", "value": publication_state})
        if cursor is not None:
            clauses.append("c.sort_key < @after")
            params.append({"name": "@after", "value": decode_cursor(cursor)})
        # Only fixed clause text and parameter placeholders are interpolated.
        sql = (
            "SELECT TOP @limit * FROM c WHERE "  # noqa: S608
            + " AND ".join(clauses)
            + " ORDER BY c.sort_key DESC"
        )
        try:
            rows = [
                row
                async for row in self._container.query_items(
                    sql, parameters=params, partition_key=[customer_id, domain_id]
                )
            ]
        except Exception as exc:
            _raise_mapped(exc)
        reports = [_from_row(row) for row in rows]
        page = reports[:limit]
        next_cursor = encode_cursor(sort_key(page[-1])) if len(reports) > limit else None
        return Page[StoredReport](items=tuple(page), next_cursor=next_cursor)
