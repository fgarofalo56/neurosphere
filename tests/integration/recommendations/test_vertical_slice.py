"""Vertical slice, in process (PRP-15 item 6).

sandbox generator (fixed seed, customer ``contoso``) -> worker pipeline (rules, duplicates,
right-sizing projections) -> ``InMemoryRecommendationStore`` -> the real API app built by
``create_app`` with the default routers, over HTTP (dev-issuer tokens, in-memory policy store).

In process: no compose, no network, no cloud, so this is NOT marked ``integration`` and runs in
CI. What it proves: scope denial in list, detail and ``q`` search; the wire contract; schema
validity of every record; review routing returns 202; execution is refused (409); no route
mutates anything. What it does NOT prove: a Cosmos store (none exists yet, so RU and index
behaviour are not exercised), the real PRP-17 review router, or any live pricing.
"""

from __future__ import annotations

import asyncio
import json
from collections import Counter
from dataclasses import dataclass
from typing import Any

import authz.authz_helpers as helpers  # pyright: ignore[reportMissingImports]
import pytest
from neurosphere_api.recommendations import PREFIX, InMemoryReviewRouter
from neurosphere_core.auth.scope import Role
from neurosphere_core.recommendations import InMemoryRecommendationStore
from neurosphere_workers.recommendations.pipeline import PipelineSummary, run_pipeline
from neurosphere_workers.recommendations.rules.tests.support import contract_problems
from neurosphere_workers.recommendations.tests.support import (
    CREATED_AT,
    PAIRS,
    generate_sandbox,
    make_scope,
    synthetic_prices,
)

CUSTOMER = helpers.CUSTOMER  # "contoso"
SEED = 3
ALICE, BOB, CAROL = helpers.ALICE, helpers.BOB, helpers.CAROL


@dataclass
class Slice:
    h: Any
    store: InMemoryRecommendationStore
    review: InMemoryReviewRouter
    summary: PipelineSummary
    domain_a: str
    domain_b: str
    by_domain: dict[str, list[Any]]

    def get(self, who: str, path: str, **params: Any) -> Any:
        return self.h.client.get(f"{PREFIX}{path}", params=params or None, headers=self.h.auth(who))

    def post(self, who: str, path: str, body: Any = None) -> Any:
        return self.h.client.post(f"{PREFIX}{path}", json=body, headers=self.h.auth(who))


async def _list_all(store: InMemoryRecommendationStore, scope: Any, domain: str) -> list[Any]:
    out: list[Any] = []
    cursor = None
    while True:
        page = await store.list(scope, domain, cursor=cursor, limit=200)
        out.extend(page.items)
        cursor = page.next_cursor
        if cursor is None:
            return out


@pytest.fixture(scope="module", name="s")
def slice_(tmp_path_factory: pytest.TempPathFactory) -> Slice:
    out = tmp_path_factory.mktemp("recommendations-slice")
    generate_sandbox(out, seed=SEED, customer=CUSTOMER)
    domains = sorted(
        json.loads(line)["id"]
        for line in (out / "domains.ndjson").read_text(encoding="utf-8").splitlines()
        if line
    )
    scope = make_scope(domains, customer=CUSTOMER)
    store = InMemoryRecommendationStore()
    summary = asyncio.run(
        run_pipeline(
            out,
            scope=scope,
            store=store,
            prices=synthetic_prices(),
            pairs=PAIRS,
            created_at=CREATED_AT,
        )
    )
    by_domain = {d: asyncio.run(_list_all(store, scope, d)) for d in domains}
    populated = [d for d in domains if by_domain[d]]
    assert len(populated) >= 2, "the slice needs recommendations in at least two domains"
    # Domain A: the one holding a duplicate candidate when there is one; B: any other populated.
    with_duplicate = [
        d for d in populated if any(r.kind == "candidate_duplicate" for r in by_domain[d])
    ]
    domain_a = (with_duplicate or populated)[0]
    domain_b = next(d for d in populated if d != domain_a)

    h = helpers.harness(
        helpers.policy(
            ALICE, helpers.role(Role.VIEWER, domain_a), memberships=(domain_a, domain_b)
        ),
        helpers.policy(BOB, helpers.role(Role.VIEWER, domain_b), memberships=(domain_a, domain_b)),
        helpers.policy(
            CAROL, helpers.role(Role.ANALYST, domain_a), memberships=(domain_a, domain_b)
        ),
        routers={},  # the default hooks only: the recommendations router must come from REGISTERED
    )
    review = InMemoryReviewRouter()
    h.app.state.recommendation_store = store
    h.app.state.review_router = review
    return Slice(h, store, review, summary, domain_a, domain_b, by_domain)


