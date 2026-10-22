"""PRP-21 item 3: federated summaries stay inside the caller's scope, cloud and boundary.

Harness: PRP-06 authz harness (dev-issuer tokens, in-memory policy store) with the real federation
router, in-process cells that run their OWN authenticator and scope source, and in-memory
aggregate stores. No network.
"""

import asyncio
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

import authz.authz_helpers as helpers  # pyright: ignore[reportMissingImports]
import httpx
import pytest
from neurosphere_api.federation import (
    PREFIX,
    FederationState,
    Federator,
    HttpCellClient,
    InProcessCellClient,
    SummaryCache,
    build_router,
    summary_cache_key,
)
from neurosphere_api.federation.client import CellClient
from neurosphere_core.aggregates import (
    CostPoint,
    ErrorPoint,
    InMemoryAggregateStore,
    aggregate_doc_id,
    format_bucket,
)
from neurosphere_core.auth.scope import Role
from neurosphere_core.errors import (
    CapabilityUnavailableError,
    DependencyTransientError,
    ForbiddenError,
)
from neurosphere_workers.federation import (
    CellRef,
    CellRegistry,
    CellSummary,
    DomainSummary,
)

ALICE: str = helpers.ALICE  # restricted: viewer on finance only
BOB: str = helpers.BOB  # viewer on finance, operations and hr
FINANCE: str = helpers.FINANCE
OPERATIONS: str = helpers.OPERATIONS
HR: str = helpers.HR
CUSTOMER: str = helpers.CUSTOMER
NOW = datetime.fromtimestamp(helpers.T0, UTC)
BOUNDARY = "boundary-1"


def cell_ref(cell_id: str, *, cloud: str = "commercial", boundary: str = BOUNDARY) -> CellRef:
    return CellRef.model_validate(
        {
            "cell_id": cell_id,
            "cloud": cloud,
            "boundary_id": boundary,
            "endpoint": f"https://{cell_id}.example.invalid",
        }
    )


CELL_A = cell_ref("cell-a")
CELL_B = cell_ref("cell-b")
CELL_GOV = cell_ref("cell-gov", cloud="government")
CELL_OTHER_BOUNDARY = cell_ref("cell-x", boundary="boundary-2")


def _start(days_ago: int) -> str:
    base = NOW.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_ago)
    return format_bucket(base)


def _ident(dom: str, metric: str, key: str) -> dict[str, Any]:
    start = _start(1)
    return {
        "id": aggregate_doc_id(CUSTOMER, dom, metric, "day", start, key),
        "customer_id": CUSTOMER,
        "domain_id": dom,
        "grain": "day",
        "bucket_start": start,
        "series_key": key,
        "watermark": format_bucket(NOW),
    }


def _cost(dom: str, amount: str, kind: str = "estimated") -> CostPoint:
    return CostPoint.model_validate(
        {
            **_ident(dom, "cost", f"{kind}:USD"),
            "kind": kind,
            "currency": "USD",
            "amount": Decimal(amount),
            "entry_count": 2,
            "known_count": 2,
            "complete": True,
        }
    )


def _errors(dom: str, requests: int, errs: int) -> ErrorPoint:
    return ErrorPoint.model_validate(
        {
            **_ident(dom, "errors", "errors"),
            "request_count": requests,
            "unknown_count": 0,
            "error_count": errs,
            "error_rate": errs / requests,
            "complete": True,
        }
    )


def store_with(*rows: tuple[str, str, int, int]) -> InMemoryAggregateStore:
    """One store; rows are (domain, cost, requests, errors)."""
    store = InMemoryAggregateStore()

    async def fill() -> None:
        for dom, amount, requests, errs in rows:
            docs = [_cost(dom, amount), _errors(dom, requests, errs)]
            await store.replace_bucket(CUSTOMER, dom, "day", docs[0].bucket_start, docs)

    asyncio.run(fill())
    return store


class SwitchableRevocation:
    def __init__(self) -> None:
        self.revoked = False

    async def is_revoked(self, principal_id: str, issued_at: datetime) -> bool:
        return self.revoked


