from __future__ import annotations

import asyncio
from itertools import count

from neurosphere_contracts.query.v1.budget import Budget
from neurosphere_core.search import SearchRequest
from neurosphere_core.search.fixture import FixtureSearchIndex, documents_from_catalog

from .search_helpers import cid, corpus, make_scope

SCOPE = make_scope([cid("domain", "alpha"), cid("domain", "beta")])


def _req(term: str, *, limit: int, timeout_ms: int = 5000) -> SearchRequest:
    return SearchRequest(term=term, budget=Budget(timeout_ms=timeout_ms, limit=limit, max_depth=0))


def test_limit_returns_partial_with_flag() -> None:
    index = FixtureSearchIndex(documents_from_catalog(corpus()))
    res = asyncio.run(index.search(SCOPE, _req("triage", limit=5)))
    assert len(res.hits) == 5
    assert res.matched == 24
    assert res.partial is True
    assert res.partial_reason == "limit"


def test_within_budget_is_not_partial() -> None:
    index = FixtureSearchIndex(documents_from_catalog(corpus()))
    res = asyncio.run(index.search(SCOPE, _req("triage", limit=100)))
    assert res.partial is False
    assert res.partial_reason is None
    assert res.matched == len(res.hits) == 24


def test_timeout_returns_partial_with_flag() -> None:
    ticks = count(0, 400)  # each clock read advances 0.4s of fake time

    def clock() -> float:
        return next(ticks) / 1000.0

    index = FixtureSearchIndex(documents_from_catalog(corpus()), clock=clock)
    res = asyncio.run(index.search(SCOPE, _req("triage", limit=100, timeout_ms=1000)))
    assert res.partial is True
    assert res.partial_reason == "timeout_ms"
    assert len(res.hits) < 24


def test_empty_term_returns_empty_result() -> None:
    index = FixtureSearchIndex(documents_from_catalog(corpus()))
    res = asyncio.run(index.search(SCOPE, _req("   ", limit=10)))
    assert res.hits == []
    assert res.partial is False
