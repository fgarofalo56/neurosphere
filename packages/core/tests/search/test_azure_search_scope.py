"""Azure search: server-side scope filter, injection resistance, parity, cache keys, gating."""

from __future__ import annotations

import ast
import asyncio
import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from neurosphere_contracts.query.v1.budget import Budget
from neurosphere_contracts.scope.v1.identity_scope import IdentityScope
from neurosphere_core.capabilities import CapabilityResult, matrix_from_rows
from neurosphere_core.errors import CapabilityUnavailableError
from neurosphere_core.search import SearchFilters, SearchRequest
from neurosphere_core.search.azure import (
    AzureAuthorizedSearch,
    FallbackAuthorizedSearch,
    azure_search_capability,
    build_filter,
    cache_key,
    require_azure_search,
)
from neurosphere_core.search.fixture import FixtureSearchIndex, documents_from_catalog
from neurosphere_core.search.fixture.index import SearchDocument, tokenize

from .search_helpers import cid, corpus, make_scope

BUDGET = Budget(timeout_ms=5000, limit=100, max_depth=0)
ALPHA = cid("domain", "alpha")
BETA = cid("domain", "beta")

# ---------------------------------------------------------------- fake service


class _Pager:
    def __init__(self, rows: list[dict[str, Any]], count: int) -> None:
        self._rows = rows
        self._count = count

    def __aiter__(self) -> AsyncIterator[dict[str, Any]]:
        async def gen() -> AsyncIterator[dict[str, Any]]:
            for row in self._rows:
                yield row

        return gen()

    async def get_count(self) -> int:
        return self._count


_TOKEN = re.compile(r"\s*(?:(\()|(\))|(,)|'((?:[^']|'')*)'|([A-Za-z_][A-Za-z0-9_.]*))")


