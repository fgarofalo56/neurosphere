"""PRP-40 item 3: ``GET /api/v1/audit/search`` over the chains the caller may read."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from authz.authz_helpers import FINANCE, HR, OPERATIONS  # pyright: ignore[reportMissingImports]
from neurosphere_api.audit.access import MAX_SEARCH_WINDOW, decode_cursor, encode_cursor
from neurosphere_api.audit.search_store import (
    AuditSearchFilter,
    CosmosAuditSearchStore,
    SearchPosition,
)

from .audit_api_helpers import (
    AUDITOR_FO,
    SINCE,
    STEWARD,
    UNTIL,
    World,
    chain_of,
    make_world,
    seed,
)

SEARCH = "/api/v1/audit/search"


@pytest.fixture
async def world() -> World:
    w = make_world()
    await seed(w)
    return w


def _domains(body: dict[str, Any]) -> list[str]:
    return [item["domain_id"] for item in body["items"]]


def _stamps(body: dict[str, Any]) -> list[str]:
    return [item["record"]["recorded_at"] for item in body["items"]]


async def test_returns_only_readable_chains_newest_first(world: World) -> None:
    response = world.get(AUDITOR_FO, SEARCH, since=SINCE, until=UNTIL)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body["domains"]) == {FINANCE, OPERATIONS}
    assert set(_domains(body)) == {FINANCE, OPERATIONS}  # never HR, never the denials chain
    assert len(body["items"]) == 8
    assert _stamps(body) == sorted(_stamps(body), reverse=True)
    assert body["next_cursor"] is None


async def test_filters_apply(world: World) -> None:
    response = world.get(
        AUDITOR_FO,
        SEARCH,
        since=SINCE,
        until=UNTIL,
        operation="catalog.update",
        kind="after",
        outcome="failed",
        actor="p-11112222",
    )
    body = response.json()
    assert response.status_code == 200, body
    assert len(body["items"]) == 2
    for item in body["items"]:
        record = item["record"]
        assert item["domain_id"] == OPERATIONS
        assert record["operation"] == "catalog.update"
        assert record["outcome"]["result"] == "failed"
    one = world.get(AUDITOR_FO, SEARCH, since=SINCE, until=UNTIL, correlation_id="corr-f2")
    assert [i["record"]["correlation_id"] for i in one.json()["items"]] == ["corr-f2"]


async def test_named_domain_filter(world: World) -> None:
    body = world.get(AUDITOR_FO, SEARCH, since=SINCE, until=UNTIL, domain=[FINANCE]).json()
    assert set(_domains(body)) == {FINANCE} and len(body["items"]) == 4


async def test_unreadable_named_domain_is_403_and_recorded(world: World) -> None:
    response = world.get(AUDITOR_FO, SEARCH, since=SINCE, until=UNTIL, domain=[FINANCE, HR])
    assert response.status_code == 403
    assert response.json()["reason"] == "target_out_of_scope"
    attempt = world.denials.attempts[-1]
    assert (attempt.domain_id, attempt.permission) == (HR, "audit.read")


async def test_caller_without_audit_read_is_403(world: World) -> None:
    response = world.get(STEWARD, SEARCH, since=SINCE, until=UNTIL)
    assert response.status_code == 403
    assert response.json()["reason"] == "permission_missing"


async def test_cursor_pages_without_gaps_or_duplicates(world: World) -> None:
    seen: list[str] = []
    cursor: str | None = None
    pages = 0
    while True:
        params: dict[str, Any] = {"since": SINCE, "until": UNTIL, "page_size": 3}
        if cursor:
            params["cursor"] = cursor
        body = world.get(AUDITOR_FO, SEARCH, **params).json()
        seen += [item["record"]["audit_id"] for item in body["items"]]
        pages += 1
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert pages == 3
    assert len(seen) == len(set(seen)) == 8


@pytest.mark.parametrize(
    "params",
    [
        {"until": UNTIL},  # since missing
        {"since": SINCE},  # until missing
        {"since": UNTIL, "until": SINCE},  # reversed
        {"since": "2026-09-01T00:00:00Z", "until": UNTIL},  # over the cap
        {"since": "2026-11-01T00:00:00", "until": "2026-11-02T00:00:00"},  # no zone
        {"since": SINCE, "until": UNTIL, "page_size": 501},
        {"since": SINCE, "until": UNTIL, "operation": "SELECT * FROM c"},
        {"since": SINCE, "until": UNTIL, "actor": "alice@contoso.com"},
        {"since": SINCE, "until": UNTIL, "cursor": "not a cursor"},
        {"since": SINCE, "until": UNTIL, "cursor": "W10"},  # "[]"
        {"since": SINCE, "until": UNTIL, "chain_id": "contoso.hr"},  # ignored, see below
    ],
)
async def test_invalid_input_is_refused(world: World, params: dict[str, Any]) -> None:
    response = world.get(AUDITOR_FO, SEARCH, **params)
    if "chain_id" in params:
        # A raw chain id is not a parameter: it is ignored, never used to pick a chain.
        assert response.status_code == 200
        assert HR not in _domains(response.json())
        return
    assert response.status_code == 422, response.text


async def test_cursor_naming_another_chain_is_refused(world: World) -> None:
    forged = encode_cursor(SearchPosition("2026-11-01T12:30:00.000000Z", chain_of(HR), 1))
    response = world.get(AUDITOR_FO, SEARCH, since=SINCE, until=UNTIL, cursor=forged)
    assert response.status_code == 422
    assert response.json()["reason"] == "invalid_cursor"


async def test_store_absent_is_503_capability_unavailable() -> None:
    w = make_world(with_search_store=False)
    response = w.get(AUDITOR_FO, SEARCH, since=SINCE, until=UNTIL)
    assert response.status_code == 503
    assert response.json()["reason"] == "capability_unavailable"


def test_window_cap_is_documented() -> None:
    from pathlib import Path

    runbook = Path(__file__).resolve().parents[4] / "docs" / "runbooks" / "audit-siem.md"
    text = runbook.read_text(encoding="utf-8")
    assert f"{MAX_SEARCH_WINDOW.days} days" in text


def test_cursor_round_trip() -> None:
    position = SearchPosition("2026-11-01T12:30:00.000000Z", "contoso.finance", 7)
    assert decode_cursor(encode_cursor(position), {"contoso.finance"}) == position


# -- Cosmos query shape ------------------------------------------------------------------------


def _filter(**kw: Any) -> AuditSearchFilter:
    return AuditSearchFilter(
        since=datetime(2026, 11, 1, tzinfo=UTC), until=datetime(2026, 11, 2, tzinfo=UTC), **kw
    )


def test_cosmos_query_is_parameterized_and_fixed_text() -> None:
    hostile = "x' OR 1=1 --"
    sql, params = CosmosAuditSearchStore.build_query(
        "contoso.finance",
        _filter(operation=hostile, actor=hostile, correlation_id=hostile),
        SearchPosition("2026-11-01T12:00:00.000000Z", "contoso.finance", 3),
        51,
    )
    assert hostile not in sql
    assert "contoso.finance" not in sql
    names = {p["name"] for p in params}
    assert {"@operation", "@actor", "@correlation_id", "@before_at", "@before_seq"} <= names
    assert all(name in sql for name in names)
    assert sql.startswith("SELECT TOP @limit * FROM c WHERE c.doc_type = @doc_type")
    assert sql.endswith("ORDER BY c.sequence DESC")


class _Container:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.calls: list[dict[str, Any]] = []

    def query_items(self, query: str, **kwargs: Any) -> Any:
        self.calls.append({"query": query, **kwargs})

        async def pages() -> Any:
            for row in self.rows:
                yield row

        return pages()


async def test_cosmos_search_is_single_partition_and_strips_storage_fields(world: World) -> None:
    chain = chain_of(FINANCE)
    (record,) = await world.repository.read_range(chain, start=0, limit=1)
    row = {**record.model_dump(mode="json"), "id": "rec-0", "doc_type": "audit_record"}
    row |= {"_rid": "r", "_etag": '"e"', "_ts": 1}
    container = _Container([row])
    store = CosmosAuditSearchStore(container)
    found = await store.search(chain, _filter(), before=None, limit=10)
    assert found == [record]
    (call,) = container.calls
    assert call["partition_key"] == chain
    assert "enable_cross_partition_query" not in call
