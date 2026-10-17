"""Pure curation rules: locks pin presented lineage, observations are never lost."""

from __future__ import annotations

import itertools
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from neurosphere_contracts.catalog.v1.edge_override import EdgeOverride
from neurosphere_contracts.catalog.v1.invokes import InvokesRelation
from neurosphere_core.catalog import (
    active_lock,
    format_timestamp,
    merge_observation,
    parse_timestamp,
    present_edge,
)

_EXAMPLES = Path(__file__).resolve().parents[3] / "contracts/schemas/catalog/v1/examples/valid"
EDGE_ID = "commercial:contoso:neurosphere:invokes:e-0001"
ACTOR = "commercial:contoso:entra:person:psn_0123456789abcdef"
NOW = datetime(2026, 10, 17, 12, 0, 0, tzinfo=UTC)
AFTER_EXPIRY = datetime(2027, 1, 2, 0, 0, 0, tzinfo=UTC)
EXPIRY = "2026-12-01T00:00:00Z"
SECURITY = "audit:sec-0042"


def make_edge(**patch: Any) -> InvokesRelation:
    raw = json.loads((_EXAMPLES / "invokes.inferred.json").read_text(encoding="utf-8"))
    raw.update(patch)
    return InvokesRelation.model_validate(raw)


def make_override(
    decision: str,
    decided_at: str,
    *,
    ident: str,
    expiry: str | None = EXPIRY,
    **extra: Any,
) -> EdgeOverride:
    raw: dict[str, Any] = {
        "schema_version": "1.0.0",
        "id": f"commercial:contoso:neurosphere:edge_override:{ident}",
        "edge_id": EDGE_ID,
        "relation_type": "invokes",
        "expected_edge_version": 2,
        "expected_edge_etag": '"edge-etag-2"',
        "cloud": "commercial",
        "customer_id": "contoso",
        "domain_id": "commercial:contoso:neurosphere:domain:finance",
        "decision": decision,
        "actor": ACTOR,
        "reason": f"steward {decision}",
        "decided_at": decided_at,
        "lock": None,
        "set_confidence": None,
        "set_validity": None,
        "add_evidence_ids": [],
        "review_item_id": None,
    }
    if decision in ("lock", "override"):
        raw["lock"] = {"locked": True, "reason": "steward hold", "expiry": expiry, "actor": ACTOR}
    raw.update(extra)
    return EdgeOverride.model_validate(raw)


def lock_override(**extra: Any) -> EdgeOverride:
    return make_override("lock", "2026-10-10T00:00:00Z", ident="lock-1", **extra)


# --------------------------------------------------------------------------- timestamps


def test_timestamp_round_trip_and_nanosecond_input() -> None:
    parsed = parse_timestamp("2026-10-09T17:30:00.123456789Z")
    assert parsed == datetime(2026, 10, 9, 17, 30, 0, 123456, tzinfo=UTC)
    assert format_timestamp(parsed) == "2026-10-09T17:30:00.123456Z"


def test_naive_clock_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        active_lock([], datetime(2026, 10, 17))


# --------------------------------------------------------------------------- active lock


def test_active_lock_until_expiry_then_none() -> None:
    lock = lock_override()
    assert active_lock([lock], NOW) is lock
    assert active_lock([lock], AFTER_EXPIRY) is None
    # exactly at expiry the lock no longer applies
    assert active_lock([lock], parse_timestamp(EXPIRY)) is None


def test_unlock_clears_and_later_lock_replaces() -> None:
    lock = lock_override()
    unlock = make_override("unlock", "2026-10-11T00:00:00Z", ident="unlock-1")
    relock = make_override("lock", "2026-10-12T00:00:00Z", ident="lock-2")
    assert active_lock([lock, unlock], NOW) is None
    assert active_lock([relock, unlock, lock], NOW) is relock


def test_future_dated_decisions_do_not_apply_yet() -> None:
    future = make_override(
        "lock", "2026-11-01T00:00:00Z", ident="lock-f", expiry="2026-12-31T00:00:00Z"
    )
    assert active_lock([future], NOW) is None


# --------------------------------------------------------------------------- presentation


def test_unlocked_edge_is_presented_as_observed() -> None:
    edge = make_edge()
    presented = present_edge(edge, [], NOW)
    assert presented.confidence == 0.82
    assert presented.status == "inferred"
    assert not presented.pinned
    assert not presented.hidden
    assert presented.lock.locked is False