def _all_items(s: Slice, who: str, domain: str, **params: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        query = {**params, "limit": 50, **({"cursor": cursor} if cursor else {})}
        response = s.get(who, f"/domains/{domain}", **query)
        assert response.status_code == 200, response.text
        body = response.json()
        items.extend(body["items"])
        cursor = body["next_cursor"]
        if cursor is None:
            return items


def test_list_returns_rules_duplicates_and_projections_for_the_scoped_domain(s: Slice) -> None:
    items = _all_items(s, ALICE, s.domain_a)
    kinds = Counter(i["kind"] for i in items)
    assert kinds["candidate_duplicate"] >= 1
    assert kinds["model_right_sizing"] >= 1
    assert kinds["cost_spike"] + kinds["unused_agent"] + kinds["latency_degradation"] >= 1
    assert {i["domain_id"] for i in items} == {s.domain_a}
    assert len(items) == len(s.by_domain[s.domain_a])
    assert all(i["advisory"] is True for i in items)


def test_pagination_walks_every_record_once(s: Slice) -> None:
    seen: list[str] = []
    cursor: str | None = None
    while True:
        response = s.get(
            ALICE, f"/domains/{s.domain_a}", limit=2, **({"cursor": cursor} if cursor else {})
        )
        body = response.json()
        assert len(body["items"]) <= 2
        seen.extend(i["recommendation_id"] for i in body["items"])
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert len(seen) == len(set(seen)) == len(s.by_domain[s.domain_a])


def test_kind_filter(s: Slice) -> None:
    items = _all_items(s, ALICE, s.domain_a, kind="candidate_duplicate")
    assert items and {i["kind"] for i in items} == {"candidate_duplicate"}


def test_domain_b_is_403_for_a_domain_a_caller_everywhere(s: Slice) -> None:
    b_record = s.by_domain[s.domain_b][0]
    b_id = b_record.recommendation_id.root
    b_subject = b_record.subject_ids[0].root
    assert s.get(ALICE, f"/domains/{s.domain_b}").status_code == 403
    assert s.get(ALICE, f"/domains/{s.domain_b}/items/{b_id}").status_code == 403
    assert s.get(ALICE, f"/domains/{s.domain_b}", q=b_subject).status_code == 403
    # The same record addressed through domain A is simply absent (404), not leaked.
    assert s.get(ALICE, f"/domains/{s.domain_a}/items/{b_id}").status_code == 404


def test_domain_b_records_never_appear_in_domain_a_list_or_search(s: Slice) -> None:
    b_ids = {r.recommendation_id.root for r in s.by_domain[s.domain_b]}
    b_subjects = {x.root for r in s.by_domain[s.domain_b] for x in r.subject_ids}
    a_ids = {i["recommendation_id"] for i in _all_items(s, ALICE, s.domain_a)}
    assert a_ids and not (a_ids & b_ids)
    for subject in sorted(b_subjects)[:5]:
        hits = _all_items(s, ALICE, s.domain_a, q=subject)
        assert not ({h["recommendation_id"] for h in hits} & b_ids)
    for kind in ("cost_spike", "unused_agent", "candidate_duplicate"):
        hits = _all_items(s, ALICE, s.domain_a, q=kind)
        assert not ({h["recommendation_id"] for h in hits} & b_ids)


def test_and_the_reverse_holds_for_a_domain_b_caller(s: Slice) -> None:
    a_ids = {r.recommendation_id.root for r in s.by_domain[s.domain_a]}
    assert s.get(BOB, f"/domains/{s.domain_a}").status_code == 403
    b_ids = {i["recommendation_id"] for i in _all_items(s, BOB, s.domain_b)}
    assert b_ids and not (b_ids & a_ids)


def test_unauthenticated_is_401(s: Slice) -> None:
    response = s.h.client.get(f"{PREFIX}/domains/{s.domain_a}")
    assert response.status_code == 401


def test_every_record_validates_against_the_recommendation_schema(s: Slice) -> None:
    checked = 0
    for domain, who in ((s.domain_a, ALICE), (s.domain_b, BOB)):
        for item in _all_items(s, who, domain):
            assert contract_problems(item) == [], item["recommendation_id"]
            checked += 1
    assert checked == len(s.by_domain[s.domain_a]) + len(s.by_domain[s.domain_b])
    assert checked >= 10


def test_detail_matches_the_wire_contract(s: Slice) -> None:
    for kind in ("model_right_sizing", "candidate_duplicate"):
        record = next(r for r in s.by_domain[s.domain_a] if r.kind == kind)
        response = s.get(ALICE, f"/domains/{s.domain_a}/items/{record.recommendation_id.root}")
        assert response.status_code == 200, response.text
        body = response.json()
        assert set(body) == {"recommendation", "review", "execution"}
        assert contract_problems(body["recommendation"]) == []
        assert body["recommendation"]["recommendation_id"] == record.recommendation_id.root
        assert body["execution"] == {"executable": False, "reason": "action gates not passed"}
        assert body["review"] == {"state": "not_routed", "review_request_id": None}
        rec = body["recommendation"]
        for key in ("evidence_window", "coverage", "uncertainty", "prerequisites", "owner"):
            assert key in rec, key
        if kind == "model_right_sizing":
            estimate = rec["projected_estimate"]
            assert estimate["estimate_kind"] == "estimated"
            assert estimate["price_version"] == "sandbox-prices-2026-10"
            assert estimate["price_effective_date"] == "2026-10-01"
            assert rec["prerequisites"], "right-sizing lists its prerequisites"


def test_a_missing_recommendation_is_404(s: Slice) -> None:
    missing = f"commercial:{CUSTOMER}:neurosphere:recommendation:cost-spike-{'0' * 24}"
    assert s.get(ALICE, f"/domains/{s.domain_a}/items/{missing}").status_code == 404


def test_route_to_review_returns_202_and_the_detail_shows_pending(s: Slice) -> None:
    record = next(r for r in s.by_domain[s.domain_a] if r.kind == "candidate_duplicate")
    rid = record.recommendation_id.root
    response = s.post(CAROL, f"/domains/{s.domain_a}/review-requests", {"recommendation_id": rid})
    assert response.status_code == 202, response.text
    created = response.json()
    assert created["state"] == "pending_review" and created["review_request_id"]
    detail = s.get(ALICE, f"/domains/{s.domain_a}/items/{rid}").json()
    assert detail["review"] == {
        "state": "pending_review",
        "review_request_id": created["review_request_id"],
    }
    assert detail["execution"]["executable"] is False


def test_a_viewer_cannot_route_and_other_domain_ids_cannot_be_routed(s: Slice) -> None:
    rid = s.by_domain[s.domain_a][0].recommendation_id.root
    body = {"recommendation_id": rid}
    assert s.post(ALICE, f"/domains/{s.domain_a}/review-requests", body).status_code == 403
    b_rid = s.by_domain[s.domain_b][0].recommendation_id.root
    assert (
        s.post(
            CAROL, f"/domains/{s.domain_b}/review-requests", {"recommendation_id": b_rid}
        ).status_code
        == 403
    )
    assert (
        s.post(
            CAROL, f"/domains/{s.domain_a}/review-requests", {"recommendation_id": b_rid}
        ).status_code
        == 404
    )


def test_executions_are_refused_with_capability_unavailable(s: Slice) -> None:
    before = {i["recommendation_id"]: i for i in _all_items(s, ALICE, s.domain_a)}
    rid = next(iter(before))
    for body in (None, {"recommendation_id": rid}, {"recommendation_id": rid, "confirm": True}):
        response = s.post(CAROL, f"/domains/{s.domain_a}/executions", body)
        assert response.status_code == 409, response.text
        problem = response.json()
        assert problem["code"] == "capability_unavailable"
        assert problem["detail"] == "action gates not passed"
    assert s.post(ALICE, f"/domains/{s.domain_a}/executions", {}).status_code == 403
    assert s.post(CAROL, f"/domains/{s.domain_b}/executions", {}).status_code == 403
    after = {i["recommendation_id"]: i for i in _all_items(s, ALICE, s.domain_a)}
    assert after == before, "refused executions must not change any record"


def test_no_route_mutates_catalog_or_recommendation_state(s: Slice) -> None:
    paths = {
        path: sorted(methods)
        for path, methods in s.h.app.openapi()["paths"].items()
        if path.startswith(PREFIX)
    }
    assert paths == {
        f"{PREFIX}/domains/{{domain}}": ["get"],
        f"{PREFIX}/domains/{{domain}}/executions": ["post"],
        f"{PREFIX}/domains/{{domain}}/items/{{recommendation_id}}": ["get"],
        f"{PREFIX}/domains/{{domain}}/review-requests": ["post"],
    }
    for method in ("put", "patch", "delete"):
        response = s.h.client.request(
            method, f"{PREFIX}/domains/{s.domain_a}", headers=s.h.auth(CAROL)
        )
        assert response.status_code in (404, 405)
    stored = {r.recommendation_id.root for r in s.by_domain[s.domain_a]}
    assert stored == {i["recommendation_id"] for i in _all_items(s, ALICE, s.domain_a)}


def test_the_pipeline_summary_matches_what_is_stored(s: Slice) -> None:
    stored = sum(len(v) for v in s.by_domain.values())
    assert stored == s.summary.stored
    assert not s.summary.skipped_projections
