"""Every run re-validates the stored plan and re-authorizes as the VIEWER (PRP-19 item 5)."""

from typing import Any

import authz.authz_helpers as helpers  # pyright: ignore[reportMissingImports]
from neurosphere_api.reports import RunCache
from neurosphere_core.auth.scope import Role
from reports_harness import (  # pyright: ignore[reportMissingImports]
    ALICE,
    BOB,
    CUSTOMER,
    FINANCE,
    OPERATIONS,
    agent_query,
    make_api,
    problem,
    report_body,
)


def _names(run: dict[str, Any]) -> list[str]:
    plan = run["chart_plan"]
    return sorted(row["display_name"] for row in plan["spec"]["data"]["values"])


def test_run_fills_rows_from_the_tool_and_cites_with_freshness() -> None:
    api = make_api()
    report = api.create()
    response = api.run(ALICE, report["id"])
    assert response.status_code == 200, response.text
    run = response.json()
    assert run["status"] == "ok"
    assert _names(run) == ["Agent fin-1", "Agent fin-2", "Agent ops-1"]
    assert {c["freshness"] for c in run["citations"]} <= {"fresh", "stale", "unknown"}
    assert all(c["as_of"] for c in run["citations"])
    values = run["chart_plan"]["spec"]["data"]["values"]
    assert all(isinstance(row["version"], float) for row in values)


def test_stored_report_never_holds_result_data() -> None:
    api = make_api()
    report = api.create()
    assert report["chart_plan"]["spec"]["data"]["values"] == []
    api.run(ALICE, report["id"])
    stored = api.call("GET", ALICE, f"/{report['id']}").json()
    assert stored["chart_plan"]["spec"]["data"]["values"] == []
    assert "Agent fin-1" not in str(stored)


async def test_stored_plan_that_no_longer_validates_refuses_the_run() -> None:
    api = make_api()
    report = api.create()
    row = await api.store.get(CUSTOMER, FINANCE, report["id"])
    assert row is not None
    row.chart_plan["spec"]["encoding"]["x"]["field"] = "no_such_field"
    await api.store.replace(row, if_match=row.etag or "")
    response = api.run(ALICE, report["id"])
    assert response.status_code == 422
    assert problem(response)["code"] == "invalid_schema"


async def test_stored_plan_with_a_banned_key_refuses_the_run() -> None:
    api = make_api()
    report = api.create()
    row = await api.store.get(CUSTOMER, FINANCE, report["id"])
    assert row is not None
    row.chart_plan["spec"]["transform"] = [{"calculate": "datum.version * 2", "as": "double"}]
    await api.store.replace(row, if_match=row.etag or "")
    assert api.run(ALICE, report["id"]).status_code == 422


def test_revocation_between_two_runs_flips_the_second_run_to_deny() -> None:
    api = make_api()
    report = api.create()
    api.share(ALICE, report["id"], BOB)
    assert api.run(BOB, report["id"]).status_code == 200
    # Bob's FINANCE role is revoked in the policy store; the next request derives a new scope.
    api.revoke(BOB, helpers.role(Role.VIEWER, OPERATIONS))
    second = api.run(BOB, report["id"])
    assert second.status_code == 403
    assert "Agent" not in second.text


def test_revoked_source_access_redacts_rows_on_the_next_run() -> None:
    api = make_api()
    report = api.create()
    first = api.run(ALICE, report["id"]).json()
    assert "Agent ops-1" in _names(first)
    api.revoke(ALICE, helpers.role(Role.ANALYST, FINANCE))
    second = api.run(ALICE, report["id"])
    assert second.status_code == 200, second.text
    assert _names(second.json()) == ["Agent fin-1", "Agent fin-2"]


def test_query_filter_can_narrow_but_never_widen_the_viewers_sources() -> None:
    api = make_api()
    only_ops = agent_query(
        filters=[{"field": "domain_id", "op": "eq", "value": OPERATIONS}],
    )
    report = api.create(body=report_body(query_spec=only_ops))
    assert _names(api.run(ALICE, report["id"]).json()) == ["Agent ops-1"]
    api.share(ALICE, report["id"], BOB)
    shared = api.run(BOB, report["id"])
    assert shared.status_code == 200, shared.text
    assert shared.json()["status"] == "no_data"
    assert shared.json()["chart_plan"] is None


def test_unauthenticated_run_is_401() -> None:
    api = make_api()
    report = api.create()
    assert api.run("", report["id"]).status_code == 401


def test_run_cache_keys_carry_the_scope_hash_and_never_bypass_authorization() -> None:
    cache = RunCache()
    api = make_api(cache=cache)
    report = api.create()
    api.share(ALICE, report["id"], BOB)
    assert api.run(ALICE, report["id"]).status_code == 200
    assert api.run(BOB, report["id"]).status_code == 200
    keys = cache.keys()
    assert len(keys) == 2 and keys[0] != keys[1]
    assert all("sha256:" in key and report["id"] in key for key in keys)
    # A cached entry for Bob does not help once Bob's access is revoked.
    api.revoke(BOB, helpers.role(Role.VIEWER, OPERATIONS))
    assert api.run(BOB, report["id"]).status_code == 403


def test_cached_run_still_returns_only_the_viewers_rows() -> None:
    cache = RunCache()
    api = make_api(cache=cache)
    report = api.create()
    api.share(ALICE, report["id"], BOB)
    assert len(_names(api.run(ALICE, report["id"]).json())) == 3
    assert _names(api.run(BOB, report["id"]).json()) == ["Agent fin-1", "Agent fin-2"]
    assert len(_names(api.run(ALICE, report["id"]).json())) == 3


def test_reports_are_unavailable_until_configured() -> None:
    api = make_api()
    for name in ("report_store", "report_tool_registry"):
        delattr(api.h.app.state, name)
    response = api.call("GET", ALICE, "")
    assert response.status_code == 503
    assert problem(response)["code"] == "dependency_transient"
