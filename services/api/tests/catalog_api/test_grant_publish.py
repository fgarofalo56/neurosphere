"""Grant publish and unpublish through the catalog API (PRP-34 item 5).

Drafting goes through the one action plane (no new executor path); the draft carries the
connector ``dry_run`` diff; the catalog Grant records a publication only after a verified,
succeeded intent, and the recording is a real catalog write (provenance plus ``apim_*``
attributes).
"""

from __future__ import annotations

from typing import Any

from gateway_mode_harness import (  # pyright: ignore[reportMissingImports]
    ADMIN,
    GATEWAY_ID,
    OPERATOR,
    OUTSIDER,
    STEWARD,
    VIEWER,
    problem,
)
from grant_publish_harness import (  # pyright: ignore[reportMissingImports]
    ACTIONS,
    GRANT_ID,
    KEY_A,
    GrantEnv,
    grant_doc,
    make_grant_env,
)
from neurosphere_connector_apim_gateway.grants import publication_names

NAMES = publication_names(GRANT_ID)


def _ops(view: dict[str, Any]) -> dict[str, Any]:
    return {op["path"]: op for op in view["intent"]["proposed_diff"]["operations"]}


def _publish_and_execute(g: GrantEnv, **body: Any) -> str:
    drafted = g.publish(STEWARD, **body)
    assert drafted.status_code == 201, drafted.text
    intent_id = drafted.json()["intent"]["intent_id"]
    g.execute(intent_id)
    return intent_id


# -- authorization ---------------------------------------------------------------------------


def test_draft_needs_action_propose_on_the_grants_domain() -> None:
    g = make_grant_env()
    assert g.publish(None).status_code == 401
    for who in (VIEWER, ADMIN, OUTSIDER):
        response = g.publish(who)
        assert response.status_code == 403, (who, response.text)
    assert g.unpublish(VIEWER).status_code == 403
    assert g.unpublish(OUTSIDER).status_code == 403
    assert g.record(VIEWER, "00000000-0000-4000-8000-000000000001").status_code == 403
    assert g.env.apim.writes() == []


# -- draft ------------------------------------------------------------------------------------


def test_publish_drafts_an_intent_using_the_dry_run_diff() -> None:
    g = make_grant_env()
    response = g.publish(STEWARD)
    assert response.status_code == 201, response.text
    view = response.json()
    intent = view["intent"]
    assert intent["action_kind"] == "grant_publish"
    assert intent["state"] == "drafted"
    assert intent["target"] == {"canonical_id": GRANT_ID, "entity_type": "grant"}
    assert intent["target_version"] == "grant-unpublished"
    ops = _ops(view)
    # The dry_run diff: plan digest bound in as a test operation, then the publication.
    assert ops["/plan_digest"]["op"] == "test"
    digest = ops["/plan_digest"]["value"]
    assert len(digest) == 64
    publication = ops["/publication"]["value"]
    assert publication["gateway_id"] == GATEWAY_ID
    assert publication["access"] == "subscription"
    assert publication["tokens_per_minute"] == 20000
    assert publication["token_quota"] == 5000000
    assert publication["token_quota_period"] == "Monthly"  # noqa: S105
    assert publication["principal_object_id"] == "11111111-2222-4333-8444-555555555555"
    # The same digest the connector computes now (drafting read the live gateway, wrote nothing).
    plan = g.env.apim.calls
    assert g.env.apim.writes() == []
    assert any(c.path == NAMES.product for c in plan)
    # Same intent through the action API.
    listed = g.call("GET", STEWARD, f"{ACTIONS}/domains/{grant_doc()['domain_id']}/intents")
    assert [i["intent"]["intent_id"] for i in listed.json()["items"]] == [intent["intent_id"]]


def test_replay_returns_the_original_intent() -> None:
    g = make_grant_env()
    first = g.publish(STEWARD)
    again = g.publish(STEWARD)
    assert again.status_code == 200
    assert again.json()["intent"]["intent_id"] == first.json()["intent"]["intent_id"]
    assert KEY_A  # idempotency key is caller supplied


def test_publish_refusals() -> None:
    g = make_grant_env()
    assert g.publish(STEWARD, gateway_id="gw-" + "c" * 32).status_code == 404
    group = problem(g.publish(STEWARD, access="entra", gateway_id="nope"))
    assert group["code"] == "invalid_schema"  # malformed gateway id


def test_group_grant_cannot_use_a_subscription_key() -> None:
    doc = grant_doc()
    doc["principal"] = {
        "kind": "entra_group",
        "object_id": doc["principal"]["object_id"],
        "display": "Analysts",
    }
    g = make_grant_env(grant=doc)
    refused = problem(g.publish(STEWARD))
    assert refused["code"] == "invalid_schema"
    assert refused["reason"] == "group_needs_entra_access"
    assert g.publish(STEWARD, access="entra").status_code == 201


