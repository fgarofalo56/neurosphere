"""The ``agent_matcher`` component of the data builder (PRP-72 item 4): composed from the search,
the catalog graph, the aggregate reader and the feedback store; ``disabled`` with a reason code the
route answers with when search or the catalog is missing; never blocks readiness."""

import asyncio
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from authz.authz_helpers import FakeClock  # pyright: ignore[reportMissingImports]
from neurosphere_api.recommendations.match_composition import SyncedAgentMatcher
from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.catalog.repo import InMemoryCatalogRepository
from neurosphere_core.catalog.repo.documents import parse_entity
from neurosphere_core.recommendations.matching import (
    CosmosFeedbackStore,
    InMemoryFeedbackStore,
)
from neurosphere_core.scope import IdentityScope
from runtime_api.runtime_helpers import (  # pyright: ignore[reportMissingImports]
    CUSTOMER,
    FINANCE,
    Composed,
    FakeCosmosClient,
    compose,
    configure_auth_env,
    configured_overrides,
)
from runtime_data.data_helpers import (  # pyright: ignore[reportMissingImports]
    EmptyContainer,
    builders_with_real_data,
    data_overrides,
)

HR = f"commercial:{CUSTOMER}:catalog:domain:hr"
_EXAMPLES = Path(__file__).resolve().parents[4] / "packages/contracts/schemas/catalog/v1/examples"
MATCH_URL = f"/api/v1/recommendations/domains/{FINANCE}/match"
SUPPORT_BOT = f"commercial:{CUSTOMER}:foundry:agent:support-bot"


def _agent(name: str, domain: str, text: str) -> Any:
    raw = json.loads((_EXAMPLES / "valid/agent.minimal-and-typical.json").read_text("utf-8"))
    raw.update(
        id=f"commercial:{CUSTOMER}:foundry:agent:{name}",
        customer_id=CUSTOMER,
        domain_id=domain,
        current_version_id=None,
        external_agent_id=None,
        display_name=text,
        description=text,
        tags=["support"],
        capabilities=["summarization"],
        attributes=None,
        version=1,
        etag="caller-etag",
    )
    return parse_entity(raw)


def _steward(domains: list[str]) -> IdentityScope:
    payload: dict[str, Any] = {
        "schema_version": "1.0.0",
        "cloud": "commercial",
        "customer_id": CUSTOMER,
        "principal": {
            "principal_id": f"commercial:{CUSTOMER}:idp:person:seed",
            "principal_pseudonym": "p-0001",
            "principal_kind": "user",
        },
        "roles": [{"role": "domain_steward", "domain_ids": domains}],
        "allowed_domains": domains,
        "allowed_resources": [],
        "policy_version": "v1",
        "derived_at": "2026-01-01T00:00:00Z",
        "scope_hash": "sha256:" + hashlib.sha256(b"seed").hexdigest(),
    }
    return IdentityScope._from_verified_contract(  # pyright: ignore[reportPrivateUsage]
        ContractScope.model_validate(payload)
    )


def _compose(
    monkeypatch: pytest.MonkeyPatch,
    env: dict[str, str],
    *,
    feedback: bool = True,
    without: tuple[str, ...] = (),
) -> Composed:
    configure_auth_env(monkeypatch)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    clock = FakeClock()
    overrides = data_overrides(clock, without=without)
    if feedback:
        overrides = replace(
            overrides,
            backends={
                **overrides.backends,
                "recommendation_feedback_store": InMemoryFeedbackStore(),
            },
        )
    repo = overrides.backends.get("catalog_repository")
    if isinstance(repo, InMemoryCatalogRepository):
        for name, domain, text in (
            ("support-bot", FINANCE, "summarize support ticket conversations"),
            ("hr-bot", HR, "summarize support ticket conversations too"),
        ):
            asyncio.run(repo.create_entity(_steward([domain]), _agent(name, domain, text)))
    return compose(overrides, builders=builders_with_real_data(), clock=clock)


def _match(composed: Composed) -> Any:
    body = {"schema_version": "1.0.0", "task_text": "summarize support ticket"}
    with composed.client() as client:
        return client.post(MATCH_URL, json=body, headers=composed.auth())