def test_active_lock_pins_presented_edge_and_expiry_restores_observed() -> None:
    edge = make_edge()
    pin = make_override(
        "override",
        "2026-10-10T00:00:00Z",
        ident="ovr-1",
        set_confidence=0.4,
        set_validity={"valid_from": "2026-10-01T08:00:00Z", "valid_to": "2026-11-15T00:00:00Z"},
    )
    pinned = present_edge(edge, [pin], NOW)
    assert pinned.pinned
    assert pinned.confidence == 0.4
    assert pinned.validity.valid_to is not None
    assert pinned.status == "curated"
    assert pinned.lock.locked is True
    assert pinned.curation is not None
    assert pinned.curation.decision == "overridden"

    restored = present_edge(edge, [pin], AFTER_EXPIRY)
    assert not restored.pinned
    assert restored.confidence == 0.82
    assert restored.validity.valid_to is None
    assert restored.status == "inferred"
    assert restored.lock.locked is False
    assert restored.curation is None


def test_reject_hides_and_accept_shows_again() -> None:
    edge = make_edge()
    reject = make_override("reject", "2026-10-10T00:00:00Z", ident="rej-1")
    accept = make_override("accept", "2026-10-11T00:00:00Z", ident="acc-1")
    assert present_edge(edge, [reject], NOW).hidden
    shown = present_edge(edge, [reject, accept], NOW)
    assert not shown.hidden
    assert shown.status == "curated"


def test_decisions_for_other_edges_are_ignored() -> None:
    other = make_override("reject", "2026-10-10T00:00:00Z", ident="rej-x")
    other = other.model_copy(update={"edge_id": "commercial:contoso:neurosphere:invokes:e-9999"})
    assert not present_edge(make_edge(), [other], NOW).hidden


def test_steward_evidence_is_added_never_removed() -> None:
    edge = make_edge()
    accept = make_override(
        "accept", "2026-10-10T00:00:00Z", ident="acc-1", add_evidence_ids=["review:77"]
    )
    presented = present_edge(edge, [accept], NOW)
    assert "review:77" in presented.evidence_ids
    assert {"trace:4bf92f3577b34da6a3ce929d0e0e4736", SECURITY} <= set(presented.evidence_ids)
    assert presented.security_evidence_ids == [SECURITY]


# --------------------------------------------------------------------------- merge


def _new_observation(**patch: Any) -> InvokesRelation:
    base: dict[str, Any] = {
        "confidence": 0.2,
        "evidence_ids": ["trace:new-0001"],
        "security_evidence_ids": [],
        "last_observed": "2026-10-17T11:00:00Z",
    }
    base.update(patch)
    return make_edge(**base)


def test_merge_on_locked_edge_keeps_presented_and_stores_observation() -> None:
    existing = make_edge()
    lock = lock_override()
    outcome = merge_observation(existing, _new_observation(), [lock], NOW)

    assert "trace:new-0001" in [e.root for e in outcome.stored.evidence_ids]
    assert SECURITY in [e.root for e in outcome.stored.security_evidence_ids]
    assert outcome.stored.last_observed.root == "2026-10-17T11:00:00Z"
    assert outcome.stored.confidence == 0.82  # held by the lock
    assert outcome.presented_changed is False
    assert outcome.presented_before is not None
    assert outcome.presented.confidence == outcome.presented_before.confidence == 0.82
    assert outcome.presented.pinned
    assert outcome.observation.evidence_ids == ["trace:new-0001"]
    assert outcome.observation.confidence == 0.2

    assert outcome.review_item is not None
    assert outcome.review_item.reason == "conflicts_with_lock"
    assert outcome.review_item.governing_override_id == lock.id
    assert outcome.review_item.status == "open"


def test_merge_on_locked_edge_without_contradiction_has_no_review_item() -> None:
    outcome = merge_observation(
        make_edge(), _new_observation(confidence=0.85), [lock_override()], NOW
    )
    assert outcome.review_item is None
    assert outcome.presented_changed is False


def test_merge_on_locked_edge_with_contradicting_validity_goes_to_review() -> None:
    ended = _new_observation(
        confidence=0.82,
        validity={"valid_from": "2026-10-01T08:00:00Z", "valid_to": "2026-10-16T00:00:00Z"},
    )
    outcome = merge_observation(make_edge(), ended, [lock_override()], NOW)
    assert outcome.review_item is not None
    assert outcome.presented.validity.valid_to is None


