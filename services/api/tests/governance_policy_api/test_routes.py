"""Governance policy routes: drafts, ETag/If-Match, scope filtering, violations, exceptions.

PRP-105 item 6 (acceptance criteria 4 route side, 8): every read filters by the caller's
server-derived scope; an id outside it is 404 like a missing one; writes are audited.
"""

from __future__ import annotations

import pytest
from govpolicy_api_harness import (  # pyright: ignore[reportMissingImports]
    ADMIN,
    ANALYST,
    AUDITOR,
    CONTROL,
    CONTROL_STEWARD,
    FINANCE,
    INVESTIGATOR,
    OPERATIONS,
    OPS_STEWARD,
    STEWARD,
    STEWARD_2,
    SUBJECT,
    VIEWER,
    GovWorld,
    draft_body,
    pid,
    rule,
)
from neurosphere_core.errors import ForbiddenError
from neurosphere_core.governance.policy import violation_canonical_id


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> GovWorld:
    return GovWorld.build(monkeypatch)


# -- drafts ------------------------------------------------------------------------------------


def test_create_draft_is_server_stamped_audited_and_returns_an_etag(world: GovWorld) -> None:
    response = world.create()
    assert response.status_code == 201, response.text
    body = response.json()
    policy = body["policy"]
    assert response.headers["ETag"] == body["etag"]
    assert policy["status"] == "draft"
    assert policy["policy_version"] == 1
    assert policy["previous_version"] is None
    assert policy["domain_id"] == FINANCE
    assert policy["customer_id"] == "contoso"
    assert policy["created_by"] == pid(STEWARD)
    assert policy["content_sha256"].startswith("sha256:")
    assert body["policy_digest"].startswith("sha256:")
    assert body["publish_refusals"] == []
    assert world.operations().count("govpolicy.draft_create") == 2  # before + after


def test_admin_may_draft_but_analyst_and_viewer_may_not(world: GovWorld) -> None:
    created = world.create(ADMIN, policy_id="admin-drafted")
    assert created.status_code == 201, created.text
    for who in (ANALYST, VIEWER, AUDITOR):
        refused = world.create(who, policy_id=f"by-{who[:4]}")
        assert refused.status_code == 403, refused.text
        assert refused.json()["reason"] == "target_out_of_scope"


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda b: b["rules"][0].update(kind="free_text_condition"), "unknown_rule_kind"),
        (lambda b: b["rules"][0]["params"].update(min_owners="one"), "invalid_policy"),
        (lambda b: b["rules"][0].update(expression="agent.owner == null"), "invalid_policy"),
    ],
    ids=["unknown-kind", "bad-params", "free-text-field"],
)
def test_an_invalid_draft_is_refused_and_nothing_is_stored(
    world: GovWorld, mutate: object, reason: str
) -> None:
    body = draft_body()
    mutate(body)  # type: ignore[operator]
    response = world.call("POST", STEWARD, f"/domains/{FINANCE}/policies", json=body)
    assert response.status_code == 422, response.text
    problem = response.json()
    assert problem["code"] == "invalid_schema"
    assert problem["reason"] == reason
    missing = world.call("GET", STEWARD, f"/domains/{FINANCE}/policies/support-owners")
    assert missing.status_code == 404
    assert "govpolicy.draft_create" not in world.operations()


def test_a_body_field_the_server_owns_is_refused(world: GovWorld) -> None:
    body = draft_body(status="published")
    response = world.call("POST", STEWARD, f"/domains/{FINANCE}/policies", json=body)
    assert response.status_code == 422


