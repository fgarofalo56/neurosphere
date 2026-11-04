"""``NS_SEARCH_PROVIDER`` composition: fixture index, Azure capability gate, unset 503."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from authz.authz_helpers import FakeClock  # pyright: ignore[reportMissingImports]
from neurosphere_api.runtime.builders.search import SearchRuntime
from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.catalog.repo import InMemoryCatalogRepository
from neurosphere_core.catalog.repo.documents import parse_entity
from neurosphere_core.scope import IdentityScope
from runtime_api.runtime_helpers import (  # pyright: ignore[reportMissingImports]
    CUSTOMER,
    FINANCE,
    Composed,
    compose,
    configure_auth_env,
)

from .data_helpers import builders_with_real_data, data_overrides

HR = f"commercial:{CUSTOMER}:catalog:domain:hr"
_EXAMPLES = Path(__file__).resolve().parents[4] / "packages/contracts/schemas/catalog/v1/examples"
SEARCH_URL = "/api/v1/catalog/search"
BODY = {"term": "payroll", "budget": {"timeout_ms": 5000, "limit": 50, "max_depth": 0}}


def _agent(name: str, domain: str, text: str) -> Any:
    raw = json.loads((_EXAMPLES / "valid/agent.minimal-and-typical.json").read_text("utf-8"))
    raw.update(
        id=f"commercial:{CUSTOMER}:foundry:agent:{name}",
        customer_id=CUSTOMER,
        domain_id=domain,
        current_version_id=None,
        external_agent_id=None,
        display_name=text,
        attributes=None,
        version=1,
        etag="caller-etag",
    )
    return parse_entity(raw)


def _seeder(domains: list[str]) -> IdentityScope:
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


def _seed(repo: InMemoryCatalogRepository, name: str, domain: str, text: str) -> None:
    asyncio.run(repo.create_entity(_seeder([domain]), _agent(name, domain, text)))


class FakeAzure:
    """Search + upload slice of the Azure client; records every call."""

    def __init__(self) -> None:
        self.searches: list[dict[str, Any]] = []
        self.uploads: list[list[dict[str, Any]]] = []

    async def search(self, search_text: str | None = None, **kwargs: Any) -> Any:
        self.searches.append({"text": search_text, **kwargs})
        return _EmptyPager()

    async def merge_or_upload_documents(self, documents: list[dict[str, Any]], **_: Any) -> Any:
        self.uploads.append(documents)
        return [type("R", (), {"succeeded": True})() for _ in documents]


class _EmptyPager:
    def __aiter__(self) -> _EmptyPager:
        return self

    async def __anext__(self) -> Any:
        raise StopAsyncIteration

    async def get_count(self) -> int:
        return 0


def _compose(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str], azure: FakeAzure | None = None
) -> tuple[Composed, InMemoryCatalogRepository]:
    configure_auth_env(monkeypatch)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    clock = FakeClock()
    overrides = data_overrides(clock)
    repo = overrides.backends["catalog_repository"]
    assert isinstance(repo, InMemoryCatalogRepository)
    if azure is not None:
        overrides = replace(overrides, backends={**overrides.backends, "search_client": azure})
    _seed(repo, "support-bot", FINANCE, "payroll triage helper")
    _seed(repo, "hr-bot", HR, "payroll secrets agent")
    return compose(overrides, builders=builders_with_real_data(), clock=clock), repo


def _ids(composed: Composed) -> list[str]:
    with composed.client() as client:
        response = client.post(SEARCH_URL, json=BODY, headers=composed.auth())
    assert response.status_code == 200, response.text
    return [n["id"] for n in response.json()["nodes"]]


def test_fixture_search_returns_matches_and_never_the_restricted_domain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    composed, _ = _compose(monkeypatch, {"NS_SEARCH_PROVIDER": "fixture"})
    assert composed.registry.get("catalog").state == "ok"
    assert _ids(composed) == [f"commercial:{CUSTOMER}:foundry:agent:support-bot"]


def test_catalog_writes_are_picked_up_after_invalidate(monkeypatch: pytest.MonkeyPatch) -> None:
    composed, repo = _compose(
        monkeypatch, {"NS_SEARCH_PROVIDER": "fixture", "NS_SEARCH_REFRESH_SECONDS": "3600"}
    )
    first = _ids(composed)
    _seed(repo, "payroll-two", FINANCE, "payroll second finance agent")
    assert _ids(composed) == first  # inside the refresh window: not yet indexed
    runtime = composed.app.state.search_runtime
    assert isinstance(runtime, SearchRuntime)
    runtime.invalidate()
    assert len(_ids(composed)) == len(first) + 1


def test_unset_provider_keeps_the_503(monkeypatch: pytest.MonkeyPatch) -> None:
    composed, _ = _compose(monkeypatch, {})
    assert getattr(composed.app.state, "search_runtime", None) is None
    with composed.client() as client:
        response = client.post(SEARCH_URL, json=BODY, headers=composed.auth())
    assert response.status_code == 503
    assert "search_unavailable" in response.text


def test_invalid_provider_names_only_the_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    composed, _ = _compose(monkeypatch, {"NS_SEARCH_PROVIDER": "elastic"})
    assert composed.registry.get("catalog").reason == "search_settings_invalid"


def test_azure_in_an_unsupported_region_is_disabled_and_makes_no_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    azure = FakeAzure()
    composed, _ = _compose(
        monkeypatch,
        {"NS_SEARCH_PROVIDER": "azure", "NS_SEARCH_REGION": "marscentral"},
        azure,
    )
    runtime = composed.app.state.search_runtime
    assert isinstance(runtime, SearchRuntime)
    assert runtime.azure_enabled is False
    assert runtime.disabled_reason == "not_verified"
    # the in-process index still answers, scoped; Azure was never contacted
    assert _ids(composed) == [f"commercial:{CUSTOMER}:foundry:agent:support-bot"]
    assert azure.searches == [] and azure.uploads == []


def test_azure_without_a_region_or_service_is_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    composed, _ = _compose(monkeypatch, {"NS_SEARCH_PROVIDER": "azure"})
    assert composed.app.state.search_runtime.disabled_reason == "search_region_missing"
    composed, _ = _compose(
        monkeypatch, {"NS_SEARCH_PROVIDER": "azure", "NS_SEARCH_REGION": "eastus"}
    )
    assert composed.app.state.search_runtime.disabled_reason == "search_service_missing"


def test_azure_supported_region_queries_azure_with_a_server_side_scope_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    azure = FakeAzure()
    composed, _ = _compose(
        monkeypatch, {"NS_SEARCH_PROVIDER": "azure", "NS_SEARCH_REGION": "eastus"}, azure
    )
    runtime = composed.app.state.search_runtime
    assert runtime.azure_enabled is True and runtime.disabled_reason is None
    assert _ids(composed) == []  # the fake index is empty; what matters is what was sent
    assert len(azure.searches) == 1
    odata = azure.searches[0]["filter"]
    assert FINANCE in odata and HR not in odata
    # the indexer pushed only the in-scope entity
    uploaded = [d["id"] for batch in azure.uploads for d in batch]
    assert uploaded == [f"commercial:{CUSTOMER}:foundry:agent:support-bot"]
