"""Whole-domain search (PRP-74 item 2): ordering, counts, caps, timeout, limit, isolation."""

import asyncio
from typing import Any

import pytest
from map_api_helpers import (  # pyright: ignore[reportMissingImports]
    ALICE,
    BOB,
    FINANCE,
    OPERATIONS,
    agent_doc,
    agent_id,
    make_api,
    mcp_doc,
    put_points,
    service_doc,
    subject_point,
)
from neurosphere_api.map.settings import MapSettings
from neurosphere_core.aggregates import subject_series_key
from topology_helpers import (  # pyright: ignore[reportMissingImports]
    bulk_seed,
    get_search,
    mixed_world,
)

_KIND_ORDER = ["agent", "source", "model", "person", "service", "tool", "mcp_server"]
_TOTAL = 5000


def _kinds(body: dict[str, Any]) -> list[str]:
    return [m["node"]["kind"] for m in body["matches"]]


def test_5000_entity_world_is_ordered_by_kind_and_counts_sum() -> None:
    api = make_api()
    bulk_seed(api, mixed_world(_TOTAL))
    response = get_search(api, ALICE, FINANCE, q="", limit=50)
    assert response.status_code == 200
    body = response.json()
    assert body["truncated"] is False
    assert body["truncation_reason"] is None
    counts = body["counts"]
    assert sum(counts["by_kind"].values()) == _TOTAL
    assert counts["by_kind"] == {
        "agent": 1000,
        "tool": 1000,
        "service": 1000,
        "model": 1000,
        "mcp_server": 1000,
    }
    for facet in ("by_health", "by_environment", "by_cloud"):
        assert sum(counts[facet].values()) == _TOTAL
    assert counts["by_environment"] == {"production": 1250, "staging": 3750}
    assert counts["by_cloud"] == {"commercial": _TOTAL}
    assert len(body["matches"]) == 50
    # Matches follow the viewport's kind order; the first 50 are all agents.
    order = [_KIND_ORDER.index(k) for k in _kinds(body)]
    assert order == sorted(order)
    assert set(_kinds(body)) == {"agent"}
    assert all(m["cluster_id"] == "kind:agent" for m in body["matches"])


def test_kind_order_across_kinds_and_counts_cover_more_than_the_page() -> None:
    api = make_api()
    bulk_seed(api, mixed_world(50))
    body = get_search(api, ALICE, FINANCE, limit=50).json()
    kinds = _kinds(body)
    order = [_KIND_ORDER.index(k) for k in kinds]
    assert order == sorted(order)
    assert len(set(kinds)) == 5
    small = get_search(api, ALICE, FINANCE, limit=3).json()
    assert len(small["matches"]) == 3
    assert sum(small["counts"]["by_kind"].values()) == 50


def test_text_match_is_case_insensitive_on_label_and_id() -> None:
    api = make_api()
    api.seed(agent_doc("alpha", FINANCE), agent_doc("beta", FINANCE), service_doc("alpha-db"))
    by_label = get_search(api, ALICE, FINANCE, q="AGENT ALPHA").json()
    assert [m["node"]["id"] for m in by_label["matches"]] == [agent_id("alpha")]
    by_id = get_search(api, ALICE, FINANCE, q=":AGENT:BETA").json()
    assert [m["node"]["id"] for m in by_id["matches"]] == [agent_id("beta")]
    both = get_search(api, ALICE, FINANCE, q="alpha").json()
    assert {m["node"]["kind"] for m in both["matches"]} == {"agent", "service"}
    assert get_search(api, ALICE, FINANCE, q="zzz-none").json()["matches"] == []


