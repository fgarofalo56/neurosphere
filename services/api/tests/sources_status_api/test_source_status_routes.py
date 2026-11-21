"""PRP-139 item 3: the ``sources_status`` builder and both routes, composed over in-memory stores.

Composes the REAL authz builder and the REAL ``sources_status`` builder (no Cosmos). Principals come
from the connector admin harness: a customer-level admin, a domain admin and an analyst.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest
from authz.authz_helpers import (  # pyright: ignore[reportMissingImports]
    FakeClock,
    make_validator,
)
from connectors_harness import (  # pyright: ignore[reportMissingImports]
    ANALYST,
    CUSTOMER_ADMIN,
    DOMAIN,
    DOMAIN_ADMIN,
    configure_env,
    gateway_body,
    seeded_policies,
)
from neurosphere_api.runtime import CompositionOverrides
from neurosphere_api.runtime.builders import AUDIT_REPOSITORY, BuildContext, BuilderSpec
from neurosphere_api.runtime.builders import authz as authz_builder
from neurosphere_api.runtime.builders import sources_status as builder
from neurosphere_core.admin import InMemoryAdminConfigRepository
from neurosphere_core.audit import AuditRepository, InMemoryAuditStore
from neurosphere_core.auth.revocation import InMemoryRevocationStore
from neurosphere_core.sources_status import ConnectorRunStatus, InMemorySourceStatusRepository
from runtime_api.runtime_helpers import (  # pyright: ignore[reportMissingImports]
    Composed,
    compose,
    composed_principal_id,
)

USER = "/api/v1/sources/status"
ADMIN = "/api/v1/admin/sources/status"
NOW = datetime(2026, 11, 21, 10, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _auth(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_env(monkeypatch)


class World:
    def __init__(self, composed: Composed, statuses: InMemorySourceStatusRepository) -> None:
        self.composed = composed
        self.statuses = statuses

    def get(self, path: str, who: str) -> Any:
        return self.composed.client().get(path, headers=self.composed.auth(who))


def build(**backends: object) -> World:
    clock = FakeClock()
    statuses = InMemorySourceStatusRepository()
    overrides = CompositionOverrides(
        authenticator=make_validator(clock),
        policy_repository=seeded_policies(),
        revocation_store=InMemoryRevocationStore(clock=clock),
        clock=clock,
        backends={"source_status_repository": statuses, **backends},
    )
    audit = AuditRepository(InMemoryAuditStore())

    def build_data(ctx: BuildContext) -> None:
        ctx.publish(AUDIT_REPOSITORY, audit)
        ctx.ok("audit")

    chain = (
        authz_builder.BUILDER,
        BuilderSpec("stub-data", ("audit",), build_data),
        builder.BUILDER,
    )
    return World(compose(overrides, builders=chain, clock=clock), statuses)


def record(world: World, **over: Any) -> None:
    body: dict[str, Any] = {
        "kind": "gateway_poll",
        "state": "ok",
        "last_attempt_at": NOW,
        "last_success_at": NOW,
        "counts": {"gateways_polled": 2},
    }
    body.update(over)

    asyncio.run(world.statuses.record("contoso", ConnectorRunStatus.model_validate(body)))


def test_the_component_is_ok_when_a_store_is_available() -> None:
    world = build()
    assert world.composed.registry.get("sources_status").state == "ok"


def test_a_bad_override_disables_the_component_and_the_routes_answer_503() -> None:
    world = build(source_status_repository=object())
    assert world.composed.registry.get("sources_status").state == "disabled"
    assert world.get(USER, ANALYST).status_code == 503
    assert world.get(ADMIN, CUSTOMER_ADMIN).status_code == 503


def test_an_empty_estate_is_four_not_connected_sources_in_order() -> None:
    world = build()
    body = world.get(USER, ANALYST).json()
    assert [s["source"] for s in body["sources"]] == [
        "foundry",
        "apim_gateway",
        "billing",
        "azure_monitor_telemetry",
    ]
    assert {s["state"] for s in body["sources"]} == {"not_connected"}
    assert [s["available"] for s in body["sources"]] == [True, True, True, False]
    assert all(s["last_success_at"] is None for s in body["sources"])


def test_the_user_route_returns_states_and_times_only() -> None:
    world = build()
    record(world)
    body = world.get(USER, ANALYST).json()
    assert body["sources"][1] == {
        "source": "apim_gateway",
        "state": "connected",
        "last_success_at": "2026-11-21T10:00:00Z",
        "available": True,
    }
    assert set(body) == {"sources"}
    assert all(
        set(s) == {"source", "state", "last_success_at", "available"} for s in body["sources"]
    )


def test_a_domain_admin_reads_the_user_route_and_gets_403_on_the_admin_route() -> None:
    world = build()
    assert world.get(USER, DOMAIN_ADMIN).status_code == 200
    denied = world.get(ADMIN, DOMAIN_ADMIN)
    assert denied.status_code == 403
    assert denied.json()["reason"] == "customer_scope_required"


def test_the_admin_route_adds_reasons_and_connector_counts() -> None:
    world = build()
    record(world, state="failed", reason="source_access_denied", counts={"gateways_failed": 1})
    body = world.get(ADMIN, CUSTOMER_ADMIN).json()
    gateway = body["sources"][1]
    assert (gateway["state"], gateway["reason"]) == ("failing", "source_access_denied")
    assert body["sources"][3]["reason"] == "not_available_in_release"
    assert body["connectors"][1] == {
        "kind": "gateway_poll",
        "state": "failed",
        "reason": "source_access_denied",
        "last_success_at": "2026-11-21T10:00:00Z",
        "last_attempt_at": "2026-11-21T10:00:00Z",
        "counts": {"gateways_failed": 1},
    }
    assert body["connectors"][0]["state"] == "not_configured"


def test_a_stored_enabled_config_without_a_run_is_awaiting_the_first_run() -> None:
    repository = InMemoryAdminConfigRepository(cloud="commercial")
    world = build(admin_config_repository=repository)

    asyncio.run(
        repository.create(
            "contoso",
            "connector_config",
            "gateway-main",
            gateway_body(domain_ids=[DOMAIN]),
            updated_by=str(composed_principal_id(CUSTOMER_ADMIN)),
        )
    )
    admin = world.get(ADMIN, CUSTOMER_ADMIN).json()
    assert admin["sources"][1]["state"] == "not_connected"
    assert admin["sources"][1]["reason"] == "awaiting_first_run"
    assert world.get(USER, ANALYST).json()["sources"][1]["state"] == "not_connected"


def test_no_token_is_401() -> None:
    world = build()
    client = world.composed.client()
    assert client.get(USER).status_code == 401
    assert client.get(ADMIN).status_code == 401