def test_merge_after_lock_expiry_follows_the_inference() -> None:
    outcome = merge_observation(make_edge(), _new_observation(), [lock_override()], AFTER_EXPIRY)
    assert outcome.stored.confidence == 0.2
    assert outcome.presented.confidence == 0.2
    assert outcome.presented_changed is True
    assert outcome.review_item is None


def test_merge_without_curation_updates_edge_and_reports_change() -> None:
    existing = make_edge()
    outcome = merge_observation(existing, _new_observation(), [], NOW)
    assert outcome.stored.confidence == 0.2
    assert outcome.presented_changed is True
    assert outcome.review_item is None
    assert outcome.stored.updated_at.root == format_timestamp(NOW)
    assert existing.confidence == 0.82  # inputs are never mutated


def test_first_observation_creates_the_edge() -> None:
    outcome = merge_observation(None, _new_observation(), [], NOW)
    assert outcome.presented_before is None
    assert outcome.presented_changed is True
    assert outcome.review_item is None
    assert outcome.stored.id == EDGE_ID


def test_reobserving_a_curated_reject_goes_to_review_and_stays_hidden() -> None:
    reject = make_override("reject", "2026-10-10T00:00:00Z", ident="rej-1")
    first = merge_observation(make_edge(), _new_observation(), [reject], NOW)
    assert first.presented.hidden
    assert first.presented_changed is False
    assert first.review_item is not None
    assert first.review_item.reason == "conflicts_with_reject"
    assert "trace:new-0001" in first.review_item.new_evidence_ids

    # A replay of the same batch produces the same review item id (queue dedupes it)
    replay = merge_observation(first.stored, _new_observation(), [reject], NOW)
    assert replay.review_item is not None
    assert replay.review_item.id == first.review_item.id
    assert replay.observation.id == first.observation.id
    assert [e.root for e in replay.stored.evidence_ids] == [
        e.root for e in first.stored.evidence_ids
    ]


def test_merge_rejects_a_different_edge() -> None:
    other = make_edge(id="commercial:contoso:neurosphere:invokes:e-0002")
    with pytest.raises(ValueError, match="same edge"):
        merge_observation(make_edge(), other, [], NOW)


# --------------------------------------------------------------------------- evidence invariant


def _decision_catalog() -> list[EdgeOverride]:
    return [
        make_override("reject", "2026-10-02T00:00:00Z", ident="d-rej", add_evidence_ids=["rev:1"]),
        make_override("accept", "2026-10-03T00:00:00Z", ident="d-acc"),
        make_override(
            "override",
            "2026-10-04T00:00:00Z",
            ident="d-ovr",
            set_confidence=0.1,
            add_evidence_ids=["rev:2"],
        ),
        make_override("lock", "2026-10-05T00:00:00Z", ident="d-lock"),
        make_override("unlock", "2026-10-06T00:00:00Z", ident="d-unlock"),
        make_override(
            "lock", "2026-10-07T00:00:00Z", ident="d-lock2", expiry="2026-10-20T00:00:00Z"
        ),
    ]


def test_no_decision_sequence_removes_evidence_or_security_evidence() -> None:
    """Property-style: any subset in any order, at any clock, retains all evidence."""
    edge = make_edge()
    base_evidence = {e.root for e in edge.evidence_ids}
    base_security = {e.root for e in edge.security_evidence_ids}
    assert SECURITY in base_security
    catalog = _decision_catalog()
    clocks = [NOW, AFTER_EXPIRY, NOW + timedelta(days=-30)]
    checked = 0
    for size in range(len(catalog) + 1):
        for subset in itertools.permutations(catalog, size):
            if size > 4 and size < len(catalog):
                continue  # keep the search bounded; sizes 0-4 plus the full set
            for clock in clocks:
                presented = present_edge(edge, subset, clock)
                assert base_evidence <= set(presented.evidence_ids)
                assert base_security <= set(presented.security_evidence_ids)

                outcome = merge_observation(edge, _new_observation(), subset, clock)
                assert base_evidence <= {e.root for e in outcome.stored.evidence_ids}
                assert base_security <= {e.root for e in outcome.stored.security_evidence_ids}
                assert base_evidence <= set(outcome.presented.evidence_ids)
                assert base_security <= set(outcome.presented.security_evidence_ids)
                assert "trace:new-0001" in {e.root for e in outcome.stored.evidence_ids}
                checked += 1
    assert checked > 1000
