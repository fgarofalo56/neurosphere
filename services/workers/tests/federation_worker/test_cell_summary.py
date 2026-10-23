"""PRP-21 item 3: per-cell scope-filtered summaries (no network, in-memory aggregate store)."""

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

import pytest
from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.aggregates import (
    AggregateWindow,
    CostPoint,
    ErrorPoint,
    Grain,
    InMemoryAggregateStore,
    QueryResult,
    aggregate_doc_id,
    format_bucket,
)
from neurosphere_core.errors import CapabilityUnavailableError
from neurosphere_core.scope import IdentityScope
from neurosphere_workers.federation import (
    CellRef,
    CellRegistry,
    CostTotal,
    combine_cost_totals,
    compute_cell_summary,
)
from pydantic import ValidationError

NOW = datetime(2027, 1, 15, 8, 30, tzinfo=UTC)
CUSTOMER = "contoso"


def domain(name: str, cloud: str = "commercial") -> str:
    return f"{cloud}:{CUSTOMER}:catalog:domain:{name}"


FINANCE = domain("finance")
HR = domain("hr")


def make_scope(*domains: str, cloud: str = "commercial", member_of: tuple[str, ...] = ()) -> Any:
    """A server-derived-shaped scope: viewer role on ``domains``, membership in ``member_of``."""
    contract = ContractScope.model_validate(
        {
            "schema_version": "1.0.0",
            "cloud": cloud,
            "customer_id": CUSTOMER,
            "principal": {
                "principal_id": f"{cloud}:{CUSTOMER}:entra:person:psn_0123456789abcdef",
                "principal_pseudonym": "p-7f3a9c21",
                "principal_kind": "user",
            },
            "roles": [{"role": "viewer", "domain_ids": list(domains)}],
            "allowed_domains": list(member_of or domains),
            "allowed_resources": [],
            "policy_version": "v1",
            "derived_at": "2027-01-15T00:00:00Z",
            "scope_hash": "sha256:" + hashlib.sha256(",".join(domains).encode()).hexdigest(),
        }
    )
    return IdentityScope._from_verified_contract(contract)  # pyright: ignore[reportPrivateUsage]


def cell(cloud: str = "commercial", boundary: str = "b1", cell_id: str = "cell-a") -> CellRef:
    return CellRef.model_validate(
        {
            "cell_id": cell_id,
            "cloud": cloud,
            "boundary_id": boundary,
            "endpoint": "https://cell-a.example.invalid",
        }
    )


def _start(days_ago: int) -> str:
    base = NOW.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_ago)
    return format_bucket(base)


def _ident(dom: str, metric: str, start: str, key: str) -> dict[str, Any]:
    return {
        "id": aggregate_doc_id(CUSTOMER, dom, metric, "day", start, key),
        "customer_id": CUSTOMER,
        "domain_id": dom,
        "grain": "day",
        "bucket_start": start,
        "series_key": key,
        "watermark": format_bucket(NOW),
    }


def cost(dom: str, days_ago: int, amount: str | None, kind: str = "estimated") -> CostPoint:
    start = _start(days_ago)
    return CostPoint.model_validate(
        {
            **_ident(dom, "cost", start, f"{kind}:USD"),
            "kind": kind,
            "currency": "USD",
            "amount": None if amount is None else Decimal(amount),
            "entry_count": 4,
            "known_count": 0 if amount is None else 4,
            "complete": amount is not None,
        }
    )


def errors(dom: str, days_ago: int, requests: int, errs: int | None) -> ErrorPoint:
    start = _start(days_ago)
    return ErrorPoint.model_validate(
        {
            **_ident(dom, "errors", start, "errors"),
            "request_count": requests,
            "unknown_count": 0,
            "error_count": errs,
            "error_rate": None if errs is None else errs / requests,
            "complete": errs is not None,
        }
    )


async def seed(store: InMemoryAggregateStore, *points: Any) -> None:
    buckets: dict[tuple[str, str, str], list[Any]] = {}
    for point in points:
        buckets.setdefault((point.domain_id, point.grain, point.bucket_start), []).append(point)
    for (dom, grain, start), docs in buckets.items():
        await store.replace_bucket(CUSTOMER, dom, cast(Grain, grain), start, docs)


