"""Reports hardening (PRP-19 round 2 item 11): mandatory ETags on every write, audit events,
normalized principal ids and per-scope run-cache keys. Real in-memory audit repository."""

import asyncio
import re
from typing import Any

from neurosphere_api.reports import RunCache
from reports_harness import (  # pyright: ignore[reportMissingImports]
    ALICE,
    AUDIT_CHAIN,
    BOB,
    CAROL,
    CUSTOMER,
    DAVE,
    ERIN,
    FINANCE,
    Api,
    make_api,
    principal,
    problem,
)


def _records(api: Api) -> list[Any]:
    return asyncio.run(api.audit.read_range(AUDIT_CHAIN, limit=500))


def _ops(api: Api, operation: str) -> list[Any]:
    return [r for r in _records(api) if r.operation == operation]


def rows(run: dict[str, Any]) -> list[str]:
    values = run["chart_plan"]["spec"]["data"]["values"]
    return sorted(r["display_name"] for r in values)


def _share_path(report_id: str) -> str:
    return f"/{report_id}/shares"


# -- If-Match is mandatory on share, unshare and request-publication -------------------------


def _three_calls(api: Api, report_id: str, **kwargs: Any) -> list[Any]:
    return [
        api.call(
            "POST", ALICE, _share_path(report_id), json={"principal_id": principal(BOB)}, **kwargs
        ),
        api.call("DELETE", ALICE, f"{_share_path(report_id)}/{principal(BOB)}", **kwargs),
        api.call("POST", ALICE, f"/{report_id}/publication", **kwargs),
    ]


def test_a_missing_if_match_is_422_on_share_unshare_and_request() -> None:
    api = make_api()
    report = api.create()
    for response in _three_calls(api, report["id"], auto_etag=False):
        assert response.status_code == 422, response.text
        assert problem(response)["errors"][0]["pointer"] == "/header/If-Match"
    # Nothing changed.
    assert api.call("GET", ALICE, f"/{report['id']}").json()["etag"] == report["etag"]
    assert _records(api) == []


def test_a_stale_if_match_is_409_stale_version_on_share_unshare_and_request() -> None:
    api = make_api()
    report = api.create()
    api.share(ALICE, report["id"], CAROL)  # bumps the ETag; ``report["etag"]`` is now stale
    for response in _three_calls(api, report["id"], headers={"If-Match": report["etag"]}):
        assert response.status_code == 409, response.text
        assert problem(response)["code"] == "stale_version"
    assert api.call("GET", ALICE, f"/{report['id']}").json()["shares"] == [principal(CAROL)]


# -- audit -------------------------------------------------------------------------------------


def test_run_is_audited_for_the_viewer_and_carries_no_data() -> None:
    api = make_api()
    report = api.create()
    api.share(ALICE, report["id"], BOB)
    assert api.run(BOB, report["id"]).status_code == 200
    runs = _ops(api, "report.run")
    assert len(runs) == 1
    record = runs[0]
    assert record.kind == "after" and record.outcome.result == "succeeded"
    assert record.subject.target.canonical_id.endswith(f"finance/{report['id']}")
    assert record.subject.target.entity_type == "report"
    dump = record.model_dump_json()
    for leaked in ("Agent fin-1", "display_name", "values"):
        assert leaked not in dump


def test_a_denied_run_is_audited() -> None:
    api = make_api()
    report = api.create()
    assert api.run(CAROL, report["id"]).status_code == 404  # CAROL has no access to it
    denied = [r for r in _ops(api, "report.run") if r.kind == "denied"]
    assert len(denied) == 1
    assert denied[0].denial.code == "forbidden"
    assert denied[0].denial.reason == "report_not_visible"
    assert denied[0].actor.principal_pseudonym  # the viewer, from the verified scope


def test_share_and_unshare_are_audited_with_the_target_principal() -> None:
    api = make_api()
    report = api.create()
    api.share(ALICE, report["id"], BOB)
    api.call("DELETE", ALICE, f"{_share_path(report['id'])}/{principal(BOB)}")
    shares = _ops(api, "report.share")
    assert [r.kind for r in shares] == ["before", "after"]
    assert shares[1].outcome.detail == f"shared:target={principal(BOB)}"
    unshares = _ops(api, "report.unshare")
    assert [r.kind for r in unshares] == ["before", "after"]
    assert unshares[1].outcome.detail == f"unshared:target={principal(BOB)}"
    assert shares[1].actor == unshares[1].actor
    assert shares[1].subject.target_version != shares[0].subject.target_version


def test_a_non_owner_share_is_audited_as_denied() -> None:
    api = make_api()
    report = api.create()
    api.share(ALICE, report["id"], ERIN)
    response = api.call(
        "POST", ERIN, _share_path(report["id"]), json={"principal_id": principal(CAROL)}
    )
    assert response.status_code == 403
    denied = [r for r in _ops(api, "report.share") if r.kind == "denied"]
    assert [d.denial.reason for d in denied] == ["not_owner"]


