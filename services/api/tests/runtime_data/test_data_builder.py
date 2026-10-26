"""The data builder: every component ok with fakes, routes answer, one gap names one component."""

from __future__ import annotations

from typing import Any

import pytest
from authz.authz_helpers import FakeClock  # pyright: ignore[reportMissingImports]
from neurosphere_api.federation.service import FederationState
from neurosphere_api.runtime.builders import (
    AGGREGATE_READER,
    AUDIT_REPOSITORY,
    CATALOG_REPOSITORY,
    HITL_SERVICE,
    BuilderSpec,
    data,
)
from neurosphere_core.audit import AuditRepository
from neurosphere_core.hitl import HitlService
from runtime_api.runtime_helpers import (  # pyright: ignore[reportMissingImports]
    FINANCE,
    Composed,
    FakeCosmosClient,
    compose,
    configure_auth_env,
    configured_overrides,
)

from .data_helpers import builders_with_real_data, data_overrides

ROUTES = (
    f"/api/v1/dashboards/domains/{FINANCE}/cost?days=7",
    f"/api/v1/map/domains/{FINANCE}/viewport",
    f"/api/v1/replay/domains/{FINANCE}/traces",
    "/api/v1/federation/summary",
    "/api/v1/federation/cell-summary",
    f"/api/v1/finops/domains/{FINANCE}/forecast",
    f"/api/v1/evaluation/domains/{FINANCE}/quality",
    f"/api/v1/recommendations/domains/{FINANCE}",
    f"/api/v1/reconciliation/domains/{FINANCE}",
    "/api/v1/catalog/entities",
    "/api/v1/audit/chains/chain-1/records",
)

SINGLE_GAPS = ("ledger", "evaluation", "recommendations")


def _compose(monkeypatch: pytest.MonkeyPatch, **kwargs: Any) -> Composed:
    configure_auth_env(monkeypatch)
    clock = FakeClock()
    return compose(data_overrides(clock, **kwargs), builders=builders_with_real_data(), clock=clock)


def _not_ok(composed: Composed) -> dict[str, str]:
    return {
        name: composed.registry.get(name).state
        for name in data.COMPONENTS
        if composed.registry.get(name).state != "ok"
    }


def test_every_data_component_is_ok_with_fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    composed = _compose(monkeypatch)
    assert _not_ok(composed) == {}
    assert composed.registry.ready


def test_state_keys_and_published_objects(monkeypatch: pytest.MonkeyPatch) -> None:
    composed = _compose(monkeypatch)
    state = composed.app.state
    for key in (
        "catalog_repository",
        "catalog_graph",
        "catalog_review_queue",
        "catalog_clock",
        "aggregate_reader",
        "ledger_store",
        "federation",
        "evaluation_store",
        "evaluation_pilot_dataset_ids",
        "recommendation_store",
        "review_router",
        "audit_repository",
        "trace_reader",
        "replay_payload_policy",
        "map_pseudonymizer",
        "map_viewport_limits",
        "realtime",
    ):
        assert getattr(state, key, None) is not None, key
    federation = state.federation
    assert isinstance(federation, FederationState)
    assert federation.local_cell is not None


@pytest.mark.parametrize("route", ROUTES)
def test_routes_are_not_unconfigured(monkeypatch: pytest.MonkeyPatch, route: str) -> None:
    composed = _compose(monkeypatch)
    with composed.client() as client:
        response = client.get(route, headers=composed.auth())
    assert response.status_code != 503, response.text
    assert response.status_code < 500, response.text