class CountingClient:
    """Wraps a real cell client; records how often (and with which credential) it was called."""

    def __init__(self, inner: CellClient) -> None:
        self.inner = inner
        self.calls: list[str] = []

    async def fetch_summary(self, cell: CellRef, authorization: str | None, days: int) -> Any:
        self.calls.append(cell.cell_id)
        return await self.inner.fetch_summary(cell, authorization, days)


class FixedClient:
    """A cell that answers with a canned summary (or raises), regardless of the credential."""

    def __init__(self, answer: CellSummary | Exception) -> None:
        self.answer = answer
        self.calls = 0

    async def fetch_summary(self, cell: CellRef, authorization: str | None, days: int) -> Any:
        self.calls += 1
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


class Ticker:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@dataclass
class Env:
    h: Any
    revocation: SwitchableRevocation
    ticker: Ticker
    cache: SummaryCache
    clients: dict[str, Any]
    stores: dict[str, InMemoryAggregateStore] = field(default_factory=dict)

    def get(self, who: str | None, path: str = "/summary", **params: Any) -> Any:
        headers = self.h.auth(who) if who else {}
        return self.h.client.get(f"{PREFIX}{path}", params=params or None, headers=headers)


def build(
    *,
    registry_cells: tuple[CellRef, ...] = (CELL_A, CELL_B, CELL_GOV, CELL_OTHER_BOUNDARY),
    overrides: dict[str, Any] | None = None,
    ttl: float = 60.0,
    configure: bool = True,
) -> Env:
    revocation = SwitchableRevocation()
    h = helpers.harness(
        helpers.policy(ALICE, helpers.role(Role.VIEWER, FINANCE)),
        helpers.policy(BOB, helpers.role(Role.VIEWER, FINANCE, OPERATIONS, HR)),
        routers={PREFIX: build_router()},
        revocation_checker=revocation,
    )
    stores = {
        "cell-a": store_with((FINANCE, "10.00", 100, 4), (OPERATIONS, "5555.00", 500, 50)),
        "cell-b": store_with((OPERATIONS, "20.00", 40, 1), (HR, "7777.00", 900, 90)),
        "cell-gov": store_with((FINANCE, "31337.00", 1, 1)),
        "cell-x": store_with((FINANCE, "42424.00", 1, 1)),
    }
    clients: dict[str, Any] = {
        cell_id: CountingClient(
            InProcessCellClient(
                authenticator=h.validator,
                scope_source=h.deriver,
                reader=store,
                clock=lambda: NOW,
            )
        )
        for cell_id, store in stores.items()
    }
    clients.update(overrides or {})
    ticker = Ticker()
    cache = SummaryCache(ttl, clock=ticker)
    if configure:
        h.app.state.federation = FederationState(
            federator=Federator(
                serving_cloud="commercial",
                boundary_id=BOUNDARY,
                registry=CellRegistry(cells=registry_cells),
                clients=clients,
                clock=lambda: NOW,
            ),
            cache=cache,
            local_cell=CELL_A,
        )
        h.app.state.aggregate_reader = stores["cell-a"]
    return Env(
        h=h, revocation=revocation, ticker=ticker, cache=cache, clients=clients, stores=stores
    )


# ------------------------------------------------------------------ scope filtering


def test_restricted_principal_sees_nothing_of_other_domains() -> None:
    env = build()
    response = env.get(ALICE)
    assert response.status_code == 200, response.text
    body = response.json()
    assert [d["domain_id"] for d in body["domains"]] == [FINANCE]
    text = response.text
    for forbidden in (OPERATIONS, HR, "5555", "7777", "31337", "42424"):
        assert forbidden not in text
    finance = body["domains"][0]
    assert finance["request_count"] == 100
    assert finance["error_count"] == 4
    assert [(c["kind"], c["amount"]) for c in finance["costs"]] == [
        ("estimated", "10.000000000000")
    ]
    assert [(t["kind"], t["amount"]) for t in body["totals"]] == [("estimated", "10.000000000000")]