def test_replace_draft_needs_the_current_etag(world: GovWorld) -> None:
    created = world.create().json()
    path = f"/domains/{FINANCE}/policies/support-owners/draft"
    body = {k: v for k, v in draft_body().items() if k != "policy_id"}
    body["rules"] = [rule(), rule("eu-only", "residency")]

    no_header = world.call("PUT", STEWARD, path, json=body)
    assert no_header.status_code == 422
    stale = world.call("PUT", STEWARD, path, json=body, headers={"If-Match": '"stale"'})
    assert stale.status_code == 409, stale.text
    assert stale.json()["reason"] == "policy_modified"

    fresh = world.call("PUT", STEWARD, path, json=body, headers={"If-Match": created["etag"]})
    assert fresh.status_code == 200, fresh.text
    replaced = fresh.json()
    assert replaced["etag"] != created["etag"]
    assert fresh.headers["ETag"] == replaced["etag"]
    assert [r["rule_id"] for r in replaced["policy"]["rules"]] == ["owner-needed", "eu-only"]
    assert replaced["policy"]["created_by"] == pid(STEWARD)
    # The stale attempt is audited too (before + failed after), then the successful pair.
    assert world.operations().count("govpolicy.draft_replace") == 4


def test_a_second_open_draft_is_refused(world: GovWorld) -> None:
    assert world.create().status_code == 201
    again = world.create()
    assert again.status_code == 409
    assert again.json()["reason"] == "policy_draft_exists"


async def test_a_published_version_is_immutable_and_the_next_draft_is_version_two(
    world: GovWorld,
) -> None:
    created = world.create()
    stored = await world.plane.policies.get("contoso", "support-owners")
    assert stored is not None and created.status_code == 201
    await world.publish_directly(await world.scope_of(STEWARD), stored)

    body = {k: v for k, v in draft_body().items() if k != "policy_id"}
    path = f"/domains/{FINANCE}/policies/support-owners/draft"
    published_etag = world.call("GET", STEWARD, f"/domains/{FINANCE}/policies/support-owners")
    replace = world.call(
        "PUT", STEWARD, path, json=body, headers={"If-Match": published_etag.headers["ETag"]}
    )
    assert replace.status_code == 409
    assert replace.json()["reason"] == "policy_published"

    nxt = world.create()
    assert nxt.status_code == 201, nxt.text
    assert (nxt.json()["policy"]["policy_version"], nxt.json()["policy"]["previous_version"]) == (
        2,
        1,
    )
    versions = world.call("GET", VIEWER, f"/domains/{FINANCE}/policies/support-owners/versions")
    assert [v["policy"]["status"] for v in versions.json()["items"]] == ["published", "draft"]
    first = world.call("GET", VIEWER, f"/domains/{FINANCE}/policies/support-owners?version=1")
    assert first.json()["policy"]["status"] == "published"


# -- reads and scope ---------------------------------------------------------------------------


def test_reads_carry_etags_and_are_audited_as_allowed_reads(world: GovWorld) -> None:
    world.create()
    listed = world.call("GET", VIEWER, f"/domains/{FINANCE}/policies")
    assert listed.status_code == 200, listed.text
    assert [p["policy"]["policy_id"] for p in listed.json()["items"]] == ["support-owners"]
    one = world.call("GET", AUDITOR, f"/domains/{FINANCE}/policies/support-owners")
    assert one.status_code == 200, one.text
    assert one.headers["ETag"] == one.json()["etag"]
    operations = world.operations()
    assert "govpolicy.policy_list" in operations
    assert "govpolicy.policy_read" in operations


def test_an_out_of_scope_id_is_404_like_a_missing_one(world: GovWorld) -> None:
    world.create()
    world.create(OPS_STEWARD, domain=OPERATIONS, policy_id="ops-owners")
    # The FINANCE policy asked for through a domain the caller can read: indistinguishable.
    other = world.call("GET", OPS_STEWARD, f"/domains/{OPERATIONS}/policies/support-owners")
    missing = world.call("GET", OPS_STEWARD, f"/domains/{OPERATIONS}/policies/no-such-policy")
    assert other.status_code == missing.status_code == 404
    assert (other.json()["code"], other.json()["reason"]) == (
        missing.json()["code"],
        missing.json()["reason"],
    )
    versions = world.call(
        "GET", OPS_STEWARD, f"/domains/{OPERATIONS}/policies/support-owners/versions"
    )
    assert versions.status_code == 404
    listed = world.call("GET", OPS_STEWARD, f"/domains/{OPERATIONS}/policies").json()
    assert [p["policy"]["policy_id"] for p in listed["items"]] == ["ops-owners"]