class RecordingReader:
    """Wraps the store and records which domains were queried."""

    def __init__(self, inner: InMemoryAggregateStore) -> None:
        self.inner = inner
        self.queried: set[str] = set()

    async def query(
        self,
        customer_id: str,
        domain_id: str,
        metric: Any,
        grain: Any,
        window: AggregateWindow,
        *,
        max_series: int,
        max_points: int,
    ) -> QueryResult:
        self.queried.add(domain_id)
        return await self.inner.query(
            customer_id,
            domain_id,
            metric,
            grain,
            window,
            max_series=max_series,
            max_points=max_points,
        )

    async def status(self, customer_id: str) -> Any:
        return await self.inner.status(customer_id)


def run_summary(reader: Any, scope: Any, **kwargs: Any) -> Any:
    return asyncio.run(
        compute_cell_summary(
            reader, scope, cell=kwargs.pop("cell", cell()), clock=lambda: NOW, **kwargs
        )
    )


def seeded() -> InMemoryAggregateStore:
    store = InMemoryAggregateStore()
    asyncio.run(
        seed(
            store,
            cost(FINANCE, 1, "10.50"),
            cost(FINANCE, 2, "4.50"),
            cost(FINANCE, 1, "99", kind="invoiced"),
            errors(FINANCE, 1, 100, 5),
            errors(FINANCE, 2, 50, 1),
            cost(HR, 1, "7777.00"),
            errors(HR, 1, 9000, 900),
        )
    )
    return store


def test_restricted_scope_summary_has_only_its_domain() -> None:
    reader = RecordingReader(seeded())
    summary = run_summary(reader, make_scope(FINANCE, member_of=(FINANCE, HR)))
    assert [d.domain_id for d in summary.domains] == [FINANCE]
    assert reader.queried == {FINANCE}  # the other domain's data was never even read
    dumped = summary.model_dump_json()
    assert HR not in dumped
    assert "7777" not in dumped
    row = summary.domains[0]
    assert row.request_count == 150
    assert row.error_count == 6


def test_estimated_and_invoiced_are_separate_rows() -> None:
    summary = run_summary(seeded(), make_scope(FINANCE))
    by_kind = {c.kind: c for c in summary.domains[0].costs}
    assert by_kind["estimated"].amount == Decimal("15.000000000000")
    assert by_kind["invoiced"].amount == Decimal("99.000000000000")
    assert len(summary.domains[0].costs) == 2


def test_unknown_cost_and_missing_data_are_not_zero() -> None:
    store = InMemoryAggregateStore()
    asyncio.run(seed(store, cost(FINANCE, 1, None), errors(FINANCE, 1, 10, None)))
    summary = run_summary(store, make_scope(FINANCE, HR))
    finance = next(d for d in summary.domains if d.domain_id == FINANCE)
    hr = next(d for d in summary.domains if d.domain_id == HR)
    assert finance.costs[0].amount is None
    assert finance.costs[0].complete is False
    assert finance.error_count is None
    assert finance.complete is False
    assert hr.request_count is None
    assert hr.error_count is None
    assert hr.costs == ()
    assert hr.complete is False


def test_cell_refuses_scope_of_another_cloud() -> None:
    gov_domain = domain("finance", "government")
    scope = make_scope(gov_domain, cloud="government")
    with pytest.raises(CapabilityUnavailableError) as raised:
        run_summary(seeded(), scope, cell=cell(cloud="commercial"))
    assert raised.value.code == "capability_unavailable"


def test_combine_cost_totals_never_mixes_kind_or_currency() -> None:
    rows = [
        CostTotal(kind="estimated", currency="USD", amount=Decimal("1"), complete=True),
        CostTotal(kind="estimated", currency="USD", amount=None, complete=False),
        CostTotal(kind="estimated", currency="EUR", amount=Decimal("2"), complete=True),
        CostTotal(kind="invoiced", currency="USD", amount=Decimal("3"), complete=True),
    ]
    merged = {(c.kind, c.currency): c for c in combine_cost_totals(rows)}
    assert len(merged) == 3
    assert merged[("estimated", "USD")].amount == Decimal("1")
    assert merged[("estimated", "USD")].complete is False
    assert merged[("estimated", "EUR")].complete is True


def test_registry_config_is_strict() -> None:
    good = cell().model_dump()
    with pytest.raises(ValidationError):
        CellRef.model_validate({**good, "endpoint": "http://cell-a.example.invalid"})
    with pytest.raises(ValidationError):
        CellRef.model_validate({**good, "cloud": "azure"})
    with pytest.raises(ValidationError):
        CellRef.model_validate({**good, "extra": 1})
    with pytest.raises(ValidationError):
        CellRegistry(cells=(cell(), cell()))