def test_wider_principal_merges_across_cells_per_domain() -> None:
    env = build()
    body = env.get(BOB).json()
    by_domain = {d["domain_id"]: d for d in body["domains"]}
    assert set(by_domain) == {FINANCE, OPERATIONS, HR}
    ops = by_domain[OPERATIONS]
    assert ops["request_count"] == 540  # cell-a 500 + cell-b 40
    assert ops["error_count"] == 51
    assert ops["costs"][0]["amount"] == "5575.000000000000"
    assert body["cells"] == [
        {"cell_id": "cell-a", "state": "ok"},
        {"cell_id": "cell-b", "state": "ok"},
    ]


def test_spoofed_domain_and_customer_fields_are_ignored() -> None:
    env = build()
    spoof = {"domain_id": HR, "customer_id": "fabrikam", "domains": OPERATIONS}
    headers = {**env.h.auth(ALICE), "X-Domain-Id": HR, "X-Customer-Id": "fabrikam"}
    response = env.h.client.get(f"{PREFIX}/summary", params=spoof, headers=headers)
    assert response.status_code == 200
    assert [d["domain_id"] for d in response.json()["domains"]] == [FINANCE]
    assert response.json()["customer_id"] == CUSTOMER
    cell_response = env.h.client.get(f"{PREFIX}/cell-summary", params=spoof, headers=headers)
    assert cell_response.status_code == 200
    assert [d["domain_id"] for d in cell_response.json()["domains"]] == [FINANCE]


def test_credential_is_forwarded_and_cell_derives_its_own_scope() -> None:
    seen: list[CellSummary] = []

    class Spy:
        inner: CellClient | None = None

        async def fetch_summary(self, cell: CellRef, authorization: str | None, days: int) -> Any:
            assert self.inner is not None
            result = await self.inner.fetch_summary(cell, authorization, days)
            seen.append(result)
            return result

    spy = Spy()
    env = build(overrides={"cell-a": spy})
    spy.inner = InProcessCellClient(
        authenticator=env.h.validator,
        scope_source=env.h.deriver,
        reader=env.stores["cell-a"],
        clock=lambda: NOW,
    )
    assert env.get(ALICE).status_code == 200
    # The cell, not the federator, produced a summary bound to the caller's scope hash.
    assert [s.cell_id for s in seen] == ["cell-a"]
    assert [d.domain_id for d in seen[0].domains] == [FINANCE]
    assert seen[0].scope_hash.startswith("sha256:")


def test_cell_response_cannot_widen_the_callers_view() -> None:
    leaking = CellSummary(
        cell_id="cell-b",
        cloud="commercial",
        boundary_id=BOUNDARY,
        customer_id=CUSTOMER,
        scope_hash="sha256:" + "0" * 64,
        window_start=NOW - timedelta(days=30),
        window_end=NOW,
        domains=(
            DomainSummary(domain_id=HR, request_count=9999, error_count=9, complete=True),
            DomainSummary(domain_id=FINANCE, request_count=1, error_count=0, complete=True),
        ),
    )
    env = build(overrides={"cell-b": FixedClient(leaking)})
    body = env.get(ALICE).json()
    assert HR not in json.dumps(body)
    assert "9999" not in json.dumps(body)
    assert [d["domain_id"] for d in body["domains"]] == [FINANCE]
    assert body["domains"][0]["request_count"] == 101  # cell-a 100 + cell-b 1


# ------------------------------------------------------------------ cloud boundary


def test_cross_cloud_cell_is_refused_with_capability_unavailable() -> None:
    env = build()
    response = env.get(ALICE, cells=["cell-gov"])
    assert response.status_code == 409
    assert response.json()["code"] == "capability_unavailable"
    assert env.clients["cell-gov"].calls == []  # no credential was ever sent there


def test_cross_boundary_cell_is_refused() -> None:
    env = build()
    response = env.get(ALICE, cells=["cell-a", "cell-x"])
    assert response.status_code == 409
    assert response.json()["code"] == "capability_unavailable"
    assert env.clients["cell-x"].calls == []