def test_filters_apply_and_are_echoed() -> None:
    api = make_api()
    bulk_seed(api, mixed_world(60))
    body = get_search(api, ALICE, FINANCE, node_type="agent", environment="production").json()
    assert body["filters_applied"]["node_type"] == ["agent"]
    assert set(_kinds(body)) == {"agent"}
    # 60 entities cycle five kinds: 12 agents (i = 0, 5, ..., 55); production when i % 4 == 0.
    assert body["counts"]["by_kind"] == {"agent": 3}
    assert body["counts"]["by_environment"] == {"production": 3}
    for m in body["matches"]:
        assert m["node"]["facets"]["environment"] == "production"
    bad = get_search(api, ALICE, FINANCE, health="great")
    assert bad.status_code == 422
    assert bad.json()["reason"] == "invalid_filter"


def test_health_filter_and_counts_use_measured_points() -> None:
    api = make_api()
    api.seed(agent_doc("bad", FINANCE), agent_doc("good", FINANCE), agent_doc("none", FINANCE))
    put_points(
        api,
        subject_point(subject_series_key("agent", agent_id("bad")), error_count=9, error_rate=0.9),
        subject_point(subject_series_key("agent", agent_id("good")), error_rate=0.0),
    )
    body = get_search(api, ALICE, FINANCE, health="failing").json()
    assert [m["node"]["id"] for m in body["matches"]] == [agent_id("bad")]
    everything = get_search(api, ALICE, FINANCE).json()
    assert everything["counts"]["by_health"] == {"failing": 1, "ok": 1, "unknown": 1}


def test_scan_page_cap_reports_scan_limit() -> None:
    api = make_api()
    bulk_seed(api, mixed_world(1200))
    api.h.app.state.map_settings = MapSettings(search_scan_pages=2)
    body = get_search(api, ALICE, FINANCE, limit=50).json()
    assert body["truncated"] is True
    assert body["truncation_reason"] == "scan_limit"
    assert body["coverage"]["state"] == "partial"
    assert sum(body["counts"]["by_kind"].values()) == 1000  # two pages of 500
    # Enough pages to finish: not truncated.
    api.h.app.state.map_settings = MapSettings(search_scan_pages=3)
    done = get_search(api, ALICE, FINANCE).json()
    assert done["truncated"] is False
    assert sum(done["counts"]["by_kind"].values()) == 1200


def test_slow_scan_reports_timeout() -> None:
    api = make_api()
    bulk_seed(api, mixed_world(1200))
    original = api.repo.list_entities

    async def slow(*args: Any, **kwargs: Any) -> Any:
        await asyncio.sleep(0.4)
        return await original(*args, **kwargs)

    api.repo.list_entities = slow  # type: ignore[method-assign]
    api.h.app.state.map_settings = MapSettings(search_timeout_ms=100)
    body = get_search(api, ALICE, FINANCE).json()
    assert body["truncated"] is True
    assert body["truncation_reason"] == "timeout_ms"
    assert body["coverage"]["state"] == "partial"


@pytest.mark.parametrize("limit", [0, 51, -1])
def test_limit_out_of_range_is_422(limit: int) -> None:
    api = make_api()
    assert get_search(api, ALICE, FINANCE, limit=limit).status_code == 422


def test_limit_bounds_are_accepted_and_q_is_bounded() -> None:
    api = make_api()
    api.seed(agent_doc("a", FINANCE))
    assert get_search(api, ALICE, FINANCE, limit=1).status_code == 200
    assert get_search(api, ALICE, FINANCE, limit=50).status_code == 200
    assert get_search(api, ALICE, FINANCE, q="x" * 129).status_code == 422


def test_other_domain_entities_are_never_returned() -> None:
    api = make_api()
    api.seed(
        agent_doc("fin", FINANCE),
        agent_doc("ops", OPERATIONS),
        mcp_doc("ops-mcp", OPERATIONS),
    )
    response = get_search(api, ALICE, FINANCE)
    assert [m["node"]["id"] for m in response.json()["matches"]] == [agent_id("fin")]
    assert "ops" not in response.text.replace("operations", "")
    assert get_search(api, ALICE, OPERATIONS).status_code == 403
    assert get_search(api, BOB, FINANCE).status_code == 403
    assert get_search(api, None, FINANCE).status_code == 401
