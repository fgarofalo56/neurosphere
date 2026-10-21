"""Review-state allowlist, item shape rules, policy registry and the HITL store."""

from __future__ import annotations

import itertools
from datetime import timedelta
from typing import get_args

import pytest
from neurosphere_contracts.actions.v1.review_item_state import ReviewItemState
from neurosphere_core.auth.scope.permissions import Permission
from neurosphere_core.errors import (
    CapabilityUnavailableError,
    DependencyTransientError,
    InvalidSchemaError,
    StaleVersionError,
)
from neurosphere_core.hitl import (
    FINAL_STATES,
    INSIGHT_KINDS,
    REVIEW_TRANSITIONS,
    InMemoryHitlStore,
    ReviewItem,
    ReviewKind,
    ReviewPolicy,
    ReviewPolicyRegistry,
    ReviewStateName,
    is_allowed_transition,
    review_kind_for,
    transition,
)
from neurosphere_core.scope import IdentityScope
from pydantic import ValidationError

from .hitl_helpers import (
    CHECKER,
    CHECKER_ID,
    CONFIRMATION,
    DOMAIN,
    INTENT_ID,
    MAKER,
    MAKER_ID,
    OTHER_DOMAIN,
    SCOPE_HASH,
    T0,
    TARGET,
    build,
    open_insight,
    open_maker_checker,
)

STATES: tuple[str, ...] = get_args(ReviewStateName)
KINDS: tuple[str, ...] = get_args(ReviewKind)


def _item(**overrides: object) -> ReviewItem:
    data: dict[str, object] = {
        "item_id": "33333333-3333-4333-8333-333333333333",
        "kind": "relationship",
        "state": "pending",
        "cloud": "commercial",
        "customer_id": "contoso",
        "domain_id": DOMAIN,
        "subject_ref": TARGET,
        "created_at": T0,
        "sla_due_at": T0 + timedelta(hours=24),
        "expires_at": T0 + timedelta(days=7),
        "policy_version": "v1",
    }
    data.update(overrides)
    return ReviewItem.model_validate(data)


def _scope(domains: list[str]) -> IdentityScope:
    from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope

    contract = ContractScope.model_validate(
        {
            "schema_version": "1.0.0",
            "cloud": "commercial",
            "customer_id": "contoso",
            "principal": {
                "principal_id": CHECKER_ID,
                "principal_pseudonym": "p-checker",
                "principal_kind": "user",
            },
            "roles": [],
            "allowed_domains": domains,
            "allowed_resources": [],
            "policy_version": "v1",
            "derived_at": "2026-10-20T00:00:00Z",
            "scope_hash": SCOPE_HASH,
        }
    )
    return IdentityScope._from_verified_contract(contract)  # pyright: ignore[reportPrivateUsage]


# -- state table -----------------------------------------------------------------------------


def test_states_match_the_contract_enum() -> None:
    contract_states = set(get_args(ReviewItemState.model_fields["root"].annotation))
    assert set(STATES) == contract_states
    assert set(REVIEW_TRANSITIONS) == contract_states


@pytest.mark.parametrize(("source", "target"), list(itertools.product(STATES, STATES)))
def test_only_allowlisted_pairs_transition(source: str, target: str) -> None:
    allowed = target in REVIEW_TRANSITIONS[source]
    assert is_allowed_transition(source, target) is allowed
    item = _item(
        state=source,
        **(
            {"assignee_principal_id": CHECKER_ID, "assignee": CHECKER}
            if source == "assigned"
            else {}
        ),
    )
    changes: dict[str, object] = (
        {"assignee_principal_id": CHECKER_ID, "assignee": CHECKER}
        if target == "assigned"
        else {"assignee_principal_id": None, "assignee": None}
    )
    if allowed:
        moved = transition(item, target, **changes)  # pyright: ignore[reportArgumentType]
        assert moved.state_name == target
    else:
        with pytest.raises(StaleVersionError) as info:
            transition(item, target, **changes)  # pyright: ignore[reportArgumentType]
        assert info.value.reason == "invalid_review_transition"


def test_terminal_states_have_no_exit_and_approved_only_reports_the_action_outcome() -> None:
    for state in ("rejected", "expired", "executed", "failed"):
        assert REVIEW_TRANSITIONS[state] == frozenset()
    assert REVIEW_TRANSITIONS["approved"] == frozenset({"executed", "failed"})
    assert FINAL_STATES == {"approved", "rejected", "expired", "executed", "failed"}


