"""PRP-137 item 5: the alias routes and the ``agent_identity`` builder over in-memory stores."""

from __future__ import annotations

import json

import pytest
from alias_harness import (  # pyright: ignore[reportMissingImports]
    AUDITOR,
    BOTH_STEWARD,
    EXPIRING,
    FINANCE,
    OPS,
    OPS_STEWARD,
    STEWARD,
    VIEWER,
    agent_id,
    body,
    build,
    configure_env,
)


@pytest.fixture(autouse=True)
def _auth(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_env(monkeypatch)


def test_the_component_is_ok() -> None:
    assert build().composed.registry.get("agent_identity").state == "ok"


def test_a_steward_declares_an_alias_and_gets_the_job() -> None:
    world = build()
    response = world.put(FINANCE, STEWARD, body("asst-1", reason="renamed_in_foundry"))
    assert response.status_code == 200, response.text
    out = response.json()
    assert out["outcome"] == "created"
    assert out["alias_id"] and out["retired_alias_id"] is None
    assert out["reresolve_needed"] is True
    assert out["reresolve_job"] == {
        "command": "python -m neurosphere_workers.agent_identity reresolve",
        "arguments": [
            "--customer",
            "contoso",
            "--source-id",
            "foundry",
            "--external-agent-id",
            "asst-1",
        ],
    }


def test_the_alias_can_be_read_back() -> None:
    world = build()
    assert world.put(FINANCE, STEWARD, body("asst-1")).status_code == 200
    read = world.get(FINANCE, VIEWER, source_id="foundry", external_agent_id="asst-1")
    assert read.status_code == 200, read.text
    assert read.json() == {
        "source_id": "foundry",
        "external_agent_id": "asst-1",
        "target_agent_id": agent_id("fin-one"),
    }


def test_an_unknown_alias_is_404() -> None:
    world = build()
    read = world.get(FINANCE, VIEWER, source_id="foundry", external_agent_id="nope")
    assert read.status_code == 404


@pytest.mark.parametrize(
    "target",
    [
        agent_id("missing"),  # not in the catalog
        agent_id("ops-one"),  # exists, other domain, but outside this caller's scope
        "commercial:other:foundry:agent:x",  # another customer
        "commercial:contoso:foundry:model:x",  # not an agent
        "not-an-id",
    ],
)
def test_every_unusable_target_is_the_same_404(target: str) -> None:
    world = build()
    reference = world.put(FINANCE, STEWARD, body(target=agent_id("missing")))
    response = world.put(FINANCE, STEWARD, body(target=target))
    assert response.status_code == 404
    assert response.status_code == reference.status_code
    assert response.json().get("reason") == reference.json().get("reason")
    assert response.json().get("detail") == reference.json().get("detail")


def test_a_target_in_another_domain_the_caller_can_read_is_the_same_404() -> None:
    world = build()
    reference = world.put(FINANCE, BOTH_STEWARD, body(target=agent_id("missing")))
    response = world.put(FINANCE, BOTH_STEWARD, body(target=agent_id("ops-one")))
    assert response.status_code == reference.status_code == 404
    assert response.json().get("reason") == reference.json().get("reason")
    # the same target is fine through its own domain
    assert world.put(OPS, BOTH_STEWARD, body(target=agent_id("ops-one"))).status_code == 200


def test_a_target_in_another_domain_is_not_revealed_by_the_read() -> None:
    world = build()
    assert world.put(OPS, BOTH_STEWARD, body("asst-9", agent_id("ops-one"))).status_code == 200
    seen = world.get(FINANCE, BOTH_STEWARD, source_id="foundry", external_agent_id="asst-9")
    assert seen.status_code == 404
    assert agent_id("ops-one") not in seen.text


@pytest.mark.parametrize("who", [VIEWER, AUDITOR, OPS_STEWARD])
def test_only_catalog_curate_in_the_domain_writes(who: str) -> None:
    world = build()
    before = world.audit_count()
    response = world.put(FINANCE, who, body())
    assert response.status_code == 403
    assert world.audit_count() == before + 1, "the denial was not recorded"
    ok = world.get(FINANCE, STEWARD, source_id="foundry", external_agent_id="asst-1")
    assert ok.status_code == 404, "nothing was written"


def test_an_expired_role_is_denied_and_recorded() -> None:
    world = build()
    world.clock.advance(11)
    before = world.audit_count()
    assert world.put(FINANCE, EXPIRING, body()).status_code == 403
    assert world.audit_count() == before + 1


def test_a_viewer_of_another_domain_cannot_read() -> None:
    world = build()
    before = world.audit_count()
    read = world.get(FINANCE, OPS_STEWARD, source_id="foundry", external_agent_id="asst-1")
    assert read.status_code == 403
    assert world.audit_count() == before + 1


def test_no_token_is_401() -> None:
    world = build()
    client = world.composed.client()
    assert (
        client.put(f"/api/v1/agent-identity/domains/{FINANCE}/aliases", json=body()).status_code
        == 401
    )


def test_a_body_with_extra_or_malformed_fields_is_422() -> None:
    world = build()
    assert world.put(FINANCE, STEWARD, body(extra="x")).status_code == 422
    assert world.put(FINANCE, STEWARD, body(reason="Free text with spaces")).status_code == 422


def test_audit_records_carry_ids_and_codes_not_event_content() -> None:
    world = build()
    external = "0f1e2d3c-4b5a-4968-8776-655443322110"  # a GUID-shaped telemetry id
    assert world.put(FINANCE, STEWARD, body(external, reason="renamed")).status_code == 200
    text = json.dumps(world.audit_docs(), default=str)
    assert external not in text
    assert "agent_identity.alias_declare" in text
    assert "created" in text and "renamed" in text


def test_an_unconfigured_plane_is_503_after_authorization() -> None:
    world = build()
    from neurosphere_api.agent_identity import configure_agent_identity

    configure_agent_identity(world.composed.app, None)
    assert world.put(FINANCE, STEWARD, body()).status_code == 503
    assert world.put(FINANCE, VIEWER, body()).status_code == 403
