"""Policy exceptions, engine side (PRP-105 item 3, acceptance criterion 4; clarifications 7, 8).

Request -> HITL ``policy_exception`` item (subject = the violation's canonical id, deterministic
item id) -> a ``catalog.curate`` reviewer decides in HITL -> the next evaluation tick reads the
decision back: approved = ``excepted`` until expiry, rejected or expired = the violation stays
``open``. The requester can never review their own request.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from neurosphere_contracts.actions.v1.actor import Actor
from neurosphere_contracts.admin.v1.system_setting import EnforcementSetting
from neurosphere_core.errors import (
    DependencyTransientError,
    ForbiddenError,
    InvalidSchemaError,
    StaleVersionError,
)
from neurosphere_core.governance.policy import (
    ExceptionRequest,
    ExceptionRequestResult,
    GovernancePolicyNotFoundError,
    GovernancePolicyStaleError,
    PolicyDecider,
    PolicyDecision,
    ViolationFilters,
    exception_id_for,
    review_item_id_for,
    violation_canonical_id,
)
from neurosphere_core.governance.policy.events import EXCEPTION_DECIDED
from neurosphere_core.governance.policy.models import PolicyDecisionRequest, PolicyViolation
from neurosphere_core.paging import PageRequest
from neurosphere_core.scope import IdentityScope

from .engine_helpers import (
    CUSTOMER,
    CUSTOMERS_SOURCE,
    DOMAIN_A,
    READER,
    REQUESTER_ID,
    REQUESTER_SCOPE,
    REVIEWER_ID,
    VIEWER_SCOPE,
    Engine,
    actor,
    build_engine,
    make_scope,
    policy_draft,
    principal_id,
)

JUSTIFICATION = "Migration to the approved agent version is under way."


async def _violation(engine: Engine) -> PolicyViolation:
    await engine.publish(policy_draft())
    await engine.tick()
    page = await engine.violations.list(
        CUSTOMER, ViolationFilters(domain_ids=(DOMAIN_A,)), PageRequest()
    )
    (stored,) = page.items
    return stored.violation


async def _request(
    engine: Engine,
    violation: PolicyViolation,
    *,
    scope: IdentityScope = REQUESTER_SCOPE,
    days: float = 30,
    text: str = JUSTIFICATION,
    code: str = "migration_in_progress",
    domain: str = DOMAIN_A,
) -> ExceptionRequestResult:
    return await engine.requester.request(
        scope,
        ExceptionRequest(
            domain_id=domain,
            violation_id=violation.violation_id.root,
            justification_code=code,
            justification_text=text,
            expires_at=engine.clock() + timedelta(days=days),
        ),
        correlation_id="corr-exception",
    )


async def _decide(
    engine: Engine, item_id: str, decision: str, *, reviewer_id: str = REVIEWER_ID, hex_char="c"
) -> Any:
    return await engine.hitl.decide(
        item_id,
        reviewer_id,
        actor(hex_char),
        decision,  # type: ignore[arg-type]
        "reviewed",
        None,
        engine.clock(),
        "corr-review",
        scope_hash="sha256:" + "c" * 64,
    )


async def _current(engine: Engine, violation: PolicyViolation) -> PolicyViolation:
    stored = await engine.violations.get(CUSTOMER, DOMAIN_A, violation.violation_id.root)
    assert stored is not None
    return stored.violation


# --- request ----------------------------------------------------------------------------------


async def test_a_request_opens_a_policy_exception_review_on_the_violation() -> None:
    engine = await build_engine()
    violation = await _violation(engine)

    result = await _request(engine, violation)

    item = result.review_item
    canonical = violation_canonical_id("commercial", CUSTOMER, violation.violation_id.root)
    assert item.kind == "policy_exception"
    assert item.subject_ref == canonical
    assert item.domain_id == DOMAIN_A
    assert item.maker_principal_id == REQUESTER_ID
    exception = result.exception.exception
    assert exception.status == "requested"
    assert exception.violation_id is not None
    assert exception.violation_id.root == violation.violation_id.root
    assert exception.review_item_id is not None
    assert exception.review_item_id.root == item.item_id
    assert exception.exception_id.root == exception_id_for(violation.violation_id.root, 1)
    assert item.item_id == review_item_id_for(exception.exception_id.root)
    assert exception.requested_by.root == REQUESTER_ID
    assert exception.reason_code.root == "migration_in_progress"
    review = await engine.hitl.get(item.item_id)
    assert review is not None
    operations = await engine.operations()
    assert "govpolicy.exception_request" in operations
    # the justification text is stored nowhere (only its digest reaches the audit subject)
    stored_doc = next(iter(engine.exceptions.backend._docs.values()))
    assert JUSTIFICATION not in repr(stored_doc)
    records = await engine.records()
    assert JUSTIFICATION not in repr([r.model_dump() for r in records])


async def test_a_retried_request_is_review_item_exists_not_a_second_review() -> None:
    engine = await build_engine()
    violation = await _violation(engine)
    first = await _request(engine, violation)

    with pytest.raises(StaleVersionError) as info:
        await _request(engine, violation)

    assert info.value.reason == "review_item_exists"
    assert len(engine.exceptions.backend._docs) == 1
    review = await engine.hitl.get(first.review_item.item_id)
    assert review is not None


async def test_the_requester_cannot_review_their_own_request() -> None:
    engine = await build_engine()
    violation = await _violation(engine)
    result = await _request(engine, violation)

    with pytest.raises(ForbiddenError) as info:
        await _decide(engine, result.review_item.item_id, "approved", reviewer_id=REQUESTER_ID)

    assert info.value.reason == "self_approval_forbidden"


async def test_requesting_needs_action_propose_in_the_violations_domain() -> None:
    engine = await build_engine()
    violation = await _violation(engine)

    with pytest.raises(ForbiddenError) as info:
        await _request(engine, violation, scope=VIEWER_SCOPE)
    assert info.value.reason == "exception_request_forbidden"
    assert engine.exceptions.backend._docs == {}

    elsewhere = make_scope("b", [("analyst", [DOMAIN_A])], [])
    with pytest.raises(GovernancePolicyNotFoundError):
        await _request(engine, violation, scope=elsewhere)


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"days": 91}, "invalid_exception_expiry"),
        ({"days": -1}, "invalid_exception_expiry"),
        ({"text": ""}, "invalid_justification"),
        ({"text": "x" * 1001}, "invalid_justification"),
        ({"text": "line\x07bell"}, "invalid_justification"),
        ({"code": "Not A Code"}, "invalid_justification"),
    ],
)
async def test_bounded_justification_and_expiry(overrides: dict[str, Any], reason: str) -> None:
    engine = await build_engine()
    violation = await _violation(engine)

    with pytest.raises(InvalidSchemaError) as info:
        await _request(engine, violation, **overrides)

    assert info.value.reason == reason
    assert engine.exceptions.backend._docs == {}


async def test_the_expiry_ceiling_follows_the_configured_max_days() -> None:
    engine = await build_engine(max_days=10)
    violation = await _violation(engine)
    with pytest.raises(InvalidSchemaError):
        await _request(engine, violation, days=11)
    result = await _request(engine, violation, days=10)
    assert result.exception.exception.status == "requested"


# --- read-back --------------------------------------------------------------------------------


async def test_an_approved_exception_is_active_until_expiry_then_the_violation_reopens() -> None:
    engine = await build_engine()
    violation = await _violation(engine)
    result = await _request(engine, violation, days=2)
    await _decide(engine, result.review_item.item_id, "approved")

    run = await engine.tick()

    assert run.exceptions is not None
    assert run.exceptions.approved == 1
    stored = await engine.exceptions.get(
        CUSTOMER, DOMAIN_A, result.exception.exception.exception_id.root
    )
    assert stored is not None
    assert stored.exception.status == "approved"
    assert stored.exception.decided_by is not None
    assert stored.exception.decided_by.root == REVIEWER_ID
    assert stored.exception.audit_id is not None
    current = await _current(engine, violation)
    assert current.status == "excepted"
    assert current.exception_id is not None
    assert current.exception_id.root == stored.exception.exception_id.root
    assert [e.status for e in engine.sink.decided_events] == ["approved"]
    assert engine.sink.decided_events[0].event_class == EXCEPTION_DECIDED
    operations = await engine.operations()
    assert "govpolicy.exception_decide" in operations
    # still observed while excepted: the record is bumped, not re-opened
    await engine.tick()
    still_excepted = await _current(engine, violation)
    assert still_excepted.status == "excepted"

    later = await engine.tick(advance_minutes=3 * 24 * 60)

    assert later.exceptions is not None
    assert later.exceptions.expired == 1
    assert later.exceptions.violations_reopened == 1
    expired = await engine.exceptions.get(
        CUSTOMER, DOMAIN_A, result.exception.exception.exception_id.root
    )
    assert expired is not None
    assert expired.exception.status == "expired"
    reopened = await _current(engine, violation)
    assert reopened.status == "open"
    assert reopened.exception_id is None


async def test_a_rejected_exception_leaves_the_violation_open() -> None:
    engine = await build_engine()
    violation = await _violation(engine)
    result = await _request(engine, violation)
    await _decide(engine, result.review_item.item_id, "rejected")

    run = await engine.tick()

    assert run.exceptions is not None
    assert run.exceptions.rejected == 1
    stored = await engine.exceptions.get(
        CUSTOMER, DOMAIN_A, result.exception.exception.exception_id.root
    )
    assert stored is not None
    assert stored.exception.status == "rejected"
    still_open = await _current(engine, violation)
    assert still_open.status == "open"
    # a new request after a rejection is a new exception and a new review, not a conflict
    again = await _request(engine, violation)
    assert again.exception.exception.exception_id.root == exception_id_for(
        violation.violation_id.root, 2
    )


async def test_an_expired_review_leaves_the_violation_open() -> None:
    engine = await build_engine()
    violation = await _violation(engine)
    result = await _request(engine, violation)
    item = await engine.hitl.get(result.review_item.item_id)
    assert item is not None
    outcome = await engine.hitl.apply_timers(
        item, item.expires_at + timedelta(minutes=1), correlation_id="corr-timer"
    )
    assert outcome.item.state_name == "expired"

    run = await engine.tick()

    assert run.exceptions is not None
    assert run.exceptions.expired == 1
    stored = await engine.exceptions.get(
        CUSTOMER, DOMAIN_A, result.exception.exception.exception_id.root
    )
    assert stored is not None
    assert stored.exception.status == "expired"
    still_open = await _current(engine, violation)
    assert still_open.status == "open"


async def test_an_undecided_review_changes_nothing() -> None:
    engine = await build_engine()
    violation = await _violation(engine)
    result = await _request(engine, violation)

    run = await engine.tick()

    assert run.exceptions is not None
    assert run.exceptions.checked == 1
    assert run.exceptions.decided_ids == []
    stored = await engine.exceptions.get(
        CUSTOMER, DOMAIN_A, result.exception.exception.exception_id.root
    )
    assert stored is not None
    assert stored.exception.status == "requested"


async def test_an_excepted_violation_cannot_get_a_second_request() -> None:
    engine = await build_engine()
    violation = await _violation(engine)
    result = await _request(engine, violation)
    await _decide(engine, result.review_item.item_id, "approved")
    await engine.tick()

    with pytest.raises(GovernancePolicyStaleError) as info:
        await _request(engine, violation)
    assert info.value.reason == "violation_not_open"


async def test_a_reviewer_who_cannot_be_named_leaves_the_exception_waiting() -> None:
    engine = await build_engine()
    violation = await _violation(engine)
    result = await _request(engine, violation)
    engine.authorizer.grants["commercial:acme:entra:person:short"] = engine.authorizer.grants[
        REVIEWER_ID
    ]
    await engine.hitl.decide(
        result.review_item.item_id,
        "commercial:acme:entra:person:short",
        actor_of_pseudonym("short-pseudonym"),
        "approved",
        "reviewed",
        None,
        engine.clock(),
        "corr-review",
        scope_hash="sha256:" + "e" * 64,
    )

    run = await engine.tick()

    assert run.exceptions is not None
    assert run.exceptions.reviewer_unresolved == 1
    stored = await engine.exceptions.get(
        CUSTOMER, DOMAIN_A, result.exception.exception.exception_id.root
    )
    assert stored is not None
    assert stored.exception.status == "requested"
    still_open = await _current(engine, violation)
    assert still_open.status == "open"


# --- separation of duties across the retry path -----------------------------------------------

#: A second analyst in domain A (``action.propose``), distinct from REQUESTER_SCOPE.
OTHER_REQUESTER_SCOPE = make_scope("e", [("analyst", [DOMAIN_A])], [DOMAIN_A])
OTHER_REQUESTER_ID = principal_id("e")


def _fail_open_item_once(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Make the next ``hitl.open_item`` call raise a transient error; later calls go through."""
    real = engine.hitl.open_item
    calls: list[int] = []

    async def flaky(**kwargs: Any) -> Any:
        calls.append(1)
        if len(calls) == 1:
            raise DependencyTransientError("hitl store unavailable")
        return await real(**kwargs)

    monkeypatch.setattr(engine.hitl, "open_item", flaky)
    return calls