def test_unknown_state_is_refused() -> None:
    assert not is_allowed_transition("pending", "done")
    assert not is_allowed_transition("done", "pending")


# -- item shape ------------------------------------------------------------------------------


def test_maker_checker_item_requires_intent_hash_and_maker() -> None:
    with pytest.raises(ValidationError, match="maker_checker items require"):
        _item(kind="maker_checker")
    item = _item(
        kind="maker_checker",
        intent_id=INTENT_ID,
        confirmation_hash=CONFIRMATION,
        maker_principal_id=MAKER_ID,
        maker=MAKER,
    )
    assert item.review_kind == "maker_checker"


def test_insight_item_carries_no_intent_or_hash() -> None:
    with pytest.raises(ValidationError, match="insight review items"):
        _item(intent_id=INTENT_ID)
    with pytest.raises(ValidationError, match="insight review items"):
        _item(confirmation_hash=CONFIRMATION)


def test_domain_must_belong_to_cloud_and_customer() -> None:
    with pytest.raises(ValidationError, match="domain_id must belong"):
        _item(customer_id="fabrikam")
    with pytest.raises(ValidationError, match="domain_id must belong"):
        _item(cloud="government")


def test_assignee_present_exactly_when_assigned() -> None:
    with pytest.raises(ValidationError, match="assignee"):
        _item(state="assigned")
    with pytest.raises(ValidationError, match="assignee"):
        _item(assignee_principal_id=CHECKER_ID, assignee=CHECKER)


def test_item_is_frozen() -> None:
    item = _item()
    with pytest.raises(ValidationError):
        item.state = ReviewItemState("approved")  # pyright: ignore[reportAttributeAccessIssue]


def test_review_kind_mapping_separates_insight_from_maker_checker() -> None:
    assert review_kind_for("maker_checker") == "maker_checker"
    for kind in INSIGHT_KINDS:
        assert review_kind_for(kind) == "insight_review"
    assert set(KINDS) == INSIGHT_KINDS | {"maker_checker"}


# -- policy registry -------------------------------------------------------------------------


def test_default_policies() -> None:
    registry = ReviewPolicyRegistry()
    mc = registry.resolve("maker_checker", "model_swap")
    assert mc.self_approval_forbidden is True
    assert mc.approver_permission is Permission.ACTION_APPROVE
    for kind in INSIGHT_KINDS:
        assert registry.resolve(kind).approver_permission is Permission.CATALOG_CURATE


def test_action_kind_override_wins_over_kind_default() -> None:
    relaxed = ReviewPolicy(
        approver_permission=Permission.ACTION_APPROVE,
        self_approval_forbidden=False,
        policy_version="relaxed-1",
    )
    registry = ReviewPolicyRegistry(action_overrides={("maker_checker", "tag_update"): relaxed})
    assert registry.resolve("maker_checker", "tag_update") is relaxed
    assert registry.resolve("maker_checker", "model_swap").self_approval_forbidden is True


def test_unknown_kind_has_no_policy() -> None:
    with pytest.raises(CapabilityUnavailableError) as info:
        ReviewPolicyRegistry().resolve("unknown_kind")
    assert info.value.reason == "review_policy_missing"


def test_policy_durations_must_be_positive() -> None:
    with pytest.raises(ValidationError, match="sla must be positive"):
        ReviewPolicy(approver_permission=Permission.ACTION_APPROVE, sla=timedelta(0))


# -- store -----------------------------------------------------------------------------------


async def test_create_get_and_etag_conditional_replace() -> None:
    store = InMemoryHitlStore()
    created = await store.create(_item())
    assert created.etag is not None
    assert await store.get(created.item_id) == created
    with pytest.raises(StaleVersionError) as dup:
        await store.create(_item())
    assert dup.value.reason == "review_item_exists"

    claimed = transition(created, "assigned", assignee_principal_id=CHECKER_ID, assignee=CHECKER)
    stored = await store.replace(claimed, if_match=created.etag)
    assert stored.etag not in (None, created.etag)
    with pytest.raises(StaleVersionError) as stale:
        await store.replace(claimed, if_match=created.etag)
    assert stale.value.reason == "etag_mismatch"


async def test_store_outage_is_dependency_transient() -> None:
    store = InMemoryHitlStore()
    store.outage = True
    for call in (store.create(_item()), store.get("x"), store.due(T0)):
        with pytest.raises(DependencyTransientError) as info:
            await call
        assert info.value.reason == "hitl_store_unavailable"


