"""POST/GET /api/v1/lifecycle/requests: permission, persistence, audit, worker round trip."""

from datetime import timedelta
from typing import Any

from lifecycle_harness import (  # pyright: ignore[reportMissingImports]
    ADMIN,
    CHAIN,
    DOMAIN_ADMIN,
    NOW,
    VIEWER,
    Env,
    make_env,
)
from neurosphere_core.audit import AuditContext
from neurosphere_core.lifecycle import (
    ActionKind,
    LifecycleEngine,
    TargetRef,
    TargetRegistry,
    load_policy,
)
from neurosphere_core.lifecycle.memory import InMemoryTarget
from neurosphere_core.lifecycle.models import TargetRecord

BODY: dict[str, Any] = {
    "action": "delete",
    "target": {"target_kind": "catalog", "container": "catalog", "record_id": "doc-1"},
}


def test_without_the_permission_it_is_403_and_nothing_is_stored(env: Env) -> None:
    for who in (VIEWER, DOMAIN_ADMIN):  # a viewer, and an admin who is not customer-level
        resp = env.call(who, "POST", "/requests", json=BODY)
        assert resp.status_code == 403, who
    assert env.call(None, "POST", "/requests", json=BODY).status_code == 401
    assert env.call(VIEWER, "GET", "/requests").status_code == 403
    assert env.call(VIEWER, "GET", "/status").status_code == 403
    assert env.call(VIEWER, "GET", "/requests/anything").status_code == 403


def test_a_job_is_persisted_and_status_shows_pending(env: Env) -> None:
    resp = env.call(ADMIN, "POST", "/requests", json=BODY)
    assert resp.status_code == 202
    accepted = resp.json()
    assert accepted["state"] == "pending"
    assert accepted["deduplicated"] is False
    got = env.call(ADMIN, "GET", f"/requests/{accepted['request_id']}")
    assert got.status_code == 200
    view = got.json()
    assert view["state"] == "pending"
    assert view["outcome"] is None
    assert view["action"] == "delete"
    assert view["dry_run"] is False
    listed = env.call(ADMIN, "GET", "/requests").json()
    assert [j["request_id"] for j in listed] == [accepted["request_id"]]
    assert env.call(ADMIN, "GET", "/requests/nope").status_code == 404


def test_equal_pending_request_is_deduplicated(env: Env) -> None:
    first = env.call(ADMIN, "POST", "/requests", json=BODY).json()
    second = env.call(ADMIN, "POST", "/requests", json=BODY).json()
    assert second["deduplicated"] is True
    assert second["request_id"] == first["request_id"]
    assert len(env.call(ADMIN, "GET", "/requests").json()) == 1


def test_bad_shapes_are_rejected(env: Env) -> None:
    assert env.call(ADMIN, "POST", "/requests", json={"action": "export"}).status_code == 422
    assert env.call(ADMIN, "POST", "/requests", json={"action": "delete"}).status_code == 422
    assert env.call(ADMIN, "POST", "/requests", json={"action": "bogus"}).status_code == 422
    assert env.call(ADMIN, "POST", "/requests", json={"action": "erase_subject"}).status_code == 422
    ok = env.call(ADMIN, "POST", "/requests", json={"action": "erase_subject", "subject_id": "s1"})
    assert ok.status_code == 202


async def test_the_write_is_audited_with_the_server_derived_identity(env: Env) -> None:
    body = {**BODY, "customer_id": "fabrikam", "domain_id": "commercial:fabrikam:x:domain:y"}
    assert env.call(ADMIN, "POST", "/requests", json=body).status_code == 202
    rows = await env.audit_rows()
    assert [r.kind for r in rows] == ["before", "after"]
    assert {r.operation for r in rows} == {"lifecycle.request.submit"}
    assert rows[-1].outcome.detail == "job_persisted"
    assert rows[-1].outcome.verified is True
    # The stored job carries the caller's own audit context, never the body's customer or domain.
    job = (await env.state.jobs.list())[0]
    assert job.ctx.actor.principal_pseudonym == job.requested_by
    assert "fabrikam" not in job.model_dump_json()


async def test_audit_targets_are_refused_and_audited(env: Env) -> None:
    body = {
        "action": "delete",
        "target": {"target_kind": "catalog", "container": "audit", "record_id": "x"},
    }
    resp = env.call(ADMIN, "POST", "/requests", json=body)
    assert resp.status_code == 403
    assert await env.state.jobs.list() == []
    rows = await env.audit_rows()
    assert [(r.kind, r.denial.reason) for r in rows] == [("denied", "audit_immutable")]


def test_dry_run_flag_is_stored(env: Env) -> None:
    resp = env.call(ADMIN, "POST", "/requests", json={**BODY, "dry_run": True})
    job = env.call(ADMIN, "GET", f"/requests/{resp.json()['request_id']}").json()
    assert job["dry_run"] is True


def test_unconfigured_service_is_503() -> None:
    env = make_env(configure=False)
    assert env.call(ADMIN, "GET", "/status").status_code == 503


async def test_outcome_appears_after_the_worker_ran() -> None:
    """API persists, the worker's engine runs it, the outcome is visible on the same route."""
    env = make_env(mode="execute")
    resp = env.call(ADMIN, "POST", "/requests", json=BODY)
    request_id = resp.json()["request_id"]

    target = InMemoryTarget("catalog", "catalog")
    target.put(
        TargetRecord(
            record_id="doc-1", data_class="telemetry", created_at=NOW - timedelta(days=100)
        )
    )
    registry = TargetRegistry()
    registry.register(target)
    policy = load_policy(
        {
            "policy_version": "p1",
            "retain_prompt_response_bodies": False,
            "rules": [
                {"data_class": "telemetry", "min_retention_days": 0, "max_retention_days": 9}
            ],
        }
    )
    engine = LifecycleEngine(
        policy=policy,
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
    assert isinstance(job.ctx, AuditContext)
    outcome = await engine.submit(job.request, job.ctx, dry_run=job.dry_run)
    await env.state.jobs.record_outcome(job.job_id, outcome)

    view = env.call(ADMIN, "GET", f"/requests/{request_id}").json()
    assert view["state"] == "done"
    assert view["outcome"]["status"] == "completed"
    assert view["outcome"]["effect"] == "deleted"
    assert "doc-1" not in target.records
    assert ActionKind.DELETE.value == view["action"]
    assert TargetRef(target_kind="catalog", container="catalog", record_id="doc-1")
