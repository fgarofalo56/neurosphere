"""Azure AI Search implementation of ``AuthorizedSearch``.

Authorization is server-side and happens in the service query, before ranking: the OData filter
is built only from the server-derived scope (see ``filters``), so out-of-scope documents are
never candidates. Results are re-checked against the scope as defense in depth. Authentication
is Entra ID / managed identity only: the client factory takes an ``AsyncTokenCredential`` and
there is no key or connection-string path. The query is lexical (simple query syntax over
tokenized words); semantic ranker, vector and agentic retrieval are not used, so no Government
claim beyond the ``ai_search.base`` capability row is made.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from typing import Any, Final, Literal, Protocol

from azure.core.credentials_async import AsyncTokenCredential
from azure.search.documents.aio import SearchClient
from neurosphere_contracts.scope.v1.identity_scope import IdentityScope

from neurosphere_core.cloud import CloudName, CloudProfile, profile_for
from neurosphere_core.errors import CapabilityUnavailableError
from neurosphere_core.search.azure.filters import (
    FIELD_CLOUD,
    FIELD_CUSTOMER,
    FIELD_DOMAIN,
    FIELD_ID,
    build_filter,
    build_search_text,
)
from neurosphere_core.search.protocol import SearchHit, SearchRequest, SearchResult

__all__ = ["AzureAuthorizedSearch", "SearchBackend", "create_search_client"]

_SCORE_DECIMALS: Final = 9
_SELECT: Final = [FIELD_ID, FIELD_DOMAIN, FIELD_CUSTOMER, FIELD_CLOUD]
_GOV_AUDIENCE: Final = "https://search.azure.us"


class SearchBackend(Protocol):
    """The slice of ``azure.search.documents.aio.SearchClient`` used here (fakeable offline)."""

    async def search(self, search_text: str | None = None, **kwargs: Any) -> Any:
        """Return an async pager of dict documents with ``@search.score`` and ``get_count()``."""
        ...


def create_search_client(
    profile: CloudProfile,
    *,
    service: str,
    index_name: str,
    credential: AsyncTokenCredential,
) -> SearchClient:
    """Build an Entra-authenticated client; the host comes only from the cloud profile."""
    audience = _GOV_AUDIENCE if profile.cloud is CloudName.GOVERNMENT else None
    kwargs: dict[str, Any] = {"audience": audience} if audience else {}
    return SearchClient(profile.search_endpoint(service), index_name, credential, **kwargs)


class AzureAuthorizedSearch:
    """``AuthorizedSearch`` over an Azure AI Search index of catalog entity documents."""

    def __init__(self, backend: SearchBackend, *, cloud: Literal["commercial", "government"]):
        self._backend = backend
        self._cloud = cloud
        profile_for(CloudName(cloud))  # the cloud must name a known profile

    @property
    def cloud(self) -> str:
        return self._cloud

    async def search(self, scope: IdentityScope, request: SearchRequest) -> SearchResult:
        if scope.cloud != self._cloud:
            # Never route one cloud's scope to the other cloud's endpoint.
            raise CapabilityUnavailableError(
                "cloud_mismatch",
                f"search backend serves {self._cloud}; scope is {scope.cloud}",
            )
        odata_filter = build_filter(scope, request)
        text = build_search_text(request.term)
        if odata_filter is None or text is None:
            return SearchResult(hits=[], matched=0, partial=False)

        limit = request.budget.limit
        collected: list[tuple[float, str]] = []
        matched = 0
        timed_out = False
        allowed = {d.root for d in scope.allowed_domains}
        granted = {g.resource_id.root for g in scope.allowed_resources if "read" in g.permissions}
        try:
            async with asyncio.timeout(request.budget.timeout_ms / 1000.0):
                pager = await self._backend.search(
                    text,
                    filter=odata_filter,
                    query_type="simple",
                    search_mode="any",
                    select=_SELECT,
                    top=limit + 1,
                    include_total_count=True,
                )
                async for doc in _aiter(pager):
                    if not _doc_in_scope(doc, scope, allowed, granted):
                        continue  # defense in depth; the filter should have excluded it
                    collected.append(
                        (round(float(doc["@search.score"]), _SCORE_DECIMALS), doc["id"])
                    )
                count = await pager.get_count() if hasattr(pager, "get_count") else None
                matched = count if isinstance(count, int) else len(collected)
        except TimeoutError:
            timed_out = True
            matched = len(collected)

        collected.sort(key=lambda p: (-p[0], p[1]))  # same tie-break as the fixture
        matched = max(matched, len(collected))
        reason: Literal["limit", "timeout_ms"] | None = None
        if timed_out:
            reason = "timeout_ms"
        elif matched > limit:
            reason = "limit"
        return SearchResult(
            hits=[SearchHit(id=i, score=s) for s, i in collected[:limit]],
            matched=matched,
            partial=reason is not None,
            partial_reason=reason,
        )


async def _aiter(pager: Any) -> AsyncIterator[Mapping[str, Any]]:
    async for doc in pager:
        yield doc


def _doc_in_scope(
    doc: Mapping[str, Any], scope: IdentityScope, allowed: set[str], granted: set[str]
) -> bool:
    return (
        doc.get(FIELD_CLOUD) == scope.cloud
        and doc.get(FIELD_CUSTOMER) == scope.customer_id
        and isinstance(doc.get(FIELD_ID), str)
        and (doc.get(FIELD_DOMAIN) in allowed or doc[FIELD_ID] in granted)
    )