def test_disabled_and_unlimited_and_mcp_grants_are_refused() -> None:
    g = make_grant_env(grant=grant_doc(enabled=False))
    assert problem(g.publish(STEWARD))["reason"] == "grant_disabled"
    doc = grant_doc()
    doc["limits"] = {
        "tokens_per_minute": None,
        "token_quota": None,
        "quota_period": None,
        "requests_per_minute": 10,
        "mcp_calls_per_minute": None,
    }
    g = make_grant_env(grant=doc)
    assert problem(g.publish(STEWARD))["reason"] == "grant_needs_token_limit"


def test_observe_mode_gateway_is_refused() -> None:
    g = make_grant_env(manage=False)
    refused = problem(g.publish(STEWARD))
    assert refused["reason"] == "gateway_observe_mode"
    assert g.env.apim.writes() == []


def test_missing_target_api_is_refused() -> None:
    g = make_grant_env()
    refused = problem(g.publish(STEWARD, api_id="absent"))
    assert refused["reason"] == "target_api_missing"


# -- recording --------------------------------------------------------------------------------


def test_record_refuses_an_intent_that_has_not_executed() -> None:
    g = make_grant_env()
    intent_id = g.publish(STEWARD).json()["intent"]["intent_id"]
    refused = g.record(STEWARD, intent_id)
    assert refused.status_code == 422
    assert problem(refused)["reason"] == "intent_not_verified"
    assert g.record(STEWARD, "00000000-0000-4000-8000-0000000000ff").status_code == 404
    assert "apim_published" not in (g.stored().model_dump(mode="json").get("attributes") or {})


def test_provenance_is_recorded_after_a_verified_publish() -> None:
    g = make_grant_env()
    before = g.stored()
    intent_id = _publish_and_execute(g)
    # The gateway really changed.
    assert {NAMES.fragment, NAMES.product, NAMES.product_policy, NAMES.subscription} <= set(
        g.env.apim.resources
    )
    response = g.record(STEWARD, intent_id)
    assert response.status_code == 200, response.text
    doc = response.json()
    assert doc["provenance"]["source_id"] == GATEWAY_ID
    assert doc["provenance"]["method"] == "declared"
    assert doc["provenance"]["connector_version"] == "apim-gateway/0.1.0"
    attrs = doc["attributes"]
    assert attrs["apim_published"] is True
    assert attrs["apim_gateway_id"] == GATEWAY_ID
    assert attrs["apim_intent_id"] == intent_id
    assert attrs["apim_ownership"] == "recorded"
    assert NAMES.product in attrs["apim_created"].split(",")
    assert "apis/llm" not in attrs["apim_resources"]
    # Stored, version moved, nothing else about the grant changed.
    after = g.stored()
    assert after.etag.root != before.etag.root
    assert after.model_dump(mode="json")["principal"] == before.model_dump(mode="json")["principal"]
    # Recording the same intent again is a no-op.
    again = g.record(STEWARD, intent_id)
    assert again.status_code == 200
    assert again.json()["etag"] == doc["etag"]
    # No key material anywhere in the catalog document.
    assert "pk-generated-secret" not in response.text


def test_unpublish_reverses_the_recorded_publication() -> None:
    g = make_grant_env()
    publish_id = _publish_and_execute(g)
    assert g.record(STEWARD, publish_id).status_code == 200
    drafted = g.unpublish(STEWARD)
    assert drafted.status_code == 201, drafted.text
    view = drafted.json()
    assert view["intent"]["action_kind"] == "grant_unpublish"
    assert view["intent"]["target_version"] == "grant-published"
    ops = _ops(view)
    assert ops["/publication"]["op"] == "remove"
    assert NAMES.product in ops["/publication/resources"]["value"]
    assert "/plan_digest" in ops
    unpublish_id = view["intent"]["intent_id"]
    g.execute(unpublish_id)
    assert set(g.env.apim.resources) == {"apis/llm"}
    recorded = g.record(STEWARD, unpublish_id)
    assert recorded.status_code == 200, recorded.text
    attrs = recorded.json()["attributes"]
    assert attrs["apim_published"] is False
    assert attrs["apim_created"] is None
    # Nothing left to unpublish.
    assert (
        problem(g.unpublish(STEWARD, idempotency_key="idem-grant-publish-000009"))["reason"]
        == "grant_not_published"
    )


def test_unpublish_before_publish_and_without_ownership_is_refused() -> None:
    g = make_grant_env()
    assert problem(g.unpublish(STEWARD))["reason"] == "grant_not_published"
    blind = make_grant_env(wire_records=False)
    intent_id = _publish_and_execute(blind)
    recorded = blind.record(STEWARD, intent_id)
    assert recorded.json()["attributes"]["apim_ownership"] == "unrecorded"
    assert problem(blind.unpublish(STEWARD))["reason"] == "ownership_unrecorded"


def test_entra_publish_records_without_a_subscription() -> None:
    g = make_grant_env()
    intent_id = _publish_and_execute(g, access="entra")
    assert NAMES.subscription not in g.env.apim.resources
    assert g.record(OPERATOR, intent_id).status_code == 200
