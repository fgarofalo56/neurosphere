"""Legal hold routes: audited with the server-derived identity, and a hold blocks deletion."""

from datetime import timedelta
from typing import Any

from lifecycle_harness import (  # pyright: ignore[reportMissingImports]
    ADMIN,
    CHAIN,
    DOMAIN_ADMIN,
    NOW,
    VIEWER,
    Env,
)
from neurosphere_core.lifecycle import (
    JobStatus,
    LifecycleEngine,
    Rule,
    TargetRegistry,
    load_policy,
)
from neurosphere_core.lifecycle.memory import InMemoryTarget
from neurosphere_core.lifecycle.models import TargetRecord

HOLD: dict[str, Any] = {
    "reason_code": "litigation",
    "target_kind": "catalog",
    "record_id": "doc-1",
    "custodians": ["p-custodian"],
}


def test_without_the_permission_it_is_403(env: Env) -> None:
    for who in (VIEWER, DOMAIN_ADMIN):
        assert env.call(who, "POST", "/holds", json=HOLD).status_code == 403
        assert env.call(who, "GET", "/holds").status_code == 403
        assert env.call(who, "DELETE", "/holds/h1").status_code == 403
    assert env.call(None, "GET", "/holds").status_code == 401


def test_place_list_release_round_trip(env: Env) -> None:
    placed = env.call(ADMIN, "POST", "/holds", json=HOLD)
    assert placed.status_code == 201
    hold = placed.json()
    assert hold["record_id"] == "doc-1"
    assert hold["custodians"] == ["p-custodian"]
    listed = env.call(ADMIN, "GET", "/holds").json()
    assert [h["hold_id"] for h in listed] == [hold["hold_id"]]
    assert env.call(ADMIN, "DELETE", f"/holds/{hold['hold_id']}").status_code == 204
    assert env.call(ADMIN, "GET", "/holds").json() == []
    assert env.call(ADMIN, "DELETE", f"/holds/{hold['hold_id']}").status_code == 404


def test_a_hold_needs_a_selector(env: Env) -> None:
    assert env.call(ADMIN, "POST", "/holds", json={"reason_code": "litigation"}).status_code == 422
    assert env.call(ADMIN, "POST", "/holds", json={"reason_code": "BAD CODE"}).status_code == 422


async def test_place_and_release_are_audited_with_the_server_derived_identity(env: Env) -> None:
    spoof = {**HOLD, "customer_id": "fabrikam", "domain_id": "commercial:fabrikam:x:domain:y"}
    placed = env.call(ADMIN, "POST", "/holds", json=spoof)
    assert placed.status_code == 201  # the caller-supplied customer and domain are ignored
    assert "fabrikam" not in placed.text
    hold_id = placed.json()["hold_id"]
    assert env.call(ADMIN, "DELETE", f"/holds/{hold_id}").status_code == 204

    rows = await env.audit_rows()
    assert [(r.kind, r.operation) for r in rows] == [
        ("before", "lifecycle.hold.place"),
        ("after", "lifecycle.hold.place"),
        ("before", "lifecycle.hold.release"),
        ("after", "lifecycle.hold.release"),
    ]
    assert [r.outcome.detail for r in rows if r.kind == "after"] == [
        "hold_placed",
        "hold_released",
    ]
    assert all(r.outcome.verified for r in rows if r.kind == "after")
    pseudonyms = {r.actor.principal_pseudonym for r in rows}
    assert len(pseudonyms) == 1
    # Every record carries the caller's own scope hash and customer segment, never the body's.
    assert "fabrikam" not in "".join(r.model_dump_json() for r in rows)
    # The hold document itself never stored the spoofed fields either.
    assert all("fabrikam" not in h.model_dump_json() for h in await env.state.holds.active())


async def test_a_failed_hold_write_is_audited_and_surfaces(env: Env) -> None:
    async def boom(hold: Any) -> None:
        raise RuntimeError("store down")

    env.state.holds.place = boom  # type: ignore[method-assign]
    resp = env.call(ADMIN, "POST", "/holds", json=HOLD)
    assert resp.status_code >= 500
    rows = await env.audit_rows()
    assert [r.kind for r in rows] == ["before", "after"]
    assert rows[-1].outcome.result == "failed"
    assert rows[-1].outcome.verified is False


async def test_a_held_target_blocks_deletion_end_to_end() -> None:
    from lifecycle_harness import make_env  # pyright: ignore[reportMissingImports]

    env = make_env(mode="execute")
    assert env.call(ADMIN, "POST", "/holds", json=HOLD).status_code == 201
    body = {
        "action": "delete",
        "target": {"target_kind": "catalog", "container": "catalog", "record_id": "doc-1"},
    }
    request_id = env.call(ADMIN, "POST", "/requests", json=body).json()["request_id"]

    target = InMemoryTarget("catalog", "catalog")
    target.put(
        TargetRecord(
            record_id="doc-1", data_class="telemetry", created_at=NOW - timedelta(days=100)
        )
    )
    registry = TargetRegistry()
    registry.register(target)
    engine = LifecycleEngine(
        policy=load_policy(
            {
                "policy_version": "p1",
                "retain_prompt_response_bodies": False,
                "rules": [
                    {"data_class": "telemetry", "min_retention_days": 0, "max_retention_days": 9}
                ],
            }
        ),
        targets=registry,
        holds=env.state.holds,
        queue=env.state.queue,
        audit=env.audit,
        audit_chain_id=CHAIN,
        cloud="commercial",
        customer_id="contoso",
        clock=lambda: NOW,
        mode="execute",
    )
    (job,) = await env.state.jobs.claim(None, 10)
    outcome = await engine.submit(job.request, job.ctx, dry_run=job.dry_run)
    await env.state.jobs.record_outcome(job.job_id, outcome)

    assert outcome.status is JobStatus.QUEUED
    assert outcome.blocked_by is Rule.LEGAL_HOLD
    assert "doc-1" in target.records
    assert target.delete_calls == 0
    view = env.call(ADMIN, "GET", f"/requests/{request_id}").json()
    assert view["state"] == "queued"
    assert view["outcome"]["reason"] == "legal_hold"

    # Releasing the hold through the API lets the queued request run.
    hold_id = env.call(ADMIN, "GET", "/holds").json()[0]["hold_id"]
    assert env.call(ADMIN, "DELETE", f"/holds/{hold_id}").status_code == 204
    results = await engine.process_queue()
    assert [r.status for r in results] == [JobStatus.COMPLETED]
    assert "doc-1" not in target.records
