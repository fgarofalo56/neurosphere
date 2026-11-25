"""PRP-102 item 4: index queries are partition-scoped, filtered, parameterised and page-bounded."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from neurosphere_core.interactions import (
    MAX_QUERY_PAGE_SIZE,
    CosmosInteractionIndex,
    InMemoryInteractionIndex,
    InteractionQuery,
    InteractionStoreError,
)
from neurosphere_core.interactions.models import encode_continuation, format_timestamp
from pydantic import ValidationError

from ._support import CUSTOMER, DOMAIN, OTHER_DOMAIN, make_record, new_id

_AGENT_A = "commercial:acme:neurosphere:agent:support-bot"
_AGENT_B = "commercial:acme:neurosphere:agent:sales-bot"
_TOOL = "commercial:acme:neurosphere:tool:crm-lookup"
_ASSET = "commercial:acme:neurosphere:data_asset:crm"
_PRINCIPAL = "commercial:acme:entra:principal:p-" + "ab" * 32
_BASE = datetime(2026, 11, 20, 10, 0, tzinfo=UTC)
_NATIVE = "native-position-1"


async def _seed(index: InMemoryInteractionIndex) -> dict[str, str]:
    """Ten records in DOMAIN plus decoys in another domain and another customer."""
    ids: dict[str, str] = {}
    for i in range(10):
        iid = new_id()
        ids[f"r{i}"] = iid
        await index.create(
            make_record(
                iid,
                captured_at=format_timestamp(_BASE + timedelta(minutes=i)),
                agent_id=_AGENT_A if i % 2 == 0 else _AGENT_B,
                tool_id=_TOOL if i in (3, 4) else None,
                principal_id=_PRINCIPAL if i == 5 else None,
                data_asset_ids=[_ASSET] if i == 6 else [],
                sensitivity_categories=["phi"] if i == 7 else ["pii"],
                findings_summary=(
                    [{"category": "jwt", "count": 1, "action": "replaced"}] if i == 8 else []
                ),
            )
        )
    await index.create(make_record(new_id(), domain_id=OTHER_DOMAIN, agent_id=_AGENT_A))
    await index.create(
        make_record(
            new_id(),
            customer_id="globex",
            domain_id="commercial:globex:neurosphere:domain:support",
            agent_id=_AGENT_A,
        )
    )
    return ids


def _q(**kwargs: Any) -> InteractionQuery:
    return InteractionQuery(customer_id=CUSTOMER, domain_id=DOMAIN, **kwargs)


def _ids(page: Any) -> list[str]:
    return [r.interaction_id.root for r in page.items]


async def test_query_is_scoped_to_one_partition_newest_first() -> None:
    index = InMemoryInteractionIndex()
    ids = await _seed(index)
    page = await index.query(_q(page_size=100))
    assert _ids(page) == [ids[f"r{i}"] for i in reversed(range(10))]
    assert all(r.customer_id.root == CUSTOMER and r.domain_id.root == DOMAIN for r in page.items)
    assert page.continuation is None


@pytest.mark.parametrize(
    ("filters", "expected"),
    [
        ({"agent_id": _AGENT_A}, [8, 6, 4, 2, 0]),
        ({"tool_id": _TOOL}, [4, 3]),
        ({"principal_id": _PRINCIPAL}, [5]),
        ({"data_asset_id": _ASSET}, [6]),
        ({"sensitivity_category": "phi"}, [7]),
        ({"detected_category": "jwt"}, [8]),
        (
            {
                "captured_from": _BASE + timedelta(minutes=2),
                "captured_before": _BASE + timedelta(minutes=5),
            },
            [4, 3, 2],
        ),
        ({"agent_id": _AGENT_B, "captured_from": _BASE + timedelta(minutes=6)}, [9, 7]),
    ],
)
async def test_filters(filters: dict[str, Any], expected: list[int]) -> None:
    index = InMemoryInteractionIndex()
    ids = await _seed(index)
    page = await index.query(_q(**filters))
    assert _ids(page) == [ids[f"r{i}"] for i in expected]


async def test_pages_are_bounded_and_continue_without_gaps() -> None:
    index = InMemoryInteractionIndex()
    ids = await _seed(index)
    seen: list[str] = []
    continuation = None
    sizes = []
    while True:
        page = await index.query(_q(page_size=3, continuation=continuation))
        sizes.append(len(page.items))
        seen.extend(_ids(page))
        continuation = page.continuation
        if continuation is None:
            break
    assert sizes == [3, 3, 3, 1]
    assert seen == [ids[f"r{i}"] for i in reversed(range(10))]


@pytest.mark.parametrize("size", [0, MAX_QUERY_PAGE_SIZE + 1, 500])
def test_page_size_is_hard_bounded(size: int) -> None:
    with pytest.raises(ValidationError):
        _q(page_size=size)


def test_customer_and_domain_are_required() -> None:
    with pytest.raises(ValidationError):
        InteractionQuery(customer_id=CUSTOMER)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        InteractionQuery(domain_id=DOMAIN)  # type: ignore[call-arg]


async def test_continuation_from_another_partition_or_filter_is_refused() -> None:
    index = InMemoryInteractionIndex()
    await _seed(index)
    page = await index.query(_q(page_size=2))
    assert page.continuation is not None
    foreign = [
        InteractionQuery(
            customer_id=CUSTOMER,
            domain_id=OTHER_DOMAIN,
            page_size=2,
            continuation=page.continuation,
        ),
        _q(page_size=2, agent_id=_AGENT_A, continuation=page.continuation),
        _q(page_size=2, continuation="garbage"),
        _q(page_size=2, continuation="nsq1.!!!"),
    ]
    for query in foreign:
        with pytest.raises(InteractionStoreError) as caught:
            await index.query(query)
        assert caught.value.reason == "invalid_query"
    # page size is not part of the binding
    assert (await index.query(_q(page_size=5, continuation=page.continuation))).items


async def test_list_records_orders_by_id_and_is_bounded() -> None:
    index = InMemoryInteractionIndex()
    await _seed(index)
    first = await index.list_records(limit=5)
    rest = await index.list_records(limit=100, after=first[-1].interaction_id.root)
    every = [r.interaction_id.root for r in first + rest]
    assert every == sorted(every) and len(every) == 12
    assert len(await index.list_records(limit=100, customer_id="globex")) == 1
    assert len(await index.list_records(limit=100, principal_id=_PRINCIPAL)) == 1
    with pytest.raises(InteractionStoreError):
        await index.list_records(limit=MAX_QUERY_PAGE_SIZE + 1)


# --- Cosmos backend over a fake container ---------------------------------------------------


class _FakePage:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def __aiter__(self) -> Any:
        async def gen() -> Any:
            for row in self._rows:
                yield row

        return gen()


class _FakePager:
    def __init__(self, rows: list[dict[str, Any]], token: str | None) -> None:
        self._pages = [_FakePage(rows)]
        self.continuation_token = token

    def __aiter__(self) -> _FakePager:
        return self

    async def __anext__(self) -> _FakePage:
        if not self._pages:
            raise StopAsyncIteration
        return self._pages.pop(0)


class _FakeQueryResult:
    def __init__(self, owner: _FakeCosmos, rows: list[dict[str, Any]]) -> None:
        self._owner = owner
        self._rows = rows

    def by_page(self, continuation_token: str | None = None) -> _FakePager:
        self._owner.continuations.append(continuation_token)
        return _FakePager(self._rows, self._owner.next_token)


class _FakeCosmos:
    def __init__(self, rows: list[dict[str, Any]], next_token: str | None) -> None:
        self.rows = rows
        self.next_token = next_token
        self.calls: list[dict[str, Any]] = []
        self.continuations: list[str | None] = []

    def query_items(self, query: str, **kwargs: Any) -> _FakeQueryResult:
        self.calls.append({"query": query, **kwargs})
        return _FakeQueryResult(self, self.rows)


def _row(**overrides: Any) -> dict[str, Any]:
    iid = new_id()
    return {**make_record(iid, **overrides).model_dump(mode="json"), "id": iid, "_etag": "e"}


async def test_cosmos_query_is_parameterised_partition_scoped_and_bounded() -> None:
    fake = _FakeCosmos([_row(), _row()], next_token=_NATIVE)
    index = CosmosInteractionIndex(fake)  # type: ignore[arg-type]
    query = _q(
        page_size=2,
        agent_id=_AGENT_A,
        principal_id=_PRINCIPAL,
        tool_id=_TOOL,
        data_asset_id=_ASSET,
        sensitivity_category="pii",
        detected_category="jwt",
        captured_from=_BASE,
        captured_before=_BASE + timedelta(days=1),
    )
    page = await index.query(query)
    (call,) = fake.calls
    assert call["partition_key"] == [CUSTOMER, DOMAIN]
    assert call["max_item_count"] == 2
    values = [p["value"] for p in call["parameters"]]
    for value in (CUSTOMER, DOMAIN, _AGENT_A, _PRINCIPAL, _TOOL, _ASSET, "pii", "jwt"):
        assert value in values
        assert value not in call["query"]
    assert format_timestamp(_BASE) in values
    assert "ORDER BY c.captured_at DESC" in call["query"]
    assert len(page.items) == 2
    assert page.continuation is not None and "native" not in page.continuation

    fake.next_token = None
    follow = await index.query(query.model_copy(update={"continuation": page.continuation}))
    assert fake.continuations == [None, _NATIVE]
    assert follow.continuation is None


async def test_cosmos_query_bounds_an_oversized_service_page() -> None:
    fake = _FakeCosmos([_row() for _ in range(5)], next_token=None)
    page = await CosmosInteractionIndex(fake).query(_q(page_size=3))  # type: ignore[arg-type]
    assert len(page.items) == 3


async def test_cosmos_query_refuses_foreign_rows_and_tokens() -> None:
    other = _row(domain_id=OTHER_DOMAIN)
    fake = _FakeCosmos([other], next_token=None)
    index = CosmosInteractionIndex(fake)  # type: ignore[arg-type]
    with pytest.raises(InteractionStoreError) as caught:
        await index.query(_q())
    assert caught.value.reason == "interaction_store_unavailable"

    foreign_token = encode_continuation(
        InteractionQuery(customer_id="globex", domain_id=DOMAIN), "native"
    )
    calls_before = len(fake.calls)
    with pytest.raises(InteractionStoreError) as caught:
        await index.query(_q(continuation=foreign_token))
    assert caught.value.reason == "invalid_query"
    assert len(fake.calls) == calls_before