def test_default_selection_never_contacts_other_cloud_or_boundary() -> None:
    env = build()
    assert env.get(BOB).status_code == 200
    assert env.clients["cell-gov"].calls == []
    assert env.clients["cell-x"].calls == []
    assert env.clients["cell-a"].calls == ["cell-a"]


def test_federator_has_no_cross_cloud_merge_path() -> None:
    env = build()
    federator = cast(FederationState, env.h.app.state.federation).federator
    scope = asyncio.run(_derive_scope(env, ALICE))
    with pytest.raises(CapabilityUnavailableError) as raised:
        federator.select(["cell-gov"])
    assert raised.value.code == "capability_unavailable"
    with pytest.raises(CapabilityUnavailableError):
        asyncio.run(federator.summarize(scope, None, days=30, cells=[CELL_GOV]))
    gov_only = Federator(
        serving_cloud="commercial",
        boundary_id=BOUNDARY,
        registry=CellRegistry(cells=(CELL_GOV,)),
        clients={},
    )
    with pytest.raises(CapabilityUnavailableError):
        gov_only.select(None)


def test_cell_answering_for_another_cloud_is_discarded() -> None:
    gov_answer = CellSummary(
        cell_id="cell-b",
        cloud="government",
        boundary_id=BOUNDARY,
        customer_id=CUSTOMER,
        scope_hash="sha256:" + "1" * 64,
        window_start=NOW - timedelta(days=30),
        window_end=NOW,
        domains=(DomainSummary(domain_id=FINANCE, request_count=777, complete=True),),
    )
    env = build(overrides={"cell-b": FixedClient(gov_answer)})
    response = env.get(ALICE)
    assert response.status_code == 409
    assert response.json()["code"] == "capability_unavailable"
    assert "777" not in response.text


def test_scope_from_another_cloud_is_refused() -> None:
    env = build(registry_cells=(CELL_A,))
    federation = cast(FederationState, env.h.app.state.federation)
    other = Federator(
        serving_cloud="government",
        boundary_id=BOUNDARY,
        registry=CellRegistry(cells=(cell_ref("cell-g", cloud="government"),)),
        clients={},
    )
    env.h.app.state.federation = FederationState(
        federator=other, cache=federation.cache, local_cell=None
    )
    response = env.get(ALICE)
    assert response.status_code == 409
    assert response.json()["code"] == "capability_unavailable"


# ------------------------------------------------------------------ cache and revocation


def test_cache_key_differs_per_scope_and_embeds_scope_hash() -> None:
    env = build()
    scope_a = asyncio.run(_derive_scope(env, ALICE))
    scope_b = asyncio.run(_derive_scope(env, BOB))
    key_a = summary_cache_key(scope_a, days=30, cell_ids=["cell-a"])
    key_b = summary_cache_key(scope_b, days=30, cell_ids=["cell-a"])
    assert key_a != key_b
    assert scope_a.scope_hash in key_a
    assert scope_b.scope_hash in key_b
    assert summary_cache_key(scope_a, days=7, cell_ids=["cell-a"]) != key_a


def test_cached_summary_is_not_shared_between_scopes() -> None:
    env = build()
    narrow = env.get(ALICE).json()
    wide = env.get(BOB).json()
    again = env.get(ALICE).json()
    assert len(narrow["domains"]) == 1
    assert len(wide["domains"]) == 3
    assert again == narrow
    assert env.clients["cell-a"].calls == ["cell-a", "cell-a"]  # alice, bob; alice's repeat hit


def test_revoked_principal_gets_403_within_ttl_despite_warm_cache() -> None:
    env = build(ttl=60.0)
    assert env.get(ALICE).status_code == 200
    calls_before = list(env.clients["cell-a"].calls)
    env.revocation.revoked = True
    env.ticker.now += 5.0  # well inside the cache TTL
    response = env.get(ALICE)
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"
    assert env.clients["cell-a"].calls == calls_before
    assert "10.0" not in response.text


