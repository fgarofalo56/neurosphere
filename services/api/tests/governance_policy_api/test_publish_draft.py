"""Publish and retire draft a ``governance_policy_publish`` intent; they never write the policy.

PRP-105 item 6 (acceptance criteria 5 and 10): the intent goes through the one action plane
(``ActionApi.draft``) with the item-3 diff (``test /policy_version``, ``test /policy_digest``,
``replace /status``); with no platform-control write target it is advisory ("no supported write
connector") and the version stays a draft. The publish dry run refuses ``rule_kind_unavailable``
and ``enforce_requires_mode_change`` before anything is drafted.
"""

from __future__ import annotations

from typing import Any

import pytest
from govpolicy_api_harness import (  # pyright: ignore[reportMissingImports]
    ADMIN,
    ANALYST,
    FINANCE,
    OPERATIONS,
    OPS_STEWARD,
    STEWARD,
    VIEWER,
    GovWorld,
    rule,
)
from neurosphere_core.governance.policy import parse_publish_diff, policy_digest

POLICY = "/domains/" + FINANCE + "/policies/support-owners"
KEY = "govpolicy-publish-0001"


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> GovWorld:
    return GovWorld.build(monkeypatch)


def _stage(world: GovWorld, verb: str, who: str = STEWARD, **over: Any) -> Any:
    body: dict[str, Any] = {"version": 1, "idempotency_key": KEY}
    body.update(over)
    return world.call("POST", who, f"{POLICY}/{verb}", json=body)


def test_publish_drafts_an_advisory_intent_and_the_policy_stays_a_draft(world: GovWorld) -> None:
    assert world.create().status_code == 201
    before = world.call("GET", STEWARD, POLICY).json()

    response = _stage(world, "publish")
    assert response.status_code == 201, response.text
    view = response.json()
    intent = view["intent"]
    assert intent["action_kind"] == "governance_policy_publish"
    assert intent["state"] == "drafted"
    assert intent["target"] == {
        "canonical_id": "commercial:contoso:neurosphere:governance_policy:support-owners",
        "entity_type": "governance_policy",
    }
    assert intent["target_version"] == "v1"
    assert view["advisory"] is True  # no platform-control write target before PRP-108
    assert view["requires_approval"] is True
    parsed = parse_publish_diff(intent["proposed_diff"])
    assert (parsed.stage, parsed.policy_version) == ("publish", 1)
    assert parsed.policy_digest == before["policy_digest"]

    after = world.call("GET", STEWARD, POLICY).json()
    assert after["policy"]["status"] == "draft"
    assert after["etag"] == before["etag"]

    replay = _stage(world, "publish")
    assert replay.status_code == 200
    assert replay.json()["intent"]["intent_id"] == intent["intent_id"]


def test_validation_says_no_supported_write_connector(world: GovWorld) -> None:
    world.create()
    intent_id = _stage(world, "publish").json()["intent"]["intent_id"]
    validated = world.client.post(
        f"/api/v1/actions/domains/{FINANCE}/intents/{intent_id}/validate",
        headers=world.auth(STEWARD),
    )
    assert validated.status_code == 200, validated.text
    checks = {c["check_id"]: c for c in validated.json()["intent"]["prerequisite_results"]}
    assert "no supported write connector" in checks["write_connector_supported"]["detail"]
    status = world.call("GET", STEWARD, POLICY).json()["policy"]["status"]
    assert status == "draft"


@pytest.mark.parametrize(
    ("over", "reason"),
    [
        ({"rules": [rule("cards", "content_rule")]}, "rule_kind_unavailable"),
        ({"rules": [rule("spend", "budget")]}, "rule_kind_unavailable"),
        ({"mode": "enforce"}, "enforce_requires_mode_change"),
    ],
    ids=["content-rule-unbound", "budget", "enforce"],
)
def test_the_publish_dry_run_refuses_before_drafting(
    world: GovWorld, over: dict[str, Any], reason: str
) -> None:
    created = world.create(**over)
    assert created.status_code == 201, created.text  # a draft may hold them
    assert created.json()["publish_refusals"][0]["reason"] == reason
    response = _stage(world, "publish")
    assert response.status_code == 422, response.text
    assert response.json()["reason"] == reason
    listed = world.client.get(
        f"/api/v1/actions/domains/{FINANCE}/intents", headers=world.auth(STEWARD)
    )
    assert listed.json()["items"] == []


def test_publish_needs_govpolicy_manage_in_the_domain(world: GovWorld) -> None:
    world.create()
    for who in (VIEWER, ANALYST, OPS_STEWARD):
        denied = _stage(world, "publish", who)
        assert denied.status_code == 403, denied.text
    drafted = _stage(world, "publish", ADMIN, idempotency_key="govpolicy-publish-admin1")
    assert drafted.status_code == 201, drafted.text


def test_publish_of_a_missing_or_foreign_version_is_404(world: GovWorld) -> None:
    world.create()
    assert _stage(world, "publish", version=2).status_code == 404
    world.create(OPS_STEWARD, domain=OPERATIONS, policy_id="ops-owners")
    foreign = world.call(
        "POST",
        STEWARD,
        f"/domains/{FINANCE}/policies/ops-owners/publish",
        json={"version": 1, "idempotency_key": KEY},
    )
    assert foreign.status_code == 404


async def test_retire_drafts_an_intent_and_the_version_stays_published(world: GovWorld) -> None:
    world.create()
    assert _stage(world, "retire").json()["reason"] == "policy_not_published"
    stored = await world.plane.policies.get("contoso", "support-owners")
    assert stored is not None
    published = await world.publish_directly(await world.scope_of(STEWARD), stored)

    refused = _stage(world, "publish", idempotency_key="govpolicy-publish-again1")
    assert refused.status_code == 422
    assert refused.json()["reason"] == "policy_not_draft"

    response = _stage(world, "retire", idempotency_key="govpolicy-retire-00001")
    assert response.status_code == 201, response.text
    parsed = parse_publish_diff(response.json()["intent"]["proposed_diff"])
    assert (parsed.stage, parsed.policy_version) == ("retire", 1)
    assert parsed.policy_digest == policy_digest(published.policy)
    assert world.call("GET", STEWARD, POLICY).json()["policy"]["status"] == "published"


def test_no_route_writes_a_published_state(world: GovWorld) -> None:
    """Every method on every policy path leaves the stored status a draft."""
    world.create()
    _stage(world, "publish")
    body = {"display_name": "x", "severity": "low", "rules": [rule()], "status": "published"}
    world.call("PUT", STEWARD, f"{POLICY}/draft", json=body, headers={"If-Match": "*"})
    world.call("PATCH", STEWARD, POLICY, json={"status": "published"})
    assert world.call("GET", STEWARD, POLICY).json()["policy"]["status"] == "draft"
    assert "govpolicy.publish" not in world.operations()
