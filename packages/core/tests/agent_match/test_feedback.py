"""Feedback store (in-memory twin), bounded prior and metrics for the agent recommender."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from neurosphere_core.errors import InvalidSchemaError, NotFoundError
from neurosphere_core.recommendations.matching.feedback import (
    CandidateNotInMatchError,
    FeedbackRecord,
    InMemoryFeedbackStore,
    MatchCandidateRecord,
    MatchNotFoundError,
    MatchRecord,
    feedback_signal,
    summarize_metrics,
    token_jaccard,
)
from neurosphere_core.stores.containers import TTL_PER_ITEM, container_spec

CUSTOMER = "contoso"
DOMAIN = "commercial:contoso:catalog:domain:finance"
OTHER_DOMAIN = "commercial:contoso:catalog:domain:ops"
AGENT_A = "commercial:contoso:catalog:agent:a"
AGENT_B = "commercial:contoso:catalog:agent:b"
TOKENS = ("summarize", "support", "ticket")
NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


def make_match(
    match_id: str = "m1",
    *,
    principal: str = "p-1",
    domain: str = DOMAIN,
    tokens: tuple[str, ...] = TOKENS,
    created: datetime = NOW,
) -> MatchRecord:
    return MatchRecord(
        match_id=match_id,
        customer_id=CUSTOMER,
        domain_id=domain,
        principal=principal,
        task_tokens=tokens,
        candidates=(
            MatchCandidateRecord(AGENT_A, 1, 0.9),
            MatchCandidateRecord(AGENT_B, 2, 0.4),
        ),
        created_at=created,
        expires_at=created + timedelta(days=180),
    )


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


def rec(
    principal: str,
    decision: str = "accepted",
    *,
    entity: str = AGENT_A,
    tokens: tuple[str, ...] = TOKENS,
    at: datetime = NOW,
) -> FeedbackRecord:
    return FeedbackRecord(
        match_id=f"m-{principal}",
        customer_id=CUSTOMER,
        domain_id=DOMAIN,
        principal=principal,
        entity_id=entity,
        decision="accepted" if decision == "accepted" else "rejected",
        reason_code=None,
        rank_at_decision=1,
        score_at_decision=0.5,
        task_tokens=tokens,
        decided_at=at,
        expires_at=at + timedelta(days=180),
    )


async def put(store: InMemoryFeedbackStore, principal: str, decision: str = "accepted") -> None:
    await store.record_match(make_match(f"m-{principal}", principal=principal))
    await store.record_feedback(
        customer_id=CUSTOMER,
        domain_id=DOMAIN,
        match_id=f"m-{principal}",
        principal=principal,
        entity_id=AGENT_A,
        decision="accepted" if decision == "accepted" else "rejected",
    )


async def test_one_decision_per_principal_match_candidate_with_replace() -> None:
    clock = Clock()
    store = InMemoryFeedbackStore(clock=clock)
    await store.record_match(make_match())
    for decision in ("accepted", "rejected"):
        await store.record_feedback(
            customer_id=CUSTOMER,
            domain_id=DOMAIN,
            match_id="m1",
            principal="p-1",
            entity_id=AGENT_A,
            decision="accepted" if decision == "accepted" else "rejected",
            reason_code="not_relevant",
        )
        clock.now += timedelta(minutes=1)
    stored = await store.list_feedback(
        customer_id=CUSTOMER, domain_ids=[DOMAIN], entity_ids=[AGENT_A]
    )
    assert len(stored) == 1
    assert stored[0].decision == "rejected"
    assert (stored[0].rank_at_decision, stored[0].score_at_decision) == (1, 0.9)
    assert stored[0].task_tokens == TOKENS


async def test_feedback_for_other_candidates_keeps_separate_decisions() -> None:
    store = InMemoryFeedbackStore(clock=Clock())
    await store.record_match(make_match())
    for entity in (AGENT_A, AGENT_B):
        await store.record_feedback(
            customer_id=CUSTOMER,
            domain_id=DOMAIN,
            match_id="m1",
            principal="p-1",
            entity_id=entity,
            decision="accepted",
        )
    found = await store.list_feedback(
        customer_id=CUSTOMER, domain_ids=[DOMAIN], entity_ids=[AGENT_A, AGENT_B]
    )
    assert {r.entity_id for r in found} == {AGENT_A, AGENT_B}


async def test_refusals_unknown_match_other_principal_and_unknown_candidate() -> None:
    store = InMemoryFeedbackStore(clock=Clock())
    await store.record_match(make_match())

    async def attempt(match_id: str, principal: str, entity: str) -> None:
        await store.record_feedback(
            customer_id=CUSTOMER,
            domain_id=DOMAIN,
            match_id=match_id,
            principal=principal,
            entity_id=entity,
            decision="accepted",
        )

    with pytest.raises(MatchNotFoundError) as unknown:
        await attempt("missing", "p-1", AGENT_A)
    assert isinstance(unknown.value, NotFoundError)
    with pytest.raises(MatchNotFoundError):
        await attempt("m1", "p-2", AGENT_A)
    with pytest.raises(CandidateNotInMatchError) as bad:
        await attempt("m1", "p-1", "commercial:contoso:catalog:agent:zzz")
    assert isinstance(bad.value, InvalidSchemaError)
    assert bad.value.reason == "candidate_not_in_match"
    assert (
        await store.list_feedback(customer_id=CUSTOMER, domain_ids=[DOMAIN], entity_ids=[AGENT_A])
        == ()
    )


async def test_feedback_is_refused_for_the_wrong_domain_or_after_expiry() -> None:
    clock = Clock()
    store = InMemoryFeedbackStore(clock=clock)
    await store.record_match(make_match())
    with pytest.raises(MatchNotFoundError):
        await store.record_feedback(
            customer_id=CUSTOMER,
            domain_id=OTHER_DOMAIN,
            match_id="m1",
            principal="p-1",
            entity_id=AGENT_A,
            decision="accepted",
        )
    clock.now += timedelta(days=181)
    with pytest.raises(MatchNotFoundError):
        await store.record_feedback(
            customer_id=CUSTOMER,
            domain_id=DOMAIN,
            match_id="m1",
            principal="p-1",
            entity_id=AGENT_A,
            decision="accepted",
        )


async def test_match_with_more_than_32_tokens_is_refused() -> None:
    store = InMemoryFeedbackStore(clock=Clock())
    tokens = tuple(f"t{i}" for i in range(33))
    with pytest.raises(InvalidSchemaError):
        await store.record_match(make_match(tokens=tokens))
    await store.record_match(make_match(tokens=tokens[:32]))


async def test_list_feedback_is_scoped_to_customer_and_domains() -> None:
    store = InMemoryFeedbackStore(clock=Clock())
    await put(store, "p-1")
    assert (
        await store.list_feedback(customer_id="other", domain_ids=[DOMAIN], entity_ids=[AGENT_A])
        == ()
    )
    assert (
        await store.list_feedback(
            customer_id=CUSTOMER, domain_ids=[OTHER_DOMAIN], entity_ids=[AGENT_A]
        )
        == ()
    )
    with pytest.raises(InvalidSchemaError):
        await store.list_feedback(
            customer_id=CUSTOMER, domain_ids=[DOMAIN], entity_ids=[str(i) for i in range(1001)]
        )


async def test_stored_fields_hold_no_text_and_no_clear_principal() -> None:
    store = InMemoryFeedbackStore(clock=Clock())
    await put(store, "p-1")
    (stored,) = await store.list_feedback(
        customer_id=CUSTOMER, domain_ids=[DOMAIN], entity_ids=[AGENT_A]
    )
    assert {f for f in stored.__slots__} == {
        "match_id",
        "customer_id",
        "domain_id",
        "principal",
        "entity_id",
        "decision",
        "reason_code",
        "rank_at_decision",
        "score_at_decision",
        "task_tokens",
        "decided_at",
        "expires_at",
    }


# --- feedback_signal ---------------------------------------------------------------------


def test_prior_is_zero_below_min_principals() -> None:
    records = [rec("p-1"), rec("p-2"), rec("p-1")]
    signal = feedback_signal(records, candidate_id=AGENT_A, task_tokens=TOKENS, now=NOW)
    assert signal.prior == 0.0
    assert signal.detail_code == "feedback_insufficient_evidence"
    assert signal.principals == 2


def test_prior_sign_and_bound() -> None:
    accepted = [rec(f"p-{i}") for i in range(3)]
    rejected = [rec(f"p-{i}", "rejected") for i in range(3)]
    up = feedback_signal(accepted, candidate_id=AGENT_A, task_tokens=TOKENS, now=NOW)
    down = feedback_signal(rejected, candidate_id=AGENT_A, task_tokens=TOKENS, now=NOW)
    assert 0 < up.prior <= 0.15
    assert -0.15 <= down.prior < 0
    assert up.detail_code == "feedback_positive"
    assert down.detail_code == "feedback_negative"
    many = [rec(f"p-{i}") for i in range(500)]
    big = feedback_signal(many, candidate_id=AGENT_A, task_tokens=TOKENS, now=NOW)
    assert big.prior <= 0.15
    assert big.principals == 500
    # Weight is capped at min_principals principals' worth: 500 principals move it no more than 3.
    assert big.prior == pytest.approx(up.prior)
    tight = feedback_signal(many, candidate_id=AGENT_A, task_tokens=TOKENS, bound=0.05, now=NOW)
    assert tight.prior <= 0.05


def test_one_principal_repeating_never_counts_twice_and_latest_wins() -> None:
    records = [rec("p-1", at=NOW), rec("p-1", "rejected", at=NOW + timedelta(hours=1))]
    records += [rec("p-2", "rejected"), rec("p-3", "rejected")]
    signal = feedback_signal(records, candidate_id=AGENT_A, task_tokens=TOKENS, now=NOW)
    assert signal.principals == 3
    assert signal.prior < 0


def test_prior_ignores_dissimilar_other_candidate_and_expired_feedback() -> None:
    records = [rec(f"p-{i}", tokens=("unrelated", "words", "here")) for i in range(3)]
    records += [rec(f"q-{i}", entity=AGENT_B) for i in range(3)]
    records += [rec(f"r-{i}", at=NOW - timedelta(days=200)) for i in range(3)]
    signal = feedback_signal(records, candidate_id=AGENT_A, task_tokens=TOKENS, now=NOW)
    assert (signal.prior, signal.principals) == (0.0, 0)


def test_similarity_threshold_is_half() -> None:
    assert token_jaccard(("a", "b"), ("a", "c")) == pytest.approx(1 / 3)
    near = [rec(f"p-{i}", tokens=("summarize", "support")) for i in range(3)]
    signal = feedback_signal(near, candidate_id=AGENT_A, task_tokens=TOKENS, now=NOW)
    assert signal.principals == 3  # jaccard 2/3 >= 0.5
    assert token_jaccard((), ()) == 0.0


def test_signal_rejects_bad_parameters() -> None:
    with pytest.raises(ValueError, match="bound"):
        feedback_signal([], candidate_id=AGENT_A, task_tokens=TOKENS, min_principals=0)


# --- metrics -----------------------------------------------------------------------------


def test_metrics_rate_is_none_without_feedback() -> None:
    result = summarize_metrics(4, [])
    assert (result.matches, result.accepts, result.rejects) == (4, 0, 0)
    assert result.acceptance_rate is None
    assert result.matches_with_feedback == 0


def test_metrics_counts_and_rate() -> None:
    result = summarize_metrics(
        5, [("m1", "accepted"), ("m1", "rejected"), ("m2", "accepted"), ("m3", "accepted")]
    )
    assert result.matches_with_feedback == 3
    assert (result.accepts, result.rejects) == (3, 1)
    assert result.acceptance_rate == 0.75


async def test_store_metrics_window_and_scope() -> None:
    clock = Clock()
    store = InMemoryFeedbackStore(clock=clock)
    await put(store, "p-1")
    await put(store, "p-2", "rejected")
    await store.record_match(make_match("old", created=NOW - timedelta(days=10)))
    await store.record_match(make_match("elsewhere", domain=OTHER_DOMAIN))
    window = await store.metrics(
        customer_id=CUSTOMER,
        domain_ids=[DOMAIN],
        since=NOW - timedelta(days=1),
        until=NOW + timedelta(days=1),
    )
    assert (window.matches, window.matches_with_feedback) == (2, 2)
    assert (window.accepts, window.rejects, window.acceptance_rate) == (1, 1, 0.5)
    empty = await store.metrics(
        customer_id=CUSTOMER,
        domain_ids=[DOMAIN],
        since=NOW + timedelta(days=2),
        until=NOW + timedelta(days=3),
    )
    assert (empty.matches, empty.acceptance_rate) == (0, None)
    with pytest.raises(InvalidSchemaError):
        await store.metrics(
            customer_id=CUSTOMER,
            domain_ids=[DOMAIN],
            since=datetime(2026, 1, 1),
            until=NOW,
        )


def test_container_is_registered_with_per_item_ttl() -> None:
    spec = container_spec("recommendation_feedback")
    assert spec.partition_key_paths == ("/customer_id", "/domain_id")
    assert spec.default_ttl == TTL_PER_ITEM
    assert spec.owner == "neurosphere_core.recommendations.matching.cosmos_store"