def test_cache_entry_expires_after_ttl() -> None:
    env = build(ttl=10.0)
    assert env.get(ALICE).status_code == 200
    assert env.get(ALICE).status_code == 200
    assert env.clients["cell-a"].calls == ["cell-a"]
    env.ticker.now += 11.0
    assert env.get(ALICE).status_code == 200
    assert env.clients["cell-a"].calls == ["cell-a", "cell-a"]


# ------------------------------------------------------------------ fail closed / honesty


def test_unauthenticated_is_401_and_no_permission_is_403() -> None:
    env = build()
    assert env.get(None).status_code == 401
    assert env.get(helpers.NOBODY).status_code in (401, 403)


def test_missing_federation_config_is_503() -> None:
    env = build(configure=False)
    response = env.get(ALICE)
    assert response.status_code == 503
    assert response.json()["code"] == "dependency_transient"


def test_failed_cell_makes_summary_incomplete_not_zero() -> None:
    env = build(overrides={"cell-b": FixedClient(DependencyTransientError("down"))})
    body = env.get(BOB).json()
    assert {c["cell_id"]: c["state"] for c in body["cells"]} == {
        "cell-a": "ok",
        "cell-b": "unavailable",
    }
    assert body["complete"] is False
    assert "7777" not in json.dumps(body)  # cell-b's HR data never arrived
    hr_rows = [d for d in body["domains"] if d["domain_id"] == HR]
    assert all(r["request_count"] is None and r["costs"] == [] for r in hr_rows)  # unknown, not 0


def test_all_cells_failing_is_503() -> None:
    down = DependencyTransientError("down")
    env = build(overrides={"cell-a": FixedClient(down), "cell-b": FixedClient(down)})
    assert env.get(ALICE).status_code == 503


def test_cell_that_denies_the_caller_contributes_nothing() -> None:
    env = build(overrides={"cell-b": FixedClient(ForbiddenError("no access"))})
    body = env.get(BOB).json()
    assert {c["cell_id"]: c["state"] for c in body["cells"]}["cell-b"] == "denied"
    assert "7777" not in json.dumps(body)  # cell-b's HR data never arrived
    hr_rows = [d for d in body["domains"] if d["domain_id"] == HR]
    assert all(r["request_count"] is None and r["costs"] == [] for r in hr_rows)  # unknown, not 0


def test_every_route_declares_a_permission() -> None:
    from neurosphere_api.authz import undeclared_routes

    env = build()
    assert tuple(undeclared_routes(env.h.app)) == ()


# ------------------------------------------------------------------ http client


def test_http_client_forwards_only_the_credential() -> None:
    seen: list[httpx.Request] = []
    summary = CellSummary(
        cell_id="cell-a",
        cloud="commercial",
        boundary_id=BOUNDARY,
        customer_id=CUSTOMER,
        scope_hash="sha256:" + "2" * 64,
        window_start=NOW - timedelta(days=30),
        window_end=NOW,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=summary.model_dump_json())

    async def run() -> CellSummary:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await HttpCellClient(http).fetch_summary(CELL_A, "Bearer test-token", 7)

    result = asyncio.run(run())
    assert result.cell_id == "cell-a"
    request = seen[0]
    assert request.url.host == "cell-a.example.invalid"
    assert request.url.path == "/api/v1/federation/cell-summary"
    assert dict(request.url.params) == {"days": "7"}
    assert request.headers["authorization"] == "Bearer test-token"
    assert "domain" not in str(request.url).lower()
    assert "customer" not in str(request.url).lower()


@pytest.mark.parametrize(
    ("status", "expected"),
    [(403, "forbidden"), (401, "unauthorized"), (500, "dependency_transient")],
)
def test_http_client_maps_cell_errors(status: int, expected: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status)

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            await HttpCellClient(http).fetch_summary(CELL_A, "Bearer x", 7)

    with pytest.raises(Exception) as raised:
        asyncio.run(run())
    assert getattr(raised.value, "code", None) == expected


async def _derive_scope(env: Env, who: str) -> Any:
    authorization = env.h.auth(who)["Authorization"]
    claims = await env.h.validator.authenticate(authorization)
    derivation = await env.h.deriver.derive(claims)
    return derivation.scope