def test_a_domain_outside_the_scope_is_refused(world: GovWorld) -> None:
    world.create()
    for who in (OPS_STEWARD, INVESTIGATOR):
        denied = world.call("GET", who, f"/domains/{FINANCE}/policies")
        assert denied.status_code == 403
    assert world.call("GET", None, f"/domains/{FINANCE}/policies").status_code == 401


def test_a_customer_wide_policy_needs_the_permission_in_the_control_domain(
    world: GovWorld,
) -> None:
    created = world.create(CONTROL_STEWARD, domain=CONTROL, policy_id="customer-owners")
    assert created.status_code == 201, created.text
    assert world.call("GET", STEWARD, f"/domains/{CONTROL}/policies").status_code == 403
    assert world.create(STEWARD, domain=CONTROL, policy_id="x-owners").status_code == 403
    read = world.call("GET", CONTROL_STEWARD, f"/domains/{CONTROL}/policies/customer-owners")
    assert read.status_code == 200


def test_a_policy_id_is_unique_per_customer(world: GovWorld) -> None:
    world.create()
    clash = world.create(OPS_STEWARD, domain=OPERATIONS)
    assert clash.status_code == 409
    assert clash.json()["reason"] == "policy_exists"


# -- violations and exceptions -----------------------------------------------------------------


async def test_violations_are_listed_and_read_in_their_domain_only(world: GovWorld) -> None:
    stored = await world.violation()
    violation_id = stored.violation.violation_id.root
    listed = world.call("GET", VIEWER, f"/domains/{FINANCE}/violations?status=open")
    assert listed.status_code == 200, listed.text
    assert [v["violation"]["violation_id"] for v in listed.json()["items"]] == [violation_id]
    one = world.call("GET", AUDITOR, f"/domains/{FINANCE}/violations/{violation_id}")
    assert one.status_code == 200
    assert one.json()["violation"]["subject"]["canonical_id"] == SUBJECT

    elsewhere = world.call("GET", OPS_STEWARD, f"/domains/{OPERATIONS}/violations/{violation_id}")
    missing = world.call(
        "GET",
        OPS_STEWARD,
        f"/domains/{OPERATIONS}/violations/00000000-0000-4000-8000-00000000dead",
    )
    assert elsewhere.status_code == missing.status_code == 404
    assert elsewhere.json()["reason"] == missing.json()["reason"]
    assert world.call("GET", OPS_STEWARD, f"/domains/{OPERATIONS}/violations").json()["items"] == []


async def test_an_exception_request_opens_a_policy_exception_review(world: GovWorld) -> None:
    stored = await world.violation()
    violation_id = stored.violation.violation_id.root
    path = f"/domains/{FINANCE}/violations/{violation_id}/exception-requests"
    body = {
        "justification_code": "migration_in_progress",
        "justification_text": "Owner hand-over is scheduled for next sprint.",
        "expires_at": world.expiry(30),
    }
    for who in (VIEWER, ADMIN, AUDITOR):
        refused = world.call("POST", who, path, json=body)
        assert refused.status_code == 403, refused.text

    response = world.call("POST", ANALYST, path, json=body)
    assert response.status_code == 201, response.text
    view = response.json()
    assert view["exception"]["status"] == "requested"
    assert view["exception"]["requested_by"] == pid(ANALYST)
    assert view["exception"]["violation_id"] == violation_id
    item = await world.hitl.get(view["review_item_id"])
    assert item is not None
    assert item.kind == "policy_exception"
    assert item.subject_ref == violation_canonical_id("commercial", "contoso", violation_id)
    assert "govpolicy.exception_request" in world.operations()
    # The justification text is never stored or echoed.
    assert "Owner hand-over" not in response.text

    listed = world.call("GET", VIEWER, f"/domains/{FINANCE}/exceptions?status=requested")
    assert [e["exception"]["exception_id"] for e in listed.json()["items"]] == [
        view["exception"]["exception_id"]
    ]


