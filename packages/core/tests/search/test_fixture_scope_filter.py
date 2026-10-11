from __future__ import annotations

import asyncio

import pytest
from neurosphere_contracts.query.v1.budget import Budget
from neurosphere_contracts.scope.v1.identity_scope import IdentityScope
from neurosphere_core.search import SearchFilters, SearchRequest
from neurosphere_core.search.fixture import FixtureSearchIndex, documents_from_catalog
from pydantic import ValidationError

from .search_helpers import cid, corpus, make_scope

BUDGET = Budget(timeout_ms=5000, limit=100, max_depth=0)
ALPHA = cid("domain", "alpha")
BETA = cid("domain", "beta")


def _ids(scope: IdentityScope, term: str, filters: SearchFilters | None = None) -> set[str]:
    index = FixtureSearchIndex(documents_from_catalog(corpus()))
    req = SearchRequest(term=term, filters=filters or SearchFilters(), budget=BUDGET)
    return {h.id for h in asyncio.run(index.search(scope, req)).hits}


def _beta_ids() -> set[str]:
    return {d["id"] for d in corpus() if ":beta" in d["id"]}


@pytest.mark.parametrize("term", ["triage", "beta", "agent", "domain", "routes support tickets"])
def test_cross_domain_documents_never_returned(term: str) -> None:
    beta = _beta_ids()
    assert len(beta) >= 10
    got = _ids(make_scope([ALPHA]), term)
    assert got or term == "beta"
    assert not got & beta


def test_filters_cannot_widen_scope() -> None:
    got = _ids(make_scope([ALPHA]), "triage", SearchFilters(domain_ids=[ALPHA, BETA]))
    assert got
    assert not got & _beta_ids()


def test_empty_scope_returns_nothing() -> None:
    assert _ids(make_scope([]), "triage") == set()


def test_other_customer_or_cloud_scope_returns_nothing() -> None:
    assert _ids(make_scope([ALPHA], customer="other"), "triage") == set()
    assert _ids(make_scope([ALPHA], cloud="government"), "triage") == set()


def test_resource_grant_admits_single_document() -> None:
    one = cid("agent", "beta-03")
    got = _ids(make_scope([ALPHA], grants=[one]), "triage")
    assert one in got
    assert got & _beta_ids() == {one}


def test_out_of_scope_docs_do_not_change_scores() -> None:
    scope = make_scope([ALPHA])
    docs = documents_from_catalog(corpus())
    alpha_only = [d for d in docs if d.domain_id == ALPHA]
    req = SearchRequest(term="triage tickets", budget=BUDGET)
    a = asyncio.run(FixtureSearchIndex(docs).search(scope, req))
    b = asyncio.run(FixtureSearchIndex(alpha_only).search(scope, req))
    assert a.hits == b.hits


def test_term_is_never_evaluated() -> None:
    got = _ids(make_scope([ALPHA]), "__import__('os').system('x') OR zz=zz; DROP")
    assert got == set()


def test_unknown_filter_field_rejected() -> None:
    with pytest.raises(ValidationError):
        SearchFilters.model_validate({"raw": "x"})