async def test_list_is_scope_filtered_and_paginated() -> None:
    store = InMemoryHitlStore()
    for i in range(5):
        await store.create(
            _item(
                item_id=f"33333333-3333-4333-8333-00000000000{i}",
                created_at=T0 + timedelta(minutes=i),
            )
        )
    await store.create(
        _item(
            item_id="33333333-3333-4333-8333-999999999999",
            domain_id=OTHER_DOMAIN,
        )
    )
    scope = _scope([DOMAIN])
    first = await store.list(scope, DOMAIN, limit=2)
    assert [i.item_id[-1] for i in first.items] == ["0", "1"]
    assert first.next_cursor is not None
    second = await store.list(scope, DOMAIN, cursor=first.next_cursor, limit=2)
    assert [i.item_id[-1] for i in second.items] == ["2", "3"]
    third = await store.list(scope, DOMAIN, cursor=second.next_cursor, limit=2)
    assert [i.item_id[-1] for i in third.items] == ["4"]
    assert third.next_cursor is None
    # A domain outside the scope is empty even though items exist there.
    assert (await store.list(scope, OTHER_DOMAIN)).items == ()
    assert (await store.list(scope, DOMAIN, state="approved")).items == ()
    assert len((await store.list(scope, DOMAIN, kind="relationship")).items) == 5
    with pytest.raises(InvalidSchemaError) as info:
        await store.list(scope, DOMAIN, cursor="bm90LWpzb24")
    assert info.value.reason == "invalid_cursor"
    with pytest.raises(InvalidSchemaError):
        await store.list(scope, DOMAIN, limit=0)


async def test_due_returns_items_whose_stored_deadlines_passed() -> None:
    store = InMemoryHitlStore()
    await store.create(_item(item_id="33333333-3333-4333-8333-000000000001"))
    late = _item(
        item_id="33333333-3333-4333-8333-000000000002",
        sla_due_at=T0 + timedelta(hours=1),
    )
    await store.create(late)
    await store.create(_item(item_id="33333333-3333-4333-8333-000000000003", state="rejected"))
    assert await store.due(T0) == []
    due = await store.due(T0 + timedelta(hours=2))
    assert [i.item_id for i in due] == [late.item_id]
    capped = await store.get(late.item_id)
    assert capped is not None and capped.etag is not None
    await store.replace(capped.model_copy(update={"escalation_capped": True}), if_match=capped.etag)
    assert await store.due(T0 + timedelta(hours=2)) == []


# -- service state rules ---------------------------------------------------------------------


async def test_open_sets_deadlines_from_policy_and_audits() -> None:
    harness = build()
    item = await open_insight(harness)
    policy = ReviewPolicyRegistry().resolve("relationship")
    assert item.state_name == "pending"
    assert item.sla_due_at == T0 + policy.sla
    assert item.expires_at == T0 + policy.expiry
    assert item.policy_version == policy.policy_version
    kinds = [r["kind"] for r in await harness.records()]
    assert kinds == ["before", "after"]


async def test_open_rejects_an_invalid_item() -> None:
    harness = build()
    with pytest.raises(InvalidSchemaError) as info:
        await harness.service.open_item(
            kind="maker_checker",
            customer_id="contoso",
            domain_id=DOMAIN,
            subject_ref=TARGET,
            now=T0,
            correlation_id="corr-x",
        )
    assert info.value.reason == "invalid_review_item"


async def test_action_outcome_only_after_approval_and_only_for_maker_checker() -> None:
    harness = build()
    item = await open_maker_checker(harness)
    with pytest.raises(StaleVersionError):
        await harness.service.mark_executed(item.item_id, T0, correlation_id="corr-m")
    insight = await open_insight(harness)
    with pytest.raises(InvalidSchemaError) as info:
        await harness.service.mark_failed(insight.item_id, T0, correlation_id="corr-m")
    assert info.value.reason == "not_maker_checker"
    await harness.service.decide(
        item.item_id,
        CHECKER_ID,
        CHECKER,
        "approved",
        "looks right",
        CONFIRMATION,
        T0,
        "corr-d",
        scope_hash=SCOPE_HASH,
    )
    done = await harness.service.mark_executed(item.item_id, T0, correlation_id="corr-m")
    assert done.state_name == "executed"
    with pytest.raises(StaleVersionError):
        await harness.service.mark_failed(item.item_id, T0, correlation_id="corr-m")
    assert (await harness.audit.verify("contoso.retail")).ok