@pytest.mark.parametrize("days", [0, 91])
async def test_an_exception_expiry_is_time_boxed(world: GovWorld, days: int) -> None:
    stored = await world.violation()
    path = f"/domains/{FINANCE}/violations/{stored.violation.violation_id.root}/exception-requests"
    body = {
        "justification_code": "migration_in_progress",
        "justification_text": "Scheduled.",
        "expires_at": world.expiry(days),
    }
    response = world.call("POST", STEWARD, path, json=body)
    assert response.status_code == 422, response.text
    assert response.json()["reason"] == "invalid_exception_expiry"


async def test_the_requester_cannot_review_their_own_exception(world: GovWorld) -> None:
    stored = await world.violation()
    path = f"/domains/{FINANCE}/violations/{stored.violation.violation_id.root}/exception-requests"
    body = {
        "justification_code": "migration_in_progress",
        "justification_text": "Scheduled.",
        "expires_at": world.expiry(10),
    }
    view = world.call("POST", STEWARD, path, json=body).json()
    item = await world.hitl.get(view["review_item_id"])
    assert item is not None and item.maker is not None
    scope = await world.scope_of(STEWARD)
    with pytest.raises(ForbiddenError) as refused:
        await world.hitl.decide(
            view["review_item_id"],
            pid(STEWARD),
            item.maker,
            "approved",
            "self approval attempt",
            None,
            world.now(),
            "corr-self-review",
            scope_hash=scope.scope_hash,
        )
    assert refused.value.reason == "self_approval_forbidden"

    reviewer_scope = await world.scope_of(STEWARD_2)
    reviewer = item.maker.model_copy(
        update={"principal_pseudonym": reviewer_scope.to_contract().principal.principal_pseudonym}
    )
    decision = await world.hitl.decide(
        view["review_item_id"],
        pid(STEWARD_2),
        reviewer,
        "approved",
        "owner hand-over confirmed",
        None,
        world.now(),
        "corr-second-steward",
        scope_hash=reviewer_scope.scope_hash,
    )
    assert decision.decision == "approved"


async def test_an_exception_for_a_violation_elsewhere_is_404(world: GovWorld) -> None:
    stored = await world.violation()
    path = (
        f"/domains/{OPERATIONS}/violations/{stored.violation.violation_id.root}/exception-requests"
    )
    body = {
        "justification_code": "migration_in_progress",
        "justification_text": "Scheduled.",
        "expires_at": world.expiry(10),
    }
    response = world.call("POST", OPS_STEWARD, path, json=body)
    assert response.status_code == 404


# -- bindings ----------------------------------------------------------------------------------


async def test_bindings_start_in_audit_and_are_listed_per_domain(world: GovWorld) -> None:
    world.create(rules=[rule("pii-read", "data_sensitivity_access")])
    stored = await world.plane.policies.get("contoso", "support-owners")
    assert stored is not None
    await world.publish_directly(await world.scope_of(STEWARD), stored)
    listed = world.call("GET", VIEWER, f"/domains/{FINANCE}/bindings")
    assert listed.status_code == 200, listed.text
    items = listed.json()["items"]
    assert items, "publishing created bindings"
    assert {b["binding"]["mode"] for b in items} == {"audit"}
    assert all(b["capability"]["point"] == b["binding"]["point"] for b in items)
    only_sdk = world.call("GET", VIEWER, f"/domains/{FINANCE}/bindings?point=sdk").json()
    assert [b["binding"]["point"] for b in only_sdk["items"]] == ["sdk"]
    assert world.call("GET", OPS_STEWARD, f"/domains/{OPERATIONS}/bindings").json()["items"] == []