async def _decision_for_reader(engine: Engine) -> PolicyDecision:
    """What the decider answers for the violating read (the PII policy is bound ``audit``)."""
    pdp = PolicyDecider(
        engine.policies,
        engine.bindings,
        engine.exceptions,
        catalog=engine.catalog,
        settings=lambda: EnforcementSetting(decision_cache_ttl_seconds=0),
    )
    body = {
        "schema_version": "1.2.0",
        "decision_point": "tool_call",
        "operation": "data_access",
        "agent_id": READER,
        "data_asset_ids": [CUSTOMERS_SOURCE],
        "access": "read",
    }
    return await pdp.decide_detail(
        REQUESTER_SCOPE, PolicyDecisionRequest.model_validate(body), now=engine.clock()
    )


async def test_another_principal_cannot_take_over_a_request_whose_review_never_opened(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = await build_engine()
    violation = await _violation(engine)
    calls = _fail_open_item_once(engine, monkeypatch)

    # A requests: the exception is stored, the review item is not (transient HITL failure).
    with pytest.raises(DependencyTransientError):
        await _request(engine, violation)
    assert len(calls) == 1
    exception_id = exception_id_for(violation.violation_id.root, 1)
    pending = await engine.exceptions.get(CUSTOMER, DOMAIN_A, exception_id)
    assert pending is not None
    assert pending.exception.requested_by.root == REQUESTER_ID

    # B asks on the same violation: same ordinal, same exception id -> refused, no review opened.
    with pytest.raises(GovernancePolicyStaleError) as info:
        await _request(engine, violation, scope=OTHER_REQUESTER_SCOPE)
    assert info.value.reason == "exception_exists"
    assert len(calls) == 1
    no_review = await engine.hitl.get(review_item_id_for(exception_id))
    assert no_review is None

    # A's own retry re-opens the missing review with A as maker, so A still cannot approve it.
    retried = await _request(engine, violation)
    assert retried.review_item.maker_principal_id == REQUESTER_ID
    with pytest.raises(ForbiddenError):
        await _decide(engine, retried.review_item.item_id, "approved", reviewer_id=REQUESTER_ID)

    await engine.tick()
    stored = await engine.exceptions.get(CUSTOMER, DOMAIN_A, exception_id)
    assert stored is not None
    assert stored.exception.status == "requested"
    current = await _current(engine, violation)
    assert current.status == "open"
    decision = await _decision_for_reader(engine)
    assert decision.applied_exception_ids == ()
    assert decision.response.effect == "audit"


@pytest.mark.parametrize("reviewer", ["requester", "third_party"])
async def test_the_reconciler_never_honours_an_approval_not_separated_from_the_requester(
    monkeypatch: pytest.MonkeyPatch, reviewer: str
) -> None:
    """Defence in depth: a review item whose maker is not the requester is never honoured."""
    engine = await build_engine()
    violation = await _violation(engine)
    _fail_open_item_once(engine, monkeypatch)
    with pytest.raises(DependencyTransientError):
        await _request(engine, violation)
    exception_id = exception_id_for(violation.violation_id.root, 1)
    item_id = review_item_id_for(exception_id)
    # The pre-fix takeover, reproduced directly: B becomes the maker of A's review item.
    await engine.hitl.open_item(
        kind="policy_exception",
        customer_id=CUSTOMER,
        domain_id=DOMAIN_A,
        subject_ref=violation_canonical_id("commercial", CUSTOMER, violation.violation_id.root),
        now=engine.clock(),
        correlation_id="corr-takeover",
        item_id=item_id,
        maker_principal_id=OTHER_REQUESTER_ID,
        maker=actor("e"),
        opened_by=actor("e"),
        scope_hash="sha256:" + "e" * 64,
        channel="rest",
    )
    if reviewer == "requester":
        await _decide(engine, item_id, "approved", reviewer_id=REQUESTER_ID, hex_char="b")
    else:
        await _decide(engine, item_id, "approved")

    run = await engine.tick()

    assert run.exceptions is not None
    assert run.exceptions.self_approval_refused == 1
    assert run.exceptions.approved == 0
    stored = await engine.exceptions.get(CUSTOMER, DOMAIN_A, exception_id)
    assert stored is not None
    assert stored.exception.status == "rejected"
    current = await _current(engine, violation)
    assert current.status == "open"
    assert [e.status for e in engine.sink.decided_events] == ["rejected"]
    details = [
        r.outcome.detail
        for r in await engine.records()
        if r.operation == "govpolicy.exception_decide" and r.outcome is not None
    ]
    assert "self_approval_refused" in details
    # later ticks leave it closed, and the decider never honours it
    await engine.tick()
    still = await engine.exceptions.get(CUSTOMER, DOMAIN_A, exception_id)
    assert still is not None
    assert still.exception.status == "rejected"
    decision = await _decision_for_reader(engine)
    assert decision.applied_exception_ids == ()
    assert decision.response.effect == "audit"


def actor_of_pseudonym(pseudonym: str) -> Actor:
    return Actor.model_validate(
        {"principal_pseudonym": pseudonym, "principal_kind": "user", "on_behalf_of": None}
    )