def test_publication_request_and_decisions_are_audited() -> None:
    api = make_api()
    approved = api.create()
    rejected = api.create()
    for rep in (approved, rejected):
        assert api.call("POST", ALICE, f"/{rep['id']}/publication").status_code == 200
    for rep, decision in ((approved, "approve"), (rejected, "reject")):
        etag = api.current_etag(rep["id"])
        response = api.call(
            "POST",
            DAVE,
            f"/{rep['id']}/publication/decision",
            json={"decision": decision},
            headers={"If-Match": etag},
        )
        assert response.status_code == 200, response.text
    requests = _ops(api, "report.publication.request")
    assert [r.outcome.detail for r in requests if r.kind == "after"] == [
        "publication_requested"
    ] * 2
    decisions = [r for r in _ops(api, "report.publication.decide") if r.kind == "after"]
    assert [r.outcome.detail for r in decisions] == ["decision=approve", "decision=reject"]
    assert {r.actor.principal_pseudonym for r in decisions} != {
        r.actor.principal_pseudonym for r in requests
    }


def test_a_refused_self_approval_is_audited() -> None:
    api = make_api()
    report = api.create(ERIN)
    assert api.call("POST", ERIN, f"/{report['id']}/publication").status_code == 200
    response = api.call(
        "POST",
        ERIN,
        f"/{report['id']}/publication/decision",
        json={"decision": "approve"},
        headers={"If-Match": api.current_etag(report["id"])},
    )
    assert response.status_code == 403
    assert response.json()["reason"] == "self_approval_refused"
    denied = [r for r in _ops(api, "report.publication.decide") if r.kind == "denied"]
    assert len(denied) == 1
    assert denied[0].denial.reason == "self_approval_refused"
    assert not [r for r in _ops(api, "report.publication.decide") if r.kind == "after"]


# -- principal normalization -------------------------------------------------------------------


def _set_owner(api: Api, report_id: str, owner: str) -> None:
    async def swap() -> None:
        stored = await api.store.get(CUSTOMER, FINANCE, report_id)
        assert stored is not None
        await api.store.replace(stored.model_copy(update={"owner": owner}), if_match=stored.etag)

    asyncio.run(swap())


def test_self_approval_is_refused_for_a_mixed_case_or_padded_owner() -> None:
    api = make_api()
    report = api.create()
    assert api.call("POST", ALICE, f"/{report['id']}/publication").status_code == 200
    # The stored owner is DAVE, spelled with different case and padding.
    _set_owner(api, report["id"], f"  {principal(DAVE).upper()} ")
    response = api.call(
        "POST",
        DAVE,
        f"/{report['id']}/publication/decision",
        json={"decision": "approve"},
        headers={"If-Match": api.current_etag(report["id"])},
    )
    assert response.status_code == 403
    assert response.json()["reason"] == "self_approval_refused"


def test_shares_are_stored_normalized_and_matched_case_insensitively() -> None:
    api = make_api()
    report = api.create()
    spelled = principal(BOB).upper()
    response = api.call("POST", ALICE, _share_path(report["id"]), json={"principal_id": spelled})
    assert response.status_code == 200, response.text
    assert response.json()["shares"] == [principal(BOB)]
    # The same principal again, in another spelling, is a no-op (no duplicate, no new version).
    again = api.call("POST", ALICE, _share_path(report["id"]), json={"principal_id": spelled})
    assert again.json()["shares"] == [principal(BOB)]
    assert again.json()["etag"] == response.json()["etag"]
    assert api.run(BOB, report["id"]).status_code == 200
    removed = api.call("DELETE", ALICE, f"{_share_path(report['id'])}/{spelled}")
    assert removed.json()["shares"] == []
    assert api.run(BOB, report["id"]).status_code == 404


# -- run-cache scope hash ----------------------------------------------------------------------


def test_the_same_report_run_under_two_scopes_never_shares_a_cache_entry() -> None:
    cache = RunCache()
    api = make_api(cache=cache)
    report = api.create()
    api.share(ALICE, report["id"], BOB)
    alice = api.run(ALICE, report["id"]).json()
    assert len(cache.keys()) == 1
    bob = api.run(BOB, report["id"]).json()
    keys = cache.keys()
    assert len(keys) == 2  # BOB missed: ALICE's entry was not served to him
    hashes = [re.search(r"sha256:[0-9a-f]+", key) for key in keys]
    assert all(hashes) and hashes[0] is not None and hashes[1] is not None
    assert hashes[0].group() != hashes[1].group()
    assert all(report["id"] in key for key in keys)
    assert rows(alice) != rows(bob)
    assert rows(bob) == ["Agent fin-1", "Agent fin-2"]
    # Hits stay per-scope.
    assert rows(api.run(BOB, report["id"]).json()) == rows(bob)
    assert len(cache.keys()) == 2