def test_without_a_search_provider_the_matcher_is_disabled_with_a_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    composed = _compose(monkeypatch, {})
    assert composed.registry.get("agent_matcher").state == "disabled"
    assert composed.registry.ready  # optional: never blocks readiness
    state = composed.app.state
    assert state.agent_matcher is None
    assert state.agent_matcher_unavailable == "search_unavailable"
    response = _match(composed)
    assert response.status_code == 409
    assert response.json()["code"] == "capability_unavailable"
    assert "search_unavailable" in response.text


def test_without_the_catalog_the_matcher_is_disabled_with_a_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    composed = _compose(monkeypatch, {"NS_SEARCH_PROVIDER": "fixture"}, without=("catalog",))
    assert composed.registry.get("catalog").state == "failed"
    assert composed.registry.get("agent_matcher").state == "disabled"
    assert composed.app.state.agent_matcher_unavailable == "catalog_unavailable"


def test_with_the_fixture_search_the_matcher_is_composed_and_scoped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    composed = _compose(monkeypatch, {"NS_SEARCH_PROVIDER": "fixture"})
    assert composed.registry.get("agent_matcher").state == "ok"
    assert composed.registry.ready
    state = composed.app.state
    assert isinstance(state.agent_matcher, SyncedAgentMatcher)
    assert isinstance(state.recommendation_feedback_store, InMemoryFeedbackStore)
    assert state.agent_matcher_unavailable is None
    response = _match(composed)
    assert response.status_code == 200, response.text
    candidates = response.json()["match"]["candidates"]
    assert [c["entity_id"] for c in candidates] == [SUPPORT_BOT]  # the hr agent is out of scope


def test_feedback_over_the_composed_app_is_audited_and_counted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    composed = _compose(monkeypatch, {"NS_SEARCH_PROVIDER": "fixture"})
    match_id = _match(composed).json()["match"]["match_id"]
    body = {
        "schema_version": "1.0.0",
        "match_id": match_id,
        "entity_id": SUPPORT_BOT,
        "decision": "accepted",
    }
    with composed.client() as client:
        sent = client.post(f"{MATCH_URL}/feedback", json=body, headers=composed.auth())
        assert sent.status_code == 202, sent.text
        stats = client.get(f"{MATCH_URL}/metrics", headers=composed.auth()).json()
    assert (stats["matches"], stats["accepts"], stats["acceptance_rate"]) == (1, 1, 1.0)


def test_without_a_feedback_override_the_store_is_the_cosmos_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_auth_env(monkeypatch)
    monkeypatch.setenv("NS_SEARCH_PROVIDER", "fixture")
    clock = FakeClock()
    overrides = configured_overrides(
        clock, cosmos_client_factory=FakeCosmosClient, blob_client=EmptyContainer()
    )
    composed = compose(overrides, builders=builders_with_real_data(), clock=clock)
    assert composed.registry.get("agent_matcher").state == "ok"
    assert isinstance(composed.app.state.recommendation_feedback_store, CosmosFeedbackStore)


def test_a_missing_cosmos_client_fails_only_the_matcher_with_its_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    composed = _compose(monkeypatch, {"NS_SEARCH_PROVIDER": "fixture"}, feedback=False)
    status = composed.registry.get("agent_matcher")
    assert (status.state, status.reason) == ("failed", "cosmos_unconfigured")
    assert composed.registry.get("catalog").state == "ok"


def test_invalid_match_settings_are_a_reason_code(monkeypatch: pytest.MonkeyPatch) -> None:
    composed = _compose(
        monkeypatch, {"NS_SEARCH_PROVIDER": "fixture", "NS_MATCH_FEEDBACK_BOUND": "7"}
    )
    status = composed.registry.get("agent_matcher")
    assert (status.state, status.reason) == ("failed", "match_settings_invalid")
    assert "7" not in (status.reason or "")


def test_match_settings_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    composed = _compose(
        monkeypatch,
        {
            "NS_SEARCH_PROVIDER": "fixture",
            "NS_MATCH_CANDIDATE_CAP": "5",
            "NS_MATCH_MIN_PRINCIPALS": "2",
        },
    )
    assert composed.registry.get("agent_matcher").state == "ok"
    settings = composed.app.state.agent_matcher._settings  # pyright: ignore[reportPrivateUsage]
    assert (settings.candidate_cap, settings.min_principals) == (5, 2)
