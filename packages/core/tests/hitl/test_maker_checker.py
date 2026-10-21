"""Maker-checker separation on REAL principal ids, reviewer authorization and decision finality."""

from __future__ import annotations

from typing import Literal

import pytest
from neurosphere_contracts.actions.v1.actor import Actor
from neurosphere_core.auth.scope.permissions import Permission
from neurosphere_core.errors import (
    DependencyTransientError,
    ForbiddenError,
    InvalidSchemaError,
    StaleVersionError,
)
from neurosphere_core.hitl import ImmutableDecision, ReviewPolicy, ReviewPolicyRegistry

from .hitl_helpers import (
    AGENT_ID,
    CHECKER,
    CHECKER_ID,
    CONFIRMATION,
    INTENT_ID,
    MAKER,
    MAKER_ID,
    OTHER_CONFIRMATION,
    SCOPE_HASH,
    T0,
    THIRD,
    THIRD_ID,
    Harness,
    actor,
    build,
    open_insight,
    open_maker_checker,
)


async def _decide(
    harness: Harness,
    item_id: str,
    principal_id: str,
    reviewer: Actor,
    *,
    decision: Literal["approved", "rejected"] = "approved",
    confirmation_hash: str | None = CONFIRMATION,
) -> ImmutableDecision:
    return await harness.service.decide(
        item_id,
        principal_id,
        reviewer,
        decision,
        "change matches the reviewed diff",
        confirmation_hash,
        T0,
        "corr-decide-1",
        scope_hash=SCOPE_HASH,
    )


async def _denials(harness: Harness) -> list[str]:
    records = await harness.audit.read_range("contoso.retail", start=0, limit=500)
    return [r.denial.reason for r in records if r.denial is not None]


async def test_maker_cannot_approve_own_change() -> None:
    harness = build()
    item = await open_maker_checker(harness)
    with pytest.raises(ForbiddenError) as info:
        await _decide(harness, item.item_id, MAKER_ID, MAKER)
    assert info.value.reason == "self_approval_forbidden"
    assert await _denials(harness) == ["self_approval_forbidden"]
    stored = await harness.store.get(item.item_id)
    assert stored is not None and stored.state_name == "pending"
    assert await harness.decision_store.list_for_item(item.item_id) == []


async def test_same_principal_under_a_different_pseudonym_is_still_the_maker() -> None:
    harness = build()
    item = await open_maker_checker(harness)
    disguised = actor("p-totally-different")
    with pytest.raises(ForbiddenError) as info:
        await _decide(harness, item.item_id, MAKER_ID, disguised)
    assert info.value.reason == "self_approval_forbidden"


async def test_distinct_principals_with_colliding_pseudonyms_are_separate_people() -> None:
    """Pseudonyms (and display names) are never compared: only the real principal id is."""
    harness = build()
    shared = actor("p-collide")
    item = await open_maker_checker(harness, maker=shared)
    decision = await _decide(harness, item.item_id, CHECKER_ID, shared)
    assert decision.decision == "approved"
    assert decision.self_approval_allowed is False
    stored = await harness.store.get(item.item_id)
    assert stored is not None and stored.state_name == "approved"


async def test_principal_the_agent_acted_for_cannot_approve() -> None:
    harness = build()
    agent = actor("p-copilot", kind="agent", on_behalf_of="p-maker")
    item = await open_maker_checker(
        harness, maker_principal_id=AGENT_ID, maker=agent, on_behalf_of_principal_id=MAKER_ID
    )
    with pytest.raises(ForbiddenError) as info:
        await _decide(harness, item.item_id, MAKER_ID, MAKER)
    assert info.value.reason == "self_approval_forbidden"
    approved = await _decide(harness, item.item_id, CHECKER_ID, CHECKER)
    assert approved.maker == agent


async def test_distinct_checker_approves_and_decision_binds_the_confirmation_hash() -> None:
    harness = build()
    item = await open_maker_checker(harness)
    decision = await _decide(harness, item.item_id, CHECKER_ID, CHECKER)
    assert decision.review_kind == "maker_checker"
    assert decision.intent_id is not None and decision.intent_id.root == INTENT_ID
    assert decision.approved_confirmation_hash is not None
    assert decision.approved_confirmation_hash.root == CONFIRMATION
    assert decision.reviewer == CHECKER
    assert decision.maker == MAKER
    stored = await harness.store.get(item.item_id)
    assert stored is not None
    assert stored.decision_id == decision.decision_id.root
    assert harness.authorizer.calls[-1][3] is Permission.ACTION_APPROVE
    assert (await harness.audit.verify("contoso.retail")).ok


@pytest.mark.parametrize("supplied", [OTHER_CONFIRMATION, None])
async def test_maker_checker_decision_must_carry_the_items_hash(supplied: str | None) -> None:
    harness = build()
    item = await open_maker_checker(harness)
    with pytest.raises(InvalidSchemaError) as info:
        await _decide(harness, item.item_id, CHECKER_ID, CHECKER, confirmation_hash=supplied)
    assert info.value.reason == "confirmation_hash_mismatch"
    assert await _denials(harness) == ["confirmation_hash_mismatch"]