def _tokenize_odata(text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    pos = 0
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m:
            raise ValueError(f"unparseable filter at {pos}: {text[pos:]!r}")
        pos = m.end()
        if m.group(1):
            out.append(("(", "("))
        elif m.group(2):
            out.append((")", ")"))
        elif m.group(3):
            out.append((",", ","))
        elif m.group(4) is not None:
            out.append(("str", m.group(4).replace("''", "'")))
        else:
            out.append(("id", m.group(5)))
    return out


def evaluate_filter(text: str, doc: dict[str, Any]) -> bool:
    """A strict evaluator for the OData subset the product emits; anything else raises."""
    toks = _tokenize_odata(text)
    i = 0

    def peek() -> tuple[str, str]:
        return toks[i] if i < len(toks) else ("end", "")

    def take(kind: str, value: str | None = None) -> str:
        nonlocal i
        k, v = peek()
        if k != kind or (value is not None and v != value):
            raise ValueError(f"expected {kind} {value!r}, got {k} {v!r}")
        i += 1
        return v

    def parse_or() -> bool:
        left = parse_and()
        while peek() == ("id", "or"):
            take("id", "or")
            right = parse_and()
            left = left or right
        return left

    def parse_and() -> bool:
        left = parse_atom()
        while peek() == ("id", "and"):
            take("id", "and")
            right = parse_atom()
            left = left and right
        return left

    def parse_atom() -> bool:
        if peek()[0] == "(":
            take("(")
            value = parse_or()
            take(")")
            return value
        name = take("id")
        if name == "search.in":
            take("(")
            field = take("id")
            take(",")
            values = take("str")
            take(",")
            delim = take("str")
            take(")")
            return doc.get(field) in values.split(delim)
        take("id", "eq")
        return doc.get(name) == take("str")

    result = parse_or()
    if i != len(toks):
        raise ValueError(f"trailing tokens: {toks[i:]}")
    return result


class FakeSearchClient:
    """Evaluates the filter over a sandbox doc set; records every call."""

    def __init__(self, docs: list[SearchDocument]) -> None:
        self.docs = [d.model_dump() for d in docs]
        self.calls: list[dict[str, Any]] = []
        self.delay = 0.0

    async def search(self, search_text: str | None = None, **kwargs: Any) -> _Pager:
        self.calls.append({"search_text": search_text, **kwargs})
        if self.delay:
            await asyncio.sleep(self.delay)
        terms = set((search_text or "").split())
        matches: list[tuple[float, dict[str, Any]]] = []
        for doc in self.docs:
            if not evaluate_filter(kwargs["filter"], doc):
                continue
            toks = tokenize(doc["text"])
            score = float(sum(toks.count(t) for t in terms))
            if score > 0:
                matches.append((score, doc))
        matches.sort(key=lambda p: -p[0])
        top = kwargs["top"]
        rows = [{**d, "@search.score": s} for s, d in matches[:top]]
        return _Pager(rows, len(matches))


def _docs() -> list[SearchDocument]:
    return documents_from_catalog(corpus())


def _req(term: str = "triage", filters: SearchFilters | None = None, **b: int) -> SearchRequest:
    budget = Budget(**{"timeout_ms": 5000, "limit": 100, "max_depth": 0, **b})
    return SearchRequest(term=term, filters=filters or SearchFilters(), budget=budget)


def _azure(
    client: FakeSearchClient | None = None,
) -> tuple[AzureAuthorizedSearch, FakeSearchClient]:
    fake = client or FakeSearchClient(_docs())
    return AzureAuthorizedSearch(fake, cloud="commercial"), fake


def _ids(scope: IdentityScope, req: SearchRequest) -> set[str]:
    svc, _ = _azure()
    return {h.id for h in asyncio.run(svc.search(scope, req)).hits}


def _beta_ids() -> set[str]:
    return {d["id"] for d in corpus() if ":beta" in d["id"]}


# ------------------------------------------------------------------- filters


def test_filter_string_is_built_from_scope_only() -> None:
    flt = build_filter(make_scope([ALPHA]), _req("anything; or 1 eq 1"))
    assert flt is not None
    assert flt.startswith("cloud eq 'commercial' and customer_id eq 'acme' and ")
    assert f"search.in(domain_id, '{ALPHA}', '|')" in flt
    assert "anything" not in flt
    assert "1 eq 1" not in flt


def test_no_effective_domains_returns_empty_without_calling_service() -> None:
    svc, fake = _azure()
    result = asyncio.run(svc.search(make_scope([]), _req()))
    assert result.hits == [] and result.matched == 0 and not result.partial
    assert fake.calls == []


def test_empty_term_does_not_call_service() -> None:
    svc, fake = _azure()
    assert asyncio.run(svc.search(make_scope([ALPHA]), _req("  ...  "))).hits == []
    assert fake.calls == []


def test_out_of_scope_requested_domain_yields_empty_not_error() -> None:
    scope = make_scope([ALPHA])
    req = _req(filters=SearchFilters(domain_ids=[BETA]))
    assert build_filter(scope, req) is None
    svc, fake = _azure()
    result = asyncio.run(svc.search(scope, req))
    assert result.hits == [] and fake.calls == []


def test_requested_domains_only_narrow() -> None:
    scope = make_scope([ALPHA, BETA])
    got = _ids(scope, _req(filters=SearchFilters(domain_ids=[ALPHA])))
    assert got and not got & _beta_ids()
    wide = _ids(make_scope([ALPHA]), _req(filters=SearchFilters(domain_ids=[ALPHA, BETA])))
    assert wide and not wide & _beta_ids()


@pytest.mark.parametrize(
    "evil",
    [
        "x' or domain_id ne 'zzz",
        "commercial:acme:cat:domain:alpha' or '1' eq '1",
        "a') or (domain_id eq 'commercial:acme:cat:domain:beta",
        "commercial:acme:cat:domain:beta' eq domain_id",
        "$filter=1 eq 1",
        "a/b/any(x: true)",
        "commercial:acme:cat:domain:béta",
        "commercial:acme:cat:domain:beta|commercial:acme:cat:domain:alpha",
        "commercial:acme:cat:domain:beta\n",
        "",
    ],
)
def test_filter_injection_never_widens(evil: str) -> None:
    beta = _beta_ids()
    # Scope-side injection: a hostile domain/customer value inside the scope is dropped.
    try:
        scope = make_scope([ALPHA, evil])
    except Exception:
        scope = None
    if scope is not None:
        got = _ids(scope, _req())
        assert got and not got & beta
        flt = build_filter(scope, _req())
        assert (flt is not None and evil not in flt) or evil == ""
    # Request-side injection: SearchFilters validates IDs; anything that passes is quoted-safe.
    try:
        filters = SearchFilters(domain_ids=[ALPHA, evil])
    except Exception:
        filters = None
    if filters is not None:
        got = _ids(make_scope([ALPHA]), _req(filters=filters))
        assert not got & beta
    # Term-side injection never reaches the filter.
    got = _ids(make_scope([ALPHA]), _req(f"triage {evil}"))
    assert not got & beta


def test_hostile_customer_id_in_scope_returns_nothing() -> None:
    # The contract rejects this value; model_copy skips validation to test our own guard.
    scope = make_scope([ALPHA]).model_copy(update={"customer_id": "acme' or '1' eq '1"})
    assert build_filter(scope, _req()) is None
    base = make_scope([ALPHA])
    bad = type(base.allowed_domains[0]).model_construct(root=ALPHA + "' or 1 eq 1")
    hostile = base.model_copy(update={"allowed_domains": [bad]})
    assert build_filter(hostile, _req()) is None


def test_term_operators_are_stripped_to_words() -> None:
    svc, fake = _azure()
    asyncio.run(svc.search(make_scope([ALPHA]), _req('triage* OR "x" -y /re/ $top=1')))
    assert fake.calls[0]["search_text"] == "1 or re top triage x y"
    assert fake.calls[0]["query_type"] == "simple"


def test_cross_domain_documents_never_returned_end_to_end() -> None:
    beta = _beta_ids()
    for term in ("triage", "agent", "domain", "beta", "routes support tickets"):
        got = _ids(make_scope([ALPHA]), _req(term))
        assert not got & beta


def test_other_customer_or_cloud_returns_nothing() -> None:
    assert _ids(make_scope([ALPHA], customer="other"), _req()) == set()
    svc, _ = _azure()
    with pytest.raises(CapabilityUnavailableError):
        asyncio.run(svc.search(make_scope([ALPHA], cloud="government"), _req()))


def test_read_grants_are_honoured_and_bounded_by_scope_customer() -> None:
    grant = cid("agent", "beta-03")
    got = _ids(make_scope([ALPHA], grants=[grant]), _req())
    assert grant in got
    assert not (got - {grant}) & _beta_ids()


def test_defense_in_depth_drops_out_of_scope_rows() -> None:
    class Leaky(FakeSearchClient):
        async def search(self, search_text: str | None = None, **kwargs: Any) -> _Pager:
            kwargs["filter"] = "cloud eq 'commercial'"  # a broken service ignoring the scope
            return await super().search(search_text, **kwargs)

    svc, _ = _azure(Leaky(_docs()))
    got = {h.id for h in asyncio.run(svc.search(make_scope([ALPHA]), _req())).hits}
    assert got and not got & _beta_ids()


# --------------------------------------------------------------------- budget


def test_limit_partial_semantics_match_fixture() -> None:
    scope = make_scope([ALPHA])
    req = _req(limit=5)
    azure_res = asyncio.run(_azure()[0].search(scope, req))
    fix_res = asyncio.run(FixtureSearchIndex(_docs()).search(scope, req))
    assert len(azure_res.hits) == len(fix_res.hits) == 5
    assert azure_res.matched == fix_res.matched
    assert azure_res.partial is fix_res.partial is True
    assert azure_res.partial_reason == fix_res.partial_reason == "limit"


def test_budget_maps_to_top_and_timeout_is_partial() -> None:
    svc, fake = _azure()
    asyncio.run(svc.search(make_scope([ALPHA]), _req(limit=7)))
    assert fake.calls[0]["top"] == 8
    fake.delay = 0.5
    result = asyncio.run(svc.search(make_scope([ALPHA]), _req(timeout_ms=50)))
    assert result.partial and result.partial_reason == "timeout_ms"


# ------------------------------------------------------------ fixture parity


@pytest.mark.parametrize(
    "scope_domains", [[ALPHA], [BETA], [ALPHA, BETA], []], ids=["a", "b", "ab", "none"]
)
@pytest.mark.parametrize("term", ["triage", "agent 03", "routes support tickets", "domain", "zzz"])
def test_same_id_set_as_fixture_within_documented_tolerance(
    scope_domains: list[str], term: str
) -> None:
    scope = make_scope(scope_domains)
    req = _req(term)
    fixture = asyncio.run(FixtureSearchIndex(_docs()).search(scope, req))
    azure = asyncio.run(_azure()[0].search(scope, req))
    # Tolerance (see fallback.py): same ID set and matched; order may differ among ties.
    assert {h.id for h in azure.hits} == {h.id for h in fixture.hits}
    assert azure.matched == fixture.matched
    assert azure.partial == fixture.partial


# ------------------------------------------------------------------ cache key


def test_cache_key_differs_by_scope_and_is_stable() -> None:
    req = _req()
    a, b = make_scope([ALPHA]), make_scope([ALPHA, BETA])
    assert cache_key(a, req) != cache_key(b, req)
    assert cache_key(a, req) == cache_key(make_scope([ALPHA]), _req())
    assert cache_key(make_scope([ALPHA], customer="other"), req) != cache_key(a, req)
    assert cache_key(a, req) != cache_key(a, _req("beta"))
    assert cache_key(a, req) != cache_key(a, _req(limit=3))
    # the declared scope_hash field is not trusted: same members, same key
    assert cache_key(a, req) == cache_key(
        a.model_copy(update={"scope_hash": "sha256:" + "0" * 64}), req
    )


# ------------------------------------------------------- gating and fallback


def _cap(cloud: str, region: str) -> CapabilityResult:
    return azure_search_capability(cloud, region)


def test_government_without_verified_row_is_disabled_with_reason() -> None:
    cap = azure_search_capability("government", "usgovvirginia", matrix=matrix_from_rows([]))
    assert cap.status == "disabled" and cap.reason_code == "not_verified" and cap.reason
    with pytest.raises(CapabilityUnavailableError):
        require_azure_search(cap)
    fixture = FixtureSearchIndex(_docs())
    azure, fake = _azure()
    wrapper = FallbackAuthorizedSearch(fixture, azure=azure, capability=cap)
    assert not wrapper.azure_enabled and wrapper.disabled_reason == cap.reason
    asyncio.run(wrapper.search(make_scope([ALPHA], cloud="government"), _req()))
    assert fake.calls == []


def test_commercial_unverified_row_is_disabled() -> None:
    cap = _cap("commercial", "marscentral")
    assert cap.status == "disabled" and cap.reason
    with pytest.raises(CapabilityUnavailableError) as exc:
        require_azure_search(cap)
    assert exc.value.reason == "not_verified"


def test_government_resolution_only_uses_government_rows() -> None:
    cap = _cap("government", "usgovvirginia")
    assert cap.row_id is None or ".government." in cap.row_id


def test_fallback_uses_fixture_when_disabled_or_unconfigured() -> None:
    fixture = FixtureSearchIndex(_docs())
    azure, fake = _azure()
    scope, req = make_scope([ALPHA]), _req()
    expected = asyncio.run(fixture.search(scope, req))

    disabled = FallbackAuthorizedSearch(
        fixture, azure=azure, capability=_cap("commercial", "marscentral")
    )
    assert not disabled.azure_enabled and disabled.disabled_reason
    assert asyncio.run(disabled.search(scope, req)) == expected

    unconfigured = FallbackAuthorizedSearch(fixture)
    assert unconfigured.disabled_reason == "azure search is not configured"
    assert asyncio.run(unconfigured.search(scope, req)) == expected
    assert fake.calls == []


def test_fallback_uses_azure_when_supported_and_same_cloud() -> None:
    fixture = FixtureSearchIndex(_docs())
    azure, fake = _azure()
    supported = _cap("government", "usgovvirginia").model_copy(update={"status": "supported"})
    wrapper = FallbackAuthorizedSearch(fixture, azure=azure, capability=supported)
    asyncio.run(wrapper.search(make_scope([ALPHA]), _req()))
    assert len(fake.calls) == 1
    # a Government scope is never sent to the commercial-configured backend
    asyncio.run(wrapper.search(make_scope([ALPHA], cloud="government"), _req()))
    assert len(fake.calls) == 1


# --------------------------------------------------------------- no key auth


def test_no_key_or_connection_string_auth_path() -> None:
    root = Path(__file__).resolve().parents[2] / "neurosphere_core" / "search" / "azure"
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom | ast.Import):
                names = [a.name for a in node.names] + [getattr(node, "module", "") or ""]
                assert not any("AzureKeyCredential" in n for n in names), path.name
            if isinstance(node, ast.arg):
                assert node.arg.lower() not in {"key", "api_key", "connection_string"}
