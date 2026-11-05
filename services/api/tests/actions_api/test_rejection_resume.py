"""A rejection hit by a policy-store outage resumes on resend (PRP-17 audit close-out, Lane B).

Before: ``hitl.decide`` recorded the rejection and moved the item to ``rejected``, then the
approver recheck inside ``ActionService.apply_approval`` hit the outage (503) and the intent
stayed ``awaiting_approval`` until expiry, because only an ``approved`` item could be resumed.
Now the effective reviewer resends the same decision and hash; it converges the intent to
``failed`` (``approval_rejected``) with ONE recorded decision, and nobody else can ride on it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from action_plane_harness import (  # pyright: ignore[reportMissingImports]
    ALICE,
    BOB,
    CAROL,
    DAVE,
    ERIN,
    FINANCE,
    Api,
    make_api,
    problem,
)


def _decide(api: Api, view: dict[str, Any], who: str, decision: str = "rejected") -> Any:
    return api.step(
        who,
        view["intent"]["intent_id"],
        "decisions",
        {
            "decision": decision,
            "reason": "the diff is wrong",
            "confirmation_hash": view["intent"]["confirmation_hash"],
        },
    )


def _review_decide(api: Api, view: dict[str, Any], who: str, decision: str = "rejected") -> Any:
    path = f"/domains/{FINANCE}/items/{view['review_item_id']}/decisions"
    body = {
        "decision": decision,
        "reason": "the diff is wrong",
        "confirmation_hash": view["intent"]["confirmation_hash"],
    }
    return api.review("POST", who, path, json=body)


def _state(api: Api, view: dict[str, Any]) -> str:
    return api.get_intent(view["intent"]["intent_id"]).json()["intent"]["state"]


def _decisions(api: Api, view: dict[str, Any]) -> list[Any]:
    return asyncio.run(api.hitl.decisions(view["review_item_id"]))


def _item_state(api: Api, view: dict[str, Any]) -> str:
    item = asyncio.run(api.hitl.get(view["review_item_id"]))
    assert item is not None
    return item.state_name


def _outage_after_reviewer_check(api: Api) -> Callable[[], None]:
    """Let HITL's reviewer authorization through, then fail every later recheck (outage).

    Returns a function that ends the outage. The first check after arming is the reviewer
    authorization inside ``HitlService.decide``; the next one is the approver recheck inside
    ``ActionService.apply_approval``, i.e. AFTER the decision was recorded.
    """
    real: Callable[[str, str, str, str], Awaitable[bool]] = api.rechecker.check
    seen = {"n": 0, "down": True}

    async def check(principal_id: str, customer_id: str, domain_id: str, permission: str) -> bool:
        seen["n"] += 1
        if seen["down"] and seen["n"] > 1:
            raise RuntimeError("policy store down")
        return await real(principal_id, customer_id, domain_id, permission)

    api.rechecker.check = check  # type: ignore[method-assign]

    def recover() -> None:
        seen["down"] = False

    return recover


def _stuck_rejection(api: Api, decide: Callable[..., Any] = _decide) -> dict[str, Any]:
    view = api.awaiting_approval()
    recover = _outage_after_reviewer_check(api)
    down = decide(api, view, BOB)
    assert down.status_code == 503, down.text
    assert problem(down)["reason"] == "policy_store_unavailable"
    recover()
    # The decision is recorded and effective, but never applied: the intent is not final.
    assert _state(api, view) == "awaiting_approval"
    assert _item_state(api, view) == "rejected"
    assert len(_decisions(api, view)) == 1
    return view


def test_rejection_during_outage_converges_on_resend() -> None:
    api = make_api()
    view = _stuck_rejection(api)
    resumed = _decide(api, view, BOB)
    assert resumed.status_code == 200, resumed.text
    intent = resumed.json()["intent"]
    assert intent["state"] == "failed" and intent["status_reason"] == "approval_rejected"
    assert _item_state(api, view) == "rejected"
    assert len(_decisions(api, view)) == 1  # resumed, not recorded twice
    # Idempotent end state: a further resend changes nothing and records nothing.
    again = _decide(api, view, BOB)
    assert again.status_code == 422
    assert problem(again)["reason"] == "invalid_transition"
    assert _state(api, view) == "failed"
    assert len(_decisions(api, view)) == 1
    assert api.connector.forbidden_calls == []


def test_rejection_resumes_through_the_review_queue_route_too() -> None:
    api = make_api()
    view = _stuck_rejection(api, _review_decide)
    resumed = _review_decide(api, view, BOB)
    assert resumed.status_code == 200, resumed.text
    assert _state(api, view) == "failed"
    assert len(_decisions(api, view)) == 1


def test_maker_cannot_ride_on_the_recorded_rejection() -> None:
    api = make_api()
    view = _stuck_rejection(api)
    own = _decide(api, view, ALICE)
    # The recorded decision is BOB's: the maker's resend is not a resume and records nothing.
    assert own.status_code == 409, own.text
    assert problem(own)["reason"] == "review_item_final"
    assert _state(api, view) == "awaiting_approval"
    assert len(_decisions(api, view)) == 1


@pytest.mark.parametrize("who", [CAROL, DAVE, ERIN])
def test_non_reviewers_cannot_resume_a_rejection(who: str) -> None:
    # CAROL Viewer, DAVE Admin (no action.approve), ERIN steward only in OPERATIONS.
    api = make_api()
    view = _stuck_rejection(api)
    denied = _decide(api, view, who)
    assert denied.status_code == 403, denied.text
    assert problem(denied)["code"] == "forbidden"
    assert _state(api, view) == "awaiting_approval"
    assert len(_decisions(api, view)) == 1


def test_resend_with_the_opposite_decision_is_refused() -> None:
    api = make_api()
    view = _stuck_rejection(api)
    flipped = _decide(api, view, BOB, decision="approved")
    assert flipped.status_code == 409
    assert problem(flipped)["reason"] == "review_item_final"
    assert _state(api, view) == "awaiting_approval"
    assert len(_decisions(api, view)) == 1


def test_maker_cannot_reject_their_own_change() -> None:
    api = make_api()
    view = api.awaiting_approval()
    own = _decide(api, view, ALICE)
    assert own.status_code == 403
    assert problem(own)["reason"] == "self_approval_forbidden"
    assert _state(api, view) == "awaiting_approval"
    assert _decisions(api, view) == []


def test_viewer_reject_is_403_and_records_nothing() -> None:
    api = make_api()
    view = api.awaiting_approval()
    denied = _decide(api, view, CAROL)
    assert denied.status_code == 403
    assert _state(api, view) == "awaiting_approval"
    assert _decisions(api, view) == []
