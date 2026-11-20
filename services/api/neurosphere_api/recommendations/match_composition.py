"""Composition helpers of the agent matcher (PRP-72 item 4), used by the data builder.

The matcher ranks with the composed ``AuthorizedSearch``, not with ``GraphQuery.search`` (which
drops the hit scores). The composed catalog graph refreshes the per-scope search index lazily at
search time, so a matcher that talks to the search port directly must trigger the same refresh
first: :class:`SyncedAgentMatcher` does that once per call and is otherwise an ``AgentMatcher``.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from neurosphere_contracts.recommendations.v1.agent_match_request import AgentMatchRequest
from neurosphere_core.catalog.protocol import GraphQuery
from neurosphere_core.recommendations.matching import AgentMatcher, MatchResult
from neurosphere_core.scope import IdentityScope
from neurosphere_core.search.protocol import AuthorizedSearch

from neurosphere_api.runtime.builders.search import IndexedGraphQuery

__all__ = ["SyncedAgentMatcher", "search_and_sync"]

Sync = Callable[[IdentityScope], Awaitable[None]]


def search_and_sync(graph: GraphQuery) -> tuple[AuthorizedSearch, Sync] | None:
    """The search port and the index refresh of a composed graph; ``None`` without search.

    Only the graph ``wrap_catalog_for_search`` composes carries a search index; a graph without
    one (``NS_SEARCH_PROVIDER`` unset, or a test fake) yields ``None``.
    """
    if not isinstance(graph, IndexedGraphQuery):
        return None
    inner: Any = graph._search  # the port the composed graph already ranks with
    if not isinstance(inner, AuthorizedSearch):
        return None
    return inner, graph._sync


class SyncedAgentMatcher(AgentMatcher):
    """``AgentMatcher`` that refreshes the caller's search index before ranking."""

    def __init__(self, *args: Any, sync: Sync | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._sync = sync

    async def match_detailed(
        self, scope: IdentityScope, domain: str, request: AgentMatchRequest
    ) -> MatchResult:
        if self._sync is not None and domain in scope.allowed_domains:
            await self._sync(scope)  # never raises: a failed refresh serves the stale index
        return await super().match_detailed(scope, domain, request)