async def test_policy_may_allow_self_approval_per_action_kind() -> None:
    relaxed = ReviewPolicy(
        approver_permission=Permission.ACTION_APPROVE,
        self_approval_forbidden=False,
        policy_version="relaxed-1",
    )
    harness = build(
        policies=ReviewPolicyRegistry(action_overrides={("maker_checker", "tag_update"): relaxed})
    )
    item = await open_maker_checker(harness, action_kind="tag_update")
    decision = await _decide(harness, item.item_id, MAKER_ID, MAKER)
    assert decision.self_approval_allowed is True
    assert decision.policy_version == "relaxed-1"


async def test_reviewer_without_permission_is_refused_and_audited() -> None:
    grants = {MAKER_ID: {Permission.ACTION_APPROVE}, CHECKER_ID: {Permission.CATALOG_CURATE}}
    harness = build(grants=grants)
    item = await open_maker_checker(harness)
    with pytest.raises(ForbiddenError) as info:
        await _decide(harness, item.item_id, CHECKER_ID, CHECKER)
    assert info.value.reason == "reviewer_not_authorized"
    assert await _denials(harness) == ["reviewer_not_authorized"]


async def test_insight_review_needs_catalog_curate_and_executes_nothing() -> None:
    harness = build(grants={CHECKER_ID: {Permission.ACTION_APPROVE}})
    item = await open_insight(harness, "evaluation_dispute")
    with pytest.raises(ForbiddenError):
        await _decide(harness, item.item_id, CHECKER_ID, CHECKER, confirmation_hash=None)
    assert harness.authorizer.calls[-1][3] is Permission.CATALOG_CURATE

    harness = build(grants={CHECKER_ID: {Permission.CATALOG_CURATE}})
    item = await open_insight(harness, "evaluation_dispute")
    with pytest.raises(InvalidSchemaError) as info:
        await _decide(harness, item.item_id, CHECKER_ID, CHECKER)
    assert info.value.reason == "confirmation_hash_not_applicable"
    decision = await _decide(
        harness, item.item_id, CHECKER_ID, CHECKER, decision="rejected", confirmation_hash=None
    )
    assert decision.review_kind == "insight_review"
    assert decision.intent_id is None
    assert decision.maker is None
    stored = await harness.store.get(item.item_id)
    assert stored is not None and stored.state_name == "rejected"


async def test_policy_store_outage_fails_closed() -> None:
    harness = build()
    item = await open_maker_checker(harness)
    harness.authorizer.outage = True
    with pytest.raises(DependencyTransientError):
        await _decide(harness, item.item_id, CHECKER_ID, CHECKER)
    with pytest.raises(DependencyTransientError):
        await harness.service.assign(
            item.item_id,
            None,
            CHECKER_ID,
            T0,
            by=CHECKER,
            scope_hash=SCOPE_HASH,
            correlation_id="corr-a",
        )
    stored = await harness.store.get(item.item_id)
    assert stored is not None and stored.state_name == "pending"


async def test_decided_item_is_final() -> None:
    harness = build()
    item = await open_maker_checker(harness)
    await _decide(harness, item.item_id, CHECKER_ID, CHECKER)
    with pytest.raises(StaleVersionError) as info:
        await _decide(harness, item.item_id, THIRD_ID, THIRD, decision="rejected")
    assert info.value.reason == "review_item_final"
    assert len(await harness.decision_store.list_for_item(item.item_id)) == 1


async def test_unknown_item_is_forbidden_not_revealed() -> None:
    harness = build()
    with pytest.raises(ForbiddenError) as info:
        await _decide(harness, "44444444-4444-4444-8444-444444444444", CHECKER_ID, CHECKER)
    assert info.value.reason == "review_item_not_found"


async def test_cannot_assign_to_the_maker_or_decide_someone_elses_claim() -> None:
    harness = build()
    item = await open_maker_checker(harness)
    with pytest.raises(ForbiddenError) as info:
        await harness.service.assign(
            item.item_id,
            MAKER_ID,
            CHECKER_ID,
            T0,
            by=CHECKER,
            assignee=MAKER,
            scope_hash=SCOPE_HASH,
            correlation_id="corr-a",
        )
    assert info.value.reason == "self_approval_forbidden"

    with pytest.raises(InvalidSchemaError) as missing:
        await harness.service.assign(
            item.item_id,
            THIRD_ID,
            CHECKER_ID,
            T0,
            by=CHECKER,
            scope_hash=SCOPE_HASH,
            correlation_id="corr-a",
        )
    assert missing.value.reason == "assignee_actor_required"

    claimed = await harness.service.assign(
        item.item_id, None, CHECKER_ID, T0, by=CHECKER, scope_hash=SCOPE_HASH, correlation_id="c"
    )
    assert claimed.state_name == "assigned"
    assert claimed.assignee_principal_id == CHECKER_ID
    assert claimed.assignee == CHECKER
    assert claimed.assignment_due_at is not None and claimed.assignment_due_at > T0

    with pytest.raises(ForbiddenError) as other:
        await _decide(harness, item.item_id, THIRD_ID, THIRD)
    assert other.value.reason == "review_item_assigned_to_other"

    reassigned = await harness.service.assign(
        item.item_id,
        THIRD_ID,
        CHECKER_ID,
        T0,
        by=CHECKER,
        assignee=THIRD,
        scope_hash=SCOPE_HASH,
        correlation_id="c",
    )
    assert reassigned.assignee_principal_id == THIRD_ID
    decision = await _decide(harness, item.item_id, THIRD_ID, THIRD)
    assert decision.decision == "approved"
    final = await harness.store.get(item.item_id)
    assert final is not None and final.assignee_principal_id is None