def test_the_four_shared_objects_are_published(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_auth_env(monkeypatch)
    seen: dict[str, object] = {}

    def probe(ctx: Any) -> None:
        seen["audit"] = ctx.maybe_shared(AUDIT_REPOSITORY)
        seen["hitl"] = ctx.maybe_shared(HITL_SERVICE)
        seen["aggregates"] = ctx.maybe_shared(AGGREGATE_READER)
        seen["catalog"] = ctx.maybe_shared(CATALOG_REPOSITORY)
        ctx.ok("hitl")
        ctx.ok("action_plane")
        ctx.ok("reports")
        ctx.ok("mcp_admin")

    builders = tuple(
        BuilderSpec("planes", spec.components, probe) if spec.name == "stub-planes" else spec
        for spec in builders_with_real_data()
    )
    clock = FakeClock()
    composed = compose(data_overrides(clock), builders=builders, clock=clock)
    assert isinstance(seen["audit"], AuditRepository)
    assert isinstance(seen["hitl"], HitlService)
    assert seen["audit"] is composed.app.state.audit_repository
    assert seen["aggregates"] is composed.app.state.aggregate_reader
    assert seen["catalog"] is composed.app.state.catalog_repository


@pytest.mark.parametrize("component", SINGLE_GAPS)
def test_one_missing_dependency_names_exactly_that_component(
    monkeypatch: pytest.MonkeyPatch, component: str
) -> None:
    composed = _compose(monkeypatch, without=(component,))
    assert _not_ok(composed) == {component: "failed"}
    assert composed.registry.get(component).reason == "cosmos_unconfigured"
    with composed.client() as client:
        body = client.get("/readyz").json()
    failing = sorted(k for k, v in body["dependencies"].items() if v != "ok")
    assert failing == ["composition", f"composition.{component}.cosmos_unconfigured"]


def test_missing_audit_also_names_the_review_router(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_auth_env(monkeypatch)
    clock = FakeClock()
    overrides = data_overrides(clock, without=("audit",))
    backends = {k: v for k, v in overrides.backends.items() if k != "hitl_service"}
    overrides = configured_overrides(clock, backends=backends, blob_client=overrides.blob_client)
    composed = compose(overrides, builders=builders_with_real_data(), clock=clock)
    assert _not_ok(composed) == {"audit": "failed", "review_router": "failed"}


def test_invalid_archive_settings_name_only_replay(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_auth_env(monkeypatch)
    monkeypatch.setenv("NS_ARCHIVE_CONTAINER", "x")  # below the 3-character minimum
    clock = FakeClock()
    composed = compose(
        data_overrides(clock, without=("replay",)),
        builders=builders_with_real_data(),
        clock=clock,
    )
    assert _not_ok(composed) == {"replay": "failed"}
    assert composed.registry.get("replay").reason == "archive_settings_invalid"


def test_real_cosmos_stores_build_over_a_cosmos_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """No backend overrides: every store is the Cosmos one, built lazily over the fake client."""
    from neurosphere_core.aggregates.cosmos import CosmosAggregateStore
    from neurosphere_core.audit import AuditRepository
    from neurosphere_core.catalog.repo.cosmos import CosmosCatalogRepository
    from neurosphere_core.catalog.review_queue_cosmos import CosmosReviewQueue
    from neurosphere_core.evaluation.cosmos_store import CosmosEvaluationStore
    from neurosphere_core.ledger.cosmos import CosmosLedgerStore
    from neurosphere_core.recommendations.cosmos_store import CosmosRecommendationStore

    from .data_helpers import EmptyContainer

    configure_auth_env(monkeypatch)
    clock = FakeClock()
    overrides = configured_overrides(
        clock, cosmos_client_factory=FakeCosmosClient, blob_client=EmptyContainer()
    )
    composed = compose(overrides, builders=builders_with_real_data(), clock=clock)
    assert _not_ok(composed) == {}
    state = composed.app.state
    assert isinstance(state.catalog_repository, CosmosCatalogRepository)
    assert isinstance(state.catalog_review_queue, CosmosReviewQueue)
    assert isinstance(state.aggregate_reader, CosmosAggregateStore)
    assert isinstance(state.ledger_store, CosmosLedgerStore)
    assert isinstance(state.evaluation_store, CosmosEvaluationStore)
    assert isinstance(state.recommendation_store, CosmosRecommendationStore)
    assert isinstance(state.audit_repository, AuditRepository)


def test_a_wrongly_typed_backend_is_refused_by_name(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_auth_env(monkeypatch)
    clock = FakeClock()
    overrides = data_overrides(clock)
    backends = {**overrides.backends, "ledger_store": object()}
    overrides = configured_overrides(clock, backends=backends, blob_client=overrides.blob_client)
    composed = compose(overrides, builders=builders_with_real_data(), clock=clock)
    assert composed.registry.get("ledger").reason == "ledger_store_override_invalid"
