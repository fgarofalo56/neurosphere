"""Review queue API (PRP-17 item 4): scope/kind filtering, assignment, insight and
maker-checker decisions through the one approval path, superseded decisions."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from action_plane_harness import (  # pyright: ignore[reportMissingImports]
    ALICE,
    BOB,
    CAROL,
    CUSTOMER,
    ERIN,
    FINANCE,
    OPERATIONS,
    Api,
    make_api,
    principal,
    problem,
)
from neurosphere_contracts.actions.v1.actor import Actor
from neurosphere_contracts.actions.v1.approval_decision import ApprovalDecision
from neurosphere_core.hitl import ReviewItem, ReviewKind

EDGE = "commercial:contoso:catalog:edge:e-0001"
OPS_EDGE = "commercial:contoso:catalog:edge:e-0099"


def _now(api: Api) -> datetime:
    return datetime.fromtimestamp(api.h.clock(), UTC)


def _open_insight(
    api: Api, kind: ReviewKind = "relationship", domain: str = FINANCE, subject: str = EDGE
) -> ReviewItem:
    return asyncio.run(
        api.hitl.open_item(
            kind=kind,
            customer_id=CUSTOMER,
            domain_id=domain,
            subject_ref=subject,
            now=_now(api),
            correlation_id="corr-open-insight",
        )
    )


def _items(api: Api, who: str, domain: str = FINANCE, **params: Any) -> list[dict[str, Any]]:
    response = api.review("GET", who, f"/domains/{domain}/items", params=params or None)
    assert response.status_code == 200, response.text
    return response.json()["items"]


def _item_path(item_id: str, domain: str = FINANCE) -> str:
    return f"/domains/{domain}/items/{item_id}"


class Directory:
    def __init__(self, actors: dict[str, Actor]) -> None:
        self.actors = actors

    async def actor_for(self, customer_id: str, principal_id: str) -> Actor | None:
        return self.actors.get(principal_id) if customer_id == CUSTOMER else None


def _seeded() -> tuple[Api, dict[str, Any], ReviewItem, ReviewItem]:
    api = make_api()
    pending = api.awaiting_approval()
    relationship = _open_insight(api)
    recommendation = _open_insight(
        api, "recommendation", subject="commercial:contoso:neurosphere:recommendation:rec-0042"
    )
    return api, pending, relationship, recommendation


# -- filtering ----------------------------------------------------------------------------------


def test_steward_sees_both_queues_viewer_sees_none() -> None:
    api, pending, relationship, recommendation = _seeded()
    seen = {i["item_id"]: i["kind"] for i in _items(api, BOB)}
    assert seen == {
        pending["review_item_id"]: "maker_checker",
        relationship.item_id: "relationship",
        recommendation.item_id: "recommendation",
    }
    assert _items(api, CAROL) == []  # data.read on the domain, but no review permission
    assert _items(api, CAROL, kind="maker_checker") == []


def test_kind_and_state_filters() -> None:
    api, pending, relationship, _ = _seeded()
    maker_checker = _items(api, BOB, kind="maker_checker")
    assert [i["item_id"] for i in maker_checker] == [pending["review_item_id"]]
    assert maker_checker[0]["intent_id"] == pending["intent"]["intent_id"]
    insight = _items(api, BOB, kind="relationship")
    assert [i["item_id"] for i in insight] == [relationship.item_id]
    assert insight[0]["intent_id"] is None
    assert _items(api, BOB, state="approved") == []


def test_queue_is_per_domain_and_scope() -> None:
    api, *_ = _seeded()
    ops = _open_insight(api, domain=OPERATIONS, subject=OPS_EDGE)
    # ERIN: viewer on FINANCE (sees nothing to review there), steward on OPERATIONS.
    assert _items(api, ERIN) == []
    assert [i["item_id"] for i in _items(api, ERIN, OPERATIONS)] == [ops.item_id]
    # BOB has no role on OPERATIONS at all: the route itself refuses.
    out = api.review("GET", BOB, f"/domains/{OPERATIONS}/items")
    assert out.status_code == 403 and problem(out)["code"] == "forbidden"
    # An item id from another domain is not found under this domain's path.
    assert api.review("GET", BOB, _item_path(ops.item_id)).status_code == 404


def test_viewer_deep_link_to_a_review_item_is_403() -> None:
    api, pending, relationship, _ = _seeded()
    for item_id in (pending["review_item_id"], relationship.item_id):
        response = api.review("GET", CAROL, _item_path(item_id))
        assert response.status_code == 403
        assert problem(response)["reason"] == "permission_missing"
    decision = api.review(
        "POST",
        CAROL,
        _item_path(pending["review_item_id"]) + "/decisions",
        json={
            "decision": "approved",
            "reason": "deep link",
            "confirmation_hash": pending["intent"]["confirmation_hash"],
        },
    )
    assert decision.status_code == 403


# -- assignment ---------------------------------------------------------------------------------


def test_claim_shows_a_pseudonym_never_the_principal_id() -> None:
    api, pending, *_ = _seeded()
    claimed = api.review(
        "POST", BOB, _item_path(pending["review_item_id"]) + "/assignment", json={}
    )
    assert claimed.status_code == 200, claimed.text
    body = claimed.json()
    assert body["state"] == "assigned"
    assert body["assignee_pseudonym"]
    assert principal(BOB) not in claimed.text and principal(ALICE) not in claimed.text


def test_maker_cannot_claim_their_own_change() -> None:
    api, pending, *_ = _seeded()
    own = api.review("POST", ALICE, _item_path(pending["review_item_id"]) + "/assignment", json={})
    assert own.status_code == 403
    assert problem(own)["reason"] == "self_approval_forbidden"


def test_assigning_another_reviewer_needs_the_directory() -> None:
    api, _, relationship, _ = _seeded()
    path = _item_path(relationship.item_id) + "/assignment"
    body = {"assignee_principal_id": principal(ALICE)}
    unavailable = api.review("POST", BOB, path, json=body)
    assert unavailable.status_code == 409
    assert problem(unavailable)["reason"] == "reviewer_directory_unconfigured"
    alice = Actor(principal_pseudonym="p-alice", principal_kind="user", on_behalf_of=None)
    api.h.app.state.reviewer_directory = Directory({principal(ALICE): alice})
    assigned = api.review("POST", BOB, path, json=body)
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["assignee_pseudonym"] == "p-alice"
    unknown = api.review("POST", BOB, path, json={"assignee_principal_id": principal(CAROL)})
    assert unknown.status_code == 403


# -- decisions ----------------------------------------------------------------------------------


def test_insight_decision_never_touches_actions() -> None:
    api, pending, relationship, _ = _seeded()
    writes, events = api.intents.replace_calls, len(api.auditor.events)
    decided = api.review(
        "POST",
        BOB,
        _item_path(relationship.item_id) + "/decisions",
        json={"decision": "approved", "reason": "edge confirmed by owner"},
    )
    assert decided.status_code == 200, decided.text
    body = decided.json()
    assert body["state"] == "approved"
    assert [d["review_kind"] for d in body["decisions"]] == ["insight_review"]
    assert body["effective_decision_id"] == body["decisions"][0]["decision_id"]
    assert body["superseded_decision_ids"] == []
    assert api.intents.replace_calls == writes and len(api.auditor.events) == events
    state = api.get_intent(pending["intent"]["intent_id"]).json()["intent"]["state"]
    assert state == "awaiting_approval"


def test_insight_decision_with_a_hash_is_refused() -> None:
    api, pending, relationship, _ = _seeded()
    refused = api.review(
        "POST",
        BOB,
        _item_path(relationship.item_id) + "/decisions",
        json={
            "decision": "approved",
            "reason": "x",
            "confirmation_hash": pending["intent"]["confirmation_hash"],
        },
    )
    assert refused.status_code == 422
    assert problem(refused)["reason"] == "confirmation_hash_not_applicable"


def test_maker_checker_decision_via_queue_uses_the_action_approval_path() -> None:
    api, pending, *_ = _seeded()
    decided = api.review(
        "POST",
        BOB,
        _item_path(pending["review_item_id"]) + "/decisions",
        json={
            "decision": "approved",
            "reason": "diff checked",
            "confirmation_hash": pending["intent"]["confirmation_hash"],
        },
    )
    assert decided.status_code == 200, decided.text
    body = decided.json()
    assert body["state"] == "approved"
    assert body["decisions"][0]["review_kind"] == "maker_checker"
    assert (
        body["decisions"][0]["approved_confirmation_hash"] == pending["intent"]["confirmation_hash"]
    )
    intent = api.get_intent(pending["intent"]["intent_id"]).json()
    assert intent["intent"]["state"] == "executing"
    approvals = [e for e in api.auditor.events if e.operation == "action.approve"]
    assert approvals and approvals[-1].to_state == "executing"
    # Same path, same rules: an intent already handed to the executor takes no second decision.
    again = api.review(
        "POST",
        BOB,
        _item_path(pending["review_item_id"]) + "/decisions",
        json={
            "decision": "approved",
            "reason": "again",
            "confirmation_hash": pending["intent"]["confirmation_hash"],
        },
    )
    assert again.status_code == 422
    assert problem(again)["reason"] == "invalid_transition"
    assert len(asyncio.run(api.hitl.decisions(pending["review_item_id"]))) == 1


def test_self_approval_via_the_queue_is_403() -> None:
    api, pending, *_ = _seeded()
    own = api.review(
        "POST",
        ALICE,
        _item_path(pending["review_item_id"]) + "/decisions",
        json={
            "decision": "approved",
            "reason": "mine",
            "confirmation_hash": pending["intent"]["confirmation_hash"],
        },
    )
    assert own.status_code == 403
    assert problem(own)["reason"] == "self_approval_forbidden"


def test_non_effective_decisions_are_marked_superseded() -> None:
    api, _, relationship, _ = _seeded()
    path = _item_path(relationship.item_id)
    api.review("POST", BOB, path + "/decisions", json={"decision": "approved", "reason": "ok"})
    logged = asyncio.run(api.hitl.decisions(relationship.item_id))
    assert len(logged) == 1
    # A concurrent decision that lost the item's ETag race stays in the append-only log.
    document = logged[0].model_dump(mode="json")
    document.update(decision_id="44444444-4444-4444-8444-000000000001", decision="rejected")
    loser = ApprovalDecision.model_validate(document)
    item = asyncio.run(api.hitl.get(relationship.item_id))
    assert item is not None
    asyncio.run(
        api.decision_log.append(
            loser,
            cloud=item.cloud,
            customer_id=item.customer_id,
            domain_id=item.domain_id,
            scope_hash="sha256:" + "1" * 64,
        )
    )
    view = api.review("GET", BOB, path).json()
    ids = [d["decision_id"] for d in view["decisions"]]
    assert len(ids) == 2
    assert view["effective_decision_id"] == logged[0].decision_id.root
    assert view["superseded_decision_ids"] == ["44444444-4444-4444-8444-000000000001"]
    assert view["state"] == "approved"
