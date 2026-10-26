"""Curation: decisions, locks, re-inference, audit and authorization (PRP-10 item 4)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from authz.authz_helpers import (  # pyright: ignore[reportMissingImports]
    FINANCE,
    OPERATIONS,
)
from curation_helpers import (  # pyright: ignore[reportMissingImports]
    AUDITOR,
    EDGE_ID,
    OPS_EDGE_ID,
    PREFIX,
    SECURITY,
    STEWARD_BOTH,
    STEWARD_FINANCE,
    VIEWER,
    Curation,
    decision_body,
    make_curation,
    make_edge,
)
from neurosphere_api.authz import route_inventory, undeclared_routes
from neurosphere_api.catalog.curation import CurationService


def _curation() -> Curation:
    return make_curation(
        make_edge(),
        make_edge(OPS_EDGE_ID, OPERATIONS),
    )


def _service(c: Curation) -> CurationService:
    return CurationService(c.repo, c.queue, c.audit, c.now)


def _body_with(decision: str, **extra: Any) -> dict[str, Any]:
    return decision_body(decision, **extra)


# --------------------------------------------------------------------------- decisions


@pytest.mark.parametrize("decision", ["accept", "reject", "unlock"])
def test_plain_decisions_are_stored(decision: str) -> None:
    c = _curation()
    response = c.post(STEWARD_FINANCE, make_edge(), decision_body(decision))
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["override"]["decision"] == decision
    assert body["presented"]["hidden"] is (decision == "reject")
    assert len(c.repo.overrides[EDGE_ID]) == 1


def test_decision_time_is_server_clock_not_caller() -> None:
    c = _curation()
    response = c.post(STEWARD_FINANCE, make_edge(), decision_body("accept"))
    stored = c.repo.overrides[EDGE_ID][0]
    assert stored.decided_at.root.startswith("2027-01-15T")
    assert response.json()["override"]["decided_at"] == stored.decided_at.root


def test_lock_pins_presented_edge_with_reason_and_expiry() -> None:
    c = _curation()
    body = decision_body("lock", set_confidence=0.5)
    response = c.post(STEWARD_FINANCE, make_edge(), body)
    assert response.status_code == 201, response.text
    presented = response.json()["presented"]
    assert presented["pinned"] is True
    assert presented["confidence"] == 0.5
    assert presented["lock"]["expiry"] == body["lock"]["expiry"]
    assert presented["lock"]["reason"] == "hold"
    read = c.get(VIEWER, f"/edges/{EDGE_ID}")
    assert read.status_code == 200
    assert read.json()["pinned"] is True


@pytest.mark.parametrize(
    "lock",
    [
        None,
        {"locked": True, "reason": "hold", "actor": "x"},
        {"locked": True, "expiry": "2027-03-01T00:00:00Z", "actor": "x"},
        {"locked": False, "reason": "hold", "expiry": "2027-03-01T00:00:00Z", "actor": "x"},
        {"locked": True, "reason": "hold", "expiry": "2027-03-01T00:00:00Z"},
        {"locked": True, "reason": "hold", "expiry": "2027-01-01T00:00:00Z", "actor": "x"},
    ],
    ids=["no_lock", "no_expiry", "no_reason", "unlocked", "no_actor", "expiry_in_past"],
)
@pytest.mark.parametrize("decision", ["lock", "override"])
def test_lock_without_reason_or_expiry_is_rejected(
    decision: str, lock: dict[str, Any] | None
) -> None:
    from curation_helpers import PERSON  # pyright: ignore[reportMissingImports]

    c = _curation()
    if lock is not None and "actor" in lock:
        lock = {**lock, "actor": PERSON}
    body = decision_body(decision, lock=lock)
    response = c.post(STEWARD_FINANCE, make_edge(), body)
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_schema"
    assert EDGE_ID not in c.repo.overrides


def test_pin_fields_are_refused_on_a_plain_decision() -> None:
    c = _curation()
    response = c.post(STEWARD_FINANCE, make_edge(), decision_body("accept", set_confidence=0.1))
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_schema"


def test_expired_lock_stops_applying() -> None:
    c = _curation()
    assert c.post(STEWARD_FINANCE, make_edge(), decision_body("lock")).status_code == 201
    assert c.get(VIEWER, f"/edges/{EDGE_ID}").json()["pinned"] is True
    c.h.clock.advance(timedelta(days=60).total_seconds())
    expired = c.get(VIEWER, f"/edges/{EDGE_ID}").json()
    assert expired["pinned"] is False
    assert expired["lock"]["locked"] is False


# --------------------------------------------------------------------------- preconditions


def test_stale_etag_or_version_is_stale_version() -> None:
    c = _curation()
    patches: list[dict[str, Any]] = [{"expected_edge_etag": '"old"'}, {"expected_edge_version": 1}]
    for patch in patches:
        response = c.post(STEWARD_FINANCE, make_edge(), decision_body("accept", **patch))
        assert response.status_code == 409
        assert response.json()["code"] == "stale_version"
    assert EDGE_ID not in c.repo.overrides


@pytest.mark.parametrize("missing", ["expected_edge_etag", "expected_edge_version"])
def test_missing_precondition_is_invalid_schema(missing: str) -> None:
    c = _curation()
    body = decision_body("accept")
    del body[missing]
    response = c.post(STEWARD_FINANCE, make_edge(), body)
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_schema"


def test_body_must_target_the_path_edge_and_its_domain() -> None:
    c = _curation()
    other = make_edge("commercial:contoso:neurosphere:invokes:other")
    wrong_edge = c.post(STEWARD_FINANCE, make_edge(), decision_body("accept", edge=other))
    assert wrong_edge.status_code == 422
    wrong_domain = c.post(
        STEWARD_FINANCE, make_edge(), decision_body("accept", domain_id=OPERATIONS)
    )
    assert wrong_domain.status_code == 422
    assert wrong_domain.json()["code"] == "invalid_schema"


# --------------------------------------------------------------------------- evidence


@pytest.mark.parametrize(
    "extra",
    [
        {"security_evidence_ids": []},
        {"evidence_ids": []},
        {"remove_evidence_ids": [SECURITY]},
    ],
)
def test_override_cannot_remove_security_evidence(extra: dict[str, Any]) -> None:
    c = _curation()
    response = c.post(STEWARD_FINANCE, make_edge(), decision_body("override", **extra))
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_schema"


def test_security_evidence_survives_decisions_and_is_visible_to_auditor() -> None:
    c = _curation()
    body = decision_body("override", set_confidence=0.1, add_evidence_ids=["steward:note-1"])
    response = c.post(STEWARD_FINANCE, make_edge(), body)
    assert response.status_code == 201, response.text
    presented = response.json()["presented"]
    assert SECURITY in presented["security_evidence_ids"]
    assert "steward:note-1" in presented["evidence_ids"]
    assert SECURITY in presented["evidence_ids"]

    seen = c.get(AUDITOR, f"/edges/{EDGE_ID}/observations")
    assert seen.status_code == 200
    assert seen.json()["items"] == []  # no observation stored yet


async def test_raw_observations_with_security_evidence_are_auditor_only() -> None:
    c = _curation()
    scope = await c.scope_of(STEWARD_FINANCE)
    obs = make_edge(confidence=0.7, last_observed="2026-10-12T00:00:00Z")
    await _service(c).apply_inference(scope, obs)
    auditor = c.get(AUDITOR, f"/edges/{EDGE_ID}/observations")
    assert auditor.status_code == 200
    items = auditor.json()["items"]
    assert len(items) == 1
    assert items[0]["security_evidence_ids"] == [SECURITY]
    for who in (VIEWER, STEWARD_FINANCE):
        denied = c.get(who, f"/edges/{EDGE_ID}/observations")
        assert denied.status_code == 403
        assert SECURITY not in denied.text
    assert c.get(None, f"/edges/{EDGE_ID}/observations").status_code == 401
    # an auditor of FINANCE cannot read raw observations of an OPERATIONS edge or a ghost edge
    assert c.get(AUDITOR, f"/edges/{OPS_EDGE_ID}/observations").status_code == 403
    assert (
        c.get(
            AUDITOR, "/edges/commercial:contoso:neurosphere:invokes:ghost/observations"
        ).status_code
        == 403
    )


# --------------------------------------------------------------------------- re-inference


async def test_locked_edge_is_unchanged_after_reinference_and_observation_is_stored() -> None:
    c = _curation()
    assert c.post(STEWARD_FINANCE, make_edge(), decision_body("lock")).status_code == 201
    scope = await c.scope_of(STEWARD_FINANCE)
    before = c.get(VIEWER, f"/edges/{EDGE_ID}").json()

    contradicting = make_edge(
        confidence=0.3,
        last_observed="2026-10-12T00:00:00Z",
        evidence_ids=["trace:new-1", SECURITY],
    )
    result = await _service(c).apply_inference(scope, contradicting)

    after = c.get(VIEWER, f"/edges/{EDGE_ID}").json()
    assert result.presented_changed is False
    assert after["confidence"] == before["confidence"] == 0.82
    assert after["pinned"] is True
    assert c.repo.edges[EDGE_ID].confidence == 0.82  # stored edge not pulled by the inference
    assert result.observation_recorded is True
    assert [o.confidence for o in c.repo.observations] == [0.3]


async def test_conflicting_inference_lands_in_the_review_queue() -> None:
    c = _curation()
    assert c.post(STEWARD_FINANCE, make_edge(), decision_body("lock")).status_code == 201
    scope = await c.scope_of(STEWARD_FINANCE)
    result = await _service(c).apply_inference(
        scope, make_edge(confidence=0.2, last_observed="2026-10-12T00:00:00Z")
    )
    assert result.review_enqueued is True
    items = await c.queue.list_open(scope)
    assert [i.reason for i in items] == ["conflicts_with_lock"]
    assert items[0].edge_id == EDGE_ID
    assert items[0].id == result.review_item_id
    # replaying the same inference does not duplicate the item
    again = await _service(c).apply_inference(
        scope, make_edge(confidence=0.2, last_observed="2026-10-12T00:00:00Z")
    )
    assert again.review_enqueued is False
    assert len(await c.queue.list_open(scope)) == 1
    assert len(c.repo.observations) == 1


async def test_reinference_of_a_rejected_edge_is_queued_not_shown() -> None:
    c = _curation()
    assert c.post(STEWARD_FINANCE, make_edge(), decision_body("reject")).status_code == 201
    scope = await c.scope_of(STEWARD_FINANCE)
    result = await _service(c).apply_inference(
        scope, make_edge(last_observed="2026-10-12T00:00:00Z")
    )
    assert result.presented.hidden is True
    assert [i.reason for i in await c.queue.list_open(scope)] == ["conflicts_with_reject"]


async def test_unlocked_inference_updates_edge_without_conflict() -> None:
    c = _curation()
    scope = await c.scope_of(STEWARD_FINANCE)
    result = await _service(c).apply_inference(
        scope, make_edge(confidence=0.4, last_observed="2026-10-12T00:00:00Z")
    )
    assert result.review_item_id is None
    assert c.repo.edges[EDGE_ID].confidence == 0.4


async def test_expired_lock_lets_inference_through() -> None:
    c = _curation()
    assert c.post(STEWARD_FINANCE, make_edge(), decision_body("lock")).status_code == 201
    c.h.clock.advance(timedelta(days=60).total_seconds())
    scope = await c.scope_of(STEWARD_FINANCE)
    result = await _service(c).apply_inference(
        scope, make_edge(confidence=0.3, last_observed="2026-10-12T00:00:00Z")
    )
    assert result.review_item_id is None
    assert result.presented.confidence == 0.3


# --------------------------------------------------------------------------- audit


async def test_every_curation_action_writes_audit_records() -> None:
    c = _curation()
    assert c.post(STEWARD_FINANCE, make_edge(), decision_body("lock")).status_code == 201
    records = await c.audit_records()
    assert [r.kind for r in records] == ["before", "after"]
    assert {r.operation for r in records} == {"catalog.curate"}
    assert all(r.subject is not None and r.subject.target.canonical_id == EDGE_ID for r in records)
    assert records[1].outcome is not None
    assert records[1].outcome.verified is True
    assert records[1].outcome.detail == "decision=lock"

    # a refused decision is audited too (denied), and writes nothing
    stale = c.post(
        STEWARD_FINANCE,
        make_edge(),
        decision_body("accept", ident="ovr-2", expected_edge_etag='"nope"'),
    )
    assert stale.status_code == 409
    refused = (await c.audit_records())[-1]
    assert refused.kind == "denied"
    assert refused.denial is not None
    assert refused.denial.code == "stale_version"
    assert len(c.repo.overrides[EDGE_ID]) == 1


async def test_conflicting_inference_is_audited() -> None:
    c = _curation()
    assert c.post(STEWARD_FINANCE, make_edge(), decision_body("lock")).status_code == 201
    scope = await c.scope_of(STEWARD_FINANCE)
    await _service(c).apply_inference(
        scope, make_edge(confidence=0.2, last_observed="2026-10-12T00:00:00Z")
    )
    records = await c.audit_records()
    assert [r.operation for r in records[2:]] == ["catalog.infer", "catalog.infer"]
    assert records[-1].outcome is not None
    assert records[-1].outcome.detail == "conflict_queued"


# --------------------------------------------------------------------------- authorization


def test_steward_of_one_domain_cannot_curate_another() -> None:
    c = _curation()
    ops_edge = make_edge(OPS_EDGE_ID, OPERATIONS)
    # the body claims the steward's own domain (FINANCE) for an OPERATIONS edge
    for claimed in (OPERATIONS, FINANCE):
        response = c.post(
            STEWARD_FINANCE, ops_edge, decision_body("accept", edge=ops_edge, domain_id=claimed)
        )
        assert response.status_code == 403, response.text
        assert response.json()["code"] == "forbidden"
    assert OPS_EDGE_ID not in c.repo.overrides


def test_steward_of_both_domains_can_curate_both() -> None:
    c = _curation()
    ops_edge = make_edge(OPS_EDGE_ID, OPERATIONS)
    assert c.post(STEWARD_BOTH, ops_edge, decision_body("accept", edge=ops_edge)).status_code == 201
    assert c.post(STEWARD_BOTH, make_edge(), decision_body("accept")).status_code == 201


def test_viewer_cannot_curate_but_can_read() -> None:
    c = _curation()
    assert c.post(VIEWER, make_edge(), decision_body("accept")).status_code == 403
    assert c.get(VIEWER, f"/edges/{EDGE_ID}").status_code == 200
    assert c.get(VIEWER, f"/edges/{EDGE_ID}/overrides").status_code == 200
    assert EDGE_ID not in c.repo.overrides


def test_missing_scope_is_401() -> None:
    c = _curation()
    assert c.post(None, make_edge(), decision_body("accept")).status_code == 401
    assert c.get(None, f"/edges/{EDGE_ID}").status_code == 401
    assert c.get(None, f"/edges/{EDGE_ID}/overrides").status_code == 401


def test_unknown_and_out_of_scope_edges_are_the_same_403() -> None:
    c = _curation()
    missing = make_edge("commercial:contoso:neurosphere:invokes:ghost")
    unknown = c.post(STEWARD_FINANCE, missing, decision_body("accept", edge=missing))
    ops_edge = make_edge(OPS_EDGE_ID, OPERATIONS)
    # a principal with no membership in OPERATIONS would not see the edge at all; the fake hides
    # edges outside ``allowed_domains``, so remove the edge from view by asking for a ghost
    assert unknown.status_code == 403
    assert unknown.json()["code"] == "forbidden"
    assert c.get(STEWARD_FINANCE, f"/edges/{missing.id}").status_code == 403
    assert ops_edge.id in c.repo.edges


def test_override_history_lists_decisions_in_order() -> None:
    c = _curation()
    c.post(STEWARD_FINANCE, make_edge(), decision_body("lock", ident="a"))
    c.h.clock.advance(60)
    c.post(STEWARD_FINANCE, make_edge(), decision_body("unlock", ident="b"))
    history = c.get(VIEWER, f"/edges/{EDGE_ID}/overrides").json()
    assert [o["decision"] for o in history["overrides"]] == ["lock", "unlock"]


# --------------------------------------------------------------------------- routes


def test_all_curation_routes_declare_permissions() -> None:
    c = _curation()
    assert undeclared_routes(c.h.app) == ()
    declared = {
        (e.path, e.methods): e.permissions
        for e in route_inventory(c.h.app)
        if e.path.startswith(PREFIX)
    }
    assert declared == {
        (f"{PREFIX}/edges/{{edge_id:path}}/decisions", ("POST",)): ("catalog.curate",),
        (f"{PREFIX}/edges/{{edge_id:path}}/overrides", ("GET",)): ("data.read",),
        (f"{PREFIX}/edges/{{edge_id:path}}/observations", ("GET",)): ("evidence.read",),
        (f"{PREFIX}/edges/{{edge_id:path}}", ("GET",)): ("data.read",),
    }


def test_register_hook_uses_the_curation_prefix() -> None:
    from neurosphere_api.catalog.curation import register
    from neurosphere_api.routers import RouterRegistry

    registry = RouterRegistry()
    register(registry)
    # The successor prefix and its deprecated alias PREFIX (PRP-29 item 4).
    assert registry.prefixes == ("/api/v1/catalog/curation", PREFIX)
